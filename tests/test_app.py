from pathlib import Path
from streamlit.testing.v1 import AppTest


def by_label(elements, label):
    return next(e for e in elements if e.label == label)


def test_streamlit_synthetic_workflow_and_review_export():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    assert not app.exception
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Find suggested moments").click().run()
    assert not app.exception
    assert app.session_state["analysis"].synthetic
    assert app.session_state["analysis"].master.locate.sample_detected is None
    assert app.session_state["analysis"].publishing.locate.detection_status == "not_verified"
    by_label(app.text_input, "Your name / reviewer (required to mark as reviewed)").set_value(
        "Synthetic reviewer"
    )
    by_label(app.text_area, "Edit your Nature of Use draft").set_value("Synthetic review draft")
    by_label(app.button, "Save draft").click().run()
    assert not app.exception
    assert app.session_state["analysis"].review.status == "edited"
    assert (
        app.session_state["analysis"].review.corrected["nature_of_use"]["text"]
        == "Synthetic review draft"
    )
    assert app.session_state["analysis"].nature_of_use.text != "Synthetic review draft"
    by_label(app.button, "Mark document as reviewed").click().run()
    assert not app.exception
    assert app.session_state["analysis"].review.status == "edited"
    assert any("resolve uncertain" in e.value for e in app.error)


def test_intake_requires_paired_uploads_and_starts_without_results():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    by_label(app.button, "Start").click().run()
    assert not app.exception
    assert by_label(app.radio, "Type of reuse").value == "Both"
    assert "analysis" not in app.session_state
    by_label(app.button, "Find suggested moments").click().run()
    assert not app.exception
    assert any("Add both the original and new recordings" in e.value for e in app.error)
    assert "analysis" not in app.session_state


def test_demo_requires_metadata_and_respects_master_scope():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.text_input, "New artist").set_value("   ")
    by_label(app.button, "Find suggested moments").click().run()
    assert any("Enter a title and artist" in e.value for e in app.error)
    by_label(app.text_input, "New artist").set_value("Generated tones")
    by_label(app.radio, "Type of reuse").set_value("Master")
    by_label(app.button, "Find suggested moments").click().run()
    assert not app.exception
    assert app.session_state["analysis"].input.analysis_scope == ["master"]
    assert app.session_state["analysis"].publishing.locate.detection_status == "not_requested"


def test_next_back_flow_saves_draft_and_preserves_edits():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    assert by_label(app.button, "Next: Listen & explore →").disabled
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Find suggested moments").click().run()
    by_label(app.button, "Next: Listen & explore →").click().run()
    assert app.session_state["workflow_tab"] == "3 · Listen & check"
    for element in app.selectbox:
        if element.label == "Have you checked this use?":
            element.set_value("not_detected")
    app.run()
    by_label(app.button, "Next: Describe the sound →").click().run()
    assert app.session_state["workflow_tab"] == "4 · Describe the sound"
    for element in app.selectbox:
        if element.label == "Have you checked this use?":
            element.set_value("not_detected")
    for element in app.checkbox:
        if element.label == "I’ve listened and checked these details":
            element.check()
    by_label(app.text_area, "Edit your Nature of Use draft").set_value("Unsaved synthetic draft")
    by_label(app.text_input, "Your name / reviewer (required to mark as reviewed)").set_value(
        "Reviewer"
    ).run()
    by_label(app.button, "Next: Your Nature of Use →").click().run()
    assert not app.exception
    assert app.session_state["workflow_tab"] == "7 · Your Nature of Use"
    assert app.session_state["analysis"].review.status == "edited"
    assert (
        app.session_state["analysis"].review.corrected["nature_of_use"]["text"]
        == "Unsaved synthetic draft"
    )
    by_label(app.button, "← Back: Review your draft").click().run()
    assert (
        by_label(app.text_area, "Edit your Nature of Use draft").value == "Unsaved synthetic draft"
    )
    assert (
        by_label(app.text_input, "Your name / reviewer (required to mark as reviewed)").value
        == "Reviewer"
    )
    by_label(app.button, "← Back: Place the sample").click().run()
    by_label(app.button, "← Back: Add your tracks").click().run()
    assert app.session_state["workflow_tab"] == "1 · Add your tracks"
    assert app.session_state["analysis"].synthetic


