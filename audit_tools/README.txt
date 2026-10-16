Independent audit tools (written from the problem statement, not from SutraYana code)

validate.py   : checks an output dict against the rules: coverage, capacity, closed sequence that lists EVERY assigned node,
                axis-aligned, cable inside (inner - wall - window), node visits, hub point clearance, and recomputes L/B/O across ALL rings.
adjacency.py  : door + open-passage room graph from raw geometry (no wall-only links) and an exact minimum-hub partition solver.
run_audit.py  : run from the SutraYana repo root:  RESPLAN_PKL=path/to/ResPlan.pkl python audit_tools/run_audit.py 0 1 2 3
partition_greedy_vs_exact.py : greedy vs exact hub-count comparison on 400 random plans.
Open parameters to confirm with organisers: open-passage minimum width (0.5 m here), tolerance (2 mm here).
