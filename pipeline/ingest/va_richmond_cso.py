"""City of Richmond monthly CSO outfall reports (Virginia) -> data/build/events/va-richmond-cso.json.

Source
  Richmond Department of Public Utilities posts one workbook a month on its CSO Outfalls page,
  https://www.rva.gov/public-utilities/csooutfalls (links "July 2026" ... to rva.gov/media/<id>
  pages that link the file under sites/default/files/..., sometimes the file directly). Sheet
  "CSO Summary" (per outfall: sensor type, % of report with good data, number of observed
  activations, observed overflow volume MG) and one sheet per outfall "CSO_06-Events" with one row
  per activation: label, start, end (Excel serial dates), "Rainfall, in", "Observed Overflow
  Volume, mg", overflow_duration_hours. Sheet note: "Activations are defined by CSO volumes > 0.01
  MG and an interevent time of 72 hours", so the end can be days after the overflow hours. No
  licence stated. Posted one to two months after the month. The live EmNet map is not polled
  (owner decision pending; research/va/report.md).

Record rules
  - One cso event per outfall per activation row: source_record_id "CSO_06-20260719T1840"; status
    ended; started_at / ended_at from the serials read as America/New_York wall clock (the workbook
    states no zone: inferred, raw._time_basis); time_precision minute.
  - volume_gal = observed MG x 1,000,000 (volume_text keeps the figure as published); estimate_flag
    "measured" for a flow-sensor outfall and "estimated" for a level-sensor outfall (Summary sheet).
    Rainfall, duration hours and the month's summary row are kept in raw.
  - Discharger va-richmond-dpu (VPDES VA0063177); outfall "CSO_06" -> ECHO inventory outfall "006"
    in data/outfalls-mid-atlantic.json: receiving water as ECHO names it, coordinates and water slug
    (water_match outfall_registry; null when the inventory has no slug: Gillies Creek, Haxall Canal ...).
  - Workbooks are fetched when a month is new or its link changed; the newest listed month is
    re-read every run (revisions). `--backfill` reads every month from January 2025. Parsed months
    are kept in data/build/va-richmond-cso-state.json; raw workbooks are saved when new or changed.

Run from pipeline/: python -m ingest.va_richmond_cso [--backfill]
Cadence: daily (monthly files).
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import io
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest import va_waters
from ingest.ny_sprtk import _rows, _sheets, _shared_strings

SOURCE_ID = "va-richmond-cso"
PAGE = "https://www.rva.gov/public-utilities/csooutfalls"
STATE_PATH = BUILD_DIR / "va-richmond-cso-state.json"
TZ = ZoneInfo("America/New_York")
PERMIT = "VA0063177"
DISCHARGER = {"discharger_id": "va-richmond-dpu",
              "discharger_name": "City of Richmond Department of Public Utilities (Richmond WWTP and combined sewer system)",
              "npdes_permit": PERMIT}
AUTHORITY = "City of Richmond Department of Public Utilities (monthly CSO outfall report)"
BACKFILL_FROM = date(2025, 1, 1)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
TIME_NOTE = ("Excel serial dates with no zone stated; read as America/New_York wall-clock time (inferred: "
             "Richmond's map uses America/New_York).")
ACTIVATION_NOTE = ("Workbook note: activations are defined by CSO volumes > 0.01 MG and an interevent time of "
                   "72 hours, so the end can be days after the overflow hours (overflow_duration_hours).")


# ---------------------------------------------------------------- page and workbook

def month_links(html: str, base: str = PAGE) -> dict[str, str]:
    """{'2026-07': url} from the CSO Outfalls page (anchor text 'July 2026')."""
    out = {}
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        t = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        m = re.fullmatch(r"(?i)(%s)\s+(\d{4})" % "|".join(MONTHS), t)
        if m:
            out[f"{m.group(2)}-{MONTHS.index(m.group(1).lower()) + 1:02d}"] = urljoin(base, htmllib.unescape(href))
    return out


def xlsx_link(html: str, base: str) -> str | None:
    m = re.search(r'(?:href|src)="([^"]+\.xlsx[^"]*)"', html) or re.search(r'(/sites/default/files/[^"\s]+\.xlsx[^"\s]*)', html)
    return urljoin(base, htmllib.unescape(m.group(1))) if m else None


def excel_time(v) -> datetime | None:
    """Excel serial (days since 1899-12-30) -> aware America/New_York, to the minute."""
    if v in (None, ""):
        return None
    dt = datetime(1899, 12, 30) + timedelta(days=float(v))
    dt = (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)
    return dt.replace(tzinfo=TZ)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_workbook(content: bytes) -> dict:
    """{'summary': {outfall: {...}}, 'events': {outfall: [row ...]}, 'title': str, 'notes': [...]}"""
    z = zipfile.ZipFile(io.BytesIO(content))
    ss = _shared_strings(z)
    out = {"summary": {}, "events": {}, "title": None, "notes": []}
    for name, path in _sheets(z):
        rows = list(_rows(z, path, ss))
        if name.strip().lower() == "cso summary":
            hdr = None
            for r in rows:
                if r and r[0] and not hdr and re.search(r"overflow", r[0] or "", re.I) and len(r) == 1:
                    out["title"] = (out["title"] + "; " if out["title"] else "") + r[0]
                    continue
                if len(r) > 1 and r[1] == "Sensor Type":
                    hdr = r
                    continue
                if hdr and r and r[0] and re.match(r"CSO_?\d+", r[0]):
                    out["summary"][r[0]] = {hdr[i]: r[i] for i in range(1, min(len(hdr), len(r))) if hdr[i]}
            continue
        m = re.match(r"(CSO_?\d+)-Events", name.strip())
        if not m:
            continue
        of = m.group(1)
        hdr = None
        evs = []
        for r in rows:
            if not r:
                continue
            if r[0] and str(r[0]).startswith("Note:"):
                if r[0] not in out["notes"]:
                    out["notes"].append(r[0])
                continue
            if len(r) > 2 and (r[1] or "").strip().lower() == "start":
                hdr = [(x or "").strip() for x in r]
                continue
            if hdr and len(r) >= 3 and r[1] and re.fullmatch(r"\d+(\.\d+)?", str(r[1]).strip()):
                cells = {hdr[i] or "label": r[i] for i in range(min(len(hdr), len(r)))}
                cells["label"] = r[0]
                evs.append(cells)
        out["events"][of] = evs
    return out


# ---------------------------------------------------------------- records

def outfall_number(of: str) -> str:
    n = int(re.search(r"\d+", of).group(0))
    return f"{n:03d}"


def to_records(month: str, parsed: dict, source_url: str, fetched_at: str) -> list[dict]:
    recs = []
    for of, rows in parsed["events"].items():
        num = outfall_number(of)
        eo = va_waters.echo_outfall(PERMIT, num)
        summ = parsed["summary"].get(of) or {}
        sensor = (summ.get("Sensor Type") or "").strip()
        for row in rows:
            problems = []
            try:
                start, end = excel_time(row.get("start")), excel_time(row.get("end"))
            except (TypeError, ValueError) as e:
                start = end = None
                problems.append(f"time not read: {e}")
            if start and end and end < start:
                problems.append("end before start")
            mg = _f(row.get("Observed Overflow Volume, mg"))
            vol_text = f"{row.get('Observed Overflow Volume, mg')} MG (observed overflow volume)" if mg is not None else None
            gal = int(round(mg * 1_000_000)) if mg is not None and mg >= 0 else None
            rid = f"{of}-{start:%Y%m%dT%H%M}" if start else f"{of}-{month}-{hashlib.sha1(str(row).encode()).hexdigest()[:8]}"
            slug = (eo or {}).get("water_slug")
            raw = {"month": month, "outfall_sheet": f"{of}-Events", "row": row,
                   "rain_in": _f(row.get("Rainfall, in")), "overflow_duration_hours": _f(row.get("overflow_duration_hours")),
                   "summary_row": summ or None, "workbook_title": parsed.get("title"), "workbook_notes": parsed.get("notes"),
                   "echo_outfall": {k: eo.get(k) for k in ("outfall", "receiving_water_echo", "water_slug", "match",
                                                          "distance_m")} if eo else None,
                   "_time_basis": TIME_NOTE, "activation_note": ACTIVATION_NOTE}
            recs.append(event(
                source_id=SOURCE_ID, source_record_id=rid, event_type="unknown" if not start else "cso",
                status="ended" if end else "unknown", **DISCHARGER,
                outfall_id=num, outfall_name=of.replace("_", " "),
                waterbody_text=(eo or {}).get("receiving_water_echo"), water_slugs=[slug] if slug else [],
                water_match="outfall_registry" if slug else "none",
                lat=(eo or {}).get("lat"), lon=(eo or {}).get("lon"),
                coord_source="outfall_layer" if eo and eo.get("lat") is not None else None,
                started_at=start.isoformat() if start else None, ended_at=end.isoformat() if end else None,
                time_precision="minute", reported_at=None, published_at=None, source_updated_at=None,
                fetched_at=fetched_at, material="combined sewage and stormwater",
                volume_gal=gal, volume_text=vol_text,
                estimate_flag="measured" if sensor.lower() == "flow" else ("estimated" if sensor else "unknown"),
                authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
                source_url=source_url, raw=raw, parse_error="; ".join(problems) or None,
            ))
    return recs


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="every month from January 2025")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_PATH, {}) or {}
    months = state.setdefault("months", {})
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(PAGE, timeout=60)
        r.raise_for_status()
        links = month_links(r.text)
        if not links:
            raise ValueError("no month links on the CSO Outfalls page (layout changed?)")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"page: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    newest = max(links)
    since = f"{BACKFILL_FROM:%Y-%m}"
    want = [m for m in sorted(links) if m >= since and
            (m not in months or months[m].get("link") != links[m] or m == newest or (args.backfill and not months[m].get("events")))]
    if not args.backfill:
        want = [m for m in want if m >= sorted(links)[-3]]
    errors = []
    for m in want:
        try:
            url = links[m]
            xurl = url if re.search(r"\.xlsx", url, re.I) else None
            if not xurl:
                p = sess.get(url, timeout=60)
                p.raise_for_status()
                xurl = xlsx_link(p.text, p.url)
                if not xurl:
                    raise ValueError(f"no workbook link on {url}")
            x = sess.get(xurl, timeout=180)
            x.raise_for_status()
            h = hashlib.sha256(x.content).hexdigest()
            if (months.get(m) or {}).get("sha256") != h:
                save_raw(SOURCE_ID, x.content, f"{m}.xlsx")
            parsed = parse_workbook(x.content)
            months[m] = {"link": links[m], "xlsx_url": xurl, "sha256": h, "fetched_at": fetched_at,
                         "title": parsed["title"], "notes": parsed["notes"], "summary": parsed["summary"],
                         "events": parsed["events"]}
        except Exception as e:  # noqa: BLE001
            errors.append(f"{m}: {type(e).__name__}: {e}")
        time.sleep(1)
    state["last_poll_at"] = fetched_at
    state["listed_months"] = sorted(links)
    write_json(STATE_PATH, state)
    records, checks = [], {}
    for m, mo in sorted(months.items()):
        recs = to_records(m, {"events": mo.get("events") or {}, "summary": mo.get("summary") or {},
                              "title": mo.get("title"), "notes": mo.get("notes")}, mo.get("xlsx_url") or mo.get("link"),
                          mo.get("fetched_at") or fetched_at)
        records += recs
        listed = sum(int(_f((s or {}).get("Number of Observed Activations")) or 0) for s in (mo.get("summary") or {}).values())
        if listed != len(recs):
            checks[m] = {"summary_activations": listed, "event_rows": len(recs)}
    ids = {}
    for rec in records:
        ids[rec["event_id"]] = rec          # an activation spanning two monthly files: the later file wins
    records = sorted(ids.values(), key=lambda x: x["started_at"] or "", reverse=True)
    meta = {"page": PAGE, "months_listed": sorted(links), "months_parsed": sorted(months),
            "months_missing_from_page": [f"{y}-{mm:02d}" for y in range(2025, int(newest[:4]) + 1) for mm in range(1, 13)
                                         if since <= f"{y}-{mm:02d}" <= newest and f"{y}-{mm:02d}" not in links],
            "summary_vs_rows": checks or None, "errors": errors or None, "registry_ids": ["va-richmond-monthly-cso-xlsx"],
            "covers_permits": [PERMIT], "statewide": False, "timezone_note": TIME_NOTE, "activation_note": ACTIVATION_NOTE,
            "emnet_map": "not polled"}
    path = write_events(SOURCE_ID, records, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"{SOURCE_ID}: {len(want)} workbooks read, {len(months)} months, {len(records)} overflow events -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
