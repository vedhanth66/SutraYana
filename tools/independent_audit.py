"""Apply the supplied external audit to new outputs in the auditor's coordinate frame."""
import argparse
import copy
import json
import pickle
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"audit_tools"))
from validate import build_truth, check_output, global_metrics, ring_polyline
from adjacency import true_edges
from itertools import combinations
import numpy as np
import networkx as nx
from scipy.optimize import milp, Bounds, LinearConstraint
from sutrayana.exporter import extract_rooms_and_doors
from sutrayana.model import Plan
from sutrayana.solver import solve_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pkl",default="ResPlan/ResPlan/ResPlan.pkl")
    parser.add_argument("--count",type=int,default=120)
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--output",default="results/independent_audit.json")
    args = parser.parse_args()
    with open(args.pkl,"rb") as f:
        data = pickle.load(f)
    rows = []
    for index in random.Random(args.seed).sample(range(len(data)),min(args.count,len(data))):
        raw = data[index] if isinstance(data,list) else data[list(data)[index]]
        try:
            converted = extract_rooms_and_doors(raw)
            plan = Plan(converted)
            out = solve_plan(plan)
            restored = copy.deepcopy(out)
            dx,dy = (v/plan.scale for v in plan.origin)
            for h in restored["hubs"]:
                h["location"]["x"] += dx
                h["location"]["y"] += dy
                for leg in h["route_segments"]:
                    leg["polyline"] = [(p[0]+dx,p[1]+dy) for p in leg["polyline"]]
            truth = build_truth(raw)
            meta = {r["id"]:{"type":r["type"],"area":r["area"],"node":(r["node"]["x"]/plan.scale,r["node"]["y"]/plan.scale)} for r in converted["rooms"] if r["id"] in plan.eligible}
            errors,_ = check_output(restored,truth,meta)
            metrics = global_metrics({h["hub_id"]:ring_polyline(h) for h in restored["hubs"]})
            rep = out["reported_metrics"]
            differences = {k:metrics[k]-rep[name] for k,name in [("L","total_length_m"),("B","total_bends"),("O","total_overlap_m")]}
            edges,rooms = true_edges(raw,truth)
            ids = [r for r,(t,p) in rooms.items() if t in {"living","bedroom","kitchen","storage"}]
            # Independent MILP cross-check: one binary variable per connected
            # capacity-feasible zone, each room covered exactly once.
            graph = nx.Graph()
            graph.add_nodes_from(ids)
            graph.add_edges_from((a,b) for a,b in edges if a in ids and b in ids)
            zones = [z for size in range(1,min(5,len(ids))+1) for z in combinations(ids,size)
                     if sum(rooms[r][1].area for r in z)<=100+1e-8 and nx.is_connected(graph.subgraph(z))]
            matrix = np.array([[int(r in z) for z in zones] for r in ids])
            reference = milp(np.ones(len(zones)),integrality=np.ones(len(zones)),bounds=Bounds(0,1),constraints=LinearConstraint(matrix,1,1),options={"mip_rel_gap":0})
            if not reference.success:
                raise ValueError("Independent partition MILP failed")
            exact = round(reference.fun)
            rows.append({"index":index,"external_errors":errors,"external_metric_differences":differences,"hubs":len(out["hubs"]),"audit_graph_minimum":exact})
        except Exception as e:
            rows.append({"index":index,"rejected":str(e)})
        print(f"Audited {len(rows)}/{args.count}: dataset index {index}",flush=True)
    summary = {"sample_size":len(rows),"outputs":sum("external_errors" in r for r in rows),
               "external_geometry_failures":sum(bool(r.get("external_errors")) for r in rows),
               "graph_minimum_disagreements":sum(r["hubs"]!=r["audit_graph_minimum"] for r in rows if "hubs" in r),
               "metric_disagreements":sum(any(abs(v)>.01 for v in r.get("external_metric_differences",{}).values()) for r in rows)}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps({"summary":summary,"results":rows},indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
