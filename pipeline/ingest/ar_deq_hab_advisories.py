"""Arkansas DEQ harmful algal bloom advisories -> data/build/events/ar-deq-hab-advisories.json

Source
  https://adeq.state.ar.us/water/planning/hab/advisories.json (registry: ar-deq-hab-advisories), the file the Harmful
  Algal Blooms page's current-advisories table and its archive page draw: {updated, advisories: [{waterbody, county,
  area, date, lifted}]}. Record rules: the fetch block in data/sources/ar-deq-hab-advisories.yaml and
  ingest/ar_transforms.py ar_hab_record, through the generic field map, history and redaction (ingest/generic/
  runner.build); this module only fetches, so that a coordinate pair DEQ writes inside a waterbody name ("Stream by ...
  (coordinates 35.123456, -93.654321)") is rounded to 0.001 degree (ar_transforms.round_text_coords) before anything
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
from common import error_text
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
        r = round_row(r)
        out.append(runner.F.safe_row(r, block)[0])
    return out


def round_row(r: dict) -> dict:
    """The row with every point in its words cut to 0.001 degree: DEQ's "(coordinates ...)" in the waterbody name,
    and any decimal, degree-minute-second or degree-decimal-minute point in the water, county or area text
    (verification 3 P1)."""
    out = {**r, **{f: T.scrub_coord_text(r[f]) for f in ("waterbody", "county", "area") if isinstance(r.get(f), str)}}
    out["waterbody"] = T.round_text_coords(out.get("waterbody"))
    return out


def fetch() -> dict:
    """DEQ's file; an HTTP error is never read as advisories, whatever its body (re-review P2-3)."""
    r = requests.get(URL, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()


def check_doc(doc) -> None:
    """ValueError unless the document is DEQ's {advisories: [rows]} or a dww-safe-rows/1 file of row objects."""
    if not isinstance(doc, dict):
        raise ValueError("the advisories file is not a JSON object")
    rows = doc.get("rows") if doc.get("format") == runner.SAFE_ROWS_FORMAT else doc.get("advisories")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("the advisories file has no list of advisory rows")


DATE_FORMAT = "%B %d, %Y"


def check_rows(rows: list[dict]) -> None:
    """ValueError unless every row carries DEQ's five fields as text, a water and a posting day that reads as a
    date, and a lift day that is blank, DEQ's "N/A" or a date: a row emptied or with its fields renamed is a failed
    read, never an advisory that left the file (verification 2 P1-1)."""
    from datetime import datetime
    for i, r in enumerate(rows):
        missing = [f for f in ("waterbody", "county", "area", "date", "lifted") if not isinstance(r.get(f), str)]
        if missing:
            raise ValueError(f"advisory row {i + 1} lacks {', '.join(missing)}")
        if not r["waterbody"].strip():
            raise ValueError(f"advisory row {i + 1} names no water")
        for f in ("date", "lifted"):
            v = r[f].strip()
            if f == "lifted" and (not v or T.NOT_GIVEN.match(v)):
                continue
            try:
                datetime.strptime(v, DATE_FORMAT)
            except ValueError:
                raise ValueError(f"advisory row {i + 1}: {f} does not read as a date") from None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved advisories.json (or dww-safe-rows/1 file) to read instead of fetching")
    ap.add_argument("--out", help="write the events file here")
    a = ap.parse_args(argv)
    row, block = runner.load_source(SOURCE_ID)
    path = Path(a.out) if a.out else EVENTS_DIR / f"{SOURCE_ID}.json"
    # carried state is cut the same way before it is read or written again, failed runs included (verification 3 P1)
    prev = [T.scrub_coords_deep(r) for r in (read_json(path, {}) or {}).get("records") or [] if isinstance(r, dict)]
    fetched_at = now_iso()
    try:
        doc = json.loads(Path(a.file).read_text()) if a.file else fetch()
        check_doc(doc)
        rows = doc["rows"] if doc.get("format") == runner.SAFE_ROWS_FORMAT else rows_of(doc, block)
        rows = [round_row(r) for r in rows]
        if not rows:
            raise ValueError("no advisories in the file")
        check_rows(rows)
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, OSError) as e:
        write_events(SOURCE_ID, prev, ok=False, error=f"{error_text(e)}", path=path, partial=True)
        print(f"{SOURCE_ID}: FAILED {error_text(e)}", file=sys.stderr)
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
        records = [T.scrub_coords_deep(r) for r in records]
    except Exception as e:  # noqa: BLE001 - a run that cannot finish keeps the previous records
        write_events(SOURCE_ID, prev, ok=False, error=f"{error_text(e)}", path=path, partial=True)
        print(f"{SOURCE_ID}: FAILED {error_text(e)}", file=sys.stderr)
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
