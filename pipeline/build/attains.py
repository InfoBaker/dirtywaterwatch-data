"""State Clean Water Act assessments beside a water's status: EPA ATTAINS, joined to the tracked water records.
This module is not a feed: it writes no events file, and nothing here changes a status, a colour or a reach. The
export (export/build.py) prints what it finds in its own block on a water's page, like the gauge conditions.

    python -I scripts/attains_context.py [--out data/build/attains/attains-waters.json] [--states TN MA ...]
                                         [--refresh-geometry] [--offline]

Sources (all keyless; docs/attains.md):
  1. Expert Query national downloads: the file list (address, size, row count, timestamp) is the `metadata` object of
     LOOKUP_URL, read each run because the folder number in the addresses changes. Three files are used, cached
     under data/raw/attains/ and downloaded again only when the lookup's timestamp or size changes: `assessments`
     (per assessment unit, use and parameter: recreation support, monitoring and assessment dates, the parameters of
     group PATHOGENS with their status, IR category and first listing), `sources` (the probable sources the state
     names per cause) and `assessmentUnits` (water type, size, location text). They are streamed (zipfile + csv),
     never loaded whole, and only the rows of the units the join found are kept. Several cycles per organization are
     in the files: each organization's latest cycle in each file is kept, and every finding carries its cycle.
  2. The ATTAINS map layers (FS_URL, layers 0 points, 1 lines, 2 areas; table 5 the control table): each state's
     assessment-unit geometry, fetched one request at a time with a pause, paged by OBJECTID, simplified on the
     server and cached per state under data/raw/attains/geom/ (refetched when the state's load date in the control
     table changes, or after GEOM_MAX_DAYS).
  3. The ATTAINS web services (API_URL): optional, only when ATTAINS_API_KEY is set, only to fill a matched unit the
     national files lack, at most API_MAX_CALLS a run. The key goes in the X-Api-Key header (api.data.gov's header
     option), never in an address and never in a log.

The join (water record -> assessment units): a unit matches a water when it lies along the water (a line: within
MATCH_M of the water's outline for at least half its length or ALONG_MIN_M; an area: it intersects the water or lies
within MATCH_M; a point: within MATCH_M) and the names agree after normalisation (names_agree), method
"geometry+name". Units named "Unnamed ..." or "Misc tribs ..." match only when they lie inside a lake, pond or
reservoir's outline (method "geometry_inside"), never along a river. A water can have many units, a unit several
waters; units are sorted with a pathogen listing first, then by distance.

Writes data/build/attains/attains-waters.json (pipeline state, not in git):
  {"built", "source": {"name", "files": [{name, url, timestamp, bytes, rows}], "layers": {url, data_last_edited},
   "fetched_at", "geometry_fetched": {st: time}}, "states": {st: {units, waters, waters_with_units,
   waters_pathogen_listed, waters_sewage_named}}, "waters": {slug: {"units": [UNIT], "summary": SUMMARY}},
   "audit": {slug: [{org_id, au_id, au_name, reason, distance_m, kept?, others?}]}}
A unit's facts are keyed by organization, unit id and cycle: its assessment is its organization's latest cycle in the
assessments file (`cycle`), its sewage sources all come from one cycle, the organization's latest in the sources file
(`sources_cycle`, also on each source), never mixed. The audit list is for checking the join and is never exported.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, error_text, live_states, now_iso



LOOKUP_URL = "https://owapps.epa.gov/expertquery/api/lookupFiles"
FS_URL = "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/ATTAINS_Assessment/FeatureServer"
API_URL = "https://api.epa.gov/attains/"
REPORT_URL = "https://mywaterway.epa.gov/waterbody-report/{org}/{au}"
SOURCE_NAME = ("EPA ATTAINS: state Clean Water Act assessments (Expert Query national downloads and the ATTAINS map "
               "layers)")
# the Expert Query keys used, and the file names their addresses end in
FILES = {"assessments": "assessments.csv.zip", "sources": "sources.csv.zip",
         "assessmentUnits": "assessment_units.csv.zip"}
DOWNLOAD_HOST = re.compile(r"(?:^|\.)(?:amazonaws\.com|epa\.gov)$")
LAYERS = {0: "point", 1: "line", 2: "area"}
CONTROL_TABLE = 5
OUT_FIELDS = ("OBJECTID,organizationid,assessmentunitidentifier,assessmentunitname,reportingcycle,waterbodyreportlink,"
              "recreation_use,pathogens,cyclestatus")
PAGE = 2000
PAUSE_S = 1.0
MAX_OFFSET_DEG = 0.0002              # the server's simplification (~20 m)
PRECISION = 5                        # decimals of the returned coordinates (~1 m)
GEOM_MAX_DAYS = 90
TRIES = 6

RAW_DIR = DATA_DIR / "raw" / "attains"
GEOM_DIR = RAW_DIR / "geom"
API_DIR = RAW_DIR / "api"
OUT = BUILD_DIR / "attains" / "attains-waters.json"
STALE_DAYS = 30                      # the export shows nothing from a cache older than this
API_MAX_CALLS = 100

MATCH_M = 100.0
ALONG_MIN_M = 500.0                  # a line lies along the water for at least min(half its length, this)
INSIDE_SHARE = 0.9                   # an unnamed unit: this share of it inside the lake's outline (buffered MATCH_M)
WATER_SIMPLIFY_DEG = 0.0001          # ~10 m: the water outlines for the join
M_PER_DEG = 111_320.0
POLYGON_KINDS = {"lake", "pond", "reservoir"}

PATHOGEN_GROUP = "PATHOGENS"
PATHOGEN_NAME = re.compile(r"(?i)\bE\.?\s?COLI\b|ESCHERICHIA|ENTEROCOCC|COLIFORM|PATHOGEN|BACTERI")
STATUS_RANK = {"cause": 5, "observed effect": 4, "insufficient information": 3, "meeting criteria": 2, "removed": 1}
RECREATION_USE = re.compile(r"(?i)recreat|swim|contact|bathing|primary contact|secondary contact|boating")

# ---------------------------------------------------------------- sewage sources (design rules, docs/attains.md)

# Only these name sewage; urban runoff, "Municipal (Urbanized High Density Area)" and MS4 are stormwater, not sewage.
SEWAGE_KINDS: tuple[tuple[str, re.Pattern], ...] = (
    ("wet_weather", re.compile(r"(?i)^WET WEATHER DISCHARGES?\b.*\b(?:SSO|CSO)\b")),
    ("cso", re.compile(r"(?i)\bCOMBINED SEWER OVERFLOWS?\b|\bCSOS?\b")),
    ("sso", re.compile(r"(?i)\bSANITARY SEWER OVERFLOWS?\b|\bSSOS?\b|\bSEWAGE (?:SPILLS?|OVERFLOWS?)\b")),
    ("municipal", re.compile(r"(?i)^MUNICIPAL POINT SOURCE|\bPACKAGE PLANTS?\b|\bPRETREATMENT\b|\bSEWAGE LAGOONS?\b|"
                             r"\bWASTEWATER TREATMENT (?:PLANTS?|FACILIT)|\bPUBLICLY OWNED TREATMENT|\bPOTWS?\b")),
    ("septic", re.compile(r"(?i)\bSEPTIC\b|\bUNSEWERED\b|\bON-?SITE (?:TREATMENT|WASTEWATER|SEWAGE)|"
                          r"\bUNPERMITTED DISCHARGE \(DOMESTIC|\bDOMESTIC WASTES?\b.*UNPERMITTED|"
                          r"\bILLICIT CONNECTIONS?\b|\bILLEGAL CONNECTIONS?\b|\bSEPTAGE\b")),
    ("boat", re.compile(r"(?i)\bSANITARY ON-?VESSEL\b|\bVESSEL (?:SEWAGE|SANITARY|WASTES?)\b|\bBOAT(?:ING)? "
                        r"(?:SEWAGE|SANITARY|DISCHARGES?)\b|\bMARINA/BOATING SANITARY\b")),
)
STORMWATER = re.compile(r"(?i)URBAN RUNOFF|STORM ?SEWERS?(?! OVERFLOW)|URBANIZED HIGH DENSITY|\bMS4\b|"
                        r"MUNICIPAL SEPARATE STORM|STORMWATER|STORM WATER")


def sewage_kind(source_name: str) -> str | None:
    """The sewage kind of a probable source as the state names it (cso, sso, municipal, wet_weather, septic, boat), or
    None. Stormwater (urban runoff, storm sewers, "Municipal (Urbanized High Density Area)", MS4) is not sewage; the
    mixed wet-weather category that names SSO or CSO is, and so are illicit connections to storm sewers."""
    s = str(source_name or "").strip()
    if not s:
        return None
    kind = next((k for k, rx in SEWAGE_KINDS if rx.search(s)), None)
    if kind == "municipal" and STORMWATER.search(s):       # a municipal storm system is stormwater
        return None
    return kind


# ---------------------------------------------------------------- names

ABBREV = {"cr": "creek", "crk": "creek", "ck": "creek", "r": "river", "riv": "river", "rv": "river",
          "res": "reservoir", "resv": "reservoir", "rsvr": "reservoir", "lk": "lake", "st": "saint", "ste": "sainte",
          "mt": "mount", "mtn": "mountain", "br": "branch", "brk": "brook", "trib": "tributary", "tribs": "tributaries",
          "ft": "fort", "pt": "point", "pd": "pond", "hbr": "harbor", "harbour": "harbor", "n": "north", "s": "south",
          "e": "east", "w": "west", "no": "north", "so": "south", "f": "fork", "fk": "fork",
          "frk": "fork", "sf": "south fork", "nf": "north fork", "ef": "east fork", "wf": "west fork",
          "mf": "middle fork", "bch": "beach", "isl": "island", "chan": "channel", "cnl": "canal", "sd": "sound"}
# the words that name a kind of water: a part of a compound name without one is a qualifier, not a name
GENERIC = {"river", "creek", "brook", "run", "branch", "fork", "bayou", "slough", "lake", "lakes", "reservoir", "pond",
           "ponds", "bay", "harbor", "sound", "inlet", "passage", "passages", "channel", "canal", "cove", "narrows",
           "strait", "reach", "waterway", "prong", "kill", "stream", "spring", "springs", "lagoon", "estuary", "gulf",
           "basin", "embayment", "arm", "impoundment", "flowage", "swamp", "ditch", "drain", "marsh", "ocean"}
# words that, after the water's own name, make a different water (a fork, a tributary, a ditch)
OTHER_WATER_AFTER = {"tributary", "tributaries", "ut", "unt", "branch", "fork", "prong", "ditch", "drain", "run",
                     "creek", "brook", "river", "canal", "north", "south", "east", "west", "slough", "bayou", "lake",
                     "pond", "reservoir", "spring", "springs", "cutoff", "little", "big", "old", "outlet", "inlet",
                     "basin", "retention"}
# words that, before the water's own name, name a part of the same water
SAME_WATER_BEFORE = {"upper", "lower", "middle", "mid", "tidal", "nontidal", "main", "mainstem", "inner", "outer"}
FORK_WORDS = {"north", "south", "east", "west", "middle", "fork", "branch", "prong"}
# an unnamed unit: unnamed or miscellaneous tributaries, unsegmented parts of a watershed (anywhere in the name), or
# a lumped one ("Lakes and reservoirs in the Plum Creek system")
UNNAMED = re.compile(r"(?i)\b(?:unnamed|un-named|unt|ut|misc|miscellaneous|tribs?|tributary|tributaries|unsegmented|"
                     r"no name)\b|^\s*(?:all\s+)?(?:lakes|ponds|streams|rivers|creeks|reservoirs|waters|wetlands)\b")
LOCATION_CUT = re.compile(r"(?i)\s+(?:from|above|below|to|at|near|upstream|downstream|between|including|excluding|"
                          r"except|segment|seg|thru|through|beginning|starting|ending|"
                          r"(?:mile|miles|mi|rm|reach)\s+\d)\b.*$")
PART_SPLIT = re.compile(r"(?i)\s*(?:/|;|,|&|\s[-–—]\s|\band\b)\s*")
TRAILING_ID = re.compile(r"[-_\s]+(?:[A-Z]{0,4}[-_]?)?\d[\d_-]*[A-Z]?\s*$")
FORK_AFTER = {"fork", "branch", "run", "bayou", "slough", "prong", "kill", "brook", "creek"}


FILLER = {"of", "the", "and"}
DIRECTION_LETTERS = {"n", "s", "e", "w", "f"}       # "Lewis River, E.F." is a fork, not initials


def tokens(name: str, expand_single: bool = True) -> tuple[str, ...]:
    """A water name as comparable words: accents dropped (Río Portugués), lower case, apostrophes dropped,
    punctuation as spaces, the abbreviations of ABBREV written out, a leading "the" dropped."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("’", "'").replace("'", "")
    s = re.sub(r"&", " and ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    out = []
    for t in s.split():
        out.extend((ABBREV.get(t, t) if expand_single or len(t) > 1 else t).split())
    if out and out[0] == "the":
        out = out[1:]
    return tuple(out)


def canon(t: tuple[str, ...]) -> tuple[str, ...]:
    """Words as compared: "reservoir" is "lake" (Kentucky Lake and Kentucky Reservoir are one water), "of" after a
    fork word is dropped (South Fork of Wildcat Creek), and a trailing "river" after a fork, branch or creek word is
    dropped (Caney Fork and Caney Fork River)."""
    out = ["lake" if x == "reservoir" else x for x in t]
    out = [x for i, x in enumerate(out) if not (x == "of" and i and out[i - 1] in FORK_WORDS)]   # South Fork of X
    if len(out) > 2 and out[-1] == "river" and out[-2] in FORK_AFTER:
        out = out[:-1]
    return tuple(out)


def is_fork(t: tuple[str, ...]) -> bool:
    return bool(t) and set(t) <= FORK_WORDS and bool(set(t) & {"fork", "branch", "prong"})


def au_names(name: str) -> list[tuple[str, ...]]:
    """The names an assessment unit's name may stand for: the name cut at its first location words ("from", "above",
    "to", "mile" ...) with a trailing id and parentheses removed, and each part of a compound name ("Dalco Passage and
    East Passage", "Nisqually Reach/Drayton Passage", "Kerr Lake; Buggs Island Lake") that names a kind of water;
    a fork written after the name ("Lewis River, E.F.", "White River - West Fork") is put in front of it; a name in
    parentheses that names a kind of water ("Smith Mtn. Lake (Blackwater River)"); the reservoir of "X Embayment of
    Y Reservoir"."""
    s = str(name or "")
    paren = re.findall(r"\(([^()]*)\)", s)
    base = re.sub(r"\([^()]*\)", " ", s)
    base = TRAILING_ID.sub("", base).strip()
    base = LOCATION_CUT.sub("", base).strip()
    parts = [tokens(p) for p in PART_SPLIT.split(base) if p.strip()]
    parts = [p for p in parts if p]
    out: list[tuple[str, ...]] = []
    if parts:
        first = parts[0]
        forks = [p for p in parts[1:] if is_fork(p)]
        out.append(forks[0] + first if forks else first)
        out += [p for p in parts[1:] if not is_fork(p) and set(p) & GENERIC and set(p) - GENERIC]
    whole = tokens(base)
    if whole and whole not in out:
        out.append(whole)
    # a parenthesis that names a water, not one that gives bounds ("(Red River to headwaters)")
    out += [t for x in paren if (t := tokens(x)) and set(t) & GENERIC and set(t) - GENERIC
            and not LOCATION_CUT.search(" " + x)]
    for t in list(out):
        if "embayment" in t and "of" in t:
            rest = t[t.index("of") + 1:]
            if rest and set(rest) & GENERIC:
                out.append(rest)
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def water_names(names) -> list[tuple[str, ...]]:
    """A water's names (its name and aliases) as comparable words, each also split at "/", ";" and parentheses
    ("Staunton River / Roanoke River", "Kerr Lake;Buggs Island Lake", "Lake Cochituate (Middle Pond)")."""
    out = []
    for n in names:
        for x in [n, *re.split(r"\s*(?:/|;|\(|\))\s*", str(n or ""))]:
            t = tokens(x)
            if t and t not in out:
                out.append(t)
    return out


ID_NAME = re.compile(r"^\s*[A-Z]{0,5}[-_ ]?\d[\w.-]*\s*$")


def id_like(name: str) -> bool:
    """A unit named by its station or segment code ("RL-09084", "07-01A": South Carolina's points) rather than a
    water's name: its location text in the assessment-units file stands in for the name in the name test."""
    return bool(ID_NAME.match(str(name or "")))


def is_unnamed(name: str) -> bool:
    return bool(UNNAMED.search(str(name or ""))) or not tokens(name)


def initials_only(a_name: str, b_name: str) -> bool:
    """True when one name is the other with initials or filler words added ("A M Puett Reservoir" and "Puett
    Reservoir."; "Lake of the Woods" and "Woods Lake"): every word of the shorter is in the longer, and the longer adds
    only single letters (other than N, S, E, W and F, which write a fork or a direction) or "of", "the", "and". A
    longer name that adds a word ("Little Mill Creek", "Sawyer Brook-Cuyahoga River") does not pass."""
    a = canon(tokens(a_name, expand_single=False))
    b = canon(tokens(b_name, expand_single=False))
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if not short or not (set(short) - GENERIC - FILLER) or not set(short) <= set(long_):
        return False
    return all((len(t) == 1 and t not in DIRECTION_LETTERS) or t in FILLER for t in long_ if t not in short)


def names_agree(water_names_, au_name: str) -> bool:
    """True when an assessment unit's name and one of the water's names (its name and aliases) agree after
    normalisation: the same words (in any order: "Lake Allatoona" and "Allatoona Lake"; "reservoir" counts as
    "lake"), or the unit's name begins with the water's name and the next word does not make another water
    ("Cumberland River Embayment", never "Mill Creek Tributary" or "Shenandoah River North Fork"), or a qualifier of
    the same water comes first ("Upper Mississippi River", "Tidal Anacostia River"). Unnamed units never agree."""
    if is_unnamed(au_name):
        return False
    if any(initials_only(n, au_name) for n in water_names_ if n):
        return True
    cands = [canon(a) for a in au_names(au_name)]
    for w0 in water_names(water_names_):
        w = canon(w0)
        for a in cands:
            if a == w or sorted(a) == sorted(w) or "".join(a) == "".join(w):      # Sixmile Run, Six Mile Run
                return True
            if len(a) > len(w) and a[:len(w)] == w and a[len(w)] not in OTHER_WATER_AFTER:
                return True
            if len(a) > len(w) and a[-len(w):] == w and all(t in SAME_WATER_BEFORE for t in a[:-len(w)]):
                return True
    return False


# ---------------------------------------------------------------- HTTP


class AttainsError(Exception):
    """A failure in this module's own words (a host at most, never an address with its query or a service's text)."""


def host_of(url: str) -> str:
    try:
        return urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


class Client:
    """One request at a time, a pause between requests, back-off on 429 and 5xx (Retry-After honoured up to two
    minutes) and on transport failures. Logs name the host, never an address with its parameters or a header."""

    def __init__(self, session=None, pause: float = PAUSE_S, tries: int = TRIES, sleep=time.sleep, log=print):
        self.session = session or requests.Session()
        self.pause, self.tries, self.sleep, self.log = pause, tries, sleep, log
        self._last = 0.0
        self.requests = 0

    def _wait_turn(self):
        if self.pause and self._last:
            gap = self.pause - (time.monotonic() - self._last)
            if gap > 0:
                self.sleep(gap)

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, stream: bool = False,
            timeout: float = 180):
        last = "no answer"
        for n in range(self.tries):
            self._wait_turn()
            wait = min(120.0, 5.0 * (2 ** n))
            try:
                self.requests += 1
                r = self.session.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=timeout,
                                     stream=stream)
            except (requests.ConnectionError, requests.Timeout) as e:
                last = error_text(e)
            else:
                self._last = time.monotonic()
                if r.status_code == 200:
                    return r
                last = f"HTTP {r.status_code}"
                if r.status_code != 429 and r.status_code < 500:
                    raise AttainsError(f"HTTP {r.status_code} at {host_of(url)}")
                ra = (r.headers or {}).get("Retry-After")
                if ra and str(ra).strip().isdigit():
                    wait = min(120.0, max(wait, float(ra)))
            self._last = time.monotonic()
            if n < self.tries - 1:
                self.log(f"attains: {host_of(url)} {last}; trying again in {wait:.0f} s")
                self.sleep(wait)
        raise AttainsError(f"{last} at {host_of(url)} after {self.tries} tries")

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        """A JSON answer; an ArcGIS error inside a 200 answer ({"error": {"code": ...}}) is retried like a 5xx."""
        last = "error"
        for n in range(self.tries):
            r = self.get(url, params=params, headers=headers)
            try:
                d = r.json()
            except ValueError:
                last = "not JSON"
            else:
                err = d.get("error") if isinstance(d, dict) else None
                if not err:
                    return d
                code = err.get("code") if isinstance(err, dict) else None
                last = f"error code {code}" if isinstance(code, int) else "error"
                if isinstance(code, int) and code != 429 and code < 500:
                    raise AttainsError(f"{last} at {host_of(url)}")
            if n < self.tries - 1:
                wait = min(120.0, 5.0 * (2 ** n))
                self.log(f"attains: {host_of(url)} {last}; trying again in {wait:.0f} s")
                self.sleep(wait)
        raise AttainsError(f"{last} at {host_of(url)} after {self.tries} tries")


