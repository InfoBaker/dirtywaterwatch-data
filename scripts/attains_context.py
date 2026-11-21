#!/usr/bin/env python3
"""The state Clean Water Act assessments beside a water's status (EPA ATTAINS): pipeline/build/attains.py does the
work; this is its command line, runnable with the isolated interpreter from the repository root:

    pipeline/.venv/bin/python -I scripts/attains_context.py --out data/build/attains/attains-waters.json
    pipeline/.venv/bin/python -I scripts/attains_context.py --states TN MA      # a few states
    pipeline/.venv/bin/python -I scripts/attains_context.py --offline           # the cached files only

Downloads and geometry are cached under data/raw/attains/ (git-ignored). No key is needed; see docs/attains.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from build import attains  # noqa: E402

if __name__ == "__main__":
    sys.exit(attains.main())
