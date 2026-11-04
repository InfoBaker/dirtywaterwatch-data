"""Virginia DEQ Pollution Response Program (PReP) sewage reports -> data/build/events/va-deq-prep.json.

Source
  DEQ's public pollution-report database, the JSON API behind the PReP search page
  (https://portal.deq.virginia.gov/v2/prep/search): GET
  https://portal.deq.virginia.gov/prep/api/prepReports?sewageRelated=Y&incidentDateTimeFrom=YYYY-MM-DD
  &expand=... (no key; wrapper {offset, limit, count, total, results}). The expansions bring the
  sewage sub-record (/prepReportSewages: duration, volume, structure, cause), the status log
  (/prepReportEvents), the report's categories (release subtypes), DEQ's permit links and the
  original report as filed (typed permit number, facility, responsible company). No coordinates:
  points come from the EDMA layer 175 "PReP Reports (Daily)" (DEQ's geocode of the site address),
  joined on the report id. Fallback when the API is blocked: the ArcGIS export table
  PREP_REPORT_EXPORTALL/MapServer/0 (same reports, flattened, no permit links).
  DEQ's required statement for redistributed data (kept verbatim in meta.attribution and in the
  source registry row): see ATTRIBUTION below. DEQ Terms of Use: poll gently.

Time (three encodings, research/va/sources.json; each decoded here and tested)
  - API: local wall-clock time with no zone ("2026-08-04T19:16:57") -> America/New_York.
  - Export table: epoch milliseconds equal to local wall-clock + 5 hours all year (EST offset
    applied in summer too) -> subtract 5 h, read the result as America/New_York wall clock.
  - EDMA layer 175: epoch milliseconds equal to local wall-clock labelled as UTC -> read the UTC
    wall clock as America/New_York.
  An incident time of exactly 00:00:00 is read as a date-only entry (time_precision "day").

Record rules
  - One record per PReP report: source_record_id = the report id. Rows with sewageRelated=N are
    never asked for. The run asks for incidents of the last 30 days and reports received in the
    last 30 days (catches unknown incident dates and late reports); `--backfill` asks from
    2025-01-01. Records are merged with the previous file (a short window never drops older rows).
  - event_type from the report's category: a site name that names a CSO ("CSO - City of
    Lynchburg", "CSO (OF004) - ...": DEQ has no CSO category) -> cso; a "Bypass Outfall" structure
    or a treatment-plant discharge that DEQ did not file as a sanitary sewer overflow -> bypass;
    category "Sanitary Sewer Overflow" (or a site name beginning "SSO") -> sso; anything else
    (No Pollution Noted, MS4 Related, unauthorised discharge away from a plant ...) -> unknown with
    a note, for review.
  - started_at = incident time; ended_at = the incident end when DEQ gives one, else the start plus
    the sewage record's duration hours (raw._ended_at_basis says which); reported_at = received
    time; source_updated_at = modifiedDate; published_at null (PReP has no publication time; the
    record's creation time is raw.created_in_prep). status: ended when an end is known or DEQ has
    closed the report, ongoing when the original report said "still occurring" and DEQ has not
    closed it, else unknown.
  - Volume: the sewage record's discharge volume (gallons) via parse_volume_gal; else DEQ's
    low/high estimate of the quantity reaching water with its unit (a range stays text).
    -1 is DEQ's "unknown" and is ignored.
  - waterbody_text = the receiving water as typed (receptor, then "other" water); water slugs by
    name within Virginia, checked against the EDMA point (ingest/va_waters.py).
  - npdes_permit: DEQ's own VPDES link on the report; else the permit number typed on the
    original report, unless it is an MS4 (stormwater) permit (DEQ links it as WAT_MS4_IP, the
    facility is named "... MS4", a VAR04 general permit, or a known individual MS4 such as
    Norfolk's VA0088650): an MS4 permit is never taken as the operator's VPDES permit.
  - discharger_id from research/va/dischargers.json by that permit, then by the operator named in
    the site name, facility or responsible company; when the permit and the name point at two
    different operators the record gets none (raw.discharger_match says why).
  - Duplicates: reports sharing an SSORS id, an NRC id, or a street address (with a house number)
    on the same local date are one event; every later report (higher id) gets duplicate_of = the
    earliest report. Two reports at one address that give different volumes are kept apart (an
    operator files one report per manhole: WVWA, 2304 Brambleton Ave SW, 2026-10-11), and so are
    the groups they belong to: a report with no volume never joins a 100-gallon and a 200-gallon one.
  - raw keeps the report's fields with personal fields removed: staff user names (createdBy ...),
    the original report's reporter and contact fields, emails and phones; staff names in free text
    ("Assigned to: ...", DEQ user names) become [name removed]. Saved raw pages are scrubbed the
    same way before they are written.
  - Raw API pages (scrubbed) are saved to data/raw/va-deq-prep/ when their reports changed (id and
    modifiedDate per page, data/build/va-deq-prep-state.json, which also caches the EDMA points).
  - DEQ blocks some automated fetches: requests carry a plain browser User-Agent; a 403 is retried
    after 20 s and 60 s, then the export table is tried; a block is recorded in meta.blocked and
    does not fail the run (the previous records stay).

Run from pipeline/: python -m ingest.va_deq_prep [--backfill] [--days N]
Cadence: hourly (records appear within minutes of a call; DEQ updates volume and cause for weeks).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BROWSER_HEADERS, BUILD_DIR, EVENTS_DIR, ROOT, event, now_iso, parse_volume_gal, read_json,
                    save_raw, scrub_text, write_events, write_json)
from ingest import va_waters

SOURCE_ID = "va-deq-prep"
API = "https://portal.deq.virginia.gov/prep/api/prepReports"
DETAIL_PAGE = "https://portal.deq.virginia.gov/v2/prep/prepReport/{id}"
SEARCH_PAGE = "https://portal.deq.virginia.gov/v2/prep/search"
EXPORT = "https://gisdata.deq.virginia.gov/arcgis/rest/services/public/PREP_REPORT_EXPORTALL/MapServer/0"
EDMA = "https://gisdata.deq.virginia.gov/arcgis/rest/services/public/EDMA/MapServer/175"
EXPAND = ("prepStatusCode,prepUnitTypeCode,prepReportSewages.prepComponentTypeCode,"
          "prepReportSewages.prepSewageCauses.prepCauseCode,prepReportSewages.prepSewageImpacts.prepImpactTypeCode,"
          "prepReportReleaseSubtypes.prepReleaseSubtypeCode,prepReportPermitViews,prepOriginalReport,"
          "prepReportEvents.prepEventTypeCode,prepFipsCode.fipsRegion")
ATTRIBUTION = ("DEQ is the data source. DEQ does not certify that this data represents a complete record. "
               "This data is provided to the citizens of the Commonwealth free of charge and for informational "
               "purposes only.")
TZ = ZoneInfo("America/New_York")
DEFAULT_DAYS = 30
BACKFILL_FROM = date(2025, 1, 1)
PAGE = 100
STATE_PATH = BUILD_DIR / "va-deq-prep-state.json"      # EDMA points by report id, raw page signatures
DISCHARGERS_FILE = ROOT / "research" / "va" / "dischargers.json"
BACKOFF_S = (20, 60)
TIME_NOTE = ("PReP API times are local wall-clock times with no zone, read as America/New_York. The export table "
             "stores local time + 5 h all year (decoded by subtracting 5 h); the EDMA point layer stores local "
             "time labelled as UTC (decoded by reading the UTC clock as local).")

PERMIT_RE = re.compile(r"\b(VA[0-9R]\d{6}|VAR\d{6})\b")
KNOWN_MS4 = {"VA0088650": "City of Norfolk MS4 (cited on PReP sewer-overflow reports)"}
CSO_NAME = re.compile(r"^\s*CSO\b|\bCSO\s*\(?\s*(?:OF|outfall)?\s*#?\d|\bcombined sewer\b", re.I)
PLANT_NAME = re.compile(r"\b(WWTP|WWTF|WRRF|WRF|WPCP|STP|treatment (?:plant|facility|works)|water (?:renewal|reclamation|"
                        r"recycling|pollution control)|headworks|loss of (?:chlorination|disinfection))\b", re.I)
COLLECTION = re.compile(r"\b(manhole|MH|SMH|pump station|lift station|force main|forcemain|gravity (?:main|sewer)|"
                        r"sewer main|sewer line|cleanout|lateral|conveyance|interceptor)\b", re.I)
# Operators named in a report (site name, facility, responsible company) -> research id. Place names
# alone ("SSO - 8521 Executive Dr - Norfolk") are not operator names and match nothing.
OPERATOR_PATTERNS = {
    "va-richmond-dpu": r"\bcity of richmond\b|\brichmond (?:dpu|conveyance|public utilities|utilities|wwtp|cso)\b",
    "va-lynchburg-water-resources": r"\bcity of lynchburg\b|\blynchburg (?:water resources|conveyance|utilities|regional|wwtp)\b",
    "va-alexrenew": r"\balex ?renew\b|\balexandria renew\b|\balexandria sanitation authority\b",
    "va-covington": r"\bcity of covington\b|\bcovington (?:wwtp|stp|conveyance|utilities)\b",
    "va-hrsd": r"\bhampton roads sanitation\b",
    "va-henrico-dpu": r"\bhenrico (?:county )?(?:conveyance|dpu|public utilities|utilities|water reclamation)\b|\bcounty of henrico\b",
    "va-hopewell-water-renewal": r"\bhopewell water renewal\b|\bcity of hopewell\b|\bhopewell conveyance\b",
    "va-wvwa": r"\bwestern virginia water authority\b",
    "va-norfolk-utilities": r"\bcity of norfolk(?: (?:utilities|department of utilities|dpu))?\b(?![- ]*(?:environmental|storm))|\bnorfolk (?:utilities|dpu|conveyance)\b",
    "va-virginia-beach-utilities": r"\bvirginia beach (?:public utilities|utilities|dpu|conveyance)\b|\bcity of virginia beach\b",
    "va-portsmouth": r"\bcity of portsmouth\b|\bportsmouth (?:utilities|public utilities|conveyance)\b",
    "va-newport-news": r"\bcity of newport news\b|\bnewport news (?:public works|wastewater|conveyance)\b",
    "va-fairfax-dpwes": r"\bnoman (?:m\.? )?cole\b|\bfairfax county (?:wastewater|conveyance|sewer|public works)\b",
    "va-arlington-des": r"\barlington (?:county )?(?:DES|conveyance|water pollution control|WPCP|utilities)\b",
    "va-chesterfield-utilities": r"\bchesterfield (?:county )?(?:utilities|conveyance|dpu)\b|\b(?:falling|proctors) creek (?:wwtp|stp)\b",
    "va-tappahannock": r"\btappahannock (?:wwtp|stp|wastewater)\b|\btown of tappahannock\b",
    "va-dickenson-psa": r"\bdickenson county psa\b|\bdickenson (?:county )?public service\b|\bhaysi (?:wwtp|stp)\b",
    "va-front-royal": r"\bfront royal (?:wwtp|stp|conveyance|utilities)\b|\btown of front royal\b",
    "va-alleghany-lower-jackson": r"\blower jackson\b|\balleghany county (?:wwtp|psa|utilities)\b",
    "va-christiansburg": r"\bchristiansburg (?:wwtf|wwtp|conveyance|utilities)\b|\btown of christiansburg\b",
    "va-fredericksburg": r"\bfredericksburg (?:wwtf|wwtp|conveyance|utilities)\b|\bcity of fredericksburg\b",
    "va-bedford": r"\bbedford (?:wwtp|stp|conveyance|utilities)\b|\btown of bedford\b",
    "va-fcwsa-remington": r"\bfauquier county water\b|\bremington (?:wwtp|stp)\b",
}
# Acronyms must be written in capitals (case-sensitive); the patterns above ignore case.
ACRONYMS = {"va-hrsd": r"\bHRSD\b", "va-alexrenew": r"\bASA\b", "va-wvwa": r"\bWVWA\b", "va-fairfax-dpwes": r"\bDPWES\b",
            "va-virginia-beach-utilities": r"\bVBPU\b", "va-fcwsa-remington": r"\bFCWSA\b"}
_OP_RE = {k: [re.compile(v, re.I)] + ([re.compile(ACRONYMS[k])] if k in ACRONYMS else [])
          for k, v in OPERATOR_PATTERNS.items()}


# ---------------------------------------------------------------- time decoding

def api_time(s) -> datetime | None:
    """PReP API: '2026-08-04T19:16:57' (local, no zone) -> aware America/New_York."""
    if not s:
        return None
    dt = datetime.fromisoformat(str(s).strip().replace("Z", ""))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def export_time(ms) -> datetime | None:
    """Export table epoch ms = local wall clock + 5 h (all year) -> aware America/New_York."""
    if ms in (None, ""):
        return None
    wall = datetime(1970, 1, 1) + timedelta(milliseconds=int(ms)) - timedelta(hours=5)
    return wall.replace(tzinfo=TZ)


def edma_time(ms) -> datetime | None:
    """EDMA layer 175 epoch ms = local wall clock labelled as UTC -> aware America/New_York."""
    if ms in (None, ""):
        return None
    wall = datetime(1970, 1, 1) + timedelta(milliseconds=int(ms))
    return wall.replace(tzinfo=TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


# ---------------------------------------------------------------- personal data

_DROP_KEY = re.compile(r"(first|last|middle|full)_?name|phone|e-?mail|fax|cell|title$|contact|created_?by|modified_?by|"
                       r"employee|staff|participant|assigned|signature|^rb[A-Z]|^rp[A-Z]|^sc[A-Z]|^po[A-Z]|accessprovided|"
                       r"onsite|^comment$|emailbody|emailsubject", re.I)
USERNAME_RE = re.compile(r"\b[A-Z][a-z]+\.(?!(?:The|This|That|These|There|They|It|A|An|On|In|At|DEQ|Staff|Flow|Flows|"
                         r"Repairs|Crews|Overflow|Sewage|No|All|Approximately|Estimated)\b)[A-Z][a-z]+(?:-[A-Z][a-z]+)?\b")
ORG_WORDS = re.compile(r"\b(city|county|town|village|authority|utilit|department|dept|district|service|psa|sanitation|"
                       r"water|sewer|wastewater|works|inc|llc|l\.l\.c|corp|company|co\b|ltd|association|assoc|hoa|"
                       r"apartments?|condominium|school|university|college|hospital|church|navy|naval|army|base|"
                       r"plant|facility|station|wwtp|wwtf|stp|wrf|hrsd|wvwa|federal|state|commonwealth|park|campground|"
                       r"hotel|motel|restaurant|center|centre|mall|partners|properties|group|enterprises|"
                       r"management|construction|contractors?|industries|farm|ms4|government|agency)", re.I)


def _org(v) -> str | None:
    """A company or facility name; anything that might be a private person's name is not kept."""
    v = (v or "").strip() if isinstance(v, str) else None
    return v if v and ORG_WORDS.search(v) else None
