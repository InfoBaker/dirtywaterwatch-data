"""Illinois operator rows for data/dischargers.json: one row per operator, every permit in exactly one row.

Usage (after pipeline/ingest/echo_sewer_overflow_events.py has written its events file):
    pipeline/.venv/bin/python -I scripts/add_il_operators.py [--dry-run]

Inputs
  1. research/il/dischargers.json (132 rows): EPA's 120 Illinois CSO permits and the 12 largest SSO reporters in EPA's
     overflow tables. Each keeps its research id (the EPA overflow module names it as discharger_id), its name the
     permittee as EPA ICIS-NPDES records it (permit_name in data/outfalls-plants-us.json), else the research name,
     turned from EPA's "OREGON STP, CITY OF" into "City of Oregon (Oregon STP)". The 43 permits EPA lists as Great Lakes
     Basin CSO permits (the research notes say so: Chicago, MWRD's four plants, Golf, Phoenix and the suburban
     general-permit coverages ILM5800xx) carry the 4-hour notice of 40 CFR 122.38 in notification_channel.
  2. data/outfalls-plants-us.json: EPA's Illinois treatment-plant permits (864), grouped by permit_name; a permit a
     row already holds is skipped; a plant add_federal_operators.private_reason flags waits for step 4 unless its
     owner reads as a public body.
  3. The Illinois permits EPA's overflow tables name (data/build/events/echo-sewer-overflow.json) that no row holds:
     the general-permit coverages for small plants (ILG58...) and others, named from the collection system EPA's
     table gives.
  4. research/il/private-utilities-candidates.json (40 private sewage permits): grouped by permittee as EPA ICIS-NPDES
     records it (Illinois EPA's permit documents were not read), legal_form from the controlled list (PRIVATE_FORMS
     below, by permittee), never an individual's name: the two permits whose permittee the candidates file removed
     are filed under the facility, legal_form "facility (permittee not named)". Two permits EPA types private but whose
     names read as public bodies (public_by_name: Forest View's CSO permit IL0020800 and Lake Arispie Sanitary
     District) are public rows.
Rules
  - Owner key (key()): lower case, punctuation dropped, "city of" and works words dropped; a village and a city of
    one name are one key only when EPA writes them so.
  - legal_form (form()) from the name, on the controlled list (docs/legal-forms.md); null when the name does not say.
  - A permit_name that carries a person's name before the body is cut to the body (add_mi_operators.clean_name).
  - notification_channel says what Illinois law and the permits require (no public notice of SSOs or bypasses; CSO
    permits' public notification; the Great Lakes 4-hour notice) and where the reports become public (EPA's overflow
    tables; MWRD's map and alerts in Cook County). notification_signup_url: MWRD's alert sign-up for the Great Lakes
    permittees, else null.
  - Idempotent: a rerun replaces the rows it wrote (source_areas ["il"]) and leaves every other row as it is; new rows
    go after the last row of the file.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pipeline"))
from add_federal_operators import private_reason, title  # noqa: E402
from add_mi_operators import clean_name  # noqa: E402

CHECKED = "2026-11-04"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "il" / "dischargers.json"
CANDIDATES = ROOT / "research" / "il" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
EVENTS = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
SIGNUP = "https://www.smart911.com/smart911/ref/reg.action?pa=mwrdcso"
MWRD_PAGE = ("https://mwrd.org/community-action/you-can-help-prevent-flooding-and-protect-water-quality/"
             "combined-sewer-overflow-notification")
BASE_LAW = ("No Illinois statute or rule requires public notice of a sanitary sewer overflow or a bypass: the permit's "
            "standard conditions require a report to Illinois EPA's regional office within 24 hours and a written report "
            "within 5 days, filed through EPA's NeT-SewerOverflow, so the reports become public in EPA's overflow tables "
            "(ECHO) days to weeks later.")
CSO_LAW = (" As a combined sewer permittee it must notify the public of overflows under its permit's public notification "
           "condition (Nine Minimum Controls, no. 8); the permit text and the operator's own pages were not read.")
GL_LAW = (" As a Great Lakes Basin CSO permittee it must notify the public electronically within 4 hours of becoming aware "
          "of a combined sewer overflow, post signs at outfalls and public access areas, tell the local health "
          "department within 4 hours, and give a supplemental notice within 7 days (40 CFR 122.38). In Cook County MWRD "
          "sends CSO notices by e-mail and text (sign-up through Smart911) and shows possible CSO activity on a daily map "
          f"({MWRD_PAGE}); the permittee's own plan was not read.")
PRIVATE_FORMS = {   # permittee as EPA records it -> legal form, note
    "ILLINOIS AMERICAN WATER COMPANY": ("investor-owned utility", "Illinois American Water, a regulated water and sewer company."),
    "AQUA ILLINOIS, INC.": ("investor-owned utility", "Aqua Illinois, a regulated water and sewer company."),
    "AQUA AMERICA - ELLWOOD GREENS UTILITY CORP": ("investor-owned utility", "A utility company of the Aqua group."),
    "PRAIRIE PATH WATER COMPANY": ("investor-owned utility", "A water and sewer company."),
    "OAK TERRACE SANITARY SYSTEM INC": ("investor-owned utility", "A sewer company serving a subdivision."),
    "LILAC BASIN CORP - UNION HILL": ("business or industrial", "A company that holds the plant's permit."),
    "GLENDENNING CAPITAL INC": ("business or industrial", "A company that holds the townhomes' plant permit."),
    "LAKE BARRINGTON HOMEOWNERS ASSOCIATION": ("homeowners' association", ""),
    "COUNTRY VIEW ESTATES HOMEOWNERS ASSOCIATION": ("homeowners' association", ""),
    "SHERWOOD HOMEOWNERS ASSOCIATION": ("homeowners' association", ""),
    "CASTLE RIDGE HOMEOWNERS ASSOCIATION": ("homeowners' association", ""),
    "WEXFORD HILLS SUBDIVISION HOMEOWNERS ASSOCIATION": ("homeowners' association", ""),
    "METRO-EAST AIRPARK PROPERTY OWNERS ASSOCIATION": ("homeowners' association", "A property owners' association."),
    "LAKE IROQUOIS ASSOCIATION": ("homeowners' association", "A lake community's association."),
    "RANCH OAKS SERVICE ASSOCIATION": ("homeowners' association", "A subdivision's service association."),
    "THE WOODHAVEN ASSOCIATION": ("campground or resort", "The association of a campground community."),
}
PRIVATE_ALIASES = {"ILLINOIS AMERICAN WATER": "ILLINOIS AMERICAN WATER COMPANY",
                   "ILLINOIS-AMERICAN WATER COMPANY": "ILLINOIS AMERICAN WATER COMPANY",
                   "ILLINOIS AMERICAN WATER - WASHINGTON ESTATES": "ILLINOIS AMERICAN WATER COMPANY",
                   "AQUA ILLINOIS INC": "AQUA ILLINOIS, INC."}
# CSO permits whose EPA name is a description, not a permittee ("COMBINED SEWER OVERFLOWS", "DIXMOOR CSOS"): the
# permittee the permit's town and EPA's Great Lakes list give, with its legal form
CSO_NAMES = {"IL0039551": ("Village of Lemont", "town"), "IL0045039": ("Village of Western Springs", "town"),
             "IL0052400": ("Village of Mount Prospect", "town"), "IL0066818": ("Village of Hinsdale", "town"),
             "ILM580011": ("Village of Dixmoor", "town"), "ILM580017": ("Village of Dolton", "town"),
             "ILM580029": ("Village of Franklin Park", "town"), "ILM580030": ("Village of North Riverside", "town"),
             "ILM580025": ("City of Calumet City", "city"), "IL0022471": ("Glenbard Wastewater Authority", "authority"),
             "IL0024384": ("City of Monmouth", "city")}
# permits EPA's records name nowhere but its collection-system table (read 2026-11-04 from the overflow tables' ZIP)
HAND = {"IL0022152": ("Oaklane Acres Subdivision STP", None,
                      "EPA's collection-system table names the system Oaklane Acres Subdivision STP and types it "
                      "privately owned; the permittee was not read.")}
# names of Illinois American Water's and Aqua Illinois's plants outside the candidates file: joined to the company's row
COMPANY = [(re.compile(r"(?i)^(iaw|iawc|il american|illinois[- ]american)\b"), "ILLINOIS AMERICAN WATER COMPANY"),
           (re.compile(r"(?i)^aqua (illinois|america)\b"), "AQUA ILLINOIS, INC.")]
SHORT = {"illinois american water company": "Illinois American Water", "aqua illinois inc": "Aqua Illinois"}
WORKS = (r"(wastewater treatment plant|wastewater treatment facility|wastewater treatment center|water reclamation "
         r"facility|water reclamation plant|water reclamation|sewage treatment plant|wwtp|wwtf|wrf|wrp|stp|potw|"
         r"csos?|combined sewer overflows?|sscs|lagoons?|treatment plant|main|plant|#\s*\d+|no\.?\s*\d+|"
         r"north|south|east|west|northeast|northwest|southeast|southwest)")


def key(name: str | None) -> str | None:
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower()).replace("&", " and ")
    s = re.sub(r"\b(city|village|town|township) of\b", " ", s)
    s = re.sub(r"[^a-z0-9# ]+", " ", s)
    s = re.sub(r"\b(the|of|il|illinois|inc|llc|co|company|corp|corporation)\b", " ", s)
    s = re.sub(r"\bmt\b", "mount", re.sub(r"\bst\b", "saint", s))
    s = re.sub(r"\bs\s*d\b", "sanitary district", s)
    s = " ".join(s.split())
    for _ in range(4):
        s = re.sub(rf"\s+{WORKS}$", "", s).strip()
    return s or None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def display(epa: str | None) -> str | None:
    """'OREGON STP, CITY OF' -> 'City of Oregon (Oregon STP)'; 'ELMHURST, CITY OF' -> 'City of Elmhurst'."""
    if not epa:
        return epa
    s = " ".join(epa.replace(" .", ".").split()).strip(" ,")
    s = re.sub(r"\.\s+(CITY|VILLAGE|TOWN) OF$", r", \1 OF", s, flags=re.I)
    m = re.match(r"^(.*?),\s*(CITY|VILLAGE|TOWN|TOWNSHIP)(?: OF)?\s*(SSCS)?$", s, re.I)
    if m:
        body, kind = m.group(1).strip(), m.group(2).title()
        place = re.sub(rf"\s*[-#]?\s*{WORKS}(\s+{WORKS})*\s*$", "", body, flags=re.I).strip(" -")
        place = re.sub(r"\s*-\s*$", "", place)
        fac = smart_title(body)
        return f"{kind} of {smart_title(place)}" + (f" ({fac})" if fac.lower() != smart_title(place).lower() else "")
    return smart_title(s)


ABBR = {"stp", "wwtp", "wwtf", "wrf", "wrp", "wrd", "sd", "csos", "cso", "mwrdgc", "mwrd", "iaw", "iawc", "potw", "sscs",
        "wtr", "lcpwd", "lcdpw", "idoc", "abrtf", "ii", "iii", "usa", "us", "dnr", "uc", "srwrd", "gwa", "ej", "ww", "sw",
        "ne", "nw", "se", "mhp"}


def smart_title(s: str) -> str:
    out = []
    for w in s.split():
        bare = re.sub(r"[^A-Za-z]", "", w).lower()
        out.append(w.upper() if bare in ABBR else re.sub(r"(?<=\w)'S\b", "'s", w.title()) if w.isupper() or w.islower() else w)
    return " ".join(out).replace("Mcelwain", "McElwain").replace("O'brien", "O'Brien")


def facility_part(fac: str, owner: str) -> str:
    """The facility as shown after the owner: 'City of Alton (Alton STP)' -> 'Alton STP'; 'Illinois American Water
    Company - Granite City WWTP' -> 'Granite City WWTP'."""
    m = re.match(r"^(?:City|Village|Town|Township) of .+? \((.+)\)$", fac)
    if m:
        return m.group(1)
    for pre in (owner, re.sub(r"(?i)\s+company$", "", owner)):
        if fac.lower().startswith(pre.lower()) and len(fac) > len(pre) + 3:
            return fac[len(pre):].strip(" -")
    return fac


