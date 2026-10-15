from time import perf_counter
from lastrada.schemas.models import Analysis, PathResult, Locate
from lastrada.measurement.pfnmf import measure
from lastrada.master.analyze import analyze as analyze_master
from lastrada.publishing.analyze import analyze as analyze_publishing
from lastrada.synthesis.narrative import draft
from lastrada.recognition.sampleid_adapter import SampleIDUnavailable
from lastrada.alignment.local import refine_candidate
from lastrada.config import Settings


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
                # Preserve coarse intervals; separate patches retain refinement provenance.
                refined = [refine_candidate(original, new, i) for i in candidates]
                result.timings_seconds["localization"] += perf_counter() - t
                candidates = [
                    r if r.source == "direct_waveform_local_alignment" else c
                    for r, c in zip(refined, candidates)
                ]
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
    result.nature_of_use = draft(result)
    for work in (intake.original_work, intake.new_work):
        if work.audio_version_warning:
            result.warnings.append(work.audio_version_warning)
    return result
