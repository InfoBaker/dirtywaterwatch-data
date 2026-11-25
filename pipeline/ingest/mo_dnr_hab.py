"""Missouri DNR harmful algal bloom map (Missouri): the waters DNR's public HAB map shows as "Harmful Algal Bloom Present"
or "Waterbody is CLOSED", polled into standing bloom advisory records.

Source
  https://gis.dnr.mo.gov/host/rest/services/wqm/HAB_SUBMIT_POINTS/MapServer/6 (registry: mo-dnr-hab-map), the
  WQM_HAB_POINTS_PUBLIC layer behind DNR's "HAB Public Viewer" (the map on
  https://dnr.mo.gov/water/alerts-hazards/harmful-algal-bloom-hab-reports-map). Public ArcGIS map service, no key; the
  privately owned waters are only counted by county in layer 5 (not read). One point per report with BloomStat (DNR's
  code), WBName, HABODat (the day the bloom was observed), CaseStatus, HABCo (county), globalid, DissDat (dissolved
  date) and IConfMet (confirmation method, source codes). DNR's map draws
  "advise" as "Harmful Algal Bloom Present" and "closed" as "Waterbody is CLOSED" whatever their age; "notice"
  (suspected), "dissap" (dissipated), "notthr" and "notver" (not threatening, not verified) only for 14 days after the
  observation, then as expired; "report" is an investigation pending. Read 2026-11-15 (UTC): 283 reports from 2017 to
  November 2026 (18 undated), 39 under "advise" (one with its case open), none "closed".

Record rules (the accuracy-first clock, as Kansas's HAB layer, ingest/ks_kdhe_hab.py)
  - One record per report per spell under "advise" or "closed": source_record_id the report's globalid and the poll the
    spell was first seen. event_type hab_advisory (blooms, plum), status advisory_active while the map shows it so,
    advice_text DNR's map label in DNR's words. The other codes are counted (meta), never records: a suspected or
    unverified bloom is not DNR's advisory.
  - started_at is the first poll that showed it (time_precision "poll"; raw.start_basis): DNR's map gives no advisory
    date. raw.observed_on is HABODat, the day the bloom was observed (a UTC day), never the advisory's start.
    raw.case_status is DNR's case status, kept as DNR states it ("Closed" cases can still be shown as present).
  - Each poll that shows it confirms the record (raw._last_seen_in_source; raw._poll_confirmed, so the colour ages out
    14 days after the last read that showed it, build/status.py). The first poll that no longer shows it under
    "advise" or "closed" ends it at that poll (raw.ended_at_precision "poll"), unless the same report supplies
    a valid DissDat under "dissap": then its source day is the end. A DissDat alongside a shown status is
    contradictory evidence, retained without closing the advisory. Confirmation codes stay as DNR gives them.
    A failed read changes nothing: an error,
    a truncated answer, a row without its id, a code DNR does not use or a shown row without a point inside Missouri
    fails the read (check), never lifts every advisory.
  - The point, kept to 0.001 degree before any save; raw.time_zone America/Chicago.

Privacy: only the fields above are requested and saved (never the public information text, the description, the
reporter or the owner fields); points rounded before the raw save.
Run from pipeline/:  python -m ingest.mo_dnr_hab [--file layer.json]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import common
from ingest import poll_periods, lift_dates
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from common import error_detail

SOURCE_ID = "mo-dnr-hab-map"
LAYER = "https://gis.dnr.mo.gov/host/rest/services/wqm/HAB_SUBMIT_POINTS/MapServer/6"
PAGE = "https://dnr.mo.gov/water/alerts-hazards/harmful-algal-bloom-hab-reports-map"
AUTHORITY = "Missouri Department of Natural Resources (harmful algal bloom map)"
FIELDS = "globalid,BloomStat,WBName,HABODat,CaseStatus,HABCo,DissDat,IConfMet"
SHOWN = {"advise": "Harmful Algal Bloom Present", "closed": "Waterbody is CLOSED"}
OTHER = {"notice", "dissap", "notthr", "notver", "report", ""}
MO_BOX = (35.9, 40.7, -95.8, -89.0)


def check(doc) -> None:
    """A layer answer good enough to say which waters are shown: anything else is a failed read."""
    if not isinstance(doc, dict) or "error" in doc or not isinstance(doc.get("features"), list):
        raise ValueError("the HAB layer's answer has no features list")
    if doc.get("exceededTransferLimit"):
        raise ValueError("the HAB layer's answer is truncated")
    for f in doc["features"]:
        if not isinstance(f, dict) or not isinstance(f.get("attributes"), dict):
            raise ValueError("a HAB layer row has no attributes")
        a = f["attributes"]
        code = str(a.get("BloomStat") or "").strip().lower()
        if code not in SHOWN and code not in OTHER:
            raise ValueError(f"unexpected bloom status {code!r}")
        if not str(a.get("globalid") or "").strip():
            raise ValueError("a HAB layer row has no id")
        if code in SHOWN:
            g = f.get("geometry")
            try:
                y, x = float(g["y"]), float(g["x"])
            except (TypeError, KeyError, ValueError):
                raise ValueError("a shown HAB report has no usable point") from None
            if not (MO_BOX[0] <= y <= MO_BOX[1] and MO_BOX[2] <= x <= MO_BOX[3]):
                raise ValueError("a shown HAB report's point is outside Missouri")


def rounded(doc: dict) -> dict:
    """Only the requested fields, every point kept to 0.001 degree, as saved in data/raw."""
    keep = FIELDS.split(",")
    return {"features": [{"attributes": {k: (f.get("attributes") or {}).get(k) for k in keep},
                          "geometry": {k: float(v) for k, v in (f.get("geometry") or {}).items()
                                       if k in ("x", "y") and v is not None}} for f in doc.get("features") or []]}


def day(ms) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d") if isinstance(ms, (int, float)) else None


def name_of(s) -> str | None:
    s = re.sub(r",?\s+(?:MO|Missouri)\.?$", "", " ".join(str(s or "").split())).strip()
    return s or None


def shown(doc: dict) -> tuple[dict[str, dict], dict]:
    out, counts = {}, {}
    for f in doc.get("features") or []:
        a, g = f["attributes"], f.get("geometry") or {}
        code = str(a.get("BloomStat") or "").strip().lower()
        counts[code or "none"] = counts.get(code or "none", 0) + 1
        if code in SHOWN:
            out[str(a["globalid"]).strip("{} ").lower()] = {
                "code": code, "name": name_of(a.get("WBName")), "observed_on": day(a.get("HABODat")),
                "case_status": a.get("CaseStatus"), "county": (str(a.get("HABCo") or "").strip() or None),
                "lat": float(g["y"]), "lon": float(g["x"])}
    return out, counts


def _source_evidence(r: dict, a: dict, at: str) -> None:
    raw = r['raw']
    fields = {k: a.get(k) for k in ('BloomStat', 'DissDat', 'IConfMet')}
    if raw.get('source_fields') and raw['source_fields'] != fields:
        raw.setdefault('source_field_history', []).append({'fields': raw['source_fields'],
                                                          'seen_at': raw.get('source_fields_seen_at')})
    raw['source_fields'] = fields
    raw['source_fields_seen_at'] = at
    raw['confirmation_method'] = common.scrub_text(str(a.get('IConfMet') or '')) or None
    raw['dissolved_on'] = day(a.get('DissDat'))
    if str(a.get('BloomStat') or '').lower() == 'dissap':
        r['advice_text'] = f"DNR reports BloomStat \"dissap\" and DissDat \"{raw['dissolved_on'] or 'not given'}\"."
    elif raw.get('dnr_code') in SHOWN:
        r['advice_text'] = f"DNR's map: {SHOWN[raw['dnr_code']]}."
    if raw['dissolved_on'] and str(a.get('BloomStat') or '').lower() in SHOWN:
        raw['end_conflict'] = (f"DNR gives DissDat {raw['dissolved_on']} and BloomStat {a['BloomStat']}; "
                               "we keep the advisory while DNR still shows the bloom as present or closed.")
        r['advice_text'] += ' ' + raw['end_conflict']
    else:
        raw.pop('end_conflict', None)


def run(doc: dict, prev: list[dict], at: str) -> tuple[list[dict], dict]:
    check(doc)
    from copy import deepcopy
    recs = {r["event_id"]: deepcopy(r) for r in prev}
    open_by = {r["raw"].get("report_id"): r for r in recs.values() if r["status"] == "advisory_active"}
    now, counts = shown(doc)
    source_rows = {str(f['attributes']['globalid']).strip('{} ').lower(): f['attributes']
                   for f in doc['features']}
    stats = {"reports": len(doc["features"]), "shown": len(now), "opened": 0, "confirmed": 0, "lifted": 0,
             "by_code": dict(sorted(counts.items()))}
    for rid, x in now.items():
        r = open_by.get(rid)
        if r is None:
            r = event(source_id=SOURCE_ID, source_record_id=f"{rid}-{re.sub(r'[^0-9]', '', at)[:14]}",
                      event_type="hab_advisory", status="advisory_active", waterbody_text=x["name"], lat=x["lat"],
                      lon=x["lon"], coord_source="source", coord_precision_m=None, started_at=at, time_precision="poll",
                      authority=AUTHORITY, advice_text=f"DNR's map: {SHOWN[x['code']]}.", source_url=PAGE,
                      raw={"state": "MO", "time_zone": "America/Chicago", "report_id": rid, "dnr_code": x["code"],
                           "dnr_label": SHOWN[x["code"]], "observed_on": x["observed_on"],
                           "case_status": x["case_status"], "county": x["county"], "layer": LAYER,
                           "start_basis": ("the first read of DNR's HAB map that showed this report as present or "
                                           "closed; DNR's map gives no advisory date"),
                           "observed_basis": "HABODat, the day the bloom was observed (UTC day); not the advisory's start"})
            recs[r["event_id"]] = r
            stats["opened"] += 1
        else:
            stats["confirmed"] += 1
            if r["raw"].get("dnr_code") != x["code"]:
                r["raw"].update(dnr_code=x["code"], dnr_label=SHOWN[x["code"]])
                r["advice_text"] = f"DNR's map: {SHOWN[x['code']]}."
            r["raw"]["case_status"] = x["case_status"]
            poll_periods.revise_place(r, at, name=x["name"], lat=x["lat"], lon=x["lon"], county=x["county"])
        _source_evidence(r, source_rows[rid], at)
        poll_periods.seen(r, at)
    # Resolve dated dissipation before any poll closure. A stale date belongs to its
    # historical spell and cannot close the returned spell at this fetch time.
    attributed = {}
    dated = set()
    for rid, a in source_rows.items():
        end = day(a.get('DissDat'))
        if str(a.get('BloomStat') or '').lower() != 'dissap' or not end:
            continue
        dated.add(rid)
        episodes = [r for r in recs.values() if r['raw'].get('report_id') == rid]
        observations = []
        for r in episodes:
            for o in r['raw'].get('lift_observations', []):
                lift_dates.remember(observations, o['date'], o['precision'], o['seen_at'])
            if r['raw'].get('ended_at_precision') == 'day' and r.get('ended_at'):
                lift_dates.remember(observations, r['ended_at'], 'day',
                                    r['raw'].get('source_fields_seen_at') or r['raw'].get('_unlisted_since')
                                    or r['fetched_at'])
        seen_at = lift_dates.remember(observations, end, 'day', at)

        def follows_start(r):
            return lift_dates.follows(end, 'day', r['started_at'], r['time_precision'], 'America/Chicago', seen_at)

        candidates = [r for r in episodes if end <= at[:10] and follows_start(r)
                      and not any(lift_dates.instant(o['started_at'], 'America/Chicago')
                                  > lift_dates.instant(r['started_at'], 'America/Chicago') and follows_start(o)
                                  for o in episodes)]
        if len(candidates) == 1:
            attributed[candidates[0]['event_id']] = end
        for r in episodes:
            r['raw']['lift_observations'] = deepcopy(observations)
            # Retain the contradictory date on unmatched open spells without confirming a listing.
            if r['status'] == 'advisory_active' or r['event_id'] in attributed:
                _source_evidence(r, a, at)
    for rid, r in open_by.items():
        if rid not in now:
            if rid in dated and r['event_id'] not in attributed:
                continue
            r.update(status="advisory_lifted", ended_at=at)
            r["raw"].update(ended_at_precision="poll", _unlisted_since=at,
                            end_basis="the first read at which DNR's map no longer showed it as present or closed; "
                                      "not DNR's own date")
            stats["lifted"] += 1
    # A late date can replace a poll end, but only on the spell it was attributed to.
    for r in recs.values():
        end = attributed.get(r['event_id'])
        if end and r['status'] == 'advisory_lifted':
            if r.get('ended_at') != end:
                r['raw'].setdefault('end_observations', []).append({
                    'ended_at': r.get('ended_at'), 'precision': r['raw'].get('ended_at_precision'),
                    'basis': r['raw'].get('end_basis'), 'replaced_at': at})
            r['ended_at'] = end
            r['raw'].update(ended_at_precision='day', end_basis="DNR's DissDat on its dissipated bloom report")
    for r in recs.values():
        r["fetched_at"] = at
        r["raw"]["_poll_confirmed"] = True
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    return out, stats


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        else:
            r = requests.get(f"{LAYER}/query", headers=HEADERS, timeout=(20, 120), params={
                "where": "1=1", "outFields": FIELDS, "outSR": 4326, "f": "json", "returnGeometry": "true"})
            r.raise_for_status()
            doc = r.json()
            check(doc)
            save_raw(SOURCE_ID, json.dumps(rounded(doc)), "json")
        recs, stats = run(doc, prev, now_iso())
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=error_detail(e))
        print(f"{SOURCE_ID}: {error_detail(e)}", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": LAYER, "page": PAGE, **stats,
        "credit": "Missouri Department of Natural Resources, Harmful Algal Bloom reports map",
        "caveat": ("DNR's public map of bloom reports: a water DNR shows as having a harmful algal bloom present, or as "
                   "closed, is shown from the first time this site read it so and ends at the first read that no longer "
                   "does, or on DNR's dissolved date when its report confirms dissipation. A dissolved date beside "
                   "a still-shown bloom does not close it. DNR gives no advisory start dates; privately owned waters "
                   "are not on the public map."),
        "cadence": "every refresh"})
    print(f"{SOURCE_ID}: {len(recs)} records ({ {k: v for k, v in stats.items() if k != 'by_code'} }) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
