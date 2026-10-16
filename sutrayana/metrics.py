"""Global scoring from polylines, including interactions between rings."""
from collections import defaultdict
import math

TOL = 0.001


def compact(points):
    out = []
    for p in points:
        p = tuple(p)
        if out and math.dist(out[-1], p) < 1e-10:
            continue
        if len(out) >= 2:
            a, b = out[-2:]
            if ((abs(a[0]-b[0]) < 1e-10 and abs(b[0]-p[0]) < 1e-10 and (b[1]-a[1])*(p[1]-b[1]) > 0)
                or (abs(a[1]-b[1]) < 1e-10 and abs(b[1]-p[1]) < 1e-10 and (b[0]-a[0])*(p[0]-b[0]) > 0)):
                out.pop()
        out.append(p)
    return out


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def score(hubs, node_points=()):
    segments, exempt, bends, total_length = [], list(node_points), 0, 0.0
    for hi, h in enumerate(hubs):
        exempt.append((h["location"]["x"], h["location"]["y"]))
        ring = []
        for leg in h["route_segments"]:
            p = compact(leg["polyline"])
            ring.extend(p if not ring else p[1:])
        ring = compact(ring)
        directions = []
        for si, (a, b) in enumerate(zip(ring, ring[1:])):
            dx, dy = b[0]-a[0], b[1]-a[1]
            if abs(dx)+abs(dy) < 1e-10:
                continue
            horizontal = abs(dy) < 1e-8
            directions.append((horizontal, 1 if dx+dy > 0 else -1))
            segments.append((hi, si, a, b, horizontal))
            total_length += math.hypot(dx, dy)
        bends += sum(directions[i] != directions[i-1] for i in range(len(directions)))
    # Group parallel lines by actual distance rather than rounding-bin coincidence.
    overlap = 0.0
    for horizontal in (True, False):
        lines = sorted((a[1] if horizontal else a[0], min(a[0],b[0]) if horizontal else min(a[1],b[1]), max(a[0],b[0]) if horizontal else max(a[1],b[1]))
                       for _, _, a, b, hor in segments if hor == horizontal)
        groups = []
        for line, lo, high in lines:
            if not groups or line - groups[-1][0] >= TOL:
                groups.append((line, []))
            groups[-1][1].extend([(lo, 1), (high, -1)])
        for _, events in groups:
            cover, prev = 0, None
            for pos, delta in sorted(events):
                if prev is not None:
                    overlap += max(0, cover-1) * (pos-prev)
                cover += delta
                prev = pos
    crossings = []
    ring_sizes = defaultdict(int)
    for hi, si, *_ in segments:
        ring_sizes[hi] = max(ring_sizes[hi], si+1)
    for i, (hi, si, a, b, horizontal) in enumerate(segments):
        for hj, sj, c, d, other_horizontal in segments[i+1:]:
            if hi == hj and (abs(si-sj) == 1 or {si, sj} == {0, ring_sizes[hi]-1}):
                continue  # The two sides of an ordinary bend are one cable.
            if horizontal == other_horizontal:
                # Positive collinear intervals are accounted for by O, not infinitely many X.
                axis, fixed = (0, 1) if horizontal else (1, 0)
                if abs(a[fixed]-c[fixed]) >= TOL:
                    continue
                lo, high = max(min(a[axis], b[axis]), min(c[axis], d[axis])), min(max(a[axis], b[axis]), max(c[axis], d[axis]))
                if abs(high-lo) >= TOL:
                    continue
                p = (lo, a[fixed]) if horizontal else (a[fixed], lo)
            else:
                ha, hb, va, vb = (a,b,c,d) if horizontal else (c,d,a,b)
                p = (va[0], ha[1])
                if not (min(ha[0],hb[0])-TOL < p[0] < max(ha[0],hb[0])+TOL and min(va[1],vb[1])-TOL < p[1] < max(va[1],vb[1])+TOL):
                    continue
            if any(math.dist(p, q) < TOL for q in exempt) or any(math.dist(p, q) < TOL for q in crossings):
                continue
            crossings.append(p)
    return {"hub_count": len(hubs), "total_length_m": total_length,
            "total_crossings": len(crossings), "total_overlap_m": overlap,
            "total_bends": bends, "total_cost_J": total_length + 5*len(crossings) + overlap + 0.5*bends}
