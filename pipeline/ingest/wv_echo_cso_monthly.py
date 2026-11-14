"""Monthly flow at West Virginia combined sewer outlets from EPA ECHO Discharge Monitoring Reports (registry:
wv-echo-dmr-cso) -> data/build/events/wv-echo-dmr-cso.json.

Source
  ECHO Effluent Charts REST service (also fed-echo-effluent-charts-rest),
  https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart?output=JSON&p_id=<permit>&parameter_code=50050
  &start_date=MM/DD/YYYY&end_date=MM/DD/YYYY, no key. What West Virginia's CSO permits put on a monthly report was read
  on 2026-11-14 for every one of the 61 permits with an open CSO outlet in DEP's layer (one request per permit, all
  parameters, January 2025 to date): 59 file nothing at any CSO outlet (their reports cover the treatment plant's own
  outfalls only); two file a monthly line at outlet C002, 'Effluent Gross': Princeton Sanitary Board (WV0023094) and
  the City of Beckley (WV0023183), each with 50050 'Flow, in conduit or thru treatment plant' (MGD), total residual
  chlorine and fecal coliform. No West Virginia permit reports a number of overflow events, hours or volume at a CSO
  outlet. So this feed reads 50050 per permit: it shows, for the outlets that report one, the months in which the
  operator reported flow leaving the outlet.

Permits
  Every West Virginia permit with an open combined sewer outlet in the outfall registry (common.load_outfall_registry:
  DEP's layer in data/outfalls-wv.json); 61 on 2026-11-14. Only lines at an outlet the registry holds as a CSO outlet
  of that permit are read; the plant's own outfalls are skipped (counted in meta).

Records
  One per permit + outlet + month in which a flow above zero is reported (any statistical base): event_type cso,
  status ended, started_at the first and ended_at the last day of the month (time_precision month, Eastern time),
  reported_at the DMR's ValueReceivedDate, volume_gal null (the figure is a rate in MGD, not a monthly total),
  volume_text 'flow reported at outlet C002 in YYYY-MM: 0.342 MGD (minimum); monthly report, not an event'. These are
  monthly figures, not events: the status build gives them the monthly mark and never red or yellow (time_precision
  month; build/status.py EPA_MONTHLY_SOURCES). A month filed NODI C ('No Discharge') or with every value zero is no
  record; it is counted in meta and kept per outlet in meta.latest_month_by_outfall (a newer month of no discharge
  clears an older monthly mark). Other NODI codes and empty values say nothing. The point, receiving water and water
  record come from the registry row.

Cache and cadence
  Each answer is compacted to the CSO outlets' 50050 lines and kept in data/build/wv-echo-dmr-cso-cache.json (data/build
  is kept between cloud runs); a permit is asked again when its answer is older than CACHE_DAYS (7), at most
  MAX_LIVE_REQUESTS (25) a run, oldest first, so ECHO is asked about once a week per permit. DMRs reach ECHO two to
  eight weeks after the month.

Failures
  A permit whose request fails three times keeps its cached answer and is named in meta.fetch; a run in which every
  request asked fails is ok=False and the previous records stay. A permit ECHO calls invalid is 'not in ECHO', no
  failure. The answers name the facility (a public plant), no person.

Run from pipeline/:  python -m ingest.wv_echo_cso_monthly [--since 2025-01-01] [--refresh] [--cache FILE]
"""
from __future__ import annotations

import argparse
import calendar
import json
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

import common
from common import BUILD_DIR, HEADERS, event, now_iso, read_json, write_events, write_json

SOURCE_ID = "wv-echo-dmr-cso"
URL = "https://echodata.epa.gov/echo/eff_rest_services.get_effluent_chart"
PARAM = "50050"
AUTHORITY = ("EPA ECHO discharge monitoring reports (the operator's own monthly report to West Virginia DEP; "
             "published weeks after the month)")
