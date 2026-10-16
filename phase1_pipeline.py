"""Geometry and connectivity inspection, using the same normalized plan as solve.py."""
import math
from shapely.geometry import Point, mapping
from sutrayana.model import Plan


def load_and_process_plan(json_path, output_image_path=None, show_plot=True, verbose=True):
    plan = Plan(json_path)
    graph = plan.graph.copy()
    for rid,r in plan.eligible.items():
        graph.nodes[rid].update(eligible=True, area=r.area, area_m2=r.area, type=r.kind, polygon=mapping(r.polygon))
    graph.graph.update(plan=plan, freespace=plan.free, scale=1.0)
    nodes = {rid:Point(r.node) for rid,r in plan.eligible.items()}
    lower = max(math.ceil(sum(r.area for r in plan.eligible.values())/100), math.ceil(len(nodes)/5))
    if verbose:
        print(f"{len(nodes)} eligible rooms; {len(graph.edges)} real connections; capacity lower bound {lower}")
    if output_image_path:
        from sutrayana.solver import solve_plan
        from sutrayana.visualize import render
        render(plan,solve_plan(plan),image_path=output_image_path)
    return graph,nodes,1.0,lower


if __name__ == "__main__":
    import sys
    load_and_process_plan(sys.argv[1] if len(sys.argv)>1 else "sample_plan.json", show_plot=False)
