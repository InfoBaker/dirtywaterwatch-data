"""Texas operator rows for data/dischargers.json: one row per operator, every Texas sewage permit in exactly one row, and
every regulated entity of TCEQ's overflow table in exactly one row.

Usage (after scripts/tx_permit_crosswalk.py; the TCEQ table saved under data/raw/tx-tceq-sso-opendata/):
    pipeline/.venv/bin/python -I scripts/add_tx_operators.py [--dry-run]

Inputs
  1. data/outfalls-plants-us.json: EPA's ICIS-NPDES sewage plant permits with state TX (1,814). permit_name is the owner
     as EPA records it ("HOUSTON, CITY OF"); the permits of one owner name are one row.
  2. research/tx/private-utilities-candidates.json: the private sewage permits (791, 100 of them among the plants) and
     the permits EPA types private whose names read as public bodies (51); legal_form_proposed is used, and a permittee
     the candidates file removed is filed under the facility, "facility (permittee not named)". Permits not starting TX
     are left to their own state.
  3. TCEQ's Sanitary Sewer Overflows table (the saved response) and data/reference/tx-tceq-permits.json: each regulated
     entity (RN...) of the table joins one row, in this order:
       a. the row holding the federal permit its reports give or the crosswalk gives (ingest/tx_transforms.federal_permit,
          the permit most of its reports carry);
       b. the row of the one owner whose linked WQ permits share the entity's WQ base number (TCEQ's permit number is
          the permittee's seven-digit base and a three-digit facility suffix: WQ0010495 is Houston's, WQ0010495090 its
          69th Street plant);
       c. the row of the one EPA plant whose facility name is the entity's, plant words aside ("BOB DERRINGTON WWP" is
          EPA's "BOB DERRINGTON WATER RECLAMATION PLANT", Odessa's);
       d. the row named for the city or town the entity's name gives ("CITY OF WACO COLLECTION SYSTEM" -> City of Waco);
       e. otherwise a row of its own (id tx-rn<number>), named as TCEQ files the entity; a federal permit only TCEQ's
          table names stays with that entity's row.
     The entity numbers are the row's tceq_entities; the WQ permits its state_permits.
  4. research/tx/dischargers.json (12 rows): each research id is an alias of the row of its operator (RESEARCH).
Rules
  - Name: "X, CITY OF" -> "City of X"; other names in title case with the usual abbreviations kept (MUD, WCID, FWSD,
    SUD, ISD, LLC ...). Never an individual's name: a name that reads as a person's is replaced by the facility's or by
    "TCEQ regulated entity <RN>", legal_form "facility (permittee not named)".
  - legal_form (form()) from the name and EPA's facility type, on the controlled list (docs/legal-forms.md); null when
    neither says.
  - kind: "sso" when an entity of the row has reports in TCEQ's table; otherwise "plant".
  - notification_channel: the report to the TCEQ regional office within 24 hours and in writing within five working
    days (30 TAC 305.125(9)), published in TCEQ's open data in batches; for a local government's facility, the notice
    to local officials and media under 30 TAC 319.302 above its thresholds. notification_signup_url null.
  - Idempotent: a rerun replaces every row it wrote (state TX, source_areas ["tx"]).
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import NAME_REMOVED, scrub_discharger  # noqa: E402
from ingest import dischargers_schema as DS  # noqa: E402
from ingest import tx_transforms as T  # noqa: E402

DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
RESEARCH = ROOT / "research" / "tx" / "dischargers.json"
CANDIDATES = ROOT / "research" / "tx" / "private-utilities-candidates.json"
CROSSWALK = ROOT / "data" / "reference" / "tx-tceq-permits.json"
RAW = ROOT / "data" / "raw" / "tx-tceq-sso-opendata"
CHECKED = "2026-11-07"
DATASET = "https://data.texas.gov/dataset/8kc5-95uk"
LAW = ("The permittee reports every sewer overflow or unauthorized discharge to the TCEQ regional office within 24 hours "
       "and in writing within five working days, or in a monthly summary for small qualifying spills (30 TAC "
       "305.125(9); TCEQ's reporting page). TCEQ publishes the reports in its Sanitary Sewer Overflows open data, "
       f"refreshed in batches months later ({DATASET}).")
LOCAL = (" A local government's facility must also notify local government officials and local media within 24 hours "
         "of a spill likely to affect a drinking-water source, of 50,000 gallons or more near one or in a sensitive "
         "area, or of 100,000 gallons or more (30 TAC 319.302-319.303); nothing requires a web posting.")
OWN = " The operator's own pages were not searched individually."
ABBR = {"mud", "wcid", "fwsd", "sud", "pud", "ud", "mwd", "isd", "llc", "lp", "ltd", "inc", "wwtp", "wwtf", "wsc",
        "mua", "tx", "us", "usa", "ii", "iii", "iv", "rv", "hoa", "poa", "mhc", "mhp", "lc", "llp", "wrf", "wrc", "wwp",
        "rn", "ud", "wsd", "msd", "tdcj", "txdot", "ra", "gbra", "lcra", "bra", "sjra", "tra", "nwhcmud", "cisd",
        "wcmud", "ws", "fm", "pa", "kk", "jv", "sa", "ssd", "cid", "id", "mmd", "dba", "uvb", "txu"}
SMALL = {"of", "and", "the", "de", "del", "la", "at", "on", "for"}
# research id -> the owner key (EPA's permit_name, upper case) or an entity name pattern
RESEARCH_ROWS = {
    "tx-houston": "HOUSTON, CITY OF", "tx-saws": "SAN ANTONIO WATER SYSTEM", "tx-austin-water": "AUSTIN, CITY OF",
    "tx-dallas-water": "DALLAS, CITY OF", "tx-fort-worth": "FORT WORTH, CITY OF", "tx-arlington": "ARLINGTON, CITY OF",
    "tx-trinity-river-authority": "TRINITY RIVER AUTHORITY OF TEXAS", "tx-corpus-christi": "CORPUS CHRISTI, CITY OF",
    # the research filed Post Oak Creek under Killeen; TCEQ's table puts the entity (RN101612448) in Grayson County under
    # Sherman's permit TX0024325, so the research id joins the row holding that entity
    "tx-killeen-post-oak": re.compile(r"^RN101612448 "), "tx-waco": "WACO, CITY OF",
    "tx-gulf-coast-authority": "GULF COAST AUTHORITY", "tx-el-paso-water": "EL PASO WATER UTILITIES PUBLIC SERVICE BOARD",
}
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").replace("+", " ").split()):
        bare = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if bare in ABBR or re.search(r"\d", bare):
            out.append(w.upper())
        elif bare in SMALL and i:
            out.append(w.lower())
        elif bare == "no":
            out.append("No.")
        else:
            out.append(re.sub(r"(?<=\w)'S\b", "'s", w.capitalize() if w.isupper() or w.islower() else w))
    return re.sub(r"No\.\.", "No.", " ".join(out))


def owner_name(pn: str) -> str:
    s = " ".join((pn or "").replace("+", " ").split()).strip(" ,")
    m = re.match(r"^(.+?)\s+(CITY|TOWN|VILLAGE)\s+OF\s+(?:[A-Z]+\s+)?CO(?:UNTY)?$", s, re.I)   # "RENO CITY OF LAMAR CO"
    if m:
        return f"{m.group(2).title()} of {smart_title(m.group(1))}"
    m = re.match(r"^(.+?),?\s+(CITY|TOWN|VILLAGE)\s+OF$", s, re.I)
    if m and not re.search(r"\bAND$|&$", m.group(1).strip(" ,"), re.I):
        return f"{m.group(2).title()} of {smart_title(m.group(1))}"
    return smart_title(s)


def key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


PLANT_WORDS = re.compile(r"\b(?:WASTE\s*WATER|WATER|SEWAGE|TREATMENT|RECLAMATION|RECYCLING|REGIONAL|PLANT|FACILITY|"
                         r"CENTER|WWTP|WWTF|WWP|WRP|WRF|WRC|STP|WTP|CITY OF|THE)\b")


GENERIC = {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "northside",
           "southside", "eastside", "westside", "central", "main", "municipal", "regional", "lagoon", "ponds", "plant",
           "system", "collection", "lift", "station", "downtown", "old", "new", "upper", "lower"}


def facility_key(name: str | None) -> str:
    """A plant's name with the plant words taken out ('BOB DERRINGTON WWP' and 'BOB DERRINGTON WATER RECLAMATION
    PLANT' are one key); '' for a name left with only generic words or numbers ('SOUTHWEST PLANT', 'PLANT 2')."""
    words = [w for w in re.findall(r"[a-z0-9]+", PLANT_WORDS.sub(" ", (name or "").upper()).lower())]
    if not [w for w in words if w not in GENERIC and not w.isdigit() and not re.fullmatch(r"no|\d+[a-z]?", w)]:
        return ""
    return "".join(words)


