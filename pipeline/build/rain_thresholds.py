"""Rainfall thresholds for the "discharge likely; no report received" caution (docs/rain-likely.md).

    python -m build.rain_thresholds [--offline] [--min-days 10]
    python -m build.rain_thresholds --radar MI GA [--budget 1200] [--events MI=path.json]   (one-off, by hand)

From the Massachusetts sewage notification records (data/build/events/ma-massdep.json), for each
permittee and, where the data allow, each outfall: the rainfall at which discharges have
historically happened. Verified Data Reports carry the permittee's own rainfall figure
(`raw.rainfallData`, inches, as typed by the permittee: parsed when it is a plain number of zero or
more, kept as text otherwise).

  discharge day   a local calendar day touched by any discharge notice of the permittee (any
                  report class, any type, from its start to its reported end). Its rainfall is
                  the smallest positive figure the permittee reported for a wet-weather discharge
                  (CSO, blended, bypass) starting that day: the cautious reading when outfalls
                  disagree. A figure of 0.00 is a dry-weather discharge (counted, not a sample:
                  rainfall cannot predict it). Sanitary sewer overflows mark the day but give no
                  sample (blockages and breaks are not rain-driven).
  no-discharge    a day with no notice in a month the permittee closed (it filed Verified Data
  day             Reports for that month, or the portal's "No Events for the month" attestation),
                  between its first record and the end of its latest closed month.
  threshold       the 10th percentile of rainfall on discharge days (nine discharge days in ten
                  had more rain), when there are at least --min-days samples; otherwise the
                  published fallback in data/rules.json rain_likely.fallback (by state).

Rainfall on no-discharge days is not in the notices, so it comes from NOAA MRMS daily totals at
the permittee's outfalls (centroid), as served by the Iowa Environmental Mesonet's reanalysis
point service (https://mesonet.agron.iastate.edu/iemre/; one request per point per year, cached in
data/raw/iem-iemre/, the current year refreshed daily). The same series gives MRMS rainfall on
discharge days, to compare the permittee's gauge with the radar estimate the live check uses.

Writes data/build/rain-thresholds.json ({built, method, fallbacks, permits: {permit: {...}}}) and
data/build/rain-thresholds.md (what the data show for Springfield, Holyoke and Chicopee).
Every CSO permittee with outfalls in the registries gets a row: history where there is enough,
the published fallback otherwise.

Georgia and Michigan (--radar, 2026-11-06): their lists carry no rainfall figure that reads as a 24-hour total
(Michigan's precipitationAmount is the operator's figure for the event, often a storm total; Georgia's list has
none), so an operator's amount is the 10th percentile of the MRMS daily radar total at its median outfall point on
the days its reported combined sewer discharges began (the larger of that day's total and the day before's:
day_radar), from 2015, the first full year of the operational MRMS product (RADAR_FIRST_DAY; Michigan: CSO and RTB
discharges on the EGLE MiEnviro list, read back to 2001; Georgia: the combined sewer permits' reports on the EPD
spills list), with the same 10-day minimum. The point service
is asked once per point and year within a request budget (a refusal stops the run and nothing is written), and the
result is data/rain-thresholds-radar.json, tracked in git; build() lays it over the fallback rows every hour
(merge_radar), never over an operator's own reported rainfall.
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import statistics
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, RAW_DIR, now_iso, read_json, write_json

OUT_JSON = BUILD_DIR / "rain-thresholds.json"
OUT_MD = BUILD_DIR / "rain-thresholds.md"
IEM_DIR = RAW_DIR / "iem-iemre"
IEM_URL = "https://mesonet.agron.iastate.edu/iemre/multiday/{d1}/{d2}/{lat:.2f}/{lon:.2f}/json"
IEM_PAUSE_S = 1.0
MIN_DAYS = 10
PERCENTILE = 0.10
WET_TYPES = {"cso", "blended", "bypass", "plant_bypass"}
DISCHARGE_TYPES = WET_TYPES | {"sso"}
MAX_SPAN_DAYS = 7          # a reported end further than this from the start marks only the first week
MAX_PLAUSIBLE_IN = 12.0    # a day's figure above this is a typing error (the Massachusetts 24-hour record is about 18 in)
MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}
NUM = re.compile(r"^\s*(\d+(?:\.\d+)?|\.\d+)\s*(?:in|in\.|inch|inches|\")?\s*$", re.I)
FOCUS = {"MA0101613": "Springfield", "MA0101630": "Holyoke", "MA0101508": "Chicopee"}


# ---------------------------------------------------------------- pure helpers

def parse_rain(text) -> float | None:
    """'0.43', '1', '.5', '0.43 in' -> inches; '', None, '-1.00', 'trace', '0.5-0.7', '35.52' (more
    than MAX_PLAUSIBLE_IN) -> None (the caller keeps the text)."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        v = float(text)
    else:
        m = NUM.match(str(text))
        if not m:
            return None
        v = float(m.group(1))
    return v if v == v and 0 <= v <= MAX_PLAUSIBLE_IN else None