def company_of(name: str | None) -> str | None:
    return next((c for pat, c in COMPANY if name and pat.search(name.strip())), None)


def form(name: str | None) -> str | None:
    n = (name or "").lower()
    if re.search(r"\b(u\.?s\.?|united states|national|army|navy|air force|veterans|federal)\b", n):
        return "federal facility"
    if re.search(r"\b(state park|correctional|idoc|department of (natural resources|transportation|corrections)|"
                 r"university of illinois|illinois state university|southern illinois university|state fish|"
                 r"state recreation|tollway|idot|dnr)\b", n):
        return "state facility"
    if re.search(r"\b(sanitary district|water reclamation district|wrd|sanitation district|sewer district|"
                 r"utility district|conservancy district|metropolitan sanitary|sanitary and sewage district|"
                 r"public water district|school district|park district|sd)\b", n):
        return "special district"
    if re.search(r"\b(metro(politan)? water reclamation district|mwrd)", n):
        return "special district"
    if re.search(r"\bauthority\b|\bagency\b|commission\b", n) and not re.search(r"\b(llc|inc)\b", n):
        return "authority"
    if re.search(r"\bcounty\b", n):
        return "county"
    if re.search(r"\b(village|township|town)\b", n):
        return "town"
    if re.search(r"\bcity\b", n):
        return "city"
    if re.search(r"\b(homeowners|owners'? association|condominium)\b", n):
        return "homeowners' association"
    if re.search(r"\b(mobile home|mhp|mhc|manufactured)\b", n):
        return "mobile-home park"
    if re.search(r"\b(campground|resort|rv park|koa)\b", n):
        return "campground or resort"
    if re.search(r"\b(country club|golf)\b", n):
        return "private club"
    if re.search(r"\bwater cooperative\b|\bco-?op\b", n):
        return "member-owned utility"
    if re.search(r"\b(illinois american water|aqua illinois|utilities inc|utility (co|corp))\b", n):
        return "investor-owned utility"
    if re.search(r"\b(llc|inc|ltd|corp|corporation|company|companies)\b", n):
        return "business or industrial"
    return None


