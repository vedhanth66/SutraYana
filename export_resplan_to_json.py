import os
import sys
import json
import math
import pickle
import itertools
from shapely.geometry import mapping, Polygon, MultiPolygon
from shapely.ops import unary_union
import shapely.affinity


def extract_rooms_and_doors(plan, plan_id="plan_0"):
    """
    Extracts rooms, nodes, doors, and metadata from a ResPlan pickle dict
    and formats them into the standard ResPlan JSON schema.
    Converts room areas to square metres (m²) using scale = sqrt(inner.area / area).
    Detects both explicit door polygons and open passages (e.g. open-concept kitchens).
    """
    all_types = ["living", "bedroom", "kitchen", "storage", "bathroom", "balcony"]
    rooms_data = []
    room_geoms = {}

    inner = plan.get("inner")
    inner_area = float(inner.area) if inner is not None else 0.0
    inner_geojson = mapping(inner) if inner is not None else {}
    plan_area_m2 = float(plan.get("area", 100.0))

    if inner_area > 0 and plan_area_m2 > 0:
        scale = math.sqrt(inner_area / plan_area_m2)
    else:
        scale = 1.0

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
            # Deterministic fixed node interior point (0.5m clearance in unit coordinates)
            clearance_units = max(0.5 * scale, 1.0)
            eroded = p.buffer(-clearance_units)
            if not eroded.is_empty:
                if isinstance(eroded, MultiPolygon):
                    eroded = max(eroded.geoms, key=lambda poly: poly.area)
                pt = eroded.centroid if eroded.contains(eroded.centroid) else eroded.representative_point()
            else:
                pt = p.representative_point()

            # Room area converted to m²
            room_area_m2 = float(p.area) / (scale ** 2)

            rooms_data.append({
                "id": rid,
                "type": rtype,
                "area": round(room_area_m2, 4),
                "area_units2": round(float(p.area), 2),
                "polygon": mapping(p),
                "centroid": {"x": round(centroid.x, 3), "y": round(centroid.y, 3)},
                "node": {"x": round(pt.x, 3), "y": round(pt.y, 3)}
            })

    # 1. Doors extraction from explicit door polygons (buffered by 0.15m)
    doors_data = []
    connected_pairs = set()
    door_geom = plan.get("door")
    front_door_geom = plan.get("front_door")
    wall_geom = plan.get("wall")
    barriers_list = [g for g in [wall_geom, front_door_geom] if g is not None and not g.is_empty]
    barrier = unary_union(barriers_list) if barriers_list else None

    d_idx = 1
    if door_geom is not None and not door_geom.is_empty:
        door_polys = [door_geom] if isinstance(door_geom, Polygon) else list(door_geom.geoms) if isinstance(door_geom, MultiPolygon) else []
        
        for dpoly in door_polys:
            if dpoly.is_empty:
                continue

            # Buffer door by 0.15m to reliably capture wall thickness contacts
            d_buf = dpoly.buffer(max(0.15 * scale, 2.0))

            # Compute contact metrics with each room to prevent corner-clipping slivers
            # from falsely linking unrelated rooms or blocking open-concept passages
            min_contact_area = 0.04 * (scale ** 2)
            room_contacts = []
            for rid, rpoly in room_geoms.items():
                if d_buf.intersects(rpoly):
                    inter = d_buf.intersection(rpoly)
                    room_contacts.append((rid, inter.area, inter.length))

            touching = [rid for rid, area, length in room_contacts if area >= min_contact_area]
            if len(touching) < 2 and len(room_contacts) >= 2:
                # Fallback: top 2 rooms with largest contact area
                sorted_contacts = sorted(room_contacts, key=lambda x: x[1], reverse=True)
                touching = [sorted_contacts[0][0], sorted_contacts[1][0]]

            if len(touching) >= 2:
                for ra, rb in itertools.combinations(touching, 2):
                    pair_key = (min(ra, rb), max(ra, rb))
                    if pair_key not in connected_pairs:
                        doors_data.append({
                            "id": f"D{d_idx:02d}",
                            "room_a": ra,
                            "room_b": rb,
                            "polygon": mapping(dpoly)
                        })
                        connected_pairs.add(pair_key)
                        d_idx += 1

    # 2. Open-concept passages and adjacent rooms (touching or within 0.15m without barrier)
    rids = list(room_geoms.keys())
    prox_thresh = max(0.15 * scale, 2.0)
    for i in range(len(rids)):
        for j in range(i + 1, len(rids)):
            ra, rb = rids[i], rids[j]
            pair_key = (min(ra, rb), max(ra, rb))
            if pair_key in connected_pairs:
                continue
            pa, pb = room_geoms[ra], room_geoms[rb]
            
            # Check contact or proximity within 0.15m
            if pa.intersects(pb) or pa.distance(pb) <= prox_thresh:
                shared = pa.buffer(prox_thresh).intersection(pb.buffer(prox_thresh))
                if not shared.is_empty:
                    if barrier is not None and not barrier.is_empty:
                        open_part = shared.difference(barrier)
                    else:
                        open_part = shared

                    # Require at least minimal opening width
                    min_opening_area = 0.05 * (scale ** 2)
                    if not open_part.is_empty and (open_part.area >= min_opening_area or open_part.length / scale >= 0.3):
                        pas_poly = open_part.buffer(scale * 0.1) if hasattr(open_part, 'buffer') else open_part
                        doors_data.append({
                            "id": f"D{d_idx:02d}",
                            "room_a": ra,
                            "room_b": rb,
                            "polygon": mapping(pas_poly)
                        })
                        connected_pairs.add(pair_key)
                        d_idx += 1

    return {
        "id": str(plan.get("id", plan_id)),
        "area": plan_area_m2,
        "inner": {
            "area": inner_area,
            "polygon": inner_geojson
        },
        "rooms": rooms_data,
        "doors": doors_data,
        "wall": mapping(wall_geom) if wall_geom is not None and not wall_geom.is_empty else None
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
