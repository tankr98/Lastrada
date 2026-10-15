# Alignment test bench

The branch includes a focused Streamlit sandbox at `dtw_test_app.py`.

Run from the repository root:

```bash
streamlit run dtw_test_app.py
```

The tester has three modes:

1. **Full SampleID → DTW**: uses the existing v0 SampleID adapter, tries direct
   waveform refinement first, then guarded DTW, then falls back to the coarse
   Sony candidate. It can optionally run stem-assisted comparison on the
   strongest Sony candidates.
2. **Manual candidate → DTW**: lets you paste one source and derivative interval
   to test full-mix DTW without needing the Sony checkpoint.
3. **Stem-assisted candidate**: separates padded source/derivative candidate
   crops with Demucs, compares selected ordered stem pairs with guarded DTW,
   and plays the strongest estimated stem pair.

The full mode needs `LASTRADA_SAMPLEID_CHECKPOINT` or
`checkpoints/sampleid-best.ckpt`.

Stem mode is optional and requires the Demucs extra:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_stems.ps1
```

See [STEM_ASSISTED_TESTING.md](STEM_ASSISTED_TESTING.md) for setup,
interpretation and limitations.

This is an engineering validation surface, not a clearance determination.
