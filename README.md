# SutraYana

A geometry-validated solver for the Cable Ring Challenge. It assigns connected room zones to the fewest hubs, preserves fixed input nodes, and constructs closed rectilinear cable rings. Results include independently checked JSON, a floor-plan overlay, and an offline interactive review page.

## Run a submission

Python 3.10 or later:

```powershell
python -m pip install -r requirements.txt
python solve.py examples/resplan_0.json results/solution.json --image results/overlay.png --html results/review.html
python solve.py examples/resplan_0.json results/solution.json --validate-only
python -m unittest discover -s tests -v
```

Open `results/review.html` in a browser. It needs no server or internet connection. Toggle individual rings, inspect capacity and visiting order, download the exact result JSON, or print the review. The PNG/SVG overlay includes actual walls, windows, doors, zone colours, fixed nodes, hubs, route direction and return legs.

The example geometry is attributed to the ResPlan Authors under CC BY 4.0; see `THIRD_PARTY_NOTICES.md`. To rebuild the clean source/demo ZIP after generating the verification files, run `python tools/package_submission.py`.

The command exits nonzero on invalid input, unsuccessful routing, or invalid output. It only replaces the output JSON after validation succeeds. An earlier output file is left untouched if a subsequent solve fails, so callers must check the exit code. Batch workers do not write a shared output file.

To inspect a structurally well-formed but invalid submission, add `--image results/violations.png` to `--validate-only`. Violating rings are red, and cable outside free space receives a red overlay.

## Input contract

The supplied problem deck specifies the output format, but does not supply the organisers' input schema. This implementation supports an explicit geometry schema; obtain an organiser sample before claiming hidden-checker compatibility.

```json
{
  "id": "example",
  "area": 16,
  "inner": {"type":"Polygon","coordinates":[[[0,0],[40,0],[40,40],[0,40],[0,0]]]},
  "wall": null,
  "window": null,
  "rooms": [{
    "id":"R1", "type":"living",
    "polygon":{"type":"Polygon","coordinates":[[[0,0],[40,0],[40,40],[0,40],[0,0]]]},
    "node":{"id":"N1","x":20,"y":20}
  }],
  "doors": []
}
```

- Geometry uses GeoJSON Polygon/MultiPolygon, including holes. `inner: {"polygon": ...}` is also accepted. Invalid polygons are repaired using Shapely `make_valid`.
- `area` is the inner footprint in m². Drawing units per metre are `sqrt(repaired_inner.area / area)`. Room capacity uses polygon area divided by scale², never guessed room-area units or `net_area`.
- Use `units: "m"` for geometry already in metres. Otherwise drawing units are assumed.
- The lower-left inner bounds become the output origin. Coordinates default to y up. Set `coordinate_system: {"y_axis":"down"}` to explicitly flip image-style input. The output records the transform.
- Eligible room types are `living`, `bedroom`, `kitchen`, and `storage`. Every room is one polygon record. Every eligible record must have a fixed interior node at least 0.5 m from walls. A top-level `nodes` list with `room_id`, `id`, `x`, `y` is also supported. Supplied node positions and IDs are preserved.
- `wall` must be supplied, including explicit `null` for a synthetic wall-free plan. Optional `window` defaults to empty. Doors contain `polygon`; raw GeoJSON `door` is also accepted. Room-pair labels cannot create connectivity through a wall.
- Excluded rooms have no node or hub. They do not connect zones. Cable may use the inner free space, subject to the terminal and obstacle checks.
- The raw dataset adapter generates demo nodes once, upstream of the solver. This is explicitly labelled in its output and is not a substitute for the organisers' fixed nodes.

## Rules and algorithms

1. Repair geometry before and after coordinate normalization. Free space is exactly `inner − wall − window`. The router keeps a one-micrometre numerical inset to avoid boundary arithmetic problems; it never enlarges free space.
2. Build room links from continuous door geometry or a continuous wall-free open passage. Node-containing free-space components must also connect. No proximity-only links, window links, entrance links, artificial door carving, or nearest-neighbour fallback.
3. Enumerate every connected subset of at most five eligible rooms with area at most 100 m² and a feasible hub point. A memoized bitmask search computes the exact minimum number of such subsets covering each room once, then enumerates all partitions achieving that minimum. No iteration cap or greedy fallback can silently increase the hub count.
4. Build a rectilinear coordinate graph from obstacle vertices, gap midpoints, small interior offsets, and exact terminals. Test every edge against free-space geometry. Direction-aware shortest paths include turn costs. Other fixed nodes are absorbing destinations, with 1 mm guards against nearby parallel passes and turns. Reuse the CSR graph structure and retain compact terminal paths rather than full shortest-path trees. Reroute penalties inspect only nearby edges.
5. Evaluate all node-order permutations with several legal hub candidates. Rank minimum-hub partitions using actual global J and then area gap. Retain alternatives for cross-ring interaction improvement.
6. Reroute individual legs with occupancy costs. Accept a change only when the recomputed global J improves and all hard-rule checks still pass. Reversals count as one bend, overlaps count `(k−1) × length`, and crossing checks include different rings and T-touches, excluding node/hub points and ordinary bends.
7. Remove unnecessary hub detours when a hub can lie legally on the closing connector. Accept only a lower global J that passes validation. Expanded hub search is optional in Ring Studio; its deadline wrapper retains the base result unless the expanded result ranks better.
8. Validate coverage, capacity, zone connectivity, fixed terminals, hub clearance, sequence, leg endpoints, closure, axis alignment, free space, unintended node visits, lengths and reported global metrics before writing.

