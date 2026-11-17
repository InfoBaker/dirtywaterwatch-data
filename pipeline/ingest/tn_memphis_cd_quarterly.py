"""The City of Memphis's consent-decree quarterly SSO reports -> data/build/events/tn-memphis-cd-quarterly.json

Source (registry tn-memphis-cd-quarterly; operator tn-memphis)
  The City's consent-decree program site, "Reports", https://sarp10.com/reports/ (200 to the named client and to
  GitHub's runner, probe 43885170112). Under "Quarterly Reports - SSO Reports" it links one PDF per quarter, each link
  titled "City of Memphis Quarterly Report- <first day> - <last day>" (2016 on; 2023 Q1 to 2026 Q2 on 2026-11-17).
  The report's own words (page 2): "To fulfill the reporting requirements defined in Section VIII.24 of the Consent
  Decree, the City of Memphis has prepared this Quarterly Report, which summarizes all SSO events occurring from
  <first day> through <last day>. The table included in this report provides the date, time, location, source,
  estimated duration, estimated volume, receiving water (if any), and cause of the SSO event." (Consent decree of
  September 20, 2012, United States and State of Tennessee v. City of Memphis, W.D. Tenn.)

Reading (pypdf, plain text; the table pages are rotated landscape pages, read row by row)
  The table starts on the page holding its header ("Receiving stream (if any)") and runs to the footnotes. Each row is
  one line: Location - Address, Date and Time, Cause, Estimated Volume (gallons), Source, Duration (Hours), then either
  the receiving stream with three YES/NO columns (Unpermitted Discharge, Appendix G Area, and Priority Area or CD 11b
  and 11c), a footnote mark (?, *, ** or †) or nothing. A line with no date continues the row above it (a time broken
  over two lines). A row that does not read in full (ROW) is counted, never quoted (it may hold a house number), and
  the report's other rows are kept: the report is named in meta.rows_not_read and the run is not healthy. The marks'
  footnotes are read from the report itself and kept with each row in the City's words (raw.reach_note).
  Every row is checked against the report's quarter; a row dated outside it is kept as written, with a note.

Records (one sso record per row)
  - started_at: the row's date and time in Memphis (America/Chicago), time_precision minute. The reports from 2025 on
    write times with AM or PM; a time written without AM or PM in such a report is ambiguous and the record is dated to
    the day (raw.time_note). Reports written in 24-hour time are read as such.
  - ended_at: the start plus the row's estimated duration in hours (common.end_after; the report's own figure), status
    ended; no duration, no end (status unknown). The duration is the City's estimate (raw.duration_hours_as_written).
  - published_at: the date on the report's certification page (page 1), when it is filled in; the Q2 2026 report leaves
    it blank, and then none is given (raw.report_posted_folder is the upload folder's year and month, for reference
    only). fetched_at: when the report was read.
  - Volume: Estimated Volume (gallons) as written (estimate_flag estimated).
  - Water: the Receiving stream cell as written (waterbody_text), placed only by the repository's matcher on the
    water it names (raw._placement named_water_only; never at a plant, never geocoded). A row with a footnote mark and
    no stream names no water and is placed on none; the mark's footnote is kept in the City's words. The City states
    for no row that the sewage reached no water (its "*" says it is believed to have reached a storm inlet or pond and
    that it cannot determine whether it reached a water), so no row is flagged as having reached no water.
  - Source column: kept as written (raw.overflow_source: "M/L" manhole, "BASEMENT" a backup into a building, ...).
  - Place: the Location - Address cell with house numbers removed (al_jefferson_county_soa.street_only), as the
    outfall_name and raw.location; Shelby County.
  - source_record_id "<YYYY>Q<n>:<date>T<HHMM|day>:<street key>", "~<k>" for a second row of the same date, time and
    street in one report.
  - One event, one record: Memphis's overflows are absent from TDEC's Events Report (the research, 2026-11-03), whose
    host has refused automated reading since 2026-11-07; a record of the same local day and street as a TDEC record of
    a Memphis permit is still marked its duplicate (link_tdec, the Knoxville reader's rule), and the count is in meta.
  - Privacy: the report's certification page carries an official's name and signature: it is never stored; only the
    parsed, scrubbed rows are kept in data/build/tn-memphis-cd-state.json, never the PDF.

Cadence: the index hourly with the refresh; a report not yet read is read when it is among the newest NEWEST listed,
  and every listed report from BACKFILL_FROM with --backfill. A report that cannot be fetched or read stays pending
  (meta.pending) and is tried again on each run, a report with rows not read is named (meta.rows_not_read) and read again
  when PARSER_VERSION changes; the feed is
  unhealthy (exit 1, the previous records kept) only when the index cannot be read or lists no quarterly report.
Run from pipeline/: python -m ingest.tn_memphis_cd_quarterly [--backfill] [--file report.pdf --quarter 2026Q2 --out x]
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import io
import re
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

import common
from common import BUILD_DIR, EVENTS_DIR, HEADERS, end_after, event, now_iso, read_json, write_events, write_json
from ingest.al_jefferson_county_soa import street_key, street_only
from ingest.la_baton_rouge_quarterly import receiving_water
from ingest.tn_kub_sso_log import _tdec_street

SOURCE_ID = "tn-memphis-cd-quarterly"
INDEX = "https://sarp10.com/reports/"
STATE_PATH = BUILD_DIR / "tn-memphis-cd-state.json"
TDEC_EVENTS = EVENTS_DIR / "tn-tdec-events-report.json"
TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
DISCHARGER_ID = "tn-memphis"
DISCHARGER = "City of Memphis"
PERMITS = ["TN0020711", "TN0020729"]          # data/dischargers.json tn-memphis npdes_permits
AUTHORITY = "City of Memphis, consent-decree quarterly report (Section VIII.24), SSO events table"
COUNTY = "Shelby"
BACKFILL_FROM = "2023-01-01"
NEWEST = 2
PARSER_VERSION = 2       # 2: review 2026-11-17 (the water cell checked; day-bound ends; date-only starts)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
LINK = re.compile(r"""<a\s[^>]*href=["']([^"']+\.pdf)["'][^>]*>(.*?)</a>""", re.I | re.S)
TITLE = re.compile(rf"City of Memphis Quarterly Report\W*({MONTHS})\s+(\d{{1,2}}),?\s*(\d{{4}})?.*?({MONTHS})\s+"
                   rf"(\d{{1,2}}),?\s*(\d{{4}})", re.I)
HEADER = re.compile(r"Receiving\s+stream", re.I)
DATE = r"\d{1,2}/\d{1,2}/(?:\d{4}|\d{2})"
DATE_IN_LINE = re.compile(rf"(?<![\d/]){DATE}(?![\d/])")
NUM = r"\d[\d,]*(?:\.\d+)?"
ROW = re.compile(
    rf"^(?P<loc>.*?)\s*(?P<date>{DATE})(?:,\s*|\s+)(?:(?P<time>\d{{1,2}}:\s*\d{{2}})(?::\d{{2}})?\s*(?P<ampm>[AP]\.?M\.?)?)?\s*"
    rf"(?P<cause>[^\d\s].*?)\s+(?P<vol>{NUM}|UNKNOWN|UNK|N/?A)\s+(?P<src>\S.*?)\s+(?P<dur>{NUM})"
    r"(?:\s+(?P<tail>(?!\d)\S.*?))?\s*$", re.I)
MARKS = r"(?:\*\*|\*|\?|†)"
FLAGS = r"(?:YES|NO)(?:\s+(?:YES|NO)){0,2}"
# what may follow the duration: a footnote mark (with YES/NO flags in some rows), or a receiving stream followed by
# one to three YES/NO flags (and a mark in some rows). Anything else (the next row's address printed on this line, a
# stream with no flag) makes the row not read: a stream is taken only where the flags close it.
TAIL_MARK = re.compile(rf"^(?:(?P<mark>{MARKS})(?:\s+(?P<flags>{FLAGS}))?|(?P<flags_only>{FLAGS}))$", re.I)
TAIL_WATER = re.compile(rf"^(?P<water>[^?*†\d][^\d]*?)\s+(?P<flags>{FLAGS})(?:\s+(?P<mark>{MARKS}))?$", re.I)
MARK_LINE = re.compile(r"^\s*(\*\*|\*|\?|†)\s+(\S.*)$")
SIGNED = re.compile(r"(?<![\d/])(\d{1,2}/\d{1,2}/\d{4})(?![\d/])")
SUITE = re.compile(r"\b(?:STE|SUITE|APT|UNIT|BLDG)\.?\s*#?\s*[\w-]+", re.I)
# a receiving-water cell ending in a street word is an address, never a water (review 2026-11-17 P1-1)
STREET_END = re.compile(r"\b(?:ROAD|RD|STREET|ST|AVENUE|AVE|DRIVE|DR|LANE|LN|COVE|CV|BOULEVARD|BLVD|PARKWAY|PKWY|"
                        r"WAY|PLACE|PL|CIRCLE|CIR|TRAIL|TRL|COURT|CT|HWY|HIGHWAY|TERRACE|TER|PIKE)\.?$", re.I)
UPLOAD = re.compile(r"/uploads/(\d{4})/(\d{2})/")


class ReadError(ValueError):
    """A report that is not the table this reader knows: no rows are taken from it."""


# ---------------------------------------------------------------- the index

def report_links(page: str, base: str = INDEX) -> dict[str, dict]:
    """{'2026Q2': {url, period: [first, last], title}} for each quarterly report the index lists."""
    out: dict[str, dict] = {}
    for href, inner in LINK.findall(page):
        title = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        m = TITLE.search(title)
        if not m:
            continue
        y2 = int(m.group(6))
        y1 = int(m.group(3) or y2)
        try:
            first = datetime.strptime(f"{m.group(1)} {m.group(2)} {y1}", "%B %d %Y").date()
            last = datetime.strptime(f"{m.group(4)} {m.group(5)} {y2}", "%B %d %Y").date()
        except ValueError:
            continue
        key = f"{last.year}Q{(last.month - 1) // 3 + 1}"
        out.setdefault(key, {"url": urljoin(base, href.strip()).replace("http://", "https://"),
                             "period": [first.isoformat(), last.isoformat()], "title": title})
    return out


# ---------------------------------------------------------------- the report

def pdf_pages(content: bytes) -> list[str]:
    import pypdf
    return [p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(content)).pages]


def _clean(s: str) -> str:
    """Spaces made plain, and the reports' font ligatures ('loca\u019fons' for 'locations') read as letters."""
    s = unicodedata.normalize("NFKC", s or "").replace("\u019f", "ti").replace("\u2010", "-")
    return " ".join(s.split())


