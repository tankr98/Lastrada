"""Recording-sample workflow: detected times and editable description proposals."""

from lastrada.alignment.intervals import merge_ranges
from lastrada.reporting.suggestions import placement_proposal
from lastrada.schemas.models import PathResult

LYRICS_UNASSESSED = "Not assessed — add any reused lyrics"


def sample_intervals(analysis):
    """Use accepted localization, retaining an existing explicit timing review.

    Coarse retrieval windows and PF-NMF activations alone cannot establish a
    recording match. Do not turn them into accepted uses by hiding their review.
    """
    saved = (analysis.review.corrected or {}).get("master")
    if saved:
        reviewed = PathResult.model_validate(saved)
        if reviewed.locate.detection_status == "not_detected":
            return []
        if reviewed.locate.detection_status == "verified":
            return list(reviewed.locate.sample_occurrences)
    return sorted(
        [
            i
            for i in analysis.master.locate.sample_occurrences
            if i.original_start is not None
            and i.new_end <= analysis.durations.get("new", 0)
            and i.original_end <= analysis.durations.get("original", 0)
            and (
                i.source in {"direct_waveform_local_alignment", "dtw_chroma_local_alignment"}
                or i.source.startswith("stem-assisted DTW · ")
            )
        ],
        key=lambda i: (i.new_start, i.new_end, i.original_start, i.original_end),
    )


def automatic_path(path):
    return (
        path.locate.timing_source == "automated"
        and path.locate.detection_status == "candidate"
        and bool(path.locate.sample_occurrences)
    )


def unresolved_recording(analysis):
    """Explain an abstention without treating unavailable checks as a negative."""
    matcher = analysis.methods.get("sampleid", "")
    stems = analysis.methods.get("stems", "")
    candidates = analysis.master.locate.sample_occurrences
    paired = [i for i in candidates if i.original_start is not None]

    def state(method, completed_prefix):
        if method.startswith("unavailable:"):
            return "unavailable"
        if method.startswith("not_run:"):
            return "not_run"
        return "completed" if method.startswith(completed_prefix) else "unknown"

    checks = {
        "recording_search": state(matcher, "local_cpu_chunk_embeddings"),
        "initial_instrument_checks": state(stems, "demucs_"),
        "candidate_count": len(candidates),
    }
    title = "We couldn’t confirm a recording sample."
    if checks["recording_search"] in {"unavailable", "not_run"}:
        reason = "matching_unavailable"
        title = "Recording matching did not complete."
        message = "The recording matcher did not finish its checks. This result cannot tell us whether the original recording was sampled."
    elif paired and checks["initial_instrument_checks"] in {"unavailable", "not_run"}:
        reason = "verification_incomplete"
        title = "Sample verification did not finish."
        message = "Possible passages were found, but instrument verification did not complete. Keep the analysis details so we can investigate."
    elif paired:
        reason = "unconfirmed_candidates"
        message = "Possible passages were found, but the saved results do not confirm a recording match."
    elif checks["recording_search"] == "completed" and not candidates:
        reason = "no_candidates"
        message = "No candidate recording match was located in these files. Check that you uploaded the intended original recording and your track in the correct order."
    else:
        reason = "insufficient_evidence"
        message = "There is not enough evidence to confirm a recording match. The saved analysis details can help us investigate."
    return {"reason": reason, "title": title, "message": message, "checks": checks}


def sample_review(analysis, model_name=None):
    intervals = sample_intervals(analysis)
    if not intervals:
        return {
            "status": "not_identified",
            "intervals": [],
            "description": {},
            "notes": {},
            "placement": {"values": {}, "reason": "No supported recording match found."},
            **unresolved_recording(analysis),
        }
    labels, source_labels = [], []
    keys = {(i.new_start, i.new_end, i.original_start, i.original_end) for i in intervals}
    from lastrada.separation.occurrences import occurrence_rows

    for row in occurrence_rows(analysis, model_name):
        i = row.interval
        if (
            row.status != "checked"
            or (i.new_start, i.new_end, i.original_start, i.original_end) not in keys
        ):
            continue
        if not row.context_only:
            labels.extend(row.suggested_instruments)
        source_labels.extend(s.instrument for s in row.source_sounds if s.scope == "sample")
    labels, source_labels = list(dict.fromkeys(labels)), list(dict.fromkeys(source_labels))
    element = (
        ", ".join(labels)
        if labels
        else (
            "Sampled passage; source sounds include " + ", ".join(source_labels).lower()
            if source_labels
            else "Sampled passage — instrument not identified"
        )
    )
    placement = placement_proposal(intervals, analysis.durations["new"])
    values = dict(placement.values)
    values.setdefault("sections", ["matched passages"])
    values.setdefault("placement", "selected_sections")
    ranges = merge_ranges([(i.new_start, i.new_end) for i in intervals], analysis.durations["new"])
    role = (
        "Recurring musical texture"
        if len(ranges) > 1
        else "A brief musical accent"
        if ranges[0][1] - ranges[0][0] <= 8
        else "An extended musical layer"
    )
    return {
        "status": "identified",
        "intervals": [i.model_dump(mode="json") for i in intervals],
        "description": {
            "element": element,
            "method": "Sampled the original recording",
            "repetition": values["repetition"],
            "role": role,
            "lyrics": LYRICS_UNASSESSED,
        },
        "notes": {
            "element": "Instrument estimates cover the checked portions; confirm the sound you used."
            if labels
            else "Source sounds are estimates, not a determination of which instrument was sampled."
            if source_labels
            else "The recording match was found, but its instrument is unresolved.",
            "role": "Suggested from the timing pattern. Confirm or edit its musical role.",
            "lyrics": "Lyrics have not been transcribed or checked; this does not mean none were used.",
        },
        "placement": {"values": values, "reason": placement.reason},
    }
