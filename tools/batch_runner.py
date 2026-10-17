"""SutraYana High-Throughput Batch Dataset Runner & Benchmark Suite.

Evaluates datasets of floor plans (JSON directory or pickle), solves each plan
with process-isolated bounded execution, validates geometric constraints,
computes theoretical lower bounds, and outputs competitive performance metrics.
"""
import argparse
import csv
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32" and "pytest" not in sys.modules:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from sutrayana.model import Plan
from sutrayana.solver import solve_plan, compute_hub_lower_bound
from sutrayana.validation import validate


def evaluate_single_plan(task_args: tuple) -> Dict[str, Any]:
    """Process-isolated evaluation of a single plan."""
    plan_path_or_dict, plan_id, options = task_args
    t0 = time.perf_counter()

    try:
        if isinstance(plan_path_or_dict, (str, Path)):
            raw_content = json.loads(Path(plan_path_or_dict).read_text(encoding="utf-8-sig"))
            plan = Plan(raw_content, wire_clearance=options.get("wire_clearance", 0.0))
        elif isinstance(plan_path_or_dict, dict):
            plan = Plan(plan_path_or_dict, wire_clearance=options.get("wire_clearance", 0.0))
        else:
            raise ValueError(f"Unknown plan input type: {type(plan_path_or_dict)}")

        total_area = sum(r.area for r in plan.eligible.values()) if plan.eligible else 0.0
        nodes_count = len(plan.eligible)
        lower_bound = compute_hub_lower_bound(plan)

        oversized = [r for r in plan.eligible.values() if r.area > 100 + 1e-6]
        if oversized:
            return {
                "plan_id": plan_id,
                "valid": False,
                "skipped": True,
                "status": "INELIGIBLE",
                "error": f"Room {oversized[0].id} ({oversized[0].area:.1f} m2) exceeds 100 m2 hub capacity",
                "rooms_count": len(plan.rooms),
                "nodes_count": nodes_count,
                "total_area_m2": round(total_area, 2),
                "lower_bound_hubs": lower_bound,
                "hubs_count": None,
                "at_lower_bound": False,
                "cost_J": None,
                "length_m": None,
                "crossings_X": None,
                "overlap_m": None,
                "bends_B": None,
                "elapsed_s": round(time.perf_counter() - t0, 4),
                "clearance_min_m": None
            }

        # Directly solve within isolated worker process
        opts = dict(options)
        opts.pop("timeout", None)
        designs_dir = opts.pop("designs_dir", None)
        save_designs = opts.pop("save_designs", False)
        out = solve_plan(plan, **opts)

        dt = time.perf_counter() - t0
        rep = out.get("reported_metrics", {})
        solver_meta = out.get("solver", {})

        # Independent validation
        val_res = validate(plan, out)
        is_valid = bool(val_res.get("valid", False))
        val_errors = val_res.get("errors", [])

        hubs_count = rep.get("hub_count", len(out.get("hubs", [])))
        cost_j = rep.get("total_cost_J", 0.0)
        len_m = rep.get("total_length_m", 0.0)
        cross_x = rep.get("total_crossings", 0)
        over_o = rep.get("total_overlap_m", 0.0)
        bends_b = rep.get("total_bends", 0)
        at_lb = (hubs_count == lower_bound) if lower_bound > 0 else True

        design_json_path = None
        if save_designs and designs_dir:
            os.makedirs(designs_dir, exist_ok=True)
            d_path = Path(designs_dir) / f"{plan_id}_solution.json"
            d_path.write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf-8")
            design_json_path = str(d_path)

        return {
            "plan_id": plan_id,
            "valid": is_valid,
            "validation_errors": val_errors,
            "rooms_count": len(plan.rooms),
            "nodes_count": nodes_count,
            "total_area_m2": round(total_area, 2),
            "lower_bound_hubs": lower_bound,
            "hubs_count": hubs_count,
            "at_lower_bound": at_lb,
            "cost_J": round(float(cost_j), 2),
            "worse_J": round(float(solver_meta.get("worse_J", cost_j)), 2),
            "length_m": round(float(len_m), 2),
            "crossings_X": int(cross_x),
            "overlap_m": round(float(over_o), 2),
            "bends_B": int(bends_b),
            "area_gap_m2": round(float(solver_meta.get("area_gap_m2", 0.0)), 2),
            "elapsed_s": round(dt, 4),
            "fallback_ladder": solver_meta.get("fallback_ladder_activated", False),
            "design_json_path": design_json_path,
            "clearance_min_m": None
        }

    except Exception as exc:
        dt = time.perf_counter() - t0
        return {
            "plan_id": plan_id,
            "valid": False,
            "error": str(exc),
            "rooms_count": 0,
            "nodes_count": 0,
            "total_area_m2": 0.0,
            "lower_bound_hubs": 0,
            "hubs_count": None,
            "at_lower_bound": False,
            "cost_J": None,
            "length_m": None,
            "crossings_X": None,
            "overlap_m": None,
            "bends_B": None,
            "elapsed_s": round(dt, 4),
            "clearance_min_m": None
        }


