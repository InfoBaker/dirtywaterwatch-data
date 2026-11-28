"""The rain caution for separate sanitary sewers (owner, 2026-11-16: "Yes, build the rain caution for those 28 operators").

    python -m build.rain_sso [--offline] [--budget N] [--if-older-h H]     (the daily pass, beside build.rain_history)

The assessment it builds (site repository docs/analysis/2026-11-16-sources-where-reports-lack.md section 6): a separate
sewer has no overflow outfall, but it overflows in heavy rain at manholes and pump stations. For an operator whose own
dated overflow reports show a strong rain signal, our caution shows while radar rain is heavy, on the stretches below
the points where its past rain-driven reports were made, and nowhere else. The test, the guards and the operators are
pinned in data/rules.json rain_likely.separate_sewers; with its switch off nothing here runs and every output is what it
was, byte for byte.

The test (rain_history's own method, applied to an operator's sanitary sewer overflow reports; settings() pins it):
  reports      the operator's dated sanitary sewer overflow reports (event_type in event_types; time to the minute, hour
               or day; copies, superseded rows, monthly and yearly figures and advisories left out) from first_day on,
               from sources that pass the late-or-partial rule below
  rain         NOAA MRMS daily totals (the same point service and cache as rain_history) at history_points point(s): the
               median of the operator's report points (the assessment read one point per operator)
  storms, followed, usable, possible_in, likely_in
               rain_history.analyse, unchanged (10 storms followed by a report, 20 storms, a year of record)
  lift         the share of the operator's reports that followed rain (a storm's first day to the day after its last),
               over the share of the period's days that fall in such a window; a strong rain signal is lift >= min_lift
               (1.5). An operator whose overflows are mostly dry-weather blockages and breaks has a lift near 1 and gets
               nothing.
Guards (each is a reason in the file when it fails):
  recency      (owner, 2026-11-16: "Seems like no overflows in a year would be a safe toggle off") out when no
               rain-driven overflow was reported in the recency_months (12) before its source's newest published report
               (the newest start among that source's records for the state; so a feed that runs late does not shorten
               the year); out when that source has published nothing in the last recency_months (silent). Nothing
               else turns it off sooner.
  sources      a source published in batches months after the reports never enters a history (source_ok); and an
               operator is cautioned only when at least one source of its reports is prompt: over its last 12 months
               more than source_min_dated_share of its sewage reports are dated and its median delay to a report is
               at most source_max_lag_days (the coverage grade's own figures, per source, computed here from the
               events this pass reads, so the rule holds on a first run; source_timely). A late source's dated
               reports (Connecticut's annual workbook, 86 days) still count in the history beside the prompt one,
               as the state grade counted them (its delay is the fastest feed's)
  state grade  where the export's state grades are on file (data/build/coverage-grades.json, written by the export
               after this stage), the operator's state must also grade "Dated reports"; with none on file the source
               rule alone applies and the run says so (the first switched-on refresh has none: the export writes it
               after this stage, review of the first run 2026-11-16)
  approved     the caution shows only for operators in the approved first set (the owner's decision of 2026-11-16);
               every other operator is left out, and widening the set is the owner's call
The places: each report that followed rain, with its point, its water records (the status build's placement) and the
event id the status build places it by. The caution is placed only on a traced stretch below those points
(build/reaches: traced from the report's own point); a water reached with no stretch traced yet is named and gets
no mark until one is. A model or a guess never supplies a place.

A required input that is missing (no events files with records, or none of the approved operators in them) stops
the pass with MissingInput: nothing is written, main exits 1 and the refresh keeps the previous file (its `|| echo`
line); a run never writes a file in which nobody qualifies for want of an input. An operator whose rain record was not
read this pass (the service refused part-way, or the budget ran out) keeps its previous entry (the build copy, else the
seed), marked "carried"; a pass that stopped is run again the next hour.

The file: data/build/rain-levels-sso.json (the repository's seed copy is data/rain-levels-sso.json, built from the
site's saved yearly exports by scripts/rain_sso_seed.py; load_levels reads the build copy first).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from build import rain_history as rh
from common import BUILD_DIR, DATA_DIR, read_json
from common import error_detail

METHOD_VERSION = 1
# the file's revision within the method: a build copy of an earlier revision is rebuilt at once rather than kept for
# --if-older-h (2: the first run's file of 2026-11-16, where nobody qualified for want of a grades file and a state key)
FILE_REVISION = 2
LEVELS_BUILD = BUILD_DIR / "rain-levels-sso.json"
LEVELS_SEED = DATA_DIR / "rain-levels-sso.json"
GRADES_FILE = BUILD_DIR / "coverage-grades.json"   # each state's reporting grade, written by the export (switch on)
KEY_PREFIX = "sso:"            # the key the live rainfall readings carry for an operator (ingest/rainfall.py)
POINT_SOURCE = "sso-report-points"
TRACE_SOURCE = "sso-rain-reports"
BASIS = "separate_sewer_history"
DATED = ("minute", "hour", "day")
SEWAGE = {"cso", "sso", "bypass", "blended", "plant_bypass", "unknown", "annual_total"}
# the assessment's test and guards; data/rules.json rain_likely.separate_sewers pins each (settings)
DEFAULTS = {
    "enabled": False,
    "event_types": ["sso"],
    "first_day": "2023-01-01",
    "min_lift": 1.5,
    "history_points": 1,
    "live_points": 4,
    "recency_months": 12,
    "source_min_dated_share": 0.8,
    "source_max_lag_days": 7,
    "approved": [],
}
LABELS = {"likely": "Overflow likely: heavy rain, no report received",       # owner, 2026-11-16: "Use 'Overflow
          "possible": "Overflow possible: heavy rain, no report received"}    # possible' for the separate sewer label"


class MissingInput(RuntimeError):
    """A required input of the daily pass is missing: the pass writes nothing and the previous file stays."""


def settings(rules: dict | None) -> dict:
    given = (((rules or {}).get("rain_likely") or {}).get("separate_sewers") or {})
    out = {**DEFAULTS, **{k: given[k] for k in DEFAULTS if given.get(k) is not None}}
    out["enabled"] = given.get("enabled") is True
    out["labels"] = {**LABELS, **(given.get("label_by_level") or {})}
    out["doc"] = given.get("doc")
    out["source"] = given.get("source")
    return out


def enabled(rules: dict | None) -> bool:
    return settings(rules)["enabled"] and bool(((rules or {}).get("rain_likely") or {}).get("enabled"))


def load_levels(build_path=None, seed_path=None) -> dict | None:
    for path in (LEVELS_BUILD if build_path is None else build_path, LEVELS_SEED if seed_path is None else seed_path):
        try:
            d = read_json(path, None) if path and path.exists() else None
        except ValueError:
            d = None
        if isinstance(d, dict) and d.get("method_version") == METHOD_VERSION and isinstance(d.get("operators"), dict):
            return d
    return None


def load_grades(path=None) -> dict | None:
    """{state: grade} from the last export (export/build.py writes it with the switch on); None when absent."""
    d = read_json(GRADES_FILE if path is None else path, None)
    g = (d or {}).get("states") if isinstance(d, dict) else None
    return g if isinstance(g, dict) and g else None


def grades_of(coverage: dict) -> dict:
    """{state: grade} from out/coverage.json's states."""
    st = (coverage or {}).get("states") or {}
    return {k: v.get("grade") for k, v in st.items() if isinstance(v, dict) and v.get("grade")}


