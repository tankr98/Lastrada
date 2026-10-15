from lastrada.reporting.suggestions import timing_questions, suggested_intervals, confirmed_prefills
from lastrada.schemas.models import Analysis, Intake, Work, Interval


def intervals(ranges):
    return [Interval(new_start=s, new_end=e, source="pfnmf_activation") for s, e in ranges]


def test_distributed_timing_asks_questions_not_assertions():
    questions = timing_questions(intervals([(0, 30), (40, 70), (80, 100)]), 100)
    assert {q.kind for q in questions} == {"throughout", "melody"}
    assert all(q.question.endswith("?") for q in questions)


def test_short_regular_regions_only_suggest_a_loop():
    questions = timing_questions(intervals([(1, 5), (21, 25), (41, 45)]), 100)
    assert [q.kind for q in questions] == ["loop"]
    assert "times" not in confirmed_prefills("loop", "master")["repetition"]


def test_single_short_region_asks_about_one_time_use():
    assert timing_questions(intervals([(12, 16)]), 100)[0].kind == "one_time"


def test_measurements_are_not_copied_into_publishing():
    intake = Intake(
        case_id="synthetic",
        original_work=Work(title="Source", artist="Generated"),
        new_work=Work(title="Mix", artist="Generated"),
        analysis_scope=["master", "publishing"],
    )
    result = Analysis(case_id="synthetic", input=intake)
    result.master.locate.measurement_intervals = intervals([(2, 4)])
    assert suggested_intervals(result, "master")[0].source == "pfnmf_activation"
    assert suggested_intervals(result, "publishing") == []
    assert result.master.locate.sample_detected is None
