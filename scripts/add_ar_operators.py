"""Arkansas operator rows for data/dischargers.json: one row per operator, every permit in exactly one row.

Usage:
    pipeline/.venv/bin/python -I scripts/add_ar_operators.py [--dry-run] [--review]

Inputs
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's Arkansas treatment-plant permits (400 on 2026-11-14); the owner is
     read from EPA's permit_name (owner_name: "Pea Ridge, City of - Pea Ridge Wastewater Treatment Plant" is the City
     of Pea Ridge; "Conway Corporation - Tucker Creek WWTP" is Conway Corporation), except where HAND names it (a
     name that gives the plant, or one body under several spellings, read from the names on 2026-11-14).
  2. data/outfalls-us.json: EPA's National CSO Inventory has no Arkansas permit (no combined sewers).
  3. research/ar/dischargers.json (9 rows): the large SSO filers of DEQ's incident search; each keeps its research id
     and receiving waters and takes the group of its permit's owner. Little Rock Water Reclamation Authority's permits
     are corrected from its 2023 SSO response plan: Adams Field AR0021806, Fourche Creek AR0040177, Little Maumelle
     AR0050849 (the research row's AR0021768 is Russellville's). Rows the research left without a permit are joined
     by RESEARCH_PERMITS (the permits EPA lists for that operator's town and name).
  4. research/ar/private-utilities-candidates.json (13 private sewage permits and two EPA types private that read as
     public bodies): a private permit is grouped by its permittee as EPA records it, with legal_form from the
     candidates file's proposal (docs/legal-forms.md), never an individual's name: a permit whose permittee the
     candidates file removed, or whose name reads as a person's (common.scrub_discharger), is filed under its
     facility, legal form "facility (permittee not named)".
  Names are compared without case, punctuation, a leading "The" or a trailing ", Inc."; ALIASES joins the spellings of
  one body.
  kind: "sso" for an operator the research names as a large SSO filer, else "plant" (Arkansas has no combined sewers;
  every permittee files its overflows with DEQ).
Legal form (form()): City of / a city's utilities, water and light, board of public utilities or water and sewer
  commission / Conway Corporation (the City of Conway's utility corporation) -> city; Town of -> town; a county ->
  county; an improvement district, sewer or regional wastewater district, public facilities board or public water
  authority (Ark. Code Ann. Title 14, Subtitles 5 and 6) -> special district; an authority created by law (Little Rock
  Water Reclamation Authority, Central Arkansas Water, the Northwest Arkansas Conservation Authority) -> authority;
  Arkansas departments, commissions and universities -> state facility; the Corps of Engineers -> federal facility. A
  private name -> the candidates file's proposal, else FORM_BY_NAME.
Rules
  - notification_channel says what Arkansas requires (the permits' Part II as DEQ states it: report every SSO, "no
    matter how small", every unanticipated bypass, upset and unpermitted discharge to DEQ within 24 hours and in most
    cases in writing within five days; no duty to tell the public) and where the reports become public (DEQ's
    Reported Noncompliance Incident Data search, current to the previous day). No operator sign-up was found:
    notification_signup_url null.
  - Idempotent: a rerun replaces the rows it wrote (source_areas ["ar"]), puts them after the last row in id order,
    and leaves every other row as it is.
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

CHECKED = "2026-11-14"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "ar" / "dischargers.json"
CANDIDATES = ROOT / "research" / "ar" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
REMOVED = NAME_REMOVED

BASE_LAW = ("Arkansas NPDES permits, Part II, as the Division of Environmental Quality states them: the permittee reports "
            "any noncompliance that may endanger health or the environment to DEQ within 24 hours of becoming aware of "
            "it and, in most cases, in writing within five days, including “Any Sanitary Sewer Overflow (SSO), no "
            "matter how small”, any unanticipated bypass, any upset and any unpermitted discharge, whether or not "
            "it reaches water, on DEQ's 24-hour online forms. No rule requires notice to the public. DEQ publishes the "
            "filed reports in its Reported Noncompliance Incident Data search (adeq.state.ar.us), current to the "
            "previous day, with dates, volume and the filer's impact but no receiving water or coordinates.")
PRIVATE_NOTE = " The rule binds every NPDES permittee, public or private."
LRWRA_NOTE = (" Little Rock Water Reclamation Authority's SSO response plan (2023), from its settlement, provides for "
              "warning signs and public notification at overflows.")

# EPA names that give the facility, or one body under several names (read from EPA's permit names, 2026-11-14)
HAND_BY_PERMIT = {
    "AR0021806": "Little Rock Water Reclamation Authority",
    "AR0040177": "Little Rock Water Reclamation Authority",
    "AR0050849": "Little Rock Water Reclamation Authority",
    "AR0020303": "North Little Rock Wastewater Utility",
    "AR0020320": "North Little Rock Wastewater Utility",
    "AR0033626": "North Little Rock Wastewater Utility",
    "AR0038288": "North Little Rock Wastewater Utility",
    "AR0021768": "Russellville Water and Sewer System",
    "AR0033545": "Cities of Cotter and Gassville",
    "AR0034401": "Fairfield Bay Wastewater Corporation",
    "AR0037907": "City Water and Light of Jonesboro",
    "AR0043401": "City Water and Light of Jonesboro",
    "AR0048615": "Lake Catherine Water and Sewer Facilities Board of Garland County",
    "AR0035742": "City of Judsonia",
    "ARG550457": "Arkansas Department of Transportation",
    "AR0053210": "Pulaski County Property Owners Multipurpose Improvement District No. 2021-2",
    "AR0050181": "St. Joseph's Utility Operating Company, LLC",
    "AR0044580": "Fairfield Bay Wastewater Corporation",
    # Conway Corporation runs the City of Conway's utilities: filed with the City's own plant (AR0033359)
    "AR0047279": "City of Conway (Conway Corporation)",
    "AR0051951": "City of Conway (Conway Corporation)",
}
REVIEW = "--review" in sys.argv
# research rows the research left without a permit: their permits by EPA's names and towns (2026-11-14)
RESEARCH_PERMITS = {"ar-lrwra": ["AR0021806", "AR0040177", "AR0050849"]}


def compact(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"^\s*the\s+", "", s)
    s = re.sub(r",?\s*(arkansas|ar|inc\.?|llc\.?)\s*$", "", s.strip())
    s = re.sub(r"\bco\.?\b", "county", s)
    return re.sub(r"[^a-z0-9]", "", s)


ALIASES: dict[str, str] = {k: v for v, spellings in {
    "U.S. Army Corps of Engineers": ["U.S. Army Corps of Engineers-White Cliffs-Saratoga Park",
                                     "U.S. Army Corps of Engineers-White Cliffs-Restroom A",
                                     "U.S. Army Corps of Engineers-White Cliffs-Shower B", "USA-COE"],
    "Arkansas Game and Fish Commission": ["Arkansas Game & Fish Commission"],
    "Little Rock Water Reclamation Authority": ["LITTLE ROCK WATER RECLAMATION AUTHORITY"],
    "City Water and Light of Jonesboro": ["City Water and Light, Jonesboro"],
}.items() for k in [compact(x) for x in [v, *spellings]]}
FORM_BY_NAME = {
    "Central Arkansas Water": "authority",
    "Little Rock Water Reclamation Authority": "authority",
    "Northwest Arkansas Conservation Authority": "authority",
    "City Water and Light of Jonesboro": "city",
    "Russellville Water and Sewer System": "city",
    "North Little Rock Wastewater Utility": "city",
    "Fairfield Bay Wastewater Corporation": "business or industrial",
    "Tri-City Utilities, Inc.": "investor-owned utility",
    "Chito Properties, LLC": "business or industrial",
    "Vanndale - Birdeye Water Association": "member-owned utility",
    "Cities of Cotter and Gassville": "city",
    "Sugarloaf Waste Water Treatment": None,
    "Montrose Waste Water Facilities": "city",
    "Arkansas Department of Transportation": "state facility",
}


def owner_name(epa: str) -> str:
    """EPA's permit name -> the owner: "Pea Ridge, City of - Pea Ridge WWTP" -> "City of Pea Ridge";
    "VAN BUREN, CITY OF-MAIN PLANT" -> "City of Van Buren"; "Conway Corporation - Tucker Creek WWTP" -> "Conway
    Corporation"."""
    s = " ".join((epa or "").split()).strip(" ,")
    m = re.match(r"^(.+?),\s*(city|town)(?:\s+of)?\b", s, re.I)
    if m:
        town = m.group(1).strip()
        if town.isupper():
            town = re.sub(r"\bMc(\w)", lambda x: "Mc" + x.group(1).upper(), town.title())
        return f"{m.group(2).title()} of {town}"
    return re.split(r"\s+-\s*|\s*-\s+", s, maxsplit=1)[0].strip(" ,")


