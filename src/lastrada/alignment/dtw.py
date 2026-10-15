"""Guarded chroma + subsequence DTW refinement for SampleID candidates.

This module is intentionally a *refiner*, not a detector. It only runs after
SampleID has proposed a source/new-work interval pair. If DTW cannot produce a
plausible alignment under conservative duration-ratio guardrails, the original
coarse candidate is returned unchanged.
"""

from __future__ import annotations

import math
import numpy as np
from scipy.signal import resample_poly, stft
from lastrada.schemas.models import Interval


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    divisor = math.gcd(source_rate, target_rate)
    return resample_poly(
        samples, target_rate // divisor, source_rate // divisor
    ).astype(np.float32)


def _segment(audio, start: float, end: float, sample_rate: int) -> np.ndarray:
    y = _resample(audio.samples, audio.sample_rate, sample_rate)
    left = max(0, int(round(start * sample_rate)))
    right = min(len(y), int(round(end * sample_rate)))
    if right <= left:
        return np.empty(0, dtype=np.float32)
    return y[left:right]


def _chroma(samples: np.ndarray, sample_rate: int, nperseg: int = 2048, hop: int = 512):
    """Small dependency-free chroma representation built from an STFT."""
    if len(samples) < max(512, nperseg // 2):
        return np.empty((12, 0), dtype=np.float64)

    _, _, z = stft(
        samples,
        fs=sample_rate,
        nperseg=min(nperseg, len(samples)),
        noverlap=max(0, min(nperseg, len(samples)) - hop),
        boundary=None,
        padded=True,
    )
    magnitude = np.abs(z).astype(np.float64)
    freqs = np.fft.rfftfreq(min(nperseg, len(samples)), d=1.0 / sample_rate)

    valid = freqs >= 55.0
    freqs = freqs[valid]
    magnitude = magnitude[valid]
    if not len(freqs):
        return np.empty((12, 0), dtype=np.float64)

    midi = 69.0 + 12.0 * np.log2(freqs / 440.0)
    pitch_classes = np.mod(np.rint(midi).astype(int), 12)

    chroma = np.zeros((12, magnitude.shape[1]), dtype=np.float64)
    for pc in range(12):
        mask = pitch_classes == pc
        if np.any(mask):
            chroma[pc] = magnitude[mask].sum(axis=0)

    # Compress dominant bins and normalize each time frame.
    chroma = np.sqrt(np.maximum(chroma, 0.0))
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    chroma /= np.maximum(norms, 1e-12)
    return chroma


def _local_cost(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    # Chroma columns are already normalized; cosine distance is 1 - dot product.
    return 1.0 - np.clip(source.T @ target, -1.0, 1.0)


def _subsequence_dtw(cost: np.ndarray):
    """Align the full source (rows) to the best subsequence of target (columns)."""
    m, n = cost.shape
    if not m or not n:
        return None, float("inf")

    acc = np.full((m, n), np.inf, dtype=np.float64)
    back = np.full((m, n), -1, dtype=np.int8)

    # Source may begin anywhere in target.
    acc[0, :] = cost[0, :]

    for i in range(1, m):
        for j in range(n):
            choices = []
            # diagonal
            if j > 0:
                choices.append((acc[i - 1, j - 1], 0))
            # consume source while holding target
            choices.append((acc[i - 1, j], 1))
            # consume target while holding source
            if j > 0:
                choices.append((acc[i, j - 1], 2))
            best_cost, move = min(choices, key=lambda x: x[0])
            acc[i, j] = cost[i, j] + best_cost
            back[i, j] = move

    end_j = int(np.argmin(acc[-1]))
    i, j = m - 1, end_j
    path = [(i, j)]

    while i > 0:
        move = int(back[i, j])
        if move == 0:
            i -= 1
            j -= 1
        elif move == 1:
            i -= 1
        elif move == 2 and j > 0:
            j -= 1
        else:
            break
        path.append((i, j))

    path.reverse()
    mean_cost = float(acc[-1, end_j] / max(len(path), 1))
    return np.asarray(path, dtype=int), mean_cost


def duration_ratio_is_plausible(
    source_duration: float,
    derivative_duration: float,
    minimum_ratio: float = 0.5,
    maximum_ratio: float = 1.5,
) -> bool:
    if source_duration <= 0 or derivative_duration <= 0:
        return False
    ratio = derivative_duration / source_duration
    return minimum_ratio <= ratio <= maximum_ratio


def refine_candidate_dtw(
    original,
    new,
    interval: Interval,
    *,
    search_padding: float = 4.0,
    max_pitch_shift_semitones: int = 6,
    minimum_duration_ratio: float = 0.5,
    maximum_duration_ratio: float = 1.5,
    minimum_duration: float = 0.5,
    analysis_rate: int = 16000,
    hop: int = 512,
):
    """Refine one coarse SampleID candidate, conservatively.

    The original/source endpoints remain the SampleID source excerpt. DTW only
    tightens the new-work placement. Unrealistic compression/expansion is rejected.
    """
    if interval.original_start is None or interval.original_end is None:
        return interval
    if interval.original_end <= interval.original_start:
        return interval

    source_duration = interval.original_end - interval.original_start
    if source_duration < minimum_duration:
        return interval

    search_start = max(0.0, interval.new_start - search_padding)
    search_end = min(new.duration, interval.new_end + search_padding)
    if search_end - search_start < minimum_duration:
        return interval

    source_y = _segment(
        original, interval.original_start, interval.original_end, analysis_rate
    )
    target_y = _segment(new, search_start, search_end, analysis_rate)
    source_chroma = _chroma(source_y, analysis_rate, hop=hop)
    target_chroma = _chroma(target_y, analysis_rate, hop=hop)

    if source_chroma.shape[1] < 2 or target_chroma.shape[1] < 2:
        return interval

    best = None
    seconds_per_frame = hop / analysis_rate

    for shift in range(-max_pitch_shift_semitones, max_pitch_shift_semitones + 1):
        shifted = np.roll(source_chroma, shift, axis=0)
        path, mean_cost = _subsequence_dtw(_local_cost(shifted, target_chroma))
        if path is None or not len(path):
            continue

        target_frames = path[:, 1]
        refined_start = search_start + float(target_frames.min()) * seconds_per_frame
        refined_end = search_start + float(target_frames.max() + 1) * seconds_per_frame
        refined_start = max(0.0, refined_start)
        refined_end = min(new.duration, refined_end)
        derivative_duration = refined_end - refined_start

        # Reject DTW's common failure mode: collapsing a long source into a tiny
        # harmonic fragment, or stretching it implausibly far.
        if derivative_duration < minimum_duration:
            continue
        if not duration_ratio_is_plausible(
            source_duration,
            derivative_duration,
            minimum_duration_ratio,
            maximum_duration_ratio,
        ):
            continue

        # The refinement should still touch the SampleID candidate it is refining,
        # rather than silently jumping to a different nearby occurrence.
        if refined_end <= interval.new_start or refined_start >= interval.new_end:
            continue

        candidate = (mean_cost, shift, refined_start, refined_end)
        if best is None or candidate[0] < best[0]:
            best = candidate

    if best is None:
        return interval

    _, _shift, refined_start, refined_end = best
    return Interval(
        new_start=float(refined_start),
        new_end=float(refined_end),
        original_start=interval.original_start,
        original_end=interval.original_end,
        source="dtw_chroma_local_alignment",
        status="candidate",
        # Preserve SampleID's similarity as candidate evidence. DTW cost is not
        # squeezed into this calibrated-looking field.
        similarity=interval.similarity,
    )
