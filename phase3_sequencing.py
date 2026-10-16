import os
import sys
import json
import math
import itertools
import tempfile
from collections import defaultdict
import networkx as nx

os.environ.setdefault('MPLCONFIGDIR', tempfile.gettempdir())
import matplotlib.pyplot as plt
from shapely.geometry import shape

from phase1_pipeline import load_and_process_plan
from phase2_partition import run_phase2


def calculate_tour_distance(sequence, G):
    """Calculates the total hop-distance of a closed sequence H -> N1 -> ... -> Nn -> H."""
    total_dist = 0
    for i in range(len(sequence) - 1):
        u, v = sequence[i], sequence[i + 1]
        try:
            total_dist += nx.shortest_path_length(G, u, v)
        except nx.NetworkXNoPath:
            return float('inf')
    return total_dist


def calculate_physical_tour_length(sequence, nodes_dict, scale):
    """Calculates Euclidean physical distance in meters for tie-breaking."""
    if not nodes_dict or not scale:
        return 0.0
    total_len = 0.0
    for i in range(len(sequence) - 1):
        p1 = nodes_dict[sequence[i]]
        p2 = nodes_dict[sequence[i + 1]]
        total_len += p1.distance(p2) / scale
    return total_len


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


def get_room_metric_coord(r, G, nodes_dict=None, scale=1.0, pair_paths=None):
    """
    Extracts the (x, y) coordinates of a room node strictly in METRES.
    """
    if pair_paths is not None and (r, r) in pair_paths and pair_paths[(r, r)]:
        return pair_paths[(r, r)][0]
    if nodes_dict is not None and r in nodes_dict:
        pt = nodes_dict[r]
        s = scale if scale and scale > 0 else 1.0
        return (pt.x / s, pt.y / s)
    if G is not None and G.has_node(r):
        nd = G.nodes[r]
        s = scale if scale and scale > 0 else 1.0
        if "node" in nd and isinstance(nd["node"], dict) and "x" in nd["node"]:
            return (float(nd["node"]["x"]) / s, float(nd["node"]["y"]) / s)
        if "centroid" in nd and isinstance(nd["centroid"], dict) and "x" in nd["centroid"]:
            return (float(nd["centroid"]["x"]) / s, float(nd["centroid"]["y"]) / s)
    return (0.0, 0.0)


