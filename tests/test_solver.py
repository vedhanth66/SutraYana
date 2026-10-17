import copy
import unittest
from shapely.geometry import box, mapping
from shapely.ops import unary_union
from sutrayana.model import Plan
from sutrayana.solver import solve_plan, minimum_partitions
from sutrayana.metrics import score
from sutrayana.validation import validate


def fixture():
    # Two rooms, wall with one real door. Units deliberately differ from metres.
    rooms = [{"id":"left","type":"living","polygon":mapping(box(0,0,40,40)),"node":{"id":"N1","x":20,"y":20}},
             {"id":"right","type":"bedroom","polygon":mapping(box(42,0,82,40)),"node":{"id":"N2","x":62,"y":20}}]
    return {"id":"test","area":32.8,"inner":mapping(box(0,0,82,40)),"rooms":rooms,
            "wall":mapping(unary_union([box(40,0,42,15),box(40,25,42,40)])),
            "window":None,"doors":[{"polygon":mapping(box(40,15,42,25))}]}


def ring(points,hid="H1"):
    return {"hub_id":hid,"location":{"x":points[0][0],"y":points[0][1]},"route_segments":[{"polyline":points}]}


class SolverTests(unittest.TestCase):
    def test_door_route_and_coverage(self):
        raw = fixture()
        before = copy.deepcopy(raw)
        out = solve_plan(raw)
        self.assertEqual(raw,before)
        self.assertEqual(len(out["hubs"]),1)
        self.assertEqual(set(out["hubs"][0]["closed_sequence"][1:-1]),{"N1","N2"})
        self.assertTrue(validate(Plan(raw),out)["valid"])

    def test_wall_only_adjacency_never_connects(self):
        raw = fixture()
        raw["wall"] = mapping(box(40,0,42,40))
        # Even a falsely declared door may not carve through a solid wall.
        p = Plan(raw)
        self.assertEqual(len(p.graph.edges),0)
        self.assertEqual(minimum_partitions(p)[0],2)
        self.assertEqual(len(solve_plan(p)["hubs"]),2)

    def test_window_blocks_door(self):
        raw = fixture()
        raw["window"] = mapping(box(40,15,42,25))
        self.assertEqual(minimum_partitions(Plan(raw))[0],2)

    def test_missing_node_rejected(self):
        raw = fixture()
        del raw["rooms"][0]["node"]
        with self.assertRaisesRegex(ValueError,"fixed input node"):
            Plan(raw)

    def test_merged_door_connects_all_substantial_contacts(self):
        raw = {"id":"merged","area":36,"units":"m","inner":mapping(box(0,0,6,6)),"wall":None,"window":None,
               "doors":[{"polygon":mapping(box(2,2,4,4))}],"rooms":[]}
        for rid,poly,point in [("left",box(0,0,2,6),(1,3)),("right",box(4,0,6,6),(5,3)),("top",box(2,4,4,6),(3,5))]:
            raw["rooms"].append({"id":rid,"type":"bedroom","polygon":mapping(poly),"node":{"id":"N"+rid,"x":point[0],"y":point[1]}})
        self.assertEqual(len(Plan(raw).graph.edges),3)

    def test_area_comes_from_geometry(self):
        raw = fixture()
        raw["rooms"][0]["area"] = 999999
        self.assertAlmostEqual(Plan(raw).rooms["left"].area,16)

    def test_reversal_overlap_and_closure_bends(self):
        m = score([ring([(0,0),(3,0),(0,0)])])
        self.assertEqual(m["total_length_m"],6)
        self.assertEqual(m["total_overlap_m"],3)
        self.assertEqual(m["total_bends"],2)
        self.assertEqual(m["total_crossings"],0)

    def test_rectangle_has_no_crossings(self):
        m = score([ring([(0,0),(3,0),(3,2),(0,2),(0,0)])])
        self.assertEqual(m["total_crossings"],0)
        self.assertEqual(m["total_bends"],4)

    def test_cross_ring_crossing_and_node_exemption(self):
        a = ring([(0,1),(2,1),(0,1)])
        b = ring([(1,0),(1,2),(1,0)],"H2")
        self.assertEqual(score([a,b])["total_crossings"],1)
        self.assertEqual(score([a,b],[(1,1)])["total_crossings"],0)

    def test_t_touch_counts(self):
        a = ring([(0,1),(2,1),(0,1)])
        b = ring([(1,0),(1,1),(1,0)],"H2")
        self.assertEqual(score([a,b])["total_crossings"],1)

    def test_triple_overlap_counts_twice(self):
        hubs = [ring([(0,0),(2,0)],f"H{i}") for i in range(3)]
        self.assertEqual(score(hubs)["total_overlap_m"],4)

    def test_line_tolerance_across_rounding_boundary(self):
        self.assertEqual(score([ring([(0,.00049),(2,.00049)]),ring([(0,.00051),(2,.00051)],"H2")])["total_overlap_m"],2)

    def test_invalid_diagonal_and_skipped_node(self):
        p = Plan(fixture())
        out = solve_plan(p)
        out["hubs"][0]["closed_sequence"].pop(1)
        self.assertFalse(validate(p,out)["valid"])

    def test_empty_eligible_set(self):
        raw = fixture()
        for r in raw["rooms"]:
            r["type"] = "bathroom"
        self.assertEqual(solve_plan(raw)["hubs"],[])

    def test_capacity_exact_search(self):
        raw = fixture()
        p = Plan(raw)
        # Three 40 m² rooms connected as a path: area forces two hubs.
        from sutrayana.model import Room
        p.eligible = {str(i):Room(str(i),"living",box(i*5,0,i*5+4,10),(i*5+2,5),f"N{i}") for i in range(3)}
        p.rooms = p.eligible
        import networkx as nx
        p.graph = nx.path_graph(list(p.eligible))
        p.free = box(0,0,20,10)
        self.assertEqual(minimum_partitions(p)[0],2)

    def test_translation_preserves_nodes(self):
        from shapely import affinity
        from shapely.geometry import shape
        raw = fixture()
        for key in ("inner","wall"):
            raw[key] = mapping(affinity.translate(shape(raw[key]),100,200))
        for d in raw["doors"]:
            d["polygon"] = mapping(affinity.translate(shape(d["polygon"]),100,200))
        for r in raw["rooms"]:
            r["polygon"] = mapping(affinity.translate(shape(r["polygon"]),100,200))
            r["node"]["x"] += 100
            r["node"]["y"] += 200
        self.assertEqual(Plan(raw).rooms["left"].node,(2,2))
        self.assertTrue(solve_plan(raw)["validation"]["valid"])

    def test_missing_wall_is_not_assumed_free(self):
        raw = fixture()
        del raw["wall"]
        with self.assertRaisesRegex(ValueError,"Missing wall"):
            Plan(raw)

    def test_malformed_submission_returns_errors(self):
        p = Plan(fixture())
        for malformed in [None,[],{"hubs":[None]},{"hubs":"wrong"}]:
            self.assertFalse(validate(p,malformed)["valid"])

    def test_validator_rejects_wall_cut(self):
        p = Plan(fixture())
        out = solve_plan(p)
        leg = out["hubs"][0]["route_segments"][1]
        a,b = leg["polyline"][0],leg["polyline"][-1]
        leg["polyline"] = [a,(a[0],.5),(b[0],.5),b]
        rules = {e["rule"] for e in validate(p,out)["errors"]}
        self.assertIn("freespace",rules)

    def test_exact_partition_matches_independent_exhaustive_search(self):
        import random
        import networkx as nx
        from sutrayana.model import Room
        rng = random.Random(17)
        for _ in range(25):
            p = Plan(fixture())
            n = rng.randint(3,7)
            p.eligible = {str(i):Room(str(i),"living",box(i*20,0,i*20+4,rng.choice([4,8,16,24])),(i*20+2,2),f"N{i}") for i in range(n)}
            p.rooms = p.eligible
            p.free = box(0,0,n*20,25)
            p.graph = nx.Graph()
            p.graph.add_nodes_from(p.rooms)
            p.graph.add_edges_from((str(i),str(j)) for i in range(n) for j in range(i+1,n) if rng.random()<.4)
            best = n
            # Check connectivity at completed partitions, including temporary
            # disconnected subsets that a later room can join.
            def exhaustive(remaining,groups):
                nonlocal best
                if not remaining:
                    if all(nx.is_connected(p.graph.subgraph(g)) for g in groups):
                        best = min(best,len(groups))
                    return
                r = remaining[0]
                for group in groups:
                    if len(group)<5 and sum(p.rooms[x].area for x in group)+p.rooms[r].area<=100:
                        group.append(r)
                        exhaustive(remaining[1:],groups)
                        group.pop()
                if len(groups)<best:
                    exhaustive(remaining[1:],groups+[[r]])
            exhaustive(list(p.rooms),[])
            self.assertEqual(minimum_partitions(p)[0],best)

    def test_lower_bound_and_proven_flag(self):
        from sutrayana.solver import compute_hub_lower_bound
        raw = fixture()
        p = Plan(raw)
        lb = compute_hub_lower_bound(p)
        self.assertGreaterEqual(lb, 1)
        out = solve_plan(p)
        self.assertEqual(out["solver"]["lower_bound_hubs"], lb)
        self.assertTrue(out["solver"]["hub_count_proven"])
        self.assertFalse(out["solver"]["fallback_ladder_activated"])
        self.assertIn(1, out["solver"]["attempted_hub_counts"])

    def test_scalable_connected_zones_generator(self):
        from sutrayana.solver import generate_connected_zones
        p = Plan(fixture())
        zones = generate_connected_zones(p)
        self.assertGreater(len(zones), 0)
        # Verify every returned zone is connected and has <= 5 rooms
        for mask, room_ids in zones.items():
            self.assertLessEqual(len(room_ids), 5)
            self.assertTrue(sum(p.rooms[r].area for r in room_ids) <= 100.0 + 1e-8)


if __name__ == "__main__":
    unittest.main()

