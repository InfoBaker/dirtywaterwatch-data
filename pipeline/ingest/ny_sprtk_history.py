"""DEC Sewage Pollution Right to Know workbook, 2013 to August 2021 (New York) -> data/build/events/ny-dec-sprtk-2013-2021.json

Source
  NYS DEC's older SPRTK workbook, https://extapps.dec.ny.gov/fs/data/Sewage_Discharge_Reports.xlsx (the www.dec.ny.gov
  address 301s there), linked from the SPRTK page. DEC last changed it on 2023-07-11 (Last-Modified; 3,809,544 bytes
  when read on 2026-11-22). It holds 54 tabs and 31,660 rows: the written discharge reports of 2013 to May 2015, the
  NY-Alert notices of late 2015 to May 2016, and one tab per month or batch of NY-Alert notices from May 2016 to August
  2021. No notification ids and no posting times. The newer workbook, SPRTK_Data.xlsx (January 2021 on), is read by
  ingest/ny_sprtk.py (source ny-dec-sprtk); this module reuses its reader, field names, clocks (resolve), chains,
  record builder, water placement and volume rules. DEC's caveat: "Data quality is not checked by DEC". Credit: "NYS
  DEC Sewage Pollution Right to Know (Sewage_Discharge_Reports.xlsx)". No licence stated.

Layouts (LAYOUTS: each tab's header row is matched to one; a tab whose header matches none fails the read)
  report   "PDFs through May 2015": the written reports of 2013 to May 2015 as DEC transcribed them: discovery time,
           facility, closest address or landmark, volume with "Estimate", "Actual" or "Unknown", ending time, expected
           ending time, duration, corrective actions, receiving water, reason. A title row comes before the header.
  alert15  "NYAlerts Through 5_10_16": NY-Alert notices of late 2015 to May 2016. The date and the time are separate
           columns (dates as Excel serials, MM/DD/YYYY or "April 6, 2016"); the duration carries the notifier's word
           ("2.0 hours ended.", "ongoing.", "unknown."); the treated state and the steps taken sit in two unnamed
           columns past the header (col15, col16); older rows put the volume under "Description". A title row comes
           before the header. 35 rows carry only a date, a time and a cut fragment of text (no facility); they are
           kept, with a parse_error saying so.
  alert16  May 2016 to June 13, 2018 (snake_case headers: start_time, affectd_water_body, estimated_ind, up to three
           reasons): the start as ISO (the first tab) or DD/MON/YYYY, the duration in hours, the quantity with its
           units and an estimated flag (1 is read as "Estimated", 0 as "Actual", NY-Alert's two choices).
  alert18  June 13, 2018 to August 2021 (headers "start time", "headline", "units" and unnamed columns): DD/MON/YYYY
           starts (Excel serials in the January 2019 tab), the duration with its units, "address" the street number
           and the unnamed column after it the street name, the quantity with its units (col15) and "Estimated" or
           "Actual", up to three reasons. Later notices of a discharge open their headline with "UPDATE:" or
           "ENDED:". The August 2021 tab has no header row (its first row is data): it is read with the columns of
           the tab before it.

Times (raw._time_basis; raw._start_stored keeps the stored value)
  - alert18 tabs store New York local time shifted back by the UTC offset: local = stored + 4 h (EDT) or 5 h (EST),
    ny_sprtk.resolve's DD/MON rule. Evidence: the 40 notices in both June 2018 tabs (the last alert16 tab and the
    first alert18 tab) are stored exactly 4 hours earlier in the alert18 tab; times written in the notices' own text
    agree ("December 21, 2018 at around 9:15 AM" stored as 04:15 EST, "July 21, 2018 at 2pm" stored as 10:00 EDT);
    stored start hours peak at 03:00-04:00, where the local tabs peak at 07:00-08:00. The newer workbook's copy of
    the May 2021 notices (tab "May _website", Excel serials) holds the same stored values (485 pairs, no offset), and
    its January-August 2021 tabs give dates only, which follow the stored date, not the local one: of 347 notices
    stored at 19:00 or later and matched to one date there, 244 carry the stored date and 24 the next day.
  - alert16 tabs (and their two Excel serials) store local time: times written in the notices' text equal the stored
    time ("This event started at 3:25 PM" stored 15:25 EDT; "at 2:55pm" stored 14:55 EST), and the same notices are
    4 hours later than in the alert18 tab (above).
  - report and alert15 tabs: local time as the facility typed it (inferred; there is no other copy to compare). The
    report tab gives the discovery time, used as the start (raw._start_basis says so).
  - A date with no time, or a time of day that cannot be read, is day precision (the problem is noted). A start
    before May 1, 2013, when reporting under the Sewage Pollution Right to Know Act began (the report tab's first
    discovery date), is a typing error (one row, "1982-06-08" in the May 2016-May 2017 tab): it is not used
    (raw._start_not_used) and the record is kept with no start. No row gives a posting time: reported_at and
    published_at stay empty.
  - A start more than a year before its tab's month (a "November 2018" tab row starting 17/NOV/2014), or more than a
    month after it, is kept as written with raw._dww_note: a typing error in the year or a long-running discharge,
    which the file does not settle.

Status, end and volume (ny_sprtk.to_record)
  - alert18: the headline's opening word gives the kind of notice (raw._notice_kind): "ENDED:" is the closing notice
    (status ended, no end time given), "UPDATE:" an update, no word the first notice (status unknown). alert15:
    "hours ended." or "Discharge ended before discovery" is ended, "hours ongoing." ongoing, anything else unknown.
    report: an ending time makes the report ended at that time (ended_at), unless it is before the start; the
    expected ending time is a projection (raw._projected_end). alert16: no kind and no state, so unknown.
  - The duration is the notifier's (raw._duration_text: "24 Hours", "1.0 hours ended.", "1:30"). No end time is ever
    computed from it.
  - Volume: the quantity with its units and estimate word ("65 Gallons per Minute Estimated"), read by
    ny_sprtk.volume_of: a rate keeps its text with no gallons; a first notice's figure is an estimate. The report
    tab's volume has no unit and is read as gallons (noted).

Ids and chains
  - No notification ids: the record id is "h" plus a hash of the row's own fields (stable while the file does not
    change; raw._id_note). A row that repeats another row exactly, in the same tab or another, is the same notice: one
    record, with raw._copies naming the other places (meta.identical_rows).
  - Chains by facility + address + start minute (ny_sprtk.build_chains, with its edited-start merge); within a chain
    parent_event_id is the notice before, so the chain's latest notice is its live record.

Overlap with the newer workbook (link_copies; re-made on every run)
  A notice also in SPRTK_Data.xlsx stays in ny-dec-sprtk (data/build/events/ny-dec-sprtk.json, written first in the
  sorted ingest loop). This record is kept with duplicate_of that feed's event id (raw._duplicate_basis) only on strict
  identity: the same facility (permit or name), the same start (the same minute, or the same date where one side has
  the date only; the newer workbook's 2021 dates follow the stored clock, so the stored date counts too), and the
  same water (name or mapped water) or headline, paired one to one (address, notice kind and volume decide between
  several). A weaker match, the same facility and start with another or no water, the same facility, water and date
  with another start time, or a strict match whose partner is taken, gets raw._possible_copy_of {event_id, reason}
  and both are listed. No record is ever dropped; a record of an earlier read that leaves the file keeps its record
  with raw._missing_from_workbook_since.

Privacy
  The free-text columns (reason description, discharge description, additional instructions, location description,
  corrective actions) can carry names and phone numbers. Every raw goes through common.strip_personal (in
  common.event), as in ny_sprtk, and the records through build.redact before they are written (names in free text
  anywhere, phone numbers in the top-level fields too). The saved raw page (data/raw/ny-dec-sprtk-2013-2021/) holds
  the rows after common.strip_personal, never the workbook. tests/test_ny_sprtk_history.py proves that a planted name
  and phone number reach neither.

Reading (each run)
  The workbook is history. A run asks for it at most once every REREAD_DAYS (7) days, with If-Modified-Since (state in
  data/build/ny-sprtk-history-state.json); between reads and on a 304 the records are kept as they are and only the
  links to the newer workbook are made again. DEC first (extapps, then www), then the latest Internet Archive capture
  when DEC does not answer, as ny_sprtk does (a capture whose original Last-Modified is the one already read counts as
  unchanged). A read that fails keeps the previous records (write_events ok false, exit 1): no answer, a workbook part
  that fails its zip checksum or a sheet whose XML ends early (a file cut short), fewer tabs than the last read, fewer
  rows in a tab than the last read, or a tab in no known layout. A read takes about a minute, most of it the shared
  redaction (the refresh caps each feed at 600 seconds). meta.frozen is true (the status build never calls the feed
  stale for its age, only for a failed read) and meta.statewide false (history covers no water now). `--backfill`
  reads now, without the weekly wait or If-Modified-Since, and otherwise behaves the same: every read takes every row.

Run from pipeline/:  python -m ingest.ny_sprtk_history [--file Sewage_Discharge_Reports.xlsx] [--backfill]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, error_detail, error_text, now_iso, path_notes_to_meta,
                    read_json, save_raw, strip_personal, write_events, write_json)
from ingest import ny_sprtk as S

SOURCE_ID = "ny-dec-sprtk-2013-2021"
DEC_URLS = ["https://extapps.dec.ny.gov/fs/data/Sewage_Discharge_Reports.xlsx",
            "https://www.dec.ny.gov/fs/data/Sewage_Discharge_Reports.xlsx"]
ARCHIVE_URL = "https://web.archive.org/web/{ts}id_/https://www.dec.ny.gov/fs/data/Sewage_Discharge_Reports.xlsx"
SOURCE_URL = DEC_URLS[0]
PAGE_URL = S.PAGE_URL
STATE_FILE = BUILD_DIR / "ny-sprtk-history-state.json"
LIVE_EVENTS = EVENTS_DIR / f"{S.SOURCE_ID}.json"
REREAD_DAYS = 7
CREDIT = "NYS DEC Sewage Pollution Right to Know (Sewage_Discharge_Reports.xlsx), 2013 to August 2021"
CAVEAT = "Data quality is not checked by DEC (SPRTK page)."
ID_NOTE = "the workbook has no notification ids; the record id is a hash of the row's own fields"
# reporting under the Sewage Pollution Right to Know Act began on May 1, 2013 (the report tab's first discovery date):
# an earlier start is a typing error and is not used
EARLIEST_START = datetime(2013, 5, 1)
START_NOT_USED = "before May 1, 2013, when reporting under the Sewage Pollution Right to Know Act began: a typing error"

# the clock of each layout (docstring "Times") and its words in raw._time_basis
CLOCK = {"report": "local_typed", "alert15": "local_typed", "alert16": "local", "alert18": "shifted"}
BASIS_TEXT = {
    "shifted": ("New York local time shifted back by the UTC offset in the workbook (the same notices are stored 4 hours "
                "earlier than in the June 1-13, 2018 tab, and times written in the notices agree); read as stored + "
                "4 h (EDT) or 5 h (EST), America/New_York"),
    "local": ("New York local time in the workbook (times written in the notices' own text match the stored times); "
              "read as America/New_York"),
    "local_typed": "local time as the facility typed it (inferred: no other copy to compare); read as America/New_York",
    "date": "date only in the workbook (no time of day)",
}
START_BASIS_REPORT = ("the written report gives the discovery time, used here as the start; the discharge may have "
                      "begun earlier")

# header (lowercased, non-alphanumerics removed) -> field, per layout. ny_sprtk's names where it has one; a name with
# "_" is composed below (quantity, duration, reasons, the notice kind) and never kept as a field of its own
LAYOUTS = {
    "report": {
        "discoverydateandtime": "_start", "facilityname": "facilityName", "closestaddressorlandmark": "streetName",
        "towncity": "city", "county": "countyName", "estimateoractual": "_estimate", "volume": "_quantity",
        "treatedstate": "treatedState", "otherexplained": "dischargeDescription", "endingdateandtime": "_end",
        "expectedendingdateandtime": "_expected_end", "durationhoursandminutes": "_duration",
        "correctiveactions": "stepsToContain", "receivingwaterbody": "receivingWaterBody",
        "reasonfordischarge": "_reason1", "otherexplanation": "reasonDescription",
    },
    "alert15": {
        "organizationfacility": "facilityName", "facilityid": "facilityId", "dateofdischarge": "_date",
        "timeofdischarge": "_time", "locationofdischarge": "streetName", "additionaladdressinfo": "addressDescription",
        "nameofwaterbodyaffected": "receivingWaterBody", "descriptionofdischarge": "dischargeDescription",
        "durationofdischarge": "_duration", "reasonfordischarge": "_reason1", "description": "reasonDescription",
        "volumeorrateofdischarge": "_quantity", "units": "_quantity_units", "estimateactual": "_estimate",
        "col15": "treatedState", "col16": "stepsToContain",
    },
    "alert16": {
        "facilityname": "facilityName", "sprtkid": "facilityId", "starttime": "startDateTime",
        "duration": "_duration_hours", "address": "streetName", "city": "city", "zipcode": "_zip",
        "locationdesc": "addressDescription", "affectdwaterbody": "receivingWaterBody",
        "affectedwaterbody": "receivingWaterBody", "treatedstate": "treatedState", "quantity": "_quantity",
        "volumerateunits": "_quantity_units", "estimatedind": "_estimated_ind",
        "reasonfordischarge": "_reason1", "reasonfordischarge1": "_reason1", "reasonfordischarge2": "_reason2",
        "reasonfordischarge3": "_reason3", "reasondescription": "_rdesc1", "reasondescription1": "_rdesc1",
        "reasondescription2": "_rdesc2", "reasondescription3": "_rdesc3", "dischargedesc": "dischargeDescription",
        "additionalinstrctns": "additionalInstructions", "additionalinstructions": "additionalInstructions",
    },
    "alert18": {
        "facilityname": "facilityName", "sprtkid": "facilityId", "starttime": "startDateTime", "headline": "headline",
        "duration": "_duration", "units": "_duration_units", "address": "streetNumber", "col8": "streetName",
        "city": "city", "county": "countyName", "locationdescription": "addressDescription",
        "affectedwaterbody": "receivingWaterBody", "treatedstate": "treatedState", "quantity": "_quantity",
        "col15": "_quantity_units", "estimatedindicator": "_estimate", "reasonsfordischarge": "_reason1",
        "col18": "_reason2", "col19": "_reason3", "reasondescription": "reasonDescription",
        "dischargedescription": "dischargeDescription", "additionalinstrctions": "additionalInstructions",
        "additionalinstructions": "additionalInstructions",
    },
}
HEADLINE_WORD = re.compile(r"^\s*(ENDED|UPDATED|UPDATE)\s*:", re.I)
KIND_OF_WORD = {"ENDED": "Close", "UPDATE": "Update", "UPDATED": "Update"}
KIND_TEXT = {"New": "first notice of the discharge", "Update": "update", "Close": "closing notice (the discharge ended)"}
JUNK_TIME = re.compile(r"#VALUE!|0|:\d{0,2}|:\s*[AP]M|n/?a|none|null", re.I)
VOLUME_TEXT = re.compile(r"^\s*[\d,.]+\s*(?:'s\s*)?(?:gallons?|gal\b|mgd\b|gpm\b|million)", re.I)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def clean(v) -> str | None:
    s = " ".join(str(v).split()) if v is not None else ""
    return s or None


# ---------------------------------------------------------------- the workbook

def detect_layout(cells) -> str | None:
    keys = {norm_header(c) for c in cells if c}
    if "discoverydateandtime" in keys:
        return "report"
    if "dateofdischarge" in keys:
        return "alert15"
    if "starttime" in keys and "headline" in keys:
        return "alert18"
    if "starttime" in keys and keys & {"affectdwaterbody", "estimatedind", "volumerateunits"}:
        return "alert16"
    return None


def tab_period(name: str, year_before: int | None) -> tuple[date | None, date | None, int | None]:
    """(first day, last day, last year) of the months a tab's name gives ("NYALERTS NOVEMBER 2018", "NYAlerts May2016
    thru May2017"); a month with no year takes the next stated year in the name, else the tab before's; a name with
    "thru" or "through" and one month gives only the last day."""
    toks = re.findall(r"[A-Za-z]+|\d+", name)
    months = []
    for i, t in enumerate(toks):
        m = MONTHS.get(t[:3].lower()) if t.isalpha() and len(t) >= 3 else None
        if m:
            y = int(toks[i + 1]) if i + 1 < len(toks) and re.fullmatch(r"(?:19|20)\d\d", toks[i + 1]) else None
            months.append([m, y])
    if not months:
        return None, None, year_before
    for i, mm in enumerate(months):
        if mm[1] is None:
            mm[1] = next((x[1] for x in months[i + 1:] if x[1]), None) or year_before
    if any(y is None for _m, y in months):
        return None, None, year_before
    ranged = bool(re.search(r"\b(?:thru|through)\b", name, re.I))
    first = date(months[0][1], months[0][0], 1) if (not ranged or len(months) > 1) else None
    lm, ly = months[-1]
    last = date(ly + (lm == 12), lm % 12 + 1, 1) - timedelta(days=1)
    return first, last, ly


def read_tabs(content: bytes) -> list[dict]:
    """[{tab, layout, header_row, columns, title, header_note, period, rows: [(row number, {column: value})]}] for
    every tab, in workbook order (ny_sprtk's stdlib reader). The header is the first of a tab's first three rows that
    matches a layout; the rows before it are its title. A tab with no header row whose first row reads as data in the
    tab before's layout is read with that tab's columns. Raises ValueError for a damaged workbook or an unknown layout."""
    z = zipfile.ZipFile(io.BytesIO(content))
    bad = z.testzip()
    if bad:
        raise ValueError(f"workbook part {bad} fails its zip checksum (a file cut short or damaged)")
    ss = S._shared_strings(z)
    tabs, prev, year = [], None, None
    for name, path in S._sheets(z):
        lists = list(S._rows(z, path, ss))
        hdr_i = layout = None
        for i, cells in enumerate(lists[:3]):
            layout = detect_layout(cells)
            if layout:
                hdr_i = i
                break
        note, before = None, []
        if hdr_i is None:
            if not lists:
                cols, layout, start = [], prev["layout"] if prev else None, 0
            elif prev is not None and _reads_as_data(lists[0], prev):
                cols, layout, start = prev["columns"], prev["layout"], 0
                note = f"this tab has no header row; read with the columns of the tab before it ({prev['tab']})"
            else:
                raise ValueError(f"tab {name!r}: no header row in a known layout")
        else:
            cols = [(h.strip() if isinstance(h, str) and h.strip() else f"col{j + 1}") for j, h in enumerate(lists[hdr_i])]
            start = hdr_i + 1
            # a row above the header that reads as data in the header's layout is data (the August 2021 tab puts
            # its header row after two notices); the others are the tab's title
            before = [i for i in range(hdr_i) if _reads_as_data(lists[i], {"layout": layout, "columns": cols})]
            if before:
                note = f"the header row stands after {len(before)} data row(s), which are read with it"
        title_rows = [i for i in range(hdr_i or 0) if i not in before]
        rows = []
        for i in before + list(range(start, len(lists))):
            d = {}
            for j, v in enumerate(lists[i]):
                if v is None:
                    continue
                k = cols[j] if j < len(cols) else f"col{j + 1}"
                if k in d:
                    k = f"col{j + 1}"
                d[k] = v.strip() if isinstance(v, str) else v
            if d:
                rows.append((i + 1, d))
        first, last, year = tab_period(name, year)
        tab = {"tab": name, "layout": layout, "header_row": None if hdr_i is None else hdr_i + 1, "columns": cols,
               "title": [" ".join(str(c) for c in lists[i] if c) for i in title_rows], "header_note": note,
               "period": (first, last), "rows": rows}
        tabs.append(tab)
        if layout:
            prev = tab
    return tabs


def _reads_as_data(cells: list, prev: dict) -> bool:
    """Whether a headerless tab's first row is a data row of the tab before: its start column reads as a time."""
    amap = LAYOUTS[prev["layout"]]
    for j, c in enumerate(prev["columns"]):
        if amap.get(norm_header(c)) == "startDateTime" and j < len(cells):
            try:
                v, _fam = S.parse_dt(cells[j])
            except ValueError:
                return False
            return isinstance(v, datetime)
    return False


def check_shape(tabs: list[dict], state: dict) -> None:
    """A read with fewer tabs than the last read, or fewer rows in one of its tabs, fails (a file cut short)."""
    before = {t["tab"]: t["rows"] for t in state.get("tabs") or [] if isinstance(t, dict)}
    if not before:
        return
    if len(tabs) < len(before):
        raise ValueError(f"the workbook has {len(tabs)} tabs, {len(before)} at the last read")
    short = [f"{t['tab']} {len(t['rows'])} rows ({before[t['tab']]} at the last read)"
             for t in tabs if t["tab"] in before and len(t["rows"]) < before[t["tab"]]]
    if short:
        raise ValueError("fewer rows than at the last read: " + "; ".join(short[:5]))


# ---------------------------------------------------------------- one row

def typed_time(v) -> str | None:
    """A typed time ("2014/08/13 10:30 AM", "08/13/2014 12:00 PM", "8/13/2014 :") as ISO text (a date alone when the
    time is blank); the text as given when it is none of these (parse_dt then notes it); None when blank."""
    s = clean(v)
    if not s or JUNK_TIME.fullmatch(s):
        return None
    for fmt in ("%Y/%m/%d %I:%M %p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M%p", "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt).isoformat(timespec="minutes")
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2}/\d{1,2}/\d{4})\s*:?\s*(?:[AP]M)?", s, re.I)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()
        except ValueError:
            pass
    return s


