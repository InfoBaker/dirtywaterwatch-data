"""Georgia DNR Coastal Resources Division "Healthy Beaches" advisory map -> data/build/events/ga-dnr-beaches.json

Source
  The page https://coastalgadnr.org/HealthyBeaches embeds an ArcGIS Experience (item db7233b5d80b4fb7a6768d090257b704)
  whose web map "Beach Advisory Map" (item 029c5375c5f64691a04d32c1e01658c3) draws two layers from one GeoJSON file,
  https://webapp.gadnr.org/beach/working/beach.geojson (plain GET, no key, Last-Modified given; 37 beach polygons on
  2026-11-04): beachId (EPA beach id), beachName, areaCode, stationCode, beachDescription, status (Green, Yellow,
  Gray), dateCollected (MM/DD/YYYY, the latest sample), entero (enterococci of that sample), permanentAdvisory
  (YES / NO) and tierRankingCode. The map's own legend says what the fields mean:
    - layer "Temporary Beach Advisories" = permanentAdvisory NO and tier not 3 or 4: status Green is "Bacteria Levels
      are Acceptable"; any other status is "Temporary Advisory: Bacteria Levels are Elevated".
    - layer "Permanent Advisories" = permanentAdvisory YES and tier not 3.
    - Gray with no sample (tiers 3 and 4, the remote islands) is a beach that is not sampled: no record.
  No licence is stated. The program samples weekly in season and less often in winter (research/ga/report.md 2.5).

Snapshot to history (the file has no start or end of an advisory)
  - A temporary advisory is one record from the first poll that shows the beach not Green until the first poll that
    shows it Green again: source_record_id <beachId>-<dateCollected at first sight>, started_at = that sample date
    (time_precision day; raw.start_basis: the advisory follows the result of the sample taken that day).
    Later samples while it stands are kept in raw.samples. When the beach reads Green, status advisory_lifted and
    ended_at = the poll that first saw it (time_precision of the end is the poll: raw.ended_at_precision "poll",
    raw.lift_observed_between = [last poll showing the advisory, first poll not showing it]). A beach missing from
    the file leaves its advisory active (raw.missing_since); disappearance is not lifting.
  - A permanent advisory is one record per beach, <beachId>-permanent, status advisory_active while the file says YES
    (started_at = the first poll that saw it, time_precision poll, raw.start_basis: the start is not published);
    when the file says NO it is lifted the same way.
  event_type beach_advisory; waterbody_text the beach name; the point is the polygon's vertex mean (coord_source
  source). advice_text quotes the map's legend; advice_window null (the program publishes none).

Run from pipeline/:  python -m ingest.ga_dnr_beaches [--file beach.geojson]
Cadence: daily is enough (the file changed once on 2026-11-03).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from common import EVENTS_DIR, HEADERS, RAW_DIR, event, now_iso, read_json, write_events

SOURCE_ID = "ga-dnr-beaches"
URL = "https://webapp.gadnr.org/beach/working/beach.geojson"
PAGE_URL = "https://coastalgadnr.org/HealthyBeaches"
AUTHORITY = "Georgia DNR Coastal Resources Division, Healthy Beaches (beach advisory map)"
TEMP_TEXT = "Temporary Advisory: Bacteria Levels are Elevated"
PERM_TEXT = "Permanent Advisory"


def mdy(s: str | None) -> str | None:
    try:
        return datetime.strptime((s or "").strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def centre(geom: dict | None) -> tuple[float | None, float | None]:
    pts = []

    def walk(c):
        if isinstance(c, (list, tuple)) and len(c) >= 2 and all(isinstance(x, (int, float)) for x in c[:2]):
            pts.append(c)
        elif isinstance(c, (list, tuple)):
            for x in c:
                walk(x)
    walk((geom or {}).get("coordinates"))
    if not pts:
        return None, None
    return round(sum(p[1] for p in pts) / len(pts), 6), round(sum(p[0] for p in pts) / len(pts), 6)


def beaches(doc: dict) -> dict[str, dict]:
    out = {}
    for f in doc.get("features") or []:
        p = dict(f.get("properties") or {})
        if not p.get("beachId"):
            continue
        p["_lat"], p["_lon"] = centre(f.get("geometry"))
        out[p["beachId"]] = p
    return out


def kind_of(p: dict) -> str | None:
    """'permanent', 'temporary' or None, as the map's two layers select and colour the beach."""
    tier = str(p.get("tierRankingCode") or "")
    if str(p.get("permanentAdvisory") or "").upper() == "YES" and tier != "3":
        return "permanent"
    if str(p.get("permanentAdvisory") or "").upper() != "YES" and tier not in ("3", "4") and \
            str(p.get("status") or "").strip() and str(p.get("status")).strip().lower() != "green":
        return "temporary"
    return None


