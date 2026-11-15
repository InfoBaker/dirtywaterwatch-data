"""Delaware DNREC's recreational water advisories: the advisory history on the state's open-data portal and the
sampling stations' current status on FirstMap -> data/build/events/de-dnrec-recreational-water.json

Sources (registry de-dnrec-recreational-water)
  - Recreational Water Advisories, data.delaware.gov dataset ever-58ni (Socrata, Public Domain): one row per notice
    DNREC issued since July 2001 (474 rows on 2026-11-14), fields advisoryid, advstartdate, advenddate (dates, no
    time of day), advdesc, advcomment (DNREC's text), advreason (Bacteria, Rainfall, Algae Bloom, Chemical/Oil Spill,
    Enterococcus Monitor, End of Sampling Season, Other), advtype and unitname (the beach or station).
  - Recreational Water Sampling Location, FirstMap Environmental/DE_DNREC_Monitoring_Network FeatureServer layer 2
    (the layer behind https://recwaters.dnrec.delaware.gov/): 47 stations with UnitName, UnitID, Latitude, Longitude
    and CurrentAdvisory, whose codes the map service's own legend names (CODES: 0 Current Advisory, 1 Outside
    Advisory Area, 2 Resampling Enterococcus Spike, 3 Winter - Not Currently Sampling, 4 No Current Advisory).
  DNREC samples ocean, bay and inland beaches weekly from Memorial Day to Labor Day and posts an advisory when a
  sample, the 30-day geometric mean or two consecutive results exceed the standard; it also e-mails subscribers.

Records (rules only)
  - From the history, by advtype (TYPES): "Recreational Water Quality Advisory" a beach advisory (an algae-bloom
    reason a bloom advisory, hab_advisory), "Recreational Water Closure" a beach closure: DNREC's own advisory with
    its own start and end dates, quoted as DNREC's (red while it stands). Both dates are dates in Eastern time
    (time_precision day, raw.ended_at_precision day); an advisory with no end date and a start more than 30 days old
    is listed with "end not given" (status unknown), not as standing.
  - "Recreational Water Quality Resampling Underway" (a sample above the enterococcus standard that DNREC resamples
    instead of posting an advisory): a beach advisory record that is DNREC's label only (raw._agency_label_only, the
    label quoted): the site's caution for 72 hours from its start, or to DNREC's end date for the resampling when
    later (rules.json unresolved.sample_caution), never shown as DNREC's advisory.
  - Not records (meta.not_read): the lifts ("Recreational Water Quality Advisory Lift": the advisory row already
    carries its end), "Additional Information", "Sampling to Resume in Spring", the fish-consumption notices (not
    water contact), and the portal's system-test rows (TEST_ROW: "testing the email", "Developer testing").
  - Current status: a station whose CurrentAdvisory is 0 (Current Advisory) or 2 (Resampling) with no history row
    in effect for its beach is a record of its own, started at the first poll that showed it (time_precision poll:
    DNREC's issue time is not on the layer) and ended at the first poll that no longer shows it
    (raw.ended_at_precision poll); 1, 3 and 4 are no record: grey, "no report", never clean.
  - Place: the station's own point (the layer's Latitude and Longitude, rounded to three decimals: a public beach),
    joined by the beach's name (raw.unit_id); a beach of the history with no station keeps its name only
    (waterbody_text, placed by name). coord_source "station".
  - Keys: the history's advisoryid ("adv-731"); the poll records "station-<UnitID>-<first poll date>".

Privacy: the fields hold no person; DNREC's text goes through common.scrub_text. data/raw keeps the safe rows only.
Cadence: hourly with the refresh (the history is updated as DNREC posts; the map in season). Run from pipeline/:
  python -m ingest.de_dnrec_recwater [--file saved.json] [--at 2026-11-14T18:00:00Z]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, scrub_text, write_events, write_json)

SOURCE_ID = "de-dnrec-recreational-water"
SOCRATA = ("https://data.delaware.gov/resource/ever-58ni.json?$select=advisoryid,advstartdate,advenddate,advdesc,"
           "advcomment,advreason,advtype,unitname&$order=advisoryid&$limit=50000")
STATIONS = ("https://enterprise.firstmap.delaware.gov/arcgis/rest/services/Environmental/DE_DNREC_Monitoring_Network/"
            "FeatureServer/2/query?where=1%3D1&outFields=OBJECTID,UnitName,UnitID,CurrentAdvisory,ShowInMapID,BeachID,"
            "Latitude,Longitude&returnGeometry=false&f=json")
DATASET_URL = "https://data.delaware.gov/Energy-and-Environment/Recreational-Water-Advisories/ever-58ni"
MAP_URL = "https://recwaters.dnrec.delaware.gov/"
BEACH_URL = "https://recwaters.dnrec.delaware.gov/BeachInfo.aspx?UnitID={}"
TZ = ZoneInfo("America/New_York")
STATE_PATH = BUILD_DIR / "de-dnrec-recreational-water-state.json"
SAFE_FORMAT = "dww-de-recwater-safe/1"
AUTHORITY = "Delaware DNREC, Recreational Water Program"
TIMEOUT = (60, 300)
OPEN_NO_END_DAYS = 30

TYPES = {
    "recreational water quality advisory": ("beach_advisory", "advisory"),
    "recreational water closure": ("beach_closure", "advisory"),
    "recreational water quality resampling underway": ("beach_advisory", "label"),
}
NOT_READ = {"recreational water quality advisory lift": "lift (the advisory row carries its end)",
            "additional information": "additional information, not an advisory",
            "sampling to resume in spring": "end of the sampling season",
            "fish consumption advisory": "fish consumption, not water contact",
            "fish consumption closure": "fish consumption, not water contact"}
TEST_ROW = re.compile(r"\btest(?:ing|ed)?\b.*\b(?:email|change|developer)|developer\s+test|web\.config|BEING TESTED",
                      re.I)
LIFT_TEXT = re.compile(r"^\s*the\s+(?:recreational\s+water\s+)?advisory\s+has\s+been\s+lifted", re.I)
CODES = {0: "Monitoring – Current Advisory", 1: "Monitoring – Outside Advisory Area",
         2: "Monitoring – Resampling Enterococcus Spike", 3: "Winter – Not Currently Sampling",
         4: "Monitoring – No Current Advisory"}
POLL_CODES = {0: ("beach_advisory", "advisory"), 2: ("beach_advisory", "label")}
# beaches of the history that no longer have a station on the layer: an inland beach is placed on its lake by name
# (a small lake, drawn whole); a coastal beach keeps its name only and is listed, never coloured as the whole bay or
# ocean (raw.placement_note)
NO_STATION_WATERS = {"silverlakedoverbeach": ("Silver Lake", "Kent"),
                     "lumspondbeachlumspondstatepark": ("Lums Pond", "New Castle")}
COASTAL_NO_STATION = ("a beach DNREC no longer samples, with no station point on the map: listed by its name, not "
                      "drawn on the bay or the ocean")
# the water each beach lies on, by the beach's name (DNREC names the bay stations after their bay, and the ocean and
# Delaware Bay beaches by their town or park); a name no rule settles keeps the beach's name only
BEACH_WATERS = [
    (re.compile(r"^(Delaware Bay|Rehoboth Bay|Indian River Bay|Little Assawoman Bay) \d+$"), None),
    (re.compile(r"Bayside|Dewey Beach Bayside", re.I), "Rehoboth Bay"),
    (re.compile(r"^(Rehoboth Beach|Dewey Beach Oceanside|Bethany Beach|South Bethany Beach|Fenwick Island|"
                r"Cape Henlopen Main Beach|Herring Point Beach|Deauville Beach|Ocean Beach Near Gordons Pond|"
                r"Tower Road Beach - Oceanside|North Indian River Inlet Beach|South Indian River Inlet Beach|"
                r"3 R's Road Beach|Key Box Road Beach|Conquest Road Beach)", re.I), "Atlantic Ocean"),
    (re.compile(r"^(Lewes Beach|Slaughter Beach|Broadkill Beach|Bowers Beach|Prime Hook Beach|Cape Shores Beach|"
                r"Augustine Beach|Woodland Beach|Cape Henlopen Fishing Pier)", re.I), "Delaware Bay"),
    (re.compile(r"Little Assawoman|Assawoman Recreation Area", re.I), "Little Assawoman Bay"),
    (re.compile(r"^Lake Como", re.I), "Lake Como"),
    (re.compile(r"^(Holt's Landing|James Farm)", re.I), "Indian River Bay"),
]


def beach_water(unit: str | None) -> str | None:
    for rx, water in BEACH_WATERS:
        m = rx.search(unit or "")
        if m:
            return water or m.group(1)
    return None


LABEL_BASIS = ("DNREC resamples after a result above the enterococcus standard and has not posted an advisory: its "
               "label is quoted and the site shows its own caution, never DNREC's advisory")


def norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def day(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19]).date().isoformat()
    except ValueError:
        return None


def end_of_day(d: str) -> str:
    """The end of an Eastern-time calendar day as an instant (the next day's local midnight), so a notice dated to the
    day closes at that day's end, never its start, across a clock change too."""
    nxt = date.fromisoformat(d[:10]) + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ).isoformat()


