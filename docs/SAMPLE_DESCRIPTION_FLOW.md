# Table to Nature of Use

The Firebase interface on `local/stem-fast` has four stages: tracks, analysis,
timestamp/instrument table, and **Nature of Use**. The table's **Nature of Use**
button opens the complete drafted document immediately, with preset editing
controls underneath. There are no intervening sound-description, placement, or
separate download screens. Confirmation and downloads live on this same page.

Both automatically identified samples and unresolved candidates have a table.
Supported automatic matches retain their estimated timing provenance. Unresolved
candidates keep the earlier accept/edit controls: merely viewing the table does
not confirm a recording match. Previously saved classic reviews remain compatible.
The Streamlit workflow is unchanged.

## Presets, editing, and confirmation

The draft uses the selected table intervals and current instrument evidence.
Sound, method, repetition, musical role, placement, and lyrics have editable
presets. Unknown instruments remain explicit, and source-presence estimates are
not relabeled as verified sampled instruments. Generic **matched passages** avoids
inventing verse or chorus names. Roles and placement inferred from timing are
proposals; lyrics are **Not assessed — add any reused lyrics**, never invented text
or a claim that no lyrics were used.

The complete document comes first. Controls underneath update it in place using
`POST /api/analyses/{id}/draft`, a private, read-only preview of the same generator
used for exports. It does not queue inference, consume an analysis operation,
save a review, or approve a description. Initial presets use the actual selected
intervals, including timestamp corrections. Later deliberate edits and cleared
fields are retained. An older preview response cannot replace newer inputs.

Changing placement also updates the section selections and narrative: **intro and
outro** cannot leave **throughout the track** in generated wording. A custom wording
editor is optional. Changing a preset regenerates the text and retains earlier
custom wording on the page. **Save draft** persists an unapproved draft;
**Confirm Nature of Use** approves the displayed details before enabling HTML/text
downloads. Further edits disable downloads until the revised document is confirmed.

The user can open a draft while initial instrument checks finish. Untouched
instrument defaults update with new evidence; deliberate edits remain intact.
Saving waits for a running job so it cannot overwrite the worker's result.
Preview failures keep edits and disable confirmation until a successful retry.
Saved descriptions and intentional empty lyrics survive reload, and the table
remains accessible through **Back to table**.

## Evidence and saved records

The server owns automatic times. Paired direct-waveform, full-mix DTW, and
stem-assisted DTW localizations qualify for automatically estimated times. Coarse retrieval windows
and PF-NMF activity alone do not qualify as automatically identified samples.
They remain available in the review table. Its expandable diagnostics explain
whether recording matching was unavailable, instrument verification was
incomplete, or the available results do not confirm a recording match.
This is a conservative eligibility rule, not a new detector or an accuracy claim.

When an initial eight-second stem probe finds an accepted alignment inside a
longer coarse candidate, the pipeline retains the coarse candidate and adds the
supported portion separately. The automatic flow uses that portion's actual
source and new-track bounds. Its instrument prefill comes from the selected
alignment; other stem fits may cover different times and are not transferred.
The coarse candidate's unchecked remainder is not included in reported use.
These intervals are marked as checked portions. Repetition remains unassessed,
and the document labels their measured coverage as **Located portions**, with
an explicit note that the reuse may extend further or appear elsewhere.
This fixes the case where accepted stem evidence was retained for diagnostics
but discarded as a localization, leaving the description screen blocked.

The screen explicitly distinguishes recording reuse from replayed melodies
(interpolations). Automatic interpolation analysis is not implemented by this
flow. A recording-match abstention cannot establish that no musical reuse took
place, and similarity candidates are not automatically relabeled as interpolations.
There is no added replay/re-singing confirmation step.

An expandable **Analysis details** panel identifies the uploaded works, records
which checks ran, and provides the case ID and existing authenticated JSON export.
This download is available without an approved document; HTML/text Nature of Use
exports still require review. Model preparation failures are recorded as unavailable
matching instead of looking like an ordinary search with no matches. Unknown
legacy method metadata stays unknown.

Description approval does not relabel timestamps as human-verified. Their raw
source, candidate status and ending cues are retained. Corrected paths record
`timing_source: automated`; the export calls these estimated timings and separates
them from the reviewed description. Raw analysis evidence stays intact.

New web cases request recording analysis only. Older records remain readable:
previously reviewed timings and explicit composition reviews are preserved;
unreviewed composition paths are marked not requested in the new corrected
document, not declared absent. `workflow` defaults to `classic` for old records
and callers. Exact description answers are saved separately so a deliberately
cleared field is not refilled on reload. The direct document preview requires the API and frontend from the same release.

## Validation and limits

Local validation uses real Python review/document logic with simulated Google
identity, uploads, and job transport. It does not establish live sign-in, hosted
inference, or musical accuracy.

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
node --check web/public/app.js
PYTHON=.venv/bin/python npm test --prefix web
PYTHON=.venv/bin/python npm run test:instruments --prefix web
```

Browser scenarios cover filled answers, unresolved instruments, no supported
match, unavailable models, incomplete verification, diagnostic downloads, saved
edits/reload, background instrument updates, confirming during a running check,
and a supported subset of mixed raw candidates. A recovered bounded match is
tested through description, review, export and reload. Existing
classic table and instrument scenarios remain in the suite. Draft-specific cases also cover preset edits, out-of-order preview responses, failed-preview retry, corrected table times, save/reload, and exact preview/export agreement. API tests cover saved
analysis validation, explicit description approval and JSON/HTML/text exports.
An unresolved 41-candidate case exercises visible tables, automatic instrument
updates without confirmation, reload, and direct draft generation, confirmation and export.
The frontend change also exposes candidates from existing saved results; they
do not need a fresh audio analysis just to reach the table or draft.

A read-only eligibility check on six older private saved song analyses found
supported localizations in two cases (one and three intervals respectively).
The other four contained only coarse candidates and would abstain. These were
not rerun through inference for that eligibility check; this is not a rescore of the historical
3/22 evaluation or evidence of improved real-song accuracy. No client audio is
tracked or uploaded as part of this change.

Deployment requires the API, worker and Hosting together. Use the existing
`deploy/redeploy.py` inspect/apply process with the exact commit after required CI
passes; see the final section of [STEM_FAST_FIREBASE.md](STEM_FAST_FIREBASE.md).
Do not use the older provisioning commands for an existing installation.
