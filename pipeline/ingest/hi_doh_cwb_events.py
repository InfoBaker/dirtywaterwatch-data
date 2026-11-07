"""Hawaii Department of Health, Clean Water Branch: water quality advisories and events -> data/build/events/hi-doh-cwb-events-api.json

Source
  The Clean Water Branch's public portal (https://eha-cloud.doh.hawaii.gov/cwb/) draws every advisory it issues from
  one JSON endpoint, https://eha-cloud.doh.hawaii.gov/cwb/api/events, asked with "Accept: application/json" (without
  it the host answers an HTML snapshot). No key, no cookie needed. The answer is {page, totalResultsCount, list}: the
  newest 500 events (2023-01-01 to the read; 1,901 events in all on 2026-11-07); the page, skip and take parameters are
  ignored (research of 2026-11-03), so older history is not read. The endpoint is undocumented and states no terms or
  licence: it is read once an hour, politely, and the licence question is the owner's (research/hi/sources.json).
  Law: HAR 11-62 Appendix B (the owner or agent of a wastewater system reports spills, overflows and discharges to the
  Clean Water Branch) and HAR 11-55 (NPDES; the permits' standard conditions). The Department, not the operator, tells
  the public: the advisory on this portal, signs at the water, e-mail notices by island, news releases for large
  spills. No operator duty to tell the public directly was found.

What is kept (privacy)
  SAFE_FIELDS only. Never read: createdBy and updatedBy (the Department's staff e-mail addresses, at the top level and
  inside each station object), descriptionHtml (the description again, with links). Before the answer is saved under
  data/raw/ those keys are dropped from it. The free text (title, locationName, description, cause) is the
  Department's own notice; a sewage spill notice can give a street address: every house number before a street word
  is removed, Hawaii's hyphenated ones ("99-999 Sample Place") by HI_HOUSE_NUMBER here and the others by
  common.strip_house_numbers; common.strip_personal runs on every string (in common.event) and build/redact.py over
  the records last. tests/test_ingest_hi.py proves a staff e-mail and a house number never reach a record.

Record rules
  - Key: the event id (source_record_id "<id>"); source_url the event's portal page.
  - Times: postedDate, closedDate, createdOn and updatedOn are UTC written without a zone (posts fall between 17:00
    and 02:00 UTC, the Department's working day in Honolulu; signRemovalDate is closedDate written in Hawaii time, ten
    hours earlier, in 467 of 479 closed events). They are written in Pacific/Honolulu with the offset, precision minute.
    postedDateHst is not used: it is the UTC date of postedDate in all 500 events, not the Hawaii date. sampleDate and
    signPostedDate are dates only (00:00), read as Hawaii days. A Beach Notification starts on its sample day when that
    day is on or up to SAMPLE_MAX_DAYS before the posting; otherwise (2001-12-13 typed for a 2023 notice) at the
    posting, with raw._sample_date_not_used.
  - started_at and published_at are the advisory's posting time (postedDate): the Department's window starts when it
    posts the advisory; a spill's own start is given, when at all, only in the text and is not read as a time.
    reported_at is null (the Department's receipt of the operator's report is not given). source_updated_at is
    updatedOn. ended_at is closedDate, the time the Department cancelled the advisory; null while it is open.
  - Type (the event's "type"):
      Sewage Spill      -> sso; plant_bypass when the notice says the wastewater was partly treated or exceeded the
                           permit's bacteria level (PARTIAL_RE); bypass when it names a treatment plant and neither.
      Permit Exceedance -> plant_bypass (a plant's effluent above its permit's fecal indicator bacteria limit).
      Brown Water Advisory -> rain_advisory (the beach category, never a sewage report, never in the sewage colours;
                           raw.advisory_noun "Brown Water Advisory" is its label): storm-water runoff after heavy rain.
      Beach Advisory    -> beach_advisory (enterococci above the Department's threshold at a monitored beach).
      Beach Notification -> beach_advisory with status unknown and raw._agency_label_only: a first high sample the
                           Department is retesting, with no advisory issued; the site's caution (data/rules.json
                           unresolved.sample_caution) from the sample day to the later of 72 hours and the notice's
                           closing (or the last read that listed it open: raw._caution_to_notice_end), never the
                           Department's advisory.
      any other type    -> unknown, with parse_error.
    raw._type_basis says which rule applied.
  - Status: Open -> advisory_active (the Department's own window: "remain out of the affected waters until this
    advisory has been cancelled"); raw._last_seen_in_source is the read that listed it (the status build re-confirms a
    beach or rain advisory from it). Closed -> advisory_lifted with ended_at closedDate. A Beach Notification is status
    unknown (above). An advisory listed as open at an earlier read and missing from a later complete read (it fell out
    of the newest 500, or the Department withdrew it) keeps advisory_active with raw._unlisted_since (the first read
    without it): the status build ends the Department's window there; for a sewage type raw._end_not_confirmed makes it
    "end not confirmed" (hatched) to day 30 and for at least 72 hours after the unlisting, then the end-never-reported
    note to day 90, since the Department's cancellation was never seen.
  - Water (rules only; no model, no geocoding, no coordinates: the API gives none): the place texts are the "Affected
    waters:" lines, the water the advice names ("stay out of Kuapa Pond"), locationName, the title after "at", "for" or "from", and a beach station's name. Diacritics and the
    okina are folded ("Kane'ohe" -> "Kaneohe"; the feed spells the same water both ways); a named water is up to three
    capitalised words before a water word (WATER_KINDS: bay, harbor, stream, canal, pond, river, lagoon, cove, loch,
    channel, gulch ...). Facility names are not waters ("Joint Base Pearl Harbor Hickam"); a water word followed by a
    land word is not one ("Pearl Harbor Peninsula"). For a rain or beach advisory, a stream, river, gulch or pond that
    is only an end of a shoreline stretch ("Guardrails to Olowalu Stream") or the land behind an ocean station
    ("Kolekole Gulch (Ocean)") is not the advisory's water. The named waters are waterbody_text. water_slugs: the
    Hawaii water records (data/waters-hi.json, waters-nhd.json, waters-extra.json, with data/water-aliases.json) whose
    name or alias is the named water, on the event's island (the record's box centre inside the island's box,
    ISLANDS); a name two islands share (Waimea Bay, Kailua Bay) is never placed across islands. A report with no match
    is kept with no water (waterbody_text still says what the Department named); research/hi/receiving-waters-missing.json
    lists the names for the water batch. raw.advisory_extent "named_water" when a rain or beach advisory's place is the
    water itself ("Hanalei Bay", "Hilo bay and along the Hamakua coast"), not a beach or a stretch's end. Island-wide and
    statewide Brown Water Advisories name no water: kept with raw.extent "island" or "statewide".
  - Operator: only when the notice names a facility (FACILITIES: the Kailua Regional, Sand Island, Waianae, Hilo,
    Wailua, East Honolulu, Marine Corps Base Hawaii and Joint Base Pearl Harbor-Hickam plants, the counties' named pump
    stations and plants): discharger_id from data/dischargers.json, npdes_permit when the plant has one permit. A spill
    at a street address names no operator and gets none (the Department's cause can be a private line).
  - Volume: the "Volume:" or "Estimated Volume:" line; a plain gallon figure is volume_gal (common.parse_volume_gal),
    anything else ("Undetermined") volume_text only.
  - advice_text: the Department's own sentences of advice from the description (ADVICE_RE).
  - History: the endpoint holds the newest 500, so the previous run's records are carried; an event that leaves the
    list keeps its record. An answer with fewer than half the events of the last good read, or not the expected
    shape, is an outage (ok false, the records kept).

Not computed for Hawaii: the radar rainfall caution (the MRMS grid covers the contiguous states only; Hawaii has no
combined sewers). A model pass could later classify place texts the rules leave unplaced; it would never supply a place
or a colour.

Cadence: hourly. Run from pipeline/:  python -m ingest.hi_doh_cwb_events [--file saved.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, parse_volume_gal, read_json, save_raw,
                    strip_house_numbers, write_events)

SOURCE_ID = "hi-doh-cwb-events-api"
URL = "https://eha-cloud.doh.hawaii.gov/cwb/api/events"
PORTAL = "https://eha-cloud.doh.hawaii.gov/cwb/"
EVENT_URL = "https://eha-cloud.doh.hawaii.gov/cwb/#!/event/{id}/details/view"
TZ = ZoneInfo("Pacific/Honolulu")
AUTHORITY = "Hawaii Department of Health, Clean Water Branch"   # the site audit strips authority names before its verdict-word check
TIMEOUT = (60, 600)            # the host is quick, the network here may not be
MIN_ROWS_RATIO = 0.5
SAMPLE_MAX_DAYS = 14           # a sample date later than the posting, or this long before it, is a typing slip
STATION_FIELDS = ("id", "name", "cleanName", "number", "siteDescription", "waterClassificationType", "beachId",
                  "watershedId", "isPrimary", "status")
ISLAND_FIELDS = ("name", "cleanName", "abbreviation", "countyName", "fipsCountyCode")
SAFE_FIELDS = ("id", "type", "isStatewide", "isIslandWide", "hasBwa", "postedDate", "closedDate", "title", "locationName",
               "description", "cause", "signRemovalDate", "signPostedDate", "signType", "status", "stationId",
               "sampleDate", "sampleValue", "postedNoticeTemplateName", "closedNoticeTemplateName", "createdOn",
               "updatedOn")
NEVER_READ = ("createdBy", "updatedBy", "descriptionHtml")

# island (folded, lower case) -> public name, county seat (the town the names pass measures from when a report names
# none), box (west, south, east, north; degrees, generous, from the islands' coastlines)
ISLANDS = {
    "oahu": ("Oahu", "Honolulu", (-158.32, 21.22, -157.60, 21.74)),
    "kauai": ("Kauai", "Lihue", (-159.84, 21.84, -159.25, 22.27)),
    "niihau": ("Niihau", "Lihue", (-160.28, 21.74, -160.02, 22.05)),
    "maui": ("Maui", "Wailuku", (-156.72, 20.55, -155.95, 21.05)),
    "molokai": ("Molokai", "Kaunakakai", (-157.34, 21.03, -156.68, 21.24)),
    "lanai": ("Lanai", "Lanai City", (-157.08, 20.71, -156.79, 20.97)),
    "kahoolawe": ("Kahoolawe", "Wailuku", (-156.72, 20.48, -156.52, 20.62)),
    "hawaii": ("Hawaii", "Hilo", (-156.08, 18.89, -154.78, 20.29)),
}
COUNTY_ISLANDS = {"honolulu": ["oahu"], "kauai": ["kauai", "niihau"], "maui": ["maui", "molokai", "lanai", "kahoolawe"],
                  "hawaii": ["hawaii"]}

TYPES = {"Sewage Spill": "sso", "Permit Exceedance": "plant_bypass", "Brown Water Advisory": "rain_advisory",
         "Beach Advisory": "beach_advisory", "Beach Notification": "beach_advisory"}
SEWAGE_TYPES = {"sso", "bypass", "plant_bypass"}
PARTIAL_RE = re.compile(r"partially[ -]treated|effluent|disinfection|chlorinat|\bUV\b|sand filt|fecal indicator|"
                        r"exceed", re.I)
PLANT_RE = re.compile(r"wastewater treatment plant|\bWWTP\b|water reclamation facility|treatment facility", re.I)
ADVICE_RE = re.compile(r"(?:advised?|advises|recommends?|remain out|stay out|avoid)", re.I)

WATER_KINDS = ("bay", "harbor", "harbour", "stream", "canal", "pond", "ponds", "fishpond", "river", "lagoon", "cove",
               "loch", "channel", "marina", "estuary", "inlet", "gulch", "reservoir")
FRESH_KINDS = {"stream", "river", "gulch", "canal", "pond", "ponds", "fishpond", "reservoir"}
_KIND = "|".join(WATER_KINDS)
_WORD = r"[A-Z][A-Za-z.-]*"
WATER_RE = re.compile(rf"\b((?:{_WORD}\s+){{1,3}}?)((?i:{_KIND}))\b")
LAKE_RE = re.compile(r"\bLake\s+[A-Z][A-Za-z-]+")
NOT_FIRST = {"The", "At", "Near", "From", "To", "And", "Of", "Offshore", "Waters", "Fronting", "Along", "In", "On",
             "Into", "Via", "Up", "Off", "Update", "UPDATE", "Revised", "REVISED", "Advisory", "Discharge",
             "Wastewater", "Brown", "Water", "Beach", "Shorelines", "Shoreline", "Affected", "Location", "Big"}
# after the water word: a land or facility word means the name is not a water ("Pearl Harbor Peninsula"); a beach word
# means the beach on that water ("Waimea Bay Beach Park")
LAND_AFTER = re.compile(r"^\s*(?:Peninsula|Hickam|Wastewater|Pump|Village|Road|Rd|Street|St|Highway|Hwy|Avenue|Ave|"
                        r"Drive|Elementary|School|Bridge|Heights|Estates)\b", re.I)
BEACH_AFTER = re.compile(r"^\s*(?:Beach|Park|Landing|Pier|Pavilion|Recreational|State|Resort|Boat Ramp|Shoreline|"
                         r"Mouth|\(|-|#\s?\d|\d)", re.I)
FACILITY_NAMES = re.compile(r"Joint Base Pearl Harbor[- ]Hickam|Marine Corps (?:Base )?Hawaii|Kaneohe Tunnel Influent "
                            r"Facility|Pearl Harbor Naval Shipyard", re.I)
RANGE_RE = re.compile(r"\bto\b|\bfrom\b|\bnorth to\b|\bsouth to\b", re.I)
SPELLING = {"nuuipa pond": "Nuupia Pond"}          # the Department's typing, kept as given in raw
ISLAND_SUFFIX = re.compile(r",\s*(?:Big Island,\s*)?(?:O ?ahu|Kaua ?i|Maui|Hawai ?i(?: Island)?|Moloka ?i|L[aā]na ?i|"
                           r"Ni ?ihau)\s*\.?\s*$", re.I)
# "The public is advised to stay out of Kuapa Pond due to ...": the water the advice names
STAY_OUT_RE = re.compile(r"(?:stay|remain|keep)\s+(?:out|our)\s+of\s+(?:the\s+)?(?:(?:affected\s+)?waters?\s+(?:of|near|at|"
                         r"around)\s+(?:the\s+)?)?(.{3,80}?)(?=\s+(?:due to|until|because|in [A-Z])|[.;]|$)", re.I)
AFFECTED_RE = re.compile(r"(?im)^\s*Affected (?:waters?|areas?)\s*:\s*(.+?)\s*$")
VOLUME_RE = re.compile(r"(?im)^\s*(?:Estimated\s+)?Volume\s*:\s*(.+?)\s*$")
EVENT_LINE_RE = re.compile(r"(?im)^\s*Event\s*:\s*(.+?)\s*$")
SPILL_STATUS_RE = re.compile(r"(?im)^\s*Status(?: of spill)?\s*:\s*(.+?)\s*$")
# Hawaii's hyphenated house numbers ("99-999 Sample Place", "91-9999 Sample Road"): zone-section and lot, before a street
_STREET = (r"street|st|road|rd|avenue|ave|av|lane|ln|drive|dr|way|court|ct|place|pl|circle|cir|boulevard|blvd|"
           r"highway|hwy|loop|parkway|pkwy|terrace|ter|trail|alley|walk")
HI_HOUSE_NUMBER = re.compile(rf"(?<![\w.,/:-])\d{{1,2}}-\d{{1,5}}[A-Za-z]?(?=\s+(?:[A-Z][\w'‘ʻ.-]*\s+){{1,3}}"
                             rf"(?i:{_STREET})\b\.?)")
HOUSE_NUMBER_REMOVED = "[house number removed]"
GALLONS_RE = re.compile(r"\d[\d,.]*\s*(?:gal(?:lon)?s?\b|mg\b|million gallons)", re.I)
DATE_IN_TEXT = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}:\d{2}\s*(?:am|pm)\b", re.I)

# named facility -> (dischargers.json id, permit or None). First match wins; matched against title, location and the
# notice's Event and Location lines.
FACILITIES = [
    (re.compile(r"marine corps", re.I), "hi-mcbh-kaneohe", "HI0110078"),
    (re.compile(r"joint base pearl harbor|hickam", re.I), "hi-jbphh", "HI0110086"),
    (re.compile(r"kailua regional", re.I), "hi-honolulu-env", "HI0021296"),
    (re.compile(r"sand island wastewater", re.I), "hi-honolulu-env", "HI0021956"),
    (re.compile(r"waianae wastewater", re.I), "hi-honolulu-env", "HI0021953"),
    (re.compile(r"honouliuli", re.I), "hi-honolulu-env", None),
    (re.compile(r"wahiawa wastewater|kaneohe tunnel|kahala pump station", re.I), "hi-honolulu-env", None),
    (re.compile(r"east honolulu wastewater", re.I), "hi-hawaii-american-water", "HI0020303"),
    (re.compile(r"schofield barracks wastewater", re.I), "hi-aqua-engineers-schofield", "HI0110141"),
    (re.compile(r"hilo wastewater", re.I), "hi-hawaii-county", "HI0021377"),
    (re.compile(r"kulaimano", re.I), "hi-hawaii-county", "HI0020770"),
    (re.compile(r"papaikou", re.I), "hi-hawaii-county", "HI0021113"),
    (re.compile(r"kealakehe|kona wastewater", re.I), "hi-hawaii-county", None),
    (re.compile(r"kihei pump station|kihei wastewater|lahaina wastewater|wailuku[- ]kahului|kahului wastewater",
                re.I), "hi-maui-county", None),
    (re.compile(r"wailua wastewater", re.I), "hi-kauai-county", "HI0020257"),
    (re.compile(r"waimea wastewater|lihue wastewater|kapaia sewage", re.I), "hi-kauai-county", None),
]
OPERATOR_NAMES = {
    "hi-honolulu-env": "City and County of Honolulu, Department of Environmental Services",
    "hi-hawaii-county": "County of Hawaii, Department of Environmental Management",
    "hi-kauai-county": "County of Kauai, Wastewater Management Division",
    "hi-maui-county": "County of Maui, Department of Environmental Management",
    "hi-mcbh-kaneohe": "Marine Corps Base Hawaii",
    "hi-jbphh": "Joint Base Pearl Harbor-Hickam",
    "hi-hawaii-american-water": "Hawaii-American Water Company",
    "hi-aqua-engineers-schofield": "Aqua Engineers, Inc.",
}


# ---------------------------------------------------------------- reading the endpoint

def fetch(sess=None) -> dict:
    s = sess or requests.Session()
    r = s.get(URL, headers={**HEADERS, "Accept": "application/json"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def drop_never_read(o):
    """The answer without the staff fields (createdBy, updatedBy, at every depth) and descriptionHtml."""
    if isinstance(o, dict):
        return {k: drop_never_read(v) for k, v in o.items() if k not in NEVER_READ}
    if isinstance(o, list):
        return [drop_never_read(v) for v in o]
    return o


def safe_row(e: dict) -> dict:
    out = {k: e.get(k) for k in SAFE_FIELDS if k in e}
    isl = e.get("island") if isinstance(e.get("island"), dict) else None
    out["island"] = {k: isl.get(k) for k in ISLAND_FIELDS if k in isl} if isl else None
    st = e.get("station") if isinstance(e.get("station"), dict) else None
    if st:
        out["station"] = {k: st.get(k) for k in STATION_FIELDS if k in st}
    out["locations_count"] = len(e.get("locations") or [])
    out["event_beaches_count"] = len(e.get("eventBeaches") or [])
    return out


# ---------------------------------------------------------------- helpers

def fold(s) -> str:
    """Diacritics and the okina folded away ("Kāneʻohe" -> "Kaneohe", "O‘ahu" -> "Oahu"); spaces collapsed."""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[ʻ‘’'`ʼ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def key(s) -> str:
    """A name compared: folded, lower case, punctuation as spaces."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", fold(s).lower()).split())


