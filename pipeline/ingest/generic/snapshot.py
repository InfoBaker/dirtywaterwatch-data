"""Generic snapshot state machine: a status layer or page that shows only the current state of each outfall or
station, polled into events opened and closed "at the poll" (not a feed; docs/generic-ingesters.md). The same
machine as the Philadelphia CSOcast ingester, driven by the block.

fetch block keys
  platform: snapshot
  rows_from: the platform that reads one snapshot (arcgis, socrata, csv, json, rss), with its own keys here
  snapshot:
    unit: the field that names one outfall or station
    state: the field whose value says what it is doing
    states: {pattern: active | recent | clear | no_data}, patterns as regular expressions (case ignored), first
            match wins; a value no pattern matches is "unrecognised" and changes nothing
    poll_time: a time spec for the source's own poll time (else our fetch time is used, and said)
    recent_hours: {regex, default}: how far back a "recent" message reaches (72 by default)
    stale_hours: a poll time older than this marks the unit stale (24)
    min_units_ratio: a snapshot with fewer units than this share of the last one is a failed fetch (0.5)
  record: the per-unit fields (event_type, outfall_id, lat, lon, waterbody_text ...), read from the unit's latest
          row; the times and the status come from the machine, so the record map names none of them

The machine (state kept in data/build/generic/<id>-snapshot.json: it is the archive, never delete it)
  open:      the first snapshot that says active opens an event (ongoing); started_at = that poll time, and
             raw.started_after = the last poll that said clear or recent, when there was one
  continue:  later active snapshots keep it ongoing (raw.last_active_at)
  close:     the first snapshot that says clear or recent ends it; ended_at = that poll time (raw.ended_after =
             the last poll that said active); a poll time before the start (the clock went back) uses our fetch
             time (raw.end_basis "fetch")
  recent:    a unit first seen as recent (or seen so after clear) had an event that began and ended between polls:
             an ended event with started_at null, ended_at = that poll, raw.occurred_after = the earliest it can
             have begun (the previous clear poll, or recent_hours before)
  no data:   not an event; an ongoing event becomes unknown until the unit reports again
  vanished:  a unit missing from the snapshot leaves its ongoing event unknown (raw.vanished)
Every time is a poll time: time_precision "poll". Every transition is kept in raw.transitions.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from build import redact
from common import BUILD_DIR, event
from ingest.generic import fieldmap as F

KINDS = {"active", "recent", "clear", "no_data"}
TIME_BASIS = {
    "precision": "poll: started_at and ended_at are the source's poll times of the snapshots our fetch saw, not the "
                 "event's own start and end",
    "started_at": "the poll time of the first snapshot that said the unit was active; it began at or before then, "
                  "after started_after when that is given",
    "ended_at": "the poll time of the first snapshot that no longer said active; it ended at or before then, after "
                "ended_after",
}


def _inner(block: dict):
    from ingest.generic.runner import platform
    return platform(block["rows_from"]), {**block, "platform": block["rows_from"]}


def fetch(block: dict, sess):
    mod, inner = _inner(block)
    return mod.fetch(inner, sess)


def parse(block: dict, content: bytes) -> list[dict]:
    mod, inner = _inner(block)
    return mod.parse(inner, content)


def state_path(source_id: str):
    return BUILD_DIR / "generic" / f"{source_id}-snapshot.json"


def validate(block: dict) -> list[str]:
    errs = []
    s = block.get("snapshot")
    if not isinstance(s, dict):
        return ["fetch.snapshot is missing"]
    if block.get("rows_from") in (None, "snapshot"):
        errs.append("fetch.rows_from names the platform that reads one snapshot")
    for k in ("unit", "state"):
        if not s.get(k):
            errs.append(f"snapshot.{k} is missing")
        elif s[k] not in block.get("safe_fields", []):
            errs.append(f"snapshot.{k} {s[k]!r} is not a safe field")
    for pat, kind in (s.get("states") or {}).items():
        if kind not in KINDS:
            errs.append(f"snapshot.states {pat!r} -> {kind!r} is not one of {sorted(KINDS)}")
        try:
            re.compile(pat)
        except re.error as e:
            errs.append(f"snapshot.states {pat!r}: {e}")
    if not s.get("states"):
        errs.append("snapshot.states is missing")
    for t in F.TIME_FIELDS:
        if t in (block.get("record") or {}):
            errs.append(f"record.{t}: the snapshot machine sets the times")
    return errs


def kind_of(msg, states: dict) -> str:
    m = F.clean(msg)
    for pat, kind in states.items():
        if re.search(pat, m, re.I):
            return kind
    return "unrecognised"


def too_few(rows: list, state: dict, ratio: float = 0.5) -> bool:
    prev_n = len((state or {}).get("units") or {})
    return not rows or bool(prev_n and len(rows) < prev_n * ratio)


def _new_key(evs: dict, name: str, lp: datetime | None, now_dt: datetime, tz) -> str:
    key = base = f"{F.slug(name) or 'unit'}-{(lp or now_dt.astimezone(tz)):%Y%m%dT%H%M}"
    n = 2
    while key in evs:
        key, n = f"{base}-{n}", n + 1
    return key


def recent_hours(msg, spec) -> int:
    spec = spec if isinstance(spec, dict) else {"default": spec or 72}
    m = re.search(spec.get("regex") or r"past\s+(\d+)\s+hours", F.clean(msg), re.I)
    return int(m.group(1)) if m else int(spec.get("default", 72))


def poll(state: dict, rows: list[dict], now: str, ctx: F.Ctx) -> dict:
    """One snapshot (safe rows) into the state. Returns this poll's counts."""
    s = ctx.block["snapshot"]
    units = state.setdefault("units", {})
    evs = state.setdefault("events", {})
    open_ = state.setdefault("open", {})
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    stats = Counter()
    seen = set()
    for a in rows:
        name = F.clean(F.get(a, s["unit"]))
        if not name:
            stats["unnamed"] += 1
            continue
        if name in seen:
            stats["repeated_unit"] += 1
            continue
        seen.add(name)
        msg = F.clean(F.get(a, s["state"]))
        kind = kind_of(msg, s["states"])
        stats[kind] += 1
        lp = None
        if s.get("poll_time"):
            lp, _ = F.time_value(s["poll_time"], a, {}, ctx, {}, "poll_time")
        at = F.iso(lp) if lp else now
        prev = dict(units.get(name) or {})
        o = units.setdefault(name, {"first_seen_at": now})
        if prev.get("message") != msg:
            o["changed_at"] = now
            o["changed_at_poll"] = F.iso(lp)
        o.update({"message": msg, "state": kind, "last_poll": F.iso(lp), "last_seen_at": now, "row": a})
        o["stale"] = bool(lp and now_dt - lp.astimezone(UTC) > timedelta(hours=float(s.get("stale_hours", 24))))
        if kind == "no_data":
            o.setdefault("no_data_since", at)
        else:
            o.pop("no_data_since", None)
        prev_known = prev.get("last_known_state", prev.get("state") if prev.get("state") in ("active", "recent", "clear") else None)
        if kind in ("active", "recent", "clear"):
            o["last_known_state"] = kind
        if kind in ("recent", "clear"):
            o["last_clear_poll"] = at

        key = open_.get(name)
        ev = evs.get(key) if key else None
        trans = {"fetched_at": now, "poll_time": F.iso(lp), "message": msg}
        if ev is not None and (not ev["transitions"] or ev["transitions"][-1]["message"] != msg):
            ev["transitions"].append(trans)
        if kind == "active":
            if ev is None:                                                   # open
                key = _new_key(evs, name, lp, now_dt, ctx.tz)
                ev = evs[key] = {"unit": name, "state": "ongoing", "started_at": at,
                                 "started_after": prev.get("last_clear_poll") if prev_known in ("clear", "recent") else None,
                                 "reported_at": at, "transitions": [trans]}
                if not lp:
                    ev["start_basis"] = "fetch"
                open_[name] = key
                stats["opened"] += 1
            else:                                                            # continue
                if ev["state"] != "ongoing":
                    ev.setdefault("resumed", []).append({"at": at, "after": ev["state"]})
                    ev.pop("vanished", None)
                ev["state"] = "ongoing"
            ev["last_active_at"] = at
        elif kind in ("recent", "clear"):
            if ev is not None:                                               # close
                ev["state"] = "ended"
                if ev.get("started_at") and at < ev["started_at"]:
                    ev["ended_at"], ev["end_basis"] = F.iso(now_dt.astimezone(ctx.tz)), "fetch"
                else:
                    ev["ended_at"], ev["end_basis"] = at, ("poll" if lp else "fetch")
                ev["ended_after"] = ev.get("last_active_at")
                ev["closed_by"] = msg
                open_.pop(name, None)
                stats["closed"] += 1
            elif kind == "recent" and prev_known not in ("active", "recent"):
                hours = recent_hours(msg, s.get("recent_hours"))
                floor = F.iso((lp or now_dt.astimezone(ctx.tz)) - timedelta(hours=hours))
                after = prev.get("last_clear_poll") if prev_known == "clear" else None
                key = _new_key(evs, name, lp, now_dt, ctx.tz)
                evs[key] = ev = {"unit": name, "state": "ended", "started_at": None, "ended_at": at,
                                 "end_basis": "poll" if lp else "fetch", "reported_at": at, "first_seen_as_recent": True,
                                 "occurred_after": max(t for t in (floor, after) if t), "transitions": [trans]}
                stats["opened_recent"] += 1
        elif kind == "no_data":
            if ev is not None and ev["state"] == "ongoing":
                ev["state"] = "unknown"
                ev["no_data_since"] = at
        if ev is not None:
            ev["last_poll"] = F.iso(lp)
            ev["last_seen_at"] = now
    for name, key in list(open_.items()):
        if name not in seen and evs[key]["state"] == "ongoing":
            evs[key]["state"] = "unknown"
            evs[key]["vanished"] = {"last_seen_at": evs[key].get("last_seen_at"), "missing_at": now}
    state["polls"] = state.get("polls", 0) + 1
    state["last_poll_at"] = now
    return dict(stats)


