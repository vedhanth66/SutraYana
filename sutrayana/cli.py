"""SutraYana / HackHive Unified Modular Command-Line Interface.

Provides CLI-first commands:
  hackhive solve <input.json> [<output.json>] [options]
  hackhive check <input.json> <output.json> [options]
  hackhive batch <input_path> [options]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from sutrayana.model import Plan
from sutrayana.solver import solve_plan, compute_hub_lower_bound
from sutrayana.validation import validate


def cmd_solve(args: argparse.Namespace) -> int:
    """Execute cable-ring solver with checker mirror validation."""
    started = time.perf_counter()
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file '{input_path}' not found.", file=sys.stderr)
        return 1

    out_path = Path(args.output) if args.output else input_path.with_name(f"solution_{input_path.stem}.json")
    try:
        plan = Plan(str(input_path), open_min=args.open_min, wire_clearance=args.wire_clearance)
        output = solve_plan(
            plan,
            open_min=args.open_min,
            wire_clearance=args.wire_clearance,
            use_rl=args.rl,
            max_nodes_per_hub=args.device_cap,
            max_area_per_hub=args.area_cap,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp_target.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
        tmp_target.replace(out_path)

        rep = validate(plan, output)
        is_valid = rep.get("valid", False)
        m = output.get("reported_metrics", {})
        dt = time.perf_counter() - started

        if not args.quiet:
            status = "VALID" if is_valid else "INVALID"
            print(f"[{status}] Plan {plan.id} | Hubs: {m.get('hub_count')} | J: {m.get('total_cost_J', 0):.2f} (L={m.get('total_length_m', 0):.1f}m, X={m.get('total_crossings', 0)}, O={m.get('total_overlap_m', 0):.2f}m, B={m.get('total_bends', 0)}) | Time: {dt:.2f}s")
            print(f"Saved solution to: {out_path}")

        # Optional exports
        if args.submission:
            from sutrayana.exporter import format_official_submission
            raw_input = json.loads(input_path.read_text(encoding="utf-8"))
            if not is_valid:
                print("Warning: official submission withheld because independent validation failed.", file=sys.stderr)
            else:
                sub_data = format_official_submission(raw_input, output, rep)
                sub_path = Path(args.submission)
                sub_path.parent.mkdir(parents=True, exist_ok=True)
                sub_path.write_text(json.dumps(sub_data, indent=2), encoding="utf-8")
                if not args.quiet:
                    print(f"Saved Slide 8 official submission to: {sub_path}")

        if args.pdf:
            from sutrayana.report import generate_plan_report_pdf
            raw_input = json.loads(input_path.read_text(encoding="utf-8"))
            pdf_bytes = generate_plan_report_pdf(
                raw_input,
                output,
                {"plan_id": plan.id, "elapsed_s": dt, "is_valid": is_valid}
            )
            pdf_path = Path(args.pdf)
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(pdf_bytes)
            if not args.quiet:
                print(f"Saved PDF report to: {pdf_path}")

        if args.image or args.html:
            from sutrayana.visualize import render
            render(plan, output, image_path=args.image, html_path=args.html)
            if not args.quiet:
                if args.image:
                    print(f"Saved layout image to: {args.image}")
                if args.html:
                    print(f"Saved interactive review HTML to: {args.html}")

        return 0 if is_valid else 1

    except Exception as exc:
        print(f"Error solving plan: {exc}", file=sys.stderr)
        return 1


def cmd_check(args: argparse.Namespace) -> int:
    """Execute independent checker mirror on input plan and solution JSON."""
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        print(f"Error: input file '{input_path}' not found.", file=sys.stderr)
        return 1
    if not output_path.exists():
        print(f"Error: output file '{output_path}' not found.", file=sys.stderr)
        return 1

    try:
        plan = Plan(str(input_path), wire_clearance=args.wire_clearance)
        output_data = json.loads(output_path.read_text(encoding="utf-8"))
        report = validate(plan, output_data)
        is_valid = report.get("valid", False)
        recomputed = report.get("recomputed_metrics", {}) or {}
        reported = output_data.get("reported_metrics", {}) or {}

        print("=" * 70)
        print("SUTRAYANA INDEPENDENT CHECKER MIRROR")
        print(f"Plan ID         : {plan.id}")
        print(f"Input Plan      : {input_path}")
        print(f"Candidate Design: {output_path}")
        print(f"Overall Verdict : {'PASSED (VALID)' if is_valid else 'FAILED (REJECTED)'}")
        print("-" * 70)
        print("METRIC AUDIT:")
        print(f"  Hub Count (H) : Reported = {reported.get('hub_count')} | Recomputed = {recomputed.get('hub_count')}")
        print(f"  Cable Length  : Reported = {reported.get('total_length_m', 0):.2f}m | Recomputed = {recomputed.get('total_length_m', 0):.2f}m")
        print(f"  Crossings (X) : Reported = {reported.get('total_crossings', 0)} | Recomputed = {recomputed.get('total_crossings', 0)}")
        print(f"  Overlap (O)   : Reported = {reported.get('total_overlap_m', 0):.2f}m | Recomputed = {recomputed.get('total_overlap_m', 0):.2f}m")
        print(f"  Bends (B)     : Reported = {reported.get('total_bends', 0)} | Recomputed = {recomputed.get('total_bends', 0)}")
        print(f"  Total Cost (J): Reported = {reported.get('total_cost_J', 0):.2f} | Recomputed = {recomputed.get('total_cost_J', 0):.2f}")
        print("-" * 70)

        errors = report.get("errors", [])
        if errors:
            print("VIOLATIONS ENCOUNTERED:")
            for err in errors:
                print(f"  [Rule: {err.get('rule')}] {err.get('message')}")
        else:
            print("Zero violations detected. Solution satisfies all geometric, capacity, and topological constraints.")
        print("=" * 70)

        if args.pdf:
            from sutrayana.report import generate_plan_report_pdf
            raw_input = json.loads(input_path.read_text(encoding="utf-8"))
            pdf_bytes = generate_plan_report_pdf(
                raw_input,
                output_data,
                {"plan_id": plan.id, "is_valid": is_valid}
            )
            Path(args.pdf).write_bytes(pdf_bytes)
            print(f"Saved check verification PDF to: {args.pdf}")

        if args.image:
            from sutrayana.visualize import render
            render(plan, output_data, image_path=args.image)
            print(f"Saved check overlay image to: {args.image}")

        return 0 if is_valid else 1

    except Exception as exc:
        print(f"Checker execution error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hackhive",
        description="SutraYana / HackHive: CLI-First Closed-Ring Cable Routing Suite."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommands")

    # Command: solve
    p_solve = subparsers.add_parser("solve", help="Synthesize optimal verified cable rings for a floor plan.")
    p_solve.add_argument("input", help="Path to input floor plan JSON.")
    p_solve.add_argument("output", nargs="?", default=None, help="Path for output solution JSON (optional).")
    p_solve.add_argument("--wire-clearance", type=float, default=0.0, help="Wall clearance in metres (0.0 for slide rules, 0.5 for strict).")
    p_solve.add_argument("--open-min", type=float, default=0.5, help="Minimum passage clearance in metres (default: 0.5).")
    p_solve.add_argument("--area-cap", type=float, default=100.0, help="Maximum zone area per hub in m² (default: 100.0).")
    p_solve.add_argument("--device-cap", type=int, default=5, help="Maximum devices per hub (D5 rule, default: 5).")
    p_solve.add_argument("--rl", action="store_true", help="Enable RL adaptive routing.")
    p_solve.add_argument("--submission", help="Path to write Slide 8 official submission JSON format.")
    p_solve.add_argument("--pdf", help="Path to save PDF verification report.")
    p_solve.add_argument("--image", help="Path to save rendered layout image (PNG/SVG).")
    p_solve.add_argument("--html", help="Path to save standalone interactive review page.")
    p_solve.add_argument("--quiet", "-q", action="store_true", help="Suppress progress logs.")
    p_solve.set_defaults(func=cmd_solve)

    # Command: check
    p_check = subparsers.add_parser("check", help="Run independent checker mirror on a candidate solution.")
    p_check.add_argument("input", help="Path to input floor plan JSON.")
    p_check.add_argument("output", help="Path to candidate solution JSON.")
    p_check.add_argument("--wire-clearance", type=float, default=0.0, help="Wall clearance in metres (default: 0.0).")
    p_check.add_argument("--pdf", help="Path to export PDF check report.")
    p_check.add_argument("--image", help="Path to export verification overlay image.")
    p_check.add_argument("--quiet", "-q", action="store_true", help="Minimal output.")
    p_check.set_defaults(func=cmd_check)

    return parser


def main(args: list[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)
    return parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main())
