"""Monthly CSO figures per Indiana outfall from EPA ECHO Discharge Monitoring Reports (registry: in-echo-dmr-cso).

Source
  ECHO Effluent Charts REST service (also fed-echo-effluent-charts-rest),
  https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart?output=JSON&p_id=<permit>
  &parameter_code=<code>&start_date=MM/DD/YYYY&end_date=MM/DD/YYYY, no key. 327 IAC 5-2.1-7 has every Indiana CSO
  community document its overflows on a monthly CSO discharge monitoring report; IDEM's permits ask, per CSO outfall
  ('Effluent Gross'), three monthly totals (read 2026-11-14 on LaPorte, South Bend, Fort Wayne, Gary and Indianapolis):
    84165 'Discharge event observation [Visual Monitoring]'  MO TOTAL  #/mo   (the number of discharge events)
    50037 'Duration'                                          MO TOTAL  hr/mo  (hours of discharge)
    74063 'Overflow volume [SS0 volume, CSO volume]'          MO TOTAL  Mgal   (million gallons)
  A month with no overflow is filed NODI C ('No Discharge'). One request per permit and parameter, a short sleep
  between them; each answer is kept with common.save_raw (data/raw/in-echo-dmr-cso/<stamp>.<permit>-<code>.json) and
  doubles as the cache: a run reuses a copy fetched in the last CACHE_DAYS days with the same start date (--refresh
  asks again), so ECHO is asked about once a week per permit.

Permits
  Every Indiana permit with at least one open combined sewer outfall in the outfall registry (every data/outfalls-*.json
  through common.load_outfall_registry: IDEM's layer in data/outfalls-in.json, else EPA's inventory), 90 on 2026-11-14.

Records
  One per permit + outfall + month in which any of the three figures is above zero: event_type cso, status ended,
  started_at the first and ended_at the last day of the month, time_precision month, reported_at the DMR's
  ValueReceivedDate (the day EPA received it), volume_gal the month's million gallons times 1,000,000 when given,
  volume_text 'N discharge events, H hours, V million gallons in YYYY-MM (monthly DMR totals)'. These are monthly
  totals, not events: the status build gives them the monthly mark and never red or yellow (time_precision month;
  build/status.py EPA_MONTHLY_SOURCES), and the charts never add them to the discharge counts. NODI C months and months
  with every figure zero are not records; they are counted in meta and kept per outfall in
  meta.latest_month_by_outfall (a newer month of no discharge clears an older monthly mark). Other NODI codes and empty
  values say nothing. Only 'Effluent Gross' lines at external outfalls of the registry's CSO rows are read; a plant's
  own outfall and an internal monitoring point are counted in meta and skipped. raw.time_zone is the outfall's county's
  zone (zones.indiana_zone: the month is a calendar month on that clock); the point, receiving water and water record
  come from the registry row.

Lag and cadence
  DMRs are due on the 28th of the following month in Indiana and ECHO refreshes weekly, so a month appears four to eight
  weeks after it ends (the median lag is measured from ValueReceivedDate and kept in meta.median_days_month_end_to_receipt).
  The request covers --since (default 2025-01-01) to today, so late and revised DMRs are picked up.

Failures
  A permit whose requests fail three times is named in meta.fetch; the run is ok=False and the previous records stay
  (a first run with nothing to keep writes what it has, still ok=False). Each try waits at most REQUEST_TIMEOUT s; after
  MAX_CONSECUTIVE_FAILURES failed tries in a row the run asks nothing more.

Run from pipeline/:  python -m ingest.in_echo_cso_monthly [--since 2025-01-01] [--refresh]
"""
from __future__ import annotations

import argparse
import calendar
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime

import requests

import common
import zones
from common import DATA_DIR, HEADERS, RAW_DIR, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "in-echo-dmr-cso"
URL = "https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart"
PARAMS = {"84165": "events", "50037": "hours", "74063": "volume"}
AUTHORITY = ("EPA ECHO discharge monitoring reports (the operator's own monthly CSO totals, filed with IDEM; "
             "reported weeks after the month)")
