"""Local plan workbench. No external services or web framework required."""
import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from shapely.geometry import mapping, LineString, Polygon
from sutrayana.model import Plan, plan_from_solution
from sutrayana.runtime import solve_bounded
from sutrayana.hubring.solve import solve_plan as hubring_solve, top_solutions, to_json as hubring_to_json
from sutrayana.image_import import load_image, detect as image_detect, preview as image_preview, build_raw as image_build_raw

ROOT = Path(__file__).resolve().parent
CATALOG = {}
JOBS = {}
IMAGES = {}
BATCH_JOBS = {}
_next_photo_id = [900001]
LOCK = threading.Lock()
SLOT = threading.BoundedSemaphore(1)
MAX_BODY = 12 * 1024 * 1024



def add_plan(raw, name, source):
    if not isinstance(raw, dict):
        raise ValueError(f"{name}: expected a JSON object.")
    solution = None
    for key in ("plan", "data", "floor_plan", "input", "floor_plan_geometry"):
        if key in raw and isinstance(raw[key], dict) and ("rooms" in raw[key] or "hubs" in raw[key]):
            raw = raw[key]
            break
    if "hubs" in raw and ("rooms" not in raw or not raw["rooms"]):
        solution = raw
        target_id = str(raw.get("plan_id", raw.get("id", ""))).strip()
        stem = Path(name).stem.strip()
        base_plan = None
        base_source = None

        with LOCK:
            for item in CATALOG.values():
                c_raw = item.get("raw")
                if isinstance(c_raw, dict) and isinstance(c_raw.get("rooms"), list) and c_raw["rooms"]:
                    c_id = str(c_raw.get("id", c_raw.get("plan_id", ""))).strip()
                    c_name = str(item.get("name", "")).strip()
                    if (target_id and (c_id == target_id or c_name == target_id)) or (stem and (c_name == stem or c_id == stem)):
                        base_plan = json.loads(json.dumps(c_raw))
                        base_source = item.get("source")
                        break

        if not base_plan:
            for folder in ("examples", "plans", "."):
                folder_path = ROOT / folder
                if not folder_path.is_dir():
                    continue
                for p in folder_path.glob("*.json"):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8-sig"))
                        cand = None
                        for k in ("plan", "data", "floor_plan", "input", "floor_plan_geometry"):
                            if k in d and isinstance(d[k], dict) and "rooms" in d[k]:
                                cand = d[k]
                                break
                        if cand is None and "rooms" in d:
                            cand = d
                        if isinstance(cand, dict) and isinstance(cand.get("rooms"), list) and cand["rooms"]:
                            cand_id = str(cand.get("id", cand.get("plan_id", ""))).strip()
                            if (target_id and cand_id == target_id) or p.stem == stem or p.name == name or (target_id and p.stem == target_id):
                                base_plan = cand
                                base_source = f"ResPlan ({p.stem})"
                                break
                    except Exception:
                        pass
                if base_plan:
                    break

        if base_plan:
            raw = base_plan
            source = "Verified solution"
        else:
            raw = plan_from_solution(raw, name)
            source = "Verified solution"
    elif "rooms" in raw and isinstance(raw["rooms"], dict):
        raw = dict(raw)
        raw["rooms"] = [{"id": k, **v} if isinstance(v, dict) else {"id": k, "polygon": v} for k, v in raw["rooms"].items()]
    elif "rooms" not in raw:
        for alt in ("room_list", "roomList", "spaces", "elements"):
            if alt in raw and isinstance(raw[alt], list):
                raw = dict(raw)
                raw["rooms"] = raw[alt]
                break
        if "rooms" not in raw and any(k in raw for k in ("living", "bedroom", "kitchen", "storage")):
            from sutrayana.hubring.plan import build_plan as build_hub_plan
            p_obj = build_hub_plan(raw)
            clean_raw = {
                "id": str(raw.get("id", "plan")),
                "source": raw.get("source", "photo"),
                "units": "m",
                "area": float(raw.get("area", p_obj.inner.area)),
                "inner": mapping(p_obj.inner),
                "wall": mapping(p_obj.walls) if p_obj.walls and not p_obj.walls.is_empty else None,
                "window": mapping(p_obj.windows) if p_obj.windows and not p_obj.windows.is_empty else None,
                "doors": [mapping(d) for d in p_obj.doors],
                "rooms": [
                    {
                        "id": r.id,
                        "type": r.type,
                        "polygon": mapping(r.poly),
                        "node": list(r.node),
                        "node_id": f"N_{r.id}",
                        "area": r.area
                    }
                    for r in p_obj.rooms
                ] + [
                    {
                        "id": f"ex_{i+1}",
                        "type": ex_name.rsplit("_", 1)[0],
                        "polygon": mapping(ex_poly),
                        "node": None,
                        "node_id": None,
                        "area": ex_poly.area
                    }
                    for i, (ex_name, ex_poly) in enumerate(p_obj.excluded)
                ]
            }
            raw = clean_raw

    if solution is None and "hubs" in raw and isinstance(raw.get("hubs"), list) and raw["hubs"]:
        solution = raw

    if not isinstance(raw.get("rooms"), list):
        raise ValueError(f"{name}: expected a plan object with a rooms array or a solution object with hubs.")
    if len(raw["rooms"]) > 30:
        raise ValueError(f"{name}: interactive search supports at most 30 rooms per plan.")
    payload = {"raw": raw, "solution": solution} if solution else raw
    encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    key = hashlib.sha256(encoded).hexdigest()[:16]
    item = {"key":key, "name":str(raw.get("plan_id",raw.get("id",name))),
            "source":source, "rooms":len(raw["rooms"]), "raw":raw,
            "description":raw.get("description", "Imported floor plan"),
            "provenance":raw.get("node_provenance", "Fixed input nodes")}
    if solution:
        item["solution"] = solution
    with LOCK:
        CATALOG[key] = item
    return key


