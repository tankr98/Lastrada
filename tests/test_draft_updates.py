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


def test_table_draft_prefills_selected_times_without_saving_or_approving():
    from lastrada.web.domain import DraftPayload, draft_preview
    from lastrada.reporting.sample_flow import LYRICS_UNASSESSED

    analysis = analysis_with_match()
    analysis.input.analysis_scope = ["master"]
    before = analysis.model_dump_json()
    payload = DraftPayload(prefill=True, paths={"master": {
        "status": "confirmed", "times_confirmed": True,
        "intervals": [{"new_start": 0, "new_end": 5, "original_start": 2, "original_end": 7, "source": "creator_review"}],
    }})
    result = draft_preview(analysis, payload)
    assert analysis.model_dump_json() == before
    assert result["paths"]["master"]["placement"] == "intro_only"
    assert result["paths"]["master"]["lyrics"] == LYRICS_UNASSESSED
    assert all(result["paths"]["master"][key] for key in ("element", "method", "repetition", "role", "sections"))
    assert "Draft — review required" in result["document"]
    assert "Lyrics: Not assessed" not in result["document"]
    assert "Reused lyrics have not been assessed." in result["document"]
    assert not result["paths"]["master"]["details_confirmed"]


def test_draft_levers_export_and_saved_classic_answers_agree():
    from lastrada.web.domain import DraftPayload, ReviewPayload, draft_preview

    analysis = analysis_with_match()
    analysis.input.analysis_scope = ["master"]
    preview = draft_preview(analysis, DraftPayload(prefill=True, paths={"master": {
        "status": "confirmed", "times_confirmed": True,
        "intervals": [i.model_dump() for i in analysis.master.locate.sample_occurrences],
    }}))
    payload = DraftPayload(paths=preview["paths"])
    payload.paths["master"].placement = Placement.INTRO_OUTRO
    payload.paths["master"].lyrics = ""
    payload.paths["master"].element = "Bass and guitar"
    changed = draft_preview(analysis, payload)
    assert "in the intro and outro" in changed["document"]
    assert "throughout the track" not in changed["document"]
    saved = apply_review(analysis, ReviewPayload(paths=changed["paths"], description_initialized=True))
    assert saved.review.description_answers["lyrics"] == ""
    assert document_text(saved) == changed["document"]
    approved = ReviewPayload(paths=changed["paths"], reviewer="Creator", approve=True)
    approved.paths["master"].details_confirmed = True
    reviewed = apply_review(saved, approved)
    assert "Bass and guitar" in document_text(reviewed)
    assert reviewed.review.status == "approved"


def test_timestamp_only_save_does_not_turn_missing_defaults_into_deliberate_blanks():
    from lastrada.web.domain import DraftPayload, ReviewPayload, draft_preview

    analysis = analysis_with_match()
    analysis.input.analysis_scope = ["master"]
    answers = {"master": {"status": "confirmed", "times_confirmed": True,
        "intervals": [i.model_dump() for i in analysis.master.locate.sample_occurrences]}}
    saved = apply_review(analysis, ReviewPayload(paths=answers))
    assert saved.review.description_answers == {}
    preview = draft_preview(saved, DraftPayload(prefill=True, paths=answers))
    assert all(preview["paths"]["master"][key] for key in ("element", "method", "repetition", "role", "lyrics"))
    # A later timestamp edit can refresh defaults without refilling a cleared lyric.
    preview["paths"]["master"]["lyrics"] = ""
    changed = draft_preview(saved, DraftPayload(prefill=True, paths=preview["paths"], preserve_fields={"master": ["lyrics"]}))
    assert changed["paths"]["master"]["lyrics"] == ""