def split_time(d, t) -> tuple[str | None, str | None]:
    """alert15's date and time columns -> (ISO text, or the text as given when the date cannot be read; a problem)."""
    ds, ts = clean(d) or "", clean(t) or ""
    ds = "" if JUNK_TIME.fullmatch(ds) else ds
    ts = "" if JUNK_TIME.fullmatch(ts) else ts
    if not ds:
        return (None, None) if not ts else (None, f"time {ts!r} given with no date")
    day = None
    try:
        if re.fullmatch(r"\d{5}", ds):
            day = (S.EXCEL_EPOCH + timedelta(days=int(ds))).date()
        elif re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", ds):
            day = datetime.strptime(ds, "%m/%d/%Y").date()
        elif m := re.match(r"([A-Z][a-z]+ \d{1,2}, \d{4})", ds):
            day = datetime.strptime(m.group(1), "%B %d, %Y").date()
    except ValueError:
        day = None
    if day is None:
        return f"{ds} {ts}".strip(), None
    m = re.fullmatch(r"(\d{1,2}):(\d{1,2})(?::\d{1,2})?\s*(?:([AaPp])\.?\s*[Mm]\.?)?", ts)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if m.group(3):
            h = h % 12 + (12 if m.group(3).lower() == "p" else 0) if 1 <= h <= 12 else 99
        if h < 24 and mi < 60:
            return datetime(day.year, day.month, day.day, h, mi).isoformat(timespec="minutes"), None
    return day.isoformat(), (f"time of day {ts!r} not understood: the date only" if ts else None)