def write_grades(coverage: dict, path=None) -> None:
    """data/build/coverage-grades.json from the export's coverage block (export/build.py calls this after the status
    build, so the daily pass of the same refresh reads the previous export's grades, and the first run none)."""
    rh._write(GRADES_FILE if path is None else path, {"built": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                      "states": grades_of(coverage)})


# ---------------------------------------------------------------- reports

def _pt(r: dict):
    try:
        lat, lon = float(r.get("lat")), float(r.get("lon"))
    except (TypeError, ValueError):
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def sso_spans(records: list[dict], operator_of, cfg: dict, placements: dict | None = None) -> tuple[dict, dict]:
    """({operator: [span]}, {operator: {reason: count}}) for every dated sanitary sewer overflow report from first_day
    on. A span is rain_history's ({first, last, precision, source_id, event_id, started_at}) plus point, water_slugs
    and permit. placements: the status build's (status.json placements), for water_slugs, copies and superseded rows;
    a record's own water_slugs, duplicate_of and superseded_by otherwise. Pure."""
    first_day = date.fromisoformat(str(cfg["first_day"]))
    types = set(cfg["event_types"])
    out: dict = defaultdict(list)
    left: dict = defaultdict(lambda: defaultdict(int))
    for r in records:
        if r.get("event_type") not in types:
            continue
        op = operator_of(r)
        if not op:
            continue
        pl = (placements or {}).get(r.get("event_id")) or {}
        if rh.is_advisory(r):
            left[op]["advisories"] += 1
            continue
        if r.get("duplicate_of") or pl.get("duplicate_of") or r.get("superseded_by") or pl.get("superseded"):
            left[op]["copies"] += 1
            continue
        prec = r.get("time_precision")
        if prec not in DATED:
            left[op]["not_dated_to_the_day"] += 1
            continue
        d0 = rh.rain_day(r.get("started_at"), prec)
        if d0 is None:
            left[op]["no_start"] += 1
            continue
        if d0 < first_day:
            left[op]["before_first_day"] += 1
            continue
        d1 = rh.rain_day(r.get("ended_at"), prec) or d0
        d1 = min(max(d1, d0), d0 + timedelta(days=7))
        slugs = pl.get("water_slugs") if "water_slugs" in pl else r.get("water_slugs")
        out[op].append({"first": d0, "last": d1, "outfall": None, "precision": prec, "source_id": r.get("source_id"),
                        "event_id": r.get("event_id"), "started_at": r.get("started_at"), "point": _pt(r),
                        "water_slugs": [s for s in slugs or [] if isinstance(s, str) and s],
                        "reaches": [k for k in [pl.get("reach"), *(pl.get("reaches") or [])] if k],
                        "permit": r.get("npdes_permit")})
    return dict(out), {k: dict(v) for k, v in left.items()}


def source_figures(records: list[dict], today: date) -> dict:
    """The late-or-partial rule's figures for one source, over the 12 months to today: {records, dated_share,
    lag_days (median days from start to report), latest}. Pure."""
    from export.coverage import is_dated, lag_of
    since = today - timedelta(days=365)
    n, k, lags, latest = 0, 0, [], None
    for r in records:
        if r.get("event_type") not in SEWAGE or r.get("duplicate_of"):
            continue
        d = rh.rain_day(r.get("started_at"), r.get("time_precision") if r.get("time_precision") in DATED else "day")
        if d is None or not since <= d <= today:
            continue
        n += 1
        if is_dated(r):
            k += 1
            latest = d if latest is None or d > latest else latest
            lag = lag_of(r) if not r.get("parent_event_id") else None   # first reports only, as the grade
            if lag is not None:                                          # (an update of a notice comes later)
                lags.append(lag)
    return {"records": n, "dated_share": round(k / n, 3) if n else None,
            "lag_days": round(statistics.median(lags), 2) if lags else None,
            "latest": latest.isoformat() if latest else None}


def source_ok(fig: dict, cfg: dict, batches: bool = False) -> str | None:
    """None when a source's reports may enter a history; else why not, as words that follow "its source <id>": a
    source published in batches months after the reports (Texas's table) never does. Pure."""
    if batches:
        return "is published in batches months after the reports"
    return None


def source_timely(fig: dict, cfg: dict) -> str | None:
    """None when a source publishes dated reports promptly; else why not, as words that follow "its source <id>": over
    its last 12 months it dates source_min_dated_share or less of its sewage reports, or its median delay from a
    discharge to its report is over source_max_lag_days (export/coverage.py's grade figures, per source, the delay over
    first reports; a delay that cannot be read passes, as in the grade); nor one with no sewage report in 12 months
    (a silent prompt source never carries a late one: review 2026-11-16 P1-1). Pure."""
    if not (fig or {}).get("records"):
        return "has published no sewage report in the last 12 months"
    share, lag = fig.get("dated_share"), fig.get("lag_days")
    need = float(cfg["source_min_dated_share"])
    if share is None or share <= need + 1e-9:
        return (f"gives a date for {round(100 * (share or 0))} percent of its sewage reports of the last 12 months "
                f"(more than {round(100 * need)} percent needed)")
    if lag is not None and lag > float(cfg["source_max_lag_days"]) + 1e-9:
        return (f"publishes its reports a median {lag:g} days after the discharge "
                f"(at most {float(cfg['source_max_lag_days']):g} days needed)")
    return None


GRADE_OK = "Dated reports"


def state_grade_ok(state: str | None, grades: dict | None) -> str | None:
    """None when the operator's state grades "Dated reports" (export/coverage.py: over 80 percent dated, the newest
    within 14 days, a delay of at most 7 days); else why not. With no grades on file this check is not made (None):
    the source rule (source_timely, from the events themselves) has already decided timeliness, and the caller says the
    grades were missing; a missing file never turns every operator off (first run, 2026-11-16). Pure."""
    if not grades:
        return None
    g = grades.get(str(state or "").upper())
    if g != GRADE_OK:
        return f"its state's reports grade \"{g or 'not graded'}\", not \"{GRADE_OK}\""
    return None


# ---------------------------------------------------------------- the test

def window_days(sts: list[dict]) -> set[date]:
    out = set()
    for st in sts:
        d = st["first"]
        while d <= st["last"] + timedelta(days=1):
            out.add(d)
            d += timedelta(days=1)
    return out


def follows_rain(span: dict, windows: set[date]) -> bool:
    return any(span["first"] + timedelta(days=i) in windows for i in range((span["last"] - span["first"]).days + 1))


