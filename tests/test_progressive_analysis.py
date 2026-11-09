from types import SimpleNamespace

import pytest

from lastrada.audio.synthetic import demo_pair
from lastrada.config import Settings
from lastrada.pipeline import analyze_pair
from lastrada.schemas.models import Interval


@pytest.mark.parametrize(
    "initial,refine,expected",
    [
        ("direct_waveform_local_alignment", False, ["ready", "stems", "ready"]),
        ("sampleid_rank_sequence", True, ["stems", "ready"]),
        ("sampleid_rank_sequence", False, ["stems"]),
    ],
)
def test_preview_waits_for_supported_evidence_and_does_not_change_predictions(
    monkeypatch,
    intake,
    initial,
    refine,
    expected,
):
    from lastrada import pipeline

    candidate = Interval(
        new_start=2, new_end=4, original_start=0, original_end=2, source=initial, status="candidate"
    )
    adapter = SimpleNamespace(match=lambda *a, **kw: [candidate.model_copy(deep=True)])
    monkeypatch.setattr(pipeline, "refine_candidate", lambda a, b, c, **kw: c)
    events, previews = [], []

    def stems(result, original, new, candidates, settings, on_progress=None):
        events.append("stems")
        if refine:
            candidates[0] = candidates[0].model_copy(
                update={"source": "stem-assisted DTW · bass → bass"}
            )
        if on_progress:
            on_progress(candidates)
        return candidates

    monkeypatch.setattr(pipeline, "_run_optional_stem_assistance", stems)

    def preview(partial):
        events.append("ready")
        previews.append(partial.model_copy(deep=True))

    settings = Settings(dtw_enabled=False, iterations=10)
    original, new = demo_pair()[:2]
    result = analyze_pair(
        intake, original, new, adapter=adapter, settings=settings, on_result=preview
    )
    assert events == expected
    baseline = analyze_pair(intake, original, new, adapter=adapter, settings=settings)
    assert result.master == baseline.master
    if previews:
        assert result.timings_seconds["first_supported_result"] <= result.timings_seconds["total"]
        assert previews[0].master.locate.sample_occurrences[0].source != "sampleid_rank_sequence"


def test_completed_refinement_survives_a_later_instrument_failure(monkeypatch, intake):
    from lastrada import pipeline
    from lastrada.schemas.models import Analysis
    from lastrada.separation import demucs

    candidate = Interval(
        new_start=2,
        new_end=4,
        original_start=0,
        original_end=2,
        source="sampleid_rank_sequence",
        status="candidate",
    )
    refined = candidate.model_copy(update={"source": "stem-assisted DTW · bass → bass"})
    closed = []
    monkeypatch.setattr(demucs, "demucs_available", lambda: True)
    monkeypatch.setattr(
        demucs, "DemucsSeparator", lambda **kw: SimpleNamespace(close=lambda: closed.append(True))
    )

    def fail_later(*args, on_progress=None, **kwargs):
        on_progress([refined], [])
        raise demucs.StemSeparationUnavailable("Later crop timed out")

    monkeypatch.setattr(pipeline, "stem_assist_candidates", fail_later)
    result = Analysis(case_id=intake.case_id, input=intake)
    updates = []
    intervals = pipeline._run_optional_stem_assistance(
        result,
        None,
        None,
        [candidate],
        Settings(stem_enabled=True),
        on_progress=lambda rows, comp: updates.append(list(rows)),
    )
    assert intervals == [refined] == updates[0]
    assert closed == [True] and "Later crop timed out" in result.methods["stems"]