TZ = "America/New_York"
DEFAULT_SINCE = "2025-01-01"
CACHE_DAYS = 7
MAX_LIVE_REQUESTS = 25
CACHE_FILE = BUILD_DIR / "wv-echo-dmr-cso-cache.json"
REQUEST_TIMEOUT = (10, 60)
KEEP = ("MonitoringPeriodEndDate", "DMRValueNmbr", "DMRUnitDesc", "StatisticalBaseDesc", "NODICode", "NODIDesc",
        "ValueReceivedDate", "DMRValueId", "VersionNmbr", "LimitSetScheduleId")


def norm(o) -> str:
    return common.outfall_key("X", o)[1]


def cso_outlets() -> dict[str, dict[str, dict]]:
    """permit -> {outlet key: registry row} for West Virginia's open CSO outlets."""
    out: dict[str, dict[str, dict]] = {}
    for r in common.load_outfall_registry(provisional=False):
        if r.get("state") != "WV" or r.get("outfall_kind") != "cso" or common._closed(r):
            continue
        out.setdefault(r["npdes_permit"], {})[norm(r.get("outfall"))] = r
    return out


def compact(results: dict, outlets: dict[str, dict]) -> dict:
    """The answer's lines at the permit's CSO outlets, and the count of lines skipped."""
    lines, skipped = {}, 0
    for f in results.get("PermFeatures") or []:
        num = f.get("PermFeatureNmbr")
        for p in f.get("Parameters") or []:
            if p.get("ParameterCode") != PARAM:
                continue
            rows = p.get("DischargeMonitoringReports") or []
            if norm(num) not in outlets:
                skipped += len(rows)
                continue
            if "gross" not in str(p.get("MonitoringLocationDesc") or "").lower():
                skipped += len(rows)
                continue
            lines.setdefault(num, []).extend({k: r.get(k) for k in KEEP} for r in rows)
    return {"name": results.get("CWPName"), "lines": lines, "skipped_non_cso": skipped}


