"""Alabama operator rows for data/dischargers.json: one row per operator, every permit in exactly one row.

Usage (after scripts/al_reference_files.py has written data/reference/al-adem-sso-permits.json):
    pipeline/.venv/bin/python -I scripts/add_al_operators.py [--dry-run] [--review]

Inputs
  1. data/reference/al-adem-sso-permits.json: every permit in ADEM's SSO report layer with the permittee names ADEM
     gives (newest first). The owner of such a permit is ADEM's newest name for it: the state's own record of who holds
     the permit today.
  2. data/outfalls-plants-us.json: EPA ICIS-NPDES's Alabama treatment-plant permits; the owner is EPA's permit_name
     (EPA's permittee field holds the facility's name in Alabama's rows). A few EPA names give the facility after the
     place ("ENTERPRISE CITY OF S E LAGOON"): the place is read before "CITY OF", and HAND names the rest.
  3. research/al/dischargers.json (11 rows): the largest SSO filers and two large systems; each keeps its research id
     and receiving waters, and takes the group of its permits' owner.
  4. research/al/private-utilities-candidates.json (136 private sewage permits and 3 EPA types private that read as
     public bodies): a private permit is grouped by its permittee as ADEM names it (else as EPA records it), with
     legal_form from the candidates file's proposal (docs/legal-forms.md), never an individual's name: a permit whose
     permittee the candidates file removed, or ADEM's layer read as a person's, is filed under its facility, legal
     form "facility (permittee not named)".
  Names are compared without case, punctuation, a leading "The", a trailing ", AL" or ", Inc."; ALIASES joins the
  spellings of one body (read from the names on 2026-11-07: "Jefferson County Commission Environmental Services
  Department" is the Jefferson County Commission's department).
  kind: "sso" for an operator with a permit in ADEM's SSO layer, else "plant".
Legal form (form()): City of / Town of; a county commission or county government; Alabama's municipal utility boards,
  water works and sewer boards and water, sewer and fire protection authorities are public corporations (Ala. Code
  Title 11, Chapter 50 (municipal water, sewer and gas boards) and Chapter 88 (water, sewer
  and fire protection authorities)) -> authority; a district -> special district; a county board of
  education -> special district (a public school district); Alabama departments, universities, state parks -> state
  facility; the U.S. Army Corps of Engineers and other federal bodies -> federal facility; EPA's municipal facility
  type with no other form -> city. A private name -> the candidates file's proposal.
Rules
  - notification_channel says what Alabama requires (r. 335-6-6-.12(l)6.(v): report to ADEM, the public, the county
    health department and affected water systems as soon as possible; ADEM's form: 24 hours, a 5-day follow-up; no
    channel set for the public notice) and where the reports become public (ADEM's SSO map and layer, minutes after
    filing). notification_signup_url: ADEM's county e-mail list is the state's (no operator sign-up was found except
    Jefferson County's Everbridge alerts, whose page was not read: null).
  - Idempotent: a rerun replaces the rows it wrote (source_areas ["al"]), puts them after the last row in id order,
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
CHECKED = "2026-11-07"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "al" / "dischargers.json"
CANDIDATES = ROOT / "research" / "al" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
ADEM = ROOT / "data" / "reference" / "al-adem-sso-permits.json"
REMOVED = "[name removed]"

BASE_LAW = ("Ala. Admin. Code r. 335-6-6-.12(l)6.(v): the permittee reports a notifiable sanitary sewer overflow (one that "
            "reaches a surface water or may endanger health) to ADEM, the public, the county health department and "
            "affected water systems as soon as possible; ADEM's reporting form sets 24 hours and a written follow-up "
            "within 5 days through AEPACS. The rule sets no channel or content for the public notice. ADEM posts every "
            "report on its public SSO map and layer within minutes of filing.")
PRIVATE_NOTE = " The rule binds every NPDES permittee, public or private."
JEFFERSON_NOTE = (" Jefferson County also sends opt-in overflow alerts (Everbridge, since 2021) and no-contact advisories "
                  "(GovDelivery); the sign-up page was not read.")
MAWSS_NOTE = " MAWSS also posts each overflow as a news item on its website (not read one by one)."

# EPA names that give the facility, not the owner (read by hand from EPA's permit names, 2026-11-07)
HAND = {
    "AL0022632": "Utilities Board of the City of Bayou La Batre",
    "AL0023205": "Water Works and Sewer Board of the City of Prichard",
    "AL0044644": "Limestone County Water and Sewer Authority",       # 'PINEY CHAPEL SCH WWTP LCWSA'
    "AL0072443": "Limestone County Water and Sewer Authority",       # 'CREEKSIDE ELEM SCH WWTP LCWSA'
    "AL0050920": "Colbert County Board of Education",                 # 'COLBERT CO BOE COLBERT HGTS SC'
    "AL0051799": "Winston County Board of Education",                 # 'WINSTON CO BOE MEEK HIGH SCHOL'
    "AL0051802": "Winston County Board of Education",
    "AL0061581": "Moody Governmental Utility Services Corporation",   # 'Moody GUSC'
}
REVIEW = "--review" in sys.argv


def compact(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"^\s*the\s+", "", s)
    s = re.sub(r",?\s*(alabama|al|inc\.?)\s*$", "", s.strip())
    s = re.sub(r",?\s*(alabama|al|inc\.?)\s*$", "", s.strip())
    s = re.sub(r"\bco\.?\b", "county", s)
    s = re.sub(r"\bwaterworks\b", "water works", s)
    return re.sub(r"[^a-z0-9]", "", s)


# one body, several spellings: compact key -> the name the row takes
ALIASES: dict[str, str] = {k: v for v, spellings in {
    "Water Works and Sewer Board of the City of Aliceville": ["Water and Sewer Board of the City of Aliceville",
                                                              "Water Works & Sewer Board of the City of Aliceville"],
    "Baldwin County Sewer Service, LLC": ["Baldwin County Sewer Services", "Baldwin County Sewer Service, LLC"],
    "Water Works, Sewer, and Gas Board of the City of Childersburg": ["Childersburg Water Works, Sewer, and Gas Board"],
    "Water Works and Sewer Board of the City of Daleville": ["Daleville Water and Sewer Board"],
    "City of Huntsville": ["City of Huntsville Water Pollution Control", "City Of Huntsville Water Pollution Control"],
    "Montgomery Water Works and Sanitary Sewer Board": ["Montgomery Water Works & Sanitary Sewer Board",
                                                        "Water Works & Sanitary Sewer Board of the City of Montgomery"],
    "City of Talladega": ["City of Talladega Water & Environmental Services"],
    # MAWSS is the trade name of the Board of Water and Sewer Commissioners of the City of Mobile
    "Mobile Area Water and Sewer System": ["Board of Water and Sewer Commissioners of The City of Mobile"],
}.items() for k in [compact(x) for x in [v, *spellings]]}
# legal forms the name rules miss or the candidates file proposed wrongly (read from the names, 2026-11-07)
FORM_BY_NAME = {
    "Mobile Area Water and Sewer System": "authority",
    "Moody Governmental Utility Services Corporation": "authority",
    "SWWC Services, Inc.": "investor-owned utility",
    "SWWC Utilities, Inc.": "investor-owned utility",
    "Community Utilities of Alabama Inc.": "investor-owned utility",
    "Enviro Management Co": "business or industrial",
    "Alabama 4-H Center": "state facility",
    "5020 Engineering Resource Group Incorporated": "business or industrial",
    "Absolute Environmental Disposal, LLC": "investor-owned utility",
    "Arbor Utility Management, LLC": "investor-owned utility",
    "Corex Utilities Inc.": "investor-owned utility",
    "Pinnacle Wastewater Systems, LLC": "investor-owned utility",
    "South Alabama Utility Service, INC WWTP": "investor-owned utility",
    "Harbor Pointe Utilities LLC": "investor-owned utility",
    "Phoenix Water Resources, LLC": "investor-owned utility",
    "Asset Management Professionals, LLC": "business or industrial",
    "StructCon, LLC": "business or industrial",
    "IMS Development, LLC": "business or industrial",
    "Matthews Landing, Inc": "business or industrial",
    "Hillwood Limited d/b/a Hillwood Apartments": "business or industrial",
    "Tensaw Island Landowners Association": "homeowners' association",
    "Community Action Agency": "institution",
}
ABBR = {"llc", "lp", "ii", "iii", "wwtp", "wsa", "boe", "usa", "u.s.", "us", "mawss", "swwc", "tva", "dcnr", "aum"}


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
    """A display name: spaces collapsed, a leading 'The' and a trailing ', AL' dropped, EPA's 'X CITY OF ...' read."""
    s = " ".join((name or "").split()).strip(" ,")
    m = re.match(r"^([A-Z .'-]+?) CITY OF\b", s)
    if m and s.isupper():
        return f"City of {smart_title(m.group(1))}"
    s = re.sub(r"^The\s+", "", s)
    s = re.sub(r",?\s*(Alabama|AL)\.?$", "", s).strip(" ,")
    if s.isupper() or s.islower():
        s = smart_title(s)
    s = re.sub(r"\bOf\b", "of", re.sub(r"\bAnd\b", "and", s[0].upper() + s[1:])) if s else s
    return s


