from lastrada.evaluation.metrics import evaluate


def prediction():
    return {
        "input": {"analysis_scope": ["master"]},
        "durations": {"new": 10.0},
        "master": {
            "classification": {"placement": "chorus_only", "review_required": True},
            "locate": {"total_covered_seconds": 3.0, "detection_status": "not_verified"},
        },
    }


def test_unconfirmed_not_scored_but_coverage_union_scored(frame):
    result = evaluate(frame, {"SYN-0": prediction()})
    assert result["overall_agreement"] is None
    assert result["placement_scored"] == 0
    assert result["coverage_seconds_error"]["mean"] == 0


def test_confirmed_per_class_confusion(frame):
    frame.loc[0, "confirmed by Stephen"] = "yes"
    result = evaluate(frame, {"SYN-0": prediction()})
    assert result["overall_agreement"] == 1.0
    assert result["per_class"]["chorus_only"]["scored"] == 1
    assert result["per_class"]["verses"]["agreement"] is None


def test_missing_prediction_explicit(frame):
    result = evaluate(frame, {})
    assert result["reserved_case_count"] == 1
    assert any("No prediction" in reason for reason in result["cases"][0]["reasons"])


def test_interpolation_control_never_scores_publishing_times_as_master(frame):
    frame.loc[0, "test note"] = "interpolation"
    result = evaluate(frame, {"SYN-0": prediction()})
    assert result["coverage_seconds_error"]["count"] == 0
    assert result["cases"][0]["control_assessed"] is False


def test_version_warning_blocks_coverage(frame):
    frame.loc[0, "audio notes"] = "Different mix"
    result = evaluate(frame, {"SYN-0": prediction()})
    assert result["coverage_seconds_error"]["count"] == 0


def test_out_of_bounds_timestamps_not_scored(frame):
    frame.loc[0, "timestamps"] = "0:08-0:20"
    result = evaluate(frame, {"SYN-0": prediction()})
    assert result["coverage_seconds_error"]["count"] == 0
