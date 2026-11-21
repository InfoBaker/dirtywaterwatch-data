"""Bangor, Maine: the sanitary sewer overflow log of the City's annual consent-decree reports, 2016 to 2024.

Source
  The City of Bangor's Annual Report on Compliance to EPA and Maine DEP under its 2015 consent decree (United States
  v. City of Bangor), one PDF a year, listed at https://bangormaine.gov/411/Consent-Decree---US-EPA (registry:
  me-bangor-sso-log). Each report's appendix E or F, "SSO Event Log", has one row per sanitary sewer overflow found in
  the calendar year: event number, date and time reported or discovered, date and time stopped, location (nearest
  address), final disposition (ground, street, MS4, surface water), source of notification, suspected cause, whether a
  blockage or hydraulic limitation in the public system caused it, measures taken, estimated volume and method, and
  the date of the last overflow at the place. The reports for 2016 to 2022 are scans (the log pages are rotated
  images; 2021 has no text at all), so the tables are not read by a parser: data/reference/bangor-sso-log-2016-2024.csv
  holds them as transcribed by two independent readings that agree on every row (the file's header says how), without
  the location column. The ingester reads that file and asks the City's page which reports are listed: a report year
  the file lacks (the 2025 report is due on 2026-01-31 and was not listed on 2026-11-21) or a known year whose link
  changed is named in meta.unread_reports for a session to transcribe, and the run stays ok. A page that cannot be read,
  or that lists no report at all, writes the records with ok=False (partial), so the check's failure shows and the
  records stay.

Records
  One per log row: event_type sso, discharger me-bangor (ME0100781). started_at the time reported or discovered (the
  overflow may have begun earlier; minute precision where the log gives a time, Eastern time, else day), ended_at the
  time stopped where the log gives one (status ended), else none (status unknown: "end not confirmed"). A range in the
  first cell ("10/14/2022-10/19/2022") starts at its first day and keeps the last in raw. A printed date that cannot
  be a date ("8/34/17") is not read: the row is dated by its stop date and says so. A printed date after the report's
  own date ("4/6/2022" in the 2021 log, issued January 2022) is read in the report's year and says so
  (raw.date_as_printed), as the Portland filings are (ingest/me_cbep_portland_cso.py). volume_gal only where the
  estimate is one number ("1,200 Gallons", "5,000 gallons/ visual estimate"); "<99,970", "50 -100 gallons",
  "Minimal", "Trace" and "Unknown" stay in volume_text alone.
  Waters: the final disposition is the only place a water is named ("Drained overland to Penobscot River", "MS4 to
  Birch Stream"). A named water with a record near Bangor is the record's water (water_match name), and "possibly
  reaching" still places it (raw.possibly; the cautious reading). A disposition that keeps the sewage out of any water
  (the ground alone, a basement, back into the system) is raw.reached_water False with the log's words as the reason;
  a storm drain, a ditch or an unnamed stream is left open. The location column is never kept and nothing is
  geocoded, so no record has a point.

Run from pipeline/:  python -m ingest.me_bangor_sso_log
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from common import DATA_DIR, HEADERS, event, write_events

SOURCE_ID = "me-bangor-sso-log"
REGISTRY_ID = "me-bangor-sso-log"
INDEX_URL = "https://bangormaine.gov/411/Consent-Decree---US-EPA"
REFERENCE = DATA_DIR / "reference" / "bangor-sso-log-2016-2024.csv"
PERMIT = "ME0100781"
DISCHARGER_ID = "me-bangor"
AUTHORITY = "City of Bangor (annual consent-decree report to EPA)"
ZONE = ZoneInfo("America/New_York")
# year: (document id on the City's site, the report's own date where it prints one)
REPORTS = {2024: (3275, "2025-01-31"), 2023: (3332, "2024-01-31"), 2022: (3333, "2023-01-31"), 2021: (3334, None),
           2020: (3335, None), 2019: (3336, "2020-01-31"), 2018: (3337, "2019-01-31"), 2017: (3338, "2018-01-31"),
           2016: (3339, None)}
LINK = re.compile(r"DocumentCenter/View/(\d+)/Annual-Report-on-Compliance-Calendar-Year-(\d{4})")
# waters a disposition can name; a name with no record near Bangor stays in waterbody_text
WATER_NAMES = ("penobscot river", "kenduskeag stream", "birch stream", "penjajawoc stream")
BANGOR_BOX = (-68.90, 44.74, -68.66, 44.90)       # lon/lat box of the city, for telling a same-named water elsewhere
NO_WATER = re.compile(r"basement|back into|flowed back|returned to system|placed back|pumped back")
OPEN_WATER = re.compile(r"possib|\bms4\b|\bditch\b|\bstream\b|\briver\b|\bstorm\w*|\bstreet\b|\boutfall\b")   # word starts: "downstream" is no stream


def report_url(year: int) -> str:
    return f"https://bangormaine.gov/DocumentCenter/View/{REPORTS[year][0]}/Annual-Report-on-Compliance-Calendar-Year-{year}"


def bangor_waters() -> dict[str, str]:
    """name -> slug for the WATER_NAMES that have one Maine record whose box touches Bangor."""
    data = json.loads((DATA_DIR / "waters-me.json").read_text())
    found: dict[str, list[str]] = {}
    for w in data.get("waters", []):
        n = re.sub(r"[^a-z0-9]+", " ", str(w.get("name", "")).lower()).strip()
        b = w.get("bbox")
        if n in WATER_NAMES and b and b[0] <= BANGOR_BOX[2] and b[2] >= BANGOR_BOX[0] and b[1] <= BANGOR_BOX[3] \
                and b[3] >= BANGOR_BOX[1]:
            found.setdefault(n, []).append(w["slug"])
    return {n: s[0] for n, s in found.items() if len(s) == 1}


# --------------------------------------------------------------------------- cells

_DT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})(?:\s+at\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm]))?")


def _one(text: str) -> tuple[datetime | date | None, str | None]:
    """The first date (and time) in a cell; None and a note when what is printed is not a date."""
    m = _DT.search(text or "")
    if not m:
        return None, None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    yr = yr + 2000 if yr < 100 else yr
    try:
        d = date(yr, mo, dy)
    except ValueError:
        return None, f"'{m.group(0)}' is not a date"
    if m.group(4):
        h = int(m.group(4)) % 12 + (12 if m.group(6).lower() == "pm" else 0)
        return datetime(yr, mo, dy, h, int(m.group(5)), tzinfo=ZONE), None
    return d, None


def when(cell: str, year: int, issued: str | None) -> tuple[datetime | date | None, dict]:
    """A log cell's first date or time, read in the report's year when the printed one falls after the report."""
    v, note = _one(cell)
    info: dict = {}
    if note:
        info["not_a_date"] = note
    if v is not None:
        latest = date.fromisoformat(issued) if issued else date(year + 1, 1, 31)
        day = v.date() if isinstance(v, datetime) else v
        if day > latest:
            try:
                v = v.replace(year=year)
                info["date_as_printed"] = cell.strip()
            except ValueError:
                return None, {**info, "not_a_date": f"'{cell.strip()}' falls after the report and cannot be read"}
    rng = re.split(r"\s*(?:-|to)\s*(?=\d{1,2}/\d)", cell or "", maxsplit=1)
    if len(rng) == 2:
        info["through"] = rng[1].strip()
    return v, info


def iso(v: datetime | date) -> str:
    return v.isoformat(timespec="minutes") if isinstance(v, datetime) else v.isoformat()


def gallons(text: str) -> tuple[int | None, str]:
    """One number of gallons, or None for a bound, a range or a word; and the estimate flag."""
    t = (text or "").strip()
    if not re.match(r"^\d", t) or re.match(r"^[\d,]+\s*-\s*\d", t):
        return None, "unknown"
    n = int(re.match(r"^([\d,]+)", t).group(1).replace(",", ""))
    if re.search(r"measured", t, re.I):
        return n, "measured"
    if re.search(r"estimat|visual|calculat|based on|by area|evidence|observation", t, re.I):
        return n, "estimated"
    return n, "unknown"


def waters_of(disposition: str, slugs: dict[str, str]) -> tuple[list[str], list[str], bool | None, str | None]:
    """(slugs, names named, reached_water, reason) from the final disposition."""
    d = re.sub(r"\s+", " ", (disposition or "").lower()).strip()
    names = [n for n in WATER_NAMES if n in d]
    if names:
        return sorted({slugs[n] for n in names if n in slugs}), [n.title() for n in names], True, None
    if OPEN_WATER.search(d) or not d or d == "n/a":
        return [], [], None, None
    if d == "ground" or NO_WATER.search(d):
        return [], [], False, f"the log gives the final disposition as \"{disposition.strip()}\""
    return [], [], None, None


# --------------------------------------------------------------------------- records

def records_from(text: str, slugs: dict[str, str]) -> tuple[list[dict], dict]:
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    out, counts = [], {"rows": 0, "with_water": 0, "no_water": 0, "water_without_record": []}
    for r in csv.DictReader(io.StringIO(body)):
        counts["rows"] += 1
        year, page = int(r["report_year"]), int(r["page"])
        issued = REPORTS.get(year, (None, None))[1]
        start, sinfo = when(r["reported_or_discovered"], year, issued)
        stop, einfo = when(r["stopped"], year, issued)
        notes = []
        if start is None and stop is not None:
            start = stop.date() if isinstance(stop, datetime) else stop
            notes.append(f"the time reported or discovered is printed as '{r['reported_or_discovered'].strip()}'; "
                         "dated by the time stopped")
        if start is None:
            raise ValueError(f"{year} {r['event_no']}: no readable date")
        if stop is not None and iso(stop)[:10] < iso(start)[:10]:
            notes.append(f"the time stopped ('{r['stopped'].strip()}') is before the time reported; not used")
            stop = None
        slug_list, names, reached, why = waters_of(r["final_disposition"], slugs)
        bucket = "with_water" if slug_list else ("no_water" if reached is False else "open")
        counts[bucket] = counts.get(bucket, 0) + 1
        for n in names:
            if n.lower() not in slugs and n not in counts["water_without_record"]:
                counts["water_without_record"].append(n)
        gal, flag = gallons(r["estimated_volume"])
        event_no = r["event_no"].replace("‐", "-").strip()
        raw = {"report_year": year, "report_url": report_url(year), "page": page, "event_no": event_no,
               "reported_or_discovered": r["reported_or_discovered"], "stopped": r["stopped"],
               "final_disposition": r["final_disposition"], "suspected_cause": r["suspected_cause"],
               "public_system_blockage_or_limit": r["due_to_blockage_or_hydraulic_limitation"],
               "notified_by": r["source_of_notification_kind"], "prior_sso_at_location": r["prior_sso_date"],
               "time_basis": "the time reported or discovered; the overflow may have begun earlier"}
        if sinfo.get("through"):
            raw["reported_or_discovered_through"] = sinfo["through"]
        for k in ("date_as_printed", "not_a_date"):
            for side, info in (("reported_or_discovered", sinfo), ("stopped", einfo)):
                if info.get(k):
                    raw.setdefault(k, {})[side] = info[k]
        if "about" in (r["stopped"] or "") and "minute" in (r["stopped"] or ""):
            raw["duration_as_printed"] = r["stopped"]
        if names:
            raw["waters_named"] = names
            if "possib" in r["final_disposition"].lower():
                raw["possibly"] = True
        if reached is False:
            raw["reached_water"] = False
            raw["_no_water_reason"] = why
        if notes:
            raw["notes"] = notes
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"{year}:{event_no}",
            event_type="sso", status="ended" if stop is not None else "unknown",
            discharger_id=DISCHARGER_ID, discharger_name="City of Bangor", npdes_permit=PERMIT,
            waterbody_text="; ".join(names) or None, water_slugs=slug_list,
            water_match="name" if slug_list else "none",
            started_at=iso(start), ended_at=iso(stop) if stop is not None else None,
            time_precision="minute" if isinstance(start, datetime) else "day",
            published_at=issued, source_updated_at=issued,
            material="sanitary sewage", volume_gal=gal, volume_text=r["estimated_volume"].strip() or None,
            estimate_flag=flag, authority=AUTHORITY, source_url=f"{report_url(year)}#page={page}",
            raw=raw,
        ))
    out.sort(key=lambda e: (e["started_at"], e["event_id"]), reverse=True)
    return out, counts


def listed_reports() -> dict[int, int]:
    resp = requests.get(INDEX_URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return {int(y): int(i) for i, y in LINK.findall(resp.text)}


def main(argv=None) -> int:
    meta = {"registry_ids": [REGISTRY_ID], "index": INDEX_URL, "reference": REFERENCE.name,
            "cadence": "yearly report, dated January 31 for the year before; the City's page is read each run"}
    if not REFERENCE.exists():
        write_events(SOURCE_ID, [], ok=False, error=f"missing {REFERENCE.name}", meta=meta)
        return 1
    try:
        records, counts = records_from(REFERENCE.read_text(), bangor_waters())
    except (KeyError, ValueError, csv.Error) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{REFERENCE.name} could not be read: {e}", meta=meta)
        print(f"{SOURCE_ID}: {REFERENCE.name} could not be read: {e}", file=sys.stderr)
        return 1
    meta["counts"] = counts
    try:
        listed = listed_reports()
        if not listed:          # a maintenance page, a challenge or a new link format: the check did not happen
            raise ValueError("the page lists no Annual Report on Compliance")
    except (requests.RequestException, ValueError) as e:
        meta["index_error"] = str(e)[:300]
        write_events(SOURCE_ID, records, ok=False, partial=True, error=f"the City's report page: {e}"[:300], meta=meta)
        print(f"{SOURCE_ID}: {len(records)} records; the City's report page was not read ({e})", file=sys.stderr)
        return 1
    unread = [{"year": y, "url": f"https://bangormaine.gov/DocumentCenter/View/{i}/"
                                 f"Annual-Report-on-Compliance-Calendar-Year-{y}",
               "why": "not transcribed" if y not in REPORTS else "its link changed"}
              for y, i in sorted(listed.items()) if REPORTS.get(y, (None,))[0] != i]
    meta["listed_reports"] = sorted(listed)
    meta["unread_reports"] = unread
    path = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} records -> {path}")
    for u in unread:
        print(f"  report to transcribe: {u['year']} ({u['why']}) {u['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