def percentile(values, p: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default); None for no values."""
    a = sorted(v for v in values if v is not None)
    if not a:
        return None
    k = (len(a) - 1) * p
    f = int(k)
    c = min(f + 1, len(a) - 1)
    return round(a[f] + (a[c] - a[f]) * (k - f), 2)


def local_date(s) -> date | None:
    from build.status import LOCAL, parse_time
    t = parse_time(s)
    return t.astimezone(LOCAL).date() if t else None


def outfall_key(oid) -> str | None:
    """'SPR010' and '010' -> '010'; 'SPR015A' -> '015A'; 'HOL08' -> '008'."""
    if oid in (None, ""):
        return None
    s = re.sub(r"[^A-Z0-9]", "", str(oid).upper())
    m = re.search(r"(\d+)([A-Z]?)$", s)
    return f"{int(m.group(1)):03d}{m.group(2)}" if m else s or None


def month_days(y: int, m: int):
    for d in range(1, calendar.monthrange(y, m)[1] + 1):
        yield date(y, m, d)


def history(records: list[dict], no_events: list[dict], today: date) -> dict[str, dict]:
    """Per permit: discharge days and their rainfall, dry days, per-outfall samples. Pure."""
    out: dict[str, dict] = {}

    def row(permit):
        return out.setdefault(permit, {
            "name": None, "notice_days": set(), "rain_by_day": {}, "zero_days": set(), "unparsed": [],
            "closed_months": set(), "attested_months": set(), "first": None, "last_closed": None,
            "outfalls": defaultdict(dict), "outfall_first": {}, "outfall_last": {}, "types": defaultdict(int)})

    for r in records:
        permit = r.get("npdes_permit")
        if not permit or r.get("event_type") not in DISCHARGE_TYPES:
            continue
        d0 = local_date(r.get("started_at"))
        if d0 is None or d0 >= today:
            continue
        h = row(permit)
        h["name"] = h["name"] or r.get("discharger_name")
        h["types"][r["event_type"]] += 1
        h["first"] = min(h["first"] or d0, d0)
        d1 = local_date(r.get("ended_at")) or d0
        d1 = min(max(d1, d0), d0 + timedelta(days=MAX_SPAN_DAYS))
        d = d0
        while d <= d1:
            h["notice_days"].add(d)
            d += timedelta(days=1)
        raw = r.get("raw") or {}
        if raw.get("_report_class") == "Verified Data Report":
            h["closed_months"].add((d0.year, d0.month))
        text = raw.get("rainfallData")
        if text in (None, ""):
            continue
        v = parse_rain(text)
        if v is None:
            h["unparsed"].append({"event_id": r.get("event_id"), "text": str(text)})
            continue
        if r["event_type"] not in WET_TYPES:
            continue
        if v == 0:
            h["zero_days"].add(d0)
            continue
        h["rain_by_day"][d0] = min(v, h["rain_by_day"].get(d0, v))
        ok = outfall_key(r.get("outfall_id"))
        if ok:
            od = h["outfalls"][ok]
            od[d0] = min(v, od.get(d0, v))
            h["outfall_first"][ok] = min(h["outfall_first"].get(ok, d0), d0)
            h["outfall_last"][ok] = max(h["outfall_last"].get(ok, d0), d0)
    for a in no_events:
        permit = a.get("npdes_permit")
        m = MONTHS.get(str(a.get("month") or "")[:3].title())
        try:
            y = int(a.get("year"))
        except (TypeError, ValueError):
            continue
        if not permit or not m:
            continue
        h = row(permit)
        h["attested_months"].add((y, m))
        h["closed_months"].add((y, m))
        h["first"] = min(h["first"] or date(y, m, 1), date(y, m, 1))
    yesterday = today - timedelta(days=1)
    for h in out.values():
        dry = set()
        last = None
        for (y, m) in sorted(h["closed_months"]):
            for d in month_days(y, m):
                if d < (h["first"] or d) or d > yesterday:
                    continue
                last = max(last or d, d)
                if d not in h["notice_days"]:
                    dry.add(d)
        h["dry_days"] = dry
        h["last_closed"] = last
        h["conflicts"] = sorted(f"{y}-{m:02d}" for (y, m) in h["attested_months"]
                                if any(d.year == y and d.month == m for d in h["notice_days"]))
    return out


def threshold_from(values: list[float], min_days: int) -> float | None:
    return percentile(values, PERCENTILE) if len(values) >= min_days else None


def fallback_for(state: str | None, rules: dict) -> dict:
    """The published fallback for a permittee with no usable history (data/rules.json)."""
    rl = rules.get("rain_likely") or {}
    fb = rl.get("fallback") or {}
    by_state = fb.get("by_state") or {}
    r = by_state.get(state) if state else None
    key = f"rain_likely.fallback.by_state.{state}" if r else "rain_likely.fallback.default"
    if not r:
        from build.rain_likely import SITE_DEFAULT_SOURCE, SITE_DEFAULT_TEXT
        r = fb.get("default") or {"inches": 0.1, "basis": SITE_DEFAULT_TEXT, "source": SITE_DEFAULT_SOURCE}
    return {"threshold_in": r.get("inches"), "rule": key, "basis_text": r.get("basis"), "source": r.get("source"),
            "kind": "state" if key.startswith("rain_likely.fallback.by_state.") else "site_default"}


# ---------------------------------------------------------------- MRMS daily history (IEM)

class BudgetSpent(Exception):
    """The run's request budget for the point service is used up (a rerun continues from the cache)."""


class ServiceRefused(Exception):
    """The point service refused (403, 429, 5xx) or failed IEM_MAX_FAILURES times in a row: stop asking."""


class RequestBudget:
    """At most `limit` requests to the point service in one run; counts what was asked."""

    def __init__(self, limit: int):
        self.limit, self.used, self.failures_in_a_row, self.failures = limit, 0, 0, 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise BudgetSpent(f"{self.used} of {self.limit} point-service requests used")
        self.used += 1


IEM_MAX_FAILURES = 3
IEM_KEEP = ("date", "mrms_precip_in", "prism_precip_in")


def compact_iem(text: str, url: str, fetched_at: str) -> str:
    """The point service's answer cut to what is read back (the day, MRMS and PRISM daily inches): a year at a
    point is about 20 KB instead of 140 KB, so the cache that travels with the pipeline state stays small."""
    d = json.loads(text)
    rows = [{k: r.get(k) for k in IEM_KEEP} for r in (d or {}).get("data") or [] if isinstance(r, dict)]
    return json.dumps({"source": url, "fetched_at": fetched_at, "data": rows}, separators=(",", ":"))


