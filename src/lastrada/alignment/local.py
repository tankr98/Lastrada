"""Optional direct-waveform refinement. Unsupported transforms retain coarse candidates."""

import numpy as np
from scipy.signal import correlate
from lastrada.schemas.models import Interval


def refine_candidate(original, new, interval, radius=1.0, minimum_correlation=0.75):
    if original.sample_rate != new.sample_rate or interval.original_start is None:
        return interval
    sr = new.sample_rate
    source = original.samples[int(interval.original_start * sr) : int(interval.original_end * sr)]
    # Limit direct matching to the first two seconds of a candidate source window.
    source = source[: 2 * sr]
    if len(source) < sr // 2 or np.linalg.norm(source) < 1e-8:
        return interval
    left = max(0, int((interval.new_start - radius) * sr))
    right = min(len(new.samples), int((interval.new_start + radius) * sr) + len(source))
    target = new.samples[left:right]
    if len(target) < len(source):
        return interval
    numerator = correlate(target, source, mode="valid", method="fft")
    energies = (
        np.convolve(target**2, np.ones(len(source)), mode="valid")
        if len(source) < 128
        else (
            np.cumsum(np.r_[0, target.astype(np.float64) ** 2])[len(source) :]
            - np.cumsum(np.r_[0, target.astype(np.float64) ** 2])[: -len(source)]
        )
    )
    scores = numerator / np.maximum(np.sqrt(energies) * np.linalg.norm(source), 1e-12)
    best = int(np.argmax(scores))
    if scores[best] < minimum_correlation:
        return interval
    start = (left + best) / sr
    # Refine only the actual compared patch, never claim the entire grouped region was aligned.
    return Interval(
        new_start=start,
        new_end=min(start + len(source) / sr, new.duration),
        original_start=interval.original_start,
        original_end=interval.original_start + len(source) / sr,
        source="direct_waveform_local_alignment",
        status="candidate",
        similarity=float(np.clip(scores[best], -1, 1)),
    )
