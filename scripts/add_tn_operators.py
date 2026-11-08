"""Tennessee operator rows for data/dischargers.json: one row per operator, every permit in exactly one row.

Usage:
    pipeline/.venv/bin/python -I scripts/add_tn_operators.py [--dry-run] [--review]

Inputs
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's Tennessee treatment-plant permits (399 on 2026-11-07); the owner
     is EPA's permit_name (Tennessee's rows give the permittee there, "City of Cookeville"), except where it names the
     facility ("KNOX CO-GAP CREEK ES", "MONTEAGLE STP"): HAND names the owner of those, read from the names.
  2. data/outfalls-us.json: EPA's National CSO Inventory, Tennessee's three combined-sewer permits (Nashville
     TN0020575, Clarksville TN0020656, Chattanooga TN0024210; 17 open outfalls).
  3. research/tn/dischargers.json (10 rows): the CSO permittees and the large SSO filers of TDEC's Events Report; each
     keeps its research id and receiving waters, and takes the group of its permit's owner.
  4. research/tn/private-utilities-candidates.json (36 private sewage permits and one EPA types private that reads as a
     public body, Grundy County's industrial park): a private permit is grouped by its permittee as EPA records it, with
     legal_form from the candidates file's proposal (docs/legal-forms.md), never an individual's name: a permit whose
     permittee the candidates file removed, or whose name reads as a person's (common.scrub_discharger), is filed under
     its facility, legal form "facility (permittee not named)".
  Names are compared without case, punctuation, a leading "The" or a trailing ", Inc."; ALIASES joins the spellings of
  one body (read from the names on 2026-11-07).
  kind: "cso" for the three CSO permittees, "sso" for an operator the research names as a large SSO filer, else
  "plant" (every Tennessee sewer system files its overflows with TDEC; the table that would say which could not be read
  on 2026-11-07).
Legal form (form()): City of / Metro (Nashville and Davidson County's consolidated government) / a city's utilities
  board, commission, system or department -> city; Town of -> town; a county, its government or its schools ->
  county (Tennessee's county school systems are county departments); a utility district (Tenn. Code Ann. Title 7,
  Chapter 82) or a special sewer district -> special district; an authority created by law (a utilities, water and
  wastewater or energy authority) -> authority; Tennessee departments, state parks, universities -> state facility;
  the Corps of Engineers, the National Park Service, the Forest Service -> federal facility. A private name -> the
  candidates file's proposal, else FORM_BY_NAME.
Rules
  - notification_channel says what Tennessee requires (0400-40-05-.07(2)(o): report to TDEC within 24 hours and in
    writing within five days; no duty to tell the public) and where the reports become public (TDEC's Events Report,
    about five days after the event). No operator sign-up was found: notification_signup_url null.
  - Idempotent: a rerun replaces the rows it wrote (source_areas ["tn"]), puts them after the last row in id order,
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

CHECKED = "2026-11-07"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "tn" / "dischargers.json"
CANDIDATES = ROOT / "research" / "tn" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
REMOVED = NAME_REMOVED

BASE_LAW = ("Tenn. Comp. R. & Regs. 0400-40-05-.07(2)(o): the permittee reports any noncompliance or release that could "
            "threaten human health or the environment to TDEC within 24 hours and in writing within five days (MyTDEC "
            "Forms); 0400-40-05-.07(2)(n)1 prohibits sanitary sewer overflows. No rule requires notice to the public. "
            "TDEC publishes the filed reports in its Division of Water Resources Events Report (dataviewers.tdec.tn.gov), "
            "about five days after the event, with dates, county, city, street and volume but no receiving water.")
PRIVATE_NOTE = " The rule binds every NPDES permittee, public or private."
CSO_NOTE = (" Combined sewer overflows are discharges the permit allows and are not in TDEC's Events Report; no public "
            "notice of a CSO event was found.")
MEMPHIS_NOTE = " The City of Memphis's two plants (TN0020711, TN0020729) have no rows in TDEC's Events Report."

# EPA names that give the facility, not the owner (read by hand from EPA's permit names, 2026-11-07)
HAND_BY_NAME = {
    "BLOUNT CO-FRIENDSVILLE ES": "Blount County Schools",
    "BRADLEY CO-TAYLORS ES": "Bradley County Schools",
    "HAWKINS CO-KEPLAR ES": "Hawkins County Board of Education",
    "HENDERSON CO-SOUTH HAVEN SCH.": "Henderson County Schools",
    "KNOX CO-GAP CREEK ES": "Knox County Schools",
    "KNOX CO-RITTA ES": "Knox County Schools",
    "LINCOLN CO-HIGHLAND RIM SCH": "Lincoln County Department of Education",
    "MCMINN CO-RICEVILLE ES": "McMinn County Board of Education",
    "SEVIER CO-CATON'S CHAPEL ES": "Sevier County Schools",
    "WARREN CO-DIBRELL SCH": "Warren County Schools",
    "WEAKLEY CO-DRESDEN HS": "Weakley County Schools",
    "WEST KNOX UD-KARNS BEAV CR STP": "West Knox Utility District",
    "OAK RIDGE - CLINCH RIVER STP": "City of Oak Ridge",
    "MONTEAGLE STP": "Town of Monteagle",
    "COLLIERVILLE NORTHWEST STP": "Town of Collierville",
    "USA COE D HOL REC AREA A": "U.S. Army Corps of Engineers",
    "TDEC-D.CROCKETT BIRTH S.P. STP": "Tennessee Department of Environment and Conservation",
    "TDEC-PARIS LANDING S.P. STP": "Tennessee Department of Environment and Conservation",
    "TDOC-YOUTH DEV. CENTER STP": "Tennessee Department of Correction",
    "PARROTTSVILLE E SCHL STP": "Cocke County Board of Education",     # Parrottsville Elementary, Cocke County
}
REVIEW = "--review" in sys.argv


def compact(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)                     # "(KUB)", "(WWTA)"
    s = re.sub(r"^\s*the\s+", "", s)
    s = re.sub(r",?\s*(tennessee|tn|inc\.?|llc\.?)\s*$", "", s.strip())
    s = re.sub(r"\bco\.?\b", "county", s)
    return re.sub(r"[^a-z0-9]", "", s)


ALIASES: dict[str, str] = {k: v for v, spellings in {
    "Metro Water Services": ["Metro Water Services (DRY CREEK STP)", "Metro Water Services - Nashville Central STP"],
    "U.S. Army Corps of Engineers": ["U.S. Army Corps of Engineers (USACE)"],
    "National Park Service": ["U.S. Department of the Interior - National Parks Service",
                              "US Department of Interior National Park Service", "USDI - National Parks Service (NPS)"],
    "Sullivan County Schools": ["Sullivan County Board of Education", "Sullivan County Department of Education"],
    "Grainger County Schools": ["Grainger County Board of Education",
                                "Grainger County Board of Education dba Grainger County Schools"],
    "Limestone Water Utility Operating Company, LLC": [
        "Limestone Water Utility Operating Company, formerly IRM Utility, Inc."],
    "Tennessee Department of Environment and Conservation": ["TDEC", "Tennessee State Parks"],
    "Tennessee Department of Correction": ["Tennessee Department of Correction (TDOC)", "Tennessee Department of Corrections"],
    "City of Johnson City": ["Johnson City"],
    "City of Lewisburg": ["Lewisburg Water and Sewer Department"],
    "City of Jefferson City": ["Jefferson City"],
    "Hamilton County Water and Wastewater Treatment Authority": [
        "Hamilton County Water & Wastewater Treatment Authority (WWTA)"],
    "Knoxville Utilities Board": ["Knoxville Utilities Board (KUB)"],
}.items() for k in [compact(x) for x in [v, *spellings]]}
# legal forms the name rules miss or the candidates file proposed wrongly (read from the names, 2026-11-07)
FORM_BY_NAME = {
    "Metro Water Services": "city",
    "Joint Sewerage System": "city",
    "Tellico Area Services System": "authority",
    "Tellico Reservoir Development Agency": "authority",
    "Megasite Authority of West Tennessee": "authority",
    "Berry's Chapel Utility, Inc.": "investor-owned utility",
    "Tennessee Wastewater Systems, Inc.": "investor-owned utility",
    "Uplands Village": "institution",
    "Peninsula, a Division of Parkwest Medical Center": "institution",
    "Pine Lake Cooperative, Inc.": "homeowners' association",
    "Treadway Circle Water and Sewer Trust": "member-owned utility",
    "Maranthony Trust": "business or industrial",
    "CH2M HILL Constructors, Inc.": "business or industrial",
    "Brushy Mountain Group, LLC": "business or industrial",
    "Bill Rice Ranch, Inc.": "institution",
    "SCUS Head Start Programs, Inc. dba Save The Children Head Start": "institution",
    "Middle Tennessee Council, Inc., Boy Scouts of America": "institution",
    "Cumberland Heights Foundation, Inc.": "institution",
    "Lakeshore United Methodist Assembly, Inc.": "institution",
    "Greeneville Sewage, LLC, d/b/a Hampton Carter Commercial Center WWTP": "business or industrial",
    "Crossville Housing Authority": "authority",
    "Bethany Hills Camp STP": "institution",
    "Dumplin Valley Assoc. STP": "homeowners' association",
    "Hendersonville Shop. Ctr. STP": "business or industrial",
    "Mallard Ridge Mobile Estates": "mobile-home park",
    "Pine Grove Mobile Home Park": "mobile-home park",
    "Bays Mountain Park": "city",
    "Cheatham Cnty. Ind. Park STP": "county",
    "Van Buren County Industrial Pk": "county",
    "Chapel Hill S.D. STP": "town",
    "Friendship STP": "city",
    "Northeast Tennessee Regional Recovery Center": "state facility",
}
ABBR = {"llc", "lp", "ii", "iii", "wwtp", "stp", "usa", "u.s.", "us", "tdec", "tdoc", "tdot", "kub", "s.d.", "s.p.",
        "mhc", "rv", "es"}


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
    if re.search(r"^tennessee (department|state)|university|state park|^tdec\b|^tdoc\b", n):
        return "state facility"
    if re.search(r"utility district|utilities district|special sewer district|\bud\b", n):
        return "special district"
    if re.search(r"\bcounty\b.*\b(schools|school system|board of education|department of education)\b", n):
        return "county"
    if re.search(r"\bauthority\b", n):
        return "authority"
    if re.search(r"\bcounty (government|commission)\b|^[\w ]+ county$", n):
        return "county"
    if re.search(r"^town of\b", n):
        return "town"
    if re.search(r"^city of\b|^metro\b|utilities board|utilities commission|utility system|utility department|"
                 r"public utilities|board of public utilities|power, water|light and water|water and sewer department|"
                 r"water commission|^\w+ city$", n):
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
    extra = (CSO_NOTE if cso else "") + (MEMPHIS_NOTE if {"TN0020711", "TN0020729"} & set(permits) else "")
    return BASE_LAW + extra + (PRIVATE_NOTE if private else "")


def row(rid, name, kind, permits, towns, waters, notes, legal_form, outfall_count=None, outfalls_source=None,
        verified="inferred", private=False):
    return {"id": rid, "name": name, "short_name": name, "legal_form": legal_form, "state": "TN",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfall_count,
            "outfalls_source": outfalls_source, "notification_channel": notification(permits, private, kind == "cso"),
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": CHECKED, "aliases": [rid],
            "source_areas": ["tn"]}


PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def person_only(name: str | None) -> bool:
    return bool(name) and scrub_discharger({"discharger_name": name})["discharger_name"] == REMOVED


def inputs():
    pl: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "TN" and r.get("npdes_permit"):
            pl[r["npdes_permit"].upper()].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    doc = json.loads(CSO.read_text())
    for r in (doc["outfalls"] if isinstance(doc, dict) else doc):
        if r.get("state") == "TN" and r.get("npdes_permit") and str(r.get("outfall_status") or "").upper() != "CLOSED":
            cso[r["npdes_permit"].upper()].append(r)
    cand = json.loads(CANDIDATES.read_text())
    return pl, cso, cand


def owner_of(p: str, pl: dict, cands: dict) -> tuple[str | None, str]:
    c = cands.get(p)
    if c and c.get("permittee_as_recorded") == REMOVED:
        return None, "EPA's permittee name reads as an individual's"
    if pl.get(p):
        n = pl[p][0].get("permit_name") or pl[p][0].get("permittee")
        if n in HAND_BY_NAME:
            return HAND_BY_NAME[n], "read by hand from EPA's permit name, which names the facility"
        if person_only(n):
            return None, "EPA's permit name reads as an individual's"
        return n, "EPA ICIS-NPDES permit name"
    if c:
        return c.get("permittee_as_recorded"), "EPA ICIS-NPDES permittee (private-utility candidates)"
    return None, "no name on record"


def build(dis: list[dict]) -> tuple[list[dict], Counter, dict]:
    keep = [d for d in dis if not (d.get("state") == "TN" and "tn" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    pl, cso, cand = inputs()
    cands = {c["npdes_permit"]: c for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"]: c for c in cand["public_by_name"]}
    research = json.loads(RESEARCH.read_text())
    research_permits = {x.strip().upper() for r in research for x in (r.get("npdes_permit") or "").split(";") if x.strip()}
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
            r = next(r for r in research if p in (r.get("npdes_permit") or "").upper())
            name, basis = r["name"], "the research row (TDEC's Events Report)"
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
        rp = [x.strip().upper() for x in (r.get("npdes_permit") or "").split(";") if x.strip()]
        keys = {by_permit[x] for x in rp if x in by_permit}
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
        rid = r["id"] if r else f"tn-{slug(g['name'])}"
        if len(rr) > 1:                                  # one operator, several research rows (Metro Water's plants)
            rid = f"tn-{slug(g['name'])}"
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
    new = [d for d in out if d.get("state") == "TN" and "tn" in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1), f"\nTennessee rows {len(new)}, permits "
          f"{sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