def iem_daily(lat: float, lon: float, years: list[int], offline: bool = False, session=None,
              budget: RequestBudget | None = None) -> dict[date, float]:
    """{date: MRMS daily inches} at the point; per-year files cached in data/raw/iem-iemre/, the
    current year refetched when older than a day. Missing values are left out. With a budget (the
    one-off radar thresholds, radar_build): every request counts against it (BudgetSpent when it is
    used up), and a refusal (HTTP 403, 429 or 5xx) or IEM_MAX_FAILURES failures in a row raise
    ServiceRefused instead of being printed and passed over."""
    import requests
    IEM_DIR.mkdir(parents=True, exist_ok=True)
    this_year = datetime.now(UTC).year
    out = {}
    for y in years:
        p = IEM_DIR / f"{lat:.2f}_{lon:.2f}_{y}.json"
        fresh = p.exists() and (y < this_year or time.time() - p.stat().st_mtime < 86400)
        if not fresh and not offline:
            d1 = date(y, 1, 1)
            d2 = min(date(y, 12, 31), datetime.now(UTC).date() - timedelta(days=1))
            session = session or requests.Session()
            if budget is not None:
                budget.take()
            url = IEM_URL.format(d1=d1, d2=d2, lat=lat, lon=lon)
            try:
                resp = session.get(url, headers=HEADERS, timeout=90)
                code = getattr(resp, "status_code", 200)
                if budget is not None and (code in (403, 429) or code >= 500):
                    raise ServiceRefused(f"IEM {lat:.2f},{lon:.2f} {y}: HTTP {code}")
                resp.raise_for_status()
                tmp = p.with_suffix(".part")      # a full disk or a stop mid-write never leaves half a file
                tmp.write_text(compact_iem(resp.text, url, now_iso()))
                tmp.replace(p)
                if budget is not None:
                    budget.failures_in_a_row = 0
            except ServiceRefused:
                raise
            except Exception as e:  # noqa: BLE001  the cached copy (if any) still serves
                print(f"rain_thresholds: IEM {lat:.2f},{lon:.2f} {y}: {type(e).__name__}: {e}")
                if budget is not None:
                    budget.failures_in_a_row += 1
                    budget.failures += 1
                    if budget.failures_in_a_row >= IEM_MAX_FAILURES:
                        raise ServiceRefused(f"{IEM_MAX_FAILURES} failures in a row, the last: {type(e).__name__}: {e}") from e
            time.sleep(IEM_PAUSE_S)
        try:
            d = read_json(p, {}) if p.exists() else {}
        except ValueError:          # an unreadable cached file is no answer (the next run asks again)
            d = {}
        for row in (d or {}).get("data") or []:
            v = row.get("mrms_precip_in")
            if v is None:
                continue
            try:
                out[date.fromisoformat(row["date"])] = float(v)
            except (KeyError, ValueError, TypeError):
                continue
    return out


# ---------------------------------------------------------------- outfall registry

def cso_permittees() -> dict[str, dict]:
    """Every permit with a CSO outfall in the registries (ingest/rainfall.py cso_outfalls: closed
    outfalls left out): {permit: {state, name, points: [(lat, lon)], outfalls: {key: (lat, lon)}}}."""
    from ingest.rainfall import cso_outfalls
    out: dict[str, dict] = {}
    for o in cso_outfalls():
        p = out.setdefault(o["permit"], {"state": o["state"], "name": o.get("name"), "points": [], "outfalls": {}})
        p["name"] = p["name"] or o.get("name")
        p["points"].append((o["lat"], o["lon"]))
        k = outfall_key(o.get("outfall"))
        if k:
            p["outfalls"].setdefault(k, (o["lat"], o["lon"]))
    return out


def centroid(points) -> tuple[float, float] | None:
    if not points:
        return None
    return (round(statistics.median(p[0] for p in points), 2), round(statistics.median(p[1] for p in points), 2))


# ---------------------------------------------------------------- radar on reported discharge days (GA, MI)
#
# Where the operators' notices carry no rainfall figure that can be read as a 24-hour total (Michigan's
# precipitationAmount is the operator's figure for the event, often the storm total: used directly as a radar trigger
# it kept only 82 percent of overflow days; Georgia's list has none), the operator's amount is read from the radar
# itself: the NOAA MRMS daily total at the operator's outfalls on each day one of its combined sewer discharges began,
# and its 10th percentile, as for Massachusetts, when at least MIN_DAYS such days had radar rain. The point service is
# asked once per point and year (one-off, by hand: `python -m build.rain_thresholds --radar MI GA`, about 600
# requests); the result is data/rain-thresholds-radar.json, tracked in git, which build() merges into
# data/build/rain-thresholds.json every hour without asking the service again.

