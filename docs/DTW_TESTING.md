# DTW test bench

The branch includes a focused Streamlit sandbox at `dtw_test_app.py`.

Run from the repository root:

```bash
streamlit run dtw_test_app.py
```

The tester has two modes:

1. **Full SampleID → DTW**: uses the existing v0 SampleID adapter, tries direct waveform
   refinement first, then guarded DTW, then falls back to the coarse Sony candidate.
2. **Manual candidate → DTW**: lets you paste one source and derivative interval to test
   DTW without needing the Sony checkpoint.

The full mode needs `LASTRADA_SAMPLEID_CHECKPOINT` or
`checkpoints/sampleid-best.ckpt`.

This is an engineering validation surface, not a clearance determination.
