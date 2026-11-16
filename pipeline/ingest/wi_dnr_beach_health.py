"""Wisconsin DNR's beach advisories and closures (Wisconsin Beach Health) -> data/build/events/wi-dnr-beach-health.json

Source (registry wi-dnr-beach-health)
  - The beach map layer, https://dnrmaps.wi.gov/arcgis2/rest/services/OGW_Beach_Monitoring/BEACH_MONITORING_LOCATIONS/
    MapServer/1 ("Beach Monitoring Locations", WI DNR Office of Great Waters; maxRecordCount 2000). It carries, per
    beach, the same Status, Reason and Date of Advisory that the Beach Health report table
    (https://apps.dnr.wi.gov/beachhealth/: Beach Name | Status | Reason | Date of Advisory | Nearest Town) prints, and
    the beach's point: BEACH_ACTION is the table's Status ("Advisory", "Closed", "End"), STATUS its Reason ("E. coli",
    "Algae", "Closed for season"), ISSUED its Date of Advisory, as text ("17-SEP-26 - " while in effect,
    "08-SEP-26 - 08-SEP-26" once ended). MAP_STATUS is the map symbol (Open, Advisory, Closed, "Other Status" drawn as
    Status Unknown, Closed for season, No Data Available); it follows the age of the last sample, not the advisory: on
    2026-11-16 every one of the 441 beaches was "No Data Available", the Algae closure and the Algae advisory included.
    SAMPLEDATE is the last sample's time.
  - Read by the GitHub runner on 2026-11-16 (runs 43788047052 at 01:45Z and 43788371768 at 01:48Z; this machine cannot
    open a connection to dnrmaps.wi.gov): 441 beaches, returnCountOnly 441; 439 "End" / "Closed for season", one
    "Advisory" / "Algae" (Gile Flowage Beach, ISSUED "17-SEP-26 - ") and one "Closed" / "Algae" (Lake Kegonsa State
    Park Beach, "11-SEP-26 - "). The report table listed the same two, with the same dates, among 453 beaches: 14
    table beaches have no point on the layer (all "End" / "Closed for season" that day), and the table adds the
    nearest town. The service's other layer, OGW_Beach_Monitoring_Locations_Ext/MapServer/0, held 366 beaches and not
    Gile Flowage's advisory: it is not read.

Records (rules only; the layer is read as a sequence of polls)
  - One record per beach whose BEACH_ACTION is "Advisory" or "Closed" (or, should the two ever disagree, whose
    MAP_STATUS is "Advisory" or "Closed": we show the stricter reading), as the Department's own advisory: red is the
    Department's window, shown while the Department lists it. The type: a Reason naming algae (blue-green, cyano,
    bloom) is a bloom (hab_advisory, the closure kept in raw.beach_action); otherwise "Closed" is beach_closure and
    "Advisory" beach_advisory. Any other action value is kept with our caution only (status unknown, raw.
    _agency_label_only, the label quoted), never dropped and never grey.
  - Not advisories, and never shown as clean or safe: "End" (the advisory has ended), "Open", a Reason or map symbol of
    "Closed for season" (the season's end, not a water finding), "Status Unknown" and "No Data Available" (no recent
    sample). These make no record; the beach is grey ("no report"). A blank BEACH_ACTION says nothing: it neither
    opens nor ends a record.
  - started_at: the Date of Advisory where ISSUED gives it unambiguously (DD-MON-YY, the Department's own form, a real
    date not after the read day: time_precision day, in Central time); otherwise the first read that listed the
    advisory (time_precision poll, raw.issued_text keeps the Department's text). No end is invented: an end date in
    ISSUED while the action still says Advisory or Closed is kept as text (raw.issued_end_text) and the record stays in
    effect.
  - The point is the layer's, rounded to three decimals (raw._point_extent_only): one marker; the lake or river is
    never coloured whole for one beach, and the water is the placement code's by its ordinary point rules
    (waterbody_text null). A beach without a usable point is listed, not mapped.
  - A complete healthy read that no longer shows the advisory (another action, another reason category, another
    Date of Advisory, or the beach no longer on the layer) ends it at that read (advisory_lifted, raw.
    ended_at_precision poll; the Department's own end date, where ISSUED then gives one, is kept as raw.
    source_end_text). A beach listed again later is a new record. Each read that lists it confirms it
    (raw._last_seen_in_source; raw.listed_periods after an unread gap of more than 14 days).
  - A read is complete only when the layer answers with a feature list, no exceededTransferLimit, every field asked
    for on every beach, a unique integer BEACH_SEQ_NO, at least MIN_BEACHES beaches, no drop below 80 per cent of the
    last complete read's count, and a returnCountOnly count equal to the beaches returned. Any other read is ok false:
    it lifts, greys and drops nothing and keeps every record and the state (common.write_events), and the run exits 1.
  - Keys: "<BEACH_SEQ_NO>-<advisory|closure|label>-<issue date>" or, with no usable date, "...-p<first read>".

Privacy: only the eight fields below are requested (no sampler, station or contact field exists on the layer; the
STATIONNAME, ECOLIPRONAME, ECOLIVALUE and WATERTEMP fields are not requested); the beach name is scrubbed before
anything is saved; data/raw keeps only the fields read, points rounded.
Cadence: hourly with the refresh once Wisconsin is live (daily before). Run from pipeline/:
python -m ingest.wi_dnr_beach_health [--file saved.json] [--at ISO]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest.de_dnrec_derns import scrub
from ingest.de_sc_periods import extend as extend_periods

SOURCE_ID = "wi-dnr-beach-health"
FIELDS = ("OBJECTID", "BEACH_SEQ_NO", "OGW_BEACH_NAME_TEXT", "STATUS", "BEACH_ACTION", "MAP_STATUS", "ISSUED",
          "SAMPLEDATE")
LAYER_URL = ("https://dnrmaps.wi.gov/arcgis2/rest/services/OGW_Beach_Monitoring/BEACH_MONITORING_LOCATIONS/"
             "MapServer/1")
QUERY = LAYER_URL + "/query?where=1%3D1&outFields=" + ",".join(FIELDS) + "&returnGeometry=true&outSR=4326&f=json"
COUNT = LAYER_URL + "/query?where=1%3D1&returnCountOnly=true&f=json"
REPORT_URL = "https://apps.dnr.wi.gov/beachhealth/"
AUTHORITY = "Wisconsin Department of Natural Resources, Wisconsin Beach Health"
TZ = ZoneInfo("America/Chicago")
STATE_PATH = BUILD_DIR / "wi-dnr-beach-health-state.json"
SAFE_FORMAT = "dww-wi-dnr-beach-health-safe/1"
TIMEOUT = (60, 300)
BOUNDS = (-93.0, 42.4, -86.2, 47.4)          # Wisconsin with its Great Lakes shore; a point outside is not used
MIN_BEACHES = 200                             # 441 on 2026-11-16; far fewer is a partial answer
MIN_SHARE_OF_LAST = 0.8

ADVISORY = re.compile(r"^\s*advisory\s*$", re.I)
CLOSED = re.compile(r"^\s*clos(?:ed|ure)\s*$", re.I)
NOT_IN_EFFECT = re.compile(r"^\s*(?:end|ended|open|lifted)\s*$", re.I)
SEASON = re.compile(r"closed\s+for\s+(?:the\s+)?season", re.I)
BLOOM = re.compile(r"alga|blue[\s-]*green|cyano|bloom", re.I)
ISSUED_RE = re.compile(r"^\s*(\d{2})-([A-Za-z]{3})-(\d{2})\s*-\s*(?:(\d{2}-[A-Za-z]{3}-\d{2}))?\s*$")
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                      "DEC"), 1)}


def _pt(geom) -> tuple[float | None, float | None]:
    try:
        x, y = float(geom["x"]), float(geom["y"])
    except (TypeError, KeyError, ValueError):
        return None, None
    if math.isnan(x) or math.isnan(y):
        return None, None
    lat, lon = round(y, 3), round(x, 3)
    if BOUNDS[1] <= lat <= BOUNDS[3] and BOUNDS[0] <= lon <= BOUNDS[2]:
        return lat, lon
    return None, None


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def local_day(at: str) -> date:
    return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(TZ).date()


def parse_issued(text, at: str) -> tuple[str | None, str | None]:
    """(the Date of Advisory as YYYY-MM-DD, the end text) from ISSUED. Only the Department's own form, DD-MON-YY,
    a real date not after the read's local day, is read as a date; anything else gives (None, end text or None)."""
    m = ISSUED_RE.match(text or "")
    if not m:
        return None, None
    end = m.group(4)
    mon = MONTHS.get(m.group(2).upper())
    if not mon:
        return None, end
    try:
        d = date(2000 + int(m.group(3)), mon, int(m.group(1)))
    except ValueError:
        return None, end
    if d > local_day(at):
        return None, end
    return d.isoformat(), end


