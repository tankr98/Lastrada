from lastrada.schemas.models import PathResult, Locate, Description, Feature
from lastrada.classification.placement import classify


def analyze(measurement, candidate_intervals=None, sampleid_ran=False):
    candidates = candidate_intervals or []
    # No candidate above a threshold is a model-specific negative, never a legal conclusion.
    status = "candidate" if candidates else "not_detected" if sampleid_ran else "not_verified"
    locate = Locate(
        detection_status=status,
        sample_detected=False if status == "not_detected" else None,
        measurement_intervals=measurement.intervals,
        sample_occurrences=candidates,
        total_covered_seconds=measurement.coverage_seconds,
        coverage_percentage=measurement.coverage_percentage,
    )
    result = PathResult(
        rights_type="master",
        locate=locate,
        describe=Description(
            elements=[
                Feature(
                    feature="spectral_activation_coverage",
                    value=measurement.coverage_percentage,
                    unit="percent",
                    source="pfnmf_activation",
                    status="estimated",
                )
            ],
            limitations=measurement.warnings
            + [
                "PF-NMF intervals are spectral measurements, not recording detections.",
                "Source intervals, instruments, lyrics, pitch and timing alterations are unknown.",
                "SampleID similarity is uncalibrated candidate evidence.",
            ],
        ),
    )
    result.classification = classify(measurement.coverage_percentage, measurement.intervals)
    return result
