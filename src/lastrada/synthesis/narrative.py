"""Only narrate structured evidence; do not invent musical detail."""

from lastrada.schemas.models import Narrative


def draft(analysis):
    parts = []
    for rights in analysis.input.analysis_scope:
        path = getattr(analysis, rights)
        prefix = "Publishing" if rights == "publishing" else "Master recording"
        locate, description = path.locate, path.describe
        if locate.detection_status == "verified":
            items = [
                str(f.value)
                for f in description.elements
                if f.status == "expert_verified"
                and f.feature in ("musical_element", "lyrics", "instrumentation")
                and f.value
            ]
            element = ", ".join(items) or "material whose musical identity remains unspecified"
            parts.append(f"{prefix}: expert review identifies reuse of {element}.")
            if locate.sample_occurrences:
                times = ", ".join(
                    f"{i.new_start:.2f}–{i.new_end:.2f}s" for i in locate.sample_occurrences
                )
                parts.append(f"It appears in the new recording at {times}.")
            if locate.coverage_percentage is not None:
                parts.append(
                    f"The reviewed intervals cover {locate.total_covered_seconds:.2f} seconds "
                    f"({locate.coverage_percentage:.1f}% of the new recording)."
                )
            if description.sections:
                parts.append(f"Reviewed sections: {', '.join(description.sections)}.")
            if description.reuse_type:
                parts.append(f"Reviewed reuse method: {description.reuse_type}.")
            if description.repetition:
                parts.append(f"Repetition: {description.repetition}.")
            if description.role_in_new_song:
                parts.append(f"Role in the new recording: {description.role_in_new_song}.")
        elif rights == "master":
            if locate.sample_occurrences:
                parts.append(
                    f"{prefix}: {len(locate.sample_occurrences)} grouped candidate matching "
                    "regions require listening and expert verification."
                )
            elif locate.detection_status == "not_detected":
                parts.append(
                    f"{prefix}: SampleID found no candidates above the configured threshold; "
                    "this does not establish absence of reuse."
                )
            else:
                parts.append(f"{prefix}: direct reuse has not been verified.")
            if locate.coverage_percentage is not None:
                parts.append(
                    f"Experimental PF-NMF spectral activation occupies "
                    f"{locate.total_covered_seconds:.2f} seconds "
                    f"({locate.coverage_percentage:.1f}%); this is not verified sample coverage."
                )
        else:
            parts.append(
                "Publishing: compositional reuse has not been localized or verified. "
                "An expert must identify any replayed melody, re-sung lyric or other reused element."
            )
        if path.classification.placement:
            qualifier = "Reviewed" if path.classification.source == "expert_review" else "Proposed"
            parts.append(
                f"{qualifier} placement: {path.classification.placement.value.replace('_', ' ')}."
            )
    return Narrative(text=" ".join(parts))
