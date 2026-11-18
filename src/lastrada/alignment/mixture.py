"""Mixture-aware alignment for an isolated derivative stem against a source mix.

The source passage may contain many simultaneous instruments. Unlike symmetric
chroma cosine distance, the containment cost asks whether the ordered pitch
content of the isolated derivative stem is supported inside the source mix.
Additional source instruments therefore do not automatically count against the
candidate. Results remain engineering evidence that requires listening review.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import stft

from lastrada.alignment.dtw import (
    DTWRefinementResult,
    _rejected,
    _segment,
    _subsequence_dtw,
    duration_ratio_is_plausible,
)
from lastrada.schemas.models import Interval


_STEM_BANDS = {
    "bass": (35.0, 1600.0),
    "vocals": (70.0, 5000.0),
    "guitar": (55.0, 5000.0),
    "piano": (27.5, 6000.0),
    "other": (45.0, 7000.0),
}


def _containment_chroma(
    samples: np.ndarray,
    sample_rate: int,
    *,
    band: tuple[float, float],
    target: bool,
    nperseg: int = 2048,
    hop: int = 512,
    context_frames: int = 5,
):
    """Return context chroma plus its per-frame, pre-context representation."""
    if len(samples) < max(512, nperseg // 2):
        return (
            np.empty((12 * context_frames, 0), dtype=np.float64),
            np.empty((12, 0), dtype=np.float64),
        )

    frame_size = min(nperseg, len(samples))
    frequencies, _, spectrum = stft(
        samples,
        fs=sample_rate,
        nperseg=frame_size,
        noverlap=max(0, frame_size - hop),
        boundary=None,
        padded=True,
    )
    magnitude = np.abs(spectrum).astype(np.float64)
    valid = (frequencies >= band[0]) & (
        frequencies <= min(float(band[1]), sample_rate / 2.0)
    )
    frequencies = frequencies[valid]
    magnitude = magnitude[valid]
    if not len(frequencies):
        return (
            np.empty((12 * context_frames, 0), dtype=np.float64),
            np.empty((12, 0), dtype=np.float64),
        )

    midi = 69.0 + 12.0 * np.log2(frequencies / 440.0)
    pitch_classes = np.mod(np.rint(midi).astype(int), 12)
    chroma = np.zeros((12, magnitude.shape[1]), dtype=np.float64)
    for pitch_class in range(12):
        mask = pitch_classes == pitch_class
        if np.any(mask):
            chroma[pitch_class] = magnitude[mask].sum(axis=0)

    chroma = np.sqrt(np.maximum(chroma, 0.0))
    floor = np.percentile(chroma, 35, axis=0, keepdims=True)
    chroma = np.maximum(chroma - floor, 0.0)

    if target:
        # The isolated stem supplies weights: strong pitch classes matter most.
        chroma = chroma**1.25
        chroma /= np.maximum(chroma.sum(axis=0, keepdims=True), 1e-12)
    else:
        # The source mix supplies support. Max normalization and weak-bin
        # suppression keep additional instruments from dominating the distance.
        chroma /= np.maximum(chroma.max(axis=0, keepdims=True), 1e-12)
        chroma = np.clip((chroma - 0.12) / 0.88, 0.0, 1.0)

    left = context_frames // 2
    right = context_frames - 1 - left
    padded = np.pad(chroma, ((0, 0), (left, right)), mode="edge")
    features = np.concatenate(
        [padded[:, index : index + chroma.shape[1]] for index in range(context_frames)],
        axis=0,
    )
    if target:
        features /= np.maximum(features.sum(axis=0, keepdims=True), 1e-12)
    return features, chroma


def _shift_context(features: np.ndarray, semitones: int) -> np.ndarray:
    if not semitones:
        return features
    context_frames = features.shape[0] // 12
    blocks = features.reshape(context_frames, 12, features.shape[1])
    return np.roll(blocks, semitones, axis=1).reshape(features.shape)


def _containment_cost(source_support: np.ndarray, target_weights: np.ndarray) -> np.ndarray:
    # Each target column sums to one, so this is a weighted source-support score.
    support = np.clip(source_support.T @ target_weights, 0.0, 1.0)
    return np.maximum(0.0, 1.0 - support)


def refine_candidate_mixture_details(
    original,
    new,
    interval: Interval,
    *,
    stem: str,
    search_padding: float = 4.0,
    max_pitch_shift_semitones: int = 6,
    minimum_duration_ratio: float = 0.5,
    maximum_duration_ratio: float = 1.5,
    minimum_duration: float = 0.5,
    analysis_rate: int = 16000,
    hop: int = 512,
) -> DTWRefinementResult:
    """Align one isolated derivative stem to an original full-mix passage."""
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
    band = _STEM_BANDS.get(stem, _STEM_BANDS["other"])
    source_features, _ = _containment_chroma(
        source_y,
        analysis_rate,
        band=band,
        target=False,
        hop=hop,
    )
    target_features, target_chroma = _containment_chroma(
        target_y,
        analysis_rate,
        band=band,
        target=True,
        hop=hop,
    )

    if source_features.shape[1] < 2 or target_features.shape[1] < 2:
        return _rejected(
            interval,
            "not enough mixture-aware chroma frames",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )
    if np.linalg.norm(source_y) < 1e-6 or np.linalg.norm(target_y) < 1e-6:
        return _rejected(interval, "insufficient harmonic energy for stem comparison")

    # A single sustained note or chord is not distinctive enough to identify a
    # sampled element. The threshold is an abstention rule, not a probability.
    temporal_variation = float(np.mean(np.var(target_chroma, axis=1)))
    if temporal_variation < 0.001:
        return _rejected(
            interval,
            "insufficient changing pitch information in derivative stem",
        )

    best = None
    seconds_per_frame = hop / analysis_rate
    for shift in range(-max_pitch_shift_semitones, max_pitch_shift_semitones + 1):
        shifted = _shift_context(source_features, shift)
        path, mean_cost = _subsequence_dtw(
            _containment_cost(shifted, target_features)
        )
        if path is None or not len(path):
            continue

        _, reversed_cost = _subsequence_dtw(
            _containment_cost(shifted[:, ::-1], target_features)
        )
        if mean_cost > 0.58:
            continue
        if reversed_cost - mean_cost < 0.02 and mean_cost > 0.34:
            continue

        matched_target_frames = path[:, 1]
        refined_start = search_start + float(matched_target_frames.min()) * seconds_per_frame
        refined_end = (
            search_start
            + float(matched_target_frames.max()) * seconds_per_frame
            + min(2048, len(source_y)) / analysis_rate
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
            "no mixture-aware harmonic alignment passed containment, order and duration guardrails",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    refined = Interval(
        new_start=best["refined_start"],
        new_end=best["refined_end"],
        original_start=interval.original_start,
        original_end=interval.original_end,
        source="dtw_mixture_chroma_local_alignment",
        status="candidate",
        similarity=interval.similarity,
    )
    return DTWRefinementResult(
        interval=refined,
        accepted=True,
        reason=(
            "mixture-aware harmonic alignment passed containment, order and "
            "duration guardrails; listening required"
        ),
        mean_cost=best["mean_cost"],
        pitch_shift_semitones=best["pitch_shift"],
        duration_ratio=best["duration"] / source_duration,
        source_duration=source_duration,
        derivative_duration=best["duration"],
        search_start=search_start,
        search_end=search_end,
        path_points=best["path_points"],
    )
