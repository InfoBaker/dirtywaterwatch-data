"""Water records from NHDPlus V2.1 for every receiving water that has none (data/waters-nhd.json).

    python -m ingest.waters_from_nhd [--offline] [--refresh] [--limit N] [--targets-only] [--no-osm]
                                     [--osm-max N] [--osm-only] [--rebuild] [--budget-s S] [--max-requests N]
    python -m ingest.waters_from_nhd --state XX [--state YY ...] [--budget-s S] [--max-requests N] [--targets-only]
    python -m ingest.waters_from_nhd --state XX [--state YY ...] --tidy     (offline; tidy_main)
    python -m ingest.waters_from_nhd --names research/<st>/receiving-waters-missing.json --state XX [--add-places]
                                     [--budget-s S] [--max-requests N] [--targets-only]

A state build (--state, 2026-11-04; docs/national-waters.md in the site repository): a state's records are built
before it goes live, from data/receiving-waters-national.json (scripts/gen_receiving_waters.py: one row per receiving
water per state, with its operators, outfalls, up to three points, EPA's NHD reach codes and NHDPlus ids, and
define_by) instead of the outfall files and reports below. Targets are every row without a water record on file (a
'record' row whose slug no water file on disk holds, an openboatlaunch slug whose extract is not here, is built as a
reach or point row and says so in its notes) and every unnamed outfall, in the order reach, point, name, unnamed.
EPA's receiving-water text is read by national_parts (path notation 'X CRK/Y CRK/Z RIVER' names X; Florida's class and
WBID tags, river-basin tails, counties, roads and land-application systems are not waters and become the row's
stated reason in `skipped`). A reach row takes the NHDPlus V2.1 feature of each GNIS id on its reach codes and NHDPlus
ids that carries the row's name, every flowline of that id in the state (or the waterbody polygon for a lake, pond,
reservoir or bay name), with no snapping (resolve_reach; the codes and ids are asked in batches, reach_index). When
EPA's reaches carry another name (a plant indexed by its fence to the stream there: most of North Carolina's rows),
the name pass runs next (the GNIS feature of that name nearest the operators' towns, no NLDI request), then the
points. A point row snaps its points (NLDI), a name row takes the name pass, then the other places of a name, the OSM
fallback and the state's hand records as below. An unnamed outfall takes the flowline of its own NHDPlus id or reach
code, else the flowline NLDI snaps its point to: a named flowline gives that water's record, an unnamed one a record of
that flowline alone named for the first named water downstream ('Unnamed tributary to X', resolve_unnamed, NLDI
navigation). Records for states not yet live go into the same data/waters-nhd.json (the export and every public output
keep to rules.json live_states); the write merges into the file: every other state's records, target rows, skipped
texts and problems stay, and the run's statistics go under stats.state_builds.<ST>. Target rows of a state build
carry define_by (the national list's), defined_by (how the record was found), permits, reach_slugs ({EPA id: slug},
read by ingest.outfall_waters --state) and, for an unnamed outfall, outfall_ref. Then
`python -m ingest.outfall_waters --state XX` ties every outfall row of the state to its record or a reason.

--tidy (2026-11-04, nothing fetched): once openboatlaunch's extract for a state is on file, the state build's NHD records
of the same waters are dropped for openboatlaunch's (the public record) and the records that only shared an
openboatlaunch slug take a town slug (resolve_existing_duplicates; with no out/water outline on this machine the
record's bounding box decides, same_water_by_box); target rows' reasons are put in public voice, the tool's detail kept
in reason_detail (public_reasons); 'Unnamed stream' records are named for their town (name_unnamed_streams).

Report names (--names FILE --state XX, 2026-11-04): the receiving-water names a state's reports give that the national
list does not hold (research/<st>/receiving-waters-missing.json) as targets, one per water name, most reports first,
with the points and towns the file gives (--add-places, nothing fetched, first writes them into the file from the
state's reports in data/build/events: the points the reports carry and their town fields, and the towns of the
operators they name). A text that names no public water (a storm-sewer system or MS4, a catch basin or treatment
works, private property, the open sea, a street, an unnamed or unknown stream, a river basin, a county) gets that
reason and never a record (report_name_parts); a tributary of a named water gives the named water. A name the status
resolver already places on a record maps to it, nothing built. The others take the name pass (report_name_choices):
the NHDPlus V2.1 features of that GNIS name in the state (asked thirty spellings to a query, prefetch_names), the one
nearest each place the reports give (each cluster of points within 2 km; each town within 3 km when no point finds the
name), so every place
of a name gets its own record; with no place, a name found once in the state. A feature already a record in this file
maps to it; a feature openboatlaunch already holds maps to that record (new_record: the outline, else the bounding box
and towns of the tidy, same_water_by_box). A name NHDPlus V2.1 does not carry, or carries only away from the reports'
places, then takes the NHD high-resolution flowlines of the name near the points or towns, then the OSM fallback when
Overpass answers. Rows carry from: "reports" and their report count, are merged among the
state's report rows only (the state build's rows stay exactly), and the run's statistics go under
stats.state_builds.<ST>.report_names. FILE is rewritten to the names still without a record, each with its reason
(rows), the names a record now holds in `resolved` (with the slugs), so the next run resumes with what is left.

Budgets: --max-requests (network requests; cached answers are free) and --budget-s (seconds) stop the run before a
request, never inside one (BudgetExhausted); the targets not reached say so, what was built is written (merged, never
dropping a record), and the next run resumes from the cached responses. NLDI requests keep to USGS's limit of 3,600 an
hour per address across runs (data/raw/nhd-waters/nldi-requests.json): a request over it waits, or stops the run when
the wait passes --budget-s. The national list puts four in five named waters on EPA reach codes, so a state needs NLDI
only for its point rows and unnamed outfalls.

Targets: every outfall in data/outfalls-ne.json, data/outfalls-mid-atlantic.json and the state layers
(data/build/ma-cso-outfalls.json, me-cso-outfalls.json, nj-cso-outfalls.json) whose water_slug is
empty or whose receiving-water name has no record in the same state (status.Resolver: the name, an
alias or a stem, kept by the placement guard), plus every event in data/build/events/*.json that the
status resolver leaves unplaced and that has a waterbody_text (fixtures and restricted files left
out). Texts are split into water names ("Teall Brook & Ley Creek", "Delaware River/Newton Creek"),
trimmed ("Tributary of Longhouse creek", "Penhorn Creek UNT", "Foster Brook to Lake Erie") and grouped
by state and name; names that are not waters ("none", "ground", "catch basin", street addresses, the
open ocean) are listed with that reason. Beach, HAB and other point advisories name a site, not a
water: their target is the NHD lake or pond at the site's point.

Each target with coordinates (up to three distinct points, the most reported first):
  1. USGS NLDI snaps the point to an NHDPlus COMID: comid/position (the flowline of the catchment
     holding the point; the default) or hydrolocation (the nearest flowline, with --hydrolocation or
     when cached; in November 2026 it took about 6 s a call and answered 502 on most calls).
  2. EPA NHDPlus V2.1 MapServer (watersgeo.epa.gov .../NHDPlus/NHDPlus/MapServer), layer 2 network
     flowlines within 2 km of the point: the snapped flowline's gnis_name/gnis_id is taken when it
     matches the target's name; otherwise the nearest flowline whose GNIS name matches; layer 4
     waterbodies (lakes, ponds, reservoirs, estuaries) the same way, preferred when the name is a
     lake, pond, reservoir or harbour word or the snapped flowline runs through that waterbody.
  3. A river: every layer 2 flowline in the state's box with that gnis_id (a MultiLineString);
     a lake or pond: the layer 4 polygons with that gnis_id (or the one COMID when unnamed).
Then the other places of a name that NHDPlus named at one of those points: every cluster of the target's points that
none of its records reaches within 2 km is resolved the same way (Run.place_pass, outfall places first, within
--place-budget seconds, 120 by default; a second West Run or Mill Creek in the state gets its own record), and the
places that found nothing are listed in the target row's places_failed. A feature keeps the slug it had in the file,
and a record the run does not rebuild keeps its slug (assign_slugs), since the outfall registries store these slugs.
Targets with only a name: layer 2 and layer 4 features of that GNIS name in the state's box, the one
lying nearest the towns of the outfalls and events (Census 2020 county subdivisions, TIGERweb); a
name found once in the state is taken without towns.
Geometry is cut to the state (Census cartographic outlines, as waters_extra.py does), merged and
simplified to about 10 m. Towns are the county subdivisions the geometry crosses (Census 2020).

A target whose NHD water is already a record (same name in the state, geometry within 300 m) maps to
that slug; a record is built only for the part that record does not cover (1 km or more, within 2 km
of the target's points). Targets NHDPlus cannot name (tidal straits and harbours drawn as unnamed
areas: Arthur Kill, Upper New York Bay) fall back to OpenStreetMap through ingest/waters_extra.py's
Overpass query and builder (a box around the points; cached in data/raw/osm-waters/); those rows say
source "osm" and fallback_for "nhd". At most --osm-max (600) such queries a run, most reports first;
generic descriptions ("No Name Small Stream") are not asked. --osm-only keeps the last full run's
records and asks OSM only for the targets it left unmapped because NHDPlus has no feature of that name
and OSM was not yet asked (written once, at the end).

Hand records (HAND): receiving waters the automatic passes cannot reach, each from a cited public
geometry (an NHDPlus GNIS id with its reach codes; USGS NHD high-resolution flowlines, service "hr", by GNIS
id or by permanent identifier inside a box, from layer 6 of hydro.nationalmap.gov's NHD MapServer, cached in
data/raw/nhd-waters/nhd-hr/; or OSM way ids fetched by id and cached in data/raw/nhd-waters/osm-hand/),
rebuilt in every run and marked hand: true. The medium-resolution NHDPlus V2.1 network leaves out small
streams and culverted stretches (2026-11-03: Scajaquada Creek has 4.9 km of its 24 km there; Penhorn Creek and
Webster Brook none), which the high-resolution flowlines carry. A spec with supersede: true replaces the
record the automatic pass built for the same name (its targets go to the hand record, which takes the plain slug).

Slugs follow openboatlaunch: <name>-<st>; <name>-<town>-<st> when the name is already a record in
that state or another NHD record of the state has it (the record with the most targets keeps the
plain slug); never an existing slug. Kind from the NHD feature: river, stream or canal for
flowlines (River in the name or stream order 5+: river; canal/ditch fcode or name: canal), lake,
pond or reservoir for waterbodies, bay for estuaries, harbours, coves and inlets (status.py treats
bays as wide waters, never filled whole).

Every response (NLDI, MapServer, TIGERweb) is cached in data/raw/nhd-waters/<kind>/<hash>.json and
reused unless --refresh; requests are 0.5 s apart with backoff on 429 and 5xx. Rows have the shape of
data/waters-extra.json plus gnis_id, comids, nhd_fcodes and targets; status.py and the export read it
like waters-extra (extra: true).

Writes never lose records (2026-11-03: a cut-off run's checkpoint had left 780 records over the 862 of the
committed file). The output is written every 25 records (partial: true) and at the end, each time merged
into the records of the file already on disk by slug: a record this run built takes the new version, one it
did not visit is kept as is, and rows are sorted by slug so git diffs stay readable. A run that ends with
fewer records than the file holds still merges (a note goes in stats.write.warning; the OSM time budget
makes this normal) unless it was started with --rebuild, which replaces the file with this run's records and says so
in the summary (and in stats.write); checkpoints of a --rebuild run still merge, so a cut-off one loses
nothing. --limit runs (partial) and --osm-only runs merge as well. The merge is by feature as well as by slug
(merge_waters, water_identity: GNIS id, else COMIDs, else OSM ways): a feature written under one slug at a
checkpoint and another later (its town list grew) is one record, the newer slug, with the older one in
`slug_aliases` (status.load_waters and the placement follow it).
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import re
import struct
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import requests
import shapely
from shapely.geometry import LinearRing, MultiPolygon, Point, Polygon, box as sbox, mapping, shape
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

from build import status as S
from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, RAW_DIR, ROOT, now_iso, read_json, write_json
from ingest import waters_extra as WX

NLDI_HYDROLOCATION = "https://api.water.usgs.gov/nldi/linked-data/hydrolocation"
NLDI_POSITION = "https://api.water.usgs.gov/nldi/linked-data/comid/position"   # the catchment's flowline
EPA_NHD = "https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer"
# USGS National Hydrography Dataset, high resolution (The National Map): layer 6 "Flowline - Large Scale". It names
# small streams and culverted stretches the medium-resolution NHDPlus V2.1 network above leaves out (hand records, service "hr")
NHD_HR = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
HR_FLOWLINES = 6
TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer"
TIGER_COUSUB = f"{TIGER}/22/query"             # Census 2020 county subdivisions (towns, townships, cities)
TIGER_PLACES = [f"{TIGER}/25/query", f"{TIGER}/26/query"]   # incorporated places, census designated places
# where county subdivisions are election or magisterial districts ("10, Lonaconing", "C-01"), towns are
# the Census places instead
PLACE_STATES = {"MD", "VA", "DC", "DE", "WV", "NC", "KY", "TN"}
# states whose county subdivisions are Census county divisions (statistical areas named for a county seat, not towns):
# towns are the Census places there too (a state build, --state, 2026-11-04; none of these is live)
PLACE_STATES |= {"AL", "AZ", "CA", "CO", "FL", "GA", "HI", "ID", "MT", "NV", "NM", "OK", "OR", "SC", "TX", "UT", "WA", "WY",
                 "PR", "AK"}
CACHE_DIR = RAW_DIR / "nhd-waters"
OUT = DATA_DIR / "waters-nhd.json"
PAUSE_S = 0.5
CHECKPOINT_EVERY = 25
NEAR_M = 2000              # flowlines and waterbodies searched around a point (status.NAME_MATCH_M)
SITE_M = 300               # a beach/HAB site's lake or pond: containing or within this
SAME_WATER_M = 300         # an NHD water this close to a same-named record is that record
REMAINDER_MIN_KM = 1.0
MAX_POINTS = 3
SIMPLIFY_M = 10.0
FIPS = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
        "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
        "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
        "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
        "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
        "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "AS": "60", "GU": "66", "MP": "69",
        "PR": "72", "VI": "78"}
FL_FIELDS = "comid,gnis_id,gnis_name,reachcode,fcode,ftype,wbareacomid,wbarea_ftype,streamorder,lengthkm"
WB_FIELDS = "comid,gnis_id,gnis_name,reachcode,fcode,ftype,areasqkm"
LAKE_FTYPES = {390: "lake", 436: "reservoir", 493: "bay", 466: "pond"}

# states whose receiving waters another builder makes from NHD: no targets here
OTHER_BUILDER = {"DC": "DC's waters come from ingest/dc_waters.py (data/waters-dc.json)"}

OUTFALL_FILES = [
    ("outfalls-ne", DATA_DIR / "outfalls-ne.json", None),
    ("outfalls-mid-atlantic", DATA_DIR / "outfalls-mid-atlantic.json", None),
    ("ma-cso-outfalls", BUILD_DIR / "ma-cso-outfalls.json", "MA"),
    ("me-cso-outfalls", BUILD_DIR / "me-cso-outfalls.json", "ME"),
    ("nj-cso-outfalls", BUILD_DIR / "nj-cso-outfalls.json", "NJ"),
]

# ---------------------------------------------------------------- names

NUMS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight",
        "9": "nine", "10": "ten", "11": "eleven", "12": "twelve", "13": "thirteen", "14": "fourteen",
        "15": "fifteen", "16": "sixteen", "17": "seventeen", "18": "eighteen", "19": "nineteen", "20": "twenty"}
WORD_FIX = {"r": "river", "riv": "river", "rvr": "river", "bk": "brook", "brk": "brook", "br": "branch",
            "cr": "creek", "ck": "creek", "crk": "creek", "pd": "pond", "lk": "lake", "res": "reservoir",
            "hbr": "harbor", "harbour": "harbor", "chan": "channel", "n": "north", "s": "south", "e": "east",
            "w": "west", "no": "north", "so": "south", "st": "saint", "ste": "sainte", "mt": "mount",
            "ft": "fort", "trib": "tributary", "strm": "stream", "pt": "point"}
KIND_WORDS = {"river", "brook", "creek", "stream", "kill", "run", "lake", "pond", "reservoir", "bay", "harbor",
              "cove", "inlet", "canal", "channel", "branch", "sound", "lagoon", "marsh", "swamp", "ditch",
              "outlet", "gut", "basin", "fork", "estuary", "narrows", "strait", "lakes", "ponds", "creeks",
              "brooks", "rivers", "falls", "spring", "springs", "millpond", "flowage", "bog", "slough",
              "kills"}            # 'Dutch Kills', 'English Kills' (tidal creeks in New York City; 2026-11-03)
LAKE_WORDS = {"lake", "lakes", "pond", "ponds", "reservoir", "millpond", "flowage", "bog"}
BAY_WORDS = {"bay", "harbor", "cove", "inlet", "basin", "sound", "lagoon", "estuary", "narrows", "strait"}
# a text with one of these words describes a place, not a water's name ("catch basin", "unnamed brook",
# "storm drain", "did not reach a waterbody"); single kind words ("Canal", "swamp") are not names either
NON_NAME = {"unknown", "unnamed", "nearby", "local", "storm", "stormwater", "drainage", "retention", "detention",
            "catch", "culvert", "culverts", "sewer", "sewers", "ground", "groundwater", "none", "na", "applicable",
            "did", "waterbody", "overland", "swale", "manhole", "manholes", "basement", "basements", "private",
            "drain", "drains", "pavement", "parking", "lawn", "yard", "soil", "other", "tbd", "unk"}
WETLAND = {"wetland", "wetlands"}
TRAILING_JUNK = {"tube", "culvert", "outfall", "pipe", "drain", "north", "south", "east", "west", "upper",
                 "lower", "low", "high", "side", "beach", "unt", "tributary", "conduit", "area", "shore",
                 "headwaters", "watershed", "mouth"}
SITE_WORDS = re.compile(r"\b(beach|beaches|camp|park|club|ymca|ywca|marina|association|assn|swim|swimming|"
                        r"resort|campground|recreation|rec|bathing|community|estates|village|landing|"
                        r"school|church|cottage|cottages|colony|day)\b", re.I)
ADDRESS = re.compile(r"^\d+[a-z]?\s+(?:[\w.'-]+\s+){0,4}(st|street|rd|road|ave|avenue|dr|drive|ln|lane|blvd|"
                     r"boulevard|way|ct|court|pl|place|hwy|highway|route|rte|pkwy|parkway|ter|terrace|cir|"
                     r"circle|sq|square|tpke|turnpike)\b", re.I)
QUALIFIERS = {"north", "south", "east", "west", "middle", "little", "upper", "lower", "branch", "fork", "of", "the"}
POINT_TYPES = S.POINT_ADVISORY_TYPES | {"shellfish_closure"}


def words(s: str) -> list[str]:
    s = str(s or "").lower().replace("'", "").replace("’", "")
    return [NUMS.get(t, WORD_FIX.get(t, t)) for t in re.findall(r"[a-z0-9]+", s)]


def compact(ws) -> str:
    return "".join(ws if isinstance(ws, list) else words(ws))


def slugify(s: str) -> str:
    return WX.slugify(s)


def town_key(t) -> str:
    t = S.norm_town(t)
    return re.sub(r"\s+(township|twp|borough|boro|village|city|town|plantation|gore|grant|cdp)$", "", t).strip()


def not_water(text: str) -> str | None:
    """Why a text is not a water's name (None when it may be one)."""
    t = str(text or "").strip()
    if not t:
        return "empty"
    if ADDRESS.search(t):
        return "a street address"
    if re.fullmatch(r"\W*[A-Za-z]{1,2}\W*", t):
        return "not a water name"           # 'N', 'A' (a yes/no column), 'UT' (an unnamed tributary)
    ws = words(t)
    if not ws or all(w.isdigit() for w in ws):
        return "not a water name"
    if "ocean" in ws:
        return "the open ocean (no NHD record)"
    if any(w in NON_NAME for w in ws) or (len(ws) == 1 and (ws[0] in KIND_WORDS or ws[0] in {"water", "waters"})):
        return "not a water name"
    if any(w in WETLAND for w in ws):
        return "a wetland (not a named NHD water)"
    return None


def has_kind(ws) -> bool:
    return any(w in KIND_WORDS for w in ws)


def trim_part(p: str) -> str:
    """'Tributary of Longhouse creek' -> 'Longhouse creek'; 'Penhorn Creek UNT' -> 'Penhorn Creek';
    'Foster Brook to Lake Erie' -> 'Foster Brook'; 'Catch Basin to Fall Mountain lake' -> 'Fall Mountain
    lake' (the first water in a chain); 'Mill Creek Tube' -> 'Mill Creek'; '' when none is a water."""
    p = re.sub(r"^\W+|\W+$", "", p.strip())
    p = re.sub(r"^(possibly|probably|maybe|likely|presumably)\s+", "", p, flags=re.I)
    p = re.sub(r"^(an?\s+|the\s+)?(unnamed\s+|small\s+)?(tributary|trib\.?|unt|ut|branch|stream|brook)\s+(of|to)\s+(the\s+)?",
               "", p, flags=re.I)
    p = re.sub(r"^(unnamed\s+)?(tributary|trib\.?|unt|ut)\s+", "", p, flags=re.I)
    chain = re.split(r"\s+(?:to|into|via|then|thence|flows to|flowing to|discharges to|leading to)\s+", p, flags=re.I)
    for c in chain:
        c = re.sub(r"^(the|a|an|at|on|in)\s+", "", c.strip(" .,-#"), flags=re.I)
        head = re.split(r"\s+(?:at|near|behind|between|below|above|along|by|off|across|from|on|in|just|adjacent|"
                        r"upstream|downstream)\s+", c, maxsplit=1, flags=re.I)[0]
        if head != c and head and not not_water(head):
            c = head            # 'West river at the Retreat Meadows' -> 'West river'
        if len(c.split()) > 6:
            continue            # free text, not a name
        toks = c.split()
        while len(toks) > 1 and words(toks[-1]) and all(w in TRAILING_JUNK for w in words(toks[-1])) \
                and has_kind(words(" ".join(toks[:-1]))):
            toks.pop()
        c = " ".join(toks).strip(" .,-#")
        if c and not not_water(c):
            return c
    return ""


