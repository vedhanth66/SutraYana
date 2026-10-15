import os
import sys
import json
import math
import heapq
import tempfile
from collections import defaultdict

os.environ.setdefault('MPLCONFIGDIR', tempfile.gettempdir())
import numpy as np
import cv2
import matplotlib.pyplot as plt
from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely import affinity

import networkx as nx

from phase1_pipeline import load_and_process_plan
from phase2_partition import run_phase2
from phase3_sequencing import find_optimal_sequence, run_phase3


def expand_door_across_wall(dpoly, expand_m=0.10):
    """
    Expands a door polygon strictly across the wall thickness (its short dimension)
    while preserving its exact opening bounds along the wall (its long dimension).
    This ensures door passages fully penetrate 15cm walls without leaking into wall frames.
    """
    from shapely.geometry import box
    minx, miny, maxx, maxy = dpoly.bounds
    dx = maxx - minx
    dy = maxy - miny
    if dx <= dy:
        # Vertical wall door (wall is vertical): expand X across wall, keep Y opening intact
        return box(minx - expand_m, miny, maxx + expand_m, maxy)
    else:
        # Horizontal wall door (wall is horizontal): expand Y across wall, keep X opening intact
        return box(minx, miny - expand_m, maxx, maxy + expand_m)


def build_orthogonal_grid(plan, scale, resolution=0.05):
    """
    Builds a 2D metric grid (resolution in metres) over the floor plan.
    - All coordinates and polygons are converted to METRES using 1.0 / scale.
    - Room interiors are marked as walkable.
    - Room boundaries are marked as walls (obstacles) with thickness=3 to prevent micro-gaps.
    - Door passages are carved strictly within the door opening bounds along the wall,
      and expanded across the wall thickness (max(0.35m, 3*res)) to fully breach walls up to 30cm.
    - Precomputes room_masks, door_cell_bounds, and room_pair_doors for topological corridor routing.
    - Constructs Shapely wall barriers (room boundaries minus exact carved passages) for strict verification.
    """
    inv_s = 1.0 / scale

    rooms_m = {}
    for r in plan.get("rooms", []):
        p = shape(r["polygon"])
        rooms_m[r["id"]] = affinity.scale(p, inv_s, inv_s, origin=(0, 0))

    doors_m = []
    for d in plan.get("doors", []):
        dp = shape(d["polygon"])
        doors_m.append(affinity.scale(dp, inv_s, inv_s, origin=(0, 0)))

    all_geoms = list(rooms_m.values()) + doors_m
    minx = min(g.bounds[0] for g in all_geoms)
    miny = min(g.bounds[1] for g in all_geoms)
    maxx = max(g.bounds[2] for g in all_geoms)
    maxy = max(g.bounds[3] for g in all_geoms)

    W = int(math.ceil((maxx - minx) / resolution)) + 1
    H = int(math.ceil((maxy - miny) / resolution)) + 1

    # 1. Rasterize room interiors and store individual room masks
    house_mask = np.zeros((H, W), dtype=np.uint8)
    room_masks = {}
    for rid, g in rooms_m.items():
        rmask = np.zeros((H, W), dtype=bool)
        polys = g.geoms if hasattr(g, 'geoms') else [g]
        for p in polys:
            ext = p.exterior.coords[:-1]
            pts = np.array([[(x - minx) / resolution, (y - miny) / resolution] for x, y in ext], dtype=np.int32)
            cv2.fillPoly(house_mask, [pts], 1)
            cv2.fillPoly(rmask.view(np.uint8), [pts], 1)
        room_masks[rid] = rmask

    # 2. Rasterize walls from room boundaries with thickness=3 (15-24cm) to close micro-gaps
    wall_mask = np.zeros((H, W), dtype=np.uint8)
    for g in rooms_m.values():
        polys = g.geoms if hasattr(g, 'geoms') else [g]
        for p in polys:
            ext = p.exterior.coords[:-1]
            pts = np.array([[(x - minx) / resolution, (y - miny) / resolution] for x, y in ext], dtype=np.int32)
            cv2.polylines(wall_mask, [pts], isClosed=True, color=1, thickness=3)

    # 3. Carve out door passages through walls
    # Expand strictly across wall thickness (short dimension) to punch through 15-30cm walls
    # while preserving strict inner bounds along the door opening so no cell spills into wall frames
    carved_door_geoms = []
    door_cell_bounds = {}
    room_pair_doors = defaultdict(list)
    expand_m = max(0.35, resolution * 3.0)

    for d in plan.get("doors", []):
        d_id = d.get("id")
        r_a = d.get("room_a")
        r_b = d.get("room_b")
        if r_a and r_b:
            room_pair_doors[(r_a, r_b)].append(d_id)
            room_pair_doors[(r_b, r_a)].append(d_id)

        dp = shape(d["polygon"])
        dp_m = affinity.scale(dp, inv_s, inv_s, origin=(0, 0))
        polys = dp_m.geoms if hasattr(dp_m, 'geoms') else [dp_m]
        for p in polys:
            from shapely.geometry import box
            d_minx, d_miny, d_maxx, d_maxy = p.bounds
            dx = d_maxx - d_minx
            dy = d_maxy - d_miny
            if dx <= dy:
                # Vertical wall: opening along Y, thickness along X
                # Along opening (Y): strict inner bounds
                gy_start = int(math.ceil((d_miny - miny) / resolution))
                gy_end = int(math.floor((d_maxy - miny) / resolution))
                if gy_start > gy_end:
                    gy_start = gy_end = int(round((0.5 * (d_miny + d_maxy) - miny) / resolution))
                # Across thickness (X): expanded
                gx_start = int(math.floor((d_minx - expand_m - minx) / resolution))
                gx_end = int(math.ceil((d_maxx + expand_m - minx) / resolution))
            else:
                # Horizontal wall: opening along X, thickness along Y
                # Along opening (X): strict inner bounds
                gx_start = int(math.ceil((d_minx - minx) / resolution))
                gx_end = int(math.floor((d_maxx - minx) / resolution))
                if gx_start > gx_end:
                    gx_start = gx_end = int(round((0.5 * (d_minx + d_maxx) - minx) / resolution))
                # Across thickness (Y): expanded
                gy_start = int(math.floor((d_miny - expand_m - miny) / resolution))
                gy_end = int(math.ceil((d_maxy + expand_m - miny) / resolution))

            gx_start = max(0, gx_start)
            gx_end = min(W - 1, gx_end)
            gy_start = max(0, gy_start)
            gy_end = min(H - 1, gy_end)

            wall_mask[gy_start:gy_end + 1, gx_start:gx_end + 1] = 0
            house_mask[gy_start:gy_end + 1, gx_start:gx_end + 1] = 1

            if d_id:
                door_cell_bounds[d_id] = (gx_start, gx_end, gy_start, gy_end)

            carved_box = box(
                minx + gx_start * resolution - 1e-4,
                miny + gy_start * resolution - 1e-4,
                minx + (gx_end + 1) * resolution + 1e-4,
                miny + (gy_end + 1) * resolution + 1e-4
            )
            carved_door_geoms.append(carved_box)

    walkable = (house_mask == 1) & (wall_mask == 0)

    # 4. Construct Shapely wall barriers for strict post-routing geometric verification
    room_bounds = []
    for r in rooms_m.values():
        polys = r.geoms if hasattr(r, 'geoms') else [r]
        for p in polys:
            room_bounds.append(p.boundary)
    boundaries_union = unary_union(room_bounds)

    doors_carve_union = unary_union(carved_door_geoms) if carved_door_geoms else None
    if doors_carve_union is not None and not doors_carve_union.is_empty:
        # Wall barriers = boundaries minus the exact door passages that were carved
        wall_barriers = boundaries_union.difference(doors_carve_union)
    else:
        wall_barriers = boundaries_union

    grid_info = {
        "walkable": walkable,
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
        "W": W,
        "H": H,
        "res": resolution,
        "rooms_m": rooms_m,
        "doors_m": doors_m,
        "room_masks": room_masks,
        "door_cell_bounds": door_cell_bounds,
        "room_pair_doors": room_pair_doors,
        "wall_barriers": wall_barriers
    }
    return grid_info


