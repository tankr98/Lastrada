"""One bounded worker subprocess; invoked by the private Cloud Run service."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time


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
    from lastrada.web.cloud import Cases, prefix
    from lastrada.audio.io import decode
    from lastrada.web.profile import analysis_settings, PROFILE
    from lastrada.pipeline import analyze_pair
    from lastrada.schemas.models import Intake, Work, Analysis
    from lastrada.reporting.comparison import spectral_view, comparison_figure
    from lastrada.recognition.sampleid_adapter import SampleIDAdapter
    from lastrada.separation.grouped_occurrences import run_grouped_instruments
    from lastrada.separation.occurrences import instrument_progress

    repo = Cases()
    root = prefix(owner, analysis_id)
    state, generation = repo.read(root + "/case.json")
    if state.get("task_id") != task_id or state["status"] == "completed":
        return
    state.update(status="running", started=time.time())
    repo.write(root + "/case.json", state, generation)

    with tempfile.TemporaryDirectory() as folder:
        paths = {}
        for role in ("original", "new"):
            paths[role] = Path(folder) / role
            repo.download(root + f"/{role}", paths[role])
        original = decode(paths["original"].read_bytes())
        new = decode(paths["new"].read_bytes())
        settings = analysis_settings()

        def save_instruments(partial):
            """Persist progress without releasing a partial result to the frontend."""

            partial.methods["web_profile"] = PROFILE["name"]
            repo.write(root + "/result.json", partial.model_dump(mode="json"))
            current, revision = repo.read(root + "/case.json")
            if current.get("task_id") == task_id:
                current["instrument_progress"] = instrument_progress(partial)
                repo.write(root + "/case.json", current, revision)

        if operation == "stems":
            # Compatibility path for analyses created before the integrated
            # pipeline. New analyses already contain grouped stem evidence.
            data, _ = repo.read(root + "/result.json")
            result = Analysis.model_validate(data)
            result = run_grouped_instruments(
                result,
                original,
                new,
                settings,
                on_progress=save_instruments,
                budget_seconds=1200,
                max_new_checks=100,
            )
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

            # Complete grouped Demucs and same-stem DTW before releasing the
            # timestamp review or Nature of Use draft. Progress may be persisted,
            # but result_ready is not set while this work is running.
            if settings.stem_group_enabled:
                try:
                    result = run_grouped_instruments(
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
            else:
                result.methods["instruments"] = (
                    "not_run: grouped stem analysis disabled"
                )

        repo.write(root + "/result.json", result.model_dump(mode="json"))

    state, generation = repo.read(root + "/case.json")
    if state.get("task_id") == task_id:
        state.update(
            status="completed",
            completed=time.time(),
            error=None,
            result_ready=True,
            result_version=state.get("result_version", 0) + 1,
            instrument_progress=instrument_progress(result),
        )
        repo.write(root + "/case.json", state, generation)


if __name__ == "__main__":
    execute(*sys.argv[1:])
