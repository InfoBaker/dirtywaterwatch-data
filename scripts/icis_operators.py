"""Operator rows for data/dischargers.json from EPA ICIS-NPDES, shared by the Minnesota and North Dakota scripts
(scripts/add_mn_operators.py, scripts/add_nd_operators.py; Ohio's scripts/add_oh_operators.py is the model).

Not run by itself. A state script calls build(cfg, dischargers) with its own law text, research files and name rules.

Inputs (per state)
  1. data/outfalls-plants-us.json: EPA ICIS-NPDES's sewage-plant permits of the state; the permittee of record is
     EPA's permit_name ("Little Falls city of", "Gwinner City Of", "Metropolitan Council"); EPA's permittee field holds
     the facility's name ("LITTLE FALLS WTP").
  2. data/outfalls-us.json: EPA's national CSO inventory rows of the state (closed outfalls count as none open).
  3. research/<st>/dischargers.json: each research id stays as an alias of the row that holds its permit (or, for a
     research row with no permit, of the row cfg.research_permit names), so a feed's discharger_id resolves.
  4. research/<st>/private-utilities-candidates.json: legal_form from the file's proposal (docs/legal-forms.md); a
     permittee the file removed (a person's name) is never named: the row names the facility, or the permit only.
Grouping: permits whose permittee of record reads as the same body after normalising ("Little Falls city of" and
  "City of Little Falls") are one row. A name that gives only the plant ("Montevideo WWTP") stays its own row: the
  body is not guessed.
Rules: legal_form from the name (form()); the notification channel is the state's law text, then the research row's
  channel; idempotent (a rerun replaces the rows it wrote: source_areas [<st>]); never an individual's name.
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
ABBR = {"llc", "lp", "ii", "iii", "wwtp", "wwtf", "wpcf", "wpc", "wrf", "wrrf", "stp", "msd", "mhp", "mhc", "usa", "us",
        "sd", "rv", "ymca", "ywca", "inc", "wlssd", "mces", "ssd", "wtp", "nfh", "mha", "cso", "wwsl", "afb"}
PUBLIC_FORMS = {"city", "town", "county", "authority", "special district", "federal facility", "state facility", "tribal"}
PRIVATE_FORMS = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)"}


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


def tidy(name: str, state_words: tuple[str, ...] = ()) -> str:
    """A display name: 'Little Falls city of' -> 'City of Little Falls'; 'Gwinner City Of' -> 'City of Gwinner';
    'Valley City City Of' -> 'City of Valley City'; 'BENSON' -> 'Benson'; 'Co' -> 'County'."""
    s = " ".join((name or "").split()).strip(" ,")
    if s.isupper() or s.islower():
        s = smart_title(s)
    m = re.match(r"^(.+?),?\s+(City|Village|Township|Town|County)\s+of\.?$", s, re.I)
    if m:
        s = f"{m.group(2).title()} of {m.group(1).strip(' ,')}"
    s = re.sub(r"\bCo\b\.?", "County", s)
    s = re.sub(r"^The\s+", "", s)
    for w in state_words:
        s = re.sub(rf",?\s*\b{re.escape(w)}\.?$", "", s).strip(" ,")
    s = s[0].upper() + s[1:] if s else s
    return re.sub(r"\bOf\b", "of", re.sub(r"\bAnd\b", "and", s))


def compact(s: str, state_words: tuple[str, ...] = ()) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\b(inc|llc)\b\.?", "", s)
    for w in state_words:
        s = re.sub(rf"\b{re.escape(w.lower())}\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def form(name: str, facility_type: str | None, by_name: dict) -> str | None:
    n = name.lower()
    if name in by_name:
        return by_name[name]
    if facility_type == "Tribal Government" or re.search(r"\btribal\b|\btribes?\b|\bband of\b|\breservation\b", n):
        return "tribal"
    if re.search(r"army|air force|\bafb\b|u\.? ?s\.? (army|dept|department|fish)|united states|national park|federal|"
                 r"veterans|\bnfh\b|national fish hatchery|corps of engineers|bureau of", n) \
            or facility_type in ("Federal Facility (U.S. Government)", "FEDERAL"):
        return "federal facility"
    if re.search(r"state park|university|\bstate of\b|department of (natural resources|transportation|corrections)|"
                 r"correctional|rest area|\bdnr\b|\bdot\b", n) or facility_type == "State Government":
        return "state facility"
    if re.search(r"sanitary (sewer )?district|\bsewer district\b|\bwater (and sewer )?district\b|"
                 r"\bsanitary sewer board\b|\bmetropolitan council\b|\bschool district\b|\bpublic schools?\b|"
                 r"\b(sewer|sanitary|service|utility|improvement) district\b|\bjoint powers\b", n):
        return "special district"
    if re.search(r"\bcounty\b", n) or facility_type == "County Government":
        return "county"
    if re.search(r"\bauthority\b|\bcommission\b", n):
        return "authority"
    if re.search(r"\btownship\b|\btwp\b|^town of\b", n):
        return "town"
    if re.search(r"^city of\b|\bcity of\b", n):
        return "city"
    if re.search(r"hutterite|hutterian|\bbrethren\b|\bcolony\b|\bbible camp\b|\bchurch\b|\bacademy\b|\bnursing\b", n):
        return "institution"
    if re.search(r"\b(llc|llp|inc|corp|corporation|company|co-?op|cooperative|ltd|l\.p\.|partnership|systems|"
                 r"paper|properties|management|solutions|energy|sugar|industries|foods?)\b", n):
        return "business or industrial"
    if re.search(r"\bmhp\b|\bmhc\b|mobile home|manufactured home|trailer (court|park)", n):
        return "mobile-home park"
    if re.search(r"\bresort\b|\bcampground\b|\bcamp\b|\bkoa\b|\brv park\b", n):
        return "campground or resort"
    if re.search(r"\bassociation\b|\bhomeowners\b", n):
        return "homeowners' association"
    if facility_type in ("Municipality", "Municipal or Water District", "POTW"):
        return "city"
    return None


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def build(cfg: dict, dis: list[dict]) -> tuple[list[dict], Counter]:
    """(dischargers with the state's rows replaced, counts). cfg: state, area, checked, research, candidates,
    channel(rs, private, is_cso) -> str, research_name {permit: name}, research_permit {research id: permit},
    form_by_name {name: form}, state_words (('Minnesota', 'MN'))."""
    st, area = cfg["state"], cfg["area"]
    words = tuple(cfg.get("state_words") or ())
    keep = [d for d in dis if not (d.get("state") == st and area in (d.get("source_areas") or []))]
    held = {str(p).upper() for d in keep for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    ids = {d["id"] for d in keep}
    plants: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == st and r.get("npdes_permit"):
            plants[r["npdes_permit"].upper()].append(r)
    cso: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(CSO.read_text())["outfalls"]:
        if str(r.get("npdes_permit") or "").startswith(st):
            cso[r["npdes_permit"].upper()].append(r)
    cand = json.loads(Path(cfg["candidates"]).read_text())
    cands = {c["npdes_permit"]: c for c in cand["candidates"]}
    public_by_name = {c["npdes_permit"] for c in cand.get("public_by_name") or []}
    research = json.loads(Path(cfg["research"]).read_text())
    rperm = cfg.get("research_permit") or {}
    res_by_permit: dict[str, list[dict]] = defaultdict(list)
    for r in research:
        p = r.get("npdes_permit") or rperm.get(r["id"])
        if p:
            res_by_permit[p].append(r)
    rname = cfg.get("research_name") or {}
    by_name = cfg.get("form_by_name") or {}
    counts = Counter()
    groups: dict[str, dict] = {}
    for p in sorted(set(plants) | set(cso) | set(cands) | set(res_by_permit)):
        if p in held:
            continue
        c = cands.get(p) or {}
        pl = plants.get(p) or []
        if p in rname:
            name, basis = rname[p], "the operator's own name (research)"
        elif pl and pl[0].get("permit_name") and c.get("permittee_as_recorded") != REMOVED:
            name, basis = pl[0]["permit_name"], "EPA ICIS-NPDES permittee of record"
        elif c and c.get("permittee_as_recorded") not in (None, REMOVED):
            name, basis = c["permittee_as_recorded"], "EPA ICIS-NPDES permittee (private-utility candidates)"
        elif c.get("permittee_as_recorded") == REMOVED:
            fac = c.get("facility") if c.get("facility") not in (None, REMOVED) else None
            groups[f"withheld:{p}"] = {"name": f"{tidy(fac, words)} (permit {p})" if fac else f"Sewage plant, permit {p}",
                                       "legal_form": "facility (permittee not named)", "permits": [p], "private": True,
                                       "basis": "EPA's permittee name reads as an individual's: not named here"}
            continue
        elif pl and pl[0].get("permittee"):
            name, basis = pl[0]["permittee"], "EPA ICIS-NPDES facility name (no permittee of record)"
        elif cso.get(p):
            name, basis = cso[p][0]["permittee"], "EPA's CSO inventory (the facility's name)"
        elif res_by_permit.get(p):
            name, basis = res_by_permit[p][0]["name"], "the research row's name"
        else:
            continue
        disp = tidy(name, words)
        ft = pl[0].get("facility_type") if pl else None
        lf = form(disp, ft, by_name)
        private = False
        if c and p not in public_by_name and lf not in PUBLIC_FORMS:
            lf = c.get("legal_form_proposed") if c.get("legal_form_proposed") in PRIVATE_FORMS else lf
            private = True
        g = groups.setdefault(compact(disp, words), {"name": disp, "legal_form": lf, "permits": [], "private": private,
                                                     "basis": basis})
        g["permits"].append(p)
        if g["legal_form"] is None and lf:
            g["legal_form"] = lf
        g["private"] = g["private"] or private
    by_permit = {p: k for k, g in groups.items() for p in g["permits"]}
    no_permit_research = []
    for r in research:
        p = r.get("npdes_permit") or rperm.get(r["id"])
        if p and p in by_permit:
            groups[by_permit[p]].setdefault("research", []).append(r)
        else:
            k = compact(tidy(r["name"], words), words)
            if k in groups:
                groups[k].setdefault("research", []).append(r)
            else:
                no_permit_research.append(r)
    new = []
    for k, g in sorted(groups.items(), key=lambda kv: kv[1]["name"].lower()):
        ps = list(dict.fromkeys(g["permits"]))
        rs = g.get("research") or []
        rid = rs[0]["id"] if rs else f"{area}-{slug(g['name'])}"
        if rid in ids:
            rid = f"{rid}-{ps[0].lower()}"
        new.append(make_row(cfg, rid, g, ps, rs, plants, cso, cands))
        ids.add(rid)
        counts["research rows" if rs else ("private rows" if g["private"] else "public rows")] += 1
    for r in no_permit_research:          # operators known only from the research (no permit of their own here)
        g = {"name": tidy(r["name"], words), "legal_form": form(tidy(r["name"], words), None, by_name),
             "private": False, "basis": "the research row (no permit of its own in EPA's files)"}
        new.append(make_row(cfg, r["id"], g, [], [r], plants, cso, cands, kind=r.get("kind") or "sso"))
        counts["research rows without a permit"] += 1
    new.sort(key=lambda r: r["id"])
    allp = [p for r in new for p in r["npdes_permits"]]
    dup = [p for p, c in Counter(allp).items() if c > 1]
    if dup:
        raise SystemExit(f"permits in two rows: {dup}")
    return keep + new, counts


def make_row(cfg, rid, g, ps, rs, plants, cso, cands, kind=None) -> dict:
    words = tuple(cfg.get("state_words") or ())
    rows = [x for p in ps for x in plants.get(p, [])]
    crow = [x for p in ps for x in cso.get(p, [])]
    open_cso = [x for x in crow if not str(x.get("outfall_status") or "").upper().startswith("CLS")]
    waters = list(dict.fromkeys([w for r in rs for w in r.get("receiving_waters") or []] +
                                [x["receiving_water_echo"] for x in rows + crow if x.get("receiving_water_echo")]))[:8]
    withheld = g["legal_form"] == "facility (permittee not named)"
    towns = list(dict.fromkeys([t for r in rs for t in r.get("towns") or []] +
                               (sorted({smart_title(x["city"]) for x in rows + crow if x.get("city")}) if not withheld
                                else [])))
    facs = sorted({f"{tidy(x.get('permittee') or '', words)} ({x['npdes_permit']})" for x in rows
                   if x.get("permittee") and (cands.get(x["npdes_permit"]) or {}).get("facility") != REMOVED})
    notes = f"Owner: {g['basis']}."
    if facs and not withheld:
        notes += " Plants: " + ", ".join(facs[:12]) + ("." if len(facs) <= 12 else f", and {len(facs) - 12} more.")
    if crow:
        notes += f" EPA's CSO inventory: {len(open_cso)} open and {len(crow) - len(open_cso)} closed combined sewer outfalls."
    for r in rs:
        if r.get("notes"):
            notes += " " + r["notes"]
    lf = (cfg.get("form_by_name") or {}).get(g["name"], g["legal_form"])
    private = (g["private"] and lf not in PUBLIC_FORMS) or lf in PRIVATE_FORMS
    return {"id": rid, "name": g["name"], "short_name": g["name"], "legal_form": lf, "state": cfg["state"],
            "kind": kind or ("cso" if open_cso else "plant"), "npdes_permit": ps[0] if ps else None,
            "npdes_permits": ps, "receiving_waters": waters, "water_slugs": [],
            "outfall_count": (len(open_cso) or len(rows) or None),
            "outfalls_source": ("EPA National CSO Inventory (data/outfalls-us.json)" if open_cso else
                                f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(rows)} rows)"
                                if rows else None),
            "notification_channel": cfg["channel"](rs, private, bool(open_cso)),
            "notification_feed_machine_readable": any(r.get("notification_feed_machine_readable") for r in rs),
            "notification_signup_url": None, "towns": towns, "notes": notes.strip(),
            "verified": next((r["verified"] for r in rs if r.get("verified") == "fetched"),
                             rs[0]["verified"] if rs else "inferred"),
            "checked": cfg["checked"], "aliases": list(dict.fromkeys([rid, *[r["id"] for r in rs]])),
            "source_areas": [cfg["area"]]}


def run(cfg: dict, argv: list[str]) -> int:
    dis = json.loads(DIS.read_text())
    out, counts = build(cfg, dis)
    new = [d for d in out if d.get("state") == cfg["state"] and cfg["area"] in (d.get("source_areas") or [])]
    print(json.dumps(dict(counts), indent=1),
          f"\n{cfg['state']} rows {len(new)}, permits {sum(len(r['npdes_permits']) for r in new)}")
    print("legal_form:", dict(Counter(r.get("legal_form") for r in new)))
    print("kind:", dict(Counter(r.get("kind") for r in new)))
    if "--dry-run" not in argv:
        DIS.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0
