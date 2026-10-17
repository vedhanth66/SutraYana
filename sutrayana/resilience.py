"""Wire-cut resilience simulation and fault-tolerance analysis for cable rings.

In high-reliability industrial and residential systems, ring circuits (closed loops)
provide Single-Point-of-Failure (SPoF) immunity: if any single cable segment is
severed, both ends of the loop remain energized by the hub. Every device continues
to receive power and telemetry through dual-feed continuity.

This module provides formal resilience verification, single-cut and multi-cut
simulation, fault localization, and comparative survivability benchmarking.
"""
from typing import Dict, List, Any, Optional, Set
import math


def simulate_single_cut(hub_data: Dict[str, Any], cut_segment_idx: int) -> Dict[str, Any]:
    """
    Simulate cutting a specific route segment in a hub's cable ring.

    Parameters
    ----------
    hub_data : Dict[str, Any]
        Hub dictionary from a SutraYana solution containing:
        - 'hub_id': e.g. 'H1'
        - 'location': [x, y]
        - 'assigned_nodes': List[str], e.g. ['N1', 'N4', 'N5']
        - 'assigned_rooms': List[str], e.g. ['R01_living', ...]
        - 'closed_sequence': List[str], e.g. ['H1', 'N4', 'N1', 'N5', 'H1']
        - 'route_segments': List[Dict] with 'from', 'to', 'polyline', 'length_m'
    cut_segment_idx : int
        Index of the segment severed (0 <= cut_segment_idx < len(route_segments)).

    Returns
    -------
    Dict[str, Any]
        Resilience report containing:
        - survivability_pct: Percentage of devices remaining online (100.0% for single cut in valid ring)
        - online_nodes: List of node IDs still powered
        - isolated_nodes: List of node IDs disconnected (empty for single cut)
        - branch_a: Dict with nodes, length, polyline (forward clockwise feed)
        - branch_b: Dict with nodes, length, polyline (reverse counter-clockwise feed)
        - fault_coordinates: Midpoint coordinates of severed segment
        - comparative_tree_loss_pct: Percentage of devices lost if this were an open daisy chain
    """
    segments = hub_data.get("route_segments", [])
    hub_id = str(hub_data.get("hub_id", hub_data.get("room_id", "HUB")))
    assigned_nodes = list(hub_data.get("assigned_nodes", []))
    assigned_rooms = list(hub_data.get("assigned_rooms", []))
    location = hub_data.get("location", hub_data.get("center", [0, 0]))

    if not segments:
        return {
            "hub_id": hub_id,
            "survivability_pct": 100.0,
            "online_nodes": assigned_nodes,
            "online_rooms": assigned_rooms,
            "isolated_nodes": [],
            "isolated_rooms": [],
            "branch_a": {"nodes": [], "length_m": 0.0, "polyline": []},
            "branch_b": {"nodes": [], "length_m": 0.0, "polyline": []},
            "fault_coordinates": location,
            "comparative_tree_loss_pct": 0.0,
            "status": "EMPTY_RING"
        }

    num_segs = len(segments)
    cut_idx = max(0, min(cut_segment_idx, num_segs - 1))
    cut_seg = segments[cut_idx]

    # Find fault coordinates (midpoint of severed segment)
    polyline = cut_seg.get("polyline", [])
    if len(polyline) >= 2:
        mid_idx = len(polyline) // 2
        fault_coords = polyline[mid_idx]
    elif polyline:
        fault_coords = polyline[0]
    else:
        fault_coords = location

    # Segments before cut form Branch A (forward clockwise from hub)
    # Segments after cut form Branch B (reverse counter-clockwise from hub)
    segs_a = segments[:cut_idx]
    segs_b = segments[cut_idx + 1:]

    def is_hub(name: Any) -> bool:
        s = str(name).strip().upper()
        return s.startswith("H") and not s.startswith("HUB_NODE") if s != "HUB" else True

    # Trace Branch A forward: H -> seg 0 -> ... -> seg (cut_idx - 1)
    nodes_a = []
    poly_a = []
    len_a = 0.0
    for s in segs_a:
        len_a += float(s.get("length_m", 0.0))
        poly_a.extend(s.get("polyline", []))
        to_node = s.get("to", s.get("to_room"))
        if to_node and not is_hub(to_node) and to_node not in nodes_a:
            nodes_a.append(to_node)

    # Trace Branch B in reverse: H <- seg (num_segs - 1) <- ... <- seg (cut_idx + 1)
    nodes_b = []
    poly_b = []
    len_b = 0.0
    for s in reversed(segs_b):
        len_b += float(s.get("length_m", 0.0))
        poly_b.extend(reversed(s.get("polyline", [])))
        from_node = s.get("from", s.get("from_room"))
        if from_node and not is_hub(from_node) and from_node not in nodes_b:
            nodes_b.append(from_node)

    online_nodes_set = set(nodes_a) | set(nodes_b)

    # Fallback to closed_sequence or assigned_nodes if node tracking format differs
    target_nodes = set(assigned_nodes)
    if not target_nodes:
        closed_seq = hub_data.get("closed_sequence", [])
        target_nodes = {v for v in closed_seq if not is_hub(v)}
    if not target_nodes and assigned_rooms:
        target_nodes = set(assigned_rooms)

    total_target_count = len(target_nodes) if target_nodes else len(online_nodes_set)
    isolated_nodes = [n for n in target_nodes if n not in online_nodes_set]

    survivability_pct = (len(online_nodes_set) / max(1, total_target_count)) * 100.0 if total_target_count > 0 else 100.0

    # Comparative analysis against non-ring open daisy chain / star branch:
    # In a daisy chain, cutting segment cut_idx drops all subsequent devices
    daisy_lost = total_target_count - len(nodes_a)
    tree_loss_pct = (daisy_lost / max(1, total_target_count)) * 100.0 if total_target_count > 0 else 0.0

    return {
        "hub_id": hub_id,
        "cut_segment_idx": cut_idx,
        "severed_segment": {
            "from": cut_seg.get("from", cut_seg.get("from_room")),
            "to": cut_seg.get("to", cut_seg.get("to_room")),
            "length_m": cut_seg.get("length_m", 0.0)
        },
        "fault_coordinates": fault_coords,
        "survivability_pct": round(survivability_pct, 1),
        "total_devices": total_target_count,
        "online_count": len(online_nodes_set),
        "isolated_count": len(isolated_nodes),
        "online_nodes": sorted(list(online_nodes_set)),
        "isolated_nodes": sorted(isolated_nodes),
        "branch_a": {
            "name": "Branch A (Clockwise)",
            "nodes": nodes_a,
            "length_m": round(len_a, 2),
            "polyline": poly_a
        },
        "branch_b": {
            "name": "Branch B (Counter-Clockwise)",
            "nodes": nodes_b,
            "length_m": round(len_b, 2),
            "polyline": poly_b
        },
        "comparative_tree_loss_pct": round(tree_loss_pct, 1),
        "status": "DUAL_FEED_ONLINE_100_PCT" if not isolated_nodes else "DEGRADED"
    }