**What is proven:** minimum hub count for the constructed connectivity graph and configured zone interpretation. All minimum-hub partitions are considered. **What is heuristic:** continuous hub placement, physical cable paths, and global minimum J. Routing failure produces an error, never a fabricated route or an unverified success.

The source deck's 1 mm tolerance is used for metric equivalence and clearance tolerance. Geometric containment checks are stricter: submitted segments must be covered by the actual free space. The implementation counts distinct cable meeting points; ordinary consecutive bends do not count as crossings. Positive collinear sharing is charged as overlap rather than infinitely many crossings.

## Assumptions to confirm with organisers

- Actual input schema and coordinate convention, including fixed node IDs.
- Minimum open-passage width: configurable with `--open-min`, default 0.5 m. A 2 cm geometry-contact allowance never permits a bridge through an obstacle.
- Whether excluded rooms may connect an assigned zone. The default requires connectivity entirely among assigned eligible rooms.
- Final fixed score weights and checker treatment of overlap endpoints. Current weights follow the supplied deck: `J = L + 5X + O + 0.5B`.

Hubs are placed separately from nodes, so the solver does not depend on permission to co-locate them. Input coordinates are not rounded before routing.

## Evaluate ResPlan

Verification on 16 October 2026: 20 regression tests passed. A seeded sample of 120 raw ResPlan records produced 112 validated designs; eight inputs were rejected for oversized rooms or unavailable legal demo-node placement. All 112 outputs also passed the supplied external geometry auditor. Its length, bend and overlap results agreed, and an independent MILP on the audit graph agreed on minimum hub count for all 112. The external auditor does not fully evaluate crossings; dedicated fixtures test those cases. Detailed evidence is in the bundle's `results/verification.json` and `results/independent_audit.json`. The 17,000-plan dataset and organiser hidden inputs have not been exhaustively verified by this revision.

Place the trusted dataset at `ResPlan/ResPlan/ResPlan.pkl` or pass `--pkl`. Pickle is a Python executable serialization format: only load a dataset you trust.

```powershell
python export_resplan_to_json.py ResPlan/ResPlan/ResPlan.pkl examples/my_plan.json 0
python batch_eval_pipeline.py --count 120 --workers 4 --seed 42 --log-name benchmark.log
python check.py --plans 0 1 2 --workers 2
```

Batch results retain the all-input pass rate and separately report benchmark-ineligible inputs, solver failures, and the eligible-input pass rate. Ineligible inputs never count as passes. Source hashes, Python version, routing mode, and demo-node provenance are recorded. Batch results include every rejected plan and its reason. Raw ResPlan includes plans outside the competition's filtered benchmark, such as rooms larger than 100 m². A raw-dataset pass rate must not be presented as a hidden-benchmark success rate. `--resolution` is retained for command-line compatibility but has no effect on the coordinate-graph router.

The supplied `audit_tools/` remains available as an external check. Its original runner assumes coordinates retain the raw origin; use `tools/independent_audit.py` to reverse the explicit output translation before applying that validator. This avoids mistaking a documented origin change for a geometric violation.

## Project layout

- `solve.py`: submission and validation CLI.
- `sutrayana/model.py`: normalization and strict connectivity.
- `sutrayana/solver.py`: complete hub partition search, sequence and route candidate selection.
- `sutrayana/routing.py`: geometry-checked turn-aware paths and rerouting.
- `sutrayana/metrics.py`: one global scorer.
- `sutrayana/validation.py`: output checks separate from construction.
- `sutrayana/visualize.py`: image and standalone review page.
- `tests/test_solver.py`: geometric, capacity, sequence and metric regressions.
- `phase1_pipeline.py` through `phase4_routing.py`: compatibility entry points using the corrected implementation. Historical unsafe routing internals have been removed.

This is a research prototype for the challenge, not a building-services design. A working implementation and evidence improve a submission; neither guarantees a competition result.
