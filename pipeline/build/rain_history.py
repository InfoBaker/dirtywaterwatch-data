"""Rain levels from each operator's own overflow history (the evidence behind "Discharge likely" and "Discharge possible").

    python -m build.rain_history [--offline] [--budget N] [--only PERMIT ...] [--if-older-h H]
                                 (the daily pass: `make rain-history`; the build runs it with --if-older-h 20)

For every open combined sewer permit of the live states (ingest/rainfall.py cso_outfalls) this pairs the storms at
the operator's outfalls with the operator's own dated reports in data/build/events/ and writes
data/build/rain-levels.json (the repository's seed copy is data/rain-levels.json; load_levels reads the build copy
first): per operator, and per outfall where its reports name outfalls, how often an overflow was reported after storms
of each size, and from that the rain at which the site's caution reads "possible" and "likely". build/rain_likely.py
reads the file; an operator with no usable history keeps its own published rule, else its state's rule, else the
site default (data/rules.json rain_likely.fallback). Nothing in the file is typed by hand.

The record of rain: NOAA MRMS daily totals from the Iowa Environmental Mesonet's reanalysis point service
(build/rain_thresholds.py iem_daily: America/Chicago calendar days, cached per point and year, the current year
asked again at most weekly here), from 2015, the first full year of the operational MRMS product: the same radar
system the hourly check reads. An operator is read at up to four points (rain_points: the median of its outfalls,
then the outfalls farthest from those chosen while more than 8 km away); its day is the wettest of them (daily_max),
as the live check takes the wettest outfall.

Definitions (pure functions below; rules.rain_likely.history overrides the numbers in DEFAULTS):

  storm        a run of consecutive days with at least the lowest rung (0.1 inch) at the operator's rain points; its
               size is the largest one-day total in the run. A day with no value ends a run. (The hourly check reads a
               rolling 24-hour total, never smaller than the largest calendar-day total: a storm reads at least as
               large live as in this record, so the live reading reaches a level no later than the record says.)
  report       a dated combined sewer discharge report of the operator (cso, blended, bypass, plant_bypass; never a
               sanitary sewer overflow, a copy, a monthly or yearly figure, a system-wide risk advisory, or a
               structure set apart from the rain caution: those are left out and counted). It covers its start day to its end day (at most max_span_days
               after the start; a report with no end covers its start day). Times with an offset are read on the rain
               record's calendar (America/Chicago); a day-precision report keeps the day it gives.
  followed     a storm is followed by a reported overflow when a report covers any day from the storm's first day to
               the day after its last day (the margin absorbs a day-precision report's missing time).
  period       from the operator's first report (2015 at the earliest) to the end of its sources' coverage (never
               after today) less lag_days (late reports), less the stretches left out: a cited system change
               (rules.rain_likely.history.system_changes), a reporting gap (gap_days or more with no report while
               gap_min_storms storms fell; a storm followed by a report is never left out with it), and,
               where the share of storms of the second rung up followed by a report rose sharply at a year boundary
               (change_point), the years before (under-reported; they still count toward the smallest storm ever
               followed by a report). A sharp fall is stated as a note and nothing is cut (the cautious side).
               observed_days: the days of the period with a rain value outside the stretches left out; the year of
               record and the three quiet years are counted in them.
  bands        storms counted by rung (0.1, 0.25, 0.5, 0.75, 1, 1.5, 2 inches and up).
  levels       possible_in  the smallest storm ever followed by a reported overflow (over every storm of the record,
                            before gaps or a change point remove any), rounded down to a rung; the report behind it
                            is cited;
               likely_in    the lowest band at or above possible_in (thin bands, under min_storms, pooled into the band
                            below) after whose storms an overflow was reported at least likely_share (half) of the
                            time, and after at least that share of all storms of that band and larger together;
                            None when no band reaches it;
               quiet        the storms below possible_in: "enough" only on quiet_min_storms (30) or more, over
                            quiet_min_period_days (three years) of observed days, with none followed by a report;
                            only then does the site show no caution below possible_in.

The safety guarantee: a history removes a caution the fallback would show only on a quiet range that is "enough";
one reported overflow in that range moves possible_in down to it. A usable history needs min_report_storms storms
followed by a report, min_total_storms storms and min_period_days of observed days; anything less leaves the operator on
the fallback, with the reason written beside its counts. An operator is computed only from a rain record that has
every year it needs (real content in the cache); otherwise its previous entry stays.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from common import BUILD_DIR, DATA_DIR, read_json

METHOD_VERSION = 1
LEVELS_BUILD = BUILD_DIR / "rain-levels.json"      # the daily pass writes here (pipeline state, kept between runs)
LEVELS_SEED = DATA_DIR / "rain-levels.json"        # the copy in the repository: read until a daily pass has run
RAIN_ZONE = ZoneInfo("America/Chicago")        # the rain record's calendar days (the point service's)
FIRST_DAY = date(2015, 1, 1)                   # the first full year of the operational MRMS product
WET_TYPES = ("cso", "blended", "bypass", "plant_bypass")
DEFAULTS = {
    "rungs_in": [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0],   # a level is always one of these: sizes are rounded down
    "min_storms": 10,           # storms in a band before it can set the "likely" level
    "likely_share": 0.5,        # "likely": an overflow was reported after at least half of the storms
    "quiet_min_storms": 30,     # no caution under the lowest reported overflow only on this many storms, none followed
    "quiet_min_period_days": 1095,   # ... over at least three years of record
    "min_report_storms": 10,    # storms followed by a report before a history is used at all
    "min_total_storms": 20,
    "min_period_days": 365,
    "max_span_days": 7,
    "gap_days": 365,            # no report for this long, with storms, is a reporting gap
    "gap_min_storms": 10,
    "lag_days": 14,             # the newest days are not counted yet: a report can arrive late
    "change_z": 3.0,            # how sharp a change at a year boundary cuts the record
    "change_min_storms": 20,    # storms on each side of the boundary
    "change_min_days_after": 730,
    "outfall_named_share": 0.9,  # an operator's reports name the outfall this often before outfalls get their own
    "outfall_min_report_storms": 10,
}


def load_levels(build_path=None, seed_path=None) -> dict | None:
    """The levels file the status build reads: the daily pass's copy when it is there and of this method version,
    else the repository's copy, else None (every operator then keeps the rule it had before)."""
    for path in (LEVELS_BUILD if build_path is None else build_path, LEVELS_SEED if seed_path is None else seed_path):
        try:
            d = read_json(path, None) if path and path.exists() else None
        except ValueError:
            d = None
        if isinstance(d, dict) and d.get("method_version") == METHOD_VERSION and isinstance(d.get("permits"), dict):
            return d
    return None