def station_index(stations: list[dict]) -> dict[str, dict]:
    return {norm(s.get("UnitName")): s for s in stations if s.get("UnitName")}


def point(st: dict | None) -> tuple[float | None, float | None]:
    if not st:
        return None, None
    try:
        return round(float(st["Latitude"]), 3), round(float(st["Longitude"]), 3)
    except (KeyError, TypeError, ValueError):
        return None, None


def history_records(rows: list[dict], stations: dict[str, dict], today: date, fetched_at: str) -> tuple[list[dict], dict]:
    recs, n = [], {"rows": len(rows), "test_rows": 0, "kept": 0}
    for r in rows:
        typ = (r.get("advtype") or "").strip().lower()
        comment = scrub_text(r.get("advcomment") or "") or None
        if TEST_ROW.search(comment or "") or TEST_ROW.search(r.get("advdesc") or ""):
            n["test_rows"] += 1
            continue
        if typ in NOT_READ or (typ in TYPES and LIFT_TEXT.search(comment or "")):
            key = NOT_READ.get(typ, "lift (the text says the advisory was lifted)")
            n[key] = n.get(key, 0) + 1
            continue
        if typ not in TYPES:
            n["unknown type"] = n.get("unknown type", 0) + 1
        etype, kind = TYPES.get(typ, ("beach_advisory", "label"))
        reason = (r.get("advreason") or "").strip() or None
        if kind == "advisory" and reason and re.search(r"algae|bloom|cyano", reason, re.I):
            etype = "hab_advisory"
        start, end = day(r.get("advstartdate")), day(r.get("advenddate"))
        st = stations.get(norm(r.get("unitname")))
        lat, lon = point(st)
        raw = {"state": "DE", "time_zone": "America/New_York", "advisory_type": r.get("advtype"),
               "advisory_reason": reason, "advisory_description": scrub_text(r.get("advdesc") or "") or None,
               "unit_name": r.get("unitname"), "unit_id": (st or {}).get("UnitID"),
               "start_basis": "DNREC's start date for the notice (a date, no time of day)"}
        if end:
            raw["ended_at_precision"] = "day"
            raw["end_basis"] = "DNREC's end date for the notice (a date, no time of day)"
        if kind == "label":
            raw.update(_agency_label_only=True, _agency_label=r.get("advtype"), _label_basis=LABEL_BASIS)
            if end:
                raw.update(_caution_to_notice_end=True, _notice_closed_at=end_of_day(end))
            status = "unknown"
        elif end:
            status = "advisory_lifted" if date.fromisoformat(end) < today else "advisory_active"
        elif start and (today - date.fromisoformat(start)).days > OPEN_NO_END_DAYS:
            status = "unknown"
            raw["status_basis"] = f"no end date given and the start is more than {OPEN_NO_END_DAYS} days old"
        else:
            status = "advisory_active"
        water = beach_water(r.get("unitname")) or r.get("unitname")
        if water != r.get("unitname"):
            raw["water_basis"] = "the water the beach lies on, by the beach's name"
        if lat is not None:
            raw["point_basis"] = "DNREC's sampling station for this beach (FirstMap, Recreational Water Sampling Location)"
        elif norm(r.get("unitname")) in NO_STATION_WATERS:
            water, raw["county"] = NO_STATION_WATERS[norm(r.get("unitname"))]
            raw["placement_note"] = "an inland beach with no station point on the map: placed on its lake by name"
        else:
            raw["placement_note"] = COASTAL_NO_STATION
        recs.append(event(
            source_id=SOURCE_ID, source_record_id=f"adv-{r.get('advisoryid')}", event_type=etype, status=status,
            waterbody_text=water, outfall_name=r.get("unitname"), lat=lat, lon=lon,
            coord_source="station" if lat is not None else None, coord_precision_m=100 if lat is not None else None,
            started_at=start, ended_at=end, time_precision="day" if start else None,
            fetched_at=fetched_at, authority=AUTHORITY, advice_text=comment,
            source_url=BEACH_URL.format(st["UnitID"]) if st else DATASET_URL, raw=raw))
        n["kept"] += 1
    return recs, n


