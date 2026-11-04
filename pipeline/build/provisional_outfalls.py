"""Provisional outfalls from the overflow reports themselves -> data/build/outfalls-reported.json.

    python -m build.provisional_outfalls [--offline] [--budget-s 45] [--max-requests 150] [--workers 1]
                                         [--no-water] [--geolocate] [--geo-budget-s 60] [--llm] [--llm-cap-usd 2]

docs/national-outfalls.md, "Locations from the reports themselves" and "Provisional outfall pipeline" (owner,
2026-11-03 16:10 and 16:12): a place where an operator's own reports put an overflow is a provisional outfall
record until official data (the registry, a state outfall layer) covers it.

1. Places. Every sewage report (cso, sso, bypass, blended, plant_bypass) of data/build/events/*.json with a point,
   fixtures and restricted files left out, and reports another source duplicates (duplicate_of) left out, is
   grouped per operator (the registry row of its discharger_id, else its permit): points within 50 m of the most
   reported point of a place are that place (leader clustering, most reported first). A place keeps its report
   count, the distinct overflows behind them (a notice and its verified report are one), first and last report
   time, event types, sources, coord_source (source / geocode / outfall_layer), the outfall ids and the names the
   reports give (never a street address), whether the reports say the sewage reached a water (yes / no / unknown)
   and up to five event ids, the latest first.
   Dropped, with the reason counted in the output's `drops`: no operator named; a private-property or building
   backup report (privacy_reason: CT BYPASS_PRIV_PUB Yes, a basement or private lateral location, Baltimore
   Private responsibility, MDE "Unauthorized Discharge" source type, VA house lateral or backup in a building, and
   the same in the report's location texts); a point at (0, 0), swapped, with the longitude's sign missing, or
   outside the report's state (Census cartographic outline, 1 km slack); a point shared by three or more
   operators (a town or county centroid).
2. Status. record_status: superseded when a registry row (common.load_outfall_registry: cso or plant, every
   data/outfalls-*.json) of the same operator's permits lies within 100 m (superseded_by names it; the row stays,
   off the map, its reports still linked); confirmed when a state outfall layer (MassDEP, Maine DEP, NJDEP) has an
   outfall of the operator's permit within 100 m that the registry lacks (an official point, not yet in the
   registry); else provisional. confidence: high when the source's coordinates repeat across two or more overflows;
   medium for one overflow or a geocoded address; low for a facility point standing in. first_seen is kept across
   runs (the previous output's row of the same operator within 50 m). outfall_kind: "cso" when CSO reports name an
   outfall id the registry lacks for the permit at the same place in two or more overflows, or the point is an
   official outfall layer's (coords_from "report"; joins the rain caution and reach tracing); every other place
   "reported" (decision of 2026-11-03: it does not drive the caution).
3. The water. Each place that is not superseded, most reports first, is put on the NHDPlus V2.1 network with USGS
   NLDI: first the flowline of the NHDPlus catchment holding the point (comid/position, 0.5 s; catchments are cut
   from the same flow-direction grid the raindrop trace follows, so it is the trace's flowline: 7 of 7 agreed when
   measured on 2026-11-03), then, with what is left of the run's budget, the raindrop trace itself
   (https://api.water.usgs.gov/nldi/linked-data/hydrolocation: the entry point and measure; about 6 s a call and
   HTTP 502 on half the calls in November 2026), which replaces the catchment answer when it succeeds. The
   flowline's GNIS name comes from EPA's NHDPlus V2.1 MapServer (layer 2 flowlines, layer 4 waterbodies for an
   artificial path through a lake or estuary; 100 COMIDs a request). An unnamed flowline is walked downstream (NLDI
   navigation DM, 50 km) to the first named water: "unnamed tributary to <X>". The named water is matched to a water
   record (status.load_waters: a COMID or GNIS id of an NHD record, else the name in the state within the
   placement's distance) and checked against the waters the reports name (agree / disagree / unclear / the reports
   name none). A named water with no record is listed (state, name, GNIS id, COMID, operators, reports) in the
   output's waters_without_record for the NHD water-record builder (ingest/waters_from_nhd.py). The row's
   water_slugs are the reports' own when they name one (a disagreement is flagged, never overwritten), else the
   traced water's record when the reports name no water and the point lies within 1 km of the flowline.
   api.water.usgs.gov allows 3,600 requests an hour per address (x-ratelimit-limit), shared with every other builder
   on this machine (reaches, waters_from_nhd): a run asks at most --max-requests (150 by default) and a 429 or 5xx is
   never cached as an answer.
4. Geolocation of reports without a point (--geolocate; build/report_geolocate.py).
Every response is cached in data/build/provisional-outfalls-cache.json (by point, COMID, query), so a re-run asks
nothing twice; requests are polite (one at a time per worker, 0.5 s apart, backoff on 429/5xx, the project's
User-Agent) and limited per run (--budget-s seconds and --max-requests requests; the hourly refresh uses the
defaults so it is not slowed; the first full run is made by hand in batches with a larger budget). Places the
budget did not reach say water.status "pending" and are taken next run.

Public wording: "Provisional location from overflow reports", never a permitted outfall. No street address is
written to a row; common.strip_personal runs over every row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from build import status as S
from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, load_outfall_registry, now_iso, read_json, strip_personal, \
    write_json

SOURCE_ID = "outfalls-reported"
OUT = BUILD_DIR / "outfalls-reported.json"
CACHE_PATH = BUILD_DIR / "provisional-outfalls-cache.json"
PUBLIC_LABEL = "Provisional location from overflow reports"
PLANT_LABEL = "treatment plant location, not an overflow point"

CLUSTER_M = 50                 # reports within this of a place's most reported point are that place
SUPERSEDE_M = 100              # an official outfall of the same operator this close supersedes / confirms
CENTROID_OPERATORS = 3         # a point shared by this many operators is a town or county centroid
CENTROID_ROUND = 4             # ... compared at 4 decimals (about 10 m)
STATE_SLACK_DEG = 0.01         # about 1 km outside the state outline still counts (shore, river line)
MAX_EVENT_IDS = 5
SEWAGE_TYPES = ("cso", "sso", "bypass", "blended", "plant_bypass")
ERROR_RETRY_DAYS = 7           # a cached failure is asked again after this long

NLDI = "https://api.water.usgs.gov/nldi/linked-data"
EPA_NHD = "https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer"
FL_FIELDS = "comid,gnis_id,gnis_name,reachcode,ftype,fcode,wbareacomid,streamorder,lengthkm,hydroseq,dnhydroseq"
WB_FIELDS = "comid,gnis_id,gnis_name,reachcode,ftype,fcode,areasqkm"
DM_KM = 50                     # downstream walk for an unnamed flowline's first named water
PAUSE_S = 0.5
DEFAULT_BUDGET_S = 45
DEFAULT_MAX_REQUESTS = 150
ALLOWANCE_RESERVE = 900        # stop asking a host once its x-ratelimit-remaining falls below this (shared hour)

STATE_LAYERS = ("ma-cso-outfalls.json", "me-cso-outfalls.json", "nj-cso-outfalls.json")


# ---------------------------------------------------------------- geometry helpers

def dist_m(lat1, lon1, lat2, lon2) -> float:
    """Metres between two points (equirectangular; exact enough under a few km)."""
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_320, (lon2 - lon1) * 111_320 * k)


_OUTLINES: dict | None = None


def state_outlines() -> dict:
    """{state code: shapely geometry} from the Census cartographic outlines openboatlaunch keeps (read by
    ingest/waters_from_nhd.py); {} when the file is not there (the outside-the-state check is then skipped)."""
    global _OUTLINES
    if _OUTLINES is None:
        try:
            from ingest import waters_from_nhd as WFN
            _OUTLINES = WFN.read_state_outlines(None)
        except Exception:
            _OUTLINES = {}
    return _OUTLINES


# ---------------------------------------------------------------- privacy (docs/national-outfalls.md)

PRIVATE_LOCATION = re.compile(r"^\s*(basement|lateral\s*-\s*private|private\s+(property|lateral|residence|home)|"
                              r"house\s+lateral|building|residence|home|dwelling)\s*$", re.I)
PRIVATE_TEXT = re.compile(
    r"\bbasements?\b|\bcrawl\s?space\b|\bprivate\s+(?:property|properties|lateral|service|residence|home|house|"
    r"sewer|system|line|side|pump|lands?|yard|driveway|road|drive|street|way|parking|lot|easement|residential)|"
    r"\bhouse\s+lateral|\bbuilding\s+(?:back[\s-]?up|sewer)|"
    r"\blateral\s*[-\u2013]\s*private\b|"
    r"\bback(?:ed)?[\s-]?ups?\s+(?:in|into|inside)\s+(?:a\s+|the\s+|\w+\s+)?(?:home|house|building|residence|dwelling|"
    r"apartment|unit|garage)|(?:home|house|building|residence|dwelling)s?\s+back[\s-]?ups?\b|"
    r"sewage\s+backup\s+in\s+(?:a\s+)?building|\binto\s+(?:a\s+|the\s+)?(?:home|house|residence|dwelling)\b", re.I)


def location_texts(ev: dict) -> dict[str, str]:
    """The location and description texts a report carries, by field ({label: text}); used for the privacy check
    and the geolocation of reports without a point. Never written to an output row."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    rep = raw.get("report") if isinstance(raw.get("report"), dict) else {}
    txt = raw.get("text") if isinstance(raw.get("text"), dict) else {}
    out = {}

    def put(label, v):
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "n/a", "-", "select..."):
            out[label] = v.strip()

    put("outfall_name", ev.get("outfall_name"))
    put("volume_text", ev.get("volume_text"))
    for k in ("BYPASS_LOCATION", "Location of Bypass", "STREET_ADDRESS", "Address", "LOCATION", "location",
              "Cause of Bypass", "BYPASS_CAUSE", "Estimated Quantity or Rate of Discharge", "How was Incident Discovered",
              "Cause of Bypass Other Explanation", "COMMENTS", "address", "Location", "Site", "site", "description",
              "Description", "Facility", "facility", "town", "Town", "municipality", "Municipality", "CSO_TOWN",
              "REPORTING_TOWN", "Muncipality", "city", "City/Town"):
        put(k, raw.get(k))
    for k in ("streetNumber", "streetName", "city", "addressDescription", "componentDescription", "systemComponent",
              "dischargeDescription", "geoaddress", "overflow_address", "zip", "county", "overflow_cause",
              "overflow_type", "facility_collection_system"):
        put(k, row.get(k))
    for k in ("site_name", "address", "city", "zip", "county_city", "facility_name"):
        put(f"report.{k}", rep.get(k))
    for k in ("location_comment", "incident_comment"):
        put(f"text.{k}", txt.get(k))
    for i, s in enumerate(raw.get("sewage") or []):
        if isinstance(s, dict):
            put(f"sewage{i}.component", s.get("component"))
            put(f"sewage{i}.component_comment", s.get("component_comment"))
            for j, imp in enumerate(s.get("impacts") or []):
                put(f"sewage{i}.impact{j}", imp)
    put("structure_type", raw.get("sewer_overflow_structure_type_desc"))
    return out


