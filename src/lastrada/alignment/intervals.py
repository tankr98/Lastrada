"""Union coverage, independent of overlapping model windows."""

import numpy as np
from lastrada.schemas.models import Interval


def merge_ranges(ranges, duration=None):
    cleaned = []
    for start, end in ranges:
        if not np.isfinite(start) or not np.isfinite(end) or start < 0 or end <= start:
            raise ValueError("Invalid interval")
        if duration is not None and end > duration + 1e-6:
            raise ValueError("Interval exceeds recording duration")
        cleaned.append((float(start), float(end)))
    merged = []
    for start, end in sorted(cleaned):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def coverage(intervals: list[Interval], duration: float):
    if not np.isfinite(duration) or duration <= 0:
        raise ValueError("Duration must be positive")
    merged = merge_ranges([(i.new_start, i.new_end) for i in intervals], duration)
    seconds = sum(end - start for start, end in merged)
    return seconds, 100 * seconds / duration


def mask_intervals(mask, frame_seconds, duration, source, minimum=0.25):
    padded = np.r_[False, np.asarray(mask, dtype=bool), False].astype(int)
    edges = np.diff(padded)
    return [
        Interval(
            new_start=s * frame_seconds, new_end=min(e * frame_seconds, duration), source=source
        )
        for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))
        if min(e * frame_seconds, duration) - s * frame_seconds >= minimum
    ]
