"""City of Somerville's CSO discharge table -> data/build/events/ma-somerville-cso-table.json.

Source (registry ma-somerville-cso-table)
  The city's CSO page, https://www.somervillema.gov/cso (Drupal, served as plain HTML; HTTP 200 to the pipeline's own
  client on 2026-11-17). Two tables of one layout: "CSO Discharge Table" (2024 on) and, under the "Past CSO
  Activations" heading, the rows of 2021 to 2023. The first row of each is its header, in plain cells: CSO Number,
  Waterbody affected, Potentially Affected Area, Start Time, Stop Time, Duration, Volume (million gallons), Event
  Rainfall (inches). 2026-11-17: 32 rows, 2021-07-02 to 2026-07-22, all at SOM-001A on the Alewife Brook. The page
  says of the table: "their estimated discharge duration and volume. Data for CSOs is preliminary and subject to
  change."
  As written: dates as 7/22/2026 and 10/8/25, clocks as 4:25pm, 7:10 PM, 3:45 am, 8:15 A.M. and 0:55 am (just after
  midnight), line breaks and non-breaking spaces inside a cell; durations as "10 min", "1 hr 50 min", "275 min".
  Read: the cells of tables whose header names the columns above (the columns are found by name; a discharge table
  with a column renamed, added or dropped is a failed read), and three sentences of the page (the estimate and
  "preliminary" sentences, the public health warning). Nothing else: the page's contacts table (staff names,
  telephones, e-mail addresses) is never read, saved or logged, and the page itself is never saved (save_raw gets the
  parsed rows only). The headline over the page ("Combined Sewer Overflow (CSO) Event on <date> at <time> at SOM-001A
  on the Alewife Brook") and the vendor map in its frame are not read here.

Records (one cso record per table row; the shape of ingest.ma_massdep's)
  - source_record_id "<outfall>:<start, local YYYYMMDDTHHMM>" ("SOM001A:20260722T1625"); permit MA0101982, outfall_id
    SOM001A (the portal's spelling; raw.row.cso_number as written), discharger ma-somerville.
  - started_at and ended_at in America/New_York to the minute (the page states no zone); an hour that repeats when
    daylight time ends is read as its first occurrence. ended_at is the Stop Time as written; a stop that is missing,
    unreadable or before the start gives start plus the Duration instead (raw._ended_at_basis says which), else no end
    (status unknown, end not confirmed). Where the Duration and start-to-stop differ by more than DURATION_SLACK_MIN
    minutes (7/29/2023: 6:15 pm to 8:35 pm, "30 min"), the stop is kept (the later end) and raw._duration_check says so.
  - volume_gal from million gallons, exact (Decimal); volume_text "<cell> million gallons"; estimate_flag estimated,
    raw.volume_method the page's own estimate and "preliminary and subject to change" sentences. raw.rainfall_in the
    Event Rainfall cell as written.
  - published_at is the first read that saw the row (the page gives no posting time). Rows already on the page at the
    feed's first read keep published_at null (raw._on_page_at_first_read): that read is not when they were posted.
    reported_at and source_updated_at null; fetched_at and raw._last_seen_in_source the latest read that listed it.
  - advice_text the page's public health warning, quoted, with no window (its hours count from the end of a rainstorm,
    not of the discharge).
  - Place: ingest.mail.ma_common.place (the MassDEP CSOs layer as ma_massdep last cached it, the ECHO outfall registry,
    the portal waterbody crosswalk), as the city's e-mail notices are placed.

One event, not two (operator_mail.link_portal, the e-mail notices' rule)
  MassDEP's portal holds Somerville's notices and Verified Data Reports of the same overflows. A row and the portal's
  record of the same overflow (same permit and outfall number, starts within 3 hours) are one event: the row becomes
  duplicate_of the family's shown record (its Verified Data Report once filed), one to one, closest first. A row the
  portal lacks (before the portal's first day, 2022-07-06, or not filed) stands alone; one whose nearest portal record
  of the outfall starts within NEAR_HOURS but outside the link window names it in raw._portal_nearest, for review.
  This module sorts after ma_massdep and reads its events file of the same run; when that file is missing or holds
  nothing for the permit, the previous run's links are kept (meta.links.portal says so), so a missing file never
  turns every row into a second count.

State: data/build/ma-somerville-cso-table-state.json keeps every row read (its cells, first and last seen, earlier
  versions of its cells): a row taken off the page stays a past report (raw._missing_from_source_since). Do not
  delete it; without it the next read is a new first read.
Failures: a failed request or a page without a discharge table is a failed read: ok=False, the previous records kept,
  the state unchanged. A row whose CSO number or start is not read (or with merged cells) is named in the error and
  health stays false (partial) until a rule reads it; the readable rows are published.
Run from pipeline/: python -m ingest.ma_somerville_cso [--file saved.html --out events.json]
Cadence: hourly with the refresh (Massachusetts is live).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, end_after, event, now_iso, read_json, save_raw, scrub_text,
                    write_events, write_json)

SOURCE_ID = "ma-somerville-cso-table"
URL = "https://www.somervillema.gov/cso"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
PERMIT = "MA0101982"
DISCHARGER_ID = "ma-somerville"            # data/dischargers.json
DISCHARGER = "City of Somerville"
CREDIT = "City of Somerville, CSO discharge table"
PORTAL_SOURCE = "ma-massdep"
STATE_PATH = BUILD_DIR / "ma-somerville-cso-table-state.json"
SPEC = {"source_id": SOURCE_ID, "outfall_prefix": "SOM", "town": "SOMERVILLE"}      # ma_common.place's lookups
DURATION_SLACK_MIN = 5          # a stated duration this close to start-to-stop agrees with it
NEAR_HOURS = 36                 # an unlinked row names a portal record of its outfall this close (for review)
MAX_REVISIONS = 20

# the header's cell text (lower case, spaces collapsed) -> the row's field
COLUMNS = {
    "cso number": "cso_number",
    "waterbody affected": "waterbody",
    "potentially affected area": "affected_area",
    "start time": "start",
    "stop time": "stop",
    "duration": "duration",
    "volume (million gallons)": "volume_mg",
    "event rainfall (inches)": "rainfall_in",
}

TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table\s*>", re.S | re.I)
ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.S | re.I)
CELL_RE = re.compile(r"<t([dh])\b([^>]*)>(.*?)</t\1\s*>", re.S | re.I)
HEADING_RE = re.compile(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>", re.S | re.I)
CSO_NO = re.compile(r"(?i)^SOM[\s_-]*0*(\d{1,3})\s*([A-Z]?)$")
STAMP = re.compile(r"(?i)^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\s*,?\s*(?:at\s+)?(\d{1,2}):(\d{2})\s*(?:([ap])\.?\s*m\.?)?$")
DUR_PART = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)(?![a-z])")
PLAIN_NUMBER = re.compile(r"^\d*\.?\d+$")
# the page's own sentences (each within one block of the page's text)
ESTIMATE_RE = re.compile(r"(?i)([^.\n]{0,200}\bestimated discharge duration and volume[^.\n]{0,100}\.)")
PRELIM_RE = re.compile(r"(?i)([^.\n]{0,200}\bpreliminary and subject to change[^.\n]{0,100}\.)")
WARNING_RE = re.compile(r"(?i)(Public health officials recommend avoiding contact with water bodies[^.\n]{0,300}\.)")


class LayoutError(Exception):
    pass


# ---------------------------------------------------------------- reading the page

def cell_text(fragment: str) -> str:
    """A cell's text: line breaks and tags become spaces, entities are decoded, spaces collapsed."""
    s = re.sub(r"(?i)<br\s*/?>", " ", fragment)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(html.unescape(s).replace("\xa0", " ").split())


