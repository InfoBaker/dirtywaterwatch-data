"""San Diego Water Board table of USIBWC spill and transboundary flow events -> data/build/events/ca-sd-regional-board-ibwc-spills.json

Source
  San Diego Regional Water Quality Control Board, "USIBWC Spill Events and Transboundary Flow Events from Mexico into
  the San Diego Region", an HTML table on
  https://www.waterboards.ca.gov/sandiego/water_issues/programs/tijuana_river_valley_strategy/sewage_issue.html
  Columns: Start Date, End Date, Event Type, Discharge Location, Approximate Discharge Volume, Volume Recovered, Notes.
  The page: the table "summarizes the information that USIBWC has reported to the San Diego Water Board since July 1,
  2024" and "is updated, if needed, approximately once a week"; USIBWC reports these events under Order No.
  R9-2021-0001 (NPDES CA0108928, the South Bay International Wastewater Treatment Plant), preliminary Spill Event and
  canyon collector reports within three days and monthly reports for Tijuana River flows. Earlier events are in the
  Board's Executive Officer's Reports (November 2021 to September 2024), not read here. No key, no licence statement.
  Credit "San Diego Regional Water Quality Control Board (data from USIBWC)". The server sends no Last-Modified; the
  page's own "Page last updated" date is kept in meta.

What is read (privacy)
  The seven columns. The table names agencies, facilities and places, no person; the Notes text still passes
  common.scrub_text and every raw passes common.strip_personal (in event()) and build.redact last.

Record rules (one record per table row)
  - Key: the table has no identifier, so source_record_id is the row's start date, the water its location names and a
    hash of the location ("2024-06-17-goat-canyon-<6 hex>"; a second row with both the same gets "-n2"). A change of
    the tracked fields (notes included) across runs is kept in raw._revisions; a row that leaves the table keeps its
    record with raw._missing_from_table_since. A Board correction of a row's start date or location makes a new key:
    the old record stays, marked missing from the table (no row identity survives such an edit). A row an earlier read
    listed as ongoing whose end cell no longer reads ongoing and gives no end keeps raw._ongoing_listing (the last read
    that listed it as ongoing, the first that did not), set once (mark_ongoing_listing).
  - Text: the location and the notes pass common.scrub_text and strip_house_numbers before any use.
  - Times: the table gives dates only (Pacific): started_at and ended_at are bare dates, time_precision "day",
    raw.time_zone America/Los_Angeles. reported_at and published_at are null: the table gives neither (the page says
    when USIBWC must report, not when each row was reported or posted); raw._first_seen_at is the first fetch that
    showed the row. source_updated_at is a date the row's own notes give for the report ("Volume reported by USIBWC
    on 04/30/2026"), else null.
  - End: a date at or after the start -> ended. An end cell that starts with "Ongoing" -> ongoing with no end (the
    status build's rule for an ongoing report with no end applies, counted from the start). A blank or other end ->
    unknown with no end ("end not confirmed"). An end before the start is kept as published (ended_at), one more than
    a day after the read only in raw._end_as_published (the shared rule would draw a window to it); both have status
    unknown and raw._end_not_used, and no window is drawn from them. No end is ever made up.
  - Event type, by a written rule on the table's own Event Type wording (EVENT_KINDS; never a model): "Spill Event"
    (the page: a release of waste "from any portion of USIBWC's Facility"), "Dry Weather Canyon Collector
    Transboundary Flow Event" (a dry-weather flow across the border in one of the five collector canyons not captured
    for treatment) and "Tijuana River Transboundary Flow Event" (any flow across the border in the Tijuana River, wet
    or dry) are each read as a sewage discharge, event_type sso, the kinds kept in raw.event_kinds; wording that
    matches none is event_type unknown with a parse_error, so the review queue sees it.
  - Operator: a row whose type includes "Spill Event" is USIBWC's (discharger ca-usibwc-south-bay, permit
    CA0108928). A transboundary flow that is not a Spill Event comes from Mexico: no operator is joined, and
    raw.reported_by says who reported it.
  - Volume: the approximate discharge volume as the table gives it ("17.7 million gallons" -> 17,700,000), estimate
    flag "estimated"; the volume recovered is kept beside it. A row with no volume has none.
  - Water and point: the table gives no coordinates, so none are used. waterbody_text is the water the discharge
    location names: the Tijuana River, or one of the five canyons the page lists (Stewart's Drain, Canyon del Sol,
    Silva Drain, Smuggler's Gulch, Goat Canyon), also when the location is a facility named for its canyon ("Goat
    Canyon Pump Station", "Del Sol Canyon Collector"); a location that names no water (Hollister Street Pump Station)
    has none. The record carries a water slug only when a California water record of that name lies in the Tijuana
    River valley (VALLEY_BOX); otherwise it is unplaced and counted (meta.unplaced_by_water).
    raw._placement "named_water_only": never placed through the permit's ocean outfall or by any other route.

Reading: one GET of the page (about 57 KB), at most every MIN_HOURS hours (the table changes about once a week; the
other runs keep the last records and say so). A page without the table, or with fewer than half the rows of the last
good read, is an outage (ok false, the records kept).

Run from pipeline/:  python -m ingest.ca_sd_tijuana_table [--file saved.html] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import requests

from common import BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, event, now_iso, read_json, save_raw, scrub_text, \
    strip_house_numbers, write_events, write_json

SOURCE_ID = "ca-sd-regional-board-ibwc-spills"
PAGE_URL = ("https://www.waterboards.ca.gov/sandiego/water_issues/programs/tijuana_river_valley_strategy/"
            "sewage_issue.html")
STATE_FILE = BUILD_DIR / "ca-sd-tijuana-state.json"
AUTHORITY = "San Diego Regional Water Quality Control Board (table of events USIBWC reported)"
CREDIT = "San Diego Regional Water Quality Control Board, USIBWC Spill Events and Transboundary Flow Events table"
TZ = "America/Los_Angeles"
MIN_HOURS = 6
DISCHARGER_ID = "ca-usibwc-south-bay"
DISCHARGER_NAME = "US Section, International Boundary and Water Commission"
PERMIT = "CA0108928"
REPORTED_BY = ("the US Section of the International Boundary and Water Commission (USIBWC), under Order No. "
               "R9-2021-0001 (NPDES CA0108928)")

COLUMNS = {"start date": "start", "end date": "end", "event type": "event_type", "discharge location": "location",
           "approximate discharge volume": "volume", "volume recovered": "recovered", "notes": "notes"}
NEEDED = ("start", "end", "event_type", "location")
TRACKED = ("start", "end", "event_type", "location", "volume", "recovered", "notes")

# the table's Event Type wording -> kinds (the page's own definitions); each kind is a sewage discharge (sso)
EVENT_KINDS = (
    ("facility_spill", re.compile(r"\bspill\s+event", re.I),
     "a Spill Event: a release of waste from USIBWC's facility (the plant, its pump stations or canyon collectors)"),
    ("canyon_collector_flow", re.compile(r"canyon\s*collector\s*transboundary\s*flow", re.I),
     "a dry weather Canyon Collector Transboundary Flow Event: a dry-weather flow from Mexico in a collector canyon "
     "not captured for treatment"),
    ("river_transboundary_flow", re.compile(r"tijuana\s+river\s+transboundary\s+flow", re.I),
     "a Tijuana River Transboundary Flow Event: a flow from Mexico across the border in the Tijuana River, wet or dry "
     "weather"),
)
MATERIAL = {
    "facility_spill": "waste released from USIBWC's facility (the table's Spill Event)",
    "canyon_collector_flow": "dry weather flow from Mexico not captured by the canyon collector",
    "river_transboundary_flow": "wet and dry weather flows from Mexico in the Tijuana River",
}
TYPE_BASIS = ("The table's Event Type is read by a fixed rule on its wording, each kind as a sewage discharge (sso): "
              "the page describes the canyon collectors as a failsafe to collect and divert untreated sewage and other "
              "dry weather transboundary flows, and says flows they do not capture can enter waters of the US and "
              "of California")

# the waters a discharge location can name: the river and the five collector canyons the page lists
WATER_NAMES = (
    ("Tijuana River", re.compile(r"\btijuana\s+river\b", re.I), ("tijuana river",)),
    ("Smuggler's Gulch", re.compile(r"\bsmuggler['’]?s?\s+gulch\b", re.I), ("smugglers gulch", "smuggler gulch")),
    ("Goat Canyon", re.compile(r"\bgoat\s+canyon\b", re.I), ("goat canyon",)),
    ("Stewart's Drain", re.compile(r"\bstewart['’]?s?\s+drain\b", re.I), ("stewarts drain", "stewart drain")),
    ("Silva Drain", re.compile(r"\bsilva\s+drain\b", re.I), ("silva drain",)),
    ("Canyon del Sol", re.compile(r"\b(?:canyon\s+del\s+sol|del\s+sol\s+canyon)\b", re.I),
     ("canyon del sol", "del sol canyon")),
)
# the Tijuana River valley in the US (west, south, east, north): a water record of one of those names is used only
# when its outline's box meets this one, so a same-named water elsewhere in California never takes these reports
VALLEY_BOX = (-117.16, 32.50, -116.95, 32.62)

DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*$")
# an end cell that says the event goes on: it starts with "Ongoing" ("Ongoing intermittent flows"); "No longer
# ongoing" or any other wording is not read as ongoing (review 2026-11-15 P1-6)
# ("Ongoing (has not stopped)" is ongoing: a stop word after "not" or "never" does not count; second review P1)
ONGOING = re.compile(r"^\s*ongoing\b(?!.*\bno\s+longer\b)(?!.*(?<!not )(?<!never )\b(?:ended|stopped|ceased)\b)",
                     re.I)
NONE_TEXT = re.compile(r"^\s*(none|n/?a|-+|0|unknown|tbd)?\s*\.?\s*$", re.I)
NONE_WORD = re.compile(r"^\s*(none|0)\s*\.?\s*(gallons?)?\s*$", re.I)
# the whole cell must be one plain amount ("302,000 gallons", "1.61 million gallons", ".5 million gallons"); a range,
# a bound ("<1,000"), a sign, a rate ("per day", "/day") or anything else is kept as text with no number (review
# 2026-11-15 P1-5)
VOLUME = re.compile(r"^\s*(?:approximately\s+|approx\.?\s+|about\s+|~\s*)?(\d[\d,]*(?:\.\d+)?|\.\d+)\s*"
                    r"(billion|million|thousand)?\s*(?:gallons?|gal\.?)\s*\.?\s*$", re.I)
SCALE = {"billion": 1e9, "million": 1e6, "thousand": 1e3, None: 1}
REPORTED_ON = re.compile(r"\breported\b[^.]{0,60}?\bon\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)
PAGE_UPDATED = re.compile(r"Page\s+last\s+updated\s*(?:<!--.*?-->\s*)*(\d{1,2}/\d{1,2}/\d{2,4})", re.I | re.S)


# ---------------------------------------------------------------- reading the page

class _Tables(HTMLParser):
    """Every table's rows as lists of cell texts (whitespace collapsed)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[list[list[str]]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._stack[-1].append([])
        elif tag in ("td", "th") and self._stack:
            if not self._stack[-1]:
                self._stack[-1].append([])
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._stack:
            self._stack[-1][-1].append(clean("".join(self._cell)))
            self._cell = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def clean(v) -> str:
    return " ".join(html.unescape(str(v if v is not None else "")).replace("\xa0", " ").split())


