"""Ohio operator rows for data/dischargers.json: one row per permittee, every Ohio permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_oh_operators.py [--dry-run]

Inputs
  1. data/outfalls-us.json: EPA's national CSO inventory, Ohio's 89 combined sewer permits (1,032 open outfalls).
  2. data/outfalls-plants-us.json: EPA ICIS-NPDES's Ohio sewage-plant permits (1,279); the permittee of record is
     EPA's permit_name ("City of Defiance", "New Athens, Village of", "Butler Co Brd of Comm"); EPA's permittee field
     holds the facility's name ("DEFIANCE WWTP").
  3. research/oh/dischargers.json (96 rows): one per CSO permit (with the channel found or searched), and five
     operators known only from their SSO annual reports. Each keeps its research id as an alias.
  4. research/oh/private-utilities-candidates.json (235 private sewage permits, 4 typed private that read as public):
     legal_form from the file's proposal (docs/legal-forms.md); a permittee the file removed (a person's name) is
     never named: the row names the facility, legal form "facility (permittee not named)".
  Grouping: permits whose permittee of record reads as the same body after normalising ("New Athens, Village of" and
  "Village of New Athens"; "Co" and "County"; "Brd of Comm" and "Board of Commissioners") are one row. A name that
  gives only the plant ("Hiram WWTP") stays its own row: the body is not guessed.
  kind: "cso" for an operator holding a permit of EPA's CSO inventory, else "plant" ("sso" for the research rows
  known only from SSO annual reports, which hold no permit here).
Legal form (form()): City of / Village of (a village is a "town" on the list) / Township; a county board of
  commissioners or county sewer district -> county; a regional sewer district or regional water and sewer district
  (Ohio Revised Code chapter 6119), a sanitary or conservancy district -> special district; a port, sewer or water
  authority -> authority; ODNR, ODOT, Ohio's universities and other state bodies -> state facility; federal bodies ->
  federal facility; a private name -> the candidates file's proposal; EPA's municipal type with no other form -> city.
Rules
  - notification_channel says what Ohio requires and where the public can see it: no Ohio statute or rule requires
    public notice of a sewage discharge in general; OAC 3745-33-08(A)(12) requires a permanent sign at every outfall
    including a bypass or CSO outfall, and (F)(1) notice to a downstream public water supply operator for majors
    near an intake; overflows are reported to Ohio EPA within 24 hours (not published). For a CSO permittee in the
    Lake Erie basin, 40 CFR 122.38's four-hour public notice; for one in the Ohio River basin, its permit's Nine
    Minimum Controls public notification. Then the operator's own channel as the research found it, with its URL.
  - Idempotent: a rerun replaces the rows it wrote (source_areas ["oh"]) and leaves every other row as it is.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKED = "2026-11-08"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "oh" / "dischargers.json"
CANDIDATES = ROOT / "research" / "oh" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
REMOVED = "[name removed]"

BASE_LAW = ("No Ohio statute or rule requires public notice of a sewage discharge in general. OAC 3745-33-08(A)(12) "
            "requires a permanent sign at each permitted outfall, bypass and combined sewer overflow outfalls included, "
            "and (F)(1) requires a major discharger near a drinking-water intake to notify the public water supply "
            "operator as soon as practicable after a discharge begins. Sewer overflows and bypasses are reported to "
            "Ohio EPA within 24 hours; those reports are not published.")
LAKE_ERIE = (" As a combined sewer permittee in the Lake Erie basin it owes the public notice of 40 CFR 122.38: an "
             "initial notice no later than four hours after becoming aware of a discharge, under its public "
             "notification plan.")
OHIO_RIVER = (" As a combined sewer permittee outside the Lake Erie basin, its public notice rests on its permit's "
              "Nine Minimum Controls (public notification) and any consent decree.")
NOT_SEARCHED = " Its own public channel was not searched individually."

# legal forms the name rules miss (read from the names, 2026-11-08)
FORM_BY_NAME = {
    "Northeast Ohio Regional Sewer District": "special district",
    "Metropolitan Sewer District of Greater Cincinnati": "county",
    "Eastern Ohio Regional Wastewater Authority": "authority",
    "Biery Cheese": "business or industrial",
    "Starlite Lanes": "business or industrial",
    "Earthlore Environmental": "business or industrial",
    "Fort Scott Development Wastewater Treatment Plant": "business or industrial",
    "Camp Wesley": "campground or resort",
}
# research names that are a facility of a body named in EPA's permit name
RESEARCH_NAME = {"OH0043991": "Northeast Ohio Regional Sewer District",
                 "OH0023833": "City of Akron",                                  # Akron Water Reclamation Facility
                 "OH0105457": "Metropolitan Sewer District of Greater Cincinnati",  # its CSO permit in EPA's inventory
                 "OH0024732": "City of Columbus",                               # Jackson Pike (EPA: "Sewerage & Drainage")
                 "OH0024741": "City of Columbus"}                               # Southerly: the same city's permit
ABBR = {"llc", "lp", "ii", "iii", "wwtp", "wpcf", "wpc", "wrf", "wrrf", "stp", "wwtf", "msd", "odnr", "odot", "mhp",
        "mhc", "usa", "us", "sd", "rv", "ymca", "ywca", "inc"}


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").split()):
        bare = re.sub(r"[^A-Za-z.]", "", w).lower().rstrip(".")
        if bare in ABBR:
            out.append(w.upper())
        elif bare in ("of", "and", "the", "for", "at") and i:
            out.append(bare)
        else:
            out.append(re.sub(r"(?<=\w)'S\b", "'s", w.title()) if w.isupper() or w.islower() else w)
    return re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), " ".join(out))


def tidy(name: str) -> str:
    """A display name: 'New Athens, Village of' -> 'Village of New Athens'; 'Toronto, City of' -> 'City of Toronto';
    'North Ridgeville City' -> 'City of North Ridgeville'; 'Co' -> 'County', 'Brd of Comm' -> 'Board of
    Commissioners'; all-capitals names title-cased."""
    s = " ".join((name or "").split()).strip(" ,")
    if s.isupper() or s.islower():
        s = smart_title(s)
    m = re.match(r"^(.+?),\s*(City|Village|Township|Town|County)\s+of\.?$", s, re.I)
    if m:
        s = f"{m.group(2).title()} of {m.group(1)}"
    m = re.match(r"^([A-Z][\w .'-]+?)\s+(City|Village)$", s)
    if m:
        s = f"{m.group(2)} of {m.group(1)}"
    s = re.sub(r"\bCo\b\.?", "County", s)
    s = re.sub(r"\b(?:Brd|Bd)\b\.?", "Board", s)
    s = re.sub(r"\bComm(?:rs?|s)?\b\.?$", "Commissioners", s)
    s = re.sub(r"\bComm\b\.?", "Commissioners", s)
    s = re.sub(r"^The\s+", "", s)
    s = re.sub(r",?\s*(Ohio|OH)\.?$", "", s).strip(" ,")
    s = re.sub(r"\bCounty (?:Board )?(?:of )?Commissioners\b", "County Board of Commissioners", s)
    return re.sub(r"\bOf\b", "of", re.sub(r"\bAnd\b", "and", s[0].upper() + s[1:])) if s else s