def joined(*parts) -> str | None:
    vals = []
    for p in parts:
        s = clean(p)
        if s and s not in vals:
            vals.append(s)
    return " ".join(vals) or None


def with_units(d, units) -> str | None:
    d, u = clean(d), clean(units)
    if d and u and not re.search(r"[a-z]", d, re.I):
        return f"{d} {u}"
    return d


def reasons_of(*vals) -> str | None:
    out = []
    for v in vals:
        for part in str(v or "").split(","):
            s = clean(part)
            if s and s not in out:
                out.append(s)
    return "; ".join(out) or None


def fields_of(row: dict, layout: str) -> tuple[dict, dict]:
    """(the row under ny_sprtk's field names, plus the composed quantity, duration, reasons, times and notice kind;
    info: problems, the notice kind and its basis, the duration text, the alert15 state, the expected end)."""
    amap = LAYOUTS[layout]
    g = {}
    for k, v in row.items():
        key = amap.get(norm_header(k))
        if key and key not in g:
            g[key] = v
    f = {k: v for k, v in g.items() if not k.startswith("_")}
    info = {"problems": []}
    if layout == "alert18":
        f["dischargeReason"] = reasons_of(g.get("_reason1"), g.get("_reason2"), g.get("_reason3"))
        f["quantity"] = joined(g.get("_quantity"), g.get("_quantity_units"), g.get("_estimate"))
        f["duration"] = with_units(g.get("_duration"), g.get("_duration_units"))
        m = HEADLINE_WORD.match(str(f.get("headline") or ""))
        word = m.group(1).upper() if m else None
        f["notificationStatus"] = KIND_OF_WORD.get(word, "New")
        info["kind"] = {"word": word, "read_as": f["notificationStatus"],
                        "basis": (f"the headline opens with {word}:" if word else "the headline opens with no "
                                  "UPDATE or ENDED word") + "; the workbook has no status column"}
    elif layout == "alert16":
        f["dischargeReason"] = reasons_of(g.get("_reason1"), g.get("_reason2"), g.get("_reason3"))
        f["reasonDescription"] = "; ".join(x for x in (clean(g.get(k)) for k in ("_rdesc1", "_rdesc2", "_rdesc3")) if x) or None
        est = {"1": "Estimated", "0": "Actual"}.get(str(g.get("_estimated_ind") or "").strip())
        f["quantity"] = joined(g.get("_quantity"), g.get("_quantity_units"), est)
        hours = clean(g.get("_duration_hours"))
        f["duration"] = f"{hours} hours" if hours and re.fullmatch(r"-?[\d.]+", hours) else hours
    elif layout == "alert15":
        f["facilityName"] = (clean(f.get("facilityName")) or "").strip(" ,") or None
        f["dischargeReason"] = reasons_of(g.get("_reason1"))
        rdesc = reasons_of(f.get("reasonDescription"))
        qty = clean(g.get("_quantity"))
        if not qty and rdesc and VOLUME_TEXT.match(rdesc):
            qty, rdesc = rdesc, None            # the older rows put the volume under "Description"
        f["reasonDescription"] = rdesc
        f["quantity"] = joined(qty, g.get("_quantity_units"), str(g.get("_estimate") or "").strip("() ") or None)
        f["duration"] = clean(g.get("_duration"))
        f["startDateTime"], prob = split_time(g.get("_date"), g.get("_time"))
        if prob:
            info["problems"].append(prob)
        dur = (f["duration"] or "").lower()
        info["state"] = ("ended" if re.search(r"hours? ended\b|ended before discovery", dur) else
                         "ongoing" if re.search(r"hours? ongoing\b", dur) else None)
    elif layout == "report":
        f["dischargeReason"] = reasons_of(str(g.get("_reason1") or "").replace(";", ","))
        if f.get("reasonDescription"):
            f["reasonDescription"] = clean(str(f["reasonDescription"]).rstrip("; "))
        est = {"estimate": "Estimated", "actual": "Actual"}.get(str(g.get("_estimate") or "").strip().lower())
        f["quantity"] = joined(g.get("_quantity"), est)
        f["duration"] = clean(g.get("_duration"))
        f["startDateTime"] = typed_time(g.get("_start"))
        f["endDateTime"] = typed_time(g.get("_end"))
        info["expected_end"] = typed_time(g.get("_expected_end"))
        try:
            ended = f["endDateTime"] is not None and S.parse_dt(f["endDateTime"])[0] is not None
        except ValueError:
            ended = False
        if ended:
            f["notificationStatus"] = "Close"
            info["kind"] = {"word": None, "read_as": "Close", "basis": "the written report gives an ending time"}
        info["start_basis"] = START_BASIS_REPORT
    if not clean(f.get("facilityName")) and not clean(f.get("facilityId")):
        info["problems"].append("the row names no facility (a fragment of a notice as the tab holds it)")
    info["duration_text"] = f.get("duration")
    return f, info