def split_names(text: str, point_mode: bool) -> list[str]:
    """The water names in one waterbody text (possibly none)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.sub(r"\(.*?\)", " ", t).strip()
    if point_mode:   # a site name: keep the water named in it ("Harry Wright Lake Low Beach")
        out = []
        for x in re.split(r"\s*-\s+|\s*[,;/]\s*", t):
            for seg in re.split(SITE_WORDS, x)[::2]:
                if has_kind(words(seg)):
                    seg = trim_part(seg)
                    if seg and has_kind(words(seg)):
                        out.append(seg)
        return out[-1:]
    parts = re.split(r"\s*(?:/|&|;|\+|,|\band\b)\s*", t, flags=re.I)
    out = []
    for p in parts:
        p = trim_part(p)
        if p and not not_water(p):
            out.append(p)
    return out


INVERTED = re.compile(r"^\s*([^,]+?),\s*([A-Za-z.' ]{2,20}?)\s*$")
INVERTED_LEAD = {"lake", "lakes", "bayou", "mount", "point", "lac", "bay", "big", "little", "old", "the"}


def gnis_display(name: str | None) -> str | None:
    """A GNIS name as written: NHDPlus V2.1 carries some in the inverted form GNIS files them under ('Apopka, Lake',
    'Marcus, Bayou' in Florida, 2026-11-04): 'Lake Apopka', 'Bayou Marcus'."""
    if not name:
        return name
    m = INVERTED.match(name)
    if m and words(m.group(2)) and words(m.group(2))[0] in INVERTED_LEAD:
        return f"{m.group(2).strip()} {m.group(1).strip()}"
    return name


def name_score(target_ws: list[str], gnis: str | None) -> float:
    """How well an NHD GNIS name matches a target's name: 1 equal (spaces, numbers and abbreviations
    aside), 0.9 the GNIS name inside the target (with a kind word), 0.85 the target inside the GNIS name
    (the target has no kind word: 'moodna', 'cazenovia'), 0.8 a close spelling (same first letter,
    10+ letters), else 0."""
    if not gnis or not target_ws:
        return 0.0
    gw = words(gnis_display(gnis))
    a, b = compact(target_ws), compact(gw)
    if a == b:
        return 1.0

    def inside(x, y):
        return any(y[i:i + len(x)] == x for i in range(len(y) - len(x) + 1))
    if len(gw) >= 2 and has_kind(gw) and inside(gw, target_ws):
        return 0.9
    if not has_kind(target_ws) and inside(target_ws, gw) and len(a) >= 5:
        extra = [w for w in gw if w not in target_ws]
        if all(w in KIND_WORDS for w in extra):
            return 0.85
    if len(a) >= 10 and len(b) >= 10 and a[0] == b[0] and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
        ka = [w for w in target_ws if w in KIND_WORDS][-1:]
        kb = [w for w in gw if w in KIND_WORDS][-1:]
        if ka == kb or not ka or not kb:
            return 0.8
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 7 and len(long_) == len(short) + 1 and a[0] == b[0] \
            and any(long_[:i] + long_[i + 1:] == short for i in range(len(long_))):
        return 0.8      # one letter more or less: 'Stoney Run' for Stony Run, 'Keeler Brook' for Keelers Brook
    if len(target_ws) >= 2 and target_ws[-1] in ("branch", "fork") and len(gw) > len(target_ws) \
            and gw[:len(target_ws)] == target_ws and gw[-1] in KIND_WORDS and gw[-1] not in ("branch", "fork"):
        return 0.8      # the local short name: 'Third Branch' for the Third Branch White River (Randolph, VT)
    if [w for w in gw if w not in QUALIFIERS] == [w for w in target_ws if w not in QUALIFIERS] \
            and all(w in gw for w in target_ws if w in QUALIFIERS):
        return 0.7      # 'Nashua River' for the North Nashua River: only for the flowline the point snaps to
    return 0.0


def sql_names(t: dict) -> list[str]:
    """GNIS spellings to ask the MapServer for (upper case): the name, numbers as words, number words
    joined to 'mile' ('Twomile Creek'), abbreviations expanded."""
    out = {t["name"].upper()}
    ws = t["words"]
    out.add(" ".join(ws).upper())
    joined = []
    for w in ws:
        if joined and w == "mile" and joined[-1] in NUMS.values():
            joined[-1] += w
        else:
            joined.append(w)
    out.add(" ".join(joined).upper())
    if t.get("report_name"):        # a report's spelling: without 'of', without a possessive, 'Wills Branch Creek' as
        for x in list(out):         # 'WILLS BRANCH', the Intracoastal Waterway under GNIS's two names
            y = re.sub(r"\b(OF|THE)\b\s*", "", x).strip()
            out.update({y, re.sub(r"'S\b", "S", y), re.sub(r"'S\b", "", y), re.sub(r"\bBRANCH CREEK$", "BRANCH", y)})
            if re.fullmatch(r"(INTRACOASTAL WATERWAY|INTRACOASTAL)", y):
                out.update({"ATLANTIC INTRACOASTAL WATERWAY", "GULF INTRACOASTAL WATERWAY"})
    if t.get("define_by") or t.get("report_name"):
        # a state build or a report name: the inverted GNIS form too ('APOPKA, LAKE' for Lake Apopka)
        for x in list(out):
            first, _, rest = x.partition(" ")
            if rest and first.lower() in INVERTED_LEAD:
                out.add(f"{rest}, {first}")
    return sorted(x.replace("'", "''") for x in out if x)


# ---------------------------------------------------------------- HTTP (cached, polite)

NLDI_PER_HOUR = 3600         # USGS: 3,600 NLDI requests an hour per address
NLDI_LOG = CACHE_DIR / "nldi-requests.json"     # the times of this address's NLDI requests in the last hour


class BudgetExhausted(Exception):
    """The run's request budget (--max-requests) or time budget (--budget-s) is used: the run stops cleanly, writes
    what it has, and the next run resumes from the cached responses."""


class Http:
    """Cached, polite GETs. max_requests: at most this many network requests in the run; deadline (time.monotonic())
    after which no network request is started; both raise BudgetExhausted before a request, never in the middle of
    one. NLDI requests (kinds starting with 'nldi') keep to NLDI_PER_HOUR in any hour, across runs (NLDI_LOG): a
    request that would exceed it waits for the oldest to age out, or stops the run when the wait passes the deadline."""

    def __init__(self, refresh: bool = False, offline: bool = False, max_requests: int | None = None,
                 deadline: float | None = None, nldi_log=None, nldi_per_hour: int = NLDI_PER_HOUR):
        self.refresh, self.offline = refresh, offline
        self.session = requests.Session()
        self.last = 0.0
        self.fetched = Counter()
        self.cached = Counter()
        self.failed = Counter()
        self.max_requests, self.deadline = max_requests, deadline
        self.requests = 0                   # network requests started this run (retries included)
        self.nldi_log = NLDI_LOG if nldi_log is None else nldi_log
        self.nldi_per_hour = nldi_per_hour
        self._nldi_times = None

    def _nldi_recent(self) -> list[float]:
        if self._nldi_times is None:
            try:
                self._nldi_times = [float(x) for x in json.loads(self.nldi_log.read_text())]
            except (OSError, ValueError, TypeError):
                self._nldi_times = []
        now = time.time()
        self._nldi_times = [x for x in self._nldi_times if now - x < 3600]
        return self._nldi_times

    def _nldi_note(self) -> None:
        self._nldi_times.append(time.time())
        try:
            self.nldi_log.parent.mkdir(parents=True, exist_ok=True)
            self.nldi_log.write_text(json.dumps([round(x, 1) for x in self._nldi_times]))
        except OSError:
            pass

    def spend(self, kind: str) -> None:
        """Count one network request against the budgets (BudgetExhausted when none is left)."""
        if self.max_requests is not None and self.requests >= self.max_requests:
            raise BudgetExhausted(f"--max-requests {self.max_requests} used")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise BudgetExhausted("--budget-s used")
        if kind.startswith("nldi"):
            recent = self._nldi_recent()
            if len(recent) >= self.nldi_per_hour:
                wait = 3600 - (time.time() - recent[-self.nldi_per_hour]) + 1
                if self.deadline is not None and time.monotonic() + wait >= self.deadline:
                    raise BudgetExhausted(f"the NLDI limit ({self.nldi_per_hour} requests an hour) is reached and "
                                          f"the wait ({wait:.0f} s) passes --budget-s")
                print(f"  NLDI: {self.nldi_per_hour} requests in the last hour; waiting {wait:.0f} s", flush=True)
                time.sleep(max(0.0, wait))
                self._nldi_recent()
            self._nldi_note()
        self.requests += 1

    @staticmethod
    def path(kind: str, url: str, params: dict):
        key = hashlib.sha1(f"{url}?{urlencode(sorted(params.items()))}".encode()).hexdigest()[:24]
        return CACHE_DIR / kind / f"{key}.json"

    def is_cached(self, kind: str, url: str, params: dict) -> bool:
        return not self.refresh and self.path(kind, url, params).exists()

    def get(self, kind: str, url: str, params: dict, attempts: int = 6):
        path = self.path(kind, url, params)
        if path.exists() and not self.refresh:
            self.cached[kind] += 1
            return json.loads(path.read_text())["response"]
        if self.offline:
            return None
        for attempt in range(attempts):
            self.spend(kind)
            wait = PAUSE_S - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.session.get(url, params=params, headers=HEADERS, timeout=120)
            except requests.RequestException as ex:
                self.last = time.time()
                print(f"  {kind}: {type(ex).__name__}; retrying", flush=True)
                time.sleep(min(120, 5 * 2 ** attempt))
                continue
            self.last = time.time()
            if r.status_code >= 500 and attempt + 1 >= attempts:
                break
            if r.status_code == 429 or r.status_code >= 500:
                ra = r.headers.get("Retry-After") or ""
                pause = float(ra) if ra.isdigit() else min(300, (30 if r.status_code == 429 else 3) * 2 ** attempt)
                print(f"  {kind}: HTTP {r.status_code}; waiting {pause:.0f} s", flush=True)
                time.sleep(pause)
                continue
            if r.status_code in (400, 404) and kind.startswith("nldi"):
                data = {"_status": r.status_code, "_text": r.text[:300]}   # off the network: remembered
            else:
                r.raise_for_status()
                try:
                    data = r.json()
                except ValueError:
                    time.sleep(5)
                    continue
                if isinstance(data, dict) and data.get("error"):    # ArcGIS reports errors in a 200
                    print(f"  {kind}: {str(data['error'])[:160]}; retrying", flush=True)
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"url": url, "params": params, "fetched_at": now_iso(), "response": data}))
            self.fetched[kind] += 1
            return data
        self.failed[kind] += 1
        return None


def features_of(d) -> list[dict]:
    out = []
    for f in (d or {}).get("features") or []:
        g = f.get("geometry")
        try:
            geom = shape(g) if g else None
        except Exception:
            geom = None
        out.append({**(f.get("properties") or {}), "_geom": geom})
    return out


def arcgis(http: Http, kind: str, layer: int, *, service: str = EPA_NHD, **params) -> list[dict]:
    """All features of a MapServer query (geojson, WGS84), following resultOffset pages. service: the
    MapServer URL (EPA's NHDPlus V2.1 by default; NHD_HR for the high-resolution flowlines)."""
    base = {"outSR": "4326", "f": "geojson", "returnGeometry": "true", "geometryPrecision": "6"}
    base.update({k: str(v) for k, v in params.items()})
    out, offset, paged = [], 0, False
    while True:
        p = dict(base)
        if paged:
            p.update(resultOffset=str(offset), resultRecordCount="1000", orderByFields="OBJECTID")
        d = http.get(kind, f"{service}/{layer}/query", p)
        if d is None:
            return out
        fs = features_of(d)
        more = d.get("exceededTransferLimit") or (d.get("properties") or {}).get("exceededTransferLimit")
        if more and not paged:      # cut at the server's limit: start again in a stable order
            paged = True
            continue
        out.extend(fs)
        if not more or not fs:
            return out
        offset += len(fs)


# ---------------------------------------------------------------- states and towns

def read_state_outlines(codes) -> dict:
    """Census cartographic state outlines (cb_2023_us_state_500k.zip, the Census Bureau's 2023 1:500,000 file:
    data/raw/census/, else the sibling openboatlaunch copy, else downloaded once from
    https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip; waters_extra.states_zip()), read
    without pyshp: shapefile polygons (outer rings clockwise, holes counter-clockwise) and the dbf's STUSPS."""
    z = zipfile.ZipFile(WX.states_zip())
    stem = "cb_2023_us_state_500k"
    shp, dbf = z.read(f"{stem}.shp"), z.read(f"{stem}.dbf")
    nrec = struct.unpack("<I", dbf[4:8])[0]
    hlen, rlen = struct.unpack("<HH", dbf[8:12])
    fields, pos = [], 32
    while dbf[pos] != 0x0D:
        fields.append((dbf[pos:pos + 11].split(b"\0")[0].decode(), dbf[pos + 16]))
        pos += 32
    codes_by_rec = []
    for i in range(nrec):
        off, vals = hlen + i * rlen + 1, {}
        for name, flen in fields:
            vals[name] = dbf[off:off + flen].decode("latin-1").strip()
            off += flen
        codes_by_rec.append(vals.get("STUSPS"))
    out, pos, i = {}, 100, 0
    while pos + 8 <= len(shp):
        _, clen = struct.unpack(">ii", shp[pos:pos + 8])
        content = shp[pos + 8:pos + 8 + clen * 2]
        pos += 8 + clen * 2
        code = codes_by_rec[i]
        i += 1
        if (codes is not None and code not in codes) or struct.unpack("<i", content[:4])[0] != 5:
            continue
        nparts, npts = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{nparts}i", content[44:44 + 4 * nparts])) + [npts]
        pts = np.frombuffer(content[44 + 4 * nparts:44 + 4 * nparts + 16 * npts], dtype="<f8").reshape(-1, 2)
        outers, holes = [], []
        for a, b in zip(parts, parts[1:]):
            ring = pts[a:b]
            if len(ring) < 4:
                continue
            (holes if LinearRing(ring).is_ccw else outers).append(Polygon(ring))
        g = unary_union(outers)
        if holes:
            g = g.difference(unary_union(holes))
        out[code] = g.buffer(0)
    return out


class States(WX.States):
    """waters_extra.States (nearest, shore_state, clip, bbox) over every state's outline, so a river
    is cut at any state line (West Virginia, North Carolina, Tennessee border the covered states)."""

    def __init__(self, codes=None):
        self.shapes = read_state_outlines(set(codes) if codes else None)


class Towns:
    """Census 2020 county subdivisions (TIGERweb layer 22) per state: name, outline, interior point."""

    def __init__(self, http: Http):
        self.http = http
        self.by_state = {}

    def load(self, state: str):
        if state in self.by_state:
            return self.by_state[state]
        rows = []
        fips = FIPS.get(state)
        feats = []
        for url in (TIGER_PLACES if state in PLACE_STATES else [TIGER_COUSUB]) if fips else []:
            feats += features_of(self.http.get("tiger", url, {
                "where": f"STATE='{fips}'", "outFields": "BASENAME,NAME,INTPTLAT,INTPTLON", "returnGeometry": "true",
                "outSR": "4326", "maxAllowableOffset": "0.0005", "geometryPrecision": "5", "f": "geojson"}))
        for f in feats:
            name = f.get("BASENAME") or ""
            if not name or "not defined" in name.lower() or f["_geom"] is None or re.search(r"\d", name):
                continue
            g = f["_geom"] if f["_geom"].is_valid else f["_geom"].buffer(0)
            rows.append((name, g))
        tree = STRtree([g for _, g in rows]) if rows else None
        self.by_state[state] = (rows, tree)
        return rows, tree

    def at(self, state: str, lon: float, lat: float) -> str | None:
        rows, tree = self.load(state)
        if tree is None:
            return None
        p = Point(lon, lat)
        for i in tree.query(p):
            if rows[i][1].contains(p):
                return rows[i][0]
        i = tree.nearest(p)
        return rows[i][0] if i is not None and rows[i][1].distance(p) < 0.01 else None

    def along(self, state: str, geom) -> list[str]:
        rows, tree = self.load(state)
        if tree is None:
            return []
        names = set()
        for i in tree.query(geom):
            name, g = rows[i]
            inter = g.intersection(geom)
            if inter.is_empty:
                continue
            if geom.geom_type.endswith("Polygon") and inter.area < 1e-7:
                continue
            names.add(name)
        return sorted(names)

    def canonical(self, state: str, name) -> str | None:
        """The county subdivision's name for a town as the records write it, or None."""
        k = town_key(name)
        rows, _ = self.load(state)
        return next((n for n, _ in rows if town_key(n) == k), None) if k else None

    def outlines(self, state: str, keys) -> list:
        rows, _ = self.load(state)
        keys = {town_key(k) for k in keys if k}
        return [g for name, g in rows if town_key(name) in keys]


# ---------------------------------------------------------------- targets

def existing_waters() -> dict:
    """The water records the site has without this file (openboatlaunch, waters-extra)."""
    return S.load_waters(include_nhd=False)


def outfall_rows():
    for key, path, default_state in OUTFALL_FILES:
        d = read_json(path) or {}
        rows = d.get("outfalls") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        for r in rows:
            permit = r.get("npdes_permit") or r.get("npdes") or r.get("permit") or ""
            state = (r.get("state") or (permit[:2] if re.match(r"[A-Z]{2}\d", permit) else default_state) or "").upper()
            name = r.get("receiving_water_echo") or r.get("receiving_water") or r.get("waterbody") or ""
            town = r.get("city") or r.get("town") or ""
            m = re.match(r"^(.*?),\s*(TOWN|CITY|VILLAGE|BOROUGH|TOWNSHIP) OF$", str(r.get("facility") or ""), re.I)
            if not town and m:
                town = m.group(1)
            yield {"file": key, "state": state, "permit": permit, "outfall": r.get("outfall"), "name": str(name).strip(),
                   "lat": r.get("lat"), "lon": r.get("lon"), "town": str(town).title(), "water_slug": r.get("water_slug")}


def has_record(resolver: S.Resolver, name: str, state: str, lat, lon, permit=None, town=None) -> bool:
    ev = {"npdes_permit": permit, "lat": lat, "lon": lon, "raw": {"state": state, "town": town or ""},
          "waterbody_text": name}
    slugs, _, _ = resolver.by_name(name, state, lat, lon, ev)
    if not slugs:
        return False
    kept, _ = resolver.guard(slugs, ev)
    return bool(kept)


class Target(dict):
    pass


def collect_targets(existing: dict, events=None, verbose=True):
    """(targets, skipped, stats). A target: one water name in one state, with the outfalls and events
    that name it, their points (weighted) and towns."""
    S._STATES = S.derive_states(existing, S.load_rules())
    S._GEOM_CACHE.clear()
    resolver = S.make_resolver(existing)
    targets: dict[tuple, Target] = {}
    skipped = Counter()
    skipped_reason = {}
    stats = Counter()

    def add(state, text, part, kind, lat, lon, town, ref, point_mode):
        ws = words(part) if part else []
        key = (state, compact(ws) if part else f"site:{lat:.4f},{lon:.4f}")
        t = targets.get(key)
        if t is None:
            t = targets[key] = Target(state=state, key=f"{state}:{key[1]}", names=Counter(), texts=Counter(),
                                      outfalls=0, events=0, points=Counter(), towns=Counter(), sources=Counter(),
                                      point_mode=point_mode, refs=[], outfall_points=Counter())
        if part:
            t["names"][part] += 1
        t["texts"][text] += 1
        t[kind] += 1
        if lat is not None and lon is not None:
            t["points"][(round(float(lon), 5), round(float(lat), 5))] += 1
            if kind == "outfalls":
                t["outfall_points"][(round(float(lon), 5), round(float(lat), 5))] += 1
        for tw in town if isinstance(town, (set, list)) else [town]:
            tw = str(tw or "").strip()
            if tw and len(tw) <= 40 and len(tw.split()) <= 4 and not re.search(r"\d", tw):
                t["towns"][tw] += 1
        t["sources"][ref.split(":")[0]] += 1
        if len(t["refs"]) < 5:
            t["refs"].append(ref)
        t["point_mode"] = t["point_mode"] and point_mode

    for o in outfall_rows():
        stats["outfalls"] += 1
        if not o["state"] or o["state"] in OTHER_BUILDER:
            continue
        name = o["name"]
        lat, lon = o["lat"], o["lon"]
        if not name:
            if not o["water_slug"]:
                skipped["outfall with no receiving-water name"] += 1
            continue
        if has_record(resolver, name, o["state"], lat, lon, o["permit"], o["town"]):
            continue        # the receiving water is a record (the registry may still lack the slug)
        parts = split_names(name, False)
        if not parts:
            skipped[f"outfall: {not_water(name) or 'no water name'}"] += 1
            skipped_reason.setdefault((o["state"], name), not_water(name) or "no water name")
            continue
        for p in parts:
            if len(parts) > 1 and has_record(resolver, p, o["state"], lat, lon, o["permit"], o["town"]):
                continue
            stats["outfall targets"] += 1
            add(o["state"], name, p, "outfalls", lat, lon, o["town"],
                f"{o['file']}:{o['permit']}:{o['outfall']}", False)

    if events is None:
        _, events, _ = S.load_events(EVENTS_DIR, False, False)
    for ev in events:
        text = (ev.get("waterbody_text") or "").strip()
        if not text:
            continue
        pl = resolver.resolve(ev)
        if pl["water_slugs"]:
            continue
        if pl.get("no_receiving_water"):        # "N/A", "storm drain", "did not reach a waterbody"
            skipped[f"event: {pl['no_receiving_water'][:60]}"] += 1
            skipped_reason.setdefault((S.event_state(ev), text), "the report names no receiving water")
            continue
        stats["unplaced events with a waterbody_text"] += 1
        state = S.event_state(ev)
        if not state:
            skipped["event with no state"] += 1
            continue
        if state in OTHER_BUILDER:
            skipped[f"event: {OTHER_BUILDER[state]}"] += 1
            skipped_reason.setdefault((state, text), OTHER_BUILDER[state])
            continue
        point_mode = ev.get("event_type") in POINT_TYPES
        towns = set(resolver.event_towns(ev))
        m = re.search(r"\(([^()]*)\)\s*$", text)
        if m and not re.search(r"\d", m.group(1)):
            towns.add(m.group(1))
        parts = split_names(text, point_mode)
        if not parts:
            why = not_water(text)
            if point_mode and ev.get("lat") is not None and ev.get("lon") is not None and not why:
                add(state, text, None, "events", ev["lat"], ev["lon"], towns, ev["event_id"], True)
                continue
            why = why or "no water name"
            skipped[f"event: {why}"] += 1
            skipped_reason.setdefault((state, text), why)
            continue
        for p in parts:
            add(state, text, p, "events", ev.get("lat"), ev.get("lon"), towns, ev["event_id"], point_mode)
    out = []
    for t in targets.values():
        if t["names"]:
            t["name"] = t["names"].most_common(1)[0][0]
            t["words"] = words(t["name"])
        else:
            t["name"], t["words"] = None, []
        out.append(t)
    out.sort(key=lambda t: (-(t["events"] + t["outfalls"]), t["key"]))
    return out, skipped, skipped_reason, stats, resolver


def print_targets(targets, limit=None):
    print(f"\n{'st':2} {'name':42} {'outfalls':>8} {'events':>7} {'points':>6}  towns")
    for t in targets[:limit]:
        name = t["name"] or (f"(unnamed outfall) {' '.join(str(x) for x in t['outfall_ref'])}" if t.get("outfall_ref")
                             else f"(site) {next(iter(t['texts']), '')}")
        print(f"{t['state']:2} {name[:42]:42} {t['outfalls']:8} {t['events']:7} {len(t['points']):6}  "
              f"{', '.join(x for x, _ in t['towns'].most_common(3))}")
    print(f"{len(targets)} targets: {sum(t['outfalls'] for t in targets)} outfall rows, "
          f"{sum(t['events'] for t in targets)} event names")


# ---------------------------------------------------------------- a state build (--state): the national target list

NATIONAL = DATA_DIR / "receiving-waters-national.json"
DEFINE_ORDER = {"reach": 0, "point": 1, "name": 2, "unnamed": 3}
# texts in EPA's receiving-water field that name a county, a town or a land-application system, not a water
# (Georgia's permits: 'BANKS COUNTY', 'CHATHAM COUNTY LAS', 'CITY OF REIDSVILLE'); checked on the segment that would
# name the receiving water
NATIONAL_NOT_WATER = [
    (re.compile(r"\b(county|counties|co|parish)\b(?!\s+(creek|river|branch|lake|line|ditch|canal|pond|run))", re.I),
     "a county name in EPA's receiving-water field, not a water"),
    (re.compile(r"\b(las|land\s+application|spray\s*field|percolation|infiltration|reuse)\b", re.I),
     "a land-application system, not a surface water"),
    (re.compile(r"^\s*(city|town|village)\s+of\b", re.I), "a town name in EPA's receiving-water field, not a water"),
    (re.compile(r"\b(hwy|highway|road|rd|route|rte|street)\b", re.I), "a road in EPA's receiving-water field, not a water"),
]
# a river basin named after the water ('PANTHER CRK/UPPER OCMULGEE RV BASIN', 'PALMETTO CREEK TRIB - Chattahoochee
# Basin'): cut off; a segment that is only a basin ('SUWANNEE RIVER BASIN') names no water
BASIN_TAIL = re.compile(r"\s*[-_]*\s*(\b[\w.']+\s+){0,3}?(river\s+|rvr\s+|rv\s+|r\.?\s+)?(basin|bsn)\b.*$", re.I)
# Florida's waterbody ids and classes ('Old Tampa Bay Class II Marine WBID 1558H'), Georgia's river-basin tails
# ('... TO OGEECHEE RB', '-SAV RB')
NATIONAL_TAGS = [
    re.compile(r"\bclass\s+(i{1,3}|iv|v|1|2|3)\b(\s+(predominately|predominantly))?"
               r"(\s+(marine|fresh|freshwater|estuary)(\s+waters?)?)?(\s+brackish)?", re.I),
    re.compile(r"\bcl\s+\d\b", re.I),
    re.compile(r"\bwbids?(\b|(?=\d))(\s*[\w-]+)?(\s+[a-z]\d?\b)?", re.I),
    re.compile(r"\b\d{3,5}[a-z]{0,2}\d?\b", re.I),
    re.compile(r"-\w+\s+rb\s*$|\s+rb\s*$", re.I),
    re.compile(r"^\s*\d{3}\s*-\s*", re.I),                  # an outfall number in front ('002-UNNAMED TRIB TO FLINT')
    re.compile(r"^\s*(discharges?d?|outfall|flows?)\s+(to|into)\s+", re.I),
    re.compile(r"^\s*tidal\s+", re.I),
    re.compile(r"\b(estuary)\b(?=\s*$)", re.I),
    re.compile(r"\b(etc)\b\.?", re.I),
]
NATIONAL_WORD_FIX = [(re.compile(r"(?<=[a-z])crk\b", re.I), " Creek"),
                     (re.compile(r"\bRV\b|\bRVR\b", re.I), "River"), (re.compile(r"\bCRK\b|\bCR\b|\bCK\b", re.I), "Creek"),
                     (re.compile(r"\bBR\b", re.I), "Branch"), (re.compile(r"\bR\b(?=\s*($|,|and\b))", re.I), "River"),
                     (re.compile(r"\bO\b(?=\s*($|,))", re.I), "Ocean"), (re.compile(r"\bLK\b\.?", re.I), "Lake"),
                     (re.compile(r"\bWtwy\b", re.I), "Waterway"), (re.compile(r"\bICWW\b", re.I), "Intracoastal Waterway"),
                     (re.compile(r"\bEst\b", re.I), "Estuary"), (re.compile(r"\bCannal\b", re.I), "Canal")]
UNNAMED_SEG = re.compile(r"\b(unnamed|un-named|unnam|trib|tributary|tri|unt|ut)\b", re.I)


def national_parts(text: str) -> tuple[list[str], str | None]:
    """(water names, reason): the waters a national row's receiving-water text names. EPA's text for the states not yet
    built carries path notation ('BOGGY CRK/SPRING CRK/FLINT RIVER', 'GROVE CRK TRIB/S. FORK/BROAD RIVER-SAV RB': the
    first water receives the discharge, the rest are where it flows; an unnamed tributary's segment hands on to the
    water it joins), Florida's class and waterbody-id tags, river-basin tails, and counties, roads or land-application
    systems in place of a water; lists ('X and Y', 'X, Y') name several receiving waters. A name with no kind word
    ('CHATTAHOOCHEE') is kept when it is a word of five letters or more ('abc', 'temp' are not). reason: why the text
    names no water (None when it names one)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.sub(r"\[?\(.*?\)\]?", " ", t)
    t = re.sub(r"\s*\[?\(.*$", "", t).strip()           # a parenthesis EPA's field cut off
    t = re.sub(r"^.*?\barm\s+of\s+(the\s+)?", "", t, flags=re.I)     # an arm of a lake is the lake
    reason = None
    for seg in re.split(r"\s*[/\\]\s*", t):
        cut = BASIN_TAIL.sub("", seg)
        if not cut.strip():
            reason = reason or "a river basin in EPA's receiving-water field, not a water"
            break
        why = next((w for rx, w in NATIONAL_NOT_WATER if rx.search(cut)
                    and not (w.startswith("a road") and has_kind(words(cut)))), None)
        if why:
            reason = reason or why
            break
        for rx in NATIONAL_TAGS:
            cut = rx.sub(" , ", cut)        # a tag ends a name ('Black Cr Class III Fresh WBID 2213I St Johns R')
        for rx, rep in NATIONAL_WORD_FIX:
            cut = rx.sub(rep, cut)
        cut = re.sub(r"\s+", " ", cut).strip(" ,.-")
        parts = []
        for p in re.split(r"\s*(?:&|;|\+|,|\band\b)\s*", cut, flags=re.I):
            p = trim_part(p)
            if not p or not_water(p) or re.fullmatch(r"(n/?a|na|etc)", p, re.I) or UNNAMED_SEG.fullmatch(p.strip()):
                continue
            if not has_kind(words(p)) and (len(compact(p)) < 5 or UNNAMED_SEG.search(p)):
                continue
            parts.append(p)
        if parts:
            return list(dict.fromkeys(parts)), None
        reason = reason or not_water(cut) or "no water name"
        if not UNNAMED_SEG.search(seg):
            break                   # only an unnamed tributary's segment hands on to the next
    return [], reason or "no water name"


def national_rows(states, path=None) -> dict:
    """{state: the national list's block for it} (data/receiving-waters-national.json)."""
    d = read_json(path or NATIONAL) or {}
    return {st: (d.get("states") or {}).get(st) or {"waters": [], "unnamed_outfalls": []} for st in states}


def registry_towns(states) -> dict:
    """{permit: Counter(city)} from the registry rows of these states (outfalls-us, outfalls-plants-us, outfalls-<st>):
    the national list gives the operators, the rows give their towns (the name pass picks the water nearest them)."""
    out = defaultdict(Counter)
    paths = [DATA_DIR / "outfalls-us.json", DATA_DIR / "outfalls-plants-us.json"]
    paths += [DATA_DIR / f"outfalls-{st.lower()}.json" for st in states]
    for p in paths:
        d = read_json(p) or {} if p.exists() else {}
        for r in (d.get("outfalls") if isinstance(d, dict) else d) or []:
            if (r.get("state") or "").upper() in states and r.get("npdes_permit") and r.get("city"):
                out[r["npdes_permit"]][str(r["city"]).title()] += 1
    return out


def collect_state_targets(states, existing: dict, national: dict | None = None, towns_by_permit: dict | None = None):
    """(targets, skipped_reason, stats) for a state build: every row of the national list for these states without a
    water record on file (define_by reach | point | name; a 'record' row whose slug no water file on disk holds, an
    openboatlaunch slug whose extract is not here, is built as its reach or point row would be and says so), and
    every unnamed outfall, as targets in the order reach, point, name, unnamed (most outfalls first within each).
    A target is one water name in one state with the national row's reach codes, NHDPlus ids, points, operators and
    their towns; an unnamed outfall is a target of its own (refs: its permit and outfall)."""
    national = national_rows(states) if national is None else national
    towns_by_permit = registry_towns(states) if towns_by_permit is None else towns_by_permit
    targets, skipped_reason, stats = {}, {}, Counter()
    for st in states:
        block = national.get(st) or {}
        for w in block.get("waters") or []:
            stats["national rows"] += 1
            how = w.get("define_by")
            note = None
            if how == "record":
                if w.get("water_slug") in existing:
                    stats["rows with a record"] += 1
                    continue
                how = "reach" if (w.get("reach_ids") or w.get("nhdplus_ids")) else "point" if w.get("points") else "name"
                note = (f"the registry's slug {w.get('water_slug')} is no water record on file (openboatlaunch's "
                        f"extract for {st} is not here): defined by {how}")
            parts, why = national_parts(w.get("name") or "")
            if not parts:
                for alt in w.get("names_seen") or []:
                    parts, _ = national_parts(alt)
                    if parts:
                        break
            if not parts:
                skipped_reason[(st, w.get("name") or "")] = why
                stats[f"rows naming no water: {why}"] += 1
                continue
            permits = [o.get("permit") for o in w.get("operators") or [] if o.get("permit")]
            n_out = sum((w.get("outfalls") or {}).values()) or 1
            for part in parts:
                ws = words(part)
                key = (st, compact(ws))
                t = targets.get(key)
                if t is None:
                    t = targets[key] = Target(state=st, key=f"{st}:{key[1]}", names=Counter(), texts=Counter(),
                                              outfalls=0, events=0, points=Counter(), towns=Counter(), sources=Counter(),
                                              point_mode=False, refs=[], outfall_points=Counter(), define_by=how,
                                              reach_ids=[], nhdplus_ids=[], permits=[], national=[], notes=[])
                elif DEFINE_ORDER.get(how, 9) < DEFINE_ORDER.get(t["define_by"], 9):
                    t["define_by"] = how
                t["names"][part] += n_out
                t["texts"][w.get("name") or part] += n_out
                t["outfalls"] += n_out
                for lat, lon in w.get("points") or []:
                    p = (round(float(lon), 5), round(float(lat), 5))
                    t["points"][p] += 1
                    t["outfall_points"][p] += 1
                for x in w.get("reach_ids") or []:
                    if x not in t["reach_ids"]:
                        t["reach_ids"].append(str(x))
                for x in w.get("nhdplus_ids") or []:
                    if x not in t["nhdplus_ids"]:
                        t["nhdplus_ids"].append(str(x))
                for p in permits:
                    if p not in t["permits"]:
                        t["permits"].append(p)
                    for tw, n in (towns_by_permit.get(p) or {}).items():
                        t["towns"][tw] += n
                t["sources"]["national"] += 1
                t["national"].append(w.get("name"))
                if note:
                    t["notes"].append(note)
                if len(t["refs"]) < 5:
                    t["refs"].append(f"national:{st}:{w.get('key') or w.get('name')}")
                stats[f"targets by {how}"] += 1
        for u in block.get("unnamed_outfalls") or []:
            stats["unnamed outfalls"] += 1
            if u.get("water_slug") and u["water_slug"] in existing:
                continue
            ids = [str(x) for x in (u.get("nhdplus_id"), ) if x]
            codes = [str(x) for x in (u.get("reach_id"), ) if x]
            has_pt = u.get("lat") is not None and u.get("lon") is not None
            ref = f"{u.get('permit')}:{u.get('outfall')}"
            if not ids and not codes and not has_pt:
                skipped_reason[(st, f"unnamed outfall {ref}")] = ("no receiving-water name, no point and no NHD reach in "
                                                                  "EPA's records for this outfall")
                stats["unnamed outfalls with no point and no reach"] += 1
                continue
            t = Target(state=st, key=f"{st}:outfall:{ref}", names=Counter(), texts=Counter(), outfalls=1, events=0,
                       points=Counter(), towns=Counter(), sources=Counter(national=1), point_mode=False,
                       refs=[f"national:{st}:outfall:{ref}"], outfall_points=Counter(), define_by="unnamed",
                       reach_ids=codes, nhdplus_ids=ids, permits=[u.get("permit")] if u.get("permit") else [],
                       national=[], notes=[], outfall_ref=[u.get("permit"), u.get("outfall")])
            if has_pt:
                p = (round(float(u["lon"]), 5), round(float(u["lat"]), 5))
                t["points"][p] += 1
                t["outfall_points"][p] += 1
            for tw, n in (towns_by_permit.get(u.get("permit")) or {}).items():
                t["towns"][tw] += n
            targets[("unnamed", st, ref)] = t
            stats["targets by unnamed"] += 1
    out = []
    for t in targets.values():
        if t["names"]:
            t["name"] = t["names"].most_common(1)[0][0]
            t["words"] = words(t["name"])
        else:
            t["name"], t["words"] = None, []
        out.append(t)
    out.sort(key=lambda t: (DEFINE_ORDER.get(t["define_by"], 9), -t["outfalls"], t["key"]))
    return out, skipped_reason, stats


UNNAMED_STREAM = "Unnamed stream"


def unnamed_name(downstream: str | None, town: str | None = None) -> str:
    """An unnamed flowline's public name: the first named water downstream ('Unnamed tributary to X'), else the town it
    lies in ('Unnamed stream near Palmetto': no named water within 50 km downstream, a coastal ditch or canal), else
    'Unnamed stream' (listed by name_unnamed_streams)."""
    if downstream:
        return f"Unnamed tributary to {downstream}"
    return f"{UNNAMED_STREAM} near {town_display(town)}" if town else UNNAMED_STREAM


def name_unnamed_streams(doc: dict, states, when: str | None = None) -> tuple[list[dict], list[str]]:
    """The records of `states` named just 'Unnamed stream' (built before unnamed_name took the town), in place: named
    for the first town of their own town list, else of their target rows' (the operators'), with the slug that name
    gives (the old slug kept in slug_aliases, which build/status.py follows) and the target rows following. Returns
    (the actions, the slugs left as they are for want of a town)."""
    states = {x.upper() for x in states}
    when = when or now_iso()[:10]
    waters = doc.get("waters") or []
    taken = {w["slug"] for w in waters if w.get("slug")}
    rows_of = defaultdict(list)
    for t in doc.get("targets") or []:
        for x in t.get("slugs") or []:
            rows_of[x].append(t)
    moved, actions, left = {}, [], []
    for i, w in enumerate(waters):
        if w.get("state") not in states or w.get("name") != UNNAMED_STREAM:
            continue
        towns = list(w.get("towns") or []) or [x for t in rows_of.get(w["slug"], []) for x in t.get("towns") or []]
        if not towns:
            left.append(w["slug"])
            continue
        name = unnamed_name(None, towns[0])
        new = f"{slugify(name)}-{w['state'].lower()}"
        if new in taken:
            new = f"{slugify(name)}-{slugify(str((w.get('comids') or [w['slug']])[0]))}-{w['state'].lower()}"
        taken.add(new)
        from_ = "its town list" if w.get("towns") else "its operators' town"
        waters[i] = {**w, "name": name, "slug": new,
                     "slug_aliases": list(dict.fromkeys(list(w.get("slug_aliases") or []) + [w["slug"]])),
                     "note": (w.get("note") or "") + f"; no named water within 50 km downstream: named for {from_} "
                                                     f"({towns[0]}) on {when}"}
        moved[w["slug"]] = new
        actions.append({"slug": w["slug"], "action": "named", "to": new, "why": f"{name} ({from_})"})
    for t in doc.get("targets") or []:
        if not any(x in moved for x in t.get("slugs") or []):
            continue
        t["slugs"] = [moved.get(x, x) for x in t["slugs"]]
        if t.get("reach_slugs"):
            t["reach_slugs"] = {k: moved.get(v, v) for k, v in t["reach_slugs"].items()}
    doc["waters"] = sorted(waters, key=lambda r: r.get("slug") or "")
    return actions, left


# ---------------------------------------------------------------- resolving a target to an NHD feature

def dist_m(geom, lon, lat) -> float:
    if geom is None:
        return float("inf")
    k = 111_320 * math.cos(math.radians(lat))
    g = shapely.transform(geom, lambda c: (c - np.array([lon, lat])) * np.array([k, 110_574]))
    return g.distance(Point(0, 0))


def geom_dist_m(a, b) -> float:
    lat0 = (a.centroid.y + b.centroid.y) / 2
    return WX.to_m(a, lat0)[0].distance(WX.to_m(b, lat0)[0])


def cluster_points(points: Counter, n=MAX_POINTS, sep_m=300) -> list[tuple]:
    chosen = []
    for (lon, lat), _ in points.most_common():
        if all(dist_m(Point(c), lon, lat) > sep_m for c in chosen):
            chosen.append((lon, lat))
        if len(chosen) >= n:
            break
    return chosen


class Nhd:
    def __init__(self, http: Http, states: States, towns: Towns):
        self.http, self.states, self.towns = http, states, towns
        self.use_hydrolocation = False

    def nldi(self, lon, lat):
        """NLDI hydrolocation (the nearest flowline, snapped) when asked for (--hydrolocation) or cached;
        otherwise, or when it fails, NLDI comid/position (the flowline of the catchment holding the
        point). In November 2026 hydrolocation took about 6 s a call and answered 502 on more than half
        of them, so a full run uses comid/position; the name check against the flowlines within 2 km
        (resolve_point) does the rest."""
        q = {"coords": f"POINT({lon} {lat})"}
        d = None
        if self.use_hydrolocation or self.http.is_cached("nldi", NLDI_HYDROLOCATION, q):
            d = self.http.get("nldi", NLDI_HYDROLOCATION, q, attempts=1)
        for f in (d or {}).get("features") or []:
            p = f.get("properties") or {}
            if p.get("source") == "indexed" and p.get("comid"):
                c = (f.get("geometry") or {}).get("coordinates") or [lon, lat]
                return {"comid": int(p["comid"]), "reachcode": p.get("reachcode"), "via": "hydrolocation",
                        "snap_m": round(dist_m(Point(c), lon, lat))}
        d = self.http.get("nldi-position", NLDI_POSITION, {"coords": f"POINT({lon} {lat})"}, attempts=3)
        for f in (d or {}).get("features") or []:
            p = f.get("properties") or {}
            if p.get("comid"):
                g = shape(f["geometry"]) if f.get("geometry") else None
                return {"comid": int(p["comid"]), "reachcode": None, "via": "position",
                        "snap_m": round(dist_m(g, lon, lat)) if g is not None else 9999}
        return None

    def near(self, layer, lon, lat, radius=NEAR_M):
        return arcgis(self.http, f"near{layer}", layer, geometry=f"{lon},{lat}", geometryType="esriGeometryPoint",
                      inSR="4326", distance=radius, units="esriSRUnit_Meter", spatialRel="esriSpatialRelIntersects",
                      outFields=FL_FIELDS if layer == 2 else WB_FIELDS, maxAllowableOffset="0.0001")

    def by_comid(self, layer, comid):
        return arcgis(self.http, f"comid{layer}", layer, where=f"comid={int(comid)}",
                      outFields=FL_FIELDS if layer == 2 else WB_FIELDS, maxAllowableOffset="0.00005")

    def state_env(self, state, pad=0.05):
        b = self.states.bbox(state)
        return f"{b[0] - pad},{b[1] - pad},{b[2] + pad},{b[3] + pad}"

    def lines_by_gnis(self, state, gnis_id):
        return arcgis(self.http, "gnis2", 2, where=f"gnis_id='{gnis_id}'", geometry=self.state_env(state),
                      geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                      outFields=FL_FIELDS, maxAllowableOffset="0.00005")

    def hr_lines(self, state, gnis_id=None, pids=None, box=None):
        """USGS NHD high-resolution flowlines (layer 6) with a GNIS id (zero-padded to 8 digits in that
        dataset) in the state's box, or with the permanent identifiers given inside box (lon0, lat0, lon1,
        lat1; the service times out on an unindexed identifier search over the whole country); cached under
        nhd-hr/."""
        if pids:
            where = "permanent_identifier IN (" + ",".join(f"'{x}'" for x in pids) + ")"
            env = ",".join(str(x) for x in box) if box else self.state_env(state)
            return arcgis(self.http, "nhd-hr", HR_FLOWLINES, service=NHD_HR, where=where, geometry=env,
                          geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                          outFields="permanent_identifier,gnis_id,gnis_name,reachcode,fcode,ftype,lengthkm",
                          maxAllowableOffset="0.00005")
        gid = str(int(gnis_id))
        return arcgis(self.http, "nhd-hr", HR_FLOWLINES, service=NHD_HR, where=f"gnis_id IN ('{gid.zfill(8)}','{gid}')",
                      geometry=self.state_env(state), geometryType="esriGeometryEnvelope", inSR="4326",
                      spatialRel="esriSpatialRelIntersects",
                      outFields="permanent_identifier,gnis_id,gnis_name,reachcode,fcode,ftype,lengthkm",
                      maxAllowableOffset="0.00005")

    def wbs_by_gnis(self, state, gnis_id, env):
        return arcgis(self.http, "gnis4", 4, where=f"gnis_id='{gnis_id}'", geometry=env,
                      geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                      outFields=WB_FIELDS, maxAllowableOffset="0.00005")

    def by_name(self, layer, state, names):
        where = "UPPER(gnis_name) IN (" + ",".join(f"'{n}'" for n in names) + ")"
        return arcgis(self.http, f"name{layer}", layer, where=where, geometry=self.state_env(state),
                      geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                      outFields=FL_FIELDS if layer == 2 else WB_FIELDS, maxAllowableOffset="0.001")


def wants_area(t) -> bool:
    ws = t["words"]
    last = [w for w in ws if w in KIND_WORDS][-1:]
    return bool(last) and (last[0] in LAKE_WORDS or last[0] in BAY_WORDS)


def resolve_point(nhd: Nhd, t, lon, lat) -> tuple[dict | None, str]:
    """(choice, how): the NHD feature a target's point names. choice: {"type": "line", "gnis_id",
    "gnis_name"} or {"type": "wb", "comid", "gnis_id", "gnis_name", "ftype"}."""
    h = nhd.nldi(lon, lat)
    fl = nhd.near(2, lon, lat)
    snapped = next((f for f in fl if h and f.get("comid") == h["comid"]), None)
    if h and snapped is None:
        got = nhd.by_comid(2, h["comid"])
        snapped = got[0] if got else None
    tw = t["words"]
    area_first = wants_area(t)
    line_choice = None
    if tw:
        sc = name_score(tw, snapped.get("gnis_name")) if snapped and snapped.get("gnis_id") else 0
        if sc >= 0.8 or (sc >= 0.7 and h["snap_m"] <= 150):
            line_choice = (snapped, f"NLDI {h['via']} COMID {snapped['comid']} ({h['snap_m']} m)")
        else:
            cands = [(name_score(tw, f.get("gnis_name")), -dist_m(f["_geom"], lon, lat), f) for f in fl
                     if f.get("gnis_id")]
            cands = [c for c in cands if c[0] >= 0.8]
            if cands:
                sc, nd, f = max(cands, key=lambda c: (c[0], c[1]))
                line_choice = (f, f"nearest flowline named '{f['gnis_name']}' ({-nd:.0f} m; NLDI COMID "
                                  f"{h['comid'] if h else '-'} is '{(snapped or {}).get('gnis_name') or 'unnamed'}')")
    wb_choice = None
    need_wb = t["point_mode"] or area_first or line_choice is None or (
        snapped is not None and snapped.get("wbarea_ftype") in LAKE_FTYPES and line_choice is None)
    if need_wb:
        wbs = [f for f in nhd.near(4, lon, lat, NEAR_M if tw else SITE_M) if f.get("ftype") in LAKE_FTYPES]
        if tw:
            cands = [(name_score(tw, f.get("gnis_name")), -dist_m(f["_geom"], lon, lat), f) for f in wbs]
            cands = [c for c in cands if c[0] >= 0.8]
            if cands:
                sc, nd, f = max(cands, key=lambda c: (c[0], c[1]))
                wb_choice = (f, f"waterbody named '{f['gnis_name']}' ({-nd:.0f} m)")
        if wb_choice is None and t["point_mode"]:
            near = [(dist_m(f["_geom"], lon, lat), f) for f in wbs if f.get("ftype") in (390, 436)]
            near = [x for x in near if x[0] <= SITE_M]
            if near:
                dd, f = min(near, key=lambda x: x[0])
                if f.get("gnis_name"):
                    wb_choice = (f, f"the lake/pond at the site ({dd:.0f} m)")
                else:
                    return None, f"the lake/pond at the site ({dd:.0f} m) has no GNIS name in NHDPlus"
    if wb_choice and (area_first or line_choice is None or t["point_mode"]):
        f, how = wb_choice
        return {"type": "wb", "comid": f["comid"], "gnis_id": f.get("gnis_id"), "gnis_name": f.get("gnis_name"),
                "ftype": f.get("ftype")}, how
    if line_choice:
        f, how = line_choice
        return {"type": "line", "gnis_id": f["gnis_id"], "gnis_name": f["gnis_name"], "comid": f["comid"]}, how
    near_names = sorted({f.get("gnis_name") for f in fl if f.get("gnis_name")})[:6]
    return None, ("no NHD flowline or waterbody of that name within 2 km"
                  + (f" (nearby: {', '.join(near_names)})" if near_names else " (no named NHD water nearby)"))


def resolve_name_only(nhd: Nhd, t) -> tuple[dict | None, str]:
    names = sql_names(t)
    town_geoms = nhd.towns.outlines(t["state"], list(t["towns"]))
    groups = defaultdict(list)
    for f in nhd.by_name(2, t["state"], names):
        if f.get("gnis_id") and name_score(t["words"], f.get("gnis_name")) >= 0.8:
            groups[("line", f["gnis_id"])].append(f)
    if wants_area(t) or not groups:
        for f in nhd.by_name(4, t["state"], names):
            if f.get("ftype") in LAKE_FTYPES and name_score(t["words"], f.get("gnis_name")) >= 0.8:
                groups[("wb", f.get("gnis_id") or f["comid"])].append(f)
    # inside the state, not just its box
    shape_ = nhd.states.shapes[t["state"]].buffer(0.01)
    groups = {k: v for k, v in groups.items() if any(f["_geom"] is not None and f["_geom"].intersects(shape_) for f in v)}
    if not groups:
        return None, "no NHD flowline or waterbody of that name in the state"

    def pick(k):
        fs = groups[k]
        f = fs[0]
        if k[0] == "line":
            return {"type": "line", "gnis_id": k[1], "gnis_name": f["gnis_name"], "comid": f["comid"]}
        return {"type": "wb", "comid": f["comid"], "gnis_id": f.get("gnis_id"), "gnis_name": f.get("gnis_name"),
                "ftype": f.get("ftype")}
    if town_geoms:
        tg = unary_union(town_geoms)
        scored = []
        for k, fs in groups.items():
            g = unary_union([f["_geom"] for f in fs if f["_geom"] is not None])
            scored.append((0.0 if g.intersects(tg) else geom_dist_m(g, tg), k))
        scored.sort()
        d0, k0 = scored[0]
        if d0 <= 3000 and (len(scored) == 1 or scored[1][0] > d0 or d0 == 0):
            return pick(k0), (f"GNIS name in {t['state']}, {'crossing' if d0 == 0 else f'{d0 / 1000:.1f} km from'} "
                              f"{', '.join(x for x, _ in t['towns'].most_common(2))}"
                              + (f" ({len(groups)} waters of that name in the state)" if len(groups) > 1 else ""))
        if len(groups) > 1:
            return None, (f"{len(groups)} NHD waters of that name in {t['state']}, none crossing or within 3 km of "
                          f"{', '.join(x for x, _ in t['towns'].most_common(2))}")
    if len(groups) == 1:
        k = next(iter(groups))
        return pick(k), f"the only NHD water of that name in {t['state']}"
    return None, f"{len(groups)} NHD waters of that name in {t['state']} and no town to choose one"


# ---------------------------------------------------------------- a state build: EPA's reach codes and NHDPlus ids

NLDI_NAV = "https://api.water.usgs.gov/nldi/linked-data/comid/{comid}/navigation/DM/flowlines"
REACH_FIELDS = "comid,gnis_id,gnis_name,reachcode,fcode,ftype,wbareacomid,wbarea_ftype,streamorder,hydroseq"
REACH_BATCH = 100
DOWNSTREAM_KM = 50          # how far down an unnamed flowline the first named water is looked for


def reach_index(nhd: "Nhd", codes, comids) -> dict:
    """{("code", reachcode): [flowline attributes], ("comid", comid): [flowline or waterbody attributes]} for EPA's NHD
    reach codes and NHDPlus ids (NHDPlus V2.1 network flowlines, layer 2; an id that is no network flowline is asked of
    the waterbodies, layer 4). Attributes only, in batches of REACH_BATCH (sorted, so a rerun asks the same batches and
    reads them from the cache)."""
    out: dict = defaultdict(list)
    codes = sorted({str(c) for c in codes if c and re.fullmatch(r"\d{14}", str(c))})
    ids = sorted({int(c) for c in comids if c and str(c).isdigit()})
    seen = set()
    for i in range(0, len(codes), REACH_BATCH):
        part = codes[i:i + REACH_BATCH]
        for f in arcgis(nhd.http, "reach2", 2, where="reachcode IN (" + ",".join(f"'{c}'" for c in part) + ")",
                        outFields=REACH_FIELDS, returnGeometry="false"):
            out[("code", str(f.get("reachcode")))].append(f)
            if f.get("comid"):
                out[("comid", int(f["comid"]))].append(f)
                seen.add(int(f["comid"]))
    left = [c for c in ids if c not in seen]
    for i in range(0, len(left), REACH_BATCH):
        part = left[i:i + REACH_BATCH]
        for f in arcgis(nhd.http, "reach2", 2, where=f"comid IN ({','.join(str(c) for c in part)})",
                        outFields=REACH_FIELDS, returnGeometry="false"):
            out[("comid", int(f["comid"]))].append(f)
            seen.add(int(f["comid"]))
    left = [c for c in left if c not in seen]
    for i in range(0, len(left), REACH_BATCH):
        part = left[i:i + REACH_BATCH]
        for f in arcgis(nhd.http, "reach4", 4, where=f"comid IN ({','.join(str(c) for c in part)})",
                        outFields=WB_FIELDS, returnGeometry="false"):
            out[("comid", int(f["comid"]))].append({**f, "_wb": True})
    return dict(out)


def target_reach_features(t, index: dict) -> list[dict]:
    """The flowlines (and waterbodies) of a target's EPA reach codes and NHDPlus ids, once each."""
    feats, seen = [], set()
    keys = [("comid", int(c)) for c in t.get("nhdplus_ids") or [] if str(c).isdigit()]
    keys += [("code", str(c)) for c in t.get("reach_ids") or []]
    for k in keys:
        for f in index.get(k) or []:
            fk = (bool(f.get("_wb")), f.get("comid"))
            if fk not in seen:
                seen.add(fk)
                feats.append(f)
    return feats


def epa_ids_of(f: dict) -> list[str]:
    return [x for x in (str(f.get("comid") or ""), str(f.get("reachcode") or "")) if x]


def resolve_reach(nhd: "Nhd", t, index: dict) -> tuple[list, str | None]:
    """([(feature key, choice, how, EPA ids)], reason): the NHDPlus features of the GNIS ids on EPA's reach codes and
    NHDPlus ids for the target that carry its name (no snapping; define_by 'reach'). A lake, pond, reservoir or bay name
    takes the waterbody the reach's artificial path runs through; a reach of another name (EPA indexes an outfall on a
    small tributary to it, under the permit's name of the larger water) is left to the point or name pass."""
    feats = target_reach_features(t, index)
    if not feats:
        return [], "EPA's reach codes and NHDPlus ids for it are not NHDPlus V2.1 network flowlines or waterbodies"
    tw = t["words"]
    area = wants_area(t)
    lines: dict = defaultdict(lambda: {"f": None, "score": 0.0, "ids": []})
    wbs: dict = defaultdict(lambda: {"f": None, "score": 0.0, "ids": []})
    for f in feats:
        if f.get("_wb"):
            sc = name_score(tw, f.get("gnis_name"))
            if sc >= 0.8:
                g = wbs[f.get("gnis_id") or f"comid{f['comid']}"]
                g["f"], g["score"] = g["f"] or f, max(g["score"], sc)
                g["ids"] += epa_ids_of(f)
            continue
        if f.get("gnis_id"):
            sc = name_score(tw, f.get("gnis_name"))
            if sc >= 0.7:
                g = lines[f["gnis_id"]]
                g["f"], g["score"] = g["f"] or f, max(g["score"], sc)
                g["ids"] += epa_ids_of(f)
        if area and f.get("wbareacomid") and f.get("wbarea_ftype") in LAKE_FTYPES:
            for w in nhd.by_comid(4, f["wbareacomid"]):
                sc = name_score(tw, w.get("gnis_name"))
                if sc >= 0.8:
                    g = wbs[w.get("gnis_id") or f"comid{w['comid']}"]
                    g["f"], g["score"] = g["f"] or w, max(g["score"], sc)
                    g["ids"] += epa_ids_of(f)
    out = []
    if wbs and (area or not lines):
        for gid, g in wbs.items():
            f = g["f"]
            c = {"type": "wb", "comid": f["comid"], "gnis_id": f.get("gnis_id"), "gnis_name": f.get("gnis_name"),
                 "ftype": f.get("ftype")}
            out.append((feature_key(t["state"], c), c, f"EPA's NHD reach/NHDPlus id {', '.join(sorted(set(g['ids']))[:4])}: "
                        f"waterbody '{f.get('gnis_name')}' ({'GNIS ' + str(f['gnis_id']) if f.get('gnis_id') else 'COMID ' + str(f['comid'])}); "
                        f"no snapping", sorted(set(g["ids"]))))
        return out, None
    if lines:
        best = max(g["score"] for g in lines.values())
        floor = 0.8 if best >= 0.8 else 0.7          # the qualifier-less name only when nothing better is on the reaches
        for gid, g in sorted(lines.items()):
            if g["score"] < floor:
                continue
            f = g["f"]
            c = {"type": "line", "gnis_id": gid, "gnis_name": f["gnis_name"], "comid": f["comid"]}
            out.append((feature_key(t["state"], c), c, f"EPA's NHD reach/NHDPlus id {', '.join(sorted(set(g['ids']))[:4])}: "
                        f"GNIS '{f['gnis_name']}' ({gid}); no snapping", sorted(set(g["ids"]))))
        return out, None
    names = sorted({f.get("gnis_name") for f in feats if f.get("gnis_name")})
    return [], ("EPA's reaches for it are " + (f"named {', '.join(names[:5])}, not '{t['name']}'" if names
                                               else "unnamed in NHDPlus V2.1"))


def downstream_name(nhd: "Nhd", comid: int) -> tuple[str | None, str | None]:
    """(GNIS name, GNIS id) of the first named NHDPlus flowline downstream of a COMID (NLDI downstream-main navigation
    up to DOWNSTREAM_KM, then the flowlines' names and hydrologic sequence from the MapServer, upstream first)."""
    d = nhd.http.get("nldi-nav", NLDI_NAV.format(comid=int(comid)), {"distance": str(DOWNSTREAM_KM)}, attempts=3)
    ids = []
    for f in (d or {}).get("features") or []:
        c = (f.get("properties") or {}).get("nhdplus_comid")
        if c and str(c).isdigit() and int(c) != int(comid):
            ids.append(int(c))
    if not ids:
        return None, None
    fs = []
    for i in range(0, len(ids), REACH_BATCH):
        fs += arcgis(nhd.http, "reach2", 2, where=f"comid IN ({','.join(str(c) for c in ids[i:i + REACH_BATCH])})",
                     outFields=REACH_FIELDS, returnGeometry="false")
    fs.sort(key=lambda f: -(f.get("hydroseq") or 0))          # hydroseq falls downstream
    for f in fs:
        if f.get("gnis_name"):
            return f["gnis_name"], f.get("gnis_id")
    return None, None


def resolve_unnamed(nhd: "Nhd", t, index: dict) -> tuple[list, str | None]:
    """([(feature key, choice, how, EPA ids)], reason) for an outfall whose permit names no water: the NHDPlus flowline
    of its EPA NHDPlus id or reach code (no snapping), else the flowline NLDI snaps its point to (comid/position); a named
    flowline gives that water's record, an unnamed one a record of that flowline alone, named for the first named water
    downstream ('Unnamed tributary to X')."""
    feats = [f for f in target_reach_features(t, index) if not f.get("_wb")]
    how = None
    if feats:
        f = feats[0]
        how = f"EPA's NHD reach/NHDPlus id {', '.join(epa_ids_of(f))}"
    elif t["points"]:
        lon, lat = next(iter(t["points"]))
        h = nhd.nldi(lon, lat)
        if not h:
            return [], "NLDI snapped the outfall's point to no NHDPlus flowline"
        if h["snap_m"] > NEAR_M:
            return [], f"the outfall's point lies {h['snap_m']} m from the NHDPlus flowline of its catchment"
        got = nhd.by_comid(2, h["comid"])
        if not got:
            return [], f"NLDI's COMID {h['comid']} is no NHDPlus V2.1 network flowline"
        f = got[0]
        how = f"NLDI {h['via']} COMID {h['comid']} ({h['snap_m']} m)"
    else:
        return [], "no receiving-water name, no point and no NHD reach in EPA's records for this outfall"
    if f.get("gnis_id"):
        c = {"type": "line", "gnis_id": f["gnis_id"], "gnis_name": f["gnis_name"], "comid": f["comid"]}
        return [(feature_key(t["state"], c), c, f"{how}: GNIS '{f['gnis_name']}' ({f['gnis_id']})", epa_ids_of(f))], None
    down, down_id = downstream_name(nhd, int(f["comid"]))
    c = {"type": "comid-line", "comid": int(f["comid"]), "gnis_id": None, "gnis_name": unnamed_name(down),
         "downstream": down, "downstream_gnis_id": down_id}
    return [(("line", t["state"], f"comid{int(f['comid'])}"), c,
             f"{how}: an unnamed NHDPlus flowline" + (f", tributary to {down} (NLDI downstream)" if down else
                                                     " with no named water within 50 km downstream"),
             epa_ids_of(f))], None


HR_NEAR_DEG = 0.03          # the box around a point the high-resolution flowlines of a name are asked in (~3 km)
HR_SPAN_DEG = 0.5           # the box around the points a high-resolution water's flowlines are gathered in (~50 km)
HR_FIELDS = "permanent_identifier,gnis_id,gnis_name,reachcode,fcode,ftype,lengthkm"


def resolve_hr(nhd: "Nhd", t) -> tuple[dict | None, str]:
    """(choice, how) from the USGS NHD high-resolution flowlines (layer 6 of hydro.nationalmap.gov's NHD MapServer) for
    a state build's target NHDPlus V2.1 does not name: the flowline of the target's name within HR_NEAR_DEG of one of
    its points (most reported first), by GNIS name; the nearest when several. The medium-resolution V2.1 network leaves
    out many small named streams and canals (Florida, 2026-11-04: Brooker Creek, Possum Creek)."""
    names = sql_names(t)
    where = "UPPER(gnis_name) IN (" + ",".join(f"'{n}'" for n in names) + ")"
    for lon, lat in cluster_points(t["points"]):
        env = f"{lon - HR_NEAR_DEG},{lat - HR_NEAR_DEG},{lon + HR_NEAR_DEG},{lat + HR_NEAR_DEG}"
        fs = arcgis(nhd.http, "nhd-hr-near", HR_FLOWLINES, service=NHD_HR, where=where, geometry=env,
                    geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                    outFields=HR_FIELDS, maxAllowableOffset="0.0001")
        cands = [(dist_m(f["_geom"], lon, lat), f) for f in fs if f.get("gnis_id") and f["_geom"] is not None
                 and name_score(t["words"], f.get("gnis_name")) >= 0.8]
        if cands:
            d, f = min(cands, key=lambda x: x[0])
            return ({"type": "hr-line", "gnis_id": str(int(f["gnis_id"])), "gnis_name": f["gnis_name"],
                     "box": [round(lon - HR_SPAN_DEG, 4), round(lat - HR_SPAN_DEG, 4), round(lon + HR_SPAN_DEG, 4),
                             round(lat + HR_SPAN_DEG, 4)]},
                    f"NHD high resolution: flowline named '{f['gnis_name']}' (GNIS {int(f['gnis_id'])}) {d:.0f} m from "
                    f"the point ({lat:.5f}, {lon:.5f})")
    return None, "no NHD high-resolution flowline of that name within 3 km of the points"


def build_hr_feature(nhd: "Nhd", state: str, choice: dict) -> dict | None:
    """A record from the NHD high-resolution flowlines of a GNIS id within the choice's box (resolve_hr)."""
    gid = str(int(choice["gnis_id"]))
    fs = arcgis(nhd.http, "nhd-hr", HR_FLOWLINES, service=NHD_HR, where=f"gnis_id IN ('{gid.zfill(8)}','{gid}')",
                geometry=",".join(str(x) for x in choice["box"]), geometryType="esriGeometryEnvelope", inSR="4326",
                spatialRel="esriSpatialRelIntersects", outFields=HR_FIELDS, maxAllowableOffset="0.00005")
    geom = to_geom_line(fs, state, nhd.states)
    if not fs or geom is None or geom.is_empty:
        return None
    fcodes = sorted({f.get("fcode") for f in fs if f.get("fcode")})
    name = gnis_display(choice["gnis_name"])
    b = geom.bounds
    return {"name": name, "kind": kind_of(name, "line", fcodes=fcodes), "state": state, "towns": nhd.towns.along(state, geom),
            "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)], "wikidata": None, "charted": None,
            "length_km": round(WX.length_km(geom), 2), "area_km2": None, "launches": [], "advisories": [], "aliases": [],
            "source": "nhd", "gnis_id": gid, "comids": [], "nhd_fcodes": fcodes, "fetched_at": now_iso(),
            "towns_from": TOWNS_FROM(state),
            "note": (f"USGS National Hydrography Dataset, high resolution (The National Map NHD MapServer, layer 6 "
                     f"'Flowline - Large Scale'): {len(fs)} flowlines with GNIS id {gid} within "
                     f"{HR_SPAN_DEG} degrees of the outfall's point, cut to the state, merged and simplified to ~10 m; "
                     f"NHDPlus V2.1 has no flowline of that name"),
            "_geom": geom}


# ---------------------------------------------------------------- building records

def kind_of(name: str, typ: str, ftype=None, fcodes=(), order=0) -> str:
    ws = words(name)
    last = [w for w in ws if w in KIND_WORDS][-1:]
    lw = last[0] if last else None
    if typ == "wb":
        if lw in ("pond", "ponds", "millpond"):
            return "pond"
        if lw in ("lake", "lakes"):
            return "lake"
        if lw == "reservoir":
            return "reservoir"
        if ftype == 493 or (lw in ("bay", "harbor", "cove", "inlet", "sound", "lagoon") and ftype not in (390, 436)):
            return "bay"
        return LAKE_FTYPES.get(ftype, "lake") if ftype != 493 else "bay"
    if any(336 <= (c or 0) // 100 <= 336 for c in fcodes) or lw in ("canal", "ditch"):
        return "canal"
    if lw == "river" or (order or 0) >= 5:
        return "river"
    return "stream"


def to_geom_line(features, state, states: States):
    geoms = [f["_geom"] for f in features if f["_geom"] is not None]
    if not geoms:
        return None
    g = states.clip(unary_union(geoms), state)
    ml = WX.as_multiline(g)
    if ml is None:
        return None
    ml = WX.as_multiline(linemerge(ml))
    g = WX.simplify(ml, SIMPLIFY_M)
    return WX.as_multiline(g)


def to_geom_area(features, state, states: States):
    geoms = [f["_geom"] for f in features if f["_geom"] is not None]
    if not geoms:
        return None
    g = unary_union([x if x.is_valid else x.buffer(0) for x in geoms])
    g = states.clip(g, state)
    g = WX.as_areas(g)
    if g is None or g.is_empty:
        return None
    return WX.as_areas(WX.simplify(g, SIMPLIFY_M))


def feature_key(state, choice) -> tuple:
    if choice["type"] == "hr-line":
        return ("line", state, str(choice["gnis_id"]))
    if choice["type"] == "comid-line":
        return ("line", state, f"comid{int(choice['comid'])}")
    if choice["type"] == "line":
        return ("line", state, choice["gnis_id"])
    return ("wb", state, choice.get("gnis_id") or f"comid{choice['comid']}")


def build_feature(nhd: Nhd, state: str, choice: dict) -> dict | None:
    """A record without slug: geometry, name, kind, towns, comids."""
    if choice["type"] == "hr-line":
        return build_hr_feature(nhd, state, choice)
    if choice["type"] == "comid-line":         # an unnamed flowline at an outfall (a state build's unnamed outfalls)
        fs = nhd.by_comid(2, choice["comid"])
        geom = to_geom_line(fs, state, nhd.states)
        if geom is None or geom.is_empty:
            return None
        fcodes = sorted({f.get("fcode") for f in fs if f.get("fcode")})
        kind = "canal" if any(336 <= (c or 0) // 100 <= 336 for c in fcodes) else "stream"
        size = {"length_km": round(WX.length_km(geom), 2), "area_km2": None}
        note = (f"NHDPlus V2.1: the unnamed network flowline COMID {choice['comid']}"
                + (f", upstream of {choice['downstream']} (GNIS {choice.get('downstream_gnis_id')}, the first named water "
                   f"downstream by NLDI navigation)" if choice.get("downstream") else "")
                + ", cut to the state and simplified to ~10 m")
    elif choice["type"] == "line":
        fs = nhd.lines_by_gnis(state, choice["gnis_id"])
        geom = to_geom_line(fs, state, nhd.states)
        if geom is None or geom.is_empty:
            return None
        fcodes = sorted({f.get("fcode") for f in fs if f.get("fcode")})
        order = max((f.get("streamorder") or 0 for f in fs), default=0)
        kind = kind_of(choice["gnis_name"], "line", fcodes=fcodes, order=order)
        size = {"length_km": round(WX.length_km(geom), 2), "area_km2": None}
        note = (f"NHDPlus V2.1: {len(fs)} network flowlines with GNIS id {choice['gnis_id']} in {state}'s box, cut to the "
                f"state, merged and simplified to ~10 m")
    else:
        if choice.get("gnis_id"):
            first = nhd.by_comid(4, choice["comid"])
            if not first or first[0]["_geom"] is None:
                return None
            b = first[0]["_geom"].bounds
            env = f"{b[0] - 0.05},{b[1] - 0.05},{b[2] + 0.05},{b[3] + 0.05}"
            fs = [f for f in nhd.wbs_by_gnis(state, choice["gnis_id"], env) if f.get("ftype") in LAKE_FTYPES] or first
        else:
            fs = nhd.by_comid(4, choice["comid"])
        geom = to_geom_area(fs, state, nhd.states)
        if geom is None or geom.is_empty:
            return None
        fcodes = sorted({f.get("fcode") for f in fs if f.get("fcode")})
        kind = kind_of(choice.get("gnis_name") or "", "wb", ftype=choice.get("ftype"))
        size = {"length_km": None, "area_km2": round(WX.area_km2(geom), 3)}
        note = (f"NHDPlus V2.1 waterbody {'GNIS id ' + choice['gnis_id'] if choice.get('gnis_id') else 'COMID ' + str(choice['comid'])}"
                f" ({len(fs)} polygon{'s' if len(fs) != 1 else ''}), cut to the state, simplified to ~10 m")
    towns = nhd.towns.along(state, geom)
    b = geom.bounds
    return {
        "name": gnis_display(choice.get("gnis_name")), "kind": kind, "state": state, "towns": towns,
        "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)],
        "wikidata": None, "charted": None, **size, "launches": [], "advisories": [], "aliases": [],
        "source": "nhd", "gnis_id": choice.get("gnis_id"),
        "comids": sorted({int(f["comid"]) for f in fs if f.get("comid")}), "nhd_fcodes": fcodes,
        "fetched_at": now_iso(), "towns_from": TOWNS_FROM(state),
        "note": note, "_geom": geom}


def TOWNS_FROM(state: str) -> str:
    return ("Census 2020 places (incorporated and designated) crossed (TIGERweb)" if state in PLACE_STATES
            else "Census 2020 county subdivisions crossed (TIGERweb)")


def same_named_existing(existing: dict, state: str, name: str) -> list[str]:
    n = S.norm_name(name or "")
    out = []
    for slug, w in existing.items():
        if w.get("state") != state:
            continue
        if S.norm_name(w.get("name") or "") == n or n in {S.norm_name(a) for a in w.get("aliases") or []}:
            out.append(slug)
    return out


def to_m_geom(g, lat0):
    return WX.to_m(g, lat0)[0]


def overlap_with_existing(rec, existing, slugs):
    """(slug, remainder geometry or None): the existing same-named record the NHD water lies along, and
    the part of the NHD water more than SAME_WATER_M from it."""
    g = rec["_geom"]
    lat0 = g.centroid.y
    gm = to_m_geom(g, lat0)
    for s in slugs:
        eg = S.water_geometry(s, existing)
        if eg is None:
            continue
        em = to_m_geom(eg, lat0)
        if gm.distance(em) > SAME_WATER_M:
            continue
        rest_m = gm.difference(em.buffer(SAME_WATER_M))
        k = np.array([111_320.0 * math.cos(math.radians(lat0)), 110_574.0])
        rest = shapely.transform(rest_m, lambda c: c / k) if not rest_m.is_empty else None
        return s, rest
    return None, None


# ---------------------------------------------------------------- an NHD water that is an openboatlaunch record

ALIAS_NOT_A_NAME = re.compile(r"/|\b(to|in|into|basin|and)\b", re.I)
SAME_BOX_SHARE = 0.5       # this share of the NHD feature inside the record's box (or of the box under the feature's)


def same_water_by_box(geom, w: dict, towns=()) -> tuple[bool | None, str]:
    """Whether an NHD feature (geom, its towns) is the water of a same-named record w whose outline is not on this
    machine (an openboatlaunch record without its out/water file: a cloud session or a runner without the sibling
    snapshot), by w's bounding box, which holds the whole water: (False, why) when the feature lies more than
    SAME_WATER_M from the box (sure: another water of that name); (True, why) when it touches the box and either
    SAME_BOX_SHARE of the feature lies in the box, or that share of the box lies under the feature's own box (a record
    that covers only a stretch of the river), or the two name a town in common; (None, why) otherwise (left as two
    records). With the outline on disk overlap_with_existing decides instead."""
    b = w.get("bbox")
    if geom is None:
        return None, "no NHD geometry"
    if not b or len(b) != 4:
        common = sorted({town_key(t) for t in towns or []} & {town_key(t) for t in w.get("towns") or []})
        if common and w.get("kind") not in S.WIDE_KINDS:
            return True, f"same name; {w.get('slug')} has no bounding box and both name {', '.join(common[:3])}"
        return None, f"{w.get('slug')} has no bounding box" + ("" if common else " and no town in common")
    bx = sbox(*b)
    d = geom_dist_m(geom, bx)
    if d > SAME_WATER_M:
        return False, f"the NHD feature lies {d / 1000:.1f} km outside {w.get('slug')}'s bounding box"
    lat0 = geom.centroid.y
    gm = to_m_geom(geom, lat0)
    bm = to_m_geom(bx, lat0)
    pad = bm.buffer(SAME_WATER_M)
    if gm.area > 0:
        share = gm.intersection(pad).area / gm.area
    else:
        share = gm.intersection(pad).length / gm.length if gm.length > 0 else 0.0
    under = to_m_geom(sbox(*geom.bounds), lat0).buffer(SAME_WATER_M)
    cover = bm.intersection(under).area / bm.area if bm.area > 0 else 0.0
    common = sorted({town_key(t) for t in towns or []} & {town_key(t) for t in w.get("towns") or []})
    why = (f"same name; {share:.0%} of the NHD feature lies within {SAME_WATER_M} m of {w.get('slug')}'s bounding box, "
           f"which the feature's own box covers {cover:.0%} of" + (f"; both name {', '.join(common[:3])}" if common else ""))
    if share >= SAME_BOX_SHARE or cover >= SAME_BOX_SHARE or common:
        return True, why
    return None, why


def existing_same_water(geom, towns, existing: dict, slugs) -> tuple[str | None, str | None]:
    """(slug, why): the same-named existing record (slugs) the NHD feature is, judged by its outline within
    SAME_WATER_M when on disk, else by its bounding box (same_water_by_box); (None, None) when none is."""
    for s in slugs:
        eg = S.water_geometry(s, existing)
        if eg is not None:
            d = geom_dist_m(geom, eg)
            if d <= SAME_WATER_M:
                return s, f"same name; the NHD feature lies {int(round(d))} m from {s}'s outline"
            continue
        same, why = same_water_by_box(geom, existing[s], towns)
        if same:
            return s, why
    return None, None


def resolve_existing_duplicates(doc: dict, existing: dict, states, when: str | None = None) -> tuple[dict, list[dict], dict]:
    """The state build's records that duplicate an openboatlaunch record now on file (2026-11-04: the NC, GA and FL
    records were built while openboatlaunch's extracts for those states were absent, so 'record' rows and the
    names openboatlaunch carries were built from NHD). For every record of `states` in doc (data/waters-nhd.json):
      - a same-named existing record that is the same water (existing_same_water) is the public one: the NHD record
        is dropped, the target rows' slugs, reach_slugs and the outfall rows of the next outfall_waters run point to
        the existing slug, each such row says so in `notes`, and the NHD record's name aliases the existing record
        lacks are returned for data/water-aliases.json;
      - an NHD record whose slug is an existing record of another water (the NHD record was shadowed: status.load_waters
        keeps the first record of a slug, openboatlaunch's) takes <name>-<town>-<st> (assign_slugs' rule for the
        second water of a name), and its target rows follow.
    Returns (the new doc, the actions, {existing slug: [aliases]}). Nothing is fetched."""
    states = {x.upper() for x in states}
    when = when or now_iso()[:10]
    waters = list(doc.get("waters") or [])
    taken = set(existing) | {w["slug"] for w in waters if w.get("slug")}
    moved: dict[str, tuple[str, str, str]] = {}      # NHD slug -> (new slug, action, why)
    aliases: dict[str, list[str]] = {}
    keep = []
    by_slug_rows = defaultdict(list)
    for t in doc.get("targets") or []:
        for x in t.get("slugs") or []:
            by_slug_rows[x].append(t)
    for w in waters:
        if w.get("state") not in states or not w.get("geometry") or w.get("covers_part_of"):
            keep.append(w)
            continue
        g = shape(w["geometry"])
        same = same_named_existing(existing, w["state"], w.get("name"))
        if w["slug"] in existing and w["slug"] not in same:
            same.append(w["slug"])
        s, why = existing_same_water(g, w.get("towns") or [], existing, same)
        if s:
            ew = existing[s]
            have = {S.norm_name(ew.get("name") or "")} | {S.norm_name(a) for a in ew.get("aliases") or []}
            # a name the NHD record went by (EPA's spelling: 'OCMULGEE RV', 'Ocmuglee River'), not a whole text that
            # names a path or a basin ('ETOWAH RV/COOSA RV BASIN', 'BRIER CRK TO SAVANNAH RIVER')
            extra = [a for a in [w.get("name")] + list(w.get("aliases") or [])
                     if a and S.norm_name(a) not in have and not ALIAS_NOT_A_NAME.search(a)]
            if extra:
                aliases[s] = list(dict.fromkeys(aliases.get(s, []) + extra))
            moved[w["slug"]] = (s, "dropped", why)
            continue
        if w["slug"] in existing:
            towns = list(w.get("towns") or [])
            for t in by_slug_rows.get(w["slug"], []):
                towns += [x for x in t.get("towns") or [] if x not in towns]
            new = None
            for tw in towns:
                c = f"{slugify(w['name'])}-{slugify(tw)}-{w['state'].lower()}"
                if c not in taken:
                    new = c
                    break
            if new is None:
                new = f"{slugify(w['name'])}-{slugify(str(w.get('gnis_id') or (w.get('comids') or ['x'])[0]))}-{w['state'].lower()}"
            taken.add(new)
            _, why = same_water_by_box(g, existing[w["slug"]], w.get("towns") or []) \
                if S.water_geometry(w["slug"], existing) is None else (None, "its outline lies elsewhere")
            moved[w["slug"]] = (new, "renamed", f"{w['slug']} is openboatlaunch's record of another {w.get('name')} "
                                                f"({why})")
            w = {**w, "slug": new}
        keep.append(w)
    actions = []
    for t in doc.get("targets") or []:
        if t.get("state") not in states:
            continue
        hits = [x for x in t.get("slugs") or [] if x in moved]
        if not hits:
            continue
        t["slugs"] = list(dict.fromkeys(moved[x][0] if x in moved else x for x in t["slugs"]))
        if t.get("reach_slugs"):
            t["reach_slugs"] = {k: moved[v][0] if v in moved else v for k, v in t["reach_slugs"].items()}
        notes = list(t.get("notes") or [])
        for x in hits:
            new, act, why = moved[x]
            notes.append(f"{when}: the NHD record {x} was dropped: openboatlaunch's {new} is this water ({why})"
                         if act == "dropped" else
                         f"{when}: the NHD record {x} was renamed {new}: {why}")
        t["notes"] = list(dict.fromkeys(notes))
    for old, (new, act, why) in sorted(moved.items()):
        actions.append({"slug": old, "action": act, "to": new, "why": why})
    # a row the build left without a record whose name an existing record now carries (openboatlaunch's extract, or a
    # hand alias in data/water-aliases.json: 'Lake Lanier' at Buford), the only one of that name in the state, and
    # reaching one of the operators' towns by its town list: that record, and the row says so
    for t in doc.get("targets") or []:
        if t.get("state") not in states or t.get("slugs") or not t.get("name"):
            continue
        cands = same_named_existing(existing, t["state"], t["name"])
        if len(cands) != 1:
            continue
        s = cands[0]
        common = sorted({town_key(x) for x in t.get("towns") or []}
                        & {town_key(x) for x in existing[s].get("towns") or []})
        if not common:
            continue
        why = (f"{existing[s].get('name')} ({s}) carries the name '{t['name']}' and reaches the operators' town"
               f"{'s' if len(common) > 1 else ''} ({', '.join(common[:3])})")
        t["slugs"] = [s]
        t["reason"] = None
        t["notes"] = list(dict.fromkeys(list(t.get("notes") or []) + [f"{when}: openboatlaunch's record: {why}"]))
        actions.append({"slug": None, "action": "mapped", "to": s, "row": t["name"], "why": why})
    out = {**doc, "waters": sorted(keep, key=lambda r: r.get("slug") or ""), "count": len(keep)}
    return out, actions, aliases


def target_point_towns(t, towns: Towns, geom=None) -> tuple[Counter, int]:
    """(towns of the target's points, number of reports): only the points within NEAR_M of geom
    when given (a target naming two waters of one name gives each its own towns); the listed
    towns follow with no weight."""
    c, n_near = Counter(), 0
    for (lon, lat), n in t["points"].items():
        if geom is not None and dist_m(geom, lon, lat) > NEAR_M:
            continue
        n_near += n
        tw = towns.at(t["state"], lon, lat)
        if tw:
            c[tw] += n
    for tw in t["towns"]:
        name = towns.canonical(t["state"], tw)
        if name:
            c[name] += 0
    return c, (n_near if t["points"] else t["events"] + t["outfalls"])


def aliases_for(rec_name: str, t, state, existing_like: dict) -> list[str]:
    """Target texts the status resolver would not match to a water called rec_name."""
    out = []
    n = S.norm_name(rec_name)
    for text in list(t["names"]) + list(t["texts"]):
        clean = re.sub(r"\(.*?\)", " ", text).strip()
        clean = re.sub(r"\s+", " ", clean)
        if not clean or len(clean) > 60 or len(clean.split()) > 6 or re.search(r"[,;:.!?]\s", clean + " ") \
                or not_water(clean):
            continue
        tn = S.norm_name(clean)
        if f" {n} " in f" {tn} ":
            continue
        words_ = n.split()
        if len(words_) >= 2 and words_[-1] in S.KIND_WORDS and tn == " ".join(words_[:-1]) and len(tn) >= 6:
            continue        # the stem rule matches it ('Winooski' for the Winooski River)
        if t["point_mode"] and not has_kind(words(clean)):
            continue        # a beach or camp name is not a name of the lake
        out.append(clean)
    return list(dict.fromkeys(out))


def previous_slugs(path=None) -> dict:
    """{water_identity: slug} of the records in the file on disk (assign_slugs keeps them)."""
    try:
        d = read_json(path or OUT) or {}
    except ValueError:
        return {}
    out = {}
    for r in d.get("waters") or []:
        k = water_identity(r) if isinstance(r, dict) and r.get("slug") else None
        if k is not None:
            out.setdefault(k, r["slug"])
    return out


def previous_rows(path=None) -> list[tuple]:
    """[(slug, state, normalised name, water_identity, geometry)] of the records in the file on disk."""
    try:
        d = read_json(path or OUT) or {}
    except ValueError:
        return []
    out = []
    for r in d.get("waters") or []:
        if isinstance(r, dict) and r.get("slug") and r.get("geometry"):
            try:
                g = shape(r["geometry"])
            except Exception:
                continue
            out.append((r["slug"], r.get("state"), S.norm_name(r.get("name") or ""), water_identity(r), g))
    return out


def assign_slugs(recs: list[dict], existing: dict, previous: dict | None = None, kept: list | None = None) -> None:
    """Slugs: <name>-<st> for the record of a name with the most reports, <name>-<town>-<st> for the others
    and when the name is already a record of the state. previous ({water_identity: slug}, previous_slugs()):
    a feature keeps the slug it had in the file when that slug is still free (2026-11-03: outfall registries
    store these slugs, and a second Mill Creek with more reports must not take the first one's slug). kept
    (previous_rows()): the file's records this run does not rebuild stay in the file (merge_waters), so their
    slugs are not free, unless this run built the same water from another source (a record of that name within
    SAME_WATER_M of it: NHDPlus naming at another place a Bull Run that only OSM had named), which then takes it
    (2026-11-03: a Lick Run found near Lynchburg took the slug of Roanoke's and the merge dropped Roanoke's)."""
    taken = set(existing)
    sticky = {}
    run_ids = {water_identity(r) for r in recs}
    for slug, st, n, k, g in kept or []:
        if k is not None and k in run_ids:
            continue
        same = [r for r in recs if r["state"] == st and S.norm_name(r["name"]) == n and r.get("_geom") is not None]
        heir = next((r for r in same if id(r) not in sticky and geom_dist_m(r["_geom"], g) <= SAME_WATER_M), None)
        if heir is not None and slug not in taken and slug.startswith(f"{slugify(heir['name'])}-"):
            sticky[id(heir)] = slug
        taken.add(slug)
    taken -= set(sticky.values())
    for r in sorted(recs, key=lambda r: (-r["_weight"], r.get("gnis_id") or "")):
        k = water_identity(r)
        s = (previous or {}).get(k) if k is not None else None
        if id(r) not in sticky and s and s not in taken and s not in sticky.values() \
                and s.startswith(f"{slugify(r['name'])}-"):
            sticky[id(r)] = s
    taken |= set(sticky.values())
    by_name = defaultdict(list)
    for r in recs:
        by_name[(r["state"], S.norm_name(r["name"]))].append(r)
    for (state, n), group in sorted(by_name.items()):
        group.sort(key=lambda r: (-r["_weight"], r.get("gnis_id") or ""))
        exists = bool(same_named_existing(existing, state, group[0]["name"]))
        first = next((r for r in group if id(r) not in sticky), None)
        for r in group:
            if id(r) in sticky:
                r["slug"] = sticky[id(r)]
                continue
            base = f"{slugify(r['name'])}-{state.lower()}"
            slug = None
            if r is first and not exists and base not in taken:
                slug = base
            else:
                for tw in [x for x, _ in r["_slug_towns"].most_common()] + list(r["towns"]):
                    s = f"{slugify(r['name'])}-{slugify(tw)}-{state.lower()}"
                    if s not in taken:
                        slug = s
                        break
            if slug is None:
                slug = f"{slugify(r['name'])}-{slugify(str(r.get('gnis_id') or r['comids'][0]))}-{state.lower()}"
            taken.add(slug)
            r["slug"] = slug


def public_record(r: dict) -> dict:
    keys = ["slug", "name", "kind", "state", "towns", "bbox", "wikidata", "charted", "area_km2", "length_km",
            "launches", "advisories", "aliases", "source", "gnis_id", "comids", "nhd_fcodes", "fetched_at",
            "towns_from", "note"]
    out = {k: r.get(k) for k in keys}
    for k in ("fallback_for", "osm", "osm_timestamp", "covers_part_of", "hand", "reachcodes"):
        if r.get(k) is not None:
            out[k] = r[k]
    out["targets"] = r.get("_targets_n", 0)
    out["geometry"] = mapping(r["_geom"])
    return out


def validate(recs: list[dict], states: States) -> list[str]:
    out = WX.validate([{"slug": r["slug"], "state": r["state"], "geometry": mapping(r["_geom"])} for r in recs], states)
    seen = Counter(r["slug"] for r in recs)
    out += [f"duplicate slug {s}" for s, n in seen.items() if n > 1]
    ids = defaultdict(list)                 # one feature, one record (water_identity; covers_part_of rows aside)
    for r in recs:
        k = water_identity(r)
        if k is not None:
            ids[k].append(r["slug"])
    out += [f"one feature in {len(v)} records ({k[0]} {k[1]} {k[2]}): {', '.join(v)}" for k, v in ids.items() if len(v) > 1]
    return out


class WriteRefused(Exception):
    """A write that would lose records of the file on disk (write_output)."""


def shown(path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def water_identity(r: dict) -> tuple | None:
    """The feature a row stands for, whatever its slug (review 2026-11-03 P2-1): (state, "gnis", GNIS id), else
    (state, "comids", its NHDPlus COMIDs), else (state, "osm", its OSM ways); None for a row that covers part of
    another (covers_part_of: a remainder shares its river's GNIS id) or carries none of these."""
    if r.get("covers_part_of"):
        return None
    st = r.get("state")
    if r.get("gnis_id"):
        return (st, "gnis", str(r["gnis_id"]))
    if r.get("comids"):
        return (st, "comids", tuple(sorted(int(c) for c in r["comids"])))
    if r.get("osm"):
        return (st, "osm", tuple(sorted(str(w) for w in r["osm"])))
    return None


def _newer(a: dict, b: dict) -> bool:
    """Whether file row a is newer than file row b (fetched later; then mapped by more targets; then the slug)."""
    return (str(a.get("fetched_at") or ""), a.get("targets") or 0, a["slug"]) > \
        (str(b.get("fetched_at") or ""), b.get("targets") or 0, b["slug"])


def _absorb(row: dict, gone: list[dict]) -> dict:
    """row with the slugs (slug_aliases) and name aliases of the rows it replaces under another slug."""
    if not gone:
        return row
    slugs = list(row.get("slug_aliases") or [])
    names = list(row.get("aliases") or [])
    for g in gone:
        for s in [g["slug"], *(g.get("slug_aliases") or [])]:
            if s != row["slug"] and s not in slugs:
                slugs.append(s)
        names += [a for a in g.get("aliases") or [] if a not in names]
    return {**row, "aliases": names, "slug_aliases": slugs}


def merge_waters(old: list[dict], new: list[dict]) -> list[dict]:
    """The rows of the file on disk with this run's rows over them (by slug), sorted by slug: a slug in both
    takes the new row, one only in the file stays as it is. The new row keeps the file row's aliases (the
    union, the file's first): a re-resolved record does not lose the aliases it had (hand ones belong in
    data/water-aliases.json, but an alias added to a record before that file existed must not vanish).
    One feature is one row (water_identity, review 2026-11-03 P2-1): a file row that a row of this run gives
    under another slug (a checkpoint's slug before its town changed, an earlier run's) is dropped, and a file
    row repeated in the file under another slug gives way to the newer one (_newer); the row kept lists the
    slugs it replaced in `slug_aliases` (build/status.py follows them) and takes their name aliases."""
    by_slug = {r["slug"]: r for r in old if r.get("slug")}
    run_slug = {}
    for r in new:
        k = water_identity(r) if r.get("slug") else None
        if k is not None:
            run_slug.setdefault(k, r["slug"])
    gone: dict[str, list[dict]] = defaultdict(list)          # kept slug -> the file rows it replaces
    for slug, r in list(by_slug.items()):
        k = water_identity(r)
        if k in run_slug and run_slug[k] != slug:
            gone[run_slug[k]].append(by_slug.pop(slug))
    groups: dict[tuple, list[str]] = defaultdict(list)
    for slug, r in by_slug.items():
        k = water_identity(r)
        if k is not None and k not in run_slug:
            groups[k].append(slug)
    for slugs in groups.values():
        if len(slugs) > 1:
            best = slugs[0]
            for s in slugs[1:]:
                if _newer(by_slug[s], by_slug[best]):
                    best = s
            gone[best] += [by_slug.pop(s) for s in slugs if s != best]
    for slug in list(by_slug):
        if gone.get(slug):
            by_slug[slug] = _absorb(by_slug[slug], gone.pop(slug))
    for r in new:
        if not r.get("slug"):
            continue
        prev = by_slug.get(r["slug"]) or {}
        kept = prev.get("aliases") or []
        if kept:
            have = list(kept)
            have += [a for a in r.get("aliases") or [] if a not in have]
            r = {**r, "aliases": have}
        if prev.get("slug_aliases"):
            r = {**r, "slug_aliases": list(prev["slug_aliases"])}
        by_slug[r["slug"]] = _absorb(r, gone.pop(r["slug"], []))
    return [by_slug[k] for k in sorted(by_slug)]


def target_key(row: dict) -> tuple:
    """A target row's identity in the file: state and name; a site (no name) by its first text."""
    if row.get("from") == "reports":      # a report name's row (--names) never stands for the national list's row
        return (row.get("state"), row.get("name"), "reports")
    if row.get("name"):
        return (row.get("state"), row["name"])
    return (row.get("state"), None, (row.get("texts") or [""])[0])


NOT_REACHED = "not reached this run"


def merge_targets(old: list[dict], new: list[dict]) -> list[dict]:
    """The file's target rows with this run's over them, the file's order kept (new targets at the end). A row this run
    did not reach (its budget ran out first: no slugs, reason 'not reached this run') does not replace the file's row
    for that target: the file's row keeps its slugs until a run resolves the target again."""
    by_key = {target_key(r): r for r in old}
    for r in new:
        k = target_key(r)
        if k in by_key and not r.get("slugs") and str(r.get("reason") or "").startswith(NOT_REACHED):
            continue
        by_key[k] = r
    return list(by_key.values())


def merge_targets_scoped(old: list[dict], new: list[dict], scope, rows_from=None) -> list[dict]:
    """A state build's target rows: the file's rows of every other state exactly as they are (site rows of the same
    text included), the scope states' rows merged with this run's over them (merge_targets). rows_from ('reports', a
    --names run): only the scope states' rows of that origin are merged; the state build's own rows stay exactly."""
    def mine(r):
        return r.get("state") in scope and (rows_from is None or r.get("from") == rows_from)
    keep = [r for r in old if not mine(r)]
    return keep + merge_targets([r for r in old if mine(r)], new)


def describe_write(info: dict) -> str:
    if info["mode"] == "rebuild":
        return (f"--rebuild: replaced the {info['existing_records']} records of the existing file with this run's "
                f"{info['run_records']} ({info['dropped']} existing records dropped, {info['added']} new)")
    return (f"merged into the {info['existing_records']} records of the existing file: {info['replaced']} replaced by "
            f"this run's version, {info['added']} new, {info['kept']} not visited this run kept as they were "
            f"-> {info['written']} records")


def write_output(recs, targets_out, skipped, problems, partial: bool, stats=None, keep=(),
                 final: bool = False, rebuild: bool = False, scope_states=None, rows_from=None) -> dict:
    """Write OUT, merged into the file on disk (merge_waters, merge_targets when partial): a checkpoint
    (final=False) or a partial final write (--limit) never drops a record. The final write of a full run
    (final=True) with fewer records than the file holds still merges (nothing is dropped) and notes it in
    stats.write.warning; rebuild replaces the file with this run's records. Returns what was done
    ({"mode": "merge" | "rebuild", existing_records, run_records, replaced, added, kept, dropped, written}).
    keep: rows already in public form (an --osm-only run keeps the last full run's records).
    scope_states: a state build (--state): the run covers only these states, so the file's target rows, skipped texts and
    problems of every other state stay (this run's rows over them), the file's partial flag and statistics stay, and
    stats (when final) is this run's statistics per state, written under stats.state_builds.<ST>.
    rows_from ('reports': a --names run, with scope_states): only the state's report-name rows are merged (the state
    build's rows stay exactly) and the statistics go under stats.state_builds.<ST>.report_names, the rest kept."""
    done = [r for r in recs if r.get("slug")]
    run_rows = list(keep) + [public_record(r) for r in done]
    try:
        prev = read_json(OUT) or {}
    except ValueError as ex:
        raise WriteRefused(f"{shown(OUT)} exists but cannot be read ({ex}); it was left as it is") from ex
    old_rows = prev.get("waters") or []
    old_slugs = {r["slug"] for r in old_rows if r.get("slug")}
    run_slugs = {r["slug"] for r in run_rows if r.get("slug")}
    replace = final and rebuild
    # A full run that resolves fewer records than the file holds (failed requests, or the OSM time budget
    # leaving names for the next run) merges like any other: the file never loses a record. It is noted in
    # the summary (stats.write.warning) rather than refused; only --rebuild drops records, on purpose.
    warning = None
    if final and not partial and not rebuild and not scope_states and len(run_rows) < len(old_rows):
        warning = (f"this run resolved {len(run_rows)} records and the file holds {len(old_rows)}; the "
                   f"{len(old_rows) - len(run_rows)} not resolved this run were kept from the file (failed requests, "
                   f"the OSM time budget, or changed targets); --rebuild replaces the file with this run's records")
    # the states built by --state (stats.state_builds) that this run has no target in: a run of the live targets
    # (no --state) keeps their records (even with --rebuild), target rows, skipped texts and statistics as they are
    builds_prev = dict((prev.get("stats") or {}).get("state_builds") or {})
    keep_states = set() if scope_states else set(builds_prev) - {r.get("state") for r in targets_out}
    kept_built = [r for r in old_rows if r.get("state") in keep_states]
    if replace:
        rows = sorted(run_rows + [r for r in kept_built if r.get("slug") not in run_slugs], key=lambda r: r.get("slug") or "")
    else:
        rows = merge_waters(old_rows, run_rows)
    info = {"mode": "rebuild" if replace else "merge", "existing_records": len(old_rows),
            "run_records": len(run_rows), "replaced": len(old_slugs & run_slugs), "added": len(run_slugs - old_slugs),
            "kept": len({r["slug"] for r in kept_built if r.get("slug")} - run_slugs) if replace else len(old_slugs - run_slugs),
            "dropped": len(old_slugs - run_slugs - {r.get("slug") for r in kept_built}) if replace else 0,
            "written": len(rows)}
    if warning:
        info["warning"] = warning
        print(f"  note: {warning}", flush=True)
    targets_rows = merge_targets(prev.get("targets") or [], targets_out) if partial and not replace else targets_out
    if scope_states:
        builds = dict((prev.get("stats") or {}).get("state_builds") or {})
        if final:
            for st, v in (stats or {}).items():
                if rows_from:
                    builds[st] = {**(builds.get(st) or {}), "report_names": {**v, "write": info}}
                    continue
                # the tidy's log (--tidy: records dropped or renamed for openboatlaunch's) is the provenance of records
                # no longer in the file: a rebuild of the state keeps it (2026-11-04 review: NC's 41 drops and 9
                # renames were lost to the rebuild that followed the tidy)
                dup = (builds.get(st) or {}).get("existing_duplicates")
                builds[st] = {**v, "write": info, **({"existing_duplicates": dup} if dup else {})}
        stats = {**(prev.get("stats") or {}), "state_builds": dict(sorted(builds.items()))}
        partial = bool(prev.get("partial"))
        targets_rows = merge_targets_scoped(prev.get("targets") or [], targets_out, scope_states, rows_from)
        skipped = list({(r.get("state"), r.get("text")): r for r in list(prev.get("skipped") or []) + list(skipped)}.values())
        problems = list(dict.fromkeys(list(prev.get("problems") or []) + list(problems)))
    else:
        if final:
            stats = {**(stats or {}), "write": info}
        elif stats is None:
            stats = prev.get("stats") or {}   # a checkpoint keeps the last full run's statistics
        if builds_prev:
            stats = {**stats, "state_builds": builds_prev}
        if keep_states:
            if targets_rows is targets_out:
                targets_rows = list(targets_out) + [r for r in prev.get("targets") or [] if r.get("state") in keep_states]
            skipped = list(skipped) + [r for r in prev.get("skipped") or [] if r.get("state") in keep_states]
    write_json(OUT, {
        "source": "USGS NLDI hydrolocation and EPA NHDPlus V2.1 MapServer (pipeline/ingest/waters_from_nhd.py); "
                  "hand records (hand: true) also from the USGS NHD high-resolution flowlines (The National Map); "
                  "towns: Census 2020 county subdivisions (TIGERweb). Rows with source 'osm' (fallback_for 'nhd'): "
                  "data (c) OpenStreetMap contributors, ODbL",
        "built": now_iso(),
        "partial": partial,
        "count": len(rows),
        "note": "Receiving waters named by outfalls and notices that have no openboatlaunch or waters-extra record. "
                "Same row shape as waters-extra.json plus gnis_id, comids, nhd_fcodes and the number of targets "
                "mapped to the row; launches and advisories empty, charted not checked.",
        "stats": stats or {},
        "problems": list(problems),
        "skipped": skipped,
        "targets": targets_rows,
        "waters": rows,
    })
    return info


# ---------------------------------------------------------------- hand records
# Receiving waters the automatic passes cannot reach, each from a public geometry source named here
# (USGS/EPA NHDPlus by GNIS id and reach code, or OpenStreetMap by way id) and built in every run.
HAND: list[dict] = [
    dict(name="Jennings Run", state="MD", kind="stream", source="nhd", gnis_id="585223",
         why="MDE's overflow table names Jennings Run for Frostburg's and Allegany County's overflows (Water and "
             "Depot Streets, Frostburg; manhole 47 between Barrelville and Corriganville), but most of those rows "
             "have no point and the rest give Allegany County points in degrees and decimal minutes as if decimal "
             "degrees (39.3932 for 39 deg 39.32 min), so the point-based NHD search looked 30 km away. NHDPlus "
             "V2.1 GNIS 585223 is the Jennings Run that runs from Frostburg to Wills Creek at Corriganville."),
    dict(name="Elk Lick Run", state="MD", kind="stream", source="osm",
         ways=[415360177, 415360119, 415360096, 415360118, 415360100, 415360127, 415360084, 415360132, 415360194,
               415360108, 415360206, 415360189, 415360184],
         why="Allegany County DPW's overflows at manhole 127 and the Mill Run pump station (MDE overflow table) "
             "name Elk Lick Run. NHDPlus V2.1 and USGS NHD name no Elk Lick Run near Cumberland (their 'Elklick "
             "Run', GNIS 584277 near Midland, and 'Elk Lick Run', GNIS 584272 in Garrett County, are 20 km and "
             "more from the reports' two points in Cumberland); OpenStreetMap's Elk Lick Run east of Cumberland "
             "(every OSM way of that name between 39.55-39.76 N and 78.60-78.90 W, listed in `osm`), about 5 km "
             "from them, is the only stream of that name near them."),
    dict(name="Richmond Dock Canal", state="VA", kind="canal", source="osm", aliases=["Richmond Dock"],
         ways=[307765822, 307765825, 113029214, 164267051],
         why="EPA's CSO inventory gives Richmond Dock Canal as the receiving water of Richmond outfalls 034 and 035 "
             "(VA0063177). Neither NHDPlus nor OpenStreetMap carries that name: OSM tags the canal along Dock "
             "Street, east to the Great Ship Lock (historically the Richmond Dock), as part of the James River and "
             "Kanawha Canal; these are its ways east of 77.431 W (both outfalls lie within 200 m of them)."),
    # service "hr": USGS NHD high-resolution flowlines (NHD_HR layer 6) by GNIS id or permanent identifier. The
    # medium-resolution NHDPlus V2.1 network the automatic pass reads has 4.9 km of Scajaquada Creek and none of the others.
    dict(name="Scajaquada Creek", state="NY", kind="stream", source="nhd", service="hr", gnis_id="964557", supersede=True,
         why="NY DEC's sewage-release reports (Cheektowaga's and Depew's pump stations and sewers, 370 reports) name "
             "Scajaquada Creek at points 7 to 18 km up the creek from the 4.9 km the NHDPlus V2.1 network gives "
             "GNIS 964557 (5 flowlines, the creek's lower end in Buffalo). The USGS NHD high-resolution flowlines carry "
             "the whole creek under that GNIS id, from the Niagara River side at Buffalo up through Cheektowaga and "
             "Depew into Lancaster, including its culverted stretches (connector and artificial-path flowlines); this "
             "record replaces the 4.9 km one."),
    dict(name="Penhorn Creek", state="NJ", kind="stream", source="nhd", service="hr", gnis_id="879201",
         aliases=["Penhorn Creek UNT"],
         why="EPA's CSO inventory and NJDEP's outfall layer give Penhorn Creek (and 'Penhorn Creek UNT', its unnamed "
             "tributaries) as the receiving water of Jersey City MUA outfalls 001 and 002 (NJ0108723), North Bergen MUA "
             "outfalls 010 and 011 (NJ0108898) and a Newark outfall (NJ0108758); 123 monthly reports name it. NHDPlus V2.1 "
             "has no flowline of that name; the USGS NHD high-resolution flowlines carry Penhorn Creek as GNIS 879201 "
             "(Jersey City, Secaucus, Kearny and North Bergen, with its culverted and artificial-path stretches)."),
    dict(name="Webster Brook", state="CT", kind="stream", source="nhd", service="hr", gnis_id="211888",
         why="CT DEEP's sewage dashboard names Webster Brook for New Britain's manholes (Linden and Belden Streets) and "
             "the MDC's Newington pump stations (Carr Avenue), 78 reports with Hartford-area rows that give no point. "
             "NHDPlus V2.1 has no flowline of that name; the USGS NHD high-resolution flowlines carry the only Webster "
             "Brook in Connecticut as GNIS 211888, on the New Britain and Newington line."),
    dict(name="Johnson's Creek", state="CT", kind="stream", source="nhd", service="hr", aliases=["Johnsons Creek"],
         pids=["{6F24A13E-CCB5-4831-83A5-BB36901876F1}"], box=(-73.18, 41.155, -73.145, 41.19),
         why="EPA's CSO inventory gives Johnson's Creek as the receiving water of Bridgeport East Side outfall 006 "
             "(CT0101010, Bay Street and Mildner Drive, 41.17302 N 73.16142 W) and the DEEP dashboard names it for "
             "32 reports of the Bridgeport East Side WPCA. USGS GNIS lists the stream as Johnsons Creek (feature "
             "208183), 1.4 km from its source at 41.17751 N 73.15611 W to its mouth at 41.16622 N 73.16400 W; "
             "neither NHDPlus V2.1 nor the NHD high-resolution flowlines carry that name (the nearest named water, "
             "Bruce Brook, ends 240 m from the outfall), and OpenStreetMap has no waterway of that name. This record "
             "is the NHD high-resolution artificial-path flowline (permanent identifier above) that lies along "
             "the GNIS source-to-mouth line (78% of its length within 150 m of that line, the GNIS mouth 27 m from it, "
             "the outfall 77 m from it); the geometry is approximate, and the reports, which give no point, are "
             "placed by name."),
    # 2026-11-03 (docs/reviews/2026-11-03-outfalls-without-water.md): receiving waters of EPA CSO inventory outfalls that
    # NHDPlus V2.1 does not name within 2 km of the outfalls, found among the USGS NHD high-resolution flowlines within
    # 2 km of them (layer 6, GNIS name and id as given). `near` is the outfall point: the record is for that place, and
    # yields only to a same-named record that reaches it (the state has other waters of these names).
    dict(name="Black Rock Canal", state="NY", kind="canal", source="nhd", service="hr", gnis_id="944187",
         near=(-78.907222, 42.937222),
         why="EPA's CSO inventory gives Black Rock Canal as the receiving water of nine Buffalo Sewer Authority outfalls "
             "(NY0028410 003-010 and 061, Bird Island WWTF), 106-141 m from the Niagara River record; NHDPlus V2.1 has no "
             "flowline of that name within 2 km; the NHD high-resolution flowlines carry Black Rock Canal as GNIS 944187, "
             "52 m from outfall 003."),
    dict(name="Furnace Run", state="PA", kind="stream", source="nhd", service="hr", gnis_id="1175361",
         near=(-76.575278, 40.786389),
         why="EPA's CSO inventory gives Furnace Run as the receiving water of Shamokin-Coal Township Joint Sewer "
             "Authority outfalls 069, 077, 079 and 105 (PA0027324, Shamokin); NHDPlus V2.1 names no Furnace Run within "
             "2 km (only Carbon Run); the NHD high-resolution flowlines carry it as GNIS 1175361, 6 m from outfall 069."),
    dict(name="Robb Run", state="PA", kind="stream", source="nhd", service="hr", gnis_id="1185194", aliases=["Robbs Run"],
         near=(-80.235001, 40.369167),
         why="EPA's CSO inventory gives 'Robbs Run' as the receiving water of McDonald Sewer System outfalls B015-B018 "
             "(PAG066109, N. McDonald Street, McDonald); NHDPlus V2.1 names only Robinson Run within 2 km; the NHD "
             "high-resolution flowlines carry Robb Run (GNIS 1185194) 115 m from outfall B015."),
    dict(name="Hooff Run", state="VA", kind="stream", source="nhd", service="hr", gnis_id="1478786",
         near=(-77.057889, 38.804083),
         why="EPA's CSO inventory gives Hooff Run as the receiving water of AlexRenew outfalls 021 and 022 (VA0025160, "
             "Alexandria); NHDPlus V2.1 names only Taylor Run within 2 km; the NHD high-resolution flowlines carry Hooff "
             "Run (GNIS 1478786, largely culverted under Alexandria) 14 m from outfall 021."),
    dict(name="Hunting Creek", state="VA", kind="stream", source="nhd", service="hr", gnis_id="1478802",
         near=(-77.046222, 38.792222),
         why="EPA's CSO inventory gives Hunting Creek as the receiving water of AlexRenew outfall 020 (VA0025160, "
             "Alexandria); NHDPlus V2.1 names Cameron Run, Oxon Run and the Potomac River within 2 km but no Hunting "
             "Creek; the NHD high-resolution flowlines carry Hunting Creek (GNIS 1478802, the tidal reach below Cameron "
             "Run) 501 m from the outfall."),
    dict(name="Bannister Creek", state="NY", kind="stream", source="nhd", service="hr", gnis_id="942970",
         near=(-73.738578, 40.597375),
         why="EPA's CSO inventory gives Bannister Creek as the receiving water of NYC DEP Rockaway outfall 017 "
             "(NY0026221, Far Rockaway); NHDPlus V2.1 names no water within 2 km; the NHD high-resolution flowlines carry "
             "Bannister Creek (GNIS 942970) 271 m from the outfall."),
    dict(name="West Run", state="PA", kind="stream", source="nhd", service="hr", gnis_id="1191105",
         near=(-79.9175, 40.402222),
         why="EPA's CSO inventory gives West Run as the receiving water of West Homestead outfalls 003, 043 and 044 "
             "(PAG066123); the NHDPlus V2.1 West Run the automatic pass found is GNIS 1210102 near Wetmore, 181 km away; "
             "the NHD high-resolution flowlines carry West Homestead's West Run as GNIS 1191105, 16 m from outfall 003."),
    dict(name="Thompson Run", state="PA", kind="stream", source="nhd", service="hr", gnis_id="1189509",
         near=(-79.850556, 40.379167),
         why="EPA's CSO inventory gives Thompson Run as the receiving water of Duquesne outfalls 001, 004 and 005 "
             "(PA0026981); the NHDPlus V2.1 Thompson Run the automatic pass found is GNIS 1189505 (Monroeville to "
             "Turtle Creek), 3.7 km away; the NHD high-resolution flowlines carry Duquesne's Thompson Run as GNIS "
             "1189509, 5 m from outfall 001."),
    dict(name="Folly Brook", state="CT", kind="stream", source="nhd", service="hr", gnis_id="207123",
         near=(-72.665818, 41.728912),
         why="EPA's CSO inventory gives Folly Brook (and 'Folly Brook Conduit') as the receiving water of Hartford MDC "
             "outfalls 039 and 040 (CT0100251); the Folly Brook the automatic pass found (GNIS 207125) is in Manchester, "
             "13 km away; the NHD high-resolution flowlines carry the Hartford-Wethersfield Folly Brook as GNIS 207123, "
             "1 m from outfall 040."),
    dict(name="Baker Brook", state="MA", kind="stream", source="nhd", service="hr", gnis_id="617539",
         near=(-71.7831337, 42.5839064),
         why="EPA's CSO inventory gives Baker Brook as the receiving water of Fitchburg outfalls 024 (Boutelle Street at "
             "Lunenburg Street) and 072 (Pearl Street at Townsend Street) (MA0100986); NHDPlus V2.1 names only the North "
             "Nashua River within 2 km; the NHD high-resolution flowlines carry Baker Brook (GNIS 617539) 822 m from "
             "outfall 024."),
]


def superseded_keys() -> set[tuple]:
    """(state, normalised name) of the automatic records a hand record replaces (HAND specs with supersede)."""
    return {(h["state"], S.norm_name(h["name"])) for h in HAND if h.get("supersede")}


def overpass_ways(http: Http, ways) -> list[dict]:
    """OSM ways by id with tags and geometry (Overpass; cached like every other response)."""
    q = f"[out:json][timeout:90];way(id:{','.join(str(int(w)) for w in ways)});out tags geom;"
    d = http.get("osm-hand", WX.OVERPASS, {"data": q})
    return (d or {}).get("elements") or []


def build_hr(spec: dict, nhd: Nhd) -> tuple[dict | None, str]:
    """(record without slug, problem): a hand record from the USGS NHD high-resolution flowlines (layer 6 of
    hydro.nationalmap.gov's NHD MapServer) with the spec's GNIS id, or with its permanent identifiers."""
    state = spec["state"]
    fs = nhd.hr_lines(state, spec.get("gnis_id"), spec.get("pids"), spec.get("box"))
    if spec.get("pids"):
        got = {f.get("permanent_identifier") for f in fs}
        missing = [x for x in spec["pids"] if x not in got]
        if missing:
            return None, f"hand record {spec['name']} ({state}): NHD flowlines {missing} not returned"
    geom = to_geom_line(fs, state, nhd.states)
    if not fs or geom is None or geom.is_empty:
        return None, (f"hand record {spec['name']} ({state}): no NHD high-resolution flowlines "
                      f"{'with GNIS id ' + str(spec['gnis_id']) if spec.get('gnis_id') else 'by the identifiers given'} in {state}")
    fcodes = sorted({f.get("fcode") for f in fs if f.get("fcode")})
    reach = sorted({str(f["reachcode"]) for f in fs if f.get("reachcode")})
    b = geom.bounds
    what = (f"with GNIS id {str(int(spec['gnis_id']))}" if spec.get("gnis_id")
            else f"by permanent identifier ({', '.join(spec['pids'])})")
    rec = {"name": spec["name"], "kind": spec.get("kind") or kind_of(spec["name"], "line", fcodes=fcodes),
           "state": state, "towns": nhd.towns.along(state, geom),
           "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)], "wikidata": None, "charted": None,
           "length_km": round(WX.length_km(geom), 2), "area_km2": None, "launches": [], "advisories": [],
           "aliases": [], "source": "nhd", "gnis_id": str(int(spec["gnis_id"])) if spec.get("gnis_id") else None,
           "comids": [], "nhd_fcodes": fcodes, "reachcodes": reach, "fetched_at": now_iso(),
           "towns_from": TOWNS_FROM(state),
           "note": (f"USGS National Hydrography Dataset, high resolution (The National Map NHD MapServer, layer 6 "
                    f"'Flowline - Large Scale'): {len(fs)} flowlines {what} in {state}, cut to the state, merged and "
                    f"simplified to ~10 m (reach codes {', '.join(reach)}). Hand record: {spec['why']}"),
           "_geom": geom}
    return rec, ""


def build_hand(spec: dict, nhd: Nhd, http: Http) -> tuple[dict | None, str]:
    """(record without slug, problem): one HAND record."""
    state = spec["state"]
    if spec["source"] == "nhd" and spec.get("service") == "hr":
        rec, problem = build_hr(spec, nhd)
        if rec is None:
            return None, problem
        geom = rec["_geom"]
    elif spec["source"] == "nhd":
        rec = build_feature(nhd, state, {"type": "line", "gnis_id": spec["gnis_id"], "gnis_name": spec["name"],
                                         "comid": None})
        if rec is None:
            return None, f"hand record {spec['name']} ({state}): no NHDPlus flowlines with GNIS id {spec['gnis_id']}"
        fs = nhd.lines_by_gnis(state, spec["gnis_id"])
        rec["reachcodes"] = sorted({str(f["reachcode"]) for f in fs if f.get("reachcode")})
        rec["kind"] = spec.get("kind") or rec["kind"]
        rec["note"] += f" (reach codes {', '.join(rec['reachcodes'])}). Hand record: {spec['why']}"
        geom = rec["_geom"]
    else:
        els = overpass_ways(http, spec["ways"])
        got = {e.get("id") for e in els}
        missing = [w for w in spec["ways"] if w not in got]
        if missing:
            return None, f"hand record {spec['name']} ({state}): OSM ways {missing} not returned (Overpass)"
        from shapely.geometry import LineString
        lines = [LineString([(g["lon"], g["lat"]) for g in e["geometry"]]) for e in els if len(e.get("geometry") or []) >= 2]
        geom = to_geom_line([{"_geom": g} for g in lines], state, nhd.states)
        if geom is None or geom.is_empty:
            return None, f"hand record {spec['name']} ({state}): the OSM ways have no geometry in {state}"
        names = sorted({(e.get("tags") or {}).get("name") for e in els} - {None})
        b = geom.bounds
        rec = {"name": spec["name"], "kind": spec.get("kind") or "stream", "state": state, "towns": [],
               "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)], "wikidata": None,
               "charted": None, "length_km": round(WX.length_km(geom), 2), "area_km2": None, "launches": [],
               "advisories": [], "aliases": [], "source": "osm", "fallback_for": "nhd",
               "osm": [f"w{w}" for w in spec["ways"]], "gnis_id": None, "comids": [], "nhd_fcodes": [],
               "fetched_at": now_iso(), "towns_from": TOWNS_FROM(state),
               "note": (f"OpenStreetMap ways {', '.join('w' + str(w) for w in spec['ways'])} (named "
                        f"{' / '.join(repr(n) for n in names) or 'nothing'} in OSM), merged and simplified to ~10 m. "
                        f"Hand record: {spec['why']}")}
    rec["towns"] = nhd.towns.along(state, geom) or rec.get("towns") or []
    rec["aliases"] = list(dict.fromkeys(list(rec.get("aliases") or []) + list(spec.get("aliases") or [])))
    rec.update(name=spec["name"], hand=True, _geom=geom, _targets=[], _weight=0, _slug_towns=Counter(),
               _key=("hand", state, slugify(spec["name"])), _targets_n=0)
    return rec, ""


# ---------------------------------------------------------------- OSM fallback

def osm_kind(ws) -> str:
    last = [w for w in ws if w in KIND_WORDS][-1:]
    lw = last[0] if last else ""
    if lw in ("kill", "kills", "channel") or lw in BAY_WORDS:
        return "bay"
    if lw in ("pond", "ponds"):
        return "pond"
    if lw in ("lake", "lakes"):
        return "lake"
    if lw == "reservoir":
        return "reservoir"
    if lw in ("canal", "ditch"):
        return "canal"
    if lw == "river":
        return "river"
    return "stream"


_LAST_OSM = 0.0
OVERPASS_MIRRORS = [WX.OVERPASS, "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter"]
# (instance, timeout s) in order: in November 2026 overpass-api.de took 30 s and more for a single way
# by id and often hung; the mail.ru instance answered the same in under 20 s
OVERPASS_TRIES = [(OVERPASS_MIRRORS[0], 90), (OVERPASS_MIRRORS[1], 180), (OVERPASS_MIRRORS[0], 200),
                  (OVERPASS_MIRRORS[2], 120)]
GENERIC_WORDS = {"no", "name", "small", "minor", "tiny", "local", "nearby", "unknown", "a", "the", "of", "to"}


def generic_name(name) -> bool:
    """'No Name Small Stream', 'Small Stream': a description, not a water's name ('Little River' is one)."""
    ws = re.findall(r"[a-z]+", str(name or "").lower())
    return bool(ws) and all(w in KIND_WORDS or w in GENERIC_WORDS for w in ws) and any(w in GENERIC_WORDS for w in ws)


def osm_fetch(spec: dict, refresh: bool, offline: bool):
    """waters_extra.fetch with short retries (Overpass answered 502 for minutes at a time in November
    2026, and waters_extra waits up to 10 minutes a water): OVERPASS_TRIES in turn (the main instance,
    a mirror, the main one again, another mirror); same cache (data/raw/osm-waters/<key>.json, reused
    while the query is unchanged, whichever instance answered)."""
    path = WX.CACHE_DIR / f"{spec['key']}.json"
    q = WX.build_query(spec)
    if path.exists() and not refresh:
        d = json.loads(path.read_text())
        if d.get("_query") == q or offline:
            return d, False
    if offline:
        return None, False
    for attempt, (url, timeout) in enumerate(OVERPASS_TRIES):
        try:
            r = requests.post(url, data={"data": q}, headers=HEADERS, timeout=timeout)
        except requests.RequestException:
            time.sleep(5)
            continue
        if r.status_code in (429, 502, 503, 504):
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None, False
        try:
            d = r.json()
        except ValueError:
            continue
        if d.get("remark") and "error" in d["remark"].lower():
            time.sleep(10)
            continue
        d["_query"], d["_fetched_at"], d["_endpoint"] = q, now_iso(), url
        WX.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d))
        return d, True
    print(f"  {spec['key']}: Overpass did not answer; left for the next run", flush=True)
    return None, False


def osm_spec(t, towns: Towns) -> dict:
    """waters_extra's spec for one target: its names, kind, towns and a box around its points."""
    pts = list(t["points"])
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    pad = 0.04
    tws = [x for x, _ in target_point_towns(t, towns)[0].most_common()] or [t["state"]]
    spec = {"name": t["name"].strip(), "state": t["state"], "kind": osm_kind(t["words"]), "towns": tws[:3],
            "box": (round(min(lats) - pad, 3), round(min(lons) - pad, 3), round(max(lats) + pad, 3), round(max(lons) + pad, 3)),
            "key": f"nhd-fallback-{slugify(t['name'])}-{t['state'].lower()}"}
    names = {t["name"].strip()} | {n.strip() for n in t["names"]}
    titled = " ".join(w.capitalize() if w.islower() else w for w in t["name"].split())
    spec["osm_names"] = sorted((names | {titled}) - {spec["name"]})
    return spec


def osm_fallback(t, states: States, towns: Towns, existing_list: list, refresh: bool, offline: bool):
    spec = osm_spec(t, towns)
    global _LAST_OSM
    if not offline and not WX.is_cached(spec, spec["key"], refresh):
        wait = WX.PAUSE_S - (time.time() - _LAST_OSM)
        if wait > 0:
            time.sleep(wait)
    d, fetched = osm_fetch(spec, refresh, offline)
    if fetched:
        _LAST_OSM = time.time()
    if d is None:
        return None, "OSM fallback: Overpass not reachable" if not offline else "OSM fallback: not cached (--offline)"
    return osm_record(t, spec, d, states, towns, existing_list)


def osm_record(t, spec: dict, d: dict, states: States, towns: Towns, existing_list: list):
    """(record, how) from an Overpass answer holding the target's named elements (or None, why)."""
    pts = list(t["points"])
    try:
        rec = WX.build_record(spec, d, states, existing_list)
    except Exception as ex:    # a malformed relation must not stop the run
        return None, f"OSM fallback failed ({type(ex).__name__})"
    if rec is None:
        return None, "no NHD feature and no OSM feature of that name near the points"
    geom = shape(rec["geometry"])
    near = min(dist_m(geom, lon, lat) for lon, lat in pts)
    if near > S.NAME_MATCH_M * (2.5 if rec["kind"] in S.WIDE_KINDS else 1):
        return None, f"OSM feature of that name is {near / 1000:.1f} km from the points"
    rec["_geom"] = geom
    if rec.get("length_km") is not None and rec["kind"] not in WX.LINE_KINDS:
        rec["kind"] = "canal" if t["words"][-1:] == ["channel"] else "river"   # drawn as a line: a river-like water
    rec.update(source="osm", fallback_for="nhd", gnis_id=None, comids=[], nhd_fcodes=[],
               towns=towns.along(t["state"], geom) or rec["towns"],
               towns_from=TOWNS_FROM(t["state"]),
               note=(rec.get("note") or "") + ("; " if rec.get("note") else "") +
               "NHDPlus V2.1 has no feature of this name here (tidal waters are unnamed areas); from OpenStreetMap")
    return rec, "OSM fallback (NHDPlus has no feature of that name)"


# ---------------------------------------------------------------- OSM fallback, one query per state
# (2026-11-03: overpass-api.de answered one per-name query a minute, too slow for the 284 names left)
OSM_STATE_MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                     "https://lz4.overpass-api.de/api/interpreter"]
OSM_STATE_TIMEOUT = 90
OSM_REGEX_MAX = 4000            # characters of name alternation per query; a longer list is split


def state_query(names: list[str], box) -> str:
    """Named rivers, streams and canals (ways and relations) and named water areas in the box."""
    s, w, n, e = box
    bb = f"{s},{w},{n},{e}"
    rx = WX.name_regex(names)
    return f"""[out:json][timeout:{OSM_STATE_TIMEOUT}];
(
  way["waterway"~"^(river|stream|canal)$"]["name"~"{rx}",i]({bb});
  relation["waterway"~"^(river|stream|canal)$"]["name"~"{rx}",i]({bb});
  way["natural"~"^(water|bay|strait)$"]["name"~"{rx}",i]({bb});
  relation["natural"~"^(water|bay|strait)$"]["name"~"{rx}",i]({bb});
);
out tags geom;
"""


def state_chunks(specs: list[dict]) -> list[tuple[list[str], tuple]]:
    """[(names, box)]: the specs' names in alternations of at most OSM_REGEX_MAX characters, each with
    the box around its specs' boxes."""
    out, cur, cur_specs = [], [], []

    def close():
        if cur:
            b = [sp["box"] for sp in cur_specs]
            out.append((sorted(set(cur)), (min(x[0] for x in b), min(x[1] for x in b), max(x[2] for x in b),
                                           max(x[3] for x in b))))
    for sp in specs:
        names = [sp["name"]] + list(sp.get("osm_names") or [])
        if cur and len(WX.name_regex(sorted(set(cur + names)))) > OSM_REGEX_MAX:
            close()
            cur, cur_specs = [], []
        cur += names
        cur_specs.append(sp)
    close()
    return out


def mirror_order(mirrors=OSM_STATE_MIRRORS, timeout=30) -> list[str]:
    """The instances by the time they take to answer a trivial query; those that did not answer last."""
    timed = []
    for url in mirrors:
        t0 = time.time()
        try:
            r = requests.post(url, data={"data": "[out:json][timeout:20];node(1);out ids;"}, headers=HEADERS,
                              timeout=timeout)
            ok = r.status_code == 200 and "elements" in r.text
        except requests.RequestException:
            ok = False
        timed.append((0 if ok else 1, time.time() - t0, url))
        print(f"  mirror {url}: {'answered' if ok else 'no answer'} in {time.time() - t0:.1f} s", flush=True)
    return [u for _, _, u in sorted(timed)]


def state_fetch(q: str, mirrors: list[str], refresh: bool, offline: bool):
    """(response, endpoint) for one state query, cached in data/raw/nhd-waters/osm-state/<hash>.json;
    two tries (the fastest instance, then the next), OSM_STATE_TIMEOUT s each; (None, why) when both fail."""
    path = CACHE_DIR / "osm-state" / f"{hashlib.sha1(q.encode()).hexdigest()[:24]}.json"
    if path.exists() and not refresh:
        d = json.loads(path.read_text())
        return d["response"], d.get("url")
    if offline:
        return None, "not cached (--offline)"
    why = "no instance listed"
    for url in (mirrors * 2)[:2]:
        try:
            r = requests.post(url, data={"data": q}, headers=HEADERS, timeout=OSM_STATE_TIMEOUT + 10)
        except requests.RequestException as ex:
            why = f"{url}: {type(ex).__name__}"
            continue
        if r.status_code != 200:
            why = f"{url}: HTTP {r.status_code}"
            time.sleep(5)
            continue
        try:
            d = r.json()
        except ValueError:
            why = f"{url}: not JSON"
            continue
        if d.get("remark") and re.search(r"error|timed out|out of memory", d["remark"], re.I):
            why = f"{url}: {d['remark'][:80]}"
            continue
        d["_fetched_at"] = now_iso()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"url": url, "query": q, "fetched_at": d["_fetched_at"], "response": d}))
        return d, url
    return None, why


