"""Rectilinear coordinate graph. Every edge is tested against exact free space.

Coordinates include obstacle offsets, gap midpoints, and exact input terminals.
No raster dilation, door carving, diagonal stubs, or obstacle-removing fallback.
"""
import numpy as np
import shapely
from shapely.geometry import LineString, Point
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from .metrics import compact


class Router:
    def __init__(self, plan, hubs):
        self.plan = plan
        terminals = [r.node for r in plan.eligible.values()] + [p for ps in hubs.values() for p in ps]
        coords = shapely.get_coordinates(plan.free)
        axes = []
        for axis in (0, 1):
            lo, hi = plan.inner.bounds[axis], plan.inner.bounds[axis+2]
            # GEOS may return the same boundary coordinate with tiny numerical
            # differences. Merge those before forming a Cartesian product.
            # Exact terminal coordinates are added separately and never rounded.
            critical = sorted(set(round(float(x),8) for x in coords[:, axis]))
            values = set()
            for a, b in zip(critical, critical[1:]):
                values.add((a+b)/2)
            for c in critical:
                values.update([c-0.015, c+0.015])
            for p in terminals:
                values.update([p[axis], p[axis]-0.004, p[axis]+0.004])
            axes.append(np.array(sorted(v for v in values if lo <= v <= hi)))
        self.xs, self.ys = axes
        nx_, ny_ = len(self.xs), len(self.ys)
        if nx_*ny_ > 1_500_000:
            raise ValueError("Geometry exceeds the coordinate-graph size limit; simplify source geometry first.")
        xx, yy = np.meshgrid(self.xs, self.ys)
        self.xy = np.column_stack([xx.ravel(), yy.ravel()])
        vertex = np.arange(nx_*ny_).reshape(ny_, nx_)
        u = np.concatenate([vertex[:, :-1].ravel(), vertex[:-1, :].ravel()])
        v = np.concatenate([vertex[:, 1:].ravel(), vertex[1:, :].ravel()])
        lines = shapely.linestrings(np.stack([self.xy[u], self.xy[v]], axis=1))
        # Stay a micron inside free space to avoid floating-point boundary
        # inconsistencies when adjacent graph edges are merged into long runs.
        safe_free = plan.free.buffer(-0.000001, join_style=2)
        self.safe_free = safe_free
        shapely.prepare(safe_free)
        good = shapely.covers(safe_free, lines)
        u, v = u[good], v[good]
        delta = self.xy[v]-self.xy[u]
        direction = np.where(delta[:, 0] > 0, 0, 1)
        lengths = np.abs(delta).sum(axis=1)
        self.u = np.concatenate([u,v])
        self.v = np.concatenate([v,u])
        self.direction = np.concatenate([direction, direction+2])
        self.weights = np.concatenate([lengths,lengths])
        self.size = len(self.xy)*4 + 1
        self.sources = np.concatenate([self.u*4 + d for d in range(4)])
        self.targets = np.tile(self.v*4 + self.direction, 4)
        self.costs = np.concatenate([self.weights + 0.5*(self.direction != d) for d in range(4)])
        self.fixed = {self.vertex(r.node) for r in plan.eligible.values()}
        self.cache = {}

    def vertex(self, p):
        x, y = np.searchsorted(self.xs, p[0]), np.searchsorted(self.ys, p[1])
        return int(y*len(self.xs)+x)

    def from_source(self, point):
        source = self.vertex(point)
        if source in self.cache:
            return self.cache[source]
        # Other fixed nodes are absorbing destinations, never intermediate waypoints.
        allowed = ~np.isin(self.sources//4, list(self.fixed-{source}))
        start = self.size-1
        rows = np.concatenate([self.sources[allowed], np.repeat(start, 4)])
        cols = np.concatenate([self.targets[allowed], source*4+np.arange(4)])
        weights = np.concatenate([self.costs[allowed], np.zeros(4)])
        graph = csr_matrix((weights, (rows, cols)), shape=(self.size,self.size))
        dist, predecessor = dijkstra(graph, directed=True, indices=start, return_predecessors=True)
        self.cache[source] = (dist, predecessor)
        return dist, predecessor

    def path(self, a, b):
        if a == b:
            return [a, b]
        if a[0] == b[0] or a[1] == b[1]:
            direct = LineString([a,b])
            if self.safe_free.covers(direct) and not any(r.node not in (a,b) and direct.distance(Point(r.node)) < .001 for r in self.plan.eligible.values()):
                return [a,b]
        dist, pred = self.from_source(a)
        target = self.vertex(b)*4
        end = target + int(np.argmin(dist[target:target+4]))
        if not np.isfinite(dist[end]):
            raise ValueError(f"No obstacle-free rectilinear route from {a} to {b}.")
        ids = []
        while end != self.size-1:
            ids.append(end//4)
            end = int(pred[end])
            if end < 0:
                raise ValueError("Incomplete path in routing graph")
        return compact([tuple(self.xy[i]) for i in reversed(ids)])

    def alternative(self, a, b, occupied, terminals, hub, incoming=None, outgoing=None):
        """Turn-aware reroute with overlap/crossing costs; final acceptance uses exact J."""
        source, target_vertex = self.vertex(a), self.vertex(b)
        xy_u, xy_v = self.xy[self.u], self.xy[self.v]
        horizontal = self.direction % 2 == 0
        extra = np.zeros(len(self.u))
        for c,d in occupied:
            if c == d:
                continue
            hor = abs(c[1]-d[1]) < 1e-8
            axis, fixed = (0,1) if hor else (1,0)
            lo,hi = min(c[axis],d[axis]),max(c[axis],d[axis])
            same = (horizontal == hor) & (np.abs(xy_u[:,fixed]-c[fixed]) < .001)
            shared = np.maximum(0,np.minimum(np.maximum(xy_u[:,axis],xy_v[:,axis]),hi)-np.maximum(np.minimum(xy_u[:,axis],xy_v[:,axis]),lo))
            extra += same*shared
            crosses = (horizontal != hor) & (xy_v[:,axis]>=lo-.0001) & (xy_v[:,axis]<=hi+.0001) & (np.minimum(xy_u[:,fixed],xy_v[:,fixed])<=c[fixed]) & (np.maximum(xy_u[:,fixed],xy_v[:,fixed])>=c[fixed])
            # Count at arrival, not again when leaving the same intersection.
            crosses &= np.abs(xy_u[:,fixed]-c[fixed]) > 1e-8
            for p in terminals:
                crosses &= ~((np.abs(xy_v[:,axis]-p[axis]) < .001) & (abs(c[fixed]-p[fixed]) < .001))
            extra += 5*crosses
        blocked = self.fixed-{source}
        if a != hub and b != hub:
            blocked = blocked | {self.vertex(hub)}
        allowed = ~np.isin(self.sources//4,list(blocked))
        start = self.size-1
        start_cost = np.zeros(4) if incoming is None else .5*(np.arange(4)!=incoming)
        weights = self.costs + np.tile(extra,4)
        graph = csr_matrix((np.concatenate([weights[allowed],start_cost]),
                            (np.concatenate([self.sources[allowed],np.repeat(start,4)]),
                             np.concatenate([self.targets[allowed],source*4+np.arange(4)]))),shape=(self.size,self.size))
        dist,pred = dijkstra(graph,directed=True,indices=start,return_predecessors=True)
        target = target_vertex*4
        end_cost = dist[target:target+4] + (0 if outgoing is None else .5*(np.arange(4)!=outgoing))
        end = target+int(np.argmin(end_cost))
        if not np.isfinite(dist[end]):
            raise ValueError("No alternative route")
        ids = []
        while end != start:
            ids.append(end//4)
            end = int(pred[end])
        return compact([tuple(self.xy[i]) for i in reversed(ids)])