def form(name: str, facility_type: str | None) -> str | None:
    n = name.lower()
    if re.search(r"army corps|u\.? ?s\.? |united states|national park|federal|tennessee valley authority", n):
        return "federal facility"
    if re.search(r"^alabama (department|state)|university|state park|department of (corrections|conservation|"
                 r"transportation)|community college", n):
        return "state facility"
    if re.search(r"board of education|school district", n):
        return "special district"
    if re.search(r"\bdistrict\b", n):
        return "special district"
    if re.search(r"housing authority|industrial development authority", n):
        return "authority"
    if re.search(r"\b(utilities|utility|water works|waterworks|sewer|water|gas)\b.*\b(board|authority|commission)\b|"
                 r"\bboard of (water|sewer)|\bsewer authority\b|\bwater authority\b|\butilities board\b|"
                 r"\bsewer board\b", n):
        return "authority"
    if re.search(r"\bcounty (commission|government)\b|\bcounty sheriff|sheriff's", n):
        return "county"
    if re.search(r"^town of\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity of\b|\bdepartment of public utilities\b", n):
        return "city"
    if re.search(r"\b(llc|inc|corp|corporation|company|l\.p\.)\b", n):
        return None                               # private: the candidates file decides
    if facility_type in ("Municipality", "Municipal or Water District", "POTW"):
        return "authority" if re.search(r"\butilities\b", n) else "city"
    if facility_type == "County Government":
        return "county"
    return None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def notification(rid: str, private: bool) -> str:
    extra = JEFFERSON_NOTE if rid == "al-jefferson-county" else MAWSS_NOTE if rid == "al-mawss" else ""
    return BASE_LAW + extra + (PRIVATE_NOTE if private else "")


