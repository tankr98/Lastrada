"""One consistent interpretation of the creator's placement selection."""

PLACEMENT_SECTIONS = {
    "throughout": ["whole track"],
    "intro_only": ["intro"],
    "outro_only": ["outro"],
    "intro_outro_with_chorus": ["intro", "chorus", "outro"],
    "intro_outro_without_chorus": ["intro", "outro"],
    "chorus_only": ["chorus"],
    "verses": ["verse"],
    "bridge_only": ["bridge"],
}

PLACEMENT_TEXT = {
    "throughout": "throughout the track",
    "intro_only": "in the intro",
    "outro_only": "in the outro",
    "intro_outro_with_chorus": "in the intro, chorus and outro",
    "intro_outro_without_chorus": "in the intro and outro, outside the chorus",
    "chorus_only": "in the choruses",
    "verses": "in the verses",
    "bridge_only": "in the bridge",
    "selected_sections": "in the selected sections",
    "one_time": "in one appearance",
}


def description_signature(paths):
    """Ignore approval metadata when deciding whether a saved draft is stale."""
    return {
        rights: {
            "status": path["locate"]["detection_status"],
            "intervals": [
                [i.get(k) for k in ("new_start", "new_end", "original_start", "original_end")]
                for i in path["locate"]["sample_occurrences"]
            ],
            "elements": [(f["feature"], f.get("value")) for f in path["describe"]["elements"]],
            "description": {
                k: path["describe"].get(k)
                for k in (
                    "sections",
                    "reuse_type",
                    "repetition",
                    "role_in_new_song",
                )
            },
            "placement": path["classification"]["placement"],
        }
        for rights, path in paths.items()
    }
