"""U.S. EPA BEACON 2.0 Beach Actions: the states' beach advisories and closures as filed with EPA, history only
-> data/build/events/fed-beacon-beach-actions.json

Source (registry data/sources/fed-beacon-beach-actions.yaml)
  BEACON 2.0 (https://beacon.epa.gov/ords/beacon2/r/beacon_apex/beacon2/), EPA's public archive of the beach
  notification data each state, territory and tribe files under the BEACH Act (Clean Water Act section 406) and the
  2014 National Beach Guidance (performance criteria 4 and 8). States file after the season: submissions are due by
  January 31 of the next year, so every window is past by the time it appears. Credit "U.S. EPA BEACON 2.0, as
  reported by each state's beach program"; EPA public domain.
  Read: the report builder's Beach Actions report (one row per action, or per group of actions at one beach with one
  window: Action ID then lists every id) and its detailed report (one row per action id and reason, with the state's
  reason, indicator and source comments; dates without times). A session is set up per year as the site's own pages
  do (open_session: the report page for the session id, then four application-process posts that clear the location
  lists, choose the national region, build the filters and set the calendar year), and each report is exported as
  CSV (pull_report: the report page once, then ?request=CSV). The pipeline's named client (common.HEADERS), about one
  second between requests: nine requests a year.
Cadence (MIN_HOURS): a full pull of the current and the previous calendar year (Eastern time) at most once every 20
  hours; between pulls the records are written again from the saved rows (data/build/fed-beacon-beach-actions-state.json)
  without the network, so the links to the state feeds follow their files every hour. The events file's header keeps
  the time of the last pull (last_ok_at). --backfill FROM_YEAR pulls the years from FROM_YEAR to the one before the
  previous year by hand (not in the refresh); they stay in the saved rows. A failed pull keeps the previous records and
  rows (ok false, the error a fixed reason and the exception's class).
Scope: the fifty states, the District of Columbia and Puerto Rico (IN_SCOPE). American Samoa, Guam, the Northern
  Mariana Islands, the Virgin Islands and the four tribal programs (BR, GP, MK, ST) are counted in meta
  (out_of_scope), not written.
Records (one per Beach Actions row; event_id fed-beacon-beach-actions:<the row's lowest action id>-<the action type's
  code> (TYPE_CODE: closure, advisory, rain, posting), so an id never depends on other rows)
  - event_type: Closure -> beach_closure; Contamination Advisory, Rain Advisory and Posting -> beach_advisory.
  - started_at, ended_at: the action's start and end in the beach's local time (beach_zone: zones.zone_for by the
    state and the beach's point, and Michigan's four Central-time counties by BEACON's county; raw.time_zone). A time of exactly 12:00 AM is a date: precision day, for the start
    (time_precision) and the end (raw.ended_at_precision) apart; any other time is to the minute. status
    advisory_lifted when the end (the end of its local day for a date) is at or before the pull, else advisory_active
    (the end as the state filed it). raw.state is the jurisdiction (the state the status build counts it under).
  - published_at, reported_at and source_updated_at stay empty (BEACON gives no publication time); fetched_at is the
    pull that read the row; raw._first_seen_at the first pull that listed any of its action ids (kept for good in the
    saved state's first_seen).
  - raw: the beach id, name, county, waterbody name and type, tier, station ids, action ids, the action type, the
    reason, indicator and possible-source codes (with our plain words for each), the duration in days, and from the
    detailed report the state's comments for the row's action ids, scrubbed as the beach comments of other feeds are
    (oh_odh_beachguard.clean_comment).
  - Place: the beach's start point from the EPA beach registry (data/beaches-epa.json, scripts/build_epa_beach_registry.py;
    coord_source source, raw.point_basis), else its end point; waterbody_text BEACON's waterbody name. The status build's
    matcher places it by that name and the point. A beach with no registry row or no point stays a record, unplaced,
    and is counted (meta.no_point).
  - History only (data/rules.json unresolved.history_only, build/status.py): no record of this source colours the map
    now or starts our caution; its window is drawn in a water's history up to the first pull that read it.
Copies, not second reports (link_copies; the ingester's own duplicate_of, as ingest/al_jefferson_county_soa.py
  link_adem): a row that repeats a record a state feed already carries is marked duplicate_of that record, so the
  status build counts the state's record once. A state record is a candidate when its source is a beach source (an
  entry of rules.json beach_reason, this one aside), its type is a beach closure, beach advisory or rain advisory, it
  is no one's duplicate, its file is not withheld from the public export (meta.distribution_discouraged: a link to it
  would hide the action from the public site) and its start is within a day of the action's (each in its own local
  day) and of the same kind (COMPATIBLE: a closure repeats a closure, an advisory an advisory or a rain advisory). By
  EPA beach id where the feed keeps it (BY_ID_PATHS); elsewhere by the beach's point (within LINK_M of the
  beach's line from its start to its end point) or by the same beach name in the same state, never when the two name
  different waters (build/status.py waters_differ). Each state record takes at most one copy, the closest first;
  raw.copy_of and raw._duplicate_basis say how. meta.links counts them. The links are made again after every feed
  (ingest/fed_beacon_beach_link.py, Makefile INGEST_SNAPSHOTS: this module runs before most state feeds) and on a
  failed pull (the saved rows written again, health false), so a copy never hides behind a record that has gone.
Checks (check_year): every row of both reports is the requested year, and the detailed report covers at least 95% of
  the main report's action ids (100% in 2014 to 2026); a year whose rows we hold, or a backfill year, may not come
  back empty; both refresh years empty is a failed pull. A backfill naming no year exits 2 and writes nothing.
Meta: counts by state and year, the newest action per state (a source-health signal: when each state last filed),
  the out-of-scope count, the private-owner and historical beaches' actions, the links and the rows with no point.
Run from pipeline/: python -m ingest.fed_beacon_beach_actions [--force] [--backfill FROM_YEAR]
                    [--from-dir DIR --fetched-at ISO] (saved CSVs named beach-actions_<year>.csv and
                    beach-actions-detail_<year>.csv; no network)
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import zones
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, write_events, write_json)

SOURCE_ID = "fed-beacon-beach-actions"
BASE = "https://beacon.epa.gov/ords/beacon2"
APP = f"{BASE}/r/beacon_apex/beacon2"
REPORT_PAGE = f"{APP}/report-page-content"
SHOW = f"{BASE}/wwv_flow.show"
MAIN, DETAIL = "beach-actions", "beach-actions-detail"
BEACH_PAGE = f"{APP}/beach-profile-details?beach_id={{}}"
APP_ID, NATIONAL_REGION = "132", "11"
STATE_FILE = BUILD_DIR / f"{SOURCE_ID}-state.json"
REGISTRY_FILE = DATA_DIR / "beaches-epa.json"
TZ_EAST = ZoneInfo("America/New_York")
MIN_HOURS = 20
PAUSE_S = 1.0
LINK_M = 300.0
LINK_DAYS = 1
CREDIT = "U.S. EPA BEACON 2.0, as reported by each state's beach program"
STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH "
          "OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
IN_SCOPE = frozenset(STATES) | {"DC", "PR"}
KNOWN_OUT_OF_SCOPE = frozenset({"AS", "GU", "MP", "VI", "BR", "GP", "MK", "ST"})
MAIN_COLUMNS = ("Jurisdiction", "Year", "Beach ID", "BeachName", "County", "WaterbodyName", "WaterbodyType", "Tier",
                "Station ID", "Action ID", "ActionStart Date", "ActionEnd Date", "Action Type", "ActionReasons",
                "ActionIndicator", "ActionPossible Source", "ActionDurationDays")
DETAIL_COLUMNS = ("Jurisdiction", "Year", "Beach Id", "Activity ID", "Action Type", "Action StartDate",
                  "Action EndDate", "Action Reasons", "Action ReasonsComment", "Action Indicator",
                  "Action IndicatorComment", "Action Possible Source", "Action PossibleSourceComment")
TYPE_CODE = {"Closure": "closure", "Contamination Advisory": "advisory", "Rain Advisory": "rain", "Posting": "posting"}
EVENT_TYPE = {"Closure": "beach_closure", "Contamination Advisory": "beach_advisory", "Rain Advisory": "beach_advisory",
              "Posting": "beach_advisory"}
# EPA's codes in plain words (ours, for a reader; the codes stay as filed in raw.reasons and the others)
REASON_WORDS = {"ELEV_BACT": "bacteria above the state's standard", "RAINFALL": "rainfall",
                "MODEL": "a predictive model of bacteria levels", "SEWAGE": "sewage",
                "POLICY": "issued by policy without a sample (preemptive)", "OTHER": "another reason"}
INDICATOR_WORDS = {"ENTERO": "enterococci", "ECOLI": "E. coli", "FECAL_COL": "fecal coliform",
                   "TOTAL_COL": "total coliform", "RATIO": "fecal-to-total coliform ratio",
                   "PREEMPT": "preemptive (no sample)", "OTHER": "another indicator"}
SOURCE_WORDS = {"UNKNOWN": "unknown", "STORM": "stormwater", "RUNOFF": "runoff", "CSO": "combined sewer overflow",
                "SSO": "sanitary sewer overflow", "POTW": "sewage treatment plant", "SEWER_LINE": "sewer line",
                "SEPTIC": "septic systems", "WILDLIFE": "wildlife", "ALGAE": "algae", "BOAT": "boats",
                "AGRICULTURAL": "agriculture", "CAFO": "animal feeding operation", "OTHER": "another source"}
# the agency each state's BEACON contact page names for its beach program
AGENCY = {
    "AK": "Alaska Department of Environmental Conservation", "AL": "Alabama Department of Environmental Management",
    "CA": "California State Water Resources Control Board", "CT": "Connecticut Department of Public Health",
    "DE": "Delaware Department of Natural Resources and Environmental Control",
    "FL": "Florida Department of Health", "GA": "Georgia Department of Natural Resources",
    "HI": "Hawaii Department of Health", "IL": "Illinois Department of Public Health",
    "IN": "Indiana Department of Environmental Management", "LA": "Louisiana Department of Health",
    "MA": "Massachusetts Department of Public Health", "MD": "Maryland Department of the Environment",
    "ME": "Maine Department of Environmental Protection",
    "MI": "Michigan Department of Environment, Great Lakes, and Energy", "MN": "Minnesota Department of Health",
    "MS": "Mississippi Department of Environmental Quality",
    "NC": "North Carolina Department of Environmental Quality", "NH": "New Hampshire Department of Environmental Services",
    "NJ": "New Jersey Department of Environmental Protection", "NY": "New York State Department of Health",
    "OH": "Ohio Department of Health", "OR": "Oregon Health Authority", "PA": "Erie County Department of Health",
    "PR": "Puerto Rico Department of Natural and Environmental Resources", "RI": "Rhode Island Department of Health",
    "SC": "South Carolina Department of Environmental Services", "TX": "Texas General Land Office",
    "VA": "Virginia Department of Health", "WA": "Washington Department of Ecology",
    "WI": "Wisconsin Department of Natural Resources",
}
# the state feeds that keep EPA's beach id, and where (raw paths)
BY_ID_PATHS = {"al-adem-beach-monitoring": "beacon_id", "ms-mdeq-beach-monitoring": "beacon_id",
               "fl-doh-beaches": "epa_beach_id", "me-healthy-beaches": "epa_beach_id", "nj-beaches": "epa_beach_id",
               "ga-dnr-beaches": "beach.beachId", "nc-rwq-advisories": "EPA_ID", "nh-des-swimming": "EPA_ID"}
LINK_TYPES = frozenset({"beach_closure", "beach_advisory", "rain_advisory"})
# a BEACON closure repeats a state's closure, an advisory a state's advisory or rain advisory; never across them
COMPATIBLE = {"beach_closure": frozenset({"beach_closure"}),
              "beach_advisory": frozenset({"beach_advisory", "rain_advisory"})}
# Michigan's Central-time counties (49 CFR 71.5: the four Upper Peninsula counties bordering Wisconsin); zones.zone_for
# reads Michigan as Eastern
MI_CENTRAL_COUNTIES = frozenset({"GOGEBIC", "IRON", "DICKINSON", "MENOMINEE"})
NOT_LINKED_SOURCES = frozenset({SOURCE_ID, "notification-pages"})


class PullError(Exception):
    """A BEACON answer that is not the report it should be (no session id, not CSV, a changed header)."""


# ---------------------------------------------------------------- reading BEACON

def open_session(sess, year: int, sleep=time.sleep, pause: float = PAUSE_S) -> str:
    """The session id of a report-builder session set to the national region and `year` (module docstring)."""
    r = sess.get(REPORT_PAGE, timeout=(20, 90))
    r.raise_for_status()
    m = re.search(r'APP_SESSION:\s*"(\d+)"', r.text) or re.search(r"[?&]session=(\d+)", r.url or "")
    if not m:
        raise PullError("the report page gave no session id")
    sid = m.group(1)
    headers = {"X-Requested-With": "XMLHttpRequest", "Referer": REPORT_PAGE}
    url = f"{SHOW}?p_context=beacon2/report-page-content/{sid}"
    base = [("p_instance", sid), ("p_flow_id", APP_ID), ("p_flow_step_id", "0")]

    def process(name: str, args: list[tuple[str, str]]):
        data = [("p_request", f"APPLICATION_PROCESS={name}"), *base]
        for k, v in args:
            data += [("p_arg_names", k), ("p_arg_values", v)]
        sleep(pause)
        resp = sess.post(url, data=data, headers=headers, timeout=(20, 90))
        resp.raise_for_status()

    process("clearLocationLists", [])
    process("setAdditionalSearchVariables", [("UI_SELECTED_AREAS", ""), ("UI_EPA_REGION", NATIONAL_REGION),
                                             ("UI_GREAT_WATERBODY", "")])
    process("buildFilters", [])
    process("setAdditionalSearchVariables", [("F101_CALENDAR_YEAR", str(year)), ("F101_START_DATE", ""),
                                             ("F101_END_DATE", ""), ("F101_MISC_DATE", "")])
    return sid


def pull_report(sess, sid: str, report: str, columns, sleep=time.sleep, pause: float = PAUSE_S) -> str:
    """One report of the session as CSV text, its header checked against `columns`."""
    sleep(pause)
    r = sess.get(f"{APP}/{report}", params={"clear": "Y", "session": sid}, timeout=(20, 200))
    r.raise_for_status()
    sleep(pause)
    r = sess.get(f"{APP}/{report}", params={"session": sid, "request": "CSV"}, timeout=(20, 600))
    r.raise_for_status()
    ctype = (r.headers.get("Content-Type") or "").lower()
    text = r.content.decode("utf-8-sig", errors="replace")
    if "csv" not in ctype and not text.startswith("Jurisdiction"):
        raise PullError(f"{report}: the answer is not CSV")
    header = next(csv.reader(io.StringIO(text)), [])
    missing = [c for c in columns if c not in header]
    if missing:
        raise PullError(f"{report}: the CSV header lacks {len(missing)} known column(s)")
    return text


def pull_year(sess, year: int, sleep=time.sleep) -> tuple[str, str]:
    """(main CSV, detailed CSV) of one calendar year, one session."""
    sid = open_session(sess, year, sleep)
    return (pull_report(sess, sid, MAIN, MAIN_COLUMNS, sleep), pull_report(sess, sid, DETAIL, DETAIL_COLUMNS, sleep))


def new_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------- parsing

def rows_of(text: str) -> list[dict]:
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def codes(v: str) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def when(text: str, tz: ZoneInfo) -> tuple[str | None, str | None]:
    """'10-SEP-2025 12:00AM' -> ('2025-09-10T00:00:00-05:00', 'day'); '17-JUL-2025 12:30PM' -> (..., 'minute').
    A time of exactly 12:00 AM is a date (precision day); a value that does not parse is (None, None)."""
    s = " ".join((text or "").split())
    try:
        dt = datetime.strptime(s, "%d-%b-%Y %I:%M%p")
    except ValueError:
        try:
            dt = datetime.strptime(s, "%d-%b-%Y")
            return dt.replace(tzinfo=tz).isoformat(), "day"
        except ValueError:
            return None, None
    prec = "day" if (dt.hour, dt.minute) == (0, 0) else "minute"
    return dt.replace(tzinfo=tz).isoformat(), prec


@lru_cache(maxsize=20000)
def scrub(v: str) -> str | None:
    """A state's comment as the record keeps it (the beach comments' scrub: ingest/oh_odh_beachguard.clean_comment)."""
    from ingest.oh_odh_beachguard import clean_comment
    return clean_comment(v)


def action_ids(v: str) -> list[str]:
    return [x for x in (y.strip() for y in (v or "").split(",")) if x]


def normalize(main_text: str, detail_text: str) -> tuple[dict[str, dict], Counter]:
    """{row key: the row as saved} from one year's two reports, and counts. The key is the row's lowest action id and
    its action type's code (TYPE_CODE), whatever the other rows hold: two rows that list the same ids under two types
    (California's Aliso County Beach, 2025) are two records. Comments are scrubbed here, before anything is saved."""
    detail = defaultdict(list)
    for d in rows_of(detail_text):
        detail[d.get("Activity ID", "")].append(d)
    rows = rows_of(main_text)
    out, n = {}, Counter()
    for r in rows:
        ids = sorted(action_ids(r.get("Action ID")), key=_num)
        if not ids or not r.get("Beach ID"):
            n["rows_without_id"] += 1
            continue
        base = f"{ids[0]}-{TYPE_CODE.get(r.get('Action Type') or '') or _slug(r.get('Action Type'))}"
        key, i = base, 1
        while key in out:              # the same ids and type twice in one report (not seen in 2014 to 2026)
            i += 1
            key = f"{base}~{i}"
        ds = [d for a in ids for d in detail.get(a, [])]
        comments = {k: _unique(scrub(d.get(col) or "") for d in ds)
                    for k, col in (("reason_comments", "Action ReasonsComment"),
                                   ("indicator_comments", "Action IndicatorComment"),
                                   ("possible_source_comments", "Action PossibleSourceComment"))}
        out[key] = {
            "key": key, "jurisdiction": r.get("Jurisdiction", "").upper(), "year": r.get("Year"),
            "beach_id": r.get("Beach ID"), "beach_name": r.get("BeachName") or None, "county": r.get("County") or None,
            "waterbody_name": r.get("WaterbodyName") or None, "waterbody_type": r.get("WaterbodyType") or None,
            "tier": r.get("Tier") or None, "station_ids": action_ids(r.get("Station ID")), "action_ids": ids,
            "action_type": r.get("Action Type") or None, "start_text": r.get("ActionStart Date") or None,
            "end_text": r.get("ActionEnd Date") or None, "reasons": codes(r.get("ActionReasons")),
            "indicators": codes(r.get("ActionIndicator")), "possible_sources": codes(r.get("ActionPossible Source")),
            "duration_days": r.get("ActionDurationDays") or None,
            "detail_rows": len(ds), **{k: v for k, v in comments.items() if v},
        }
        n["rows"] += 1
    return out, n


DETAIL_COVERAGE = 0.95      # 2014 to 2026: every main-report action id is in the detailed report


def check_year(year: int, main_text: str, detail_text: str) -> None:
    """PullError unless both reports are the requested year's (every row's Year) and the detailed report covers the
    main report's action ids (a header-only or cut-short detailed report would drop every state's comment)."""
    main, detail = rows_of(main_text), rows_of(detail_text)
    for name, rows in (("main", main), ("detail", detail)):
        if any(r.get("Year") != str(year) for r in rows):
            raise PullError(f"the {name} report holds rows of another year than {year}")
    ids = {a for r in main for a in action_ids(r.get("Action ID"))}
    if ids:
        have = {d.get("Activity ID") for d in detail}
        if len(ids & have) < DETAIL_COVERAGE * len(ids):
            raise PullError(f"the detailed report covers {len(ids & have)} of {len(ids)} action ids")


def _num(x: str):
    return (0, int(x)) if x.isdigit() else (1, x)


def _slug(v) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(v or "").lower()).strip("-") or "action"