def location(cell: str) -> str | None:
    """The Location - Address cell with the house number and any suite or unit number removed."""
    return street_only(SUITE.sub(" ", _clean(cell)))


def signed_date(pages: list[str]) -> str | None:
    """The date written on the certification page (page 1), or None when it is left blank."""
    if not pages:
        return None
    m = SIGNED.search(pages[0])
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def water_cell(text: str) -> tuple[str | None, str | None]:
    """(the receiving stream as written, or None; why it was withheld). The Baton Rouge reader's check (an address, a
    phone, an e-mail, a person's name, or a cell that is not a water's name is withheld) and a cell ending in a street
    word ('Wolf River Road'): the row is kept and placed on no water (review 2026-11-17 P1-1, P1-2)."""
    t = _clean(text)
    if not t:
        return None, None
    if STREET_END.search(t):
        return None, "the receiving-water cell ends in a street word and is withheld"
    return receiving_water(t)


def table_lines(pages: list[str]) -> tuple[list[str], dict[str, str]]:
    """(the table's row lines, {mark: footnote}) from the first page with the table header to the footnotes."""
    lines: list[str] = []
    notes: dict[str, str] = {}
    started = False
    last_mark = None
    for text in pages:
        if not started:
            if not HEADER.search(text):
                continue
            started = True
            text = text[HEADER.search(text).end():]
            # the header's own last line ("Unpermitted Discharge Appendix G Area ...") ends at the header's text
            text = text.split("\n", 1)[1] if "\n" in text else ""
        for ln in text.split("\n"):
            c = _clean(ln)
            if not c or c.startswith("CoM Public"):
                continue
            m = MARK_LINE.match(c)
            if m and not DATE_IN_LINE.search(c):
                last_mark = m.group(1)
                notes[last_mark] = common.scrub_text(_clean(m.group(2)))
                continue
            if last_mark is not None:
                if not DATE_IN_LINE.search(c):
                    notes[last_mark] = common.scrub_text(_clean(notes[last_mark] + " " + c))   # its next line
                    continue
                last_mark = None
            lines.append(c)
    return lines, notes


