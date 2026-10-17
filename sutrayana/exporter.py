"""Raw ResPlan adapter. Generated nodes are DEMO inputs, never competition inputs."""
import math
from shapely.geometry import mapping, MultiPolygon, Point
from shapely.ops import unary_union
from .model import geometry, parts, ELIGIBLE


class BenchmarkIneligible(ValueError):
    """Raw dataset record cannot supply the challenge's benchmark inputs."""
    def __init__(self, message, reason):
        super().__init__(message)
        self.reason = reason


def extract_rooms_and_doors(plan, plan_id="plan_0"):
    inner = geometry(plan["inner"])
    scale = math.sqrt(inner.area / float(plan["area"]))
    barriers = unary_union([geometry(plan.get("wall")),geometry(plan.get("window"))])
    free = inner.difference(barriers)
    free_interior = free.buffer(-.001*scale)
    wall_safe = None
    rooms = []
    for kind in ["living", "bedroom", "kitchen", "storage", "bathroom", "balcony", "stair"]:
        for poly in parts(geometry(plan.get(kind))):
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            rid = f"R{len(rooms)+1:02d}_{kind}"
            room = {"id":rid, "type":kind, "polygon":mapping(poly), "area":poly.area/scale**2}
            if kind in ELIGIBLE:
                if room["area"] > 100+1e-8:
                    raise BenchmarkIneligible(f"Room {rid} exceeds the 100 m² capacity limit.", "room_capacity")
                safe = poly.buffer(-0.50001*scale).intersection(free_interior)
                if safe.is_empty:
                    # Room borders across open space are not walls. Retain the
                    # historical node whenever possible; only repair rejected
                    # demo inputs, never move organiser-provided fixed nodes.
                    if wall_safe is None:
                        wall_safe = free.difference(barriers.buffer(.50001*scale))
                    safe = poly.buffer(-.001*scale).intersection(wall_safe)
                if safe.is_empty:
                    raise BenchmarkIneligible(f"Benchmark-ineligible room {rid}: no node with 0.5 m wall clearance", "node_clearance")
                if isinstance(safe,MultiPolygon):
                    safe = max(safe.geoms,key=lambda g:g.area)
                node = safe.centroid if safe.contains(safe.centroid) else safe.representative_point()
                if not barriers.is_empty and node.distance(barriers) < .499*scale:
                    if wall_safe is None:
                        wall_safe = free.difference(barriers.buffer(.50001*scale))
                    safe = poly.buffer(-.001*scale).intersection(wall_safe)
                    if safe.is_empty:
                        raise BenchmarkIneligible(f"Benchmark-ineligible room {rid}: no node with 0.5 m wall clearance", "node_clearance")
                    node = safe.representative_point()
                previous = [Point(r["node"]["x"], r["node"]["y"]) for r in rooms if "node" in r]
                if any(node.distance(p) < .002*scale for p in previous):
                    safe = safe.difference(unary_union([p.buffer(.004*scale) for p in previous]))
                    if safe.is_empty:
                        raise BenchmarkIneligible(f"Benchmark-ineligible room {rid}: no distinct demo node", "node_separation")
                    node = safe.representative_point()
                room["node"] = {"id":f"N{sum(r['type'] in ELIGIBLE for r in rooms)+1}", "x":node.x,"y":node.y}
            rooms.append(room)
    return {"id":str(plan.get("id",plan_id)), "area":float(plan["area"]), "inner":mapping(inner),
            "rooms":rooms, "doors":[{"id":f"D{i+1}","polygon":mapping(p)} for i,p in enumerate(parts(geometry(plan.get("door"))))],
            "wall":mapping(geometry(plan.get("wall"))), "window":mapping(geometry(plan.get("window"))),
            "front_door":mapping(geometry(plan.get("front_door"))),
            "node_provenance":"generated demo nodes; not organiser benchmark nodes",
            "coordinate_system":{"y_axis":"up"}}