def fetch(permit: str, since: date) -> tuple[dict | None, str]:
    params = {"output": "JSON", "p_id": permit, "parameter_code": PARAM,
              "start_date": since.strftime("%m/%d/%Y"), "end_date": date.today().strftime("%m/%d/%Y")}
    err = "not asked"
    for i in range(3):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            res = r.json().get("Results") or {}
            msg = str(res.get("Message") or "")
            if "invalid" in msg.lower():
                return None, "not in ECHO"
            if msg != "Success":
                raise ValueError(msg[:200])
            return res, "live"
        except (requests.RequestException, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(3 * (i + 1))
    return None, f"failed ({err})"


def ddmon(s) -> date | None:
    try:
        return datetime.strptime(s, "%d-%b-%y").date() if s else None
    except ValueError:
        return None


def num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def build(cache: dict, outlets: dict[str, dict[str, dict]]) -> tuple[list[dict], dict]:
    records, no_dis, latest, lags = [], Counter(), {}, []
    for permit, entry in sorted((cache.get("permits") or {}).items()):
        for outlet, rows in sorted((entry.get("lines") or {}).items()):
            reg = (outlets.get(permit) or {}).get(norm(outlet))
            months: dict[str, list[dict]] = {}
            for r in rows:
                d = ddmon(r.get("MonitoringPeriodEndDate"))
                if d:
                    months.setdefault(d.strftime("%Y-%m"), []).append(r)
            for ym, rs in sorted(months.items()):
                vals = [(num(r.get("DMRValueNmbr")), r) for r in rs]
                said = [v for v, _ in vals if v is not None] + [0.0 for r in rs if str(r.get("NODICode") or "") == "C"]
                received = max(filter(None, (ddmon(r.get("ValueReceivedDate")) for r in rs)), default=None)
                if said:
                    k = f"{permit}|{outlet}"
                    if k not in latest or ym > latest[k]["month"]:
                        latest[k] = {"month": ym, "discharged": any(v > 0 for v in said), "events": None,
                                     "received_at": received.isoformat() if received else None}
                pos = [(v, r) for v, r in vals if v is not None and v > 0]
                if not pos:
                    if said:
                        no_dis[permit] += 1
                    continue
                y, m = map(int, ym.split("-"))
                first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
                if received:
                    lags.append((received - last).days)
                parts = "; ".join(f"{r.get('DMRValueNmbr')} {r.get('DMRUnitDesc') or ''} ({str(r.get('StatisticalBaseDesc') or '').lower()})".replace(" (", " (", 1)
                                  for _, r in sorted(pos, key=lambda x: str(x[1].get("StatisticalBaseDesc"))))
                records.append(event(
                    source_id=SOURCE_ID, source_record_id=f"{permit}:{outlet}:{ym}", event_type="cso", status="ended",
                    discharger_name=(reg or {}).get("permittee") or entry.get("name"), npdes_permit=permit,
                    outfall_id=outlet, waterbody_text=(reg or {}).get("receiving_water_echo"),
                    water_slugs=[reg["water_slug"]] if reg and reg.get("water_slug") else [],
                    water_match="outfall_registry" if reg and reg.get("water_slug") else "none",
                    lat=(reg or {}).get("lat"), lon=(reg or {}).get("lon"),
                    coord_source="outfall_layer" if reg and reg.get("lat") is not None else None,
                    started_at=first.isoformat(), ended_at=last.isoformat(), time_precision="month",
                    reported_at=received.isoformat() if received else None,
                    material="combined sewage and stormwater", volume_gal=None,
                    volume_text=f"flow reported at outlet {outlet} in {ym}: {parts}; monthly report, not an event",
                    estimate_flag="unknown", authority=AUTHORITY,
                    source_url=f"https://echo.epa.gov/effluent-charts#{permit}",
                    raw={"month": ym, "permit_feature": outlet, "parameter": PARAM,
                         "lines": [{k: r.get(k) for k in KEEP} for r in rs], "time_zone": TZ,
                         "note": "monthly DMR flow at a combined sewer outlet (a rate in MGD), not an individual event"}))
    records.sort(key=lambda r: (r["started_at"], r["event_id"]), reverse=True)
    meta = {"no_discharge_months": dict(no_dis), "latest_month_by_outfall": dict(sorted(latest.items())),
            "median_days_month_end_to_receipt": statistics.median(lags) if lags else None}
    return records, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--cache", help="read this cache file and ask nothing (tests)")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since)
    outlets = cso_outlets()
    path = Path(args.cache) if args.cache else CACHE_FILE
    cache = read_json(path, {}) or {}
    if cache.get("since") != args.since:
        cache = {"since": args.since, "permits": {}}
    fetch_log: dict[str, str] = {}
    if not args.cache:
        now = datetime.now(UTC)
        due = sorted(outlets, key=lambda p: (cache["permits"].get(p) or {}).get("asked_at") or "")
        asked = 0
        for p in due:
            prev = (cache["permits"].get(p) or {}).get("asked_at")
            if prev and not args.refresh and now - datetime.fromisoformat(prev.replace("Z", "+00:00")) < timedelta(days=CACHE_DAYS):
                continue
            if asked >= MAX_LIVE_REQUESTS:
                fetch_log[p] = "not asked this run (request budget)"
                continue
            asked += 1
            res, how = fetch(p, since)
            fetch_log[p] = how
            if res is not None:
                cache["permits"][p] = {**compact(res, outlets[p]), "asked_at": now_iso()}
            elif how == "not in ECHO":
                cache["permits"][p] = {"name": None, "lines": {}, "asked_at": now_iso(), "not_in_echo": True}
            time.sleep(1)
        write_json(path, cache)
    records, meta = build(cache, outlets)
    meta.update({"registry_ids": [SOURCE_ID], "since": args.since,
                 "permits_asked": len(outlets), "fetch": fetch_log,
                 "permits_with_cso_lines": sorted(p for p, e in cache["permits"].items() if e.get("lines")),
                 "cadence": "weekly per permit; DMRs reach ECHO weeks after the month"})
    tried = [v for v in fetch_log.values() if not v.startswith("not asked")]
    if tried and all(v.startswith("failed") for v in tried):
        write_events(SOURCE_ID, [], ok=False, error=f"every request failed: {fetch_log}", meta=meta)
        print(f"{SOURCE_ID}: every request failed; the previous records are kept", file=sys.stderr)
        return 1
    out = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} outlet-months -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
