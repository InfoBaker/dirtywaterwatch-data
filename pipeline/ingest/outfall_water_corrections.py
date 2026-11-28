"""Hand corrections to registry outfalls' water records (data/outfall-water-corrections.json, 2026-11-28).

scripts/match_outfalls.py ties an outfall to the nearest water record within 400 m of EPA's point, and
ingest.outfall_waters keeps those ties without reading the permit's receiving-water text again. Where the permit names
another water that has its own record at the point (Fall River's outfall 002 on 'Mount Hope Bay', tied to Narragansett
Bay; Portland's Back Cove outfalls tied to Casco Bay), the correction is written here, one entry per outfall, each with
the permit's stated water and a one-line basis.

An entry is applied only while the row still says what it said when the correction was made: the same receiving-water
text from EPA (`stated`). A row whose text changed is left as it is and reported, so changed evidence is looked at
rather than overwritten.

The corrections survive a rebuild:
  - scripts/match_outfalls.py applies them to the rows it writes (it rewrites rows from EPA's file);
  - ingest.outfall_waters keeps a corrected row as it is (match_cso_row, match_plant_row) and applies the file again
    after its pass (run, run_state, run_plants), so a row a rebuild has reset is corrected again.
pipeline/tests/test_outfall_water_corrections.py checks that the files as committed say what this file says.

Each corrected row gets water_slug, water_name, water_kind, distance_m (metres from the row's point to the record, as
measured for the correction), match ('geometry+name': the record carries the stated water's name and lies within 400 m
of the point), water_match (the basis), water_matched_by (BY) and replaced_match (the earlier tie). The row's own
receiving-water text and point are not changed.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "data" / "outfall-water-corrections.json"
BY = "data/outfall-water-corrections.json (hand correction"


def load(path: Path | None = None) -> list[dict]:
    p = path or FILE
    if not p.exists():
        return []
    return json.loads(p.read_text())["corrections"]


def is_hand(o: dict) -> bool:
    """A row this file corrected (water_matched_by says so)."""
    return str(o.get("water_matched_by") or "").startswith(BY)


def stated_of(o: dict) -> str:
    return str((o.get("receiving_water_override") or {}).get("water") or o.get("receiving_water_echo") or "").strip()


def written(o: dict, c: dict) -> dict:
    """The fields an entry writes onto its row."""
    before = o.get("replaced_match")
    if not is_hand(o) or not before:
        before = {"water_slug": o.get("water_slug"), "water_name": o.get("water_name"), "match": o.get("match"),
                  "by": o.get("water_matched_by"),
                  "why": "the permit names another water, which has its own record at the point"}
    return {"water_slug": c["water_slug"], "water_name": c["water_name"], "water_kind": c["water_kind"],
            "distance_m": c["distance_m"], "match": "geometry+name",
            "water_match": f"hand correction: {c['basis']}",
            "water_matched_by": f"{BY}, {c['date']})", "replaced_match": before}


def apply_rows(name: str, rows: list[dict], corrections: list[dict] | None = None) -> list[str]:
    """Write the entries for registry file `name` (a basename such as 'outfalls-new-england.json') onto its rows, in
    place. Returns the problems: an entry whose row is missing, or whose row's receiving-water text is no longer the
    one the correction read (that row is left as it is)."""
    cs = [c for c in (load() if corrections is None else corrections) if c["file"] == name]
    if not cs:
        return []
    idx = {}
    for o in rows:
        idx.setdefault((str(o.get("npdes_permit")), str(o.get("outfall"))), []).append(o)
    problems = []
    for c in cs:
        found = idx.get((c["npdes_permit"], c["outfall"])) or []
        if not found:
            problems.append(f"{name} {c['npdes_permit']}:{c['outfall']}: no such row")
            continue
        for o in found:
            if stated_of(o) != c["stated"]:
                problems.append(f"{name} {c['npdes_permit']}:{c['outfall']}: the receiving water is now "
                                f"'{stated_of(o)}', not '{c['stated']}'; not corrected")
                continue
            o.update(written(o, c))
            o.pop("no_water_reason", None)
    return problems


def check(name: str, rows: list[dict], corrections: list[dict] | None = None) -> list[str]:
    """Problems with the rows as they are: an entry not applied (or applied differently)."""
    cs = [c for c in (load() if corrections is None else corrections) if c["file"] == name]
    out = []
    for c in cs:
        for o in rows:
            if str(o.get("npdes_permit")) == c["npdes_permit"] and str(o.get("outfall")) == c["outfall"]:
                want = written(o, c)
                diff = [k for k, v in want.items() if o.get(k) != v]
                if diff:
                    out.append(f"{name} {c['npdes_permit']}:{c['outfall']}: {', '.join(diff)} differ")
    return out