def _unique(vals) -> list[str]:
    out = []
    for v in vals:
        if v and v not in out:
            out.append(v)
    return out


# ---------------------------------------------------------------- records

def load_registry(path: Path = REGISTRY_FILE) -> dict[str, dict]:
    doc = read_json(path, {}) or {}
    return {b["beach_id"]: b for b in doc.get("beaches") or [] if isinstance(b, dict) and b.get("beach_id")}


def beach_point(b: dict | None) -> tuple[float | None, float | None, str | None]:
    """(lat, lon, basis) of a registry beach: its start point, else its end point."""
    for end in ("start", "end"):
        try:
            lat, lon = float((b or {}).get(f"{end}_lat")), float((b or {}).get(f"{end}_lon"))
        except (TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0.0, 0.0):
            att = (b.get("cited") or {}).get("attributes") or {}
            return lat, lon, (f"the beach's {end} point in EPA's beach attributes"
                              + (f" ({att.get('report')}, {att.get('year')})" if att else ""))
    return None, None, None


def beach_zone(st: str, lat, lon, county) -> str:
    """The beach's clock: zones.zone_for by the state and the point, and Michigan's four Central-time counties by the
    county BEACON names (MI_CENTRAL_COUNTIES)."""
    if st == "MI" and str(county or "").strip().upper() in MI_CENTRAL_COUNTIES:
        return zones.CENTRAL
    return zones.zone_for(st, lat, lon) or "America/New_York"


