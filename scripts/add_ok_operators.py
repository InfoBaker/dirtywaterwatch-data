"""Oklahoma operator rows for data/dischargers.json: one row per operator, every Oklahoma permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_ok_operators.py [--dry-run] [--deq data/raw/ok-deq-gis/layer4-rows.json]

Inputs
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's sewage permits with state OK (316 permits, 404 discharge points:
     264 OK00..., 40 coverages under DEQ's general permit for small lagoon systems OKG58...., 9 OK01..., 2 OK10...,
     and OKP003097). permit_name is the owner as EPA records it, permittee the facility.
  2. research/ok/dischargers.json (6 rows: Oklahoma City, Tulsa, Broken Arrow, Norman, Lawton, Sulphur) and
     research/ok/federal-seed.json: each research id stays as an alias of the row that holds its city's permits.
  3. research/ok/private-utilities-candidates.json (18 candidates, all already in the plant list or named here).
  4. EPA's overflow tables (2026-11-12 current and all-versions extracts): no Oklahoma report; one Oklahoma collection
     system, the Kickapoo plant's (OK0044733, owner type Tribal Government).
  5. DEQ's NPDES Dischargers layer (gis.deq.ok.gov WaterQWeb MapServer layer 4, "Data set updated 06/14/2026", read
     2026-11-14, safe fields only, saved as data/raw/ok-deq-gis/layer4-rows.json, git-ignored): its points are EPA's
     (median distance 0 m over the 317 discharge points matched by permit and outfall), so it adds no outfall; a permit
     DEQ marks Terminated, or that the layer does not hold, is said so in the row's notes.
Rules
  - The owner is EPA's permit_name (the permittee field where permit_name is empty) put in order: "Enid, City of" is
    "City of Enid", "X PWA" "X Public Works Authority" (Oklahoma's public trusts under 60 O.S. 176 for a city or town:
    legal_form "authority"), rural water and sewer districts "special district". The plant's or site's suffix
    ("-North", "(West Plant)", "WWTF") is cut so one owner's plants share one row. OVERRIDES names every owner the rule
    cannot (a facility recorded as permittee, an abbreviation, a typing error in EPA's record), with EPA's own text kept
    in the notes. A city and its public works authority are two bodies and stay two rows, as EPA records them.
  - Tribal permits (the Seneca-Cayuga, Otoe-Missouria, Kickapoo and Chickasaw permits): legal_form "tribal" and the
    channel of a tribal permit; whether DEQ or EPA Region 6 issued each was not read from the permit (two of them are
    not in DEQ's layer). A state's name or permit prefix is not taken as the state's jurisdiction.
  - Federal: the Fort Sill plant, owned and run by a utility company under the Army's utility privatization
    ("investor-owned utility", the installation named). State facilities: the Department of Corrections' prisons.
  - Never an individual's name: every private permittee here is a company, an association or a council.
  - notification_channel: DEQ's municipal permits' standard conditions (Part III, revision of March 2017, B.6) require
    oral notice to DEQ within 24 hours of any collection-system bypass or overflow and a written report in five days;
    DEQ's wastewater reporting page asks for a telephone report within 48 hours and a written one in five days (it also
    says five business days); DEQ Form 605-011 (revised 2025-10-01) asks for 24 hours and five days. No duty to tell
    the public; DEQ publishes no list of the reports; EPA's tables hold no Oklahoma report.
  - Idempotent: a rerun replaces the rows it wrote (state OK, source_areas ["ok"]) and leaves every other row as it is.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
RESEARCH = ROOT / "research" / "ok" / "dischargers.json"
CANDIDATES = ROOT / "research" / "ok" / "private-utilities-candidates.json"
DEQ = ROOT / "data" / "raw" / "ok-deq-gis" / "layer4-rows.json"
CHECKED = "2026-11-14"
PART3 = "https://oklahoma.gov/content/dam/ok/en/deq/documents/water-division/MunyPart3modified_3-17-17.pdf"
# the reporting condition each permit's scope supports (Astra P2-10): DEQ's municipal standard conditions only for a
# permit EPA records as a municipal POTW; a general-permit coverage or any other permit gets the federal condition,
# marked assumed and unverified, since no permit was read
SCOPE_TEXT = {
    "municipal": ("DEQ's municipal permits' standard conditions (Part III, revision of March 2017, section B.6) require "
                  "oral notice to DEQ within 24 hours of becoming aware of any collection-system bypass or overflow and "
                  f"a written report within five days ({PART3}); the permit itself was not read."),
    "general": ("A coverage under DEQ's general permit for small lagoon systems (OKG58); the general permit was not read, "
                "so its reporting condition is not asserted: the 24-hour and five-day reports of 40 CFR 122.41(l)(6), "
                "which OAC 252:606 incorporates, are assumed, unverified."),
    "unresolved": ("EPA does not record a municipal POTW permit here; the permit was not read, so DEQ's municipal "
                   "standard conditions are not asserted: the 24-hour and five-day reports of 40 CFR 122.41(l)(6), "
                   "which OAC 252:606 incorporates, are assumed, unverified."),
}
COMMON = ("DEQ's wastewater reporting page asks for a telephone report within 48 hours of the event and a written "
          "follow-up in five days, and DEQ's bypass form (605-011, revised October 2025) for 24 hours and five days. DEQ "
          "publishes no list of the reports, EPA's overflow tables hold no Oklahoma report (2026-11-12 extract), and no "
          "duty to tell the public was found.")
MUNICIPAL_TYPES = {"Municipal or Water District", "Municipality", "POTW"}
PUBLIC_FORMS = {"city", "town", "authority", "special district", "county", "permit only"}


def permit_scope(permit: str, plant: dict | None, lf: str | None) -> str:
    """'tribal', 'general', 'municipal' or 'unresolved' for one permit, from EPA's record of it and the row's form."""
    if lf == "tribal" or permit in TRIBAL_SCOPE:
        return "tribal"
    if permit.startswith("OKG"):
        return "general"
    if plant and plant.get("facility_type") in MUNICIPAL_TYPES and "POTW" in (plant.get("permit_components") or []) \
            and lf in PUBLIC_FORMS:
        return "municipal"
    return "unresolved"


def scope_text(scopes: dict[str, str]) -> str:
    """The reporting sentences for a row's permits, grouped by scope (each group named when the row mixes scopes)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for p, sc in sorted(scopes.items()):
        groups[sc].append(p)
    if len(groups) == 1:
        return SCOPE_TEXT[next(iter(groups))]
    return " ".join(f"{', '.join(ps)}: {SCOPE_TEXT[sc]}" for sc, ps in groups.items())
