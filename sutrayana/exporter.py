"""Raw ResPlan adapter. Generated nodes are DEMO inputs, never competition inputs."""
import math
from shapely.geometry import mapping, MultiPolygon
from shapely.ops import unary_union
from .model import geometry, parts, ELIGIBLE


def extract_rooms_and_doors(plan, plan_id="plan_0"):
    inner = geometry(plan["inner"])
    scale = math.sqrt(inner.area / float(plan["area"]))
    free = inner.difference(unary_union([geometry(plan.get("wall")),geometry(plan.get("window"))]))
    rooms = []
    for kind in ["living", "bedroom", "kitchen", "storage", "bathroom", "balcony", "stair"]:
        for poly in parts(geometry(plan.get(kind))):
            if poly.geom_type != "Polygon" or poly.is_empty:
                continue
            rid = f"R{len(rooms)+1:02d}_{kind}"
            room = {"id":rid, "type":kind, "polygon":mapping(poly), "area":poly.area/scale**2}
            if kind in ELIGIBLE:
                safe = poly.buffer(-0.50001*scale).intersection(free.buffer(-.001*scale))
                if safe.is_empty:
                    raise ValueError(f"Benchmark-ineligible room {rid}: no node with 0.5 m clearance")
                if isinstance(safe,MultiPolygon):
                    safe = max(safe.geoms,key=lambda g:g.area)
                node = safe.centroid if safe.contains(safe.centroid) else safe.representative_point()
                room["node"] = {"id":f"N{sum(r['type'] in ELIGIBLE for r in rooms)+1}", "x":node.x,"y":node.y}
            rooms.append(room)
    return {"id":str(plan.get("id",plan_id)), "area":float(plan["area"]), "inner":mapping(inner),
            "rooms":rooms, "doors":[{"id":f"D{i+1}","polygon":mapping(p)} for i,p in enumerate(parts(geometry(plan.get("door"))))],
            "wall":mapping(geometry(plan.get("wall"))), "window":mapping(geometry(plan.get("window"))),
            "front_door":mapping(geometry(plan.get("front_door"))),
            "node_provenance":"generated demo nodes; not organiser benchmark nodes",
            "coordinate_system":{"y_axis":"up"}}