RADAR_FILE = DATA_DIR / "rain-thresholds-radar.json"
RADAR_BUDGET = 1200
RADAR_STATES = {
    "MI": {"events": "mi-egle-mienviro-cso-sso-list", "types": ("cso",), "list": "EGLE MiEnviro list",
           "authority": "Michigan EGLE, MiEnviro CSO/SSO List",
           "what": "combined sewer overflow (CSO) and retention treatment basin (RTB) discharges, as the list classes "
                   "them (an RTB discharge is combined sewage given partial treatment before it overflows)"},
    # Georgia's list holds spills (blockages, breaks, pump stations; its few "CSO Dry-weather" rows are dry-weather
    # too): rain does not drive them, as a Massachusetts sanitary sewer overflow gives no sample, so they are counted
    # and listed but never read against the radar (sample False) and give no operator a trigger (review 2026-11-06).
    "GA": {"events": "ga-epd-spills", "types": ("cso", "sso"), "list": "EPD spills list", "sample": False,
           "no_sample_why": "the list records spills, not wet-weather combined sewer discharges: the radar was not read",
           "authority": "Georgia EPD, Municipal Sewage Spills Reported to EPD",
           "what": "every spill the list gives under a combined sewer permit (the list holds spills of raw sewage; "
                   "permitted wet-weather discharges at combined sewer outfalls are not spills and are not on it)"},
}
RADAR_SOURCE = ("{authority} (combined sewer discharges that began {y0} to {y1}); NOAA MRMS daily rainfall at the operator's "
                "outfalls, via the Iowa Environmental Mesonet")
RADAR_POINT_NOTE = ("the median of the operator's registered combined sewer outfall points (data/outfalls-*.json), to "
                    "0.01 degree, as for Massachusetts")
TRACE_IN = 0.01            # a radar total under this is no radar rain that day: counted, not a sample
# The first day read: the first full year of the operational MRMS product (NCEP, from October 2014). The point
# service also answers for 2001 to 2014, but on the same operators' discharge days those years read far lower (St.
# Joseph's 10th percentile 0.16 inch in 2001 to 2014 against 0.55 from 2015; Southgate-Wyandotte 0.07 against 0.33;
# the 26 Michigan operators pooled 0.08 against 0.20) while the operators' own figures read the same in both periods,
# so they are not a like-for-like record of the radar the live check reads.
RADAR_FIRST_DAY = date(2015, 1, 1)


def permits_by_discharger(rows: list[dict] | None = None) -> dict[str, list[str]]:
    """{discharger id: [npdes permits]} from data/dischargers.json, to place a report filed without a permit (the
    Great Lakes Water Authority files its first notices under its name) on its operator's permit."""
    if rows is None:
        d = read_json(DATA_DIR / "dischargers.json") or {}
        rows = d.get("dischargers", d) if isinstance(d, dict) else d
    out: dict[str, list[str]] = {}
    for r in rows if isinstance(rows, list) else []:
        for p in [r.get("npdes_permit")] + list(r.get("npdes_permits") or []):
            if p and r.get("id") and p not in out.setdefault(r["id"], []):
                out[r["id"]].append(p)
    return out


def record_permit(r: dict, by_discharger: dict[str, list[str]]) -> str | None:
    """The record's permit; for a report filed with none, its operator's only permit (never a guess between two)."""
    if r.get("npdes_permit"):
        return r["npdes_permit"]
    ps = by_discharger.get(r.get("discharger_id") or "") or []
    return ps[0] if len(ps) == 1 else None


def radar_discharge_days(records: list[dict], state: str, types, by_discharger: dict[str, list[str]],
                         today: date, since: date | None = None) -> dict[str, dict[date, set]]:
    """{permit: {start day: {outfall keys}}}: the local days on which a discharge of the given types of the state's
    permits began, as the source gives the day (its own offset), from `since` on. A copy (duplicate_of) is not a
    second discharge; a start on or after today is not a whole day yet. Pure."""
    out: dict[str, dict[date, set]] = {}
    for r in records:
        if r.get("event_type") not in types or r.get("duplicate_of"):
            continue
        permit = record_permit(r, by_discharger)
        if not permit or not permit.upper().startswith(state):
            continue
        try:
            d0 = date.fromisoformat(str(r.get("started_at") or "")[:10])
        except ValueError:
            continue
        if d0 >= today or (since and d0 < since):
            continue
        out.setdefault(permit, {}).setdefault(d0, set()).add(outfall_key(r.get("outfall_id")))
    return out


def day_radar(series: dict[date, float], d: date) -> float | None:
    """The radar's reading for a discharge that began on day d: the larger of that day's total and the day before's.
    The live check compares a rolling 24-hour total, read every hour, and keeps the caution 48 hours after it falls
    below the amount; a discharge that begins in the small hours after an evening storm has little rain on its own
    calendar day (and the service's days run midnight to midnight Chicago time), so the day alone would
    understate the rain the live check saw before the discharge. None when the day itself has no value."""
    v = series.get(d)
    if v is None:
        return None
    return max(v, series.get(d - timedelta(days=1)) or 0.0)


def radar_sample(days, series: dict[date, float]) -> dict:
    """The radar reading for each discharge day (day_radar): a sample when it is TRACE_IN or more, a no-rain day
    under it (snowmelt or a dry-weather discharge: counted, not a sample, as a reported 0.00 is in Massachusetts),
    missing when the series has no value for the day. Pure."""
    values, zero, missing, sampled = [], [], [], []
    for d in sorted(days):
        v = day_radar(series, d)
        if v is None:
            missing.append(d)
        elif v < TRACE_IN:
            zero.append(d)
        else:
            values.append(v)
            sampled.append(d)
    return {"values": sorted(values), "zero_days": zero, "missing_days": missing, "sampled_days": sampled}


