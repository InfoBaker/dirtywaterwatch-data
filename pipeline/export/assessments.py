"""The state's own Clean Water Act assessment in out/ (EPA ATTAINS; build/attains.py writes the cache, docs/attains.md):
shown beside a water's status, never changing it. export/build.py calls these:

  load(tracked, canon, scrub=)    the cache data/build/attains/attains-waters.json kept to the tracked waters, or nothing
                                  (with the reason) when it is missing, unreadable, not of the expected form
                                  (cache_problem) or older than STALE_DAYS; never an exception. Every free-text field of
                                  a unit passes through common.scrub_text and then `scrub` (the export's redactor,
                                  Redactor.note) before anything is written
  water_block(a, slug)            `assessment` in waters/<slug>.json: {"source", "units", "summary"} or None; the source
                                  is the citation (assessment_source)
  write_index(out_dir, a)         out/assessments.json: {"built", "source", "waters": {slug: SUMMARY}}, the whole source
                                  block once
  meta(a)                         meta.json's assessments counts (a water counts when any of its units, capped or not,
                                  has the finding)
A water's block carries at most MAX_UNITS units (a pathogen listing first, then a sewage source named, then distance);
its summary counts what it carries and, before the cap, units_total, pathogen_listed_total, sewage_named_total.
  write_csv(path, a, names)       the assessment download, out/csv/assessments.csv: one row per tracked water and
                                  matched unit, every unit (CSV_COLUMNS), the conventions of export/csv.py

The audit list of the cache (candidates not taken) is never exported. cache_problem, unit_problem and scrub_unit are
also used by build/attains.py, which checks and scrubs what it writes the same way.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common import BUILD_DIR, scrub_text, read_json

CACHE = BUILD_DIR / "attains" / "attains-waters.json"
STALE_DAYS = 30
MAX_UNITS = 25                       # units a water's block carries (the cache and the download keep all)
SOURCE_KEYS = ("name", "files", "layers", "fetched_at")
# the source block as out/assessments.json publishes it (nothing else the cache may hold)
INDEX_SOURCE_KEYS = (*SOURCE_KEYS, "geometry_fetched", "latest_cycles")
REPORT_PREFIX = "https://mywaterway.epa.gov/waterbody-report/"
LIST_SEP = ";"
CSV_COLUMNS = ["water_slug", "water", "org_id", "org_name", "state", "au_id", "au_name", "cycle", "cycle_status",
               "water_type", "size", "size_units", "location", "recreation_support", "recreation_uses",
               "monitoring_start", "monitoring_end", "assessment_date", "pathogen_parameters", "pathogen_statuses",
               "pathogen_ir_categories", "pathogen_listed", "has_tmdl", "sewage_sources", "sewage_kinds",
               "sources_cycle", "report_url", "latest_url", "match_method", "match_distance_m", "assessment_from"]

# ---------------------------------------------------------------- the cache's form (docs/attains.md, UNIT)


def _opt_str(v) -> bool:
    return v is None or isinstance(v, str)


def _opt_int(v) -> bool:
    return v is None or (isinstance(v, int) and not isinstance(v, bool))


def _opt_num(v) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


def _opt_bool(v) -> bool:
    return v is None or isinstance(v, bool)


def _opt_str_list(v) -> bool:
    return v is None or (isinstance(v, list) and all(isinstance(x, str) for x in v))


UNIT_TEXT = ("org_name", "state", "au_name", "cycle_status", "water_type", "size_units", "location", "from")
REC_TEXT = ("support", "monitoring_start", "monitoring_end", "assessment_date")
PATHOGEN_TEXT = ("parameter", "status", "ir_category")
SOURCE_TEXT = ("name", "kind", "cause")
MATCH_TEXT = ("method", "geometry", "name_from")


def unit_problem(u) -> str | None:
    """What is wrong with one UNIT of the cache (a field named, never its value), or None when every field the export
    reads has its documented type: ids as text, years as integers, the size a finite number, the report addresses on
    How's My Waterway, `recreation`, `pathogens`, `sewage_sources` and `match` as documented."""
    if not isinstance(u, dict):
        return "a unit is not an object"
    for k in ("org_id", "au_id"):
        if not isinstance(u.get(k), str) or not u[k].strip():
            return f"a unit has no {k}"
    for k in UNIT_TEXT:
        if not _opt_str(u.get(k)):
            return f"a unit's {k} is not text"
    for k in ("cycle", "sources_cycle"):
        if not _opt_int(u.get(k)):
            return f"a unit's {k} is not a year"
    if not _opt_num(u.get("size")):
        return "a unit's size is not a number"
    if not _opt_bool(u.get("has_tmdl")):
        return "a unit's has_tmdl is not true or false"
    for k in ("report_url", "latest_url"):
        v = u.get(k)
        if v is not None and not (isinstance(v, str) and v.startswith(REPORT_PREFIX)):
            return f"a unit's {k} is not a How's My Waterway address"
    rec = u.get("recreation")
    if rec is not None:
        if not isinstance(rec, dict):
            return "a unit's recreation is not an object"
        if any(not _opt_str(rec.get(k)) for k in REC_TEXT) or not _opt_str_list(rec.get("uses")):
            return "a unit's recreation fields are not text"
    pats = u.get("pathogens")
    if pats is not None:
        if not isinstance(pats, list) or not all(isinstance(p, dict) for p in pats):
            return "a unit's pathogens is not a list of objects"
        for p in pats:
            if (any(not _opt_str(p.get(k)) for k in PATHOGEN_TEXT) or not _opt_int(p.get("first_listed"))
                    or not _opt_bool(p.get("delisted")) or not _opt_str_list(p.get("uses"))
                    or not _opt_str_list(p.get("use_groups"))):
                return "a unit's pathogen fields do not have their types"
    srcs = u.get("sewage_sources")
    if srcs is not None:
        if not isinstance(srcs, list) or not all(isinstance(s, dict) for s in srcs):
            return "a unit's sewage_sources is not a list of objects"
        for s in srcs:
            if (any(not _opt_str(s.get(k)) for k in SOURCE_TEXT) or not _opt_bool(s.get("confirmed"))
                    or not _opt_int(s.get("cycle"))):
                return "a unit's sewage source fields do not have their types"
    m = u.get("match")
    if m is not None:
        if not isinstance(m, dict):
            return "a unit's match is not an object"
        if any(not _opt_str(m.get(k)) for k in MATCH_TEXT) or not _opt_num(m.get("distance_m")):
            return "a unit's match fields do not have their types"
    return None