def when(v) -> datetime | None:
    """A UTC time written without a zone ('2026-10-23T01:26:16.1170000') -> aware UTC."""
    if not v or not isinstance(v, str):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})", v)
    if not m:
        return None
    try:
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}").replace(tzinfo=UTC)
    except ValueError:
        return None


def day(v) -> datetime | None:
    """A date-only field (00:00, 'sampleDate') -> 00:00 of that day in Hawaii."""
    if not v or not isinstance(v, str):
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=TZ)
    except ValueError:
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


def scrub_address(s):
    """House numbers out of a street address: Hawaii's hyphenated ones here, the others by common.strip_house_numbers."""
    if not isinstance(s, str) or not s:
        return s
    return strip_house_numbers(HI_HOUSE_NUMBER.sub(HOUSE_NUMBER_REMOVED, s))


def island_of(row: dict) -> str | None:
    isl = row.get("island") or {}
    k = key(isl.get("cleanName") or isl.get("name") or "").replace(" ", "")
    return k if k in ISLANDS else None


def title_place(title: str) -> str | None:
    """'Brown Water Advisory at Kalapaki Beach Park, Kaua‘i' -> 'Kalapaki Beach Park'."""
    t = re.sub(r"^\W*(?:update|revised)\W*", "", fold(title or ""), flags=re.I)
    m = re.search(r"\b(?:at|for|from)\s+(?:the\s+)?(.+)$", t, re.I)
    if not m:
        return None
    return ISLAND_SUFFIX.sub("", m.group(1)).strip(" ,.") or None


