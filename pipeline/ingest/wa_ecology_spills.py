"""Washington Ecology sewage spill list (RCW 90.48.636) -> data/build/events/wa-ecology-sewage-spills.json

Source
  Washington State Department of Ecology, "Sewage spills" (https://ecology.wa.gov/water-shorelines/water-quality/
  wastewater/sewage-spills). The page embeds an ArcGIS Experience ("Sewage spill table only", item
  4fb5f533aabb41ce9e5bd8aa59284ab6 on gis.ecology.wa.gov/portal) whose table reads a public hosted feature layer, the
  results of Ecology's "Sewage Spill Webpage Entry" form:
  https://gis.ecology.wa.gov/hosting/rest/services/Hosted/survey123_48de962d0dea40eb9485805510a40b84_results/FeatureServer/0
  Terms: Ecology's copyright page (TERMS_URL), which covers "the linked database and map servers": data may be used
  "provided the Washington State Department of Ecology is credited as the data provider and a link is provided to the
  Ecology data source web page"; commercial and political use (a campaign or lobbying effort) is prohibited. The
  layer's item (a15e4d84ba7e47b3a14ac9adcdfa54a9) is public and states no licence of its own.
  The portal, the item and the layer answered HTTP 200 to the project user agent on 2026-11-04 (no key, no cookie);
  the research of 2026-11-03 had a firewall refusal there with another client. Nothing is worked around: if the
  host refuses the project user agent the run fails (ok false) and the records stay. The page's disclaimer: "This
  information is provided as it has been reported. It has not been independently verified by Ecology."
  Law: RCW 90.48.636(1) (2025 c 315): Ecology "must post on the website notice of the reported sewage spill" for
  every spill "reported to the department under individual water quality permits for discharges that contain
  sewage", with the estimated volume, level of treatment, date and time initiated, location, the time it ceased
  once known, "The geographic area potentially impacted" and the steps taken to contain it; (2) final information
  "Within a reasonable amount of time following the conclusion". No posting deadline in the statute; Ecology's page:
  "our goal is to publish the information within five working days". RCW 90.48.632: a sewage spill is "the
  intentional or accidental discharge of untreated or undertreated wastewater that does not meet permit
  requirements", combined sewers included. Permitted facilities only: no private backups or illegal dumping.

What is requested (privacy)
  Only these fields (outFields) are requested and kept: objectid, globalid, ecology_region, start_date_and_time,
  permitee, location, county, initial_estimated_amount, level_of_treatment, potentially_impacted_area,
  end_event_timedate, final_event_duration_hours, final_total_event_volume, link_to_5_day_report, event_type,
  event_type_other, erts_number, was_the_spill_continuous. Never requested: steps_taken_to_contain_or_clean (the
  operator's narrative, which can name staff, residents and the homes they cleaned; raw._withheld says so and the
  record links Ecology's report) and the layer's editor fields (creator and editor user names; the layer does not
  list them as fields, and they are never asked for). The geometry is not requested: every point on the layer is
  0,0 (checked 2026-11-04).
  permitee is a coded value of Ecology's facility names (data/reference/wa-ecology-facility-permits.json lists them;
  none is a person). location and potentially_impacted_area are typed by the operator: common.scrub_text runs on
  both (e-mails, phones, staff names after a title, a house number tied to a residence), and when the report (its area or
  its location) says the sewage went into a home (a private residence, a basement, a private property) every street
  address's house number in the location is removed (common.strip_house_numbers): Ecology mostly writes a hundred block, but not
  always. Every string then passes common.strip_personal (in event()) and build.redact runs over the records last.
  tests/test_ingest_wa.py proves the withheld narrative and the placeholder details never reach a record.

Record rules
  - Key: globalid (lower case, braces dropped); source_url is the layer query for that globalid with the safe fields.
  - Times: start_date_and_time and end_event_timedate are epoch milliseconds in UTC (the form's own storage; read as
    Pacific time, the starts fall in the working day), written in America/Los_Angeles with the offset,
    time_precision "minute". reported_at and published_at are null: the layer gives neither Ecology's receipt nor
    its posting time; raw._first_seen_at is our clock. source_updated_at is null (the layer's last edit time is the
    whole table's, kept in meta.layer_last_edit_at).
  - Status (the layer has no status field): an end at or after the start -> ended at that end. No end, but a final
    duration or volume posted (RCW 90.48.636(2), after the spill concludes) -> ended with no end. No end and no final
    figures -> unknown: the end is posted "once known", so a blank end says it is not posted yet, not that the
    spill goes on (most such reports are weeks old; review 2026-11-04). The status build gives either the 14-day
    caution from the start (unresolved.unknown_status_yellow_days), then "end not confirmed" to day 30. An end
    before the start stays as published with status ended (raw._end_not_used): the status build does not use it
    (status.end_not_credible) and the pages say so. A start more than a day after the read is not used
    (raw._start_not_used).
    final_event_duration_hours is free text ("about 0.5 hours", "est. 24 hours"): kept in raw, never turned into an
    end.
  - Type (event_type, from Ecology's "Spill type" and "Level of treatment"):
      Sanitary Sewer Overflow -> sso; Combined Sewer Overflow -> cso; Full Bypass -> bypass; Secondary Bypass and
      Disinfection Failure -> plant_bypass (wastewater that left the plant partly treated; RCW 90.48.632 counts it as
      a sewage spill); WWTP Overflow -> bypass when untreated, else plant_bypass; Other: the typed words name a CSO
      -> cso, else as no type. No type given: untreated sewage -> sso, partial treatment -> plant_bypass, neither
      -> unknown (parse_error). raw._type_basis says which rule applied. material is the level of treatment.
  - Water: potentially_impacted_area as typed is raw.potentially_impacted_area. reached_water: true when it names a
    water (WATER_RE: a river, creek, lake, bay, sound, inlet, slough, harbor, strait, canal, waterway ...), and the
    named waters are waterbody_text; false when it says the sewage did not reach water, stayed in a building or
    structure, or went to the ground, a road or a field, with no storm drain named; null when it names a storm
    drain, catch basin, ditch or MS4 and no water (storm systems lead to waters the report does not name), or says
    unknown. water_slugs stay empty: the status build places by name, permit and town.
  - Operator: permitee -> permit through data/reference/wa-ecology-facility-permits.json, then the Washington row of
    data/dischargers.json holding that permit (raw._discharger_basis says which); discharger_name is Ecology's
    facility name in full (the stored code is cut to 30 characters).
  - Volume: final_total_event_volume, else initial_estimated_amount (estimate_flag estimated). A plain "N gallons"
    is volume_gal; ranges, rates and words stay volume_text only.
  - History: a report that leaves the layer keeps its record with raw._missing_from_layer_since; fields that change
    between reads are kept in raw._revisions (the end and final volume arrive later).
  - No coordinates. A point comes from the registry (permit) in the status build.

Reading: the whole layer every run (72 reports from 2026-06-15 on 2026-11-04), paged by objectid. A history
backfill is not needed: the layer holds every report since the site began. An answer with fewer than half the
reports of the last good read is an outage (ok false, the records kept).

Cadence: hourly (the layer is small).
Run from pipeline/:  python -m ingest.wa_ecology_spills [--file saved.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta, read_json,
                    save_raw, scrub_text, strip_house_numbers, write_events)

SOURCE_ID = "wa-ecology-sewage-spills"
LAYER = ("https://gis.ecology.wa.gov/hosting/rest/services/Hosted/"
         "survey123_48de962d0dea40eb9485805510a40b84_results/FeatureServer/0")
PAGE_URL = "https://ecology.wa.gov/water-shorelines/water-quality/wastewater/sewage-spills"
TERMS_URL = "https://ecology.wa.gov/About-us/Accountability-transparency/Our-website/Copyright-information"
TZ = ZoneInfo("America/Los_Angeles")
SAFE_FIELDS = ["objectid", "globalid", "ecology_region", "start_date_and_time", "permitee", "location", "county",
               "initial_estimated_amount", "level_of_treatment", "potentially_impacted_area", "end_event_timedate",
               "final_event_duration_hours", "final_total_event_volume", "link_to_5_day_report", "event_type",
               "event_type_other", "erts_number", "was_the_spill_continuous"]
FREE_TEXT = ("location", "potentially_impacted_area", "event_type_other", "initial_estimated_amount",
             "final_total_event_volume", "final_event_duration_hours")
WITHHELD = ("steps_taken_to_contain_or_clean (the operator's narrative: it can name staff, residents and homes; "
            "Ecology's report, linked in raw.row.link_to_5_day_report, has it); the layer's editor fields")
FACILITIES = DATA_DIR / "reference" / "wa-ecology-facility-permits.json"
DISCHARGERS = DATA_DIR / "dischargers.json"
AUTHORITY = "Washington State Department of Ecology (sewage spill list, RCW 90.48.636)"
CAVEAT = ("Ecology: \"This information is provided as it has been reported. It has not been independently verified by "
          "Ecology.\" Permitted facilities only; Ecology aims to post a spill within five working days of the "
          "facility's report.")
PAGE_SIZE = 1000
MIN_ROWS_RATIO = 0.5

TYPE_MAP = {"sanitary sewer overflow": "sso", "combined sewer overflow": "cso", "full bypass": "bypass",
            "secondary bypass": "plant_bypass", "disinfection failure": "plant_bypass"}
WATER_WORDS = (r"river|creek|lake|bay|sound|inlet|slough|harbou?r|strait|canal|waterway|passage|narrows|ocean|"
               r"pond|reservoir|stream|channel|estuary|lagoon|cove|reach")
# a named water: up to five words before a water word ("Port Gardner Bay", "Strait Juan de Fuca", "Lake Union")
WATER_RE = re.compile(rf"\bStrait\s+(?:of\s+)?Juan\s+de\s+Fuca\b|"
                      rf"\b(?:(?:Lake|Hood|Port|Puget)\s+(?:[A-Z][\w'.-]*\s*){{1,3}}|"
                      rf"(?:[A-Z][\w'.-]*\s+){{1,4}}(?i:{WATER_WORDS})\b)")
# words after a name that make it a place, not a water ("Wind River and Rossmore Ridge neighborhoods")
NOT_A_WATER_AFTER = re.compile(r"^[^.;]{0,40}?\b(neighbou?rhoods?|subdivisions?|estates|lift station|pump station|"
                               r"road|drive|street|trail|park)\b", re.I)
GENERIC_WATER = re.compile(r"^(?:the\s+)?(?:retention|detention|storm(?:water)?|stormwater|private|local|nearby|"
                           r"unnamed)\b", re.I)
STORM_RE = re.compile(r"\b(ms4|catch\s*basins?|storm\s*(?:drains?|sewers?|water|system)|stormwater|ditch(?:es)?|"
                      r"retention pond|detention pond|curb\s*line|curbline)\b", re.I)
NO_WATER_RE = re.compile(r"(did not reach|no (?:impact to|surface|sewage left|discharge to)|not reach(?:ed)? (?:a |any )?"
                         r"(?:water|surface)|contained|private (?:residence|property|home)|residen(?:ce|tial)|"
                         r"basements?|homes?\b|building|\bground\b|soil|excavation|road(?:way)?|street|parking|vaults?|"
                         r"field|grassland|cornfield|underground|groundwater|lift station|valve box|alley)", re.I)
HOME_RE = re.compile(r"(private (?:residence|property|home)|residen(?:ce|tial)|basements?|homes?\b|homeowner)", re.I)
UNKNOWN_RE = re.compile(r"^\s*(unknown|not reported|unknown/not reported|n/?a)\s*[.;]?\s*$", re.I)
GALLONS_RE = re.compile(r"^\s*(?:~|approx\.?|approximately|about|estimated|est\.?)?\s*([\d,]+(?:\.\d+)?)\s*"
                        r"(?:gal(?:lon)?s?)?\s*$", re.I)


# ------------------------------------------------------------------------------------------------ reading the layer

def query_url(where: str) -> str:
    q = {"where": where, "outFields": ",".join(SAFE_FIELDS), "returnGeometry": "false", "orderByFields": "objectid",
         "f": "json"}
    return f"{LAYER}/query?{urllib.parse.urlencode(q)}"


def fetch(sess=None) -> tuple[list[dict], dict]:
    """Every report (safe fields only) and the layer's metadata."""
    sess = sess or requests.Session()
    meta = sess.get(f"{LAYER}?f=json", headers=HEADERS, timeout=60)
    meta.raise_for_status()
    info = meta.json()
    if "error" in info:
        raise RuntimeError(f"layer answered an error: {info['error']}")
    rows, last = [], -1
    for _ in range(100):
        r = sess.get(query_url(f"objectid > {last}"), headers=HEADERS, timeout=60)
        r.raise_for_status()
        doc = r.json()
        if "error" in doc:
            raise RuntimeError(f"query answered an error: {doc['error']}")
        page = [f.get("attributes") or {} for f in doc.get("features") or []]
        rows += page
        if not page or len(page) < PAGE_SIZE and not doc.get("exceededTransferLimit"):
            break
        nxt = max(int(a.get("objectid") or 0) for a in page)
        if nxt <= last:
            raise RuntimeError("paging did not move past the last objectid")
        last = nxt
    rows = [safe_row(a) for a in rows]
    save_raw(SOURCE_ID, json.dumps({"layer_last_edit": (info.get("editingInfo") or {}).get("lastEditDate"),
                                    "rows": rows}, indent=1), "json")
    return rows, {"layer_last_edit_ms": (info.get("editingInfo") or {}).get("lastEditDate")}


