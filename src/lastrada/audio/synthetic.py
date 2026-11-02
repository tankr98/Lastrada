"""Generated signals only; never substitute these for missing real inference."""

import numpy as np
from lastrada.audio.io import prepare


def demo_pair(sr=8000):
    t = np.arange(sr * 4) / sr
    # Time-varying harmonics, deliberately distinct from the new backing track.
    frequency = 310 + 90 * np.sin(2 * np.pi * t / 2)
    phase = 2 * np.pi * np.cumsum(frequency) / sr
    original = 0.55 * np.sin(phase) + 0.2 * np.sin(2 * phase)
    new_t = np.arange(sr * 12) / sr
    new = 0.15 * np.sin(2 * np.pi * 1110 * new_t)
    new[2 * sr : 6 * sr] += original
    new[8 * sr : 12 * sr] += original
    return prepare(original, sr), prepare(new, sr), [(2.0, 6.0), (8.0, 12.0)]
