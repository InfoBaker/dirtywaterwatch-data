"""The generic ingester's runner (not a feed): read data/sources/<id>.yaml, fetch by its platform (or read a saved
response), keep the safe fields, map each row to the event record (fieldmap.py), dedupe, carry the history of
earlier runs, and write data/build/events/<id>.json exactly as a feed module does.

  python -m ingest.generic <source-id> [--file saved] [--meta saved-metadata.json] [--out path]
  python -m ingest.generic --list        the sources make ingest runs (fetch blocks with live: true), in order
  python -m ingest.generic --check       every fetch block validated; nothing is fetched or written

A block with live: false (a port being compared with its module) runs only with --out, so it never replaces the
module's events file; a live block whose module is still a feed is refused, so the two never write one file. Every
failure (a block that cannot run, a fetch, a short response, too many rows a hook could not read) is written to the
events file as ok: false, and the previous records stay.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
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
INGEST_DIR = Path(__file__).resolve().parent.parent
RECORD_INTERNAL = {"_start_dt", "_end_dt"}
MISSING_KEY = "_missing_from_source_since"
MAX_ERROR_SHARE = 0.2
MIN_ROWS_RATIO = 0.5
SHORT_RUNS_TO_ACCEPT = 3      # a short response that persists this many runs in a row is the source's new size
# keys every block may carry, and the keys of each platform (every block setting is checked)
COMMON_KEYS = {"platform", "live", "time_zone", "safe_fields", "reviewed_fields", "free_text", "filter", "bounds",
               "record", "transform", "waters", "dedupe", "post", "history", "meta", "raw_notes", "decoded_times",
               "headers", "browser_headers", "max_error_share", "min_rows_ratio", "after", "module",
               "short_runs_to_accept"}
PLATFORM_KEYS = {
    "socrata": {"domain", "dataset", "format", "metadata", "where", "order", "page_size", "max_rows"},
    "arcgis": {"url", "where", "out_fields", "order_by", "cursor_field", "page_size", "max_rows", "geometry", "metadata"},
    "csv": {"url", "params", "csv"}, "json": {"url", "params", "json"}, "rss": {"url", "params"},
    "atom": {"url", "params"},
}
REQUIRED_KEYS = {"socrata": {"domain", "dataset"}, "arcgis": {"url"}, "csv": {"url"}, "json": {"url"}, "rss": {"url"},
                 "atom": {"url"}}
# meta keys renamed to the names the export publishes (export/build.py PUBLIC_FEED_META)
META_ALIASES = {"time_basis": "time_note", "caveat": "disclaimer", "time_zone": "timezone"}


class RunFailed(RuntimeError):
    """A run whose records must not replace the previous ones."""


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
            try:
                d = yaml.safe_load(q.read_text()) or {}
            except yaml.YAMLError:
                continue
            if isinstance(d, dict) and d.get("id") == source_id:
                row = d
                break
    if not isinstance(row, dict):
        raise F.SpecError(f"no registry row {source_id}")
    block = row.get("fetch")
    if not isinstance(block, dict):
        raise F.SpecError(f"{source_id} has no fetch block")
    return row, block


def blocks(sources_dir: Path = SOURCES_DIR, unreadable: list | None = None) -> dict[str, tuple[dict, dict]]:
    """{source id: (row, fetch block)} for every registry row with a fetch block; files that cannot be read are
    named in unreadable."""
    out = {}
    for p in sorted(sources_dir.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except (yaml.YAMLError, OSError) as e:
            if unreadable is not None:
                unreadable.append(f"{p.name}: {type(e).__name__}")
            continue
        if isinstance(d, dict) and d.get("fetch") is not None:
            if not isinstance(d["fetch"], dict):
                if unreadable is not None:
                    unreadable.append(f"{p.name}: fetch is not a mapping")
                continue
            out[d.get("id") or p.stem] = (d, d["fetch"])
    return out


def module_feed(source_id: str, block: dict) -> str | None:
    """The feed module that writes the same events file (ingest/<id with _>.py, or the block's `module`), when it is
    still a feed (has a __main__ and is not marked "not a feed", the Makefile's rule)."""
    for name in filter(None, [block.get("module"), source_id.replace("-", "_")]):
        p = INGEST_DIR / f"{name}.py"
        if p.exists():
            text = p.read_text()
            if re.search(r"__name__ == .__main__.", text) and "not a feed" not in text:
                return name
    return None


def live_ids(sources_dir: Path = SOURCES_DIR, problems: list | None = None) -> list[str]:
    """The live blocks in run order: by id, except that a block runs after the ids it names in `after`. A live block
    whose module is still a feed is left out and named in problems."""
    problems = problems if problems is not None else []
    found = blocks(sources_dir, problems)
    ids = []
    for sid, (row, b) in sorted(found.items()):
        if b.get("live") is not True or row.get("enabled", True) is False:
            continue
        mod = module_feed(sid, b)
        if mod:
            problems.append(f"{sid}: live, but ingest/{mod}.py still writes its events file (mark the module "
                            f"\"not a feed\" when the block replaces it)")
            continue
        ids.append(sid)
    order, done, visiting = [], set(), set()

    def visit(sid):
        if sid in done:
            return
        if sid in visiting:
            problems.append(f"{sid}: a cycle in after")
            return
        visiting.add(sid)
        for dep in F.listify(found[sid][1].get("after")):
            if dep in ids:
                visit(dep)
        visiting.discard(sid)
        done.add(sid)
        order.append(sid)
    for sid in ids:
        visit(sid)
    return order


def check_all(sources_dir: Path = SOURCES_DIR) -> dict[str, list[str]]:
    unreadable: list = []
    out = {sid: errs for sid, (_, b) in blocks(sources_dir, unreadable).items() if (errs := validate_block(b, sid))}
    for u in unreadable:
        out[u.split(":")[0]] = [u]
    return out


def validate_block(block: dict, source_id: str = "") -> list[str]:
    errs = F.validate(block, source_id)
    try:
        mod = platform(block.get("platform", ""))
    except F.SpecError as e:
        return errs + [str(e)]
    p = block["platform"]
    inner = block.get("rows_from") if p == "snapshot" else p
    allowed = COMMON_KEYS | PLATFORM_KEYS.get(inner, set()) | ({"rows_from", "snapshot"} if p == "snapshot" else set())
    unknown = set(block) - allowed
    if unknown:
        errs.append(f"unknown settings {sorted(unknown)} for platform {p}" + (f" (rows from {inner})" if p == "snapshot" else ""))
    missing = REQUIRED_KEYS.get(inner, set()) - set(block)
    if missing:
        errs.append(f"missing settings {sorted(missing)} for {inner}")
    if inner == "arcgis" and block.get("out_fields") is not None:
        of = block["out_fields"]
        if not isinstance(of, list) or set(of) - set(block.get("safe_fields") or []):
            errs.append("arcgis out_fields is a list of safe fields (never *)")
    if inner == "socrata" and block.get("format") not in (None, "json", "csv"):
        errs.append("socrata format is json or csv")
    k = block.get("short_runs_to_accept")
    if k is not None and (isinstance(k, bool) or not isinstance(k, int) or k < 1):
        errs.append("short_runs_to_accept is a whole number of runs, 1 or more")
    if p == "snapshot":
        errs = [e for e in errs if "source_record_id" not in e] + mod.validate(block)
        if inner and inner != "snapshot":
            try:
                platform(inner)
            except F.SpecError as e:
                errs.append(str(e))
    return errs


# ---------------------------------------------------------------- rows to records

def keep_row(row: dict, block: dict) -> bool:
    """The block's filter: every rule {field, regex, exclude} must hold (exclude: true drops matching rows)."""
    for rule in block.get("filter") or []:
        hit = bool(re.search(rule["regex"], F.clean(F.get(row, rule["field"])), re.I))
        if hit == bool(rule.get("exclude")):
            return False
    return True


def match_water(rec: dict, row: dict, notes: dict, ctx: F.Ctx) -> tuple[list[str], str]:
    """(water_slugs, water_match): text that names no water stays text and is placed on none; otherwise the
    block's matcher (waters.matcher), when it has one; else none (the status build matches by name later)."""
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


def to_record(row: dict, ctx: F.Ctx, dropped: list | None = None) -> dict:
    """One safe row -> one event record. Never drops a row: what cannot be read is a record with a parse_error.
    A transform or matcher that fails leaves the mapped fields and the record key as the field map made them, adds
    its error, and counts in raw._hook_errors (the run fails when too many rows have one)."""
    block = ctx.block
    raw = {"row": dict(row)}
    if dropped:
        raw["_dropped_objects"] = sorted(dropped)
    try:
        rec, notes = F.build_fields(row, ctx)
    except F.SpecError:
        raise
    except Exception as e:  # noqa: BLE001 - never drop a record
        raw["_hook_errors"] = [f"field map: {type(e).__name__}: {e}"]
        return event(source_id=ctx.source_id, source_record_id="row-" + F.row_sha(row)[:12],
                     fetched_at=ctx.fetched_at, source_updated_at=ctx.source_updated_at, raw=raw,
                     parse_error=f"the field map could not read this row ({type(e).__name__}: {e})")
    errors = []
    for fn in F.listify(block.get("transform")):
        try:
            F.resolve(fn)(row, rec, notes, ctx)
        except F.SpecError:
            raise
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fn}: {type(e).__name__}: {e}")
    if rec.get("lat") is not None and not rec.get("coord_source"):
        rec["coord_source"] = "source"
    try:
        slugs, how = match_water(rec, row, notes, ctx)
    except F.SpecError:
        raise
    except Exception as e:  # noqa: BLE001
        errors.append(f"{(block.get('waters') or {}).get('matcher')}: {type(e).__name__}: {e}")
        slugs, how = [], "none"
        notes["_water"] = {"why_none": "the water matcher failed on this row"}
    hook_errors = notes.get("_hook_errors", []) + errors        # a value spec's failures, then the hooks'
    problems = notes.pop("_problems", []) + hook_errors
    if hook_errors:
        notes["_hook_errors"] = hook_errors
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


def _track_items(h: dict):
    t = h.get("track") or []
    if isinstance(t, dict):
        for f, o in t.items():
            o = o or {}
            yield f, o.get("key") or "_seen", o.get("label") or "value", o.get("from") or f, bool(o.get("skip_null")), bool(o.get("key"))
    else:
        for f in t:
            yield f, "_seen", "value", f, False, False


def _supersede_keys(rec: dict, keys: list[str]) -> str | None:
    parts = [F.render(t, (rec.get("raw") or {}).get("row") or {}, rec, None) for t in keys]
    return None if any(p is None for p in parts) else "\x1f".join(parts)


def carry_history(records: list[dict], prev_records: list[dict], block: dict, fetched_at: str) -> Counter:
    """First sighting, revisions of the safe fields and tracked values across runs; records that left the source
    are kept with the missing mark (history.missing_key, raw._missing_from_source_since by default): the events
    file is the history seen so far. history.supersede names keys (lists of templates over the row and the record)
    by which a record that left the source is matched to the current row that replaced it (a corrected start or
    address): it is then duplicate_of that row. A record that comes back keeps the gap in raw._absences."""
    h = block.get("history") or {}
    mkey = h.get("missing_key") or MISSING_KEY
    prev = {r["event_id"]: r for r in prev_records or [] if isinstance(r, dict) and r.get("event_id")}
    n = Counter()
    ign = set((block.get("dedupe") or {}).get("ignore") or [])
    listed = bool(h.get("confirm_while_listed"))
    for r in records:
        p = prev.get(r["event_id"])
        praw = (p or {}).get("raw") or {}
        if listed:   # history.confirm_while_listed: this fetch found the record in the source (an advisory still shown)
            r["raw"]["_last_seen_in_source"] = fetched_at
        r["raw"]["_first_seen_at"] = praw.get("_first_seen_at") or (p or {}).get("fetched_at") or fetched_at
        if not p:
            n["new"] += 1
        if praw.get(mkey):
            r["raw"]["_absences"] = list(praw.get("_absences") or []) + [{"missing_since": praw[mkey],
                                                                           "returned_at": fetched_at}]
            n["returned"] += 1
        elif praw.get("_absences"):
            r["raw"]["_absences"] = praw["_absences"]
        if h.get("revisions") and p:
            old, new = praw.get("row") or {}, r["raw"].get("row") or {}
            changed = {k: old.get(k) for k in set(old) | set(new) if k not in ign and F.clean(old.get(k)) != F.clean(new.get(k))}
            revs = list(praw.get("_revisions") or [])
            if changed:
                revs.append({"replaced_at": fetched_at, "seen_until": p.get("fetched_at"),
                             "source_updated_at_before": p.get("source_updated_at"), "old_values": changed})
                n["revised"] += 1
            if revs:
                r["raw"]["_revisions"] = revs
        for f, key, label, src, skip_null, own_key in _track_items(h):
            old = (praw.get(key) if own_key else (praw.get("_seen") or {}).get(f)) if p else None
            seen = list(old or [])
            v = r.get(src[1:]) if str(src).startswith("@") else (r["raw"].get("row") or {}).get(src)
            if not (skip_null and v is None) and (not seen or seen[-1].get(label) != v):
                seen.append({label: v, "first_seen_at": fetched_at})
            if own_key:
                if seen or not skip_null:
                    r["raw"][key] = seen
            else:
                r["raw"].setdefault("_seen", {})[f] = seen
    if h.get("keep_missing", True):
        now = {r["event_id"] for r in records}
        index = []
        for keys in h.get("supersede") or []:
            idx: dict[str, dict] = {}
            for r in records:
                k = _supersede_keys(r, keys)
                if k is not None:
                    idx.setdefault(k, r)
            index.append((keys, idx))
        for eid, p in prev.items():
            if eid in now:
                continue
            p = {**p, "raw": dict(p.get("raw") or {})}
            p["raw"][mkey] = p["raw"].get(mkey) or fetched_at
            if listed:   # the first fetch that no longer found it: the status build ends the advisory there
                p["raw"]["_unlisted_since"] = p["raw"].get("_unlisted_since") or p["raw"][mkey]
            succ = None
            for keys, idx in index:
                k = _supersede_keys(p, keys)
                if k is not None and k in idx:
                    succ = idx[k]
                    break
            if succ is not None and not p.get("duplicate_of"):
                p["duplicate_of"] = succ["event_id"]
                p["raw"]["_duplicate_basis"] = f"gone from the source; {succ['event_id']} looks like its corrected row"
                n["superseded_by_corrected_row"] += 1
            else:
                n["kept_missing"] += 1
            records.append(p)
    return n


def build(source_id: str, block: dict, rows: list[dict], fetched_at: str, prev_records=(), platform_meta=None,
          extra: dict | None = None) -> tuple[list[dict], dict]:
    """(records, stats) from the source's rows: the whole pipeline after the fetch, with no network. RunFailed when
    more than max_error_share of the rows had a hook fail."""
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
    pairs = [F.safe_row(r, block) for r in kept]
    safe = [s for s, _ in pairs]
    records = [to_record(s, ctx, d) for s, d in pairs]
    hook_errors = sum(1 for r in records if r["raw"].get("_hook_errors"))
    share = float(block.get("max_error_share", MAX_ERROR_SHARE))
    if records and hook_errors > share * len(records):
        first = next(r["raw"]["_hook_errors"][0] for r in records if r["raw"].get("_hook_errors"))
        raise RunFailed(f"{hook_errors} of {len(records)} rows could not be read by the block's hooks (more than "
                        f"{share:.0%}); first: {first}")
    records, dups = dedupe(records, safe, block)
    for fn in F.listify(block.get("post")):
        dups.update(F.resolve(fn)(records, ctx) or {})
    # names of private individuals out before the comparison with the previous run (which was written redacted),
    # and again over everything kept
    records = redact.redact_events(records)
    hist = carry_history(records, list(prev_records), block, fetched_at)
    records = redact.redact_events(records)
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    mkey = (block.get("history") or {}).get("missing_key") or MISSING_KEY
    current = [r for r in records if not r["raw"].get(mkey)]
    stats = {"rows": len(rows), "rows_kept_by_filter": len(kept), "records_written": len(records),
             "duplicates": dict(dups), "history": dict(hist),
             "by_type": dict(Counter(r["event_type"] for r in current)),
             "by_status": dict(Counter(r["status"] for r in current)),
             "water_match": dict(Counter(r["water_match"] for r in current)),
             "with_coordinates": sum(1 for r in current if r.get("lat") is not None),
             "parse_errors": sum(1 for r in current if r.get("parse_error")),
             "hook_errors": hook_errors, "source_updated_at": sua}
    return records, stats


# ---------------------------------------------------------------- fetch, save, write

# the platform metadata a block may keep: the fields the platforms read (socrata.source_updated_at,
# arcgis.source_updated_at); a dataset's or layer's metadata also names its owner and editors, never kept
SAFE_META = ("rowsUpdatedAt", "editingInfo.lastEditDate")
SAFE_ROWS_FORMAT = "dww-safe-rows/1"


def safe_meta(meta: dict | None) -> dict | None:
    """Only SAFE_META of the platform's metadata (nested keys kept nested), or None."""
    if not isinstance(meta, dict):
        return None
    out: dict = {}
    for path in SAFE_META:
        v, ok = meta, True
        for k in path.split("."):
            if isinstance(v, dict) and k in v:
                v = v[k]
            else:
                ok = False
                break
        if ok and not isinstance(v, (dict, list)):
            d = out
            *head, last = path.split(".")
            for k in head:
                d = d.setdefault(k, {})
            d[last] = v
    return out


def safe_payload(rows: list[dict], block: dict, meta: dict | None) -> bytes:
    """What data/raw keeps of a response: the rows the block's filter keeps, each cut to its safe fields with free
    text scrubbed (fieldmap.safe_row), and the safe metadata; never the response itself (SOL wave 1 P1-7)."""
    doc = {"format": SAFE_ROWS_FORMAT, "rows": [F.safe_row(r, block)[0] for r in rows if keep_row(r, block)],
           "meta": safe_meta(meta)}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str).encode()


