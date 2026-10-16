import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import webapp
from tools.blender_bridge import generate_blender_twin

def main():
    webapp.load_catalog()
    print(f"Checking {len(webapp.CATALOG)} catalog plans...")

    for key, item in webapp.CATALOG.items():
        out_glb = Path("results") / f"twin_{key}.glb"
        out_blend = Path("results") / f"twin_{key}.blend"
        if out_glb.exists() and out_blend.exists():
            print(f"[OK] Already cached: {key} ({item['name']})")
            continue
        print(f"Building twin for {key} ({item['name']})...")
        try:
            generate_blender_twin(
                plan_source=item["raw"],
                solution_path=item.get("solution"),
                output_blend_path=out_blend,
                export_glb=True,
                glb_path=out_glb,
                auto_solve=True
            )
            print(f"[DONE] Built {key} ({item['name']})")
        except Exception as e:
            print(f"[FAIL] Failed {key} ({item['name']}): {e}")

    print("Catalog cache check complete!")

if __name__ == "__main__":
    main()
