"""Shared rules for the Colorado, Montana and Wyoming operator rows (scripts/add_co_operators.py, add_mt_operators.py,
add_wy_operators.py): one row per permittee, every permit of the state in exactly one row.

Inputs (per state <st>)
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's sewage-plant permits with that state (EPA's `permit_name` is the
     permit's name, usually the owning body: "Rangely Town of", "CITY OF GREAT FALLS", "Sheridan, City of"; `permittee`
     is the facility's name). data/outfalls-us.json holds no combined sewer permit for any of the three states.
  2. research/<st>/dischargers.json: the research rows; each research id stays the id (or an alias) of the row that
     holds its permit, so a feed's discharger_id resolves (common.discharger_alias_map).
  3. research/<st>/private-utilities-candidates.json: private permits with a sewage code, some outside the plant
     table; a name the candidates file removed ("[name removed]": a person) is never read from EPA's other fields either
     unless that field names a body (a company, a district).
  4. EPA's sewer overflow collection-system table (the current and all-versions extracts of 2026-11-14): the permits
     EPA Region 8 holds there are EPA-issued permits on tribal land (Polson, Ronan, Poplar, Fort Washakie).
Name: the state script's NAME override, else EPA's permit name when it names a body and does not read as a person, else
  the candidates file's permittee, else EPA's facility name, else "Sewage plant, permit <id>". Names are tidied
  ("Rangely Town of" -> "Town of Rangely", "POLSON- CITY OF" -> "City of Polson") and permits whose tidied names agree
  are one row.
Legal form (form()): the controlled list of docs/legal-forms.md, from the name and EPA's facility type; a state's FORM
  override wins. A name that gives only a plant keeps legal_form null: the body is not guessed.
EPA-issued permits (EPA Region 8 issues NPDES permits on tribal lands and lands of exclusive federal jurisdiction in all
  three states, and for every federal facility in Colorado: "About Region 8's NPDES Permit Program", read 2026-11-14):
  a permit is filed as EPA's when EPA's collection-system table lists it, when it is a coverage under EPA's lagoon
  general permit for Indian country (COG587, MTG589, WYG589), when EPA types its facility a tribal government or the
  name is a tribe's, a tribal utility's or a reservation community's listed in the state script, and, in Colorado, when
  EPA types it a federal facility. Its channel is EPA's (40 CFR 122.41(l)(6)), not the state's.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CSO = ROOT / "data" / "outfalls-us.json"
REMOVED = "[name removed]"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
R8 = "https://www.epa.gov/npdes-permits/about-region-8s-npdes-permit-program"
# EPA's collection-system table (current extract of 2026-11-14, one payload received 2025-03-04, repeated 2025-01-31 in
# the all-versions extract): the only Colorado, Montana or Wyoming permits in either EPA overflow table
EPA_TABLE_PERMITS = {"MT0020559", "MT0021474", "MT0030597", "WYG589101"}
TRIBAL_GP = re.compile(r"^(COG587|MTG589|WYG589)")
ABBR = {"wwtf", "wwtp", "wsd", "llc", "inc", "us", "usa", "pc", "mhp", "cdot", "cdpw", "wydot", "bopu", "usbor", "cdnr",
        "cpw", "ktc", "pud", "hoa", "re1", "r-1", "re-2", "dbo", "doi", "nps", "dnrc", "sscs", "ii"}
BODY = re.compile(r"\b(city|town|village|county|counties|district|dist|authority|board|commission|commissioners|comm|"
                  r"tribe|tribes|tribal|nation|department|dept|government|university|school|schools|state|service|"
                  r"united states|national|bureau|forest|corp|corporation|company|co\.|inc|llc|ltd|association|assoc|"
                  r"homeowners|utilities|utility|metro|metropolitan|sanitation|sewer|water|recovery|renew|"
                  r"park|parks|resort|ranch|lodge|club|institute|hospital|diocese|mission|housing|airport|port|"
                  r"cdot|wydot|cdpw|usbor|church|camp|estates|subdivision|village|manor|mhp|wwtf|wwtp|lagoon|hoa|pud)\b", re.I)
PERSONISH = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:-[A-Z][a-z]+)?$")


def smart_title(s: str) -> str:
    out = []
    for i, w in enumerate((s or "").split()):
        bare = re.sub(r"[^A-Za-z0-9-]", "", w).lower()
        if bare in ABBR:
            out.append(w.upper())
        elif bare in ("of", "and", "the", "for", "at", "on", "in") and i:
            out.append(bare)
        else:
            out.append(w.title() if w.isupper() or w.islower() else w)
    s = " ".join(out)
    s = re.sub(r"(?<=\w)'S\b", "'s", s)
    return re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), s)


EXPAND = [(r"\bWSD\b", "Water and Sanitation District"), (r"\bW\s*(?:&|and)\s*S Dist\b\.?", "Water and Sewer District"),
          (r"\bWater (?:&|and) San(?:itation)? Dist(?:rict)?\b\.?", "Water and Sanitation District"),
          (r"\bWater Sanitation Dist\b\.?", "Water and Sanitation District"),
          (r"\bSan(?:itation)? Dist\b\.?", "Sanitation District"), (r"\bSaniation\b", "Sanitation"),
          (r"\bSanitatin\b", "Sanitation"), (r"\bMetro Dist\b\.?", "Metropolitan District"),
          (r"\bMetro District\b", "Metropolitan District"), (r"\bDist\b\.?", "District"), (r"\bDis\b\.?$", "District"),
          (r"\bCo Water\b", "County Water"), (r"\bCo\s+(?=Water|Sewer)", "County "), (r"\bComm\b\.?", "Community"),
          (r"\bResevior\b", "Reservoir"), (r"\bHomewoners\b", "Homeowners"), (r"\bAssoc\b\.?", "Association")]


def tidy(name: str) -> str:
    """'Rangely Town of' -> 'Town of Rangely'; 'EVANS, CITY OF' -> 'City of Evans'; 'POLSON- CITY OF' -> 'City of
    Polson'; 'Monte Vista  City of' -> 'City of Monte Vista'; 'TOWN OF JOLIET' -> 'Town of Joliet'."""
    s = " ".join((name or "").split()).strip(" ,-")
    s = re.sub(r"\s+c/o\s+.*$", "", s, flags=re.I)          # 'c/o' a law firm or an agent: not the body
    if s.isupper() or s.islower():
        s = smart_title(s)
    m = re.match(r"^(.+?)[,\-]?\s+(City|Town|County)\s+of\.?(?:\s*-\s*\w+)?$", s, re.I)
    if m:
        s = f"{m.group(2).title()} of {m.group(1).strip(' ,-')}"
    for pat, rep in EXPAND:
        s = re.sub(pat, rep, s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,-")
    s = re.sub(r"\bOf\b", "of", re.sub(r"\bAnd\b", "and", s))
    return s[0].upper() + s[1:] if s else s


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("&", " and "))


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def personish(name: str) -> bool:
    """A name that reads as a person's ('Jane Doe'), not a body's: never shown."""
    n = (name or "").strip()
    return bool(PERSONISH.match(n)) and not BODY.search(n)


