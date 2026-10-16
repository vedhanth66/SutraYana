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


if __name__ == "__main__":
    unittest.main()