def issued_start_text(text) -> str:
    return re.split(r"\s+-\s*|\s*-\s+", _s(text), maxsplit=1)[0].upper() if _s(text) else ""


def _epoch(ms) -> str | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).astimezone(TZ).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------- the read

def check_read(js, count, last_count: int | None = None) -> list[dict]:
    """The layer's features, or ValueError for anything but a complete answer (see the module text)."""
    if not isinstance(js, dict) or js.get("error") or not isinstance(js.get("features"), list):
        raise ValueError("the layer returned an error or no feature list")
    if js.get("exceededTransferLimit"):
        raise ValueError("the layer response was cut off (exceededTransferLimit)")
    feats = js["features"]
    seen = set()
    for f in feats:
        a = (f or {}).get("attributes")
        if not isinstance(a, dict) or any(k not in a for k in FIELDS):
            raise ValueError(f"a beach lacks the fields {FIELDS}")
        seq = a.get("BEACH_SEQ_NO")
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise ValueError("a beach has no integer BEACH_SEQ_NO")
        if seq in seen:
            raise ValueError(f"beach {seq} is listed twice")
        seen.add(seq)
        for k in ("BEACH_ACTION", "STATUS", "MAP_STATUS", "ISSUED", "OGW_BEACH_NAME_TEXT"):
            if a.get(k) is not None and not isinstance(a[k], str):
                raise ValueError(f"beach {seq}: {k} is not text")
    if len(feats) < MIN_BEACHES:
        raise ValueError(f"the layer returned {len(feats)} beaches, fewer than {MIN_BEACHES}")
    if not isinstance(count, dict) or not isinstance(count.get("count"), int) or count["count"] != len(feats):
        raise ValueError(f"the layer counts {(count or {}).get('count') if isinstance(count, dict) else None} beaches "
                         f"and returned {len(feats)}")
    if last_count and len(feats) < MIN_SHARE_OF_LAST * last_count:
        raise ValueError(f"the layer returned {len(feats)} beaches, against {last_count} at the last complete read")
    return feats