DEFAULT_SINCE = "2025-01-01"
SLEEP_S = 1.0
CACHE_DAYS = 7
REQUEST_TIMEOUT = 60
MAX_CONSECUTIVE_FAILURES = 5
MGAL = {"Mgal": 1_000_000, "MG": 1_000_000, "MG/mo": 1_000_000, "gal": 1, "gal/mo": 1}
RAW_FIELDS = ("DMRValueId", "DMRValueNmbr", "DMRUnitDesc", "StatisticalBaseDesc", "NODICode", "NODIDesc",
              "ValueReceivedDate", "DMRDueDate", "DaysLate", "VersionNmbr", "LimitSetScheduleId")


def registry_outfalls(rows: list[dict] | None = None) -> dict[tuple[str, str], dict]:
    """(permit, outfall key) -> the registry row of every Indiana combined sewer outfall (open or closed)."""
    rows = common.load_outfall_registry(provisional=False) if rows is None else rows
    out = {}
    for r in rows:
        if r.get("state") != "IN" or str(r.get("outfall_kind") or "cso") != "cso":
            continue
        out[common.outfall_key(r.get("npdes_permit"), r.get("outfall"))] = r
    return out


def permits_to_read(reg: dict) -> list[str]:
    """Permits with at least one open combined sewer outfall in the registry."""
    return sorted({p for (p, _), r in reg.items() if not str(r.get("outfall_status") or "").upper().startswith("CLS")})


def dischargers() -> dict[str, dict]:
    out = {}
    for d in read_json(DATA_DIR / "dischargers.json", []) or []:
        if d.get("state") != "IN":
            continue
        for p in d.get("npdes_permits") or [d.get("npdes_permit")]:
            if p:
                out.setdefault(p, d)
    return out


def cached(permit: str, code: str, since: date, today: date) -> tuple[dict | None, str | None]:
    """A copy fetched in the last CACHE_DAYS days for this permit, parameter and start date, if any."""
    d = RAW_DIR / SOURCE_ID
    if not d.exists():
        return None, None
    for p in sorted(d.glob(f"*.{permit}-{code}.json"), reverse=True):
        try:
            stamp = datetime.strptime(p.name[:8], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - stamp).days > CACHE_DAYS:
            continue
        try:
            res = json.loads(p.read_text())["Results"]
        except (ValueError, KeyError, OSError):
            continue
        if res.get("Message") == "Success" and res.get("StartDate") == since.strftime("%m/%d/%Y"):
            return res, p.name
    return None, None


def fetch(permit: str, code: str, since: date) -> tuple[dict | None, str]:
    params = {"output": "JSON", "p_id": permit, "parameter_code": code,
              "start_date": since.strftime("%m/%d/%Y"), "end_date": date.today().strftime("%m/%d/%Y")}
    err = "not tried"
    for i in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
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


def collect(results: dict[tuple[str, str], dict], reg: dict, stats: dict) -> tuple[dict, dict]:
    """(permit, feature, month) -> {param: DMR row}; and permit -> ECHO facility name. results is keyed (permit, code)."""
    cells: dict[tuple, dict] = defaultdict(dict)
    names = {}
    for (permit, code), res in results.items():
        names[permit] = res.get("CWPName")
        for f in res.get("PermFeatures") or []:
            feat = str(f.get("PermFeatureNmbr") or "").upper()
            for par in f.get("Parameters") or []:
                if str(par.get("ParameterCode")) not in PARAMS:
                    continue
                rows = par.get("DischargeMonitoringReports") or []
                if "gross" not in str(par.get("MonitoringLocationDesc") or "").lower() or \
                        "external" not in str(f.get("PermFeatureTypeDesc") or "external").lower():
                    stats["skipped_not_effluent_gross"][f"{permit}:{feat}"] += len(rows)
                    continue
                if common.outfall_key(permit, feat) not in reg:
                    stats["skipped_not_cso_outfall"][f"{permit}:{feat}"] += len(rows)
                    continue
                name = PARAMS[str(par["ParameterCode"])]
                for row in rows:
                    pend = row.get("MonitoringPeriodEndDate")
                    if not pend:
                        continue
                    try:
                        ym = month_bounds(pend)[2]
                    except ValueError:
                        stats["unparsed_period"][f"{permit}:{feat}:{pend}"] += 1
                        continue
                    prev = cells[(permit, feat, ym)].get(name)
                    if prev is None or (num(prev.get("DMRValueNmbr")) is None and num(row.get("DMRValueNmbr")) is not None) \
                            or (num(row.get("DMRValueNmbr")) or 0) > (num(prev.get("DMRValueNmbr")) or 0):
                        cells[(permit, feat, ym)][name] = dict(row, _pend=pend, _param=par.get("ParameterDesc"))
    return dict(cells), names