def _saved_safe_rows(content: bytes) -> dict | None:
    try:
        doc = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) and doc.get("format") == SAFE_ROWS_FORMAT else None


def fetch_rows(source_id: str, block: dict, file: str | None, meta_file: str | None) -> tuple[list[dict], dict | None, str | None]:
    """(rows, platform metadata, path of the saved raw record). A fetched response is parsed first; data/raw/<source>/
    (on the machine that runs the fetch) then keeps only safe_payload (the filtered rows' safe fields, scrubbed, and
    SAFE_META) when that changed since the last saved one. A response that fails to parse is not kept. A file saved
    this way replays with --file (its rows are already safe)."""
    mod = platform(block["platform"])
    if file:
        content = Path(file).read_bytes()
        saved = _saved_safe_rows(content)
        if saved is not None:
            return list(saved.get("rows") or []), saved.get("meta"), None
        pmeta = json.loads(Path(meta_file).read_text()) if meta_file else None
        return mod.parse(block, content), safe_meta(pmeta), None
    got = mod.fetch(block, session(block))
    rows = mod.parse(block, got.content)
    meta = safe_meta(got.meta)
    payload = safe_payload(rows, block, meta)
    state_path = STATE_DIR / f"{source_id}-fetch.json"
    state = read_json(state_path, {}) or {}
    sha = hashlib.sha256(payload).hexdigest()
    raw_path = state.get("raw_path")
    if sha != state.get("sha256"):
        p = save_raw(source_id, payload, "json")
        raw_path = str(p.relative_to(ROOT))
        state = {"sha256": sha, "raw_path": raw_path, "saved_at": now_iso(),
                 "versions_saved": int(state.get("versions_saved") or 0) + 1}
    state["fetched_at"] = now_iso()
    state["bytes"] = len(got.content)
    write_json(state_path, state)
    return rows, meta, raw_path


