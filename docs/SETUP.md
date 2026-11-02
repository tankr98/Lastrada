# Setup and operation

Use Python 3.12+, the existing isolated checkout and the scripts in README. Do not create a worktree for ordinary cloud tasks. Core dependencies and developer checks are pinned in `requirements.lock`; use `bash scripts/install.sh` to refresh them. This sync intentionally retains only core/developer dependencies: rerun optional installation afterward if desired.

Launch from the checkout:

```bash
.venv/bin/python -m streamlit run app.py --server.address 0.0.0.0
```

The four views provide intake/playback, separate rights timelines, reviewed classification/draft and exports. Try the clearly labeled synthetic demo first. Run `scripts/diagnose.py`, `pytest -q` and `scripts/synthetic_smoke.py` with `.venv/bin/python` for readiness. Live processes do not survive environment publication; start Streamlit again in a future task.

## Optional SampleID on CPU

The core app works without this extra. Obtain weights only from the authoritative Sony-linked Zenodo record, respecting TLS and the checksum published by the provider. No client audio needs to leave the local process.

```bash
bash scripts/install_sampleid.sh
.venv/bin/python scripts/check_sampleid.py
```

The optional installer uses CPU Torch, pins the inspected Sony source revision in an editable clone outside this checkout, and downloads the authoritative checkpoint with TLS enabled. It verifies the published MD5 before installation and re-verifies existing weights on repeat runs. Unexpected local source revisions/changes or invalid existing checkpoints stop setup rather than overwrite local work. The optional helper can fetch validated byte ranges in parallel to avoid a slow single stream.

The app finds `checkpoints/sampleid-best.ckpt` automatically; use `LASTRADA_SAMPLEID_CHECKPOINT` to override it and `LASTRADA_CACHE_DIR` to choose a private writable cache. Select **Include optional SampleID candidate matching** in Intake to run it. `.env.example` documents names; the app reads exported process variables and does not automatically load `.env`. No weights are downloaded by the adapter itself. It selects CPU and configurable chunk/batch sizes from `configs/default.json`. Weights and embeddings stay ignored.

The current environment has a checksum-verified checkpoint and successfully ran actual pretrained CPU inference on generated audio. Initial Zenodo access was blocked; adding the required domain and retrying restored access. These checks do not establish accuracy on historical songs. The standard pytest suite needs no weights or Torch; `scripts/check_sampleid.py` is an explicit optional integration check.

## Local data and repeatability

Keep source documents/audio outside the public checkout or under ignored private directories. Audit and evaluate using explicit paths. Exports are local downloads; review state is session-only. No external enrichment API or credentials are necessary.

`requirements.lock` captures the tested Linux/Python 3.12 dependency versions. Refresh it deliberately using `uv pip compile pyproject.toml --extra dev -o requirements.lock`, then rerun checks. Refreshing setup must not copy client data into tracked directories or overwrite user configuration.
