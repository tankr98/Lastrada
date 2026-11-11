"""Generated case for the browser contract test; no client recordings or models."""

import json
import os
from pathlib import Path
import sys
from lastrada.schemas.models import Analysis, Intake, Work, Interval
from lastrada.reporting.suggestions import suggested_intervals, placement_proposal
from lastrada.web.domain import ReviewPayload, DraftPayload, apply_review, draft_preview
from lastrada.reporting.document import document_html, document_text
from lastrada.separation.occurrences import occurrence_rows, instrument_prefill
from lastrada.reporting.loop_groups import group_loop_families, loop_family_rows
from lastrada.web.profile import PROFILE
from lastrada.reporting.sample_flow import sample_review


def initial():
    intake = Intake(
        case_id="00000000-0000-4000-8000-000000000001",
        original_work=Work(title="Source", artist="Artist"),
        new_work=Work(title="New", artist="Artist"),
        analysis_scope=["master", "publishing"],
    )
    analysis = Analysis(case_id=intake.case_id, input=intake, durations={"original": 20, "new": 20})
    analysis.master.locate.measurement_intervals = [
        Interval(new_start=1, new_end=4, source="pfnmf")
    ]
    sample_scenario = os.getenv("LASTRADA_BROWSER_SAMPLE_FLOW")
    if sample_scenario:
        analysis.input.analysis_scope = ["master"]
        analysis.master.locate.sample_occurrences = [Interval(
            new_start=8, new_end=12, original_start=2, original_end=6,
            source="sampleid_rank_sequence" if sample_scenario in {"no_match", "matcher_unavailable", "verification_incomplete", "candidate_table", "table_edits"} else "direct_waveform_local_alignment",
            status="candidate", end_review={"new_through": 12.5, "original_through": 6.5},
        )]
        if sample_scenario == "automatic_subset":
            analysis.master.locate.sample_occurrences.append(Interval(
                new_start=1, new_end=3, original_start=10, original_end=12,
                source="sampleid_rank_sequence", status="candidate",
            ))
        if sample_scenario == "candidate_table":
            analysis.durations = {"new": 180, "original": 180}
            analysis.master.locate.sample_occurrences = [Interval(
                new_start=1 + 4 * index, new_end=3 + 4 * index,
                original_start=2 + 3 * (index % 4), original_end=4 + 3 * (index % 4),
                source="sampleid_rank_sequence", status="candidate",
            ) for index in range(41)]
        analysis.instrument_occurrences = occurrence_rows(analysis, PROFILE["stem_model"])
        for row in analysis.instrument_occurrences:
            row.status = "pending" if sample_scenario.startswith(("automatic", "early_")) or sample_scenario == "candidate_table" else "checked"
            row.suggested_instruments = ["Guitar"] if sample_scenario == "prefilled" else []
        analysis.methods.update(sampleid="local_cpu_chunk_embeddings", stems="demucs_htdemucs_6s_candidate_regions")
        if sample_scenario == "matcher_unavailable":
            analysis.master.locate.sample_occurrences = []
            analysis.instrument_occurrences = []
            analysis.methods.update(sampleid="unavailable: matcher preparation failed (RuntimeError)",
                                    stems="not_run: no matcher")
        elif sample_scenario == "verification_incomplete":
            analysis.methods["stems"] = "unavailable: crop timeout"
        elif sample_scenario == "recovered":
            from types import SimpleNamespace
            from unittest.mock import patch
            from lastrada import pipeline
            from lastrada.web.profile import analysis_settings
            from lastrada.separation.occurrences import record_initial_comparisons

            coarse = Interval(new_start=0, new_end=20, original_start=0, original_end=20,
                              source="sampleid_rank_sequence", status="candidate")
            evidence = SimpleNamespace(accepted=True, source_stem="bass", derivative_stem="bass",
                refined_new_start=6, refined_new_end=14, mean_dtw_cost=.1,
                duration_ratio=1, pitch_shift_semitones=0, same_label=True, reason="test alignment")
            settings = analysis_settings()
            with patch.object(pipeline, "compare_candidate_stems", return_value=SimpleNamespace(evidence=[evidence])):
                updated, comparisons = pipeline.stem_assist_candidates(None, None, [coarse], None, settings)
            analysis.master.locate.sample_occurrences = updated
            record_initial_comparisons(analysis, [coarse], updated, comparisons, settings)
    if os.getenv("LASTRADA_BROWSER_ENDING"):
        analysis.master.locate.sample_occurrences = [
            Interval(
                new_start=1, new_end=2.5, original_start=2, original_end=3.5,
                source="direct_waveform_local_alignment", status="candidate",
                end_review={"new_through": 3, "original_through": 4},
            )
        ]
        if os.getenv("LASTRADA_BROWSER_ENDING") == "mixed":
            analysis.master.locate.sample_occurrences.extend([
                Interval(
                    new_start=1, new_end=2.75, original_start=2, original_end=3.5,
                    source="direct_waveform_local_alignment", status="candidate",
                ),
                Interval(
                    new_start=10, new_end=11.5, original_start=2, original_end=3.5,
                    source="direct_waveform_local_alignment", status="candidate",
                ),
            ])
    if os.getenv("LASTRADA_BROWSER_ANALYSIS"):
        analysis = Analysis.model_validate_json(
            Path(os.environ["LASTRADA_BROWSER_ANALYSIS"]).read_text()
        )
        intake = analysis.input
    result = {
        "analysis": analysis.model_dump(mode="json"),
        "instrument_rows": [
            r.model_dump(mode="json") for r in occurrence_rows(analysis, PROFILE["stem_model"])
        ],
        "loop_families": loop_family_rows(
            group_loop_families(suggested_intervals(analysis, "master"), analysis.durations["new"])
        ),
        "suggestions": {
            r: {
                "instruments": instrument_prefill(analysis, PROFILE["stem_model"])
                if r == "master"
                else {},
                "intervals": [i.model_dump(mode="json") for i in suggested_intervals(analysis, r)],
                "placement": placement_proposal(
                    suggested_intervals(analysis, r), analysis.durations["new"]
                ).__dict__,
            }
            for r in intake.analysis_scope
        },
    }
    if sample_scenario:
        result["sample_review"] = sample_review(analysis, PROFILE["stem_model"])
    return result


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "initial":
        print(json.dumps(initial()))
    else:
        body = json.load(sys.stdin)
        analysis = Analysis.model_validate(body["analysis"])
        if mode == "sample":
            print(json.dumps(sample_review(analysis, PROFILE["stem_model"])))
        elif mode == "draft":
            print(json.dumps(draft_preview(analysis, DraftPayload.model_validate(body["payload"]), PROFILE["stem_model"])))
        elif mode == "review":
            print(
                apply_review(
                    analysis, ReviewPayload.model_validate(body["payload"])
                ).model_dump_json()
            )
        elif mode == "html":
            print(document_html(analysis))
        elif mode == "json":
            print(analysis.model_dump_json(indent=2))
        else:
            print(document_text(analysis))
