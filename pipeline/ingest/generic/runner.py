"""The generic ingester's runner (not a feed): read data/sources/<id>.yaml, fetch by its platform (or read a saved
response), keep the safe fields, map each row to the event record (fieldmap.py), dedupe, carry the history of
earlier runs, and write data/build/events/<id>.json exactly as a feed module does.

  python -m ingest.generic <source-id> [--file saved] [--meta saved-metadata.json] [--out path]
  python -m ingest.generic --list        the sources make ingest runs (fetch blocks with live: true)
  python -m ingest.generic --check       every fetch block validated; non-zero exit on a problem

A block with live: false (a port being compared with its module) runs only with --out, so it never replaces the
module's events file.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from build import redact
from common import (BUILD_DIR, EVENTS_DIR, ROOT, SOURCES_DIR, event, now_iso, path_notes_to_meta, read_json, save_raw,
                    write_events, write_json)
from ingest.generic import fieldmap as F
from ingest.generic.base import session

PLATFORMS = {"socrata": "socrata", "arcgis": "arcgis", "csv": "csv_json", "json": "csv_json", "rss": "rss",
             "atom": "rss", "snapshot": "snapshot"}
STATE_DIR = BUILD_DIR / "generic"
RECORD_INTERNAL = {"_start_dt", "_end_dt"}


def platform(name: str):
    if name not in PLATFORMS:
        raise F.SpecError(f"unknown platform {name!r} (one of {', '.join(sorted(PLATFORMS))})")
    return importlib.import_module(f"ingest.generic.{PLATFORMS[name]}")


# ---------------------------------------------------------------- the registry

def load_source(source_id: str, sources_dir: Path = SOURCES_DIR) -> tuple[dict, dict]:
    """(the registry row, its fetch block) for a source id (the file data/sources/<id>.yaml, or the row whose id
    it is)."""
    p = sources_dir / f"{source_id}.yaml"
    row = yaml.safe_load(p.read_text()) if p.exists() else None
    if row is None:
        for q in sorted(sources_dir.glob("*.yaml")):
            d = yaml.safe_load(q.read_text()) or {}
            if isinstance(d, dict) and d.get("id") == source_id:
                row = d
                break
    if not isinstance(row, dict):
        raise F.SpecError(f"no registry row {source_id}")
    block = row.get("fetch")
    if not isinstance(block, dict):
        raise F.SpecError(f"{source_id} has no fetch block")
    return row, block


def blocks(sources_dir: Path = SOURCES_DIR) -> dict[str, tuple[dict, dict]]:
    """{source id: (row, fetch block)} for every registry row with a fetch block."""
    out = {}
    for p in sorted(sources_dir.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if isinstance(d, dict) and isinstance(d.get("fetch"), dict):
            out[d.get("id") or p.stem] = (d, d["fetch"])
    return out


def live_ids(sources_dir: Path = SOURCES_DIR) -> list[str]:
    return sorted(sid for sid, (row, b) in blocks(sources_dir).items()
                  if b.get("live") is True and row.get("enabled", True) is not False)


def check_all(sources_dir: Path = SOURCES_DIR) -> dict[str, list[str]]:
    return {sid: errs for sid, (_, b) in blocks(sources_dir).items() if (errs := validate_block(b, sid))}


def validate_block(block: dict, source_id: str = "") -> list[str]:
    errs = F.validate(block, source_id)
    try:
        mod = platform(block.get("platform", ""))
    except F.SpecError as e:
        return errs + [str(e)]
    if block.get("platform") == "snapshot":
        errs = [e for e in errs if "source_record_id" not in e] + mod.validate(block)
        if block.get("rows_from") and block["rows_from"] != "snapshot":
            try:
                platform(block["rows_from"])
            except F.SpecError as e:
                errs.append(str(e))
    return errs


# ---------------------------------------------------------------- rows to records

def keep_row(row: dict, block: dict) -> bool:
    """The block's filter: every rule {field, regex, exclude} must hold (exclude: true drops matching rows)."""
    import re
    for rule in block.get("filter") or []:
        hit = bool(re.search(rule["regex"], F.clean(F.get(row, rule["field"])), re.I))
        if hit == bool(rule.get("exclude")):
            return False
    return True


