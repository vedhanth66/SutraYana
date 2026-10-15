import sys, os
sys.path.insert(0, os.path.abspath('.'))
import pickle, math
from export_resplan_to_json import extract_rooms_and_doors
from phase4_routing import build_orthogonal_grid, a_star_orthogonal, get_node_grid_and_stub, compress_orthogonal_path, calculate_ring_metrics, verify_no_wall_crossings
from phase1_pipeline import load_and_process_plan
from phase2_partition import run_phase2, find_best_hub_in_component
from phase3_sequencing import find_optimal_sequence
import numpy as np
import networkx as nx

with open('ResPlan/ResPlan/ResPlan.pkl', 'rb') as f:
    data = pickle.load(f)

for plan_idx in [713, 3963, 1703, 192]:
    p = extract_rooms_and_doors(data[plan_idx], plan_id=f'plan_{plan_idx:05d}')
    G, nodes_dict_units, scale, min_hubs = load_and_process_plan(p, verbose=False)
    best_hubs, _ = run_phase2(p, plan_data=(G, nodes_dict_units, scale, min_hubs), verbose=False)
    grid_info = build_orthogonal_grid(p, scale, resolution=0.08)
    inv_s = 1.0 / scale
    nodes_m = {r_id: (round(pt.x * inv_s, 4), round(pt.y * inv_s, 4)) for r_id, pt in nodes_dict_units.items()}
    minx, miny, res = grid_info["minx"], grid_info["miny"], grid_info["res"]
    H, W = grid_info["H"], grid_info["W"]

    for hub_room, assigned_rooms in sorted(best_hubs.items()):
        best_r, _ = find_best_hub_in_component(G, assigned_rooms, nodes_dict_units, scale)
        if len(assigned_rooms) <= 1:
            continue

        from phase4_routing import compute_pairwise_physical_distances
        pairwise_dist, pair_paths = compute_pairwise_physical_distances(grid_info, nodes_m, assigned_rooms, G=G)
        seq, _ = find_optimal_sequence(G, best_r, list(assigned_rooms), pairwise_dist=pairwise_dist, pair_paths=pair_paths)

        # PASS 1: Sequential routing
        protected_cells = set()
        for pt_m in nodes_m.values():
            ngx = int(round((pt_m[0] - minx) / res))
            ngy = int(round((pt_m[1] - miny) / res))
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    protected_cells.add((ngx + dx, ngy + dy))

        cable_usage = {
            "grid_h_usage": np.zeros((H, W), dtype=np.int16),
            "grid_v_usage": np.zeros((H, W), dtype=np.int16),
            "protected_cells": protected_cells,
            "used_vertices": set()
        }

        node_stubs = {r: get_node_grid_and_stub(nodes_m[r], r, grid_info) for r in set(seq)}
        legs_grid = []
        legs_raw = []

        def add_leg_to_usage(grid_pts):
            for k in range(len(grid_pts) - 1):
                x1, y1 = grid_pts[k]
                x2, y2 = grid_pts[k + 1]
                gx1 = int(round((x1 - minx) / res))
                gy1 = int(round((y1 - miny) / res))
                gx2 = int(round((x2 - minx) / res))
                gy2 = int(round((y2 - miny) / res))
                if gy1 == gy2 and 0 <= gy1 < H and 0 <= min(gx1, gx2) < W:
                    cable_usage["grid_h_usage"][gy1, min(gx1, gx2)] += 1
                elif gx1 == gx2 and 0 <= gx1 < W and 0 <= min(gy1, gy2) < H:
                    cable_usage["grid_v_usage"][min(gy1, gy2), gx1] += 1
            for pt in grid_pts:
                gx = int(round((pt[0] - minx) / res))
                gy = int(round((pt[1] - miny) / res))
                cable_usage["used_vertices"].add((gx, gy))

        def remove_leg_from_usage(grid_pts):
            for k in range(len(grid_pts) - 1):
                x1, y1 = grid_pts[k]
                x2, y2 = grid_pts[k + 1]
                gx1 = int(round((x1 - minx) / res))
                gy1 = int(round((y1 - miny) / res))
                gx2 = int(round((x2 - minx) / res))
                gy2 = int(round((y2 - miny) / res))
                if gy1 == gy2 and 0 <= gy1 < H and 0 <= min(gx1, gx2) < W:
                    cable_usage["grid_h_usage"][gy1, min(gx1, gx2)] = max(0, cable_usage["grid_h_usage"][gy1, min(gx1, gx2)] - 1)
                elif gx1 == gx2 and 0 <= gx1 < W and 0 <= min(gy1, gy2) < H:
                    cable_usage["grid_v_usage"][min(gy1, gy2), gx1] = max(0, cable_usage["grid_v_usage"][min(gy1, gy2), gx1] - 1)

        # PASS 1
        for i in range(len(seq) - 1):
            u, v = seq[i], seq[i + 1]
            Gu, stub_to_u = node_stubs[u]
            Gv, stub_to_v = node_stubs[v]
            stub_from_u = list(reversed(stub_to_u))
            grid_pts = a_star_orthogonal(grid_info, Gu, Gv, cable_usage=cable_usage)
            legs_grid.append(grid_pts)
            leg_raw = stub_from_u + grid_pts[1:] + stub_to_v[1:]
            legs_raw.append(leg_raw)
            add_leg_to_usage(grid_pts)

        # Build full polyline Pass 1
        full_p1 = []
        for i, l_raw in enumerate(legs_raw):
            full_p1.extend(l_raw if i == 0 else l_raw[1:])
        comp_p1 = compress_orthogonal_path(full_p1)
        m1 = calculate_ring_metrics(comp_p1)

        # PASS 2: Rip-up and reroute
        for i in range(len(seq) - 1):
            u, v = seq[i], seq[i + 1]
            Gu, stub_to_u = node_stubs[u]
            Gv, stub_to_v = node_stubs[v]
            stub_from_u = list(reversed(stub_to_u))

            remove_leg_from_usage(legs_grid[i])
            new_grid = a_star_orthogonal(grid_info, Gu, Gv, cable_usage=cable_usage)
            if new_grid is not None:
                legs_grid[i] = new_grid
                legs_raw[i] = stub_from_u + new_grid[1:] + stub_to_v[1:]
            add_leg_to_usage(legs_grid[i])

        full_p2 = []
        for i, l_raw in enumerate(legs_raw):
            full_p2.extend(l_raw if i == 0 else l_raw[1:])
        comp_p2 = compress_orthogonal_path(full_p2)
        m2 = calculate_ring_metrics(comp_p2)

        print(f"Plan #{plan_idx:05d} Hub [{best_r}]:")
        print(f"  Pass 1: L={m1['L']}m, B={m1['B']}, O={m1['O']}m, X={m1['X']}, J={m1['J']}")
        print(f"  Pass 2: L={m2['L']}m, B={m2['B']}, O={m2['O']}m, X={m2['X']}, J={m2['J']}")