def to_record(row: dict, reg: dict | None, fetched_at: str, prev: dict | None, first_seen: str | None = None) -> dict:
    st = row["jurisdiction"]
    lat, lon, basis = beach_point(reg)
    tz = ZoneInfo(beach_zone(st, lat, lon, row.get("county")))
    start, sprec = when(row.get("start_text"), tz)
    end, eprec = when(row.get("end_text"), tz)
    pulled = _t(fetched_at)
    end_t = _t(end)
    if end_t is not None and eprec == "day":
        end_t = end_t + timedelta(days=1)          # a date: the action ran through that local day
    lifted = end_t is not None and pulled is not None and end_t <= pulled
    praw = (prev or {}).get("raw") or {}
    raw = {k: row.get(k) for k in ("jurisdiction", "year", "beach_id", "beach_name", "county", "waterbody_name",
                                   "waterbody_type", "tier", "station_ids", "action_ids", "action_type", "reasons",
                                   "indicators", "possible_sources", "duration_days", "start_text", "end_text",
                                   "reason_comments", "indicator_comments",
                                   "possible_source_comments") if row.get(k) not in (None, [], "")}
    raw["reason_words"] = [REASON_WORDS.get(c, c) for c in row.get("reasons") or []]
    raw["indicator_words"] = [INDICATOR_WORDS.get(c, c) for c in row.get("indicators") or []]
    raw["possible_source_words"] = [SOURCE_WORDS.get(c, c) for c in row.get("possible_sources") or []]
    raw["state"] = st                              # the state the record counts under (status.event_state)
    raw["report"] = f"BEACON Beach Actions report, {row.get('year')}"
    raw["time_zone"] = tz.key
    raw["ended_at_precision"] = eprec
    if reg:
        raw["beach"] = {k: reg.get(k) for k in ("beach_act", "historical", "dormant", "access", "owner", "length_mi")
                        if reg.get(k) not in (None, "")}
    if basis:
        raw["point_basis"] = basis
    raw["_first_seen_at"] = first_seen or praw.get("_first_seen_at") or (prev or {}).get("fetched_at") or fetched_at
    rec = event(
        source_id=SOURCE_ID, source_record_id=row["key"], fetched_at=fetched_at,
        source_url=BEACH_PAGE.format(row["beach_id"]),
        event_type=EVENT_TYPE.get(row.get("action_type") or "", "beach_advisory"),
        status="advisory_lifted" if lifted else "advisory_active",
        waterbody_text=row.get("waterbody_name"), water_slugs=[], water_match="none",
        outfall_name=row.get("beach_name"),
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=start, ended_at=end, time_precision=sprec,
        reported_at=None, published_at=None, source_updated_at=None,
        authority=f"{AGENCY.get(st, 'The state beach program')}, as reported to U.S. EPA (BEACON 2.0)",
        advice_text=None, raw=raw,
    )
    if row.get("action_type") not in EVENT_TYPE:
        rec["raw"]["type_unmapped"] = row.get("action_type")
    return rec


