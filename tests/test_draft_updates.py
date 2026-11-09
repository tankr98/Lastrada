import pytest

from lastrada.reporting.document import document_text
from lastrada.reporting.placement import PLACEMENT_SECTIONS
from lastrada.schemas.models import Analysis, Placement
from lastrada.web.domain import apply_review
from test_sample_flow import analysis_with_match, sample_payload


@pytest.mark.parametrize("placement,sections", PLACEMENT_SECTIONS.items())
def test_current_placement_controls_regenerated_draft_after_reload(placement, sections):
    analysis = analysis_with_match()
    payload = sample_payload(analysis)
    payload.paths["master"].placement = Placement.THROUGHOUT
    payload.paths["master"].sections = ["whole track"]
    saved = Analysis.model_validate_json(apply_review(analysis, payload).model_dump_json())
    payload.narrative = saved.review.corrected["nature_of_use"]["text"]
    payload.paths["master"].placement = Placement(placement)
    updated = apply_review(saved, payload)
    assert updated.review.corrected["master"]["describe"]["sections"] == sections
    text = document_text(updated)
    if placement != "throughout":
        assert "throughout the track" not in text.lower()
    if placement == "intro_outro_without_chorus":
        assert "in the intro and outro, outside the chorus" in text


def test_manual_draft_survives_until_answers_change_and_is_kept_when_regenerated():
    analysis = analysis_with_match()
    payload = sample_payload(analysis)
    saved = apply_review(analysis, payload)
    payload.narrative = "My custom musical explanation."
    edited = apply_review(saved, payload)
    assert edited.review.corrected["nature_of_use"]["text"] == payload.narrative
    payload.paths["master"].element = "Guitar and bass"
    payload.paths["master"].lyrics = "A creator-provided lyric"
    changed = apply_review(edited, payload)
    assert changed.review.previous_narrative == payload.narrative
    draft = changed.review.corrected["nature_of_use"]["text"]
    assert "Guitar and bass" in draft and "A creator-provided lyric" in draft
    assert draft == changed.review.generated_narrative


def test_old_record_without_generated_metadata_also_refreshes_from_changed_answers():
    analysis = analysis_with_match()
    payload = sample_payload(analysis)
    saved = apply_review(analysis, payload)
    saved.review.generated_narrative = None
    payload.narrative = saved.review.corrected["nature_of_use"]["text"]
    payload.paths["master"].placement = Placement.INTRO_OUTRO
    saved = Analysis.model_validate_json(saved.model_dump_json())
    assert "in the intro and outro" in apply_review(saved, payload).review.generated_narrative
