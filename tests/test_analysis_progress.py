from lastrada.web.execute import _merge_progress, _resumable_stage


def progress(stage, percent, updated=100.0, started=50.0, restart_count=0):
    return {
        "stage": stage,
        "percent": percent,
        "updated": updated,
        "stage_started": started,
        "restart_count": restart_count,
    }


def test_backend_progress_never_moves_backwards():
    current = progress("stem_analysis", 78, updated=200.0, started=120.0)
    merged, accepted = _merge_progress(
        current,
        progress("preparing_matcher", 20, updated=210.0, started=210.0),
    )
    assert not accepted
    assert merged == current


def test_same_stage_keeps_highest_percent_and_original_start_time():
    current = progress("stem_analysis", 78, updated=200.0, started=120.0)
    merged, accepted = _merge_progress(
        current,
        progress("stem_analysis", 62, updated=210.0, started=210.0, restart_count=1),
    )
    assert accepted
    assert merged["percent"] == 78
    assert merged["stage_started"] == 120.0
    assert merged["restart_count"] == 1


def test_worker_retry_resumes_only_after_saved_stem_progress():
    state = {
        "status": "running",
        "instrument_progress": progress("stem_analysis", 70),
    }
    assert _resumable_stage(state) == "stem_analysis"
    state["instrument_progress"]["stage"] = "finalizing"
    assert _resumable_stage(state) == "finalizing"
    state["instrument_progress"]["stage"] = "matching"
    assert _resumable_stage(state) is None
