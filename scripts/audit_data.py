"""Usage: python scripts/audit_data.py FILE --output data/private/audit.json"""

import argparse
import json
from pathlib import Path
from lastrada.ingestion.dataset import load_dataset, audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spreadsheet")
    parser.add_argument("--audio-root")
    parser.add_argument("--output", default="data/private/audit.json")
    args = parser.parse_args()
    output = Path(args.output)
    if not output.resolve().is_relative_to((Path.cwd() / "data/private").resolve()):
        parser.error("Confidential audit outputs must be under ignored data/private/")
    report = audit(load_dataset(args.spreadsheet), args.audio_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    print(f"Audit saved locally to {output}; do not commit it.")


if __name__ == "__main__":
    main()