def read_rows(text: str) -> list[dict]:
    """The table's rows under short keys. Raises when the table or a needed column is missing (a changed page must not
    pass silently)."""
    p = _Tables()
    p.feed(text)
    for t in p.tables:
        rows = [r for r in t if any(c for c in r)]
        if not rows:
            continue
        header = [c.lower().rstrip(":") for c in rows[0]]
        idx = {COLUMNS[h]: i for i, h in enumerate(header) if h in COLUMNS}
        if all(k in idx for k in NEEDED):
            out = []
            for cells in rows[1:]:
                r = {k: (cells[i] if i < len(cells) else "") for k, i in idx.items()}
                if any(r.values()):
                    out.append(r)
            return out
    raise ValueError("the page holds no table with the columns Start Date, End Date, Event Type and Discharge Location")


def page_updated(text: str) -> str | None:
    m = PAGE_UPDATED.search(text)
    d = parse_date(m.group(1)) if m else None
    return d.isoformat() if d else None


# ---------------------------------------------------------------- helpers

def parse_date(v) -> date | None:
    m = DATE.match(clean(v))
    if not m:
        return None
    mo, d, y = (int(x) for x in m.groups())
    y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def gallons(v) -> int | None:
    s = clean(v)
    if not s or NONE_TEXT.match(s):
        return None
    m = VOLUME.match(s)
    if not m or (m.group(1).count(",") and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", m.group(1))):
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return int(round(n * SCALE[(m.group(2) or "").lower() or None]))


def kinds_of(event_type: str) -> list[str]:
    return [k for k, rx, _ in EVENT_KINDS if rx.search(event_type or "")]


def water_name(location: str) -> str | None:
    for name, rx, _ in WATER_NAMES:
        if rx.search(location or ""):
            return name
    return None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("'", "").replace("’", "")).strip("-") or "row"


