"""Export trusted ResPlan pickle records as demo JSON with fixed generated nodes."""
import argparse
import json
import pickle
from pathlib import Path
from sutrayana.exporter import extract_rooms_and_doors


def export_single_plan(pkl_path, output_json="resplan_sample.json", plan_index=0):
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)
    raw = data[list(data)[plan_index]] if isinstance(data, dict) else data[plan_index]
    result = extract_rooms_and_doors(raw, f"plan_{plan_index}")
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(output_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Exported demo plan {plan_index} to {output_json}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pkl", nargs="?", default="ResPlan/ResPlan/ResPlan.pkl")
    parser.add_argument("output", nargs="?", default="resplan_sample.json")
    parser.add_argument("index", nargs="?", type=int, default=0)
    args = parser.parse_args()
    export_single_plan(args.pkl, args.output, args.index)
