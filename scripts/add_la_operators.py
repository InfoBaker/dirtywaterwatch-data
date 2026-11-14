"""Louisiana operator rows for data/dischargers.json: one row per operator, every Louisiana permit in one row.

Usage: pipeline/.venv/bin/python -I scripts/add_la_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES sewage permits with state LA (433 permits on 2026-11-14). EPA's
     permit_name is "<owner> - <plant>"; the owner is the part before the dash.
  2. data/outfalls-la.json: the two industrial "CSO" rows of EPA's inventory (kind other); Louisiana has no municipal
     combined sewer permit.
  3. research/la/dischargers.json (8 rows): each research id is an alias of the row holding its operator (by permit,
     or for the six rows that name none, by RESEARCH_OWNER).
  4. research/la/private-utilities-candidates.json (126 private sewage permits): a permit not already held gets a row.
  5. The collection-system permits named in Baton Rouge's quarterly reports (LA0036439, LA0036412) hold the City-
     Parish's reports: kind "sso".
Rules: scripts/wv_la_operator_rules.py (owner names and legal forms; never a person's name). notification_channel:
the law (LAW) and the operator's own published reports where read (OWN_CHANNELS). Idempotent: a rerun replaces the
rows it wrote (state LA, source_areas ["la"]).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wv_la_operator_rules import clean, owner, slug, title  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-la.json"
RESEARCH = ROOT / "research" / "la" / "dischargers.json"
CANDIDATES = ROOT / "research" / "la" / "private-utilities-candidates.json"
CHECKED = "2026-11-14"
ST = "LA"
LAW = ("Louisiana's rules on unauthorized discharges (LAC 33:I Chapter 39) send an emergency discharge to the State "
       "Police hotline within the first hour and a discharge above a reportable quantity within 24 hours, with a "
       "written report to LDEQ within seven calendar days; other permit excursions go to LDEQ's Single Point of "
       "Contact, and the permit's standard conditions add the federal 24-hour and five-day reports (40 CFR "
       "122.41(l)(6)). LDEQ keeps the reports in its document system, which is searched one document at a time behind "
       "a reCAPTCHA; no list is published and no duty to tell the public was found. The operator's own pages were not "
       "searched individually unless named here.")
OWN_CHANNELS = {
    "LA0036412": ("https://brprojects.com/baton-rouge-sso-program/program-overview/regulatory-information/",
                  " The City-Parish publishes its consent-decree quarterly reports to EPA and LDEQ, whose Part D lists "
                  "each unauthorized discharge of the quarter (date, cause, receiving water, gallons) about a month "
                  "after the quarter ends."),
    "LA0038091": ("https://www.swbno.org/Wastewater/ConsentDecree",
                  " The Board publishes its consent-decree quarterly and annual reports; the Q3 2026 report (624 pages) "
                  "holds no dated list of overflows."),
    "LA0041394": ("https://cleanwatershreveport.com/consent-decree-public-repository/",
                  " The City publishes its consent-decree annual reports, with a numbered table of the year's sanitary "
                  "sewer overflows; the site did not answer this project's client on 2026-11-14."),
}
OVERRIDES = [
    (r"baton rouge (?:city|ph)|e baton rouge city|city of baton rouge|east baton rouge parish",
     "City of Baton Rouge and Parish of East Baton Rouge", "city"),
    (r"sewerage (?:&|and) water board of new|sewerage & water board", "Sewerage and Water Board of New Orleans",
     "authority"),
    (r"jefferson parish (?:department|dept) of sewerage|jefferson parish sewerage", "Jefferson Parish Department of Sewerage",
     "county"),
    (r"shreveport", "City of Shreveport", "city"),
    (r"^bossier city", "City of Bossier City", "city"),
    (r"terrebonne ph(?:arish)? conso", "Terrebonne Parish Consolidated Government", "county"),
    (r"^utilities,? inc\.? of (?:la|louisiana)\b", "Utilities, Inc. of Louisiana", "investor-owned utility"),
    (r"magnolia water utility operating", "Magnolia Water Utility Operating Company, LLC", "investor-owned utility"),
    (r"nati?onal water infrastructure", "National Water Infrastructure, LLC", "investor-owned utility"),
    (r"lafayette consolidated government|city of lafayette", "Lafayette Consolidated Government", "county"),
    (r"st\.? tammany parish gov|st\.? tammany parish government", "St. Tammany Parish Government", "county"),
]
RESEARCH_OWNER = {"la-swbno": "Sewerage and Water Board of New Orleans",
                  "la-baton-rouge": "City of Baton Rouge and Parish of East Baton Rouge",
                  "la-jefferson-parish": "Jefferson Parish Department of Sewerage", "la-shreveport": "City of Shreveport",
                  "la-lafayette-lus": "Lafayette Consolidated Government",
                  "la-st-tammany": "St. Tammany Parish Government"}
SSO_PERMITS = {"LA0036439", "LA0036412"}


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    plants = [r for r in json.loads(PLANTS.read_text())["outfalls"] if r.get("state") == ST]
    other = {r["npdes_permit"]: r for r in json.loads(CSO.read_text())["outfalls"]}   # industrial, kind other
    open_cso: dict = {}
    cso_permits: set = set()
    cso_waters: dict = defaultdict(set)
    by_permit: dict[str, dict] = {}
    for r in plants:
        p = r["npdes_permit"]
        e = by_permit.setdefault(p, {"permit_name": r.get("permit_name"), "permittee": r.get("permittee"),
                                     "facility_type": r.get("facility_type"), "city": r.get("city"), "waters": set(),
                                     "rows": 0, "source": "EPA ICIS-NPDES (data/outfalls-plants-us.json)"})
        e["rows"] += 1
        if r.get("receiving_water_echo"):
            e["waters"].add(clean(r["receiving_water_echo"]))
    for p, r in other.items():
        e = by_permit.setdefault(p, {"permit_name": r.get("permittee"), "permittee": r.get("permittee"),
                                     "facility_type": None, "city": r.get("city"), "waters": set(), "rows": 0,
                                     "source": "EPA CSO inventory, industrial (data/outfalls-la.json)"})
        e["industrial_cso"] = True
    cand = json.loads(CANDIDATES.read_text())
    for c in cand.get("candidates") or []:
        if c.get("npdes_permit") and c["npdes_permit"] not in by_permit:
            by_permit[c["npdes_permit"]] = {"permit_name": c.get("permittee_as_recorded"), "permittee": None,
                                            "facility_type": (c.get("ownership") or {}).get("facility_type"),
                                            "city": c.get("city"), "waters": set(c.get("receiving_waters_echo") or []),
                                            "rows": 0, "source": "private sewage candidates (research)",
                                            "legal_form": c.get("legal_form_proposed")}
    research = json.loads(RESEARCH.read_text())
    alias = defaultdict(list)
    by_owner = defaultdict(list)
    for r in research:
        if r.get("npdes_permit"):
            alias[r["npdes_permit"]].append(r["id"])
        elif r["id"] in RESEARCH_OWNER:
            by_owner[RESEARCH_OWNER[r["id"]]].append(r["id"])
    groups: dict[str, dict] = {}
    hows = defaultdict(int)
    for p, e in sorted(by_permit.items()):
        name, form, how = owner(e["permit_name"], e["permittee"], e["facility_type"], ST, p, OVERRIDES)
        if e.get("legal_form") and how not in ("override",) and not name.startswith("Holder of permit"):
            form = e["legal_form"]
        hows[how] += 1
        g = groups.setdefault(slug(name), {"name": name, "legal_form": form, "permits": [], "waters": set(), "towns": set(),
                                     "aliases": [], "notes": [], "outfalls": 0, "sources": set()})
        g["permits"].append(p)
        g["waters"] |= e["waters"] | cso_waters.get(p, set())
        if e.get("city"):
            g["towns"].add(title(clean(e["city"]).split(",")[0]))
        g["aliases"] += alias.get(p, []) + [x for x in by_owner.get(g["name"], []) if x not in g["aliases"]]
        if e.get("industrial_cso"):
            g["notes"].append(f"{p}: EPA's combined sewer inventory lists this industrial plant's combined outfall; "
                              "not a municipal combined sewer outlet (data/outfalls-la.json)")
        g["outfalls"] += open_cso.get(p, 0) or e["rows"]
        g["sources"].add(e["source"])
        if how not in ("override", "municipal"):
            g["notes"].append(f"{p}: EPA records the permittee as \"{title(clean(e['permit_name'] or ''))}\""
                              if not name.startswith("Holder of permit") else f"{p}: the permittee's name is withheld")
    rows = []
    for _, g in sorted(groups.items()):
        name = g["name"]
        permits = sorted(g["permits"])
        cso = [p for p in permits if p in cso_permits]
        channel = LAW
        url = None
        for p in permits:
            if p in OWN_CHANNELS:
                url, extra = OWN_CHANNELS[p]
                channel += extra
        rid = f"la-{slug(name)}"
        rows.append({
            "id": rid, "name": name, "short_name": name, "legal_form": g["legal_form"], "state": ST,
            "kind": "sso" if set(permits) & SSO_PERMITS else "plant", "npdes_permit": permits[0], "npdes_permits": permits,
            "receiving_waters": sorted(g["waters"])[:20], "water_slugs": [],
            "outfall_count": g["outfalls"],
            "outfalls_source": "EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json)",
            "notification_channel": channel, "notification_feed_machine_readable": False,
            "notification_signup_url": url, "towns": sorted(g["towns"]),
            "notes": "; ".join(g["notes"][:6]) or None, "verified": "fetched", "checked": CHECKED,
            "aliases": sorted(set([rid] + g["aliases"])), "source_areas": ["la"]})
    keep = [r for r in dis if not (r.get("state") == ST and "la" in (r.get("source_areas") or []))]
    held = {p for r in rows for p in r["npdes_permits"]}
    stats = {"rows": len(rows), "permits": len(held), "sso_rows": sum(1 for r in rows if r["kind"] == "sso"),
             "by_how": dict(hows),
             "legal_forms": dict(sorted(defaultdict(int, {}).items()))}
    lf = defaultdict(int)
    for r in rows:
        lf[str(r["legal_form"])] += 1
    stats["legal_forms"] = dict(sorted(lf.items()))
    return keep + rows, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    out, stats = build(dis)
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