ASSIGNED_RE = re.compile(r"\b(Assigned (?:to|by)|Prepared by|Reported by|Entered by)\s*:\s*[^,;\n()]+", re.I)


def staff_names(obj, out: set[str] | None = None) -> set[str]:
    """User names in createdBy/modifiedBy fields at any depth ('First.Last', also as 'First Last')."""
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.search(r"(created|modified|assigned|updated)_?by$", str(k), re.I) and isinstance(v, str):
                if USERNAME_RE.fullmatch(v.strip()):
                    out.add(v.strip())
                    out.add(v.strip().replace(".", " "))
            else:
                staff_names(v, out)
    elif isinstance(obj, list):
        for v in obj:
            staff_names(v, out)
    return out


# People named in DEQ's free text: "Ms. Massey", "spoke with <First Last>", "called <First Last>".
HONORIFIC_RE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mx)\.?\s+(?!Utility\b)[A-Z][a-zA-Z'’-]+(?:\s+[A-Z][a-zA-Z'’-]+)?")
VERB_NAME_RE = re.compile(r"\b((?i:spoke|spoken|speaking|talked|talking|met|meeting|called|calling|emailed|e-mailed|"
                          r"texted|contacted|contacting|notified|informed|per|according to|reported by|submitted by|prepared by|"
                          r"left (?:a )?(?:message|voicemail)"
                          r" (?:for|with))\s+(?:(?i:with|to)\s+)?)([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-zA-Z'’-]+)")