def tidy(name: str) -> str:
    words = [w[:1].upper() + w[1:] for w in name.split()]
    out = " ".join(words)
    return SPELLING.get(out.lower(), out)


def water_names(text: str, marine_only: bool = False, range_ends_fresh: bool = False) -> list[tuple[str, bool]]:
    """[(water name, beach-qualified)] in one place text. marine_only drops streams, rivers, gulches and ponds (the
    land behind an ocean station); range_ends_fresh drops them where the text is a stretch ("X to Y")."""
    t = FACILITY_NAMES.sub(" ; ", fold(text or ""))
    t = re.sub(r"\(\s*Ocean\s*\)", " (Ocean)", t)
    is_range = bool(RANGE_RE.search(t))
    out: list[tuple[str, bool]] = []
    for m in WATER_RE.finditer(t):
        words = m.group(1).split()
        while words and words[0] in NOT_FIRST:
            words = words[1:]
        if not words:
            continue
        kind = m.group(2).lower()
        after = t[m.end():]
        if LAND_AFTER.match(after):
            continue
        ocean_station = after.lstrip().startswith("(Ocean)")
        if kind in FRESH_KINDS and (marine_only or ocean_station or (range_ends_fresh and is_range)):
            continue
        name = tidy(" ".join(words + [m.group(2)]))
        out.append((name, bool(BEACH_AFTER.match(after)) or ocean_station))
    for m in LAKE_RE.finditer(t):           # "Lake Wilson": the water word first
        if not (marine_only or (range_ends_fresh and is_range)) and not LAND_AFTER.match(t[m.end():]):
            out.append((tidy(m.group(0)), bool(BEACH_AFTER.match(t[m.end():]))))
    return out