def row(rid, name, kind, permits, towns, waters, notes, legal_form, outfall_count=None, outfalls_source=None,
        verified="inferred", private=False):
    return {"id": rid, "name": name, "short_name": name, "legal_form": legal_form, "state": "AL",
            "kind": kind, "npdes_permit": permits[0] if permits else None, "npdes_permits": list(permits),
            "receiving_waters": waters, "water_slugs": [], "outfall_count": outfall_count,
            "outfalls_source": outfalls_source, "notification_channel": notification(rid, private),
            "notification_feed_machine_readable": True, "notification_signup_url": None,
            "towns": towns, "notes": notes, "verified": verified, "checked": CHECKED, "aliases": [rid],
            "source_areas": ["al"]}


PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def inputs():
    adem = json.loads(ADEM.read_text())["permits"]
    pl: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "AL" and r.get("npdes_permit"):
            pl[r["npdes_permit"].upper()].append(r)
    cand = json.loads(CANDIDATES.read_text())
    return adem, pl, cand


def owner_of(p: str, adem: dict, pl: dict, cands: dict) -> tuple[str | None, str]:
    """(owner name, basis); None when the only name is withheld (a person's)."""
    if p in HAND:
        return HAND[p], "read by hand from EPA's permit name (HAND)"
    a = (adem.get(p) or {}).get("permittees") or []
    if a:
        return a[0]["name"], "ADEM's SSO report layer (the permittee on the permit's newest report)"
    c = cands.get(p)
    if c and c.get("permittee_as_recorded") == REMOVED:
        return None, "EPA's permittee name reads as an individual's"
    if pl.get(p):
        return pl[p][0].get("permit_name") or pl[p][0].get("permittee"), "EPA ICIS-NPDES permit name"
    if c:
        return c.get("permittee_as_recorded"), "EPA ICIS-NPDES permittee (private-utility candidates)"
    return None, "no name on record"