def source_problem(src) -> str | None:
    """What is wrong with the cache's source block (published whole in out/assessments.json), or None."""
    if src is None:
        return None
    if not isinstance(src, dict):
        return "the source block is not an object"
    if not _opt_str(src.get("name")) or not _opt_str(src.get("fetched_at")):
        return "the source name or fetch time is not text"
    files = src.get("files")
    if files is not None:
        if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
            return "the source files are not a list of objects"
        for f in files:
            if (any(not _opt_str(f.get(k)) for k in ("name", "url", "timestamp"))
                    or any(not _opt_num(f.get(k)) for k in ("bytes", "rows"))):
                return "a source file's fields do not have their types"
    layers = src.get("layers")
    if layers is not None and (not isinstance(layers, dict) or not _opt_str(layers.get("url"))
                               or not _opt_str(layers.get("data_last_edited"))):
        return "the source layers block does not have its types"
    gf = src.get("geometry_fetched")
    if gf is not None and (not isinstance(gf, dict) or not all(isinstance(k, str) and _opt_str(v) for k, v in gf.items())):
        return "the geometry fetch times do not have their types"
    lc = src.get("latest_cycles")
    if lc is not None:
        if not isinstance(lc, dict) or not all(isinstance(t, dict) for t in lc.values()):
            return "the latest cycles do not have their types"
        if not all(isinstance(o, str) and _opt_int(c) for t in lc.values() for o, c in t.items()):
            return "the latest cycles do not have their types"
    return None


def cache_problem(cache) -> str | None:
    """What keeps the cache from being used (a part named, never a value), or None: the whole retained form is
    checked, every water and every unit (unit_problem) and the source block (source_problem), before anything is
    exported, so a cache that is valid JSON with a malformed part shows nothing rather than stopping the export."""
    if not isinstance(cache, dict):
        return "the file is not an object"
    waters = cache.get("waters")
    if not isinstance(waters, dict):
        return "the file has no waters object"
    why = source_problem(cache.get("source"))
    if why:
        return why
    for slug, rec in waters.items():
        if not isinstance(slug, str) or not slug or not isinstance(rec, dict):
            return "a water is not an object"
        units = rec.get("units")
        if units is None:
            continue
        if not isinstance(units, list):
            return "a water's units is not a list"
        for u in units:
            why = unit_problem(u)
            if why:
                return why
    return None


# ---------------------------------------------------------------- free text

# fields that hold an identifier, an address, a code or a date, never a source's free text
FIXED_KEYS = frozenset({"org_id", "au_id", "report_url", "latest_url", "state", "kind", "from", "method", "geometry",
                        "name_from", "monitoring_start", "monitoring_end", "assessment_date", "url", "timestamp"})


def scrub_unit(obj, fn):
    """A copy of a unit (or an audit entry) with every free-text string through fn (identifiers, addresses, codes and
    dates, FIXED_KEYS, kept as they are); numbers, booleans and None unchanged."""
    def walk(v, key):
        if isinstance(v, str):
            return v if key in FIXED_KEYS else fn(v)
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        return v
    return walk(obj, "")


