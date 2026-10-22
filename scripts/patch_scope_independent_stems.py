from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    path = Path("app.py")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        """        detected_checkpoint, checkpoint_note = resolve_sampleid_checkpoint(
            allow_download=False
        )
""",
        """        use_stems = st.checkbox(
            "Run Demucs stem-assisted comparison",
            value=True,
            disabled=not use_sampleid,
            help=(
                "Separates the strongest Sony candidate into estimated stems and "
                "runs guarded DTW on selected stem pairs. Stem evidence is generated "
                "for any selected rights scope."
            ),
        )
        detected_checkpoint, checkpoint_note = resolve_sampleid_checkpoint(
            allow_download=False
        )
""",
        "insert Demucs main-flow control",
    )

    text = replace_once(
        text,
        """                analysis_start = perf_counter()
""",
        """                run_stem_assistance = bool(use_sampleid and use_stems)
                analysis_settings = settings.model_copy(
                    update={"stem_enabled": run_stem_assistance}
                )
                analysis_start = perf_counter()
""",
        "create per-run stem settings",
    )

    text = replace_once(
        text,
        """                if use_sampleid and "master" in intake.analysis_scope:
""",
        """                if use_sampleid:
""",
        "remove master gate from Sony adapter setup",
    )

    text = replace_once(
        text,
        """                reused_preview = reusable and (not use_sampleid or adapter is None)
""",
        """                reused_preview = (
                    reusable
                    and (not use_sampleid or adapter is None)
                    and not run_stem_assistance
                )
""",
        "avoid reusing a preview when stems were requested",
    )

    text = replace_once(
        text,
        """                            adapter=adapter,
                            synthetic=synthetic,
                            settings=settings,
""",
        """                            adapter=adapter,
                            synthetic=synthetic,
                            settings=analysis_settings,
""",
        "pass per-run stem settings",
    )

    text = replace_once(
        text,
        """    if result is not None:
        reviewed_paths = {}
        for rights in result.input.analysis_scope:
""",
        """    if result is not None:
        stem_frame = _stem_evidence_frame(result)
        st.markdown("### Stem evidence")
        st.caption(
            "Demucs estimates instrument stems for the strongest Sony candidate region, "
            "then guarded DTW compares the source and new-song stem pairs. This evidence "
            "is shown regardless of the selected rights scope."
        )
        if stem_frame.empty:
            stem_status = result.methods.get(
                "stems", "not_run: no stem evidence status was recorded"
            )
            st.info(
                "No stem comparison rows were generated for this run. "
                f"Status: {stem_status}"
            )
        else:
            st.dataframe(
                stem_frame,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Accepted means the pair passed engineering guardrails. It is supporting "
                "evidence, not a verified instrument identification or legal conclusion."
            )

        reviewed_paths = {}
        for rights in result.input.analysis_scope:
""",
        "render one global stem table",
    )

    text = replace_once(
        text,
        """                    if rights == "master" and getattr(result, "stem_evidence", None):
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
""",
        "",
        "remove master-only duplicate stem table",
    )

    path.write_text(text, encoding="utf-8")


def patch_pipeline() -> None:
    path = Path("src/lastrada/pipeline.py")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        """    return records


def stem_assist_candidates(original, new, candidates, separator, settings):
""",
        """    return records


def _should_run_recording_evidence(intake, adapter, settings):
    \"\"\"Run Sony/DTW/stem evidence even when master rights are not requested.

    The legal master path remains not_requested unless master is in the intake scope;
    this helper only controls whether recording evidence is computed for reviewer use.
    \"\"\"
    return (
        "master" in intake.analysis_scope
        or adapter is not None
        or settings.stem_enabled
    )


def stem_assist_candidates(original, new, candidates, separator, settings):
""",
        "add recording-evidence scope helper",
    )

    text = replace_once(
        text,
        """    if "master" in intake.analysis_scope:
        t = perf_counter()
""",
        """    if _should_run_recording_evidence(intake, adapter, settings):
        t = perf_counter()
""",
        "remove master gate from recording evidence pipeline",
    )

    text = replace_once(
        text,
        """        t = perf_counter()
        result.master = analyze_master(measurement, candidates, ran)
        result.timings_seconds["classification"] = perf_counter() - t
    else:
        result.master = PathResult(
            rights_type="master", locate=Locate(detection_status="not_requested")
        )
""",
        """        if "master" in intake.analysis_scope:
            t = perf_counter()
            result.master = analyze_master(measurement, candidates, ran)
            result.timings_seconds["classification"] = perf_counter() - t
        else:
            result.master = PathResult(
                rights_type="master", locate=Locate(detection_status="not_requested")
            )
    else:
        result.master = PathResult(
            rights_type="master", locate=Locate(detection_status="not_requested")
        )
""",
        "keep legal master output unrequested outside master scope",
    )

    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    path = Path("tests/test_stem_main_flow.py")
    text = path.read_text(encoding="utf-8")
    marker = "test_recording_evidence_is_not_gated_by_master_scope"
    if marker in text:
        return
    text = text.rstrip() + """


def test_recording_evidence_is_not_gated_by_master_scope():
    publishing_only = SimpleNamespace(analysis_scope=["publishing"])

    assert pipeline._should_run_recording_evidence(
        publishing_only, object(), Settings(stem_enabled=False)
    )
    assert pipeline._should_run_recording_evidence(
        publishing_only, None, Settings(stem_enabled=True)
    )
    assert not pipeline._should_run_recording_evidence(
        publishing_only, None, Settings(stem_enabled=False)
    )
""" + "\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_app()
    patch_pipeline()
    patch_tests()
