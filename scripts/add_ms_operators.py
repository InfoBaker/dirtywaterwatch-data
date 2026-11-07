"""Mississippi operator rows for data/dischargers.json: one row per operator, every permit in exactly one row.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events file, for the permits only EPA's
overflow tables name):
    pipeline/.venv/bin/python -I scripts/add_ms_operators.py [--dry-run]

Inputs
  1. research/ms/dischargers.json (9 rows): the largest filers in EPA's overflow tables and the coastal authorities. Each
     keeps its research id; its permits are those the row gives plus every other permit the owner key (owner()) joins.
  2. data/outfalls-plants-us.json: EPA ICIS-NPDES's Mississippi treatment-plant permits (362), grouped by owner. The
     owner is read from EPA's permit name: a public authority, district, board of supervisors, school district, tribe
     or state body named before the facility ('JACKSON COUNTY UTILITY AUTHORITY, POTW 7C'; the abbreviations HCUA,
     DCRUA, PRCUA, SCUA and JCUA spelt out from EPA's own longer names), 'X, CITY OF' and 'X, TOWN OF', else the place
     before 'POTW' or 'LAGOON' ('LAUREL POTW, NUMBER 2' is Laurel's). A municipality named only by its place is filed as
     "the municipal sewer system of X", legal form city (a city, town or village: the class was not read).
  3. Permits EPA's overflow tables name (kept or dropped reports) that no plant row holds (one on 2026-11-07: a school
     district's lift station, named from the collection system EPA's table gives).
  4. research/ms/private-utilities-candidates.json (36 private sewage permits): grouped by permittee as EPA ICIS-NPDES
     records it, legal_form from PRIVATE below (docs/legal-forms.md), never an individual's name: a permit whose
     permittee the candidates file removed is filed under its facility (or its permit alone when the facility's name
     was removed too), legal form "facility (permittee not named)". Permits EPA types private whose names read as
     public bodies (public_by_name, and JCUA's POTW 4D, Hinds Community College) are public rows.
Rules
  - notification_channel says what Mississippi requires (no statewide public notice; the 24-hour report to MDEQ and,
    from 2025-12-21, the 5-day report through NeT-SewerOverflow) and where the reports become public (EPA's overflow
    tables); for the City of Jackson also the consent decree's overflow response plan (news releases and signs) and
    JXN Water's quarterly reports. notification_signup_url is null everywhere: no Mississippi operator offers an
    overflow alert sign-up that was found.
  - Idempotent: a rerun replaces the rows it wrote (source_areas ["ms"]) and leaves every other row as it is.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKED = "2026-11-07"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "ms" / "dischargers.json"
CANDIDATES = ROOT / "research" / "ms" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
DROPPED = ROOT / "data" / "build" / "echo-sewer-overflow-dropped.json"

BASE_LAW = ("No Mississippi statute or rule requiring public notice of a sewer overflow or a bypass was found: the "
            "permit conditions require a report to MDEQ within 24 hours and, from 21 December 2025, an electronic "
            "report within 5 days through EPA's NeT-SewerOverflow, so the reports become public in EPA's overflow "
            "tables (ECHO), a median of 4 days after the overflow began. MDEQ posts no list of its own.")
JACKSON_LAW = (" The City of Jackson's sewer system is run by JXN Water under a 2023 federal court order: the 2013 consent "
               "decree's overflow response plan calls for news releases and temporary signs for significant overflows "
               "(as reported in the press; the plan was not read), and JXN Water files quarterly status reports with "
               "the court.")
PRIVATE_NOTE = " The permit conditions bind a private permittee as they bind a public one."

# the abbreviations EPA's Mississippi permit names use for the regional authorities, spelt out from EPA's longer names
ABBREV = [(r"\bHARRISON CO(UNTY)? UTIL(ITY)? AUTH(ORITY)?\b", "HARRISON COUNTY UTILITY AUTHORITY"),
          (r"\bHANCOCK CO(UNTY)? UTIL(ITY)? AUTH(ORITY)?\b", "HANCOCK COUNTY UTILITY AUTHORITY"),
          (r"\bDCRUA\b|\bDESOTO CO(UNTY)? REGIONAL UTILITY( AUTH(ORITY)?)?\b", "DESOTO COUNTY REGIONAL UTILITY AUTHORITY"),
          (r"\bPRCUA\b|\bPEARL RIVER CO(UNTY)? UTILITY AUTHORITY\b", "PEARL RIVER COUNTY UTILITY AUTHORITY"),
          (r"\bSCUA\b", "STONE COUNTY UTILITY AUTHORITY"),
          (r"\bJCUA\b(?: A\b)?", "JACKSON COUNTY UTILITY AUTHORITY"),
          (r"\bJACKSON COUNTY UTILITY AUTHORITY,? JACKSON COUNTY UTILITY AUTHORITY\b", "JACKSON COUNTY UTILITY AUTHORITY"),
          (r"\bCOAHOMA CO UTIL DISTRICT\b", "COAHOMA COUNTY UTILITY DISTRICT"),
          (r"\bMS BAND OF CHOCTAW\b", "MISSISSIPPI BAND OF CHOCTAW"),
          (r"\bMISS DEPT OF W F & PARKS\b", "MISSISSIPPI DEPARTMENT OF WILDLIFE, FISHERIES AND PARKS"),
          (r"\bSCHOOL DIST\b", "SCHOOL DISTRICT"), (r"\bSEWER DIST\b", "SEWER DISTRICT"),
          (r"\b(\w+) CO\b(?= (BOARD|UTILITY|WATER|SCHOOL|INDUSTRIAL|REGIONAL))", r"\1 COUNTY"),
          (r"\bWATER ASSN\b", "WATER ASSOCIATION"), (r"\bEUP0RA\b", "EUPORA")]
# a public body named before the facility: the owner is the name up to and including these words
BODY = re.compile(r"^(.*?\b(?:REGIONAL UTILITY AUTHORITY|UTILITY AUTHORITY|WASTEWATER AUTHORITY|UTILITY DISTRICT"
                  r"(?: NUMBER \d+)?|WATER (?:&|AND) SEWER DIST(?:RICT)?|SEWER DISTRICT|BOARD OF SUPERVISORS|"
                  r"SCHOOL DISTRICT|PORT COMMISSION|INDUSTRIAL DEVELOPMENT AUTHORITY|MUNICIPAL UTILITIES|"
                  r"LIGHT & WATER DEPT|BAND OF CHOCTAW INDIANS|DEPARTMENT OF WILDLIFE, FISHERIES AND PARKS))\b")
CITY_OF = re.compile(r"^([A-Z .'-]+?),\s*(CITY|TOWN) OF\b")
PLACE = re.compile(r"^([A-Z .'-]+?)\s+(?:POTW|LAGOON|SOUTH LAGOON|NORTH LAGOON)\b")
# names that read wrong by the rules (read from EPA's permit names and facility types, 2026-11-07)
HAND = {
    "MS0043630": ("TOWN OF POPE", "Town of Pope (Pope Sewer District)", "town"),
    "MS0055735": ("MERIDIAN", None, None),                          # 'EAST MERIDIAN POTW' is Meridian's
    "MS0061221": ("HARRISON COUNTY UTILITY AUTHORITY", None, None),
    "MS0021873": ("UNIVERSITY OF MISSISSIPPI", "University of Mississippi", "state facility"),
    "MS0056685": ("HINDS COMMUNITY COLLEGE", "Hinds Community College", "state facility"),
    "MS0026000": ("SOUTHWEST MISSISSIPPI COMMUNITY COLLEGE", "Southwest Mississippi Community College", "state facility"),
    "MS0027855": ("ALCORN STATE UNIVERSITY", "Alcorn State University", "state facility"),
    "MS0031534": ("ELLISVILLE STATE SCHOOL", "Ellisville State School", "state facility"),
    "MS0029009": ("MISSISSIPPI STATE PENITENTIARY", "Mississippi State Penitentiary", "state facility"),
    "MS0045331": ("MISSISSIPPI STATE PENITENTIARY", "Mississippi State Penitentiary", "state facility"),
    "MS0059838": ("MISSISSIPPI ARMY NATIONAL GUARD", "Mississippi Army National Guard (Camp Shelby)", "state facility"),
    "MSR108299": ("MISSISSIPPI ARMY NATIONAL GUARD", "Mississippi Army National Guard (Camp Shelby)", "state facility"),
    "MS0058122": ("PHOENIX NETTLETON MS I INDUSTRIAL INVESTORS LLC", "Phoenix Nettleton MS I Industrial Investors LLC "
                  "(Presto Distribution Center)", "business or industrial"),
    "MS0060046": ("MARSHALL UTILITY SERVICES LLC", "Marshall Utility Services LLC", "investor-owned utility"),
    "MS0042528": ("HOMESTEAD WATER ASSOCIATION", "Homestead Water Association (Homestead Community Club Inc)",
                  "member-owned utility"),
    "MSR104282": ("THE BRAMBLES", "The Brambles (permit MSR104282)", None),
    "MS0034487": ("LINCOLN COUNTY SCHOOL DISTRICT", "Lincoln County School District (Loyd Star School)",
                  "special district"),
    "MSU008001": ("JACKSON COUNTY UTILITY AUTHORITY", None, None),  # EPA types JCUA's POTW 4D private
}
# private permittees as EPA records them -> legal form, note
PRIVATE = {
    "SEBASTOPOL WATER ASSOCIATION": ("member-owned utility", "A rural water association."),
    "ADAMS COUNTY WATER ASSOCIATION": ("member-owned utility", "A rural water association with several subdivision plants."),
    "TUNICA INDUSTRIAL PARK": ("business or industrial", "The industrial park's own plant; its owner was not read."),
    "RAINBOW LAKES PROPERTY OWNERS ASSOC": ("homeowners' association", "A property owners' association."),
    "RESERVOIR EAST SUBDIVISION": ("homeowners' association", "A subdivision's plant; the owner was not read."),
    "MIZE POTW": ("business or industrial", "EPA types the plant privately owned; the owner was not read."),
    "CHURCH OF GOD THE BIBLEWAY INC": ("institution", "A church's campground."),
    "CEDAR CREEK LLC": ("business or industrial", ""),
    "GREAT RIVER UTILITY OPERATING CO LLC": ("investor-owned utility", "A sewer company with subdivision plants."),
    "FRENCH CAMP POTW": ("institution", "EPA types the plant privately owned; the owner was not read."),
    "COCK OF THE WALK HWY 49 LLC": ("business or industrial", "A restaurant's plant."),
    "KATSIB PROPERTIES LLC": ("mobile-home park", "The owner of a mobile-home park."),
    "WESTSIDE CHURCH OF CHRIST": ("institution", "A church."),
    "ANDERSON GROVE LLC": ("mobile-home park", "The owner of a mobile-home park."),
    "PASCAGOULA WATER TREATMENT PLANT, BAYOU CASOTTE": ("business or industrial",
                                                        "EPA types the plant privately owned; the owner was not read."),
    "SOUTHWEST DEVELOPMENT CORP": ("business or industrial", "A developer."),
    "CAESAR OAKS LLC": ("business or industrial", ""),
    "EAST OXFORD UTILITIES LLC": ("investor-owned utility", "A sewer company."),
    "OUR LADY OF HOPE INC": ("institution", ""),
    "AUBURN APARTMENTS LLC": ("business or industrial", "An apartment complex's owner."),
    "BEAU RIVAGE RESORTS LLC": ("private club", "A resort's golf course."),
}
PRIVATE_ALIASES = {"GREAT RIVER UTILITY OPERATING COMPANY LLC": "GREAT RIVER UTILITY OPERATING CO LLC",
                   "ADAMS COUNTY WATER ASSN INC": "ADAMS COUNTY WATER ASSOCIATION"}
ABBR_WORDS = {"potw", "wwtp", "wwtf", "wrrf", "hcr", "ii", "llc", "jxn", "ms", "us", "s20", "ls"}


def norm(name: str | None) -> str:
    s = " ".join((name or "").upper().replace("’", "'").split())
    for pat, rep in ABBREV:
        s = re.sub(pat, rep, s)
    return s


def smart_title(s: str) -> str:
    out = []
    for w in (s or "").split():
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if bare in ABBR_WORDS:
            out.append(w.upper())
        elif bare in ("of", "and", "the") and out:
            out.append(bare)
        else:
            out.append(re.sub(r"(?<=\w)'S\b", "'s", w.title()) if w.isupper() or w.islower() else w)
    s = " ".join(out)
    return re.sub(r"\bDesoto\b", "DeSoto", re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), s))


def form(name: str) -> str | None:
    n = name.lower()
    if "band of choctaw" in n:
        return "tribal"
    if re.search(r"\b(utility|wastewater|regional utility) authority\b|\bport commission\b|"
                 r"industrial development authority", n):
        return "authority"
    if re.search(r"\b(utility|sewer|water (&|and) sewer) district\b|\bschool district\b", n):
        return "special district"
    if re.search(r"\bboard of supervisors\b", n):
        return "county"
    if re.search(r"department of wildlife|state park|state university|community college|penitentiary", n):
        return "state facility"
    if re.search(r"\bwater (and sewer |& sewer )?association\b|\bwastewater association\b", n):
        return "member-owned utility"
    if re.search(r"\b(llc|inc|corp|company)\b", n):
        return "business or industrial"
    return None


def owner(permit: str, permit_name: str | None, facility_type: str | None) -> tuple[str, str, str | None, str]:
    """(key, display name, legal form, basis) of a permit's owner from EPA's permit name. A place before 'POTW' is a
    municipality only when it is a city EPA gives for some Mississippi plant (CITIES) ('CLEARY HEIGHTS
    POTW' in Florence is a subdivision's plant: filed under its own name, owner not read)."""
    if permit in HAND:
        k, disp, lf = HAND[permit]
        if disp is None:
            return owner("", k, facility_type)
        return k, disp, lf, "read by hand from EPA's permit name and facility type"
    s = norm(permit_name)
    m = CITY_OF.match(s)
    if m:
        place = m.group(1).strip()
        kind = m.group(2).title()
        return place, f"{kind} of {smart_title(place)}", kind.lower() if kind == "Town" else "city", "EPA's permit name"
    m = BODY.match(s)
    if m:
        body = m.group(1).strip(" ,")
        if body.endswith(("MUNICIPAL UTILITIES", "LIGHT & WATER DEPT")):
            place = re.sub(r"\s+(MUNICIPAL UTILITIES|LIGHT & WATER DEPT)$", "", body)
            return place, f"City of {smart_title(place)} ({smart_title(body)})", "city", "EPA's permit name"
        return body, smart_title(body), form(body), "EPA's permit name"
    if facility_type in ("Municipal or Water District", "Municipality", "POTW", None):
        m = PLACE.match(s)
        if m and not re.search(r"\b(INDUSTRIAL|SUBDIVISION|LLC|INC|ASSOCIATION)\b", s):
            place = m.group(1).strip()
            if CITIES and compact(place) not in CITIES:
                return s, smart_title(s), None, ("EPA's permit name; EPA types the plant municipal or a water "
                                                 "district, but the name is not its town's: the owner was not read")
            return place, f"{smart_title(place)} municipal sewer system", "city", (
                "EPA's permit name gives the place, EPA types the plant municipal; Mississippi's class of the "
                "municipality (city, town or village) was not read")
    body = re.sub(r",.*$", "", s) if form(re.sub(r",.*$", "", s)) else s
    return body, smart_title(body), form(body), "EPA's permit name"


def compact(s: str | None) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


# the cities EPA ICIS-NPDES gives for Mississippi's plants: a place before 'POTW' that is one of them is a municipality
CITIES = {compact(r.get("city")) for r in json.loads(PLANTS.read_text())["outfalls"] if r.get("state") == "MS"} - {""}


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def notification(jackson: bool = False, private: bool = False) -> str:
    return BASE_LAW + (JACKSON_LAW if jackson else "") + (PRIVATE_NOTE if private else "")


def row(rid, name, short, kind, permits, towns, waters, notes, legal_form, outfall_count=None, outfalls_source=None,
        verified="inferred", jackson=False, private=False):
    return {"id": rid, "name": name, "short_name": short or name, "legal_form": legal_form, "state": "MS",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfall_count,
            "outfalls_source": outfalls_source, "notification_channel": notification(jackson, private),
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": CHECKED, "aliases": [rid],
            "source_areas": ["ms"]}


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "MS" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def sobe_permits() -> dict[str, str | None]:
    """MS permit -> the collection system EPA's overflow tables name, over kept and dropped reports."""
    out: dict[str, str | None] = {}
    if EVENTS.exists():
        for r in json.loads(EVENTS.read_text()).get("records", []):
            p = r.get("npdes_permit") or ""
            if p.startswith("MS"):
                out.setdefault(p, (r.get("raw") or {}).get("collection_system_name"))
    if DROPPED.exists():
        for r in json.loads(DROPPED.read_text()).get("dropped", []):
            if str(r.get("permit") or "").startswith("MS"):
                out.setdefault(r["permit"], None)
    return out


