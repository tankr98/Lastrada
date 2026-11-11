from copy import deepcopy
import re

from lastrada.schemas.models import Analysis, Intake, Work, Interval, InstrumentPresence
from lastrada.web.domain import DraftPayload, draft_preview
from lastrada.reporting.table_draft import ROLE_UNKNOWN, METHOD_UNCONFIRMED
from lastrada.separation.occurrences import occurrence_rows
from lastrada.web.profile import PROFILE


def table_case(intervals=None):
    analysis = Analysis(case_id="table-draft", input=Intake(case_id="table-draft",
        original_work=Work(title="Original", artist="Source Artist"),
        new_work=Work(title="New", artist="New Artist"), analysis_scope=["master"]),
        durations={"original": 200, "new": 200})
    analysis.master.locate.sample_occurrences = intervals or [Interval(new_start=60, new_end=65,
        original_start=15, original_end=20, source="sampleid_rank_sequence")]
    analysis.instrument_occurrences = occurrence_rows(analysis, PROFILE["stem_model"])
    for row in analysis.instrument_occurrences:
        row.status = "checked"
        row.suggested_instruments = ["Guitar"]
    return analysis


def request(analysis):
    return DraftPayload(table_draft=True, prefill=True, paths={"master": {
        "status": "pending", "intervals": [i.model_dump() for i in analysis.master.locate.sample_occurrences],
    }})


def test_unconfirmed_table_generates_a_factual_draft_without_any_review_or_mutation():
    analysis = table_case()
    before = analysis.model_dump()
    result = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    assert analysis.model_dump() == before
    assert result["paths"]["master"]["times_confirmed"] is False
    assert "recording reuse remains unconfirmed" in result["narrative"]
    assert "0:15.00–0:20.00 in the original recording" in result["narrative"]
    assert "1:00.00–1:05.00 in the new track" in result["narrative"]
    assert "guitar" in result["narrative"]
    assert result["paths"]["master"]["role"] == ROLE_UNKNOWN
    assert "Draft — review required" in result["document"]
    assert analysis.review.corrected is None


def test_repetition_keeps_one_paired_example_in_story_and_every_row_in_appendix():
    from lastrada.reporting.loop_groups import group_loop_families
    intervals = [Interval(new_start=10*n, new_end=10*n+2, original_start=3, original_end=5,
                          source="sampleid_rank_sequence") for n in range(12)]
    analysis = table_case(intervals)
    original = deepcopy(analysis.model_dump())
    groups = group_loop_families(intervals, 200)
    result = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    assert f"{groups[0].occurrence_count} possible appearances" in result["document"]
    assert result["narrative"].count("in the original recording") == 1
    assert "recurring" in result["narrative"]
    from lastrada.reporting.document import timestamp
    appendix = result["document"].split("Exact timestamps and evidence\n")[1]
    for i in intervals:
        assert f"{timestamp(i.new_start)}–{timestamp(i.new_end)}" in appendix
    assert len(re.findall(r"^\d+\. In new track:", appendix, re.M)) == len(intervals)
    assert analysis.model_dump() == original


def test_presence_context_and_bounded_probe_are_not_attributed_to_whole_sample():
    analysis = table_case()
    row = analysis.instrument_occurrences[0]
    row.context_only = True
    row.source_sounds = [InstrumentPresence(instrument="Vocals", energy_share=.7, scope="context", start=14, end=21)]
    # Validate assignments as persisted records before exercising the real serializer.
    analysis = Analysis.model_validate(analysis.model_dump())
    result = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    text = result["document"]
    assert "surrounding audio in the original recording contains estimated vocals at 0:14.00–0:21.00" in text
    assert "check supports guitar" not in text
    assert "alone do not establish" in text
    assert "guitar" not in result["narrative"].lower()
    row = analysis.instrument_occurrences[0]
    row.context_only = False
    row.probe = row.interval.model_copy(update={"new_start": 61, "new_end": 64, "original_start": 16, "original_end": 19})
    result = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    text = result["document"]
    assert "check supports guitar" in text
    assert "0:16.00–0:19.00 in the original and 1:01.00–1:04.00 in the new track" in text
    assert "unchecked remainder" in text
    assert "only to the checked audio" in result["narrative"]


def test_missing_positions_and_instruments_stay_unknown_and_examples_cannot_supply_facts():
    analysis = table_case([Interval(new_start=7, new_end=9, source="pfnmf")])
    analysis.instrument_occurrences = []
    text = draft_preview(analysis, request(analysis), PROFILE["stem_model"])["narrative"]
    assert "position in the original recording is unknown" in text
    assert "0:07.00–0:09.00 in the new track" in text
    assert "unresolved instrumentation" in text
    for invented in ["synthesizer", "pitched", "sped up", "keep runnin", "beneath the new artist"]:
        assert invented not in text