def settings(rules: dict | None) -> dict:
    given = (((rules or {}).get("rain_likely") or {}).get("history") or {})
    return {**DEFAULTS, **{k: given[k] for k in DEFAULTS if given.get(k) is not None}}


# ---------------------------------------------------------------- reports

def parse_instant(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return t


def rain_day(s, precision: str | None) -> date | None:
    """The rain-record day of a report time: the day the source gives for a day-precision time (or one with no
    offset), else the instant's America/Chicago calendar day."""
    if not s:
        return None
    text = str(s).strip()
    if precision == "day" or len(text) <= 10:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    t = parse_instant(text)
    if t is None:
        return None
    return t.astimezone(RAIN_ZONE).date() if t.tzinfo else t.date()


def is_advisory(r: dict) -> bool:
    """A system-wide risk advisory (common.system_wide_advisory) or an authority's advisory naming a water that keeps
    the rain caution (raw.keeps_rain_caution): not a report that an overflow happened, as rain_likely.discharge_starts
    reads them."""
    from common import system_wide_advisory
    raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
    return bool(system_wide_advisory(r) or raw.get("keeps_rain_caution") is True)


def report_spans(records: list[dict], permit_of, skip=frozenset(), cfg: dict | None = None) -> dict[str, list[dict]]:
    """{permit: [{first, last, outfall, precision, source_id, event_id, started_at}]} for every dated combined sewer
    discharge report (started_at as the source gives it). permit_of(record) gives the record's permit (or None); skip:
    (PERMIT, OUTFALL) of structures outside the rain caution. Also returns, under the key None, the counts of what was
    left out and why (copies, monthly_or_yearly, advisories, not_rain_driven, no_start). Pure."""
    cfg = cfg or DEFAULTS
    out: dict = defaultdict(list)
    left = defaultdict(lambda: defaultdict(int))
    for r in records:
        if r.get("event_type") not in WET_TYPES:
            continue
        permit = permit_of(r)
        if not permit:
            continue
        if is_advisory(r):
            left[permit]["advisories"] += 1
            continue
        if r.get("duplicate_of"):
            left[permit]["copies"] += 1
            continue
        prec = r.get("time_precision")
        if prec in ("month", "year"):
            left[permit]["monthly_or_yearly"] += 1
            continue
        oid = str(r.get("outfall_id") or "").strip().upper()
        if (permit.upper(), oid) in skip:
            left[permit]["not_rain_driven"] += 1
            continue
        d0 = rain_day(r.get("started_at"), prec)
        if d0 is None:
            left[permit]["no_start"] += 1
            continue
        d1 = rain_day(r.get("ended_at"), prec) or d0
        d1 = min(max(d1, d0), d0 + timedelta(days=int(cfg["max_span_days"])))
        out[permit].append({"first": d0, "last": d1, "outfall": oid or None, "precision": prec or "minute",
                            "source_id": r.get("source_id"), "event_id": r.get("event_id"),
                            "started_at": r.get("started_at")})
    out[None] = {p: dict(v) for p, v in left.items()}
    return dict(out)


# ---------------------------------------------------------------- storms

def daily_max(series: list[dict[date, float]]) -> dict[date, float]:
    """The largest daily total over the operator's rain points, day by day (a day missing at every point is missing)."""
    out: dict[date, float] = {}
    for s in series:
        for d, v in s.items():
            if v is not None and (d not in out or v > out[d]):
                out[d] = float(v)
    return out


def storms(daily: dict[date, float], first: date, last: date, min_in: float = 0.1) -> list[dict]:
    """Runs of consecutive days at or above min_in between first and last (inclusive): [{first, last, size, peak_day}].
    A day with no value ends a run (it is not read as dry or wet). Pure."""
    out, cur = [], None
    d = first
    while d <= last:
        v = daily.get(d)
        if v is not None and v >= min_in:
            if cur is None:
                cur = {"first": d, "last": d, "size": v, "peak_day": d}
            else:
                cur["last"] = d
                if v > cur["size"]:
                    cur["size"], cur["peak_day"] = v, d
        else:
            if cur is not None:
                out.append(cur)
                cur = None
        d += timedelta(days=1)
    if cur is not None:
        out.append(cur)
    return out


def mark_followed(sts: list[dict], spans: list[dict]) -> list[dict]:
    """Each storm with followed: whether a report covers a day from its first day to the day after its last. Pure."""
    days = set()
    for s in spans:
        d = s["first"]
        while d <= s["last"]:
            days.add(d)
            d += timedelta(days=1)
    out = []
    for st in sts:
        d, hit = st["first"], False
        while d <= st["last"] + timedelta(days=1):
            if d in days:
                hit = True
                break
            d += timedelta(days=1)
        out.append({**st, "followed": hit})
    return out


# ---------------------------------------------------------------- the period of record

def gaps(spans: list[dict], sts: list[dict], first: date, last: date, cfg: dict) -> list[tuple[date, date]]:
    """Stretches with no report for gap_days or more in which at least gap_min_storms storms fell: [(from, to)],
    the days strictly between two reports (or from the start of the period to the first report in it, or after the
    last one to the end of the period). Pure."""
    marks = sorted({s["last"] for s in spans} | {s["first"] for s in spans})
    edges = [first - timedelta(days=1)] + [d for d in marks if first <= d <= last]
    out = []
    pairs = list(zip(edges, edges[1:])) + ([(edges[-1], last + timedelta(days=1))] if edges else [])
    covered = set()
    for s in spans:
        d = s["first"]
        while d <= s["last"]:
            covered.add(d)
            d += timedelta(days=1)
    for a, b in pairs:
        if (b - a).days < int(cfg["gap_days"]):
            continue
        g0, g1 = a + timedelta(days=1), b - timedelta(days=1)
        if any(d in covered for d in (g0, g1)):
            continue
        n = sum(1 for st in sts if g0 <= st["first"] and st["last"] <= g1)
        if n >= int(cfg["gap_min_storms"]):
            out.append((g0, g1))
    return out


def in_gap(st: dict, gap_list: list[tuple[date, date]]) -> bool:
    return any(g0 <= st["first"] and st["last"] <= g1 for g0, g1 in gap_list)


def drop_gaps(sts: list[dict], gap_list: list[tuple[date, date]]) -> list[dict]:
    """The storms outside the reporting gaps. A storm followed by a report is never dropped (a storm on a gap's last
    day can be followed by the next day's report: that report is evidence, not a gap). Pure."""
    return [st for st in sts if st["followed"] or not in_gap(st, gap_list)]


def change_point(sts: list[dict], last: date, cfg: dict) -> dict | None:
    """The year boundary at which the share of storms followed by a report changed sharply (a two-proportion
    z of change_z or more, change_min_storms storms on each side, at least change_min_days_after of record after it):
    {year, before: [followed, storms], after: [followed, storms], z}; None when there is none. Of several such
    boundaries the sharpest (largest |z|; the later on a tie). Only storms of the second rung up are compared: the smallest storms say little about the system. Pure."""
    floor = float(cfg["rungs_in"][1]) if len(cfg["rungs_in"]) > 1 else float(cfg["rungs_in"][0])
    big = [s for s in sts if s["size"] >= floor]
    years = sorted({s["first"].year for s in big})
    best = None
    for y in years[1:]:
        cut = date(y, 1, 1)
        if (last - cut).days < int(cfg["change_min_days_after"]):
            continue
        a = [s for s in big if s["first"] < cut]
        b = [s for s in big if s["first"] >= cut]
        if len(a) < int(cfg["change_min_storms"]) or len(b) < int(cfg["change_min_storms"]):
            continue
        ha, hb = sum(s["followed"] for s in a), sum(s["followed"] for s in b)
        p = (ha + hb) / (len(a) + len(b))
        se = math.sqrt(p * (1 - p) * (1 / len(a) + 1 / len(b)))
        if se == 0:
            continue
        z = (hb / len(b) - ha / len(a)) / se
        if abs(z) >= float(cfg["change_z"]):
            cand = {"year": y, "before": [ha, len(a)], "after": [hb, len(b)], "z": round(z, 2)}
            if best is None or (abs(z), y) > (abs(best["z"]), best["year"]):
                best = cand
    return best


# ---------------------------------------------------------------- bands and levels

def band_counts(sts: list[dict], rungs: list[float]) -> list[dict]:
    """[{lo, hi, storms, followed}] by rain band (hi None for the last): each storm in the band of its size."""
    out = [{"lo": lo, "hi": (rungs[i + 1] if i + 1 < len(rungs) else None), "storms": 0, "followed": 0}
           for i, lo in enumerate(rungs)]
    for st in sts:
        for c in reversed(out):
            if st["size"] >= c["lo"]:
                c["storms"] += 1
                c["followed"] += 1 if st["followed"] else 0
                break
    return out


def _merge(a: dict, b: dict) -> dict:
    return {"lo": a["lo"], "hi": b["hi"], "storms": a["storms"] + b["storms"], "followed": a["followed"] + b["followed"]}


def pool_thin(bands: list[dict], min_storms: int) -> list[dict]:
    """Pool a band with fewer than min_storms storms into the band below it, from the largest storms down (so a
    pooled band's lower edge only ever moves down: rounding down); a thin remainder at the bottom joins the band
    above it. Pure."""
    out: list[dict] = []
    cur = None
    for c in reversed(bands):
        cur = dict(c) if cur is None else _merge(c, cur)
        if cur["storms"] >= min_storms:
            out.insert(0, cur)
            cur = None
    if cur is not None:
        out = [_merge(cur, out[0])] + out[1:] if out else [cur]
    return out


def lowest_reported(sts: list[dict], rungs: list[float], spans: list[dict] | None = None) -> dict | None:
    """The smallest storm followed by a reported overflow, and that size rounded down to a rung:
    {size_in, day, rounded_in, report_day, report}; None when no storm was followed by a report. report cites the
    earliest report covering the storm's window (its first day to the day after its last): {event_id, source_id,
    started_at}; report_day is that report's first day (None, None without spans). Pure."""
    hit = [s for s in sts if s["followed"]]
    if not hit:
        return None
    s = min(hit, key=lambda x: (x["size"], x["first"]))
    rung = max((r for r in rungs if r <= s["size"] + 1e-9), default=rungs[0])
    out = {"size_in": round(s["size"], 2), "day": s["peak_day"].isoformat(), "rounded_in": rung,
           "report_day": None, "report": None}
    w1 = s["last"] + timedelta(days=1)
    cover = [x for x in spans or [] if x["first"] <= w1 and x["last"] >= s["first"]]
    if cover:
        c = min(cover, key=lambda x: (x["first"], str(x.get("started_at") or ""), str(x.get("event_id") or "")))
        out["report_day"] = c["first"].isoformat()
        out["report"] = {"event_id": c.get("event_id"), "source_id": c.get("source_id"), "started_at": c.get("started_at")}
    return out


def likely_from(bands: list[dict], floor_in: float, cfg: dict) -> float | None:
    """The smallest rain that reads "likely": the lower edge of the lowest band (thin bands pooled downward) at or above
    floor_in in which an overflow was reported after at least likely_share of the storms, and after at least that share
    of all larger storms taken together. None when no band reaches it. Pure."""
    # only the bands at or above floor_in are pooled: a thin band below it never drags a band at it below the floor
    pooled = pool_thin([b for b in bands if b["lo"] >= floor_in - 1e-9], int(cfg["min_storms"]))
    bar = float(cfg["likely_share"]) - 1e-9
    for i, c in enumerate(pooled):
        if c["lo"] < floor_in - 1e-9 or c["storms"] < int(cfg["min_storms"]):
            continue
        n = sum(x["storms"] for x in pooled[i:])
        k = sum(x["followed"] for x in pooled[i:])
        if c["followed"] / c["storms"] >= bar and k / n >= bar:
            return c["lo"]
    return None


def count_range(sts: list[dict], lo: float, hi: float | None) -> dict:
    sel = [s for s in sts if s["size"] >= lo - 1e-9 and (hi is None or s["size"] < hi - 1e-9)]
    n, k = len(sel), sum(1 for s in sel if s["followed"])
    return {"lo": lo, "hi": hi, "storms": n, "followed": k, "share": round(k / n, 3) if n else None}


def usable(sts: list[dict], first: date | None, last: date | None, cfg: dict, observed: int | None = None) -> str | None:
    """None when the history can be used; else the reason it cannot, in plain words. observed: the days of the
    period with a rain value outside the stretches left out (observed_days); the calendar span when not given."""
    n, k = len(sts), sum(1 for s in sts if s["followed"])
    if first is None or last is None:
        return "no dated overflow report in the record"
    if k < int(cfg["min_report_storms"]):
        return f"{k} storm{'s' if k != 1 else ''} followed by a report; {cfg['min_report_storms']} are needed"
    if n < int(cfg["min_total_storms"]):
        return f"{n} storm{'s' if n != 1 else ''} on record; {cfg['min_total_storms']} are needed"
    days = (last - first).days + 1 if observed is None else observed
    if days < int(cfg["min_period_days"]):
        return f"{days} day{'s' if days != 1 else ''} of rain record; {cfg['min_period_days']} are needed"
    return None


def analyse(daily: dict[date, float], spans: list[dict], coverage_end: date, cfg: dict, today: date,
            cuts: list[dict] | None = None) -> dict:
    """One operator's evidence from its rain days and its report spans. cuts: cited system changes
    ([{from: date, ...}]: the record starts at the latest). Pure."""
    spans = sorted(spans, key=lambda s: (s["first"], s["last"]))
    first = max(FIRST_DAY, min(s["first"] for s in spans)) if spans else None
    last = min(coverage_end, today) - timedelta(days=int(cfg["lag_days"]))     # late reports: the newest days wait
    if first is None or first > last or max(s["first"] for s in spans) < FIRST_DAY:
        if spans and max(s["first"] for s in spans) < FIRST_DAY:
            why = "its dated overflow reports are all from before 2015, where the rain record starts"
        elif spans:
            why = (f"its dated overflow reports are all from the last {cfg['lag_days']} days of its sources' coverage, "
                   "not counted yet because reports can arrive late")
        else:
            why = "no dated overflow report in the record"
        return {"usable": False, "why_not": why, "storms": 0, "followed": 0, "observed_days": 0}
    left_out, notes = [], []
    for c in sorted(cuts or [], key=lambda c: c["from"]):
        if c["from"] > last:
            return {"usable": False, "storms": 0, "followed": 0, "observed_days": 0,
                    "why_not": "a cited change to the system is too recent for any storm after it to be counted"}
        if c["from"] > first:
            left_out.append({"from": first.isoformat(), "to": (c["from"] - timedelta(days=1)).isoformat(),
                             "why": "system_change_cited", "what": c.get("what"), "source": c.get("source")})
            first = c["from"]
    rungs = [float(e) for e in cfg["rungs_in"]]
    every = mark_followed(storms(daily, first, last, rungs[0]), spans)
    gl = gaps(spans, every, first, last, cfg)
    for g0, g1 in gl:
        left_out.append({"from": g0.isoformat(), "to": g1.isoformat(), "why": "reporting_gap",
                         "storms": sum(1 for st in every if in_gap(st, [(g0, g1)]) and not st["followed"])})
    sts = drop_gaps(every, gl)
    share_sts, share_first = sts, first
    cp = change_point(sts, last, cfg)
    if cp and cp["z"] > 0:      # reports became more frequent: the earlier years under-report, their shares are left out
        cut = date(cp["year"], 1, 1)
        left_out.append({"from": first.isoformat(), "to": (cut - timedelta(days=1)).isoformat(), "why": "reported_less_before",
                         "before": cp["before"], "after": cp["after"], "z": cp["z"]})
        share_sts, share_first = [s for s in sts if s["first"] >= cut], cut
    elif cp:                    # reports became less frequent: stated, never cut without a cited change (the safe side)
        notes.append({"what": "reported_less_since", "year": cp["year"], "before": cp["before"], "after": cp["after"],
                      "z": cp["z"]})
    observed = sum(1 for i in range((last - share_first).days + 1)
                   if (d := share_first + timedelta(days=i)) in daily and daily[d] is not None
                   and not any(g0 <= d <= g1 for g0, g1 in gl))
    why = usable(share_sts, share_first, last, cfg, observed)
    bands = band_counts(share_sts, rungs)
    # over every storm of the record, before gaps and the change point remove any: the least rain ever followed
    low = lowest_reported(every, rungs, spans)
    out = {"usable": why is None, "why_not": why, "period": [share_first.isoformat(), last.isoformat()],
           "record_from": first.isoformat(),
           "storms": len(share_sts), "followed": sum(1 for s in share_sts if s["followed"]),
           "reports": sum(1 for s in spans if share_first <= s["first"] <= last),
           "day_precision_reports": sum(1 for s in spans if s["precision"] == "day" and share_first <= s["first"] <= last),
           "left_out": left_out, "notes": notes, "bands": [{**b, "share": round(b["followed"] / b["storms"], 3)
                                                             if b["storms"] else None} for b in bands],
           "lowest_reported": low, "observed_days": observed, "_storms": sts, "_every": every}
    covered = set()
    for st in share_sts:
        d = st["first"]
        while d <= st["last"] + timedelta(days=1):
            covered.add(d)
            d += timedelta(days=1)
    out["reports_with_no_storm"] = sum(1 for s in spans if share_first <= s["first"] <= last and not any(
        s["first"] + timedelta(days=i) in covered for i in range((s["last"] - s["first"]).days + 1)))
    if why is None and low is not None:
        p_in = low["rounded_in"]
        l_in = likely_from(bands, p_in, cfg)
        # counted over the years the shares use: years that under-report cannot show that small storms are quiet
        quiet = count_range(share_sts, rungs[0], p_in) if p_in > rungs[0] else None
        out["possible_in"] = p_in
        out["likely_in"] = l_in
        # "enough" needs the count and the years: one wet year of small storms is not a record of a quiet system
        long_enough = observed >= int(cfg["quiet_min_period_days"])
        out["quiet"] = ({**quiet, "enough": quiet["storms"] >= int(cfg["quiet_min_storms"]) and quiet["followed"] == 0
                         and long_enough} if quiet else None)
        out["possible"] = count_range(share_sts, p_in, l_in) if l_in is None or l_in > p_in else None
        out["likely"] = count_range(share_sts, l_in, None) if l_in is not None else None
    return out


# ---------------------------------------------------------------- rain points

def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def rain_points(points, max_points: int = 4, min_sep_km: float = 8.0) -> list[tuple[float, float]]:
    """The points the rain record is read at for one operator: the median of its outfall points (0.01 degree), then
    repeatedly the outfall point farthest from those chosen, while it is more than min_sep_km away, up to max_points
    (a spread-out system is read where its outfalls are; the live check takes the wettest outfall). Pure."""
    raw = [(float(a), float(b)) for a, b in points if a is not None and b is not None]
    if not raw:
        return []
    # the median over every outfall point, as build.rain_thresholds.centroid (the same cached files)
    chosen = [(round(statistics.median(p[0] for p in raw), 2), round(statistics.median(p[1] for p in raw), 2))]
    pts = sorted({(round(a, 2), round(b, 2)) for a, b in raw})
    while len(chosen) < max_points:
        far, dist = None, -1.0
        for p in pts:
            d = min(_km(p, c) for c in chosen)
            if d > dist:
                far, dist = p, d
        if far is None or dist <= min_sep_km:
            break
        chosen.append(far)
    return chosen


# ---------------------------------------------------------------- per outfall

def outfall_evidence(spans: list[dict], sts: list[dict], a: dict, cfg: dict, every: list[dict] | None = None) -> dict | None:
    """{outfall key: {reports, storms, followed, lowest_reported, possible, likely}} from the reports that name each
    outfall, against the operator's storms in the period its shares use; None unless the operator's reports in that
    period name an outfall at least outfall_named_share of the time. possible and likely are the outfall's own
    followed counts inside the operator's ranges; lowest_reported is over every storm of the record (every, when
    given), citing the outfall's report. Pure."""
    from build.rain_thresholds import outfall_key
    if not a.get("period"):
        return None
    p0, p1 = (date.fromisoformat(x) for x in a["period"])
    rec0 = date.fromisoformat(a["record_from"])
    inside = [s for s in spans if p0 <= s["first"] <= p1]
    if not inside or sum(1 for s in inside if s.get("outfall")) / len(inside) < float(cfg["outfall_named_share"]) - 1e-9:
        return None
    by: dict[str, list[dict]] = defaultdict(list)
    for s in spans:
        k = outfall_key(s.get("outfall"))
        if k:
            by[k].append(s)
    rungs = [float(e) for e in cfg["rungs_in"]]
    out = {}
    for k, sp in sorted(by.items()):
        if not any(rec0 <= s["first"] <= p1 for s in sp):
            continue
        marked = mark_followed(sts, sp)
        share = [s for s in marked if s["first"] >= p0]
        row = {"reports": sum(1 for s in sp if p0 <= s["first"] <= p1), "storms": len(share),
               "followed": sum(1 for s in share if s["followed"]),
               "lowest_reported": lowest_reported(mark_followed(every, sp) if every is not None else marked, rungs, sp),
               "possible": None, "likely": None}
        for name in ("possible", "likely"):
            r = a.get(name)
            if r:
                c = count_range(share, r["lo"], r["hi"])
                row[name] = {"lo": c["lo"], "hi": c["hi"], "storms": c["storms"], "followed": c["followed"]}
        out[k] = row
    return out or None


# ---------------------------------------------------------------- the cross-check with the live readings

def crosscheck(hist: dict | None, daily_by_permit: dict[str, dict[date, float]], since: datetime | None = None,
               min_in: float = 0.05) -> dict:
    """The live hourly readings (data/build/rainfall-history.json: values[i] is the largest 24-hour total over the
    operator's outfalls for the 24 hours ending at start + i hours, UTC) against this record: at each America/Chicago
    midnight, the live value for the 24 hours ending then against the record's total for the day that ends then,
    where either is at least min_in. Pure."""
    note = ("the live check's saved 24-hour radar total for the operator, for the 24 hours ending at each midnight, "
            "America/Chicago, against this record's total for that calendar day (the wettest rain point), where "
            f"either is at least {min_in} inch; an indication only while the saved live readings are incomplete "
            "(hours with no reading for an operator are not compared)")
    empty = {"from": None, "to": None, "operators": 0, "comparisons": 0, "live_higher": 0,
             "median_live_over_record": None}
    try:
        start = datetime.fromisoformat(str((hist or {}).get("start")).replace("Z", "+00:00"))
        step = int((hist or {}).get("step_hours") or 1)
    except (TypeError, ValueError):
        return {**empty, "note": "No saved live rainfall readings are available to compare yet."}
    rows, ratios, ops, t_min, t_max = 0, [], set(), None, None
    higher = 0
    for permit, values in sorted(((hist or {}).get("permits") or {}).items()):
        daily = daily_by_permit.get(permit)
        if not daily or not isinstance(values, list):
            continue
        for i, live in enumerate(values):
            if live is None:
                continue
            t = start + timedelta(hours=i * step)
            if since is not None and t - timedelta(hours=24) < since:
                continue
            loc = t.astimezone(RAIN_ZONE)
            if loc.hour or loc.minute:
                continue
            rec = daily.get(loc.date() - timedelta(days=1))
            if rec is None or max(live, rec) < min_in:
                continue
            rows += 1
            ops.add(permit)
            higher += 1 if live > rec else 0
            if live >= min_in and rec >= min_in:
                ratios.append(live / rec)
            t_min = t if t_min is None or t < t_min else t_min
            t_max = t if t_max is None or t > t_max else t_max
    if not rows:
        return {**empty, "note": "no day in which both the live readings and this record have a value yet: " + note}
    iso = lambda t: t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")   # noqa: E731
    return {"from": iso(t_min), "to": iso(t_max), "operators": len(ops), "comparisons": rows, "live_higher": higher,
            "median_live_over_record": round(statistics.median(ratios), 2) if ratios else None, "note": note}


# ---------------------------------------------------------------- the daily pass

RAIN_RECORD = {"source_id": "iem-iemre-mrms-daily",
               "name": "NOAA MRMS daily rainfall totals, from the Iowa Environmental Mesonet reanalysis point service",
               "url": "https://mesonet.agron.iastate.edu/iemre/", "first_day": FIRST_DAY.isoformat(),
               "day": "America/Chicago calendar days"}
METHOD_TEXT = ("Each operator's storms since 2015 (runs of days with at least 0.1 inch of rain at its combined sewer "
               "outfalls, NOAA MRMS radar) are paired with its own dated overflow reports. Discharge is possible from "
               "the smallest storm it ever reported an overflow after, rounded down to a step, and likely from the "
               "smallest step at which it reported an overflow after at least half of the storms of that size and of "
               "all larger storms together. Below the possible amount no caution is shown only when at least 30 storms "
               "that small are on record and none was followed by a report.")
NO_REPORT = "no dated overflow report from this operator in a source this site reads"
NOT_READ = "the rain record for this operator has not been read yet"
FRESH_S = 7 * 86400            # the current year at a point is asked again at most weekly
DEFAULT_BUDGET = 1500
# The live readings are compared from the unit repair on (rainfall-history.json units_repair): earlier hours may be
# millimetres read as inches.
LIVE_HISTORY = BUILD_DIR / "rainfall-history.json"
ENTRY_KEYS = {"usable": False, "why_not": None, "period": None, "record_from": None, "storms": 0, "followed": 0,
              "reports": 0, "reports_with_no_storm": 0, "day_precision_reports": 0, "bands": [],
              "lowest_reported": None, "possible_in": None, "likely_in": None, "quiet": None, "possible": None,
              "likely": None, "left_out": [], "notes": [], "sources": [], "points": [], "outfalls": None,
              "observed_days": 0}
NOT_USED = ("copies", "monthly_or_yearly", "advisories", "not_rain_driven", "no_start")


def source_coverage(records: list[dict], today: date) -> date | None:
    """The end of a source's coverage: its latest dated combined sewer discharge report (any operator; advisories
    are not reports), capped at today. Pure."""
    best = None
    for r in records:
        if r.get("event_type") not in WET_TYPES or r.get("time_precision") in ("month", "year") or is_advisory(r):
            continue
        d = rain_day(r.get("started_at"), r.get("time_precision"))
        if d is not None and (best is None or d > best):
            best = d
    return min(best, today) if best else None


def _events_sources():
    from common import EVENTS_DIR
    for f in sorted(EVENTS_DIR.glob("*.json")):
        if f.name.startswith("fixture"):
            continue
        try:
            d = read_json(f, {}) or {}
        except ValueError:
            print(f"rain_history: {f.name} unreadable, left out")
            continue
        yield f.stem, (d.get("records") or []) if isinstance(d, dict) else []


def _iem_reader(lat, lon, years, offline, budget):
    from build.rain_thresholds import iem_daily
    return iem_daily(lat, lon, years, offline=offline, budget=budget, fresh_s=FRESH_S)


def _iem_have(lat, lon, years) -> bool:
    """Every point-year is in the cache with real content: a readable answer holding at least one day's MRMS value
    (an empty or unreadable file is no record)."""
    from build.rain_thresholds import IEM_DIR
    for y in years:
        p = IEM_DIR / f"{lat:.2f}_{lon:.2f}_{y}.json"
        try:
            rows = (json.loads(p.read_text()) or {}).get("data") or []
        except (OSError, ValueError, AttributeError):
            return False
        if not any(isinstance(r, dict) and r.get("mrms_precip_in") is not None for r in rows):
            return False
    return True


def missing_years(daily: dict[date, float], years: list[int], today: date) -> list[int]:
    """The years needed with no day's value at any point (the current year only once a week of it has passed). Pure."""
    have = {d.year for d, v in daily.items() if v is not None}
    return [y for y in years if y not in have and not (y == today.year and today < date(y, 1, 8))]


def _round(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    return x


def _cuts(rules: dict | None) -> dict[str, list[dict]]:
    given = ((((rules or {}).get("rain_likely") or {}).get("history") or {}).get("system_changes") or {})
    out = {}
    for permit, rows in given.items() if isinstance(given, dict) else []:
        for r in rows or []:
            try:
                out.setdefault(permit, []).append({**r, "from": date.fromisoformat(str(r["from"])[:10])})
            except (KeyError, TypeError, ValueError):
                print(f"rain_history: rules system_changes {permit}: a row with no readable 'from' left out")
    return out


def _live_since(hist: dict | None) -> datetime | None:
    ranges = ((hist or {}).get("units_repair") or {}).get("ranges") or []
    try:
        return min(datetime.fromisoformat(str(r[0]).replace("Z", "+00:00")) for r in ranges) if ranges else None
    except (TypeError, ValueError, IndexError):
        return None


def build(offline: bool = False, budget: int = DEFAULT_BUDGET, only=None, today: date | None = None,
          now: datetime | None = None, *, sources=None, outfalls=None, skip=None, rules=None, prev=None,
          by_discharger=None, reader=None, have=None, live_history=None, out_path=None, write: bool = True) -> dict:
    """The levels file (spec: rain-history-spec.md section 1). Every input can be given (the tests); by default the
    events files, the outfall registry, data/rules.json, the previous levels file, the point service and the live
    readings are read. Writes out_path (data/build/rain-levels.json) atomically when write is true."""
    from build.rain_thresholds import BudgetSpent, RequestBudget, ServiceRefused, permits_by_discharger, record_permit
    now = now or datetime.now(UTC)
    today = today or now.date()
    if rules is None:
        rules = read_json(DATA_DIR / "rules.json", {}) or {}
    cfg = settings(rules)
    if outfalls is None:
        from common import live_states
        from ingest.rainfall import cso_outfalls
        outfalls = cso_outfalls(set(live_states()))
    if skip is None:
        from build.rain_likely import not_rain_driven
        from common import load_outfall_registry
        skip = not_rain_driven(load_outfall_registry(DATA_DIR))
    if by_discharger is None:
        by_discharger = permits_by_discharger()
    if prev is None:
        prev = load_levels() or {}
    if sources is None:
        sources = _events_sources()
    if live_history is None:
        live_history = read_json(LIVE_HISTORY, None)
    reader = reader or _iem_reader
    have = have or _iem_have
    cuts = _cuts(rules)
    prev_permits = (prev or {}).get("permits") or {} if (prev or {}).get("method_version") == METHOD_VERSION else {}

    reg: dict[str, list[dict]] = defaultdict(list)
    for o in outfalls:
        reg[o["permit"]].append(o)

    def permit_of(r):
        p = record_permit(r, by_discharger)
        return p if p in reg else None

    spans: dict[str, list[dict]] = defaultdict(list)
    left: dict[str, dict] = defaultdict(lambda: dict.fromkeys(NOT_USED, 0))
    per_source: dict[str, dict[str, dict]] = defaultdict(dict)
    for sid, recs in sources:
        for r in recs:
            if not r.get("source_id"):
                r["source_id"] = sid
        got = report_spans(recs, permit_of, skip, cfg)
        lo = got.pop(None, {}) or {}
        for p, counts in lo.items():
            for k, v in counts.items():
                left[p][k] = left[p].get(k, 0) + v
        if not got:
            continue
        end = source_coverage(recs, today)
        for p, v in got.items():
            for s in v:
                s["source_id"] = s.get("source_id") or sid
            spans[p] += v
            per_source[p][sid] = {"source_id": sid, "reports": len(v), "first": min(s["first"] for s in v).isoformat(),
                                  "last": max(s["first"] for s in v).isoformat(),
                                  "coverage_end": end.isoformat() if end else None}

    want = {p.upper() for p in only} if only else None
    order = sorted(reg, key=lambda p: (-len(spans.get(p) or []), p))
    bud = RequestBudget(budget)
    stopped = None
    permits: dict[str, dict] = {}
    daily_by_permit: dict[str, dict[date, float]] = {}
    not_read = 0
    for p in order:
        rows = reg[p]
        name = next((o.get("name") for o in rows if o.get("name")), None)
        state = next((o.get("state") for o in rows if o.get("state")), p[:2])
        base = {**ENTRY_KEYS, "permit": p, "name": name, "state": state, "computed": today.isoformat(),
                "method_version": METHOD_VERSION,
                "not_used": dict(left[p]) if p in left else dict.fromkeys(NOT_USED, 0),
                "sources": sorted(per_source.get(p, {}).values(), key=lambda s: s["source_id"])}
        sp = spans.get(p) or []
        if want is not None and p.upper() not in want:
            if p in prev_permits:
                permits[p] = prev_permits[p]
            else:
                permits[p] = {**base, "why_not": NOT_READ if sp else NO_REPORT}
                not_read += 1 if sp else 0
            continue
        if not sp:
            permits[p] = {**base, "why_not": NO_REPORT}
            continue
        pts = rain_points([(o["lat"], o["lon"]) for o in rows])
        base["points"] = [list(x) for x in pts]
        first = max(FIRST_DAY, min(s["first"] for s in sp))
        years = list(range(min(first.year, today.year), today.year + 1))
        cover = max((date.fromisoformat(s["coverage_end"]) for s in base["sources"] if s["coverage_end"]), default=today)
        series = []
        if stopped is None and not offline:
            try:
                series = [reader(lat, lon, years, False, bud) for lat, lon in pts]
            except (BudgetSpent, ServiceRefused) as e:
                stopped = f"{type(e).__name__} at {p}: {e}"
                print(f"rain_history: stopped asking the point service ({stopped}); the next run continues from the cache")
                series = []
        if not series:
            if all(have(lat, lon, years) for lat, lon in pts):
                series = [reader(lat, lon, years, True, None) for lat, lon in pts]
        elif not all(have(lat, lon, years) for lat, lon in pts):
            series = []             # a year at a point not read (a failed request): incomplete, not used
        daily = daily_max(series) if series else {}
        if not series or missing_years(daily, years, today):
            # never computed from a rain record missing a year it needs: the previous entry stays, else "not read"
            not_read += 1
            permits[p] = prev_permits[p] if p in prev_permits else {**base, "why_not": NOT_READ}
            continue
        daily_by_permit[p] = daily
        a = analyse(daily, sp, cover, cfg, today, cuts.get(p))
        sts = a.pop("_storms", None)
        every = a.pop("_every", None)
        entry = {**base, **a}
        if sts is not None:
            entry["outfalls"] = outfall_evidence(sp, sts, a, cfg, every)
        permits[p] = entry

    entries = {p: permits[p] for p in sorted(permits)}
    usable_n = sum(1 for e in entries.values() if e.get("usable"))
    out = {"method_version": METHOD_VERSION, "built": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "today": today.isoformat(), "method": METHOD_TEXT, "rain_record": RAIN_RECORD,
           "settings": cfg,
           "crosscheck": crosscheck(live_history, daily_by_permit, _live_since(live_history)),
           "counts": {"permits": len(entries), "usable": usable_n,
                      "with_quiet_range": sum(1 for e in entries.values() if e.get("usable")
                                              and (e.get("quiet") or {}).get("enough")),
                      "never_likely": sum(1 for e in entries.values() if e.get("usable") and e.get("likely_in") is None)},
           "run": {"requests": bud.used, "budget": budget, "failures": bud.failures, "stopped": stopped,
                   "not_read": not_read, "offline": offline},
           "permits": entries}
    out = _round(out)
    if write:
        _write(out_path or LEVELS_BUILD, out)
    return out


def _write(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)


def fresh_enough(hours: float, path=None, now: datetime | None = None) -> bool:
    """Whether the build copy is of this method version and was built less than `hours` ago (the hourly refresh then
    leaves it alone: a daily pass)."""
    path = LEVELS_BUILD if path is None else path
    try:
        d = read_json(path, None) if path.exists() else None
    except ValueError:
        return False
    if not isinstance(d, dict) or d.get("method_version") != METHOD_VERSION:
        return False
    try:
        built = datetime.fromisoformat(str(d.get("built")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return ((now or datetime.now(UTC)) - built) < timedelta(hours=hours)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--offline", action="store_true", help="read only the cached rain record")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="point-service requests this run")
    ap.add_argument("--only", nargs="+", metavar="PERMIT", help="read these permits; the others keep their entries")
    ap.add_argument("--if-older-h", type=float, default=None, metavar="H",
                    help="do nothing when the build copy is of this method version and younger than H hours")
    a = ap.parse_args(argv)
    if a.if_older_h is not None and fresh_enough(a.if_older_h):
        print(f"rain_history: {LEVELS_BUILD.name} is younger than {a.if_older_h:g} hours; nothing to do")
        return 0
    d = build(offline=a.offline, budget=a.budget, only=a.only)
    c, r, x = d["counts"], d["run"], d["crosscheck"]
    print(f"rain_history: {c['permits']} permits, {c['usable']} usable ({c['with_quiet_range']} with a quiet range, "
          f"{c['never_likely']} never likely); {r['requests']} requests, {r['not_read']} not read"
          + (f"; stopped: {r['stopped']}" if r["stopped"] else ""))
    print(f"rain_history: cross-check {x['comparisons']} comparisons at {x['operators']} operators, live higher in "
          f"{x['live_higher']}, median live/record {x['median_live_over_record']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