def join_rows(lines: list[str]) -> list[str]:
    """One string per table row: a line with a date starts a row, a line without one continues the row above."""
    rows: list[str] = []
    for c in lines:
        if DATE_IN_LINE.search(c) or not rows:
            rows.append(c)
        else:
            rows[-1] = rows[-1] + ("" if rows[-1].endswith(":") else " ") + c
    return rows


def _date(s: str) -> date:
    m, d, y = (int(x) for x in s.split("/"))
    return date(y + 2000 if y < 100 else y, m, d)


def parse_report(pages: list[str]) -> dict:
    """{signed, notes, rows: [...], not_read: n, ampm: bool}. ReadError when there is no table."""
    lines, notes = table_lines(pages)
    if not lines:
        raise ReadError("no SSO table (no 'Receiving stream' header) in the report")
    rows, bad = [], 0
    raw_rows = join_rows(lines)
    for s in raw_rows:
        m = ROW.match(re.sub(r"(\d)([?*†])", r"\1 \2", s))
        tail = (m.group("tail") or "").strip() if m else ""
        t_m = TAIL_MARK.match(tail) or TAIL_WATER.match(tail) if tail else None
        # a row holding two events (a second date, a second volume in the Source cell) is not read: which figure
        # goes with which date is not known
        if not m or (tail and not t_m) or DATE_IN_LINE.search(m.group("loc") + " " + m.group("cause")) \
                or re.search(r"\b\d{3,}\b|\d\.\d", m.group("src")):
            bad += 1
            continue
        try:
            d = _date(m.group("date"))
        except ValueError:
            bad += 1
            continue
        g = t_m.groupdict() if t_m else {}
        water, withheld = water_cell(g.get("water") or "")
        t = (m.group("time") or "").replace(" ", "")
        row = {"date": d.isoformat(), "time": t or None,
               "ampm": (m.group("ampm") or "").replace(".", "").upper() or None,
               "location": location(m.group("loc")) if m.group("loc").strip() else None,
               "cause": _clean(m.group("cause")).upper(), "volume": m.group("vol"), "source": _clean(m.group("src")),
               "duration": m.group("dur"), "mark": g.get("mark"),
               "water": water,
               "flags": (g.get("flags") or g.get("flags_only") or "").upper().split() or None}
        if withheld:
            row["water_withheld"] = withheld
        rows.append(row)
    if not rows:
        raise ReadError(f"the SSO table's {len(raw_rows)} lines read as no row")
    ampm = any(r["ampm"] for r in rows)
    return {"signed": signed_date(pages), "notes": notes, "rows": rows, "not_read": bad, "ampm": ampm,
            "parser_version": PARSER_VERSION}