def page_text(page: str) -> str:
    """The page's text, one line per block (heading, paragraph, cell), so a sentence never runs into a heading."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", page)
    s = re.sub(r"(?i)<br\s*/?>|</(?:h[1-6]|p|div|li|td|th|tr|table)\s*>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    return "\n".join(" ".join(line.split()) for line in s.split("\n") if line.strip())


def sentence(rx: re.Pattern, text: str) -> str | None:
    m = rx.search(text)
    return " ".join(m.group(1).split()).strip() if m else None


def parse(page: str) -> tuple[list[dict], list[str], dict]:
    """(rows, unread, page facts). rows: {"table", "cells"} for each data row of each discharge table, in page order.
    unread: the rows that cannot be read as one row of the header's columns (named by table and row number).
    Raises LayoutError when the page holds no discharge table, or one whose columns changed."""
    rows, unread, tables = [], [], []
    for tm in TABLE_RE.finditer(page):
        trs = ROW_RE.findall(tm.group(1))
        if not trs:
            continue
        header = [cell_text(c[2]).lower() for c in CELL_RE.findall(trs[0])]
        if not (any("start" in h for h in header) and any("cso" in h or "volume" in h for h in header)):
            continue                    # not a discharge table (the contacts table, layout tables)
        if sorted(header) != sorted(COLUMNS) or len(header) != len(COLUMNS):
            raise LayoutError(f"a discharge table's columns changed: {header}")
        heads = HEADING_RE.findall(page[:tm.start()])
        name = cell_text(heads[-1]) if heads else "discharge table"
        tables.append(name)
        fields = [COLUMNS[h] for h in header]
        for i, tr in enumerate(trs[1:], start=1):
            cells = CELL_RE.findall(tr)
            texts = [cell_text(c[2]) for c in cells]
            if not any(texts):
                continue                # a blank row
            if len(cells) != len(fields) or any(re.search(r"(?i)\b(?:col|row)span\s*=", c[1]) for c in cells):
                unread.append(f"{name} row {i}: {len(cells)} cells, not one per column")
                continue
            rows.append({"table": name, "cells": dict(zip(fields, texts))})
    if not tables:
        raise LayoutError("no CSO discharge table (a header with CSO Number and Start Time) on the page")
    text = page_text(page)
    facts = {"tables": tables, "estimate_sentence": sentence(ESTIMATE_RE, text),
             "preliminary_sentence": sentence(PRELIM_RE, text), "warning": sentence(WARNING_RE, text)}
    return rows, unread, facts


# ---------------------------------------------------------------- cells

def parse_stamp(text: str | None) -> tuple[datetime | None, str | None]:
    """'7/22/2026 4:25pm', '10/8/25 8:55 AM', '8/15/2022 8:15 A.M.', '5/21/2023 0:55 am' -> local datetime. A clock
    without am or pm is read only when it cannot be a 12-hour time (0:xx, 13:xx to 23:xx)."""
    t = " ".join((text or "").split())
    m = STAMP.match(t)
    if not m:
        return None, f"{t!r} is not a date and time"
    mo, d, y, hh, mm, ap = m.groups()
    year, h, mi = int(y), int(hh), int(mm)
    year += 2000 if year < 100 else 0
    if mi > 59:
        return None, f"{t!r}: minutes out of range"
    if ap:
        if h == 0 and ap.lower() == "a":
            pass                        # "0:55 am": the midnight hour, as the 24-hour clock writes it
        elif 1 <= h <= 12:
            h = h % 12 + (12 if ap.lower() == "p" else 0)
        else:
            return None, f"{t!r}: hour out of range for {ap.upper()}M"
    elif not (h == 0 or 13 <= h <= 23):
        return None, f"{t!r}: no AM or PM"
    try:
        return datetime(year, int(mo), int(d), h, mi, tzinfo=TZ), None
    except ValueError:
        return None, f"{t!r} is not a valid date"


def parse_duration(text: str | None) -> int | None:
    """'10 min', '1 hr 50 min', '275 min', '2 hours' -> minutes; anything else None."""
    t = " ".join((text or "").split())
    parts = DUR_PART.findall(t)
    if not parts or re.sub(r"(?i)\band\b|[\s,]", "", DUR_PART.sub("", t)):
        return None
    return int(round(sum(float(n) * (60 if u.lower().startswith("h") else 1) for n, u in parts)))


def gallons(text: str | None) -> int | None:
    """A Volume (million gallons) cell -> whole gallons, exactly (0.57 is 570,000, never 569,999)."""
    t = (text or "").replace(",", "").strip()
    if not PLAIN_NUMBER.match(t):
        return None
    return int((Decimal(t) * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def outfall_of(text: str | None) -> tuple[int, str] | None:
    m = CSO_NO.match(" ".join((text or "").split()))
    return (int(m.group(1)), m.group(2).upper()) if m else None


def row_key(cells: dict) -> tuple[str | None, str | None]:
    """(source_record_id, problem): "SOM001A:20260722T1625" from the CSO number and the start."""
    of = outfall_of(cells.get("cso_number"))
    if of is None:
        return None, f"CSO number {cells.get('cso_number')!r} not read"
    start, why = parse_stamp(cells.get("start"))
    if start is None:
        return None, f"start time: {why}"
    return f"SOM{of[0]:03d}{of[1]}:{start:%Y%m%dT%H%M}", None


def minutes_between(a: datetime, b: datetime) -> int:
    return int((b.astimezone(UTC) - a.astimezone(UTC)).total_seconds() // 60)


# ---------------------------------------------------------------- state

def merge(rows: list[dict], state: dict, now: str) -> tuple[dict, list[str], int]:
    """Fold this read's rows into the state. Returns (the rows of this read by key, unread, repeated rows)."""
    held = state.setdefault("rows", {})
    state.setdefault("first_read_at", now)
    seen, unread, repeated = {}, [], 0
    for r in rows:
        key, why = row_key(r["cells"])
        if key is None:
            unread.append(f"{r['table']}: {why}")
            continue
        if key in seen:
            if seen[key]["cells"] == r["cells"]:
                repeated += 1
                continue
            n = 2
            while f"{key}:{n}" in seen:
                n += 1
            key = f"{key}:{n}"          # two different rows with one outfall and start: both kept
        seen[key] = r
    for key, r in seen.items():
        prev = held.get(key)
        if prev is None:
            held[key] = {"table": r["table"], "cells": r["cells"], "first_seen_at": now, "last_seen_at": now}
            continue
        if prev["cells"] != r["cells"]:
            revs = prev.setdefault("revisions", [])
            revs.append({"cells": prev["cells"], "first_seen_at": prev.get("cells_since") or prev["first_seen_at"],
                         "last_seen_at": prev["last_seen_at"]})
            del revs[:-MAX_REVISIONS]
            prev["cells"], prev["cells_since"] = r["cells"], now
        prev["table"], prev["last_seen_at"] = r["table"], now
        prev.pop("missing_since", None)
    for key, h in held.items():
        if key not in seen:
            h.setdefault("missing_since", now)
    state["last_read"] = {"at": now, "rows": len(rows), "keys": len(seen), "unread": len(unread), "repeated": repeated}
    return seen, unread, repeated