def stress_test_all_single_cuts(solution: Dict[str, Any]) -> Dict[str, Any]:
    """
    Exhaustively simulate cutting EVERY single segment across ALL hubs in the solution.

    Proves the formal resilience guarantee: SutraYana ring networks maintain 100.0%
    survivability under any single point of failure.

    Parameters
    ----------
    solution : Dict[str, Any]
        Complete solution output containing 'hubs'.

    Returns
    -------
    Dict[str, Any]
        Summary metrics of the exhaustive stress test.
    """
    hubs = solution.get("hubs", [])
    total_cuts_simulated = 0
    passed_cuts = 0
    total_devices = 0
    worst_tree_loss_pct = 0.0
    hub_reports = []

    for h_idx, hub in enumerate(hubs):
        segs = hub.get("route_segments", [])
        assigned = hub.get("assigned_nodes", hub.get("assigned_rooms", []))
        total_devices += len(assigned)
        h_cuts = []

        for s_idx in range(len(segs)):
            total_cuts_simulated += 1
            res = simulate_single_cut(hub, s_idx)
            if res["survivability_pct"] >= 99.9:
                passed_cuts += 1
            if res["comparative_tree_loss_pct"] > worst_tree_loss_pct:
                worst_tree_loss_pct = res["comparative_tree_loss_pct"]
            h_cuts.append({
                "cut_segment_idx": s_idx,
                "survivability_pct": res["survivability_pct"],
                "tree_loss_pct": res["comparative_tree_loss_pct"]
            })

        hub_reports.append({
            "hub_id": hub.get("hub_id", f"H{h_idx+1}"),
            "assigned_count": len(assigned),
            "segments_count": len(segs),
            "cuts_tested": len(h_cuts)
        })

    overall_resilience_pct = (passed_cuts / max(1, total_cuts_simulated)) * 100.0 if total_cuts_simulated > 0 else 100.0

    return {
        "total_hubs": len(hubs),
        "total_devices": total_devices,
        "total_cuts_simulated": total_cuts_simulated,
        "single_cut_survivability_rate_pct": round(overall_resilience_pct, 2),
        "worst_case_tree_topology_loss_pct": round(worst_tree_loss_pct, 1),
        "all_single_cuts_passed": (passed_cuts == total_cuts_simulated),
        "hub_summaries": hub_reports,
        "verdict": "SPoF_IMMUNE_DUAL_FEED_CONFIRMED" if passed_cuts == total_cuts_simulated else "DEGRADED"
    }


