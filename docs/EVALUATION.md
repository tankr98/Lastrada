# Evaluation protocol

Use only the reserved cases designated by `test pair`. Do not tune thresholds, fit hyperparameters or retrieve descriptions from this set. Generated predictions must come from leakage-free paired audio intake. Predictions, annotations and expert-corrected outputs remain distinct.

```bash
.venv/bin/python scripts/evaluate.py /approved/private/path/sample-uses.xlsx \
  --predictions outputs/predictions --rights master --output data/private/evaluation.json
```

Run separately for `publishing`. Input files must be exported analysis envelopes, one per case. The harness evaluates automated outputs, never substitutes expert corrections for predictions. It lists every reserved case, including absent predictions, unconfirmed labels, version warnings, out-of-bounds timestamps and abstentions.

Primary: overall and per-class agreement against explicitly Stephen-confirmed labels, a six-by-six confusion matrix, class-specific prediction rates and review-required cases. Agreement is conditional on valid predictions; abstentions are counted/listed separately so coverage of the evaluation set is visible. Unconfirmed labels never contribute to accuracy.

Secondary: union reference intervals before duration scoring. Report absolute seconds and percentage-point errors with count, mean, median, p90 and maximum. These errors assess the experimental measurement, not legal detection. Master coverage is not scored against publishing timings on interpolation controls. Track candidate/verified false positives and unassessed controls separately. Audio-version mismatches and out-of-bounds annotations block coverage scoring until explicitly validated.

Paragraphs require expert judgment of the factual element, placement, extent, reuse method and role. The harness does not use wording similarity as a proxy. No automated paragraph quality score or review-time reduction is claimed. Intake preparation, model inference, localization, classification, narrative and total times are recorded; the approximately 45-minute human baseline remains contextual, not a measured comparison.

Synthetic tests exercise interval union, known-copy coverage, waveform alignment, optional embedding grouping, rights isolation, leakage boundaries and review/export integrity. They do not establish accuracy on commercial recordings or publishing interpolation.