def privacy_reason(ev: dict) -> str | None:
    """Why a report is left out of the public places (a private property or a building backup), or None. Rules
    only; a language model may add exclusions (report_geolocate), never remove one."""
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    if str(raw.get("BYPASS_PRIV_PUB") or "").strip().lower() == "yes":
        return "private property (CT BYPASS_PRIV_PUB: Yes)"
    for k in ("BYPASS_LOCATION", "Location of Bypass"):
        v = raw.get(k)
        if isinstance(v, str) and PRIVATE_LOCATION.match(v):
            return f"private property or building ({k}: {v})"
    if str(raw.get("_responsibility") or raw.get("RESPONSIBILITY") or "").strip().lower() == "private":
        return "private responsibility (Baltimore RESPONSIBILITY: Private)"
    st = raw.get("_source_type") or row.get("overflow_type")
    if isinstance(st, str) and st.strip().lower() == "unauthorized discharge":
        return "source type: Unauthorized Discharge (not the operator's system)"
    for i, s in enumerate(raw.get("sewage") or []):
        if not isinstance(s, dict):
            continue
        if str(s.get("component") or "").strip().lower() in ("house lateral", "private lateral", "building"):
            return f"private property (component: {s.get('component')})"
        for imp in s.get("impacts") or []:
            if isinstance(imp, str) and "backup in building" in imp.lower():
                return f"building backup (impact: {imp})"
    for label, t in location_texts(ev).items():
        m = PRIVATE_TEXT.search(t)        # every field, the incident and discovery texts included (review P1-1)
        if m:
            return f"private property or building backup ({label}: '{m.group(0)}')"
    return None


# no street address in an output row: a house number followed by words, or a text with a street word and a number
ADDRESS_LIKE = re.compile(r"\b\d{1,6}[A-Za-z]?\s+(?:[NSEW]\.?\s+)?[A-Za-z][\w.'-]*(?:\s+[A-Za-z][\w.'-]*){0,4}\s*"
                          r"(?:st|street|rd|road|ave|avenue|dr|drive|ln|lane|blvd|boulevard|ct|court|pl|place|way|"
                          r"ter|terrace|cir|circle|pkwy|parkway|hwy|highway|tpke|turnpike|route|rte|sq|square|trl|"
                          r"trail|pike|row|xing|crossing)\b\.?", re.I)
HOUSE_NUMBER_START = re.compile(r"^\s*\d{1,6}[A-Za-z]?\s+[A-Za-z]")
OUTFALL_ID_TEXT = re.compile(r"^\s*(?:CSO|SSO|OUTFALL|OF|DSN|SITE)?\s*(?:SITE)?\s*#?\s*[A-Z]{0,4}-?\d{1,4}[A-Z]?\s*$", re.I)


def safe_place_name(name) -> str | None:
    """A name the reports give a place, fit for a public row: no street address (a house number and a street), no
    personal detail (common.scrub_text through strip_personal), at most 80 characters; None otherwise."""
    if not isinstance(name, str) or not name.strip():
        return None
    n = re.sub(r"\s+", " ", name).strip()
    if ADDRESS_LIKE.search(n) or (HOUSE_NUMBER_START.match(n) and not OUTFALL_ID_TEXT.match(n)):
        return None
    if re.search(r"\b\d{5}(?:-\d{4})?\b", n):          # a ZIP code: part of an address
        return None
    if re.search(r"\b(?:house|home|residence|lot|unit|apt|apartment)\s*(?:#|no\.?|number)?\s*\d+", n, re.I) \
            or re.search(r"\bprivate\b|\bresident", n, re.I):
        return None                                    # a house number in words, or a private place
    for m in NUMBER_WORD.finditer(n):
        if not OUTFALL_BEFORE.search(n[max(0, m.start() - 12):m.start()]):
            return None                                # "Manhole at 399 Tremont": a house number and a street
    if not PLACE_WORD.search(n) and not OUTFALL_ID_TEXT.match(n):
        return None                                    # a bare name ("John Doe") is not shown: it may be a person
    if person_like(n):
        return None
    n = strip_personal(n)
    if "[" in n:                                       # something was scrubbed: not a place name
        return None
    return n[:80]


NUMBER_WORD = re.compile(r"(?<![#\w./-])\d{1,6}[A-Za-z]?\s+(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z'.]{2,}")
OUTFALL_BEFORE = re.compile(r"(?:cso|sso|outfall|of|dsn|site|regulator|reg|no\.?|#|structure|station|ps|unit|"
                            r"basin|tank|pump)\s*[-#:]?\s*$", re.I)
PLACE_WORD = re.compile(
    r"\b(?:pump|pumping|lift|station|ps|manhole|mh|main|sewer|siphon|regulator|outfall|cso|sso|overflow|plant|wwtp|"
    r"wwtf|wpcf|wpca|wrf|headworks|tank|basin|chamber|interceptor|culvert|pipe|force|lateral|clarifier|filter|"
    r"influent|effluent|bypass|bridge|park|field|school|cemetery|cemetary|church|library|plaza|wharf|pier|dam|"
    r"falls|brook|river|creek|stream|run|pond|lake|harbor|harbour|bay|cove|canal|kill|street|st|road|rd|avenue|"
    r"ave|drive|dr|lane|ln|boulevard|blvd|court|ct|place|pl|way|terrace|ter|circle|parkway|pkwy|highway|hwy|"
    r"route|rte|rt|turnpike|tpke|square|trail|pike|alley|extension|ext|north|south|east|west|corner|intersection|"
    r"junction|end|behind|near|across|between|off|tributary|ditch|wetland|swamp|marsh|ocean|sound|inlet)\b", re.I)