def clock_for(basis: str):
    """The time reader for a layout's clock (ny_sprtk.parse_notice's clock): a date alone is day precision."""
    def clock(v):
        val, _fam = S.parse_dt(v)
        if val is None:
            return None, None, None
        if not isinstance(val, datetime):
            return val, "day", "date"
        out = S.resolve(val, "dmon", None)[0] if basis == "shifted" else S.resolve(val, "iso_dt", "local")[0]
        return out, "minute", basis
    return clock


def stored_value(v) -> datetime | date | None:
    try:
        return S.parse_dt(v)[0]
    except ValueError:
        return None


# ---------------------------------------------------------------- notices and records

def notices_of(tabs: list[dict]) -> tuple[list[dict], Counter]:
    """One notice per distinct row (a row repeating another exactly is a copy: n["copies"])."""
    by_id: dict[str, dict] = {}
    stats = Counter()
    for t_i, tab in enumerate(tabs):
        for rownum, row in tab["rows"]:
            stats["rows"] += 1
            stats[f"rows_{tab['layout']}"] += 1
            nid = "h" + hashlib.sha1(json.dumps([tab["layout"], sorted(row.items())], ensure_ascii=False)
                                     .encode()).hexdigest()[:16]
            if nid in by_id:
                by_id[nid]["copies"].append({"tab": tab["tab"], "row": rownum})
                stats["identical_rows"] += 1
                continue
            f, info = fields_of(row, tab["layout"])
            by_id[nid] = {"id": nid, "synthetic_id": False, "tab": tab["tab"], "tab_index": t_i, "row": rownum,
                          "f": f, "row_raw": row, "website": False, "layout": tab["layout"], "info": info,
                          "copies": [], "period": tab["period"]}
    return list(by_id.values()), stats


