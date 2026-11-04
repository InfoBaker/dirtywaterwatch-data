"""Michigan EGLE MiEnviro "CSO/SSO List" -> data/build/events/mi-egle-mienviro-cso-sso-list.json

Source
  Michigan Department of Environment, Great Lakes, and Energy (EGLE), Water Resources Division: the public list
  "CSO and SSO Information in MiEnviro" (https://mienviro.michigan.gov/ncore/external/overflow/list, linked from
  Michigan.gov/SewageDischarge). The page reads an unauthenticated JSON service,
  GET https://mienviro.michigan.gov/ncore/ss/ssolist?queryParams=<JSON {"filter":[{...}],"top":n}>
  &includeMetadataInResponse=false&responseFields=<comma list> (the parameters the page's own CSV download sends).
  Filters used: reportStatusId (IN_PROCESS, COMPLETE), eventStartDateMin / eventStartDateMax (dates; the maximum is
  exclusive), submissionId. An unfiltered query times out, so every request is filtered. No key, no cookie, no
  documentation and no licence statement (michigan.gov footer: "Copyright State of Michigan"). Credit "Michigan EGLE,
  MiEnviro CSO/SSO List".
  Law: MCL 324.3112a(1): the person responsible for a sewer system that discharges untreated or partially treated
  sewage must notify EGLE, the local health departments and a daily newspaper "immediately, but not more than 24
  hours after the discharge begins", and report volume, quality, cause, the waters or land receiving it and the times
  it began and ended at its conclusion; (2): EGLE "shall promptly post the notification on its website" (this list).
  Great Lakes CSO permittees give their 4-hour notice under 40 CFR 122.38 through the same list (GLWA's plan).

What is requested (privacy)
  Only these fields are requested (responseFields) and kept: submissionId, submissionReferenceNumber, sectionNumber,
  submissionReceivedDate, responsiblePartyName, siteName, permitNumber, countyDescription, countyId, reportStatusId,
  reportStatusDescription, dischargeType, dischargeQuality, dischargeVolume, dischargeVolumeNumeric, eventStartDate,
  eventEndDate, featureNumber, featureDescription, receivingWater, landImpacted, precipitationAmount, precipitationType.
  Never requested: the narrative fields locationDescription, dischargeDescription, actionTaken, actionToBeTaken,
  deqActions, agencyComments and socRequirements (written by operators and EGLE staff, they can name the people they
  dealt with and residents' addresses; raw._withheld says so and the source record has them), and `id`, which the
  service renumbers on every response (it is not an id).
  responsiblePartyName and siteName are typed by the filer: a value that is only a person's name becomes
  "[name removed]", and a person's name in brackets after a body ("City of X (<name>)") is cut (party_name()); when
  the responsible party is a person, the site name goes too unless it names a works or a place (a lagoon, a park).
  landImpacted (the land the sewage reached), featureDescription, a featureNumber that is not an outfall number and the
  free-text discharge type lose every house number (an address's, and a number before a name or a state highway, or
  after "at": the land can be a home's driveway or yard; free_text()) and the name of a person given as the land's
  owner or resident ("property owned by <given> <surname>"; a body such as a township stays: cut_owner_names()).
  Every string then passes common.strip_personal (in event()) and build.redact runs over the records last.
  tests/test_ingest_mi.py proves that the withheld fields and the placeholder names never reach a record or the
  saved raw page.

Which reports become records
  dischargeType and dischargeQuality hold comma lists, often doubled ("CSO Discharge,CSO Discharge"); the "Other
  Discharge" choice adds the filer's own words. classify():
  - "CSO Discharge" -> cso; "RTB Discharge" (a retention treatment basin: combined sewage given partial treatment
    before it overflows) -> cso, raw._discharge_kind "RTB"; "SSO Discharge" -> sso.
  - "Other Discharge": a quality of RTB -> cso (RTB); raw or diluted raw sewage -> bypass when the words place it at
    a treatment plant (plant, WWTP, WRRF, lagoon, headworks, influent ...), else sso; partially treated -> plant_bypass;
    blended -> blended.
  - Left out, counted (meta.left_out, cumulative in data/build/mi-egle-mienviro-state.json): an "Other" report whose
    words name only fuel, oil, paint or chemicals and no sewage word (other pollution), and one whose words name only
    biosolids or sludge and names no receiving water (the scope rule applied to Florida on 2026-11-04: biosolids are
    counted, not shown; a spill that reached a named water stays a record). Activated sludge (return or waste
    activated sludge, mixed liquor) is partially treated sewage under MCL 324.3112a(9), not biosolids: a record.
  - No type and no quality: event_type unknown with a parse_error (kept for review).

Record rules
  - Key: submissionId and sectionNumber (one submission holds a section per outfall or location; checked unique over
    every report of 2013-2026). source_record_id "<submissionId>-<sectionNumber>"; source_url is the list service
    filtered to that submission.
  - Times carry EGLE's offsets (-04:00 / -05:00) and are kept as given, time_precision "minute". A start more than a
    day after the read (one report starts in 3021) is not used (raw._start_not_used). reported_at is
    submissionReceivedDate (EGLE's receipt). published_at is null: the list gives no posting time (it shows a report
    as soon as it is submitted). source_updated_at is null. raw._first_seen_at is our clock.
  - Status. A report EGLE lists as completed (COMPLETE) with an end -> ended at that end. A completed report whose end
    repeats its start to the minute -> ended with no end (raw._end_equals_start, raw._end_not_used): the form fills
    the start in as the end until the report is completed and 107 completed reports since 2025 kept it, 98 of them
    with a volume, so the end is not confirmed; the status build then gives the site's caution from the report time
    and "end not confirmed" to day 30. A report in process (IN_PROCESS, the first notice, until it
    is completed) whose end equals its start, or has none, -> ongoing with no end: the form repeats the start as the
    end until the report is completed (151 of 334 open reports on 2026-11-04), so it is never read as an end; the
    status build gives an ongoing report 7 days of red, then "end not confirmed" to day 30. An in-process report with
    a later end -> ended at that end (the operator's own; raw._end_basis says the report is not yet completed). An end
    before the start is not used (raw._end_not_used).
  - Revisions: a report that moves from in process to completed keeps its event id; the fields it had before are kept
    in raw._revisions (when they changed and what they were).
  - Water: receivingWater as typed is waterbody_text. reached_water: true when a water is named; false when a
    completed report names no water but names the land it reached (landImpacted); else null (an open report often
    names neither yet). water_slugs stay empty (the status build places by permit and outfall, name and town).
  - Operator: permitNumber as typed ("MI 0022802", "MI0023582 V4.1", "3112a-0707", "GW1810021", "MIG570128", "N/A")
    is read to one permit (norm_permit; the typed value is raw._permit_as_given). discharger_id from data/dischargers.json
    by that permit (a Michigan row holding it), else, for a report that gives no permit, by EGLE's responsible party
    name when it is one of NAME_OPERATORS (GLWA files its first notices with no permit); never inferred otherwise
    (raw._discharger_basis says why). discharger_name is the responsible party as EGLE lists it.
  - Outfall: featureNumber is outfall_id when it reads as an outfall number ("002", "R03", "013b"; an "Outfall 003"
    prefix dropped); otherwise it is text (a drain, a valve) and goes to outfall_name with featureDescription.
  - Volume: dischargeVolumeNumeric is in gallons ("6.50000 Million Gallons" -> 6,500,000); volume_text is the list's
    own wording; estimate_flag unknown (the list does not say).
  - Copies: two submissions of one report (the same permit or party, outfall, start minute and volume; seen when an
    operator files again) keep the one EGLE received last; the other is duplicate_of it (link_copies; recomputed
    every run). Sections of one submission are never copies of each other.
  - No coordinates in the list. A point comes from the outfall registry (permit and outfall) in the status build.

Reading
  Each run reads every IN_PROCESS report (about 330) and every COMPLETE report whose start lies in the last 60 days,
  then asks by submissionId for up to LOOKUP_MAX reports read as in process before that are in neither answer (one
  completed after a start more than 60 days back; within LOOKUP_BUDGET_S seconds, and none after a timeout, so a slow
  service cannot hold the hourly run); a submission the service no longer lists keeps its record with
  raw._missing_from_list_since. An answer of no open reports at all is an outage (ok false, the records kept).
  Records kept from earlier runs are rebuilt from their raw fields under the current rules.

History (`--backfill [--from YEAR] [--refetch]`; never in the scheduled hourly run)
  By hand, or once in a dispatched refresh with the backfill input "mi_egle_mienviro" (.github/workflows/refresh.yml
  runs --backfill before the refresh; the state is saved to R2 only when the whole run succeeds). Reads every COMPLETE
  report a year at a time from YEAR (default 2001, the owner's call; the list also holds 1999 and 2000, --from 1999),
  plus the starts typed after next year (and, from 1999, before 1999: typing errors, kept as reports), about one
  request every 35 to 40 seconds (the service's own pace; 1.5 to 2.6 MB a year uncompressed). Each year's rows are
  saved as they arrive (scrubbed as the raw page is) to data/build/archive/mi-egle-mienviro-cso-sso-list/<year>.json,
  so a run cut short keeps what it read. A year already in the archive is not asked for again, except this year and
  the last (reports are completed months after they start), unless --refetch. After BACKFILL_BUDGET_S the remaining
  years are not requested and are named in meta.lookup_errors ("run --backfill again"). An HTTP 4xx answer (other
  than 429) means the service no longer answers this query: the backfill stops and says so. A timeout, a dropped
  connection, a 5xx or 429, or an answer that is not the list's JSON is transient: that year is named, not saved,
  asked for again by the next --backfill, and the next year is tried (after BACKFILL_MAX_FAILURES in a row the
  backfill stops for this run). Every archived year is applied with the current rows, so a backfill is also a
  rebuild of the history. meta.backfill gives the range asked, the years read, from the archive, failed and not
  requested, the rows per year and the records per start year; every later hourly run carries it unchanged.

Cadence: hourly (start to submission: median 20.7 hours in the open reports of 2026-11-03).
Run from pipeline/:  python -m ingest.mi_egle_mienviro [--file saved.json] [--backfill [--from YEAR] [--refetch]]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import string
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, HOUSE_NUMBER_REMOVED, NAME_REMOVED, OPERATOR_WORDS, ROOT,
                    event, now_iso,
                    path_notes_to_meta, read_json, save_raw, scrub_text, strip_house_numbers, write_events, write_json)

SOURCE_ID = "mi-egle-mienviro-cso-sso-list"
BASE = "https://mienviro.michigan.gov/ncore"
LIST_URL = f"{BASE}/ss/ssolist"
PAGE_URL = f"{BASE}/external/overflow/list"
STATE_FILE = BUILD_DIR / "mi-egle-mienviro-state.json"
AUTHORITY = "Michigan EGLE (MiEnviro CSO/SSO List)"
CREDIT = "Michigan Department of Environment, Great Lakes, and Energy, MiEnviro CSO/SSO List"
FIELDS = ["submissionId", "submissionReferenceNumber", "sectionNumber", "submissionReceivedDate", "responsiblePartyName",
          "siteName", "permitNumber", "countyDescription", "countyId", "reportStatusId", "reportStatusDescription",
          "dischargeType", "dischargeQuality", "dischargeVolume", "dischargeVolumeNumeric", "eventStartDate",
          "eventEndDate", "featureNumber", "featureDescription", "receivingWater", "landImpacted",
          "precipitationAmount", "precipitationType"]
WITHHELD = ("id", "locationDescription", "dischargeDescription", "actionTaken", "actionToBeTaken", "deqActions",
            "agencyComments", "socRequirements")
WITHHELD_NOTE = ("The list's narrative fields (location description, discharge description, actions taken and to be "
                 "taken, EGLE's actions and comments) are not reproduced here: they can name the people involved and "
                 "residents' addresses. The source record has them.")
COMPLETE_DAYS = 60
LOOKUP_MAX = 40
LOOKUP_BUDGET_S = 180          # the lookups of one hourly run stop after this; a timeout stops them at once
LOOKUP_READ_TIMEOUT_S = 60
clock = time.monotonic
TOP = 5000
BACKFILL_FROM = 2001            # the owner's call of 2026-11-04 (history from 2001); --from 1999 reads the rest
LIST_FIRST_YEAR = 1999          # the list's first full year as served on 2026-11-04 (1,572 reports of 1999, 2,371
                                # of 2000; before 1999 only a few starts typed in error, 1919, 1960 ...)
BACKFILL_BUDGET_S = 40 * 60     # a backfill stops asking for more years after this, so the dispatched refresh (a
                                # 100-minute job: backfill, then the 20 to 40 minute refresh) ends in time; rerun it
BACKFILL_PAUSE_S = 2.0          # between two years' requests (each takes the service 30 to 40 s to answer)
BACKFILL_READ_TIMEOUT_S = 300
BACKFILL_MAX_FAILURES = 3       # transient failures in a row that stop the backfill for this run
BACKFILL_REREAD_YEARS = 2       # this year and the last are read again by every backfill (reports complete late)
ARCHIVE_DIR = BUILD_DIR / "archive" / SOURCE_ID
MI_TZ_NOTE = "Times as EGLE's list gives them, with their UTC offsets."

# a report that gives no permit is joined to an operator by EGLE's responsible-party name only for these names
# (normalised: lower case, single spaces); GLWA files its first CSO notices with no permit number
NAME_OPERATORS = {
    "glwa": "mi-glwa-wrrf-mi0022802",
    "great lakes water authority": "mi-glwa-wrrf-mi0022802",
}

PERMIT_PATTERNS = [
    (re.compile(r"MI\s*-?\s*([0GSU]\d{6})(?!\d)", re.I), lambda m: "MI" + m.group(1).upper()),
    (re.compile(r"\b3112\s*A\s*-\s*(\d{3,4})(?!\d)", re.I), lambda m: f"3112a-{int(m.group(1)):04d}"),
    (re.compile(r"\bGW\s*(\d{7})\b", re.I), lambda m: "GW" + m.group(1)),
]
OUTFALL_NO = re.compile(r"^(?:(?:outfall|of|cso|rtb)\s*#?\s*)?([A-Z]{0,3}-?\d{1,4}[A-Z]?)$", re.I)

CSO_TYPES = {"cso discharge"}
RTB_TYPES = {"rtb discharge"}
SSO_TYPES = {"sso discharge"}
GENERIC_TYPES = CSO_TYPES | RTB_TYPES | SSO_TYPES | {"other discharge"}
NOT_SEWAGE = re.compile(r"\b(motor oil|oil|diesel|fuel|gasoline|paint|hydraulic|antifreeze|chemicals?|illicit)\b", re.I)
BIOSOLIDS = re.compile(r"\b(biosolids?|sludge|cake)\b", re.I)
SEWAGE_WORDS = re.compile(
    r"sewage|sanitary|\braw\b|influent|wastewater|waste water|overflow|by-?pass|lagoon|wwsl|effluent|mixed liq|"
    r"\bras\b|\bwas\b|filtrate|primary|secondary|\bcso\b|\bsso\b|\brtb\b|grit|digester|clarifier|oxidation ditch|"
    r"septage|septic|drain ?field|force main|lift station|pump station|manhole|partial|untreated|diluted|blended|"
    r"activated|mixed liquor",
    re.I)
PLANT_WORDS = re.compile(r"\b(plant|wwtp|wwtf|wrrf|wrf|potw|treatment|lagoons?|wwsl|headworks|influent|grit|digester|"
                         r"clarifier|reactor|aeration|basin|tank|facility|oxidation ditch|filtration|filters?)\b", re.I)
WATER_NONE = re.compile(r"^\s*(n/?a|none|no|nothing|unknown|tbd|-+|\.+|0)\s*\.?\s*$", re.I)
# a person's name in brackets after a body: "Dearborn Heights (<name>)"
BRACKETED = re.compile(r"\s*\(([^()]{3,40})\)")
SITE_WORDS = {"cm", "cs", "ls", "ps", "lagoon", "lagoons", "collection", "main", "interceptor", "drain", "basin",
              "rtb", "rtf", "outfall", "estates", "park", "village", "mhc", "condo", "condominium", "communities",
              "community", "heights", "lake", "lakes", "river", "creek", "bay", "harbor", "point", "springs", "hills"}


# ---------------------------------------------------------------- helpers

def clean(v) -> str:
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def parts(v) -> list[str]:
    """'CSO Discharge,CSO Discharge' -> ['CSO Discharge'] (order kept, repeats and blanks dropped)."""
    out = []
    for p in str(v or "").split(","):
        p = clean(p)
        if p and p.lower() not in {q.lower() for q in out}:
            out.append(p)
    return out


TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def parse_ts(v) -> datetime | None:
    """'2026-10-27T10:45:00.0000000-04:00' -> aware datetime (EGLE's offset kept); a value with no offset is read in
    Michigan's Eastern time."""
    s = clean(v)
    m = TS.match(s)
    if not m:
        return None
    d, t, off = m.groups()
    if len(t) == 5:
        t += ":00"
    try:
        if off is None:
            from zoneinfo import ZoneInfo
            return datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=ZoneInfo("America/Detroit"))
        off = "+00:00" if off == "Z" else (off if ":" in off else off[:3] + ":" + off[3:])
        return datetime.fromisoformat(f"{d}T{t}{off}")
    except ValueError:
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def norm_permit(v) -> str | None:
    """The permit a typed permitNumber names: an NPDES permit (MI0022802, MIG570128, MIS...), a Part 31 sewer-system
    number (3112a-0707) or a groundwater permit (GW1810021); None for "N/A", "Various" and the like."""
    s = clean(v)
    if not s:
        return None
    for rx, fmt in PERMIT_PATTERNS:
        m = rx.search(s)
        if m:
            return fmt(m)
    return None


