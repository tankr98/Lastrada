# Reproducible private data audit

Run from the checkout with the project environment:

```bash
.venv/bin/python scripts/audit_data.py /approved/private/path/sample-uses.xlsx \
  --audio-root /approved/private/path/audio \
  --output data/private/audit.json
```

Omit `--audio-root` when audio is unavailable; the result records that local presence was not checked. The script writes under ignored `data/private/` only. Do not publish the resulting audit, case identifiers, row notes or the source spreadsheet.

The audit validates the complete expected schema and unique IDs, profiles missing fields, identifies duplicate normalized song pairs, reports labels/confirmations, preserves reserved-case and audio-version notes, and reports incomplete/malformed timestamp ranges. Referenced filenames are counted separately from locally verified pairs. Path traversal outside the audio root is rejected.

The supplied workbook was ingested in the build environment. Case-level findings and aggregate results are deliberately kept in local `data/private/audit.json`, rather than public repository documentation. Actual historical audio was not supplied, so filename references cannot establish runnable real cases. Expert-confirmed placement labels and matching recording versions are prerequisites for meaningful scoring.
