"""Guarded chroma + subsequence DTW refinement for SampleID candidates.

This module is intentionally a *refiner*, not a detector. It only runs after
SampleID has proposed a source/new-work interval pair. If DTW cannot produce a
plausible alignment under conservative duration-ratio guardrails, the original
coarse candidate is returned unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import resample_poly, stft

from lastrada.schemas.models import Interval


@dataclass
class DTWRefinementResult:
    """Detailed evidence from one guarded DTW attempt.

    `accepted` only means that the alignment passed the configured engineering
    guardrails. It is not a probability or verified sample conclusion.
    """

    interval: Interval
    accepted: bool
    reason: str
    mean_cost: float | None = None
    pitch_shift_semitones: int | None = None
    duration_ratio: float | None = None
    source_duration: float | None = None
    derivative_duration: float | None = None
    search_start: float | None = None
    search_end: float | None = None
    path_points: int = 0


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


def _chroma(
    samples: np.ndarray,
    sample_rate: int,
    nperseg: int = 2048,
    hop: int = 512,
):
    """Small dependency-free chroma representation built from an STFT."""
    if len(samples) < max(512, nperseg // 2):
        return np.empty((12, 0), dtype=np.float64)

    frame_size = min(nperseg, len(samples))
    _, _, z = stft(
        samples,
        fs=sample_rate,
        nperseg=frame_size,
        noverlap=max(0, frame_size - hop),
        boundary=None,
        padded=True,
    )
    magnitude = np.abs(z).astype(np.float64)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)

    valid = freqs >= 55.0
    freqs = freqs[valid]
    magnitude = magnitude[valid]
    if not len(freqs):
        return np.empty((12, 0), dtype=np.float64)

    midi = 69.0 + 12.0 * np.log2(freqs / 440.0)
    pitch_classes = np.mod(np.rint(midi).astype(int), 12)

    chroma = np.zeros((12, magnitude.shape[1]), dtype=np.float64)
    for pitch_class in range(12):
        mask = pitch_classes == pitch_class
        if np.any(mask):
            chroma[pitch_class] = magnitude[mask].sum(axis=0)

    chroma = np.sqrt(np.maximum(chroma, 0.0))
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    chroma /= np.maximum(norms, 1e-12)
    return chroma


def _local_cost(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    # Chroma columns are already normalized; cosine distance is 1 - dot product.
    return 1.0 - np.clip(source.T @ target, -1.0, 1.0)


def _subsequence_dtw(cost: np.ndarray):
    """Align the full source (rows) to the best subsequence of target (columns)."""
    source_frames, target_frames = cost.shape
    if not source_frames or not target_frames:
        return None, float("inf")

    accumulated = np.full((source_frames, target_frames), np.inf, dtype=np.float64)
    back = np.full((source_frames, target_frames), -1, dtype=np.int8)

    # The source query may begin anywhere in the target search region.
    accumulated[0, :] = cost[0, :]

    for source_index in range(1, source_frames):
        for target_index in range(target_frames):
            choices = []
            if target_index > 0:
                choices.append((accumulated[source_index - 1, target_index - 1], 0))
            choices.append((accumulated[source_index - 1, target_index], 1))
            if target_index > 0:
                choices.append((accumulated[source_index, target_index - 1], 2))
            best_cost, move = min(choices, key=lambda item: item[0])
            accumulated[source_index, target_index] = (
                cost[source_index, target_index] + best_cost
            )
            back[source_index, target_index] = move

    end_target = int(np.argmin(accumulated[-1]))
    source_index, target_index = source_frames - 1, end_target
    path = [(source_index, target_index)]

    while source_index > 0:
        move = int(back[source_index, target_index])
        if move == 0:
            source_index -= 1
            target_index -= 1
        elif move == 1:
            source_index -= 1
        elif move == 2 and target_index > 0:
            target_index -= 1
        else:
            break
        path.append((source_index, target_index))

    path.reverse()
    mean_cost = float(
        accumulated[-1, end_target] / max(len(path), 1)
    )
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


def _rejected(
    interval: Interval,
    reason: str,
    *,
    source_duration: float | None = None,
    search_start: float | None = None,
    search_end: float | None = None,
) -> DTWRefinementResult:
    return DTWRefinementResult(
        interval=interval,
        accepted=False,
        reason=reason,
        source_duration=source_duration,
        search_start=search_start,
        search_end=search_end,
    )


def refine_candidate_dtw_details(
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
) -> DTWRefinementResult:
    """Refine one candidate and return alignment evidence plus the interval."""
    if interval.original_start is None or interval.original_end is None:
        return _rejected(interval, "source timestamps unavailable")
    if interval.original_end <= interval.original_start:
        return _rejected(interval, "invalid source interval")

    source_duration = interval.original_end - interval.original_start
    if source_duration < minimum_duration:
        return _rejected(
            interval,
            "source interval shorter than minimum duration",
            source_duration=source_duration,
        )

    search_start = max(0.0, interval.new_start - search_padding)
    search_end = min(new.duration, interval.new_end + search_padding)
    if search_end - search_start < minimum_duration:
        return _rejected(
            interval,
            "derivative search region shorter than minimum duration",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    source_y = _segment(
        original,
        interval.original_start,
        interval.original_end,
        analysis_rate,
    )
    target_y = _segment(new, search_start, search_end, analysis_rate)
    source_chroma = _chroma(source_y, analysis_rate, hop=hop)
    target_chroma = _chroma(target_y, analysis_rate, hop=hop)

    if source_chroma.shape[1] < 2 or target_chroma.shape[1] < 2:
        return _rejected(
            interval,
            "not enough chroma frames",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    best = None
    seconds_per_frame = hop / analysis_rate

    for shift in range(-max_pitch_shift_semitones, max_pitch_shift_semitones + 1):
        shifted = np.roll(source_chroma, shift, axis=0)
        path, mean_cost = _subsequence_dtw(_local_cost(shifted, target_chroma))
        if path is None or not len(path):
            continue

        matched_target_frames = path[:, 1]
        refined_start = (
            search_start + float(matched_target_frames.min()) * seconds_per_frame
        )
        refined_end = (
            search_start
            + float(matched_target_frames.max() + 1) * seconds_per_frame
        )
        refined_start = max(0.0, refined_start)
        refined_end = min(new.duration, refined_end)
        derivative_duration = refined_end - refined_start

        if derivative_duration < minimum_duration:
            continue
        if not duration_ratio_is_plausible(
            source_duration,
            derivative_duration,
            minimum_duration_ratio,
            maximum_duration_ratio,
        ):
            continue
        if refined_end <= interval.new_start or refined_start >= interval.new_end:
            continue

        candidate = {
            "mean_cost": float(mean_cost),
            "pitch_shift": int(shift),
            "refined_start": float(refined_start),
            "refined_end": float(refined_end),
            "duration": float(derivative_duration),
            "path_points": int(len(path)),
        }
        if best is None or candidate["mean_cost"] < best["mean_cost"]:
            best = candidate

    if best is None:
        return _rejected(
            interval,
            "no alignment passed overlap and duration guardrails",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    refined = Interval(
        new_start=best["refined_start"],
        new_end=best["refined_end"],
        original_start=interval.original_start,
        original_end=interval.original_end,
        source="dtw_chroma_local_alignment",
        status="candidate",
        similarity=interval.similarity,
    )
    return DTWRefinementResult(
        interval=refined,
        accepted=True,
        reason="alignment passed guardrails",
        mean_cost=best["mean_cost"],
        pitch_shift_semitones=best["pitch_shift"],
        duration_ratio=best["duration"] / source_duration,
        source_duration=source_duration,
        derivative_duration=best["duration"],
        search_start=search_start,
        search_end=search_end,
        path_points=best["path_points"],
    )


def refine_candidate_dtw(
    original,
    new,
    interval: Interval,
    **kwargs,
):
    """Compatibility wrapper returning only the refined or original interval."""
    return refine_candidate_dtw_details(original, new, interval, **kwargs).interval
