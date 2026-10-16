"""Process isolation gives Windows and Unix the same hard per-plan deadline."""
import multiprocessing as mp
import time


def _worker(connection, source, options):
    try:
        from .solver import solve_plan
        from .model import Plan
        import inspect
        plan = source if isinstance(source, Plan) else Plan(source, open_min=options.get("open_min", .5), wire_clearance=options.get("wire_clearance", .5), translate_origin=options.get("translate_origin", False))
        accepted = inspect.signature(solve_plan).parameters
        output = solve_plan(plan, **{k:v for k,v in options.items() if k in accepted})
        output.setdefault("warnings", list(plan.warnings))
        if options.get("wide") and "wide" not in accepted:
            output["warnings"].append({"rule":"search", "message":"This backend does not support expanded hub search; the base search was retained."})
        output.setdefault("solver", {})["wire_clearance_m"] = plan.wire_clearance
        connection.send({"ok": True, "output": output})
    except Exception as error:
        connection.send({"ok": False, "error": f"{type(error).__name__}: {error}"})
    finally:
        connection.close()


def solve_bounded(source, *, timeout=30, enhanced=False, **options):
    if not 0 < timeout <= 300:
        raise ValueError("Time limit must be between 0 and 300 seconds.")
    started = time.monotonic()
    context = mp.get_context("spawn")

    def run(opts, budget):
        reader, writer = context.Pipe(duplex=False)
        process = context.Process(target=_worker, args=(writer, source, opts), daemon=True)
        process.start()
        writer.close()
        try:
            if not reader.poll(max(0, budget)):
                return {"ok": False, "error": f"Time limit reached ({timeout:g} s). No unvalidated output was emitted."}
            return reader.recv()
        except EOFError:
            return {"ok": False, "error": f"Solver process exited unexpectedly (exit code {process.exitcode})."}
        finally:
            reader.close()
            if process.is_alive():
                process.terminate()
            process.join(2)
            if process.is_alive():
                process.kill()
                process.join()

    result = run(options, timeout)
    if enhanced and result["ok"]:
        remaining = timeout - (time.monotonic() - started)
        if remaining > .5:
            wider = run(dict(options, wide=True), remaining)
            def rank(item):
                output = item["output"]
                return (len(output["hubs"]), output["reported_metrics"]["total_cost_J"], output["solver"]["area_gap_m2"])
            if wider["ok"] and rank(wider) < rank(result):
                result = wider
            elif not wider["ok"]:
                result["output"]["warnings"].append({"rule":"search_budget", "message":"Kept the validated base result. Expanded search: " + wider["error"]})
    result["elapsed_s"] = round(time.monotonic() - started, 3)
    return result
