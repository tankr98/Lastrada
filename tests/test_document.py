from lastrada.reporting.document import (
    document_text,
    document_html,
    missing_document_inputs,
    creator_narrative,
)
from lastrada.schemas.models import Analysis, Feature, Interval, Intake, Work, Placement


def example():
    intake = Intake(
        case_id="synthetic-document",
        original_work=Work(title="Source", artist="Generated"),
        new_work=Work(title="Mix", artist="Generated"),
        analysis_scope=["master"],
    )
    result = Analysis(
        case_id=intake.case_id, input=intake, durations={"original": 10.0, "new": 10.0}
    )
    result.master.locate.total_covered_seconds = 8
    result.master.locate.coverage_percentage = 80
    result.nature_of_use.text = creator_narrative(result)
    return result


def test_unconfirmed_overlap_never_becomes_documented_use():
    result = example()
    text = document_text(result)
    assert "80%" not in text and "8.00s" not in text
    assert "not been confirmed" in text
    assert any("sampled sound" in item for item in missing_document_inputs(result))
    assert "spectral" not in creator_narrative(result)


def test_complete_creator_details_generate_clear_document():
    result = example()
    path = result.master
    path.locate.detection_status = "verified"
    path.locate.sample_detected = True
    path.locate.sample_occurrences = [
        Interval(new_start=2, new_end=4, source="expert_review", status="expert_verified")
    ]
    path.locate.total_covered_seconds = 2.0
    path.locate.coverage_percentage = 20.0
    path.describe.elements = [
        Feature(
            feature="musical_element",
            value="a drum break",
            source="expert_review",
            status="expert_verified",
        )
    ]
    path.describe.sections = ["chorus"]
    path.describe.reuse_type = "chopped the recording"
    path.describe.repetition = "repeats twice"
    path.describe.role_in_new_song = "supports the hook"
    path.classification.placement = Placement.CHORUS
    result.nature_of_use.text = creator_narrative(result)
    assert missing_document_inputs(result) == []
    text = document_text(result)
    assert "a drum break" in text and "0:02.00–0:04.00" in text
    assert "20.0%" in text and "supports the hook" in text


def test_document_escapes_user_text():
    result = example()
    result.nature_of_use.text = "<script>bad()</script>"
    assert "<script>" not in document_html(result)
    assert "&lt;script&gt;" in document_html(result)


def test_throughout_summarizes_times_in_narrative_and_both_exports():
    result = example()
    path = result.master
    path.locate.detection_status = "verified"
    path.locate.sample_detected = True
    path.locate.sample_occurrences = [
        Interval(new_start=2, new_end=3, source="expert_review", status="expert_verified"),
        Interval(new_start=5, new_end=6, source="expert_review", status="expert_verified"),
    ]
    path.classification.placement = Placement.THROUGHOUT
    path.describe.repetition = "A short loop repeated in the track"
    result.nature_of_use.text = creator_narrative(result)
    for text in (result.nature_of_use.text, document_text(result), document_html(result)):
        assert "throughout the track" in text
        assert "A short loop repeated in the track" in text
        assert "0:02.00" not in text
        assert "0:05.00" not in text
    # Detailed evidence is preserved for analysis and JSON export.
    assert len(result.model_dump()["master"]["locate"]["sample_occurrences"]) == 2
    path.classification.placement = Placement.VERSES
    result.nature_of_use.text = creator_narrative(result)
    assert "0:02.00–0:03.00" in result.nature_of_use.text
    assert "0:05.00–0:06.00" in document_text(result)