def safe_row(a: dict) -> dict:
    """Only the safe fields, the free text scrubbed (the saved raw page holds this, never the answer as fetched)."""
    out = {k: a.get(k) for k in SAFE_FIELDS}
    for k in FREE_TEXT:
        if isinstance(out.get(k), str):
            out[k] = scrub_text(out[k])
    if isinstance(out.get("location"), str) and (HOME_RE.search(str(out.get("potentially_impacted_area") or ""))
                                                  or HOME_RE.search(out["location"])):
        out["location"] = strip_house_numbers(out["location"])
    return out


def load_file(path: str) -> tuple[list[dict], dict]:
    doc = json.loads(open(path, encoding="utf-8").read())
    if isinstance(doc, dict) and "features" in doc:            # a saved query answer
        rows = [f.get("attributes") or {} for f in doc["features"]]
        last = None
    else:                                                      # our saved raw page
        rows, last = doc.get("rows") or [], doc.get("layer_last_edit")
    return [safe_row(a) for a in rows], {"layer_last_edit_ms": last}


# ------------------------------------------------------------------------------------------------ one record

def clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def when(ms) -> datetime | None:
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(int(ms) / 1000, UTC).astimezone(TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def classify(a: dict) -> tuple[str, str]:
    """(event_type, basis)."""
    t = clean(a.get("event_type")).rstrip("_").strip().lower()
    lvl = clean(a.get("level_of_treatment")).lower()
    other = clean(a.get("event_type_other"))
    raw_sewage = lvl.startswith("none")
    partial = lvl.startswith("partial")
    if t in TYPE_MAP:
        return TYPE_MAP[t], f"Ecology's spill type {a.get('event_type')!r}"
    if t == "wwtp overflow":
        return ("bypass" if raw_sewage or not partial else "plant_bypass",
                f"Ecology's spill type 'WWTP Overflow' with level of treatment {a.get('level_of_treatment')!r}")
    if t == "other" and re.search(r"cso\b|combined sewer", other, re.I):
        return "cso", f"Ecology's spill type 'Other', typed as {other!r}"
    why = "no spill type given" if not t or t == "not reported" else f"spill type {a.get('event_type')!r} ({other!r})"
    if raw_sewage:
        return "sso", f"{why}; level of treatment 'None (Raw Sewage)': read as a sewer overflow"
    if partial:
        return "plant_bypass", f"{why}; level of treatment {a.get('level_of_treatment')!r}: partly treated at a plant"
    return "unknown", f"{why}; no level of treatment"


def water_names(text: str) -> list[str]:
    out = []
    for m in WATER_RE.finditer(text or ""):
        n = clean(m.group(0)).strip(" .,;")
        if not n or GENERIC_WATER.search(n) or re.match(r"(?i)^(city|town|county)\b", n):
            continue
        if NOT_A_WATER_AFTER.match(text[m.end():]):
            continue
        if n not in out:
            out.append(n)
    return out


def reached(area: str) -> tuple[bool | None, list[str], str]:
    """(reached_water, named waters, why) from the potentially impacted area as typed."""
    t = clean(area)
    if not t or UNKNOWN_RE.match(t):
        return None, [], "the report gives the area as unknown or not reported"
    names = water_names(t)
    if re.search(r"did not reach|no (?:impact to|discharge to)[^.;]*(?:surface|water)", t, re.I):
        return False, [], "the report says the sewage did not reach surface water"
    if names:
        return True, names, "the report names the water"
    if STORM_RE.search(t):
        return None, [], "the report names a storm drain, ditch or MS4 and no water"
    if NO_WATER_RE.search(t):
        return False, [], f"the report names no water, only '{t[:60]}'"
    return None, [], "the report's area names no water"


def volume(a: dict) -> tuple[float | None, str | None, str]:
    final, first = clean(a.get("final_total_event_volume")), clean(a.get("initial_estimated_amount"))
    text, flag = (final, "unknown") if final and not UNKNOWN_RE.match(final) else (first, "estimated")
    if not text or UNKNOWN_RE.match(text):
        return None, None, "unknown"
    if re.search(r"\b(est\.?|estimated|approx|about)\b|[~<>]", text, re.I):
        flag = "estimated"
    m = GALLONS_RE.match(text)
    if m and not re.search(r"per|/|-|and", text, re.I):
        unit_said = re.search(r"gal", text, re.I) or re.search(r"gal", f"{final} {first}", re.I)
        if unit_said:
            return float(m.group(1).replace(",", "")), text, flag
        return None, f"{text} (unit not stated)", flag
    return None, text, flag


def final_posted(a: dict) -> bool:
    """Whether Ecology has posted a final duration or volume (RCW 90.48.636(2): the final information follows the
    spill's conclusion)."""
    return any(clean(a.get(k)) and not UNKNOWN_RE.match(clean(a.get(k)))
               for k in ("final_event_duration_hours", "final_total_event_volume"))


def facility_permits() -> dict:
    return (read_json(FACILITIES, {}) or {}).get("facilities") or {}


def permit_operators(rows=None) -> dict[str, str]:
    rows = rows if rows is not None else (read_json(DISCHARGERS, []) or [])
    out = {}
    for r in rows:
        if r.get("state") != "WA":
            continue
        for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
            if p:
                out.setdefault(str(p).upper(), r["id"])
    return out


def to_record(a: dict, fetched_at: str, facilities: dict, operators: dict, prev: dict | None) -> dict:
    gid = clean(a.get("globalid")).strip("{}").lower()
    notes: dict = {"_withheld": WITHHELD}
    problems = []
    fetch_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    start, end = when(a.get("start_date_and_time")), when(a.get("end_event_timedate"))
    if start and start > fetch_dt + timedelta(days=1):
        notes["_start_not_used"] = iso(start)
        problems.append("the start is more than a day after the read: not used")
        start = None
    if start and (start.hour, start.minute) == (0, 0):
        notes["_start_at_midnight"] = "the start is typed as midnight: it may be a date given without a time"
    status, ended = "unknown", None
    if end and start and end < start:
        # kept as published: the status build does not use it (status.end_not_credible) and the pages say why
        # (docs/plan.md §2, "Published end not used")
        status, ended = "ended", iso(end)
        notes["_end_not_used"] = iso(end)
        notes["_end_basis"] = "Ecology's End Date & Time, which lies before the start: published, not used"
        problems.append("the end is before the start: not used")
    elif end:
        status, ended = "ended", iso(end)
        notes["_end_basis"] = "Ecology's End Date & Time"
        if end > fetch_dt:
            notes["_end_after_fetch"] = True
    elif final_posted(a):
        status = "ended"
        notes["_end_basis"] = ("no end on the list, but Ecology has posted the final duration or volume, which RCW "
                               "90.48.636(2) adds after the spill concludes: ended, its end not posted (not invented)")
    else:
        notes["_end_basis"] = ("no end on the list and no status field: Ecology posts the end once known "
                               "(RCW 90.48.636(1)), so a blank end says the end is not yet posted, not that the spill "
                               "goes on; status unknown (not an end the site invented)")
    et, basis = classify(a)
    notes["_type_basis"] = basis
    if et == "unknown":
        problems.append("no spill type and no level of treatment")
    rw, names, why = reached(a.get("potentially_impacted_area"))
    vol, vtext, flag = volume(a)
    code = clean(a.get("permitee"))
    fac = facilities.get(a.get("permitee") or "") or facilities.get(code) or {}
    permit = fac.get("npdes_permit")
    dis = operators.get(permit) if permit else None
    notes["_discharger_basis"] = (f"Ecology's facility {code!r} -> permit {permit} ({fac.get('basis')}) -> registry row"
                                  if dis else
                                  f"Ecology's facility {code!r} -> permit {permit}: no Washington registry row holds it"
                                  if permit else f"Ecology's facility {code!r} matched no permit"
                                  + (f" ({fac.get('why')})" if fac.get("why") else ""))
    first_seen = ((prev or {}).get("raw") or {}).get("_first_seen_at") or fetched_at
    revisions = list(((prev or {}).get("raw") or {}).get("_revisions") or [])
    old_row = ((prev or {}).get("raw") or {}).get("row") or {}
    changed = {k: old_row.get(k) for k in SAFE_FIELDS if old_row and old_row.get(k) != a.get(k)}
    if changed:
        revisions.append({"seen_at": fetched_at, "before": changed})
    raw = {"row": a, "potentially_impacted_area": a.get("potentially_impacted_area"), "reached_water": rw,
           "_water_basis": why, **({"_no_water_reason": why} if rw is False else {}), "_first_seen_at": first_seen, "report_url": a.get("link_to_5_day_report"),
           "erts_number": clean(a.get("erts_number")) or None, "county": a.get("county"),
           "duration_text": a.get("final_event_duration_hours"), "continuous": a.get("was_the_spill_continuous"),
           "_time_basis": "epoch milliseconds in UTC (the form's storage), written in Pacific time", **notes}
    if revisions:
        raw["_revisions"] = revisions
    where = urllib.parse.quote("globalid='{" + gid.upper() + "}'")
    return event(source_id=SOURCE_ID, source_record_id=gid, event_type=et, status=status,
                 discharger_id=dis, discharger_name=clean(fac.get("name")) or code or None, npdes_permit=permit,
                 outfall_name=clean(a.get("location")) or None,
                 waterbody_text="; ".join(names) or None, water_slugs=[], water_match="none",
                 started_at=iso(start), ended_at=ended, time_precision="minute" if start else None,
                 reported_at=None, published_at=None, source_updated_at=None, fetched_at=fetched_at,
                 material=clean(a.get("level_of_treatment")) or None, volume_gal=vol, volume_text=vtext,
                 estimate_flag=flag, authority=AUTHORITY,
                 source_url=f"{LAYER}/query?where={where}&outFields={','.join(SAFE_FIELDS)}&f=json",
                 raw=raw, parse_error="; ".join(problems) or None)


def build(rows: list[dict], fetched_at: str, prev_records=(), facilities=None, operators=None) -> tuple[list[dict], dict]:
    facilities = facility_permits() if facilities is None else facilities
    operators = permit_operators() if operators is None else operators
    prev = {r["source_record_id"]: r for r in prev_records if isinstance(r, dict) and r.get("source_record_id")}
    out, seen = [], set()
    for a in rows:
        gid = clean(a.get("globalid")).strip("{}").lower()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        out.append(to_record(a, fetched_at, facilities, operators, prev.get(gid)))
    for k, r in prev.items():                         # a report that left the layer keeps its record
        if k not in seen:
            r = json.loads(json.dumps(r))
            r["raw"].setdefault("_missing_from_layer_since", fetched_at)
            out.append(r)
    out = redact.redact_events(out)
    out.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"rows": len(rows), "records_written": len(out),
             "by_type": dict(Counter(r["event_type"] for r in out)),
             "by_status": dict(Counter(r["status"] for r in out)),
             "reached_water": dict(Counter(str(r["raw"].get("reached_water")) for r in out)),
             "with_operator": sum(1 for r in out if r.get("discharger_id")),
             "missing_from_layer": sum(1 for r in out if r["raw"].get("_missing_from_layer_since"))}
    return out, stats