def person_like(text) -> bool:
    """A value that may be a person's name (build/redact.person_shaped, else a bare two- or three-word capitalised
    name with no water or place word)."""
    try:
        from build.redact import person_shaped
        if person_shaped(text):
            return True
    except Exception:
        pass
    t = str(text or "").strip()
    return bool(re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z'-]+", t)) and not PLACE_WORD.search(t)


# ---------------------------------------------------------------- reading the reports

def report_time(ev: dict) -> datetime | None:
    for k in ("started_at", "reported_at", "published_at", "source_updated_at"):
        t = S.parse_time(ev.get(k))
        if t:
            return t
    return None


def reached(ev: dict) -> str:
    """Whether the report says the sewage reached a water: yes / no / unknown."""
    if S.reached_no_water(ev):
        return "no"
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    rep = raw.get("report") if isinstance(raw.get("report"), dict) else {}
    for k in S.REACH_FLAG_KEYS:
        if str(raw.get(k) or "").strip().lower() == "yes":
            return "yes"
    if str(row.get("surfaceWater") or "").strip().lower() == "yes" or rep.get("water_threatened") == "Y":
        return "yes"
    # "text": the notice's text says the sewage reached the water its form said was not reached (Florida PNP)
    if raw.get("reached_water") in (True, "text") or raw.get("ENTER_STORM") == 1 and ev.get("waterbody_text"):
        return "yes"
    for s in raw.get("sewage") or []:
        if isinstance(s, dict) and any(isinstance(i, str) and "discharge to state waters" in i.lower()
                                       for i in s.get("impacts") or []):
            return "yes"
    if ev.get("water_slugs"):
        return "yes"
    if ev.get("event_type") == "cso":
        return "yes"                       # a combined sewer overflow discharges at an outfall to a water
    return "unknown"


def coord_problem(lat, lon, state: str | None, outlines: dict) -> str | None:
    """Why a report's point cannot stand for a place, or None."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return "no coordinates"
    if lat != lat or lon != lon:
        return "no coordinates"
    if abs(lat) < 0.5 and abs(lon) < 0.5:
        return "at (0, 0)"
    if 17 <= lon <= 72 and -180 <= lat <= -60:
        return "latitude and longitude swapped"
    if 17 <= lat <= 72 and 60 <= lon <= 180:
        return "longitude without its minus sign"
    if not (17 <= lat <= 72 and -180 <= lon <= -60):
        return "not a point in the United States"
    if not state:
        return "no state to check the point against"
    g = outlines.get(state)
    if g is None:
        return f"no {state} outline to check the point against"     # fail closed (review P2-16)
    from shapely.geometry import Point
    p = Point(lon, lat)
    if not g.contains(p) and g.distance(p) > STATE_SLACK_DEG:
        return f"outside {state}"
    return None


def load_report_events(events_dir: Path = EVENTS_DIR) -> list[dict]:
    """The sewage reports of every events file (fixtures and restricted files left out; status.load_events)."""
    _, events, _ = S.load_events(events_dir)
    return [e for e in events if e.get("event_type") in SEWAGE_TYPES]


def operator_index(rows: list[dict] | None = None) -> tuple[dict, dict]:
    """({key: registry row id}, {row id: row}) for data/dischargers.json: a row is found by its id, its permits and
    the aliases that map to it."""
    rows = S.discharger_rows() if rows is None else rows
    aliases = S.discharger_aliases(rows)
    by_id = {r["id"]: r for r in rows if r.get("id")}
    key = {}
    for r in rows:
        if not r.get("id"):
            continue
        for k in [r["id"], r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
            if k:
                key.setdefault(k, r["id"])
    for a, rid in aliases.items():
        key.setdefault(a, rid)
    return key, by_id


def operator_of(ev: dict, key: dict) -> str | None:
    """The operator a report counts under: the registry row of its discharger id (or an alias of it), else of its
    permit; else its own discharger id or permit (an operator the registry does not list yet); None when the
    report names no operator."""
    did, permit = ev.get("discharger_id"), ev.get("npdes_permit")
    for k in (did, permit):
        if k and k in key:
            return key[k]
    return did or permit or None


def permit_state(permit) -> str | None:
    """The state a permit number names ("RISS00018" -> RI), when the site covers it."""
    st = str(permit or "")[:2].upper()
    try:
        return st if st in S.states() else None
    except Exception:
        return None


def operator_permits(op: str, events: list[dict], by_id: dict) -> list[str]:
    r = by_id.get(op) or {}
    out = [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]
    out += [e.get("npdes_permit") for e in events]
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{7}", op or ""):
        out.append(op)
    return list(dict.fromkeys(p.strip().upper() for p in out if isinstance(p, str) and p.strip()))


# ---------------------------------------------------------------- places

def cluster_points(items: list[tuple[float, float, object]], m: float = CLUSTER_M) -> list[list]:
    """Leader clustering: the exact points (5 decimals) most reported first; each point joins the nearest leader
    within m metres, else leads a new place. Returns [[(lat, lon, item), ...], ...], the leader's items first."""
    exact = defaultdict(list)
    for lat, lon, it in items:
        exact[(round(lat, 5), round(lon, 5))].append(it)
    order = sorted(exact, key=lambda p: (-len(exact[p]), p))
    leaders: list[tuple[float, float]] = []
    groups: list[list] = []
    for p in order:
        best, bd = None, None
        for i, q in enumerate(leaders):
            if abs(q[0] - p[0]) > 0.001 or abs(q[1] - p[1]) > 0.0015:
                continue
            d = dist_m(p[0], p[1], q[0], q[1])
            if d <= m and (bd is None or d < bd):
                best, bd = i, d
        if best is None:
            leaders.append(p)
            groups.append([(p[0], p[1], it) for it in exact[p]])
        else:
            groups[best].extend((p[0], p[1], it) for it in exact[p])
    return groups


def join_places(places: list[dict], extra: list[dict]) -> int:
    """Add the geolocated places to places; one within 50 m of a place of the same operator from the reports' own
    points joins that place (its reports counted there) instead of standing beside it. Returns how many joined."""
    by_op = defaultdict(list)
    for p in places:
        by_op[p["discharger_id"]].append(p)
    joined = 0
    for g in extra:
        near = [(dist_m(g["lat"], g["lon"], p["lat"], p["lon"]), p) for p in by_op.get(g["discharger_id"], [])
                if not p.get("geolocation")]
        near = [x for x in near if x[0] <= CLUSTER_M]
        if not near:
            places.append(g)
            by_op[g["discharger_id"]].append(g)
            continue
        p = min(near, key=lambda x: x[0])[1]
        joined += 1
        for k in ("report_count", "overflow_count"):
            p[k] += g[k]
        for k in ("event_types", "sources", "coord_sources", "reached_counts", "cso_outfall_overflows"):
            p[k] = dict(Counter(p.get(k) or {}) + Counter(g.get(k) or {}))
        for k in ("outfall_ids", "place_names", "reports_water_text", "reports_water_slugs"):
            p[k] = list(dict.fromkeys((p.get(k) or []) + (g.get(k) or [])))
        p["_all_event_ids"] = list(dict.fromkeys((p.get("_all_event_ids") or []) + (g.get("_all_event_ids") or [])))
        times = [t for t in (p.get("first_report_at"), g.get("first_report_at"), p.get("last_report_at"),
                             g.get("last_report_at")) if t]
        if times:
            p["first_report_at"], p["last_report_at"] = min(times), max(times)
        rc = p["reached_counts"]
        p["reached_water"] = "yes" if rc.get("yes") else ("no" if rc.get("no") == p["report_count"] else "unknown")
    return joined


def place_id(op: str, lat: float, lon: float) -> str:
    return "rep-" + hashlib.sha1(f"{op}|{lat:.4f}|{lon:.4f}".encode()).hexdigest()[:10]


def outfall_ids(ev: dict) -> list[str]:
    try:
        ids, _ = S.outfall_ids_of(ev)
    except Exception:
        ids = []
    if not ids and ev.get("outfall_id"):
        ids = [str(ev["outfall_id"])]
    return [str(i).strip() for i in ids if str(i).strip()]


def build_places(events: list[dict], outlines: dict | None = None, key: dict | None = None,
                 by_id: dict | None = None) -> tuple[list[dict], Counter, list[dict]]:
    """(places, drops, unlocated): one place per operator and 50 m, from the reports with a usable point; drops
    counts the reports left out by reason; unlocated are the reports kept (operator, privacy) that have no usable
    point (the geolocation step's input)."""
    outlines = state_outlines() if outlines is None else outlines
    if key is None or by_id is None:
        key, by_id = operator_index()
    drops = Counter()
    kept, unlocated = [], []
    for ev in events:
        if ev.get("duplicate_of"):
            drops["a copy of another source's report (duplicate_of)"] += 1
            continue
        op = operator_of(ev, key)
        if not op:
            drops["no operator named"] += 1
            continue
        why = privacy_reason(ev)
        if why:
            drops["private property or building backup"] += 1
            continue
        state = S.event_state(ev) or (by_id.get(op) or {}).get("state") or permit_state(ev.get("npdes_permit") or op)
        if ev.get("lat") is None or ev.get("lon") is None:
            unlocated.append({**ev, "_op": op, "_state": state})
            continue
        prob = coord_problem(ev.get("lat"), ev.get("lon"), state, outlines)
        if prob:
            drops[f"point {prob}" if not prob.startswith("outside") else "point outside the report's state"] += 1
            unlocated.append({**ev, "_op": op, "_state": state, "_coord_problem": prob})
            continue
        kept.append((float(ev["lat"]), float(ev["lon"]), {**ev, "_op": op, "_state": state}))
    # a point three or more operators share is a town or county centroid
    ops_at = defaultdict(set)
    for lat, lon, ev in kept:
        ops_at[(round(lat, CENTROID_ROUND), round(lon, CENTROID_ROUND))].add(ev["_op"])
    shared = {p for p, ops in ops_at.items() if len(ops) >= CENTROID_OPERATORS}
    by_op = defaultdict(list)
    for lat, lon, ev in kept:
        if (round(lat, CENTROID_ROUND), round(lon, CENTROID_ROUND)) in shared:
            drops[f"point shared by {CENTROID_OPERATORS} or more operators (a town or county centroid)"] += 1
            continue
        by_op[ev["_op"]].append((lat, lon, ev))
    places = []
    for op in sorted(by_op):
        evs = [e for _, _, e in by_op[op]]
        permits = operator_permits(op, evs, by_id)
        row = by_id.get(op) or {}
        for group in cluster_points(by_op[op]):
            places.append(place_row(op, row, permits, group))
    return places, drops, unlocated


def place_row(op: str, oprow: dict, permits: list[str], group: list) -> dict:
    lat, lon = group[0][0], group[0][1]
    evs = [it for _, _, it in group]
    times = [(report_time(e), e) for e in evs]
    dated = sorted((t, e["event_id"]) for t, e in times if t)
    latest_first = [eid for _, eid in sorted(dated, reverse=True)] + [e["event_id"] for t, e in times if not t]
    overflows = {e.get("parent_event_id") or e["event_id"] for e in evs}
    reach = Counter(reached(e) for e in evs)
    reach_sum = "yes" if reach["yes"] else ("no" if reach["no"] == len(evs) else "unknown")
    names = Counter(n for n in (safe_place_name(e.get("outfall_name")) for e in evs) if n)
    oids = Counter(i for e in evs for i in outfall_ids(e))
    cso_named = defaultdict(set)              # outfall id -> the distinct CSO overflows naming it here
    for e in evs:
        if e.get("event_type") == "cso":
            for i in outfall_ids(e):
                cso_named[i].add(e.get("parent_event_id") or e["event_id"])
    texts = Counter(strip_personal(str(e["waterbody_text"]).strip())[:120] for e in evs
                    if isinstance(e.get("waterbody_text"), str) and e["waterbody_text"].strip()
                    and not S.reached_no_water(e) and not ADDRESS_LIKE.search(e["waterbody_text"])
                    and not re.search(r"\bprivate\b|\bresident'?s?\b|\bhomeowner|\bbackyard|\byard\b",
                                      e["waterbody_text"], re.I)
                    and not re.search(r"\b\d{5}\b", e["waterbody_text"]) and not person_like(e["waterbody_text"]))
    slugs = Counter(s for e in evs for s in (e.get("water_slugs") or []))
    states = Counter(e.get("_state") for e in evs if e.get("_state"))
    names_seen = Counter(e.get("discharger_name") for e in evs if e.get("discharger_name"))
    cs = Counter(e.get("coord_source") or "source" for e in evs)
    return {
        "id": place_id(op, lat, lon),
        "source_id": SOURCE_ID,
        "discharger_id": op,
        "permittee": oprow.get("name") or (names_seen.most_common(1)[0][0] if names_seen else None),
        "npdes_permit": permits[0] if permits else None,
        "npdes_permits": permits,
        "state": (oprow.get("state") or (states.most_common(1)[0][0] if states else None)
                  or next((x[:2] for x in permits if x[:2] in S.states()), None)),
        "lat": round(lat, 6), "lon": round(lon, 6),
        "coord_source": cs.most_common(1)[0][0],
        "coord_sources": dict(cs),
        "coord_spread_m": round(max(dist_m(lat, lon, a, b) for a, b, _ in group)),
        "report_count": len(evs),
        "overflow_count": len(overflows),
        "first_report_at": S.iso(dated[0][0]) if dated else None,
        "last_report_at": S.iso(dated[-1][0]) if dated else None,
        "event_types": dict(Counter(e.get("event_type") for e in evs)),
        "sources": dict(Counter(e.get("source_id") for e in evs)),
        "outfall_ids": [i for i, _ in oids.most_common(10)],
        "cso_outfall_overflows": {i: len(v) for i, v in cso_named.items()},
        "place_names": [n for n, _ in names.most_common(5)],
        "reached_water": reach_sum,
        "reached_counts": dict(reach),
        "reports_water_text": [t for t, _ in texts.most_common(3)],
        "reports_water_slugs": [s for s, _ in slugs.most_common(5)],
        "event_ids": latest_first[:MAX_EVENT_IDS],
        "_all_event_ids": latest_first,
    }


# ---------------------------------------------------------------- official points: supersede, confirm, kind

def registry_rows(rows: list[dict] | None = None) -> list[dict]:
    """The official registry rows (cso or plant) with a point; never this builder's own rows, whatever loader
    reads them."""
    if rows is None:
        try:
            rows = load_outfall_registry(DATA_DIR, provisional=False)      # the official files only
        except TypeError:                                                  # a loader without the flag
            rows = load_outfall_registry(DATA_DIR)
    out = []
    for o in rows:
        if o.get("source_id") == SOURCE_ID or o.get("coords_from") == "report" or o.get("record_status"):
            continue
        if str(o.get("outfall_kind") or "cso") not in ("cso", "plant"):
            continue
        try:
            float(o["lat"]), float(o["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(o)
    return out


def state_layer_rows() -> list[dict]:
    """Outfalls of the state layers the ingesters keep (MassDEP, Maine DEP, NJDEP), as {npdes_permit, outfall, lat,
    lon, _file}."""
    out = []
    for name in STATE_LAYERS:
        try:
            d = read_json(BUILD_DIR / name) or {}
        except Exception:
            continue
        rows = d.get("outfalls") if isinstance(d, dict) else d
        if isinstance(rows, dict):
            rows = list(rows.values())
        for o in rows or []:
            if not isinstance(o, dict):
                continue
            permit = o.get("npdes_permit") or o.get("npdes") or o.get("permit")
            try:
                lat, lon = float(o["lat"]), float(o["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if permit:
                out.append({"npdes_permit": str(permit).upper(), "outfall": o.get("outfall"), "lat": lat, "lon": lon,
                            "_file": f"data/build/{name}"})
    return out


def nearest_of(rows_by_permit: dict, permits, lat, lon):
    best = None
    for p in permits or []:
        for o in rows_by_permit.get(p, []):
            d = dist_m(lat, lon, float(o["lat"]), float(o["lon"]))
            if best is None or d < best[0]:
                best = (d, o)
    return best


def classify(places: list[dict], registry: list[dict], layers: list[dict]) -> None:
    """record_status, superseded_by / confirmed_by, outfall_kind, confidence (in place)."""
    reg = defaultdict(list)
    for o in registry:
        reg[str(o["npdes_permit"]).upper()].append(o)
    lay = defaultdict(list)
    for o in layers:
        lay[o["npdes_permit"]].append(o)
    reg_numbers = defaultdict(set)
    for o in registry:
        reg_numbers[str(o["npdes_permit"]).upper()].add(S.oid_key(o.get("outfall")) if hasattr(S, "oid_key") else
                                                        str(o.get("outfall")))
    for p in places:
        permits = p.get("npdes_permits") or []
        p["superseded_by"] = p["confirmed_by"] = None
        near = nearest_of(reg, permits, p["lat"], p["lon"])
        lnear = nearest_of(lay, permits, p["lat"], p["lon"])
        if near and near[0] <= SUPERSEDE_M:
            o = near[1]
            p["record_status"] = "superseded"
            p["superseded_by"] = {"npdes_permit": o.get("npdes_permit"), "outfall": o.get("outfall"),
                                  "outfall_kind": o.get("outfall_kind") or "cso", "file": o.get("_file"),
                                  "distance_m": round(near[0])}
        elif lnear and lnear[0] <= SUPERSEDE_M:
            # spec: a state outfall layer's record supersedes as the registry's does (review P2-13); the loader
            # should read the state layers so the outfall itself stays on the map
            o = lnear[1]
            p["record_status"] = "superseded"
            p["superseded_by"] = {"npdes_permit": o["npdes_permit"], "outfall": o.get("outfall"),
                                  "outfall_kind": "cso", "file": o["_file"], "distance_m": round(lnear[0])}
        else:
            p["record_status"] = "provisional"
        if near:
            p["nearest_registry_m"] = round(near[0])
        # kind: a CSO outfall the registry lacks, named by the reports at this place in two or more overflows, or an
        # official outfall layer's point
        permit = (permits or [None])[0]
        have = set()
        for q in permits:
            have |= reg_numbers.get(q, set())
        named2 = p.get("cso_outfall_overflows")
        if named2 is None:                    # a row built without the per-outfall count: every overflow is a CSO one
            named2 = {i: p["overflow_count"] for i in p["outfall_ids"]} if p["event_types"].keys() <= {"cso"} else {}
        new_ids = [i for i in p["outfall_ids"]
                   if (S.oid_key(i) if hasattr(S, "oid_key") else i) not in have and named2.get(i, 0) >= 2]
        is_cso = p["event_types"].get("cso", 0) > 0
        layer_point = p["coord_source"] == "outfall_layer"
        p["outfall_kind"] = "reported"
        p["kind_basis"] = None
        if p["record_status"] != "superseded" and not p.get("stand_in") and not p.get("geolocation"):
            if new_ids and is_cso:
                p["outfall_kind"] = "cso"
                p["kind_basis"] = (f"CSO reports name outfall {', '.join(new_ids[:3])} at this place in "
                                   f"{max(named2[i] for i in new_ids)} overflows; the registry has no such outfall "
                                   f"for {permit}")
            elif layer_point:
                p["outfall_kind"] = "cso"
                p["kind_basis"] = "the point is an official CSO outfall layer's (not yet in the registry)"
        p["coords_from"] = "report"
        p["outfall"] = p["id"]                     # the registry key's outfall number: never a real one
        p["outfall_status"] = None
        # confidence (spec): high = source coordinates repeated across reports; medium = one report or a geocoded
        # address; low = a facility point standing in
        geocoded = p["coord_sources"].get("geocode", 0) >= max(1, p["report_count"] / 2)
        if p.get("geolocation"):
            p["confidence"] = "low" if p.get("stand_in") else p["geolocation"]["confidence"]
        elif p.get("stand_in"):
            p["confidence"] = "low"
        elif geocoded:
            p["confidence"] = "medium"
        elif p["overflow_count"] >= 2:
            p["confidence"] = "high"
        else:
            p["confidence"] = "medium"


# ---------------------------------------------------------------- HTTP (cached, polite, budgeted)

class Budget:
    def __init__(self, seconds: float, max_requests: int):
        self.deadline = time.monotonic() + max(0.0, seconds)
        self.max, self.used = max_requests, 0
        self.lock = threading.Lock()
        self.spent = False

    def take(self) -> bool:
        with self.lock:
            if self.used >= self.max or time.monotonic() >= self.deadline:
                self.spent = True
                return False
            self.used += 1
            return True

    def left_s(self) -> float:
        return self.deadline - time.monotonic()


class Net:
    """GETs with a per-host pause, backoff on 429 and 5xx, the project's User-Agent, and a request budget."""

    def __init__(self, budget: Budget, offline: bool = False, pause: float = PAUSE_S):
        self.budget, self.offline, self.pause = budget, offline, pause
        self.local = threading.local()
        self.lock = threading.Lock()
        self.last: dict[str, float] = {}
        self.counts = Counter()
        self.failures = Counter()
        self.seconds = Counter()
        self.blocked_until: dict[str, float] = {}
        self.rate_limited: dict[str, int] = {}

    def session(self):
        import requests
        s = getattr(self.local, "s", None)
        if s is None:
            s = self.local.s = requests.Session()
            s.headers.update(HEADERS)
        return s

    def _wait(self, host: str):
        while True:
            with self.lock:
                gap = self.pause - (time.monotonic() - self.last.get(host, 0.0))
                if gap <= 0:
                    self.last[host] = time.monotonic()
                    return
            time.sleep(gap)

    def get_json(self, kind: str, url: str, params: dict, timeout: float = 60, attempts: int = 3):
        """(json, None) or (None, why). 400/404 come back as {"_status": code}."""
        import requests
        if self.offline:
            return None, "offline"
        host = url.split("/")[2]
        why = "failed"
        for attempt in range(attempts):
            if self.blocked_until.get(host, 0) > time.monotonic():
                return None, "rate limited"
            if not self.budget.take():
                return None, "budget"
            self._wait(host)
            t0 = time.monotonic()
            try:
                r = self.session().get(url, params=params, timeout=min(timeout, max(5.0, self.budget.left_s())))
            except requests.RequestException as ex:
                why = type(ex).__name__
                self._count(kind, t0, failed=True)
                time.sleep(max(0.0, min(30, 2 * 2 ** attempt, self.budget.left_s())))
                continue
            self._count(kind, t0, failed=r.status_code >= 400 and r.status_code not in (400, 404))
            left = r.headers.get("x-ratelimit-remaining") if hasattr(r, "headers") else None
            if left is not None and str(left).isdigit() and int(left) < ALLOWANCE_RESERVE:
                # leave the rest of the hour's allowance to the other builders (reaches, waters_from_nhd)
                with self.lock:
                    self.blocked_until[host] = time.monotonic() + 3600
                    self.rate_limited[host] = -int(left)
            if r.status_code == 429 or r.status_code >= 500:
                why = f"HTTP {r.status_code}"
                ra = r.headers.get("Retry-After") or ""
                wait = float(ra) if ra.isdigit() else 2 * 2 ** attempt
                if r.status_code == 429 and wait > 30:
                    # the host's hourly allowance is spent (NLDI: 3,600 an hour per address, shared with the other
                    # builders): stop asking it this run instead of sleeping through the refresh
                    with self.lock:
                        self.blocked_until[host] = time.monotonic() + wait
                        self.rate_limited[host] = int(wait)
                    return None, "rate limited"
                time.sleep(max(0.0, min(30, wait, self.budget.left_s())))
                continue
            if r.status_code in (400, 404):
                return {"_status": r.status_code}, None
            if r.status_code >= 400:
                return None, f"HTTP {r.status_code}"
            try:
                d = r.json()
            except ValueError:
                why = "not JSON"
                continue
            if isinstance(d, dict) and d.get("error"):
                why = str(d["error"])[:120]
                time.sleep(max(0.0, min(30, 2 * 2 ** attempt, self.budget.left_s())))
                continue
            return d, None
        return None, why

    def _count(self, kind, t0, failed=False):
        with self.lock:
            self.counts[kind] += 1
            self.seconds[kind] += time.monotonic() - t0
            if failed:
                self.failures[kind] += 1


def transient(why) -> bool:
    """A failure that says nothing about the point (rate limit, server error, timeout): never cached."""
    w = str(why or "")
    return w.startswith("HTTP 429") or w.startswith("HTTP 5") or w in ("failed", "not JSON", "rate limited") or \
        w.endswith("Error") or w.endswith("Timeout") or "Timeout" in w


def fresh_error(entry: dict | None) -> bool:
    """A cached failure younger than ERROR_RETRY_DAYS (not asked again yet)."""
    if not isinstance(entry, dict) or not entry.get("error"):
        return False
    t = S.parse_time(entry.get("fetched_at"))
    return bool(t and datetime.now(UTC) - t < timedelta(days=ERROR_RETRY_DAYS))


def load_cache(path: Path = CACHE_PATH) -> dict:
    try:
        d = read_json(path) or {}
    except Exception:
        d = {}
    for k in ("hydro", "flowline", "waterbody", "dm"):
        d.setdefault(k, {})
    d.setdefault("version", 1)
    return d


def save_merged(path: Path, mine: dict) -> None:
    """Write a cache merged with what is on disk now (another run may have added answers since this one read it):
    for each table, the disk's entries this run lacks are kept, this run's win. Atomic replace."""
    try:
        disk = json.loads(path.read_text())
    except (OSError, ValueError):
        disk = {}
    out = dict(disk) if isinstance(disk, dict) else {}
    for k, v in mine.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":")))
    tmp.replace(path)


class Hydro:
    """NLDI hydrolocation -> COMID -> NHDPlus names -> the first named water downstream; every answer cached."""

    def __init__(self, net: Net, cache: dict):
        self.net, self.cache = net, cache
        self.lock = threading.Lock()

    def save(self, path: Path = CACHE_PATH) -> None:
        """Write the cache (only a run that asked something writes it: an offline or locked-out run never
        overwrites what a running hand run is filling)."""
        if self.net.offline or not sum(self.net.counts.values()):
            return
        with self.lock:
            save_merged(path, self.cache)

    @staticmethod
    def point_key(lat, lon) -> str:
        return f"{float(lat):.5f},{float(lon):.5f}"

    def cached_point(self, lat, lon) -> dict | None:
        e = self.cache["hydro"].get(self.point_key(lat, lon))
        if e is None or (e.get("error") and not fresh_error(e)):
            return None
        return e

    def _hydrolocation(self, lat, lon):
        """(entry, why): the raindrop trace (NLDI hydrolocation) of a point; entry None on failure."""
        coords = f"POINT({float(lon):.6f} {float(lat):.6f})"
        d, why = self.net.get_json("nldi-hydrolocation", f"{NLDI}/hydrolocation", {"coords": coords}, timeout=60,
                                   attempts=2)
        if d is not None and not d.get("_status"):
            for f in d.get("features") or []:
                pr = f.get("properties") or {}
                if pr.get("type") == "hydrolocation" and str(pr.get("comid") or "").strip():
                    c = (f.get("geometry") or {}).get("coordinates") or [None, None]
                    return {"comid": int(pr["comid"]), "via": "hydrolocation",
                            "measure": round(float(pr["measure"]), 3) if pr.get("measure") not in (None, "") else None,
                            "reachcode": pr.get("reachcode") or None,
                            "snap": [round(c[0], 6), round(c[1], 6)] if c[0] is not None else None}, None
            why = "no flowline"
        elif d is not None:
            why = f"HTTP {d.get('_status')}"
        return None, why

    def _position(self, lat, lon):
        """(entry, why): the flowline of the NHDPlus catchment holding the point (NLDI comid/position)."""
        coords = f"POINT({float(lon):.6f} {float(lat):.6f})"
        d, why = self.net.get_json("nldi-position", f"{NLDI}/comid/position", {"coords": coords}, timeout=30,
                                   attempts=2)
        for f in (d or {}).get("features") or []:
            pr = f.get("properties") or {}
            if pr.get("comid"):
                snap = None
                try:
                    from shapely.geometry import Point, shape
                    from shapely.ops import nearest_points
                    q = nearest_points(shape(f["geometry"]), Point(float(lon), float(lat)))[0]
                    snap = [round(q.x, 6), round(q.y, 6)]
                except Exception:
                    pass
                return {"comid": int(pr["comid"]), "via": "position", "measure": None, "reachcode": None,
                        "snap": snap}, None
        return None, (why or "no flowline")

    def _store(self, lat, lon, entry):
        if entry.get("snap"):
            entry["snap_m"] = round(dist_m(float(lat), float(lon), entry["snap"][1], entry["snap"][0]))
        entry["fetched_at"] = now_iso()
        with self.lock:
            self.cache["hydro"][self.point_key(lat, lon)] = entry
        return entry

    def locate(self, lat, lon, first: str = "position") -> dict | None:
        """The COMID a point drains to, cached: {comid, via, measure, reachcode, snap [lon, lat], snap_m} or
        {error}; None when the budget ran out. first="position": the catchment's flowline (NLDI comid/position,
        0.5 s), the raindrop trace later (refine); first="hydrolocation": the raindrop trace (NLDI hydrolocation,
        about 6 s, often HTTP 502 in November 2026), the catchment when it fails."""
        hit = self.cached_point(lat, lon)
        if hit is not None:
            return hit
        order = [self._position, self._hydrolocation] if first == "position" else [self._hydrolocation, self._position]
        whys = []
        for fn in order:
            entry, why = fn(lat, lon)
            if entry is not None:
                if whys:
                    entry["first_failed"] = whys[0]
                return self._store(lat, lon, entry)
            if why in ("budget", "offline") or transient(why):
                return None               # not an answer: asked again next run
            whys.append(why)
            if first == "position":
                break                     # the slow trace is not the fallback of the fast one
        return self._store(lat, lon, {"error": "; ".join(f"{w}" for w in whys)})

    def refine(self, lat, lon) -> bool | None:
        """Replace a cached catchment answer by the raindrop trace (NLDI hydrolocation); True when it did, False when
        the trace failed (remembered, not asked again for ERROR_RETRY_DAYS), None when the budget ran out."""
        hit = self.cached_point(lat, lon)
        if not hit or hit.get("via") != "position":
            return False
        t = S.parse_time(hit.get("trace_failed_at"))
        if t and datetime.now(UTC) - t < timedelta(days=ERROR_RETRY_DAYS):
            return False
        entry, why = self._hydrolocation(lat, lon)
        if entry is None:
            if why in ("budget", "offline"):
                return None
            if transient(why):
                return False
            with self.lock:
                hit["trace_failed_at"], hit["trace_failed"] = now_iso(), why
            return False
        entry["catchment_comid"] = hit["comid"]
        self._store(lat, lon, entry)
        return True

    def hydrolocate(self, lat, lon) -> dict | None:
        return self.locate(lat, lon)

    def _layer(self, table: str, layer: int, fields: str, comids) -> bool:
        """Fill cache[table] for the COMIDs it lacks (100 a request). False when the budget ran out."""
        need = sorted({int(c) for c in comids if str(int(c)) not in self.cache[table]})
        for i in range(0, len(need), 100):
            chunk = need[i:i + 100]
            d, why = self.net.get_json(f"epa-nhd-{layer}", f"{EPA_NHD}/{layer}/query",
                                       {"where": f"comid IN ({','.join(map(str, chunk))})", "outFields": fields,
                                        "returnGeometry": "false", "f": "json"}, timeout=60)
            if d is None:
                if why in ("budget", "offline"):
                    return False
                continue
            got = {}
            for f in d.get("features") or []:
                a = {k.lower(): v for k, v in (f.get("attributes") or {}).items()}
                if a.get("comid") is not None:
                    got[str(int(a["comid"]))] = a
            with self.lock:
                for c in chunk:
                    self.cache[table][str(c)] = got.get(str(c)) or {"missing": True}
        return True

    def flowlines(self, comids) -> dict | None:
        """{comid: attributes} or None when any of them could not be fetched (budget, failure): never an empty answer
        standing for an unnamed flowline."""
        self._layer("flowline", 2, FL_FIELDS, comids)
        if any(str(int(c)) not in self.cache["flowline"] for c in comids):
            return None
        return {int(c): self.cache["flowline"][str(int(c))] for c in comids}

    def waterbodies(self, comids) -> dict | None:
        self._layer("waterbody", 4, WB_FIELDS, comids)
        if any(str(int(c)) not in self.cache["waterbody"] for c in comids):
            return None
        return {int(c): self.cache["waterbody"][str(int(c))] for c in comids}

    def downstream(self, comid: int) -> list[dict] | None:
        """[{comid, start [lon, lat]}] of the main path DM_KM downstream (NLDI navigation DM), cached; None when
        the budget ran out."""
        k = str(int(comid))
        e = self.cache["dm"].get(k)
        if e is not None and not (isinstance(e, dict) and e.get("error") and not fresh_error(e)):
            return e if isinstance(e, list) else []
        d, why = self.net.get_json("nldi-dm", f"{NLDI}/comid/{int(comid)}/navigation/DM/flowlines",
                                   {"distance": str(DM_KM)}, timeout=60)
        if d is None and (why in ("budget", "offline") or transient(why)):
            return None
        out = []
        for f in (d or {}).get("features") or []:
            pr = f.get("properties") or {}
            c = pr.get("nhdplus_comid") or pr.get("comid")
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if coords and isinstance(coords[0], list) and coords and isinstance(coords[0][0], list):
                coords = coords[0]
            if c:
                out.append({"comid": int(c), "start": [round(coords[0][0], 6), round(coords[0][1], 6)] if coords else None})
        with self.lock:
            self.cache["dm"][k] = out if d is not None else {"error": why, "fetched_at": now_iso()}
        return out

    def name_of(self, fl: dict, wbs: dict | None) -> tuple[str | None, str | None, str]:
        """(GNIS name, GNIS id, what) of a flowline, or of the lake / estuary its artificial path runs through."""
        if fl.get("gnis_name"):
            return fl["gnis_name"], str(fl.get("gnis_id") or "") or None, "flowline"
        wb = (wbs or {}).get(int(fl["wbareacomid"])) if fl.get("wbareacomid") else None
        if wb and wb.get("gnis_name"):
            return wb["gnis_name"], str(wb.get("gnis_id") or "") or None, "waterbody"
        return None, None, ""

    def prefetch(self, points, workers: int = 1, first: str = "position", verbose: bool = False, save=None) -> None:
        """Ask everything the points need, in the fewest requests: locate the new points (workers in parallel), then
        the names of all their COMIDs (100 a request), then the downstream walks of the unnamed ones and their names.
        Stops where the budget runs out (water_at then says pending)."""
        new = [pt for pt in points if self.cached_point(*pt) is None]
        t0 = time.monotonic()

        def loc(pt):
            if self.net.budget.spent or any(t > time.monotonic() for t in self.net.blocked_until.values()):
                return None
            return self.locate(pt[0], pt[1], first=first)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for i, _ in enumerate(ex.map(loc, new), 1):
                if i % 100 == 0:
                    if save:
                        save()
                    if verbose:
                        print(f"  located {i}/{len(new)} new points, {sum(self.net.counts.values())} requests, "
                              f"{time.monotonic() - t0:.0f} s", flush=True)
        comids = {e["comid"] for e in (self.cached_point(*pt) for pt in points) if e and e.get("comid")}
        if self.flowlines(comids) is None:
            return
        fl = lambda c: self.cache["flowline"].get(str(int(c))) or {}       # noqa: E731
        wbc = {fl(c)["wbareacomid"] for c in comids if fl(c).get("wbareacomid") and not fl(c).get("gnis_name")}
        if wbc and self.waterbodies(wbc) is None:
            return
        wb = lambda c: self.cache["waterbody"].get(str(int(c))) or {}      # noqa: E731
        unnamed = sorted(c for c in comids if not fl(c).get("missing") and not fl(c).get("gnis_name")
                         and not (fl(c).get("wbareacomid") and wb(fl(c)["wbareacomid"]).get("gnis_name")))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            list(ex.map(lambda c: None if self.net.budget.spent else self.downstream(c), unnamed))
        if save:
            save()
        dm = set()
        for c in unnamed:
            e = self.cache["dm"].get(str(int(c)))
            if isinstance(e, list):
                dm |= {x["comid"] for x in e}
        if dm and self.flowlines(dm) is None:
            return
        wbc = {fl(c)["wbareacomid"] for c in dm if fl(c).get("wbareacomid") and not fl(c).get("gnis_name")}
        if wbc:
            self.waterbodies(wbc)

    def refine_all(self, points, workers: int = 1) -> Counter:
        """Spend what is left of the budget replacing catchment answers by raindrop traces, most reports first."""
        todo = [pt for pt in points if (self.cached_point(*pt) or {}).get("via") == "position"]
        out = Counter()

        def one(pt):
            if self.net.budget.spent:
                return None
            return self.refine(*pt)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for r in ex.map(one, todo):
                out[{True: "traced", False: "trace failed", None: "budget"}[r]] += 1
        return out

    def water_at(self, lat, lon) -> dict:
        """The water a point drains to. {status: done | pending | failed, ...}."""
        h = self.hydrolocate(lat, lon)
        if h is None:
            return {"status": "pending", "why": "request budget of this run"}
        if h.get("error"):
            return {"status": "failed", "why": h["error"]}
        comid = h["comid"]
        fls = self.flowlines([comid])
        if fls is None:
            return {"status": "pending", "why": "NHDPlus name not fetched yet (request budget or a failed request)"}
        fl = fls.get(comid) or {}
        wbs = self.waterbodies([fl["wbareacomid"]]) if fl.get("wbareacomid") else {}
        if wbs is None:
            return {"status": "pending", "why": "request budget of this run"}
        base = {"comid": comid, "via": h["via"], "measure": h.get("measure"),
                "reachcode": h.get("reachcode") or fl.get("reachcode"), "snap": h.get("snap"), "snap_m": h.get("snap_m"),
                "flowline_ftype": fl.get("ftype"), "streamorder": fl.get("streamorder")}
        if fl.get("missing"):
            return {**base, "status": "failed", "why": f"COMID {comid} not in EPA's NHDPlus V2.1 flowlines"}
        name, gid, what = self.name_of(fl, wbs)
        if name:
            return {**base, "status": "done", "relation": "on", "name": name, "gnis_id": gid, "named_comid": comid,
                    "named_what": what, "downstream_km": 0.0, "at": h.get("snap")}
        path = self.downstream(comid)
        if path is None:
            return {"status": "pending", "why": "request budget of this run"}
        comids = [p["comid"] for p in path]
        fls = self.flowlines(comids) if comids else {}
        if fls is None:
            return {"status": "pending", "why": "request budget of this run"}
        wbc = [f["wbareacomid"] for f in fls.values() if f.get("wbareacomid") and not f.get("gnis_name")]
        wbs = self.waterbodies(wbc) if wbc else {}
        if wbs is None:
            return {"status": "pending", "why": "request budget of this run"}
        order = sorted((p for p in path if not (fls.get(p["comid"]) or {}).get("missing")),
                       key=lambda p: -float((fls.get(p["comid"]) or {}).get("hydroseq") or 0))
        km = (float(fl.get("lengthkm") or 0) * (float(h["measure"]) / 100.0)) if h.get("measure") is not None \
            else float(fl.get("lengthkm") or 0) / 2
        for p in order:
            if p["comid"] == comid:
                continue
            f = fls.get(p["comid"]) or {}
            nm, ngid, nwhat = self.name_of(f, wbs)
            if nm:
                return {**base, "status": "done", "relation": "unnamed tributary to", "name": nm, "gnis_id": ngid,
                        "named_comid": p["comid"], "named_what": nwhat, "downstream_km": round(km, 2),
                        "at": p.get("start")}
            km += float(f.get("lengthkm") or 0)
        return {**base, "status": "done", "relation": "unnamed", "name": None, "gnis_id": None,
                "why": f"no named water within {DM_KM} km downstream (NHDPlus V2.1)"}


# ---------------------------------------------------------------- matching a water to a record

class WaterMatcher:
    def __init__(self, waters: dict | None = None):
        self.waters = S.load_waters() if waters is None else waters
        self.resolver = S.Resolver(self.waters, [], placement_rules={})
        self.by_gnis = defaultdict(list)
        self.by_comid = {}
        for slug, w in self.waters.items():
            if w.get("gnis_id"):
                self.by_gnis[(w.get("state"), str(w["gnis_id"]))].append(slug)
            for c in w.get("comids") or []:
                self.by_comid.setdefault(int(c), slug)

    def canon(self, slug):
        return self.resolver.canon(slug) if hasattr(self.resolver, "canon") else slug

    def match(self, name: str | None, gnis_id: str | None, comid: int | None, state: str | None, lat, lon) \
            -> tuple[str | None, str]:
        """(slug, how) of the record for a named NHD water near (lat, lon); (None, why) when there is none."""
        if comid is not None and int(comid) in self.by_comid:
            return self.by_comid[int(comid)], f"COMID {comid} is in the record's NHD flowlines"
        if gnis_id and (state, str(gnis_id)) in self.by_gnis:
            slugs = self.by_gnis[(state, str(gnis_id))]
            near = self.resolver.nearest(slugs, lat, lon) if lat is not None else None
            return (near[1] if near else slugs[0]), f"GNIS id {gnis_id}"
        if not name or not state:
            return None, "no name"
        slugs, _, _ = self.resolver.by_name(name, state, lat, lon)
        for s in slugs:
            if S.norm_name(self.waters[s].get("name") or "") != S.norm_name(name) and \
                    S.norm_name(name) not in [S.norm_name(a) for a in self.waters[s].get("aliases") or []]:
                continue
            d = self.resolver.distance_m(s, lat, lon) if lat is not None else None
            lim, _ = self.resolver.name_limit_m(s)
            if d is None:
                b = self.waters[s].get("bbox")
                pad = lim / 111_320
                if b and b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad:
                    return s, f"name in {state}, within the record's box"
                continue
            if d <= lim:
                return s, f"name in {state}, {d:.0f} m from the record"
        return None, f"no {state} record named {name!r} near the point"

    def report_slugs(self, place: dict) -> list[str]:
        return [self.canon(s) for s in place.get("reports_water_slugs") or []]

    def check(self, place: dict, slug: str | None, name: str | None) -> tuple[str, str]:
        """(agree | disagree | no_report_water | unclear, note) of the hydrolocated water against the reports'.
        disagree: the reports' water has a record and it is another; unclear: the reports' water text names a water
        this check cannot compare (no record, another spelling)."""
        rs = self.report_slugs(place)
        texts = place.get("reports_water_text") or []
        if not rs and not texts:
            return "no_report_water", "the reports name no water"
        if slug and slug in rs:
            return "agree", f"the reports name it ({slug})"
        if name and any(name_in_text(name, t) for t in texts):
            return "agree", "the reports' water text names it"
        if rs:
            return "disagree", f"the reports name {', '.join(rs[:3])}"
        return "unclear", f"the reports name {texts[0][:60]!r}, which has no record to compare"


NUM_WORDS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight",
             "9": "nine", "10": "ten", "11": "eleven", "12": "twelve", "18": "eighteen"}


def compact_name(t: str) -> str:
    """A water name compared without spaces, kind abbreviations expanded and numbers as words ("2 Mile Creek" and
    "Twomile Creek" are one name)."""
    ws = [NUM_WORDS.get(w, w) for w in S.norm_name(str(t or "")).split()]
    return "".join(ws)


def name_in_text(name: str, text: str) -> bool:
    n, t = compact_name(name), compact_name(text)
    return bool(n) and n in t


WATER_SNAP_MAX_M = 1000        # a point farther than this from its flowline: the traced water is only a candidate


# ---------------------------------------------------------------- the run

def previous_rows(path: Path = OUT) -> dict[str, list[dict]]:
    try:
        d = read_json(path) or {}
    except Exception:
        return {}
    out = defaultdict(list)
    for r in d.get("outfalls") or []:
        if isinstance(r, dict) and r.get("discharger_id") and r.get("lat") is not None:
            out[r["discharger_id"]].append(r)
    return out


def carry_over(places: list[dict], prev: dict[str, list[dict]], now: str) -> None:
    """Keep each place's id and first_seen from the previous output's row of the same operator within 50 m; a
    previous row goes to one place only (the nearest pairs first), so two places never share an id."""
    pairs = []
    for i, p in enumerate(places):
        for j, r in enumerate(prev.get(p["discharger_id"], [])):
            try:
                d = dist_m(p["lat"], p["lon"], float(r["lat"]), float(r["lon"]))
            except (TypeError, ValueError):
                continue
            if d <= CLUSTER_M:
                pairs.append((d, i, j, r))
    used_p, used_r = set(), set()
    for d, i, j, r in sorted(pairs, key=lambda x: (x[0], x[1], x[2])):
        key = (places[i]["discharger_id"], j)
        if i in used_p or key in used_r:
            continue
        used_p.add(i)
        used_r.add(key)
        places[i]["id"] = r.get("id") or places[i]["id"]
        places[i]["outfall"] = places[i]["id"]
        places[i]["first_seen"] = r.get("first_seen") or now
    taken = {p["id"] for i, p in enumerate(places) if i in used_p}
    for i, p in enumerate(places):
        if i not in used_p:
            p["first_seen"] = now
            if p["id"] in taken:                      # a fresh id never takes one a carried-over place holds
                p["id"] = p["outfall"] = place_id(p["discharger_id"] + "|new", p["lat"], p["lon"])


def water_fields(p: dict, w: dict, matcher: WaterMatcher) -> None:
    """The hydrolocated water on the place: p["water"], and receiving_water / water_slugs / water_match."""
    rs = matcher.report_slugs(p)
    texts = p.get("reports_water_text") or []
    slug, how = (None, "")
    if w.get("status") == "done" and w.get("name"):
        at = w.get("at") or w.get("snap") or [p["lon"], p["lat"]]
        slug, how = matcher.match(w["name"], w.get("gnis_id"), w.get("named_comid"), p.get("state"), at[1], at[0])
    label = None
    if w.get("status") == "done":
        label = (w["name"] if w.get("relation") == "on" else
                 f"unnamed tributary to {w['name']}" if w.get("name") else "unnamed stream (no named water downstream)")
    check, note = matcher.check(p, slug, w.get("name")) if w.get("status") == "done" else ("not_checked", "")
    via = {"hydrolocation": "USGS NLDI hydrolocation (raindrop trace)",
           "position": "USGS NLDI comid/position (the NHDPlus catchment's flowline, where the raindrop trace "
                        "lands; the trace itself not yet run)"}.get(w.get("via"), "")
    p["water"] = {k: v for k, v in {
        "status": w.get("status"), "why": w.get("why"), "label": label, "name": w.get("name"),
        "relation": w.get("relation"), "gnis_id": w.get("gnis_id"), "comid": w.get("comid"),
        "named_comid": w.get("named_comid"), "reachcode": w.get("reachcode"), "measure": w.get("measure"),
        "snap_m": w.get("snap_m"), "downstream_km": w.get("downstream_km"), "via": via or None,
        "water_slug": slug, "record_match": how if slug else (how or None),
        "record": "matched" if slug else ("no record" if w.get("name") else None),
        "check": check, "check_note": note or None,
    }.items() if v is not None}
    far = (w.get("snap_m") or 0) > WATER_SNAP_MAX_M
    if far and w.get("status") == "done":
        p["water"]["candidate_only"] = (f"the point lies {w['snap_m']} m from the flowline (over "
                                        f"{WATER_SNAP_MAX_M} m: sewered ground, the traced water is a candidate)")
    if rs:
        p["water_slugs"] = rs
        p["receiving_water"] = texts[0] if texts else None
        p["water_match"] = "reports" + (f"; hydrolocation {check}" if check not in ("not_checked",) else "")
    elif slug and not far and check in ("agree", "no_report_water"):
        p["water_slugs"] = [slug]
        p["receiving_water"] = texts[0] if texts else label
        p["water_match"] = "hydrolocation" + ("" if w.get("relation") == "on" else " (unnamed tributary)")
    else:
        p["water_slugs"] = []
        p["receiving_water"] = texts[0] if texts else label
        p["water_match"] = "none"


def method_text(p: dict) -> str:
    src = {"source": "the reports' own coordinates", "geocode": "a geocode of the reports' address",
           "outfall_layer": "an official outfall layer the reports name"}.get(p["coord_source"], p["coord_source"])
    parts = [f"point from {src} ({p['report_count']} report{'s' if p['report_count'] != 1 else ''} within "
             f"{CLUSTER_M} m: {', '.join(sorted(p['sources']))})"]
    if p.get("geolocation"):
        parts = [p["geolocation"]["method"]]
    w = p.get("water") or {}
    if w.get("status") == "done" and w.get("via"):
        parts.append(f"water by {w['via']} to NHDPlus V2.1 COMID {w.get('comid')}"
                     + (f", downstream {w['downstream_km']} km to the first named water"
                        if w.get("relation") == "unnamed tributary to" else ""))
    elif w.get("status") in ("pending", "failed"):
        parts.append(f"water not traced yet ({w.get('why')})")
    return "; ".join(parts)


def public_row(p: dict) -> dict:
    p = {k: v for k, v in p.items() if not k.startswith("_")}
    p["label"] = PLANT_LABEL if p.get("stand_in") else PUBLIC_LABEL
    p["on_map"] = p["record_status"] != "superseded" and p["reached_water"] != "no"
    p["method"] = method_text(p)
    return strip_personal(p)


def waters_without_record(places: list[dict]) -> list[dict]:
    agg = {}
    for p in places:
        w = p.get("water") or {}
        if w.get("record") != "no record" or not w.get("name"):
            continue
        k = (p.get("state"), w["name"], w.get("gnis_id"))
        a = agg.setdefault(k, {"state": k[0], "name": k[1], "gnis_id": k[2], "comids": set(), "operators": set(),
                               "places": 0, "reports": 0, "as_unnamed_tributary": 0})
        a["comids"].add(w.get("named_comid"))
        a["operators"].add(p["discharger_id"])
        a["places"] += 1
        a["reports"] += p["report_count"]
        a["as_unnamed_tributary"] += w.get("relation") == "unnamed tributary to"
    out = []
    for a in agg.values():
        out.append({**a, "comids": sorted(c for c in a["comids"] if c), "operators": sorted(a["operators"])})
    return sorted(out, key=lambda a: (-a["reports"], a["state"] or "", a["name"]))


def summarize(places: list[dict], drops: Counter, unlocated: list[dict], key: dict, by_id: dict,
              registry: list[dict]) -> dict:
    reg_permits = {str(o["npdes_permit"]).upper() for o in registry}
    no_point = []
    for rid, r in by_id.items():
        perms = {p.upper() for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])] if p}
        if not perms & reg_permits:
            no_point.append(rid)
    live = {p["discharger_id"] for p in places if p["record_status"] != "superseded"}
    gained = sorted(set(no_point) & live)
    by_state = defaultdict(Counter)
    for p in places:
        by_state[p.get("state") or "?"][f"{p['record_status']}/{p['confidence']}"] += 1
    wat = Counter()
    for p in places:
        w = p.get("water") or {}
        if p["record_status"] == "superseded":
            continue
        if w.get("status") != "done":
            wat[w.get("status") or "not asked"] += 1
        elif w.get("relation") == "unnamed":
            wat["unnamed, no named water downstream"] += 1
        else:
            wat[f"{'unnamed tributary' if w.get('relation') != 'on' else 'named flowline'}: "
                f"{'record matched' if w.get('water_slug') else 'no record yet'}"] += 1
    return {
        "places": len(places),
        "by_status": dict(Counter(p["record_status"] for p in places)),
        "by_confidence": dict(Counter(p["confidence"] for p in places if p["record_status"] != "superseded")),
        "by_kind": dict(Counter(p["outfall_kind"] for p in places if p["record_status"] != "superseded")),
        "by_state": {s: dict(c) for s, c in sorted(by_state.items())},
        "on_map": sum(1 for p in places if p["record_status"] != "superseded" and p["reached_water"] != "no"),
        "reports_placed": sum(p["report_count"] for p in places),
        "operators_with_places": len({p["discharger_id"] for p in places}),
        "registry_operators_without_registry_point": len(no_point),
        "of_them_gaining_a_place": len(gained),
        "of_them_gaining_by_state": dict(Counter((by_id[g].get("state") or "?") for g in gained)),
        "waters": dict(wat),
        "water_checks": dict(Counter((p.get("water") or {}).get("check") for p in places
                                     if (p.get("water") or {}).get("status") == "done")),
        "reports_without_point": len(unlocated),
    }


