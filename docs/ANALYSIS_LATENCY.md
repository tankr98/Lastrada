# Faster analysis and current draft wording

This update is for `local/stem-fast`, compared with deployed source
`77dd6d364ea8db7be54b968edc2299f47415abb4`.

## Model reuse

The Firebase profile reuses one bounded Demucs subprocess across the initial
candidate crops. Additional per-moment checks reuse up to two subprocesses on
CPU, matching the existing two-way crop concurrency. Each child caches only its
current separator configuration. The upstream CLI still performs decoding,
normalization, separation and WAV writing with the existing model, zero shifts,
overlap, segments, threads and crop limits. Other profiles retain the legacy
default unless `stem_reuse_model` is enabled.

A crop timeout or child error discards that child; a subsequent request starts a
fresh one. The owner closes all children when its pass ends. Children remain in
the analysis process group so the outer worker timeout also terminates them.
Models are reused within a job, not across separate analysis jobs.

## Earlier supported results

The existing analysis job publishes a private preview after supported waveform,
full-mix DTW or stem-assisted evidence is available. Coarse Sony similarities and
PF-NMF fallback estimates alone cannot open the description screen. The same
initial instrument comparisons continue, updating evidence and untouched fields.
Completed refinements survive a failure in a later crop.

The browser lets the creator review or edit sound and placement while those
comparisons finish. It preserves edits and explicit description confirmations.
The status explains that instrument checks are still running. Saving the draft
waits for the initial job to finish; the API rejects review/export writes during
that job to prevent a partial worker result from overwriting a review. Resetting
the sample ignores stale responses. Existing optional instrument passes and
their bounds remain available after the initial job.

This reduces time before useful interaction; it does not remove the need to
finish checks before saving/exporting. Model downloads on a cold worker, Sony
embedding time, queue wait and later per-moment checks can still take minutes.
No worker resources, IAM, quotas or matching thresholds change.

## Draft and export consistency

Placement selection synchronizes its section checkboxes. Saving changed sound,
lyrics, role, repetition, placement or timing regenerates the draft from those
inputs, including after save/reload. Selecting intro/outro replaces an obsolete
automatic “Repeated throughout the track” suggestion. Both the preview and
HTML/text export use the current placement.

Custom wording stays intact when structured answers have not changed. If changed
answers require regenerating custom text, the previous wording remains available
under **Earlier draft wording**; it is not included in the current document.
Records saved before the new draft metadata remain supported.

## Controlled local measurements

Both paths used the same installed production dependency image, predownloaded
weights, empty separate crop caches, no network, and a Docker limit of two CPUs
and 4 GiB. Inputs were manufactured known-copy audio, not a real-pair accuracy
benchmark. These are single-run local measurements, not hosted latency or
cold-start guarantees.

Four uncached six-second crops took **220.9 seconds** with a fresh process per
crop and **147.9 seconds** with model reuse (33% less). All decoded stem arrays
were byte-identical. Peak container memory was **1.16 GiB** and **1.18 GiB**,
respectively. Private raw measurements and scripts are kept under ignored
`outputs/private/latency-2026-11-09/`.

The full pipeline control used a 12-second generated source and 14-second mix
with a known six-second insertion. Final master timestamps, stem evidence and
instrument-occurrence records matched the baseline exactly. In the candidate
run the first supported result was available at **70.0 seconds**, before all
checks finished at **470.6 seconds**. Peak memory was **2.20 GiB**, versus
**2.21 GiB** for the baseline.

The baseline's total was **363.8 seconds**. This trial therefore did **not** show
a reduction in total wall time. It overlapped other local validation; even the
unchanged Sony inference stage varied from 29.4 to 66.4 seconds. Treat these
full-pipeline timings as evidence of earlier interaction and output equivalence,
not an isolated estimate of end-to-end speedup. The four-crop result above tests
the model-reuse change separately. Hosted and cold-download timings remain
unmeasured.

## Validation and version compatibility

Regression tests cover supported/unsupported previews, private result access,
blocked premature review/export, preserving completed evidence after failure,
model reuse/timeout/restart/cleanup, placement changes after reload, and custom
draft preservation. Browser scenarios exercise early interaction and reset,
edits through final completion, placement synchronization and exported wording,
alongside the existing classic and instrument flows.

All **268 Python tests**, Ruff, JavaScript syntax, the synthetic smoke check and
local launcher checks passed. Browser tests use simulated Google authentication
and cloud transport with real Python review/export validation.

An `extra_forbidden` error for `instrument_occurrences[*].model_name` indicates
that the reader does not accept the saved result format. The deployed source
above already accepts that field; the affected website/API/worker versions must
be checked before attributing a particular user's failure. The updated result
endpoint gives a concise compatibility message without dumping record values.
Deploy API, worker and Hosting from the same tested commit when releasing this
update; a frontend-only deployment cannot repair an older reader.
