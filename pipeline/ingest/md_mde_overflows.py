"""MDE Reported Sewer Overflows (New for 2023), Maryland -> data/build/events/md-mde-overflows.json

Source
  Maryland Department of the Environment, "Reported Sewer Overflows (New for 2023)" on the Maryland
  Open Data Portal (Socrata stgj-u72u): every CSO, SSO, plant bypass and "unauthorized discharge"
  reported to MDE under Env. Sec. 9-331.1 / COMAR 26.08.10 since February 2023 (about 3,500 rows).
  CSV download https://opendata.maryland.gov/api/views/stgj-u72u/rows.csv?accessType=DOWNLOAD (the
  SODA endpoint sits behind Cloudflare, which blocked a compound query; the CSV is one simple GET),
  metadata https://opendata.maryland.gov/api/views/stgj-u72u.json. Licence: Public Domain;
  attribution "Maryland Department of the Environment".

Quirks (research/md/report.md 2.2, and what this module found)
  - The whole table is replaced on every reload and its `id` is a row number (id 1 = newest), so the
    record key is composite: npdes_no + start date + start time + normalised address (street words
    abbreviated, punctuation and case ignored). Rows that share a key (the table repeats some rows
    word for word) get "~2", "~3" in order of volume, and the copies are duplicate_of the first.
  - The same overflow can appear under two owners or two collection-system ids (2026-05-23 428 E
    Preston St: Baltimore City 58,080 gal and Baltimore County 10,000 gal). Rows with the same start
    minute and the same address but different keys are kept; the lower-volume rows are duplicate_of
    the highest. Rows MDE itself marks "(DUPLICATE)" are duplicate_of the original row when one is
    found (same address, same day or within three days, same owner first).
  - Baltimore City SSOs are also on the City's own layer (ingest/md_baltimore_sso.py, run before this
    module): an MDE row of the same operator that starts the same day at the same address, or within
    200 m, is duplicate_of the City's record, which has the end time, point and revised volume.
  - Event types: CSO -> cso, SSO -> sso, Bypass -> bypass, Unauthorized Discharge -> sso with the
    source's label kept in raw._source_type (docs/decisions.md, Maryland decision 2).
  - Times: start_date + start_time are local (America/New_York). ended_at = start + duration_day/
    hour/minute when the duration is given (status ended), as elapsed time (common.end_after: across a clock
    change the end is the elapsed one; a start known only to the day gives the day of the latest end it allows);
    with no duration, status unknown.
  - Coordinates (41% of rows): latitude and longitude are swapped on some rows, the longitude lacks
    its minus sign on others, one longitude is typed as degrees-minutes-seconds text. Each pair is
    tried as given, swapped, with the longitude's sign added, and both, and kept only in Maryland
    (lat 37.9 to 39.8, lon -79.5 to -75.0); raw._coords says which. State-plane-like numbers (6632,
    2557) and points in other states are not used.
  - Degrees and decimal minutes written as decimal degrees (2026-11-03): about one row in ten gives the digits
    after the point as minutes with their own point dropped (39.4012 for 39 deg 40.12 min; Braddock Run's
    LaVale rows, Jennings Run, George's Creek, Howard County's), which lands tens of kilometres from the
    place (39.4012, -78.4734 is in West Virginia; 39 deg 40.12 min N, 78 deg 47.34 min W is LaVale, the
    address 1 Old Mt Savage Rd). When the row's county is known and the pair, after the repairs above,
    lies outside that county's Census bounding box (COUNTY_BBOX), the digits are read as minutes (as given or
    swapped, at least three decimals, minutes under 60) and the reading is used when it lies inside the
    county's box; raw._coords says "read as degrees and decimal minutes". A point inside its county is
    never changed, a row with no county is not tried, and a pair whose minutes are 60 or more is not
    degrees and minutes. The repair applies only when the repaired point lies in the row's county and the
    pair as decimal degrees does not; otherwise the point is left as given and raw._coords says it is
    outside its county (review 2026-11-03 P2-4). The county box
    is the only witness: a correct point whose county field is wrong can still be moved when its digits
    read as minutes land in that county (the review's examples); a ZIP or address check would be needed.
  - receiving_water is free text. "none", "N/A", "ground"/"groundwater", "storm drain", "no",
    "unknown" or empty keep the text and name no water (decision 3); other text is matched within
    Maryland, checked against the point and the county (ingest/md_waters.py and its name traps).
  - Volumes: discharge_volume via common.parse_volume_gal; early figures are revised by operators, so
    every change of a row seen between runs is kept in raw._revisions (the old values and when).
  - Operator: discharger_id from research/md/dischargers.json by npdes_no (collection-system pseudo
    ids included; MDCPRIVAT is not an operator), then by owner name; DC Water's Potomac Interceptor
    rows (pseudo-permit MDC521199) are the operator dc-water (decision 5). npdes_permit is filled only
    for a real permit number (MD + 7 digits); MDE's collection-system ids stay in raw.row.npdes_no.
  - source_updated_at is the dataset's rowsUpdatedAt (metadata), the same for every row; MDE
    publishes no per-row report or publication time (reported_at, published_at null). Each record's
    raw._first_seen_at is the first run of this module that saw it (our clock).
  - Every distinct CSV download is kept in data/raw/md-mde-overflows/ (with the metadata of that
    load); records that leave the table are kept (raw._missing_from_source_since), and when a row
    with the same npdes_no, date and time (or date and address) replaced them they become
    duplicate_of it.

Cadence: daily (metadata "Daily"; MDE's page says monthly; one reload observed with about one day
of latency). Run from pipeline/:  python -m ingest.md_mde_overflows [--file rows.csv --meta meta.json]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, ROOT, end_after, event, now_iso, parse_volume_gal,
                    path_notes_to_meta, read_json, save_raw, write_events, write_json)
from ingest import md_waters

SOURCE_ID = "md-mde-overflows"
DATASET = "stgj-u72u"
CSV_URL = f"https://opendata.maryland.gov/api/views/{DATASET}/rows.csv?accessType=DOWNLOAD"
META_URL = f"https://opendata.maryland.gov/api/views/{DATASET}.json"
PAGE_URL = f"https://opendata.maryland.gov/dataset/Reported-Sewer-Overflows-New-for-2023-/{DATASET}"
STATE_FILE = BUILD_DIR / "md-mde-overflows-state.json"
RESEARCH_DISCHARGERS = ROOT / "research" / "md" / "dischargers.json"
BALTIMORE_EVENTS = EVENTS_DIR / "md-baltimore-sso.json"
TZ = ZoneInfo("America/New_York")
TYPES = {"cso": "cso", "sso": "sso", "bypass": "bypass", "unauthorized discharge": "sso"}
NEAR_M = 200
ID_OVERRIDES = {"md-dc-water-potomac-interceptor": "dc-water"}   # decision 5: DC Water's pipe, operator dc-water
NOT_AN_OPERATOR = {"MDCPRIVAT"}
REAL_PERMIT = re.compile(r"^MD\d{7}$")
PERMIT_TOKEN = re.compile(r"\bMD[0-9A-Z]{7}\b")
# MDE owner_name spellings -> research/md/dischargers.json ids (owners seen 2023-2026 with a research row)
OWNER_IDS = {
    "baltimore city dpw": "md-baltimore-city-dpw", "baltimore county dpw": "md-baltimore-county-dpw",
    "wssc": "md-wssc-water", "allegany county dpw": "md-allegany-county-dpw", "city of frostburg": "md-frostburg",
    "anne arundel county dpw": "md-anne-arundel-dpw", "mayor and city council of cumberland": "md-cumberland",
    "lavale sanitary commission": "md-lavale", "howard county dpw": "md-howard-county-dpw",
    "city of cambridge dpw": "md-cambridge", "city of crisfield": "md-crisfield",
    "worcester county dpw": "md-worcester-county", "st marys county metropolitan commission": "md-metcom",
    "maryland environmental service": "md-mes", "state of maryland mes": "md-mes",
    "harford county dpw": "md-harford-county-dpw",
    "washington county department of water quality": "md-washington-county-dwq", "town of hancock": "md-hancock",
    "charles county dpw": "md-charles-county-dpw", "u s navy": "md-us-navy",
    "frederick county division of utilities": "md-frederick-county-utilities",
    "garrett county sanitary district inc": "md-garrett-sanitary",
    "american water operations and maintenance inc": "md-fort-meade-american-water",
    "city of frederick dpw": "md-frederick-city", "town of rock hall": "md-rock-hall",
    "gatewater landing apartments": "md-gatewater-landing", "gatewater landing": "md-gatewater-landing",
    "carroll county bureau of utilities": "md-carroll-county",
    "somerset county sanitary district inc": "md-somerset-sanitary", "city of rockville": "md-rockville",
    "mayor and council of myersville": "md-myersville", "calvert county dpw": "md-calvert-county",
    "city of annapolis": "md-annapolis", "city of salisbury": "md-salisbury",
    "maryland water service utilities inc": "md-maryland-water-service", "town of perryville": "md-perryville",
    "dorchester county water and wastewater department": "md-dorchester-county",
    "dorchester county dpw": "md-dorchester-county", "city of hagerstown": "md-hagerstown",
    "dc water": "md-dc-water-potomac-interceptor", "town of westernport": "md-westernport",
    "easton utilities commission": "md-easton-utilities", "town of chesapeake city": "md-chesapeake-city",
}
NO_WATER = re.compile(r"^\s*(n\s*/?\s*a|none|no|nope|unknown|unk|null|nil|tbd|-+|0|ground|groundwater|ground water|"
                      r"the ground|on the ground|ground surface|grass|soil|land|storm ?drains?|storm ?sewer|"
                      r"storm ?drain system|side ditch|ditch|duplicate\b.*)\s*[.!]*\s*$", re.I)
NOT_REACHED = re.compile(r"\b(did not|didn'?t|does not|doesn'?t|never|no discharge)\s+(enter|reach|go)", re.I)
ADDR_WORDS = {"street": "st", "str": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr", "lane": "ln",
              "court": "ct", "place": "pl", "boulevard": "blvd", "parkway": "pkwy", "highway": "hwy", "terrace": "ter",
              "circle": "cir", "square": "sq", "turnpike": "tpke", "east": "e", "west": "w", "north": "n",
              "south": "s", "mount": "mt", "saint": "st", "route": "rt", "rte": "rt", "pike": "pk", "trail": "trl",
              "and": "and"}
DMS = re.compile(r"^\s*(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['’m]\s*([\d.]+)\s*(?:\"|”|''|s)?\s*([NSEW])\s*$", re.I)
# Census 2020 county bounding boxes (TIGERweb State_County layer 11, STATE=24; lon_min, lat_min, lon_max, lat_max,
# rounded outward to 0.001 degree): the row's own county decides whether a point is where the row says
COUNTY_BBOX = {
    "allegany": (-79.068, 39.438, -78.313, 39.724), "anne arundel": (-76.841, 38.711, -76.349, 39.238),
    "baltimore": (-76.896, 39.156, -76.287, 39.722), "baltimore city": (-76.712, 39.197, -76.529, 39.373),
    "calvert": (-76.702, 38.305, -76.321, 38.770), "caroline": (-76.016, 38.635, -75.707, 39.144),
    "carroll": (-77.312, 39.348, -76.787, 39.721), "cecil": (-76.234, 39.360, -75.766, 39.723),
    "charles": (-77.324, 38.171, -76.662, 38.707), "dorchester": (-76.439, 38.058, -75.701, 38.705),
    "frederick": (-77.678, 39.220, -77.106, 39.721), "garrett": (-79.488, 39.202, -78.928, 39.723),
    "harford": (-76.570, 39.254, -76.035, 39.722), "howard": (-77.188, 39.103, -76.696, 39.370),
    "kent": (-76.355, 38.992, -75.756, 39.406), "montgomery": (-77.528, 38.934, -76.888, 39.354),
    "prince georges": (-77.087, 38.535, -76.669, 39.132), "queen annes": (-76.437, 38.807, -75.747, 39.262),
    "st marys": (-76.875, 37.888, -76.201, 38.514), "somerset": (-76.237, 37.886, -75.539, 38.299),
    "talbot": (-76.464, 38.571, -75.896, 38.946), "washington": (-78.364, 39.318, -77.469, 39.723),
    "wicomico": (-75.949, 38.215, -75.307, 38.561), "worcester": (-75.662, 37.994, -74.986, 38.453),
}
# a person named after an honorific in operators' free text ("Mr. Smith reports ..."); "Dr" is left out
# (in this table it is Drive). The export's redactor (build/redact.py) then runs over every record too.
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Mx|Miss)\.?\s+[A-Z][A-Za-z'\u2019-]+(?:\s+[A-Z][A-Za-z'\u2019-]+)?")
FREE_TEXT_FIELDS = ("overflow_cause", "receiving_water")
CSV_FIELDS = ["overflow_type", "facility_collection_system", "npdes_no", "start_date", "start_time", "duration_day",
              "duration_hour", "duration_minute", "overflow_address", "zip", "owner_name", "discharge_volume",
              "overflow_cause", "receiving_water", "county", "penalty_id", "overflow_latitude", "overflow_longitude", "id"]


# ---------------------------------------------------------------- parsing helpers

def field_name(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def read_rows(text: str) -> list[dict]:
    rd = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    out = []
    for r in rd:
        out.append({field_name(k): (v if v is not None else "") for k, v in r.items() if k is not None})
    return out


def clean(v) -> str:
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def parse_date(s: str):
    s = clean(s)
    for fmt in ("%m/%d/%Y", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def parse_clock(s: str):
    s = clean(s)
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def start_of(row: dict) -> tuple[datetime | None, str | None]:
    d, t = parse_date(row.get("start_date")), parse_clock(row.get("start_time"))
    if d is None:
        return None, None
    if t is None:
        return datetime(d.year, d.month, d.day, tzinfo=TZ), "day"
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=TZ), "minute"


def duration_of(row: dict) -> timedelta | None:
    parts = [clean(row.get(k)) for k in ("duration_day", "duration_hour", "duration_minute")]
    if not any(parts):
        return None
    try:
        d, h, m = (float(p) if p else 0.0 for p in parts)
    except ValueError:
        return None
    if min(d, h, m) < 0:
        return None
    return timedelta(days=d, hours=h, minutes=m)


def norm_addr(s: str | None, for_match: bool = False) -> str:
    t = clean(s).lower()
    if for_match:
        t = re.sub(r"\(\s*duplicate\s*\)|\bduplicate\b", " ", t)
        t = re.sub(r"\s+-\s+.*$", "", t)             # "428 E Preston St - SSO Site #72" -> "428 E Preston St"
    t = t.replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(ADDR_WORDS.get(w, w) for w in t.split())


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def coord_num(s: str) -> tuple[float | None, str | None]:
    s = clean(s)
    if not s:
        return None, None
    m = DMS.match(s)
    if m:
        v = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3)) / 3600
        return (-v if m.group(4).upper() in "SW" else v), f"{s!r} read as degrees-minutes-seconds"
    try:
        v = float(s)
    except ValueError:
        m = re.fullmatch(r"(-?\d{1,3}\.\d{3,})\s*[A-Za-z]", s)
        if m:
            return float(m.group(1)), f"{s!r}: trailing letter dropped"
        return None, f"{s!r} is not a number"
    return (v if math.isfinite(v) else None), None


def in_box(box, lat, lon) -> bool:
    return box[0] <= lon <= box[2] and box[1] <= lat <= box[3]


def decimals(s: str) -> int:
    t = clean(s)
    return len(t.split(".")[-1]) if "." in t else 0


def dmm_degrees(v: float) -> float | None:
    """The magnitude of a number written as degrees and decimal minutes with the minutes' point dropped
    (39.4012 = 39 deg 40.12 min = 39.6687); None when those minutes are 60 or more."""
    s = abs(v)
    deg = math.floor(s)
    minutes = round((s - deg) * 100, 4)
    return deg + minutes / 60 if minutes < 60 else None


def dmm_pair(lat_s: str, lon_s: str, a: float, b: float, box) -> tuple[float, float, str] | None:
    """(lat, lon, how): the pair read as degrees and decimal minutes (as given, then swapped; Maryland's
    longitudes are west) when that lies inside the county box."""
    for how, x, y, xs, ys in (("as given", a, b, lat_s, lon_s), ("swapped", b, a, lon_s, lat_s)):
        if decimals(xs) < 3 or decimals(ys) < 3:
            continue
        la, lo = dmm_degrees(x), dmm_degrees(y)
        if la is not None and lo is not None and in_box(box, la, -lo):
            return round(la, 5), round(-lo, 5), how
    return None


def coords(lat_s: str, lon_s: str, county: str | None = None) -> tuple[float | None, float | None, str]:
    """(lat, lon, note): the pair as given, swapped, with the longitude's minus sign added, or both;
    the first that lies in Maryland is used. With the row's county (COUNTY_BBOX), a result outside that
    county is replaced by the pair read as degrees and decimal minutes when that lies inside it, and is
    otherwise kept with a note that it lies outside the county."""
    a, na = coord_num(lat_s)
    b, nb = coord_num(lon_s)
    notes = [n for n in (na, nb) if n]
    if a is None and b is None:
        return None, None, "; ".join(notes) or "no coordinates"
    if a is None or b is None:
        return None, None, "; ".join(notes + ["only one coordinate readable: not used"])
    readings = (("as given", a, b), ("latitude and longitude swapped", b, a),
                ("longitude's minus sign added", a, -b), ("swapped and the longitude's minus sign added", b, -a))
    found = None
    for how, lat, lon in readings:
        if md_waters.in_md(lon, lat):
            found = (lat, lon, "; ".join(notes + [how]))
            break
    box = COUNTY_BBOX.get(md_waters.norm_county(county)) if county else None
    if box and not (found and in_box(box, found[0], found[1])):
        # the degrees-and-minutes repair applies only when the pair as decimal degrees (the one reading of it in
        # Maryland, if any) is outside the row's county and the repaired point is inside it (review 2026-11-03 P2-4)
        alt = dmm_pair(lat_s, lon_s, a, b, box)
        if alt:
            la, lo, how = alt
            where = (f"({found[0]}, {found[1]}) as decimal degrees is outside {clean(county)} County"
                     if found else f"({a}, {b}) is not in Maryland as decimal degrees")
            return la, lo, "; ".join(notes + [where, f"{how}, read as degrees and decimal minutes"])
        if found:           # otherwise the point stays as given, and the record says it is outside its county
            return found[0], found[1], "; ".join([found[2], f"outside {clean(county)} County (its Census box); kept as "
                                                  "given: no reading as degrees and decimal minutes lies in the county"])
    if found:
        return found
    return None, None, "; ".join(notes + [f"({a}, {b}) is not in Maryland in any order: not used"])


def metres(lat1, lon1, lat2, lon2) -> float:
    my = 111_320.0
    mx = my * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * my, (lon1 - lon2) * mx)


def _allowlist() -> set[str]:
    d = read_json(DATA_DIR / "name-allowlist.json", {}) or {}
    return {" ".join(re.sub(r"[^a-z0-9]+", " ", str(x).lower()).split()) for x in d.get("names", [])}


def scrub_people(text: str, allow: set[str] | None = None) -> str:
    """Names after an honorific in free text -> [name removed] (allowlisted phrases such as "Mr. Rooter" stay)."""
    if not text:
        return text
    allow = _allowlist() if allow is None else allow

    def rep(m):
        return m.group(0) if " ".join(re.sub(r"[^a-z0-9]+", " ", m.group(0).lower()).split()) in allow else redact.REDACTED
    return HONORIFIC.sub(rep, text)


def scrub_row(row: dict, allow: set[str]) -> dict:
    out = dict(row)
    for k in FREE_TEXT_FIELDS:
        if out.get(k):
            out[k] = scrub_people(out[k], allow)
    return out


def norm_owner(s: str | None) -> str:
    t = clean(s).lower().replace("&", " and ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\bsaint\b", "st", " ".join(t.split()))


# ---------------------------------------------------------------- operators

def load_dischargers(path: Path = RESEARCH_DISCHARGERS) -> tuple[dict, dict]:
    """(permit or MDE collection-system id -> research id (only ids that name one row), research id -> name)."""
    rows = read_json(path, []) or []
    by_permit: dict[str, set[str]] = defaultdict(set)
    names = {}
    for d in rows:
        names[d["id"]] = d.get("name")
        for m in PERMIT_TOKEN.finditer(str(d.get("npdes_permit") or "")):
            if m.group(0) not in NOT_AN_OPERATOR:
                by_permit[m.group(0)].add(d["id"])
    return {p: next(iter(ids)) for p, ids in by_permit.items() if len(ids) == 1}, names


def operator_of(row: dict, permits: dict) -> tuple[str | None, str]:
    npdes = clean(row.get("npdes_no")).upper()
    owner = clean(row.get("owner_name"))
    by_owner = OWNER_IDS.get(norm_owner(owner))
    by_permit = permits.get(npdes) if npdes and npdes not in NOT_AN_OPERATOR else None
    if by_permit and by_owner and by_permit != by_owner:
        did, basis = by_owner, f"owner name (permit/system id {npdes} is listed under {by_permit}; the owner filed the report)"
    elif by_permit:
        did, basis = by_permit, f"permit/system id {npdes}"
    elif by_owner:
        did, basis = by_owner, "owner name"
    elif owner:
        did, basis = f"md-{slug(owner)}", "built from the owner name (no research row)"
    else:
        return None, "no owner"
    if did in ID_OVERRIDES:
        basis += f"; {did} is the operator {ID_OVERRIDES[did]} (decision 5)"
        did = ID_OVERRIDES[did]
    return did, basis


# ---------------------------------------------------------------- records

def water_of(text: str, county: str | None, lat, lon) -> tuple[list[str], str, dict]:
    t = clean(text)
    if not t or NO_WATER.match(t):
        return [], "none", {"why_none": f"receiving water given as {t!r}: no surface water named (decision 3)"}
    if NOT_REACHED.search(t):
        return [], "none", {"why_none": "the text says the overflow did not reach a water"}
    point = (lon, lat) if lat is not None and lon is not None else None
    slugs, notes = md_waters.match_waters(t, None, point, county or None)
    note = {}
    if notes:
        note["name_notes"] = notes
    if slugs:
        note["via"] = "receiving water name within Maryland" + (" (checked against the point)" if point else "") + \
                      (f" and county {county}" if county else "")
    else:
        note["why_none"] = "no Maryland water record matched the name"
    return slugs, ("name" if slugs else "none"), note


def base_key(row: dict) -> str:
    npdes = clean(row.get("npdes_no")).upper() or "none"
    st, prec = start_of(row)
    when = st.strftime("%Y%m%d") + ("T" + st.strftime("%H%M") if prec == "minute" else "") if st else "nodate"
    return "-".join([slug(npdes) or "none", when, slug(norm_addr(row.get("overflow_address"))) or "no-address"])


def row_sha(row: dict) -> str:
    return hashlib.sha1(json.dumps({k: v for k, v in row.items() if k != "id"}, sort_keys=True).encode()).hexdigest()


def volume_of(row: dict) -> int | None:
    v, _ = parse_volume_gal(clean(row.get("discharge_volume")) or None)
    return v


def to_record(row: dict, rid: str, ctx: dict) -> dict:
    base = dict(source_id=SOURCE_ID, source_record_id=rid, fetched_at=ctx["fetched_at"], source_url=PAGE_URL,
                source_updated_at=ctx["source_updated_at"])
    raw = {"row": dict(row)}
    try:
        return build_record(row, base, raw, ctx)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=clean(row.get("owner_name")) or None,
                     parse_error=f"{type(e).__name__}: {e}")


def build_record(row: dict, base: dict, raw: dict, ctx: dict) -> dict:
    problems = []
    label = clean(row.get("overflow_type"))
    etype = TYPES.get(label.lower())
    if etype is None:
        etype = "unknown"
        problems.append(f"unknown overflow_type {label!r}")
    if label.lower() == "unauthorized discharge":
        raw["_source_type"] = label
    start, prec = start_of(row)
    if start is None:
        problems.append(f"unreadable start_date {row.get('start_date')!r}")
    dur = duration_of(row)
    ended_at = None
    if start is not None and dur is not None:
        end, basis = end_after(start, dur, prec)
        ended_at = end.isoformat()
        raw["_ended_at_basis"] = f"start + duration_day/hour/minute ({basis})"
        status = "ended"
    else:
        status = "unknown"
    county = clean(row.get("county")) or None
    lat, lon, cnote = coords(row.get("overflow_latitude"), row.get("overflow_longitude"), county)
    raw["_coords"] = cnote
    water = clean(row.get("receiving_water")) or None
    slugs, match, wnote = water_of(water or "", county, lat, lon)
    raw["_water"] = wnote
    did, dbasis = operator_of(row, ctx["permits"])
    raw["_discharger_basis"] = dbasis
    npdes = clean(row.get("npdes_no")).upper()
    vtext = clean(row.get("discharge_volume")) or None
    gal, est = parse_volume_gal(vtext)
    owner = clean(row.get("owner_name")) or None
    return event(
        **base, event_type=etype, status=status,
        discharger_id=did, discharger_name=owner, npdes_permit=npdes if REAL_PERMIT.match(npdes) else None,
        outfall_id=None, outfall_name=clean(row.get("overflow_address")) or None,
        waterbody_text=water, water_slugs=slugs, water_match=match,
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=None,
        started_at=start.isoformat() if start else None, ended_at=ended_at, time_precision=prec,
        reported_at=None, published_at=None,
        material=None, volume_gal=gal, volume_text=(vtext + " gallons") if vtext and gal is not None and vtext.replace(".", "").isdigit() else vtext,
        estimate_flag=est, authority=owner,
        advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def assign_ids(rows: list[dict]) -> list[tuple[str, dict, str | None]]:
    """[(source_record_id, row, duplicate-of source_record_id)]: rows sharing a composite key get "~2",
    "~3" in order of volume (then content), and the copies point at the first."""
    groups = defaultdict(list)
    for r in rows:
        groups[base_key(r)].append(r)
    out = []
    for key, rs in groups.items():
        rs = sorted(rs, key=lambda r: (-(volume_of(r) or -1), row_sha(r)))
        for i, r in enumerate(rs):
            out.append((key if i == 0 else f"{key}~{i + 1}", r, key if i else None))
    return out


def mark_duplicates(records: list[dict], rows_by_id: dict) -> Counter:
    """duplicate_of within the table: same key (assign_ids), same start minute and address under another
    key (lower volume -> highest), and rows MDE marks "(DUPLICATE)"."""
    n = Counter()
    by_id = {r["event_id"]: r for r in records}
    # same start minute and address, different keys
    groups = defaultdict(list)
    for r in records:
        row = rows_by_id[r["event_id"]]
        addr = norm_addr(row.get("overflow_address"), for_match=True)
        if r.get("duplicate_of") or not addr or r.get("time_precision") != "minute" or "duplicate" in clean(row.get("overflow_address")).lower():
            continue
        groups[(r["started_at"], addr)].append(r)
    for (_, addr), rs in groups.items():
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: (-(r.get("volume_gal") or -1), r["event_id"]))
        keep = rs[0]
        for r in rs[1:]:
            r["duplicate_of"] = keep["event_id"]
            r["raw"]["_duplicate_basis"] = (f"same start ({r['started_at']}) and address as {keep['event_id']} "
                                            f"(owner {keep.get('discharger_name')!r}, {keep.get('volume_gal')} gal); "
                                            f"the lower-volume row is the copy")
            n["same_start_and_address"] += 1
    # rows MDE marks "(DUPLICATE)"
    plain = defaultdict(list)
    for r in records:
        row = rows_by_id[r["event_id"]]
        if r.get("duplicate_of") or "duplicate" in (clean(row.get("overflow_address")) + clean(row.get("receiving_water"))).lower():
            continue
        plain[norm_addr(row.get("overflow_address"), for_match=True)].append(r)
    for r in records:
        row = rows_by_id[r["event_id"]]
        marked = "duplicate" in clean(row.get("overflow_address")).lower() or \
                 clean(row.get("receiving_water")).lower().startswith("duplicate") or \
                 clean(row.get("overflow_cause")).lower().startswith("duplicate")
        if not marked or r.get("duplicate_of"):
            continue
        r["raw"]["_source_marks_duplicate"] = True
        addr = norm_addr(row.get("overflow_address"), for_match=True)
        t = datetime.fromisoformat(r["started_at"]) if r.get("started_at") else None
        best = None
        for c in plain.get(addr, []):
            if c is r or not c.get("started_at") or t is None:
                continue
            gap = abs((datetime.fromisoformat(c["started_at"]) - t).total_seconds())
            if gap > 3 * 86400:
                continue
            score = (c.get("discharger_id") != r.get("discharger_id"), gap)
            if best is None or score < best[0]:
                best = (score, c)
        if best:
            r["duplicate_of"] = best[1]["event_id"]
            r["raw"]["_duplicate_basis"] = f"MDE marks this row a duplicate; original {best[1]['event_id']} (same address)"
            n["marked_by_mde"] += 1
        else:
            n["marked_by_mde_original_not_found"] += 1
    return n


def match_baltimore(records: list[dict], rows_by_id: dict, dpw: list[dict]) -> int:
    """An MDE row of the same operator that starts the same local day at the same address, or within
    200 m, is duplicate_of the Baltimore DPW record (the closest start wins)."""
    by_day = defaultdict(list)
    for d in dpw:
        if d.get("event_type") != "sso" or not d.get("started_at") or not d.get("discharger_id") or d.get("duplicate_of"):
            continue
        by_day[datetime.fromisoformat(d["started_at"]).astimezone(TZ).date()].append(d)
    n = 0
    for r in records:
        if r.get("duplicate_of") or not r.get("started_at") or not r.get("discharger_id"):
            continue
        t = datetime.fromisoformat(r["started_at"]).astimezone(TZ)
        addr = norm_addr(rows_by_id[r["event_id"]].get("overflow_address"), for_match=True)
        best = None
        for d in by_day.get(t.date(), []):
            if d["discharger_id"] != r["discharger_id"]:
                continue
            same_addr = bool(addr) and addr == norm_addr(d.get("outfall_name"), for_match=True)
            dist = None
            if r.get("lat") is not None and d.get("lat") is not None:
                dist = metres(r["lat"], r["lon"], d["lat"], d["lon"])
            if not same_addr and (dist is None or dist > NEAR_M):
                continue
            gap = abs((datetime.fromisoformat(d["started_at"]) - t).total_seconds())
            if best is None or gap < best[0]:
                best = (gap, d, same_addr, dist)
        if best:
            gap, d, same_addr, dist = best
            how = "same address" if same_addr else f"{round(dist)} m apart"
            r["duplicate_of"] = d["event_id"]
            r["raw"]["_duplicate_basis"] = (f"Baltimore DPW SSO map record {d['event_id']}: same operator, same day, {how} "
                                            f"(DPW {d.get('volume_gal')} gal, start {d['started_at']}; this row "
                                            f"{r.get('volume_gal')} gal); the City's record carries the end time and point")
            n += 1
    return n


def carry_history(records: list[dict], prev: dict, fetched_at: str, allow: set[str] | None = None) -> Counter:
    """First sighting and every change of a row between runs (the table is edited in place)."""
    n = Counter()
    for r in records:
        p = prev.get(r["event_id"])
        if not p:
            r["raw"]["_first_seen_at"] = fetched_at
            n["new"] += 1
            continue
        praw = p.get("raw") or {}
        r["raw"]["_first_seen_at"] = praw.get("_first_seen_at") or p.get("fetched_at")
        revs = list(praw.get("_revisions") or [])
        old, new = scrub_row(praw.get("row") or {}, allow if allow is not None else _allowlist()), r["raw"]["row"]
        changed = {k: old.get(k) for k in set(old) | set(new) if k != "id" and clean(old.get(k)) != clean(new.get(k))}
        if changed:
            revs.append({"replaced_at": fetched_at, "seen_until": p.get("fetched_at"),
                         "source_updated_at_before": p.get("source_updated_at"), "old_values": changed})
            n["revised"] += 1
        if revs:
            r["raw"]["_revisions"] = revs
    return n


def keep_vanished(records: list[dict], prev: dict, rows_by_id: dict, fetched_at: str) -> Counter:
    """Records of earlier runs whose key is gone from the table are kept; when a current row has the
    same npdes_no and start (or the same npdes_no, day and address) they are duplicate_of it."""
    n = Counter()
    now_ids = {r["event_id"] for r in records}
    by_start = defaultdict(list)
    by_day_addr = defaultdict(list)
    for r in records:
        row = rows_by_id[r["event_id"]]
        npdes = clean(row.get("npdes_no")).upper()
        by_start[(npdes, r.get("started_at"))].append(r)
        if r.get("started_at"):
            by_day_addr[(npdes, r["started_at"][:10], norm_addr(row.get("overflow_address"), for_match=True))].append(r)
    for eid, p in prev.items():
        if eid in now_ids:
            continue
        p = dict(p)
        p["raw"] = dict(p.get("raw") or {})
        p["raw"]["_missing_from_source_since"] = p["raw"].get("_missing_from_source_since") or fetched_at
        row = p["raw"].get("row") or {}
        npdes = clean(row.get("npdes_no")).upper()
        succ = by_start.get((npdes, p.get("started_at"))) or \
            (by_day_addr.get((npdes, (p.get("started_at") or "")[:10], norm_addr(row.get("overflow_address"), for_match=True)))
             if p.get("started_at") else None)
        if succ and not p.get("duplicate_of"):
            p["duplicate_of"] = succ[0]["event_id"]
            p["raw"]["_duplicate_basis"] = f"gone from the table; {succ[0]['event_id']} looks like its corrected row"
            n["superseded_by_corrected_row"] += 1
        else:
            n["kept_missing"] += 1
        records.append(p)
    return n


def build(rows: list[dict], meta_info: dict, fetched_at: str, prev_records: list[dict], dpw: list[dict],
          permits: dict) -> tuple[list[dict], dict]:
    upd = meta_info.get("rowsUpdatedAt")
    source_updated_at = datetime.fromtimestamp(int(upd), UTC).astimezone(TZ).isoformat() if upd else None
    ctx = {"fetched_at": fetched_at, "source_updated_at": source_updated_at, "permits": permits}
    allow = _allowlist()
    rows = [scrub_row(r, allow) for r in rows]
    records = []
    for rid, row, dup_of in assign_ids(rows):
        rec = to_record(row, rid, ctx)
        if dup_of:
            rec["duplicate_of"] = f"{SOURCE_ID}:{dup_of}"
            rec["raw"]["_duplicate_basis"] = "the table repeats this row (same npdes_no, start and address)"
        records.append(rec)
    # private individuals' names in the operators' free text never reach the record (the export's pass)
    records = redact.redact_events(records)
    rows_by_id = {r["event_id"]: r["raw"].get("row") or {} for r in records}
    dups = Counter({"repeated_rows": sum(1 for r in records if r.get("duplicate_of"))})
    dups.update(mark_duplicates(records, rows_by_id))
    dups["baltimore_dpw"] = match_baltimore(records, rows_by_id, dpw)
    prev = {r["event_id"]: r for r in prev_records}
    hist = carry_history(records, prev, fetched_at, allow)
    rows_by_id.update({eid: (p.get("raw") or {}).get("row") or {} for eid, p in prev.items() if eid not in rows_by_id})
    gone = keep_vanished(records, prev, rows_by_id, fetched_at)
    records = redact.redact_events(records)      # again over everything kept (revisions, vanished rows)
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    current = [r for r in records if not r["raw"].get("_missing_from_source_since")]
    stats = {
        "rows": len(rows), "records_written": len(records), "duplicates": dict(dups), "history": dict(hist),
        "vanished": dict(gone), "by_type": dict(Counter(r["event_type"] for r in current)),
        "by_source_type": dict(Counter(clean((r["raw"].get("row") or {}).get("overflow_type")) for r in current)),
        "water_match": dict(Counter(r["water_match"] for r in current)),
        "with_coordinates": sum(1 for r in current if r.get("lat") is not None),
        "coordinate_repairs": dict(Counter(r["raw"].get("_coords", "").split("; ")[-1] for r in current
                                           if r.get("lat") is not None)),
        "source_updated_at": source_updated_at,
    }
    return records, stats


# ---------------------------------------------------------------- fetch and main

def fetch(sess: requests.Session) -> tuple[str, dict, bytes, bytes]:
    r = sess.get(CSV_URL, timeout=(15, 180))
    r.raise_for_status()
    if "csv" not in (r.headers.get("content-type") or "") and not r.text.lstrip("﻿").upper().startswith("OVERFLOW_TYPE"):
        raise ValueError(f"not a CSV ({r.headers.get('content-type')}, {len(r.content)} bytes)")
    m = sess.get(META_URL, timeout=(15, 60))
    m.raise_for_status()
    return r.content.decode("utf-8-sig"), m.json(), r.content, m.content


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this CSV instead of downloading")
    ap.add_argument("--meta", help="the dataset metadata JSON for --file")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    try:
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8-sig")
            meta_info = json.loads(Path(args.meta).read_text()) if args.meta else {}
            csv_bytes = meta_bytes = None
        else:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            text, meta_info, csv_bytes, meta_bytes = fetch(sess)
        rows = read_rows(text)
        if not rows or "npdes_no" not in rows[0]:
            raise ValueError("the CSV has no rows or no NPDES_NO column")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1

    state = read_json(STATE_FILE, {}) or {}
    raw_path = state.get("raw_path")
    if csv_bytes is not None:
        sha = hashlib.sha256(csv_bytes).hexdigest()
        if sha != state.get("sha256") or meta_info.get("rowsUpdatedAt") != state.get("rowsUpdatedAt"):
            p = save_raw(SOURCE_ID, csv_bytes, "csv")
            (p.with_suffix(".meta.json")).write_bytes(meta_bytes)
            raw_path = str(p.relative_to(ROOT))
            state = {"sha256": sha, "raw_path": raw_path, "saved_at": fetched_at,
                     "rowsUpdatedAt": meta_info.get("rowsUpdatedAt"),
                     "versions_saved": int(state.get("versions_saved") or 0) + 1}
        state["fetched_at"] = fetched_at
        write_json(STATE_FILE, state)

    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    dpw = (read_json(BALTIMORE_EVENTS, {}) or {}).get("records", [])
    permits, _ = load_dischargers()
    records, stats = build(rows, meta_info, fetched_at, prev, dpw, permits)
    meta = {**stats, "csv_url": CSV_URL, "raw_path": raw_path, "dataset": DATASET,
            "rows_updated_at_epoch": meta_info.get("rowsUpdatedAt"),
            "credit": "Maryland Department of the Environment, Reported Sewer Overflows (New for 2023), opendata.maryland.gov",
            "license": "Public Domain (Socrata metadata)",
            "caveat": "Reported to MDE by the owner or operator; whether the public was notified is not recorded in this table.",
            "registry_ids": ["md-mde-sewer-overflows-2023"]}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['rows']} rows -> {stats['records_written']} records; types {stats['by_type']}; "
          f"duplicates {stats['duplicates']}; water match {stats['water_match']}; "
          f"{stats['with_coordinates']} with coordinates -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
