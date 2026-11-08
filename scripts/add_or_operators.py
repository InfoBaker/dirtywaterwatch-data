"""Oregon operator rows for data/dischargers.json: one row per operator, every Oregon sewage permit EPA lists in exactly
one row.

Usage: pipeline/.venv/bin/python -I scripts/add_or_operators.py [--dry-run]

Inputs
  - data/outfalls-us.json: the three Oregon CSO permits of EPA's national CSO inventory (Portland's Columbia Boulevard
    plant OR0026905, 36 open outfalls; Astoria OR0027561, 38; Corvallis OR0026361, 4).
  - data/outfalls-plants-us.json: the 163 Oregon plant permits EPA lists (ICIS-NPDES permitted features), one outfall
    row each.
  - research/or/dischargers.json (9 rows): Portland, Astoria, Corvallis, Clean Water Services, Water Environment
    Services, Oak Lodge Water Services, Salem, the Metropolitan Wastewater Management Commission and Tillamook. Each
    keeps its research id.
  - research/or/private-utilities-candidates.json: OR0030864 (Brandy Bar Landing, Inc., a privately owned sewage
    permit outside the plant table) and OR0020834 (the City of St. Helens, typed privately owned by EPA but a city).
Rules
  - GROUPS: the permits one operator holds (Portland's Columbia Boulevard and Tryon Creek plants; Clean Water Services'
    four plants; Water Environment Services' four; Rogue Valley Sewer Services' two; Coos Bay's two; the Confederated
    Tribes of Warm Springs' two). Every other permit is its own row.
  - Names and legal forms (docs/legal-forms.md): a grouped operator's name, short name and form are written below
    from what the operator is (Clean Water Services and Water Environment Services are county service districts and
    Rogue Valley Sewer Services and Oak Lodge Water Services special districts: "special district"; the Metropolitan
    Wastewater Management Commission is an intergovernmental commission: "authority"; the Warm Springs tribes:
    "tribal"). A single plant whose town is an incorporated Oregon city (CITY_PERMITS: the town is read from EPA's
    facility name, "WOODBURN WWTP" -> Woodburn) is "City of <Town>", legal form "city", with the basis in the notes
    (inferred from the facility's name and the town; not checked against DEQ's permit). The other single plants
    (sanitary districts, joint authorities, schools, a port, resorts, unincorporated places: NOT_CITY) keep EPA's
    facility name and no legal form, except where the name says what it is (KNOWN_FORMS).
  - kind: "cso" for the three CSO permittees, "sso" for the research's separate-sewer operators, "plant" otherwise.
  - notification_channel: the permit's general conditions (Schedule F, read in DEQ's general conditions): the
    permittee alerts the public by its own Emergency Response and Public Notification Plan, with no deadline and no
    channel set; Portland's and Oak Lodge's own posts where they exist; the operator's own pages were not searched
    otherwise.
  - No individual is named: every name is a public body's or a company's; EPA's facility name is title-cased.
  - Idempotent: every row with state OR is rebuilt; other states' rows are left as they are; the Oregon rows are
    written after the last row of the file in id order.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "or" / "dischargers.json"
PRIVATE = ROOT / "research" / "or" / "private-utilities-candidates.json"
CHECKED = "2026-11-07"
SCHEDULE_F = "https://www.oregon.gov/deq/FilterPermitsDocs/WPCFGenCondDom.pdf"
LAW = ("DEQ's permit general conditions (NPDES Schedule F; the WPCF domestic general conditions): \"If effluent "
       "limitations specified in this permit are exceeded or an overflow occurs that threatens public health, the "
       "permittee must take such steps as are necessary to alert the public, health agencies and other affected "
       "entities (e.g., public water systems) about the extent and nature of the discharge in accordance with the "
       "notification procedures specified in this permit or as specified in its Emergency Response and Public "
       "Notification Plan\". No deadline and no channel are set; the permittee reports to the Oregon Emergency Response "
       "System by telephone within 24 hours and to DEQ in writing within five days, and neither report is published.")
NOT_SEARCHED = " The operator's own web pages were not searched individually."
CHANNELS = {
    "or-portland-bes": (" Portland Environmental Services publishes a CSO Advisory or Sewage Advisory for each event on "
                        "its news page and RSS feed (read by this site), the Big Pipe Tracker shows the current CSO "
                        "advisory and the tunnels' fill every 15 minutes, and a GovDelivery e-mail list sends the CSO "
                        "advisories.", "https://public.govdelivery.com/accounts/ORPORTLAND_ENT/signup/39493", True),
    "or-oak-lodge": (" Oak Lodge Water Services posts each overflow as a news article on its website (for example "
                     "2025-12-18: three lift stations, impacts to Kellogg Creek and the Willamette River).", None, False),
}
# operator id -> (permits, name, short name, legal form or None, kind)
GROUPS = {
    "or-portland-bes": (["OR0026905", "OR0026891"],
                        "City of Portland Environmental Services (Columbia Boulevard and Tryon Creek plants and the "
                        "combined and separate sewer systems)", "Portland Environmental Services", "city", "cso"),
    "or-astoria": (["OR0027561"], "City of Astoria (wastewater treatment plant and combined sewer system)",
                   "City of Astoria", "city", "cso"),
    "or-corvallis": (["OR0026361"], "City of Corvallis (wastewater reclamation plant and combined sewer outfalls)",
                     "City of Corvallis", "city", "cso"),
    "or-clean-water-services": (["OR0020168", "OR0023345", "OR0028118", "OR0029777"],
                                "Clean Water Services (Washington County: Forest Grove, Hillsboro, Durham and Rock "
                                "Creek plants)", "Clean Water Services", "special district", "sso"),
    "or-wes-clackamas": (["OR0026221", "OR0031259", "OR0031020", "OR0031399"],
                         "Water Environment Services (Clackamas County: Kellogg Creek, Tri-City, Hoodland and Boring "
                         "plants)", "Water Environment Services", "special district", "sso"),
    "or-oak-lodge": (["OR0026140"], "Oak Lodge Water Services (water reclamation facility, Milwaukie)",
                     "Oak Lodge Water Services", "special district", "sso"),
    "or-salem": (["OR0026409"], "City of Salem (Willow Lake water pollution control facility)", "City of Salem", "city",
                 "sso"),
    "or-mwmc-eugene-springfield": (["OR0031224"], "Metropolitan Wastewater Management Commission (Eugene-Springfield)",
                                   "Metropolitan Wastewater Management Commission", "authority", "sso"),
    "or-tillamook": (["OR0020664"], "City of Tillamook (wastewater treatment plant)", "City of Tillamook", "city", "sso"),
    "or-rogue-valley-sewer": (["OR0022594", "OR0030660"], "Rogue Valley Sewer Services (Gold Hill and Shady Cove plants)",
                              "Rogue Valley Sewer Services", "special district", "plant"),
    "or-coos-bay": (["OR0023574", "OR0023582"], "City of Coos Bay (plants No. 1 and No. 2, Empire)", "City of Coos Bay",
                    "city", "plant"),
    "or-warm-springs-tribes": (["OR0032638", "OR0034100"],
                               "Confederated Tribes of Warm Springs (Warm Springs and Kah-Nee-Ta plants)",
                               "Confederated Tribes of Warm Springs", "tribal", "plant"),
    "or-st-helens": (["OR0020834"], "City of St. Helens (wastewater treatment plant)", "City of St. Helens", "city", "plant"),
    "or-brandy-bar-landing": (["OR0030864"], "Brandy Bar Landing, Inc. (Reedsport)", "Brandy Bar Landing",
                              "business or industrial", "plant"),
    "or-gresham": (["OR0026131"], "City of Gresham (wastewater treatment plant)", "City of Gresham", "city", "plant"),
    "or-albany": (["OR0028801"], "City of Albany (Albany-Millersburg water reclamation facility)", "City of Albany",
                  "city", "plant"),
    "or-medford": (["OR0026263"], "City of Medford (regional water reclamation facility, Central Point)",
                   "City of Medford", "city", "plant"),
    "or-sandy": (["OR0026573"], "City of Sandy (wastewater treatment plant, Boring)", "City of Sandy", "city", "plant"),
    "or-roseburg-rusa": (["OR0031356"], "Roseburg Urban Sanitary Authority (Roseburg plant)",
                         "Roseburg Urban Sanitary Authority", "special district", "plant"),
    "or-south-suburban-sd": (["OR0023876"], "South Suburban Sanitary District (Klamath Falls)",
                             "South Suburban Sanitary District", "special district", "plant"),
}
# single plants that are not a city's: EPA's facility name kept, no legal form unless KNOWN_FORMS gives it
NOT_CITY = {"OR0022471", "OR0026018", "OR0023493", "OR0027499", "OR0027791", "OR0027201", "OR0029882", "OR0030066",
            "OR0031461", "OR0027294", "OR0023370", "OR0022616", "OR0031496", "OR0041246", "OR0032387", "OR0033049",
            "OR0031453", "OR0022918", "OR0030945", "OR0028355", "OR0030210", "OR0030392", "OR0044709"}
KNOWN_FORMS = {"OR0031496": "special district"}      # "Westport Sewer Service District": the name says so
# a town spelled otherwise in EPA's facility name (after the suffixes are cut)
TOWN_FIX = {"Mt. Angel": "Mount Angel", "Mt Vernon": "Mount Vernon"}
TOWN_CUT = re.compile(r"^City of\s+|,\s*City of$|\s+(?:Wastewater Treatment and Reclamation Facility.*|"
                      r"Water Pollution Control Facility|Wastewater Treatment Facility|Wastewater Treatment Plant|"
                      r"Lagoon Treatment Plant|Water Reclamation Facility|- Wynooski Road)$", re.I)
SUFFIX = re.compile(r"\s*(?:STP|WWTP|WWTF|WPCF|WRF|RWRF|SEWAGE TREATMENT PLANT|WASTEWATER TREATMENT PLANT|"
                    r"WATER RECLAMATION FACILITY)\s*$", re.I)
TOWN_FORMS = {"Lakeview": "town"}                    # Oregon's Lakeview is the Town of Lakeview
RIVER_MILE = re.compile(r"\s*\((?:RM|RIVER MILE)[^)]*\)|\s*\(RM\s*[\d.]+\)", re.I)


def title(s: str | None) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if not (s.isupper() or s.islower()):
        return s
    t = s.title()
    t = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), t)
    for w in ("Of", "And", "To", "At", "The", "Via"):
        t = re.sub(rf"(?<=\s){w}\b", w.lower(), t)
    return re.sub(r"\b(Stp|Wwtp|Wwtf|Wpcf|Wrf|Rwrf|Jwsa|Bsd|Wes|Mwmc|R\.U\.S\.A\.|Am)\b", lambda m: m.group(1).upper(), t)


def water(s: str | None) -> str | None:
    s = RIVER_MILE.sub("", (s or "").strip())
    return title(s) or None


def town_of(facility: str) -> str | None:
    t = title(SUFFIX.sub("", facility or "").strip())
    for _ in range(3):
        t = TOWN_CUT.sub("", t).strip()
    return TOWN_FIX.get(t, t) or None


def load_epa() -> dict[str, dict]:
    """permit -> {facility, city, waters, outfalls, kind}."""
    out: dict[str, dict] = {}
    for fname, kind in (("outfalls-us.json", "cso"), ("outfalls-plants-us.json", "plant")):
        doc = json.loads((ROOT / "data" / fname).read_text())
        for r in doc["outfalls"] if isinstance(doc, dict) else doc:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("OR") or r.get("state") not in (None, "OR"):
                continue
            o = out.setdefault(p, {"facility": None, "city": None, "waters": [], "outfalls": 0, "kind": kind})
            o["facility"] = o["facility"] or r.get("permittee")
            o["city"] = o["city"] or r.get("city")
            for w in re.split(r"\s*[,/]\s*", r.get("receiving_water_echo") or ""):
                w = water(w)
                if w and w not in o["waters"] and not w.lower().startswith("at its mouth"):
                    o["waters"].append(w)
            if str(r.get("outfall_status") or "").lower() not in ("closed", "eliminated", "inactive"):
                o["outfalls"] += 1
    cand = json.loads(PRIVATE.read_text())
    for c in cand["candidates"] + cand.get("public_by_name", []):
        out.setdefault(c["npdes_permit"], {"facility": c["facility"], "city": c.get("city"),
                                           "waters": [water(w) for w in c.get("receiving_waters_echo") or []],
                                           "outfalls": 0, "kind": "plant"})
    return out


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def build(epa: dict[str, dict], research: list[dict]) -> tuple[list[dict], dict]:
    owner = {p: rid for rid, g in GROUPS.items() for p in g[0]}
    missing = sorted(set(owner) - set(epa))
    if missing:
        raise SystemExit(f"grouped permits EPA does not list: {missing}")
    res = {r["id"]: r for r in research}
    rows = []
    for rid, (permits, name, short, lf, kind) in GROUPS.items():
        rows.append(row(rid, permits, name, short, lf, kind, epa, res.get(rid), None))
    for p in sorted(set(epa) - set(owner)):
        e = epa[p]
        fac = title(e["facility"])
        if p in NOT_CITY:
            town = None
            name, short, lf = fac, fac, KNOWN_FORMS.get(p)
            basis = ("EPA's facility name; the permittee (a sanitary district, a joint authority, a school district, a "
                     "port or a private owner) was not checked against DEQ's permit, so no legal form is given"
                     if not lf else "the permittee's name says what it is")
        else:
            town = town_of(e["facility"])
            if not town:
                raise SystemExit(f"{p}: no town read from {e['facility']!r}")
            lf = TOWN_FORMS.get(town, "city")
            name = f"{'Town' if lf == 'town' else 'City'} of {town} ({fac})"
            short = f"{'Town' if lf == 'town' else 'City'} of {town}"
            basis = (f"the plant of {town}, an incorporated Oregon {'town' if lf == 'town' else 'city'} (inferred from "
                     "EPA's facility name; not checked against DEQ's permit)")
        rid = "or-" + slug(town or fac)
        if any(r["id"] == rid for r in rows):
            rid = f"{rid}-{p.lower()}"
        rows.append(row(rid, [p], name, short, lf, "plant", epa, None, basis, town))
    rows.sort(key=lambda r: r["id"])
    stats = {"rows": len(rows), "permits": sum(len(r["npdes_permits"]) for r in rows),
             "by_form": dict(Counter(r.get("legal_form") for r in rows)),
             "by_kind": dict(Counter(r["kind"] for r in rows))}
    return rows, stats


def row(rid, permits, name, short, lf, kind, epa, r0, basis, town=None) -> dict:
    towns = list((r0 or {}).get("towns") or ([town] if town else []))
    for p in permits:
        t = title(epa[p].get("city") or "")
        if t and t not in towns:
            towns.append(t)
    waters = list(dict.fromkeys([water(w) for w in (r0 or {}).get("receiving_waters") or []]
                                + [w for p in permits for w in epa[p]["waters"]]))
    waters = [w for w in waters if w]
    n_out = sum(epa[p]["outfalls"] for p in permits)
    n_cso = sum(epa[p]["outfalls"] for p in permits if epa[p]["kind"] == "cso")
    facs = "; ".join(f"{p} {epa[p]['facility']}" for p in permits)
    note = f"EPA ECHO ICIS-NPDES and the national CSO inventory: {facs}."
    if n_cso:
        note += f" {n_cso} open combined sewer outfalls in EPA's inventory."
    if basis:
        note += f" Name: {basis}."
    if r0:
        note += f" Research row (research/or/dischargers.json, checked {r0.get('checked')})."
    extra, signup, feed = CHANNELS.get(rid, (NOT_SEARCHED, None, False))
    out = {"id": rid, "name": name, "state": "OR", "kind": kind, "npdes_permit": permits[0],
           "npdes_permits": list(permits), "receiving_waters": waters, "water_slugs": [],
           "outfall_count": n_out or None,
           "outfalls_source": (f"EPA's national CSO inventory and ICIS-NPDES discharge points (data/outfalls-us.json, "
                               f"data/outfalls-plants-us.json: {n_out} open rows for these permits)") if n_out else None,
           "notification_channel": LAW + extra, "notification_feed_machine_readable": feed,
           "notification_signup_url": signup, "towns": towns, "notes": note,
           "verified": "fetched" if r0 and r0.get("verified") == "fetched" else "inferred", "checked": CHECKED,
           "aliases": [rid], "source_areas": ["or"] + ([] if r0 else ["federal"]), "short_name": short}
    if lf:
        out["legal_form"] = lf
    return out


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    new, stats = build(load_epa(), json.loads(RESEARCH.read_text()))
    others = [r for r in dis if r.get("state") != "OR"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
