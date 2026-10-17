"""Streamlit demo for running and checking cable-planning solutions.
Directly adapted from npm-install-regrets-2/hackhive-cable-routing legacy demo interface.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import time

import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sutrayana
from sutrayana.model import Plan, parts
from sutrayana.solver import solve_plan, compute_hub_lower_bound
from sutrayana.validation import validate
from sutrayana.exporter import format_official_submission
from sutrayana.report import generate_plan_report_pdf

st.set_page_config(page_title="SutraYana / Cable Ring Planner", layout="wide")
st.title("SutraYana: Closed-Ring Cable Planner")
st.caption("Normalized Plan → exact partitioning & rectilinear router → independent validation")

solver_path = Path(sutrayana.__file__).resolve()
solver_version = hashlib.sha256(solver_path.read_bytes()).hexdigest()[:12]
st.caption(f"Running solver: SutraYana package ({solver_version})")

# Plan selector
col_src, col_opts = st.columns([2, 1])
with col_src:
    plan_source = st.radio(
        "Plan source",
        ("Bundled examples", "Upload JSON floor plan"),
        horizontal=True,
    )

plan_data = None
plan_name = "custom_plan"

if plan_source == "Bundled examples":
    example_dirs = [ROOT / "examples", ROOT / "plans"]
    available_files = []
    for d in example_dirs:
        if d.is_dir():
            available_files.extend(sorted(d.glob("*.json")))

    if not available_files:
        st.error("No example plans found in examples/ or plans/ directory.")
        st.stop()

    file_map = {f"{f.parent.name}/{f.name}": f for f in available_files}
    chosen_label = st.selectbox("Select example plan", list(file_map.keys()), index=0)
    selected_path = file_map[chosen_label]
    plan_name = selected_path.stem
    try:
        plan_data = json.loads(selected_path.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"Failed to read plan file: {e}")
        st.stop()
else:
    uploaded = st.file_uploader("Upload Floor Plan JSON", type=["json"])
    if uploaded is not None:
        try:
            plan_data = json.loads(uploaded.read().decode("utf-8"))
            plan_name = Path(uploaded.name).stem
        except Exception as e:
            st.error(f"Invalid JSON file: {e}")
            st.stop()

# Labelled What-If Scenarios & Sensitivity Controls
with st.sidebar:
    st.header("Labelled What-If Scenarios")
    st.caption("Investigate how parameter variations impact hub counts and routing economics.")

    area_cap = st.slider(
        "Area Cap (m²)",
        min_value=50.0,
        max_value=150.0,
        value=100.0,
        step=5.0,
        help="Standard is 100 m² per circuit. Relaxing allows larger consolidated loops; tightening forces more hubs."
    )

    hub_clearance = st.selectbox(
        "Hub & Wire Clearance",
        (0.0, 0.25, 0.5),
        index=0,
        format_func=lambda x: f"{x:.2f} m {'(Slide rules · obstacles)' if x == 0.0 else '(Stricter clearance)'}",
        help="Distance wires and hubs must keep from physical walls and windows."
    )

    d5_device_cap = st.slider(
        "D5 Device Cap (Nodes/Hub)",
        min_value=3,
        max_value=10,
        value=5,
        step=1,
        help="Rule D5: Maximum monitored devices connected to a single control hub loop. Standard is 5."
    )

    d7_door_clearance = st.slider(
        "D7 Doorway Passage Clearance (m)",
        min_value=0.2,
        max_value=1.2,
        value=0.5,
        step=0.05,
        help="Rule D7: Minimum clear passage width required to traverse door portals between adjacent rooms."
    )

    use_rl = st.checkbox("Enable RL Adaptive Routing (Experimental)", value=False)

with col_opts:
    st.info(f"**What-If Settings**: {area_cap:.0f}m² cap · {d5_device_cap} nodes/hub · {hub_clearance}m clearance · {d7_door_clearance:.2f}m door min")

if plan_data is None:
    st.info("Please select or upload a floor plan to begin.")
    st.stop()

# Support wrapper object if bundled with metadata
raw_plan = plan_data.get("plan", plan_data)

def render_plan_matplotlib(plan_obj: Plan, solution: dict | None = None):
    """Draw input plan or solution overlay using matplotlib."""
    fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
    fig.patch.set_facecolor("#fafbf9")
    ax.set_facecolor("#fafbf9")

    def draw_poly(g, color, alpha=1.0, edge="none", lw=0.6):
        for p in parts(g):
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            from shapely.geometry.polygon import orient
            p = orient(p, sign=1)
            vertices, codes = [], []
            for ring in [p.exterior] + list(p.interiors):
                pts = list(ring.coords)
                vertices.extend(pts)
                codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(pts) - 2) + [MplPath.CLOSEPOLY])
            patch = PathPatch(MplPath(vertices, codes), facecolor=color, edgecolor=edge, alpha=alpha, lw=lw)
            ax.add_patch(patch)

    draw_poly(plan_obj.inner, "#e9ede9")
    for room in plan_obj.rooms.values():
        draw_poly(room.polygon, "#f1f3ef", edge="#c6cec7")
    draw_poly(plan_obj.wall, "#35443e")
    draw_poly(plan_obj.window, "#71b9de")
    for door in plan_obj.doors:
        draw_poly(door, "#e9cb81", alpha=0.8)

    circuit_colors = ["#007f78", "#bf5b2e", "#6453b8", "#b53869", "#2e74ad", "#2e8b57"]

    if solution and solution.get("hubs"):
        for i, h in enumerate(solution["hubs"]):
            c = circuit_colors[i % len(circuit_colors)]
            for rid in h.get("assigned_rooms", []):
                if rid in plan_obj.rooms:
                    draw_poly(plan_obj.rooms[rid].polygon, c, alpha=0.15)
            for seg in h.get("route_segments", []):
                xy = seg.get("polyline", [])
                if len(xy) >= 2:
                    xs, ys = zip(*xy)
                    ax.plot(xs, ys, color=c, lw=2.2, zorder=10)
            loc = h.get("location", {})
            hx, hy = loc.get("x", 0), loc.get("y", 0)
            ax.plot(hx, hy, "s", color=c, markersize=8, markeredgecolor="white", markeredgewidth=1.2, zorder=15)
            ax.text(hx + 0.15, hy, h.get("hub_id", ""), fontsize=8, fontweight="bold", color=c, zorder=16)

    for rid, r in plan_obj.rooms.items():
        if r.node:
            ax.plot(r.node[0], r.node[1], "o", color="#1b4d3e", markersize=6, zorder=12)
            ax.text(r.node[0] + 0.15, r.node[1], r.node_id or "", fontsize=8, fontweight="bold", color="#1b4d3e", zorder=13)

    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.axis("off")
    return fig

if st.button("Run planner", type="primary"):
    try:
        t0 = time.perf_counter()
        plan_obj = Plan(raw_plan, open_min=d7_door_clearance, wire_clearance=hub_clearance)
        h_lower_bound = compute_hub_lower_bound(plan_obj, max_nodes_per_hub=d5_device_cap, max_area_per_hub=area_cap)

        with st.spinner("Running SutraYana optimization (exact cover + rectilinear routing)..."):
            solution = solve_plan(
                plan_obj,
                open_min=d7_door_clearance,
                wire_clearance=hub_clearance,
                use_rl=use_rl,
                max_nodes_per_hub=d5_device_cap,
                max_area_per_hub=area_cap,
            )
            elapsed = time.perf_counter() - t0
            report = validate(plan_obj, solution)
            is_valid = report.get("valid", False)

        m = solution.get("reported_metrics", {})
        h_count = m.get("hub_count", len(solution.get("hubs", [])))
        j_cost = m.get("total_cost_J", 0.0)
        solver_meta = solution.get("solver", {})

        # Metrics bar
        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("Hubs (H)", f"{h_count}", delta=f"Lower Bound: {h_lower_bound}")
        c2.metric("Checked Cost (J)", f"{j_cost:.2f}")
        c3.metric("Length (L)", f"{m.get('total_length_m', 0.0):.2f} m")
        c4.metric("Crossings (X)", f"{m.get('total_crossings', 0)}")
        c5.metric("Overlap (O)", f"{m.get('total_overlap_m', 0.0):.2f} m")
        c6.metric("Bends (B)", f"{m.get('total_bends', 0)}")
        c7.metric("Solve Time", f"{elapsed:.3f} s")

        # Decision transparency block
        decision_trace = solver_meta.get("decision_trace", [])
        st.subheader("Decision Transparency: Why this layout was chosen")
        worse_j_val = solver_meta.get("worse_J", j_cost)
        area_gap_val = solver_meta.get("area_gap_m2", 0.0)
        st.info(
            f"**Ranking Strategy**: {solver_meta.get('ranking_criterion', 'fewest hubs -> worse J of two counting readings -> area gap')}.\n\n"
            f"Evaluated {len(decision_trace)} candidate arrangements under the checker mirror. "
            f"Selected design achieves **{h_count} hubs** (theoretical lower bound: {h_lower_bound}), "
            f"conservative worse J = **{worse_j_val:.2f}**, and area spread = **{area_gap_val:.1f} m²**."
        )
        if decision_trace:
            with st.expander("Candidate Arrangement Decision Table", expanded=False):
                st.dataframe(decision_trace, use_container_width=True)

        if is_valid:
            st.success(f"Independent validation passed! All {len(plan_obj.eligible)} nodes connected with 0 rule violations.")
        else:
            st.error("The independent validator rejected this solution. See diagnostics below.")

        st.subheader("Floor-plan comparison")
        st.caption("Input shows normalized rooms, fixed nodes, and portals. Output adds solver's assignments, hubs, and closed cable rings.")
        in_col, out_col = st.columns(2)
        with in_col:
            st.markdown("**Input floor plan**")
            fig_in = render_plan_matplotlib(plan_obj)
            st.pyplot(fig_in)
            plt.close(fig_in)
        with out_col:
            st.markdown("**Solver output and checked routes**")
            fig_out = render_plan_matplotlib(plan_obj, solution)
            st.pyplot(fig_out)
            plt.close(fig_out)

        # Hub loop inspector
        st.subheader("Hub Loop Inspection")
        hubs = solution.get("hubs", [])
        hub_ids = [h["hub_id"] for h in hubs]
        selected_hub_id = st.selectbox("Inspect Hub Loop", hub_ids, index=0)
        selected_hub = next((h for h in hubs if h["hub_id"] == selected_hub_id), None)

        if selected_hub:
            assigned_area = sum(plan_obj.rooms[rid].area for rid in selected_hub.get("assigned_rooms", []) if rid in plan_obj.rooms)
            nodes_count = len(selected_hub.get("assigned_nodes", []))
            loop_len = selected_hub.get("ring_length_m", 0.0)

            hc1, hc2, hc3, hc4 = st.columns(4)
            hc1.metric("Assigned Area", f"{assigned_area:.1f} m²", "/ 100 m² max")
            hc2.metric("Assigned Nodes", f"{nodes_count}", "/ 5 max")
            hc3.metric("Loop Length", f"{loop_len:.2f} m")
            hc4.metric("Loop Status", "VALID" if is_valid else "INVALID")

            st.markdown(f"**Canonical Closed Sequence:** `{' → '.join(selected_hub.get('closed_sequence', []))}`")

        # Diagnostics & JSON expanders
        with st.expander("Solution and independent validation details"):
            left, right = st.columns(2)
            with left:
                st.subheader("Solution JSON")
                st.json(solution)
            with right:
                st.subheader("Independent Validation Report")
                st.json({
                    "is_valid": is_valid,
                    "recomputed_metrics": m,
                    "diagnostics": report.get("diagnostics", []),
                    "warnings": report.get("warnings", []),
                })

        # Downloads
        st.subheader("Export & Reports")
        d1, d2 = st.columns(2)
        with d1:
            if is_valid:
                official_sub = format_official_submission(raw_plan, solution, report)
                st.download_button(
                    "Download Slide 8 Official Submission JSON",
                    data=json.dumps(official_sub, indent=2),
                    file_name=f"submission_{plan_name}.json",
                    mime="application/json",
                    type="primary",
                )
            else:
                st.button("Download Slide 8 Official Submission JSON (Withheld: Validation Failed)", disabled=True)
        with d2:
            try:
                pdf_bytes = generate_plan_report_pdf(
                    raw_plan,
                    solution,
                    {
                        "plan_id": plan_name,
                        "elapsed_s": elapsed,
                        "is_valid": is_valid,
                        "diagnostics": report.get("diagnostics", []),
                    }
                )
                st.download_button(
                    "Download Comprehensive PDF Verification Report",
                    data=pdf_bytes,
                    file_name=f"report_{plan_name}.pdf",
                    mime="application/pdf",
                )
            except Exception as pdf_err:
                st.warning(f"PDF generation notice: {pdf_err}")

    except Exception as error:
        st.error(f"Run failed: {error}")
        import traceback
        st.code(traceback.format_exc())
