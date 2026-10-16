import unittest
from pathlib import Path
from sutrayana.runtime import solve_bounded

ROOT = Path(__file__).resolve().parents[1]

class FrontendRestoreTests(unittest.TestCase):
    def test_ring_studio_controls_are_present(self):
        html=(ROOT/"web/index.html").read_text(encoding="utf-8")
        self.assertIn("SutraYana / Ring Studio", html)
        for control in ("map","solve","plans","download","save-svg","history","warnings","profile"):
            self.assertIn('id="'+control+'"',html)

    def test_current_backend_returns_ui_metadata(self):
        result=solve_bounded(str(ROOT/"plans/test_01.json"),timeout=15)
        self.assertTrue(result["ok"],result)
        self.assertGreater(result["elapsed_s"],0)
        self.assertEqual(result["output"]["solver"]["wire_clearance_m"],.5)

    def test_deadline_is_enforced(self):
        result=solve_bounded(str(ROOT/"plans/test_01.json"),timeout=.001)
        self.assertFalse(result["ok"])
        self.assertIn("Time limit",result["error"])

if __name__ == "__main__":
    unittest.main()
