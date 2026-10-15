import sys, os
sys.path.insert(0, os.path.abspath('.'))
import pickle
from export_resplan_to_json import extract_rooms_and_doors
from phase4_routing import run_phase4, calculate_ring_metrics

with open('ResPlan/ResPlan/ResPlan.pkl', 'rb') as f:
    data = pickle.load(f)

p = extract_rooms_and_doors(data[713], plan_id='plan_00713')
out, total_J, hubs = run_phase4(p, verbose=False)
h = hubs['R01_living']
m = h['metrics']
print(f"Plan 713: L={m['L']}, B={m['B']}, O={m['O']}, X={m['X']}, J={m['J']}")

poly = h['polyline']
tol_mm = 0.001
h_segs = []
v_segs = []
for k in range(len(poly) - 1):
    x1, y1 = poly[k]
    x2, y2 = poly[k + 1]
    if abs(y2 - y1) <= tol_mm:
        h_segs.append((round(0.5 * (y1 + y2), 3), min(x1, x2), max(x1, x2), (x1, y1), (x2, y2)))
    else:
        v_segs.append((round(0.5 * (x1 + x2), 3), min(y1, y2), max(y1, y2), (x1, y1), (x2, y2)))

print(f"\nTotal H segments: {len(h_segs)}, Total V segments: {len(v_segs)}")
cross_idx = 0
for cy, x1, x2, p1, p2 in h_segs:
    for cx, y1, y2, q1, q2 in v_segs:
        if (x1 + tol_mm < cx < x2 - tol_mm) and (y1 + tol_mm < cy < y2 - tol_mm):
            cross_idx += 1
            print(f"  Crossing {cross_idx}: H seg ({p1} -> {p2}) at y={cy} crossed by V seg ({q1} -> {q2}) at x={cx}")

from shapely.geometry import shape

print("\n--- Scaled Room Bounds ---")
scale = 15.7055
for r in p['rooms']:
    if r['type'] in ['living', 'bedroom', 'kitchen', 'storage']:
        b = shape(r['polygon']).bounds
        print(f"{r['id']} ({r['type']}): x=[{b[0]/scale:.2f}, {b[2]/scale:.2f}], y=[{b[1]/scale:.2f}, {b[3]/scale:.2f}]")

print("\n--- Door Locations ---")
for d in p['doors']:
    b = shape(d['polygon']).bounds
    print(f"{d['id']}: x=[{b[0]/scale:.2f}, {b[2]/scale:.2f}], y=[{b[1]/scale:.2f}, {b[3]/scale:.2f}]")

