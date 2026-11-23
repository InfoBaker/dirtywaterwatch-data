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
    SAMPLEDATE is the last sample's time. ECOLIVALUE is retained as the source's E. coli result text;
    units and laboratory sentinel meanings are not assumed.
  - Read by the GitHub runner on 2026-11-16 (runs 43788047052 at 01:45Z and 43788371768 at 01:48Z; this machine cannot
    open a connection to dnrmaps.wi.gov): 441 beaches, returnCountOnly 441; 439 "End" / "Closed for season", one
    "Advisory" / "Algae" (Gile Flowage Beach, ISSUED "17-SEP-26 - ") and one "Closed" / "Algae" (Lake Kegonsa State
    Park Beach, "11-SEP-26 - "). The report table listed the same two, with the same dates, among 453 beaches: 12
    table beaches have no point on the layer (all "End" / "Closed for season" that day), and the table adds the
    nearest town. The service's other layer, OGW_Beach_Monitoring_Locations_Ext/MapServer/0, held 366 beaches and not
    Gile Flowage's advisory: it is not read.
  - The report table (tblSearchResult) is read too, for the beaches the layer does not hold (by name; 12 on
    2026-11-16): an advisory or closure there is a record with no point (raw.nearest_town, raw.read_from
    "report_table"), listed for Wisconsin; its place on the map is not known and none is invented. A table that fails,
    changes its columns, has a row out of shape, fewer than MIN_TABLE_ROWS rows or under 80 per cent of the last
    complete table, keeps the table's held records, leaves the layer's alone, and fails health for that read only
    (common.write_events partial).

