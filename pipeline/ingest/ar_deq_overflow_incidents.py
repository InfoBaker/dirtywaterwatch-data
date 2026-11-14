"""Arkansas DEQ: Reported Noncompliance Incident Data (sewer overflows, bypasses, upsets and unpermitted discharges
reported on DEQ's 24-hour online forms) -> data/build/events/ar-deq-overflow-incidents.json

Source
  https://adeq.state.ar.us/water/enforcement/sso/data.aspx (registry: ar-deq-overflow-incidents), the Division of
  Environmental Quality's public search of the reports permittees file through its 24-hour online forms ("Any Sanitary
  Sewer Overflow (SSO), no matter how small", every unanticipated bypass, every upset, every unpermitted discharge
  "regardless of whether it reaches waters of the state"). A classic ASP.NET page with a plain HTML form: the search is
  a POST of the visible fields (facility, permit, miscellaneous text, four type boxes, a date range on the day the
  overflow began) and the result pages are the same POST with the page's own hidden paging fields (PageNo,
  RecordsPerPage up to 100, Sort, SortASC), exactly what a visitor's browser sends when it clicks a page link. No
  session, cookie, token or view state is involved; nothing is submitted to the reporting forms. The page states
  "Data current as of <date>" (meta.data_current_as_of).

  How the search behaves (read 2026-11-14): with no type box ticked it returns every type; two or more boxes return
  nothing (the boxes are combined with AND), so this module never ticks a box. The date range selects on the day the
  overflow began. Each result row has the permit, facility, location text, the days the overflow started and stopped,
  the day DEQ received the report, the volume in gallons, the impact (DEQ's checkbox: reached receiving water, public
  land only, private property, treatment plant, basement backup), the type, the environmental damage, and a detail row
  with the Web Confirmation Number (a GUID per report), cause, action taken and type of overflow; an optional third
  row holds the filer's comments.

  Completeness: each window's "Recs Found" count is read from the page and the run fails (ok false, previous records
  kept) unless the distinct confirmation numbers read equal it; a window DEQ reports as empty must say "Recs Found: 0"
  in a page that has the result table, else the run fails too. Pages are read at 100 rows, sorted by the start date.

What is read (privacy)
  SAFE_FIELDS only. Never read: the Comments row (the filer's free text: it can name residents, staff and
  contractors), and nothing the page does not show (the forms also collect the filer's name, phone and e-mail; the
  search does not show them). Location, cause, action taken and type of overflow go through the strict free-text
  scrub (house numbers, unit numbers, phones, e-mails and people's names cut) before anything is saved; the facility
  name that reads as only a person's becomes "[name removed]" (common.scrub_discharger). data/raw keeps only the
  scrubbed safe rows (dww-safe-rows/1), never a page.

Record rules: the fetch block in data/sources/ar-deq-overflow-incidents.yaml and ingest/ar_transforms.py
  (ar_deq_record), through the generic field map, history and redaction (ingest/generic/runner.build); this module
  only fetches.

Polling window
  Each run reads the reports whose overflow began in the last WINDOW_DAYS days (two pages or so). Records whose start
  is older than the window were not asked for: they are carried from the previous events file as read (their safe
  row replayed), so they are never marked missing from the source; a report inside the window that DEQ no longer
  lists is kept with the missing mark (history.keep_missing). --backfill FROM reads from that day, a month at a time.

Run from pipeline/:  python -m ingest.ar_deq_overflow_incidents [--backfill 2025-01-01] [--file saved.json]
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, ROOT, now_iso, path_notes_to_meta, read_json, save_raw, write_events
from ingest.generic import runner

SOURCE_ID = "ar-deq-overflow-incidents"
URL = "https://adeq.state.ar.us/water/enforcement/sso/data.aspx"
TZ = ZoneInfo("America/Chicago")
WINDOW_DAYS = 120
PAGE_SIZE = 100
PAUSE_S = 2.0
TIMEOUT_S = 180
MAX_PAGES = 60                      # per window; a month has two at most
# the result table's columns (the td headers attribute) -> safe field
COLUMNS = {
    "NPDES Permit Number": "permit_no",
    "Facility Name": "facility_name",
    "Location": "location",
    "Date Overflow Started": "date_started",
    "Date Overflow Stopped": "date_stopped",
    "Date Reported": "date_reported",
    "Volume": "volume_gal",
    "Impact": "impact",
    "Type": "incident_type",
    "Environmental Damage": "environmental_damage",
}
# the detail row's bold labels -> safe field; "Comments" is never read
DETAIL = {
    "Web Confirmation Number": "confirmation_no",
    "Cause": "cause",
    "Action Taken": "action_taken",
    "Type of Overflow": "overflow_type",
}
SAFE_FIELDS = list(COLUMNS.values()) + list(DETAIL.values())
RECS = re.compile(r"Recs\s+Found</abbr>\s*:\s*(?:&nbsp;|\s)*([\d,]+)", re.I)
PAGES = re.compile(r"<b>\s*/\s*([\d,]+)\s*</b>")
CURRENT = re.compile(r"Data\s+current\s+as\s+of\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
TD = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.S | re.I)
HEADERS_ATTR = re.compile(r"""headers\s*=\s*["']([^"']+)["']""", re.I)
LABEL = re.compile(r"<b>\s*([^<]{2,40}?)\s*:?\s*</b>(.*?)(?=<b>|$)", re.S | re.I)


class SearchFailed(RuntimeError):
    """A window that could not be read whole: the run keeps the previous records."""


def text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", " ", fragment or "", flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def form(start: date, end: date, page: int = 1) -> dict:
    """The POST a visitor's browser sends: the search fields as typed (no type box ticked: every type) and, for a page
    after the first, the result form's own paging fields."""
    return {"T_FacilityName": "", "T_NPID": "", "T_MiscSearch": "",
            "T_DateStart": start.strftime("%m/%d/%Y"), "T_DateEnd": end.strftime("%m/%d/%Y"), "Search": "Search",
            "PageNo": str(page), "RecordsPerPage": str(PAGE_SIZE), "Sort": "DateOverflowStarted", "SortASC": "True"}