# ---------------------------------------------------------------- the national files


def lookup_files(client: Client) -> dict:
    """The Expert Query file list: {key: {url, timestamp, zipSize, numRows, csvSize}} for the keys in FILES, each
    address checked (https, an EPA or Amazon S3 host, ending in the expected file name)."""
    d = client.get_json(LOOKUP_URL)
    meta = d.get("metadata") if isinstance(d, dict) else None
    if not isinstance(meta, dict):
        raise AttainsError("the file list has no metadata")
    out = {}
    for key, fname in FILES.items():
        m = meta.get(key)
        if not isinstance(m, dict) or not m.get("url"):
            raise AttainsError(f"the file list has no {key} file")
        u = urlsplit(str(m["url"]))
        if u.scheme != "https" or not DOWNLOAD_HOST.search(u.hostname or "") or not u.path.endswith("/" + fname):
            raise AttainsError(f"the {key} address is not an EPA download")
        out[key] = {k: m.get(k) for k in ("url", "timestamp", "zipSize", "numRows", "csvSize")}
    return out


def cached_file(key: str, meta: dict, raw_dir: Path = RAW_DIR) -> Path | None:
    """The cached download of `key` when its sidecar has the lookup's timestamp and the file its size, else None."""
    p = raw_dir / FILES[key]
    side = p.with_name(p.name + ".meta.json")
    try:
        s = json.loads(side.read_text())
    except (OSError, ValueError):
        return None
    if not p.is_file() or s.get("timestamp") != meta.get("timestamp") or p.stat().st_size != meta.get("zipSize"):
        return None
    return p


