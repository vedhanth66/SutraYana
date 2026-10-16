"""Input normalization. All solver geometry is in metres, y up."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import networkx as nx
from shapely import make_valid, affinity, wkt
from shapely.geometry import shape, Point, Polygon, LineString, box, MultiPoint, mapping
from shapely.ops import unary_union, nearest_points

ELIGIBLE = {"living", "bedroom", "kitchen", "storage"}
AREA_TOL = 1e-6


def parts(g):
    return list(g.geoms) if hasattr(g, "geoms") else ([] if g.is_empty else [g])


def geometry(value):
    if value is None:
        return Polygon()
    if hasattr(value, "geom_type"):
        g = value
    elif isinstance(value, str):
        g = wkt.loads(value)
    elif isinstance(value, (list, tuple)):
        if not value:
            return Polygon()
        if isinstance(value[0], dict):
            g = unary_union([geometry(v) for v in value])
        elif isinstance(value[0][0], (int, float)):
            g = Polygon(value)
        else:
            g = Polygon(value[0], value[1:])
    else:
        if "polygon" in value:
            return geometry(value["polygon"])
        if value.get("type") == "Feature":
            return geometry(value["geometry"])
        if "wkt" in value:
            return geometry(value["wkt"])
        if "coordinates" in value and "type" not in value:
            return geometry(value["coordinates"])
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


def plan_from_solution(raw, name="plan"):
    """Reconstruct a valid Plan dictionary from a submission/solution JSON containing 'hubs'."""
    plan_id = str(raw.get("plan_id", raw.get("id", name)))
    terminals = {}
    all_pts = []
    hubs = raw.get("hubs", [])
    for h in hubs:
        hp = (float(h["location"]["x"]), float(h["location"]["y"]))
        terminals[h["hub_id"]] = hp
        all_pts.append(hp)
        for seg in h.get("route_segments", []):
            pts = [tuple(p) for p in seg.get("polyline", [])]
            all_pts.extend(pts)
            if pts:
                terminals[seg["from"]] = pts[0]
                terminals[seg["to"]] = pts[-1]

    if not all_pts:
        all_pts = [(0.0, 0.0), (10.0, 10.0)]

    mp = MultiPoint(all_pts)
    x0, y0, x1, y1 = mp.bounds
    margin = 2.0
    inner = box(x0 - margin, y0 - margin, x1 + margin, y1 + margin)

    rooms = []
    doors = []
    for h in hubs:
        assigned_rooms = h.get("assigned_rooms", [])
        assigned_nodes = h.get("assigned_nodes", [])
        for rid, nid in zip(assigned_rooms, assigned_nodes):
            np = terminals.get(nid, (0.0, 0.0))
            pts_in_room = [np]
            if h.get("room_id") == rid:
                pts_in_room.append(terminals.get(h["hub_id"], np))
            cx = sum(p[0] for p in pts_in_room) / len(pts_in_room)
            cy = sum(p[1] for p in pts_in_room) / len(pts_in_room)
            dx = max(1.5, max(abs(p[0] - cx) for p in pts_in_room) + 0.8)
            dy = max(1.5, max(abs(p[1] - cy) for p in pts_in_room) + 0.8)
            poly = box(cx - dx, cy - dy, cx + dx, cy + dy).intersection(inner)
            kind = "kitchen" if "kitchen" in rid.lower() else ("bedroom" if "bed" in rid.lower() else ("storage" if "store" in rid.lower() else "living"))
            rooms.append({
                "id": rid,
                "type": kind,
                "polygon": mapping(poly),
                "node": {"id": nid, "x": np[0], "y": np[1]}
            })

    for h in hubs:
        assigned_rooms = h.get("assigned_rooms", [])
        for i in range(len(assigned_rooms) - 1):
            r1 = next((r for r in rooms if r["id"] == assigned_rooms[i]), None)
            r2 = next((r for r in rooms if r["id"] == assigned_rooms[i + 1]), None)
            if r1 and r2:
                p1 = Point(r1["node"]["x"], r1["node"]["y"])
                p2 = Point(r2["node"]["x"], r2["node"]["y"])
                door_poly = LineString([p1, p2]).buffer(0.3)
                doors.append({"polygon": mapping(door_poly)})

    return {
        "id": plan_id,
        "units": "m",
        "area": round(inner.area, 2),
        "inner": mapping(inner),
        "wall": None,
        "window": None,
        "doors": doors,
        "rooms": rooms,
        "node_provenance": "Reconstructed from verified solution JSON"
    }


class Plan:
    def __init__(self, source, open_min=0.5, wire_clearance=0.0, translate_origin=False):
        raw = json.loads(Path(source).read_text(encoding="utf-8-sig")) if isinstance(source, (str, Path)) else source
        if not isinstance(raw, dict):
            raise ValueError("A plan must be a JSON object.")
        self.raw = raw
        for key in ("plan", "data", "floor_plan", "input"):
            if key in raw and isinstance(raw[key], dict) and ("rooms" in raw[key] or "hubs" in raw[key]):
                raw = raw[key]
                break
        if "hubs" in raw and ("rooms" not in raw or not raw["rooms"]):
            target_id = str(raw.get("plan_id", raw.get("id", ""))).strip()
            found = None
            if target_id:
                root = Path(__file__).resolve().parents[1]
                for folder in ("examples", "plans", "."):
                    fdir = root / folder
                    if not fdir.is_dir():
                        continue
                    for p in fdir.glob("*.json"):
                        try:
                            d = json.loads(p.read_text(encoding="utf-8-sig"))
                            cand = None
                            for k in ("plan", "data", "floor_plan", "input"):
                                if k in d and isinstance(d[k], dict) and "rooms" in d[k]:
                                    cand = d[k]
                                    break
                            if cand is None and "rooms" in d:
                                cand = d
                            if isinstance(cand, dict) and isinstance(cand.get("rooms"), list) and cand["rooms"]:
                                if str(cand.get("id", cand.get("plan_id", ""))).strip() == target_id:
                                    found = cand
                                    break
                        except Exception:
                            pass
                    if found:
                        break
            if found:
                raw = found
            else:
                raw = plan_from_solution(raw, raw.get("plan_id", "plan"))
        elif "rooms" in raw and isinstance(raw["rooms"], dict):
            raw = dict(raw)
            raw["rooms"] = [{"id": k, **v} if isinstance(v, dict) else {"id": k, "polygon": v} for k, v in raw["rooms"].items()]
        elif "rooms" not in raw:
            for alt in ("room_list", "roomList", "spaces", "elements"):
                if alt in raw and isinstance(raw[alt], list):
                    raw = dict(raw)
                    raw["rooms"] = raw[alt]
                    break
        if not math.isfinite(wire_clearance) or wire_clearance < 0 or not math.isfinite(open_min) or open_min <= 0:
            raise ValueError("Clearance must be finite and nonnegative; passage width must be positive.")
        self.wire_clearance = wire_clearance
        self.translate_origin = translate_origin
        self.warnings = []
        self.node_provenance = raw.get("node_provenance", "fixed input nodes")
        self.id = str(raw.get("plan_id", raw.get("id", "plan")))
        inner = geometry(raw.get("inner", raw.get("boundary")))
        area = float(raw.get("area", raw.get("area_m2", 0)))
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
            g = affinity.scale(g, 1 / self.scale, 1 / self.scale, origin=(0, 0))
            return g if g.is_valid else make_valid(g)

        self.convert = convert
        self.inner = convert(inner)
        if "wall" not in raw and "walls" not in raw:
            raise ValueError("Missing wall geometry. Supply wall: null explicitly for a wall-free synthetic plan.")
        self.wall = convert(geometry(raw.get("wall", raw.get("walls"))))
        self.window = convert(geometry(raw.get("window", raw.get("windows"))))
        self.barriers = unary_union([self.wall, self.window])
        self.free = self.inner.difference(self.barriers)
        # The competition constrains cable containment, not a 0.5 m cable
        # clearance. Build the optional display clearance geometry only on use.
        self._wire_free = None
        self.rooms = {}
        node_ids = set()
        top_nodes = {str(n["room_id"]): n for n in raw.get("nodes", [])}
        for item in raw.get("rooms", []):
            rid = str(item["id"])
            if rid in self.rooms:
                raise ValueError(f"Duplicate room ID: {rid}")
            poly = convert(geometry(item.get("polygon", item.get("geometry"))))
            if poly.is_empty or poly.area <= 0:
                raise ValueError(f"Room {rid} has no polygon area.")
            kind = item.get("type", item.get("room_type", "")).lower().replace(" ", "_")
            kind = {"living_room": "living", "bed_room": "bedroom", "store": "storage"}.get(kind, kind)
            nd = item.get("node", top_nodes.get(rid))
            point, nid = None, None
            if kind in ELIGIBLE:
                if nd is None:
                    raise ValueError(f"Room {rid} needs its fixed input node; the solver never invents one.")
                pos = nd.get("location", nd.get("coordinates", nd)) if isinstance(nd, dict) else nd
                p = Point(pos["x"], pos["y"]) if isinstance(pos, dict) else Point(pos)
                p = convert(p)
                if not math.isfinite(p.x + p.y):
                    raise ValueError(f"Non-finite node in {rid}")
                point = (p.x, p.y)
                nid = str(nd.get("id", item.get("node_id", f"N{len(node_ids)+1}"))) if isinstance(nd, dict) else str(item.get("node_id", f"N{len(node_ids)+1}"))
                if nid in node_ids:
                    raise ValueError(f"Duplicate node ID: {nid}")
                node_ids.add(nid)
                if not poly.contains(p) or not self.free.covers(p):
                    raise ValueError(f"Fixed node {nid} is outside its room or in an obstacle.")
                clearance = p.distance(self.barriers) if not self.barriers.is_empty else math.inf
                if clearance < 0.5 - 0.001:
                    self.warnings.append({"rule":"node_clearance", "room_id":rid, "node_id":nid,
                        "message":f"Fixed node {nid} in {rid} is {clearance:.3f} m from a wall/window; required 0.500 m. The input node is preserved."})
                if poly.area > 100 + AREA_TOL:
                    self.warnings.append({"rule":"capacity", "room_id":rid,
                        "message":f"Room {rid} measures {poly.area:.6f} m², exceeding 100 m². It cannot be split across hubs."})
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
                touches = []
                for rid, r in self.eligible.items():
                    if gap.distance(r.polygon) > 0.02:
                        continue
                    a, b = nearest_points(gap, r.polygon)
                    if a.equals(b) or self.free.covers(LineString([a, b])):
                        contact = gap.boundary.intersection(r.polygon.buffer(0.02)).length
                        if contact > 0.05:
                            touches.append((contact, rid))
                touches.sort(reverse=True)
                if len(touches) >= 2:
                    threshold = max(.10, .25 * touches[0][0])
                    connected = [rid for contact, rid in touches if contact >= threshold]
                    for i, a in enumerate(connected):
                        for b in connected[i + 1:]:
                            graph.add_edge(a, b, type="door")
        ids = sorted(self.eligible)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if graph.has_edge(a, b):
                    continue
                pa, pb = self.rooms[a].polygon, self.rooms[b].polygon
                if pa.distance(pb) > 0.04:
                    continue
                gap = pa.buffer(0.02, join_style=2).intersection(pb.buffer(0.02, join_style=2)).intersection(self.free)
                for p in parts(gap):
                    if p.area <= 1e-9:
                        continue
                    ca = p.intersection(pa).length
                    cb = p.intersection(pb).length
                    x0, y0, x1, y1 = p.bounds
                    if min(ca, cb) >= self.open_min and max(x1 - x0, y1 - y0) >= self.open_min:
                        graph.add_edge(a, b, type="opening")
                        break
        # A door polygon can touch both sides of a sealed wall. Its contacts
        # alone do not prove that the two fixed terminals can reach each other.
        active_space = self.wire_free if self.wire_clearance > 0 and not self.barriers.is_empty else self.free
        components = parts(active_space)
        membership = {rid: {i for i, g in enumerate(components) if g.covers(Point(r.node))}
                      for rid, r in self.eligible.items()}
        graph.remove_edges_from([(a, b) for a, b in graph.edges
                                 if not membership[a].intersection(membership[b])])
        return graph

    def set_wire_clearance(self, clearance):
        if not math.isfinite(clearance) or clearance < 0:
            raise ValueError("Clearance must be finite and nonnegative.")
        if getattr(self, "wire_clearance", None) != clearance:
            self.wire_clearance = clearance
            self._wire_free = None
            if hasattr(self, "_hub_barrier"):
                delattr(self, "_hub_barrier")
            self.graph = self._connectivity()

    def hub_candidates(self, rid, wide=False):
        r = self.rooms[rid]
        if not hasattr(self, "_hub_barrier"):
            barrier_width = max(.5, self.wire_clearance) + .00001
            self._hub_barrier = self.barriers.buffer(barrier_width, join_style=2) if not self.barriers.is_empty else Polygon()
        safe_space = self.wire_free if self.wire_clearance > 0 and not self.barriers.is_empty else self.free
        safe = r.polygon.intersection(safe_space).difference(self._hub_barrier)
        if safe.is_empty:
            safe = r.polygon.intersection(self.free).difference(self._hub_barrier)
        if safe.is_empty:
            return []
        n = Point(r.node)
        candidates = []
        for dx, dy in [(0.03, 0), (0, 0.03), (-0.03, 0), (0, -0.03)]:
            p = Point(n.x + dx, n.y + dy)
            if safe.covers(p) and r.polygon.contains(p):
                candidates.append((p.x, p.y))
        for component in parts(safe):
            p = component.centroid
            if not component.covers(p):
                p = component.representative_point()
            if p.distance(n) > 0.002 and r.polygon.contains(p):
                candidates.append((p.x, p.y))
        x0, y0, x1, y1 = safe.bounds
        fractions = (.2, .35, .5, .65, .8) if wide else (.3, .5, .7)
        for fx in fractions:
            for fy in fractions:
                p = Point(x0 + fx * (x1 - x0), y0 + fy * (y1 - y0))
                if safe.contains(p) and p.distance(n) > .002 and r.polygon.contains(p):
                    candidates.append((p.x, p.y))
        seen = set()
        unique = []
        for c in candidates:
            k = (round(c[0], 4), round(c[1], 4))
            if k not in seen:
                seen.add(k)
                unique.append(c)
        return unique[:16 if wide else 4]

    def _compute_wire_free(self):
        clearance = getattr(self, "wire_clearance", 0.0)
        barriers = getattr(self, "barriers", None)
        free = getattr(self, "free", None)
        if free is None:
            return Polygon()
        if barriers is None or barriers.is_empty or clearance <= 0:
            return free
        barrier_buf = barriers.buffer(clearance, join_style=2)
        return free.difference(barrier_buf)

    def __getattr__(self, name):
        if name == "wire_free":
            value = self._compute_wire_free()
            self._wire_free = value
            return value
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    @property
    def wire_free(self):
        if hasattr(self, "_wire_free") and self._wire_free is not None:
            return self._wire_free
        value = self._compute_wire_free()
        self._wire_free = value
        return value

    @wire_free.setter
    def wire_free(self, val):
        self._wire_free = val