def _norm(s) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower().replace("'", "").replace("’", "")).split())


def _meets_valley(bbox) -> bool:
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
        return False
    w, s, e, n = VALLEY_BOX
    return not (bbox[2] < w or bbox[0] > e or bbox[3] < s or bbox[1] > n)


def valley_waters(waters: dict | None = None) -> dict[str, dict[str, list[str]]]:
    """{water name (WATER_NAMES): {"slugs": [...], "elsewhere": [...]}}: "slugs" are the California water records of
    that name (record name or alias) whose box meets VALLEY_BOX; "elsewhere" are the records the status build's own
    name match (build.status.Resolver.by_name) gives for the name that are not among them, i.e. a same-named water
    elsewhere in California. waters None loads every water file (build.status.load_waters)."""
    from build import status
    if waters is None:
        waters = status.load_waters()
    ca = {s: w for s, w in waters.items() if isinstance(w, dict) and w.get("state") == "CA"}
    out: dict[str, dict[str, list[str]]] = {name: {"slugs": [], "elsewhere": []} for name, _, _ in WATER_NAMES}
    for slug, w in ca.items():
        if not _meets_valley(w.get("bbox")):
            continue
        names = {_norm(w.get("name"))} | {_norm(a) for a in (w.get("aliases") or [])}
        for name, _, keys in WATER_NAMES:
            if names & set(keys):
                out[name]["slugs"].append(slug)
    resolver = status.Resolver(ca, [], placement_rules={})
    for name, _, _ in WATER_NAMES:
        # every record the status build's name match could pick for the name (an ambiguous match the build settles by
        # the operator's towns included: review 2026-11-15 P1-4): the names, aliases and stems it holds, as by_name
        # reads them
        t = f" {status.norm_name(name)} "
        cand = set()
        for (st, n), slugs in resolver.names.items():
            if st == "CA" and f" {n} " in t:
                cand.update(slugs)
        for table in (resolver.exact, resolver.stems):
            cand.update(table.get(("CA", status.norm_name(name))) or [])
        got, _, _ = resolver.by_name(name, "CA", None, None, {"raw": {}})
        cand.update(got)
        out[name]["elsewhere"] = sorted(s for s in cand if s not in out[name]["slugs"])
        out[name]["slugs"].sort()
    return {k: v for k, v in out.items() if v["slugs"] or v["elsewhere"]}