NOT_FIRST_NAME = {"The", "DEQ", "VDH", "EPA", "HRSD", "WVWA", "Miss", "Public", "Emergency", "Fire", "Police", "State",
                  "National", "Virginia", "Department", "Health", "Environmental", "Regional", "Town", "City", "County",
                  "Norfolk", "Hampton", "Richmond", "Henrico", "Chesterfield", "Fairfax", "Arlington", "Portsmouth",
                  "Chesapeake", "Suffolk", "Roanoke", "Lynchburg", "Hopewell", "Petersburg", "Alexandria", "Newport",
                  "Virginia Beach", "Water", "Sewer", "Utility", "Utilities", "Operations", "Maintenance", "Staff",
                  "Duty", "Plant", "Facility", "On", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday", "January", "February", "March", "April", "May", "June", "July", "August",
                  "September", "October", "November", "December"}


# "email from Doe, Jane <jdoe@example.org> indicated", "call from John Q. Public (operator)": the person named as
# the other party of a call, e-mail, letter or report; "Last, First" only in that context or beside an e-mail address.
_PERSON = r"(?:[A-Z][a-zA-Z'’-]+,\s+[A-Z][a-zA-Z'’-]+(?:\s+[A-Z]\.)?|[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-zA-Z'’-]+)"
CORRESPONDENCE_RE = re.compile(r"\b((?i:e-?mails?|phone calls?|calls?|letters?|voicemails?|texts?|messages?|reports?|notifications?|"
                               r"conversations?|correspondence|discussions?)\s+(?i:from|with|to|by)\s+)(" + _PERSON +
                               r")(\s*(?:<[^<>\s]+@[^<>\s]+>|\([^()]*@[^()]*\)))?")
NAME_WITH_EMAIL_RE = re.compile(r"\b" + _PERSON + r"\s*(?:<[^<>\s]+@[^<>\s]+>|\([^()]*@[^()]*\))")


def _correspondence(m: re.Match) -> str:
    who = m.group(2)
    first = who.split(",")[-1].split()[0] if "," in who else who.split()[0]
    if ORG_WORDS.search(who) or first in NOT_FIRST_NAME or who.split()[0] in NOT_FIRST_NAME or re.search(
            r"(?i)septic|plumbing|pumping|services?|excavat|electric|engineer|consult|hauling|rooter|roto", who):
        return m.group(0)
    return f"{m.group(1)}[name removed]"


def _verb_name(m: re.Match) -> str:
    who = m.group(2)
    if ORG_WORDS.search(who) or who.split()[0] in NOT_FIRST_NAME or re.search(
            r"(?i)septic|plumbing|pumping|services?|excavat|electric|engineer|consult|hauling|rooter|roto", who):
        return m.group(0)
    return f"{m.group(1)}[name removed]"


def scrub_free(s, names: set[str] = frozenset()):
    if not isinstance(s, str):
        return s
    for n in sorted(names, key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(n)}\b", "[name removed]", s, flags=re.I)
    s = ASSIGNED_RE.sub(lambda m: f"{m.group(1)}: [name removed]", s)
    s = USERNAME_RE.sub("[name removed]", s)
    s = HONORIFIC_RE.sub("[name removed]", s)
    s = VERB_NAME_RE.sub(_verb_name, s)
    s = CORRESPONDENCE_RE.sub(_correspondence, s)
    s = NAME_WITH_EMAIL_RE.sub("[name removed]", s)
    return scrub_text(s)


def scrub_obj(obj, names: set[str] = frozenset()):
    """A copy of an API/export object without personal keys, with names, emails and phones scrubbed
    from strings (used for the saved raw pages and the record's raw)."""
    if isinstance(obj, dict):
        return {k: scrub_obj(v, names) for k, v in obj.items() if not _DROP_KEY.search(str(k))}
    if isinstance(obj, list):
        return [scrub_obj(v, names) for v in obj]
    return scrub_free(obj, names)


# ---------------------------------------------------------------- normalising one report

