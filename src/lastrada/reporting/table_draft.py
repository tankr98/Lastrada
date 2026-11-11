"""Read-only, plain-language drafting from the existing analysis table.

The reference prose informed structure only: identify the material, distinguish
source/new times, then describe repetition. No reference-pair facts are loaded.
"""

from lastrada.reporting.document import timestamp
from lastrada.reporting.loop_groups import group_loop_families
from lastrada.reporting.sample_flow import description_proposal, automatic_path
from lastrada.schemas.models import PathResult
from lastrada.separation.occurrences import occurrence_rows

ROLE_UNKNOWN = "Musical role not established by the analysis"
METHOD_UNCONFIRMED = "Possible recording sample — not confirmed by the analysis"


def key(interval):
    return (interval.new_start, interval.new_end, interval.original_start, interval.original_end)


def proposal(analysis, intervals, model_name=None, rights="master", confirmed=False):
    result = description_proposal(analysis, intervals, model_name, rights)
    result["description"]["role"] = ROLE_UNKNOWN
    result["notes"]["role"] = "Timing and instrument labels do not establish a hook, melody or background role."
    if not confirmed:
        result["description"]["method"] = METHOD_UNCONFIRMED if rights == "master" else "Musical reuse not confirmed by the analysis"
    return result


def join_words(values):
    values = list(dict.fromkeys(values))
    if len(values) < 2:
        return "".join(values)
    return ", ".join(values[:-1]) + " and " + values[-1]


def sounds(values):
    return join_words("unidentified accompaniment" if v.lower() == "other" else v.lower()
                      for v in values if v.lower() not in {"full_mix", "full mix"})


def span(start, end):
    return f"{timestamp(start)}–{timestamp(end)}"


def sound_note(row):
    if not row or row.status != "checked":
        return "The instrument or vocal content has not been established for this passage."
    labels = sounds(row.suggested_instruments) if not row.context_only else ""
    if labels:
        note = f"The instrument check supports {labels} in this match."
        if row.probe and key(row.probe) != key(row.interval):
            p = row.probe
            note += (f" This check covers {span(p.original_start, p.original_end)} in the original"
                     f" and {span(p.new_start, p.new_end)} in the new track; it does not identify"
                     " the instruments in the unchecked remainder.")
        return note
    notes = []
    for name, estimates in (("original recording", row.source_sounds), ("new track", row.new_sounds)):
        if not estimates:
            continue
        groups = {}
        for item in estimates:
            groups.setdefault((item.start, item.end, item.scope), []).append(item.instrument)
        for (start, end, scope), labels in groups.items():
            label = sounds(labels)
            if label:
                where = "surrounding audio" if scope == "context" else "checked audio"
                notes.append(f"The {where} in the {name} contains estimated {label} at {span(start, end)}.")
    if notes:
        notes.append("These sound estimates alone do not establish which instruments were sampled.")
    return " ".join(notes) or "The instrument or vocal content is unresolved."


def representative(items, maximum=3):
    if len(items) <= maximum:
        return list(items)
    return [items[0], items[len(items) // 2], items[-1]]


def narrative(analysis, paths, model_name=None):
    """Use existing grouping and exact row/probe bounds, without modifying them."""
    rows = {key(row.interval): row for row in occurrence_rows(analysis, model_name)}
    paragraphs = []
    for rights, value in paths.items():
        path = PathResult.model_validate(value)
        if path.locate.detection_status == "not_requested":
            continue
        if path.locate.detection_status == "not_detected":
            paragraphs.append("The saved review records no recording sample." if rights == "master"
                              else "The saved review records no separate replayed melody or re-sung lyrics.")
            continue
        intervals = path.locate.sample_occurrences
        established = path.locate.detection_status == "verified" or automatic_path(path)
        if not intervals:
            paragraphs.append("The analysis has not located a passage to describe. Source and new-track timestamps, instruments and musical role remain unresolved.")
            continue
        opening = ("The nature of the use is a recording sample from the original song."
                   if established else "The analysis suggests possible sampled passages from the original song. Recording reuse remains unconfirmed.")
        if rights != "master":
            opening = "The saved review describes the following possible reuse of the original composition."
        description = path.describe
        element = next((str(f.value) for f in description.elements if f.feature == "musical_element" and f.value), "")
        if element:
            common = {"Vocals": "a vocal passage", "Bass": "a bass part", "Guitar": "a guitar part",
                      "Piano": "a piano part", "Drums": "a drum part"}
            opening += f" The sound is described as {common.get(element, element)}."
        if description.reuse_type and description.reuse_type not in {METHOD_UNCONFIRMED, "Sampled the original recording"}:
            opening += f" The described method is {description.reuse_type.rstrip('.')}."
        paragraphs.append(opening)
        families = group_loop_families(intervals, analysis.durations["new"])
        for family in families[:4]:
            count = family.occurrence_count
            terms = "appearances" if established else "possible appearances"
            if count > 1:
                repeated = (f"The table groups this passage into {count} {terms}, suggesting repetition. "
                            "Representative timestamps are given below." if count > 3
                            else f"The table groups this passage into {count} {terms}, suggesting repetition.")
                paragraphs.append(repeated)
            for item in representative(family.occurrences):
                start = (f"The passage at {span(item.original_start, item.original_end)} in the original recording"
                         if item.original_start is not None else "A passage whose position in the original recording is unknown")
                match = "appears" if established else "is a possible match"
                detail = f"{start} {match} at {span(item.new_start, item.new_end)} in the new track."
                if rights == "master":
                    detail += " " + sound_note(rows.get(key(item)))
                if item.end_review:
                    detail += " The ending is uncertain and may extend beyond the displayed time."
                paragraphs.append(detail)
        if len(families) > 4:
            paragraphs.append("Further passage groups and every exact timestamp remain available in View detailed analysis.")
        if path.classification.placement:
            from lastrada.reporting.placement import PLACEMENT_TEXT
            paragraphs.append("In this draft, the use is placed " + PLACEMENT_TEXT[path.classification.placement] + ".")
        if description.repetition:
            repetition = description.repetition
            if repetition.startswith("Repetition not fully assessed"):
                paragraphs.append("Only located portions are shown, so the full repetition pattern remains uncertain.")
            else:
                paragraphs.append("The repetition is described as " + repetition[0].lower() + repetition[1:].rstrip(".") + ".")
        if description.role_in_new_song and description.role_in_new_song != ROLE_UNKNOWN:
            paragraphs.append("Described musical role: " + description.role_in_new_song.rstrip(".") + ".")
        else:
            paragraphs.append("The analysis does not establish the passage’s musical role in the new track.")
        lyrics = next((str(f.value) for f in description.elements if f.feature == "lyrics" and f.value), "")
        if lyrics:
            paragraphs.append("Reused lyrics supplied for this draft: " + lyrics)
        paragraphs.extend(description.limitations)
    return "\n\n".join(paragraphs)