REMOVED_MARK = re.compile(r"\\\[(?:[a-z]+\\ )+removed\\\]")


def same_text(stored, current: str) -> bool:
    """Whether a stored value (after the export's final redaction, which may have replaced a name with "[name
    removed]") is the current one: each removal mark in the stored value stands for any text (second review P2)."""
    stored = clean(stored)
    if stored == current:
        return True
    if "removed]" not in stored:
        return False
    pat = REMOVED_MARK.sub(".+?", re.escape(stored))
    return re.fullmatch(pat, current, re.S) is not None


def record_ids(rows: list[dict]) -> list[str]:
    """The row's start date, the water its location names (a fixed name, or "site"), and six hex digits of a hash of
    the location as published: no free text of the table reaches an identifier (review 2026-11-15 P1-2). A second row
    with the same start and location gets "-n2" (a suffix no hash can end in, so it never meets another row's key)."""
    seen: Counter = Counter()
    out = []
    for r in rows:
        d = parse_date(r.get("start"))
        # the hash is of the location as scrubbed (a house number or name is never recoverable from the key: second
        # review P1), ten hex digits (40 bits)
        loc = strip_house_numbers(scrub_text(clean(r.get("location")))).lower()
        base = (f"{d.isoformat() if d else 'no-start'}-{slugify(water_name(loc) or 'site')}-"
                f"{hashlib.sha256(loc.encode()).hexdigest()[:10]}")
        seen[base] += 1
        out.append(base if seen[base] == 1 else f"{base}-n{seen[base]}")
    return out


