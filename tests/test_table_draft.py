from copy import deepcopy

from lastrada.schemas.models import Analysis, Intake, Work, Interval, InstrumentPresence
from lastrada.web.domain import DraftPayload, draft_preview
from lastrada.reporting.table_draft import ROLE_UNKNOWN
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
    assert "Recording reuse remains unconfirmed" in result["narrative"]
    assert "0:15.00–0:20.00 in the original recording" in result["narrative"]
    assert "1:00.00–1:05.00 in the new track" in result["narrative"]
    assert "guitar" in result["narrative"]
    assert result["paths"]["master"]["role"] == ROLE_UNKNOWN
    assert "Draft — review required" in result["document"]
    assert analysis.review.corrected is None


def test_repetition_uses_existing_groups_and_representative_paired_rows():
    from lastrada.reporting.loop_groups import group_loop_families
    intervals = [Interval(new_start=10*n, new_end=10*n+2, original_start=3, original_end=5,
                          source="sampleid_rank_sequence") for n in range(12)]
    analysis = table_case(intervals)
    original = deepcopy(analysis.model_dump())
    groups = group_loop_families(intervals, 200)
    result = draft_preview(analysis, request(analysis), PROFILE["stem_model"])
    assert f"{groups[0].occurrence_count} possible appearances" in result["narrative"]
    assert "Representative timestamps" in result["narrative"]
    assert result["narrative"].count("is a possible match at") == 3
    for time in ["0:00.00–0:02.00", "1:00.00–1:02.00", "1:50.00–1:52.00"]:
        assert time in result["narrative"]
    assert analysis.model_dump() == original


def test_presence_context_and_bounded_probe_are_not_attributed_to_whole_sample():
    analysis = table_case()
    row = analysis.instrument_occurrences[0]
    row.context_only = True
    row.source_sounds = [InstrumentPresence(instrument="Vocals", energy_share=.7, scope="context", start=14, end=21)]
    # Validate assignments as persisted records before exercising the real serializer.
    analysis = Analysis.model_validate(analysis.model_dump())
    text = draft_preview(analysis, request(analysis), PROFILE["stem_model"])["narrative"]
    assert "surrounding audio in the original recording contains estimated vocals at 0:14.00–0:21.00" in text
    assert "check supports guitar" not in text
    assert "alone do not establish" in text
    row = analysis.instrument_occurrences[0]
    row.context_only = False
    row.probe = row.interval.model_copy(update={"new_start": 61, "new_end": 64, "original_start": 16, "original_end": 19})
    text = draft_preview(analysis, request(analysis), PROFILE["stem_model"])["narrative"]
    assert "check supports guitar" in text
    assert "0:16.00–0:19.00 in the original and 1:01.00–1:04.00 in the new track" in text
    assert "unchecked remainder" in text


def test_missing_positions_and_instruments_stay_unknown_and_examples_cannot_supply_facts():
    analysis = table_case([Interval(new_start=7, new_end=9, source="pfnmf")])
    analysis.instrument_occurrences = []
    text = draft_preview(analysis, request(analysis), PROFILE["stem_model"])["narrative"]
    assert "position in the original recording is unknown" in text
    assert "0:07.00–0:09.00 in the new track" in text
    assert "has not been established" in text
    for invented in ["synthesizer", "pitched", "sped up", "keep runnin", "beneath the new artist"]:
        assert invented not in text