def to_record(key: str, ev: dict, unit: dict, ctx: F.Ctx) -> dict:
    row = unit.get("row") or {}
    rec, notes = F.build_fields(row, ctx)
    for fn in F.listify(ctx.block.get("transform")):
        F.resolve(fn)(row, rec, notes, ctx)
    problems = notes.pop("_problems", [])
    for k in ("source_record_id", "status", "time_precision", "_start_dt", "_end_dt", *F.TIME_FIELDS):
        rec.pop(k, None)
    st = ev["state"]
    ended = ev.get("ended_at") if st == "ended" else None
    if rec.get("lat") is not None and not rec.get("coord_source"):
        rec["coord_source"] = "source"
    from ingest.generic.runner import match_water
    slugs, how = match_water(rec, row, notes, ctx)
    raw = {"row": row, "transitions": ev.get("transitions"), "time_basis": TIME_BASIS,
           "started_after": ev.get("started_after"), "occurred_after": ev.get("occurred_after"),
           "start_basis": ("the first snapshot that said active; it began at or before then" if ev.get("started_at") else
                           "first seen as recent: it began and ended between our polls; the start was not observed"),
           "last_active_at": ev.get("last_active_at"), "ended_after": ev.get("ended_after") if ended else None,
           "end_basis": ev.get("end_basis") if ended else None, "closed_by": ev.get("closed_by"),
           "resumed": ev.get("resumed"), "no_data_since": ev.get("no_data_since"), "vanished": ev.get("vanished"),
           **notes}
    if unit.get("stale") and st == "ongoing":
        problems.append("the unit's poll time is more than the stale limit old: the status may be stale")
    return event(source_id=ctx.source_id, source_record_id=key, status={"ongoing": "ongoing", "ended": "ended"}.get(st, "unknown"),
                 started_at=ev.get("started_at"), ended_at=ended, time_precision="poll",
                 reported_at=ev.get("reported_at"), source_updated_at=ev.get("last_poll"),
                 fetched_at=ev.get("last_seen_at") or ctx.fetched_at, raw=raw,
                 water_slugs=slugs, water_match=how, parse_error="; ".join(problems) or None, **rec)


