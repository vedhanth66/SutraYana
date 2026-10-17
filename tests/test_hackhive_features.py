"""Unit and integration tests for HackHive features:
- CLI commands (hackhive solve, check)
- Ranking system (fewest hubs, worse J of two readings, area gap)
- Checker mirror validation gate
- Labelled what-ifs (D5 device cap, Area cap, Door clearance)
"""
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sutrayana.model import Plan
from sutrayana.solver import solve_plan, compute_hub_lower_bound
from sutrayana.validation import validate
from sutrayana.cli import main as cli_main
SAMPLE_PLAN = ROOT / "sample_plan.json"


def test_solve_metadata_and_ranking_system(tmp_path):
    """Test that solve_plan computes dual readings, ranking criterion, and decision trace."""
    plan = Plan(str(SAMPLE_PLAN))
    out = solve_plan(plan)

    assert "solver" in out
    solver_meta = out["solver"]
    assert solver_meta.get("checker_mirror_passed") is True
    assert "ranking_criterion" in solver_meta
    assert "worse_J" in solver_meta
    assert "decision_trace" in solver_meta
    assert len(solver_meta["decision_trace"]) > 0

    trace_entry = solver_meta["decision_trace"][0]
    assert "hubs_count" in trace_entry
    assert "solver_J" in trace_entry
    assert "checker_J" in trace_entry
    assert "worse_J" in trace_entry
    assert "passed_checker" in trace_entry
    assert trace_entry["status"] == "PASSED_CHECKER"

    # Verify that worse_J >= solver_J
    assert solver_meta["worse_J"] >= out["reported_metrics"]["total_cost_J"] - 1e-4


def test_hackhive_cli_solve_and_check(tmp_path):
    """Test CLI commands solve and check."""
    out_file = tmp_path / "cli_out.json"
    ret = cli_main(["solve", str(SAMPLE_PLAN), str(out_file), "-q"])
    assert ret == 0
    assert out_file.exists()

    # Run check command on the generated output
    ret_check = cli_main(["check", str(SAMPLE_PLAN), str(out_file), "-q"])
    assert ret_check == 0

    # Corrupt the output to test that checker mirror catches violations
    corrupted = json.loads(out_file.read_text(encoding="utf-8"))
    corrupted["hubs"][0]["closed_sequence"][0] = "ILLEGAL_START"
    corrupt_file = tmp_path / "corrupted.json"
    corrupt_file.write_text(json.dumps(corrupted), encoding="utf-8")

    ret_corrupt = cli_main(["check", str(SAMPLE_PLAN), str(corrupt_file), "-q"])
    assert ret_corrupt == 1


def test_what_if_parameter_variations():
    """Test labelled what-ifs: D5 device cap and area cap variations."""
    plan = Plan(str(SAMPLE_PLAN))

    # Standard: max_nodes=5, max_area=100
    lb_std = compute_hub_lower_bound(plan, max_nodes_per_hub=5, max_area_per_hub=100.0)

    # Restrictive D5: max_nodes=2
    lb_tight_nodes = compute_hub_lower_bound(plan, max_nodes_per_hub=2, max_area_per_hub=100.0)
    assert lb_tight_nodes >= lb_std

    # Restrictive area: max_area=20
    lb_tight_area = compute_hub_lower_bound(plan, max_nodes_per_hub=5, max_area_per_hub=20.0)
    assert lb_tight_area >= lb_std