def match_water(rec: dict, row: dict, notes: dict, ctx: F.Ctx) -> tuple[list[str], str]:
    """(water_slugs, water_match): text that names no water stays text and is placed on none; otherwise the
    block's matcher (waters.matcher), when it has one; else none (the status build matches by name later)."""
    import re
    w = ctx.block.get("waters") or {}
    text = F.clean(rec.get("waterbody_text"))
    if not text:
        notes["_water"] = {"why_none": "the source names no receiving water"}
        return [], "none"
    extra = [re.compile(p, re.I) for p in w.get("no_water") or []]
    if F.NO_WATER.match(text) or any(p.search(text) for p in extra):
        notes["_water"] = {"why_none": f"receiving water given as {text!r}: no surface water named"}
        return [], "none"
    if F.NOT_REACHED.search(text):
        notes["_water"] = {"why_none": "the text says the overflow did not reach a water"}
        return [], "none"
    if not w.get("matcher"):
        return [], "none"
    slugs, how, note = F.resolve(w["matcher"])(text, rec, row, ctx)
    if note:
        notes["_water"] = note
    return list(slugs or []), (how if slugs else "none")


def to_record(row: dict, ctx: F.Ctx) -> dict:
    """One safe row -> one event record. Never drops a row: what cannot be read is an unknown record with a
    parse_error."""
    block = ctx.block
    raw = {"row": dict(row)}
    try:
        rec, notes = F.build_fields(row, ctx)
        for fn in F.listify(block.get("transform")):
            F.resolve(fn)(row, rec, notes, ctx)
        if rec.get("lat") is not None and not rec.get("coord_source"):
            rec["coord_source"] = "source"
        slugs, how = match_water(rec, row, notes, ctx)
        problems = notes.pop("_problems", [])
        raw.update(notes)
        sid = rec.pop("source_record_id", None)
        if sid is None:
            sid = "row-" + F.row_sha(row)[:12]
            problems.append("no source record id: the id is a hash of the row")
        rec = {k: v for k, v in rec.items() if k not in RECORD_INTERNAL}
        if rec.get("source_updated_at") is None:          # the record's own edit time, else the dataset's
            rec["source_updated_at"] = ctx.source_updated_at
        return event(source_id=ctx.source_id, source_record_id=str(sid), fetched_at=ctx.fetched_at,
                     water_slugs=slugs, water_match=how, raw=raw, parse_error="; ".join(problems) or None, **rec)
    except F.SpecError:
        raise
    except Exception as e:  # noqa: BLE001 - never drop a record
        sid = None
        try:
            sid = F.value(block["record"]["source_record_id"], row, {}, ctx)
        except Exception:  # noqa: BLE001
            pass
        return event(source_id=ctx.source_id, source_record_id=str(sid or "row-" + F.row_sha(row)[:12]),
                     fetched_at=ctx.fetched_at, source_updated_at=ctx.source_updated_at, raw=raw,
                     parse_error=f"{type(e).__name__}: {e}")


def _order_key(rec: dict, row: dict, order: list[str], ignore) -> tuple:
    out = []
    for o in order:
        desc = o.startswith("-")
        v = rec.get(o.lstrip("-"))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(-v if desc else v)
        else:
            out.append(1 if desc else -1) if v is None else out.append(0)
    return (*out, F.row_sha(row, ignore))


def dedupe(records: list[dict], rows: list[dict], block: dict) -> tuple[list[dict], Counter]:
    """Records that share a source record id: suffix (the default) keeps them all, the copies as id~2, id~3 in the
    block's order and duplicate_of the first; first keeps only the first."""
    d = block.get("dedupe") or {}
    mode, order, ignore = d.get("repeats", "suffix"), list(d.get("order") or []), set(d.get("ignore") or [])
    groups: dict[str, list] = {}
    for rec, row in zip(records, rows):
        groups.setdefault(rec["source_record_id"], []).append((rec, row))
    out, n = [], Counter()
    for key, grp in groups.items():
        if len(grp) == 1:
            out.append(grp[0][0])
            continue
        if mode == "first":
            out.append(grp[0][0])
            n["dropped_repeats"] += len(grp) - 1
            continue
        grp.sort(key=lambda p: _order_key(p[0], p[1], order, ignore))
        first = grp[0][0]
        out.append(first)
        for i, (rec, _) in enumerate(grp[1:], start=2):
            rec["source_record_id"] = f"{key}~{i}"
            rec["event_id"] = f"{rec['source_id']}:{key}~{i}"
            rec["duplicate_of"] = first["event_id"]
            rec["raw"]["_duplicate_basis"] = "the source repeats this record (same record key)"
            out.append(rec)
            n["repeated_rows"] += 1
    return out, n