ABBR = {"llc", "lp", "ii", "iii", "wwtp", "wwtf", "usa", "u.s.", "us", "sid", "poid", "ahtd", "p.f.b.", "pfb", "rv",
        "ww", "wwt", "h.a.c.t.", "poa", "hepoa"}


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").split()):
        bare = re.sub(r"[^A-Za-z.]", "", w).lower()
        if bare in ABBR:
            out.append(w.upper())
        elif bare in ("of", "and", "the", "for") and i:
            out.append(bare)
        else:
            out.append(re.sub(r"(?<=\w)'S\b", "'s", w.title()) if w.isupper() or w.islower() else w)
    s = " ".join(out)
    return re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), s)


def tidy(name: str) -> str:
    s = " ".join((name or "").split()).strip(" ,")
    s = re.sub(r"^The\s+", "", s)
    s = re.sub(r"\s*\((?:AUB|CUA|ESCUD|FPU|JEA|M\.U\.D\.|NETRRC|RWSG|TDOC|TDOT|TRDA|WBUD|WKUD|NPS|USACE|USDA)\)", "", s)
    if s.isupper() or s.islower():
        s = smart_title(s)
    return s


def form(name: str, facility_type: str | None) -> str | None:
    n = name.lower()
    if re.search(r"army corps|national park|forest service|^u\.?s\.? |united states|federal", n):
        return "federal facility"
    if re.search(r"^arkansas (department|game|state)|university|state park|^ahtd\b", n):
        return "state facility"
    if re.search(r"improvement dist|\bsid\b|sewer district|wastewater (treatment )?district|regional wastewater|"
                 r"water distribution district|\bpoid\b|facilities board|facility board|\bp\.?f\.?b\.?|"
                 r"public water authority|sewer facilities|treatment board|\bwwt dist", n):
        return "special district"
    if re.search(r"\bauthority\b", n):
        return "authority"
    if re.search(r"\bcounty (government|commission)\b|^[\w ]+ county$", n):
        return "county"
    if re.search(r"^town of\b", n):
        return "town"
    if re.search(r"^cit(y|ies) of\b|utilities board|utilities commission|utility system|utility department|"
                 r"public utilities|board of public utilities|light and water|water and light|water and sewer|"
                 r"water & sewer|wastewater commission|water commission|water utilities|wastewater utility|"
                 r"^\w+ utilities$|^\w+ city$", n):
        return "city"
    if re.search(r"\b(llc|inc|corp|corporation|company|l\.p\.|lp)\b", n):
        return None
    if facility_type in ("Municipality", "Municipal or Water District", "POTW"):
        return "city"
    if facility_type == "County Government":
        return "county"
    return None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def notification(permits: list[str], private: bool, cso: bool) -> str:
    extra = LRWRA_NOTE if "AR0021806" in permits else ""
    return BASE_LAW + extra + (PRIVATE_NOTE if private else "")