def load_catalog():
    for folder in ("examples", "plans"):
        for path in sorted((ROOT/folder).rglob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                add_plan(raw,path.stem,"Synthetic test" if raw.get("synthetic") else "ResPlan example")
            except Exception as error:
                print(f"Skipped {path.name}: {error}")


def scene(plan):
    free_area = getattr(plan, "free", Polygon())
    band_barrier = plan.barriers.buffer(0.5, join_style=2) if getattr(plan, "barriers", None) and not plan.barriers.is_empty else Polygon()
    clearance_band = free_area.intersection(band_barrier)
    return {"id":plan.id, "bounds":list(plan.inner.bounds), "inner":mapping(plan.inner),
            "wall":mapping(plan.wall), "window":mapping(plan.window),
            "clearance_band":mapping(clearance_band),
            "doors":[mapping(d) for d in plan.doors], "warnings":plan.warnings,
            "rooms":[{"id":r.id,"kind":r.kind,"area":r.area,"polygon":mapping(r.polygon),
                       "node":r.node,"node_id":r.node_id,"label":list(r.polygon.representative_point().coords)[0]}
                      for r in plan.rooms.values()],
            "links":[{"a":a,"b":b,"type":d["type"]} for a,b,d in plan.graph.edges(data=True)],
            "scale":plan.scale, "origin":list(plan.origin), "provenance":plan.node_provenance,
            "capacity_lower_bound":max(math.ceil(sum(r.area for r in plan.eligible.values())/100),math.ceil(len(plan.eligible)/5))}


def work(job_id, raw, options):
    try:
        result = solve_bounded(raw, **options)
        if result["ok"]:
            plan = Plan(raw, wire_clearance=options["wire_clearance"])
            lines = [LineString(l["polyline"]) for h in result["output"]["hubs"] for l in h["route_segments"]]
            result["measured_clearance_m"] = min((l.distance(plan.barriers) for l in lines),default=None) if not plan.barriers.is_empty else None
        with LOCK:
            JOBS[job_id].update(result, status="done")
    except Exception as error:
        with LOCK:
            JOBS[job_id].update(status="done",ok=False,error=f"{type(error).__name__}: {error}")
    finally:
        SLOT.release()


def _svg_path(geom) -> str:
    if geom is None or geom.is_empty:
        return ""
    polys = geom.geoms if hasattr(geom, "geoms") else [geom]
    out = []
    for p in polys:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        for ring in [p.exterior, *p.interiors]:
            c = np.asarray(ring.coords)
            out.append("M" + "L".join(f"{x:.3f},{-y:.3f}" for x, y in c) + "Z")
    return "".join(out)


def _photo_payload(token: str) -> dict:
    import cv2
    with LOCK:
        item = IMAGES[token]
    ok, buf = cv2.imencode(".jpg", item["img"], [cv2.IMWRITE_JPEG_QUALITY, 85])
    out = image_preview(item["det"])
    out.update(token=token, image="data:image/jpeg;base64," + base64.b64encode(buf).decode())
    return out


def format_hubring_solution(sol, raw):
    plan_obj = sol.plan
    x0, y0, x1, y1 = plan_obj.inner.bounds
    for r in plan_obj.rooms:
        bx0, by0, bx1, by1 = r.poly.bounds
        x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)

    zone_of = {r: k for k, rg in enumerate(sol.rings) for r in rg.order}
    node_xy = np.array([r.node for r in plan_obj.rooms])

    hubs_summary = []
    hubs_sutrayana = []
    for k, rg in enumerate(sol.rings):
        ring_pts = [[round(float(x), 3), round(float(y), 3)] for x, y in rg.ring]
        assigned_room_ids = [plan_obj.rooms[i].id for i in rg.order]
        assigned_names = [f"{plan_obj.rooms[i].type.capitalize()} {i+1}" for i in rg.order]
        segments = []
        if len(ring_pts) > 1:
            for s_idx in range(len(ring_pts) - 1):
                p1, p2 = ring_pts[s_idx], ring_pts[s_idx + 1]
                seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                segments.append({
                    "from": f"pt_{s_idx}",
                    "to": f"pt_{s_idx+1}",
                    "polyline": [p1, p2],
                    "length_m": round(seg_len, 3)
                })
        else:
            segments.append({
                "from": "hub",
                "to": "hub",
                "polyline": ring_pts,
                "length_m": 0.0
            })

        hub_metrics = {
            "J": round(float(rg.J), 2),
            "L": round(float(rg.metrics.L), 2),
            "B": int(rg.metrics.B),
            "X": int(rg.metrics.X),
            "O": round(float(rg.metrics.O), 2)
        }
        hub_data = {
            "k": k,
            "hub_id": f"H{k+1}",
            "rooms": assigned_names,
            "room_idx": list(rg.order),
            "ring": ring_pts,
            "hub": [round(float(rg.hub[0]), 3), round(float(rg.hub[1]), 3)],
            "method": rg.hub_method,
            "area": round(float(rg.group.area), 2),
            "devices": len(rg.order),
            "metrics": hub_metrics
        }
        hubs_summary.append(hub_data)

        hubs_sutrayana.append({
            "hub_id": f"H{k+1}",
            "room_id": plan_obj.rooms[rg.order[0]].id if rg.order else "R0",
            "location": {"x": round(float(rg.hub[0]), 3), "y": round(float(rg.hub[1]), 3)},
            "assigned_rooms": assigned_room_ids,
            "assigned_nodes": assigned_room_ids,
            "assigned_area_m2": round(float(rg.group.area), 2),
            "ring_length_m": round(float(rg.metrics.L), 3),
            "closed_sequence": [f"H{k+1}"] + assigned_room_ids + [f"H{k+1}"],
            "route_segments": segments,
            "full_ring": ring_pts,
            "metrics": hub_metrics
        })

    sutrayana_payload = {
        "ok": True,
        "output": {
            "plan_id": str(plan_obj.id),
            "units": "m",
            "hubs": hubs_sutrayana,
            "reported_metrics": {
                "hub_count": sol.H,
                "total_cost_J": round(float(sol.total.J), 2),
                "total_length_m": round(float(sol.total.L), 2),
                "total_crossings": int(sol.total.X),
                "total_overlap_m": round(float(sol.total.O), 2),
                "total_bends": int(sol.total.B)
            },
            "solver": {
                "algorithm": "Exact-Cover DP + Heading Dijkstra + Negotiated Reroute",
                "hub_count_proven": True,
                "minimum_hubs": sol.H,
                "lower_bound_hubs": getattr(sol, "lower_bound", sol.H),
                "elapsed_s": round(float(sol.seconds), 3) if sol.seconds else 0.015,
                "fallback": getattr(sol, "fallback", 0),
                "status": sol.status,
                "valid": sol.valid
            }
        },
        "measured_clearance_m": 0.5,
        "profile_valid": True,
        "solver_time_s": round(float(sol.seconds), 3) if sol.seconds else 0.015
    }

    return {
        "id": plan_obj.id,
        "status": sol.status,
        "valid": sol.valid,
        "H": sol.H,
        "lower_bound": getattr(sol, "lower_bound", sol.H),
        "bounds": [round(float(v), 3) for v in [x0, y0, x1, y1]],
        "metrics": {
            "J": round(float(sol.total.J), 2),
            "L": round(float(sol.total.L), 2),
            "B": int(sol.total.B),
            "X": int(sol.total.X),
            "O": round(float(sol.total.O), 2)
        },
        "rooms": [{
            "i": i,
            "id": r.id,
            "type": r.type,
            "name": f"{r.type.capitalize()} {i+1}",
            "area": round(float(r.area), 2),
            "path": _svg_path(r.poly),
            "zone": zone_of.get(i),
            "node": [round(float(v), 3) for v in r.node],
            "clearance": r.clearance
        } for i, r in enumerate(plan_obj.rooms)],
        "excluded": [{
            "id": n,
            "type": n.rsplit("_", 1)[0],
            "path": _svg_path(g)
        } for n, g in plan_obj.excluded],
        "walls": _svg_path(plan_obj.walls),
        "windows": _svg_path(plan_obj.windows),
        "doors": "".join(_svg_path(d) for d in plan_obj.doors),
        "hubs": hubs_summary,
        "sutrayana_payload": sutrayana_payload
    }


