import argparse
import json
from pathlib import Path
from lastrada.ingestion.dataset import load_dataset
from lastrada.evaluation.metrics import evaluate
from lastrada.schemas.models import Analysis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spreadsheet")
    parser.add_argument("--predictions", default="outputs/predictions")
    parser.add_argument("--rights", choices=["publishing", "master"], default="master")
    parser.add_argument("--output", default="data/private/evaluation.json")
    args = parser.parse_args()
    target = Path(args.output)
    if not target.resolve().is_relative_to((Path.cwd() / "data/private").resolve()):
        parser.error("Confidential evaluation output must stay in ignored data/private/")
    predictions = {}
    for path in Path(args.predictions).glob("*.json"):
        analysis = Analysis.model_validate_json(path.read_text())
        if analysis.case_id in predictions:
            raise ValueError("Duplicate predictions for a case")
        predictions[analysis.case_id] = analysis.model_dump(mode="json")
    report = evaluate(load_dataset(args.spreadsheet), predictions, args.rights)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2))
    print(f"Local evaluation written to {target}; scored {report['placement_scored']} placements.")


if __name__ == "__main__":
    main()