def run(file: str | None = None, out: str | None = None) -> int:
    fetched_at = now_iso()
    path = Path(out) if out else EVENTS_DIR / f"{SOURCE_ID}.json"
    prev_doc = read_json(path, {}) or {}
    prev = prev_doc.get("records") or []
    base_meta = {"credit": "Washington State Department of Ecology, Sewage spills (RCW 90.48.636)",
                 "license": "Ecology's terms: data may be used with Ecology credited as the data provider and a link to "
                            "the source page; no commercial or political use", "terms_url": TERMS_URL, "disclaimer": CAVEAT,
                 "page_url": PAGE_URL, "layer": LAYER, "time_note": "start and end as Ecology lists them (minute)"}
    try:
        rows, info = load_file(file) if file else fetch()
    except (requests.RequestException, RuntimeError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}", meta=base_meta, path=path)
        print(f"{SOURCE_ID}: failed: {e}", file=sys.stderr)
        return 1
    last_n = (prev_doc.get("meta") or {}).get("rows")
    if not rows or (last_n and len(rows) < last_n * MIN_ROWS_RATIO and not file):
        write_events(SOURCE_ID, [], ok=False, error=f"{len(rows)} reports (last good read {last_n}): an outage",
                     meta=base_meta, path=path)
        print(f"{SOURCE_ID}: {len(rows)} reports: treated as an outage", file=sys.stderr)
        return 1
    recs, stats = build(rows, fetched_at, prev)
    meta = {**base_meta, **stats, "layer_last_edit_at": iso(when(info.get("layer_last_edit_ms")))}
    meta = path_notes_to_meta(recs, meta)
    write_events(SOURCE_ID, recs, meta=meta, path=path)
    print(json.dumps({"source": SOURCE_ID, **stats}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a saved query answer or raw page (no network)")
    ap.add_argument("--out", help="write the events file here instead of data/build/events/")
    a = ap.parse_args(argv)
    return run(a.file, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
