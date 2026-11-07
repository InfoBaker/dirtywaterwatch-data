"""Yearly archive files of TCEQ's Sanitary Sewer Overflows reports before 2023 (review 2026-11-07 P2-6): the hourly
build carries the reports that began on or after 2023-01-01 (data/sources/tx-tceq-sso-opendata.yaml, where and
filter); the 2010-2022 reports, about 40,000, are built here with the same field map and hook and written once per
table version to data/build/archive/tx-tceq-sso-opendata/<year>.json, for the export's yearly downloads and the charts'
long history to read. Not wired into the export yet: the export and the charts read only the events file.

Usage (from the repository root):
    pipeline/.venv/bin/python -I scripts/tx_tceq_archive.py [--file saved-read.json --meta saved-meta.json] [--force]
With no --file it reads the table's rows that began before 2023 (Socrata, the safe fields only), and does nothing when
the table's rowsUpdatedAt is the one the archive was last written from (manifest.json), unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import now_iso  # noqa: E402
from ingest.generic import runner as R  # noqa: E402
from ingest.generic import socrata  # noqa: E402
from ingest.generic.base import session  # noqa: E402

SOURCE = "tx-tceq-sso-opendata"
OUT = ROOT / "data" / "build" / "archive" / SOURCE
CUT = "2023-01-01"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--meta")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    _, block = R.load_source(SOURCE)
    old = {k: v for k, v in block.items() if k not in ("where", "filter", "if_changed")}
    manifest = json.loads((OUT / "manifest.json").read_text()) if (OUT / "manifest.json").exists() else {}
    if a.file:
        rows = socrata.parse(old, Path(a.file).read_bytes())
        meta = json.loads(Path(a.meta).read_text()) if a.meta else None
    else:
        sess = session(old)
        version = socrata.current_version(old, sess)
        if version and version == manifest.get("table_version") and not a.force:
            print(f"archive is current (table version {version})")
            return 0
        pages, _ = socrata.read_pages({**old, "where": f"start_date < '{CUT}T00:00:00'"}, sess, socrata.urls(old))
        rows = [r for pg in pages for r in pg]
        meta = {"rowsUpdatedAt": version}
    rows = [r for r in rows if str(r.get("start_date") or "")[:10] < CUT]
    recs, stats = R.build(SOURCE, old, rows, now_iso(), (), meta)
    by_year = defaultdict(list)
    for r in recs:
        by_year[(r.get("started_at") or "unknown")[:4]].append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    for y, rs in sorted(by_year.items()):
        (OUT / f"{y}.json").write_text(json.dumps({"source_id": SOURCE, "year": y, "count": len(rs), "records": rs},
                                                  ensure_ascii=False) + "\n")
    man = {"source_id": SOURCE, "before": CUT, "table_version": socrata.table_version(old, meta),
           "written_at": now_iso(), "years": {y: len(rs) for y, rs in sorted(by_year.items())}}
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    print(json.dumps(man["years"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