def _t(v) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None
    return t.replace(tzinfo=UTC) if t is not None and t.tzinfo is None else t


# ---------------------------------------------------------------- copies of state records

def _metres(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(a)))


def to_beach_m(lat, lon, reg: dict | None) -> float | None:
    """Metres from (lat, lon) to the beach's line from its start to its end point (a flat projection; a beach is short)."""
    try:
        a = (float(reg["start_lat"]), float(reg["start_lon"]))
    except (TypeError, ValueError, KeyError):
        return None
    try:
        b = (float(reg["end_lat"]), float(reg["end_lon"]))
    except (TypeError, ValueError, KeyError):
        b = a
    k = math.cos(math.radians(a[0]))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], lon * k, lat
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return _metres(lat, lon, ay + t * dy, (ax + t * dx) / k)


def _get(raw, path: str):
    for p in path.split("."):
        raw = raw.get(p) if isinstance(raw, dict) else None
    return raw


def norm_name(v) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).split())


def _names(ev: dict) -> set[str]:
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    vals = [ev.get("outfall_name"), ev.get("waterbody_text")]
    for k in ("beach_name", "beachName", "beach", "name", "location", "station", "site"):
        v = raw.get(k)
        vals.append(v.get("beachName") if isinstance(v, dict) else v)
    return {n for n in (norm_name(v) for v in vals if isinstance(v, str)) if len(n) >= 4}