# ---------------------------------------------------------------- water records

def bbox_centre(w: dict):
    b = w.get("bbox")
    if isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b):
        return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    if isinstance(w.get("lon"), (int, float)) and isinstance(w.get("lat"), (int, float)):
        return w["lon"], w["lat"]
    return None


def on_island(w: dict, isl: str | None) -> bool:
    c = bbox_centre(w)
    if not isl or c is None:
        return False
    x0, y0, x1, y1 = ISLANDS[isl][2]
    return x0 <= c[0] <= x1 and y0 <= c[1] <= y1


def load_hi_waters(data_dir: Path = DATA_DIR) -> list[dict]:
    """Hawaii's water records (waters-hi.json, waters-nhd.json, waters-extra.json), with the hand aliases."""
    out, seen = [], set()
    for name in ("waters-hi.json", "waters-nhd.json", "waters-extra.json"):
        d = read_json(data_dir / name, {}) or {}
        for w in (d.get("waters") if isinstance(d, dict) else d) or []:
            if isinstance(w, dict) and w.get("state") == "HI" and w.get("slug") and w["slug"] not in seen:
                seen.add(w["slug"])
                out.append(w)
    aliases = read_json(data_dir / "water-aliases.json", {}) or {}
    for w in out:
        extra = aliases.get(w["slug"]) if isinstance(aliases, dict) else None
        if isinstance(extra, list):
            w["aliases"] = list(dict.fromkeys(list(w.get("aliases") or []) + [a for a in extra if isinstance(a, str)]))
    return out


