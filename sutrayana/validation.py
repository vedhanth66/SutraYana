"""Submission checks, independent of the route construction algorithms."""
from collections import Counter
import math
import networkx as nx
from shapely.geometry import Point, LineString
from .metrics import score, length


def validate(plan, output):
    try:
        return _validate(plan, output)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return {"valid":False,"errors":[{"rule":"schema","message":f"Malformed submission: {error}"}],"recomputed_metrics":None}


def _validate(plan, output):
    errors = []
    def fail(code, message):
        errors.append({"rule": code, "message": message})
    if output.get("units") != "m":
        fail("units", "Output units must be m")
    if str(output.get("plan_id")) != plan.id:
        fail("identity", "Output plan_id does not match input")
    hubs = output.get("hubs", [])
    counts = Counter(r for h in hubs for r in h.get("assigned_rooms", []))
    if counts != Counter({r: 1 for r in plan.eligible}):
        fail("coverage", "Every eligible room must be assigned exactly once; no extra rooms")
    ids = [h.get("hub_id") for h in hubs]
    if len(ids) != len(set(ids)):
        fail("identity", "Hub IDs must be unique")
    all_nodes = {r.node_id: r.node for r in plan.eligible.values()}
    for h in hubs:
        hid = h.get("hub_id", "?")
        assigned = h.get("assigned_rooms", [])
        if not assigned or any(r not in plan.eligible for r in assigned):
            fail("assignment", f"{hid}: empty or ineligible assignment")
            continue
        rooms = [plan.rooms[r] for r in assigned]
        if len(rooms) > 5 or sum(r.area for r in rooms) > 100+1e-8:
            fail("capacity", f"{hid}: exceeds 5 nodes or 100 m²")
        if not nx.is_connected(plan.graph.subgraph(assigned)):
            fail("connectivity", f"{hid}: zone lacks door/open-passage connectivity")
        expected = [r.node_id for r in rooms]
        if Counter(h.get("assigned_nodes", [])) != Counter(expected):
            fail("nodes", f"{hid}: assigned_nodes does not match assigned rooms")
        seq = h.get("closed_sequence", [])
        if len(seq) != len(expected)+2 or seq[:1] != [hid] or seq[-1:] != [hid] or Counter(seq[1:-1]) != Counter(expected):
            fail("sequence", f"{hid}: must explicitly visit each assigned node once and return to hub")
        loc = h.get("location", {})
        try:
            hp = Point(float(loc["x"]), float(loc["y"]))
            if not math.isfinite(hp.x+hp.y):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            fail("hub", f"{hid}: invalid hub coordinates")
            continue
        home = h.get("room_id")
        if home not in assigned or not plan.rooms[home].polygon.contains(hp) or (not plan.barriers.is_empty and hp.distance(plan.barriers) < .5-.001) or not plan.free.covers(hp):
            fail("hub", f"{hid}: hub must be in an assigned room with 0.5 m clearance")
        targets = dict(all_nodes, **{hid: (hp.x,hp.y)})
        legs = h.get("route_segments", [])
        if len(legs) != len(seq)-1:
            fail("legs", f"{hid}: leg count does not match sequence")
        ring_length = 0
        for i, leg in enumerate(legs):
            a, b = leg.get("from"), leg.get("to")
            if i+1 >= len(seq) or [a,b] != seq[i:i+2]:
                fail("legs", f"{hid}: leg {i} does not match sequence")
            pts = leg.get("polyline", [])
            if len(pts) < 2 or any(len(p)!=2 or not all(isinstance(x, (int,float)) and math.isfinite(x) for x in p) for p in pts):
                fail("geometry", f"{hid}: malformed polyline in leg {i}")
                continue
            if a not in targets or b not in targets or math.dist(pts[0], targets[a]) > 1e-7 or math.dist(pts[-1], targets[b]) > 1e-7:
                fail("endpoints", f"{hid}: leg {i} does not start/end at the fixed terminals")
            for p, q in zip(pts, pts[1:]):
                if abs(p[0]-q[0]) > 1e-8 and abs(p[1]-q[1]) > 1e-8:
                    fail("axis", f"{hid}: diagonal in leg {i}")
                if math.dist(p,q) > 1e-10 and not plan.free.covers(LineString([p,q])):
                    fail("freespace", f"{hid}: leg {i} leaves inner-wall-window")
            line = LineString(pts)
            for nid, point in targets.items():
                if nid not in (a,b) and line.distance(Point(point)) < .001:
                    fail("visits", f"{hid}: leg {i} passes another terminal {nid}")
            # An endpoint cannot occur again within its own leg.
            for nid in (a,b):
                if nid not in targets:
                    continue
                point = Point(targets[nid])
                for j, (p,q) in enumerate(zip(pts,pts[1:])):
                    if (nid == a and j == 0) or (nid == b and j == len(pts)-2):
                        continue
                    if math.dist(p,q)>1e-10 and LineString([p,q]).distance(point) < .001:
                        fail("visits", f"{hid}: leg {i} revisits {nid}")
            actual = length(pts)
            ring_length += actual
            if abs(leg.get("length_m", -1)-actual) > .001:
                fail("length", f"{hid}: incorrect leg length")
        if abs(h.get("ring_length_m", -1)-ring_length) > .001:
            fail("length", f"{hid}: incorrect ring length")
    metrics = score(hubs, all_nodes.values()) if not errors else None
    if metrics is not None:
        for key, value in metrics.items():
            if abs(output.get("reported_metrics", {}).get(key, -1)-value) > .001:
                fail("metrics", f"Incorrect reported {key}")
    return {"valid": not errors, "errors": errors, "recomputed_metrics": metrics}
