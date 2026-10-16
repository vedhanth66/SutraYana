"""Compatibility wrapper for complete connected partition search and routed ranking."""
from sutrayana.model import Plan
from sutrayana.solver import solve_plan, minimum_partitions
MAX_HUB_AREA = 100.0


def run_phase2(json_path="sample_plan.json", show_plot=False, save_img=None, plan_data=None, verbose=True):
    plan = plan_data[0].graph["plan"] if plan_data else Plan(json_path)
    output = solve_plan(plan)
    hubs = {h["room_id"]:set(h["assigned_rooms"]) for h in output["hubs"]}
    if save_img:
        from sutrayana.visualize import render
        render(plan,output,image_path=save_img)
    if verbose:
        print(f"Minimum hubs: {len(hubs)}; global J: {output['reported_metrics']['total_cost_J']:.3f}")
    return hubs,output["reported_metrics"]["total_cost_J"]


if __name__ == "__main__":
    import sys
    run_phase2(sys.argv[1] if len(sys.argv)>1 else "sample_plan.json")
