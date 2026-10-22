# Stem-assisted SampleID / DTW testing

This branch adds an optional Demucs layer to the existing alignment test bench.
It is designed for cases such as a reused guitar recording underneath different
vocals or drums.

## What it does

For one Sony or manually supplied candidate interval:

1. crop the source and derivative around the candidate, with padding;
2. run Demucs separately on both crops;
3. retain the full mix and estimated stems;
4. compare matching stem labels with guarded chroma/DTW;
5. also compare guitar/piano against `other`, because separation can leak those
   instruments into the generic accompaniment stem;
6. rank accepted stem-pair alignments by label agreement and DTW cost;
7. let the reviewer listen to the strongest estimated source and derivative stems.

The default six-source model produces estimated `vocals`, `drums`, `bass`,
`guitar`, `piano`, and `other` stems. These are not recovered studio multitracks.
Bleed, artifacts and incorrect stem assignment are expected.

## Windows setup

From the repository root on `feat/stem-assisted-comparison`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\install_stems.ps1
```

Then launch:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dtw_test_app.py
```

The first Demucs run downloads model weights. CPU separation may take several
minutes. If a compatible CUDA GPU and PyTorch build are available, select
`cuda` in the interface.

## Test without Sony

1. Upload both tracks.
2. Open **Stem-assisted candidate**.
3. Enter approximate source and derivative timestamps.
4. Keep `htdemucs_6s` to include guitar and piano.
5. Click **Separate and compare stems**.

The app displays all selected ordered stem pairs, whether their DTW alignment
passed the duration and overlap guardrails, the rough pitch shift, duration
ratio, and DTW cost. It also plays the strongest ordered pair.

## Test after Sony

1. Configure Sony's checkpoint in **Full SampleID → DTW**.
2. Enable **Run stem-assisted comparison on the strongest Sony candidates**.
3. Start with one candidate because Demucs is compute-intensive.
4. Run the pipeline.

Sony remains the candidate-localization stage. Stem separation and DTW organize
supporting evidence around those candidates; they do not verify sampling.

## Cache

Separated candidate crops are cached under `cache/demucs/`, keyed by crop audio,
timestamps and model name. The cache is ignored by Git. Repeating the same
candidate should avoid another Demucs run.

## Interpretation

A strong `guitar → guitar` result means the two *estimated guitar stems* aligned
under the configured DTW rules. It does not establish that:

- the separator recovered the exact studio guitar stem;
- the guitar is the only reused element;
- the alignment is legally or musicologically verified;
- lower DTW cost is a probability of sampling.

Use full-mix Sony evidence, timing consistency, stem agreement and human listening
together. Keep all automated outputs at `candidate` status until expert review.