Records (rules only; the layer is read as a sequence of polls)
  - One record per beach whose BEACH_ACTION or MAP_STATUS is "Advisory" or "Closed", the stronger kept (closure over
    advisory), as the Department's own advisory: red is the Department's window, shown while the Department lists it.
    A recognised signal is resolved before an unfamiliar action is considered (raw.unrecognised_action keeps it).
    The type: a Reason naming algae only (blue-green, cyano, bloom) is a bloom (hab_advisory, the closure kept in
    raw.bloom_action); a Reason naming bacteria and algae is one beach advisory or closure with raw._also_categories
    ["bloom"], carried on its intervals and its one marker (build/status.py); a Reason naming neither is kept as
    raw.reason_categories ["unknown"]. An action value we do not know, with nothing recognised, is our caution only
    (status unknown, raw._agency_label_only: data/rules.json unresolved.sample_caution, to the later of 72 hours and
    the last read that listed it plus 72 hours, or its end), never the Department's red, never dropped or grey.
  - Not advisories, and never shown as clean or safe: "End" (the advisory has ended), "Open", a Reason or map symbol of
    "Closed for season" (the season's end, not a water finding). These make no record; the beach is grey ("no
    report"). The map symbols "Status Unknown" and "No Data Available" (no recent sample) open nothing and do not
    cancel an advisory or closure the Department lists in BEACH_ACTION: both of today's records carry "No Data
    Available". A blank BEACH_ACTION says nothing: it neither opens nor ends a record.
  - started_at: the Date of Advisory where ISSUED gives it unambiguously (DD-MON-YY, the Department's own form, a real
    date not after the read day: time_precision day, in Central time); otherwise the first read that listed the
    advisory (time_precision poll, raw.issued_text keeps the Department's text). No end is invented: an end date in
    ISSUED while either status still says Advisory or Closed is parsed into raw.source_ended_at, quoted with
    both statuses in advice_text, and kept apart from ended_at: the record stays in effect. A beach that returns with a Date of Advisory earlier than the end we saw of its last episode starts at the
    return (time_precision poll, the text kept): the days between are not coloured.
  - The point is the layer's, rounded to three decimals (raw._point_extent_only): one marker; the lake or river is
    never coloured whole for one beach, and the water is the placement code's by its ordinary point rules
    (waterbody_text null). A beach without a usable point is listed, not mapped.
  - A complete healthy read that no longer shows the advisory (another action, another reason category, another
    Date of Advisory, or the beach no longer on the layer) ends it at that read (advisory_lifted, raw.
    ended_at_precision poll), or at the second ISSUED date when it is valid and its first date matches this
    episode and no later episode intervenes. A disputed source date stays separate and keeps an unmatched advisory
    open. The original text and superseded end remain available. A beach listed again later is a new record. Each read that lists it confirms it
    (raw._last_seen_in_source; raw.listed_periods after an unread gap of more than 14 days).
  - A read is complete only when the layer answers with a feature list, no exceededTransferLimit, every field asked
    for on every beach and of its type (OBJECTID and BEACH_SEQ_NO integers, SAMPLEDATE a number or null, the texts
    text or null, the point numbers or "NaN"), a unique BEACH_SEQ_NO, at least MIN_BEACHES beaches, no drop below 80 per cent of the
    last complete read's count, and a returnCountOnly count equal to the beaches returned. Any other read is ok false:
    it lifts, greys and drops nothing and keeps every record and the state (common.write_events), and the run exits 1.
  - A connection that is not made (a connect timeout or a refused or dropped connection; the map server has not always
    accepted one from a runner) is tried up to CONNECT_TRIES times per request, CONNECT_PAUSE_S apart, with a 20 s
    connect timeout; an HTTP error (a 403 among them), a read timeout or a malformed answer is not retried. After the
    last try the read fails as above. Worst case per request: 3 x 20 s + 2 x 30 s = 120 s.
  - Keys: "<BEACH_SEQ_NO>-<advisory|closure|label>-<issue date>" or, with no usable date, "...-p<first read>".

Privacy: only the nine fields below are requested (no sampler, station or contact field exists on the layer; the
STATIONNAME, ECOLIPRONAME and WATERTEMP fields are not requested); every text field read, and every table
cell, is scrubbed before anything is saved, and again when a record is made from carried state; data/raw keeps only the fields read, points rounded.
Cadence: hourly with the refresh once Wisconsin is live (daily before). Run from pipeline/:
python -m ingest.wi_dnr_beach_health [--file saved.json] [--at ISO]
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from urllib3.exceptions import ReadTimeoutError

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from common import error_text
from ingest.de_dnrec_derns import scrub
from ingest.de_sc_periods import extend as extend_periods

SOURCE_ID = "wi-dnr-beach-health"
FIELDS = ("OBJECTID", "BEACH_SEQ_NO", "OGW_BEACH_NAME_TEXT", "STATUS", "BEACH_ACTION", "MAP_STATUS", "ISSUED",
          "SAMPLEDATE", "ECOLIVALUE")
REQUIRED_FIELDS = tuple(k for k in FIELDS if k != "ECOLIVALUE")  # older saved reads predate this field
LAYER_URL = ("https://dnrmaps.wi.gov/arcgis2/rest/services/OGW_Beach_Monitoring/BEACH_MONITORING_LOCATIONS/"
             "MapServer/1")
QUERY = LAYER_URL + "/query?where=1%3D1&outFields=" + ",".join(FIELDS) + "&returnGeometry=true&outSR=4326&f=json"
COUNT = LAYER_URL + "/query?where=1%3D1&returnCountOnly=true&f=json"
REPORT_URL = "https://apps.dnr.wi.gov/beachhealth/"
AUTHORITY = "Wisconsin Department of Natural Resources, Wisconsin Beach Health"
TZ = ZoneInfo("America/Chicago")
STATE_PATH = BUILD_DIR / "wi-dnr-beach-health-state.json"
SAFE_FORMAT = "dww-wi-dnr-beach-health-safe/1"
TIMEOUT = (20, 300)                           # connect, read; the runner's probes connect in under 0.4 s
CONNECT_TRIES = 3                             # per request; only a connection not made is tried again
CONNECT_PAUSE_S = 30
_pause = time.sleep
BOUNDS = (-93.0, 42.4, -86.2, 47.4)          # Wisconsin with its Great Lakes shore; a point outside is not used
MIN_BEACHES = 200                             # 441 on 2026-11-16; far fewer is a partial answer
MIN_SHARE_OF_LAST = 0.8
MIN_TABLE_ROWS = 200                          # 453 rows on 2026-11-16

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
    if len(at) == 10:
        return date.fromisoformat(at)
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


def issued_end(text, at: str, start: str | None = None) -> str | None:
    """A valid source end, never before this episode or after the read's local day."""
    first, tail = parse_issued(text, at)
    end, _ = parse_issued(f"{tail} - ", at) if tail else (None, None)
    return end if first and end and first <= end and (not start or local_day(start).isoformat() <= end) else None


def sample_result(value, sampled_at):
    if value is None or isinstance(value, bool) or not str(value).strip():
        return None
    # ECOLIVALUE's unit and laboratory sentinel meanings are not established by this layer read.
    # Keep the source result as text; do not infer CFU, MPN or a numeric concentration.
    return {'analyte': 'E. coli', 'text': scrub(str(value)), 'unit': None, 'qualifier': None,
            'sampled_at': sampled_at, 'source_field': 'ECOLIVALUE'}


def issued_start_text(text) -> str:
    return re.split(r"\s+-\s*|\s*-\s+", _s(text), maxsplit=1)[0].upper() if _s(text) else ""


def _epoch(ms) -> str | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1000, timezone.utc).astimezone(TZ).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None




# ---------------------------------------------------------------- the layer read

TEXT_FIELDS = ("OGW_BEACH_NAME_TEXT", "STATUS", "BEACH_ACTION", "MAP_STATUS", "ISSUED")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_read(js, count, last_count: int | None = None) -> list[dict]:
    """The layer's features, or ValueError for anything but a complete answer: every field asked for present and of
    its type on every beach (OBJECTID and BEACH_SEQ_NO integers, SAMPLEDATE an epoch number or null, the text fields
    text or null, the point numbers, "NaN" or absent), BEACH_SEQ_NO unique, the count equal to the features, the floor
    and the share of the last complete read met. A failed check ends, lifts and saves nothing (Astra review P1-1)."""
    if not isinstance(js, dict) or js.get("error") or not isinstance(js.get("features"), list):
        raise ValueError("the layer returned an error or no feature list")
    if js.get("exceededTransferLimit"):
        raise ValueError("the layer response was cut off (exceededTransferLimit)")
    feats = js["features"]
    seen = set()
    for f in feats:
        if not isinstance(f, dict):
            raise ValueError("a feature is not an object")
        a = f.get("attributes")
        if not isinstance(a, dict) or any(k not in a for k in REQUIRED_FIELDS):
            raise ValueError(f"a beach lacks the fields {FIELDS}")
        seq = a.get("BEACH_SEQ_NO")
        if not _is_int(seq):
            raise ValueError("a beach has no integer BEACH_SEQ_NO")
        if not _is_int(a.get("OBJECTID")):
            raise ValueError(f"beach {seq}: OBJECTID is not an integer")
        if a.get("SAMPLEDATE") is not None and not _is_num(a["SAMPLEDATE"]):
            raise ValueError(f"beach {seq}: SAMPLEDATE is not a date")
        for k in TEXT_FIELDS:
            if a.get(k) is not None and not isinstance(a[k], str):
                raise ValueError(f"beach {seq}: {k} is not text")
        g = f.get("geometry")
        if g is not None:
            if not isinstance(g, dict) or not all(_is_num(g.get(c)) or g.get(c) == "NaN" for c in ("x", "y")):
                raise ValueError(f"beach {seq}: the point is malformed")
        if seq in seen:
            raise ValueError(f"beach {seq} is listed twice")
        seen.add(seq)
    if len(feats) < MIN_BEACHES:
        raise ValueError(f"the layer returned {len(feats)} beaches, fewer than {MIN_BEACHES}")
    if not isinstance(count, dict) or not _is_int(count.get("count")) or count["count"] != len(feats):
        raise ValueError(f"the layer counts {(count or {}).get('count') if isinstance(count, dict) else None} beaches "
                         f"and returned {len(feats)}")
    if last_count and len(feats) < MIN_SHARE_OF_LAST * last_count:
        raise ValueError(f"the layer returned {len(feats)} beaches, against {last_count} at the last complete read")
    return feats


def safe_features(features: list[dict]) -> list[dict]:
    """The fields read, every text scrubbed, the point rounded to three decimals, before anything is saved (P2)."""
    out = []
    for f in features:
        a = f.get("attributes") or {}
        lat, lon = _pt(f.get("geometry"))
        attrs = {k: (scrub(a[k]) if isinstance(a.get(k), str) else a.get(k)) for k in FIELDS if k in a}
        out.append({"attributes": attrs, "geometry": {"x": lon, "y": lat} if lat is not None else None})
    return out


# ---------------------------------------------------------------- the report table (beaches with no point)

TABLE_HEAD = ["beach name", "status", "reason", "date of advisory", "nearest town"]


def _cell(c: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip()


def parse_table(page) -> list[dict]:
    """The report page's results table as rows {name, status, reason, issued, town}, or ValueError when the table is
    missing, its columns changed, a row is not in its shape or the page is cut off."""
    if not isinstance(page, str):
        raise ValueError("the report page is not text")
    i = page.find('id="tblSearchResult"')
    if i < 0:
        raise ValueError("the report table was not found")
    j = page.find("</table>", i)
    if j < 0:
        raise ValueError("the report table is cut off")
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", page[i:j], re.S)
    if not trs:
        raise ValueError("the report table has no rows")
    head = [_cell(c).lower() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", trs[0], re.S)]
    if head != TABLE_HEAD:
        raise ValueError(f"the report table's columns changed: {head}")
    rows = []
    for tr in trs[1:]:
        cells = [_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) != 5 or not cells[0]:
            raise ValueError("a report row is not in the table's shape")
        rows.append({"name": scrub(cells[0]), "status": scrub(cells[1]), "reason": scrub(cells[2]),
                     "issued": scrub(cells[3]), "town": scrub(cells[4])})
    return rows


def check_table(rows: list[dict], last_count: int | None = None) -> list[dict]:
    if len(rows) < MIN_TABLE_ROWS:
        raise ValueError(f"the report table has {len(rows)} rows, fewer than {MIN_TABLE_ROWS}")
    if last_count and len(rows) < MIN_SHARE_OF_LAST * last_count:
        raise ValueError(f"the report table has {len(rows)} rows, against {last_count} at the last complete read")
    return rows


def _norm(s) -> str:
    return re.sub(r"\s+", " ", _s(s).lower())


def table_only(rows: list[dict], features: list[dict]) -> list[dict]:
    """The table's rows for beaches the layer does not hold (by name): the beaches with no map point."""
    on_layer = {_norm((f.get("attributes") or {}).get("OGW_BEACH_NAME_TEXT")) for f in features}
    return [r for r in rows if _norm(r["name"]) not in on_layer]


# ---------------------------------------------------------------- what the fields say

BACTERIA = re.compile(r"e\.?\s*coli|bacteri|enterococ|fecal|coliform", re.I)


def reason_categories(reason: str) -> list[str]:
    cats = [c for c, rx in (("bacteria", BACTERIA), ("bloom", BLOOM)) if rx.search(reason or "")]
    return cats or ["unknown"]


def classify(action: str, reason: str, sym: str) -> dict | None:
    """What the Department's fields say about one beach: None for no advisory in effect, {"blank": True} for a blank
    action with nothing else recognised (it says nothing), else the advisory. A recognised advisory or closure, in the
    action or the map symbol, is resolved first, the stronger of the two kept (closure over advisory); an unfamiliar
    action is a label only when nothing is recognised (Astra review P1-4)."""
    action, reason, sym = _s(action), _s(reason), _s(sym)
    if SEASON.search(reason) and not (ADVISORY.match(action) or ADVISORY.match(sym) or CLOSED.match(sym)):
        return None                                    # the season's end: not an advisory, never a finding
    found = {}
    for src, v in (("BEACH_ACTION", action), ("MAP_STATUS", sym)):
        if ADVISORY.match(v):
            found.setdefault("advisory", src)
        elif CLOSED.match(v):
            found.setdefault("closure", src)
    unrecognised = action if action and not (ADVISORY.match(action) or CLOSED.match(action)
                                             or NOT_IN_EFFECT.match(action)) else None
    if found:
        kind = "closure" if "closure" in found else "advisory"
        basis = found[kind]
    elif unrecognised:
        kind, basis = "label", "BEACH_ACTION"
    elif not action:
        return {"blank": True}
    else:
        return None
    cats = reason_categories(reason)
    if cats == ["bloom"]:
        etype, also = "hab_advisory", []
    else:
        etype = "beach_closure" if kind == "closure" else "beach_advisory"
        also = ["bloom"] if "bloom" in cats else []
    return {"kind": kind, "etype": etype, "also": also, "cats": cats, "action": action or None, "reason": reason or None,
            "map_status": sym or None, "basis": basis, "unrecognised_action": unrecognised if found else None}


# ---------------------------------------------------------------- records

def _midnight_utc(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=TZ).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance(state: dict, current: dict, listed: set, blank: set, now: str, key_of) -> dict:
    """One complete read applied to the held records of one list (the layer's or the table's): each observation
    continues the open record of the same item, kind, type and issue text, or opens a new one; an open record the read
    no longer shows ends at this read (a blank action or disputed source end holds it)."""
    from copy import deepcopy
    state = deepcopy(state)

    def same(v, o) -> bool:
        return (v["kind"], v["etype"], v.get("issued_start") or "") == (o["kind"], o["etype"],
                                                                        o.get("issued_start") or "")
    matched = set()
    for iid, o in current.items():
        key = next((k for k, v in state.items() if v["iid"] == iid and not v.get("ended_at") and same(v, o)), None)
        if key is None:
            start, prec, returned = o["issued"], "day" if o["issued"] else "poll", False
            ends = [v["ended_at"] for v in state.values() if v["iid"] == iid and v.get("ended_at")]
            if start and ends and _midnight_utc(start) < max(
                    _midnight_utc((date.fromisoformat(e) + timedelta(days=1)).isoformat()) if len(e) == 10
                    else datetime.fromisoformat(e.replace("Z", "+00:00")) for e in ends):
                # the Department's date is earlier than the end we saw of this beach's last episode: the days between
                # were seen without it, so this episode starts at its return (Astra review P1-3)
                start, prec, returned = None, "poll", True
            stamp = start or "p" + re.sub(r"[^0-9T]", "", now)[:13]
            key = base = key_of(iid, o["kind"], stamp)
            n = 2
            while key in state:
                key, n = f"{base}-{n}", n + 1
            state[key] = {"iid": iid, "first_seen_at": now, "last_seen_at": now, "started_at": start or now,
                          "precision": prec, "returned": returned, **o}
        else:
            v = state[key]
            v["listed_periods"] = extend_periods(v.get("listed_periods"), now, _period_origin(v), v.get("last_seen_at"))
            v["last_seen_at"] = now
            for k in ("action", "reason", "cats", "also", "map_status", "basis", "unrecognised_action", "issued_text",
                      "issued_end_text", "sample_at", "sample_result", "town"):
                if k in o:
                    if v.get(k) != o[k] and v.get(k) is not None:
                        v.setdefault('revisions', []).append({'seen_at': now, 'field': k, 'was': v[k], 'now': o[k]})
                    v[k] = o[k]
            for k in ("name", "lat", "lon"):
                if o.get(k) is not None and o[k] != v.get(k):
                    if v.get(k) is not None:
                        v.setdefault("revisions", []).append({"seen_at": now, "field": k, "was": v.get(k),
                                                              "now": o[k]})
                    v[k] = o[k]
            v.pop("missing_since", None)
        matched.add(key)
    # Resolve each inactive observation once, within the retained episode's boundaries. Reused first
    # ISSUED dates are common on returns and cannot identify an episode on their own.
    attributed = {}
    for iid, es in listed.items() if isinstance(listed, dict) else ():
        if (iid in current or iid in blank
                or any(ADVISORY.match(_s(es.get(k))) or CLOSED.match(_s(es.get(k)))
                       for k in ('action', 'map_status'))):
            continue
        end = issued_end(es.get('issued_text'), now)
        if not end:
            continue
        candidates = []
        for key, v in state.items():
            if (v['iid'] != iid or issued_start_text(es.get('issued_text')) != v.get('issued_start')
                    or not issued_end(es.get('issued_text'), now, v['started_at'])):
                continue
            # An observed end bounds late corrections. A source-only end can be revised within that boundary.
            observed_end = v.get('end_seen_at')
            if not observed_end and v.get('ended_at_precision', 'poll') == 'poll':
                observed_end = v.get('ended_at')
            if observed_end and end > local_day(observed_end).isoformat():
                continue
            others = [o for k, o in state.items() if k != key and o['iid'] == iid]
            if any(datetime.fromisoformat(o['first_seen_at'].replace('Z', '+00:00'))
                   > datetime.fromisoformat(v['first_seen_at'].replace('Z', '+00:00'))
                   and local_day(o['started_at']).isoformat() <= end for o in others):
                continue
            candidates.append(key)
        if len(candidates) == 1:
            attributed[candidates[0]] = end

    for key, v in state.items():
        es = listed.get(v['iid'], {}) if isinstance(listed, dict) else {}
        _, end_text = parse_issued(es.get('issued_text'), now)
        end = attributed.get(key)
        if end_text and not end:
            evidence = {**deepcopy(es), 'seen_at': now}
            history = v.setdefault('unattributed_lift_evidence', [])
            if not history or any(history[-1].get(k) != val for k, val in es.items()):
                history.append(evidence)
        if end:
            if v.get('ended_at') and v['ended_at'] != end:
                v.setdefault('end_observations', []).append({
                    'ended_at': v['ended_at'], 'precision': v.get('ended_at_precision', 'poll'),
                    'end_seen': deepcopy(v.get('end_seen')),
                    'seen_at': v.get('source_end_seen_at') or v.get('end_seen_at'), 'replaced_at': now})
            v.update(ended_at=end, ended_at_precision='day', end_seen=deepcopy(es),
                     end_seen_at=v.get('end_seen_at') or now, source_end_seen_at=now,
                     end_basis="The Department's second ISSUED date for this advisory")
            v.pop('missing_since', None)
            continue
        if v.get('ended_at') or key in matched:
            continue
        if v['iid'] in blank:
            v['missing_since'] = v.get('missing_since') or now
            continue
        # An inactive row carrying a disputed date cannot close an unmatched episode at the poll either.
        if end_text and v['iid'] not in current:
            continue
        v['ended_at'] = now
        v['ended_at_precision'] = 'poll'
        v['end_seen_at'] = now
        v.pop('missing_since', None)
        v['end_seen'] = deepcopy(es) if es else {'absent': True}
    return state


def _observation(action, reason, sym, issued_text, name, now, **extra) -> dict | None:
    c = classify(action, reason, sym)
    if c is None or c.get("blank"):
        return c
    issued, end_text = parse_issued(issued_text, now)
    return {**c, "name": _s(name) or None, "issued": issued, "issued_text": _s(issued_text) or None,
            "issued_start": issued_start_text(issued_text), "issued_end_text": end_text, **extra}


def records(features: list[dict], prev: dict, now: str, table: list[dict] | None = None,
            table_ok: bool = True) -> tuple[list[dict], dict, dict]:
    """Records from a complete layer read (check_read) of safe features and, when table_ok, the report table's rows
    (parse_table): the table only for the beaches the layer does not hold. When the table could not be read its held
    records are carried unchanged. Returns (records, the new state, counts)."""
    counts = {"beaches": len(features), "by_action": {}, "by_reason": {}, "by_map_status": {}, "in_effect": 0,
              "without_point": 0}
    current, blank, listed = {}, set(), {}
    for f in features:
        a = f.get("attributes") or {}
        for key, fld in (("by_action", "BEACH_ACTION"), ("by_reason", "STATUS"), ("by_map_status", "MAP_STATUS")):
            v = _s(a.get(fld)) or "(blank)"
            counts[key][v] = counts[key].get(v, 0) + 1
        seq = a["BEACH_SEQ_NO"]
        listed[seq] = {"action": _s(a.get("BEACH_ACTION")) or None, "reason": _s(a.get("STATUS")) or None,
                       "issued_text": _s(a.get("ISSUED")) or None, "map_status": _s(a.get("MAP_STATUS")) or None}
        lat, lon = _pt(f.get("geometry"))
        o = _observation(a.get("BEACH_ACTION"), a.get("STATUS"), a.get("MAP_STATUS"), a.get("ISSUED"),
                         a.get("OGW_BEACH_NAME_TEXT"), now, lat=lat, lon=lon, sample_at=_epoch(a.get("SAMPLEDATE")),
                         source="layer", sample_result=sample_result(a.get("ECOLIVALUE"), _epoch(a.get("SAMPLEDATE"))))
        if o is None:
            continue
        if o.get("blank"):
            blank.add(seq)
            continue
        counts["in_effect"] += 1
        counts["without_point"] += lat is None
        current[seq] = o
    beaches = advance(prev.get("beaches") or {}, current, listed, blank, now, lambda i, k, s: f"{i}-{k}-{s}")
    new = {**prev, "beaches": beaches, "last_count": len(features)}
    held_table = prev.get("table") or {}
    if table_ok and table is not None:
        only = table_only(table, features)
        counts["table_rows"], counts["table_only_beaches"] = len(table), len(only)
        tcur, tlisted, tblank = {}, {}, set()
        for r in only:
            iid = f"{_norm(r['name'])}|{_norm(r['town'])}"
            tlisted[iid] = {"action": r["status"] or None, "reason": r["reason"] or None, "issued_text": r["issued"] or None}
            o = _observation(r["status"], r["reason"], None, r["issued"], r["name"], now, lat=None, lon=None,
                             town=r["town"] or None, source="report_table")
            if o is None:
                continue
            if o.get("blank"):
                tblank.add(iid)
                continue
            if iid in tcur:
                raise ValueError(f"the report table lists {r['name']} twice")
            tcur[iid] = o
        counts["table_in_effect"] = len(tcur)
        new["table"] = advance(held_table, tcur, tlisted, tblank, now, _table_key)
        new["last_table_count"] = len(table)
    else:
        new["table"] = held_table
    recs = [_record(k, v, now) for k, v in sorted(beaches.items())]
    recs += [_record(k, v, now) for k, v in sorted(new["table"].items())]
    return recs, new, counts


def _table_key(iid: str, kind: str, stamp: str) -> str:
    name, town = iid.split("|", 1)
    slug = re.sub(r"[^a-z0-9]+", "-", f"{name} {town}").strip("-")
    return f"t-{slug}-{kind}-{stamp}"


def _period_origin(v: dict) -> str:
    """The first listing period starts at the Department's date (local midnight) where it gives one, else the first
    read: the Department's own window is confirmed by its date, the time before our first read is not ours."""
    if v.get("precision") == "day":
        return _iso(_midnight_utc(v["started_at"]))
    return v["started_at"]


LABEL_CAUTION_HOURS = 72


def _record(key: str, v: dict, now: str) -> dict:
    kind, etype = v["kind"], v["etype"]
    from_table = v.get("source") == "report_table"
    has_pt = v.get("lat") is not None
    name, reason = scrub(v.get("name")), scrub(v.get("reason"))       # carried state is scrubbed again (P2)
    raw = {"state": "WI", "time_zone": "America/Chicago", "beach_name": name,
           "beach_action": scrub(v.get("action")), "reason": reason, "reason_categories": v.get("cats") or ["unknown"],
           "map_status": scrub(v.get("map_status")), "advisory_kind": kind,
           "read_from": "report_table" if from_table else v.get("basis"), "issued_text": scrub(v.get("issued_text")),
           "first_seen_at": v.get("first_seen_at"), "_last_seen_in_source": v.get("last_seen_at"),
           "_point_extent_only": True}
    if from_table:
        raw.update(nearest_town=scrub(v.get("town")),
                   point_basis=("the Department's report lists this beach and its nearest town but gives no map point "
                                "for it: its place on the map is not known, and none is invented"))
    else:
        raw.update(beach_seq_no=v["iid"], last_sample_at=v.get("sample_at"),
                   extent_basis=("the Department gives one point for the beach: shown at that point; the lake or river "
                                 "is not coloured whole"),
                   point_basis=("the beach's point on the Department's beach map layer, rounded to three decimals"
                                if has_pt else "the Department's layer gives no usable point for this beach: listed, "
                                               "not mapped"))
    if v.get('sample_result'):
        raw['sample_result'] = v['sample_result']
    if v.get("also"):
        raw["_also_categories"] = list(v["also"])
        raw["also_basis"] = ("the Department's reason names bacteria and algae: one advisory at the beach, counted as a "
                             "beach advisory and as an algal bloom")
    if v.get("unrecognised_action"):
        raw["unrecognised_action"] = scrub(v["unrecognised_action"])
    if etype == "hab_advisory":
        raw["bloom_action"] = "closure" if kind == "closure" else "advisory"
    if v.get("returned"):
        raw["start_basis"] = ("the read at which the beach returned to the Department's list; the Department's date "
                              "(issued_text) is earlier than the end we saw of its last episode, so the days between "
                              "are not shown")
    elif v.get("precision") == "day":
        raw["start_basis"] = "the Department's Date of Advisory, a date with no time of day"
    else:
        raw["start_basis"] = ("the first read that listed the advisory; the Department's date could not be read "
                              "unambiguously, and its text is kept (issued_text)")
    if v.get("issued_end_text"):
        raw["issued_end_text"] = scrub(v["issued_end_text"])
        raw["issued_end_basis"] = ("the Department's text gives an end date while its action still lists the "
                                   "advisory; we keep showing it while it is listed")
        parsed_end = issued_end(v.get('issued_text'), now, v['started_at'])
        if parsed_end:
            raw['source_ended_at'] = parsed_end
    p = v.get("listed_periods") or []
    if len(p) > 1:
        raw.update(listed_periods=p, periods_basis=("the reads that listed this advisory, in periods: a read more "
                                                    "than 14 days after the previous one opens a new period, and the "
                                                    "unread time between is not confirmed"))
    if v.get("missing_since"):
        raw["_missing_from_source_since"] = v["missing_since"]
    if v.get('unattributed_lift_evidence'):
        raw['unattributed_lift_evidence'] = v['unattributed_lift_evidence']
    if v.get('end_observations'):
        raw['end_observations'] = v['end_observations']
    if v.get("revisions"):
        raw["revisions"] = v["revisions"]
    if v.get("ended_at"):
        es = v.get("end_seen") or {}
        raw['end_seen'] = es
        raw.update(ended_at_precision=v.get("ended_at_precision", "poll"),
                   end_basis=("the first complete read of the Department's list that no longer listed the beach"
                              if es.get("absent") else
                              "the first complete read of the Department's list that no longer showed this advisory "
                              f"(it then gave {scrub(es.get('action')) or 'no action'}, "
                              f"{scrub(es.get('reason')) or 'no reason'})"))
        if v.get('end_basis'):
            raw['end_basis'] = v['end_basis']
        _, end_text = parse_issued(es.get("issued_text"), now)
        if end_text:
            raw["source_end_text"] = scrub(end_text)
    if v.get('ended_at_precision') == 'day' and v.get('ended_at'):
        es = v.get('end_seen') or {}
        _, end_text = parse_issued(es.get('issued_text'), now)
        raw['source_end_observation'] = {
            'date': v['ended_at'], 'text': scrub(end_text),
            'action': scrub(es.get('action')), 'map_status': scrub(es.get('map_status')),
            'issued_text': scrub(es.get('issued_text')),
            'seen_at': v.get('source_end_seen_at') or v.get('end_seen_at')}
    elif not v.get('ended_at') and raw.get('source_ended_at'):
        raw['source_end_observation'] = {
            'date': raw['source_ended_at'], 'text': raw.get('issued_end_text'),
            'action': raw['beach_action'], 'map_status': raw['map_status'],
            'issued_text': raw['issued_text'], 'seen_at': v.get('last_seen_at')}
    if kind == "label":
        # our caution while the Department lists a value we do not know, never its advisory, even after it ends
        # (data/rules.json unresolved.sample_caution; Astra review P1-5)
        raw.update(_agency_label_only=True, _agency_label=scrub(v.get("action")),
                   _label_basis="a Beach Health action we do not know; shown with our caution while it is listed",
                   _caution_to_notice_end=True, _open_notice_caution_hours=LABEL_CAUTION_HOURS,
                   _notice_end_basis="the Department still listed the beach with this action")
        if v.get("ended_at"):
            raw["_notice_closed_at"] = v["ended_at"]
        status = "unknown"
    else:
        status = "advisory_lifted" if v.get("ended_at") else "advisory_active"
    word = {"advisory": "an advisory", "closure": "a closure"}.get(kind, f"\"{scrub(v.get('action'))}\"")
    advice = (f"The Wisconsin DNR's Beach Health system lists {word} at this beach"
              + (f" (reason: {reason})" if reason else "")
              + (f", dated {v['issued']}" if v.get("issued") else "") + ".")
    if v.get('issued_end_text') and not v.get('ended_at'):
        advice += (f" The Department gives ISSUED \"{scrub(v.get('issued_text'))}\" and "
                   f"BEACH_ACTION \"{scrub(v.get('action'))}\", MAP_STATUS \"{scrub(v.get('map_status'))}\"; "
                   "we keep showing the advisory while it is listed.")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status,
        outfall_name=name or f"Beach {v['iid']}", waterbody_text=None,
        lat=v.get("lat"), lon=v.get("lon"), coord_source="beach" if has_pt else None,
        coord_precision_m=100 if has_pt else None,
        started_at=v["started_at"], ended_at=v.get("ended_at"), time_precision=v["precision"], fetched_at=now,
        reported_at=None, published_at=None, source_updated_at=None,
        authority=AUTHORITY, advice_text=advice,
        advice_window_basis=("our caution while the Department lists this action" if kind == "label"
                             else "shown while the Department lists the advisory"),
        source_url=REPORT_URL, raw=raw)


META = {"credit": "Wisconsin Department of Natural Resources, Wisconsin Beach Health (beach map layer and report)",
        "license": "No licence statement on the service",
        "caveat": ("The Department's current advisories and closures, with its reason and date; blooms are shown as "
                   "blooms. Out of season most beaches read \"Closed for season\": that is the season's end, not a "
                   "finding about the water. A lack of recent sample data does not cancel an advisory or closure the "
                   "Department lists."),
        "time_basis": ("The Department's Date of Advisory (a date, no time of day); an end is the first read that no "
                       "longer lists the advisory, or its matching second ISSUED date when the status confirms it.")}


def _get(url: str) -> requests.Response:
    """GET with the feed's headers and timeout; a connection not made is tried again (CONNECT_TRIES, CONNECT_PAUSE_S
    apart). Anything else (an HTTP status, a read timeout, a TLS error, a malformed answer) is raised at once; the
    caller's failure path is unchanged."""
    for n in range(1, CONNECT_TRIES + 1):
        try:
            return requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.exceptions.SSLError:
            raise
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
            # requests reports a read timeout in the body as a ConnectionError wrapping urllib3's ReadTimeoutError
            if n == CONNECT_TRIES or isinstance(e.args[0] if e.args else None, ReadTimeoutError):
                raise
            print(f"{SOURCE_ID}: connection not made ({type(e).__name__}), try {n + 1} of {CONNECT_TRIES} "
                  f"in {CONNECT_PAUSE_S} s", file=sys.stderr)
            _pause(CONNECT_PAUSE_S)


def run(args) -> int:
    now = args.at or now_iso()
    prev = {} if args.file else (read_json(STATE_PATH, {}) or {})
    out = args.out
    table, table_err = None, None
    if args.file:
        saved = json.loads(open(args.file).read())
        feats, table = saved["beaches"], saved.get("table")
        if table is None:
            table_err = "the saved file holds no report table"
    else:
        try:
            r = _get(QUERY)
            r.raise_for_status()
            c = _get(COUNT)
            c.raise_for_status()
            feats = safe_features(check_read(r.json(), c.json(), prev.get("last_count")))
        except Exception as e:                         # any failure: nothing lifted, greyed, dropped or saved
            write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}"[:300], meta=META, path=out)
            print(f"{SOURCE_ID}: read failed: {type(e).__name__}", file=sys.stderr)
            return 1
        try:
            p = _get(REPORT_URL)
            p.raise_for_status()
            table = check_table(parse_table(p.text), prev.get("last_table_count"))
        except Exception as e:                         # the table alone failed: its held records stand
            table, table_err = None, f"the report table: {error_text(e)}"[:300]
        save_raw(SOURCE_ID, json.dumps({"format": SAFE_FORMAT, "beaches": feats, "table": table}), "json")
    try:
        recs, new, n = records(feats, prev, now, table, table_ok=table is not None)
    except ValueError as e:
        if table is None:
            write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}"[:300], meta=META, path=out)
            return 1
        table_err = f"the report table: {error_text(e)}"[:300]     # a table that cannot be applied
        recs, new, n = records(feats, prev, now, None, table_ok=False)
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}"[:300], meta=META, path=out)
        return 1
    if table_err:
        # the layer's read stands; the table's held records are carried, and health is false for this read
        write_events(SOURCE_ID, recs, ok=False, error=table_err, meta={**META, "counts": n}, path=out, partial=True)
    else:
        write_events(SOURCE_ID, recs, meta={**META, "counts": n}, path=out)
    if not args.file:
        write_json(STATE_PATH, new)
    print(f"{SOURCE_ID}: {len(recs)} records; {n['in_effect']} in effect of {n['beaches']} beaches"
          + (f"; {table_err}" if table_err else ""))
    return 1 if table_err else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="saved {beaches, table} JSON of safe features and rows (no network)")
    ap.add_argument("--at")
    ap.add_argument("--out")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
