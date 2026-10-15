"""Focused Streamlit tester for SampleID -> direct alignment -> guarded DTW.

Run from the repository root:
    streamlit run dtw_test_app.py

This is intentionally separate from the main Nature-of-Use UI so the alignment
experiment can be inspected without changing the client-facing workflow.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from lastrada.audio.io import decode
from lastrada.alignment.intervals import coverage
from lastrada.alignment.local import refine_candidate
from lastrada.alignment.dtw import refine_candidate_dtw, duration_ratio_is_plausible
from lastrada.config import load_settings
from lastrada.recognition.sampleid_adapter import SampleIDAdapter, SampleIDUnavailable
from lastrada.schemas.models import Interval


settings = load_settings()

st.set_page_config(
    page_title="Lastrada · DTW Test Bench",
    page_icon="🎯",
    layout="wide",
)

st.title("DTW / SampleID Test Bench")
st.caption(
    "Experimental alignment sandbox. Nothing shown here is a verified Nature-of-Use conclusion."
)

with st.expander("What this test bench does", expanded=True):
    st.markdown(
        """
**Full-pipeline mode**
1. Sony SampleID proposes coarse source ↔ derivative candidate intervals.
2. Direct waveform correlation gets first chance to refine near-identical audio.
3. Guarded chroma + DTW runs only when direct correlation does not refine the candidate.
4. DTW results that require implausible time compression/expansion are rejected and the coarse Sony interval is preserved.