def poll_records(stations: list[dict], history: list[dict], prev: dict, fetched_at: str, today: date) -> tuple[list[dict], dict]:
    """The current-status snapshot: records opened and closed at polls (module docstring)."""
    # a history row in effect today, of the same kind as the map's status (an advisory, or DNREC's resampling label),
    # already carries it; a row aged out for want of an end (raw.status_basis) never does
    open_hist = {(norm(r["raw"].get("unit_name")), "label" if r["raw"].get("_agency_label_only") else "advisory")
                 for r in history
                 if r["status"] in ("advisory_active", "unknown") and not r["raw"].get("status_basis")
                 and r.get("ended_at") and r["ended_at"] >= today.isoformat()
                 and (r.get("started_at") or "") <= today.isoformat()}
    state = {k: dict(v) for k, v in (prev.get("polls") or {}).items()}
    showing, explicit = {}, {}
    for s in stations:
        code = s.get("CurrentAdvisory")
        if code in CODES:
            explicit[str(s.get("UnitID"))] = code            # a known status read for this station
        if code in POLL_CODES and (norm(s.get("UnitName")), POLL_CODES[code][1]) not in open_hist:
            showing[str(s.get("UnitID"))] = (s, code)
    for uid, (s, code) in showing.items():
        cur = next((v for v in state.values() if v["unit_id"] == uid and not v.get("ended_at") and v["code"] == code), None)
        if cur is None:
            key = f"station-{uid}-{re.sub(r'[^0-9T]', '', fetched_at)[:13]}"
            lat, lon = point(s)
            state[key] = {"unit_id": uid, "code": code, "name": s.get("UnitName"), "started_at": fetched_at,
                          "lat": lat, "lon": lon}
        else:
            cur["last_seen_at"] = fetched_at
    for key, v in state.items():
        if v.get("ended_at"):
            continue
        if v["unit_id"] in explicit and explicit[v["unit_id"]] != v["code"]:
            v["ended_at"] = fetched_at                       # the map now shows another status for the station
        elif v["unit_id"] not in explicit:
            v["missing_since"] = v.get("missing_since") or fetched_at     # absent or unreadable: not a lift
        else:
            v.pop("missing_since", None)
    recs = []
    for key, v in sorted(state.items()):
        etype, kind = POLL_CODES[v["code"]]
        lat, lon = point({"Latitude": v.get("lat"), "Longitude": v.get("lon")})
        raw = {"state": "DE", "time_zone": "America/New_York", "unit_id": v["unit_id"], "unit_name": v["name"],
               "current_advisory_code": v["code"], "current_advisory_label": CODES[v["code"]],
               "start_basis": "the first poll of DNREC's map that showed this status; DNREC's issue time is not on the map",
               "_last_seen_in_source": v.get("last_seen_at") or v["started_at"],
               "point_basis": "DNREC's sampling station for this beach (FirstMap, Recreational Water Sampling Location)"}
        if v.get("ended_at"):
            raw.update(ended_at_precision="poll", end_basis="the first poll of DNREC's map that showed another status")
        if v.get("missing_since"):
            raw["_missing_from_source_since"] = v["missing_since"]
        if kind == "label":
            raw.update(_agency_label_only=True, _agency_label=CODES[v["code"]], _label_basis=LABEL_BASIS,
                       _caution_to_notice_end=True, _notice_closed_at=v.get("ended_at") or raw["_last_seen_in_source"])
            status = "unknown"
        else:
            status = "advisory_lifted" if v.get("ended_at") else "advisory_active"
        recs.append(event(source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status,
                          waterbody_text=beach_water(v["name"]) or v["name"], outfall_name=v["name"], lat=lat, lon=lon, coord_source="station",
                          coord_precision_m=100, started_at=v["started_at"], ended_at=v.get("ended_at"),
                          time_precision="poll", fetched_at=fetched_at, authority=AUTHORITY,
                          source_url=BEACH_URL.format(v["unit_id"]), raw=raw))
    return recs, {"polls": state}


