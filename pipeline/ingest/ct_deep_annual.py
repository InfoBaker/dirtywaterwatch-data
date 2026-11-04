"""CT DEEP Sewage Right-to-Know annual spreadsheets (2021-2025 data) -> data/build/events/ct-deep-annual.json.

Source
------
DEEP's Sewage Right-to-Know page (https://portal.ct.gov/deep/water/municipal-wastewater/
ct-sewage-right-to-know) links, for each annual report due February 1 under CGS 22a-424a(c)(5),
three workbooks under https://portal.ct.gov/-/media/deep/water/municipal_wastewater/
srtk-annual-report/:

  <report year>-cso-event-report.xlsx (2022-2024) / -cso-bypass.xlsx (2025-2026): one tab per CSO
      utility (BPT, GNHWPCA, MDC, NORWALK, NORWICH, WATERBURY).
  <report year>-sso-event-report.xlsx / -sso-bypass.xlsx: one tab per town, SSOs and NPDES
      permitted bypasses.
  <report year>-annual-report.xlsx: CSO SUMMARY, SSO SUMMARY, REACHED WATER SUMMARY (totals; the
      CSO count leaves out zero-flow and rescinded reports, so it can be below the row count).

Columns: the 2023-2026 workbooks use the Performance Dashboard's columns plus "Final Volume
Converted for counting" (DEEP's number in gallons); only the 2026 workbooks carry Request ID.
The 2022 workbooks (2021 data) use the pre-QAlert form's columns ("Regulator activated"
"01/16/2021, 5:00 AM", "Bypass Began or Discovered", "DEEP Estimate"), mapped here to the
dashboard names; 2021 events before December also sit in the ArcGIS archive
(ingest/ct_deep_archive.py), not linked here. Some rows were never on the dashboard: MDC's
treatment-plant bypasses "REPORTED THROUGH MOR" (monthly operating report) have no Request ID.

A report year holds the previous calendar year (the 2026 report is 2025 data). These are the
same QAlert reports the dashboard shows (ingest/ct_deep.py), closed and reconciled by DEEP, and
they fill what the dashboard's 200-row limit cannot reach for 2021-2025. They also keep the CSO
Group Name and Receiving Waterbody that the dashboard rows lost.

Request mechanics: plain GETs of the 15 workbooks (no login; a few MB in all). Every file is
saved with save_raw() and its Last-Modified header becomes published_at for its records.
--cached re-reads the newest saved copy of each file instead of downloading. The workbooks are
read with the standard library (zip + XML); dates are Excel serial days.

Normalisation: each row goes through ingest/ct_deep.normalise (the same field rules, event
types, status rules, volume parsing and water matching as the dashboard), then:
- source_id ct-deep-annual; source_record_id = the Request ID when present (the dashboard's
  record id), so the event id is ct-deep-annual:<Request ID>, and the extra top-level key
  duplicate_of = "ct-deep:<Request ID>" when data/build/events/ct-deep.json has that record
  (the dashboard record stays the primary; build/status.py's own permit + day linking covers
  the rest). Rows without a Request ID get a deterministic id "x" + sha1(permittee | start |
  outfall)[:12] (a "-2", "-3" suffix for exact repeats, in file order).
- volume_gal = "Final Volume Converted for counting" when present (DEEP's own conversion), with
  volume_text the operator's text; else the dashboard volume parsing.
- published_at = the workbook's Last-Modified; raw._source_file = workbook name and tab.
- authority "<permittee> (CT DEEP Sewage Right-to-Know annual report <report year>)".
- Status: the workbook's Status when given; a row with no Status column value but an end time
  is ended (closed annual record).
- raw is the workbook row as DEEP wrote it (personal fields and phone/email text removed).
Rows that are not events (blank, "NO REPORTED BYPASSES AT 002-1") are skipped; a row that has a
date or Request ID but cannot be read is kept with parse_error (event_type unknown when the
type cannot be told). Dates are kept as DEEP typed them (one 2025 MDC row reads 09/07/2026).

Cadence: annual (the report is due February 1; the 2026 files were last modified 2026-02-25).
Run once a year, or with --cached to rebuild.

Run from pipeline/: python -m ingest.ct_deep_annual [--cached]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO

import requests

from common import EVENTS_DIR, HEADERS, RAW_DIR, event, now_iso, read_json, save_raw, write_events
from ingest.ct_deep import TZ, clean, discharger_for, normalise, report_parts, scrub
from ingest.ct_deep_archive import utility_key


def report_label(row: dict) -> str | None:
    return report_parts(row.get("Report Type"))[1]

SOURCE_ID = "ct-deep-annual"
BASE = "https://portal.ct.gov/-/media/deep/water/municipal_wastewater/srtk-annual-report/"
PAGE_URL = "https://portal.ct.gov/deep/water/municipal-wastewater/ct-sewage-right-to-know"
FILES = {  # report year -> (cso workbook, sso workbook, summary workbook)
    2022: ("2022-cso-event-report.xlsx", "2022-sso-event-report.xlsx", "2022-annual-report.xlsx"),
    2023: ("2023-cso-event-report.xlsx", "2023-sso-event-report.xlsx", "2023-annual-report.xlsx"),
    2024: ("2024-cso-event-report.xlsx", "2024-sso-event-report.xlsx", "2024-annual-report.xlsx"),
    2025: ("2025-cso-bypass.xlsx", "2025-sso-bypass.xlsx", "2025-annual-report.xlsx"),
    2026: ("2026-cso-bypass.xlsx", "2026-sso-bypass.xlsx", "2026-annual-report.xlsx"),
}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
EXCEL_EPOCH = date(1899, 12, 30)


# ---------------------------------------------------------------- xlsx (standard library)

def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(content: bytes) -> dict[str, list[list]]:
    """{sheet name: rows (lists of cell strings or None)}."""
    z = zipfile.ZipFile(BytesIO(content))
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            ss.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in
            ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall("pr:Relationship", NS)}
    out = {}
    for sh in wb.find("m:sheets", NS):
        target = rels[sh.get(f"{{{NS['r']}}}id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter(f"{{{NS['m']}}}row"):
            vals = {}
            for c in row.findall("m:c", NS):
                t, v = c.get("t"), c.find("m:v", NS)
                if t == "s" and v is not None:
                    val = ss[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                else:
                    val = v.text if v is not None else None
                vals[_col(c.get("r"))] = val
            rows.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
        out[sh.get("name")] = rows
    return out


def excel_date(v) -> str | None:
    """Excel serial day -> 'MM/DD/YYYY' (the dashboard's text form); text dates pass through."""
    s = clean(v)
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s) and 20000 < float(s) < 80000:
        d = EXCEL_EPOCH + timedelta(days=int(float(s)))
        return d.strftime("%m/%d/%Y")
    return s