def parse_page(page: str) -> tuple[list[dict], int | None, int | None, str | None]:
    """(rows of the page with SAFE_FIELDS only, Recs Found, the page count, the data-current date). The Comments row
    is skipped unread."""
    m = RECS.search(page)
    found = int(m.group(1).replace(",", "")) if m else None
    m = PAGES.search(page)
    pages = int(m.group(1).replace(",", "")) if m else None
    m = CURRENT.search(page)
    current = m.group(1) if m else None
    i = page.find("</tfoot>")
    body = page[i:page.find("</table>", i)] if i >= 0 else ""
    rows: list[dict] = []
    cur: dict | None = None
    for tr in TR.findall(body):
        cells = TD.findall(tr)
        heads = {(HEADERS_ATTR.search(a).group(1) if HEADERS_ATTR.search(a) else ""): v for a, v in cells}
        if "NPDES Permit Number" in heads:
            cur = {COLUMNS[h]: text(v) for h, v in heads.items() if h in COLUMNS}
            rows.append(cur)
        elif "Comments" in heads:
            continue                        # the filer's comments: never read
        elif cur is not None and "Web Confirmation Number" in tr:
            inner = cells[0][1] if cells else tr
            for lab, val in LABEL.findall(inner):
                key = DETAIL.get(lab.strip().rstrip(":").strip())
                if key:
                    cur[key] = text(val)
    for r in rows:
        for f in SAFE_FIELDS:
            r.setdefault(f, "")
    return rows, found, pages, current


def post(sess: requests.Session, data: dict) -> str:
    r = sess.post(URL, data=data, timeout=TIMEOUT_S, headers={**HEADERS})
    r.raise_for_status()
    return r.text


def query(sess: requests.Session, start: date, end: date, pause: float = PAUSE_S) -> tuple[list[dict], str | None]:
    """Every report whose overflow began from start to end (days, inclusive). A window with more reports than one
    page holds is split in halves and each half asked again (DEQ sorts on the start day, which is not unique, so rows
    tied on it may change places between page requests); only a single day with more than a page is paged. Raises
    SearchFailed unless the rows read equal the page's Recs Found."""
    first = post(sess, form(start, end))
    got, found, pages, current = parse_page(first)
    if found is None or "tblGrid" not in first:
        raise SearchFailed(f"{start}..{end}: the result table or its count is missing from the page")
    if found > len(got) and end > start:
        mid = start + (end - start) // 2
        time.sleep(pause)
        a, cur = query(sess, start, mid, pause)
        time.sleep(pause)
        b, _ = query(sess, mid + timedelta(days=1), end, pause)
        rows = a + b
        if len(rows) != found:
            raise SearchFailed(f"{start}..{end}: the halves hold {len(rows)} reports, the whole {found}")
        return rows, current or cur
    rows = list(got)
    for p in range(2, min(pages or 1, MAX_PAGES) + 1):
        time.sleep(pause)
        more, f2, _, _ = parse_page(post(sess, form(start, end, p)))
        if f2 is not None and f2 != found:
            raise SearchFailed(f"{start}..{end}: the count changed between pages ({found} then {f2})")
        rows += more
    if len(rows) != found:
        raise SearchFailed(f"{start}..{end}: {len(rows)} reports read, the page says {found}")
    return rows, current


