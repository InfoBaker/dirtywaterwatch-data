"""ADEM sanitary sewer overflow reports (Alabama) -> data/build/events/al-adem-sso-history.json

Source
  Alabama Department of Environmental Management (ADEM). Every sanitary sewer overflow (SSO) report a permittee files
  through AEPACS, ADEM's electronic permitting and compliance system, is posted on ADEM's public ArcGIS server within
  minutes of filing (a report filed 2026-11-03 13:40 was on both layers that afternoon). Two layers, public, no key,
  no licence or terms shown (copyrightText empty):
    history  https://gis.adem.alabama.gov/arcgis/rest/services/SSOs_ALL_OB_ID/MapServer/0 (registry al-adem-sso-history)
             one row per report at its latest version: 14,758 reports on 2026-11-07, starts from 2012-05-11 to
             2026-11-06 (about 1,100 to 2,300 a year since 2017), 319 permits. Fields read (FIELDS): object_id,
             sso_report_id, sso_report_version, lat, long, LOCATION_OF_DISCHARGE, rec_stream, date_sso_began,
             date_sso_stopped, sso_ongoing_ind, est_volume, permittee, facility_site_name, permit_no. maxRecordCount
             2000; resultOffset paging fails on this server, so pages are object_id ranges or a where clause.
    live     https://gis.adem.alabama.gov/arcgis/rest/services/SSO_Service/MapServer/0 (registry al-adem-sso-map-live)
             the public SSO map's layer: reports still ongoing plus 10 days after they stop (AEPACS form: SSOs "are
             displayed on the map for 10 days after the SSO has ceased"); 31 rows on 2026-11-07. It adds received_date
             (ADEM's receipt of the filing), report_type, cause_of_discharge and the volume range in full.
  Law: Ala. Admin. Code r. 335-6-6-.12(l)6.(v), the permittee "shall report to the Director, the public, the county
  health department ... as soon as possible" upon becoming aware of a notifiable SSO (r. 335-6-6-.02(hh): one that
  reaches a surface water of the State or may imminently and substantially endanger human health); ADEM's AEPACS form
  sets the notice at 24 hours and a written follow-up at 5 days.

Reading
  Every run reads the live layer (one query) and the history rows that started in the last LOOKBACK_DAYS or are
  marked ongoing (one where clause). Once every FULL_EVERY_HOURS (and with --full) the whole history layer is read in
  object_id ranges of 2,000; a full read with fewer than half the reports of the last good one is an outage (ok false,
  the records kept). Records of earlier runs are carried: the events file is the history seen so far; a report missing
  from a full read keeps its record with raw._missing_from_layer_since.

Record rules (one sso record per ADEM report id, source_record_id "SSO-00215084")
  - The live layer gives old ids as bare numbers ("8447"); they are written as the history layer writes them
    ("SSO-00008447").
  - Times: the history layer stores Central wall-clock time as if it were UTC (an epoch of 13:03 UTC is the live
    layer's "2026-11-03 01:03 pm" for the same report, checked on all 31 live-layer reports on 2026-11-07): each value is
    read as UTC and its wall-clock time labelled America/Chicago (raw._time_basis). time_precision minute.
    reported_at is the live layer's received_date (Central time) when the report is still at version 1 there: the
    field is the receipt of the latest version filed, so for a later version it is kept in raw._received_latest_version
    and never taken for the first notice; once set it is kept. The history layer gives no receipt time, so most
    reports have none. published_at and
    source_updated_at are null (the layers give no posting or edit time); raw._first_seen_at is our clock.
  - Status: sso_ongoing_ind Yes -> ongoing, as ADEM marks it, however old the start (nine reports on 2026-11-07, one
    from 2018-03-18); a stop time -> ended at it; otherwise unknown. A stop before the start is not used.
  - Volume: est_volume as filed. A number is volume_gal ("1200", "500.00"); a range on ADEM's form ("250,000 < gallons
    <= 500,000") is volume_text only, never turned into one figure; the history layer cuts the wording at 15
    characters ("250,000 < gall", "<=1,0"), so the live layer's full wording is used when it has the report, else the
    words say only what the cut text states ("more than 250,000 gallons", "1,000 gallons or less"). estimate_flag
    estimated (the form asks for an estimate).
  - Receiving water: rec_stream (the live layer's receiving_stream when present) is split at semicolons. Each part is
    a named water ("Eslava Creek", "UT to Stinking Bear Creek", a conduit with the water in brackets: "Storm
    Drain(Tanyard Branch)" -> Tanyard Branch; a lake in brackets after a river: "Tennessee River (Wheeler Lake)" ->
    both), a conduit alone ("Storm Drain", "Drainage Ditch"), a statement that no water was reached ("Ground Absorbed",
    "Backup into Building/Residence", "CONTAINED", "Onto Street", "pump truck"), or other words. raw.reached_water is
    true when a part names a water (the names are waterbody_text, joined by "; "), null when a conduit or other words
    are the most it says (a storm drain leads to a water the report does not name) or the field is empty, false when
    every part says the sewage stayed out of water: such a report is kept, never placed on a water
    (raw._no_water_reason). water_slugs stay empty: the status build places by name and point.
  - A report whose words say it duplicates another report or was not an overflow keeps its record; when it names
    another ADEM report id that is on the layer, duplicate_of points to it (raw._report_note quotes the words).
  - Point: lat/long as filed (every report has one); a point outside Alabama's box is not used (raw._coords_rejected).
  - Operator: permit_no -> the Alabama row of data/dischargers.json holding the permit; discharger_name is ADEM's
    permittee as filed.
  - event_type sso for every report: ADEM's layer is the SSO report system (some reports are at a plant's own lift
    station; the location words say so).
Privacy: the layers carry no reporter, contact or certifier field (none is requested). A permittee that reads as a
  person's name (common.scrub_discharger: one permit on 2026-11-07) is "[name removed]" in discharger_name and in raw;
  the permit stays. LOCATION_OF_DISCHARGE,
  rec_stream and cause_of_discharge are typed by the permittee and often give a street address, frequently a home's
  ("2306 PEER CT", "Into Private Residence"): common.scrub_text runs on each (e-mails, phones, staff names) and then
  common.strip_house_numbers removes every street address's house number (the street and ADEM's point stay), then
  strip_al_house_numbers the forms it leaves (lettered avenues and courts, lists of numbers, titled names), as
  California's and Washington's spill feeds do; build.redact runs over the records last. tests/test_ingest_al.py
  proves a house number, an e-mail and a phone number never reach a record.
A language-model pass could later read the long free-text receiving-water parts that the rules leave as "other
words"; it would never supply a place or a colour.

Cadence: hourly. Run from pipeline/:
  python -m ingest.al_adem_sso [--full] [--file history.json [--live live.json]]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, HOUSE_NUMBER_REMOVED, NAME_REMOVED, event, now_iso, path_notes_to_meta, read_json,
                    save_raw, scrub_text, strip_house_numbers, write_events, write_json)

SOURCE_ID = "al-adem-sso-history"
HISTORY = "https://gis.adem.alabama.gov/arcgis/rest/services/SSOs_ALL_OB_ID/MapServer/0"
LIVE = "https://gis.adem.alabama.gov/arcgis/rest/services/SSO_Service/MapServer/0"
MAP_URL = "https://gis.adem.alabama.gov/sso/index.html"
EFILE = "http://app.adem.alabama.gov/efile/results.aspx?PermitNumber={permit}&DocType=SSO"
STATE_FILE = BUILD_DIR / "al-adem-sso-state.json"
TZ = ZoneInfo("America/Chicago")
AUTHORITY = "Alabama Department of Environmental Management (SSO reports filed through AEPACS)"
FIELDS = ["object_id", "sso_report_id", "sso_report_version", "lat", "long", "LOCATION_OF_DISCHARGE", "rec_stream",
          "date_sso_began", "date_sso_stopped", "sso_ongoing_ind", "est_volume", "permittee", "facility_site_name",
          "permit_no"]
LIVE_FIELDS = ["sso_report_id", "sso_report_version", "permit_no", "permittee", "facility_site", "report_type",
               "received_date", "date_sso_began", "date_sso_stopped", "sso_ongoing_ind", "est_volume",
               "location_of_discharge", "receiving_stream", "lattitude_decimal", "longitude_decimal",
               "cause_of_discharge"]
LOOKBACK_DAYS = 60
FULL_EVERY_HOURS = 20
PAGE = 2000
MIN_RATIO = 0.5
AL_BOX = (-88.6, -84.8, 30.1, 35.1)          # lon min, lon max, lat min, lat max (Alabama with a margin)
TIME_BASIS = ("The history layer stores Central wall-clock time as if it were UTC: each epoch value is read as UTC "
              "and the wall-clock time labelled America/Chicago (the live layer's text times agree).")

# ---------------------------------------------------------------- receiving water words
CONDUIT = re.compile(r"(?i)^(storm\s*drain|drainage\s*ditch|ditch|culvert|catch\s*basin|storm\s*water\s*basin)\b")
STORM = re.compile(r"(?i)\b(storm\s*drains?|drainage\s*ditch(es)?|ditch(es)?|culverts?|catch\s*basin|storm\s*water|"
                   r"retention|detention|basin)\b")
WATER = re.compile(r"(?i)\b(creek|branch|river|bayou|lake|bay|run|slough|pond|reservoir|springs?|fork|canal|tributary|"
                   r"trib|harbou?r|lagoon|swamp|marsh|sound|gulf|gull(e)?y|waterway|pass|wetlands?|cove|inlet|stream|"
                   r"brook|bogue)\b|^UT\b")
NOT_REACHED = re.compile(r"(?i)did\s*not\s*(reach|make\s*it)|no\s+\w+\s+reached|not\s+reach|never\s+reached")
NO_WATER = re.compile(
    r"(?i)ground|absorb|backup|back-up|building|residence|\bhouse\b|\bhomes?\b|basement|toilet|crawl\s*space|contain|"
    r"vac+u+m|vacume?d|pump(ed)?\s+(back|into)|pump\s*trucks?|vac\s*trucks?|septage|reclaim|recover|captured|"
    r"no\s*discharge|no\s*overflow|not\s+an?\s+ov|street|curb|gutter|road|pavement|asphalt|parking|drive\s*way|yard|"
    r"\barea\b|lift\s*station|manhole|evaporat|dried|garbage|private|fenced|excavat|holding\s*tank|on-?\s*site|weeds|"
    r"grass|field|evidence|duplicate|hay\s*bales|right\s*of\s*way|\bROW\b|gravel|confined|raked|removed|shovel")
GENERIC = re.compile(r"(?i)^(the\s+)?(flat\s+low\s+level\s+)?(wetlands?|all\s+creeks|creek|stream|river|pond|"
                     r"subsidiary|susidiary|retention\s+pond)$")
PRIVATE_WATER = re.compile(r"(?i)\bprivate\b|^went\s+into|^pond\s+area|habitat|personal\s+property")
LEADS_TO = re.compile(r"(?i)\s*(?:,\s*)?\b(?:which|that)\s+(?:leads|flows|drains)\s+(?:in)?to\s+")
DESTINATION = re.compile(r"(?i)destination|not\s+listed|not\s+an\s+option|not\s+labeled|not\s+on\s+the\s+creek\s+list|"
                         r"not\s+under|discharged?\s+into|enter(s|ing)\s+into|going\s+.*into|on\s+into|flowing\s+into")
NEGATIVE = re.compile(r"(?i)no\s+signs?\s+of|did\s*not|not\s+reach|no\s+leak|non-notifiable|not\s+a\s+sanitary")
DEST_NAME = re.compile(r"(?i)\b([a-z]+)\s+(creek|river|branch)\b")
NOT_A_NAME_WORD = {"the", "into", "a", "an", "unnamed", "named", "on", "and", "to", "of", "in"}
INVALID = re.compile(r"(?i)invalid\s+named\s+receiving\s+water")
DUPLICATE = re.compile(r"(?i)duplicate|incorrect(ed)?\s+basin|please\s+see\s+SSO|not\s+an?\s+ove?rflow|"
                       r"there\s+was\s+no\s+overflow|not\s+related\s+to\s+a\s+sanitary\s+sewer\s+overflow|"
                       r"storm\s+drain\s+issue|not\s+a\s+sanitary\s+sewer\s+overflow|non-notifiable")
REPORT_ID = re.compile(r"\bSSO-?\s?(\d{5,8})\b", re.I)
MAX_NAME_WORDS = 7

# ---------------------------------------------------------------- volume
NUMBER = re.compile(r"^\s*([\d,]*\.?\d+)\s*(gal(lons?)?)?\s*$", re.I)
RANGE_FULL = re.compile(r"^\s*([\d,]+)\s*<\s*gal\w*\s*<=\s*([\d,]+)", re.I)
RANGE_LOW = re.compile(r"^\s*([\d,]+)\s*<", re.I)
AT_MOST = re.compile(r"^\s*<=\s*([\d,]+)\s*(gal\w*)?\s*$", re.I)
MORE_THAN = re.compile(r"^\s*>=?\s*([\d,]+)", re.I)
LESS = re.compile(r"^\s*<\s*([\d,]+)\s*(gal\w*)?\s*$", re.I)
# the lower bounds of the ranges on ADEM's form, read from the live layer's full wordings ("1,000 < gallons <= 10,000",
# "75,000 < gallons <= 100,000", ... "750,000 < gallons <= 1,000,000") and the history layer's lower bounds
BINS = ["1,000", "10,000", "25,000", "50,000", "75,000", "100,000", "250,000", "500,000", "750,000", "1,000,000"]


def report_id(v) -> str | None:
    s = str(v or "").strip()
    if not s:
        return None
    if s.isdigit():
        return f"SSO-{int(s):08d}"
    return s.upper()


def wall_clock(ms) -> datetime | None:
    """An epoch-ms value that holds Central wall-clock time stored as UTC -> aware America/Chicago."""
    if ms in (None, ""):
        return None
    try:
        t = datetime.fromtimestamp(float(ms) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return t.replace(tzinfo=None).replace(tzinfo=TZ)


def live_time(s) -> datetime | None:
    """The live layer's text times: '2026-11-03 01:03 pm', '2018-03-18 5:00 PM', 'Nov  2 2026 10:52AM' (Central)."""
    s = " ".join(str(s or "").split())
    if not s:
        return None
    for fmt in ("%Y-%m-%d %I:%M %p", "%b %d %Y %I:%M%p", "%Y-%m-%d %H:%M", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(s.upper() if "%p" in fmt else s, fmt.replace("%b", "%b")).replace(tzinfo=TZ)
        except ValueError:
            continue
    try:
        return datetime.strptime(s.title(), "%b %d %Y %I:%M%p").replace(tzinfo=TZ)
    except ValueError:
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# A house number common.strip_house_numbers leaves: Birmingham's lettered avenues and courts put the street word first
# ("4201 AVENUE T", "6716 COURT N"), lists of numbers ("1100, 1105, 1201 Avenue K") and named streets with a title
# ("1203 Dr Martin Luther King Jr Drive"). Here any number (or list) of up to six digits followed by a word is a house
# number, unless a route or unit word is next to it ("Hwy 29", "Lift Station 18", "100 yds", "2 inch") or it is part of a
# decimal, a coordinate, an id ("#3219", "SSO-00212633") or an ordinal ("21st"). Keyed on Alabama (this module only).
_UNIT = (r"(?:feet|foot|ft|yards?|yds?|miles?|mi|meters?|m|inch(?:es)?|in|gallons?|gals?|gal|gpm|gpd|mgd|psi|lbs?|"
         r"pounds?|hours?|hrs?|minutes?|mins?|seconds?|days?|weeks?|am|pm|a\.m\.|p\.m\.|percent|sq|square|x|by|lf|"
         r"linear|cubic|cy|degrees?|mph|loads?|times?|of|to|and|or|from|%)")
_NUM = r"\d{1,6}[A-Za-z]?"
AL_HOUSE_RE = re.compile(rf"(?<![\w.,/:#-]){_NUM}(?:[ ]{{0,2}},[ ]{{0,2}}(?:(?:and|&)[ ]{{1,2}})?{_NUM}|"
                         rf"[ ]{{1,2}}(?:and|&)[ ]{{1,2}}{_NUM})*(?=[ ]{{1,2}}(?![ ]*{_UNIT}\b)(?i:[NSEW]\.?[ ]{{1,2}})?[A-Za-z])",
                         re.I)
ROUTE_WORD = re.compile(r"(?i)\b(?:US|SR|CR|S\.?R\.?|C\.?R\.?|Hwy|Highway|Route|Rte|Interstate|I|Exit|Mile|Marker|MM|"
                        r"Ave|Avenue|Street|St|Road|Rd|Court|Ct|Lane|Ln|Drive|Dr|Circle|Cir|Place|Pl|Terrace|Way|"
                        r"Trail|Pkwy)[ .#-]{0,3}$")
# an identifier before a number ("Manhole 4698", "Lift Station 18"): the number is the asset's, unless a street word
# follows within four words ("Lift Station 2734 Morgan Russell Road", "lot 2096 Gadwell Drive": an address)
ID_WORD = re.compile(r"(?i)\b(?:Lot|Unit|Suite|Ste|Apt|Bldg|Building|Station|LS|PS|No|Number|Manhole|MH|Pump|Site|"
                     r"Phase|Section|Basin|Outfall|Line|Main|Gate|Pier|Box)[ .#-]{0,3}$")
STREET_AFTER = re.compile(r"(?i)^(?:[ ]{1,2}[A-Za-z][\w'.-]*){0,4}?[ ]{1,2}(?:Road|Rd|Street|St|Lane|Ln|Drive|Dr|Avenue|"
                          r"Ave|Circle|Cir|Court|Ct|Way|Place|Pl|Blvd|Boulevard|Pkwy|Parkway|Trail|Trl|Terrace|Cove|Cv|"
                          r"Loop|Run|Pike)\b")


def strip_al_house_numbers(v: str) -> str:
    """strip_house_numbers' leftovers (AL_HOUSE_RE): a leading house number or a list of them before a word."""
    def repl(m):
        before = v[max(0, m.start() - 16):m.start()]
        if ROUTE_WORD.search(before):
            return m.group(0)
        if ID_WORD.search(before) and not STREET_AFTER.match(v[m.end():]):
            return m.group(0)
        return HOUSE_NUMBER_REMOVED
    return AL_HOUSE_RE.sub(repl, v)


def clean_text(v) -> str | None:
    """Free text as typed, scrubbed: e-mails, phones, staff names, then every street address's house number
    (common.strip_house_numbers, then strip_al_house_numbers for the forms it leaves)."""
    if v is None:
        return None
    s = " ".join(str(v).split())
    if not s:
        return None
    return strip_al_house_numbers(strip_house_numbers(scrub_text(s))) or None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _bin(cut: str) -> str | None:
    """The one lower bound of ADEM's ranges that a cut text begins with ('100,00' -> '100,000'), else None
    ('1,0' begins both 1,000 and 1,000,000)."""
    hits = [b for b in BINS if b.startswith(cut.strip())]
    return hits[0] if len(hits) == 1 else None


def volume(text: str | None, cut: bool = False) -> tuple[int | None, str | None]:
    """(gallons, words) of est_volume as filed; a range stays words only. cut: the text may be cut short (the history
    layer keeps 15 characters), so a bound is completed only when it matches one of ADEM's own ranges (BINS)."""
    t = " ".join(str(text or "").split())
    if not t:
        return None, None
    m = NUMBER.match(t)
    if m:
        g = float(m.group(1).replace(",", ""))
        return int(round(g)), f"{g:,.0f} gallons (estimate as filed)"
    m = RANGE_FULL.match(t)
    if m:
        return None, f"{m.group(1)} to {m.group(2)} gallons (a range on ADEM's form)"
    m = AT_MOST.match(t)
    if m:
        top = m.group(1)
        if cut and top not in BINS:
            top = "1,000" if "1,000".startswith(top) else None       # the form's only "<=" range is <=1,000
        if top:
            return None, f"{top} gallons or less (a range on ADEM's form)"
        return None, f"a range on ADEM's form, cut short in the layer ({t!r})"
    m = LESS.match(t)
    if m:
        return None, f"less than {m.group(1)} gallons (as filed)"
    m = RANGE_LOW.match(t)
    if m:
        low = m.group(1) if not cut or m.group(1) in BINS else _bin(m.group(1))
        if not low:
            return None, f"a range on ADEM's form, cut short in the layer ({t!r})"
        nxt = BINS.index(low) + 1 if low in BINS else None
        if cut and nxt is not None and nxt < len(BINS) and not re.search(r"<=", t):
            return None, (f"more than {low} gallons (a range on ADEM's form, cut short in the layer; the form's range "
                          f"from {low} goes to {BINS[nxt]})")
        return None, f"more than {low} gallons (a range on ADEM's form)"
    m = MORE_THAN.match(t)
    if m:
        return None, f"more than {m.group(1)} gallons (a range on ADEM's form)"
    return None, f"{t} (as filed)"


def volume_text(hist: str | None, live: str | None) -> tuple[int | None, str | None, str]:
    """The live layer's full wording when it has the report, else the history layer's (cut at 15 characters)."""
    if live and str(live).strip():
        g, w = volume(live)
        return g, w, "live layer (est_volume, full wording)"
    g, w = volume(hist, cut=True)
    return g, w, "history layer (est_volume, cut at 15 characters)"


# ---------------------------------------------------------------- receiving water
def split_parts(s: str | None) -> list[str]:
    out, buf, depth = [], "", 0
    for ch in s or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [" ".join(x.split()) for x in out if x.strip()]


def is_name(s: str) -> bool:
    return bool(WATER.search(s)) and len(s.split()) <= MAX_NAME_WORDS and not NOT_REACHED.search(s) \
        and not STORM.search(re.sub(r"(?i)^UT\s+(to|of)\s+", "", s)) and not re.search(r"\d", s)


def classify(part: str) -> tuple[str, list[str]]:
    """(kind, names) of one part: kind water | generic | conduit | no_water | invalid | other."""
    if INVALID.search(part):
        return "invalid", []
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", part)
    if m:
        head, inner = m.group(1).strip(), m.group(2).strip()
        inner_names = []
        for x in [inner] if "(" not in inner else [re.sub(r"\s*\(.*$", "", inner), re.sub(r"^.*?\((.*)\)\s*$", r"\1", inner)]:
            x = x.strip()
            if x and is_name(x) and not GENERIC.match(x) and not PRIVATE_WATER.search(x):
                inner_names.append(x)
            elif x and WATER.search(x) and PRIVATE_WATER.search(x):
                return "generic", []
        if CONDUIT.match(head) or not head:
            return ("water", inner_names) if inner_names else ("conduit", [])
        if is_name(head) and not GENERIC.match(head):
            return "water", [head, *inner_names]
        if inner_names:
            return "water", inner_names
        part = head or inner
    if NOT_REACHED.search(part):
        return "no_water", []
    if GENERIC.match(part) or (WATER.search(part) and PRIVATE_WATER.search(part)):
        return "generic", []
    if LEADS_TO.search(part):
        names = [x.strip(" .,") for x in LEADS_TO.split(part) if x.strip(" .,")]
        if names and all(is_name(x) for x in names):
            return "water", names
    if DESTINATION.search(part) and not NEGATIVE.search(part):
        names = []
        for m in DEST_NAME.finditer(part):
            if m.group(1).lower() not in NOT_A_NAME_WORD:
                n = f"{m.group(1).title()} {m.group(2).title()}"
                if n not in names:
                    names.append(n)
        if names:
            return "water", names
    if is_name(part):
        return "water", [part]
    if STORM.search(part):
        return "conduit", []
    if NO_WATER.search(part):
        return "no_water", []
    return "other", []


def receiving(text: str | None) -> dict:
    """reached_water (True, False or None), names, the parts and why."""
    parts = split_parts(text)
    kinds, names = [], []
    for p in parts:
        k, ns = classify(p)
        kinds.append(k)
        for n in ns:
            if n not in names:
                names.append(n)
    out = {"parts": [{"text": p, "kind": k} for p, k in zip(parts, kinds)], "names": names}
    if names:
        out.update(reached_water=True, why="the report names the receiving water")
    elif "generic" in kinds:
        out.update(reached_water=True, why="the report says the sewage reached a water it does not name")
    elif "conduit" in kinds:
        out.update(reached_water=None, why="the report names a storm drain or ditch and no water")
    elif "invalid" in kinds:
        out.update(reached_water=None, why=("ADEM's layer gives 'Invalid Named Receiving Water Not Migrated': the "
                                           "name was lost when ADEM moved its records"))
    elif "other" in kinds:
        out.update(reached_water=None, why="the report's receiving-water words name no water")
    elif kinds:
        shown = "; ".join(parts)[:80]
        out.update(reached_water=False, why=f"the report names no water, only '{shown}'")
    else:
        out.update(reached_water=None, why="the report leaves the receiving water blank")
    return out


# ---------------------------------------------------------------- operators
def permit_index(data_dir: Path = DATA_DIR) -> dict[str, tuple[str, str]]:
    out = {}
    for d in read_json(data_dir / "dischargers.json", []) or []:
        if d.get("state") != "AL":
            continue
        for p in [d.get("npdes_permit"), *(d.get("npdes_permits") or [])]:
            if p:
                out.setdefault(str(p).upper(), (d["id"], d.get("name")))
    return out


# ---------------------------------------------------------------- records
def in_al(lat, lon) -> bool:
    x0, x1, y0, y1 = AL_BOX
    return lat is not None and lon is not None and x0 <= lon <= x1 and y0 <= lat <= y1


def to_record(a: dict, live: dict | None, fetched_at: str, prev: dict | None, ops: dict, known_ids: set[str]) -> dict:
    rid = report_id(a.get("sso_report_id"))
    base = dict(source_id=SOURCE_ID, source_record_id=rid, fetched_at=fetched_at,
                source_url=(f"{HISTORY}/query?where=sso_report_id%3D%27{quote(rid)}%27&outFields="
                            f"{','.join(FIELDS)}&returnGeometry=false&f=json"))
    row = {k: a.get(k) for k in FIELDS if k in a}
    for k in ("LOCATION_OF_DISCHARGE", "rec_stream", "facility_site_name"):
        if k in row:
            row[k] = clean_text(row[k])
    raw: dict = {"state": "AL", "row": row}
    try:
        return build_record(a, live, base, raw, prev, ops, known_ids)
    except Exception as e:  # noqa: BLE001 - never drop a report
        return event(**base, event_type="sso", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def build_record(a, live, base, raw, prev, ops, known_ids) -> dict:
    problems = []
    raw["_time_basis"] = TIME_BASIS
    start, stop = wall_clock(a.get("date_sso_began")), wall_clock(a.get("date_sso_stopped"))
    if live:
        lv = {k: live.get(k) for k in LIVE_FIELDS if k in live}
        for k in ("location_of_discharge", "receiving_stream", "cause_of_discharge", "facility_site"):
            if k in lv:
                lv[k] = clean_text(lv[k])
        raw["live"] = lv
        if start is None:
            start = live_time(live.get("date_sso_began"))
        if stop is None and live.get("date_sso_stopped"):
            stop = live_time(live.get("date_sso_stopped"))
    ongoing = str(a.get("sso_ongoing_ind") or (live or {}).get("sso_ongoing_ind") or "").strip().lower() == "yes"
    if ongoing:
        status, ended = "ongoing", None
        if stop is not None:
            raw["_stop_while_ongoing"] = iso(stop)
        if start is not None:
            raw["_ongoing_days"] = (datetime.now(TZ) - start).days
    elif stop is not None:
        status, ended = "ended", iso(stop)
    else:
        status, ended = "unknown", None
    if stop is not None and start is not None and stop < start:
        problems.append("date_sso_stopped before date_sso_began: ended_at left empty")
        ended = None
        raw["_end_not_used"] = iso(stop)
        if status == "ended":
            status = "unknown"

    # received time: the live layer's, kept once seen
    p_raw = (prev or {}).get("raw") or {}
    received = live_time((live or {}).get("received_date")) if live else None
    live_ver = str((live or {}).get("sso_report_version") or "").strip()
    reported_at = (prev or {}).get("reported_at")
    if received and live_ver == "1":
        reported_at = reported_at or iso(received)
        raw["_received_basis"] = ("received_date on ADEM's live SSO map layer while the report was at version 1 "
                                  "(ADEM's receipt of the first filing)")
    elif received:
        raw["_received_latest_version"] = {"version": live_ver or None, "received": iso(received),
                                           "basis": "received_date on ADEM's live layer: the receipt of this version, "
                                                    "not of the first filing"}
    if reported_at and "_received_basis" not in raw:
        raw["_received_basis"] = p_raw.get("_received_basis")

    lat, lon = fnum(a.get("lat")), fnum(a.get("long"))
    if (lat is None or lon is None) and live:
        lat, lon = fnum(live.get("lattitude_decimal")), fnum(live.get("longitude_decimal"))
    if lat is not None and not in_al(lat, lon):
        raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in Alabama's box"}
        lat = lon = None

    w_text = clean_text((live or {}).get("receiving_stream")) or clean_text(a.get("rec_stream"))
    rw = receiving(w_text)
    raw["receiving_water_text"] = w_text
    raw["receiving_water_parts"] = rw["parts"]
    raw["reached_water"] = rw["reached_water"]
    raw["_reached_water_basis"] = rw["why"]
    if rw["reached_water"] is False:
        raw["_no_water_reason"] = rw["why"]

    dup_of = None
    words = " ".join(x for x in [w_text, clean_text((live or {}).get("cause_of_discharge"))] if x)
    if DUPLICATE.search(words or ""):
        raw["_report_note"] = ("the report's words say it duplicates another report or was not a sewer overflow: "
                               "kept on the record")
        for m in REPORT_ID.finditer(words):
            other = f"SSO-{int(m.group(1)):08d}"
            if other != base["source_record_id"] and other in known_ids:
                dup_of = f"{SOURCE_ID}:{other}"
                break
        if not rw["names"] and rw["reached_water"] is not True:
            raw["reached_water"] = False
            raw["_no_water_reason"] = "the report says it duplicates another report or was not a sewer overflow"

    gal, vtext, vbasis = volume_text(a.get("est_volume"), (live or {}).get("est_volume"))
    raw["_volume_basis"] = vbasis
    permit = str(a.get("permit_no") or (live or {}).get("permit_no") or "").strip().upper() or None
    did, _ = ops.get(permit or "", (None, None))
    raw["efile_url"] = EFILE.format(permit=permit) if permit else None
    raw["report_version"] = a.get("sso_report_version")
    if live and live.get("report_type"):
        raw["report_type"] = live.get("report_type")

    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or base["fetched_at"]
    seen = list(p_raw.get("_versions_seen") or [])
    ver = a.get("sso_report_version")
    if not seen or seen[-1].get("version") != ver:
        seen.append({"version": ver, "first_seen_at": base["fetched_at"]})
    raw["_versions_seen"] = seen

    rec = event(
        **base, event_type="sso", status=status,
        discharger_id=did, discharger_name=(a.get("permittee") or (live or {}).get("permittee") or None),
        npdes_permit=permit, outfall_id=None,
        outfall_name=clean_text(a.get("LOCATION_OF_DISCHARGE")) or clean_text((live or {}).get("location_of_discharge")),
        waterbody_text="; ".join(rw["names"]) or None, water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=None,
        started_at=iso(start), ended_at=ended, time_precision="minute" if start else None,
        reported_at=reported_at, published_at=None, source_updated_at=None,
        material="untreated sewage", volume_gal=gal, volume_text=vtext,
        estimate_flag="estimated" if (gal is not None or vtext) else "unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None, duplicate_of=dup_of,
    )
    if rec["discharger_name"] == NAME_REMOVED:      # a permittee that reads as a person's name: out of raw too
        for part in (rec["raw"].get("row") or {}, rec["raw"].get("live") or {}):
            if part.get("permittee"):
                part["permittee"] = NAME_REMOVED
    return rec


def build(hist_rows: list[dict], live_rows: list[dict], fetched_at: str, prev_records: list[dict], full: bool,
          ops: dict | None = None) -> tuple[list[dict], dict]:
    ops = permit_index() if ops is None else ops
    prev = {r["event_id"]: r for r in prev_records}
    live = {report_id(r.get("sso_report_id")): r for r in live_rows if report_id(r.get("sso_report_id"))}
    rows = {}
    for a in hist_rows:
        rid = report_id(a.get("sso_report_id"))
        if rid:
            rows[rid] = a
    for rid, lv in live.items():                 # on the live layer only: built from its own fields
        if rid not in rows:
            rows[rid] = {"sso_report_id": rid, "sso_report_version": lv.get("sso_report_version"),
                         "permit_no": lv.get("permit_no"), "permittee": lv.get("permittee"),
                         "facility_site_name": lv.get("facility_site"), "sso_ongoing_ind": lv.get("sso_ongoing_ind"),
                         "LOCATION_OF_DISCHARGE": lv.get("location_of_discharge")}
    known = set(rows) | {r["source_record_id"] for r in prev_records}
    records, seen = [], set()
    for rid, a in rows.items():
        eid = f"{SOURCE_ID}:{rid}"
        seen.add(eid)
        records.append(to_record(a, live.get(rid), fetched_at, prev.get(eid), ops, known))
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        if full:
            r.setdefault("raw", {})
            r["raw"]["_missing_from_layer_since"] = r["raw"].get("_missing_from_layer_since") or fetched_at
        records.append(r)
        kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"read_reports": len(rows), "live_rows": len(live), "kept_from_earlier_runs": kept, "full_read": full,
             "by_status": dict(Counter(r["status"] for r in records)),
             "reached_water": dict(Counter(str((r.get("raw") or {}).get("reached_water")) for r in records)),
             "with_water_name": sum(1 for r in records if r.get("waterbody_text")),
             "with_operator": sum(1 for r in records if r.get("discharger_id")),
             "duplicates": sum(1 for r in records if r.get("duplicate_of"))}
    return records, stats


# ---------------------------------------------------------------- fetching
def _query(sess, layer: str, params: dict) -> dict:
    r = sess.get(f"{layer}/query", params={"returnGeometry": "false", "f": "json", **params}, timeout=(20, 300))
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"ArcGIS error: {d['error']}")
    if d.get("exceededTransferLimit"):
        raise RuntimeError("the layer cut the answer short (exceededTransferLimit): page it smaller")
    return d