def element_box(el: dict):
    b = el.get("bounds")
    if b:
        return b["minlat"], b["minlon"], b["maxlat"], b["maxlon"]
    pts = list(el.get("geometry") or []) + [g for m in el.get("members") or [] for g in m.get("geometry") or []]
    if not pts:
        return None
    return (min(p["lat"] for p in pts), min(p["lon"] for p in pts), max(p["lat"] for p in pts), max(p["lon"] for p in pts))


def for_spec(resp: dict, spec: dict) -> dict:
    """The part of a state answer that is this target's: its names, inside its box."""
    names = {n.lower() for n in [spec["name"]] + list(spec.get("osm_names") or [])}
    s, w, n, e = spec["box"]
    els = []
    for el in resp.get("elements") or []:
        b = element_box(el)
        if (((el.get("tags") or {}).get("name") or "").lower() in names and b is not None
                and not (b[2] < s or b[0] > n or b[3] < w or b[1] > e)):
            els.append(el)
    return {"elements": els, "osm3s": resp.get("osm3s"), "_fetched_at": resp.get("_fetched_at")}


# ---------------------------------------------------------------- main

def evaluate(existing: dict, recs: list[dict], events) -> dict:
    """Unplaced events (with and without a waterbody text) before and after, with the status resolver."""
    out = {}
    nhd_waters = {r["slug"]: {**public_record(r), "extra": True} for r in recs}
    for label, waters in (("before", existing), ("after", {**existing, **{k: v for k, v in nhd_waters.items() if k not in existing}})):
        S._GEOM_CACHE.clear()
        S._STATES = S.derive_states(waters, S.load_rules())
        res = S.make_resolver(waters)
        un = []
        for ev in events:
            pl = res.resolve(ev)
            if not pl["water_slugs"] and not pl.get("no_receiving_water"):
                un.append(ev)
        out[label] = {"unplaced": len(un),
                      "unplaced_with_text": sum(1 for ev in un if (ev.get("waterbody_text") or "").strip()),
                      "ids": {ev["event_id"] for ev in un}}
    S._GEOM_CACHE.clear()
    return out