def build(dis: list[dict]) -> tuple[list[dict], Counter]:
    keep = [d for d in dis if not (d.get("state") == "MS" and "ms" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    pl = plants()
    cand = json.loads(CANDIDATES.read_text())
    public_by_name = {c["npdes_permit"] for c in cand["public_by_name"]}
    private = {c["npdes_permit"]: c for c in cand["candidates"] if c["npdes_permit"] not in HAND}
    counts = Counter()
    groups: dict[str, dict] = {}

    def group(k, disp, lf, basis):
        return groups.setdefault(k, {"name": disp, "legal_form": lf, "basis": basis, "permits": [], "rows": [],
                                     "research": None, "sobe": [], "cands": []})

    # every public permit: the plants, then the overflow tables' permits no plant row holds
    for p, rows in sorted(pl.items()):
        if p in held or p in private:
            continue
        k, disp, lf, basis = owner(p, rows[0].get("permit_name") or rows[0].get("permittee"), rows[0].get("facility_type"))
        g = group(k, disp, lf, basis)
        g["permits"].append(p)
        g["rows"] += rows
    for p, sysname in sorted(sobe_permits().items()):
        if p in held or p in pl or p in private:
            continue
        k, disp, lf, basis = owner(p, sysname, None)
        g = group(k, disp, lf, basis)
        g["permits"].append(p)
        g["sobe"].append((p, sysname))
        counts["permits only in EPA's overflow tables"] += 1
    for c in cand["public_by_name"]:                 # typed private by EPA, named as public bodies
        if c["npdes_permit"] in held or c["npdes_permit"] in pl:
            continue
        k, disp, lf, basis = owner(c["npdes_permit"], c["permittee_as_recorded"], None)
        g = group(k, disp, lf, basis + " (EPA types the facility privately owned; the permittee is a public body)")
        g["permits"].append(c["npdes_permit"])
        g["cands"].append(c)
        counts["public bodies EPA types private"] += 1
    for c in cand["candidates"]:
        if c["npdes_permit"] in HAND and c["npdes_permit"] not in pl:
            k, disp, lf, basis = owner(c["npdes_permit"], c["facility"], None)
            group(k, disp, lf, basis)["permits"].append(c["npdes_permit"])

    # research rows take the group of their owner (and keep their id and receiving waters)
    research = json.loads(RESEARCH.read_text())
    new: list[dict] = []
    for r in research:
        perms = [p.strip() for p in (r.get("npdes_permit") or "").split(";") if p.strip()]
        keys = {owner(p, pl[p][0].get("permit_name"), pl[p][0].get("facility_type"))[0]
                for p in perms if p in pl}
        if r["id"] == "ms-harrison-county-wwsd":
            keys = {"HARRISON COUNTY UTILITY AUTHORITY"}
        if len(keys) != 1:
            raise SystemExit(f"{r['id']}: its permits read as {keys or 'no owner'}")
        k = keys.pop()
        groups[k]["research"] = r
    reserved = {r["id"] for r in research}
    for k, g in sorted(groups.items(), key=lambda kv: kv[0]):
        perms = list(dict.fromkeys(g["permits"]))
        if not perms or set(perms) <= held:
            continue
        r = g["research"]
        rows = g["rows"]
        jackson = k == "JACKSON"
        name, lf = g["name"], g["legal_form"]
        if jackson:
            name, lf = "City of Jackson (sewer system run by JXN Water)", "city"
        rid = r["id"] if r else f"ms-{slug(k)}"
        if rid in ids or (not r and rid in reserved):
            rid = f"{rid}-{perms[0].lower()}"
        facs = ", ".join(sorted(
            {f"{smart_title(x.get('permit_name') or x.get('permittee') or '')} ({x['npdes_permit']})" for x in rows}
            | {f"{smart_title(n or '')} ({p}, from EPA's overflow tables)" for p, n in g["sobe"]}
            | {f"{smart_title(c['facility'])} ({c['npdes_permit']})" for c in g["cands"]
               if c["facility"] != "[name removed]"}))
        waters = list(dict.fromkeys([*(r.get("receiving_waters") or [] if r else []),
                                     *[x["receiving_water_echo"] for x in rows if x.get("receiving_water_echo")]]))[:8]
        towns = list(dict.fromkeys([*(r.get("towns") or [] if r else []),
                                    *sorted({smart_title(x["city"]) for x in rows + g["cands"] if x.get("city")})]))
        notes = f"Owner from {g['basis']}. Plants: {facs}."
        if r:
            notes += " " + (r.get("notes") or "")
        kind = "sso" if r else ("sso" if g["sobe"] else "plant")
        nr = row(rid, name, re.sub(r" \(.*\)$", "", name), kind, perms, towns, waters, notes.strip(), lf,
                 outfall_count=len(rows) or None,
                 outfalls_source=(f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                  if rows else None),
                 verified=(r.get("verified") if r else "fetched"), jackson=jackson)
        if r and r["id"] not in nr["aliases"]:
            nr["aliases"].append(r["id"])
        new.append(nr)
        ids.add(rid)
        held.update(perms)
        counts["research rows" if r else "public rows"] += 1

    # private sewage permits, grouped by permittee
    groups4: dict[str, list[dict]] = defaultdict(list)
    for p, c in sorted(private.items()):
        if p in held:
            continue
        if p in public_by_name:
            continue
        who = c["permittee_as_recorded"]
        who = re.sub(r",.*$", "", who) if re.sub(r",.*$", "", who) in PRIVATE or \
            PRIVATE_ALIASES.get(re.sub(r",.*$", "", who)) else who
        who = PRIVATE_ALIASES.get(who, who)
        groups4[who if who != "[name removed]" else f"[name removed] {p}"].append(c)
    for who, cs in groups4.items():
        perms = [c["npdes_permit"] for c in cs]
        facs = ", ".join(f"{smart_title(c['facility'])} ({c['npdes_permit']}, {smart_title(c['city'])})"
                         if c["facility"] != "[name removed]" else f"permit {c['npdes_permit']}" for c in cs)
        if who.startswith("[name removed]"):
            c = cs[0]
            name = (f"{smart_title(c['facility'])} (permit {c['npdes_permit']})" if c["facility"] != "[name removed]"
                    else f"Sewage plant, permit {c['npdes_permit']}")
            lf, note, waters = "facility (permittee not named)", ("EPA's permittee name reads as an individual's: not "
                                                                  "named here; the row names the facility."), []
            rid = f"ms-{c['npdes_permit'].lower()}"
        else:
            lf, note = PRIVATE.get(who, (None, "The permittee as EPA records it; its legal form was not read."))
            name = smart_title(who)
            rid = f"ms-{slug(who)}"
            waters = list(dict.fromkeys(w for c in cs for w in c.get("receiving_waters_echo") or []))[:8]
        if rid in ids:
            rid = f"{rid}-{perms[0].lower()}"
        nr = row(rid, name, name, "plant", perms, sorted({smart_title(c["city"]) for c in cs if c.get("city")}), waters,
                 (note + f" Plants: {facs}. Privately owned by EPA's facility type; permittee as EPA ICIS-NPDES records "
                  "it (research/ms/private-utilities-candidates.json); MDEQ's permit documents were not read.").strip(),
                 lf, verified="inferred", private=True)
        new.append(nr)
        ids.add(rid)
        held.update(perms)
        counts["private rows"] += 1
    # the permits EPA types private whose names read as public bodies are in the plant groups above; any left over
    left = [p for p in public_by_name if p not in held]
    if left:
        raise SystemExit(f"public-by-name permits with no row: {left}")
    for r in new:
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
    return keep + new, counts


def main(argv) -> int:
    dis = json.loads(DIS.read_text())
    out, counts = build(dis)
    new = [d for d in out if d.get("state") == "MS" and "ms" in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1), f"\nMississippi rows {len(new)}, permits "
          f"{sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