def verify_no_wall_crossings(polyline, wall_barriers):
    """
    Verifies that no segment in polyline crosses any wall barrier.
    Raises ValueError if a wall crossing is detected.
    """
    if wall_barriers is None or wall_barriers.is_empty:
        return

    for k in range(len(polyline) - 1):
        p1 = polyline[k]
        p2 = polyline[k + 1]
        seg = LineString([p1, p2])
        if seg.crosses(wall_barriers):
            inter = seg.intersection(wall_barriers)
            raise ValueError(
                f"CRITICAL: Wall crossing violation detected along segment {p1} -> {p2}! "
                f"Intersection with wall barrier: {inter}"
            )


def a_star_orthogonal(grid_info, start_pt_m, goal_pt_m, cable_usage=None, walkable_mask=None):
    """
    Axis-Aligned A* search between start_pt_m and goal_pt_m on the metric grid.
    Movement is restricted strictly to 4 orthogonal directions (Up, Down, Left, Right).
    Cost includes:
      - step_length = resolution (0.05m per step)
      - bend_penalty = 0.5m whenever direction turns (90° turn)
      - overlap_penalty = 1.0 * resolution if sharing an already-routed cable line
      - crossing_penalty = 5.0 if crossing perpendicularly across an already-routed cable (away from nodes/hubs)
    """
    walkable = walkable_mask if walkable_mask is not None else grid_info["walkable"]
    minx, miny = grid_info["minx"], grid_info["miny"]
    res = grid_info["res"]
    W, H = grid_info["W"], grid_info["H"]

    start_gx = int(round((start_pt_m[0] - minx) / res))
    start_gy = int(round((start_pt_m[1] - miny) / res))
    goal_gx = int(round((goal_pt_m[0] - minx) / res))
    goal_gy = int(round((goal_pt_m[1] - miny) / res))

    start_gx = max(0, min(W - 1, start_gx))
    start_gy = max(0, min(H - 1, start_gy))
    goal_gx = max(0, min(W - 1, goal_gx))
    goal_gy = max(0, min(H - 1, goal_gy))

    # Orthogonal 4 directions: (dx, dy, dir_code) where 1: H, 2: V
    dirs = [(1, 0, 1), (-1, 0, 1), (0, 1, 2), (0, -1, 2)]

    open_set = []
    # (f_score, g_score, gx, gy, direction)
    heapq.heappush(open_set, (0.0, 0.0, start_gx, start_gy, 0))
    came_from = {}
    cost_so_far = {(start_gx, start_gy, 0): 0.0}

    goal_reached_state = None

    # Cable usage unpacking if present
    h_use = cable_usage.get("grid_h_usage") if cable_usage else None
    v_use = cable_usage.get("grid_v_usage") if cable_usage else None
    protected = cable_usage.get("protected_cells") if cable_usage else None

    while open_set:
        f, g, cx, cy, cdir = heapq.heappop(open_set)

        if (cx, cy) == (goal_gx, goal_gy):
            goal_reached_state = (cx, cy, cdir)
            break

        if g > cost_so_far.get((cx, cy, cdir), float('inf')):
            continue

        for dx, dy, ndir in dirs:
            nx = cx + dx
            ny = cy + dy

            # Ensure within grid bounds and walkable (start and goal are always allowed)
            is_walk = False
            if 0 <= nx < W and 0 <= ny < H:
                if (nx, ny) == (goal_gx, goal_gy) or walkable[ny, nx]:
                    is_walk = True

            if is_walk:
                bend_cost = 0.5 if (cdir != 0 and cdir != ndir) else 0.0
                step_cost = res + bend_cost

                # Overlap and crossing penalties
                if cable_usage is not None:
                    if ndir == 1:  # Horizontal move
                        edge_x = min(cx, nx)
                        edge_y = cy
                        if h_use[edge_y, edge_x] > 0:
                            step_cost += 1.0 * res  # Overlap penalty (1 per m)
                        if protected is None or (nx, ny) not in protected:
                            # Moving horizontally into (nx, ny) where a vertical cable exists
                            if v_use[ny, nx] > 0 or (ny > 0 and v_use[ny - 1, nx] > 0):
                                step_cost += 5.0  # Crossing penalty (5 per crossing)
                    elif ndir == 2:  # Vertical move
                        edge_x = cx
                        edge_y = min(cy, ny)
                        if v_use[edge_y, edge_x] > 0:
                            step_cost += 1.0 * res  # Overlap penalty (1 per m)
                        if protected is None or (nx, ny) not in protected:
                            # Moving vertically into (nx, ny) where a horizontal cable exists
                            if h_use[ny, nx] > 0 or (nx > 0 and h_use[ny, nx - 1] > 0):
                                step_cost += 5.0  # Crossing penalty (5 per crossing)

                new_g = g + step_cost
                state = (nx, ny, ndir)

                if new_g < cost_so_far.get(state, float('inf')):
                    cost_so_far[state] = new_g
                    h = (abs(nx - goal_gx) + abs(ny - goal_gy)) * res
                    if cdir != 0 and ((dx != 0 and goal_gy != ny) or (dy != 0 and goal_gx != nx)):
                        h += 0.5  # At least one turn required
                    heapq.heappush(open_set, (new_g + h, new_g, nx, ny, ndir))
                    came_from[state] = (cx, cy, cdir)

    if not goal_reached_state:
        return None

    # Reconstruct path points in metres
    curr = goal_reached_state
    grid_pts = []
    while curr in came_from:
        grid_pts.append((minx + curr[0] * res, miny + curr[1] * res))
        curr = came_from[curr]
    grid_pts.append((minx + start_gx * res, miny + start_gy * res))
    grid_pts.reverse()

    return grid_pts