def test_manual_step_cannot_bypass_intake():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py").run()
    by_label(app.button, "Start").click().run()
    app.session_state["workflow_tab"] = "7 · Your Nature of Use"
    app.run()
    # Defensive guard runs before the tab widget as well as on manual tab changes.
    assert app.session_state["workflow_tab"] == "1 · Add your tracks"


def test_next_does_not_revoke_unchanged_approval():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Find suggested moments").click().run()
    for element in app.selectbox:
        if element.label == "Have you checked this use?":
            element.set_value("not_detected")
    for element in app.checkbox:
        if element.label == "I’ve listened and checked these details":
            element.check()
    by_label(app.text_input, "Your name / reviewer (required to mark as reviewed)").set_value(
        "Reviewer"
    )
    by_label(app.text_area, "Edit your Nature of Use draft").set_value(
        "Reviewed synthetic finding."
    )
    by_label(app.button, "Mark document as reviewed").click().run()
    assert app.session_state["analysis"].review.status == "approved"
    by_label(app.button, "Next: Your Nature of Use →").click().run()
    assert not app.exception
    assert app.session_state["analysis"].review.status == "approved"
    by_label(app.button, "← Back: Review your draft").click().run()
    by_label(app.text_area, "Edit your Nature of Use draft").set_value("Changed synthetic finding.")
    by_label(app.button, "Next: Your Nature of Use →").click().run()
    assert app.session_state["analysis"].review.status == "edited"


def test_prefilled_times_require_confirmation_and_loop_answers_fill_only_blanks():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    assert app.session_state["dark_mode"] is True
    by_label(app.toggle, "Dark mode").set_value(False).run()
    assert app.session_state["dark_mode"] is False
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.radio, "Type of reuse").set_value("Master")
    by_label(app.button, "Find suggested moments").click().run()
    by_label(app.selectbox, "Have you checked this use?").set_value("verified").run()
    assert len(app.dataframe[0].value) > 0
    by_label(app.button, "Save draft").click().run()
    saved = app.session_state["analysis"].review.corrected["master"]["locate"]
    assert saved["detection_status"] == "candidate"
    assert saved["sample_detected"] is None
    assert saved["sample_occurrences"][0]["status"] == "estimated"
    question = next(r for r in app.radio if "repeating loop?" in r.label)
    question.set_value("Yes").run()
    by_label(app.button, "Use this answer to fill the details").click().run()
    assert (
        by_label(app.text_input, "Does it loop or repeat?").value
        == "A short loop repeated in the track"
    )
    by_label(app.text_input, "Does it loop or repeat?").set_value("My own loop description").run()
    by_label(app.button, "Use this answer to fill the details").click().run()
    assert by_label(app.text_input, "Does it loop or repeat?").value == "My own loop description"
    by_label(app.radio, "Do these times match the sample you hear?").set_value(
        "Yes, use these times"
    ).run()
    by_label(app.button, "Save draft").click().run()
    saved = app.session_state["analysis"].review.corrected["master"]["locate"]
    assert saved["detection_status"] == "verified"
    assert saved["sample_occurrences"][0]["source"] == "expert_review"


