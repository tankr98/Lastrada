"""Cloud-independent validation and review rules for the web client."""

import hashlib
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from lastrada.schemas.models import Analysis, Interval, Feature, Placement, PathResult
from lastrada.reporting.review import reviewed_copy
from lastrada.reporting.document import missing_document_inputs, creator_narrative
from lastrada.alignment.intervals import coverage

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def owner_key(uid):
    return hashlib.sha256(uid.encode()).hexdigest()


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Upload(Payload):
    name: str = Field(min_length=1, max_length=250)
    size: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    content_type: str = "application/octet-stream"


class Credits(Payload):
    original_title: str = Field(min_length=1, max_length=200)
    original_artist: str = Field(min_length=1, max_length=200)
    new_title: str = Field(min_length=1, max_length=200)
    new_artist: str = Field(min_length=1, max_length=200)


class CreateAnalysis(Payload):
    original: Upload
    new: Upload
    credits: Credits


class UseReview(Payload):
    status: Literal["pending", "no_use", "confirmed"] = "pending"
    intervals: list[Interval] = Field(default_factory=list, max_length=2000)
    times_confirmed: bool = False
    details_confirmed: bool = False
    element: str = Field(default="", max_length=2000)
    lyrics: str = Field(default="", max_length=4000)
    method: str = Field(default="", max_length=2000)
    repetition: str = Field(default="", max_length=2000)
    role: str = Field(default="", max_length=2000)
    sections: list[Literal["whole track", "intro", "verse", "chorus", "bridge", "outro", "matched passages"]] = Field(
        default_factory=list
    )
    placement: Placement | None = None


class ReviewPayload(Payload):
    workflow: Literal["classic", "sample"] = "classic"
    description_initialized: bool = False
    table_draft: bool = False
    paths: dict[Literal["master", "publishing"], UseReview]
    narrative: str = Field(default="", max_length=20000)
    reviewer: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)
    approve: bool = False


class DraftPayload(ReviewPayload):
    prefill: bool = False
    preserve_fields: dict[Literal["master", "publishing"], list[Literal[
        "element", "method", "repetition", "role", "lyrics", "sections", "placement"
    ]]] = Field(default_factory=dict)


def draft_preview(analysis: Analysis, payload: DraftPayload, model_name=None):
    """Generate the same document as export, without saving or approving it."""
    from lastrada.reporting.document import document_text
    from lastrada.reporting.sample_flow import description_proposal, sample_intervals

    review = ReviewPayload.model_validate(payload.model_dump(exclude={"prefill", "preserve_fields"}))
    review.approve = False
    proposals = {}
    for rights, answer in review.paths.items():
        answer.details_confirmed = False
        intervals = sample_intervals(analysis) if review.workflow == "sample" else answer.intervals
        proposal = description_proposal(analysis, intervals, model_name, rights)
        old_defaults = dict(proposal["description"])
        if payload.table_draft:
            from lastrada.reporting.table_draft import proposal as table_proposal
            proposal = table_proposal(analysis, intervals, model_name, rights,
                                     confirmed=review.workflow == "sample" or
                                     (answer.status == "confirmed" and answer.times_confirmed))
        proposals[rights] = proposal
        if payload.prefill and answer.status != "no_use":
            preserved = payload.preserve_fields.get(rights, [])
            for field, value in proposal["description"].items():
                if field not in preserved and (not getattr(answer, field)
                        or (payload.table_draft and getattr(answer, field) == old_defaults.get(field))):
                    setattr(answer, field, value)
            values = proposal["placement"]["values"]
            if "sections" not in preserved and not answer.sections:
                answer.sections = values["sections"]
            if "placement" not in preserved and not answer.placement:
                answer.placement = Placement(values["placement"])
    result = apply_review(analysis, review, model_name=model_name)
    return {
        "paths": {r: a.model_dump(mode="json") for r, a in review.paths.items()},
        "proposals": proposals,
        "narrative": result.review.corrected["nature_of_use"]["text"],
        "generated": result.review.generated_narrative,
        "previous_narrative": result.review.previous_narrative,
        "document": document_text(result),
    }


