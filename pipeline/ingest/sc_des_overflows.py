"""South Carolina DES wastewater overflow list -> data/build/events/sc-des-overflow-list.json

Source
  South Carolina Department of Environmental Services (DES), Bureau of Water: the public list "View Wastewater
  Overflows" in DES's ePermitting system (https://epermitting.des.sc.gov/ext/ncore/external/overflow/list, linked from
  https://des.sc.gov/programs/bureau-water/wastewater/wastewater-sewer-overflows). The page reads the same
  unauthenticated nCORE (Windsor Solutions) list service that Michigan's MiEnviro list uses,
  GET https://epermitting.des.sc.gov/ext/ncore/ss/ssolist?queryParams=<JSON {"filter":[{...}],"top":n}>
  &includeMetadataInResponse=false&responseFields=<comma list>, so the request, the cut-short check and the window
  halving are ingest/mi_egle_mienviro.py's own (query, query_window) with this list's address and safe fields. No key,
  no cookie, no licence statement. Credit "South Carolina DES, ePermitting wastewater overflow list".
  Law: S.C. Code 48-1-95(B): a utility must notify DES of a significant spill (5,000 gallons or more) within 24 hours
  and in writing within five days; DES's overflow page asks every regulated system to report overflows electronically
  through ePermitting (generally those of 500 gallons or more and any that reach a water). This list is those reports.

What the list holds (read 2026-11-16)
  1,773 rows, every one reportStatusId COMPLETE ("Completed"; an IN_PROCESS query answers none, so a report appears
  once DES's form is completed), section 2 on every row, submissionId unique, events from 2022-09-26 to 2026-11-10
  (plus two starts typed in later years). No total count: the service gives none (metadata null) and its
  hasResultsRemaining is false even for an answer cut at `top`, so mi_egle_mienviro.query's "an answer of `top` rows is
  cut short" rule applies.

What is requested (privacy)
  Only FIELDS are requested (responseFields) and kept. Never requested (WITHHELD): responsiblePartyName (often the
  person who filed: about 100 of 312 distinct values name no body), locationDescription (street addresses),
  actionTaken, actionToBeTaken, deqActions, agencyComments, socRequirements, and `id` (renumbered on every answer).
  siteName passes mi_egle_mienviro.party_name (a person's name becomes "[name removed]"); the place (featureNumber,
  featureDescription), the receiving water, the land reached, the type and the cause (dischargeDescription, the
  operator's words) pass mi_egle_mienviro.free_text (e-mails, telephones, owners' and residents' names and house
  numbers cut: "across from <number> <street>" keeps the street without the number); common.event strips personal
  keys and build.redact runs over the records last. The raw page saved is the scrubbed rows.

Record rules
  - Key: submissionId and sectionNumber (mi_egle_mienviro.row_key); a report DES revises keeps its record, the earlier
    values in raw._revisions. source_url is the list service filtered to that submission.
  - Times: DES's service writes each time with its UTC offset, and every start, end and receipt on the 2026-11-16 list
    carries the offset America/New_York had at that local time (-04:00 in daylight time, -05:00 otherwise; 0 of 5,319
    differ), so the times are Eastern local time as the list means them; they are kept with their offsets,
    time_precision minute. A value with no offset is read in America/New_York.
  - reported_at is submissionReceivedDate (DES's receipt), never a start. published_at and source_updated_at are null
    (the list gives no posting time). raw._first_seen_at is our clock.
  - A start is not used (raw._start_not_used; the report is kept with no start) when it lies more than a day after the
    read (2029-08-17 for an event that ended 2026-08-17), when it repeats the receipt time to the minute (7 rows on
    2026-11-16, each with an end before it: the form's receipt time, not the event's), or when it is after the receipt
    (6 rows: a discharge is reported after it starts).
  - Ends: an end before the start, or after the read (an end the operator expected, not one that has happened), is
    not used (raw._end_not_used). A completed
    report whose end repeats its start to the minute (110 rows on 2026-11-16, 97 of them with a volume) has its end
    not confirmed, as on Michigan's list from the same form: status ended with no end (the status build then gives the
    caution from the report time and "end not confirmed" to day 30). A completed report with an end -> ended at it.
    A report DES lists as in process (none on 2026-11-16) follows Michigan's rule: ongoing with no end unless it gives
    an end after its start.
  - Type: sso. The list is DES's sanitary sewer overflow list (the service is "ssolist"; South Carolina has no combined
    sewers); dischargeType is "SSO Discharge" or empty (1,168 rows), raw._type_basis says so. A report whose place and
    cause name only biosolids or sludge, with no sewage word and no receiving water, is left out and counted
    (meta.left_out "biosolids"), the owner's scope rule of 2026-11-04 as on Michigan's list. A row DES marks withdrawn,
    void, rejected or deleted is left out (meta.left_out "withdrawn by DES") and its earlier record is not kept.
  - Operator: permitNumber as given. A federal NPDES permit (SC0xxxxxx, SCGxxxxxx) is npdes_permit, joined to
    data/dischargers.json by that permit (a South Carolina row holding it alone). A state permit (SSS satellite sewer
    systems, ND no-discharge permits) is raw._state_permit, never npdes_permit (ND is not North Dakota); no operator row
    holds one, so the operator is listed as DES's site name. discharger_name is the operator row's name when joined,
    else the site name; an operator is never inferred from a place or a name. raw.state is "SC" on every record.
  - Place: the manhole, pump station or line as the list gives it (featureDescription, with featureNumber when it adds
    to it) is outfall_name: a place description, never an outfall id (manhole numbers are not outfall numbers, so the
    outfall registry is never asked). countyDescription is raw.county.
  - Water: receivingWater as given is waterbody_text ("STORM DRAIN", "Not Applicable" and the like included; the status
    build reads those as no water). raw._placement "named_water_only": the status build places a report only on the
    water it names, within the county the list gives (COUNTY_FIELD_STATES), never on its permit's plant water and never
    by a point (the list gives none); a report naming no water is listed with its county and colours nothing.
    raw.reached_water: true when a water is named, else null.
  - Volume: dischargeVolumeNumeric in gallons (volume_gal; a negative value is not used); volume_text the list's own
    words, spaces collapsed; estimate_flag unknown.
  - Cause: dischargeDescription as given (scrubbed), raw.dischargeDescription.
  - Copies: two submissions with the same permit, place, receiving water, start, end and volume are one report filed
    twice (seen 2025-05-12: SSS000716, two pairs a minute apart); the one DES received last stands and the others are
    duplicate_of it (raw._duplicate_basis), recomputed every run. Nothing less than all of these links two reports.
  - EPA's copy: EPA's overflow tables (ingest/echo_sewer_overflow_events.py, run before this module) held no South
    Carolina row on 2026-11-16. Should one appear, an EPA record of an SC permit whose start (EPA's local time, naive) is
    the same minute as exactly one record here of the same permit, and the only EPA record of that permit and minute,
    becomes duplicate_of this list's record (written back into EPA's events file), as Georgia's EPD list does with
    EPA's Georgia rows (ingest/ga_epd_spills.py); no end or other field is taken from it. Anything less stays apart.
  - The City of Florence's notices (ingest/sc_florence_sso.py) give no start, so they are not linked to these reports.

Reading and failure
  Each run reads the whole list in one request (about 1.3 MB uncompressed, 5 to 10 s on 2026-11-16); an answer of TOP
  rows is cut short and the list is then read a year of starts at a time (with the starts typed before 2022 and after
  next year), halved by query_window while a year holds TOP or more. A failed request, an answer that is not the list's
  JSON, a row without the list's key fields, no rows at all, or fewer rows than MIN_SHARE of the last complete read
  (meta.completeness) is a failed read: ok false, nothing saved, every record kept as it was, exit 1. A report missing
  from a complete healthy read keeps its record (reports are records, not standing listings), with
  raw._missing_from_list_since. Records kept from earlier runs are rebuilt from their raw fields under the current
  rules.

History (`--backfill`)
  The list's whole history (from 2022) is read by every run, so the first hourly run loads it; `--backfill` (the
  refresh workflow's backfill input "sc_des_overflows") does the same read and records meta.backfill (rows, range,
  time taken): one request, about 1.3 MB, under a minute.

Cadence: hourly (start to DES's receipt: median 4.9 days on the 2026-11-16 list, 5.0 days over the last 12 months).
Run from pipeline/:  python -m ingest.sc_des_overflows [--file saved.json] [--backfill]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, NAME_REMOVED, ROOT, event, now_iso, path_notes_to_meta,
                    read_json, save_raw, scrub_text, write_events, write_json)
from ingest import mi_egle_mienviro as mi

SOURCE_ID = "sc-des-overflow-list"
REGISTRY_IDS = ["sc-des-sso-database"]
BASE = "https://epermitting.des.sc.gov/ext/ncore"
LIST_URL = f"{BASE}/ss/ssolist"
PAGE_URL = f"{BASE}/external/overflow/list"
STATE_FILE = BUILD_DIR / "sc-des-overflow-list-state.json"
EPA_EVENTS = EVENTS_DIR / "echo-sewer-overflow.json"
AUTHORITY = "South Carolina DES (ePermitting wastewater overflow list)"
CREDIT = "South Carolina Department of Environmental Services, ePermitting wastewater overflow list"
FIELDS = ["submissionId", "submissionReferenceNumber", "sectionNumber", "submissionReceivedDate", "siteName",
          "permitNumber", "countyDescription", "countyId", "reportStatusId", "reportStatusDescription",
          "dischargeType", "dischargeQuality", "dischargeVolume", "dischargeVolumeNumeric", "eventStartDate",
          "eventEndDate", "featureNumber", "featureDescription", "receivingWater", "landImpacted",
          "dischargeDescription", "precipitationAmount", "precipitationType"]
WITHHELD = ("id", "responsiblePartyName", "locationDescription", "actionTaken", "actionToBeTaken", "deqActions",
            "agencyComments", "socRequirements")
WITHHELD_NOTE = ("The list's responsible party (often the person who filed), its location description and the "
                 "actions taken and comments are not reproduced here: they can name people and street addresses. "
                 "The source record has them.")
REQUIRED = ("submissionId", "sectionNumber", "eventStartDate", "eventEndDate", "submissionReceivedDate",
            "permitNumber", "reportStatusId")
TOP = 5000
MIN_SHARE = 0.9                 # a read holding fewer rows than this share of the last complete read is cut short
LIST_FIRST_YEAR = 2022          # the list's first start on 2026-11-16: 2022-09-26
EASTERN = ZoneInfo("America/New_York")
TZ_NOTE = ("Times as DES's list gives them, with their UTC offsets: Eastern time (each offset is the one "
           "America/New_York had at that local time).")
TYPE_BASIS = ("DES's list is its sanitary sewer overflow list (the service is 'ssolist'; South Carolina has no "
              "combined sewers)")
FEDERAL_PERMIT = re.compile(r"^SC[0G]\d{6}$")
WITHDRAWN = re.compile(r"withdr|void|reject|delet|cancel", re.I)
SEWAGE_OR_WATER = mi.SEWAGE_WORDS


# ---------------------------------------------------------------- helpers

clean = mi.clean


def parse_ts(v) -> datetime | None:
    """'2026-11-10T19:30:00.0000000-05:00' -> aware datetime (DES's offset kept); a value with no offset is read in
    Eastern time."""
    m = mi.TS.match(clean(v))
    if not m:
        return None
    d, t, off = m.groups()
    if len(t) == 5:
        t += ":00"
    try:
        if off is None:
            return datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=EASTERN)
        off = "+00:00" if off == "Z" else (off if ":" in off else off[:3] + ":" + off[3:])
        return datetime.fromisoformat(f"{d}T{t}{off}")
    except ValueError:
        return None


iso = mi.iso


def safe_row(r: dict) -> dict:
    return {k: r.get(k) for k in FIELDS if k in r}


# a person named in the operator's words (lessons from reviews, 6): "Mr. <surname>", "Dr. <given> <surname>", and
# "<given> <surname> reported / called / stated ..." unless the words name a body ("Public Works reported")
HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?[ ]{1,2}[A-Z][A-Za-z'-]+(?:[ ]{1,2}[A-Z][A-Za-z'-]+)?")
NAME_VERB = re.compile(r"\b([A-Z][a-z'-]+[ ]{1,2}[A-Z][a-z'-]+)(?=[ ]{1,2}(?:reported|called|stated|said|notified|"
                       r"contacted|observed|noticed|discovered)\b)")


def cut_person_cues(v: str) -> str:
    v = HONORIFIC.sub(NAME_REMOVED, v)
    return NAME_VERB.sub(lambda m: m.group(0) if mi._site_words(m.group(1)) else NAME_REMOVED, v)


def scrubbed_row(r: dict) -> dict:
    """The fields as the record and the raw save keep them (module docstring, privacy)."""
    out = safe_row(r)
    if out.get("siteName") is not None:
        out["siteName"] = mi.party_name(out["siteName"])
    for k in ("featureNumber", "featureDescription", "receivingWater", "landImpacted", "dischargeType",
              "dischargeDescription"):
        if isinstance(out.get(k), str):
            out[k] = cut_person_cues(mi.free_text(out[k])) or None
    for k in ("permitNumber", "countyDescription", "dischargeVolume", "dischargeQuality"):
        if isinstance(out.get(k), str):
            out[k] = scrub_text(clean(out[k])) or None
    return out


row_key = mi.row_key


def permit_index(rows: list[dict] | None = None) -> dict[str, str]:
    """NPDES permit -> data/dischargers.json id, for South Carolina rows (a permit two rows hold maps to neither)."""
    if rows is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
    seen: dict[str, set[str]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("state") != "SC":
            continue
        for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
            if p:
                seen.setdefault(str(p).strip().upper(), set()).add((r["id"], r.get("name")))
    return {p: next(iter(v)) for p, v in seen.items() if len(v) == 1}


def place_text(number, description) -> str | None:
    """The place as the list gives it: the description, with the feature number when the description lacks it."""
    num, desc = clean(number), clean(description)
    if re.fullmatch(r"0+", num):            # "0", "00": the form's empty number
        num = ""
    if num and desc and num.lower() not in desc.lower():
        return f"{desc} ({num})"
    return desc or num or None


# ---------------------------------------------------------------- records

TRACKED = ("reportStatusId", "eventStartDate", "eventEndDate", "dischargeVolume", "receivingWater", "featureNumber",
           "featureDescription", "dischargeType", "permitNumber", "dischargeDescription")


def build_record(row: dict, fetched_at: str, prev: dict | None, permits: dict) -> dict | tuple[str, str]:
    """A record, or ("left out", kind)."""
    a = scrubbed_row(row)
    key = row_key(a)
    status_text = f"{clean(a.get('reportStatusId'))} {clean(a.get('reportStatusDescription'))}"
    if WITHDRAWN.search(status_text):
        return ("left out", "withdrawn by DES")
    place_words = " ".join(clean(a.get(k)) for k in ("featureDescription", "dischargeDescription", "dischargeType"))
    water = clean(a.get("receivingWater")) or None
    named = bool(water and not mi.WATER_NONE.match(water))
    if mi.BIOSOLIDS.search(place_words) and not named \
            and not SEWAGE_OR_WATER.search(mi.BIOSOLIDS.sub(" ", place_words)):
        return ("left out", "biosolids")
    sid = clean(a.get("submissionId"))
    q = urllib.parse.quote(json.dumps({"filter": [{"submissionId": sid}], "top": 50}, separators=(",", ":")))
    base = dict(source_id=SOURCE_ID, source_record_id=key, fetched_at=fetched_at, source_url=f"{LIST_URL}?queryParams={q}")
    p_raw = (prev or {}).get("raw") or {}
    raw = dict(a)
    raw["_withheld"] = WITHHELD_NOTE
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or fetched_at
    revs = list(p_raw.get("_revisions") or [])
    if p_raw and any(clean(p_raw.get(k)) != clean(a.get(k)) for k in TRACKED):
        revs.append({"seen_until": (prev or {}).get("fetched_at"), **{k: p_raw.get(k) for k in TRACKED}})
    if revs:
        raw["_revisions"] = revs[-10:]
    raw["state"] = "SC"
    raw["county"] = clean(a.get("countyDescription")) or None
    raw["_placement"] = "named_water_only"
    raw["_type_basis"] = (f"{TYPE_BASIS}; the report's type: {clean(a.get('dischargeType'))!r}"
                          if clean(a.get("dischargeType")) else f"{TYPE_BASIS}; the report gives no type")
    try:
        return _record(a, base, raw, fetched_at, permits, water, named)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="sso", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def _record(a, base, raw, fetched_at, permits, water, named) -> dict:
    problems = []
    fetched = parse_ts(fetched_at) or datetime.now(UTC)
    start, end = parse_ts(a.get("eventStartDate")), parse_ts(a.get("eventEndDate"))
    received = parse_ts(a.get("submissionReceivedDate"))
    if a.get("eventStartDate") and start is None:
        problems.append(f"start not read: {a.get('eventStartDate')!r}")
    if a.get("eventEndDate") and end is None:
        problems.append(f"end not read: {a.get('eventEndDate')!r}")
    if start is not None and start > fetched + timedelta(days=1):
        raw["_start_not_used"] = (f"the start as published ({iso(start)}) lies after the list was read, most likely "
                                  "a typing error in the year; the report is kept with no start")
        start = None
    elif start is not None and received is not None and start.replace(second=0, microsecond=0) == \
            received.replace(second=0, microsecond=0):
        raw["_start_not_used"] = (f"the start as published ({iso(start)}) is the minute DES received the report, not "
                                  "the time the discharge began; the report is kept with no start")
        start = None
    elif start is not None and received is not None and start > received:
        raw["_start_not_used"] = (f"the start as published ({iso(start)}) is after DES received the report "
                                  f"({iso(received)}); the report is kept with no start")
        start = None
    if end is not None and end > fetched:
        raw["_end_not_used"] = (f"the end as published ({iso(end)}) lies after the list was read: not an end that "
                                "has happened")
        end = None
    if end is not None and start is not None and end < start:
        raw["_end_not_used"] = f"the end as published ({iso(end)}) is before the start"
        end = None
    complete = clean(a.get("reportStatusId")).upper() == "COMPLETE"
    if complete:
        if end is not None and start is not None and end == start:
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
            raw["_end_basis"] = raw.get("_end_basis") or "the completed report gives no end time that can be used"
    else:
        if end is not None and (start is None or end > start):
            status, ended_at = "ended", iso(end)
            raw["_end_basis"] = ("the report is not yet completed (DES lists it as in process); the end is the one "
                                 "the operator gave and may change when the report is completed")
        else:
            status, ended_at = "ongoing", None
            raw["_end_basis"] = ("the report is not yet completed (DES lists it as in process) and gives no end "
                                 "after its start, so no end is used")
    raw["reached_water"] = True if named else None
    permit = clean(a.get("permitNumber")).upper() or None
    npdes = permit if permit and FEDERAL_PERMIT.match(permit) else None
    if permit and not npdes:
        raw["_state_permit"] = permit
    tied = permits.get(npdes) if npdes else None
    site = clean(a.get("siteName")) or None
    if tied:
        did, dname = tied
        raw["_discharger_basis"] = f"joined by permit {npdes} (data/dischargers.json)"
    else:
        did, dname = None, (site if site and site != NAME_REMOVED else None)
        raw["_discharger_basis"] = (
            f"No operator on record for permit {npdes} yet; listed by DES's site name." if npdes else
            f"The report gives the state permit {permit}, which no operator row holds; listed by DES's site name; an "
            "operator is never inferred from a place or a name." if permit else
            "The report gives no permit; listed by DES's site name.")
    gal = mi.fnum(a.get("dischargeVolumeNumeric"))
    if gal is not None and gal < 0:
        raw["_volume_not_used"] = f"the list gives a negative volume ({a.get('dischargeVolumeNumeric')})"
        gal = None
    gal = int(round(gal)) if gal is not None else None
    vtext = clean(a.get("dischargeVolume")) or None
    return event(
        **base, event_type="sso", status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=npdes,
        outfall_id=None, outfall_name=place_text(a.get("featureNumber"), a.get("featureDescription")),
        waterbody_text=water, water_slugs=[], water_match="none",
        started_at=iso(start), ended_at=ended_at, time_precision="minute" if (start or ended_at) else None,
        reported_at=iso(received), published_at=None, source_updated_at=None,
        material=None, volume_gal=gal, volume_text=vtext, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


COPY_BASIS = "the same report was filed again"


def link_copies(records: list[dict]) -> int:
    """Two submissions with the same permit, place, receiving water, start, end and volume: the one DES received last
    stands, the others are duplicate_of it. Recomputed every run. Returns the count."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        raw = r.setdefault("raw", {})
        if raw.pop("_duplicate_basis", None) is not None:
            r["duplicate_of"] = None
        if not r.get("started_at"):
            continue
        who = r.get("npdes_permit") or raw.get("_state_permit")
        if not who:
            continue
        k = (who, clean(raw.get("featureNumber")).lower(), clean(raw.get("featureDescription")).lower(),
             clean(raw.get("receivingWater")).lower(), r["started_at"], r.get("ended_at"),
             clean(raw.get("eventEndDate"))[:16], r.get("volume_gal"))
        groups[k].append(r)
    n = 0
    for rs in groups.values():
        if len({clean(x["raw"].get("submissionId")) for x in rs}) < 2:
            continue
        keep = max(rs, key=lambda x: (x.get("reported_at") or "", x["event_id"]))
        for r in rs:
            if r is keep:
                continue
            r["duplicate_of"] = keep["event_id"]
            r["raw"]["_duplicate_basis"] = (f"{COPY_BASIS} (the same permit, place, receiving water, start, end and "
                                            f"volume); DES received {keep['event_id']} later")
            n += 1
    return n


def build(rows: list[dict], fetched_at: str, prev_records: list[dict], permits: dict | None = None,
          complete_read: bool = True, left_state: dict | None = None) -> tuple[list[dict], dict]:
    """rows: the list's rows read this run. Earlier records not read again are rebuilt from their raw fields and kept
    (raw._missing_from_list_since when this was a complete read)."""
    permits = permit_index() if permits is None else permits
    left_state = left_state if left_state is not None else {}
    prev = {r["event_id"]: r for r in prev_records if isinstance(r, dict) and r.get("event_id")}
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
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        raw = r.get("raw") or {}
        row = {k: raw.get(k) for k in FIELDS if k in raw}
        key = row_key(row)
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
        if raw.get("_missing_from_list_since") or complete_read:
            rec["raw"]["_missing_from_list_since"] = raw.get("_missing_from_list_since") or fetched_at
        records.append(rec)
        kept += 1
    dups = link_copies(records)
    records.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]), reverse=True)
    stats = {"rows_read": len(seen), "kept_from_earlier_runs": kept, "copies": dups,
             "by_status": dict(Counter(r["status"] for r in records)),
             "with_operator_row": sum(1 for r in records if r.get("discharger_id")),
             "with_state_permit": sum(1 for r in records if (r.get("raw") or {}).get("_state_permit")),
             "names_water": sum(1 for r in records if (r.get("raw") or {}).get("reached_water")),
             "start_not_used": sum(1 for r in records if (r.get("raw") or {}).get("_start_not_used")),
             "end_not_confirmed": sum(1 for r in records if r["status"] == "ended" and not r.get("ended_at")),
             "left_out_this_run": dict(left_now), "statewide": True}
    return records, stats