def period_note(n: dict, start) -> str | None:
    first, last = n["period"]
    st = S.as_utc(start)
    if st is None:
        return None
    d = st.astimezone(S.TZ).date()
    if first and d < first - timedelta(days=365):
        return (f"start {d.isoformat()} is more than a year before the tab's month ({n['tab']}): a typing error in the "
                "year or a long-running discharge; kept as written")
    if last and d > last + timedelta(days=31):
        return (f"start {d.isoformat()} is more than a month after the tab's last month ({n['tab']}): a typing error; "
                "kept as written")
    return None


def finish(rec: dict, n: dict) -> dict:
    """This workbook's notes on a record ny_sprtk.to_record built: layout, id, copies, notice kind, stored start,
    duration, the alert15 state, the report's projected end, a start outside the tab's months."""
    raw, info, p = rec.setdefault("raw", {}), n["info"], n.get("p") or {}
    raw["_layout"] = n["layout"]
    raw["_id_note"] = ID_NOTE
    if n["layout"] != "alert18" and isinstance(raw.get("_chain"), dict):
        raw["_chain"].pop("head_missing", None)     # only alert18 rows say which notice is the first
    if n["copies"]:
        raw["_copies"] = n["copies"]
    if info.get("kind"):
        raw["_notice_kind"] = {**info["kind"], "read_as": KIND_TEXT.get(info["kind"]["read_as"], info["kind"]["read_as"]),
                               "status": info["kind"]["read_as"]}
    if info.get("duration_text"):
        raw["_duration_text"] = info["duration_text"]
    stored = stored_value(n["f"].get("startDateTime"))
    if isinstance(stored, datetime):
        raw["_start_stored"] = stored.isoformat(timespec="minutes")
    elif isinstance(stored, date):
        raw["_start_stored"] = stored.isoformat()
    if p.get("facility_id"):
        raw["_facility_id"] = p["facility_id"]
    if n.get("start_not_used"):
        raw["_start_not_used"] = {"value": n["start_not_used"], "reason": START_NOT_USED}
    if info.get("start_basis") and rec.get("started_at"):
        raw["_start_basis"] = info["start_basis"]
    if rec.get("status") == "unknown" and info.get("state"):
        rec["status"] = info["state"]
        raw["_status_basis"] = f"the duration column says {info['state']} ({info.get('duration_text')}); no end time is given"
    if info.get("expected_end") and rec.get("status") != "ended":
        try:
            val, prec, _b = clock_for(CLOCK[n["layout"]])(info["expected_end"])
        except ValueError:
            val = None
        if val is not None:
            raw["_projected_end"] = S.local_iso(val)
            raw["_projected_end_note"] = "the report's expected ending time: a projection, not a reported end"
    note = period_note(n, p.get("start"))
    if note:
        raw["_dww_note"] = list(raw.get("_dww_note") or []) + [note]
    return rec