def compute_pairwise_physical_distances(grid_info, nodes_m, room_ids, G=None):
    """
    Precomputes pairwise physical A* path costs between all room nodes in room_ids.
    Cost includes physical length (L) + bend penalty (0.5 * B).
    """
    pairwise = {}
    rooms = list(room_ids)
    H, W = grid_info["H"], grid_info["W"]
    room_masks = grid_info.get("room_masks", {})
    door_cell_bounds = grid_info.get("door_cell_bounds", {})
    room_pair_doors = grid_info.get("room_pair_doors", {})

    for i in range(len(rooms)):
        for j in range(i, len(rooms)):
            u, v = rooms[i], rooms[j]
            if u == v:
                pairwise[(u, v)] = 0.0
                continue

            leg_walkable = None
            if G is not None and G.has_node(u) and G.has_node(v) and nx.has_path(G, u, v):
                try:
                    room_path = nx.shortest_path(G, u, v)
                    corridor_mask = np.zeros((H, W), dtype=bool)
                    for r in room_path:
                        if r in room_masks:
                            corridor_mask |= room_masks[r]
                    for k in range(len(room_path) - 1):
                        r_a, r_b = room_path[k], room_path[k + 1]
                        for d_id in room_pair_doors.get((r_a, r_b), []):
                            if d_id in door_cell_bounds:
                                gx1, gx2, gy1, gy2 = door_cell_bounds[d_id]
                                corridor_mask[gy1:gy2 + 1, gx1:gx2 + 1] = True
                    leg_walkable = grid_info["walkable"] & corridor_mask
                except Exception:
                    leg_walkable = None

            pts = None
            if leg_walkable is not None:
                pts = a_star_orthogonal(grid_info, nodes_m[u], nodes_m[v], walkable_mask=leg_walkable)
            if pts is None:
                pts = a_star_orthogonal(grid_info, nodes_m[u], nodes_m[v])

            if pts is None:
                dist = float('inf')
            else:
                comp = compress_orthogonal_path(pts)
                m = calculate_ring_metrics(comp)
                dist = m["L"] + 0.5 * m["B"]
            pairwise[(u, v)] = dist
            pairwise[(v, u)] = dist
    return pairwise