def row(rid, name, kind, permits, towns, waters, notes, legal_form, outfall_count=None, outfalls_source=None,
        verified="inferred", private=False):
    return {"id": rid, "name": name, "short_name": name, "legal_form": legal_form, "state": "AR",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfall_count,
            "outfalls_source": outfalls_source, "notification_channel": notification(permits, private, kind == "cso"),
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": CHECKED, "aliases": [rid],
            "source_areas": ["ar"]}


PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def person_only(name: str | None) -> bool:
    return bool(name) and scrub_discharger({"discharger_name": name})["discharger_name"] == REMOVED


def inputs():
    pl: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "AR" and r.get("npdes_permit"):
            pl[r["npdes_permit"].upper()].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    doc = json.loads(CSO.read_text())
    for r in (doc["outfalls"] if isinstance(doc, dict) else doc):
        if r.get("state") == "AR" and r.get("npdes_permit") and str(r.get("outfall_status") or "").upper() != "CLOSED":
            cso[r["npdes_permit"].upper()].append(r)
    cand = json.loads(CANDIDATES.read_text())
    return pl, cso, cand


def owner_of(p: str, pl: dict, cands: dict) -> tuple[str | None, str]:
    c = cands.get(p)
    if c and c.get("permittee_as_recorded") == REMOVED:
        return None, "EPA's permittee name reads as an individual's"
    if p in HAND_BY_PERMIT:
        return HAND_BY_PERMIT[p], "read by hand from EPA's permit names"
    if pl.get(p):
        n = pl[p][0].get("permit_name") or pl[p][0].get("permittee")
        if person_only(n):
            return None, "EPA's permit name reads as an individual's"
        return owner_name(n), "EPA ICIS-NPDES permit name"
    if c:
        return owner_name(c.get("permittee_as_recorded")), "EPA ICIS-NPDES permittee (private-utility candidates)"
    return None, "no name on record"