def build(tabs: list[dict], fetched_at: str, prev: list[dict], live: list[dict]) -> tuple[list[dict], dict]:
    notices, stats = notices_of(tabs)
    for n in notices:
        p = S.parse_notice(n, clock=clock_for(CLOCK[n["layout"]]))
        p["problems"].extend(n["info"]["problems"])
        st = S.as_utc(p["start"])
        if st is not None and st < EARLIEST_START.replace(tzinfo=S.TZ):
            n["start_not_used"] = S.local_iso(p["start"])
            p["start"] = p["start_prec"] = None
            p["basis"].pop("start", None)
    chains = S.build_chains(notices)
    dmap, cso = S.load_dischargers()
    ctx = {"echo": S.load_echo(), "dischargers": dmap, "cso_permits": cso, "place_cache": {}, "fetched_at": fetched_at,
           "source_id": SOURCE_ID, "source_url": SOURCE_URL, "basis_text": BASIS_TEXT}
    records = []
    for cid, chain in chains.items():
        parent = None
        for i, n in enumerate(chain):
            rec = S.to_record(n, cid, chain, i, parent, ctx)
            try:
                finish(rec, n)
            except Exception as e:  # noqa: BLE001 - never drop a record
                rec["parse_error"] = "; ".join(x for x in (rec.get("parse_error"), f"notes: {error_text(e)}") if x)
            records.append(rec)
            parent = rec["event_id"]
    new_ids = {r["event_id"] for r in records}
    if len(new_ids) != len(records):
        raise ValueError(f"{len(records) - len(new_ids)} repeated event ids")
    kept = 0
    for r in prev:
        if r.get("event_id") in new_ids:
            continue
        raw = r.setdefault("raw", {})
        raw["_missing_from_workbook_since"] = raw.get("_missing_from_workbook_since") or fetched_at
        records.append(r)
        kept += 1
    overlap = link_copies(records, live)
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    starts = sorted(r["started_at"][:10] for r in records if r.get("started_at"))
    latest = [r for r in records if (r["raw"].get("_chain") or {}).get("latest") == r["event_id"]]
    no_start = [n for n in notices if n["p"]["start"] is None]
    out = {
        "tabs": [{"tab": t["tab"], "layout": t["layout"], "rows": len(t["rows"]), "header_row": t["header_row"],
                  **({"title": t["title"]} if t["title"] else {}), **({"header_note": t["header_note"]} if t["header_note"] else {})}
                 for t in tabs],
        "rows": stats["rows"], "rows_by_layout": {k[5:]: v for k, v in stats.items() if k.startswith("rows_")},
        "identical_rows": stats["identical_rows"], "notices": len(notices), "chains": len(chains),
        "records_written": len(new_ids), "records_kept_from_earlier_reads": kept,
        "rows_without_start": len(no_start),
        "start_not_read": sum(1 for n in no_start if any(x.startswith("startDateTime") for x in n["p"]["problems"])),
        "rows_without_facility": sum(1 for n in notices if not n["p"]["facility_id"] and not n["p"]["facility_name"]),
        "start_range": [starts[0], starts[-1]] if starts else None,
        "starts_outside_tab_months": sum(1 for r in records if any("tab's" in str(x) for x in r["raw"].get("_dww_note") or [])),
        "time_basis": dict(Counter(b for n in notices for b in n["p"]["basis"].values())),
        "records_by_status": dict(Counter(r["status"] for r in records)),
        "latest_notices_by_type": dict(Counter(r["event_type"] for r in latest)),
        "latest_notices_water_match": dict(Counter(r["water_match"] for r in latest)),
        "overlap_with_newer_workbook": overlap,
    }
    return records, out


# ---------------------------------------------------------------- copies in the newer workbook

def _when(rec: dict) -> tuple[datetime | None, date | None]:
    """(start minute in UTC when the record has the minute, start date in New York)."""
    s = rec.get("started_at")
    if not s:
        return None, None
    try:
        t = datetime.fromisoformat(str(s))
    except ValueError:
        return None, None
    if t.tzinfo is None:
        return None, t.date()
    minute = t.astimezone(UTC).replace(second=0, microsecond=0) if rec.get("time_precision") == "minute" else None
    return minute, t.astimezone(S.TZ).date()


def _side(rec: dict, history: bool) -> dict:
    raw = rec.get("raw") if isinstance(rec.get("raw"), dict) else {}
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    if history:
        f = fields_of(row, raw["_layout"])[0] if raw.get("_layout") in LAYOUTS else {}
        fid = raw.get("_facility_id") or rec.get("npdes_permit")
        kind = (raw.get("_notice_kind") or {}).get("status")
    else:
        f = S.canonical(row)[0]
        fid = rec.get("npdes_permit") or S.facility_of(f)[0]
        kind = str(f.get("notificationStatus") or "").strip().title() or None
    name = S.norm_text(S.clean_name(rec.get("discharger_name")))
    keys = {k for k in (fid, f"n:{name}" if name else None) if k}
    minute, day = _when(rec)
    stored = wall = None
    if history and raw.get("_start_stored"):
        try:
            stored = datetime.fromisoformat(raw["_start_stored"])
        except ValueError:
            stored = None
    if not history and minute is not None:
        wall = datetime.fromisoformat(rec["started_at"]).astimezone(S.TZ).replace(tzinfo=None, second=0, microsecond=0)
    head = S.norm_text(HEADLINE_WORD.sub("", str(row.get("headline") or "")))
    return {"keys": keys, "minute": minute, "day": day, "stored": stored, "wall": wall,
            "water": S.norm_text(rec.get("waterbody_text")), "slugs": tuple(sorted(rec.get("water_slugs") or [])),
            "head": head, "kind": kind, "addr": S.address_key(f), "vol": S.norm_text(rec.get("volume_text"))}


