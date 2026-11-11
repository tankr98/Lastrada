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


def fragment(value, limit=24):
    """Keep a preset's first thought brief; full supplied values stay in the appendix."""
    text = " ".join(str(value).split())
    text = re.split(r"[.!?](?:\s|$)", text, maxsplit=1)[0]
    words = text.split()
    return " ".join(words[:limit]).rstrip(".,;:!?") + ("…" if len(words) > limit else "")


def feature(path, name):
    return next((str(f.value) for f in path.describe.elements if f.feature == name and f.value), "")


def role_sentence(path, intervals, rows, repeated):
    """A musical interpretation, explicitly tentative and tied to measured evidence."""
    supplied = path.describe.role_in_new_song
    if supplied and supplied != ROLE_UNKNOWN:
        return f"The intended musical role is described as “{fragment(supplied)}”."
    labels = {label.lower() for i in intervals for row in [rows.get(key(i))]
              if row and row.status == "checked" and not row.context_only
              for label in row.suggested_instruments}
    placement = path.classification.placement
    if placement in {"intro_outro_without_chorus", "intro_outro_with_chorus"}:
        thought = "the opening and closing placement could give the track a shared musical motif"
    elif placement == "intro_only":
        thought = ("the vocal material at the opening could act as an introductory motif, giving the track a recognizable point of entry"
                   if "vocals" in labels else "its opening placement could introduce a musical motif that sets the track’s character")
    elif placement == "outro_only":
        thought = ("the closing vocal material could give the ending a recognizable vocal signature"
                   if "vocals" in labels else "its closing placement could give the ending a recognizable musical signature")
    elif repeated and labels & {"bass", "drums"}:
        thought = "the repeated bass and percussion in the checked audio could provide a rhythmic foundation"
        if "bass" not in labels:
            thought = thought.replace("bass and percussion", "percussion")
        elif "drums" not in labels:
            thought = thought.replace("bass and percussion", "bass")
    elif repeated and "vocals" in labels:
        thought = "the recurring vocal material in the checked audio could act as a refrain linking the passages"
    elif repeated:
        thought = "the recurring material could provide a musical thread linking the passages"
    elif has_partial_matches(intervals):
        thought = "the checked portion could contribute a musical layer, although its wider role remains unclear"
    elif intervals and max(i.new_end - i.new_start for i in intervals) <= 8:
        thought = "its brief duration suggests it could act as a musical accent"
    else:
        thought = "its sustained presence could provide a continuing musical layer"
    if path.locate.detection_status != "verified" and not automatic_path(path):
        return "If the suggested match is correct, " + thought + "."
    return thought[0].upper() + thought[1:] + "."


def narrative(analysis, paths, model_name=None):
    """At most two short paragraphs; detailed evidence belongs in the appendix."""
    rows = {key(row.interval): row for row in occurrence_rows(analysis, model_name)}
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
        established = path.locate.detection_status == "verified" or automatic_path(path)
        if not intervals:
            stories.append((["The analysis has not located a passage to describe.",
                             "Source and new-track timestamps, instruments and musical role remain unresolved."], []))
            continue
        description = path.describe
        element = feature(path, "musical_element")
        common = {"Vocals": "a vocal passage", "Bass": "a bass part", "Guitar": "a guitar part",
                  "Piano": "a piano part", "Drums": "a drum part",
                  "Sampled passage — instrument not identified": "a passage with unresolved instrumentation"}
        material = common.get(element, f"material described as “{fragment(element)}”") if element else "a musical passage"
        labels = [part.strip() for part in element.split(",")]
        if len(labels) > 1 and all(label in {"Vocals", "Bass", "Guitar", "Piano", "Drums", "Other"} for label in labels):
            material = "a passage containing " + sounds(labels)
        source_note = ""
        if element.startswith("Sampled passage; source sounds include "):
            material = "a musical passage"
            source_note = ", with " + fragment(element.split("include ", 1)[1], 14) + " estimated in the source"
        new = " ".join(analysis.input.new_work.title.split())
        original = " ".join(analysis.input.original_work.title.split())
        opening = f"“{new}” {'draws on' if established else 'may draw on'} {material} from “{original}”" + source_note
        if not established:
            opening += ", although recording reuse remains unconfirmed" if rights == "master" else ", although musical reuse remains unconfirmed"
        method = description.reuse_type
        if method and method not in {METHOD_UNCONFIRMED, "Sampled the original recording"}:
            opening += f", with the use described as “{fragment(method, 14)}”"
        opening += "."
        families = group_loop_families(intervals, analysis.durations["new"])
        first = min(intervals, key=lambda i: (i.new_start, i.new_end))
        source = (f"the passage at {span(first.original_start, first.original_end)} in the original recording"
                  if first.original_start is not None else "a passage whose position in the original recording is unknown")
        example = f"For example, {source} {'appears' if established else 'may appear'} at {span(first.new_start, first.new_end)} in the new track."
        placement = PLACEMENT_TEXT.get(path.classification.placement, "in the located passages")
        repetition = description.repetition or ""
        if repetition in {"Recurs in multiple passages", "Repeated throughout the track", "Repeated in the selected sections"}:
            usage = f"The material recurs {placement}"
        elif repetition == "A short loop repeated in the track":
            usage = f"The recurring pattern {placement} suggests a loop"
        else:
            usage = f"The passage is placed {placement}"
            if repetition not in {"Used once", "One continuous appearance", ""} and not repetition.startswith("Repetition not"):
                usage += f", with repetition described as “{fragment(repetition, 14)}”"
        usage += "."
        interpretation = [role_sentence(path, intervals, rows if rights == "master" else {},
                                        any(f.occurrence_count > 1 for f in families))]
        lyrics = feature(path, "lyrics")
        if lyrics:
            interpretation.append(f"The supplied lyric excerpt is “{fragment(lyrics, 14)}”.")
        limits = []
        if has_partial_matches(intervals):
            limits.append("only checked portions are located, so reuse may extend further or recur elsewhere")
        if any(i.end_review for i in intervals):
            limits.append("some endings are uncertain and may extend beyond the displayed times")
        if any(row and (row.context_only or (row.probe and key(row.probe) != key(i)))
               for i in intervals for row in [rows.get(key(i))]):
            limits.append("instrument estimates apply only to the checked audio")
        if limits:
            interpretation.append("These details remain estimates: " + "; ".join(limits) + ".")
        stories.append(([opening, example, usage], interpretation))
    if len(stories) == 1:
        return "\n\n".join(" ".join(part) for part in stories[0] if part)
    # Legacy cases can have recording and composition paths. Keep one paragraph
    # per path; their full descriptions and caveats remain in the evidence list.
    return "\n\n".join(" ".join(facts[:3] + interpretation[:1])
                        for facts, interpretation in stories[:2])