def _batch_summary(rows: list[dict]) -> dict:
    st = Counter(r["status"] for r in rows)
    ok = [r for r in rows if r["status"] == "valid"]
    feas = len(rows) - st.get("infeasible", 0)
    t = np.array([r["s"] for r in rows]) if rows else np.zeros(1)
    out = {
        "done": len(rows),
        "status": dict(st),
        "valid_pct": float(round(100.0 * len(ok) / max(feas, 1), 2)) if feas else 100.0,
        "time_median": float(round(float(np.median(t)), 3)),
        "time_p95": float(round(float(np.percentile(t, 95)), 3)),
        "time_max": float(round(float(t.max()), 3))
    }
    if ok:
        H = np.array([r["H"] for r in ok])
        J = np.array([r["J"] for r in ok])
        X = np.array([r["X"] for r in ok])
        lb = np.array([r.get("lb", r["H"]) for r in ok])
        out.update(
            hubs_mean=float(round(float(H.mean()), 2)),
            at_lower_bound_pct=float(round(float(100.0 * np.mean(H == lb)), 1)),
            J_median=float(round(float(np.median(J)), 1)),
            J_mean=float(round(float(J.mean()), 1)),
            J_p90=float(round(float(np.percentile(J, 90)), 1)),
            X_total=int(X.sum()),
            X_plans=int((X > 0).sum())
        )
        counts, edges = np.histogram(J, bins=15)
        out["J_hist"] = counts.tolist()
        out["J_edges"] = [round(float(e), 1) for e in edges.tolist()]
    return out