def test_seven_screen_navigation_keeps_musical_details():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    assert by_label(app.button, "Next: Track details →").disabled
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Next: Track details →").click().run()
    assert app.session_state["workflow_tab"] == "2 · Track details"
    by_label(app.radio, "Type of reuse").set_value("Master")
    by_label(app.button, "Find suggested moments").click().run()
    assert app.session_state["workflow_tab"] == "3 · Listen & check"
    by_label(app.selectbox, "Have you checked this use?").set_value("verified")
    by_label(app.radio, "Do these times match the sample you hear?").set_value(
        "Yes, use these times"
    ).run()
    assert not by_label(app.button, "Next: Describe the sound →").disabled
    by_label(app.button, "Next: Describe the sound →").click().run()
    by_label(app.text_input, "What did you take?").set_value("A drum break")
    by_label(app.text_input, "How did you use it?").set_value("Chopped recording")
    by_label(app.text_input, "Does it loop or repeat?").set_value("Repeats")
    by_label(app.text_input, "What does it do in your track?").set_value("Drives groove").run()
    by_label(app.button, "Next: Place the sample →").click().run()
    assert app.session_state["workflow_tab"] == "5 · Place the sample"
    by_label(app.multiselect, "Which sections of your track?").set_value(["verse"])
    by_label(app.selectbox, "Where does it appear overall?").set_value("verses")
    by_label(app.checkbox, "I’ve listened and checked these details").check().run()
    by_label(app.button, "Next: Review your draft →").click().run()
    assert app.session_state["workflow_tab"] == "6 · Review your draft"
    by_label(app.text_input, "Your name / reviewer (required to mark as reviewed)").set_value(
        "Creator"
    ).run()
    by_label(app.button, "Next: Your Nature of Use →").click().run()
    assert app.session_state["workflow_tab"] == "7 · Your Nature of Use"
    saved = app.session_state["analysis"].review.corrected["master"]["describe"]
    assert saved["sections"] == ["verse"]
    assert saved["elements"][0]["value"] == "A drum break"
    by_label(app.button, "← Back: Review your draft").click().run()
    by_label(app.button, "← Back: Place the sample").click().run()
    assert by_label(app.multiselect, "Which sections of your track?").value == ["verse"]
    assert by_label(app.text_input, "What did you take?").value == "A drum break"
    assert not app.exception


def test_landing_restart_clears_case_and_preserves_theme():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    assert any(t.value == "Your Music, Your Time." for t in app.title)
    assert len(app.file_uploader) == 0
    by_label(app.toggle, "Dark mode").set_value(False).run()
    by_label(app.button, "Start").click().run()
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Next: Track details →").click().run()
    assert "preview_analysis" in app.session_state
    by_label(app.button, "Find suggested moments").click().run()
    by_label(app.button, "New Sample").click().run()
    assert not app.exception
    assert "analysis" not in app.session_state
    assert "preview_analysis" not in app.session_state
    assert app.session_state["dark_mode"] is False
    assert any(t.value == "Your Music, Your Time." for t in app.title)
    by_label(app.button, "Start").click().run()
    assert by_label(app.button, "Next: Track details →").disabled


def test_times_acceptance_and_quality_gates():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.radio, "Type of reuse").set_value("Master")
    by_label(app.button, "Find suggested moments").click().run()
    assert by_label(app.button, "Next: Describe the sound →").disabled
    by_label(app.selectbox, "Have you checked this use?").set_value("verified")
    by_label(app.radio, "Do these times match the sample you hear?").set_value(
        "Yes, use these times"
    ).run()
    assert not by_label(app.button, "Next: Describe the sound →").disabled
    by_label(app.button, "Save draft").click().run()
    saved = app.session_state["analysis"].review.corrected["master"]["locate"]["sample_occurrences"]
    seeds = app.session_state["review_master_seed_intervals"]
    assert [(i["new_start"], i["new_end"]) for i in saved] == [
        (i.new_start, i.new_end) for i in seeds
    ]
    assert all(i["status"] == "expert_verified" for i in saved)
    by_label(app.button, "Next: Describe the sound →").click().run()
    assert by_label(app.button, "Next: Place the sample →").disabled
    assert by_label(app.button, "Next: Your Nature of Use →").disabled
    assert by_label(app.button, "Generate Nature of Use draft").disabled
    by_label(app.radio, "Do these times match the sample you hear?").set_value(
        "No, let me edit"
    ).run()
    assert by_label(app.button, "Next: Describe the sound →").disabled
    by_label(app.checkbox, "I’ve listened and confirmed these times").check()
    by_label(app.selectbox, "Have you checked this use?").set_value("verified").run()
    assert not by_label(app.button, "Next: Describe the sound →").disabled


