"""Compatibility wrapper: sequencing and physical routing are optimized together."""
from sutrayana.model import Plan
from sutrayana.solver import solve_plan
from phase4_routing import calculate_ring_metrics, compress_orthogonal_path


def run_phase3(json_path="sample_plan.json", show_plot=False, save_img=None, plan_data=None):
    plan = plan_data[0].graph["plan"] if plan_data else Plan(json_path)
    output = solve_plan(plan)
    if save_img:
        from sutrayana.visualize import render
        render(plan,output,image_path=save_img)
    return ({h["room_id"]:h["closed_sequence"] for h in output["hubs"]},
            {h["room_id"]:set(h["assigned_rooms"]) for h in output["hubs"]})


if __name__ == "__main__":
    import sys
    print(run_phase3(sys.argv[1] if len(sys.argv)>1 else "sample_plan.json")[0])
