import os
import sys
import time
import random
import pickle
import argparse
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed

# Set matplotlib cache directory before importing matplotlib
os.environ.setdefault('MPLCONFIGDIR', tempfile.gettempdir())

from export_resplan_to_json import extract_rooms_and_doors
from phase4_routing import run_phase4


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

        # Run complete Phase 1 - 4 pipeline in-memory
        output_data, total_J, hubs_routed = run_phase4(
            formatted,
            show_plot=False,
            save_img=None,
            resolution=resolution,
            verbose=False
        )
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


def run_batch_evaluation(pkl_path=None, num_plans=50, workers=4, resolution=0.08, seed=42):
    print("=" * 80)
    print("SUTRAYANA: FULL-PIPELINE PARALLEL BATCH EVALUATION (PHASE 1 -> 4)")
    print(f"Target Plans: {num_plans} | Parallel Workers: {workers} | Grid Resolution: {resolution*100:.0f}cm")
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

    random.seed(seed)
    sampled_indices = random.sample(range(min(2000, total_available)), num_plans)

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

    print("\n" + "=" * 80)
    print("BATCH EVALUATION SUMMARY (Phase 1 -> Phase 2 -> Phase 3 -> Phase 4)")
    print("=" * 80)
    print(f"Total Plans Evaluated : {len(results)}")
    print(f"Passed All Validations: {len(successful)} / {len(results)} ({pass_rate:.1f}%)")
    print(f"Total Wall-Clock Time : {total_wall_time:.2f} seconds")
    print(f"System Throughput     : {throughput:.2f} plans/second")
    if successful:
        avg_cpu_time = (sum(r["time_sec"] for r in successful) / len(successful)) * 1000.0
        avg_hubs = sum(r["hub_count"] for r in successful) / len(successful)
        avg_L = sum(r["total_L"] for r in successful) / len(successful)
        avg_B = sum(r["total_B"] for r in successful) / len(successful)
        avg_O = sum(r["total_O"] for r in successful) / len(successful)
        avg_X = sum(r["total_X"] for r in successful) / len(successful)
        avg_J = sum(r["total_J"] for r in successful) / len(successful)
        print(f"Average Plan Runtime  : {avg_cpu_time:.1f} ms/plan")
        print("-" * 80)
        print("Average Metrics Across Valid Plans:")
        print(f"  - Hub Count (H)    : {avg_hubs:.2f}")
        print(f"  - Cable Length (L) : {avg_L:.2f} m")
        print(f"  - Total Bends (B)  : {avg_B:.1f}")
        print(f"  - Total Overlap (O): {avg_O:.2f} m")
        print(f"  - Crossings (X)    : {avg_X:.2f}")
        print(f"  - Objective Cost J : {avg_J:.2f}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parallel Batch Evaluation for SutraYana (Phase 1-4)")
    parser.add_argument("--pkl", type=str, default=None, help="Path to ResPlan.pkl")
    parser.add_argument("--count", type=int, default=25, help="Number of plans to evaluate")
    parser.add_argument("--workers", type=int, default=min(os.cpu_count() or 4, 8), help="Number of parallel worker processes")
    parser.add_argument("--resolution", type=float, default=0.08, help="Grid resolution in metres (e.g. 0.05, 0.08, 0.10)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    args = parser.parse_args()

    run_batch_evaluation(
        pkl_path=args.pkl,
        num_plans=args.count,
        workers=args.workers,
        resolution=args.resolution,
        seed=args.seed
    )
