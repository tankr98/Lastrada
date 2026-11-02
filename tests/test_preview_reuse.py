from lastrada.audio.synthetic import demo_pair
from lastrada.pipeline import analyze_pair, reuse_preview
from lastrada.schemas.models import Intake, Work


def test_reusing_preview_changes_credits_and_scope_without_mutating_measurements():
    original, new, _ = demo_pair()
    intake = Intake(
        case_id="preview",
        original_work=Work(title="Source", artist="Generated"),
        new_work=Work(title="Mix", artist="Generated"),
        analysis_scope=["master"],
    )
    preview = analyze_pair(intake, original, new, synthetic=True)
    before = preview.model_dump()
    confirmed = intake.model_copy(deep=True)
    confirmed.case_id = "confirmed-case"
    confirmed.new_work.title = "Confirmed mix"
    confirmed.original_work.audio_version_warning = "Extended edit"
    confirmed.analysis_scope = ["publishing", "master"]
    reused = reuse_preview(preview, confirmed)
    assert reused.case_id == reused.input.case_id == "confirmed-case"
    assert reused.master.model_dump() == preview.master.model_dump()
    assert reused.publishing.locate.detection_status == "not_verified"
    assert "Extended edit" in reused.warnings
    assert reused.input.new_work.title == "Confirmed mix"
    assert preview.model_dump() == before
    confirmed.analysis_scope = ["publishing"]
    publishing_only = reuse_preview(preview, confirmed)
    assert publishing_only.master.locate.detection_status == "not_requested"
    assert not publishing_only.master.locate.measurement_intervals
    assert "measurement" not in publishing_only.methods
