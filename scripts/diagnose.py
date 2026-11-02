import importlib.util
import os
import platform
from pathlib import Path
import shutil
import sys


def main():
    print("Python:", platform.python_version())
    print("CPU count:", os.cpu_count())
    print(
        "FFmpeg:", "available" if shutil.which("ffmpeg") else "missing; WAV/FLAC remain supported"
    )
    missing = []
    for name in [
        "numpy",
        "scipy",
        "sklearn",
        "soundfile",
        "pandas",
        "openpyxl",
        "pydantic",
        "streamlit",
        "plotly",
    ]:
        installed = importlib.util.find_spec(name) is not None
        print(f"{name}:", "available" if installed else "missing")
        if not installed:
            missing.append(name)
    checkpoint = os.getenv("LASTRADA_SAMPLEID_CHECKPOINT") or "checkpoints/sampleid-best.ckpt"
    print(
        "SampleID checkpoint:",
        "present" if checkpoint and Path(checkpoint).is_file() else "not configured",
    )
    print(
        "SampleID package:",
        "installed" if importlib.util.find_spec("sampleid") else "optional, not installed",
    )
    if importlib.util.find_spec("torch"):
        import torch

        print("Torch:", torch.__version__, "CUDA available:", torch.cuda.is_available())
    else:
        print("Torch: optional, not installed")
    # Never print environment values or credentials.
    return 1 if missing or sys.version_info < (3, 12) else 0


if __name__ == "__main__":
    raise SystemExit(main())
