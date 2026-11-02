"""End-to-end local analysis plus independently generated known ranges."""

import json
from lastrada.audio.synthetic import demo_pair
from lastrada.pipeline import analyze_pair
from lastrada.schemas.models import Intake, Work


def main():
    original, new, ranges = demo_pair()
    intake = Intake(
        case_id="synthetic-smoke",
        original_work=Work(title="Source", artist="Generated"),
        new_work=Work(title="Mix", artist="Generated"),
        analysis_scope=["publishing", "master"],
    )
    result = analyze_pair(intake, original, new, synthetic=True)
    expected = sum(end - start for start, end in ranges) / new.duration * 100
    measured = result.master.locate.coverage_percentage
    assert abs(measured - expected) < 5
    assert result.master.locate.sample_detected is None
    assert result.publishing.locate.sample_occurrences == []
    print(
        json.dumps(
            {
                "synthetic": True,
                "known_coverage_percent": expected,
                "estimated_activation_percent": measured,
                "absolute_percentage_point_error": abs(measured - expected),
                "timings_seconds": result.timings_seconds,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