class Run:
    """The resolving pass: target rows, the records by NHD feature, checkpoints."""

    def __init__(self, nhd, states, towns, existing, args, http, skipped_reason):
        self.nhd, self.states, self.towns, self.existing = nhd, states, towns, existing
        self.existing_list = list(existing.values())
        self.args, self.http, self.skipped_reason = args, http, skipped_reason
        self.feats: dict[tuple, dict] = {}       # feature key -> record (or {"_existing": slug})
        self.rows: list[dict] = []
        self.problems: list[str] = []
        self.osm_used = 0
        self.osm_queue = []
        self.place_stats = {}
        self.previous = previous_slugs()        # the slugs of the file on disk, kept where free (assign_slugs)
        self.kept_rows = previous_rows()
        self.osm_remaining = []
        self.osm_states = {}
        self.last_written = 0
        self.reach_index = {}                   # a state build: EPA's reach codes and NHDPlus ids (reach_index())
        self.only_states = None                 # a state build: its states (hand records of other states not rebuilt)
        self.stopped = None                     # why the run stopped early (BudgetExhausted), if it did
        self.rows_from = None                   # a --names run: its target rows are the reports' ("reports")

    def attach(self, rec, row, t, how):
        rec["_targets"].append(row)
        tc, n = target_point_towns(t, self.towns, rec["_geom"])
        rec["_weight"] += n
        rec["_targets_n"] = len(rec["_targets"])
        rec["_slug_towns"].update(tc)
        if not how.startswith("the lake/pond at the site"):     # a camp's or beach's name is not the lake's
            for a in aliases_for(rec["name"], t, t["state"], self.existing):
                if a not in rec["aliases"] and S.norm_name(a) != S.norm_name(rec["name"]):
                    rec["aliases"].append(a)
        row["how"].append(how)
        row["_recs"].append(rec)

    def new_record(self, k, c, t, row):
        rec = build_feature(self.nhd, t["state"], c)
        if rec is None:
            row["reason"] = f"NHD feature {k[2]} has no geometry in {t['state']}"
            return None
        if not rec["name"]:
            rec["name"] = t["name"] or "Unnamed water"
        if rec["name"] == UNNAMED_STREAM:        # no named water downstream: the town it lies in, else the operators'
            town = next(iter(rec.get("towns") or []), None) or next((x for x, _ in t["towns"].most_common(1)), None)
            rec["name"] = unnamed_name(None, town)
        rec.update(_targets=[], _weight=0, _slug_towns=Counter(), _key=k)
        same = same_named_existing(self.existing, t["state"], rec["name"])
        if not same:
            return rec
        s, rest = overlap_with_existing(rec, self.existing, same)
        if not s:
            # a same-named record whose outline is not on this machine (openboatlaunch's out/water absent): its
            # bounding box decides whether this is that water (same_water_by_box); the remainder cannot be cut
            unmeasured = [x for x in same if S.water_geometry(x, self.existing) is None]
            hit, _ = existing_same_water(rec["_geom"], rec.get("towns") or [], self.existing, unmeasured)
            return {"_existing": hit} if hit else rec
        rest = WX.as_multiline(rest) if (rest is not None and rec["length_km"] is not None) else None
        if rest is None or rest.is_empty or WX.length_km(rest) < REMAINDER_MIN_KM or not t["points"] \
                or min(dist_m(rest, lon, lat) for lon, lat in t["points"]) > S.NAME_MATCH_M:
            return {"_existing": s}
        g = WX.as_multiline(WX.simplify(rest, SIMPLIFY_M))
        b = g.bounds
        rec.update(_geom=g, covers_part_of=s, length_km=round(WX.length_km(g), 2),
                   bbox=[round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)],
                   towns=self.towns.along(t["state"], g),
                   note=rec["note"] + f"; only the part more than {SAME_WATER_M} m from {s} (that record covers the rest)")
        return rec

    @staticmethod
    def new_row(t) -> dict:
        row = {"_key": t["key"], "state": t["state"], "name": t["name"],
               "texts": [x for x, _ in t["texts"].most_common(4)], "outfalls": t["outfalls"], "events": t["events"],
               "points": len(t["points"]), "towns": [x for x, _ in t["towns"].most_common(4)], "slugs": [],
               "how": [], "reason": None, "_recs": []}
        if t.get("define_by"):                  # a state build's target (the national list)
            row.update(define_by=t["define_by"], defined_by=None, permits=list(t.get("permits") or [])[:12],
                       _epa=[])
            if t.get("notes"):
                row["notes"] = list(dict.fromkeys(t["notes"]))
            if t.get("outfall_ref"):
                row["outfall_ref"] = list(t["outfall_ref"])
            if not t["name"]:
                row["texts"] = [f"unnamed outfall {t['outfall_ref'][0]} {t['outfall_ref'][1]}"] if t.get("outfall_ref") else []
        return row

    def hand_pass(self, targets):
        """The HAND records, each attached to the targets that carry its name (or an alias)."""
        by_key = defaultdict(list)
        for t, row in targets:
            for n in [t["name"] or ""] + list(t["names"]):
                by_key[(t["state"], compact(n))].append((t, row))
        for spec in HAND:
            if getattr(self, "only_states", None) and spec["state"] not in self.only_states:
                continue                # a state build rebuilds only its own states' hand records
            auto = [(k, r) for k, r in self.feats.items() if not r.get("_existing") and
                    k[0] != "hand" and r["state"] == spec["state"] and S.norm_name(r["name"]) == S.norm_name(spec["name"])]
            same = same_named_existing(self.existing, spec["state"], spec["name"])
            if not spec.get("supersede"):      # a record of the same name in this run holds the name
                same += [f"this run's {r['name']}" for _, r in auto]
            if spec.get("near") and same:
                # a hand record for one place (2026-11-03: a Furnace Run or Mill Creek at an outfall, while the state
                # has other waters of that name): only a same-named record that reaches the place makes it unneeded
                lon, lat = spec["near"]
                geoms = [S.water_geometry(x, self.existing) for x in same_named_existing(self.existing, spec["state"],
                                                                                          spec["name"])]
                geoms += [r.get("_geom") for _, r in auto]
                same = [] if all(g is None or dist_m(g, lon, lat) > NEAR_M for g in geoms) else same
            if same:                           # the hand record is a fallback: a found record wins, quietly
                print(f"  note: hand record {spec['name']} ({spec['state']}) not needed: "
                      f"{', '.join(same)} already carries the name", flush=True)
                continue
            try:
                rec, problem = build_hand(spec, self.nhd, self.http)
            except Exception as ex:      # a hand record must not stop the run
                rec, problem = None, f"hand record {spec['name']} ({spec['state']}): {type(ex).__name__}: {ex}"
            if rec is None:
                self.problems.append(problem)
                continue
            inherited = []
            if spec.get("supersede"):
                # the record this run built by the automatic pass for the same water is replaced: its targets
                # go to the hand record (by name below, and the rest by their row), its aliases are kept, and the
                # hand record takes the plain slug
                for k, r in auto:
                    for row in r["_targets"]:
                        row["_recs"] = [x for x in row["_recs"] if x is not r]
                        row["how"].append(f"hand record replaces the NHDPlus V2.1 record (GNIS {r.get('gnis_id')}, "
                                          f"{r.get('length_km')} km)")
                        inherited.append(row)
                    rec["aliases"] = list(dict.fromkeys(rec["aliases"] + r["aliases"]))
                    del self.feats[k]
            self.feats[rec["_key"]] = rec
            seen = set()
            how = (f"hand record ({rec['source']}: " +
                   (f"{'NHD high resolution ' if spec.get('service') == 'hr' else ''}GNIS {spec['gnis_id']}" if spec.get("gnis_id")
                    else "NHD high resolution flowline" if spec.get("pids") else "OSM ways") + ")")
            for n in [spec["name"]] + list(spec.get("aliases") or []):
                for t, row in by_key.get((spec["state"], compact(n)), []):
                    if id(row) in seen:
                        continue
                    seen.add(id(row))
                    self.attach(rec, row, t, how)
                    row["reason"] = None
            t_of = {id(row): t for t, row in targets}
            for row in inherited:
                if id(row) not in seen and id(row) in t_of:
                    seen.add(id(row))
                    self.attach(rec, row, t_of[id(row)], how)

    def resolve(self, t):
        nhd = self.nhd
        row = self.new_row(t)
        self.rows.append(row)
        choices = []
        by = t.get("define_by")
        epa = {}                                # feature key -> EPA ids that named it (a state build's reach_slugs)
        reach_note = None
        if by == "unnamed":
            found, reason = resolve_unnamed(nhd, t, self.reach_index)
            for k, c, how, ids in found:
                choices.append((k, c, how))
                epa[k] = ids
            row["reason"] = reason
            if found:
                row["defined_by"] = "unnamed"
        elif by == "reach":
            found, reach_note = resolve_reach(nhd, t, self.reach_index)
            for k, c, how, ids in found:
                choices.append((k, c, how))
                epa[k] = ids
            if found:
                row["defined_by"] = "reach"
        if not choices and by == "reach" and t["name"] and t["points"] and t["towns"]:
            # a state build: EPA's reaches name another water (a treatment plant indexed by its fence to the small
            # stream there while the permit names the river it reaches: 171 of North Carolina's 183 reach rows): the
            # GNIS feature of the name nearest the operators' towns first, which costs no NLDI request; the points
            # only when that finds none or cannot choose
            c, how = resolve_name_only(nhd, t)
            if c is not None:
                choices.append((feature_key(t["state"], c), c, how))
                row["defined_by"] = "name"
            else:
                reach_note = f"{reach_note}; {how}"
        if choices or by == "unnamed":
            pass
        elif t["points"]:
            seen = set()
            row["_tried"] = cluster_points(t["points"])
            fails = []
            for lon, lat in row["_tried"]:
                c, how = resolve_point(nhd, t, lon, lat)
                if c is None:
                    row["reason"] = how
                    fails.append({"lon": lon, "lat": lat, "reason": how})
                    continue
                k = feature_key(t["state"], c)
                if k not in seen:
                    seen.add(k)
                    choices.append((k, c, how))
            if choices and fails:           # another point found the name: keep where it did not (place_pass)
                row["places_failed"] = fails
        elif t["name"]:
            c, how = resolve_name_only(nhd, t)
            if c is None:
                row["reason"] = how
            else:
                choices.append((feature_key(t["state"], c), c, how))
        else:
            row["reason"] = "a site with no point"
        if by and by != "unnamed" and not row.get("defined_by") and choices:
            row["defined_by"] = "point" if t["points"] else "name"
        if by and by != "unnamed" and not choices and t["name"] and t["points"] and not (by == "reach" and t["towns"]):
            # a state build: EPA's reaches and the points name another water (a plant indexed to the small stream
            # by its fence, the permit naming the river it reaches): the GNIS feature of the name nearest the
            # operators' towns, as for a row with a name only
            c, how = resolve_name_only(nhd, t)
            if c is not None:
                choices.append((feature_key(t["state"], c), c, f"{how} (the points found no water of that name "
                                                               f"within 2 km: {row['reason']})"))
                row["defined_by"] = "name"
            else:
                row["reason"] = f"{row['reason']}; {how}" if row["reason"] else how
        if reach_note and not choices:
            row["reason"] = f"{reach_note}; {row['reason']}" if row["reason"] else reach_note
        elif reach_note:
            row.setdefault("notes", []).append(f"{reach_note}: defined by {row['defined_by']}")
        for k, c, how in choices:
            if k not in self.feats:
                rec = self.new_record(k, c, t, row)
                if rec is None:
                    continue
                self.feats[k] = rec
            rec = self.feats[k]
            if rec.get("_existing"):
                row["slugs"].append(rec["_existing"])
                row["how"].append(f"{how}; the same water as existing record {rec['_existing']}")
                if k in epa:
                    row["_epa"].append((epa[k], rec))
                continue
            self.attach(rec, row, t, how)
            if k in epa:
                row["_epa"].append((epa[k], rec))
        a = self.args
        if not row["how"] and t["name"] and t["points"] and not a.no_osm and has_kind(t["words"]):
            if generic_name(t["name"]):
                row["reason"] = f"{row['reason']}; a description, not a name: OSM not asked"
            else:
                self.osm_queue.append((t, row))
        if row["how"]:
            row["reason"] = None

    def hr_pass(self, pairs, budget=None):
        """A state build: the targets with a name and points that neither NHDPlus V2.1 nor the name pass placed go to
        the NHD high-resolution flowlines (resolve_hr), within budget seconds of requests; those not reached say so."""
        started, n, found = time.monotonic(), 0, 0
        for t, row in pairs:
            if row["how"] or not t["name"] or not t["points"] or not has_kind(t["words"]) or generic_name(t["name"]):
                continue
            if self.stopped or (budget is not None and time.monotonic() - started > budget):
                row["reason"] = f"{row['reason']}; NHD high resolution not asked this run (budget)"
                continue
            n += 1
            try:
                c, how = resolve_hr(self.nhd, t)
                rec = None
                if c is not None:
                    k = feature_key(t["state"], c)
                    if k not in self.feats:
                        rec = self.new_record(k, c, t, row)
                        if rec is not None:
                            self.feats[k] = rec
                    rec = self.feats.get(k)
            except BudgetExhausted as ex:
                self.stopped = str(ex)
                row["reason"] = f"{row['reason']}; NHD high resolution not asked ({ex})"
                continue
            if rec is None:
                row["reason"] = f"{row['reason']}; {how}"
                continue
            if rec.get("_existing"):
                row["slugs"].append(rec["_existing"])
                row["how"].append(f"{how}; the same water as existing record {rec['_existing']}")
            else:
                self.attach(rec, row, t, how)
            row["defined_by"] = "point (NHD high resolution)"
            row["reason"] = None
            found += 1
        print(f"  NHD high resolution: {n} targets asked, {found} with a record ({time.monotonic() - started:.0f} s)",
              flush=True)

    def not_reached(self, t) -> dict:
        row = self.new_row(t)
        row["reason"] = f"{NOT_REACHED} ({self.stopped}); the next run resumes"
        self.rows.append(row)
        return row

    def stop(self, t, ex) -> None:
        """The budget ran out while resolving t: the run stops starting requests; t's row says so."""
        self.stopped = str(ex)
        print(f"  stopped: {ex}", flush=True)
        row = self.rows[-1] if self.rows and self.rows[-1]["_key"] == t["key"] else None
        if row is None:
            self.not_reached(t)
        elif not row["how"]:
            row["reason"] = f"{NOT_REACHED} ({self.stopped}); the next run resumes"

    def place_geoms(self, row) -> list:
        geoms = [r["_geom"] for r in row["_recs"] if r.get("_geom") is not None]
        geoms += [S.water_geometry(s, self.existing) for s in row["slugs"]]
        return [g for g in geoms if g is not None]

    def uncovered_places(self, t, row) -> list[tuple]:
        """[(lon, lat, outfall rows, reports)]: the places of a target's points that no record found for it reaches
        (a point more than NEAR_M from all of them), one per cluster of points NEAR_M apart, the most reported point
        of each standing for it; places within NEAR_M of a point resolve() already tried are left out."""
        if not t["name"] or not t["points"]:
            return []
        geoms = self.place_geoms(row)
        pts = Counter({p: n for p, n in t["points"].items() if all(dist_m(g, p[0], p[1]) > NEAR_M for g in geoms)})
        if not pts:
            return []
        tried = row.get("_tried") or []
        out = []
        for lon, lat in cluster_points(pts, n=len(pts), sep_m=NEAR_M):
            if any(dist_m(Point(x), lon, lat) <= NEAR_M for x in tried):
                continue
            near = [p for p in pts if dist_m(Point(p), lon, lat) <= NEAR_M]
            out.append((lon, lat, sum(t.get("outfall_points", Counter())[p] for p in near), sum(pts[p] for p in near)))
        return out

    def place_pass(self, pairs):
        """The other places of a name (2026-11-03): resolve() looks at the three most reported points of a target,
        one name in one state, so a Mill Creek or West Run elsewhere in the state got no record of its own (the
        outfalls of Wilkes-Barre and West Homestead were 62 and 181 km from the Mill Creek and West Run that were
        built). Every place of a target's points that none of its records reaches is resolved here, the places
        with the most outfall rows first, then the most reports, within --place-budget seconds of requests (a
        cached place costs almost nothing); places not reached are left for the next run and listed in the
        target's places_failed with that reason. Only targets NHDPlus named at a point resolve() tried: the others
        go to the OSM fallback."""
        budget = getattr(self.args, "place_budget", None)
        queue = []
        for t, row in pairs:
            if not row["how"]:
                # NHDPlus named the water at none of the points tried: the OSM fallback (one box around all the
                # points) or a hand record answers for it; a record found here at another place would take the
                # name from the OSM record of the first places (2026-11-03: Lick Run, Roanoke)
                continue
            for lon, lat, n_out, n in self.uncovered_places(t, row):
                queue.append((-n_out, -n, t["key"], lon, lat, t, row))
        queue.sort(key=lambda q: q[:5])
        started, done, found = time.monotonic(), 0, 0
        for _, _, _, lon, lat, t, row in queue:
            failed = row.setdefault("places_failed", [])
            if any(dist_m(g, lon, lat) <= NEAR_M for g in self.place_geoms(row)):
                continue                        # an earlier place of this name built a record that reaches here
            if budget is not None and time.monotonic() - started > budget:
                if len(failed) < 12:
                    failed.append({"lon": lon, "lat": lat, "reason": f"not tried this run (--place-budget {budget:g} s used)"})
                continue
            done += 1
            try:
                c, how = resolve_point(self.nhd, t, lon, lat)
            except BudgetExhausted as ex:       # the run's budget: this place and the rest wait for the next run
                c, how = None, f"not tried this run ({ex})"
            except Exception as ex:             # one bad place must not stop the run
                c, how = None, f"build error ({type(ex).__name__}: {ex})"
            if c is None:
                if len(failed) < 12:
                    failed.append({"lon": lon, "lat": lat, "reason": how})
                continue
            k = feature_key(t["state"], c)
            if k not in self.feats:
                rec = self.new_record(k, c, t, row)
                if rec is None:
                    continue
                self.feats[k] = rec
            rec = self.feats[k]
            how = f"{how}; another place of the name ({lat:.5f}, {lon:.5f})"
            if rec.get("_existing"):
                if rec["_existing"] not in row["slugs"]:
                    row["slugs"].append(rec["_existing"])
                row["how"].append(f"{how}; the same water as existing record {rec['_existing']}")
            elif not any(r is rec for r in row["_recs"]):
                self.attach(rec, row, t, how)
            found += 1
            row["reason"] = None
        for _, row in pairs:
            if not row.get("places_failed"):
                row.pop("places_failed", None)
        self.place_stats = {"places": len(queue), "resolved": done, "found": found,
                            "seconds": round(time.monotonic() - started, 1)}
        print(f"  other places of a name: {len(queue)} places, {done} resolved, {found} with a record "
              f"({self.place_stats['seconds']} s)", flush=True)

    def osm_pass(self):
        """OSM for the targets NHDPlus could not name, most reports first, at most --osm-max."""
        a = self.args
        self.osm_queue.sort(key=lambda x: -(x[0]["events"] + x[0]["outfalls"]))
        for n, (t, row) in enumerate(self.osm_queue):
            if n >= a.osm_max:
                row["reason"] = f"{row['reason']}; OSM fallback not tried (over --osm-max {a.osm_max})"
                continue
            try:
                self.osm_one(t, row)
            except Exception as ex:
                self.problems.append(f"{t['key']}: OSM fallback {type(ex).__name__}: {ex}")
            if n % 10 == 9:
                print(f"  OSM fallback {n + 1}/{min(len(self.osm_queue), a.osm_max)}", flush=True)
                self.checkpoint(n, len(self.osm_queue))

    def osm_state_pass(self):
        """The OSM fallback for the queued targets with one Overpass query per state (split when the
        name alternation is long). A target the stopped per-name run already cached keeps that answer. A
        state whose query fails twice is skipped: its targets say so and stay for the next run."""
        a = self.args
        by_state = defaultdict(list)
        for t, row in self.osm_queue[:a.osm_max]:
            by_state[t["state"]].append((t, row, osm_spec(t, self.towns)))
        for t, row in self.osm_queue[a.osm_max:]:
            row["reason"] = f"{row['reason']}; OSM fallback not tried (over --osm-max {a.osm_max})"
        mirrors = mirror_order() if (by_state and not a.offline) else []      # nothing queued: no Overpass ping
        self.osm_states = {}
        started, budget = time.monotonic(), getattr(a, "osm_budget", None)
        for state, items in sorted(by_state.items()):
            todo = [x for x in items if not WX.is_cached(x[2], x[2]["key"], a.refresh)]
            elements, failed, via = [], None, set()
            over = budget is not None and todo and time.monotonic() - started > budget
            if over:
                failed = f"time budget of {budget:g} s used"
            chunks = state_chunks([sp for _, _, sp in todo])
            asked, stopped = set(), None
            for names, box in ([] if over else chunks):
                # the budget is checked before each query, not only between states: a state whose names split into
                # several chunks stops at the budget too (review 2026-11-03 P3-9); its asked chunks still count
                if budget is not None and time.monotonic() - started > budget:
                    stopped = f"time budget of {budget:g} s used"
                    break
                resp, how = state_fetch(state_query(names, box), mirrors, a.refresh, a.offline)
                if resp is None:
                    failed = how
                    break
                via.add(how)
                elements.append(resp)
                asked.update(names)
            self.osm_states[state] = {"targets": len(items), "queries": len(chunks), "sent": len(elements),
                                      "failed": failed or stopped, "via": sorted(via)}
            print(f"  {state}: {len(items)} names, {len(todo)} asked in "
                  f"{self.osm_states[state]['queries']} quer{'y' if self.osm_states[state]['queries'] == 1 else 'ies'}"
                  f"{f'; FAILED ({failed})' if failed else ''}{f'; stopped after {len(elements)} ({stopped})' if stopped else ''}", flush=True)
            for t, row, spec in items:
                self.osm_used += 1
                not_asked = bool(stopped) and not {spec["name"], *(spec.get("osm_names") or [])} <= asked
                if WX.is_cached(spec, spec["key"], a.refresh):        # the per-name run's answer
                    d = json.loads((WX.CACHE_DIR / f"{spec['key']}.json").read_text())
                elif failed or not_asked:
                    failed_here = failed or stopped
                    why = ("OSM fallback not tried this run (time budget used)" if failed_here.startswith("time budget")
                           else f"OSM state query for {state} failed twice ({failed})")
                    row["reason"] = f"{row['reason']}; {why}: left for the next run"
                    self.osm_remaining.append(f"{state}: {t['name']}")
                    continue
                else:
                    parts = [for_spec(r, spec) for r in elements]
                    d = {"elements": [e for p in parts for e in p["elements"]],
                         "osm3s": next((p["osm3s"] for p in parts if p["osm3s"]), None),
                         "_fetched_at": next((p["_fetched_at"] for p in parts if p["_fetched_at"]), None)}
                    seen, uniq = set(), []
                    for e in d["elements"]:
                        if (e["type"], e["id"]) not in seen:
                            seen.add((e["type"], e["id"]))
                            uniq.append(e)
                    d["elements"] = uniq
                try:
                    rec, how = osm_record(t, spec, d, self.states, self.towns, self.existing_list)
                except Exception as ex:      # a malformed element must not stop the run
                    self.problems.append(f"{t['key']}: OSM fallback {type(ex).__name__}: {ex}")
                    continue
                if rec is None:
                    row["reason"] = f"{row['reason']}; {how}" if row["reason"] else how
                    continue
                k = ("osm", t["state"], slugify(rec["name"]))
                if k not in self.feats:
                    rec.update(_targets=[], _weight=0, _slug_towns=Counter(), _key=k,
                               aliases=list(rec.get("aliases") or []))
                    self.feats[k] = rec
                self.attach(self.feats[k], row, t, how)
                row["reason"] = None

    def osm_one(self, t, row):
        a = self.args
        self.osm_used += 1
        rec, how = osm_fallback(t, self.states, self.towns, self.existing_list, a.refresh, a.offline)
        if rec is None:
            row["reason"] = f"{row['reason']}; {how}" if row["reason"] else how
            return
        k = ("osm", t["state"], slugify(rec["name"]))
        if k not in self.feats:
            rec.update(_targets=[], _weight=0, _slug_towns=Counter(), _key=k, aliases=list(rec.get("aliases") or []))
            self.feats[k] = rec
        self.attach(self.feats[k], row, t, how)
        row["reason"] = None

    def checkpoint(self, i, n):
        built = [r for r in self.feats.values() if not r.get("_existing")]
        if len(built) - self.last_written >= CHECKPOINT_EVERY:
            self.last_written = len(built)
            assign_slugs(built, self.existing, getattr(self, "previous", None), getattr(self, "kept_rows", None))
            try:
                info = write_output(built, finish_rows(self.rows), skipped_list(self.skipped_reason), [], partial=True,
                                    scope_states=getattr(self, "only_states", None),
                                    rows_from=getattr(self, "rows_from", None))
            except WriteRefused as ex:      # an unreadable file: not overwritten; the next checkpoint tries again
                print(f"[{i}/{n}] checkpoint not written: {ex}", flush=True)
                return
            print(f"[{i}/{n}] {len(built)} records this run, {info['written']} in the file; requests {dict(self.http.fetched)} cached "
                  f"{sum(self.http.cached.values())} failed {dict(self.http.failed)}", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="refetch even when a cached response exists")
    ap.add_argument("--offline", action="store_true", help="use only cached responses")
    ap.add_argument("--limit", type=int, help="resolve only the first N targets (most events first)")
    ap.add_argument("--targets-only", action="store_true", help="print the target table and stop")
    ap.add_argument("--no-osm", action="store_true", help="no OpenStreetMap fallback")
    ap.add_argument("--osm-max", type=int, default=600, help="at most this many OSM fallback queries (was 120)")
    ap.add_argument("--osm-only", action="store_true",
                    help="keep the last full run's records and run only the OSM fallback (for the names NHDPlus "
                         "could not name and OSM was not yet asked about) and the hand records; writes once at the end")
    ap.add_argument("--osm-budget", type=float, default=180.0,
                    help="seconds the OSM fallback may spend on Overpass in one run (default 180); names not "
                         "reached are left for the next run, so a scheduled refresh is never held up")
    ap.add_argument("--place-budget", type=float, default=120.0,
                    help="seconds the pass over the other places of a name (Run.place_pass) may spend in one run "
                         "(default 120); places not reached are left for the next run")
    ap.add_argument("--osm-per-name", action="store_true",
                    help="with --osm-only: one Overpass query per name (slow) instead of one per state")
    ap.add_argument("--hydrolocation", action="store_true",
                    help="ask NLDI hydrolocation for every point (slow in Nov 2026); default: comid/position")
    ap.add_argument("--rebuild", action="store_true",
                    help="let the final write replace data/waters-nhd.json with this run's records even when that "
                         "is fewer than the file holds (default: merged into it, and refused when fewer)")
    ap.add_argument("--state", action="append", metavar="XX",
                    help="a state build (repeatable): the targets are the national list's rows for these states "
                         "(data/receiving-waters-national.json), live or not; see the module docstring")
    ap.add_argument("--budget-s", type=float, help="stop starting network requests after this many seconds; what is "
                                                   "built is written and the next run resumes from the cache")
    ap.add_argument("--hr-budget", type=float, default=900.0,
                    help="a state build: seconds the NHD high-resolution pass may spend (default 900)")
    ap.add_argument("--max-requests", type=int, help="at most this many network requests in the run (cached answers "
                                                     "are free); the run then stops cleanly and the next one resumes")
    ap.add_argument("--tidy", action="store_true",
                    help="with --state: no build, nothing fetched: the state's records that duplicate an "
                         "openboatlaunch record now on file (resolve_existing_duplicates), its target rows' reasons in "
                         "public voice (public_reasons), its 'Unnamed stream' records named for their town "
                         "(name_unnamed_streams)")
    ap.add_argument("--names", metavar="FILE",
                    help="a state's report names (research/<st>/receiving-waters-missing.json) as the targets, with "
                         "--state XX: the name pass on each, merged into data/waters-nhd.json as rows from the reports; "
                         "FILE is rewritten to the names still without a record, each with its reason")
    ap.add_argument("--add-places", action="store_true",
                    help="with --names: nothing built or fetched; the file's rows gain the points and towns of the "
                         "state's reports in data/build/events that give each name")
    args = ap.parse_args(argv)
    if args.names:
        if args.rebuild or args.osm_only or args.tidy or (args.state and len(args.state) > 1):
            ap.error("--names takes one --state and no --rebuild, --osm-only or --tidy")
        return names_main(args)
    if args.add_places:
        ap.error("--add-places needs --names")
    if args.tidy:
        if not args.state:
            ap.error("--tidy needs --state")
        return tidy_main(args.state)
    if args.state:
        if args.rebuild or args.osm_only:
            ap.error("--state merges into data/waters-nhd.json: no --rebuild or --osm-only")
        return state_main(args)
    if args.rebuild and args.limit:
        ap.error("--rebuild with --limit would replace the file with the records of the first N targets")
    if args.osm_only:
        return osm_only(args)

    existing = existing_waters()
    _, events, _ = S.load_events(EVENTS_DIR, False, False)
    t0 = time.time()
    targets, skipped, skipped_reason, stats, _ = collect_targets(existing, events)
    print(f"targets collected in {time.time() - t0:.0f} s: {dict(stats)}")
    print_targets(targets, None if args.targets_only else 60)
    if args.targets_only:
        for k, n in skipped.most_common():
            print(f"skipped {n:6}  {k}")
        return 0

    http = Http(args.refresh, args.offline, max_requests=args.max_requests,
                deadline=time.monotonic() + args.budget_s if args.budget_s else None)
    states = States()
    towns = Towns(http)
    nhd = Nhd(http, states, towns)
    nhd.use_hydrolocation = args.hydrolocation

    run = Run(nhd, states, towns, existing, args, http, skipped_reason)
    todo = targets[:args.limit] if args.limit else targets
    for i, t in enumerate(todo, 1):
        if run.stopped:
            run.not_reached(t)
            continue
        try:
            run.resolve(t)
        except BudgetExhausted as ex:
            run.stop(t, ex)
        except Exception as ex:      # one bad feature must not stop the run
            import traceback
            traceback.print_exc()
            run.problems.append(f"{t['key']}: {type(ex).__name__}: {ex}")
            row = run.rows[-1] if run.rows and run.rows[-1]["_key"] == t["key"] else None
            if row is not None and not row["how"]:
                row["reason"] = row["reason"] or f"build error ({type(ex).__name__}: {ex})"
        run.checkpoint(i, len(todo))
    pairs = list(zip(todo, run.rows)) if len(run.rows) == len(todo) else \
        [(t, r) for t in todo for r in run.rows if r["_key"] == t["key"]]
    run.place_pass(pairs)
    print(f"NHD pass done: {sum(1 for r in run.feats.values() if not r.get('_existing'))} records; "
          f"OSM fallback for {min(len(run.osm_queue), args.osm_max)} of {len(run.osm_queue)} targets", flush=True)
    if args.osm_per_name:
        run.osm_pass()            # one Overpass query per name: slow, kept for debugging a single name
    else:
        run.osm_state_pass()      # one query per state, within --osm-budget seconds
    run.hand_pass(pairs)
    feats, target_rows, problems = run.feats, run.rows, run.problems
    recs = [r for r in feats.values() if not r.get("_existing")]
    for r in recs:
        if not r["towns"]:      # no Census town or place crossed: the towns of the reports' points
            r["towns"] = sorted(x for x, n in r["_slug_towns"].most_common(3) if n)
            r["towns_from"] = "the Census places of the outfalls' and notices' points"
    assign_slugs(recs, existing, run.previous, run.kept_rows)
    problems += validate(recs, states)
    taken = set(existing)
    problems += [f"slug {r['slug']} collides with an existing record" for r in recs if r["slug"] in taken]
    rows = finish_rows(target_rows)
    unmapped = [r for r in rows if not r["slugs"] and not r["reason"]]
    problems += [f"target {r['state']} {r['name']}: neither mapped nor given a reason" for r in unmapped]

    ev_eval = evaluate(existing, recs, events)
    newly = ev_eval["before"]["ids"] - ev_eval["after"]["ids"]
    kinds = Counter(r["kind"] for r in recs)
    stats_out = {"targets": len(todo), "targets_mapped": sum(1 for r in rows if r["slugs"]),
                 "targets_unmapped": sum(1 for r in rows if not r["slugs"]),
                 "records": len(recs), "records_by_kind": dict(kinds),
                 "records_by_source": dict(Counter(r["source"] for r in recs)),
                 "events_unplaced_before": ev_eval["before"]["unplaced"],
                 "events_unplaced_after": ev_eval["after"]["unplaced"],
                 "events_newly_placed": len(newly),
                 "events_unplaced_with_text_before": ev_eval["before"]["unplaced_with_text"],
                 "events_unplaced_with_text_after": ev_eval["after"]["unplaced_with_text"],
                 "other_places": run.place_stats,
                 "requests": dict(http.fetched), "cached": dict(http.cached), "failed": dict(http.failed)}
    if run.stopped:
        stats_out["stopped"] = run.stopped
    try:
        info = write_output(recs, rows, skipped_list(skipped_reason), problems, partial=bool(args.limit or run.stopped),
                            stats=stats_out, final=True, rebuild=args.rebuild and not run.stopped)
    except WriteRefused as ex:
        print(f"\nNOT WRITTEN: {ex}")
        for p in problems[:40]:
            print("PROBLEM", p)
        return 1

    print(f"\n{'slug':44} {'kind':9} {'size':>11} targets  towns")
    for r in sorted(recs, key=lambda r: -r["_weight"])[:80]:
        size = f"{r['length_km']:.1f} km" if r.get("length_km") is not None else f"{r['area_km2']:.3f} km2"
        print(f"{r['slug'][:44]:44} {r['kind']:9} {size:>11} {r['_targets_n']:7}  {'; '.join(r['towns'][:4])}")
    print(f"\n{len(recs)} records by kind {dict(kinds)} -> {shown(OUT)}: {describe_write(info)}")
    print(json.dumps({k: v for k, v in stats_out.items()}, indent=1))
    reasons = Counter(re.sub(r"\(.*", "", r["reason"] or "").strip() for r in rows if not r["slugs"])
    for k, n in reasons.most_common(12):
        print(f"unmapped {n:5}  {k}")
    for p in problems[:40]:
        print("PROBLEM", p)
    return 0                       # problems are listed above and kept in stats; the file was written


