"""Rainfall thresholds for the "discharge likely; no report received" caution (docs/rain-likely.md).

    python -m build.rain_thresholds [--offline] [--min-days 10]

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

def iem_daily(lat: float, lon: float, years: list[int], offline: bool = False, session=None) -> dict[date, float]:
    """{date: MRMS daily inches} at the point; per-year files cached in data/raw/iem-iemre/, the
    current year refetched when older than a day. Missing values are left out."""
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
            try:
                resp = session.get(IEM_URL.format(d1=d1, d2=d2, lat=lat, lon=lon), headers=HEADERS, timeout=90)
                resp.raise_for_status()
                p.write_text(resp.text)
            except Exception as e:  # noqa: BLE001  the cached copy (if any) still serves
                print(f"rain_thresholds: IEM {lat:.2f},{lon:.2f} {y}: {type(e).__name__}: {e}")
            time.sleep(IEM_PAUSE_S)
        d = read_json(p, {}) if p.exists() else {}
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
    out = {
        "built": now_iso(), "today": today.isoformat(), "min_days": min_days, "percentile": PERCENTILE,
        "method": ("threshold_in = the 10th percentile of the rainfall the permittee reported on its discharge days "
                   "(the smallest positive figure on each day, CSO, blended and bypass reports), when at least "
                   f"{min_days} days have one; else the published fallback for the state (data/rules.json "
                   "rain_likely.fallback). Compared with the MRMS 24-hour total at the permittee's outfalls."),
        "source": "MassDEP Sewage Notification Data System, via the EEA Data Portal (Verified Data Reports)",
        "fallbacks": (rules.get("rain_likely") or {}).get("fallback"),
        "count": len(permits), "with_history": sum(1 for r in permits.values() if r["basis"] == "history"),
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="use only the cached MRMS daily history")
    ap.add_argument("--min-days", type=int, default=MIN_DAYS)
    a = ap.parse_args()
    d = build(offline=a.offline, min_days=a.min_days)
    print(f"rain_thresholds: {d['count']} permittees, {d['with_history']} with their own history -> {OUT_JSON}")
    for p, name in FOCUS.items():
        r = d["permits"].get(p) or {}
        print(f"  {name} {p}: threshold {r.get('threshold_in')} in ({r.get('basis')}), n={r.get('n_discharge_days')}, "
              f"p50={r.get('p50')}, dry days={r.get('n_dry_days')}")


if __name__ == "__main__":
    main()