# ---------------------------------------------------------------- records

def _local(d: date, h: int, mi: int) -> datetime | None:
    """The instant of a wall-clock time in Memphis, or None when the clock time does not exist (the spring gap) or
    happens twice (the autumn overlap): such a row is dated to the day (review 2026-11-17 P2-12)."""
    a = datetime(d.year, d.month, d.day, h, mi, tzinfo=TZ, fold=0)
    b = a.replace(fold=1)
    if a.utcoffset() != b.utcoffset():
        return None
    back = a.astimezone(common.UTC if hasattr(common, "UTC") else ZoneInfo("UTC")).astimezone(TZ)
    return a if (back.hour, back.minute) == (h, mi) else None


def _start(r: dict, ampm_report: bool) -> tuple[datetime, str, str | None]:
    out = _start_raw(r, ampm_report)
    if out[1] == "minute":
        st = _local(out[0].date(), out[0].hour, out[0].minute)
        if st is None:
            d = out[0].date()
            return (datetime(d.year, d.month, d.day, tzinfo=TZ), "day",
                    f"the time {r.get('time')} {r.get('ampm') or ''} falls in the hour the change to or from daylight "
                    "time skips or repeats: the record is dated to the day")
    return out


def _start_raw(r: dict, ampm_report: bool) -> tuple[datetime, str, str | None]:
    d = date.fromisoformat(r["date"])
    t = r.get("time")
    if t:
        h, mi = (int(x) for x in t.split(":"))
        if r.get("ampm") and 1 <= h <= 12 and mi < 60:
            h = h % 12 + (12 if r["ampm"] == "PM" else 0)
            return datetime(d.year, d.month, d.day, h, mi, tzinfo=TZ), "minute", None
        if not r.get("ampm") and not ampm_report and 0 <= h < 24 and mi < 60 and (h, mi) != (0, 0):
            return datetime(d.year, d.month, d.day, h, mi, tzinfo=TZ), "minute", None
        note = (f"the time is written '{t}' with no AM or PM in a report that writes AM and PM: the record is dated to "
                "the day" if ampm_report else f"the time is written '{t}', which the table may use for no time: the record "
                "is dated to the day" if (h, mi) == (0, 0) else f"the time '{t}' is not a clock time: the record is dated "
                "to the day")
        return datetime(d.year, d.month, d.day, tzinfo=TZ), "day", note
    return datetime(d.year, d.month, d.day, tzinfo=TZ), "day", "the row gives no time: the record is dated to the day"