def state_stats(states, targets, rows, recs, tstats, http, run) -> dict:
    """Per state: targets by define_by, records built by how they were defined, targets failed with their reasons."""
    out = {}
    for st in states:
        t_st = [t for t in targets if t["state"] == st]
        r_st = [r for r in rows if r["state"] == st]
        built = [r for r in recs if r["state"] == st]
        by_rec = Counter()
        for r in built:
            ways = {row.get("defined_by") for row in r.get("_targets") or [] if row.get("defined_by")}
            by_rec[sorted(ways, key=lambda w: DEFINE_ORDER.get(w, 9))[0] if ways else ("hand" if r.get("hand") else
                                                                                          r.get("source") or "other")] += 1
        failed = [r for r in r_st if not r["slugs"]]
        out[st] = {"built": now_iso(), "targets": len(t_st),
                   "targets_by_define_by": dict(Counter(t["define_by"] for t in t_st)),
                   "targets_mapped": sum(1 for r in r_st if r["slugs"]),
                   "targets_mapped_by": dict(Counter(r.get("defined_by") or "existing record" for r in r_st if r["slugs"])),
                   "targets_failed": len(failed),
                   "failed_reasons": dict(Counter(re.sub(r"\s*\(.*", "", r["reason"] or "no reason")[:120]
                                                  for r in failed).most_common(15)),
                   "records": len(built), "records_by_define_by": dict(by_rec),
                   "records_by_kind": dict(Counter(r["kind"] for r in built)),
                   "no_water": dict(Counter(why for (s_, _), why in run.skipped_reason.items() if s_ == st))}
    shared = {"requests": dict(http.fetched), "network_requests": http.requests, "cached": dict(http.cached),
              "failed": dict(http.failed), "stopped": run.stopped, "other_places": run.place_stats}
    for v in out.values():
        v["run"] = shared
    return out