def national_slugs(data_dir: Path = DATA_DIR) -> dict[str, str]:
    """{name key: slug} of data/receiving-waters-national.json's Hawaii rows that carry a water slug."""
    d = read_json(data_dir / "receiving-waters-national.json", {}) or {}
    out = {}
    for r in (((d.get("states") or {}).get("HI") or {}).get("waters") or []):
        if r.get("water_slug"):
            for n in [r.get("name")] + list(r.get("names_seen") or []):
                if n:
                    out[key(n)] = r["water_slug"]
    return out


class Waters:
    def __init__(self, records: list[dict], national: dict[str, str] | None = None):
        self.by_name: dict[str, list[dict]] = {}
        for w in records:
            for n in [w.get("name")] + list(w.get("aliases") or []):
                if isinstance(n, str) and n.strip():
                    self.by_name.setdefault(key(n), [])
                    if w not in self.by_name[key(n)]:
                        self.by_name[key(n)].append(w)
        self.national = national or {}
        self.slugs = {w["slug"] for w in records}

    def match(self, name: str, isl: str | None) -> tuple[str | None, str]:
        """(slug, basis) of the named water on the island, or (None, why not)."""
        cands = self.by_name.get(key(name)) or []
        here = [w for w in cands if on_island(w, isl)]
        if len(here) == 1:
            return here[0]["slug"], "name, on the event's island"
        if len(here) > 1:
            return None, f"{len(here)} Hawaii water records of that name on the island"
        nat = self.national.get(key(name))
        if nat and nat in self.slugs:
            w = next(w for ws in self.by_name.values() for w in ws if w["slug"] == nat)
            if on_island(w, isl):
                return nat, "the national receiving-water list's record, on the event's island"
        if cands:
            return None, "Hawaii water records of that name lie on another island"
        return None, "no Hawaii water record of that name"


