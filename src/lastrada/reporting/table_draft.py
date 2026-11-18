"""Read-only, plain-language drafting from the existing analysis table.

The reference prose informed structure only: identify the material, distinguish
source/new times, then describe repetition. No reference-pair facts are loaded.
"""

import re

from lastrada.reporting.document import timestamp
from lastrada.reporting.loop_groups import group_loop_families
from lastrada.reporting.sample_flow import description_proposal, automatic_path, has_partial_matches
from lastrada.reporting.placement import PLACEMENT_TEXT
from lastrada.schemas.models import PathResult
from lastrada.separation.occurrences import occurrence_rows

ROLE_UNKNOWN = "Musical role not established by the analysis"
METHOD_UNCONFIRMED = "Recording sample"
METHOD_DEFAULTS = {
    METHOD_UNCONFIRMED, "Possible recording sample — not confirmed by the analysis",
    "Musical reuse not confirmed by the analysis", "Replayed musical material",
    "Sampled the original recording", "Replayed or re-sang the original music",
}


def key(interval):
    return (interval.new_start, interval.new_end, interval.original_start, interval.original_end)


def proposal(analysis, intervals, model_name=None, rights="master", confirmed=False):
    result = description_proposal(analysis, intervals, model_name, rights)
    result["notes"]["role"] = "Drafted from the named musical parts; adjust to describe their role in your arrangement."
    if not confirmed:
        result["description"]["method"] = METHOD_UNCONFIRMED if rights == "master" else "Replayed musical material"
    return result


def join_words(values):
    values = list(dict.fromkeys(values))
    if len(values) < 2:
        return "".join(values)
    return ", ".join(values[:-1]) + " and " + values[-1]


def sounds(values):
    return join_words("instrumental texture" if v.lower() in {"other", "other sounds (unidentified)"} else v.lower()
                      for v in values if v.lower() not in {"full_mix", "full mix"})


def span(start, end):
    return f"{timestamp(start)}–{timestamp(end)}"


def sound_note(row):
    if not row or row.status != "checked":
        return ""
    labels = sounds(row.suggested_instruments) if not row.context_only else ""
    if labels:
        note = f"Musical material: {labels}."
        if row.probe and key(row.probe) != key(row.interval):
            p = row.probe
            note += (f" Instrument detail covers {span(p.original_start, p.original_end)} in the original"
                     f" and {span(p.new_start, p.new_end)} in the new track.")
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
                where = "Surrounding texture" if scope == "context" else "Texture"
                notes.append(f"{where} in the {name}: estimated {label} at {span(start, end)}.")
    return " ".join(notes)


def fragment(value, limit=24):
    """Keep a preset's first thought brief; full supplied values stay in the appendix."""
    text = " ".join(str(value).split())
    text = re.split(r"[.!?](?:\s|$)", text, maxsplit=1)[0]
    words = text.split()
    return " ".join(words[:limit]).rstrip(".,;:!?") + ("…" if len(words) > limit else "")


def feature(path, name):
    return next((str(f.value) for f in path.describe.elements if f.feature == name and f.value), "")


def role_sentence(path, intervals, rows, repeated):
    from lastrada.reporting.prose import arrangement, named_parts, role_preset, structure

    element = feature(path, "musical_element")
    parts = named_parts(element)
    supplied = path.describe.role_in_new_song or ""
    defaults = {ROLE_UNKNOWN, role_preset(element.split(",")), "Recurring musical texture",
                "A brief musical accent", "An extended musical layer", "Musical layer in the located passages"}
    if supplied and supplied not in defaults:
        return f"Its role in the arrangement is “{fragment(supplied)}”."
    return arrangement(parts) or structure(path.classification.placement, repeated,
                                           max((i.new_end - i.new_start for i in intervals), default=0) <= 8)


