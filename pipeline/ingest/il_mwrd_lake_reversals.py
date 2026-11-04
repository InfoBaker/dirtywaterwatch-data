"""MWRD's table of reversals to Lake Michigan (1985 to date) -> data/build/events/il-mwrd-lake-michigan-reversals.json.

Source
  https://mwrd.org/files/rdrct/Lake_Michigan_Reversals.pdf (registry il-mwrd-lake-michigan-reversals; linked from
  MWRD's CSO notification page). One PDF page: "Reversals to Lake Michigan (1985 - Present), Million Gallons", a row
  per reversal (year, the date or dates, the volume let through O'Brien Lock, the Chicago River Controlling Works
  (CRCW) and the Wilmette gate, and the total) and a row "None" for a year without one. MWRD's note: in severe storms
  the Chicago Area Waterway System, which takes the area's combined sewer overflows, is let back into Lake Michigan
  through gates beside the locks, or through the locks themselves. Fetched 2026-11-04: 36 reversals (57 records), the last on
  2023-07-02/03 (1,142.6 million gallons).

Records
  - One record per reversal and structure with a volume (a row with CRCW and Wilmette volumes gives two records):
    event_type cso (the water is combined sewage and stormwater mixed into the waterway), raw.diversion the structure,
    waterbody_text "Lake Michigan", the structure's point (il_mwrd.DIVERSION_POINTS), volume_gal the table's million
    gallons, estimate_flag unknown (the table does not say how volumes are found).
  - Dates: the table gives days only: started_at the first day, ended_at the last (the same day for a one-day row),
    time_precision "day", status "ended". A range running into the next year ("12/31-1/1") ends in the next year.
  - source_record_id: the first day and the structure ("2023-07-02-crcw"); stable while MWRD keeps the row.
  - A row whose structure volumes do not add up to its total (within 0.2) keeps its records with a parse_error.
  - source_updated_at: the PDF's HTTP Last-Modified; published_at null (no posting date); the years with "None" go to
    meta.years_without_reversal.
  Nothing personal is in the table.

Text: `pdftotext -layout` (poppler-utils). The PDF's fonts are CID fonts that the pure-Python helper
(ingest/nh_pdftext.py) cannot read; where pdftotext is missing the run writes ok=False and keeps the previous
records. Columns are assigned by the end of each number under the header's column names.

Run from pipeline/: python -m ingest.il_mwrd_lake_reversals [--file saved.pdf | --text saved.txt] [--out events.json]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from common import BUILD_DIR, HEADERS, event, read_json, save_raw, write_events, write_json
from ingest import il_mwrd as M

SOURCE_ID = "il-mwrd-lake-michigan-reversals"
URL = "https://mwrd.org/files/rdrct/Lake_Michigan_Reversals.pdf"
HASH_PATH = BUILD_DIR / "il-mwrd-lake-reversals-hash.json"
AUTHORITY = "Metropolitan Water Reclamation District of Greater Chicago (Reversals to Lake Michigan table)"
COLUMNS = [("O'Brien Lock", r"O'?Brien\s+Lock"), ("CRCW", r"CRCW"), ("Wilmette", r"Wilmette"), ("Total", r"Total\s+Volume")]
ROW = re.compile(r"^\s*(\d{4})\s+(None|\d{1,2}/\d{1,2}(?:\s*-\s*\d{1,2}/\d{1,2})?)\b(.*)$")
NUM = re.compile(r"\d[\d,]*\.\d+|\d[\d,]*")
MATERIAL = "waterway water with combined sewage and stormwater, let back into Lake Michigan"


def pdf_text(pdf: bytes) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext (poppler-utils) is not installed")
    return subprocess.run([exe, "-layout", "-", "-"], input=pdf, capture_output=True, check=True, timeout=60).stdout.decode(
        "utf-8", "replace")


def header_edges(lines: list[str]) -> dict[str, int] | None:
    for ln in lines:
        if re.search(COLUMNS[1][1], ln) and re.search(COLUMNS[2][1], ln):
            out = {}
            for name, pat in COLUMNS:
                m = re.search(pat, ln)
                if m:
                    out[name] = m.end()
            if len(out) == len(COLUMNS):
                return out
    return None


def parse(text: str) -> tuple[list[dict], list[int], list[str]]:
    """([{year, dates, start, end, volumes {column: MG}, total, line}], years with none, problems)."""
    lines = text.splitlines()
    edges = header_edges(lines)
    if not edges:
        raise ValueError("the table's header (O'Brien Lock, CRCW, Wilmette, Total Volume) was not found")
    rows, none_years, problems, seen = [], [], [], set()
    for ln in lines:
        m = ROW.match(ln)
        if not m:
            continue
        year, dates = int(m.group(1)), re.sub(r"\s+", "", m.group(2))
        if (year, dates) in seen:          # the page repeats the table (text layer and print copy)
            continue
        seen.add((year, dates))
        if dates == "None":
            none_years.append(year)
            continue
        vols = {}
        for n in NUM.finditer(ln, m.start(3)):
            end = n.end()
            col = min(edges, key=lambda c: abs(edges[c] - end))
            vols[col] = float(n.group(0).replace(",", ""))
        a, _, b = dates.partition("-")
        sm, sd = (int(x) for x in a.split("/"))
        start = date(year, sm, sd)
        if b:
            em, ed = (int(x) for x in b.split("/"))
            end = date(year + (1 if em < sm else 0), em, ed)
        else:
            end = start
        total = vols.pop("Total", None)
        if not vols:
            problems.append(f"{year} {dates}: no structure volume read")
        elif total is not None and abs(sum(vols.values()) - total) > 0.2:
            problems.append(f"{year} {dates}: structure volumes {sum(vols.values()):.1f} do not add up to the total "
                            f"{total:.1f}")
        rows.append({"year": year, "dates": dates, "start": start.isoformat(), "end": end.isoformat(), "volumes": vols,
                     "total": total, "line": ln.strip()})
    return rows, sorted(set(none_years)), problems


def records(rows: list[dict], problems: list[str], last_modified: str | None) -> list[dict]:
    out = []
    for r in rows:
        prob = [p for p in problems if p.startswith(f"{r['year']} {r['dates']}:")]
        for col, mg in r["volumes"].items():
            lat, lon = M.DIVERSION_POINTS[col]
            name = next(n for _, c, n in M.DIVERSIONS if c == col)
            out.append(event(
                source_id=SOURCE_ID, source_record_id=f"{r['start']}-{re.sub(r'[^a-z0-9]+', '-', col.lower()).strip('-')}",
                event_type="cso", status="ended", outfall_name=name, waterbody_text=M.LAKE,
                lat=lat, lon=lon, coord_source="outfall_layer",
                started_at=r["start"], ended_at=r["end"], time_precision="day",
                source_updated_at=last_modified, material=MATERIAL,
                volume_gal=int(round(mg * 1_000_000)), volume_text=f"{mg:,.1f} million gallons ({col})",
                estimate_flag="unknown", authority=AUTHORITY, source_url=URL,
                raw={"row": r["line"], "year": r["year"], "dates": r["dates"], "diversion": name,
                     "from_waterway": M.DIVERSION_WATERWAYS[col], "structure_column": col, "row_total_mg": r["total"],
                     "time_note": "the table gives days only"},
                parse_error="; ".join(prob) or None))
    out.sort(key=lambda x: (x["started_at"], x["event_id"]), reverse=True)
    return out


def build(text: str, last_modified: str | None) -> tuple[list[dict], dict]:
    rows, none_years, problems = parse(text)
    recs = records(rows, problems, last_modified)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "reversals": len(rows), "records": len(recs),
            "years_without_reversal": none_years, "problems": problems, "credit": M.CREDIT,
            "time_note": "The table gives the days of each reversal, not its hours."}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="a saved copy of the PDF")
    ap.add_argument("--text", help="a saved pdftotext -layout text of the PDF")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else None
    lm = None
    try:
        if a.text:
            text = Path(a.text).read_text()
        else:
            if a.file:
                pdf = Path(a.file).read_bytes()
            else:
                r = requests.get(URL, headers=HEADERS, timeout=60)
                r.raise_for_status()
                pdf = r.content
                h = r.headers.get("Last-Modified")
                lm = parsedate_to_datetime(h).isoformat().replace("+00:00", "Z") if h else None
                digest = hashlib.sha256(pdf).hexdigest()
                if (read_json(HASH_PATH, {}) or {}).get("sha256") != digest:
                    save_raw(SOURCE_ID, pdf, "pdf")
                    write_json(HASH_PATH, {"sha256": digest, "last_modified": lm})
            text = pdf_text(pdf)
        recs, meta = build(text, lm)
    except (requests.RequestException, RuntimeError, ValueError, subprocess.SubprocessError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta, path=out)
    print(f"{SOURCE_ID}: {meta['reversals']} reversals, {len(recs)} records, problems {len(meta['problems'])} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
