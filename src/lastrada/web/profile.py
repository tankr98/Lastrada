"""Explicit analysis profile for this branch's Firebase deployment."""

import json
from pathlib import Path


PROFILE = json.loads(
    (Path(__file__).resolve().parents[3] / "configs/web-profile.json").read_text()
)


def analysis_settings():
    from lastrada.config import Settings

    return Settings(
        stem_enabled=True,
        stem_reuse_model=True,
        stem_model_name=PROFILE["stem_model"],
        stem_max_candidates=PROFILE["initial_stem_candidates"],
        stem_separation_padding_seconds=4,
        stem_include_cross_other=True,
        stem_group_enabled=True,
        stem_group_workers=PROFILE.get("group_workers", 3),
        stem_group_max_representatives=PROFILE.get(
            "group_representatives",
            3,
        ),
        stem_group_positive_confirmations=PROFILE.get(
            "group_positive_confirmations",
            2,
        ),
        stem_group_negative_confirmations=PROFILE.get(
            "group_negative_confirmations",
            3,
        ),
        stem_dtw_workers=PROFILE.get("dtw_workers", 2),
    )