def test_recording_sample_can_finish_without_replayed_music():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Find suggested moments").click().run()
    # Reproduce the confusing state: accepting an empty publishing table.
    app.radio(key="review_publishing_agreement").set_value("Yes, use these times").run()
    assert by_label(app.button, "Next: Describe the sound →").disabled
    app.selectbox(key="review_publishing_status").set_value("not_detected").run()
    assert app.session_state["review_publishing_checked"] is True
    assert app.session_state["review_publishing_agreement"] == "Not checked"
    assert app.radio(key="review_publishing_agreement").disabled
    # The recording evidence is still required independently.
    assert by_label(app.button, "Next: Describe the sound →").disabled
    app.radio(key="review_master_agreement").set_value("Yes, use these times").run()
    assert not by_label(app.button, "Next: Describe the sound →").disabled
    by_label(app.button, "Next: Describe the sound →").click().run()
    for field, value in [
        ("element", "Drum break"),
        ("method", "Chopped original audio"),
        ("repetition", "Looped under verses"),
        ("role", "Rhythm bed"),
    ]:
        app.text_input(key="review_master_" + field).set_value(value)
    app.run()
    by_label(app.button, "Next: Place the sample →").click().run()
    app.multiselect(key="review_master_sections").set_value(["verse"])
    app.selectbox(key="review_master_placement").set_value("verses")
    app.checkbox(key="review_master_checked").check().run()
    assert not by_label(app.button, "Next: Review your draft →").disabled
    by_label(app.button, "Next: Review your draft →").click().run()
    app.text_input(key="review_name").set_value("Creator").run()
    assert not by_label(app.button, "Next: Your Nature of Use →").disabled
    by_label(app.button, "Next: Your Nature of Use →").click().run()
    assert not app.exception
    saved = app.session_state["analysis"].review.corrected
    assert saved["publishing"]["locate"]["detection_status"] == "not_detected"
    assert saved["publishing"]["locate"]["sample_occurrences"] == []
    assert saved["publishing"]["describe"]["elements"] == []
    assert saved["master"]["locate"]["sample_detected"] is True
    assert saved["master"]["locate"]["sample_occurrences"]


def test_reuse_analysis_and_media_without_work_on_hidden_screens(monkeypatch):
    from unittest.mock import Mock
    from lastrada.audio import io
    from lastrada.measurement import pfnmf
    from lastrada.reporting import comparison

    measure = Mock(wraps=pfnmf.measure)
    encode = Mock(wraps=io.wav_bytes)
    spectra = Mock(wraps=comparison.spectral_view)
    figure = Mock(wraps=comparison.comparison_figure)
    monkeypatch.setattr("lastrada.pipeline.measure", measure)
    monkeypatch.setattr(io, "wav_bytes", encode)
    monkeypatch.setattr(comparison, "spectral_view", spectra)
    monkeypatch.setattr(comparison, "comparison_figure", figure)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app.py", default_timeout=30
    ).run()
    by_label(app.button, "Start").click().run()
    by_label(app.checkbox, "Use a clearly labeled synthetic demonstration").check().run()
    by_label(app.button, "Next: Track details →").click().run()
    assert measure.call_count == 1
    by_label(app.radio, "Type of reuse").set_value("Master")
    by_label(app.button, "Find suggested moments").click().run()
    assert measure.call_count == 1  # Credits/scope do not repeat PF-NMF.
    assert encode.call_count == spectra.call_count == 2
    assert figure.call_count == 1
    app.radio(key="review_master_agreement").set_value("Yes, use these times").run()
    by_label(app.button, "Next: Describe the sound →").click().run()
    assert len(app.get("plotly_chart")) == 0
    assert len(app.get("audio")) == 0
    for value in ["Drum break", "Bassline", "Vocal phrase"]:
        app.text_input(key="review_master_element").set_value(value).run()
    assert measure.call_count == 1
    assert encode.call_count == spectra.call_count == 2
    assert figure.call_count == 1
    # Returning to listening retains exact evidence and cached media.
    app.button(key="wizard_back_3").click().run()
    assert len(app.get("plotly_chart")) == 1
    assert encode.call_count == spectra.call_count == 2
    assert app.text_input(key="review_master_element").value == "Vocal phrase"
    by_label(app.button, "New Sample").click().run()
    assert "playback_bytes" not in app.session_state
    assert "decoded_pair" not in app.session_state
