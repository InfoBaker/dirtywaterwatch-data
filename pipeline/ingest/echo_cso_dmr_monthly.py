"""Monthly CSO figures from EPA ECHO Discharge Monitoring Reports: Springfield, Holyoke, Chicopee (MA).

Source
  ECHO Effluent Charts REST service (registry: fed-echo-effluent-charts-rest),
  https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart?output=JSON&p_id=<permit>
  &parameter_code=<code>&start_date=MM/DD/YYYY&end_date=MM/DD/YYYY, no key. Region 1 permits since
  about 2022 require a monthly CSO DMR per outfall: 51484 'Number of Events', 81381 'Duration of
  discharge', 82220 'Flow, total'. One request per permit and parameter (9 per run); each response
  is kept under data/raw/echo-cso-dmr-monthly/.

Records
  One per permit + outfall + month (+ limit set, when an outfall has two monitoring lines, as
  Chicopee 007 does), with the three parameters merged: event_type cso, status ended, started_at
  the first and ended_at the last day of the month, time_precision month, reported_at the DMR's
  ValueReceivedDate. These are monthly totals, not events: the status builder must not colour a
  water from them (same as annual_total). Months reported as NODI C (no discharge) or with zero
  events and no volume are not records; they are counted in meta.no_discharge_months. Internal
  monitoring points (Chicopee 010) are skipped: they are not a discharge to a water.
  volume_gal is filled only when the reported value is a monthly total in gallons (Holyoke
  'gal/mo' MO TOTAL). Springfield's flow is coded 'DAILY MX' in 'gal/d' although the permit asks for
  a monthly total, and Chicopee reports 'MGD' under TOTAL/MAXIMUM with the monthly line 'not
  quantifiable' (NODI Q): those stay null with the figure and its coding in volume_text and raw,
  until the semantics are confirmed with EPA Region 1.
  water_slugs and coordinates from data/outfalls-new-england.json (permit + outfall); where the registry has
  no slug, its ECHO receiving-water name against data/waters-new-england.csv (water_match 'name').

Failures
  Any of the nine requests failing (after three tries) makes the run ok=False with the failed
  requests named; the previous records stay. The research samples are not used as a fallback:
  they cover two parameters over shorter windows and would make a partial history look complete.

Lag and cadence
  DMRs are due the 15th of the following month and ECHO refreshes weekly, so a month appears
  2-7 weeks after it ends. Poll weekly (Mondays); the request covers --since (default 2024-01-01)
  to today, so late and revised DMRs are picked up.

Run from pipeline/:  python -m ingest.echo_cso_dmr_monthly [--since 2024-01-01]
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime

import requests

import common
from common import DATA_DIR, HEADERS, ROOT, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "echo-cso-dmr-monthly"
URL = "https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart"
PERMITS = {"MA0101613": "Springfield", "MA0101630": "Holyoke", "MA0101508": "Chicopee"}
PARAMS = {"51484": "events", "81381": "duration", "82220": "flow"}
AUTHORITY = "EPA ECHO Discharge Monitoring Reports (permittee-reported monthly CSO figures)"
GAL_TOTAL_UNITS = {"gal/mo": 1, "gal": 1, "MG": 1_000_000, "MG/mo": 1_000_000}
TOTAL_BASES = {"MO TOTAL", "TOTAL"}


def name_index() -> tuple[dict, dict]:
    """(state, normalised name) -> water rows, and slug -> bbox, for the receiving-water fallback."""
    import csv
    import re
    idx: dict = defaultdict(list)
    with open(DATA_DIR / "waters-new-england.csv", newline="") as f:
        for r in csv.DictReader(f):
            idx[(r["state"], re.sub(r"[^a-z0-9]", "", r["name"].lower()))].append(r)
    bbox = {w["slug"]: w.get("bbox") for w in (read_json(DATA_DIR / "waters-ma.json", {}) or {}).get("waters", [])}
    return idx, bbox


def water_by_name(o: dict | None, idx: dict, bbox: dict) -> list[str]:
    """Outfall registry row without a slug -> the one MA water named like its ECHO receiving water
    (bbox around the outfall breaks ties between same-named waters)."""
    import re
    if not o or not o.get("receiving_water_echo"):
        return []
    hits = idx.get((o.get("state") or "MA", re.sub(r"[^a-z0-9]", "", o["receiving_water_echo"].lower())), [])
    if o.get("lat") is not None:   # same-named waters elsewhere in the state are not this one
        lat, lon = o["lat"], o["lon"]
        pad = .01 if len(hits) > 1 else .03
        hits = [h for h in hits if (b := bbox.get(h["slug"])) and b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad]
    return [hits[0]["slug"]] if len(hits) == 1 else []


def fetch(permit: str, code: str, since: date) -> tuple[dict | None, str]:
    params = {"output": "JSON", "p_id": permit, "parameter_code": code,
              "start_date": since.strftime("%m/%d/%Y"), "end_date": date.today().strftime("%m/%d/%Y")}
    for i in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            js = r.json()
            if (js.get("Results") or {}).get("Message") != "Success":
                raise ValueError(str(js)[:200])
            save_raw(SOURCE_ID, r.content, f"{permit}-{code}.json")
            return js["Results"], "live"
        except (requests.RequestException, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(3 * (i + 1))
    return None, f"failed ({err})"


def month_bounds(period_end: str) -> tuple[str, str, str]:
    d = datetime.strptime(period_end, "%d-%b-%y").date()
    first = d.replace(day=1)
    last = d.replace(day=calendar.monthrange(d.year, d.month)[1])
    return first.isoformat(), last.isoformat(), first.strftime("%Y-%m")


def ddmon(s: str | None) -> str | None:
    try:
        return datetime.strptime(s, "%d-%b-%y").date().isoformat() if s else None
    except ValueError:
        return None


def num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2024-01-01")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since)

    reg = read_json(DATA_DIR / "outfalls-new-england.json", {}) or {}
    outfalls = {(o["npdes_permit"], str(o["outfall"]).upper()): o for o in reg.get("outfalls", [])}
    disc = {}
    for r in read_json(ROOT / "research/ma/dischargers.json", []) or []:
        if r.get("npdes_permit"):
            disc[r["npdes_permit"]] = r

    # (permit, outfall, month, limit set schedule) -> {"events": row, "duration": row, "flow": row}
    cells: dict[tuple, dict] = defaultdict(dict)
    names: dict[str, str] = {}
    fetch_log, skipped_internal = {}, Counter()
    for permit in PERMITS:
        for code, label in PARAMS.items():
            res, how = fetch(permit, code, since)
            fetch_log[f"{permit}:{code}"] = how
            if not res:
                continue
            names[permit] = res.get("CWPName") or names.get(permit)
            for f in res.get("PermFeatures") or []:
                for par in f.get("Parameters") or []:
                    if "internal" in (par.get("MonitoringLocationDesc") or "").lower():
                        skipped_internal[f"{permit}:{f['PermFeatureNmbr']}"] += len(par.get("DischargeMonitoringReports") or [])
                        continue
                    for row in par.get("DischargeMonitoringReports") or []:
                        if not row.get("MonitoringPeriodEndDate"):
                            continue
                        key = (permit, f["PermFeatureNmbr"], row["MonitoringPeriodEndDate"], row.get("LimitSetScheduleId"))
                        prev = cells[key].get(label)
                        # several value types per month (Concentration1/Quantity2): keep a reported value
                        if prev is None or (prev.get("DMRValueNmbr") in (None, "") and row.get("DMRValueNmbr") not in (None, "")):
                            row = dict(row, _location=par.get("MonitoringLocationDesc"), _param=par.get("ParameterDesc"))
                            cells[key][label] = row
            time.sleep(1)

    if not any(h == "live" for h in fetch_log.values()):
        write_events(SOURCE_ID, [], ok=False, error=f"all requests failed: {fetch_log}")
        print(f"{SOURCE_ID}: all requests failed", file=sys.stderr)
        return 1

    # an outfall with two monitoring lines in the same month (Chicopee 007) gets :1 / :2
    sets: dict[tuple, list] = defaultdict(list)
    for (permit, of, pend, ls) in cells:
        if ls not in sets[(permit, of, pend)]:
            sets[(permit, of, pend)].append(ls)
    for k in sets:
        sets[k].sort(key=lambda x: str(x))

    records, no_discharge, latest = [], Counter(), {}
    widx, wbbox = name_index()
    for (permit, of, pend, ls), vals in sorted(cells.items()):
        start, end, ym = month_bounds(pend)
        ev, du, fl = vals.get("events"), vals.get("duration"), vals.get("flow")
        n_ev = num((ev or {}).get("DMRValueNmbr"))
        n_du = num((du or {}).get("DMRValueNmbr"))
        n_fl = num((fl or {}).get("DMRValueNmbr"))
        nodis = {k: v.get("NODICode") for k, v in vals.items() if v.get("NODICode")}
        # each outfall's latest month, a month of no discharge included (build/status.py: it clears an older
        # monthly mark; review 2026-11-03 SOL P2-7); a month with no figure and no NODI C says nothing
        said = [x for x in (n_ev, n_du, n_fl) if x is not None] + [0.0 for c in nodis.values() if str(c).upper() == "C"]
        if said:
            k = f"{permit}|{of}"
            if k not in latest or ym > latest[k]["month"]:
                latest[k] = {"month": ym, "discharged": any(x > 0 for x in said), "events": n_ev,
                             "received_at": max(filter(None, [ddmon(v.get("ValueReceivedDate")) for v in vals.values()]),
                                                default=None)}
        if not n_ev and not n_du and not n_fl:
            no_discharge[permit] += 1
            continue
        vol_gal, vol_note = None, None
        if fl and n_fl is not None:
            unit, base = fl.get("DMRUnitDesc"), fl.get("StatisticalBaseDesc")
            if unit in GAL_TOTAL_UNITS and base in TOTAL_BASES:
                vol_gal = int(round(n_fl * GAL_TOTAL_UNITS[unit]))
            else:
                vol_note = f"{fl.get('DMRValueNmbr')} {unit} ({base}; monthly-total semantics unconfirmed)"
        parts = []
        if n_ev is not None:
            parts.append(f"{n_ev:g} discharge event(s)")
        if n_du is not None:
            parts.append(f"{n_du:g} {(du or {}).get('DMRUnitDesc') or 'h'} of discharge")
        if vol_gal is not None:
            parts.append(f"{vol_gal:,} gallons")
        elif vol_note:
            parts.append(vol_note)
        if nodis:
            parts.append("NODI " + ", ".join(f"{k} {v}" for k, v in sorted(nodis.items())))
        o = outfalls.get((permit, of.upper()))
        same_month = sets[(permit, of, pend)]
        srid = f"{permit}:{of}:{ym}" + (f":{same_month.index(ls) + 1}" if len(same_month) > 1 else "")
        received = max(filter(None, [ddmon(v.get("ValueReceivedDate")) for v in vals.values()]), default=None)
        raw = {"month": ym, "permit_feature": of, "limit_set_schedule_id": ls,
               "monitoring_location": next((v["_location"] for v in vals.values()), None),
               "parameters": {k: {f: v.get(f) for f in ("ParameterCode", "_param", "DMRValueId", "DMRValueNmbr",
                                                           "DMRUnitDesc", "StatisticalBaseDesc", "ValueTypeDesc",
                                                           "NODICode", "NODIDesc", "ValueReceivedDate", "DMRDueDate",
                                                           "DaysLate", "VersionNmbr")}
                              for k, v in vals.items()},
               "note": "monthly DMR total, not an individual event"}
        d = disc.get(permit, {})
        slugs, how = ([o["water_slug"]], "outfall_registry") if o and o.get("water_slug") else ([], "none")
        if not slugs:
            slugs = water_by_name(o, widx, wbbox)
            how = "name" if slugs else "none"
        records.append(event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="cso", status="ended",
            discharger_id=d.get("id"), discharger_name=d.get("name") or names.get(permit), npdes_permit=permit,
            outfall_id=of, outfall_name=(o or {}).get("outfall_name"),
            waterbody_text=(o or {}).get("receiving_water_echo"),
            water_slugs=slugs, water_match=how,
            lat=(o or {}).get("lat"), lon=(o or {}).get("lon"), coord_source="outfall_layer" if o and o.get("lat") else None,
            started_at=start, ended_at=end, time_precision="month", reported_at=received,
            material="combined sewage and stormwater", volume_gal=vol_gal, volume_text="; ".join(parts) or None,
            estimate_flag="unknown", authority=AUTHORITY,
            source_url=f"https://echo.epa.gov/effluent-charts#{permit}",
            raw=raw,
        ))
    records.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    meta = {"registry_ids": ["fed-echo-effluent-charts-rest"], "since": args.since, "permits": PERMITS,
            "fetch": fetch_log, "no_discharge_months": dict(no_discharge),
            "latest_month_by_outfall": dict(sorted(latest.items())),
            "skipped_internal_monitoring_points": dict(skipped_internal),
            "cadence": "weekly; DMRs due the 15th of the following month"}
    failed = {k: v for k, v in fetch_log.items() if v != "live"}
    if failed:
        # a partial pull never refreshes the feed: ok=False, previous records kept (a first run with
        # nothing to keep writes what it has, still ok=False)
        err = "requests failed: " + "; ".join(f"{k} {v}" for k, v in failed.items())
        path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
        prev = read_json(path, {}) or {}
        if prev.get("records") or not records:
            write_events(SOURCE_ID, [], ok=False, error=err, meta=meta)
        else:
            write_json(path, {"source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": False, "error": err,
                              "last_ok_at": None, "meta": meta, "count": len(records), "records": records})
        print(f"{SOURCE_ID}: run not ok ({err})", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} outfall-months -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
