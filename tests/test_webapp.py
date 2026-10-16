import unittest

from sutrayana.runtime import solve_bounded


class WebAppCompatibilityTests(unittest.TestCase):
    def test_runtime_exports_solve_bounded(self):
        self.assertTrue(callable(solve_bounded))

    def test_import_solution_links_to_base_plan(self):
        from webapp import add_plan, CATALOG, load_catalog
        import json
        from pathlib import Path
        load_catalog()
        root = Path(__file__).resolve().parents[1]
        output_file = root / "output_plan.json"
        if output_file.exists():
            sol = json.loads(output_file.read_text(encoding="utf-8"))
            key = add_plan(sol, "output_plan.json", "Imported JSON")
            item = CATALOG[key]
            self.assertEqual(item["name"], "14433")
            self.assertEqual(item["rooms"], 10)
            self.assertTrue("solution" in item)


    def test_solve_bounded_clearance_profiles(self):
        import json
        from pathlib import Path
        from sutrayana.model import Plan
        from shapely.geometry import LineString
        root = Path(__file__).resolve().parents[1]
        sample = json.loads((root / "sample_plan.json").read_text(encoding="utf-8"))
        
        # Test existing profile: wire_clearance = 0
        res0 = solve_bounded(sample, wire_clearance=0.0)
        self.assertTrue(res0["ok"])
        self.assertEqual(res0["output"]["solver"]["wire_clearance_m"], 0.0)
        
        # Test extra profile: wire_clearance = 0.5
        res5 = solve_bounded(sample, wire_clearance=0.5)
        self.assertTrue(res5["ok"])
        self.assertEqual(res5["output"]["solver"]["wire_clearance_m"], 0.5)
        p5 = Plan(sample, wire_clearance=0.5)
        lines = [LineString(l["polyline"]) for h in res5["output"]["hubs"] for l in h["route_segments"]]
        measured = min(l.distance(p5.barriers) for l in lines)
        self.assertGreaterEqual(measured, 0.5 - 0.001)

    def test_solve_bounded_rl_mode(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        sample = json.loads((root / "sample_plan.json").read_text(encoding="utf-8"))
        res_rl = solve_bounded(sample, wire_clearance=0.0, use_rl=True, timeout=60)
        self.assertTrue(res_rl["ok"])
        self.assertTrue(res_rl["output"]["solver"]["rl_adaptive_routing"])



if __name__ == "__main__":
    unittest.main()
