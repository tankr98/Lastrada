"""Conservative, editable credits inferred from familiar audio filenames."""

import re
from pathlib import PurePath


def filename_credits(filename: str) -> tuple[str, str] | None:
    """Recognize 'Title by Artist' and conventional 'Artist - Title' names."""
    stem = PurePath(filename).stem.strip()
    by_parts = re.split(r"\s+by\s+", stem, flags=re.IGNORECASE)
    if len(by_parts) == 2:
        title, artist = by_parts
    elif len(by_parts) > 2:
        return None
    else:
        parts = re.split(r"\s+[-–—]\s+", stem)
        if len(parts) != 2:
            return None
        artist, title = parts
    title, artist = title.strip(), artist.strip()
    if not title or not artist:
        return None
    return title, artist


def prefill_credits(state, prefix: str, filename: str):
    """Refresh empty or earlier inferred fields; preserve user corrections."""
    credits = filename_credits(filename)
    previous = state.get(prefix + "_inferred_credits", {})
    inferred = {}
    for field, value in zip(("title", "artist"), credits or ("", ""), strict=True):
        key = prefix + "_" + field
        current = state.get(key, "")
        if current == "" or (field in previous and current == previous[field]):
            state[key] = value
            if value:
                inferred[field] = value
    state[prefix + "_inferred_credits"] = inferred