def _ids(v) -> list[str]:
    return [x for x in re.split(r"[,;/\s]+", str(v or "")) if re.fullmatch(r"\d{4,}", x)]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f or f < 0 else (int(f) if f == int(f) else f)


def _yn(v):
    return v if v in ("Y", "N") else None


def from_api(r: dict) -> dict:
    """The fields this module uses, from one API report (with the expansions in EXPAND)."""
    names = staff_names(r)
    orig = r.get("prepOriginalReport") or {}
    fips = r.get("prepFipsCode") or {}
    sew = []
    for s in r.get("prepReportSewages") or []:
        sew.append({
            "duration_h": _num(s.get("duration")), "component": (s.get("prepComponentTypeCode") or {}).get("description"),
            "component_id": s.get("componentTypeId"),
            "volume_gal": s.get("dischargeVolume"), "volume_unknown": _yn(s.get("dischargeUnknown")),
            "wet_weather": _yn(s.get("conditionsWet")), "treated": _yn(s.get("dischargeTreated")),
            "precipitation_in": s.get("precipitationAmount"),
            "causes": [(c.get("prepCauseCode") or {}).get("description") or c.get("otherDescription")
                       for c in s.get("prepSewageCauses") or []],
            "impacts": [(c.get("prepImpactTypeCode") or {}).get("description") or c.get("otherDescription")
                        for c in s.get("prepSewageImpacts") or []],
            "corrective_action": scrub_free(s.get("correctiveAction"), names),
            "steps_taken": scrub_free(s.get("stepsTaken"), names),
            "component_comment": scrub_free(s.get("componentComment"), names),
            "other_cause": scrub_free(s.get("otherCauseDesc"), names),
        })
    log = []
    for e in r.get("prepReportEvents") or []:
        log.append({"at": e.get("eventDate"), "type": (e.get("prepEventTypeCode") or {}).get("description") or e.get("eventTypeId")})
    log.sort(key=lambda x: x["at"] or "")
    return {
        "id": str(r.get("id")), "via": "api",
        "incident": r.get("incidentDateTime"), "incident_end": r.get("incidentEndDateTime"),
        "received": r.get("receivedDateTime"), "created": r.get("createdDate"), "modified": r.get("modifiedDate"),
        "closed": r.get("incidentClosureDate"), "date_unknown": r.get("isIncidentDateUnknown") == "Y",
        "site_name": r.get("siteName"), "address": r.get("siteAddress1"), "city": r.get("siteCity"),
        "zip": r.get("siteZipCode"), "county_city": fips.get("description"),
        "region": (fips.get("fipsRegion") or {}).get("regionName"),
        "status_text": (r.get("prepStatusCode") or {}).get("description"),
        "categories": [x["prepReleaseSubtypeCode"]["name"] for x in r.get("prepReportReleaseSubtypes") or []
                       if (x.get("prepReleaseSubtypeCode") or {}).get("name")],
        "waterbody": r.get("receptorWaterbodyId"), "other_waterbody": r.get("otherWaterbodyDesc"),
        "original_waterbody": orig.get("impactThreatWaterbodyName"), "water_threatened": _yn(r.get("isImpactThreatWaterbody")),
        "low": r.get("receptorEstimateLow"), "high": r.get("receptorEstimateHigh"),
        "unit": (r.get("prepUnitTypeCode") or {}).get("description") or ({9: "Gallons"}.get(r.get("receptorUnitTypeId"))),
        "sewage": sew,
        "ssors": (str(r["ssorsId"]).strip() or None) if r.get("ssorsId") else None, "nrc": _ids(r.get("nrcId")),
        "vdem": r.get("vdemId"), "epa": r.get("epaId"),
        "permit_views": [{"type": v.get("type"), "text": v.get("linkText")} for v in r.get("prepReportPermitViews") or []],
        "typed_permit": orig.get("permitId"), "facility_name": _org(orig.get("facilityName")),
        "facility_permitted": _yn(orig.get("facilityPermitted")), "responsible_company": _org(orig.get("rpCompanyName")),
        "still_occurring": _yn(orig.get("stillOccurring")),
        "status_log": log,
        "text": {"incident_comment": scrub_free(r.get("incidentComment"), names),
                 "location_comment": scrub_free(r.get("locationComment"), names),
                 "closure_comment": scrub_free(r.get("closureComment"), names)},
    }


def _types(s) -> list[str]:
    """'Risk Tier 3 (RT3), Sanitary Sewer Overflow (SSO)' -> ['Risk Tier 3', 'Sanitary Sewer Overflow']."""
    return [re.sub(r"\s*\([A-Z0-9]{2,4}\)\s*$", "", p).strip() for p in re.split(r",\s*(?=[A-Z])", s or "") if p.strip()]


def from_export(a: dict) -> dict:
    """The same fields from one export-table row (times decoded from the +5 h encoding)."""
    def t(k):
        return iso(export_time(a.get(k)))
    fips = str(a.get("FIPS_CITY_COUNTY") or "")
    sew_keys = [k for k in a if k.startswith("SEWAGE_INFO_")]
    sew = []
    if any(a.get(k) not in (None, "") for k in sew_keys):
        sew.append({
            "duration_h": _num(a.get("SEWAGE_INFO_DURATION_OF_EVENT_HRS")), "component": a.get("SEWAGE_INFO_SYSTEM_STRUCTURE"),
            "component_id": None, "volume_gal": a.get("SEWAGE_INFO_DISCHARGE_VOLUMN_GALLONS"), "volume_unknown": None,
            "wet_weather": _yn(a.get("SEWAGE_INFO_WET_WEATHER_EVENT")), "treated": _yn(a.get("SEWAGE_INFO_DISCHARGE_TREATED")),
            "precipitation_in": a.get("SEWAGE_INFO_PRECIPITATION_INCHES"),
            "causes": [x for x in [a.get("SEWAGE_INFO_CAUSE_OF_EVENT")] if x],
            "impacts": [x for x in [a.get("SEWAGE_INFO_IMPACTS")] if x],
            "corrective_action": scrub_free(a.get("SEWAGE_INFO_CORRECTIVE_ACTION_TAKEN")),
            "steps_taken": scrub_free(a.get("SEWAGE_INFO_STEPS_TAKEN")),
            "component_comment": scrub_free(a.get("SEWAGE_INFO_OTHER_TYPE_OF_STRUCTURE")), "other_cause": None,
        })
    return {
        "id": str(a.get("IR_NUMBER")), "via": "export",
        "incident": t("INCIDENT_DATE_TIME"), "incident_end": None, "received": t("RECEIVED_DATE_TIME"),
        "created": None, "modified": None, "closed": t("CLOSURE_DATE"),
        "date_unknown": a.get("ORIGINAL_REPORT_INCIDENT_DATE_UNKNOWN") == "Y" and not a.get("INCIDENT_DATE_TIME"),
        "site_name": a.get("INCIDENT_NAME"), "address": a.get("INCIDENT_ADDRESS_1"), "city": a.get("INCIDENT_CITY"),
        "zip": a.get("INCIDENT_ZIP_CODE"), "county_city": fips.split("/", 1)[1] if "/" in fips else (fips or None),
        "region": a.get("DEQ_REGION"), "status_text": a.get("IR_DESCRIPTION_STATUS"),
        "categories": _types(a.get("INCIDENT_TYPES")),
        "waterbody": a.get("WATERBODY"), "other_waterbody": a.get("OTHER_WATERBODY_RECEPTOR"),
        "original_waterbody": a.get("ORIGINAL_REPORT_WATERBODY"), "water_threatened": None,
        "low": a.get("LOW_QUANTITY_TO_WATER"), "high": a.get("HIGH_QUANTITY_TO_WATER"), "unit": a.get("QUANTITY_UNITS"),
        "sewage": sew, "ssors": (str(a["SSORS_ID"]).strip() or None) if a.get("SSORS_ID") else None,
        "nrc": _ids(a.get("NRC_ID")), "vdem": a.get("VDEM_NUMBER"), "epa": a.get("EPA_ID"),
        "permit_views": [], "typed_permit": a.get("ORIGINAL_REPORT_PERMIT_NUMBER"),
        "facility_name": _org(a.get("ORIGINAL_REPORT_FACILITY_NAME")), "facility_permitted": _yn(a.get("ORIGINAL_REPORT_PERMITTED")),
        "responsible_company": None, "still_occurring": _yn(a.get("ORIGINAL_REPORT_IS_INCIDENT_STILL_OCCURING")),
        "status_log": [],
        "text": {"incident_comment": scrub_free(a.get("FOLLOW_UP_SUMMARY_OF_INCIDENT_DETAILS")),
                 "location_comment": scrub_free(a.get("DETAILED_LOCATION_DESCRIPTION")),
                 "closure_comment": scrub_free(a.get("CLOSURE_COMMENTS"))},
    }


