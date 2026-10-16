"""Recheck the historical routing regressions with the corrected full solver."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch_eval_pipeline import run_batch_evaluation

if __name__ == "__main__":
    run_batch_evaluation(plan_indices=[713,3963,1703,192], workers=2, log_name="routing_regressions.log")