# ---------------------------------------------------------------- records

def build_record(row: dict, rid: str, fetched_at: str, prev: dict | None, placed: dict) -> dict:
    a = {k: clean(row.get(k)) for k in COLUMNS.values()}
    for k in ("location", "notes"):        # typed text: a name, a mailbox, a phone or a house number never kept
        if a.get(k):
            a[k] = strip_house_numbers(scrub_text(a[k]))
    base = dict(source_id=SOURCE_ID, source_record_id=rid, fetched_at=fetched_at, source_url=PAGE_URL)
    p_raw = (prev or {}).get("raw") or {}
    raw = {"row": a, "time_zone": TZ}
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or fetched_at
    revs = list(p_raw.get("_revisions") or [])
    p_row = p_raw.get("row") or {}
    if p_row and any(not same_text(p_row.get(k), a.get(k, "")) for k in TRACKED):
        revs.append({"seen_until": (prev or {}).get("fetched_at"), **{k: p_row.get(k) for k in TRACKED}})
    if revs:
        raw["_revisions"] = revs[-10:]
    try:
        rec = _record(a, base, raw, fetched_at, placed)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")
    mark_ongoing_listing(rec, prev, fetched_at)
    return rec


def mark_ongoing_listing(rec: dict, prev: dict | None, fetched_at: str) -> None:
    """raw._ongoing_listing {"last_listed_at", "unmarked_since"} on a row the table still shows whose end cell no longer
    reads ongoing and gives no end (status unknown, no end, no published end set aside), when an earlier read listed it
    as ongoing: last_listed_at is the last read that listed it as ongoing (that record's fetched_at), unmarked_since the
    first read that did not. Set once at the change and carried unchanged on later reads (not a tracked field, so no
    revision); a row that reads ongoing again, or gets an end, carries none. The status build's listed-ongoing rule
    (build/status.py listed_ongoing_intervals) counts its fallback from last_listed_at."""
    raw = rec.setdefault("raw", {})
    raw.pop("_ongoing_listing", None)
    if rec.get("status") != "unknown" or rec.get("ended_at") or raw.get("_end_not_used"):
        return
    p_raw = (prev or {}).get("raw") or {}
    if isinstance(p_raw.get("_ongoing_listing"), dict) and (prev or {}).get("status") == "unknown":
        raw["_ongoing_listing"] = dict(p_raw["_ongoing_listing"])
    elif (prev or {}).get("status") == "ongoing" and not (prev or {}).get("ended_at") and prev.get("fetched_at"):
        raw["_ongoing_listing"] = {"last_listed_at": prev["fetched_at"], "unmarked_since": fetched_at}


