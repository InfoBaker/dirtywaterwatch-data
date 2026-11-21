"""Transforms named by fetch blocks (docs/generic-ingesters.md; not a feed). A record transform is called as
fn(row, rec, notes, ctx) after the field map and may change the record's fields (rec) and add raw notes (notes);
a water matcher as fn(text, rec, row, ctx) -> (slugs, water_match, note); a post step as fn(records, ctx) ->
counts, over all the records of a run (cross-record rules such as duplicates). Each is the few lines of logic a
feed needs that a field map cannot say; where a state's helper already holds that logic, the transform calls it.
"""
from __future__ import annotations

import inspect
import importlib
import re
from collections import Counter

from common import EVENTS_DIR, read_json
from ingest.generic import fieldmap as F

# the state water matchers whose module name is not ingest/<st>_waters.py (each has match_waters(text, towns,
# point=(lon, lat), county=...)); any other state is found as ingest/<st>_waters.py
WATER_MODULES = {"MD": "ingest.md_waters", "PA": "ingest.pa_waters", "VA": "ingest.va_waters", "NJ": "ingest.nj_waters",
                 "NY": "ingest.ny_waters"}


@F.hook
def state_waters(text: str, rec: dict, row: dict, ctx: F.Ctx):
    """The state's own water matcher (waters.state), checked against the record's point and, when the block names
    one, the county (waters.county, a constant, or waters.county_field, a safe field). waters.aliases rewrite a
    source's name to the name the water records use before matching."""
    w = ctx.block.get("waters") or {}
    st = str(w.get("state") or "").upper()
    mod = importlib.import_module(F.water_state_module(st) or f"ingest.{st.lower()}_waters")
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


@F.hook
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


@F.hook
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


# ---------------------------------------------------------------- Maryland: MDE Reported Sewer Overflows, 2005-2023

# The frozen 2005 to January 2023 table (3rgd-zjxx) reports the same things as the 2023 table under other column
# names. Its rows are read under the 2023 table's names, so ingest/md_mde_overflows.py's coordinate repairs, operator
# match and duplicate rules apply to both tables unchanged.
MD_HISTORY_FIELDS = {
    "npdes": "npdes_no", "municipality_facility": "owner_name", "collection_system": "facility_collection_system",
    "date_discovered": "start_date", "time_discovered": "start_time", "duration_days": "duration_day",
    "duration_hours": "duration_hour", "duration_minutes": "duration_minute", "location": "overflow_address",
    "zip_code": "zip", "quantity_in_gallons_estimated": "discharge_volume", "cause": "overflow_cause",
    "receiving_waters": "receiving_water", "latitude": "overflow_latitude", "longitude": "overflow_longitude",
}
# the 2005-2023 table's spellings of operators with a research/md/dischargers.json row (the 2023 table's spellings are
# md_mde_overflows.OWNER_IDS; "<place> City of" and "<place> Town of" are also tried as "City of <place>")
MD_HISTORY_OWNERS = {
    "city of baltimore": "md-baltimore-city-dpw", "city of baltimore dept of public works": "md-baltimore-city-dpw",
    "city of baltimore department of public works": "md-baltimore-city-dpw",
    "cumberland city of": "md-cumberland", "city of cumberland": "md-cumberland",
    "city of cambridge": "md-cambridge", "city of frederick": "md-frederick-city",
    "baltimore county dpw bureau of utilities": "md-baltimore-county-dpw",
    "la vale": "md-lavale", "lavale": "md-lavale", "mes": "md-mes",
    "anne arundel county dpw bureau of utility operations": "md-anne-arundel-dpw",
    "st mary s county metropolitan commission": "md-metcom",
    "howard county dpw bureau of utilities": "md-howard-county-dpw", "howard county bureau of utilities": "md-howard-county-dpw",
    "navy department of": "md-us-navy", "department of the navy": "md-us-navy",
    "frederick county utilities and solid waste management": "md-frederick-county-utilities",
    "calvert county bureau of utilities division of water and sewer": "md-calvert-county",
    "somerset county sanitary district": "md-somerset-sanitary", "carroll county dpw": "md-carroll-county",
}
_PLACE_OF = re.compile(r"^(.+) (city|town) of$")


