"""New Jersey beach monitoring (NJDEP Cooperative Coastal Monitoring Program and the freshwater
and environmental programs on njbeaches.org): beach advisories and closures.

Source
  The public API behind https://njbeaches.org/ (https://beachapi.njdep.rutgers.edu/api/, found in
  the site's Next.js bundle; no key, CORS open; registry row nj-ccmp-beach-api):
    public/data/filters            every monitoring station (1,600) with beach_status_id, name,
                                   municipality, program, category (Ocean/Bay/River/Lake), type
                                   (Primary/Bracket), EPA beach id and lat/lon. The live status.
    public/data/download/incident/ one CSV row per station per incident day: start and end date,
                                   action (CONTAM_ADV advisory, CLOSURE), reason (ELEV_BACT,
                                   HARMFUL_ALGAL_BLOOM, OTHER), source (UNKNOWN, ALGAE, STORM,
                                   WILDLIFE, CSO), indicator (ENTERO, ECOLI, PREEMPT, OTHER).
  Status codes (public/beaches/statuses/): 1 OPEN, 2 ADVISORY, 3 CLOSED, 8 CLOSED_FOR_SEASON,
  9 NOT_YET_OPEN_FOR_SEASON, 13 MONITORING_IN_PROGRESS ("same classification as Open").
  The local health agencies' contact person and phone number in the station list are dropped before
  the raw copy is saved; the raw copy is saved only when it changed.

Snapshot to history (default run)
  ADVISORY -> beach_advisory, CLOSED -> beach_closure, advisory_active. The station list has no
  start time, so a live record starts at the first poll that showed it (raw.started_at_basis says
  so; time_precision 'hour') unless an incident run from the CSVs covers that day, which gives the
  program's start date (day precision). One advisory is ONE record across polls; state in
  data/build/nj-beaches-state.json. Same rules as ingest/me_healthy_beaches.py:
  - a response without a beachList, with no named station, or with fewer than half the previous
    poll's stations is a FAILED FETCH: ok=False, previous records kept, state untouched;
  - a station missing from the list leaves its advisory active (raw.missing_polls); build/status.py
    ages it out 14 days after the last poll that showed it (source_updated_at);
  - a station present with another status (OPEN, MONITORING_IN_PROGRESS, CLOSED_FOR_SEASON, the
    other action ...) is a lift observation; the record is lifted on the second consecutive one,
    with ended_at = the first poll that observed it (raw.lift_observed_between).
  An unrecognised beach_status_id is written as event_type unknown with a parse_error.

Backfill (--backfill [--years 2025,2026])
  The incident CSV per year (default 2025 to this year). Rows of one station and one action whose
  dates touch (next start <= previous end) form one incident: started_at = the first start date,
  ended_at = the last end date (day precision; the program samples on one day and the row ends the
  next), advisory_lifted. A run whose end date is after the download date is advisory_active with no
  end. Rows are kept in the state file, so later polls keep them. A run that covers a live record's
  first day is folded into that record (raw.incident_rows) instead of being a second record.

Mapping
  CONTAM_ADV -> beach_advisory, CLOSURE -> beach_closure. The source code is kept as raw.cause when
  it is not UNKNOWN: a source of CSO (Manasquan, 2026-08-22, preemptive closures) stays a beach
  record with raw.cause "CSO", never a discharge event (no discharger, outfall or volume is given).
  advice_text is the program's own wording (njbeaches.org "Beach Closing / Advisory Policies"); no
  site window (data/rules.json: beach records follow the authority). water_slugs: a New Jersey
  water named in the beach name and near the station (water_match 'name'), else for bay, river and
  lake stations the one water of that kind listing the municipality whose box holds the station
  (unpadded for lakes, and never for a lake beach named after another lake; water_match
  'inferred'); ocean beaches have no water record.

Lag and cadence
  Results are posted the day after sampling (ocean and bay stations are sampled Mondays, retested
  daily while an advisory stands). Season mid-May to mid-September; poll hourly in season, daily
  otherwise (off-season every station reads CLOSED_FOR_SEASON or NOT_YET_OPEN_FOR_SEASON).

Run from pipeline/:  python -m ingest.nj_beaches [--backfill] [--years 2025,2026]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, read_json, save_raw, strip_personal, write_events, write_json
from ingest import nj_waters

SOURCE_ID = "nj-beaches"
API = "https://beachapi.njdep.rutgers.edu/api/"
FILTERS_URL = API + "public/data/filters"
INCIDENT_URL = API + "public/data/download/incident/"
PORTAL_URL = "https://njbeaches.org/"
POLICY_URL = "https://njbeaches.org/closings_advisories"
STATE_PATH = BUILD_DIR / "nj-beaches-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "New Jersey Cooperative Coastal Monitoring Program (NJDEP)"
FIRST_YEAR = 2025
LIFT_CONFIRMATIONS = 2

STATUS_CODES = {1: "OPEN", 2: "ADVISORY", 3: "CLOSED", 8: "CLOSED_FOR_SEASON", 9: "NOT_YET_OPEN_FOR_SEASON",
                13: "MONITORING_IN_PROGRESS"}
LIVE_TYPE = {"ADVISORY": "beach_advisory", "CLOSED": "beach_closure"}
ACTION_TYPE = {"CONTAM_ADV": "beach_advisory", "CLOSURE": "beach_closure"}
LAKE_WORD = re.compile(r"\b(lakes?|ponds?|reservoir|millpond)\b", re.I)

ADVICE = {
    "beach_advisory": (
        "Any initial sample that exceeds the state standard requires that the local health agency issue a "
        "swimming advisory at the bathing beach where the sample was collected. Swimming Advisories warn the "
        "public of potentially unhealthy water conditions. Additional sampling is conducted until water "
        "quality results are again within the standard."),
    "beach_closure": (
        "Beaches are closed if two consecutive samples collected at a bathing beach exceed the state standard. "
        "Beach closings remain in effect until subsequent sampling indicates bacteria levels are again below "
        "the standard. The closure applies to water activities like swimming, wading, and playing in the water. "
        "Health authorities may close beaches at any time for any reason as a precaution in order to protect "
        "public health."),
}
ADVICE_BASIS = ("njbeaches.org Beach Closing / Advisory Policies (N.J.A.C. 8:26): in effect until sampling shows "
                "Enterococci below 104 per 100 mL; no fixed window")


# --------------------------------------------------------------------------- helpers

def _clock() -> datetime:
    """Poll time (UTC); tests replace it."""
    return datetime.now(UTC).replace(microsecond=0)


def utc_iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def mdy(s: str | None) -> str | None:
    """'08/22/2026' -> '2026-08-22'."""
    try:
        return datetime.strptime((s or "").strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def fnum(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def fetch(url: str, params: dict | None = None, tries: int = 3) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # noqa: PERF203
            last = e
            time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def save_if_changed(state: dict, name: str, content: bytes, ext: str) -> None:
    h = hashlib.sha256(content).hexdigest()
    if state.setdefault("raw_hashes", {}).get(name) != h:
        save_raw(SOURCE_ID, content, ext)
        state["raw_hashes"][name] = h


# --------------------------------------------------------------------------- stations

def station_info(b: dict, counties: dict) -> dict | None:
    name = (b.get("station_name") or "").strip()
    if not name:
        return None
    lat, lon = fnum(b.get("latitude")), fnum(b.get("longitude"))
    if lat is not None and lon is not None and not nj_waters.in_nj(lon, lat):
        lat = lon = None
    muni = b.get("municipality") or {}
    return {"station": name, "beach_station_id": b.get("beach_station_id"),
            "beach": (b.get("beach_name") or "").strip() or name, "epa_beach_id": b.get("epa_beach_id"),
            "municipality": (muni.get("name") or "").strip() or None,
            "county": counties.get(muni.get("county_id")),
            "program": (b.get("program") or {}).get("name"), "program_abbv": (b.get("program") or {}).get("abbv"),
            "category": (b.get("category") or {}).get("name"), "station_type": (b.get("type") or {}).get("name"),
            "local_health_authority": (b.get("local_health_authority") or {}).get("name"),
            "public_map_visible": b.get("is_public_visible"), "lat": lat, "lon": lon,
            "beach_status_id": b.get("beach_status_id")}


def validate_snapshot(js, prev_count: int | None) -> tuple[list[dict] | None, dict, str | None]:
    """(active stations, county names, None) or (None, {}, reason) for a failed fetch."""
    p = js.get("payload") if isinstance(js, dict) else None
    if not isinstance(p, dict) or not isinstance(p.get("beachList"), list):
        return None, {}, "malformed response: no payload.beachList"
    counties = {c.get("county_id"): c.get("name") for c in ((p.get("filters") or {}).get("counties") or [])
                if isinstance(c, dict)}
    st = [s for s in (station_info(b, counties) for b in p["beachList"] if isinstance(b, dict) and b.get("is_active"))
          if s]
    if not st:
        return None, {}, "empty response: no active named station"
    if prev_count and len(st) < prev_count / 2:
        return None, {}, f"incomplete response: {len(st)} stations against {prev_count} in the previous poll"
    return st, counties, None


# --------------------------------------------------------------------------- incident CSV

def parse_incidents(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if rows and "Station_Name" not in rows[0]:
        raise ValueError(f"unexpected incident CSV header: {list(rows[0])[:6]}")
    return [{k: (v or "").strip() for k, v in r.items() if k} for r in rows]


def incident_runs(rows: list[dict]) -> dict[str, dict]:
    """Group incident-day rows into incidents: one station, one action, touching dates."""
    by: dict[tuple, list[dict]] = {}
    for r in rows:
        by.setdefault((r.get("Station_Name"), r.get("Beach_Act_Type_Name")), []).append(r)
    groups: list[tuple[str, str, list[dict]]] = []
    for (st, act), rs in by.items():
        rs.sort(key=lambda r: (mdy(r.get("Incident_Start_Date")) or "", mdy(r.get("Incident_End_Date")) or ""))
        cur: list[dict] = []
        cur_end = None
        for r in rs:
            s, e = mdy(r.get("Incident_Start_Date")), mdy(r.get("Incident_End_Date"))
            if cur and s and cur_end and s <= cur_end:
                cur.append(r)
                cur_end = max(cur_end, e or cur_end)
            else:
                if cur:
                    groups.append((st, act, cur))
                cur, cur_end = [r], e
        if cur:
            groups.append((st, act, cur))
    runs: dict[str, dict] = {}
    for st, act, rows_ in groups:
        start = mdy(rows_[0].get("Incident_Start_Date"))
        end = max(filter(None, (mdy(r.get("Incident_End_Date")) for r in rows_)), default=None)
        etype = ACTION_TYPE.get(act, "unknown")
        key = f"{st}:{etype}:{start or 'nostart'}"
        if key in runs:   # rows with no start date: keep them apart
            key += f":{len(runs)}"
        runs[key] = {"station": st, "action": act, "event_type": etype, "start": start, "end": end, "rows": rows_}
    return runs


def run_cause(run: dict) -> str | None:
    causes = sorted({r.get("Beach_Source_Type_Name") for r in run["rows"]} - {"", None, "UNKNOWN"})
    return "; ".join(causes) or None


def row_station(r: dict) -> dict:
    lat, lon = fnum(r.get("Lat_DD")), fnum(r.get("Lon_DD"))
    if lat is not None and lon is not None and not nj_waters.in_nj(lon, lat):
        lat = lon = None
    return {"station": r.get("Station_Name"), "beach": r.get("Beach_Name") or r.get("Station_Name"),
            "municipality": r.get("Municipality") or None, "county": r.get("County_Name") or None,
            "program": r.get("Program_Name") or None, "category": r.get("Location_Type_Name") or None,
            "lat": lat, "lon": lon}


# --------------------------------------------------------------------------- snapshot -> state

def apply_snapshot(state: dict, stations: dict[str, dict], now: datetime) -> None:
    """Fold one valid snapshot into state['active'] / state['lifted'] (rules in the module docstring)."""
    now_utc, now_local = utc_iso(now), now.astimezone(TZ).isoformat()
    active, lifted = state["active"], state["lifted"]
    posted: dict[str, str] = {}
    for sid, s in stations.items():
        code = STATUS_CODES.get(s.get("beach_status_id"))
        if code in ("OPEN", "MONITORING_IN_PROGRESS", "CLOSED_FOR_SEASON", "NOT_YET_OPEN_FOR_SEASON"):
            continue
        etype = LIVE_TYPE.get(code, "unknown")
        key = next((k for k, a in active.items() if a["station"] == sid and a["event_type"] == etype
                    and (etype != "unknown" or a.get("status_id") == s.get("beach_status_id"))), None)
        if key is None:
            key = f"{sid}:{etype}:{now_local[:16]}"
        a = active.get(key) or {"station": sid, "event_type": etype, "first_seen": now_utc,
                                "first_seen_local": now_local, "missing_polls": 0}
        a.update({"status_id": s.get("beach_status_id"), "status_code": code, "last_seen": now_utc,
                  "last_seen_local": now_local, "missing_polls": 0})
        a.pop("pending_lift", None)
        active[key] = a
        posted[sid] = key
    for key in list(active):
        a = active[key]
        if posted.get(a["station"]) == key:
            continue
        s = stations.get(a["station"])
        if s is None:
            a["missing_polls"] = a.get("missing_polls", 0) + 1
            continue
        observed = STATUS_CODES.get(s.get("beach_status_id")) or f"status id {s.get('beach_status_id')}"
        pl = a.setdefault("pending_lift", {"first_observed_at": now_local, "first_observed_utc": now_utc,
                                           "observations": 0, "observed": observed})
        pl["observations"] += 1
        if pl["observations"] < LIFT_CONFIRMATIONS:
            continue
        a.update({"ended_at": pl["first_observed_at"], "lift_observed": pl["observed"],
                  "lift_observed_between": [a.get("last_seen_local"), pl["first_observed_at"]]})
        a.pop("pending_lift", None)
        lifted[key] = active.pop(key)


# --------------------------------------------------------------------------- records

def place(st: dict) -> tuple[list[str], str, dict]:
    pt = (st["lon"], st["lat"]) if st.get("lat") is not None else None
    towns = [st["municipality"]] if st.get("municipality") else None
    slugs, notes = nj_waters.match_waters(st.get("beach"), towns, pt)
    if slugs:
        return slugs, "name", {"notes": notes or None}
    cat = (st.get("category") or "").lower()
    # a lake beach named after a lake with no water record ("Lake Lenape") is not on the town's lake
    if cat != "ocean" and not (cat == "lake" and LAKE_WORD.search(st.get("beach") or "")):
        slugs, note = nj_waters.by_town(st.get("municipality"), st.get("category"), pt,
                                        pad=0 if cat == "lake" else 0.01)
        if slugs:
            return slugs, "inferred", {"notes": [note]}
        if note:
            notes.append(note)
    return [], "none", {"notes": notes or None}


def make_record(*, key: str, etype: str, status: str, st: dict, started_at, ended_at, precision, raw: dict,
                source_updated_at=None, parse_error=None) -> dict:
    slugs, how, pnote = place(st)
    raw = dict(raw)
    if pnote.get("notes"):
        raw["water_match_notes"] = pnote["notes"]
    where = st.get("municipality")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status,
        waterbody_text=f"{st['beach']} ({where})" if where else st["beach"],
        water_slugs=slugs, water_match=how,
        lat=st.get("lat"), lon=st.get("lon"), coord_source="source" if st.get("lat") is not None else None,
        started_at=started_at, ended_at=ended_at, time_precision=precision,
        source_updated_at=source_updated_at, authority=AUTHORITY,
        advice_text=ADVICE.get(etype), advice_window_hours=None,
        advice_window_basis=ADVICE_BASIS if etype in ADVICE else None,
        source_url=PORTAL_URL, raw=raw, parse_error=parse_error,
    )


def run_raw(run: dict) -> dict:
    rows = [{k: r.get(k) for k in ("Incident_Start_Date", "Incident_End_Date", "Beach_Act_Type_Name",
                                   "Beach_Reason_Type_Name", "Beach_Reason_Type_Desc", "Beach_Source_Type_Name",
                                   "Beach_Indicator_Type_Name", "Beach_Indicator_Type_Desc",
                                   "Incident_Additional_Comments")} for r in run["rows"]]
    return {"cause": run_cause(run),
            "reasons": sorted({r.get("Beach_Reason_Type_Name") for r in run["rows"]} - {"", None}),
            "indicators": sorted({r.get("Beach_Indicator_Type_Name") for r in run["rows"]} - {"", None}),
            "incident_rows": rows}


def covers(run: dict, day: str) -> bool:
    """Does the incident run cover this local date (with one day's lag for posting)?"""
    if not run.get("start") or not run.get("end"):
        return False
    end = (date.fromisoformat(run["end"]) + timedelta(days=1)).isoformat()
    return run["start"] <= day <= end


def build_records(state: dict, today: str) -> list[dict]:
    stations = state["stations"]
    runs = state["history"]
    records: dict[str, dict] = {}
    folded: dict[str, str] = {}
    live = list(state["lifted"].items()) + list(state["active"].items())
    for key, a in live:
        m = [rk for rk, r in runs.items() if r["station"] == a["station"] and r["event_type"] == a["event_type"]
             and covers(r, a["first_seen_local"][:10])]
        if len(m) == 1:
            folded[m[0]] = key
    for rk, run in sorted(runs.items()):
        if rk in folded:
            continue
        st = stations.get(run["station"]) or run.get("station_info") or {"station": run["station"], "beach": run["station"]}
        st = {**(run.get("station_info") or {}), **{k: v for k, v in st.items() if v is not None}}
        perr = None
        if run["event_type"] == "unknown":
            perr = f"unrecognised action {run['action']!r}"
        if not run["start"]:
            perr = (perr + "; " if perr else "") + "no start date"
        raw = {"from": "incident CSV", **run_raw(run), "station": run["station"], "program": st.get("program"),
               "location_type": st.get("category"), "county": st.get("county"),
               "local_health_authority": st.get("local_health_authority"), "epa_beach_id": st.get("epa_beach_id")}
        if run["end"] and run["end"] > today:
            status, ended = "advisory_active", None
            raw["note"] = f"incident end date {run['end']} is after the download date: not treated as an end"
        elif run["end"]:
            status, ended = "advisory_lifted", run["end"]
        else:
            status, ended = "unknown", None
            perr = (perr + "; " if perr else "") + "no end date"
        records[rk] = make_record(key=rk, etype=run["event_type"], status=status, st=st, started_at=run["start"],
                                  ended_at=ended, precision="day", raw=raw,
                                  source_updated_at=run.get("downloaded_at"), parse_error=perr)
    by_live = {v: k for k, v in folded.items()}
    for bucket, status in (("lifted", "advisory_lifted"), ("active", "advisory_active")):
        for key, a in state[bucket].items():
            st = stations.get(a["station"]) or {"station": a["station"], "beach": a["station"]}
            raw = {"from": "public/data/filters", "station": a["station"], "status_code": a.get("status_code"),
                   "beach_status_id": a.get("status_id"), "first_seen": a["first_seen"], "last_seen": a["last_seen"],
                   "missing_polls": a.get("missing_polls", 0), "program": st.get("program"),
                   "location_type": st.get("category"), "station_type": st.get("station_type"),
                   "county": st.get("county"), "local_health_authority": st.get("local_health_authority"),
                   "epa_beach_id": st.get("epa_beach_id"), "public_map_visible": st.get("public_map_visible")}
            for k in ("pending_lift", "lift_observed", "lift_observed_between"):
                if a.get(k) is not None:
                    raw[k] = a[k]
            started, prec = a["first_seen_local"], "hour"
            raw["started_at_basis"] = "first poll that showed this status (the station list gives no start time)"
            rk = by_live.get(key)
            if rk:
                run = runs[rk]
                raw.update(run_raw(run))
                raw["incident_end_date"] = run["end"]
                if run["start"] and run["start"] <= a["first_seen_local"][:10]:
                    started, prec = run["start"], "day"
                    raw["started_at_basis"] = "incident CSV start date"
            if status == "advisory_lifted":
                raw["ended_at_basis"] = "first poll that showed the station without this status"
            perr = None
            if a["event_type"] == "unknown":
                perr = f"unrecognised beach_status_id {a.get('status_id')!r}"
            records[key] = make_record(key=key, etype=a["event_type"], status=status, st=st, started_at=started,
                                       ended_at=a.get("ended_at") if status == "advisory_lifted" else None,
                                       precision=prec, raw=raw, source_updated_at=a["last_seen"], parse_error=perr)
    return sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)


