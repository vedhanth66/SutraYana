"""Open the restored app, reusing its existing local server."""
from pathlib import Path
import json
import runpy
import sys
import urllib.request
import webbrowser
ROOT=Path(__file__).resolve().parent
if __name__ == "__main__":
    for port in range(8788,8808):
        url=f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(url+"/api/health",timeout=.2) as response:
                data=json.load(response)
            if data.get("root")==str(ROOT) and data.get("ui_version")=="restored-20261016":
                webbrowser.open(url+"/?ui=ring-studio-restored")
                raise SystemExit(0)
        except (OSError,ValueError):
            continue
    sys.argv = [str(ROOT/"webapp.py"), "--port", "8788"]
    runpy.run_path(str(ROOT/"webapp.py"),run_name="__main__")