def radar_row(permit: str, name: str | None, state: str, days, series: dict[date, float], min_days: int,
              point: tuple[float, float] | None, n_points: int) -> dict:
    """One operator's row of data/rain-thresholds-radar.json: its threshold (the 10th percentile of the radar on its
    discharge days, when at least min_days had radar rain), the counts behind it, the dates spanned. Pure."""
    spec = RADAR_STATES[state]
    smp = radar_sample(days, series)
    vs = smp["values"]
    thr = threshold_from(vs, min_days) if spec.get("sample", True) else None
    sd = smp["sampled_days"]
    row = {"permit": permit, "name": name, "state": state, "has_cso_outfalls": True, "per_24h": True,
           "compare_to": "the NOAA MRMS radar-only 24-hour total at any of the permittee's outfalls",
           "n_start_days": len(days), "n_discharge_days": len(vs), "n_no_radar_rain_days": len(smp["zero_days"]),
           "n_no_radar_value_days": len(smp["missing_days"]),
           "since": sd[0].isoformat() if sd else None, "until": sd[-1].isoformat() if sd else None,
           "p5": percentile(vs, 0.05), "p10": percentile(vs, 0.10), "p25": percentile(vs, 0.25),
           "p50": percentile(vs, 0.50), "p90": percentile(vs, 0.90),
           "under_0_1_in": sum(1 for v in vs if v < 0.1),
           "share_under_0_1_in": round(sum(1 for v in vs if v < 0.1) / len(vs), 3) if vs else None,
           "point": list(point) if point else None, "n_outfall_points": n_points,
           "point_basis": RADAR_POINT_NOTE, "threshold_method": "radar_on_discharge_days"}
    if thr is not None:
        src = RADAR_SOURCE.format(authority=spec["authority"], y0=sd[0].year, y1=sd[-1].year)
        row.update(threshold_in=thr, basis="history", rule="rain_likely.percentile", threshold_kind="operator_history",
                   basis_text=(f"10th percentile of the NOAA MRMS daily rainfall at the operator's outfalls on the "
                               f"{len(vs)} days its reported discharges began with radar rain ({sd[0]:%b %Y} to "
                               f"{sd[-1]:%b %Y}; the larger of that day's total and the day before's): nine "
                               f"discharge days in ten had more rain"),
                   source=src)
    else:
        why = (spec["no_sample_why"] if spec.get("sample") is False else
               f"{len(vs)} discharge days with radar rain (fewer than {min_days})" if series else
               f"{len(days)} discharge days (fewer than {min_days}): the radar was not read")
        row.update(threshold_in=None, basis=None, why_fallback=why)
    return row


def radar_build(states=("MI", "GA"), budget: int = RADAR_BUDGET, min_days: int = MIN_DAYS, offline: bool = False,
                events: dict[str, Path] | None = None, today: date | None = None, write: bool = True,
                since: date | None = RADAR_FIRST_DAY) -> dict:
    """Read each state's records (data/build/events/<source>.json, or events[state]), ask the point service for the
    years of each operator's discharge days at its median outfall point (the operators with the most discharge days
    first, within the budget), and write RADAR_FILE. Operators with no registered combined sewer outfall are listed,
    not read: the caution has no point for them. Raises ServiceRefused or BudgetSpent (nothing written; the cache
    keeps what was read)."""
    today = today or datetime.now(UTC).date()
    reg = cso_permittees()
    by_dis = permits_by_discharger()
    names = {p: (v or {}).get("name") for p, v in _discharger_names().items()}
    bud = RequestBudget(budget)
    out = {"built": now_iso(), "today": today.isoformat(), "min_days": min_days, "percentile": PERCENTILE,
           "since": since.isoformat() if since else None,
           "method": ("threshold_in = the 10th percentile of the NOAA MRMS daily radar total (Iowa Environmental Mesonet "
                      "point service) at the operator's median outfall point on the days its reported combined sewer "
                      "discharges began (the larger of that day's total and the day before's), from `since` (the "
                      "first full year of the operational MRMS product), when at least min_days of those days had "
                      "radar rain (0.01 inch or more); days under 0.01 inch are counted, not sampled. Merged into "
                      "data/build/rain-thresholds.json every hour by build()."),
           "radar_source": "NOAA MRMS daily totals via the Iowa Environmental Mesonet reanalysis point service "
                           "(mesonet.agron.iastate.edu/iemre): America/Chicago calendar days, summed from MRMS hourly "
                           "totals (gauge-corrected GaugeCorr_QPE_01H to October 2020 and MultiSensor_QPE_01H_Pass2 after, "
                           "radar-only RadarOnly_QPE_01H where those are missing, as in early 2015)",
           "states": {}, "permits": {}, "not_registered": {}}
    plan = []
    for st in states:
        spec = RADAR_STATES[st]
        path = (events or {}).get(st) or EVENTS_DIR / f"{spec['events']}.json"
        ev = read_json(Path(path), {}) or {}
        recs = ev.get("records") or []
        days = radar_discharge_days(recs, st, spec["types"], by_dis, today, since)
        cso_days = days if spec["types"] == ("cso",) else radar_discharge_days(recs, st, ("cso",), by_dis, today, since)
        starts = [d for dd in days.values() for d in dd]
        out["states"][st] = {"authority": spec["authority"], "what": spec["what"], "records_file": Path(path).name,
                             "records_fetched_at": ev.get("fetched_at"), "records": len(recs),
                             "first_day": min(starts).isoformat() if starts else None,
                             "last_day": max(starts).isoformat() if starts else None}
        for permit, dd in days.items():
            if permit in reg:
                plan.append((st, permit, dd))
        # combined sewer discharges of a permit with no registered combined sewer outfall: listed, not read
        for permit, dd in cso_days.items():
            if permit not in reg:
                out["not_registered"][permit] = {"state": st, "name": names.get(permit), "n_start_days": len(dd)}
    plan.sort(key=lambda x: (-len(x[2]), x[1]))
    for st, permit, dd in plan:
        g = reg[permit]
        c = centroid(g["points"])
        series = {}
        if c and len(dd) >= min_days and RADAR_STATES[st].get("sample", True):
            years = sorted({d.year for d in dd} | {(d - timedelta(days=1)).year for d in dd})
            series = iem_daily(c[0], c[1], years, offline=offline, budget=bud)
        npts = len({(round(a, 2), round(b, 2)) for a, b in g["points"]})
        out["permits"][permit] = radar_row(permit, names.get(permit) or g.get("name"), st, dd, series, min_days, c, npts)
    for st in states:
        rows = [r for r in out["permits"].values() if r["state"] == st]
        out["states"][st].update(operators=len(rows), with_threshold=sum(1 for r in rows if r["threshold_in"] is not None))
    if bud.failures:     # a year left unread would leave its discharge days out silently (review 2026-11-06)
        raise ServiceRefused(f"{bud.failures} point-service request(s) failed; a rerun asks again for the years not cached")
    out["requests"] = bud.used
    out["count"] = len(out["permits"])
    out["with_threshold"] = sum(1 for r in out["permits"].values() if r["threshold_in"] is not None)
    if write:
        write_json(RADAR_FILE, out)
    return out


