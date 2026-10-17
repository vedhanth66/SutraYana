"""Geometry-validated cable ring planning."""

from .solver import solve_plan
from .resilience import simulate_single_cut, stress_test_all_single_cuts, simulate_multi_cut
from .report import build_pdf_report, render_plan_images, generate_plan_report_pdf

__all__ = ["solve_plan", "simulate_single_cut", "stress_test_all_single_cuts", "simulate_multi_cut", "build_pdf_report", "render_plan_images", "generate_plan_report_pdf"]
