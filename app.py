"""Local reviewer interface. UI state is session-local; exports contain no audio."""

import os
from copy import deepcopy
from time import perf_counter
from pathlib import Path
import pandas as pd
import streamlit as st
from lastrada.audio.io import decode, wav_bytes
from lastrada.audio.synthetic import demo_pair
from lastrada.pipeline import analyze_pair
from lastrada.schemas.models import Intake, Work, PLACEMENT_CLASSES, Feature, Interval, Placement
from lastrada.reporting.review import reviewed_copy
from lastrada.reporting.export import json_report
from lastrada.reporting.comparison import spectral_view, comparison_figure
from lastrada.pipeline import reuse_preview
from lastrada.reporting.document import (
    document_text,
    document_html,
    missing_document_inputs,
    creator_narrative,
)
from lastrada.alignment.intervals import coverage
from lastrada.classification.placement import classify
from lastrada.recognition.sampleid_adapter import SampleIDAdapter, SampleIDUnavailable
from lastrada.ingestion.dataset import load_dataset, retrieve_examples
from lastrada.ingestion.filenames import prefill_credits
from lastrada.config import load_settings
from lastrada.reporting.suggestions import suggested_intervals, timing_questions, confirmed_prefills

settings = load_settings()

st.set_page_config(
    page_title="Lastrada · Nature of Use",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="collapsed",
)
WORKFLOW_STEPS = [
    "1 · Add your tracks",
    "2 · Track details",
    "3 · Listen & check",
    "4 · Describe the sound",
    "5 · Place the sample",
    "6 · Review your draft",
    "7 · Your Nature of Use",
]


def new_sample():
    # Restart case data, including upload widget IDs, while preserving appearance.
    dark = st.session_state.get("dark_mode", True)
    st.session_state.clear()
    st.session_state.dark_mode = dark


def start_sample():
    st.session_state.started = True


def uploaded_credits(prefix):
    uploaded = st.session_state.get(prefix + "_upload")
    prefill_credits(st.session_state, prefix, uploaded.name if uploaded else "")


def pair_identity(original_file, new_file, synthetic):
    return (
        synthetic,
        None if synthetic else getattr(original_file, "file_id", None),
        None if synthetic else getattr(new_file, "file_id", None),
        settings.model_dump_json(),
    )


def prepare_preview(original_file, new_file, synthetic):
    identity = pair_identity(original_file, new_file, synthetic)
    if (
        st.session_state.get("preview_identity") == identity
        and "preview_analysis" in st.session_state
    ):
        return st.session_state.preview_analysis
    if synthetic:
        original, new, _ = demo_pair()
    else:
        original, new = decode(original_file.getvalue()), decode(new_file.getvalue())
    st.session_state.decoded_pair = (original, new)
    st.session_state.preview_identity = pair_identity(original_file, new_file, synthetic)
    intake = Intake(
        case_id="preview",
        original_work=Work(title="Original", artist="Unknown"),
        new_work=Work(title="New track", artist="Unknown"),
        analysis_scope=["master"],
    )
    return analyze_pair(intake, original, new, synthetic=synthetic, settings=settings)


def go_to_step(index):
    # Enforce prerequisites in callbacks as well as disabled navigation buttons.
    current = WORKFLOW_STEPS.index(st.session_state.get("workflow_tab", WORKFLOW_STEPS[0]))
    if index > current and index >= 3:
        if any(
            st.session_state.get("step_errors", {}).get(stage, [])
            for stage in range(2, min(index, 5))
        ):
            return
    if index == 6 and not st.session_state.get("document_ready", False):
        return
    st.session_state.refresh_screen = True
    st.session_state.workflow_tab = WORKFLOW_STEPS[
        index if "analysis" in st.session_state or index <= 1 else 0
    ]


def validate_step():
    if (
        "analysis" not in st.session_state
        and st.session_state.get("workflow_tab") not in WORKFLOW_STEPS[:2]
    ):
        st.session_state.workflow_tab = WORKFLOW_STEPS[0]


if "pending_narrative" in st.session_state:
    st.session_state.review_narrative = st.session_state.pop("pending_narrative")
if "pending_workflow_tab" in st.session_state:
    st.session_state.workflow_tab = st.session_state.pop("pending_workflow_tab")
legacy_steps = [
    "1 · Intake",
    "2 · Locate and measure",
    "3 · Classify and describe",
    "4 · Review and export",
]
if st.session_state.get("workflow_tab") not in WORKFLOW_STEPS:
    previous = st.session_state.get("workflow_tab")
    st.session_state.workflow_tab = WORKFLOW_STEPS[
        legacy_steps.index(previous) if previous in legacy_steps else 0
    ]
validate_step()
st.session_state.pop("refresh_screen", None)

brand, restart, appearance = st.columns([4, 1.4, 1.3])
restart.button("New Sample", on_click=new_sample, key="new_sample")
brand.caption("LASTRADA · NATURE OF USE")
with appearance:
    dark_mode = st.toggle("Dark mode", value=True, key="dark_mode")
current_step = WORKFLOW_STEPS.index(st.session_state.get("workflow_tab", WORKFLOW_STEPS[0]))
if st.session_state.get("started"):
    st.progress(
        (current_step + 1) / 7,
        text=f"STEP {current_step + 1} OF 7 · {WORKFLOW_STEPS[current_step].split(' · ')[1]}",
    )