def row_ids(rows: list[dict], quarter: str | None = None) -> list[str]:
    """'<date>T<HHMM><AM|PM>|day:<street key>', '~<k>' for a later row of the same date, time and street in one report.
    The quarter is not part of the id, so a row repeated in a later report is the same record (review 2026-11-17
    P1-7); build() keeps the newest report's copy."""
    seen: Counter = Counter()
    out = []
    for r in rows:
        hm = (r.get("time") or "").replace(":", "").zfill(4) + (r.get("ampm") or "") if r.get("time") else "day"
        base = f"{r['date']}T{hm}:{street_key(r.get('location'))}"
        seen[base] += 1
        out.append(base if seen[base] == 1 else f"{base}~{seen[base]}")
    return out


def published_on(rep: dict) -> str | None:
    """The certification page's date as the report's publication date, unless it falls before the quarter's last day
    (the Q2 2024 report is dated 6/29/2024): a report of the whole quarter cannot be issued before it ends, so such a
    date is kept as written (raw.report_signed_on) and no publication date is given."""
    signed, period = rep.get("signed"), rep.get("period") or []
    if signed and len(period) == 2 and signed < period[1]:
        return None
    return signed


def to_records(quarter: str, rep: dict) -> list[dict]:
    out = []
    period = rep.get("period") or []
    published = published_on(rep)
    url = rep.get("url")
    folder = UPLOAD.search(url or "")
    for rid, r in zip(row_ids(rep["rows"], quarter), rep["rows"]):
        st, prec, tnote = _start(r, rep.get("ampm", False))
        raw = {"state": "TN", "county": COUNTY, "time_zone": TZ_NAME, "quarter": quarter, "report_period": period,
               "report_url": url, "report_sha256": rep.get("sha256"), "report_signed_on": rep.get("signed"),
               "location": r.get("location"), "cause": r.get("cause"), "overflow_source": r.get("source"),
               "volume_as_written": r.get("volume"), "duration_hours_as_written": r.get("duration"),
               "operator_permits": PERMITS, "_placement": "named_water_only",
               "place_note": "the City's table gives a street location in Memphis (Shelby County); house numbers "
                             "are removed and no point is taken from the street",
               "parser_version": rep.get("parser_version")}
        if rep.get("signed") and not published:
            raw["published_note"] = (f"the certification page is dated {rep['signed']}, before the quarter ended "
                                     f"({period[1]}): kept as written, not used as the publication date")
        if folder and not published:
            raw["report_posted_folder"] = f"{folder.group(1)}-{folder.group(2)}"
        if tnote:
            raw["time_note"] = tnote
        if r.get("water_withheld"):
            raw["receiving_water_withheld"] = r["water_withheld"]
        if r.get("water"):
            raw["receiving_water_as_written"] = r["water"]
            raw["flags_as_written"] = r.get("flags")      # Unpermitted Discharge, Appendix G Area, the third column
        if not r.get("location"):
            raw["place_note"] = ("the row's Location - Address cell is printed apart from its date in the report's text "
                                 "and is not tied to this row; the record gives no location")
        if r.get("mark"):
            raw["reach_mark"] = r["mark"]
            note = (rep.get("notes") or {}).get(r["mark"])
            if note:
                raw["reach_note"] = note
        if r.get("source", "").upper() == "BASEMENT":
            raw["source_note"] = "the table's Source is BASEMENT: a backup into a building"
        if len(period) == 2 and not (period[0] <= r["date"] <= period[1]):
            raw["date_note"] = (f"the date given lies outside the report's quarter ({period[0]} to {period[1]}); "
                                "kept as the City wrote it")
        end, status = None, "unknown"
        dur = r.get("duration")
        try:
            hours = float(dur.replace(",", "")) if dur else 0.0
        except ValueError:
            hours = 0.0
        if hours > 0:
            # the City's estimated duration bounds the end: the latest day it allows, at day precision, never a clock
            # time (the TDEC rows' rule, tn_transforms; review 2026-11-17 P1-4)
            e, basis = end_after(st, timedelta(minutes=-(-hours * 60 // 1)), "day")
            end, status = e.date().isoformat(), "ended"
            raw["ended_at_precision"] = "day"
            raw["ended_at_basis"] = (f"{basis} (the report's estimated duration, {dur} hours; the report gives no "
                                     "end time)")
        vol = (r.get("volume") or "").replace(",", "")
        try:
            gal = round(float(vol)) if vol else None
        except ValueError:
            gal = None
        out.append(event(
            source_id=SOURCE_ID, source_record_id=rid, event_type="sso", status=status,
            discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, npdes_permit=None,
            outfall_name=r.get("location"), waterbody_text=r.get("water"), water_slugs=[], water_match="none",
            started_at=st.isoformat() if prec == "minute" else r["date"], ended_at=end, time_precision=prec,
            reported_at=None, published_at=published, source_updated_at=None,
            fetched_at=rep.get("read_at") or now_iso(),
            material="untreated sewage", volume_gal=gal,
            volume_text=f"{r.get('volume')} gallons (estimated)" if gal is not None else None,
            estimate_flag="estimated", authority=AUTHORITY, source_url=url, raw=raw))
    return out


def link_tdec(records: list[dict], tdec: list[dict]) -> Counter:
    """Mark a record duplicate_of TDEC's record of a Memphis permit that began the same local day at the same street;
    none where either side has two of that day and street (tn_kub_sso_log.link_tdec)."""
    def day(v):
        if isinstance(v, str) and len(v) == 10:
            return date.fromisoformat(v)            # a date with no time is that day, in no zone
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(TZ).date()
        except (TypeError, ValueError):
            return None
    idx: dict[tuple, list[dict]] = {}
    for t in tdec:
        if (t.get("npdes_permit") not in PERMITS and t.get("discharger_id") != DISCHARGER_ID) or t.get("duplicate_of"):
            continue
        d, s = day(t.get("started_at")), _tdec_street(t)
        if d and s:
            idx.setdefault((d, s), []).append(t)
    ours = Counter((day(r["started_at"]), street_key(r["raw"].get("location"))) for r in records)
    counts = Counter()
    for r in records:
        key = (day(r["started_at"]), street_key(r["raw"].get("location")))
        cand = idx.get(key, [])
        if not cand:
            continue
        if len(cand) > 1 or ours[key] > 1:
            counts["not linked: several reports of one day and street"] += 1
            continue
        from build.status import waters_differ
        if waters_differ(r, cand[0]):
            counts["not linked: the two name different waters"] += 1      # review 2026-11-17 P1-8
            continue
        r["duplicate_of"] = cand[0]["event_id"]
        r["raw"]["_duplicate_basis"] = (f"TDEC's Events Report record of {DISCHARGER} (permit "
                                        f"{cand[0].get('npdes_permit')}) began the same day at the same street")
        counts["linked"] += 1
    return counts


def build(state: dict, tdec: list[dict] | None = None) -> tuple[list[dict], Counter]:
    by_id: dict[str, dict] = {}
    for q, rep in sorted((state.get("reports") or {}).items()):
        for r in to_records(q, rep):
            by_id[r["event_id"]] = r          # a row repeated in a later report: the newer copy (review P1-7)
    recs = list(by_id.values())
    links = link_tdec(recs, tdec if tdec is not None else (read_json(TDEC_EVENTS, {}) or {}).get("records") or [])
    recs.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return recs, links


# ---------------------------------------------------------------- reading

def read_report(state: dict, quarter: str, info: dict, content: bytes, at: str) -> None:
    rep = parse_report(pdf_pages(content))
    rep.update(url=info["url"], period=info.get("period"), sha256=hashlib.sha256(content).hexdigest(), read_at=at)
    prev = state.setdefault("reports", {}).get(quarter)
    attempt = {"url": rep["url"], "sha256": rep["sha256"], "read_at": at, "rows": len(rep["rows"]),
               "rows_not_read": rep["not_read"], "parser_version": PARSER_VERSION}
    if prev and prev.get("parser_version") == PARSER_VERSION and rep["not_read"] > prev.get("not_read", 0):
        # a new copy that reads less completely than the accepted one never replaces it (review 2026-11-17 P1-5)
        prev.setdefault("attempts", []).append(attempt)
        return
    rep["attempts"] = ((prev or {}).get("attempts") or []) + [attempt]
    state["reports"][quarter] = rep
    state.setdefault("pending", {}).pop(quarter, None)


def retained(prev: dict, state: dict, recs: list[dict]) -> list[dict]:
    """The previous events file's records of reports with no copy in the state (no state file, an emptied one, a
    report whose read failed): kept, so a failed read never drops an earlier record (review 2026-11-17 P1-6)."""
    have = set(state.get("reports") or {})
    ids = {r["event_id"] for r in recs}
    out = []
    for r in prev.get("records") or []:
        if not isinstance(r, dict) or r.get("event_id") in ids or (r.get("raw") or {}).get("quarter") in have:
            continue
        r = {**r, "raw": {**(r.get("raw") or {}),
                          "retained_from": "the previous events file (no copy of this report in the state)"}}
        out.append(r)
    return out


def due(state: dict, links: dict[str, dict], backfill: bool) -> list[str]:
    """Reports to fetch: on a backfill every listed report from BACKFILL_FROM not yet read (or listed at a new
    address); hourly the newest NEWEST of those, and every pending report."""
    listed = sorted(q for q, v in links.items() if v["period"][0] >= BACKFILL_FROM)
    newest = set(listed[-NEWEST:])
    out = []
    for q in listed:
        rep = (state.get("reports") or {}).get(q)
        changed = rep is not None and (rep.get("url") != links[q]["url"]
                                       or (rep.get("parser_version") or 0) < PARSER_VERSION)
        # a report never read: on a backfill, or hourly when among the newest; one read before at another address
        # or by an older parser: whatever its age (review 2026-11-17 P2-11)
        if (rep is None and (backfill or q in newest)) or changed or q in (state.get("pending") or {}):
            out.append(q)
    return out


def _get(url: str):
    return requests.get(url, headers=HEADERS, timeout=(20, 180))


def run(now: str, state_path: Path = STATE_PATH, out: Path | None = None, get=_get, backfill: bool = False,
        tdec: list[dict] | None = None) -> int:
    state = read_json(state_path, {}) or {}
    try:
        r = get(INDEX)
        r.raise_for_status()
        links = report_links(r.text)
        if not links:
            raise ReadError("the index lists no quarterly report")
    except (requests.RequestException, ValueError) as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        err = f"index not read ({type(e).__name__}{f', HTTP {code}' if code else ''})"     # never the message
        write_events(SOURCE_ID, [], ok=False, error=err, meta={"index": INDEX}, path=out)
        print(f"{SOURCE_ID}: FAILED {err}", file=sys.stderr)
        return 1
    state["index_read_at"] = now
    state["index_reports"] = links
    pend = state.setdefault("pending", {})
    for q in due(state, links, backfill):
        try:
            resp = get(links[q]["url"])
            resp.raise_for_status()
            read_report(state, q, links[q], resp.content, now)
        except Exception as e:   # one report's failure never stops the rest
            prev = pend.get(q) or {}
            code = getattr(getattr(e, "response", None), "status_code", None)
            why = (f"the report could not be fetched (HTTP {code})" if code else
                   f"the report could not be read ({type(e).__name__})")       # never the message (review P1-3)
            pend[q] = {"url": links[q]["url"], "reason": why,
                       "since": prev.get("since") or now, "last_tried": now}
    write_json(state_path, state)
    recs, tlinks = build(state, tdec)
    reps = state.get("reports") or {}
    held = retained(read_json(out if out else EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}, state, recs)
    recs += held
    listed = sorted(q for q, v in links.items() if v["period"][0] >= BACKFILL_FROM)
    meta = {"registry_ids": [SOURCE_ID], "index": INDEX, "credit": AUTHORITY, "time_zone": TZ_NAME,
            "covers_operator": DISCHARGER_ID, "carried_from": BACKFILL_FROM,
            "reports_read": {q: {"period": v.get("period"), "signed": v.get("signed"), "rows": len(v.get("rows") or []),
                                 "rows_not_read": v.get("not_read", 0), "read_at": v.get("read_at")}
                             for q, v in sorted(reps.items())},
            "listed_not_read": [q for q in listed if q not in reps and q not in pend],
            "rows_not_read": {q: v["not_read"] for q, v in sorted(reps.items()) if v.get("not_read")},
            "pending": dict(sorted(pend.items())), "tdec_links": dict(tlinks),
            "newest_listed": listed[-1] if listed else None,
            "retained_from_previous_events": sorted({(r.get("raw") or {}).get("quarter") or "" for r in held})}
    # the index was read: the feed is healthy; a report not read (tried again each run) and rows of a report not
    # read are named in meta (the backfill rule)
    problems = [f"report {q} not read ({v['reason']})" for q, v in sorted(pend.items())]
    problems += [f"report {q}: {n} rows not read" for q, n in meta["rows_not_read"].items()]
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(recs)} records from {len(reps)} reports (TDEC links {dict(tlinks)}"
          + (f"; named: {'; '.join(problems)}" if problems else "") + f") -> {path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help=f"read every listed report from {BACKFILL_FROM}")
    ap.add_argument("--file", help="a saved report PDF, read in place of the live one (needs --quarter and --out)")
    ap.add_argument("--quarter")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.file:
        if not (a.quarter and a.out):
            ap.error("--file needs --quarter and --out")
        out = Path(a.out)
        state_path = out.with_suffix(".state.json")
        state = read_json(state_path, {}) or {}
        read_report(state, a.quarter, {"url": Path(a.file).name, "period": None}, Path(a.file).read_bytes(), now_iso())
        write_json(state_path, state)
        recs, links = build(state)
        write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "tdec_links": dict(links)}, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records from {a.file}")
        return 0
    out = Path(a.out) if a.out else None
    return run(now_iso(), out.with_suffix(".state.json") if out else STATE_PATH, out, backfill=a.backfill)


if __name__ == "__main__":
    sys.exit(main())
