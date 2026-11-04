#!/usr/bin/env python3
"""National receiving-water target list: every water body an outfall discharges to, per state, with the operators
that discharge to it and the NHD identifiers EPA already gives, so each water gets a defined record before its
state goes live (owner, 2026-11-04: openboatlaunch does not cover all water bodies; every water body must be
clearly defined and mapped for connection with the appropriate operators).

Reads the outfall registries (data/outfalls-ne.json, data/outfalls-mid-atlantic.json, data/outfalls-us.json,
data/outfalls-plants-us.json) and the water records (data/waters-*.json) and writes

  data/receiving-waters-national.json   per state: one row per receiving water (name as the permit gives it,
                                        GNIS names, NHD reach codes and NHDPlus ids, outfalls by kind, operators,
                                        up to three points, the water record when one exists, how it can be
                                        defined: record | reach | name | point | unnamed)

and prints the per-state summary that docs/national-readiness.md carries. Run from the repository root:
  python3 -I scripts/gen_receiving_waters.py [--summary-only]

The NHD builder (pipeline/ingest/waters_from_nhd.py) is the consumer: a state's rows are its targets, the reach
codes and NHDPlus ids first (no snapping needed), names with points second, names alone third; unnamed outfalls
are snapped by point. Nothing here is public; the public outputs stay gated by data/rules.json live_states.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "receiving-waters-national.json"
TALLY = ROOT / "docs" / "national-waters-tally.md"

REGISTRIES = ["data/outfalls-ne.json", "data/outfalls-mid-atlantic.json", "data/outfalls-us.json",
              "data/outfalls-plants-us.json"]
NOT_WATERS = re.compile(r"^(none|n/?a|unknown|ground ?water|land|ground|soil|dry|evaporation|percolation|storm ?drain|"
                        r"storm sewer|municipal sewer|sanitary sewer|pond \(evaporation\)|spray field|"
                        r"leach(ing)? field|drain ?field|infiltration|reuse|irrigation|land application)\b", re.I)


def rows(path: pathlib.Path) -> list:
    d = json.loads(path.read_text())
    return d if isinstance(d, list) else d["outfalls"]


# EPA permit names sometimes carry a contact's name ("A. Person - City of X", or a bare name): never copied.
CONTACT = re.compile(r"^([A-Z][a-z]+(?: [A-Z]\.?)? [A-Z][A-Za-z'\-]+(?:, P\.E\.)?)\s*[-,]\s*(?=\S)")
CONTACT_SUFFIX = re.compile(r"^((City|Town|Village|Borough|Municipality)( (&|and) (County|Borough))? of [A-Z][a-z]|[A-Z]{3,6}$)")
BARE_PERSON = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.?)? [A-Z][a-z]+(?:, P\.E\.)?$")
ORG_WORDS = re.compile(r"\b(City|County|Water|Utilities|Utility|STP|WWTP|WWTF|WRRF|POTW|WPCF|WPCP|PWA|MUA|District|Authority|"
                       r"Township|Village|Board|Commission|Council|Department|Power|Sewer|Sewerage|Regional|Public|Works|Inc|"
                       r"Co|Corp|LLC|University|Base|Park|Service|Lake|Springs|Falls|Beach|Creek|River|Town|Borough|Metropolitan|"
                       r"Municipal|Plant|Facility|System|Association|Tribe|Nation|Pueblo|Hospital|School|Camp|Fort|Station|Valley|"
                       r"Hills|Heights|Point|Island|Harbor|Port|Bay|Sanitation|Sanitary|Wastewater|Environmental|Energy|Gas|"
                       r"Reclamation|Treatment|Joint|Parish|Community|Resort|Mill|Mills|Company|Enterprises|Industries|Estates|"
                       r"Center|College|Prison|Airport|Naval|Air|Army|Marine|National|State|Federal|Agency|Rural|Farm|Farms|Ranch|"
                       r"Dairy|Foods|Products|Paper|Chemical|Oil|Refinery|Mining|Mine|Coal|Timber|Lumber|Golf|Club|Inn|Hotel|Lodge|"
                       r"Campground|Apartments|East|West|North|South|Upper|Lower|Central|Saint|St|Mount|Mt|New|Old|Big|Little|Delta|"
                       r"Grand|Fair|Green|Spring|Cedar|Oak|Pine|Elk|Deer|Eagle|Bear|Buffalo|Red|White|Black|Blue|Silver|Gold)\b")


def safe_permittee(s: str | None) -> str | None:
    if not s:
        return s
    m = CONTACT.match(s)
    if m and CONTACT_SUFFIX.match(s[m.end():]):
        return s[m.end():]
    if BARE_PERSON.match(s) and not ORG_WORDS.search(s):
        return "permit holder (EPA permit name is a person; name withheld)"
    return s


def norm_name(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s.strip())
    s = s.strip(" .;,")
    if not s or NOT_WATERS.match(s):
        return None
    return s


def key_name(s: str) -> str:
    k = s.lower()
    k = re.sub(r"\b(unnamed|unt|un-named|tributary|trib\.?|to|of|the|a|an)\b", " ", k)
    k = re.sub(r"[^a-z0-9 ]", " ", k)
    return re.sub(r"\s+", " ", k).strip() or s.lower()


def water_records() -> dict:
    """{state: {slug: name}} from every data/waters-*.json file."""
    out: dict = collections.defaultdict(dict)
    for p in sorted((ROOT / "data").glob("waters-*.json")):
        try:
            d = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        recs = d if isinstance(d, list) else d.get("waters") or d.get("records") or []
        for r in recs:
            if isinstance(r, dict) and r.get("slug"):
                out[(r.get("state") or "").upper()][r["slug"]] = r.get("name")
    return out


def build() -> dict:
    live = set(json.loads((ROOT / "data" / "rules.json").read_text()).get("live_states", []))
    records = water_records()
    seen: set = set()
    waters: dict = collections.defaultdict(dict)   # state -> key -> row
    unnamed: dict = collections.defaultdict(list)  # state -> rows without a name
    for rel in REGISTRIES:
        p = ROOT / rel
        if not p.exists():
            continue
        for r in rows(p):
            dedupe = (r.get("npdes_permit"), str(r.get("outfall") or "").lstrip("0"))
            if dedupe in seen:
                continue
            seen.add(dedupe)
            st = (r.get("state") or "").upper()
            kind = r.get("outfall_kind") or "cso"
            closed = r.get("outfall_status") == "CLS"
            name = norm_name(r.get("receiving_water_echo")) or norm_name(r.get("reach_gnis_name"))
            if not name:
                unnamed[st].append({"permit": r.get("npdes_permit"), "outfall": r.get("outfall"), "kind": kind,
                                    "closed": closed, "lat": r.get("lat"), "lon": r.get("lon"),
                                    "reach_id": r.get("reach_id"), "nhdplus_id": r.get("nhdplus_id"),
                                    "water_slug": r.get("water_slug")})
                continue
            k = key_name(name)
            w = waters[st].get(k)
            if w is None:
                w = waters[st][k] = {"name": name, "names_seen": set(), "gnis_names": set(), "reach_ids": set(),
                                     "nhdplus_ids": set(), "outfalls": collections.Counter(), "operators": {},
                                     "points": [], "water_slugs": set()}
            w["names_seen"].add(name)
            if r.get("reach_gnis_name"):
                w["gnis_names"].add(r["reach_gnis_name"])
            if r.get("reach_id"):
                w["reach_ids"].add(str(r["reach_id"]))
            if r.get("nhdplus_id"):
                w["nhdplus_ids"].add(str(r["nhdplus_id"]))
            w["outfalls"]["closed" if closed else kind] += 1
            if r.get("npdes_permit"):
                w["operators"][r["npdes_permit"]] = safe_permittee(r.get("permittee") or r.get("permit_name"))
            if r.get("lat") and r.get("lon") and len(w["points"]) < 3:
                pt = [round(r["lat"], 5), round(r["lon"], 5)]
                if pt not in w["points"]:
                    w["points"].append(pt)
            if r.get("water_slug"):
                w["water_slugs"].add(r["water_slug"])
    out_states: dict = {}
    for st in sorted(set(waters) | set(unnamed)):
        ws = []
        for k, w in sorted(waters[st].items(), key=lambda kv: (-sum(kv[1]["outfalls"].values()), kv[0])):
            slug = sorted(w["water_slugs"])[0] if w["water_slugs"] else None
            if slug:
                how = "record"
            elif w["reach_ids"] or w["nhdplus_ids"]:
                how = "reach"
            elif w["points"]:
                how = "point"
            else:
                how = "name"
            ws.append({"name": w["name"], "key": k, "names_seen": sorted(w["names_seen"]),
                       "gnis_names": sorted(w["gnis_names"]), "reach_ids": sorted(w["reach_ids"]),
                       "nhdplus_ids": sorted(w["nhdplus_ids"]), "outfalls": dict(w["outfalls"]),
                       "operators": [{"permit": p, "permittee": n} for p, n in sorted(w["operators"].items())],
                       "points": w["points"], "water_slug": slug, "define_by": how})
        un = unnamed[st]
        summary = {
            "live": st in live,
            "waters_named": len(ws),
            "with_record": sum(1 for w in ws if w["define_by"] == "record"),
            "with_reach": sum(1 for w in ws if w["define_by"] == "reach"),
            "by_point_only": sum(1 for w in ws if w["define_by"] == "point"),
            "by_name_only": sum(1 for w in ws if w["define_by"] == "name"),
            "operators": len({o["permit"] for w in ws for o in w["operators"]} | {u["permit"] for u in un}),
            "outfalls_named": sum(sum(w["outfalls"].values()) for w in ws),
            "outfalls_unnamed": len(un),
            "unnamed_with_reach": sum(1 for u in un if u.get("reach_id") or u.get("nhdplus_id")),
            "unnamed_with_point": sum(1 for u in un if u.get("lat") and u.get("lon")),
            "water_records_on_file": len(records.get(st, {})),
        }
        out_states[st] = {"summary": summary, "waters": ws, "unnamed_outfalls": un}
    return {"about": __doc__.split("\n\n")[0].strip(),
            "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "define_by": {"record": "a water record exists (openboatlaunch, waters-extra or waters-nhd) and the registry carries its slug",
                          "reach": "EPA gives an NHD reach code or NHDPlus id: the record is built from that feature's GNIS id, no snapping",
                          "point": "a name and outfall points: snap the point (NLDI) and take the NHDPlus feature of that name",
                          "name": "a name only: the GNIS feature of that name in the state nearest the permittee's town",
                          "unnamed": "no receiving-water name: snap the outfall point and take the flowline or waterbody there"},
            "states": out_states}


def summary_table(d: dict) -> str:
    lines = ["| State | Live | Named waters | With record | With NHD reach | Point only | Name only | Unnamed outfalls (with reach / point) | Operators |",
             "|---|---|---:|---:|---:|---:|---:|---|---:|"]
    tot = collections.Counter()
    for st, s in sorted(d["states"].items(), key=lambda kv: kv[0]):
        m = s["summary"]
        lines.append(f"| {st} | {'yes' if m['live'] else ''} | {m['waters_named']} | {m['with_record']} | {m['with_reach']} | "
                     f"{m['by_point_only']} | {m['by_name_only']} | {m['outfalls_unnamed']} ({m['unnamed_with_reach']} / {m['unnamed_with_point']}) | {m['operators']} |")
        for k in ("waters_named", "with_record", "with_reach", "by_point_only", "by_name_only", "outfalls_unnamed",
                  "unnamed_with_reach", "unnamed_with_point", "operators"):
            tot[k] += m[k]
    lines.append(f"| **All** | | **{tot['waters_named']}** | **{tot['with_record']}** | **{tot['with_reach']}** | **{tot['by_point_only']}** | "
                 f"**{tot['by_name_only']}** | **{tot['outfalls_unnamed']}** ({tot['unnamed_with_reach']} / {tot['unnamed_with_point']}) | **{tot['operators']}** |")
    return "\n".join(lines)


def main() -> int:
    d = build()
    table = summary_table(d)
    if "--summary-only" not in sys.argv:
        OUT.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n")
        TALLY.write_text(
            "# Receiving waters per state (generated)\n\n"
            f"Generated by `scripts/gen_receiving_waters.py` ({d['generated']}) from the outfall registries and the water "
            "files in `data/`; do not edit by hand. The rule and the method are in `docs/national-waters.md`. "
            "A named water is a receiving water as the permit names it, grouped by state; *with record* means the registry "
            "already carries a water record's slug (openboatlaunch, waters-extra or waters-nhd); *with NHD reach* means EPA "
            "gives a reach code or NHDPlus id, so the record is built from that feature without snapping; *point only* and "
            "*name only* need the snapping or the name pass; unnamed outfalls are snapped by point. Every named water and every "
            "unnamed outfall must end as a record or a stated reason before its state goes live.\n\n" + table + "\n")
        print(f"wrote {OUT.relative_to(ROOT)} and {TALLY.relative_to(ROOT)}: "
              f"{sum(s['summary']['waters_named'] for s in d['states'].values())} named waters in {len(d['states'])} jurisdictions")
    else:
        print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
