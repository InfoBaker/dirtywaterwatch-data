"""SFPUC beach and bay map (combined sewer discharge flag and beach postings) -> data/build/events/ca-sfpuc-beach-map.json

Source
  San Francisco Public Utilities Commission, "Beaches and Bay" map (https://webapps.sfpuc.org/sapps/beachesandbay.html,
  linked from https://www.sfpuc.gov/programs/ocean-and-beach-monitoring). The map reads an undocumented service,
  GET https://infrastructure.sfwater.org/lims.asmx/getBeaches, which answers an XML <string> holding a JSON list of
  monitoring stations (20 on 2026-11-04): stationid, stationname, cso, s_color, posted, p_color, sample_date, lat,
  lon. No key, no licence statement. Credit "San Francisco Public Utilities Commission, Beaches and Bay map".
  What the fields mean, from the map page's own script (read 2026-11-04):
  - cso not null: the map draws the CSO sign, "Combined Sewer Discharge has occurred within the last 24-72 hours.
    (Call 1-877-SFBEACH or 1-877-732-3224 for details)". SFPUC's page says signs go up "whenever a Combined Sewer
    System discharge occurs that affects a recreational beach" and stay "until the discharge ceases".
  - s_color "R", or posted with p_color "R" or "G": the station is posted, "Concentrations of bacteria were elevated
    at this location within the past 24 hours or a combined sewer discharge has recently occurred at this site."
  - s_color "W" / "Y": not (routinely) sampled; otherwise the map shows the State's bacteria standards as met.
  Law: SFPUC's combined system permits (NPDES CA0037664 Bayside, CA0037681 Oceanside) carry public notification under
  the CSO Control Policy; the county health officer posts beaches (Health and Safety Code 115885).

What is read (privacy)
  Station fields only; there are no personal fields in the service. Every raw passes common.strip_personal (in
  event()).

Snapshot state machine (data/build/ca-sfpuc-beaches-state.json keeps every station's last state and every event; it
is the archive: do not delete it). All times are our poll times (time_precision "poll"); the service gives none.
  - CSO flag (event_type cso, discharger ca-sfpuc, permit CA0037681 for the Pacific (westside) stations, CA0037664
    for the bay stations): the first poll that shows the flag opens an event, status ongoing, started_at = that poll
    (raw.occurred_after = the last poll that showed no flag, or 72 hours before when there is none: the discharge
    itself happened between those times); it stays ongoing while the flag shows, which is SFPUC's own window, quoted
    in advice_text; the first poll without the flag ends it (ended_at = that poll; raw.flag_last_seen_at = the last
    poll that showed it). The status build then applies the site's caution after the end.
  - Posting (event_type beach_advisory): the first poll that shows a station posted opens an advisory_active record;
    the first poll that does not lifts it (advisory_lifted, ended_at = that poll). The posting's cause (bacteria or a
    discharge) is not given by the service.
  - A station missing from an answer leaves its open records as they are and is marked (raw.missing_since); an answer
    with fewer than half the stations of the last good one is a failed fetch (ok false, the records kept).

Run from pipeline/:  python -m ingest.ca_sfpuc_beaches [--file saved.xml]
Cadence: hourly (the flag is seen only when polled; a flag shown and removed between two polls is missed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, write_events, write_json

SOURCE_ID = "ca-sfpuc-beach-map"
SERVICE = "https://infrastructure.sfwater.org/lims.asmx/getBeaches"
MAP_URL = "https://webapps.sfpuc.org/sapps/beachesandbay.html"
STATE_FILE = BUILD_DIR / "ca-sfpuc-beaches-state.json"
AUTHORITY = "San Francisco Public Utilities Commission (Beaches and Bay map)"
CREDIT = "San Francisco Public Utilities Commission, Beaches and Bay map"
DISCHARGER = "ca-sfpuc"
CSO_TEXT = ("Combined Sewer Discharge has occurred within the last 24-72 hours. (Call 1-877-SFBEACH or "
            "1-877-732-3224 for details)")
POSTED_TEXT = ("Concentrations of bacteria were elevated at this location within the past 24 hours or a combined "
               "sewer discharge has recently occurred at this site.")
FIELDS = ("stationid", "stationname", "cso", "s_color", "posted", "p_color", "sample_date", "lat", "lon")
WESTSIDE_LON = -122.47       # stations west of this face the Pacific (Oceanside permit); the rest face the bay


def parse(text: str) -> list[dict]:
    """The station list inside the service's XML <string> (or a bare JSON list)."""
    s = text.strip()
    m = re.search(r"<string[^>]*>(.*)</string>", s, re.S)
    if m:
        s = m.group(1)
    s = s.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("the service did not answer a list of stations")
    return [{k: x.get(k) for k in FIELDS} for x in data if isinstance(x, dict) and x.get("stationid")]


