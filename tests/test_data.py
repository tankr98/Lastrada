import pytest
from pydantic import ValidationError
from lastrada.ingestion.dataset import (
    load_dataset,
    audit,
    parse_timestamps,
    intake_from_row,
    retrieve_examples,
    confirmed_label,
    safe_audio_path,
)
from lastrada.schemas.models import Intake


def test_ingestion_and_missing_columns(frame, tmp_path):
    path = tmp_path / "synthetic.xlsx"
    frame.to_excel(path, index=False)
    assert len(load_dataset(path)) == 4
    frame.drop(columns=["timestamps"]).to_excel(path, index=False)
    with pytest.raises(ValueError, match="Missing required"):
        load_dataset(path)


def test_duplicate_ids_rejected(frame, tmp_path):
    frame.loc[1, "example id"] = frame.loc[0, "example id"]
    path = tmp_path / "synthetic.xlsx"
    frame.to_excel(path, index=False)
    with pytest.raises(ValueError, match="Duplicate example"):
        load_dataset(path)


def test_timestamps_no_invention():
    ranges, issues = parse_timestamps("0:02-0:05; 1:00-; 0:70-1:20; 2:00-1:00")
    assert ranges == [(2.0, 5.0)]
    assert len(issues) == 3


def test_audit_separates_confirmation_and_filename_presence(frame):
    result = audit(frame)
    assert result["confirmed_label_count"] == 1
    assert result["audio_checked"] is False
    assert result["local_audio_pairs"] is None
    assert len(result["scored_cases"]) == 1


def test_duplicate_song_pairs(frame):
    for c in ["new song title", "new artist(s)", "original song title", "original artist(s)"]:
        frame.loc[1, c] = frame.loc[0, c].upper() + " "
    assert set(audit(frame)["duplicate_pair_ids"]) == {"SYN-0", "SYN-1"}


def test_no_reference_leakage(frame):
    value = intake_from_row(frame.iloc[0].to_dict(), ["master"]).model_dump()
    assert "six class" not in str(value)
    assert "Synthetic reference only" not in str(value)
    with pytest.raises(ValidationError):
        Intake.model_validate({**value, "timestamps": [2, 4]})


def test_retrieval_never_returns_test_or_low_confidence(frame):
    result = retrieve_examples(frame, "chorus_only", exclude_ids=["SYN-3"])
    assert [r["case_id"] for r in result] == ["SYN-2"]
    assert result[0]["label_source"] == "expert_confirmed"


def test_rule_label_not_ground_truth(frame):
    assert confirmed_label(frame.iloc[0].to_dict()) is None


def test_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        safe_audio_path(
            tmp_path, {"pair folder": "../", "new song audio file": "secret.wav"}, "new"
        )