def run_batch(
    plan_sources: List[tuple],
    workers: int = 4,
    options: Optional[Dict[str, Any]] = None,
    output_csv: str = "results/benchmark_report.csv",
    output_json: str = "results/benchmark_summary.json"
) -> Dict[str, Any]:
    """Execute batch benchmark across all provided plans."""
    options = options or {}
    total_plans = len(plan_sources)
    results = []

    print("\n" + "=" * 80)
    print("SUTRAYANA HIGH-PERFORMANCE BATCH BENCHMARK RUNNER")
    print(f"Total Plans       : {total_plans}")
    print(f"Parallel Workers  : {workers}")
    print(f"Clearance Profile : {options.get('wire_clearance', 0.0)} m")
    print(f"Per-Plan Timeout  : {options.get('timeout', 30)} s")
    print("=" * 80)

    start_time = time.perf_counter()
    tasks = [(src, pid, options) for src, pid in plan_sources]

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(evaluate_single_plan, t): t[1] for t in tasks}
            for i, fut in enumerate(as_completed(futures), start=1):
                res = fut.result()
                results.append(res)
                status_icon = "[PASS]" if res["valid"] else "[FAIL]"
                lb_icon = "[LB]" if res.get("at_lower_bound") else "[  ]"
                j_str = f"J={res['cost_J']:.1f}" if res.get("cost_J") is not None else "J=FAIL"
                time_str = f"{res['elapsed_s']*1000:.0f}ms"
                print(f"[{i:03d}/{total_plans}] {status_icon} Plan {res['plan_id']:<14} | Hubs: {str(res.get('hubs_count')):<2} {lb_icon} | {j_str:<10} | Time: {time_str}")
    else:
        for i, t in enumerate(tasks, start=1):
            res = evaluate_single_plan(t)
            results.append(res)
            status_icon = "[PASS]" if res["valid"] else "[FAIL]"
            lb_icon = "[LB]" if res.get("at_lower_bound") else "[  ]"
            j_str = f"J={res['cost_J']:.1f}" if res.get("cost_J") is not None else "J=FAIL"
            time_str = f"{res['elapsed_s']*1000:.0f}ms"
            print(f"[{i:03d}/{total_plans}] {status_icon} Plan {res['plan_id']:<14} | Hubs: {str(res.get('hubs_count')):<2} {lb_icon} | {j_str:<10} | Time: {time_str}")

    total_wall_s = time.perf_counter() - start_time

    # Sort results by plan_id
    results.sort(key=lambda r: str(r["plan_id"]))

    eligible_results = [r for r in results if not r.get("skipped")]
    valid_results = [r for r in eligible_results if r["valid"]]
    eligible_count = len(eligible_results)
    eligible_valid_pct = (len(valid_results) / max(1, eligible_count)) * 100.0 if eligible_count > 0 else 0.0
    valid_count = len(valid_results)
    valid_pct = (valid_count / max(1, total_plans)) * 100.0

    lb_matched = [r for r in valid_results if r.get("at_lower_bound")]
    lb_match_pct = (len(lb_matched) / max(1, valid_count)) * 100.0 if valid_count > 0 else 0.0

    zero_crossings = [r for r in valid_results if r.get("crossings_X", 0) == 0]
    zero_cross_pct = (len(zero_crossings) / max(1, valid_count)) * 100.0 if valid_count > 0 else 0.0

    costs_j = [r["cost_J"] for r in valid_results if r.get("cost_J") is not None]
    times_s = [r["elapsed_s"] for r in results]

    median_j = sorted(costs_j)[len(costs_j) // 2] if costs_j else 0.0
    mean_j = sum(costs_j) / max(1, len(costs_j)) if costs_j else 0.0
    median_time_ms = (sorted(times_s)[len(times_s) // 2]) * 1000.0 if times_s else 0.0
    p95_time_ms = (sorted(times_s)[int(len(times_s) * 0.95)]) * 1000.0 if times_s else 0.0
    throughput = total_plans / max(0.001, total_wall_s)

    # Save to CSV
    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    csv_fields = [
        "plan_id", "valid", "hubs_count", "lower_bound_hubs", "at_lower_bound",
        "cost_J", "worse_J", "length_m", "crossings_X", "overlap_m", "bends_B",
        "area_gap_m2", "rooms_count", "nodes_count", "total_area_m2", "elapsed_s",
        "design_json_path"
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    # Save to JSON
    summary = {
        "benchmark_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_plans_evaluated": total_plans,
        "eligible_inputs_count": eligible_count,
        "valid_plans_count": valid_count,
        "eligible_pass_rate_pct": round(eligible_valid_pct, 2),
        "validity_rate_pct": round(valid_pct, 2),
        "lower_bound_match_count": len(lb_matched),
        "lower_bound_match_rate_pct": round(lb_match_pct, 2),
        "zero_crossings_rate_pct": round(zero_cross_pct, 2),
        "throughput_plans_per_sec": round(throughput, 2),
        "median_latency_ms": round(median_time_ms, 1),
        "p95_latency_ms": round(p95_time_ms, 1),
        "median_cost_J": round(median_j, 2),
        "mean_cost_J": round(mean_j, 2),
        "total_wall_clock_sec": round(total_wall_s, 2),
        "detailed_results": results
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Print Gorgeous ASCII Leaderboard Summary
    print("\n" + "=" * 80)
    print("SUTRAYANA BENCHMARK PERFORMANCE REPORT")
    print("=" * 80)
    print(f"Total Plans Evaluated     : {total_plans}")
    print(f"Benchmark-Eligible Inputs : {eligible_count} / {total_plans}")
    print(f"Eligible Pass Rate        : {valid_count} / {eligible_count} ({eligible_valid_pct:.2f}%)")
    print(f"Theoretical Lower-Bound H : {len(lb_matched)} / {valid_count} ({lb_match_pct:.2f}%)")
    print(f"Zero Crossings Rate (X=0) : {len(zero_crossings)} / {valid_count} ({zero_cross_pct:.2f}%)")
    print(f"Median Execution Latency  : {median_time_ms:.1f} ms / plan")
    print(f"P95 Execution Latency     : {p95_time_ms:.1f} ms / plan")
    print(f"System Throughput         : {throughput:.2f} plans / second")
    print(f"Objective Cost J (Median) : {median_j:.2f}")
    print(f"Objective Cost J (Mean)   : {mean_j:.2f}")
    print(f"Total Benchmark Wall-Time : {total_wall_s:.2f} s")
    print("-" * 80)
    print(f"Detailed CSV Report       : {output_csv}")
    print(f"Detailed JSON Summary     : {output_json}")
    print("=" * 80 + "\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="SutraYana High-Throughput Batch Dataset Runner")
    parser.add_argument("--dir", default=None, help="Directory containing JSON floor plans (e.g. examples/ or plans/)")
    parser.add_argument("--pkl", default=None, help="Path to ResPlan.pkl dataset")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of plans to evaluate")
    parser.add_argument("--workers", type=int, default=min(mp.cpu_count() or 4, 8), help="Number of worker processes")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-plan solver timeout in seconds")
    parser.add_argument("--clearance", type=float, default=0.0, choices=[0.0, 0.5], help="Wire-to-wall clearance (0.0 or 0.5)")
    parser.add_argument("--csv", default="results/benchmark_report.csv", help="Path to output CSV")
    parser.add_argument("--json", default="results/benchmark_summary.json", help="Path to output JSON")
    args = parser.parse_args()

    plan_sources = []

    if args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            print(f"ERROR: Directory '{args.dir}' does not exist.")
            sys.exit(1)
        for p in sorted(d.glob("*.json")):
            plan_sources.append((p, p.stem))
    elif args.pkl:
        import pickle
        with open(args.pkl, "rb") as f:
            data = pickle.load(f)
        for i, item in enumerate(data):
            plan_sources.append((item, f"plan_{i:05d}"))
    else:
        # Default: scan examples/ and plans/
        for folder in ["examples", "plans"]:
            fpath = ROOT / folder
            if fpath.is_dir():
                for p in sorted(fpath.glob("*.json")):
                    plan_sources.append((p, p.stem))

    if not plan_sources:
        print("ERROR: No floor plan files found!")
        sys.exit(1)

    if args.limit:
        plan_sources = plan_sources[:args.limit]

    options = {
        "timeout": args.timeout,
        "wire_clearance": args.clearance
    }

    run_batch(
        plan_sources=plan_sources,
        workers=args.workers,
        options=options,
        output_csv=args.csv,
        output_json=args.json
    )


if __name__ == "__main__":
    main()
