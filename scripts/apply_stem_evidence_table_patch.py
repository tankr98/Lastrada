"""One-time deterministic patch for PR #6 stem-evidence presentation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected one match in {relative_path}, found {count}: {old[:80]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/lastrada/schemas/models.py",
    '''class Locate(StrictModel):
''',
    '''class StemEvidence(StrictModel):
    candidate_number: int = Field(ge=1)
    source_stem: str = Field(min_length=1)
    new_song_stem: str = Field(min_length=1)
    dtw_result: Literal["accepted", "weak", "rejected"]
    duration_ratio: float | None = Field(default=None, gt=0)
    interpretation: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    mean_dtw_cost: float | None = Field(default=None, ge=0)
    pitch_shift_semitones: int | None = None


class Locate(StrictModel):
''',
)

replace_once(
    "src/lastrada/schemas/models.py",
    '''    methods: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
''',
    '''    methods: dict[str, str] = Field(default_factory=dict)
    stem_evidence: list[StemEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
''',
)

replace_once(
    "src/lastrada/pipeline.py",
    '''from lastrada.schemas.models import Analysis, Interval, Locate, PathResult
''',
    '''from lastrada.schemas.models import Analysis, Interval, Locate, PathResult, StemEvidence
''',
)

replace_once(
    "src/lastrada/pipeline.py",
    '''def stem_assist_candidates(original, new, candidates, separator, settings):
''',
    '''def _stem_verdict(item):
    if item.accepted:
        return "accepted"
    if item.mean_dtw_cost is not None or item.duration_ratio is not None:
        return "weak"
    return "rejected"


def _stem_interpretation(item, verdict):
    if verdict == "accepted" and item.same_label:
        return "strong supporting evidence"
    if verdict == "accepted":
        return "possible separator spillover"
    if verdict == "weak":
        return "no useful alignment"
    if item.source_stem == "vocals" and item.derivative_stem == "vocals":
        return "no supporting vocal alignment"
    if item.same_label:
        return "no useful alignment"
    return "no useful cross-stem alignment"


def _stem_evidence_records(comparisons):
    records = []
    for candidate_number, comparison in enumerate(comparisons, start=1):
        for item in comparison.evidence:
            verdict = _stem_verdict(item)
            records.append(
                StemEvidence(
                    candidate_number=candidate_number,
                    source_stem=item.source_stem,
                    new_song_stem=item.derivative_stem,
                    dtw_result=verdict,
                    duration_ratio=item.duration_ratio,
                    interpretation=_stem_interpretation(item, verdict),
                    reason=item.reason or "No additional DTW detail",
                    mean_dtw_cost=item.mean_dtw_cost,
                    pitch_shift_semitones=item.pitch_shift_semitones,
                )
            )
    return records


def stem_assist_candidates(original, new, candidates, separator, settings):
''',
)

replace_once(
    "src/lastrada/pipeline.py",
    '''        result.timings_seconds["stem_separation"] = perf_counter() - started
''',
    '''        result.stem_evidence = _stem_evidence_records(comparisons)
        result.timings_seconds["stem_separation"] = perf_counter() - started
''',
)

replace_once(
    "app.py",
    '''st.set_page_config(
''',
    '''def _stem_evidence_frame(result):
    columns = [
        "Candidate",
        "Source stem",
        "New-song stem",
        "DTW result",
        "Duration ratio",
        "Interpretation",
    ]
    rows = [
        {
            "Candidate": item.candidate_number,
            "Source stem": item.source_stem,
            "New-song stem": item.new_song_stem,
            "DTW result": item.dtw_result,
            "Duration ratio": (
                f"{item.duration_ratio:.2f}×"
                if item.duration_ratio is not None
                else "—"
            ),
            "Interpretation": item.interpretation,
        }
        for item in getattr(result, "stem_evidence", [])
    ]
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty and frame["Candidate"].nunique() == 1:
        frame = frame.drop(columns=["Candidate"])
    return frame


st.set_page_config(
''',
)

replace_once(
    "app.py",
    '''                with st.container(key=f"stage_2_{rights}_times"):
                    st.markdown("### Check the moments")
                    st.caption(
                        "Suggested moments carry straight into your document when you accept them. Listen first; you only need to edit if they are wrong."
                    )
''',
    '''                with st.container(key=f"stage_2_{rights}_times"):
                    st.markdown("### Review the evidence")
                    st.caption(
                        "Use the stem verdicts as supporting evidence, then listen and confirm or edit the paired timestamps."
                    )
''',
)

replace_once(
    "app.py",
    '''                    seeds = st.session_state[key + "seed_intervals"]
                    if rights == "master" and seeds:
''',
    '''                    seeds = st.session_state[key + "seed_intervals"]
                    if rights == "master" and getattr(result, "stem_evidence", None):
                        st.markdown("#### Stem evidence")
                        st.caption(
                            "Demucs estimated the stems for the strongest Sony candidate region, and guarded DTW compared the selected source ↔ new-song stem pairs."
                        )
                        st.dataframe(
                            _stem_evidence_frame(result),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.caption(
                            "Accepted means the pair passed engineering guardrails. It is supporting evidence, not a verified instrument or legal conclusion."
                        )
                    st.markdown("#### Check the moments")
                    st.caption(
                        "Suggested moments carry straight into your document when you accept them. Listen first; edit them if they are wrong."
                    )
                    if rights == "master" and seeds:
''',
)

replace_once(
    "tests/test_stem_main_flow.py",
    '''def _comparison(*, accepted=True):
    evidence = SimpleNamespace(
        accepted=accepted,
        source_stem="guitar",
        derivative_stem="guitar",
        refined_new_start=12.25,
        refined_new_end=17.75,
    )
    return SimpleNamespace(evidence=[evidence])
''',
    '''def _comparison(
    *,
    accepted=True,
    source_stem="guitar",
    derivative_stem="guitar",
    mean_dtw_cost=None,
    duration_ratio=None,
):
    evidence = SimpleNamespace(
        accepted=accepted,
        source_stem=source_stem,
        derivative_stem=derivative_stem,
        refined_new_start=12.25,
        refined_new_end=17.75,
        same_label=source_stem == derivative_stem,
        reason=(
            "alignment passed guardrails"
            if accepted
            else "no alignment passed overlap and duration guardrails"
        ),
        mean_dtw_cost=(0.22 if accepted else mean_dtw_cost),
        pitch_shift_semitones=0 if accepted else None,
        duration_ratio=(1.04 if accepted else duration_ratio),
    )
    return SimpleNamespace(evidence=[evidence])
''',
)

path = ROOT / "tests/test_stem_main_flow.py"
text = path.read_text(encoding="utf-8")
addition = '''\n\ndef test_stem_evidence_records_match_reviewer_table_verdicts():
    comparisons = [
        _comparison(),
        _comparison(source_stem="guitar", derivative_stem="other"),
        _comparison(accepted=False, source_stem="vocals", derivative_stem="vocals"),
        _comparison(
            accepted=False,
            source_stem="drums",
            derivative_stem="drums",
            mean_dtw_cost=0.72,
            duration_ratio=1.18,
        ),
    ]

    records = pipeline._stem_evidence_records(comparisons)

    assert [record.dtw_result for record in records] == [
        "accepted",
        "accepted",
        "rejected",
        "weak",
    ]
    assert records[0].interpretation == "strong supporting evidence"
    assert records[1].interpretation == "possible separator spillover"
    assert records[2].interpretation == "no supporting vocal alignment"
    assert records[3].interpretation == "no useful alignment"
    assert records[0].duration_ratio == 1.04
'''
if "test_stem_evidence_records_match_reviewer_table_verdicts" in text:
    raise RuntimeError("Stem evidence verdict test already exists")
path.write_text(text.rstrip() + addition + "\n", encoding="utf-8")

print("Applied structured stem-evidence model and Step 3 table patch.")
