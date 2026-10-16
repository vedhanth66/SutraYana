"""Input normalization. All solver geometry is in metres, y up."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import networkx as nx
from shapely import make_valid, affinity
from shapely.geometry import shape, Point, Polygon, LineString
from shapely.ops import unary_union, nearest_points

ELIGIBLE = {"living", "bedroom", "kitchen", "storage"}


def parts(g):
    return list(g.geoms) if hasattr(g, "geoms") else ([] if g.is_empty else [g])


def geometry(value):
    if value is None:
        return Polygon()
    if hasattr(value, "geom_type"):
        g = value
    else:
        if "polygon" in value:
            value = value["polygon"]
        if value.get("type") == "Feature":
            value = value["geometry"]
        g = shape(value)
    if not g.is_valid:
        g = make_valid(g)
    return g


@dataclass
class Room:
    id: str
    kind: str
    polygon: object
    node: tuple | None
    node_id: str | None

    @property
    def area(self):
        return self.polygon.area


class Plan:
    def __init__(self, source, open_min=0.5):
        raw = json.loads(Path(source).read_text(encoding="utf-8-sig")) if isinstance(source, (str, Path)) else source
        self.id = str(raw.get("plan_id", raw.get("id", "plan")))
        inner = geometry(raw.get("inner"))
        area = float(raw.get("area", 0))
        if inner.is_empty or inner.area <= 0 or not math.isfinite(area) or area <= 0:
            raise ValueError("Input needs an inner polygon and positive area in square metres.")
        self.scale = 1.0 if raw.get("units") == "m" else math.sqrt(inner.area / area)
        self.origin = inner.bounds[:2]
        self.y_down = raw.get("coordinate_system", {}).get("y_axis") == "down"
        ymax = inner.bounds[3]

        def convert(g):
            if self.y_down:
                g = affinity.scale(g, 1, -1, origin=(0, 0))
                g = affinity.translate(g, -self.origin[0], ymax)
            else:
                g = affinity.translate(g, -self.origin[0], -self.origin[1])
            return affinity.scale(g, 1 / self.scale, 1 / self.scale, origin=(0, 0))

        self.convert = convert
        self.inner = convert(inner)
        if "wall" not in raw and "walls" not in raw:
            raise ValueError("Missing wall geometry. Supply wall: null explicitly for a wall-free synthetic plan.")
        self.wall = convert(geometry(raw.get("wall", raw.get("walls"))))
        self.window = convert(geometry(raw.get("window", raw.get("windows"))))
        self.barriers = unary_union([self.wall, self.window])
        self.free = self.inner.difference(self.barriers)
        self.rooms = {}
        node_ids = set()
        top_nodes = {n["room_id"]: n for n in raw.get("nodes", [])}
        for item in raw.get("rooms", []):
            rid = str(item["id"])
            if rid in self.rooms:
                raise ValueError(f"Duplicate room ID: {rid}")
            poly = convert(geometry(item.get("polygon", item.get("geometry"))))
            if poly.is_empty or poly.area <= 0:
                raise ValueError(f"Room {rid} has no polygon area.")
            kind = item.get("type", "").lower()
            nd = item.get("node", top_nodes.get(rid))
            point, nid = None, None
            if kind in ELIGIBLE:
                if nd is None:
                    raise ValueError(f"Room {rid} needs its fixed input node; the solver never invents one.")
                pos = nd.get("location", nd) if isinstance(nd, dict) else nd
                p = Point(pos["x"], pos["y"]) if isinstance(pos, dict) else Point(pos)
                p = convert(p)
                if not math.isfinite(p.x + p.y):
                    raise ValueError(f"Non-finite node in {rid}")
                point = (p.x, p.y)
                nid = str(nd.get("id", item.get("node_id", f"N{len(node_ids)+1}"))) if isinstance(nd, dict) else str(item.get("node_id", f"N{len(node_ids)+1}"))
                if nid in node_ids or nid.startswith("H"):
                    raise ValueError(f"Duplicate or reserved node ID: {nid}")
                node_ids.add(nid)
                if not poly.contains(p) or not self.free.covers(p):
                    raise ValueError(f"Fixed node {nid} is outside its room or in an obstacle.")
                if p.distance(poly.boundary) < 0.5 - 0.001:
                    raise ValueError(f"Fixed node {nid} lacks the required 0.5 m clearance.")
                if poly.area > 100 + 1e-8:
                    raise ValueError(f"Room {rid} exceeds the 100 m² capacity limit.")
            self.rooms[rid] = Room(rid, kind, poly, point, nid)
        if not self.rooms and raw.get("rooms") is None:
            raise ValueError("Expected rooms array; use export_resplan_to_json.py for raw ResPlan records.")
        self.eligible = {k: r for k, r in self.rooms.items() if r.kind in ELIGIBLE}
        self.doors = []
        for d in raw.get("doors", []):
            if d.get("type") in {"window", "entrance", "front_door", "passage"}:
                continue
            self.doors.extend(parts(convert(geometry(d.get("polygon", d.get("geometry"))))))
        if "door" in raw:
            self.doors.extend(parts(convert(geometry(raw["door"]))))
        self.open_min = open_min
        self.graph = self._connectivity()

    def _connectivity(self):
        """Require a continuous free connector touching both rooms; no wall proximity edges."""
        graph = nx.Graph()
        graph.add_nodes_from(self.eligible)
        for door in self.doors:
            for gap in parts(door.intersection(self.free)):
                # Annotation gaps of up to 2 cm are accepted only if the bridge is free.
                touches = []
                for rid, r in self.eligible.items():
                    if gap.distance(r.polygon) > 0.02:
                        continue
                    a, b = nearest_points(gap, r.polygon)
                    if a.equals(b) or self.free.covers(LineString([a, b])):
                        contact = gap.boundary.intersection(r.polygon.buffer(0.02)).length
                        if contact > 0.05:
                            touches.append((contact, rid))
                # ResPlan can merge touching doors into one polygon. Preserve
                # every substantial contact in that free component, while
                # excluding tiny corner slivers rather than forcing two rooms.
                touches.sort(reverse=True)
                if len(touches) >= 2:
                    threshold = max(.10,.25*touches[0][0])
                    connected = [rid for contact,rid in touches if contact >= threshold]
                    for i,a in enumerate(connected):
                        for b in connected[i+1:]:
                            graph.add_edge(a,b,type="door")
        ids = sorted(self.eligible)
        for i, a in enumerate(ids):
            for b in ids[i+1:]:
                if graph.has_edge(a, b):
                    continue
                pa, pb = self.rooms[a].polygon, self.rooms[b].polygon
                if pa.distance(pb) > 0.04:
                    continue
                gap = pa.buffer(0.02, join_style=2).intersection(pb.buffer(0.02, join_style=2)).intersection(self.free)
                for p in parts(gap):
                    if p.area <= 1e-9:
                        continue
                    # Both contacts must lie in the same free component, and be wide.
                    ca = p.intersection(pa).length
                    cb = p.intersection(pb).length
                    x0, y0, x1, y1 = p.bounds
                    if min(ca, cb) >= self.open_min and max(x1-x0, y1-y0) >= self.open_min:
                        graph.add_edge(a, b, type="opening")
                        break
        return graph

    def hub_candidates(self, rid):
        r = self.rooms[rid]
        safe = r.polygon.buffer(-0.5+1e-9).intersection(self.free)
        if safe.is_empty:
            return []
        n = Point(r.node)
        candidates = []
        # A separate hub point avoids ambiguous zero-length hub-node legs.
        for dx, dy in [(0.03, 0), (0, 0.03), (-0.03, 0), (0, -0.03)]:
            p = Point(n.x+dx, n.y+dy)
            if safe.covers(p):
                candidates.append((p.x, p.y))
        for component in parts(safe):
            p = component.centroid
            if not component.covers(p):
                p = component.representative_point()
            if p.distance(n) > 0.002:
                candidates.append((p.x, p.y))
        return list(dict.fromkeys(candidates))[:2]
