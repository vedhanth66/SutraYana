"""Exact connected set partitioning followed by finite-candidate route optimization."""
from functools import lru_cache
from itertools import combinations, permutations
import copy
import math
import networkx as nx
from shapely.geometry import Point, LineString
from .model import Plan
from .routing import Router
from .metrics import score, length
from .validation import validate


def minimum_partitions(plan):
    ids = sorted(plan.eligible)
    n = len(ids)
    zones = {}
    for size in range(1, min(5, n)+1):
        for zone in combinations(ids, size):
            if sum(plan.rooms[r].area for r in zone) <= 100+1e-8 and nx.is_connected(plan.graph.subgraph(zone)) and any(plan.hub_candidates(r) for r in zone):
                zones[sum(1 << ids.index(r) for r in zone)] = zone
    by_first = {i: [mask for mask in zones if mask & (1 << i)] for i in range(n)}
    @lru_cache(None)
    def optimum(mask):
        if not mask:
            return 0
        first = (mask & -mask).bit_length()-1
        return min((1+optimum(mask ^ z) for z in by_first[first] if z & mask == z), default=math.inf)
    def enumerate_best(mask):
        if not mask:
            yield []
            return
        first = (mask & -mask).bit_length()-1
        for z in by_first[first]:
            if z & mask == z and optimum(mask) == 1+optimum(mask ^ z):
                for rest in enumerate_best(mask ^ z):
                    yield [zones[z]] + rest
    full = (1 << n)-1
    if not math.isfinite(optimum(full)):
        raise ValueError("No capacity-feasible connected partition with legal hub positions.")
    return int(optimum(full)), list(enumerate_best(full))


