"""EPA ECHO Sewer Overflow and Bypass Event dataset (eRule Phase 2), New England, New York, Washington DC, Georgia and
Washington State.

Source
  https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip
  (registry: fed-echo-sewer-overflow-bypass-events). ZIP of CSVs, no key, ~1.1 MB: the parent
  table sewer_overflow_bypass_report_events plus child tables (types, receiving_waters, impacts,
  causes, corrective_actions, treatment_codes) and collection_system_permits. Current version of
  each report only (the all-versions ZIP holds the revision history). These are the permittee's
  24-hour / 5-day noncompliance reports to the regulator (40 CFR 122.41(l)(6)-(7), (m)(3); part 127),
  not public notices. Coverage in New England is partial: NH (EPA-issued permits) and RI report
  here, MA barely (MWRA and one other), CT, VT and ME not at all (ME and VT have until 2028); NY
  had no rows in the 2026-10-30 file. Routine permitted wet-weather CSOs are mostly not here.

Which events are kept (one record per event that reached a water)
  The dataset has no 'reached a water' flag, so the rule is built from its fields, in order:
    1. DROP building backups: structure type BAS 'Basement Backup', impact SBB 'Sewage Backup in
       Building', or an 'Other' structure text naming a basement, bathtub, toilet or home.
    2. DROP when the receiving-water field says there was none ('none', 'n/a', 'No water body',
       'No discharge was sent to the river' ...).
    3. KEEP when a receiving water is named (an unnamed brook or wetland counts as a water).
    4. KEEP when an impact is to a water: AHI aquatic habitat, ALI aquatic life, SBC shellfish bed,
       BEC beach, DWC drinking water; or the 'Other' impact/description text names a river, brook,
       stream, pond, harbor, bay, cove, waterway or storm drain.
    5. KEEP bypass events (the diverted flow leaves the plant through its permitted outfall) and
       CSO events at a CSO outfall or regulator (structure 'CSO Outfall', or 'Other' text naming a
       CSO, regulator or outfall).
    6. DROP the rest: SSOs, and CSO-type overflows from manholes or broken pipes, with no receiving
       water and only land or no-observable impacts.
  Dropped events go to data/build/echo-sewer-overflow-dropped.json with the reason, for review.

Mapping
  event_type from the types table: CSO -> cso, SSO -> sso, BYP -> bypass (first by sequence; a
  report with several types keeps them in raw.types). Start/end are given without a timezone:
  they are recorded as given, naive ('2025-09-09T20:30:00', time_precision minute, raw.timezone_note),
  presumably local time. Extreme-event reports (G9B) have no per-event times: the report period
  is used (time_precision day). status: ended when an end is given, else unknown (never ongoing:
  the report is filed after the fact). reported_at = program_report_received_date (date only).
  published_at = the extract date (ZIP entry date of the events table); source_updated_at = the
  ZIP's HTTP Last-Modified. Volume in gallons; estimate_flag measured for automated/manual
  measurement, estimated for best professional judgement/modeling. Coordinates are the event's own.
  water_slugs: CSO events via data/outfalls-ne.json (permit + permitted feature), else the
  receiving-water name against data/waters-ne.csv in the permit's state (bbox tiebreak).
  source_record_id = permit:form_set_id:event_id_ext (stable across report versions).

Failures
  A failed download (the research copy then stands in only on a first run with no previous
  records), or an extract missing any expected table, writes ok=False with the error; the previous
  records stay and the dropped-events file is not rewritten.

Washington DC (permit DC0021199, DC Water; research/dc/report.md section 2.3)
  EPA writes DC's permit, so DC Water files its SSO/CSO noncompliance reports here: 140 current rows
  (2023-03 to 2026-09) with coordinates, times and gallons; Maryland and Virginia have none yet.
  - Receiving water is free text ('soapstone', 'Hickory Run', 'Watts Branch Creek', 'Rock Creek ' with
    a trailing space, 'ROCK CREEK', 'Anacostia river'). DC_WATER_ALIASES (from research/dc/waters-dc.json)
    normalises each name to the NHD name of the DC water record, so waterbody_text reads 'Hickey Run'
    for 'Hickory Run'. The text as reported stays in raw.receiving_waters; raw.receiving_water_aliases
    says what was changed. A name that is not in the table is kept as typed.
  - Rows whose point lies outside the District (the Potomac Interceptor collapse of 2026-01-19, in
    Montgomery County, Maryland, reported under DC0021199) get raw.state 'MD' and raw.state_basis
    (a point in Virginia would get MD too and stay unplaced); npdes_permit and discharger stay DC Water's (docs/decisions.md,
    Washington DC item 3: reported in Maryland, operator unchanged). The point is tested against the
    DC GIS boundary (ingest/dc_waters.py), which takes in the Potomac to the Virginia shore. status.py's
    event_state reads a two-letter raw.state before the permit prefix (review 2026-11-03 P1-2), so these rows
    are placed, guarded and counted in Maryland.
  - Revisions are NOT read: this module uses the current-version ZIP only, so a report is seen in its
    latest version (the Interceptor row: no volume on 20 January, 217 gal on 3 February, 242,000,000 gal
    on 16 April; the three 3 February rows 291.70 to 291,667 gal). The all-versions ZIP (revision_history
    in research/dc/events.json) is not downloaded or parsed here; a build that reads it would link the
    versions by parent_event_id.
  - The CSO-typed rows with a feature number (structure 'CSO Outfall') look the outfall up in
    data/outfalls-ne.json only, which has no DC rows, so they are placed by name or point; DC's outfalls
    are in data/outfalls-mid-atlantic.json (scripts/match_outfalls.py).

Georgia (permits GA...; research/ga/report.md section 2.2; the state is not live until data/rules.json says so)
  Georgia permittees file their 24-hour and 5-day spill reports in EPD's GEOS, and these reach this dataset: 1,232
  current GA rows from 90 permits in the 2026-11-03 extract (887 kept, from 83 permits), with start and end times and receiving waters but no
  volume (the volume field is empty on every GA row). Two Georgia habits are handled here:
  - The receiving-water field often says the spill did not reach a water ('DID NOT ENTER STATE WATERS', 'did not
    reach waters', misspelt variants): NO_WATER_TEXT reads these as "receiving water stated as none" (dropped, like
    'none'). No row of another state used these words in that extract. STATE_NO_WATER["GA"] adds Georgia's other
    wordings for no water ('Dry land', 'N/A dry land', 'Not Appicable', 'Bulding Basement', 'DID NOT DISCHARGE TO
    STATE WATERS'), read for GA permits only. Storm drains, MS4 systems and catch basins stay waters, as everywhere.
  - The point is mostly the permit's own (the plant or the utility's office), not the spill's: in that extract 757 of
    887 kept GA events share a point with four or more other events of the same permit. For the states in
    REPEATED_POINT_STATES a point that REPEATED_POINT_MIN or more kept events of one permit share is not used for
    those events (lat/lon null; raw.reported_point keeps it and raw.point_note says why), unless the event is a
    bypass (a plant bypass happens at the plant). The live states are not in the set.
  The state's own list (ingest/ga_epd_spills.py, run after this module) is the public record where both describe a
  spill: it takes the end from the EPA record and marks that record duplicate_of its own, in this module's file.

Washington State (permits WA...; research/wa/report.md section 2.3; not live until data/rules.json says so)
  Two permittees report here (2026-11-03 extract: 36 current rows): American Water Military Services at Joint Base
  Lewis-McChord (WA0021954, an EPA-issued federal-facility permit, which Ecology's own spill list need not carry) and
  the City of Puyallup (WA0037168). Their SSO reports name no receiving water and give the event's own point (no
  point shared by many reports), so the general rules apply unchanged: an SSO with no receiving water and only land
  impacts is dropped, a bypass that names Puget Sound is kept. Ecology's list (ingest/wa_ecology_spills.py) is the
  state's public record for the permits it carries.

Lag and cadence
  'The data are refreshed daily' (extract ~07:10 ET); event-to-receipt lag in NE: median 2-3 days,
  90th percentile 6-7 days (NH, MA), 38 days (RI), so weeks of lag overall. Poll daily.

Run from pipeline/:  python -m ingest.echo_sewer_overflow_events
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import common
from common import (BUILD_DIR, DATA_DIR, HEADERS, ROOT, event, now_iso, read_json, save_raw,
                    write_events, write_json)

SOURCE_ID = "echo-sewer-overflow"
URL = "https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip"
FALLBACK_DIR = ROOT / "research" / "federal" / "raw" / "sobe_current"
STATES = {"CT", "MA", "ME", "NH", "RI", "VT", "NY", "DC", "GA", "WA"}
# states whose reports mostly carry the permit's point rather than the event's (module docstring, Georgia)
REPEATED_POINT_STATES = {"GA"}
REPEATED_POINT_MIN = 5
AUTHORITY = "EPA ECHO Sewer Overflow and Bypass Event report (reported to regulators)"
SUMMARY_URL = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"

TYPE_MAP = {"CSO": "cso", "SSO": "sso", "BYP": "bypass"}
MATERIAL = {"cso": "combined sewage and stormwater", "sso": "untreated sewage",
            "bypass": "wastewater diverted around part of the treatment process"}
MEASURED = {"Automated Remote Monitoring", "Manual Direct Measurement"}
ESTIMATED = {"Best Professional Judgement", "Modeling"}
WATER_IMPACTS = {"AHI", "ALI", "SBC", "BEC", "DWC"}
BUILDING_TEXT = re.compile(r"basement|bathtub|bathroom|toilet|\bhome\b|\bhouse\b|residential", re.I)
NO_WATER_TEXT = re.compile(r"^\s*(none|n/?a|no water ?body|no discharge.*|no direct discharge.*|not applicable|"
                           r"did\s*n\S*\s+(?:enter|reach)\b.*)\s*\.?\s*$", re.I)
# Georgia reports' own ways of saying no water was reached (dry land, misspelt "not applicable", a basement), read
# only for GA permits so the live states' rows are untouched
STATE_NO_WATER = {"GA": re.compile(r"^\s*((?:n/?a\s+)?dry\s*land(?:\s+spill)?|n[o0][a-z]?t?\s+ap+l?i?c\w*|non\s+applicable|"
                                   r"bu\w*ding\s+basement|did\s*n\S*\s+discharge\b.*)\s*\.?\s*$", re.I)}


def no_water(w: str, state: str | None = None) -> bool:
    """The receiving-water text says there was none (NO_WATER_TEXT, and the state's own wordings)."""
    pat = STATE_NO_WATER.get(state or "")
    return bool(NO_WATER_TEXT.match(w) or (pat and pat.match(w)))
WATER_WORDS = re.compile(r"\b(river|brook|stream|creek|pond|lake|harbou?r|bay|cove|waterway|body of water|"
                         r"storm ?drain|catch basin|wetland|swamp|ocean)\b", re.I)
OUTFALL_TEXT = re.compile(r"\bcso\b|regulator|outfall", re.I)
TZ_NOTE = "ECHO gives event times without a timezone; recorded as given (presumably local time)"

TABLES = {
    "events": "sewer_overflow_bypass_report_events.csv",
    "types": "sewer_overflow_bypass_types.csv",
    "waters": "sewer_overflow_bypass_receiving_waters.csv",
    "impacts": "sewer_overflow_bypass_impacts.csv",
    "causes": "sewer_overflow_bypass_causes.csv",
    "actions": "sewer_overflow_bypass_corrective_actions.csv",
    "treatment": "sewer_overflow_treatment_codes.csv",
    "systems": "collection_system_permits.csv",
}


# --------------------------------------------------------------------------- DC names and state

def _alias_key(text: str) -> str:
    """Lower case, '&' as 'and', punctuation dropped, spaces collapsed: 'Rock Creek ' == 'ROCK CREEK'."""
    t = (text or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


# Free-text receiving waters in DC Water's reports and in ECHO's inventory -> the NHD name of the DC
# water record (research/dc/waters-dc.json, name and source_aliases). Keys are _alias_key() forms.
# 'Soapstone Valley stream' has no NHD name (it is the research record's name; no record is built yet).
# The Piney Branch address is the research file's alias for a row that gave an address as its water.
DC_WATER_ALIASES = {
    "potomac river": "Potomac River", "potomac river east side": "Potomac River",
    "anacostia river": "Anacostia River", "anacostia river east side": "Anacostia River",
    "anacostia river west side": "Anacostia River", "lower anacostia river": "Anacostia River",
    "anacostia": "Anacostia River",
    "rock creek": "Rock Creek", "rock creek east side": "Rock Creek", "rock creek west side": "Rock Creek",
    "piney branch": "Piney Branch", "park rd piney branch pky nw": "Piney Branch",
    "broad branch": "Broad Branch",
    "soapstone": "Soapstone Valley stream", "soapstone stream": "Soapstone Valley stream",
    "soapstone valley stream": "Soapstone Valley stream",
    "washington channel": "Washington Channel", "washington ship channel": "Washington Channel",
    "oxon run": "Oxon Run",
    "watts branch": "Watts Branch", "watts branch creek": "Watts Branch",
    "hickey run": "Hickey Run", "hickory run": "Hickey Run",
    "pope branch": "Pope Branch",
    "pinehurst branch": "Pinehurst Branch", "fenwick branch": "Fenwick Branch", "piney run": "Piney Run",
    "barnaby run": "Barnaby Run", "maddox branch": "Maddox Branch",
    "chesapeake and ohio canal": "Chesapeake and Ohio Canal", "c and o canal": "Chesapeake and Ohio Canal",
    "beaverdam creek": "Beaverdam Creek",
    "tidal basin": "Tidal Basin", "kingman lake": "Kingman Lake",
}


def normalise_dc_water(name: str) -> str:
    """The NHD name for a DC receiving-water text; the text itself, stripped, when it is not in the table."""
    return DC_WATER_ALIASES.get(_alias_key(name), (name or "").strip())


OUT_OF_DISTRICT_BASIS = ("point outside the District: DC Water's Potomac Interceptor runs through Maryland and "
                         "its overflows are reported in Maryland, operator unchanged (owner-decision default, Washington DC item 3)")


def dc_row_state(lat, lon) -> tuple[str | None, str | None]:
    """('MD', basis) for a DC0021199 row whose point lies outside the District (the Potomac Interceptor
    collapse of 2026-01-19 is in Montgomery County); (None, None) inside the District or with no point.
    The decision names Maryland. A point in Virginia (the Interceptor also runs through Loudoun and
    Fairfax) would get MD too and then fail the placement guard (no Maryland water near it), so it stays
    unplaced rather than landing on a wrong water. The District outline is the DC GIS boundary
    (ingest/dc_waters.py), which takes in the Potomac to the Virginia shore."""
    if lat is None or lon is None:
        return None, None
    from ingest.dc_waters import in_district
    return (None, None) if in_district(lat, lon) else ("MD", OUT_OF_DISTRICT_BASIS)


# --------------------------------------------------------------------------- fetch

def fetch() -> tuple[dict[str, list[dict]], dict]:
    """Tables from the live ZIP, or from the research copy when the download fails."""
    info: dict = {"url": URL}
    try:
        r = requests.get(URL, headers=HEADERS, timeout=180)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        lm = r.headers.get("Last-Modified")
        info["last_modified"] = parsedate_to_datetime(lm).isoformat().replace("+00:00", "Z") if lm else None
        prev = (read_json(BUILD_DIR / "events" / f"{SOURCE_ID}.json", {}) or {}).get("meta", {})
        if prev.get("last_modified") and prev.get("last_modified") == info["last_modified"]:
            info["raw_saved"] = None   # same extract as last run: no second copy
        else:
            info["raw_saved"] = str(save_raw(SOURCE_ID, r.content, "zip").relative_to(ROOT))
        info["via"] = "live"
        names = {Path(n).name: n for n in zf.namelist()}
        zi = zf.getinfo(names[TABLES["events"]])
        info["extract_date"] = datetime(*zi.date_time).date().isoformat()
        tables = {k: list(csv.DictReader(io.TextIOWrapper(zf.open(names[v]), encoding="utf-8-sig")))
                  for k, v in TABLES.items() if v in names}
        return tables, info
    except (requests.RequestException, zipfile.BadZipFile, KeyError) as e:
        print(f"warn: ECHO download failed ({e}); using {FALLBACK_DIR}", file=sys.stderr)
        info.update(via="research copy", last_modified=None, error=f"ECHO download: {type(e).__name__}: {e}")
        zpath = FALLBACK_DIR / "current_sewer_overflow_and_collection_systems_tables.zip"
        if zpath.exists():
            zf = zipfile.ZipFile(zpath)
            zi = zf.getinfo(TABLES["events"])
            info["extract_date"] = datetime(*zi.date_time).date().isoformat()
        tables = {}
        for k, v in TABLES.items():
            p = FALLBACK_DIR / v
            if p.exists():
                with open(p, encoding="utf-8-sig", newline="") as f:
                    tables[k] = list(csv.DictReader(f))
        if "events" not in tables:
            raise RuntimeError(f"ECHO download failed and no research copy: {e}") from e
        return tables, info


# --------------------------------------------------------------------------- lookups

def by_event(rows: list[dict] | None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows or []:
        out[r["sewer_overflow_bypass_event_key"]].append(r)
    return out


def discharger_index() -> dict[str, dict]:
    idx = {}
    for f in sorted((ROOT / "research").glob("*/dischargers.json")):
        rows = read_json(f, []) or []
        for r in rows if isinstance(rows, list) else rows.get("dischargers", []):
            if r.get("npdes_permit"):
                idx.setdefault(r["npdes_permit"], r)
    return idx


class Waters:
    """Receiving-water name -> openboatlaunch slug, in the permit's state; registry for outfalls."""

    def __init__(self):
        self.by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
        bbox = {}
        for st in ("ct", "ma", "me", "nh", "ri", "vt"):
            for w in (read_json(DATA_DIR / f"waters-{st}.json", {}) or {}).get("waters", []):
                bbox[w["slug"]] = w.get("bbox")
        with open(DATA_DIR / "waters-ne.csv", newline="") as f:
            for r in csv.DictReader(f):
                r["bbox"] = bbox.get(r["slug"])
                self.by_name[(r["state"], self.key(r["name"]))].append(r)
        self.keys: dict[str, list[str]] = defaultdict(list)
        for st, k in self.by_name:
            self.keys[st].append(k)
        reg = read_json(DATA_DIR / "outfalls-ne.json", {}) or {}
        self.outfalls = {(o["npdes_permit"], str(o["outfall"]).zfill(3)): o for o in reg.get("outfalls", [])}

    @staticmethod
    def key(name: str) -> str:
        s = (name or "").lower().replace("&", " and ")
        s = re.sub(r"\bwbid\b|\bestuar(y|ies)\s*:", " ", s)
        s = re.sub(r"\s+via\s+.*$", "", s)
        return re.sub(r"[^a-z0-9]", "", s)

    def by_text(self, text: str, state: str, lat, lon) -> list[str]:
        slugs = []
        parts = re.split(r",|;|\band\b|/", text or "")
        for part in [text or ""] + parts:
            hits = self.by_name.get((state, self.key(part)), [])
            if not hits and len(self.key(part)) >= 8:   # spelling slips: 'Conncecticut River'
                close = difflib.get_close_matches(self.key(part), self.keys.get(state, []), n=2, cutoff=0.92)
                if len(close) == 1:
                    hits = self.by_name[(state, close[0])]
            if hits and lat is not None:   # a same-named water elsewhere in the state is not this one
                pad = .02 if len(hits) > 1 else .05
                hits = [h for h in hits if h["bbox"] and h["bbox"][0] - pad <= lon <= h["bbox"][2] + pad
                        and h["bbox"][1] - pad <= lat <= h["bbox"][3] + pad]
            if len(hits) == 1 and hits[0]["slug"] not in slugs:
                slugs.append(hits[0]["slug"])
            if slugs and part == (text or ""):
                break   # the whole text matched one water
        return slugs


# --------------------------------------------------------------------------- rule

def reached_water(ev: dict, types: list[str], waters: list[str], impacts: list[dict],
                  state: str | None = None) -> tuple[bool, str]:
    struct = ev.get("sewer_overflow_structure_type_code") or ""
    other = ev.get("sewer_overflow_structure_type_code_other_text") or ""
    codes = {i["sewer_overflow_bypass_impact_code"] for i in impacts}
    real_waters = [w for w in waters if w.strip() and not no_water(w, state)]
    if struct == "BAS" or "SBB" in codes or (struct == "OTH" and BUILDING_TEXT.search(other)):
        if not real_waters:
            return False, "building backup"
    if waters and not real_waters:
        return False, "receiving water stated as none"
    if real_waters:
        return True, "receiving water named"
    if codes & WATER_IMPACTS:
        return True, "impact to a water (" + ",".join(sorted(codes & WATER_IMPACTS)) + ")"
    texts = " ".join([i.get("sewer_overflow_bypass_impact_other_text") or "" for i in impacts]
                     + [ev.get("sewer_overflow_bypass_description_text") or ""])
    m = WATER_WORDS.search(texts)
    if m:
        return True, f"text names a water ({m.group(0).lower()})"
    if "BYP" in types:
        return True, "bypass (leaves the plant through its permitted outfall)"
    if "CSO" in types and (struct == "CSO" or (struct == "OTH" and OUTFALL_TEXT.search(other))):
        return True, "CSO at a CSO outfall or regulator"
    return False, "no evidence the discharge reached a water"


# --------------------------------------------------------------------------- records

def naive(ts: str | None) -> str | None:
    ts = (ts or "").strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).isoformat()
    except ValueError:
        return None


def build(tables: dict, info: dict) -> tuple[list[dict], list[dict], Counter]:
    types, rws, imps = by_event(tables.get("types")), by_event(tables.get("waters")), by_event(tables.get("impacts"))
    causes, acts, treat = by_event(tables.get("causes")), by_event(tables.get("actions")), by_event(tables.get("treatment"))
    systems = {(s["permit_identifier"], s["collection_system_identifier"]): s for s in tables.get("systems", [])}
    disc = discharger_index()
    W = Waters()
    kept, dropped, why = [], [], Counter()
    for ev in tables["events"]:
        permit = ev["permit_identifier"]
        state = permit[:2]
        if state not in STATES:
            continue
        k = ev["sewer_overflow_bypass_event_key"]
        t_rows = sorted(types.get(k, []), key=lambda r: int(r.get("sewer_overflow_bypass_type_code_sequence") or 0))
        t_codes = [r["sewer_overflow_bypass_type_code"] for r in t_rows]
        w_names = [r["name_receiving_water"] for r in rws.get(k, [])]
        i_rows = imps.get(k, [])
        ok, reason = reached_water(ev, t_codes, w_names, i_rows, state)
        why[(state, "kept" if ok else "dropped", reason)] += 1
        srid = f"{permit}:{ev['program_report_form_set_id']}:{ev['sewer_overflow_bypass_event_id_ext'] or '0'}"
        if not ok:
            dropped.append({"source_record_id": srid, "permit": permit, "reason": reason,
                            "type": t_codes, "structure": ev.get("sewer_overflow_structure_type_desc"),
                            "impacts": [i["sewer_overflow_bypass_impact_desc"] for i in i_rows],
                            "receiving_water": w_names, "start": ev.get("sewer_overflow_bypass_start_datetime"),
                            "description": ev.get("sewer_overflow_bypass_description_text")})
            continue

        etype = TYPE_MAP.get(t_codes[0], "unknown") if t_codes else "unknown"
        perr = None if t_codes else "no type row for this event"
        start, end = naive(ev["sewer_overflow_bypass_start_datetime"]), naive(ev["sewer_overflow_bypass_end_datetime"])
        precision = "minute"
        extreme = ev.get("program_report_npdes_data_group_number_code") == "G9B"
        if extreme and not start:
            start, end, precision = (ev.get("program_report_start_date") or None), (ev.get("program_report_end_date") or None), "day"
        if not start:
            perr = (perr + "; " if perr else "") + "no start time"
            precision = None
        vol = ev.get("sewer_overflow_bypass_discharge_volume_gallons")
        try:
            vol_gal = int(round(float(vol))) if vol not in (None, "") else None
        except ValueError:
            vol_gal = None
        qm = ev.get("discharge_quantification_method_desc") or ""
        flag = "measured" if qm in MEASURED else "estimated" if qm in ESTIMATED else "unknown"
        try:
            lat, lon = float(ev["latitude_measure"]), float(ev["longitude_measure"])
            if lat == 0 and lon == 0:
                lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        outfall = (ev.get("permitted_feature_identifier") or "").strip() or None
        slugs, how, coord_src = [], "none", "source" if lat is not None else None
        reg = W.outfalls.get((permit, outfall.zfill(3))) if outfall and etype == "cso" else None
        if reg and reg.get("water_slug"):
            slugs, how = [reg["water_slug"]], "outfall_registry"
        real_w = [w.strip() for w in w_names if w.strip() and not no_water(w, state)]
        w_aliases = {}
        if state == "DC":   # free text -> the NHD name; what was typed stays in raw.receiving_waters
            w_aliases = {w: normalise_dc_water(w) for w in w_names if w.strip() and not NO_WATER_TEXT.match(w)
                         and normalise_dc_water(w) != w}
            real_w = list(dict.fromkeys(normalise_dc_water(w) for w in real_w))
        dc_state, dc_basis = dc_row_state(lat, lon) if state == "DC" else (None, None)
        if not slugs and real_w:
            for w in real_w:
                for s in W.by_text(w, state, lat, lon):
                    if s not in slugs:
                        slugs.append(s)
            how = "name" if slugs else "none"
        if lat is None and reg and reg.get("lat") is not None:
            lat, lon, coord_src = reg["lat"], reg["lon"], "outfall_layer"
        sysrow = systems.get((permit, ev.get("collection_system_identifier") or ""), {})
        d = disc.get(permit, {})
        dname = d.get("name") or (reg or {}).get("permittee") or sysrow.get("collection_system_name") or None
        raw = {k2: v for k2, v in ev.items() if v not in ("", None)}
        raw.update({
            "types": [r["sewer_overflow_bypass_type_desc"] for r in t_rows],
            "receiving_waters": w_names,
            "impacts": [{"code": i["sewer_overflow_bypass_impact_code"], "desc": i["sewer_overflow_bypass_impact_desc"],
                         "other": i.get("sewer_overflow_bypass_impact_other_text") or None} for i in i_rows],
            "causes": [{"code": c["sewer_overflow_bypass_cause_code"], "desc": c["sewer_overflow_bypass_cause_desc"],
                        "other": c.get("sewer_overflow_bypass_cause_other_text") or None} for c in causes.get(k, [])],
            "corrective_actions": [{"code": a["sewer_overflow_bypass_corrective_action_code"],
                                    "desc": a["sewer_overflow_bypass_corrective_action_desc"],
                                    "other": a.get("sewer_overflow_bypass_corrective_action_other_text") or None}
                                   for a in acts.get(k, [])],
            "treatment": [{"code": t.get("sewer_overflow_treatment_code") or None,
                           "desc": t.get("sewer_overflow_treatment_desc") or None,
                           "bypassed_equipment": t.get("bypass_treatment_plant_equipment_desc") or None}
                          for t in treat.get(k, [])],
            "collection_system_name": sysrow.get("collection_system_name"),
            "percent_collection_system_css": sysrow.get("percent_collection_system_css"),
            "reached_water_rule": reason, "timezone_note": TZ_NOTE, "report_version": ev.get("program_report_form_id"),
        })
        if w_aliases:
            raw["receiving_water_aliases"] = w_aliases
        if dc_state:   # placement state differs from the permit's; the operator stays DC Water
            raw["state"], raw["state_basis"] = dc_state, dc_basis
        if extreme:
            raw["extreme_event_note"] = "G9B extreme-event report: spills too numerous to list; times are the report period"
        kept.append(event(
            source_id=SOURCE_ID, source_record_id=srid, event_type=etype,
            status="ended" if end else "unknown",
            discharger_id=d.get("id"), discharger_name=dname, npdes_permit=permit,
            outfall_id=outfall if etype in ("cso", "bypass") else None,
            outfall_name=(reg or {}).get("outfall_name") or None,   # the description text stays in raw
            waterbody_text="; ".join(real_w) or None, water_slugs=slugs, water_match=how,
            lat=lat, lon=lon, coord_source=coord_src,
            started_at=start, ended_at=end, time_precision=precision,
            reported_at=ev.get("program_report_received_date") or None,
            published_at=info.get("extract_date"), source_updated_at=info.get("last_modified"),
            material=MATERIAL.get(etype), volume_gal=vol_gal,
            volume_text=(f"{vol_gal:,} gallons" + (f" ({qm})" if qm else "")) if vol_gal is not None else None,
            estimate_flag=flag, authority=AUTHORITY,
            source_url=f"https://echo.epa.gov/detailed-facility-report?fid={permit}&sys=ICP",
            raw=raw, parse_error=perr,
        ))
    repeated_points(kept)
    kept.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    return kept, dropped, why


def repeated_points(kept: list[dict]) -> int:
    """For REPEATED_POINT_STATES: a point REPEATED_POINT_MIN or more kept events of one permit share is the permit's
    location, not the spill's; it is moved to raw.reported_point (bypasses keep it). Returns the events changed."""
    shared = Counter((r["npdes_permit"], r["lat"], r["lon"]) for r in kept
                     if r["lat"] is not None and r["npdes_permit"][:2] in REPEATED_POINT_STATES)
    n = 0
    for r in kept:
        k = (r["npdes_permit"], r["lat"], r["lon"])
        if r["lat"] is None or shared.get(k, 0) < REPEATED_POINT_MIN or r["event_type"] == "bypass":
            continue
        r["raw"]["reported_point"] = [r["lat"], r["lon"]]
        r["raw"]["point_note"] = (f"the same point is given for {shared[k]} reports of this permit: taken as the "
                                  "permit's location, not the spill's")
        r["lat"] = r["lon"] = r["coord_source"] = None
        n += 1
    return n


def write_failed(records: list[dict], error: str, meta: dict) -> Path:
    """ok=False with the error. The previous records stay (common.write_events); only on a first run
    with nothing to keep are the research-copy records written, still marked ok=False."""
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = read_json(path, {}) or {}
    if prev.get("records") or not records:
        return write_events(SOURCE_ID, [], ok=False, error=error, meta=meta)
    write_json(path, {"source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": False, "error": error,
                      "last_ok_at": prev.get("last_ok_at"), "meta": meta, "count": len(records), "records": records})
    return path


def main(argv=None) -> int:
    try:
        tables, info = fetch()
    except RuntimeError as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    errors = [info["error"]] if info.get("error") else []
    missing = [TABLES[k] for k in TABLES if k not in tables]
    if missing:
        errors.append("tables missing from the extract: " + ", ".join(missing))
    kept, dropped, why = build(tables, info)
    meta = {"registry_ids": ["fed-echo-sewer-overflow-bypass-events"], "states": sorted(STATES),
            "extract_date": info.get("extract_date"), "last_modified": info.get("last_modified"),
            "via": info.get("via"), "raw_saved": info.get("raw_saved"),
            "kept": len(kept), "dropped": len(dropped),
            "by_rule": [{"state": s, "outcome": o, "reason": r, "count": n} for (s, o, r), n in sorted(why.items())],
            "cadence": "daily (ECHO refresh ~07:10 ET); event-to-receipt lag days to weeks", "errors": errors}
    if errors:
        path = write_failed(kept, "; ".join(errors), meta)
        print(f"{SOURCE_ID}: run not ok ({'; '.join(errors)}) -> {path}", file=sys.stderr)
        return 1
    write_json(BUILD_DIR / "echo-sewer-overflow-dropped.json",
               {"source_id": SOURCE_ID, "fetched_at": now_iso(), "rule": "see ingest/echo_sewer_overflow_events.py docstring",
                "count": len(dropped), "dropped": dropped})
    path = write_events(SOURCE_ID, kept, meta=meta)
    print(f"{SOURCE_ID}: {len(kept)} kept, {len(dropped)} dropped ({info.get('via')}, extract {info.get('extract_date')}) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