META = {"credit": "Delaware Department of Natural Resources and Environmental Control, Recreational Water Program "
                  "(data.delaware.gov Recreational Water Advisories; FirstMap)",
        "license": "Public Domain (data.delaware.gov); no statement on the FirstMap layer",
        "caveat": ("DNREC's own advisory and closure dates. A resampling notice is DNREC's label for a high result it "
                   "is checking, not an advisory. Out of season DNREC does not sample, so no advisory is not a finding."),
        "time_basis": "Dates in Eastern time with no time of day; the map's current status is dated by the poll that saw it."}


SAFE_ROW_FIELDS = ("advisoryid", "advstartdate", "advenddate", "advdesc", "advcomment", "advreason", "advtype", "unitname")
SAFE_STATION_FIELDS = ("OBJECTID", "UnitName", "UnitID", "CurrentAdvisory", "ShowInMapID", "BeachID")


def safe_rows(rows: list[dict]) -> list[dict]:
    """The history's rows cut to the fields read, DNREC's text scrubbed, before anything is saved."""
    out = []
    for r in rows:
        x = {k: r.get(k) for k in SAFE_ROW_FIELDS if r.get(k) is not None}
        for k in ("advdesc", "advcomment"):
            if x.get(k):
                x[k] = scrub_text(x[k])
        out.append(x)
    return out


