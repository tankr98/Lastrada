# Local Sony + DTW + stem-assisted workflow

Stem separation is an optional second-stage validation step in the normal seven-screen Lastrada website. It does not launch the old DTW Lab.

## Analysis order

1. Sony SampleID proposes paired original/new-track candidates.
2. Direct waveform alignment or guarded full-mix DTW refines each candidate.
3. When `LASTRADA_STEM_ENABLED=1`, Demucs separates only the strongest padded candidate region(s), not the full recordings.
4. Guarded DTW compares selected estimated stem pairs: matching labels plus guitar/piano ↔ `other` spillover checks.
5. A successful stem alignment may refine a still-coarse Sony interval. It does not replace an existing direct-waveform or full-mix DTW refinement.
6. Step 3 shows the final paired timings and provenance inside the normal listening-review table.

Demucs stems are model estimates with possible bleed and artifacts. A label such as `guitar → guitar` is supporting evidence, not a final musical-element conclusion.

## Windows PowerShell

From a checkout of `feat/stem-assisted-main-flow`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\install_sampleid.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install_stems.ps1
```

Place `sampleid-best.ckpt` at `checkpoints\sampleid-best.ckpt` or set its full path:

```powershell
$env:LASTRADA_SAMPLEID_CHECKPOINT = (Resolve-Path ".\checkpoints\sampleid-best.ckpt").Path
```

Enable stem assistance and keep the first test conservative:

```powershell
$env:LASTRADA_STEM_ENABLED = "1"
$env:LASTRADA_STEM_MODEL = "htdemucs_6s"
$env:LASTRADA_STEM_DEVICE = "cpu"
$env:LASTRADA_STEM_MAX_CANDIDATES = "1"
$env:LASTRADA_STEM_PADDING_SECONDS = "4.0"
$env:LASTRADA_STEM_CROSS_OTHER = "1"
```

Verify Sony, then launch the main website:

```powershell
.\.venv\Scripts\python.exe .\scripts\diagnose_sampleid.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The first `htdemucs_6s` analysis downloads Demucs model weights and can be slow on CPU. Results are cached under `cache\demucs` for repeat runs.

## Expected Step 3 result

When stem-assisted DTW refines a coarse Sony interval, its timing source appears as, for example:

```text
stem-assisted DTW · guitar → guitar
```

The technical-details expander also includes a `stems` method summary and `stem_separation` processing time. If Demucs is unavailable or no paired Sony candidate exists, the Sony/full-mix result remains unchanged and the reason is recorded in the methods/warnings output.