def tidy_main(states, path=None, aliases_path=None) -> int:
    """--state XX --tidy (offline, after a state build or a new openboatlaunch extract): resolve_existing_duplicates
    on data/waters-nhd.json, the aliases into data/water-aliases.json (merged, sorted by slug), public_reasons and
    name_unnamed_streams; the counts and actions under stats.state_builds.<ST>.existing_duplicates. Then rerun
    `python -m ingest.outfall_waters --state XX` so the outfall rows follow the slugs."""
    states = sorted({x.upper() for x in states})
    path = path or OUT
    aliases_path = aliases_path or (DATA_DIR / S.WATER_ALIASES_FILE)
    S._GEOM_CACHE.clear()
    existing = existing_waters()
    doc = read_json(path) or {}
    new, actions, aliases = resolve_existing_duplicates(doc, existing, states)
    voiced = public_reasons(new, set(states))
    named, unnamed_left = name_unnamed_streams(new, states)
    actions += named
    builds = dict((new.get("stats") or {}).get("state_builds") or {})
    for st in states:
        # a later pass adds to the earlier ones' actions (the counts are of all of them)
        prev = (builds.get(st) or {}).get("existing_duplicates") or {}
        mine = list(prev.get("actions") or []) + [a for a in actions if a["to"].endswith(f"-{st.lower()}")]
        # a pass that repeats an earlier action (a rebuild reset a row the tidy had mapped) is not counted twice
        mine = list({json.dumps(a, sort_keys=True): a for a in mine}.values())
        builds[st] = {**(builds.get(st) or {}), "existing_duplicates": {
            "date": now_iso()[:10], "dropped": sum(a["action"] == "dropped" for a in mine),
            "renamed": sum(a["action"] == "renamed" for a in mine),
            "rows_mapped": sum(a["action"] == "mapped" for a in mine),
            "unnamed_named": sum(a["action"] == "named" for a in mine),
            "unnamed_left": [x for x in unnamed_left if x.endswith(f"-{st.lower()}")], "actions": mine}}
    new["stats"] = {**(new.get("stats") or {}), "state_builds": dict(sorted(builds.items()))}
    if actions or voiced:
        new["count"] = len(new["waters"])
        write_json(path, new)
    if aliases:
        cur = read_json(aliases_path) or {}
        for k, v in aliases.items():
            cur[k] = list(dict.fromkeys(list(cur.get(k) or []) + v))
        aliases_path.write_text(json.dumps(dict(sorted(cur.items())), indent=1, ensure_ascii=False) + "\n")
    for a in actions:
        print(f"  {a['action']:8} {a['slug'] or 'row ' + repr(a.get('row'))} -> {a['to']}: {a['why']}")
    print(f"{', '.join(states)}: {sum(a['action'] == 'dropped' for a in actions)} NHD records dropped for the "
          f"openboatlaunch record of the same water, {sum(a['action'] == 'renamed' for a in actions)} renamed off an "
          f"openboatlaunch slug, {sum(a['action'] == 'mapped' for a in actions)} target rows without a record mapped "
          f"to the one now carrying their name; {len(aliases)} records given aliases in {shown(aliases_path)}; "
          f"{voiced} target rows' reasons put in public voice (the detail in reason_detail); "
          f"{len(named)} 'Unnamed stream' records named for their town"
          + (f", left as they are (no town): {', '.join(unnamed_left)}" if unnamed_left else ""))
    return 0


