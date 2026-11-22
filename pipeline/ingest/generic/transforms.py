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

from common import EVENTS_DIR, NAME_REMOVED, read_json
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


def _canonical_spelling(did: str) -> str | None:
    """The 2023 table's spelling (md_mde_overflows.OWNER_IDS) of a research operator, so operator_of applies its own
    precedence and conflict note to an older spelling exactly as to the newer one."""
    return next((k for k, v in _mde().OWNER_IDS.items() if v == did), None)


@F.hook
def md_mde_history_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    """The 2023 module's coordinate repairs and operator match on a 2005-2023 row, with the older table's own
    spellings of the operators. An owner the scrub replaced ("[name removed]") is no owner: the permit alone may
    still name the operator."""
    M = _mde()
    r = md_history_row(row)
    county = F.clean(r.get("county")) or None
    lat, lon, note = M.coords(r.get("overflow_latitude"), r.get("overflow_longitude"), county)
    rec["lat"], rec["lon"] = lat, lon
    rec["coord_source"] = "source" if lat is not None else None
    notes["_coords"] = note
    if "md_permits" not in ctx.extra:
        ctx.extra["md_permits"] = M.load_dischargers()[0]
    owner = F.clean(r.get("owner_name"))
    spelled = None
    if not owner or NAME_REMOVED in owner:
        r["owner_name"] = ""
    elif M.norm_owner(owner) not in M.OWNER_IDS:
        alias = md_history_owner(owner)
        spelled = _canonical_spelling(alias) if alias else None
        if spelled:
            r["owner_name"] = spelled
    did, basis = M.operator_of(r, ctx.extra["md_permits"])
    if spelled:
        basis += f" (the 2005-2023 table's spelling, read as {spelled!r})"
    rec["discharger_id"] = did
    notes["_discharger_basis"] = basis


def _same_report(a: dict, b: dict) -> bool:
    """Two records of one table that share a record key are one report filed twice only when the owner and the
    volume agree (a corrected type or a spacing difference is still a copy); otherwise both are kept."""
    M = _mde()
    ra, rb = md_history_row(a["raw"].get("row")), md_history_row(b["raw"].get("row"))
    return M.norm_owner(ra.get("owner_name")) == M.norm_owner(rb.get("owner_name")) and \
        a.get("volume_gal") == b.get("volume_gal")


@F.hook
def md_mde_history_duplicates(records: list[dict], ctx: F.Ctx) -> Counter:
    """Within the table: a row sharing another's record key (permit, start, address) is its copy only when the owner
    and volume agree; else it is kept as its own report (a key with no time of day or no address can be shared by two
    reports). Then the 2023 module's rules (same start minute and address under another key; rows MDE marks
    "(DUPLICATE)"). Across the tables: the 2023 table (md-mde-overflows, a feed module, run before the blocks) begins
    in January 2023 and this one ends in February 2023. A row here is duplicate_of a 2023 record only when exactly one
    2023 record has the same start day, the same address and the same event type, and their times agree (equal, or
    one known only to the day). A 2023 record that is itself a copy (of the City's own SSO record) passes the link on
    to its original. The run fails when the 2023 table's events file is missing, so a read is never kept without this
    check (the table is then asked only for its version)."""
    M = _mde()
    n = Counter()
    groups: dict[str, list] = {}
    for r in records:                       # the dedupe step's order: the key's first record, then ~2, ~3
        groups.setdefault(r["event_id"].split("~")[0], []).append(r)
    for grp in groups.values():
        if len(grp) < 2:
            continue
        reports = [grp[0]]
        for r in grp[1:]:
            if not str(r["raw"].get("_duplicate_basis", "")).startswith("the source repeats"):
                continue
            same = next((o for o in reports if _same_report(r, o)), None)
            if same is not None:
                r["duplicate_of"] = same["event_id"]
                continue
            r["duplicate_of"] = None
            r["raw"].pop("_duplicate_basis", None)
            r["raw"]["_same_key_kept"] = (f"shares the record key of {grp[0]['event_id']} but names another owner or "
                                          f"volume: kept as its own report")
            reports.append(r)
            n["same_key_kept_apart"] += 1
    rows_by_id = {r["event_id"]: md_history_row((r.get("raw") or {}).get("row")) for r in records}
    n.update(M.mark_duplicates(records, rows_by_id))
    newer = ctx.extra.get("md_mde_records")
    if newer is None:
        doc = read_json((ctx.extra.get("events_dir") or EVENTS_DIR) / "md-mde-overflows.json", None)
        if not doc or not doc.get("records"):
            raise RuntimeError("md-mde-overflows.json (the 2023 table) is missing or empty: the reports in both tables "
                               "cannot be matched, so this read is not kept")
        newer = doc["records"]
    newer_by_id = {p["event_id"]: p for p in newer}
    by_day_addr: dict[tuple, list] = {}
    for p in newer:
        if not p.get("started_at"):
            continue
        addr = M.norm_addr(((p.get("raw") or {}).get("row") or {}).get("overflow_address"), for_match=True)
        if addr:
            by_day_addr.setdefault((p["started_at"][:10], addr, p.get("event_type")), []).append(p)
    n["in_2023_table"] = 0
    for r in records:
        if r.get("duplicate_of") or not r.get("started_at"):
            continue
        addr = M.norm_addr(rows_by_id[r["event_id"]].get("overflow_address"), for_match=True)
        if not addr:
            continue
        cands = [p for p in by_day_addr.get((r["started_at"][:10], addr, r.get("event_type")), [])
                 if p["started_at"] == r["started_at"] or "day" in (p.get("time_precision"), r.get("time_precision"))]
        if len(cands) != 1:
            if len(cands) > 1:
                n["in_2023_table_ambiguous"] += 1
            continue
        hit = cands[0]
        target = hit.get("duplicate_of") or hit["event_id"]
        via = f" (itself a copy of {target})" if hit.get("duplicate_of") else ""
        r["duplicate_of"] = target
        r["raw"]["_duplicate_basis"] = (f"same start day, address and type as {hit['event_id']} in MDE's 2023 table{via}, "
                                        f"which carries the report on")
        n["in_2023_table"] += 1
    return n