def safe_features(features: list[dict]) -> list[dict]:
    """The fields read, the beach name scrubbed, the point rounded to three decimals, before anything is saved."""
    out = []
    for f in features:
        a = f.get("attributes") or {}
        lat, lon = _pt(f.get("geometry"))
        attrs = {k: (scrub(a[k]) if k == "OGW_BEACH_NAME_TEXT" and isinstance(a.get(k), str) else a.get(k))
                 for k in FIELDS if k in a}
        out.append({"attributes": attrs, "geometry": {"x": lon, "y": lat} if lat is not None else None})
    return out


# ---------------------------------------------------------------- records

def classify(a: dict) -> dict | None:
    """What the Department's fields say about one beach: None for no advisory in effect, {"blank": True} for a blank
    action (says nothing), else the advisory's kind, category and labels."""
    action, reason, sym = _s(a.get("BEACH_ACTION")), _s(a.get("STATUS")), _s(a.get("MAP_STATUS"))
    if SEASON.search(reason) and not ADVISORY.match(action):
        return None                                    # the season's end: not an advisory, never a finding
    kind, basis = None, "BEACH_ACTION"
    if ADVISORY.match(action):
        kind = "advisory"
    elif CLOSED.match(action):
        kind = "closure"
    elif action and not NOT_IN_EFFECT.match(action):
        kind = "label"
    if kind is None and (ADVISORY.match(sym) or CLOSED.match(sym)):
        kind, basis = ("advisory" if ADVISORY.match(sym) else "closure"), "MAP_STATUS"
    if kind is None:
        return {"blank": True} if not action else None
    category = "bloom" if BLOOM.search(reason) else "bacteria_or_other"
    return {"kind": kind, "category": category, "action": action or None, "reason": reason or None,
            "map_status": sym or None, "basis": basis}