palette = (
    dict(
        bg="#091426",
        surface="#14243b",
        field="#1b2e49",
        text="#f5f8ff",
        muted="#b9c7db",
        border="#334963",
    )
    if dark_mode
    else dict(
        bg="#f7f9fc",
        surface="#ffffff",
        field="#edf2f8",
        text="#14243b",
        muted="#52647a",
        border="#d5dfeb",
    )
)
st.markdown(
    f"""
<style>
.stApp,[data-testid="stHeader"] {{background:{palette["bg"]};color:{palette["text"]};}}
.block-container {{max-width:900px;padding-top:4rem;padding-bottom:4rem;}}
h1,h2,h3,h4 {{letter-spacing:-.035em;color:{palette["text"]} !important;}}
[data-testid="stSidebar"] {{background:{palette["surface"]};border:0;}}
[data-testid="stSidebar"][aria-expanded="true"] {{width:230px !important;min-width:230px !important;max-width:230px !important;}}
[data-testid="stSidebar"][aria-expanded="false"] {{width:0 !important;min-width:0 !important;max-width:0 !important;}}
[data-testid="stHeader"] button {{color:{palette["text"]} !important;}}
.stCaption,.stCaption p,[data-testid="stCaption"] p,small {{color:{palette["muted"]} !important;}}
[data-testid="stFileUploaderDropzone"] small,[data-testid="stFileUploaderDropzone"] span {{color:{palette["muted"]} !important;opacity:1 !important;}}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p {{opacity:1 !important;}}
[data-testid="stAlert"] {{background:{palette["surface"]};color:{palette["text"]};border:1px solid {palette["border"]};}}
[data-testid="stSidebar"] p {{font-size:.9rem;}}
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"],label {{color:{palette["text"]} !important;}}
[data-testid="stCaptionContainer"] p {{color:{palette["muted"]} !important;}}
[data-testid="stVerticalBlockBorderWrapper"]>div {{border-color:{palette["border"]} !important;border-radius:16px;}}
[data-testid="stFileUploaderDropzone"],input,textarea,[data-baseweb="select"]>div {{background:{palette["field"]} !important;color:{palette["text"]} !important;border-color:{palette["border"]} !important;}}
input::placeholder,textarea::placeholder {{color:{palette["muted"]} !important;}}
[data-baseweb="popover"],[role="listbox"],[role="option"] {{background:{palette["surface"]} !important;color:{palette["text"]} !important;}}
[data-testid="stExpander"] details {{background:{palette["surface"]};border-color:{palette["border"]};}}
[data-baseweb="tab-list"] {{gap:20px;margin-bottom:20px;border-bottom:1px solid {palette["border"]};}}
[data-baseweb="tab"] {{color:{palette["muted"]};font-weight:700;}}
[data-baseweb="tab"][aria-selected="true"] {{color:{palette["text"]};}}
button {{border-radius:10px !important;}}
button[kind="primary"],button[kind="primaryFormSubmit"] {{background:#dceaff !important;color:#091426 !important;font-weight:700;border-color:#dceaff;}}
[data-testid="stBaseButton-secondary"] {{background:{palette["surface"]};color:{palette["text"]};border-color:{palette["border"]};}}
.hero h1 {{font-size:32px;line-height:1.1;margin:22px 0 10px;}}
.hero p {{color:{palette["muted"]};font-size:17px;max-width:680px;line-height:1.6;}}
.st-key-nature_document {{background:#fff;color:#14243b;border-radius:16px;}}
.st-key-nature_document h3,.st-key-nature_document p,.st-key-nature_document [data-testid="stMarkdownContainer"] {{color:#14243b !important;}}
.st-key-nature_document [data-testid="stCaptionContainer"] p {{color:#52647a !important;}}
button[kind="primary"] *,button[kind="primaryFormSubmit"] * {{color:#091426 !important;}}
button:disabled {{opacity:.55;}}
[data-testid="stExpander"] details {{background:transparent;border:0;border-bottom:1px solid {palette["border"]};border-radius:0;}}
[data-testid="stProgress"] {{margin-bottom:2rem;}}
@keyframes stepReveal {{from {{opacity:0;transform:translateY(8px);}} to {{opacity:1;transform:translateY(0);}}}}
[class*="st-key-stage_"] {{animation:stepReveal .24s ease-out;}}
@media(prefers-reduced-motion:reduce) {{[class*="st-key-stage_"] {{animation:none;}}}}
</style>

""",
    unsafe_allow_html=True,
)
if not st.session_state.get("started"):
    st.markdown(
        """<style>.st-key-landing {text-align:center;padding:12vh 0 6vh;}
    .st-key-landing h1 {font-size:clamp(36px,5vw,64px);text-align:center;}
    .st-key-landing [data-testid="stMarkdownContainer"] {text-align:center;}
    .st-key-landing [data-testid="stButton"] {display:flex;justify-content:center;}
    .st-key-landing button {min-width:220px;min-height:58px;font-size:20px;}</style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="landing"):
        st.title("Your Music, Your Time.")
        st.write(
            "Upload your tracks, check where your sample appears, and create your Nature of Use document."
        )
        _, center, _ = st.columns([1, 1, 1])
        with center:
            st.button("Start", type="primary", on_click=start_sample, width="stretch")
    st.stop()

with st.sidebar:
    st.markdown("### Lastrada")
    st.caption("NATURE OF USE WORKSPACE")
    st.divider()
    for index, label in enumerate(WORKFLOW_STEPS):
        st.caption(("● " if index == current_step else "○ ") + label.split(" · ")[1])
    st.divider()
    st.caption("Made for creators · Review before sharing")
    with st.expander("Demo and advanced options"):
        synthetic = st.checkbox("Use a clearly labeled synthetic demonstration", key="demo")
        use_sampleid = st.checkbox("Include optional SampleID candidate matching", value=False)
        st.caption(
            "Experimental matching needs calibration. Scores do not establish accurate sample timestamps."
        )


def check_use(rights):
    prefix = f"review_{rights}_"
    absent = st.session_state.get(prefix + "status") == "not_detected"
    st.session_state[prefix + "checked"] = absent
    if absent:
        st.session_state[prefix + "agreement"] = "Not checked"
        st.session_state[prefix + "times_confirmed"] = False


def accept_times(rights):
    prefix = f"review_{rights}_"
    if st.session_state.get(prefix + "status") == "not_detected":
        return
    if st.session_state.get(prefix + "agreement") == "Yes, use these times":
        st.session_state[prefix + "status"] = "verified"
    else:
        st.session_state[prefix + "times_confirmed"] = False
        if st.session_state.get(prefix + "status") == "verified":
            st.session_state[prefix + "status"] = "candidate"


def apply_suggestion(rights, kind):
    prefix = f"review_{rights}_"
    for field, value in confirmed_prefills(kind, rights).items():
        existing = st.session_state.get(prefix + field)
        if existing in (None, "", "Needs review"):
            st.session_state[prefix + field] = value


def listen_assets(result):
    # Session-local: avoid rehashing whole audio arrays on every interaction.
    if "playback_bytes" not in st.session_state:
        st.session_state.playback_bytes = tuple(
            wav_bytes(st.session_state[key]) for key in ("original_audio", "new_audio")
        )
    if "spectral_views" not in st.session_state:
        st.session_state.spectral_views = tuple(
            spectral_view(st.session_state[key]) for key in ("original_audio", "new_audio")
        )
    intervals = suggested_intervals(result, "master")
    signature = (dark_mode, tuple(i.model_dump_json() for i in intervals))
    if st.session_state.get("comparison_signature") != signature:
        st.session_state.comparison_plot = comparison_figure(
            *st.session_state.spectral_views, intervals, dark=dark_mode
        )
        st.session_state.comparison_signature = signature
    return st.session_state.playback_bytes, st.session_state.comparison_plot


# Keep widgets mounted, as tabs did, so uploads and table edits survive navigation.
# Only the current screen is displayed; hidden screens never receive focus.
st.markdown(
    "<style>"
    + "".join(
        f'[class*="st-key-stage_{index}"] {{display:none !important;}}'
        for index in range(7)
        if index != current_step
    )
    + (
        ".st-key-review_shell {display:none !important;}"
        if current_step not in (2, 3, 4, 5)
        else ""
    )
    + ".st-key-review_shell > div {border:0 !important;}"
    + "</style>",
    unsafe_allow_html=True,
)
views = [
    st.container(),
    st.container(key="stage_2"),
    st.container(key="review_shell"),
    st.container(key="stage_6"),
]


with views[0]:
    with st.container(key="stage_0"):
        st.subheader("Step 1 · Add your tracks")
        st.caption(
            "You’ll need the original track, your new track, and the title and artist for each. MP3 files work."
        )
        left, right = st.columns(2, gap="large")
        with left, st.container(border=False):
            st.markdown("#### The original track")
            st.caption("The track you sampled, or the song whose melody or lyrics you replayed.")
            original_file = st.file_uploader(
                "Original audio",
                key="original_upload",
                on_change=uploaded_credits,
                args=("original",),
                type=["wav", "flac", "mp3", "m4a", "ogg"],
                help="MP3, WAV, FLAC, M4A or OGG · up to 100 MB · maximum 10 minutes",
            )
            if original_file and current_step == 0:
                st.audio(original_file.getvalue(), format=original_file.type or "audio/mpeg")
                st.caption(f"{original_file.name} · {original_file.size / 1024 / 1024:.1f} MB")
        with right, st.container(border=False):
            st.markdown("#### Your new track")
            st.caption("Your finished track or current mix containing the sample.")
            new_file = st.file_uploader(
                "New audio",
                key="new_upload",
                on_change=uploaded_credits,
                args=("new",),
                type=["wav", "flac", "mp3", "m4a", "ogg"],
                help="MP3, WAV, FLAC, M4A or OGG · up to 100 MB · maximum 10 minutes",
            )
            if new_file and current_step == 0:
                st.audio(new_file.getvalue(), format=new_file.type or "audio/mpeg")
                st.caption(f"{new_file.name} · {new_file.size / 1024 / 1024:.1f} MB")
        if synthetic:
            st.info(
                "Synthetic demo selected. Generated audio will be used instead of your uploads."
            )
        if st.button(
            "Next: Track details →",
            key="next_uploads",
            type="primary",
            disabled=not synthetic and (not original_file or not new_file),
        ):
            try:
                with st.spinner("Finding suggested moments…"):
                    st.session_state.preview_analysis = prepare_preview(
                        original_file, new_file, synthetic
                    )
                st.session_state.pending_workflow_tab = WORKFLOW_STEPS[1]
                st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
    with st.container(key="stage_1"):
        st.subheader("Name the tracks")
        st.caption(
            "These credits will appear in your document. Titles and artists recognized from filenames are filled in for you — check or edit them below."
        )
        if synthetic:
            for key, default in {
                "original_title": "Synthetic source",
                "original_artist": "Generated tones",
                "new_title": "Synthetic mix",
                "new_artist": "Generated tones",
            }.items():
                if st.session_state.get(key, "") == "":
                    st.session_state[key] = default
        preview = st.session_state.get("preview_analysis")
        if preview:
            if preview.master.locate.measurement_intervals:
                st.write(
                    "We found similar recorded sound at suggested moments. A recording sample involves master rights; replaying or re-singing the music involves publishing rights."
                )
            else:
                st.write(
                    "We didn’t find clear sound overlap. This does not rule out a recording sample or replayed music."
                )
            st.caption(
                "PF-NMF compares sound patterns; it cannot decide which rights apply. Tell us how you created the sample below."
            )
        with st.form("intake", border=False):
            left, right = st.columns(2, gap="large")
            with left:
                original_title = st.text_input(
                    "Original title",
                    key="original_title",
                    placeholder="Song title",
                )
                original_artist = st.text_input(
                    "Original artist",
                    key="original_artist",
                    placeholder="Artist or group",
                )
            with right:
                new_title = st.text_input("New title", key="new_title", placeholder="Song title")
                new_artist = st.text_input(
                    "New artist",
                    key="new_artist",
                    placeholder="Artist or group",
                )
            st.divider()
            st.markdown("#### What kind of reuse are you documenting?")
            scope = st.radio(
                "Type of reuse",
                ["Both", "Master", "Publishing"],
                horizontal=True,
                format_func=lambda x: {
                    "Master": "Sampled the recording",
                    "Publishing": "Replayed or re-sang it",
                    "Both": "Both / check both",
                }[x],
                help="Using the actual recording involves master rights. Replaying a melody or re-singing lyrics involves publishing rights. These are separate findings.",
            )
            st.caption(
                "Not sure? Choose both. Recording samples and replayed melodies or lyrics are documented separately."
            )
            with st.expander("Case reference and recording versions · optional"):
                case_id = st.text_input(
                    "Case identifier",
                    "synthetic-demo" if synthetic else "",
                    placeholder="Your internal reference",
                )
                original_warning = st.text_input(
                    "Original audio-version warning (optional)",
                    placeholder="For example, radio edit or different mix",
                )
                new_warning = st.text_input(
                    "New audio-version warning (optional)",
                    placeholder="For example, unreleased edit or extended intro",
                )
            st.caption(
                "Your recordings are processed in this workspace. Analysis produces an experimental draft that needs expert review."
            )
            submitted = st.form_submit_button(
                "Find suggested moments", type="primary", width="stretch"
            )
        if submitted:
            try:
                if not synthetic and (not original_file or not new_file):
                    raise ValueError("Add both the original and new recordings to start.")
                if not all(
                    value.strip()
                    for value in (original_title, original_artist, new_title, new_artist)
                ):
                    raise ValueError("Enter a title and artist for both recordings.")
                intake = Intake(
                    case_id=case_id.strip() or "local-case",
                    original_work=Work(
                        title=original_title.strip(),
                        artist=original_artist.strip(),
                        audio_file=original_file.name if original_file else None,
                        audio_version_warning=original_warning or None,
                    ),
                    new_work=Work(
                        title=new_title.strip(),
                        artist=new_artist.strip(),
                        audio_file=new_file.name if new_file else None,
                        audio_version_warning=new_warning or None,
                    ),
                    analysis_scope=["publishing", "master"] if scope == "Both" else [scope.lower()],
                )
                analysis_start = perf_counter()
                t = perf_counter()
                reusable = "preview_analysis" in st.session_state and st.session_state.get(
                    "preview_identity"
                ) == pair_identity(original_file, new_file, synthetic)
                if reusable:
                    original, new = st.session_state.decoded_pair
                elif synthetic:
                    original, new, _ = demo_pair()
                else:
                    if not original_file or not new_file:
                        raise ValueError("Upload both original and new recordings")
                    original, new = decode(original_file.getvalue()), decode(new_file.getvalue())
                preparation_time = perf_counter() - t
                adapter_setup_start = perf_counter()
                adapter = None
                adapter_error = None
                checkpoint = os.getenv("LASTRADA_SAMPLEID_CHECKPOINT") or (
                    "checkpoints/sampleid-best.ckpt"
                    if Path("checkpoints/sampleid-best.ckpt").is_file()
                    else None
                )
                if use_sampleid and "master" in intake.analysis_scope:
                    try:
                        adapter = SampleIDAdapter(
                            checkpoint,
                            os.getenv("LASTRADA_CACHE_DIR", "cache") + "/sampleid",
                            batch_size=settings.sampleid_batch_size,
                        )
                    except SampleIDUnavailable as exc:
                        adapter_error = str(exc)
                        st.warning(adapter_error)
                adapter_setup_time = perf_counter() - adapter_setup_start
                with st.spinner("Measuring audio locally…"):
                    result = (
                        reuse_preview(st.session_state.preview_analysis, intake)
                        if reusable and not use_sampleid
                        else analyze_pair(
                            intake,
                            original,
                            new,
                            adapter=adapter,
                            synthetic=synthetic,
                            settings=settings,
                        )
                    )
                if adapter_error:
                    result.methods["sampleid"] = f"unavailable: {adapter_error}"
                    result.warnings.append(adapter_error)
                result.timings_seconds["audio_preparation"] = preparation_time
                result.timings_seconds["model_setup"] = adapter_setup_time
                attachment_seconds = perf_counter() - analysis_start
                if reusable and not use_sampleid:
                    result.timings_seconds["intake_attachment"] = attachment_seconds
                    result.timings_seconds["total"] += attachment_seconds
                else:
                    result.timings_seconds["total"] = attachment_seconds
                st.session_state.analysis = result
                st.session_state.original_audio = original
                st.session_state.new_audio = new
                for asset in (
                    "playback_bytes",
                    "spectral_views",
                    "comparison_plot",
                    "comparison_signature",
                ):
                    st.session_state.pop(asset, None)
                # Clear prior case's review widgets and exports.
                for key in list(st.session_state):
                    if key.startswith("review_"):
                        del st.session_state[key]
                st.session_state.pending_workflow_tab = WORKFLOW_STEPS[2]
                st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        st.divider()
        st.button(
            "Next: Listen & explore →",
            key="next_intake",
            type="primary",
            width="content",
            disabled="analysis" not in st.session_state,
            on_click=go_to_step,
            args=(2,),
        )
        if "analysis" not in st.session_state:
            st.caption("Start an analysis above to continue.")
        st.button("← Back: Add your tracks", key="back_details", on_click=go_to_step, args=(0,))

result = st.session_state.get("analysis")
if current_step == 2:
    with views[1]:
        st.subheader("Listen & check")
        st.caption(
            "Compare the tracks and check the suggested moments. The analysis is a starting point, not a substitute for listening."
        )
        if result is None:
            st.write("Provide a pair in Intake, or try the synthetic demonstration.")
        else:
            playback, spectral_plot = listen_assets(result)
            original_player, new_player = st.columns(2, gap="large")
            with original_player:
                st.caption("THE ORIGINAL")
                st.audio(playback[0], format="audio/wav")
            with new_player:
                st.caption("YOUR TRACK")
                st.audio(playback[1], format="audio/wav")
            with st.container():
                st.subheader("See how the tracks compare")
                st.caption(
                    "These spectral views show the sound frequencies in each track. Hover over a mint marker to inspect a suggested moment and any available original-track times. Drag to zoom; double-click to reset."
                )
                if result.synthetic:
                    st.warning(
                        "Synthetic demonstration · No historical audio or pretrained inference is implied."
                    )
                for rights in result.input.analysis_scope:
                    path = getattr(result, rights)
                    st.subheader("Recorded audio" if rights == "master" else "Melody & lyrics")
                    st.caption(
                        {
                            "candidate": "Suggested matches · check by listening",
                            "not_verified": "Waiting for your listening check",
                            "unknown": "More information needed",
                            "not_detected": "No matches found by this check",
                            "verified": "Checked by the reviewer",
                        }.get(path.locate.detection_status, "Not requested")
                    )
                    if rights == "master":
                        seconds, percent = (
                            path.locate.total_covered_seconds,
                            path.locate.coverage_percentage,
                        )
                        st.metric(
                            "Estimated audio overlap — experimental",
                            f"{percent:.1f}% · {seconds:.2f}s",
                        )
                        st.caption(
                            "Shading marks moments with similar sound patterns. Shared instruments can also create overlap, so this is not a confirmed sample percentage."
                        )
                        st.plotly_chart(spectral_plot, width="stretch", key="spectral_comparison")
                        st.caption(
                            "PF-NMF highlights similar sound in your track; it does not tell us which passage of the original was used. Source times appear only when available from matching or your review. Each track’s colour scale is relative to its own peak."
                        )

                    else:
                        st.write(
                            "Replayed melodies and re-sung lyrics need your listening notes. The tool cannot automatically locate them yet. Describe them separately from any recording sample in step 3."
                        )
                with st.expander("How the analysis works · technical details"):
                    st.caption(
                        "The tool compares sound patterns. It cannot reliably identify instruments, lyrics or musical sections for you yet. Your listening notes complete the document."
                    )
                    st.json(result.methods)
                    st.write("Processing time (seconds)", result.timings_seconds)
                    for rights in result.input.analysis_scope:
                        st.write(getattr(result, rights).describe.limitations)


@st.fragment
def render_review():
    if st.session_state.pop("refresh_screen", False):
        st.rerun(scope="app")
    result = st.session_state.get("analysis")
    if result is not None:
        reviewed_paths = {}
        for rights in result.input.analysis_scope:
            path = getattr(result, rights).model_copy(deep=True)
            with st.container(border=False):
                with st.container(key=f"stage_2_{rights}_heading"):
                    st.subheader(
                        "Your recording sample"
                        if rights == "master"
                        else "Your replayed melody / lyrics"
                    )
                key = f"review_{rights}_"
                with st.container(key=f"stage_2_{rights}_status"):
                    status = st.selectbox(
                        "Have you checked this use?",
                        ["not_verified", "unknown", "candidate", "not_detected", "verified"],
                        index=[
                            "not_verified",
                            "unknown",
                            "candidate",
                            "not_detected",
                            "verified",
                        ].index(path.locate.detection_status),
                        key=key + "status",
                        on_change=check_use,
                        args=(rights,),
                        format_func=lambda x, rights=rights: {
                            "not_verified": "I haven’t checked it yet",
                            "unknown": "I’m not sure",
                            "candidate": "Possible use — needs checking",
                            "not_detected": (
                                "I didn’t replay or re-sing anything"
                                if rights == "publishing"
                                else "I didn’t use the original recording"
                            ),
                            "verified": "I’ve confirmed this use",
                        }[x],
                    )
                    st.caption(
                        "Choose ‘I’ve confirmed this use’ only after listening. Similarity scores cannot confirm a sample for you."
                    )
                if status == "not_detected":
                    st.markdown(
                        "<style>"
                        + "".join(
                            f".st-key-stage_{stage}_{rights}_{section} {{display:none !important;}}"
                            for stage, section in [(2, "times"), (3, "sound"), (4, "placement")]
                        )
                        + "</style>",
                        unsafe_allow_html=True,
                    )
                    with st.container(key=f"stage_2_{rights}_skipped"):
                        st.caption(
                            "No replayed or re-sung music — nothing to add for this check. Continue with your recording sample."
                            if rights == "publishing"
                            else "No recording sample — nothing to add for this check."
                        )
                with st.container(key=f"stage_2_{rights}_times"):
                    st.markdown("### Check the moments")
                    st.caption(
                        "Suggested moments carry straight into your document when you accept them. Listen first; you only need to edit if they are wrong."
                    )
                    if key + "seed_intervals" not in st.session_state:
                        st.session_state[key + "seed_intervals"] = suggested_intervals(
                            result, rights
                        )
                    seeds = st.session_state[key + "seed_intervals"]
                    agreement = st.radio(
                        "Do these times match the sample you hear?"
                        if seeds
                        else "Add the times you hear — no times were found for this use.",
                        ["Not checked", "Yes, use these times", "No, let me edit"],
                        key=key + "agreement",
                        horizontal=True,
                        on_change=accept_times,
                        args=(rights,),
                        disabled=status == "not_detected",
                    )
                    editable = agreement == "No, let me edit"
                    rows = [
                        {
                            "new_start": i.new_start,
                            "new_end": i.new_end,
                            "original_start": i.original_start,
                            "original_end": i.original_end,
                        }
                        for i in seeds
                    ]
                    intervals = st.data_editor(
                        pd.DataFrame(
                            rows, columns=["new_start", "new_end", "original_start", "original_end"]
                        ),
                        num_rows="dynamic",
                        disabled=status == "not_detected" or not editable,
                        key=key + "intervals",
                        column_config={
                            c: st.column_config.NumberColumn(
                                {
                                    "new_start": "Your track · start (s)",
                                    "new_end": "Your track · end (s)",
                                    "original_start": "Original · start (s)",
                                    "original_end": "Original · end (s)",
                                }[c],
                                min_value=0.0,
                                step=0.01,
                            )
                            for c in ["new_start", "new_end", "original_start", "original_end"]
                        },
                    )
                    with st.container(key=key + "manual_confirmation"):
                        manual_confirmed = st.checkbox(
                            "I’ve listened and confirmed these times",
                            key=key + "times_confirmed",
                            disabled=not editable,
                        )
                    if not editable:
                        st.markdown(
                            f"<style>.st-key-{key}manual_confirmation {{display:none;}}</style>",
                            unsafe_allow_html=True,
                        )
                    times_confirmed = (agreement == "Yes, use these times" and bool(seeds)) or (
                        editable and manual_confirmed
                    )
                    if status == "not_detected":
                        st.caption(
                            "No-use finding selected. Estimated times will not be included as sample use."
                        )
                    try:
                        current_times = [
                            Interval(
                                new_start=r["new_start"],
                                new_end=r["new_end"],
                                source="timing_question",
                            )
                            for r in intervals.to_dict("records")
                            if not pd.isna(r["new_start"]) and not pd.isna(r["new_end"])
                        ]
                        questions = timing_questions(current_times, result.durations["new"])
                    except ValueError:
                        questions = []
                    for suggestion in questions if status != "not_detected" else []:
                        answer = st.radio(
                            suggestion.question,
                            ["Not sure", "Yes", "No"],
                            horizontal=True,
                            key=key + "suggestion_" + suggestion.kind,
                        )
                        if answer == "Yes":
                            st.button(
                                "Use this answer to fill the details",
                                key=key + "apply_" + suggestion.kind,
                                on_click=apply_suggestion,
                                args=(rights, suggestion.kind),
                            )
                    st.caption(
                        "A timing pattern cannot identify a melody or prove a loop. Suggestions are added only when you say yes."
                    )
                with st.container(key=f"stage_3_{rights}_sound"):
                    st.subheader("What did you use?")
                    st.caption("Describe the sound in your own words.")
                    element = st.text_input(
                        "What did you take?",
                        placeholder="For example: a vocal phrase, drum break or guitar melody",
                        key=key + "element",
                    )
                    lyrics = st.text_input("Any reused lyrics? (optional)", key=key + "lyrics")
                    reuse_type = st.text_input(
                        "How did you use it?",
                        key=key + "method",
                        placeholder="For example: chopped the original recording, replayed the melody",
                    )
                    repetition = st.text_input(
                        "Does it loop or repeat?",
                        placeholder="For example: a four-bar loop under each verse",
                        key=key + "repetition",
                    )
                    role = st.text_input(
                        "What does it do in your track?",
                        placeholder="For example: the main hook, or a texture under new vocals",
                        key=key + "role",
                    )
                with st.container(key=f"stage_4_{rights}_placement"):
                    st.subheader("Where does it fit?")
                    st.caption("Tell us where the sample sits in your track.")
                    pitch = st.number_input(
                        "Did you pitch it up or down? (semitones, optional)",
                        value=0.0,
                        key=key + "pitch",
                    )
                    pitch_known = st.checkbox(
                        "I know this pitch change is correct", key=key + "pitch_known"
                    )
                    sections = st.multiselect(
                        "Which sections of your track?",
                        ["intro", "verse", "chorus", "bridge", "outro"],
                        key=key + "sections",
                    )
                    placement = st.selectbox(
                        "Where does it appear overall?",
                        ["Needs review"] + PLACEMENT_CLASSES,
                        key=key + "placement",
                        format_func=lambda x: {
                            "Needs review": "Still deciding",
                            "throughout": "Throughout the track",
                            "intro_outro_with_chorus": "Intro / outro and chorus",
                            "chorus_only": "Choruses only",
                            "intro_outro_without_chorus": "Intro / outro, outside the chorus",
                            "verses": "Verses",
                            "one_time": "One appearance",
                        }[x],
                    )
                    confirmed = st.checkbox(
                        "I’ve listened and checked these details", key=key + "checked"
                    )
                try:
                    occurrences = []
                    for row in intervals.to_dict("records"):
                        if status == "not_detected":
                            continue
                        if pd.isna(row["new_start"]) and pd.isna(row["new_end"]):
                            continue
                        if row["new_end"] > result.durations["new"]:
                            raise ValueError("A sample time extends beyond your track")
                        if (
                            not pd.isna(row["original_end"])
                            and row["original_end"] > result.durations["original"]
                        ):
                            raise ValueError("A source time extends beyond the original track")
                        occurrences.append(
                            Interval(
                                new_start=row["new_start"],
                                new_end=row["new_end"],
                                original_start=None
                                if pd.isna(row["original_start"])
                                else row["original_start"],
                                original_end=None
                                if pd.isna(row["original_end"])
                                else row["original_end"],
                                source="expert_review"
                                if times_confirmed
                                else "unconfirmed_timing_suggestion",
                                status="expert_verified" if times_confirmed else "estimated",
                            )
                        )
                    path.locate.sample_occurrences = occurrences
                    effective_status = (
                        "candidate"
                        if status == "verified" and not times_confirmed and occurrences
                        else status
                    )
                    path.locate.detection_status = effective_status
                    path.locate.sample_detected = (
                        True
                        if effective_status == "verified"
                        else False
                        if status == "not_detected"
                        else None
                    )
                    path.locate.pitch_shift_semitones = pitch if pitch_known else None
                    path.locate.review_required = not confirmed
                    if occurrences and effective_status == "verified":
                        sec, pct = coverage(occurrences, result.durations["new"])
                        path.locate.total_covered_seconds, path.locate.coverage_percentage = (
                            sec,
                            pct,
                        )
                    elif status == "not_detected":
                        if occurrences:
                            raise ValueError("Remove reuse occurrences for a not-detected finding")
                        path.locate.total_covered_seconds, path.locate.coverage_percentage = (
                            0.0,
                            0.0,
                        )
                    else:
                        # Unverified measurements remain in the automated snapshot, not reviewed truth.
                        path.locate.total_covered_seconds = None
                        path.locate.coverage_percentage = None
                    path.describe.elements = [
                        Feature(
                            feature=f,
                            value=v,
                            source="expert_review",
                            status="expert_verified",
                            review_required=not confirmed,
                        )
                        for f, v in [("musical_element", element), ("lyrics", lyrics)]
                        if v
                    ]
                    path.describe.sections, path.describe.reuse_type = sections, reuse_type or None
                    path.describe.repetition, path.describe.role_in_new_song = (
                        repetition or None,
                        role or None,
                    )
                    path.classification = classify(
                        path.locate.coverage_percentage, occurrences, sections, expert=True
                    )
                    path.classification.placement = (
                        None if placement == "Needs review" else Placement(placement)
                    )
                    path.classification.source = "expert_review"
                    path.classification.review_required = not confirmed or (
                        status == "verified" and placement == "Needs review"
                    )
                    if status == "not_detected":
                        # Retain widget edits for backtracking, but exclude unused-path claims.
                        from lastrada.schemas.models import Description, Classification

                        path.locate.pitch_shift_semitones = None
                        path.describe = Description()
                        path.classification = Classification(
                            source="expert_review",
                            review_required=not confirmed,
                            reason="Creator confirmed this type of reuse does not apply",
                        )
                    reviewed_paths[rights] = path.model_dump(mode="json")
                except ValueError as exc:
                    st.error(f"{rights.capitalize()}: {exc}")
        candidate = result.model_copy(deep=True)
        for rights, value in reviewed_paths.items():
            from lastrada.schemas.models import PathResult

            setattr(candidate, rights, PathResult.model_validate(value))
        candidate.review.corrected = None
        remaining = missing_document_inputs(candidate)
        step_errors = {2: [], 3: [], 4: []}
        for rights in result.input.analysis_scope:
            prefix = f"review_{rights}_"
            item = reviewed_paths.get(rights)
            if item is None:
                step_errors[2].append(f"{rights}: fix invalid timestamps")
                continue
            if item["locate"]["detection_status"] == "not_detected":
                if not st.session_state.get(prefix + "checked"):
                    step_errors[4].append(f"{rights}: confirm the no-use finding")
                continue
            if (
                item["locate"]["detection_status"] != "verified"
                or not item["locate"]["sample_occurrences"]
                or not all(
                    i["status"] == "expert_verified" for i in item["locate"]["sample_occurrences"]
                )
            ):
                step_errors[2].append(f"{rights}: confirm the use and accept or correct its times")
            for field, label in [
                ("element", "what you used"),
                ("method", "how you used it"),
                ("repetition", "how it repeats"),
                ("role", "its musical role"),
            ]:
                if not str(st.session_state.get(prefix + field, "")).strip():
                    step_errors[3].append(f"{rights}: describe {label}")
            if (
                not st.session_state.get(prefix + "sections")
                or st.session_state.get(prefix + "placement") == "Needs review"
                or not st.session_state.get(prefix + "checked")
            ):
                step_errors[4].append(
                    f"{rights}: choose sections and placement, then confirm the details"
                )
        st.session_state.step_errors = step_errors
        with st.container(key="stage_5"):
            st.subheader("Make it yours")
            st.caption("Read the draft, make any edits, and add your name.")
            if remaining:
                with st.expander(f"What’s still needed? · {len(remaining)} details"):
                    for item in remaining:
                        st.write("• " + item)
            else:
                st.success(
                    "Your musical details are complete. Generate the draft and give it a final read."
                )
            generated = creator_narrative(candidate)
            if st.button(
                "Generate Nature of Use draft",
                type="primary",
                disabled=bool(remaining) or any(step_errors.values()),
            ):
                st.session_state.review_narrative = generated
                st.session_state.review_generated_text = generated
            narrative = st.text_area(
                "Edit your Nature of Use draft",
                value=creator_narrative(result),
                height=180,
                key="review_narrative",
            )
            reviewer = st.text_input(
                "Your name / reviewer (required to mark as reviewed)", key="review_name"
            )
            notes = st.text_area("Anything still to check? (optional)", key="review_notes")
            left, right = st.columns(2)
            save = left.button("Save draft")
            approve = right.button("Mark document as reviewed", type="primary")
            st.divider()
            st.caption(
                "Next saves your description as a draft. Marking it as reviewed is a separate action."
            )
            back, forward = st.columns(2)
            back.button(
                "← Back: Place the sample", key="back_draft", on_click=go_to_step, args=(4,)
            )
            st.session_state.document_ready = (
                not remaining
                and not any(step_errors.values())
                and bool(reviewer.strip())
                and bool(narrative.strip())
            )
            if not st.session_state.document_ready:
                st.caption(
                    "Complete the listening checks and musical details, then add your name to continue."
                )
            proceed = forward.button(
                "Next: Your Nature of Use →",
                key="next_draft",
                type="primary",
                width="content",
                disabled=not st.session_state.document_ready,
            )
            if save or approve or proceed:
                try:
                    if len(reviewed_paths) != len(result.input.analysis_scope):
                        raise ValueError("Resolve invalid fields before saving")
                    if narrative in (
                        st.session_state.get("review_generated_text"),
                        creator_narrative(result),
                    ):
                        narrative = generated
                    updated = reviewed_copy(
                        result, reviewed_paths, narrative, reviewer, approve=approve, notes=notes
                    )
                    if (approve or proceed) and missing_document_inputs(updated):
                        raise ValueError(
                            "Complete the musical details before marking this document as reviewed: "
                            + "; ".join(missing_document_inputs(updated))
                        )
                    if proceed and result.review.status == "approved":
                        previous_payload = deepcopy(result.review.corrected)
                        updated_payload = deepcopy(updated.review.corrected)
                        for payload in (previous_payload, updated_payload):
                            payload["nature_of_use"].pop("review_required", None)
                        if (
                            previous_payload == updated_payload
                            and reviewer == result.review.reviewer
                            and notes == result.review.notes
                        ):
                            updated = result
                    st.session_state.analysis = updated
                    st.success("Draft saved for this session. Your document is ready to preview.")
                    result = st.session_state.analysis
                    if proceed:
                        st.session_state.pending_narrative = narrative
                        st.session_state.pending_workflow_tab = WORKFLOW_STEPS[6]
                        st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            with st.expander("Optional local historical references"):
                st.caption(
                    "Reference text is separate from predictions. Reserved test cases are always excluded. "
                    "Client data stays local and must not be committed."
                )
                spreadsheet = st.file_uploader(
                    "Local reference spreadsheet", type=["xlsx"], key="review_reference_upload"
                )
                if spreadsheet:
                    try:
                        reference_frame = load_dataset(spreadsheet)
                        selection = st.selectbox(
                            "Retrieve by reviewed placement",
                            PLACEMENT_CLASSES,
                            key="review_reference_class",
                        )
                        st.write(
                            retrieve_examples(
                                reference_frame, selection, exclude_ids=[result.case_id]
                            )
                        )
                    except ValueError as exc:
                        st.error(str(exc))

    for index, next_label in [
        (2, "Describe the sound"),
        (3, "Place the sample"),
        (4, "Review your draft"),
    ]:
        with st.container(key=f"stage_{index}_navigation"):
            errors = [
                error
                for stage in range(2, index + 1)
                for error in st.session_state.get("step_errors", {}).get(stage, [])
            ]
            if errors:
                st.caption("Before you continue: " + "; ".join(errors))
            st.divider()
            back, forward = st.columns([1, 2])
            back.button(
                "← Back", key=f"wizard_back_{index}", on_click=go_to_step, args=(index - 1,)
            )
            forward.button(
                f"Next: {next_label} →",
                key=f"wizard_next_{index}",
                type="primary",
                disabled=result is None
                or any(
                    st.session_state.get("step_errors", {}).get(stage, [])
                    for stage in range(2, index + 1)
                ),
                on_click=go_to_step,
                args=(index + 1,),
            )


with views[2]:
    render_review()

if current_step == 6:
    with views[3]:
        st.subheader("Your Nature of Use")
        st.caption(
            "The finished product: a clear account of what you took and how you used it. Review the text, then download your document."
        )
        if result is None:
            st.write(
                "Add your tracks and work through the first three steps to create your document."
            )
        else:
            missing = missing_document_inputs(result)
            if missing:
                st.warning("This is an unfinished draft. These details still need your input:")
                for item in missing:
                    st.write("• " + item)
            elif result.review.status != "approved":
                st.info(
                    "Your details are filled in. Give the description a final listening check and mark it as reviewed on the review screen."
                )
            else:
                st.success("Reviewed Nature of Use · ready to download")
            source = result.review.corrected or result.model_dump(mode="json")
            with st.container(border=True, key="nature_document"):
                st.caption(
                    "NATURE OF USE · "
                    + ("REVIEWED" if result.review.status == "approved" else "DRAFT")
                )
                st.subheader(result.input.new_work.title + " — " + result.input.new_work.artist)
                st.caption(
                    "Original: "
                    + result.input.original_work.title
                    + " — "
                    + result.input.original_work.artist
                )
                st.write(source["nature_of_use"]["text"])
            left, right = st.columns(2)
            left.download_button(
                "Download Nature of Use · HTML",
                document_html(result),
                "nature-of-use.html",
                "text/html",
                type="primary",
                width="content",
            )
            right.download_button(
                "Download Nature of Use · Text",
                document_text(result),
                "nature-of-use.txt",
                "text/plain",
                width="content",
            )
            st.caption(
                "The HTML document can be opened in a browser and printed to PDF. Download before leaving; drafts are saved for this session only."
            )
            with st.expander("Supporting analysis and saved versions"):
                st.json(result.model_dump(mode="json", exclude={"review"}))
                st.json(result.review.model_dump(mode="json"))
                st.download_button(
                    "Download analysis data · JSON",
                    json_report(result),
                    "lastrada-analysis.json",
                    "application/json",
                )
        st.divider()
        st.button("← Back: Review your draft", key="back_export", on_click=go_to_step, args=(5,))
