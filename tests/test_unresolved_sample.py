import pytest

from lastrada.reporting.sample_flow import sample_review
from test_sample_flow import analysis_with_match


@pytest.mark.parametrize(
    "matcher,stems,has_candidates,reason",
    [
        ("unavailable: load failed", "not_run: no matcher", False, "matching_unavailable"),
        ("not_run: no checkpoint", "not_run: no matcher", False, "matching_unavailable"),
        ("local_cpu_chunk_embeddings", "unavailable: timed out", True, "verification_incomplete"),
        ("local_cpu_chunk_embeddings", "not_run: disabled", True, "verification_incomplete"),
        ("local_cpu_chunk_embeddings", "demucs_htdemucs_6s_candidate_regions", True, "unconfirmed_candidates"),
        ("local_cpu_chunk_embeddings", "not_run: no paired Sony candidate available", False, "no_candidates"),
        ("", "", False, "insufficient_evidence"),
    ],
)
def test_unresolved_reason_distinguishes_missing_checks_from_completed_search(
    matcher, stems, has_candidates, reason
):
    analysis = analysis_with_match("sampleid_rank_sequence")
    if not has_candidates:
        analysis.master.locate.sample_occurrences = []
    analysis.methods.update(sampleid=matcher, stems=stems)
    before = analysis.model_dump()
    proposal = sample_review(analysis)
    assert proposal["status"] == "not_identified"
    assert proposal["reason"] == reason
    assert proposal["intervals"] == [] and proposal["description"] == {}
    assert proposal["checks"]["candidate_count"] == int(has_candidates)
    assert analysis.model_dump() == before


def test_unavailable_optional_check_does_not_hide_an_existing_supported_match():
    analysis = analysis_with_match()
    analysis.methods.update(stems="unavailable: model failed")
    assert sample_review(analysis)["status"] == "identified"
