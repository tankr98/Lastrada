from types import SimpleNamespace

from lastrada import pipeline
from lastrada.config import Settings, load_settings
from lastrada.schemas.models import Interval


def _comparison(*, accepted=True):
    evidence = SimpleNamespace(
        accepted=accepted,
        source_stem="guitar",
        derivative_stem="guitar",
        refined_new_start=12.25,
        refined_new_end=17.75,
    )
    return SimpleNamespace(evidence=[evidence])


def test_stem_assistance_refines_a_coarse_sony_candidate(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "compare_candidate_stems",
        lambda *_args, **_kwargs: _comparison(),
    )
    candidate = Interval(
        new_start=10.0,
        new_end=20.0,
        original_start=30.0,
        original_end=40.0,
        source="sampleid_rank_sequence",
        status="candidate",
        similarity=0.91,
    )

    updated, comparisons = pipeline.stem_assist_candidates(
        object(),
        object(),
        [candidate],
        object(),
        Settings(stem_enabled=True),
    )

    assert len(comparisons) == 1
    assert updated[0].new_start == 12.25
    assert updated[0].new_end == 17.75
    assert updated[0].original_start == 30.0
    assert updated[0].source == "stem-assisted DTW · guitar → guitar"


def test_stem_assistance_does_not_replace_existing_full_mix_dtw(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "compare_candidate_stems",
        lambda *_args, **_kwargs: _comparison(),
    )
    candidate = Interval(
        new_start=11.0,
        new_end=18.0,
        original_start=30.0,
        original_end=40.0,
        source="dtw_chroma_local_alignment",
        status="candidate",
        similarity=0.91,
    )

    updated, _ = pipeline.stem_assist_candidates(
        object(),
        object(),
        [candidate],
        object(),
        Settings(stem_enabled=True),
    )

    assert updated[0] == candidate


def test_stem_settings_can_be_enabled_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LASTRADA_STEM_ENABLED", "1")
    monkeypatch.setenv("LASTRADA_STEM_MODEL", "htdemucs")
    monkeypatch.setenv("LASTRADA_STEM_MAX_CANDIDATES", "2")
    monkeypatch.setenv("LASTRADA_STEM_PADDING_SECONDS", "6.5")
    monkeypatch.setenv("LASTRADA_STEM_CROSS_OTHER", "0")

    settings = load_settings(tmp_path / "missing.json")

    assert settings.stem_enabled is True
    assert settings.stem_model_name == "htdemucs"
    assert settings.stem_max_candidates == 2
    assert settings.stem_separation_padding_seconds == 6.5
    assert settings.stem_include_cross_other is False