def compress_orthogonal_path(pts):
    """
    Compresses consecutive collinear grid points into clean polyline corner vertices.
    Guarantees every segment is strictly axis-aligned (either dx == 0 or dy == 0).
    """
    if len(pts) <= 2:
        return pts

    compressed = [pts[0]]
    for i in range(1, len(pts) - 1):
        dx_in = pts[i][0] - pts[i - 1][0]
        dy_in = pts[i][1] - pts[i - 1][1]
        dx_out = pts[i + 1][0] - pts[i][0]
        dy_out = pts[i + 1][1] - pts[i][1]

        dir_in = ('H' if abs(dx_in) > 1e-6 else 'V')
        dir_out = ('H' if abs(dx_out) > 1e-6 else 'V')

        # Keep vertex if direction changes (bend) or step reverses
        if dir_in != dir_out or (dx_in * dx_out < -1e-6) or (dy_in * dy_out < -1e-6):
            compressed.append((round(pts[i][0], 4), round(pts[i][1], 4)))

    compressed.append((round(pts[-1][0], 4), round(pts[-1][1], 4)))
    return compressed


def calculate_ring_metrics(polyline_pts, tol_mm=0.001):
    """
    Calculates L, B, O, X, J for a closed orthogonal cable ring.
      J = L + 5.0 * X + 1.0 * O + 0.5 * B
    """
    if len(polyline_pts) < 2:
        return {"L": 0.0, "B": 0, "O": 0.0, "X": 0, "J": 0.0, "segments": []}

    # 1. Total Length (L) and segment extraction
    L = 0.0
    segs = []
    h_segs = []
    v_segs = []

    for k in range(len(polyline_pts) - 1):
        x1, y1 = polyline_pts[k]
        x2, y2 = polyline_pts[k + 1]
        slen = math.hypot(x2 - x1, y2 - y1)
        if slen < tol_mm:
            continue
        L += slen
        if abs(y2 - y1) <= tol_mm:
            # Horizontal segment
            c_y = round(0.5 * (y1 + y2), 3)
            h_segs.append((c_y, min(x1, x2), max(x1, x2)))
            segs.append(("H", c_y, min(x1, x2), max(x1, x2), slen))
        else:
            # Vertical segment
            c_x = round(0.5 * (x1 + x2), 3)
            v_segs.append((c_x, min(y1, y2), max(y1, y2)))
            segs.append(("V", c_x, min(y1, y2), max(y1, y2), slen))

    # 2. Bends (B)
    B = 0
    dirs = []
    for k in range(len(polyline_pts) - 1):
        x1, y1 = polyline_pts[k]
        x2, y2 = polyline_pts[k + 1]
        dx, dy = x2 - x1, y2 - y1
        if math.hypot(dx, dy) >= tol_mm:
            dirs.append("H" if abs(dx) >= abs(dy) else "V")

    if len(dirs) >= 2:
        for i in range(len(dirs)):
            if dirs[(i - 1) % len(dirs)] != dirs[i]:
                B += 1

    # 3. Overlap (O) - sweep line interval coverage along identical coordinate lines
    O = 0.0
    by_line = defaultdict(list)
    for orient, coord, cmin, cmax, _ in segs:
        by_line[(orient, coord)].append((cmin, cmax))

    for _, ivs in by_line.items():
        if len(ivs) > 1:
            events = []
            for a, b in ivs:
                events.extend([(a, 1), (b, -1)])
            events.sort(key=lambda ev: (ev[0], -ev[1]))
            cov, px = 0, None
            for x, d in events:
                if px is not None and cov >= 2 and x > px:
                    O += (cov - 1) * (x - px)
                cov += d
                px = x

    # 4. Transverse Crossings (X)
    X = 0
    for y_h, x1, x2 in h_segs:
        for x_v, y1, y2 in v_segs:
            # Strictly interior crossing
            if (x1 + tol_mm < x_v < x2 - tol_mm) and (y1 + tol_mm < y_h < y2 - tol_mm):
                X += 1

    J = L + 5.0 * X + 1.0 * O + 0.5 * B

    return {
        "L": round(L, 3),
        "B": int(B),
        "O": round(O, 3),
        "X": int(X),
        "J": round(J, 3),
        "segments": segs
    }