def carry_history(records: list[dict], prev_records: list[dict], block: dict, fetched_at: str) -> Counter:
    """First sighting, revisions of the safe fields and tracked values across runs; records that left the source
    are kept (raw._missing_from_source_since): the events file is the history seen so far."""
    h = block.get("history") or {}
    prev = {r["event_id"]: r for r in prev_records or [] if isinstance(r, dict) and r.get("event_id")}
    n = Counter()
    for r in records:
        p = prev.get(r["event_id"])
        praw = (p or {}).get("raw") or {}
        r["raw"]["_first_seen_at"] = praw.get("_first_seen_at") or (p or {}).get("fetched_at") or fetched_at
        if not p:
            n["new"] += 1
        if h.get("revisions") and p:
            old, new = praw.get("row") or {}, r["raw"].get("row") or {}
            ign = set((block.get("dedupe") or {}).get("ignore") or [])
            changed = {k: old.get(k) for k in set(old) | set(new) if k not in ign and F.clean(old.get(k)) != F.clean(new.get(k))}
            revs = list(praw.get("_revisions") or [])
            if changed:
                revs.append({"replaced_at": fetched_at, "seen_until": p.get("fetched_at"), "old_values": changed})
                n["revised"] += 1
            if revs:
                r["raw"]["_revisions"] = revs
        for f in h.get("track") or []:
            seen = list(((praw.get("_seen") or {}).get(f)) or [])
            v = (r["raw"].get("row") or {}).get(f)
            if not seen or seen[-1].get("value") != v:
                seen.append({"value": v, "first_seen_at": fetched_at})
            r["raw"].setdefault("_seen", {})[f] = seen
    if h.get("keep_missing", True):
        now = {r["event_id"] for r in records}
        for eid, p in prev.items():
            if eid in now:
                continue
            p = {**p, "raw": dict(p.get("raw") or {})}
            p["raw"]["_missing_from_source_since"] = p["raw"].get("_missing_from_source_since") or fetched_at
            records.append(p)
            n["kept_missing"] += 1
    return n


def build(source_id: str, block: dict, rows: list[dict], fetched_at: str, prev_records=(), platform_meta=None,
          extra: dict | None = None) -> tuple[list[dict], dict]:
    """(records, stats) from the source's rows: the whole pipeline after the fetch, with no network."""
    errs = validate_block(block, source_id)
    if errs:
        raise F.SpecError(f"{source_id}: " + "; ".join(errs))
    tz = ZoneInfo(block.get("time_zone") or "UTC")
    mod = platform(block["platform"])
    sua = mod.source_updated_at(block, platform_meta, tz) if hasattr(mod, "source_updated_at") else None
    ctx = F.Ctx(source_id=source_id, block=block, tz=tz, fetched_at=fetched_at, source_updated_at=sua,
                extra={"platform_meta": platform_meta or {}, **(extra or {})})
    kept = [r for r in rows if keep_row(r, block)]
    if block["platform"] == "snapshot":
        return mod.build(kept, ctx, extra.get("state") if extra else None)
    safe = [F.safe_row(r, block) for r in kept]
    records = [to_record(r, ctx) for r in safe]
    records, dups = dedupe(records, safe, block)
    for fn in F.listify(block.get("post")):
        dups.update(F.resolve(fn)(records, ctx) or {})
    hist = carry_history(records, list(prev_records), block, fetched_at)
    records = redact.redact_events(records)      # private individuals' names in quoted text (build/redact.py)
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    current = [r for r in records if not r["raw"].get("_missing_from_source_since")]
    stats = {"rows": len(rows), "rows_kept_by_filter": len(kept), "records_written": len(records),
             "duplicates": dict(dups), "history": dict(hist),
             "by_type": dict(Counter(r["event_type"] for r in current)),
             "by_status": dict(Counter(r["status"] for r in current)),
             "water_match": dict(Counter(r["water_match"] for r in current)),
             "with_coordinates": sum(1 for r in current if r.get("lat") is not None),
             "parse_errors": sum(1 for r in current if r.get("parse_error")),
             "source_updated_at": sua}
    return records, stats


# ---------------------------------------------------------------- fetch, save, write

