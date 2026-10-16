"""Inspect dataset index 713 using the validated submission path."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_resplan_to_json import export_single_plan
from phase4_routing import run_phase4

if __name__ == "__main__":
    export_single_plan("ResPlan/ResPlan/ResPlan.pkl", "results/plan_713.json", 713)
    run_phase4("results/plan_713.json", save_img="results/plan_713.png", output_json_path="results/solution_713.json")
