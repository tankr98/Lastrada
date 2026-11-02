"""Diagnose local Sony SampleID readiness on Windows, macOS, or Linux.

Run from the repository root:
    python scripts/diagnose_sampleid.py
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import traceback
import zipfile


def checkpoint_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.getenv("LASTRADA_SAMPLEID_CHECKPOINT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path("checkpoints/sampleid-best.ckpt"),
            Path.home() / ".lastrada_sampleid" / "sampleid-best.ckpt",
        ]
    )

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def main() -> int:
    print("Python:", sys.executable)
    print("Version:", sys.version.replace("\n", " "))
    print("Working directory:", Path.cwd())
    print("Home directory:", Path.home())
    print("LASTRADA_SAMPLEID_CHECKPOINT:", os.getenv("LASTRADA_SAMPLEID_CHECKPOINT"))
    print("torch installed:", bool(importlib.util.find_spec("torch")))
    print("sampleid installed:", bool(importlib.util.find_spec("sampleid")))
    print()

    try:
        import sampleid

        package_dir = Path(sampleid.__file__).resolve().parent
        print("sampleid package:", sampleid.__file__)
        print("checkpoint model source present:", (package_dir / "src").is_dir())
    except Exception:
        package_dir = None
        print("sampleid import failed:")
        traceback.print_exc()

    try:
        from sampleid import SampleID  # noqa: F401
        import src.networks.resnet_ibn  # noqa: F401

        print("Sony Hydra model target import: OK")
    except Exception:
        print("Sony Hydra model target import: FAIL")
        traceback.print_exc()
        print(
            "Install Sony's repository in editable mode so sampleid/src is present. "
            "On Windows run scripts/install_sampleid.ps1."
        )
        return 3

    valid: Path | None = None
    for path in checkpoint_candidates():
        exists = path.is_file()
        size_mb = path.stat().st_size / 1024 / 1024 if exists else 0.0
        archive = zipfile.is_zipfile(path) if exists else False
        print(f"Checkpoint candidate: {path}")
        print(f"  exists: {exists}")
        print(f"  size MB: {size_mb:.1f}")
        print(f"  valid zip checkpoint: {archive}")
        if exists and size_mb >= 100 and archive and valid is None:
            valid = path

    if valid is None:
        print("\nRESULT: FAIL - no valid sampleid-best.ckpt was found.")
        return 2

    print(f"\nTrying to load checkpoint: {valid}")
    try:
        import torch
        from sampleid import SampleID

        model = SampleID.load_checkpoint(str(valid), device=torch.device("cpu"))
        model.eval()
    except Exception:
        print("\nRESULT: FAIL - checkpoint/model load raised this exception:")
        traceback.print_exc()
        return 4

    print("\nRESULT: PASS - Sony SampleID checkpoint loaded successfully on CPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