def form(name: str, facility_type: str | None, tribal_words: re.Pattern | None = None) -> str | None:
    n = name.lower()
    if tribal_words is not None and tribal_words.search(name) or re.search(r"\btrib(e|al)\b|\bnation\b", n) \
            or facility_type == "Tribal Government":
        return "tribal"
    if re.search(r"\bu\.?s\.?\b|united states|national park|federal|bureau of|\busbor\b|\bnps\b|\barmy\b|"
                 r"air force|forest service|\bdoi\b", n) or (facility_type or "").startswith("Federal"):
        return "federal facility"
    if re.search(r"department of (corrections|transportation|local affairs)|dept of (corrections|transportation)|"
                 r"\bcdot\b|\bwydot\b|\bcdpw\b|state park|state parks|\bcpw\b|correctional|state hospital|"
                 r"university|\bdnrc\b|montana department|colorado department|colorado dept", n) \
            or facility_type == "State Government":
        return "state facility"
    if re.search(r"homeowners|home owners|\bhoa\b|neighborhood association|property owners", n):
        return "homeowners' association"
    if re.search(r"mobile home|\bmhp\b|mobile manor|manufactured home", n):
        return "mobile-home park"
    if re.search(r"\bschool dist|school district|public schools|\bre-?\d|\bsd\b", n):
        return "special district"
    if re.search(r"\bauthority\b|joint powers|joint sewer|\bboard of public utilities\b|utilities commission|"
                 r"utility commission", n):
        return "authority"
    if re.search(r"\bdistrict\b|\bmetropolitan\b", n):
        return "special district"
    if re.search(r"water and sewer|sewer and water|water-sewer|water sewer", n):
        return "special district"
    if re.search(r"\bresort\b|\bcampground\b|\brv park\b|\blodge\b", n) and not re.search(
            r"\b(city|town|county) of\b|\bcounty\b", n):
        return "campground or resort"
    if re.search(r"\bclub\b", n):
        return "private club"
    if re.search(r"\bcounty\b|commissioners", n):
        return "county"
    if re.search(r"^town of\b|\btown\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity\b", n):
        return "city"
    if re.search(r"\b(school|institute|diocese|mission|church|camp)\b", n):
        return "institution"
    if re.search(r"\b(llc|inc|corp|corporation|company|ltd|co\.?)\b", n) or facility_type in (
            "Privately Owned Facility", "NON-POTW"):
        return "business or industrial"
    return None


PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}


def load_plants(st: str) -> dict[str, list[dict]]:
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == st and r.get("npdes_permit"):
            plants[r["npdes_permit"].upper()].append(r)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if str(r.get("npdes_permit") or "").startswith(st):
            raise SystemExit(f"{st} has a combined sewer permit in data/outfalls-us.json: handle it ({r['npdes_permit']})")
    return plants


def name_for(p: str, pl: list[dict], cand: dict, overrides: dict) -> tuple[str, str]:
    if p in overrides:
        return overrides[p], "the permittee's own name (EPA's spelling in the notes)"
    removed = cand.get("permittee_as_recorded") == REMOVED or cand.get("facility") == REMOVED
    pn = (pl[0].get("permit_name") or "") if pl else ""
    if pn and BODY.search(pn) and not personish(tidy(pn)):
        return pn, "EPA ICIS-NPDES permit name"
    rec = cand.get("permittee_as_recorded")
    if rec and rec != REMOVED and BODY.search(rec) and not personish(tidy(rec)):
        return rec, "EPA's permittee as recorded (private-utility candidates file)"
    fac = (pl[0].get("permittee") if pl else None) or cand.get("facility")
    if fac and fac != REMOVED and (BODY.search(fac) or not removed) and not personish(tidy(fac)):
        return fac, "EPA ICIS-NPDES facility name (the owning body is not in the file)"
    return f"Sewage plant, permit {p}", "EPA gives no name that can be shown"