def _discharger_names() -> dict[str, dict]:
    from build.rain_likely import discharger_index
    return discharger_index()


def merge_radar(permits: dict[str, dict], radar: dict, reg: dict, rules: dict) -> int:
    """Lay the radar thresholds (RADAR_FILE) over the hourly rows: an operator with a threshold of its own from the
    radar takes it, unless its own reported rainfall already gives one (Massachusetts). Returns how many were laid."""
    n = 0
    for permit, r in ((radar or {}).get("permits") or {}).items():
        if (permits.get(permit) or {}).get("basis") == "history":
            continue
        if r.get("threshold_in") is None:     # the fallback stays; say why from the radar file (review 2026-11-06)
            if permit in permits and r.get("why_fallback"):
                permits[permit]["why_fallback"] = r["why_fallback"]
            continue
        fb = fallback_for(r.get("state") or permit[:2], rules)
        permits[permit] = {**r, "has_cso_outfalls": permit in reg, "fallback_in": fb["threshold_in"]}
        n += 1
    return n


# ---------------------------------------------------------------- build

def stats(values) -> dict:
    vs = [v for v in values if v is not None]
    return {"n": len(vs), "p10": percentile(vs, 0.10), "p50": percentile(vs, 0.50), "p90": percentile(vs, 0.90)}


