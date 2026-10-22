"""Summarize repeated timing candidates without discarding exact occurrences.

Sony and PF-NMF can emit many overlapping timing rows.  This module groups
candidates that point to the same source passage, collapses near-duplicate
new-song windows, and produces reviewer-facing loop/use summaries.  The raw
intervals remain available for audit and manual correction.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from lastrada.schemas.models import Interval


@dataclass(frozen=True)
class LoopFamily:
    family_number: int
    source_start: float | None
    source_end: float | None
    candidate_count: int
    occurrence_count: int
    first_use: float
    last_use: float
    coverage_seconds: float
    typical_spacing_seconds: float | None
    regular_spacing: bool
    pattern: str
    occurrences: tuple[Interval, ...]
    raw_candidates: tuple[Interval, ...]


def _duration(start: float, end: float) -> float:
    return max(0.0, float(end) - float(start))


def _overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    denominator = max(1e-9, min(_duration(a_start, a_end), _duration(b_start, b_end)))
    return overlap / denominator


def _representative_source(intervals: list[Interval]) -> tuple[float | None, float | None]:
    starts = [item.original_start for item in intervals if item.original_start is not None]
    ends = [item.original_end for item in intervals if item.original_end is not None]
    if not starts or not ends:
        return None, None
    return float(median(starts)), float(median(ends))


def _source_family_score(interval: Interval, family: list[Interval]) -> float:
    source_start, source_end = _representative_source(family)
    if interval.original_start is None or interval.original_end is None:
        return 1.0 if source_start is None else -1.0
    if source_start is None or source_end is None:
        return -1.0

    overlap = _overlap_ratio(
        interval.original_start,
        interval.original_end,
        source_start,
        source_end,
    )
    if overlap >= 0.35:
        return 2.0 + overlap

    center = (interval.original_start + interval.original_end) / 2.0
    family_center = (source_start + source_end) / 2.0
    tolerance = max(
        2.0,
        0.25
        * max(
            _duration(interval.original_start, interval.original_end),
            _duration(source_start, source_end),
        ),
    )
    distance = abs(center - family_center)
    if distance <= tolerance:
        return 1.0 - distance / max(tolerance, 1e-9)
    return -1.0


def _source_priority(interval: Interval) -> int:
    source = interval.source.lower()
    if "direct_waveform" in source:
        return 5
    if "stem-assisted" in source:
        return 4
    if "dtw" in source:
        return 3
    if "sampleid" in source:
        return 2
    if "expert" in source:
        return 6
    return 1


def _same_new_occurrence(a: Interval, b: Interval) -> bool:
    overlap = _overlap_ratio(a.new_start, a.new_end, b.new_start, b.new_end)
    if overlap >= 0.50:
        return True

    a_center = (a.new_start + a.new_end) / 2.0
    b_center = (b.new_start + b.new_end) / 2.0
    a_duration = _duration(a.new_start, a.new_end)
    b_duration = _duration(b.new_start, b.new_end)
    duration_ratio = max(a_duration, b_duration) / max(1e-9, min(a_duration, b_duration))
    return abs(a_center - b_center) <= 0.75 and duration_ratio <= 2.0


def _collapse_new_occurrences(intervals: list[Interval]) -> list[Interval]:
    clusters: list[list[Interval]] = []
    for interval in sorted(intervals, key=lambda item: (item.new_start, item.new_end)):
        matching = next(
            (
                cluster
                for cluster in clusters
                if any(_same_new_occurrence(interval, old) for old in cluster)
            ),
            None,
        )
        if matching is None:
            clusters.append([interval])
        else:
            matching.append(interval)

    representatives = []
    for cluster in clusters:
        representatives.append(
            max(
                cluster,
                key=lambda item: (
                    _source_priority(item),
                    -1.0 if item.similarity is None else item.similarity,
                    _duration(item.new_start, item.new_end),
                ),
            )
        )
    return sorted(representatives, key=lambda item: (item.new_start, item.new_end))


def _coverage(intervals: list[Interval]) -> float:
    if not intervals:
        return 0.0
    ranges = sorted((item.new_start, item.new_end) for item in intervals)
    total = 0.0
    current_start, current_end = ranges[0]
    for start, end in ranges[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    total += current_end - current_start
    return float(total)


def _spacing(intervals: list[Interval]) -> tuple[float | None, bool]:
    if len(intervals) < 2:
        return None, False
    starts = [item.new_start for item in intervals]
    gaps = [right - left for left, right in zip(starts, starts[1:], strict=False)]
    typical = float(median(gaps))
    if len(gaps) < 2:
        return typical, False
    deviations = [abs(gap - typical) for gap in gaps]
    regular = median(deviations) <= max(0.75, 0.20 * max(typical, 1e-9))
    return typical, bool(regular)


def _pattern(
    occurrences: list[Interval],
    candidate_count: int,
    new_duration: float | None,
    regular_spacing: bool,
    source_known: bool,
) -> str:
    count = len(occurrences)
    if not source_known:
        if candidate_count >= 3:
            return "Clustered unresolved candidates"
        return "Unresolved candidate"

    span = occurrences[-1].new_end - occurrences[0].new_start if occurrences else 0.0
    spread = span / new_duration if new_duration and new_duration > 0 else 0.0
    if count >= 3 and spread >= 0.65:
        return "Likely looped throughout"
    if count >= 3 and regular_spacing:
        return "Likely regular loop"
    if count >= 3:
        return "Repeated use"
    if count == 2:
        return "Repeated twice"
    if candidate_count >= 3:
        return "Continuous or overlapping use"
    return "Single use"


def group_loop_families(
    intervals: list[Interval] | tuple[Interval, ...],
    new_duration: float | None = None,
) -> list[LoopFamily]:
    """Group candidate rows by source passage and summarize repeated uses.

    Intervals with unknown original timestamps are placed in one unresolved
    family.  The function never deletes or mutates the raw candidates.
    """
    families: list[list[Interval]] = []
    ordered = sorted(
        intervals,
        key=lambda item: (
            item.original_start is None,
            float("inf") if item.original_start is None else item.original_start,
            item.new_start,
        ),
    )
    for interval in ordered:
        scored = [(_source_family_score(interval, family), family) for family in families]
        score, family = max(scored, default=(-1.0, None), key=lambda item: item[0])
        if family is None or score < 0:
            families.append([interval])
        else:
            family.append(interval)

    summaries = []
    for family_number, family in enumerate(families, start=1):
        occurrences = _collapse_new_occurrences(family)
        if not occurrences:
            continue
        source_start, source_end = _representative_source(family)
        typical_spacing, regular_spacing = _spacing(occurrences)
        summaries.append(
            LoopFamily(
                family_number=family_number,
                source_start=source_start,
                source_end=source_end,
                candidate_count=len(family),
                occurrence_count=len(occurrences),
                first_use=float(occurrences[0].new_start),
                last_use=float(occurrences[-1].new_end),
                coverage_seconds=_coverage(occurrences),
                typical_spacing_seconds=typical_spacing,
                regular_spacing=regular_spacing,
                pattern=_pattern(
                    occurrences,
                    len(family),
                    new_duration,
                    regular_spacing,
                    source_start is not None,
                ),
                occurrences=tuple(occurrences),
                raw_candidates=tuple(
                    sorted(family, key=lambda item: (item.new_start, item.new_end))
                ),
            )
        )

    return sorted(
        summaries,
        key=lambda item: (
            -item.occurrence_count,
            -item.candidate_count,
            item.first_use,
        ),
    )


def format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "Unknown"
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes}:{remainder:04.1f}"


def loop_family_rows(families: list[LoopFamily]) -> list[dict]:
    rows = []
    for family in families:
        source = (
            f"{format_timestamp(family.source_start)}–{format_timestamp(family.source_end)}"
            if family.source_start is not None
            else "Source not identified"
        )
        rows.append(
            {
                "Group": family.family_number,
                "Pattern": family.pattern,
                "Source passage": source,
                "Grouped uses": family.occurrence_count,
                "Candidate rows": family.candidate_count,
                "First use": format_timestamp(family.first_use),
                "Last use": format_timestamp(family.last_use),
                "Coverage": f"{family.coverage_seconds:.1f}s",
                "Typical spacing": (
                    f"{family.typical_spacing_seconds:.1f}s"
                    if family.typical_spacing_seconds is not None
                    else "—"
                ),
            }
        )
    return rows


def raw_interval_rows(families: list[LoopFamily]) -> list[dict]:
    rows = []
    for family in families:
        for item in family.raw_candidates:
            rows.append(
                {
                    "Group": family.family_number,
                    "Method": item.source,
                    "Your track start": item.new_start,
                    "Your track end": item.new_end,
                    "Original start": item.original_start,
                    "Original end": item.original_end,
                }
            )
    return rows
