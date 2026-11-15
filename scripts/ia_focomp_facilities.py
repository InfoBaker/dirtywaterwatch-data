"""The Iowa DNR facilities whose field-office records the Iowa feed reads (pipeline/ingest/ia_dnr_focomp.py), from the
public site search of DNR's Field Office Compliance application (FOCOMP, https://programs.iowadnr.gov/focomp/Search/Sites).

The search's export (a PDF; /focomp/Search/SitesSearchExport) lists, per facility type, every active site with its
name, State Facility ID, address, city, county, its programs (type, program ID, status) and its "affiliates". This
script asks for the wastewater program's Major Municipal (FacilityTypeID 911) and Combined Sewer (933) facilities, reads
the export with the repository's PDF text reader (pipeline/ingest/nh_pdftext.py) and keeps only the site's name, State
Facility ID, city, county and its wastewater program IDs and types. The affiliates column names people (operators,
consultants, staff) and the address is not needed: neither is kept, and the export itself is not saved.

Writes data/reference/ia-focomp-facilities.json: {source, fetched_at, types, facilities: [{st_fac_id, name, city,
county, program_ids, types, combined_sewer}]} sorted by name. The feed reads the facilities in it; Minor Municipal
(912, about 750 sites) and the semi-public types are not read yet (the state text says so).

Run from the repository root (about two minutes; the exports are slow):
  pipeline/.venv/bin/python scripts/ia_focomp_facilities.py [--file-911 a.pdf --file-933 b.pdf]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest import nh_pdftext  # noqa: E402

OUT = ROOT / "data" / "reference" / "ia-focomp-facilities.json"
HEADERS = {"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org; admin@infobakery.com)"}
EXPORT = ("https://programs.iowadnr.gov/focomp/Search/SitesSearchExport?ProgramTypeID=21&FacilityTypeID={t}"
          "&IncludeInactive=false&HasSpills=false&OrderBy=SiteName&SortOrder=asc&ExportAs=pdf")
TYPES = {"911": "Major Municipal", "933": "Combined Sewer"}
# the export's columns (x of the column's left edge, points): name 20, State Facility ID 128, address 181, city 294,
# county 366, programs 438, affiliates 645 (never read)
COL_ID, COL_CITY, COL_COUNTY, COL_PROG, COL_AFFIL = (120, 175), (290, 362), (362, 434), (434, 640), 640


def _in(x, col):
    return col[0] <= x < col[1]


def parse_export(pdf: bytes) -> list[dict]:
    """[{st_fac_id, name, city, county, programs: [text]}] from one export; the affiliates column is never read."""
    out, cur = [], None
    for row in nh_pdftext.rows(nh_pdftext.text_items(pdf)):
        items = [i for i in row if i["x"] < COL_AFFIL]
        if any(i["text"].strip() in ("State Facility ID", "Program Type / Facility Type / ID / Status") for i in items):
            continue                                        # the column headers repeated at the top of each page
        ids = [i["text"].strip() for i in items if _in(i["x"], COL_ID) and re.fullmatch(r"\d{9}", i["text"].strip())]
        if ids:
            cur = {"st_fac_id": ids[0], "name": [], "city": [], "county": [], "programs": []}
            out.append(cur)
        if cur is None:
            continue
        for i in items:
            t = i["text"].strip()
            if not t:
                continue
            if i["x"] < 100 and not re.fullmatch(r"\d+ of \d+|FOCD Site Search", t):
                cur["name"].append(t)
            elif _in(i["x"], COL_CITY) and not ids:
                continue                                    # an address's second line runs into the city column
            elif _in(i["x"], COL_CITY):
                cur["city"].append(t)
            elif _in(i["x"], COL_COUNTY):
                cur["county"].append(t)
            elif _in(i["x"], COL_PROG):
                cur["programs"].append(t)
    for f in out:
        f["name"] = re.sub(r"\s+", " ", " ".join(f["name"])).strip()
        f["city"] = " ".join(f["city"]).strip()
        f["county"] = f["county"][-1] if f["county"] else ""
        f["programs"] = re.sub(r"\s+", " ", " ".join(f["programs"]))
    return out


def wastewater_programs(text: str) -> list[tuple[str, str]]:
    """[(type, program id)] of the wastewater programs in a site's programs text."""
    return [(m.group(1).strip(), m.group(2)) for m in
            re.finditer(r"wastewater - ([A-Za-z -]+?) - #\s*([0-9A-Z-]+)", text, re.I)]


def build(exports: dict[str, bytes], fetched_at: str) -> dict:
    by: dict[str, dict] = {}
    for t, pdf in exports.items():
        for f in parse_export(pdf):
            row = by.setdefault(f["st_fac_id"], {"st_fac_id": f["st_fac_id"], "name": f["name"], "city": f["city"],
                                                 "county": f["county"], "program_ids": [], "types": []})
            for typ, pid in wastewater_programs(f["programs"]):
                if pid not in row["program_ids"]:
                    row["program_ids"].append(pid)
                typ = typ.title()
                if typ not in row["types"]:
                    row["types"].append(typ)
    for row in by.values():
        row["combined_sewer"] = "Combined Sewer" in row["types"]
    return {"source": {"name": "Iowa DNR Field Office Compliance, site search export (wastewater program)",
                       "url": "https://programs.iowadnr.gov/focomp/Search/Sites", "fetched_at": fetched_at,
                       "facility_types": TYPES},
            "kept": "site name, State Facility ID, city, county, wastewater program IDs and types (no affiliates, no "
                    "addresses)",
            "facilities": sorted(by.values(), key=lambda r: (r["name"], r["st_fac_id"]))}


def main(argv) -> int:
    exports = {}
    for t in TYPES:
        flag = f"--file-{t}"
        if flag in argv:
            exports[t] = Path(argv[argv.index(flag) + 1]).read_bytes()
        else:
            r = requests.get(EXPORT.format(t=t), headers=HEADERS, timeout=(30, 600))
            r.raise_for_status()
            exports[t] = r.content
    doc = build(exports, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    cs = sum(1 for f in doc["facilities"] if f["combined_sewer"])
    print(f"{len(doc['facilities'])} facilities ({cs} combined sewer) -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