def evidence_lines(analysis, paths, model_name=None):
    """Every selected row, with actual sound/probe scope, after the short story."""
    rows = {key(row.interval): row for row in occurrence_rows(analysis, model_name)}
    lines = []
    for rights, path in paths.items():
        if path.locate.detection_status == "not_requested":
            continue
        lines.append("Recording sample (master)" if rights == "master" else "Replayed melody or lyrics (publishing)")
        automatic = automatic_path(path)
        if automatic:
            lines.append("Sample timings are automatically estimated; description reviewed separately.")
        elif path.locate.detection_status not in {"verified", "not_detected"}:
            lines.append("Use has not been confirmed. Automated matching needs listening review.")
        elif path.locate.detection_status == "not_detected":
            lines.append("No reuse identified in this rights path; this is not a legal conclusion.")
        for n, item in enumerate(path.locate.sample_occurrences, 1):
            approx = "≈ " if item.end_review else ""
            lines.append(f"{n}. In new track: {timestamp(item.new_start)}–{approx}{timestamp(item.new_end)}; "
                         f"in original: {timestamp(item.original_start)}–{approx}{timestamp(item.original_end)}")
            if rights == "master":
                lines.append("   " + sound_note(rows.get(key(item))))
        if any(i.end_review for i in path.locate.sample_occurrences):
            lines.append("Some endings are uncertain and may extend beyond the estimated times.")
        families = group_loop_families(path.locate.sample_occurrences, analysis.durations["new"])
        for family in families:
            if family.occurrence_count > 1:
                qualifier = "" if path.locate.detection_status == "verified" or automatic else "possible "
                lines.append(f"Group {family.family_number}: {family.occurrence_count} {qualifier}appearances ({family.candidate_count} timing rows).")
        if (path.locate.detection_status == "verified" or automatic) and path.locate.total_covered_seconds is not None and path.locate.coverage_percentage is not None:
            label = "Located portions" if automatic and has_partial_matches(path.locate.sample_occurrences) else "Estimated total use" if automatic else "Reviewed total use"
            lines.append(f"{label}: {path.locate.total_covered_seconds:.2f}s ({path.locate.coverage_percentage:.1f}% of the new track)")
        # Preserve long creator-supplied presets outside the bounded narrative.
        for label, value in [("Sound", feature(path, "musical_element")), ("How used", path.describe.reuse_type),
                             ("Repetition", path.describe.repetition), ("Role", path.describe.role_in_new_song)]:
            if value and fragment(value, 14) != value.rstrip(".!?"):
                lines.append(f"{label} (full description): {value}")
        if feature(path, "lyrics"):
            lines.append("Reused lyrics supplied for this draft: " + feature(path, "lyrics"))
        lines.extend(path.describe.limitations)
        lines.append("")
    return lines
