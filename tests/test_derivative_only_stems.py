from pathlib import Path

import numpy as np

from lastrada.alignment import stems
from lastrada.alignment.dtw import DTWRefinementResult, refine_candidate_rhythm_details
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
    hits = [(0.20, 1.0), (0.70, 0.7), (1.20, 1.0), (1.70, 0.6),
            (2.20, 1.0), (2.70, 0.8), (3.20, 1.0), (3.70, 0.7)]
    for index, (time, amplitude) in enumerate(hits):
        left = int(time * sample_rate)
        length = int(0.05 * sample_rate)
        generator = np.random.default_rng(index + 17)
        burst = generator.standard_normal(length)
        burst *= np.exp(-np.arange(length) / (0.008 * sample_rate))
        right = min(len(samples), left + length)
        samples[left:right] += amplitude * burst[: right - left]
    return samples


def test_derivative_only_path_separates_new_audio_once(monkeypatch, tmp_path):
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
                stems={"drums": stem_audio, "guitar": stem_audio},
                offset_seconds=18.0,
                candidate_start_local=start - 18.0,
                candidate_end_local=end - 18.0,
                crop_duration=12.0,
                model_name="fake_6s",
                cache_path=Path(tmp_path),
            )

    def accepted(method):
        def run(_source, _target, interval, **_kwargs):
            methods.append(method)
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
    monkeypatch.setattr(stems, "refine_candidate_dtw_details", accepted("chroma"))

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
        ("drums", "drums"),
        ("guitar", "guitar"),
    }
    assert sorted(methods) == ["chroma", "rhythm"]
    assert all("original full-mix passage" in item.reason for item in result.evidence)


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
        Interval(
            new_start=1.0,
            new_end=5.0,
            original_start=0.0,
            original_end=4.0,
            source="sampleid",
            status="candidate",
        ),
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