def state_main(args) -> int:
    """--state XX [--state YY]: a state build from the national target list (module docstring, "A state build")."""
    states = sorted({s.upper() for s in args.state})
    bad = [s for s in states if s not in FIPS]
    if bad:
        print(f"unknown state code {', '.join(bad)}")
        return 2
    existing = existing_waters()
    S._STATES = S.derive_states(existing, S.load_rules(), live_only=False) | set(states)
    S._GEOM_CACHE.clear()
    targets, skipped_reason, tstats = collect_state_targets(states, existing)
    print(f"state build {', '.join(states)}: {dict(tstats)}")
    print_targets(targets, None if args.targets_only else 40)
    if args.targets_only:
        for (st, text), why in sorted(skipped_reason.items()):
            print(f"no water {st}  {text[:50]:50}  {why}")
        return 0
    http = Http(args.refresh, args.offline, max_requests=args.max_requests,
                deadline=time.monotonic() + args.budget_s if args.budget_s else None)
    shapes = States()
    towns = Towns(http)
    nhd = Nhd(http, shapes, towns)
    nhd.use_hydrolocation = args.hydrolocation
    run = Run(nhd, shapes, towns, existing, args, http, skipped_reason)
    run.only_states = set(states)
    try:
        for st in states:
            towns.load(st)
        run.reach_index = reach_index(nhd, [c for t in targets for c in t.get("reach_ids") or []],
                                      [c for t in targets for c in t.get("nhdplus_ids") or []])
        print(f"EPA reach index: {len(run.reach_index)} keys", flush=True)
    except BudgetExhausted as ex:
        run.stopped = str(ex)
    todo = targets[:args.limit] if args.limit else targets
    for i, t in enumerate(todo, 1):
        if run.stopped:
            run.not_reached(t)
            continue
        try:
            run.resolve(t)
        except BudgetExhausted as ex:
            run.stop(t, ex)
        except Exception as ex:      # one bad feature must not stop the run
            import traceback
            traceback.print_exc()
            run.problems.append(f"{t['key']}: {type(ex).__name__}: {ex}")
            row = run.rows[-1] if run.rows and run.rows[-1]["_key"] == t["key"] else None
            if row is not None and not row["how"]:
                row["reason"] = row["reason"] or f"build error ({type(ex).__name__}: {ex})"
        run.checkpoint(i, len(todo))
    pairs = [(t, r) for t, r in zip(todo, run.rows)]
    if not run.stopped:
        run.place_pass([(t, r) for t, r in pairs if t["name"]])
        run.hr_pass(pairs, args.hr_budget)
        run.osm_queue = [(t, r) for t, r in run.osm_queue if not r["how"]]
        if not args.no_osm:
            run.osm_state_pass()
        run.hand_pass(pairs)
    else:
        for t, row in run.osm_queue:
            row["reason"] = f"{row['reason']}; OSM fallback not tried ({run.stopped})"
    recs = [r for r in run.feats.values() if not r.get("_existing")]
    for r in recs:
        if not r["towns"]:
            r["towns"] = sorted(x for x, n in r["_slug_towns"].most_common(3) if n)
            r["towns_from"] = "the Census places of the outfalls' points"
    assign_slugs(recs, existing, run.previous, run.kept_rows)
    problems = run.problems + validate(recs, shapes)
    problems += [f"slug {r['slug']} collides with an existing record" for r in recs if r["slug"] in existing]
    rows = finish_rows(run.rows)
    problems += [f"target {r['state']} {r['name']}: neither mapped nor given a reason" for r in rows
                 if not r["slugs"] and not r["reason"]]
    stats_out = state_stats(states, todo, rows, recs, tstats, http, run)
    try:
        info = write_output(recs, rows, skipped_list(skipped_reason), problems, partial=True, stats=stats_out,
                            final=True, scope_states=set(states))
    except WriteRefused as ex:
        print(f"\nNOT WRITTEN: {ex}")
        return 1
    print(f"\n{len(recs)} records -> {shown(OUT)}: {describe_write(info)}")
    print(json.dumps(stats_out, indent=1))
    for p in problems[:40]:
        print("PROBLEM", p)
    return 0


# ---------------------------------------------------------------- report names (--names, 2026-11-04)
# The receiving-water names a state's reports give that no water record holds yet (research/<st>/receiving-waters-
# missing.json, written by each state's build: North Carolina's DWR overflow layers, Georgia's EPD lists and EPA's
# overflow reports, Florida's DEP pollution notices). The state build above targets the national list (outfalls and
# permits), not these names; the live (no --state) build targets unplaced events, which need data/build/events.

REPORT_FIX = [(re.compile(r"\bun-?n?am+ed\b", re.I), "unnamed"),
              (re.compile(r"\btrib(?:ua|au|uat|u)tary\b|\btribuatary\b|\btributray\b", re.I), "tributary"),
              (re.compile(r"^\s*icw\s*$", re.I), "Intracoastal Waterway"),
              (re.compile(r"\bintercoastal\b", re.I), "Intracoastal")]
# a report's text that names no public water (checked on the whole text, before any name is read from it)
REPORT_NOT_WATER = [
    (re.compile(r"\bms4\b|\bmunicipal separate storm", re.I), "a storm-sewer system (MS4), not a named water"),
    (re.compile(r"\bstorm\s*water\b|\bstorm\s*(drain|drains|sewer|sewers|system|pipe|line|inlet)\b", re.I),
     "a storm-sewer system, not a named water"),
    (re.compile(r"\b(catch\s+basin|manhole|lift\s+station|pump\s+station|aeration\s+basin|clarifier|backwash|"
                r"equalization|(retention|detention|drainage|holding)\s+pond)\b", re.I),
     "part of a sewer, drainage or treatment works, not a public water"),
    (re.compile(r"\b(subdivision|resident'?s?|yard|private|parking|driveway|basement|crawl\s*space)\b", re.I),
     "private property, not a public water"),
    (re.compile(r"\bgulf\s+of\s+(mexico|america)\b|\b(atlantic|pacific)\s+ocean\b|^\s*(the\s+)?ocean\s*$", re.I),
     "the open sea (no NHD record)"),
]
STREET_NAME = re.compile(r"^[\w' .-]+?\s+(ct|st|rd|ave|av|dr|ln|blvd|cir|trce|trl|pkwy|hwy|ter|pl|way|court|street|"
                         r"road|avenue|drive|lane|boulevard|circle|trace|trail|parkway|highway|terrace|place)\.?$", re.I)
TRIB_LEAD = re.compile(r"^(an?\s+|the\s+)?(unnamed\s+|unknown\s+|small\s+)?(tributary|tributaries|trib\.?|unt|ut)"
                       r"(\s+(of|to|into)\b)?\s*(the\s+)?", re.I)
TRIB_ANY = re.compile(r"\b(tributary|tributaries|trib|unt|ut)\b", re.I)
REPORT_TOWN_M = 3000        # a water of the name within 3 km of a town the reports give (the name pass's rule)


def report_name_parts(text: str) -> tuple[list[str], str | None, bool]:
    """(water names, reason, tributary) for one receiving-water name as a report gives it. A tributary of a named water
    ('Tributary to Proctor Creek', 'UT Eno River', 'Ditch feeding Rocky Creek', 'Bull creek tributary') gives the named
    water (the tributary has no name of its own and its water reaches that one), tributary True. reason: why the text
    names no public water (storm-sewer systems, catch basins and treatment works, private property, the open sea, street
    names, an unnamed or unknown stream, a kind of water with no name, a river basin), never a record."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    for rx, rep in REPORT_FIX:
        t = rx.sub(rep, t)
    fixed = t
    # a chain ('Stormdrain to UT of Island Creek', 'Catch basin to Fall Mountain Lake'): the storm drain or sewer works
    # the report names first is the way, the water after it the receiving water
    chain = re.split(r"\s+(?:to|into|via|then|thence|(?:flows?|flowing|discharges?|discharging|leading|draining)\s+(?:in)?to)\s+",
                     t, flags=re.I)
    through = None
    while chain:
        why = next((w for rx, w in REPORT_NOT_WATER if rx.search(chain[0])), None)
        if why is None:
            break
        if len(chain) == 1:
            return [], why, False
        through = through or why
        chain = chain[1:]
    if through or len(chain) > 1:
        why = next((w for rx, w in REPORT_NOT_WATER if rx.search(" ".join(chain))), None)
        if why:
            return [], why, False
    if through:
        t = " to ".join(chain)
        if not TRIB_ANY.search(t) and not re.match(r"^(an?|the)\s+", t, re.I):
            t = f"tributary to {t}"         # through a storm drain: the water it reaches is named, not where it entered
    t = re.sub(r",\s*(a|which is a|that is a)\s+(trib|tributary)\b.*$", "", t, flags=re.I)
    t = re.sub(r"\b(that|which)\s+(runs|flows|drains|leads|goes)\s+(in)?to\b", "to", t, flags=re.I)
    t = re.sub(r"^\s*(the\s+)?(drainage\s+)?(ditch|swale|creek|stream|branch|channel)\s+(feeding|leading\s+to|draining\s+"
               r"(in)?to|running\s+(in)?to|flowing\s+(in)?to)\s+", "tributary to ", t, flags=re.I)
    tributary = bool(TRIB_ANY.search(t))
    prev = None
    while prev != t:
        prev, t = t, TRIB_LEAD.sub("", t, count=1).strip()
    if tributary and re.match(r"^(at|near|behind|by|on|in|off|along|beside|from)\b", t, re.I):
        return [], "an unnamed tributary named by a place, not by the water it joins", False
    if not t or re.fullmatch(r"(unnamed|unknown|unk)?\s*(creek|stream|branch|tributary|pond|lake|ditch|canal|river)?", t, re.I):
        return [], ("an unnamed or unknown stream: the report names no water" if re.search(r"unnamed|unknown|unk|trib", fixed, re.I)
                    else "a kind of water with no name"), False
    if STREET_NAME.match(t) and not has_kind(words(t)[:-1]):
        return [], "a street name, not a water", False
    parts, why = national_parts(t)
    if not parts and why and why.startswith(("a county", "a road")) and has_kind(words(t)):
        parts = split_names(t, False)       # 'County Home Branch', 'Mill Road Branch': a water's own name
    if not parts:
        if why and why.startswith("a river basin"):
            why = "a basin (a river basin, or a stormwater, treatment or marina basin), not a water's name"
        elif tributary:
            why = "a tributary named by a place, not by the water it joins"
        elif re.fullmatch(r"[A-Za-z]{3,4}", t.strip()):
            why = "a short name with no kind of water (creek, river, lake): not looked up"
        return [], (why or "no water name").replace("in EPA's receiving-water field", "in the report"), False
    return parts, None, tributary


def read_names_file(path) -> tuple[dict, list[dict]]:
    """(the file's own keys, its rows) for the three shapes the states wrote: North Carolina {rows: [{name, reports,
    points [[lat, lon]], permits, stream_index, sources}]}, Georgia {names: [{name, reports, seen_in, kind}]}, Florida
    [[name, reports]], and this module's own rewrite {rows: [...]}. Rows keep every field they carry."""
    d = read_json(path)
    if isinstance(d, list):
        meta, rows = {}, [{"name": r[0], "reports": r[1]} if isinstance(r, list) else dict(r) for r in d]
    else:
        meta = {k: v for k, v in (d or {}).items() if k not in ("rows", "names")}
        rows = [dict(r) for r in (d or {}).get("rows") or (d or {}).get("names") or []]
    for r in rows:
        r["reports"] = int(r.get("reports") or 0)
    rows.sort(key=lambda r: (-r["reports"], str(r.get("name") or "")))
    return meta, rows


def state_discharger_towns(state: str) -> dict:
    """{permit or discharger id: [towns]} from research/<st>/dischargers.json and data/dischargers.json."""
    out = defaultdict(list)
    for p in (ROOT / "research" / state.lower() / "dischargers.json", DATA_DIR / "dischargers.json"):
        d = read_json(p) if p.exists() else None
        for r in (d.get("dischargers") if isinstance(d, dict) else d) or []:
            if not isinstance(r, dict) or (r.get("state") or state) != state:
                continue
            for k in (r.get("npdes_permit"), r.get("id")):
                if k:
                    out[k] += [x for x in r.get("towns") or [] if x and x not in out[k]]
    return out


def report_places(state: str, rows: list[dict], events, towns_by_permit: dict | None = None) -> dict:
    """{row name: {"points": Counter((lon, lat)), "towns": Counter, "sources": Counter}} from the state's reports whose
    waterbody text (or one of the water names the source read from its text, raw._water_names) is the row's name, case
    and punctuation aside; and from the operators the row names (permits) through the registry's towns."""
    by_key = defaultdict(list)
    for r in rows:
        by_key[compact(r["name"])].append(r["name"])
    dis = state_discharger_towns(state)
    reg = towns_by_permit if towns_by_permit is not None else registry_towns({state})
    out = {r["name"]: {"points": Counter(), "towns": Counter(), "sources": Counter()} for r in rows}

    def permit_towns(key):
        return list(dis.get(key) or []) + [t for t, _ in (reg.get(key) or Counter()).most_common(2)]
    for r in rows:
        for p in r.get("permits") or []:
            for tw in permit_towns(p):
                out[r["name"]]["towns"][str(tw).title()] += 1
    for ev in events:
        texts = [ev.get("waterbody_text") or ""] + list(((ev.get("raw") or {}).get("_water_names") or []))
        names = {n for x in texts if x for n in by_key.get(compact(x), [])}
        if not names:
            continue
        if S.event_state(ev) != state:
            continue
        raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
        row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
        tws = [raw.get("FACILITY_CITY"), row.get("city")] + [raw.get(k) for k in S.TOWN_KEYS]
        tws += permit_towns(ev.get("npdes_permit")) + permit_towns(ev.get("discharger_id"))
        tws = [re.sub(r",\s*(fl|fla|florida|ga|georgia|nc|north carolina)\.?$", "", str(x).strip(), flags=re.I).title()
               for x in tws if isinstance(x, str) and x.strip() and not re.search(r"\d", x)]
        for n in names:
            o = out[n]
            o["sources"][ev.get("source_id") or "?"] += 1
            if ev.get("lat") is not None and ev.get("lon") is not None:
                o["points"][(round(float(ev["lon"]), 5), round(float(ev["lat"]), 5))] += 1
            for tw in dict.fromkeys(tws):
                o["towns"][tw] += 1
    return out


def add_places(path, state: str, events_dir=None) -> int:
    """--names FILE --add-places (nothing fetched): each row of the names file gains `towns` (the reports' own town
    fields and the towns of the operators they name, most reports first) and `points` ([lat, lon], up to five places
    2 km apart, most reports first) from the state's reports in data/build/events, and `places_from` (the sources).
    A row's own points and towns are kept first. The build reads only the file, so its places are on the record."""
    meta, rows = read_names_file(path)
    S._STATES = S.derive_states(S.load_waters(include_nhd=False), S.load_rules(), live_only=False) | {state}
    _, events, _ = S.load_events(events_dir or EVENTS_DIR, False, False)
    places = report_places(state, rows, events)
    n = 0
    for r in rows:
        p = places[r["name"]]
        pts = Counter({(lon, lat): 2 for lat, lon in r.get("points") or []}) + p["points"]
        if pts:
            r["points"] = [[lat, lon] for lon, lat in cluster_points(pts, n=5, sep_m=NEAR_M)]
        tws = list(dict.fromkeys(list(r.get("towns") or []) + [t for t, _ in p["towns"].most_common(4)]))
        if tws:
            r["towns"] = tws[:4]
        if p["sources"]:
            r["places_from"] = sorted(p["sources"])
        n += bool(pts or tws)
    write_names_file(path, meta, state, rows, None)
    print(f"{state}: {n} of {len(rows)} names given places from {len(events)} reports -> {shown(path)}")
    return 0


def reason_kind(reason: str, multi: bool = False) -> str:
    """A row's reason as counted in the file's by_reason: the first clause, without the place or the date detail ('(the
    nearest is 2.2 km away)', '(35.36514, -80.14824)') and, for a text naming several waters, without the water's name."""
    r = re.sub(r"^[^:;(]*?: ", "", reason) if multi else reason
    r = r.split("; ")[0]
    r = re.sub(r"\s*\((?=[^()]*(\d+\.\d|\d{4}-\d\d))[^()]*\)", "", r)       # a distance, a point or a date
    return r.strip()[:120]


def write_names_file(path, meta: dict, state: str, rows: list[dict], resolved: list[dict] | None,
                     run_note: dict | None = None) -> None:
    """The names file in one shape for the three states: the file's own keys, `rows` (the names still without a water
    record, most reports first, each with its reason once a build has run), `resolved` (the names a record now holds,
    with the slugs and how), and the counts."""
    old_resolved = list(meta.get("resolved") or [])
    if resolved is not None:
        done = {r["name"] for r in resolved}
        resolved = [r for r in old_resolved if r["name"] not in done] + resolved
    else:
        resolved = old_resolved
    resolved.sort(key=lambda r: (-r.get("reports", 0), r["name"]))
    rows = sorted(rows, key=lambda r: (-r["reports"], r["name"]))
    keep = {k: v for k, v in meta.items() if k not in ("waters", "count", "reports", "by_kind", "by_reason", "resolved",
                                                        "resolved_names", "resolved_reports", "rows", "names", "build")}
    if not keep.get("about"):
        keep = {"about": f"Receiving-water names in {state}'s reports that data/receiving-waters-national.json does not "
                         f"hold for {state}, by name as typed, with the number of reports giving each.", **keep}
    doc = {**keep, "state": state, "waters": len(rows), "reports": sum(r["reports"] for r in rows)}
    if any(r.get("kind") for r in rows):
        doc["by_kind"] = dict(Counter(r["kind"] for r in rows if r.get("kind")).most_common())
    reasons = Counter(reason_kind(r["reason"], multi=len(r.get("parts") or []) > 1) for r in rows if r.get("reason"))
    if reasons:
        doc["by_reason"] = dict(reasons.most_common())
    if resolved:
        doc["resolved_names"] = len(resolved)
        doc["resolved_reports"] = sum(r.get("reports", 0) for r in resolved)
    if run_note:
        doc["build"] = run_note
    doc["rows"] = rows
    if resolved:
        doc["resolved"] = resolved
    write_json(path, doc)


def has_record_at(resolver: S.Resolver, name: str, state: str, places: list[tuple], towns: list[str]) -> list[str]:
    """The water records the status resolver gives a report of this name in the state (the name, an alias or a stem,
    kept by the placement guard) at the reports' places: each point, else each town, else with no place."""
    tries = [(lat, lon, towns[0] if towns else "") for lon, lat in places[:3]] or \
            [(None, None, tw) for tw in towns[:3]] or [(None, None, "")]
    out = []
    for lat, lon, tw in tries:
        ev = {"lat": lat, "lon": lon, "raw": {"state": state, "town": tw}, "waterbody_text": name}
        slugs, _, _ = resolver.by_name(name, state, lat, lon, ev)
        if slugs:
            kept, _ = resolver.guard(slugs, ev)
            out += [s for s in kept if s not in out]
    return out


def holds_name(rec: dict, name: str) -> bool:
    """Whether a water record carries the name itself (its name or an alias, spelling aside, or the name without its
    kind word): not only by the status resolver's qualifier rule, which gives 'West Fork Deep River' to the Deep River."""
    ws = words(name)
    for n in [rec.get("name") or ""] + list(rec.get("aliases") or []):
        sc = name_score(ws, n)
        if sc in (1.0, 0.85) or (sc == 0.8 and abs(len(compact(ws)) - len(compact(gnis_display(n) or ""))) <= 2):
            return True
    return False