# ---------------------------------------------------------------- records

def to_record(key: str, h: dict, facts: dict, ctx: dict, first_read_at: str | None) -> dict:
    from ingest.mail.ma_common import place
    cells = h["cells"]
    num, suffix = outfall_of(cells.get("cso_number"))
    start, _ = parse_stamp(cells.get("start"))
    problems = []
    raw = {"row": {k: scrub_text(v) for k, v in cells.items()}, "table": h.get("table"), "state": "MA",
           "time_zone": TZ_NAME,
           "time_note": ("the table's local clock, read as Eastern time (America/New_York): the page states no zone"),
           "_first_seen_at": h["first_seen_at"], "_last_seen_in_source": h["last_seen_at"],
           "_outfall_key": num, "_outfall_suffix": suffix, "_channel": "web"}
    if h.get("missing_since"):
        raw["_missing_from_source_since"] = h["missing_since"]
    if h.get("revisions"):
        raw["revisions"] = [{"cells": {k: scrub_text(v) for k, v in rv["cells"].items()},
                             "first_seen_at": rv["first_seen_at"], "last_seen_at": rv["last_seen_at"]}
                            for rv in h["revisions"]]
    published = h["first_seen_at"]
    if first_read_at and h["first_seen_at"] == first_read_at:
        published = None
        raw["_on_page_at_first_read"] = (f"on the page at the feed's first read ({first_read_at}): posted before it, "
                                         "at a time the page does not give")

    stop, stop_why = parse_stamp(cells.get("stop")) if cells.get("stop") else (None, None)
    dur = parse_duration(cells.get("duration"))
    raw["duration_min"] = dur
    if cells.get("duration") and dur is None:
        problems.append(f"duration {cells['duration']!r} not read")
    if stop_why:
        problems.append(f"stop time: {stop_why}")
    end = None
    if stop is not None and stop >= start:
        end = stop
        raw["_ended_at_basis"] = "the table's stop time"
        span = minutes_between(start, stop)
        if dur is not None and abs(span - dur) > DURATION_SLACK_MIN:
            raw["_duration_check"] = (f"the table's duration ({cells['duration']}) differs from start to stop "
                                      f"({span} min); the stop time is kept as written (the later end)"
                                      if span > dur else
                                      f"the table's duration ({cells['duration']}) is longer than start to stop "
                                      f"({span} min); the stop time is kept as written")
    else:
        if stop is not None:
            problems.append("stop time before the start time")
        if dur is not None:
            end, basis = end_after(start, timedelta(minutes=dur), "minute")
            raw["_ended_at_basis"] = (f"{basis}: the start plus the table's duration ({cells['duration']}), since the "
                                      f"stop time is {'before the start' if stop is not None else 'missing or not read'}")
    if end is None:
        raw["_end_note"] = "the table gives no readable stop time or duration: end not confirmed"

    vol_cell = cells.get("volume_mg") or ""
    gal = gallons(vol_cell)
    if vol_cell and gal is None:
        problems.append(f"volume {vol_cell!r} not read as million gallons")
    volume_text = f"{vol_cell} million gallons" if gal is not None else (scrub_text(vol_cell) or None)
    method = " ".join(f"“{s}”" for s in (facts.get("estimate_sentence"), facts.get("preliminary_sentence")) if s)
    if volume_text:
        raw["volume_method"] = (f"the city's table: {method}" if method
                                else "the city's table (it calls its volumes estimated)")
    raw["rainfall_in"] = cells.get("rainfall_in") or None

    lay, echo, slugs, wmatch, wnote = place(ctx, SPEC, PERMIT, num, suffix, cells.get("waterbody") or None)
    if wnote:
        raw["_water"] = wnote
    lat = lon = coord_source = None
    if lay and lay.get("lat") is not None:
        lat, lon, coord_source = round(lay["lat"], 6), round(lay["lon"], 6), "outfall_layer"
        raw["_coords"] = f"MassDEP CSOs layer DEP_OUTFL_ {lay['dep_id']} (locations are estimates)"
    elif echo and echo.get("lat") is not None:
        lat, lon, coord_source = echo["lat"], echo["lon"], "outfall_layer"
        raw["_coords"] = f"EPA ECHO CSO inventory {echo['npdes_permit']} outfall {echo['outfall']}"

    warning = facts.get("warning")
    iso = lambda d: d.isoformat(timespec="seconds") if d else None      # noqa: E731
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status="ended" if end else "unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=PERMIT,
        outfall_id=f"SOM{num:03d}{suffix}", outfall_name=(lay or {}).get("address"),
        waterbody_text=scrub_text(cells.get("waterbody") or "") or None, water_slugs=slugs, water_match=wmatch,
        lat=lat, lon=lon, coord_source=coord_source,
        started_at=iso(start), ended_at=iso(end), time_precision="minute",
        reported_at=None, published_at=published, source_updated_at=None, fetched_at=h["last_seen_at"],
        volume_gal=gal, volume_text=volume_text, estimate_flag="estimated" if gal is not None else "unknown",
        authority=CREDIT,
        advice_text=warning, advice_window_hours=None,
        advice_window_basis=("the city's public health warning on its CSO page (its hours count from the end of a "
                             "rainstorm, not of the discharge)") if warning else None,
        source_url=URL, raw=raw, parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- one event, not two

