"""Colorado toxic algae status sheet -> algal-bloom advisories (source id co-cdphe-toxic-algae).

Source
  The public Google Sheet the Colorado Department of Public Health and Environment's toxic algae page links ("Recent
  blooms for select water bodies"; research/co, checked 2026-11-03: the page linked it; on 2026-11-14 cdphe.colorado.gov
  answered 403 to the build's client, so the link was not re-read), read as CSV:
  https://docs.google.com/spreadsheets/d/1rnsdGU5IrrCt3jfYQGa3obDd7SN27R1mitLhilBvYSQ/export?format=csv
  Four columns: Waterbody name, Condition Category, Update Date, Other notes. No key, no licence stated. The notes are
  the agency's own words about the bloom; the raw save keeps those four columns only, the notes scrubbed
  (ingest/mountain_scrub.py), and records carried from earlier runs are scrubbed again on every save path.
  A sheet with fewer rows than the last good read (meta.last_ok_rows, kept through failed runs) is a failed read.
  On 2026-11-14 it held 197 rows: a season baseline of 127 waters at "No bloom reported" dated 2026-04-01, then rows
  appended in date order as conditions changed (Caution 48, Warning 14, Third party 3, No bloom reported 133 in all);
  the last update was dated 2026-09-09. It is a log: a water's current condition is its last row.

Record rules
  - Rows are read per water in sheet order (the order they were appended). A run of rows other than "No bloom
    reported" is one advisory: started_at the Update Date of its first row (the sheet's date for the condition, day
    precision, Mountain time; the sheet does not say whether it is the sampling or the posting day, raw.date_note), the
    rows of the run kept in raw.updates (date, condition, note), the highest condition in raw.condition_max.
  - The next "No bloom reported" row of that water ends it: status advisory_lifted, ended_at that row's Update Date
    (raw.ended_at_precision day, raw.end_basis quoting the row). A run with no such row is the water's current
    condition: status advisory_active with no end, confirmed at every read that still shows it as the water's last
    row (raw._last_seen_in_source the read's time), so it lasts while the sheet keeps it; a read that finds the run
    gone or changed writes raw._unlisted_since at that read (a poll bound, never an invented lift).
  - "Third party" is the sheet's own category (another body reports for that water, as for Blue Mesa Reservoir); kept
    in its words (raw._agency_label), the advisory's window as for the others.
  - A date out of order within a water (2026-08-26 written 8/26/2024 between August 2026 rows) is kept as written and
    listed in raw.date_anomalies; it never starts or ends a run on its own.
  - No coordinates: the record is placed by the water's name (raw.placement_hint, state CO); a qualifier the sheet
    adds ("Blue Heron Lake, St. Vrain State Park", "Jumbo Reservoir (Julesburg)") is kept in raw.place.
  - A "No bloom reported" row is never a record and never reads as clean water: grey.

Run from pipeline/:  python -m ingest.co_cdphe_toxic_algae [--file saved.csv]
"""
from __future__ import annotations

import csv
import io
import re
import sys
from datetime import date
from pathlib import Path

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest.mountain_scrub import scrub

SOURCE_ID = "co-cdphe-toxic-algae"
SHEET = "1rnsdGU5IrrCt3jfYQGa3obDd7SN27R1mitLhilBvYSQ"
URL = f"https://docs.google.com/spreadsheets/d/{SHEET}/export?format=csv"
PAGE = f"https://docs.google.com/spreadsheets/d/{SHEET}"
LANDING = "https://cdphe.colorado.gov/toxic-algae"
AUTHORITY = "Colorado Department of Public Health and Environment (toxic algae status sheet)"
TZ = "America/Denver"
NONE = "no bloom reported"
RANK = {"third party": 1, "caution": 2, "warning": 3}
COLUMNS = ("Waterbody name", "Condition Category", "Update Date", "Other notes")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def parse_date(s: str) -> str | None:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*", s or "")
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    yr = yr + 2000 if yr < 100 else yr
    try:
        return date(yr, mo, dy).isoformat()
    except ValueError:
        return None


def water_name(name: str) -> tuple[str, str | None]:
    """('Blue Heron Lake', 'St. Vrain State Park') from 'Blue Heron Lake, St. Vrain State Park'."""
    n = " ".join((name or "").split())
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", n)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    if "," in n:
        a, b = n.split(",", 1)
        return a.strip(), b.strip()
    return n, None