def _same_start(h: dict, live: dict) -> str | None:
    if h["minute"] is not None and live["minute"] is not None:
        if h["minute"] == live["minute"]:
            return "the same start minute"
        if isinstance(h["stored"], datetime) and live["wall"] is not None and h["stored"].replace(second=0) == live["wall"]:
            return "the same start as stored (the newer workbook reads this tab's stored value as local time)"
        return None
    if live["day"] == h["day"]:
        return "the same start date"
    if isinstance(h["stored"], datetime) and live["day"] == h["stored"].date():
        return "the same start date as stored (the newer workbook's 2021 dates follow the stored clock)"
    return None


def _same_water(h: dict, live: dict) -> str | None:
    if h["water"] and h["water"] == live["water"]:
        return "the same water"
    if h["slugs"] and h["slugs"] == live["slugs"]:
        return "the same mapped water"
    if h["head"] and h["head"] == live["head"]:
        return "the same headline"
    return None


def link_copies(records: list[dict], live: list[dict]) -> dict:
    """duplicate_of / raw._possible_copy_of against the newer workbook's records (docstring "Overlap"); the links of
    an earlier run are made again from scratch. Returns the counts."""
    for r in records:
        r["duplicate_of"] = None
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        raw.pop("_duplicate_basis", None)
        raw.pop("_possible_copy_of", None)
    idx: dict[tuple, list[str]] = defaultdict(list)
    sides: dict[str, dict] = {}
    for rec in live:
        if not isinstance(rec, dict) or not rec.get("event_id"):
            continue
        s = _side(rec, history=False)
        if s["day"] is None or not s["keys"]:
            continue
        sides[rec["event_id"]] = s
        for k in s["keys"]:
            idx[(k, s["day"])].append(rec["event_id"])
    strict, weak = [], {}
    by_id = {r["event_id"]: r for r in records}
    for rec in records:
        h = _side(rec, history=True)
        if h["day"] is None or not h["keys"]:
            continue
        days = {h["day"]} | ({h["stored"].date()} if isinstance(h["stored"], datetime) else set())
        cands = sorted({eid for k in h["keys"] for d in days for eid in idx.get((k, d), ())})
        for eid in cands:
            ls = sides[eid]
            start, water = _same_start(h, ls), _same_water(h, ls)
            if start and water:
                score = ((4 if start == "the same start minute" else 0) + (3 if h["addr"] and h["addr"] == ls["addr"] else 0)
                         + (2 if h["kind"] and h["kind"] == ls["kind"] else 0) + (1 if h["vol"] and h["vol"] == ls["vol"] else 0)
                         + (1 if water == "the same water" else 0))
                strict.append((score, rec["event_id"], eid, start, water))
            elif start and rec["event_id"] not in weak:
                weak[rec["event_id"]] = (eid, f"the same facility and start ({start}), with another or no water")
            elif water and h["minute"] is not None and ls["minute"] is not None and rec["event_id"] not in weak:
                weak[rec["event_id"]] = (eid, "the same facility, water and date, with another start time")
    taken_h, taken_l, left = set(), set(), {}
    for score, hid, eid, start, water in sorted(strict, key=lambda x: (-x[0], x[1], x[2])):
        if hid in taken_h:
            continue
        if eid in taken_l:
            left.setdefault(hid, eid)
            continue
        taken_h.add(hid)
        taken_l.add(eid)
        rec = by_id[hid]
        rec["duplicate_of"] = eid
        rec["raw"]["_duplicate_basis"] = (f"also in the newer workbook (SPRTK_Data.xlsx) as {eid}: the same facility, "
                                          f"{start}, {water}; listed from there")
    possible = 0
    for hid, eid in left.items():
        if hid in taken_h:
            continue
        by_id[hid]["raw"]["_possible_copy_of"] = {
            "event_id": eid, "reason": "the same facility, start and water as a notice of the newer workbook that is "
                                       "paired with another notice of this workbook"}
        possible += 1
    for hid, (eid, reason) in weak.items():
        if hid in taken_h or hid in left:
            continue
        by_id[hid]["raw"]["_possible_copy_of"] = {"event_id": eid, "reason": reason}
        possible += 1
    return {"duplicate_of": len(taken_h), "possible_copy_of": possible, "newer_workbook_records": len(live)}


# ---------------------------------------------------------------- fetch and runs

def _lm_iso(h) -> str | None:
    try:
        return parsedate_to_datetime(h).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if h else None
    except (TypeError, ValueError):
        return None


def _is_xlsx(content: bytes) -> bool:
    return content[:2] == b"PK"