def signal(daily: dict[date, float], spans: list[dict], a: dict) -> dict:
    """The rain signal over the period analyse used (the assessment's lift): {share_follow, baseline, lift}. Pure."""
    sts = a.get("_storms") or []
    per = a.get("period")
    if not per:
        return {"share_follow": None, "baseline": None, "lift": None}
    p0, p1 = date.fromisoformat(per[0]), date.fromisoformat(per[1])
    # the stretches analyse left out (reporting gaps) are out of the days and of the reports alike: one mask for both
    # sides of the ratio (review 2026-11-16 P1-1)
    gaps = [(date.fromisoformat(x["from"]), date.fromisoformat(x["to"])) for x in a.get("left_out") or []
            if x.get("why") == "reporting_gap"]
    out = lambda d: any(g0 <= d <= g1 for g0, g1 in gaps)       # noqa: E731
    win = window_days(sts)
    obs = [d for d in daily if p0 <= d <= p1 and daily[d] is not None and not out(d)]
    base = len([d for d in obs if d in win]) / len(obs) if obs else None
    inside = [s for s in spans if p0 <= s["first"] <= p1 and not out(s["first"])]
    share = sum(1 for s in inside if follows_rain(s, win)) / len(inside) if inside else None
    return {"share_follow": round(share, 3) if share is not None else None,
            "baseline": round(base, 3) if base is not None else None,
            "lift": round(share / base, 2) if share is not None and base else None}


def months_back(d: date, n: int) -> date:
    """The same day n months before d (the month's last day where it has fewer days). Pure."""
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    m += 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def months_between(a: date, b: date) -> int:
    """Whole months from a to b. Pure."""
    return (b.year - a.year) * 12 + b.month - a.month - (1 if b.day < a.day else 0)


def recency(daily: dict[date, float], spans: list[dict], newest_by_source: dict[str, date], cfg: dict, today: date,
            rung: float = 0.1) -> dict:
    """The 12-month rule (owner, 2026-11-16): the operator's newest rain-driven report (a report covering a day from a
    storm's first day to the day after its last, the feature's own rain test), the source it came from, that source's
    newest published report for the state, the months between, silent or not, in or out. Pure."""
    n = int(cfg["recency_months"])
    sts = rh.storms(daily, min(daily), max(daily), rung) if daily else []
    win = window_days(sts)
    rain = [s for s in spans if follows_rain(s, win)]
    if not rain:
        return {"in": False, "newest_rain_report": None, "source": None, "source_newest": None,
                "months_between": None, "silent": False, "why": "no rain-driven overflow report on record"}
    top = max(rain, key=lambda s: (s["first"], str(s.get("source_id"))))
    sid = top.get("source_id")
    anchor = newest_by_source.get(sid)
    out = {"newest_rain_report": top["first"].isoformat(), "source": sid,
           "source_newest": anchor.isoformat() if anchor else None,
           "months_between": months_between(top["first"], anchor) if anchor else None,
           "silent": anchor is None or anchor < months_back(today, n)}
    if out["silent"]:
        return {**out, "in": False, "why": f"its source {sid} has published no report in the last {n} months"
                + (f" (newest {anchor.isoformat()})" if anchor else "")}
    if top["first"] < months_back(anchor, n):
        return {**out, "in": False, "why": f"no rain-driven overflow reported in the {n} months to {anchor.isoformat()}, "
                f"its source's newest report (newest rain-driven report {top['first'].isoformat()})"}
    return {**out, "in": True, "why": None}


def verdict(entry: dict, cfg: dict, today: date, grades: dict | None = None) -> list[str]:
    """Why an operator does not qualify ([] when it does), in plain words, every failing rule. Pure."""
    why = []
    g = state_grade_ok(entry.get("state"), grades)
    if g:
        why.append(g)
    srcs, late = entry.get("sources") or [], entry.get("late_sources") or {}
    if srcs and all(s in late for s in srcs):      # no source of its reports publishes dated reports promptly
        why += [f"its source {s} {late[s]}" for s in srcs]
    if entry.get("op") not in set(cfg["approved"]):
        why.append("not in the approved first set")
    if not entry.get("usable"):
        why.append(f"no usable history: {entry.get('history_why_not') or entry.get('why_not') or 'too few dated overflow reports to test'}")
    lift = entry.get("lift")
    if lift is None or lift < float(cfg["min_lift"]) - 1e-9:
        why.append(f"no strong rain signal (lift {lift if lift is not None else 'not computed'}; "
                   f"{cfg['min_lift']} needed)")
    rc = entry.get("recency")
    if rc is not None and rc.get("in") is not True:
        why.append(rc.get("why") or "no rain-driven overflow reported in the last year")
    return why


def places(spans: list[dict], a: dict) -> dict:
    """The reports that followed rain in the period: their waters (count each), points and event ids. Pure."""
    per = a.get("period")
    if not per:
        return {"reports": 0, "waters": [], "points": [], "events": []}
    p0, p1 = date.fromisoformat(per[0]), date.fromisoformat(per[1])
    win = window_days(a.get("_storms") or [])
    hit = [s for s in spans if p0 <= s["first"] <= p1 and follows_rain(s, win)]
    waters = Counter(w for s in hit for w in dict.fromkeys(s["water_slugs"]))
    events = [{"event_id": s["event_id"], "day": s["first"].isoformat(),
               "point": [round(s["point"][0], 3), round(s["point"][1], 3)] if s["point"] else None,
               "water_slugs": s["water_slugs"], "reaches": s["reaches"]} for s in sorted(hit, key=lambda s: (s["first"], str(s["event_id"])))]
    return {"reports": len(hit), "named_water": sum(1 for s in hit if s["water_slugs"]),
            "with_point": sum(1 for s in hit if s["point"]),
            "waters": [{"water_slug": w, "reports": n} for w, n in sorted(waters.items(), key=lambda x: (-x[1], x[0]))],
            "events": events}


def analyse_operator(op: str, daily: dict[date, float], spans: list[dict], coverage_end: date, cfg: dict,
                     hist_cfg: dict, today: date) -> dict:
    """One operator's entry: rain_history.analyse on its reports, the signal, the recency counts, the places and
    the verdict. Pure."""
    a = rh.analyse(daily, spans, coverage_end, hist_cfg, today)
    sig = signal(daily, spans, a)
    pl = places(spans, a)
    a.pop("_storms", None)
    a.pop("_every", None)
    entry = {"op": op, **a, **sig, "places": pl,
             "newest_report": max(s["first"] for s in spans).isoformat() if spans else None}
    return entry


def report_points(points, n: int = 4, min_sep_km: float = 8.0) -> list[tuple[float, float]]:
    """Up to n of the given report points themselves (never a point no report gave, review 2026-11-16 P2-5): the one
    nearest the median first, then the farthest from those chosen while more than min_sep_km away. Pure."""
    pts = sorted({(round(float(a), 3), round(float(b), 3)) for a, b in points or [] if a is not None and b is not None})
    if not pts:
        return []
    mid = (statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts))
    chosen = [min(pts, key=lambda p: (rh._km(p, mid), p))]
    while len(chosen) < n:
        far, dist = None, -1.0
        for p in pts:
            d = min(rh._km(p, c) for c in chosen)
            if d > dist:
                far, dist = p, d
        if far is None or dist <= min_sep_km:
            break
        chosen.append(far)
    return chosen