# --------------------------------------------------------------------------- main

def backfill(state: dict, years: list[int], now: datetime, errors: list[str]) -> dict:
    got = {}
    for y in years:
        params = {"downloadType": "incident", "program": "", "county": "", "municipality": "", "locationType": "",
                  "stationType": "", "beachId": "", "lha": "", "startDate": f"{y}-01-01", "endDate": f"{y}-12-31"}
        try:
            r = fetch(INCIDENT_URL, params)
            rows = parse_incidents(r.content.decode("utf-8-sig", errors="replace"))
            save_raw(SOURCE_ID, r.content, f"incident-{y}.csv")
        except (requests.RequestException, ValueError) as e:
            errors.append(f"incident CSV {y}: {type(e).__name__}: {e}")
            continue
        # a year's runs are replaced by the new download (revised rows win)
        for k in [k for k, v in state["history"].items() if v.get("year") == y]:
            del state["history"][k]
        for k, run in incident_runs(rows).items():
            run.update({"year": y, "downloaded_at": utc_iso(now), "station_info": row_station(run["rows"][0])})
            state["history"][k] = run
        got[y] = len(rows)
        time.sleep(1)
    return got


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backfill", action="store_true", help="download the incident CSVs (2025 to this year)")
    ap.add_argument("--years", default=None, help="comma-separated years for --backfill")
    args = ap.parse_args(argv)

    now = _clock()
    poll_at = utc_iso(now)
    state = read_json(STATE_PATH, {}) or {}
    for k in ("active", "lifted", "history", "stations"):
        state.setdefault(k, {})

    snap_error = None
    try:
        r = fetch(FILTERS_URL)
        js = r.json()
        stations, _, snap_error = validate_snapshot(js, state.get("last_station_count"))
    except (requests.RequestException, ValueError) as e:
        stations, snap_error = None, f"{type(e).__name__}: {e}"
    if snap_error:
        state["failed_polls"] = state.get("failed_polls", 0) + 1
        state["last_failure"] = {"at": poll_at, "error": snap_error}
        write_json(STATE_PATH, state)
        write_events(SOURCE_ID, [], ok=False, error=snap_error,
                     meta={"active_now": len(state["active"]), "last_poll_at": state.get("last_poll_at")})
        print(f"{SOURCE_ID}: snapshot rejected, records kept: {snap_error}", file=sys.stderr)
        return 1
    # the local health agencies' contact person and phone number never reach disk
    save_if_changed(state, "filters", json.dumps(strip_personal(js), separators=(",", ":")).encode(), "filters.json")

    st_by = {s["station"]: s for s in stations}
    for sid, s in st_by.items():
        state["stations"][sid] = {k: v for k, v in s.items() if k != "beach_status_id"}

    errors: list[str] = []
    fetched_years = {}
    if args.backfill:
        years = ([int(y) for y in args.years.split(",") if y.strip()] if args.years
                 else list(range(FIRST_YEAR, now.astimezone(TZ).year + 1)))
        fetched_years = backfill(state, years, now, errors)
        state["history_fetched_at"] = poll_at
        print(f"backfill: rows per year {fetched_years}, {len(state['history'])} incidents stored")

    apply_snapshot(state, st_by, now)
    records = build_records(state, now.astimezone(TZ).date().isoformat())

    state["last_poll_at"] = poll_at
    state["last_station_count"] = len(st_by)
    state["failed_polls"] = 0
    write_json(STATE_PATH, state)

    counts = {}
    for s in st_by.values():
        c = STATUS_CODES.get(s.get("beach_status_id"), str(s.get("beach_status_id")))
        counts[c] = counts.get(c, 0) + 1
    meta = {"registry_ids": ["nj-ccmp-beach-api"], "stations_active": len(st_by), "station_statuses": counts,
            "active_now": len(state["active"]),
            "pending_lifts": sum(1 for a in state["active"].values() if a.get("pending_lift")),
            "incidents_stored": len(state["history"]), "history_fetched_at": state.get("history_fetched_at"),
            "poll_cadence": "hourly mid-May to mid-September, daily otherwise",
            "credit": "NJDEP Cooperative Coastal Monitoring Program (njbeaches.org)"}
    if errors:
        path = write_events(SOURCE_ID, records, ok=False, error="; ".join(errors), meta=meta)
        print(f"{SOURCE_ID}: partial run, records kept: {'; '.join(errors)} -> {path}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} records ({len(state['active'])} active now) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