def build_rows(st: str, *, checked: str, channel, epa_channel, names: dict, forms: dict, tribal_words: re.Pattern,
               epa_issued_extra: set, notes_by_permit: dict, kinds: dict | None = None,
               short_names: dict | None = None, federal_is_epa: bool = False,
               row_ids: dict | None = None) -> tuple[list[dict], Counter]:
    """Rows for one state. channel(row) and epa_channel(row) return the notification_channel text."""
    sl = st.lower()
    plants = load_plants(st)
    cand_doc = json.loads((ROOT / "research" / sl / "private-utilities-candidates.json").read_text())
    cands = {c["npdes_permit"]: c for c in cand_doc["candidates"] + cand_doc.get("public_by_name", [])}
    private_cands = {c["npdes_permit"] for c in cand_doc["candidates"]}
    research = json.loads((ROOT / "research" / sl / "dischargers.json").read_text())
    seed = json.loads((ROOT / "research" / sl / "federal-seed.json").read_text())
    permits = set(plants) | {r["npdes_permit"] for r in research if r.get("npdes_permit")} \
        | {m["npdes_permit"] for m in seed.get("major_plant_permits") or []} | set(cands)
    counts = Counter()
    groups: dict[str, dict] = {}
    for p in sorted(permits):
        pl = plants.get(p) or []
        c = cands.get(p) or {}
        name, basis = name_for(p, pl, c, names)
        disp = tidy(name)
        ftype = pl[0].get("facility_type") if pl else None
        epa = bool(p in EPA_TABLE_PERMITS or TRIBAL_GP.match(p) or p in epa_issued_extra
                   or ftype == "Tribal Government" or tribal_words.search(disp)
                   or (federal_is_epa and (ftype or "").startswith("Federal")))
        lf = forms.get(p) or form(disp, ftype, tribal_words) or (
            c.get("legal_form_proposed") if p in private_cands else None)
        if lf == "facility (permittee not named)" or disp.startswith("Sewage plant, permit"):
            lf = lf or "facility (permittee not named)"
        key = compact(disp) if not disp.startswith("Sewage plant, permit") else compact(p)
        g = groups.setdefault(key, {"name": disp, "legal_form": lf, "permits": [], "basis": basis, "epa": set(),
                                    "private": p in private_cands and lf not in PUBLIC_FORMS})
        g["permits"].append(p)
        if epa:
            g["epa"].add(p)
        if g["legal_form"] is None and lf:
            g["legal_form"] = lf
        if not pl:
            counts["permits outside the plant table (candidates or research)"] += 1
    by_permit = {p: k for k, g in groups.items() for p in g["permits"]}
    for r in research:
        k = by_permit.get(r.get("npdes_permit"))
        if k:
            groups[k].setdefault("research", []).append(r)
    ids: set[str] = set()
    new = []
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["name"].lower()):
        ps = sorted(g["permits"], key=lambda p: (not (plants.get(p) and (plants[p][0].get("major_minor") == "Major")),
                                                  p))
        rs = g.get("research") or []
        rid = rs[0]["id"] if rs else next((row_ids[p] for p in ps if p in (row_ids or {})), None) \
            or f"{sl}-{slug(g['name'])}"
        if rid in ids:
            rid = f"{rid}-{ps[0].lower()}"
        ids.add(rid)
        rows = [x for p in ps for x in plants.get(p, [])]
        waters = list(dict.fromkeys([w for r in rs for w in r.get("receiving_waters") or []] +
                                    [x["receiving_water_echo"] for x in rows if x.get("receiving_water_echo")]))[:8]
        towns = list(dict.fromkeys(
            [t for r in rs for t in r.get("towns") or []]
            + sorted({smart_title(re.sub(r",.*", "", x["city"])) for x in rows
                      if x.get("city") and "UNKNOWN" not in x["city"].upper()})
            + sorted({smart_title(cands[p]["city"]) for p in ps if (cands.get(p) or {}).get("city")
                      and "UNKNOWN" not in cands[p]["city"].upper()})))
        facs = sorted({f"{tidy(x.get('permittee') or '')} ({x['npdes_permit']})" for x in rows
                       if x.get("permittee") and not personish(tidy(x["permittee"]))})
        notes = f"Owner: {g['basis']}."
        if facs:
            notes += " Plants: " + ", ".join(facs[:12]) + ("." if len(facs) <= 12 else f", and {len(facs) - 12} more.")
        for p in ps:
            if p in notes_by_permit:
                notes += " " + notes_by_permit[p]
        status = sorted({f"{x['npdes_permit']} {x.get('permit_status')}" for x in rows
                         if x.get("permit_status") in ("EXP", "TRM", "NON")})
        if status:
            notes += (" EPA's permit status: " + ", ".join(status) + " (EXP expired; a permit can be administratively "
                      "continued or renewed after EPA's file was written, so the row is kept).")
        if g["private"] or (g["legal_form"] not in PUBLIC_FORMS and g["legal_form"]):
            notes = "Privately owned. " + notes
        for r in rs:
            if r.get("notes") and r["notes"] not in ("Major permit.",):
                notes += " " + r["notes"]
        epa_ps = sorted(g["epa"])
        row = {"id": rid, "name": g["name"], "short_name": (short_names or {}).get(rid) or g["name"],
               "legal_form": g["legal_form"], "state": st,
               "kind": (kinds or {}).get(rid) or "plant", "npdes_permit": ps[0], "npdes_permits": ps,
               "receiving_waters": waters, "water_slugs": [],
               "outfall_count": len({(x["npdes_permit"], x["outfall"]) for x in rows
                                     if x.get("outfall") not in (None, "")}) or None,
               "outfalls_source": (f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                   if rows else None),
               "notification_channel": None, "notification_feed_machine_readable": False,
               "notification_signup_url": None, "towns": towns, "notes": notes.strip(),
               "verified": next((r["verified"] for r in rs if r.get("verified") == "fetched"),
                                rs[0]["verified"] if rs else "inferred"),
               "checked": checked, "aliases": list(dict.fromkeys([rid, *[r["id"] for r in rs]])),
               "source_areas": [sl], "epa_issued_permits": epa_ps}
        row["notification_channel"] = epa_channel(row) if epa_ps and len(epa_ps) == len(ps) else channel(row)
        if epa_ps and len(epa_ps) < len(ps):
            row["notification_channel"] += " " + epa_channel(row)
        if not row["legal_form"]:
            row.pop("legal_form")
        new.append(row)
        counts["rows with research" if rs else ("private rows" if g["private"] else "rows")] += 1
        if epa_ps:
            counts["rows with EPA-issued permits"] += 1
    allp = [p for r in new for p in r["npdes_permits"]]
    dup = [p for p, c in Counter(allp).items() if c > 1]
    if dup:
        raise SystemExit(f"permits in two rows: {dup}")
    missing = permits - set(allp)
    if missing:
        raise SystemExit(f"permits with no row: {sorted(missing)}")
    return sorted(new, key=lambda r: r["id"]), counts