def download(client: Client, key: str, meta: dict, raw_dir: Path = RAW_DIR, log=print) -> Path:
    """The national file `key`, from the cache when the lookup's timestamp and size are unchanged, else downloaded
    whole (to a .part file, checked against the lookup's size, then moved in place) with its sidecar."""
    have = cached_file(key, meta, raw_dir)
    if have:
        log(f"attains: {key} cached ({meta.get('timestamp')}, {have.stat().st_size:,} bytes)")
        return have
    raw_dir.mkdir(parents=True, exist_ok=True)
    p = raw_dir / FILES[key]
    part = p.with_name(p.name + ".part")
    t0 = time.monotonic()
    r = client.get(meta["url"], stream=True, timeout=300)
    n = 0
    with open(part, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
            n += len(chunk)
    if meta.get("zipSize") and n != meta["zipSize"]:
        part.unlink(missing_ok=True)
        raise AttainsError(f"{key}: {n:,} bytes, the file list says {meta['zipSize']:,}")
    os.replace(part, p)
    p.with_name(p.name + ".meta.json").write_text(json.dumps({"key": key, **meta, "downloaded_at": now_iso()}, indent=1))
    log(f"attains: {key} downloaded ({n:,} bytes in {time.monotonic() - t0:.0f} s)")
    return p


def csv_rows(path: Path):
    """The rows of the one CSV in a national zip, as dicts, streamed (the file is never read whole)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise AttainsError(f"{path.name}: {len(names)} CSV files inside, one expected")
        with z.open(names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="", errors="replace")
            reader = csv.reader(text)
            header = next(reader, None)
            if not header:
                return
            for row in reader:
                yield header, row


def col(name: str) -> str:
    """A column name as compared: upper case, letters and digits only (the files' "ASSESSMENTUNITID" and the
    documented "assessmentUnitId" are the same column)."""
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def getter(header: list[str]):
    idx = {col(h): i for i, h in enumerate(header)}

    def g(row, key: str) -> str:
        i = idx.get(col(key))
        return row[i].strip() if i is not None and i < len(row) else ""
    return idx, g


# the files give a use's support as a code; the words are ATTAINS's own
USE_SUPPORT = {"F": "Fully Supporting", "N": "Not Supporting", "I": "Insufficient Information", "X": "Not Assessed"}


def support_words(x) -> str | None:
    v = str(x or "").strip()
    return USE_SUPPORT.get(v.upper(), v) or None


def _int(x):
    try:
        return int(str(x).strip()[:4])
    except (TypeError, ValueError):
        return None


def _num(x):
    try:
        v = float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return int(v) if v.is_integer() else round(v, 3)


def _date(x):
    """A date as given (date precision): YYYY-MM-DD from the file's text, else None. Never a time."""
    m = re.match(r"\s*(\d{4})[-/](\d{2})[-/](\d{2})", str(x or ""))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(x or ""))
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def _yn(x):
    v = str(x or "").strip().upper()
    return True if v in ("Y", "YES", "TRUE", "1") else False if v in ("N", "NO", "FALSE", "0") else None