def figures(cell: dict) -> dict:
    """{events, hours, volume_mgal, no_discharge, received, unit_volume} of one outfall-month."""
    out = {"no_discharge": False, "received": None}
    vals = {}
    for name, row in cell.items():
        if str(row.get("NODICode") or "").upper() == "C":
            vals[name] = 0.0
            out["no_discharge"] = True
        elif row.get("NODICode") or row.get("NODIDesc"):
            continue
        else:
            v = num(row.get("DMRValueNmbr"))
            if v is not None:
                vals[name] = v
        rec = ddmon(row.get("ValueReceivedDate"))
        if rec and (out["received"] is None or rec > out["received"]):
            out["received"] = rec
    out["events"], out["hours"] = vals.get("events"), vals.get("hours")
    vol = vals.get("volume")
    unit = (cell.get("volume") or {}).get("DMRUnitDesc") or "Mgal"
    out["volume_gal"] = round(vol * MGAL[unit]) if vol is not None and unit in MGAL else None
    out["volume_mgal"] = vol if unit in ("Mgal", "MG", "MG/mo") else None
    out["volume_raw"] = None if vol is None else f"{vol:g} {unit}"
    out["any"] = any((x or 0) > 0 for x in (out["events"], out["hours"], vol))
    out["said"] = bool(vals)
    return out


def volume_text(fg: dict, ym: str) -> str:
    parts = []
    if fg["events"] is not None:
        n = fg["events"]
        parts.append(f"{n:g} discharge event{'s' if n != 1 else ''}")
    if fg["hours"] is not None:
        parts.append(f"{fg['hours']:g} hours")
    if fg["volume_mgal"] is not None:
        parts.append(f"{fg['volume_mgal']:g} million gallons")
    elif fg["volume_raw"]:
        parts.append(fg["volume_raw"])
    return ", ".join(parts) + f" in {ym} (monthly DMR totals)"


def latest_months(cells: dict) -> dict[str, dict]:
    """{"<permit>|<outfall>": {month, discharged, events, received_at}}: each outfall's latest month the DMRs speak of,
    no-discharge months included (build/status.py latest_observations)."""
    out: dict[str, dict] = {}
    for (permit, feat, ym), cell in cells.items():
        fg = figures(cell)
        if not fg["said"]:
            continue
        k = f"{permit}|{feat}"
        cur = out.get(k)
        if cur is None or ym > cur["month"]:
            out[k] = {"month": ym, "discharged": fg["any"], "events": fg["events"], "received_at": fg["received"]}
    return dict(sorted(out.items()))