def route_all_hubs(plan, scale, final_sequences, nodes_dict_units, resolution=0.05, grid_info=None, G=None):
    """
    Routes axis-aligned closed ring cables for each hub in metres.
    Includes active overlap and crossing penalties across all legs and hubs.
    Restricts search to topological room corridor per leg when G is available.
    Enforces strict post-routing geometric wall-crossing verification.
    """
    inv_s = 1.0 / scale
    # Convert node coordinates to metres
    nodes_m = {r_id: (round(pt.x * inv_s, 4), round(pt.y * inv_s, 4)) for r_id, pt in nodes_dict_units.items()}

    if grid_info is None:
        print(f"\nBuilding {resolution*100:.0f}cm metric grid over floor plan...")
        grid_info = build_orthogonal_grid(plan, scale, resolution=resolution)

    H, W = grid_info["H"], grid_info["W"]
    res = grid_info["res"]
    minx, miny = grid_info["minx"], grid_info["miny"]
    room_masks = grid_info.get("room_masks", {})
    door_cell_bounds = grid_info.get("door_cell_bounds", {})
    room_pair_doors = grid_info.get("room_pair_doors", {})

    # Protect cells near all room nodes and hubs (legs meeting at node/hub do not count as crossing)
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
        "protected_cells": protected_cells
    }

    hubs_routed = {}

    for hub_idx, (hub_room, sequence) in enumerate(sorted(final_sequences.items()), start=1):
        print(f"\n--- Routing Hub {hub_idx} [{hub_room}] ---")
        print(f"  Closed Tour Sequence: {' -> '.join(sequence)}")

        # Handle 1-room hub (node is the hub itself)
        if len(sequence) <= 1:
            pt = nodes_m[sequence[0]]
            compressed_polyline = [pt, pt]
            metrics = calculate_ring_metrics(compressed_polyline)
            hubs_routed[hub_room] = {
                "hub_idx": hub_idx,
                "hub_room": hub_room,
                "sequence": sequence,
                "polyline": compressed_polyline,
                "route_segments": [],
                "metrics": metrics
            }
            continue

        full_raw_path = []
        route_segments = []

        for i in range(len(sequence) - 1):
            u = sequence[i]
            v = sequence[i + 1]
            start_pt = nodes_m[u]
            goal_pt = nodes_m[v]

            # Build topological corridor mask if graph G is provided and path exists
            leg_walkable = None
            if G is not None and G.has_node(u) and G.has_node(v) and nx.has_path(G, u, v):
                try:
                    room_path = nx.shortest_path(G, u, v)
                    corridor_mask = np.zeros((H, W), dtype=bool)
                    for r in room_path:
                        if r in room_masks:
                            corridor_mask |= room_masks[r]
                    for k in range(len(room_path) - 1):
                        r_a, r_b = room_path[k], room_path[k + 1]
                        for d_id in room_pair_doors.get((r_a, r_b), []):
                            if d_id in door_cell_bounds:
                                gx1, gx2, gy1, gy2 = door_cell_bounds[d_id]
                                corridor_mask[gy1:gy2 + 1, gx1:gx2 + 1] = True
                    leg_walkable = grid_info["walkable"] & corridor_mask
                except Exception:
                    leg_walkable = None

            leg_raw = None
            if leg_walkable is not None:
                leg_raw = a_star_orthogonal(grid_info, start_pt, goal_pt, cable_usage=cable_usage, walkable_mask=leg_walkable)

            # Fallback to global walkable if corridor was disconnected
            if leg_raw is None:
                leg_raw = a_star_orthogonal(grid_info, start_pt, goal_pt, cable_usage=cable_usage)

            if leg_raw is None:
                raise RuntimeError(f"A* failed to route leg: {u} -> {v} through doors!")

            # Update cable usage grid for subsequent legs to avoid overlap and crossings
            for k in range(len(leg_raw) - 1):
                x1, y1 = leg_raw[k]
                x2, y2 = leg_raw[k + 1]
                gx1 = int(round((x1 - minx) / res))
                gy1 = int(round((y1 - miny) / res))
                gx2 = int(round((x2 - minx) / res))
                gy2 = int(round((y2 - miny) / res))
                if gy1 == gy2:
                    cable_usage["grid_h_usage"][gy1, min(gx1, gx2)] += 1
                elif gx1 == gx2:
                    cable_usage["grid_v_usage"][min(gy1, gy2), gx1] += 1

            leg_comp = compress_orthogonal_path(leg_raw)
            leg_len = sum(math.hypot(leg_comp[k + 1][0] - leg_comp[k][0], leg_comp[k + 1][1] - leg_comp[k][1]) for k in range(len(leg_comp) - 1))
            route_segments.append({
                "from": u,
                "to": v,
                "length_m": round(leg_len, 3),
                "polyline": leg_comp
            })

            # Stitch leg into full path
            for pt in (leg_raw if i == 0 else leg_raw[1:]):
                full_raw_path.append(pt)

        # Compress into clean orthogonal polyline corners
        compressed_polyline = compress_orthogonal_path(full_raw_path)

        # Safety net: Verify strict adherence to walls
        verify_no_wall_crossings(compressed_polyline, grid_info["wall_barriers"])
        print("  [PASS] Strict wall-crossing verification passed (0 walls crossed).")

        metrics = calculate_ring_metrics(compressed_polyline)

        print(f"  Total Segments / Vertices: {len(compressed_polyline)}")
        print(f"  Length (L): {metrics['L']} m")
        print(f"  Bends  (B): {metrics['B']} (penalty: {metrics['B'] * 0.5:.2f})")
        print(f"  Overlap(O): {metrics['O']} m")
        print(f"  Cross  (X): {metrics['X']} (penalty: {metrics['X'] * 5.0:.2f})")
        print(f"  Cost   (J): {metrics['J']}")

        hubs_routed[hub_room] = {
            "hub_idx": hub_idx,
            "hub_room": hub_room,
            "sequence": sequence,
            "polyline": compressed_polyline,
            "route_segments": route_segments,
            "metrics": metrics
        }

    return hubs_routed, grid_info


