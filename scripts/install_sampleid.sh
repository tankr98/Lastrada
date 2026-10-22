#!/usr/bin/env bash
# Optional CPU inference setup. No client data is transmitted.
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/shared/uv-cache}"
uv pip install --python .venv/bin/python 'torch==2.14.1+cpu' --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/bin/python 'hydra-core==1.3.7' 'tqdm==4.70.1'
model_root="${LASTRADA_SAMPLEID_SOURCE:-/workspace/shared/sampleid-upstream}"
model_revision='e212b0b9974d52d334cc793ef1b8cabaf251e5f8'
if [[ ! -e "$model_root" ]]; then
    git clone https://github.com/sony/sampleid.git "$model_root"
    git -C "$model_root" checkout "$model_revision"
fi
if [[ "$(git -C "$model_root" rev-parse HEAD)" != "$model_revision" ]]; then
    echo 'Existing SampleID source is not the pinned revision; preserve it and investigate.' >&2
    exit 1
fi
git -C "$model_root" diff --quiet
git -C "$model_root" diff --cached --quiet
uv pip install --python .venv/bin/python --no-deps -e "$model_root"
.venv/bin/python scripts/fetch_sampleid.py --workers 32