def build_records(cells: dict, names: dict, reg: dict, disc: dict, stats: dict) -> list[dict]:
    records = []
    for (permit, feat, ym), cell in sorted(cells.items()):
        fg = figures(cell)
        if not fg["said"]:
            stats["no_value_months"][permit] += 1
            continue
        if not fg["any"]:
            stats["no_discharge_months"][permit] += 1
            continue
        pend = next(iter(cell.values()))["_pend"]
        start, end, _ = month_bounds(pend)
        o = reg.get(common.outfall_key(permit, feat)) or {}
        d = disc.get(permit) or {}
        lat, lon = o.get("lat"), o.get("lon")
        slug = o.get("water_slug")
        tz = zones.indiana_zone(county=o.get("county"), lat=lat, lon=lon)
        raw = {"month": ym, "permit_feature": feat,
               "events": fg["events"], "hours": fg["hours"], "volume": fg["volume_raw"],
               "dmr": {name: {k: row.get(k) for k in RAW_FIELDS} | {"parameter": row.get("_param")}
                       for name, row in sorted(cell.items())},
               "receiving_water_registry": o.get("receiving_water_echo"),
               "outfall_registry_file": o.get("_file"), "outfall_status": o.get("outfall_status"),
               "county": o.get("county"), "time_zone": tz,
               "note": ("the operator's monthly DMR totals for this outfall (events, hours, million gallons), not an "
                        "individual discharge: no day is given")}
        records.append(event(
            source_id=SOURCE_ID, source_record_id=f"{permit}:{feat}:{ym}", event_type="cso", status="ended",
            discharger_id=d.get("id"), discharger_name=d.get("name") or names.get(permit), npdes_permit=permit,
            outfall_id=feat, outfall_name=o.get("outfall_name"),
            waterbody_text=o.get("receiving_water_echo"),
            water_slugs=[slug] if slug else [], water_match="outfall_registry" if slug else "none",
            lat=lat, lon=lon, coord_source="outfall_registry" if lat is not None else None,
            started_at=start, ended_at=end, time_precision="month", reported_at=fg["received"],
            material="combined sewage and stormwater", volume_gal=fg["volume_gal"],
            volume_text=volume_text(fg, ym), estimate_flag="unknown",
            authority=AUTHORITY, source_url=f"https://echo.epa.gov/effluent-charts#{permit}", raw=raw,
        ))
    records.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    return records


def median_lag_days(records: list[dict]) -> float | None:
    lags = []
    for r in records:
        try:
            lags.append((date.fromisoformat(r["reported_at"]) - date.fromisoformat(r["ended_at"])).days)
        except (TypeError, ValueError):
            continue
    return statistics.median(lags) if lags else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--refresh", action="store_true", help="ignore the cached responses")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since)
    today = datetime.now(UTC).date()

    reg = registry_outfalls()
    permits = permits_to_read(reg)
    results, fetch_log = {}, {}
    failures_in_a_row, stopped = 0, False
    for permit in permits:
        for code in PARAMS:
            key = f"{permit}-{code}"
            res, name = (None, None) if args.refresh else cached(permit, code, since, today)
            if res is not None:
                results[(permit, code)], fetch_log[key] = res, f"cache ({name})"
                continue
            if stopped:
                fetch_log[key] = f"failed (not asked: stopped after {MAX_CONSECUTIVE_FAILURES} failures)"
                continue
            if any(v == "live" for v in fetch_log.values()):
                time.sleep(SLEEP_S)
            res, how = fetch(permit, code, since)
            fetch_log[key] = how
            if res is None:
                failures_in_a_row += 1
                stopped = failures_in_a_row >= MAX_CONSECUTIVE_FAILURES
            else:
                failures_in_a_row = 0
                results[(permit, code)] = res

    if not results:
        write_events(SOURCE_ID, [], ok=False, error="all requests failed")
        print(f"{SOURCE_ID}: all requests failed", file=sys.stderr)
        return 1

    stats = defaultdict(Counter)
    cells, names = collect(results, reg, stats)
    records = build_records(cells, names, reg, dischargers(), stats)
    per_permit = Counter(r["npdes_permit"] for r in records)
    meta = {"registry_ids": [SOURCE_ID, "fed-echo-effluent-charts-rest"], "since": args.since,
            "parameters": {c: n for c, n in PARAMS.items()}, "permits": permits,
            "fetch": fetch_log, "records_per_permit": dict(sorted(per_permit.items())),
            "permits_without_records": sorted(set(permits) - set(per_permit)),
            "median_days_month_end_to_receipt": median_lag_days(records),
            **{k: dict(v) for k, v in stats.items()},
            "cadence": f"cached per permit and parameter for {CACHE_DAYS} days; DMRs reach ECHO weeks after the month",
            "latest_month_by_outfall": latest_months(cells),
            "history_only": "month precision: the monthly mark, never red or yellow"}
    failed = {k: v for k, v in fetch_log.items() if v.startswith("failed")}
    if failed:
        err = f"{len(failed)} requests failed: " + "; ".join(f"{k} {v}" for k, v in list(failed.items())[:10])
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