def text_scrubber(scrub=None):
    """The free-text pass of the export: common.scrub_text (e-mail addresses, phone numbers, staff names, a resident's
    house number), then `scrub` when given (the export's Redactor.note: names marked as a person, the blocklist),
    each distinct string once."""
    seen: dict[str, str] = {}

    def fn(t: str) -> str:
        out = seen.get(t)
        if out is None:
            out = scrub_text(t)
            if scrub is not None:
                out = scrub(out)
            seen[t] = out
        return out
    return fn


# ---------------------------------------------------------------- the cache kept to the tracked waters


def read_cache(path: Path | None = None) -> tuple[dict | None, str | None]:
    """The cache and, when it cannot be used, why (missing, unreadable): never an exception."""
    path = path or CACHE
    try:
        if not path.is_file():
            return None, "no assessment file for this export"
        return read_json(path), None
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return {}, "the assessment file is not readable"


def _empty(why: str, built=None) -> dict:
    return {"built": built, "source": None, "waters": {}, "unavailable": why}


def public(cache: dict | None, tracked, canon=lambda s: s, now: str | None = None,
           why_missing: str | None = None, scrub=None) -> dict:
    """The tracked waters' units and summaries, {"built", "source", "waters": {slug: {"units", "summary"}},
    "unavailable"}. A cache that is missing, unreadable, not of the expected form (cache_problem) or older than
    STALE_DAYS gives no water anything, with the reason in "unavailable" (the export never fails over it). A slug the
    cache knows under an older name (build/status.py SLUG_ALIASES, through canon) is written under the record's own
    slug. Every unit's free text passes through text_scrubber(scrub)."""
    if cache is None:
        return _empty(why_missing or "no assessment file for this export")
    if why_missing:
        return _empty(why_missing)
    try:
        return _public(cache, tracked, canon, now, scrub)
    except Exception:  # noqa: BLE001 - the export never fails over the assessments (cache_problem should catch all)
        return _empty("the assessment file could not be used")


def _public(cache, tracked, canon, now, scrub) -> dict:
    why = cache_problem(cache)
    if why:
        return _empty(f"the assessment file does not have the expected form ({why})")
    try:
        built = datetime.fromisoformat(str(cache.get("built")).replace("Z", "+00:00"))
        built = built if built.tzinfo else built.replace(tzinfo=UTC)
    except ValueError:
        return _empty("the assessment file has no build time")
    at = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(UTC)
    if at - built > timedelta(days=STALE_DAYS):
        return _empty(f"the assessment file was built {built:%Y-%m-%d}, more than {STALE_DAYS} days ago",
                      built=cache.get("built"))
    fn = text_scrubber(scrub)
    waters: dict[str, dict] = {}
    for slug, rec in sorted(cache["waters"].items()):
        own = canon(slug)
        if own not in tracked or not rec.get("units"):
            continue
        if own in waters and own != slug:            # the record's own slug wins over an older name
            continue
        units = sort_units([scrub_unit(u, fn) for u in rec["units"]])
        kept = units[:MAX_UNITS]
        waters[own] = {"units": kept, "summary": capped_summary(kept, units), "all_units": units}
    src = cache.get("source")
    src = {k: src[k] for k in INDEX_SOURCE_KEYS if k in src} if isinstance(src, dict) else None
    return {"built": cache.get("built"), "source": src, "waters": waters, "unavailable": None}


def _listed(u: dict) -> bool:
    return any(str(p.get("status")).lower() == "cause" for p in u.get("pathogens") or [])


def sort_units(units: list[dict]) -> list[dict]:
    """A pathogen listing first, then a sewage source named, then distance (the cache's order, kept here so the cap
    takes the same units whatever order a cache holds)."""
    return sorted(units, key=lambda u: (not _listed(u), not u.get("sewage_sources"),
                                        (u.get("match") or {}).get("distance_m") or 0, str(u.get("au_id"))))


def capped_summary(kept: list[dict], units: list[dict]) -> dict:
    """SUMMARY of what a block carries (units, pathogen_listed, sewage_named, latest_cycle, states) and, before the
    cap of MAX_UNITS, units_total, pathogen_listed_total and sewage_named_total."""
    cycles = [u["cycle"] for u in kept if isinstance(u.get("cycle"), int)]
    return {"units": len(kept), "pathogen_listed": sum(1 for u in kept if _listed(u)),
            "sewage_named": sum(1 for u in kept if u.get("sewage_sources")),
            "latest_cycle": max(cycles) if cycles else None,
            "states": sorted({u["state"] for u in kept if u.get("state")}),
            "units_total": len(units), "pathogen_listed_total": sum(1 for u in units if _listed(u)),
            "sewage_named_total": sum(1 for u in units if u.get("sewage_sources"))}