def flagged(st: dict) -> bool:
    return st.get("cso") not in (None, "", "null")


def posted(st: dict) -> bool:
    return st.get("s_color") == "R" or bool(st.get("posted")) and st.get("p_color") in ("R", "G")


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def permit_for(st: dict) -> str:
    lon = fnum(st.get("lon"))
    return "CA0037681" if lon is not None and lon < WESTSIDE_LON else "CA0037664"


def step(state: dict, stations: list[dict], polled_at: str) -> dict:
    """Advance the state machine by one poll; returns the counts of what changed."""
    st_state = state.setdefault("stations", {})
    events = state.setdefault("events", {})
    changes = {"opened": 0, "closed": 0}
    seen = set()
    poll = datetime.fromisoformat(polled_at.replace("Z", "+00:00"))
    for s in stations:
        sid = str(s["stationid"])
        seen.add(sid)
        prev = st_state.get(sid) or {}
        now = {"cso": flagged(s), "posted": posted(s), "at": polled_at, "station": s}
        for kind, on in (("cso", now["cso"]), ("post", now["posted"])):
            open_id = prev.get(f"open_{kind}")
            if on and not open_id:
                eid = f"{sid}-{kind}-{poll.strftime('%Y%m%dT%H%MZ')}"
                last_off = prev.get(f"last_off_{kind}")
                events[eid] = {"kind": kind, "station": sid, "opened_at": polled_at,
                               "occurred_after": last_off or (poll - timedelta(hours=72)).isoformat().replace("+00:00", "Z"),
                               "occurred_after_basis": ("the last poll that showed none" if last_off else
                                                        "72 hours before the first poll that showed it (none seen earlier)"),
                               "last_seen_at": polled_at, "closed_at": None, "station_row": s}
                now[f"open_{kind}"] = eid
                changes["opened"] += 1
            elif on and open_id:
                events[open_id]["last_seen_at"] = polled_at
                events[open_id]["station_row"] = s
                events[open_id].pop("missing_since", None)
                now[f"open_{kind}"] = open_id
            elif not on and open_id:
                events[open_id]["closed_at"] = polled_at
                changes["closed"] += 1
            if not on:
                now[f"last_off_{kind}"] = polled_at
            elif prev.get(f"last_off_{kind}"):
                now[f"last_off_{kind}"] = prev[f"last_off_{kind}"]
        st_state[sid] = now
    for sid, prev in st_state.items():
        if sid in seen:
            continue
        for kind in ("cso", "post"):
            if prev.get(f"open_{kind}"):
                events[prev[f"open_{kind}"]].setdefault("missing_since", polled_at)
    return changes


