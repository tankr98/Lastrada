"""Reserved-set scoring with explicit missing, unconfirmed and version-mismatch cases."""

import numpy as np
from lastrada.alignment.intervals import merge_ranges
from lastrada.ingestion.dataset import confirmed_label, parse_timestamps
from lastrada.schemas.models import PLACEMENT_CLASSES


def distribution(values):
    if not values:
        return {"count": 0, "mean": None, "median": None, "p90": None, "maximum": None}
    return {
        "count": len(values),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "maximum": float(max(values)),
    }


def evaluate(frame, predictions, rights="master", validated_version_ids=()):
    if rights not in ("publishing", "master"):
        raise ValueError("Unknown rights path")
    matrix = {c: {p: 0 for p in PLACEMENT_CLASSES} for c in PLACEMENT_CLASSES}
    cases, seconds_errors, percentage_errors = [], [], []
    class_correct = class_total = 0
    for row in frame.to_dict("records"):
        if not row["test pair"]:
            continue
        identifier = row["example id"]
        record = {
            "case_id": identifier,
            "reasons": [],
            "placement_scored": False,
            "coverage_scored": False,
            "review_required": None,
        }
        prediction = predictions.get(identifier)
        label = confirmed_label(row)
        if not label:
            record["reasons"].append("Placement label is not Stephen-confirmed")
        if prediction is None:
            record["reasons"].append("No prediction; paired audio may be missing")
            cases.append(record)
            continue
        if prediction.get("synthetic"):
            record["reasons"].append("Synthetic predictions cannot score historical cases")
            cases.append(record)
            continue
        if rights not in prediction.get("input", {}).get("analysis_scope", []):
            record["reasons"].append("Rights path was not requested")
            cases.append(record)
            continue
        path = prediction.get(rights, {})
        classification = path.get("classification", {})
        predicted = classification.get("placement")
        record["review_required"] = classification.get("review_required", True)
        if label and predicted in PLACEMENT_CLASSES:
            matrix[label][predicted] += 1
            class_total += 1
            class_correct += int(label == predicted)
            record["placement_scored"] = True
            record["placement_correct"] = label == predicted
            if label != predicted:
                record["reasons"].append(classification.get("reason", "Incorrect placement"))
        elif not predicted:
            record["reasons"].append("Model abstained from placement")
        ranges, issues = parse_timestamps(row["timestamps"])
        record["reasons"].extend(issues)
        duration = prediction.get("durations", {}).get("new")
        predicted_seconds = path.get("locate", {}).get("total_covered_seconds")
        # Publishing annotation timings are not master positives for interpolation controls.
        control = bool(row["test note"])
        if control and rights == "master":
            status = path.get("locate", {}).get("detection_status", "unknown")
            record["interpolation_control_status"] = status
            record["control_false_positive"] = status in ("candidate", "verified")
            record["control_assessed"] = status in ("candidate", "verified", "not_detected")
            record["reasons"].append(
                "Interpolation publishing annotations are not master coverage truth"
            )
        elif row["audio notes"] and identifier not in validated_version_ids:
            record["reasons"].append(
                "Audio-version warning needs validation before coverage scoring"
            )
        elif ranges and not issues and duration and predicted_seconds is not None:
            try:
                merged = merge_ranges(ranges, duration)
                target_seconds = sum(end - start for start, end in merged)
                error = abs(predicted_seconds - target_seconds)
                seconds_errors.append(error)
                percentage_errors.append(100 * error / duration)
                record.update(
                    coverage_scored=True,
                    absolute_seconds_error=error,
                    percentage_point_error=100 * error / duration,
                    reference_seconds=target_seconds,
                    measurement_source="experimental_pfnmf" if rights == "master" else "publishing",
                )
            except ValueError:
                record["reasons"].append("Reference timestamps exceed recording duration")
        else:
            record["reasons"].append("Coverage truth or usable measurement is missing")
        cases.append(record)
    per_class = {}
    for label, values in matrix.items():
        count = sum(values.values())
        eligible = sum(
            confirmed_label(r) == label for r in frame.to_dict("records") if r["test pair"]
        )
        per_class[label] = {
            "scored": count,
            "eligible": eligible,
            "agreement": values[label] / count if count else None,
            "prediction_rate": count / eligible if eligible else None,
        }
    return {
        "rights_path": rights,
        "reserved_case_count": len(cases),
        "placement_scored": class_total,
        "overall_agreement": class_correct / class_total if class_total else None,
        "confusion_matrix": matrix,
        "per_class": per_class,
        "coverage_seconds_error": distribution(seconds_errors),
        "coverage_percentage_point_error": distribution(percentage_errors),
        "review_required_cases": sum(c["review_required"] is True for c in cases),
        "cases": cases,
        "paragraph_evaluation": "Expert rubric required: element, placement, extent, reuse method, role; "
        "not scored through text similarity.",
    }