def read_rows(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or any(c not in rows[0] for c in COLUMNS):
        raise ValueError(f"the sheet's columns changed: {list(rows[0]) if rows else 'no rows'}")
    out = []
    for i, r in enumerate(rows):
        name = " ".join((r.get("Waterbody name") or "").split())
        if not name:
            continue
        out.append({"row": i + 2, "name": name, "condition": " ".join((r.get("Condition Category") or "").split()),
                    "date_text": (r.get("Update Date") or "").strip(), "date": parse_date(r.get("Update Date") or ""),
                    "note": scrub(r.get("Other notes")) or None})
    return out


def runs(rows: list[dict]) -> list[dict]:
    """Per water, each run of rows that are not 'No bloom reported', with the row that ends it (or None)."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["name"].lower(), []).append(r)
    out = []
    for rs in by.values():
        cur: list[dict] = []
        for r in rs + [None]:
            if r is not None and r["condition"].lower() != NONE:
                cur.append(r)
                continue
            if cur:
                out.append({"rows": cur, "ended_by": r})
                cur = []
    return out


def scrubbed_csv(text: str) -> str:
    """What the raw save keeps: the sheet's four columns only (an explicit allowlist; any other column is dropped), the
    notes scrubbed (ingest/mountain_scrub.py: names, titles, contacts, house numbers, phones, e-mails, and coordinates
    rounded to three decimals)."""
    rows = list(csv.DictReader(io.StringIO(text)))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow([" ".join((r.get(c) or "").split()) if c != "Other notes" else scrub(r.get(c)) for c in COLUMNS])
    return out.getvalue()


def sanitized(r: dict) -> dict:
    """A record carried from an earlier run, its free text scrubbed again (notes in raw.updates, the advice, the end
    basis): every save path, retained records and the failure path included (Astra review 2026-11-15 P1)."""
    r = dict(r)
    raw = dict(r.get("raw") or {})
    if isinstance(raw.get("updates"), list):
        raw["updates"] = [{**u, "note": scrub(u.get("note")) or None} if isinstance(u, dict) else u
                          for u in raw["updates"]]
    for k in ("end_basis",):
        if isinstance(raw.get(k), str):
            raw[k] = scrub(raw[k])
    if isinstance(r.get("advice_text"), str):
        r["advice_text"] = scrub(r["advice_text"])
    r["raw"] = raw
    return r


def build(text: str, fetched: str, previous: list[dict], previous_rows: int | None = None) -> tuple[list[dict], dict]:
    rows = read_rows(text)
    if previous_rows and len(rows) < previous_rows:
        # the sheet is a log that only grows: fewer rows than the last good read is a truncated or wrong answer
        raise ValueError(f"the sheet has {len(rows)} rows, fewer than the {previous_rows} of the last read")
    records: dict[str, dict] = {}
    n = {"rows": len(rows), "waters": len({r["name"].lower() for r in rows}), "advisories": 0, "current": 0,
         "lifted": 0, "undated": 0}
    for run in runs(rows):
        first = run["rows"][0]
        start = first["date"]
        if not start:
            n["undated"] += 1
            continue
        water, place = water_name(first["name"])
        srid = f"{slug(first['name'])}:{start}"
        updates = [{"date": r["date"] or r["date_text"], "condition": r["condition"], "note": r["note"]}
                   for r in run["rows"]]
        anomalies = []
        prev_d = None
        for r in run["rows"]:
            if r["date"] and prev_d and r["date"] < prev_d:
                anomalies.append(f"row {r['row']}: {r['date_text']} is earlier than the row before it ({prev_d})")
            prev_d = max(prev_d or "", r["date"] or "") or prev_d
        top = max(run["rows"], key=lambda r: RANK.get(r["condition"].lower(), 0))
        last = run["rows"][-1]
        end = run["ended_by"]
        raw = {"water": water, "place": place, "sheet_name": first["name"], "updates": updates,
               "condition_first": first["condition"], "condition_last": last["condition"],
               "condition_max": top["condition"], "time_zone": TZ,
               "date_note": ("the sheet's Update Date for the first row with this condition; the sheet does not say "
                             "whether it is the sampling or the posting day"),
               "placement_hint": {"name": water, "state": "CO",
                                  "basis": "the water the sheet names; the sheet gives no point"},
               "sheet_url": PAGE}
        if any(r["condition"].lower() == "third party" for r in run["rows"]):
            raw["_agency_label"] = "Third party"
            raw["third_party_note"] = ("the sheet's own category: another body reports the condition of this water; "
                                       "the advisory's window is applied as for the sheet's other conditions")
        if anomalies:
            raw["date_anomalies"] = anomalies
        advice = (f"The sheet lists {first['name']} as \"{last['condition']}\" since {start}"
                  + (f": {last['note']}" if last["note"] else "") + ".")
        if end:
            raw["ended_at_precision"] = "day"
            raw["end_basis"] = (f"the sheet's next row for this water, dated {end['date_text']}: \"{end['condition']}\""
                                + (f" ({end['note']})" if end["note"] else ""))
            n["lifted"] += 1
        else:
            raw["_last_seen_in_source"] = fetched
            raw["end_basis"] = "still the water's last row in the sheet at this read"
            n["current"] += 1
        rec = event(source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory",
                    status="advisory_lifted" if end else "advisory_active", waterbody_text=water,
                    started_at=start, ended_at=(end or {}).get("date"), time_precision="day",
                    fetched_at=fetched, authority=AUTHORITY, advice_text=advice, source_url=PAGE, raw=raw)
        records[rec["event_id"]] = rec
        n["advisories"] += 1
    kept = 0
    for p in previous:      # a current advisory the sheet no longer shows: ended at this read (a poll bound)
        if p["event_id"] in records:
            if p["status"] == "advisory_active" and (p.get("raw") or {}).get("_first_seen_at"):
                records[p["event_id"]]["raw"]["_first_seen_at"] = p["raw"]["_first_seen_at"]
            continue
        p = sanitized(p)
        praw = dict(p.get("raw") or {})
        if p.get("status") == "advisory_active" and not p.get("ended_at") and not praw.get("_unlisted_since"):
            # ended at this read as a poll bound; the colour stops 14 days after the last read that listed it however
            # late the absence is seen (raw._ages_after_confirmation; lessons, item 2)
            praw["_unlisted_since"] = fetched
            p["ended_at"] = fetched
            praw["_ages_after_confirmation"] = True
            praw["ended_at_precision"] = "poll"
            praw["end_basis"] = ("the read that no longer found this advisory in the sheet (a poll bound; the sheet "
                                 "gives no lift)")
        p["raw"] = praw
        records[p["event_id"]] = p
        kept += 1
    for r in records.values():
        r["raw"].setdefault("_first_seen_at", fetched)
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    last = max((r["date"] for r in rows if r["date"]), default=None)
    meta = {"registry_ids": [SOURCE_ID], "url": PAGE, "landing": LANDING, "kept_from_previous": kept,
            "last_ok_rows": len(rows),
            "latest_update_date": last, **n,
            "cadence": "the sheet is read every run; CDPHE adds a row when a water's condition changes"}
    return out, meta


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    try:
        if "--file" in argv:
            text = Path(argv[argv.index("--file") + 1]).read_text(encoding="utf-8-sig")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=90)
            r.raise_for_status()
            text = r.content.decode("utf-8-sig")
            save_raw(SOURCE_ID, scrubbed_csv(text), "csv")
        last = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
        prev = last.get("records", [])
        # always compared with the last good read, whatever the runs since (a failed run keeps that read's meta):
        # a truncated answer after an outage is never accepted (Astra review 2026-11-15 P1)
        lm = last.get("meta") or {}
        recs, meta = build(text, fetched, prev, lm.get("last_ok_rows") or lm.get("rows"))
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records, sanitized again)
        kept = [sanitized(r) for r in (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
                if isinstance(r, dict)]
        write_events(SOURCE_ID, kept, ok=False, partial=True, error=scrub(f"{type(e).__name__}: {e}")[:300])
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['rows']} rows, {meta['waters']} waters, {meta['advisories']} advisories "
          f"({meta['current']} current, {meta['lifted']} ended by a later row) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
