"""Tests for PDF report generation and independent verification reporting."""
from pathlib import Path
import pytest
from sutrayana.model import Plan
from sutrayana.solver import solve_plan
from sutrayana.validation import validate
from sutrayana.report import build_pdf_report, render_plan_images


def test_build_pdf_report_valid_run():
    plan = Plan("examples/plan_00124.json")
    solution = solve_plan(plan)
    validation = validate(plan, solution)

    # Render input/output images
    input_png, output_png = render_plan_images(plan, solution)
    assert input_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert output_png.startswith(b"\x89PNG\r\n\x1a\n")

    report_payload = {
        "plan_id": plan.id,
        "source": "ResPlan example",
        "status": "VALIDATED",
        "lower_bound_hubs": 2,
        "wire_clearance_m": 0.0,
        "development": solution,
        "validation": validation,
        "reported_metrics": solution["reported_metrics"],
        "timings": {"load_s": 0.005, "zone_s": 0.002, "solve_s": 0.015, "validate_s": 0.003, "total_s": 0.025},
        "diagnostics": [],
        "input_image": input_png,
        "output_image": output_png,
        "submission": solution
    }

    pdf_bytes = build_pdf_report(report_payload)
    assert len(pdf_bytes) > 1000
    # PDF starts with %PDF
    assert pdf_bytes.startswith(b"%PDF")


def test_build_pdf_report_withheld_submission_on_failure():
    plan = Plan("examples/plan_00124.json")
    # Simulate a rejected solution
    invalid_validation = {"valid": False, "errors": [{"rule": "capacity", "message": "Exceeded 5 nodes limit"}]}
    report_payload = {
        "plan_id": plan.id,
        "source": "Synthetic negative test",
        "status": "FAILED",
        "lower_bound_hubs": 2,
        "development": {},
        "validation": invalid_validation,
        "timings": {"total_s": 0.01},
        "diagnostics": [{"code": "CAPACITY_VIOLATION", "message": "Hub contains too many devices"}],
        "submission": None
    }
    pdf_bytes = build_pdf_report(report_payload)
    assert pdf_bytes.startswith(b"%PDF")