def new_record(p: dict, kind: str, poll: str, ctx: dict) -> dict:
    sample = mdy(p.get("dateCollected"))
    temp = kind == "temporary"
    rid = f"{p['beachId']}-{sample or 'nodate'}" if temp else f"{p['beachId']}-permanent"
    raw = {"beach": {k: v for k, v in p.items() if not k.startswith("_")}, "first_seen_poll": poll,
           "last_seen_poll": poll, "samples": [{"date": sample, "entero": p.get("entero")}] if sample else [],
           "start_basis": ("the date of the sample whose result the advisory follows" if temp else
                           "the advisory was already posted when first read; its start is not published")}
    return event(source_id=SOURCE_ID, source_record_id=rid, event_type="beach_advisory", status="advisory_active",
                 waterbody_text=p.get("beachName") or None, lat=p["_lat"], lon=p["_lon"],
                 coord_source="source" if p["_lat"] is not None else None,
                 started_at=sample if temp else poll, time_precision="day" if temp and sample else "poll",
                 source_updated_at=ctx.get("last_modified"), fetched_at=ctx["fetched_at"],
                 authority=AUTHORITY, advice_text=TEMP_TEXT if temp else PERM_TEXT,
                 source_url=PAGE_URL, raw=raw, parse_error=None if (sample or not temp) else "no sample date")


def apply_snapshot(prev: list[dict], doc: dict, ctx: dict) -> tuple[list[dict], dict]:
    poll = ctx["fetched_at"]
    now = beaches(doc)
    records = {r["event_id"]: r for r in prev}
    active = {}
    for r in records.values():
        if r["status"] == "advisory_active":
            b = (r["raw"].get("beach") or {}).get("beachId")
            kind = "permanent" if r["source_record_id"].endswith("-permanent") else "temporary"
            active[(b, kind)] = r
    n = {"opened": 0, "continued": 0, "lifted": 0, "missing": 0}
    for (b, kind), r in active.items():
        p = now.get(b)
        raw = r["raw"]
        if p is None:
            raw.setdefault("missing_since", poll)
            n["missing"] += 1
            continue
        raw.pop("missing_since", None)
        if kind_of(p) == kind:
            sample = mdy(p.get("dateCollected"))
            if sample and all(s.get("date") != sample for s in raw.get("samples") or []):
                raw.setdefault("samples", []).append({"date": sample, "entero": p.get("entero")})
            raw["beach"] = {k: v for k, v in p.items() if not k.startswith("_")}
            raw["last_seen_poll"] = poll
            r["source_updated_at"] = ctx.get("last_modified")
            n["continued"] += 1
        else:
            r["status"] = "advisory_lifted"
            r["ended_at"] = poll
            raw["ended_at_precision"] = "poll"
            raw["lift_observed_between"] = [raw.get("last_seen_poll"), poll]
            n["lifted"] += 1
    for b, p in now.items():
        kind = kind_of(p)
        cur = active.get((b, kind))
        if not kind or (cur and cur["status"] == "advisory_active"):
            continue
        rec = new_record(p, kind, poll, ctx)
        if rec["event_id"] in records:                     # the same sample read again after a lift: a new spell
            rec["source_record_id"] += f"~{poll[:10]}"
            rec["event_id"] = f"{SOURCE_ID}:{rec['source_record_id']}"
        records[rec["event_id"]] = rec
        n["opened"] += 1
    out = sorted(records.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return out, n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved beach.geojson instead of downloading")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    try:
        if args.file:
            doc, lm = json.loads(Path(args.file).read_text()), None
        else:
            r = requests.get(URL, headers=HEADERS, timeout=(15, 60))
            r.raise_for_status()
            doc = r.json()
            h = r.headers.get("Last-Modified")
            lm = parsedate_to_datetime(h).isoformat().replace("+00:00", "Z") if h else None
            if lm != (prev_doc.get("meta") or {}).get("last_modified"):
                p = RAW_DIR / SOURCE_ID / f"beach-{(lm or fetched_at)[:19].replace(':', '')}.geojson"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
        n_beaches = len(beaches(doc))
        prev_n = (prev_doc.get("meta") or {}).get("beaches") or 0
        if not n_beaches or n_beaches < prev_n / 2:
            raise ValueError(f"{n_beaches} beaches in the file (previous poll {prev_n})")
    except Exception as e:  # noqa: BLE001 - an outage keeps the advisories as they were
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    records, n = apply_snapshot(prev_doc.get("records", []), doc, {"fetched_at": fetched_at, "last_modified": lm})
    meta = {"url": URL, "page_url": PAGE_URL, "last_modified": lm, "beaches": n_beaches, "changes": n,
            "active": sum(1 for r in records if r["status"] == "advisory_active"),
            "credit": "Georgia Department of Natural Resources, Coastal Resources Division, Healthy Beaches",
            "license": "none stated", "registry_ids": ["ga-dnr-healthy-beaches"]}
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"{SOURCE_ID}: {n_beaches} beaches, {meta['active']} advisories active, changes {n} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
