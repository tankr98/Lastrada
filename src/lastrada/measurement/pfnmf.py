"""Experimental Euclidean PF-NMF. Activation is not a sample detector.
Reference spectral dictionary stays fixed; new free atoms absorb residual energy.
No source timestamps, pitch estimates, instruments or probabilities are inferred.
"""

from dataclasses import dataclass
import warnings
import numpy as np
from scipy.signal import stft
from sklearn.decomposition import NMF
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from lastrada.alignment.intervals import mask_intervals, coverage
from lastrada.audio.io import prepare


@dataclass
class Measurement:
    intervals: list
    coverage_seconds: float
    coverage_percentage: float
    activation: np.ndarray
    frame_seconds: float
    reconstruction_error: float
    warnings: list[str]


def spectrogram(audio):
    _, _, z = stft(
        audio.samples, fs=audio.sample_rate, nperseg=512, noverlap=384, boundary=None, padded=True
    )
    return np.abs(z).astype(np.float64)


def measure(
    original, new, components=8, free_components=8, iterations=80, threshold=0.55, minimum=0.25
):
    if original.sample_rate != new.sample_rate:
        raise ValueError("PF-NMF requires equal normalized sample rates")
    # Preserve 16kHz input for SampleID; PF-NMF alone uses an 8kHz representation.
    if original.sample_rate != 8000:
        original = prepare(original.samples, original.sample_rate, 8000)
        new = prepare(new.samples, new.sample_rate, 8000)
    if not 0 < threshold < 1 or min(components, free_components, iterations) <= 0:
        raise ValueError("Invalid PF-NMF configuration")
    reference, target = spectrogram(original), spectrogram(new)
    frame_seconds = 128 / new.sample_rate
    notes = ["Spectral activation coverage is experimental; it is not verified sample coverage."]
    if np.max(reference) < 1e-8 or np.max(target) < 1e-8:
        return Measurement(
            [],
            0,
            0,
            np.zeros(target.shape[1]),
            frame_seconds,
            0,
            notes + ["Silent input: no usable spectral measurement."],
        )
    rng = np.random.default_rng(42)
    eps = 1e-10
    with threadpool_limits(limits=2), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        model = NMF(
            n_components=min(components, *reference.shape),
            init="random",
            random_state=42,
            max_iter=iterations,
            solver="mu",
        )
        model.fit(reference.T)
        fixed = model.components_.T.copy()
        fixed /= np.maximum(fixed.sum(axis=0, keepdims=True), eps)
        free = rng.random((target.shape[0], free_components)) + eps
        free /= free.sum(axis=0, keepdims=True)
        w = np.column_stack([fixed, free])
        h = rng.random((w.shape[1], target.shape[1])) * target.mean() + eps
        k = fixed.shape[1]
        for _ in range(iterations):
            h *= (w.T @ target) / np.maximum((w.T @ w) @ h, eps)
            # Only the free dictionary is updated. Fixed atoms remain intact.
            residual_numerator = target @ h[k:].T
            residual_denominator = (w @ h) @ h[k:].T
            w[:, k:] *= residual_numerator / np.maximum(residual_denominator, eps)
        fixed_energy = (fixed @ h[:k]).sum(axis=0)
        total_energy = (w @ h).sum(axis=0)
        activation = fixed_energy / np.maximum(total_energy, eps)
        energy = target.sum(axis=0)
        active = (activation >= threshold) & (energy > max(energy.max() * 0.01, eps))
        # Fill only internal sub-200ms gaps, reducing frame-level NMF flicker.
        # This is a synthetic-validated heuristic, not evidence of uninterrupted reuse.
        true_indices = np.flatnonzero(active)
        for left, right in zip(true_indices[:-1], true_indices[1:]):
            if (right - left - 1) * frame_seconds <= 0.2:
                active[left : right + 1] = True
        intervals = mask_intervals(active, frame_seconds, new.duration, "pfnmf_activation", minimum)
        seconds, percent = coverage(intervals, new.duration)
        error = float(np.linalg.norm(target - w @ h) / np.linalg.norm(target))
        if caught:
            notes.append("Reference NMF reached its iteration limit; inspect stability before use.")
    return Measurement(intervals, seconds, percent, activation, frame_seconds, error, notes)