# ---------------------------------------------------------------- the daily pass

def events_sources(events_dir=None) -> tuple[list, dict[str, bool]]:
    """([(source id, records)], {source id: published in batches}) from the events files (rain_history's reader, with
    each file's meta.published_in_batches: review 2026-11-16 P2-6)."""
    from common import EVENTS_DIR
    out, batches = [], {}
    for f in sorted((EVENTS_DIR if events_dir is None else events_dir).glob("*.json")):
        if f.name.startswith("fixture"):
            continue
        try:
            d = read_json(f, {}) or {}
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        out.append((f.stem, d.get("records") or []))
        if (d.get("meta") or {}).get("published_in_batches"):
            batches[f.stem] = True
    return out, batches


def operator_resolver(rows: list[dict] | None = None, aliases: dict | None = None):
    """The operator id of a record as the export's CSV gives it (export/csv.py operators_of): its discharger_id (an
    alias read as its registry row), else the first registry row holding its permit."""
    if rows is None:
        from build.status import discharger_rows
        rows = discharger_rows()
    if aliases is None:
        from build.status import discharger_aliases
        aliases = discharger_aliases(rows)
    ids = {r.get("id") for r in rows or [] if r.get("id")}
    by_permit: dict[str, str] = {}
    for r in rows or []:
        for p in [r.get("npdes_permit")] + list(r.get("npdes_permits") or []):
            if p and r.get("id"):
                by_permit.setdefault(p, r["id"])

    def of(r: dict) -> str | None:
        did = r.get("discharger_id")
        did = aliases.get(did, did) if isinstance(did, str) else did
        if did in ids:
            return did
        return by_permit.get(r.get("npdes_permit")) or (did if isinstance(did, str) and did else None)
    return of