def read_assessments(path: Path, wanted: set[tuple[str, str]]) -> tuple[dict, dict, set]:
    """(per (org, au, cycle) the unit's assessment as kept, the latest cycle of every organization in the file, the
    parameter names of group PATHOGENS anywhere in the file). Kept per unit and cycle: the unit's fields, its
    recreation uses (support, dates) and its PATHOGENS parameters (status, IR category, first listing, a TMDL)."""
    org_max: dict[str, int] = {}
    units: dict[tuple, dict] = {}
    pathogen_names: set[str] = set()
    idx = g = None
    for header, row in csv_rows(path):
        if g is None:
            idx, g = getter(header)
            need = ("organizationId", "assessmentUnitId", "reportingCycle")
            if any(col(k) not in idx for k in need):
                raise AttainsError(f"{path.name}: columns missing ({', '.join(k for k in need if col(k) not in idx)})")
        org, cyc = g(row, "organizationId"), _int(g(row, "reportingCycle"))
        if cyc is not None and cyc > org_max.get(org, 0):
            org_max[org] = cyc
        group = g(row, "parameterGroup").upper()
        if group == PATHOGEN_GROUP:
            pathogen_names.add(g(row, "parameterName").upper())
        key = (org, g(row, "assessmentUnitId"))
        if key not in wanted or cyc is None:
            continue
        u = units.get(key + (cyc,))
        if u is None:
            u = units[key + (cyc,)] = {
                "org_name": g(row, "organizationName"), "state": g(row, "state"),
                "au_name": g(row, "assessmentUnitName"), "cycle_status": g(row, "cycleStatus") or None,
                "water_type": g(row, "waterType") or None, "size": _num(g(row, "waterSize")),
                "size_units": g(row, "waterSizeUnits") or None, "location": g(row, "locationDescription") or None,
                "overall_status": g(row, "overallStatus") or None, "ir_category": g(row, "epaIrCategory") or None,
                "uses": {}, "pathogens": {}}
        use, use_group = g(row, "useName"), g(row, "useGroup")
        if use and (use_group.upper() == "RECREATION_USE" or (not use_group and RECREATION_USE.search(use))):
            have = u["uses"].get(use)
            rec = {"support": support_words(g(row, "useSupport")),
                   "monitoring_start": _date(g(row, "monitoringStartDate")),
                   "monitoring_end": _date(g(row, "monitoringEndDate")),
                   "assessment_date": _date(g(row, "assessmentDate"))}
            if have is None:
                u["uses"][use] = rec
            else:
                for k, v in rec.items():
                    have[k] = have[k] or v
        if group == PATHOGEN_GROUP and g(row, "parameterName"):
            p = g(row, "parameterName").upper()
            status = g(row, "parameterStatus") or None
            have = u["pathogens"].get(p)
            rec = {"parameter": p, "status": status, "ir_category": g(row, "parameterIrCategory") or None,
                   "first_listed": _int(g(row, "cycleFirstListed")), "delisted": _yn(g(row, "delisted")),
                   "tmdl": g(row, "associatedActionType").upper() == "TMDL", "uses": set(), "use_groups": set()}
            if have is None or STATUS_RANK.get(str(status).lower(), 0) > STATUS_RANK.get(str(have["status"]).lower(), 0):
                if have is not None:
                    rec["tmdl"] = rec["tmdl"] or have["tmdl"]
                    rec["uses"], rec["use_groups"] = have["uses"], have["use_groups"]
                u["pathogens"][p] = rec
            else:
                have["tmdl"] = have["tmdl"] or rec["tmdl"]
                have["first_listed"] = have["first_listed"] or rec["first_listed"]
            # the uses the parameter is assessed against: each row is one unit x use x parameter (none named: none kept)
            kept = u["pathogens"][p]
            if use:
                kept["uses"].add(use)
            if use and use_group:
                kept["use_groups"].add(use_group.upper())
    return units, org_max, pathogen_names


def read_sources(path: Path, wanted: set[tuple[str, str]], pathogen_names: set[str]) -> tuple[dict, dict]:
    """(per (org, au, cycle) the probable sources of its PATHOGENS causes, the latest cycle of every organization in
    the sources file)."""
    org_max: dict[str, int] = {}
    out: dict[tuple, list] = defaultdict(list)
    g = None
    for header, row in csv_rows(path):
        if g is None:
            _, g = getter(header)
        org, cyc = g(row, "organizationId"), _int(g(row, "reportingCycle"))
        if cyc is not None and cyc > org_max.get(org, 0):
            org_max[org] = cyc
        key = (org, g(row, "assessmentUnitId"))
        if key not in wanted or cyc is None:
            continue
        cause = g(row, "causeName").upper()
        if g(row, "parameterGroup").upper() != PATHOGEN_GROUP and cause not in pathogen_names:
            continue
        out[key + (cyc,)].append({"name": g(row, "sourceName"), "cause": cause or None,
                                  "confirmed": _yn(g(row, "confirmed"))})
    return dict(out), org_max


def read_units(path: Path, wanted: set[tuple[str, str]]) -> dict:
    """Per (org, au) the unit's record of its latest cycle in the assessment-units file (water type, size, location)."""
    out: dict[tuple, dict] = {}
    g = None
    for header, row in csv_rows(path):
        if g is None:
            _, g = getter(header)
        key = (g(row, "organizationId"), g(row, "assessmentUnitId"))
        if key not in wanted:
            continue
        cyc = _int(g(row, "reportingCycle")) or 0
        have = out.get(key)
        if have is not None and have["cycle"] > cyc:
            continue
        rec = {"cycle": cyc, "org_name": g(row, "organizationName"), "state": g(row, "state"),
               "au_name": g(row, "assessmentUnitName"), "water_type": g(row, "waterType") or None,
               "size": _num(g(row, "waterSize")), "size_units": g(row, "waterSizeUnits") or None,
               "location": g(row, "locationDescription") or None, "au_status": g(row, "assessmentUnitStatus") or None}
        if have is not None and have["cycle"] == cyc:          # one row per water type: the first, the others added
            if rec["water_type"] and rec["water_type"] not in str(have["water_type"]):
                have["water_type"] = f"{have['water_type']}; {rec['water_type']}" if have["water_type"] else rec["water_type"]
            continue
        out[key] = rec
    return out


# ---------------------------------------------------------------- geometry


def esri_geometry(layer: int, g: dict):
    """An ArcGIS JSON geometry as shapely (multipoint, polyline paths, polygon rings with holes), or None."""
    from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon
    from shapely.validation import make_valid
    if not isinstance(g, dict):
        return None
    if layer == 0:
        pts = g.get("points") or ([[g["x"], g["y"]]] if "x" in g and "y" in g else [])
        pts = [Point(p[0], p[1]) for p in pts if len(p) >= 2]
        return MultiPoint(pts) if len(pts) > 1 else (pts[0] if pts else None)
    if layer == 1:
        paths = [LineString(p) for p in g.get("paths") or [] if len(p) >= 2]
        return MultiLineString(paths) if len(paths) > 1 else (paths[0] if paths else None)
    rings = [r for r in g.get("rings") or [] if len(r) >= 4]
    if not rings:
        return None

    def signed(r):
        return sum(x1 * y2 - x2 * y1 for (x1, y1, *_), (x2, y2, *_) in zip(r, r[1:]))
    outers = [[Polygon(r), []] for r in rings if signed(r) <= 0]       # ArcGIS: outer rings clockwise
    holes = [r for r in rings if signed(r) > 0]
    if not outers:                                                     # a ring list in the other orientation
        outers, holes = [[Polygon(r), []] for r in holes], []
    for h in holes:
        hp = Point(h[0][0], h[0][1])
        home = next((o for o in outers if o[0].contains(hp)), None)
        if home is not None:
            home[1].append(h)
    polys = [Polygon(o[0].exterior.coords, o[1]) for o in outers]
    geom = MultiPolygon(polys) if len(polys) > 1 else polys[0]
    return geom if geom.is_valid else make_valid(geom)


def fetch_control(client: Client) -> dict:
    """The control table's state organizations: {state: [{org_id, org_name, cycle, created_on}]}."""
    d = client.get_json(f"{FS_URL}/{CONTROL_TABLE}/query", params={
        "where": "orgtype='State'", "outFields": "state,organizationid,organizationname,reportingcycle,createdon",
        "returnGeometry": "false", "f": "json"})
    out: dict[str, list] = defaultdict(list)
    for f in d.get("features") or []:
        a = f.get("attributes") or {}
        st = str(a.get("state") or "").upper()
        if re.fullmatch(r"[A-Z]{2}", st):
            out[st].append({"org_id": a.get("organizationid"), "org_name": a.get("organizationname"),
                            "cycle": a.get("reportingcycle"), "created_on": a.get("createdon")})
    return dict(out)