def _person(s: str) -> bool:
    from build import redact
    words = {w.lower() for w in re.split(r"[\s\-/.,()&']+", s) if w}
    if words & (OPERATOR_WORDS | SITE_WORDS):
        return False
    return bool(redact.person_shaped(s) or redact.person_shaped(string.capwords(s)))


def _site_words(s: str) -> bool:
    return bool({w.lower() for w in re.split(r"[\s\-/.,()&']+", s) if w} & (OPERATOR_WORDS | SITE_WORDS))


NAME_WORD = re.compile(r"^(?:[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*|[A-Z]\.?)$")


def _bracketed_person(s: str) -> bool:
    """Words in brackets after a body that read as a person's name: two or three capitalised words (an initial
    allowed) with no works, place or site word ("City of X (<given> <surname>)"); an acronym or a works stays."""
    words = s.split()
    return (2 <= len(words) <= 3 and all(NAME_WORD.match(w) for w in words) and not _site_words(s)) or _person(s)


ROLE = re.compile(r"^(owner|manager|operator|superintendent|director|supervisor|president|agent|contact)$", re.I)
SEGMENT_SEP = re.compile(r"\s+[-\u2013\u2014/]\s+|\s*,\s*")


def party_name(v) -> str | None:
    """A filer-typed body name with no person in it: a value that is only a person's name becomes "[name removed]";
    a person's name in brackets after the body is cut, and so is one joined to it by a dash or a comma ("<body> -
    <given> <surname>", "<given> <surname> - <body>", "<given> <surname>, Owner")."""
    s = clean(v)
    if not s:
        return None
    s = BRACKETED.sub(lambda m: "" if _bracketed_person(clean(m.group(1))) else m.group(0), s).strip()
    if _person(s):
        return NAME_REMOVED
    segs = SEGMENT_SEP.split(s)
    if len(segs) > 1:
        seps = SEGMENT_SEP.findall(s)
        role = any(ROLE.match(x) for x in segs)
        drop = {i for i, x in enumerate(segs)
                if _person(x) or ROLE.match(x) or (role and _bracketed_person(x))}
        if drop:
            kept = [i for i in range(len(segs)) if i not in drop]
            if not kept:
                return NAME_REMOVED
            out = segs[kept[0]]
            for i in kept[1:]:
                out += seps[i - 1] + segs[i]
            s = out.strip(" ,-")
    return scrub_text(s) or None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def classify(types: list[str], quality: list[str], water_named: bool = False) -> tuple[str | None, str | None, str]:
    """(event_type or None when left out, left-out kind or None, the discharge kind as EGLE's list words it).
    water_named: the report names a receiving water (a biosolids or sludge spill that reached one stays a record)."""
    low = {t.lower() for t in types}
    qlow = {q.lower() for q in quality}
    if low & CSO_TYPES:
        return "cso", None, "CSO"
    if low & RTB_TYPES:
        return "cso", None, "RTB"
    if low & SSO_TYPES:
        return "sso", None, "SSO"
    words = " ".join(t for t in types if t.lower() not in GENERIC_TYPES)
    if words:
        sewage = SEWAGE_WORDS.search(words)
        if NOT_SEWAGE.search(words) and not sewage:
            return None, "other pollution", "Other"
        rest = BIOSOLIDS.sub(" ", words)
        if BIOSOLIDS.search(words) and not SEWAGE_WORDS.search(rest) and not water_named:
            return None, "biosolids", "Other"
    if not types and not quality:
        return "unknown", None, "not stated"
    if "rtb" in qlow:
        return "cso", None, "RTB"
    if qlow & {"raw sewage", "diluted raw sewage"}:
        return ("bypass" if PLANT_WORDS.search(words) else "sso"), None, "Other"
    if "partially treated" in qlow:
        return "plant_bypass", None, "Other"
    if "blended sewage" in qlow:
        return "blended", None, "Other"
    if types:
        return "sso", None, "Other"
    return "unknown", None, "not stated"