# ---------------------------------------------------------------- one event

def classify(row: dict) -> tuple[str, str]:
    t = row.get("type")
    et = TYPES.get(t)
    if et is None:
        return "unknown", f"type {t!r} is not one this module reads"
    if t == "Sewage Spill":
        words = " ".join(str(row.get(k) or "") for k in ("title", "locationName", "description", "cause"))
        ev_line = " ".join(EVENT_LINE_RE.findall(row.get("description") or ""))
        if PARTIAL_RE.search(words):
            return "plant_bypass", "Sewage Spill whose notice says the wastewater was partly treated or exceeded the " \
                                   "permit's bacteria level"
        if PLANT_RE.search(" ".join([str(row.get("title") or ""), str(row.get("locationName") or ""), ev_line])):
            return "bypass", "Sewage Spill at a named treatment plant, untreated as far as the notice says"
        return "sso", "Sewage Spill"
    return et, t


def advice(desc: str) -> str | None:
    sents = re.split(r"(?<=[.!])\s+|\n+", desc or "")
    keep = [s.strip() for s in sents if ADVICE_RE.search(s) and "http" not in s and len(s.strip()) > 20]
    return " ".join(dict.fromkeys(keep[:3])) or None


def operator(row: dict) -> tuple[str | None, str | None, str | None]:
    text = " ".join([fold(row.get("title")), fold(row.get("locationName")), fold(row.get("description"))])
    for rx, oid, permit in FACILITIES:
        m = rx.search(text)
        if m:
            return oid, permit, m.group(0)
    return None, None, None


def place(row: dict, et: str, waters: Waters, isl: str | None) -> dict:
    """The water texts, names, slugs and extent of one event (the record rules' Water paragraph)."""
    advisory = et in ("rain_advisory", "beach_advisory")
    desc = row.get("description") or ""
    texts: list[tuple[str, str]] = [(a, "affected waters") for a in AFFECTED_RE.findall(desc)]
    for m in STAY_OUT_RE.finditer(fold(desc)):
        texts.append((m.group(1), "advice"))
    if row.get("locationName"):
        texts.append((row["locationName"], "location"))
    tp = title_place(row.get("title") or "")
    if tp:
        texts.append((tp, "title"))
    st = row.get("station") or {}
    if st.get("name"):
        texts.append((st["name"], "station"))
    marine = advisory and str(st.get("waterClassificationType") or "").lower() == "marine"
    names: dict[str, dict] = {}
    for text, origin in texts:
        for name, qualified in water_names(text, marine_only=marine and origin == "station",
                                           range_ends_fresh=advisory):
            n = names.setdefault(name, {"name": name, "from": [], "qualified": True})
            n["from"].append(origin)
            n["qualified"] = n["qualified"] and qualified
    slugs, basis = [], {}
    for n in names.values():
        slug, why = waters.match(n["name"], isl)
        basis[n["name"]] = why
        if slug and slug not in slugs:
            slugs.append(slug)
    extent = None
    if row.get("isStatewide"):
        extent = "statewide"
    elif row.get("isIslandWide"):
        extent = "island"
    elif et == "rain_advisory" and names:
        where = ISLAND_SUFFIX.sub("", fold(row.get("locationName") or st.get("name") or tp or "")).strip(" ,.")
        lead = next(iter(names.values()))
        if not RANGE_RE.search(where) and not lead["qualified"] and key(where).startswith(key(lead["name"])):
            extent = "named_water"
    beach = None
    if advisory and not names and extent is None:
        beach = scrub_address(ISLAND_SUFFIX.sub("", fold(st.get("name") or row.get("locationName") or tp or "")).strip(" ,."))
    return {"texts": [{"text": scrub_address(fold(t)), "from": o} for t, o in texts], "names": list(names.values()),
            "slugs": slugs, "match_basis": basis, "extent": extent, "place": beach or None}


