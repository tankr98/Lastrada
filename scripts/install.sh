#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/shared/uv-cache}"
uv venv --allow-existing .venv
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
.venv/bin/python scripts/diagnose.py
