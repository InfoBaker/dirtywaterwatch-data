"""Monthly CSO discharge days per New Jersey outfall from EPA ECHO Discharge Monitoring Reports.

Source
  ECHO Effluent Charts REST service (registry: nj-echo-effluent-dmr-cso, fed-echo-effluent-charts-rest),
  https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart?output=JSON&p_id=<permit>
  &parameter_code=81381&start_date=MM/DD/YYYY&end_date=MM/DD/YYYY, no key. NJPDES CSO permits report
  parameter 81381 'Duration of discharge' per outfall as a monthly total in days, counting "as a
  whole day for any calendar day when a discharge occurs" (permit Part IV.C.1.d); most permittees
  model it with a DEP-approved model rather than measure it (Part IV.A.1.c).
  The 25 NJPDES permits in research/nj/dischargers.json (21 CSO municipalities and authorities plus
  four treatment plants that hold CSO permits): ONE request per permit, a short sleep between them.
  Each response is kept with common.save_raw (data/raw/nj-echo-monthly/<stamp>.<permit>-81381.json)
  and doubles as the cache: a run reuses the copy fetched in the same calendar month (UTC) with the
  same start date, so ECHO is asked once a month per permit (--refresh asks again).

Records
  One per permit + outfall + month (+ limit set, when an outfall has two monitoring lines in a
  month): event_type cso, status ended, started_at the first and ended_at the last day of the month,
  time_precision month, reported_at the DMR's ValueReceivedDate, volume_text 'N days with discharge'.
  History only: month-precision records never colour a water (build/status.py). Months reported
  with zero days or a NODI code (no discharge, conditional monitoring not required ...) are not
  records; they are counted in meta. Only CSO outfalls are kept: permit features listed in the NJDEP
  outfall layer (data/build/nj-cso-outfalls.json, ingest/nj_outfalls.py) or as CSO outfalls in the
  ECHO inventory (data/outfalls-mid-atlantic.json), and any outfall of a CSO-only permit (Paterson
  028, raw.outfall_note); a treatment plant's own outfalls (MCUA 007) and internal monitoring points
  are counted in meta and skipped. outfall_id is the ECHO feature number ('030'); the NJDEP id
  ('NJ0108880-030A') is in raw. Coordinates, outfall name, receiving water and water_slugs come from
  the NJDEP layer join, else the ECHO inventory row.

Lag and cadence
  DMRs reach ECHO weeks to months after the month (median days after month end: Gloucester City 2,
  Paterson 14, Jersey City MUA 24, Camden City 27, Newark 97). The default window starts 2024-01-01
  so late and revised reports are picked up.

Failures
  A permit whose request fails three times makes the run ok=False with the permit named; the
  previous records stay (a first run with nothing to keep writes what it has, still ok=False).

Run from pipeline/:  python -m ingest.nj_echo_monthly [--since 2024-01-01] [--refresh]
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime

import requests

import common
from common import BUILD_DIR, DATA_DIR, HEADERS, RAW_DIR, ROOT, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "nj-echo-monthly"
URL = "https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart"
PARAM = "81381"
AUTHORITY = ("EPA ECHO monthly discharge monitoring report (modeled or measured days per month, "
             "reported weeks to months later)")
DEFAULT_SINCE = "2024-01-01"
SLEEP_S = 1.5
RAW_FIELDS = ("DMRValueId", "DMRValueNmbr", "DMRUnitDesc", "StatisticalBaseDesc", "ValueTypeDesc",
              "NODICode", "NODIDesc", "ValueReceivedDate", "DMRDueDate", "DaysLate", "VersionNmbr", "LimitSetScheduleId")


def permits() -> dict[str, dict]:
    out = {}
    for r in read_json(ROOT / "research/nj/dischargers.json", []) or []:
        if r.get("npdes_permit"):
            out[r["npdes_permit"]] = r
    return out


def cached(permit: str, since: date, month: str) -> tuple[dict | None, str | None]:
    """The raw copy fetched this month (UTC, 'YYYYMM') for this permit and start date, if any."""
    d = RAW_DIR / SOURCE_ID
    for p in sorted(d.glob(f"{month}*.{permit}-{PARAM}.json"), reverse=True):
        try:
            res = json.loads(p.read_text())["Results"]
        except (ValueError, KeyError, OSError):
            continue
        if res.get("Message") == "Success" and res.get("StartDate") == since.strftime("%m/%d/%Y"):
            return res, p.name
    return None, None


def fetch(permit: str, since: date) -> tuple[dict | None, str]:
    params = {"output": "JSON", "p_id": permit, "parameter_code": PARAM,
              "start_date": since.strftime("%m/%d/%Y"), "end_date": date.today().strftime("%m/%d/%Y")}
    err = "not tried"
    for i in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            js = r.json()
            if (js.get("Results") or {}).get("Message") != "Success":
                raise ValueError(str(js)[:200])
            save_raw(SOURCE_ID, r.content, f"{permit}-{PARAM}.json")
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


def outfall_tables() -> tuple[dict, dict]:
    """(permit, ECHO feature number) -> NJDEP layer row, and -> ECHO inventory row (CSO outfalls)."""
    nj = {}
    for o in (read_json(BUILD_DIR / "nj-cso-outfalls.json", {}) or {}).get("outfalls", []):
        if o.get("echo_outfall"):
            nj[(o["npdes_permit"], str(o["echo_outfall"]).upper())] = o
    echo = {}
    for o in (read_json(DATA_DIR / "outfalls-mid-atlantic.json", {}) or {}).get("outfalls", []):
        if str(o.get("npdes_permit", "")).startswith("NJ"):
            echo[(o["npdes_permit"], str(o["outfall"]).upper())] = o
    return nj, echo


def collect(results: dict[str, dict], nj: dict, echo: dict, stats: dict, disc: dict) -> tuple[dict, dict]:
    """(permit, feature, period end, limit set) -> chosen DMR row; and permit -> ECHO facility name."""
    cells: dict[tuple, dict] = {}
    names = {}
    for permit, res in results.items():
        names[permit] = res.get("CWPName")
        for f in res.get("PermFeatures") or []:
            feat = str(f.get("PermFeatureNmbr") or "").upper()
            for par in f.get("Parameters") or []:
                n = len(par.get("DischargeMonitoringReports") or [])
                if "internal" in (par.get("MonitoringLocationDesc") or "").lower():
                    stats["skipped_internal"][f"{permit}:{feat}"] += n
                    continue
                listed = (permit, feat) in nj or (permit, feat) in echo
                if not listed and (disc.get(permit) or {}).get("kind") != "cso":
                    # a treatment plant's own outfall (MCUA 007), not a CSO outfall
                    stats["skipped_not_cso_outfall"][f"{permit}:{feat} ({f.get('PermFeatureTypeDesc')})"] += n
                    continue
                if not listed:
                    stats["unlisted_outfalls_kept"][f"{permit}:{feat}"] += n
                for row in par.get("DischargeMonitoringReports") or []:
                    if not row.get("MonitoringPeriodEndDate"):
                        continue
                    key = (permit, feat, row["MonitoringPeriodEndDate"], row.get("LimitSetScheduleId"))
                    prev = cells.get(key)
                    if prev is None or (prev.get("DMRValueNmbr") in (None, "") and row.get("DMRValueNmbr") not in (None, "")):
                        cells[key] = dict(row, _location=par.get("MonitoringLocationDesc"), _code=par.get("ParameterCode"),
                                          _param=par.get("ParameterDesc"), _feature_type=f.get("PermFeatureTypeDesc"),
                                          _listed=listed)
    return cells, names


def latest_months(cells: dict) -> dict[str, dict]:
    """{"<permit>|<outfall>": {month, discharged, days, received_at}}: each outfall's latest month as the DMRs give it,
    zero-day and "no discharge" (NODI C) months included, which are no events (build/status.py: a newer month of no
    discharge clears an older monthly mark; review 2026-11-03 SOL P2-7). Other NODI codes and empty values say
    nothing and are left out."""
    out: dict[str, dict] = {}
    for (permit, feat, pend, _ls), row in cells.items():
        try:
            _s, _e, ym = month_bounds(pend)
        except ValueError:
            continue
        days = num(row.get("DMRValueNmbr"))
        if row.get("NODICode") or row.get("NODIDesc"):
            if str(row.get("NODICode") or "").upper() != "C":
                continue
            days = 0.0
        if days is None:
            continue
        k = f"{permit}|{feat}"
        cur = out.get(k)
        if cur is None or ym > cur["month"] or (ym == cur["month"] and days > (cur["days"] or 0)):
            out[k] = {"month": ym, "discharged": days > 0, "days": days, "received_at": ddmon(row.get("ValueReceivedDate"))}
    return dict(sorted(out.items()))


def build_records(cells: dict, names: dict, disc: dict, nj: dict, echo: dict, stats: dict) -> list[dict]:
    sets: dict[tuple, list] = defaultdict(list)
    for (permit, feat, pend, ls) in cells:
        if ls not in sets[(permit, feat, pend)]:
            sets[(permit, feat, pend)].append(ls)
    for k in sets:
        sets[k].sort(key=lambda x: str(x))
    records = []
    for (permit, feat, pend, ls), row in sorted(cells.items()):
        try:
            start, end, ym = month_bounds(pend)
        except ValueError:
            stats["unparsed_period"][f"{permit}:{feat}:{pend}"] += 1
            continue
        days = num(row.get("DMRValueNmbr"))
        if row.get("NODICode") or row.get("NODIDesc"):
            stats["nodi_months"][f"{permit}: {row.get('NODIDesc') or row.get('NODICode')}"] += 1
            continue
        if days is None:
            stats["no_value_months"][permit] += 1
            continue
        if days <= 0:
            stats["zero_day_months"][permit] += 1
            continue
        o, e = nj.get((permit, feat)), echo.get((permit, feat))
        same = sets[(permit, feat, pend)]
        srid = f"{permit}:{feat}:{ym}" + (f":{same.index(ls) + 1}" if len(same) > 1 else "")
        unit = row.get("DMRUnitDesc") or ""
        if unit == "d":
            vtext = f"{days:g} day{'s' if days != 1 else ''} with discharge in {ym} ({row.get('StatisticalBaseDesc') or 'monthly'})"
        else:
            vtext = f"{days:g} {unit} duration of discharge in {ym} ({row.get('StatisticalBaseDesc') or 'monthly'})"
        if o and o.get("water_slug"):
            slugs, how = [o["water_slug"]], o.get("water_match") or "outfall_registry"
        elif e and e.get("water_slug"):
            slugs, how = [e["water_slug"]], "outfall_registry"
        else:
            slugs, how = [], "none"
        lat = (o or {}).get("lat") if (o or {}).get("lat") is not None else (e or {}).get("lat")
        lon = (o or {}).get("lon") if (o or {}).get("lat") is not None else (e or {}).get("lon")
        d = disc.get(permit, {})
        raw = {"month": ym, "permit_feature": feat, "feature_type": row.get("_feature_type"),
               "monitoring_location": row.get("_location"), "parameter": row.get("_param"),
               "parameter_code": row.get("_code"),
               "dmr": {k: row.get(k) for k in RAW_FIELDS},
               "njdep_outfall_id": (o or {}).get("outfall_id"), "njdep_outfall_status": (o or {}).get("status"),
               "receiving_water_echo": (e or {}).get("receiving_water_echo"),
               "note": "monthly DMR total of days with a discharge (modeled or measured), not an individual event"}
        if not row.get("_listed"):
            raw["outfall_note"] = "outfall not in the NJDEP CSO layer or the ECHO CSO inventory; reported under a CSO permit"
        records.append(event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="cso", status="ended",
            discharger_id=d.get("id"), discharger_name=d.get("name") or names.get(permit), npdes_permit=permit,
            outfall_id=feat, outfall_name=(o or {}).get("outfall_name") or (e or {}).get("outfall_name") or None,
            waterbody_text=(o or {}).get("receiving_water") or (e or {}).get("receiving_water_echo"),
            water_slugs=slugs, water_match=how, lat=lat, lon=lon,
            coord_source="outfall_layer" if lat is not None else None,
            started_at=start, ended_at=end, time_precision="month", reported_at=ddmon(row.get("ValueReceivedDate")),
            material="combined sewage and stormwater", volume_text=vtext, estimate_flag="unknown",
            authority=AUTHORITY, source_url=f"https://echo.epa.gov/effluent-charts#{permit}", raw=raw,
        ))
    records.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--refresh", action="store_true", help="ignore this month's cached responses")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since)
    month = datetime.now(UTC).strftime("%Y%m")

    disc = permits()
    results, fetch_log = {}, {}
    for i, permit in enumerate(disc):
        res, name = (None, None) if args.refresh else cached(permit, since, month)
        if res is not None:
            results[permit], fetch_log[permit] = res, f"cache ({name})"
            continue
        if i and any(v == "live" for v in fetch_log.values()):
            time.sleep(SLEEP_S)
        res, how = fetch(permit, since)
        fetch_log[permit] = how
        if res is not None:
            results[permit] = res

    if not results:
        write_events(SOURCE_ID, [], ok=False, error=f"all requests failed: {fetch_log}")
        print(f"{SOURCE_ID}: all requests failed", file=sys.stderr)
        return 1

    nj, echo = outfall_tables()
    stats = defaultdict(Counter)
    cells, names = collect(results, nj, echo, stats, disc)
    records = build_records(cells, names, disc, nj, echo, stats)
    per_permit = Counter(r["npdes_permit"] for r in records)
    meta = {"registry_ids": ["nj-echo-effluent-dmr-cso", "fed-echo-effluent-charts-rest"], "since": args.since,
            "parameter": f"{PARAM} Duration of discharge (days per month)", "permits": sorted(disc),
            "fetch": fetch_log, "records_per_permit": dict(per_permit),
            "permits_without_records": sorted(set(disc) - set(per_permit)),
            **{k: dict(v) for k, v in stats.items()},
            "cadence": "monthly cache per permit; DMRs reach ECHO weeks to months after the month",
            "latest_month_by_outfall": latest_months(cells),
            "history_only": "month precision: never colours a water"}
    failed = {k: v for k, v in fetch_log.items() if v.startswith("failed")}
    if failed:
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
    print(f"{SOURCE_ID}: {len(records)} outfall-months from {len(per_permit)} permits -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