def town_of(row: dict) -> str | None:
    """'Kalama Park, Kihei' -> 'Kihei': the place after the last comma of locationName, when it is a single place
    name and not an island."""
    loc = fold(row.get("locationName") or "")
    if "," not in loc:
        return None
    tail = loc.rsplit(",", 1)[1].strip(" .")
    if not tail or re.search(r"\d", tail) or key(tail).replace(" ", "") in ISLANDS or len(tail.split()) > 3 \
            or re.search(rf"\b(?:{_KIND}|beach|park|point|big island|island)\b", tail, re.I):
        return None
    return tail


def to_record(row: dict, fetched_at: str, waters: Waters, prev: dict | None = None) -> dict:
    et, type_basis = classify(row)
    isl = island_of(row)
    posted, closed, updated = when(row.get("postedDate")), when(row.get("closedDate")), when(row.get("updatedOn"))
    open_ = str(row.get("status") or "").lower() == "open"
    notification = row.get("type") == "Beach Notification"
    status = "unknown" if notification or et == "unknown" else ("advisory_active" if open_ else
                                                                  "advisory_lifted" if closed else "unknown")
    start, precision = posted, "minute"
    sample = day(row.get("sampleDate"))
    sample_ok = bool(sample and posted and sample <= posted and posted - sample <= timedelta(days=SAMPLE_MAX_DAYS))
    if notification and sample_ok:
        start, precision = sample, "day"
    pl = place(row, et, waters, isl)
    oid, permit, fac = operator(row) if et in SEWAGE_TYPES else (None, None, None)
    desc = row.get("description") or ""
    vol_lines = VOLUME_RE.findall(desc)
    vol_text = scrub_address(fold(vol_lines[0])) if vol_lines else None
    if vol_text and DATE_IN_TEXT.search(vol_text) and not GALLONS_RE.search(vol_text):
        vol_text = None                 # a date typed on the volume line ("Date/time: 3/20/26, 10:00 pm")
    vol_gal, est = parse_volume_gal(vol_text) if vol_text and GALLONS_RE.search(vol_text) else (None, "unknown")
    if vol_gal is not None and re.search(r"estimat", "".join(re.findall(r"(?im)^\s*Estimated\s+Volume", desc)), re.I):
        est = "estimated"
    clean = {**row, "title": scrub_address(row.get("title")), "locationName": scrub_address(row.get("locationName")),
             "description": scrub_address(desc)}
    raw = {"row": clean, "state": "HI", "_type_basis": type_basis,
           "island": ISLANDS[isl][0] if isl else None, "county": ((row.get("island") or {}).get("countyName")),
           "places": pl["texts"], "_water_names": [n["name"] for n in pl["names"]], "match_basis": pl["match_basis"],
           "_first_seen_at": (prev or {}).get("raw", {}).get("_first_seen_at") or fetched_at}
    town = town_of(row)
    if town:
        raw["town"] = town
    if pl["extent"]:
        raw["advisory_extent" if pl["extent"] == "named_water" else "extent"] = pl["extent"]
    if et == "rain_advisory":
        raw["advisory_noun"] = "Brown Water Advisory"
    if open_ and status == "advisory_active":
        raw["_last_seen_in_source"] = fetched_at
    if notification:
        sv = row.get("sampleValue")
        raw["_agency_label_only"] = True
        raw["_caution_to_notice_end"] = True
        raw["_notice_end_basis"] = ("the Department's notice was still posted (closedDate)" if not open_ else
                                    "the Department's notice was still listed as open at this read")
        if open_:
            raw["_last_seen_in_source"] = fetched_at
        elif closed:
            raw["_notice_closed_at"] = iso(closed)      # to the minute; the record's start is a day
        raw["_agency_label"] = (f"Enterococci {sv:g} per 100 mL in routine monitoring; the Department is retesting and "
                                "issued no advisory" if isinstance(sv, (int, float)) else
                                "A high enterococci result; the Department is retesting and issued no advisory")
    if row.get("sampleDate"):
        raw["sample_date"] = iso(sample)
        if not sample_ok:
            raw["_sample_date_not_used"] = (f"the sample date is not on or within {SAMPLE_MAX_DAYS} days before the "
                                            "posting (a typing slip): the posting time is used")
    if row.get("signRemovalDate"):
        raw["sign_removal_hawaii_time"] = row["signRemovalDate"]
    spill = SPILL_STATUS_RE.findall(desc)
    if spill:
        raw["spill_status_text"] = fold(spill[0])
    if fac:
        raw["_discharger_basis"] = f"the notice names {fac!r}"
    raw["start_basis"] = ("the day of the sample (sampleDate)" if precision == "day" else
                          "the Department's posting of the advisory (postedDate, UTC); the spill's own start is not "
                          "given as a time")
    if pl["place"]:
        raw["place_basis"] = "the Department names a beach or shore, not a water: the place is the water text"
    if pl["names"] and not pl["slugs"]:
        raw["unplaced_reason"] = "; ".join(f"{n}: {w}" for n, w in pl["match_basis"].items())
    material = {"sso": "untreated wastewater", "bypass": "wastewater", "plant_bypass": "partly treated wastewater",
                "rain_advisory": "storm-water runoff"}.get(et)
    rec = event(
        source_id=SOURCE_ID, source_record_id=str(row.get("id")), event_type=et, status=status,
        discharger_id=oid, discharger_name=OPERATOR_NAMES.get(oid) if oid else None, npdes_permit=permit,
        waterbody_text="; ".join(n["name"] for n in pl["names"]) or pl["place"],
        water_slugs=pl["slugs"], water_match="name" if pl["slugs"] else "none",
        started_at=iso(start), ended_at=iso(closed) if closed and not open_ else None, time_precision=precision,
        reported_at=None, published_at=iso(posted), source_updated_at=iso(updated), fetched_at=fetched_at,
        material=material, volume_gal=vol_gal, volume_text=vol_text, estimate_flag=est if vol_text else "unknown",
        authority=AUTHORITY, advice_text=scrub_address(fold(advice(desc))),
        advice_window_hours=None,
        advice_window_basis=("the Department keeps the advisory until it cancels it" if not notification else
                             "no advisory: the Department is retesting the beach"),
        source_url=EVENT_URL.format(id=row.get("id")), raw=raw,
        parse_error=None if et != "unknown" else type_basis)
    return rec


