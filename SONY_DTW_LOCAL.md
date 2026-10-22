# Sony + DTW local website

This branch is a frozen, local-testing version of the main Lastrada workflow with:

- Sony SampleID candidate matching
- direct waveform refinement
- guarded chroma DTW refinement
- the normal seven-step review and Nature of Use flow

It does **not** run Demucs or any stem-assisted comparison. PF-NMF remains only as the existing lightweight fallback/context layer used by the main interface.

## Fresh Windows setup

```powershell
cd $HOME

git clone `
  --branch local/sony-dtw-only `
  --single-branch `
  https://github.com/tankr98/Lastrada.git `
  Lastrada-sony-dtw-fast

cd "$HOME\Lastrada-sony-dtw-fast"

powershell -ExecutionPolicy Bypass `
  -File .\run_sony_dtw_local.ps1 `
  -Install
```

The default checkpoint location is:

```text
C:\Users\<you>\.lastrada_sampleid\sampleid-best.ckpt
```

If the checkpoint is elsewhere:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\run_sony_dtw_local.ps1 `
  -Install `
  -Checkpoint "C:\full\path\sampleid-best.ckpt"
```

Open:

```text
http://localhost:8502
```

## Later runs

```powershell
cd "$HOME\Lastrada-sony-dtw-fast"

powershell -ExecutionPolicy Bypass `
  -File .\run_sony_dtw_local.ps1
```

## Test flow

1. Click **New Sample**.
2. Upload the original and derivative tracks.
3. Select **Sampled the recording** or **Both / check both** so the recording analysis runs.
4. Leave **Use Sony SampleID + guarded DTW timing analysis** enabled.
5. Click **Find suggested moments**.
6. In Step 3, review paired original/new-track timestamps and their method provenance.

The local site uses port 8502 so it can run alongside another Streamlit app on port 8501.