def windows(start: date, end: date):
    """Calendar-month windows from start to end."""
    a = start
    while a <= end:
        nxt = (a.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield a, min(end, nxt - timedelta(days=1))
        a = nxt


def fetch(start: date, end: date, pause: float = PAUSE_S) -> tuple[list[dict], dict]:
    sess = requests.Session()
    rows, current, n = [], None, 0
    for a, b in windows(start, end):
        if n:
            time.sleep(pause)
        got, cur = query(sess, a, b, pause)
        rows += got
        current = current or cur
        n += 1
    out = rows
    return out, {"windows": n, "window_start": start.isoformat(), "window_end": end.isoformat(),
                 "data_current_as_of": current}


def started_day(row: dict) -> date | None:
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", row.get("date_started") or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def carried_rows(prev_records: list[dict], window_start: date, have: set[str]) -> list[dict]:
    """The safe rows of earlier records whose overflow began before the polled window (not asked for this run, so not
    missing from the source); a record already marked missing stays as the history left it."""
    out = []
    for r in prev_records:
        raw = r.get("raw") or {}
        row = raw.get("row") or {}
        k = row.get("confirmation_no")
        if not k or k in have or raw.get("_missing_from_source_since") or r.get("duplicate_of"):
            continue
        d = started_day(row)
        if d is not None and d < window_start:
            out.append({f: row.get(f, "") for f in SAFE_FIELDS})
            have.add(k)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", help="read from this day (YYYY-MM-DD) instead of the last WINDOW_DAYS days")
    ap.add_argument("--file", help="a saved dww-safe-rows/1 file to replay instead of fetching")
    ap.add_argument("--out", help="write the events file here")
    a = ap.parse_args(argv)
    row, block = runner.load_source(SOURCE_ID)
    path = Path(a.out) if a.out else EVENTS_DIR / f"{SOURCE_ID}.json"
    prev_doc = read_json(path, {}) or {}
    prev = prev_doc.get("records") or []
    fetched_at = now_iso()
    today = datetime.now(TZ).date()
    try:
        if a.file:
            doc = json.loads(Path(a.file).read_text())
            rows, info = list(doc.get("rows") or []), dict((doc.get("meta") or {}).get("ar_search") or {})
            start = date.fromisoformat(info.get("window_start") or "1990-01-01")
        else:
            start = date.fromisoformat(a.backfill) if a.backfill else today - timedelta(days=WINDOW_DAYS)
            rows, info = fetch(start, today)
    except (requests.RequestException, SearchFailed, ValueError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=path)
        print(f"{SOURCE_ID}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    raw_path = None
    if not a.file:
        safe = [runner.F.safe_row(r, block)[0] for r in rows]
        doc = {"format": runner.SAFE_ROWS_FORMAT, "rows": safe, "meta": {"ar_search": info}}
        p = save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False, sort_keys=True).encode(), "json")
        raw_path = str(p.relative_to(ROOT))
    polled = len(rows)
    have = {r.get("confirmation_no") for r in rows}
    rows = rows + carried_rows(prev, start, have)
    try:
        records, stats = runner.build(SOURCE_ID, block, rows, fetched_at, prev, None)
    except Exception as e:  # noqa: BLE001 - a run that cannot finish keeps the previous records
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=path)
        print(f"{SOURCE_ID}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    meta = {**stats, **runner.public_meta(block.get("meta") or {}), "platform": "html-form", "raw_path": raw_path,
            "generic": True, "registry_ids": row.get("registry_ids") or [], "timezone": block.get("time_zone"),
            "rows_polled": polled, "rows_carried": len(rows) - polled, **info}
    path_notes_to_meta(records, meta)
    out = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta, path=path)
    print(f"{SOURCE_ID}: {polled} rows polled ({info.get('window_start')}..{info.get('window_end')}), "
          f"{len(rows) - polled} carried -> {len(records)} records; types {stats.get('by_type')}; -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