def form(name: str, ftype: str | None) -> str | None:
    n, t = name.upper(), (ftype or "")
    if re.match(r"^CITY OF\b", n):
        return "city"
    if re.match(r"^(TOWN|VILLAGE) OF\b", n):
        return "town"
    if t.startswith("Tribal"):
        return "tribal"
    if t.startswith("Federal"):
        return "federal facility"
    if re.search(r"\b(MUD|MUNICIPAL UTILITY DISTRICT|WCID|WATER CONTROL|FWSD|FRESH WATER SUPPLY|SUD|SPECIAL UTILITY|PUD|"
                 r"UTILITY DISTI?R?CT|UD|MMD|MANAGEMENT DISTRICT|IMPROVEMENT DISTRICT|WATER DISTRICT|CONSERVATION DISTRICT|"
                 r"NAVIGATION DISTRICT|DRAINAGE DISTRICT|ISD|SCHOOL DISTRICT|HOSPITAL DISTRICT|MWD|WATER SUPPLY DISTRICT|"
                 r"SANITARY DISTRICT|SEWER DISTRICT|WSD|RECLAMATION DISTRICT|DISTRICT NO)\b", n):
        return "special district"
    if re.search(r"\bAUTHORITY\b|\bPUBLIC SERVICE BOARD\b|\bSAN ANTONIO WATER SYSTEM\b|\bUTILITIES$|\bUTILITIES BOARD\b", n) \
            and not re.search(r"\b(INC|LLC|LP|LTD|CORP|COMPANY)\b", n):
        return "authority"
    if re.search(r"\b(WSC|WATER SUPPLY CORP|WATER SUPPLY CORPORATION|COOPERATIVE|CO-OP)\b", n):
        return "member-owned utility"
    if t.startswith("State") or re.search(r"\b(TEXAS DEPARTMENT|TEXAS PARKS|STATE OF TEXAS|UNIVERSITY|TEXAS A&M|"
                                          r"TEXAS TECH|STATE PARK|STATE JAIL|TDCJ|TXDOT)\b", n):
        return "state facility"
    if t.startswith("County") or re.match(r"^[A-Z .]+ COUNTY$", n):
        return "county"
    if re.search(r"\b(HOA|HOMEOWNERS|PROPERTY OWNERS|POA|OWNERS ASSOCIATION)\b", n):
        return "homeowners' association"
    if re.search(r"\b(MHP|MHC|MOBILE HOME|MANUFACTURED HOME)\b", n):
        return "mobile-home park"
    if re.search(r"\b(RV|CAMPGROUND|CAMP|RESORT|KOA)\b", n):
        return "campground or resort"
    if re.search(r"\b(INC|LLC|L\.L\.C|LP|L\.P|LTD|CORP|CORPORATION|COMPANY|CO)\b\.?", n):
        return ("investor-owned utility" if re.search(r"\b(UTILIT|WATER|SEWER|WASTEWATER|AQUA)", n)
                else "business or industrial")
    if t.startswith("Municipality") and re.search(r"\bCITY\b", n):
        return "city"
    return None


