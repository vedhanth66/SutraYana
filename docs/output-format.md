# SutraYana / HackHive Output Format Specification

This document defines the official submission format, mathematical schemas, and coordinate conventions required by the **Cable Ring Planning Competition** (Slide 8 specification).

---

## 1. Top-Level Structure

Every valid output is a JSON object with strictly defined keys:

```json
{
  "plan_id": "14433",
  "units": "m",
  "hubs": [ ... ],
  "reported_metrics": { ... },
  "solver": { ... },
  "validation": { ... }
}
```

### Required Fields
- `plan_id` (string): Unique identifier corresponding exactly to the input floor plan.
- `units` (string): Metric units, strictly `"m"` (metres).
- `hubs` (array of objects): Array of control hub loops.
- `reported_metrics` (object): Recomputed scalar scores and physical statistics.
- `solver` (object): Execution metadata, lower-bound proof, and decision transparency trace.
- `validation` (object): Independent checker mirror verification verdict.

---

## 2. Hub Object Schema

Each element in the `hubs` array defines one closed electrical/data ring:

```json
{
  "hub_id": "H1",
  "room_id": "R05_kitchen",
  "location": {
    "x": 11.649,
    "y": 7.187
  },
  "assigned_rooms": [
    "R01_living",
    "R02_bedroom",
    "R03_bedroom",
    "R05_kitchen"
  ],
  "assigned_nodes": [
    "N1",
    "N2",
    "N3",
    "N5"
  ],
  "closed_sequence": [
    "H1",
    "N5",
    "N2",
    "N1",
    "N3",
    "H1"
  ],
  "route_segments": [
    {
      "from": "H1",
      "to": "N5",
      "polyline": [
        [11.649, 7.187],
        [11.649, 7.157]
      ],
      "length_m": 0.03
    }
  ],
  "ring_length_m": 35.56
}
```

### Hub Fields Definition:
| Field | Type | Description |
|-------|------|-------------|
| `hub_id` | `string` | Unique identifier formatted as `H1`, `H2`, etc. |
| `room_id` | `string` | Identifier of the physical room where the hub is located. |
| `location` | `object` | 2D coordinates `{"x": float, "y": float}` in source metres. |
| `assigned_rooms` | `array[string]` | Distinct list of rooms covered by this circuit (connected subgraph, total area $\le 100.0\text{ m}^2$). |
| `assigned_nodes` | `array[string]` | Distinct list of fixed device terminals covered ($\le 5$ devices). |
| `closed_sequence` | `array[string]` | Complete canonical cycle starting and ending at `hub_id`: `[H, N_1, ..., N_k, H]`. |
| `route_segments` | `array[object]` | Array of individual point-to-point legs connecting the sequence. |
| `ring_length_m` | `float` | Sum of all segment lengths in metres. |

---

## 3. Route Segment Schema

Each segment within `route_segments` represents a single directed leg between two consecutive terminals:

```json
{
  "from": "N5",
  "to": "N2",
  "polyline": [
    [11.649, 7.157],
    [11.649, 5.648],
    [10.150, 5.648]
  ],
  "length_m": 3.008
}
```

### Constraints:
1. **Endpoint Alignment**: `polyline[0]` must coincide with the terminal position of `from`, and `polyline[-1]` must coincide with `to`.
2. **Orthogonality**: Consecutive points must differ in at most one coordinate (strictly horizontal or vertical motion; no diagonals).
3. **No Terminal Penetration**: Segments must not pass through unassigned terminals or intermediate hubs.
4. **Obstacle Clearance**: Segments must reside entirely within inner navigable room space and passage portals.

---

## 4. Reported Metrics Schema

```json
{
  "hub_count": 2,
  "total_cost_J": 43.59,
  "total_length_m": 35.56,
  "total_crossings": 0,
  "total_overlap_m": 0.03,
  "total_bends": 16
}
```

Where:
- $\text{total\_cost\_J} = L + 5.0 \cdot X + 1.0 \cdot O + 0.5 \cdot B$
- All metrics are independently recomputed from raw polylines by the checker mirror.

---

## 5. Decision Transparency & Solver Metadata Schema

```json
{
  "minimum_hubs": 2,
  "hub_count_proven": true,
  "lower_bound_hubs": 2,
  "fallback_ladder_activated": false,
  "ranking_criterion": "fewest hubs -> worse J of two counting readings -> area gap",
  "checker_mirror_passed": true,
  "worse_J": 43.59,
  "area_gap_m2": 24.1,
  "decision_trace": [
    {
      "hubs_count": 2,
      "solver_J": 43.59,
      "checker_J": 43.59,
      "worse_J": 43.59,
      "area_gap_m2": 24.1,
      "passed_checker": true,
      "status": "PASSED_CHECKER"
    }
  ]
}
```
This metadata guarantees 100% transparency into the exact decision tree and candidate arrangements evaluated by the solver.
