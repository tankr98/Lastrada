from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from lastrada import pipeline
from lastrada.alignment import dtw
from lastrada.alignment.local import refine_candidate
from lastrada.alignment.stems import bounded_stem_probe, compare_candidate_stems
from lastrada.audio.io import Audio
from lastrada.config import Settings
from lastrada.schemas.models import Analysis, Intake, Interval, Work
from lastrada.separation.demucs import SeparatedRegion
from lastrada.separation.occurrences import record_initial_comparisons, run_occurrence_instruments
from lastrada.separation.presence import describe_region


def test_600_second_direct_match_keeps_full_times_with_bounded_real_dtw(monkeypatch):
    sr = 8000
    samples = np.random.default_rng(871).normal(0, 0.2, 600 * sr).astype(np.float32)
    audio = Audio(samples, sr, 600)
    coarse = Interval(
        new_start=0, new_end=600, original_start=0, original_end=600,
        source="sampleid_rank_sequence", status="candidate",
    )
    direct = refine_candidate(audio, audio, coarse)
    assert direct.source == "direct_waveform_local_alignment"
    assert direct.new_end == direct.original_end == 600
    crops, matrices = [], []

    class Separator:
        def separate_region(self, audio, start, end, padding_seconds):
            assert end - start <= 8
            left, right = max(0, start - padding_seconds), min(audio.duration, end + padding_seconds)
            crop = Audio(audio.samples[round(left * sr):round(right * sr)], sr, right - left)
            crops.append(crop.duration)
            return SeparatedRegion(
                stems={"full_mix": crop, "guitar": crop}, offset_seconds=left,
                candidate_start_local=start-left, candidate_end_local=end-left,
                crop_duration=crop.duration, model_name="test", cache_path=Path("unused"),
            )

    local_cost = dtw._local_cost

    def bounded_cost(source, target):
        # Check before the real quadratic allocation, not after it.
        assert source.shape[1] <= 251 and target.shape[1] <= 501
        matrices.append((source.shape[1], target.shape[1]))
        return local_cost(source, target)

    monkeypatch.setattr(dtw, "_local_cost", bounded_cost)
    settings = Settings(stem_enabled=True, stem_separation_padding_seconds=4,
                        dtw_max_pitch_shift_semitones=0)
    updated, comparisons = pipeline.stem_assist_candidates(audio, audio, [direct], Separator(), settings)
    assert updated == [direct]
    assert crops == [16, 16]
    assert matrices and max(a * b for a, b in matrices) <= 251 * 501
    comparison = comparisons[0]
    assert comparison.partial
    assert (comparison.probe.new_start, comparison.probe.new_end) == (296, 304)
    result = Analysis(case_id="long", input=Intake(
        case_id="long", original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"), analysis_scope=["master"],
    ), durations={"new": 600, "original": 600})
    result.master.locate.sample_occurrences = updated
    record_initial_comparisons(result, [direct], updated, comparisons, settings)
    saved = Analysis.model_validate_json(result.model_dump_json())
    row = saved.instrument_occurrences[0]
    assert row.interval == direct and row.probe == comparison.probe
    assert row.status == "checked" and not row.context_only
    assert all("Checked portion only" in item.interpretation for item in row.evidence)
    assert row.source_sounds and all(s.start == 296 and s.end == 304 for s in row.source_sounds)
    assert "not the full interval" in row.reason
    print({"reported_seconds": 600, "probe_seconds": 8, "separated_crops": crops,
           "dtw_matrix_shapes": matrices})


@pytest.mark.parametrize("source", ["sampleid_rank_sequence", "direct_waveform_local_alignment"])
def test_bounded_evidence_never_replaces_a_full_interval(monkeypatch, source):
    original = Interval(new_start=0, new_end=300, original_start=0, original_end=600, source=source)
    seen = []

    def compare(a, b, probe, separator, **kwargs):
        seen.append(probe)
        return SimpleNamespace(evidence=[SimpleNamespace(
            accepted=True, source_stem="guitar", derivative_stem="guitar",
            refined_new_start=148, refined_new_end=152,
        )])

    monkeypatch.setattr(pipeline, "compare_candidate_stems", compare)
    result, comparisons = pipeline.stem_assist_candidates(
        None, None, [original], None, Settings(stem_enabled=True, stem_probe_seconds=12),
    )
    assert result[0] == original and comparisons[0].partial
    if source == "sampleid_rank_sequence":
        assert len(result) == 2
        assert (result[1].new_start, result[1].new_end) == (148, 152)
        assert (result[1].original_start, result[1].original_end) == (296, 304)
        assert result[1].source == "stem-assisted DTW · guitar → guitar · checked portion"
    else:
        assert result == [original]
    assert (seen[0].new_start, seen[0].new_end) == (148, 152)
    assert (seen[0].original_start, seen[0].original_end) == (296, 304)


