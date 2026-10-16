"""Bridge between SutraYana 2D Floor Plan models and Blender 3D Digital Twin.
Extracts normalized Shapely geometry from SutraYana Plan objects and invokes
Blender headlessly to generate high-fidelity .blend files and render previews.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Ensure repository root is on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sutrayana.model import Plan


def find_blender_binary():
    """Locate the Blender executable on Windows or POSIX systems."""
    # 1. Environment variable override
    env_path = os.environ.get("BLENDER_PATH")
    if env_path and Path(env_path).is_file():
        return str(Path(env_path).resolve())

    # 2. Check PATH
    which_blender = shutil.which("blender")
    if which_blender:
        return which_blender

    # 3. Standard Windows installation paths
    program_files = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]

    candidates = [
        r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    ]

    for cand in candidates:
        if Path(cand).is_file():
            return str(Path(cand).resolve())

    # Search Blender Foundation folder dynamically
    for pf in program_files:
        bf_dir = Path(pf) / "Blender Foundation"
        if bf_dir.is_dir():
            for exe in bf_dir.glob("*/blender.exe"):
                if exe.is_file():
                    return str(exe.resolve())

    return None


def flatten_polygons(geom):
    """Yield all individual Polygon objects from a Shapely geometry."""
    if geom is None or geom.is_empty:
        return
    if hasattr(geom, "geoms"):
        for sub in geom.geoms:
            yield from flatten_polygons(sub)
    elif hasattr(geom, "exterior"):
        yield geom


def serialize_polygon(poly, cx, cy):
    """Convert a single Shapely polygon into centered coordinates dict."""
    if poly is None or poly.is_empty or not hasattr(poly, "exterior"):
        return None

    # Exterior
    ext_coords = [[round(x - cx, 4), round(y - cy, 4)] for x, y in poly.exterior.coords]

    # Interiors (holes)
    holes_coords = []
    for hole in getattr(poly, "interiors", []):
        holes_coords.append([[round(x - cx, 4), round(y - cy, 4)] for x, y in hole.coords])

    return {
        "exterior": ext_coords,
        "interiors": holes_coords,
    }


def extract_plan_payload(plan_source, solution_source=None, auto_solve=True):
    """Load plan with SutraYana and extract centered geometry, hubs, and cable routes for Blender."""
    raw = None
    if isinstance(plan_source, (str, Path)) and Path(plan_source).is_file():
        try:
            raw = json.loads(Path(plan_source).read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    elif isinstance(plan_source, dict):
        raw = plan_source

    plan = Plan(plan_source) if not isinstance(plan_source, Plan) else plan_source

    bounds = plan.inner.bounds  # (minx, miny, maxx, maxy)
    cx = (bounds[0] + bounds[2]) / 2.0
    cy = (bounds[1] + bounds[3]) / 2.0

    centered_bounds = [
        round(bounds[0] - cx, 4),
        round(bounds[1] - cy, 4),
        round(bounds[2] - cx, 4),
        round(bounds[3] - cy, 4),
    ]

    # Rooms
    rooms_list = []
    for rid, room in plan.rooms.items():
        poly_dicts = []
        for p in flatten_polygons(room.polygon):
            sp = serialize_polygon(p, cx, cy)
            if sp:
                poly_dicts.append(sp)

        rooms_list.append({
            "id": str(rid),
            "type": room.kind,
            "polygons": poly_dicts,
            "node": {
                "id": room.node_id,
                "x": round(room.node[0] - cx, 4) if room.node else None,
                "y": round(room.node[1] - cy, 4) if room.node else None,
            } if room.node else None,
        })

    # Walls
    walls_list = []
    if plan.wall and not plan.wall.is_empty:
        for w in flatten_polygons(plan.wall):
            sp = serialize_polygon(w, cx, cy)
            if sp:
                walls_list.append(sp)

    # Windows
    windows_list = []
    if plan.window and not plan.window.is_empty:
        for w in flatten_polygons(plan.window):
            sp = serialize_polygon(w, cx, cy)
            if sp:
                windows_list.append(sp)

    # Doors
    doors_list = []
    if hasattr(plan, "doors") and plan.doors:
        for d in plan.doors:
            d_poly = d
            if not hasattr(d, "exterior") and not hasattr(d, "geoms"):
                from sutrayana.model import geometry
                d_poly = geometry(d)
            for sub_d in flatten_polygons(d_poly):
                sp = serialize_polygon(sub_d, cx, cy)
                if sp:
                    doors_list.append(sp)

    # Terminals (Fixed nodes)
    terminals_list = []
    for rid, room in plan.rooms.items():
        if room.node and room.node_id:
            terminals_list.append({
                "id": str(room.node_id),
                "room_id": str(rid),
                "x": round(room.node[0] - cx, 4),
                "y": round(room.node[1] - cy, 4),
            })

    # Hubs and Cable Route Segments (Phase 3)
    raw_hubs = raw.get("hubs", []) if isinstance(raw, dict) else []
    if not raw_hubs and solution_source:
        if isinstance(solution_source, (str, Path)) and Path(solution_source).is_file():
            sol_raw = json.loads(Path(solution_source).read_text(encoding="utf-8-sig"))
            raw_hubs = sol_raw.get("hubs", [])
        elif isinstance(solution_source, dict):
            raw_hubs = solution_source.get("hubs", [])

    if not raw_hubs and auto_solve:
        try:
            from sutrayana.solver import solve_plan
            sol = solve_plan(plan_source)
            raw_hubs = sol.get("hubs", [])
        except Exception as e:
            print(f"Auto-solve skipped or unable to solve: {e}")

    hubs_list = []
    for h_idx, h in enumerate(raw_hubs):
        hx = float(h["location"]["x"]) - cx
        hy = float(h["location"]["y"]) - cy
        segs = []
        for s in h.get("route_segments", []):
            pts = [[round(pt[0] - cx, 4), round(pt[1] - cy, 4)] for pt in s.get("polyline", [])]
            segs.append({
                "from": str(s.get("from", "")),
                "to": str(s.get("to", "")),
                "polyline": pts,
                "length_m": round(float(s.get("length_m", 0.0)), 3),
            })
        hubs_list.append({
            "id": str(h.get("hub_id", f"H{h_idx + 1}")),
            "room_id": str(h.get("room_id", "")),
            "x": round(hx, 4),
            "y": round(hy, 4),
            "segments": segs,
        })

    return {
        "plan_id": plan.id,
        "center": [round(cx, 4), round(cy, 4)],
        "bounds": centered_bounds,
        "rooms": rooms_list,
        "walls": walls_list,
        "windows": windows_list,
        "doors": doors_list,
        "terminals": terminals_list,
        "hubs": hubs_list,
    }


def generate_blender_twin(
    plan_source,
    output_blend_path,
    render_image_path=None,
    top_render_path=None,
    wall_height=1.4,
    floor_thickness=0.05,
    solution_path=None,
    auto_solve=True,
    export_glb=True,
    glb_path=None,
    blender_path=None,
):
    """Full pipeline: extract geometry, write payload, invoke Blender headless."""
    blender_exe = blender_path or find_blender_binary()
    if not blender_exe or not Path(blender_exe).is_file():
        raise FileNotFoundError(
            "Blender executable not found. Please install Blender or set BLENDER_PATH."
        )

    print(f"Using Blender executable: {blender_exe}")

    payload = extract_plan_payload(plan_source, solution_source=solution_path, auto_solve=auto_solve)

    # Scratch directory for payload
    root_dir = Path(__file__).resolve().parents[1]
    scratch_dir = root_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    payload_file = scratch_dir / f"payload_{payload['plan_id']}.json"

    with open(payload_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    builder_script = Path(__file__).resolve().parent / "blender_builder.py"
    output_blend = Path(output_blend_path).resolve()
    output_blend.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(blender_exe),
        "--background",
        "--python",
        str(builder_script),
        "--",
        "--input",
        str(payload_file),
        "--output",
        str(output_blend),
        "--wall-height",
        str(wall_height),
        "--floor-thickness",
        str(floor_thickness),
    ]

    glb_target = None
    if export_glb:
        glb_target = Path(glb_path).resolve() if glb_path else output_blend.with_suffix(".glb")
        glb_target.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--glb", str(glb_target)])

    if render_image_path:
        render_path = Path(render_image_path).resolve()
        render_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--render", str(render_path)])

    if top_render_path:
        top_path = Path(top_render_path).resolve()
        top_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--top-render", str(top_path)])

    print(f"Launching Blender build for {output_blend.name}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("Blender STDERR:\n", result.stderr)
        print("Blender STDOUT:\n", result.stdout)
        raise RuntimeError(f"Blender process exited with code {result.returncode}")

    print("Blender output summary:")
    for line in result.stdout.splitlines():
        if any(keyword in line for keyword in ("Building 3D", "Saved .blend", "Exporting", "GLB export", "Rendering", "Render complete", "Saved:")):
            print(" ", line)

    cables_count = sum(len(h.get("segments", [])) for h in payload.get("hubs", []))
    return {
        "blend_file": str(output_blend),
        "glb_file": str(glb_target) if glb_target else None,
        "render_file": str(Path(render_image_path).resolve()) if render_image_path else None,
        "top_render_file": str(Path(top_render_path).resolve()) if top_render_path else None,
        "plan_id": payload["plan_id"],
        "rooms_count": len(payload["rooms"]),
        "walls_count": len(payload["walls"]),
        "windows_count": len(payload.get("windows", [])),
        "doors_count": len(payload.get("doors", [])),
        "terminals_count": len(payload.get("terminals", [])),
        "hubs_count": len(payload.get("hubs", [])),
        "cables_count": cables_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Convert SutraYana 2D plan to Blender 3D Digital Twin")
    parser.add_argument("--plan", required=True, help="Path to input plan JSON")
    parser.add_argument("--solution", default=None, help="Optional path to solved solution JSON with hubs & routes")
    parser.add_argument("--no-solve", action="store_true", help="Disable auto-solving for raw floor plans")
    parser.add_argument("--output", default="results/digital_twin.blend", help="Path to output .blend file")
    parser.add_argument("--glb", default=None, help="Optional path to export web-ready .glb file")
    parser.add_argument("--no-glb", action="store_true", help="Disable automatic .glb export")
    parser.add_argument("--render", default=None, help="Optional path to render a PNG snapshot")
    parser.add_argument("--top-render", default=None, help="Optional path to render a top-down architectural PNG")
    parser.add_argument("--wall-height", type=float, default=1.4, help="Cutaway wall height in metres (default 1.4)")
    parser.add_argument("--floor-thickness", type=float, default=0.05, help="Floor thickness in metres (default 0.05)")

    args = parser.parse_args()
    res = generate_blender_twin(
        plan_source=args.plan,
        output_blend_path=args.output,
        render_image_path=args.render,
        top_render_path=args.top_render,
        wall_height=args.wall_height,
        floor_thickness=args.floor_thickness,
        solution_path=args.solution,
        auto_solve=not args.no_solve,
        export_glb=not args.no_glb,
        glb_path=args.glb,
    )
    print("\nDigital Twin generation complete!")
    print(f"  Blend File:   {res['blend_file']}")
    if res["glb_file"]:
        print(f"  GLB File:     {res['glb_file']}")
    if res["render_file"]:
        print(f"  Render Image: {res['render_file']}")
    if res["top_render_file"]:
        print(f"  Top Render:   {res['top_render_file']}")
    print(f"  Rooms:        {res['rooms_count']}")
    print(f"  Walls:        {res['walls_count']}")
    print(f"  Windows:      {res['windows_count']}")
    print(f"  Doors:        {res['doors_count']}")
    print(f"  Terminals:    {res['terminals_count']}")
    print(f"  Hubs:         {res['hubs_count']}")
    print(f"  Cable Routes: {res['cables_count']}")


if __name__ == "__main__":
    main()
