"""Oregon Health Authority, Oregon Beach Monitoring Program: the current beach conditions table, read as a snapshot
-> data/build/events/or-oha-beach-monitoring.json

Source
  https://www.oregon.gov/oha/PH/HEALTHYENVIRONMENTS/RECREATION/BEACHWATERQUALITY/Pages/status.aspx (registry:
  or-oha-beach-monitoring), no key. One HTML table per coast ("North Coast Beaches", "Mid Coast Beaches", "South Coast
  Beaches"), each row County | Beach | Status, the status in bold, one of OHA's key words: OPEN ("Swimming and bathing
  are permitted"), ADVISORY ("Swimming and bathing are not recommended at this time"), SEWAGE ("Sewage spills or major
  pollution events occurred. Avoid swimming or water contact.") and NO MONITORING. OHA samples from mid-May to
  mid-September; on 2026-11-07 "The 2026 monitoring season has ended" and every beach (33) read NO MONITORING, so this
  reader was written from the page's own markup ahead of the 2027 season (review 2026-11-08 P2-7) and is tested on a
  fixture in that markup. No law requires the page; it is OHA's practice with DEQ.

Record rules (rules only; no geocoding)
  - A row whose status is ADVISORY opens a beach advisory (event_type beach_advisory, the beach category); SEWAGE opens
    OHA's sewage advisory (event_type sso, the sewage category: OHA's own word for a sewage spill at the beach), status
    advisory_active, raw.advisory_noun "Beach advisory (Oregon Health Authority)" or "Sewage advisory (Oregon Health
    Authority)", advice_text OHA's key sentence for the status. OPEN and NO MONITORING are no record (grey: no report).
  - The page gives no issue date: started_at is the first read that showed the status (time_precision poll; raw
    .start_basis says so); published_at, reported_at and source_updated_at stay null. Each read that still shows it
    writes raw._last_seen_in_source; the first complete read that no longer shows it writes raw._unlisted_since, where
    the status build ends OHA's window (OHA lifts an advisory by changing the status). A failed read changes nothing.
  - Key: "<beach slug>-<status>-<first day>"; one open record per beach and status.
  - Place: waterbody_text the beach's name as OHA gives it, raw.county its county and raw.coast the table; placed by
    name in its county (Oregon's county-aware placement); no point.
  - Times: America/Los_Angeles (raw.time_zone).
  - A read that finds no table row at all is a changed page: ok false, the records kept.

Privacy: only the three cells of each row and the coast heading are read and saved; the page's contact address is
never read. Cadence: hourly (the page changes when OHA posts). Run from pipeline/:  python -m ingest.or_oha_beaches [--file page.html]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "or-oha-beach-monitoring"
URL = "https://www.oregon.gov/oha/PH/HEALTHYENVIRONMENTS/RECREATION/BEACHWATERQUALITY/Pages/status.aspx"
TZ = "America/Los_Angeles"
TIMEOUT = (60, 600)
STATUSES = ("NO MONITORING", "ADVISORY", "SEWAGE", "OPEN")
KEY_TEXT = {"ADVISORY": "Swimming and bathing are not recommended at this time.",
            "SEWAGE": "Sewage spills or major pollution events occurred. Avoid swimming or water contact."}
OPENS = {"ADVISORY": ("beach_advisory", "Beach advisory (Oregon Health Authority)"),
         "SEWAGE": ("sso", "Sewage advisory (Oregon Health Authority)")}
AUTHORITY = "Oregon Health Authority (Oregon Beach Monitoring Program)"


def text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def rows_of(body: bytes | str) -> list[dict]:
    """[{coast, county, beach, status}] of the page: every table row whose last cell is one of OHA's status words."""
    t = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    out = []
    for m in re.finditer(r"(?is)<h3[^>]*>(.*?)</h3>\s*<table\b(.*?)</table>", t):
        coast = text(m.group(1))
        for tr in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", m.group(2)):
            cells = [text(c) for c in re.findall(r"(?is)<td\b[^>]*>(.*?)</td>", tr)]
            cells = [c for c in cells]
            if len(cells) < 3:
                continue
            county, beach, status = cells[-3], cells[-2], cells[-1].upper()
            st = next((s for s in STATUSES if status.startswith(s)), None)
            if st and county and beach and county.lower() != "county":
                out.append({"coast": coast, "county": county, "beach": beach, "status": st})
    return out


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def build(rows: list[dict], prev: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    recs = {r["source_record_id"]: r for r in prev}
    open_now = {(slug(r["beach"]), r["status"]): r for r in rows if r["status"] in OPENS}
    seen = set()
    for r in recs.values():                                   # the advisories open at the last read
        raw = r.get("raw") or {}
        k = (raw.get("beach_slug"), raw.get("oha_status"))
        if raw.get("_unlisted_since"):
            continue
        if k in open_now:
            raw["_last_seen_in_source"] = fetched_at
            seen.add(k)
        else:
            raw["_unlisted_since"] = fetched_at               # OHA changed the status: its window ends at this read
    for k, row in open_now.items():
        if k in seen:
            continue
        et, noun = OPENS[row["status"]]
        rid = f"{k[0]}-{row['status'].lower()}-{fetched_at[:10]}"
        recs[rid] = event(
            source_id=SOURCE_ID, source_record_id=rid, event_type=et, status="advisory_active",
            waterbody_text=row["beach"], water_match="name", started_at=fetched_at, time_precision="poll",
            reported_at=None, published_at=None, source_updated_at=None, fetched_at=fetched_at,
            authority=AUTHORITY, advice_text=f"Oregon Health Authority: {row['status']}. {KEY_TEXT[row['status']]}",
            advice_window_basis="in effect while OHA's beach conditions table shows the status; OHA sets no fixed period",
            source_url=URL,
            raw={"state": "OR", "time_zone": TZ, "county": row["county"], "coast": row["coast"],
                 "beach_slug": k[0], "oha_status": row["status"], "advisory_noun": noun,
                 "start_basis": ("the first read of OHA's table that showed the status: the page gives no issue date, "
                                 "so the advisory may have begun earlier"),
                 "_first_seen_at": fetched_at, "_last_seen_in_source": fetched_at})
    out = sorted(recs.values(), key=lambda r: r["started_at"] or "", reverse=True)
    stats = {"rows": len(rows), "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES},
             "open_records": sum(1 for r in out if not (r.get("raw") or {}).get("_unlisted_since")),
             "records": len(out)}
    return out, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved page (HTML) or the safe rows this module saves (JSON)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records") or []
    try:
        if args.file:
            body = Path(args.file).read_bytes()
            rows = json.loads(body)["rows"] if args.file.endswith(".json") else rows_of(body)
        else:
            r = requests.get(URL, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            rows = rows_of(r.content)
            save_raw(SOURCE_ID, json.dumps({"url": URL, "rows": rows}, ensure_ascii=False), "json")
        if not rows:
            raise ValueError("no beach rows in OHA's table: the page has changed")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    recs, stats = build(rows, prev, fetched_at)
    meta = {**stats, "page": URL, "registry_ids": [SOURCE_ID], "timezone": TZ,
            "credit": "Oregon Health Authority, Oregon Beach Monitoring Program, current beach conditions",
            "time_basis": "the page gives no dates: an advisory runs from the first read that shows it to the first that "
                          "no longer does"}
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {json.dumps(stats)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
