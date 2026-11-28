"""Hand corrections to registry outfalls' water records (data/outfall-water-corrections.json, 2026-11-28).

scripts/match_outfalls.py ties an outfall to the nearest water record within 400 m of EPA's point, and
ingest.outfall_waters keeps those ties without reading the permit's receiving-water text again. Where the permit names
another water that has its own record at the point (Fall River's outfall 002 on 'Mount Hope Bay', tied to Narragansett
Bay; Portland's Back Cove outfalls tied to Casco Bay), the correction is written here, one entry per outfall, each with
the permit's stated water and a one-line basis.

An entry is applied only while the row still says what it said when the correction was made: the same receiving-water
text from EPA (`stated`). A row whose text changed is not corrected, and a row corrected before its text changed goes
back to the tie the correction replaced (revert(); ingest.outfall_waters then matches it as any other row); check()
reports the entry as needing review, so changed evidence is looked at rather than overwritten (registry water review
2026-11-28, P3). A copy of the outfall in another registry file that has no receiving-water text at all is corrected
too (agrees(): it says nothing against the entry); the entry's own row must keep the text. A row that had no water
keeps its no_water_reason in replaced_match, and revert() gives it back (untraced-outfall fixes 2026-11-28).

Rows are found by the registry loader's key (common.outfall_key: permit upper case, outfall number without leading
zeros), so '002' and '2' are one outfall, and every copy of the row is corrected, in the entry's file and in any other
registry file (registry water review 2026-11-28, P2-2: EPA's '2' beside the old '002' was the copy the loader read).
check_registry() checks the row the loader actually reads for each entry.

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
# kept in replaced_match beside slug, name, match, by; no_water_reason: why a row with no water had none (revert() gives
# it back; untraced-outfall fixes 2026-11-28)
BEFORE_FIELDS = ("water_kind", "distance_m", "water_match", "no_water_reason")
WHY_RETIED = "the permit names another water, which has its own record at the point"
WHY_NO_WATER = "the row had no water record; the receiving water the permit names has one"
_LOADED: dict = {}


def load(path: Path | None = None) -> list[dict]:
    p = path or FILE
    if not p.exists():
        return []
    return json.loads(p.read_text())["corrections"]


def _default() -> list[dict]:
    """The committed file, read once per change of the file (match_cso_row asks for every row)."""
    try:
        m = FILE.stat().st_mtime_ns
    except OSError:
        return []
    if _LOADED.get("mtime") != m:
        _LOADED.update(mtime=m, rows=load())
    return _LOADED["rows"]


def key(permit, outfall) -> tuple[str, str]:
    """The registry loader's key (common.outfall_key): '002' and '2' are one outfall."""
    from common import outfall_key
    return outfall_key(permit, outfall)


def key_of(x: dict) -> tuple[str, str]:
    return key(x.get("npdes_permit"), x.get("outfall"))


def is_hand(o: dict) -> bool:
    """A row this file corrected (water_matched_by says so)."""
    return str(o.get("water_matched_by") or "").startswith(BY)


def stated_of(o: dict) -> str:
    return str((o.get("receiving_water_override") or {}).get("water") or o.get("receiving_water_echo") or "").strip()


def entry_for(o: dict, corrections: list[dict] | None = None) -> dict | None:
    """The entry for this row's outfall (by the loader's key), whatever the row's text."""
    k = key_of(o)
    return next((c for c in (_default() if corrections is None else corrections) if key_of(c) == k), None)


def agrees(o: dict, c: dict, name: str | None = None) -> bool:
    """Whether the row's receiving-water text is still the one the entry read: the same text, or, on a copy of the
    outfall in another registry file than the entry's, no text at all (EPA's national copy of NEORSD's 211 and 212 has
    none: it says nothing against the entry; untraced-outfall fixes 2026-11-28). The entry's own row must keep the
    text. name: the row's registry file (None: not known, as in the registry pass; a row with no text then agrees)."""
    s = stated_of(o)
    return s == c["stated"] or (not s and name != c["file"])


def holds(o: dict, corrections: list[dict] | None = None, name: str | None = None) -> bool:
    """A corrected row whose correction still applies: its entry is in the file, the row's receiving-water text is
    still the entry's (agrees), and the row carries the entry's water."""
    c = entry_for(o, corrections)
    return bool(is_hand(o) and c and agrees(o, c, name) and o.get("water_slug") == c["water_slug"])


def revert(o: dict) -> None:
    """A corrected row whose correction no longer applies goes back to the tie the correction replaced (the matcher's
    own result, replaced_match); fields the replaced tie did not record are dropped."""
    before = o.pop("replaced_match", None) or {}
    o.update({"water_slug": before.get("water_slug"), "water_name": before.get("water_name"),
              "match": before.get("match"), "water_matched_by": before.get("by")})
    for f in BEFORE_FIELDS:
        if f in before:
            o[f] = before[f]
        else:
            o.pop(f, None)
    if not o.get("water_matched_by"):
        o.pop("water_matched_by", None)


def written(o: dict, c: dict) -> dict:
    """The fields an entry writes onto its row."""
    before = o.get("replaced_match")
    if not is_hand(o) or not before:
        before = {"water_slug": o.get("water_slug"), "water_name": o.get("water_name"), "match": o.get("match"),
                  "by": o.get("water_matched_by"), "why": WHY_RETIED if o.get("water_slug") else WHY_NO_WATER,
                  **{f: o[f] for f in BEFORE_FIELDS if o.get(f) is not None}}
    return {"water_slug": c["water_slug"], "water_name": c["water_name"], "water_kind": c["water_kind"],
            "distance_m": c["distance_m"], "match": "geometry+name",
            "water_match": f"hand correction: {c['basis']}",
            "water_matched_by": f"{BY}, {c['date']})", "replaced_match": before}