TRIBAL = ("A tribal permit: whether DEQ or EPA Region 6 issued it was not read from the permit (EPA, not the state, "
          "administers the Clean Water Act program on tribal land where the state has no authority). Either way the "
          "permit's 24-hour and five-day noncompliance reports go to the issuing agency (40 CFR 122.41(l)(6)), which "
          "publishes no list of them; EPA's overflow tables hold no report under it. No public notice duty was found.")
PRIVATE = (" The permit conditions bind a private or state permittee as they bind a public one.")
OWN = " The operator's own pages were not searched individually."

# permit -> (name, short name or None, legal form, note or None); every owner the ordering rule cannot name
OVERRIDES = {
    "OK0020711": ("Stigler Municipal Improvement Authority", None, "authority",
                  "EPA records no owner name; its facility name is the Authority."),
    "OK0021458": ("Spinnaker Point Homeowners' Association", None, "homeowners' association", None),
    "OK0022870": ("City of Seminole", None, "city", None),
    "OK0022888": ("Mounds Public Works Authority", None, "authority", "EPA records the owner as \"Mounds WTF\"."),
    "OKG580003": ("Mounds Public Works Authority", None, "authority", None),
    "OK0022951": ("Oklahoma Department of Corrections", None, "state facility", None),
    "OKG580069": ("Oklahoma Department of Corrections", None, "state facility", None),
    "OK0026221": ("Tulsa Metropolitan Utility Authority", None, "authority", None),
    "OK0026239": ("Tulsa Metropolitan Utility Authority", None, "authority", "EPA records the owner as \"TMUA\"."),
    "OK0042935": ("Tulsa Metropolitan Utility Authority", None, "authority", None),
    "OK0034363": ("Regional Metropolitan Utility Authority", None, "authority",
                  "EPA records the owner as \"RMUA-Haikey Creek\": the Haikey Creek plant's regional authority (Tulsa, "
                  "Broken Arrow and Bixby, by its name; its members were not read)."),
    "OK0027553": ("Oklahoma City Water Utilities Trust", None, "authority", None),
    "OK0027561": ("Oklahoma City Water Utilities Trust", None, "authority", None),
    "OK0030520": ("City of Oklahoma City", None, "city",
                  "EPA records the owner as \"Oklahoma City, City of- Dunjee Park\"."),
    "OK0036978": ("City of Oklahoma City", None, "city", "EPA records the owner as \"OK City, City of-North Canadian\"."),
    "OK0038385": ("City of Oklahoma City", None, "city", "EPA records the owner as \"OK City, City of-South Canadian\"."),
    "OK0026077": ("Bethany/Warr Acres Public Works Authority", None, "authority", None),
    "OK0026085": ("Del City Municipal Services Authority", None, "authority", None),
    "OK0026972": ("Seminole County Rural Water and Sewer Management District No. 3", None, "special district", None),
    "OK0028291": ("Ottawa County Rural Water District No. 1", None, "special district",
                  "The Wyandotte plant, as EPA records it."),
    "OK0028622": ("Okfuskee County Rural Water District No. 1", None, "special district",
                  "The Boley plant, as EPA records it."),
    "OK0030236": ("City of Seneca, Missouri", "City of Seneca", "city",
                  "EPA records the owner as \"Seneca, City of (Missouri)\": a Missouri city whose plant permit is "
                  "Oklahoma's."),
    "OK0030295": ("American Water (Fort Sill wastewater treatment facility)", "American Water", "investor-owned utility",
                  "EPA records the owner as American Water Enterprises, Inc.: the Army's Fort Sill installation, whose "
                  "utility system a company owns and runs under the Army's utility privatization; EPA types it a "
                  "privately owned facility."),
    "OK0030422": ("City of Ardmore", None, "city", None),
    "OK0038440": ("City of Ardmore", None, "city", "EPA records the facility as \"ARDMORE PWA\"."),
    "OK0034568": ("Oklahoma Ordnance Works Authority", None, "authority",
                  "EPA records the owner as \"OK Ordnance Works Auth/ TSC\" and types it state government."),
    "OK0034754": ("Green Country Sewer Company", None, "investor-owned utility", "The Sunrise plant, as EPA records it."),
    "OK0037664": ("Lone Elm Mobile Home Park", None, "mobile-home park", None),
    "OK0037826": ("Choctaw County Rural Water and Sewer District No. 1", None, "special district",
                  "The Grant plant, as EPA records it."),
    "OK0037834": ("Choctaw Utilities Authority", None, "authority",
                  "The City of Choctaw's (Oklahoma County) authority, as EPA records it; not a tribal body."),
    "OK0037842": ("Stoney Resort", None, "campground or resort", None),
    "OK0037869": ("The Coves Master Association, Inc.", "Coves Master Association", "homeowners' association", None),
    "OK0038032": ("Rogers County Rural Sewer District No. 1", None, "special district", None),
    "OK0038458": ("Bridge Creek Public Schools", None, "special district", "A public school district."),
    "OK0039098": ("Seneca-Cayuga Tribe", None, "tribal",
                  "EPA's name; the tribe is now the Seneca-Cayuga Nation. EPA types the owner a tribal government."),
    "OK0039136": ("Garrett Investment Company, LLC (Holliday Outt mobile home park)", "Holliday Outt MHP",
                  "mobile-home park", None),
    "OK0039128": ("Langley Public Works Authority", None, "authority",
                  "EPA's owner field reads \"Langely PWA\"; the facility field, \"LANGLEY PUBLIC WORKS AUTHORITY\"."),
    "OK0041491": ("Foss Reservoir Master Conservancy District", None, "special district", None),
    "OK0042684": ("Thomas Park, LLC", None, "business or industrial", None),
    "OK0043257": ("Wagoner County Rural Water, Sewer, Gas and Solid Waste Management District No. 4", None,
                  "special district", None),
    "OK0045721": ("Chickasaw Tribal Utilities Authority", None, "tribal", "The WinStar plant, as EPA records it."),
    "OK0045764": ("Indian Nations Council, Boy Scouts of America (Camp Tom Hale)", "Indian Nations Council, BSA",
                  "institution", None),
    "OK0100625": ("Pittsburg County Rural Water District No. 20", None, "special district",
                  "The Carlton Landing plant, as EPA records it."),
    "OK0100927": ("Marshall County Rural Water and Sewer District No. 1", None, "special district",
                  "The Pointe Vista North plant, as EPA records it."),
    "OKG580052": ("Le Flore County Rural Water and Sewer District No. 5", None, "special district", None),
    "OKG580063": ("Haskell County Rural Water District No. 2", None, "special district", None),
    "OKP003097": ("Umicore Optical Materials USA, Inc.", "Umicore Optical Materials", "business or industrial",
                  "EPA records the facility as \"CITY OF QUAPAW POTW\" and the owner as the company; the permit's form "
                  "(OKP) was not read."),
    "OK0043915": ("City of Kendrick", None, "city",
                  "EPA's owner field reads \"KENDRICK, CITY OF\" and its facility field \"KENDRICK, TOWN OF\"."),
    "OK0032387": ("Wright City Public Works Authority", None, "authority",
                  "EPA records the owner as \"Wright City, Town of (PWA)\"."),
    "OK0027154": ("Town of Asher", None, "town", "EPA records the facility as the Asher Utility Development Authority."),
    "OKG580050": ("Town of Whitefield", None, "town", "EPA records the facility as the Whitefield MIA."),
    "OK0035297": ("Canadian Public Works Authority", None, "authority", None),
    "OK0028509": ("Yale Water and Sewage Trust", None, "authority", None),
    "OK0026107": ("City of McAlester", None, "city", None),
    "OK0031798": ("City of Miami", None, "city", "EPA records the owner as \"Miami WWTF-SE Plant\"."),
    "OK0034266": ("City of Lone Grove", None, "city", None),
    "OK0045951": ("City of Newkirk", None, "city", "EPA records the owner as \"Newkirk WTF\"."),
    "OKG580023": ("Bluejacket Public Works Authority", None, "authority", None),
    "OKG580068": ("Town of Gans", None, "town", "EPA records the owner as \"Gans WWTF\"."),
    # private candidates outside the plant list (research/ok/private-utilities-candidates.json)
    "OK0002461": ("Vicinity Energy Tulsa, LLC", None, "business or industrial",
                  "A district energy company's plant; EPA lists a sewerage code (NAICS 221320) among its codes."),
    "OK0034835": ("Permit OK0034835 (permittee not named)", None, "facility (permittee not named)",
                  "EPA's permittee and facility names read as an individual's: not named here."),
    "OK0036081": ("Yale South Corporation (Keystone Manor plant)", "Yale South Corporation", "business or industrial",
                  None),
    "OK0037494": ("Trails End M.H. Parks, Inc.", "Trails End MHP", "mobile-home park", None),
    "OK0037770": ("Harbors Area Association", None, "homeowners' association", None),
    "OK0038016": ("Falls Creek Baptist Conference Center", None, "institution", None),
    "OK0038849": ("Heavener Utilities Authority", None, "authority",
                  "EPA records the industrial park plant (OK0038849, \"Heavener UA-Industrial Park\") as a food "
                  "processor's code (NAICS 311615)."),
}
# permits whose holder EPA does not name (both its owner and facility fields give only a plant): a permit-only row per
# permit, "Permit OK... (<plant>)", permit_only true, legal_form null, left out of operator counts (main's rule,
# scripts/icis_operators.py; Astra P2-9), never named after the plant or an inferred town or tribe
PERMIT_ONLY = {"OKG580038", "OK0066666", "OK0100731", "OK0032417", "OK0032425",   # Avant, Forgan, Minco, Wetumka (2)
               "OK0029190",       # "Norman WWTF" / "Norman Water Reclamation Facility"
               "OKG580062",       # "Sand Springs-Sand Creek WWTF" in both fields
               "OK0044695",       # "Otoe Missouria Treatment Facil" in both fields, EPA type NON-POTW
               "OK0044733",       # "Kickapoo WWTP" in both fields; EPA's collection-system table types the owner tribal
               "OK0037982", "OK0044971"}   # two correctional centers named in both fields (the department not named)