def _local_day(ev: dict, field: str = "started_at"):
    from build import status as S          # here, not at the top: the status build's clocks
    t = S.ev_time(ev, field)
    return t.astimezone(S.event_zone(ev)).date() if t is not None else None


def candidates(files: dict[str, dict]) -> list[dict]:
    """The state records a BEACON row may repeat (module docstring)."""
    out = []
    for sid, f in files.items():
        if sid in NOT_LINKED_SOURCES or not isinstance(f, dict):
            continue
        if (f.get("meta") or {}).get("distribution_discouraged"):
            continue
        for r in f.get("records") or []:
            if isinstance(r, dict) and r.get("event_id") and r.get("event_type") in LINK_TYPES \
                    and not r.get("duplicate_of") and r.get("started_at"):
                out.append(r)
    return out


def link_copies(records: list[dict], cands: list[dict], registry: dict[str, dict]) -> Counter:
    """Set duplicate_of on each record that repeats a state record (module docstring); returns the counts. A name links
    only a state record with no point: a point more than LINK_M from the beach says it is another beach."""
    from build import status as S
    by_id, by_day = defaultdict(list), defaultdict(list)
    for ev in cands:
        d = _local_day(ev)
        if d is None:
            continue
        c = {"ev": ev, "day": d, "names": None}
        path = BY_ID_PATHS.get(ev.get("source_id"))
        v = _get(ev.get("raw") or {}, path) if path else None
        if isinstance(v, str) and v.strip():
            by_id[v.strip().upper()].append(c)
        by_day[(S.event_state(ev) or "", d)].append(c)
    pairs = []
    for rec in records:
        rec["duplicate_of"] = None
        raw = rec["raw"]
        raw.pop("copy_of", None)
        raw.pop("_duplicate_basis", None)
        d = _local_day(rec)
        if d is None:
            continue
        reg = registry.get(raw.get("beach_id"))
        kinds = COMPATIBLE.get(rec.get("event_type"), frozenset())
        seen = set()
        for c in by_id.get(str(raw.get("beach_id") or "").upper(), []):
            days = abs((c["day"] - d).days)
            if days <= LINK_DAYS and c["ev"].get("event_type") in kinds:
                seen.add(c["ev"]["event_id"])
                pairs.append(((0, days, 0.0), rec, c, "epa_beach_id", None, days))
        mine = norm_name(raw.get("beach_name"))
        near = [c for k in range(-LINK_DAYS, LINK_DAYS + 1)
                for c in by_day.get((raw.get("jurisdiction"), d + timedelta(days=k)), [])]
        for c in near:
            if c["ev"]["event_id"] in seen or c["ev"].get("event_type") not in kinds:
                continue
            days = abs((c["day"] - d).days)
            try:
                lat, lon = float(c["ev"]["lat"]), float(c["ev"]["lon"])
            except (TypeError, ValueError, KeyError):
                lat = lon = None
            m = to_beach_m(lat, lon, reg) if lat is not None and reg else None
            if m is not None:
                if m > LINK_M:
                    continue
                how = "point"
            elif lat is None:
                if c["names"] is None:
                    c["names"] = _names(c["ev"])
                if not (mine and mine in c["names"]):
                    continue
                how = "name"
            else:
                continue            # the state's record has a point and this beach none: nothing to compare
            if S.waters_differ(rec, c["ev"]):
                continue
            pairs.append(((1 if how == "point" else 2, days, m if m is not None else LINK_M), rec, c, how, m, days))
    pairs.sort(key=lambda p: (p[0], p[1]["event_id"], p[2]["ev"]["event_id"]))
    used, n = set(), Counter()
    for _, rec, c, how, m, days in pairs:
        other = c["ev"]
        if rec["duplicate_of"] or other["event_id"] in used:
            continue
        rec["duplicate_of"] = other["event_id"]
        rec["raw"]["copy_of"] = {"event_id": other["event_id"], "source_id": other.get("source_id"), "by": how,
                                 "days_apart": days, **({"metres": round(m)} if m is not None else {})}
        said = {"epa_beach_id": f"the same EPA beach id ({rec['raw'].get('beach_id')})",
                "point": f"its point {round(m or 0)} m from the beach's line",
                "name": "the same beach name in the same state"}[how]
        rec["raw"]["_duplicate_basis"] = (f"the state's record {other['event_id']} of {other.get('source_id')}: "
                                          f"{said}, starting {days} day(s) apart")
        used.add(other["event_id"])
        n[f"by_{how}"] += 1
    return n


