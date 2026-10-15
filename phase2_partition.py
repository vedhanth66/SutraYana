import os
import sys
import json
import math
import itertools
import tempfile
import networkx as nx

os.environ.setdefault('MPLCONFIGDIR', tempfile.gettempdir())
import matplotlib.pyplot as plt
from shapely.geometry import shape

from phase1_pipeline import load_and_process_plan


def is_connected_subgraph(G, nodes_subset):
    """Checks if the given subset of nodes forms a single connected component."""
    if not nodes_subset:
        return False
    subgraph = G.subgraph(nodes_subset)
    return nx.is_connected(subgraph)


def get_room_area_m2(G, r):
    """Returns room area strictly in square metres (m²)."""
    return float(G.nodes[r].get("area_m2", G.nodes[r].get("area", 0.0)))


def generate_partitions(G, k, scale, max_iterations=2500, state=None):
    """
    Generates valid partitions of graph G into k connected components.
    Yields a list of sets, where each set is a connected component satisfying:
      - area <= 100 m²
      - node count <= 5
    Includes iteration guard to prevent combinatorial explosion on large plans.
    """
    if state is None:
        state = {"count": 0}

    nodes = list(G.nodes())
    n = len(nodes)

    if n < k:
        return

    # Capacity pruning
    room_areas = [get_room_area_m2(G, u) for u in nodes]
    total_area = sum(room_areas)
    effective_cap = max(100.0, max(room_areas))
    if total_area > k * effective_cap + 1e-6 or n > k * 5:
        return

    # Base case: k == 1
    if k == 1:
        state["count"] += 1
        if is_connected_subgraph(G, set(nodes)):
            area = sum(get_room_area_m2(G, u) for u in nodes)
            # Allow single room exceeding 100m² to form a solo hub
            if (area <= 100.0 + 1e-6 or len(nodes) == 1) and len(nodes) <= 5:
                yield [set(nodes)]
        return

    # Recursive case: try subsets for the first component
    first_node = nodes[0]
    remaining_nodes = nodes[1:]

    for i in range(len(remaining_nodes) + 1):
        if state["count"] >= max_iterations:
            return

        for combo in itertools.combinations(remaining_nodes, i):
            state["count"] += 1
            if state["count"] >= max_iterations:
                return

            comp1 = {first_node} | set(combo)
            if len(comp1) > 5:
                continue

            if not is_connected_subgraph(G, comp1):
                continue

            area1 = sum(get_room_area_m2(G, u) for u in comp1)
            if area1 > 100.0 + 1e-6 and len(comp1) > 1:
                continue

            remaining_nodes_set = set(nodes) - comp1
            if not remaining_nodes_set:
                continue

            sub_G = G.subgraph(remaining_nodes_set)
            for sub_partition in generate_partitions(sub_G, k - 1, scale, max_iterations, state):
                yield [comp1] + sub_partition


def greedy_partition_fallback(G, eligible_nodes, k, scale):
    """
    Fast, deterministic fallback partitioner for complex or large floor plans.
    Grows contiguous zones from seed rooms until capacity constraints are met.
    """
    unassigned = set(eligible_nodes)
    areas = {r: get_room_area_m2(G, r) for r in eligible_nodes}
    zones = []

    while unassigned:
        sub = G.subgraph(unassigned)
        seed = max(unassigned, key=lambda r: (sub.degree(r), areas[r], r))
        zone = {seed}
        unassigned.remove(seed)
        cur_area = areas[seed]

        # Grow zone along neighbors
        frontier = [n for n in G.neighbors(seed) if n in unassigned]
        while frontier and len(zone) < 5:
            best_nxt = None
            for nxt in sorted(frontier, key=lambda r: (-sub.degree(r), -areas[r])):
                if cur_area + areas[nxt] <= 100.0 + 1e-6:
                    best_nxt = nxt
                    break
            if best_nxt is None:
                break
            zone.add(best_nxt)
            unassigned.remove(best_nxt)
            cur_area += areas[best_nxt]
            frontier = [n for r in zone for n in G.neighbors(r) if n in unassigned]

        zones.append(zone)

    return zones