def visualize_phase4_routes(plan, scale, hubs_routed, grid_info, output_image_path=None, show_plot=True):
    """
    Renders the floor plan with walls, doors, nodes, and routed axis-aligned cables.
    """
    inv_s = 1.0 / scale
    rooms_m = grid_info["rooms_m"]
    doors_m = grid_info["doors_m"]

    fig, ax = plt.subplots(figsize=(12, 9))

    # 1. Draw rooms
    for rid, poly in rooms_m.items():
        polys = poly.geoms if hasattr(poly, "geoms") else [poly]
        for p in polys:
            x, y = p.exterior.xy
            ax.fill(x, y, color="#f8f9fa", alpha=0.9, zorder=1)
            ax.plot(x, y, color="#495057", linewidth=2.0, zorder=2)
        cx, cy = poly.centroid.x, poly.centroid.y
        ax.text(cx, cy, rid, fontsize=9, ha="center", va="center", color="#6c757d", fontweight="bold", zorder=3)

    # 2. Draw doors
    for dpoly in doors_m:
        polys = dpoly.geoms if hasattr(dpoly, "geoms") else [dpoly]
        for p in polys:
            x, y = p.exterior.xy
            ax.fill(x, y, color="#d4edda", alpha=0.9, zorder=2)
            ax.plot(x, y, color="#28a745", linewidth=2.5, zorder=3)

    # 3. Draw cable routes
    palette = ["#d63384", "#0d6efd", "#fd7e14", "#6f42c1", "#20c997"]

    total_J = sum(data["metrics"]["J"] for data in hubs_routed.values())

    for hub_room, data in hubs_routed.items():
        h_idx = data["hub_idx"]
        col = palette[(h_idx - 1) % len(palette)]
        poly_pts = data["polyline"]

        xs = [p[0] for p in poly_pts]
        ys = [p[1] for p in poly_pts]

        m = data["metrics"]
        lbl = f"Hub {h_idx} [{hub_room}] Ring (L={m['L']}m, B={m['B']}, O={m['O']}m, J={m['J']})"
        ax.plot(xs, ys, color=col, linewidth=3.0, alpha=0.85, label=lbl, zorder=5)

        # Plot vertices
        ax.scatter(xs, ys, color=col, s=25, zorder=6)

        # Hub marker
        hx, hy = poly_pts[0]
        ax.plot(hx, hy, marker="*", color="#ffc107", markersize=20, markeredgecolor="black", zorder=7)

    ax.set_title(
        f"Phase 4: Axis-Aligned Cable Routing & Physical Optimization\n"
        f"Strictly Orthogonal (No Wall Crossings) | Total Objective Cost J: {total_J:.2f}",
        fontsize=13,
        fontweight="bold"
    )
    ax.set_xlabel("X (metres)", fontsize=10)
    ax.set_ylabel("Y (metres)", fontsize=10)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper right", fontsize=9)
    plt.tight_layout()

    if output_image_path:
        plt.savefig(output_image_path, dpi=150)
        print(f"\nPhase 4 visualization saved to: {output_image_path}")

    if show_plot:
        plt.show()