def records(features: list[dict], prev: dict, now: str) -> tuple[list[dict], dict, dict]:
    """Records from a complete read (check_read) of safe features, with the state carried between reads."""
    state = {k: dict(v) for k, v in (prev.get("beaches") or {}).items()}
    counts = {"beaches": len(features), "by_action": {}, "by_reason": {}, "by_map_status": {}, "in_effect": 0,
              "without_point": 0}
    current, blank = {}, set()
    for f in features:
        a = f.get("attributes") or {}
        for key, fld in (("by_action", "BEACH_ACTION"), ("by_reason", "STATUS"), ("by_map_status", "MAP_STATUS")):
            v = _s(a.get(fld)) or "(blank)"
            counts[key][v] = counts[key].get(v, 0) + 1
        seq = a["BEACH_SEQ_NO"]
        c = classify(a)
        if c is None:
            continue
        if c.get("blank"):
            blank.add(seq)
            continue
        issued, end_text = parse_issued(a.get("ISSUED"), now)
        lat, lon = _pt(f.get("geometry"))
        counts["in_effect"] += 1
        counts["without_point"] += lat is None
        current[seq] = {**c, "name": _s(a.get("OGW_BEACH_NAME_TEXT")) or None, "issued": issued,
                        "issued_text": _s(a.get("ISSUED")) or None, "issued_start": issued_start_text(a.get("ISSUED")),
                        "issued_end_text": end_text, "lat": lat, "lon": lon, "sample_at": _epoch(a.get("SAMPLEDATE"))}
    listed = {(f.get("attributes") or {}).get("BEACH_SEQ_NO"): f for f in features}

    def same(v, o) -> bool:
        return (v["kind"], v["category"], v.get("issued_start") or "") == (o["kind"], o["category"],
                                                                            o.get("issued_start") or "")
    matched = set()
    for seq, o in current.items():
        key = next((k for k, v in state.items() if v["seq"] == seq and not v.get("ended_at") and same(v, o)), None)
        if key is None:
            stamp = o["issued"] or "p" + re.sub(r"[^0-9T]", "", now)[:13]
            key = base = f"{seq}-{o['kind']}-{stamp}"
            n = 2
            while key in state:                        # a return with the same date: its own record
                key, n = f"{base}-{n}", n + 1
            state[key] = {"seq": seq, "first_seen_at": now, "last_seen_at": now,
                          "started_at": o["issued"] or now, "precision": "day" if o["issued"] else "poll",
                          **{k: o[k] for k in ("kind", "category", "action", "reason", "map_status", "basis", "name",
                                               "issued", "issued_text", "issued_start", "issued_end_text", "lat",
                                               "lon", "sample_at")}}
        else:
            v = state[key]
            v["listed_periods"] = extend_periods(v.get("listed_periods"), now, _period_origin(v), v.get("last_seen_at"))
            v["last_seen_at"] = now
            for k in ("action", "reason", "map_status", "basis", "issued_text", "issued_end_text", "sample_at"):
                v[k] = o[k]
            for k in ("name", "lat", "lon"):
                if o[k] is not None and o[k] != v.get(k):
                    if v.get(k) is not None:
                        v.setdefault("revisions", []).append({"seen_at": now, "field": k, "was": v.get(k),
                                                              "now": o[k]})
                    v[k] = o[k]
            v.pop("missing_since", None)
        matched.add(key)
    for key, v in state.items():
        if v.get("ended_at") or key in matched:
            continue
        if v["seq"] in blank:
            v["missing_since"] = v.get("missing_since") or now    # a blank action: not a lift
            continue
        v["ended_at"] = now                            # a complete read that no longer shows it
        v.pop("missing_since", None)
        f = listed.get(v["seq"])
        if f is not None:
            a = f.get("attributes") or {}
            v["end_seen"] = {"action": _s(a.get("BEACH_ACTION")) or None, "reason": _s(a.get("STATUS")) or None,
                             "issued_text": _s(a.get("ISSUED")) or None}
        else:
            v["end_seen"] = {"absent": True}
    recs = [_record(k, v, now) for k, v in sorted(state.items())]
    return recs, state, counts


def _period_origin(v: dict) -> str:
    """The first listing period starts at the Department's date (local midnight) where it gives one, else the first
    read: the Department's own window is confirmed by its date, the time before our first read is not ours."""
    if v.get("precision") == "day":
        return datetime.fromisoformat(v["started_at"]).replace(tzinfo=TZ).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    return v["started_at"]


