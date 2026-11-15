"""Arkansas DEQ harmful algal bloom advisories -> data/build/events/ar-deq-hab-advisories.json

Source
  https://adeq.state.ar.us/water/planning/hab/advisories.json (registry: ar-deq-hab-advisories), the file the Harmful
  Algal Blooms page's current-advisories table and its archive page draw: {updated, advisories: [{waterbody, county,
  area, date, lifted}]}. Record rules: the fetch block in data/sources/ar-deq-hab-advisories.yaml and
  ingest/ar_transforms.py ar_hab_record, through the generic field map, history and redaction (ingest/generic/
  runner.build); this module only fetches, so that a coordinate pair DEQ writes inside a waterbody name ("Stream by ...
  (coordinates 35.507114, -94.216947)") is rounded to 0.001 degree (ar_transforms.round_text_coords) before anything
  is saved, mapped or used in a record key (review 2026-11-14 P1-6). data/raw keeps only those rounded safe rows
  (dww-safe-rows/1), and only when they change. A failed read keeps the previous records (ok false).

Run from pipeline/:  python -m ingest.ar_deq_hab_advisories [--file saved.json] [--out path]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests

from common import BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, now_iso, path_notes_to_meta, read_json, save_raw, write_events
from common import write_json
from ingest import ar_transforms as T
from ingest.generic import runner

SOURCE_ID = "ar-deq-hab-advisories"
URL = "https://adeq.state.ar.us/water/planning/hab/advisories.json"
STATE_PATH = BUILD_DIR / "generic" / f"{SOURCE_ID}-fetch.json"


def rows_of(doc: dict, block: dict) -> list[dict]:
    """The file's rows with their coordinates rounded, cut to the safe fields and scrubbed."""
    from ingest.generic.csv_json import rows_of_json
    rows = rows_of_json(doc, block)
    out = []
    for r in rows:
        r = {**r, "waterbody": T.round_text_coords(r.get("waterbody"))}
        out.append(runner.F.safe_row(r, block)[0])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved advisories.json (or dww-safe-rows/1 file) to read instead of fetching")
    ap.add_argument("--out", help="write the events file here")
    a = ap.parse_args(argv)
    row, block = runner.load_source(SOURCE_ID)
    path = Path(a.out) if a.out else EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    fetched_at = now_iso()
    try:
        doc = json.loads(Path(a.file).read_text()) if a.file else \
            requests.get(URL, headers=HEADERS, timeout=120).json()
        rows = doc["rows"] if doc.get("format") == runner.SAFE_ROWS_FORMAT else rows_of(doc, block)
        rows = [{**r, "waterbody": T.round_text_coords(r.get("waterbody"))} for r in rows]
        if not rows:
            raise ValueError("no advisories in the file")
    except (requests.RequestException, ValueError, KeyError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=path)
        print(f"{SOURCE_ID}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    raw_path = None
    if not a.file:
        payload = json.dumps({"format": runner.SAFE_ROWS_FORMAT, "rows": rows,
                              "meta": {"updated": doc.get("updated")}}, ensure_ascii=False, sort_keys=True).encode()
        state = read_json(STATE_PATH, {}) or {}
        sha = hashlib.sha256(payload).hexdigest()
        raw_path = state.get("raw_path")
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, payload, "json").relative_to(ROOT))
            write_json(STATE_PATH, {"sha256": sha, "raw_path": raw_path, "saved_at": fetched_at})
    try:
        records, stats = runner.build(SOURCE_ID, block, rows, fetched_at, prev, None)
    except Exception as e:  # noqa: BLE001 - a run that cannot finish keeps the previous records
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=path)
        print(f"{SOURCE_ID}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    meta = {**stats, **runner.public_meta(block.get("meta") or {}), "platform": "json", "raw_path": raw_path,
            "generic": True, "registry_ids": row.get("registry_ids") or [], "timezone": block.get("time_zone"),
            "file_updated": doc.get("updated") if isinstance(doc, dict) else None}
    path_notes_to_meta(records, meta)
    out = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta, path=path)
    print(f"{SOURCE_ID}: {len(rows)} rows -> {len(records)} records; status {stats.get('by_status')} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
