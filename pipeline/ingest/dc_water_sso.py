"""DC Water's sanitary sewer overflow file -> data/build/events/dc-water-sso.json.

Source
  https://serviceinfo.dcwater.com/dashboard/sso.csv, the data behind DC Water's Sanitary Sewer dashboard
  (https://www.dcwater.com/resources/open-data-portal/sanitary-sewer-dashboard; registry dc-dcwater-sso-dashboard,
  source dc-dcwater-sso-csv). Voluntary: no law or permit clause names it. On 2026-11-16 it held 36 rows reported
  2023-05-08 to 2026-01-20 (none between September 2024 and October 2025 but one) with five columns: PremiseNo,
  Date Reported, SpillVolInGal, Location, Description. DC Water's page attaches the condition "not for any
  commercial, legal or other use".

What is kept and what is dropped (privacy)
  Kept: Date Reported (reported_at, local time to the minute), SpillVolInGal (volume_gal; the file does not say
  whether a figure is measured or estimated: estimate_flag unknown) and the Location's street names: an intersection
  ("@HAWAII AVE @TAYLOR ST NE") as written without the '@' marks, an address with its house number removed
  ("[house number removed] MINNESOTA AVE NE"), a block number too. A Location that still holds any other figure after
  that is withheld (raw.location_withheld). Dropped before anything is saved: PremiseNo (a customer premise id),
  Description (it repeats the address, house number included, and names no water) and every house number. The file
  itself is never saved (no data/raw copy); only the kept fields reach the records and the health metadata.

Records
  One per row: event_type sso, status unknown (no end is given), started_at null (the file gives the day the spill
  was reported, which is not its start), reported_at the Date Reported, published_at null, no water (the file names
  none) and no point (the file gives no coordinates; a street address is never geocoded). The record is a report for
  the District, placed on no water. source_record_id is the Date Reported to the second as written
  ("2026-01-20T00:44:24.607"), with the street names' digest added when two rows share it: never the premise id, the
  row order or a house number.

Rows that leave the file, failures
  A record of the previous events file whose row is no longer in the file stays as a past report
  (raw.not_listed_since). A file that cannot be fetched, has no rows, or whose header differs from COLUMNS fails the
  run (ok=False) and keeps every earlier record; a row whose date cannot be read is skipped, listed by count only, and
  the run is ok=False (partial).

Duplicates
  An EPA Sewer Overflow and Bypass Event row of DC0021199 (data/build/events/echo-sewer-overflow.json) whose
  start-to-end days, widened by one day, hold the report day and whose location names one of the row's streets is the
  structured record of the same spill: duplicate_of it (one such row only).

Run from pipeline/: python -m ingest.dc_water_sso [--backfill]   (the file is read whole; --backfill is accepted)
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sys
from datetime import date, datetime, timedelta

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, write_events

SOURCE_ID = "dc-water-sso"
REGISTRY_ID = "dc-dcwater-sso-csv"
URL = "https://serviceinfo.dcwater.com/dashboard/sso.csv"
PAGE = "https://www.dcwater.com/resources/open-data-portal/sanitary-sewer-dashboard"
ECHO_FILE = EVENTS_DIR / "echo-sewer-overflow.json"
COLUMNS = ["PremiseNo", "Date Reported", "SpillVolInGal", "Location", "Description"]
KEPT = ["Date Reported", "SpillVolInGal", "Location (street names only)"]
DROPPED = ["PremiseNo", "Description", "the house number of Location"]
PERMIT = "DC0021199"
DISCHARGER_ID = "dc-dc0021199"
DISCHARGER_NAME = "District of Columbia Water and Sewer Authority (DC Water)"
AUTHORITY = "DC Water, Sanitary Sewer dashboard data file"
HOUSE_NUMBER_REMOVED = "[house number removed]"
MATCH_PAD_DAYS = 1
ORDINAL = re.compile(r"^\d{1,3}(?:ST|ND|RD|TH)$", re.I)
SUFFIX = {"ST": "STREET", "STREET": "STREET", "AVE": "AVENUE", "AV": "AVENUE", "AVENUE": "AVENUE", "RD": "ROAD",
          "ROAD": "ROAD", "PKY": "PARKWAY", "PKWY": "PARKWAY", "PARKWAY": "PARKWAY", "PL": "PLACE", "PLACE": "PLACE",
          "DR": "DRIVE", "DRIVE": "DRIVE", "CIR": "CIRCLE", "CIRCLE": "CIRCLE", "BLVD": "BOULEVARD",
          "BOULEVARD": "BOULEVARD", "TER": "TERRACE", "TERRACE": "TERRACE", "CT": "COURT", "COURT": "COURT",
          "LN": "LANE", "LANE": "LANE", "WAY": "WAY"}
QUADRANTS = {"NW", "NE", "SE", "SW"}


STREET_PART = re.compile(r"^(?:[A-Z][A-Z'.-]*|\d{1,3}(?:ST|ND|RD|TH))(?: (?:[A-Z][A-Z'.-]*|\d{1,3}(?:ST|ND|RD|TH)))* "
                         r"(?:ST|STREET|AVE?|AVENUE|RD|ROAD|PKY|PKWY|PARKWAY|PL|PLACE|DR|DRIVE|CIR|CIRCLE|BLVD|BOULEVARD|"
                         r"TER|TERRACE|CT|COURT|LN|LANE|WAY|LINE)(?: (?:NW|NE|SE|SW))?$", re.I)


def safe_location(loc: str) -> tuple[str | None, str | None]:
    """(the Location's street names with no house number, why it was withheld or None). Every part must be a street
    name (words or an ordinal ending in a street word, a quadrant after it); anything else withholds the location."""
    t = " ".join((loc or "").replace("\\", " ").split())
    if not t:
        return None, "the file gives no location"
    if t.startswith("@") or " @" in t:
        parts = [p.strip() for p in t.split("@") if p.strip()]
        out, check = " and ".join(parts), parts
    else:
        # a house number (with a suffix or a range) or a block number ahead of the street
        out = re.sub(r"^\d{1,6}(?:-?[A-Za-z]\b|-\d{1,6}[A-Za-z]?|\s*1/2)?\s+(?:BLOCK\s+OF\s+|BLK\s+)?",
                     HOUSE_NUMBER_REMOVED + " ", t, flags=re.I)
        check = [out.replace(HOUSE_NUMBER_REMOVED, "").strip()]
    if not all(STREET_PART.match(p) for p in check):
        return None, "the location is not only street names and is withheld"
    return out, None


def streets(loc: str | None) -> set[str]:
    """The normalised street names of a location, each with its quadrant when the location gives one
    ('HAWAII AVENUE NE', '2ND STREET'): K Street NW and K Street SE are different streets."""
    text = (loc or "").replace(HOUSE_NUMBER_REMOVED, " ").upper()
    quad = re.findall(r"\b(NW|NE|SE|SW)\b", text)
    q = quad[-1] if len(set(quad)) == 1 else None
    out = set()
    for part in re.split(r"\band\b|&|@|,|\(|\)|\bAT\b|\bNEAR\b|\bALONG\b", text, flags=re.I):
        words = [w.strip(".") for w in part.split()]
        words = [w for w in words if w not in QUADRANTS and not re.fullmatch(r"\d+", w)]
        for i, w in enumerate(words):
            if w in SUFFIX and i >= 1:
                name = " ".join(words[max(0, i - 3):i] + [SUFFIX[w]])
                out.add(name + (f" {q}" if q else ""))
                break
    return out


def same_street(mine: set[str], theirs: set[str]) -> bool:
    """A shared street name whose quadrants do not differ (one side may give none)."""
    for a in mine:
        for b in theirs:
            an, aq = (a[:-3], a[-2:]) if a[-3:-2] == " " and a[-2:] in QUADRANTS else (a, None)
            bn, bq = (b[:-3], b[-2:]) if b[-3:-2] == " " and b[-2:] in QUADRANTS else (b, None)
            if (an == bn or an.endswith(" " + bn) or bn.endswith(" " + an)) and (aq is None or bq is None or aq == bq):
                return True
    return False


def reported(v: str) -> tuple[str | None, str | None]:
    """(reported_at to the minute, the timestamp as an id 'YYYY-MM-DDTHH:MM:SS.fff') of 'YYYY-MM-DD HH:MM:SS.fffffff'."""
    m = re.fullmatch(r"\s*(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?\s*", v or "")
    if not m:
        return None, None
    try:
        datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None, None
    frac = (m.group(5) or "").rstrip("0")
    rid = f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4) or '00'}" + (f".{frac}" if frac else "")
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}", rid


def volume(v: str) -> int | None:
    t = (v or "").replace(",", "").strip()
    return int(float(t)) if re.fullmatch(r"\d+(?:\.\d+)?", t) else None


def parse(text: str) -> tuple[list[dict], int]:
    """(the kept fields of each row, the number of rows whose date could not be read). Raises ValueError when the
    header is not COLUMNS or there are no rows. Nothing of a dropped field leaves this function."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if [h.strip() for h in header or []] != COLUMNS:
        raise ValueError(f"the file's columns changed (expected {', '.join(COLUMNS)}; found "
                         f"{len(header or [])} columns)")
    rows, bad = [], 0
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        if len(cells) > len(COLUMNS) and not any(c.endswith("\\") for c in cells[:len(COLUMNS) - 1]):
            # a comma the file escapes with a backslash ('Street\,') inside the last column, Description, which is
            # dropped: the cells after the fourth are all Description's
            cells = cells[:len(COLUMNS) - 1] + [",".join(cells[len(COLUMNS) - 1:])]
        if len(cells) != len(COLUMNS):
            bad += 1
            continue
        r = dict(zip(COLUMNS, cells))
        at, rid = reported(r["Date Reported"])
        if at is None:
            bad += 1
            continue
        loc, why = safe_location(r["Location"])
        rows.append({"reported_at": at, "id": rid, "volume_gal": volume(r["SpillVolInGal"]),
                     "volume_as_given": r["SpillVolInGal"].strip() if volume(r["SpillVolInGal"]) is not None else None, "location": loc, "location_withheld": why})
    if not rows and not bad:
        raise ValueError("the file has no rows")
    return rows, bad


def row_id(r: dict) -> str:
    """The Date Reported to the second, with a digest of the row's own kept street names and gallons: never the premise
    id, the row order, another row or a house number."""
    key = f"{r['location'] or ''}|{r['volume_as_given'] or ''}"
    return f"{r['id']}-{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def to_records(rows: list[dict], fetched_at: str) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        rid = row_id(r)
        if rid in seen:
            continue                    # the same kept fields twice: one report
        seen.add(rid)
        raw = {"date_reported": r["reported_at"], "volume_as_given": r["volume_as_given"],
               "location_streets": r["location"], "fields_kept": KEPT, "fields_dropped": DROPPED,
               "date_basis": "the file's Date Reported; it gives no start or end of the spill",
               "placement": "the file names no water and gives no coordinates: a District report placed on no water",
               "time_zone": "America/New_York", "page": PAGE,
               "use_condition": "DC Water's page: 'not for any commercial, legal or other use'"}
        if r["location_withheld"]:
            raw["location_withheld"] = r["location_withheld"]
        rec = event(source_id=SOURCE_ID, source_record_id=rid, event_type="sso", status="unknown",
                    discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER_NAME, npdes_permit=PERMIT,
                    waterbody_text=None, water_slugs=[], water_match="none",
                    started_at=None, ended_at=None, time_precision=None, reported_at=r["reported_at"],
                    published_at=None, source_updated_at=None, fetched_at=fetched_at,
                    material="untreated sewage", volume_gal=r["volume_gal"],
                    volume_text=f"{r['volume_as_given']} gallons" if r["volume_gal"] is not None else None,
                    estimate_flag="unknown", authority=AUTHORITY, source_url=URL, raw=raw)
        out.append(rec)
    return out


def carry_forward(prev: dict, current: list[dict], at: str) -> list[dict]:
    """Earlier records whose rows the file no longer lists: kept as past reports (raw.not_listed_since)."""
    have = {r["event_id"] for r in current}
    out = []
    for r in prev.get("records") or []:
        if isinstance(r, dict) and r.get("event_id") and r["event_id"] not in have:
            raw = dict(r.get("raw") or {})
            raw.setdefault("not_listed_since", at)
            out.append({**r, "raw": raw})
    return out


def echo_rows():
    d = read_json(ECHO_FILE, {}) or {}
    return [r for r in d.get("records") or [] if isinstance(r, dict) and r.get("npdes_permit") == PERMIT
            and r.get("started_at") and r.get("event_type") == "sso"]


def _day(v) -> date | None:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def link_duplicates(recs: list[dict], rows: list[dict]) -> int:
    n = 0
    for rec in recs:
        rec["duplicate_of"] = None
        d = _day(rec.get("reported_at"))
        mine = streets((rec.get("raw") or {}).get("location_streets"))
        if d is None or not mine:
            continue
        cands = []
        for row in rows:
            s, e = _day(row.get("started_at")), _day(row.get("ended_at")) or _day(row.get("started_at"))
            if s is None or not (s - timedelta(days=MATCH_PAD_DAYS) <= d <= e + timedelta(days=MATCH_PAD_DAYS)):
                continue
            text = " ".join(str(row.get(k) or "") for k in ("location_text", "outfall_name")) + " " + \
                str((row.get("raw") or {}).get("location_text") or (row.get("raw") or {}).get("location") or "")
            if same_street(mine, streets(text.replace("PKWY", "PARKWAY"))):
                cands.append(row["event_id"])
        if len(cands) == 1:
            rec["duplicate_of"] = cands[0]
            rec["raw"]["duplicate_basis"] = ("EPA's Sewer Overflow and Bypass Event row of DC0021199 on the same days, "
                                             "naming the same street")
            n += 1
    return n


def main(argv=None) -> int:
    at = now_iso()
    path = EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = read_json(path, {}) or {}
    try:
        r = requests.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        rows, bad = parse(r.content.decode("utf-8-sig", "replace"))
    except (requests.RequestException, ValueError) as e:
        msg = f"{type(e).__name__}: {e}" if isinstance(e, requests.RequestException) else str(e)
        write_events(SOURCE_ID, [], ok=False, error=f"not read: {msg}",
                     meta={"registry_ids": [REGISTRY_ID], "url": URL, "fields_kept": KEPT, "fields_dropped": DROPPED})
        print(f"{SOURCE_ID}: not read ({msg}); earlier records kept", file=sys.stderr)
        return 1
    recs = to_records(rows, at)
    held = carry_forward(prev, recs, at)
    recs += held
    dups = link_duplicates(recs, echo_rows())
    meta = {"registry_ids": [REGISTRY_ID], "url": URL, "page": PAGE, "rows_in_file": len(rows) + bad,
            "rows_unread": bad, "not_listed_kept": len(held), "duplicates_of_epa_rows": dups,
            "fields_kept": KEPT, "fields_dropped": DROPPED,
            "newest_reported": max((x["reported_at"] for x in rows), default=None),
            "coordinates": "the file gives none"}
    err = f"{bad} rows whose date or cells could not be read were skipped" if bad else None
    # DC Water's page attaches "not for any commercial, legal or other use" to this file: the records are kept in the
    # events file but withheld from the status build and the export until the owner has decided on that condition, as
    # New Hampshire's swimming layer is (build/status.py load_events reads meta.distribution_discouraged)
    meta["distribution_discouraged"] = True
    meta["use_condition"] = "DC Water's page: 'not for any commercial, legal or other use'"
    out = write_events(SOURCE_ID, recs, ok=not bad, error=err, meta=meta, partial=bool(bad))
    print(f"{SOURCE_ID}: {len(recs)} records ({len(held)} no longer listed, {dups} linked to EPA rows) -> {out}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
