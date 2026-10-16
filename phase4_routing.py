"""Compatibility entry point for the validated solver. Prefer solve.py for submissions."""
import json
from pathlib import Path
from sutrayana.model import Plan
from sutrayana.solver import solve_plan
from sutrayana.metrics import score, compact


def compress_orthogonal_path(pts):
    return compact(pts)


def calculate_ring_metrics(polyline_pts, tol_mm=0.001):
    p = polyline_pts[0]
    m = score([{"location":{"x":p[0],"y":p[1]},"route_segments":[{"polyline":polyline_pts}]}])
    return {"L":m["total_length_m"],"B":m["total_bends"],"X":m["total_crossings"],"O":m["total_overlap_m"],"J":m["total_cost_J"]}


def run_phase4(json_path="sample_plan.json", show_plot=False, save_img=None, resolution=0.08, output_json_path=None, verbose=True):
    plan = Plan(json_path)
    out = solve_plan(plan)
    if output_json_path:
        target = Path(output_json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if save_img or show_plot:
        from sutrayana.visualize import render
        render(plan, out, image_path=save_img or "floor_plan_phase4.png")
    routed = {}
    for i,h in enumerate(out["hubs"], 1):
        polyline = [p for leg in h["route_segments"] for p in leg["polyline"]]
        routed[h["room_id"]] = {**h, "hub_idx":i, "hub_loc":(h["location"]["x"],h["location"]["y"]), "sequence":h["closed_sequence"], "polyline":compact(polyline), "metrics":calculate_ring_metrics(polyline)}
    if verbose:
        print(f"VALIDATED: {len(out['hubs'])} hubs, global J={out['reported_metrics']['total_cost_J']:.3f}")
    return out, out["reported_metrics"]["total_cost_J"], routed


if __name__ == "__main__":
    import sys
    run_phase4(sys.argv[1] if len(sys.argv)>1 else "sample_plan.json", save_img="floor_plan_phase4.png" if "--save" in sys.argv else None, output_json_path="output_plan.json")
