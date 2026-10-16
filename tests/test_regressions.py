import unittest
from pathlib import Path
import numpy as np
from shapely.geometry import box, mapping, Point, MultiPolygon
from sutrayana.model import Plan
from sutrayana.exporter import extract_rooms_and_doors, BenchmarkIneligible
from sutrayana.routing import Router
from sutrayana.solver import solve_plan
from sutrayana.validation import validate
from test_solver import fixture


class RegressionTests(unittest.TestCase):
    def test_scaling_repair_recovers_recorded_topology_exception(self):
        p = Plan(Path(__file__).parent/"fixtures/plan_757.json")
        self.assertTrue(p.barriers.is_valid)
        self.assertTrue(solve_plan(p)["validation"]["valid"])

    def test_door_contacts_do_not_join_disconnected_node_components(self):
        raw = fixture()
        # One labelled room spans both disconnected sides, so a door can touch
        # that room somewhere other than the component containing its node.
        raw["wall"] = mapping(box(40,0,42,40))
        raw["rooms"][0]["polygon"] = mapping(MultiPolygon([box(0,0,40,40),box(42,0,50,40)]))
        raw["rooms"][1]["polygon"] = mapping(box(50,0,82,40))
        raw["doors"] = [{"polygon":mapping(box(49,15,51,25))}]
        p = Plan(raw)
        self.assertEqual(len(p.graph.edges),0)
        self.assertTrue(solve_plan(p)["validation"]["valid"])

    def test_demo_clearance_uses_walls_not_open_room_edges(self):
        raw = {"inner": box(0,0,4,4), "area":16, "wall":None,
               "storage":box(1,1,1.8,3), "living":None}
        converted = extract_rooms_and_doors(raw)
        out = solve_plan(converted)
        self.assertTrue(out["validation"]["valid"])
        self.assertEqual(len(out["hubs"]), 1)

    def test_impossible_demo_clearance_is_not_a_pass(self):
        raw = {"inner":box(0,0,4,4), "area":16, "storage":box(1,1,1.8,3),
               "wall":box(0,0,4,4).difference(box(1,1,1.8,3))}
        with self.assertRaises(BenchmarkIneligible) as caught:
            extract_rooms_and_doors(raw)
        self.assertEqual(caught.exception.reason, "node_clearance")

    def test_oversized_room_is_explicitly_ineligible(self):
        with self.assertRaises(BenchmarkIneligible) as caught:
            extract_rooms_and_doors({"inner":box(0,0,20,20),"area":400,"living":box(0,0,20,20)})
        self.assertEqual(caught.exception.reason, "room_capacity")

    def test_demo_nodes_are_distinct_at_checker_tolerance(self):
        raw = {"inner":box(0,0,4,4), "area":16, "wall":None,
               "living":box(0,0,4,4), "kitchen":box(0,0,4,4)}
        out = extract_rooms_and_doors(raw)
        a,b = [Point(r["node"]["x"],r["node"]["y"]) for r in out["rooms"]]
        self.assertGreater(a.distance(b), .002)

    def test_terminal_guard_includes_nearby_parallel_passes(self):
        p = Plan(fixture())
        router = Router(p, {r:p.hub_candidates(r) for r in p.eligible})
        xy_u, xy_v = router.xy[router.u], router.xy[router.v]
        for room in p.eligible.values():
            node = np.asarray(room.node)
            delta = np.maximum(np.maximum(np.minimum(xy_u,xy_v)-node,node-np.maximum(xy_u,xy_v)),0)
            near = np.sum(delta*delta,axis=1)<.001**2
            aligned = np.where(router.direction%2==0, np.abs(xy_u[:,1]-node[1]), np.abs(xy_u[:,0]-node[0]))<1e-10
            self.assertFalse(np.any(near & ~aligned))

    def test_terminal_path_cache_reuses_search_without_retaining_trees(self):
        raw = fixture()
        raw["rooms"][1]["node"]["y"] = 30
        p = Plan(raw)
        candidates = {r:p.hub_candidates(r) for r in p.eligible}
        router = Router(p,candidates)
        original = router._graph
        calls = []
        def counted(*args,**kwargs):
            calls.append(1)
            return original(*args,**kwargs)
        router._graph = counted
        router.path(p.rooms["left"].node,p.rooms["right"].node)
        router.path(p.rooms["left"].node,candidates["right"][0])
        self.assertEqual(len(calls),1)
        self.assertFalse(router.cache)

    def test_local_penalties_equal_full_edge_reference(self):
        p = Plan(fixture())
        candidates = {r:p.hub_candidates(r) for r in p.eligible}
        router = Router(p,candidates)
        occupied = [((.7,2),(7.4,2)),((2,.8),(2,3.6)),((1.997,.7),(1.997,3.4)),
                    ((0,1.1),(8.2,1.1)),((7.1,3),(1.1,3))]
        terminals = [r.node for r in p.eligible.values()]
        u,v = router.xy[router.u],router.xy[router.v]
        horizontal = router.direction%2==0
        reference = np.zeros(len(router.u))
        for c,d in occupied:
            hor = c[1]==d[1]
            axis,fixed = (0,1) if hor else (1,0)
            lo,hi = sorted((c[axis],d[axis]))
            same = (horizontal==hor)&(np.abs(u[:,fixed]-c[fixed])<.001)
            reference += same*np.maximum(0,np.minimum(np.maximum(u[:,axis],v[:,axis]),hi)-np.maximum(np.minimum(u[:,axis],v[:,axis]),lo))
            cross = (horizontal!=hor)&(v[:,axis]>=lo-.0001)&(v[:,axis]<=hi+.0001)&(np.minimum(u[:,fixed],v[:,fixed])<=c[fixed])&(np.maximum(u[:,fixed],v[:,fixed])>=c[fixed])
            cross &= np.abs(u[:,fixed]-c[fixed])>1e-8
            for terminal in terminals:
                cross &= ~((np.abs(v[:,axis]-terminal[axis])<.001)&(abs(c[fixed]-terminal[fixed])<.001))
            reference += 5*cross
        original = router._graph
        captured = []
        def capture(source,blocked,extra=None,start_cost=None):
            captured.append(extra.copy())
            return original(source,blocked,extra,start_cost)
        router._graph = capture
        router.alternative(terminals[0],terminals[1],occupied,terminals,candidates['left'][0])
        np.testing.assert_allclose(captured[0],reference,rtol=0,atol=1e-12)

    def test_hub_refinement_never_increases_cost(self):
        p = Plan(fixture())
        out = solve_plan(p)
        self.assertLessEqual(out["reported_metrics"]["total_cost_J"],out["solver"]["cost_before_hub_refinement"])
        self.assertTrue(validate(p,out)["valid"])

    def test_expanded_search_preserves_valid_base_result(self):
        from sutrayana.runtime import solve_bounded
        base = solve_plan(fixture())
        expanded = solve_bounded(fixture(), timeout=30, enhanced=True)
        self.assertTrue(expanded["ok"], expanded)
        out = expanded["output"]
        self.assertTrue(validate(Plan(fixture()),out)["valid"])
        self.assertLessEqual(out["reported_metrics"]["total_cost_J"],base["reported_metrics"]["total_cost_J"]+1e-9)

    def test_clearance_profile_narrow_door_fallback(self):
        from shapely.geometry import LineString
        test3_path = Path(__file__).resolve().parents[1] / "plans/test_03.json"
        # Profile 0: Slide rules allows 1 hub through narrow 0.8m door
        out0 = solve_plan(test3_path, wire_clearance=0.0)
        self.assertEqual(len(out0["hubs"]), 1)
        # Profile 0.5: Requires 2 hubs because 0.8m door cannot pass 0.5m clearance
        out5 = solve_plan(test3_path, wire_clearance=0.5)
        self.assertEqual(len(out5["hubs"]), 2)
        p5 = Plan(test3_path, wire_clearance=0.5)
        lines = [LineString(l["polyline"]) for h in out5["hubs"] for l in h["route_segments"]]
        self.assertGreaterEqual(min(l.distance(p5.barriers) for l in lines), 0.5 - 0.001)

    def test_clearance_profile_wide_doorway_and_sample_plan(self):
        from shapely.geometry import LineString
        root = Path(__file__).resolve().parents[1]
        for path, expected_max_hubs in [("plans/test_02.json", 1), ("sample_plan.json", 4)]:
            plan_file = root / path
            out = solve_plan(plan_file, wire_clearance=0.5)
            p = Plan(plan_file, wire_clearance=0.5)
            self.assertTrue(validate(p, out)["valid"])
            lines = [LineString(l["polyline"]) for h in out["hubs"] for l in h["route_segments"]]
            min_dist = min(l.distance(p.barriers) for l in lines)
            self.assertGreaterEqual(min_dist, 0.5 - 0.001)
            self.assertLessEqual(len(out["hubs"]), expected_max_hubs)


if __name__ == "__main__":
    unittest.main()