def collect_name_targets(state: str, rows: list[dict], resolver: S.Resolver, waters: dict | None = None):
    """(targets, done, skipped_reason): one target per water name a row gives (most reports first), with the row's
    report count, points and towns; done: [(target, slugs)] for names a water record already holds (the status resolver
    places these reports on it and the record carries the name: nothing is built); skipped_reason: {(state, name): why}
    for names that are no water. A name the resolver gives to a record of another name (a fork or branch to its river)
    is built, and its row notes where the resolver puts it today."""
    targets, done, skipped = {}, [], {}
    for r in rows:
        parts, why, trib = report_name_parts(r["name"])
        r["_parts"] = parts
        if not parts:
            skipped[(state, r["name"])] = why
            continue
        pts = Counter()
        for i, (lat, lon) in enumerate(r.get("points") or []):
            pts[(round(float(lon), 5), round(float(lat), 5))] += max(1, r["reports"] // (i + 1))
        tws = [str(x) for x in r.get("towns") or [] if x]
        for p in parts:
            ws = words(p)
            key = (state, compact(ws))
            t = targets.get(key)
            if t is None:
                t = targets[key] = Target(state=state, key=f"{state}:reports:{key[1]}", names=Counter(), texts=Counter(),
                                          outfalls=0, events=0, points=Counter(), towns=Counter(), sources=Counter(),
                                          point_mode=False, refs=[], outfall_points=Counter(), report_rows=[],
                                          tributary=False, notes=[], report_name=True)
            t["names"][p] += r["reports"]
            t["texts"][r["name"]] += r["reports"]
            t["events"] += r["reports"]
            t["points"] += pts
            for tw in tws:
                t["towns"][tw] += r["reports"]
            t["sources"]["reports"] += 1
            t["report_rows"].append(r["name"])
            if trib:
                t["tributary"] = True
                t["notes"].append(f"'{r['name']}': a tributary of {p} (the tributary has no name of its own)")
    out = []
    for t in targets.values():
        t["name"] = t["names"].most_common(1)[0][0]
        t["words"] = words(t["name"])
        places = cluster_points(t["points"], n=3, sep_m=NEAR_M)
        slugs = has_record_at(resolver, t["name"], state, places, [x for x, _ in t["towns"].most_common(3)])
        own = [x for x in slugs if waters is None or holds_name(waters.get(x) or {}, t["name"])]
        if own:
            done.append((t, own))
            continue
        if slugs:
            t["notes"].append(f"the status resolver gives the name to {', '.join(slugs)} (another name): the name's own "
                              f"water is built")
        out.append(t)
    out.sort(key=lambda t: (-t["events"], t["key"]))
    done.sort(key=lambda x: (-x[0]["events"], x[0]["key"]))
    return out, done, skipped


NAME_BATCH = 30             # GNIS spellings asked in one MapServer query (one target's spellings are never split)


def prefetch_names(nhd: Nhd, state: str, targets: list, layer: int, attr: str) -> None:
    """t[attr] = the layer's features whose GNIS name is one of t's spellings in the state's box, for every target, asked
    NAME_BATCH spellings at a time (the same features a query per target gives, for about a thirtieth of the requests;
    a cached batch costs nothing). BudgetExhausted propagates: the targets of the batches not asked have no attr."""
    batch, names = [], []

    def ask():
        if not batch:
            return
        where = "UPPER(gnis_name) IN (" + ",".join(f"'{n}'" for n in sorted(set(names))) + ")"
        fs = arcgis(nhd.http, f"name{layer}", layer, where=where, geometry=nhd.state_env(state),
                    geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                    outFields=FL_FIELDS if layer == 2 else WB_FIELDS, maxAllowableOffset="0.001")
        for t in batch:
            mine = {n.replace("''", "'") for n in sql_names(t)}
            t[attr] = [f for f in fs if str(f.get("gnis_name") or "").upper() in mine]
        batch.clear()
        names.clear()
    for t in targets:
        sn = sql_names(t)
        if batch and len(names) + len(sn) > NAME_BATCH:
            ask()
        batch.append(t)
        names.extend(sn)
    ask()


def report_score(target_ws: list[str], gnis: str | None) -> float:
    """name_score for a report's spelling: 'of' and 'the' aside ('South Fork of Middle River'), and GNIS's 'Atlantic' or
    'Gulf' in front of the Intracoastal Waterway aside."""
    tw = [w for w in target_ws if w not in ("of", "the")]
    gw = [w for w in words(gnis_display(gnis)) if w not in ("of", "the")] if gnis else []
    sc = name_score(tw, " ".join(gw)) if gw else 0.0
    if sc < 0.8 and gw and [w for w in gw if w not in ("atlantic", "gulf")] == tw and "intracoastal" in tw:
        return 0.9
    return sc


def report_name_choices(nhd: Nhd, t) -> tuple[list[tuple], str | None, list[dict]]:
    """([(feature key, choice, how)], reason when none, places that found none): the NHDPlus V2.1 features of the
    target's name in the state (prefetch_names), the one nearest each place the reports give: each cluster of their
    points (a feature within 2 km, NEAR_M), and when no point finds one, each town (crossing it or within 3 km: EPA's
    overflow reports may give the plant's point, while the town is the overflow's); a place two features of the
    name lie equally near chooses neither. With no place, a name found once in the state is taken."""
    st = t["state"]
    groups = defaultdict(list)
    for f in t.get("_l2") or []:
        if f.get("gnis_id") and report_score(t["words"], f.get("gnis_name")) >= 0.8:
            groups[("line", f["gnis_id"])].append(f)
    if wants_area(t) or not groups:
        for f in t.get("_l4") or []:
            if f.get("ftype") in LAKE_FTYPES and report_score(t["words"], f.get("gnis_name")) >= 0.8:
                groups[("wb", f.get("gnis_id") or f["comid"])].append(f)
    shape_ = nhd.states.shapes[st].buffer(0.01)
    groups = {k: v for k, v in groups.items() if any(f["_geom"] is not None and f["_geom"].intersects(shape_) for f in v)}
    if not groups:
        town = nhd.towns.canonical(st, t["name"])
        if town:
            return [], f"the name of a town ({town}), not of a water: no NHD water of that name in {st}", []
        return [], f"no NHD flowline or waterbody of that name in {st}", []

    def pick(k):
        f = groups[k][0]
        if k[0] == "line":
            return {"type": "line", "gnis_id": k[1], "gnis_name": f["gnis_name"], "comid": f["comid"]}
        return {"type": "wb", "comid": f["comid"], "gnis_id": f.get("gnis_id"), "gnis_name": f.get("gnis_name"),
                "ftype": f.get("ftype")}
    geoms = {k: unary_union([f["_geom"] for f in fs if f["_geom"] is not None]) for k, fs in groups.items()}
    several = f" ({len(groups)} waters of that name in {st})" if len(groups) > 1 else ""
    points = [(Point(lon, lat), f"the reports' point ({lat:.5f}, {lon:.5f})", NEAR_M, {"lon": lon, "lat": lat})
              for lon, lat in cluster_points(t["points"], n=6, sep_m=NEAR_M)]
    towns = []
    for tw, _ in t["towns"].most_common(4):
        g = nhd.towns.outlines(st, [tw])
        if g:
            towns.append((unary_union(g), tw, REPORT_TOWN_M, {"town": tw}))
    if not points and not towns:
        if len(groups) == 1:
            k = next(iter(groups))
            return [(feature_key(st, pick(k)), pick(k), f"the only NHD water of that name in {st} (the reports give "
                                                         f"no place)")], None, []
        return [], f"{len(groups)} NHD waters of that name in {st} and the reports give no place to choose one", []
    chosen, failed = {}, []
    # the points first; the towns only when no point finds the name (a report's point may be the operator's plant, as
    # EPA's overflow reports give it, while its town is where the overflow was)
    for place in points + [None] + towns:
        if place is None:
            if chosen:
                break
            continue
        g, label, lim, where = place
        scored = sorted((0.0 if G.intersects(g) else geom_dist_m(G, g), k) for k, G in geoms.items())
        d0, k0 = scored[0]
        if d0 <= lim and (len(scored) == 1 or scored[1][0] > d0 or d0 == 0):
            chosen.setdefault(k0, f"GNIS name in {st}, {'crossing' if d0 == 0 else f'{d0:.0f} m from'} {label}{several}")
        elif d0 <= lim:
            failed.append({**where, "reason": f"two NHD waters of that name lie equally near {label}"})
        else:
            failed.append({**where, "reason": f"no NHD water of that name within {lim / 1000:g} km of {label} (the "
                                              f"nearest is {d0 / 1000:.1f} km away)"})
    if not chosen:
        return [], (f"{len(groups)} NHD water{'s' if len(groups) > 1 else ''} of that name in {st}, none within reach of "
                    f"the reports' places"), failed
    return [(feature_key(st, pick(k)), pick(k), how) for k, how in chosen.items()], None, failed


def wants_hr(reason: str | None) -> bool:
    """Whether a report name the name pass left goes to the NHD high-resolution flowlines: NHDPlus V2.1 has no water of
    the name in the state, or none at the reports' places (a small stream of the name there that V2.1 leaves out);
    not when the reports give no place, or two waters of the name lie equally near."""
    return bool(reason) and (reason.startswith("no NHD flowline") or "none within reach" in reason)


def resolve_hr_places(nhd: Nhd, t) -> tuple[dict | None, str]:
    """resolve_hr for a report name: the reports' points, else the towns they give (the flowline of the name within
    HR_NEAR_DEG of the town's outline)."""
    if t["points"]:
        return resolve_hr(nhd, t)
    names = sql_names(t)
    where = "UPPER(gnis_name) IN (" + ",".join(f"'{n}'" for n in names) + ")"
    for tw, _ in t["towns"].most_common(2):
        g = nhd.towns.outlines(t["state"], [tw])
        if not g:
            continue
        g = unary_union(g)
        b = g.bounds
        env = f"{b[0] - HR_NEAR_DEG},{b[1] - HR_NEAR_DEG},{b[2] + HR_NEAR_DEG},{b[3] + HR_NEAR_DEG}"
        fs = arcgis(nhd.http, "nhd-hr-near", HR_FLOWLINES, service=NHD_HR, where=where, geometry=env,
                    geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                    outFields=HR_FIELDS, maxAllowableOffset="0.0001")
        cands = [(geom_dist_m(f["_geom"], g) if not f["_geom"].intersects(g) else 0.0, f) for f in fs
                 if f.get("gnis_id") and f["_geom"] is not None and name_score(t["words"], f.get("gnis_name")) >= 0.8]
        cands = [c for c in cands if c[0] <= REPORT_TOWN_M]
        if cands:
            d, f = min(cands, key=lambda x: x[0])
            c = g.centroid
            return ({"type": "hr-line", "gnis_id": str(int(f["gnis_id"])), "gnis_name": f["gnis_name"],
                     "box": [round(c.x - HR_SPAN_DEG, 4), round(c.y - HR_SPAN_DEG, 4), round(c.x + HR_SPAN_DEG, 4),
                             round(c.y + HR_SPAN_DEG, 4)]},
                    f"NHD high resolution: flowline named '{f['gnis_name']}' (GNIS {int(f['gnis_id'])}) "
                    f"{'crossing' if d == 0 else f'{d:.0f} m from'} {tw}")
    return None, ("no NHD high-resolution flowline of that name near the reports' points" if t["points"] else
                  "no NHD high-resolution flowline of that name within 3 km of the reports' towns" if t["towns"] else
                  "the reports give no place to look for it in the NHD high-resolution flowlines")


def nhd_identities(state: str, path=None) -> dict:
    """{feature key: slug} of the state's records in data/waters-nhd.json (a GNIS id, else an NHDPlus COMID): a report
    name whose feature is already a record maps to it (a rebuild here would replace that record with this run's)."""
    d = read_json(path or OUT) or {}
    out = {}
    for r in d.get("waters") or []:
        if r.get("state") != state or not r.get("slug"):
            continue
        if r.get("gnis_id"):
            kind = "wb" if r.get("area_km2") is not None else "line"
            out.setdefault((kind, state, str(r["gnis_id"])), r["slug"])
        elif r.get("comids") and r.get("area_km2") is not None:
            out.setdefault(("wb", state, f"comid{r['comids'][0]}"), r["slug"])
    return out


REPORT_ROWS = "reports"


def names_main(args) -> int:
    """--names FILE [--state XX]: water records for the receiving-water names a state's reports give (module docstring,
    "Report names"). The file is rewritten to the names still without a record, each with its reason."""
    path = Path(args.names)
    meta, rows = read_names_file(path)
    state = (args.state[0] if args.state else meta.get("state") or "").upper()
    if state not in FIPS:
        print(f"--names needs --state XX (the file gives {meta.get('state')!r})")
        return 2
    if getattr(args, "add_places", False):
        return add_places(path, state)
    rows = [r for r in rows if r.get("name")]
    existing = existing_waters()
    allw = S.load_waters(include_nhd=True)
    S._STATES = S.derive_states(existing, S.load_rules(), live_only=False) | {state}
    S._GEOM_CACHE.clear()
    resolver = S.make_resolver(allw)
    targets, done, skipped_reason = collect_name_targets(state, rows, resolver, allw)
    print(f"report names {state}: {len(rows)} names, {len(targets)} waters to build, {len(done)} already a record, "
          f"{len(skipped_reason)} no water", flush=True)
    if args.targets_only:
        print_targets(targets, None)
        for (st, text), why in sorted(skipped_reason.items()):
            print(f"no water {st}  {text[:50]:50}  {why}")
        return 0
    http = Http(args.refresh, args.offline, max_requests=args.max_requests,
                deadline=time.monotonic() + args.budget_s if args.budget_s else None)
    shapes = States()
    towns = Towns(http)
    nhd = Nhd(http, shapes, towns)
    run = Run(nhd, shapes, towns, existing, args, http, skipped_reason)
    run.only_states, run.rows_from = {state}, REPORT_ROWS
    known = nhd_identities(state)
    for t, slugs in done:
        row = run.new_row(t)
        row.update({"from": REPORT_ROWS, "reports": t["events"], "slugs": slugs,
                    "how": ["already a water record: the status resolver places reports of this name on it"]})
        if t["notes"]:
            row["notes"] = list(dict.fromkeys(t["notes"]))[:6]
        run.rows.append(row)
    try:
        towns.load(state)
        prefetch_names(nhd, state, targets, 2, "_l2")
        prefetch_names(nhd, state, [t for t in targets if wants_area(t) or not t.get("_l2")], 4, "_l4")
    except BudgetExhausted as ex:
        run.stopped = str(ex)
    hr_queue = []
    for i, t in enumerate(targets, 1):
        row = run.new_row(t)
        row.update({"from": REPORT_ROWS, "reports": t["events"]})
        if t["notes"]:
            row["notes"] = list(dict.fromkeys(t["notes"]))[:6]
        if run.stopped or "_l2" not in t:
            row["reason"] = f"{NOT_REACHED} ({run.stopped or 'the name query was not asked'}); the next run resumes"
            run.rows.append(row)
            continue
        run.rows.append(row)
        try:
            choices, reason, failed = report_name_choices(nhd, t)
            if failed:
                row["places_failed"] = failed[:12]
            row["reason"] = reason
            for k, c, how in choices:
                slug = known.get(k)
                if slug:
                    row["slugs"].append(slug)
                    row["how"].append(f"{how}; the same NHD feature as record {slug}")
                    continue
                if k not in run.feats:
                    rec = run.new_record(k, c, t, row)
                    if rec is None:
                        continue
                    run.feats[k] = rec
                rec = run.feats[k]
                if rec.get("_existing"):
                    row["slugs"].append(rec["_existing"])
                    row["how"].append(f"{how}; the same water as existing record {rec['_existing']}")
                    continue
                run.attach(rec, row, t, how)
            if row["how"]:
                row["reason"] = None
                row["defined_by"] = "name"
            elif not choices and wants_hr(reason):
                hr_queue.append((t, row))
        except BudgetExhausted as ex:
            run.stop(t, ex)
        except Exception as ex:      # one bad name must not stop the run
            import traceback
            traceback.print_exc()
            run.problems.append(f"{t['key']}: {type(ex).__name__}: {ex}")
            row["reason"] = row["reason"] or f"build error ({type(ex).__name__}: {ex})"
        run.checkpoint(i, len(targets))
    for t, row in hr_queue:             # NHDPlus V2.1 has none of the name there: the high-resolution flowlines
        if run.stopped:
            row["reason"] = f"{row['reason']}; NHD high resolution not asked ({run.stopped})"
            continue
        if generic_name(t["name"]):
            row["reason"] = f"{row['reason']}; a description, not a name"
            continue
        try:
            c, how = resolve_hr_places(nhd, t)
            if c is None:
                row["reason"] = f"{row['reason']}; {how}"
            else:
                k = feature_key(state, c)
                if known.get(k):
                    row["slugs"].append(known[k])
                    row["how"].append(f"{how}; the same NHD feature as record {known[k]}")
                else:
                    if k not in run.feats:
                        rec = run.new_record(k, c, t, row)
                        if rec is not None:
                            run.feats[k] = rec
                    rec = run.feats.get(k)
                    if rec is None:
                        row["reason"] = f"{row['reason']}; {how}: no geometry in {state}"
                    elif rec.get("_existing"):
                        row["slugs"].append(rec["_existing"])
                        row["how"].append(f"{how}; the same water as existing record {rec['_existing']}")
                    else:
                        run.attach(rec, row, t, how)
                if row["how"]:
                    row["reason"], row["defined_by"] = None, "name (NHD high resolution)"
        except BudgetExhausted as ex:
            run.stopped = str(ex)
            row["reason"] = f"{row['reason']}; NHD high resolution not asked ({ex})"
        if not row["how"] and t["points"] and not args.no_osm and not generic_name(t["name"]):
            run.osm_queue.append((t, row))
    if run.osm_queue and not run.stopped:
        if args.offline or not mirror_answers():
            for t, row in run.osm_queue:
                row["reason"] = f"{row['reason']}; OSM fallback: Overpass not reachable"
        else:
            run.osm_state_pass()
    elif run.osm_queue:
        for t, row in run.osm_queue:
            row["reason"] = f"{row['reason']}; OSM fallback not tried ({run.stopped})"
    recs = [r for r in run.feats.values() if not r.get("_existing")]
    for r in recs:
        if not r["towns"]:
            r["towns"] = sorted(x for x, n in r["_slug_towns"].most_common(3) if n)
            r["towns_from"] = "the Census places of the reports' points"
    assign_slugs(recs, existing, run.previous, run.kept_rows)
    problems = run.problems + validate(recs, shapes)
    problems += [f"slug {r['slug']} collides with an existing record" for r in recs if r["slug"] in existing]
    out_rows = finish_rows(run.rows)
    problems += [f"target {r['state']} {r['name']}: neither mapped nor given a reason" for r in out_rows
                 if not r["slugs"] and not r["reason"]]
    stats_out = {state: names_stats(state, path, rows, targets, done, out_rows, recs, skipped_reason, http, run)}
    try:
        info = write_output(recs, out_rows, skipped_list(skipped_reason), problems, partial=True, stats=stats_out,
                            final=True, scope_states={state}, rows_from=REPORT_ROWS)
    except WriteRefused as ex:
        print(f"\nNOT WRITTEN: {ex}")
        return 1
    rewrite_names(path, meta, state, rows, out_rows, skipped_reason, stats_out[state])
    print(f"\n{len(recs)} records -> {shown(OUT)}: {describe_write(info)}")
    print(json.dumps(stats_out, indent=1))
    for p in problems[:40]:
        print("PROBLEM", p)
    return 0


def mirror_answers() -> bool:
    """Whether any Overpass instance answers a trivial query (mirror_order); the OSM fallback is skipped when none does."""
    try:
        return any(_ping(u) for u in OSM_STATE_MIRRORS)
    except Exception:
        return False


def _ping(url: str) -> bool:
    try:
        r = requests.post(url, data={"data": "[out:json][timeout:10];node(1);out ids;"}, headers=HEADERS, timeout=15)
        return r.status_code == 200 and "elements" in r.text
    except requests.RequestException:
        return False


def names_stats(state, path, rows, targets, done, out_rows, recs, skipped_reason, http, run) -> dict:
    mine = [r for r in out_rows if r.get("from") == REPORT_ROWS]
    built = [r for r in mine if r["slugs"] and not str(r["how"][0] if r["how"] else "").startswith("already a water")]
    return {"built": now_iso(), "file": str(Path(path).resolve().relative_to(ROOT)) if str(Path(path).resolve()).startswith(str(ROOT)) else Path(path).name,
            "names": len(rows), "reports": sum(r["reports"] for r in rows),
            "names_no_water": len(skipped_reason), "waters_named": len(targets) + len(done),
            "already_a_record": len(done), "targets": len(targets),
            "targets_mapped": sum(1 for r in mine if r["slugs"]) - len(done), "records": len(recs),
            "targets_failed": sum(1 for r in mine if not r["slugs"]),
            "failed_reasons": dict(Counter(re.sub(r"\s*\(.*", "", r["reason"] or "no reason")[:120]
                                           for r in mine if not r["slugs"]).most_common(15)),
            "network_requests": http.requests, "requests": dict(http.fetched), "cached": dict(http.cached),
            "failed": dict(http.failed), "stopped": run.stopped}


def rewrite_names(path, meta, state, rows, out_rows, skipped_reason, stats) -> None:
    """The names file rewritten to what is still missing: a row whose every water name now has a record moves to
    `resolved` (with the slugs); the others stay with their reason (no water, or why each name found no record)."""
    by_name = {}
    for r in out_rows:
        if r.get("from") == REPORT_ROWS:
            by_name[compact(r["name"])] = r
    left, resolved = [], []
    for r in rows:
        parts = r.pop("_parts", None) or []
        base = {k: v for k, v in r.items() if k not in ("reason", "places_failed", "parts")}
        why = skipped_reason.get((state, r["name"]))
        if not parts:
            left.append({**base, "reason": why or "no water name"})
            continue
        trs = [by_name.get(compact(p)) for p in parts]
        if all(x is not None and x["slugs"] for x in trs):
            resolved.append({"name": r["name"], "reports": r["reports"],
                             "slugs": list(dict.fromkeys(s for x in trs for s in x["slugs"])),
                             "how": "; ".join(dict.fromkeys(
                                 ("a water record already holds the name" if (x["how"] or [""])[0].startswith("already")
                                  else "record built from the name" if x.get("defined_by") else "the same water as a "
                                  "record on file") for x in trs))})
            continue
        bits = []
        for p, x in zip(parts, trs):
            if x is None:
                bits.append(f"{p}: not reached this run")
            elif not x["slugs"]:
                bits.append(f"{p}: {x['reason']}" if len(parts) > 1 else x["reason"])
        out = {**base, "reason": "; ".join(bits)}
        if len(parts) > 1 or compact(parts[0]) != compact(r["name"]):
            out["parts"] = parts
        fails = [f for x in trs if x for f in x.get("places_failed") or []]
        if fails:
            out["places_failed"] = fails[:6]
        left.append(out)
    note = {"date": stats["built"][:10], "command": f"python -m ingest.waters_from_nhd --names {stats['file']} "
            f"--state {state}", "records_built": stats["records"], "names_resolved": len(resolved),
            "network_requests": stats["network_requests"]}
    if stats.get("stopped"):
        note["stopped"] = stats["stopped"]
    write_names_file(path, meta, state, left, resolved, note)


NHD_FAILED = re.compile(r"no NHD flowline or waterbody of that name|has no GNIS name in NHDPlus")
OSM_ASKED = re.compile(r"no NHD feature and no OSM feature|OSM feature of that name is|OSM fallback failed|"
                       r"OSM fallback \(NHDPlus has no feature")


def osm_only(args) -> int:
    """--osm-only: the last full run's records stay; the targets it left unmapped because NHDPlus has no
    feature of that name and OSM was not asked (over --osm-max) go to the OSM fallback now, most reports
    first; the HAND records are rebuilt. Targets are collected again with the current resolver and the
    last run's records, so names placed since are not asked about. Written once, at the end."""
    prev = read_json(OUT) or {}
    if not prev.get("waters"):
        print("--osm-only needs a full run's data/waters-nhd.json first")
        return 1
    base = existing_waters()
    replaced = superseded_keys()
    keep = [r for r in prev["waters"] if not r.get("hand") and (r.get("state"), S.norm_name(r.get("name") or "")) not in replaced]
    existing = {**base, **{r["slug"]: {**r, "extra": True} for r in keep if r["slug"] not in base}}
    _, events, _ = S.load_events(EVENTS_DIR, False, False)
    targets, skipped, skipped_reason, stats, _ = collect_targets(existing, events)
    prev_rows = {(r["state"], r["name"]): r for r in prev.get("targets") or []}
    http = Http(args.refresh, args.offline)
    states, towns = States(), Towns(http)
    nhd = Nhd(http, states, towns)
    run = Run(nhd, states, towns, existing, args, http, skipped_reason)
    pairs, asked = [], 0
    for t in targets:
        row = run.new_row(t)
        run.rows.append(row)
        pairs.append((t, row))
        pr = prev_rows.get((t["state"], t["name"]))
        reason = (pr or {}).get("reason") or ""
        if pr is None:
            row["reason"] = "a target since the last full run (not asked about by --osm-only)"
        elif pr.get("slugs"):
            row.update(slugs=list(pr["slugs"]), how=list(pr.get("how") or []))
        elif t["name"] and t["points"] and not args.no_osm and has_kind(t["words"]) and generic_name(t["name"]) \
                and NHD_FAILED.search(reason):
            row["reason"] = re.sub(r";?\s*OSM fallback not tried.*$", "", reason) + "; a description, not a name: OSM not asked"
        elif t["name"] and t["points"] and not args.no_osm and has_kind(t["words"]) and NHD_FAILED.search(reason) \
                and (args.refresh or not OSM_ASKED.search(reason)):
            row["reason"] = re.sub(r";?\s*OSM fallback not tried.*$", "", reason)
            run.osm_queue.append((t, row))
            asked += 1
        else:
            row["reason"] = reason or "unmapped in the last full run"
    print(f"--osm-only: {len(targets)} targets; OSM fallback for {min(asked, args.osm_max)} of {asked}", flush=True)
    run.osm_queue.sort(key=lambda x: -(x[0]["events"] + x[0]["outfalls"]))
    if args.osm_per_name:
        run.osm_pass()
    else:
        run.osm_state_pass()
    run.hand_pass(pairs)
    recs = [r for r in run.feats.values() if not r.get("_existing")]
    for r in recs:
        if not r["towns"]:
            r["towns"] = sorted(x for x, n in r["_slug_towns"].most_common(3) if n)
            r["towns_from"] = "the Census places of the outfalls' and notices' points"
    assign_slugs(recs, existing, run.previous, run.kept_rows)
    problems = run.problems + validate(recs, states)
    problems += [f"slug {r['slug']} collides with an existing record" for r in recs if r["slug"] in existing]
    rows = finish_rows(run.rows)
    ev_eval = evaluate(base, keep_records(keep) + recs, events)
    stats_out = {**(prev.get("stats") or {}),
                 "osm_only_run": {"built": now_iso(), "targets": len(targets), "osm_asked": min(asked, args.osm_max),
                                  "osm_records": sum(1 for r in recs if not r.get("hand")),
                                  "osm_by_state": run.osm_states, "osm_remaining": run.osm_remaining,
                                  "hand_records": sum(1 for r in recs if r.get("hand")),
                                  "targets_mapped": sum(1 for r in rows if r["slugs"]),
                                  "events_unplaced_after": ev_eval["after"]["unplaced"],
                                  "requests": dict(http.fetched), "cached": dict(http.cached),
                                  "failed": dict(http.failed)},
                 "records": len(keep) + len(recs)}
    try:
        info = write_output(recs, rows, skipped_list(skipped_reason), problems, partial=False, stats=stats_out,
                            keep=keep, final=True, rebuild=args.rebuild)
    except WriteRefused as ex:
        print(f"NOT WRITTEN: {ex}")
        return 1
    print(f"{len(recs)} new records ({stats_out['osm_only_run']['osm_records']} OSM, "
          f"{stats_out['osm_only_run']['hand_records']} hand) + {len(keep)} kept -> {shown(OUT)}: {describe_write(info)}")
    for r in recs:
        print(f"  {r['slug']:44} {r['kind']:8} {r.get('length_km') or r.get('area_km2')} {'; '.join(r['towns'][:4])}")
    print(json.dumps(stats_out["osm_only_run"], indent=1))
    for p in problems[:40]:
        print("PROBLEM", p)
    return 0                       # problems are listed above and kept in stats; the file was written


def keep_records(rows) -> list[dict]:
    """Public rows back into the record form evaluate() and public_record() read."""
    return [{**r, "_geom": shape(r["geometry"])} for r in rows if r.get("geometry")]


def town_display(t) -> str:
    return " ".join(w.capitalize() for w in str(t).split())


# A target row's reason reaches the public outfall registry (ingest.outfall_waters copies it into no_water_reason), so it
# is written in public voice; the tool's detail (the endpoint, the exception, the command-line flag) goes to the row's
# reason_detail (a place's to its `detail`), which nothing exports. (review 2026-11-04 P3: "OSM state query for FL
# failed twice (https://overpass-api.de/api/interpreter: ConnectionError)".)
TOOL_DETAIL = [
    (re.compile(r"OSM state query for [A-Z]{2} failed twice \([^)]*\)|OSM fallback: Overpass not reachable"),
     "the map service (OpenStreetMap) could not be reached on {date}"),
    (re.compile(r"OSM fallback: not cached \(--offline\)|not cached \(--offline\)"),
     "the map service (OpenStreetMap) was not asked on {date}"),
    (re.compile(r"\((?:--place-budget [\d.]+ s used|--budget-s used|--max-requests[^)]*)\)"),
     "(the run's time or request limit was reached on {date})"),
    (re.compile(r"build error \([A-Za-z_]+(?:Error|Exception)[^)]*\)|OSM fallback failed \([A-Za-z_]+\)"),
     "the record could not be built on {date} (a fault in the build, logged)"),
]


def public_voice(text: str | None, date: str) -> tuple[str | None, list[str]]:
    """(the text with each piece of tool detail replaced by its public wording, the pieces replaced)."""
    if not text:
        return text, []
    found = []
    for rx, say in TOOL_DETAIL:
        def sub(m, say=say):
            found.append(m.group(0))
            return say.format(date=date)
        text = rx.sub(sub, text)
    return text, found


def public_row(row: dict, date: str) -> dict:
    """A target row with its reason and its places' reasons in public voice (public_voice), the detail kept in
    reason_detail and the place's `detail`. A row already in public voice is returned unchanged."""
    out = dict(row)
    reason, found = public_voice(row.get("reason"), date)
    if found:
        out["reason"] = reason
        out["reason_detail"] = list(dict.fromkeys(list(row.get("reason_detail") or []) + found))
    if row.get("places_failed"):
        places = []
        for p in row["places_failed"]:
            r, f = public_voice(p.get("reason"), date)
            places.append({**p, "reason": r, "detail": "; ".join(dict.fromkeys(([p["detail"]] if p.get("detail") else []) + f))}
                          if f else p)
        out["places_failed"] = places
    return out


def public_reasons(doc: dict, states, date_of=None) -> int:
    """The target rows of `states` in doc put in public voice in place (public_row); the date is the state's build date
    (stats.state_builds.<ST>.built) unless date_of(state) gives one. Returns the number of rows changed."""
    builds = (doc.get("stats") or {}).get("state_builds") or {}
    n = 0
    rows = doc.get("targets") or []
    for i, r in enumerate(rows):
        st = r.get("state")
        if st not in states:
            continue
        date = (date_of(st) if date_of else None) or str((builds.get(st) or {}).get("built") or doc.get("built") or "")[:10]
        new = public_row(r, date)
        if new != r:
            rows[i] = new
            n += 1
    return n


def finish_rows(rows, date: str | None = None):
    """Target rows in the file's form, their reasons in public voice (public_row). A state build's row also carries
    reach_slugs: {EPA reach code or NHDPlus id: slug} for the features its reach codes and ids named
    (ingest.outfall_waters ties an outfall by its own reach)."""
    date = date or now_iso()[:10]
    out = []
    for r in rows:
        recs = r.get("_recs") or []
        slugs = list(dict.fromkeys(r["slugs"] + [x["slug"] for x in recs if x.get("slug")]))
        row = {k: v for k, v in {**r, "slugs": slugs}.items() if not k.startswith("_")}
        reach = {}
        for ids, rec in r.get("_epa") or []:
            s = rec.get("slug") or rec.get("_existing")
            if s:
                for x in ids:
                    reach.setdefault(x, s)
        if reach:
            row["reach_slugs"] = dict(sorted(reach.items()))
        out.append(public_row(row, date))
    return out


def skipped_list(skipped_reason: dict) -> list[dict]:
    return [{"state": st, "text": text, "reason": why} for (st, text), why in sorted(skipped_reason.items(),
                                                                                       key=lambda kv: (kv[0][0] or "", kv[0][1]))]


if __name__ == "__main__":
    sys.exit(main())