# ---------------------------------------------------------------- the run

def load_files(events_dir: Path = EVENTS_DIR) -> dict[str, dict]:
    """The other beach feeds' events files: every source with an entry in rules.json beach_reason."""
    rules = read_json(DATA_DIR / "rules.json", {}) or {}
    sids = set(((rules.get("beach_reason") or {}).get("sources") or {})) - NOT_LINKED_SOURCES
    out = {}
    for sid in sorted(sids):
        f = read_json(events_dir / f"{sid}.json", None)
        if isinstance(f, dict):
            out[sid] = f
    return out


def build(state: dict, registry: dict[str, dict], files: dict[str, dict], prev_records: list[dict]) -> tuple[list[dict], dict]:
    prev = {r["event_id"]: r for r in prev_records if isinstance(r, dict) and r.get("event_id")}
    first = state.get("first_seen") or {}         # {action id: the first pull that listed it}, kept for good
    records, out_scope = [], Counter()
    seen = set()
    by_sy, newest, no_point, no_reg, private, historical = Counter(), {}, Counter(), Counter(), Counter(), Counter()
    for y in sorted((state.get("years") or {}), reverse=True):
        yd = state["years"][y]
        for key, row in sorted((yd.get("rows") or {}).items()):
            st = row.get("jurisdiction") or ""
            if st not in IN_SCOPE:
                out_scope[st or "(none)"] += 1
                continue
            eid = f"{SOURCE_ID}:{key}"
            if eid in seen:
                continue            # a row a later year's report lists again: the later report's copy is kept
            seen.add(eid)
            reg = registry.get(row.get("beach_id"))
            seen_at = [first[a] for a in row.get("action_ids") or [] if first.get(a)]
            rec = to_record(row, reg, yd.get("pulled_at") or state.get("pulled_at") or now_iso(), prev.get(eid),
                            min(seen_at, key=lambda v: _t(v) or datetime.max.replace(tzinfo=UTC)) if seen_at else None)
            records.append(rec)
            by_sy[(st, str(row.get("year")))] += 1
            if rec["started_at"] and (st not in newest or rec["started_at"] > newest[st]["start"]):
                newest[st] = {"start": rec["started_at"], "end": rec["ended_at"], "event_id": rec["event_id"]}
            if reg is None:
                no_reg[st] += 1
            if rec["lat"] is None:
                no_point[st] += 1
            if reg and str(reg.get("owner") or "").lower() == "private":
                private[st] += 1
            if reg and str(reg.get("historical") or "").upper() == "Y":
                historical[st] += 1
    links = link_copies(records, candidates(files), registry)
    linked_by_sy = Counter((r["raw"]["jurisdiction"], str(r["raw"].get("year")), r["raw"]["copy_of"]["by"])
                           for r in records if r.get("duplicate_of"))
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    by_state = defaultdict(dict)
    for (st, y), k in sorted(by_sy.items()):
        by_state[st][y] = {"actions": k, **{f"linked_by_{h}": linked_by_sy[(st, y, h)]
                                            for h in ("epa_beach_id", "point", "name") if linked_by_sy[(st, y, h)]}}
    meta = {"credit": CREDIT, "registry_ids": [SOURCE_ID], "history_only": True, "published_in_batches": True,
            "years": {y: {"pulled_at": state["years"][y].get("pulled_at"),
                          "rows": len(state["years"][y].get("rows") or {})} for y in sorted(state.get("years") or {})},
            "last_pull_at": state.get("pulled_at"), "by_state_year": dict(by_state),
            "newest_action_by_state": dict(sorted(newest.items())),
            "out_of_scope": {"rows": sum(out_scope.values()), "by_jurisdiction": dict(sorted(out_scope.items()))},
            "no_point": {"rows": sum(no_point.values()), "by_state": dict(sorted(no_point.items()))},
            "no_registry_row": {"rows": sum(no_reg.values()), "by_state": dict(sorted(no_reg.items()))},
            "private_owner_beaches": dict(sorted(private.items())),
            "historical_beaches": dict(sorted(historical.items())),
            "links": {"linked": sum(links.values()), **dict(sorted(links.items())),
                      "state_files_read": sorted(files),
                      "withheld_not_linked": sorted(s for s, f in files.items()
                                                    if (f.get("meta") or {}).get("distribution_discouraged"))}}
    return records, meta