def run(args) -> dict:
    t0 = time.monotonic()
    now = now_iso()
    key, by_id = operator_index()
    events = load_report_events()
    places, drops, unlocated = build_places(events, key=key, by_id=by_id)
    registry = registry_rows()
    args.judge = None
    privacy_model = None
    if getattr(args, "llm", False):
        from build.llm_judge import Judge
        args.judge = Judge(cap_usd=args.llm_cap_usd, offline=args.offline, budget_s=getattr(args, "llm_budget_s", None))
    if getattr(args, "geolocate", False):
        try:
            from build import report_geolocate as RG
            anchors = defaultdict(list)
            for p in places:
                anchors[p["discharger_id"]].append((p["lat"], p["lon"]))
            extra, gstats = RG.geolocate(unlocated, args, key=key, by_id=by_id, anchors=anchors)
            gstats["joined_to_a_place_from_coordinates"] = join_places(places, extra)
        except Exception as ex:                     # the geolocation step never stops the build
            gstats = {"error": f"{type(ex).__name__}: {ex}"[:300]}
    else:
        gstats = {"skipped": "geolocation not asked this run (--geolocate)"}
    if args.judge is not None:
        # the model's privacy opinion on the places' location texts (rules ran first; it can only exclude more)
        from build import report_geolocate as RG
        by_eid = {e["event_id"]: e for e in events}
        n_before = len(places)
        places, more = RG.privacy_second_opinion(places, by_eid, args.judge)
        drops.update({k: v for k, v in more.items() if k.startswith("excluded")})
        privacy_model = {"places_checked": n_before, **dict(more)}
        args.judge.save()
    classify(places, registry, state_layer_rows())
    carry_over(places, previous_rows(), now)
    seen_ids = Counter()
    for p in places:                                  # ids are unique in the output, whatever happened above
        seen_ids[p["id"]] += 1
        if seen_ids[p["id"]] > 1:
            p["id"] = p["outfall"] = f"{p['id']}-{seen_ids[p['id']]}"
    cache = load_cache()
    budget = Budget(args.budget_s, args.max_requests)
    net = Net(budget, offline=args.offline)
    hydro = Hydro(net, cache)
    matcher = WaterMatcher()
    todo = sorted((p for p in places if p["record_status"] != "superseded"),
                  key=lambda p: (-p["report_count"], p["id"]))
    results = {}
    refine_stats = Counter()
    if args.no_water:
        for p in todo:
            results[p["id"]] = {"status": "pending", "why": "water step not run (--no-water)"}
    else:
        pts = list(dict.fromkeys((p["lat"], p["lon"]) for p in todo))      # most reports first
        hydro.prefetch(pts, args.workers, first=args.first, verbose=args.verbose, save=lambda: hydro.save(CACHE_PATH))
        for p in todo:
            results[p["id"]] = hydro.water_at(p["lat"], p["lon"])
        if args.refine and not budget.spent:
            refined = hydro.refine_all(pts, args.workers)
            refine_stats.update(refined)
        if sum(net.counts.values()):
            hydro.save(CACHE_PATH)
    for p in places:
        if p["record_status"] == "superseded":
            p["water"] = {"status": "not_asked", "why": "superseded by an official outfall"}
            p["water_slugs"] = matcher.report_slugs(p)
            p["receiving_water"] = (p.get("reports_water_text") or [None])[0]
            p["water_match"] = "reports" if p["water_slugs"] else "none"
        else:
            water_fields(p, results.get(p["id"]) or {"status": "pending", "why": "not reached"}, matcher)
    if getattr(args, "geolocate", False):
        try:
            from build import report_geolocate as RG
            RG.after_water(places, args, gstats)
        except Exception as ex:
            gstats["after_water_error"] = f"{type(ex).__name__}: {ex}"[:300]
    places.sort(key=lambda p: (p.get("state") or "", p["discharger_id"], -p["report_count"], p["id"]))
    rows = [public_row(p) for p in places]
    summary = summarize(places, drops, unlocated, key, by_id, registry)
    doc = {
        "source_id": SOURCE_ID,
        "generated_at": now,
        "label": PUBLIC_LABEL,
        "rule": ("docs/national-outfalls.md: places where operators' own reports put an overflow (50 m), provisional "
                 "until an official outfall of the same operator lies within 100 m; build/provisional_outfalls.py"),
        "count": len(rows),
        "summary": summary,
        "drops": dict(drops.most_common()),
        "waters_without_record": waters_without_record(places),
        "geolocation": gstats,
        "model": args.judge.stats() if args.judge is not None else None,
        "model_privacy": privacy_model,
        "run": {"seconds": round(time.monotonic() - t0, 1), "requests": dict(net.counts),
                "request_failures": dict(net.failures), "rate_limited": dict(net.rate_limited),
                "request_seconds": {k: round(v, 1) for k, v in net.seconds.items()},
                "budget_s": args.budget_s, "max_requests": args.max_requests, "budget_spent": budget.spent,
                "workers": args.workers, "first": args.first, "refined": dict(refine_stats),
                "pending_water": sum(1 for p in places if (p.get("water") or {}).get("status") == "pending")},
        "outfalls": rows,
    }
    write_json(OUT, doc)
    return doc


