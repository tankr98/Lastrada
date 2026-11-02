"""Focused Streamlit tester for SampleID, DTW and optional Demucs stems.

Run from the repository root:
    streamlit run dtw_test_app.py

This is intentionally separate from the main Nature-of-Use UI so experimental
alignment evidence can be inspected without changing the client-facing workflow.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from lastrada.audio.io import decode, wav_bytes
from lastrada.alignment.intervals import coverage
from lastrada.alignment.local import refine_candidate
from lastrada.alignment.dtw import (
    duration_ratio_is_plausible,
    refine_candidate_dtw_details,
)
from lastrada.alignment.stems import compare_candidate_stems
from lastrada.config import load_settings
from lastrada.recognition.sampleid_adapter import (
    SampleIDAdapter,
    SampleIDUnavailable,
)
from lastrada.schemas.models import Interval
from lastrada.separation.demucs import (
    DemucsSeparator,
    StemSeparationUnavailable,
    demucs_available,
)


settings = load_settings()


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def _candidate_inputs(prefix: str):
    columns = st.columns(4)
    with columns[0]:
        source_start = st.number_input(
            "Source start (s)",
            min_value=0.0,
            value=0.0,
            step=0.5,
            key=f"{prefix}_source_start",
        )
    with columns[1]:
        source_end = st.number_input(
            "Source end (s)",
            min_value=0.1,
            value=5.0,
            step=0.5,
            key=f"{prefix}_source_end",
        )
    with columns[2]:
        new_start = st.number_input(
            "Derivative hint start (s)",
            min_value=0.0,
            value=0.0,
            step=0.5,
            key=f"{prefix}_new_start",
        )
    with columns[3]:
        new_end = st.number_input(
            "Derivative hint end (s)",
            min_value=0.1,
            value=5.0,
            step=0.5,
            key=f"{prefix}_new_end",
        )
    return source_start, source_end, new_start, new_end


def _make_interval(source_start, source_end, new_start, new_end, source):
    if source_end <= source_start or new_end <= new_start:
        raise ValueError("End timestamps must be after start timestamps")
    return Interval(
        new_start=float(new_start),
        new_end=float(new_end),
        original_start=float(source_start),
        original_end=float(source_end),
        source=source,
        status="candidate",
    )


def _stem_controls(prefix: str):
    model = st.selectbox(
        "Demucs model",
        ["htdemucs_6s", "htdemucs"],
        index=0,
        key=f"{prefix}_model",
        help=(
            "htdemucs_6s adds estimated guitar and piano stems. "
            "htdemucs provides vocals, drums, bass and other."
        ),
    )
    default_device = "cuda" if _cuda_available() else "cpu"
    device = st.selectbox(
        "Demucs device",
        ["cpu", "cuda"],
        index=0 if default_device == "cpu" else 1,
        key=f"{prefix}_device",
    )
    separation_padding = st.slider(
        "Stem crop padding (seconds)",
        1.0,
        12.0,
        4.0,
        0.5,
        key=f"{prefix}_separation_padding",
    )
    include_cross = st.checkbox(
        "Also compare guitar/piano against the 'other' stem",
        value=True,
        key=f"{prefix}_cross_other",
        help=(
            "Useful because separation can put guitar or piano energy into the "
            "generic other stem."
        ),
    )
    return model, device, separation_padding, include_cross


def _evidence_frame(result, candidate_number=None):
    rows = []
    for item in result.evidence:
        row = item.to_dict()
        if candidate_number is not None:
            row = {"candidate": candidate_number, **row}
        rows.append(row)
    return pd.DataFrame(rows)


def _render_best_stem_audio(result):
    best = result.best
    if best is None:
        return
    source_audio = result.source_region.stems.get(best.source_stem)
    derivative_audio = result.derivative_region.stems.get(best.derivative_stem)
    if source_audio is None or derivative_audio is None:
        return

    st.markdown(
        f"**Top ordered pair:** `{best.source_stem}` → "
        f"`{best.derivative_stem}`"
    )
    left, right = st.columns(2)
    with left:
        st.caption(f"Estimated source stem: {best.source_stem}")
        st.audio(wav_bytes(source_audio), format="audio/wav")
    with right:
        st.caption(f"Estimated derivative stem: {best.derivative_stem}")
        st.audio(wav_bytes(derivative_audio), format="audio/wav")


st.set_page_config(
    page_title="Lastrada · Alignment Test Bench",
    page_icon="🎯",
    layout="wide",
)

st.title("SampleID / DTW / Stem Test Bench")
st.caption(
    "Experimental evidence sandbox. Nothing shown here is a verified "
    "Nature-of-Use conclusion."
)

with st.expander("What this test bench does", expanded=True):
    st.markdown(
        """
