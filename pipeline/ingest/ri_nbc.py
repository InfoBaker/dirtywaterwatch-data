"""Narragansett Bay Commission CSO Alarm Map (Rhode Island): live CSO outfall activations.

Source: NBC's open JSON API behind https://www.narrabay.com/programs-and-initiatives/combined-sewer-overflow-cso/cso-alarm-map/
(no key, no terms stated; footer "Copyright (c) 2026 Narragansett Bay Commission").
- GET https://cso-api.narrabay.com/pins: one row per site (60 CSO outfalls of the Field's Point
  RI0100315 and Bucklin Point RI0100072 systems, 3 plant outfalls, an abandoned site, a demo row
  "OF 000 WBNS Test 2024" and a blank SITE_ID 0 row). ACTIVATION_DATE / DEACTIVATION_DATE hold the
  site's latest alarm while it is within the map's ~48 h window, otherwise null. CSO_ALARM_HISTORYID
  is NBC's alarm id. Ten sites say "No data available" (no live meter).
- GET https://cso-api.narrabay.com/dryoverflows: "Verified Overflow Events in the last 30 Days"
  (SITE_NAME, ACTIVATION_DATE, DEACTIVATION_DATE, DATE_VERIFIED as SQL Server strings like
  "Oct  5 2026  8:50PM"); rows appear after NBC verification (~9 h after the end in the one example).

Quirks:
- Each poll is a snapshot with no history, so this module keeps data/build/ri-nbc-state.json: an
  activation is one event keyed by outfall + activation minute (e.g. OF220-20261005T2050). The state
  file is the archive: do not delete it. Every poll's sighting of an activation is kept in its
  `obs` (runs of [time, state, by], first and last of each run): "active" (on /pins, no
  deactivation), "ended" (a deactivation on /pins or /dryoverflows), "absent" (no longer on /pins).
  `derive` turns them into the record:
  open: the first sighting active; started_at is NBC's ACTIVATION_DATE (minute);
  continue: later active sightings (raw.last_seen_active_at);
  close: NBC's DEACTIVATION_DATE when given (minute); otherwise, once the outfall's row on /pins no
    longer shows the activation and gives no deactivation (the row present, the answer complete:
    MIN_SITES_SHARE of the most sites seen), ended_at = the first poll that no longer showed it (it ended at or before then,
    after raw.last_seen_active_at): status ended, time_precision "poll". If the activation was
    already older than the map's ~48 h window by then (MAP_WINDOW_H), it may have aged off the map
    while still running: status unknown, the end not invented (raw.vanished_without_deactivation);
  reappear: an activation seen active again after it left /pins is ongoing again (raw.spells_seen_active).
- The site's Worker (worker/src/live/nbc.ts) polls the same endpoints every 5 minutes into D1 with the
  same keys. Each run reads its records and revisions (`wrangler d1 execute --remote`, read-only,
  revisions of the last two days after the first full read; `--backfill-worker` reads all; set
  DWW_WORKER_D1=0 to skip) and folds them in as "worker" sightings, so an activation that comes and
  goes between hourly runs is still a record, and start and end sightings are known to 5 minutes.
  Without wrangler the public GET /api/live (events first seen since the last static fetch) is read
  instead. R2 RAW holds every Worker response but cannot be listed from wrangler; it is not read.
- Timezone is not stated. The map calls moment(t).utcOffset("4"), which moment ignores (a string
  without a sign is not an offset), so the page shows the value as the viewer's local wall clock.
  Values without an offset are therefore read as America/New_York wall-clock times; raw keeps the
  source strings and a `timezone_note`. Values that carry an offset or Z are converted.
- No volume (volume_gal null). Receiving water per outfall is not in the feed: it is the research
  inference in research/ri/raw/nbc-outfalls-from-api.csv (water_match "inferred"), mapped to
  openboatlaunch waters by name; where an outfall sits on openboatlaunch's "Pawtucket River" stretch
  of the Seekonk/Blackstone (geometry within 150 m) that slug is added. Moshassuck, Woonasquatucket,
  West River and Bucklin Brook have no openboatlaunch record yet: water_slugs [] and water_match
  "none", with the name kept in waterbody_text. ECHO's permit receiving water (data/outfalls-new-england.json)
  and the RIGIS UTILITY_NBC_Sewer_Overflows_spf point (offset from the API point, STATUS) are kept
  in raw as cross-checks; the RIGIS layer is cached in data/raw/ri-nbc/ and refreshed every 30 days.
- Raw responses are saved to data/raw/ri-nbc/ only when they differ from the last saved copy.
- raw is the public source record: the outfall list behind the water inference is named in
  meta.outfall_list_file, and any note naming a repository file moves to meta.internal_notes
  (common.path_notes_to_meta).

Cadence: hourly with the refresh, plus the Worker's 5-minute polls (the map's own refresh is 60 s,
disabled); /dryoverflows has a 30-day window, so a gap of more than ~28 days in polling loses
verified events for good.

Run: python -m ingest.ri_nbc [--backfill-worker | --no-worker]   (from pipeline/)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, HEADERS, RAW_DIR, ROOT, event, now_iso, path_notes_to_meta, read_json,
                    save_raw, strip_personal, write_events, write_json)
from ingest import ri_waters

SOURCE_ID = "ri-nbc"
PINS_URL = "https://cso-api.narrabay.com/pins"
DRY_URL = "https://cso-api.narrabay.com/dryoverflows"
MAP_URL = "https://www.narrabay.com/programs-and-initiatives/combined-sewer-overflow-cso/cso-alarm-map/"
RIGIS_URL = ("https://services2.arcgis.com/S8zZg9pg23JUEexQ/arcgis/rest/services/"
             "UTILITY_NBC_Sewer_Overflows_spf/FeatureServer/0/query")
STATE_PATH = BUILD_DIR / "ri-nbc-state.json"
OUTFALL_CSV = ROOT / "research" / "ri" / "raw" / "nbc-outfalls-from-api.csv"
RIGIS_CACHE = RAW_DIR / SOURCE_ID / "rigis-nbc-sewer-overflows.json"
TZ = ZoneInfo("America/New_York")
# The site's Worker polls /pins and /dryoverflows every 5 minutes into D1 (worker/src/live/nbc.ts,
# same event keys); its records and revisions are read with wrangler, else from the public /api/live.
LIVE_URL = "https://dirtywaterwatch.org/api/live"
WRANGLER_DIR = ROOT / "worker"
WRANGLER = WRANGLER_DIR / "node_modules" / ".bin" / "wrangler"
D1_DATABASE = "dirtywaterwatch"
WORKER_POLL_MIN = 5
OBS_STATES = ("active", "ended", "absent")
MAP_WINDOW_H = 44   # /pins keeps an alarm ~48 h: an activation that leaves it later may have aged off, not ended
MIN_SITES_SHARE = 0.8   # a /pins answer with fewer sites than this share of the most seen is partial
OBS_NOTE = ("Sightings of this activation on NBC's /pins and /dryoverflows: 'pipeline' is this site's hourly "
            "fetch, 'worker' its 5-minute poller. active = shown with no deactivation; ended = shown with a "
            "deactivation; absent = no longer shown. A run of sightings in the same state keeps its first and last.")

AUTHORITY = "Narragansett Bay Commission CSO Alarm Map"
ADVICE = ("During rainstorms and up to 48 hours after a sewage overflow, there may be increased health "
          "risks from non-contact recreational activities, such as paddling, fishing, etc.")
TZ_NOTE = ("NBC does not state the timezone; the map applies moment.utcOffset(\"4\"), which is a no-op, "
           "so values are shown as local wall clock. Read here as America/New_York; unconfirmed.")
DISCHARGERS = {
    "Field's Point": ("ri-nbc-fields-point", "Narragansett Bay Commission - Field's Point WWTF and associated CSOs", "RI0100315"),
    "Bucklin Point": ("ri-nbc-bucklin-point", "Narragansett Bay Commission - Bucklin Point WWTF and associated CSOs", "RI0100072"),
}
# openboatlaunch maps the tidal stretch below Pawtucket Falls as "Pawtucket River"; an outfall
# inferred to the Seekonk or Blackstone that sits on that stretch is placed on it as well.
SAME_CHANNEL = {"pawtucket-river-ri": {"seekonk-river-ri", "blackstone-river-ri"}}


# ---------------------------------------------------------------- parsing helpers

def parse_time(v) -> tuple[str | None, str | None]:
    """Source time -> (ISO with America/New_York offset, how it was read). None when absent."""
    if v in (None, "", "null"):
        return None, None
    s = str(v).strip()
    m = re.fullmatch(r"/Date\((-?\d+)([+-]\d{4})?\)/", s)
    if m:
        dt = datetime.fromtimestamp(int(m.group(1)) / 1000, UTC).astimezone(TZ)
        return dt.isoformat(timespec="seconds"), "epoch"
    for fmt in ("%b %d %Y %I:%M%p", "%b %d %Y %I:%M:%S%p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
                "%m/%d/%Y %H:%M"):
        try:
            dt = datetime.strptime(" ".join(s.split()), fmt).replace(tzinfo=TZ)
            return dt.isoformat(timespec="seconds"), "naive-local"
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"unparsed time {s!r}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ).isoformat(timespec="seconds"), "naive-local"
    return dt.astimezone(TZ).isoformat(timespec="seconds"), "offset"


def outfall_code(site: str) -> str | None:
    """'OF 220_Moshassuck_Esten' -> 'OF 220'; 'OF 036-1_Felix' -> 'OF 036-1'; 'OF 002 BP' -> 'OF 002 BP'."""
    m = re.match(r"\s*OF\s*(\d{3}(?:-\d+)?)(?:[ _]+(FP|BP)\b)?", site or "")
    if not m:
        return None
    return f"OF {m.group(1)}" + (f" {m.group(2)}" if m.group(2) else "")


def of_number(code: str | None) -> int | None:
    m = re.match(r"OF (\d+)", code or "")
    return int(m.group(1)) if m else None


def record_key(code: str, started_iso: str) -> str:
    return f"{code.replace(' ', '')}-{datetime.fromisoformat(started_iso):%Y%m%dT%H%M}"


# ---------------------------------------------------------------- outfall reference data

def load_outfall_csv() -> dict:
    out = {}
    if OUTFALL_CSV.exists():
        with OUTFALL_CSV.open(newline="") as fh:
            for r in csv.DictReader(fh):
                out[r["site"].strip()] = r
    return out


def receiving_names(inferred: str | None) -> list[str]:
    """'Seekonk River / upper Providence River, inferred' -> ['Seekonk River', 'Providence River']."""
    s = re.sub(r",\s*inferred.*$", "", inferred or "", flags=re.I)
    s = re.sub(r"\([^)]*\)", "", s)
    names = []
    for part in s.split("/"):
        part = re.sub(r"^(upper|lower)\s+", "", part.strip(), flags=re.I).strip()
        if part:
            names.append(part)
    return names


def place_on_waters(names: list[str], lat, lon, echo_water: str | None = None) -> tuple[list[str], dict]:
    near = ri_waters.near(lat, lon, 600)
    near_d = dict(near)
    named = []
    for n in names:
        for slug in ri_waters.by_name(n):
            if slug not in named:
                named.append(slug)
    # Several inferred names (e.g. "Seekonk / upper Providence"): the one the ECHO permit record
    # names for this outfall, else the nearest within 300 m, else all of them.
    how = "name"
    if len(named) > 1:
        echo_pick = [s for s in named if ri_waters.norm(ri_waters.name_of(s)) == ri_waters.norm(echo_water)]
        close = sorted((s for s in named if near_d.get(s, 1e9) <= 300), key=lambda s: near_d[s])
        if echo_pick:
            named, how = echo_pick, "name, alternative chosen by ECHO permit receiving water"
        elif close:
            named, how = close[:1], "name, alternative chosen by distance"
    slugs = list(named)
    for alias, parents in SAME_CHANNEL.items():
        if alias not in slugs and near_d.get(alias, 1e9) <= 150 and parents & set(named):
            slugs.append(alias)
    if len(slugs) > len(named):
        how += "; same-channel stretch added by geometry (<=150 m)"
    return slugs, {"inferred_names": names, "how": how if slugs else None, "nearest_waters_m": near[:3]}


def load_rigis(session: requests.Session) -> dict:
    """OF number -> list of {x, y, status} from the RIGIS layer (cached 30 days)."""
    cached = read_json(RIGIS_CACHE)
    fresh = cached and datetime.fromisoformat(cached["fetched_at"].replace("Z", "+00:00")) > datetime.now(UTC) - timedelta(days=30)
    if not fresh:
        try:
            r = session.get(RIGIS_URL, params={"where": "1=1", "outFields": "OF_,STATUS", "outSR": 4326,
                                               "f": "json", "resultRecordCount": 2000}, timeout=60)
            r.raise_for_status()
            js = r.json()
            if "features" not in js:
                raise ValueError(str(js)[:200])
            cached = {"fetched_at": now_iso(), "url": RIGIS_URL, "features": js["features"]}
            write_json(RIGIS_CACHE, cached)
        except Exception as e:  # cross-check only; never fatal
            print(f"ri-nbc: RIGIS layer unavailable ({e})", file=sys.stderr)
    out = {}
    for f in (cached or {}).get("features", []):
        a, g = f.get("attributes", {}), f.get("geometry") or {}
        if a.get("OF_") is not None and "x" in g:
            out.setdefault(int(a["OF_"]), []).append({"lon": g["x"], "lat": g["y"], "status": a.get("STATUS")})
    return out


def load_echo_outfalls() -> dict:
    reg = read_json(DATA_DIR / "outfalls-new-england.json", {}) or {}
    return {(o["npdes_permit"], o["outfall"]): o for o in reg.get("outfalls", [])
            if o["npdes_permit"] in ("RI0100315", "RI0100072")}


def metres(lat1, lon1, lat2, lon2) -> int:
    return int(round(((lat1 - lat2) * ri_waters.MY) ** 2 + ((lon1 - lon2) * ri_waters.MX) ** 2) ** 0.5)


def site_info(pin: dict, csv_rows: dict, rigis: dict, echo: dict) -> dict:
    """Everything about an outfall site that does not change between polls."""
    site = (pin.get("SITE_DESCRIPTION") or "").strip()
    code = outfall_code(site)
    num = of_number(code)
    row = csv_rows.get(site) or next((r for r in csv_rows.values() if outfall_code(r["site"]) == code), None)
    system = (row or {}).get("system") or ("Bucklin Point" if (num or 0) >= 100 or code and code.endswith("BP") else "Field's Point")
    lat = float(pin["OUTFALL_LAT"]) if pin.get("OUTFALL_LAT") not in (None, "", "null") else None
    lon = float(pin["OUTFALL_LONG"]) if pin.get("OUTFALL_LONG") not in (None, "", "null") else None
    permit = DISCHARGERS[system][2]
    plant = bool(code and code.endswith(("FP", "BP")))
    echo_key = f"{num:03d}" if plant else (f"{num:03d}A" if num is not None else None)
    eo = echo.get((permit, echo_key)) if echo_key else None
    names = receiving_names((row or {}).get("receiving_water_inferred"))
    slugs, placement = place_on_waters(names, lat, lon, eo.get("receiving_water_echo") if eo else None)
    rig = None  # RIGIS numbers CSO regulators only; plant outfalls (OF 002 FP/BP, OF 003 BP) collide
    if num is not None and lat is not None and not plant and rigis.get(num):
        rig = min(({**p, "offset_m": metres(lat, lon, p["lat"], p["lon"])} for p in rigis[num]), key=lambda p: p["offset_m"])
        if rig["offset_m"] > 1000:
            rig = {**rig, "mismatch": True}
    return {
        "site": site, "code": code, "system": system, "lat": lat, "lon": lon,
        "waterbody_text": (", ".join(names) + " (inferred)") if names else None,
        "water_slugs": slugs, "water_match": "inferred" if slugs else "none",
        "placement": placement,
        "rigis": rig, "echo_receiving_water": eo.get("receiving_water_echo") if eo else None,
        "echo_outfall": echo_key if eo else None,
        "live_meter": not re.search(r"no (live )?data available", pin.get("SITE_NOTES") or "", re.I),
    }


# ---------------------------------------------------------------- observations across polls

def z(t: str | None) -> str | None:
    """Any ISO time -> UTC 'YYYY-MM-DDTHH:MM:SSZ' (observation times compare as strings)."""
    if not t:
        return None
    dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def add_obs(ev: dict, at: str, state: str, by: str) -> None:
    """One poll's sighting of an activation: state "active" (on /pins with no deactivation), "ended"
    (on /pins or /dryoverflows with a deactivation) or "absent" (no longer on /pins). Kept sorted;
    a run of sightings in the same state keeps only its first and last, so the list stays short."""
    assert state in OBS_STATES, state
    pts = {tuple(p) for p in ev.get("obs") or []}
    pts.add((z(at), state, by))
    pts = sorted(pts)
    keep = []
    for i, p in enumerate(pts):
        prev_same = i > 0 and pts[i - 1][1] == p[1]
        next_same = i + 1 < len(pts) and pts[i + 1][1] == p[1]
        if not (prev_same and next_same):
            keep.append(list(p))
    ev["obs"] = keep


def derive(ev: dict) -> None:
    """Status and end of one activation from the source's own times and the observations:
    - the source's deactivation (DEACTIVATION_DATE on /pins or /dryoverflows) ends it, minute precision;
    - the latest sighting active: ongoing;
    - seen active, then no longer on /pins without a deactivation: ended at the first poll that no
      longer showed it (it ended at or before then, after last_seen_active_at), time_precision "poll";
      unless the activation was older than the map's ~48 h window by then (it may have aged off the
      map while still running): status unknown, the end not invented;
    - no sightings (a /dryoverflows-only row): ended when the source gives the end, else unknown."""
    pts = sorted(tuple(p) for p in ev.get("obs") or [])
    act = [p for p in pts if p[1] == "active"]
    last_act = act[-1][0] if act else None
    clear = next((p for p in pts if last_act and p[0] > last_act and p[1] != "active"), None)
    ev["first_seen_active_at"] = act[0][0] if act else None
    ev["last_seen_active_at"] = last_act
    ev["first_seen_clear_at"] = clear[0] if clear else None
    ev["spells"] = sum(1 for i, p in enumerate(pts) if p[1] == "active" and (i == 0 or pts[i - 1][1] != "active"))
    ev.pop("vanished", None)
    if ev.get("parse_error"):
        ev.update(state="unknown", ended_at=None, end_basis=None)
    elif ev.get("source_ended_at"):
        ev.update(state="ended", ended_at=ev["source_ended_at"], end_basis="source")
    elif pts and pts[-1][1] == "active":
        ev.update(state="ongoing", ended_at=None, end_basis=None)
    elif clear:
        ev["vanished"] = {"last_seen_at": last_act, "missing_at": clear[0]}
        start = ev.get("started_at")
        age_h = ((datetime.fromisoformat(clear[0].replace("Z", "+00:00")) - datetime.fromisoformat(start))
                 .total_seconds() / 3600) if start else None
        if age_h is not None and age_h > MAP_WINDOW_H:
            ev.update(state="unknown", ended_at=None, end_basis=None)
        else:
            end = datetime.fromisoformat(clear[0].replace("Z", "+00:00")).astimezone(TZ).isoformat(timespec="seconds")
            ev.update(state="ended", ended_at=end, end_basis="poll")
    elif pts:
        ev.update(state="unknown", ended_at=None, end_basis=None)
    else:
        ev.update(state=ev.get("state") if ev.get("state") in ("ongoing", "unknown") else "unknown",
                  ended_at=None, end_basis=None)


def migrate(state: dict) -> None:
    """State files written before the observation runs: the stored end is the source's, and an
    activation last seen ongoing was seen active at its last sighting."""
    for ev in (state.get("events") or {}).values():
        if "source_ended_at" not in ev and "end_basis" not in ev:
            ev["source_ended_at"] = ev.get("ended_at")
            if not ev.get("obs") and ev.get("state") in ("ongoing", "unknown") and not ev.get("parse_error"):
                seen = (ev.get("vanished") or {}).get("last_seen_at") or ev.get("last_seen_at")
                if seen:
                    add_obs(ev, seen, "active", "pipeline")
                if (ev.get("vanished") or {}).get("missing_at"):
                    add_obs(ev, ev["vanished"]["missing_at"], "absent", "pipeline")


# ---------------------------------------------------------------- the Worker's 5-minute polls

def record_obs(rec: dict, at: str) -> list[tuple[str, str]]:
    """A stored Worker record (one revision) as sightings: ongoing -> active at that poll, ended ->
    ended, unknown after it left /pins -> absent at the poll that missed it."""
    st = rec.get("status")
    if st == "ongoing":
        return [(z(at), "active")]
    if st == "ended":
        return [(z(at), "ended")]
    if st == "unknown":
        v = (rec.get("raw") or {}).get("vanished_without_deactivation") or {}
        if isinstance(v, dict) and v.get("missing_at"):
            return [(z(v["missing_at"]), "absent")]
    return []


def worker_from_d1(event_rows: list[dict], revision_rows: list[dict]) -> dict:
    """D1 rows (event: event_id, first_seen_at, last_changed_at; event_revision: event_id,
    fetched_at, record) -> {key: {record, first_seen_at, last_changed_at, obs}}."""
    out = {}
    first = {r["event_id"]: r for r in event_rows}
    for r in sorted(revision_rows, key=lambda r: r.get("fetched_at") or ""):
        eid = r.get("event_id") or ""
        if not eid.startswith(f"{SOURCE_ID}:"):
            continue
        try:
            rec = json.loads(r["record"]) if isinstance(r.get("record"), str) else r.get("record") or {}
        except ValueError:
            continue
        w = out.setdefault(eid.split(":", 1)[1], {"obs": [], "first_seen_at": None, "last_changed_at": None})
        w["record"] = rec
        w["obs"] += record_obs(rec, r["fetched_at"])
        w["last_changed_at"] = max(z(r["fetched_at"]), w["last_changed_at"] or "")
    for key, w in out.items():
        e = first.get(f"{SOURCE_ID}:{key}") or {}
        seen = [t for t in [z(e.get("first_seen_at"))] + [o[0] for o in w["obs"]] if t]
        w["first_seen_at"] = min(seen) if seen else None
        if e.get("last_changed_at"):
            w["last_changed_at"] = max(z(e["last_changed_at"]), w["last_changed_at"] or "")
    return out


def worker_from_live(js: dict) -> dict:
    """GET /api/live (events the Worker first saw after the last static fetch) -> the same shape.
    Only the current status is given: ongoing -> active at first sight and at the last change;
    ended -> ended at the last change; unknown -> absent at the last change."""
    out = {}
    for e in (js or {}).get("events") or []:
        if e.get("source_id") != SOURCE_ID or not str(e.get("event_id") or "").startswith(f"{SOURCE_ID}:"):
            continue
        key = e["event_id"].split(":", 1)[1]
        first, changed = z(e.get("first_seen_at")), z(e.get("last_changed_at") or e.get("first_seen_at"))
        st = e.get("status")
        obs = ([(first, "active"), (changed, "active")] if st == "ongoing" else
               [(changed, "ended")] if st == "ended" else [(changed, "absent")] if st == "unknown" else [])
        rec = {k: e.get(k) for k in ("status", "started_at", "ended_at", "outfall_id", "outfall_name", "lat", "lon",
                                     "parse_error")}
        rec["raw"] = {}
        out[key] = {"record": rec, "first_seen_at": first, "last_changed_at": changed, "obs": [o for o in obs if o[0]]}
    return out


def merge_worker(state: dict, wk: dict, refs: tuple, channel: str) -> dict:
    """Fold the Worker's sightings into the pipeline's state: same event keys (outfall + activation
    minute); an activation only the Worker saw becomes an event here too. The source's own times win;
    the Worker adds sightings (5-minute polls) and its first-seen time."""
    evs = state.setdefault("events", {})
    stats = {"worker_events": len(wk), "worker_new": 0, "worker_obs": 0}
    for key, w in wk.items():
        rec = w.get("record") or {}
        if "unparsed" in key or (rec.get("parse_error") and not rec.get("started_at")):
            continue
        raw = rec.get("raw") or {}
        ev = evs.get(key)
        if ev is None:
            pin = dict(raw.get("pins") or {})
            if not pin.get("SITE_DESCRIPTION"):
                pin["SITE_DESCRIPTION"] = rec.get("outfall_name") or ""
            pin.setdefault("OUTFALL_LAT", rec.get("lat"))
            pin.setdefault("OUTFALL_LONG", rec.get("lon"))
            info = site_info(pin, *refs)
            ev = evs[key] = {"first_seen_at": w.get("first_seen_at"), "site": info["site"], "info": info,
                             "pins_raw": strip_personal(raw.get("pins")) if raw.get("pins") else None,
                             "started_at": rec.get("started_at"), "time_read_as": raw.get("time_read_as"),
                             "alarm_history_id": raw.get("alarm_history_id"), "last_seen_at": w.get("last_changed_at")}
            if raw.get("dryoverflows"):
                ev["dry_raw"] = raw["dryoverflows"]
                ev["verified_at"] = raw.get("verified_at")
            stats["worker_new"] += 1
        else:
            if w.get("first_seen_at") and (not ev.get("first_seen_at") or w["first_seen_at"] < ev["first_seen_at"]):
                ev["first_seen_at"] = w["first_seen_at"]
            if not ev.get("started_at") and rec.get("started_at"):
                ev["started_at"] = rec["started_at"]
        if rec.get("status") == "ended" and rec.get("ended_at") and not ev.get("source_ended_at"):
            ev["source_ended_at"] = rec["ended_at"]
        for at, st in w.get("obs") or []:
            add_obs(ev, at, st, "worker")
            stats["worker_obs"] += 1
        ev["worker"] = {"channel": channel, "first_seen_at": w.get("first_seen_at"),
                        "last_changed_at": w.get("last_changed_at"), "status": rec.get("status")}
    return stats


def read_worker_d1(since: str | None) -> tuple[dict | None, str | None]:
    """The Worker's NBC records and revisions from D1 (wrangler d1 execute --remote, read-only), the
    revisions newer than `since` (all when None). (None, why) when wrangler is missing, not logged in
    or DWW_WORKER_D1=0."""
    if os.environ.get("DWW_WORKER_D1", "1").lower() in ("0", "no", "false", "off"):
        return None, "disabled (DWW_WORKER_D1=0)"
    if not WRANGLER.exists():
        return None, "wrangler is not installed in worker/"
    if since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", since):
        since = None
    sql = (f"SELECT event_id, first_seen_at, last_changed_at, status FROM event WHERE source_id = '{SOURCE_ID}'; "
           f"SELECT event_id, fetched_at, record FROM event_revision WHERE event_id LIKE '{SOURCE_ID}:%'"
           + (f" AND fetched_at > '{since}'" if since else "") + " ORDER BY fetched_at")
    try:
        p = subprocess.run([str(WRANGLER), "d1", "execute", D1_DATABASE, "--remote", "--json", "--command", sql],
                           cwd=WRANGLER_DIR, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                           env={**os.environ, "WRANGLER_SEND_METRICS": "false"})
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"wrangler: {e}"
    out = p.stdout or ""
    if p.returncode != 0 or "[" not in out:
        return None, f"wrangler exit {p.returncode}: {(p.stderr or out).strip()[-300:]}"
    try:
        js = json.loads(out[out.index("["):])
        events, revisions = js[0]["results"], js[1]["results"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return None, f"wrangler output: {e}"
    return worker_from_d1(events, revisions), None


def read_worker_live(session: requests.Session) -> tuple[dict | None, str | None]:
    try:
        r = session.get(LIVE_URL, timeout=30)
        r.raise_for_status()
        return worker_from_live(r.json()), None
    except Exception as e:
        return None, f"{LIVE_URL}: {e}"


# ---------------------------------------------------------------- fetch and state

def fetch(session: requests.Session, url: str):
    r = session.get(url, timeout=45)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"{url}: expected a JSON array, got {type(data).__name__}")
    return data, r.content


def save_if_changed(state: dict, name: str, content: bytes) -> None:
    h = hashlib.sha256(content).hexdigest()
    if state.setdefault("raw_hashes", {}).get(name) != h:
        save_raw(SOURCE_ID, content, f"{name}.json")
        state["raw_hashes"][name] = h


def poll(state: dict, pins: list, dry: list | None, now: str, refs: tuple) -> dict:
    csv_rows, rigis, echo = refs
    evs = state.setdefault("events", {})
    by_site = {}
    seen = set()
    stats = {"pins": len(pins), "pins_active": 0, "dry_rows": len(dry or []), "parse_errors": 0}
    for pin in pins:
        site = (pin.get("SITE_DESCRIPTION") or "").strip()
        if not site or pin.get("SITE_ID") in (0, None) or re.search(r"\bOF 000\b|WBNS", site, re.I):
            continue  # blank row and the WBNS demo site
        info = site_info(pin, csv_rows, rigis, echo)
        by_site[site] = (pin, info)
        if not pin.get("ACTIVATION_DATE"):
            continue
        stats["pins_active"] += 1
        try:
            started, how = parse_time(pin["ACTIVATION_DATE"])
            ended, _ = parse_time(pin.get("DEACTIVATION_DATE"))
            key = record_key(info["code"] or f"SITE{pin['SITE_ID']}", started)
        except Exception as e:
            stats["parse_errors"] += 1
            key = f"SITE{pin.get('SITE_ID')}-unparsed-{pin.get('CSO_ALARM_HISTORYID')}"
            ev = evs.setdefault(key, {"first_seen_at": now})
            ev.update({"site": site, "info": info, "pins_raw": strip_personal(pin), "last_seen_at": now,
                       "parse_error": str(e), "started_at": None, "ended_at": None, "state": "unknown"})
            seen.add(key)
            continue
        ev = evs.setdefault(key, {"first_seen_at": now})
        ev.update({"site": site, "info": info, "pins_raw": strip_personal(pin), "last_seen_at": now,
                   "started_at": started, "time_read_as": how,
                   "alarm_history_id": pin.get("CSO_ALARM_HISTORYID") or ev.get("alarm_history_id")})
        if ended:
            ev["source_ended_at"] = ev.get("source_ended_at") or ended
        add_obs(ev, now, "ended" if ended else "active", "pipeline")
        seen.add(key)

    # last seen active, now gone from /pins without a deactivation: only when the outfall's own row is
    # in this response and the response is complete (a short or empty answer says nothing about an
    # outfall; disappearance from a partial snapshot is not an end)
    state["max_sites"] = max(state.get("max_sites") or 0, len(by_site))
    complete = len(by_site) >= MIN_SITES_SHARE * state["max_sites"]
    stats["pins_complete"] = complete
    for key, ev in evs.items():
        if key not in seen and ev.get("obs") and ev["obs"][-1][1] == "active":
            if complete and ev.get("site") in by_site:
                add_obs(ev, now, "absent", "pipeline")
                stats["left_pins"] = stats.get("left_pins", 0) + 1
            else:
                stats["not_judged"] = stats.get("not_judged", 0) + 1

    for row in dry or []:
        site = (row.get("SITE_NAME") or "").strip()
        pin, info = by_site.get(site, (None, None))
        if info is None:
            fake = {"SITE_DESCRIPTION": site, "SITE_ID": None, "OUTFALL_LAT": None, "OUTFALL_LONG": None}
            info = site_info(fake, csv_rows, rigis, echo)
        try:
            started, how = parse_time(row.get("ACTIVATION_DATE"))
            ended, _ = parse_time(row.get("DEACTIVATION_DATE"))
            verified, _ = parse_time(row.get("DATE_VERIFIED"))
            key = record_key(info["code"] or re.sub(r"\W+", "", site)[:20], started)
        except Exception as e:
            stats["parse_errors"] += 1
            key = "DRY-unparsed-" + hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()[:10]
            ev = evs.setdefault(key, {"first_seen_at": now})
            ev.update({"site": site, "info": info, "dry_raw": row, "last_seen_at": now, "parse_error": str(e),
                       "started_at": None, "ended_at": None, "state": "unknown"})
            continue
        if key not in evs:
            # Same overflow already seen on /pins under a whole-hour shift? Then the two endpoints
            # disagree on timezone: merge, keep the /pins key, and record the shift.
            for k2, e2 in evs.items():
                if e2.get("site") == site and e2.get("started_at") and "dry_raw" not in e2:
                    delta = datetime.fromisoformat(started) - datetime.fromisoformat(e2["started_at"])
                    hours = delta.total_seconds() / 3600
                    if 0 < abs(hours) <= 6 and abs(delta.total_seconds()) % 3600 < 60:
                        e2["tz_shift_dryoverflows_minus_pins_h"] = round(hours)
                        key = k2
                        break
        ev = evs.setdefault(key, {"first_seen_at": now})
        ev.setdefault("info", info)
        if ev["info"].get("lat") is None and info.get("lat") is not None:
            ev["info"] = info
        ev.update({"site": site, "dry_raw": row, "dry_last_seen_at": now, "verified_at": verified,
                   "time_read_as": ev.get("time_read_as") or how})
        ev.setdefault("started_at", started)
        if "tz_shift_dryoverflows_minus_pins_h" in ev:
            ended = ev.get("source_ended_at") or (ended and (datetime.fromisoformat(ended) - timedelta(
                hours=ev["tz_shift_dryoverflows_minus_pins_h"])).isoformat())
        ev["last_seen_at"] = max(ev.get("last_seen_at") or now, now)
        if ended:
            ev["source_ended_at"] = ev.get("source_ended_at") or ended
    for ev in evs.values():
        derive(ev)
    state["last_poll_at"] = now
    state["polls"] = state.get("polls", 0) + 1
    return stats


def time_basis(ev: dict) -> dict:
    return {
        "started_at": "NBC's ACTIVATION_DATE (to the minute)" if ev.get("started_at") else None,
        "ended_at": {
            "source": "NBC's DEACTIVATION_DATE (to the minute)",
            "poll": ("the first poll that no longer showed the activation on /pins, with no deactivation given: it "
                     "ended at or before then, after last_seen_active_at (time_precision poll)"),
        }.get(ev.get("end_basis")),
    }


def to_record(key: str, ev: dict) -> dict:
    info = ev.get("info") or {}
    did, dname, permit = DISCHARGERS.get(info.get("system"), (None, None, None))
    rig = info.get("rigis")
    raw = {
        "pins": ev.get("pins_raw"), "dryoverflows": ev.get("dry_raw"),
        "first_seen_at": ev.get("first_seen_at"), "last_seen_at": ev.get("last_seen_at"),
        "alarm_history_id": ev.get("alarm_history_id"), "verified_at": ev.get("verified_at"),
        "time_read_as": ev.get("time_read_as"), "timezone_note": TZ_NOTE,
        "tz_shift_dryoverflows_minus_pins_h": ev.get("tz_shift_dryoverflows_minus_pins_h"),
        "vanished_without_deactivation": ev.get("vanished"),
        "first_seen_active_at": ev.get("first_seen_active_at"), "last_seen_active_at": ev.get("last_seen_active_at"),
        "first_seen_clear_at": ev.get("first_seen_clear_at"), "spells_seen_active": ev.get("spells"),
        "observations": [{"at": o[0], "state": o[1], "by": o[2]} for o in ev.get("obs") or []],
        "observation_note": OBS_NOTE, "time_basis": time_basis(ev), "worker": ev.get("worker"),
        "water_placement": {**(info.get("placement") or {}), "basis": "inferred from the outfall's site name and coordinates"},
        "echo_outfall": info.get("echo_outfall"), "echo_receiving_water": info.get("echo_receiving_water"),
        "rigis_point": rig, "live_meter": info.get("live_meter"),
        "api_urls": [PINS_URL, DRY_URL],
    }
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="unknown" if ev.get("parse_error") else "cso",
        status=ev.get("state") or "unknown",
        discharger_id=did, discharger_name=dname, npdes_permit=permit,
        outfall_id=info.get("code"), outfall_name=info.get("site") or ev.get("site"),
        waterbody_text=info.get("waterbody_text"), water_slugs=info.get("water_slugs") or [],
        water_match=info.get("water_match") or "none",
        lat=info.get("lat"), lon=info.get("lon"), coord_source="source" if info.get("lat") is not None else None,
        coord_precision_m=max(10, rig["offset_m"]) if rig and not rig.get("mismatch") else None,
        started_at=ev.get("started_at"), ended_at=ev.get("ended_at"),
        time_precision="poll" if ev.get("end_basis") == "poll" else "minute",
        reported_at=ev.get("verified_at"), published_at=None, source_updated_at=None,
        fetched_at=ev.get("last_seen_at") or now_iso(),
        material=None, volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=ADVICE, advice_window_hours=48, advice_window_basis="NBC CSO Alarm Map page",
        source_url=MAP_URL, raw=raw,
        parse_error=ev.get("parse_error") or (
            f"/dryoverflows times differ from /pins by {ev['tz_shift_dryoverflows_minus_pins_h']} h; the timezone "
            "of one endpoint is wrong. Times shown are /pins read as America/New_York (review)"
            if ev.get("tz_shift_dryoverflows_minus_pins_h") else None),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill-worker", action="store_true", help="read every revision the Worker holds in D1")
    ap.add_argument("--no-worker", action="store_true", help="do not read the Worker's polls")
    args = ap.parse_args(argv)
    state = read_json(STATE_PATH, {}) or {}
    migrate(state)
    now = now_iso()
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        pins, pins_bytes = fetch(s, PINS_URL)
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"pins: {e}")
        print(f"ri-nbc: FAILED {e}", file=sys.stderr)
        return 1
    dry, dry_err = None, None
    try:
        dry, dry_bytes = fetch(s, DRY_URL)
    except Exception as e:
        dry_err = f"dryoverflows: {e}"
    save_if_changed(state, "pins", pins_bytes)
    if dry is not None:
        save_if_changed(state, "dryoverflows", dry_bytes)
    refs = (load_outfall_csv(), load_rigis(s), load_echo_outfalls())
    stats = poll(state, pins, dry, now, refs)
    wk_state = state.setdefault("worker", {})
    worker_err, channel = None, None
    if not args.no_worker:
        last = wk_state.get("d1_read_ok_at")
        since = None if args.backfill_worker or not last else z(
            (datetime.fromisoformat(last.replace("Z", "+00:00")) - timedelta(days=2)).isoformat())
        wk, worker_err = read_worker_d1(since)
        channel = "d1"
        if wk is None:
            wk, live_err = read_worker_live(s)
            channel = "api_live" if wk is not None else None
            worker_err = f"D1: {worker_err}" + (f"; {live_err}" if live_err else "; read /api/live instead")
        if wk is not None:
            stats.update(merge_worker(state, wk, refs, channel))
            wk_state[f"{channel}_read_ok_at"] = now
            for ev in state["events"].values():
                derive(ev)
    wk_state.update({"last_channel": channel, "last_error": worker_err, "last_try_at": now})
    write_json(STATE_PATH, state)
    records = sorted((to_record(k, ev) for k, ev in state["events"].items()),
                     key=lambda r: r["started_at"] or "", reverse=True)
    sites = [site_info(p, *refs) for p in pins if (p.get("SITE_DESCRIPTION") or "").strip() and p.get("SITE_ID")
             and not re.search(r"\bOF 000\b|WBNS", p.get("SITE_DESCRIPTION") or "", re.I)]
    meta = {**stats, "dryoverflows_error": dry_err, "polls_total": state["polls"],
            "sites": len(sites), "sites_with_slug": sum(1 for x in sites if x["water_slugs"]),
            "sites_live_meter": sum(1 for x in sites if x["live_meter"]),
            "events_with_tz_disagreement": sum(1 for e in state["events"].values() if e.get("tz_shift_dryoverflows_minus_pins_h")),
            "timezone_note": TZ_NOTE, "outfall_list_file": str(OUTFALL_CSV.relative_to(ROOT)),
            "worker_channel": channel, "worker_error": worker_err, "worker_poll_minutes": WORKER_POLL_MIN,
            "events_by_status": {k: sum(1 for r in records if r["status"] == k) for k in ("ongoing", "ended", "unknown")},
            "events_poll_precision": sum(1 for r in records if r["time_precision"] == "poll"),
            "observation_note": OBS_NOTE}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=dry_err, meta=meta)
    print(f"ri-nbc: {len(records)} events {meta['events_by_status']} ({stats['pins_active']} active on /pins, "
          f"{stats['dry_rows']} verified rows); Worker via {channel}: {stats.get('worker_events', 0)} events, "
          f"{stats.get('worker_new', 0)} new{' (' + worker_err + ')' if worker_err else ''}; "
          f"sites {meta['sites']}, with water slug {meta['sites_with_slug']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