def build(rows: list[dict], ctx: F.Ctx, state: dict | None) -> tuple[list[dict], dict]:
    """(records, stats): this snapshot polled into the state (changed in place), then every event of the state as a
    record. The state is the history: the runner saves it."""
    state = state if state is not None else {}
    safe = [F.safe_row(r, ctx.block) for r in rows]
    stats = poll(state, safe, ctx.fetched_at, ctx)
    units = state.get("units") or {}
    records = [to_record(k, ev, units.get(ev["unit"], {}), ctx) for k, ev in state.get("events", {}).items()]
    records = redact.redact_events(records)
    records.sort(key=lambda r: (r.get("reported_at") or "", r["event_id"]), reverse=True)
    present = {n: u for n, u in units.items() if u.get("last_seen_at") == ctx.fetched_at}
    out = {"rows": len(rows), "records_written": len(records), "poll": stats, "polls_total": state.get("polls"),
           "events_open": len(state.get("open") or {}), "units_in_snapshot": len(present),
           "by_unit_state": dict(Counter(u.get("state") for u in present.values())),
           "stale": sum(1 for u in present.values() if u.get("stale")),
           "by_type": dict(Counter(r["event_type"] for r in records)),
           "by_status": dict(Counter(r["status"] for r in records)),
           "water_match": dict(Counter(r["water_match"] for r in records)),
           "units": {n: {"state": u.get("state"), "message": u.get("message"), "last_poll": u.get("last_poll"),
                         "stale": u.get("stale"), "no_data_since": u.get("no_data_since"),
                         "present": n in present,
                         "open_event_id": f"{ctx.source_id}:{state['open'][n]}" if n in (state.get("open") or {}) else None}
                     for n, u in sorted(units.items())},
           "time_precision": "poll", "time_basis": TIME_BASIS}
    return records, out