def towns_of(name: str | None, cities: list[str]) -> list[str]:
    out = []
    m = re.match(r"^(?:City|Village|Town|Township) of (.+?)(?: \(|$)", name or "")
    if m:
        out.append(m.group(1))
    out += [re.sub(r"^(Village|City|Town) Of ", "", title(c)) for c in cities if c]
    return list(dict.fromkeys(t for t in out if t))


def plants() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "IL" and r.get("npdes_permit"):
            out[r["npdes_permit"].upper()].append(r)
    return out


def sobe_permits() -> dict[str, Counter]:
    """IL permit -> Counter of the names EPA's overflow tables give it (collection system, then discharger)."""
    out: dict[str, Counter] = defaultdict(Counter)
    if not EVENTS.exists():
        return out
    for r in json.loads(EVENTS.read_text()).get("records", []):
        p = r.get("npdes_permit") or ""
        if p.startswith("IL"):
            n = (r.get("raw") or {}).get("collection_system_name") or r.get("discharger_name")
            out[p][re.sub(r"\s+SSCS\s*$", "", n.strip()) if n else None] += 1
    return out


def notification(kind: str, gl: bool, private: bool = False) -> str:
    s = BASE_LAW
    if kind == "cso":
        s += GL_LAW if gl else CSO_LAW
    if private:
        s += " The permit conditions bind a private permittee as they bind a public one."
    return s


