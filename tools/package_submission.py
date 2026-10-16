"""Build a clean source/demo bundle without datasets, caches or scratch files."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / "results" / "SutraYana-submission.zip"
    files = [ROOT/name for name in ["README.md","THIRD_PARTY_NOTICES.md","requirements.txt","solve.py",
             "batch_eval_pipeline.py","check.py","export_resplan_to_json.py","phase1_pipeline.py",
             "phase2_partition.py","phase3_sequencing.py","phase4_routing.py","sample_plan.json","output_plan.json","floor_plan_phase4.png"]]
    for directory,pattern in [("sutrayana","*.py"),("tests","*.py"),("tools","*.py"),("audit_tools","*.py"),("examples","*")]:
        files.extend(p for p in (ROOT/directory).glob(pattern) if p.is_file())
    files.extend((ROOT/"tests/fixtures").glob("*.json"))
    files.extend(ROOT/"results"/name for name in ["review.html","final_120.json","independent_audit.json","verification.json"])
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        raise SystemExit(f"Missing deliverables: {missing}")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(destination,"w",ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path,path.relative_to(ROOT))
    with ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise SystemExit("Archive verification failed")
        print(f"Created {destination} ({len(archive.namelist())} files; {destination.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