def outfall_fields(number, description) -> tuple[str | None, str | None]:
    """(outfall_id, outfall_name): featureNumber when it reads as an outfall number, the text otherwise."""
    num, desc = clean(number), clean(description)
    m = OUTFALL_NO.match(num) if num else None
    if m:
        return m.group(1), desc or None
    names = [x for x in (num, desc) if x]
    return None, " - ".join(dict.fromkeys(names)) or None


def permit_index(rows: list[dict] | None = None) -> dict[str, str]:
    """permit -> data/dischargers.json id, for Michigan rows (a permit two rows hold maps to neither)."""
    if rows is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
    seen: dict[str, set[str]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("state") != "MI":
            continue
        for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
            if p:
                k = norm_permit(p) or str(p).strip()
                seen.setdefault(k.upper(), set()).add(r["id"])
    return {p: next(iter(v)) for p, v in seen.items() if len(v) == 1}


def row_key(r: dict) -> str | None:
    sid, sec = clean(r.get("submissionId")), clean(r.get("sectionNumber"))
    return f"{sid}-{sec}" if sid and sec else None


def safe_row(r: dict) -> dict:
    """Only the requested fields (a service that ignored responseFields keeps no others)."""
    return {k: r.get(k) for k in FIELDS if k in r}


# a person named as the owner or resident of the land the sewage reached ("property owned by <given> <surname> at
# ...", "the yard of Mr. <surname>"): the name is cut unless it names a body (a township, a company)
OWNER_CUE = re.compile(
    r"(?i:\b(owned\s+by|property\s+of|home\s+of|house\s+of|residence\s+of|yard\s+of|lot\s+of|land\s+of|farm\s+of|"
    r"field\s+of|parcel\s+of|driveway\s+of|basement\s+of|homeowners?|residents?|neighbou?rs?|tenants?)[ ]{1,2})"
    r"((?:(?:Mr|Mrs|Ms|Miss|Dr)\.?[ ]{1,2})?[A-Z][\w'.-]*(?:[ ]{1,2}(?:&|and)?[ ]{0,2}[A-Z][\w'.-]*){0,3})")
# a house number in the free text: a number of two to six digits before a capitalised word or a state highway
# ("Driveway of <number> <name> Lake", "between residences <number> <street> and ...", "yard at <number> M-28"),
# or after "at" ("Ditch at <number> traveling east"); not a quantity ("40 Feet", "23 Mile Road"), a time, or a number
# a route, lot, station, outfall or drain word stands before ("Lot 187", "Drain #264", "Station 23")
ADDR_NUMBER = re.compile(
    r"(?<![\w.,/:#$-])(?!0)(\d{2,6})(?=[ ]{1,2}(?:[NSEW]\.?[ ]{1,2})?(?:[A-Z][A-Za-z']+\b|M-\d|US[ -]?\d))")
AT_NUMBER = re.compile(r"(?i:\b(?:at|near|behind|of)[ ]{1,2})(?!0)(\d{3,6})(?=[ ]{1,2}[a-z]|[ ]{0,2}[,.;)]|$)")
QUANTITY_AFTER = re.compile(
    r"[ ]{1,2}(?i:feet|foot|ft|gallons?|gal|yards?|yds?|square|sq|acres?|hours?|hrs?|minutes?|mins?|inch(?:es)?|"
    r"percent|mg|gpm|mgd|million|thousand|miles?|mile|lbs?|pounds?|cubic|cu|linear|lf|am|pm|block)\b")
NUMBER_WORD_BEFORE = re.compile(
    r"(?i:\b(?:US|SR|CR|M|I|Hwy|Highway|Route|Rte|Interstate|Exit|Mile|Marker|MM|Lot|Unit|Site|Sites|Suite|Ste|Apt|"
    r"Bldg|Building|Station|LS|PS|No|Number|Outfall|CSO|SSO|RTB|Manhole|MH|Basin|Structure|Drain|Pump|Pumps|Tank|"
    r"Cell|Lagoon|Gate|Door|Bay|Section|Phase|Zone|Room|Line|Feature|Permit|Year|January|February|March|April|May|"
    r"June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?)"
    r"[ #.-]{0,3}$")


# a person's name as the owner of the land, in the possessive: "<given> <surname>'s back yard" (a 2019 report types
# the apostrophe as a backtick); two or three capitalised words, or one after Mr / Mrs / Ms / Dr
OWNER_POSSESSIVE = re.compile(
    r"((?:(?:Mr|Mrs|Ms|Miss|Dr)\.?[ ]{1,2}[A-Z][\w.-]*)|(?:[A-Z][\w.-]*(?:[ ]{1,2}[A-Z][\w.-]*){1,2}))"
    r"(?:'|`|\u2019)s(?=[ ]{1,2}(?:(?:back|front|side|rear)[ ]{1,2})?(?i:yard|home|house|property|residence|"
    r"driveway|basement|lawn|lot|farm|field|garage|land|cottage|cabin)\b)")


def cut_owner_names(v: str) -> str:
    """'property owned by <given> <surname> at ...' -> 'property owned by [name removed] at ...', and
    "<given> <surname>'s back yard" -> "[name removed]'s back yard" (a body stays)."""
    def body(name):
        return _site_words(name) or re.search(r"(?i)\b(llc|inc|corp|company|co|ltd|lp)\b", name)

    def one(m):
        name = m.group(2)
        if body(name):
            return m.group(0)
        return m.group(0)[:m.start(2) - m.start(0)] + NAME_REMOVED

    def poss(m):
        return m.group(0) if body(m.group(1)) else NAME_REMOVED + m.group(0)[len(m.group(1)):]
    return OWNER_POSSESSIVE.sub(poss, OWNER_CUE.sub(one, v))


def cut_address_numbers(v: str) -> str:
    """Every number that reads as a house number in free text (ADDR_NUMBER, AT_NUMBER) -> [house number removed]."""
    def one(m):
        before, after = v[max(0, m.start(1) - 16):m.start(1)], v[m.end(1):m.end(1) + 16]
        if NUMBER_WORD_BEFORE.search(before) or QUANTITY_AFTER.match(after):
            return m.group(0)
        return m.group(0)[:m.start(1) - m.start(0)] + HOUSE_NUMBER_REMOVED + m.group(0)[m.end(1) - m.start(0):]
    v = ADDR_NUMBER.sub(one, v)
    return AT_NUMBER.sub(one, v)


def free_text(v: str) -> str:
    """A filer's free text as the record keeps it: emails, phones and staff names (scrub_text), owners' and residents'
    names, and house numbers cut."""
    return cut_address_numbers(strip_house_numbers(cut_owner_names(scrub_text(clean(v)))))


def scrubbed_row(r: dict) -> dict:
    """The fields as the record keeps them: names checked, house numbers cut (see the docstring)."""
    out = safe_row(r)
    for k in ("responsiblePartyName", "siteName"):
        if out.get(k) is not None:
            out[k] = party_name(out[k])
    # a person filed as the responsible party: the site is named for them too unless it names a works or a place
    if out.get("responsiblePartyName") == NAME_REMOVED and out.get("siteName") and not _site_words(out["siteName"]):
        out["siteName"] = NAME_REMOVED
    if out.get("landImpacted"):
        land = re.sub(r"(?i)(\baddress(?:\s+of)?:?\s*)\d{1,6}[A-Za-z]?\b", r"\1[house number removed]",
                      clean(out["landImpacted"]))
        out["landImpacted"] = free_text(land)
    for k in ("featureDescription", "dischargeType"):
        if isinstance(out.get(k), str):
            out[k] = free_text(out[k])
    # an outfall number stays as typed ("002", "Outfall 003"); any other feature text is free text
    if isinstance(out.get("featureNumber"), str):
        fn = scrub_text(out["featureNumber"])
        out["featureNumber"] = fn if OUTFALL_NO.match(clean(fn)) else free_text(fn)
    for k in ("receivingWater", "dischargeQuality"):
        if isinstance(out.get(k), str):
            out[k] = cut_owner_names(scrub_text(out[k]))
    return out


# ---------------------------------------------------------------- records

TRACKED = ("reportStatusId", "eventStartDate", "eventEndDate", "dischargeVolume", "receivingWater", "featureNumber",
           "dischargeType", "dischargeQuality", "permitNumber")


def build_record(row: dict, fetched_at: str, prev: dict | None, permits: dict[str, str]) -> dict | tuple[str, str]:
    """A record, or ("left out", kind) for a report that is not a sewage record."""
    a = scrubbed_row(row)
    key = row_key(a)
    sid = clean(a.get("submissionId"))
    q = urllib.parse.quote(json.dumps({"filter": [{"submissionId": sid}], "top": 50}, separators=(",", ":")))
    base = dict(source_id=SOURCE_ID, source_record_id=key, fetched_at=fetched_at,
                source_url=f"{LIST_URL}?queryParams={q}")
    p_raw = (prev or {}).get("raw") or {}
    raw = dict(a)
    raw["_withheld"] = WITHHELD_NOTE
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or fetched_at
    revs = list(p_raw.get("_revisions") or [])
    if p_raw and any(clean(p_raw.get(k)) != clean(a.get(k)) for k in TRACKED):
        revs.append({"seen_until": (prev or {}).get("fetched_at"), **{k: p_raw.get(k) for k in TRACKED}})
    if revs:
        raw["_revisions"] = revs[-10:]
    types, quality = parts(a.get("dischargeType")), parts(a.get("dischargeQuality"))
    rw = clean(a.get("receivingWater"))
    etype, left, kind = classify(types, quality, bool(rw and not WATER_NONE.match(rw)))
    if etype is None:
        return ("left out", left)
    raw["_discharge_kind"] = kind
    try:
        return _record(a, base, raw, etype, types, quality, fetched_at, permits)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def _record(a, base, raw, etype, types, quality, fetched_at, permits) -> dict:
    problems = []
    if etype == "unknown":
        problems.append("the list gives no discharge type or quality")
    fetched = parse_ts(fetched_at) or datetime.now(UTC)
    start, end = parse_ts(a.get("eventStartDate")), parse_ts(a.get("eventEndDate"))
    if a.get("eventStartDate") and start is None:
        problems.append(f"start not read: {a.get('eventStartDate')!r}")
    if start is not None and start > fetched + timedelta(days=1):
        raw["_start_not_used"] = (f"the start as published ({iso(start)}) lies after the list was read, most likely "
                                  "a typing error in the year; the report is kept with no start")
        start = None
    status_id = clean(a.get("reportStatusId")).upper()
    complete = status_id == "COMPLETE"
    if end is not None and start is not None and end < start:
        raw["_end_not_used"] = f"the end as published ({iso(end)}) is before the start"
        end = None
    if complete:
        if end is not None and start is not None and end == start:
            # the form repeats the start as the end until the report is completed, and some completed reports keep
            # it (107 of the completed reports since 2025, 98 of them with a volume: a discharge of millions of
            # gallons does not start and end in the same minute), so the end is not confirmed
            status, ended_at = "ended", None
            raw["_end_equals_start"] = True
            raw["_end_not_used"] = (f"the completed report gives the same time for the start and the end of the "
                                    f"discharge ({iso(end)}), the time the form fills in until the report is "
                                    "completed; the end is not confirmed")
            raw["_end_basis"] = "the completed report gives no end distinct from its start"
        elif end is not None:
            status, ended_at = "ended", iso(end)
        else:
            status, ended_at = "ended", None
            raw["_end_basis"] = "the completed report gives no end time"
    else:
        if end is not None and (start is None or end > start):
            status, ended_at = "ended", iso(end)
            raw["_end_basis"] = ("the report is not yet completed (EGLE lists it as in process); the end is the one "
                                 "the operator gave and may change when the report is completed")
        else:
            status, ended_at = "ongoing", None
            raw["_end_basis"] = ("the report is not yet completed (EGLE lists it as in process) and gives no end: "
                                 "the form repeats the start as the end until the report is completed, so no end is "
                                 "used")
    water = clean(a.get("receivingWater")) or None
    land = clean(a.get("landImpacted")) or None
    named = bool(water and not WATER_NONE.match(water))
    if named:
        raw["reached_water"] = True
    elif complete and land:
        raw["reached_water"] = False
    else:
        raw["reached_water"] = None
    permit = norm_permit(a.get("permitNumber"))
    raw["_permit_as_given"] = a.get("permitNumber")
    party = a.get("responsiblePartyName")
    did = permits.get(permit.upper()) if permit else None
    if did is None and not permit:
        did = NAME_OPERATORS.get(clean(party).lower())
        if did:
            raw["_discharger_basis"] = (f"the report gives no permit; joined by EGLE's responsible party "
                                        f"{party!r}")
    if did is None:
        raw["_discharger_basis"] = (f"No operator on record for permit {permit} yet." if permit else
                                    "The report gives no permit number, so no operator is joined; an operator is "
                                    "never inferred from a place or a facility name.")
    outfall_id, outfall_name = outfall_fields(a.get("featureNumber"), a.get("featureDescription"))
    gal = fnum(a.get("dischargeVolumeNumeric"))
    gal = int(round(gal)) if gal is not None and gal >= 0 else None
    vtext = clean(a.get("dischargeVolume")) or None
    if vtext:                               # "6.50000 Million Gallons" -> "6.5 Million Gallons"
        vtext = re.sub(r"(\d+)\.(\d*?)0*(?=\s|$)", lambda m: m.group(1) + ("." + m.group(2) if m.group(2) else ""),
                       vtext)
    material = ", ".join(quality) or None
    if raw.get("_discharge_kind") == "RTB":
        material = (material + " " if material and material.upper() != "RTB" else "") + \
            "(retention treatment basin discharge: combined sewage given partial treatment)"
    return event(
        **base, event_type=etype, status=status,
        discharger_id=did, discharger_name=party, npdes_permit=permit,
        outfall_id=outfall_id, outfall_name=outfall_name,
        waterbody_text=water, water_slugs=[], water_match="none",
        started_at=iso(start), ended_at=ended_at, time_precision="minute" if (start or ended_at) else None,
        reported_at=iso(parse_ts(a.get("submissionReceivedDate"))), published_at=None, source_updated_at=None,
        material=material, volume_gal=gal, volume_text=vtext, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def link_copies(records: list[dict]) -> int:
    """Two submissions of one report (same permit or party, outfall, start minute and volume): the one EGLE received
    last stands, the others are duplicate_of it. Sections of one submission are never copies. Returns the count."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        raw = r.setdefault("raw", {})
        if raw.pop("_duplicate_basis", None) is not None:
            r["duplicate_of"] = None
        if not r.get("started_at") or r.get("event_type") == "unknown":
            continue
        who = r.get("npdes_permit") or clean(r.get("discharger_name")).lower()
        if not who or who == NAME_REMOVED.lower():
            continue
        groups[(who, clean(raw.get("featureNumber")).lower(), r["started_at"][:16], r.get("volume_gal"))].append(r)
    n = 0
    for k, rs in groups.items():
        if len({clean(x["raw"].get("submissionId")) for x in rs}) < 2:
            continue
        keep = max(rs, key=lambda x: (x.get("reported_at") or "", x["event_id"]))
        for r in rs:
            if r is keep or clean(r["raw"].get("submissionId")) == clean(keep["raw"].get("submissionId")):
                continue
            r["duplicate_of"] = keep["event_id"]
            r["raw"]["_duplicate_basis"] = (f"the same report (permit or party, outfall, start and volume) was filed "
                                            f"again; EGLE received {keep['event_id']} later")
            n += 1
    return n


def build(rows: list[dict], fetched_at: str, prev_records: list[dict], permits: dict[str, str] | None = None,
          missing: set[str] | None = None, left_state: dict | None = None,
          carry_completed: bool = False) -> tuple[list[dict], dict]:
    """rows: the list's rows read this run. Returns (records, stats); earlier records not read again are rebuilt
    from their raw fields and kept. missing: keys the service no longer lists (looked up and not found).
    carry_completed: an earlier record of a report EGLE lists as completed that this run did not read is kept as
    saved, not rebuilt (the hourly run with the history on file; main() allows it only while the rules that built
    the saved records are unchanged, build_stamp)."""
    permits = permit_index() if permits is None else permits
    missing = missing or set()
    left_state = left_state if left_state is not None else {}
    prev = {r["event_id"]: r for r in prev_records}
    records, seen, left_now = [], set(), Counter()
    for row in rows:
        key = row_key(row)
        if not key:
            continue
        eid = f"{SOURCE_ID}:{key}"
        if eid in seen:
            continue
        seen.add(eid)
        rec = build_record(row, fetched_at, prev.get(eid), permits)
        if isinstance(rec, tuple):
            left_state[key] = rec[1]
            left_now[rec[1]] += 1
            continue
        left_state.pop(key, None)
        records.append(rec)
    kept = carried = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        raw = r.get("raw") or {}
        row = {k: raw.get(k) for k in FIELDS if k in raw}
        key = row_key(row)
        if (carry_completed and key and key not in missing and isinstance(r.get("raw"), dict)
                and clean(raw.get("reportStatusId")).upper() == "COMPLETE"):
            records.append(r)                   # a completed report not read again: as saved (same rules)
            kept += 1
            carried += 1
            continue
        rec = build_record(row, r.get("fetched_at") or fetched_at, r, permits) if key else r
        if isinstance(rec, tuple):
            left_state[key] = rec[1]
            continue
        rec["fetched_at"] = r.get("fetched_at") or rec["fetched_at"]
        rec["raw"]["_first_seen_at"] = raw.get("_first_seen_at") or rec["raw"].get("_first_seen_at")
        if raw.get("_revisions"):
            rec["raw"]["_revisions"] = raw["_revisions"]
        else:
            rec["raw"].pop("_revisions", None)
        if key in missing or raw.get("_missing_from_list_since"):
            rec["raw"]["_missing_from_list_since"] = raw.get("_missing_from_list_since") or fetched_at
        records.append(rec)
        kept += 1
    dups = link_copies(records)
    records.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]), reverse=True)
    stats = {"rows_read": len(seen), "kept_from_earlier_runs": kept, "kept_as_saved": carried, "copies": dups,
             "by_status": dict(Counter(r["status"] for r in records)),
             "by_type": dict(Counter(r["event_type"] for r in records)),
             "by_report_status": dict(Counter(clean((r.get("raw") or {}).get("reportStatusId")) for r in records)),
             "reached_water": dict(Counter(str((r.get("raw") or {}).get("reached_water")) for r in records)),
             "with_operator_row": sum(1 for r in records if r.get("discharger_id")),
             "with_outfall_number": sum(1 for r in records if r.get("outfall_id")),
             "left_out_this_run": dict(left_now), "statewide": True}
    return records, stats


# ---------------------------------------------------------------- fetching

def query(sess: requests.Session, flt: dict, top: int = TOP, read_timeout: float = 300) -> list[dict]:
    params = {"queryParams": json.dumps({"filter": [flt], "top": top}, separators=(",", ":")),
              "includeMetadataInResponse": "false", "responseFields": ",".join(FIELDS)}
    r = sess.get(LIST_URL, params=params, timeout=(20, read_timeout))
    r.raise_for_status()
    d = r.json()
    if not isinstance(d, dict) or not isinstance(d.get("queryResults"), list):
        raise RuntimeError(f"unexpected answer: {str(d)[:200]}")
    # the service stops at `top` rows and does not always say so: 2006 answered exactly 5,000 rows (February to May)
    # with hasResultsRemaining false on 2026-11-04, so a full answer is read as cut short too
    if d.get("hasResultsRemaining") or len(d["queryResults"]) >= top:
        raise OverflowError(f"{top} rows or more for {flt}")
    return [safe_row(x) for x in d["queryResults"] if isinstance(x, dict)]


class BudgetSpent(Exception):
    """The backfill's time ran out between the requests of a halved span (BACKFILL_BUDGET_S)."""


def query_window(sess, status: str, start: date, stop: date, deadline: float | None = None) -> list[dict]:
    """COMPLETE (or IN_PROCESS) reports with a start in [start, stop): halved while a window holds more than TOP.
    deadline (a clock() time): no further half is asked for after it (BudgetSpent), so a span halved at the end of
    the backfill's budget does not run on past it."""
    flt = {"reportStatusId": status, "eventStartDateMin": start.isoformat(), "eventStartDateMax": stop.isoformat()}
    try:
        return query(sess, flt)
    except OverflowError:
        mid = start + (stop - start) / 2
        if mid <= start:
            raise
        if deadline is not None and clock() > deadline:
            raise BudgetSpent(f"{start.isoformat()} to {stop.isoformat()} needs halving after the budget") from None
        first = query_window(sess, status, start, mid, deadline)
        if deadline is not None and clock() > deadline:
            raise BudgetSpent(f"{mid.isoformat()} to {stop.isoformat()} not asked for within the budget")
        return first + query_window(sess, status, mid, stop, deadline)


def fetch_current(sess, today: date) -> list[dict]:
    open_rows = query(sess, {"reportStatusId": "IN_PROCESS"})
    if not open_rows:
        raise RuntimeError("the list answered with no open (in process) reports at all: read as an outage")
    done = query_window(sess, "COMPLETE", today - timedelta(days=COMPLETE_DAYS), today + timedelta(days=2))
    return open_rows + done


def backfill_spans(first_year: int, today: date) -> list[tuple[str, date | None, date | None]]:
    """(name, start, stop) of each request of a backfill, oldest first: the starts typed before the list's first year
    (only when the backfill starts there), one span per year to this year, and the starts typed after next year."""
    first = LIST_FIRST_YEAR
    spans = [(f"before-{first}", None, date(first, 1, 1))] if first_year <= first else []
    spans += [(str(y), date(y, 1, 1), date(y + 1, 1, 1)) for y in range(max(first_year, first), today.year + 1)]
    return spans + [("later", date(today.year + 1, 1, 1), None)]


def archive_path(name: str) -> Path:
    return ARCHIVE_DIR / f"{name}.json"


def read_archive(name: str) -> list[dict] | None:
    d = read_json(archive_path(name))
    if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
        return None
    return [safe_row(x) for x in d["rows"] if isinstance(x, dict)]


def transient(e: Exception) -> bool:
    """A failure worth asking again: a timeout, a dropped connection, a 5xx or 429, or an answer that is not the list's
    JSON. An HTTP 4xx other than 429 is not (the service no longer answers the query) and stops the backfill."""
    if isinstance(e, requests.HTTPError):
        code = getattr(e.response, "status_code", None)
        return code is None or code >= 500 or code == 429
    return True


def fetch_span(sess, start: date | None, stop: date | None, deadline: float | None = None) -> list[dict]:
    if start and stop:
        return query_window(sess, "COMPLETE", start, stop, deadline)
    flt = {"reportStatusId": "COMPLETE"}
    if start:
        flt["eventStartDateMin"] = start.isoformat()
    if stop:
        flt["eventStartDateMax"] = stop.isoformat()
    return query(sess, flt, read_timeout=BACKFILL_READ_TIMEOUT_S)


def fetch_backfill(sess, today: date, first_year: int, refetch: bool = False, state: dict | None = None,
                   save_state=None) -> tuple[list[dict], dict, list[str]]:
    """Every COMPLETE report from first_year on, a span at a time (backfill_spans), each saved to the archive as it
    arrives. Returns (rows of every span in the archive, read now or before; summary for meta.backfill; errors)."""
    state = state if state is not None else {}
    spans = backfill_spans(first_year, today)
    reread = {str(y) for y in range(today.year - BACKFILL_REREAD_YEARS + 1, today.year + 1)} | {"later"}
    rows, errors = [], []
    read, archived, failed, not_requested, rows_by_span = [], [], [], [], {}
    years = state.setdefault("backfill_years", {})
    t0, fails, stopped = clock(), 0, None
    for name, start, stop in spans:
        have = None if refetch or name in reread else read_archive(name)
        if have is not None:
            rows += have
            archived.append(name)
            rows_by_span[name] = len(have)
            continue
        if stopped or clock() - t0 > BACKFILL_BUDGET_S:
            not_requested.append(name)
            old = read_archive(name)             # an earlier copy of a year read again: kept until it is read
            if old is not None:
                rows += old
                rows_by_span[name] = len(old)
            continue
        if read or failed:
            time.sleep(BACKFILL_PAUSE_S)
        at = now_iso()
        try:
            got = fetch_span(sess, start, stop, t0 + BACKFILL_BUDGET_S)
        except Exception as e:  # noqa: BLE001
            old = read_archive(name)
            if old is not None:
                rows += old
                rows_by_span[name] = len(old)
            if isinstance(e, BudgetSpent):          # the time ran out inside a halved span: not a failure
                not_requested.append(name)
                stopped = stopped or "budget"
                continue
            if not transient(e):
                code = getattr(getattr(e, "response", None), "status_code", None)
                stopped = (f"backfill stopped at {name}: the service answered HTTP {code}; it no longer answers "
                           "this query (not asked again this run)")
                errors.append(stopped)
                failed.append(name)
                continue
            failed.append(name)
            errors.append(f"backfill {name} not read: {type(e).__name__}; asked again by the next --backfill")
            fails += 1
            if fails >= BACKFILL_MAX_FAILURES:
                stopped = f"backfill stopped after {fails} failures in a row; run --backfill again"
                errors.append(stopped)
            continue
        fails = 0
        got = [scrubbed_row(r) for r in got]
        write_json(archive_path(name), {"service": LIST_URL, "fields": FIELDS, "span": name,
                                        "start_min": start.isoformat() if start else None,
                                        "start_max_exclusive": stop.isoformat() if stop else None,
                                        "fetched_at": at, "rows": got})
        years[name] = {"rows": len(got), "fetched_at": at}
        if save_state:
            save_state()                         # the archive and the state agree after every year
        rows += got
        read.append(name)
        rows_by_span[name] = len(got)
    if not_requested:
        errors.append(f"backfill stopped after {BACKFILL_BUDGET_S // 60} minutes or a failure: {len(not_requested)} "
                      f"spans from {not_requested[0]} to {not_requested[-1]} not requested; run --backfill again")
    held = [n for n, _, _ in spans if archive_path(n).exists()]
    complete = not failed and not not_requested
    covered = None
    for n in reversed([n for n, _, _ in spans if n.isdigit()]):    # the first year from which every year to now is held
        if n not in held:
            break
        covered = n
    summary = {"from": first_year, "to": today.year, "complete": complete,
               "covered_from": int(covered) if covered else None,
               "read_now": read, "from_archive": archived, "failed": failed, "not_requested": not_requested,
               "rows_by_span": rows_by_span, "rows": sum(rows_by_span.values())}
    return rows, summary, errors


def lookups(sess, prev_records: list[dict], read_keys: set[str], state: dict, fetched_at: str
            ) -> tuple[list[dict], set[str], list[str]]:
    """Reports read as in process before that neither answer holds now: asked by submissionId (at most LOOKUP_MAX a
    run, the longest unchecked first). Returns (rows found, keys the service no longer lists, errors)."""
    want = {}
    for r in prev_records:
        raw = r.get("raw") or {}
        key = row_key(raw)
        if (key and key not in read_keys and clean(raw.get("reportStatusId")).upper() == "IN_PROCESS"
                and not raw.get("_missing_from_list_since")):
            want.setdefault(clean(raw.get("submissionId")), []).append(key)
    checked = state.setdefault("lookups", {})
    order = sorted(want, key=lambda s: checked.get(s, ""))[:LOOKUP_MAX]
    rows, gone, errors = [], set(), []
    t0 = clock()
    for sid in order:
        if clock() - t0 > LOOKUP_BUDGET_S:
            errors.append(f"lookups stopped after {LOOKUP_BUDGET_S} s; the rest wait for the next run")
            break
        try:
            got = query(sess, {"submissionId": sid}, top=50, read_timeout=LOOKUP_READ_TIMEOUT_S)
        except (requests.Timeout, requests.ConnectionError) as e:
            errors.append(f"submission {sid}: {type(e).__name__}; lookups stopped for this run")
            break                         # a service that does not answer is not asked 40 more times
        except Exception as e:  # noqa: BLE001
            errors.append(f"submission {sid}: {type(e).__name__}")
            continue
        checked[sid] = fetched_at
        found = {row_key(x) for x in got}
        rows += got
        gone |= {k for k in want[sid] if k not in found}
    return rows, gone, errors


# ---------------------------------------------------------------- main

def load_file(path: str) -> list[dict]:
    d = json.loads(Path(path).read_text())
    docs = d if isinstance(d, list) else [d]
    out = []
    for doc in docs:
        if isinstance(doc, dict) and isinstance(doc.get("queryResults"), list):
            out += [safe_row(x) for x in doc["queryResults"]]
        elif isinstance(doc, dict) and isinstance(doc.get("rows"), list):
            out += [safe_row(x) for x in doc["rows"]]
        elif isinstance(doc, dict) and "submissionId" in doc:
            out.append(safe_row(doc))
    return out


def left_scope(state: dict) -> str:
    """The span the left-out counts cover, for the site's sentence ("Of <span>, ...")."""
    b = state.get("backfill") or {}
    first = b.get("covered_from", b.get("from"))
    return (f"every report read since January {first}" if first else
            "the reports read so far (open reports and those completed in the last 60 days at first)")


def build_stamp(permits: dict[str, str]) -> str:
    """What the saved records were built under: this module, common.py and build/redact.py as files, the permit
    index and the name lists (the allowlist, the private blocklist in data/build and the public one in data/ that
    build/redact.py also reads). A change to any of them makes the next run rebuild every record (once)."""
    from build import redact
    h = hashlib.sha256()
    for f in (Path(__file__), Path(sys.modules["common"].__file__), Path(redact.__file__),
              DATA_DIR / "name-allowlist.json", BUILD_DIR / "name-blocklist.json", DATA_DIR / "name-blocklist.json"):
        h.update(f.read_bytes() if f.exists() else b"-")
    h.update(json.dumps(sorted(permits.items())).encode())
    return h.hexdigest()


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved list response (or a list of them) instead of the service")
    ap.add_argument("--backfill", action="store_true", help="also read every COMPLETE report from --from on")
    ap.add_argument("--from", dest="first_year", type=int, default=BACKFILL_FROM,
                    help=f"first year of the backfill (default {BACKFILL_FROM}, the list's first year)")
    ap.add_argument("--refetch", action="store_true",
                    help="with --backfill: ask again for years already in the archive")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    today = datetime.now(UTC).date()
    sess = requests.Session()
    sess.headers.update({**HEADERS, "Accept": "application/json"})
    state = read_json(STATE_FILE, {}) or {}
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    errors: list[str] = []
    missing: set[str] = set()
    history, summary = [], None
    try:
        if args.file:
            rows = load_file(args.file)
        else:
            rows = fetch_current(sess, today)
            if args.backfill:
                history, summary, errors = fetch_backfill(sess, today, args.first_year, args.refetch, state,
                                                          lambda: write_json(STATE_FILE, state))
            found, missing, more = lookups(sess, prev, {row_key(r) for r in rows + history}, state, fetched_at)
            rows += found
            errors += more
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    raw_path = state.get("raw_path")
    if not args.file:
        doc = {"service": LIST_URL, "fields": FIELDS, "fetched_at": fetched_at, "rows": [scrubbed_row(r) for r in rows]}
        sha = hashlib.sha256(json.dumps(doc["rows"], sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False), "json").relative_to(ROOT))
            state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
    left_state = state.setdefault("left_out", {})
    permits = permit_index()
    # the hourly run keeps the completed reports it did not read as saved while the rules are unchanged (with the
    # history from 2001 on file, rebuilding some 50,000 records every hour took minutes); a backfill, a --file run
    # or a change of rules rebuilds every record
    stamp = build_stamp(permits)
    carry = not args.backfill and not args.file and state.get("build_stamp") == stamp
    # the current answer first: a report read now wins over its archived copy (build keeps the first row of a key)
    records, stats = build(rows + history, fetched_at, prev, permits, missing, left_state, carry_completed=carry)
    saved = {id(r) for r in prev}
    rebuilt = [i for i, r in enumerate(records) if id(r) not in saved]
    if len(rebuilt) == len(records):
        records = redact.redact_events(records)
    else:
        # the records kept as saved were redacted when they were built; the rebuilt ones are redacted with a lexicon of
        # their own (a lexicon over every record took 15 s an hour; a smaller one stops fewer words, so it can remove
        # more); the export's pass over every record of every feed, with a lexicon of them all, is unchanged
        redactor = redact.redactor_for([records[i] for i in rebuilt])
        for i in rebuilt:
            records[i] = redactor.event(records[i])
    state["fetched_at"] = fetched_at
    if summary is not None:
        state["backfill"] = {**summary, "at": fetched_at,
                             "records_by_start_year": dict(sorted(Counter(
                                 (r.get("started_at") or "no start")[:4] for r in records
                                 if r.get("source_record_id")).items()))}
    write_json(STATE_FILE, state)
    left = Counter(left_state.values())
    newest = max((r.get("reported_at") or "" for r in records), default="") or None
    meta = {**stats, "newest_report": newest, "raw_path": raw_path, "page": PAGE_URL, "service": LIST_URL,
            "time_basis": MI_TZ_NOTE, "credit": CREDIT, "registry_ids": [SOURCE_ID],
            "left_out": dict(left),
            "left_out_note": (f"Counted over {left_scope(state)}: reports on the list that are not sewage records, "
                              "other pollution (fuel, oil, paint or chemicals with no sewage named) and spills of "
                              "biosolids or sludge onto land, are counted here but not shown as sewage reports."),
            "backfill": state.get("backfill"), "lookup_errors": errors or None}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    # the stamp only once the records it built are on file: a run stopped before (a timeout, a full disk) leaves the
    # old one, so the next run rebuilds every record rather than keep old ones under rules they were not built with
    state["build_stamp"] = stamp
    write_json(STATE_FILE, state)
    print(f"{SOURCE_ID}: {stats['rows_read']} rows read, {stats['kept_from_earlier_runs']} kept; status "
          f"{stats['by_status']}; types {stats['by_type']}; operator row {stats['with_operator_row']}; "
          f"left out {dict(left)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