# ---------------------------------------------------------------- the whole read

def build(doc: dict, fetched_at: str, previous: list[dict] = (), waters: Waters | None = None) -> tuple[list[dict], dict]:
    waters = waters or Waters(load_hi_waters(), national_slugs())
    rows = [safe_row(e) for e in (doc.get("list") or []) if isinstance(e, dict) and e.get("id") is not None]
    prev = {r["source_record_id"]: r for r in previous if r.get("source_id") == SOURCE_ID}
    out, seen = [], set()
    for row in rows:
        rid = str(row["id"])
        seen.add(rid)
        out.append(to_record(row, fetched_at, waters, prev.get(rid)))
    for rid, r in prev.items():          # history: an event that left the newest 500 keeps its record
        if rid in seen:
            continue
        raw = r.setdefault("raw", {})
        if r.get("status") == "advisory_active" and not raw.get("_unlisted_since"):
            raw["_unlisted_since"] = fetched_at
            raw["_end_basis"] = ("the advisory was open at the last read that listed it and is missing from a later "
                                 "complete read; the Department's cancellation was not seen")
            if r.get("event_type") in SEWAGE_TYPES:
                raw["_end_not_confirmed"] = True
        out.append(r)
    out.sort(key=lambda r: int(r["source_record_id"]) if str(r["source_record_id"]).isdigit() else 0)
    meta = {"endpoint": URL, "portal": PORTAL, "total_results": doc.get("totalResultsCount"), "read": len(rows),
            "carried": len(out) - len(rows), "by_type": dict(Counter(r.get("type") for r in rows)),
            "by_event_type": dict(Counter(r["event_type"] for r in out)),
            "open": sum(1 for r in rows if str(r.get("status")).lower() == "open"),
            "placed": sum(1 for r in out if r["water_slugs"]),
            "named_unplaced": sum(1 for r in out if r["waterbody_text"] and not r["water_slugs"]),
            "no_water_named": sum(1 for r in out if not r["waterbody_text"]),
            "never_read": list(NEVER_READ), "licence": "none stated (the endpoint is undocumented)",
            "rain_caution": "not computed for Hawaii (the radar grid covers the contiguous states only)"}
    return out, meta


def run(file: str | None = None, out: str | None = None) -> int:
    path = Path(out) if out else EVENTS_DIR / f"{SOURCE_ID}.json"
    prev_doc = read_json(path, {}) or {}
    previous = prev_doc.get("records") or []
    last_read = (prev_doc.get("meta") or {}).get("read") if prev_doc.get("ok") else None
    fetched_at = now_iso()
    try:
        if file:
            doc = json.loads(Path(file).read_text())
        else:
            doc = fetch()
            save_raw(SOURCE_ID, json.dumps(drop_never_read(doc), ensure_ascii=False), "json")
        if not isinstance(doc, dict) or not isinstance(doc.get("list"), list):
            raise ValueError("the answer is not {page, totalResultsCount, list}")
        if isinstance(last_read, int) and len(doc["list"]) < MIN_ROWS_RATIO * last_read:
            raise ValueError(f"{len(doc['list'])} events, fewer than half the last good read's")
    except Exception as e:                       # an outage keeps the records
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}"[:300], path=path)
        print(f"{SOURCE_ID}: read failed: {e}", file=sys.stderr)
        return 1
    records, meta = build(doc, fetched_at, previous)
    write_events(SOURCE_ID, records, meta=meta, path=path)
    print(f"{SOURCE_ID}: {len(records)} records ({meta['read']} read, {meta['carried']} carried); "
          f"{meta['by_event_type']}; placed {meta['placed']}, named but unplaced {meta['named_unplaced']}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a saved answer of the endpoint (JSON)")
    ap.add_argument("--out", help="write here instead of data/build/events/")
    a = ap.parse_args(argv)
    return run(a.file, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