def build(offline: bool = False, min_days: int = MIN_DAYS, today: date | None = None, write: bool = True) -> dict:
    from build.status import load_rules
    rules = load_rules()
    today = today or datetime.now(UTC).date()
    ev = read_json(EVENTS_DIR / "ma-massdep.json", {}) or {}
    recs = ev.get("records") or []
    no_events = (ev.get("meta") or {}).get("no_event_reports") or []
    hist = history(recs, no_events, today)
    reg = cso_permittees()
    permits = {}
    for permit in sorted(set(reg) | {p for p, h in hist.items() if h["rain_by_day"]}):
        h = hist.get(permit)
        g = reg.get(permit) or {}
        state = g.get("state") or permit[:2]
        values = sorted((h or {}).get("rain_by_day", {}).values())
        thr = threshold_from(values, min_days)
        fb = fallback_for(state, rules)
        row = {"permit": permit, "name": (h or {}).get("name") or g.get("name"), "state": state,
               "has_cso_outfalls": permit in reg, "per_24h": True,
               "compare_to": "the NOAA MRMS radar-only 24-hour total at any of the permittee's outfalls"}
        if thr is not None:
            row.update(threshold_in=thr, basis="history", rule="rain_likely.percentile",
                       basis_text=f"10th percentile of the rainfall the permittee itself reported on "
                                  f"{len(values)} discharge days ({min(h['rain_by_day']):%b %Y} to "
                                  f"{max(h['rain_by_day']):%b %Y}): nine discharge days in ten had more rain",
                       source="MassDEP Sewage Notification Data System (Verified Data Reports, rainfallData)",
                       threshold_kind="operator_history")
        else:
            row.update(threshold_in=fb["threshold_in"], basis="published", rule=fb["rule"],
                       basis_text=fb["basis_text"], source=fb["source"], threshold_kind=fb["kind"],
                       why_fallback=(f"{len(values)} discharge days with a reported rainfall (fewer than {min_days})"
                                     if h else "no discharge history with rainfall in the Massachusetts portal"))
        row["fallback_in"] = fb["threshold_in"]
        if h:
            row.update({
                "n_discharge_days": len(values), "n_notice_days": len(h["notice_days"]),
                "n_zero_rain_days": len(h["zero_days"]), "n_dry_days": len(h["dry_days"]),
                "n_closed_months": len(h["closed_months"]), "n_attested_months": len(h["attested_months"]),
                "attestation_conflicts": h["conflicts"],
                "p10": percentile(values, 0.10), "p25": percentile(values, 0.25), "p50": percentile(values, 0.50),
                "p90": percentile(values, 0.90), "min": values[0] if values else None,
                "since": h["first"].isoformat() if h["first"] else None,
                "until": h["last_closed"].isoformat() if h["last_closed"] else None,
                "types": dict(h["types"]),
                "unparsed": {"count": len(h["unparsed"]), "examples": h["unparsed"][:5]},
            })
            outs = {}
            for k in sorted(h["outfalls"]):
                vs = sorted(h["outfalls"][k].values())
                outs[k] = {"threshold_in": threshold_from(vs, min_days), "n_discharge_days": len(vs),
                           "p10": percentile(vs, 0.10), "p50": percentile(vs, 0.50),
                           "since": h["outfall_first"][k].isoformat(), "until": h["outfall_last"][k].isoformat(),
                           "point": list(g["outfalls"][k]) if k in (g.get("outfalls") or {}) else None}
            row["outfalls"] = outs
            # MRMS daily at the permittee's outfalls: rainfall on no-discharge days, and the radar's
            # reading on the permittee's discharge days
            pts = g.get("points") or [(r["lat"], r["lon"]) for r in recs
                                      if r.get("npdes_permit") == permit and r.get("lat") is not None]
            c = centroid(pts)
            if c and h["first"]:
                years = list(range(h["first"].year, today.year + 1))
                daily = iem_daily(c[0], c[1], years, offline=offline)
                dry = [daily.get(d) for d in sorted(h["dry_days"]) if d in daily]
                wet = [daily.get(d) for d in sorted(h["rain_by_day"]) if d in daily]
                # the day before as well: a storm late on one day and an overflow after midnight
                wet2 = [daily[d] + daily.get(d - timedelta(days=1), 0.0) for d in sorted(h["rain_by_day"]) if d in daily]
                thr_used = row["threshold_in"]
                span = [h["first"] + timedelta(days=i) for i in range(((h["last_closed"] or h["first"]) - h["first"]).days + 1)]
                flagged = [d for d in span if any(daily.get(d - timedelta(days=k), 0.0) >= thr_used for k in (0, 1, 2))]
                above = [d for d in sorted(set(h["dry_days"]) | set(h["rain_by_day"]))
                         if daily.get(d) is not None and daily[d] >= thr_used]
                above_dis = [d for d in above if d in h["rain_by_day"]]
                row["mrms_daily"] = {
                    "point": list(c), "source": "NOAA MRMS daily totals via the Iowa Environmental Mesonet "
                                                "reanalysis point service (mesonet.agron.iastate.edu/iemre)",
                    "discharge_days": stats(wet), "discharge_days_with_day_before": stats(wet2), "dry_days": stats(dry),
                    "dry_days_at_or_above_threshold": sum(1 for v in dry if v >= thr_used),
                    "share_dry_days_at_or_above_threshold": round(sum(1 for v in dry if v >= thr_used) / len(dry), 3)
                    if dry else None,
                    "discharge_days_below_threshold_by_radar": sum(1 for v in wet if v < thr_used),
                    "discharge_days_below_threshold_by_radar_with_day_before": sum(1 for v in wet2 if v < thr_used),
                    "share_of_days_flagged": round(len(flagged) / len(span), 3) if span else None,
                    "share_of_days_flagged_note": "days whose radar total, or that of either of the two days before, "
                                                  "reached the threshold: about how often the caution would have shown "
                                                  "(before discharge notices, which turn the waters red, take over)",
                    "days_at_or_above_threshold": len(above),
                    "share_of_those_with_a_discharge": round(len(above_dis) / len(above), 3) if above else None,
                }
        permits[permit] = row
    n_radar = merge_radar(permits, read_json(RADAR_FILE, {}) or {}, reg, rules)
    out = {
        "built": now_iso(), "today": today.isoformat(), "min_days": min_days, "percentile": PERCENTILE,
        "method": ("threshold_in = the 10th percentile of the rainfall the permittee reported on its discharge days "
                   "(the smallest positive figure on each day, CSO, blended and bypass reports), when at least "
                   f"{min_days} days have one; else the published fallback for the state (data/rules.json "
                   "rain_likely.fallback). Compared with the MRMS 24-hour total at the permittee's outfalls. "
                   "Georgia and Michigan operators: the 10th percentile of the MRMS daily radar total on their reported "
                   "discharge days (data/rain-thresholds-radar.json, built by --radar)."),
        "source": "MassDEP Sewage Notification Data System, via the EEA Data Portal (Verified Data Reports)",
        "fallbacks": (rules.get("rain_likely") or {}).get("fallback"),
        "count": len(permits), "with_history": sum(1 for r in permits.values() if r["basis"] == "history"),
        "with_radar_history": n_radar,
        "permits": permits,
    }
    if write:
        write_json(OUT_JSON, out)
        OUT_MD.write_text(summary_md(out))
    return out