def apply_review(analysis: Analysis, payload: ReviewPayload, model_name=None):
    from lastrada.reporting.sample_flow import sample_intervals, LYRICS_UNASSESSED, has_partial_matches, PARTIAL_USE_NOTE
    from lastrada.reporting.placement import PLACEMENT_SECTIONS, description_signature

    sample = payload.workflow == "sample"
    expected = {"master"} if sample else set(analysis.input.analysis_scope)
    if set(payload.paths) != expected or not expected.issubset(analysis.input.analysis_scope):
        raise ValueError("Review each applicable type of use")
    paths = {}
    for rights, answer in payload.paths.items():
        path = PathResult(rights_type=rights)
        detected = sample_intervals(analysis) if sample else []
        if sample:
            if answer.status != "confirmed" or answer.times_confirmed:
                raise ValueError("Confirm the description; detected times are not a listening confirmation")
            if not detected:
                raise ValueError("No supported recording match is available")
            if answer.intervals and answer.intervals != detected:
                raise ValueError("Detected timestamps must match the stored analysis")
        if answer.status == "no_use":
            path.locate.detection_status = "not_detected"
            path.locate.sample_detected = False
            path.locate.review_required = False
            path.classification.review_required = False
        else:
            confirmed = (
                answer.status == "confirmed" and answer.times_confirmed and bool(answer.intervals)
            )
            path.locate.detection_status = "verified" if confirmed else "candidate"
            path.locate.sample_detected = True if confirmed else None
            path.locate.review_required = not answer.details_confirmed
            path.locate.sample_occurrences = [
                i.model_copy(
                    update={
                        "source": "expert_review"
                        if answer.times_confirmed
                        else "unconfirmed_timing_suggestion",
                        "status": "expert_verified" if answer.times_confirmed else "estimated",
                        "end_review": None if answer.times_confirmed else i.end_review,
                        "ending_review_context": i.ending_review_context or i.end_review,
                    }
                )
                for i in answer.intervals
            ]
            if sample:
                # Describe-only confirmation never fabricates a timestamp review.
                saved = (analysis.review.corrected or {}).get("master", {})
                reviewed_times = saved.get("locate", {}).get("detection_status") == "verified"
                path.locate.sample_occurrences = [i.model_copy(deep=True) for i in detected]
                path.locate.timing_source = "reviewed" if reviewed_times else "automated"
                path.locate.detection_status = "verified" if reviewed_times else "candidate"
                path.locate.sample_detected = True if reviewed_times else None
            if confirmed or sample:
                seconds, percent = coverage(
                    path.locate.sample_occurrences, analysis.durations["new"]
                )
                path.locate.total_covered_seconds, path.locate.coverage_percentage = (
                    seconds,
                    percent,
                )
            path.describe.elements = (
                [
                    Feature(
                        feature="musical_element",
                        value=answer.element.strip(),
                        source="expert_review"
                        if answer.details_confirmed
                        else "unconfirmed_description",
                        status="expert_verified" if answer.details_confirmed else "estimated",
                        review_required=not answer.details_confirmed,
                    )
                ]
                if answer.element.strip()
                else []
            )
            if answer.lyrics.strip() and answer.lyrics.strip() != LYRICS_UNASSESSED:
                path.describe.elements.append(
                    Feature(
                        feature="lyrics",
                        value=answer.lyrics.strip(),
                        source="expert_review"
                        if answer.details_confirmed
                        else "unconfirmed_description",
                        status="expert_verified" if answer.details_confirmed else "estimated",
                        review_required=not answer.details_confirmed,
                    )
                )
            else:
                path.describe.limitations.append("Reused lyrics have not been assessed.")
            if sample and has_partial_matches(detected):
                path.describe.limitations.append(PARTIAL_USE_NOTE)
            path.describe.sections = PLACEMENT_SECTIONS.get(answer.placement, answer.sections)
            path.describe.reuse_type = answer.method.strip() or None
            path.describe.repetition = answer.repetition.strip() or None
            if answer.placement != "throughout" and path.describe.repetition == "Repeated throughout the track":
                path.describe.repetition = "Repeated in the selected sections"
            path.describe.role_in_new_song = answer.role.strip() or None
            path.classification.placement = answer.placement
            path.classification.source = "expert_review"
            path.classification.review_required = (
                not answer.details_confirmed or answer.placement is None
            )
        paths[rights] = path.model_dump(mode="json")
    if sample:
        for rights in set(analysis.input.analysis_scope) - {"master"}:
            saved = (analysis.review.corrected or {}).get(rights)
            if saved and saved["locate"]["detection_status"] in {"verified", "not_detected"}:
                paths[rights] = saved  # Preserve a previous explicit review.
            else:
                omitted = PathResult(rights_type=rights)
                omitted.locate.detection_status = "not_requested"
                omitted.locate.review_required = False
                omitted.classification.review_required = False
                paths[rights] = omitted.model_dump(mode="json")
    candidate = analysis.model_copy(deep=True)
    candidate.review.corrected = None
    candidate.review.workflow = payload.workflow
    for rights, value in paths.items():
        setattr(candidate, rights, PathResult.model_validate(value))
    if payload.table_draft:
        from lastrada.reporting.table_draft import narrative as table_narrative
        generated = table_narrative(analysis, paths, model_name)
    else:
        generated = creator_narrative(candidate)
    previous_paths = {
        r: analysis.review.corrected[r] for r in paths
    } if analysis.review.corrected else None
    changed = previous_paths is not None and description_signature(paths) != description_signature(previous_paths)
    supplied = payload.narrative.strip()
    narrative = generated if changed or not supplied else supplied
    previous_narrative = analysis.review.previous_narrative
    if changed and supplied and supplied != analysis.review.generated_narrative:
        previous_narrative = supplied
    if payload.approve:
        missing = missing_document_inputs(candidate)
        if missing:
            raise ValueError("Complete your details: " + "; ".join(missing))
    result = reviewed_copy(
        analysis,
        paths,
        narrative,
        payload.reviewer.strip(),
        approve=payload.approve,
        notes=payload.notes,
        workflow=payload.workflow,
    )
    if "master" in payload.paths and (sample or payload.description_initialized):
        result.review.description_answers = {
            field: getattr(payload.paths["master"], field)
            for field in ("element", "method", "repetition", "role", "lyrics")
        }
        result.review.description_answers["repetition"] = paths["master"]["describe"]["repetition"] or ""
    result.review.generated_narrative = generated
    result.review.previous_narrative = previous_narrative
    return result
