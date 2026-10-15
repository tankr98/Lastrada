# Technical decisions and architecture

## Scope and routing

The high-level future-state workflow is preserved as eight steps: intake → validation → requester-informed rights routing → independent publishing/master analysis → synthesis → expert review → final output → delivery. In the implemented seven-stage analysis sequence, INPUT combines intake/validation/routing; LOCATE and DESCRIBE stay separate inside each rights path; CLASSIFY, SYNTHESIZE, EXPERT REVIEW and EXPORT follow. Delivery is a local download in v0.

Module boundaries: `schemas` holds strict Pydantic models; `audio` prepares local recordings; `measurement` provides PF-NMF; `recognition` supplies optional SampleID embeddings; `alignment` unions intervals and refines waveform patches; `publishing` and `master` generate independent findings; `classification` proposes placement; `synthesis` drafts evidence-based text; `reporting` preserves review versions and exports; `ingestion` and `evaluation` remain separate from the analysis input.

`Intake` accepts metadata and rights scope only. Historical descriptions, labels, annotated timestamps, use-type conclusions and reference answers cannot be added to it. Historical retrieval is explicitly labeled reference material and does not feed the automated narrative. Credits may still reveal relationships; evaluate this risk before using writer metadata in a learned model.

## PF-NMF baseline

The referenced client implementation was not available at build time. This implementation is a minimal experimental baseline, not a reproduction of its reported performance.

An 8 kHz mono magnitude STFT (512-sample window, 128-sample hop) is factorized into a reference dictionary using multiplicative-update NMF. Its normalized spectral atoms are fixed while target activations and eight free residual atoms are updated using Euclidean-loss multiplicative updates. The fixed spectral contribution divided by the total reconstructed spectral contribution produces a frame-wise activation ratio. Frames above 0.55 with sufficient energy are retained; internal gaps no longer than 200 ms are filled and regions shorter than 250 ms discarded. All these thresholds are experimental defaults validated on synthetic fixtures only. Two numerical threads bound CPU use. Full inputs are limited to ten minutes; analysis is synchronous in v0.

Union duration of activation regions is called *spectral activation coverage*, not verified sample duration. Identical/common instruments may strongly activate fixed components. The method does not recover source locations, pitch, tempo, lyrics, instrument identity or calibrated confidence. It is not a stand-alone detector, and absence of activation is not absence of compositional reuse. Section segmentation is not implemented. A >=95% temporal coverage heuristic can propose `throughout`; other classes require expert sections/choice. The `entire` coverage category is reserved for literal full duration.

## SampleID

Inspected Sony source revision: `e212b0b9974d52d334cc793ef1b8cabaf251e5f8`, MIT licensed. Current `SampleID.load_checkpoint(ckpt_path, device=cpu)` and `model(batch, audio=True)` APIs accept raw mono audio; upstream example uses 16 kHz, five-second batches. Embeddings are temporally averaged, so this adapter chunks explicitly and normalizes vectors for cosine comparison.

The adapter loads local checkpoints only, resamples to 16 kHz, pads short final chunks, skips silence, batches on CPU and caches embeddings keyed by audio content, model hash and preprocessing parameters. Candidate matches above a configurable uncalibrated threshold are limited per target chunk and grouped by overlapping source/target windows and consistent offsets. High similarity is never a positive verified reuse claim.

Optional local waveform correlation refines only the two-second patch actually compared. It does not pretend that the whole coarse embedding region was aligned, nor handle pitch/time transformations. Coarse candidates remain coarse when direct waveform alignment fails. Chunk grouping is bounded by the ten-minute input cap. Refined/embedding regions are distinct from PF-NMF activation measurements; they are not silently interchangeable.

The authoritative checkpoint was downloaded after the Zenodo network requirement became available and verified against its published MD5 (`c50d08e54b37e49fbcf8904b1f0f5ca3`). Local SHA-256 is `a6026b65b6516569aa7a6c7f967e2ebe31dcb123af53560b122d87d72ddf4693`. CPU pretrained inference produced a 1×2048 embedding and a 0.99999988 self-match cosine on generated audio. This checks integration, not accuracy on real music. No fabricated embeddings are used in the app. Core functionality is independent of Torch/weights. Model-loading failures surface as unavailable capability.

## Review and operations

A reviewer supplies independent evidence for each rights path. Verified reuse requires explicit expert intervals. Coverage is recalculated from the union of corrected intervals. Approval requires named review, resolved findings and classification, and a narrative. Automated outputs are retained alongside a separate corrected envelope. Approving documentation is not legal clearance. JSON and escaped standalone HTML exports contain no recordings.

No case database, login, shared storage, background queue, external LLM or production deployment is included. Do not expose the app to untrusted networks with confidential recordings until access controls and retention are designed. Telemetry is disabled. Input paths and public documentation contain no client case narratives.


## Guarded DTW candidate refinement

SampleID remains the candidate-localization stage. A new optional
`alignment/dtw.py` refinement stage runs only after SampleID has supplied both
source and new-work timestamps. It computes a lightweight STFT-derived chroma
sequence, searches pitch shifts within a configurable semitone range, and uses
subsequence Dynamic Time Warping to tighten the new-work placement.

DTW is not allowed to turn harmonic resemblance into a detection. The refiner
abstains and preserves the coarse SampleID interval unless the refined placement
still overlaps the SampleID hint, exceeds a minimum duration, and falls inside a
configured derivative/source duration ratio. Defaults accept ratios from 0.5x to
1.5x; these are conservative engineering guardrails, not validated legal or
musicological thresholds.

The pipeline first attempts direct waveform correlation for near-identical audio.
Guarded DTW is a fallback for moderate pitch/time transformations. All outputs
remain status=`candidate`; DTW cost is not stored as probability or confidence,
and the original SampleID similarity is preserved only as provenance from the
recognition stage. Exact source-boundary refinement, chopped/reordered samples,
and calibrated real-recording accuracy remain future validation work.