def segments_intersect(p1, p2, p3, p4):
    """
    Checks if line segment (p1, p2) and line segment (p3, p4) strictly cross each other in 2D.
    """
    def ccw(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1 = ccw(p1, p2, p3)
    d2 = ccw(p1, p2, p4)
    d3 = ccw(p3, p4, p1)
    d4 = ccw(p3, p4, p2)

    return ((d1 * d2 < -1e-6) and (d3 * d4 < -1e-6))


def count_tour_segment_crossings(sequence, coords_map):
    """
    Counts self-intersections among non-adjacent segments of the closed sequence polyline.
    Non-adjacent intersections guarantee transverse cable crossings and figure-8 paths.
    """
    n = len(sequence) - 1
    if n < 4:
        return 0

    pts = [coords_map.get(r, (0.0, 0.0)) for r in sequence]
    crossings = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if segments_intersect(pts[i], pts[i + 1], pts[j], pts[j + 1]):
                crossings += 1
    return crossings


def calculate_angular_sweep_penalty(sequence, hub_room, coords_map):
    """
    Penalizes zigzagging across the apartment by measuring polar angle monotonicity
    around the Hub (or territory centroid).
    A smooth circular sweep visits rooms in consistent rotational order (pure perimeter loop).
    Direction reversals (jumping across the central room and back) incur heavy penalties.
    """
    if len(sequence) <= 3:
        return 0.0

    hx, hy = coords_map.get(hub_room, (0.0, 0.0))
    non_hub = [r for r in sequence[:-1] if r != hub_room]
    if len(non_hub) <= 1:
        return 0.0

    angles = []
    for r in non_hub:
        rx, ry = coords_map.get(r, (hx, hy))
        angles.append(math.atan2(ry - hy, rx - hx))

    # Calculate angular steps between consecutive rooms
    diffs = []
    for k in range(len(angles) - 1):
        d = (angles[k + 1] - angles[k] + math.pi) % (2 * math.pi) - math.pi
        diffs.append(d)

    # Count sign reversals (jumping back and forth across the center)
    reversals = 0
    for k in range(len(diffs) - 1):
        if diffs[k] * diffs[k + 1] < -1e-4:
            reversals += 1

    return reversals * 25.0


def calculate_doorway_flow_penalty(sequence, G, hub_room):
    """
    Factors in doorway connectivity weights and penalizes non-adjacent room leaps
    or cutting across the central hub room.
    """
    if G is None:
        return 0.0

    hop_penalty = 0.0
    chord_cut_penalty = 0.0

    for i in range(len(sequence) - 1):
        u = sequence[i]
        v = sequence[i + 1]
        if u == v:
            continue

        try:
            sp = nx.shortest_path(G, u, v)
            hops = len(sp) - 1
            if hops > 1:
                # Extra hops through intermediate rooms add bends and congestion
                hop_penalty += (hops - 1) * 15.0

            # If moving between two non-hub rooms cuts across the central hub room
            if u != hub_room and v != hub_room and hub_room in sp[1:-1]:
                chord_cut_penalty += 20.0
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            hop_penalty += 50.0

    return hop_penalty + chord_cut_penalty


def find_optimal_sequence(G, hub_room, assigned_nodes, nodes_dict=None, scale=None, pairwise_dist=None, pair_paths=None):
    """
    Finds the optimal closed sequence for a single hub using brute-force permutations
    guided by doorway connectivity weights and circular perimeter sweeps.
    Evaluates every permutation of visiting the assigned rooms:
        Hub -> N1 -> N2 -> ... -> Nn -> Hub
    Prioritizes:
      1. Zero transverse crossings (X = 0) by eliminating self-intersecting chords.
      2. Minimum 90° bends (B) by following circular perimeter order around the hub.
      3. Physical doorway flow (preferring direct door adjacency and penalizing central room zigzags).
      4. Lowest total system cost J (L + 5X + 1.0O + 0.5B).
    """
    nodes_to_visit = sorted([n for n in assigned_nodes if n != hub_room])

    # If the hub room is the only room in the component
    if not nodes_to_visit:
        return [hub_room], 0.0

    # Build metric coordinates map for all rooms in territory
    coords_map = {}
    for r in assigned_nodes:
        coords_map[r] = get_room_metric_coord(r, G, nodes_dict, scale, pair_paths)

    best_sequence = None
    best_ranking = (float('inf'), float('inf'), float('inf'), float('inf'), float('inf'))
    best_dist = float('inf')

    # Try every permutation of visiting the non-hub rooms
    for perm in itertools.permutations(nodes_to_visit):
        sequence = [hub_room] + list(perm) + [hub_room]

        # 1. Doorway connectivity flow penalty
        doorway_penalty = calculate_doorway_flow_penalty(sequence, G, hub_room)

        # 2. Geometric tour self-crossing penalty (identifies figure-8 zigzags)
        tour_crossings = count_tour_segment_crossings(sequence, coords_map)
        crossing_penalty = tour_crossings * 50.0

        # 3. Angular sweep reversal penalty (penalizes jumping across hub room)
        angular_penalty = calculate_angular_sweep_penalty(sequence, hub_room, coords_map)

        if pair_paths is not None:
            # Reconstruct the closed loop polyline using precomputed leg paths
            full_path = []
            valid = True
            for i in range(len(sequence) - 1):
                leg = pair_paths.get((sequence[i], sequence[i + 1]))
                if leg is None:
                    valid = False
                    break
                full_path.extend(leg if i == 0 else leg[1:])

            if valid:
                comp = compress_orthogonal_path(full_path)
                m = calculate_ring_metrics(comp)

                # Composite cost emphasizing zero crossings and minimum bends:
                effective_cost = (
                    m["J"]
                    + 25.0 * m["X"]
                    + 1.0 * m["B"]
                    + doorway_penalty
                    + crossing_penalty
                    + angular_penalty
                )

                # Ranking tuple:
                # 1. Minimum actual transverse crossings m["X"] (strictly 0)
                # 2. Minimum tour segment crossings (no figure-8s)
                # 3. Lowest composite score (effective_cost)
                # 4. Lowest true objective J
                # 5. Fewest bends B
                ranking = (m["X"], tour_crossings, round(effective_cost, 2), round(m["J"], 3), m["B"])
                if ranking < best_ranking:
                    best_ranking = ranking
                    best_dist = m["J"]
                    best_sequence = sequence

        elif pairwise_dist is not None:
            phys_dist = sum(pairwise_dist.get((sequence[i], sequence[i + 1]), float('inf')) for i in range(len(sequence) - 1))
            total_hops = calculate_tour_distance(sequence, G)

            effective_cost = phys_dist + doorway_penalty + crossing_penalty + angular_penalty
            ranking = (tour_crossings, round(effective_cost, 2), total_hops, round(phys_dist, 3))
            if ranking < best_ranking:
                best_ranking = ranking
                best_dist = phys_dist
                best_sequence = sequence

        else:
            hop_dist = calculate_tour_distance(sequence, G)
            phys_len = calculate_physical_tour_length(sequence, nodes_dict, scale)

            effective_cost = hop_dist * 10.0 + doorway_penalty + crossing_penalty + angular_penalty + phys_len
            ranking = (tour_crossings, round(effective_cost, 2), hop_dist, round(phys_len, 3))
            if ranking < best_ranking:
                best_ranking = ranking
                best_dist = hop_dist
                best_sequence = sequence

    if best_sequence is None:
        best_sequence = [hub_room] + list(nodes_to_visit) + [hub_room]
        best_dist = calculate_tour_distance(best_sequence, G)

    return best_sequence, best_dist


def visualize_sequenced_tours(json_path, G, nodes_dict, best_hubs, final_sequences, output_image_path=None, show_plot=True):
    """
    Visualizes the floor plan with closed ring sequences (tours) plotted for each hub territory.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        plan = json.load(f)

    room_map = {r["id"]: r for r in plan.get("rooms", [])}

    colors = ['#cce5ff', '#d4edda', '#fff3cd', '#f8d7da', '#e2e3e5', '#d1ecf1']
    edge_colors = ['#004085', '#155724', '#856404', '#721c24', '#383d41', '#0c5460']
    tour_colors = ['#0056b3', '#28a745', '#fd7e14', '#e83e8c', '#6f42c1', '#20c997']

    fig, ax = plt.subplots(figsize=(11, 8.5))

    # Plot room polygons with territory fills
    for hub_idx, hub_room in enumerate(sorted(best_hubs.keys()), start=1):
        assigned_rooms = best_hubs[hub_room]
        c_idx = (hub_idx - 1) % len(colors)
        face_color = colors[c_idx]
        edge_color = edge_colors[c_idx]

        for room_id in assigned_rooms:
            room = room_map[room_id]
            poly = shape(room["polygon"])
            polys = poly.geoms if hasattr(poly, "geoms") else [poly]

            for p in polys:
                x, y = p.exterior.xy
                ax.fill(x, y, color=face_color, alpha=0.6)
                ax.plot(x, y, color=edge_color, linewidth=1.5)

            cx = room.get("centroid", {}).get("x", poly.centroid.x)
            cy = room.get("centroid", {}).get("y", poly.centroid.y)
            is_hub = (room_id == hub_room)
            lbl = f"{room_id}\n[HUB {hub_idx}]" if is_hub else room_id

            ax.text(
                cx, cy, lbl,
                fontsize=8, ha='center', va='center',
                fontweight='bold' if is_hub else 'normal',
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, edgecolor=edge_color if is_hub else "none")
            )

    # Plot the closed tour sequences with directed arrows
    for hub_idx, hub_room in enumerate(sorted(best_hubs.keys()), start=1):
        seq = final_sequences[hub_room]
        t_col = tour_colors[(hub_idx - 1) % len(tour_colors)]

        for i in range(len(seq) - 1):
            u, v = seq[i], seq[i + 1]
            p1, p2 = nodes_dict[u], nodes_dict[v]

            ax.annotate(
                "",
                xy=(p2.x, p2.y),
                xytext=(p1.x, p1.y),
                arrowprops=dict(
                    arrowstyle="->",
                    color=t_col,
                    lw=2.5,
                    mutation_scale=15,
                    shrinkA=8,
                    shrinkB=8
                ),
                zorder=5
            )

            # Order indicator at midpoint
            mid_x = (p1.x + p2.x) / 2
            mid_y = (p1.y + p2.y) / 2
            ax.text(
                mid_x, mid_y, f"{i + 1}",
                fontsize=8, fontweight='bold', color=t_col,
                bbox=dict(boxstyle="circle,pad=0.15", facecolor="white", edgecolor=t_col, lw=1.2),
                zorder=6
            )

    # Plot nodes and hub markers
    for node_id, pt in nodes_dict.items():
        if node_id not in best_hubs:
            ax.plot(pt.x, pt.y, 'o', color='navy', markersize=7, zorder=7)

    for hub_idx, hub_room in enumerate(sorted(best_hubs.keys()), start=1):
        pt = nodes_dict[hub_room]
        t_col = tour_colors[(hub_idx - 1) % len(tour_colors)]
        ax.plot(pt.x, pt.y, '*', color='crimson', markersize=18, markeredgecolor='black', zorder=8, label=f"Hub {hub_idx} ({hub_room})")

    ax.set_title("Phase 3: Closed Ring Sequencing (TSP Tour per Hub)", fontsize=12, fontweight='bold')
    ax.set_aspect('equal')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')
    plt.tight_layout()

    if output_image_path:
        plt.savefig(output_image_path, dpi=150)
        print(f"Sequencing visualization saved to: {output_image_path}")

    if show_plot:
        plt.show()


def run_phase3(json_path="sample_plan.json", show_plot=False, save_img=None, plan_data=None):
    # 1. Load plan graph and nodes from Phase 1
    if plan_data is not None:
        G, nodes_dict, scale, min_hubs = plan_data
    else:
        G, nodes_dict, scale, min_hubs = load_and_process_plan(json_path, show_plot=False)

    # 2. Get optimal partitioning and hub placement from Phase 2
    best_hubs, best_total_cost = run_phase2(json_path, show_plot=False, plan_data=(G, nodes_dict, scale, min_hubs))

    # Precompute physical pairwise distances using A* on metric grid if possible
    grid_info = None
    nodes_m = None
    try:
        from phase4_routing import build_orthogonal_grid, compute_pairwise_physical_distances
        with open(json_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)
        grid_info = build_orthogonal_grid(plan, scale)
        nodes_m = {r: (round(pt.x / scale, 4), round(pt.y / scale, 4)) for r, pt in nodes_dict.items()}
    except Exception:
        pass

    print("\n--- Phase 3: Optimal Node Sequencing ---")

    final_sequences = {}
    for hub_idx, (hub_room, assigned_rooms) in enumerate(sorted(best_hubs.items()), start=1):
        print(f"\nHub {hub_idx} ({hub_room}) - Assigned Rooms: {sorted(list(assigned_rooms))}")

        pairwise_dist = None
        if grid_info is not None and nodes_m is not None:
            pairwise_dist = compute_pairwise_physical_distances(grid_info, nodes_m, assigned_rooms)

        # Find the optimal closed sequence
        sequence, dist = find_optimal_sequence(G, hub_room, list(assigned_rooms), nodes_dict, scale, pairwise_dist=pairwise_dist)

        print(f"  Optimal Ring Sequence: {' -> '.join(sequence)}")
        if pairwise_dist is not None:
            print(f"  Physical Path Length: {dist:.2f} m")
        else:
            print(f"  Total Hop Distance: {dist}")

        final_sequences[hub_room] = sequence

    if show_plot or save_img:
        visualize_sequenced_tours(json_path, G, nodes_dict, best_hubs, final_sequences, output_image_path=save_img, show_plot=show_plot)

    return final_sequences, best_hubs


if __name__ == "__main__":
    target_json = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "sample_plan.json"
    save_flag = "floor_plan_phase3.png" if "--save" in sys.argv else None
    show_flag = "--show" in sys.argv
    run_phase3(target_json, show_plot=show_flag, save_img=save_flag)