def build(offline: bool = False, budget: int = 600, today: date | None = None, now: datetime | None = None, *,
          sources=None, rules=None, operator_of=None, placements=None, batches=None, reader=None, have=None,
          names=None, grades=None, prev=None, out_path=None, write: bool = True) -> dict:
    """The levels file. Every input can be given (the tests, scripts/rain_sso_seed.py); by default the events files,
    data/rules.json, the last status build's placements, the export's state grades, the previous levels file (build
    copy, else seed) and the point service. Only the approved operators are read (the rain record's requests stay
    small); every operator with reports is counted. Raises MissingInput (nothing written) when the events files hold
    no records or none of the approved operators' reports."""
    from build.status import own_state
    from build.rain_thresholds import BudgetSpent, RequestBudget, ServiceRefused
    now = now or datetime.now(UTC)
    today = today or now.date()
    if rules is None:
        rules = read_json(DATA_DIR / "rules.json", {}) or {}
    cfg = settings(rules)
    hist_cfg = rh.settings(rules)
    if sources is None:
        sources, file_batches = events_sources()
        batches = {**file_batches, **(batches or {})}
    if placements is None:
        placements = (read_json(BUILD_DIR / "status.json", {}) or {}).get("placements") or {}
    operator_of = operator_of or operator_resolver()
    reader = reader or rh._iem_reader
    have = have or rh._iem_have
    approved = set(cfg["approved"])
    grades = load_grades() if grades is None else grades
    if prev is None:
        prev = load_levels() or {}
    prev_ops = (prev or {}).get("operators") or {} if (prev or {}).get("method_version") == METHOD_VERSION else {}
    if not any(recs for _, recs in sources or []):
        raise MissingInput("no events file with records")
    # every source the previous file drew an approved operator's history from must be there (review 2026-11-16 P1-3):
    # an events file that did not arrive is a missing input, never "no report"
    need = {s for op in approved for s in (prev_ops.get(op) or {}).get("sources") or []}
    gone = sorted(need - {sid for sid, recs in sources or [] if recs})
    if gone:
        raise MissingInput(f"no records from {', '.join(gone)}, a source of the approved operators' reports")

    spans: dict[str, list[dict]] = defaultdict(list)
    left: dict[str, dict] = defaultdict(dict)
    src_figs, src_why = {}, {}
    names = dict(names or {})
    state_of: dict[str, str] = {}
    all_points: dict[str, list] = defaultdict(list)
    newest_pub: dict[tuple, date] = {}
    src_out: dict[str, dict[str, str]] = defaultdict(dict)     # {operator: {source: why source_ok leaves it out}}
    with_reports: set[str] = set()
    for sid, recs in sources:
        for r in recs:
            if not r.get("source_id"):
                r["source_id"] = sid
        fig = source_figures(recs, today)
        for r in recs:      # each source's newest published report, by state (the 12-month rule's anchor)
            d0 = rh.rain_day(r.get("started_at"), r.get("time_precision") if r.get("time_precision") in DATED else "day")
            # the record's state from its own fields (build/status.py own_state: raw.state, the permit's prefix, the
            # source's prefix); the ingesters write no top-level state (first run, 2026-11-16: every key was "")
            st = own_state(r, sid) or ""
            if d0 is not None and d0 <= today and r.get("time_precision") not in ("month", "year"):
                k = (sid, st)
                if k not in newest_pub or d0 > newest_pub[k]:
                    newest_pub[k] = d0
        why = source_ok(fig, cfg, bool((batches or {}).get(sid)))
        got, lo = sso_spans(recs, operator_of, cfg, placements)
        for r in recs:      # the rain point: the median of every dated report point of the operator, any year
            if r.get("event_type") in set(cfg["event_types"]) and r.get("time_precision") in DATED \
                    and not r.get("duplicate_of") and not r.get("superseded_by") and _pt(r) \
                    and not ((placements or {}).get(r.get("event_id")) or {}).get("duplicate_of") \
                    and not ((placements or {}).get(r.get("event_id")) or {}).get("superseded"):
                op = operator_of(r)
                if op:
                    all_points[op].append(_pt(r))
        if not got and not lo:
            continue
        src_figs[sid], src_why[sid] = fig, why
        for op, c in lo.items():
            for k, v in c.items():
                left[op][k] = left[op].get(k, 0) + v
        for r in recs:
            if r.get("event_type") in set(cfg["event_types"]):
                op = operator_of(r)
                if op and r.get("discharger_name"):
                    names.setdefault(op, r["discharger_name"])
                if op:
                    with_reports.add(op)
                    st = own_state(r, sid)
                    if st:
                        state_of.setdefault(op, st)
        for op, v in got.items():
            if why is not None:
                left[op]["source_not_dated"] = left[op].get("source_not_dated", 0) + len(v)
                src_out[op][sid] = why
                continue
            for s in v:
                s["coverage_end"] = fig.get("latest")
            spans[op] += v

    if approved and not approved & with_reports:
        raise MissingInput(f"none of the {len(approved)} approved operators has a report in the events files")

    bud = RequestBudget(budget)
    stopped = None
    unread: list[str] = []      # approved operators with reports whose rain record was not read and nothing was kept
    ops: dict[str, dict] = {}
    outside = 0
    for op in sorted(set(spans) | approved):
        sp = spans.get(op) or []
        late = {s: w for s in sorted({x["source_id"] for x in sp if x.get("source_id")})
                if (w := source_timely(src_figs.get(s) or {}, cfg))}
        base = {"op": op, "name": names.get(op), "state": state_of.get(op) or op[:2].upper(),
                "late_sources": late,
                "reports": len(sp), "not_used": left.get(op, {}),
                "sources": sorted({s["source_id"] for s in sp if s.get("source_id")}),
                "permits": sorted({s["permit"] for s in sp if s.get("permit")}),
                "usable_sources": len({s["source_id"] for s in sp if s.get("source_id")})}
        if op not in approved:
            outside += 1        # counted only: the file names no operator outside the approved set
            continue
        pts = rh.rain_points(all_points.get(op) or [], max_points=int(cfg["history_points"]))
        if not sp or not pts:
            outs = [f"its source {k} {w}" for k, w in sorted(src_out.get(op, {}).items())]
            if sp:
                hwhy = "no dated report with a point"
            elif outs:
                hwhy = "no report from a source whose reports can enter a history"
            else:
                hwhy = "no dated overflow report since " + str(cfg["first_day"])
            why = verdict({**base, "usable": False, "why_not": hwhy, "lift": None}, cfg, today, grades)
            if outs and not sp:     # the source rule is the reason, in its own words, not "too few reports"
                why = outs + [w for w in why if not w.startswith("no usable history") and not w.startswith("no strong")]
            ops[op] = {**base, "usable": False, "history_why_not": hwhy, "qualifies": False, "read": False,
                       "why_not": why}
            continue
        first = min(s["first"] for s in sp)
        years = list(range(first.year, today.year + 1))
        cover = max((date.fromisoformat(s["coverage_end"]) for s in sp if s.get("coverage_end")), default=today)
        series = []
        if stopped is None and not offline:
            try:
                series = [reader(lat, lon, years, False, bud) for lat, lon in pts]
            except (BudgetSpent, ServiceRefused) as e:
                stopped = f"{type(e).__name__} at {op}: {error_detail(e)}"
                series = []
        if not series and all(have(lat, lon, years) for lat, lon in pts):
            series = [reader(lat, lon, years, True, None) for lat, lon in pts]
        period_last = min(cover, today) - timedelta(days=int(hist_cfg["lag_days"]))
        if not series or rh.short_years(series, years, period_last, today):
            # never computed from a rain record short of a year it needs: the previous entry stays (the build copy,
            # else the seed), so a service that refuses part-way never takes the caution away for a day
            if op in prev_ops:
                was = prev_ops[op].get("carried") or {}
                ops[op] = {**prev_ops[op], "carried": {"from": was.get("from") or (prev or {}).get("built"),
                                                       "why": stopped or "the rain record was not read this pass"}}
                continue
            ops[op] = {**base, "qualifies": False, "read": False, "points": [list(p) for p in pts],
                       "why_not": ["the rain record for this operator has not been read yet"]}
            unread.append(op)
            continue
        daily = rh.daily_max(series)
        e = analyse_operator(op, daily, sp, cover, cfg, hist_cfg, today)
        entry = {**base, **e, "points": [list(p) for p in pts], "read": True,
                 "live_points": [list(p) for p in report_points(
                     [ev["point"] for ev in e["places"]["events"] if ev["point"]], int(cfg["live_points"]))]}
        entry["history_why_not"] = entry.pop("why_not", None)
        entry["recency"] = recency(daily, sp, {k[0]: v for k, v in newest_pub.items() if k[1] == entry["state"]},
                                   cfg, today, float(hist_cfg["rungs_in"][0]))
        why = verdict(entry, cfg, today, grades)
        entry["qualifies"] = not why
        entry["why_not"] = why
        ops[op] = entry

    if unread and not any(o.get("read") or o.get("carried") for o in ops.values()):
        # review 2026-11-16 P2-4: no rain record read and none kept is a missing input, not "nobody qualifies"
        raise MissingInput(f"the rain record of {len(unread)} approved operators was not read and no previous entry "
                           "is on file" + (f" ({stopped})" if stopped else ""))
    out = {"method_version": METHOD_VERSION, "revision": FILE_REVISION, "built": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "today": today.isoformat(), "rain_record": rh.RAIN_RECORD,
           "settings": {k: v for k, v in cfg.items() if k not in ("doc", "source", "labels")},
           "history_settings": hist_cfg,
           "sources": {sid: {**src_figs[sid], "excluded": src_why[sid],
                             "newest_published": max((v.isoformat() for k, v in newest_pub.items() if k[0] == sid), default=None),
                             "newest_published_by_state": {k[1]: v.isoformat() for k, v in sorted(newest_pub.items())
                                                           if k[0] == sid},
                             "silent": max((v for k, v in newest_pub.items() if k[0] == sid), default=date.min)
                             < months_back(today, int(cfg["recency_months"]))}
                       for sid in sorted(src_figs)},
           "state_grades": {st: (grades or {}).get(st) for st in sorted({o["state"] for o in ops.values()
                                                                          if o["op"] in approved})},
           "state_grades_on_file": bool(grades),
           "counts": {"operators": len(ops), "outside_the_set": outside, "read": sum(1 for o in ops.values() if o.get("read") and not o.get("carried")),
                      "carried": sum(1 for o in ops.values() if o.get("carried")),
                      "qualify": sum(1 for o in ops.values() if o.get("qualifies")),
                      "qualify_by_state": dict(sorted(Counter(o["state"] for o in ops.values()
                                                              if o.get("qualifies")).items()))},
           "run": {"requests": bud.used, "budget": budget, "stopped": stopped, "offline": offline,
                   "unread": unread},
           "operators": {k: ops[k] for k in sorted(ops)}}
    out = rh._round(out)
    if write:
        rh._write(out_path or LEVELS_BUILD, out)
    return out


# ---------------------------------------------------------------- what the other stages read

def too_old(entry: dict, cfg: dict, today: date | None) -> str | None:
    """The silence rule read against today, not the day the file was built: a source with no published report in the
    last recency_months drops the operator even when the file was kept by failed passes or is the seed. Pure."""
    if today is None:
        return None
    rc = entry.get("recency") or {}
    n = int(cfg["recency_months"])
    try:
        anchor = date.fromisoformat(str(rc.get("source_newest"))[:10])
    except ValueError:
        return "the date of its source's newest report is not on file"
    if anchor < months_back(today, n):
        return f"its source {rc.get('source')} has published no report in the last {n} months (newest {anchor.isoformat()})"
    return None