def excel_time(v) -> str | None:
    """A fraction of a day (0.5625) -> '01:30 PM'; text passes through."""
    s = clean(v)
    if s and re.fullmatch(r"0?\.\d+|0|1", s):
        mins = round(float(s) * 1440) % 1440
        h, m = divmod(mins, 60)
        return f"{(h % 12) or 12:02d}:{m:02d} {'AM' if h < 12 else 'PM'}"
    return s


# ---------------------------------------------------------------- fetch

def fetch(name: str, cached: bool, session: requests.Session) -> tuple[bytes, str | None, str]:
    """(content, published_at, how)"""
    if cached:
        saved = sorted((RAW_DIR / SOURCE_ID).glob(f"*.{name}"))
        if saved:
            meta = read_json(saved[-1].with_name(saved[-1].name + ".headers.json"), {}) or {}
            return saved[-1].read_bytes(), meta.get("published_at"), f"cached {saved[-1].name}"
    r = session.get(BASE + name, timeout=120)
    r.raise_for_status()
    lm = r.headers.get("Last-Modified")
    published = parsedate_to_datetime(lm).astimezone(UTC).isoformat().replace("+00:00", "Z") if lm else None
    p = save_raw(SOURCE_ID, r.content, name)
    p.with_name(p.name + ".headers.json").write_text(json.dumps(
        {"url": BASE + name, "last_modified": lm, "published_at": published,
         "content_length": len(r.content), "fetched_at": now_iso()}, indent=1))
    time.sleep(1)
    return r.content, published, "downloaded"


