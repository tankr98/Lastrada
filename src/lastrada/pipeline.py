import os
from pathlib import Path
from time import perf_counter

from lastrada.alignment.dtw import refine_candidate_dtw
from lastrada.alignment.local import refine_candidate
from lastrada.alignment.stems import compare_candidate_stems
from lastrada.config import Settings
from lastrada.master.analyze import analyze as analyze_master
from lastrada.measurement.pfnmf import measure
from lastrada.publishing.analyze import analyze as analyze_publishing
from lastrada.recognition.sampleid_adapter import SampleIDUnavailable
from lastrada.schemas.models import Analysis, Interval, Locate, PathResult
from lastrada.synthesis.narrative import draft


def _best_separated_stem_evidence(comparison):
    """Return the strongest accepted non-full-mix stem pair, if one exists."""
    return next(
        (
            item
            for item in comparison.evidence
            if item.accepted
            and not (
                item.source_stem == "full_mix"
                and item.derivative_stem == "full_mix"
            )
        ),
        None,
    )


def stem_assist_candidates(original, new, candidates, separator, settings):
    """Run Demucs + guarded DTW on the strongest paired candidates.

    Stem evidence is a second-stage validation layer. It only replaces the
    review timing when the current interval is still a coarse Sony candidate;
    an existing direct-waveform or full-mix DTW refinement is preserved.
    """
    updated = list(candidates)
    comparisons = []

    for index, candidate in enumerate(updated[: settings.stem_max_candidates]):
        if candidate.original_start is None or candidate.original_end is None:
            continue

        comparison = compare_candidate_stems(
            original,
            new,
            candidate,
            separator,
            separation_padding=settings.stem_separation_padding_seconds,
            dtw_search_padding=min(
                settings.dtw_search_padding_seconds,
                settings.stem_separation_padding_seconds,
            ),
            max_pitch_shift_semitones=settings.dtw_max_pitch_shift_semitones,
            minimum_duration_ratio=settings.dtw_min_duration_ratio,
            maximum_duration_ratio=settings.dtw_max_duration_ratio,
            minimum_duration=settings.dtw_minimum_duration_seconds,
            include_cross_other=settings.stem_include_cross_other,
        )
        comparisons.append(comparison)

        best = _best_separated_stem_evidence(comparison)
        if best is None:
            continue

        # Do not displace a stronger full-mix refinement. Stem evidence is used
        # to refine a still-coarse Sony interval, while all results remain
        # candidate evidence requiring listening review.
        if candidate.source not in {
            "sampleid_rank_sequence",
            "sampleid_chunk_cosine",
        }:
            continue

        updated[index] = Interval(
            new_start=best.refined_new_start,
            new_end=best.refined_new_end,
            original_start=candidate.original_start,
            original_end=candidate.original_end,
            source=(
                "stem-assisted DTW · "
                f"{best.source_stem} → {best.derivative_stem}"
            ),
            status="candidate",
            similarity=candidate.similarity,
        )

    return updated, comparisons


def _run_optional_stem_assistance(result, original, new, candidates, settings):
    if not settings.stem_enabled:
        result.methods["stems"] = "not_run: optional stem assistance disabled"
        return candidates
    if not candidates:
        result.methods["stems"] = "not_run: no paired Sony candidate available"
        return candidates

    try:
        from lastrada.separation.demucs import (
            DemucsSeparator,
            StemSeparationUnavailable,
            demucs_available,
        )
    except ImportError:
        result.methods["stems"] = "unavailable: optional Demucs package is not installed"
        result.warnings.append(
            "Stem-assisted validation was requested, but Demucs is not installed. "
            "Install the optional stems dependencies and rerun the analysis."
        )
        return candidates

    if not demucs_available():
        result.methods["stems"] = "unavailable: optional Demucs package is not installed"
        result.warnings.append(
            "Stem-assisted validation was requested, but Demucs is not installed. "
            "Install the optional stems dependencies and rerun the analysis."
        )
        return candidates

    cache_root = Path(os.getenv("LASTRADA_CACHE_DIR", "cache")) / "demucs"
    try:
        separator = DemucsSeparator(
            model_name=settings.stem_model_name,
            device=settings.stem_device,
            cache_dir=cache_root,
        )
        started = perf_counter()
        updated, comparisons = stem_assist_candidates(
            original,
            new,
            candidates,
            separator,
            settings,
        )
        result.timings_seconds["stem_separation"] = perf_counter() - started
    except (StemSeparationUnavailable, OSError, RuntimeError, ValueError) as exc:
        result.methods["stems"] = f"unavailable: {exc}"
        result.warnings.append(f"Stem-assisted validation did not complete: {exc}")
        return candidates

    accepted_pairs = []
    refined_candidates = 0
    for comparison in comparisons:
        best = _best_separated_stem_evidence(comparison)
        if best is not None:
            accepted_pairs.append(f"{best.source_stem}->{best.derivative_stem}")
    for before, after in zip(candidates, updated, strict=False):
        if before.source != after.source and after.source.startswith("stem-assisted DTW"):
            refined_candidates += 1

    if comparisons:
        pair_summary = ", ".join(accepted_pairs) if accepted_pairs else "none accepted"
        result.methods["stems"] = (
            f"demucs_{settings.stem_model_name}_candidate_regions; "
            f"accepted_pairs={pair_summary}; "
            f"timings_refined={refined_candidates}"
        )
        result.warnings.append(
            "Demucs stems are model estimates with possible bleed and artifacts; "
            "stem labels are supporting evidence and require listening review."
        )
        if refined_candidates:
            current = result.methods.get("alignment", "")
            result.methods["alignment"] = (
                current + "_then_stem_assisted_dtw" if current else "stem_assisted_dtw"
            )
    else:
        result.methods["stems"] = "not_run: no eligible paired candidate"

    return updated