def _record(a: dict, base: dict, raw: dict, fetched_at: str, placed: dict) -> dict:
    problems = []
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).date()

    # event type
    kinds = kinds_of(a.get("event_type", ""))
    raw["event_kinds"] = kinds
    if kinds:
        etype = "sso"
        raw["_event_type_basis"] = (f"{TYPE_BASIS}; the table's type '{a.get('event_type')}' reads as "
                                    + " and ".join(next(t for k, _, t in EVENT_KINDS if k == x) for x in kinds))
    else:
        etype = "unknown"
        problems.append(f"event type not read: {a.get('event_type')!r}")
    if any(k.endswith("_flow") for k in kinds):
        raw["transboundary"] = True

    # times
    start = parse_date(a.get("start"))
    end = parse_date(a.get("end"))
    end_text = a.get("end", "")
    if a.get("start") and start is None:
        problems.append(f"start not read: {a.get('start')!r}")
    if start is not None and start > fetched + timedelta(days=1):
        raw["_start_not_used"] = (f"the start as published ({start.isoformat()}) lies after the page was read, most "
                                  "likely a typing error; the report is kept with no start")
        start = None
    implausible = None
    if end is not None and start is not None and end < start:
        implausible = "is before the start"
    elif end is not None and end > fetched + timedelta(days=1):
        implausible = "lies after the page was read"
    if implausible:
        # an end before the start stays in ended_at (the status build's shared rule draws no window from it); an end
        # after the read stays only in raw: the shared rule allows ends up to 31 days ahead, so in ended_at it would
        # draw a discharge window to a day that has not come (review 2026-11-15 P1-1)
        status = "unknown"
        ended_at = end.isoformat() if implausible == "is before the start" else None
        raw["_end_as_published"] = end.isoformat()
        raw["_end_not_used"] = f"the end as published ({end.isoformat()}) {implausible}"
        raw["_end_basis"] = ("the table gives an end that " + implausible + ", most likely a typing error: it is kept "
                             "as published and not used, so the event has no confirmed end (the site's rule for an "
                             "implausible end, unresolved.implausible_end)")
    elif end is not None:
        status, ended_at = "ended", end.isoformat()
        raw["ended_at_precision"] = "day"
    elif ONGOING.search(end_text):
        status, ended_at = "ongoing", None
        raw["_end_basis"] = f"the table's end reads '{end_text}': ongoing, no end given"
    else:
        status, ended_at = "unknown", None
        if end_text:
            problems.append(f"end not read: {end_text!r}")
        raw["_end_basis"] = ("the table gives no end" if not end_text else
                             f"the table's end reads '{end_text}', not a date: no end is used")
    raw["_time_basis"] = "dates as the table gives them, in Pacific time; the table gives no times of day"
    raw["_reported_basis"] = ("the table gives no report or posting date for the row; the page says USIBWC files "
                              "preliminary Spill Event and canyon collector reports within three days of the event and "
                              "monthly reports for Tijuana River flows")
    m = REPORTED_ON.search(a.get("notes", ""))
    updated = parse_date(m.group(1)) if m else None
    if updated:
        raw["_source_updated_basis"] = f"the row's notes: '{m.group(0)}'"

    # operator
    if "facility_spill" in kinds:
        did, dname, permit = DISCHARGER_ID, DISCHARGER_NAME, PERMIT
    else:
        did = dname = permit = None
        raw["_discharger_basis"] = ("a transboundary flow from Mexico that the table does not class as a Spill Event of "
                                    "USIBWC's facility: no operator is joined")
    raw["reported_by"] = REPORTED_BY

    # water (no point: the table gives none)
    water = water_name(a.get("location", ""))
    found = (placed.get(water) or {}) if water else {}
    slugs = list(found.get("slugs") or [])
    raw["_placement"] = "named_water_only"
    raw["named_water"] = water
    text = water
    if water and slugs:
        raw["_water_basis"] = (f"the discharge location '{a.get('location')}' names {water}; placed on the water "
                               "record of that name in the Tijuana River valley")
    elif water and found.get("elsewhere"):
        text = None             # the status build's name match would take a same-named water elsewhere in California
        raw["_water_basis"] = (f"the discharge location '{a.get('location')}' names {water}; no water record of that "
                               "name in the Tijuana River valley yet, and a water of the same name elsewhere in "
                               "California is not this one, so the name is not given as the water and the report is "
                               "not placed")
    elif water:
        raw["_water_basis"] = (f"the discharge location '{a.get('location')}' names {water}; no water record of that "
                               "name in the Tijuana River valley yet, so the report is not placed")
    else:
        raw["_water_basis"] = (f"the discharge location '{a.get('location')}' names no water; the table gives no "
                               "receiving water or point, so the report is not placed")

    # volume
    vol = gallons(a.get("volume"))
    rec = gallons(a.get("recovered"))
    rtext = a.get("recovered", "")
    said_none = bool(NONE_WORD.match(rtext))                  # the table's "None": nothing was recovered
    raw["volume_recovered_gal"] = rec if rec is not None else (0 if said_none else None)
    parts = []
    if a.get("volume") and not NONE_TEXT.match(a["volume"]):
        parts.append(f"{a['volume']} (approximate discharge volume)")
    if rtext and not (NONE_TEXT.match(rtext) and not said_none):
        parts.append("none recovered" if said_none else f"{rtext} recovered")
    if a.get("volume") and vol is None and not NONE_TEXT.match(a["volume"]):
        problems.append(f"volume not read: {a.get('volume')!r}")
    if rtext and rec is None and not said_none and not NONE_TEXT.match(rtext):
        problems.append(f"volume recovered not read: {rtext!r}")
    material = "; ".join(MATERIAL[k] for k in kinds) or None
    return event(
        **base, event_type=etype, status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=permit,
        outfall_id=None, outfall_name=a.get("location") or None,
        waterbody_text=text, water_slugs=slugs, water_match="name" if slugs else "none",
        lat=None, lon=None, coord_source=None, coord_precision_m=None,
        started_at=start.isoformat() if start else None, ended_at=ended_at,
        time_precision="day" if (start or ended_at) else None,
        reported_at=None, published_at=None, source_updated_at=updated.isoformat() if updated else None,
        material=material, volume_gal=vol, volume_text="; ".join(parts) or None,
        estimate_flag="estimated" if vol is not None else "unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def build(rows: list[dict], fetched_at: str, prev_records: list[dict], placed: dict | None = None
          ) -> tuple[list[dict], dict]:
    """rows: the table's rows (short keys). Returns (records, stats); earlier records of rows no longer in the table
    are kept and marked."""
    placed = valley_waters() if placed is None else placed
    prev = {r["event_id"]: r for r in prev_records}
    records, seen = [], set()
    for row, rid in zip(rows, record_ids(rows)):
        eid = f"{SOURCE_ID}:{rid}"
        seen.add(eid)
        records.append(build_record(row, rid, fetched_at, prev.get(eid), placed))
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        raw = r.setdefault("raw", {})
        raw["_missing_from_table_since"] = raw.get("_missing_from_table_since") or fetched_at
        records.append(r)
        kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    unplaced = Counter(((r.get("raw") or {}).get("named_water") or "(names no water)") for r in records
                       if not r.get("water_slugs"))
    stats = {"rows_in_table": len(rows), "records": len(records), "kept_missing_from_table": kept,
             "by_status": dict(Counter(r["status"] for r in records)),
             "by_kind": dict(Counter("+".join((r.get("raw") or {}).get("event_kinds") or ["unread"]) for r in records)),
             "by_year": dict(sorted(Counter((r.get("started_at") or "none")[:4] for r in records).items())),
             "placed": sum(1 for r in records if r.get("water_slugs")),
             "unplaced": sum(1 for r in records if not r.get("water_slugs")),
             "unplaced_by_water": dict(unplaced),
             "valley_waters": placed,
             "with_volume": sum(1 for r in records if r.get("volume_gal") is not None)}
    return records, stats