# ---------------------------------------------------------------- EPA's copy

EPA_BASIS = "South Carolina DES's overflow list carries this report as"


def _naive_minute(v) -> str | None:
    s = clean(v)
    return s[:16] if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s) else None


def mark_epa_duplicates(records: list[dict], epa: list[dict]) -> Counter:
    """An EPA record of an SC permit whose start minute (EPA's local time) is that of exactly one record here of the
    same permit, and is the only such EPA record, becomes duplicate_of it. Marks of earlier runs are cleared first."""
    n: Counter = Counter()
    for e in epa:
        if ((e.get("raw") or {}).get("_duplicate_basis") or "").startswith(EPA_BASIS):
            e["duplicate_of"] = None
            e["raw"].pop("_duplicate_basis", None)
            n["cleared"] += 1
    mine = defaultdict(list)
    for r in records:
        if r.get("duplicate_of") or not r.get("npdes_permit") or not r.get("started_at"):
            continue
        mine[(r["npdes_permit"], r["started_at"][:16])].append(r)
    theirs = defaultdict(list)
    for e in epa:
        p = str(e.get("npdes_permit") or "")
        m = _naive_minute(e.get("started_at"))
        if e.get("duplicate_of") or not p.startswith("SC") or not m:
            continue
        theirs[(p, m)].append(e)
    for k, es in theirs.items():
        rs = mine.get(k) or []
        if len(es) == 1 and len(rs) == 1:
            es[0]["duplicate_of"] = rs[0]["event_id"]
            es[0].setdefault("raw", {})["_duplicate_basis"] = (f"{EPA_BASIS} {rs[0]['event_id']} (the same permit "
                                                               "and start minute)")
            n["paired"] += 1
        else:
            n["not_paired"] += len(es)
    return n