**Manual-candidate mode**
- Skip Sony entirely and paste one known/assumed source + derivative interval to inspect how the DTW layer behaves.
        """
    )

left, right = st.columns(2)
with left:
    original_file = st.file_uploader(
        "Original / source track",
        type=["wav", "flac", "mp3", "m4a", "ogg"],
        key="dtw_test_original",
    )
with right:
    new_file = st.file_uploader(
        "New / derivative track",
        type=["wav", "flac", "mp3", "m4a", "ogg"],
        key="dtw_test_new",
    )

if original_file:
    st.audio(original_file.getvalue())
if new_file:
    st.audio(new_file.getvalue())

with st.sidebar:
    st.header("DTW guardrails")
    min_ratio = st.slider(
        "Minimum duration ratio",
        0.20,
        1.00,
        float(settings.dtw_min_duration_ratio),
        0.05,
        help="Derivative matched duration / source duration.",
    )
    max_ratio = st.slider(
        "Maximum duration ratio",
        1.00,
        3.00,
        float(settings.dtw_max_duration_ratio),
        0.05,
    )
    padding = st.slider(
        "Search padding (seconds)",
        0.0,
        20.0,
        float(settings.dtw_search_padding_seconds),
        0.5,
    )
    max_pitch = st.slider(
        "Pitch search (+/- semitones)",
        0,
        12,
        int(settings.dtw_max_pitch_shift_semitones),
        1,
    )

if original_file and new_file:
    try:
        original = decode(original_file.getvalue())
        new = decode(new_file.getvalue())
    except Exception as exc:
        st.error(f"Could not decode the uploaded audio: {exc}")
        st.stop()

    tab_full, tab_manual = st.tabs(["Full SampleID → DTW", "Manual candidate → DTW"])

    with tab_full:
        detected_checkpoint = os.getenv("LASTRADA_SAMPLEID_CHECKPOINT") or (
            str(Path("checkpoints/sampleid-best.ckpt").resolve())
            if Path("checkpoints/sampleid-best.ckpt").is_file()
            else ""
        )
        checkpoint_text = st.text_input(
            "Sony checkpoint path",
            value=detected_checkpoint,
            placeholder=r"C:\Users\you\.lastrada_sampleid\sampleid-best.ckpt",
            help=(
                "Paste the full path to sampleid-best.ckpt, set LASTRADA_SAMPLEID_CHECKPOINT, "
                "or place it in checkpoints/sampleid-best.ckpt."
            ),
        )
        checkpoint = checkpoint_text.strip() or None
        checkpoint_ok = bool(checkpoint and Path(checkpoint).is_file())

        if checkpoint_ok:
            size_mb = Path(checkpoint).stat().st_size / 1024 / 1024
            st.success(f"Checkpoint found ({size_mb:.1f} MB): {checkpoint}")
        elif checkpoint:
            st.error(f"Checkpoint path does not exist: {checkpoint}")
        else:
            st.warning("Sony checkpoint is not configured on this machine.")

        c1, c2, c3 = st.columns(3)
        with c1:
            threshold = st.slider(
                "Existing v0 Sony similarity threshold",
                -1.0,
                1.0,
                float(settings.sampleid_similarity_threshold),
                0.01,
            )
        with c2:
            chunk_seconds = st.slider(
                "Sony chunk seconds",
                1.0,
                10.0,
                float(settings.sampleid_chunk_seconds),
                0.5,
            )
        with c3:
            hop_seconds = st.slider(
                "Sony hop seconds",
                0.5,
                5.0,
                float(settings.sampleid_hop_seconds),
                0.5,
            )

        st.warning(
            "The current Lastrada v0 SampleID adapter still uses an uncalibrated absolute cosine threshold. "
            "This test bench is for DTW integration testing, not final Sony candidate logic."
        )

        if st.button("Run full pipeline", type="primary", key="run_full"):
            if not checkpoint_ok:
                st.error(
                    "Sony checkpoint is unavailable. Paste a valid checkpoint path above or use the Manual candidate tab."
                )
            else:
                coarse = None
                try:
                    adapter = SampleIDAdapter(
                        checkpoint,
                        os.getenv("LASTRADA_CACHE_DIR", "cache") + "/sampleid",
                        batch_size=settings.sampleid_batch_size,
                    )
                    with st.spinner("Running Sony SampleID..."):
                        coarse = adapter.match(
                            original,
                            new,
                            threshold=threshold,
                            seconds=chunk_seconds,
                            hop=hop_seconds,
                        )
                except SampleIDUnavailable as exc:
                    st.error(str(exc))

                if coarse:
                    rows = []
                    refined_intervals = []

                    for idx, candidate in enumerate(coarse, start=1):
                        direct = refine_candidate(original, new, candidate)
                        if direct.source == "direct_waveform_local_alignment":
                            final = direct
                            method = "direct waveform"
                        else:
                            final = refine_candidate_dtw(
                                original,
                                new,
                                candidate,
                                search_padding=padding,
                                max_pitch_shift_semitones=max_pitch,
                                minimum_duration_ratio=min_ratio,
                                maximum_duration_ratio=max_ratio,
                                minimum_duration=settings.dtw_minimum_duration_seconds,
                            )
                            if final.source == "dtw_chroma_local_alignment":
                                method = "guarded DTW"
                            else:
                                final = candidate
                                method = "coarse Sony fallback"

                        refined_intervals.append(final)
                        source_duration = (
                            candidate.original_end - candidate.original_start
                            if candidate.original_start is not None
                            else None
                        )
                        refined_duration = final.new_end - final.new_start
                        ratio = (
                            refined_duration / source_duration
                            if source_duration and source_duration > 0
                            else None
                        )

                        rows.append(
                            {
                                "candidate": idx,
                                "sony_similarity": candidate.similarity,
                                "source_start": candidate.original_start,
                                "source_end": candidate.original_end,
                                "sony_new_start": candidate.new_start,
                                "sony_new_end": candidate.new_end,
                                "final_new_start": final.new_start,
                                "final_new_end": final.new_end,
                                "final_duration_s": refined_duration,
                                "duration_ratio": ratio,
                                "method": method,
                                "plausible_ratio": (
                                    duration_ratio_is_plausible(
                                        source_duration,
                                        refined_duration,
                                        min_ratio,
                                        max_ratio,
                                    )
                                    if source_duration
                                    else None
                                ),
                            }
                        )

                    df = pd.DataFrame(rows)
                    st.subheader("Candidate-by-candidate results")
                    st.dataframe(df, use_container_width=True, hide_index=True)

                    seconds, percent = coverage(refined_intervals, new.duration)
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Sony candidates", len(coarse))
                    m2.metric("Union candidate seconds", f"{seconds:.2f}s")
                    m3.metric("Union candidate coverage", f"{percent:.2f}%")

                    counts = df["method"].value_counts().rename_axis("method").reset_index(name="count")
                    st.subheader("How candidates were handled")
                    st.dataframe(counts, use_container_width=True, hide_index=True)

                    st.download_button(
                        "Download test results CSV",
                        df.to_csv(index=False).encode("utf-8"),
                        file_name="dtw_test_results.csv",
                        mime="text/csv",
                    )
                elif coarse == []:
                    st.info("SampleID ran successfully but returned no candidates under the current v0 settings.")

    with tab_manual:
        st.write(
            "Use this when you already know one approximate Sony candidate or want to test DTW independently."
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            source_start = st.number_input(
                "Source start (s)", min_value=0.0, value=0.0, step=0.5
            )
        with c2:
            source_end = st.number_input(
                "Source end (s)", min_value=0.1, value=5.0, step=0.5
            )
        with c3:
            new_start = st.number_input(
                "Derivative hint start (s)", min_value=0.0, value=0.0, step=0.5
            )
        with c4:
            new_end = st.number_input(
                "Derivative hint end (s)", min_value=0.1, value=5.0, step=0.5
            )

        if st.button("Run manual DTW test", type="primary", key="run_manual"):
            if source_end <= source_start or new_end <= new_start:
                st.error("End timestamps must be after start timestamps.")
            else:
                candidate = Interval(
                    new_start=float(new_start),
                    new_end=float(new_end),
                    original_start=float(source_start),
                    original_end=float(source_end),
                    source="manual_test_candidate",
                    status="candidate",
                )
                refined = refine_candidate_dtw(
                    original,
                    new,
                    candidate,
                    search_padding=padding,
                    max_pitch_shift_semitones=max_pitch,
                    minimum_duration_ratio=min_ratio,
                    maximum_duration_ratio=max_ratio,
                    minimum_duration=settings.dtw_minimum_duration_seconds,
                )

                source_duration = source_end - source_start
                before_duration = new_end - new_start
                after_duration = refined.new_end - refined.new_start

                result = pd.DataFrame(
                    [
                        {
                            "source_start": source_start,
                            "source_end": source_end,
                            "source_duration_s": source_duration,
                            "hint_new_start": new_start,
                            "hint_new_end": new_end,
                            "hint_duration_s": before_duration,
                            "final_new_start": refined.new_start,
                            "final_new_end": refined.new_end,
                            "final_duration_s": after_duration,
                            "duration_ratio": after_duration / source_duration,
                            "method": refined.source,
                            "dtw_refined": refined.source == "dtw_chroma_local_alignment",
                        }
                    ]
                )

                st.dataframe(result, use_container_width=True, hide_index=True)

                if refined.source == "dtw_chroma_local_alignment":
                    st.success(
                        "Guarded DTW found a plausible refinement under the current duration-ratio limits."
                    )
                else:
                    st.info(
                        "DTW abstained. The coarse candidate was preserved because no plausible refinement passed the guardrails."
                    )

                st.download_button(
                    "Download manual DTW result CSV",
                    result.to_csv(index=False).encode("utf-8"),
                    file_name="manual_dtw_test.csv",
                    mime="text/csv",
                )
else:
    st.info("Upload both tracks to begin.")