def read_portal(events_dir: Path) -> list[dict] | None:
    """MassDEP's records of Somerville's permit from this run's ma-massdep events file; None when there are none."""
    doc = read_json(events_dir / f"{PORTAL_SOURCE}.json", {}) or {}
    recs = [r for r in doc.get("records") or [] if isinstance(r, dict) and r.get("npdes_permit") == PERMIT]
    return recs or None


def link(records: list[dict], portal: list[dict] | None, previous: dict) -> dict:
    """Each row to MassDEP's record of the same overflow (operator_mail.link_portal: same permit and outfall number,
    starts within 3 hours, one to one, to the family's shown record). portal None: the previous run's links."""
    from ingest import operator_mail as O
    for r in records:
        r["duplicate_of"] = None
        r["raw"].pop("_link_basis", None)
        r["raw"].pop("_portal_nearest", None)
    if portal is None:
        kept = 0
        for r in records:
            p = previous.get(r["event_id"]) or {}
            if p.get("duplicate_of"):
                r["duplicate_of"] = p["duplicate_of"]
                r["raw"]["_link_basis"] = p.get("_link_basis")
                kept += 1
        return {"portal": "the ma-massdep events file holds no record of the permit this run: the previous links kept",
                "linked_to_portal": kept, "standing_alone": len(records) - kept}
    for r in records:
        r["raw"]["_chain"] = r["event_id"]
    n = O.link_portal(records, portal, PERMIT)
    for r in records:
        r["raw"].pop("_chain", None)
    fams = O.portal_families(portal, PERMIT)
    near = 0
    for r in records:
        s = O.parse_iso(r.get("started_at"))
        if r["duplicate_of"] or s is None:
            continue
        cands = [(abs((f["start"] - s).total_seconds()), f) for f in fams if f["num"] == r["raw"].get("_outfall_key")]
        cands = [c for c in cands if c[0] <= NEAR_HOURS * 3600]
        if cands:
            gap, f = min(cands, key=lambda c: (c[0], c[1]["root"]))
            r["raw"]["_portal_nearest"] = {
                "record": f["target"]["event_id"], "starts_hours_apart": round(gap / 3600, 1),
                "why_not_linked": "more than 3 hours apart, or that overflow is linked to a closer row"}
            near += 1
    return {"portal": f"{len(portal)} records of {PERMIT}", "linked_to_portal": n,
            "standing_alone": len(records) - n, "near_portal_record": near}