# ---------------------------------------------------------------- fetching

class BadRead(Exception):
    """An answer that is not a complete reading of the list."""


def year_spans(today: date) -> list[tuple[str, date | None, date | None]]:
    spans = [(f"before-{LIST_FIRST_YEAR}", None, date(LIST_FIRST_YEAR, 1, 1))]
    spans += [(str(y), date(y, 1, 1), date(y + 1, 1, 1)) for y in range(LIST_FIRST_YEAR, today.year + 2)]
    return spans + [("later", date(today.year + 2, 1, 1), None)]


def fetch_all(sess, today: date) -> tuple[list[dict], str]:
    """Every row of the list: one request, or a year of starts at a time when one answer is cut short. Returns
    (rows, how)."""
    kw = {"url": LIST_URL, "fields": FIELDS}
    try:
        return mi.query(sess, {}, top=TOP, **kw), "one request"
    except OverflowError:
        pass
    rows = []
    for name, start, stop in year_spans(today):
        if start and stop:
            rows += mi.query_window(sess, None, start, stop, **kw)
        else:
            flt = {"eventStartDateMin": start.isoformat()} if start else {"eventStartDateMax": stop.isoformat()}
            rows += mi.query(sess, flt, top=TOP, **kw)
    return rows, "by year of start"


def check_read(rows: list[dict], last_complete: int | None) -> None:
    """A read that is not the whole list raises BadRead (module docstring, Reading and failure)."""
    if not rows:
        raise BadRead("the list answered no rows at all: read as an outage")
    bad = [i for i, r in enumerate(rows) if any(k not in r for k in REQUIRED) or not row_key(r)]
    if bad:
        raise BadRead(f"{len(bad)} of {len(rows)} rows lack the list's key fields ({', '.join(REQUIRED)}): the "
                      "answer's shape changed")
    if last_complete and len(rows) < MIN_SHARE * last_complete:
        raise BadRead(f"the list answered {len(rows)} rows, fewer than {int(MIN_SHARE * 100)} percent of the "
                      f"{last_complete} of the last complete read: read as cut short")