def solve_plan(source, *, open_min=0.5):
    plan = source if isinstance(source, Plan) else Plan(source, open_min=open_min)
    open_min = plan.open_min
    minimum, partitions = minimum_partitions(plan)
    nodes = [r.node for r in plan.eligible.values()]
    candidates = {rid: plan.hub_candidates(rid) for rid in plan.eligible}
    router = Router(plan, candidates) if minimum else None
    path_cache = {}
    def path(a, b):
        key = (a,b)
        if key not in path_cache:
            path_cache[key] = router.path(a,b)
        return path_cache[key]

    @lru_cache(None)
    def zone_options(zone):
        options = []
        for home in zone:
            for hp in candidates[home]:
                hub_point = Point(hp)
                for order in permutations(zone):
                    points = [hp] + [plan.rooms[r].node for r in order] + [hp]
                    sequence = ["H"] + [plan.rooms[r].node_id for r in order] + ["H"]
                    legs = []
                    try:
                        for i, (a,b) in enumerate(zip(points, points[1:])):
                            polyline = path(a,b)
                            if i not in (0,len(points)-2) and LineString(polyline).distance(hub_point) < .001:
                                raise ValueError("Intermediate hub visit")
                            legs.append({"from": sequence[i], "to": sequence[i+1], "polyline": polyline, "length_m": length(polyline)})
                    except ValueError:
                        continue
                    h = {"hub_id": "H", "room_id": home, "location": {"x":hp[0], "y":hp[1]},
                         "assigned_rooms": list(zone), "assigned_nodes": [plan.rooms[r].node_id for r in zone],
                         "closed_sequence": sequence, "route_segments": legs,
                         "ring_length_m": sum(l["length_m"] for l in legs)}
                    cost = score([h],nodes)["total_cost_J"]
                    options.append((cost,h))
        options.sort(key=lambda item: item[0])
        # Keep distinct routes for global interaction optimization. Enumeration of
        # node orders is complete, but continuous route/hub search is heuristic.
        seen, retained = set(), []
        for cost,h in options:
            signature = tuple(tuple(tuple(p) for p in l["polyline"]) for l in h["route_segments"])
            if signature not in seen:
                seen.add(signature)
                retained.append(h)
            if len(retained) >= 8:
                break
        return retained

    best, best_rank = None, None
    feasible_partitions = 0
    for partition in partitions:
        options = [zone_options(tuple(zone)) for zone in partition]
        if any(not o for o in options):
            continue
        feasible_partitions += 1
        chosen = [o[0] for o in options]
        # Coordinate descent uses the global objective, including cross-ring X/O.
        for _ in range(3):
            changed = False
            for i, opts in enumerate(options):
                current = score(chosen,nodes)["total_cost_J"]
                selected = chosen[i]
                for option in opts:
                    trial = chosen[:i]+[option]+chosen[i+1:]
                    cost = score(trial,nodes)["total_cost_J"]
                    if cost < current-1e-9:
                        current, selected = cost, option
                if selected is not chosen[i]:
                    chosen[i], changed = selected, True
            if not changed:
                break
        areas = [sum(plan.rooms[r].area for r in z) for z in partition]
        gap = max(areas)-min(areas) if areas else 0.0
        metrics = score(chosen,nodes)
        rank = (metrics["total_cost_J"],gap)
        if best_rank is None or rank < best_rank:
            best, best_rank = chosen, rank
    if best is None:
        raise ValueError("No validated routes found for the minimum-hub partitions; no invalid fallback is emitted.")
    best = copy.deepcopy(best)
    for i,h in enumerate(best,1):
        hid = f"H{i}"
        h["hub_id"] = hid
        h["closed_sequence"] = [hid]+h["closed_sequence"][1:-1]+[hid]
        h["route_segments"][0]["from"] = hid
        h["route_segments"][-1]["to"] = hid
    initial_cost = score(best,nodes)["total_cost_J"]
    # Rip up one leg at a time. Obstacles never change; only cable-use costs do.
    # A proposed reroute must improve the true global score and pass all checks.
    def direction(a,b):
        return (0 if b[0]>a[0] else 2) if abs(b[1]-a[1])<1e-8 else (1 if b[1]>a[1] else 3)
    terminals = nodes + [(h["location"]["x"],h["location"]["y"]) for h in best]
    for sweep in range(2):
        improved = False
        for hi,h in enumerate(best):
            if len(h["assigned_nodes"]) == 1 and h["ring_length_m"] < .1:
                continue  # A tiny direct out-and-back cannot gain by adding bends.
            legs = h["route_segments"]
            for li,leg in enumerate(legs):
                occupied = [(tuple(a),tuple(b)) for hj,other in enumerate(best) for lj,l in enumerate(other["route_segments"])
                            if (hj,lj)!=(hi,li) for a,b in zip(l["polyline"],l["polyline"][1:])]
                previous = legs[li-1]["polyline"]
                following = legs[(li+1)%len(legs)]["polyline"]
                hp = (h["location"]["x"],h["location"]["y"])
                try:
                    alt = router.alternative(tuple(leg["polyline"][0]),tuple(leg["polyline"][-1]),occupied,terminals,hp,
                                             direction(previous[-2],previous[-1]),direction(following[0],following[1]))
                except ValueError:
                    continue
                old_points,old_length = leg["polyline"],leg["length_m"]
                current = score(best,nodes)["total_cost_J"]
                leg["polyline"],leg["length_m"] = alt,length(alt)
                h["ring_length_m"] = sum(l["length_m"] for l in legs)
                metrics = score(best,nodes)
                trial = {"plan_id":plan.id,"units":"m","hubs":best,"reported_metrics":metrics}
                if metrics["total_cost_J"] < current-1e-8 and validate(plan,trial)["valid"]:
                    improved = True
                else:
                    leg["polyline"],leg["length_m"] = old_points,old_length
                    h["ring_length_m"] = sum(l["length_m"] for l in legs)
        if not improved:
            break
    output = {"plan_id": plan.id, "units":"m", "hubs":best, "reported_metrics":score(best,nodes),
              "solver": {"minimum_hubs":minimum, "hub_count_proven":True,
                         "minimum_hub_partitions":len(partitions), "routable_partitions":feasible_partitions,
                         "area_gap_m2":best_rank[1], "cost_optimality":"heuristic finite hub/route candidates",
                         "cost_before_rerouting":initial_cost,
                         "open_passage_min_m":open_min, "zone_transit":"assigned eligible rooms only",
                         "coordinate_transform":{"origin_drawing_units":list(plan.origin), "units_per_metre":plan.scale, "source_y_down":plan.y_down}}}
    report = validate(plan,output)
    if not report["valid"]:
        raise ValueError("Output failed validation: " + "; ".join(e["message"] for e in report["errors"][:8]))
    output["validation"] = report
    return output
