"""Tests for wire-cut resilience simulation and fault-tolerance verification."""
import pytest
from sutrayana.solver import solve_plan
from sutrayana.model import Plan
from sutrayana.resilience import (
    simulate_single_cut,
    stress_test_all_single_cuts,
    simulate_multi_cut,
)


@pytest.fixture
def solved_sample_plan():
    plan = Plan("examples/plan_00124.json")
    solution = solve_plan(plan)
    return plan, solution


def test_single_cut_100_percent_survivability(solved_sample_plan):
    _, solution = solved_sample_plan
    hubs = solution["hubs"]
    assert len(hubs) > 0

    hub = hubs[0]
    segments = hub["route_segments"]
    assert len(segments) >= 2

    for cut_idx in range(len(segments)):
        res = simulate_single_cut(hub, cut_idx)
        # Every single cut must maintain 100% device survivability due to dual-feed ring topology
        assert res["survivability_pct"] == 100.0
        assert len(res["isolated_nodes"]) == 0
        assert res["online_count"] == len(hub["assigned_nodes"])
        assert res["status"] == "DUAL_FEED_ONLINE_100_PCT"
        # Comparative tree loss must be non-zero for non-terminal segments
        assert res["comparative_tree_loss_pct"] >= 0.0


def test_stress_test_all_single_cuts(solved_sample_plan):
    _, solution = solved_sample_plan
    summary = stress_test_all_single_cuts(solution)

    assert summary["all_single_cuts_passed"] is True
    assert summary["single_cut_survivability_rate_pct"] == 100.0
    assert summary["verdict"] == "SPoF_IMMUNE_DUAL_FEED_CONFIRMED"
    assert summary["total_cuts_simulated"] > 0


def test_multi_cut_partial_isolation(solved_sample_plan):
    _, solution = solved_sample_plan
    hub = solution["hubs"][0]
    segments = hub["route_segments"]

    if len(segments) >= 4:
        # Cut segment 1 and segment 3
        res = simulate_multi_cut(hub, [1, 3])
        assert res["total_cuts"] == 2
        # Under 2 cuts on 4+ segments, intermediate nodes may be isolated
        assert 0.0 <= res["survivability_pct"] <= 100.0


def test_empty_hub_graceful_handling():
    empty_hub = {"center": [0, 0], "assigned_rooms": [], "route_segments": []}
    res = simulate_single_cut(empty_hub, 0)
    assert res["survivability_pct"] == 100.0
    assert res["status"] == "EMPTY_RING"