# ---------------------------------------------------------------- rows

HEADER_KEYS = {"Request ID", "Report Type", "Reporting Utility", "Date Activated", "Date Bypass Began or was Discovered",
               "Utility", "Regulator activated", "Bypass Began or Discovered"}
# The 2022 report (2021 data) still uses the pre-QAlert form's columns: map them to the dashboard's
OLD_CSO = {"CSO Town": "Muncipality", "Regulator Name": "CSO Group Name", "Receiving Water body": "Receiving Waterbody",
           "Total Estimated Volume": "Final Volume", "DEEP Estimate": "Final Volume Converted for counting"}
OLD_SSO = {"Utility": "Reporting Utility", "Town": "Municipality", "Closest Street Address": "Address",
           "Location": "Location of Bypass", "How was event discovered?": "How was Incident Discovered",
           "Estimate Quantity or Volume": "Estimated Quantity or Rate of Discharge",
           "Quantity or Volume determined": "How was estimated Quantity or Rate Determined", "Final Volume": "Final Quantity",
           "DEEP ESTIMATE FOR REPORT": "Final Volume Converted for counting", "Reach Waterbody?": "Reach Waterbody"}


def split_dt(v) -> tuple[str | None, str | None]:
    """'01/16/2021, 5:00 AM' or an Excel serial date-time -> ('01/16/2021', '05:00 AM')."""
    s = clean(v)
    if not s:
        return None, None
    if re.fullmatch(r"\d+(\.\d+)?", s) and 20000 < float(s) < 80000:
        f = float(s)
        return excel_date(str(int(f))), (excel_time(str(f - int(f))) if f != int(f) else None)
    m = re.match(r"^\s*([\d/.-]+)\s*,?\s*(.*)$", s)
    return (m.group(1), clean(m.group(2))) if m else (s, None)


def translate_old(kind: str, row: dict) -> dict | None:
    """2021-format row -> dashboard column names (None when the row is not in that format)."""
    if kind == "cso" and "Regulator activated" in row:
        out = {OLD_CSO.get(k, k): v for k, v in row.items() if k not in ("Regulator activated", "Regulator Stopped")}
        out["Report Type"] = f"CSO - {clean(row.get('Utility')) or ''}"
        out["Date Activated"], out["Event Start Time"] = split_dt(row.get("Regulator activated"))
        out["Date Ceased"], out["Event End Time"] = split_dt(row.get("Regulator Stopped"))
        return out
    if kind == "sso" and "Bypass Began or Discovered" in row:
        out = {OLD_SSO.get(k, k): v for k, v in row.items() if k not in ("Bypass Began or Discovered", "Bypass Ended")}
        out["Date Bypass Began or was Discovered"], out["Event Start Time"] = split_dt(row.get("Bypass Began or Discovered"))
        out["Date Bypass Ended"], out["Event End Time"] = split_dt(row.get("Bypass Ended"))
        return out
    return None


def sheet_rows(rows: list[list]) -> list[dict]:
    """Rows under the header line (the first row naming Request ID or a date column)."""
    out, header = [], None
    for i, r in enumerate(rows):
        cells = [clean(x) for x in r]
        if header is None:
            names = {re.sub(r"\s+", " ", c).strip() for c in cells if c}
            if len(names & HEADER_KEYS) >= 2:
                header = [re.sub(r"\s+", " ", c).strip() if c else None for c in r]
            continue
        if not any(cells):
            continue
        rec = {h: (r[j] if j < len(r) else None) for j, h in enumerate(header) if h}
        rec["_row"] = i + 1
        out.append(rec)
    return out


