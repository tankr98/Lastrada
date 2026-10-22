import numpy as np

from lastrada.alignment.dtw import (
    duration_ratio_is_plausible,
    refine_candidate_dtw,
)
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval


def _tone(freq, seconds, sr):
    t = np.arange(int(seconds * sr)) / sr
    return 0.7 * np.sin(2 * np.pi * freq * t)


def _phrase(sr=16000):
    # Four distinct harmonic blocks to give DTW a sequence rather than one chord.
    notes = [220.0, 261.63, 329.63, 392.0]
    return np.concatenate([_tone(f, 1.0, sr) for f in notes]).astype(np.float32)


def test_duration_ratio_guardrail():
    assert duration_ratio_is_plausible(10, 7.5, 0.5, 1.5)
    assert duration_ratio_is_plausible(10, 15.0, 0.5, 1.5)
    assert not duration_ratio_is_plausible(10, 0.4, 0.5, 1.5)
    assert not duration_ratio_is_plausible(10, 20.1, 0.5, 1.5)


def test_dtw_refines_inserted_phrase_near_candidate():
    sr = 16000
    phrase = _phrase(sr)
    original_samples = np.concatenate([
        np.zeros(sr, dtype=np.float32),
        phrase,
        np.zeros(sr, dtype=np.float32),
    ])
    new_samples = np.concatenate([
        np.zeros(2 * sr, dtype=np.float32),
        phrase,
        np.zeros(2 * sr, dtype=np.float32),
    ])
    original = Audio(original_samples, sr, len(original_samples) / sr)
    new = Audio(new_samples, sr, len(new_samples) / sr)

    coarse = Interval(
        new_start=1.5,
        new_end=6.5,
        original_start=1.0,
        original_end=5.0,
        source="sampleid_chunk_cosine",
        status="candidate",
        similarity=0.95,
    )

    refined = refine_candidate_dtw(
        original,
        new,
        coarse,
        search_padding=1.0,
        max_pitch_shift_semitones=0,
        minimum_duration_ratio=0.5,
        maximum_duration_ratio=1.5,
    )

    assert refined.source == "dtw_chroma_local_alignment"
    assert abs(refined.new_start - 2.0) < 0.6
    assert abs(refined.new_end - 6.0) < 0.7
    assert refined.similarity == coarse.similarity


def test_dtw_abstains_without_source_timestamps():
    sr = 16000
    y = _phrase(sr)
    audio = Audio(y, sr, len(y) / sr)
    coarse = Interval(
        new_start=0,
        new_end=2,
        source="sampleid_chunk_cosine",
        status="candidate",
        similarity=0.8,
    )
    assert refine_candidate_dtw(audio, audio, coarse) == coarse
