"""out/coverage.json: what is reported, state by state and water by water (docs/plan.md §2.y; owner, 2026-11-03: a
quiet map must not read as a clean one).

    coverage(events, waters, feeds, registry, dischargers, rules, as_of, rain_block, cso_permits) -> dict

The figures follow the site's own reading (site/src/lib/coverage.ts `computed`, which uses this file when it exists),
so the pages, the /reporting/ table and the CSV agree:

  records      a state's sewage reports (cso, sso, bypass, blended, plant_bypass, unknown, annual_total), not
               duplicates, not superseded, in the 12 months before the snapshot (a yearly total by its publication)
  dated        a report with a start to the day or better: time_precision minute, hour, day, bound, poll (opened or
               closed at the first poll that showed the change: Philadelphia CSOcast, NBC, CCMUA) or none given
  dated_share  dated / records; latest_dated the newest dated report's start (or report time)
  lag_days     per feed, the median days from a dated first report's start to its report (reported_at, else
               published_at); the state's is the fastest feed carrying a quarter of its dated reports, with 3 or more
               such times, read more often than monthly
  grade        "Dated reports" (over 80 percent dated, newest within 14 days, delay at most 7 days), "Dated reports,
               delayed", "Monthly totals only", "Annual totals only", "No public reports", with its sentence
  duty         the first sentence of data/rules.json red.by_state[<st>].basis (null where none)
  rain_caution where the "discharge likely" caution is computed (build/rain_likely.caution_coverage)
  notification_pages  per state in the public-notice channel register (data/notice-channels.json, or per state
               data/notice-channels/<st>.json): the page-health table of ingest/notification_pages.py
               (data/build/notice-pages/health.json): {built, counts, operators, channels}, each channel and operator
               with its one public line (`wording`); absent where the register has no rows for the state

Per water: the same figures over the reports placed on the water, its grade and a sentence for the status card
("Only monthly totals are reported for this water ..."). Never a safety verdict.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from build import status as status_mod

NY = ZoneInfo("America/New_York")
SEWAGE = {"cso", "sso", "bypass", "blended", "plant_bypass", "unknown", "annual_total"}
DATED_PRECISION = {"minute", "hour", "day", "bound", "poll"}
GRADES = ["Dated reports", "Dated reports, delayed", "Monthly totals only", "Annual totals only", "No public reports"]
FRESH_DAYS = 14
LAG_OK_DAYS = 7
DATED_OVER = 0.8
PRECISION_TEXT = {"minute": "to the minute", "hour": "to the hour", "day": "to the day",
                  "poll": "to the poll (checked through the day)", "bound": "a date range", "month": "month only",
                  "year": "year only"}
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "PR": "Puerto Rico", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
ABBR = re.compile(r"\b(?:Va|Ga|Comp|Env|Md|Code|Ann|Stat|Gen|Laws|Rev|Pt|Sec|Art|No|St|Mass|Conn|Me|Vt|Pa|R\.I|N\.Y|N\.J|N\.H|D\.C|"
                  r"U\.S|C\.F\.R|seq|al|e\.g|i\.e)\.$")


def _s(v):
    return v if isinstance(v, str) and v else None


def _t(s) -> datetime | None:
    return status_mod.parse_time(s) if s else None


def iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z") if t else None


def day_text(t: datetime | None) -> str:
    """"Oct 26, 2026" in New England time (the site's fmtTime(..., 'day'))."""
    if t is None:
        return ""
    d = t.astimezone(NY)
    return f"{d:%b} {d.day}, {d.year}"


def is_dated(e: dict) -> bool:
    p = e.get("time_precision")
    return p in DATED_PRECISION or (not p and e.get("event_type") != "annual_total")


def precision_of(e: dict) -> str:
    return "year" if e.get("event_type") == "annual_total" else (e.get("time_precision") or "minute")


def when_of(e: dict) -> datetime | None:
    return _t(_s(e.get("started_at")) or _s(e.get("reported_at")) or _s(e.get("published_at")) or _s(e.get("source_updated_at")))


def in_window_at(e: dict) -> datetime | None:
    """A yearly total counts in the 12 months in which it was published (its period starts long before)."""
    if e.get("event_type") == "annual_total" or e.get("time_precision") == "year":
        return _t(_s(e.get("published_at")) or _s(e.get("ended_at")) or _s(e.get("started_at")))
    return when_of(e)


def lag_of(e: dict) -> float | None:
    """Days from a discharge's start to its first report (reported_at) or, failing that, its publication."""
    a, b = _t(_s(e.get("started_at"))), _t(_s(e.get("reported_at")) or _s(e.get("published_at")))
    if a is None or b is None or b < a:
        return None
    return (b - a).total_seconds() / 86400


def median(xs):
    return statistics.median(xs) if xs else None


def duty_sentence(rules: dict, st: str) -> str | None:
    """The first sentence of the state's basis in data/rules.json (the site's stateLawSentence)."""
    basis = ((((rules or {}).get("red") or {}).get("by_state") or {}).get(st) or {}).get("basis")
    if not isinstance(basis, str) or not basis.strip():
        return None
    out = ""
    for part in re.split(r"(?<=\.)\s+(?=[A-Z])", basis.strip()):
        out = f"{out} {part}" if out else part
        last = (out.split() or [""])[-1]
        if not ABBR.search(last):
            break
    return out if out.endswith(".") else (out if out.endswith(")") else f"{out}.")


def state_name(st: str) -> str:
    return STATE_NAMES.get(st, st)


FEDERAL_PUBLISHER = "the U.S. Environmental Protection Agency"
# the grade sentence names the one operator whose feed gives every dated report only where the registry lists at least
# this many sewer operators in the state: a one-operator jurisdiction (the District of Columbia) keeps its sentence
# (Oregon final audit 2026-11-08 P2-3)
MIN_OPERATORS_FOR_PUBLISHER = 2


REFUSED = re.compile(r"\b403\b|forbidden", re.I)


def unreadable(feeds: list[dict]) -> str | None:
    """'refused' when one of the state's own sewage feeds has never been read and its host answered 403 (Tennessee's
    Events Report: final audit 2026-11-08 P1-2), 'failing' when one has never been read for another reason, else
    None. A feed read once (last_ok_at) is never this: its reports are on file."""
    bad = [f for f in feeds or [] if f.get("ok") is False and not f.get("last_ok_at") and not f.get("fixture")]
    if not bad:
        return None
    return "refused" if any(REFUSED.search(str(f.get("error") or "")) for f in bad) else "failing"


def grade_of(st: str, f: dict, as_of: datetime, federal: bool = False, operator: str | None = None,
             unread: str | None = None) -> tuple[str, str]:
    """(grade, sentence) from a state's figures (the site's gradeOf). federal: every dated report of the state comes
    from a feed whose registry rows are all federal (EPA's eRule tables): the state publishes no list of its own, so
    the sentence says who does (2026-11-07 Mississippi final audit: "Mississippi publishes dated overflow reports"
    stood above the state text's "The Department publishes no list"). operator: every dated report comes from one
    operator's own feed (its registry level "operator"), named by its attribution, so the sentence says so rather
    than crediting the state (2026-11-08 Oregon final audit P2-3: all 13 of Oregon's were the City of Portland's)."""
    name = state_name(st)
    Name = "The District of Columbia" if name.startswith("District") else name
    in_name = "the District of Columbia" if st == "DC" else name
    # no possessive ("Massachusetts's") and no unsourced delay: the delayed sentence gives the state's own lag
    by = f"Overflow reports from sewer operators in {in_name} are published by {FEDERAL_PUBLISHER}" if federal else None
    if f["records_12m"] == 0 and unread:
        # the state publishes reports this site cannot read: never "none are reported" (final audit 2026-11-08 P1-2;
        # owner default: the label of a delayed source)
        why = ("its server refuses this site's requests" if unread == "refused"
               else "this site has not yet been able to read them")
        return "Dated reports, delayed", (f"{Name} publishes dated overflow reports, but {why}, so none are shown here "
                                          f"yet; a quiet map in {in_name} means those reports cannot be read, not that "
                                          "none happen. The advisories and the rain caution this site can read are "
                                          "still shown.")
    if by is None and operator:
        who = operator if operator.lower().startswith("the ") else f"the {operator}"
        by = f"Of the sewer operators in {in_name}, only {who} publishes dated reports"
    if f["records_12m"] == 0:
        # scoped to the grading window: a state with an older readable report on file (New Mexico's of June 2024)
        # must not be told it publishes nothing readable (SOL review 2026-11-07, site P2-8; the site's coverage.ts
        # gradeOf says the same)
        return "No public reports", (f"{Name} has published no sewage overflow reports we can read in the last 12 "
                                     "months; the map shows no recent discharges there because none are reported, "
                                     "not because none happen.")
    latest = _t(f.get("latest_dated"))
    fresh = latest is not None and as_of - latest <= timedelta(days=FRESH_DAYS)
    lag = f.get("lag_days")
    if (f.get("dated_share") or 0) > DATED_OVER:
        if fresh and (lag is None or lag <= LAG_OK_DAYS):
            return "Dated reports", (f"{by}; the newest is from {day_text(latest)}." if by else
                                     f"{Name} publishes dated overflow reports; the newest is from {day_text(latest)}.")
        return "Dated reports, delayed", (
            (by or f"{Name} publishes dated reports") + (f", but the newest is from {day_text(latest)}" if latest else "")
            + (f" and reports typically appear {round(lag)} days after a discharge" if lag is not None and lag > LAG_OK_DAYS else "")
            + (f", {(as_of - latest).days} days before {day_text(as_of)}, as the reports are published in batches months "
               "later" if f.get("published_in_batches") and latest and (as_of - latest).days > LAG_OK_DAYS else "")
            + f"; a quiet map in {in_name} can mean a report has not appeared yet.")
    if f["monthly_share"] >= f["annual_share"] and f["monthly_share"] > 0:
        return "Monthly totals only", (f"{Name} publishes monthly totals, not dated reports; the map shows no dated "
                                       "discharges there because none are reported by date, not because none happen.")
    if f["annual_share"] > 0:
        return "Annual totals only", (f"{Name} publishes yearly totals, not dated overflow reports; the map shows no "
                                      "discharges there because none are reported, not because none happen.")
    return "Dated reports, delayed", f"Few of the reports in {in_name} carry a date; a quiet map there can mean a report has not appeared yet."


def water_grade(f: dict, state_grade: tuple[str, str] | None, as_of: datetime) -> tuple[str, str]:
    """(grade, sentence) for a water's status card, from the reports placed on it."""
    if f["records_12m"] == 0:
        g, s = state_grade or ("No public reports", "")
        return g, ("No report we read names this water in the last 12 months; that does not mean no discharge."
                   + (f" {s}" if s else ""))
    latest = _t(f.get("latest_dated"))
    fresh = latest is not None and as_of - latest <= timedelta(days=FRESH_DAYS)
    if (f.get("dated_share") or 0) > DATED_OVER:
        if fresh and (f.get("lag_days") is None or f["lag_days"] <= LAG_OK_DAYS):
            return "Dated reports", f"Dated reports are published for this water; the newest is from {day_text(latest)}."
        return "Dated reports, delayed", ("Dated reports are published for this water"
                                          + (f", but the newest is from {day_text(latest)}" if latest else "")
                                          + "; a quiet map here can mean a report has not appeared yet.")
    if f["monthly_share"] >= f["annual_share"] and f["monthly_share"] > 0:
        return "Monthly totals only", ("Only monthly totals are reported for this water: the number of days with a "
                                       "discharge, not the dates. A quiet map here means no dated report, not no discharge.")
    if f["annual_share"] > 0:
        return "Annual totals only", ("Only yearly totals are reported for this water. A quiet map here means no "
                                      "dated report, not no discharge.")
    return "Dated reports, delayed", "Few reports for this water carry a date; a quiet map here can mean a report has not appeared yet."


def _figures(evs: list[dict], firsts: list[dict], feeds_of: dict, cadence: dict, names: dict, ids,
             batches: dict | None = None) -> dict:
    """The figures over one set of reports (a state's or a water's)."""
    d = [e for e in evs if is_dated(e)]
    latest = max((t for t in (when_of(e) for e in d) if t), default=None)
    fc = []
    for sid in ids:
        mine = [e for e in evs if e.get("source_id") == sid]
        counts = Counter(precision_of(e) for e in mine)
        precision = counts.most_common(1)[0][0] if counts else None
        lt = max((t for t in (when_of(e) for e in mine) if t), default=None)
        lags = [x for x in (lag_of(e) for e in firsts if e.get("source_id") == sid and is_dated(e)) if x is not None]
        fc.append({"source_id": sid, "name": names.get(sid) or sid, "precision": precision,
                   "precision_text": PRECISION_TEXT.get(precision) if precision else None,
                   "precisions": dict(counts.most_common()), "cadence_hours": cadence.get(sid),
                   "records_12m": len(mine), "latest": iso(lt),
                   "lag_days": round(median(lags), 2) if lags else None, "_lags": len(lags),
                   "_dated": sum(1 for e in mine if is_dated(e))})
    fc = [f for f in fc if f["records_12m"] > 0 or f["source_id"] in feeds_of]
    fc.sort(key=lambda f: (-f["records_12m"], f["source_id"]))
    timely = [f["lag_days"] for f in fc if f["lag_days"] is not None and f["_lags"] >= 3 and f["_dated"] >= len(d) / 4
              and (f["cadence_hours"] is None or f["cadence_hours"] < 720)]
    n = len(evs)
    return {"records_12m": n, "dated": len(d), "dated_share": round(len(d) / n, 4) if n else None,
            "latest_dated": iso(latest), "lag_days": min(timely) if timely else None,
            # a feed published in batches months after the reports (TCEQ's table, meta.published_in_batches): the
            # grade sentence gives the delay from the newest report to the snapshot (Texas final audit 2026-11-07)
            **({"published_in_batches": True} if any((batches or {}).get(f["source_id"]) and f["_dated"] for f in fc)
               else {}),
            "monthly_share": round(sum(1 for e in evs if e.get("time_precision") == "month") / n, 4) if n else 0,
            "annual_share": round(sum(1 for e in evs if e.get("time_precision") == "year"
                                      or e.get("event_type") == "annual_total") / n, 4) if n else 0,
            "feeds": [{k: v for k, v in f.items() if not k.startswith("_")} for f in fc]}


# ---------------------------------------------------------------- how the public is told (docs/plan.md §2.y)

TOLD = ("online", "likelihood", "print_only", "login_only", "signs_only", "none")     # best first
TOLD_TEXT = {"online": "posted online for each overflow", "likelihood": "model or likelihood only",
             "print_only": "print only", "login_only": "login only", "signs_only": "signs only", "none": "nothing found"}
WEB_KINDS = {"operator_page", "state_alert_page", "feed", "shared_site", "local_health_page"}
_COVERS = re.compile(r"Covers(?: (every operator in the state)|:\s*([^.]*))", re.I)


def channel_told(r: dict, sewage_sources=frozenset()) -> str:
    """How one register row tells the public of an overflow (TOLD): on the open web for each overflow (a page,
    state table or feed that posts notices or a status, read by us or not; a bot wall stops machines, not people;
    EPA's dataset is the operators' reports to EPA, not a public notice), a model or likelihood, print, a login,
    signs, or nothing."""
    bar, pub, kind = r.get("barrier"), r.get("publishes"), r.get("channel_kind")
    if bar == "print_only":
        return "print_only"
    if bar == "login_required":
        return "login_only"
    if bar == "signs_only" or kind == "lights_signs_page":
        return "signs_only"
    if pub == "likelihood" or (pub == "link_only" and re.search(r"rain|likel|shared", str(r.get("link_text") or ""), re.I)):
        return "likelihood"
    if "-epa-echo-" in str(r.get("id")) or str(r.get("feed_source_id") or "").startswith(("echo-", "nj-echo-")) \
            or bar in ("no_web_page", "phone_only"):
        return "none"
    if kind in WEB_KINDS and (pub in ("notices", "status") or (r.get("unmonitored_reason") == "feed_ingested"
                                                               and pub == "unknown"
                                                               and r.get("feed_source_id") in sewage_sources)):
        return "online"
    return "none"


def notice_reach(register: dict, sewage_sources=frozenset()) -> dict[str, dict]:
    """Per state from the public-notice channel register: `barriers` {barrier: {count, ids}} (the operator id, or the
    channel id for an agency row) and `told_online` {operators, online, share, by_class, classes}: for each operator
    in the state's rows, the best way its overflows reach the public (TOLD) over its own channels and the agency
    channels that cover it (a note's "Covers every operator in the state" or "Covers: <ids>")."""
    rows = [r for r in (register or {}).get("channels") or [] if isinstance(r, dict)]
    by_state: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_state[str(r.get("state"))].append(r)
    out = {}
    for st, rs in sorted(by_state.items()):
        ops = sorted({r["operator_id"] for r in rs if r.get("operator_id")})
        barriers: dict[str, dict] = {}
        for r in rs:
            b = r.get("barrier")
            if b:
                e = barriers.setdefault(b, {"count": 0, "ids": set()})
                e["count"] += 1
                e["ids"].add(r.get("operator_id") or r["id"])
        best = {op: "none" for op in ops}
        for r in rs:
            m = _COVERS.search(str(r.get("note") or ""))
            covered = ops if m and m.group(1) else (
                [x.strip() for x in m.group(2).split(",") if x.strip() in best] if m else [])
            if r.get("operator_id") in best:
                covered = list(dict.fromkeys([r["operator_id"], *covered]))
            if not covered:
                continue
            how = channel_told(r, sewage_sources)
            for op in covered:
                if TOLD.index(how) < TOLD.index(best[op]):
                    best[op] = how
        classes = {k: sorted(op for op, v in best.items() if v == k) for k in TOLD}
        n = len(ops)
        out[st] = {"barriers": {b: {"count": e["count"], "ids": sorted(e["ids"])} for b, e in sorted(barriers.items())},
                   "told_online": {"operators": n, "online": len(classes["online"]),
                                   "share": round(len(classes["online"]) / n, 4) if n else None,
                                   "by_class": {k: len(v) for k, v in classes.items()},
                                   "labels": TOLD_TEXT, "classes": classes}}
    return out


def load_register(path=None) -> dict | None:
    """The notice-channel register in either layout (data/notice-channels.json or data/notice-channels/<st>.json;
    ingest/notification_pages.load_register), or None when there is none or it does not read."""
    from ingest import notification_pages as np_mod
    try:
        if np_mod.register_layout(path) == "none":
            return None
        return np_mod.load_register(path)
    except (OSError, ValueError):
        return None


def load_notification_pages(path=None) -> dict | None:
    """The page-health table of the public-notice channel monitor (ingest/notification_pages.py), or None."""
    import json
    from common import BUILD_DIR
    p = path or BUILD_DIR / "notice-pages" / "health.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def coverage(events: list[dict], waters, feeds: list[dict], registry: list[dict], dischargers: list[dict], rules: dict,
             as_of, rain_states: dict | None = None, source_names: dict | None = None,
             notification_pages: dict | None = None, register: dict | None = None,
             source_levels: dict | None = None) -> dict:
    """out/coverage.json: {built_from, as_of, definitions, states: {ST: {...}}, waters: {slug: {...}},
    rain_caution_states}. events: the public records (with `state`, `superseded`, `duplicate_of`); waters: the tracked
    water rows (slug, state, events); feeds and registry: out/sources.json's; rain_states: rain_caution_states;
    source_levels: {source_id: [the levels of its registry rows]} over the whole registry (EPA's eRule tables:
    fed-echo-sewer-overflow-bypass-events, level federal, states ["US"])."""
    from export import csv as csv_mod
    now = status_mod.parse_time(as_of) or datetime.now(UTC)
    start = now - timedelta(days=365)
    reg = {r.get("id"): r for r in registry or [] if isinstance(r, dict) and r.get("id")}
    # the site's sources: a feed takes its registry rows' event types and states
    feed_types, feed_states, cadence, batches, feed_rows = {}, {}, {}, {}, {}
    for f in feeds or []:
        sid = f.get("source_id")
        feed_rows[sid] = f
        rows = [reg[i] for i in f.get("registry_ids") or [] if i in reg]
        feed_types[sid] = {t for r in rows for t in r.get("event_types") or []}
        feed_states[sid] = [str(x).upper() for r in rows for x in r.get("states") or []]
        cadence[sid] = f.get("expected_cadence_hours")
        batches[sid] = bool(f.get("published_in_batches"))
    sewage_feeds = {sid for sid, ts in feed_types.items() if ts & SEWAGE}
    names = source_names if source_names is not None else csv_mod.source_labels(events, feeds, registry)
    rows = [w for w in (waters.values() if isinstance(waters, dict) else waters or []) if isinstance(w, dict) and w.get("slug")]
    source_states = {rid: [str(x).upper() for x in r.get("states") or []] for rid, r in reg.items()}
    source_states.update({sid: list(dict.fromkeys(v)) for sid, v in feed_states.items()})
    links = csv_mod.SiteLinks(events, rows, dischargers, (), as_of, source_states)     # the site's eventState
    by_state, firsts_state = defaultdict(list), defaultdict(list)
    kept: dict[str, dict] = {}
    for e in events:
        if e.get("event_type") not in SEWAGE or e.get("duplicate_of"):
            continue
        t = in_window_at(e)
        if t is None or t < start or t > now + timedelta(days=1):
            continue
        st = links.state_of(e)
        if not st:
            continue
        if not e.get("parent_event_id"):
            firsts_state[st].append(e)
        if e.get("superseded"):
            continue
        by_state[st].append(e)
        kept[e["event_id"]] = e
    codes = set(by_state) | {s for sid in sewage_feeds for s in feed_states.get(sid, [])}
    states = {}
    for st in sorted(c for c in codes if c in STATE_NAMES):        # postal codes only (a feed's "US" is no state)
        evs = by_state.get(st, [])
        ids = sorted({e.get("source_id") for e in evs} | {sid for sid in sewage_feeds if st in feed_states.get(sid, [])})
        own = {sid for sid in sewage_feeds if st in feed_states.get(sid, [])}
        f = _figures(evs, firsts_state.get(st, []), own, cadence, names, ids, batches)
        dated = {e.get("source_id") for e in evs if is_dated(e)}
        federal = bool(dated) and all(set((source_levels or {}).get(s) or []) == {"federal"} for s in dated)
        operator = None
        n_ops = sum(1 for r in dischargers or [] if isinstance(r, dict) and str(r.get("state") or "").upper() == st)
        if len(dated) == 1 and n_ops >= MIN_OPERATORS_FOR_PUBLISHER:
            sid = next(iter(dated))
            if set((source_levels or {}).get(sid) or []) == {"operator"}:
                operator = (reg.get(sid) or {}).get("attribution")
        grade, sentence = grade_of(st, f, now, federal=federal, operator=operator,
                                   unread=unreadable([feed_rows[s] for s in sorted(own) if s in feed_rows]))
        states[st] = {"code": st, "name": state_name(st), "duty": duty_sentence(rules, st), **f, "grade": grade,
                      "sentence": sentence, "rain_caution": (rain_states or {}).get(st)}
    # what stands in the way, and how each state's operators tell the public (the channel register; §2.y)
    sewage_sources = frozenset(e.get("source_id") for e in events if e.get("event_type") in SEWAGE)
    for st, block in notice_reach(register, sewage_sources).items():
        if st in states:
            states[st].update(block)
    # the notification-page health table, for each state the register has rows for (docs/plan.md §2.y)
    for st, block in ((notification_pages or {}).get("states") or {}).items():
        if st in states and isinstance(block, dict):
            states[st]["notification_pages"] = {"built": (notification_pages or {}).get("built"), **block}
    # per water: the reports placed on it (or listed on its page) in the same 12 months
    water_out = {}
    for w in rows:
        ids_on = set(csv_mod._ids_of(w.get("events")))
        evs = [kept[i] for i in ids_on if i in kept]
        firsts = [e for e in evs if not e.get("parent_event_id")]
        f = _figures(evs, firsts, set(), cadence, names, sorted({e.get("source_id") for e in evs}))
        st = str(w.get("state") or w["slug"][-2:]).upper()
        sg = (states[st]["grade"], states[st]["sentence"]) if st in states else None
        grade, sentence = water_grade(f, sg, now)
        water_out[w["slug"]] = {"state": st, "records_12m": f["records_12m"], "dated_share": f["dated_share"],
                                "latest_dated": f["latest_dated"], "monthly_share": f["monthly_share"],
                                "annual_share": f["annual_share"], "feeds": [x["source_id"] for x in f["feeds"]],
                                "grade": grade, "sentence": sentence, "state_grade": sg[0] if sg else None}
    return {"as_of": iso(now), "window_days": 365,
            "definitions": {"dated": "a report with a start to the day or better (to the minute, hour or day, a date "
                                     "range, or to the poll: opened or closed at the first check that showed it)",
                            "lag_days": "typical days from a discharge's start to its first report",
                            "grades": GRADES},
            "states": states, "waters": water_out, "rain_caution_states": rain_states or {}}