@pytest.mark.parametrize("accepted", [True, False])
def test_bounded_match_survives_save_review_and_export_without_accepting_coarse_times(monkeypatch, accepted):
    from lastrada.reporting.document import document_text, missing_document_inputs
    from lastrada.reporting.sample_flow import sample_review
    from lastrada.web.domain import ReviewPayload, UseReview, apply_review

    coarse = Interval(new_start=0, new_end=300, original_start=0, original_end=600,
                      source="sampleid_rank_sequence", status="candidate")
    evidence = SimpleNamespace(
        accepted=accepted, source_stem="guitar", derivative_stem="guitar", same_label=True,
        refined_new_start=148, refined_new_end=152, mean_dtw_cost=0.1,
        duration_ratio=0.5, pitch_shift_semitones=0, reason="test alignment",
    )
    fits = [evidence]
    if accepted:
        fits.append(SimpleNamespace(**(vars(evidence) | {
            "source_stem": "bass", "derivative_stem": "bass",
            "refined_new_start": 150, "refined_new_end": 156, "mean_dtw_cost": .2,
        })))
    monkeypatch.setattr(pipeline, "compare_candidate_stems", lambda *a, **kw:
                        SimpleNamespace(evidence=fits))
    settings = Settings(stem_enabled=True)
    updated, comparisons = pipeline.stem_assist_candidates(None, None, [coarse], None, settings)
    result = Analysis(case_id="bounded", input=Intake(
        case_id="bounded", original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="New", artist="Test"), analysis_scope=["master"],
    ), durations={"new": 300, "original": 600})
    result.master.locate.sample_occurrences = updated
    record_initial_comparisons(result, [coarse], updated, comparisons, settings)
    saved = Analysis.model_validate_json(result.model_dump_json())
    proposal = sample_review(saved, settings.stem_model_name)
    if not accepted:
        assert proposal["status"] == "not_identified"
        assert updated == [coarse]
        return
    assert proposal["status"] == "identified"
    assert proposal["description"]["element"] == "Guitar"
    assert "not fully assessed" in proposal["description"]["repetition"]
    assert len(proposal["intervals"]) == 1
    assert proposal["intervals"][0]["new_start"] == 148
    assert proposal["intervals"][0]["original_start"] == 296
    assert saved.master.locate.sample_occurrences[0] == coarse
    assert len(saved.instrument_occurrences) == 2
    assert saved.instrument_occurrences[1].candidate_number == 2
    assert saved.instrument_occurrences[0].suggested_instruments == ["Guitar", "Bass"]
    assert saved.instrument_occurrences[1].suggested_instruments == ["Guitar"]
    payload = ReviewPayload(workflow="sample", reviewer="Creator", approve=True,
        paths={"master": UseReview(status="confirmed", details_confirmed=True,
            **proposal["description"], sections=proposal["placement"]["values"]["sections"],
            placement=proposal["placement"]["values"]["placement"])})
    reviewed = Analysis.model_validate_json(apply_review(saved, payload).model_dump_json())
    assert missing_document_inputs(reviewed) == []
    text = document_text(reviewed)
    assert "Located portions: 4.00s" in text
    assert "reuse may extend beyond them or appear elsewhere" in text
    assert "Estimated total use" not in text
    assert "2:28.00" in text and "4:56.00" in text
    assert "300.00s" not in text


def test_direct_stem_comparison_also_bounds_its_input():
    calls = []

    class StopAtSeparation:
        def separate_region(self, audio, start, end, **kwargs):
            calls.append((start, end))
            raise RuntimeError("stop before inference")

    interval = Interval(new_start=0, new_end=600, original_start=0, original_end=600, source="test")
    with pytest.raises(RuntimeError, match="stop before inference"):
        compare_candidate_stems(None, None, interval, StopAtSeparation())
    assert calls == [(296, 304)]


