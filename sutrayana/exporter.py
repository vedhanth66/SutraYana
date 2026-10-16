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