# ---------------------------------------------------------------- classification

def classify(rep: dict) -> tuple[str, str]:
    """(event_type, basis) from the report's category, structure and site name."""
    name = rep.get("site_name") or ""
    cats = [c for c in rep.get("categories") or []]
    lc = " | ".join(cats).lower()
    comps = " | ".join(s.get("component") or "" for s in rep.get("sewage") or [])
    sso_cat = "sanitary sewer overflow" in lc
    if CSO_NAME.search(name):
        return "cso", f"site name names a combined sewer overflow (DEQ category: {', '.join(cats) or 'none'})"
    if re.search(r"bypass", comps, re.I) or re.search(r"\bbypass", name, re.I):
        return "bypass", f"bypass structure or site name (structure: {comps or 'none'})"
    sso_name = bool(re.match(r"\s*SSO\b", name)) and "no pollution noted" not in lc
    if sso_cat:
        return "sso", "DEQ category Sanitary Sewer Overflow"
    if sso_name and "unauthorized discharge" not in lc:
        return "sso", f"site name begins 'SSO' (DEQ category: {', '.join(cats) or 'none'})"
    if PLANT_NAME.search(name) and "no pollution noted" not in lc:
        return "bypass", f"treatment-plant discharge not filed as a sanitary sewer overflow (category: {', '.join(cats) or 'none'})"
    if sso_name:
        return "sso", f"site name begins 'SSO' (DEQ category: {', '.join(cats) or 'none'})"
    return "unknown", f"DEQ category {', '.join(cats) or 'none'} is not a sewer-overflow category"


def _norm_permit(v) -> str | None:
    m = PERMIT_RE.search(re.sub(r"\s+", "", str(v or "")).upper())
    return m.group(1) if m else None


def permit_choice(rep: dict) -> tuple[str | None, dict]:
    """(VPDES permit or None, notes). An MS4 permit is never the operator's VPDES permit."""
    views = rep.get("permit_views") or []
    vpdes = []
    for v in views:
        p = _norm_permit(v.get("text"))
        if (v.get("type") or "").upper() == "WAT_VPDES" and p and p not in vpdes:
            vpdes.append(p)
    ms4_links = [v for v in views if "MS4" in (v.get("type") or "").upper() or re.search(r"\bMS4\b", v.get("text") or "")]
    typed = _norm_permit(rep.get("typed_permit"))
    why_ms4 = None
    if typed:
        if typed in KNOWN_MS4:
            why_ms4 = f"known MS4 permit: {KNOWN_MS4[typed]}"
        elif typed.startswith("VAR04"):
            why_ms4 = "VAR04 general MS4 permit"
        elif re.search(r"\bMS4\b", rep.get("facility_name") or ""):
            why_ms4 = "the report's facility is an MS4"
        elif ms4_links and typed not in vpdes:
            why_ms4 = "DEQ links the report to an MS4 permit (" + ", ".join(
                f"{v.get('type')} {v.get('text')}" for v in ms4_links) + ")"
    notes = {"typed_permit": typed, "deq_vpdes_links": vpdes or None, "ms4": why_ms4,
             "ms4_links": [f"{v.get('type')}: {v.get('text')}" for v in ms4_links] or None}
    if vpdes:
        notes["basis"] = "DEQ's VPDES link on the report"
        if len(vpdes) > 1:
            notes["note"] = f"{len(vpdes)} VPDES links; the first is used"
        return vpdes[0], notes
    if typed and not why_ms4:
        notes["basis"] = "permit number on the original report"
        return typed, notes
    notes["basis"] = "none" if not typed else "typed permit is an MS4 permit: not used as the VPDES permit"
    return None, notes


# ---------------------------------------------------------------- dischargers

def load_dischargers(path=DISCHARGERS_FILE) -> tuple[dict, dict]:
    """({permit: research row}, {id: research row})."""
    rows = read_json(path, []) or []
    by_permit, by_id = {}, {}
    for r in rows:
        by_id[r["id"]] = r
        for p in PERMIT_RE.findall(str(r.get("npdes_permit") or "")):
            by_permit.setdefault(p, r)
    return by_permit, by_id


def operators_named(*texts) -> list[str]:
    hits = []
    for t in texts:
        if not t:
            continue
        for did, rx in _OP_RE.items():
            if any(x.search(t) for x in rx) and did not in hits:
                hits.append(did)
    return hits


def discharger_for(rep: dict, permit: str | None, refs: tuple[dict, dict]) -> tuple[str | None, str | None, dict]:
    by_permit, by_id = refs
    p_row = by_permit.get(permit) if permit else None
    named = operators_named(rep.get("site_name"), rep.get("facility_name"), rep.get("responsible_company"))
    note = {"by_permit": p_row["id"] if p_row else None, "by_name": named or None}
    if p_row and named and p_row["id"] not in named:
        note["result"] = (f"permit {permit} is {p_row['id']} but the report names {', '.join(named)}: "
                          "no discharger set (review)")
        return None, None, note
    if p_row:
        note["result"] = "by permit"
        return p_row["id"], p_row.get("name"), note
    if len(named) == 1 and named[0] in by_id:
        note["result"] = "by operator name in the report"
        return named[0], by_id[named[0]].get("name"), note
    if len(named) > 1:
        note["result"] = "several operators named: none set"
    return None, None, note


