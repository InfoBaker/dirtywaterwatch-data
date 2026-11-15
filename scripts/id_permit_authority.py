"""Who issues each Idaho sewage permit of the outfall registry: Idaho DEQ (IPDES) or EPA Region 10.

Idaho DEQ has run the Idaho Pollutant Discharge Elimination System since 2018 (municipal permits from July 2018); EPA
Region 10 keeps permitting in Indian country, and a permit EPA issued before the transfer stays EPA's until DEQ
reissues it. This script reads two public records and writes, per permit, what they show (never a guess):
  - DEQ's "Issued Permits and Water Quality Certifications" table
    (https://www.deq.idaho.gov/permits/issued-permits-and-water-quality-certifications/): the rows of type IPDES give
    the permit numbers DEQ has issued. Only the permit numbers are kept: the table's permittee column names
    applicants and consultants, and the page itself is not saved.
  - The Census Bureau's federal American Indian reservations (TIGERweb AIANNHA MapServer layer 2): a plant whose point
    (EPA's, data/outfalls-plants-us.json) lies within a reservation is in Indian country, where EPA issues the permit.
Each Idaho permit of data/outfalls-plants-us.json gets one of:
  "IDEQ"      on DEQ's list of issued IPDES permits;
  "EPA"       not on DEQ's list and its plant lies within a reservation (the reservation named), or EPA types the
              facility a tribal government's;
  "unconfirmed"  neither: an expired or administratively continued permit DEQ has not listed (EPA's earlier permit,
              or one DEQ has not reissued); the operator row says so.

Writes data/reference/id-permit-authority.json. Run from the repository root:
  pipeline/.venv/bin/python scripts/id_permit_authority.py [--deq-file page.html --reservations-file r.geojson]
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "id-permit-authority.json"
HEADERS = {"User-Agent": "DirtyWaterWatch/0.1 (+https://dirtywaterwatch.org; admin@infobakery.com)"}
DEQ = "https://www.deq.idaho.gov/permits/issued-permits-and-water-quality-certifications/"
RES = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/AIANNHA/MapServer/2/query?where=1%3D1"
       "&geometry=-117.3,41.9,-111.0,49.1&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects"
       "&outFields=NAME,GEOID&returnGeometry=true&maxAllowableOffset=0.001&outSR=4326&f=geojson")


def deq_ipdes(page: str) -> set[str]:
    """The permit numbers of the table's IPDES rows."""
    m = re.search(r"<table\b.*?</table>", page or "", re.S)
    if not m:
        raise SystemExit("no table on DEQ's issued-permits page")
    out = set()
    for row in re.findall(r"<tr\b.*?</tr>", m.group(0), re.S):
        cells = [htmllib.unescape(re.sub(r"<[^>]+>", " ", c)) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) > 2 and "IPDES" in cells[2]:
            out |= set(re.findall(r"\bID[0G]\d{6}\b", " ".join(cells[:2])))
    if not out:
        raise SystemExit("no IPDES row in DEQ's table")
    return out


def build(deq: set[str], res: dict, plants: list[dict], read: str) -> dict:
    shapes = [(f["properties"]["NAME"], shape(f["geometry"])) for f in res["features"]]
    out = {}
    for r in plants:
        p = r["npdes_permit"]
        if p in out:
            continue
        inside = [n for n, g in shapes if r.get("lat") is not None and g.covers(Point(r["lon"], r["lat"]))]
        if p in deq:
            out[p] = {"authority": "IDEQ", "basis": "on Idaho DEQ's list of issued IPDES permits"}
        elif inside or r.get("facility_type") == "Tribal Government":
            where = inside[0] if inside else "Indian country (EPA: Tribal Government)"
            out[p] = {"authority": "EPA", "reservation": inside[0] if inside else None,
                      "basis": (f"not on Idaho DEQ's list of issued IPDES permits; EPA's point for the plant lies within "
                                f"the {where} (Census TIGERweb), where EPA Region 10 issues permits")
                      if inside else "not on Idaho DEQ's list; EPA types the facility a tribal government's"}
        else:
            out[p] = {"authority": "unconfirmed",
                      "basis": ("not on Idaho DEQ's list of issued IPDES permits and outside a reservation: an expired "
                                "or administratively continued permit DEQ has not listed; the issuer was not confirmed")}
    return {"read": read, "sources": {"deq_issued_permits": DEQ, "reservations": RES.split("/query")[0]},
            "rule": __doc__.split("Each Idaho permit")[0].strip().splitlines()[0],
            "counts": {k: sum(1 for v in out.values() if v["authority"] == k) for k in ("IDEQ", "EPA", "unconfirmed")},
            "permits": dict(sorted(out.items()))}


def main(argv) -> int:
    page = (Path(argv[argv.index("--deq-file") + 1]).read_text() if "--deq-file" in argv
            else requests.get(DEQ, headers=HEADERS, timeout=(20, 300)).text)
    res = (json.loads(Path(argv[argv.index("--reservations-file") + 1]).read_text()) if "--reservations-file" in argv
           else requests.get(RES, headers=HEADERS, timeout=(20, 300)).json())
    plants = [r for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if str(r.get("npdes_permit") or "").startswith("ID")]
    doc = build(deq_ipdes(page), res, plants, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{len(doc['permits'])} permits -> {OUT.relative_to(ROOT)}: {doc['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
