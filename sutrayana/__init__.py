"""Geometry-validated cable ring planning."""

from .solver import solve_plan
from .resilience import simulate_single_cut, stress_test_all_single_cuts, simulate_multi_cut

__all__ = [
    "solve_plan",
    "simulate_single_cut",
    "stress_test_all_single_cuts",
    "simulate_multi_cut",
    "build_pdf_report",
    "render_plan_images",
    "generate_plan_report_pdf",
]


def __getattr__(name):
    if name in ("build_pdf_report", "render_plan_images", "generate_plan_report_pdf"):
        from . import report
        return getattr(report, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
