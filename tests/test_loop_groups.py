from lastrada.reporting.loop_groups import group_loop_families, loop_family_rows
from lastrada.schemas.models import Interval


def interval(
    new_start,
    new_end,
    original_start=None,
    original_end=None,
    *,
    source="sampleid_rank_sequence",
    similarity=0.9,
):
    return Interval(
        new_start=new_start,
        new_end=new_end,
        original_start=original_start,
        original_end=original_end,
        source=source,
        status="candidate",
        similarity=similarity,
    )


def test_repeated_source_passage_becomes_one_loop_family():
    families = group_loop_families(
        [
            interval(10, 18, 42, 50),
            interval(30, 38, 42.2, 50.1),
            interval(50, 58, 41.9, 49.9),
            interval(70, 78, 42.1, 50.2),
        ],
        new_duration=90,
    )

    assert len(families) == 1
    family = families[0]
    assert family.occurrence_count == 4
    assert family.candidate_count == 4
    assert family.pattern == "Likely looped throughout"
    assert family.typical_spacing_seconds == 20
    assert family.regular_spacing is True


def test_overlapping_windows_collapse_but_raw_rows_are_retained():
    families = group_loop_families(
        [
            interval(10, 18, 42, 50, similarity=0.88),
            interval(10.4, 18.2, 42.1, 50.1, similarity=0.94),
            interval(10.7, 18.5, 41.8, 49.8, source="dtw_chroma_local_alignment"),
        ],
        new_duration=100,
    )

    family = families[0]
    assert family.candidate_count == 3
    assert family.occurrence_count == 1
    assert len(family.raw_candidates) == 3
    assert family.occurrences[0].source == "dtw_chroma_local_alignment"


def test_distinct_source_passages_stay_separate():
    families = group_loop_families(
        [
            interval(10, 18, 42, 50),
            interval(30, 38, 42.1, 50.1),
            interval(50, 58, 100, 108),
        ],
        new_duration=90,
    )

    assert len(families) == 2
    assert sorted(family.candidate_count for family in families) == [1, 2]


def test_unknown_source_rows_are_summarized_without_claiming_a_loop():
    families = group_loop_families(
        [
            interval(145.18, 145.79),
            interval(146.03, 148.49),
            interval(148.84, 149.85),
            interval(150.09, 151.34),
        ],
        new_duration=182,
    )

    assert len(families) == 1
    assert families[0].pattern == "Clustered unresolved candidates"
    row = loop_family_rows(families)[0]
    assert row["Source passage"] == "Source not identified"
    assert row["Candidate rows"] == 4


def test_two_repetitions_are_summarized_as_repeated_twice():
    families = group_loop_families(
        [interval(5, 10, 20, 25), interval(45, 50, 20.1, 25.1)],
        new_duration=60,
    )

    assert families[0].pattern == "Repeated twice"
    assert families[0].occurrence_count == 2
