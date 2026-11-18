"""Musical descriptions grounded in named parts and their placement.

The reference uses inform the writing style, never facts about a new pair. Stem
names support broad arrangement roles, not keys, chord progressions, lyrics,
syncopation, production effects or the prominence of a part in the final mix.
"""


def join_words(values):
    values = list(dict.fromkeys(values))
    return ", ".join(values[:-1]) + " and " + values[-1] if len(values) > 1 else "".join(values)


def named_parts(element):
    names = {
        "bass": "bass", "drums": "drums", "vocals": "vocals",
        "guitar": "guitar", "piano": "piano", "other": "other",
        "other sounds (unidentified)": "other",
    }
    pieces = [p.strip().lower() for p in element.split(",")]
    return list(dict.fromkeys(names[p] for p in pieces)) if all(p in names for p in pieces) else []


def role_preset(labels):
    parts = set(named_parts(", ".join(labels)))
    roles = []
    if "bass" in parts:
        roles.append("low-register foundation")
    if "drums" in parts:
        roles.append("rhythmic pulse")
    if parts & {"guitar", "piano"}:
        roles.append("pitched accompaniment")
    if "vocals" in parts:
        roles.append("vocal motif")
    if "other" in parts:
        roles.append("instrumental texture")
    value = join_words(roles)
    return value[0].upper() + value[1:] if value else "Musical texture in the sampled passages"


def arrangement(parts):
    """Describe every named component, without letting drums take priority."""
    if {"bass", "drums"}.issubset(parts):
        sentence = "The bass and drums provide a low-register foundation and rhythmic pulse"
        pitched = [p for p in ("guitar", "piano") if p in parts]
        if pitched:
            sentence += ", with " + join_words(pitched) + " adding pitched texture"
        if "other" in parts:
            sentence += " and an additional instrumental layer"
        if "vocals" in parts:
            sentence += " alongside the vocal phrase"
        return sentence + "."
    roles = {
        "bass": "a low-register bass foundation",
        "drums": "a rhythmic drum pulse",
        "guitar": "a pitched guitar texture",
        "piano": "a pitched piano texture",
        "vocals": "a vocal phrase",
        "other": "an additional instrumental texture",
    }
    if len(parts) > 1:
        return "Musically, the passage brings together " + join_words(roles[p] for p in parts) + "."
    return {
        "bass": "The bass places the musical emphasis in the low register, giving the passage a tonal anchor.",
        "drums": "The drum part supplies the passage’s rhythmic pulse and percussive character.",
        "guitar": "The guitar gives the passage a pitched texture that can carry a melodic or accompanying role.",
        "piano": "The piano gives the passage a pitched texture that can carry a melodic or harmonic role.",
        "vocals": "The vocal phrase brings a recognizable human voice into the arrangement.",
        "other": "The borrowed material adds an instrumental texture to the arrangement.",
    }.get(parts[0], "") if parts else ""


def structure(placement, repeated, short):
    if placement in {"intro_outro_without_chorus", "intro_outro_with_chorus"}:
        return ("Its return in the outro echoes the opening, framing the track with a shared motif."
                if placement == "intro_outro_without_chorus" else
                "Its return in the chorus and outro links those sections back to the opening motif.")
    if placement == "intro_only":
        return "Placed at the opening, the passage introduces the track’s musical character."
    if placement == "outro_only":
        return "Placed at the close, the passage gives the ending a distinct musical character."
    if placement == "chorus_only":
        return "Its chorus placement gives those sections a shared musical identity."
    if placement == "bridge_only":
        return "Its bridge placement gives that section a distinct musical identity."
    if repeated:
        return "The return of the same source phrase creates a recurring motif linking the sampled passages."
    if short:
        return "The brief appearance works as a musical accent within the arrangement."
    return "The extended passage gives the arrangement a continuing musical texture."
