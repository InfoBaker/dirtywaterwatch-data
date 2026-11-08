"""Per-water status now and the hourly history of the last 90 days (docs/plan.md §2).

    python -m build.status [--fixtures] [--include-nhdes] [--now 2026-11-02T12:00:00Z]

Reads every data/build/events/*.json, the outfall registry (every data/outfalls-*.json through
common.load_outfall_registry), data/dischargers.json (towns, receiving waters), the water
records (data/waters-ne.json, plus data/waters-extra.json and data/waters-nhd.json when they exist; the hand aliases of
data/water-aliases.json, {slug: [texts]}, are merged into the records' aliases) and the source registry
(data/sources/*.yaml when present). Writes data/build/status.json and data/build/history.json.

The rules are written out in docs/plan.md §2 (kept in step with this module and its tests):
discharge windows (ongoing red 72 h, yellow to 7 days, then "end never reported"; ended: red to
the authority window, yellow to 72 h; unknown-status no end: yellow 7 days); state default
windows and caution windows from data/rules.json (red_rule / yellow_rule); month/year records never colour; beach/rain/HAB advisories colour only lakes,
ponds and reservoirs under 50 km² and are otherwise advisory points; active advisories age out
14 days after the last confirmation; a discharge's end before its start or more than
unresolved.implausible_end.days_after_fetch days after the report was read is not used (end_not_credible: the record
has no confirmed end, the published value stays, intervals carry end_not_used); revisions (resolve_revisions); ECHO
duplicates (find_duplicates: a dry-land record never absorbs a report of a water); the placement guard (Resolver.guard_detail: 2 km, or the water's own reach for a
named match), the outfall registry for reports that name no water or a water no record matches (Resolver.by_registry:
the outfalls a report names, outfall_ids_of, each to its water, Resolver.by_outfalls), reports that
name no receiving water (no_receiving_water: counted apart, colour nothing) and reports of no release (no_release,
counted with them); CSO reports naming no outfall shown on every water of their permit (rules.placement); withheld
distribution_discouraged files.

Discharge likely (build/rain_likely.py, when rules.rain_likely.enabled): radar rainfall over a CSO
permittee's threshold with no notice from it in the last 24 hours colours its reaches, the rivers
along them and its lakes and ponds yellow, rule "rain_likely" (status.json "rain_likely" block,
waters[].rain, reasons[].rain); docs/rain-likely.md.

Outputs: status.json {built, now, fixtures_included, restricted_included, withheld_sources, rules,
advisory_windows (data/rules.json version), constants, counts, waters: {slug: {status, since, reason_short, reasons, events,
covered_by, stale, stale_sources, fixture_only}}, placements, sources (with placement counts),
unplaced_events, no_receiving_water_events,
duplicates, advisory_points, dropped_fixtures, problems}; history.json {start, step_hours, hours,
waters: {slug: one char per hour, r/y/g}, intervals: {slug: [[from, until, colour, rule, event]]}}.
"""
from __future__ import annotations

import argparse
import copy
import functools
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import zones
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, ROOT, SOURCES_DIR, discharger_alias_map, load_outfall_registry,
                    now_iso, read_json, rules_live_states, write_json)
from build import shoreline as SH
from build.redact import REDACTED, person_shaped

LOCAL = ZoneInfo("America/New_York")
OBL_WATER_DIR = Path(os.environ.get("OBL_WATER_DIR", ROOT.parent / "openboatlaunch" / "out" / "water"))
# The states the site covers are not a code constant: data/rules.json `live_states` is the one list (states(),
# 2026-11-03g); water records of other states may sit in data/waters-*.json without opening one. Rules without
# the list (older test rules) fall back to the water records' states and rules.red.by_state; NE is the pilot's
# fallback when neither is readable.
NE = {"MA", "CT", "RI", "NH", "VT", "ME", "NY"}
_STATES: set[str] | None = None


def derive_states(waters: dict | None = None, rules: dict | None = None, live_only: bool = True) -> set[str]:
    """The live states: rules.json `live_states` exactly when the rules carry the list (2026-11-03g: water records
    and registry rows of other states sit in data/ without opening a state). live_only=False, or rules without
    the list (older test rules), gives the states of the water records and rules.red.by_state, as before (a tool
    working beyond the live states, e.g. building water records for the next state, can ask for that)."""
    live = rules_live_states(rules)
    if live is not None and live_only:
        return set(live)
    out = {str(w.get("state")).upper() for w in (waters or {}).values() if w.get("state")}
    out |= live or set()
    out |= {str(k).upper() for k in (((rules or {}).get("red") or {}).get("by_state") or {})}
    if waters is not None and not any(w.get("state") for w in waters.values()):
        out |= {str(w.get("state")).upper() for w in load_waters().values() if w.get("state")}
    return {x for x in out if re.fullmatch(r"[A-Z]{2}", x)} or set(NE)


def states() -> set[str]:
    """The live states: data/rules.json `live_states` (cached; build() refreshes it from the rules it uses). Every
    public output keeps to it: placement, the guard, windows, counts, coverage, the outfall registry's rows, the radar
    reads, the export and the CSV downloads."""
    global _STATES
    if _STATES is None:
        rules = load_rules()
        _STATES = derive_states(None, rules) if rules_live_states(rules) is not None else derive_states(load_waters(), rules)
    return _STATES


def water_state(slug: str, w: dict | None = None) -> str:
    """A water record's state: its own, else its slug's last part ("mill-river-ma" -> "MA")."""
    st = str((w or {}).get("state") or "").upper()
    return st or str(slug).rsplit("-", 1)[-1].upper()


def live_waters(waters: dict, live: set[str] | None = None) -> dict:
    """The water records of the live states (states()): a record built for a state not yet live stays in data/ and
    reaches no placement, status, map, page or download."""
    live = states() if live is None else live
    return {s: w for s, w in waters.items() if water_state(s, w) in live}

HISTORY_DAYS = 90
ADVISORY_NO_END_DAYS = 7     # an advisory record with no status and no end: yellow this long
NOTE_DAYS = HISTORY_DAYS
GEOMETRY_MATCH_M = 400
# Placement guard for name-based slugs (water_match name or inferred, the ingester's or ours): the
# water must be in the event's state, and the event's point (when it has one) within NAME_MATCH_M of
# the water (WIDE_NAME_MATCH_M for bays and sounds). Beyond that a named match is still kept when the
# point lies within the water's own reach, scaled by its kind (name_limit_m): rivers, streams and canals
# up to the record's extent (its bounding-box diagonal, at most RIVER_EXTENT_CAP_M) plus NAME_MARGIN_M,
# lakes, ponds and reservoirs within the polygon plus LAKE_NAME_MATCH_M; and only when the report's town
# (its own municipality field or its operator's towns) is unknown or among the water's towns, so a named
# match never lands on a same-named water in another town. Otherwise the slug is set aside, unplaced.
# Point-only matches (by_point) keep GEOMETRY_MATCH_M.
NAME_MATCH_M = 2000
WIDE_NAME_MATCH_M = 5000
NAME_MARGIN_M = 2000
RIVER_EXTENT_CAP_M = 10000
LAKE_NAME_MATCH_M = 3000
WIDE_KINDS = {"bay", "sound"}
GUARDED_MATCHES = {"name", "inferred"}
# The steps of the placement work of 2026-11-03, switchable for measuring them one at a time (all on).
# outfall_ids: the outfalls a report names (its outfall_id, an outfall number in its outfall name, the per-outfall
# volume string of the CT DEEP dashboard's Greater New Haven rows) joined to the registry, also when its water text
# matched no record, with the outfall's own point as the last resort (OUTFALL_POINT_M); multi_outfall: a report
# whose outfalls reach several waters is placed on each of them (one record, several waters).
# no_release: a report whose text says nothing was released ("No release" at every outfall it lists, "No
# overflow", "0 Did not overflow") is kept but colours nothing (no_release); a mixed per-outfall report is placed
# on its released outfalls only.
# stated_no_water (review 2026-11-03 P1-3): a report whose source says the discharge reached no water (its own flag,
# no_water_flag, or its receiving-water text: "did not reach", "was contained", STATED_NO_WATER) is classed no
# receiving water before any name, point or outfall placement; the water it names stays in the note only.
# registry_first (owner, 2026-11-03, next-steps 2g): a report whose outfalls (outfall_ids_of) the registry maps to a
# water is placed on that water before any name matching (Resolver.registry_first), and a registry row the registry
# pass has matched (water_matched_by) keeps its own water_slug, or its stated lack of one, instead of status.py
# re-reading its receiving-water text (Resolver.row_water). The report's own text yields only when it names another
# water (REGISTRY_YIELDS_TO_NAMED_WATER).
# watershed_labels (same date): a receiving-water text that is a watershed label (a USGS HUC-12 name, an MDE basin
# label, "<name> watershed", "<stream> basin", "<stream> drainage") is never read as a water name (watershed_labels).
PLACE_STEPS = {"registry": True, "relaxed_guard": True, "no_receiving_water": True, "outfall_ids": True,
               "multi_outfall": True, "no_release": True, "stated_no_water": True, "registry_first": True,
               "watershed_labels": True}
# When the report's own receiving-water text names a water (kept by the placement guard) whose name shares no name
# word with the registry's water for its outfall, the report's named water is used and the registry's is noted:
# the registry's water for many outfalls is EPA's point snapped to the nearest record (scripts/match_outfalls.py
# 'geometry': New Bedford's CLARK COVE outfalls on Buzzards Bay, Fall River's TAUNTON RIVER on Narragansett Bay,
# New Haven Harbor on Long Island Sound), and the discharger's report names the water per overflow. A registry water
# of the same name (another Hudson River record, the Jersey City one) or a text that names no record wins for the
# registry. False: the registry's water wins over every name (measured 2026-11-03 on 63,881 reports: 5,040 placed by
# the name they give move onto the registry's water, New Bedford Harbor and Clarks Cove onto Buzzards Bay; with True,
# 294 move onto the registry's water and 1,195 that the outfall_id alone had put on it move to the water they name).
REGISTRY_YIELDS_TO_NAMED_WATER = True
# rules.placement.no_outfall_all_waters (data/rules.json, a switch): a CSO report that names no water and no outfall
# is placed on every water its permit's registry outfalls reach (a permit the registry lacks: every receiving water
# data/dischargers.json lists, CSO reports only since review 2026-11-03 P3-1), with this note
NO_OUTFALL_NOTE = "outfall not stated in the report; shown on every water this permit's outfalls discharge to"
# A registry outfall with no water slug and no water of its receiving water's name takes the water at its own
# point only this close, and only when that water's name does not contradict its receiving water's
# (names_disagree): ECHO outfall points sit at street corners, and a point 237 m from Bruce Brook is not a
# discharge to Bruce Brook when the permit says Johnson's Creek.
OUTFALL_POINT_M = 150

DISCHARGE_TYPES = {"cso", "sso", "bypass", "blended", "plant_bypass"}
COARSE_PRECISION = {"month", "year"}
# docs/plan.md §2.x: a month-precision discharge report marks its outfall and water "monthly" for the reported month
# (local time) in the history, and on the current map while it is its outfall's latest report and its month ended
# at most this many days ago (a site default: an outfall that stopped reporting does not keep its mark for ever)
MONTHLY_CURRENT_DAYS = 90
DAYS_TEXT = re.compile(r"(\d+)\s+days?\s+with\s+discharge", re.I)
EVENTS_TEXT = re.compile(r"(\d+)\s+discharge\s+events?", re.I)
EPA_MONTHLY_SOURCES = ("nj-echo-monthly", "echo-cso-dmr-monthly")
POINT_ADVISORY_TYPES = {"beach_advisory", "beach_closure", "rain_advisory", "hab_advisory"}
WHOLE_WATER_KINDS = {"lake", "pond", "reservoir"}
SMALL_WATER_KM2 = 50
# An advisory_active beach, rain, HAB or shellfish record with no explicit end stops colouring
# CONFIRM_DAYS after the source last confirmed it (the later of started_at and source_updated_at).
AGING_TYPES = {"hab_advisory", "beach_advisory", "beach_closure", "rain_advisory", "shellfish_closure"}
CONFIRM_DAYS = 14
ADVISORY_TYPES = {"beach_advisory", "beach_closure", "hab_advisory", "shellfish_closure", "rain_advisory"}
RANK = {None: -1, "grey": 0, "monthly": 1, "unresolved": 2, "yellow": 3, "red": 4}
CHAR = {"red": "r", "yellow": "y", "unresolved": "u", "monthly": "m", "grey": "g"}
LEGEND = {"r": "red: advisory in effect", "y": "yellow: caution",
          "u": "unresolved: no end reported (hatched yellow)",
          "m": "monthly report: days with discharge, dates not given (dotted)", "g": "grey: tracked, no current report",
          "R": "beach advisory in effect, no sewage status (red)", "Y": "beach caution, no sewage status (yellow)",
          "B": "algal bloom advisory, no sewage status"}
RIVER_KINDS = {"river", "stream", "canal"}
NO_FILL_KINDS = RIVER_KINDS | {"bay", "sound"}     # coloured by reaches / markers, never filled whole
# Shoreline lakes (the Great Lakes: data/rules.json reach.shoreline, build/shoreline.py; decision of 2026-11-04): never
# filled whole either. A report from an outfall (or with a point) on one colours its modeled shoreline stretch, a reach
# record with model "shoreline", which carries the report like a river reach: the lake lists the report and takes its
# status (placement "reach"), the map draws the stretch and the lake's outline only (fill false, stretch_model).
# A report on one with no stretch is listed and counted (placement "shoreline_unmodeled") and colours no shore.
SHORE_STATUS_BASIS = "modeled shoreline stretches at the outfalls; the lake is not coloured whole"
# the open ocean (reach.shoreline.oceans, 2026-11-04): the same model on the state's ocean shore, its own words
OCEAN_STATUS_BASIS = "modeled shoreline stretches at the outfalls and reported locations; the ocean is not coloured whole"
# a sound under the lake model (reach.shoreline.lakes with kinds ["sound"]: Puget Sound, 2026-11-06)
SOUND_STATUS_BASIS = "modeled shoreline stretches at the outfalls; the sound is not coloured whole"
# a bay under the lake model (reach.shoreline.lakes with kinds ["bay"]: San Francisco Bay, 2026-11-06)
BAY_STATUS_BASIS = "modeled shoreline stretches at the outfalls; the bay is not coloured whole"
SHORE_SUMMARY = "affected along a modeled shoreline stretch"
_SHORE_REACHES: set[str] = set()       # the reach keys of this build's shoreline stretches (where())
# An authority's advisory for a named stretch of a river (the record's `stretch`, docs/plan.md §3): build/reaches.py
# traces the stretch (reach kind "advisory_stretch") and the advisory colours only that stretch, in its own category
# (beach), with no travel time; the rivers it runs along take their state from it (placement "reach") and the water
# page still lists the advisory. With no stretch traced (not yet, its end off the mapped path or upstream of its start)
# the advisory stays a coloured marker at its point and the river is not coloured (reaches, not whole rivers; SOL
# wave2 P1-3, 2026-11-07); the marker's why says the stretch could not be traced (stretch_fallback).
ADVISORY_STRETCH = "advisory_stretch"
_STRETCH_REACHES: set[str] = set()     # the reach keys of this build's advisory stretches (where())
STRETCH_SUMMARY = "part of this water is under an authority's advisory for a named stretch"
REACH_WATER_M = 500                                 # a reach segment lies on a river water within this

# Advisory windows (owner decision 2026-11-02) live in data/rules.json: red hours by state (the
# authority's own window; null = red only while the discharge runs) and the site's yellow caution
# hours, resolved by_water > by_water_kind > by_event_type > default, counted from ended_at.
RULES_PATH = DATA_DIR / "rules.json"
FOLLOW_AUTHORITY_TYPES = ADVISORY_TYPES | {"annual_total"}   # yellow: by_event_type only
_RULES: dict | None = None


def load_rules(path: Path | None = None) -> dict:
    global _RULES
    if path is None and _RULES is not None:
        return _RULES
    d = read_json(path or RULES_PATH) or {}
    d.setdefault("red", {}).setdefault("by_state", {})
    d.setdefault("yellow", {}).setdefault("default_hours", None)
    if path is None:
        _RULES = d
    return d


def red_rule_for(ev: dict, state: str | None, rules: dict) -> dict:
    """The authority's window after the end: the event's stated window, else the discharger's entry
    (rules.red.by_discharger, by discharger_id), else the state's entry."""
    if ev.get("advice_window_hours") is not None:
        return {"rule": "red.event", "hours": float(ev["advice_window_hours"]),
                "rationale": ev.get("advice_window_basis") or "stated in the source record",
                "source": ev.get("source_url"), "clock": "end_of_discharge"}
    by_d = (rules.get("red") or {}).get("by_discharger") or {}
    did = ev.get("discharger_id")
    if did not in by_d and ev.get("discharger_id_source") in by_d:    # a rule written under the ingester's id
        did = ev["discharger_id_source"]
    r = by_d.get(did) if did and not str(did).startswith("_") else None
    if isinstance(r, dict):
        return {"rule": f"red.by_discharger.{did}", "hours": r.get("hours"), "rationale": r.get("basis"),
                "source": r.get("source"), "clock": r.get("clock")}
    r = (rules.get("red") or {}).get("by_state", {}).get(state)
    if r is not None:
        return {"rule": f"red.by_state.{state}", "hours": r.get("hours"), "rationale": r.get("basis"),
                "source": r.get("source"), "clock": r.get("clock")}
    return {"rule": "red.none", "hours": None, "rationale": "no authority window on file for this state",
            "source": "data/rules.json", "clock": None}


def yellow_rule_for(ev: dict, water: dict | None, rules: dict) -> dict:
    """The site's caution window after the end: by_water > by_water_kind > by_event_type > default.
    Beach, rain, HAB, shellfish and annual records follow the authority (by_event_type only)."""
    y = rules.get("yellow") or {}
    et = ev.get("event_type") or "unknown"
    water = water or {}

    def pack(level, key, r):
        return {"rule": f"yellow.{level}.{key}", "hours": r.get("hours"), "rationale": r.get("rationale"),
                "source": r.get("source")}
    if et not in FOLLOW_AUTHORITY_TYPES:
        slug = water.get("slug")
        r = (y.get("by_water") or {}).get(slug) if slug and not slug.startswith("_") else None
        if isinstance(r, dict) and r.get("enabled", True) is not False:
            return pack("by_water", slug, r)
        kind = water.get("kind")
        r = (y.get("by_water_kind") or {}).get(kind) if kind else None
        if isinstance(r, dict):
            return pack("by_water_kind", kind, r)
    r = (y.get("by_event_type") or {}).get(et)
    if isinstance(r, dict):
        return pack("by_event_type", et, r)
    return {"rule": "yellow.default", "hours": y.get("default_hours"), "rationale": y.get("default_rationale"),
            "source": "data/rules.json"}


# docs/plan.md §2.z: every status effect, history hour, map feature, list row and count carries a category
CATEGORIES = ("sewage", "beach", "bloom")
CATEGORY_OF = {"beach_advisory": "beach", "beach_closure": "beach", "shellfish_closure": "beach",
               "rain_advisory": "beach", "hab_advisory": "bloom"}           # every other type (discharges): sewage
CATEGORY_LABEL = {"sewage": "Sewage", "beach": "Beach advisory", "bloom": "Algal bloom advisory"}
# the history letter of an hour with no sewage status: a beach advisory R (red) or Y (yellow, unresolved), a bloom B
BEACH_CHAR = {"red": "R", "yellow": "Y", "unresolved": "Y"}
BLOOM_CHAR = "B"


def precedence(category, status) -> int:
    """The site's order of hour letters and headlines (docs/plan.md §2.z): r > y > u > R > Y > B > m > g, i.e. a sewage
    discharge, caution or unresolved report, then a beach advisory (red, then yellow or unresolved), then a bloom
    advisory, then the monthly mark (a monthly total is no active status), then nothing. Lower comes first."""
    cat = category or "sewage"
    if status == "grey" or status is None:
        return 7
    if cat == "sewage":
        return {"red": 0, "yellow": 1, "unresolved": 2, "monthly": 6}.get(status, 7)
    if cat == "beach":
        return 3 if status == "red" else 4
    return 5


def category_of(event_type) -> str:
    """sewage (cso, sso, bypass, blended, plant_bypass, unknown, annual totals, the rain-likely caution), beach
    (beach advisories and closures, shellfish closures, rainfall advisories) or bloom (algal bloom advisories)."""
    return CATEGORY_OF.get(event_type or "", "sewage")


RULES = {
    "ongoing": ("red", "Discharge ongoing (no end reported yet)"),
    "unresolved": ("unresolved", "Unresolved: no end reported"),
    "discharge": ("red", "Discharge in progress"),
    "authority_window": ("red", "Within the authority's advice window after the discharge ended"),
    "advisory_active": ("red", "Official advisory in effect"),
    "caution": ("yellow", "Within the site's caution window after the discharge ended (data/rules.json)"),
    "no_end": ("yellow", "Discharge record with no status and no reported end"),
    "day_start_caution": ("yellow", "Report dated to the day only, with no end: caution from the start of that day"),
    "text_caution": ("yellow", "Water named in the notice's text; the notice's form said no water was reached: "
                               "the site's caution, not an advisory"),
    "citizen_caution": ("yellow", "Reported by a member of the public, not confirmed by an authority: the site's "
                                  "caution, not an advisory"),
    "code_caution": ("yellow", "A code on the source's map whose meaning the source does not publish: the site's "
                               "caution, not an advisory"),
    "end_never_reported": ("grey", "Unresolved: no end reported (off the map after 30 days)"),
    "not_reconfirmed": ("grey", "Advisory not re-confirmed by the source for 14 days (sets no colour)"),
    "rain_advisory": ("yellow", "Precautionary rainfall advisory"),
    "advisory_unconfirmed": ("yellow", "Advisory with no reported status, issued less than 7 days ago"),
    # data/rules.json unresolved.sample_caution: a sample result the agency labels a risk but issues no advisory for
    "sample_caution": ("yellow", "Elevated result in the agency's sample; no advisory issued: the site's caution"),
    # build/rain_likely.py: radar rainfall over the permittee's threshold, no notice in the last 24 h
    # ("Discharge possible: ..." where only this site's default amount applies: rain_likely.label_for, per interval)
    "rain_likely": ("yellow", "Discharge likely: heavy rain, no report received"),
    # docs/plan.md §2.x: a month-precision report (EPA's monthly DMR totals): its own mark, never red or yellow
    "monthly": ("monthly", "Monthly report: days with discharge, dates not given"),
}

TYPE_LABEL = {"cso": "CSO", "sso": "Sewer overflow", "bypass": "Bypass", "blended": "Blended discharge",
              "plant_bypass": "Plant bypass", "beach_advisory": "Beach advisory", "beach_closure": "Beach closure",
              "hab_advisory": "Cyanobacteria advisory", "shellfish_closure": "Shellfish closure",
              "rain_advisory": "Rainfall advisory", "annual_total": "Annual total", "unknown": "Report"}

# Ingester source ids are short ("ma-massdep"); the registry rows are per endpoint. An events
# file's meta may name its rows ("registry_ids"); otherwise this table does.
REGISTRY_ALIASES = {
    "ma-massdep": ["ma-massdep-csoapi", "ma-massdep-sewage-notification-portal"],
    "vt-dec": ["vt-dec-sewage-overflow-public-alerts", "vt-dec-sewage-overflow-incident-reports", "vt-anr-sewage-overflows"],
    "ri-nbc": ["ri-nbc-cso-api-pins", "ri-nbc-cso-api-dryoverflows", "ri-nbc-cso-api-geopins"],
    "me-healthy-beaches": ["me-mhb-geojson-site", "me-mhb-geojson-bma", "me-mhb-status-history"],
    "ct-deep": ["ct-deep-cso-dashboard"],
    "ct-deep-cso": ["ct-deep-cso-dashboard"],
}
# Permits a feed reports for, when it is not statewide and its records do not show them all yet
# (events-file meta "covers_permits" / "covers_waters" / "statewide" take precedence).
FEED_PERMITS = {"ri-nbc": ["RI0100072", "RI0100315"]}

# Expected cadence (hours) when data/sources/<id>.yaml gives none; first match wins.
DEFAULT_CADENCE = [
    (r"echo", 7 * 24),
    (r"annual|report|status-report", 400 * 24),
    (r"beach|healthy|hab|cyano|shellfish|ridoh|ridem|dmr", 24),
    (r"^(ma|ct|vt|nh|ri|me|ny)-", 6),
    (r".", 24),
]


# ---------------------------------------------------------------- time