def public_meta(block_meta: dict) -> dict:
    return {META_ALIASES.get(k, k): v for k, v in (block_meta or {}).items()}


def run(source_id: str, file: str | None = None, meta_file: str | None = None, out: str | None = None,
        sources_dir: Path = SOURCES_DIR) -> int:
    row, block = load_source(source_id, sources_dir)
    if out and Path(out).resolve().parent == EVENTS_DIR.resolve():
        print(f"{source_id}: --out inside the events directory would be read as a feed", file=sys.stderr)
        return 2
    live_write = not out
    if live_write and block.get("live") is not True:
        print(f"{source_id}: the fetch block is not live (live: true); pass --out to write elsewhere", file=sys.stderr)
        return 2
    if live_write and module_feed(source_id, block):
        print(f"{source_id}: ingest/{module_feed(source_id, block)}.py still writes this events file; pass --out",
              file=sys.stderr)
        return 2
    snapshot = block.get("platform") == "snapshot"
    if snapshot and file and not out:
        print(f"{source_id}: replaying a saved snapshot needs --out (the live archive takes live polls only)",
              file=sys.stderr)
        return 2
    path = Path(out) if out else EVENTS_DIR / f"{source_id}.json"

    def fail(msg: str, code: int = 1, meta: dict | None = None) -> int:
        write_events(source_id, [], ok=False, error=msg, path=path, meta=meta)
        print(f"{source_id}: FAILED {msg}", file=sys.stderr)
        return code

    errs = validate_block(block, source_id)
    if errs:
        return fail("the fetch block cannot run: " + "; ".join(errs), 2)
    fetched_at = now_iso()
    try:
        rows, pmeta, raw_path = fetch_rows(source_id, block, file, meta_file)
    except Exception as e:  # noqa: BLE001
        return fail(f"{type(e).__name__}: {e}")
    prev_doc = read_json(path, {}) or {}
    prev = prev_doc.get("records", [])
    # a failed run keeps the last good run's meta, so meta.rows is the last good count; short_runs counts the short
    # responses in a row: a short one fails until it persists for short_runs_to_accept runs, then it is accepted
    # as the source's new size (a table that retires rows, a snapshot that loses outfalls never freezes for good)
    prev_meta = prev_doc.get("meta") or {}
    short_runs = int(prev_meta.get("short_runs") or 0) + 1
    accept_after = int(block.get("short_runs_to_accept", SHORT_RUNS_TO_ACCEPT))
    short = None
    extra = {"events_dir": EVENTS_DIR}
    if snapshot:
        snap = importlib.import_module("ingest.generic.snapshot")
        extra["state_path"] = Path(out).with_suffix(".snapshot.json") if out else snap.state_path(source_id)
        extra["state"] = read_json(extra["state_path"], {}) or {}
        ratio = float((block.get("snapshot") or {}).get("min_units_ratio", 0.5))
        units = snap.unit_count([r for r in rows if keep_row(r, block)], block)
        if not units:
            return fail("no units in the snapshot")
        if snap.too_few(units, extra["state"], ratio):
            short = {"units": units, "last_good": extra["state"].get("last_units_n")}
    else:
        prev_rows = prev_meta.get("rows")
        ratio = float(block.get("min_rows_ratio", MIN_ROWS_RATIO))
        if isinstance(prev_rows, int) and prev_rows and len(rows) < prev_rows * ratio:
            short = {"rows": len(rows), "last_good": prev_rows}
    if short is not None:
        what = f"{short.get('units', short.get('rows'))} {'units' if snapshot else 'rows'}"
        if short_runs < accept_after:
            return fail(f"{what} in the response (the last good one had {short['last_good']}); short run "
                        f"{short_runs} of the {accept_after} in a row after which it is accepted",
                        meta={"short_runs": short_runs})
        short["short_runs"] = short_runs
    try:
        records, stats = build(source_id, block, rows, fetched_at, prev, pmeta, extra)
    except Exception as e:  # noqa: BLE001 - a run that cannot finish keeps the previous records
        return fail(f"{type(e).__name__}: {e}")
    if short is not None:
        stats["short_response_accepted"] = short
    if snapshot:
        write_json(extra["state_path"], extra["state"])
    meta = {**stats, **public_meta(block.get("meta") or {}), "platform": block["platform"], "raw_path": raw_path,
            "generic": True, "registry_ids": row.get("registry_ids") or [], "timezone": block.get("time_zone")}
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
    ap.add_argument("--list", action="store_true", help="print the live generic sources in run order")
    ap.add_argument("--check", action="store_true", help="validate every fetch block (nothing is written)")
    a = ap.parse_args(argv)
    if a.list:
        problems: list = []
        ids = live_ids(problems=problems)
        print("\n".join(ids))
        for p in problems:
            print(f"!! {p}", file=sys.stderr)
        return 1 if problems else 0
    if a.check:
        bad = check_all()
        for sid, errs in bad.items():
            print(f"{sid}: " + "; ".join(errs))
        print(f"{len(blocks())} fetch blocks, {len(bad)} with problems")
        return 1 if bad else 0
    if not a.source_id:
        ap.error("a source id, --list or --check")
    try:
        return run(a.source_id, a.file, a.meta, a.out)
    except F.SpecError as e:
        print(f"{a.source_id}: {e}", file=sys.stderr)
        return 2
