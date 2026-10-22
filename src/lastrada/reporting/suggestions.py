"""Timing-only suggestions. Musical identity and looping require creator confirmation."""

from dataclasses import dataclass
from statistics import median
from lastrada.alignment.intervals import merge_ranges
from lastrada.schemas.models import PathResult


@dataclass
class TimingSuggestion:
    kind: str
    question: str
    source: str


def suggested_intervals(analysis, rights):
    if analysis.review.corrected and rights in analysis.review.corrected:
        return list(
            PathResult.model_validate(analysis.review.corrected[rights]).locate.sample_occurrences
        )
    path = getattr(analysis, rights)
    if rights == "publishing":
        return list(path.locate.sample_occurrences)
    return list(path.locate.sample_occurrences or path.locate.measurement_intervals)


def timing_questions(intervals, duration):
    if not intervals or not duration:
        return []
    ranges = merge_ranges([(i.new_start, i.new_end) for i in intervals], duration)
    used = sum(e - s for s, e in ranges)
    spread = (ranges[-1][1] - ranges[0][0]) / duration
    lengths = [e - s for s, e in ranges]
    result = []
    if used / duration >= 0.6 and spread >= 0.85:
        result.append(
            TimingSuggestion(
                "throughout",
                "These estimates are spread across most of your track. Does the sample repeat throughout?",
                "estimated_timing_pattern",
            )
        )
        result.append(
            TimingSuggestion(
                "melody",
                "Does this sampled part carry the melody?",
                "creator_confirmation_required",
            )
        )
    if (
        len(ranges) >= 2
        and median(lengths) <= 8
        and max(lengths) - min(lengths) <= max(0.5, median(lengths) * 0.3)
    ):
        result.append(
            TimingSuggestion(
                "loop",
                "Several estimated moments are short and similar in length. Are they a repeating loop?",
                "estimated_timing_pattern",
            )
        )
    elif len(ranges) == 1 and lengths[0] <= 10:
        result.append(
            TimingSuggestion(
                "one_time",
                "We estimated one short moment. Is the sample used just once?",
                "estimated_timing_pattern",
            )
        )
    return result


def confirmed_prefills(kind, rights):
    # Applied only after an explicit Yes and button click; never overwrite existing edits.
    return {
        "throughout": {"placement": "throughout", "repetition": "Repeated throughout the track"},
        "melody": {
            "element": "a sampled melody" if rights == "master" else "a replayed melody",
            "role": "Carries the melody of the new track",
        },
        "loop": {"repetition": "A short loop repeated in the track"},
        "one_time": {"placement": "one_time", "repetition": "Used once"},
    }.get(kind, {})