def compact(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\b(inc|llc|ohio|oh)\b\.?", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def form(name: str, facility_type: str | None) -> str | None:
    n = name.lower()
    if name in FORM_BY_NAME:
        return FORM_BY_NAME[name]
    if re.search(r"army|air force|u\.? ?s\.? (army|dept|department)|united states|national park|federal|veterans|nasa",
                 n) or facility_type in ("Federal Facility (U.S. Government)", "FEDERAL"):
        return "federal facility"
    if re.search(r"\b(odnr|odot)\b|^ohio (department|dept|state|turnpike|dnr|dot)|state park|university|\bstate of ohio\b|"
                 r"department of (rehabilitation|natural resources|transportation|corrections|youth)|correctional|"
                 r"rest area", n):
        return "state facility"
    if re.search(r"regional (water and )?sewer district|\bsanitary district\b|\bconservancy district\b|"
                 r"\bsewer district\b(?!.*county)|\bwater (and sewer )?district\b|\bsch(ool)?\.? district\b|"
                 r"board of education|\blocal (sch(ool)?s?|sch\.?)\b|\bschools?\b", n):
        return "special district"
    if re.search(r"\bcounty\b", n):
        return "county"
    if re.search(r"\bauthority\b", n):
        return "authority"
    if re.search(r"^village of\b|\bvillage of\b|^town of\b", n):
        return "town"
    if re.search(r"\btownship\b|\btwp\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity of\b", n):
        return "city"
    if re.search(r"\b(llc|inc|corp|corporation|company|ltd|l\.p\.)\b", n):
        return None
    if re.search(r"\bmhp\b|\bmhc\b|mobile home|manufactured home", n):
        return "mobile-home park"
    if re.search(r"\bclub\b|\belks\b|\blodge\b", n):
        return "private club"
    if facility_type == "State Government":
        return "state facility"
    if facility_type in ("Municipal or Water District", "POTW"):
        return "city"
    return None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


def build(dis: list[dict]) -> tuple[list[dict], Counter]:
    keep = [d for d in dis if not (d.get("state") == "OH" and "oh" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "OH" and r.get("npdes_permit"):
            plants[r["npdes_permit"].upper()].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if str(r.get("npdes_permit") or "").startswith("OH"):
            cso[r["npdes_permit"].upper()].append(r)
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"] for c in cand["public_by_name"]}
    research = json.loads(RESEARCH.read_text())
    res_by_permit = {r["npdes_permit"]: r for r in research if r.get("npdes_permit")}
    counts = Counter()
    groups: dict[str, dict] = {}
    for p in sorted(set(plants) | set(cso) | set(cands) | set(res_by_permit)):
        if p in held:
            continue
        c = cands.get(p) or {}
        pl = plants.get(p) or []
        if p in RESEARCH_NAME:
            name, basis = RESEARCH_NAME[p], "the operator's own name (research)"
        elif pl and pl[0].get("permit_name") and not (c.get("permittee_as_recorded") == REMOVED):
            name, basis = pl[0]["permit_name"], "EPA ICIS-NPDES permittee of record"
        elif c and c.get("permittee_as_recorded") not in (None, REMOVED):
            name, basis = c["permittee_as_recorded"], "EPA ICIS-NPDES permittee (private-utility candidates)"
        elif c.get("permittee_as_recorded") == REMOVED:
            fac = c.get("facility") if c.get("facility") not in (None, REMOVED) else None
            groups[f"withheld:{p}"] = {"name": f"{tidy(fac)} (permit {p})" if fac else f"Sewage plant, permit {p}",
                                       "legal_form": "facility (permittee not named)", "permits": [p], "private": True,
                                       "basis": "EPA's permittee name reads as an individual's: not named here"}
            continue
        elif pl and pl[0].get("permittee"):
            name, basis = pl[0]["permittee"], "EPA ICIS-NPDES facility name (no permittee of record)"
        elif cso.get(p):
            name, basis = cso[p][0]["permittee"], "EPA's CSO inventory (the facility's name)"
        elif res_by_permit.get(p):
            name, basis = res_by_permit[p]["name"], "the research row's name"
        else:
            continue
        disp = tidy(name)
        ft = pl[0].get("facility_type") if pl else None
        lf = form(disp, ft)
        private = False
        if c and p not in public_by_name and lf not in PUBLIC_FORMS:
            lf = c.get("legal_form_proposed") if c.get("legal_form_proposed") in PRIVATE_FORMS else None
            private = True
        g = groups.setdefault(compact(disp), {"name": disp, "legal_form": lf, "permits": [], "private": private,
                                              "basis": basis})
        g["permits"].append(p)
        if g["legal_form"] is None and lf:
            g["legal_form"] = lf
        g["private"] = g["private"] or private
    by_permit = {p: k for k, g in groups.items() for p in g["permits"]}
    no_permit_research = []
    for r in research:
        p = r.get("npdes_permit")
        if p and p in by_permit:
            groups[by_permit[p]].setdefault("research", []).append(r)
        else:
            k = compact(tidy(r["name"]))
            if k in groups:
                groups[k].setdefault("research", []).append(r)
            else:
                no_permit_research.append(r)
    new = []
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["name"].lower()):
        ps = list(dict.fromkeys(g["permits"]))
        rs = g.get("research") or []
        rid = rs[0]["id"] if rs else f"oh-{slug(g['name'])}"
        if rid in ids:
            rid = f"{rid}-{ps[0].lower()}"
        new.append(make_row(rid, g, ps, rs, plants, cso, cands))
        ids.add(rid)
        counts["research rows" if rs else ("private rows" if g["private"] else "public rows")] += 1
    for r in no_permit_research:          # operators known only from SSO annual reports
        g = {"name": tidy(r["name"]), "legal_form": form(tidy(r["name"]), None), "private": False,
             "basis": "the research row (an SSO annual report)"}
        new.append(make_row(r["id"], g, [], [r], plants, cso, cands, kind="sso"))
        counts["research rows without a permit"] += 1
    new.sort(key=lambda r: r["id"])
    allp = [p for r in new for p in r["npdes_permits"]]
    dup = [p for p, c in Counter(allp).items() if c > 1]
    if dup:
        raise SystemExit(f"permits in two rows: {dup}")
    return keep + new, counts


def channel(rs: list[dict], is_cso: bool, lake_erie: bool, private: bool) -> str:
    s = BASE_LAW
    if is_cso:
        s += LAKE_ERIE if lake_erie else OHIO_RIVER
    found = [r["notification_channel"] for r in rs if r.get("verified") == "fetched"]
    listed = [r["notification_channel"] for r in rs if r.get("verified") != "fetched"
              and not r["notification_channel"].startswith("not searched")]
    if found:
        s += " Its channel: " + " ".join(found)
    elif listed:
        s += " Listed for it (not read here): " + " ".join(listed)
    else:
        s += NOT_SEARCHED
    if private:
        s += " The permit rule binds every NPDES permittee, public or private."
    return s


def make_row(rid, g, ps, rs, plants, cso, cands, kind=None) -> dict:
    rows = [x for p in ps for x in plants.get(p, [])]
    crow = [x for p in ps for x in cso.get(p, [])]
    open_cso = [x for x in crow if not str(x.get("outfall_status") or "").upper().startswith("CLS")]
    lake_erie = any(r.get("kind") == "cso" and "outside EPA's Lake Erie list" not in r["notification_channel"]
                    for r in rs)
    waters = list(dict.fromkeys([w for r in rs for w in r.get("receiving_waters") or []] +
                                [x["receiving_water_echo"] for x in rows + crow if x.get("receiving_water_echo")]))[:8]
    towns = list(dict.fromkeys([t for r in rs for t in r.get("towns") or []] +
                               sorted({smart_title(x["city"]) for x in rows + crow if x.get("city")}
                                      if g["legal_form"] != "facility (permittee not named)" else [])))
    facs = sorted({f"{tidy(x.get('permittee') or '')} ({x['npdes_permit']})" for x in rows
                   if x.get("permittee") and (cands.get(x["npdes_permit"]) or {}).get("facility") != REMOVED})
    notes = f"Owner: {g['basis']}."
    if facs and g["legal_form"] != "facility (permittee not named)":
        notes += " Plants: " + ", ".join(facs[:12]) + ("." if len(facs) <= 12 else f", and {len(facs) - 12} more.")
    if crow:
        notes += (f" EPA's CSO inventory: {len(open_cso)} open combined sewer outfalls"
                  f"{' (Lake Erie basin, 40 CFR 122.38)' if lake_erie else ''}.")
    for r in rs:
        if r.get("notes"):
            notes += " " + r["notes"]
    lf = FORM_BY_NAME.get(g["name"], g["legal_form"])
    private = (g["private"] and lf not in PUBLIC_FORMS) or lf in PRIVATE_FORMS
    out = {"id": rid, "name": g["name"], "short_name": g["name"], "legal_form": lf, "state": "OH",
           "kind": kind or ("cso" if crow else "plant"), "npdes_permit": ps[0] if ps else None, "npdes_permits": ps,
           "receiving_waters": waters, "water_slugs": [],
           "outfall_count": (len(open_cso) or len(rows) or None),
           "outfalls_source": ("EPA National CSO Inventory (data/outfalls-us.json)" if crow else
                               f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)"
                               if rows else None),
           "notification_channel": channel(rs, bool(crow), lake_erie, private),
           "notification_feed_machine_readable": any(r.get("notification_feed_machine_readable") for r in rs),
           "notification_signup_url": None, "towns": towns, "notes": notes.strip(),
           "verified": next((r["verified"] for r in rs if r.get("verified") == "fetched"),
                            rs[0]["verified"] if rs else "inferred"),
           "checked": CHECKED, "aliases": list(dict.fromkeys([rid, *[r["id"] for r in rs]])), "source_areas": ["oh"]}
    if lake_erie:
        out["great_lakes_basin"] = True
    return out


def main(argv) -> int:
    dis = json.loads(DIS.read_text())
    out, counts = build(dis)
    new = [d for d in out if d.get("state") == "OH" and "oh" in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1), f"\nOhio rows {len(new)}, permits {sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
