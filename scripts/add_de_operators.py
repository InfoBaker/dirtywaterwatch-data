"""Delaware operator rows for data/dischargers.json: one row per operator, every Delaware permit of the outfall
registry in exactly one row, and the sewer operators DNREC's release reports name.

Usage: pipeline/.venv/bin/python -I scripts/add_de_operators.py [--dry-run]

Inputs
  - research/de/dischargers.json (6 rows): Wilmington's combined system (DE0020320, the state's one CSO permit, 41
    open outfalls in EPA's inventory), New Castle County, Kent County (DE0020338), the City of Dover, Sussex County
    and Millsboro. Each keeps its research id.
  - data/outfalls-plants-us.json and data/outfalls-us.json: every Delaware permit EPA lists (12 plant permits and the
    CSO permit). The permits of one owner are one row (PLANTS names the owner of each plant: EPA records the plant's
    name as permittee for every Delaware POTW).
  - DE0051071 "NEW CASTLE COUNTY-MS4" (EPA lists it with a POTW component) is New Castle County's and the
    Department of Transportation's municipal separate storm sewer permit: a storm sewer, not sewage. It is held in
    New Castle County's row and its outfall is kind "other" (data/outfalls-de.json), so the share line counts only
    sewage outfalls.
  - The operators DNREC's release reports name that hold no surface-discharge permit (EXTRA: the City of Newark and the
    Towns of Middletown and Smyrna, whose sewers feed a county or the Wilmington plant) and the private wastewater
    utilities the Public Service Commission regulates (Artesian Wastewater Management, Tidewater Environmental
    Services: https://depsc.delaware.gov/wastewater-regulation/, read 2026-11-09 in the expansion research).
Rules
  - legal_form from the controlled list (docs/legal-forms.md); never an individual's name.
  - notification_channel: DNREC's release list (7 Del. C. 6028: a sewage release of 10,000 gallons or more reported to
    DNREC and posted by DNREC within one business day; permitted discharges exempt); Wilmington's CSO signs; the
    operator's own pages were not searched individually.
  - Idempotent: every row with state DE is rebuilt; other states' rows are left as they are; the Delaware rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "de" / "dischargers.json"
CHECKED = "2026-11-14"
DERNS = "https://derns.dnrec.delaware.gov/Pub/RecentReleases.aspx"
LAW = ("DNREC's Environmental Release Notification System (7 Del. C. 6028): a sewage release of 10,000 gallons or "
       "more is reported to DNREC at once and DNREC posts it on its public Recent Releases list within one business "
       f"day ({DERNS}); smaller releases appear when they are reported. DNREC also notifies the district's legislators "
       "and registered neighbours within 12 hours (6014(b)). The operator's own pages were not searched individually.")
CSO = (" Wilmington's combined sewer overflows are permitted discharges, exempt from that duty: each outfall is marked "
       "by a sign, and no overflow notice, list or alert was found on the City's pages "
       "(https://wilmingtondewater.gov/262/Combined-Sewer-Overflows-CSOs).")
# research id -> (extra permits, kind, legal_form, short name, name)
RESEARCH_ROWS = {
    "de-de0020320": ([], "cso", "city", "City of Wilmington",
                     "City of Wilmington (Wilmington Regional Wastewater Treatment Plant and combined sewer system)"),
    "de-new-castle-county": (["DE0050547", "DE0051071"], "sso", "county", "New Castle County",
                             "New Castle County Department of Public Works (sewer)"),
    "de-kent-county": ([], "plant", "county", "Kent County", "Kent County Levy Court, Wastewater (Kent County "
                       "Regional Resource Recovery Facility)"),
    "de-city-of-dover": ([], "sso", "city", "City of Dover", "City of Dover Public Works (collection system)"),
    "de-sussex-county": ([], "sso", "county", "Sussex County",
                         "Sussex County Engineering, Environmental Services (wastewater)"),
    "de-millsboro": ([], "sso", "town", "Town of Millsboro", "Town of Millsboro (wastewater)"),
}
# EPA plant permit -> (row id, name, legal_form, town, note). An owner is named only where EPA's permittee field names
# it (DE0020338 "KENT COUNTY ...", DE0050547 "... - NCC", DE0051071 "NEW CASTLE COUNTY-DELDOT MS4"); every other
# Delaware POTW permit carries the plant's name as permittee, so its row is the permit's and names no owner, and it is
# left out of operator counts (re-review P2-5: never an owner inferred from a plant's town)
UNVERIFIED = ("EPA records the plant's name as the permittee; the owner was not verified against the permit, so the "
              "row is the permit's and names no owner.")
PLANTS = {
    "DE0020010": ("de-de0020010", "Selbyville Wastewater Treatment Facility (permittee not recorded by EPA)", None,
                  "Selbyville", UNVERIFIED),
    "DE0020028": ("de-de0020028", "Rehoboth Beach Wastewater Treatment Plant (permittee not recorded by EPA)", None,
                  "Rehoboth Beach", UNVERIFIED),
    "DE0020125": ("de-de0020125", "Laurel Sewage Treatment Plant (permittee not recorded by EPA)", None, "Laurel",
                  UNVERIFIED),
    "DE0020265": ("de-de0020265", "Seaford Wastewater Treatment Plant (permittee not recorded by EPA)", None, "Seaford",
                  UNVERIFIED),
    "DE0021491": ("de-de0021491", "Milton Water Reclamation Facility (permittee not recorded by EPA)", None, "Milton",
                  UNVERIFIED),
    "DE0021512": ("de-de0021512", "Howard Seymour Water Reclamation Plant, Lewes (permittee not recorded by EPA)", None,
                  "Lewes", UNVERIFIED),
    "DE0050008": ("de-de0050008", "South Coastal Regional Wastewater Facility (permittee not recorded by EPA)", None,
                  "Frankford", UNVERIFIED),
    "DE0021539": ("de-de0021539", "Port Penn Wastewater Treatment Plant (permittee not recorded by EPA)", None,
                  "Port Penn", UNVERIFIED),
    "DE0021555": ("de-de0021555", "Delaware City Wastewater Treatment Plant (permittee not recorded by EPA)", None,
                  "Delaware City", UNVERIFIED),
    "DE0020338": ("de-kent-county", None, "county", "Milford", "The Kent County Regional Resource Recovery Facility "
                  "(EPA's permittee: 'KENT COUNTY WASTEWATER TREATMENT FACILITY')."),
    "DE0050547": ("de-new-castle-county", None, "county", "Middletown",
                  "The MOT (Middletown-Odessa-Townsend) Wastewater Treatment Plant, New Castle County's (EPA's permittee: "
                  "'MOT Wastewater Treatment Plant - NCC')."),
    "DE0051071": ("de-new-castle-county", None, "county", "New Castle",
                  "DE0051071 is New Castle County's and DelDOT's municipal separate storm sewer permit (MS4): a storm "
                  "sewer, not sewage; its EPA row is kind other in data/outfalls-de.json."),
}
# operators the release reports name, with no surface-discharge permit
EXTRA = {
    "de-city-of-newark": ("City of Newark (sewer)", "city", ["Newark"], "sso",
                          "Newark's sewers drain to New Castle County's system; named by DNREC's release reports."),
    "de-town-of-middletown": ("Town of Middletown (sewer)", "town", ["Middletown"], "sso",
                              "Middletown's sewers drain to New Castle County's MOT plant; named by DNREC's release "
                              "reports."),
    "de-town-of-smyrna": ("Town of Smyrna (sewer)", "town", ["Smyrna"], "sso",
                          "Smyrna's sewers drain to Kent County's plant; named by DNREC's release reports."),
    "de-artesian-wastewater": ("Artesian Wastewater Management, Inc.", "investor-owned utility", [], "sso",
                               "A private wastewater utility the Public Service Commission regulates "
                               "(https://depsc.delaware.gov/wastewater-regulation/); its systems discharge to land, not "
                               "under a surface-discharge permit EPA lists."),
    "de-tidewater-environmental": ("Tidewater Environmental Services, Inc.", "investor-owned utility", [], "sso",
                                   "A private wastewater utility the Public Service Commission regulates "
                                   "(https://depsc.delaware.gov/wastewater-regulation/)."),
}


def load_epa() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        for r in doc["outfalls"]:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("DE") or r.get("state") not in (None, "DE"):
                continue
            o = out.setdefault(p, {"facility": r.get("permittee"), "waters": [], "outfalls": 0, "open_cso": 0})
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w.title() not in o["waters"]:
                o["waters"].append(w.title())
            o["outfalls"] += 1
            if f == "outfalls-us.json" and not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                o["open_cso"] += 1
    return out


def row(rid, name, permits, kind, lf, towns, waters, outfalls, notes, short=None, research=False) -> dict:
    r = {"id": rid, "name": name, "state": "DE", "kind": kind, "npdes_permit": permits[0] if permits else None,
         "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [], "outfall_count": outfalls or None,
         "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points and the national CSO inventory "
                             f"(data/outfalls-plants-us.json, data/outfalls-us.json: {outfalls} rows for these permits)"
                             if outfalls else None),
         "notification_channel": LAW + (CSO if kind == "cso" else ""),
         "notification_feed_machine_readable": True, "notification_signup_url": None,
         "towns": towns, "notes": notes, "verified": "fetched", "checked": CHECKED, "aliases": [rid],
         "source_areas": ["de"] + ([] if research else ["federal"]), "legal_form": lf}
    if short:
        r["short_name"] = short
    return r


def build(epa: dict, research: list[dict]) -> list[dict]:
    rows: dict[str, dict] = {}
    for r in research:
        extra, kind, lf, short, name = RESEARCH_ROWS[r["id"]]
        permits = [p for p in [r.get("npdes_permit"), *extra] if p]
        waters = list(dict.fromkeys(r.get("receiving_waters") or []))
        n = sum(epa.get(p, {}).get("outfalls", 0) for p in permits)
        note = ((r.get("notes") or "").strip() + f" Research row (research/de/dischargers.json, checked "
                f"{r.get('checked')}).").strip()
        rows[r["id"]] = row(r["id"], name, permits, kind, lf, r.get("towns") or [], waters, n, note, short, True)
    for p, o in sorted(epa.items()):
        rid, name, lf, town, note = PLANTS.get(p, (f"de-{p.lower()}", (o["facility"] or p).title(), None, None, None))
        if rid in rows:
            if p not in rows[rid]["npdes_permits"]:
                rows[rid]["npdes_permits"].append(p)
            if town and town not in rows[rid]["towns"]:
                rows[rid]["towns"].append(town)
            if note:
                rows[rid]["notes"] += " " + f"{p}: {note}"
            continue
        n = o["outfalls"]
        rows[rid] = row(rid, name, [p], "cso" if o["open_cso"] else "plant", lf, [town] if town else [], o["waters"], n,
                        f"EPA ECHO ICIS-NPDES: {p} {o['facility']}." + (f" {note}" if note else ""))
    for rid, r in rows.items():
        r["outfall_count"] = sum(epa.get(p, {}).get("outfalls", 0) for p in r["npdes_permits"]
                                 if p != "DE0051071") or None
        r["npdes_permit"] = r["npdes_permits"][0] if r["npdes_permits"] else None
    for rid, (name, lf, towns, kind, note) in EXTRA.items():
        if rid in rows:
            continue
        rows[rid] = row(rid, name, [], kind, lf, towns, [], 0, note, research=True)
    return sorted(rows.values(), key=lambda r: r["id"])


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    new = build(load_epa(), json.loads(RESEARCH.read_text()))
    others = [r for r in dis if r.get("state") != "DE"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    if [i for i, n in ids.items() if n > 1]:
        raise SystemExit("duplicate ids")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
                      "by_form": dict(Counter(r.get("legal_form") for r in new))}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