def find_best_hub_in_component(G, component_nodes, nodes_dict, scale):
    """
    Finds the optimal room in the component to host the hub by prioritizing:
    1. Higher degree in the territory's induced subgraph (subG.degree) - avoids leaf rooms that force doorway retracing.
    2. Room type suitability: common areas (living, kitchen, hallway) preferred over private bedrooms/bathrooms.
    3. Minimum total shortest-path distance to all other rooms in the component.
    4. Deterministic room ID sorting as final tie-breaker.
    """
    subG = G.subgraph(component_nodes)
    type_priority = {
        'living': 0, 'kitchen': 1, 'hallway': 1, 'corridor': 1, 'entry': 1,
        'storage': 2, 'bedroom': 3, 'bathroom': 4, 'balcony': 5
    }

    best_room = None
    best_key = (float('inf'), float('inf'), float('inf'), "")
    best_cost = float('inf')

    for hub_candidate in sorted(component_nodes):
        total_dist = 0
        for target_node in component_nodes:
            if hub_candidate != target_node:
                try:
                    dist = nx.shortest_path_length(G, hub_candidate, target_node)
                    total_dist += dist
                except nx.NetworkXNoPath:
                    total_dist += 999

        deg = subG.degree(hub_candidate) if subG.has_node(hub_candidate) else 0
        r_type = G.nodes[hub_candidate].get('type', '').lower()
        t_prio = type_priority.get(r_type, 10)

        # Maximize degree (-deg), minimize type priority (t_prio), minimize total_dist, deterministic ID
        key = (-deg, t_prio, total_dist, hub_candidate)
        if key < best_key:
            best_key = key
            best_room = hub_candidate
            best_cost = total_dist

    return best_room, best_cost


def partition_and_place_hubs(G, nodes_dict, scale, min_hubs, verbose=True):
    """
    Finds the optimal partitioning of eligible rooms in G into >= min_hubs components
    and selects the best hub room for each component.
    """
    # Only partition eligible rooms
    eligible_nodes = [n for n in G.nodes() if G.nodes[n].get("eligible", False)]
    subG = G.subgraph(eligible_nodes)

    best_partition = None
    best_hubs = None
    best_total_cost = float('inf')
    best_tie_breaker = (float('inf'), float('inf'))

    # Hub suitability preference: common/utility areas (living, kitchen) preferred over private bedrooms
    type_priority = {'living': 0, 'kitchen': 1, 'storage': 2, 'bedroom': 3}

    k = min_hubs
    total_nodes = len(eligible_nodes)

    while k <= total_nodes:
        if verbose:
            print(f"Trying to partition into {k} hubs...")
        found_valid = False

        state = {"count": 0}
        for partition in generate_partitions(subG, k, scale, max_iterations=3000, state=state):
            found_valid = True
            current_hubs = {}
            total_cost = 0

            for comp in partition:
                hub_room, cost = find_best_hub_in_component(G, comp, nodes_dict, scale)
                current_hubs[hub_room] = comp
                total_cost += cost

            # Calculate assigned-area gap (primary competition tie-breaker)
            h_areas = [sum(get_room_area_m2(G, r) for r in comp) for comp in partition]
            area_gap = (max(h_areas) - min(h_areas)) if len(h_areas) >= 2 else 0.0

            # Calculate hub room suitability score (secondary tie-breaker)
            type_score = sum(
                type_priority.get(G.nodes[h].get('type', '').lower(), 99)
                for h in current_hubs.keys()
            )

            # Combined tie-breaker: type suitability then area gap balance
            tb_score = (type_score, round(area_gap, 2))

            if (total_cost < best_total_cost) or (total_cost == best_total_cost and tb_score < best_tie_breaker):
                best_total_cost = total_cost
                best_tie_breaker = tb_score
                best_partition = partition
                best_hubs = current_hubs

        # If combinatorial search didn't yield a valid partition within iteration limit, use greedy fallback
        if not found_valid and state["count"] >= 3000:
            print("  Combinatorial search reached limit. Employing greedy zone-growing fallback...")
            fallback_partition = greedy_partition_fallback(G, eligible_nodes, k, scale)
            if fallback_partition:
                current_hubs = {}
                total_cost = 0
                for comp in fallback_partition:
                    hub_room, cost = find_best_hub_in_component(G, comp, nodes_dict, scale)
                    current_hubs[hub_room] = comp
                    total_cost += cost
                best_hubs = current_hubs
                best_total_cost = total_cost
                best_partition = fallback_partition
                found_valid = True

        if found_valid:
            break
        k += 1

    if best_hubs is None:
        best_hubs = {r: {r} for r in eligible_nodes}
        best_total_cost = 0

    return best_hubs, best_total_cost