def run_phase4(json_path="sample_plan.json", show_plot=False, save_img=None, resolution=0.05, output_json_path=None, verbose=True):
    # Load raw JSON plan (supports either file path or in-memory dict)
    if isinstance(json_path, dict):
        plan = json_path
        plan_id = str(plan.get("id", "PLAN_01"))
    else:
        with open(json_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        plan_id = str(plan.get("id", os.path.splitext(os.path.basename(json_path))[0]))

    # 1. Phase 1 Data Pipeline
    G, nodes_dict_units, scale, min_hubs = load_and_process_plan(json_path, show_plot=False, verbose=verbose)

    # 2. Phase 2 Partitioning & Hub Placement
    best_hubs, best_total_cost = run_phase2(json_path, show_plot=False, plan_data=(G, nodes_dict_units, scale, min_hubs), verbose=verbose)

    if verbose:
        print("\n=======================================================")
        print("PHASE 4: AXIS-ALIGNED CABLE ROUTING & PHYSICAL OPTIMIZATION")
        print("=======================================================")

    # 3. Build metric grid with 15cm walls, dilated doors, and wall barriers
    grid_info = build_orthogonal_grid(plan, scale, resolution=resolution)
    inv_s = 1.0 / scale
    nodes_m = {r_id: (round(pt.x * inv_s, 4), round(pt.y * inv_s, 4)) for r_id, pt in nodes_dict_units.items()}

    # Canonical node mapping: N1, N2, ... for all eligible rooms (per PPT Slide 8)
    all_eligible = sorted([r for r, d in G.nodes(data=True) if d.get("eligible", True)])
    room_to_node = {r: f"N{idx}" for idx, r in enumerate(all_eligible, 1)}

    # 4. Phase 3 Physical-Distance Driven Sequencing
    if verbose:
        print("\n--- Physical-Distance Driven TSP Sequencing ---")
    final_sequences = {}
    for hub_idx, (hub_room, assigned_rooms) in enumerate(sorted(best_hubs.items()), start=1):
        pairwise_dist = compute_pairwise_physical_distances(grid_info, nodes_m, assigned_rooms, G=G)
        sequence, phys_cost = find_optimal_sequence(G, hub_room, list(assigned_rooms), pairwise_dist=pairwise_dist)
        if verbose:
            print(f"Hub {hub_idx} [{hub_room}] Physical TSP: {' -> '.join(sequence)} (Cost: {phys_cost:.2f}m)")
        final_sequences[hub_room] = sequence

    # 5. Route all hubs with active overlap & crossing penalties and topological corridors
    hubs_routed, grid_info = route_all_hubs(
        plan, scale, final_sequences, nodes_dict_units, resolution=resolution, grid_info=grid_info, G=G
    )

    total_L = sum(h["metrics"]["L"] for h in hubs_routed.values())
    total_B = sum(h["metrics"]["B"] for h in hubs_routed.values())
    total_O = sum(h["metrics"]["O"] for h in hubs_routed.values())
    total_X = sum(h["metrics"]["X"] for h in hubs_routed.values())
    total_J = sum(h["metrics"]["J"] for h in hubs_routed.values())

    if verbose:
        print("\n=== FINAL ROUTING RESULTS & OBJECTIVE METRICS ===")
        for hub_room, h_data in hubs_routed.items():
            m = h_data["metrics"]
            print(f"Hub [{hub_room}]: L={m['L']}m | Bends={m['B']} | Overlap={m['O']}m | Crossings={m['X']} | Score J={m['J']}")

        print("-" * 55)
        print(f"TOTAL SYSTEM COST: J = {total_J:.2f}")
        print(f"  - Total Length (L): {total_L:.2f} m")
        print(f"  - Total Bends  (B): {total_B} (cost: {total_B * 0.5:.2f})")
        print(f"  - Total Overlap(O): {total_O:.2f} m")
        print(f"  - Total Cross  (X): {total_X} (cost: {total_X * 5.0:.2f})")
        print("=======================================================\n")

    # 6. Generate official Output JSON (PPT Slide 8 format)
    output_data = {
        "plan_id": plan_id,
        "units": "m",
        "hubs": [],
        "reported_metrics": {
            "hub_count": len(hubs_routed),
            "total_length_m": round(total_L, 3),
            "total_bends": int(total_B),
            "total_overlap_m": round(total_O, 3),
            "total_crossings": int(total_X),
            "total_cost_J": round(total_J, 3)
        }
    }

    for hub_room, h_data in hubs_routed.items():
        h_idx = h_data["hub_idx"]
        hub_id = f"H{h_idx}"
        hx, hy = nodes_m[hub_room]
        assigned_r = sorted(list(best_hubs[hub_room]))

        # Format sequence with H1 at start and end, and N1, N2... for interior nodes
        seq_canonical = []
        for s_idx, r in enumerate(h_data["sequence"]):
            if (s_idx == 0 or s_idx == len(h_data["sequence"]) - 1) and r == hub_room:
                seq_canonical.append(hub_id)
            else:
                seq_canonical.append(room_to_node[r])

        # Format segments with canonical H1 and N1, N2...
        segments_canonical = []
        for s_idx, seg in enumerate(h_data["route_segments"]):
            u, v = seg["from"], seg["to"]
            from_id = hub_id if (s_idx == 0 and u == hub_room) else room_to_node.get(u, u)
            to_id = hub_id if (s_idx == len(h_data["route_segments"]) - 1 and v == hub_room) else room_to_node.get(v, v)
            segments_canonical.append({
                "from": from_id,
                "to": to_id,
                "length_m": seg["length_m"],
                "polyline": seg["polyline"]
            })

        output_data["hubs"].append({
            "hub_id": hub_id,
            "room_id": hub_room,
            "location": {"x": hx, "y": hy},
            "assigned_rooms": assigned_r,
            "assigned_nodes": [room_to_node[r] for r in assigned_r],
            "closed_sequence": seq_canonical,
            "route_segments": segments_canonical,
            "ring_length_m": h_data["metrics"]["L"]
        })

    out_json = output_json_path or "output_plan.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
    if verbose:
        print(f"Official Output JSON saved to: {out_json}")

    if show_plot or save_img:
        visualize_phase4_routes(plan, scale, hubs_routed, grid_info, output_image_path=save_img, show_plot=show_plot)

    return output_data, total_J, hubs_routed


if __name__ == "__main__":
    target_json = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "sample_plan.json"
    save_flag = "floor_plan_phase4.png" if "--save" in sys.argv else None
    show_flag = "--show" in sys.argv
    run_phase4(target_json, show_plot=show_flag, save_img=save_flag)