def to_dashboard_row(kind: str, rec: dict) -> dict:
    row = {k: v for k, v in rec.items() if not k.startswith("_")}
    for k in ("Date Activated", "Date Ceased", "Date Bypass Began or was Discovered", "Date Bypass Ended"):
        if k in row:
            row[k] = excel_date(row[k])
    for k in ("Event Start Time", "Event End Time"):
        if k in row:
            row[k] = excel_time(row[k])
    for k, v in list(row.items()):
        if isinstance(v, str):
            row[k] = v.strip()
    rid = clean(row.get("Request ID"))
    if rid and re.fullmatch(r"\d+(\.0+)?", rid):
        row["Request ID"] = str(int(float(rid)))
    return row


def is_event_row(kind: str, row: dict) -> bool:
    date_col = "Date Activated" if kind == "cso" else "Date Bypass Began or was Discovered"
    return bool(clean(row.get("Request ID")) or clean(row.get(date_col)))


def permittee(kind: str, row: dict) -> str:
    return (clean(row.get("Report Type")) if kind == "cso" else clean(row.get("Reporting Utility"))) or \
        clean(row.get("Muncipality") or row.get("Municipality")) or ""


# ---------------------------------------------------------------- summaries (for the completeness table)

def summary_totals(sheets: dict) -> dict:
    """{'cso_reports': n, 'sso_events': n} from the annual-report workbook's TOTAL rows."""
    out = {}
    for name, rows in sheets.items():
        up = name.upper()
        key, col_name = (("cso_reports", "TOTAL # of REPORTS") if up.startswith("CSO")
                         else ("sso_events", "# ot TOTAL EVENTS") if up.startswith("SSO") else (None, None))
        if not key:
            continue
        header, idx, total = None, None, None
        for r in rows:
            cells = [clean(x) for x in r]
            if header is None:
                for j, c in enumerate(cells):
                    if c and re.sub(r"\s+", " ", c).strip().lower() in (col_name.lower(), "# of total events", "total # of reports"):
                        header, idx = cells, j
                continue
            if cells and cells[0] and re.match(r"^\s*(total|summary)", cells[0], re.I) and idx < len(cells) and cells[idx]:
                try:
                    total = int(float(cells[idx]))
                except ValueError:
                    pass
        if total is not None:
            out[key] = total
    return out


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cached", action="store_true", help="re-read the newest saved copy of each workbook")
    args = ap.parse_args(argv)
    fetched = now_iso()
    now = datetime.now(TZ)
    s = requests.Session()
    s.headers.update(HEADERS)
    dash = {r["event_id"] for r in (read_json(EVENTS_DIR / "ct-deep.json", {}) or {}).get("records", [])}

    records, files_meta, totals = [], {}, {}
    seen_ids: Counter = Counter()
    try:
        for ry, names in FILES.items():
            for kind, name in zip(("cso", "sso", "summary"), names):
                content, published, how = fetch(name, args.cached, s)
                sheets = read_xlsx(content)
                files_meta[name] = {"published_at": published, "how": how, "sheets": {k: len(v) for k, v in sheets.items()}}
                print(f"  {name}: {how}, sheets {list(sheets)}", file=sys.stderr)
                if kind == "summary":
                    totals[ry - 1] = summary_totals(sheets)
                    continue
                for sheet, rows in sheets.items():
                    if "SUMMARY" in sheet.upper():
                        continue
                    for rec in sheet_rows(rows):
                        orig = {k: v for k, v in rec.items() if not k.startswith("_")}
                        row = to_dashboard_row(kind, translate_old(kind, orig) or orig)
                        if not is_event_row(kind, row):
                            continue
                        records.append(make_record(kind, row, orig, rec["_row"], name, sheet, ry, published, fetched, now,
                                                   dash, seen_ids))
    except Exception as e:
        print(f"ct_deep_annual: failed: {type(e).__name__}: {e}", file=sys.stderr)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        return 1

    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    by_year = defaultdict(Counter)
    for r in records:
        by_year[(r.get("started_at") or "none")[:4]][r["raw"].get("_view", "?")[:3]] += 1
    meta = {"page": PAGE_URL, "files": files_meta, "summary_totals_by_data_year": totals,
            "rows_by_start_year": {y: dict(c) for y, c in sorted(by_year.items())},
            "counts": {"records": len(records), "by_type": dict(Counter(r["event_type"] for r in records)),
                       "by_status": dict(Counter(r["status"] for r in records)),
                       "duplicate_of_dashboard": sum(bool(r.get("duplicate_of")) for r in records),
                       "with_slugs": sum(bool(r["water_slugs"]) for r in records),
                       "parse_errors": sum(bool(r["parse_error"]) for r in records)}}
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"ct_deep_annual: {len(records)} records -> {path}", file=sys.stderr)
    print(json.dumps(meta["counts"]), file=sys.stderr)
    return 0


