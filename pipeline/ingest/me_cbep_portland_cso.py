"""Portland, Maine: combined sewer overflows storm by storm and outfall by outfall, 2015 to 2019.

Source
  The Casco Bay Estuary Partnership's State of the Bay archive (registry: me-cbep-portland-cso),
  https://github.com/CBEP-SoCB-Details/Casco_Bay_CSOs at commit 99cadaabf605e1f46c619339c1e5220762b5d660 (2021-12-03,
  the repository's last change). It holds the yearly overflow workbooks the City of Portland and the Portland Water
  District filed with Maine DEP ("CSO Activity and Volumes": one row per storm with its first and last day, one column
  of gallons per outfall), received by CBEP from PWD staff, and CBEP's merged file of 2015 to 2019. It is the only
  public dated overflow record for Maine: DEP publishes yearly totals (ingest/me_dep_cso.py) and does not post the
  filings.
  - 2015 to 2018: CBEP's merged file Derived_Data/Portland_CSO_data_2015_2019.csv. Its 2016 to 2018 figures equal the
    filings' (2017 and 2018 to the gallon); CBEP rebuilt 2015 from a daily sheet ("Overflow Estimates") and cleaned
    the filings' mistyped dates.
  - 2019: the filing itself, Original_Data/Portland_Data/2019 Portland CSO Activity and Volumes - Final.xlsx. CBEP's
    merged file drops its storm 46, which the filing dates 12/13/2020 to 12/15/2020 inside reporting year 2019 (56.5
    million gallons; radar rain at Portland 2.54 inches on 2019-12-14), and shows 0 in six cells the filing fills.
    A filed date outside the reporting year is read in the reporting year, and the record says so (date_as_filed).
    With it the filing totals 185.1 million gallons, against 184.5 in DEP's 2019 status report.
  Both are static. The ingester reads tracked copies in data/reference/: CBEP's file as published (SHA256 checked) and
  a numbers-only extract of the 2019 workbook (the workbook names a city contact; the extract keeps storm, dates,
  outfall and cell). `python -m ingest.me_cbep_portland_cso --extract` rebuilds the extract from the pinned workbook.
  Terms: CBEP's archive is MIT-licensed for its code; its notice says the data belong to their providers and CBEP may
  post them "for study and non-commercial use". Records credit the City of Portland and PWD as filers and CBEP as
  publisher.

Records
  One per storm and outfall with a positive figure: event_type cso, status ended, started_at the storm's first day
  and ended_at its last day (time_precision day): the outfall discharged during that storm, on a day the files do not
  give. volume_gal the outfall's gallons for the storm. A blank, "NA" or "--" cell is no record (in 2015 "--" meant
  "metering data unavailable": CBEP lists CSOs 002, 009 and 011 as never metered that year and 007 and 023 as often
  not; later a blank means no discharge detected); a 0 is no record; a meter note ("Removed Apr 8") is no record. All
  are counted in meta. A float-block trip with no metered volume ("BLOCK") is not in CBEP's file, so 2015 to 2018
  can miss a discharge whose volume was not measured. Each outfall is placed by the outfall registry
  (data/outfalls-new-england.json): permit ME0101435 (City of Portland) or ME0102075 (Portland Water District, East
  End), its point and its water; an outfall the registry lacks keeps its number and no point (parse_error). A record's
  id is the storm's first day and the outfall. source_url points at the record's line in CBEP's file, or at the 2019
  workbook (its row in raw).

Failures
  A missing or changed reference file writes ok=False with the reason (the previous records stay).

Run from pipeline/:  python -m ingest.me_cbep_portland_cso [--extract]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import quote

from common import DATA_DIR, HEADERS, event, write_events
from ingest.me_dep_cso import dischargers, me_waters_by_name, outfall_water, registry_index

SOURCE_ID = "me-cbep-portland-cso"
REGISTRY_ID = "me-cbep-portland-cso"
COMMIT = "99cadaabf605e1f46c619339c1e5220762b5d660"
REPO = "https://github.com/CBEP-SoCB-Details/Casco_Bay_CSOs"
RAW = f"https://raw.githubusercontent.com/CBEP-SoCB-Details/Casco_Bay_CSOs/{COMMIT}/"
MERGED_PATH = "Derived_Data/Portland_CSO_data_2015_2019.csv"
FILING_PATH = "Original_Data/Portland_Data/2019 Portland CSO Activity and Volumes - Final.xlsx"
MERGED_URL = f"{REPO}/blob/{COMMIT}/{MERGED_PATH}"
FILING_URL = f"{REPO}/blob/{COMMIT}/{quote(FILING_PATH)}"
MERGED_REF = DATA_DIR / "reference" / "cbep-portland-cso-2015-2019.csv"
FILING_REF = DATA_DIR / "reference" / "portland-cso-2019-filing.csv"
MERGED_SHA256 = "7d074e50c97cb68f6c6c1c53459cae20faf900c4ef08856f2336334f8fcfa7f0"
FILING_XLSX_SHA256 = "3c1382d5e324eedd2d6eb4e1e83862bd28f7e9eb25a21672f0f44e68d912f209"   # the pinned workbook
FILING_YEAR = 2019
PUBLISHED_AT = "2021-12-03"          # the commit that holds both files (CBEP's last change to the archive)
PERMITS = ("ME0101435", "ME0102075")  # City of Portland CSOs; Portland Water District, East End
AUTHORITY = "City of Portland and Portland Water District (published by the Casco Bay Estuary Partnership)"
COLUMN = re.compile(r"^CSO_(\d{3})$")
FILING_FIELDS = ["storm", "row", "first_day", "last_day", "first_as_filed", "last_as_filed", "outfall", "cell"]


# --------------------------------------------------------------------------- the 2019 filing (extract mode)

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _colnum(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n


def workbook_rows(data: bytes) -> dict[int, dict[int, str | None]]:
    """The first sheet's cells, {row: {column: text}} (shared strings resolved; stdlib only)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_M + "si"):
            ss.append("".join(t.text or "" for t in si.iter(_M + "t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    target = rels[wb.find(_M + "sheets")[0].get(_R + "id")].lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target
    rows: dict[int, dict[int, str | None]] = {}
    for r in ET.fromstring(z.read(target)).iter(_M + "row"):
        vals = {}
        for c in r.findall(_M + "c"):
            v = c.find(_M + "v")
            if v is None:
                isv = c.find(_M + "is")
                val = "".join(t.text or "" for t in isv.iter(_M + "t")) if isv is not None else None
            else:
                val = ss[int(v.text)] if c.get("t") == "s" else v.text
            vals[_colnum(c.get("r"))] = val
        rows[int(r.get("r"))] = vals
    return rows


def excel_day(v) -> date | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return date(1899, 12, 30) + timedelta(days=int(f))


def in_year(d: date | None, year: int) -> date | None:
    """A filed date read in the reporting year (12/13/2020 in the 2019 filing is 2019-12-13)."""
    if d is None or d.year == year:
        return d
    try:
        return d.replace(year=year)
    except ValueError:      # 29 February outside a leap year: no reading
        return None


def extract_filing(data: bytes) -> list[dict]:
    """Storm rows of the 2019 workbook, one per storm and outfall cell (numbers and notes; no names)."""
    rows = workbook_rows(data)
    hdr = next(rn for rn in sorted(rows) if any(re.fullmatch(r"CSO \d{3}", str(v or "")) for v in rows[rn].values()))
    cols = {k: v[4:] for k, v in rows[hdr].items() if re.fullmatch(r"CSO \d{3}", str(v or ""))}
    out = []
    for rn in sorted(rows):
        r = rows[rn]
        no = str(r.get(1) or "").strip()
        if rn <= hdr or not no.isdigit():
            continue
        d0, d1 = excel_day(r.get(2)), excel_day(r.get(3))
        f0, f1 = in_year(d0, FILING_YEAR), in_year(d1, FILING_YEAR)
        for k, of in sorted(cols.items(), key=lambda kv: kv[1]):
            cell = r.get(k)
            if cell in (None, ""):
                continue
            out.append({"storm": int(no), "row": rn, "first_day": f0.isoformat() if f0 else "",
                        "last_day": f1.isoformat() if f1 else "",
                        "first_as_filed": d0.isoformat() if d0 else str(r.get(2) or ""),
                        "last_as_filed": d1.isoformat() if d1 else str(r.get(3) or ""),
                        "outfall": of, "cell": str(cell).strip()})
    return out


def write_filing_extract() -> int:
    import requests
    resp = requests.get(RAW + quote(FILING_PATH), headers=HEADERS, timeout=60)
    resp.raise_for_status()
    digest = hashlib.sha256(resp.content).hexdigest()
    if digest != FILING_XLSX_SHA256:
        print(f"the workbook differs from the pinned one (sha256 {digest}); nothing written", file=sys.stderr)
        return 1
    rows = extract_filing(resp.content)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FILING_FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    FILING_REF.write_text(f"# extracted from {FILING_URL} (sha256 {digest})\n" + buf.getvalue())
    print(f"{FILING_REF}: {len(rows)} cells; workbook sha256 {digest}")
    return 0


# --------------------------------------------------------------------------- records

def gallons(cell: str | None) -> float | None:
    """The cell's gallons, or None for a blank, NA, "--" or a note (not metered, nothing detected, a meter note)."""
    c = (cell or "").strip()
    try:
        return float(c.replace(",", ""))
    except ValueError:
        return None


def outfall_index(reg: dict) -> dict[str, dict]:
    """Outfall number -> registry row, for the two Portland permits (the numbers do not repeat across them)."""
    return {of: row for (permit, of), row in reg.items() if permit in PERMITS}


class Placer:
    def __init__(self, reg: dict, by_name: dict, disc: dict):
        self.reg, self.by_name, self.disc, self.idx = reg, by_name, disc, outfall_index(reg)

    def record(self, *, year: int, first: str, last: str, of: str, gal: float, url: str, raw: dict, counts: dict,
               note: str | None = None) -> dict:
        o = self.idx.get(of)
        if o is None and of not in counts["not_in_registry"]:
            counts["not_in_registry"].append(of)
        permit = (o or {}).get("npdes_permit")
        d = self.disc.get(permit, {}) if permit else {}
        slug, how = (outfall_water(permit, of, o.get("receiving_water_echo"), self.reg, self.by_name, o.get("lat"),
                                   o.get("lon")) if o else (None, "none"))
        g = int(round(gal))
        span = first if first == last else f"{first} to {last}"
        text = f"{g:,} gallons at outfall {of} during the storm of {span}" + (f" ({note})" if note else "")
        return event(
            source_id=SOURCE_ID, source_record_id=f"{first}:{of}",
            event_type="cso", status="ended",
            discharger_id=d.get("id"), discharger_name=d.get("name") or (o or {}).get("permittee"),
            npdes_permit=permit, outfall_id=of, outfall_name=(o or {}).get("outfall_name"),
            waterbody_text=(o or {}).get("receiving_water_echo"),
            water_slugs=[slug] if slug else [], water_match=how,
            lat=(o or {}).get("lat"), lon=(o or {}).get("lon"),
            coord_source="outfall_registry" if o and o.get("lat") is not None else None,
            started_at=first, ended_at=last, time_precision="day",
            published_at=PUBLISHED_AT, source_updated_at=PUBLISHED_AT,
            material="combined sewage and stormwater (CSO)",
            volume_gal=g, volume_text=text,
            estimate_flag="estimated" if year == 2015 else "unknown",
            authority=AUTHORITY, source_url=url,
            raw={**raw, "year": year, "first_day": first, "last_day": last, "outfall": of, "gallons": gal,
                 "dates": "the storm's first and last day; the outfall discharged during the storm",
                 "commit": COMMIT},
            parse_error=None if o else f"outfall {of} is not in the outfall registry for {' or '.join(PERMITS)}",
        )


def merged_records(text: str, place: Placer, counts: dict) -> list[dict]:
    """CBEP's merged file, every year but the filing's."""
    rows = list(csv.DictReader(io.StringIO(text)))
    cols = [c for c in (rows[0].keys() if rows else []) if COLUMN.match(c)]
    counts["outfall_columns"] = len(cols)
    out = []
    for line, r in enumerate(rows, start=2):           # line 1 is the header
        year = int(r["Year"])
        if year == FILING_YEAR:
            continue
        counts["storms"] += 1
        storm = int(r["event"]) if (r.get("event") or "").strip().isdigit() else None   # one 2016 storm has NA
        for c in cols:
            of = COLUMN.match(c).group(1)
            g = gallons(r[c])
            if g is None:
                counts["blank_na_or_note"] += 1
                continue
            if g <= 0:
                counts["zero"] += 1
                continue
            out.append(place.record(
                year=year, first=r["firstdate"], last=r["lastdate"], of=of, gal=g, url=f"{MERGED_URL}#L{line}",
                counts=counts,
                raw={"file": MERGED_PATH, "line": line, "storm": storm, "storm_days": int(r["days"]),
                     "storm_rain_in": float(r["totalprecip"]), "storm_max_rain_in": float(r["maxprecip"]),
                     "storm_total_gal": gallons(r.get("eventtotal")),
                     "compiled_by": "Casco Bay Estuary Partnership, from the yearly workbooks of the City of Portland and PWD"}))
    return out


def filing_records(text: str, place: Placer, counts: dict) -> list[dict]:
    """The 2019 filing's extract."""
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    out, storms = [], set()
    for r in csv.DictReader(io.StringIO(body)):
        storms.add(r["storm"])
        g = gallons(r["cell"])
        if g is None:
            counts["blank_na_or_note"] += 1
            continue
        if g <= 0:
            counts["zero"] += 1
            continue
        if not r["first_day"] or not r["last_day"]:
            counts["no_date"] += 1
            continue
        refiled = (r["first_as_filed"] != r["first_day"]) or (r["last_as_filed"] != r["last_day"])
        note = (f"the filing dates this storm {r['first_as_filed']} to {r['last_as_filed']}, outside its reporting "
                f"year {FILING_YEAR}; read in {FILING_YEAR}") if refiled else None
        raw = {"file": FILING_PATH, "row": int(r["row"]), "storm": int(r["storm"]),
               "filed_by": "City of Portland (MEPDES ME0101435 filing for reporting year 2019, covering the PWD outfalls)"}
        if refiled:
            raw["date_as_filed"] = {"first": r["first_as_filed"], "last": r["last_as_filed"]}
        out.append(place.record(year=FILING_YEAR, first=r["first_day"], last=r["last_day"], of=r["outfall"], gal=g,
                                url=FILING_URL, raw=raw, counts=counts, note=note))
    counts["storms"] += len(storms)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", action="store_true", help="rebuild the 2019 filing extract from the pinned workbook")
    args = ap.parse_args(argv)
    if args.extract:
        return write_filing_extract()
    meta = {"registry_ids": [REGISTRY_ID], "files": [MERGED_URL, FILING_URL], "commit": COMMIT,
            "published_at": PUBLISHED_AT, "years": "2015-2019 (2019 from the filing)",
            "cadence": "static archive (2015 to 2019); unchanged since 2021-12-03"}
    problems = []
    if not MERGED_REF.exists():
        problems.append(f"missing {MERGED_REF.name}")
    elif hashlib.sha256(MERGED_REF.read_bytes()).hexdigest() != MERGED_SHA256:
        problems.append(f"{MERGED_REF.name} differs from the pinned file")
    if not FILING_REF.exists():
        problems.append(f"missing {FILING_REF.name}")
    if problems:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(problems), meta=meta)
        print(f"{SOURCE_ID}: " + "; ".join(problems), file=sys.stderr)
        return 1
    counts = {"storms": 0, "outfall_columns": 0, "zero": 0, "blank_na_or_note": 0, "no_date": 0,
              "not_in_registry": []}
    place = Placer(registry_index(), me_waters_by_name(), dischargers())
    records = merged_records(MERGED_REF.read_text(), place, counts)
    records += filing_records(FILING_REF.read_text(), place, counts)
    records.sort(key=lambda e: (e["started_at"], e["event_id"]), reverse=True)
    meta["counts"] = counts
    path = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} records from {counts['storms']} storms -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
