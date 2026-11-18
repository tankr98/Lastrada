from pathlib import Path

import numpy as np
import pytest

from lastrada.alignment import stems
from lastrada.alignment.dtw import DTWRefinementResult, refine_candidate_rhythm_details
from lastrada.alignment.mixture import refine_candidate_mixture_details
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval
from lastrada.separation.demucs import SeparatedRegion


def _audio(samples, sample_rate=16000):
    samples = np.asarray(samples, dtype=np.float32)
    return Audio(samples, sample_rate, len(samples) / sample_rate)


def _zeros(seconds, sample_rate=16000):
    return _audio(np.zeros(int(seconds * sample_rate), dtype=np.float32), sample_rate)


def _percussion_pattern(seconds=4.0, sample_rate=16000):
    samples = np.zeros(int(seconds * sample_rate), dtype=np.float32)
    hits = [
        (0.20, 1.0),
        (0.70, 0.7),
        (1.20, 1.0),
        (1.70, 0.6),
        (2.20, 1.0),
        (2.70, 0.8),
        (3.20, 1.0),
        (3.70, 0.7),
    ]
    for index, (time, amplitude) in enumerate(hits):
        left = int(time * sample_rate)
        length = int(0.05 * sample_rate)
        generator = np.random.default_rng(index + 17)
        burst = generator.standard_normal(length)
        burst *= np.exp(-np.arange(length) / (0.008 * sample_rate))
        right = min(len(samples), left + length)
        samples[left:right] += amplitude * burst[: right - left]
    return samples


def _melody(notes, sample_rate=16000, note_seconds=0.5):
    time = np.arange(int(sample_rate * note_seconds)) / sample_rate
    window = np.hanning(len(time))
    parts = []
    for note in notes:
        fundamental = 440.0 * 2 ** ((note - 69) / 12)
        tone = sum(
            np.sin(2 * np.pi * fundamental * harmonic * time) / harmonic
            for harmonic in range(1, 5)
        )
        parts.append(tone * window)
    return np.concatenate(parts).astype(np.float32)


def _four_second_interval():
    return Interval(
        new_start=1.0,
        new_end=5.0,
        original_start=0.0,
        original_end=4.0,
        source="sampleid",
        status="candidate",
    )


def test_derivative_only_path_checks_all_six_stems(monkeypatch, tmp_path):
    original = _zeros(20)
    derivative = _zeros(40)
    stem_audio = _zeros(12)
    calls = []
    methods = []

    class FakeSeparator:
        def separate_region(self, audio, start, end, padding_seconds=4.0):
            calls.append((audio, start, end, padding_seconds))
            assert audio is derivative
            return SeparatedRegion(
                stems={
                    "bass": stem_audio,
                    "drums": stem_audio,
                    "other": stem_audio,
                    "vocals": stem_audio,
                    "guitar": stem_audio,
                    "piano": stem_audio,
                },
                offset_seconds=18.0,
                candidate_start_local=start - 18.0,
                candidate_end_local=end - 18.0,
                crop_duration=12.0,
                model_name="fake_6s",
                cache_path=Path(tmp_path),
            )

    def accepted(method):
        def run(_source, _target, interval, **kwargs):
            label = kwargs.get("stem")
            methods.append(f"{method}:{label}" if label else method)
            refined = Interval(
                new_start=interval.new_start,
                new_end=interval.new_end,
                original_start=interval.original_start,
                original_end=interval.original_end,
                source=method,
                status="candidate",
                similarity=interval.similarity,
            )
            return DTWRefinementResult(
                interval=refined,
                accepted=True,
                reason="test",
                mean_cost=0.1,
                duration_ratio=1.0,
            )

        return run

    monkeypatch.setattr(stems, "refine_candidate_rhythm_details", accepted("rhythm"))
    monkeypatch.setattr(stems, "refine_candidate_mixture_details", accepted("mixture"))

    def old_symmetric_matcher(*_args, **_kwargs):
        raise AssertionError("isolated stems must not use symmetric full-mix chroma")

    monkeypatch.setattr(stems, "refine_candidate_dtw_details", old_symmetric_matcher)

    interval = Interval(
        new_start=20.0,
        new_end=24.0,
        original_start=6.0,
        original_end=10.0,
        source="sampleid",
        status="candidate",
        similarity=0.9,
    )
    result = stems.compare_candidate_stems(
        original,
        derivative,
        interval,
        FakeSeparator(),
        include_full_mix=False,
    )

    assert len(calls) == 1
    assert result.source_region.model_name == "original_full_mix"
    assert set(result.source_region.stems) == {"full_mix"}
    assert {(item.source_stem, item.derivative_stem) for item in result.evidence} == {
        ("bass", "bass"),
        ("drums", "drums"),
        ("other", "other"),
        ("vocals", "vocals"),
        ("guitar", "guitar"),
        ("piano", "piano"),
    }
    assert sorted(methods) == [
        "mixture:bass",
        "mixture:guitar",
        "mixture:other",
        "mixture:piano",
        "mixture:vocals",
        "rhythm",
    ]
    assert all("original full-mix passage" in item.reason for item in result.evidence)


