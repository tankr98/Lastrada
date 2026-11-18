"""Regression coverage for lost tonal/vocal parts and document-only prose."""

import pytest

from lastrada.reporting.document import document_html, document_text
from lastrada.schemas.models import Analysis, InstrumentPresence, Placement, StemEvidence
from lastrada.separation.occurrences import occurrence_rows
from lastrada.web.domain import DraftPayload, ReviewPayload, apply_review, draft_preview
from lastrada.web.profile import PROFILE
from test_table_draft import assert_short_story, request, table_case


def evidence(stem, verdict="accepted", scope="sample"):
    return StemEvidence(candidate_number=1, source_stem=stem, new_song_stem=stem,
                        dtw_result=verdict, scope=scope,
                        interpretation="Generated test comparison", reason="Generated test comparison")


def multi_part_case():
    analysis = table_case()
    row = analysis.instrument_occurrences[0]
    row.suggested_instruments = ["Drums"]
    row.evidence = [evidence(s) for s in ("drums", "bass", "guitar", "piano", "vocals")]
    row.evidence.append(evidence("other", "rejected"))
    row.interval.end_review = None
    return analysis


def test_old_drums_only_summary_recovers_all_accepted_parts_without_mutating_evidence():
    analysis = multi_part_case()
    before = analysis.model_dump_json()
    loaded = Analysis.model_validate_json(before)
    rows = occurrence_rows(loaded, PROFILE["stem_model"])
    labels = ["Drums", "Bass", "Guitar", "Piano", "Vocals"]
    assert rows[0].suggested_instruments == labels
    preview = draft_preview(loaded, request(loaded), PROFILE["stem_model"])
    assert preview["paths"]["master"]["element"] == ", ".join(labels)
    for word in ("drum", "bass", "guitar", "piano", "vocal"):
        assert word in preview["narrative"].lower()
    for fabricated in ("minor key", "major key", "chord progression", "syncopated", "sped up", "pitched up"):
        assert fabricated not in preview["narrative"].lower()
    assert_short_story(preview["narrative"])
    assert loaded.model_dump_json() == before


@pytest.mark.parametrize("scope,verdict,context", [
    ("sample", "rejected", False), ("sample", "weak", False),
    ("context", "accepted", False), ("sample", "accepted", True),
])
def test_unmatched_or_context_sounds_are_not_promoted_into_sampled_parts(scope, verdict, context):
    analysis = table_case()
    row = analysis.instrument_occurrences[0]
    row.context_only = context
    row.suggested_instruments = ["Guitar"]
    row.evidence = [evidence("guitar", verdict, scope)]
    row.new_sounds = [InstrumentPresence(instrument="Piano", energy_share=.8,
                                        start=60, end=65, scope="sample")]
    preview = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    assert "guitar" not in preview["narrative"].lower()
    assert "piano" not in preview["narrative"].lower()
    assert analysis.instrument_occurrences[0].evidence[0].dtw_result == verdict


def test_all_parts_survive_confirmation_reload_edit_and_both_document_exports():
    analysis = multi_part_case()
    before = analysis.model_dump_json()
    payload = request(analysis)
    payload.paths["master"].status = "confirmed"
    payload.paths["master"].times_confirmed = True
    preview = draft_preview(analysis, payload, PROFILE["stem_model"])
    review = ReviewPayload(table_draft=True, paths=preview["paths"], reviewer="Creator", approve=True)
    review.paths["master"].details_confirmed = True
    saved = Analysis.model_validate_json(apply_review(analysis, review, PROFILE["stem_model"]).model_dump_json())
    edit = DraftPayload(table_draft=True, paths=preview["paths"])
    edit.paths["master"].placement = Placement.INTRO_OUTRO
    edited = draft_preview(saved, edit, PROFILE["stem_model"])
    review.paths["master"].placement = edit.paths["master"].placement
    revised = apply_review(saved, review, PROFILE["stem_model"])
    assert revised.review.corrected["nature_of_use"]["text"] == edited["narrative"]
    for text in (edited["document"], document_text(revised), document_html(revised)):
        assert "in the intro and outro" in text and "throughout the track" not in text
        for word in ("drum", "bass", "guitar", "piano", "vocal"):
            assert word in text.lower()
        for diagnostic in ("unverified", "unconfirmed", "uncertain", "not been assessed", "remain estimates"):
            assert diagnostic not in text.lower()
        assert "0:15.00–0:20.00" in text and "1:00.00–1:05.00" in text
    assert analysis.model_dump_json() == before


def test_legacy_generated_wording_refreshes_but_custom_wording_survives():
    analysis = multi_part_case()
    preview = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    review = ReviewPayload(table_draft=True, paths=preview["paths"])
    saved = apply_review(analysis, review, PROFILE["stem_model"])
    old = "Old automatic wording: recording reuse remains unconfirmed."
    saved.review.generated_narrative = old
    saved.review.corrected["nature_of_use"]["text"] = old
    review.narrative = old
    updated = apply_review(saved, review, PROFILE["stem_model"])
    assert "unconfirmed" not in updated.review.corrected["nature_of_use"]["text"]
    assert updated.review.previous_narrative == old
    review.narrative = "My own musical description."
    custom = apply_review(saved, review, PROFILE["stem_model"])
    assert custom.review.corrected["nature_of_use"]["text"] == review.narrative
