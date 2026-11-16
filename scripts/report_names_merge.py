"""The report names of one or more feeds merged into a state's research/<st>/receiving-waters-missing.json (the names
pass's file, `python -m ingest.waters_from_nhd --names ... --state XX`), for feeds added after the state's file was
written and rewritten by its water batch: the file's other rows and resolved names keep every field (reason, parts,
slugs, places), and the feeds' own counts are replaced, never added twice (reports_by_source).

Each record is judged as the status build judges it (build.status.Resolver.resolve): a record it places on a water is
counted under `resolved` by name; one it reads as naming no receiving water ("STORM DRAIN", "Not Applicable", the
source's own no-water flag) is counted in left_out with that reason; one whose name several records hold and whose
county or point does not choose one is counted in left_out (the water has a record). The others take the names pass's
own reading of the text (waters_from_nhd.report_name_parts): no water name -> left out with its reason; a tributary,
ditch or storm drain leading to a named water ("Tributary to Gills Creek", "storm drain to Gills Creek") -> left out,
since the tributary is not the water it joins; a chain ("Colleton Creek to Wappoo Cut to Ashley River") -> its first
water, the pass's own convention (trim_part); a list ("Broad River and Saluda River") -> each water. A part is a row
only when it carries a kind of water (creek, river, lake, cut, swamp ...): a town or a filer's other words are left out
and counted, never written. Each name part is judged again on its own (a part a record holds is resolved).

One row per name (as the report gives it) and county: {name, county, reports, open, towns, sources, reports_by_source,
points?}; points only where the record carries one ([lat, lon], 0.001 degree, up to five). No other free text from a
record is written. Used by scripts/de_sc_report_water_names.py (SC), mountain_report_water_names.py (WY) and
oh_report_water_names.py (OH).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from build import status as S  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

OPEN = {"ongoing", "advisory_active"}
# kind words the names pass's KIND_WORDS lacks but South Carolina's and Wyoming's waters use ("Wappoo Cut", "Long Bay
# Swash", "Intracoastal Waterway", "Turkey Draw")
EXTRA_KINDS = {"cut", "swash", "waterway", "bayou", "draw", "wash", "arroyo", "sloughs", "tank", "impoundment"}
TRIB = "a tributary, ditch or drain leading to a named water (not the water it joins)"
NO_KIND = "a place or other words with no kind of water (not a water's name)"
AMBIGUOUS = "several water records hold the name and the report's county or point does not choose one"
COPY = "a copy of another report (duplicate_of): counted once"
DESCRIPTION = "a description of a place (a small stream, a pond next to a site, an address), not a water's name"
# words that make a filer's text a description, not a water's own name ("EDGE OF CREEK", "Pond feeding Rawls Creek",
# "STREAM WEST OF KEITH DRIVE", "Small Stream", "Conveyance Ditch", "Old City of Pickens Lagoon", "SITE DITCH"): such a
# text is never written (it can carry a street or a business)
DESCRIPTIVE = {"of", "at", "on", "by", "behind", "beside", "next", "between", "near", "along", "located", "running",
               "parallel", "feeding", "feed", "in", "into", "not", "named", "edge", "bed", "corner", "neighborhood",
               "site", "runoff", "conveyance", "stromwater", "stormwater", "lagoon", "lagoons", "sediment", "station", "lane",
               "street", "avenue", "trail", "drive", "road", "circle", "highway", "sc", "right", "small", "old",
               "outfall", "removed", "house", "property", "unit", "plant", "facility", "lot", "area", "nearby"}
PRIVATE = "a pond named for a person (private ground), not a public water's name"
NOT_PROPER = {"the", "a", "an", "water", "waters"}


def key(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def county_label(c) -> str | None:
    c = re.sub(r"\s+", " ", str(c or "")).strip()
    if not c:
        return None
    c = c.title() if c.isupper() or c.islower() else c
    return c if c.lower().endswith("county") else f"{c} County"


def has_kind(name: str) -> bool:
    ws = N.words(name)
    return N.has_kind(ws) or any(w in EXTRA_KINDS for w in ws)


def name_problem(name: str) -> str | None:
    """Why a part the names pass reads is not written as a row (None when it is a water's own name): no kind of water
    (a town, "Monroeville"), or a description (DESCRIPTIVE words, brackets, no word but kinds of water)."""
    if re.search(r"[\[\]@]", name) or N.not_water(name):
        return DESCRIPTION
    # a person's title ("Mr. Smith's pond") or an owner's pond ("Smith's Pond", "Jones's lake"): a pond on private
    # ground, not a public water's name (a creek or branch keeps its possessive: "Clem's Branch", "Tom's Branch")
    if re.search(r"\b(mr|mrs|ms|miss|dr)\b\.?\s", name, re.I) or re.search(r"\w['’]s\s+(pond|lake)\b", name, re.I):
        return PRIVATE
    if not has_kind(name):
        return NO_KIND
    ws = N.words(name)
    # "West Branch of Huron River", "Middle Fork of the Saluda River": the 'of' (and 'the') of a branch's own name
    ws = [w for i, w in enumerate(ws) if not (w in ("of", "the") and i and (ws[i - 1] in ("branch", "fork", "prong")
                                                                           or ws[i - 1] == "of"))]
    if any(w in DESCRIPTIVE for w in ws):
        return DESCRIPTION
    if not [w for w in ws if w not in N.KIND_WORDS and w not in EXTRA_KINDS and w not in NOT_PROPER]:
        return DESCRIPTION
    return None


def nw_reason(reason) -> str:
    """The status build's no-water reason without the report's own words (a filer's text can carry a street or a
    business): "the report names no water, only 'STORM DRAIN ON ...'" -> "the report names no water, only a storm
    drain, ditch or the like"."""
    r = str(reason or "")
    r = re.sub(r",?\s*only\s+'.*$", ", only a storm drain, ditch or the like", r)
    r = re.sub(r"\s*\('.*'\)\s*$", "", r)
    return r[:120]


def make_resolver(state: str):
    waters = S.load_waters(include_nhd=True)
    S._STATES = S.derive_states(waters, S.load_rules(), live_only=False) | {state}
    return S.make_resolver(waters)


def operator_towns(state: str):
    """record -> the towns of the operator its federal permit names (research/<st>/dischargers.json, data/dischargers.json
    and the outfall registries' cities, as the names pass's --add-places reads them), so the pass can choose among the
    waters of one name in the state; per row, so a name's rows in two counties keep their own towns."""
    dis = N.state_discharger_towns(state)
    reg = N.registry_towns({state})

    def towns(r):
        p = r.get("npdes_permit")
        return (list(dis.get(p) or []) + [t for t, _ in (reg.get(p) or Counter()).most_common(2)]) if p else []
    return towns


def judge(records: list[dict], state: str, resolver, names_of=None, county: str | None = None, towns_of=None) -> dict:
    """{rows: {(key, county): row}, resolved: {(name, county): {...}}, left_out: Counter} for one feed's records.
    names_of(record) -> the name texts a record gives (default: its waterbody_text); county: the county a feed's records
    lie in when they give none (one city's notices), used for a record with no raw.county; towns_of(record) -> the
    towns a row gains besides the record's own town field (operator_towns), up to four, most reports first."""
    feed_county = county
    names_of = names_of or (lambda r: [r.get("waterbody_text") or ""])
    rows, resolved, left = {}, {}, Counter()
    for r in records:
        if r.get("duplicate_of"):
            left[COPY] += 1
            continue
        raw = dict(r.get("raw") or {})
        raw.setdefault("state", state)
        county = county_label(raw.get("county")) or county_label(feed_county)
        texts = [re.sub(r"\s+", " ", str(t or "")).strip() for t in names_of(r)]
        texts = [t for t in texts if t]
        if not texts:
            left["names no water"] += 1
            continue
        sid = r.get("source_id")
        for text in texts:
            ev = {**r, "raw": raw, "waterbody_text": text}
            res = resolver.resolve(ev)
            if res.get("water_slugs"):
                _resolve(resolved, resolver, county, res["water_slugs"], sid)
                continue
            if res.get("no_receiving_water"):
                left[f"names no receiving water: {nw_reason(res['no_receiving_water'])}"] += 1
                continue
            if res.get("unplaced_reason") == "ambiguous name":
                left[AMBIGUOUS] += 1
                continue
            parts, why, trib = N.report_name_parts(S.state_split_text(text, state), state)
            if not parts:
                left[why or "no water name"] += 1
                continue
            if trib:
                left[TRIB] += 1
                continue
            for p in parts:
                bad = name_problem(p)
                if bad:
                    left[bad] += 1
                    continue
                if len(parts) > 1:
                    got = resolver.resolve({**ev, "waterbody_text": p})
                    if got.get("water_slugs"):
                        _resolve(resolved, resolver, county, got["water_slugs"], sid)
                        continue
                row = rows.setdefault((key(p), county), {"name": p, "county": county, "reports": 0, "open": 0,
                                                         "towns": [], "sources": {}, "_spell": Counter(),
                                                         "_towns": Counter()})
                row["_spell"][p] += 1
                row["reports"] += 1
                row["open"] += int(r.get("status") in OPEN and not r.get("ended_at"))
                row["sources"][sid] = row["sources"].get(sid, 0) + 1
                if r.get("lat") is not None and r.get("lon") is not None:
                    pt = [round(float(r["lat"]), 3), round(float(r["lon"]), 3)]
                    if pt not in row.setdefault("points", []) and len(row["points"]) < 5:
                        row["points"].append(pt)
                for t in [raw.get("town"), raw.get("city"), *(towns_of(r) if towns_of else [])]:
                    if isinstance(t, str) and t.strip() and not re.search(r"\d", t):
                        row["_towns"][t.strip().title()] += 1
    for row in rows.values():
        row["name"] = sorted(row.pop("_spell").items(), key=lambda x: (-x[1], x[0].isupper(), x[0]))[0][0]
        row["reports_by_source"] = dict(row["sources"])
        row["towns"] = [t for t, _ in sorted(row.pop("_towns").items(), key=lambda x: (-x[1], x[0]))[:4]]
        if not row["towns"]:
            row.pop("towns")
    return {"rows": rows, "resolved": resolved, "left_out": left}


def _resolve(resolved, resolver, county, slugs, sid):
    """A placed report counted under the record(s) it is placed on, by the record's name (never the report's text, which
    can be a filer's description: "possibly Flat Creek through a storm drain")."""
    slugs = sorted(slugs)
    name = "; ".join(dict.fromkeys(str((resolver.waters.get(x) or {}).get("name") or x) for x in slugs))
    e = resolved.setdefault((key(name), county), {"name": name, "county": county, "reports": 0, "slugs": [],
                                                  "how": "a water record holds the name (status build)",
                                                  "reports_by_source": {}})
    e["reports"] += 1
    e["slugs"] = sorted(set(e["slugs"]) | set(slugs))
    e["reports_by_source"][sid] = e["reports_by_source"].get(sid, 0) + 1


def _strip(entries: list[dict], sids: set) -> list[dict]:
    """entries with the given sources' earlier counts taken out (an entry left with no report and no other source is
    dropped): a rerun replaces a feed's counts."""
    out = []
    for e in entries:
        by = e.get("reports_by_source") or {}
        mine = {s: n for s, n in by.items() if s in sids}
        if not mine:
            out.append(e)
            continue
        e = dict(e)
        e["reports"] = max(0, int(e.get("reports") or 0) - sum(mine.values()))
        e["reports_by_source"] = {s: n for s, n in by.items() if s not in sids}
        src = e.get("sources")
        if isinstance(src, dict):
            e["sources"] = {s: n for s, n in src.items() if s not in sids}
        elif isinstance(src, list):
            e["sources"] = [s for s in src if s not in sids]
        if not e["reports_by_source"]:
            e.pop("reports_by_source")
        if e["reports"] == 0 and not e.get("sources") and not e.get("reports_by_source"):
            continue
        out.append(e)
    return out


def merge(path: Path, state: str, judged: dict[str, dict], feeds_read: dict[str, str]) -> dict:
    """Merge judge()'s output for each feed (sid -> judged) into the names file at path; returns the counts."""
    sids = set(judged)
    meta, rows = N.read_names_file(path) if path.exists() else ({}, [])
    rows = _strip(rows, sids)
    old_resolved = _strip(list(meta.get("resolved") or []), sids)
    by_key = {(key(r["name"]), r.get("county")): r for r in rows}
    res_key = {(key(r["name"]), r.get("county")): r for r in old_resolved}
    added = Counter()
    left = {}
    for sid, j in judged.items():
        left[sid] = dict(j["left_out"].most_common())
        for k, new in j["rows"].items():
            old = by_key.get(k)
            if old is None:
                rows.append(new)
                by_key[k] = new
                added["new_rows"] += 1
                continue
            old["reports"] = int(old.get("reports") or 0) + new["reports"]
            if "open" in old or "open" in new:
                old["open"] = int(old.get("open") or 0) + new.get("open", 0)
            src = old.get("sources")
            if isinstance(src, list):
                old["sources"] = sorted(set(src) | set(new["sources"]))
            else:
                old["sources"] = {**(src or {}), **new["sources"]}
            old["reports_by_source"] = {**(old.get("reports_by_source") or {}), **new["reports_by_source"]}
            for p in new.get("points") or []:
                if p not in old.setdefault("points", []) and len(old["points"]) < 5:
                    old["points"].append(p)
            added["merged_rows"] += 1
        for k, new in j["resolved"].items():
            old = res_key.get(k)
            if old is None:
                old_resolved.append(new)
                res_key[k] = new
                continue
            old["reports"] = int(old.get("reports") or 0) + new["reports"]
            old["reports_by_source"] = {**(old.get("reports_by_source") or {}), **new["reports_by_source"]}
            old["slugs"] = sorted(set(old.get("slugs") or []) | set(new["slugs"]))
    meta["resolved"] = []
    meta["left_out"] = {**(meta.get("left_out") or {}), **left} if isinstance(meta.get("left_out"), dict) else left
    meta["feeds_merged"] = {**(meta.get("feeds_merged") or {}), **feeds_read}
    N.write_names_file(path, meta, state, rows, old_resolved, meta.get("build"))
    doc = json.loads(path.read_text())
    return {"rows": doc.get("waters"), "reports": doc.get("reports"), **added,
            "feed_rows": sum(len(j["rows"]) for j in judged.values()),
            "feed_row_reports": sum(r["reports"] for j in judged.values() for r in j["rows"].values()),
            "feed_resolved_reports": sum(r["reports"] for j in judged.values() for r in j["resolved"].values()),
            "feed_left_out": sum(sum(j["left_out"].values()) for j in judged.values())}


def read_feed(events_dir: Path, sid: str):
    """(records, a line for feeds_merged) of one feed's events file, or (None, 'not built')."""
    p = Path(events_dir) / f"{sid}.json"
    if not p.exists():
        return None, "not built"
    doc = json.loads(p.read_text())
    recs = doc.get("records") or []
    return recs, f"{len(recs)} records, fetched {(doc.get('fetched_at') or doc.get('last_ok_at') or '')[:10]}"