def load(tracked, canon=lambda s: s, path: Path | None = None, now: str | None = None, scrub=None) -> dict:
    cache, why = read_cache(path)
    return public(cache, tracked, canon=canon, now=now, why_missing=why, scrub=scrub)


def assessment_source(source: dict | None) -> dict | None:
    """The citation a water's block carries (name, the national files with their addresses, dates and sizes, the map
    layers and their edit date, the fetch time); the per-organization cycles and per-state geometry times stay in
    out/assessments.json, once (they made up half of each block's bytes)."""
    if not isinstance(source, dict):
        return None
    return {k: source[k] for k in SOURCE_KEYS if k in source}


def water_block(a: dict, slug: str) -> dict | None:
    w = a["waters"].get(slug)
    return {"source": assessment_source(a["source"]), "units": w["units"], "summary": w["summary"]} if w else None


def index(a: dict) -> dict:
    return {"built": a["built"], "source": a["source"], "waters": {slug: w["summary"] for slug, w in a["waters"].items()}}


def write_index(out_dir: Path, a: dict) -> Path:
    path = Path(out_dir) / "assessments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index(a), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return path


def meta(a: dict) -> dict:
    """meta.json's counts: a water counts as pathogen-listed or sewage-named when any of its units has the finding,
    those past the block's cap included (the uncapped totals); waters_capped, the blocks cut to MAX_UNITS."""
    s = [w.get("summary") or {} for w in a["waters"].values()]
    return {"built": a["built"], "waters_with_units": len(s),
            "waters_pathogen_listed": sum(1 for x in s if x.get("pathogen_listed_total", x.get("pathogen_listed"))),
            "waters_sewage_named": sum(1 for x in s if x.get("sewage_named_total", x.get("sewage_named"))),
            "waters_capped": sum(1 for x in s if x.get("units_total", 0) > x.get("units", 0)),
            "unavailable": a["unavailable"]}


# ---------------------------------------------------------------- the download


def csv_rows(a: dict, names: dict | None = None) -> list[list[str]]:
    """One row per tracked water and matched unit, every unit (no cap), waters by slug, units in the block's order
    (a pathogen listing first, then a sewage source, then distance). Cell values as export/csv.py writes them."""
    from export.csv import _number, _text, _url
    names = names or {}
    rows = []
    for slug in sorted(a["waters"]):
        w = a["waters"][slug]
        for u in w.get("all_units") or w.get("units") or []:
            rec = u.get("recreation") or {}
            pats = u.get("pathogens") or []
            srcs = u.get("sewage_sources") or []
            m = u.get("match") or {}
            listed = any(str(p.get("status")).lower() == "cause" for p in pats)
            rows.append([
                _text(slug), _text(names.get(slug)), _text(u.get("org_id")), _text(u.get("org_name")),
                _text(u.get("state")), _text(u.get("au_id")), _text(u.get("au_name")), _number(u.get("cycle")),
                _text(u.get("cycle_status")), _text(u.get("water_type")), _number(u.get("size")),
                _text(u.get("size_units")), _text(u.get("location")), _text(rec.get("support")),
                _text(LIST_SEP.join(rec.get("uses") or [])), _text(rec.get("monitoring_start")),
                _text(rec.get("monitoring_end")), _text(rec.get("assessment_date")),
                _text(LIST_SEP.join(str(p.get("parameter") or "") for p in pats)),
                _text(LIST_SEP.join(str(p.get("status") or "") for p in pats)),
                _text(LIST_SEP.join(str(p.get("ir_category") or "") for p in pats)),
                "true" if listed else "false", "true" if u.get("has_tmdl") else "false",
                _text(LIST_SEP.join(str(x.get("name") or "") for x in srcs)),
                _text(LIST_SEP.join(str(x.get("kind") or "") for x in srcs)),
                _number(u.get("sources_cycle")), _url(u.get("report_url")), _url(u.get("latest_url")),
                _text(m.get("method")), _number(m.get("distance_m")), _text(u.get("from"))])
    return rows


def write_csv(path: Path, a: dict, names: dict | None = None) -> int:
    """out/csv/assessments.csv (UTF-8 without a byte-order mark, RFC 4180, CRLF, a header row); the rows written.
    No file when no water has a unit (a stale or missing cache), and an older one is removed."""
    path = Path(path)
    rows = csv_rows(a, names)
    if not rows:
        path.unlink(missing_ok=True)
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)           # comma, quote only where needed, quote doubled, CRLF line ends
        w.writerow(CSV_COLUMNS)
        w.writerows(rows)
    tmp.replace(path)
    return len(rows)