def row(rid, name, kind, permits, towns, waters, notes, legal_form, gl=False, outfall_count=None, outfalls_source=None,
        verified="inferred", short=None, private=False):
    return {"id": rid, "name": name, "short_name": short or name, "legal_form": legal_form, "state": "IL",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfall_count,
            "outfalls_source": outfalls_source, "notification_channel": notification(kind, gl, private),
            "notification_feed_machine_readable": True, "notification_signup_url": SIGNUP if gl else None,
            "towns": towns, "notes": notes, "verified": verified, "checked": CHECKED, "aliases": [rid],
            "source_areas": ["il"]}


def build(dis: list[dict]) -> tuple[list[dict], Counter]:
    keep = [d for d in dis if "il" not in (d.get("source_areas") or []) or d.get("state") != "IL"]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    pl = plants()
    cand = json.loads(CANDIDATES.read_text())
    private_permits = {c["npdes_permit"] for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"]: c for c in cand["public_by_name"]}
    new: list[dict] = []
    by_key: dict[str, dict] = {}
    counts = Counter()

    def add(r):
        new.append(r)
        ids.add(r["id"])
        held.update(p.upper() for p in r["npdes_permits"])

    def owner_of(p, fallback):
        rows = pl.get(p) or []
        if rows and rows[0].get("permit_name"):
            return clean_name(rows[0]["permit_name"]), "EPA ICIS-NPDES permit name"
        return fallback, "EPA's CSO inventory permittee name"

    # 1. research rows
    for r in json.loads(RESEARCH.read_text()):
        p = (r.get("npdes_permit") or "").upper()
        if r["id"] in ids or p in held:
            counts["research row already held"] += 1
            continue
        gl = "Great Lakes Basin list (40 CFR" in (r.get("notes") or "")
        kind = "cso" if r["kind"] == "cso" else "sso"
        owner, basis = owner_of(p, r["name"])
        fac = display(r["name"])
        own = display(owner)
        lf = form(owner) or form(r["name"])
        if p in CSO_NAMES:
            own, lf = CSO_NAMES[p]
            basis = "the permit's town (EPA's name for it is a description)"
        elif re.search(r"(?i)^(.+?)\s+csos?$", owner or "") and not lf:
            own = re.sub(r"(?i)\s+csos?$", "", display(owner)) + " combined sewer system"
        name = own if key(own) == key(fac) or own == fac or p in CSO_NAMES else f"{own} ({facility_part(fac, own)})"
        if p in private_permits:
            continue                                   # step 4 files the private permittees
        notes = (f"Permittee from {basis}. " + (r.get("notes") or "")).strip()
        nr = row(r["id"], name, kind, [p], towns_of(own, r.get("towns") or []), r.get("receiving_waters") or [],
                 notes, lf, gl=gl, outfall_count=r.get("outfall_count"),
                 outfalls_source=r.get("outfalls_source"), verified=r.get("verified") or "inferred",
                 short=own)
        add(nr)
        counts["research"] += 1
        if kind == "sso" and not company_of(owner):
            by_key.setdefault(key(owner) or p, nr)

    # 2. plant permits grouped by owner (a company's plants wait for its row in step 4)
    deferred: dict[str, list[tuple[str, str]]] = defaultdict(list)
    groups: dict[str, list[str]] = defaultdict(list)
    for p, rows in sorted(pl.items()):
        if p in held or p in private_permits:
            continue
        owner = clean_name(rows[0].get("permit_name")) or rows[0].get("permittee")
        if company_of(owner) or company_of(rows[0].get("permittee")):
            deferred[company_of(owner) or company_of(rows[0].get("permittee"))].append((p, rows[0].get("permittee") or owner))
            held.add(p)
            continue
        if private_reason(p, {"rows": rows, "files": {"plants"}}) and not form(owner) in (
                "city", "town", "county", "special district", "authority", "state facility", "federal facility"):
            counts["plant private by EPA's type, not a candidate: held"] += 1
            continue
        groups[key(owner) or p].append(p)
    for k, perms in groups.items():
        rows = [r for p in perms for r in pl[p]]
        owner = clean_name(rows[0].get("permit_name")) or rows[0].get("permittee")
        if k in by_key:
            by_key[k]["npdes_permits"] += perms
            held.update(perms)
            counts["plant permits joined to a research row"] += len(perms)
            continue
        rid = f"il-{slug(k)}"
        if rid in ids:
            rid = f"il-{slug(k)}-{perms[0].lower()}"
        facs = ", ".join(sorted({f"{smart_title(r.get('permittee') or '')} ({r['npdes_permit']})" for r in rows}))
        name = display(owner)
        waters = list(dict.fromkeys(r["receiving_water_echo"] for r in rows if r.get("receiving_water_echo")))[:8]
        nr = row(rid, name, "plant", perms, towns_of(name, sorted({r.get("city") for r in rows if r.get("city")})),
                 waters, f"Permittee as EPA ICIS-NPDES names it; plants: {facs}. (scripts/add_il_operators.py)",
                 form(owner), outfall_count=len(rows),
                 outfalls_source=f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)",
                 verified="fetched")
        add(nr)
        by_key[k] = nr
        counts["plant rows"] += 1

    # 3. permits in EPA's overflow tables that no row holds (a private candidate's permittee waits for its row)
    cand_keys = {key(PRIVATE_ALIASES.get(c["permittee_as_recorded"], c["permittee_as_recorded"])):
                 PRIVATE_ALIASES.get(c["permittee_as_recorded"], c["permittee_as_recorded"])
                 for c in cand["candidates"] if c["permittee_as_recorded"] != "[name removed]"}
    for p, names in sorted(sobe_permits().items()):
        if p in held or p in private_permits:
            continue
        nm = next((n for n, _ in names.most_common() if n and clean_name(n)), None)
        if p in public_by_name:
            nm = public_by_name[p]["permittee_as_recorded"]
        company = company_of(nm) or cand_keys.get(key(nm) or "")
        if company:
            deferred[company].append((p, nm))
            held.add(p)
            continue
        if p in HAND:
            nm = HAND[p][0]
        k = key(nm) or p
        if k in by_key:
            by_key[k]["npdes_permits"].append(p)
            held.add(p)
            counts["overflow-table permits joined"] += 1
            continue
        name = display(clean_name(nm)) if nm else f"Sewer system (permit {p})"
        rid = f"il-{slug(k)}" if f"il-{slug(k)}" not in ids else f"il-{slug(k)}-{p.lower()}"
        hand = HAND.get(p)
        nr = row(rid, name, "sso", [p], towns_of(name, []), [],
                 hand[2] if hand else
                 f"Named from EPA's overflow tables (collection system {nm!r}); permit {p}. (scripts/add_il_operators.py)",
                 hand[1] if hand else form(nm), verified="fetched", private=bool(hand))
        add(nr)
        by_key[k] = nr
        counts["overflow-table rows"] += 1

    # 3b. the two permits EPA types private whose names are public bodies
    for p, c in sorted(public_by_name.items()):
        if p in held:
            continue
        name = display(c["permittee_as_recorded"])
        kind = "cso" if "COMBINED SEWER" in (c.get("facility") or "") else "plant"
        nr = row(f"il-{slug(key(c['permittee_as_recorded']) or p)}-{p.lower()}", name, kind, [p],
                 towns_of(name, [c.get("city")]), c.get("receiving_waters_echo") or [],
                 f"EPA types the facility privately owned, but the permittee is a public body ({c['permittee_as_recorded']}); "
                 f"facility {smart_title(c.get('facility') or '')}, permit status {c.get('permit_status')}.",
                 form(c["permittee_as_recorded"]), verified="fetched")
        add(nr)
        counts["public bodies EPA types private"] += 1

    # 4. private sewage permits
    groups4: dict[str, list[dict]] = defaultdict(list)
    for c in cand["candidates"]:
        if c["npdes_permit"] in held:
            continue
        who = PRIVATE_ALIASES.get(c["permittee_as_recorded"], c["permittee_as_recorded"])
        groups4[who if who != "[name removed]" else f"[name removed] {c['npdes_permit']}"].append(c)
    deferred_names = [pn for v in deferred.values() for pn in v]
    for who, cs in groups4.items():
        perms = [c["npdes_permit"] for c in cs]
        facs = ", ".join(f"{smart_title(c['facility'])} ({c['npdes_permit']}, {title(c['city'])})" for c in cs)
        if who.startswith("[name removed]"):
            c = cs[0]
            name, lf = f"{smart_title(c['facility'])} (permit {c['npdes_permit']})", "facility (permittee not named)"
            rid = f"il-{c['npdes_permit'].lower()}"
            note = "EPA's permittee name reads as an individual's: not named here; the row names the facility."
            waters = []
        else:
            lf, note = PRIVATE_FORMS.get(who, (None, "The permittee EPA records is the facility's own name; its legal "
                                                     "form was not read."))
            name = SHORT.get(key(who) or "", smart_title(who))
            rid = f"il-{slug(key(who) or who)}"
            waters = list(dict.fromkeys(w for c in cs for w in c.get("receiving_waters_echo") or []))[:8]
        if rid in ids:
            rid = f"{rid}-{perms[0].lower()}"
        research_ids = [c["research_row"] for c in cs if c.get("research_row")]
        extra = [p for p, _ in deferred.pop(who, [])]
        if extra:
            perms += extra
            facs += "; and from EPA's overflow tables " + ", ".join(f"{smart_title(n)} ({p})" for p, n in deferred_names
                                                                     if p in extra)
        nr = row(rid, name, "plant" if not research_ids else "sso", perms,
                 sorted({title(c["city"]) for c in cs}) if lf != "facility (permittee not named)" else [title(cs[0]["city"])],
                 waters, (note + f" Plants: {facs}. Privately owned; permittee as EPA ICIS-NPDES records it "
                          "(research/il/private-utilities-candidates.json); Illinois EPA's permit documents were not "
                          "read.").strip(), lf, verified=False, private=True)
        nr["aliases"] += research_ids
        add(nr)
        counts["private rows"] += 1
    if deferred:
        raise SystemExit(f"company permits with no company row: {dict(deferred)}")
    for r in new:
        r["npdes_permits"] = list(dict.fromkeys(r["npdes_permits"]))
    return keep + new, counts


def main(argv) -> int:
    dis = json.loads(DIS.read_text())
    out, counts = build(dis)
    new = [d for d in out if "il" in (d.get("source_areas") or []) and d.get("state") == "IL"]
    print(json.dumps(dict(counts), indent=1), f"\nIllinois rows {len(new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