def _record(key: str, v: dict, now: str) -> dict:
    bloom, kind = v["category"] == "bloom", v["kind"]
    etype = "hab_advisory" if bloom else ("beach_closure" if kind == "closure" else "beach_advisory")
    has_pt = v.get("lat") is not None
    raw = {"state": "WI", "time_zone": "America/Chicago", "beach_seq_no": v["seq"], "beach_name": v.get("name"),
           "beach_action": v.get("action"), "reason": v.get("reason"), "map_status": v.get("map_status"),
           "advisory_kind": kind, "read_from": v.get("basis"), "issued_text": v.get("issued_text"),
           "last_sample_at": v.get("sample_at"), "first_seen_at": v.get("first_seen_at"),
           "_last_seen_in_source": v.get("last_seen_at"), "_point_extent_only": True,
           "extent_basis": ("the Department gives one point for the beach: shown at that point; the lake or river is "
                            "not coloured whole"),
           "point_basis": ("the beach's point on the Department's beach map layer, rounded to three decimals" if has_pt
                           else "the Department's layer gives no usable point for this beach: listed, not mapped"),
           "start_basis": ("the Department's Date of Advisory (ISSUED), a date with no time of day" if v.get("issued")
                           else "the first read that listed the advisory; the Department's date could not be read "
                                "unambiguously, and its text is kept (issued_text)")}
    if bloom:
        raw["bloom_action"] = "closure" if kind == "closure" else "advisory"
    if v.get("issued_end_text"):
        raw["issued_end_text"] = v["issued_end_text"]
        raw["issued_end_basis"] = ("the Department's text gives an end date while its action still lists the "
                                   "advisory; we keep showing it while it is listed")
    p = v.get("listed_periods") or []
    if len(p) > 1:
        raw.update(listed_periods=p, periods_basis=("the reads that listed this advisory, in periods: a read more "
                                                    "than 14 days after the previous one opens a new period, and the "
                                                    "unread time between is not confirmed"))
    if v.get("missing_since"):
        raw["_missing_from_source_since"] = v["missing_since"]
    if v.get("revisions"):
        raw["revisions"] = v["revisions"]
    if v.get("ended_at"):
        es = v.get("end_seen") or {}
        raw.update(ended_at_precision="poll",
                   end_basis=("the first complete read of the Department's layer that no longer listed the beach"
                              if es.get("absent") else
                              "the first complete read of the Department's layer that no longer showed this advisory "
                              f"(it then gave {es.get('action') or 'no action'}, {es.get('reason') or 'no reason'})"))
        _, end_text = parse_issued(es.get("issued_text"), v["ended_at"])
        if end_text:
            raw["source_end_text"] = end_text
    if kind == "label":
        raw.update(_agency_label_only=True, _agency_label=v.get("action"),
                   _label_basis="a BEACH_ACTION value we do not know; kept with our caution")
        status = "unknown"
    else:
        status = "advisory_lifted" if v.get("ended_at") else "advisory_active"
    word = {"advisory": "an advisory", "closure": "a closure"}.get(kind, f"\"{v.get('action')}\"")
    advice = (f"The Wisconsin DNR's Beach Health system lists {word} at this beach"
              + (f" (reason: {v['reason']})" if v.get("reason") else "")
              + (f", dated {v['issued']}" if v.get("issued") else "") + ".")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status,
        outfall_name=v.get("name") or f"Beach {v['seq']}", waterbody_text=None,
        lat=v.get("lat"), lon=v.get("lon"), coord_source="beach" if has_pt else None,
        coord_precision_m=100 if has_pt else None,
        started_at=v["started_at"], ended_at=v.get("ended_at"), time_precision=v["precision"], fetched_at=now,
        reported_at=None, published_at=None, source_updated_at=None,
        authority=AUTHORITY, advice_text=advice,
        advice_window_basis="shown while the Department's layer lists the advisory",
        source_url=REPORT_URL, raw=raw)


META = {"credit": "Wisconsin Department of Natural Resources, Wisconsin Beach Health (beach map layer)",
        "license": "No licence statement on the service",
        "caveat": ("The Department's current advisories and closures, with its reason and date; blooms are shown as "
                   "blooms. Out of season most beaches read \"Closed for season\": that is the season's end, not a "
                   "finding about the water."),
        "time_basis": ("The Department's Date of Advisory (a date, no time of day); an end is the first read that no "
                       "longer lists the advisory.")}


def run(args) -> int:
    now = args.at or now_iso()
    prev = {} if args.file else (read_json(STATE_PATH, {}) or {})
    out = args.out
    if args.file:
        saved = json.loads(open(args.file).read())
        feats = saved["beaches"]
    else:
        try:
            r = requests.get(QUERY, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            c = requests.get(COUNT, headers=HEADERS, timeout=TIMEOUT)
            c.raise_for_status()
            feats = safe_features(check_read(r.json(), c.json(), prev.get("last_count")))
        except Exception as e:                         # any failure: nothing lifted, greyed or dropped
            write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}"[:300], meta=META, path=out)
            print(f"{SOURCE_ID}: read failed: {type(e).__name__}", file=sys.stderr)
            return 1
        save_raw(SOURCE_ID, json.dumps({"format": SAFE_FORMAT, "beaches": feats}), "json")
    try:
        recs, beaches, n = records(feats, prev, now)
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}"[:300], meta=META, path=out)
        return 1
    write_events(SOURCE_ID, recs, meta={**META, "counts": n}, path=out)
    if not args.file:
        write_json(STATE_PATH, {**prev, "beaches": beaches, "last_count": n["beaches"]})
    print(f"{SOURCE_ID}: {len(recs)} records; {n['in_effect']} in effect of {n['beaches']} beaches")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="saved {beaches} JSON of safe features (no network)")
    ap.add_argument("--at")
    ap.add_argument("--out")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