def test_method_default_requires_both_recording_and_timing_confirmation():
    analysis = table_case()
    payload = request(analysis)
    payload.paths["master"].times_confirmed = True
    still_unconfirmed = draft_preview(analysis, payload, PROFILE["stem_model"])
    assert still_unconfirmed["paths"]["master"]["method"] == METHOD_UNCONFIRMED
    assert "recording reuse remains unconfirmed" in still_unconfirmed["narrative"]
    payload.paths["master"].status = "confirmed"
    reviewed = draft_preview(analysis, payload, PROFILE["stem_model"])
    assert reviewed["paths"]["master"]["method"] == "Sampled the original recording"
    assert "recording reuse remains unconfirmed" not in reviewed["narrative"]
    assert analysis.review.corrected is None


def assert_short_story(text):
    paragraphs = text.split("\n\n")
    assert 1 <= len(paragraphs) <= 2
    for paragraph in paragraphs:
        assert 1 <= len(re.findall(r"[.!?](?:\s|$)", paragraph)) <= 4


def test_many_groups_and_verbose_presets_do_not_expand_the_main_story():
    intervals = [Interval(new_start=n*12, new_end=n*12+3, original_start=n*10,
                          original_end=n*10+3, source="sampleid_rank_sequence") for n in range(14)]
    analysis = table_case(intervals)
    before = analysis.model_dump_json()
    payload = request(analysis)
    full = "An opening motif. " + "Another detailed explanation. " * 12
    for field in ("element", "method", "repetition", "role", "lyrics"):
        setattr(payload.paths["master"], field, full)
    result = draft_preview(analysis, payload, PROFILE["stem_model"])
    assert_short_story(result["narrative"])
    assert "Another detailed explanation" not in result["narrative"]
    assert full.strip() in result["document"].split("Exact timestamps and evidence")[1]
    assert len(re.findall(r"^\d+\. In new track:", result["document"], re.M)) == len(intervals)
    assert analysis.model_dump_json() == before


def test_role_interpretation_is_tentative_and_uses_checked_instruments_only():
    intervals = [Interval(new_start=n*10, new_end=n*10+3, original_start=15, original_end=18,
                          source="sampleid_rank_sequence") for n in range(3, 9)]
    analysis = table_case(intervals)
    for row in analysis.instrument_occurrences:
        row.suggested_instruments = ["Bass", "Drums"]
    result = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    assert_short_story(result["narrative"])
    assert "If the suggested match is correct" in result["narrative"]
    assert "could provide a rhythmic foundation" in result["narrative"]
    for row in analysis.instrument_occurrences:
        row.context_only = True
    context = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    assert "rhythmic foundation" not in context["narrative"]
    assert "instrument estimates apply only to the checked audio" in context["narrative"]


def test_two_rights_paths_still_fit_two_paragraphs_and_keep_all_evidence():
    from lastrada.reporting.table_draft import narrative
    from lastrada.schemas.models import PathResult
    analysis = table_case()
    path = PathResult(rights_type="master")
    path.locate.sample_occurrences = analysis.master.locate.sample_occurrences
    path.describe.role_in_new_song = "A possible repeated motif"
    composition = path.model_copy(update={"rights_type": "publishing"})
    text = narrative(analysis, {"master": path.model_dump(), "publishing": composition.model_dump()}, PROFILE["stem_model"])
    assert_short_story(text)
    assert len(text.split("\n\n")) == 2


def test_shortening_saved_wording_preserves_it_across_save_and_reload():
    from lastrada.web.domain import ReviewPayload, apply_review
    analysis = table_case()
    payload = request(analysis)
    payload.paths["master"].status = "confirmed"
    payload.paths["master"].times_confirmed = True
    initial = draft_preview(analysis, payload, PROFILE["stem_model"])
    old = "Earlier opening.\n\nEarlier middle.\n\nEarlier ending."
    review = ReviewPayload(table_draft=True, description_initialized=True, paths=initial["paths"],
                           reviewer="Creator", narrative=old, approve=True)
    review.paths["master"].details_confirmed = True
    saved = apply_review(analysis, review, PROFILE["stem_model"])
    before = saved.model_dump_json()
    refresh = DraftPayload(table_draft=True, paths=initial["paths"])
    preview = draft_preview(saved, refresh, PROFILE["stem_model"])
    assert_short_story(preview["narrative"])
    assert preview["previous_narrative"] == old
    assert saved.model_dump_json() == before
    review.narrative = ""
    shortened = Analysis.model_validate_json(apply_review(saved, review, PROFILE["stem_model"]).model_dump_json())
    assert shortened.review.previous_narrative == old
    assert shortened.review.corrected["nature_of_use"]["text"] == preview["narrative"]