**Full pipeline**
1. Sony SampleID proposes coarse source ↔ derivative candidate intervals.
2. Direct waveform correlation gets first chance for near-identical audio.
3. Guarded full-mix DTW handles moderate pitch/time transformations.
4. Optionally, Demucs separates padded candidate crops and compares selected
   source-stem ↔ derivative-stem pairs with the same guarded DTW logic.

**Manual DTW**
- Paste one candidate to test full-mix DTW without Sony.

**Stem-assisted candidate**
- Paste one candidate, separate both regions, compare the estimated stems and
  listen to the best ordered stem pair.

Demucs stems are estimates with bleed and artifacts. They are not recovered
studio multitracks, and a stem label is not a final musical-element conclusion.
        """
    )

left, right = st.columns(2)
with left:
    original_file = st.file_uploader(
        "Original / source track",
        type=["wav", "flac", "mp3", "m4a", "ogg"],
        key="alignment_test_original",
    )
with right:
    new_file = st.file_uploader(
        "New / derivative track",
        type=["wav", "flac", "mp3", "m4a", "ogg"],
        key="alignment_test_new",
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
        "Full-mix DTW search padding (seconds)",
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

    tab_full, tab_manual, tab_stems = st.tabs(
        [
            "Full SampleID → DTW",
            "Manual candidate → DTW",
            "Stem-assisted candidate",
        ]
    )

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
                "Paste the full path, set LASTRADA_SAMPLEID_CHECKPOINT, or place "
                "the file in checkpoints/sampleid-best.ckpt."
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

        columns = st.columns(3)
        with columns[0]:
            threshold = st.slider(
                "Existing v0 Sony similarity threshold",
                -1.0,
                1.0,
                float(settings.sampleid_similarity_threshold),
                0.01,
            )
        with columns[1]:
            chunk_seconds = st.slider(
                "Sony chunk seconds",
                1.0,
                10.0,
                float(settings.sampleid_chunk_seconds),
                0.5,
            )
        with columns[2]:
            hop_seconds = st.slider(
                "Sony hop seconds",
                0.5,
                5.0,
                float(settings.sampleid_hop_seconds),
                0.5,
            )

        st.warning(
            "The current Lastrada v0 SampleID adapter still uses an "
            "uncalibrated absolute cosine threshold. This test bench is for "
            "integration testing, not final Sony candidate logic."
        )

        run_stems = st.checkbox(
            "Run stem-assisted comparison on the strongest Sony candidates",
            value=False,
            key="full_run_stems",
        )
        if run_stems:
            top_n_stems = st.slider(
                "Number of Sony candidates to separate",
                1,
                3,
                1,
                key="full_top_n_stems",
                help="Demucs is compute-intensive, especially on CPU.",
            )
            full_model, full_device, full_stem_padding, full_cross = _stem_controls(
                "full"
            )
        else:
            top_n_stems = 0
            full_model = "htdemucs_6s"
            full_device = "cpu"
            full_stem_padding = 4.0
            full_cross = True

        if st.button("Run full pipeline", type="primary", key="run_full"):
            if not checkpoint_ok:
                st.error(
                    "Sony checkpoint is unavailable. Paste a valid checkpoint "
                    "path above or use one of the manual tabs."
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

                    for index, candidate in enumerate(coarse, start=1):
                        direct = refine_candidate(original, new, candidate)
                        if direct.source == "direct_waveform_local_alignment":
                            final = direct
                            method = "direct waveform"
                            detail = None
                        else:
                            detail = refine_candidate_dtw_details(
                                original,
                                new,
                                candidate,
                                search_padding=padding,
                                max_pitch_shift_semitones=max_pitch,
                                minimum_duration_ratio=min_ratio,
                                maximum_duration_ratio=max_ratio,
                                minimum_duration=(
                                    settings.dtw_minimum_duration_seconds
                                ),
                            )
                            final = detail.interval
                            method = (
                                "guarded DTW"
                                if detail.accepted
                                else "coarse Sony fallback"
                            )

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
                                "candidate": index,
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
                                "dtw_cost": (
                                    detail.mean_cost if detail is not None else None
                                ),
                                "pitch_shift_semitones": (
                                    detail.pitch_shift_semitones
                                    if detail is not None
                                    else None
                                ),
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

                    results_frame = pd.DataFrame(rows)
                    st.subheader("Candidate-by-candidate full-mix results")
                    st.dataframe(
                        results_frame,
                        use_container_width=True,
                        hide_index=True,
                    )

                    seconds, percent = coverage(refined_intervals, new.duration)
                    metrics = st.columns(3)
                    metrics[0].metric("Sony candidates", len(coarse))
                    metrics[1].metric("Union candidate seconds", f"{seconds:.2f}s")
                    metrics[2].metric("Union candidate coverage", f"{percent:.2f}%")

                    counts = (
                        results_frame["method"]
                        .value_counts()
                        .rename_axis("method")
                        .reset_index(name="count")
                    )
                    st.subheader("How candidates were handled")
                    st.dataframe(counts, use_container_width=True, hide_index=True)

                    st.download_button(
                        "Download full-mix test results CSV",
                        results_frame.to_csv(index=False).encode("utf-8"),
                        file_name="dtw_test_results.csv",
                        mime="text/csv",
                    )

                    if run_stems:
                        st.subheader("Stem-assisted evidence")
                        if not demucs_available():
                            st.error(
                                "Demucs is not installed in this environment. "
                                "Install the optional stems dependencies first."
                            )
                        else:
                            try:
                                separator = DemucsSeparator(
                                    model_name=full_model,
                                    device=full_device,
                                    cache_dir=(
                                        Path(
                                            os.getenv(
                                                "LASTRADA_CACHE_DIR", "cache"
                                            )
                                        )
                                        / "demucs"
                                    ),
                                )
                                stem_frames = []
                                first_stem_result = None
                                for candidate_number, candidate in enumerate(
                                    coarse[:top_n_stems], start=1
                                ):
                                    with st.spinner(
                                        "Separating candidate "
                                        f"{candidate_number}/{top_n_stems}..."
                                    ):
                                        stem_result = compare_candidate_stems(
                                            original,
                                            new,
                                            candidate,
                                            separator,
                                            separation_padding=(
                                                full_stem_padding
                                            ),
                                            dtw_search_padding=min(
                                                padding, full_stem_padding
                                            ),
                                            max_pitch_shift_semitones=max_pitch,
                                            minimum_duration_ratio=min_ratio,
                                            maximum_duration_ratio=max_ratio,
                                            minimum_duration=(
                                                settings.dtw_minimum_duration_seconds
                                            ),
                                            include_cross_other=full_cross,
                                        )
                                    if first_stem_result is None:
                                        first_stem_result = stem_result
                                    stem_frames.append(
                                        _evidence_frame(
                                            stem_result,
                                            candidate_number=candidate_number,
                                        )
                                    )

                                stem_frame = pd.concat(
                                    stem_frames, ignore_index=True
                                )
                                st.dataframe(
                                    stem_frame,
                                    use_container_width=True,
                                    hide_index=True,
                                )
                                accepted = int(stem_frame["accepted"].sum())
                                st.metric("Accepted stem-pair alignments", accepted)
                                if first_stem_result is not None:
                                    _render_best_stem_audio(first_stem_result)
                                st.download_button(
                                    "Download stem evidence CSV",
                                    stem_frame.to_csv(index=False).encode("utf-8"),
                                    file_name="stem_assisted_evidence.csv",
                                    mime="text/csv",
                                )
                            except StemSeparationUnavailable as exc:
                                st.error(str(exc))
                elif coarse == []:
                    st.info(
                        "SampleID ran successfully but returned no candidates "
                        "under the current v0 settings."
                    )

    with tab_manual:
        st.write(
            "Use this when you already know one approximate candidate or want "
            "to test full-mix DTW independently."
        )
        source_start, source_end, new_start, new_end = _candidate_inputs("manual")

        if st.button("Run manual DTW test", type="primary", key="run_manual"):
            try:
                candidate = _make_interval(
                    source_start,
                    source_end,
                    new_start,
                    new_end,
                    "manual_test_candidate",
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                detail = refine_candidate_dtw_details(
                    original,
                    new,
                    candidate,
                    search_padding=padding,
                    max_pitch_shift_semitones=max_pitch,
                    minimum_duration_ratio=min_ratio,
                    maximum_duration_ratio=max_ratio,
                    minimum_duration=settings.dtw_minimum_duration_seconds,
                )
                refined = detail.interval
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
                            "dtw_refined": detail.accepted,
                            "dtw_cost": detail.mean_cost,
                            "pitch_shift_semitones": (
                                detail.pitch_shift_semitones
                            ),
                            "reason": detail.reason,
                        }
                    ]
                )
                st.dataframe(result, use_container_width=True, hide_index=True)

                if detail.accepted:
                    st.success(
                        "Guarded DTW found a plausible refinement under the "
                        "current limits."
                    )
                else:
                    st.info(
                        "DTW abstained and preserved the coarse candidate. "
                        f"Reason: {detail.reason}."
                    )

                st.download_button(
                    "Download manual DTW result CSV",
                    result.to_csv(index=False).encode("utf-8"),
                    file_name="manual_dtw_test.csv",
                    mime="text/csv",
                )

    with tab_stems:
        st.write(
            "Paste one approximate candidate. The app separates only padded "
            "candidate crops, compares selected stem pairs and lets you listen "
            "to the strongest ordered pair."
        )
        if not demucs_available():
            st.error(
                "Demucs is not installed. From the repository root run:\n\n"
                "`.\\.venv\\Scripts\\python.exe -m pip install -e \".[stems]\"`"
            )

        source_start, source_end, new_start, new_end = _candidate_inputs("stems")
        stem_model, stem_device, stem_padding, cross_other = _stem_controls(
            "manual_stems"
        )

        if st.button(
            "Separate and compare stems",
            type="primary",
            key="run_stem_assisted",
            disabled=not demucs_available(),
        ):
            try:
                candidate = _make_interval(
                    source_start,
                    source_end,
                    new_start,
                    new_end,
                    "manual_stem_candidate",
                )
                separator = DemucsSeparator(
                    model_name=stem_model,
                    device=stem_device,
                    cache_dir=(
                        Path(os.getenv("LASTRADA_CACHE_DIR", "cache"))
                        / "demucs"
                    ),
                )
                with st.spinner(
                    "Separating both candidate regions. The first run may "
                    "download model weights and can take several minutes..."
                ):
                    stem_result = compare_candidate_stems(
                        original,
                        new,
                        candidate,
                        separator,
                        separation_padding=stem_padding,
                        dtw_search_padding=min(padding, stem_padding),
                        max_pitch_shift_semitones=max_pitch,
                        minimum_duration_ratio=min_ratio,
                        maximum_duration_ratio=max_ratio,
                        minimum_duration=settings.dtw_minimum_duration_seconds,
                        include_cross_other=cross_other,
                    )
            except (ValueError, StemSeparationUnavailable) as exc:
                st.error(str(exc))
            else:
                frame = _evidence_frame(stem_result)
                st.subheader("Ordered stem-pair evidence")
                st.caption(
                    "Accepted rows passed timing guardrails. Lower DTW cost is "
                    "a closer alignment under these features, not a probability."
                )
                st.dataframe(frame, use_container_width=True, hide_index=True)

                accepted = stem_result.accepted
                metrics = st.columns(3)
                metrics[0].metric(
                    "Source stems",
                    len(stem_result.source_region.stems),
                )
                metrics[1].metric(
                    "Derivative stems",
                    len(stem_result.derivative_region.stems),
                )
                metrics[2].metric("Accepted stem pairs", len(accepted))

                _render_best_stem_audio(stem_result)
                st.download_button(
                    "Download stem comparison CSV",
                    frame.to_csv(index=False).encode("utf-8"),
                    file_name="stem_comparison.csv",
                    mime="text/csv",
                )
                st.warning(
                    "A strong guitar→guitar row is supporting evidence that "
                    "the estimated guitar content aligns. It does not prove "
                    "that the exact studio guitar stem was recovered or that "
                    "the final musical-element label is guitar."
                )
else:
    st.info("Upload both tracks to begin.")