def layer_edits(client: Client) -> dict:
    """{layer: dataLastEditDate as ISO time} for the three geometry layers."""
    out = {}
    for layer in LAYERS:
        d = client.get_json(f"{FS_URL}/{layer}", params={"f": "json"})
        ms = ((d.get("editingInfo") or {}).get("dataLastEditDate"))
        out[str(layer)] = ms_iso(ms)
    return out


def ms_iso(ms) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_state_layer(client: Client, state: str, layer: int, log=print) -> list[list]:
    """Every feature of one state organization in one layer, paged by OBJECTID (keyset), as compact rows
    [layer, org, au_id, au_name, cycle, report_link, recreation_use, pathogens, cycle_status, geometry]."""
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise ValueError(f"not a state code: {state!r}")
    rows, last = [], 0
    while True:
        d = client.get_json(f"{FS_URL}/{layer}/query", params={
            "where": f"orgtype='State' AND state='{state}' AND OBJECTID>{last}", "outFields": OUT_FIELDS,
            "returnGeometry": "true", "outSR": "4326", "maxAllowableOffset": str(MAX_OFFSET_DEG),
            "geometryPrecision": str(PRECISION), "orderByFields": "OBJECTID", "resultRecordCount": str(PAGE),
            "f": "json"})
        feats = d.get("features") or []
        for f in feats:
            a = f.get("attributes") or {}
            oid = a.get("OBJECTID")
            if isinstance(oid, int) and oid > last:
                last = oid
            rows.append([layer, a.get("organizationid"), a.get("assessmentunitidentifier"), a.get("assessmentunitname"),
                         a.get("reportingcycle"), a.get("waterbodyreportlink"), a.get("recreation_use"),
                         a.get("pathogens"), a.get("cyclestatus"), f.get("geometry")])
        if not feats or (len(feats) < PAGE and not d.get("exceededTransferLimit")):
            break
    log(f"attains: {state} layer {layer} ({LAYERS[layer]}s): {len(rows):,} features")
    return rows


def geometry_due(state: str, control: dict, edits: dict, manifest: dict, now: datetime, force: bool = False) -> str | None:
    """Why a state's cached geometry must be fetched again (no copy, the state's load date in the control table
    changed, older than GEOM_MAX_DAYS, or asked), or None when the cached copy stands. A layer's edit date changes
    whenever any state is reloaded, so it is recorded, not compared."""
    have = manifest.get(state)
    if force:
        return "asked"
    if not have:
        return "no copy"
    loads = sorted(str(o.get("created_on")) for o in control.get(state) or [])
    if have.get("loads") != loads:
        return "the state's load date changed"
    t = parse_time(have.get("fetched_at"))
    if t is None or now - t > timedelta(days=GEOM_MAX_DAYS):
        return f"older than {GEOM_MAX_DAYS} days"
    return None