def refresh_years(now: datetime | None = None) -> list[int]:
    y = (now or datetime.now(UTC)).astimezone(TZ_EAST).year
    return [y - 1, y]


def rewrite(records: list[dict], meta: dict, path: Path | None = None) -> Path:
    """The records written again between pulls: the file's header (fetched_at, ok, last_ok_at) stays the last pull's."""
    path = Path(path) if path is not None else EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = read_json(path, {}) or {}
    out = {**prev, "source_id": SOURCE_ID, "meta": meta, "count": len(records), "records": records}
    write_json(path, out)
    return path


def read_saved(from_dir: Path, year: int) -> tuple[str, str]:
    return ((from_dir / f"{MAIN}_{year}.csv").read_text(encoding="utf-8-sig"),
            (from_dir / f"{DETAIL}_{year}.csv").read_text(encoding="utf-8-sig"))


def note_first_seen(state: dict, pulled: dict) -> None:
    """state["first_seen"]: each action id's first pull, kept for good (a row that leaves a report and comes back, or
    is regrouped with other ids, keeps its first read)."""
    first = state.setdefault("first_seen", {})
    for y, yd in pulled.items():
        for row in (yd.get("rows") or {}).values():
            for a in row.get("action_ids") or []:
                first.setdefault(a, yd["pulled_at"])


def summary(records: list[dict], meta: dict, what: str) -> str:
    links = meta["links"]
    return (f"{SOURCE_ID}: {what}; {len(records)} records in scope, {links['linked']} linked as copies of state records "
            f"({links.get('by_epa_beach_id', 0)} by EPA id, {links.get('by_point', 0)} by point, "
            f"{links.get('by_name', 0)} by name), {meta['out_of_scope']['rows']} out of scope, "
            f"{meta['no_point']['rows']} with no point")