def qualifying(levels: dict | None, rules: dict | None, grades: dict | None | bool = False,
               today: date | None = None) -> dict[str, dict]:
    """{operator: entry} for the operators the caution covers now: qualifies in the file, still approved, and (the
    status build's check each hour) its state still grades "Dated reports" (grades given) and its newest report is
    still within the age limit on today (today given)."""
    if not levels or not enabled(rules):
        return {}
    cfg = settings(rules)
    approved = set(cfg["approved"])
    return {op: e for op, e in sorted((levels.get("operators") or {}).items())
            if e.get("qualifies") is True and op in approved and e.get("possible_in") is not None
            and (grades is False or state_grade_ok(e.get("state"), grades) is None)
            and too_old(e, cfg, today) is None}


def live_points(rules: dict | None = None, levels: dict | None = None) -> list[dict]:
    """The points the hourly rainfall check reads for the covered operators, as ingest/rainfall.py's outfall rows
    (permit "sso:<operator>"); [] with the switch off."""
    rules = read_json(DATA_DIR / "rules.json", {}) or {} if rules is None else rules
    if not enabled(rules):
        return []
    levels = load_levels() if levels is None else levels
    out = []
    for op, e in qualifying(levels, rules).items():
        for lat, lon in e.get("live_points") or e.get("points") or []:
            out.append({"permit": KEY_PREFIX + op, "outfall": None, "state": e.get("state") or op[:2].upper(),
                        "name": e.get("name"), "lat": float(lat), "lon": float(lon), "water_slug": None,
                        "water_match": None, "distance_m": None, "source": POINT_SOURCE})
    return out


def is_key(permit) -> bool:
    """True for the key the live rainfall readings carry for a separate sewer operator ("sso:<operator>")."""
    return str(permit).startswith(KEY_PREFIX)


def trace_key(event_id: str) -> str:
    """The key build/reaches gives a stretch traced from a report's own point (event_points)."""
    return "pt-" + hashlib.sha1(event_id.encode()).hexdigest()[:12]


def trace_points(waters: dict, rules: dict | None = None, levels: dict | None = None, river_kinds=None) -> list[dict]:
    """The report points to trace a stretch from (build/reaches candidates, the shape of event_points): one per point
    (three decimals) of the covered operators' rain-driven reports on a river water, carrying every report at that
    point; [] with the switch off."""
    from build.rain_likely import RIVER_KINDS
    kinds = river_kinds or RIVER_KINDS
    rules = read_json(DATA_DIR / "rules.json", {}) or {} if rules is None else rules
    if not enabled(rules):
        return []
    levels = load_levels() if levels is None else levels
    by_pt: dict[tuple, dict] = {}
    for op, e in qualifying(levels, rules).items():
        for ev in (e.get("places") or {}).get("events") or []:
            if not ev.get("point") or not ev.get("event_id"):
                continue
            river = next((s for s in ev.get("water_slugs") or [] if (waters.get(s) or {}).get("kind") in kinds), None)
            if not river:
                continue
            k = (round(ev["point"][0], 3), round(ev["point"][1], 3))
            c = by_pt.setdefault(k, {"key": trace_key(ev["event_id"]), "permit": None, "outfall": None,
                                     "water_slug": river, "lat": k[0], "lon": k[1], "name": None,
                                     "sources": [TRACE_SOURCE], "event_ids": []})
            c["event_ids"].append(ev["event_id"])
    return [by_pt[k] for k in sorted(by_pt)]


# ---------------------------------------------------------------- the caution, each hour (build/status.py)

TIDAL_KINDS = {"bay", "sound"}
MIN_REPORTS_TIDAL = 2   # a bay or sound is marked only where at least this many rain-driven reports reached it


def reach_index(reaches: dict) -> dict[str, list[str]]:
    """{event id: [reach key]} of the stretches traced from a report's own point (event_ids on the cached record)."""
    out: dict[str, list[str]] = defaultdict(list)
    for key, r in sorted((reaches or {}).items()):
        if r.get("cut_reason") == "no_trace" or not r.get("segments"):
            continue
        for eid in r.get("event_ids") or []:
            out[eid].append(key)
    return out


def placement(entry: dict, waters: dict, reaches: dict, reach_waters_fn, placements: dict | None = None,
              by_event: dict | None = None) -> tuple[list[str], dict, dict, list[dict]]:
    """(reach keys, {water slug: placement tag}, {slug: reach keys}, the waters named) for one operator: only the
    traced stretches below the points of its rain-driven reports (tag "reach" on the waters each stretch runs along),
    and a bay or sound that MIN_REPORTS_TIDAL or more of them reached (tag "tidal", as a report there is placed). A
    river with no stretch traced yet, a lake, pond or reservoir (filling a whole lake is a strong claim) and a water no
    rain-driven report reached get no mark; every water a report reached is named with the reason. A stretch from a
    report's own point that the status build's point-trace rule withheld (status.point_trace_withheld) is never used.
    Pure."""
    from build.status import point_trace_withheld
    by_event = reach_index(reaches) if by_event is None else by_event
    pl_all = placements or {}
    keys, tags, reach_of = [], {}, defaultdict(set)
    reach_hits: Counter = Counter()
    events = (entry.get("places") or {}).get("events") or []
    for ev in events:
        eid = ev.get("event_id")
        pl = pl_all.get(eid) or {}
        if not ev.get("point"):
            continue                # no point given: no stretch can be traced from it
        ks = list(dict.fromkeys([*(ev.get("reaches") or []), *[k for k in [pl.get("reach"), *(pl.get("reaches") or [])] if k],
                                 *by_event.get(eid, [])]))
        for k in ks:
            r = (reaches or {}).get(k)
            if not r or not r.get("segments") or r.get("cut_reason") == "no_trace":
                continue
            if eid not in (r.get("event_ids") or []) or r.get("outfall") not in (None, ""):
                continue            # a registry outfall's reach, or one traced for other reports: never this caution's
                #                     place (review 2026-11-16 P1-3)
            if point_trace_withheld(pl, k):
                continue            # the status build's point-trace rule set this report's point aside (denied, a
                #                     location it cannot use, too far from a stream): it is never the caution's place
            if k not in keys:
                keys.append(k)
            reach_hits[k] += 1
            on = set(reach_waters_fn(r, waters))
            if r.get("water_slug") in waters:
                on.add(r["water_slug"])
            for sl in on:
                tags[sl] = "reach"
                reach_of[sl].add(k)
    named = []
    for w in (entry.get("places") or {}).get("waters") or []:
        sl, n = w.get("water_slug"), int(w.get("reports") or 0)
        kind = (waters.get(sl) or {}).get("kind")
        if sl in tags:
            why = "a stretch below the reported points"
        elif sl not in waters:
            why = "not a water record we track"
        elif kind in TIDAL_KINDS and n >= MIN_REPORTS_TIDAL:
            tags[sl] = "tidal"
            why = "tidal water: movement not modeled"
        elif kind in TIDAL_KINDS:
            why = f"fewer than {MIN_REPORTS_TIDAL} rain-driven reports here"
        elif kind in {"river", "stream", "canal"}:
            why = "no downstream stretch traced yet from the reported points"
        else:
            why = "a whole lake, pond or reservoir is not marked"
        named.append({"water_slug": sl, "name": (waters.get(sl) or {}).get("name"), "reports": n,
                      "placement": tags.get(sl), "why": why})
    return sorted(keys), {k: tags[k] for k in sorted(tags)}, {k: sorted(v) for k, v in reach_of.items()}, named