def person_name(name: str) -> bool:
    return bool(name) and scrub_discharger({"discharger_name": name})["discharger_name"] == NAME_REMOVED \
        and not T.FACILITY_WORDS.search(name)


# words that make a part of an owner's name a body's, not a person's
ORG_WORDS = re.compile(
    r"\b(?:inc|llc|l\.?l\.?c|lp|l\.?p|ltd|llp|corp|corporation|company|co|association|assn|associates|partners|partnership|"
    r"trust|holdings|group|enterprises|properties|property|investments?|development|developers?|ventures?|capital|"
    r"management|services?|utilit(?:y|ies)|water|sewer|wastewater|systems?|works|plants?|mud|wcid|fwsd|sud|pud|isd|mwd|"
    r"district|authority|county|city|town|village|state|texas|department|university|college|school|church|ministries|"
    r"camp|park|resort|rv|estates|ranch|club|hoa|poa|owners|homeowners|marina|hospital|center|centre|village|"
    r"apartments|mhp|mhc|motel|hotel|inn|farms?|dairy|foods|products|energy|oil|gas|pipeline|railroad|airport|"
    r"navigation|river|lake|bay|island|community|council|commission|board|federal|national|united states|us|usa|"
    r"army|navy|air force|tdcj|txdot|wwtp|wwtf|wrf|stp|lagoon|treatment|reclamation|recycling|regional|public|"
    r"municipal|consolidated|cooperative|co-op|supply|resources|industries|international|america|american|bank|"
    r"living|homes|home|subdivision|commercial|retail|plaza|mall|church|travel|truck|stop|store|market|ud|wsd|cisd|"
    r"i\.?s\.?d|cid|mmd|wsc|agency|tribe|tribal|indian|a&m|creek|branch|springs?|hills|valley|meadows?|oaks?|"
    r"crossing|landing|point|harbor|shores?|woods|pines|ridge|heights|place|counties|waste|disposal|parts|foundation|"
    r"ships?|equity|fund|lots)\b", re.I)