def run(argv=None, sess=None, sleep=time.sleep, now: datetime | None = None, events_dir: Path = EVENTS_DIR,
        state_file: Path = STATE_FILE, registry_file: Path = REGISTRY_FILE) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="pull now even within 20 hours of the last pull")
    ap.add_argument("--backfill", type=int, metavar="FROM_YEAR",
                    help="pull the years from FROM_YEAR to the one before the previous year (by hand)")
    ap.add_argument("--from-dir", type=Path, help="read saved CSVs instead of BEACON (no network)")
    ap.add_argument("--fetched-at", help="with --from-dir: when the saved CSVs were fetched (ISO time)")
    args = ap.parse_args(argv)
    now = now or datetime.now(UTC)
    fetched_at = args.fetched_at if args.from_dir and args.fetched_at else \
        now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out_path = events_dir / f"{SOURCE_ID}.json"
    state = read_json(state_file, {}) or {}
    state.setdefault("years", {})
    years = refresh_years(now)
    if args.backfill:
        years = list(range(args.backfill, years[0]))
        if not years:
            print(f"{SOURCE_ID}: --backfill {args.backfill} names no year before {refresh_years(now)[0]}: nothing read",
                  file=sys.stderr)
            return 2
    last = _t(state.get("pulled_at"))
    due = bool(args.force or args.backfill or args.from_dir or last is None or not out_path.exists()
               or now - last >= timedelta(hours=MIN_HOURS))
    pulled, failed, counts = {}, [], Counter()
    if due:
        sess = sess or (None if args.from_dir else new_session())
        for y in years:
            try:
                main_text, detail_text = read_saved(args.from_dir, y) if args.from_dir else pull_year(sess, y, sleep)
                check_year(y, main_text, detail_text)
                rows, n = normalize(main_text, detail_text)
                had = len((state["years"].get(str(y)) or {}).get("rows") or {})
                if not rows and (had or args.backfill):
                    # a past year's national report is never empty, nor one whose rows we hold
                    raise PullError(f"the {y} report listed no action")
                pulled[str(y)] = {"pulled_at": fetched_at, "rows": rows}
                counts.update(n)
            except (requests.RequestException, PullError, OSError, csv.Error, UnicodeError) as e:
                failed.append(f"{y}: {type(e).__name__}")
                if not args.backfill:
                    break
        if not failed and not args.backfill and pulled and not any(v["rows"] for v in pulled.values()):
            failed.append("every year: PullError")      # the reports answered, and listed no action at all
        if failed and (not args.backfill or not pulled):
            err = f"BEACON pull failed ({'; '.join(failed)})"
            if state["years"]:
                # the saved rows written again and linked to this hour's state files: a link to a state record that
                # has gone is dropped, though BEACON could not be read (health stays false, last_ok_at the last pull)
                prev = (read_json(out_path, {}) or {}).get("records") or []
                records, meta = build(state, load_registry(registry_file), load_files(events_dir), prev)
                meta["years_not_read"] = failed
                write_events(SOURCE_ID, records, ok=False, error=err, meta=meta, path=out_path, partial=True)
            else:
                write_events(SOURCE_ID, [], ok=False, error=err, path=out_path)
            print(f"{SOURCE_ID}: FAILED {err}", file=sys.stderr)
            return 1
        state["years"].update(pulled)
        note_first_seen(state, pulled)
        if not args.backfill:
            state["pulled_at"] = fetched_at
        write_json(state_file, state)
    prev = (read_json(out_path, {}) or {}).get("records") or []
    records, meta = build(state, load_registry(registry_file), load_files(events_dir), prev)
    if counts:
        meta["this_pull"] = dict(sorted(counts.items()))
    if failed:
        meta["years_not_read"] = failed
    if due:
        write_events(SOURCE_ID, records, ok=not failed, error=None if not failed else
                     f"BEACON backfill: {len(failed)} year(s) not read", meta=meta, path=out_path,
                     partial=bool(failed))
    else:
        rewrite(records, meta, out_path)
    print(summary(records, meta, "pulled " + ", ".join(pulled) if due else
                  f"no pull due (last {state.get('pulled_at')})") + (f"; not read: {', '.join(failed)}" if failed else ""))
    return 0


def relink_only(events_dir: Path = EVENTS_DIR, state_file: Path = STATE_FILE, registry_file: Path = REGISTRY_FILE) -> int:
    """The records written again from the saved rows and linked to the state feeds' files as they stand after this
    hour's feeds (ingest/fed_beacon_beach_link.py, Makefile INGEST_SNAPSHOTS); no network, the header kept."""
    out_path = events_dir / f"{SOURCE_ID}.json"
    state = read_json(state_file, {}) or {}
    if not state.get("years") or not out_path.exists():
        print(f"{SOURCE_ID}: no saved rows or no events file: nothing to link")
        return 0
    prev = (read_json(out_path, {}) or {}).get("records") or []
    records, meta = build(state, load_registry(registry_file), load_files(events_dir), prev)
    rewrite(records, meta, out_path)
    print(summary(records, meta, "linked again after the state feeds"))
    return 0


if __name__ == "__main__":
    sys.exit(run())