def parse_time(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def read_manifest(geom_dir: Path = GEOM_DIR) -> dict:
    try:
        d = json.loads((geom_dir / "manifest.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json_atomic(path: Path, obj, compress: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    if compress:
        with gzip.open(tmp, "wb", compresslevel=6) as f:
            f.write(data)
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def state_geometry(client: Client | None, state: str, control: dict, edits: dict, geom_dir: Path = GEOM_DIR,
                   force: bool = False, offline: bool = False, now: datetime | None = None, log=print) -> list | None:
    """One state's features: the cached copy when it stands (geometry_due), else fetched from the three layers and
    cached (geom/<st>.json.gz and the manifest). None when there is neither (offline, or the fetch failed)."""
    now = now or datetime.now(UTC)
    manifest = read_manifest(geom_dir)
    p = geom_dir / f"{state}.json.gz"
    why = None if offline else geometry_due(state, control, edits, manifest, now, force)
    if why is None and p.is_file():
        try:
            with gzip.open(p, "rb") as f:
                return json.loads(f.read())
        except (OSError, ValueError, EOFError) as e:
            if offline:
                log(f"attains: {state} geometry cache unreadable ({error_text(e)})")
                return None
            why = "cache unreadable"
    if offline or client is None:
        return None
    log(f"attains: {state} geometry: fetching ({why})")
    rows = []
    for layer in LAYERS:
        rows += fetch_state_layer(client, state, layer, log=log)
    write_json_atomic(p, rows, compress=True)
    manifest = read_manifest(geom_dir)
    manifest[state] = {"fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "features": len(rows), "layer_edits": edits,
                       "loads": sorted(str(o.get("created_on")) for o in control.get(state) or [])}
    write_json_atomic(geom_dir / "manifest.json", manifest)
    return rows


def group_units(rows: list[list]) -> dict[tuple[str, str], dict]:
    """The features of a state grouped by (org, au): the rows repeat per geometry part; their geometries are joined."""
    from shapely.geometry import GeometryCollection
    from shapely.ops import unary_union
    parts: dict[tuple, dict] = {}
    for layer, org, au, name, cyc, link, rec, path, cstat, g in rows:
        if not org or not au:
            continue
        geom = esri_geometry(int(layer), g)
        if geom is None or geom.is_empty:
            continue
        u = parts.setdefault((org, au), {"org_id": org, "au_id": au, "au_name": name, "cycle": cyc, "link": link,
                                         "recreation_use": rec, "pathogens": path, "cycle_status": cstat,
                                         "geoms": [], "layers": set()})
        u["geoms"].append(geom)
        u["layers"].add(int(layer))
    for u in parts.values():
        gs = u.pop("geoms")
        if len(gs) == 1:
            u["geom"] = gs[0]
        else:
            try:
                u["geom"] = unary_union(gs)
            except Exception:  # noqa: BLE001 - a bad part: keep them as a collection
                u["geom"] = GeometryCollection(gs)
        u["kind"] = "area" if 2 in u["layers"] else "line" if 1 in u["layers"] else "point"
    return parts


# ---------------------------------------------------------------- the join


def _project(geom, lon0: float, lat0: float):
    """A geometry in metres on a local equirectangular projection about (lon0, lat0)."""
    import shapely
    k = math.cos(math.radians(lat0)) * M_PER_DEG

    def f(xy):
        out = xy.copy()
        out[:, 0] = (xy[:, 0] - lon0) * k
        out[:, 1] = (xy[:, 1] - lat0) * M_PER_DEG
        return out
    return shapely.transform(geom, f)


def _polygons(geom):
    from shapely.geometry import MultiPolygon, Polygon
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [p for g in getattr(geom, "geoms", []) for p in _polygons(g)]


def geometry_test(au_geom, au_kind: str, water_geom, inside_only: bool = False) -> tuple[bool, int | None, str | None]:
    """(passes, distance in metres, why not) of a unit against a water. A line passes when it lies along the water
    (within MATCH_M for at least half its length or ALONG_MIN_M), an area when it meets the water or lies within
    MATCH_M, a point when within MATCH_M; with inside_only, when INSIDE_SHARE of the unit lies inside the water's
    polygons (buffered MATCH_M). why: "too_far", "not_along" or "not_inside"; the distance is None when the water is
    nowhere near the unit's box."""
    from shapely.geometry import box
    c = au_geom.centroid if not au_geom.is_empty else None
    if c is None or c.is_empty:
        return False, None, "too_far"
    lon0, lat0 = c.x, c.y
    pad = (MATCH_M * 3) / (M_PER_DEG * max(0.05, math.cos(math.radians(abs(lat0)))))
    minx, miny, maxx, maxy = au_geom.bounds
    try:
        near = water_geom.intersection(box(minx - pad, miny - pad, maxx + pad, maxy + pad))
    except Exception:  # noqa: BLE001 - an invalid outline: test against the whole
        near = water_geom
    if near.is_empty:
        return False, None, "too_far"
    a = _project(au_geom, lon0, lat0)
    w = _project(near, lon0, lat0)
    d = round(a.distance(w))
    if inside_only:
        polys = _polygons(w)
        if not polys:
            return False, d, "not_inside"
        from shapely.ops import unary_union
        zone = unary_union(polys).buffer(MATCH_M)
        if au_kind == "area":
            share = a.intersection(zone).area / a.area if a.area else 0.0
        elif au_kind == "line":
            share = a.intersection(zone).length / a.length if a.length else 0.0
        else:
            share = 1.0 if zone.contains(a) else 0.0
        return (True, d, None) if share >= INSIDE_SHARE else (False, d, "not_inside")
    if d > MATCH_M:
        return False, d, "too_far"
    if au_kind == "line":
        length = a.length
        along = a.intersection(w.buffer(MATCH_M)).length if length else 0.0
        if along < min(0.5 * length, ALONG_MIN_M):
            return False, d, "not_along"
    return True, d, None


def measure(au_geom, au_kind: str, water_geom, inside_only: bool = False) -> dict | None:
    """geometry_test as a match: {distance_m, method} when it passes, else None."""
    ok, d, _ = geometry_test(au_geom, au_kind, water_geom, inside_only)
    if not ok:
        return None
    return {"distance_m": d, "method": "geometry_inside" if inside_only else "geometry+name"}


def water_index(waters: dict, geometry_of) -> tuple[list, list, object]:
    """(slugs, simplified outlines, STRtree) of the water records that have an outline."""
    from shapely import STRtree
    slugs, geoms = [], []
    for slug in sorted(waters):
        g = geometry_of(slug)
        if g is None or g.is_empty:
            continue
        try:
            g2 = g.simplify(WATER_SIMPLIFY_DEG, preserve_topology=True)
        except Exception:  # noqa: BLE001
            g2 = g
        if g2.is_empty:
            continue
        slugs.append(slug)
        geoms.append(g2)
    return slugs, geoms, (STRtree(geoms) if geoms else None)


# Why a candidate the geometry search found was not taken (the audit list in the cache, never published):
#   name_mismatch     it lies along the water within MATCH_M but the names do not agree
#   too_far           the names agree but it lies farther than MATCH_M
#   not_along         the names agree and it comes within MATCH_M, but not along the water (a confluence or crossing)
#   unnamed_on_river  an unnamed or lumped unit along a river, stream, bay or canal (unnamed units match lakes only)
#   not_inside        an unnamed unit near a lake, pond or reservoir that does not lie inside its outline
#   no_name           a unit named by a code whose location text could not be read
#   other_state       a unit that would match, but of another state's assessment (a water keeps its own state's units)
# and, for a unit that was taken: ambiguous_multi_water, when it matched more than one water (kept on each).
REJECT_REASONS = ("name_mismatch", "too_far", "not_along", "unnamed_on_river", "not_inside", "no_name", "other_state")


def match_state(units: dict, waters: dict, slugs: list, geoms: list, tree,
                rejected: dict | None = None) -> dict[str, list]:
    """{slug: [(unit key, match)]} for one state's units: candidates from the tree (within MATCH_M in degrees at the
    state's highest latitude, a superset), then the name test, then the metric test. With `rejected` (a dict), the
    candidates not taken are added to it, {slug: [(unit key, reason, distance_m)]}, with the reasons of
    REJECT_REASONS; a name that disagrees on a unit that does not lie along the water is not listed (noise)."""
    if tree is None or not units:
        return {}
    keys = list(units)
    ugeoms = [units[k]["geom"] for k in keys]
    maxlat = max(abs(g.bounds[3]) for g in ugeoms)
    maxlat = max(maxlat, max(abs(g.bounds[1]) for g in ugeoms))
    deg = MATCH_M / (M_PER_DEG * max(0.05, math.cos(math.radians(min(maxlat, 85.0)))))
    pairs = tree.query(ugeoms, predicate="dwithin", distance=deg)
    out: dict[str, list] = defaultdict(list)

    def reject(slug, key, reason, d):
        if rejected is not None:
            rejected.setdefault(slug, []).append((key, reason, d))
    for ui, wi in zip(pairs[0].tolist(), pairs[1].tolist()):
        u = units[keys[ui]]
        key = keys[ui]
        slug = slugs[wi]
        w = waters[slug]
        names = [w.get("name")] + list(w.get("aliases") or [])
        name = u.get("match_name") or u["au_name"]
        if id_like(name):                # a code with no location text: no name to compare
            ok, d, _ = geometry_test(u["geom"], u["kind"], geoms[wi])
            if ok:
                reject(slug, key, "no_name", d)
            continue
        if is_unnamed(name):
            if w.get("kind") not in POLYGON_KINDS:
                ok, d, _ = geometry_test(u["geom"], u["kind"], geoms[wi])
                if ok:
                    reject(slug, key, "unnamed_on_river", d)
                continue
            ok, d, why = geometry_test(u["geom"], u["kind"], geoms[wi], inside_only=True)
            if not ok:
                if d is not None and d <= MATCH_M:
                    reject(slug, key, why, d)
                continue
            m = {"distance_m": d, "method": "geometry_inside"}
        else:
            agree = names_agree(names, name)
            ok, d, why = geometry_test(u["geom"], u["kind"], geoms[wi])
            if agree and not ok:
                reject(slug, key, why, d)
                continue
            if not agree:
                if ok:
                    reject(slug, key, "name_mismatch", d)
                continue
            m = {"distance_m": d, "method": "geometry+name"}
        if u.get("state") and u["state"] != water_state(slug, w):
            reject(slug, key, "other_state", d)     # a unit of another state's assessment: audit only
            continue
        if u.get("match_name"):
            m = {**m, "name_from": "location"}
        out[slug].append((key, m))
    return out


def water_state(slug: str, w: dict) -> str:
    """A water record's state: its own field, else its slug's last part ("mill-river-ma" -> "MA")."""
    return str(w.get("state") or "").upper() or str(slug).rsplit("-", 1)[-1].upper()


# ---------------------------------------------------------------- the units as published


def unit_record(key: tuple[str, str], lay: dict, match: dict, assess: dict | None, src_rows: list | None,
                src_cycle: int | None, au_file: dict | None) -> dict:
    """UNIT (docs/attains.md): the layer's identity and link, the national files' assessment of the organization's
    latest cycle (else the layer's flags, marked "from": "layer"), the sewage sources of its PATHOGENS causes."""
    org, au = key
    a = assess or {}
    f = au_file or {}
    rec_uses = a.get("uses") or {}
    rec = None
    if rec_uses:
        # the swimming use first (a primary-contact or plain "Recreation" use), then by name; the support shown is
        # "Not Supporting" when any recreation use is, else the first use's
        order = sorted(rec_uses.items(), key=lambda kv: (0 if "primary" in kv[0].lower() or kv[0].lower() == "recreation"
                                                         else 1, kv[0]))
        first = order[0][1]
        rec = {"support": first.get("support"), "uses": [k for k, _ in order],
               "monitoring_start": min((v["monitoring_start"] for v in rec_uses.values() if v.get("monitoring_start")),
                                       default=None),
               "monitoring_end": max((v["monitoring_end"] for v in rec_uses.values() if v.get("monitoring_end")),
                                     default=None),
               "assessment_date": max((v["assessment_date"] for v in rec_uses.values() if v.get("assessment_date")),
                                      default=None)}
        worst = [v.get("support") for v in rec_uses.values() if v.get("support")]
        if "Not Supporting" in worst:
            rec["support"] = "Not Supporting"
    elif not assess and lay.get("recreation_use"):
        rec = {"support": lay.get("recreation_use"), "uses": [], "monitoring_start": None, "monitoring_end": None,
               "assessment_date": None}
    if assess:
        pathogens = sorted((p for p in a.get("pathogens", {}).values()),
                           key=lambda p: (-STATUS_RANK.get(str(p.get("status")).lower(), 0), p["parameter"]))
        has_tmdl = any(p.get("tmdl") or str(p.get("ir_category") or "").upper().startswith("4A") for p in pathogens)
        pathogens = [public_pathogen(p) for p in pathogens]
    elif lay.get("pathogens"):
        pathogens = [{"parameter": PATHOGEN_GROUP, "status": lay.get("pathogens"), "ir_category": None,
                      "first_listed": None}]
        has_tmdl = False
    else:
        pathogens, has_tmdl = [], False
    sources, seen = [], set()
    for s in src_rows or []:
        kind = sewage_kind(s.get("name"))
        if not kind:
            continue
        k = (s.get("name"), s.get("cause"))
        if k in seen:
            continue
        seen.add(k)
        sources.append({"name": s.get("name"), "kind": kind, "confirmed": s.get("confirmed"), "cause": s.get("cause"),
                        "cycle": src_cycle})
    cycle = a.get("_cycle") or lay.get("cycle")
    return {
        "org_id": org, "org_name": a.get("org_name") or f.get("org_name") or None,
        "state": a.get("state") or f.get("state") or lay.get("state"),
        "au_id": au, "au_name": lay.get("au_name") or a.get("au_name") or f.get("au_name"),
        "cycle": cycle, "cycle_status": a.get("cycle_status") or lay.get("cycle_status"),
        "water_type": a.get("water_type") or f.get("water_type"),
        "size": a.get("size") if a.get("size") is not None else f.get("size"),
        "size_units": a.get("size_units") or f.get("size_units"),
        "location": a.get("location") or f.get("location"),
        "recreation": rec,
        "pathogens": pathogens,
        "sewage_sources": sources,
        "has_tmdl": has_tmdl,
        "sources_cycle": src_cycle if sources else None,
        "report_url": (REPORT_URL.format(org=org, au=au) + (f"/{cycle}" if cycle else "")),
        "latest_url": REPORT_URL.format(org=org, au=au),
        "from": "national files" if assess else "layer",
        "match": {"method": match["method"], "distance_m": match["distance_m"], "geometry": lay.get("kind"),
                  **({"name_from": match["name_from"]} if match.get("name_from") else {})},
    }


def public_pathogen(p: dict) -> dict:
    """A PATHOGENS row as published: parameter, status, IR category, first listing, delisted only when true, and the
    use names (`uses`) and use groups (`use_groups`) the file ties it to, left out when it ties it to none."""
    out = {k: p.get(k) for k in ("parameter", "status", "ir_category", "first_listed")}
    if p.get("delisted"):
        out["delisted"] = True
    for k in ("uses", "use_groups"):
        if p.get(k):
            out[k] = sorted(p[k])
    return out


def pathogen_listed(u: dict) -> bool:
    return any(str(p.get("status")).lower() == "cause" for p in u.get("pathogens") or [])


def summary(units: list[dict]) -> dict:
    """SUMMARY: units, pathogen_listed (a PATHOGENS parameter in status Cause), sewage_named (a sewage source named),
    latest_cycle and the states."""
    cycles = [u["cycle"] for u in units if isinstance(u.get("cycle"), int)]
    return {"units": len(units), "pathogen_listed": sum(1 for u in units if pathogen_listed(u)),
            "sewage_named": sum(1 for u in units if u.get("sewage_sources")),
            "latest_cycle": max(cycles) if cycles else None,
            "states": sorted({u["state"] for u in units if u.get("state")})}


def sort_units(units: list[dict]) -> list[dict]:
    return sorted(units, key=lambda u: (not pathogen_listed(u), not u.get("sewage_sources"),
                                        u["match"]["distance_m"], u["au_id"]))


# ---------------------------------------------------------------- the optional web services


def api_fill(client: Client, key: tuple[str, str], pathogen_names: set[str], api_dir: Path = API_DIR,
             api_key: str | None = None, log=print) -> dict | None:
    """The unit's assessment from the ATTAINS web services (latest cycle), in read_assessments' shape plus
    "_sources", or None. Only with ATTAINS_API_KEY (or api_key): the key goes in the X-Api-Key header, never in the
    address or a log. Answers are cached under data/raw/attains/api/."""
    api_key = api_key if api_key is not None else os.environ.get("ATTAINS_API_KEY")
    if not api_key:
        return None
    org, au = key
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{org}__{au}")
    p = api_dir / f"{safe}.json"
    d = None
    if p.is_file():
        try:
            d = json.loads(p.read_text())
        except ValueError:
            d = None
    if d is None:
        try:
            d = client.get_json(f"{API_URL}assessments", params={"organizationId": org, "assessmentUnitIdentifier": au},
                                headers={"X-Api-Key": api_key})
        except AttainsError as e:
            log(f"attains: web services: {error_text(e)}")
            return None
        api_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d))
    return parse_api(d, au, pathogen_names)


def parse_api(d: dict, au: str, pathogen_names: set[str]) -> dict | None:
    """The fields read_assessments keeps, from a web-services assessments answer (items[].assessments[])."""
    for item in (d or {}).get("items") or []:
        cyc = _int(item.get("reportingCycleText"))
        for a in item.get("assessments") or []:
            if a.get("assessmentUnitIdentifier") != au:
                continue
            u = {"org_name": item.get("organizationName"), "state": None, "au_name": None,
                 "cycle_status": item.get("reportStatusCode"), "water_type": None, "size": None, "size_units": None,
                 "location": None, "overall_status": a.get("overallStatus"), "ir_category": a.get("epaIRCategory"),
                 "uses": {}, "pathogens": {}, "_cycle": cyc}
            for use in a.get("useAttainments") or []:
                name = use.get("useName") or ""
                if not RECREATION_USE.search(name):
                    continue
                md = use.get("assessmentMetadata") or {}
                mon = md.get("monitoringActivity") or {}
                code = str(use.get("useAttainmentCode") or "")
                u["uses"][name] = {"support": support_words(code),
                                   "monitoring_start": _date(mon.get("monitoringStartDate")),
                                   "monitoring_end": _date(mon.get("monitoringEndDate")),
                                   "assessment_date": _date(md.get("assessmentDate")
                                                            or (md.get("assessmentActivity") or {}).get("assessmentDate"))}
            for par in a.get("parameters") or []:
                name = str(par.get("parameterName") or "").upper()
                if not name or not (name in pathogen_names or PATHOGEN_NAME.search(name)):
                    continue
                li = ((par.get("impairedWatersInformation") or {}).get("listingInformation") or {})
                uses = {str(x.get("associatedUseName")) for x in par.get("associatedUses") or []
                        if isinstance(x, dict) and x.get("associatedUseName")}
                u["pathogens"][name] = {"parameter": name, "status": par.get("parameterStatusName"), "ir_category": None,
                                        "first_listed": _int(li.get("cycleFirstListedText")), "delisted": None,
                                        "tmdl": False, "uses": uses, "use_groups": set()}
            srcs = []
            for s in a.get("probableSources") or []:
                for c in s.get("associatedCauseNames") or [{}]:
                    cause = str(c.get("causeName") or "").upper()
                    if cause and not (cause in pathogen_names or PATHOGEN_NAME.search(cause)):
                        continue
                    srcs.append({"name": s.get("sourceName"), "cause": cause or None,
                                 "confirmed": _yn(s.get("sourceConfirmedIndicator"))})
            u["_sources"] = srcs
            return u
    return None


# ---------------------------------------------------------------- the build


def load_water_records():
    """The live water records and their outlines, as the export reads them (build/status.py)."""
    from build import status as status_mod
    waters = status_mod.live_waters(status_mod.load_waters())
    return waters, (lambda slug: status_mod.water_geometry(slug, waters))


def _audit(rejected: dict, units: dict, audit: dict) -> None:
    for slug, lst in rejected.items():
        for (org, au), reason, d in lst:
            audit[slug].append({"org_id": org, "au_id": au, "au_name": units[(org, au)]["au_name"], "reason": reason,
                                "distance_m": d,
                                **({"state": units[(org, au)].get("state")} if reason == "other_state" else {})})


def _take(found: dict, units: dict, layer_units: dict, matches: dict) -> int:
    n = 0
    for slug, lst in found.items():
        for key, m in lst:
            layer_units[key] = {k: v for k, v in units[key].items() if k not in ("geom", "layers", "match_name")}
            matches[slug].append((key, m))
            n += 1
    return n


def build(states: list[str] | None = None, out: Path = OUT, raw_dir: Path = RAW_DIR, geom_dir: Path | None = None,
          client: Client | None = None, offline: bool = False, refresh_geometry: bool = False,
          waters: dict | None = None, geometry_of=None, now: datetime | None = None, log=print) -> dict:
    """Join the water records to the assessment units of `states` (default: every state organization in the control
    table) and write `out`. Returns the written object."""
    now = now or datetime.now(UTC)
    geom_dir = geom_dir or (raw_dir / "geom")
    client = client or Client(log=log)
    t0 = time.monotonic()
    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # the file list and the layers' edit dates (offline: the cached sidecars and manifest only)
    if offline:
        files_meta = {}
        for key, fname in FILES.items():
            try:
                files_meta[key] = json.loads((raw_dir / (fname + ".meta.json")).read_text())
            except (OSError, ValueError):
                raise AttainsError(f"offline: no cached {key} file")
        control, edits = {}, {}
        manifest = read_manifest(geom_dir)
        control = {st: [] for st in manifest}
        edits = next((m.get("layer_edits") for m in manifest.values() if m.get("layer_edits")), {}) or {}
    else:
        files_meta = lookup_files(client)
        control = fetch_control(client)
        edits = layer_edits(client)
    if waters is None or geometry_of is None:
        waters, geometry_of = load_water_records()
    # default: the live states (data/rules.json live_states) that have a state organization in the control table
    want_states = sorted(states) if states else sorted(st for st in control if st in set(live_states()))
    slugs, wgeoms, tree = water_index(waters, geometry_of)
    log(f"attains: {len(waters):,} water records, {len(slugs):,} with an outline; states {', '.join(want_states)}")
    # the join, state by state
    paths = {k: (raw_dir / FILES[k]) if offline else download(client, k, files_meta[k], raw_dir, log=log) for k in FILES}
    layer_units: dict[tuple, dict] = {}
    matches: dict[str, list] = defaultdict(list)
    coded: dict[tuple, dict] = {}            # units named by a code: matched once their location text is read
    audit: dict[str, list] = defaultdict(list)   # the candidates not taken, per water (the cache only)
    geometry_fetched = {}
    per_state_units = Counter()
    failed_states = []
    for st in want_states:
        try:
            rows = state_geometry(None if offline else client, st, control, edits, geom_dir, force=refresh_geometry,
                                  offline=offline, now=now, log=log)
        except AttainsError as e:
            log(f"attains: {st} geometry not fetched ({error_text(e)}); the state is left out this run")
            failed_states.append(st)
            continue
        if rows is None:
            log(f"attains: {st}: no geometry")
            failed_states.append(st)
            continue
        units = group_units(rows)
        for u in units.values():
            u["state"] = st
        per_state_units[st] = len(units)
        held = {k: u for k, u in units.items() if id_like(u["au_name"])}
        coded.update(held)
        rej: dict = {}
        found = match_state({k: u for k, u in units.items() if k not in held}, waters, slugs, wgeoms, tree, rej)
        n_pairs = _take(found, units, layer_units, matches)
        _audit(rej, units, audit)
        geometry_fetched[st] = (read_manifest(geom_dir).get(st) or {}).get("fetched_at")
        log(f"attains: {st}: {len(units):,} units, {len(found):,} waters matched ({n_pairs:,} pairs)"
            + (f"; {len(held):,} named by a code, matched by their location text below" if held else ""))
    if failed_states:
        # a partial file never replaces a whole one: the workflow saves nothing and the last good file stands
        raise AttainsError(f"no geometry for {', '.join(failed_states)}; {out.name} not written")
    if coded:
        t1 = time.monotonic()
        loc = read_units(paths["assessmentUnits"], set(coded))
        for k, u in coded.items():
            u["match_name"] = (loc.get(k) or {}).get("location")
        rej = {}
        found = match_state(coded, waters, slugs, wgeoms, tree, rej)
        n_pairs = _take(found, coded, layer_units, matches)
        _audit(rej, coded, audit)
        log(f"attains: {len(coded):,} units named by a code: {len(found):,} waters matched by their location text "
            f"({n_pairs:,} pairs, {time.monotonic() - t1:.0f} s)")
    wanted = set(layer_units)
    log(f"attains: {len(wanted):,} units matched to {len(matches):,} waters; reading the national files")
    # the national files: streamed, kept to the matched units
    t1 = time.monotonic()
    assessments, a_org_max, pathogen_names = read_assessments(paths["assessments"], wanted)
    log(f"attains: assessments read ({len(assessments):,} unit-cycles kept, {time.monotonic() - t1:.0f} s)")
    t1 = time.monotonic()
    sources, s_org_max = read_sources(paths["sources"], wanted, pathogen_names)
    log(f"attains: sources read ({len(sources):,} unit-cycles kept, {time.monotonic() - t1:.0f} s)")
    t1 = time.monotonic()
    au_file = read_units(paths["assessmentUnits"], wanted)
    log(f"attains: assessment units read ({len(au_file):,} kept, {time.monotonic() - t1:.0f} s)")
    # each organization's latest cycle in each file
    units_out: dict[tuple, dict] = {}
    from_layer, api_used = 0, 0
    for key, lay in layer_units.items():
        org = key[0]
        a = assessments.get(key + (a_org_max.get(org),)) if a_org_max.get(org) else None
        if a is not None:
            a = {**a, "_cycle": a_org_max[org]}
        sc = s_org_max.get(org)
        srcs = sources.get(key + (sc,)) if sc else None
        if a is None and api_used < API_MAX_CALLS and os.environ.get("ATTAINS_API_KEY") and not offline:
            api_used += 1
            got = api_fill(client, key, pathogen_names, raw_dir / "api", log=log)
            if got is not None:
                a = got
                srcs, sc = got.pop("_sources", None), got.get("_cycle")
        if a is None:
            from_layer += 1
        units_out[key] = (lay, a, srcs, sc)
    log(f"attains: {len(units_out) - from_layer:,} units from the national files, {from_layer:,} from the layers "
        f"only{f', {api_used} web-service lookups' if api_used else ''}")
    # a unit taken by more than one water is kept on each; the audit names the others
    taken_by: dict[tuple, set] = defaultdict(set)
    dist: dict[tuple, int] = {}
    for slug, lst in matches.items():
        for key, m in lst:
            taken_by[key].add(slug)
            dist[(slug, key)] = min(m["distance_m"], dist.get((slug, key), m["distance_m"]))
    for key, slugs_of in taken_by.items():
        if len(slugs_of) > 1:
            for slug in slugs_of:
                audit[slug].append({"org_id": key[0], "au_id": key[1], "au_name": layer_units[key]["au_name"],
                                    "reason": "ambiguous_multi_water", "distance_m": dist[(slug, key)], "kept": True,
                                    "others": sorted(slugs_of - {slug})})
    waters_out = {}
    for slug, lst in sorted(matches.items()):
        best: dict[tuple, dict] = {}
        for key, m in lst:
            if key not in best or m["distance_m"] < best[key]["distance_m"]:
                best[key] = m
        recs = []
        for key, m in best.items():
            lay, a, srcs, sc = units_out[key]
            recs.append(unit_record(key, lay, m, a, srcs, sc, au_file.get(key)))
        recs = sort_units(recs)
        waters_out[slug] = {"units": recs, "summary": summary(recs)}
    # per state counts (a water counts in its own state)
    by_state: dict[str, Counter] = defaultdict(Counter)
    for slug, w in waters.items():
        st = str(w.get("state") or slug.rsplit("-", 1)[-1]).upper()
        if want_states and st not in want_states:
            continue
        c = by_state[st]
        c["waters"] += 1
        s = (waters_out.get(slug) or {}).get("summary")
        if s:
            c["waters_with_units"] += 1
            c["waters_pathogen_listed"] += 1 if s["pathogen_listed"] else 0
            c["waters_sewage_named"] += 1 if s["sewage_named"] else 0
    for st, n in per_state_units.items():
        by_state[st]["units"] = n
    obj = {
        "built": now_iso(),
        "source": {
            "name": SOURCE_NAME,
            "files": [{"name": k, "url": files_meta[k].get("url"), "timestamp": files_meta[k].get("timestamp"),
                       "bytes": files_meta[k].get("zipSize"), "rows": files_meta[k].get("numRows")} for k in FILES],
            "layers": {"url": FS_URL, "data_last_edited": max((v for v in edits.values() if v), default=None)},
            "fetched_at": fetched_at, "geometry_fetched": geometry_fetched,
            "latest_cycles": {"assessments": {o: c for o, c in sorted(a_org_max.items())},
                              "sources": {o: c for o, c in sorted(s_org_max.items())}},
        },
        "states": {st: dict(sorted(c.items())) for st, c in sorted(by_state.items())},
        "waters": waters_out,
        # the candidates the geometry search found and the join did not take, and the units taken by several waters,
        # per water, with the reason (REJECT_REASONS, ambiguous_multi_water): for audit; never exported
        "audit": {slug: sorted(lst, key=lambda x: (x["reason"], x["distance_m"] if x["distance_m"] is not None else 1e9,
                                                   x["au_id"]))
                  for slug, lst in sorted(audit.items())},
    }
    write_json_atomic(out, obj)
    tot = Counter()
    for st, c in sorted(by_state.items()):
        tot.update(c)
        log(f"attains: {st}: {c['waters_with_units']:,} of {c['waters']:,} waters with units, "
            f"{c['waters_pathogen_listed']:,} with a pathogen listing, {c['waters_sewage_named']:,} with a sewage source")
    reasons = Counter(x["reason"] for lst in audit.values() for x in lst)
    log("attains: audit (candidates not taken, units on several waters): "
        + ", ".join(f"{r} {n:,}" for r, n in sorted(reasons.items())))
    log(f"attains: wrote {out.name}: {tot['waters_with_units']:,} of {tot['waters']:,} waters with units, "
        f"{tot['waters_pathogen_listed']:,} with a pathogen listing, {tot['waters_sewage_named']:,} with a sewage "
        f"source named ({time.monotonic() - t0:.0f} s)")
    return obj


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT), help="the cache to write (default data/build/attains/attains-waters.json)")
    ap.add_argument("--states", nargs="*", help="state codes (default: every state organization in the control table)")
    ap.add_argument("--refresh-geometry", action="store_true", help="fetch every state's geometry again")
    ap.add_argument("--offline", action="store_true", help="the cached files and geometry only, no request")
    a = ap.parse_args(argv)
    states = [s.upper() for s in a.states] if a.states else None
    if states and any(not re.fullmatch(r"[A-Z]{2}", s) for s in states):
        print("attains: --states takes two-letter codes")
        return 2
    try:
        build(states, Path(a.out), offline=a.offline, refresh_geometry=a.refresh_geometry)
    except AttainsError as e:
        print(f"::error::attains: {error_text(e)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
