"""Historical references and labels never enter the prediction boundary."""

import re
from pathlib import Path
import pandas as pd
from lastrada.schemas.models import Intake, Work, PLACEMENT_CLASSES

EXPECTED_COLUMNS = [
    "example id",
    "test pair",
    "test note",
    "pair folder",
    "new song title",
    "new artist(s)",
    "new writer(s)",
    "new song audio file",
    "new song YouTube",
    "original song title",
    "original artist(s)",
    "original writer(s)",
    "original song audio file",
    "original song YouTube",
    "use type",
    "nature of the use",
    "timestamps",
    "sections named",
    "six class",
    "six class confidence",
    "confirmed by Stephen",
    "loop language",
    "audio notes",
]
TIME = r"(?:(?:\d+):)?\d{1,2}:\d{2}"
RANGE = re.compile(rf"(?P<start>{TIME})\s*[-–—]\s*(?P<end>{TIME})")


def parse_time(value):
    parts = [int(p) for p in value.split(":")]
    if len(parts) not in (2, 3) or any(p >= 60 for p in parts[1:]):
        raise ValueError("Invalid time")
    return sum(v * 60**i for i, v in enumerate(reversed(parts)))


def parse_timestamps(value):
    ranges, issues = [], []
    for piece in str(value or "").split(";"):
        piece = piece.strip()
        if not piece:
            continue
        match = RANGE.fullmatch(piece)
        if not match:
            issues.append(f"Unparsed timestamp: {piece}")
            continue
        try:
            start, end = parse_time(match["start"]), parse_time(match["end"])
            if end <= start:
                raise ValueError("End before start")
            ranges.append((float(start), float(end)))
        except ValueError:
            issues.append(f"Invalid timestamp range: {piece}")
    return ranges, issues


def confirmed_label(row):
    label = row.get("six class", "")
    confirmation = str(row.get("confirmed by Stephen", "")).strip().lower()
    if label in PLACEMENT_CLASSES and confirmation in {"yes", "true", "confirmed", label}:
        return label
    return None


def load_dataset(path):
    frame = pd.read_excel(path, dtype=str, keep_default_na=False)
    frame.columns = [str(c).strip() for c in frame.columns]
    missing = set(EXPECTED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    if frame["example id"].str.strip().eq("").any():
        raise ValueError("Every row must have an example id")
    if frame["example id"].duplicated().any():
        raise ValueError("Duplicate example ids")
    return frame


def intake_from_row(row, scope):
    # Explicit whitelist. No use-type conclusion, timings, sections or target paragraph.
    def work(prefix):
        return Work(
            title=row[f"{prefix} song title"],
            artist=row[f"{prefix} artist(s)"],
            writers=[w.strip() for w in row[f"{prefix} writer(s)"].split(";") if w.strip()],
            audio_file=row[f"{prefix} song audio file"] or None,
            reference_url=row[f"{prefix} song YouTube"] or None,
            audio_version_warning=row["audio notes"] or None,
        )

    return Intake(
        case_id=row["example id"],
        original_work=work("original"),
        new_work=work("new"),
        analysis_scope=scope,
    )


def safe_audio_path(root, row, kind):
    folder, filename = row.get("pair folder", ""), row.get(f"{kind} song audio file", "")
    if not filename:
        return None
    root = Path(root).resolve()
    path = (root / folder / filename).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Audio reference escapes configured root")
    return path if path.is_file() else None


def audit(frame, audio_root=None):
    records = frame.to_dict("records")
    pair_cols = ["new song title", "new artist(s)", "original song title", "original artist(s)"]
    normalized = frame[pair_cols].map(lambda x: " ".join(x.casefold().split()))
    duplicates = normalized.duplicated(keep=False)
    result = {
        "rows": len(frame),
        "columns": list(frame.columns),
        "missing_by_column": {c: int(frame[c].eq("").sum()) for c in frame},
        "duplicate_pair_ids": frame.loc[duplicates, "example id"].tolist(),
        "placement_counts": frame["six class"].value_counts().to_dict(),
        "confirmed_label_count": sum(confirmed_label(r) is not None for r in records),
        "invalid_labels": [
            r["example id"]
            for r in records
            if r["six class"] and r["six class"] not in PLACEMENT_CLASSES
        ],
        "scored_cases": [],
        "timestamp_issues": {},
        "audio_checked": audio_root is not None,
        "local_audio_pairs": None if audio_root is None else 0,
        "filename_pairs": sum(
            bool(r["new song audio file"] and r["original song audio file"]) for r in records
        ),
    }
    for row in records:
        _, issues = parse_timestamps(row["timestamps"])
        if issues:
            result["timestamp_issues"][row["example id"]] = issues
        if audio_root is not None:
            paths = [safe_audio_path(audio_root, row, p) for p in ("new", "original")]
            result["local_audio_pairs"] += int(all(paths))
        if row["test pair"]:
            result["scored_cases"].append(
                {
                    "case_id": row["example id"],
                    "test_pair": row["test pair"],
                    "interpolation_control": bool(row["test note"]),
                    "confirmed_label": confirmed_label(row),
                    "audio_version_warning": row["audio notes"],
                    "filenames_complete": bool(
                        row["new song audio file"] and row["original song audio file"]
                    ),
                }
            )
    return result


def retrieve_examples(frame, placement, exclude_ids=(), limit=3):
    """Development references only. Never inject retrieved text as analysis evidence."""
    if placement not in PLACEMENT_CLASSES:
        return []
    subset = frame[
        (frame["test pair"] == "")
        & (~frame["example id"].isin(exclude_ids))
        & (frame["six class"] == placement)
        & (frame["six class confidence"] == "high")
    ]
    # Returned references stay separate from predictions; callers label them explicitly.
    return [
        {
            "case_id": r["example id"],
            "reference_text": r["nature of the use"],
            "label_source": "expert_confirmed" if confirmed_label(r) else "rule_derived",
            "use_type": r["use type"],
        }
        for r in subset.to_dict("records")[:limit]
    ]