def records(state: dict, fetched_at: str) -> list[dict]:
    out = []
    for eid, e in sorted(state.get("events", {}).items()):
        s = e.get("station_row") or {}
        lat, lon = fnum(s.get("lat")), fnum(s.get("lon"))
        raw = {"station": {k: s.get(k) for k in FIELDS}, "occurred_after": e.get("occurred_after"),
               "occurred_after_basis": e.get("occurred_after_basis"), "flag_last_seen_at": e.get("last_seen_at"),
               "_time_basis": "our poll times: the service gives no times"}
        if e.get("missing_since"):
            raw["missing_since"] = e["missing_since"]
        name = s.get("stationname")
        if e["kind"] == "cso":
            status = "ended" if e.get("closed_at") else "ongoing"
            raw["_basis"] = ("SFPUC's map showed the combined sewer discharge sign at this station from the first poll "
                             "to the last; the discharge happened at or before the first poll, after occurred_after")
            out.append(event(
                source_id=SOURCE_ID, source_record_id=eid, event_type="cso", status=status,
                discharger_id=DISCHARGER, discharger_name="San Francisco Public Utilities Commission",
                npdes_permit=permit_for(s), outfall_name=f"Combined sewer discharge near {name}",
                waterbody_text="Pacific Ocean" if permit_for(s) == "CA0037681" else "San Francisco Bay",
                lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=500,
                started_at=e["opened_at"], ended_at=e.get("closed_at"), time_precision="poll",
                reported_at=e["opened_at"], published_at=None, source_updated_at=e.get("last_seen_at"),
                fetched_at=fetched_at, material="combined sewage", authority=AUTHORITY,
                advice_text=CSO_TEXT, advice_window_hours=None,
                advice_window_basis="SFPUC shows the sign while it judges the discharge's effect current; the record "
                                    "is red while the sign shows",
                source_url=MAP_URL, raw=raw))
        else:
            status = "advisory_lifted" if e.get("closed_at") else "advisory_active"
            out.append(event(
                source_id=SOURCE_ID, source_record_id=eid, event_type="beach_advisory", status=status,
                outfall_name=name, waterbody_text="Pacific Ocean" if permit_for(s) == "CA0037681" else
                "San Francisco Bay", lat=lat, lon=lon, coord_source="source" if lat is not None else None,
                started_at=e["opened_at"], ended_at=e.get("closed_at"), time_precision="poll",
                reported_at=e["opened_at"], published_at=None, source_updated_at=e.get("last_seen_at"),
                fetched_at=fetched_at, authority=AUTHORITY, advice_text=POSTED_TEXT, source_url=MAP_URL, raw=raw))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved getBeaches answer instead of the service")
    ap.add_argument("--state", help="state file (default data/build/ca-sfpuc-beaches-state.json)")
    ap.add_argument("--out", help="events file (default data/build/events/ca-sfpuc-beach-map.json)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state_path = Path(args.state) if args.state else STATE_FILE
    if args.file and not args.state:
        state_path = Path(args.file).with_suffix(".state.json")    # a replay never touches the archive
    out = Path(args.out) if args.out else None
    state = read_json(state_path, {}) or {}
    try:
        if args.file:
            text = Path(args.file).read_text()
        else:
            r = requests.get(SERVICE, headers=HEADERS, timeout=(20, 60))
            r.raise_for_status()
            text = r.text
        stations = parse(text)
        last = state.get("last_count") or 0
        if not stations or len(stations) * 2 < last:
            raise RuntimeError(f"{len(stations)} stations answered (last good answer {last}): read as an outage")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    changes = step(state, stations, fetched_at)
    state.update(last_count=len(stations), polled_at=fetched_at)
    write_json(state_path, state)
    recs = records(state, fetched_at)
    meta = {"stations": len(stations), "flagged_now": sum(1 for s in stations if flagged(s)),
            "posted_now": sum(1 for s in stations if posted(s)), **changes, "service": SERVICE, "page": MAP_URL,
            "credit": CREDIT, "registry_ids": [SOURCE_ID], "time_basis": "our poll times (the service gives none)",
            "snapshot": True}
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta, path=out)
    print(f"{SOURCE_ID}: {len(stations)} stations, {meta['flagged_now']} with the CSO sign, {meta['posted_now']} "
          f"posted; {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
