#!/usr/bin/env python3
"""HackHive / SutraYana CLI Entrypoint.

Usage:
  python hackhive.py solve <input.json> [<output.json>] [options]
  python hackhive.py check <input.json> <output.json> [options]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sutrayana.cli import main

if __name__ == "__main__":
    sys.exit(main())
