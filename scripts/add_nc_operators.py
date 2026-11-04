"""North Carolina operator rows for data/dischargers.json: one row per public operator, every permit in one row.

Usage (after the SSO ingester has written its events files, with --backfill once):
    pipeline/.venv/bin/python -I scripts/add_nc_operators.py [--dry-run]

Inputs
  - research/nc/dischargers.json: the ten collection systems with the most 2026 overflows (Charlotte Water ...),
    with the notification channels the research found. Each becomes a registry row under its research id.
  - data/build/events/nc-dwr-sso-2026.json and nc-dwr-sso-2022-2025.json (pipeline/ingest/nc_dwr_sso.py): the
    collection-system permits (WQCS...) DWR's layers name. The owner comes from the history layer, where a public
    body is named (raw._owner_public: a city, town, county, authority, district, commission ...); a permit with no
    public owner on record (a utility company, an association, a park, or a 2026-only permit) gets no row here
    (the owner has not decided on private utilities; scripts/add_federal_operators.py skips them too).
  - data/outfalls-plants-us.json: EPA ICIS-NPDES treatment-plant permits for North Carolina (322). Its
    `permit_name` is the owner (City of Hickory) and `permittee` the plant (NORTHEAST WWTP), so plants are grouped
    by owner. Private plants are skipped with add_federal_operators.private_reason.

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
  - Idempotent: a permit already in any registry row is not added again; an id already present is left alone.
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
EVENTS = [ROOT / "data" / "build" / "events" / f for f in ("nc-dwr-sso-2026.json", "nc-dwr-sso-2022-2025.json")]
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
LAW = ("Press release to news media within 24 hours for 1,000 gallons or more reaching surface waters; newspaper notice "
       "for 15,000 gallons or more (G.S. 143-215.1C(b)). No web posting is required; none searched for this operator.")

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
OWNER_ALIASES = {"onwasa": "onslow water and sewer authority", "aqua north carolina inc": None,
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


def feed_permits() -> tuple[dict[str, Counter], dict[str, str]]:
    """(WQCS permit -> Counter of public owner names from the history layer (empty for a 2026-only permit),
    WQCS permit -> the layer's facility name)."""
    out: dict[str, Counter] = defaultdict(Counter)
    fac: dict[str, str] = {}
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
    return out, fac


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

    groups: dict[str, dict] = {}                     # owner key -> {names, wqcs, plants}
    def group(k):
        return groups.setdefault(k, {"names": Counter(), "wqcs": set(), "plants": set()})
    skipped = Counter()
    feed, fac = feed_permits()
    unowned = []
    for permit, owners in feed.items():
        names = [(n, c) for n, c in owners.most_common() if n]
        if not names:
            unowned.append(permit)
            continue
        g = group(key(names[0][0]))
        g["names"][names[0][0]] += names[0][1]
        g["wqcs"].add(permit)
    plants = plant_permits()
    for permit, rows in plants.items():
        why = private_reason(permit, {"rows": rows, "files": {"plants"}})
        if why:
            skipped[f"plant: {why}"] += 1
            continue
        owner = rows[0].get("permit_name") or rows[0].get("permittee")
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
    new_rows, added_permits = [], 0
    for k in sorted(groups):
        g = groups[k]
        rid = by_key.get(k)
        wqcs = sorted(g["wqcs"])
        npdes = sorted(g["plants"], key=lambda p: (not p.startswith("NC0"), p))
        prow = [r for p in npdes for r in plants[p]]
        waters = list(dict.fromkeys(w for r in prow if (w := (r.get("receiving_water_echo") or "").strip())))[:8]
        name = (RESEARCH_OWNERS[rid][0] if rid else NAME_OVERRIDE.get(k) or
                next((n for n, _ in g["names"].most_common() if re.match(r"^(City|Town|Village) of ", n)), None)
                or g["names"].most_common(1)[0][0])
        towns = list(dict.fromkeys([t for t in [own_place(name)] if t] +
                                   [title(r.get("city")) for r in prow if r.get("city")]))
        rid = rid or f"nc-{slug(k)}"
        if rid in have_ids and rid not in RESEARCH_OWNERS:
            rid = f"{rid}-{slug(wqcs[0] if wqcs else npdes[0])}"
        if rid in have_ids:
            continue                                 # already in the registry: left alone (idempotent)
        permits = [p for p in wqcs + npdes if p.upper() not in have_permits]
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
        else:
            row = {"id": rid, "name": name, "state": "NC", "kind": "sso" if wqcs else "plant", "npdes_permit": first,
                   "npdes_permits": permits, "receiving_waters": waters, "water_slugs": [],
                   "outfall_count": len(prow) or None, "outfalls_source": src,
                   "notification_channel": LAW if wqcs else "None found online (not searched individually)",
                   "notification_feed_machine_readable": False, "notification_signup_url": None, "towns": towns,
                   "notes": ("Row made from the sources' own names: "
                             + (f"collection-system permit {', '.join(wqcs)} and its owner from the NC DWR SSO layers"
                                if wqcs else "") + ("; " if wqcs and npdes else "")
                             + (f"treatment-plant permit {', '.join(npdes)} from EPA ICIS-NPDES (owner as ICIS names it)"
                                if npdes else "")
                             + (f" ({', '.join(g['by_facility_name'])} joined by DWR's facility name, which names this "
                                "place; the 2026 layer gives no owner)" if g.get("by_facility_name") else "")
                             + ". No contact or notification channel was researched (scripts/add_nc_operators.py). "
                               "Not verified."),
                   "verified": False, "checked": TODAY, "aliases": [rid], "source_areas": ["nc"]}
            if len(name) > 30:
                row["short_name"] = re.sub(r"^(City|Town|Village) of ", "", name)
        have_ids.add(rid)
        have_permits |= {p.upper() for p in permits}
        new_rows.append(row)
    out = dis + new_rows
    claims = Counter(p for d in out for p in (d.get("npdes_permits") or []))
    twice = [p for p, n in claims.items() if n > 1]
    if twice:
        print(f"refusing: permits in two rows {twice[:10]}", file=sys.stderr)
        return 1
    print(f"collection permits joined by facility name: {by_name}")
    print(f"NC operator rows: {len(new_rows)} new ({sum(1 for r in new_rows if r['kind'] == 'sso')} with a collection "
          f"permit), {added_permits} permits; skipped {dict(skipped)}" + (" (dry run)" if dry else ""))
    if not dry:
        tmp = DIS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        tmp.replace(DIS)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
