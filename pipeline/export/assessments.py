"""The state's own Clean Water Act assessment in out/ (EPA ATTAINS; build/attains.py writes the cache, docs/attains.md):
shown beside a water's status, never changing it. export/build.py calls these:

  load(tracked, canon)            the cache data/build/attains/attains-waters.json kept to the tracked waters, or nothing
                                  (with the reason) when it is missing, unreadable or older than STALE_DAYS
  water_block(a, slug)            `assessment` in waters/<slug>.json: {"source", "units", "summary"} or None; the source
                                  is the citation (assessment_source)
  write_index(out_dir, a)         out/assessments.json: {"built", "source", "waters": {slug: SUMMARY}}, the whole source
                                  block once
  meta(a)                         meta.json's assessments counts
A water's block carries at most MAX_UNITS units (a pathogen listing first, then a sewage source named, then distance);
its summary counts what it carries and, before the cap, units_total, pathogen_listed_total, sewage_named_total.
  write_csv(path, a, names)       the assessment download, out/csv/assessments.csv: one row per tracked water and
                                  matched unit, every unit (CSV_COLUMNS), the conventions of export/csv.py

The audit list of the cache (candidates not taken) is never exported.
"""
from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common import BUILD_DIR

CACHE = BUILD_DIR / "attains" / "attains-waters.json"
STALE_DAYS = 30
MAX_UNITS = 25                       # units a water's block carries (the cache and the download keep all)
SOURCE_KEYS = ("name", "files", "layers", "fetched_at")
LIST_SEP = ";"
CSV_COLUMNS = ["water_slug", "water", "org_id", "org_name", "state", "au_id", "au_name", "cycle", "cycle_status",
               "water_type", "size", "size_units", "location", "recreation_support", "recreation_uses",
               "monitoring_start", "monitoring_end", "assessment_date", "pathogen_parameters", "pathogen_statuses",
               "pathogen_ir_categories", "pathogen_listed", "has_tmdl", "sewage_sources", "sewage_kinds",
               "sources_cycle", "report_url", "latest_url", "match_method", "match_distance_m", "assessment_from"]


def read_cache(path: Path | None = None) -> tuple[dict | None, str | None]:
    """The cache and, when it cannot be used, why (missing, unreadable): never an exception."""
    path = path or CACHE
    if not path.is_file():
        return None, "no assessment file for this export"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError, UnicodeDecodeError):
        return {}, "the assessment file is not readable"


def public(cache: dict | None, tracked, canon=lambda s: s, now: str | None = None,
           why_missing: str | None = None) -> dict:
    """The tracked waters' units and summaries, {"built", "source", "waters": {slug: {"units", "summary"}},
    "unavailable"}. A cache that is missing, unreadable or older than STALE_DAYS gives no water anything, with the
    reason in "unavailable" (the export never fails over it). A slug the cache knows under an older name
    (build/status.py SLUG_ALIASES, through canon) is written under the record's own slug."""
    empty = {"built": None, "source": None, "waters": {}, "unavailable": why_missing or "no assessment file for this export"}
    if not isinstance(cache, dict) or not isinstance(cache.get("waters"), dict):
        return empty if cache is None else {**empty, "unavailable": "the assessment file is not readable"}
    try:
        built = datetime.fromisoformat(str(cache.get("built")).replace("Z", "+00:00"))
        built = built if built.tzinfo else built.replace(tzinfo=UTC)
    except ValueError:
        return {**empty, "unavailable": "the assessment file has no build time"}
    at = datetime.fromisoformat(now.replace("Z", "+00:00")) if now else datetime.now(UTC)
    if at - built > timedelta(days=STALE_DAYS):
        return {**empty, "built": cache.get("built"),
                "unavailable": f"the assessment file was built {built:%Y-%m-%d}, more than {STALE_DAYS} days ago"}
    waters: dict[str, dict] = {}
    for slug, rec in sorted(cache["waters"].items()):
        own = canon(slug)
        if own not in tracked or not isinstance(rec, dict) or not rec.get("units"):
            continue
        if own in waters and own != slug:            # the record's own slug wins over an older name
            continue
        units = sort_units(rec["units"])
        kept = units[:MAX_UNITS]
        waters[own] = {"units": kept, "summary": capped_summary(kept, units), "all_units": units}
    return {"built": cache.get("built"), "source": cache.get("source"), "waters": waters, "unavailable": None}


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


def load(tracked, canon=lambda s: s, path: Path | None = None, now: str | None = None) -> dict:
    cache, why = read_cache(path)
    return public(cache, tracked, canon=canon, now=now, why_missing=why)


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
    s = [w.get("summary") or {} for w in a["waters"].values()]
    return {"built": a["built"], "waters_with_units": len(s),
            "waters_pathogen_listed": sum(1 for x in s if x.get("pathogen_listed")),
            "waters_sewage_named": sum(1 for x in s if x.get("sewage_named")),
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