def format_official_submission(plan, solution, report=None):
    """
    Format output matching Slide 8 of the challenge deck:
    - Coordinates in physical metres, lower-left origin, y up.
    - Structure:
        {
          "plan_id": "...",
          "units": "m",
          "hubs": [
            {
              "hub_id": "H1",
              "room_id": "...",
              "location": {"x": 5.2, "y": 3.6},
              "assigned_rooms": ["...", ...],
              "assigned_nodes": ["...", ...],
              "closed_sequence": ["H1", "N1", ...],
              "route_segments": [
                {"from": "H1", "to": "N1", "length_m": 4.8, "polyline": [[x, y], ...]}
              ],
              "ring_length_m": 23.8
            }
          ],
          "reported_metrics": {
            "hub_count": 2,
            "total_length_m": 49.0,
            "crossings": 0,
            "overlap_m": 0.0,
            "bends": 8,
            "total_cost_J": 53.0
          }
        }
    """
    hubs_out = []
    for h in solution.get("hubs", []):
        loc = h.get("location", {})
        if isinstance(loc, (list, tuple)):
            loc_dict = {"x": round(float(loc[0]), 3), "y": round(float(loc[1]), 3)}
        elif isinstance(loc, dict):
            loc_dict = {"x": round(float(loc.get("x", 0)), 3), "y": round(float(loc.get("y", 0)), 3)}
        else:
            loc_dict = {"x": 0.0, "y": 0.0}

        segs_out = []
        for s in h.get("route_segments", []):
            segs_out.append({
                "from": s.get("from", s.get("from_id")),
                "to": s.get("to", s.get("to_id")),
                "length_m": round(float(s.get("length_m", 0.0)), 3),
                "polyline": [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in s.get("polyline", [])]
            })

        hubs_out.append({
            "hub_id": h.get("hub_id"),
            "room_id": h.get("room_id"),
            "location": loc_dict,
            "assigned_rooms": sorted(list(h.get("assigned_rooms", []))),
            "assigned_nodes": sorted(list(h.get("assigned_nodes", []))),
            "closed_sequence": list(h.get("closed_sequence", [])),
            "route_segments": segs_out,
            "ring_length_m": round(float(h.get("ring_length_m", 0.0)), 3)
        })

    rep = dict(solution.get("reported_metrics", {}))
    return {
        "plan_id": str(solution.get("plan_id", getattr(plan, "id", "plan"))),
        "units": "m",
        "hubs": hubs_out,
        "reported_metrics": rep
    }


def export_provisional_submission(plan, solution):
    """Provisional submission export following Slide 8 format with explicit coordinate metadata."""
    sub = format_official_submission(plan, solution)
    return {
        "format": "hackhive-provisional-metre-export-v0.1",
        "plan_id": sub["plan_id"],
        "coordinate_system": {
            "unit": "metre",
            "origin": "internal_boundary_lower_left",
            "y_axis": "up"
        },
        "hubs": sub["hubs"],
        "reported_metrics": sub["reported_metrics"]
    }


_RESPLAN_DATA = None
_RESPLAN_ID_MAP = None


def lookup_resplan_by_id_or_stem(target_id=None, stem=None):
    """Attempt to find a plan record in ResPlan.pkl by ID (e.g. '7108') or stem (e.g. 'plan_09012')."""
    global _RESPLAN_DATA, _RESPLAN_ID_MAP
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "ResPlan" / "ResPlan" / "ResPlan.pkl",
        root / "ResPlan" / "ResPlan.pkl",
        root.parent / "ResPlan.pkl",
    ]
    pkl_file = None
    for cand in candidates:
        if cand.is_file():
            pkl_file = cand
            break
    if not pkl_file:
        return None

    if _RESPLAN_DATA is None:
        try:
            import pickle
            with open(pkl_file, "rb") as f:
                _RESPLAN_DATA = pickle.load(f)
        except Exception:
            return None

    if _RESPLAN_ID_MAP is None and _RESPLAN_DATA:
        _RESPLAN_ID_MAP = {}
        for i, item in enumerate(_RESPLAN_DATA):
            if isinstance(item, dict):
                pid = str(item.get("id", item.get("plan_id", ""))).strip()
                if pid:
                    _RESPLAN_ID_MAP[pid] = i

    target_idx = None
    # 1. Try numeric index from stem (e.g. 'plan_09012' -> 9012)
    if stem:
        m = re.search(r"(\d+)", stem)
        if m:
            idx = int(m.group(1))
            if 0 <= idx < len(_RESPLAN_DATA):
                item = _RESPLAN_DATA[idx]
                item_id = str(item.get("id", item.get("plan_id", ""))).strip()
                if not target_id or item_id == str(target_id).strip():
                    target_idx = idx

    # 2. Try target_id in map
    if target_idx is None and target_id and _RESPLAN_ID_MAP:
        target_idx = _RESPLAN_ID_MAP.get(str(target_id).strip())

    # 3. Try integer target_id as index directly
    if target_idx is None and target_id and str(target_id).strip().isdigit():
        idx = int(target_id)
        if 0 <= idx < len(_RESPLAN_DATA):
            item = _RESPLAN_DATA[idx]
            if str(item.get("id", "")) == str(target_id).strip():
                target_idx = idx

    if target_idx is not None and 0 <= target_idx < len(_RESPLAN_DATA):
        try:
            raw_record = _RESPLAN_DATA[target_idx]
            extracted = extract_rooms_and_doors(raw_record, plan_id=stem or f"plan_{target_idx:05d}")
            return extracted
        except Exception:
            return None

    return None
