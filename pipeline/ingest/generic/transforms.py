"""Transforms named by fetch blocks (docs/generic-ingesters.md; not a feed). A record transform is called as
fn(row, rec, notes, ctx) after the field map and may change the record's fields (rec) and add raw notes (notes);
a water matcher as fn(text, rec, row, ctx) -> (slugs, water_match, note); a post step as fn(records, ctx) ->
counts, over all the records of a run (cross-record rules such as duplicates). Each is the few lines of logic a
feed needs that a field map cannot say; where a state's helper already holds that logic, the transform calls it.
"""
from __future__ import annotations

import inspect
import importlib
from collections import Counter

from common import EVENTS_DIR, read_json
from ingest.generic import fieldmap as F

# the state water matchers (ingest/<st>_waters.py match_waters(text, towns, point=(lon, lat), county=...))
WATER_MODULES = {"MD": "ingest.md_waters", "PA": "ingest.pa_waters", "VA": "ingest.va_waters", "NJ": "ingest.nj_waters",
                 "NY": "ingest.ny_waters"}


def state_waters(text: str, rec: dict, row: dict, ctx: F.Ctx):
    """The state's own water matcher (waters.state), checked against the record's point and, when the block names
    one, the county (waters.county, a constant, or waters.county_field, a safe field). waters.aliases rewrite a
    source's name to the name the water records use before matching."""
    w = ctx.block.get("waters") or {}
    st = str(w.get("state") or "").upper()
    mod = importlib.import_module(WATER_MODULES[st])
    name = (w.get("aliases") or {}).get(text, text)
    point = (rec["lon"], rec["lat"]) if rec.get("lat") is not None and rec.get("lon") is not None else None
    county = w.get("county") or (F.clean(row.get(w["county_field"])) or None if w.get("county_field") else None)
    params = inspect.signature(mod.match_waters).parameters
    kw = {k: v for k, v in (("point", point), ("county", county)) if k in params}
    slugs, notes = mod.match_waters(name, None, **kw)
    note = {}
    if name != text:
        note["matched_as"] = name
    if notes:
        note["name_notes"] = notes
    if slugs:
        note["via"] = (f"receiving water name within {st}" + (" (checked against the point)" if point else "")
                       + (f" and county {county}" if county else ""))
    else:
        note["why_none"] = f"no {st} water record matched the name"
    return slugs, "name", note


# ---------------------------------------------------------------- Maryland: MDE Reported Sewer Overflows

def _mde():
    from ingest import md_mde_overflows as M
    return M


def md_mde_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    """MDE's coordinate repairs (swapped, unsigned, degrees and decimal minutes, checked against the row's county)
    and its operator (permit or collection-system id, then the owner's name; ingest/md_mde_overflows.py)."""
    M = _mde()
    lat, lon, note = M.coords(row.get("overflow_latitude"), row.get("overflow_longitude"), F.clean(row.get("county")) or None)
    rec["lat"], rec["lon"] = lat, lon
    rec["coord_source"] = "source" if lat is not None else None
    notes["_coords"] = note
    if "md_permits" not in ctx.extra:
        ctx.extra["md_permits"] = M.load_dischargers()[0]
    did, basis = M.operator_of(row, ctx.extra["md_permits"])
    rec["discharger_id"] = did
    notes["_discharger_basis"] = basis


def md_mde_duplicates(records: list[dict], ctx: F.Ctx) -> Counter:
    """Within the table: the same start minute and address under another key, and rows MDE marks "(DUPLICATE)";
    across sources: the City's own SSO layer (md-baltimore-sso, run first) holds the end time and point."""
    M = _mde()
    rows_by_id = {r["event_id"]: (r.get("raw") or {}).get("row") or {} for r in records}
    n = Counter(M.mark_duplicates(records, rows_by_id))
    dpw = ctx.extra.get("md_baltimore_records")
    if dpw is None:
        dpw = (read_json((ctx.extra.get("events_dir") or EVENTS_DIR) / "md-baltimore-sso.json", {}) or {}).get("records", [])
    n["baltimore_dpw"] = M.match_baltimore(records, rows_by_id, dpw)
    return n