def _for_file(name: str, rows: list[dict], corrections: list[dict] | None) -> tuple[list[dict], dict]:
    """(the entries that touch file `name`: its own and any other file's entry whose outfall has a copy here,
    {key: [rows]} of the file by the loader's key)."""
    cs = _default() if corrections is None else corrections
    idx: dict = {}
    for o in rows:
        if isinstance(o, dict) and o.get("npdes_permit"):
            idx.setdefault(key_of(o), []).append(o)
    return [c for c in cs if c["file"] == name or key_of(c) in idx], idx


def _review(name: str, c: dict, o: dict) -> str:
    return (f"{name} {c['npdes_permit']}:{c['outfall']} (row outfall '{o.get('outfall')}'): needs review: the "
            f"receiving water is now '{stated_of(o)}', not '{c['stated']}' as when the correction was made; "
            "the row is not corrected")


def apply_rows(name: str, rows: list[dict], corrections: list[dict] | None = None) -> list[str]:
    """Write the entries onto the rows of registry file `name` (a basename such as 'outfalls-new-england.json'), in
    place: every row of the entry's outfall by the loader's key ('002' and '2' alike), in the entry's own file and in
    any other. Returns the problems: an entry whose row is missing from its own file, or whose row's receiving-water
    text is no longer the one the correction read (that row is not corrected, and goes back to the replaced tie if it
    was)."""
    cs, idx = _for_file(name, rows, corrections)
    problems = []
    for c in cs:
        found = idx.get(key_of(c)) or []
        if not found:
            problems.append(f"{name} {c['npdes_permit']}:{c['outfall']}: no such row")
            continue
        for o in found:
            if not agrees(o, c, name):
                if is_hand(o):
                    revert(o)
                problems.append(_review(name, c, o))
                continue
            o.update(written(o, c))
            o.pop("no_water_reason", None)          # kept in replaced_match (written); revert() gives it back
    return problems


def check(name: str, rows: list[dict], corrections: list[dict] | None = None) -> list[str]:
    """Problems with the rows of file `name` as they are: an entry of this file with no row; a row of an entry's
    outfall (any copy, by the loader's key) not corrected or corrected differently; an entry whose row's
    receiving-water text changed (needs review)."""
    cs, idx = _for_file(name, rows, corrections)
    out = []
    for c in cs:
        found = idx.get(key_of(c)) or []
        if not found:
            out.append(f"{name} {c['npdes_permit']}:{c['outfall']}: no such row")
        for o in found:
            if not agrees(o, c, name):
                out.append(_review(name, c, o) + ("; the row still carries the correction" if is_hand(o) else ""))
                continue
            want = written(o, c)
            diff = [k for k, v in want.items() if o.get(k) != v]
            if diff:
                out.append(f"{name} {c['npdes_permit']}:{c['outfall']} (row outfall '{o.get('outfall')}'): "
                           f"{', '.join(diff)} differ")
    return out


def check_registry(data_dir: Path | None = None, corrections: list[dict] | None = None) -> list[str]:
    """check() over every registry file (data/outfalls-*.json), and for each entry the row the registry loader
    (common.load_outfall_registry) reads: it must be there and carry the correction. Empty when all is well."""
    from common import DATA_DIR, OUTFALL_REGISTRY_GLOB, OUTFALL_REGISTRY_SKIPPED, load_outfall_registry
    d = Path(data_dir) if data_dir is not None else DATA_DIR
    cs = _default() if corrections is None else corrections
    out: list[str] = []
    for p in sorted(d.glob(OUTFALL_REGISTRY_GLOB)):
        try:
            doc = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            out.append(f"{p.name}: not read ({type(e).__name__})")
            continue
        rows = doc.get("outfalls") if isinstance(doc, dict) else doc
        out += check(p.name, [o for o in rows or [] if isinstance(o, dict)], cs)
    names = {p.name for p in d.glob(OUTFALL_REGISTRY_GLOB)}
    out += [f"{c['file']} {c['npdes_permit']}:{c['outfall']}: the file is not in the registry"
            for c in cs if c["file"] not in names]
    loaded = {key_of(o): o for o in load_outfall_registry(d, provisional=False)}
    out += list(OUTFALL_REGISTRY_SKIPPED)
    for c in cs:
        o = loaded.get(key_of(c))
        if o is None:
            out.append(f"{c['file']} {c['npdes_permit']}:{c['outfall']}: the registry loader reads no row for it")
        elif agrees(o, c, Path(str(o.get("_file") or "")).name) and any(o.get(k) != v for k, v in written(o, c).items()):
            out.append(f"{c['file']} {c['npdes_permit']}:{c['outfall']}: the registry loader reads the row of "
                       f"{o.get('_file')} (outfall '{o.get('outfall')}'), which is not corrected")
    return list(dict.fromkeys(out))


def main() -> int:
    """python -m ingest.outfall_water_corrections: check_registry(); exit 1 on any problem."""
    probs = check_registry()
    for p in probs:
        print("hand correction: " + p)
    print(f"hand corrections: {len(_default())} entries, {len(probs)} problems")
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
