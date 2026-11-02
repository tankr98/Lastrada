import pytest
from lastrada.ingestion.filenames import filename_credits, prefill_credits


@pytest.mark.parametrize(
    "filename, expected",
    [
        (
            "You Can't Turn Me Away by Sylvia Striplin.mp3",
            ("You Can't Turn Me Away", "Sylvia Striplin"),
        ),
        ("JEZEBEL by GIVĒON.mp3", ("JEZEBEL", "GIVĒON")),
        (
            "Sylvia Striplin - You Can't Turn Me Away.wav",
            ("You Can't Turn Me Away", "Sylvia Striplin"),
        ),
        (" Artist — Song (Live).flac", ("Song (Live)", "Artist")),
        ("Song BY Artist.MP3", ("Song", "Artist")),
        ("mix_final_03.mp3", None),
        ("Song.mp3", None),
        ("Artist - Song - Mix.mp3", None),
        ("Song by Artist by Another.mp3", None),
    ],
)
def test_filename_credits(filename, expected):
    assert filename_credits(filename) == expected


def test_prefill_preserves_corrections_and_refreshes_previous_guesses():
    state = {}
    prefill_credits(state, "original", "Song by Artist.mp3")
    assert state["original_title"] == "Song"
    assert state["original_artist"] == "Artist"
    state["original_title"] = "My corrected title"
    prefill_credits(state, "original", "New Song by New Artist.mp3")
    assert state["original_title"] == "My corrected title"
    assert state["original_artist"] == "New Artist"
    prefill_credits(state, "original", "unknown.mp3")
    assert state["original_title"] == "My corrected title"
    assert state["original_artist"] == ""
