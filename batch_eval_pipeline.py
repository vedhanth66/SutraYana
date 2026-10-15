import os
import sys
import time
import random
import pickle
import tempfile
import json

from export_resplan_to_json import extract_rooms_and_doors
from phase1_pipeline import load_and_process_plan
from phase2_partition import run_phase2
from phase3_sequencing import find_optimal_sequence


def evaluate_batch(pkl_path="../SutraYana_temp/ResPlan/ResPlan.pkl", num_plans=25, seed=42):
    print("=" * 80)
    print(f"BATCH EVALUATION: Testing Phase 1 -> Phase 2 -> Phase 3 on {num_plans} ResPlan Plans")
    print("=" * 80)

    if not os.path.exists(pkl_path):
        # Fallback search
        alt_paths = [
            "ResPlan/ResPlan.pkl",
            "../ResPlan.pkl",
            "../../ResPlan.pkl"
        ]
        for ap in alt_paths:
            if os.path.exists(ap):
                pkl_path = ap
                break

    print(f"Loading dataset from: {pkl_path}")
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)

    total_available = len(data) if isinstance(data, list) else len(data.keys())
    print(f"Total available plans in dataset: {total_available}")

    random.seed(seed)
    sampled_indices = random.sample(range(min(500, total_available)), num_plans)

    results = []
    total_start = time.time()

    for run_idx, plan_idx in enumerate(sampled_indices, start=1):
        plan_raw = data[plan_idx] if isinstance(data, list) else data[list(data.keys())[plan_idx]]
        t0 = time.time()

        try:
            # 1. Export in-memory JSON structure
            formatted = extract_rooms_and_doors(plan_raw, plan_id=f"plan_{plan_idx}")
            
            # Temporary file for pipeline loading
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
                json.dump(formatted, tf)
                temp_json_path = tf.name

            # 2. Phase 1: Data Pipeline & House Graph
            G, nodes_dict, scale, min_hubs = load_and_process_plan(temp_json_path, show_plot=False)

            eligible_nodes = [n for n in G.nodes() if G.nodes[n].get("eligible", True)]
            if len(eligible_nodes) == 0:
                print(f"[{run_idx:02d}/{num_plans}] Plan #{plan_idx:05d}: Skipped (0 eligible rooms)")
                os.remove(temp_json_path)
                continue

            # 3. Phase 2: Partitioning & Hub Placement
            best_hubs, total_cost = run_phase2(temp_json_path, show_plot=False, plan_data=(G, nodes_dict, scale, min_hubs))

            # 4. Phase 3: Node Sequencing (TSP per hub)
            hub_sequences = {}
            total_tour_hops = 0
            for hub_room, assigned in best_hubs.items():
                seq, dist = find_optimal_sequence(G, hub_room, list(assigned), nodes_dict, scale)
                hub_sequences[hub_room] = seq
                total_tour_hops += dist

            dt = time.time() - t0
            os.remove(temp_json_path)

            # Verification of constraints
            num_hubs = len(best_hubs)
            max_nodes_per_hub = max(len(assigned) for assigned in best_hubs.values())
            hub_areas = [
                sum(float(G.nodes[r]["area"]) / (scale ** 2) for r in assigned)
                for assigned in best_hubs.values()
            ]
            max_area_per_hub = max(hub_areas)
            area_gap = (max(hub_areas) - min(hub_areas)) if len(hub_areas) >= 2 else 0.0

            valid = (
                num_hubs >= min_hubs
                and max_nodes_per_hub <= 5
                and max_area_per_hub <= 100.0 + 1e-4
            )

            results.append({
                "plan_idx": plan_idx,
                "eligible_rooms": len(eligible_nodes),
                "min_hubs": min_hubs,
                "actual_hubs": num_hubs,
                "max_nodes_per_hub": max_nodes_per_hub,
                "max_area_per_hub": max_area_per_hub,
                "area_gap_m2": area_gap,
                "total_tour_hops": total_tour_hops,
                "time_sec": dt,
                "valid": valid
            })

            status = "PASSED" if valid else "FAILED"
            print(
                f"[{run_idx:02d}/{num_plans}] Plan #{plan_idx:05d}: {status} | "
                f"Eligible: {len(eligible_nodes)} | Hubs: {num_hubs} (min {min_hubs}) | "
                f"MaxHubArea: {max_area_per_hub:.1f}m² | TourHops: {total_tour_hops} | Time: {dt*1000:.1f}ms"
            )

        except Exception as e:
            print(f"[{run_idx:02d}/{num_plans}] Plan #{plan_idx:05d}: CRASHED -> {e}")
            results.append({
                "plan_idx": plan_idx,
                "valid": False,
                "error": str(e)
            })

    total_time = time.time() - total_start
    successful = [r for r in results if r.get("valid")]
    success_rate = (len(successful) / len(results)) * 100 if results else 0

    print("\n" + "=" * 80)
    print("BATCH EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Plans Evaluated : {len(results)}")
    print(f"Passed All Checks     : {len(successful)} / {len(results)} ({success_rate:.1f}%)")
    print(f"Total Wall Clock Time : {total_time:.2f}s (Avg {(total_time/len(results))*1000:.1f} ms/plan)")
    if successful:
        avg_hops = sum(r["total_tour_hops"] for r in successful) / len(successful)
        avg_gap = sum(r["area_gap_m2"] for r in successful) / len(successful)
        print(f"Average Total Tour Hops: {avg_hops:.2f}")
        print(f"Average Area Gap       : {avg_gap:.2f} m²")
    print("=" * 80)


if __name__ == "__main__":
    pkl = sys.argv[1] if len(sys.argv) > 1 else "../SutraYana_temp/ResPlan/ResPlan.pkl"
    n_count = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    evaluate_batch(pkl, n_count)