# ---------------------------------------------------------------- one record

def _volume(rep: dict) -> tuple[int | None, str | None, str, str | None]:
    """(gallons, text, estimate_flag, basis)."""
    for s in rep.get("sewage") or []:
        v = _num(s.get("volume_gal"))
        if v is not None and v > 0:
            gal, flag = parse_volume_gal(v)
            return gal, f"{v:,} gallons", ("unknown" if s.get("volume_unknown") == "Y" else flag), \
                "sewage report discharge volume (gallons)"
    low, high, unit = _num(rep.get("low")), _num(rep.get("high")), (rep.get("unit") or "").strip()
    u = unit or "(unit not given)"
    if low in (0, 1) and high in (None, 0, 1):
        low = high = None          # DEQ's placeholders (low 1 / high -1) for "not known"
    if low is None and high is None:
        return None, None, "unknown", None
    if low is not None and high is not None and low != high:
        text = f"up to {high:,} {u}" if low in (0, 1) else f"{low:,}-{high:,} {u}"
    else:
        text = f"{(high if high is not None else low):,} {u}"
    text += " to water (DEQ estimate)"
    if unit.lower() != "gallons":
        return None, text, "estimated", "DEQ estimate of the quantity reaching water; unit is not gallons"
    gal, _ = parse_volume_gal(text.replace(" to water (DEQ estimate)", "").replace(" Gallons", " gallons"))
    return gal, text, "estimated", "DEQ estimate of the quantity reaching water"


def _material(rep: dict) -> str:
    treated = {s.get("treated") for s in rep.get("sewage") or []}
    if "N" in treated:
        return "untreated sewage"
    if "Y" in treated:
        return "sewage (reported as treated or partly treated)"
    return "sewage"


def _outfall(name: str | None) -> str | None:
    m = re.search(r"\b(?:OF|outfall)\s*#?\s*0*(\d{1,3})\b", name or "", re.I)
    return f"{int(m.group(1)):03d}" if m else None


