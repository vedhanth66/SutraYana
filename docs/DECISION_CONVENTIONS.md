# SutraYana / HackHive: Decision Conventions & Geometric Tolerances

This document codifies the exact decision conventions, geometric tolerances, tie-breaking rules, and validation criteria implemented in SutraYana.

---

## 1. Room Eligibility & Classification

Only functional spaces designated for permanent residential occupancy and active automation equipment are included in the cable ring network:

| Room Type | Status | Rationale |
|-----------|--------|-----------|
| `living` | **Eligible** | Primary occupancy zone requiring continuous telemetry and power. |
| `bedroom` | **Eligible** | Habitational zone requiring dedicated environmental and device rings. |
| `kitchen` | **Eligible** | High-density device area included under residential fire & electrical codes. |
| `storage` | **Eligible** | Utility and service room included in automation topology. |
| `bathroom` | *Excluded* | Wet zone excluded from primary living ring loops. |
| `balcony` | *Excluded* | Exterior structural space excluded from interior climate rings. |
| `stair` | *Excluded* | Vertical circulation core excluded from horizontal ring partitioning. |

---

## 2. Capacity & Partitioning Rules

1. **Max Devices per Hub (Rule D5)**: Exactly 5 devices ($|N(h)| \le 5$).
2. **Max Area per Hub**: $100.0\text{ m}^2$ maximum assigned area ($\sum_{r \in R(h)} \text{Area}(r) \le 100.0 + 10^{-6}\text{ m}^2$).
3. **Connectivity Requirement**: Any room subset assigned to a single hub must form a connected subgraph in the floor plan's topological adjacency graph. Disconnected clusters are strictly invalid.
4. **Partition Exhaustiveness**: Every eligible room must be assigned to exactly one hub ($\sum_{h} \mathbf{1}_{r \in R(h)} = 1, \forall r$).

---

## 3. Dual-Reading Ranking System & Checker Mirror

To eliminate optimistic scoring discrepancies between solver heuristics and independent evaluation, candidate arrangements are evaluated through a **Checker Mirror**:

### 3.1 Ranking Tuple
Every evaluated arrangement is ranked lexicographically by:
$$\text{Rank} = \left( H, \max(J_{\text{solver}}, J_{\text{checker}}), \text{Area Gap} \right)$$

1. **Primary Metric (Fewest Hubs $H$)**: Minimize total control hub count first.
2. **Secondary Metric (Worse $J$ of Two Readings)**:
   - Reading 1 ($J_{\text{solver}}$): Solver's internal path metric calculation.
   - Reading 2 ($J_{\text{checker}}$): Independent checker mirror recomputation from emitted polylines.
   - The arrangement is scored strictly on $\max(J_{\text{solver}}, J_{\text{checker}})$. This penalizes any numerical ambiguity or discretization variance.
3. **Tertiary Metric (Area Gap)**:
   $$\text{Area Gap} = \max_{h} \text{Area}(h) - \min_{h} \text{Area}(h)$$
   Prefers evenly distributed electrical circuit loads.

### 3.2 Checker Mirror Gate
During rip-up-and-reroute passes and candidate selection, candidate solutions must pass the independent validator before acceptance. If an alternative fails the checker mirror, it is rejected, guaranteeing that only 100% verified designs are submitted.

---

## 4. Geometric Tolerances & Routing Conventions

### 4.1 Routing Profiles
- **Profile 0.0 m (Slide Rules / Obstacle Avoidance)**:
  Wires avoid penetrating solid wall geometries and window openings while utilizing full door widths. Conduits may hug wall edges up to $0.05\text{ m}$ to maximize pathway space in narrow corridors.
- **Profile 0.5 m (Strict Clearance)**:
  Wires and hubs must maintain at least $0.50\text{ m}$ clearance from all physical barrier boundaries (walls and windows), except when traversing designated door openings.

### 4.2 Door Traversals (Rule D7)
- Cable conduits passing between adjacent rooms must cross strictly within the designated door opening polygon.
- Door transit points are placed at the medial centerline of the door polygon to maximize lateral clearance from door frames. Default minimum door passage width is $0.50\text{ m}$.

### 4.3 Metric Calculation Rules
- **Length ($L$)**: Computed as the Euclidean sum of all segment lengths in metres along the closed ring:
  $$L = \sum_{i=0}^{k} \text{dist}(V_i, V_{i+1}) \quad \text{where } V_{k+1} = V_0$$
- **Bends ($B$)**: Counted as every change in coordinate heading $\ge 45^\circ$ along the polyline. A $180^\circ$ reversal counts as one sharp bend.
- **Crossings ($X$)**: The count of transversal geometric intersections between non-adjacent line segments. Coincident collinear segments are treated as overlap, not crossings.
- **Overlap ($O$)**: The total metric length of collinear cable segments traversing the same conduit path.

---

## 5. Single-Point-of-Failure (SPoF) Resilience
- All cable routes must form **closed 2-regular cycles** (rings).
- If any single cable segment is severed, the hub's dual-ended current feed ensures that both the clockwise and counter-clockwise sub-chains remain energized.
- A design that leaves any terminal device isolated under any single cable break is deemed non-compliant with ring resilience standards.
