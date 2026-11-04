"""out/outfalls.json for the Worker live layer (worker/README.md) and the map's outfall points.

The export writes it (`make export`: pipeline/export/outfalls.py, from the same registry rows as the operator and
water pages; docs/national-outfalls.md has the row contract). This script rewrites it from the files on disk (the
registry, out/rain.json, out/monthly-outfalls.json), as scripts/upload-current.sh has always run it before the
upload. Run from the project root after `make export`: python3 -I scripts/export-outfalls.py
"""
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "pipeline"))

from export import outfalls  # noqa: E402

if __name__ == "__main__":
    outfalls.main()
