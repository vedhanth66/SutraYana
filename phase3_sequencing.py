import os
import sys
import json
import itertools
import tempfile
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


def find_optimal_sequence(G, hub_room, assigned_nodes, nodes_dict=None, scale=None):
    """
    Finds the optimal closed sequence for a single hub using brute-force permutations.
    Evaluates every permutation of visiting the assigned rooms:
        Hub -> N1 -> N2 -> ... -> Nn -> Hub
    Minimizes total graph hop-distance, using physical Euclidean length as tie-breaker.
    """
    nodes_to_visit = sorted([n for n in assigned_nodes if n != hub_room])

    # If the hub room is the only room in the component
    if not nodes_to_visit:
        return [hub_room], 0

    best_sequence = None
    best_dist = float('inf')
    best_phys_len = float('inf')

    # Try every possible order of visiting the nodes
    for perm in itertools.permutations(nodes_to_visit):
        sequence = [hub_room] + list(perm) + [hub_room]
        dist = calculate_tour_distance(sequence, G)
        phys_len = calculate_physical_tour_length(sequence, nodes_dict, scale)

        if dist < best_dist or (dist == best_dist and phys_len < best_phys_len):
            best_dist = dist
            best_phys_len = phys_len
            best_sequence = sequence

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


def run_phase3(json_path="sample_plan.json", show_plot=False, save_img=None):
    # 1. Load plan graph and nodes from Phase 1
    G, nodes_dict, scale, min_hubs = load_and_process_plan(json_path, show_plot=False)

    # 2. Get optimal partitioning and hub placement from Phase 2
    best_hubs, best_total_cost = run_phase2(json_path, show_plot=False, plan_data=(G, nodes_dict, scale, min_hubs))

    print("\n--- Phase 3: Optimal Node Sequencing ---")

    final_sequences = {}
    for hub_idx, (hub_room, assigned_rooms) in enumerate(sorted(best_hubs.items()), start=1):
        print(f"\nHub {hub_idx} ({hub_room}) - Assigned Rooms: {sorted(list(assigned_rooms))}")

        # Find the optimal closed sequence
        sequence, dist = find_optimal_sequence(G, hub_room, list(assigned_rooms), nodes_dict, scale)

        print(f"  Optimal Ring Sequence: {' -> '.join(sequence)}")
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