# permits whose scope is tribal by EPA's owner type or the facility's own name: the tribal channel, issuer not read
TRIBAL_SCOPE = {"OK0044695", "OK0044733"}
ABBR = [(r"\bPWA\b", "Public Works Authority"), (r"\bPUA\b", "Public Utilities Authority"),
        (r"\bMUA\b", "Metropolitan Utility Authority"), (r"\bMSA\b", "Municipal Services Authority"),
        (r"\bMIA\b", "Municipal Improvement Authority"), (r"\bMA\b", "Municipal Authority"),
        (r"\bUA\b", "Utilities Authority"), (r"\bPub\.?\s+Works\s+Auth\.?", "Public Works Authority"),
        (r"\bAuth\b\.?", "Authority"), (r"\bCo\.?\s+RWD\s*#?\s*(\d+)", r"County Rural Water District No. \1")]
FACILITY = re.compile(r"\s*(?:\b(?:WWTF|WTF|WWT|WWTP|STP|WDS)\b.*|\(.*\)|\bWastewater\b.*)$", re.I)
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,-")
    words = []
    for w in s.split(" "):
        words.append(w.title() if (w.isupper() and len(w) > 2 and w not in ("RWD", "LLC")) or w.islower() else w)
    s = " ".join(words)
    return re.sub(r"(?<=\w )\b(Of|And|The)\b", lambda m: m.group(1).lower(), s).replace("Mcalester", "McAlester") \
        .replace("Mcloud", "McLoud").replace("Mccurtain", "McCurtain")