# ---------------------------------------------------------------- fetching and main

def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved page instead of the Board's")
    ap.add_argument("--force", action="store_true", help=f"read the page even if read in the last {MIN_HOURS} hours")
    ap.add_argument("--state", help="state file (default data/build/ca-sd-tijuana-state.json)")
    ap.add_argument("--out", help="events file (default data/build/events/ca-sd-regional-board-ibwc-spills.json)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state_path = Path(args.state) if args.state else STATE_FILE
    if args.file and not args.state:
        state_path = Path(args.file).with_suffix(".state.json")    # a replay never touches the run's state
    out = Path(args.out) if args.out else EVENTS_DIR / f"{SOURCE_ID}.json"
    state = read_json(state_path, {}) or {}
    prev_doc = read_json(out, {}) or {}
    prev = prev_doc.get("records", [])
    # one request at most every MIN_HOURS hours, a failed one included (review 2026-11-15 P2-8): after a good read the
    # last records are written again as healthy; after a failed one the events file is left as it is (ok false, the
    # records kept) until the next request
    last = state.get("attempted_at") or state.get("fetched_at")
    if not args.file and not args.force and last:
        age = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")) - \
            datetime.fromisoformat(last.replace("Z", "+00:00"))
        if age < timedelta(hours=MIN_HOURS):
            if prev and prev_doc.get("ok") is not False:
                meta = {**(prev_doc.get("meta") or {}), "checked_at": fetched_at,
                        "not_read_this_run": f"the page is read at most every {MIN_HOURS} hours; last read {last}"}
                write_events(SOURCE_ID, prev, ok=True, error=None, meta=meta, path=out)
                print(f"{SOURCE_ID}: read {last}; {len(prev)} records kept")
                return 0
            if prev_doc:
                print(f"{SOURCE_ID}: the last request ({last}) failed; next request {MIN_HOURS} hours after it")
                return 0
    if not args.file:
        state["attempted_at"] = fetched_at
    try:
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8", errors="replace")
        else:
            r = requests.get(PAGE_URL, headers=HEADERS, timeout=(20, 60))
            r.raise_for_status()
            text = r.content.decode("utf-8", errors="replace")
        rows = read_rows(text)
        good = int(state.get("last_rows") or 0)
        if not rows or len(rows) * 2 < good:
            raise RuntimeError(f"{len(rows)} rows in the table (last good read {good}): read as an outage")
    except Exception as e:  # noqa: BLE001
        write_json(state_path, state)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", path=out)
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    raw_path = state.get("raw_path")
    if not args.file:
        sha = hashlib.sha256(text.encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, text, "html").relative_to(ROOT))
            state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
    records, stats = build(rows, fetched_at, prev)
    records = redact.redact_events(records)
    state.update(fetched_at=fetched_at, last_rows=len(rows))
    write_json(state_path, state)
    meta = {**stats, "page": PAGE_URL, "page_last_updated": page_updated(text), "raw_path": raw_path,
            "credit": CREDIT, "registry_ids": [SOURCE_ID],
            "time_basis": "dates as the table gives them (Pacific); no times of day",
            "shown_note": ("Every row of the table is a record: USIBWC's Spill Events and the transboundary flows "
                           "from Mexico it reported since July 1, 2024. The table gives no coordinates; a report is "
                           "placed only on a water record its discharge location names. Earlier events are in the "
                           "San Diego Water Board's Executive Officer's Reports, not read here.")}
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta, path=out)
    print(f"{SOURCE_ID}: {stats['rows_in_table']} rows, {len(records)} records; status {stats['by_status']}; "
          f"placed {stats['placed']}, unplaced {stats['unplaced_by_water']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
