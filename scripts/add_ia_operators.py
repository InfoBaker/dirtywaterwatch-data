"""Iowa operator rows for data/dischargers.json: one row per operator, every Iowa permit of the outfall registry in
exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_ia_operators.py [--dry-run]

Inputs
  - data/outfalls-plants-us.json and data/outfalls-us.json: every Iowa permit EPA lists (826 sewage plant permits; 9
    combined sewer permits with 39 open and 45 closed outfalls in EPA's CSO inventory). permit_name is the owner as EPA
    records it; one owner's permits are one row (the City spellings joined: "ALBIA, CITY OF" and "ALBIA CITY
    OF"; a rural water association's or a county's plants in several towns are its own row).
  - research/ia/dischargers.json (10 rows: the nine CSO permittees and Waterloo): each research id stays as an alias
    of the row that holds its permit.
  - data/reference/ia-focomp-facilities.json: the 105 facilities DNR classes major municipal, matched to a permit by
    the facility's name and city as EPA spells them (92 match); a matched row says its field-office reports are read.
Rules
  - legal_form from the owner's name and EPA's facility type (docs/legal-forms.md): "City of X", "X Municipal
    Utilities" -> city; a sanitary, sanitation or sewer district -> special district; a rural water association or
    "Inc." water system -> member-owned utility; a rural water district -> special district; a county -> county; Iowa
    American Water -> investor-owned utility; a tribal government (EPA's type) -> tribal; Des Moines Metropolitan WRA
    and a wastewater treatment agency of two cities -> authority; otherwise null. Read from the name, never a person's.
  - kind: cso for a permit with an open combined sewer outfall in EPA's inventory, else plant.
  - notification_channel: 567 IAC 63.6 (a telephone report to the DNR field office within 24 hours of an unanticipated
    bypass or upset, a written report within five days; public notice only when DNR decides one is needed), where the
    reports become public (DNR's Field Office Compliance records, read here for the major municipal facilities), and
    the CSO permittees' public notice. A tribal government's permit is EPA Region 7's.
  - Idempotent: every row with state IA is rebuilt; other states' rows are left as they are and Iowa's go after them.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_sd_operators import municipal, slug, tidy, title, town  # noqa: E402

DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "ia" / "dischargers.json"
FOCOMP = ROOT / "data" / "reference" / "ia-focomp-facilities.json"
CHECKED = "2026-11-14"
FOCOMP_URL = "https://programs.iowadnr.gov/focomp/"
LAW = ("567 IAC 63.6: an unanticipated bypass or upset is reported to the Iowa DNR field office by telephone as soon as "
       "possible and within 24 hours, and in writing within five days; DNR decides whether the public must be told, and "
       "then the operator prepares the notice. The reports are public in DNR's Field Office Compliance records "
       f"({FOCOMP_URL}), one page per report; EPA's overflow tables hold no Iowa report.")
READ = " This site reads the facility's field-office bypass reports from those records."
NOT_READ = (" This site does not yet read this facility's field-office records (it reads the facilities DNR classes major "
            "municipal).")
CSO_LAW = (" As a combined sewer permittee, its permit is expected to require public notice of overflows under the "
           "federal combined sewer policy; the permit text was not read.")
EPA_LAW = ("A tribal government's permit, written by EPA Region 7: the 24-hour and five-day reports go to EPA; no public "
           "notice requirement was found.")
WATERLOO = (" The City of Waterloo posts each sanitary sewer overflow and bypass on its SSO & Bypass Public Notification "
            "page, read by this site.")
OWNERS = {
    "DES MOINES METROPOLITAN WRA": ("ia-des-moines-metropolitan-wra", "Des Moines Metropolitan Wastewater Reclamation "
                                    "Authority", "authority"),
    "BALDWIN-MONMOUTH WW TREATMENT AGENCY": ("ia-baldwin-monmouth-ww-treatment-agency",
                                             "Baldwin-Monmouth Wastewater Treatment Agency", "authority"),
    "IOWA AMERICAN WATER": ("ia-iowa-american-water", "Iowa American Water", "investor-owned utility"),
    # agencies two or more local governments set up under Iowa Code chapter 28E (their names say so; charters not read)
    "EASTERN IOWA REGIONAL UTILITY SERVICES SYSTEM": ("ia-eiruss", "Eastern Iowa Regional Utility Service Systems",
                                                      "authority"),
    "EASTERN IOWA REGIONAL UTILITY SERVICE SYSTEMS": ("ia-eiruss", "Eastern Iowa Regional Utility Service Systems",
                                                      "authority"),
    "REGIONAL UTILITY SERVICE SYSTEMS": ("ia-russ", "Regional Utility Service Systems", "authority"),
    "MAHARISHI VEDIC CITY": ("ia-maharishi-vedic-city", "City of Maharishi Vedic City", "city"),
}


def form(owner: str, ftype: str | None) -> str | None:
    n = owner.lower()
    if ftype == "Tribal Government" or re.search(r"\btribe\b|\btribal\b", n):
        return "tribal"
    if re.search(r"municipal utilit", n):
        return "city"
    if re.search(r"\b(sanitary|sanitation|sewer)\b.*\bdist", n) or re.search(r"water district", n):
        return "special district"
    if re.search(r"water (association|assn|system|systems)|regional water|utilities assoc|\binc\b", n):
        return "member-owned utility"
    if re.search(r"\bcounty\b|\bco\. board\b", n):
        return "county"
    if ftype == "Federal Facility (U.S. Government)":
        return "federal facility"
    if ftype == "State Government":
        return "state facility"
    return None


def load_epa() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in ("outfalls-plants-us.json", "outfalls-us.json"):
        for r in json.loads((ROOT / "data" / f).read_text())["outfalls"]:
            p = str(r.get("npdes_permit") or "").upper()
            if not p.startswith("IA"):
                continue
            o = out.setdefault(p, {"owner": None, "facility": None, "city": None, "type": None, "waters": [],
                                   "outfalls": 0, "open_cso": 0, "closed_cso": 0})
            o["owner"] = o["owner"] or r.get("permit_name") or r.get("permittee")
            o["facility"] = o["facility"] or r.get("permittee")
            o["city"] = o["city"] or r.get("city")
            o["type"] = o["type"] or r.get("facility_type")
            w = (r.get("receiving_water_echo") or "").strip()
            if w and w not in o["waters"]:
                o["waters"].append(w)
            if f == "outfalls-us.json":
                if str(r.get("outfall_status") or "").upper().startswith("CLS"):
                    o["closed_cso"] += 1
                else:
                    o["open_cso"] += 1
                    o["outfalls"] += 1
            else:
                o["outfalls"] += 1
    return out


def focomp_permits(epa: dict) -> dict[str, str]:
    """permit -> FOCOMP facility name, by the name and city EPA and DNR both give."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    by = defaultdict(list)
    for p, o in epa.items():
        by[norm(o["facility"])].append(p)
    out = {}
    for f in json.loads(FOCOMP.read_text())["facilities"]:
        m = [p for p in by.get(norm(f["name"]), []) if (epa[p]["city"] or "").upper() == f["city"].upper()] \
            or by.get(norm(f["name"]), [])
        if len(m) == 1:
            out[m[0]] = f["name"]
    return out


