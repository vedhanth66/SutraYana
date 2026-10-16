"""Validate every recorded failure plus a deterministic holdout and slow cases."""
import argparse
import json
import pickle
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from batch_eval_pipeline import process_single_plan_task


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pkl", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", default="evidence/large_validation.json")
    args = parser.parse_args()
    previous = json.loads(Path(args.previous).read_text())["detailed_results"]
    failures = {r["plan_idx"] for r in previous if not r.get("valid")}
    slow = {r["plan_idx"] for r in sorted(previous,key=lambda r:r.get("time_sec",0),reverse=True)[:50]}
    with open(args.pkl,"rb") as f:
        data = pickle.load(f)
    indices = sorted(failures | slow | set(random.Random(20261016).sample(range(len(data)),min(args.count,len(data)))))
    rows = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(process_single_plan_task,(data[i],i,.08)) for i in indices]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows)%100==0:
                print(len(rows),"/",len(indices),"elapsed",round(time.perf_counter()-started,1),flush=True)
    recovered = [r["plan_idx"] for r in rows if r["plan_idx"] in failures and r.get("valid")]
    errors = [r for r in rows if not r.get("valid") and not r.get("skipped")]
    summary = {"total":len(rows),"valid":sum(bool(r.get("valid")) for r in rows),
               "ineligible":sum(bool(r.get("skipped")) for r in rows),"solver_failures":len(errors),
               "historical_failures_tested":len(failures),"recovered":len(recovered),
               "wall_seconds":time.perf_counter()-started}
    Path(args.output).write_text(json.dumps({"summary":summary,"recovered_indices":recovered,"errors":errors,"results":rows},indent=2))
    print(summary,flush=True)
    for error in errors:
        print(error,flush=True)


if __name__ == "__main__":
    main()