def report_starts(events: list[dict], ops: dict[str, dict]) -> dict[str, list[tuple[datetime, str]]]:
    """{operator: [(start, event id)]} of every dated discharge report of a covered operator (its discharger id, or a
    permit its own reports carry): such a report holds the caution back, as a notice does for a combined sewer."""
    from build.rain_likely import DISCHARGE_TYPES, parse_t
    from common import system_wide_advisory
    permits = {}
    for op, e in ops.items():
        for p in e.get("permits") or []:
            permits.setdefault(p, op)
    out = defaultdict(list)
    for ev in events:
        if ev.get("time_precision") in ("month", "year") or system_wide_advisory(ev):
            continue
        et = ev.get("event_type")
        if et not in DISCHARGE_TYPES and not (et == "unknown" and ev.get("status") == "ongoing"):
            continue
        op = ev.get("discharger_id") if ev.get("discharger_id") in ops else permits.get(ev.get("npdes_permit"))
        if not op:
            continue
        t = parse_t(ev.get("started_at"))
        if t is not None:
            out[op].append((t, ev["event_id"]))
    return out


def evidence(entry: dict, level: str, peak: float | None, named: list[dict], levels: dict) -> dict:
    """The evidence record of a separate sewer caution (the rain words' facts): the operator's own history, the
    waters its rain-driven reports reached, and that a separate sewer has no overflow outfall."""
    from build.rain_likely import episode_class
    cls = episode_class({**entry, "usable": True}, peak) if peak is not None else None
    if cls and cls.get("kind") == "below_lowest":
        cls = None
    shown = [w for w in named if w.get("placement")]
    return {"basis": BASIS, "level": level, "caution_in": entry.get("possible_in"), "likely_in": entry.get("likely_in"),
            "class": cls, "period": entry.get("period"), "lowest_reported": entry.get("lowest_reported"),
            "quiet": None, "notes": list(entry.get("notes") or []), "why_no_history": None, "rule_text": None,
            "report_sources": list(entry.get("sources") or []), "rain_record": rh.RAIN_RECORD["source_id"],
            "method_version": METHOD_VERSION, "computed": levels.get("today"),
            "storms": entry.get("storms"), "followed": entry.get("followed"),
            "rain_reports": (entry.get("places") or {}).get("reports"), "reports": entry.get("reports"),
            "lift": entry.get("lift"),
            "waters": [{"water_slug": w["water_slug"], "name": w.get("name"), "reports": w["reports"]}
                       for w in named[:3] if w.get("name")],
            "shown_on": [w["water_slug"] for w in shown],
            "no_outfall": True}