def fetch(sess: requests.Session, state: dict, force: bool) -> tuple[bytes | None, dict]:
    """(workbook bytes, or None when not modified since the last read; where it came from). DEC with
    If-Modified-Since (none when force), then the latest Internet Archive capture. Raises when neither answers."""
    headers = {} if force or not state.get("last_modified_http") else {"If-Modified-Since": state["last_modified_http"]}
    errors = []
    for url in DEC_URLS:
        try:
            r = sess.get(url, headers=headers, timeout=(15, 180))
            if r.status_code == 304:
                return None, {"via": "dec", "url": url, "last_modified": state.get("last_modified")}
            r.raise_for_status()
            if not _is_xlsx(r.content):
                raise ValueError(f"not an xlsx ({len(r.content)} bytes)")
            lm = r.headers.get("Last-Modified")
            return r.content, {"via": "dec", "url": r.url, "last_modified_http": lm, "last_modified": _lm_iso(lm)}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url}: {error_text(e)}")
    url = ARCHIVE_URL.format(ts=datetime.now(UTC).strftime("%Y%m%d%H%M%S"))
    for attempt in range(2):
        try:
            r = sess.get(url, timeout=(20, 180))
            if r.status_code == 429:
                raise requests.HTTPError("429 Too Many Requests")
            r.raise_for_status()
            if not _is_xlsx(r.content):
                raise ValueError(f"not an xlsx ({len(r.content)} bytes)")
            cap = re.search(r"/web/(\d{14})", r.url)
            lm = r.headers.get("x-archive-orig-last-modified")
            info = {"via": "archive.org", "url": r.url, "last_modified_http": lm, "last_modified": _lm_iso(lm),
                    "capture": (datetime.strptime(cap.group(1), "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                                .isoformat().replace("+00:00", "Z") if cap else None), "dec_errors": errors}
            if not force and lm and lm == state.get("last_modified_http"):
                return None, info
            return r.content, info
        except Exception as e:  # noqa: BLE001
            errors.append(f"archive.org: {error_text(e)}")
            if attempt == 0:
                time.sleep(10)
    raise RuntimeError("; ".join(errors))


def due(state: dict, now: datetime) -> bool:
    """Whether the workbook is asked for this run: REREAD_DAYS after the last read (or never read)."""
    try:
        t = datetime.fromisoformat(str(state.get("read_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    return now - t >= timedelta(days=REREAD_DAYS)


def keep(prev_doc: dict, prev: list[dict], fetched_at: str, state: dict, why: dict, said: str) -> int:
    """A run that reads nothing new: the records are kept, the links to the newer workbook made again. The records
    were redacted when they were read (and the export redacts every record again)."""
    live = (read_json(LIVE_EVENTS, {}) or {}).get("records", [])
    records = list(prev)
    overlap = link_copies(records, live)
    meta = {**(prev_doc.get("meta") or {}), **why, "checked_at": fetched_at, "overlap_with_newer_workbook": overlap}
    meta.pop("overlap_note", None)
    if not live:
        meta["overlap_note"] = "the newer workbook's records were not found, so no overlap was checked this run"
    write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    write_json(STATE_FILE, {**state, "checked_at": fetched_at})
    print(f"{SOURCE_ID}: {said}; {len(records)} records kept ({overlap['duplicate_of']} listed from the newer workbook, "
          f"{overlap['possible_copy_of']} possible copies)")
    return 0


def raw_page(tabs: list[dict], info: dict, fetched_at: str) -> dict:
    """The saved raw page: every row after common.strip_personal, never the workbook itself."""
    return {"file": info.get("url") or SOURCE_URL, "last_modified": info.get("last_modified"), "fetched_at": fetched_at,
            "rows_note": "every row of every tab, with personal data scrubbed (common.strip_personal)",
            "tabs": [{"tab": t["tab"], "layout": t["layout"], "header_row": t["header_row"], "columns": t["columns"],
                      "rows": [[n, strip_personal(r)] for n, r in t["rows"]]} for t in tabs]}


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved Sewage_Discharge_Reports.xlsx instead of DEC's")
    ap.add_argument("--backfill", action="store_true",
                    help="read the workbook now (every read takes every row; this skips the weekly wait and the 304)")
    args = ap.parse_args(argv)
    t0 = time.monotonic()
    fetched_at = now_iso()
    now = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    state = read_json(STATE_FILE, {}) or {}
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_doc.get("records", [])
    if not args.file and not args.backfill and prev and not due(state, now):
        return keep(prev_doc, prev, fetched_at, state, {"last_read_at": state.get("read_at")},
                    f"read {state.get('read_at')}, next read {REREAD_DAYS} days after it")
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        if args.file:
            content, info = Path(args.file).read_bytes(), {"via": "file", "file": Path(args.file).name}
        else:
            content, info = fetch(sess, state, force=args.backfill or not prev)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    if content is None:
        state.update(read_at=fetched_at, last_modified=info.get("last_modified") or state.get("last_modified"))
        return keep(prev_doc, prev, fetched_at, state,
                    {"workbook_not_modified_since": info.get("last_modified"), "last_read_at": fetched_at,
                     "last_read_via": info.get("via")},
                    f"workbook not modified since {info.get('last_modified')} ({info.get('via')})")
    try:
        tabs = read_tabs(content)
        check_shape(tabs, state)
        live = (read_json(LIVE_EVENTS, {}) or {}).get("records", [])
        records, stats = build(tabs, fetched_at, prev, live)
    except Exception as e:  # noqa: BLE001 - a read that fails keeps the previous records
        write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    page = raw_page(tabs, info, fetched_at)
    sha = hashlib.sha256(json.dumps(page["tabs"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    raw_path = state.get("raw_path")
    if sha != state.get("sha256") or not (raw_path and (ROOT / raw_path).exists()):
        raw_path = str(save_raw(SOURCE_ID, json.dumps(page, ensure_ascii=False), "json").relative_to(ROOT))
        state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
    size = len(content)
    del page, content
    records = redact.redact_events(records)
    if not args.file:
        state.update(read_at=fetched_at, tabs=[{"tab": t["tab"], "rows": len(t["rows"])} for t in tabs],
                     **{k: info.get(k) for k in ("via", "url", "capture", "last_modified_http", "last_modified")})
    if args.backfill:
        state["backfill"] = {"at": fetched_at, "notices": stats["notices"]}
    state.update(fetched_at=fetched_at, checked_at=fetched_at)
    write_json(STATE_FILE, state)
    meta = {**stats,
            "workbook": {k: info.get(k) for k in ("via", "url", "file", "capture", "last_modified", "dec_errors")
                         if info.get(k) is not None} | {"bytes": size},
            "raw_path": raw_path, "page": PAGE_URL, "credit": CREDIT, "caveat": CAVEAT, "registry_ids": [SOURCE_ID],
            "reread_days": REREAD_DAYS, "last_read_at": fetched_at, "checked_at": fetched_at, "frozen": True,
            "statewide": False, "backfill": state.get("backfill"),
            "time_note": ("The workbook's NY-Alert tabs from June 13, 2018 store local time shifted back by the UTC offset "
                          "(read as stored + 4 or 5 hours); the earlier tabs store local time. Each record's "
                          "raw._time_basis says how its times were read."),
            "overlap_basis": ("A notice also in the newer workbook (SPRTK_Data.xlsx) is listed from that feed: the same "
                              "facility, the same start (minute, or date where one side has the date only) and the same "
                              "water or headline, paired one to one. A weaker match is noted as a possible copy, and "
                              "both are listed."),
            "run_seconds": round(time.monotonic() - t0, 1)}
    if not live:
        meta["overlap_note"] = "the newer workbook's records were not found, so no overlap was checked this run"
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    o = stats["overlap_with_newer_workbook"]
    print(f"{SOURCE_ID}: {stats['rows']} rows in {len(tabs)} tabs ({info.get('via')}), {stats['notices']} notices "
          f"({stats['identical_rows']} identical rows), {stats['chains']} chains, {stats['records_written']} records "
          f"written, {stats['records_kept_from_earlier_reads']} kept; starts {stats['start_range']}; listed from the "
          f"newer workbook {o['duplicate_of']}, possible copies {o['possible_copy_of']}; rows without a start "
          f"{stats['rows_without_start']}; {meta['run_seconds']} s -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
