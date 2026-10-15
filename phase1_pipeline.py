import os
import sys
import json
import math
import tempfile
import networkx as nx

# Configure Matplotlib writable cache directory if not already set
os.environ.setdefault('MPLCONFIGDIR', tempfile.gettempdir())
import matplotlib.pyplot as plt
from shapely.geometry import shape, Point, Polygon, MultiPolygon


def load_and_process_plan(json_path, output_image_path=None, show_plot=True, verbose=True):
    """
    Phase 1 Core Data Pipeline:
    1. Loads ResPlan JSON.
    2. Calculates scale using math.sqrt(inner.area / area).
    3. Identifies all eligible rooms (living, bedroom, kitchen, storage).
    4. Extracts fixed node for each eligible room.
    5. Builds NetworkX graph where nodes are rooms and edges are doors only.
    6. Prints total eligible area (m²), eligible nodes, and minimum hubs required.
    7. Plots the floor plan with eligible rooms highlighted, nodes marked, and door connections.
    """
    if isinstance(json_path, dict):
        plan = json_path
        p_name = plan.get("id", "in_memory_plan")
    else:
        p_name = str(json_path)
        with open(json_path, 'r', encoding='utf-8') as f:
            plan = json.load(f)

    if show_plot and verbose:
        print(f"\n--- Loading and Processing Plan: {p_name} ---")

    # 1. Calculate Scale
    if isinstance(plan.get("inner"), dict) and "area" in plan["inner"]:
        inner_area_units = float(plan["inner"]["area"])
    elif "inner" in plan:
        inner_geom = shape(plan["inner"])
        inner_area_units = float(inner_geom.area)
    else:
        raise ValueError("Plan JSON must contain an 'inner' key with area or polygon.")

    area_m2 = float(plan["area"])
    if area_m2 <= 0:
        raise ValueError("Plan JSON has non-positive area in m².")

    scale = math.sqrt(inner_area_units / area_m2)
    if verbose:
        print(f"Scale: {scale:.4f} units/m")

    # 2. Identify Rooms and Extract Nodes
    eligible_types = {"living", "bedroom", "kitchen", "storage"}
    all_rooms = {}
    eligible_rooms = {}
    nodes = {}

    G = nx.Graph()

    for room in plan.get("rooms", []):
        room_id = room["id"]
        r_type = room.get("type", "").lower()
        is_eligible = (r_type in eligible_types)
        all_rooms[room_id] = room
        if is_eligible:
            eligible_rooms[room_id] = room

        # Parse polygon geometry
        poly = shape(room["polygon"])
        
        # Ensure area attribute is present
        if "area" not in room or room["area"] is None:
            room["area"] = poly.area

        # Extract fixed node (either from JSON or representative interior point)
        if "node" in room and isinstance(room["node"], dict) and "x" in room["node"] and "y" in room["node"]:
            nodes[room_id] = Point(float(room["node"]["x"]), float(room["node"]["y"]))
        else:
            # Deterministic node extraction: interior point with clearance or representative point
            clearance = 0.5 * scale  # 0.5m clearance in unit coordinates
            eroded = poly.buffer(-clearance)
            if not eroded.is_empty:
                if isinstance(eroded, MultiPolygon):
                    eroded = max(eroded.geoms, key=lambda p: p.area)
                pt = eroded.centroid if eroded.contains(eroded.centroid) else eroded.representative_point()
            else:
                pt = poly.representative_point()
            nodes[room_id] = pt

        # Add all rooms to graph G with eligibility attribute
        G.add_node(room_id, eligible=is_eligible, **room)

    # 3. Build Full Graph (Add ALL doors in the house topology)
    for door in plan.get("doors", []):
        r1, r2 = door.get("room_a"), door.get("room_b")
        if r1 in all_rooms and r2 in all_rooms:
            G.add_edge(r1, r2, type="door", door_id=door.get("id"), polygon=door.get("polygon"))

    # 4. Calculate Minimum Hubs (on eligible rooms)
    total_area = sum(float(r["area"]) / (scale ** 2) for r in eligible_rooms.values())
    total_nodes = len(eligible_rooms)
    min_hubs_area = math.ceil(total_area / 100.0) if total_area > 0 else 0
    min_hubs_nodes = math.ceil(total_nodes / 5.0) if total_nodes > 0 else 0
    min_hubs = max(min_hubs_area, min_hubs_nodes)

    if verbose:
        print(f"Total Eligible Area: {total_area:.2f} m²")
        print(f"Total Eligible Nodes: {total_nodes}")
        print(f"Minimum Hubs Required: {min_hubs}")
        print(f"Door Edges in Graph: {list(G.edges())}")

    # 5. Visualize (only if requested)
    if show_plot or output_image_path:
        fig, ax = plt.subplots(figsize=(10, 8))

        # Plot eligible rooms
        first_room = True
        for room_id, room in eligible_rooms.items():
            poly = shape(room["polygon"])
            
            # Plot polygon exterior / parts
            polys_to_plot = poly.geoms if hasattr(poly, "geoms") else [poly]
            for p in polys_to_plot:
                x, y = p.exterior.xy
                lbl = "Eligible Room" if first_room else ""
                ax.plot(x, y, color='royalblue', linewidth=1.8, label=lbl)
                ax.fill(x, y, color='skyblue', alpha=0.25)
                first_room = False

            # Room label at centroid
            if "centroid" in room and isinstance(room["centroid"], dict):
                cx, cy = float(room["centroid"]["x"]), float(room["centroid"]["y"])
            else:
                cx, cy = poly.centroid.x, poly.centroid.y
            
            room_area_m2 = float(room["area"]) / (scale ** 2)
            ax.text(
                cx, cy,
                f"{room_id}\n({room['type']})\n{room_area_m2:.1f} m²",
                fontsize=8,
                ha='center',
                va='center',
                fontweight='bold',
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7, edgecolor="none")
            )

        # Plot nodes
        first_node = True
        for node_id, pt in nodes.items():
            lbl = "Fixed Room Node" if first_node else ""
            ax.plot(pt.x, pt.y, 'ro', markersize=8, zorder=5, label=lbl)
            first_node = False

        # Plot door connections
        first_edge = True
        for u, v in G.edges():
            u_pt = nodes[u]
            v_pt = nodes[v]
            lbl = "Door Connection" if first_edge else ""
            ax.plot([u_pt.x, v_pt.x], [u_pt.y, v_pt.y], 'g--', linewidth=2.2, alpha=0.8, zorder=4, label=lbl)
            first_edge = False

        ax.set_title(
            f"Floor Plan: Eligible Rooms, Fixed Nodes & Door Connections\n"
            f"Eligible Area: {total_area:.2f} m² | Nodes: {total_nodes} | Minimum Hubs: {min_hubs}",
            fontsize=12,
            fontweight='bold'
        )
        ax.set_aspect('equal')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='upper right')
        plt.tight_layout()

        if output_image_path:
            plt.savefig(output_image_path, dpi=150)
            print(f"Visualization saved to: {output_image_path}")

        if show_plot:
            plt.show()
        else:
            plt.close(fig)

    return G, nodes, scale, min_hubs


if __name__ == "__main__":
    target_path = sys.argv[1] if len(sys.argv) > 1 else "sample_plan.json"
    save_img = "floor_plan_phase1.png" if "--save" in sys.argv else None
    load_and_process_plan(target_path, output_image_path=save_img, show_plot=True)