def compute(rain: dict, rules: dict, events: list[dict], now: datetime, h_start: datetime, waters: dict,
            reaches: dict, reach_waters_fn, placements: dict | None = None, levels: dict | None = None,
            grades: dict | None | bool = None) -> tuple[dict, dict, dict]:
    """(intervals by water slug, intervals by reach key, the block status.json "rain_likely" carries under
    "separate_sewers", and the episodes to add to its "episodes"). The intervals are the combined sewer caution's
    (rule "rain_likely", yellow), with their own evidence basis. Pure but for the levels and grades files read when
    not given."""
    from build import rain_likely as rl
    cfg = settings(rules)
    rlc = rl.settings(rules)
    levels = load_levels() if levels is None else levels
    grades = load_grades() if grades is None else grades
    tail = float(rlc["tail_hours"])
    supp = timedelta(hours=float(rlc["notice_suppress_hours"]))
    stale_h = float(rlc["rainfall_stale_hours"])
    rf = (rain or {}).get("rainfall") or {}
    hist = (rain or {}).get("history") or {}
    latest = rf.get("permits") or {}
    series = hist.get("permits") or {}
    start = rl.parse_t(hist.get("start"))
    valid = rl.parse_t((rf.get("mrms") or {}).get("valid_time"))
    stale = valid is None or now - valid > timedelta(hours=stale_h + 1)
    ops = qualifying(levels, rules, grades, now.date())
    starts = report_starts(events, ops)
    by_event = reach_index(reaches)
    by_water, by_reach = defaultdict(list), defaultdict(list)
    ecfg = {"label": cfg["labels"]["possible"], "doc": cfg["doc"], "source": cfg["source"]}
    block = {"enabled": True, "rule": rl.RULE, "basis": BASIS, "doc": cfg["doc"], "source": cfg["source"],
             "label_by_level": cfg["labels"], "tail_hours": tail, "notice_suppress_hours": supp.total_seconds() / 3600,
             "levels": {k: (levels or {}).get(k) for k in ("method_version", "built", "today", "counts")},
             "operators": {}, "not_covered": {}, "waters": {}, "problems": []}
    episodes = {}
    if levels is None:
        block["problems"].append("no separate sewer levels file (data/build/rain-levels-sso.json) yet")
    if grades is not False and not grades:
        # the export writes the grades after this build (the first switched-on hour has none): the daily pass's source
        # rule stands alone, and that is said here rather than turning every operator off (first run, 2026-11-16)
        block["problems"].append("no state grades file (data/build/coverage-grades.json) yet; the daily pass's "
                                 "source rule applies alone")
    for op, e in sorted(((levels or {}).get("operators") or {}).items()):
        if op not in ops and op in set(cfg["approved"]):
            why = list(e.get("why_not") or [])
            g = state_grade_ok(e.get("state"), grades if grades is not False else None)
            if e.get("qualifies") and g:
                why.append(g)
            old = too_old(e, cfg, now.date())
            if e.get("qualifies") and old:
                why.append(old)
            block["not_covered"][op] = {"name": e.get("name"), "state": e.get("state"), "why_not": why,
                                        "reports": e.get("reports"), "storms": e.get("storms"),
                                        "followed": e.get("followed"), "lift": e.get("lift"), "period": e.get("period")}
    for op, e in ops.items():
        key = KEY_PREFIX + op
        info = latest.get(key) or {}
        t_in = float(e["possible_in"])
        l_in = e.get("likely_in")
        keys, tags, reach_of, named = placement(e, waters, reaches, reach_waters_fn, placements, by_event)
        eps = rl.runs(series.get(key) or [], start, t_in, now, tail, stale_h) if start else []
        blocks = [(s0, s0 + supp) for s0, _ in starts.get(op, []) if s0 <= now]
        h24 = info.get("h24")
        row = {"name": e.get("name"), "discharger_id": op, "state": e.get("state"), "threshold_in": t_in,
               "likely_in": l_in, "threshold_kind": BASIS, "trigger_basis": "operator",
               "rain_24h_in": h24, "valid_time": info.get("valid_time"), "point": rl._point(info.get("h24_point")),
               "points": [list(p) for p in e.get("live_points") or []],
               "rainfall_read": info.get("read"), "status": "no_reading" if h24 is None else "below", "episode": None,
               "suppressed_by": [], "level": "possible", "label": cfg["labels"]["possible"],
               "waters": sorted(tags), "reaches": keys, "named_waters": named,
               "history": {k: e.get(k) for k in ("period", "storms", "followed", "reports", "lift", "share_follow",
                                                  "baseline", "possible_in", "likely_in", "recency", "newest_report",
                                                  "bands", "lowest_reported", "possible", "likely", "notes")},
               "evidence": evidence(e, "possible", None, named, levels or {})}
        for ep in eps:
            eid = f"rain_likely:{key}:{ep['start'].strftime('%Y%m%dT%H')}Z"
            peak = round(ep["peak"], 2)
            level = "likely" if l_in is not None and peak >= float(l_in) - 1e-9 else "possible"
            pieces = [(a, b) for a, b in rl.subtract(ep["start"], ep["end"], blocks) if (b is None or b > h_start) and a <= now]
            by_report = sorted({x for s0, x in starts.get(op, []) if s0 <= now and s0 + supp > ep["start"]
                                and (ep["end"] is None or s0 < ep["end"])})
            in_now = ep["start"] <= now and (ep["end"] is None or ep["end"] > now)
            active = any(a <= now and (b is None or b > now) for a, b in pieces)
            ev = evidence(e, level, peak, named, levels or {})
            if in_now:
                row.update(episode=eid, status="likely" if active else "suppressed",
                           suppressed_by=[] if active else by_report, level=level,
                           label=cfg["labels"][level], evidence=ev)
            if not pieces and not in_now:
                continue
            rain_rec = {"permit": key, "discharger_name": e.get("name"), "discharger_id": op, "state": e.get("state"),
                        "threshold_in": t_in, "threshold_basis": "history", "threshold_rule": f"{rl.RULE}.separate_sewers",
                        "threshold_text": None, "threshold_source": None, "threshold_kind": BASIS,
                        "trigger_basis": "operator", "label": cfg["labels"][level], "level": level,
                        "n_discharge_days": None, "history_since": (e.get("period") or [None, None])[0],
                        "history_until": (e.get("period") or [None, None])[1],
                        "peak_24h_in": peak, "peak_at": rl.iso(ep["peak_at"]), "above_from": rl.iso(ep["start"]),
                        "last_above_at": rl.iso(ep["last_above"]), "dropped_below_at": rl.iso(ep.get("dropped_at")),
                        "until": rl.iso(ep["end"]),
                        "until_rule": f"{tail:g} hours after the 24-hour total falls below {rl.inch(t_in)}",
                        "rain_24h_in": h24, "valid_time": info.get("valid_time"), "point": rl._point(info.get("h24_point")),
                        "qpf_24h_in": info.get("qpf_24h_in"), "qpf_update_time": info.get("qpf_update_time"),
                        "rainfall_source": rl.RAINFALL_SOURCE, "rainfall_source_id": rl.SOURCE_ID,
                        "rainfall_product": info.get("product") or rl.PRODUCT, "rainfall_read": info.get("read"),
                        "rainfall_read_text": "read hourly at the points of the operator's past rain-driven reports",
                        "rainfall_service": rl.MRMS_SERVICE, "rainfall_stale": bool(ep.get("rainfall_stale")) or stale,
                        "suppressed_by": by_report, "evidence": ev}
            rule_applied = {"rule": rl.RULE, "threshold_in": t_in, "threshold_basis": "history", "tail_hours": tail,
                            "trigger_basis": "operator", "basis": BASIS, "rationale": cfg["doc"], "source": cfg["source"]}
            episodes[eid] = {"permit": key, "discharger_name": e.get("name"), "discharger_id": op, "state": e.get("state"),
                             "trigger_basis": "operator", "level": level, "label": rain_rec["label"], "basis": BASIS,
                             "start": rl.iso(ep["start"]), "end": rl.iso(ep["end"]), "active": active, "in_effect": in_now,
                             "pieces": [[rl.iso(a), rl.iso(b)] for a, b in pieces], "waters": sorted(tags),
                             "reaches": keys, "rain": rain_rec}
            rl._emit(pieces, eid, ep, key, rain_rec, rule_applied, {**ecfg, "label": rain_rec["label"]}, tail, keys,
                     tags, reach_of, by_water, by_reach, rl.SOURCE_ID, "NOAA MRMS radar estimate")
        block["operators"][op] = row
        for sl in tags:
            w = block["waters"].setdefault(sl, {"operators": [], "likely": False})
            w["operators"].append(op)
            w["likely"] = w["likely"] or row["status"] == "likely"
    block["counts"] = {"operators": len(block["operators"]), "not_covered": len(block["not_covered"]),
                       "likely_now": sum(1 for r in block["operators"].values() if r["status"] == "likely"),
                       "suppressed_now": sum(1 for r in block["operators"].values() if r["status"] == "suppressed"),
                       "episodes": len(episodes),
                       "by_state": dict(sorted(Counter(r["state"] for r in block["operators"].values()).items()))}
    return dict(by_water), dict(by_reach), {**block, "_episodes": episodes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--if-older-h", type=float, default=None)
    ap.add_argument("--force", action="store_true", help="build even with the switch off")
    a = ap.parse_args(argv)
    rules = read_json(DATA_DIR / "rules.json", {}) or {}
    if not a.force and not enabled(rules):
        print("rain_sso: rules.rain_likely.separate_sewers is off; nothing to do")
        return 0
    if a.if_older_h is not None:
        d = read_json(LEVELS_BUILD, None) if LEVELS_BUILD.exists() else None
        try:
            built = datetime.fromisoformat(str((d or {}).get("built")).replace("Z", "+00:00"))
            # a pass that stopped part-way (the service refused, the budget ran out) runs again the next hour, and so
            # does a file of an earlier revision (the first run's, in which nobody qualified)
            run = (d or {}).get("run") or {}
            done = not run.get("stopped") and not run.get("unread") and (d or {}).get("revision") == FILE_REVISION
            if (d or {}).get("method_version") == METHOD_VERSION and done \
                    and datetime.now(UTC) - built < timedelta(hours=a.if_older_h):
                print(f"rain_sso: {LEVELS_BUILD.name} is younger than {a.if_older_h:g} hours; nothing to do")
                return 0
        except ValueError:
            pass
    try:
        d = build(offline=a.offline, budget=a.budget, rules=rules)
    except MissingInput as e:
        print(f"rain_sso: stopped: {error_detail(e)}; nothing written, the previous levels file stays")
        return 1
    c = d["counts"]
    print(f"rain_sso: {c['operators']} operators with reports, {c['read']} read, {c['qualify']} qualify "
          f"{c['qualify_by_state']}; {d['run']['requests']} requests"
          + (f"; {c['carried']} carried from the previous file" if c.get("carried") else "")
          + ("" if d.get("state_grades_on_file") else "; state grades not on file, the source rule alone applied")
          + (f"; not read: {', '.join(d['run']['unread'])}" if d['run'].get('unread') else "")
          + (f"; stopped: {d['run']['stopped']}" if d['run']['stopped'] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
