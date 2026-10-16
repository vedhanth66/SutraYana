import os
import sys
import time
import random
import pickle
import argparse
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed

# Set matplotlib cache directory before importing matplotlib
os.environ.setdefault('MPLCONFIGDIR', tempfile.gettempdir())

from export_resplan_to_json import extract_rooms_and_doors
from phase4_routing import run_phase4


class TeeLogger:
    """Simultaneously writes all terminal output to console and a log file."""
    def __init__(self, filepath, stream=sys.stdout):
        self.terminal = stream
        self.log_file = open(filepath, "w", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.terminal.flush()
        self.log_file.write(message)
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        if not self.log_file.closed:
            self.log_file.close()


def process_single_plan_task(args):
    """
    Worker task to run the complete Phase 1 -> Phase 2 -> Phase 3 -> Phase 4 pipeline
    on a single ResPlan plan dictionary in-memory.
    """
    plan_raw, plan_idx, resolution = args
    t0 = time.time()
    try:
        formatted = extract_rooms_and_doors(plan_raw, plan_id=f"plan_{plan_idx:05d}")
        eligible_rooms = [
            r for r in formatted.get("rooms", [])
            if r.get("type", "").lower() in {"living", "bedroom", "kitchen", "storage"}
        ]
        if not eligible_rooms:
            return {"plan_idx": plan_idx, "skipped": True, "reason": "No eligible rooms"}

        # Run complete Phase 1 - 4 pipeline in-memory with automatic 4cm fallback
        try:
            output_data, total_J, hubs_routed = run_phase4(
                formatted,
                show_plot=False,
                save_img=None,
                resolution=resolution,
                verbose=False
            )
        except Exception as e_run:
            # Gracefully retry at high-precision 4cm resolution if 8cm encountered doorway bottlenecks
            if resolution > 0.04:
                formatted_retry = extract_rooms_and_doors(plan_raw, plan_id=f"plan_{plan_idx:05d}")
                output_data, total_J, hubs_routed = run_phase4(
                    formatted_retry,
                    show_plot=False,
                    save_img=None,
                    resolution=0.04,
                    verbose=False
                )
            else:
                raise e_run
        dt = time.time() - t0
        rep = output_data["reported_metrics"]

        # Calculate assigned area gap
        hub_areas = []
        for h in output_data["hubs"]:
            room_ids = h["assigned_rooms"]
            h_area = sum(float(r["area"]) for r in formatted["rooms"] if r["id"] in room_ids)
            hub_areas.append(h_area)
        area_gap = (max(hub_areas) - min(hub_areas)) if len(hub_areas) >= 2 else 0.0

        return {
            "plan_idx": plan_idx,
            "valid": True,
            "skipped": False,
            "eligible_rooms": len(eligible_rooms),
            "hub_count": rep["hub_count"],
            "total_L": rep["total_length_m"],
            "total_B": rep["total_bends"],
            "total_O": rep["total_overlap_m"],
            "total_X": rep["total_crossings"],
            "total_J": rep["total_cost_J"],
            "area_gap_m2": round(area_gap, 2),
            "time_sec": dt
        }
    except Exception as e:
        dt = time.time() - t0
        return {
            "plan_idx": plan_idx,
            "valid": False,
            "skipped": False,
            "error": str(e),
            "time_sec": dt
        }


def find_resplan_pickle(preferred_path=None):
    candidates = [
        preferred_path,
        "ResPlan/ResPlan.pkl",
        "ResPlan/ResPlan/ResPlan.pkl",
        "../SutraYana_temp/ResPlan/ResPlan.pkl",
        "../ResPlan.pkl"
    ]
    for cp in candidates:
        if cp and os.path.exists(cp):
            return cp
    return None


def run_batch_evaluation(pkl_path=None, num_plans=50, workers=4, resolution=0.08, seed=42, results_dir="results", log_name=None, plan_indices=None):
    os.makedirs(results_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    res_cm = int(round(resolution * 100))
    if not log_name:
        prefix = "benchmark" if plan_indices else "batch_eval"
        plan_count_str = f"{len(plan_indices)}plans" if plan_indices else f"{num_plans}plans"
        log_name = f"{prefix}_{timestamp}_{plan_count_str}_res{res_cm}cm.log"
    json_name = os.path.splitext(log_name)[0] + ".json"

    log_path = os.path.join(results_dir, log_name)
    json_path = os.path.join(results_dir, json_name)

    tee = TeeLogger(log_path, sys.stdout)
    orig_stdout = sys.stdout
    sys.stdout = tee

    try:
        print("=" * 80)
        print("SUTRAYANA: FULL-PIPELINE PARALLEL BATCH EVALUATION (PHASE 1 -> 4)")
        if plan_indices:
            print(f"Target Benchmark Indices: {plan_indices}")
        else:
            print(f"Target Plans   : {num_plans}")
        print(f"Parallel Workers: {workers}")
        print(f"Grid Resolution : {resolution*100:.0f}cm")
        print(f"Results Log File: {log_path}")
        print(f"Results JSON File: {json_path}")
        print("=" * 80)

        pkl_file = find_resplan_pickle(pkl_path)
        if not pkl_file:
            print(f"ERROR: Could not find ResPlan.pkl! Checked common paths.")
            sys.exit(1)

        print(f"Loading dataset from: {pkl_file} ...")
        with open(pkl_file, "rb") as f:
            data = pickle.load(f)

        total_available = len(data) if isinstance(data, list) else len(data.keys())
        print(f"Successfully loaded dataset with {total_available} total plans.")

        if plan_indices:
            sampled_indices = [int(p) for p in plan_indices if int(p) < total_available]
            num_plans = len(sampled_indices)
        else:
            random.seed(seed)
            if num_plans >= total_available:
                sampled_indices = list(range(total_available))
                num_plans = len(sampled_indices)
            else:
                sampled_indices = random.sample(range(total_available), num_plans)

        tasks = []
        for p_idx in sampled_indices:
            raw_plan = data[p_idx] if isinstance(data, list) else data[list(data.keys())[p_idx]]
            tasks.append((raw_plan, p_idx, resolution))

        print(f"\nStarting parallel execution across {workers} worker processes...\n")
        results = []
        start_wall = time.time()

        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                future_to_idx = {executor.submit(process_single_plan_task, t): t[1] for t in tasks}
                for i, future in enumerate(as_completed(future_to_idx), start=1):
                    res = future.result()
                    results.append(res)
                    p_idx = res["plan_idx"]
                    if res.get("skipped"):
                        print(f"[{i:02d}/{num_plans}] Plan #{p_idx:05d}: SKIPPED ({res.get('reason')})")
                    elif res.get("valid"):
                        print(
                            f"[{i:02d}/{num_plans}] Plan #{p_idx:05d}: PASSED | "
                            f"Hubs: {res['hub_count']} | J={res['total_J']:.2f} "
                            f"(L={res['total_L']:.1f}m, B={res['total_B']}, O={res['total_O']:.1f}m, X={res['total_X']}) | "
                            f"Time: {res['time_sec']*1000:.0f}ms"
                        )
                    else:
                        print(f"[{i:02d}/{num_plans}] Plan #{p_idx:05d}: FAILED -> {res.get('error')}")
        else:
            for i, t in enumerate(tasks, start=1):
                res = process_single_plan_task(t)
                results.append(res)
                p_idx = res["plan_idx"]
                if res.get("skipped"):
                    print(f"[{i:02d}/{num_plans}] Plan #{p_idx:05d}: SKIPPED ({res.get('reason')})")
                elif res.get("valid"):
                    print(
                        f"[{i:02d}/{num_plans}] Plan #{p_idx:05d}: PASSED | "
                        f"Hubs: {res['hub_count']} | J={res['total_J']:.2f} "
                        f"(L={res['total_L']:.1f}m, B={res['total_B']}, O={res['total_O']:.1f}m, X={res['total_X']}) | "
                        f"Time: {res['time_sec']*1000:.0f}ms"
                    )
                else:
                    print(f"[{i:02d}/{num_plans}] Plan #{p_idx:05d}: FAILED -> {res.get('error')}")

        total_wall_time = time.time() - start_wall
        successful = [r for r in results if r.get("valid")]
        pass_rate = (len(successful) / len(results)) * 100 if results else 0.0
        throughput = len(results) / total_wall_time if total_wall_time > 0 else 0.0

        avg_cpu_time = (sum(r["time_sec"] for r in successful) / len(successful)) * 1000.0 if successful else 0.0
        avg_hubs = sum(r["hub_count"] for r in successful) / len(successful) if successful else 0.0
        avg_L = sum(r["total_L"] for r in successful) / len(successful) if successful else 0.0
        avg_B = sum(r["total_B"] for r in successful) / len(successful) if successful else 0.0
        avg_O = sum(r["total_O"] for r in successful) / len(successful) if successful else 0.0
        avg_X = sum(r["total_X"] for r in successful) / len(successful) if successful else 0.0
        avg_J = sum(r["total_J"] for r in successful) / len(successful) if successful else 0.0

        print("\n" + "=" * 80)
        print("BATCH EVALUATION SUMMARY (Phase 1 -> Phase 2 -> Phase 3 -> Phase 4)")
        print("=" * 80)
        print(f"Total Plans Evaluated : {len(results)}")
        print(f"Passed All Validations: {len(successful)} / {len(results)} ({pass_rate:.1f}%)")
        print(f"Total Wall-Clock Time : {total_wall_time:.2f} seconds")
        print(f"System Throughput     : {throughput:.2f} plans/second")
        if successful:
            print(f"Average Plan Runtime  : {avg_cpu_time:.1f} ms/plan")
            print("-" * 80)
            print("Average Metrics Across Valid Plans:")
            print(f"  - Hub Count (H)    : {avg_hubs:.2f}")
            print(f"  - Cable Length (L) : {avg_L:.2f} m")
            print(f"  - Total Bends (B)  : {avg_B:.1f}")
            print(f"  - Total Overlap (O): {avg_O:.2f} m")
            print(f"  - Crossings (X)    : {avg_X:.2f}")
            print(f"  - Objective Cost J : {avg_J:.2f}")
        print("=" * 80)
        print(f"COMPLETE LOG SAVED TO   : {log_path}")
        print(f"STRUCTURED JSON SAVED TO: {json_path}")
        print("=" * 80 + "\n")

        # Save structured JSON
        json_payload = {
            "timestamp": timestamp,
            "config": {
                "num_plans": num_plans,
                "workers": workers,
                "resolution_m": resolution,
                "seed": seed,
                "pkl_file": pkl_file
            },
            "summary": {
                "total_evaluated": len(results),
                "passed": len(successful),
                "pass_rate_pct": round(pass_rate, 2),
                "wall_time_sec": round(total_wall_time, 2),
                "throughput_plans_per_sec": round(throughput, 2),
                "avg_runtime_ms": round(avg_cpu_time, 2) if successful else None,
                "avg_hub_count": round(avg_hubs, 2) if successful else None,
                "avg_length_m": round(avg_L, 2) if successful else None,
                "avg_bends": round(avg_B, 2) if successful else None,
                "avg_overlap_m": round(avg_O, 2) if successful else None,
                "avg_crossings": round(avg_X, 2) if successful else None,
                "avg_cost_J": round(avg_J, 2) if successful else None
            },
            "detailed_results": results
        }
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(json_payload, jf, indent=2)

    finally:
        sys.stdout = orig_stdout
        tee.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parallel Batch Evaluation for SutraYana (Phase 1-4)")
    parser.add_argument("--pkl", type=str, default=None, help="Path to ResPlan.pkl")
    parser.add_argument("--count", type=int, default=25, help="Number of plans to evaluate")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 8), help="Number of parallel worker processes")
    parser.add_argument("--resolution", type=float, default=0.08, help="Grid resolution in metres (e.g. 0.05, 0.08, 0.10)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument("--results-dir", type=str, default="results", help="Directory where log and json results will be saved")
    parser.add_argument("--plans", nargs="+", type=int, default=None, help="Specific plan indices to evaluate (e.g. 1 5 16 80 192)")
    args = parser.parse_args()

    run_batch_evaluation(
        pkl_path=args.pkl,
        num_plans=args.count,
        workers=args.workers,
        resolution=args.resolution,
        seed=args.seed,
        results_dir=args.results_dir,
        log_name=args.log_name,
        plan_indices=args.plans
    )
