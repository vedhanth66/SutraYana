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
        # The checker treats a 1 mm neighbourhood as a terminal visit. Exact
        # vertex absorption alone misses parallel passes and near-endpoint turns.
        edge_lo = np.minimum(self.xy[u], self.xy[v])
        edge_hi = np.maximum(self.xy[u], self.xy[v])
        horizontal_edges = self.xy[u, 1] == self.xy[v, 1]
        for room in plan.eligible.values():
            p = np.asarray(room.node)
            delta = np.maximum(np.maximum(edge_lo-p, p-edge_hi), 0)
            near = np.sum(delta*delta, axis=1) < .001**2
            aligned = np.where(horizontal_edges, np.abs(self.xy[u, 1]-p[1]), np.abs(self.xy[u, 0]-p[0])) < 1e-10
            good &= ~near | aligned
        u, v = u[good], v[good]
        delta = self.xy[v]-self.xy[u]
        direction = np.where(delta[:, 0] > 0, 0, 1)
        lengths = np.abs(delta).sum(axis=1)
        self._positive_edges = len(u)
        self._edge_grids = []
        for d in (0, 1):
            grid = np.full(nx_*ny_, -1, dtype=np.int32)
            selected = np.flatnonzero(direction == d)
            grid[u[selected]] = selected
            self._edge_grids.append(grid.reshape(ny_, nx_))
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
        self._terminal_vertices = {self.vertex(p) for p in terminals}
        self._paths = {}
        self._order = np.lexsort((self.targets, self.sources))
        counts = np.bincount(self.sources, minlength=self.size)
        counts[-1] = 4
        self._indptr = np.concatenate(([0], np.cumsum(counts))).astype(np.int32)
        self._indices = np.concatenate((self.targets[self._order], np.zeros(4, dtype=int))).astype(np.int32)
        self._base_data = self.costs[self._order]
        self._edge_sources = self.sources[self._order] // 4
        self._xy_u, self._xy_v = self.xy[self.u], self.xy[self.v]
        self._edge_min = np.minimum(self._xy_u, self._xy_v)
        self._edge_max = np.maximum(self._xy_u, self._xy_v)

    def _graph(self, source, blocked, extra=None, start_cost=None):
        # Reuse the sorted CSR structure; only edge weights and the four
        # super-source destinations change between shortest-path searches.
        data = self._base_data.copy()
        if extra is not None:
            data += extra[self._order % len(self.u)]
        if blocked:
            mask = np.zeros(len(self.xy), dtype=bool)
            mask[list(blocked)] = True
            data[mask[self._edge_sources]] = np.inf
        indices = self._indices.copy()
        indices[-4:] = source*4 + np.arange(4)
        data = np.concatenate((data, np.zeros(4) if start_cost is None else start_cost))
        return csr_matrix((data, indices, self._indptr), shape=(self.size, self.size))

    def vertex(self, p):
        x, y = np.searchsorted(self.xs, p[0]), np.searchsorted(self.ys, p[1])
        return int(y*len(self.xs)+x)

    def from_source(self, point):
        source = self.vertex(point)
        if source in self.cache:
            return self.cache[source]
        # Other fixed nodes are absorbing destinations, never intermediate waypoints.
        start = self.size-1
        graph = self._graph(source, self.fixed-{source})
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
        source, target_vertex = self.vertex(a), self.vertex(b)
        if source not in self._paths or target_vertex not in self._paths[source]:
            dist, pred = self.from_source(a)
            paths = {}
            # Keep compact terminal paths, not a full distance/predecessor tree
            # for every hub candidate. On large plans those trees used hundreds
            # of megabytes per worker and were repeatedly paged through memory.
            targets = (self._terminal_vertices if source in self.fixed else self.fixed) | {target_vertex}
            for destination in targets:
                target = destination*4
                end = target + int(np.argmin(dist[target:target+4]))
                if not np.isfinite(dist[end]):
                    paths[destination] = None
                    continue
                ids = []
                while end != self.size-1:
                    ids.append(end//4)
                    end = int(pred[end])
                    if end < 0:
                        raise ValueError("Incomplete path in routing graph")
                paths[destination] = compact([tuple(self.xy[i]) for i in reversed(ids)])
            self._paths.setdefault(source, {}).update(paths)
            self.cache.pop(source, None)
        result = self._paths[source].get(target_vertex)
        if result is None:
            raise ValueError(f"No obstacle-free rectilinear route from {a} to {b}.")
        return result

    def alternative(self, a, b, occupied, terminals, hub, incoming=None, outgoing=None):
        """Turn-aware reroute with overlap/crossing costs; final acceptance uses exact J."""
        source, target_vertex = self.vertex(a), self.vertex(b)
        xy_u, xy_v = self._xy_u, self._xy_v
        extra = np.zeros(len(self.u))
        for c,d in occupied:
            if c == d:
                continue
            hor = abs(c[1]-d[1]) < 1e-8
            axis, fixed = (0,1) if hor else (1,0)
            lo,hi = min(c[axis],d[axis]),max(c[axis],d[axis])
            # Only inspect grid edges near this segment, not every edge in the
            # floor plan for each occupied cable segment.
            along = self.xs if hor else self.ys
            across = self.ys if hor else self.xs
            def edges(grid, i0, i1, j0, j1):
                block = grid[j0:j1, i0:i1] if hor else grid[i0:i1, j0:j1]
                ids = block.ravel()
                ids = ids[ids >= 0]
                return np.concatenate((ids, ids+self._positive_edges))
            i0 = max(0, int(np.searchsorted(along, lo, side="right"))-1)
            i1 = int(np.searchsorted(along, hi, side="left"))+1
            j0, j1 = np.searchsorted(across, [c[fixed]-.001, c[fixed]+.001])
            same = edges(self._edge_grids[0 if hor else 1], i0, i1, j0, j1)
            same = same[np.abs(xy_u[same,fixed]-c[fixed]) < .001]
            extra[same] += np.maximum(0, np.minimum(self._edge_max[same,axis],hi)-np.maximum(self._edge_min[same,axis],lo))
            i0 = int(np.searchsorted(along, lo-.0001, side="left"))
            i1 = int(np.searchsorted(along, hi+.0001, side="right"))
            j0 = max(0, int(np.searchsorted(across, c[fixed], side="left"))-1)
            j1 = int(np.searchsorted(across, c[fixed], side="right"))+1
            selected = edges(self._edge_grids[1 if hor else 0], i0, i1, j0, j1)
            selected = selected[(self._edge_min[selected,fixed]<=c[fixed]) & (self._edge_max[selected,fixed]>=c[fixed])]
            # Count at arrival, not again when leaving the same intersection.
            selected = selected[np.abs(xy_u[selected,fixed]-c[fixed]) > 1e-8]
            for p in terminals:
                if abs(c[fixed]-p[fixed]) < .001:
                    selected = selected[np.abs(xy_v[selected,axis]-p[axis]) >= .001]
            extra[selected] += 5
        blocked = self.fixed-{source}
        if a != hub and b != hub:
            blocked = blocked | {self.vertex(hub)}
        start = self.size-1
        start_cost = np.zeros(4) if incoming is None else .5*(np.arange(4)!=incoming)
        graph = self._graph(source, blocked, extra, start_cost)
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