def narrative(analysis, paths, model_name=None):
    """Two short musical paragraphs; review diagnostics stay in the analysis."""
    from lastrada.reporting.prose import named_parts, structure

    stories = []
    for rights, value in paths.items():
        path = PathResult.model_validate(value)
        if path.locate.detection_status == "not_requested":
            continue
        if path.locate.detection_status == "not_detected":
            stories.append((["The saved review records no recording sample." if rights == "master"
                             else "The saved review records no separate replayed melody or re-sung lyrics."], []))
            continue
        intervals = path.locate.sample_occurrences
        if not intervals:
            stories.append((["No passage is selected for this Nature of Use."], []))
            continue
        established = path.locate.detection_status == "verified" or automatic_path(path)
        element = feature(path, "musical_element")
        parts = named_parts(element)
        common = {"vocals": "a vocal phrase", "bass": "a bass part", "guitar": "a guitar part",
                  "piano": "a piano part", "drums": "a drum part", "other": "an instrumental texture"}
        if len(parts) == 1:
            material = common[parts[0]]
        elif len(parts) > 2:
            material = "a layered vocal and instrumental passage" if "vocals" in parts else "a layered instrumental passage"
        elif parts:
            material = "a passage combining " + sounds(parts)
        elif not element or element.startswith("Sampled passage"):
            material = "a musical passage"
        else:
            material = f"the musical material “{fragment(element)}”"
        new = " ".join(analysis.input.new_work.title.split())
        original = " ".join(analysis.input.original_work.title.split())
        placement = PLACEMENT_TEXT.get(path.classification.placement, "in the located passages")
        location = " " + placement if path.classification.placement != "one_time" else ""
        method = path.describe.reuse_type or ""
        replayed = rights == "publishing" or "replay" in method.lower() or "re-sang" in method.lower()
        verb = "reworks" if replayed else "draws on"
        opening = (f"“{new}” {verb} {material} from “{original}”{location}." if established else
                   f"The proposed use in “{new}” centers on {material} from “{original}”{location}.")
        first = min(intervals, key=lambda i: (i.new_start, i.new_end))
        if first.original_start is not None:
            example = (f"The excerpt at {span(first.original_start, first.original_end)} in the original recording "
                       f"{'appears at' if established else 'is paired with'} {span(first.new_start, first.new_end)} in the new track.")
        else:
            example = f"The selected passage runs from {span(first.new_start, first.new_end)} in the new track."
        facts = [opening, example]
        if method and method not in METHOD_DEFAULTS:
            facts.append(f"The treatment of the passage is “{fragment(method, 18)}”.")
        families = group_loop_families(intervals, analysis.durations["new"])
        repetition = path.describe.repetition or ""
        repeated = any(f.occurrence_count > 1 for f in families) and repetition not in {"Used once", "One continuous appearance"}
        interpretation = [role_sentence(path, intervals, {}, repeated)]
        structural = structure(path.classification.placement, repeated,
                               max(i.new_end - i.new_start for i in intervals) <= 8)
        if structural != interpretation[0]:
            interpretation.append(structural)
        if repetition and repetition not in {"Used once", "One continuous appearance", "Recurs in multiple passages",
                                            "Repeated throughout the track", "Repeated in the selected sections"} and not repetition.startswith("Repetition not"):
            if repetition == "A short loop repeated in the track":
                interpretation.append("The excerpt is used as a short repeating loop.")
            else:
                interpretation.append(f"The repetition follows the selected pattern: “{fragment(repetition, 14)}”.")
        lyrics = feature(path, "lyrics")
        if lyrics:
            interpretation.append(f"The borrowed lyric phrase is “{fragment(lyrics, 14)}”.")
        stories.append((facts, interpretation[:4]))
    if len(stories) == 1:
        return "\n\n".join(" ".join(part) for part in stories[0] if part)
    return "\n\n".join(" ".join(facts[:3] + interpretation[:1]) for facts, interpretation in stories[:2])


def evidence_lines(analysis, paths, model_name=None):
    """Every selected row, with actual sound/probe scope, after the short story."""
    rows = {key(row.interval): row for row in occurrence_rows(analysis, model_name)}
    lines = []
    for rights, path in paths.items():
        if path.locate.detection_status == "not_requested":
            continue
        lines.append("Recording sample (master)" if rights == "master" else "Replayed melody or lyrics (publishing)")
        automatic = automatic_path(path)
        for n, item in enumerate(path.locate.sample_occurrences, 1):
            approx = "≈ " if item.end_review else ""
            lines.append(f"{n}. In new track: {timestamp(item.new_start)}–{approx}{timestamp(item.new_end)}; "
                         f"in original: {timestamp(item.original_start)}–{approx}{timestamp(item.original_end)}")
            if rights == "master":
                note = sound_note(rows.get(key(item)))
                if note:
                    lines.append("   " + note)
        families = group_loop_families(path.locate.sample_occurrences, analysis.durations["new"])
        for family in families:
            if family.occurrence_count > 1:
                lines.append(f"Group {family.family_number}: {family.occurrence_count} appearances ({family.candidate_count} timing rows).")
        if (path.locate.detection_status == "verified" or automatic) and path.locate.total_covered_seconds is not None and path.locate.coverage_percentage is not None:
            label = "Located portions" if automatic and has_partial_matches(path.locate.sample_occurrences) else "Estimated total use" if automatic else "Reviewed total use"
            lines.append(f"{label}: {path.locate.total_covered_seconds:.2f}s ({path.locate.coverage_percentage:.1f}% of the new track)")
        # Preserve long creator-supplied presets outside the bounded narrative.
        for label, value in [("Sound", feature(path, "musical_element")), ("How used", path.describe.reuse_type),
                             ("Repetition", path.describe.repetition), ("Role", path.describe.role_in_new_song)]:
            if value and value not in METHOD_DEFAULTS | {ROLE_UNKNOWN} and not value.startswith("Repetition not") and fragment(value, 14) != value.rstrip(".!?"):
                lines.append(f"{label} (full description): {value}")
        if feature(path, "lyrics"):
            lines.append("Reused lyrics supplied for this draft: " + feature(path, "lyrics"))
        lines.append("")
    return lines