# ---------------------------------------------------------------- run

def run(page: str, now: str, state_path: Path = STATE_PATH, events_dir: Path = EVENTS_DIR,
        out: Path | None = None, ctx: dict | None = None) -> tuple[int, list[dict], dict]:
    """Read one page into the state and write the events file. Returns (exit code, records, meta)."""
    out = out or events_dir / f"{SOURCE_ID}.json"
    try:
        rows, unread, facts = parse(page)
    except LayoutError as e:
        write_events(SOURCE_ID, [], ok=False, error=f"page: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1, [], {}
    state = read_json(state_path, {}) or {}
    seen, bad, repeated = merge(rows, state, now)
    unread += bad
    write_json(state_path, state)
    if ctx is None:
        from ingest import operator_mail as O
        ctx = O.ma_context({"somerville": SPEC})
    recs = [to_record(k, h, facts, ctx, state.get("first_read_at")) for k, h in state["rows"].items()]
    previous = {r.get("event_id"): {"duplicate_of": r.get("duplicate_of"), "_link_basis": (r.get("raw") or {}).get("_link_basis")}
                for r in (read_json(out, {}) or {}).get("records") or [] if isinstance(r, dict)}
    links = link(recs, read_portal(events_dir), previous)
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "credit": CREDIT, "tables": facts["tables"],
            "rows_read": len(rows), "rows_held": len(state["rows"]), "repeated_rows": repeated,
            "missing_from_source": sum(1 for h in state["rows"].values() if h.get("missing_since")),
            "first_read_at": state.get("first_read_at"), "links": links,
            "estimate_wording": " ".join(s for s in (facts.get("estimate_sentence"), facts.get("preliminary_sentence")) if s) or None,
            "time_note": "the table's times have no zone; read as America/New_York",
            "covers_permits": [PERMIT], "statewide": False}
    if unread:
        meta["unread"] = unread
        write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta, path=out,
                     error="rows not read: " + "; ".join(unread))
        print(f"{SOURCE_ID}: PARTIAL {len(recs)} records; not read: {unread}", file=sys.stderr)
        return 1, recs, meta
    write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records from {len(rows)} rows; {links['linked_to_portal']} linked to the portal, "
          f"{links['standing_alone']} standing alone -> {out}")
    return 0, recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--file", help="a saved copy of the page (no request)")
    ap.add_argument("--out", help="events file to write (needed with --file; its state sits beside it)")
    a = ap.parse_args(argv)
    if a.file and not a.out:
        ap.error("--file needs --out")
    now = now_iso()
    out = Path(a.out) if a.out else None
    if a.file:
        page = Path(a.file).read_text(errors="replace")
    else:
        try:
            r = requests.get(URL, headers=HEADERS, timeout=(20, 90))
            r.raise_for_status()
            page = r.text
        except requests.RequestException as e:
            write_events(SOURCE_ID, [], ok=False, error=f"page: {type(e).__name__}: {e}")
            print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
            return 1
    state_path = out.with_suffix(".state.json") if out else STATE_PATH
    code, recs, meta = run(page, now, state_path=state_path, out=out)
    if not a.file and meta:
        rows = [{"table": h["table"], "cells": h["cells"]} for h in (read_json(state_path, {}) or {}).get("rows", {}).values()
                if h.get("last_seen_at") == now]
        save_raw(SOURCE_ID, json.dumps(rows, ensure_ascii=False), "json")     # the parsed rows only, never the page
    return code


if __name__ == "__main__":
    sys.exit(main())