def build(dis: list[dict]) -> tuple[list[dict], Counter, dict]:
    keep = [d for d in dis if not (d.get("state") == "AR" and "ar" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    pl, cso, cand = inputs()
    cands = {c["npdes_permit"]: c for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"]: c for c in cand["public_by_name"]}
    research = json.loads(RESEARCH.read_text())
    def rperm(r):
        return RESEARCH_PERMITS.get(r["id"]) or [x.strip().upper() for x in (r.get("npdes_permit") or "").split(";")
                                                 if x.strip()]
    research_permits = {x for r in research for x in rperm(r)}
    counts = Counter()
    groups: dict[str, dict] = {}
    perms = sorted(set(pl) | set(cso) | set(cands) | set(public_by_name) | research_permits)
    for p in perms:
        if p in held:
            continue
        name, basis = owner_of(p, pl, {**cands, **public_by_name})
        if name is None and p in cso:
            name, basis = cso[p][0].get("permittee"), "EPA National CSO Inventory permittee"
        if name is None and p in research_permits:
            r = next(r for r in research if p in rperm(r))
            name, basis = r["name"], "the research row (DEQ's incident search)"
        ft = pl[p][0].get("facility_type") if pl.get(p) else None
        private_c = cands.get(p)
        if name is None:
            c = private_c or {}
            fac = c.get("facility") if c.get("facility") not in (None, REMOVED) else None
            if fac:     # a former name may be a person's ("... - FORMERLY <a name> CENTER"): never kept
                fac = re.sub(r"\s*[-,(]?\s*formerly\b.*$", "", fac, flags=re.I).strip(" -,") or None
            if fac and person_only(fac):
                fac = None
            key = f"withheld:{p}"
            g = groups.setdefault(key, {"name": (f"{tidy(fac)} (permit {p})" if fac else f"Sewage plant, permit {p}"),
                                        "legal_form": "facility (permittee not named)", "basis": basis, "permits": [],
                                        "private": True, "research": None})
            g["permits"].append(p)
            continue
        disp = tidy(name)
        disp = ALIASES.get(compact(disp), disp)
        k = compact(disp)
        lf = form(disp, ft)
        private = False
        if private_c and p not in public_by_name and lf not in PUBLIC_FORMS:
            lf = private_c.get("legal_form_proposed") if private_c.get("legal_form_proposed") in PRIVATE_FORMS else None
            private = True
        g = groups.setdefault(k, {"name": disp, "legal_form": lf, "basis": basis, "permits": [], "private": private,
                                  "research": None})
        g["permits"].append(p)
        if g["legal_form"] is None and lf:
            g["legal_form"] = lf
        g["private"] = g["private"] or private
        if p in public_by_name:
            counts["public bodies EPA types private"] += 1

    by_permit = {p: k for k, g in groups.items() for p in g["permits"]}
    for r in research:
        rp = rperm(r)
        keys = {by_permit[x] for x in rp if x in by_permit}
        if not rp:                                  # a research row with no permit: joined by its town's operator
            keys = {k for k, g in groups.items() if r["towns"] and re.search(
                rf"\b{re.escape(r['towns'][0])}\b", g["name"], re.I)}
            keys = {k for k in keys if not re.search(r"\bnorth\b", groups[k]["name"], re.I)
                    or re.search(r"\bnorth\b", r["towns"][0], re.I)}
        if len(keys) != 1:
            if REVIEW:
                print(f"!! {r['id']}: its permits read as {keys or 'no owner'}")
                continue
            raise SystemExit(f"{r['id']}: its permits read as {keys or 'no owner'}")
        k = keys.pop()
        groups[k].setdefault("research_rows", []).append(r)

    new = []
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["name"].lower()):
        ps = list(dict.fromkeys(g["permits"]))
        rr = g.get("research_rows") or []
        r = rr[0] if rr else None
        rows = [x for p in ps for x in pl.get(p, [])]
        csos = [x for p in ps for x in cso.get(p, [])]
        rid = r["id"] if r else f"ar-{slug(g['name'])}"
        if len(rr) > 1:                                  # one operator, several research rows (Metro Water's plants)
            rid = f"ar-{slug(g['name'])}"
        if rid in ids:
            rid = f"{rid}-{ps[0].lower()}"
        withheld = g["legal_form"] == "facility (permittee not named)"
        facs = sorted({f"{tidy(x.get('permittee') or '')} ({x['npdes_permit']})" for x in rows
                       if x.get("permittee") and not withheld and not person_only(x.get("permittee"))})
        waters = list(dict.fromkeys([*[w for x in rr for w in x.get("receiving_waters") or []],
                                     *[x["receiving_water_echo"] for x in csos + rows if x.get("receiving_water_echo")],
                                     *[w for p in ps for w in (cands.get(p) or {}).get("receiving_waters_echo") or []]]))[:8]
        towns = list(dict.fromkeys([*[t for x in rr for t in x.get("towns") or []],
                                    *sorted({smart_title(x["city"]) for x in rows if x.get("city")}
                                            | {smart_title(c["city"]) for p in ps for c in [cands.get(p) or {}]
                                               if c.get("city") and not withheld})]))
        notes = f"Owner: {g['basis']}."
        if facs:
            notes += " Plants and systems: " + ", ".join(facs[:12]) + ("." if len(facs) <= 12 else f", and {len(facs) - 12} more.")
        if withheld:
            notes = "The permittee's name reads as an individual's: not named here; the row names the facility. " + notes
        for x in rr:
            if x.get("notes"):
                notes += " " + x["notes"]
        lf = FORM_BY_NAME.get(g["name"], g["legal_form"])
        private = (g["private"] and lf not in PUBLIC_FORMS) or lf in PRIVATE_FORMS
        kind = "cso" if csos else ("sso" if rr else "plant")
        nr = row(rid, g["name"], kind, ps, towns, waters, notes.strip(), lf,
                 outfall_count=(len(csos) if csos else (len(rows) or None)),
                 outfalls_source=(f"EPA National CSO Inventory (data/outfalls-us.json, {len(csos)} open CSO outfalls)"
                                  if csos else f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, "
                                               f"{len(rows)} rows)" if rows else None),
                 verified=(r.get("verified") if r else "fetched"), private=private)
        for x in rr:
            if x["id"] not in nr["aliases"]:
                nr["aliases"].append(x["id"])
        new.append(nr)
        ids.add(rid)
        counts["research rows" if rr else ("private rows" if private else "public rows")] += 1
    new.sort(key=lambda r: r["id"])
    allp = [p for r in new for p in r["npdes_permits"]]
    dup = [p for p, c in Counter(allp).items() if c > 1]
    if dup:
        raise SystemExit(f"permits in two rows: {dup}")
    return keep + new, counts, groups


def review(groups: dict) -> None:
    by = defaultdict(list)
    for k, g in groups.items():
        m = re.search(r"\b(?:City|Town) of (?:the )?([A-Z][\w.' -]+?)(?:\s+(?:Water|Utilities|Sewer|,|$)|$)", g["name"])
        w = (m.group(1) if m else g["name"].split()[0]).lower()
        by[w].append(f"{g['name']} [{g['legal_form']}] {g['permits']}")
    for w, gs in sorted(by.items()):
        if len(gs) > 1 and w not in ("the", "city", "town"):
            print(w, "\n   " + "\n   ".join(gs))


def main(argv) -> int:
    dis = json.loads(DIS.read_text())
    out, counts, groups = build(dis)
    if "--review" in argv:
        review(groups)
    new = [d for d in out if d.get("state") == "AR" and "ar" in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1), f"\nArkansas rows {len(new)}, permits "
          f"{sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
