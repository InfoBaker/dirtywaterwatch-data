"""North Carolina operator rows for data/dischargers.json: one row per public operator, every permit in one row.

Usage (after the SSO ingester has written its events files, with --backfill once):
    pipeline/.venv/bin/python -I scripts/add_nc_operators.py [--dry-run]

Inputs
  - research/nc/dischargers.json: the ten collection systems with the most 2026 overflows (Charlotte Water ...),
    with the notification channels the research found. Each becomes a registry row under its research id.
  - data/build/events/nc-dwr-sso-2026.json and nc-dwr-sso-2022-2025.json (pipeline/ingest/nc_dwr_sso.py): the
    collection-system permits (WQCS...) DWR's layers name. The owner comes from the history layer, where a public
    body is named (raw._owner_public: a city, town, county, authority, district, commission ...). Every other
    permit (a utility company, an association, a park, a person, or a permit seen only on the 2026 layer, which has
    no owner field) takes its permittee from research/nc/private-utilities.json.
  - research/nc/private-utilities.json: the permittee of each such permit as DWR's own permit records name it (the
    Water Quality Permitting document repository), with legal_form (LEGAL_FORMS), facility, towns and the document
    cited; and the EPA plant permits whose owner is private. Private utilities are covered like any other operator
    (G.S. 143-215.1C binds "the owner or operator of any wastewater collection or treatment works"). A permittee who
    is an individual is never named: that row names the facility, legal_form "facility (permittee not named)".
  - data/outfalls-plants-us.json: EPA ICIS-NPDES treatment-plant permits for North Carolina (322). Its
    `permit_name` is the owner (City of Hickory) and `permittee` the plant (NORTHEAST WWTP), so plants are grouped
    by owner. A plant add_federal_operators.private_reason flags is kept when its owner is a public body by name
    (ICIS calls some public plants NON-POTW) or the research file names its permittee; any other is skipped.

Rules
  - Owners match by key(): lower case, punctuation dropped, a leading "city of", "town of", "village of" dropped and
    trailing "public utilities", "public works", "utilities", "water system", "general services" dropped; the word
    county stays (Durham County and the City of Durham are two operators). OWNER_ALIASES joins the spellings that
    key() cannot ("ONWASA", "PWC/Fayetteville", "Cpe Fear Public Utility Auth W" ...).
  - A researched operator keeps its research id and gains the plant permits of its owner key.
  - Every other public owner with a permit gets a row: id nc-<key slug>, name as DWR (else EPA) spells the owner,
    kind "sso" when it holds a collection-system permit (else "plant"), npdes_permit its first NPDES permit (else
    the collection-system permit), receiving_waters and towns from EPA's plant rows (and the owner's own place),
    notification_channel the statutory press release, verified false.
  - A private operator gets one row for all its permits: id nc-<slug of the operator>, name and legal_form from the
    research file, towns from it, receiving_waters from the overflow reports under its permits (then EPA's plant
    rows), notification_channel the statutory press release ((c) for an industrial system), permit_note citing
    each permit's DWR document.
  - An operator whose row exists (same id and the same owner by key(), or a researched row) gains the permits of
    its owner that no row holds yet; a different owner whose slug is taken gets the slug plus its first permit.
  - Idempotent: a permit already in any registry row is not added again. New rows go in after the last North
    Carolina row (the state's block stays together).
Writes data/dischargers.json (indent 1) and prints counts.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from add_federal_operators import private_reason, title  # noqa: E402

TODAY = date.today().isoformat()
DIS = ROOT / "data" / "dischargers.json"
RESEARCH = ROOT / "research" / "nc" / "dischargers.json"
PRIVATE = ROOT / "research" / "nc" / "private-utilities.json"
EVENTS = [ROOT / "data" / "build" / "events" / f for f in ("nc-dwr-sso-2026.json", "nc-dwr-sso-2022-2025.json")]
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
LAW = ("Press release to news media within 24 hours for 1,000 gallons or more reaching surface waters; newspaper notice "
       "for 15,000 gallons or more (G.S. 143-215.1C(b)). No web posting is required; none searched for this operator.")
LAW_C = ("Press release to news media within 24 hours for 1,000 gallons or more of untreated waste reaching surface "
         "waters; newspaper notice for 15,000 gallons or more (G.S. 143-215.1C(c), works other than municipal or "
         "domestic). No web posting is required; none searched for this operator.")
# legal_form an entry of research/nc/private-utilities.json may carry (the row it makes writes registry_form of it)
LEGAL_FORMS = ("private utility", "private company", "owners' association", "mobile-home park", "private club",
               "industrial facility", "facility (permittee not named)", "town", "county", "special district")
# a public body: grouped with its public owner key and never described as privately owned
PUBLIC_FORMS = ("town", "county", "special district")

# research id -> (public name, short name, owner keys)
RESEARCH_OWNERS = {
    "nc-charlotte-water": ("Charlotte Water", None, ["charlotte water"]),
    "nc-winston-salem": ("City of Winston-Salem", None, ["winston salem"]),
    "nc-greensboro": ("City of Greensboro", None, ["greensboro", "greensboro n buffalo crk wwtp"]),
    "nc-raleigh": ("City of Raleigh (Raleigh Water)", None, ["raleigh"]),
    "nc-hickory": ("City of Hickory", None, ["hickory"]),
    "nc-durham": ("City of Durham", None, ["durham"]),
    "nc-asheboro": ("City of Asheboro", None, ["asheboro"]),
    "nc-msd-buncombe": ("Metropolitan Sewerage District of Buncombe County", "MSD of Buncombe County",
                        ["metropolitan sewerage district of buncombe county north carolina",
                         "metropolitan sewerage district of buncombe county"]),
    "nc-cfpua": ("Cape Fear Public Utility Authority", "CFPUA", ["cape fear public utility authority",
                                                                 "cpe fear public utility auth w"]),
    "nc-pwc-fayetteville": ("Fayetteville Public Works Commission", "Fayetteville PWC",
                            ["fayetteville public works commission", "pwc fayetteville"]),
}
OWNER_ALIASES = {"onwasa": "onslow water and sewer authority",
                 "harnett co public util erwin w": "harnett county", "henderson county utilities": "henderson county",
                 "union county public works": "union county", "morven town": "morven",
                 "johnston county public utilities": "johnston county",
                 "bessemer city pretreatment pgm": "bessemer city", "ellerbe wwtp": "ellerbe",
                 "lincoln county forney crk wwtp": "lincoln county",
                 "eastern band of cherokee indians jacob cornsilk complex": "eastern band of cherokee indians",
                 "eastern band cherokee indians qualla boundary cherokee wwtp": "eastern band of cherokee indians",
                 "county of wake facilities design and construction": "wake county"}
NAME_OVERRIDE = {"eastern band of cherokee indians": "Eastern Band of Cherokee Indians", "wake county": "Wake County",
                 "morven": "Town of Morven"}
FACILITY = re.compile(r"^(.+?)\s+(collection system|wwtp|wwtf|wrf)$", re.I)
# a report's water text that names no water ("Private pond", "storm drain"): not a receiving water for the row
GENERIC_WATER = re.compile(r"^\s*(private|storm|ditch|ground|none|unknown|n/?a)\b", re.I)
TRAIL = re.compile(r"\s+(public utilities|public works|utilities|water system|general services)$")


def key(name) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower().replace("&", " and "))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(city|town|village) of ", "", s)
    s = TRAIL.sub("", s)
    return OWNER_ALIASES.get(s, s) if s in OWNER_ALIASES else s


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def own_place(name: str) -> str | None:
    m = re.match(r"^(?:City|Town|Village) of (.+?)(?:\s*\(.*\))?$", name or "", re.I)
    return title(m.group(1)) if m else None


def feed_permits() -> tuple[dict[str, Counter], dict[str, str], dict[str, Counter]]:
    """(WQCS permit -> Counter of public owner names from the history layer (empty for a 2026-only permit),
    WQCS permit -> the layer's facility name, WQCS permit -> Counter of the receiving waters its reports name)."""
    out: dict[str, Counter] = defaultdict(Counter)
    fac: dict[str, str] = {}
    waters: dict[str, Counter] = defaultdict(Counter)
    for p in EVENTS:
        if not p.exists():
            continue
        for r in json.loads(p.read_text()).get("records", []):
            permit = r.get("npdes_permit")
            if not permit:
                continue
            owner = (r.get("raw") or {}).get("_owner_public")
            out[permit][owner] += 1 if owner else 0
            if r.get("discharger_name"):
                fac.setdefault(permit, r["discharger_name"])
            if (r.get("waterbody_text") and (r.get("raw") or {}).get("reached_water") is not False
                    and not GENERIC_WATER.match(r["waterbody_text"])):
                waters[permit][r["waterbody_text"]] += 1
    return out, fac, waters


def private_research() -> tuple[dict[str, dict], dict[str, dict]]:
    """research/nc/private-utilities.json -> (collection permit -> entry, plant permit -> entry)."""
    if not PRIVATE.exists():
        return {}, {}
    d = json.loads(PRIVATE.read_text())
    for e in d.get("collection_permits", []) + d.get("plant_permits", []):
        if e.get("legal_form") not in LEGAL_FORMS:
            raise ValueError(f"{e.get('permit')}: legal_form {e.get('legal_form')!r} is not one of {LEGAL_FORMS}")
        if not e.get("operator"):
            raise ValueError(f"{e.get('permit')}: no operator name")
    return ({e["permit"]: e for e in d.get("collection_permits", [])},
            {e["permit"]: e for e in d.get("plant_permits", [])})


def public_by_name(name) -> bool:
    """A public body by its name (the DWR ingester's own test), for plants ICIS types as NON-POTW."""
    if str(ROOT / "pipeline") not in sys.path:
        sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest.nc_dwr_sso import owner_kind
    return owner_kind(name)[0] == "public"


def registry_form(form: str) -> str:
    """The research file's legal form as the registry writes it: the controlled value (ingest/dischargers_schema.py;
    "private utility" is an "investor-owned utility", "private company" and "industrial facility" are "business or
    industrial", "owners' association" is a "homeowners' association")."""
    if str(ROOT / "pipeline") not in sys.path:
        sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest.dischargers_schema import LEGACY
    return LEGACY.get(form, form)


def cite(e: dict) -> str:
    src = e.get("source") or {}
    when = f", {src['document_date']}" if src.get("document_date") else ""
    doc = f"{src.get('document')}{when}" if src.get("document") else src.get("title", "")
    return (f"{e['permit']} ({e.get('facility')}, {e.get('county')} County): permittee per {doc} "
            f"<{src.get('url')}>").replace(" County County", " County")


def plant_permits() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in json.loads(PLANTS.read_text())["outfalls"]:
        if r.get("state") == "NC" and r.get("npdes_permit"):
            out[r["npdes_permit"]].append(r)
    return out


def main(argv) -> int:
    dry = "--dry-run" in argv
    dis = json.loads(DIS.read_text())
    have_ids = {d["id"] for d in dis}
    have_permits = {str(p).upper() for d in dis for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])] if p}
    research = {r["id"]: r for r in json.loads(RESEARCH.read_text())}
    priv_cs, priv_plants = private_research()

    groups: dict[str, dict] = {}                     # owner key -> {names, wqcs, plants}
    def group(k):
        return groups.setdefault(k, {"names": Counter(), "wqcs": set(), "plants": set(), "research": []})
    skipped = Counter()
    feed, fac, feed_waters = feed_permits()

    def research_group(e):
        """The group of a permit the research file names: a public body joins its owner key, a private operator
        its own key (prefixed, so a company never merges with a public body of the same words)."""
        pub = e["legal_form"] in PUBLIC_FORMS
        g = group(key(e["operator"]) if pub else "private " + key(e["operator"]))
        g["names"][e["operator"]] += 0
        g["research"].append(e)
        g["private"] = not pub
        return g
    unowned = []
    for permit, owners in feed.items():
        names = [(n, c) for n, c in owners.most_common() if n]
        if not names:
            if permit in priv_cs:
                research_group(priv_cs[permit])["wqcs"].add(permit)
            else:
                unowned.append(permit)
            continue
        g = group(key(names[0][0]))
        g["names"][names[0][0]] += names[0][1]
        g["wqcs"].add(permit)
    plants = plant_permits()
    for permit, rows in plants.items():
        owner = rows[0].get("permit_name") or rows[0].get("permittee")
        if permit in priv_plants:
            research_group(priv_plants[permit])["plants"].add(permit)
            continue
        why = private_reason(permit, {"rows": rows, "files": {"plants"}})
        if why and not public_by_name(owner):
            skipped[f"plant: {why}"] += 1
            continue
        k = key(owner)
        if k is None:
            skipped["plant: owner alias marked private"] += 1
            continue
        g = group(k)
        g["names"][owner] += 0
        g["plants"].add(permit)

    # a 2026-only collection permit named "<Place> Collection System" joins the public owner of that place, when one
    # is on record (from the history layer or EPA's plants); the others get no row
    by_name = {}
    for permit in unowned:
        m = FACILITY.match(fac.get(permit) or "")
        k = key(m.group(1)) if m else None
        if k and k in groups and groups[k]["names"]:
            groups[k]["wqcs"].add(permit)
            groups[k].setdefault("by_facility_name", []).append(permit)
            by_name[permit] = k
        else:
            skipped["collection permit with no public owner on record"] += 1

    by_key = {k: rid for rid, (_, _, ks) in RESEARCH_OWNERS.items() for k in ks}
    by_id = {d["id"]: d for d in dis}
    new_rows, added_permits, grown = [], 0, {}

    def basis(p, g) -> str:
        e = next((e for e in g["research"] if e["permit"] == p), None)
        if e:
            return cite(e)
        if p in plants:
            r0 = plants[p][0]
            return (f"{p} from EPA ICIS-NPDES (owner as ICIS names it: {r0.get('permit_name')}; facility "
                    f"{title(r0.get('permittee'))})")
        return f"{p} and its owner from the NC DWR SSO layers"

    for k in sorted(groups):
        g = groups[k]
        rid = by_key.get(k)
        wqcs = sorted(g["wqcs"])
        npdes = sorted(g["plants"], key=lambda p: (not p.startswith("NC0"), p))
        prow = [r for p in npdes for r in plants[p]]
        reported = Counter()
        for p in wqcs:
            reported.update(feed_waters.get(p) or {})
        waters = list(dict.fromkeys([w for r in prow if (w := (r.get("receiving_water_echo") or "").strip())] +
                                    [w for w, _ in reported.most_common()]))[:8]
        name = (RESEARCH_OWNERS[rid][0] if rid else g["research"][0]["operator"] if g.get("private") else
                NAME_OVERRIDE.get(k) or
                next((n for n, _ in g["names"].most_common() if re.match(r"^(City|Town|Village) of ", n)), None)
                or g["names"].most_common(1)[0][0])
        towns = list(dict.fromkeys([t for t in [own_place(name)] if t] +
                                   [title(r.get("city")) for r in prow if r.get("city")] +
                                   [t for e in g["research"] for t in e.get("towns") or []]))
        # a private operator's id leaves out Inc, LLC and Ltd (nc-aqua-north-carolina)
        rid = rid or f"nc-{slug(re.sub(r'(?<= )(inc|llc|ltd)( |$)', ' ', k.removeprefix('private ')) if g.get('private') else k)}"
        existing = by_id.get(rid)
        if existing is not None and rid not in RESEARCH_OWNERS and not (
                existing.get("state") == "NC" and key(existing.get("name")) == k.removeprefix("private ")):
            rid = f"{rid}-{slug(wqcs[0] if wqcs else npdes[0])}"          # another owner holds the slug
            existing = by_id.get(rid)
        permits = [p for p in wqcs + npdes if p.upper() not in have_permits]
        if existing is not None:
            # the operator's row exists: it gains the permits of its owner that no row holds yet
            if permits:
                existing["npdes_permits"] = list(existing.get("npdes_permits") or []) + permits
                existing["npdes_permit"] = existing.get("npdes_permit") or permits[0]
                existing["towns"] = list(dict.fromkeys(list(existing.get("towns") or []) +
                                                       [t for e in g["research"] if e["permit"] in permits
                                                        for t in e.get("towns") or []]))
                added = [r for p in permits if p in plants for r in plants[p]]
                if added:
                    existing["outfall_count"] = (existing.get("outfall_count") or 0) + len(added)
                    existing["outfalls_source"] = "; ".join(x for x in [
                        existing.get("outfalls_source"), f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, "
                        f"{len(added)} rows for {', '.join(p for p in permits if p in plants)})"] if x)
                existing["notes"] = (f"{existing.get('notes') or ''} Permits added {TODAY} (scripts/add_nc_operators.py): "
                                     + "; ".join(basis(p, g) for p in permits) + ".").strip()
                grown[rid] = permits
                added_permits += len(permits)
                have_permits |= {p.upper() for p in permits}
            continue
        if rid in RESEARCH_OWNERS:
            rr = research[rid]
            permits = list(dict.fromkeys([rr["npdes_permit"], *permits]))
        if not permits:
            continue
        added_permits += len(permits)
        first = next((p for p in permits if p.startswith("NC")), permits[0])
        src = (f"EPA ICIS-NPDES Discharge Points (data/outfalls-plants-us.json, {len(prow)} rows for "
               f"{', '.join(npdes)})") if prow else None
        if rid in RESEARCH_OWNERS:
            rr = research[rid]
            short = RESEARCH_OWNERS[rid][1]
            row = {"id": rid, "name": name, "state": "NC", "kind": "sso", "npdes_permit": first, "npdes_permits": permits,
                   "receiving_waters": list(dict.fromkeys(rr.get("receiving_waters", []) + waters))[:10],
                   "water_slugs": [], "outfall_count": len(prow) or None, "outfalls_source": src,
                   "notification_channel": rr.get("notification_channel") if not str(rr.get("notification_channel") or "")
                   .startswith("not searched") else LAW,
                   "notification_feed_machine_readable": False, "notification_signup_url": None,
                   "towns": list(dict.fromkeys(rr.get("towns", []) + towns)),
                   "notes": (f"{rr.get('notes') or ''} Collection-system permit {rr['npdes_permit']} (NC DWR SSO layers); "
                             f"treatment-plant permits {', '.join(npdes) or 'none'} from EPA ICIS-NPDES, joined by the "
                             "owner's name (scripts/add_nc_operators.py).").strip(),
                   "verified": rr.get("verified"), "checked": rr.get("checked"), "aliases": [rid], "source_areas": ["nc"]}
            if short:
                row["short_name"] = short
        elif g.get("private"):
            ents = sorted(g["research"], key=lambda e: e["permit"])
            form = ents[0]["legal_form"]
            earlier = [f"{e['permit']}: {e['history_layer_owner']}" for e in ents if e.get("history_layer_owner")]
            row = {"id": rid, "name": name, "state": "NC", "legal_form": registry_form(form), "kind": "sso" if wqcs else "plant",
                   "npdes_permit": first, "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [],
                   "outfall_count": len(prow) or None, "outfalls_source": src,
                   "notification_channel": LAW_C if form == "industrial facility" else LAW,
                   "notification_feed_machine_readable": False, "notification_signup_url": None, "towns": towns,
                   "permit_note": "; ".join(cite(e) for e in ents if e["permit"] in permits) + ".",
                   "notes": ("Privately owned; covered like any other operator (G.S. 143-215.1C binds the owner or "
                             "operator of any permitted wastewater collection or treatment works). Permittee and "
                             "facilities from the permit records (research/nc/private-utilities.json: NC DWR's for a "
                             "collection-system permit, EPA ICIS-NPDES for a plant; each is cited in permit_note): "
                             + "; ".join(f"{e.get('facility')} ({e['permit']})" for e in ents if e["permit"] in permits)
                             + "." + "".join(f" {e['permittee_note']}" for e in ents if e.get("permittee_note"))
                             + (f" DWR's 2022-2025 overflow layer names an earlier owner ({'; '.join(earlier)}); its "
                                "reports under the permit are joined to this row." if earlier else "")
                             + (" Receiving waters as the overflow reports under these permits name them."
                                if reported else "")
                             + " No contact or notification channel was researched (scripts/add_nc_operators.py). "
                               "Not verified."),
                   "verified": False, "checked": TODAY, "aliases": [rid], "source_areas": ["nc"]}
            short = re.sub(r"\s+(Inc|LLC|Ltd)\b.*$", "", name, flags=re.I)
            if len(name) > 30 and short != name:
                row["short_name"] = short
        else:
            ents = sorted(g["research"], key=lambda e: e["permit"])
            row = {"id": rid, "name": name, "state": "NC", "kind": "sso" if wqcs else "plant", "npdes_permit": first,
                   "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [],
                   "outfall_count": len(prow) or None, "outfalls_source": src,
                   "notification_channel": LAW if wqcs else "None found online (not searched individually)",
                   "notification_feed_machine_readable": False, "notification_signup_url": None, "towns": towns,
                   "notes": ("Row made from the sources' own names: "
                             + (f"collection-system permit {', '.join(wqcs)} and its owner from the NC DWR SSO layers"
                                if wqcs and not ents else "")
                             + (f"collection-system permit {', '.join(wqcs)} from the NC DWR SSO layers, its owner from "
                                "DWR's permit records (research/nc/private-utilities.json; the overflow layers name no public owner for it)"
                                if wqcs and ents else "")
                             + ("; " if wqcs and npdes else "")
                             + (f"treatment-plant permit {', '.join(npdes)} from EPA ICIS-NPDES (owner as ICIS names it)"
                                if npdes else "")
                             + (f" ({', '.join(g['by_facility_name'])} joined by DWR's facility name, which names this "
                                "place; the 2026 layer gives no owner)" if g.get("by_facility_name") else "")
                             + ". No contact or notification channel was researched (scripts/add_nc_operators.py). "
                               "Not verified."),
                   "verified": False, "checked": TODAY, "aliases": [rid], "source_areas": ["nc"]}
            if ents:
                row["legal_form"] = registry_form(ents[0]["legal_form"])
                row["permit_note"] = "; ".join(cite(e) for e in ents if e["permit"] in permits) + "."
                pnotes = "".join(f" {e['permittee_note']}" for e in ents if e.get("permittee_note"))
                if pnotes:
                    row["notes"] = row["notes"].replace(". No contact or notification", "." + pnotes +
                                                        " No contact or notification", 1)
            if len(name) > 30:
                row["short_name"] = re.sub(r"^(City|Town|Village) of ", "", name)
        have_ids.add(rid)
        have_permits |= {p.upper() for p in permits}
        new_rows.append(row)
    # new rows go in after the last North Carolina row, so the state's rows stay together
    last_nc = max((i for i, d in enumerate(dis) if d.get("state") == "NC"), default=len(dis) - 1)
    out = dis[:last_nc + 1] + new_rows + dis[last_nc + 1:]
    claims = Counter(p for d in out for p in (d.get("npdes_permits") or []))
    twice = [p for p, n in claims.items() if n > 1]
    if twice:
        print(f"refusing: permits in two rows {twice[:10]}", file=sys.stderr)
        return 1
    print(f"collection permits joined by facility name: {by_name}")
    print(f"existing rows that gained permits: {grown}")
    print(f"NC operator rows: {len(new_rows)} new ({sum(1 for r in new_rows if r['kind'] == 'sso')} with a collection "
          f"permit; {sum(1 for r in new_rows if r.get('legal_form') in {registry_form(f) for f in LEGAL_FORMS} and r['legal_form'] not in PUBLIC_FORMS)} private), {added_permits} "
          f"permits; skipped {dict(skipped)}" + (" (dry run)" if dry else ""))
    if not dry:
        tmp = DIS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        tmp.replace(DIS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
