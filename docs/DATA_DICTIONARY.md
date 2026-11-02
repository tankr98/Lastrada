# Historical reference data dictionary

The importer validates all columns below and preserves stable identifiers. Source workbooks and case-level audit outputs stay local; no real examples appear here.

| Column | Meaning / handling |
|---|---|
| example id | Required unique case identifier; never regenerated |
| test pair | Nonempty marks reserved evaluation case; never retrieval or tuning |
| test note | Reserved control note; verify its meaning before evaluating master negatives |
| pair folder | Relative audio folder; validated against configured audio root |
| new song title / new artist(s) | New-work identity |
| original song title / original artist(s) | Source-work identity |
| new writer(s) / original writer(s) | Semicolon-separated credits; metadata, not evidence of direct audio reuse |
| new song audio file / original song audio file | Referenced filenames; presence does not establish local audio availability |
| new song YouTube / original song YouTube | Reference metadata only; no downloading performed |
| use type | Historical reference conclusion; excluded from Stage 1 |
| nature of the use | Target/reference paragraph; excluded from Stage 1 |
| timestamps | Semicolon-separated M:SS–M:SS or H:MM:SS ranges; malformed/incomplete/reversed endpoints reported, not invented |
| sections named | Reference section labels; excluded from Stage 1 |
| six class | Exact client taxonomy; usually rule-derived until confirmed |
| six class confidence | Low/blank confidence is not reliable truth |
| confirmed by Stephen | Only explicit yes/true/confirmed or matching class confirms a valid label; blanks never do |
| loop language | Historical text-derived field, not model evidence |
| audio notes | Version limitations retained separately; block coverage scoring until validated |

Taxonomy: `throughout`, `intro_outro_with_chorus`, `chorus_only`, `intro_outro_without_chorus`, `verses`, `one_time`. Musical sections such as `verse` are not additional placement classes.

Intake uses an explicit metadata whitelist. Ground truth is available only to ingestion/evaluation/reviewer reference tools. Public synthetic fixtures use generated identifiers, titles, waveforms and narratives.