FAMILY = re.compile(r"\bfamily\s+(?:limited\s+)?(?:partnership|trust|lp|ltd)\b", re.I)


def owner_person(name: str) -> bool:
    """Whether EPA's owner name holds a private individual's name (review 2026-11-07 P1-2): a family partnership or
    trust, or any part of the name (split at commas, 'and', '&') that has no word of a body ('<code> <surname>,
    <forename>', 'HOA <name> AND <name>', a three-part personal name, '... LLC, AND <name>'). Errs toward the facility's
    name: a body's name with no such word is filed under its facility, which loses nothing."""
    n = " ".join((name or "").replace("+", " ").split())
    if not n:
        return False
    if FAMILY.search(n) or person_name(n):
        return True
    n = re.sub(r"^(?:the|hoa|poa)\s+", "", n, flags=re.I)
    n = re.sub(r",?\s*\b(city|town|village|county)\s+of\b", r" \1", n, flags=re.I)  # 'AUSTIN,CITY OF' -> 'AUSTIN city'
    n = re.sub(r"\bof\s+city\b", "city", n, flags=re.I)
    n = re.sub(r"\bA\s*&\s*M\b", "A-and-M university", n, flags=re.I)
    raw = [x.strip() for x in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*", n, flags=re.I) if x.strip()]
    parts: list[str] = []
    for x in raw:                     # a lone legal suffix or number belongs to the part before it ('BEARPEN CREEK, LP')
        if parts and (re.fullmatch(r"[\d\s.#-]+|(?:inc|l\.?l\.?c|l\.?p|ltd|llp|co|corp)\.?", x, re.I)):
            parts[-1] += " " + x
        else:
            parts.append(x)
    from build import redact
    for x in parts:
        if ORG_WORDS.search(x) or re.search(r"\d", x):
            continue
        words = re.findall(r"[A-Za-z]+", x)
        if len(words) == 1 and words[0].lower() not in redact.FIRST_NAMES:
            continue                  # one word, not a given name ('ANGELINA and Neches River Authority')
        return True
    return False


def tceq_rows() -> list[dict]:
    saved = sorted(p for p in RAW.glob("*.json") if not p.name.endswith(".meta.json") and p.name != "meta.json")
    if not saved:
        raise SystemExit("save TCEQ's table under data/raw/tx-tceq-sso-opendata/ first")
    doc = json.loads(saved[-1].read_text())
    return [r for pg in doc["pages"] for r in pg]


def build(dis: list[dict]) -> tuple[list[dict], dict]:
    keep = [d for d in dis if not (d.get("state") == "TX" and "tx" in (d.get("source_areas") or []))]
    held_elsewhere = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    # 1. owners of the plant permits
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "TX" and str(r.get("npdes_permit") or "").startswith("TX"):
            plants[r["npdes_permit"]].append(r)
    groups: dict[str, dict] = {}            # owner key -> {name, ftype, permits, lf, notes}
    permit_owner: dict[str, str] = {}

    def add_owner(k, name, ftype=None, lf=None, note=None):
        g = groups.setdefault(k, {"name": name, "ftype": ftype, "permits": [], "lf": lf, "notes": [], "rns": [],
                                  "wq": set(), "towns": set(), "waters": [], "plants": [], "research": []})
        if note and note not in g["notes"]:
            g["notes"].append(note)
        return g

    for p, rows in sorted(plants.items()):
        if p in held_elsewhere:
            continue
        pn = " ".join((rows[0].get("permit_name") or rows[0].get("permittee") or p).replace("+", " ").split())
        name = owner_name(pn)
        if owner_person(pn) or person_name(name):
            fac = smart_title(rows[0].get("permittee") or "")
            name = (f"{fac} (permit {p})" if fac and not owner_person(fac) and not re.search(r"\(", fac)
                    else f"Holder of permit {p}")
            lf = "facility (permittee not named)" if form(name, None) not in PUBLIC_FORMS else None
            k = f"PERMIT {p}"
        else:
            k, lf = key(name), None
        g = add_owner(k, name, rows[0].get("facility_type"), lf)
        g["permits"].append(p)
        permit_owner[p] = k
        g["plants"].append(f"{p} {smart_title(rows[0].get('permittee') or '')}".strip())
        g["towns"] |= {smart_title(r["city"]) for r in rows if r.get("city") and "COUNTY" not in r["city"].upper()
                       and r["city"].upper() != "UNKNOWN"}
        g["waters"] += [r["receiving_water_echo"].strip() for r in rows if r.get("receiving_water_echo")]
    # 2. the private candidates
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand["public_by_name"] if str(c["npdes_permit"]).startswith("TX")}
    for p, c in sorted(cands.items()):
        if p in held_elsewhere:
            continue
        lf = c.get("legal_form_proposed")
        if p in permit_owner:                          # already a plant's owner row: the candidates' legal form
            g = groups[permit_owner[p]]
            if lf and not g["lf"] and form(g["name"], g["ftype"]) not in PUBLIC_FORMS:
                g["lf"] = lf
            continue
        who = c.get("permittee_as_recorded") or ""
        if not who or NAME_REMOVED in who or owner_person(who) or person_name(owner_name(who)):
            fac = c.get("facility") or ""
            name = (f"{smart_title(fac)} (permit {p})" if fac and NAME_REMOVED not in fac and not owner_person(fac)
                    else f"Holder of permit {p}")
            k, lf = f"PERMIT {p}", "facility (permittee not named)"
            if form(name, None) in PUBLIC_FORMS:       # a district's plant whose permittee of record was not named
                lf = None
        else:
            name = owner_name(who)
            k = key(name)
            if form(name, None) in PUBLIC_FORMS:       # a name that reads as a public body: its form, not the proposal
                lf = form(name, None)
        g = add_owner(k, name, (c.get("ownership") or {}).get("facility_type"), lf)
        g["permits"].append(p)
        permit_owner[p] = k
        if lf == "facility (permittee not named)":
            g["towns"] |= set()
        elif c.get("city"):
            g["towns"].add(smart_title(c["city"]))
        g["waters"] += list(c.get("receiving_waters_echo") or [])
    # 3. TCEQ's regulated entities
    x = json.loads(CROSSWALK.read_text())
    look = {"wq": x["wq_to_npdes"], "rn": x["rn_to_npdes"]}
    ent: dict[str, dict] = {}
    for r in tceq_rows():
        rn = (r.get("regulated_entity_number") or "").strip().upper()
        e = ent.setdefault(rn, {"names": Counter(), "reports": 0, "permits": Counter(), "wq": set(), "counties": Counter()})
        e["names"][" ".join((r.get("regulated_entity_name") or "").split())] += 1
        e["reports"] += 1
        p, _, wq = T.federal_permit(r, look)
        if p:
            e["permits"][p] += 1
        e["wq"] |= set(wq)
        if r.get("county"):
            e["counties"][r["county"]] += 1
    # WQ base -> owners of the entities whose permit is linked
    base_owner: dict[str, set] = defaultdict(set)
    for rn, e in ent.items():
        for p in e["permits"]:
            if p in permit_owner:
                for q in e["wq"]:
                    base_owner[q[:9]].add(permit_owner[p])
    city_rows = {key(g["name"]): k for k, g in groups.items() if re.match(r"^(City|Town|Village) of ", g["name"])}
    fac = defaultdict(set)                  # EPA's facility name, plant words aside -> owners
    for p, rows in plants.items():
        if p in permit_owner:
            fk = facility_key(rows[0].get("permittee"))
            if len(fk) >= 6:
                fac[fk].add(permit_owner[p])
    how = Counter()
    for rn, e in sorted(ent.items()):
        ename = e["names"].most_common(1)[0][0]
        k, basis = None, None
        if e["permits"]:
            p = e["permits"].most_common(1)[0][0]
            if p in permit_owner:
                k, basis = permit_owner[p], "federal permit"
        if k is None:
            owners = {o for q in e["wq"] for o in base_owner.get(q[:9], ())}
            if len(owners) == 1:
                k, basis = next(iter(owners)), "WQ base number"
        if k is None and len(fac.get(facility_key(ename), ())) == 1:
            k, basis = next(iter(fac[facility_key(ename)])), "EPA's facility of the same name"
        if k is None:
            m = re.match(r"^(?:THE\s+)?(CITY|TOWN|VILLAGE) OF\s+(.+)$", ename.upper())
            if m:
                kind, words = m.group(1), m.group(2).split()
                for n in range(len(words), 0, -1):          # the longest prefix that names a city row already
                    ck = key(f"{kind.title()} of {smart_title(' '.join(words[:n]))}")
                    if ck in city_rows:
                        k, basis = city_rows[ck], "the city its name gives"
                        break
                if k is None:
                    c = re.match(r"^([A-Z .'-]+?)(?:\s+(?:COLLECTION|WASTEWATER|WWTP|WWTF|SEWER|SANITARY|LIFT|PUBLIC|"
                                 r"WATER|UTILIT|WRF|WTP|PLANT|SYSTEM)\b.*)?$", m.group(2))
                    if c and len(c.group(1).split()) <= 3:
                        nm = f"{kind.title()} of {smart_title(c.group(1).strip())}"
                        k, basis = key(nm), "the city its name gives"
                        add_owner(k, nm, None, "city" if kind == "CITY" else "town")
                        city_rows[key(nm)] = k
        if k is None:
            nm = smart_title(ename)
            lf = None
            if not ename or person_name(nm):
                nm, lf = f"TCEQ regulated entity {rn}", "facility (permittee not named)"
            k, basis = f"RN {rn}", "its own row"
            g = add_owner(k, nm, None, lf)
            g["rn_row"] = rn
            for p in e["permits"]:
                if p not in permit_owner and p not in held_elsewhere:
                    g["permits"].append(p)
                    permit_owner[p] = k
        how[basis] += 1
        g = groups[k]
        g["rns"].append(rn)
        g["wq"] |= e["wq"]
        g.setdefault("reports", 0)
        g["reports"] += e["reports"]
        g.setdefault("entity_names", []).append(f"{rn} {smart_title(ename) if not person_name(smart_title(ename)) else '(name not shown)'}")
        g.setdefault("counties", Counter()).update(e["counties"])
    # 4. research ids
    for rid, target in RESEARCH_ROWS.items():
        if isinstance(target, str):
            k = key(owner_name(target)) if key(owner_name(target)) in groups else None
        else:
            k = next((kk for kk, g in groups.items() if any(target.search(n) for n in g.get("entity_names", []))), None)
        if k is None:
            raise SystemExit(f"research row {rid}: no operator row for {target!r}")
        groups[k]["research"].append(rid)
    # rows
    ids = Counter()
    new = []
    for k, g in groups.items():
        rid = f"tx-rn{g['rn_row'][2:]}" if g.get("rn_row") else "tx-" + re.sub(r"[^a-z0-9]+", "-", g["name"].lower()).strip("-")[:70]
        ids[rid] += 1
        if ids[rid] > 1:
            rid = f"{rid}-{ids[rid]}"
        lf = g["lf"] or form(g["name"], g["ftype"])
        reports = g.get("reports", 0)
        note = []
        if g["plants"]:
            note.append("EPA ICIS-NPDES: " + "; ".join(g["plants"][:12]) + (f"; and {len(g['plants']) - 12} more" if len(g["plants"]) > 12 else "") + ".")
        if g.get("entity_names"):
            note.append(f"TCEQ regulated entities in the overflow table: {'; '.join(g['entity_names'][:10])}"
                        + (f"; and {len(g['entity_names']) - 10} more" if len(g["entity_names"]) > 10 else "")
                        + f" ({reports} report(s), September 2010 to August 2026, table refreshed 2026-09-24).")
        else:
            note.append("No report under these permits is in TCEQ's overflow table (read 2026-11-07).")
        if not g["permits"]:
            note.append("No federal permit was found for the entity (it may discharge through another operator's plant).")
        public = lf in PUBLIC_FORMS
        towns = sorted(g["towns"])[:1] if lf == "facility (permittee not named)" else sorted(g["towns"])
        counties = [f"{T.county_name(c)}" for c, _ in g.get("counties", Counter()).most_common(3)]
        new.append({
            "id": rid, "name": g["name"], "short_name": g["name"], "legal_form": lf, "state": "TX",
            "kind": "sso" if reports else "plant", "npdes_permit": g["permits"][0] if g["permits"] else None,
            "npdes_permits": list(g["permits"]), "receiving_waters": list(dict.fromkeys(g["waters"]))[:8],
            "water_slugs": [], "outfall_count": sum(len(plants.get(p, [])) for p in g["permits"]) or None,
            "outfalls_source": (f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, "
                                f"{sum(len(plants.get(p, [])) for p in g['permits'])} rows)"
                                if any(p in plants for p in g["permits"]) else None),
            "notification_channel": LAW + (LOCAL if public else "") + OWN,
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": " ".join(note), "verified": "fetched", "checked": CHECKED,
            "aliases": list(dict.fromkeys([rid] + g["research"])), "source_areas": ["tx"],
            "tceq_entities": sorted(g["rns"]), "state_permits": sorted(g["wq"]),
            **({"counties": counties} if counties else {}),
        })
    # a row whose name and form the registry's check questions (a joint permit of a company and a district, a word the
    # check reads as public or private) is filed with no legal form rather than a guess
    for r in new:
        if r["legal_form"] and DS.check_legal_forms([r]):
            r["notes"] += f" Legal form not settled by the name (read as {r['legal_form']!r}; the permit was not read)."
            r["legal_form"] = None
    new.sort(key=lambda r: r["id"])
    allids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in allids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup[:10]}")
    every = Counter(p for r in new for p in r["npdes_permits"])
    twice = [p for p, n in every.items() if n > 1]
    if twice:
        raise SystemExit(f"permits in two rows: {twice[:10]}")
    stats = {"rows": len(new), "permits": len(every), "entities": len(ent), "entity_joins": dict(how),
             "kind": dict(Counter(r["kind"] for r in new)), "legal_form": dict(Counter(r["legal_form"] for r in new)),
             "held_elsewhere": sorted(p for p in (set(plants) | set(cands)) if p in held_elsewhere)}
    return keep + new, stats


def main(argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    out, stats = build(dis)
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