@pytest.mark.parametrize("reverse", [False, True])
def test_real_bounded_alignment_opens_only_the_matching_sample(reverse):
    from lastrada.reporting.sample_flow import sample_review

    sr = 8000
    rng = np.random.default_rng(991)
    t = np.arange(sr // 2) / sr
    notes = rng.integers(48, 85, 40)
    samples = np.concatenate([
        np.sin(2 * np.pi * 440 * 2 ** ((note - 69) / 12) * t) * np.sin(np.pi * t / .5)
        for note in notes
    ]).astype(np.float32)
    original = Audio(samples, sr, 20)
    copied = samples[::-1] if reverse else samples
    new = Audio(np.pad(copied, (5 * sr, 5 * sr)), sr, 30)

    class Separator:
        def separate_region(self, audio, start, end, padding_seconds):
            left, right = max(0, start - padding_seconds), min(audio.duration, end + padding_seconds)
            crop = Audio(audio.samples[round(left * sr):round(right * sr)], sr, right - left)
            return SeparatedRegion(
                stems={"full_mix": crop, "guitar": crop}, offset_seconds=left,
                candidate_start_local=start-left, candidate_end_local=end-left,
                crop_duration=crop.duration, model_name="test", cache_path=Path("unused"),
            )

    coarse = Interval(new_start=5, new_end=25, original_start=0, original_end=20,
                      source="sampleid_rank_sequence", status="candidate")
    settings = Settings(stem_enabled=True, dtw_max_pitch_shift_semitones=0)
    updated, comparisons = pipeline.stem_assist_candidates(original, new, [coarse], Separator(), settings)
    result = Analysis(case_id="control", input=Intake(
        case_id="control", original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="New", artist="Test"), analysis_scope=["master"],
    ), durations={"new": 30, "original": 20})
    result.master.locate.sample_occurrences = updated
    record_initial_comparisons(result, [coarse], updated, comparisons, settings)
    proposal = sample_review(Analysis.model_validate_json(result.model_dump_json()))
    if reverse:
        assert proposal["status"] == "not_identified"
        assert updated == [coarse]
    else:
        assert proposal["status"] == "identified"
        match = proposal["intervals"][0]
        assert match["original_start"] == 6 and match["original_end"] == 14
        assert abs(match["new_start"] - 11) < .15 and abs(match["new_end"] - 19) < .15


def test_bounded_probe_clears_only_derived_review_metadata():
    interval = Interval(new_start=1, new_end=2.5, original_start=2, original_end=3.5, source="test",
                        end_review={"new_through": 3, "original_through": 4})
    probe = bounded_stem_probe(interval)
    assert probe.new_end == interval.new_end and probe.original_end == interval.original_end
    assert probe.end_review is None and interval.end_review is not None


@pytest.mark.parametrize("reverse", [False, True])
def test_repeated_source_with_different_probes_keeps_its_measured_sounds_on_reload(reverse):
    # Both rows refer to source 0–10, but the 2x new duration narrows its source
    # probe. Bass is present only outside that narrower region; guitar spans both.
    sr = 1000
    guitar = np.ones(10 * sr, dtype=np.float32)
    bass = np.zeros_like(guitar)
    bass[sr:3 * sr] = bass[7 * sr:9 * sr] = 1
    region = SimpleNamespace(
        offset_seconds=0, crop_duration=10, candidate_start_local=0, candidate_end_local=10,
        stems={"full_mix": Audio(guitar + bass, sr, 10),
               "guitar": Audio(guitar, sr, 10), "bass": Audio(bass, sr, 10)},
    )
    intervals = [
        Interval(new_start=start, new_end=end, original_start=0, original_end=10, source="test")
        for start, end in [(0, 10), (20, 40), (50, 60)]
    ]
    if reverse:
        intervals = intervals[1:] + intervals[:1]
    probes = [bounded_stem_probe(interval) for interval in intervals]
    comparisons = [SimpleNamespace(
        probe=probe, partial=True, source_region=region, derivative_region=None, evidence=[],
    ) for probe in probes]
    expected = [describe_region(region, probe.original_start, probe.original_end) for probe in probes]
    result = Analysis(case_id="repeated", input=Intake(
        case_id="repeated", original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"), analysis_scope=["master"],
    ), durations={"new": 60, "original": 10})
    result.master.locate.sample_occurrences = intervals
    settings = Settings(stem_enabled=True, stem_max_candidates=3)
    record_initial_comparisons(result, intervals, intervals, comparisons, settings)
    assert [row.source_sounds for row in result.instrument_occurrences] == expected

    # Persist/resume runs stabilization again, even when no new checks are needed.
    saved = Analysis.model_validate_json(result.model_dump_json())
    resumed = run_occurrence_instruments(saved, None, None, settings, max_new_checks=0)
    assert [row.source_sounds for row in resumed.instrument_occurrences] == expected
    for row, interval, probe in zip(resumed.instrument_occurrences, intervals, probes, strict=True):
        narrow = interval.new_end - interval.new_start == 20
        bounds = (3, 7) if narrow else (1, 9)
        assert row.interval == interval and row.probe == probe
        assert (probe.original_start, probe.original_end) == bounds
        assert {sound.instrument for sound in row.source_sounds} == (
            {"Guitar"} if narrow else {"Bass", "Guitar"}
        )
        assert all((sound.start, sound.end) == bounds for sound in row.source_sounds)
        assert "not the full interval" in row.reason
    wide = [row for row in resumed.instrument_occurrences if row.probe.original_start == 1]
    assert wide[0].source_sounds == wide[1].source_sounds
    assert wide[0].source_sounds[0] is not wide[1].source_sounds[0]