def fetch_rows(source_id: str, block: dict, file: str | None, meta_file: str | None) -> tuple[list[dict], dict | None, str | None]:
    """(rows, platform metadata, path of the saved raw response). A fetched response is kept in data/raw/<source>/
    when its content changed since the last saved one."""
    mod = platform(block["platform"])
    if file:
        content = Path(file).read_bytes()
        pmeta = json.loads(Path(meta_file).read_text()) if meta_file else None
        return mod.parse(block, content), pmeta, None
    got = mod.fetch(block, session(block))
    rows = mod.parse(block, got.content)
    state_path = STATE_DIR / f"{source_id}-fetch.json"
    state = read_json(state_path, {}) or {}
    sha = hashlib.sha256(got.content + (got.meta_bytes or b"")).hexdigest()
    raw_path = state.get("raw_path")
    if sha != state.get("sha256"):
        p = save_raw(source_id, got.content, got.ext)
        if got.meta_bytes:
            p.with_suffix(".meta.json").write_bytes(got.meta_bytes)
        raw_path = str(p.relative_to(ROOT))
        state = {"sha256": sha, "raw_path": raw_path, "saved_at": now_iso(),
                 "versions_saved": int(state.get("versions_saved") or 0) + 1}
    state["fetched_at"] = now_iso()
    write_json(state_path, state)
    return rows, got.meta, raw_path


def run(source_id: str, file: str | None = None, meta_file: str | None = None, out: str | None = None,
        sources_dir: Path = SOURCES_DIR) -> int:
    row, block = load_source(source_id, sources_dir)
    errs = validate_block(block, source_id)
    if errs:
        print(f"{source_id}: the fetch block cannot run: " + "; ".join(errs), file=sys.stderr)
        return 2
    if block.get("live") is not True and not out:
        print(f"{source_id}: the fetch block is not live (live: true); pass --out to write elsewhere", file=sys.stderr)
        return 2
    path = Path(out) if out else EVENTS_DIR / f"{source_id}.json"
    fetched_at = now_iso()
    try:
        rows, pmeta, raw_path = fetch_rows(source_id, block, file, meta_file)
    except Exception as e:  # noqa: BLE001
        write_events(source_id, [], ok=False, error=f"{type(e).__name__}: {e}", path=path)
        print(f"{source_id}: FAILED {e}", file=sys.stderr)
        return 1
    prev = (read_json(path, {}) or {}).get("records", [])
    extra = {"events_dir": EVENTS_DIR}
    if block["platform"] == "snapshot":
        snap = importlib.import_module("ingest.generic.snapshot")
        extra["state_path"] = snap.state_path(source_id)
        extra["state"] = read_json(extra["state_path"], {}) or {}
        if snap.too_few(rows, extra["state"], float((block.get("snapshot") or {}).get("min_units_ratio", 0.5))):
            msg = f"{len(rows)} units in the snapshot (previous {len(extra['state'].get('units') or {})})"
            write_events(source_id, [], ok=False, error=msg, path=path)
            print(f"{source_id}: FAILED {msg}", file=sys.stderr)
            return 1
    records, stats = build(source_id, block, rows, fetched_at, prev, pmeta, extra)
    if block["platform"] == "snapshot":
        write_json(extra["state_path"], extra["state"])
    meta = {**stats, **(block.get("meta") or {}), "platform": block["platform"], "raw_path": raw_path,
            "generic": True, "registry_ids": row.get("registry_ids") or [], "time_zone": block.get("time_zone")}
    path_notes_to_meta(records, meta)
    p = write_events(source_id, records, ok=True, error=None, meta=meta, path=path)
    print(f"{source_id}: {stats.get('rows')} rows -> {stats.get('records_written')} records; types {stats.get('by_type')}; "
          f"status {stats.get('by_status')}; water match {stats.get('water_match')} -> {p}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generic ingester: a data/sources/<id>.yaml fetch block -> events file")
    ap.add_argument("source_id", nargs="?")
    ap.add_argument("--file", help="read this saved response instead of fetching")
    ap.add_argument("--meta", help="the platform metadata JSON for --file (Socrata view, ArcGIS layer)")
    ap.add_argument("--out", help="write the events file here (required for a block that is not live)")
    ap.add_argument("--list", action="store_true", help="print the live generic sources, one per line")
    ap.add_argument("--check", action="store_true", help="validate every fetch block")
    a = ap.parse_args(argv)
    if a.list:
        print("\n".join(live_ids()))
        return 0
    if a.check:
        bad = check_all()
        for sid, errs in bad.items():
            print(f"{sid}: " + "; ".join(errs))
        print(f"{len(blocks())} fetch blocks, {len(bad)} with problems")
        return 1 if bad else 0
    if not a.source_id:
        ap.error("a source id, --list or --check")
    return run(a.source_id, a.file, a.meta, a.out)