@pytest.mark.parametrize("stem", ["bass", "guitar", "piano", "vocals", "other"])
def test_mixture_refiner_finds_tonal_stem_inside_dense_source_mix(stem):
    sample_rate = 16000
    melody = _melody([60, 64, 67, 69, 67, 64, 62, 60], sample_rate)
    time = np.arange(len(melody)) / sample_rate
    generator = np.random.default_rng(82)
    source_mix = (
        melody
        + 0.45 * np.sin(2 * np.pi * 110 * time)
        + 0.30 * np.sin(2 * np.pi * 330 * time)
        + 0.12 * generator.standard_normal(len(melody))
    ).astype(np.float32)
    derivative = np.pad(melody, (sample_rate, sample_rate))

    result = refine_candidate_mixture_details(
        _audio(source_mix, sample_rate),
        _audio(derivative, sample_rate),
        _four_second_interval(),
        stem=stem,
        search_padding=0.5,
        max_pitch_shift_semitones=0,
    )

    assert result.accepted
    assert result.interval.source == "dtw_mixture_chroma_local_alignment"
    assert result.mean_cost is not None and result.mean_cost <= 0.58
    assert result.interval.new_start < 1.30
    assert result.interval.new_end > 4.70


def test_mixture_refiner_rejects_unrelated_tonal_sequence():
    sample_rate = 16000
    source = _melody([60, 64, 67, 69, 67, 64, 62, 60], sample_rate)
    unrelated = _melody([61, 63, 66, 68, 65, 63, 61, 58], sample_rate)

    result = refine_candidate_mixture_details(
        _audio(source, sample_rate),
        _audio(np.pad(unrelated, (sample_rate, sample_rate)), sample_rate),
        _four_second_interval(),
        stem="guitar",
        search_padding=0.5,
        max_pitch_shift_semitones=0,
    )

    assert not result.accepted
    assert "mixture-aware harmonic alignment" in result.reason


def test_mixture_refiner_rejects_stationary_tone():
    sample_rate = 16000
    time = np.arange(4 * sample_rate) / sample_rate
    tone = np.sin(2 * np.pi * 440 * time).astype(np.float32)

    result = refine_candidate_mixture_details(
        _audio(tone, sample_rate),
        _audio(np.pad(tone, (sample_rate, sample_rate)), sample_rate),
        _four_second_interval(),
        stem="vocals",
        search_padding=0.5,
        max_pitch_shift_semitones=0,
    )

    assert not result.accepted
    assert "changing pitch information" in result.reason


def test_rhythm_refiner_accepts_copied_drums_from_original_mix():
    sample_rate = 16000
    drums = _percussion_pattern(sample_rate=sample_rate)
    time = np.arange(len(drums)) / sample_rate
    source_mix = drums + 0.2 * np.sin(2 * np.pi * 220 * time).astype(np.float32)
    derivative = np.zeros(6 * sample_rate, dtype=np.float32)
    derivative[sample_rate : sample_rate + len(drums)] = drums

    result = refine_candidate_rhythm_details(
        _audio(source_mix, sample_rate),
        _audio(derivative, sample_rate),
        _four_second_interval(),
        search_padding=0.5,
    )

    assert result.accepted
    assert result.interval.source == "dtw_onset_local_alignment"
    assert result.mean_cost is not None and result.mean_cost <= 0.62
    assert result.pitch_shift_semitones is None
    assert result.interval.new_start < 1.25
    assert result.interval.new_end > 4.75


def test_rhythm_refiner_rejects_stationary_tone():
    sample_rate = 16000
    time = np.arange(4 * sample_rate) / sample_rate
    tone = np.sin(2 * np.pi * 440 * time).astype(np.float32)

    result = refine_candidate_rhythm_details(
        _audio(tone, sample_rate),
        _audio(tone, sample_rate),
        Interval(
            new_start=0.0,
            new_end=4.0,
            original_start=0.0,
            original_end=4.0,
            source="sampleid",
            status="candidate",
        ),
        search_padding=0.0,
    )

    assert not result.accepted
    assert "transient structure" in result.reason
