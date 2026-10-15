import os
import sys
import json
import math
import pickle
from shapely.geometry import mapping, Polygon, MultiPolygon
from shapely.ops import unary_union
import shapely.affinity


def extract_rooms_and_doors(plan, plan_id="plan_0"):
    """
    Extracts rooms, nodes, doors, and metadata from a ResPlan pickle dict
    and formats them into the standard ResPlan JSON schema for Phase 1.
    """
    all_types = ["living", "bedroom", "kitchen", "storage", "bathroom", "balcony"]
    rooms_data = []
    room_geoms = {}

    inner = plan.get("inner")
    inner_area = float(inner.area) if inner is not None else 0.0
    inner_geojson = mapping(inner) if inner is not None else {}

    r_count = 1
    for rtype in all_types:
        geom = plan.get(rtype)
        if geom is None or geom.is_empty:
            continue
        
        polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms) if isinstance(geom, MultiPolygon) else []
        for p in polys:
            if p.is_empty or p.area < 1e-4:
                continue
            rid = f"R{r_count:02d}_{rtype}"
            r_count += 1
            room_geoms[rid] = p

            centroid = p.centroid
            # Deterministic fixed node interior point
            eroded = p.buffer(-max(p.length * 0.02, 1.0))
            if not eroded.is_empty:
                pt = eroded.centroid if eroded.contains(eroded.centroid) else eroded.representative_point()
            else:
                pt = p.representative_point()

            rooms_data.append({
                "id": rid,
                "type": rtype,
                "area": float(p.area),
                "polygon": mapping(p),
                "centroid": {"x": round(centroid.x, 3), "y": round(centroid.y, 3)},
                "node": {"x": round(pt.x, 3), "y": round(pt.y, 3)}
            })

    # Doors extraction and robust geometric room association
    doors_data = []
    door_geom = plan.get("door")
    if door_geom is not None and not door_geom.is_empty:
        door_polys = [door_geom] if isinstance(door_geom, Polygon) else list(door_geom.geoms) if isinstance(door_geom, MultiPolygon) else []
        
        d_idx = 1
        for dpoly in door_polys:
            if dpoly.is_empty:
                continue

            # 1. Direct boundary touch or intersection test
            direct = []
            for rid, rpoly in room_geoms.items():
                if dpoly.intersects(rpoly) or dpoly.touches(rpoly):
                    direct.append(rid)

            if len(direct) == 2:
                r_a, r_b = direct[0], direct[1]
            else:
                # 2. Adaptive scale-aware contact scoring for doors spanning wall thickness
                minx, miny, maxx, maxy = dpoly.bounds
                diag = max(math.hypot(maxx - minx, maxy - miny), 2.0)
                tol = max(diag * 0.25, 1.5)
                
                scored = []
                d_bound = dpoly.boundary
                for rid, rpoly in room_geoms.items():
                    try:
                        r_buf = rpoly.buffer(tol)
                        if dpoly.intersects(r_buf):
                            c_len = d_bound.intersection(r_buf).length
                            scored.append((rid, c_len))
                    except Exception:
                        pass

                scored.sort(key=lambda x: x[1], reverse=True)
                if len(scored) >= 2 and scored[1][1] > 1e-4:
                    r_a, r_b = scored[0][0], scored[1][0]
                elif len(direct) >= 2:
                    r_a, r_b = direct[0], direct[1]
                else:
                    continue

            doors_data.append({
                "id": f"D{d_idx:02d}",
                "room_a": r_a,
                "room_b": r_b,
                "polygon": mapping(dpoly)
            })
            d_idx += 1

    return {
        "id": str(plan.get("id", plan_id)),
        "area": float(plan.get("area", 100.0)),
        "inner": {
            "area": inner_area,
            "polygon": inner_geojson
        },
        "rooms": rooms_data,
        "doors": doors_data
    }


def export_single_plan(pkl_path, output_json="resplan_sample.json", plan_index=0):
    print(f"Loading {pkl_path}...")
    with open(pkl_path, 'rb') as f:
        data = pickle.load(f)

    if isinstance(data, dict):
        plan = data[list(data.keys())[plan_index]]
    else:
        plan = data[plan_index]

    formatted = extract_rooms_and_doors(plan, plan_id=f"plan_{plan_index}")
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(formatted, f, indent=2)

    print(f"Successfully exported plan {plan_index} to {output_json}")


if __name__ == "__main__":
    pkl_file = sys.argv[1] if len(sys.argv) > 1 else "../SutraYana_temp/ResPlan/ResPlan.pkl"
    out_file = sys.argv[2] if len(sys.argv) > 2 else "resplan_sample.json"
    idx = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    export_single_plan(pkl_file, out_file, idx)
