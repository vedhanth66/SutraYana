"""
SutraYana Verification & Batch Evaluation Runner (check.py)

Supports both single-plan verification and parallel batch evaluation across the ResPlan dataset.
All console output is automatically captured into the `results/` folder with descriptive timestamped filenames.

Usage examples:
  py check.py sample_plan.json               # Verifies a single plan and logs to results/
  py check.py                                # Runs 50 random plans batch evaluation
  py check.py --count 100 --workers 4        # Runs 100 plans across 4 worker processes
  py check.py --count 500 --resolution 0.08  # Runs 500 plans at 8cm grid resolution
"""

import os
import sys
import time
import argparse
from batch_eval_pipeline import TeeLogger, run_batch_evaluation
from phase4_routing import run_phase4


def run_single_plan_with_logging(plan_path, save_img="floor_plan_phase4.png", results_dir="results"):
    os.makedirs(results_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(plan_path))[0]
    log_name = f"check_{timestamp}_{base_name}.log"
    log_path = os.path.join(results_dir, log_name)

    tee = TeeLogger(log_path, sys.stdout)
    orig_stdout = sys.stdout
    sys.stdout = tee

    try:
        print("=" * 80)
        print(f"SUTRAYANA: SINGLE-PLAN VERIFICATION")
        print(f"Target Plan     : {plan_path}")
        print(f"Results Log File: {log_path}")
        print("=" * 80)
        output_data, total_J, hubs_routed = run_phase4(
            plan_path,
            show_plot=False,
            save_img=save_img,
            verbose=True
        )
        print("\n" + "=" * 80)
        print("VERIFICATION COMPLETED SUCCESSFULLY")
        print(f"Hubs Placed     : {len(output_data.get('hubs', []))}")
        print(f"Total Cost J    : {total_J:.2f}")
        print(f"Log written to  : {log_path}")
        if save_img:
            print(f"Rendered image  : {save_img}")
        print("=" * 80 + "\n")
    finally:
        sys.stdout = orig_stdout
        tee.close()


if __name__ == "__main__":
    # If the user passed a .json file directly, run single-plan check
    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        target_json = sys.argv[1]
        save_img_path = "floor_plan_phase4.png" if "--save" in sys.argv or "-s" in sys.argv else None
        run_single_plan_with_logging(target_json, save_img=save_img_path)
    else:
        parser = argparse.ArgumentParser(description="SutraYana Verification & Batch Evaluation")
        parser.add_argument("--count", type=int, default=50, help="Number of plans to evaluate (default: 50)")
        parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 8), help="Worker processes")
        parser.add_argument("--resolution", type=float, default=0.08, help="Grid resolution in metres (default: 0.08)")
        parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling (default: 42)")
        parser.add_argument("--results-dir", type=str, default="results", help="Directory where logs and results are stored")
        parser.add_argument("--log-name", type=str, default=None, help="Custom filename for the log output")
        parser.add_argument("--pkl", type=str, default=None, help="Path to ResPlan.pkl")
        args = parser.parse_args()

        run_batch_evaluation(
            pkl_path=args.pkl,
            num_plans=args.count,
            workers=args.workers,
            resolution=args.resolution,
            seed=args.seed,
            results_dir=args.results_dir,
            log_name=args.log_name
        )
