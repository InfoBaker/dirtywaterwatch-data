"""Wisconsin operator rows for data/dischargers.json: one row per operator, every Wisconsin permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_wi_operators.py [--dry-run]

Inputs
  1. data/outfalls-us.json: EPA's national CSO inventory, Wisconsin's two combined sewer permits (MMSD WI0036820, 114
     open outfalls; Superior WI0025593, 3).
  2. data/outfalls-plants-us.json: EPA ICIS-NPDES's Wisconsin sewage-plant permits (588 permits, 596 rows). For
     Wisconsin EPA's `permittee` field holds the facility's name ("WHITEWATER CITY WWTF", "NEW GLARUS WASTEWATER
     TREATMENT FACILITY") and `permit_name` the permit's name, which is the owning body for some ("VILLAGE OF
     PARDEEVILLE", "City of Osseo") and a cut-off facility name for others ("WHITEWATER WASTEWATER TREATMEN").
  3. research/wi/dischargers.json (11 rows): MMSD (two rows, one permit), Superior, and eight operators found through
     their own SSO notices. Each research id stays as an alias of the row that holds its permit or its place.
  4. research/wi/private-utilities-candidates.json (15 candidates, 3 public by name): the permittee as EPA records it.
Name (name_for): the research's name for MMSD and Superior; else the permit's name when it names a body (city, village,
  town, county, sanitary or utility district, commission, tribe or band, a state department) and is not a cut-off
  facility name; else the candidates file's permittee; else EPA's facility name. A name that gives only the plant
  ("New Glarus Wastewater Treatment Facility") stays its own row with legal_form null: the body is not guessed (a
  Wisconsin plant can belong to a city, a village or a sanitary district of the same name).
Legal form (form()): City of / X City -> city; Village of / X Village, Town of -> town (a village is a "town" on the
  list); sanitary, utility, metropolitan sewerage and school districts, joint sewerage and utility commissions -> special
  district; a county -> county; the DNR's parks, the Department of Corrections, the university -> state facility;
  federal bodies -> federal facility; a tribe, band, nation or tribal enterprise -> tribal; a company -> business or
  industrial; a mobile-home park -> mobile-home park; else null.
kind: "cso" for an operator holding a permit of EPA's CSO inventory, "sso" for a research row known only from its own
  overflow notices, else "plant".
notification_channel says what Wisconsin requires: s. NR 210.21(5), Wis. Adm. Code (public notice "promptly" after
  any sanitary sewer or treatment facility overflow, by the communications the operator's emergency response plan
  names; the DNR's form instructions set a daily newspaper as the minimum for an overflow to surface water), the report
  to the DNR within 24 hours and the written form 3400-184 within five business days through Switchboard (not
  published). For the two Great Lakes Basin combined sewer permittees, 40 CFR 122.38's four-hour public notice. Then
  the operator's own channel as the research found it, with its URL.
Idempotent: a rerun replaces the rows it wrote (state WI, source_areas ["wi"]) where they stood and leaves every other
row as it is; on a first run they go after the last row of the file.
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKED = "2026-11-14"
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "wi" / "dischargers.json"
CANDIDATES = ROOT / "research" / "wi" / "private-utilities-candidates.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
REMOVED = "[name removed]"

BASE_LAW = ("Wisconsin requires public notice of every sanitary sewer overflow and treatment facility overflow: s. NR "
            "210.21(5), Wis. Adm. Code, \"promptly\" after the overflow, by the communications the operator's emergency "
            "response plan names; the Department of Natural Resources' form instructions make a daily newspaper of "
            "general circulation the minimum when the overflow reaches surface water. No web posting and no hour "
            "deadline are set. The overflow is reported to the DNR within 24 hours and on form 3400-184 within five "
            "business days through the DNR's Switchboard system; the DNR does not publish those reports.")
GREAT_LAKES = (" As a combined sewer permittee in the Great Lakes Basin it also owes the public notice of 40 CFR 122.38: "
               "an initial notice no later than four hours after becoming aware of a discharge, under its public "
               "notification plan.")
NOT_SEARCHED = " Its own public channel was not searched individually."

RESEARCH_NAME = {"WI0036820": "Milwaukee Metropolitan Sewerage District",
                 "WI0025593": "City of Superior (Superior Sewage Disposal System)"}
FORM_BY_PERMIT = {"WI0036820": "special district",          # a metropolitan sewerage district, ss. 200.21-200.65, Wis. Stats.
                  "WI0025593": "city",
                  "WI0046868": "tribal"}                    # Menominee Tribal Enterprises (EPA: the tribe)
# The 14 Wisconsin permits in EPA's collection-system table (current extract of 2026-11-12, one payload received
# 2025-03-04): the permits EPA Region 5 issues on tribal land (Keshena is on the Menominee Reservation). Each is tribal.
EPA_TRIBAL_PERMITS = {"WI0036188", "WI0036498", "WI0036544", "WI0036579", "WI0036587", "WI0049727", "WI0058424",
                      "WI0058432", "WI0062847", "WI0071315", "WI0071323", "WI0071501", "WI0073041", "WI0073059"}
FORM_BY_PERMIT.update({p: "tribal" for p in EPA_TRIBAL_PERMITS})
NAME_BY_PERMIT = {"WI0046868": "Menominee Tribal Enterprises"}
ABBR = {"wwtf", "wwtp", "wpcf", "stp", "sd", "dnr", "doc", "mhp", "llc", "inc", "usa", "us", "ii", "wi", "uw"}
BODY = re.compile(r"\b(city|village|town|township|county|sanitary|utility|utilities|district|commission|comm|"
                  r"tribe|band|nation|dept|department|dnr|doc|university|state of)\b", re.I)
CUT_OFF = re.compile(r"\b(wastewater|treatmen\w*|trtmn\w*|wwtf|wwtp|facil\w*|plant|plnt)\b|\bS C$|\bCOMBI$", re.I)
# Wisconsin's tribes and bands (their own names; a tribal community's plant is tribal, not the county's of its name)
TRIBAL = re.compile(r"\btrib(e|al)\b|\bband\b|\bnation\b|\bindian\b|potawatom[iy]|lac courte oreilles|"
                    r"lac du flambeau|bad river|red cliff|sokaogon|mole lake|oneida|ho-chunk|stockbridge-munsee|munsee", re.I)
# research rows known by their own notices whose plant permit the name rules cannot join
RESEARCH_PERMIT = {"wi-fremont-sso": "WI0026158"}
PLACE_STRIP = re.compile(r"^(?:city|village|town) of |\b(?:utilities|utility|city|village|sso)\b|\(.*?\)", re.I)


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").split()):
        bare = re.sub(r"[^A-Za-z]", "", w).lower()
        if bare in ABBR:
            out.append(w.upper())
        elif bare in ("of", "and", "the", "for", "at") and i:
            out.append(bare)
        else:
            out.append(w.title() if w.isupper() or w.islower() else w)
    s = " ".join(out)
    s = re.sub(r"(?<=\w)'S\b", "'s", s)
    return re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), s)


def tidy(name: str) -> str:
    """'Brookfield, City of' -> 'City of Brookfield'; 'LAKE NEBAGAMON  VILLAGE OF' -> 'Village of Lake Nebagamon';
    'Hammond Village' -> 'Village of Hammond'; 'Wyeville (Village of)' -> 'Village of Wyeville'."""
    s = " ".join((name or "").split()).strip(" ,")
    if s.isupper() or s.islower():
        s = smart_title(s)
    s = re.sub(r"\(\s*(City|Village|Town) of\s*\)", r", \1 of", s, flags=re.I)
    m = re.match(r"^(.+?),?\s+(City|Village|Town|County)\s+of\.?$", s, re.I)
    if m:
        s = f"{m.group(2).title()} of {m.group(1).strip(' ,')}"
    m = re.match(r"^([A-Z][\w .'-]+?)\s+(City|Village)$", s)
    if m:
        s = f"{m.group(2)} of {m.group(1)}"
    s = re.sub(r"\bSan(?:itary)? Dist\b\.?", "Sanitary District", s)
    s = re.sub(r"\bDist\b\.?", "District", s)
    s = re.sub(r"\bComm\b\.?", "Commission", s)
    s = re.sub(r"\bWI (DNR|DOC)\b", r"Wisconsin \1", s)
    s = re.sub(r"\bWI Dept of\b", "Wisconsin Department of", s)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    return re.sub(r"\bOf\b", "of", re.sub(r"\bAnd\b", "and", s[0].upper() + s[1:])) if s else s


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("&", " and "))


def form(name: str, facility_type: str | None) -> str | None:
    n = name.lower()
    if re.search(r"\barmy\b|fort mccoy|\bu\.?\s?s\.?\s+(?:army|dept|department|fish|forest)|united states|"
                 r"national park|federal|veterans", n):
        return "federal facility"
    if TRIBAL.search(n) or facility_type == "Tribal Government":
        return "tribal"
    if re.search(r"\bdnr\b|\bdoc\b|department of (corrections|natural resources|transportation|health)|state park|"
                 r"correctional|university|\buw\b", n) or facility_type == "State Government":
        return "state facility"
    if re.search(r"sanitary district|\bsd\b|utility district|sewerage district|sewerage dist|metro(politan)? sew|"
                 r"school district|sewerage commission|sewage commission|utility commission|wastewater control commission|"
                 r"joint sewerage|joint s c\b|sewerage comm|sanitary commission|regional sewerage", n):
        return "special district"
    if re.search(r"\bcounty\b", n):
        return "county"
    if re.search(r"^village of\b|\bvillage\b|^town of\b|\btown of\b|\btownship\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity\b", n):
        return "city"
    if re.search(r"\b(llc|inc|corp|corporation|company|co\.)\b", n) or facility_type == "Corporation":
        return "business or industrial"
    if re.search(r"\bmhp\b|mobile home|manufactured home", n):
        return "mobile-home park"
    return None


def name_for(p: str, pl: list[dict], cand: dict) -> tuple[str, str]:
    if p in NAME_BY_PERMIT:
        return NAME_BY_PERMIT[p], "EPA's permit name, read as the tribal enterprise it is"
    if p in RESEARCH_NAME:
        return RESEARCH_NAME[p], "the operator's own name (research)"
    pn = (pl[0].get("permit_name") or "") if pl else ""
    if pn and BODY.search(pn) and not CUT_OFF.search(pn):
        return pn, "EPA ICIS-NPDES permit name (the owning body)"
    rec = cand.get("permittee_as_recorded")
    if rec and rec != REMOVED and BODY.search(rec) and not CUT_OFF.search(rec):
        return rec, "EPA's permittee as recorded (private-utility candidates file)"
    fac = (pl[0].get("permittee") if pl else None) or cand.get("facility")
    if fac and fac != REMOVED:
        return fac, "EPA ICIS-NPDES facility name (the owning body is not in the file)"
    return f"Sewage plant, permit {p}", "EPA gives no name that can be shown"


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}


def build(dis: list[dict]) -> tuple[list[dict], Counter, int]:
    first = next((i for i, d in enumerate(dis) if d.get("state") == "WI" and "wi" in (d.get("source_areas") or [])), None)
    keep = [d for d in dis if not (d.get("state") == "WI" and "wi" in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "WI" and r.get("npdes_permit"):
            plants[r["npdes_permit"].upper()].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if str(r.get("npdes_permit") or "").startswith("WI"):
            cso[r["npdes_permit"].upper()].append(r)
    cand = json.loads(CANDIDATES.read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"] + cand["public_by_name"]}
    private_cands = {c["npdes_permit"] for c in cand["candidates"]}
    research = json.loads(RESEARCH.read_text())
    counts = Counter()
    groups: dict[str, dict] = {}
    for p in sorted(set(plants) | set(cso) | {r["npdes_permit"] for r in research if r.get("npdes_permit")}):
        if p in held:
            continue
        pl = plants.get(p) or []
        name, basis = name_for(p, pl, cands.get(p) or {})
        disp = tidy(name)
        lf = FORM_BY_PERMIT.get(p) or form(disp, pl[0].get("facility_type") if pl else None)
        g = groups.setdefault(compact(disp), {"name": disp, "legal_form": lf, "permits": [], "basis": basis,
                                              "private": p in private_cands and lf not in PUBLIC_FORMS})
        g["permits"].append(p)
        if g["legal_form"] is None and lf:
            g["legal_form"] = lf
    by_permit = {p: k for k, g in groups.items() for p in g["permits"]}
    no_permit = []
    for r in research:
        p = r.get("npdes_permit") or RESEARCH_PERMIT.get(r["id"])
        if p and p in by_permit:
            groups[by_permit[p]].setdefault("research", []).append(r)
            continue
        place = compact(PLACE_STRIP.sub(" ", r["name"]))
        hits = [k for k, g in groups.items() if place and compact(g["name"]).replace("cityof", "").replace(
            "villageof", "").replace("townof", "").startswith(place)]
        if len(hits) == 1:
            groups[hits[0]].setdefault("research", []).append(r)
        else:
            no_permit.append(r)
    new = []
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["name"].lower()):
        ps = list(dict.fromkeys(g["permits"]))
        rs = g.get("research") or []
        rid = "wi-mmsd" if "WI0036820" in ps else (rs[0]["id"] if rs else f"wi-{slug(g['name'])}")
        if rid in ids:
            rid = f"{rid}-{ps[0].lower()}"
        new.append(make_row(rid, g, ps, rs, plants, cso))
        ids.add(rid)
        counts["rows with research" if rs else ("private rows" if g["private"] else "rows")] += 1
    for r in no_permit:
        g = {"name": tidy(r["name"]), "legal_form": form(tidy(r["name"]), None), "private": False,
             "basis": "the research row (the operator's own overflow notice)"}
        new.append(make_row(r["id"], g, [], [r], plants, cso, kind="sso"))
        counts["research rows without a permit"] += 1
    new.sort(key=lambda r: r["id"])
    allp = [p for r in new for p in r["npdes_permits"]]
    dup = [p for p, c in Counter(allp).items() if c > 1]
    if dup:
        raise SystemExit(f"permits in two rows: {dup}")
    at = first if first is not None else len(keep)
    return keep[:at] + new + keep[at:], counts, len(new)


def channel(rs: list[dict], is_cso: bool) -> str:
    s = BASE_LAW + (GREAT_LAKES if is_cso else "")
    found = [r["notification_channel"] for r in rs if r.get("verified") == "fetched" and r.get("notification_channel")]
    listed = [r["notification_channel"] for r in rs if r.get("verified") != "fetched" and r.get("notification_channel")
              and not r["notification_channel"].startswith("not searched")]
    if found:
        s += " Its channel: " + " ".join(dict.fromkeys(found))
    elif listed:
        s += " Listed for it (research): " + " ".join(dict.fromkeys(listed))
    else:
        s += NOT_SEARCHED
    return s


def make_row(rid, g, ps, rs, plants, cso, kind=None) -> dict:
    rows = [x for p in ps for x in plants.get(p, [])]
    crow = [x for p in ps for x in cso.get(p, [])]
    open_cso = [x for x in crow if not str(x.get("outfall_status") or "").upper().startswith("CLS")]
    waters = list(dict.fromkeys([w for r in rs for w in r.get("receiving_waters") or []] +
                                [x["receiving_water_echo"] for x in rows + crow if x.get("receiving_water_echo")]))[:8]
    towns = list(dict.fromkeys([t for r in rs for t in r.get("towns") or []] +
                               sorted({smart_title(re.sub(r",.*", "", x["city"])) for x in rows + crow if x.get("city")})))
    facs = sorted({f"{tidy(x.get('permittee') or '')} ({x['npdes_permit']})" for x in rows if x.get("permittee")})
    notes = f"Owner: {g['basis']}."
    if facs:
        notes += " Plants: " + ", ".join(facs[:12]) + ("." if len(facs) <= 12 else f", and {len(facs) - 12} more.")
    if crow:
        notes += f" EPA's CSO inventory: {len(open_cso)} open combined sewer outfalls (Great Lakes Basin, 40 CFR 122.38)."
    for r in rs:
        if r.get("notes"):
            notes += " " + r["notes"]
    lf = g["legal_form"]
    out = {"id": rid, "name": g["name"], "short_name": "MMSD" if rid == "wi-mmsd" else g["name"], "legal_form": lf,
           "state": "WI", "kind": kind or ("cso" if crow else "plant"), "npdes_permit": ps[0] if ps else None,
           "npdes_permits": ps, "receiving_waters": waters, "water_slugs": [],
           "outfall_count": (len(open_cso) or len(rows) or None),
           "outfalls_source": ("EPA National CSO Inventory (data/outfalls-us.json)" if crow else
                               f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)"
                               if rows else None),
           "notification_channel": channel(rs, bool(crow)),
           "notification_feed_machine_readable": False,
           "notification_signup_url": None, "towns": towns, "notes": notes.strip(),
           "verified": next((r["verified"] for r in rs if r.get("verified") == "fetched"),
                            rs[0]["verified"] if rs else "inferred"),
           "checked": CHECKED, "aliases": list(dict.fromkeys([rid, *[r["id"] for r in rs]])), "source_areas": ["wi"]}
    if crow:
        out["great_lakes_basin"] = True
    if rid == "wi-mmsd":
        out["notification_channel"] += (" MMSD posts a Storm Update on its news page with each overflow it reports to "
                                         "the DNR, with the dates and volume, about five days after the overflow "
                                         "(https://www.mmsd.com/about-us/news).")
        out["notification_signup_url"] = "https://mmsd.com/what-you-can-do/water-drop-alert"
        out["notes"] += (" The Water Drop Alert text messages ask residents to use less water before heavy rain; they "
                         "are not overflow notices.")
    return out


def main(argv) -> int:
    dis = json.loads(DIS.read_text())
    out, counts, n = build(dis)
    new = [d for d in out if d.get("state") == "WI" and "wi" in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1), f"\nWisconsin rows {len(new)}, permits "
          f"{sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
