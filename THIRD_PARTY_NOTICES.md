# Third-party data and tools

The example plan in `sample_plan.json` and `examples/resplan_0.json`, and their generated overlays, derive from dataset index 0 (plan ID 14433) of ResPlan, by the ResPlan Authors. The geometric data is supplied under Creative Commons Attribution 4.0 International (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/.

Dataset reference supplied by the challenge: https://www.kaggle.com/datasets/resplan/resplan. SutraYana converts the geometry to its JSON schema, generates explicitly labelled demo node positions, and adds computed zones, hubs and cable routes. Those additions are not part of the original dataset.

The full dataset and upstream source remain local under the ignored `ResPlan/` directory. They are not included in the submission bundle. The upstream licence text is retained at `examples/ResPlan-LICENSE.txt`.

The `audit_tools/` directory was supplied with the user's audit context. Its validator is retained unchanged; `tools/independent_audit.py` adapts the coordinate origin and runs it against this implementation. The external auditor does not provide a complete crossing count, so crossing behaviour is covered by explicit regression fixtures in `tests/test_solver.py`.

Runtime dependencies are NumPy, SciPy, Shapely, NetworkX and Matplotlib, installed separately through `requirements.txt`; their licences remain with their distributions.