LOCK_PATH = BUILD_DIR / "provisional-outfalls.lock"


def lock_holder() -> str | None:
    """The pid of a live run holding the lock, else None (a stale lock is ignored)."""
    try:
        pid = int(LOCK_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return str(pid)


def acquire_lock() -> bool:
    """Take the lock atomically (O_CREAT | O_EXCL); a stale lock (dead pid) is removed and taken."""
    for _ in range(2):
        try:
            fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if lock_holder():
                return False
            try:
                LOCK_PATH.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true", help="no requests: cached answers only")
    ap.add_argument("--no-water", action="store_true", help="skip the hydrolocation step")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S, help="seconds of requests this run")
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    ap.add_argument("--workers", type=int, default=1, help="parallel NLDI workers (keep it low: 1 to 3)")
    ap.add_argument("--first", choices=("position", "hydrolocation"), default="position",
                    help="new points: the catchment's flowline first (fast), or the raindrop trace first")
    ap.add_argument("--no-refine", dest="refine", action="store_false",
                    help="do not spend the rest of the budget replacing catchment answers by raindrop traces")
    ap.add_argument("--geolocate", action="store_true", help="also place reports without a point (step 4)")
    ap.add_argument("--geo-budget-s", type=float, default=60)
    ap.add_argument("--llm", action="store_true", help="let the language model read location text (step 4)")
    ap.add_argument("--llm-cap-usd", type=float, default=2.0, help="spend cap of this run's model calls")
    ap.add_argument("--llm-budget-s", type=float, default=None, help="seconds of model calls this run (cached answers"
                                                                     " are always used)")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    if not acquire_lock():
        # another run (a hand batch) is building: it writes the output and the caches; this one touches nothing
        print(f"provisional outfalls: run {lock_holder()} holds {LOCK_PATH.name}; the previous output stays",
              flush=True)
        return 0
    try:
        doc = run(args)
    finally:
        LOCK_PATH.unlink(missing_ok=True)
    s = doc["summary"]
    print(f"outfalls-reported: {doc['count']} places ({s['by_status']}), {s['on_map']} on the map; "
          f"{s['of_them_gaining_a_place']} of {s['registry_operators_without_registry_point']} operators without a "
          f"registry point gain one; waters {s['waters']}; requests {doc['run']['requests']} in "
          f"{doc['run']['seconds']} s; pending {doc['run']['pending_water']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