def parse_time(s, tz: ZoneInfo | None = None) -> datetime | None:
    """ISO 8601 to an aware UTC datetime. A naive time (or a bare date, read as its midnight) is local clock time in tz,
    the record's own zone (event_zone), else America/New_York (an ambiguous or skipped hour at a DST change takes the
    first reading), and is converted to UTC here, so every window below is added in absolute hours, never wall-clock."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz or LOCAL)
    return dt.astimezone(UTC)


def end_of_local_day(dt: datetime, tz: ZoneInfo | None = None) -> datetime:
    """The end of the calendar day containing dt in tz (the record's zone, event_zone; else America/New_York), in UTC
    (23 or 25 h days included)."""
    tz = tz or LOCAL
    d = dt.astimezone(tz).date() + timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(UTC)


@functools.lru_cache(maxsize=64)
def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError, OSError):
        return None


def event_zone(ev: dict, state: str | None = None) -> ZoneInfo:
    """The clock a record's bare dates and unzoned times are read in, and its calendar days end in (SOL 2026-11-07,
    wave 1 P1-2, wave 2 P1-1): raw.time_zone (an IANA name its ingester gives from the record's own point), else the
    zone of the record's state at its point (zones.zone_for: Florida, South Dakota and Nebraska by the point), the
    state from event_state, else the state the caller passes; America/New_York when neither is known."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    if isinstance(raw.get("time_zone"), str) and (z := _zone(raw["time_zone"])):
        return z
    name = zones.zone_for(event_state(ev) or state, ev.get("lat"), ev.get("lon"))
    return (_zone(name) if name else None) or LOCAL


def ev_time(ev: dict, key: str, state: str | None = None, tz: ZoneInfo | None = None) -> datetime | None:
    """parse_time of the record's field in the record's own zone (event_zone)."""
    v = ev.get(key)
    if not v:
        return None
    return parse_time(v, tz or event_zone(ev, state))


def end_precision(ev: dict) -> str | None:
    """The precision of the record's end: raw.ended_at_precision where the ingester gives the end its own (an exact
    end borrowed from another report, a lift seen at a poll: minute, hour, poll, bound), else time_precision. Only an
    end of day precision is counted to the end of its local day (SOL 2026-11-07, wave 1 P1-1, wave 2 P1-2)."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    return raw.get("ended_at_precision") or ev.get("time_precision")


# A start more than this far after the build's time is a source error (a NY SPRTK record published with a start of
# 2026-12-30): the record keeps its page and archive row, but sets no status, no reach and no colour, and is left
# out of the "latest report" and of counts of reports to date (coordinator, 2026-11-03)
FUTURE_START_H = 24


def future_start(ev: dict, now: datetime | None) -> str | None:
    """The validation note for a record whose start lies more than FUTURE_START_H hours after now, else None."""
    st = ev_time(ev, "started_at")
    if st is None or now is None or st <= now + timedelta(hours=FUTURE_START_H):
        return None
    return f"start is in the future as published (started_at {ev.get('started_at')}); it sets no status"


def end_limit_days(rules: dict | None) -> float | None:
    """unresolved.implausible_end.days_after_fetch in data/rules.json: how far after the report was read a published
    end may lie and still be quoted as the end of the window (None: no limit)."""
    v = (((rules or {}).get("unresolved") or {}).get("implausible_end") or {}).get("days_after_fetch")
    return float(v) if v is not None else None


def end_not_credible(ev: dict, now: datetime | None = None, rules: dict | None = None) -> str | None:
    """Why the published end is not quoted as the end of a colour window, or None. An end before the start, or (with
    now) a discharge's end more than unresolved.implausible_end.days_after_fetch days after the report was read
    (fetched_at, else the build time): most likely a typing error in the source (a 2036 for 2026), which would
    otherwise colour red for years (generic-ingesters re-check R6). The record then has no confirmed end: it follows
    the rules for records with none (docs/plan.md §2), and the published value stays in the record as given.
    Advisories keep their end, the authority's own (a seasonal shellfish closure may run for months), and so do
    month and year records (their end is the period's end; they set no window), and a planned bypass whose ingester
    labels its end as the operator's planned end (raw.end_is_planned: EPA's anticipated bypass notices)."""
    tz = event_zone(ev)
    en = ev_time(ev, "ended_at", tz=tz)
    if en is None:
        return None
    st = ev_time(ev, "started_at", tz=tz)
    if st and en < st:
        return f"ended_at {ev.get('ended_at')} is before started_at {ev.get('started_at')}; the end is ignored"
    if now is None or ev.get("event_type") in ADVISORY_TYPES or ev.get("status") in ("advisory_active", "advisory_lifted"):
        return None
    if (ev.get("raw") or {}).get("end_is_planned") is True:
        return None     # an operator's planned end of an anticipated bypass, labelled by its ingester (months ahead)
    if ev.get("event_type") == "annual_total" or ev.get("time_precision") in COARSE_PRECISION:
        return None     # a month or year record ends at the period's end by construction, and sets no window
    days = end_limit_days(load_rules() if rules is None else rules)
    if days is None:
        return None
    read = min(t for t in (ev_time(ev, "fetched_at", tz=tz), now) if t)
    if en <= read + timedelta(days=days):
        return None
    return (f"ended_at {ev.get('ended_at')} is more than {days:g} days after the report was read "
            f"({read.astimezone(LOCAL):%Y-%m-%d}); the end is not used and is treated as not confirmed")


def latest_observations(files: dict) -> dict[tuple, dict]:
    """{(source_id, permit, outfall key): {month, discharged, ...}}: each outfall's latest monthly observation as its
    collector saw it, explicit zero and "no discharge" months included (meta.latest_month_by_outfall, keyed
    "<permit>|<outfall>"); the events files keep only the months with a discharge."""
    out = {}
    for sid, f in (files or {}).items():
        for k, o in ((f.get("meta") or {}).get("latest_month_by_outfall") or {}).items():
            if not isinstance(o, dict) or not o.get("month"):
                continue
            permit, _, of = str(k).partition("|")
            out[(sid, permit or sid, oid_key(of) if of else None)] = o
    return out


def unresolved_days(rules: dict) -> float:
    return float(((rules or {}).get("unresolved") or {}).get("unresolved_yellow_days") or 30)


def end_assumed(ev: dict, now: datetime, rules: dict) -> datetime | None:
    """When the site assumes a discharge with no reported end ended (unresolved_yellow_days after it began), if
    that is past; None for a record with an end (or a bound), a month or year total, or an advisory."""
    et = ev.get("event_type")
    if not (et in DISCHARGE_TYPES or (et == "unknown" and ev.get("status") == "ongoing")):
        return None
    if ev.get("time_precision") in COARSE_PRECISION or (ev_time(ev, "ended_at") is not None
                                                        and not end_not_credible(ev, now, rules)):
        return None
    if ev.get("status") == "ended" and (ev.get("raw") or {}).get("_ended_before"):
        return None
    tz = event_zone(ev)
    begin = ev_time(ev, "started_at", tz=tz) or ev_time(ev, "reported_at", tz=tz) or ev_time(ev, "published_at", tz=tz)
    if begin is None:
        return None
    at = begin + timedelta(days=unresolved_days(rules))
    return at if at <= now else None


def month_of(ev: dict) -> tuple[datetime, datetime, str] | None:
    """(first instant, first instant of the next month, "YYYY-MM") of a month-precision record's month, local time."""
    t = parse_time(ev.get("started_at"))
    if t is None:
        return None
    loc = t.astimezone(LOCAL)
    start = datetime(loc.year, loc.month, 1, tzinfo=LOCAL)
    nxt = datetime(loc.year + (loc.month == 12), loc.month % 12 + 1, 1, tzinfo=LOCAL)
    return start.astimezone(UTC), nxt.astimezone(UTC), f"{loc.year:04d}-{loc.month:02d}"


def monthly_mark(ev: dict) -> dict | None:
    """The monthly mark of a month-precision discharge report (docs/plan.md §2.x), or None for any other record:
    {start, end, month, days, events, discharged, received_at, retrieved_at, label}. days: the days with discharge
    the report gives ("4 days with discharge in 2024-01"); events: its number of discharge events (EPA's CSO DMRs);
    discharged: False when the report says none (0 days, 0 events, 0 gallons), True when it says some or cannot be
    read (err on safety). received_at: when EPA (or the agency) received the report, None when the source does not
    say (the label then says the receipt date is not given); published_at and retrieved_at (the site's fetch time)
    are kept apart."""
    if ev.get("time_precision") != "month" or ev.get("event_type") not in DISCHARGE_TYPES:
        return None
    m = month_of(ev)
    if m is None:
        return None
    start, end, month = m
    text = str(ev.get("volume_text") or "")
    dm, em = DAYS_TEXT.search(text), EVENTS_TEXT.search(text)
    days = int(dm.group(1)) if dm else None
    events = int(em.group(1)) if em else None
    vol = ev.get("volume_gal") if isinstance(ev.get("volume_gal"), (int, float)) else None
    known = [x for x in (days, events, vol) if x is not None]
    discharged = not known or any(x > 0 for x in known)
    rt = parse_time(ev.get("reported_at"))       # when EPA (or the agency) received it; never our fetch time (SOL P1-5)
    when = f"{rt.astimezone(LOCAL):%b} {rt.astimezone(LOCAL).day}, {rt.astimezone(LOCAL).year}" if rt else None
    mtext = f"{start.astimezone(LOCAL):%B %Y}"
    if days is not None:
        what = f"{days} day{'' if days == 1 else 's'} with discharge reported for {mtext}"
    elif events is not None:
        what = f"{events} discharge event{'' if events == 1 else 's'} reported for {mtext}"
    else:
        what = f"discharge reported for {mtext}" + (f" ({text.strip()})" if text.strip() else "")
    to = "monthly report to EPA" if ev.get("source_id") in EPA_MONTHLY_SOURCES else "monthly report"
    label = f"{what[0].upper()}{what[1:]}; dates not given ({to}, {f'received {when}' if when else 'receipt date not given'})"
    return {"start": start, "end": end, "month": month, "days": days, "events": events, "discharged": discharged,
            "received_at": iso(rt) if rt else None, "published_at": ev.get("published_at"),
            "retrieved_at": ev.get("fetched_at"), "label": label}


def monthly_interval(ev: dict, mark: dict) -> dict:
    """The history interval of a monthly mark: the reported month, colour monthly, rule monthly."""
    iv = _iv(ev, mark["start"], mark["end"], "monthly")
    iv.update(days=mark["days"], events=mark["events"], month=mark["month"], received_at=mark["received_at"],
              retrieved_at=mark["retrieved_at"], monthly_label=mark["label"], placement=None)
    return iv


def time_problem(ev: dict, now: datetime | None = None, rules: dict | None = None) -> str | None:
    """A validation error in the record's times (an end before the start; with now, a start in the future or an end
    too far after the report was read: end_not_credible), else None."""
    out = []
    bad_end = end_not_credible(ev, now, rules)
    if bad_end:
        out.append(bad_end)
    fs = future_start(ev, now)
    if fs:
        out.append(fs)
    return "; ".join(out) or None


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cadence_hours(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    named = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 720, "yearly": 8760, "annually": 8760}
    if s in named:
        return float(named[s])
    m = re.match(r"(\d+(?:\.\d+)?)\s*(min|minute|minutes|h|hr|hrs|hour|hours|d|day|days|w|week|weeks)\b", s)
    if not m:
        return None   # "by hand" and the like: never stale
    n, u = float(m.group(1)), m.group(2)
    if u.startswith("min"):
        return n / 60
    if u.startswith("h"):
        return n
    if u.startswith("d"):
        return n * 24
    return n * 168


def default_cadence(source_id: str) -> float:
    for pat, h in DEFAULT_CADENCE:
        if re.search(pat, source_id):
            return float(h)
    return 24.0


# ---------------------------------------------------------------- inputs

def load_registry(sources_dir: Path = SOURCES_DIR) -> dict[str, dict]:
    reg = {}
    if not sources_dir.exists():
        return reg
    try:
        import yaml
    except ImportError:
        return reg
    for p in sorted(sources_dir.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except Exception as e:  # a half-written file from another builder must not stop the build
            reg[p.stem] = {"id": p.stem, "_error": f"unreadable yaml: {e}"}
            continue
        if isinstance(d, dict):
            reg[d.get("id") or p.stem] = d
    return reg


WITHHELD: list[str] = []      # files left out by the last load_events (distribution discouraged)


def canonical_dischargers(events: list[dict], aliases: dict[str, str]) -> list[dict]:
    """The events with each registry alias in discharger_id replaced by the row's id (a new dict; the old id in
    discharger_id_source, as export.build.canonicalize_events writes it)."""
    out = []
    for ev in events:
        did = ev.get("discharger_id")
        canon = aliases.get(did) if isinstance(did, str) else None
        out.append({**ev, "discharger_id": canon, "discharger_id_source": did} if canon and canon != did else ev)
    return out


NOT_LIVE: list[str] = []      # (source id, state) of the records left out by the last load_events with `live` given
_US_CODES = frozenset("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
                      "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP".split())


def _state_of_any(r: dict, sid: str) -> str | None:
    """A record's state whether or not that state is live (event_state knows the live states only): the record's
    raw.state, its state field, then the two-letter prefix of its source id or event id when that is a US code."""
    raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
    for v in (raw.get("state"), r.get("state")):
        if isinstance(v, str) and v.strip()[:2].upper() in _US_CODES:
            return v.strip()[:2].upper()
    for v in (sid, r.get("event_id")):
        if isinstance(v, str) and len(v) > 2 and v[2] in "-:_" and v[:2].upper() in _US_CODES:
            return v[:2].upper()
    return None


def load_events(events_dir: Path = EVENTS_DIR, include_fixtures: bool = False, include_restricted: bool = False,
                live: set[str] | None = None):
    """(files, events, problems): files = {source_id: file header + fixture flag}; events carry
    `_fixture` and `_file`. A file whose meta has distribution_discouraged true (NHDES Healthy
    Swimming) is left out unless include_restricted (--include-nhdes; owner's decision pending).
    `live`: the states the site publishes (rules.json live_states): a record whose state (event_state) is another
    state is left out, so that no water of a live state takes its colour or its history from a report the export
    will not carry (2026-11-07: Alabama's ingester, merged before Alabama went live, placed one of its reports on
    the Chattahoochee and Walter F George Reservoir on the Georgia side; the pages then counted "Record not found"
    and the publish failed the wording scan). None (tests, batches, audits with a scratch rules file) keeps every
    state's records as before."""
    files, events, problems = {}, [], []
    WITHHELD.clear()
    NOT_LIVE.clear()
    live_up = {str(x).upper() for x in live} if live is not None else None
    for p in sorted(events_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception as e:
            problems.append(f"{p.name}: unreadable ({e})")
            continue
        if not isinstance(d, dict) or "records" not in d:
            problems.append(f"{p.name}: not an events file")
            continue
        fixture = bool((d.get("meta") or {}).get("fixture")) or p.stem.startswith("fixture-")
        if fixture and not include_fixtures:
            continue
        if (d.get("meta") or {}).get("distribution_discouraged") and not include_restricted:
            WITHHELD.append(d.get("source_id") or p.stem)
            continue
        sid = d.get("source_id") or p.stem
        files[sid] = {k: d.get(k) for k in ("source_id", "fetched_at", "ok", "error", "last_ok_at", "meta", "count")}
        files[sid].update(source_id=sid, fixture=fixture, file=p.name, records=len(d.get("records") or []))
        for r in d.get("records") or []:
            if not isinstance(r, dict) or not r.get("event_id"):
                problems.append(f"{p.name}: record without event_id")
                continue
            r = dict(r)
            r["_fixture"] = fixture
            r["_file"] = p.name
            r.setdefault("source_id", sid)
            if live_up is not None:
                st = event_state(r) or _state_of_any(r, sid)
                if st and st not in live_up:
                    NOT_LIVE.append((sid, st))
                    continue
            events.append(r)
    return files, events, problems


# read last, in this order, tagged extra: OSM receiving waters, DC's NHD waters (ingest/dc_waters.py), the NHD
# receiving waters (ingest/waters_from_nhd.py)
EXTRA_WATER_FILES = ("waters-extra.json", "waters-dc.json", "waters-nhd.json")
# regional openboatlaunch files (the six New England states' records in one file, as of 2026-11-01): below the state
# extracts (load_waters; review 2026-11-07 P2-1)
REGIONAL_WATER_FILES = ("waters-new-england.json",)

# Aliases written by hand, {water slug: [alias text, ...]}, merged into the records' own aliases at load. The
# water files are rewritten by their generators (ingest/waters_from_nhd.py, ingest/md_waters.py, ...), so a
# hand alias kept on a record would be lost at the next run; this file is nobody's output. (Not matched by
# the data/waters-*.json glob.)
WATER_ALIASES_FILE = "water-aliases.json"
ALIAS_PROBLEMS: list[str] = []      # build problems of the last full load_waters' alias merge (build() reports them)
# {old slug: record slug} from the records' slug_aliases (ingest/waters_from_nhd.py merges one feature written under
# two slugs into the newer one and lists the older there; review 2026-11-03 P2-1), as of the last load_waters
SLUG_ALIASES: dict[str, str] = {}


def slug_aliases(waters: dict[str, dict]) -> dict[str, str]:
    """{old slug: the record's slug} for every slug_aliases entry that is not itself a record."""
    return {a: s for s, w in waters.items() for a in (w.get("slug_aliases") or []) if isinstance(a, str) and a not in waters}


def apply_water_aliases(waters: dict[str, dict], path: Path, moved: dict[str, str] | None = None) -> list[str]:
    """Merge the hand aliases of `path` into the matching records of `waters` (in place: the record is replaced
    by a copy whose aliases are its own followed by the hand ones it lacks). Returns the problems, as text: an
    unreadable or malformed file, a slug that is no water record (its aliases are not applied), a value that is
    not a list of texts. Never raises."""
    name = f"data/{path.name}"
    try:
        d = read_json(path)
    except Exception as e:                  # a half-written file must not stop the build
        return [f"{name}: unreadable ({type(e).__name__}: {e})"[:300]]
    if d is None:
        return []
    if not isinstance(d, dict):
        return [f"{name}: not an object of {{water slug: [alias texts]}}"]
    problems = []
    for slug, texts in d.items():
        if not isinstance(texts, list):
            problems.append(f"{name}: {slug}: the aliases are not a list of texts")
            continue
        slug = slug if slug in waters else (moved or {}).get(slug, slug)       # a slug merged into another record
        w = waters.get(slug)
        if w is None:
            problems.append(f"{name}: {slug} is not a water record ({len(texts)} alias(es) not applied)")
            continue
        have = list(w.get("aliases") or [])
        for t in texts:
            if isinstance(t, str) and t.strip() and t not in have:
                have.append(t)
        waters[slug] = {**w, "aliases": have}
    return problems


def load_waters(include_nhd: bool = True) -> dict[str, dict]:
    """openboatlaunch's water records (data/waters-ne.json, then any other data/waters-*.json),
    data/waters-extra.json (receiving waters with no openboatlaunch record, from OSM, same shape,
    geometry inline), data/waters-dc.json (DC's waters from NHD) and data/waters-nhd.json (receiving
    waters from NHDPlus, ingest/waters_from_nhd.py; include_nhd=False leaves it out). Records of these
    carry `extra: true`; a slug already known keeps its first record. The hand aliases of
    data/water-aliases.json are merged into the records' aliases last (apply_water_aliases); the problems
    of that merge (a slug with no record) are left in ALIAS_PROBLEMS for build(), except for include_nhd=False,
    where the NHD records they may name are not loaded."""
    waters = {}
    state_files = sorted(p for p in DATA_DIR.glob("waters-*.json")
                         if p.name != "waters-ne.json" and p.name not in EXTRA_WATER_FILES + REGIONAL_WATER_FILES)
    # a regional file comes after the state extracts: a state's own extract wins where both carry a slug (its
    # renames and changes take effect), and a regional record of a state that has its own extract is not loaded
    # (a slug openboatlaunch renamed stays an alias, not a record); the regional record's other fields are kept
    paths = [DATA_DIR / "waters-ne.json"] + state_files + [DATA_DIR / n for n in REGIONAL_WATER_FILES]
    paths += [DATA_DIR / n for n in EXTRA_WATER_FILES if include_nhd or n != "waters-nhd.json"]
    own = set()
    for p in state_files:
        m = re.fullmatch(r"waters-([a-z]{2})\.json", p.name)
        if m:
            own.add(m.group(1).upper())
    for path in paths:
        try:
            d = read_json(path)
        except Exception:
            continue          # a half-written file from another builder must not stop the build
        if not d:
            continue
        rows = d.get("waters", []) if isinstance(d, dict) else d
        for w in rows:
            if not isinstance(w, dict) or not w.get("slug"):
                continue
            if path.name in EXTRA_WATER_FILES:
                w = {**w, "extra": True}
            if path.name in REGIONAL_WATER_FILES:
                have = waters.get(w["slug"])
                if have is not None:
                    waters[w["slug"]] = {**w, **have}      # the state extract's fields win, the regional extras stay
                    continue
                if str(w.get("state") or "").upper() in own:
                    continue
            kept = waters.setdefault(w["slug"], w)
            if kept is not w and w.get("slug_aliases"):
                # the same slug in a later file (a state extract beside the regional New England file): the slugs
                # openboatlaunch renamed or merged into it still resolve (ingest.obl_waters, ingest.obl_changes)
                have = list(kept.get("slug_aliases") or [])
                waters[w["slug"]] = {**kept, "slug_aliases": have + [a for a in w["slug_aliases"] if a not in have]}
    moved = slug_aliases(waters)
    SLUG_ALIASES.clear()
    SLUG_ALIASES.update(moved)
    problems = apply_water_aliases(waters, DATA_DIR / WATER_ALIASES_FILE, moved)
    ALIAS_PROBLEMS[:] = problems if include_nhd else []
    return waters


def load_outfalls() -> list[dict]:
    """The whole outfall registry (common.load_outfall_registry: every data/outfalls-*.json, once per permit and
    outfall number, each row with outfall_kind and country, and the provisional records from the reports with
    record_status), national: coverage, the rain caution and the export keep the live states (states()) where it
    matters. Until 2026-11-03 this read data/outfalls-ne.json only."""
    return [{k: v for k, v in o.items() if k != "_file"} for o in load_outfall_registry(DATA_DIR)]


def load_registry_outfalls(provisional: bool = False) -> list[dict]:
    """Every outfall of the registry (common.load_outfall_registry over data/outfalls-*.json), each a copy tagged
    with its file (`_file`), for placement (permit + outfall -> receiving water and water slug). A half-written
    file from another builder is skipped (common.OUTFALL_REGISTRY_SKIPPED) and must not stop the build. The
    provisional records built from the reports themselves (data/build/outfalls-reported.json) are left out unless
    asked for: a report is never placed by a point derived from the reports."""
    return load_outfall_registry(DATA_DIR, provisional=provisional)


def outfall_state(o: dict) -> str:
    """A registry row's state: its own, else its permit's first two letters."""
    return str(o.get("state") or str(o.get("npdes_permit") or "")[:2]).upper()


def live_outfalls(rows: list[dict] | None = None, live: set[str] | None = None) -> list[dict]:
    """The registry rows in the live states: the states the site covers (states(), the one list the state pages,
    placement and the export use), so a national row (data/outfalls-us.json, outfalls-plants-us.json) reaches no
    public output before its state goes live, and comes with it when it does."""
    live = states() if live is None else live
    return [o for o in (load_outfalls() if rows is None else rows) if outfall_state(o) in live]


_GEOM_CACHE: dict[str, object] = {}


def water_geometry(slug: str, waters: dict | None = None):
    """The water's shapely geometry from openboatlaunch's out/water/<slug>.json (or an inline
    geometry in a waters-extra record); None when there is none."""
    if slug in _GEOM_CACHE:
        return _GEOM_CACHE[slug]
    from shapely.geometry import shape
    g = None
    w = (waters or {}).get(slug) or {}
    try:
        if w.get("geometry"):
            g = shape(w["geometry"])
        else:
            p = OBL_WATER_DIR / f"{slug}.json"
            if p.exists():
                d = json.loads(p.read_text())
                if d.get("geometry"):
                    g = shape(d["geometry"])
    except Exception:
        g = None
    _GEOM_CACHE[slug] = g
    return g


OUTLINE_SHARE_MIN = 0.5        # a live state whose records have outlines here for less than this share is a problem


def outline_coverage(waters: dict) -> dict:
    """{state: {"records", "with_outline", "openboatlaunch", "openboatlaunch_with_outline"}} for the records the build
    places on: an outline is an inline geometry (NHD, Census, OSM and hand records) or openboatlaunch's
    out/water/<slug>.json in OBL_WATER_DIR (the hourly run restores state/obl-water.tar.gz there). The placement guard
    measures a name match against the outline; a record with none keeps a name match anywhere in its state (only its
    town list can set it aside), so a state with few outlines here is placed less carefully (FL review of 2026-11-04,
    P2-6). Only file existence is checked: nothing is read."""
    out: dict[str, dict] = {}
    have_dir = OBL_WATER_DIR.is_dir()
    for slug, w in waters.items():
        st = str(w.get("state") or "").upper()
        c = out.setdefault(st, {"records": 0, "with_outline": 0, "openboatlaunch": 0, "openboatlaunch_with_outline": 0})
        c["records"] += 1
        obl = not w.get("extra") and not w.get("geometry")
        has = bool(w.get("geometry")) or (have_dir and (OBL_WATER_DIR / f"{slug}.json").is_file())
        c["with_outline"] += has
        if obl:
            c["openboatlaunch"] += 1
            c["openboatlaunch_with_outline"] += has
    return dict(sorted(out.items()))


def outline_problems(cov: dict) -> list[str]:
    """A problem line per state whose water records mostly have no outline here."""
    out = []
    for st, c in cov.items():
        if c["records"] and c["with_outline"] < OUTLINE_SHARE_MIN * c["records"]:
            out.append(f"{st}: {c['with_outline']} of {c['records']} water records have an outline here "
                       f"({c['openboatlaunch_with_outline']} of {c['openboatlaunch']} openboatlaunch records: their "
                       "outlines were not available to this run): a name match on a record with no outline is not "
                       "measured against the water")
    return out


# ---------------------------------------------------------------- placement

ABBREV = {"r": "river", "riv": "river", "bk": "brook", "brk": "brook", "hbr": "harbor", "harbour": "harbor",
          "pd": "pond", "lk": "lake", "chan": "channel", "ck": "creek", "cr": "creek", "st": "saint", "mt": "mount"}
KIND_WORDS = {"river", "brook", "creek", "stream", "lake", "pond", "reservoir", "harbor", "bay", "cove"}


@functools.lru_cache(maxsize=200_000)       # pure; called millions of times by reach_waters
def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("'", ""))
    return " ".join(ABBREV.get(t, t) for t in s.split())


def norm_oid(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def oid_key(s):
    m = re.search(r"(\d+)([A-Z]?)$", norm_oid(s))
    return (int(m.group(1)), m.group(2)) if m else None


OUTFALL_NAME_ID = re.compile(r"^\s*([A-Z]{2,5}\d{2,4}[A-Z]?)\s*:")


def outfall_name_id(row: dict) -> str | None:
    """The outfall id a registry row's outfall name opens with (EPA's MWRA rows: 'MWR201: Cottage Farm'), or None."""
    m = OUTFALL_NAME_ID.match(str(row.get("outfall_name") or ""))
    return norm_oid(m.group(1)) if m else None


# States whose reports carry an island (raw.island) and no point: a name resolves only to a record on that island
ISLAND_STATES = {"HI"}


def water_island(w: dict) -> str | None:
    """The island (ingest.hi_doh_cwb_events.ISLANDS key) a Hawaii water record lies on, from its box's centre; None
    without a box or off every island's box."""
    from ingest import hi_doh_cwb_events as HI
    b = w.get("bbox")
    if not (isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)):
        return None
    for k in HI.ISLANDS:
        if HI.on_island(w, k):
            return k
    return None


def record_point(slug: str, waters: dict) -> tuple[float, float, str] | None:
    """(lat, lon, basis) of a point on the water record itself: a point inside its outline or on its line (shapely
    representative_point), else its box's centre; None without either."""
    g = water_geometry(slug, waters)
    if g is not None and not g.is_empty:
        p = g.representative_point()
        return round(p.y, 5), round(p.x, 5), "a point on the water record's own outline"
    b = (waters.get(slug) or {}).get("bbox")
    if isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b):
        return round((b[1] + b[3]) / 2, 5), round((b[0] + b[2]) / 2, 5), "the centre of the water record's box"
    return None


RECORD_POINT_WHY = ("the report gives no point: the marker is on the water it names, at a point of that water's record, "
                    "not where the discharge or advisory was")


def island_slugs(slugs: list, ev: dict, waters: dict) -> tuple[list, str | None]:
    """(the slugs on the report's island, why others were set aside). A report with no island keeps them all."""
    from ingest import hi_doh_cwb_events as HI
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    isl = HI.key(raw.get("island") or "").replace(" ", "")
    if isl not in HI.ISLANDS:
        return list(slugs), None
    kept = [x for x in slugs if water_island(waters.get(x) or {}) == isl]
    off = [x for x in slugs if x not in kept]
    if not off:
        return kept, None
    return kept, (f"the record(s) of that name ({', '.join(off)}) do not lie on {HI.ISLANDS[isl][0]}, the report's "
                  "island (or have no box to show it)")


# States whose reports carry a point and whose name placement is county-aware (Alabama, final audit 2026-11-07 P2-2): a
# name resolves only to a record whose box, padded by NAME_MATCH_M, reaches the county the report's own point lies in,
# unless the point is within NAME_MATCH_M of the record. ADEM's layers give no county, so the county is the one whose
# outline (data/reference/al-counties.json, Census TIGERweb) holds the point. A record with no outline cannot be
# measured from a point; its box still places it in a county ("Cowan Creek" in Fairhope is not Ferguson's).
COUNTY_STATES = {"AL": "al-counties.json", "TX": "tx-counties.json"}
COUNTY_STATES["TN"] = "tn-counties.json"       # Tennessee: TDEC's HAB layer gives points and names (no county field)
# States whose reports give no point but their county as a field (Texas, final audit 2026-11-07 P1-2: TCEQ's table gives
# raw.county, "Lubbock County"): the report's county is that field, matched by name to the outline file's county; the
# rest of the rule is Alabama's. A report with neither keeps every slug (nothing to judge by).
COUNTY_FIELD_STATES = {"TX"}
COUNTY_FIELD_STATES.add("TN")    # Tennessee: TDEC's posted streams and Events Report give the county, no point
_COUNTIES: dict[str, list] = {}
_RECORD_COUNTIES: dict[tuple, frozenset] = {}


def state_counties(state: str) -> list:
    """[(geoid, name, shapely geometry)] of a COUNTY_STATES state ([] without the file)."""
    if state not in _COUNTIES:
        from shapely.geometry import shape
        path = DATA_DIR / "reference" / COUNTY_STATES[state]
        doc = read_json(path, {}) or {}
        _COUNTIES[state] = [(c["geoid"], c["county"], shape(c["geometry"])) for c in doc.get("counties") or []]
    return _COUNTIES[state]


def point_county(state: str, lat, lon) -> tuple[str, str] | None:
    """(geoid, name) of the county holding the point, or None."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    p = Point(float(lon), float(lat))
    for geoid, name, g in state_counties(state):
        if g.covers(p):
            return geoid, name
    return None


def named_county(state: str, name) -> tuple[str, str] | None:
    """(geoid, name) of the county a report's own county field names ("Lubbock County", "LUBBOCK"), or None."""
    n = re.sub(r"\s+county$", "", str(name or "").strip(), flags=re.I).lower().replace(".", "")
    if not n:
        return None
    for geoid, cname, _ in state_counties(state):
        if cname.lower().replace(".", "") in (n, f"{n} county") or re.sub(r"\s+county$", "", cname.lower()) == n:
            return geoid, cname
    return None


def record_counties(state: str, w: dict) -> frozenset:
    """The geoids of the counties a record's box, padded by NAME_MATCH_M, reaches (empty without a box)."""
    b = w.get("bbox")
    if not (isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b)):
        return frozenset()
    key = (state, tuple(b))
    if key not in _RECORD_COUNTIES:
        from shapely.geometry import box
        pad = NAME_MATCH_M / 111_000
        bx = box(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
        _RECORD_COUNTIES[key] = frozenset(g for g, _, geom in state_counties(state) if geom.intersects(bx))
    return _RECORD_COUNTIES[key]


def county_slugs(slugs: list, ev: dict, waters: dict, distance) -> tuple[list, str | None]:
    """(the slugs a report's county allows, why others were set aside). A slug within NAME_MATCH_M of the point stays,
    and so does a record with no box (nothing to judge it by); a report with no point, or a point in no county, keeps
    them all."""
    state = event_state(ev) or ""
    if state not in COUNTY_STATES:
        return list(slugs), None
    lat, lon = ev.get("lat"), ev.get("lon")
    here = point_county(state, lat, lon)
    field = False
    if here is None and state in COUNTY_FIELD_STATES:
        here = named_county(state, (ev.get("raw") or {}).get("county"))
        field = here is not None
    if here is None:
        return list(slugs), None
    kept, off = [], []
    for x in slugs:
        d = distance(x, lat, lon) if lat is not None and lon is not None else None
        rc = record_counties(state, waters.get(x) or {})
        if (d is not None and d <= NAME_MATCH_M) or not rc or here[0] in rc:     # no box: nothing to judge by
            kept.append(x)
        else:
            off.append(x)
    if not off:
        return kept, None
    return kept, (f"the record(s) of that name ({', '.join(off)}) do not reach {here[1]}, the county "
                  + ("the report gives" if field else "of the report's point"))


NAMED_ONLY_NONE = ("the report names no water; its source gives no location, so it is listed with its county and placed "
                   "on no water (never on its permit's outfalls' water)")


def named_water_only(ev: dict) -> bool:
    """Whether the record's source places it only on the water it names (raw._placement "named_water_only")."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    return raw.get("_placement") == "named_water_only"


def event_state(ev: dict) -> str | None:
    """The state a report counts under: the record's own two-letter raw.state first (an overflow outside its
    permit's state: DC Water's Potomac Interceptor rows in Montgomery County carry raw.state MD with
    raw.state_basis, docs/decisions.md Washington DC item 3, review 2026-11-03 P1-2), then the permit's prefix,
    any other raw.state, the event id's or source's prefix, and the state of its first water slug."""
    known = states()
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    own = raw.get("state").strip().upper() if isinstance(raw.get("state"), str) else ""
    if len(own) == 2 and own in known:
        return own
    # the permit's prefix: an individual permit ("SD0023574") or a general permit's or a state series', whose one or
    # two letters after the state name the series ("SDG821580", "ILG640063", "GAU020000", "NHG580001", and in EPA's
    # overflow tables Rhode Island's sewer systems "RISS00024" and Georgia's "GAIS12148"); without them the report had
    # no state, so it was not placed by name, not counted and not coloured (SD final audit 2026-11-07, review P1-1)
    m = re.match(r"([A-Z]{2})[A-Z]{0,2}\d", str(ev.get("npdes_permit") or ""))
    if m and m.group(1) in known:
        return m.group(1)
    if isinstance(raw.get("state"), str) and raw["state"][:2].upper() in known:
        return raw["state"][:2].upper()
    for s in (str(ev.get("event_id") or "").split(":", 1)[-1], str(ev.get("source_id") or "")):
        m = re.match(r"(?:fixture-)?([a-z]{2})-", s)
        if m and m.group(1).upper() in known:
            return m.group(1).upper()
    for slug in ev.get("water_slugs") or []:
        st = slug.rsplit("-", 1)[-1].upper()
        if st in known:
            return st
    return None


TOWN_KEYS = ("municipality", "Municipality", "CSO_TOWN", "REPORTING_TOWN", "CSO Town", "Town", "City/Town",
             "Town_name", "town", "city")


def norm_town(t) -> str:
    t = re.sub(r"\(.*?\)", " ", str(t or "").lower())
    t = re.sub(r"^(town|city|village|borough) of ", "", t.strip())
    t = re.sub(r"[^a-z ]", " ", t)
    return re.sub(r"\s+(town|city)$", "", re.sub(r"\s+", " ", t).strip())


# A consolidated city-county as the Census names its county subdivision ('Augusta-Richmond County consolidated
# government (balance)', 'Athens-Clarke County unified government (balance)', 'Macon-Bibb County',
# 'Louisville/Jefferson County metro government (balance)'): the city's own name, which the operator registry and the
# reports give ('Augusta'), is the same town (2026-11-04 GA final audit P1-1: Augusta Utilities' Butler Creek reports
# could not choose between the Butler Creek at Augusta and the one at Kennesaw)
CONSOLIDATED_TOWN = re.compile(r"^(?P<seat>[a-z][a-z .']*?)\s*[-/]\s*[a-z][a-z .']*?\s+county\b", re.I)


def water_town_keys(towns) -> set[str]:
    """norm_town of each of a water record's towns, and the city's own name for a consolidated city-county."""
    out = set()
    for t in towns or []:
        out.add(norm_town(t))
        m = CONSOLIDATED_TOWN.match(str(t or "").strip())
        if m:
            out.add(norm_town(m.group("seat")))
    out.discard("")
    return out


def discharger_rows() -> list[dict]:
    """The operator registry's rows (data/dischargers.json)."""
    d = read_json(DATA_DIR / "dischargers.json") or {}
    rows = d.get("dischargers", d) if isinstance(d, dict) else d
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def discharger_aliases(rows: list[dict] | None = None) -> dict[str, str]:
    """{alias: registry id} (common.discharger_alias_map over data/dischargers.json): the ids the ingesters stamp on
    events that the registry lists under another row (review 2026-11-03 P2-3)."""
    return discharger_alias_map(discharger_rows() if rows is None else rows)


