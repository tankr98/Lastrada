"""One bounded worker subprocess; invoked by the private Cloud Run service."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time


STAGE_LABELS = {
    "loading_audio": "Loading uploaded audio",
    "decoding_audio": "Preparing the recordings",
    "preparing_matcher": "Preparing Sony SampleID",
    "matching": "Finding and refining sample timestamps",
    "grouping": "Grouping repeated passages",
    "stem_analysis": "Separating stems and checking like-for-like matches",
    "finalizing": "Saving the completed analysis",
    "completed": "Analysis complete",
}

STAGE_ORDER = {
    "loading_audio": 1,
    "decoding_audio": 2,
    "preparing_matcher": 3,
    "matching": 4,
    "grouping": 5,
    "stem_analysis": 6,
    "finalizing": 7,
    "completed": 8,
}

RESUMABLE_STAGES = {"stem_analysis", "finalizing"}


def _stage_rank(stage):
    return STAGE_ORDER.get(stage, -1)


def _merge_progress(current, incoming):
    """Keep progress monotonic across stale responses and worker retries."""

    current = dict(current or {})
    incoming = dict(incoming or {})
    current_stage = current.get("stage")
    incoming_stage = incoming.get("stage")
    current_rank = _stage_rank(current_stage)
    incoming_rank = _stage_rank(incoming_stage)

    if current_rank > incoming_rank:
        return current, False
    if current_rank == incoming_rank and current_rank >= 0:
        current_updated = float(current.get("updated") or 0)
        incoming_updated = float(incoming.get("updated") or 0)
        if current_updated > incoming_updated:
            return current, False
        incoming["percent"] = max(
            int(current.get("percent") or 0),
            int(incoming.get("percent") or 0),
        )
        if current.get("stage_started"):
            incoming["stage_started"] = current["stage_started"]
        incoming["restart_count"] = max(
            int(current.get("restart_count") or 0),
            int(incoming.get("restart_count") or 0),
        )
    return incoming, True


def _resumable_stage(state):
    progress = state.get("instrument_progress") or {}
    stage = progress.get("stage")
    if state.get("status") == "running" and stage in RESUMABLE_STAGES:
        return stage
    return None


def checkpoint():
    import requests

    destination = Path(
        os.getenv("LASTRADA_MODEL_PATH", "/tmp/lastrada/sampleid-best.ckpt")
    )
    expected = os.getenv(
        "LASTRADA_SAMPLEID_SHA256",
        "a6026b65b6516569aa7a6c7f967e2ebe31dcb123af53560b122d87d72ddf4693",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        url = os.environ["LASTRADA_SAMPLEID_CHECKPOINT_URL"]
        if not url.startswith("https://"):
            raise ValueError("Model downloads require HTTPS")
        partial = destination.with_suffix(".partial")
        try:
            with requests.get(url, stream=True, timeout=(15, 300)) as response:
                response.raise_for_status()
                with partial.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        output.write(chunk)
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with destination.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        destination.unlink(missing_ok=True)
        raise ValueError("Model integrity verification failed")
    return destination


def execute(owner, analysis_id, operation, task_id):
    from google.api_core.exceptions import NotFound, PreconditionFailed
    from lastrada.web.cloud import Cases, prefix
    from lastrada.audio.io import decode
    from lastrada.web.profile import analysis_settings, PROFILE
    from lastrada.pipeline import analyze_pair
    from lastrada.schemas.models import Intake, Work, Analysis
    from lastrada.reporting.comparison import spectral_view, comparison_figure
    from lastrada.recognition.sampleid_adapter import SampleIDAdapter
    from lastrada.separation.grouped_occurrences import run_grouped_instruments
    from lastrada.separation.occurrences import (
        instrument_progress,
        run_occurrence_instruments,
    )

    repo = Cases()
    root = prefix(owner, analysis_id)
    state, _generation = repo.read(root + "/case.json")
    if state.get("task_id") != task_id or state["status"] == "completed":
        return

    previous_progress = state.get("instrument_progress") or {}
    resume_stage = _resumable_stage(state) if operation == "analyze" else None
    restart_count = int(previous_progress.get("restart_count") or 0)
    resume_result = None
    if resume_stage:
        try:
            data, _ = repo.read(root + "/result.json")
            candidate = Analysis.model_validate(data)
            if (
                candidate.methods.get("stem_strategy")
                == "integrated_grouped_representatives_same_stem"
            ):
                resume_result = candidate
                restart_count += 1
        except (NotFound, ValueError):
            resume_stage = None

    stage_state = {
        "name": previous_progress.get("stage"),
        "started": float(previous_progress.get("stage_started") or time.time()),
    }

    def publish_progress(
        stage,
        percent,
        detail,
        *,
        partial=None,
        counts=None,
    ):
        """Persist a human-readable stage without exposing a partial result."""

        now = time.time()
        if stage_state["name"] != stage:
            stage_state.update(name=stage, started=now)
        progress = dict(
            counts or (instrument_progress(partial) if partial is not None else {})
        )
        progress.update(
            stage=stage,
            label=STAGE_LABELS[stage],
            percent=max(0, min(100, int(percent))),
            detail=detail,
            updated=now,
            stage_started=stage_state["started"],
            restart_count=restart_count,
        )
        for attempt in range(3):
            current, revision = repo.read(root + "/case.json")
            if current.get("task_id") != task_id or current.get("status") == "completed":
                return False
            merged, accepted = _merge_progress(
                current.get("instrument_progress"),
                progress,
            )
            if not accepted:
                return False
            if partial is not None:
                partial.methods["web_profile"] = PROFILE["name"]
                repo.write(
                    root + "/result.json",
                    partial.model_dump(mode="json"),
                )
            current.update(
                status="running",
                started=current.get("started", now),
                instrument_progress=merged,
            )
            try:
                repo.write(root + "/case.json", current, revision)
                return True
            except PreconditionFailed:
                if attempt == 2:
                    raise
        return False

    publish_progress(
        "loading_audio",
        8,
        "The worker has started and is downloading the two uploaded tracks.",
    )

    with tempfile.TemporaryDirectory() as folder:
        paths = {}
        for role in ("original", "new"):
            paths[role] = Path(folder) / role
            repo.download(root + f"/{role}", paths[role])

        publish_progress(
            "decoding_audio",
            14,
            "Both files are available. The recordings are being decoded and normalized.",
        )
        original = decode(paths["original"].read_bytes())
        new = decode(paths["new"].read_bytes())
        settings = analysis_settings()

        def save_instruments(partial):
            """Persist grouped stem progress without releasing the review page."""

            counts = instrument_progress(partial)
            total = max(1, counts["total"])
            percent = 62 + round(33 * counts["finished"] / total)
            publish_progress(
                "stem_analysis",
                percent,
                (
                    "Grouped Demucs and same-stem DTW are running. "
                    f"{counts['finished']} of {counts['total']} timestamp rows are finalized."
                ),
                partial=partial,
                counts=counts,
            )

        def complete_grouped_stems(result, *, resumed=False):
            if not settings.stem_group_enabled:
                result.methods["instruments"] = (
                    "not_run: grouped stem analysis disabled"
                )
                return result
            try:
                detail = (
                    "The analysis worker restarted during Demucs and safely resumed from saved grouped progress."
                    if resumed
                    else "Representative occurrences are being separated with Demucs before like-for-like stem DTW."
                )
                current_percent = int(previous_progress.get("percent") or 62)
                publish_progress(
                    "stem_analysis",
                    max(62, current_percent),
                    detail,
                    partial=result,
                )
                return run_grouped_instruments(
                    result,
                    original,
                    new,
                    settings,
                    on_progress=save_instruments,
                    budget_seconds=1200,
                    max_new_checks=100,
                )
            except (OSError, RuntimeError, ValueError) as error:
                result.methods["instruments"] = (
                    "unavailable: integrated grouped stem analysis failed "
                    f"({type(error).__name__}: {error})"
                )
                result.warnings.append(
                    "Grouped Demucs and same-stem DTW could not finish. "
                    "Sony and full-mix timing evidence is preserved."
                )
                return result

        if operation == "stems":
            # Compatibility path for analyses created before the integrated
            # pipeline. New analyses already contain grouped stem evidence and
            # never launch this endpoint after the review page loads.
            publish_progress(
                "stem_analysis",
                62,
                "A legacy saved analysis is completing its remaining instrument checks.",
            )
            data, _ = repo.read(root + "/result.json")
            result = Analysis.model_validate(data)
            result = run_occurrence_instruments(
                result,
                original,
                new,
                settings,
                on_progress=save_instruments,
            )
        elif resume_result is not None:
            result = resume_result
            if resume_stage == "stem_analysis":
                result = complete_grouped_stems(result, resumed=True)
        else:
            credits = state["credits"]
            intake = Intake(
                case_id=analysis_id,
                original_work=Work(
                    title=credits["original_title"],
                    artist=credits["original_artist"],
                    audio_file=state["uploads"]["original"]["name"],
                ),
                new_work=Work(
                    title=credits["new_title"],
                    artist=credits["new_artist"],
                    audio_file=state["uploads"]["new"]["name"],
                ),
                analysis_scope=["master"],
            )
            adapter, warning, matcher_failure = None, None, None
            publish_progress(
                "preparing_matcher",
                20,
                "The Sony SampleID checkpoint is being prepared and verified.",
            )
            try:
                adapter = SampleIDAdapter(
                    checkpoint(),
                    os.getenv("LASTRADA_CACHE_DIR", "/tmp/lastrada/cache")
                    + "/sampleid",
                    batch_size=2,
                )
            except Exception as error:
                matcher_failure = (
                    "unavailable: matcher preparation failed "
                    f"({type(error).__name__})"
                )
                warning = (
                    "Sony matching is unavailable; displayed times are PF-NMF "
                    "fallback estimates. Original-track positions may be unknown."
                )

            # Sony and full-mix DTW establish candidate timestamps first. The
            # grouped Demucs stage below validates representative occurrences
            # without changing the Sony candidate-generation behavior.
            publish_progress(
                "matching",
                30,
                "Sony SampleID is finding candidate passages and full-mix DTW is refining their timing.",
            )
            main_settings = settings.model_copy(
                update={
                    "stem_enabled": False,
                    "stem_include_cross_other": False,
                }
            )
            result = analyze_pair(
                intake,
                original,
                new,
                adapter=adapter,
                settings=main_settings,
            )
            adapter = None
            result.methods["web_profile"] = PROFILE["name"]
            result.methods["stem_strategy"] = (
                "integrated_grouped_representatives_same_stem"
            )
            if warning:
                result.warnings.append(warning)
                result.methods["sampleid"] = matcher_failure

            publish_progress(
                "grouping",
                57,
                "Candidate windows have been found. Overlapping and repeated passages are being grouped.",
            )
            comparison = comparison_figure(
                spectral_view(original),
                spectral_view(new),
                result.master.locate.sample_occurrences
                or result.master.locate.measurement_intervals,
            )
            repo.write(
                root + "/comparison.json",
                json.loads(comparison.to_json()),
            )
            result = complete_grouped_stems(result)

        publish_progress(
            "finalizing",
            97,
            "The completed timestamps and supporting evidence are being saved for review.",
            partial=result,
        )
        repo.write(root + "/result.json", result.model_dump(mode="json"))

    state, generation = repo.read(root + "/case.json")
    if state.get("task_id") == task_id:
        final_counts = instrument_progress(result)
        now = time.time()
        final_counts.update(
            stage="completed",
            label=STAGE_LABELS["completed"],
            percent=100,
            detail="Sony, full-mix DTW, grouping, Demucs and same-stem DTW have finished.",
            updated=now,
            stage_started=now,
            restart_count=restart_count,
        )
        state.update(
            status="completed",
            completed=now,
            error=None,
            result_ready=True,
            result_version=state.get("result_version", 0) + 1,
            instrument_progress=final_counts,
        )
        repo.write(root + "/case.json", state, generation)


if __name__ == "__main__":
    execute(*sys.argv[1:])