def owner(permit: str, permit_name: str | None, permittee: str | None) -> tuple[str, str | None, str | None, str | None]:
    """(name, short, legal_form, note) of the permit's owner."""
    if permit in OVERRIDES:
        return OVERRIDES[permit]
    if permit in PERMIT_ONLY:
        plant = tidy(permittee or permit_name or "")
        return (f"Permit {permit} ({plant})", f"Permit {permit} ({plant})", "permit only",
                f"Permit only: EPA ICIS-NPDES gives only the plant's name as owner (\"{permit_name or permittee}\") "
                f"and facility (\"{permittee or permit_name}\"), not the body that holds the permit; the operator is "
                "not established here, so this row is not counted as an operator.")
    raw = (permit_name or permittee or "").strip()
    s = re.split(r"\s*-\s*|\s+-|-\s+", raw)[0] if re.search(r"-", raw) else raw
    s = FACILITY.sub("", s).strip(" ,")
    m = re.match(r"^(.+?),?\s+(City|Town) of$", s, re.I) or re.match(r"^(.+?),\s*(City|Town) of\b.*$", s, re.I)
    if m:
        return (f"{m.group(2).title()} of {tidy(m.group(1))}", None, m.group(2).lower(), None)
    m = re.match(r"^(City|Town) of\s+(.+)$", s, re.I)
    if m:
        return (f"{m.group(1).title()} of {tidy(m.group(2))}", None, m.group(1).lower(), None)
    for pat, rep in ABBR:
        s = re.sub(pat, rep, s)
    s = tidy(s)
    if re.search(r"\b(Authority|Trust)\b", s):
        return (s, None, "authority", None)
    if re.search(r"\bDistrict\b", s):
        return (s, None, "special district", None)
    raise SystemExit(f"{permit}: no owner rule for {raw!r}: add it to OVERRIDES")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def deq_status(path: Path = DEQ) -> tuple[dict[str, set], bool]:
    if not path.exists():
        return {}, False
    out: dict[str, set] = defaultdict(set)
    for f in json.loads(path.read_text())["features"]:
        a = f["attributes"]
        out[a["NPDESID"]].add(a.get("PermitStatusDesc"))
    return out, True