def make_record(kind, row, orig, rownum, name, sheet, ry, published, fetched, now, dash, seen_ids) -> dict:
    rid = clean(row.get("Request ID"))
    try:
        rec = normalise(kind, row, fetched, now)
        rec.pop("_key", None)
    except Exception as e:  # never drop a row
        rec = event(source_id=SOURCE_ID, source_record_id="tmp", raw=scrub(dict(row)), parse_error=f"{type(e).__name__}: {e}")
    notes = [n for n in rec["raw"].get("_dww_note", []) if n != "no source status"]
    # the raw record is the workbook row as DEEP wrote it (not the translated one)
    rec["raw"] = {**scrub({k: (v.strip() if isinstance(v, str) else v) for k, v in orig.items()}),
                  "_view": rec["raw"].get("_view")}
    errs = [e for e in (rec.get("parse_error") or "").split("; ") if e and e != "no Request ID"]
    rec["parse_error"] = "; ".join(errs) or None
    if rec["status"] == "unknown" and rec.get("ended_at") and not clean(row.get("Status")):
        rec["status"] = "ended"          # a closed annual record with an end time and no status column
    label = clean(row.get("Reporting Utility")) if kind == "sso" else report_label(row)
    key = utility_key(label)
    if key:
        did, _, npdes = discharger_for(key)
        rec.update(discharger_id=did, npdes_permit=npdes, discharger_name=rec.get("discharger_name") or label)
    if notes:
        rec["raw"]["_dww_note"] = notes
    if rid:
        sid = rid
    else:
        start = (rec.get("started_at") or row.get("Date Activated") or row.get("Date Bypass Began or was Discovered") or "")
        sid = "x" + hashlib.sha1("|".join([permittee(kind, row), str(start), str(rec.get("outfall_name") or "")]).encode()).hexdigest()[:12]
    seen_ids[sid] += 1
    if seen_ids[sid] > 1:
        sid = f"{sid}-{seen_ids[sid]}"
    conv = clean(row.get("Final Volume Converted for counting"))
    if conv:
        try:
            rec["volume_gal"] = int(round(float(conv.replace(",", ""))))
            rec["volume_text"] = clean(row.get("Final Volume")) or conv
        except ValueError:
            pass
    rec["raw"]["_source_file"] = {"file": name, "url": BASE + name, "sheet": sheet, "row": rownum, "report_year": ry}
    rec["raw"]["_view"] = rec["raw"].get("_view") or ("CSO DATA VIEW" if kind == "cso" else "SSO DATA VIEW")
    rec.update(source_id=SOURCE_ID, source_record_id=sid, event_id=f"{SOURCE_ID}:{sid}", published_at=published,
               source_url=BASE + name,
               authority=re.sub(r"\(CT DEEP Performance Dashboard\)$", f"(CT DEEP Sewage Right-to-Know annual report {ry})",
                                rec.get("authority") or "CT DEEP Performance Dashboard"))
    rec["duplicate_of"] = f"ct-deep:{rid}" if rid and f"ct-deep:{rid}" in dash else None
    return rec


if __name__ == "__main__":
    sys.exit(main())