def _row_keys(r: dict, aliases_of: dict) -> list:
    """The keys a registry row is found by: its id, its permits and the aliases that map to it."""
    return [r.get("id"), r.get("npdes_permit")] + list(r.get("npdes_permits") or []) + aliases_of.get(r.get("id"), [])


def _aliases_by_row(rows: list[dict]) -> dict[str, list[str]]:
    out = defaultdict(list)
    for a, rid in discharger_aliases(rows).items():
        out[rid].append(a)
    return out


def load_discharger_towns() -> dict:
    """npdes permit, discharger id or a registry alias of it -> the discharger's towns (data/dischargers.json)."""
    rows = discharger_rows()
    aliases_of = _aliases_by_row(rows)
    out = {}
    for r in rows:
        towns = [x for x in (r.get("towns") or []) if x]
        if not towns:
            continue
        for key in _row_keys(r, aliases_of):
            if key:
                out.setdefault(key, towns)
    return out


def load_discharger_waters() -> dict:
    """npdes permit or discharger id -> {id, state, names, slugs}: the operator's listed receiving waters
    (data/dischargers.json receiving_waters, research notes in parentheses dropped, and water_slugs)."""
    rows = discharger_rows()
    aliases_of = _aliases_by_row(rows)
    out = {}
    for r in rows:
        names = [re.sub(r"\s*\(.*?\)\s*", " ", str(x)).strip() for x in (r.get("receiving_waters") or []) if x]
        names = list(dict.fromkeys(x for x in names if x))
        if not names and not r.get("water_slugs"):
            continue
        row = {"id": r.get("id"), "state": r.get("state"), "names": names, "slugs": list(r.get("water_slugs") or [])}
        for key in _row_keys(r, aliases_of):
            if key:
                out.setdefault(key, row)
    return out


# ---------------------------------------------------------------- reports that name no receiving water
# Maryland decision 3 (docs/decisions.md) and its like in every state: a report whose receiving water is
# "none", "N/A", the ground or a storm drain, or whose source says the discharge did not reach a water,
# is kept as a record (state tables, operator pages, CSV) but colours no water and gets no reach. Such a
# report is "no receiving water", not "unplaced". A text with a water word ("unnamed tributary",
# "wetland", "Atlantic Ocean") names a water that has no record: unplaced. Beach, HAB, shellfish and
# rain advisories always name a site on some water: never in this class.
WATER_WORD = re.compile(r"\b(rivers?|brooks?|creeks?|streams?|runs?|kills?|lakes?|ponds?|reservoirs?|bays?|harbou?rs?|"
                        r"coves?|inlets?|canals?|channels?|branch|sounds?|lagoons?|marsh|swamps?|tributary|tributaries|"
                        r"trib|wetlands?|marshy|ocean|sea|falls|forks?|estuary|springs?|millpond|gut|narrows|flowage|"
                        r"riv|l i s)\b", re.I)
# "... leading to L.I.S.", "... and ultimately Little Patuxent", "drains (possibly) into Potapsco": a named
# destination after a storm drain or ditch is a receiving water, even one with no water word
DESTINATION = re.compile(r"\b(?:leading|leads|drains|drain(?:s|ing)? to|discharges?|flows|flowing|ultimately|"
                         r"outfalls?|outlets?|tributary)\b[^.;]{0,40}?\b(?:[A-Z][a-z]{3,}|[A-Z]\.?[A-Z]\.?[A-Z])")
NO_WATER_PLACEHOLDER = re.compile(
    r"^(n ?/ ?a|n a|na|n|a|no|none|nope|nil|null|unknown|unk|tbd|tbc|not applicable|not known|unknown at this time|"
    r"select|waterbody name|receiving waterbody|receiving water|other|x|0|-+|none known|no water|no waters|"
    r"no waterbody|no receiving water)$", re.I)
NO_WATER_PHRASE = re.compile(
    r"\b(did ?n[o']?t|does ?n[o']?t|do not|never|no discharge)\s+(enter|reach|go|get|impact|flow|make it)|"
    r"\bnot (reach|enter)|\bno (surface )?waters?\b|\bno waterways?\b|\bno waterbod(y|ies)\b|"
    r"\bground\b|\bgroundwater\b|\bstorm ?(drains?|sewers?|water system|water inlets?|drop inlets?|system)\b|"
    r"\bcatch ?basins?\b|\bms4\b|\bbasements?\b|\blawns?\b|\byards?\b|\bsoil\b|\bgrass\b|\bpavement\b|"
    r"\bparking\b|\bdry ?wells?\b|\bsurface only\b|\bcontained\b|\bswales?\b|\bland\b|\bstreet\b|\broad(way)?\b|"
    r"^(drainage |nearby |road ?side |side |storm |a |the )?ditch(es| line)?\b|"
    r"\b(drainage|nearby|road ?side|side|storm|a|the|in|to|into|of) ditch(es| line)?\b", re.I)
NO_WATER_EXEMPT_TYPES = {"beach_advisory", "beach_closure", "hab_advisory", "shellfish_closure", "rain_advisory"}
REACH_FLAG_KEYS = ("Reach Waterbody", "Reach Waterbody?", "REACH_WATER_BODY")