def visualize_partitioned_plan(json_path, G, nodes_dict, scale, best_hubs, output_image_path=None, show_plot=True):
    """
    Visualizes the floor plan with rooms color-coded by their assigned hub territory
    and marked hub locations.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        plan = json.load(f)

    room_map = {r["id"]: r for r in plan.get("rooms", [])}

    # Color palette for territories
    colors = ['#cce5ff', '#d4edda', '#fff3cd', '#f8d7da', '#e2e3e5', '#d1ecf1']
    edge_colors = ['#004085', '#155724', '#856404', '#721c24', '#383d41', '#0c5460']

    fig, ax = plt.subplots(figsize=(10, 8))

    hub_to_color = {}
    for idx, hub_room in enumerate(sorted(best_hubs.keys())):
        c_idx = idx % len(colors)
        hub_to_color[hub_room] = (colors[c_idx], edge_colors[c_idx])

    # Plot room polygons with territory fills
    for hub_idx, hub_room in enumerate(sorted(best_hubs.keys()), start=1):
        assigned_rooms = best_hubs[hub_room]
        face_color, edge_color = hub_to_color[hub_room]

        for room_id in assigned_rooms:
            room = room_map[room_id]
            poly = shape(room["polygon"])
            polys = poly.geoms if hasattr(poly, "geoms") else [poly]

            for p in polys:
                x, y = p.exterior.xy
                ax.fill(x, y, color=face_color, alpha=0.7)
                ax.plot(x, y, color=edge_color, linewidth=1.8)

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

    # Plot door edges
    for u, v in G.edges():
        u_pt = nodes_dict[u]
        v_pt = nodes_dict[v]
        # Check if internal to same territory
        u_hub = next((h for h, rooms in best_hubs.items() if u in rooms), None)
        v_hub = next((h for h, rooms in best_hubs.items() if v in rooms), None)
        if u_hub == v_hub and u_hub is not None:
            _, ec = hub_to_color[u_hub]
            ax.plot([u_pt.x, v_pt.x], [u_pt.y, v_pt.y], color=ec, linestyle='--', linewidth=2.2, zorder=3)
        else:
            ax.plot([u_pt.x, v_pt.x], [u_pt.y, v_pt.y], color='gray', linestyle=':', linewidth=1.2, alpha=0.5, zorder=2)

    # Plot normal nodes and hubs
    for node_id, pt in nodes_dict.items():
        if node_id not in best_hubs:
            ax.plot(pt.x, pt.y, 'o', color='navy', markersize=6, zorder=4)

    for hub_idx, hub_room in enumerate(sorted(best_hubs.keys()), start=1):
        pt = nodes_dict[hub_room]
        ax.plot(pt.x, pt.y, '*', color='crimson', markersize=16, markeredgecolor='black', zorder=6, label=f"Hub {hub_idx} ({hub_room})")

    ax.set_title("Phase 2: Partitioning & Hub Locations", fontsize=12, fontweight='bold')
    ax.set_aspect('equal')
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(loc='upper right')
    plt.tight_layout()

    if output_image_path:
        plt.savefig(output_image_path, dpi=150)
        print(f"Partition visualization saved to: {output_image_path}")

    if show_plot:
        plt.show()


def run_phase2(json_path="sample_plan.json", show_plot=False, save_img=None, plan_data=None, verbose=True):
    # 1. Run Phase 1 data pipeline (or reuse pre-loaded data)
    if plan_data is not None:
        G, nodes_dict, scale, min_hubs = plan_data
    else:
        G, nodes_dict, scale, min_hubs = load_and_process_plan(json_path, show_plot=False, verbose=verbose)

    # 2. Partition graph and place hubs
    best_hubs, best_total_cost = partition_and_place_hubs(G, nodes_dict, scale, min_hubs, verbose=verbose)

    # 3. Print resulting hubs in the exact expected format
    if verbose:
        print("\n--- Phase 2 Partitioning Results ---")
    hub_idx = 1
    result_dict = {}

    for hub_room in sorted(best_hubs.keys()):
        assigned = sorted(list(best_hubs[hub_room]))
        assigned_str = ", ".join(assigned)
        if verbose:
            print(f"Hub {hub_idx}: Located in {hub_room}, assigned rooms: {assigned_str}.")
        result_dict[f"Hub_{hub_idx}"] = {
            "hub_location": hub_room,
            "assigned_rooms": assigned,
            "total_rooms": len(assigned),
            "total_area_m2": round(sum(get_room_area_m2(G, r) for r in assigned), 2)
        }
        hub_idx += 1

    hub_areas = [result_dict[h]["total_area_m2"] for h in result_dict]
    area_gap = (max(hub_areas) - min(hub_areas)) if len(hub_areas) >= 2 else 0.0
    if verbose:
        print(f"Total Heuristic Distance Cost: {best_total_cost}")
        print(f"Assigned Area Gap (Official Tie-Breaker): {area_gap:.2f} m²\n")

    if show_plot or save_img:
        visualize_partitioned_plan(json_path, G, nodes_dict, scale, best_hubs, output_image_path=save_img, show_plot=show_plot)

    return best_hubs, best_total_cost


if __name__ == "__main__":
    target_json = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "sample_plan.json"
    save_flag = "floor_plan_phase2.png" if "--save" in sys.argv else None
    show_flag = "--show" in sys.argv
    run_phase2(target_json, show_plot=show_flag, save_img=save_flag)