def build(epa: dict, research: list[dict], fo: dict[str, str]) -> tuple[list[dict], dict]:
    alias = {r["npdes_permit"]: r["id"] for r in research if r.get("npdes_permit")}
    groups: dict[str, list[str]] = defaultdict(list)
    names: dict[str, tuple[str, str | None]] = {}
    for p, o in sorted(epa.items()):
        owner = o["owner"] or o["facility"] or p
        if owner.upper() in OWNERS:
            rid, name, lf = OWNERS[owner.upper()]
        else:
            mm = municipal(re.sub(r"(?i)\s+(?:STP|WWTP|WWTF|lagoons?)$", "", owner.strip()))
            if mm:
                name, lf = tidy(f"{mm[0]} of {mm[1]}"), mm[0].lower()
                key = "muni-" + slug(tidy(mm[1]))
            else:
                name = tidy(title(re.sub(r"\s*\(.*\)\s*$", "", owner)))
                lf = form(owner, o["type"])
                key = slug(re.sub(r"\s*\(.*\)\s*$", "", owner)) or slug(p)
            rid = f"ia-{key.removeprefix('muni-')}"
        groups[rid].append(p)
        names.setdefault(rid, (name, lf))
    rows = []
    for rid, permits in sorted(groups.items()):
        name, lf = names[rid]
        e = [epa[p] for p in permits]
        kind = "cso" if any(x["open_cso"] for x in e) else "plant"
        tribal = all(x["type"] == "Tribal Government" for x in e)
        read = [p for p in permits if p in fo]
        ch = EPA_LAW if tribal else LAW + (READ if read else NOT_READ)
        if kind == "cso" or any(x["closed_cso"] for x in e):
            ch += CSO_LAW
        if "IA0042650" in permits:
            ch += WATERLOO
        aliases = [rid] + [alias[p] for p in permits if p in alias and alias[p] != rid]
        note = (f"EPA ECHO ICIS-NPDES: {'; '.join(f'{p} {epa[p]['facility']}' for p in permits)}. Owner as EPA records "
                f"it: {'; '.join(sorted({str(x['owner']) for x in e}))}; facility type "
                f"{'; '.join(sorted({str(x['type']) for x in e}))}."
                + (f" DNR field-office facility: {'; '.join(fo[p] for p in read)}." if read else "")
                + (" Legal form read from the name." if lf and lf not in ("city",) else ""))
        n_out = sum(x["outfalls"] for x in e)
        row = {"id": rid, "name": name, "state": "IA", "kind": kind, "npdes_permit": permits[0],
               "npdes_permits": permits, "receiving_waters": list(dict.fromkeys(w for x in e for w in x["waters"])),
               "water_slugs": [], "outfall_count": n_out or None,
               "outfalls_source": ("EPA ECHO ICIS-NPDES discharge points and the national CSO inventory "
                                   f"(data/outfalls-plants-us.json, data/outfalls-us.json: {n_out} open rows; closed "
                                   f"combined sewer outfalls are not counted)") if n_out else None,
               "notification_channel": ch, "notification_feed_machine_readable": bool(read) or "IA0042650" in permits,
               "notification_signup_url": None, "towns": sorted({t for x in e if (t := town(x["city"]))}),
               "notes": note, "verified": "fetched", "checked": CHECKED, "aliases": aliases,
               "source_areas": ["ia", "federal"]}
        if lf:
            row["legal_form"] = lf
        rows.append(row)
    stats = {"rows": len(rows), "permits": sum(len(r["npdes_permits"]) for r in rows),
             "cso_rows": sum(1 for r in rows if r["kind"] == "cso"),
             "focomp_read_rows": sum(1 for r in rows if READ in r["notification_channel"]),
             "by_form": dict(Counter(r.get("legal_form") for r in rows))}
    return rows, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    epa = load_epa()
    new, stats = build(epa, json.loads(RESEARCH.read_text()), focomp_permits(epa))
    others = [r for r in dis if r.get("state") != "IA"]
    taken = {p for r in others for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in taken)
    if clash:
        raise SystemExit(f"permits already held by another state's row: {clash}")
    ids = Counter(r["id"] for r in others + new)
    if [i for i, n in ids.items() if n > 1]:
        raise SystemExit(f"duplicate ids: {[i for i, n in ids.items() if n > 1]}")
    if set(epa) - {p for r in new for p in r["npdes_permits"]}:
        raise SystemExit("permits without a row")
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(others + new, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