def analyze_pair(
    intake, original, new, adapter=None, synthetic=False, threshold=None, settings=None
):
    settings = settings or Settings()
    if max(original.duration, new.duration) > settings.max_duration_seconds:
        raise ValueError("Recording exceeds configured duration limit")
    start = perf_counter()
    result = Analysis(
        case_id=intake.case_id,
        input=intake,
        synthetic=synthetic,
        durations={"original": original.duration, "new": new.duration},
    )
    result.publishing = analyze_publishing("publishing" in intake.analysis_scope)
    result.methods["publishing"] = "expert_review_required"
    result.timings_seconds = {
        "audio_preparation": 0.0,
        "model_inference": 0.0,
        "localization": 0.0,
        "classification": 0.0,
        "narrative_generation": 0.0,
        "stem_separation": 0.0,
    }
    if "master" in intake.analysis_scope:
        t = perf_counter()
        measurement = measure(
            original,
            new,
            components=settings.reference_components,
            free_components=settings.free_components,
            iterations=settings.iterations,
            threshold=threshold if threshold is not None else settings.activation_threshold,
            minimum=settings.minimum_interval_seconds,
        )
        result.timings_seconds["localization"] = perf_counter() - t
        result.methods["measurement"] = "experimental_pfnmf_euclidean"
        result.methods["sampleid"] = (
            "not_run: optional matching disabled or no local checkpoint configured"
        )
        result.methods["stems"] = "not_run: Sony candidate pipeline did not run"
        candidates, ran = [], False
        if adapter:
            t = perf_counter()
            try:
                candidates = adapter.match(
                    original,
                    new,
                    threshold=settings.sampleid_similarity_threshold,
                    seconds=settings.sampleid_chunk_seconds,
                    hop=settings.sampleid_hop_seconds,
                )
                ran = True
                result.methods["sampleid"] = "local_cpu_chunk_embeddings"
                result.timings_seconds["model_inference"] = perf_counter() - t

                t = perf_counter()
                refined_candidates = []
                dtw_used = False

                for candidate in candidates:
                    # First prefer direct waveform correlation when the recording
                    # material is nearly unchanged.
                    direct = refine_candidate(original, new, candidate)
                    if direct.source == "direct_waveform_local_alignment":
                        refined_candidates.append(direct)
                        continue

                    # If direct matching cannot refine the candidate, try guarded
                    # chroma/DTW for moderate pitch/time transformations.
                    if settings.dtw_enabled:
                        dtw = refine_candidate_dtw(
                            original,
                            new,
                            candidate,
                            search_padding=settings.dtw_search_padding_seconds,
                            max_pitch_shift_semitones=settings.dtw_max_pitch_shift_semitones,
                            minimum_duration_ratio=settings.dtw_min_duration_ratio,
                            maximum_duration_ratio=settings.dtw_max_duration_ratio,
                            minimum_duration=settings.dtw_minimum_duration_seconds,
                        )
                        if dtw.source == "dtw_chroma_local_alignment":
                            refined_candidates.append(dtw)
                            dtw_used = True
                            continue

                    # Conservative fallback: preserve Sony's coarse candidate.
                    refined_candidates.append(candidate)

                candidates = refined_candidates
                result.timings_seconds["localization"] += perf_counter() - t
                result.methods["alignment"] = (
                    "direct_waveform_then_guarded_dtw"
                    if dtw_used
                    else "direct_waveform_or_coarse_sampleid"
                )
                candidates = _run_optional_stem_assistance(
                    result,
                    original,
                    new,
                    candidates,
                    settings,
                )
            except SampleIDUnavailable as exc:
                result.methods["sampleid"] = f"unavailable: {exc}"
                result.warnings.append(str(exc))
                result.timings_seconds["model_inference"] = perf_counter() - t

        t = perf_counter()
        result.master = analyze_master(measurement, candidates, ran)
        result.timings_seconds["classification"] = perf_counter() - t
    else:
        result.master = PathResult(
            rights_type="master", locate=Locate(detection_status="not_requested")
        )

    t = perf_counter()
    result.nature_of_use = draft(result)
    result.timings_seconds["narrative_generation"] = perf_counter() - t
    result.timings_seconds["total"] = perf_counter() - start

    if synthetic:
        result.warnings.append("SYNTHETIC DEMONSTRATION: generated signals, not a historical case.")
    for work in (intake.original_work, intake.new_work):
        if work.audio_version_warning:
            result.warnings.append(work.audio_version_warning)
    return result


def reuse_preview(preview, intake):
    """Attach confirmed credits/scope to the same pair's default analysis.

    Caller must verify that the uploads and analysis settings are unchanged.
    Optional recognition runs use analyze_pair instead.
    """
    result = preview.model_copy(deep=True)
    result.case_id, result.input = intake.case_id, intake
    result.publishing = analyze_publishing("publishing" in intake.analysis_scope)
    if "master" not in intake.analysis_scope:
        result.master = PathResult(
            rights_type="master", locate=Locate(detection_status="not_requested")
        )
        result.methods.pop("measurement", None)
        result.methods.pop("sampleid", None)
        result.methods.pop("stems", None)
    result.nature_of_use = draft(result)
    for work in (intake.original_work, intake.new_work):
        if work.audio_version_warning:
            result.warnings.append(work.audio_version_warning)
    return result