def md_history_row(row: dict) -> dict:
    """A 2005-2023 row under the 2023 table's column names (columns with no counterpart keep theirs)."""
    return {MD_HISTORY_FIELDS.get(k, k): v for k, v in (row or {}).items()}


def md_history_owner(owner: str | None) -> str | None:
    """The research id of a 2005-2023 owner spelling, or None."""
    M = _mde()
    n = M.norm_owner(owner)
    if not n:
        return None
    hit = MD_HISTORY_OWNERS.get(n) or M.OWNER_IDS.get(n)
    m = _PLACE_OF.match(n)
    if hit is None and m:
        flipped = f"{m.group(2)} of {m.group(1)}"
        hit = MD_HISTORY_OWNERS.get(flipped) or M.OWNER_IDS.get(flipped)
    return hit


@F.hook
def md_mde_history_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    """The 2023 module's coordinate repairs and operator match on a 2005-2023 row, with the older table's own
    spellings of the operators."""
    M = _mde()
    r = md_history_row(row)
    county = F.clean(r.get("county")) or None
    lat, lon, note = M.coords(r.get("overflow_latitude"), r.get("overflow_longitude"), county)
    rec["lat"], rec["lon"] = lat, lon
    rec["coord_source"] = "source" if lat is not None else None
    notes["_coords"] = note
    if "md_permits" not in ctx.extra:
        ctx.extra["md_permits"] = M.load_dischargers()[0]
    did, basis = M.operator_of(r, ctx.extra["md_permits"])
    alias = md_history_owner(r.get("owner_name"))
    if alias and basis.startswith("built from the owner name"):
        did, basis = M.ID_OVERRIDES.get(alias, alias), "owner name (the 2005-2023 table's spelling)"
    rec["discharger_id"] = did
    notes["_discharger_basis"] = basis


@F.hook
def md_mde_history_duplicates(records: list[dict], ctx: F.Ctx) -> Counter:
    """Within the table, the 2023 module's rules (same start minute and address under another key; rows MDE marks
    "(DUPLICATE)"). Across the tables: the 2023 table (md-mde-overflows, a feed module, run before the blocks)
    begins in January 2023 and this one ends in February 2023; a row here that starts the same day at the same
    address as a row there (one table may time a report to the day and the other to the minute), or with the same
    permit and start minute, is duplicate_of that row."""
    M = _mde()
    rows_by_id = {r["event_id"]: md_history_row((r.get("raw") or {}).get("row")) for r in records}
    n = Counter(M.mark_duplicates(records, rows_by_id))
    newer = ctx.extra.get("md_mde_records")
    if newer is None:
        newer = (read_json((ctx.extra.get("events_dir") or EVENTS_DIR) / "md-mde-overflows.json", {}) or {}).get("records", [])
    by_addr, by_permit = {}, {}
    for p in newer:
        if p.get("duplicate_of") or not p.get("started_at"):
            continue
        prow = (p.get("raw") or {}).get("row") or {}
        addr = M.norm_addr(prow.get("overflow_address"), for_match=True)
        if addr:
            by_addr.setdefault((p["started_at"][:10], addr), p)
        permit = M.clean(prow.get("npdes_no")).upper()
        if M.REAL_PERMIT.match(permit) and p.get("time_precision") == "minute":
            by_permit.setdefault((permit, p["started_at"]), p)
    n["in_2023_table"] = 0
    for r in records:
        if r.get("duplicate_of") or not r.get("started_at"):
            continue
        row = rows_by_id[r["event_id"]]
        addr = M.norm_addr(row.get("overflow_address"), for_match=True)
        permit = M.clean(row.get("npdes_no")).upper()
        hit, how = (by_addr.get((r["started_at"][:10], addr)), "same start day and address") if addr else (None, "")
        if hit is None and M.REAL_PERMIT.match(permit) and r.get("time_precision") == "minute":
            hit, how = by_permit.get((permit, r["started_at"])), "same permit and start minute"
        if hit is not None:
            r["duplicate_of"] = hit["event_id"]
            r["raw"]["_duplicate_basis"] = f"{how} as {hit['event_id']} in MDE's 2023 table, which carries the report on"
            n["in_2023_table"] += 1
    return n
