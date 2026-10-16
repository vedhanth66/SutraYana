"""Local plan workbench. No external services or web framework required."""
import argparse
import hashlib
import json
import math
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from shapely.geometry import mapping, LineString, Polygon
from sutrayana.model import Plan, plan_from_solution
from sutrayana.runtime import solve_bounded

ROOT = Path(__file__).resolve().parent
CATALOG = {}
JOBS = {}
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
    wire_free = getattr(plan, "wire_free", None)
    if wire_free is None:
        wire_free = getattr(plan, "_wire_free", None)
    if wire_free is None:
        wire_free = getattr(plan, "free", Polygon())
    free_area = getattr(plan, "free", Polygon())
    return {"id":plan.id, "bounds":list(plan.inner.bounds), "inner":mapping(plan.inner),
            "wall":mapping(plan.wall), "window":mapping(plan.window),
            "clearance_band":mapping(free_area.difference(wire_free)),
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
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
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
            elif path in ("/", "/app.js", "/style.css"):
                name = {"/":"index.html", "/app.js":"app.js", "/style.css":"style.css"}[path]
                mime = {"index.html":"text/html", "app.js":"text/javascript", "style.css":"text/css"}[name]
                self.respond((ROOT/"web"/name).read_bytes(),mime=mime)
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
                threading.Thread(target=work,args=(job_id,raw,{"wire_clearance":clearance,"timeout":timeout,"enhanced":bool(data.get("enhanced"))}),daemon=True).start()
                self.respond({"job_id":job_id},202)
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