def session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({**HEADERS, "Accept": "application/json"})
    return sess


def load_file(path: str) -> list[dict]:
    d = json.loads(Path(path).read_text())
    docs = d if isinstance(d, list) else [d]
    out = []
    for doc in docs:
        if isinstance(doc, dict) and isinstance(doc.get("queryResults"), list):
            out += [safe_row(x) for x in doc["queryResults"] if isinstance(x, dict)]
        elif isinstance(doc, dict) and isinstance(doc.get("rows"), list):
            out += [safe_row(x) for x in doc["rows"] if isinstance(x, dict)]
    return out


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved list response instead of the service")
    ap.add_argument("--backfill", action="store_true",
                    help="read the whole history (every run does; this records meta.backfill)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    today = datetime.now(UTC).date()
    state = read_json(STATE_FILE, {}) or {}
    prev_doc = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    prev = prev_doc.get("records", [])
    t0 = time.monotonic()
    try:
        if args.file:
            rows, how = load_file(args.file), "file"
        else:
            rows, how = fetch_all(session(), today)
        check_read(rows, None if args.file else state.get("last_complete_rows"))
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {scrub_text(str(e))[:300]}"
        write_events(SOURCE_ID, [], ok=False, error=msg,
                     meta={"completeness": {"failed_at": fetched_at, "last_complete_rows": state.get("last_complete_rows")}})
        print(f"{SOURCE_ID}: FAILED {msg}", file=sys.stderr)
        return 1
    took = round(time.monotonic() - t0, 1)
    scrubbed = [scrubbed_row(r) for r in rows]
    raw_path = state.get("raw_path")
    if not args.file:
        doc = {"service": LIST_URL, "fields": FIELDS, "fetched_at": fetched_at, "rows": scrubbed}
        sha = hashlib.sha256(json.dumps(scrubbed, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, json.dumps(doc, ensure_ascii=False), "json").relative_to(ROOT))
            state.update(sha256=sha, raw_path=raw_path, saved_at=fetched_at)
    left_state = state.setdefault("left_out", {})
    records, stats = build(scrubbed, fetched_at, prev, permit_index(), complete_read=not args.file,
                           left_state=left_state)
    records = redact.redact_events(records)
    epa_doc = read_json(EPA_EVENTS, {}) or {}
    epa = epa_doc.get("records") or []
    pairing = mark_epa_duplicates(records, epa) if epa else Counter()
    state["fetched_at"] = fetched_at
    if not args.file:
        state["last_complete_rows"] = len(rows)
    if args.backfill:
        starts = sorted(r["started_at"] for r in records if r.get("started_at"))
        state["backfill"] = {"at": fetched_at, "how": how, "rows": len(rows), "seconds": took,
                             "first_start": starts[0] if starts else None, "last_start": starts[-1] if starts else None,
                             "records_by_start_year": dict(sorted(Counter(
                                 (r.get("started_at") or "no start")[:4] for r in records).items()))}
    write_json(STATE_FILE, state)
    newest = max((r.get("reported_at") or "" for r in records), default="") or None
    meta = {**stats, "newest_report": newest, "raw_path": raw_path, "page": PAGE_URL, "service": LIST_URL,
            "read": how, "time_basis": TZ_NOTE, "credit": CREDIT, "registry_ids": REGISTRY_IDS,
            "left_out": dict(Counter(left_state.values())),
            "left_out_note": ("Reports on the list that are not sewage records (spills of biosolids or sludge onto "
                              "land) or that DES marks withdrawn are counted here, not shown."),
            "completeness": {"rows_this_read": len(rows), "min_share_of_last_complete_read": MIN_SHARE},
            "epa_pairing": dict(pairing), "backfill": state.get("backfill")}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    if sum(pairing.values()):       # EPA's file is written back only when it holds a South Carolina record
        epa_doc["meta"] = {**(epa_doc.get("meta") or {}), "sc_des_pairing": {"at": fetched_at, **dict(pairing)}}
        write_json(EPA_EVENTS, epa_doc)
    print(f"{SOURCE_ID}: {stats['rows_read']} rows read ({how}, {took} s), {stats['kept_from_earlier_runs']} kept; "
          f"status {stats['by_status']}; operator row {stats['with_operator_row']}; copies {stats['copies']}; "
          f"EPA {dict(pairing)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