def fetch_history(sess, full: bool, now: datetime) -> list[dict]:
    pages = []
    if full:
        top = int(_query(sess, HISTORY, {"where": "1=1", "returnCountOnly": "true"}).get("count") or 0)
        lo = 0
        while True:
            d = _query(sess, HISTORY, {"where": f"object_id > {lo} AND object_id <= {lo + PAGE}",
                                       "outFields": ",".join(FIELDS), "orderByFields": "object_id"})
            pages.append(d)
            lo += PAGE
            got = sum(len(p.get("features") or []) for p in pages)
            if not d.get("features") and got >= top:
                break
            if lo > 10 * max(top, 1) + PAGE:
                raise RuntimeError("object_id ranges ran past ten times the layer's count")
    else:
        since = (now.astimezone(TZ) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        pages.append(_query(sess, HISTORY, {"where": f"date_sso_began >= DATE '{since}' OR sso_ongoing_ind = 'Yes'",
                                            "outFields": ",".join(FIELDS), "orderByFields": "object_id"}))
    return pages


def rows_of(doc: dict) -> list[dict]:
    pages = doc.get("pages") or [doc]
    return [f.get("attributes") or {} for p in pages for f in p.get("features") or []]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--full", action="store_true", help="read the whole history layer")
    ap.add_argument("--file", help="a saved history response ({'pages': [...]} or one query answer); a full read")
    ap.add_argument("--live", help="a saved live-layer response (with --file)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_doc.get("records") or []
    try:
        if args.file:
            hist = rows_of(json.loads(Path(args.file).read_text()))
            live = rows_of(json.loads(Path(args.live).read_text())) if args.live else []
            full = True
        else:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            last_full = state.get("last_full_at")
            full = args.full or not prev or not last_full or (
                datetime.now(UTC) - datetime.fromisoformat(last_full.replace("Z", "+00:00"))
                > timedelta(hours=FULL_EVERY_HOURS))
            pages = fetch_history(sess, full, datetime.now(UTC))
            live_doc = _query(sess, LIVE, {"where": "1=1", "outFields": ",".join(LIVE_FIELDS)})
            hist, live = rows_of({"pages": pages}), rows_of(live_doc)
            save_raw(SOURCE_ID, json.dumps({"layer": HISTORY, "full": full, "pages": pages, "live": live_doc}), "json")
        if full:
            last = (prev_doc.get("meta") or {}).get("last_full_reports")
            if not hist or (isinstance(last, int) and len(hist) < last * MIN_RATIO):
                raise RuntimeError(f"{len(hist)} reports in a full read (the last good one had {last})")
    except (requests.RequestException, RuntimeError, ValueError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    records, stats = build(hist, live, fetched_at, prev, full)
    records = redact.redact_events(records)
    meta = {**stats, "layers": [HISTORY, LIVE], "map": MAP_URL, "time_basis": TIME_BASIS,
            "last_full_reports": len(hist) if full else (prev_doc.get("meta") or {}).get("last_full_reports"),
            "credit": "Alabama Department of Environmental Management, SSO reports (AEPACS) on ADEM's ArcGIS server",
            "registry_ids": ["al-adem-sso-history", "al-adem-sso-map-live"],
            "cadence": f"hourly: the last {LOOKBACK_DAYS} days and ongoing reports; the whole layer every "
                       f"{FULL_EVERY_HOURS} hours"}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    if full and not args.file:
        state["last_full_at"] = fetched_at
    state["fetched_at"] = fetched_at
    if not args.file:
        write_json(STATE_FILE, state)
    print(f"{SOURCE_ID}: {stats['read_reports']} reports read ({'full' if full else 'recent'}), "
          f"{stats['kept_from_earlier_runs']} kept; status {stats['by_status']}; reached water {stats['reached_water']}"
          f" -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
