"""Load the requested Demucs model before Streamlit starts.

This moves the first model download/load into the terminal, where progress and
errors are visible, instead of making the Streamlit analysis spinner appear to
hang without explanation.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="htdemucs_6s")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--segment", type=int, default=7)
    args = parser.parse_args()

    try:
        from demucs.api import Separator
    except Exception as exc:
        print(f"Demucs import failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Preparing Demucs model '{args.model}' on {args.device}. "
        "The first run may download model weights."
    )
    try:
        Separator(
            model=args.model,
            device=args.device,
            shifts=0,
            split=True,
            overlap=0.10,
            progress=False,
            jobs=0,
            segment=args.segment,
        )
    except Exception as exc:
        print(
            f"Demucs model preparation failed ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1

    print("Demucs model is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
