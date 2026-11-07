"""Chart series per water, discharger and state from the events files (docs/plan.md §1, §5).

    python -m build.charts [--now 2026-11-02T12:00:00Z] [--only water:connecticut-river-ma,state:VT]

Run after build.status (it reads data/build/status.json for the placements and the ECHO duplicates,
so a chart puts an event on the same waters as the map) and before export. Writes
out/charts/water/<slug>.json, out/charts/discharger/<id>.json, out/charts/state/<st>.json and
out/charts/index.json. The site renders them with site/src/components/charts/.

What is counted (one rule set for every chart, written into each file as `rules`):
  - Fixture files (data/build/events/fixture-*.json) are left out: they are samples.
  - Revisions are folded in (build.status.resolve_revisions): a superseded record is not counted; a
    child without its own start inherits its parent's. ECHO records that repeat a state record
    (build.status.find_duplicates, plus status.json "duplicates") are not counted.
  - Notices versus reports. MassDEP publishes a Public Notification Report when a discharge
    starts and the permittee's Verified Data Report after the month ends (raw._report_class);
    Vermont DEC publishes operator Public Alerts and DEC-reviewed incident reports (raw._table).
    Within such a source, a discharger-month (discharger id, else npdes permit; local month of the
    start) that has any verified record counts those only; a discharger-month with none counts its
    notices. Connecticut's annual-report rows that repeat a dashboard record carry the ingester's
    duplicate_of and are dropped as duplicates, as on the map. Each file says how many events came
    from which class, and for every month whether its count rests on reports, notices or both
    (`basis`).
  - What affects a record (owner, 2026-11-02): a water's counts take every event status.py puts on
    the water, from status.json waters[slug].events: events placed on the water itself ("local":
    their outfall or named receiving water is on this record) and events from outfalls elsewhere
    whose modeled reach runs into it ("arriving", estimated; their states come from the reach's
    start water). A state's counts take the events its operators report ("local") and events from
    other states' outfalls whose reach runs into one of its waters ("arriving"). Every count is
    split local/arriving (`split`, `split_labels`, `arriving_states`), and the headline `tiles`
    say what they count. The water tile "reports_90d" counts the distinct records behind the
    last-90-days strip (history.json, the same derivation as the site's strip), so the two agree.
  - Discharge events are cso, sso, bypass, blended, plant_bypass and untyped records from discharge
    feeds, with a start (or a report time) and minute, hour or day precision. Month- and
    year-precision records (Maine DEP annual totals, EPA ECHO DMR outfall-months, Portsmouth's
    monthly table) are never events: they are the `reported_totals` series, by their source.
  - Hours under advisory: the red intervals of build.status.event_intervals (the map's rules):
    a discharge from its start to its end plus the authority's advice window (the event's
    advice_window_hours, else the state default); an `ongoing` discharge with no end for 72 h
    from its start; an official advisory while it is in effect (on a water: beach, rain and HAB
    advisories only where they colour the whole water, as on the map). Unioned per entity, cut at
    local month boundaries, never past now. A discharge whose reported end is more than
    MAX_EVENT_DAYS after its start is counted to MAX_EVENT_DAYS (the file says how many).
    Discharges with no reported end and status unknown/ended set caution, not an advisory, so they
    add no hours (counted in the file).
  - Coverage: a source covers from its first record to now, or, when its newest record is more
    than ARCHIVE_GAP_DAYS older than its last fetch (an archive), to its newest record. A source
    that reports per discharger (nh-permittees) covers per discharger. ECHO event extracts are
    sparse (SPARSE_SOURCES): their months count as "partial". Months and years with no covering
    source are null in `coverage`, and the caveat names the gaps; a zero inside coverage is a
    reported zero, a null is "no source".
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from build.status import (ADVISORY_TYPES, BEACH_CHAR, BLOOM_CHAR, COARSE_PRECISION, DISCHARGE_TYPES, LOCAL, POINT_ADVISORY_TYPES,
                          colours_whole_water, end_not_credible, event_intervals, event_state, find_duplicates,
                          future_start, load_events, live_waters, load_rules, load_waters, make_resolver, parse_time, resolve_revisions)
from common import BUILD_DIR, DATA_DIR, OUT_DIR, discharger_alias_map, now_iso, read_json, write_json

CHARTS_DIR = OUT_DIR / "charts"
WINDOW_YEARS = 5                 # monthly charts: January of (this year - 4) to this month
SEASON_MONTHS = (5, 10)          # May to October, inclusive
TOP_OUTFALLS = 10
MAX_EVENT_DAYS = 31
MAX_EVENT_GALLONS = 5e9          # a single report above this is an entry error (largest real ones: ~1e9)
ARCHIVE_GAP_DAYS = 90
FIRST_YEAR = 2000                # yearly charts never start before this
SPARSE_SOURCES = {"echo-sewer-overflow", "ri-echo-dfr"}
PER_DISCHARGER_SOURCES = {"nh-permittees"}
STATE_NAMES = {"MA": "Massachusetts", "CT": "Connecticut", "RI": "Rhode Island", "NH": "New Hampshire", "VT": "Vermont",
               "ME": "Maine", "NY": "New York", "NJ": "New Jersey", "PA": "Pennsylvania",
               "VA": "Virginia", "MD": "Maryland",
               "NC": "North Carolina", "GA": "Georgia", "FL": "Florida", "MI": "Michigan", "WA": "Washington", "CA": "California", "IL": "Illinois", "NE": "Nebraska"}
COUNT_RULE_LINE = "Verified reports where available, else notices; revisions and duplicates counted once."
MONTHS_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Event types folded to three display groups (fixed order = fixed colour slots 1..3 on the site).
GROUPS = [
    ("cso", "Combined sewer overflow", ("cso",)),
    ("sso", "Sanitary sewer overflow", ("sso",)),
    ("other", "Treatment bypass, blended or other", ("bypass", "plant_bypass", "blended", "unknown")),
]
GROUP_OF = {t: g for g, _, ts in GROUPS for t in ts}
# the label of the red status, as the site prints it (site/src/lib/status.ts)
STATUS_LABEL = "Discharge or advisory reported"

# Public names, spelled out (the chart footers and caveats are public copy: public-copy review 2026-11-02).
SOURCE_LABEL = {
    "ma-massdep": "Massachusetts Department of Environmental Protection sewage notification portal",
    "vt-dec": "Vermont Department of Environmental Conservation sewage overflow page",
    "ct-deep": "Connecticut Department of Energy and Environmental Protection sewage overflow dashboard",
    "ct-deep-archive": "Connecticut Department of Energy and Environmental Protection reporting archive, 2016 to 2021",
    "ct-deep-annual": "Connecticut Sewage Right-to-Know annual reports",
    "nh-permittees": "New Hampshire sewer operator notices (Nashua, Manchester, Portsmouth, Exeter)",
    "ri-nbc": "Narragansett Bay Commission combined sewer overflow feed",
    "ri-echo-dfr": "U.S. Environmental Protection Agency facility reports for Rhode Island",
    "echo-sewer-overflow": "U.S. Environmental Protection Agency sewer overflow records",
    "echo-cso-dmr-monthly": "U.S. Environmental Protection Agency discharge monitoring reports",
    "me-dep-cso-annual": "Maine Department of Environmental Protection combined sewer overflow reports",
    "me-healthy-beaches": "Maine Healthy Beaches",
    "nh-des-swimming": "New Hampshire Department of Environmental Services Healthy Swimming",
    "ri-dem-cyano": "Rhode Island Department of Environmental Management cyanobacteria advisories",
    "ri-ridoh-beaches": "Rhode Island Department of Health beach closures",
    "vt-advisories": "Vermont advisories (cyanobacteria, Burlington beaches)",
}

# Per-source caveats, by chart; {first} and {last} are the source's coverage dates, written out.
SOURCE_NOTES = {
    "ma-massdep": {"events": "Massachusetts portal records begin {first}. Verified Data Reports arrive after the month ends, so the latest months count public notices."},
    "vt-dec": {"volume": "Vermont gave volumes as ranges before 2024 (\">10,000 to 100,000 gallons\"); those records have no single number and are not summed."},
    "ct-deep-archive": {"events": "Connecticut's reporting archive runs from {first} to {last}.",
                        "volume": "Connecticut's 2016 to 2021 archive gives volumes as ranges (\"20,001 - 50,000 gallons\"); they are not summed."},
    "ct-deep": {"events": "Connecticut dashboard records begin {first}; annual-report rows that repeat a dashboard record are counted once."},
    "ct-deep-annual": {"events": "Connecticut's Sewage Right-to-Know annual reports cover {first} to {last}.", "volume": "Some volumes in Connecticut's annual reports are given as text or ranges and are not summed."},
    "nh-permittees": {"events": "New Hampshire sewer operators publish on their own pages; each operator's record begins on a different date."},
    "echo-sewer-overflow": {"events": "The U.S. Environmental Protection Agency's sewer overflow records are limited: they hold only what operators file with the agency."},
    "ri-echo-dfr": {"events": "The U.S. Environmental Protection Agency's facility reports for Rhode Island are limited: they hold only what operators file with the agency."},
    "ri-nbc": {"events": "The Narragansett Bay Commission feed shows current overflows only; our record begins {first}."},
}
TOTAL_NOTES = {
    "me-dep-cso-annual": "Maine's Department of Environmental Protection reports one total per community and year, for all of its combined sewer outlets; the total is shown in full on each water the community's outlets reach. Event-days: calendar days with any combined sewer discharge in the community.",
    "echo-cso-dmr-monthly": "Monthly totals each operator files with the U.S. Environmental Protection Agency for each outlet (discharge monitoring reports). They describe the same discharges the state notices report, so they are shown here and never added to the discharge counts. A month with no row counts as zero inside the date range.",
    "nh-permittees": "Portsmouth publishes monthly combined sewer overflow volumes for each outlet, not individual discharges.",
}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]


def prose_day(d: str | None) -> str | None:
    """2021-12-02 -> December 2, 2021 (dates inside caveats are prose)."""
    if not d:
        return d
    y, m, dd = d.split("-")
    return f"{MONTH_NAMES[int(m) - 1]} {int(dd)}, {y}"


def prose_period(k: str) -> str:
    """2022-01 -> January 2022; a year stays."""
    if len(k) == 7 and k[4] == "-":
        return f"{MONTH_NAMES[int(k[5:]) - 1]} {k[:4]}"
    return k


# ---------------------------------------------------------------- time helpers

def local(dt: datetime) -> datetime:
    return dt.astimezone(LOCAL)


def month_key(dt: datetime) -> str:
    d = local(dt)
    return f"{d.year:04d}-{d.month:02d}"


def month_start(y: int, m: int) -> datetime:
    return datetime(y, m, 1, tzinfo=LOCAL)


def next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def month_range(y0: int, m0: int, y1: int, m1: int) -> list[str]:
    out, (y, m) = [], (y0, m0)
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = next_month(y, m)
    return out


def bounds_of_month(key: str) -> tuple[datetime, datetime]:
    y, m = int(key[:4]), int(key[5:7])
    return month_start(y, m), month_start(*next_month(y, m))


def day(dt: datetime | None) -> str | None:
    return local(dt).date().isoformat() if dt else None


def hours(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 3600)


def union(ivs: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out = []
    for s, e in sorted(ivs):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def overlap_hours(ivs: list[tuple[datetime, datetime]], a: datetime, b: datetime) -> float:
    return sum(hours(max(s, a), min(e, b)) for s, e in ivs if s < b and e > a)


def subtract(ivs, cut):
    """ivs minus cut (both unions)."""
    out = []
    for s, e in ivs:
        pieces = [(s, e)]
        for cs, ce in cut:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append((ps, pe))
                    continue
                if cs > ps:
                    nxt.append((ps, cs))
                if ce < pe:
                    nxt.append((ce, pe))
            pieces = nxt
        out.extend(pieces)
    return out


# ---------------------------------------------------------------- classification

# Sources that publish the same discharges twice, first as a notice and later as a report: the
# family name, and the class of each member file (a file whose records carry their own class, like
# ma-massdep and vt-dec, is a family of one).
# (Connecticut's dashboard and annual report were a family here until the ingester marked the
# annual rows that repeat a dashboard record with duplicate_of; the map drops those as duplicates,
# and so do the charts. A family rule on top would drop both copies.)
FAMILIES: dict[str, str] = {}
FILE_CLASS: dict[str, tuple[str, str]] = {}


def family(ev: dict) -> str:
    sid = ev.get("source_id") or "?"
    return FAMILIES.get(sid, sid)


def report_class(ev: dict) -> tuple[str | None, str | None]:
    """('verified' | 'notice' | None, the source's own name for the class)."""
    if ev.get("source_id") in FILE_CLASS:
        return FILE_CLASS[ev["source_id"]]
    raw = ev.get("raw") or {}
    rc = raw.get("_report_class")
    if isinstance(rc, str) and rc:
        return ("verified" if "verified" in rc.lower() else "notice"), rc
    t = raw.get("_table")
    if isinstance(t, str) and t and str(ev.get("source_id", "")).startswith("vt-dec"):
        return ("notice" if "alert" in t.lower() else "verified"), t
    return None, None


def when(ev: dict) -> datetime | None:
    return parse_time(ev.get("started_at")) or parse_time(ev.get("reported_at")) or parse_time(ev.get("published_at"))


def is_total(ev: dict) -> bool:
    return ev.get("event_type") == "annual_total" or ev.get("time_precision") in COARSE_PRECISION


def disch_key(ev: dict) -> str:
    return ev.get("discharger_id") or ev.get("npdes_permit") or ev.get("discharger_name") or "?"


def range_text(t) -> bool:
    s = str(t or "").lower()
    return bool(re.search(r"\d[\d,.]*\s*(to|-|–)\s*[\d,.]+|>|under|over|less than|more than", s))


# ---------------------------------------------------------------- loading

class Data:
    def __init__(self, now: datetime):
        self.now = now
        self.waters = live_waters(load_waters())     # the live states' records only (rules.json live_states)
        self.rules = load_rules()
        files, events, problems = load_events(include_fixtures=False)
        # an event's discharger_id that the registry lists as an alias is the row's id here too (as in the
        # export), so a discharger's chart is one series under the id its page uses
        aliases = discharger_alias_map([d for d in read_json(DATA_DIR / "dischargers.json", []) or [] if isinstance(d, dict)])
        for ev in events:
            if ev.get("discharger_id") in aliases:
                ev["discharger_id"] = aliases[ev["discharger_id"]]
        self.files = files
        self.problems = list(problems)
        self.status = read_json(BUILD_DIR / "status.json", {}) or {}
        self.history = read_json(BUILD_DIR / "history.json", {}) or {}
        self.placements = self.status.get("placements") or {}
        by_id = {}
        for ev in events:
            by_id.setdefault(ev["event_id"], ev)
        self.by_id = by_id
        # a start more than a day in the future as published is no report to date: not counted (status.future_start)
        self.events = [ev for ev in by_id.values() if not future_start(ev, now)]
        self.superseded, self.effective = resolve_revisions(self.events, by_id)
        # duplicates as the map drops them: ECHO repeats, the ingester's own duplicate_of, status.json's list
        self.duplicates = dict(find_duplicates(self.events))
        for ev in self.events:
            if ev.get("duplicate_of") and ev["duplicate_of"] != ev["event_id"]:
                self.duplicates[ev["event_id"]] = ev["duplicate_of"]
        for k, v in (self.status.get("duplicates") or {}).items():
            if k in by_id:
                self.duplicates.setdefault(k, v)
        # every water status.py puts an event on (placed, or on a modeled reach that runs into it)
        self.members: dict[str, set] = defaultdict(set)
        for slug, w in (self.status.get("waters") or {}).items():
            for eid in w.get("events") or []:
                self.members[eid].add(slug)
        self.reaches = self.status.get("reaches") or {}
        self.dropped: dict[str, str] = {}       # event id -> why the charts do not count it
        self._resolver = None
        self.resolved_here = 0
        self.dischargers = {}
        for d in read_json(DATA_DIR / "dischargers.json", []) or []:
            if isinstance(d, dict) and d.get("id"):
                self.dischargers[d["id"]] = d

    def slugs(self, ev: dict) -> list[str]:
        """The waters the event is placed on itself (status.py's placement)."""
        pl = self.placements.get(ev["event_id"])
        if pl is not None:
            return [s for s in pl.get("water_slugs") or [] if s in self.waters]
        if self._resolver is None:
            self._resolver = make_resolver(self.waters)
        self.resolved_here += 1
        try:
            pl = self._resolver.resolve(ev)
        except Exception as e:  # placement must never stop the charts
            self.problems.append(f"{ev['event_id']}: placement failed ({e})")
            return []
        return [s for s in pl.get("water_slugs") or [] if s in self.waters]

    def operator_short(self, ev: dict) -> str | None:
        """The operator's short name (data/dischargers.json short_name, else its name without the "City of" and
        the plant words), for "arriving from outfalls upstream on the <water>, <operator>"."""
        d = self.dischargers.get(ev.get("discharger_id")) or {}
        return d.get("short_name") or short_operator(d.get("name") or ev.get("discharger_name"))

    def water_links(self, ev: dict) -> list[tuple[str, str]]:
        """[(slug, 'local' | 'arriving')]: placed on the water, or arriving on a modeled reach."""
        on = set(self.slugs(ev))
        allw = on | self.members.get(ev["event_id"], set())
        return [(sl, "local" if sl in on else "arriving") for sl in sorted(allw) if sl in self.waters]

    def origin(self, ev: dict) -> tuple[str | None, dict | None]:
        """(state, water record) where the event's outfall is: the reach's start water, else its own
        placement, else the operator's state."""
        pl = self.placements.get(ev["event_id"]) or {}
        r = self.reaches.get(pl.get("reach")) if pl.get("reach") else None
        for slug in ([r.get("water_slug")] if r else []) + list(pl.get("water_slugs") or []):
            if slug in self.waters:
                return self.waters[slug].get("state"), {**self.waters[slug], "slug": slug}
        return event_state(ev), None


# ---------------------------------------------------------------- source coverage

def source_spans(data: Data) -> tuple[dict, dict]:
    """({source_id: (first, last)}, {(source_id, discharger key): (first, last)}) as aware datetimes."""
    first, last = {}, {}
    pfirst, plast = {}, {}
    for ev in data.events:
        sid = ev.get("source_id")
        t = when(ev)
        if t is None:
            continue
        e = parse_time(ev.get("ended_at")) or t
        if e < t or (e - t).days > MAX_EVENT_DAYS * 13:
            e = t
        for d1, d2, k in ((first, last, sid), (pfirst, plast, (sid, disch_key(ev)))):
            if k not in d1 or t < d1[k]:
                d1[k] = t
            if k not in d2 or e > d2[k]:
                d2[k] = e

    def end_for(sid, newest):
        f = data.files.get(sid) or {}
        fetched = parse_time(f.get("last_ok_at") or f.get("fetched_at")) or data.now
        if (fetched - newest).days > ARCHIVE_GAP_DAYS:
            return newest
        return data.now

    spans = {sid: (first[sid], end_for(sid, last[sid])) for sid in first}
    per = {k: (pfirst[k], end_for(k[0], plast[k])) for k in pfirst}
    return spans, per


# ---------------------------------------------------------------- the per-entity record

class Bucket:
    def __init__(self, kind: str, key: str):
        self.kind, self.key = kind, key
        self.events: list[dict] = []          # counted discharge events (effective records)
        self.advisories: list[dict] = []      # official advisories that colour this entity
        self.totals: list[dict] = []          # month/year totals
        self.cov: set = set()                 # coverage keys: sid or (sid, discharger key)
        self.cov_arriving: set = set()        # sources of arriving events only: partial coverage
        self.state: str | None = None
        self.via: dict[str, str] = {}         # event id -> "local" | "arriving"
        self.from_state: dict[str, str | None] = {}   # event id -> the state its outfall is in
        self.from_where: dict[str, tuple] = {}         # event id -> (its outfall's water name, operator short name)


def gather(data: Data):
    """Pick the counted events and drop them into the water, discharger and state buckets."""
    stats = Counter()
    # 1. candidates
    disch_sources = {ev.get("source_id") for ev in data.events
                     if ev.get("event_type") in DISCHARGE_TYPES and not is_total(ev)}
    cands = []
    for ev in data.events:
        eid = ev["event_id"]
        et = ev.get("event_type") or "unknown"
        if is_total(ev):
            continue
        if et not in DISCHARGE_TYPES and not (et == "unknown" and ev.get("source_id") in disch_sources):
            continue
        if eid in data.superseded:
            stats["superseded"] += 1
            data.dropped[eid] = "superseded"
            continue
        if eid in data.duplicates:
            stats["duplicate"] += 1
            data.dropped[eid] = "duplicate"
            continue
        eff = data.effective.get(eid, ev)
        if when(eff) is None:
            stats["undated"] += 1
            data.dropped[eid] = "undated"
            continue
        cands.append(eff)
    # 2. notices versus verified reports, per discharger-month
    classes_by_source = defaultdict(set)
    for ev in data.events:
        c, _ = report_class(ev)
        if c:
            classes_by_source[family(ev)].add(c)
    two_class = {s for s, cs in classes_by_source.items() if {"verified", "notice"} <= cs}
    has_verified = set()
    for ev in cands:
        if family(ev) in two_class and report_class(ev)[0] == "verified":
            has_verified.add((family(ev), disch_key(ev), month_key(when(ev))))
    counted = []
    for ev in cands:
        fam = family(ev)
        cls, _ = report_class(ev)
        if fam in two_class:
            k = (fam, disch_key(ev), month_key(when(ev)))
            if k in has_verified and cls != "verified":
                stats["notice_in_verified_month"] += 1
                data.dropped[ev["event_id"]] = "notice_in_verified_month"
                continue
            basis = "verified" if cls == "verified" else "notice"
        else:
            basis = "single"
        ev = {**ev, "_basis": basis, "_group": GROUP_OF.get(ev.get("event_type") or "unknown", "other")}
        counted.append(ev)
        stats[f"counted_{basis}"] += 1

    buckets: dict[tuple[str, str], Bucket] = {}

    def b(kind, key):
        k = (kind, key)
        if k not in buckets:
            buckets[k] = Bucket(kind, key)
        return buckets[k]

    def cov_key(ev):
        sid = ev.get("source_id")
        return (sid, disch_key(ev)) if sid in PER_DISCHARGER_SOURCES else sid

    for ev in counted:
        eid = ev["event_id"]
        o_state, o_water = data.origin(ev)
        st = event_state(ev) or o_state          # the operator's state
        where = ((o_water or {}).get("name"), data.operator_short(ev))
        o_state = o_state or st
        links = data.water_links(ev)
        targets = []
        for slug, via in links:
            bw = b("water", slug)
            bw.state = data.waters[slug].get("state")
            targets.append((bw, via, o_state))
        if ev.get("discharger_id"):
            bd = b("discharger", ev["discharger_id"])
            bd.state = bd.state or st
            targets.append((bd, "local", st))
        if st:
            bs = b("state", st)
            bs.state = st
            targets.append((bs, "local", st))
        # what crossed the line: the event reaches a water of another state (placed there, or on a reach)
        for other in sorted({data.waters[sl].get("state") for sl, _ in links} - {st, None}):
            bo = b("state", other)
            bo.state = other
            targets.append((bo, "arriving", st))
        for t, via, frm in targets:
            t.events.append(ev)
            t.via[eid] = via
            t.from_state[eid] = frm
            t.from_where[eid] = where
            (t.cov if via == "local" else t.cov_arriving).add(cov_key(ev))

    # official advisories: waters only, where they colour the water (the map's rule)
    for ev in data.events:
        eid = ev["event_id"]
        if is_total(ev) or eid in data.superseded or eid in data.duplicates:
            continue
        if ev.get("event_type") not in ADVISORY_TYPES and ev.get("status") not in ("advisory_active", "advisory_lifted"):
            continue
        eff = data.effective.get(eid, ev)
        for slug in data.slugs(ev):
            w = data.waters[slug]
            if ev.get("event_type") in POINT_ADVISORY_TYPES and not colours_whole_water(w):
                continue
            bw = b("water", slug)
            bw.state = w.get("state")
            bw.advisories.append(eff)
            bw.cov.add(ev.get("source_id"))

    # totals
    for ev in data.events:
        if not is_total(ev) or ev["event_id"] in data.superseded:
            continue
        st = event_state(ev)
        targets = [b("water", s) for s in data.slugs(ev)]
        for t in targets:
            t.state = data.waters[t.key].get("state")
        if ev.get("discharger_id"):
            targets.append(b("discharger", ev["discharger_id"]))
        if st:
            targets.append(b("state", st))
        for t in targets:
            t.totals.append(ev)
            t.state = t.state or st
    # every water the map tracks gets a file, even an empty one; the feeds that cover its outfalls
    # cover it for the charts too (a zero there is a reported zero)
    for slug, sw in (data.status.get("waters") or {}).items():
        if slug in data.waters:
            bw = b("water", slug)
            bw.state = data.waters[slug].get("state")
            for sid in sw.get("covered_by") or []:
                if sid in disch_sources and sid not in PER_DISCHARGER_SOURCES and sid in data.files:
                    bw.cov.add(sid)
    return buckets, stats, two_class


# ---------------------------------------------------------------- the charts of one entity

def coverage_spans(bucket: Bucket, spans: dict, per: dict):
    """(start, end, partial, source id) per covering source. A source seen only through arriving
    events (an upstream state's feed) is partial cover for this record."""
    out = []
    for k in bucket.cov | bucket.cov_arriving:
        sp = per.get(k) if isinstance(k, tuple) else spans.get(k)
        if sp:
            sid = k[0] if isinstance(k, tuple) else k
            out.append((sp[0], sp[1], sid in SPARSE_SOURCES or k not in bucket.cov, sid))
    return out


def coverage_of(spans_list, a: datetime, b: datetime):
    """'full' | 'partial' | None for the period [a, b) (b already cut at now)."""
    best = None
    for s, e, sparse, _ in spans_list:
        if s >= b or e <= a:
            continue
        if not sparse and s <= a and e >= b:
            return "full"
        best = "partial"
    return best


def gaps_text(x: list[str], cov: list) -> str | None:
    runs, start = [], None
    for i, c in enumerate(cov + ["x"]):
        if c is None and start is None:
            start = i
        elif c is not None and start is not None:
            runs.append((x[start], x[i - 1]))
            start = None
    if not runs:
        return None
    parts = [prose_period(a) if a == b else f"{prose_period(a)} to {prose_period(b)}" for a, b in runs]
    return "No tracked source covers " + ", ".join(parts) + "."


def series_meta(sources, first, last, caveats):
    cav = " ".join(c for c in dict.fromkeys(c for c in caveats if c)) or None
    return {"source_ids": sorted(sources), "first": day(first), "last": day(last), "caveat": cav}


def red_intervals(ev: dict, state: str | None, now: datetime, capped: Counter, water: dict | None = None,
                  rules: dict | None = None):
    s, e = parse_time(ev.get("started_at")), parse_time(ev.get("ended_at"))
    if s and e and (e - s).days > MAX_EVENT_DAYS and not end_not_credible(ev, now, rules):   # else: no end at all
        ev = {**ev, "ended_at": (s + timedelta(days=MAX_EVENT_DAYS)).isoformat()}
        capped["long"] += 1
    out = []
    for iv in event_intervals(ev, state, now, water=water, rules=rules):
        if iv["color"] != "red":
            continue
        a, z = iv["start"], iv["end"] or now
        z = min(z, now)
        if z > a:
            out.append((a, z))
    return out


def discharge_days(ev: dict) -> list:
    s = when(ev)
    e = parse_time(ev.get("ended_at"))
    if e is None or e < s or (e - s).days > MAX_EVENT_DAYS:
        return [local(s).date()]
    if ev.get("time_precision") == "day" and local(e).hour == 0 and local(e).minute == 0 and e > s:
        e = e - timedelta(seconds=1)   # a day-only end is that day, already counted from midnight
    d0, d1 = local(s).date(), local(e).date()
    out, d = [], d0
    while d <= d1:
        out.append(d)
        d += timedelta(days=1)
    return out


def outfall_label(ev: dict) -> tuple[str, str]:
    oid = (ev.get("outfall_id") or "").strip()
    name = (ev.get("outfall_name") or "").strip()
    if not oid and not name:
        return "", ""
    key = f"{disch_key(ev)}|{re.sub(r'[^A-Z0-9]', '', oid.upper()) or name.lower()}"
    return key, (f"{oid} {name}".strip() if oid and name and name.upper() != oid.upper() else (oid or name))


def total_measures(ev: dict) -> dict[str, float]:
    """The figures a month/year total carries: gallons, plus events / hours / event-days when given."""
    out = {}
    if ev.get("volume_gal") is not None:
        out["gallons"] = float(ev["volume_gal"])
    raw = ev.get("raw") or {}
    params = raw.get("parameters") or {}

    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None
    if isinstance(params, dict):
        if num((params.get("events") or {}).get("DMRValueNmbr")) is not None:
            out["events"] = num(params["events"]["DMRValueNmbr"])
        if num((params.get("duration") or {}).get("DMRValueNmbr")) is not None:
            out["hours"] = num(params["duration"]["DMRValueNmbr"])
    if num(raw.get("event_days")) is not None:
        out["event_days"] = num(raw["event_days"])
    return out


MEASURE_LABEL = {"gallons": ("Reported volume", "gallons"), "events": ("Discharges reported", "discharges"),
                 "hours": ("Hours of discharge reported", "hours"), "event_days": ("Days with a combined sewer discharge", "days")}


def build_entity(bucket: Bucket, data: Data, spans: dict, per: dict, name: str | None) -> dict:
    now = data.now
    ln = local(now)
    y_now, m_now = ln.year, ln.month
    months = month_range(y_now - WINDOW_YEARS + 1, 1, y_now, m_now)
    win_a = bounds_of_month(months[0])[0]
    cov_list = coverage_spans(bucket, spans, per)
    ev_sources = {e.get("source_id") for e in bucket.events}
    adv_sources = {e.get("source_id") for e in bucket.advisories}
    cov_disch = [c for c in cov_list if c[3] in ev_sources or c[3] not in adv_sources]
    cov_first = min((c[0] for c in cov_list), default=None)

    def month_cov(spans_list):
        out = []
        for k in months:
            a, z = bounds_of_month(k)
            out.append(coverage_of(spans_list, a, min(z, now)))
        return out

    m_cov = month_cov(cov_disch)
    gap = gaps_text(months, m_cov)

    def note(sid, chart, first=None, last=None):
        t = (SOURCE_NOTES.get(sid) or {}).get(chart)
        if not t:
            return None
        sp = spans.get(sid)
        return t.format(first=prose_day(day(first or (sp[0] if sp else None))), last=prose_day(day(last or (sp[1] if sp else None))))

    def meta_for(sources, caveats, clip_a=None):
        sel = [c for c in cov_list if c[3] in sources] or cov_list
        f = min((c[0] for c in sel), default=None)
        z = max((c[1] for c in sel), default=None)
        if f and clip_a:
            f = max(f, clip_a)
        return series_meta(sources, f, min(z, now) if z else None, caveats)

    charts = {}
    absent = {}
    split_on = bucket.kind in ("water", "state")

    def is_loc(ev):
        return bucket.via.get(ev["event_id"], "local") == "local"

    def split_block(loc, arr):
        return {"split": {"local": loc, "arriving": arr}} if split_on else {}

    # (a) events per month by type, last five years
    idx = {k: i for i, k in enumerate(months)}
    vals = {g: [0] * len(months) for g, _, _ in GROUPS}
    basis_sets = [set() for _ in months]
    in_window = 0
    loc_m, arr_m = [0] * len(months), [0] * len(months)
    for ev in bucket.events:
        k = month_key(when(ev))
        if k in idx:
            vals[ev["_group"]][idx[k]] += 1
            basis_sets[idx[k]].add(ev["_basis"])
            in_window += 1
            (loc_m if is_loc(ev) else arr_m)[idx[k]] += 1
    basis = []
    for s in basis_sets:
        s = s - {"single"} if len(s) > 1 else s
        basis.append(None if not s else ("mixed" if len(s) > 1 else next(iter(s))))
    by_class = Counter(ev["_basis"] for ev in bucket.events if month_key(when(ev)) in idx)
    win_sources = {ev.get("source_id") for ev in bucket.events if month_key(when(ev)) in idx}
    if bucket.events or any(c for c in m_cov):
        totals_note = ("Some sewer operators here report only monthly or yearly totals; those appear under reported totals and are not counted here."
                       if bucket.totals else None)
        charts["events_by_month"] = {
            "title": "Reported discharges per month", "unit": "events", "period": "month", "form": "stacked-columns",
            "x": months,
            "series": [{"key": g, "label": lab, "types": list(ts), "values": vals[g]} for g, lab, ts in GROUPS],
            "total": in_window, "coverage": m_cov, "basis": basis, **split_block(loc_m, arr_m),
            "count_basis": {"verified": by_class.get("verified", 0), "notice": by_class.get("notice", 0),
                            "single_class": by_class.get("single", 0),
                            "rule": "Where a source publishes both notices and later confirmed reports (Massachusetts Verified Data Reports, Vermont's reviewed incident reports, Connecticut's annual reports), an operator's month with any confirmed report counts those reports only; other months count notices."},
            **meta_for(win_sources or {c[3] for c in cov_disch},
                       [gap] + [note(s, "events") for s in sorted(win_sources)] + [totals_note], win_a),
        }
    else:
        absent["events_by_month"] = "no discharge events and no covering discharge source"

    # yearly frame: first covered year to this year
    first_year = max(FIRST_YEAR, local(cov_first).year) if cov_first else None
    years = [str(y) for y in range(first_year, y_now + 1)] if first_year else []
    y_idx = {y: i for i, y in enumerate(years)}

    def year_cov(spans_list):
        out = []
        for y in years:
            a, z = month_start(int(y), 1), month_start(int(y) + 1, 1)
            out.append(coverage_of(spans_list, a, min(z, now)))
        return out
    y_cov = year_cov(cov_disch) if years else []
    y_gap = gaps_text(years, y_cov) if years else None

    # events per year by type (all covered years)
    if bucket.events and years:
        yv = {g: [0] * len(years) for g, _, _ in GROUPS}
        loc_y, arr_y = [0] * len(years), [0] * len(years)
        for ev in bucket.events:
            y = str(local(when(ev)).year)
            if y in y_idx:
                yv[ev["_group"]][y_idx[y]] += 1
                (loc_y if is_loc(ev) else arr_y)[y_idx[y]] += 1
        charts["events_by_year"] = {
            "title": "Reported discharges per year", "unit": "events", "period": "year", "form": "stacked-columns",
            "x": years, "series": [{"key": g, "label": lab, "types": list(ts), "values": yv[g]} for g, lab, ts in GROUPS],
            "total": sum(sum(v) for v in yv.values()), "coverage": y_cov, **split_block(loc_y, arr_y),
            **meta_for(ev_sources, [y_gap] + [note(s, "events") for s in sorted(ev_sources)]),
        }

    # (b) reported volume per year
    if bucket.events and years:
        vol = [0.0] * len(years)
        vol_l, vol_r = [0.0] * len(years), [0.0] * len(years)
        with_n = [0] * len(years)
        without = [0] * len(years)
        ranged = Counter()
        lacking_by_source = Counter()
        implausible = []
        for ev in bucket.events:
            y = str(local(when(ev)).year)
            if y not in y_idx:
                continue
            if ev.get("volume_gal") is not None and float(ev["volume_gal"]) > MAX_EVENT_GALLONS:
                implausible.append(ev["event_id"])
                without[y_idx[y]] += 1
                lacking_by_source[ev.get("source_id")] += 1
                continue
            if ev.get("volume_gal") is not None:
                vol[y_idx[y]] += float(ev["volume_gal"])
                (vol_l if is_loc(ev) else vol_r)[y_idx[y]] += float(ev["volume_gal"])
                with_n[y_idx[y]] += 1
            else:
                without[y_idx[y]] += 1
                lacking_by_source[ev.get("source_id")] += 1
                if range_text(ev.get("volume_text")):
                    ranged[ev.get("source_id")] += 1
        n_with, n_without = sum(with_n), sum(without)
        cav = [y_gap]
        if n_without:
            cav.append(f"{n_without:,} of {n_with + n_without:,} discharge reports gave no volume as a number"
                       + (f" ({sum(ranged.values()):,} gave a range)" if ranged else "") + "; only numbers are summed.")
        cav += [note(s, "volume") for s in sorted(ranged)]
        if implausible:
            cav.append(f"{len(implausible):,} {'report gives' if len(implausible) == 1 else 'reports give'} more than "
                       f"{MAX_EVENT_GALLONS / 1e9:g} billion gallons for a single discharge, which looks like an entry error; "
                       f"{'it is' if len(implausible) == 1 else 'they are'} not summed.")
        if n_with:
            charts["volume_by_year"] = {
                "title": "Reported volume per year", "unit": "gallons", "period": "year", "form": "columns",
                "x": years, "series": [{"key": "gallons", "label": "Reported volume", "values": [round(v) for v in vol]}],
                "with_volume": with_n, "without_volume": without, "events_with_volume": n_with, "events_without_volume": n_without,
                "without_volume_by_source": dict(lacking_by_source), "implausible_volume_ids": implausible, "coverage": y_cov,
                **split_block([round(v) for v in vol_l], [round(v) for v in vol_r]),
                **meta_for(ev_sources, cav),
            }
        else:
            absent["volume_by_year"] = f"none of the {n_without:,} discharge reports gave a volume as a number"

    # (c) hours under advisory, (g) season share
    capped = Counter()
    d_ivs, a_ivs, l_ivs, r_ivs = [], [], [], []
    no_hours = 0
    w_self = {**data.waters[bucket.key], "slug": bucket.key} if bucket.kind == "water" else None
    for ev in bucket.events:
        if bucket.kind == "water" and not is_loc(ev):
            st, w0 = data.origin(ev)                 # windows of the state where the outfall is
        elif bucket.kind == "water":
            st, w0 = bucket.state, w_self
        else:
            st, w0 = event_state(ev), None
        r = red_intervals(ev, st, now, capped, water=w0, rules=data.rules)
        if not r:
            no_hours += 1
        d_ivs += r
        (l_ivs if is_loc(ev) else r_ivs).extend(r)
    for ev in bucket.advisories:
        a_ivs += red_intervals(ev, bucket.state, now, capped, water=w_self, rules=data.rules)
    l_u, r_u = union(l_ivs), union(r_ivs)
    d_u = union(d_ivs)
    all_u = union(d_ivs + a_ivs)
    adv_only = union(subtract(all_u, d_u)) if a_ivs else []
    adv_cov = coverage_spans(bucket, spans, per)   # discharge + advisory sources
    if (bucket.events or bucket.advisories) and years:
        m_cov_all = month_cov(adv_cov)
        def upto_now(k):
            a, z = bounds_of_month(k)
            return a, min(z, now)
        hm = [round(overlap_hours(all_u, *upto_now(k)), 1) for k in months]
        hm_d = [round(overlap_hours(d_u, *upto_now(k)), 1) for k in months]
        hm_a = [round(overlap_hours(adv_only, *upto_now(k)), 1) for k in months]
        hm_l = [round(overlap_hours(l_u, *upto_now(k)), 1) for k in months]
        hm_r = [round(overlap_hours(r_u, *upto_now(k)), 1) for k in months]
        span_h = [round(hours(*upto_now(k)), 1) for k in months]
        who = {"water": "this water", "discharger": "this sewer operator's reports", "state": "at least one water in the state"}[bucket.kind]
        cav = [gaps_text(months, m_cov_all)]
        if no_hours:
            one = no_hours == 1
            cav.append(f"{no_hours:,} discharge {'report has' if one else 'reports have'} no end time and {'is' if one else 'are'} not marked ongoing; "
                       f"under DirtyWaterWatch rules {'it shows' if one else 'they show'} caution, not a discharge or advisory status, and add{'s' if one else ''} no hours here.")
        if capped["long"]:
            cav.append(f"{capped['long']:,} {'discharge reported' if capped['long'] == 1 else 'discharges reported'} to last more than {MAX_EVENT_DAYS} days {'is' if capped['long'] == 1 else 'are'} counted as {MAX_EVENT_DAYS} days.")
        if bucket.kind != "water":
            cav.append("Official beach and cyanobacteria (harmful blue-green algae) advisories are counted on water pages only.")
        meta = meta_for(ev_sources | adv_sources, cav + [note(s, "events") for s in sorted(ev_sources)])
        rule = ("Hours with a discharge or advisory status under DirtyWaterWatch rules: a discharge from its start to its reported end "
                "plus the post-discharge period for its state (48 hours in Massachusetts, Vermont, Connecticut and Rhode Island, and "
                "where Nashua's notices state one); an ongoing discharge with no end for 72 hours; an official advisory while it is in effect.")
        charts["advisory_hours_by_month"] = {
            "title": "Hours with a discharge or advisory status per month", "unit": "hours", "period": "month", "form": "status-columns",
            "status": "red", "status_label": STATUS_LABEL, "scope": who,
            "x": months, "series": [{"key": "hours", "label": "Hours with a discharge or advisory status", "values": hm}],
            "parts": {"discharge_window": hm_d, "official_advisory_only": hm_a,
                      **({"local_events": hm_l, "arriving_events": hm_r} if split_on else {})},
            "parts_additive": False, "period_hours": span_h,
            "coverage": m_cov_all, "rule": rule, **meta,
        }
        y_cov_all = year_cov(adv_cov)
        hy, hy_d, hy_l, hy_r, sy, season = [], [], [], [], [], []
        for y in years:
            a, z = month_start(int(y), 1), min(month_start(int(y) + 1, 1), now)
            hy.append(round(overlap_hours(all_u, a, z), 1))
            hy_d.append(round(overlap_hours(d_u, a, z), 1))
            hy_l.append(round(overlap_hours(l_u, a, z), 1))
            hy_r.append(round(overlap_hours(r_u, a, z), 1))
            sy.append(round(hours(a, z), 1))
            s_a = month_start(int(y), SEASON_MONTHS[0])
            s_z = month_start(*next_month(int(y), SEASON_MONTHS[1]))
            if s_a >= now:
                season.append(None)
                continue
            s_end = min(s_z, now)
            covered = union([(max(s, s_a), min(e, s_end)) for s, e, sparse, _ in adv_cov
                             if not sparse and s < s_end and e > s_a])
            cov_h = sum(hours(s, e) for s, e in covered)
            if cov_h <= 0:
                season.append(None)
                continue
            adv_h = overlap_hours(union([(max(s, a2), min(e, b2)) for s, e in all_u for a2, b2 in covered if s < b2 and e > a2]), s_a, s_end)
            season.append({"share": round(adv_h / cov_h, 4), "hours": round(adv_h, 1), "covered_hours": round(cov_h, 1),
                           "season_hours": round(hours(s_a, s_z), 1),
                           "partial": cov_h < hours(s_a, s_z) - 1})
        charts["advisory_hours_by_year"] = {
            "title": "Hours with a discharge or advisory status per year", "unit": "hours", "period": "year", "form": "status-columns",
            "status": "red", "status_label": STATUS_LABEL, "scope": who,
            "x": years, "series": [{"key": "hours", "label": "Hours with a discharge or advisory status", "values": hy}],
            "parts": {"discharge_window": hy_d, **({"local_events": hy_l, "arriving_events": hy_r} if split_on else {})},
            "parts_additive": False, "period_hours": sy, "coverage": y_cov_all, "rule": rule,
            **meta, "caveat": " ".join(c for c in [gaps_text(years, y_cov_all)] + cav[1:] if c) or None,
        }
        sx = [y for y, s in zip(years, season) if s is not None]
        sv = [s for s in season if s is not None]
        if not sx:
            absent["season_share_by_year"] = "no season with a full-coverage source"
        if sx:
            part = [y for y, s in zip(sx, sv) if s["partial"]]
            charts["season_share_by_year"] = {
                "title": "Share of the May to October season with a discharge or advisory status", "unit": "share", "period": "year",
                "form": "status-line", "status": "red", "status_label": STATUS_LABEL, "scope": who,
                "x": sx, "series": [{"key": "share", "label": "Share of season hours with a discharge or advisory status", "values": [s["share"] for s in sv]}],
                "hours": [s["hours"] for s in sv], "covered_hours": [s["covered_hours"] for s in sv],
                "season_hours": [s["season_hours"] for s in sv], "partial": [s["partial"] for s in sv],
                "rule": rule + " Share: those hours from May 1 to October 31, over the season hours a tracked source covered (the limited U.S. Environmental Protection Agency records do not count as coverage).",
                **meta, "caveat": " ".join(c for c in ([f"Seasons with incomplete source coverage: {', '.join(part)}. The share is of the hours a source covered."] if part else []) + cav[1:] if c) or None,
            }

    # (d) days with any discharge per month
    if bucket.events:
        days_by_month, days_l, days_r = defaultdict(set), defaultdict(set), defaultdict(set)
        for ev in bucket.events:
            for d in discharge_days(ev):
                mk = f"{d.year:04d}-{d.month:02d}"
                days_by_month[mk].add(d)
                (days_l if is_loc(ev) else days_r)[mk].add(d)
        dv = [len(days_by_month.get(k, ())) for k in months]
        if any(dv) or any(m_cov):
            charts["discharge_days_by_month"] = {
                "title": "Days with a reported discharge per month", "unit": "days", "period": "month", "form": "columns",
                "x": months, "series": [{"key": "days", "label": "Days with a reported discharge", "values": dv}],
                "coverage": m_cov, **split_block([len(days_l.get(k, ())) for k in months], [len(days_r.get(k, ())) for k in months]),
                "split_additive": False,
                "rule": "A day counts when any counted discharge was under way on it, from its start to its reported end in Eastern Time; a report with no end counts its start day.",
                **meta_for(win_sources or ev_sources, [gap], win_a),
            }

    # (e) events by outfall, top 10 and the rest
    if bucket.events:
        cnt, labels, dname, unnamed, arr_k = Counter(), {}, {}, 0, Counter()
        for ev in bucket.events:
            k, lab = outfall_label(ev)
            if not k:
                unnamed += 1
                continue
            cnt[k] += 1
            labels.setdefault(k, lab)
            dname.setdefault(k, ev.get("discharger_name"))
            if not is_loc(ev):
                arr_k[k] += 1
        if cnt:
            top = cnt.most_common(TOP_OUTFALLS)
            rest = sum(cnt.values()) - sum(n for _, n in top)
            cats = [{"key": k, "label": labels[k], "discharger": dname[k], "value": n,
                     **({"arriving": arr_k[k] * 2 > n} if split_on else {})} for k, n in top]
            if rest:
                cats.append({"key": "_other", "label": f"Other outlets ({len(cnt) - len(top)})", "discharger": None, "value": rest, "other": True})
            if unnamed:
                cats.append({"key": "_unstated", "label": "Outlet not stated", "discharger": None, "value": unnamed, "other": True})
            charts["events_by_outfall"] = {
                "title": "Reported discharges by wastewater outlet", "unit": "events", "form": "bars",
                "categories": cats, "outfalls": len(cnt), "total": sum(cnt.values()) + unnamed,
                **meta_for(ev_sources, [note(s, "events") for s in sorted(ev_sources)]),
            }

    # (f) seasonality: events by calendar month, all years
    if bucket.events:
        sc = [0] * 12
        sc_l, sc_r = [0] * 12, [0] * 12
        yrs_seen = [set() for _ in range(12)]
        for ev in bucket.events:
            t = local(when(ev))
            sc[t.month - 1] += 1
            (sc_l if is_loc(ev) else sc_r)[t.month - 1] += 1
        for s, e, sparse, _ in cov_disch:
            if sparse:
                continue
            y, m = local(s).year, local(s).month
            while (y, m) <= (local(e).year, local(e).month):
                yrs_seen[m - 1].add(y)
                y, m = next_month(y, m)
        charts["seasonality"] = {
            "title": "Reported discharges by calendar month, all years", "unit": "events", "form": "columns",
            "x": MONTHS_ABBR, "series": [{"key": "events", "label": "Reported discharges", "values": sc}],
            "years_covered": [len(s) for s in yrs_seen], **split_block(sc_l, sc_r),
            **meta_for(ev_sources,
                        ["Months are summed over every year a tracked source covers; the table gives the number of years behind each month."]),
        }

    # (h) reported totals (month and year precision), by source
    tot = []
    groups = defaultdict(list)
    for ev in bucket.totals:
        groups[(ev.get("source_id"), "year" if ev.get("time_precision") == "year" or ev.get("event_type") == "annual_total" else "month")].append(ev)
    for (sid, period), evs in sorted(groups.items()):
        starts = [parse_time(e.get("started_at")) for e in evs if parse_time(e.get("started_at"))]
        if not starts:
            continue
        lo = min(starts)
        hi = max(parse_time(e.get("ended_at")) or parse_time(e.get("started_at")) for e in evs if parse_time(e.get("started_at")))
        if period == "year":
            x = [str(y) for y in range(local(lo).year, local(hi).year + 1)]
            keyf = lambda e: str(local(parse_time(e["started_at"])).year)
        else:
            x = month_range(local(lo).year, local(lo).month, local(hi).year, local(hi).month)
            keyf = lambda e: month_key(parse_time(e["started_at"]))
        xi = {k: i for i, k in enumerate(x)}
        nx = len(x)
        meas = defaultdict(lambda nx=nx: [0.0] * nx)
        rows = [0] * len(x)
        perms = set()
        for e in evs:
            k = keyf(e)
            if k not in xi:
                continue
            rows[xi[k]] += 1
            perms.add(e.get("discharger_name") or disch_key(e))
            for mk, v in total_measures(e).items():
                meas[mk][xi[k]] += v
        series = [{"key": mk, "label": MEASURE_LABEL[mk][0], "unit": MEASURE_LABEL[mk][1], "values": [round(v, 1) for v in vals_]}
                  for mk, vals_ in sorted(meas.items(), key=lambda kv: list(MEASURE_LABEL).index(kv[0]))]
        cav = [TOTAL_NOTES.get(sid)]
        if len(perms) > 1:
            cav.append(f"Sum of {len(perms)} reporting sewer operators.")
            for se in series:
                if se["key"] == "event_days":
                    se["label"], se["unit"] = "Community event-days, summed", "community event-days"
        tot.append({
            "title": f"Reported {'yearly' if period == 'year' else 'monthly'} totals: {SOURCE_LABEL.get(sid, sid)}",
            "source_name": SOURCE_LABEL.get(sid, sid), "period": period, "form": "small-multiples",
            "x": x, "series": series, "rows": rows,
            **series_meta({sid}, lo, hi, cav),
        })
    if tot:
        charts["reported_totals"] = tot

    # sources behind this entity
    srcs = []
    for s, e, sparse, sid in sorted(cov_list, key=lambda c: (c[3], c[0])):
        srcs.append({"source_id": sid, "name": SOURCE_LABEL.get(sid, sid), "first": day(s), "last": day(e),
                     "to_now": e >= now, "sparse": sparse})
    used = {c[3] for c in cov_list} | {e.get("source_id") for e in bucket.totals} | ev_sources | adv_sources
    names = {sid: SOURCE_LABEL.get(sid, sid) for sid in sorted(x for x in used if x)}
    doc = {
        "kind": bucket.kind, "id": bucket.key, "name": name, "state": bucket.state,
        "state_name": STATE_NAMES.get(bucket.state or "", bucket.state),
        "generated_at": now_iso(), "now": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "counts": {"events": len(bucket.events), "advisories": len(bucket.advisories), "totals": len(bucket.totals),
                   **({"local": sum(1 for e in bucket.events if is_loc(e)),
                       "arriving": sum(1 for e in bucket.events if not is_loc(e))} if split_on else {})},
        "sources": srcs, "source_names": names, "charts": charts, "absent": absent,
    }
    doc.update(headline(bucket, data, doc, months, l_u if bucket.events else [], r_u if bucket.events else []))
    return doc


def short_operator(name) -> str | None:
    """"City of Montpelier Water Resource Recovery Facility ..." -> "Montpelier"; "Town of Brattleboro WWTF" -> "Brattleboro"."""
    if not name:
        return None
    t = re.sub(r"^(?:City|Town|Village|Borough|County|Township) of\s+", "", str(name).strip(), flags=re.I)
    t = re.split(r"\s+(?:WWTF|WWTP|WRRF|WPCF|WPCA|POTW|STP|AWTF|Wastewater|Water Resource|Water Pollution|Pollution Control|"
                 r"Sewer|Sewage|combined sewer|collection system|DPW|Department|pump)\b|\s*[(,]", t, maxsplit=1, flags=re.I)[0]
    return t.strip(" -,") or str(name)


def items_text(items: list[str], most: int = 3) -> str:
    """Up to `most` items joined with "; ", then "and N more"."""
    if len(items) <= most:
        return "; ".join(items)
    return "; ".join(items[:most]) + f"; and {len(items) - most} more"


def the_name(name: str) -> str:
    """The water's name with the article it takes in a sentence: "the Buffalo River", "the Winooski River", but
    "Lake Anna", "Alley Pond", "Cayuga Lake" and "The Reservoir" never take another "the" (a name that starts with
    "Lake " or "The ", or ends in " Pond" or " Lake"; review 2026-11-03 H1)."""
    n = (name or "").strip()
    if re.match(r"(?i)(lake|the)\s", n) or re.search(r"(?i)\s(pond|lake)$", n):
        return n
    return f"the {n}"


RIVER_KINDS = ("river", "stream", "canal")


def this_water(kind: str | None) -> str:
    """The tile's noun for the water: "this stretch" for a river, stream or canal; a lake is "this lake" and a pond "this
    pond"; any other water, or one of unknown kind, "this water" (a stretch is a piece of a river; review 2026-11-03 H2)."""
    if kind in RIVER_KINDS:
        return "this stretch"
    return f"this {kind}" if kind in ("lake", "pond") else "this water"


def stretch_words(name: str, state: str | None, st_name: str, groups: list[tuple]) -> dict:
    """The water tile's wording for the reports arriving from upstream (owner, 2026-11-03: "0 reported in Vermont,
    11 arriving from upstream outfalls in Vermont" said the same state on both sides). groups: [(state, water name,
    operator), ...] of the arriving reports, most first. Outfalls in the water's own state are named by water and
    operator ("outfalls upstream on the Winooski River, Montpelier"), and the local side reads "on the <water>";
    outfalls in another state keep the state, also naming the water and operator. Outfalls on another record of this
    very water (a river kept as several records of one name) are "further up" it, with the operator in brackets, so
    the same name is not set on both sides bare ("50 reported on the Buffalo River; 1 arriving from outfalls further up
    the Buffalo River (Buffalo)"). Returns {local_where, local_label, arriving, arriving_label}."""
    def item(w, op):
        return ", ".join(x for x in ((the_name(w) if w else None), op) if x) or "an outfall"
    def own(w):
        return bool(w) and " ".join(str(w).split()).lower() == " ".join(str(name).split()).lower()
    in_state = [(w, op) for s, w, op in groups if s == state]
    same = [item(w, op) for w, op in in_state if not own(w)]
    further = [op for w, op in in_state if own(w)]
    other: dict[str, list[str]] = {}
    for s, w, op in groups:
        if s != state:
            other.setdefault(s or "", []).append(item(w, op))
    parts = []
    if same:
        parts.append(f"outfalls upstream on {items_text(list(dict.fromkeys(same)))}")
    if further:
        ops = list(dict.fromkeys(op for op in further if op))
        parts.append(f"outfalls further up {the_name(name)}" + (f" ({items_text(ops)})" if ops else ""))
    for s, its in other.items():
        where = f"upstream outfalls in {STATE_NAMES.get(s, s)}" if s else "upstream outfalls"
        parts.append(f"{where}: {items_text(list(dict.fromkeys(its)))}")
    arriving = "; ".join(parts) if parts else "upstream"
    local_where = f"on {the_name(name)}" if in_state or not groups else f"in {st_name}"
    return {"local_where": local_where,
            "local_label": f"Reported on {the_name(name)}" + ("" if in_state else f" in {st_name}"),
            "arriving": arriving, "arriving_label": f"Arriving from {arriving}, estimated"}


def states_text(codes: list[str]) -> str:
    names = [STATE_NAMES.get(c, c) for c in codes if c]
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def strip_records(data: Data, slug: str):
    """The distinct records behind the water's last-90-days strip, derived as the site derives
    them (site/src/lib/data.ts loadHistory): for each hour the strip shows red, yellow or
    unresolved, the events of that colour whose interval overlaps the hour. None without a strip."""
    h = data.history
    strip = (h.get("waters") or {}).get(slug)
    if not isinstance(strip, str) or not h.get("start"):
        return None
    start = parse_time(h["start"])
    n = min(len(strip), h.get("count") or len(h.get("hours") or []) or len(strip))
    code = {"red": "r", "yellow": "y", "unresolved": "u"}
    ids = set()
    for x in (h.get("intervals") or {}).get(slug) or []:
        if len(x) < 5 or x[2] not in code or not x[4]:
            continue
        cat = x[5] if len(x) > 5 else "sewage"            # beach and bloom hours have letters of their own (§2.z)
        want = code[x[2]] if cat == "sewage" else (BEACH_CHAR.get(x[2]) if cat == "beach" else BLOOM_CHAR)
        a = parse_time(x[0])
        z = parse_time(x[1]) if x[1] else None
        if a is None:
            continue
        i0 = max(0, math.floor((a - start).total_seconds() / 3600))
        i1 = n if z is None else min(n, math.ceil((z - start).total_seconds() / 3600))
        if any(strip[i] == want for i in range(i0, i1)):
            ids.add(x[4])
    return ids, start, start + timedelta(hours=n)


def headline(bucket: Bucket, data: Data, doc: dict, months: list[str], l_u, r_u) -> dict:
    """The tiles (each says what it counts and by which rule), the local/arriving labels, and for a
    water the reconciliation with the strip (strip_90d) and the counts per rule (counts_by_rule)."""
    out: dict = {}
    ch = doc["charts"]
    name, st_name = doc.get("name") or bucket.key, doc.get("state_name") or bucket.state or ""
    last12 = set(months[-12:])
    span12 = f"{prose_period(months[-12])} to {prose_period(months[-1])}"
    arr_all = Counter(bucket.from_state.get(e["event_id"]) for e in bucket.events if bucket.via.get(e["event_id"]) == "arriving")
    arr_12 = Counter(bucket.from_state.get(e["event_id"]) for e in bucket.events
                     if bucket.via.get(e["event_id"]) == "arriving" and month_key(when(e)) in last12)
    order_all = [c for c, _ in arr_all.most_common() if c]
    order_12 = [c for c, _ in arr_12.most_common() if c] or order_all
    kind = bucket.kind
    w_kind = (data.waters.get(bucket.key) or {}).get("kind") if kind == "water" else None    # river, lake, pond ...
    def groups(only12: bool) -> list[tuple]:
        c = Counter((bucket.from_state.get(e["event_id"]), *bucket.from_where.get(e["event_id"], (None, None)))
                    for e in bucket.events if bucket.via.get(e["event_id"]) == "arriving"
                    and (not only12 or month_key(when(e)) in last12))
        return [g for g, _ in c.most_common()]
    words_all = stretch_words(name, bucket.state, st_name, groups(False)) if kind == "water" else None
    words_12 = stretch_words(name, bucket.state, st_name, groups(True) or groups(False)) if kind == "water" else None
    if kind == "water":
        loc_label = words_all["local_label"]
        arr_label = words_all["arriving_label"] if groups(False) else "Arriving from outfalls upstream, estimated"
        subject = f"{the_name(name)} in {st_name}"
    elif kind == "state":
        loc_label = f"Reported by {st_name} operators"
        other = [c for c in order_all if c != bucket.state]
        arr_label = f"Arriving from other states ({states_text(other)}), estimated" if other else "Arriving from other states, estimated"
        subject = f"{st_name} waters"
    else:
        loc_label, arr_label, subject = None, None, name
    if kind in ("water", "state"):
        out["split_labels"] = {"local": loc_label, "arriving": arr_label}
        out["arriving_states"] = {c: n for c, n in arr_all.most_common() if c}
        out["arriving_states_12m"] = {c: n for c, n in arr_12.most_common() if c}

    def from_text(codes):
        if not codes:
            return "upstream"
        if kind == "water" and bucket.state in codes:
            return f"upstream outfalls in {states_text(codes)}"
        return states_text(codes)

    def sum12(c, arr=None):
        if not c:
            return 0
        vals = arr if arr is not None else [sum(v) for v in zip(*[se["values"] for se in c["series"]])]
        return round(sum(vals[-12:]), 1)

    tiles = []
    em, dm, am, ss = ch.get("events_by_month"), ch.get("discharge_days_by_month"), ch.get("advisory_hours_by_month"), ch.get("season_share_by_year")
    if em:
        n = int(sum12(em))
        t = {"key": "discharges_12m", "value": n, "period": span12,
             "label": (f"Discharges affecting {subject}, last 12 months" if kind != "discharger"
                       else f"Discharges reported by {name}, last 12 months"),
             "rule": COUNT_RULE_LINE + (" Arriving discharges are estimated from modeled downstream reaches." if kind != "discharger" else "")}
        if kind in ("water", "state") and em.get("split"):
            a, b = int(sum12(em, em["split"]["local"])), int(sum12(em, em["split"]["arriving"]))
            if kind == "water":       # by water and operator; a state only for outfalls in another state
                arriving = f"{b:,} arriving from {words_12['arriving']}" if b else "none arriving from upstream"
                t["headline"] = f"{n:,} affecting {this_water(w_kind)}: {a:,} reported {words_12['local_where']}; {arriving}"
            else:
                arriving = f"{b:,} arriving from {from_text(order_12)}" if b else "none arriving from upstream"
                t["headline"] = f"{n:,} affecting {st_name} waters: {a:,} reported by {st_name} operators, {arriving}"
            t["parts"] = [{"key": "local", "label": loc_label, "value": a},
                          {"key": "arriving", "label": arr_label, "value": b, "by_state": out["arriving_states_12m"]}]
            t["parts_additive"] = True
        tiles.append(t)
    if dm:
        t = {"key": "discharge_days_12m", "value": int(sum12(dm)), "period": span12,
             "label": (f"Days with a discharge affecting {subject}, last 12 months" if kind != "discharger"
                       else f"Days with a discharge reported by {name}, last 12 months"),
             "rule": "A day counts once however many discharges were under way on it. " + COUNT_RULE_LINE}
        if dm.get("split"):
            t["parts"] = [{"key": "local", "label": loc_label, "value": int(sum12(dm, dm["split"]["local"]))},
                          {"key": "arriving", "label": arr_label, "value": int(sum12(dm, dm["split"]["arriving"]))}]
            t["parts_additive"] = False
        tiles.append(t)
    if am:
        t = {"key": "status_hours_12m", "value": round(sum12(am)), "period": span12,
             "label": (f"Hours with a discharge or advisory status on {subject}, last 12 months" if kind == "water"
                       else f"Hours with a discharge or advisory status on at least one {st_name} water, last 12 months" if kind == "state"
                       else f"Hours with a discharge or advisory status from {name}'s reports, last 12 months"),
             "rule": "Red hours by the map's rules: each discharge to its reported end plus the state's post-discharge period; overlapping hours count once."}
        parts = am.get("parts") or {}
        if "local_events" in parts:
            t["parts"] = [{"key": "local", "label": loc_label, "value": round(sum12(am, parts["local_events"]))},
                          {"key": "arriving", "label": arr_label, "value": round(sum12(am, parts["arriving_events"]))}]
            # hours under an official advisory (beach, algal bloom) and no discharge are in the total and in neither
            # discharge part ("548 hours; reported 0, arriving 0"): a part of their own, so the parts account for it
            adv = round(sum12(am, parts["official_advisory_only"])) if parts.get("official_advisory_only") else 0
            if adv:
                t["parts"].append({"key": "official_advisories", "label": "Official advisories (beach, algal bloom)", "value": adv})
            # reported and arriving hours can overlap (counted once in the total): additive only where they do not
            t["parts_additive"] = sum(p["value"] for p in t["parts"]) == t["value"]
        tiles.append(t)
    if ss and ss.get("x"):
        i = len(ss["x"]) - 1
        tiles.append({"key": "season_share_latest", "value": ss["series"][0]["values"][i], "unit": "share",
                      "period": f"May to October {ss['x'][i]}", "partial": bool((ss.get("partial") or [False])[i]),
                      "label": f"{ss['x'][i]} season with a discharge or advisory status on {subject}" if kind == "water"
                      else f"{ss['x'][i]} season with a discharge or advisory status ({subject})",
                      "rule": "Share of May 1 to October 31 hours with red status by the map's rules, of the hours a source covered."})

    if kind == "water":
        rec = strip_records(data, bucket.key)
        if rec is not None:
            ids, h0, h1 = rec
            loc_ids = {i for i in ids if i in data.by_id and bucket.key in data.slugs(data.by_id[i])}
            arr_ids = {i for i in ids if i in data.by_id and i not in loc_ids}
            other_ids = ids - loc_ids - arr_ids
            why, xt = Counter(), Counter()
            before = 0
            for i in ids:
                r = "counted_in_charts" if i in bucket.via else (data.dropped.get(i) or ("not_a_discharge_record" if i in data.by_id else "not_an_event_record"))
                why[r] += 1
                xt[f"{'local' if i in loc_ids else 'arriving' if i in arr_ids else 'other'}/{r}"] += 1
                ev = data.effective.get(i) or data.by_id.get(i)
                if ev is not None and when(ev) is not None and when(ev) < h0:
                    before += 1
            started = Counter(bucket.via.get(e["event_id"]) for e in bucket.events if h0 <= when(e) < h1)
            out["strip_90d"] = {"records": len(ids), "local": len(loc_ids), "arriving": len(arr_ids), "other": len(other_ids),
                                "from": h0.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                                "to": h1.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                                "by_chart_rule": dict(why), "by_placement_and_rule": dict(sorted(xt.items())),
                                "started_before_window": before,
                                "counted_events_started_in_window": {"local": started.get("local", 0), "arriving": started.get("arriving", 0)}}
            tiles.append({"key": "reports_90d", "value": len(ids), "period": "last 90 days",
                          "label": f"Records behind the last-90-days strip for {the_name(name)} in {st_name}",
                          "rule": "Every distinct record the strip lists for its red, yellow and unresolved hours, notices and unresolved reports included; counted as the strip counts them.",
                          "parts": [{"key": "local", "label": loc_label, "value": len(loc_ids)},
                                    {"key": "arriving", "label": arr_label, "value": len(arr_ids)},
                                    *([{"key": "other", "label": "Other records (rain-likely and similar)", "value": len(other_ids)}] if other_ids else [])],
                          "parts_additive": True})
        listed = set(((data.status.get("waters") or {}).get(bucket.key) or {}).get("events") or [])
        cbr = Counter()
        for i in listed:
            ev = data.by_id.get(i)
            if ev is None:
                cbr["not_loaded (fixture or withheld)"] += 1
            elif i in bucket.via:
                cbr[f"counted_{bucket.via[i]}"] += 1
            elif i in data.dropped:
                cbr[data.dropped[i]] += 1
            elif is_total(ev):
                cbr["monthly_or_yearly_total"] += 1
            else:
                cbr["advisory_or_other_record"] += 1
        cbr["counted_not_listed_by_status"] = sum(1 for i in bucket.via if i not in listed)
        out["counts_by_rule"] = {"listed_by_status": len(listed), **dict(sorted(cbr.items()))}
        others = sorted({w.get("state") for sl, w in data.waters.items()
                         if sl != bucket.key and w.get("name") == doc.get("name") and w.get("state") != bucket.state} - {None})
        if others:
            if w_kind in RIVER_KINDS:
                out["tiles_note"] = f"This record covers {the_name(name)} within {st_name}; the same river upstream is a separate record."
            else:    # a lake or pond has no upstream: "this lake", never a stretch
                same = w_kind if w_kind in ("lake", "pond") else "water"
                out["tiles_note"] = f"This record covers {the_name(name)} within {st_name}; the same {same} in another state is a separate record."
    out["tiles"] = tiles
    return out


RULES_TEXT = [l.strip() for l in (__doc__ or "").split("What is counted")[1].splitlines()[1:] if l.strip()] if __doc__ else []


def entity_name(kind: str, key: str, bucket: Bucket, data: Data) -> str | None:
    if kind == "water":
        return (data.waters.get(key) or {}).get("name")
    if kind == "discharger":
        d = data.dischargers.get(key)
        if d and d.get("name"):
            return d["name"]
        c = Counter(e.get("discharger_name") for e in bucket.events + bucket.totals if e.get("discharger_name"))
        return c.most_common(1)[0][0] if c else None
    return {"MA": "Massachusetts", "CT": "Connecticut", "RI": "Rhode Island", "NH": "New Hampshire", "VT": "Vermont",
            "ME": "Maine", "NY": "New York"}.get(key, key)


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def build(now: datetime | None = None, only: set | None = None, write: bool = True):
    now = (now or datetime.now(UTC)).astimezone(UTC)
    data = Data(now)
    spans, per = source_spans(data)
    buckets, stats, two_class = gather(data)
    index = {"generated_at": now_iso(), "now": now.isoformat().replace("+00:00", "Z"), "rules": RULES_TEXT,
             "two_class_sources": sorted(two_class), "selection": dict(stats),
             "water": {}, "discharger": {}, "state": {}}
    written = Counter()
    for (kind, key), bk in sorted(buckets.items()):
        if only and f"{kind}:{key}" not in only:
            continue
        name = entity_name(kind, key, bk, data)
        doc = build_entity(bk, data, spans, per, name)
        fname = safe_name(key.upper() if kind == "state" else key)
        if write:
            write_json(CHARTS_DIR / kind / f"{fname}.json", doc)
        written[kind] += 1
        index[kind][key] = {"file": f"{kind}/{fname}.json", "name": name, "events": len(bk.events),
                            "charts": sorted(doc["charts"])}
    index["written"] = dict(written)
    if write and not only:              # files of entities that no longer exist would go stale
        keep = {f"{k}/{v['file'].split('/', 1)[1]}" for k in ("water", "discharger", "state") for v in index[k].values()}
        pruned = 0
        for kind in ("water", "discharger", "state"):
            for f in (CHARTS_DIR / kind).glob("*.json"):
                if f"{kind}/{f.name}" not in keep:
                    f.unlink()
                    pruned += 1
        index["pruned"] = pruned
    index["placed_here"] = data.resolved_here
    index["problems"] = data.problems[:50]
    if write and not only:
        write_json(CHARTS_DIR / "index.json", index)
    return index


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--now", help="evaluate at this time (ISO 8601)")
    ap.add_argument("--only", help="comma list of kind:id (water:connecticut-river-ma,state:VT)")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    idx = build(now=parse_time(a.now) if a.now else None, only=only)
    print(f"charts: {idx['written']} files; selection {idx['selection']}; two-class sources {idx['two_class_sources']}; "
          f"placed here (not in status.json) {idx['placed_here']}")
    for p in idx["problems"][:10]:
        print("  problem:", p, file=sys.stderr)


if __name__ == "__main__":
    main()
