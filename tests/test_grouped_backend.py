from pathlib import Path
from threading import Barrier, get_ident
from types import SimpleNamespace

from lastrada.config import Settings
from lastrada.schemas.models import Analysis, Intake, Interval, Work
from lastrada.separation import grouped_occurrences
from lastrada.separation.demucs_process import DemucsProcessPool
from lastrada.web.profile import analysis_settings


ROOT = Path(__file__).resolve().parents[1]


def analysis(intervals):
    result = Analysis(
        case_id="grouped",
        input=Intake(
            case_id="grouped",
            original_work=Work(title="Original", artist="Test"),
            new_work=Work(title="Derivative", artist="Test"),
            analysis_scope=["master"],
        ),
        durations={"original": 180, "new": 180},
    )
    result.master.locate.sample_occurrences = intervals
    return result


def interval(new_start, original_start, similarity):
    return Interval(
        new_start=new_start,
        new_end=new_start + 8,
        original_start=original_start,
        original_end=original_start + 8,
        source="sampleid_rank_sequence",
        status="candidate",
        similarity=similarity,
    )


def evidence(stem="drums", accepted=True):
    return SimpleNamespace(
        source_stem=stem,
        derivative_stem=stem,
        accepted=accepted,
        mean_dtw_cost=0.1 if accepted else None,
        duration_ratio=1.0 if accepted else None,
        same_label=True,
        pitch_shift_semitones=0 if accepted else None,
        reason="generated comparison",
    )


def comparison(accepted=True):
    return SimpleNamespace(
        evidence=[evidence(accepted=accepted)],
        source_region=None,
        derivative_region=None,
    )


def grouped_settings(**updates):
    values = {
        "stem_group_enabled": True,
        "stem_group_workers": 2,
        "stem_group_max_representatives": 3,
        "stem_group_positive_confirmations": 2,
        "stem_group_negative_confirmations": 3,
        "stem_dtw_workers": 2,
    }
    values.update(updates)
    return Settings(**values)


def test_deployed_profile_keeps_frontend_but_enables_grouped_backend():
    settings = analysis_settings()
    source = (ROOT / "src/lastrada/web/execute.py").read_text()

    assert settings.stem_group_enabled
    assert settings.stem_group_workers == 3
    assert settings.stem_group_max_representatives == 3
    assert settings.stem_group_positive_confirmations == 2
    assert settings.stem_group_negative_confirmations == 3
    assert "main_settings = settings.model_copy" in source
    assert '"stem_enabled": False' in source
    assert "run_grouped_instruments" in source


def test_group_checks_three_representatives_not_every_timestamp(monkeypatch):
    intervals = [
        interval(0, 40, 0.99),
        interval(20, 40, 0.90),
        interval(40, 40, 0.80),
        interval(60, 40, 0.70),
        interval(80, 40, 0.60),
    ]
    calls = []

    def compare(*args, **kwargs):
        calls.append((args[2].new_start, kwargs))
        return comparison(accepted=len(calls) > 1)

    monkeypatch.setattr(grouped_occurrences, "compare_candidate_stems", compare)
    result = grouped_occurrences.run_grouped_instruments(
        analysis(intervals),
        None,
        None,
        grouped_settings(stem_group_workers=1),
        separator=SimpleNamespace(),
    )

    assert len(calls) == 3
    assert all(call[1]["include_cross_other"] is False for call in calls)
    assert all(call[1]["include_full_mix"] is False for call in calls)
    assert all(call[1]["parallel_dtw"] is True for call in calls)
    assert all(row.status == "checked" for row in result.instrument_occurrences)
    assert all(
        row.suggested_instruments == ["Drums"]
        for row in result.instrument_occurrences
    )
    assert "3 representative comparisons" in result.instrument_occurrences[0].reason


def test_distinct_groups_run_concurrently(monkeypatch):
    barrier = Barrier(2, timeout=3)
    threads = set()

    def compare(*args, **kwargs):
        threads.add(get_ident())
        barrier.wait()
        return comparison(accepted=True)

    monkeypatch.setattr(grouped_occurrences, "compare_candidate_stems", compare)
    result = grouped_occurrences.run_grouped_instruments(
        analysis(
            [
                interval(0, 10, 0.9),
                interval(30, 90, 0.8),
            ]
        ),
        None,
        None,
        grouped_settings(
            stem_group_workers=2,
            stem_group_max_representatives=1,
            stem_group_positive_confirmations=1,
        ),
        separator=SimpleNamespace(),
    )

    assert len(threads) == 2
    assert all(row.status == "checked" for row in result.instrument_occurrences)


def test_process_pool_accepts_more_than_two_bounded_workers():
    pool = DemucsProcessPool(4)
    try:
        assert len(pool.workers) == 4
    finally:
        pool.close()