def safe_stations(stations: list[dict]) -> list[dict]:
    """The stations cut to the fields read, points rounded to three decimals, before anything is saved."""
    out = []
    for s in stations:
        x = {k: s.get(k) for k in SAFE_STATION_FIELDS}
        lat, lon = point(s)
        x["Latitude"], x["Longitude"] = lat, lon
        out.append(x)
    return out


def carry_missing(hist: list[dict], prev_hist: dict, fetched_at: str) -> tuple[list[dict], int]:
    """A record of an earlier read whose row has left the dataset is kept as it was, marked missing since this read
    (never ended by its absence)."""
    have = {r["source_record_id"] for r in hist}
    carried = []
    for key, r in prev_hist.items():
        if key in have:
            continue
        r = json.loads(json.dumps(r))
        r["raw"]["_missing_from_source_since"] = r["raw"].get("_missing_from_source_since") or fetched_at
        carried.append(r)
    return hist + carried, len(carried)


def run(args) -> int:
    fetched_at = args.at or now_iso()
    today = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).astimezone(TZ).date()
    prev = read_json(STATE_PATH, {}) or {}
    if args.file:
        saved = json.loads(open(args.file).read())
        rows, stations = saved["advisories"], saved["stations"]
    else:
        try:
            r = requests.get(SOCRATA, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            rows = r.json()
            s = requests.get(STATIONS, headers=HEADERS, timeout=TIMEOUT)
            s.raise_for_status()
            js = s.json()
            if "features" not in js:
                raise RuntimeError(f"station layer: {str(js)[:200]}")
            stations = [f["attributes"] for f in js["features"]]
            if not rows or not stations:
                raise RuntimeError("an empty history or station list")
        except (requests.RequestException, ValueError, RuntimeError) as e:
            write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=META)
            print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
            return 1
    rows, stations = safe_rows(rows), safe_stations(stations)
    if not args.file:
        save_raw(SOURCE_ID, json.dumps({"format": SAFE_FORMAT, "advisories": rows, "stations": stations}), "json")
    hist, n = history_records(rows, station_index(stations), today, fetched_at)
    hist, n["carried_missing"] = carry_missing(hist, prev.get("history") or {}, fetched_at)
    polls, new_state = poll_records(stations, hist, prev, fetched_at, today)
    if not args.file:
        new_state["history"] = {r["source_record_id"]: r for r in hist}
        write_json(STATE_PATH, new_state)
    codes = {}
    for s in stations:
        codes[CODES.get(s.get("CurrentAdvisory"), str(s.get("CurrentAdvisory")))] = codes.get(
            CODES.get(s.get("CurrentAdvisory"), str(s.get("CurrentAdvisory"))), 0) + 1
    recs = hist + polls
    write_events(SOURCE_ID, recs, meta={**META, "counts": n, "station_status": codes}, path=args.out)
    print(f"{SOURCE_ID}: {len(recs)} records ({len(hist)} from the history, {len(polls)} from the map); {n}; {codes}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="saved {advisories, stations} JSON (no network)")
    ap.add_argument("--out")
    ap.add_argument("--at", help="the fetch time to use (tests)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