def build(dis: list[dict]) -> tuple[list[dict], Counter, dict]:
    keep = [d for d in dis if not (d.get("state") == "AL" and "al" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    adem, pl, cand = inputs()
    cands = {c["npdes_permit"]: c for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"]: c for c in cand["public_by_name"]}
    counts = Counter()
    groups: dict[str, dict] = {}
    perms = sorted(set(adem) | set(pl) | set(cands) | set(public_by_name))
    for p in perms:
        if p in held:
            continue
        name, basis = owner_of(p, adem, pl, {**cands, **public_by_name})
        ft = pl[p][0].get("facility_type") if pl.get(p) else None
        private_c = cands.get(p)
        if name is None or (adem.get(p) or {}).get("permittee_removed") and not (adem.get(p) or {}).get("permittees"):
            c = private_c or {}
            fac = c.get("facility") if c.get("facility") not in (None, REMOVED) else \
                ((adem.get(p) or {}).get("facilities") or [None])[0] or (pl[p][0].get("permittee") if pl.get(p) else None)
            key = f"withheld:{p}"
            g = groups.setdefault(key, {"name": (f"{tidy(fac)} (permit {p})" if fac else f"Sewage plant, permit {p}"),
                                        "legal_form": "facility (permittee not named)", "basis": basis, "permits": [],
                                        "private": True, "research": None})
            g["permits"].append(p)
            continue
        disp = tidy(name)
        k = compact(disp)
        disp = ALIASES.get(k, disp)
        k = compact(disp)
        lf = form(disp, ft)
        private = False
        if private_c and p not in public_by_name and lf not in PUBLIC_FORMS:   # EPA types it private and the name
            # does not read as a public body: the candidates file's proposed form
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

    # research rows take the group of their permits' owner
    research = json.loads(RESEARCH.read_text())
    by_permit = {p: k for k, g in groups.items() for p in g["permits"]}
    for r in research:
        rp = [x.strip() for x in (r.get("npdes_permit") or "").split(";") if x.strip()]
        keys = {by_permit[x] for x in rp if x in by_permit}
        if not rp:                                       # Huntsville, Montgomery: no permit in the research row
            k = compact(ALIASES.get(compact(tidy(r["name"])), tidy(r["name"])))
            keys = {k} if k in groups else set()
        if len(keys) != 1:
            if REVIEW:
                print(f"!! {r['id']}: its permits read as {keys or 'no owner'}")
                continue
            raise SystemExit(f"{r['id']}: its permits read as {keys or 'no owner'}")
        groups[keys.pop()]["research"] = r

    ssop = set(adem)
    new = []
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["name"].lower()):
        ps = list(dict.fromkeys(g["permits"]))
        r = g["research"]
        rows = [x for p in ps for x in pl.get(p, [])]
        rid = r["id"] if r else f"al-{slug(g['name'])}"
        if rid in ids:
            rid = f"{rid}-{ps[0].lower()}"
        facs = sorted({f"{tidy(x.get('permittee') or '')} ({x['npdes_permit']})" for x in rows
                       if x.get("permittee") and not (cands.get(x["npdes_permit"]) or {}).get("permittee_as_recorded") == REMOVED}
                      | {f"{f} ({p}, from ADEM's SSO layer)" for p in ps if not pl.get(p)
                         for f in ((adem.get(p) or {}).get("facilities") or [])[:1]})
        waters = list(dict.fromkeys([*(r.get("receiving_waters") or [] if r else []),
                                     *[x["receiving_water_echo"] for x in rows if x.get("receiving_water_echo")],
                                     *[w for p in ps for w in (cands.get(p) or {}).get("receiving_waters_echo") or []]]))[:8]
        towns = list(dict.fromkeys([*(r.get("towns") or [] if r else []),
                                    *sorted({smart_title(x["city"]) for x in rows if x.get("city")}
                                            | {smart_title(c["city"]) for p in ps for c in [cands.get(p) or {}]
                                               if c.get("city") and g["legal_form"] != "facility (permittee not named)"})]))
        names_seen = sorted({n["name"] for p in ps for n in (adem.get(p) or {}).get("permittees") or []} - {g["name"]})
        notes = f"Owner: {g['basis']}."
        if names_seen:
            notes += " Other names on ADEM's reports: " + "; ".join(names_seen[:6]) + "."
        if facs:
            notes += " Plants and systems: " + ", ".join(facs[:12]) + ("." if len(facs) <= 12 else f", and {len(facs) - 12} more.")
        if g["legal_form"] == "facility (permittee not named)":
            notes = ("The permittee's name reads as an individual's: not named here; the row names the facility. "
                     + notes)
        rep = sum((adem.get(p) or {}).get("reports") or 0 for p in ps)
        if rep:
            notes += f" {rep:,} SSO reports on ADEM's layer (read {CHECKED})."
        if r and r.get("notes"):
            notes += " " + r["notes"]
        lf = FORM_BY_NAME.get(g["name"], g["legal_form"])
        private = (g["private"] and lf not in PUBLIC_FORMS) or lf in PRIVATE_FORMS
        nr = row(rid, g["name"], "sso" if set(ps) & ssop else "plant", ps, towns, waters, notes.strip(), lf,
                 outfall_count=len(rows) or None,
                 outfalls_source=(f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                  if rows else None),
                 verified=(r.get("verified") if r else "fetched"), private=private)
        if r and r["id"] not in nr["aliases"]:
            nr["aliases"].append(r["id"])
        new.append(nr)
        ids.add(rid)
        counts["research rows" if r else ("private rows" if private else "public rows")] += 1
    new.sort(key=lambda r: r["id"])
    allp = [p for r in new for p in r["npdes_permits"]]
    dup = [p for p, c in Counter(allp).items() if c > 1]
    if dup:
        raise SystemExit(f"permits in two rows: {dup}")
    return keep + new, counts, groups


def review(groups: dict) -> None:
    """Groups that share a place word (the word after 'City of' / 'Town of', or the first word): merge candidates."""
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
    new = [d for d in out if d.get("state") == "AL" and "al" in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1), f"\nAlabama rows {len(new)}, permits "
          f"{sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