def norm_text(text) -> str:
    t = re.sub(r"[.!,;:?…*\"]+", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def placeholder_text(text) -> bool:
    """A receiving-water text that is only a placeholder ("N/A", "None.", "Select...", "unknown")."""
    t = norm_text(text)
    return bool(t) and bool(NO_WATER_PLACEHOLDER.match(t))


def no_water_text(text) -> str | None:
    """Why a receiving-water text names no water (a placeholder, the ground, a storm drain, "did not
    reach"), or None when it may name one (any water word) or is empty."""
    t = norm_text(text)
    if not t or WATER_WORD.search(t) or DESTINATION.search(str(text)):
        return None
    shown = str(text).strip()[:60]
    if NO_WATER_PLACEHOLDER.match(t):
        return f"the report gives no receiving water ('{shown}')"
    if NO_WATER_PHRASE.search(t):
        return f"the report names no water, only '{shown}'"
    return None


def no_water_flag(ev: dict) -> str | None:
    """The source's own statement that the discharge reached no water, or None."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    for k in REACH_FLAG_KEYS:
        v = raw.get(k)
        if isinstance(v, str) and v.strip().lower() == "no":
            return f"the report says the discharge did not reach a waterbody ({k}: No)"
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    if str(row.get("surfaceWater") or "").strip().lower() == "no":
        return "the notifier says the discharge did not reach surface water (surfaceWater: No)"
    if raw.get("reached_water") is False:
        # a feed that reads "reached no water" from the words (Washington's area text) says why in _no_water_reason
        why = raw.get("_no_water_reason")
        return why if isinstance(why, str) and why else "the report says the discharge did not reach a water"
    rep = raw.get("report") if isinstance(raw.get("report"), dict) else {}
    if rep.get("water_threatened") == "N":
        return "the report says no water was impacted or threatened (isImpactThreatWaterbody: N)"
    why = str((raw.get("_water") or {}).get("why_none") or "") if isinstance(raw.get("_water"), dict) else ""
    if "did not reach" in why:
        return "the report says the discharge did not reach a water"
    if "decision 3" in why:                     # Maryland: "none", "N/A", the ground, a storm drain or blank
        m = re.search(r"given as (.*?): no surface water", why)
        given = m.group(1) if m and m.group(1) not in ("''", '""') else None
        return f"the report names no surface water (receiving water given as {given})" if given else \
            "the report names no surface water (receiving water left blank)"
    return None


def no_receiving_water(ev: dict, mentions_water=None) -> str | None:
    """Why a report that no water was placed for names no receiving water (docs/plan.md §2), or None.
    mentions_water(text): whether the text carries a known water's name (Resolver.mentions_water)."""
    if ev.get("event_type") in NO_WATER_EXEMPT_TYPES:
        return None
    flag = no_water_flag(ev)
    if flag:
        return flag
    why = no_water_text(ev.get("waterbody_text"))
    if why and mentions_water and mentions_water(ev.get("waterbody_text")):
        return None
    return why


# A report whose receiving-water text says the discharge reached no water, even when it names one ("the discharge
# did not reach Middle Patuxent River", "Loch Raven Reservoir (nearest body of water). Did not enter body of water.",
# "No liquid was determined to have entered into the James River"): review 2026-11-03 P1-3. NO_WATER_PHRASE (above)
# reads such a text only when it names no water; these phrases are read whatever it names:
#   did not / didn't / does not / has not / was not ... reach, enter, go, get, flow, make it, impact, threaten,
#     affect, leave, discharge, run (also "did not appear to reach", "did not seem to enter")
#   never reached / entered / made it / flowed / got / went
#   not reaching / not entering / not going into / not flowing into / not reach / not enter; "but not into"
#   was / were / is / are not impacted, affected, threatened; a text opening "Not impacted"; "(NOT affected"
#   no sewage / liquid / wastewater / discharge / overflow / spill / flow / release / water / effluent ... entered,
#     reached, flowed, went, impacted, affected (within the sentence); "no discharge to", "no spill into"
#   no impact(s) / exposure to / on ...; a text opening "No impact"
#   no waterway(s) / water body / surface water(s) / stream(s) ... impacted, affected, involved, entered, reached;
#     a text that is only "No waterway" (after an "N/A")
#   contained: "was contained", "fully contained", "SSO contained", "contained on site / to / within / in", a text
#     opening "Contained" (after an "N/A") -- never "not contained" or "uncontained"
#   not near a water body / stream / creek / river (opening the text)
# A text that also says the discharge did reach a water ("did reach a tributary", "went into a stream", "flowed into
# Bear Creek" with no negation before it in its sentence) or that is unsure ("not sure if", "not clear whether",
# "possibly", "may have") is not such a statement: it stays where the name or point puts it (err on safety).
STATED_NO_WATER = [re.compile(p, re.I) for p in (
    r"\b(?:did|does|do|has|have|had|was|were)\s*(?:n[o']?t|n't)\s+(?:appear\s+to\s+|seem\s+to\s+|been\s+)?"
    r"(?:reach|enter|go|get|flow|make\s+it|impact|threaten|affect|leave|discharge|run)\w*",
    r"\bnever\s+(?:reach|enter|ma[dk]e\s+it|flow|got|went)\w*",
    r"\bnot\s+(?:reaching|entering|going\s+(?:in)?to|flowing\s+(?:in)?to|reach|enter)\b|\bbut\s+not\s+(?:in)?to\b",
    r"\b(?:was|were|is|are|been)\s+not\s+(?:impacted|affected|threatened)\b|^\W*not\s+(?:impacted|affected)\b|"
    r"\(\s*not\s+affected\b",
    r"\bno\s+(?:sewage|liquid|wastewater|discharge|overflow|spill|flow|release|water|effluent)\b[^.;]{0,60}?"
    r"\b(?:entered|enter|entering|reached|reach|reaching|flowed|went|impacted|affected)\b|"
    r"\bno\s+(?:discharge|spill|release|overflow|flow)\s+(?:in)?to\b",
    r"\bno\s+(?:impacts?|exposure)\s+(?:to|on)\b|^\W*no\s+impacts?\b",
    r"\bno\s+(?:surface\s+)?(?:waterways?|water\s*ways|water\s*bod(?:y|ies)|waters?|streams?)\b[^.;]{0,30}?"
    r"\b(?:impacted|affected|involved|invoived|exposure|entered|reached)\b|"
    r"^\W*(?:n\s*/?\s*a\W+)?no\s+(?:surface\s+)?(?:waterways?|water\s*bod(?:y|ies)|waters?|receiving\s+waters?)\W*$",
    r"\b(?:was|were|is|are|been|being|fully|completely|totally|all|remained|stayed|kept|currently|and|it|sso|spill|"
    r"overflow|bypass|discharge|sewage|release)\s+contained\b|^\W*(?:n\s*/?\s*a\W+)?contained\b|"
    r"(?<!un)\bcontained\s+(?:on|to|within|in|at|by|onsite|on-site)\b",
    r"^\W*not\s+near\s+(?:a|any)\s+(?:water|stream|creek|river|brook)",
)]
NOT_CONTAINED = re.compile(r"\b(?:not|n't|never)\s+(?:\w+\s+)?contained\b|\buncontained\b", re.I)
UNSURE_REACH = re.compile(r"\bnot\s+(?:sure|clear|positive|certain|known)\s+(?:if|whether|how|that|where)\b|\bunsure\b|"
                          r"\bunclear\b|\buncertain\b|\bpossibly\b|\bmay\s+have\b|\bmight\s+have\b|\bwhether\s+or\s+not\b",
                          re.I)
DID_REACH = re.compile(r"\b(?:entered|enters|entering|reached|reaches|reaching|impacted|affected)\s+(?:an?\s+|the\s+)?"
                       r"(?:[\w'’-]+\s+){0,3}?(?:streams?|creeks?|rivers?|brooks?|run|branch|tributary|ponds?|lakes?|bay|"
                       r"cove|harbou?r|waterways?|wetlands?|marsh|reservoir|falls|sound|inlet)\b|"   # "sewage entered Bear Creek"
                       r"\b(?:did|does)\s+(?:reach|enter|go\s+into|flow\s+into)\b|"
                       r"\b(?:went|go(?:es|ing)?|flow(?:ed|s|ing)?|ran|runs|drain(?:ed|s|ing)?|discharg(?:ed|es|ing)|spill(?:ed|s|ing)|"
                       r"overflow(?:ed|s|ing)|poured|washed|seeped|emptied|released|enter(?:ed|s|ing)|reached)\s+(?:in)?to\s+"
                       r"(?:an?\s+|the\s+)?(?:[\w'’-]+\s+){0,3}?(?:streams?|creeks?|rivers?|brooks?|run|branch|tributary|"
                       r"ponds?|lakes?|bay|cove|harbou?r|waterways?|wetlands?|marsh)\b", re.I)
QUOTE_CHARS = 160                   # a statement is quoted this long (build/redact.QUOTE_LENGTHS holds it)


def quote_text(text, n: int) -> str:
    """A record's free text as a note quotes it: stripped and cut to n characters (the export swaps a quote of a
    redacted field for its redacted form by these cuts: build/redact.quote_swaps)."""
    return str(text or "").strip()[:n]


CLAUSE_SPLIT = re.compile(r"[.;\n]+")


def clauses(text) -> list[str]:
    """The clauses of a text (split at full stops, semicolons and line breaks)."""
    return [c.strip() for c in CLAUSE_SPLIT.split(str(text or "")) if c.strip()]


def _reached_in(clause: str) -> bool:
    """Whether a clause says the discharge did reach a water (DID_REACH with no negation before it in the clause)."""
    return any(not re.search(r"\b(?:no|not|never)\b|n't", clause[:m.start()], re.I) for m in DID_REACH.finditer(clause))


def _no_water_in(clause: str) -> bool:
    for rx in STATED_NO_WATER:
        for m in rx.finditer(clause):
            if "contain" in m.group(0).lower() and NOT_CONTAINED.search(clause[max(0, m.start() - 20):m.end()]):
                continue
            return True
    return False


def negated_clauses(text) -> list[str]:
    """The clauses that say the discharge reached no water ("Did not impact Middle Patuxent River"), unsure ones out;
    a clause that also says it reached a water is not one (review 2026-11-03 SOL P1-2: negation scoped to its clause)."""
    if UNSURE_REACH.search(str(text or "")):
        return []
    return [c for c in clauses(text) if _no_water_in(c) and not _reached_in(c)]


def stated_no_water(text) -> str | None:
    """The phrase of a receiving-water text that says the discharge reached no water (STATED_NO_WATER), or None:
    also None when the text says it did reach one (DID_REACH, not negated within its sentence) or is unsure."""
    t = str(text or "")
    if not t.strip() or UNSURE_REACH.search(t):
        return None
    if any(_reached_in(c) for c in clauses(t)):     # "...; sewage entered Bear Creek": it did reach a water
        return None
    for rx in STATED_NO_WATER:
        for m in rx.finditer(t):
            if "contain" in m.group(0).lower() and NOT_CONTAINED.search(t[max(0, m.start() - 20):m.end()]):
                continue
            return m.group(0).strip()
    return None


def reached_no_water(ev: dict) -> tuple[str, str | None] | None:
    """(reason, quoted statement) when the source says the discharge reached no water: its own flag (no_water_flag:
    "Reach Waterbody: No", surfaceWater No, isImpactThreatWaterbody N, Maryland decision 3 ...) or its receiving-water
    text (stated_no_water). The statement is the receiving-water text as the note quotes it, None when only the flag
    says so. None for advisories (their water field names a site) and when neither says so."""
    if ev.get("event_type") in NO_WATER_EXEMPT_TYPES:
        return None
    text = ev.get("waterbody_text")
    said = stated_no_water(text)
    statement = quote_text(text, QUOTE_CHARS) if said else None
    flag = no_water_flag(ev)
    if flag:
        return flag, statement
    if said:
        return "the report says the discharge reached no water", statement
    return None


OUTFALL_LIKE = re.compile(r"^(?:CSO|OUTFALL|OUTLET|DSN|OF)?\s*#?\s*-?\s*(\d{1,4}[A-Z]?)$", re.I)
OUTFALL_STREET = re.compile(r"^(\d{1,4})\s+[A-Za-z]{3,10}$")           # Bridgeport's "33 HUNT", "87 ANTH"
OUTFALL_STREET_AFTER = re.compile(r"^[A-Z]{3,6}\s+(\d{1,3})$")          # Bridgeport East's "WANN 153", "BAYEL 6"
OUTFALL_GROUP = re.compile(r"\bCSOs?\s*:?\s*((?:\d{3}[A-Z]?\s*,?\s*(?:and\s+)?)+)$", re.I)  # "Mill River CSOs: 009,011,012"


def outfall_ids_from_name(name) -> list[str]:
    """Outfall numbers a CSO record gives as its outfall name: "017", "CSO 017", "33 HUNT" (the number and
    a street), "WANN 153" (a street and the number), "New Haven Harbor CSOs: 021, 024, 025"; [] for anything
    else (a street address)."""
    t = str(name or "").strip()
    for rx in (OUTFALL_LIKE, OUTFALL_STREET, OUTFALL_STREET_AFTER):
        m = rx.match(t)
        if m:
            return [m.group(1)]
    m = OUTFALL_GROUP.search(t)
    return re.findall(r"\d{3}[A-Z]?", m.group(1)) if m else []


# Greater New Haven's per-outfall volume string on the CT DEEP dashboard, its only outfall field in 2026 (CSO
# Group Name and Receiving Waterbody are blank): "003-0.197 MG 2005 to 2145004-0.023 MG 2015 to 2040",
# "015-No release016-No release", "021-0.289 MG 2010 to 2050024-No data025-No release", once after the rainfall
# ("0.7 in Rain021-No release024-No release"). Each outfall number is followed by a dash and "No release",
# "No data" or a volume in MG (the end time before it runs into the next number). A binned range
# ("500 - 1,000 gallons") is not one.
VOLUME_OUTFALL = re.compile(r"(\d{3})\s*-\s*(?=no\b|n/?a\b|data\b|active\b|unknown\b|\d*\.?\d+\s*mg\b|\d{3,4}\s*to\b)", re.I)
NO_RELEASE_PART = re.compile(r"^no\s*release\b", re.I)
RAIN_PREFIX = re.compile(r"^\s*\d*\.?\d+\s*(?:in(?:ches)?\.?|\")\s*(?:of\s*)?rain\s*", re.I)
ALL_NO_RELEASE = re.compile(r"(?:\s*\d{3}\s*-\s*no\s*release\s*[,;.]?)+\s*", re.I)
# a whole volume or water text saying nothing was released: "No release", "0, No release", "0.0 mgd no release",
# "No Overflow", "0 Did not overflow", "Zero gallons", "NO SPILL - Change of conveyance", "N/A - No spill"
NO_RELEASE_TEXT = re.compile(
    r"(?:n/?a\s*[-–:]\s*)?(?:0(?:\.0+)?\s*(?:mgd|mg|gal(?:lons?)?)?\s*[,;-]?\s*)?"
    r"(?:no\s*release|no\s*overflow|no\s*discharge|no\s*spill|did\s*not\s*(?:overflow|discharge|release|spill)|"
    r"zero(?:\s*gallons?)?)\s*[.!]?\s*(?:[-–(].*)?", re.I)
# a qualifier that says the "no release" reading cannot be trusted ("NO OVERFLOW - INSTRUMENTATION ISSUES"): such a
# report is treated as released, as "No data" is (review 2026-11-03 P3-2)
UNRELIABLE_READING = re.compile(r"\b(?:instrument\w*|meters?|metering|gauges?|sensors?|probes?|offline|off-line|"
                                r"malfunction\w*|not\s+working|fail(?:ed|ure|ing)?|errors?|faults?|pending|unknown|"
                                r"unavailable|no\s+data|telemetry|communication\w*|outage|scada|estimate\s+pending|"
                                r"unverified|not\s+verified|unconfirmed|not\s+confirmed|under\s+review|investigat\w*)\b",
                                re.I)
VOLUME_OUTFALL_KEYS = ("Final Volume", "CSO Estimated Volume")
PLANT_OUTFALL = re.compile(r"^\s*(\d{3}(?:-\d{1,2})?)\s+-\s+\S")        # CT DEEP "002-1 - Norwalk 5 Day Report"


def volume_outfall_parts(text) -> list[tuple[str, str]]:
    """[(outfall number, what the string says for it)] of a per-outfall volume string, in order: "015-0.279 MG
    1950 to 2050016-No release" -> [("015", "0.279 MG 1950 to 2050"), ("016", "No release")]."""
    t = str(text or "")
    ms = list(VOLUME_OUTFALL.finditer(t))
    return [(m.group(1), t[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(t)].strip()) for i, m in enumerate(ms)]


def outfall_ids_from_volume(text) -> list[str]:
    """The outfall numbers of a per-outfall volume string (VOLUME_OUTFALL), in order; [] for any other text."""
    return list(dict.fromkeys(o for o, _ in volume_outfall_parts(text)))


def no_release(ev: dict) -> str | None:
    """Why a discharge report says nothing was released, or None: its volume text gives "No release" for every
    outfall it lists (after a rainfall note), or its volume or water text is only a no-release statement
    (NO_RELEASE_TEXT). Such a report is kept with its page but colours no water and gets no reach."""
    if ev.get("event_type") not in DISCHARGE_TYPES | {"unknown"}:
        return None
    vt = str(ev.get("volume_text") or "").strip()
    parts = volume_outfall_parts(vt)
    if parts and ALL_NO_RELEASE.fullmatch(RAIN_PREFIX.sub("", vt)):
        return f"the operator reported no release (at every outfall it lists: {', '.join(o for o, _ in parts)})"
    for t in (vt, ev.get("waterbody_text")):
        t = str(t or "").strip()
        if t and NO_RELEASE_TEXT.fullmatch(t) and not UNRELIABLE_READING.search(t):
            return f"the operator reported no release ('{t[:60]}')"
    return None


def outfall_ids_of(ev: dict) -> tuple[list[str], str]:
    """(the outfall ids a report names, where it names them): its outfall_id; else, for a CSO report, an outfall
    number given as its outfall name ("017", "33 HUNT", "WANN 153", "Mill River CSOs: 009, 011"), else the
    outfalls of its per-outfall volume string (CT DEEP dashboard, Greater New Haven); for a plant bypass, the
    plant outfall its CT DEEP report type names ("002-1 - Norwalk 5 Day Report"). ([], "") when it names none."""
    if ev.get("outfall_id") not in (None, ""):
        return [str(ev["outfall_id"])], "its outfall_id"
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    if ev.get("event_type") == "cso":
        ids = outfall_ids_from_name(ev.get("outfall_name"))
        if ids:
            return ids, f"its outfall name '{str(ev.get('outfall_name')).strip()[:40]}'"
        if PLACE_STEPS["outfall_ids"]:
            parts = []
            for k in VOLUME_OUTFALL_KEYS:              # the final volume when it lists outfalls, else the estimate
                parts = volume_outfall_parts(raw.get(k))
                if parts:
                    break
            ids = list(dict.fromkeys(o for o, _ in parts))
            quiet = [o for o in ids if all(NO_RELEASE_PART.match(x) for p, x in parts if p == o)] \
                if PLACE_STEPS["no_release"] else []
            released = [o for o in ids if o not in quiet]
            if released and quiet:                     # place only the outfalls that released (or gave no data)
                return released, f"its per-outfall volume text (no release at {', '.join(quiet)})"
            if ids:
                return ids, "its per-outfall volume text"
    elif ev.get("event_type") == "plant_bypass" and PLACE_STEPS["outfall_ids"]:
        m = PLANT_OUTFALL.match(str(raw.get("Report Type") or ""))
        if m:
            return [m.group(1)], "its report type"
    return [], ""


# Words that say what kind of water or structure a name is, not which water. Two names that share none of the
# other words name different waters ("Johnson's Creek", "Bruce Brook"; "Gully Brook Conduit", "Park River
# Conduit"); so do opposite compass words ("South Branch Park River Conduit", "North Branch Park River").
GENERIC_NAME_WORDS = KIND_WORDS | {"conduit", "storm", "drain", "via", "to", "the", "of", "and", "at", "branch", "aux",
                                   "auxiliary", "low", "level", "system", "sewer", "channel", "canal", "sound", "ocean",
                                   "tributary", "trib", "unnamed", "storage", "outlet", "inlet", "upper", "lower"}
COMPASS = {"north": "north", "n": "north", "no": "north", "south": "south", "s": "south", "so": "south",
           "east": "east", "e": "east", "west": "west", "w": "west"}


def names_disagree(text, water_name) -> str | None:
    """Why a receiving-water text and a water record's name name different waters, or None (either is empty,
    or nothing says so)."""
    a, b = norm_name(text or "").split(), norm_name(water_name or "").split()
    if not a or not b:
        return None
    da = {x for x in a if x not in GENERIC_NAME_WORDS and x not in COMPASS}
    db = {x for x in b if x not in GENERIC_NAME_WORDS and x not in COMPASS}
    if da and db and not da & db:
        return "no name word in common"
    ca, cb = {COMPASS[x] for x in a if x in COMPASS}, {COMPASS[x] for x in b if x in COMPASS}
    if ca and cb and not ca & cb:
        return "opposite compass words"
    return None


# Watershed labels (owner, 2026-11-03; PLACE_STEPS watershed_labels). A watershed or basin label names an area, not
# the water a discharge reached, and is never read as a water name (Resolver.watershed_labels): USGS HUC-12 names in
# EPA's inventory ('Outlet Saugus River-Frontal Broad Sound', 'Charles River-Frontal Boston Harbor'), MDE's basin
# labels ('Upper Potomac River', 'Potomac River - Allegany County'), and in a report's text "<name> watershed"
# ('NA (Gwynns Falls watershed)', 'Herring Run watershed'), "<stream> basin" (WSSC's sewer basins: 'Oxon Run Basin',
# 'Storm drain in Paint Branch Basin', 'Tinkers Creek in the Piscataway Basin', 'Basin 10'), "<stream> drainage" and
# "drainage basin". Not labels: a basin that is a water itself ('Paerdegat Basin', 'Atlantic Basin', 'Erie Basin':
# no stream word before it), a structure ('catch basin', 'detention basin'), a basin at a place on a water ('Otter
# Creek Basin below the falls'), and any water record's own name or alias ('Charles River Basin', MassDEP's and
# MWRA's name for the lower Charles: data/water-aliases.json). A text that is only a label is classed with the texts
# that hold no water name (no name matching; the registry, the point and the operator's waters may still place it);
# a text with a label and a water name is matched on the rest ('Dead Run, in the Gwynn Falls watershed': Dead Run).
HUC12_NAME = re.compile(r"^\s*outlet\s+.+-|.+-\s*frontal\s+.+", re.I)                 # as ingest/outfall_waters.HUC12
MDE_BASIN = re.compile(r"^\s*upper\s+potomac\s+river\s*$|\s+-\s+(?:alleg(?:h)?any|garrett|washington|frederick|"
                       r"montgomery)\s+county\s*$|^\s*potomac\s+river\s+(?:upper|middle|lower)\s+tidal\s*$", re.I)
_STREAM_WORDS = r"(?:rivers?|creeks?|runs?|branch(?:es)?|brooks?|falls|streams?|kills?)"
_AT_A_PLACE = r"(?!\s+(?:below|above|at|near|downstream|upstream)\b)"
LABEL_WORD = re.compile(
    r"\b(?P<w>(?:sub-?)?watersheds?)\b"
    rf"|\b{_STREAM_WORDS}\s+(?P<b>(?:sub-?)?basins?)\b{_AT_A_PLACE}"
    rf"|\b{_STREAM_WORDS}\s+(?P<d>drainage(?:\s+(?:basins?|areas?))?)\b(?!\s+(?:ditch|ditches|swale|swales|culvert|"
    r"pipes?|system|pond|structure|way|inlets?|line|location|catchment|network))"
    r"|\b(?P<s>sub-?basins?|drainage\s+basins?|basin\s+(?:no\.?\s*|#\s*)?\d+)\b",
    re.I)
IN_THE_BASIN = re.compile(rf"\b(?:in|within)\s+the\s+((?:[A-Z][\w'’.-]*\s+){{1,3}})(?P<b>[Bb]asin)\b{_AT_A_PLACE}")
LABEL_ANY = re.compile(r"watershed|basin|drainage|frontal|^\s*outlet\s|potomac", re.I)
# words that end the name before a label ('Storm drain in Paint Branch Basin': Paint Branch)
LABEL_STOP = {"in", "of", "the", "a", "an", "and", "or", "to", "into", "within", "near", "on", "at", "from", "is", "was",
              "storm", "drain", "drains", "catch", "stormwater", "unknown", "nearby", "closest", "nearest", "same",
              "this", "that", "its", "line", "feeding", "wetland", "wetlands", "area"}
LABEL_GLUE = {"in", "of", "the", "a", "an", "and", "or", "to", "into", "within", "near", "on", "at", "from", "is", "was"}


def bbox_extent_m(b) -> float | None:
    """The diagonal of a [west, south, east, north] box in metres."""
    if not b or len(b) != 4:
        return None
    lat = math.radians((b[1] + b[3]) / 2)
    return math.hypot((b[2] - b[0]) * 111_320 * math.cos(lat), (b[3] - b[1]) * 110_574)


def make_resolver(waters: dict | None = None) -> "Resolver":
    """The resolver build() uses, from the files on disk (charts, waters_from_nhd)."""
    return Resolver(load_waters() if waters is None else waters, load_registry_outfalls(), load_discharger_towns(),
                    load_discharger_waters(), load_rules().get("placement") or {})


class Resolver:
    def __init__(self, waters: dict, outfalls: list[dict], discharger_towns: dict | None = None,
                 discharger_waters: dict | None = None, placement_rules: dict | None = None):
        """placement_rules: data/rules.json "placement" (None: read it)."""
        self.waters = waters
        self.slug_alias = slug_aliases(waters)          # an older slug of a record -> the record (P2-1)
        pr = (load_rules().get("placement") or {}) if placement_rules is None else placement_rules
        self.no_outfall_all_waters = bool(pr.get("no_outfall_all_waters"))
        self.discharger_towns = discharger_towns or {}
        self.discharger_waters = discharger_waters or {}
        self.by_permit = defaultdict(list)
        for o in outfalls:
            if o.get("npdes_permit"):
                self.by_permit[o["npdes_permit"]].append(o)
        self._dist = {}
        self._row_water = {}
        self._labels = {}
        self.names = defaultdict(list)          # (state, norm name) -> [slugs]
        self.stems = defaultdict(list)          # (state, name without its kind word) -> [slugs]
        self.exact = defaultdict(list)          # (state, short alias) -> [slugs]: whole-text matches only
        for slug, w in waters.items():
            n = norm_name(w.get("name") or "")
            if n and (" " in n or len(n) >= 8):
                self.names[(w.get("state"), n)].append(slug)
            words = n.split()
            if len(words) >= 2 and words[-1] in KIND_WORDS and len(" ".join(words[:-1])) >= 6:
                self.stems[(w.get("state"), " ".join(words[:-1]))].append(slug)
            # aliases (data/waters-extra.json: "North Branch", "Mill R.", "Pine St Barge Canal"): a short
            # alias names the water only when it is the whole waterbody text; three words or more also
            # match inside a longer text, like a name
            for a in w.get("aliases") or []:
                an = norm_name(a)
                if not an:
                    continue
                if len(an.split()) >= 3:
                    if slug not in self.names[(w.get("state"), an)]:
                        self.names[(w.get("state"), an)].append(slug)
                elif slug not in self.exact[(w.get("state"), an)]:
                    self.exact[(w.get("state"), an)].append(slug)

    def outfall_rows(self, permit, oid) -> list[dict]:
        """The registry rows of the permit with that outfall number (exact, or the id its outfall name gives, then by
        its number). A row whose outfall name gives another id is not that outfall by number: MWRA's registry row
        C01 is 'MWR201: Cottage Farm', not Deer Island's T01, and C03 ('MWR203: Prison Point') is not MWR003."""
        rows = self.by_permit.get(permit) or []
        if not rows or oid in (None, ""):
            return []
        want = norm_oid(oid)
        hit = [r for r in rows if norm_oid(r.get("outfall")) == want or outfall_name_id(r) == want]
        if not hit and oid_key(oid) and not re.search(r"\d-\d", str(oid)):      # "002-1" is not outfall 021
            hit = [r for r in rows if oid_key(r.get("outfall")) == oid_key(oid) and outfall_name_id(r) in (None, want)]
        return hit

    def canon(self, slug):
        """A water slug, or the record it was merged into (slug_aliases)."""
        return self.slug_alias.get(slug, slug)

    def by_outfall(self, permit, oid):
        hit = self.outfall_rows(permit, oid)
        if len(hit) == 1 and self.canon(hit[0].get("water_slug")) in self.waters:
            return {**hit[0], "water_slug": self.canon(hit[0].get("water_slug"))}
        return None

    def nearest(self, slugs, lat, lon):
        if lat is None or lon is None:
            return None
        best = None
        for s in slugs:
            g = water_geometry(s, self.waters)
            if g is None:
                continue
            from shapely.geometry import Point
            d = g.distance(Point(lon, lat)) * 111_320
            if best is None or d < best[0]:
                best = (d, s)
        return best

    def event_towns(self, ev: dict) -> set[str]:
        """The discharger's towns (data/dischargers.json, by permit or discharger id) and the record's
        own municipality field."""
        towns = set()
        for key in (ev.get("npdes_permit"), ev.get("discharger_id")):
            towns |= {norm_town(t) for t in self.discharger_towns.get(key) or []}
        raw = ev.get("raw") or {}
        for k in TOWN_KEYS:
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                towns.add(norm_town(v))
        return {t for t in towns if t}

    def known_name(self, state, n: str) -> bool:
        """Whether a normalised name is a water record's name, alias or stem in the state."""
        key = (state, n)
        return bool(n) and (key in self.names or key in self.exact or key in self.stems)

    def _label_span(self, t: str, start: int, end: int, state) -> tuple[int, int] | None:
        """(start, end) of a watershed label whose label word runs from start to end, with the name before it (up to
        five words, back to punctuation or a LABEL_STOP word; the longest trailing run of them that is a water's name:
        'Stoney Run Jones Falls watershed' -> Jones Falls) and an "in the" before that. None when the name and the
        label word are a water record's own name or alias ('Charles River Basin')."""
        words, pos = [], start
        for wm in reversed(list(re.finditer(r"[A-Za-z][\w'’.]*", t[:start]))):
            gap = t[wm.end():pos]
            if len(words) >= 5 or re.search(r"[,;:()/&\[\]]|\s-\s|-\s|\.\s", gap) \
                    or wm.group(0).lower().strip(".") in LABEL_STOP:
                break
            words.insert(0, wm)
            pos = wm.start()
        for i in range(len(words)):
            if self.known_name(state, norm_name(t[words[i].start():words[-1].end()])):
                words = words[i:]
                break
        s = words[0].start() if words else start
        if self.known_name(state, norm_name(t[s:end])):
            return None
        if not words:                      # 'N/A (watershed is Dead Run, ...)': the name follows
            fm = re.match(r"\s*(?:is|=|:)\s*[^;()\[\]]+", t[end:])        # to the end of its bracket or clause
            if fm:
                end += fm.end()
        pm = re.search(r"\b(?:(?:in|of|into|within|on)\s+)?the\s+$|\b(?:in|of|within)\s+$", t[:s], re.I)
        return (pm.start() if pm else s), end

    def watershed_labels(self, text, state) -> tuple[str | None, list[str]]:
        """(the text without its watershed labels, [the labels]) (Watershed labels above): (None, [text]) when the
        whole text is a label, (text, []) when it holds none or PLACE_STEPS watershed_labels is off."""
        if not isinstance(text, str) or not text.strip() or not PLACE_STEPS["watershed_labels"]:
            return text, []
        key = (text, state)
        if key in self._labels:
            return self._labels[key]
        t = text.strip()
        if not LABEL_ANY.search(t):
            out = (text, [])
        elif HUC12_NAME.search(t) or MDE_BASIN.search(t):
            out = (None, [t])
        else:
            spans = []
            for m in LABEL_WORD.finditer(t):
                g = next(k for k in ("w", "b", "d", "s") if m.group(k))
                sp = self._label_span(t, m.start(g), m.end(), state) if g != "s" else (m.start(), m.end())
                if sp:
                    spans.append(sp)
            for m in IN_THE_BASIN.finditer(t):
                if not self.known_name(state, norm_name(m.group(1) + m.group("b"))):
                    spans.append((m.start(), m.end()))
            spans.sort()
            merged = []
            for a, b in spans:
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                else:
                    merged.append((a, b))
            if not merged:
                out = (text, [])
            else:
                labels = [t[a:b].strip() for a, b in merged]
                rest, last = [], 0
                for a, b in merged:
                    rest.append(t[last:a])
                    last = b
                rest.append(t[last:])
                rest = re.sub(r"[(\[]\s*[,;:.\-]*\s*[)\]]", " ", " ".join(rest))
                rest = re.sub(r"\s+", " ", rest).strip(" ,;:.-/")
                glue = [w for w in re.findall(r"[A-Za-z][\w'’]*", rest) if w.lower() not in LABEL_GLUE]
                out = (rest if glue else None, labels)
        self._labels[key] = out
        return out

    def by_name(self, text, state, lat, lon, ev: dict | None = None):
        """(slugs, note, ambiguous): waters of the state named in the text. A name several records share
        goes to the nearest of them when it lies within NAME_MATCH_M of the point; otherwise to the one
        whose towns hold the report's town; else the nearest (the guard then judges it). A watershed label in the
        text is not read (watershed_labels)."""
        if not text or not state:
            return [], None, False
        rest, labels = self.watershed_labels(text, state)
        if labels:
            if rest is None:
                return [], None, False
            text = rest
        nt = norm_name(re.sub(r"\(.*?\)", " ", str(text))) or norm_name(text)
        t = f" {norm_name(text)} "
        found = {}
        for (st, n), slugs in self.names.items():
            if st == state and f" {n} " in t:
                found[n] = slugs
        for key in ((state, norm_name(text)), (state, nt)):
            if key in self.exact:                                     # a short alias, the whole text
                found[key[1]] = list(dict.fromkeys(found.get(key[1], []) + self.exact[key]))
        if not found and (state, norm_name(text)) in self.stems:   # "Winooski" for the Winooski River
            found[norm_name(text)] = self.stems[(state, norm_name(text))]
        # drop names inside longer matched names ("mill river" in "north branch mill river")
        names = [n for n in found if not any(n != m and f" {n} " in f" {m} " for m in found)]
        out, notes, ambiguous = [], [], False
        for n in sorted(names):
            slugs = found[n]
            if state in ISLAND_STATES:
                # Hawaii's reports give an island, never a point: a name two islands share ("Kailua Bay" off Oahu and
                # off Kona) goes only to the record on the report's island (final audit 2026-11-07 P1-1)
                kept, why = island_slugs(slugs, ev or {}, self.waters)
                if why:
                    notes.append(f"'{n}': {why}")
                slugs = kept
                if not slugs:
                    continue
            if state in COUNTY_STATES:
                # Alabama: a name several counties share ("Cowan Creek" in Fairhope and near Ferguson) goes only to a
                # record reaching the county of the report's point (final audit 2026-11-07 P2-2)
                kept, why = county_slugs(slugs, {**(ev or {}), "lat": lat, "lon": lon,
                                                 "raw": {"state": state, **((ev or {}).get("raw") or {})}},
                                         self.waters, self.distance_m)
                if why:
                    notes.append(f"'{n}': {why}")
                slugs = kept
                if not slugs:
                    continue
            if len(slugs) == 1:
                out.append(slugs[0])
                continue
            near = self.nearest(slugs, lat, lon)
            towns = self.event_towns(ev or {})
            by_town = [x for x in slugs if towns & water_town_keys(self.waters[x].get("towns"))]
            if near and (near[0] <= NAME_MATCH_M or len(by_town) != 1 or not PLACE_STEPS["relaxed_guard"]):
                out.append(near[1])
                continue
            if len(by_town) == 1:
                out.append(by_town[0])
            else:
                ambiguous = True
                notes.append(f"'{n}' names {len(slugs)} waters in {state} ({', '.join(slugs)}); "
                             f"no point, and the discharger's towns do not pick one")
        return out, "; ".join(notes) or None, ambiguous

    def distance_m(self, slug, lat, lon):
        key = (slug, round(lat, 4), round(lon, 4))
        if key not in self._dist:
            near = self.nearest([slug], lat, lon)
            self._dist[key] = near[0] if near else None
        return self._dist[key]

    def name_limit_m(self, slug) -> tuple[float, str]:
        """(metres, basis): how far a named match may lie from the report's point, by the water's kind."""
        w = self.waters[slug]
        kind = w.get("kind")
        if kind in WIDE_KINDS:
            return WIDE_NAME_MATCH_M, f"{WIDE_NAME_MATCH_M / 1000:g} km for a bay or sound"
        if PLACE_STEPS["relaxed_guard"]:
            if kind in RIVER_KINDS:
                ext = bbox_extent_m(w.get("bbox"))
                if ext is None:
                    g = water_geometry(slug, self.waters)
                    ext = bbox_extent_m(list(g.bounds)) if g is not None else None
                if ext:
                    lim = max(NAME_MATCH_M, min(ext, RIVER_EXTENT_CAP_M) + NAME_MARGIN_M)
                    return lim, (f"the {kind} record's extent ({ext / 1000:.1f} km"
                                 f"{f', counted to {RIVER_EXTENT_CAP_M / 1000:g} km' if ext > RIVER_EXTENT_CAP_M else ''})"
                                 f" plus {NAME_MARGIN_M / 1000:g} km")
            if kind in WHOLE_WATER_KINDS:
                return LAKE_NAME_MATCH_M, f"the {kind}'s outline plus {LAKE_NAME_MATCH_M / 1000:g} km"
        return NAME_MATCH_M, f"{NAME_MATCH_M / 1000:g} km"

    def mentions_water(self, text, state) -> bool:
        """Whether the text carries the name of a water of the state, or its stem ("Little Patuxent"), outside its
        watershed labels."""
        rest, labels = self.watershed_labels(text, state)
        if labels and rest is None:
            return False
        t = f" {norm_name(rest if labels else text)} "
        return any(st == state and f" {n} " in t for (st, n) in list(self.names) + list(self.stems))

    def same_named(self, slug: str) -> list[str]:
        """The other records of the water's state that carry its name (an NHD remainder of a river, a
        same-named stream in another town)."""
        w = self.waters[slug]
        n = norm_name(w.get("name") or "")
        key = (w.get("state"), n)
        return [x for x in dict.fromkeys(self.names.get(key, []) + self.exact.get(key, [])) if x != slug]

    def town_conflict(self, ev: dict, slug: str) -> str | None:
        """When the report's towns are known (counties left out) and none is among the water's towns."""
        et = {t.replace(" ", "") for t in self.event_towns(ev) if not re.search(r"\bcounty\b", t)}
        wt = {t.replace(" ", "") for t in water_town_keys(self.waters[slug].get("towns"))}
        if et and wt and not et & wt:
            return (f"the report's town ({', '.join(sorted(et)[:3])}) is not among the water's towns "
                    f"({', '.join((self.waters[slug].get('towns') or [])[:4])})")
        return None

    def guard_detail(self, slugs, ev):
        """(kept, set_aside, relaxed) for name-based slugs: same state as the event; within NAME_MATCH_M
        (5 km for bays and sounds) of the event's point when it has one, or beyond that within the
        water's own reach (name_limit_m) when the report's town does not say it is another water.
        set_aside items are (slug, reason); relaxed maps a slug kept beyond NAME_MATCH_M to why."""
        state = event_state(ev)
        lat, lon = ev.get("lat"), ev.get("lon")
        kept, aside, notes = [], [], {}
        for slug in slugs:
            w = self.waters[slug]
            if state and w.get("state") and w["state"] != state:
                aside.append((slug, f"water in another state ({w['state']}, event {state})"))
                continue
            if lat is not None and lon is not None:
                d = self.distance_m(slug, lat, lon)
                tight = WIDE_NAME_MATCH_M if w.get("kind") in WIDE_KINDS else NAME_MATCH_M
                if d is not None and d > tight:
                    limit, basis = self.name_limit_m(slug)
                    if d > limit:
                        aside.append((slug, f"name match too far ({d / 1000:.1f} km; limit {limit / 1000:.1f} km: "
                                            f"{basis})"))
                        continue
                    conflict = self.town_conflict(ev, slug)
                    if conflict:
                        aside.append((slug, f"name match too far ({d / 1000:.1f} km) and {conflict}"))
                        continue
                    closer = [x for x in self.same_named(slug) if (self.distance_m(x, lat, lon) or 1e12) <= NAME_MATCH_M]
                    if closer:
                        aside.append((slug, f"name match too far ({d / 1000:.1f} km); a water of the same name "
                                            f"({closer[0]}) lies within {NAME_MATCH_M / 1000:g} km"))
                        continue
                    notes[slug] = (f"named in the report; the report's point is {d / 1000:.1f} km from {slug}, "
                                   f"within {basis}")
            kept.append(slug)
        return kept, aside, notes

    def guard(self, slugs, ev):
        """(kept, set_aside): guard_detail without its notes."""
        kept, aside, _ = self.guard_detail(slugs, ev)
        return kept, aside

    def by_point(self, lat, lon, state):
        if lat is None or lon is None:
            return None
        pad = 0.01
        cands = [s for s, w in self.waters.items()
                 if (state is None or w.get("state") == state) and w.get("bbox")
                 and w["bbox"][0] - pad <= lon <= w["bbox"][2] + pad and w["bbox"][1] - pad <= lat <= w["bbox"][3] + pad]
        near = self.nearest(cands, lat, lon)
        if near and near[0] <= GEOMETRY_MATCH_M:
            return near
        return None

    # ------------------------------------------------ reports that name no water: the outfall registry

    @staticmethod
    def registry_how(row: dict) -> str:
        """How the registry pass matched a row, for a placement note: its step (ingest.outfall_waters' water_match
        opens with it) or match_outfalls' match, the distance, and who matched it."""
        by = str(row.get("water_matched_by") or "outfall registry")
        wm = str(row.get("water_match") or "")
        step = wm.split(":", 1)[0].strip() if by.startswith("ingest.outfall_waters") and ":" in wm[:40] else \
            (row.get("match") or "registry")
        d = row.get("distance_m")
        return f"{step}, " + (f"{d} m from the point" if d is not None else "no point") + f"; {by}"

    def row_water(self, row) -> tuple[str | None, str]:
        """(slug, how) for one registry outfall. A row the registry pass matched (water_matched_by; PLACE_STEPS
        registry_first): its water_slug, or no water when the pass found none (no_water_reason). Otherwise its
        water_slug, else its receiving water's name in its state (checked against the outfall's own point by the
        guard), else the water at its point."""
        key = (row.get("_file"), row.get("npdes_permit"), row.get("outfall"), row.get("lat"), row.get("lon"))
        if key in self._row_water:
            return self._row_water[key]
        if PLACE_STEPS["registry_first"] and row.get("water_matched_by"):
            slug = self.canon(row.get("water_slug")) if row.get("water_slug") else None
            out = None
            if slug in self.waters:
                out = (slug, f"its registry water ({self.registry_how(row)})")
            elif not row.get("water_slug"):
                why = str(row.get("no_water_reason") or "").strip()
                out = (None, "the outfall registry gives it no water record" + (f" ({why[:160]})" if why else ""))
            if out:                         # a slug that is no record any more: read the row as before
                self._row_water[key] = out
                return out
        name = (row.get("receiving_water") or row.get("receiving_water_echo") or row.get("water_name") or "").strip()
        out = (None, f"no water for its receiving water '{name}'" if name else "no receiving water listed")
        permit = str(row.get("npdes_permit") or "")
        state = (row.get("state") or (permit[:2] if re.match(r"[A-Z]{2}\d", permit) else "") or "").upper()
        if name and self.watershed_labels(name, state)[0] is None:
            out = (None, f"its receiving water '{name}' is a watershed label, not a water name")
            name = ""
        fake = {"npdes_permit": permit, "lat": row.get("lat"), "lon": row.get("lon"), "waterbody_text": name,
                "raw": {"state": state, "town": row.get("city") or ""}}
        slug = self.canon(row.get("water_slug"))
        if slug in self.waters:
            # a slug matched by name only must carry the receiving water's name (the registry once matched
            # "Burr Creek" to Burr Pond), and any slug must pass the guard against the outfall's own point
            wn, rn = norm_name(self.waters[slug].get("name") or ""), norm_name(name)
            ok = row.get("match") not in ("name_only", "none", None) or not rn or f" {wn} " in f" {rn} " \
                or f" {rn} " in f" {wn} "
            if ok and self.guard_detail([slug], fake)[0]:
                dist = row.get("distance_m")
                out = (slug, f"its water slug, {row.get('match') or 'registry'} match"
                             + (f", {dist} m" if dist is not None else ""))
                self._row_water[key] = out
                return out
        if name:
            slugs, _, _ = self.by_name(name, state, row.get("lat"), row.get("lon"), fake)
            if len(slugs) == 1:
                kept, _, _ = self.guard_detail(slugs, fake)
                if kept:
                    out = (kept[0], f"its receiving water '{name}' by name")
        if out[0] is None and PLACE_STEPS["outfall_ids"]:
            near = self.by_point(row.get("lat"), row.get("lon"), state or None)
            if near and near[0] <= OUTFALL_POINT_M:
                wname = self.waters[near[1]].get("name")
                clash = names_disagree(name, wname)
                if clash:
                    out = (None, f"{out[1]}; the water at its point ({wname}, {round(near[0])} m) is not its "
                                 f"receiving water ({clash})")
                else:
                    out = (near[1], f"the water at its point ({round(near[0])} m"
                                    + (f"; no water record for its receiving water '{name}'" if name else "") + ")")
        self._row_water[key] = out
        return out

    def by_outfalls(self, permit, oids: list[str], where: str):
        """([slugs], "outfall_registry", note, outfalls) for the outfalls a report names, each to its registry row's
        water (row_water); outfalls on several waters place the report on each (PLACE_STEPS multi_outfall).
        (None, None, reason, []) when none of them has a water. outfalls: [{"outfall", "water_slug"}] of the
        registry rows used (build() looks up each one's cached reach)."""
        found, missing = [], []
        for o in oids:
            rows = self.outfall_rows(permit, o)
            if not rows:
                missing.append(o)
                continue
            got = [(r, *self.row_water(r)) for r in rows]
            found.append(next((g for g in got if g[1]), got[0]))
        placed = [(r, s, how) for r, s, how in found if s]
        tail = [f"outfall {r.get('outfall')}: {how}" for r, s, how in found if not s]
        if missing:
            tail.append(f"outfall{'s' if len(missing) > 1 else ''} {', '.join(missing)} not in the outfall registry")
        if not placed:
            return None, None, (f"no water placed from the report's own text, and its outfall"
                                f"{'s' if len(oids) > 1 else ''} of {permit} ({where}) "
                                f"{'have' if len(oids) > 1 else 'has'} no mapped water: " + "; ".join(tail)), []
        slugs = list(dict.fromkeys(s for _, s, _ in placed))
        if len(slugs) > 1 and not PLACE_STEPS["multi_outfall"]:
            return None, None, (f"the report names no water and its outfalls of {permit} ({where}) discharge to "
                                f"{len(slugs)} waters"), []
        ids = [r.get("outfall") for r, _, _ in placed]
        parts = []
        for s in slugs:
            mine = [(r, how) for r, x, how in placed if x == s]
            parts.append(f"{', '.join(r.get('outfall') for r, _ in mine)} to {self.waters[s].get('name')} ({mine[0][1]})")
        files = ", ".join(sorted({r.get("_file") or "outfall registry" for r, _, _ in placed}))
        note = (f"placed by outfall{'s' if len(ids) > 1 else ''} {', '.join(ids)} of permit {permit} (outfall registry): "
                + "; ".join(parts) + f"; from {where} ({files})"
                + (f"; one record on each of the {len(slugs)} waters its outfalls reach" if len(slugs) > 1 else "")
                + (f"; {'; '.join(tail)}" if tail else ""))
        return slugs, "outfall_registry", note, [{"outfall": r.get("outfall"), "water_slug": s} for r, s, _ in placed]

    def by_registry(self, ev: dict, state: str | None, names_none: bool = True):
        """For a report no water was placed for by its text or point: ([slugs], water_match, note, outfalls) from
        the outfall registry, or (None, None, reason, []). The outfalls the report names (outfall_ids_of: its
        outfall_id, an outfall number in its outfall name, a per-outfall volume string) -> their receiving waters,
        each of them when they reach several (by_outfalls). Only for a report that names no water at all
        (names_none): first the water its outfall group's label names; after the outfalls, every listed outfall of
        the permit discharging to one water; else, only for a permit the registry does not list, the operator's
        single receiving water in data/dischargers.json (weaker)."""
        permit = ev.get("npdes_permit")
        rows = (self.by_permit.get(permit) or []) if permit else []
        oname = str(ev.get("outfall_name") or "").strip()
        m = OUTFALL_GROUP.search(oname) if ev.get("event_type") == "cso" and names_none else None
        prefix = oname[:m.start()].strip(" :-") if m else ""
        if prefix:                          # "New Haven Harbor CSOs: 021, 024, 025": the group names its water
            slugs, _, _ = self.by_name(prefix, state, ev.get("lat"), ev.get("lon"), ev)
            if len(slugs) == 1:
                return slugs, "name", f"the water named in the report's outfall group ('{oname[:60]}')", []
        oids, where = outfall_ids_of(ev)
        outfall_reason = None
        if rows and oids:
            slugs, match, note, outs = self.by_outfalls(permit, oids, where)
            if slugs:
                return slugs, match, note, outs
            outfall_reason = note
        if not names_none:
            return None, None, outfall_reason, []
        if rows:
            got = [self.row_water(r) for r in rows]
            slugs = {s for s, _ in got if s}
            names = {norm_name(r.get("receiving_water") or r.get("receiving_water_echo") or r.get("water_name") or "")
                     for r in rows} - {""}
            if len(slugs) == 1 and (all(s for s, _ in got) or len(names) <= 1):
                slug = next(iter(slugs))
                files = ", ".join(sorted({r.get("_file") or "outfall registry" for r in rows}))
                return [slug], "inferred", (
                    f"water from the outfall registry ({files}): every listed outfall of {permit} ({len(rows)}) "
                    f"discharges to {self.waters[slug].get('name')}; the report names no outfall and no water"), []
            if outfall_reason:
                return None, None, outfall_reason, []
            if self.no_outfall_all_waters and not oids and ev.get("event_type") == "cso" and len(slugs) > 1:
                order = list(dict.fromkeys(s for s, _ in got if s))
                files = ", ".join(sorted({r.get("_file") or "outfall registry" for r in rows}))
                lost = sum(1 for s, _ in got if not s)
                return order, "inferred", (
                    f"{NO_OUTFALL_NOTE} ({len(order)} waters from the {len(rows)} registry outfalls of {permit}"
                    + (f"; {lost} of them have no water record" if lost else "") + f"; {files})"), \
                    [{"outfall": r.get("outfall"), "water_slug": s} for r, (s, _) in zip(rows, got) if s]
            n = len(slugs) if all(s for s, _ in got) else max(len(slugs), len(names))
            if n > 1:
                return None, None, (f"the report names no water and {permit}'s {len(rows)} registry outfalls "
                                    f"discharge to {n} waters"), []
            return None, None, f"the report names no water and {permit}'s registry outfalls have no mapped water", []
        d = self.discharger_waters.get(ev.get("discharger_id")) or (self.discharger_waters.get(permit) if permit else None)
        if not d:
            return None, None, "the report names no water and no outfall the registry lists", []
        known = [s for s in d["slugs"] if s in self.waters]
        # CSO reports only: a plant bypass leaves by the plant's own outfall, not by every water the operator lists
        if (len(d["names"]) > 1 or len(set(known)) > 1) and self.no_outfall_all_waters \
                and ev.get("event_type") == "cso":
            slugs = list(dict.fromkeys(known))
            for n in d["names"]:
                cands, _, _ = self.by_name(n, d.get("state") or state, ev.get("lat"), ev.get("lon"), ev)
                if len(cands) == 1 and cands[0] not in slugs:
                    slugs.append(cands[0])
            if len(slugs) > 1:
                return slugs, "inferred", (
                    ("outfall not in the outfall registry" if oids else "outfall not stated in the report")
                    + f"; shown on every water this operator's listed receiving waters reach ({len(slugs)} with a "
                      f"water record, data/dischargers.json)"), []
        if len(d["names"]) > 1 or len(set(known)) > 1:
            return None, None, (f"the report names no water and the operator lists "
                                f"{max(len(d['names']), len(set(known)))} receiving waters (data/dischargers.json)"), []
        slug = known[0] if known else None
        if slug is None and d["names"]:
            st = d.get("state") or state
            cands, _, _ = self.by_name(d["names"][0], st, ev.get("lat"), ev.get("lon"), ev)
            slug = cands[0] if len(cands) == 1 else None
        if slug is None:
            return None, None, (f"the report names no water and the operator's one receiving water "
                                f"({(d['names'] or ['-'])[0]}) has no water record"), []
        return [slug], "inferred", (
            f"water from data/dischargers.json: the operator's single listed receiving water "
            f"({d['names'][0] if d['names'] else self.waters[slug].get('name')}); weaker than the outfall registry: "
            f"the report names no water and no outfall"), []

    def registry_first(self, ev: dict, state: str | None, known: list[str], neg: set):
        """Registry first (PLACE_STEPS registry_first): ([slugs], note, outfalls) when the outfalls the report names
        (outfall_ids_of: its outfall_id, an outfall number in its outfall name, a per-outfall volume string) are rows
        of its permit in the outfall registry with a water (row_water); the registry's water then wins over name
        matching, the ingester's included. (None, note, []) when the report's own text names another water and
        REGISTRY_YIELDS_TO_NAMED_WATER: the named water stands, the note records the registry's. None when the
        registry has no water for its outfalls, or the ingester placed it by its own point."""
        permit = ev.get("npdes_permit")
        if not permit or not self.by_permit.get(permit):
            return None
        match = ev.get("water_match") or "inferred"
        if known and match not in GUARDED_MATCHES and match != "outfall_registry":
            return None
        # a report that says it reached no water (its flag) or whose text names none ('storm drain') is not overruled
        # by its outfall, as in by_registry; an empty or placeholder text of a CSO report is
        text = (ev.get("waterbody_text") or "").strip()
        if no_water_flag(ev) or (text and no_water_text(text)
                                 and not (placeholder_text(text) and ev.get("event_type") == "cso")):
            return None
        oids, where = outfall_ids_of(ev)
        if not oids:
            return None
        slugs, _, rnote, outs = self.by_outfalls(permit, oids, where)
        slugs = [s for s in slugs or [] if s not in neg]
        if not slugs:
            return None
        if REGISTRY_YIELDS_TO_NAMED_WATER:
            named = list(self.by_name(ev.get("waterbody_text"), state, ev.get("lat"), ev.get("lon"), ev)[0])
            oname = str(ev.get("outfall_name") or "").strip()
            gm = OUTFALL_GROUP.search(oname) if ev.get("event_type") == "cso" else None
            if gm and oname[:gm.start()].strip(" :-"):       # "New Haven Harbor CSOs: 021, 024, 025" names its water
                named += self.by_name(oname[:gm.start()].strip(" :-"), state, ev.get("lat"), ev.get("lon"), ev)[0]
            if match in GUARDED_MATCHES:
                named += [s for s in known if s not in named]
            named = [s for s in named if s not in neg]
            named = self.guard_detail(named, ev)[0] if named else []
            if named and not set(named) & set(slugs) and all(
                    names_disagree(self.waters[a].get("name"), self.waters[b].get("name"))
                    for a in named for b in slugs):
                return None, (f"the outfall registry gives outfall{'s' if len(oids) > 1 else ''} {', '.join(oids)} of "
                              f"{permit} {', '.join(str(self.waters[s].get('name') or s) for s in slugs)}; not used, "
                              f"the report names another water"), []
        return slugs, rnote, [o for o in outs if o["water_slug"] in slugs]

    def negated_waters(self, text, state, ev: dict) -> set[str]:
        """The waters the text's negated clauses name ("did not reach Middle Patuxent River"), less any a clause
        saying the discharge did reach a water names."""
        if not text:
            return set()
        neg = set()
        for c in negated_clauses(text):
            neg.update(self.by_name(c, state, ev.get("lat"), ev.get("lon"), ev)[0])
        for c in clauses(text):
            if _reached_in(c):
                neg -= set(self.by_name(c, state, ev.get("lat"), ev.get("lon"), ev)[0])
        return neg

    def placed_elsewhere(self, ev: dict, known: list[str], neg: set) -> bool:
        """Whether the report is explicitly placed on a water its negation does not name: a water the ingester gave
        it, or its outfall's in the registry."""
        if any(s not in neg for s in known):
            return True
        o = self.by_outfall(ev.get("npdes_permit"), ev.get("outfall_id"))
        return bool(o and o["water_slug"] not in neg)

    def named_in(self, ev: dict, state: str | None) -> tuple[list[str], str | None]:
        """([slugs], note) for a report that reached no water (reached_no_water): the waters its text names (kept
        by the guard), else the water at its point; listed in the note only, never placed."""
        slugs, _, _ = self.by_name(ev.get("waterbody_text"), state, ev.get("lat"), ev.get("lon"), ev)
        kept = self.guard_detail(slugs, ev)[0] if slugs else []
        if kept:
            return kept, ("water named in the report, not placed: "
                          + ", ".join(str(self.waters[s].get("name") or s) for s in kept))
        near = self.by_point(ev.get("lat"), ev.get("lon"), state)
        if near:
            return [near[1]], (f"water nearest the report's point, not placed: "
                               f"{self.waters[near[1]].get('name') or near[1]} ({round(near[0])} m)")
        return [], None

    def resolve(self, ev: dict) -> dict:
        out = self._resolve(ev)
        if text_over_flag(ev):
            # the water comes from the notice's text against its form's flag: the placement says so (TEXT_OVER_FLAG)
            raw = ev.get("raw") or {}
            basis = str(raw.get("_reached_water_basis") or TEXT_OVER_FLAG_NOTE)
            out["text_over_flag"] = basis
            # the words of the notice that place it, quoted (cite everything): 'its description says "may have
            # entered the nearby Example Bayou"; its form answered ...'
            words = str(raw.get("_reached_water_words") or "").strip()
            said = (f"the notice's description says \"{words}\"; " + basis.split("; ", 1)[1]
                    if words and "; " in basis else basis)
            out["note"] = "; ".join(x for x in (said, out.get("note")) if x)
        return out

    @staticmethod
    def place_elsewhere(ev: dict) -> str | None:
        """Why a record is not placed here: its raw.state (with raw.state_basis, the evidence) names a state other than
        the one it counts under (event_state), which happens only when that state is not shown (event_state reads a
        live raw.state first). Nebraska's Beach Watch station on Lake Yankton, South Dakota (ingest/ne_transforms.py
        OUT_OF_STATE_STATIONS) is the case: before, its point fell to the Missouri River in Nebraska, 319 m away."""
        raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
        own = str(raw.get("state") or "").strip().upper()
        if len(own) != 2 or not raw.get("state_basis"):
            return None
        counted = event_state(ev)
        if counted is None or counted == own:
            return None
        county = f"{raw['county']}, " if raw.get("county") else ""
        return (f"the report's place lies in {county}{own}, a state this site does not show yet: not placed on a "
                f"water of {counted}")

    def _resolve(self, ev: dict) -> dict:
        given = list(dict.fromkeys(self.canon(s) for s in ev.get("water_slugs") or []))
        known = [s for s in given if s in self.waters]
        unknown = [s for s in given if s not in self.waters]
        note = f"slugs not in the water records: {', '.join(unknown)}" if unknown else None
        aside = []
        if PLACE_STEPS["no_release"]:
            nr = no_release(ev)
            if nr:                  # kept, with its page; colours nothing, no reach (counted with no_receiving_water)
                return {"water_slugs": [], "water_match": "none", "note": None, "unknown_slugs": unknown,
                        "no_receiving_water": nr, "no_release": True}
        elsewhere = self.place_elsewhere(ev)
        if elsewhere:
            # the record says its place lies in a state the site does not show: never placed on a water of the state
            # it is counted under (a name of that state, or the nearest water to the point across the line)
            return {"water_slugs": [], "water_match": "none", "note": None, "unknown_slugs": unknown,
                    "unplaced_reason": elsewhere}
        text0 = ev.get("waterbody_text")
        if isinstance(text0, str) and text0.strip() \
                and (not re.sub(r"[\W_]+", "", text0.replace(REDACTED, "")) or person_shaped(text0)) \
                and not self.mentions_water(text0, event_state(ev)):
            # a reporter's name (or its redaction) in the receiving-water field is not a water name; it is never
            # matched or echoed in a note
            ev = {**ev, "waterbody_text": None}
            note = "; ".join(x for x in (note, "the report's receiving-water field holds no water name") if x)
        rest, labels = self.watershed_labels(ev.get("waterbody_text"), event_state(ev))
        if labels:
            # a watershed label is not a water name (owner, 2026-11-03): a text that is only a label is read as one
            # that names no water; an ingester's name match that came from the label is not used
            shown = quote_text(ev.get("waterbody_text"), 60)
            lab = " ".join(f" {norm_name(x)} " for x in labels)
            rn = f" {norm_name(rest or '')} "

            def from_label(s):
                w = self.waters[s]
                names = [norm_name(n) for n in [w.get("name") or ""] + list(w.get("aliases") or []) if n]
                return any(n and f" {n} " in lab and f" {n} " not in rn for n in names)
            dropped = [s for s in known if (ev.get("water_match") or "inferred") in GUARDED_MATCHES and from_label(s)]
            known = [s for s in known if s not in dropped]
            if rest is None:
                ev = {**ev, "waterbody_text": None}
                said = f"the report's receiving-water text ('{shown}') is a watershed label, not a water name"
            else:
                said = f"a watershed label in the report's receiving-water text ('{shown}') is not read as a water name"
            if dropped:
                said += " (the ingester's " + ", ".join(str(self.waters[s].get("name") or s) for s in dropped) \
                    + " came from it)"
            note = "; ".join(x for x in (note, said) if x)
        # a statement in the text is scoped to the waters its clauses name: "Did not impact Middle Patuxent River;
        # sewage entered Bear Creek" keeps Bear Creek, and a negation on one water never suppresses an explicit
        # placement (the ingester's water, the report's outfall) on another (review 2026-11-03 SOL P1-2)
        neg = self.negated_waters(ev.get("waterbody_text"), event_state(ev), ev) if PLACE_STEPS["stated_no_water"] \
            else set()
        if PLACE_STEPS["stated_no_water"]:
            said = reached_no_water(ev)
            if said and (no_water_flag(ev) or not neg or not self.placed_elsewhere(ev, known, neg)):
                # the source says it reached no water: kept, colours nothing, no reach (P1-3)
                reason, statement = said
                named, nnote = self.named_in(ev, event_state(ev))
                out = {"water_slugs": [], "water_match": "none", "unknown_slugs": unknown,
                       "note": "; ".join(x for x in (f"the report says: '{statement}'" if statement else None, nnote, note)
                                         if x) or None,
                       "no_receiving_water": reason, "stated_no_water": True}
                if named:
                    out["named_water_slugs"] = named
                return out
        if neg:
            known = [s for s in known if s not in neg]
            note = "; ".join(x for x in (note, "the report says the discharge did not reach "
                                         + ", ".join(sorted(str(self.waters[s].get("name") or s) for s in neg))
                                         + " (not placed there)") if x)

        def placed(slugs, match, n=None, extra=(), outfalls=None):
            n = "; ".join(x for x in [n, *extra] if x) or None
            out = {"water_slugs": slugs, "water_match": match, "note": n, "unknown_slugs": unknown}
            if outfalls:
                out["outfalls"] = outfalls          # the registry outfalls used: build() looks up their reaches
            if aside:
                out["set_aside"] = [{"water_slug": s, "reason": r} for s, r in aside]
                if not slugs:
                    out["unplaced_reason"] = "; ".join(dict.fromkeys(r for _, r in aside))
            return out

        state = event_state(ev)
        point = []                          # by_point, computed once when needed

        def on_a_water():
            if not point:
                near = self.by_point(ev.get("lat"), ev.get("lon"), state)
                point.append(None if near and near[1] in neg else near)
            return point[0]

        def yields_to_point(slugs, relaxed):
            """A named water kept only beyond NAME_MATCH_M gives way to a point that lies on a water."""
            if slugs and all(x in relaxed for x in slugs) and on_a_water():
                aside.extend((x, relaxed[x].replace("named in the report; ", "named in the report but not used: ")
                              + "; the report's point lies on another water") for x in slugs)
                return True
            return False

        # a source whose rule places a report only on the water it names (raw._placement named_water_only: Texas's TCEQ
        # table, which gives no point or outfall): never on its permit's outfalls' water, never by a point (final
        # audit 2026-11-07 P1-1); a report naming no water stays unplaced, listed with its county
        named_only = named_water_only(ev)
        yielded = False
        if PLACE_STEPS["registry_first"] and not named_only:
            reg = self.registry_first(ev, state, known, neg)
            if reg and reg[0]:
                return placed(reg[0], "outfall_registry", reg[1], [note], outfalls=reg[2])
            if reg:                         # the report names another water: its own name places it
                yielded = True
                note = "; ".join(x for x in (note, reg[1]) if x)
        if known:
            match = ev.get("water_match") or "inferred"
            relaxed = {}
            if match in GUARDED_MATCHES:
                known, a, relaxed = self.guard_detail(known, ev)
                aside.extend(a)
                if yields_to_point(known, relaxed):
                    known = []
            if known:
                return placed(known, match, note, [relaxed[x] for x in known if x in relaxed])
        o = None if (yielded or named_only) else self.by_outfall(ev.get("npdes_permit"), ev.get("outfall_id"))
        if o and o["water_slug"] not in neg:
            return placed([o["water_slug"]], "outfall_registry",
                          f"placed by outfall {o['outfall']} of permit {o['npdes_permit']} (outfall registry): "
                          f"its water slug ({o.get('match')}, {o.get('distance_m')} m)")
        slugs, nnote, ambiguous = self.by_name(ev.get("waterbody_text"), state, ev.get("lat"), ev.get("lon"), ev)
        slugs = [x for x in slugs if x not in neg]
        if slugs:
            slugs, a, relaxed = self.guard_detail([x for x in slugs if not any(x == y for y, _ in aside)], ev)
            aside.extend(a)
            if yields_to_point(slugs, relaxed):
                slugs = []
            if slugs:
                return placed(slugs, "name", nnote or note, [relaxed[x] for x in slugs if x in relaxed])
        near = None if named_only else on_a_water()
        if near:
            return placed([near[1]], "geometry", f"point {round(near[0])} m from the water")
        reason = None
        text = (ev.get("waterbody_text") or "").strip()
        names_none = not text or (placeholder_text(text) and ev.get("event_type") == "cso")
        # a water text that matched no record (one that may name a water: not "N/A", not a storm drain) still lets
        # the outfalls the report names place it (outfall_ids)
        unmatched = not names_none and PLACE_STEPS["outfall_ids"] and not no_water_text(text)
        if PLACE_STEPS["registry"] and (names_none or unmatched) and not no_water_flag(ev) and not aside \
                and not named_only:
            slugs, match, rnote, outs = self.by_registry(ev, state, names_none)
            slugs = [x for x in slugs or [] if x not in neg] or None
            if slugs:
                kept, a, relaxed = self.guard_detail(slugs, ev) if match in GUARDED_MATCHES else (slugs, [], {})
                aside.extend(a)             # recorded whether or not some are kept (review 2026-11-03 P3-1)
                if kept:
                    told = [f"placed on {len(kept)} of these {len(slugs)} waters; the placement guard set aside "
                            f"{len(slugs) - len(kept)}"] if len(kept) < len(slugs) else []
                    return placed(kept, match, rnote, [note] + told + [relaxed[x] for x in kept if x in relaxed],
                                  outfalls=[o for o in outs if o["water_slug"] in kept])
            else:
                reason = rnote
        out = placed([], "none", nnote or note)
        nw = no_receiving_water(ev, lambda t: self.mentions_water(t, state)) if PLACE_STEPS["no_receiving_water"] \
            else None
        if nw and (no_water_flag(ev) or not out.get("set_aside")):
            out.pop("unplaced_reason", None)
            out["no_receiving_water"] = nw
            return out
        if named_only and not text and not out.get("unplaced_reason"):
            out["unplaced_reason"] = NAMED_ONLY_NONE
        if ambiguous and not out.get("unplaced_reason"):
            out["unplaced_reason"] = "ambiguous name"
        if reason and not out.get("unplaced_reason"):
            out["unplaced_reason"] = reason
        return out


# ---------------------------------------------------------------- rules

def _iv(ev, start, end, rule, red=None, yellow=None):
    color, label = RULES[rule]
    return {"start": start, "end": end, "color": color, "rule": rule, "label": label,
            "category": category_of(ev.get("event_type")),
            "rule_applied": red if rule in ("advisory_active", "rain_advisory", "advisory_unconfirmed",
                                            "not_reconfirmed") else None,
            "event_id": ev["event_id"], "source_id": ev.get("source_id"), "fixture": bool(ev.get("_fixture")),
            "event_type": ev.get("event_type"), "event_status": ev.get("status"),
            "authority": ev.get("authority") or ev.get("discharger_name"),
            "window_hours": (red or {}).get("hours"), "window_basis": (red or {}).get("rationale"),
            "red_rule": red, "yellow_rule": yellow,
            "started_at": ev.get("started_at"), "ended_at": ev.get("ended_at")}


# A report placed on the water its text names although its form's flag said no water was reached (raw.reached_water
# "text"; the Florida DEP PNP notices, owner 2026-11-04: the text wins, err on the side of safety). Its colour is the
# site's caution only: what would be red (in progress, ongoing, an authority's window) is yellow, rule text_caution,
# since no authority advice applies to a water the authority's form says was not reached.
TEXT_OVER_FLAG = "text"
TEXT_OVER_FLAG_NOTE = "the notice's description names this water; its form answered \"Waterbodies Impacted: N\""


def text_over_flag(ev: dict) -> bool:
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    return raw.get("reached_water") == TEXT_OVER_FLAG


# A sewage report filed by a member of the public (raw.report_provenance "citizen": the Florida DEP PNP notices a
# resident filed). Its classification is the report's own (a sewage overflow), its provenance is marked apart, and its
# colour is the site's caution only (rule citizen_caution, never red): what would be red is yellow, cited as the
# public's report, never as an authority's confirmation (SOL 2026-11-07 wave 1 P1-5; err on the side of safety).
CITIZEN = "citizen"
CITIZEN_NOTE = "filed by a member of the public; no authority has confirmed the discharge"


def citizen_report(ev: dict) -> bool:
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    return raw.get("report_provenance") == CITIZEN


# A record opened from a source's code whose meaning the source does not publish (raw.code_undecoded: the reason, as
# ADEM's beach map code; ingest/al_adem_beaches.py). It is never shown as the authority's own advisory: what would be
# red is the site's caution (rule code_caution), until the source states what its codes mean.
def code_undecoded(ev: dict) -> str | None:
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    v = raw.get("code_undecoded")
    return v if isinstance(v, str) and v.strip() else None


def _caution_only(iv: dict, rule: str, applied: str, basis: str, source) -> None:
    """Turn a red interval into the site's caution under rule (no authority window applies)."""
    was = iv["rule"]
    iv["color"], iv["label"], iv["rule"] = RULES[rule][0], RULES[rule][1], rule
    iv["window_hours"] = iv["window_basis"] = None
    iv["rule_applied"] = {"rule": applied, "replaces": was, "hours": None,
                          "rationale": f"{basis}: placed on the water under the site's caution, never red "
                                       "(no authority window applies)", "source": source}


def event_intervals(ev: dict, state: str | None, now: datetime, water: dict | None = None,
                    rules: dict | None = None) -> list[dict]:
    """The colour intervals one event sets on a water (its state, and the water record for the
    caution window). end None = open (in effect now). A published end that is not credible (end_not_credible) is
    not used: the intervals are those of a record with no end, each with end_not_used (the published end, why, and
    the rule)."""
    rules = load_rules() if rules is None else rules
    out = _event_intervals(ev, state, now, water, rules)
    why = end_not_credible(ev, now, rules) if out and ev.get("ended_at") else None
    if why:
        r = ((rules.get("unresolved") or {}).get("implausible_end") or {})
        note = {"published_end": ev.get("ended_at"), "why": why, "rule": "unresolved.implausible_end",
                "days_after_fetch": end_limit_days(rules), "rationale": r.get("rationale"), "source": "data/rules.json"}
        for iv in out:
            iv["end_not_used"] = note
    if out and text_over_flag(ev):
        basis = str((ev.get("raw") or {}).get("_reached_water_basis") or TEXT_OVER_FLAG_NOTE)
        for iv in out:
            iv["text_over_flag"] = basis
            if iv["color"] == "red":
                _caution_only(iv, "text_caution", "placement.text_over_flag", basis, ev.get("source_url"))
    if out and citizen_report(ev):
        basis = str((ev.get("raw") or {}).get("_provenance_note") or CITIZEN_NOTE)
        for iv in out:
            iv["citizen_report"] = basis
            if iv["color"] == "red":
                _caution_only(iv, "citizen_caution", "provenance.citizen_report", basis, ev.get("source_url"))
    code_basis = code_undecoded(ev) if out else None
    if code_basis:
        for iv in out:
            iv["code_undecoded"] = code_basis
            if iv["color"] == "red":
                _caution_only(iv, "code_caution", "provenance.code_undecoded", code_basis, ev.get("source_url"))
    return out


def _event_intervals(ev: dict, state: str | None, now: datetime, water: dict | None, rules: dict) -> list[dict]:
    et, st = ev.get("event_type") or "unknown", ev.get("status") or "unknown"
    tz = event_zone(ev, state)

    def pt(v):
        return parse_time(v, tz)          # the record's own clock (event_zone)
    if et == "annual_total" or ev.get("time_precision") in COARSE_PRECISION:
        return []                 # outfall-months and annual totals are history, never a colour
    if future_start(ev, now):
        return []                 # a start in the future as published: no colour (FUTURE_START_H)
    if et == "unknown" and st != "ongoing":
        return []                 # an unparsed record colours only while it says ongoing
    start = pt(ev.get("started_at")) or pt(ev.get("reported_at")) or pt(ev.get("published_at"))
    if start is None:
        return []
    end = pt(ev.get("ended_at"))
    end_not_used = end_not_credible(ev, now, rules) if end is not None else None
    if end_not_used:
        end = None      # before the start, or too far ahead: no confirmed end (validation error in build: time_problem)
    if end is not None and end_precision(ev) == "day":
        end = end_of_local_day(end, tz)      # a day-precision end counts from the end of that day, in its own zone
    bound = None
    if end is None and st == "ended" and ev.get("time_precision") == "bound":
        # "no activations for 12 hours": ended by this time at the latest; windows count from the bound
        bound = pt((ev.get("raw") or {}).get("_ended_before"))
        if bound is not None:
            end = bound
            start = min(start, bound)        # a report time after the bound is not the discharge's start

    red = red_rule_for(ev, state, rules)
    yellow = yellow_rule_for(ev, water, rules)
    sc = (rules.get("unresolved") or {}).get("sample_caution") or {}
    if ev.get("source_id") in (sc.get("sources") or []) and sc.get("hours") \
            and (ev.get("raw") or {}).get(sc.get("flag") or "_agency_label_only"):
        # a sample the agency labels a risk with no advisory (Nebraska's elevated E. coli): the site's caution from
        # the sample, never the authority's advisory rule (review 2026-11-07 P2-2)
        until = start + timedelta(hours=float(sc["hours"]))
        raw = ev.get("raw") or {}
        notice_end = None
        if raw.get("_caution_to_notice_end") is True:
            # the agency keeps a notice up while it retests (Hawaii's beach notifications, ingest/hi_doh_cwb_events.py):
            # the caution runs to the later of its hours and the notice's closing, or the last read that listed it
            # while it is open (review 2026-11-07 P2-2); keyed on the record's flag, so other feeds are unchanged
            notice_end = (parse_time(raw.get("_notice_closed_at")) or end
                          or parse_time(raw.get("_last_seen_in_source")))
            if notice_end is not None and notice_end > until:
                until = notice_end
        iv = _iv(ev, start, until, "sample_caution", None, yellow)
        iv["rule_applied"] = {"rule": "unresolved.sample_caution", "hours": float(sc["hours"]),
                              "label": raw.get("_agency_label"),
                              "rationale": sc.get("rationale"), "source": "data/rules.json"}
        if notice_end is not None and until == notice_end:
            iv["rule_applied"]["extended_to"] = {
                "until": iso(notice_end), "basis": raw.get("_notice_end_basis") or "the agency's notice was still posted",
                "source": ev.get("source_url")}
        return [iv]
    if et in ADVISORY_TYPES or st in ("advisory_active", "advisory_lifted"):
        rule = "rain_advisory" if et == "rain_advisory" else "advisory_active"
        red = {"rule": "red.authority_advisory", "hours": None, "clock": None, "source": ev.get("source_url"),
               "rationale": "in effect while the authority keeps the advisory (aged out 14 days after the "
                            "last confirmation when no end is given)"}

        if st == "advisory_active":
            if end is not None:                       # an explicit end is the source's word
                return [_iv(ev, start, end, rule, red, yellow)]
            listed = pt((ev.get("raw") or {}).get("_last_seen_in_source"))
            unlisted = pt((ev.get("raw") or {}).get("_unlisted_since"))
            if unlisted is not None and unlisted > start:
                # a feed read with history.confirm_while_listed (docs/generic-ingesters.md): the advisory was shown
                # at every fetch up to the first that no longer found it; it ends there, at or before that fetch
                iv = _iv(ev, start, unlisted, rule, red, yellow)
                iv["confirmed"] = iso(listed or start)
                iv["ended_by"] = "no longer on the authority's map at this fetch"
                if (ev.get("raw") or {}).get("_end_not_confirmed") is True and et not in ADVISORY_TYPES:
                    # a sewage report under the authority's advisory that left its list without the authority's
                    # cancellation (ingest/hi_doh_cwb_events.py): its end is not confirmed, never a clean end at our
                    # fetch. "End not confirmed" (hatched) to day 30 from the start and for at least the site's caution
                    # hours after the unlisting, even past day 30 (review 2026-11-07 P2-1); then the end-never-reported
                    # note to day 90, as for any unresolved record (no_end)
                    u = (rules or {}).get("unresolved") or {}
                    days = float(u.get("unresolved_yellow_days") or 30)
                    hours = float(((rules or {}).get("yellow") or {}).get("default_hours") or 72)
                    hatch_until = max(start + timedelta(days=days), unlisted + timedelta(hours=hours))
                    iv["ended_by"] = ("no longer on the authority's list at this fetch, with no cancellation: "
                                      "the end is not confirmed")
                    un = _iv(ev, unlisted, hatch_until, "unresolved", red, yellow)
                    un["rule_applied"] = {"rule": "unresolved.unresolved_yellow_days", "days": days,
                                          "hours_after_unlisting": hours,
                                          "rationale": "the advisory left the authority's list without its "
                                                       "cancellation; the end is not confirmed",
                                          "source": "data/rules.json"}
                    out = [iv, un]
                    note_until = max(hatch_until, start + timedelta(days=NOTE_DAYS))
                    if note_until > hatch_until:
                        note = _iv(ev, hatch_until, note_until, "end_never_reported", red, yellow)
                        note["rule_applied"] = {"rule": "unresolved.unresolved_yellow_days", "days": days,
                                                "rationale": u.get("end_assumed_rationale")
                                                or u.get("unresolved_yellow_rationale"), "source": "data/rules.json"}
                        out.append(note)
                    return out
                return [iv]
            if et in AGING_TYPES:
                confirmed = max(t for t in (start, pt(ev.get("source_updated_at")), listed) if t)
                until = confirmed + timedelta(days=CONFIRM_DAYS)
                out = [_iv(ev, start, until, rule, red, yellow)]
                note = _iv(ev, until, max(until, start + timedelta(days=NOTE_DAYS)), "not_reconfirmed", red, yellow)
                note["confirmed"] = iso(confirmed)
                out[0]["confirmed"] = iso(confirmed)
                return out + ([note] if note["end"] > note["start"] else [])
            return [_iv(ev, start, None, rule, red, yellow)]
        if st == "advisory_lifted":
            # needs its own (or inherited) start; ends at ended_at, else when the lifting was reported
            real_start = pt(ev.get("started_at"))
            if real_start is None:
                return []
            told = [t for t in (pt(ev.get("reported_at")), pt(ev.get("published_at")),
                                pt(ev.get("source_updated_at"))) if t and t >= real_start]
            e = end or (min(told) if told else None)
            return [_iv(ev, real_start, e, rule, red, yellow)] if e else []
        if end:
            return [_iv(ev, start, end, rule, red, yellow)]
        return [_iv(ev, start, start + timedelta(days=ADVISORY_NO_END_DAYS), "advisory_unconfirmed", red, yellow)]

    u = rules.get("unresolved") or {}
    red_days = float(u.get("ongoing_red_days") or 7)
    unres_days = float(u.get("unresolved_yellow_days") or 30)
    unknown_days = float(u.get("unknown_status_yellow_days") or 14)

    def no_end(anchor, first_until, first_rule):
        """From the anchor (the start for ongoing, the source's report time for unknown status): the first colour,
        then unresolved to day 30, then the off-map note to day 90. Every colour ends by the absolute cap, 30 days
        (unresolved_yellow_days) after the report began, however late it was reported or first seen: after that the
        site assumes the discharge ended and the record says the end was never reported (owner, 2026-11-03)."""
        cap = (pt(ev.get("started_at")) or start) + timedelta(days=unres_days)
        first_until = min(first_until, cap)
        u_until = min(anchor + timedelta(days=unres_days), cap)
        note_from = max(anchor, first_until, u_until)
        note_until = max(note_from, anchor + timedelta(days=NOTE_DAYS))
        unres_rule = {"rule": "unresolved.unresolved_yellow_days", "days": unres_days,
                      "rationale": u.get("unresolved_yellow_rationale"), "source": "data/rules.json"}
        out = []
        if first_until > anchor:
            out.append(_iv(ev, anchor, first_until, first_rule, red, yellow))
            out[0]["rule_applied"] = (
                {"rule": "unresolved.ongoing_red_days", "days": red_days, "rationale": u.get("ongoing_red_rationale"),
                 "source": "data/rules.json"}
                if first_rule == "ongoing" else
                {"rule": "unresolved.unknown_status_yellow_days", "days": unknown_days,
                 "rationale": u.get("unknown_status_rationale"), "source": "data/rules.json"})
        if u_until > max(anchor, first_until):
            iv = _iv(ev, max(anchor, first_until), u_until, "unresolved", red, yellow)
            iv["rule_applied"] = unres_rule
            out.append(iv)
        note = _iv(ev, note_from, note_until, "end_never_reported", red, yellow)
        if note["end"] > note["start"]:
            note["rule_applied"] = {**unres_rule, "rationale": u.get("end_assumed_rationale")
                                    or u.get("unresolved_yellow_rationale")}
            out.append(note)
        return out

    if st == "ongoing" and end is None:
        return no_end(start, start + timedelta(days=red_days), "ongoing")
    if end is not None:
        out = [_iv(ev, start, end, "discharge", red, yellow)]
        out[0]["rule_applied"] = {"rule": "discharge", "rationale": "between the reported start and end"}
        if bound is not None:
            out[0]["rule_applied"] = {"rule": "discharge", "rationale": "between the start and the latest possible "
                                      "end the source states (raw._ended_before)"}
        red_until = end
        if red.get("hours"):
            red_until = end + timedelta(hours=float(red["hours"]))
            out.append(_iv(ev, end, red_until, "authority_window", red, yellow))
            out[-1]["rule_applied"] = red
        if yellow.get("hours"):
            caution_until = end + timedelta(hours=float(yellow["hours"]))
            if red_until < caution_until:
                out.append(_iv(ev, red_until, caution_until, "caution", red, yellow))
                out[-1]["rule_applied"] = yellow
        if bound is not None:
            for iv in out:
                iv["ended_by"] = iso(bound)
        return out
    # from the source's own report time: reported_at, else published_at, else the start; never a retrieval or
    # extract date that is later than the report (owner, 2026-11-03), and never before the start
    ds = u.get("day_start_caution") or {}
    if ev.get("time_precision") == "day" and ev.get("source_id") in (ds.get("sources") or []) and ds.get("hours") \
            and pt(ev.get("started_at")):
        # a feed that gives only the day a discharge began and never an end (Georgia EPD's daily list): the site's
        # caution runs from the start of that day, then the end is unconfirmed to day 30 (unresolved.day_start_caution)
        day0 = pt(ev["started_at"])
        out = no_end(day0, day0 + timedelta(hours=float(ds["hours"])), "day_start_caution")
        for iv in out:
            if iv["rule"] == "day_start_caution":
                iv["rule_applied"] = {"rule": "unresolved.day_start_caution", "hours": float(ds["hours"]),
                                      "rationale": ds.get("rationale"), "source": "data/rules.json"}
        return out
    told = next((t for t in (pt(ev.get("reported_at")), pt(ev.get("published_at"))) if t), None)
    anchor = max(start, told) if told else start
    return no_end(anchor, anchor + timedelta(days=unknown_days), "no_end")


def resolve_revisions(events: list[dict], by_id: dict) -> tuple[dict, dict]:
    """(superseded {event_id: why}, effective {event_id: record used for the rules}).

    A child (parent_event_id present in the data) with a status other than `unknown`, or with its
    own started_at, is the newer word on the event: its parent is superseded, and when the child
    has no started_at it inherits the parent's (a MassDEP "Ceased" update, a lifted cyanobacteria
    report). A child with status `unknown` and no start is a notice about the parent (a VT public
    alert linked to its incident report): it sets nothing and the parent carries the times."""
    superseded, effective = {}, {}
    for ev in events:
        par = ev.get("parent_event_id")
        if not par or par not in by_id or par == ev["event_id"]:
            continue
        if ev.get("started_at") or (ev.get("status") or "unknown") != "unknown":
            superseded[par] = f"revised by {ev['event_id']}"
        else:
            superseded[ev["event_id"]] = f"notice about {par}, which carries the times"

    def start_of(eid, depth=0):
        e = by_id.get(eid)
        if e is None or depth > 50:
            return None
        if e.get("started_at"):
            return e["started_at"]
        par = e.get("parent_event_id")
        return start_of(par, depth + 1) if par and par != eid else None

    for ev in events:
        if not ev.get("started_at") and ev.get("parent_event_id") in by_id and ev["event_id"] not in superseded:
            inherited = start_of(ev["parent_event_id"])
            if inherited:
                effective[ev["event_id"]] = {**ev, "started_at": inherited}
    return superseded, effective


def water_rules(reasons: list[dict], w: dict, slug: str, rules: dict) -> dict:
    """The red and yellow window rules on a water's status entry: those of the reason setting the
    colour now (applied: true), else those a CSO on this water would get (applied: false)."""
    top = next((r for r in reasons if r["status"] in ("red", "yellow", "unresolved")), None)
    if top:
        return {"red_rule": {**(top.get("red_rule") or {}), "applied": True, "event_id": top["event_id"]},
                "yellow_rule": {**(top.get("yellow_rule") or {}), "applied": True, "event_id": top["event_id"]},
                "rule_applied": {**(top.get("rule_applied") or {}), "status": top["status"], "event_id": top["event_id"]}}
    probe = {"event_type": "cso"}
    return {"red_rule": {**red_rule_for(probe, w.get("state"), rules), "applied": False, "for": "a CSO on this water"},
            "yellow_rule": {**yellow_rule_for(probe, {**w, "slug": slug}, rules), "applied": False,
                            "for": "a CSO on this water"},
            "rule_applied": None}


def paint(ivs: list[dict], h0: datetime, h_end: datetime, n_hours: int) -> str:
    """One character per hour, by category (docs/plan.md §2.z), in the site's precedence r > y > u > R > Y > B > m > g:
    the strictest sewage state; with none, a beach advisory R (red) or Y (yellow or unresolved); then a bloom
    advisory B; then the monthly mark m; else g. Beach and bloom hours are letters of their own."""
    by = defaultdict(list)
    for iv in ivs:
        by[iv.get("category") or "sewage"].append(iv)
    sew = _paint(by["sewage"], h0, h_end, n_hours)
    if not by["beach"] and not by["bloom"]:
        return sew
    beach = _paint(by["beach"], h0, h_end, n_hours)
    bloom = _paint(by["bloom"], h0, h_end, n_hours)
    out = []
    for a, b, c in zip(sew, beach, bloom):
        if a in "ryu":
            out.append(a)
        elif b == "r":
            out.append("R")
        elif b in "yu":
            out.append("Y")
        elif c in "ryu":
            out.append(BLOOM_CHAR)
        else:
            out.append(a)
    return "".join(out)


def _paint(ivs: list[dict], h0: datetime, h_end: datetime, n_hours: int) -> str:
    """One character per hour: the strictest state touching the hour (r > y > u > m > g)."""
    arr = bytearray(b"g" * n_hours)
    for col in ("monthly", "unresolved", "yellow", "red"):
        for iv in ivs:
            if iv["color"] != col:
                continue
            e = iv["end"] or (h_end + timedelta(hours=1))
            if e <= h0 or iv["start"] >= h_end + timedelta(hours=1):
                continue
            i0 = max(0, math.floor((iv["start"] - h0).total_seconds() / 3600))
            i1 = min(n_hours, math.ceil((e - h0).total_seconds() / 3600))
            arr[i0:i1] = CHAR[col].encode() * max(0, i1 - i0)
    return arr.decode()


def reach_lookup_key(ev: dict):
    if not ev.get("npdes_permit") or ev.get("outfall_id") in (None, ""):
        return None
    k = oid_key(ev["outfall_id"])
    return (ev["npdes_permit"], k) if k else (ev["npdes_permit"], norm_oid(ev["outfall_id"]))


def event_reaches(ev: dict, pl: dict, reach_index: dict) -> list[tuple[dict, str | None]]:
    """[(cached reach, the water slug of its outfall, or None)]: the reach of the record's own outfall_id or point
    (None: it carries every river water the record is placed on, one outfall); else one per registry outfall the
    placement used (placements[].outfalls: a report naming its outfalls in its name or volume text, perhaps
    several), each carrying its own outfall's water."""
    r = reach_index.get(reach_lookup_key(ev)) or reach_index.get(("event", ev["event_id"]))
    if r:
        return [(r, None)]
    out, seen = [], set()
    for o in pl.get("outfalls") or []:
        if not ev.get("npdes_permit") or o.get("outfall") in (None, ""):
            continue
        k = oid_key(o["outfall"])
        r = reach_index.get((ev["npdes_permit"], k if k else norm_oid(o["outfall"])))
        if r and r.get("key") not in seen:
            seen.add(r.get("key"))
            out.append((r, o.get("water_slug")))
    return out


def index_reaches(reaches: dict) -> dict:
    """(permit, outfall number key) -> cached reach (MassDEP 'SPR010', ECHO '010' both -> (10, ''));
    ("event", event_id) -> a reach traced from an event's own point (a sewer break, no outfall)."""
    out = {}
    for r in (reaches or {}).values():
        if r.get("cut_reason") == "no_trace":
            continue
        for eid in r.get("event_ids") or []:
            out[("event", eid)] = r
        if not r.get("permit") or r.get("outfall") in (None, ""):
            continue
        k = oid_key(r.get("outfall"))
        out[(r["permit"], k if k else norm_oid(r.get("outfall")))] = r
    return out


_REACH_WATERS: dict[str, list[str]] = {}


class _NoTravel(Exception):
    """A shoreline stretch has no travel time (no flow along a lake shore)."""


def _comid_in(comid, w: dict) -> bool:
    """Whether a water record's NHDPlus COMIDs hold this flowline."""
    try:
        return int(comid) in {int(x) for x in w.get("comids") or []}
    except (TypeError, ValueError):
        return False


def reach_waters(reach: dict, waters: dict) -> list[str]:
    """River water records a reach runs along: a segment's midpoint within REACH_WATER_M of the
    water's geometry (openboatlaunch or waters-extra) and, when the NHDPlus flowline is named, the
    same name (so a Connecticut River reach passing the Westfield's mouth does not flag the
    Westfield: tributaries upstream of their mouth are never on the reach), unless the record holds the
    segment's own COMID (a record whose name is not the one NHDPlus gives its flowlines)."""
    key = reach["key"]
    if reach.get("model") == SH.MODEL:      # a shoreline stretch: its lake and the same lake's records it reaches
        return [s for s in (reach.get("waters") or [reach.get("water_slug")]) if s in waters]
    if key in _REACH_WATERS:
        return _REACH_WATERS[key]
    from shapely.geometry import Point
    rivers = [(slug, w) for slug, w in waters.items() if w.get("kind") in RIVER_KINDS and w.get("bbox")]
    found = []
    for sg in reach.get("segments") or []:
        c = sg["coords"][len(sg["coords"]) // 2]
        pad = 0.01
        gnis = norm_name(sg.get("gnis_name") or "")
        for slug, w in rivers:
            b = w["bbox"]
            if slug in found:
                continue
            # the record holds the segment's own NHDPlus flowline (its COMIDs): the same water, whatever name NHDPlus
            # gives it (2026-11-06: NHDPlus names the Little Calumet River's flowlines 'Calumet River', review P1-1)
            own = sg.get("comid") is not None and _comid_in(sg["comid"], w)
            if gnis and not own and norm_name(w.get("name") or "") != gnis:
                continue
            if not (b[0] - pad <= c[0] <= b[2] + pad and b[1] - pad <= c[1] <= b[3] + pad):
                continue
            g = water_geometry(slug, waters)
            if g is not None and g.distance(Point(c[0], c[1])) * 111_320 <= REACH_WATER_M:
                found.append(slug)
    _REACH_WATERS[key] = found
    return found


def names_its_water(ev: dict) -> bool:
    """An authority's advisory for the water it names (MDEQ's water contact advisories: raw.extent "named_water"):
    it colours the water it is placed on, and on a water that is not filled it also keeps its marker, so the map still
    shows it. On a river, stream or canal it colours only the stretch it names (has_stretch); with no stretch it is a
    point there, as every advisory is (advisory_on_river: reaches, not whole rivers, 2026-11-07). Other beach, rain and HAB
    advisories speak for a beach or a station, not the whole water (colours_whole_water)."""
    return (ev.get("raw") or {}).get("advisory_extent") == "named_water"


def stretch_text(ev: dict | None) -> str:
    """' · from X to Y' for an advisory whose source names its ends (the record's `stretch`, else raw.stretch), else ''."""
    g = (ev or {}).get("stretch") or {}
    a, b = (g.get("start") or {}).get("name"), (g.get("end") or {}).get("name")
    if not (a and b):
        s = ((ev or {}).get("raw") or {}).get("stretch") or {}
        a, b = (s.get("from") or {}).get("name"), (s.get("to") or {}).get("name")
    return f" · from the {a} to the {b}" if a and b else ""


def has_stretch(ev: dict) -> bool:
    """An advisory whose record names a stretch with a point at each end (build/reaches.py stretch_of)."""
    from build.reaches import stretch_of
    return ev.get("event_type") in POINT_ADVISORY_TYPES and stretch_of(ev) is not None


def stretch_traces(reaches: dict) -> dict[str, dict]:
    """event_id -> its cached advisory stretch record (traced or not)."""
    out = {}
    for r in (reaches or {}).values():
        if r.get("kind") == ADVISORY_STRETCH:
            for eid in r.get("event_ids") or []:
                out[eid] = r
    return out


def stretch_fallback(r: dict | None) -> str:
    """Why an advisory with a stretch is shown only at its point: the stretch is not traced yet, or why it could not
    be. The river is never coloured whole in its place (SOL wave2 P1-3)."""
    tail = "the advisory is shown at its point, and the river is not coloured"
    if not r:
        return f"the stretch the advisory names is not traced yet; {tail}"
    why = r.get("error") or r.get("cut_reason") or "no stretch could be traced"
    return f"the stretch the advisory names could not be traced ({why}); {tail}"


def advisory_on_river(ev: dict, w: dict, stretched: bool = False) -> bool:
    """Reaches, not whole rivers (owner's rule; 2026-11-07, New Mexico final audit): an algal-bloom, beach, rain or
    shellfish advisory, or any other record under an authority's advisory that is not a discharge, placed on a river,
    stream or canal record (RIVER_KINDS) with no stretch of its own is shown as a point. The record is listed on the
    water's page and its marker carries the advisory's colour; the river record is not coloured. Keyed on the
    water's kind, never on the state. A lake, pond or reservoir keeps colours_whole_water; an advisory with a stretch
    and a traced stretch (stretched) keeps the advisory-stretch path; one whose stretch is not traced is a point too
    (SOL wave2 P1-3)."""
    if stretched or w.get("kind") not in RIVER_KINDS:
        return False
    if ev.get("event_type") in DISCHARGE_TYPES:
        return False
    return ev.get("event_type") in ADVISORY_TYPES or str(ev.get("status") or "") in ("advisory_active",
                                                                                    "advisory_lifted")


RIVER_POINT_WHY = ("the advisory is on a river or stream and names no stretch to draw: it is shown at its point, and "
                   "the river is not coloured whole")


def colours_whole_water(w: dict) -> bool:
    """Beach, rain and HAB advisories colour a whole water only on a lake, pond or reservoir under
    SMALL_WATER_KM2 (an unknown area counts as small)."""
    if w.get("kind") not in WHOLE_WATER_KINDS:
        return False
    a = w.get("area_km2")
    return a is None or a < SMALL_WATER_KM2


def _filled(ev: dict) -> int:
    return sum(1 for k, v in ev.items() if not k.startswith("_") and k != "raw" and v not in (None, "", [], {}))


# Words that name no particular water. A receiving-water text made only of these and water words ("unnamed
# tributary", "storm drain to creek") is not compared between two reports of one permit and day; nor is longer free
# text (more than SAME_DAY_NAME_WORDS words): only short names such as "Test Creek" or "UT to Mill River" are.
UNSPECIFIC_WATER_WORDS = {"unnamed", "unamed", "unnammed", "unknown", "un", "ut", "trib", "tributary", "tributaries",
                          "to", "of", "the", "a", "an", "and", "into", "storm", "drain", "drains", "ditch", "ms4",
                          "catch", "basin", "nearby", "local", "near", "small",
                          # descriptions, not names: "receiving stream", "tidal creek", "Outfall 001 to river" (an
                          # outfall number is never a water's name)
                          "receiving", "tidal", "drainage", "outfall", "outfalls", "outlet", "adjacent", "adjoining",
                          "nearest", "closest", "surface", "waterway", "waterbody", "possibly"}
# After a water word, these start a description of where ("creek behind the plant", "Mill Creek at Route 1", "stream
# next to the pump station"): the rest of the part is not compared
WHERE_WORDS = {"behind", "beside", "next", "adjacent", "across", "along", "near", "at", "by", "on", "in", "from",
               "below", "above", "off", "via", "downstream", "upstream", "then", "which", "eventually", "ultimately"}
SAME_DAY_NAME_WORDS = 6


def specific_water_keys(text) -> set[str]:
    """The particular waters a receiving-water text names, as comparison keys ("Test Creek" and "UT to Test Cr" give
    "testcreek"); each part between semicolons is read on its own (EPA joins several waters with "; ")."""
    keys = set()
    for part in re.split(r"[;\n]", str(text or "")):
        if not part.strip() or no_water_text(part) or stated_no_water(part) or not WATER_WORD.search(part):
            continue
        toks = norm_name(part).split()
        if len(toks) > SAME_DAY_NAME_WORDS:
            continue
        first = next((i for i, t in enumerate(toks) if WATER_WORD.fullmatch(t)), None)
        if first is not None:
            cut = next((i for i in range(first + 1, len(toks)) if toks[i] in WHERE_WORDS), len(toks))
            toks = toks[:cut]
        named = [t for t in toks if t not in UNSPECIFIC_WATER_WORDS and not t.isdigit()]
        if named and not all(WATER_WORD.fullmatch(t) for t in named):
            keys.add("".join(named))
    return keys


def waters_differ(a: dict, b: dict) -> bool:
    """Both reports name a particular water and no name of one is part of a name of the other."""
    ka, kb = specific_water_keys(a.get("waterbody_text")), specific_water_keys(b.get("waterbody_text"))
    return bool(ka and kb) and not any(x in y or y in x for x in ka for y in kb)


def find_duplicates(events: list[dict]) -> dict[str, str]:
    """{event_id: duplicate_of} for ECHO-reported discharges repeated across sources: same
    npdes_permit and same local start day (and no differing outfall ids). A state notice for that
    permit and day wins over ECHO records; among ECHO records the one with more fields wins.
    Fixtures and month/year records take no part.
    A report that reached a water never becomes the duplicate of one that says the discharge reached no water
    (reached_no_water: "Reach Waterbody: No", EPD's dry-land rows) or that names no water (no_receiving_water: "N/A",
    the ground, a storm drain): the dry-land record is linked as the duplicate of the ECHO report instead, so the
    water keeps its colour (GA review 2026-11-04 P2-11). Two reports that name
    different particular waters (waters_differ) are not linked at all: they may be two spills of one system."""
    groups = defaultdict(list)
    for ev in events:
        if ev.get("_fixture") or ev.get("time_precision") in COARSE_PRECISION or ev.get("duplicate_of"):
            continue
        if citizen_report(ev):
            continue        # a member of the public's report never absorbs (nor is absorbed by) an operator's report
        if ev.get("event_type") not in DISCHARGE_TYPES or not ev.get("npdes_permit"):
            continue
        tz = event_zone(ev)
        t = ev_time(ev, "started_at", tz=tz)
        if t:
            groups[(ev["npdes_permit"], t.astimezone(tz).date())].append(ev)   # the day in the report's own zone
    dup = {}
    dry = {}

    def is_dry(e):
        """The record says the discharge reached no water, or names none (a placeholder, the ground, a storm drain:
        no_receiving_water); either way it colours nothing."""
        if e["event_id"] not in dry:
            dry[e["event_id"]] = bool(reached_no_water(e) or no_receiving_water(e))
        return dry[e["event_id"]]

    def same_place(a, b):
        return not (a.get("outfall_id") and b.get("outfall_id") and norm_oid(a["outfall_id"]) != norm_oid(b["outfall_id"])) \
            and not waters_differ(a, b)

    def compatible(a, keep):
        """a may be made the duplicate of keep."""
        return same_place(a, keep) and not (is_dry(keep) and not is_dry(a))

    for group in groups.values():
        echo = [e for e in group if is_echo(e)]
        if not echo:
            continue
        state = sorted((e for e in group if not is_echo(e)), key=_filled, reverse=True)
        rest = []
        for e in echo:
            keep = next((x for x in state if compatible(e, x)), None)
            if keep:
                dup[e["event_id"]] = keep["event_id"]
            else:
                rest.append(e)
        rest.sort(key=lambda e: (-_filled(e), e["event_id"]))
        kept = []
        for e in rest:
            keep = next((x for x in kept if compatible(e, x) and x["source_id"] != e["source_id"]), None)
            if keep:
                dup[e["event_id"]] = keep["event_id"]
            else:
                kept.append(e)
        for x in state:         # a dry-land state record beside an ECHO report of a water: the state record repeats it
            if is_dry(x):
                keep = next((e for e in kept if compatible(x, e)), None)
                if keep:
                    dup[x["event_id"]] = keep["event_id"]
    for k in list(dup):         # an ECHO record that a dry-land record absorbed follows it to the report kept
        seen = {k}
        while dup[k] in dup and dup[k] not in seen:
            seen.add(dup[k])
            dup[k] = dup[dup[k]]
    return dup


def is_echo(ev: dict) -> bool:
    return "echo" in str(ev.get("source_id") or "")


def overlapping(intervals, t0: datetime, t1: datetime | None = None):
    """Intervals in effect during [t0, t1) (at t0 when t1 is None)."""
    if t1 is None:
        return [iv for iv in intervals if iv["start"] <= t0 and (iv["end"] is None or iv["end"] > t0)]
    return [iv for iv in intervals if iv["start"] < t1 and (iv["end"] is None or iv["end"] > t0)]


def color_of(ivs) -> str:
    best = "grey"
    for iv in ivs:
        if RANK[iv["color"]] > RANK[best]:
            best = iv["color"]
    return best


def status_at(intervals, t: datetime):
    ivs = overlapping(intervals, t)
    return color_of(ivs), ivs


def since_of(intervals, now: datetime, color: str) -> datetime | None:
    """When the colour in effect now began: walk back over the change points while the colour holds."""
    points = sorted({iv["start"] for iv in intervals if iv["start"] <= now}
                    | {iv["end"] for iv in intervals if iv["end"] is not None and iv["end"] <= now}, reverse=True)
    since = None
    for p in points:
        before = p - timedelta(seconds=1)
        if status_at(intervals, p)[0] != color:
            break
        since = p
        if status_at(intervals, before)[0] != color:
            break
    return since


PLACEMENT_TEXT = {"reach": " · on a modeled downstream reach", "named": " · named in the notice",
                  "tidal": " · tidal or estuary: movement not modeled",
                  "unmodeled": " · downstream path not modeled",
                  "shoreline_unmodeled": " · lake shore: stretch not modeled",
                  "ocean_shore_unmodeled": " · ocean shore: stretch not modeled"}
SHORE_PLACEMENT_TEXT = " · on a modeled shoreline stretch"
STRETCH_PLACEMENT_TEXT = " · on the stretch the advisory names"


def where(iv: dict) -> str:
    if iv.get("placement") == "reach" and iv.get("reach") in _SHORE_REACHES:
        return SHORE_PLACEMENT_TEXT
    if iv.get("placement") == "reach" and iv.get("reach") in _STRETCH_REACHES:
        return STRETCH_PLACEMENT_TEXT
    return PLACEMENT_TEXT.get(iv.get("placement") or "", "")


def start_txt(iv: dict) -> str:
    t = parse_time(iv.get("started_at"))
    return t.astimezone(LOCAL).strftime("%b %-d %H:%M") if t else "an unknown time"


def short_reason(iv: dict, ev: dict | None) -> str:
    text = _short_reason(iv, ev)
    if iv.get("end_not_used"):
        text += " · published end not used"
    if iv.get("text_over_flag"):
        text += " · water named in the notice's text; its form said no water was reached"
    return text


def _short_reason(iv: dict, ev: dict | None) -> str:
    if iv.get("rule") == "rain_likely":
        from build import rain_likely as rain_mod
        return rain_mod.short(iv, where(iv))
    et = ((ev or {}).get("raw") or {}).get("advisory_noun") or TYPE_LABEL.get(iv.get("event_type"), "Report")
    who = (ev or {}).get("discharger_name") or (ev or {}).get("authority") or ""
    who = f" · {who}" if who else ""
    end = parse_time(iv.get("ended_at"))
    endtxt = end.astimezone(LOCAL).strftime("%b %-d %H:%M") if end else None
    if iv.get("ended_by"):
        endtxt = "by " + parse_time(iv["ended_by"]).astimezone(LOCAL).strftime("%b %-d %H:%M")
    rule = iv["rule"]
    at = where(iv)
    if rule == "monthly":
        return f"{iv.get('monthly_label') or iv['label']}{who}"
    if rule == "ongoing":
        return f"{et} ongoing{who}{at}"
    if rule == "unresolved":
        return f"{et} of {start_txt(iv)}: unresolved, no end reported{who}{at}"
    if rule == "end_never_reported":
        return f"{et} of {start_txt(iv)}: unresolved, no end reported (off the map){who}"
    if rule == "not_reconfirmed":
        c = parse_time(iv.get("confirmed"))
        return f"{et}: last confirmed {c.astimezone(LOCAL).strftime('%b %-d') if c else 'unknown'}; not re-confirmed{who}"
    if rule == "discharge":
        return f"{et} in progress{who}{at}"
    if rule == "authority_window":
        return f"{et} ended {endtxt}; {int(iv['window_hours'])} h advice window{who}{at}"
    if rule == "caution":
        h = (iv.get("yellow_rule") or {}).get("hours")
        return f"{et} ended {endtxt}; caution to {int(h)} h after the end{who}{at}" if h else f"{et} ended {endtxt}{who}{at}"
    if rule == "no_end":
        return f"{et} with no reported end{who}{at}"
    if rule in ("text_caution", "code_caution"):
        was = (iv.get("rule_applied") or {}).get("replaces")
        what = {"ongoing": f"{et} ongoing", "discharge": f"{et} in progress",
                "authority_window": f"{et} ended {endtxt}"}.get(was, et)
        return f"{what}; site caution{who}{at}"
    if rule == "day_start_caution":
        h = (iv.get("rule_applied") or {}).get("hours")
        return (f"{et} reported to the day only, with no end; caution to {int(h)} h from the start of that day{who}{at}"
                if h else f"{et} reported to the day only, with no end{who}{at}")
    if rule in ("advisory_active", "rain_advisory"):
        tail = at if iv.get("placement") == "reach" and iv.get("reach") in _STRETCH_REACHES else ""
        return f"{et} in effect{who}{stretch_text(ev)}{tail}"
    return f"{iv['label']}{who}"


# ---------------------------------------------------------------- coverage and health

def registry_rows(sid: str, meta: dict, registry: dict) -> list[dict]:
    """The registry rows an ingester source stands for: its own yaml, the rows its meta names, the
    rows its own yaml names (feed yamls carry registry_ids too), then the alias table."""
    own = registry.get(sid) if isinstance(registry.get(sid), dict) else {}
    ids = ([sid] + list((meta or {}).get("registry_ids") or []) + list(own.get("registry_ids") or [])
           + REGISTRY_ALIASES.get(sid, []))
    return [registry[i] for i in dict.fromkeys(ids) if i in registry]


def merged_registry(sid: str, meta: dict, registry: dict) -> dict:
    """One registry view of an ingester source: states and event types unioned over its rows, the
    shortest parseable cadence."""
    rows = registry_rows(sid, meta, registry)
    out = {"ids": [r.get("id") for r in rows]}
    states, types, cads = set(), set(), []
    for r in rows:
        states.update(s for s in (r.get("states") or []) if isinstance(s, str))
        types.update(t for t in (r.get("event_types") or []) if isinstance(t, str))
        c = cadence_hours(r.get("cadence"))
        if c is not None:
            cads.append(c)
    if states:
        out["states"] = sorted(states)
    if types:
        out["event_types"] = sorted(types)
    if cads:
        out["cadence"] = min(cads)
    return out


def source_profile(sid: str, reg: dict, recs: list[dict], fixture: bool, meta: dict | None = None) -> dict:
    """What a source covers: its states, whether it reports discharges, statewide or per permit."""
    meta = meta or {}
    known = states()
    st_list = [s.upper() for s in (reg.get("states") or []) if isinstance(s, str) and s.upper() in known]
    if not st_list:
        m = re.match(r"([a-z]{2})-", sid)
        if m and m.group(1).upper() in known:
            st_list = [m.group(1).upper()]
        elif re.search(r"echo|epa|federal", sid):
            st_list = sorted(known)
    states_ = st_list
    types = {r.get("event_type") for r in recs} | set(reg.get("event_types") or [])
    permits = {r.get("npdes_permit") for r in recs if r.get("npdes_permit")}
    permits |= set(meta.get("covers_permits") or FEED_PERMITS.get(sid, []))
    statewide = meta.get("statewide") if meta.get("statewide") is not None else len(permits) >= 3
    return {"states": states_, "discharges": bool(types & DISCHARGE_TYPES), "statewide": bool(statewide) and not fixture,
            "permits": sorted(permits), "waters": list(meta.get("covers_waters") or []), "fixture": fixture}


def source_health(sid: str, f: dict, reg: dict, now: datetime) -> dict:
    reg_cad = cadence_hours(reg.get("cadence"))
    # an events file written once from a layer that no longer changes (meta.frozen: a --backfill of an archive)
    # has no expected cadence: it is never stale for its age, only for a failed read
    frozen = bool((f.get("meta") or {}).get("frozen"))
    cad = None if frozen else reg_cad if reg_cad is not None else default_cadence(sid)
    last_ok = parse_time(f.get("last_ok_at"))
    reasons = []
    if not f.get("fixture"):
        if f.get("ok") is False:
            reasons.append(f"last fetch failed: {f.get('error')}")
        if last_ok is None:
            reasons.append("never fetched successfully")
        elif cad is not None and now - last_ok > timedelta(hours=cad):
            reasons.append(f"last good fetch {iso(last_ok)} is older than the expected cadence ({cad:g} h)")
    return {"source_id": sid, "ok": f.get("ok"), "error": f.get("error"), "fetched_at": f.get("fetched_at"),
            "last_ok_at": f.get("last_ok_at"), "count": f.get("records"), "fixture": f.get("fixture"),
            "expected_cadence_hours": cad,
            "published_in_batches": bool((f.get("meta") or {}).get("published_in_batches")),
            "cadence_from": "frozen" if frozen else "registry" if reg_cad is not None else "default",
            "registry_ids": reg.get("ids") or [],
            "stale": bool(reasons), "stale_reason": "; ".join(reasons) or None}


# ---------------------------------------------------------------- build

PLACEMENT_CACHE = BUILD_DIR / "placement-cache.json"
PLACEMENT_CACHE_DAYS = 120      # records that began longer ago than this reuse their placement while nothing changed


def outline_files(waters) -> list:
    """The outlines placement reads from openboatlaunch's folder (water_geometry: a record with no inline geometry),
    as (slug, geometry_hash, present) for a record whose extract carries the hash, else (slug, size, modified) or
    (slug, None) where there is none: a moved outline, or a machine without the folder
    (the hosted runner has none), is a placement input like the records themselves (review 2026-11-04)."""
    out = [str(OBL_WATER_DIR)]
    for slug in sorted(waters):
        if (waters[slug] or {}).get("geometry"):
            continue
        gh = (waters[slug] or {}).get("geometry_hash")
        if gh:
            # openboatlaunch's API records name their outline's hash (the extract carries it): a changed outline
            # changes the hash, and a folder unpacked again (new file times) with the same outlines does not
            out.append((slug, gh, (OBL_WATER_DIR / f"{slug}.json").is_file()))
            continue
        try:
            st = (OBL_WATER_DIR / f"{slug}.json").stat()
            out.append((slug, st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((slug, None))
    return out


def placement_stamp(waters, outfalls, discharger_towns, discharger_waters, rules, states) -> str:
    """Everything a placement is made from besides the record: the water records, the outlines read from
    openboatlaunch's folder (outline_files), the outfall registry, the operators' towns and receiving waters, the
    rules, the live states, the placement steps switched on (PLACE_STEPS), the code (this module, build/redact.py,
    common.py) and the name lists. A change to any of them places every record again."""
    import hashlib
    import sys as _sys
    from build import redact as _redact
    h = hashlib.sha256(json.dumps([waters, outline_files(waters), outfalls, discharger_towns, discharger_waters, rules,
                                   sorted(states), PLACE_STEPS], sort_keys=True, default=str).encode())
    for f in (Path(__file__), Path(_redact.__file__), Path(_sys.modules["common"].__file__),
              DATA_DIR / "name-allowlist.json", BUILD_DIR / "name-blocklist.json"):
        h.update(f.read_bytes() if f.exists() else b"-")
    return h.hexdigest()


def record_hash(ev: dict) -> str:
    import hashlib
    return hashlib.blake2b(json.dumps(ev, sort_keys=True, default=str).encode(), digest_size=16).hexdigest()


def build(include_fixtures: bool = False, now: datetime | None = None, events_dir: Path = EVENTS_DIR,
          write: bool = True, waters: dict | None = None, outfalls: list | None = None,
          registry: dict | None = None, include_restricted: bool = False, rules: dict | None = None,
          reaches: dict | None = None, flows: tuple | None = None, discharger_towns: dict | None = None,
          rain: dict | None = None, discharger_waters: dict | None = None, discharger_aliases_map: dict | None = None,
          placement_cache: Path | None | bool = True, live_only: bool = False):
    """rain: {"rainfall", "history", "thresholds"} (build/rain_likely.py); read from data/build/ when
    None and rules.rain_likely.enabled is true. Placement reads every outfall registry file
    (load_registry_outfalls) when outfalls is None, else the outfalls given.
    placement_cache: a record that began more than PLACEMENT_CACHE_DAYS ago keeps the placement the last run made
    for it when the record and everything placement reads are unchanged (placement_stamp, record_hash): with the
    history of a state on file (Michigan from 2001, some 55,000 records) placing every record again took 30 s an
    hour. Everything else (intervals, colours, counts) is computed for every record as before. True: the file
    PLACEMENT_CACHE when this build writes the shared outputs (write and the default events directory); a path: that
    file; None or False: no cache."""
    now = now or datetime.now(UTC)
    loaded = waters is None
    waters = load_waters() if loaded else waters
    alias_problems = list(ALIAS_PROBLEMS) if loaded else []
    placement_outfalls = load_registry_outfalls() if outfalls is None else outfalls
    outfalls = load_outfalls() if outfalls is None else outfalls
    registry = load_registry() if registry is None else registry
    files, events, problems = load_events(events_dir, include_fixtures, include_restricted,
                                          live=rules_live_states(rules if rules is not None else load_rules()) if live_only else None)
    if live_only and NOT_LIVE:
        by_state = defaultdict(int)
        for _, st in NOT_LIVE:
            by_state[st] += 1
        print(f"status: records of states not yet live left out (rules.json live_states): {dict(sorted(by_state.items()))}")
    problems.extend(alias_problems)
    # an event's discharger_id that the operator registry lists as an alias is read as the row's id here, as the
    # export publishes it: placement's operator towns and receiving waters, the guard's town check and
    # red.by_discharger see the registry id (review 2026-11-03 P2-3); the ingester's id stays in discharger_id_source
    events = canonical_dischargers(events, discharger_aliases() if discharger_aliases_map is None else discharger_aliases_map)
    withheld = list(WITHHELD)
    rules = load_rules() if rules is None else rules
    global _STATES
    _STATES = derive_states(waters, rules)      # one state set for placement, the guard, windows and counts
    waters = live_waters(waters, _STATES)       # records of states not yet live stay out of everything below
    if reaches is None:
        from build import reaches as reaches_mod
        reaches = reaches_mod.load_reaches()
    shore = SH.rule(rules)
    shore_slugs = SH.shoreline_slugs(waters, shore)      # the Great Lakes records: a stretch, never a whole-lake fill
    ocean_slugs = {x for x in shore_slugs if SH.is_ocean(waters[x], shore)}     # and the open ocean's (the same model)
    _SHORE_REACHES.clear()
    _SHORE_REACHES.update(k for k, r in (reaches or {}).items() if r.get("model") == SH.MODEL)
    _STRETCH_REACHES.clear()
    _STRETCH_REACHES.update(k for k, r in (reaches or {}).items() if r.get("kind") == ADVISORY_STRETCH)
    stretch_of_event = stretch_traces(reaches)
    if flows is None:
        from build import reaches as reaches_mod
        flows = (read_json(reaches_mod.GAUGES_BY_RIVER) or {}, read_json(reaches_mod.GAUGES_LATEST) or {})
    reach_index = index_reaches(reaches)
    if not rules.get("version"):
        problems.append("data/rules.json missing or without a version: no red windows, no caution windows")
    discharger_towns = load_discharger_towns() if discharger_towns is None else discharger_towns
    discharger_waters = load_discharger_waters() if discharger_waters is None else discharger_waters
    resolver = Resolver(waters, placement_outfalls, discharger_towns, discharger_waters, rules.get("placement") or {})
    if placement_cache is True:
        placement_cache = PLACEMENT_CACHE if write and Path(events_dir) == Path(EVENTS_DIR) else None
    cache_old, cache_new, cache_stamp = {}, {}, None
    if placement_cache:
        cache_stamp = placement_stamp(waters, placement_outfalls, discharger_towns, discharger_waters, rules, _STATES)
        try:
            c = read_json(Path(placement_cache)) or {}
        except (OSError, ValueError):
            c = {}
        if c.get("stamp") == cache_stamp:
            cache_old = c.get("placements") or {}
    cache_before = (now - timedelta(days=PLACEMENT_CACHE_DAYS)) if placement_cache else None
    cache_hits = 0

    # live records supersede fixture traces of the same record; revisions supersede parents
    live_ids = set()
    for ev in events:
        if not ev["_fixture"]:
            live_ids.add(str(ev.get("source_record_id")))
            live_ids.update(str(x) for x in (ev.get("raw") or {}).get("_match_ids", []))
    dropped = []
    kept = []
    for ev in events:
        mids = set((ev.get("raw") or {}).get("_match_ids") or [])
        if ev["_fixture"] and mids & live_ids:
            dropped.append(ev["event_id"])
            continue
        kept.append(ev)
    events = kept
    by_id = {}
    for ev in events:
        if ev["event_id"] in by_id:
            problems.append(f"duplicate event_id {ev['event_id']} ({ev['_file']})")
        by_id[ev["event_id"]] = ev

    superseded, effective = resolve_revisions(events, by_id)
    placements, per_water_events, intervals = {}, defaultdict(list), defaultdict(list)
    unknown_slugs = defaultdict(int)
    invalid_times = defaultdict(int)
    future_starts = defaultdict(int)
    reach_ivs, reach_events, reaches_on_water = defaultdict(list), defaultdict(list), defaultdict(set)
    needs_reach = []        # recent river discharges with a point but no traced reach: build.reaches traces them
    aside_events = defaultdict(lambda: defaultdict(int))
    duplicates = find_duplicates(events)
    for ev in events:               # an ingester's own duplicate_of (CT annual sheet -> dashboard) wins
        if ev.get("duplicate_of") and ev["duplicate_of"] != ev["event_id"]:
            duplicates[ev["event_id"]] = ev["duplicate_of"]
    h_start = now - timedelta(days=HISTORY_DAYS)
    points = []
    latest_month = {}       # outfall -> (event, water slugs, monthly mark) of its latest month report
    for ev in events:
        eid = ev["event_id"]
        began = parse_time(ev.get("started_at") or ev.get("reported_at")) if cache_before else None
        if began is not None and began < cache_before:
            h = record_hash(ev)
            hit = cache_old.get(eid)
            if hit and hit[0] == h:
                pl = copy.deepcopy(hit[1])
                cache_hits += 1
            else:
                pl = resolver.resolve(ev)
            cache_new[eid] = [h, copy.deepcopy(pl)]
        else:
            pl = resolver.resolve(ev)
        placements[eid] = {k: v for k, v in pl.items() if k != "unknown_slugs"}
        if pl.get("set_aside"):
            aside_events[ev["source_id"]][("still placed" if pl["water_slugs"] else "left unplaced")] += 1
        if eid in superseded:
            placements[eid]["superseded"] = superseded[eid]
        if eid in duplicates:
            placements[eid]["duplicate_of"] = duplicates[eid]
        tp = time_problem(ev, now, rules)
        future = bool(future_start(ev, now))   # kept and listed; no status, reach or colour (FUTURE_START_H)
        if tp:
            placements[eid]["validation_error"] = tp
            if time_problem(ev):
                invalid_times[ev["source_id"]] += 1
        if future:
            placements[eid]["future_start"] = True
            future_starts[ev["source_id"]] += 1
        assumed = end_assumed(ev, now, rules)
        if assumed:             # no end reported, 30 days on: the site assumes it ended (owner, 2026-11-03)
            placements[eid]["end_assumed_at"] = iso(assumed)
            when = f"{assumed.astimezone(LOCAL):%b} {assumed.astimezone(LOCAL).day}, {assumed.astimezone(LOCAL).year}"
            days = int(unresolved_days(rules))
            placements[eid]["note"] = "; ".join(x for x in (placements[eid].get("note"), (
                f"the published end ({ev.get('ended_at')}) is not used: this site assumes the discharge ended {days} days "
                f"after it began ({when}) and it colours nothing since; no usable end was reported"
                if ev.get("ended_at") else
                f"no end was reported: this site assumes the discharge ended {days} days after it "
                f"began ({when}) and it colours nothing since; the end was never reported")) if x)
        for s in pl["unknown_slugs"]:
            unknown_slugs[s] += 1
        eff = effective.get(eid, ev)
        point_on, river_point = [], []
        live = eid not in superseded and eid not in duplicates
        is_discharge = ev.get("event_type") in DISCHARGE_TYPES or (
            ev.get("event_type") == "unknown" and ev.get("status") == "ongoing")
        coarse = ev.get("time_precision") in COARSE_PRECISION     # a monthly or annual total: never a reach
        found = event_reaches(ev, pl, reach_index) if is_discharge and not pl.get("no_receiving_water") \
            and not future and not coarse else []
        # an authority's advisory for a named stretch: its traced stretch, else a marker at its point (never the
        # whole water: SOL wave2 P1-3)
        stretched = not is_discharge and not future and has_stretch(ev)
        traced = False
        if stretched:
            sr = stretch_of_event.get(eid)
            if sr and sr.get("segments") and sr.get("cut_reason") != "no_trace":
                found, traced = [(sr, None)], True
            else:
                placements[eid]["stretch_fallback"] = stretch_fallback(sr)
        # rivers, and the shoreline lakes, whose stretches carry a report as a river reach does
        river_slugs = [x for x in pl["water_slugs"] if waters[x].get("kind") in RIVER_KINDS or x in shore_slugs]
        # the river waters each reach carries: all of the record's (its own outfall or point), or the water of the
        # one registry outfall it starts at (a report naming several outfalls: one reach per outfall)
        carry = [(r, list(river_slugs) if s is None else [x for x in river_slugs if x == s]) for r, s in found]
        modeled = [(r, c) for r, c in carry if r.get("segments") and c]
        carried = {x for _, c in modeled for x in c}
        reach = found[0][0] if found else None
        if reach:
            placements[eid]["reach"] = reach["key"]
            if len(found) > 1:
                placements[eid]["reaches"] = [r["key"] for r, _ in found]
        for slug in pl["water_slugs"]:
            per_water_events[slug].append(eid)
            if not live:
                continue
            on_river = advisory_on_river(ev, waters[slug], traced)
            if on_river or (ev.get("event_type") in POINT_ADVISORY_TYPES and not colours_whole_water(waters[slug])):
                point_on.append(slug)
                if on_river:
                    river_point.append(slug)
                if on_river or not names_its_water(ev):
                    continue                   # a station's advisory, or any advisory on a river: its marker only
            if slug in carried:
                continue                       # a reach carries it (below)
            tag = None
            if is_discharge and slug in shore_slugs:
                tag = "ocean_shore_unmodeled" if slug in ocean_slugs else "shoreline_unmodeled"
            elif is_discharge and slug in river_slugs:
                cut = [r for r, c in carry if slug in c]
                tag = "tidal" if any(r.get("cut_reason") in ("tidal_at_outfall", "lake_at_outfall") for r in cut) \
                    else "unmodeled"
            elif is_discharge and waters[slug].get("kind") in ("bay", "sound"):
                tag = "tidal"
            for iv in event_intervals(eff, waters[slug].get("state"), now, water={**waters[slug], "slug": slug},
                                      rules=rules):
                iv["placement"] = tag
                intervals[slug].append(iv)
        if (is_discharge and live and not future and not coarse and river_slugs and not reach and ev.get("lat") is not None
                and (parse_time(ev.get("started_at")) or now) > now - timedelta(days=30)):
            first = next((x for x in river_slugs if x not in shore_slugs), river_slugs[0])     # a river first
            needs_reach.append({"event_id": eid, "lat": ev["lat"], "lon": ev["lon"], "water_slug": first,
                                "permit": ev.get("npdes_permit"),
                                **({"model": SH.MODEL} if first in shore_slugs else {})})
        if modeled and live:
            done = set()                # one record colours a water once, however many of its reaches run along it
            for reach, carries in modeled:
                start_slug = reach.get("water_slug") if reach.get("water_slug") in waters else carries[0]
                w0 = {**waters[start_slug], "slug": start_slug}
                ivs = event_intervals(eff, w0.get("state"), now, water=w0, rules=rules)
                for iv in ivs:
                    reach_ivs[reach["key"]].append({**iv, "placement": "reach", "reach": reach["key"]})
                on_reach = set(reach_waters(reach, waters)) | {start_slug}
                for slug in sorted(on_reach | set(carries)):
                    if eid not in per_water_events[slug]:
                        per_water_events[slug].append(eid)
                    reaches_on_water[slug].add(reach["key"])
                    if slug in done:
                        continue
                    done.add(slug)
                    tag = "reach" if slug in on_reach else "named"
                    for iv in ivs:
                        intervals[slug].append({**iv, "placement": tag, "reach": reach["key"]})
                reach_events[reach["key"]].append(eid)
        # the monthly mark (docs/plan.md §2.x): the reported month in the history, and the outfall's latest report
        mark = monthly_mark(ev) if live and pl["water_slugs"] else None
        if mark:
            if mark["discharged"]:
                for slug in pl["water_slugs"]:
                    intervals[slug].append(monthly_interval(ev, mark))
            okey = (ev.get("npdes_permit") or ev.get("source_id"),
                    oid_key(ev.get("outfall_id")) if ev.get("outfall_id") else tuple(pl["water_slugs"]))
            if okey not in latest_month or (mark["month"], eid) > (latest_month[okey][2]["month"], latest_month[okey][0]["event_id"]):
                latest_month[okey] = (ev, list(pl["water_slugs"]), mark)
        # a report with no point (Hawaii's notices give none) placed on a water that is never filled whole (a stream, river,
        # bay or sound) and drawn by no traced reach: its marker at a point of that water's record, so it shows in its
        # colour (final audit 2026-11-07 P2-4); keyed on ISLAND_STATES, every other state unchanged
        nofill = [x for x in pl["water_slugs"] if waters[x].get("kind") in NO_FILL_KINDS]
        pick = point_on or ([] if (is_discharge and traced) or not is_discharge else nofill)
        rp = record_point(pick[0], waters) if (pick and live and not future and ev.get("lat") is None
                                                and event_state(ev) in ISLAND_STATES) else None
        if rp:
            ivs = event_intervals(eff, event_state(ev), now, water={**waters[pick[0]], "slug": pick[0]}, rules=rules)
            colouring = [iv for iv in ivs if iv["color"] != "grey"]
            if colouring and any(iv["end"] is None or iv["end"] > h_start for iv in colouring):
                col, act = status_at(ivs, now)
                top = max(act, key=lambda iv: RANK[iv["color"]]) if act else None
                points.append({"event_id": eid, "water_slugs": list(pick), "status": col,
                               "category": category_of(ev.get("event_type")),
                               "rule": top["rule"] if top else None, "label": top["label"] if top else None,
                               "short": short_reason(top, ev) if top else None,
                               "from": iso(min(iv["start"] for iv in colouring)),
                               "until": None if any(iv["end"] is None for iv in colouring)
                               else iso(max(iv["end"] for iv in colouring)),
                               "intervals": [[iso(iv["start"]), iso(iv["end"]), iv["color"], iv["rule"]]
                                             for iv in sorted(ivs, key=lambda x: x["start"])],
                               "_ivs": ivs, "lat": rp[0], "lon": rp[1], "point_basis": rp[2],
                               "why": RECORD_POINT_WHY})
        # beach, rain and HAB advisories that colour no water: a marker of their own
        if ((ev.get("event_type") in POINT_ADVISORY_TYPES or point_on) and eid not in superseded and eid not in duplicates
                and ev.get("lat") is not None and ev.get("lon") is not None
                and (point_on or not pl["water_slugs"])):
            ivs = event_intervals(eff, event_state(ev), now, rules=rules)
            colouring = [iv for iv in ivs if iv["color"] != "grey"]
            if colouring and any(iv["end"] is None or iv["end"] > h_start for iv in colouring):
                col, act = status_at(ivs, now)
                top = max(act, key=lambda iv: RANK[iv["color"]]) if act else None
                points.append({"event_id": eid, "water_slugs": point_on, "status": col,
                               "category": category_of(ev.get("event_type")),
                               "rule": top["rule"] if top else None, "label": top["label"] if top else None,
                               "short": short_reason(top, ev) if top else None,
                               "from": iso(min(iv["start"] for iv in colouring)),
                               # the end of the colouring, not of the explanatory grey note after it
                               "until": None if any(iv["end"] is None for iv in colouring)
                               else iso(max(iv["end"] for iv in colouring)),
                               "intervals": [[iso(iv["start"]), iso(iv["end"]), iv["color"], iv["rule"]]
                                             for iv in sorted(ivs, key=lambda x: x["start"])],
                               "_ivs": ivs,
                               # an advisory whose stretch is not traced: why it is a point (SOL wave2 P1-3)
                               **({"stretch_fallback": placements[eid]["stretch_fallback"]}
                                  if stretched and placements[eid].get("stretch_fallback") else {}),
                               "why": ("the advisory covers the stretch it names, drawn from end to end; the marker "
                                       "is its point" if point_on and traced else
                                       (placements[eid]["stretch_fallback"] if stretched else RIVER_POINT_WHY)
                                       if river_point and (names_its_water(ev) or
                                                           ev.get("event_type") not in POINT_ADVISORY_TYPES)
                                       else "the advisory covers the water it names; the marker is its point"
                                       if point_on and names_its_water(ev) else
                                       "water is not a lake, pond or reservoir under 50 km²" if point_on
                                       else "not placed on a water")})

    # the current map's monthly marks: an outfall whose latest report is a month total with discharge, its month
    # ended within MONTHLY_CURRENT_DAYS (docs/plan.md §2.x)
    monthly_now, monthly_outfalls = defaultdict(list), []
    observed = latest_observations(files)       # zero months included: a newer zero month clears the mark (SOL P2-7)
    for okey, (mev, mslugs, mk) in sorted(latest_month.items(), key=lambda kv: str(kv[0])):
        if not mk["discharged"] or mk["end"] <= now - timedelta(days=MONTHLY_CURRENT_DAYS) or mk["start"] > now:
            continue
        obs = observed.get((mev.get("source_id"), okey[0], okey[1]))
        if obs and obs["month"] > mk["month"] and not obs.get("discharged", True):
            continue
        row = {"event_id": mev["event_id"], "source_id": mev.get("source_id"), "npdes_permit": mev.get("npdes_permit"),
               "outfall_id": mev.get("outfall_id"), "outfall_name": mev.get("outfall_name"), "water_slugs": mslugs,
               "lat": mev.get("lat"), "lon": mev.get("lon"), "status": "monthly", "days": mk["days"],
               "events": mk["events"], "month": mk["month"], "received_at": mk["received_at"],
               "retrieved_at": mk["retrieved_at"], "label": mk["label"], "from": iso(mk["start"]), "until": iso(mk["end"]),
               "discharger_id": mev.get("discharger_id"), "discharger_name": mev.get("discharger_name")}
        monthly_outfalls.append(row)
        for slug in mslugs:
            monthly_now[slug].append(row)

    # coverage: events placed on the water, and feeds that cover its outfalls
    recs_by_source = defaultdict(list)
    for ev in events:
        recs_by_source[ev.get("source_id")].append(ev)
    covered = defaultdict(set)
    for slug, ids in per_water_events.items():
        for i in ids:
            covered[slug].add(by_id[i]["source_id"])
    regs = {sid: merged_registry(sid, f.get("meta") or {}, registry) for sid, f in files.items()}
    profiles = {sid: source_profile(sid, regs[sid], recs_by_source.get(sid, []), f["fixture"], f.get("meta") or {})
                for sid, f in files.items()}
    for sid, prof in profiles.items():
        for slug in prof["waters"]:
            if slug in waters:
                covered[slug].add(sid)
    for o in outfalls:
        slug = resolver.canon(o.get("water_slug"))
        if slug not in waters:
            continue
        for sid, prof in profiles.items():
            if not prof or not prof["discharges"] or o.get("state") not in prof["states"]:
                continue
            if prof["statewide"] or o.get("npdes_permit") in prof["permits"]:
                covered[slug].add(sid)
    health = {sid: source_health(sid, f, regs[sid], now) for sid, f in files.items()}
    # one permittee of a multi-permittee feed failed while the others succeeded (meta.partial_failures):
    # its waters are stale even though the file says ok
    partial_stale = defaultdict(list)
    for sid, f in files.items():
        for who, pf in ((f.get("meta") or {}).get("partial_failures") or {}).items():
            if not isinstance(pf, dict):
                continue
            slugs = set(pf.get("water_slugs") or [])
            prefix = pf.get("event_id_prefix")
            if prefix:
                slugs |= {sl for sl, ids in per_water_events.items() if any(i.startswith(prefix) for i in ids)}
            for sl in slugs:
                if sl not in waters:
                    continue
                covered[sl].add(sid)
                partial_stale[sl].append({"source_id": sid, "permittee": who, "last_ok_at": pf.get("last_ok_at"),
                                          "reason": f"{who}: {pf.get('error')} (last good fetch {pf.get('last_ok_at')})"})

    # discharge likely: heavy rain over a CSO permittee's outfalls, no notice received (rules.rain_likely)
    from build import rain_likely as rain_mod
    rain_block = {"enabled": False, "rule": "rain_likely", "label": RULES["rain_likely"][1]}
    if rain_mod.enabled(rules):
        rain = rain_mod.load_inputs() if rain is None else rain
        try:            # a rainfall problem never stops the status build
            by_water, by_reach, rain_block = rain_mod.compute(rain, rules, events, now, h_start, waters, outfalls,
                                                              reaches, reach_waters)
        except Exception as e:  # noqa: BLE001
            by_water, by_reach = {}, {}
            rain_block = {**rain_block, "enabled": True, "error": f"{type(e).__name__}: {e}"[:300]}
            problems.append(f"rain_likely: not computed ({type(e).__name__}: {e})"[:300])
        # the rainfall watch covers every CSO permittee's waters: the radar's, or New Jersey's shared site's
        for slug, w in (rain_block.get("waters") or {}).items():
            if slug in waters:
                covered[slug].update(w.get("sources") or [rain_mod.SOURCE_ID])
        for slug, ivs in by_water.items():
            intervals[slug].extend(ivs)
            covered[slug].update({iv.get("source_id") or rain_mod.SOURCE_ID for iv in ivs})
            for iv in ivs:
                reaches_on_water[slug].update(k for k in [iv.get("reach"), *(iv.get("reaches") or [])] if k)
        for key, ivs in by_reach.items():
            reach_ivs[key].extend(ivs)
        hf = rain_mod.health_file(rain)
        if hf:
            health[rain_mod.SOURCE_ID] = source_health(
                rain_mod.SOURCE_ID, hf, {"cadence": rain_mod.settings(rules)["cadence_hours"],
                                         "ids": [rain_mod.SOURCE_ID, rain_mod.QPF_SOURCE_ID]}, now)
        sf = rain_mod.site_health_file(rain)
        if sf:          # New Jersey's shared notification site, read every refresh (ingest/nj_cso_likely.py)
            health[rain_mod.SITE_SOURCE_ID] = source_health(
                rain_mod.SITE_SOURCE_ID, sf, {"cadence": rain_mod.settings(rules)["cadence_hours"],
                                              "ids": ["nj-njcso-group-interim-outlook"]}, now)
        problems.extend(f"rain_likely: {p}" for p in rain_block.get("problems") or [])

    # history frame
    h_end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    n_hours = HISTORY_DAYS * 24
    h0 = h_end - timedelta(hours=n_hours - 1)
    hours = [iso(h0 + timedelta(hours=i)) for i in range(n_hours)]

    out_waters, strips, hist_ivs = {}, {}, {}
    counts = defaultdict(lambda: defaultdict(int))
    cat_counts = defaultdict(lambda: defaultdict(int))      # category -> status -> waters
    for slug in sorted(covered):
        w = waters[slug]
        ivs = intervals.get(slug, [])
        color, active = status_at(ivs, now)
        active = sorted(active, key=lambda iv: (-RANK[iv["color"]], -(iv["start"].timestamp())))
        since = since_of(ivs, now, color)
        # the monthly marks stand whenever no sewage discharge, caution or unresolved report does (a beach or bloom
        # advisory on the water keeps its colour, and the mark its own line: docs/plan.md §2.z)
        sew = max((RANK[iv["color"]] for iv in active if (iv.get("category") or "sewage") == "sewage"), default=-1)
        marks = [] if sew > RANK["monthly"] else monthly_now.get(slug, [])
        if marks and RANK[color] < RANK["monthly"]:        # only a monthly report is the latest word here
            color = "monthly"
            since = max(parse_time(m["from"]) for m in marks)
        reasons = []
        for iv in active:
            ev = by_id.get(iv["event_id"])
            reasons.append({"event_id": iv["event_id"], "source_id": iv["source_id"], "fixture": iv["fixture"],
                            "status": iv["color"], "rule": iv["rule"], "label": iv["label"],
                            "short": short_reason(iv, ev), "event_type": iv["event_type"],
                            "event_status": iv["event_status"], "from": iso(iv["start"]), "until": iso(iv["end"]),
                            "authority": iv["authority"], "window_hours": iv["window_hours"],
                            "window_basis": iv["window_basis"], "started_at": iv["started_at"],
                            "confirmed": iv.get("confirmed"), "ended_by": iv.get("ended_by"),
                            "red_rule": iv.get("red_rule"), "yellow_rule": iv.get("yellow_rule"),
                            "rule_applied": iv.get("rule_applied"), "placement": iv.get("placement"),
                            **({"end_not_used": iv["end_not_used"]} if iv.get("end_not_used") else {}),
                            # the water comes from the notice's text against its form's flag (TEXT_OVER_FLAG)
                            **({"text_over_flag": iv["text_over_flag"]} if iv.get("text_over_flag") else {}),
                            # why a stretch is not traced (kept for any interval that carries it)
                            **({"stretch_fallback": iv["stretch_fallback"]} if iv.get("stretch_fallback") else {}),
                            "reach": iv.get("reach"), "category": iv.get("category") or "sewage",
                            "ended_at": iv["ended_at"],
                            # rain_likely: the radar total, the threshold and its basis (build/rain_likely.py)
                            **({"permit": iv.get("permit"), "rain": iv["rain"]} if iv.get("rain") else {}),
                            # which amount set it: operator, state or default (the label follows it)
                            **({"trigger_basis": iv.get("trigger_basis")} if iv["rule"] == "rain_likely" else {}),
                            **({k: iv.get(k) for k in ("days", "events", "month", "received_at", "retrieved_at",
                                                       "monthly_label")} if iv["rule"] == "monthly" else {})})
        have = {r["event_id"] for r in reasons}
        for m in marks:                 # the outfalls' latest monthly reports (not inside their month now)
            if m["event_id"] in have:
                continue
            ev = by_id.get(m["event_id"]) or {}
            reasons.append({"event_id": m["event_id"], "source_id": m["source_id"], "fixture": bool(ev.get("_fixture")),
                            "status": "monthly", "rule": "monthly", "label": RULES["monthly"][1], "short": m["label"],
                            "event_type": ev.get("event_type"), "event_status": ev.get("status"), "from": m["from"],
                            "until": None, "authority": ev.get("authority") or ev.get("discharger_name"),
                            "window_hours": None, "window_basis": None, "started_at": ev.get("started_at"),
                            "confirmed": None, "ended_by": None, "red_rule": None, "yellow_rule": None,
                            "rule_applied": {"rule": "monthly", "rationale": "the outfall's latest report is a monthly "
                                             "total: days with discharge, dates not given", "methods": "monthly"},
                            "placement": None, "reach": None, "ended_at": ev.get("ended_at"), "category": "sewage",
                            **{k: m.get(k) for k in ("days", "events", "month", "received_at", "retrieved_at",
                                                     "npdes_permit", "outfall_id")}, "monthly_label": m["label"]})
        # the status card: every reason that sets a colour first, sewage before beach before bloom (the headline is
        # the strongest sewage status), strictest and newest first within each (docs/plan.md §2.z)
        reasons.sort(key=lambda r: precedence(r.get("category"), r["status"]))
        # several operators' rain cautions on one water: the strongest basis first (an operator's own amount, then a
        # state's trigger, then this site's default) in the places those reasons already hold, so reasons[0], the
        # reason_short, the overlay's rain_trigger_basis and the page's first line read as the water's rain context
        # and badge do (rain_likely.strongest_basis); every other reason keeps its place
        at = [i for i, r in enumerate(reasons) if r["rule"] == "rain_likely"]
        if len(at) > 1:
            rank = {b: n for n, b in enumerate(rain_mod.TRIGGER_BASES)}
            for i, r in zip(at, sorted((reasons[i] for i in at), key=lambda r: rank.get(r.get("trigger_basis"), len(rank)))):
                reasons[i] = r
        by_cat = {c: "grey" for c in CATEGORIES}
        for r in reasons:
            c = r.get("category") or "sewage"
            if RANK[r["status"]] > RANK[by_cat[c]]:
                by_cat[c] = r["status"]
        head = min(CATEGORIES, key=lambda c: (precedence(c, by_cat[c]), CATEGORIES.index(c)))
        # newest first; a start in the future as published is never the latest report: listed last
        ev_ids = sorted(set(per_water_events.get(slug, [])),
                        key=lambda i: (not placements[i].get("future_start"), by_id[i].get("started_at") or ""),
                        reverse=True)
        stale = [{"source_id": s, "last_ok_at": health[s]["last_ok_at"], "reason": health[s]["stale_reason"]}
                 for s in sorted(covered[slug]) if s in health and health[s]["stale"]] + partial_stale.get(slug, [])
        kind = w.get("kind")
        on_reach_now = any(r.get("placement") == "reach" and r["status"] != "grey"
                           and r.get("reach") not in _STRETCH_REACHES for r in reasons)
        on_stretch_now = any(r.get("placement") == "reach" and r["status"] != "grey"
                             and r.get("reach") in _STRETCH_REACHES for r in reasons)
        out_waters[slug] = {
            "name": w.get("name"), "kind": kind, "state": w.get("state"),
            "status": color, "since": iso(since), "reason_short": reasons[0]["short"] if reasons else None,
            # by category (docs/plan.md §2.z): each category's status now, and the headline: the strongest sewage
            # status, else the beach or bloom advisory ("Algal bloom advisory" for a water with only a bloom)
            "status_by_category": by_cat,
            "headline": {"category": head, "status": by_cat[head],
                         "label": None if head == "sewage" else CATEGORY_LABEL[head]},
            "fill": kind not in NO_FILL_KINDS and slug not in shore_slugs,
            "status_basis": ("modeled reaches" if kind in RIVER_KINDS else
                             OCEAN_STATUS_BASIS if slug in ocean_slugs else
                             SOUND_STATUS_BASIS if slug in shore_slugs and kind == "sound" else
                             BAY_STATUS_BASIS if slug in shore_slugs and kind == "bay" else
                             "markers only: tidal or estuary, movement not modeled" if kind in ("bay", "sound")
                             else SHORE_STATUS_BASIS if slug in shore_slugs else "whole water"),
            "summary": (SHORE_SUMMARY if slug in shore_slugs else "part of this water is on a modeled reach")
            if on_reach_now else STRETCH_SUMMARY if on_stretch_now else None,
            **({"stretch_model": SH.MODEL} if slug in shore_slugs else {}),
            "reaches": sorted(reaches_on_water.get(slug, [])),
            "unresolved_events": sorted({r["event_id"] for r in reasons if r["rule"] in ("unresolved", "end_never_reported")}),
            "reasons": reasons, "events": ev_ids, "covered_by": sorted(covered[slug]),
            **({"rain": rain_mod.water_context(rain_block, slug)} if rain_block.get("waters", {}).get(slug) else {}),
            **water_rules(reasons, w, slug, rules),
            "stale": bool(stale), "stale_sources": stale,
            "fixture_only": all(health.get(s, {}).get("fixture") for s in covered[slug]),
        }
        counts[w.get("state")][color] += 1
        for c, col in by_cat.items():
            cat_counts[c][col] += 1

        strips[slug] = paint(ivs, h0, h_end, n_hours)
        hist_ivs[slug] = [[iso(iv["start"]), iso(iv["end"]), iv["color"], iv["rule"], iv["event_id"],
                           iv.get("category") or "sewage"]
                          for iv in sorted(ivs, key=lambda x: x["start"])
                          if iv["end"] is None or iv["end"] > h0]

    # reaches: status now, travel band for active events, hourly strips
    gauges, latest = flows
    out_reaches, reach_strips, reach_hist, active_reach_events = {}, {}, {}, []
    for key, ivs in sorted(reach_ivs.items()):
        r = reaches[key]
        color, act = status_at(ivs, now)
        out_reaches[key] = {"permit": r.get("permit"), "outfall": r.get("outfall"), "water_slug": r.get("water_slug"),
                            "river": r.get("river"), "length_km": r.get("length_km"), "cut_reason": r.get("cut_reason"),
                            "status": color, "events": sorted(set(reach_events[key])),
                            "active": sorted({iv["event_id"] for iv in act
                                              if iv["color"] != "grey" and iv["rule"] != "rain_likely"}),
                            "rain_likely": sorted({iv["event_id"] for iv in act if iv["rule"] == "rain_likely"}),
                            # the amount behind the reach's rain caution now (operator, state, default), else None
                            "rain_trigger_basis": rain_mod.strongest_basis(iv.get("trigger_basis") for iv in act
                                                                            if iv["rule"] == "rain_likely"),
                            **({"model": SH.MODEL, "states": r.get("states") or [], "waters": r.get("waters") or []}
                               if r.get("model") == SH.MODEL else {}),
                            # an advisory's named stretch: its own kind and category, the advisory and both ends
                            **({"kind": ADVISORY_STRETCH, "category": category_of((r.get("advisory") or {}).get(
                                "event_type") or "beach_advisory"), "advisory": r.get("advisory"),
                                "stretch": r.get("stretch"), "rule_applied": r.get("rule"),
                                "stretch_trace": r.get("stretch_trace"), "state": r.get("state")}
                               if r.get("kind") == ADVISORY_STRETCH else {})}
        reach_strips[key] = paint(ivs, h0, h_end, n_hours)
        hist_cat = out_reaches[key].get("category") or "sewage"
        reach_hist[key] = [[iso(iv["start"]), iso(iv["end"]), iv["color"], iv["rule"], iv["event_id"], hist_cat]
                           for iv in sorted(ivs, key=lambda x: x["start"]) if iv["end"] is None or iv["end"] > h0]
        by_event = defaultdict(list)
        for iv in act:
            if iv["color"] != "grey" and iv["rule"] != "rain_likely":     # no discharge, no travel band
                by_event[iv["event_id"]].append(iv)
        if by_event:
            from build import reaches as reaches_mod
            try:        # a travel estimate never stops the status build
                if r.get("model") == SH.MODEL or r.get("kind") == ADVISORY_STRETCH:
                    raise _NoTravel()   # a lake shore (no flow) or an advisory's named stretch: no travel time
                flow = reaches_mod.flow_for(r, gauges, latest, now)
                band = reaches_mod.travel(r["segments"], flow["q_ratio"])
            except _NoTravel:
                flow = {"q_ratio": 1.0, "gauge": None, "gauge_name": None, "flow_cfs": None, "flow_time": None,
                        "gauge_km": None, "flow_basis": None}
                band = [{"hours_typical_start": None, "hours_typical": None, "hours_fast_start": None,
                         "hours_fast": None, "hours_leading_edge": None, "velocity_peak_ms": None,
                         "velocity_max_ms": None} for _ in r["segments"]]
            except Exception as e:
                problems.append(f"reach {key}: travel time unavailable ({type(e).__name__}: {e})"[:300])
                flow = {"q_ratio": 1.0, "gauge": None, "gauge_name": None, "flow_cfs": None, "flow_time": None,
                        "gauge_km": None, "flow_basis": "travel time unavailable"}
                band = [{"hours_typical_start": None, "hours_typical": None, "hours_fast_start": None,
                         "hours_fast": None, "hours_leading_edge": None, "velocity_peak_ms": None,
                         "velocity_max_ms": None} for _ in r["segments"]]

            def reached(h, elapsed):
                return None if h is None else h <= elapsed
            for eid, evs in by_event.items():
                top = max(evs, key=lambda iv: RANK[iv["color"]])
                t0 = parse_time(by_id[eid].get("started_at")) or top["start"]
                elapsed = (now - t0).total_seconds() / 3600
                segs = [{"i": i, "km_start": sg["km_start"], "km_end": sg["km_end"], **b,
                         "reached_fast": reached(b["hours_fast_start"], elapsed),
                         "reached_typical": reached(b["hours_typical_start"], elapsed)}
                        for i, (sg, b) in enumerate(zip(r["segments"], band))]
                active_reach_events.append({
                    "event_id": eid, "reach": key, "status": top["color"], "rule": top["rule"], "label": top["label"],
                    "short": short_reason(top, by_id.get(eid)), "rule_applied": top.get("rule_applied"),
                    "started_at": by_id[eid].get("started_at"), "hours_since_start": round(elapsed, 1),
                    **{k: v for k, v in flow.items() if k != "q_ratio"}, "q_ratio": round(flow["q_ratio"], 3),
                    "segments": segs,
                    **({"kind": ADVISORY_STRETCH, "category": out_reaches[key]["category"]}
                       if r.get("kind") == ADVISORY_STRETCH else {})})

    point_strips = {}
    for pt in points:
        point_strips[pt["event_id"]] = paint(pt.pop("_ivs"), h0, h_end, n_hours)
    for sid, n in sorted(invalid_times.items()):
        problems.append(f"{sid}: {n} record(s) with ended_at before started_at; the end is ignored "
                        "(placements[].validation_error, parse_error in the export)")
    for sid, n in sorted(future_starts.items()):
        problems.append(f"{sid}: {n} record(s) with a start more than {FUTURE_START_H} h in the future as published; "
                        "kept with their page, no status (placements[].future_start)")

    for sid, c in sorted(aside_events.items()):
        problems.append(f"{sid}: name-matched slug set aside by the placement guard on {sum(c.values())} event(s) "
                        f"({', '.join(f'{v} {k}' for k, v in sorted(c.items()))}; see placements[].set_aside)")
    for s, n in sorted(unknown_slugs.items()):
        problems.append(f"water slug {s} on {n} event(s) is not in the water records")
    outlines = outline_coverage(waters)
    problems.extend(outline_problems(outlines))
    # reports that name no receiving water (no_receiving_water: decision 3 and its like) colour nothing and
    # are counted apart from the unplaced ones (a water named but not placed)
    no_water = sorted(i for i, p in placements.items() if not p["water_slugs"] and p.get("no_receiving_water"))
    unplaced = sorted(i for i, p in placements.items() if not p["water_slugs"] and not p.get("no_receiving_water"))
    by_source = defaultdict(lambda: {"placed": 0, "no_receiving_water": 0, "unplaced": 0, "no_release": 0})
    for ev in events:
        p = placements[ev["event_id"]]
        by_source[ev["source_id"]]["placed" if p["water_slugs"] else
                                   "no_receiving_water" if p.get("no_receiving_water") else "unplaced"] += 1
        if p.get("no_release"):
            by_source[ev["source_id"]]["no_release"] += 1      # a part of no_receiving_water
    for sid, h in health.items():
        if sid in by_source:
            h["placement"] = dict(by_source[sid])
    status = {
        "built": now_iso(), "now": iso(now), "fixtures_included": include_fixtures,
        "restricted_included": include_restricted, "withheld_sources": withheld,
        "rules": {k: {"status": v[0], "label": v[1],
                      # the caution's label by which amount applied (build/rain_likely.py label_by_basis)
                      **({"label_by_basis": rain_mod.labels(rules)} if k == "rain_likely" else {})}
                  for k, v in RULES.items()},
        "advisory_windows": {"file": "data/rules.json", "version": rules.get("version")},
        "constants": {"advisory_no_end_days": ADVISORY_NO_END_DAYS, "confirm_days": CONFIRM_DAYS,
                      "history_days": HISTORY_DAYS, "unresolved": rules.get("unresolved"),
                      "reach": rules.get("reach")},
        "legend": LEGEND,
        "counts": {"waters": {st: dict(c) for st, c in sorted(counts.items())},
                   "events": len(events), "placed": len(events) - len(unplaced) - len(no_water),
                   "no_receiving_water": len(no_water), "unplaced": len(unplaced),
                   "no_release": sum(1 for i in no_water if placements[i].get("no_release")),
                   # waters by category and status now (docs/plan.md §2.z); events by category
                   "waters_by_category": {c: dict(cat_counts[c]) for c in CATEGORIES},
                   "events_by_category": dict(Counter(category_of(ev.get("event_type")) for ev in events
                                                      if ev["event_id"] not in duplicates)),
                   "future_start": sum(future_starts.values()),
                   "monthly_outfalls": len(monthly_outfalls),
                   "duplicates": len(duplicates)},
        "waters": out_waters,
        "placements": placements,
        "sources": health,
        "unplaced_events": unplaced,
        "no_receiving_water_events": no_water,
        "duplicates": duplicates,
        "advisory_points": points,
        "monthly_outfalls": monthly_outfalls,     # the current map's monthly marks by outfall (docs/plan.md §2.x)
        "reaches": out_reaches,
        "reach_events_active": active_reach_events,
        "rain_likely": rain_block,
        "needs_reach": needs_reach,
        "dropped_fixtures": dropped,
        "outlines": outlines,
        "problems": problems,
    }
    history = {"built": status["built"], "start": hours[0], "step_hours": 1, "count": n_hours,
               "legend": LEGEND,
               "fixtures_included": include_fixtures, "hours": hours, "waters": strips, "intervals": hist_ivs,
               "reaches": reach_strips, "reach_intervals": reach_hist, "points": point_strips}
    if write:
        write_json(BUILD_DIR / "status.json", status)
        write_json(BUILD_DIR / "history.json", history)
    if placement_cache:
        p = Path(placement_cache)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps({"stamp": cache_stamp, "built": iso(now), "placements": cache_new},
                                  separators=(",", ":"), default=str))
        tmp.replace(p)
        print(f"status: placement reused for {cache_hits} of {len(cache_new)} records that began over "
              f"{PLACEMENT_CACHE_DAYS} days ago")
    return status, history


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", action="store_true",
                    help="include the research fixture events (data/build/events/fixture-*.json); off by default")
    ap.add_argument("--no-fixtures", action="store_true", help="the default; kept for old command lines")
    ap.add_argument("--now", help="evaluate at this time (ISO 8601), for replays and tests")
    ap.add_argument("--include-nhdes", action="store_true",
                    help="include events files marked distribution_discouraged (NHDES Healthy Swimming)")
    ap.add_argument("--live-only", action="store_true",
                    help="leave out the records of states not in rules.json live_states (the refresh; the export "
                         "carries none of them, so no live water may take its colour or history from one)")
    a = ap.parse_args()
    status, _ = build(include_fixtures=a.fixtures and not a.no_fixtures, now=parse_time(a.now) if a.now else None,
                      include_restricted=a.include_nhdes, live_only=a.live_only)
    by = defaultdict(int)
    for w in status["waters"].values():
        by[w["status"]] += 1
    print(f"status: {len(status['waters'])} tracked waters {dict(by)}; {status['counts']['events']} events "
          f"({status['counts']['unplaced']} unplaced, {status['counts']['no_receiving_water']} name no receiving "
          f"water); fixtures {'in' if status['fixtures_included'] else 'out'}")
    cov = status.get("outlines") or {}
    print("status: water records with an outline here, by state: "
          + ", ".join(f"{st} {c['with_outline']}/{c['records']}" for st, c in cov.items()))
    for p in status["problems"][:20]:
        print("  problem:", p)


if __name__ == "__main__":
    main()
