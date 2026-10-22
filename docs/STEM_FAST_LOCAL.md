# Fast local Sony + DTW + Demucs website

This branch keeps stem separation inside the normal Lastrada seven-step website while avoiding the long-running exhaustive profile.

## Why the exhaustive profile appeared stuck

The experimental stem branch could run Demucs across as many as 50 Sony candidates. Each candidate requires separation of a source crop and a new-song crop, followed by several stem-pair DTW comparisons. On CPU, that can take a very long time and the Streamlit spinner does not expose the underlying Demucs progress.

## Fast profile

- Sony SampleID still ranks candidate regions.
- Direct waveform matching and guarded DTW still run.
- Demucs uses `htdemucs_6s` so guitar and piano remain available.
- Only the top three Sony candidates are separated by default.
- The first Demucs model download/load happens in PowerShell before Streamlit opens.
- Candidate-region stems remain cached under `cache/demucs`.

## Windows PowerShell

```powershell
cd $HOME

git clone `
  --branch local/stem-fast `
  --single-branch `
  https://github.com/tankr98/Lastrada.git `
  Lastrada-stem-fast

cd "$HOME\Lastrada-stem-fast"

powershell -ExecutionPolicy Bypass `
  -File .\run_stem_fast_local.ps1 `
  -Install
```

The default checkpoint path is:

```text
C:\Users\<you>\.lastrada_sampleid\sampleid-best.ckpt
```

Use another checkpoint path with:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\run_stem_fast_local.ps1 `
  -Install `
  -Checkpoint "C:\full\path\sampleid-best.ckpt"
```

The site opens at `http://localhost:8503`.

## Candidate count

The default is three Sony candidates. For a faster diagnostic run:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\run_stem_fast_local.ps1 `
  -Candidates 1
```

The fast launcher accepts 1 through 5 candidates. Increasing this value increases CPU time substantially.

## Later launches

```powershell
cd "$HOME\Lastrada-stem-fast"

powershell -ExecutionPolicy Bypass `
  -File .\run_stem_fast_local.ps1
```

Use `-SkipModelWarmup` only after the Demucs model has already been downloaded and loaded successfully on the machine.
