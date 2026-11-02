import pandas as pd
import pytest
from lastrada.ingestion.dataset import EXPECTED_COLUMNS
from lastrada.schemas.models import Intake, Work


@pytest.fixture
def intake():
    return Intake(
        case_id="synthetic-test",
        original_work=Work(title="Source", artist="Tones"),
        new_work=Work(title="Mix", artist="Tones"),
        analysis_scope=["publishing", "master"],
    )


@pytest.fixture
def frame():
    rows = []
    for i in range(4):
        row = {c: "" for c in EXPECTED_COLUMNS}
        row.update(
            {
                "example id": f"SYN-{i}",
                "new song title": f"Mix {i}",
                "new artist(s)": "Synth",
                "original song title": "Source",
                "original artist(s)": "Synth",
                "six class": "chorus_only",
                "six class confidence": "high",
                "nature of the use": "Synthetic reference only.",
                "timestamps": "0:02-0:04; 0:03-0:05",
            }
        )
        rows.append(row)
    rows[0]["test pair"] = "1"
    rows[1]["six class confidence"] = "low"
    rows[2]["confirmed by Stephen"] = "yes"
    return pd.DataFrame(rows)