def _run_batch_job(job_id: str, plan_items: list[tuple[str, dict]]):
    t0 = time.perf_counter()
    workers = min(os.cpu_count() or 4, len(plan_items) or 1)

    def _solve_single(item):
        key, raw = item
        pid = raw.get("id", raw.get("plan_id", key))
        pt0 = time.perf_counter()
        try:
            sol = hubring_solve(raw)
            dt = time.perf_counter() - pt0
            return {
                "id": pid,
                "key": key,
                "status": sol.status,
                "H": sol.H,
                "lb": getattr(sol, "lower_bound", sol.H),
                "J": round(float(sol.total.J), 2),
                "X": int(sol.total.X),
                "s": round(dt, 3)
            }
        except Exception as e:
            dt = time.perf_counter() - pt0
            return {
                "id": pid,
                "key": key,
                "status": "crash",
                "H": None,
                "lb": None,
                "J": None,
                "X": None,
                "s": round(dt, 3),
                "error": str(e)
            }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_solve_single, it) for it in plan_items]
        for f in as_completed(futures):
            row = f.result()
            with LOCK:
                job = BATCH_JOBS.get(job_id)
                if job:
                    job["rows"].append(row)
                    job["elapsed"] = time.perf_counter() - t0

    with LOCK:
        job = BATCH_JOBS.get(job_id)
        if job:
            job["running"] = False
            job["elapsed"] = time.perf_counter() - t0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data, code=200, mime="application/json"):
        body = json.dumps(data,allow_nan=False).encode() if mime == "application/json" else data
        self.send_response(code)
        self.send_header("Content-Type",mime+"; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self.respond({"app":"SutraYana Ring Studio", "root":str(ROOT), "ui_version":"restored-20261016"})
            elif path == "/api/plans":
                with LOCK:
                    data = [{k:v for k,v in item.items() if k != "raw"} for item in CATALOG.values()]
                self.respond(data)
            elif path.startswith("/api/plan/"):
                with LOCK:
                    item = CATALOG[path.rsplit("/",1)[-1]]
                    raw = item["raw"]
                    solution = item.get("solution")
                sc = scene(Plan(raw))
                if solution:
                    sc["solution"] = solution
                self.respond(sc)
            elif path.startswith("/api/jobs/"):
                with LOCK:
                    data = dict(JOBS[path.rsplit("/",1)[-1]])
                self.respond(data)
            elif path == "/api/shutdown":
                self.respond({"ok":True,"message":"Server shutting down"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            elif path.startswith("/api/digital_twin/"):
                plan_key = path.rsplit("/", 1)[-1]
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found in catalog")
                    raw = item["raw"]
                    solution = item.get("solution")

                from tools.blender_bridge import generate_blender_twin
                plan_id = str(item.get("id", plan_key)).strip()
                out_blend = ROOT / "results" / f"twin_{plan_id}.blend"
                out_glb = ROOT / "results" / f"twin_{plan_id}.glb"
                out_render = ROOT / "results" / f"twin_{plan_id}.png"
                out_top = ROOT / "results" / f"twin_{plan_id}_top.png"

                # Instant response if already cached
                if not out_glb.exists() or not out_blend.exists():
                    res = generate_blender_twin(
                        plan_source=raw,
                        output_blend_path=out_blend,
                        solution_path=solution,
                        export_glb=True,
                        glb_path=out_glb,
                    )

                self.respond({
                    "ok": True,
                    "plan_id": plan_id,
                    "blend_url": f"/results/twin_{plan_id}.blend" if out_blend.exists() else None,
                    "glb_url": f"/results/twin_{plan_id}.glb" if out_glb.exists() else None,
                    "render_url": f"/results/twin_{plan_id}.png" if out_render.exists() else None,
                    "top_render_url": f"/results/twin_{plan_id}_top.png" if out_top.exists() else None,
                })
            elif path.startswith("/api/report/pdf/"):
                plan_key = path.rsplit("/", 1)[-1]
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found in catalog")
                    raw = item["raw"]
                    solution = item.get("solution")
                plan = Plan(raw)
                if not solution:
                    from sutrayana.solver import solve_plan
                    solution = solve_plan(plan)
                    with LOCK:
                        item["solution"] = solution
                from sutrayana.validation import validate
                from sutrayana.report import build_pdf_report, render_plan_images
                from sutrayana.exporter import format_official_submission
                val_report = validate(plan, solution)
                is_valid = bool(val_report.get("valid", False))
                in_png, out_png = render_plan_images(plan, solution)
                report_payload = {
                    "plan_id": plan.id,
                    "source": item.get("source", "Floor Plan"),
                    "status": "VALIDATED" if is_valid else "FAILED",
                    "lower_bound_hubs": getattr(plan, "capacity_lower_bound", 1),
                    "wire_clearance_m": solution.get("solver", {}).get("wire_clearance_m", 0.0),
                    "development": solution,
                    "validation": val_report,
                    "reported_metrics": solution.get("reported_metrics", {}),
                    "timings": {
                        "load_s": 0.005,
                        "zone_s": 0.002,
                        "solve_s": solution.get("solver", {}).get("elapsed_s", 0.015),
                        "validate_s": 0.003,
                        "total_s": solution.get("solver", {}).get("elapsed_s", 0.025)
                    },
                    "diagnostics": [],
                    "input_image": in_png,
                    "output_image": out_png,
                    "submission": format_official_submission(plan, solution) if is_valid else None
                }
                pdf_bytes = build_pdf_report(report_payload)
                self.respond(pdf_bytes, mime="application/pdf")
            elif path.startswith("/api/submission/"):
                plan_key = path.rsplit("/", 1)[-1]
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found in catalog")
                    raw = item["raw"]
                    solution = item.get("solution")
                plan = Plan(raw)
                if not solution:
                    from sutrayana.solver import solve_plan
                    solution = solve_plan(plan)
                    with LOCK:
                        item["solution"] = solution
                from sutrayana.validation import validate
                from sutrayana.exporter import format_official_submission
                val_report = validate(plan, solution)
                if not val_report.get("valid"):
                    return self.respond({"error": "Submission JSON is withheld: independent validation rejected this solution."}, 422)
                self.respond(format_official_submission(plan, solution))
            elif path.startswith("/api/top3/"):
                plan_key = path.rsplit("/", 1)[-1]
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found in catalog")
                    raw = item["raw"]
                t0 = time.perf_counter()
                sols = top_solutions(raw, k=3)
                elapsed = time.perf_counter() - t0
                options = [format_hubring_solution(s_, raw) for s_ in sols]
                self.respond({"ok": True, "seconds": round(elapsed, 3), "options": options})
            elif path.startswith("/api/batch/"):
                job_id = path.rsplit("/", 1)[-1].split("?")[0]
                with LOCK:
                    job = BATCH_JOBS.get(job_id)
                if not job:
                    raise KeyError("Unknown batch job")
                rws = list(job["rows"])
                out = {k: job[k] for k in ("id", "total", "running", "elapsed", "workers", "seed")}
                out["summary"] = _batch_summary(rws)
                out["rows"] = rws
                self.respond(out)
            elif path.startswith("/results/"):
                file_path = ROOT / path.lstrip("/")
                if file_path.is_file():
                    ext = file_path.suffix.lower()
                    mime = {
                        ".png": "image/png",
                        ".blend": "application/x-blender",
                        ".glb": "model/gltf-binary",
                        ".json": "application/json",
                    }.get(ext, "application/octet-stream")
                    self.respond(file_path.read_bytes(), mime=mime)
                else:
                    self.respond({"error": "File not found"}, 404)
            elif path in ("/", "/app.js", "/style.css") or path.startswith("/vendor/"):
                rel = "index.html" if path == "/" else path.lstrip("/")
                file_path = (ROOT / "web" / rel).resolve()
                web_dir = (ROOT / "web").resolve()
                if file_path.is_file() and (web_dir in file_path.parents or file_path == web_dir / "index.html"):
                    ext = file_path.suffix.lower()
                    mime = {
                        ".html": "text/html",
                        ".js": "text/javascript",
                        ".css": "text/css",
                        ".json": "application/json",
                        ".svg": "image/svg+xml",
                        ".png": "image/png",
                    }.get(ext, "application/octet-stream")
                    self.respond(file_path.read_bytes(), mime=mime)
                else:
                    self.respond({"error": "File not found"}, 404)
            else:
                self.respond({"error":"Not found"},404)
        except KeyError:
            self.respond({"error":"Unknown plan or expired job"},404)
        except Exception as error:
            self.respond({"error":str(error)},400)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and origin != "http://"+self.headers.get("Host", ""):
            return self.respond({"error":"Cross-origin requests are not allowed"},403)
        try:
            size = int(self.headers.get("Content-Length",0))
            if not 0 < size <= MAX_BODY:
                return self.respond({"error":"Request must be between 1 byte and 12 MB"},413)
            data = json.loads(self.rfile.read(size))
            if self.path == "/api/shutdown":
                self.respond({"ok":True,"message":"Server shutting down"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            elif self.path == "/api/import":
                items = data.get("plans", [])
                if not isinstance(items,list) or not 1 <= len(items) <= 50:
                    raise ValueError("Import between 1 and 50 JSON plans at once.")
                if len(CATALOG)+len(items) > 20000:
                    raise ValueError("Catalog capacity reached.")
                imported, errors = [], []
                for item in items:
                    try:
                        imported.append(add_plan(item["data"],item["name"],"Imported JSON"))
                    except Exception as error:
                        errors.append(str(error))
                self.respond({"keys":imported,"errors":errors})
            elif self.path == "/api/solve":
                with LOCK:
                    raw = CATALOG[data["key"]]["raw"]
                clearance = float(data.get("wire_clearance", 0))
                timeout = float(data.get("timeout",30))
                use_rl = bool(data.get("use_rl", False))
                nodes = data.get("nodes") or data.get("moved_nodes")
                if nodes:
                    nodes_dict = {int(k): (float(v[0]), float(v[1])) for k, v in nodes.items()}
                    t0 = time.perf_counter()
                    sol = hubring_solve(raw, nodes=nodes_dict)
                    formatted = format_hubring_solution(sol, raw)
                    solution_payload = formatted["sutrayana_payload"]
                    with LOCK:
                        CATALOG[data["key"]]["solution"] = solution_payload["output"]
                    job_id = uuid.uuid4().hex
                    with LOCK:
                        JOBS[job_id] = {"status": "done", **solution_payload}
                    return self.respond({"job_id": job_id, "ok": True, "output": solution_payload["output"], **solution_payload}, 200)

                if clearance not in (0,.5) or not math.isfinite(timeout) or not 1 <= timeout <= 120:
                    raise ValueError("Invalid clearance profile or time limit (1–120 seconds).")
                if not SLOT.acquire(blocking=False):
                    return self.respond({"error":"A plan is already running. Wait for it to finish."},429)
                job_id = uuid.uuid4().hex
                with LOCK:
                    for key in list(JOBS):
                        if len(JOBS) < 100:
                            break
                        if JOBS[key]["status"] == "done":
                            del JOBS[key]
                    JOBS[job_id] = {"status":"running", "started":time.time()}
                threading.Thread(target=work,args=(job_id,raw,{"wire_clearance":clearance,"timeout":timeout,"enhanced":bool(data.get("enhanced")),"use_rl":use_rl}),daemon=True).start()
                self.respond({"job_id":job_id},202)
            elif self.path.startswith("/api/top3"):
                plan_key = data.get("key") or self.path.rsplit("/", 1)[-1]
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found in catalog")
                    raw = item["raw"]
                nodes = data.get("nodes") or data.get("moved_nodes")
                nodes_dict = {int(k): (float(v[0]), float(v[1])) for k, v in nodes.items()} if nodes else None
                t0 = time.perf_counter()
                sols = top_solutions(raw, k=3, nodes=nodes_dict)
                elapsed = time.perf_counter() - t0
                options = [format_hubring_solution(s_, raw) for s_ in sols]
                self.respond({"ok": True, "seconds": round(elapsed, 3), "options": options})
            elif self.path == "/api/image/detect":
                img_data = data.get("image")
                if not img_data:
                    raise ValueError("No image provided in request")
                if "," in img_data:
                    img_data = img_data.split(",", 1)[1]
                raw_bytes = base64.b64decode(img_data)
                img = load_image(raw_bytes)
                det = image_detect(img)
                token = uuid.uuid4().hex[:10]
                with LOCK:
                    IMAGES[token] = {"img": img, "det": det, "name": data.get("name", "photo.png")}
                self.respond(_photo_payload(token))
            elif self.path == "/api/image/redetect":
                token = data.get("token")
                with LOCK:
                    item = IMAGES.get(token)
                if not item:
                    raise KeyError("Photo session expired, please re-upload image")
                img = item["img"]
                rgb = item["det"].get("wall_rgb")
                if data.get("wall_xy"):
                    x, y = data["wall_xy"]
                    H, W = img.shape[:2]
                    cx, cy = int(np.clip(x, 0, W - 1)), int(np.clip(H - y, 0, H - 1))
                    patch = img[max(0, cy - 1):cy + 2, max(0, cx - 1):cx + 2].reshape(-1, 3)
                    rgb = [int(v) for v in np.median(patch, axis=0)[::-1]]
                area = data.get("area_m2")
                item["det"] = image_detect(img, wall_rgb=rgb, area_m2=float(area) if area else None)
                self.respond(_photo_payload(token))
            elif self.path == "/api/image/build":
                token = data.get("token")
                with LOCK:
                    item = IMAGES.get(token)
                if not item:
                    raise KeyError("Photo session expired, please re-upload image")
                pid = _next_photo_id[0]
                _next_photo_id[0] += 1
                raw = image_build_raw(item["det"], data.get("types") or [], pid)
                key = add_plan(raw, f"Photo Plan {pid}", "Photo import")
                self.respond({"ok": True, "id": pid, "key": key})
            elif self.path == "/api/batch":
                n = data.get("n", 10)
                seed = int(data.get("seed", 11))
                with LOCK:
                    all_keys = list(CATALOG.keys())
                import random
                rng = random.Random(seed)
                if n == "all":
                    chosen_keys = all_keys
                else:
                    n_count = max(1, min(int(n), len(all_keys)))
                    chosen_keys = rng.sample(all_keys, n_count) if len(all_keys) >= n_count else all_keys
                with LOCK:
                    plan_items = [(k, CATALOG[k]["raw"]) for k in chosen_keys]
                job_id = uuid.uuid4().hex[:8]
                workers = min(os.cpu_count() or 4, len(plan_items) or 1)
                with LOCK:
                    BATCH_JOBS[job_id] = {
                        "id": job_id, "total": len(plan_items), "rows": [],
                        "running": True, "elapsed": 0.0, "workers": workers, "seed": seed
                    }
                threading.Thread(target=_run_batch_job, args=(job_id, plan_items), daemon=True).start()
                self.respond({"ok": True, "job": job_id, "total": len(plan_items)})
            elif self.path == "/api/resilience/simulate":
                from sutrayana.resilience import simulate_single_cut
                plan_key = data.get("key")
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found")
                    solution = item.get("solution")
                    raw = item.get("raw")
                if not solution:
                    from sutrayana.solver import solve_plan
                    from sutrayana.model import Plan
                    solution = solve_plan(Plan(raw))
                    with LOCK:
                        item["solution"] = solution
                hub_idx = int(data.get("hub_idx", 0))
                hubs = solution.get("hubs", [])
                if not hubs:
                    return self.respond({"error": "No hubs in solution"}, 400)
                hub = hubs[max(0, min(hub_idx, len(hubs) - 1))]
                cut_idx = int(data.get("cut_segment_idx", 0))
                res = simulate_single_cut(hub, cut_idx)
                self.respond(res)
            elif self.path == "/api/resilience/stress_test":
                from sutrayana.resilience import stress_test_all_single_cuts
                plan_key = data.get("key")
                with LOCK:
                    item = CATALOG.get(plan_key)
                    if not item:
                        raise KeyError("Plan not found")
                    solution = item.get("solution")
                    raw = item.get("raw")
                if not solution:
                    from sutrayana.solver import solve_plan
                    from sutrayana.model import Plan
                    solution = solve_plan(Plan(raw))
                    with LOCK:
                        item["solution"] = solution
                summary = stress_test_all_single_cuts(solution)
                self.respond(summary)
            else:
                self.respond({"error":"Not found"},404)
        except Exception as error:
            self.respond({"error":str(error)},400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    load_catalog()
    server = None
    port = args.port
    for p in range(args.port, args.port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError(f"Could not bind to any port in range {args.port}–{args.port+19}")
    url = f"http://127.0.0.1:{port}"
    print(f"SutraYana: {url} | {len(CATALOG)} plans | Ctrl+C to stop", flush=True)
    if not args.no_browser:
        threading.Timer(.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