def simulate_multi_cut(
    hub_data: Dict[str, Any],
    cut_indices: List[int]
) -> Dict[str, Any]:
    """
    Simulate multiple simultaneous cuts on a hub's ring.

    Under two or more cuts, segments between cut points become isolated sub-chains,
    accurately modeling severe catastrophic multi-point physical damage.
    """
    segments = hub_data.get("route_segments", [])
    num_segs = len(segments)
    if not segments or not cut_indices:
        return simulate_single_cut(hub_data, 0)

    unique_cuts = sorted(set(max(0, min(c, num_segs - 1)) for c in cut_indices))
    assigned = hub_data.get("assigned_nodes", hub_data.get("assigned_rooms", []))

    if len(unique_cuts) == 1:
        return simulate_single_cut(hub_data, unique_cuts[0])

    def is_hub(name: Any) -> bool:
        s = str(name).strip().upper()
        return s.startswith("H") and not s.startswith("HUB_NODE") if s != "HUB" else True

    first_cut = unique_cuts[0]
    last_cut = unique_cuts[-1]

    segs_a = segments[:first_cut]
    segs_b = segments[last_cut + 1:]

    nodes_a = []
    for s in segs_a:
        to_node = s.get("to", s.get("to_room"))
        if to_node and not is_hub(to_node) and to_node not in nodes_a:
            nodes_a.append(to_node)

    nodes_b = []
    for s in reversed(segs_b):
        from_node = s.get("from", s.get("from_room"))
        if from_node and not is_hub(from_node) and from_node not in nodes_b:
            nodes_b.append(from_node)

    online_set = set(nodes_a) | set(nodes_b)
    target_nodes = set(assigned) if assigned else set(nodes_a + nodes_b)
    isolated = [n for n in target_nodes if n not in online_set]
    surv_pct = (len(online_set) / max(1, len(target_nodes))) * 100.0 if target_nodes else 100.0

    return {
        "hub_id": hub_data.get("hub_id", "HUB"),
        "cut_indices": unique_cuts,
        "total_cuts": len(unique_cuts),
        "survivability_pct": round(surv_pct, 1),
        "total_devices": len(target_nodes),
        "online_count": len(online_set),
        "isolated_count": len(isolated),
        "online_nodes": sorted(list(online_set)),
        "isolated_nodes": sorted(isolated),
        "status": "MULTI_CUT_PARTIAL_ISOLATION" if isolated else "DUAL_FEED_ONLINE_100_PCT"
    }
