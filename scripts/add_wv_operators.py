"""West Virginia operator rows for data/dischargers.json: one row per operator, every West Virginia permit in one row.

Usage: pipeline/.venv/bin/python -I scripts/add_wv_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES sewage permits with state WV (603 permits on 2026-11-14). In West
     Virginia EPA's permit_name is the permittee ("FAIRMONT, CITY OF"), its permittee field mostly the plant.
  2. data/outfalls-wv.json: DEP's CSO outlets (62 permits, 519 open outlets on 61 permits): kind "cso", the open
     outlet count and DEP's receiving streams.
  3. research/wv/dischargers.json (62 CSO research rows): each research id stays an alias of the row holding its permit.
  4. research/wv/private-utilities-candidates.json (19 private sewage permits; the facility name is withheld there when
     it was a person's): a permit not already held gets a row under its recorded permittee, by the same rules.
Rules: scripts/wv_la_operator_rules.py (owner names and legal forms; never a person's name). kind "cso" for a permit
with a DEP CSO outlet, else "plant". notification_channel: the law (LAW), and the operator's own page where one was
read (OWN_CHANNELS). Idempotent: a rerun replaces the rows it wrote (state WV, source_areas ["wv"]).
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
CSO = ROOT / "data" / "outfalls-wv.json"
RESEARCH = ROOT / "research" / "wv" / "dischargers.json"
CANDIDATES = ROOT / "research" / "wv" / "private-utilities-candidates.json"
CHECKED = "2026-11-14"
ST = "WV"
LAW = ("West Virginia's Water Resources rules require whoever causes a spill or accidental discharge of pollutants, "
       "sewage included, to notify DEP's emergency spill line immediately (1-800-642-3074); the permit's standard "
       "conditions add the federal 24-hour and five-day reports (40 CFR 122.41(l)(6)). DEP publishes no list of these "
       "reports, and no duty to tell the public was found. The operator's own pages were not searched individually "
       "unless named here.")
CSO_PRACTICE = (" As a combined sewer permittee under the nine minimum controls, the operator gives public notice of its "
                "combined sewer outlets; the practice seen is an annual newspaper legal notice and a sign at each "
                "outlet. The permit's notification clause was not read.")
# the operators' own public pages read on 2026-11-09 and 2026-11-14 (research/wv expansion research)
OWN_CHANNELS = {
    "WV0023205": ("https://csbwv.gov/index.php?Itemid=68&id=62&option=com_content&view=article",
                  " Charleston Sanitary Board's combined sewer page describes wet-weather overflows and signed outlets "
                  "and advises avoiding contact during an overflow and for at least 24 hours afterward; it lists no "
                  "dated overflows."),
    "WV0023124": ("https://mub.org/cso",
                  " Morgantown Utility Board's combined sewer page lists its outlets on Deckers Creek, the Monongahela "
                  "River, Popenoe Run and Burrough Run and advises avoiding contact for 72 hours after rain; it links "
                  "a January 2025 notice and a map, and lists no dated overflows."),
    "WV0023230": ("https://www.wheelingwv.gov/departments/PublicWorks/water-pollution",
                  " Wheeling's Water Pollution Control page gives the system and a route to report problems; its "
                  "annual legal notice (2015) asked people to avoid contact for at least 24 hours after 0.10 inch of "
                  "rain; no dated overflows are published."),
}
OVERRIDES = [
    (r"^morgantown utility", "Morgantown Utility Board", "authority"),
    (r"sanitary board of the city of charleston|charleston sanitary|^the sanitary board", "Charleston Sanitary Board",
     "authority"),
    (r"^huntington sanitary|huntington, city of.*sanitary", "Huntington Sanitary Board", "authority"),
    (r"^wheeling, city of|city of wheeling", "City of Wheeling", "city"),
    (r"^west virginia[- ]american water|^wv american water|^west virginia american", "West Virginia American Water",
     "investor-owned utility"),
    (r"historical foundation", "Mineral County Historical Foundation", None),   # a private foundation; form not read
]


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    plants = [r for r in json.loads(PLANTS.read_text())["outfalls"] if r.get("state") == ST]
    cso_rows = json.loads(CSO.read_text())["outfalls"]
    open_cso = defaultdict(int)
    cso_permits = set()
    cso_waters = defaultdict(set)
    for r in cso_rows:
        cso_permits.add(r["npdes_permit"])
        if not r.get("dep_outlet_end"):
            open_cso[r["npdes_permit"]] += 1
            if r.get("receiving_water_echo"):
                cso_waters[r["npdes_permit"]].add(r["receiving_water_echo"])
    by_permit: dict[str, dict] = {}
    for r in plants:
        p = r["npdes_permit"]
        e = by_permit.setdefault(p, {"permit_name": r.get("permit_name"), "permittee": r.get("permittee"),
                                     "facility_type": r.get("facility_type"), "city": r.get("city"), "waters": set(),
                                     "rows": 0, "source": "EPA ICIS-NPDES (data/outfalls-plants-us.json)"})
        e["rows"] += 1
        if r.get("receiving_water_echo"):
            e["waters"].add(clean(r["receiving_water_echo"]))
    for r in cso_rows:
        by_permit.setdefault(r["npdes_permit"], {"permit_name": r.get("permittee"), "permittee": r.get("permittee"),
                                                 "facility_type": None, "city": r.get("city"), "waters": set(),
                                                 "rows": 0, "source": "DEP NPDES Outlets layer (data/outfalls-wv.json)"})
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
    for r in research:
        if r.get("npdes_permit"):
            alias[r["npdes_permit"]].append(r["id"])
    groups: dict[str, dict] = {}
    hows = defaultdict(int)
    for p, e in sorted(by_permit.items()):
        name, form, how = owner(e["permit_name"], e["permittee"], e["facility_type"], ST, p, OVERRIDES)
        if e.get("legal_form") and how not in ("override",) and not name.startswith("Holder of permit"):
            form = e["legal_form"]
        hows[how] += 1
        g = groups.setdefault(name, {"name": name, "legal_form": form, "permits": [], "waters": set(), "towns": set(),
                                     "aliases": [], "notes": [], "outfalls": 0, "sources": set()})
        g["permits"].append(p)
        g["waters"] |= e["waters"] | cso_waters.get(p, set())
        if e.get("city"):
            g["towns"].add(title(clean(e["city"]).split(",")[0]))
        g["aliases"] += alias.get(p, [])
        g["outfalls"] += open_cso.get(p, 0) or e["rows"]
        g["sources"].add(e["source"])
        if how not in ("override", "municipal"):
            g["notes"].append(f"{p}: EPA records the permittee as \"{title(clean(e['permit_name'] or ''))}\""
                              if not name.startswith("Holder of permit") else f"{p}: the permittee's name is withheld")
    rows = []
    for name, g in sorted(groups.items()):
        permits = sorted(g["permits"])
        cso = [p for p in permits if p in cso_permits]
        channel = LAW + (CSO_PRACTICE if cso else "")
        url = None
        for p in permits:
            if p in OWN_CHANNELS:
                url, extra = OWN_CHANNELS[p]
                channel += extra
        rid = f"wv-{slug(name)}"
        rows.append({
            "id": rid, "name": name, "short_name": name, "legal_form": g["legal_form"], "state": ST,
            "kind": "cso" if cso else "plant", "npdes_permit": permits[0], "npdes_permits": permits,
            "receiving_waters": sorted(g["waters"])[:20], "water_slugs": [],
            "outfall_count": sum(open_cso.get(p, 0) for p in cso) if cso else g["outfalls"],
            "outfalls_source": ("DEP NPDES Outlets layer, open CSO outlets (data/outfalls-wv.json)" if cso else
                                "EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json)"),
            "notification_channel": channel, "notification_feed_machine_readable": False,
            "notification_signup_url": url, "towns": sorted(g["towns"]),
            "notes": "; ".join(g["notes"][:6]) or None, "verified": "fetched", "checked": CHECKED,
            "aliases": sorted(set([rid] + g["aliases"])), "source_areas": ["wv"]})
    keep = [r for r in dis if not (r.get("state") == ST and "wv" in (r.get("source_areas") or []))]
    held = {p for r in rows for p in r["npdes_permits"]}
    stats = {"rows": len(rows), "permits": len(held), "cso_rows": sum(1 for r in rows if r["kind"] == "cso"),
             "open_cso_outlets": sum(open_cso.values()), "by_how": dict(hows),
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
