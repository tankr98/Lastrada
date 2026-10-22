"""Dedicated local entrypoint for the Sony SampleID + guarded DTW workflow.

This branch intentionally excludes Demucs/stem-assisted processing. The main
Lastrada reviewer interface is executed unchanged so the result still flows into
Step 3 and the Nature of Use workflow.
"""

from pathlib import Path
import os
import runpy

# Defensive: ignore stem settings inherited from another PowerShell session.
os.environ.pop("LASTRADA_STEM_ENABLED", None)
os.environ.pop("LASTRADA_STEM_MODEL", None)
os.environ.pop("LASTRADA_STEM_DEVICE", None)
os.environ.pop("LASTRADA_STEM_MAX_CANDIDATES", None)
os.environ.pop("LASTRADA_STEM_PADDING_SECONDS", None)
os.environ.pop("LASTRADA_STEM_CROSS_OTHER", None)

APP = Path(__file__).with_name("app.py")
runpy.run_path(str(APP), run_name="__main__")
