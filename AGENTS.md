# AGENTS.md: Developer & Autonomous Agent Architecture Guide

Welcome to **SutraYana / HackHive** — the production-grade, mathematically optimal closed-ring cable routing and control hub synthesis engine.

This document serves as the canonical technical specification for autonomous LLM coding agents, research subagents, and human contributors working within this codebase.

---

## 1. System Mission & Core Directives

The objective of SutraYana is to solve the **Residential Cable Ring Routing Problem** across arbitrary architectural floor plans (including the full 17,000-plan ResPlan dataset):
1. **Minimize Hub Count ($H$)**: Proven to match the theoretical lower bound $H_{\text{LB}}$ whenever geometrically routable.
2. **Minimize Scalar Cost Objective ($J$)**:
   $$J = L + 5.0 \cdot X + 1.0 \cdot O + 0.5 \cdot B$$
   Where $L$ is total cable length, $X$ is pairwise crossings, $O$ is overlap/retraces, and $B$ is orthogonal directional bends.
3. **Independent Checker Mirror Gate**: Every candidate solution must pass an independent verification mirror that independently recomputes all metrics from raw polyline geometry. Solutions failing independent validation are strictly withheld.
4. **Dual-Reading Ranking System**: Candidate arrangements are ranked by:
   $$\text{Rank} = \left( H, \max(J_{\text{solver}}, J_{\text{checker}}), \text{Area Gap} \right)$$
   Taking the worse reading of the two counts eliminates false optimism and guarantees conservative scoring.

---

## 2. Directory Layout & Module Responsibilities

```
SutraYana/
├── hackhive.py               # Top-level CLI entrypoint (hackhive solve/check/batch)
├── solve.py                  # Standalone single-plan CLI runner
├── check.py                  # Standalone verification runner
├── streamlit_app.py          # Interactive Streamlit demo with labelled what-ifs
├── webapp.py                 # FastAPI backend for local web studio
├── sutrayana/                # Core Python package
│   ├── __init__.py           # Package exports
│   ├── __main__.py           # Entrypoint for python -m sutrayana
│   ├── cli.py                # Unified modular CLI parser and handlers
│   ├── model.py              # Plan geometry, polygon parsing, clearance buffering
│   ├── solver.py             # Exact cover DP, zone DFS, checker mirror, ranking
│   ├── routing.py            # Non-uniform grid, 4-heading Dijkstra, rip-up reroute
│   ├── metrics.py            # Scoring function J = L + 5X + O + 0.5B
│   ├── validation.py         # Independent checker mirror
│   ├── exporter.py           # Slide 8 official submission JSON formatter
│   ├── report.py             # Publication-grade PDF verification report generator
│   ├── resilience.py         # SPoF single-cut continuity and branch simulator
│   └── visualize.py          # 2D SVG/PNG overlay renderer
├── tools/
│   ├── batch_runner.py       # Multi-core high-throughput batch runner & CSV exporter
│   └── blender_bridge.py     # 3D digital twin generator
├── docs/
│   ├── ARCHITECTURE.md       # Deep architectural and algorithmic formulations
│   ├── output-format.md      # Official Slide 8 schema specification
│   └── decision_conventions.md # Geometric tolerances & tie-breaking rules
└── tests/                    # Pytest test suite (59+ unit and integration tests)
```

---

## 3. CLI-First Design & Usage

The system provides primary CLI interfaces through `hackhive` and `python -m sutrayana`:

### 3.1 `solve`
Synthesizes verified cable rings for a floor plan:
```bash
# Basic solve
python hackhive.py solve sample_plan.json output.json

# Stricter 0.5m wall clearance with PDF verification report
python hackhive.py solve sample_plan.json output.json --wire-clearance 0.5 --pdf report.pdf

# Save Slide 8 official submission format
python hackhive.py solve sample_plan.json output.json --submission official_submission.json
```

### 3.2 `check`
Runs the independent checker mirror on a candidate solution JSON:
```bash
python hackhive.py check sample_plan.json output.json
```
Returns exit code `0` if all rules pass, or `1` if any violation is detected.

---

## 4. Hard Mathematical Invariants

Every modification to the codebase must preserve these non-negotiable invariants:
1. **Device Capacity (Rule D5)**: Exactly $\le 5$ fixed devices assigned to any single hub loop.
2. **Area Capacity**: Total room area assigned to any single hub must not exceed $100.0\text{ m}^2$.
3. **Zone Connectivity**: The room adjacency subgraph induced by any hub's assigned rooms must be topologically connected via door portals or open boundaries.
4. **Partition Completeness**: Every eligible room (`living`, `bedroom`, `kitchen`, `storage`) must be assigned to exactly one hub.
5. **Loop Topology (2-Regular Cycle)**: Each circuit must form a closed cycle beginning and ending at the hub:
   $$\text{Closed Sequence} = [H, N_1, N_2, \dots, N_k, H]$$
6. **No Obstacle Penetrations**: Wires must never traverse physical wall boundaries or windows.
7. **SPoF Survivability**: Ring continuity ensures that if any single segment is cut, 100% of devices remain online via dual-ended feeding.

---

## 5. Guidelines for Autonomous Agents

When modifying this repository:
- **Test-Driven Verification**: Run `pytest -q` before concluding any session. All existing tests must pass cleanly.
- **Strictly Local Modifications**: Never push commits to remote Git repositories without explicit user instruction.
- **Maintain Documentation Integrity**: Preserve comments, docstrings, and architectural diagrams.
- **Aesthetic Consistency**: Avoid pictographic emojis in production UI labels and console output; maintain clean, professional typography and technical precision.
