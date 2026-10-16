"""Compatibility wrapper for the web app's solver entry points."""

from __future__ import annotations

from .model import Plan
from .solver import solve_plan

__all__ = ["solve_plan", "solve_bounded"]


def solve_bounded(source, *, wire_clearance=0.5, timeout=30, enhanced=False, open_min=0.5, **kwargs):
    """Compatibility shim for the web UI, which expects a bounded solve result.

    The current solver exposes a single solve_plan() interface. The web app calls
    solve_bounded(raw, wire_clearance=..., timeout=..., enhanced=...) and treats the
    return value as a dict with an ok flag and an output payload.
    """
    if not isinstance(source, Plan):
        source = Plan(source, open_min=open_min, wire_clearance=wire_clearance)
    output = solve_plan(source, open_min=open_min)
    return {"ok": True, "output": output, "plan_id": output.get("plan_id", getattr(source, "id", "plan"))}