def write(st: str, new: list[dict], dry_run: bool) -> list[dict]:
    """Replace the state's rows (state st, source_areas [st]) where they stood; first run: after the last row."""
    sl = st.lower()
    dis = json.loads(DIS.read_text())
    mine = lambda d: d.get("state") == st and sl in (d.get("source_areas") or [])  # noqa: E731
    first = next((i for i, d in enumerate(dis) if mine(d)), None)
    keep = [d for d in dis if not mine(d)]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    clash = sorted(p for r in new for p in r["npdes_permits"] if p in held)
    if clash:
        raise SystemExit(f"permits already held by another row: {clash}")
    taken = {d["id"] for d in keep} | {a for d in keep for a in d.get("aliases") or []}
    dupe = sorted(r["id"] for r in new if r["id"] in taken)
    if dupe:
        raise SystemExit(f"ids already used: {dupe}")
    at = first if first is not None else len(keep)
    out = keep[:at] + new + keep[at:]
    if not dry_run:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def report(st: str, new: list[dict], counts: Counter) -> str:
    return json.dumps({"rows": len(new), "permits": sum(len(r["npdes_permits"]) for r in new),
                       "counts": dict(counts), "legal_form": dict(Counter(r.get("legal_form") for r in new)),
                       "kind": dict(Counter(r["kind"] for r in new)),
                       "epa_issued_permits": sum(len(r["epa_issued_permits"]) for r in new)}, indent=1)
