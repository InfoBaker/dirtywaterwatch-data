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
  kept) unless the rows read equal it; a page without the result table or its count fails the run too, so a failed
  search is never read as an empty one. A window holding more reports than one page (100 rows) is split in halves
  and each half asked again, because DEQ sorts on the start day, which is not unique, and rows tied on it may change
  places between page requests; only a single day with more than 100 reports would be paged.

What is read (privacy)
  SAFE_FIELDS only. Never read: the Comments row (the filer's free text: it can name residents, staff and
  contractors), and nothing the page does not show (the forms also collect the filer's name, phone and e-mail; the
  search does not show them). Location, cause, action taken and type of overflow go through the strict free-text
  scrub (house numbers, unit numbers, phones, e-mails and people's names cut) before anything is saved; the facility
  name that reads as only a person's becomes "[name removed]" (common.scrub_discharger). A report whose impact is
  "SSO Affected Private Property (ground)" or "Basement Backup" keeps no location text at all (privacy_cut: often a
  home). data/raw keeps only the scrubbed safe rows (dww-safe-rows/1), never a page.

Record rules: the fetch block in data/sources/ar-deq-overflow-incidents.yaml and ingest/ar_transforms.py
  (ar_deq_record), through the generic field map, history and redaction (ingest/generic/runner.build); this module
  only fetches.

Polling window
  Each run reads the reports whose overflow began in the last WINDOW_DAYS days (two pages or so). Records whose start
  is older than the window were not asked for: they are carried from the previous events file as read (their safe
  row replayed), so they are never marked missing from the source; a report inside the window that DEQ no longer
  lists is kept with the missing mark (history.keep_missing). Once a week (DEEP_EVERY_DAYS, meta.deep_read_at) the run
  reads back to DEEP_FROM instead, about thirty requests, so a report filed months late (9 of the 2,449 read on
  2026-11-14 reached DEQ more than 120 days after the overflow began) and a report DEQ removed are both seen.
  --backfill FROM reads from that day, a month at a time.

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
from common import error_text
from ingest.generic import runner

SOURCE_ID = "ar-deq-overflow-incidents"
URL = "https://adeq.state.ar.us/water/enforcement/sso/data.aspx"
TZ = ZoneInfo("America/Chicago")
WINDOW_DAYS = 120
DEEP_FROM = date(2025, 1, 1)        # the first day this site reads; a weekly read goes back to it
DEEP_EVERY_DAYS = 7
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
SAFE_FIELDS = list(COLUMNS.values()) + list(DETAIL.values()) + ["location_withheld"]
PRIVATE_IMPACT = re.compile(r"affected\s+private\s+property|basement\s+backup", re.I)
RECS = re.compile(r"Recs\s+Found</abbr>\s*:\s*(?:&nbsp;|\s)*([\d,]+)", re.I)
PAGES = re.compile(r"<b>\s*/\s*([\d,]+)\s*</b>")
CURRENT = re.compile(r"Data\s+current\s+as\s+of\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
TR = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
TD = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.S | re.I)
HEADERS_ATTR = re.compile(r"""headers\s*=\s*["']([^"']+)["']""", re.I)
LABEL = re.compile(r"<b>\s*([^<]{2,40}?)\s*:?\s*</b>(.*?)(?=<b>|$)", re.S | re.I)


class SearchFailed(RuntimeError):
    """A window that could not be read whole: the run keeps the previous records."""


CONFIRMATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{5,63}$")
MAX_NO_ID_SHARE = 0.05
NO_ID_REASON = ("no readable Web Confirmation Number (DEQ's key for the report); left out of this read and asked for "
                "again at the next")


def check_ids(rows: list[dict]) -> tuple[list[dict], int, str | None]:
    """(the reports that carry DEQ's Web Confirmation Number, how many did not). The number is the record key: a
    report without one would be keyed 'no-id' and collapse with every other such report, so it is never built or
    saved. A few such reports are left out of this read (the events file says how many and why; the next read asks
    for them again); none read, or more than MAX_NO_ID_SHARE of them without one (a changed detail row), is
    SearchFailed before anything is saved and the run keeps the previous records (verification 2026-11-15 P2-6)."""
    good = [r for r in rows if CONFIRMATION.match((r.get("confirmation_no") or "").strip())]
    bad = len(rows) - len(good)
    if bad and (not good or bad > max(1, MAX_NO_ID_SHARE * len(rows))):
        raise SearchFailed(f"{bad} of {len(rows)} reports have no readable Web Confirmation Number (a blank number or "
                           "a changed detail row); nothing is saved")
    days = [started_day(r) for r in rows if r not in good]
    known = [d for d in days if d is not None]
    # the earliest overflow day among those left out: the next read goes back at least that far (None: unknown)
    retry = min(known).isoformat() if known and len(known) == len(days) else None
    return good, bad, retry


# a point written into the report's own words ("35.123456, -93.654321", "Lat 35.1234 Long -93.6543", "35°12'34.5\"N
# 93°45'12\"W"): a filer's point, which can be a home; cut to 0.001 degree before any save (verification 2 P1-3), in
# every decimal, degree-minute-second and degree-decimal-minute form (ar_transforms.scrub_coord_text; verification 3)
COORD_TEXT_FIELDS = ("location", "cause", "action_taken", "overflow_type", "environmental_damage", "impact",
                     "facility_name")


def round_coords(row: dict) -> dict:
    """The row with every coordinate in its free text cut to three decimals (the event-point rule)."""
    from ingest import ar_transforms as T
    return {**row, **{f: T.scrub_coord_text(row[f]) for f in COORD_TEXT_FIELDS if isinstance(row.get(f), str)}}


def carried_state(records: list[dict]) -> list[dict]:
    """The records of the previous events file with every point in their words cut the same way (raw.row, the
    revisions' old values, tracked values, the outfall name and every other place in words): a record an older rule
    saved with a finer point is cut before it is read, rebuilt or written again, failed runs included (verification
    3 P1)."""
    from ingest import ar_transforms as T
    return [T.scrub_coords_deep(r) for r in records or [] if isinstance(r, dict)]


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
    rows = [privacy_cut(r) for r in rows]
    for r in rows:
        for f in SAFE_FIELDS:
            r.setdefault(f, "")
    return rows, found, pages, current


def privacy_cut(row: dict) -> dict:
    """Before anything is saved: a report whose impact is private property or a basement backup is often at a home, so
    its location text is dropped (location_withheld says why); an impact that is not one of DEQ's checkbox labels is
    the filer's own words, which can name people and homes, so only the water names it gives are kept
    (ar_transforms.water_names; review 2026-11-14 P1-5)."""
    from ingest import ar_transforms as T
    impact = (row.get("impact") or "").strip()
    if impact and not T.DEQ_IMPACTS.match(impact):
        names, _ = T.water_names(impact)
        row = {**row, "impact": "; ".join(names)}
    if PRIVATE_IMPACT.search(row.get("impact") or "") and row.get("location"):
        return {**row, "location": "", "location_withheld": "private property: DEQ's impact for this report"}
    return row


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


def carried_rows(prev_records: list[dict], window_start: date, polled: set[str]) -> list[dict]:
    """The safe rows of earlier records whose overflow began before the polled window (not asked for this run, so not
    missing from the source), DEQ's repeated rows included (the block's dedupe marks the copy again); a record already
    marked missing stays as the history left it."""
    out = []
    for r in prev_records:
        raw = r.get("raw") or {}
        row = raw.get("row") or {}
        k = row.get("confirmation_no")
        if not k or k in polled or raw.get("_missing_from_source_since"):
            continue
        d = started_day(row)
        if d is not None and d < window_start:
            out.append({f: row.get(f, "") for f in SAFE_FIELDS})
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
    prev = carried_state(prev_doc.get("records") or [])
    fetched_at = now_iso()
    today = datetime.now(TZ).date()
    try:
        if a.file:
            doc = json.loads(Path(a.file).read_text())
            rows, info = list(doc.get("rows") or []), dict((doc.get("meta") or {}).get("ar_search") or {})
            start = date.fromisoformat(info.get("window_start") or "1990-01-01")
        else:
            last_deep = (prev_doc.get("meta") or {}).get("deep_read_at")
            deep = not last_deep or (datetime.fromisoformat(last_deep.replace("Z", "+00:00")).astimezone(TZ).date()
                                     <= today - timedelta(days=DEEP_EVERY_DAYS))
            start = (date.fromisoformat(a.backfill) if a.backfill
                     else DEEP_FROM if deep else today - timedelta(days=WINDOW_DAYS))
            # a report left out of an earlier read (no confirmation number) is asked for again until it is read
            # (verification 2 P2-2): the read goes back to the earliest day among them
            retry_from = (prev_doc.get("meta") or {}).get("retry_from")
            if retry_from:
                start = min(start, date.fromisoformat(retry_from))
            rows, info = fetch(start, today)
            if start <= DEEP_FROM:
                info["deep_read_at"] = fetched_at
            elif last_deep:
                info["deep_read_at"] = last_deep
        rows, no_id, retry_day = check_ids(rows)
        rows = [round_coords(r) for r in rows]
        if no_id:
            # an incomplete read: the weekly deep read is not counted as done, and the next read goes back to the
            # earliest report left out (or to this read's start where its day is unknown)
            info["retry_from"] = retry_day or start.isoformat()
            if not a.file:
                if last_deep:
                    info["deep_read_at"] = last_deep
                else:
                    info.pop("deep_read_at", None)
    except (requests.RequestException, SearchFailed, ValueError, OSError) as e:
        # the previous records, every one of them, written back with their points cut (partial: health false,
        # last_ok_at kept, the previous meta kept)
        write_events(SOURCE_ID, prev, ok=False, error=f"{error_text(e)}", path=path, partial=True)
        print(f"{SOURCE_ID}: FAILED {error_text(e)}", file=sys.stderr)
        return 1
    raw_path = None
    if not a.file:
        safe = [runner.F.safe_row(r, block)[0] for r in rows]
        doc = {"format": runner.SAFE_ROWS_FORMAT, "rows": safe, "meta": {"ar_search": info}}
        p = save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False, sort_keys=True).encode(), "json")
        raw_path = str(p.relative_to(ROOT))
    polled = len(rows)
    rows = rows + [round_coords(r) for r in carried_rows(prev, start, {r.get("confirmation_no") for r in rows})]
    try:
        records, stats = runner.build(SOURCE_ID, block, rows, fetched_at, prev, None)
        records = carried_state(records)
    except Exception as e:  # noqa: BLE001 - a run that cannot finish keeps the previous records
        write_events(SOURCE_ID, prev, ok=False, error=f"{error_text(e)}", path=path, partial=True)
        print(f"{SOURCE_ID}: FAILED {error_text(e)}", file=sys.stderr)
        return 1
    if no_id:
        stats = {**stats, "unreadable_reports": {"count": no_id, "reason": NO_ID_REASON}}
    meta = {**stats, **runner.public_meta(block.get("meta") or {}), "platform": "html-form", "raw_path": raw_path,
            "generic": True, "registry_ids": row.get("registry_ids") or [], "timezone": block.get("time_zone"),
            "rows_polled": polled, "rows_carried": len(rows) - polled, **info}
    path_notes_to_meta(records, meta)
    if no_id:
        # an incomplete read (verification 2 P2-2): the readable reports are written, the run is not ok, last_ok_at
        # stays the previous one and the error stays until the left-out reports are read
        meta.setdefault("deep_read_at", None)
        write_events(SOURCE_ID, records, ok=False, error=f"{no_id} report(s): {NO_ID_REASON}", meta=meta, path=path,
                     partial=True)
        print(f"{SOURCE_ID}: incomplete, {no_id} report(s) left out ({NO_ID_REASON})", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta, path=path)
    print(f"{SOURCE_ID}: {polled} rows polled ({info.get('window_start')}..{info.get('window_end')}), "
          f"{len(rows) - polled} carried -> {len(records)} records; types {stats.get('by_type')}; -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