def to_record(rep: dict, refs: tuple, point: dict | None, fetched_at: str) -> dict:
    problems = []
    etype, etype_basis = classify(rep)
    if etype == "unknown":
        problems.append(f"not a sewer-overflow category ({etype_basis}); kept for review")
    try:
        start = None if rep.get("date_unknown") else api_time(rep.get("incident"))
        received = api_time(rep.get("received"))
        modified = api_time(rep.get("modified"))
        end = api_time(rep.get("incident_end"))
    except ValueError as e:
        start = received = modified = end = None
        problems.append(f"time not read: {e}")
    precision = None
    if start:
        precision = "day" if (start.hour, start.minute, start.second) == (0, 0, 0) else "minute"
    end_basis = "incidentEndDateTime" if end else None
    durations = [s.get("duration_h") for s in rep.get("sewage") or [] if isinstance(s.get("duration_h"), (int, float))]
    if end is None and start and precision == "minute" and durations and 0 < durations[0] <= 24 * 60:
        end = (start.astimezone(UTC) + timedelta(hours=durations[0])).astimezone(TZ)
        end_basis = f"incident time + duration {durations[0]} h (sewage report)"
    if end and start and end < start:
        problems.append("end before start")
    closed = (rep.get("status_text") or "").lower() == "closed"
    if end:
        status = "ended"
    elif closed:
        status = "ended"
    elif rep.get("still_occurring") == "Y" and etype != "unknown":
        status = "ongoing"          # an unclassified report never says a discharge is going on
    else:
        status = "unknown"
    permit, permit_note = permit_choice(rep)
    did, dname, d_note = discharger_for(rep, permit, refs)
    gal, vtext, eflag, vbasis = _volume(rep)
    wb = [w for w in (rep.get("waterbody"), rep.get("other_waterbody")) if w and str(w).strip()]
    if not wb and rep.get("original_waterbody"):
        wb = [rep["original_waterbody"]]
    waterbody_text = "; ".join(str(w).strip() for w in wb) or None
    lat = lon = None
    if point:
        lat, lon = point.get("lat"), point.get("lon")
    towns = [t for t in (rep.get("city"), rep.get("county_city")) if t]
    slugs, wnotes = va_waters.match_waters(waterbody_text, towns, (lon, lat) if lat is not None else None)
    water_match = "name" if slugs else "none"
    outfall = _outfall(rep.get("site_name")) if etype == "cso" else None
    eo = va_waters.echo_outfall(permit, outfall) if permit and outfall else None
    if eo and eo.get("water_slug") and not slugs:
        slugs, water_match = [eo["water_slug"]], "outfall_registry"
    authority = "Virginia DEQ Pollution Response Program (PReP)"
    if rep.get("region"):
        authority += f", {rep['region']} Regional Office"
    raw = {
        "report": {k: rep.get(k) for k in ("id", "via", "incident", "incident_end", "received", "closed", "modified",
                                             "date_unknown", "site_name", "address", "city", "zip", "county_city",
                                             "region", "status_text", "categories", "waterbody", "other_waterbody",
                                             "original_waterbody", "water_threatened", "low", "high", "unit",
                                             "ssors", "nrc", "vdem", "epa", "facility_name", "facility_permitted",
                                             "responsible_company", "still_occurring")},
        "text": rep.get("text"), "sewage": rep.get("sewage"), "status_log": rep.get("status_log") or None,
        "created_in_prep": rep.get("created"),
        "event_type_basis": etype_basis, "permit": permit_note, "discharger_match": d_note,
        "volume_basis": vbasis, "_ended_at_basis": end_basis, "_time_basis": TIME_NOTE,
        "water_placement": {"text": waterbody_text, "towns": towns, "notes": wnotes or None,
                            "echo_outfall": eo.get("outfall") if eo else None},
        "point": point, "attribution": ATTRIBUTION,
        "api_url": f"{API}/{rep.get('id')}?expand={EXPAND}",
    }
    return event(
        source_id=SOURCE_ID, source_record_id=rep["id"], event_type=etype, status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=permit,
        outfall_id=outfall, outfall_name=None,
        waterbody_text=waterbody_text, water_slugs=slugs, water_match=water_match,
        lat=lat, lon=lon, coord_source="geocode" if lat is not None else None, coord_precision_m=None,
        started_at=iso(start), ended_at=iso(end), time_precision=precision,
        reported_at=iso(received), published_at=None, source_updated_at=iso(modified), fetched_at=fetched_at,
        material=_material(rep), volume_gal=gal, volume_text=vtext, estimate_flag=eflag,
        authority=authority, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        source_url=DETAIL_PAGE.format(id=rep["id"]), raw=raw,
        parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- duplicates

def _addr_key(rec: dict) -> str | None:
    rep = (rec.get("raw") or {}).get("report") or {}
    a = re.sub(r"[^a-z0-9 ]", "", (rep.get("address") or "").lower()).strip()
    a = re.sub(r"\b(street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd|court|ct)\b", "", a)
    a = re.sub(r"\s+", " ", a).strip()
    day = (rec.get("started_at") or "")[:10]
    return f"{a}|{day}" if re.match(r"[1-9]\d*\s+[a-z]", a) and day else None


def mark_duplicates(records: list[dict]) -> int:
    """Reports sharing an SSORS id, an NRC id, or a street address on the same date are one event:
    each later report (higher id) gets duplicate_of = the earliest report's event_id. Returns the
    number of records marked."""
    parent = {r["event_id"]: r["event_id"] for r in records}
    why: dict[str, set] = {}
    # the volumes each group holds (by its root): an address match never joins two groups whose volumes differ,
    # so A (100 gal), B (no volume) and C (200 gal) at one address and date do not become one event through B
    # (review 2026-11-03 P3-8)
    vols = {r["event_id"]: ({r["volume_gal"]} if r.get("volume_gal") is not None else set()) for r in records}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def key_num(eid):
        tail = eid.split(":", 1)[1]
        return (0, int(tail)) if tail.isdigit() else (1, tail)

    def union(x, y, k, by_volume: bool = False) -> bool:
        a, b = find(x), find(y)
        if by_volume and a != b and vols[a] and vols[b] and vols[a] != vols[b]:
            return False
        if a != b:
            lo, hi = sorted((a, b), key=key_num)
            parent[hi] = lo
            vols[lo] = vols[a] | vols[b]
        why.setdefault(x, set()).add(k)
        why.setdefault(y, set()).add(k)
        return True

    seen: dict[str, str] = {}
    by_addr: dict[str, list[dict]] = {}
    for r in records:
        rep = (r.get("raw") or {}).get("report") or {}
        keys = []
        if rep.get("ssors"):
            keys.append(f"SSORS {rep['ssors']}")
        keys += [f"NRC {n}" for n in rep.get("nrc") or []]
        for k in keys:
            if k in seen:
                union(seen[k], r["event_id"], k)
            else:
                seen[k] = r["event_id"]
        ak = _addr_key(r)
        if ak:
            by_addr.setdefault(ak, []).append(r)
    # same street address on the same date: one event, unless the two reports, or the groups they already belong
    # to, give different volumes (an operator filing one report per manhole at one address, e.g. WVWA 2026-10-11)
    for ak, rs in by_addr.items():
        for i, x in enumerate(rs):
            for y in rs[i + 1:]:
                union(x["event_id"], y["event_id"], f"address+date {ak}", by_volume=True)
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(find(r["event_id"]), []).append(r)
    n = 0
    for root, members in groups.items():
        members.sort(key=lambda r: key_num(r["event_id"]))
        first = members[0]
        first["duplicate_of"] = None
        first["raw"].pop("duplicate_basis", None)
        if len(members) == 1:
            first["raw"].pop("duplicates", None)
            continue
        first["raw"]["duplicates"] = [m["event_id"] for m in members[1:]]
        for m in members[1:]:
            m["duplicate_of"] = first["event_id"]
            m["raw"]["duplicate_basis"] = sorted(why.get(m["event_id"], set()))
            m["raw"].pop("duplicates", None)
            n += 1
    return n


# ---------------------------------------------------------------- fetching

class Blocked(Exception):
    pass


def _get(sess: requests.Session, url: str, params: dict, meta: dict, sleep=time.sleep, timeout: int = 120):
    """GET with backoff on 403 (20 s, then 60 s); raises Blocked when DEQ keeps refusing."""
    for i, wait in enumerate((0,) + BACKOFF_S):
        if wait:
            sleep(wait)
        r = sess.get(url, params=params, timeout=timeout)
        if r.status_code == 403:
            meta.setdefault("http_403", []).append({"url": url, "at": now_iso(), "attempt": i + 1})
            continue
        r.raise_for_status()
        return r
    raise Blocked(f"403 from {url} after {len(BACKOFF_S) + 1} attempts")


def fetch_api(sess, params: dict, meta: dict, sleep=time.sleep, raw_sigs: dict | None = None) -> list[dict]:
    """All pages of one query. A page is saved to data/raw/ only when its reports (id + modifiedDate)
    differ from the last saved copy of that page."""
    out, offset, total = [], 0, None
    raw_sigs = {} if raw_sigs is None else raw_sigs
    while True:
        q = {"orderBy": "id desc", "limit": PAGE, "offset": offset, "sewageRelated": "Y", "expand": EXPAND, **params}
        r = _get(sess, API, q, meta, sleep)
        d = r.json()
        if not isinstance(d, dict) or "results" not in d:
            raise ValueError(f"unexpected API answer: {str(d)[:200]}")
        page = d.get("results") or []
        total = d.get("total") if total is None else total
        names = staff_names(page)
        key = f"api-{_slug(params)}-{offset}"
        sig = json.dumps([(x.get("id"), x.get("modifiedDate")) for x in page])
        if raw_sigs.get(key) != sig:
            save_raw(SOURCE_ID, json.dumps(scrub_obj(d, names), ensure_ascii=False), f"{key}.json")
            raw_sigs[key] = sig
        out.extend(page)
        offset += len(page)
        if not page or offset >= (total or 0):
            return out
        sleep(1)


def _slug(params: dict) -> str:
    return "-".join(f"{k}{v}" for k, v in sorted(params.items())).replace(":", "")[:80]


def fetch_export(sess, since: date, meta: dict, sleep=time.sleep) -> list[dict]:
    # stored as local + 5 h: local midnight of `since` is 05:00 in the stored clock
    where = f"SEWAGE_RELATED='Y' AND INCIDENT_DATE_TIME >= TIMESTAMP '{since:%Y-%m-%d} 05:00:00'"
    out, offset = [], 0
    while True:
        r = _get(sess, EXPORT + "/query", {"where": where, "outFields": "*", "orderByFields": "OBJECTID",
                                           "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}, meta, sleep)
        d = r.json()
        if "error" in d:
            raise ValueError(f"export table: {d['error']}")
        feats = d.get("features") or []
        save_raw(SOURCE_ID, json.dumps(scrub_obj(d), ensure_ascii=False), f"export-{since:%Y%m%d}-{offset}.json")
        out.extend(f.get("attributes") or {} for f in feats)
        offset += len(feats)
        if not feats or not d.get("exceededTransferLimit"):
            return out
        sleep(1)


def fetch_points(sess, ids: list[str], meta: dict, sleep=time.sleep) -> dict[str, dict]:
    out = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        where = "PRP_REPORT_ID IN (" + ",".join(f"'{x}'" for x in chunk) + ")"
        r = _get(sess, EDMA + "/query", {"where": where, "outFields": "PRP_REPORT_ID,REFERENCE_POINT,PRP_INCIDENT_DATE_TIME,"
                                         "PRP_REPORT_RECEIVED_DATE_TIME,PRP_SITE_ADDRESS1,PRP_SITE_CITY",
                                         "outSR": 4326, "returnGeometry": "true", "f": "json"}, meta, sleep, timeout=90)
        d = r.json()
        if "error" in d:
            raise ValueError(f"EDMA layer 175: {d['error']}")
        save_raw(SOURCE_ID, json.dumps(d, ensure_ascii=False), f"edma175-{i}.json")
        for f in d.get("features") or []:
            out.update(point_from_edma(f))
        if i + 100 < len(ids):
            sleep(1)
    return out


def point_from_edma(feature: dict) -> dict[str, dict]:
    a, g = feature.get("attributes") or {}, feature.get("geometry") or {}
    rid = str(a.get("PRP_REPORT_ID") or "")
    if not rid or g.get("x") is None:
        return {}
    return {rid: {"lat": round(g["y"], 6), "lon": round(g["x"], 6), "layer": "DEQ EDMA layer 175 (PReP Reports, Daily)",
                  "reference_point": a.get("REFERENCE_POINT"),
                  "note": "DEQ's geocode of the report's site address (REFERENCE_POINT 'PG'), not an outfall point",
                  "edma_incident": iso(edma_time(a.get("PRP_INCIDENT_DATE_TIME"))),
                  "edma_received": iso(edma_time(a.get("PRP_REPORT_RECEIVED_DATE_TIME")))}}


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="incidents from 2025-01-01")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    today = datetime.now(TZ).date()
    since = BACKFILL_FROM if args.backfill else today - timedelta(days=args.days)
    recent = today - timedelta(days=args.days)
    sess = requests.Session()
    sess.headers.update({**BROWSER_HEADERS, "Accept": "application/json, text/plain, */*"})
    prev = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    meta: dict = {"attribution": ATTRIBUTION, "terms": "https://www.deq.virginia.gov/news-info/about-us/terms-of-use",
                  "portal": SEARCH_PAGE, "api": API, "timezone_note": TIME_NOTE,
                  "window": {"incidents_from": since.isoformat(), "received_from": recent.isoformat()},
                  "registry_ids": ["va-deq-prep-api", "va-deq-prep-export-mapserver", "va-deq-edma-prep-daily-points"]}
    state = read_json(STATE_PATH, None) or read_json(BUILD_DIR / "va-deq-prep-points.json", {}) or {}
    raw_sigs = state.setdefault("raw_sigs", {})
    reps: dict[str, dict] = {}
    via, errors = "api", []
    try:
        for params in ({"incidentDateTimeFrom": since.isoformat()},
                       {"receivedDateTimeFrom": recent.isoformat()},
                       *(({"receivedDateTimeFrom": since.isoformat(), "isIncidentDateUnknown": "Y"},) if args.backfill else ())):
            for r in fetch_api(sess, params, meta, raw_sigs=raw_sigs):
                reps[str(r.get("id"))] = from_api(r)
    except Blocked as e:
        meta["blocked"] = {"at": now_iso(), "what": "PReP API", "error": str(e)}
        via = "export"
    except Exception as e:  # noqa: BLE001
        errors.append(f"API: {type(e).__name__}: {e}")
        via = "export"
    if via == "export":
        reps = {}
        try:
            for a in fetch_export(sess, since, meta):
                reps[str(a.get("IR_NUMBER"))] = from_export(a)
        except Blocked as e:
            meta.setdefault("blocked", {}).update({"export": str(e)})
        except Exception as e:  # noqa: BLE001
            errors.append(f"export: {type(e).__name__}: {e}")
    if not reps:
        err = "; ".join(errors) or (meta.get("blocked") or {}).get("error") or "no reports fetched"
        write_events(SOURCE_ID, [], ok=False, error=err, meta=meta)
        print(f"{SOURCE_ID}: nothing fetched ({err}); previous records kept", file=sys.stderr)
        return 0 if meta.get("blocked") else 1
    meta["via"] = via

    points, missing = state.setdefault("points", {}), state.setdefault("missing", {})
    prev_by_id = {r["event_id"]: r for r in prev.get("records", [])}
    for r in prev_by_id.values():  # points kept on earlier records
        if r.get("lat") is not None and r["source_record_id"] not in points:
            points[r["source_record_id"]] = (r.get("raw") or {}).get("point") or {"lat": r["lat"], "lon": r["lon"]}
    cutoff = (datetime.now(UTC) - timedelta(hours=20)).isoformat()
    want = [i for i in reps if i not in points and (missing.get(i) or "") < cutoff]
    try:
        got = fetch_points(sess, want, meta) if want else {}
        points.update(got)
        for i in want:
            if i not in got:
                missing[i] = now_iso()
            else:
                missing.pop(i, None)
    except Exception as e:  # noqa: BLE001
        errors.append(f"EDMA points: {type(e).__name__}: {e}")
    write_json(STATE_PATH, {"updated": now_iso(), "layer": EDMA, "points": points, "missing": missing, "raw_sigs": raw_sigs})

    refs = load_dischargers()
    fresh = [to_record(rep, refs, points.get(i), fetched_at) for i, rep in reps.items()]
    by_id = dict(prev_by_id)
    for rec in fresh:
        old = by_id.get(rec["event_id"])
        if via == "export" and old and (old.get("raw") or {}).get("report", {}).get("via") == "api":
            continue  # an API record is richer than the export row of the same report
        by_id[rec["event_id"]] = rec
    for rec in by_id.values():  # points that arrived after the record was written
        pt = points.get(rec["source_record_id"])
        if pt and rec.get("lat") is None:
            rec["lat"], rec["lon"], rec["coord_source"] = pt["lat"], pt["lon"], "geocode"
            rec["raw"]["point"] = pt
    records = sorted(by_id.values(), key=lambda r: (r.get("started_at") or r.get("reported_at") or ""), reverse=True)
    n_dup = mark_duplicates(records)
    c = Counter(r["event_type"] for r in records)
    meta.update({"fetched_reports": len(reps), "records_total": len(records), "duplicates_marked": n_dup,
                 "by_type": dict(c), "with_point": sum(1 for r in records if r.get("lat") is not None),
                 "with_water_slug": sum(1 for r in records if r.get("water_slugs")),
                 "errors": errors or None, "statewide": True})
    path = write_events(SOURCE_ID, records, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"{SOURCE_ID}: {len(reps)} reports via {via} ({since}..); {len(records)} records {dict(c)}; "
          f"{n_dup} duplicates; {meta['with_point']} with a point -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