def channel(lf: str | None, scopes: dict[str, str]) -> str:
    if scopes and all(sc == "tribal" for sc in scopes.values()):
        return TRIBAL
    rest = {p: sc for p, sc in scopes.items() if sc != "tribal"}
    return ("DEQ issues Oklahoma's discharge permits (OPDES). " + scope_text(rest) + " " + COMMON
            + (PRIVATE if lf in PRIVATE_FORMS or lf == "state facility" else "") + OWN)


def build(dis: list[dict], deq_path: Path = DEQ) -> tuple[list[dict], dict]:
    keep = [d for d in dis if not (d.get("state") == "OK" and "ok" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    pl: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "OK" and r.get("npdes_permit"):
            pl[r["npdes_permit"].upper()].append(r)
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand.get("public_by_name", [])}
    permits = sorted(set(pl) | set(cands))
    clash = [p for p in permits if p in held]
    if clash:
        raise SystemExit(f"permits already held by another row: {clash}")
    deq, have_deq = deq_status(deq_path)
    by_row: dict[str, dict] = {}
    for p in permits:
        first = (pl.get(p) or [{}])[0]
        c = cands.get(p) or {}
        name, short, lf, note = owner(p, first.get("permit_name"), first.get("permittee") or c.get("facility"))
        rid = f"ok-permit-{p.lower()}" if lf == "permit only" else f"ok-{slug(short or name)}"
        row = by_row.setdefault(rid, {"name": name, "short": short or name, "lf": lf, "permits": [], "notes": []})
        if row["lf"] != lf:
            raise SystemExit(f"{rid}: legal forms disagree ({row['lf']} and {lf})")
        row["permits"].append(p)
        if note:
            row["notes"].append(note)
    research = {}
    for r in json.loads(RESEARCH.read_text()):
        research[r["id"]] = r
    city_of = {"ok-okc-utilities": "ok-oklahoma-city-water-utilities-trust", "ok-tulsa": "ok-tulsa-metropolitan-utility-authority",
               "ok-broken-arrow": "ok-city-of-broken-arrow", "ok-norman": "ok-permit-ok0029190",
               "ok-lawton": "ok-city-of-lawton", "ok-sulphur": "ok-sulphur-municipal-authority"}
    aliases: dict[str, list[str]] = defaultdict(list)
    for rid in research:
        target = city_of.get(rid)
        if target is None or target not in by_row:
            raise SystemExit(f"research row {rid} has no operator row ({target})")
        aliases[target].append(rid)
    new = []
    for rid, m in by_row.items():
        ps = sorted(m["permits"])
        rows = [r for p in ps for r in pl.get(p, [])]
        towns = sorted({tidy(r["city"]) for r in rows if r.get("city") and "COUNTY" not in r["city"].upper()}
                       | {tidy(cands[p]["city"]) for p in ps if p in cands and cands[p].get("city")})
        waters = list(dict.fromkeys(re.sub(r"^\d{12}_\d{2}\s+", "", r["receiving_water_echo"]).strip()
                                    for r in rows if r.get("receiving_water_echo")))[:8]
        facs = "; ".join(f"{p} {tidy((pl.get(p) or [{}])[0].get('permittee') or (cands.get(p) or {}).get('facility') or '')}"
                         .strip() for p in ps)
        note = f"EPA ICIS-NPDES: {facs}. No report under these permits is in EPA's overflow tables (2026-11-12 extract)."
        if have_deq:
            term = [p for p in ps if deq.get(p) and deq[p] <= {"Terminated"}]
            absent = [p for p in ps if p not in deq]
            if term:
                note += f" DEQ's discharger layer (updated 2026-06-14) marks {', '.join(term)} terminated."
            if absent:
                note += f" DEQ's discharger layer (updated 2026-06-14) does not hold {', '.join(absent)}."
        if m["notes"]:
            note += " " + " ".join(dict.fromkeys(m["notes"]))
        kind = "collection_system" if ps == ["OK0044733"] else "plant"
        scopes = {p: permit_scope(p, (pl.get(p) or [None])[0], m["lf"]) for p in ps}
        po = m["lf"] == "permit only"
        new.append({"id": rid, "name": m["name"], "short_name": m["short"], "legal_form": None if po else m["lf"],
                    **({"permit_only": True} if po else {}), "state": "OK",
                    "kind": "sso" if kind == "collection_system" else "plant", "npdes_permit": ps[0], "npdes_permits": ps,
                    "receiving_waters": waters, "water_slugs": [], "outfall_count": len(rows) or None,
                    "outfalls_source": (f"EPA ICIS-NPDES discharge points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                        if rows else None),
                    "notification_channel": channel(m["lf"], scopes), "notification_feed_machine_readable": False,
                    "notification_signup_url": None, "towns": towns, "notes": note, "verified": "fetched",
                    "checked": CHECKED, "aliases": list(dict.fromkeys([rid] + aliases.get(rid, []))),
                    "source_areas": ["ok"]})
    new.sort(key=lambda r: r["id"])
    ids = Counter(r["id"] for r in keep + new)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate ids: {dup}")
    stats = {"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
             "discharge_points": sum(r["outfall_count"] or 0 for r in new),
             "multi_permit_rows": sum(1 for r in new if len(r["npdes_permits"]) > 1), "deq_layer_read": have_deq,
             "permit_only_rows": sum(1 for r in new if r.get("permit_only")),
             "permit_only_permits": sum(len(r["npdes_permits"]) for r in new if r.get("permit_only")),
             "operators": sum(1 for r in new if not r.get("permit_only")),
             "legal_form": dict(Counter(r["legal_form"] for r in new)), "kind": dict(Counter(r["kind"] for r in new))}
    return keep + new, stats


def main(argv: list[str]) -> int:
    deq = Path(argv[argv.index("--deq") + 1]) if "--deq" in argv else DEQ
    out, stats = build(json.loads(DIS.read_text()), deq)
    print(json.dumps(stats, indent=1))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