def summary_md(d: dict) -> str:
    lines = ["# Rainfall at which discharges happened: Springfield, Holyoke, Chicopee", "",
             f"Built {d['built']} by `pipeline/build/rain_thresholds.py` from the MassDEP Sewage Notification portal "
             "(Verified Data Reports carry each permittee's own rainfall figure) and NOAA MRMS daily totals at the "
             "permittee's outfalls (Iowa Environmental Mesonet). Threshold = 10th percentile of reported rainfall on "
             "discharge days. All figures are inches.", "",
             "| | Springfield | Holyoke | Chicopee |", "|---|---|---|---|"]
    rows = [d["permits"].get(p) or {} for p in FOCUS]

    def cell(r, f):
        try:
            return f(r)
        except Exception:  # noqa: BLE001
            return "n/a"
    spec = [
        ("Permit", lambda r: r["permit"]),
        ("Period (first record to last closed month)", lambda r: f"{r['since']} to {r['until']}"),
        ("Days with a discharge notice", lambda r: r["n_notice_days"]),
        ("Discharge days with a reported rainfall (sample)", lambda r: r["n_discharge_days"]),
        ("Dry-weather discharge days (0.00 reported)", lambda r: r["n_zero_rain_days"]),
        ("**Threshold (p10 of reported rainfall)**", lambda r: f"**{r['threshold_in']:.2f}**"),
        ("Median reported rainfall on discharge days", lambda r: f"{r['p50']:.2f}"),
        ("Smallest reported rainfall with a discharge", lambda r: f"{r['min']:.2f}"),
        ("No-discharge days counted", lambda r: r["n_dry_days"]),
        ("Months closed (verified reports or no-event attestation)", lambda r: r["n_closed_months"]),
        ("MRMS daily on discharge days: p10 / median", lambda r: f"{r['mrms_daily']['discharge_days']['p10']:.2f} / "
                                                             f"{r['mrms_daily']['discharge_days']['p50']:.2f}"),
        ("Discharge days the radar put below the threshold (that day / with the day before)",
         lambda r: f"{r['mrms_daily']['discharge_days_below_threshold_by_radar']} / "
                   f"{r['mrms_daily']['discharge_days_below_threshold_by_radar_with_day_before']} "
                   f"of {r['mrms_daily']['discharge_days']['n']}"),
        ("MRMS daily on no-discharge days: median / p90", lambda r: f"{r['mrms_daily']['dry_days']['p50']:.2f} / "
                                                                f"{r['mrms_daily']['dry_days']['p90']:.2f}"),
        ("No-discharge days at or above the threshold (radar)",
         lambda r: f"{r['mrms_daily']['dry_days_at_or_above_threshold']} "
                   f"({100 * r['mrms_daily']['share_dry_days_at_or_above_threshold']:.0f}%)"),
        ("Days at or above the threshold that had a discharge",
         lambda r: f"{100 * r['mrms_daily']['share_of_those_with_a_discharge']:.0f}% of "
                   f"{r['mrms_daily']['days_at_or_above_threshold']}"),
        ("Share of days the caution would have shown (radar, threshold day plus 48 h)",
         lambda r: f"{100 * r['mrms_daily']['share_of_days_flagged']:.0f}%"),
        ("Outfalls with their own threshold (10+ days)",
         lambda r: sum(1 for o in r["outfalls"].values() if o["threshold_in"] is not None)),
    ]
    for label, f in spec:
        lines.append(f"| {label} | " + " | ".join(str(cell(r, f)) for r in rows) + " |")
    lines += ["", "Per-outfall thresholds (p10, discharge days):", ""]
    for p, name in FOCUS.items():
        r = d["permits"].get(p) or {}
        outs = [f"{k} {o['threshold_in']:.2f} ({o['n_discharge_days']})" for k, o in (r.get("outfalls") or {}).items()
                if o["threshold_in"] is not None]
        lines.append(f"- {name}: " + ("; ".join(outs) or "none with 10 or more days"))
    lines += ["", "Reading: a permittee's threshold is low when some of its outfalls overflow in small storms. "
              "The radar's daily totals and the permittee's gauge disagree storm by storm (radar-only estimates, a "
              "calendar day against the permittee's storm total), which is why the live check compares the radar's "
              "24-hour total with the threshold at every outfall point and keeps the caution 48 hours after the "
              "total falls below it.", ""]
    return "\n".join(lines)


def radar_table(d: dict) -> str:
    """The radar thresholds as a Markdown table (operator, discharge days, dates, 10th and 5th percentiles, the share
    of days under 0.1 inch), the operators with their own figure first."""
    lines = ["| Operator (permit) | Discharge days with radar rain (of start days) | Dates | 10th pct (in) | "
             "5th pct (in) | Under 0.1 in | Trigger |", "|---|---:|---|---:|---:|---:|---|"]
    rows = sorted((d.get("permits") or {}).values(),
                  key=lambda r: (r["state"], r["threshold_in"] is None, -r["n_discharge_days"], r["permit"]))
    for r in rows:
        dates = f"{r['since']} to {r['until']}" if r.get("since") else "n/a"
        share = f"{r['under_0_1_in']} ({100 * r['share_under_0_1_in']:.0f}%)" if r.get("share_under_0_1_in") is not None else "n/a"
        p10 = f"{r['p10']:.2f}" if r.get("p10") is not None else "n/a"
        p5 = f"{r['p5']:.2f}" if r.get("p5") is not None else "n/a"
        trig = f"own, {r['threshold_in']:.2f} in" if r.get("threshold_in") is not None else "state or default"
        lines.append(f"| {r.get('name') or r['permit']} ({r['permit']}) | {r['n_discharge_days']} ({r['n_start_days']}) | "
                     f"{dates} | {p10} | {p5} | {share} | {trig} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="use only the cached MRMS daily history")
    ap.add_argument("--min-days", type=int, default=MIN_DAYS)
    ap.add_argument("--radar", nargs="+", metavar="STATE", choices=sorted(RADAR_STATES),
                    help="build data/rain-thresholds-radar.json for these states (one-off; asks the point service)")
    ap.add_argument("--budget", type=int, default=RADAR_BUDGET, help="with --radar: the most point-service requests")
    ap.add_argument("--events", action="append", default=[], metavar="STATE=PATH",
                    help="with --radar: read this state's records from PATH instead of data/build/events/")
    a = ap.parse_args()
    if a.radar:
        events = dict(e.split("=", 1) for e in a.events)
        try:
            d = radar_build(a.radar, budget=a.budget, min_days=a.min_days, offline=a.offline,
                            events={k.upper(): Path(v) for k, v in events.items()})
        except (BudgetSpent, ServiceRefused) as e:
            print(f"rain_thresholds --radar: stopped, nothing written: {type(e).__name__}: {e}")
            raise SystemExit(2) from e
        print(f"rain_thresholds --radar: {d['count']} operators, {d['with_threshold']} with their own threshold, "
              f"{d['requests']} point-service requests -> {RADAR_FILE}")
        print(radar_table(d))
        return
    d = build(offline=a.offline, min_days=a.min_days)
    print(f"rain_thresholds: {d['count']} permittees, {d['with_history']} with their own history "
          f"({d['with_radar_history']} from the radar) -> {OUT_JSON}")
    for p, name in FOCUS.items():
        r = d["permits"].get(p) or {}
        print(f"  {name} {p}: threshold {r.get('threshold_in')} in ({r.get('basis')}), n={r.get('n_discharge_days')}, "
              f"p50={r.get('p50')}, dry days={r.get('n_dry_days')}")


if __name__ == "__main__":
    main()
