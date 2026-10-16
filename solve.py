"""Single-plan submission entry point. Writes output only after validation."""
import argparse
import json
import sys
import time
from pathlib import Path
from sutrayana.model import Plan
from sutrayana.solver import solve_plan
from sutrayana.validation import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",help="Input plan JSON with fixed nodes")
    parser.add_argument("output",help="Submission JSON (or existing JSON with --validate-only)")
    parser.add_argument("--image",help="Save floor-plan overlay as PNG or SVG")
    parser.add_argument("--html",help="Save an interactive, standalone review page")
    parser.add_argument("--validate-only",action="store_true")
    parser.add_argument("--open-min",type=float,default=.5,help="Minimum open-passage width in metres (assumption: 0.5)")
    parser.add_argument("--wire-clearance",type=float,default=0.0,help="Wall-to-wire clearance in metres (default: 0.0 for slide rules, 0.5 for 0.5m clearance)")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        if args.open_min <= 0:
            raise ValueError("--open-min must be positive")
        plan = Plan(args.input,open_min=args.open_min,wire_clearance=args.wire_clearance)
        if args.validate_only:
            output = json.loads(Path(args.output).read_text(encoding="utf-8"))
            report = validate(plan,output)
            print(json.dumps(report,indent=2))
            if args.image or args.html:
                from sutrayana.visualize import render
                output["validation"] = report
                render(plan,output,image_path=args.image,html_path=args.html)
            return 0 if report["valid"] else 1
        output = solve_plan(plan,open_min=args.open_min,wire_clearance=args.wire_clearance)
        target = Path(args.output)
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary = target.with_suffix(target.suffix+".tmp")
        temporary.write_text(json.dumps(output,indent=2,allow_nan=False),encoding="utf-8")
        temporary.replace(target)
        if args.image or args.html:
            from sutrayana.visualize import render
            render(plan,output,image_path=args.image,html_path=args.html)
        m = output["reported_metrics"]
        print(f"VALID | H={m['hub_count']} | J={m['total_cost_J']:.3f} | L={m['total_length_m']:.3f} m | X={m['total_crossings']} | O={m['total_overlap_m']:.3f} m | B={m['total_bends']} | {time.perf_counter()-started:.2f}s")
        return 0
    except (ValueError,KeyError,TypeError,OSError) as e:
        print(f"FAILED: {e}",file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
