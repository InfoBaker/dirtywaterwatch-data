"""NC DEQ Division of Water Resources sanitary sewer overflows -> data/build/events/nc-dwr-sso-2026.json
(and, with --backfill, data/build/events/nc-dwr-sso-2022-2025.json).

Source
  North Carolina Department of Environmental Quality, Division of Water Resources (DWR), "Sanitary Sewer
  Overflow Tracking Map" (ArcGIS Experience 4a50b5dc87844bab9930a5906522a779), public feature layers in the
  DEQ ArcGIS organisation, queried as JSON (where 1=1, the fields below, paged by object id; 2,000 a page):
    - this year: Sanitary_Sewer_Overflows_since_Jan_2026/FeatureServer/0 (layer title "SSOs and Bypasses";
      571 rows on 2026-11-04, January to October 2026). DWR scopes the layer by year, so a layer named
      Sanitary_Sewer_Overflows_since_Jan_<year> is looked up in the organisation's service list on every run
      and every one found is read (a 2027 layer joins without a code change; the events file says which were
      read in meta.layers).
    - history (--backfill, once): Sanitary_Sewer_Overflows_September_2022_through_December_2025/FeatureServer/0
      (3,208 rows; frozen, last edited 2026-03-09). Different field names; written to its own events file
      (source id nc-dwr-sso-2022-2025) so each record cites the layer it came from.
    - 2026-11-05: the this-year layer stopped answering. Its URL (and the service's) answers 400 "Item does not exist
      or is inaccessible" (CONT_0001), where a name never used answers "Invalid URL", so the service appears to exist
      but is no longer shared; its item 8008044d5ef8446b902a083820fe85f9 answers the same. On 2026-11-06 no replacement
      is public: the organisation's service list (1,066 services) has no other sewer overflow layer (only the
      history layer and Report_an_SSO_Public_View, the Survey123 intake view last edited 2026-02-18); an ArcGIS
      Online search of the organisation and of "Sanitary Sewer Overflows" finds only the history layer, the viewer
      and its web map; the Tracking Map's web map (item 20b6faf89710464bb6e009b44fbc63dc, VIEWER_MAP) still points at
      the 2026 URL; DEQ's "Information on Sewer System Overflows" page still links the same viewer. So each run also
      reads the layers the viewer's web map shows (a republished layer the viewer is pointed at is followed, if it
      has this layer's field names: KEY_FIELDS, never a guessed mapping), and when every layer answers CONT_0001 the
      run writes ok=False with a plain "source unavailable" error, meta.unavailable and meta.unavailable_since; the
      records already read are kept.
  Every reportable overflow appears: 1,000 gallons or more to the ground, or any amount reaching surface
  water (the DWR reporting rule; permit conditions). No licence; the item says the data "cannot be construed
  to be a legal document". Credit: NC DEQ Division of Water Resources.

Record rules (this year's layers)
  - One record per row, event_id nc-dwr-sso-2026:<globalid> (stable within the layer). Rows that leave the
    layer are kept (raw._missing_from_layer_since): the events file is the history seen so far.
  - event_type: deq_program "Bypass" -> bypass, else sso (every row on 2026-11-04 says Sanitary Sewer
    Overflow, though the layer title says bypasses are included).
  - Times: epoch milliseconds in true UTC (checked 2026-11-04: report times cluster 12:00-21:00 UTC, office
    hours in Eastern time, and the 1,143,800-gallon Raleigh overflow of 2026-05-12 starts at 12:21 UTC, the
    8:21 a.m. EDT start Raleigh Water published). Written in America/New_York, time_precision "minute".
  - Two reports per row: the 24-hour report (dwr_start_date, dwr_end_date, dwr_ongoing, dwr_volume ...) and,
    once filed, the operator's written 5-day report (..._5d). The record takes the cautious reading of the
    two: the earlier start, the later end (an end before the start is not used), the larger volume, and
    "reached water" when either says so. Both sets stay in raw, and raw._times_basis says which was used.
  - Status: an end from either report -> ended; no end and dwr_ongoing "Yes" -> ongoing; no end and
    dwr_ongoing "No" -> ended with ended_at null (DWR says it stopped but gives no time; the status build
    treats it as an unconfirmed end). No end is ever invented.
  - Receiving water: dwr_waterbody is "<name> - <DWR stream index>" ("Salem Creek - 13-17-36-15"): the name
    is waterbody_text and the index raw._stream_index; else the 5-day report's water; else the unlisted-water
    text ("UT to X" is written "Unnamed tributary to X"; the source text stays in raw). raw.reached_water is
    true, false or null from "Reached Surface Water" (either report): a row that says No is kept and is not
    placed on a water. water_slugs is empty (North Carolina has no water records yet; placement by name and
    point is done by the status build).
  - Operator: the permit (WQCS..., a state collection-system permit) is npdes_permit; discharger_id is the
    data/dischargers.json row that holds the permit (public or private: a utility company, an association, a park
    is an operator like any other), else null; discharger_name is the layer's facility name. A record with no
    operator row says why in raw._discharger_basis: no permit number in DWR's record (an operator is never inferred
    from a place, a facility or an owner name), or no operator on record for the permit yet.
  - Coordinates: deq_latitude / deq_longitude (DWR's point for the reported address), coord_source "source";
    a point outside North Carolina's bounding box is dropped (raw._coords_rejected).
  - reported_at is dwr_report_date (when DWR logged the report). No publication time: published_at null; the
    first time this module saw a row is raw._first_seen_at (our clock). The layer's last edit is in meta.

Record rules (history layer, --backfill)
  - event_id nc-dwr-sso-2022-2025:<incident_number> (the BIMS incident number; a repeated number takes
    -<OBJECTID>). end_date repeats start_date on every row of this layer, so it is not an end: ended_at is
    null and status "ended" (the layer holds closed incidents; raw._end_basis says so). 240 rows have no start
    (started_at null; reported_at is report_date). volume and volume_reach_water as given.
  - 76 incidents of 2026 are in both layers: the history copy is duplicate_of this year's record.

Duplicates within this year's layers: one incident number on two records (a later year's layer repeating it, or a
layer republished with new global ids while the earlier records are kept) keeps one record; the others are
duplicate_of it (link_incidents; recomputed every run).

Privacy
  Only named fields are requested. The history layer's facility_owner holds the owner's name, and for a few
  private systems that is an individual's name: it never reaches a record. A public body's name (a city,
  town, county, authority, district, commission, university) is kept as raw._owner_public; any other owner
  becomes raw._owner_kind "private or not stated". The narrative fields (deq_comments, dwr_em_43_comments,
  dwr_resolution_5d; the history layer's resolution and volume_determined) are never requested: they name the staff,
  officials and residents the writer dealt with in forms neither filter catches ("Reported to <name> at EM"), so
  raw._withheld says they were left out. The remaining text (addresses, cause, weather) passes common.strip_personal
  (in event()) and build.redact. A fixture test checks all three.

Cadence: hourly with the refresh (DWR enters reports within about a day of the start; the layer has lagged a
few days at times).
Run from pipeline/:  python -m ingest.nc_dwr_sso [--file layer.json] [--backfill [--backfill-file hist.json]]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, ROOT, event, now_iso, path_notes_to_meta, read_json,
                    save_raw, write_events, write_json)

SOURCE_ID = "nc-dwr-sso-2026"
HIST_ID = "nc-dwr-sso-2022-2025"
ORG = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services"
LAYER = f"{ORG}/Sanitary_Sewer_Overflows_since_Jan_2026/FeatureServer/0"
HIST_LAYER = f"{ORG}/Sanitary_Sewer_Overflows_September_2022_through_December_2025/FeatureServer/0"
YEAR_LAYER = re.compile(r"^Sanitary_Sewer_Overflows_since_Jan_(\d{4})$")
PAGE_URL = "https://experience.arcgis.com/experience/4a50b5dc87844bab9930a5906522a779"
# the Tracking Map's own web map ("North Carolina Sanitary Sewer Overflows Viewer Map"): the layer DWR shows the public
VIEWER_MAP = "https://www.arcgis.com/sharing/rest/content/items/20b6faf89710464bb6e009b44fbc63dc/data"
VIEWER_TITLE = re.compile(r"sanitary sewer overflow|\bssos?\b", re.I)
# the fields a this-year layer must have before its rows are read (a layer with other names needs a mapping first)
KEY_FIELDS = ("globalid", "dwr_start_date", "dwr_permit_with_name")
STATE_FILE = BUILD_DIR / "nc-dwr-sso-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "NC DEQ Division of Water Resources (Sanitary Sewer Overflow Tracking Map)"
TIME_BASIS = "Epoch milliseconds in UTC (checked against a published start time), written in Eastern time."
NC_BOX = (-84.4, 33.7, -75.3, 36.65)          # lon, lat min / max
FIELDS = ["objectid", "globalid", "deq_program", "dwr_incident_number", "dwr_permit_with_name", "dwr_regional_office",
          "deq_county", "deq_address", "deq_municipality", "dwr_report_date", "dwr_start_date", "dwr_ongoing",
          "dwr_end_date", "dwr_volume", "dwr_reached_water", "dwr_waterbody", "dwr_unlisted_waterbody",
          "dwr_volume_waterbody", "dwr_conveyance", "dwr_fish_kill", "dwr_fish_kill_number",
          "dwr_report_complete_5d", "dwr_start_date_5d", "dwr_end_date_5d", "dwr_duration_5d",
          "dwr_volume_5d", "dwr_reached_waterbody_5d", "dwr_waterbody_5d", "dwr_volume_waterbody_5d", "dwr_fish_kill_5d",
          "dwr_fish_kill_number_5d", "dwr_cause_5d", "dwr_weather_5d", "deq_latitude",
          "deq_longitude", "unlisted_waterbody"]
HIST_FIELDS = ["OBJECTID", "report_date", "start_date", "end_date", "permit_id", "facility_name", "facility_owner",
               "incident_number", "regional_office", "location", "city", "county", "volume", "volume_reach_water",
               "waterbody_impacted", "fish_kill", "incident_cause", "latitude", "longitude"]
# Narrative fields never requested: the staff's and operators' running notes name the people they called, met or
# reported to ("Reported to <name> at EM", "the ORC <name> arrived"), which neither strip_personal nor build.redact
# catches reliably. The record keeps the coded fields (cause, weather, conveyance) and says what was left out.
WITHHELD = {"deq_comments", "dwr_em_43_comments", "dwr_resolution_5d", "resolution", "volume_determined"}
WITHHELD_NOTE = ("DWR's and the operator's free-text comments and resolution notes are not reproduced here (they name "
                 "staff and residents); the source record has them.")
DATE_FIELDS = ("dwr_report_date", "dwr_start_date", "dwr_end_date", "dwr_start_date_5d", "dwr_end_date_5d",
               "report_date", "start_date", "end_date")
# a public body as owner: kept by name; anything else (a company, an association, a person) is never named
PUBLIC_OWNER = re.compile(
    r"^(city|town|village|county)\s+of\b|\b(county|city|town|village)$|\bcounty\b|\bauthority\b|\bdistrict\b|"
    r"\bcommission\b|\bcharlotte water\b|^onwasa$|\bpublic utilities\b|\bpublic works\b|\buniversity\b|"
    r"\bpublic school|\bschools\b|\bmarine corps\b|^us mcas\b|\bgeneral services\b|\bwater system$|"
    r"\bhousing authority\b|\bh2go\b|^morven town$", re.I)
PRIVATE_HINT = re.compile(r"\b(inc|llc|ltd|company|companies|corporation|corp|association|club|communities|"
                          r"homeowners|condominium|apartments|mhc|mhp)\b\.?", re.I)
STREAM_INDEX = re.compile(r"^\s*(?P<name>.+?)\s+-\s+(?P<idx>[0-9][0-9A-Za-z.\-(), ]*)\s*$")
UT_RE = re.compile(r"^\s*UT\s+(to|of)\s+", re.I)


# ---------------------------------------------------------------- helpers

def local(ms) -> datetime | None:
    """An epoch-ms UTC value -> aware America/New_York, or None."""
    if ms is None or ms == "":
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000, UTC).astimezone(TZ)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def gallons(v) -> int | None:
    f = fnum(v)
    return int(round(f)) if f is not None and f >= 0 else None


def clean(v) -> str:
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def yes_no(v) -> bool | None:
    s = clean(v).lower()
    return True if s == "yes" else False if s == "no" else None


def owner_kind(name) -> tuple[str, str | None]:
    """(kind, public name): ("public", "City of Hickory") or ("private or not stated", None). A company, an
    association or a person is never named."""
    s = clean(name)
    if not s:
        return "not stated", None
    if PRIVATE_HINT.search(s) or not PUBLIC_OWNER.search(s):
        return "private or not stated", None
    return "public", s


def split_permit(v) -> tuple[str | None, str | None]:
    """'WQCS00003 - Winston-Salem Collection System' -> ('WQCS00003', 'Winston-Salem Collection System')."""
    s = clean(v)
    if not s:
        return None, None
    m = re.match(r"^([A-Z]{2,5}[A-Z0-9]*\d)\s*-\s*(.*)$", s)
    if m:
        return m.group(1).upper(), clean(m.group(2)) or None
    return None, s


def water_text(*candidates) -> tuple[str | None, dict]:
    """The receiving water from the first non-empty candidate: '<name> - <stream index>' gives the name and
    the index; 'UT to X' becomes 'Unnamed tributary to X'."""
    for field, v in candidates:
        s = clean(v)
        if not s:
            continue
        note = {"field": field}
        m = STREAM_INDEX.match(s)
        if m and re.search(r"\d", m.group("idx")):
            note["stream_index"] = m.group("idx").strip()
            s = clean(m.group("name"))
        if UT_RE.match(s):
            note["source_text"] = s
            s = UT_RE.sub("Unnamed tributary to ", s)
        return s, note
    return None, {}


def in_nc(lat, lon) -> bool:
    return lat is not None and lon is not None and NC_BOX[0] <= lon <= NC_BOX[2] and NC_BOX[1] <= lat <= NC_BOX[3]


def permit_index(rows: list[dict] | None = None) -> dict[str, str]:
    """permit -> data/dischargers.json id, for North Carolina rows (a permit two rows hold maps to neither)."""
    if rows is None:
        rows = read_json(DATA_DIR / "dischargers.json", []) or []
    seen: dict[str, set[str]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("state") != "NC":
            continue
        for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
            if p:
                seen.setdefault(str(p).strip().upper(), set()).add(r["id"])
    return {p: next(iter(v)) for p, v in seen.items() if len(v) == 1}


NO_PERMIT = ("DWR's record gives no permit number, so no operator is joined; an operator is never inferred from a "
             "place, a facility or an owner name.")


def operator_basis(permit: str | None, permits: dict[str, str]) -> str | None:
    """Why a record has no operator row (None when it has one)."""
    if not permit:
        return NO_PERMIT
    if permit not in permits:
        return f"No operator on record for permit {permit} yet."
    return None


def decoded(a: dict) -> dict:
    return {k: iso(local(a.get(k))) for k in DATE_FIELDS if a.get(k) not in (None, "")}


# ---------------------------------------------------------------- fetching

def layer_url(name: str) -> str:
    return f"{ORG}/{name}/FeatureServer/0"


class LayerUnavailable(RuntimeError):
    """ArcGIS answers that the layer's item does not exist or is not public (code 400, CONT_0001)."""


def year_layers(sess: requests.Session) -> list[str]:
    """Every Sanitary_Sewer_Overflows_since_Jan_<year> layer in the organisation, oldest first, then any other sewer
    overflow layer the Tracking Map's web map shows (a republished layer the viewer was pointed at); the known 2026
    layer when neither lists one or the service list cannot be read."""
    found = []
    try:
        r = sess.get(ORG, params={"f": "json"}, timeout=(15, 60))
        r.raise_for_status()
        names = sorted((s.get("name") or "" for s in r.json().get("services") or []),
                       key=lambda n: (YEAR_LAYER.match(n) or [None, "0"])[1])
        found = [layer_url(n) for n in names if YEAR_LAYER.match(n)]
    except Exception as e:  # noqa: BLE001
        print(f"{SOURCE_ID}: service list not read ({type(e).__name__}); reading the known layer", file=sys.stderr)
    for url in viewer_layers(sess):
        if url not in found:
            found.append(url)
    return found or [LAYER]


def viewer_layers(sess: requests.Session) -> list[str]:
    """The sewer overflow layers of the Tracking Map's web map (VIEWER_MAP), the history layer left out; [] when the
    map cannot be read."""
    try:
        r = sess.get(VIEWER_MAP, params={"f": "json"}, timeout=(15, 60))
        r.raise_for_status()
        out = []

        def walk(layers):
            for lyr in layers or []:
                url = (lyr.get("url") or "").rstrip("/")
                if url and VIEWER_TITLE.search(lyr.get("title") or "") and url != HIST_LAYER and url not in out:
                    out.append(url if re.search(r"/\d+$", url) else f"{url}/0")
                walk(lyr.get("layers"))
        walk(r.json().get("operationalLayers"))
        return out
    except Exception as e:  # noqa: BLE001
        print(f"{SOURCE_ID}: viewer web map not read ({type(e).__name__})", file=sys.stderr)
        return []


def unavailable(err: dict) -> bool:
    return err.get("messageCode") == "CONT_0001" or "does not exist or is inaccessible" in str(err.get("message", ""))


def unavailable_text(urls: list[str], since: str | None) -> str:
    names = ", ".join(u.split("/rest/services/")[-1].split("/FeatureServer")[0] for u in urls)
    return (f"source unavailable: DWR's sewer overflow layer ({names}) is no longer public; ArcGIS answers \"Item does "
            f"not exist or is inaccessible\"" + (f" (first seen {since})" if since else "") + ". The organisation's "
            "service list and the Sanitary Sewer Overflow Tracking Map's web map show no other layer for this year. "
            "The records read up to the last good fetch are kept; no new reports can be read until DWR shares the "
            "layer again or publishes a replacement.")


def layer_meta(sess: requests.Session, url: str) -> dict:
    try:
        r = sess.get(url, params={"f": "json"}, timeout=(15, 60))
        r.raise_for_status()
        d = r.json()
        e = d.get("editingInfo") or {}
        return {"name": d.get("name"), "data_last_edit": iso(local(e.get("dataLastEditDate"))),
                "fields": [f.get("name") for f in d.get("fields") or []]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def query_layer(sess: requests.Session, url: str, fields: list[str], oid: str) -> tuple[list[dict], dict]:
    """Every row (attributes only; the points are fields) and the raw pages."""
    feats, pages, offset = [], [], 0
    while True:
        params = {"where": "1=1", "outFields": ",".join(fields), "returnGeometry": "false", "orderByFields": oid,
                  "resultOffset": offset, "resultRecordCount": 2000, "f": "json"}
        r = sess.get(f"{url}/query", params=params, timeout=(15, 120))
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            if unavailable(d["error"]):
                raise LayerUnavailable(f"{url}: {d['error'].get('message')}")
            # a new year's layer with other field names: ask for every field rather than fail
            if fields != ["*"]:
                return query_layer(sess, url, ["*"], oid)
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        pages.append(d)
        got = d.get("features") or []
        feats += got
        if not d.get("exceededTransferLimit") or not got or offset > 100_000:
            break
        offset += len(got)
    return [f.get("attributes") or {} for f in feats], {"layer": url, "pages": pages}


def safe(a: dict, fields: list[str]) -> dict:
    """Only the fields this module asks for (a layer that answered every field keeps no others)."""
    want = {f.lower() for f in fields}
    return {k: v for k, v in a.items() if k.lower() in want}


# ---------------------------------------------------------------- this year's layers

def build_record(a: dict, layer: str, fetched_at: str, prev: dict | None, permits: dict[str, str]) -> dict:
    gid = clean(a.get("globalid")).strip("{}").lower()
    base = dict(source_id=SOURCE_ID, source_record_id=gid, fetched_at=fetched_at,
                source_url=f"{layer}/query?where=globalid%3D%27{gid}%27&outFields=*&f=json")
    raw = safe(a, FIELDS)
    raw["_layer"] = layer
    raw["_withheld"] = WITHHELD_NOTE
    try:
        return _record(a, base, raw, prev, permits)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def _record(a: dict, base: dict, raw: dict, prev: dict | None, permits: dict[str, str]) -> dict:
    problems = []
    raw["_decoded_times"] = decoded(a)
    raw["_time_basis"] = TIME_BASIS
    s24, e24 = local(a.get("dwr_start_date")), local(a.get("dwr_end_date"))
    s5, e5 = local(a.get("dwr_start_date_5d")), local(a.get("dwr_end_date_5d"))
    starts = [t for t in (s24, s5) if t]
    start = min(starts) if starts else None
    ends = [t for t in (e24, e5) if t and (start is None or t >= start)]
    dropped = [iso(t) for t in (e24, e5) if t and start is not None and t < start]
    if dropped:
        problems.append("an end before the start was not used: " + ", ".join(dropped))
    end = max(ends) if ends else None
    used = []
    if start is not None:
        used.append("start from the " + ("5-day report" if start == s5 and start != s24 else "24-hour report"))
    if end is not None:
        used.append("end from the " + ("5-day report" if end == e5 and end != e24 else "24-hour report"))
    raw["_times_basis"] = ("The earlier start and the later end of DWR's 24-hour report and the operator's 5-day "
                           "report: " + ("; ".join(used) or "neither gives a time") + ".")
    ongoing = clean(a.get("dwr_ongoing")).lower() == "yes"
    if end is not None:
        status, ended_at = "ended", iso(end)
        if ongoing:
            raw["_ongoing_flag_with_end"] = "dwr_ongoing says Yes; the 5-day report gives an end"
    elif ongoing:
        status, ended_at = "ongoing", None
    else:
        status, ended_at = "ended", None
        raw["_end_basis"] = "dwr_ongoing says No, but neither report gives an end time"

    r24, r5 = yes_no(a.get("dwr_reached_water")), yes_no(a.get("dwr_reached_waterbody_5d"))
    raw["reached_water"] = True if (r24 or r5) else (False if False in (r24, r5) else None)
    water, wnote = water_text(("dwr_waterbody", a.get("dwr_waterbody")), ("dwr_waterbody_5d", a.get("dwr_waterbody_5d")),
                              ("dwr_unlisted_waterbody", a.get("dwr_unlisted_waterbody")),
                              ("unlisted_waterbody", a.get("unlisted_waterbody")))
    if wnote:
        raw["_water"] = wnote
        if wnote.get("stream_index"):
            raw["_stream_index"] = wnote["stream_index"]

    v24, v5 = gallons(a.get("dwr_volume")), gallons(a.get("dwr_volume_5d"))
    vols = [v for v in (v24, v5) if v is not None]
    gal = max(vols) if vols else None
    w24, w5 = gallons(a.get("dwr_volume_waterbody")), gallons(a.get("dwr_volume_waterbody_5d"))
    wv = [v for v in (w24, w5) if v is not None]
    to_water = max(wv) if wv else None
    if to_water is not None:
        raw["_gallons_to_water"] = to_water
    bits = []
    if gal is not None:
        bits.append(f"{gal:,} gallons estimated")
    if to_water is not None:
        bits.append(f"{to_water:,} gallons reached surface water")
    vtext = "; ".join(bits) + " (the larger of the 24-hour and 5-day reports)" if bits and v5 is not None and v24 != v5 \
        else ("; ".join(bits) or None)

    permit, fac = split_permit(a.get("dwr_permit_with_name"))
    lat, lon = fnum(a.get("deq_latitude")), fnum(a.get("deq_longitude"))
    if lat is not None and lon is not None and not in_nc(lat, lon):
        raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in North Carolina"}
        lat = lon = None
    prog = clean(a.get("deq_program")).lower()

    p_raw = (prev or {}).get("raw") or {}
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or base["fetched_at"]
    if why := operator_basis(permit, permits):
        raw["_discharger_basis"] = why
    return event(
        **base, event_type="bypass" if prog == "bypass" else "sso", status=status,
        discharger_id=permits.get(permit or ""), discharger_name=fac, npdes_permit=permit,
        outfall_id=None, outfall_name=clean(a.get("deq_address")) or None,
        waterbody_text=water, water_slugs=[], water_match="none",
        lat=round(lat, 6) if lat is not None else None, lon=round(lon, 6) if lon is not None else None,
        coord_source="source" if lat is not None else None, coord_precision_m=None,
        started_at=iso(start), ended_at=ended_at, time_precision="minute" if start else None,
        reported_at=iso(local(a.get("dwr_report_date"))), published_at=None, source_updated_at=None,
        material="untreated wastewater", volume_gal=gal, volume_text=vtext,
        estimate_flag="estimated" if gal is not None else "unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def build(rows: list[tuple[str, dict]], fetched_at: str, prev_records: list[dict],
          permits: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """rows: (layer url, attributes). Returns the records (earlier records that left the layers kept) and stats."""
    permits = permit_index() if permits is None else permits
    prev = {r["event_id"]: r for r in prev_records}
    records, seen = [], set()
    for layer, a in rows:
        gid = clean(a.get("globalid")).strip("{}").lower()
        if not gid:
            continue
        eid = f"{SOURCE_ID}:{gid}"
        if eid in seen:
            continue
        seen.add(eid)
        records.append(build_record(a, layer, fetched_at, prev.get(eid), permits))
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        r.setdefault("raw", {})
        for k in WITHHELD & set(r["raw"]):               # a record kept from a run before these were withheld
            r["raw"].pop(k)
        r["raw"]["_missing_from_layer_since"] = r["raw"].get("_missing_from_layer_since") or fetched_at
        records.append(r)
        kept += 1
    dups = link_incidents(records, seen)
    records.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]), reverse=True)
    stats = {"layer_rows": len(seen), "kept_from_earlier_runs": kept, "duplicates": dups,
             "by_status": dict(Counter(r["status"] for r in records)),
             "by_type": dict(Counter(r["event_type"] for r in records)),
             "reached_water": dict(Counter(str((r.get("raw") or {}).get("reached_water")) for r in records)),
             "with_coordinates": sum(1 for r in records if r.get("lat") is not None),
             "with_operator_row": sum(1 for r in records if r.get("discharger_id")),
             "permits": len({r["npdes_permit"] for r in records if r.get("npdes_permit")}),
             "statewide": True}
    return records, stats


def link_incidents(records: list[dict], seen: set[str]) -> int:
    """One DWR incident number on several records (a later year's layer that repeats an incident, or a layer DWR
    republished with new global ids, whose earlier records are kept): one record stands, the others are duplicate_of
    it. The one standing is in the layers on this run, from the latest year's layer, and seen last. Links are
    recomputed every run. Returns the number of duplicates."""
    def year(r):
        m = re.search(r"since_Jan_(\d{4})", str((r.get("raw") or {}).get("_layer") or ""))
        return int(m.group(1)) if m else 0
    groups: dict[str, list[dict]] = {}
    for r in records:
        raw = r.setdefault("raw", {})
        if raw.pop("_duplicate_basis", None) is not None:
            r["duplicate_of"] = None
        inc = clean(raw.get("dwr_incident_number"))
        if inc:
            groups.setdefault(inc, []).append(r)
    n = 0
    for inc, rs in groups.items():
        if len(rs) < 2:
            continue
        keep = max(rs, key=lambda r: (r["event_id"] in seen, year(r), r["raw"].get("_first_seen_at") or "", r["event_id"]))
        for r in rs:
            if r is keep:
                continue
            r["duplicate_of"] = keep["event_id"]
            r["raw"]["_duplicate_basis"] = (f"DWR incident number {inc} is also on {keep['event_id']}, the copy in "
                                            "the layer DWR publishes now")
            n += 1
    return n


# ---------------------------------------------------------------- history layer

def hist_record(a: dict, fetched_at: str, rid: str, permits: dict[str, str], dup_of: str | None) -> dict:
    oid = a.get("OBJECTID")
    base = dict(source_id=HIST_ID, source_record_id=rid, fetched_at=fetched_at,
                source_url=f"{HIST_LAYER}/query?where=OBJECTID%3D{oid}&outFields=*&f=json")
    raw = {k: v for k, v in safe(a, HIST_FIELDS).items() if k != "facility_owner"}
    raw["_withheld"] = WITHHELD_NOTE
    kind, public = owner_kind(a.get("facility_owner"))
    raw["_owner_kind"] = kind
    if public:
        raw["_owner_public"] = public
    raw["_layer"] = HIST_LAYER
    try:
        raw["_decoded_times"] = decoded(a)
        raw["_time_basis"] = TIME_BASIS
        start, end = local(a.get("start_date")), local(a.get("end_date"))
        if end is not None and start is not None and end > start:
            ended_at = iso(end)
        else:
            ended_at = None
            raw["_end_basis"] = ("end_date repeats start_date on every row of this layer, so it is not an end time; "
                                 "the incident is closed but its end is not published here")
        if start is None:
            raw["_start_basis"] = "no start date in the layer; reported_at is the report date"
        loc = clean(a.get("location"))
        loc = re.sub(r"^-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+\s*", "", loc).strip(" ,;-") or None
        lat, lon = fnum(a.get("latitude")), fnum(a.get("longitude"))
        if lat is not None and lon is not None and not in_nc(lat, lon):
            raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in North Carolina"}
            lat = lon = None
        vol, vw = gallons(a.get("volume")), gallons(a.get("volume_reach_water"))
        if vw is not None:
            raw["_gallons_to_water"] = vw
        raw["reached_water"] = True if vw else (False if vw == 0 else None)
        water, wnote = water_text(("waterbody_impacted", a.get("waterbody_impacted")))
        if wnote:
            raw["_water"] = wnote
        bits = ([f"{vol:,} gallons"] if vol is not None else []) + \
               ([f"{vw:,} gallons reached surface water"] if vw is not None else [])
        permit = clean(a.get("permit_id")).upper() or None
        if why := operator_basis(permit, permits):
            raw["_discharger_basis"] = why
        rec = event(
            **base, event_type="sso", status="ended",
            discharger_id=permits.get(permit or ""), discharger_name=clean(a.get("facility_name")) or None,
            npdes_permit=permit, outfall_id=None, outfall_name=loc,
            waterbody_text=water, water_slugs=[], water_match="none",
            lat=round(lat, 6) if lat is not None else None, lon=round(lon, 6) if lon is not None else None,
            coord_source="source" if lat is not None else None,
            started_at=iso(start), ended_at=ended_at, time_precision="minute" if start else None,
            reported_at=iso(local(a.get("report_date"))), material="untreated wastewater",
            volume_gal=vol, volume_text="; ".join(bits) or None,
            estimate_flag="estimated" if vol is not None else "unknown", authority=AUTHORITY, raw=raw,
            duplicate_of=dup_of,
        )
    except Exception as e:  # noqa: BLE001
        rec = event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                    parse_error=f"{type(e).__name__}: {e}")
    if dup_of:
        rec["raw"]["_duplicate_basis"] = "the same DWR incident number is in this year's layer, which carries both reports"
    return rec


def build_history(rows: list[dict], fetched_at: str, current: list[dict],
                  permits: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    permits = permit_index() if permits is None else permits
    by_inc = {}
    for r in current:
        inc = clean((r.get("raw") or {}).get("dwr_incident_number"))
        if inc and not r.get("duplicate_of"):
            by_inc.setdefault(inc, r["event_id"])
    counts = Counter(clean(a.get("incident_number")) for a in rows)
    out, ids = [], set()
    for a in rows:
        inc = clean(a.get("incident_number"))
        rid = inc if inc and counts[inc] == 1 else f"{inc or 'no-incident'}-{a.get('OBJECTID')}"
        if rid in ids:
            continue
        ids.add(rid)
        out.append(hist_record(a, fetched_at, rid, permits, by_inc.get(inc) if inc else None))
    out.sort(key=lambda r: (r.get("started_at") or r.get("reported_at") or "", r["event_id"]), reverse=True)
    stats = {"layer_rows": len(rows), "records": len(out),
             "duplicate_of_this_year": sum(1 for r in out if r.get("duplicate_of")),
             "without_start": sum(1 for r in out if not r.get("started_at")),
             "with_coordinates": sum(1 for r in out if r.get("lat") is not None),
             "with_operator_row": sum(1 for r in out if r.get("discharger_id")),
             "owner_kind": dict(Counter(r["raw"].get("_owner_kind") for r in out)), "statewide": True}
    return out, stats


# ---------------------------------------------------------------- main

def _load_file(path: str) -> list[tuple[str, dict]]:
    d = json.loads(Path(path).read_text())
    docs = d if isinstance(d, list) else [d]
    out = []
    for doc in docs:
        layer = doc.get("layer") or LAYER
        for p in doc.get("pages") or [doc]:
            out += [(layer, f.get("attributes") or {}) for f in p.get("features") or []]
    return out


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved query response (this year's layer) instead of the layers")
    ap.add_argument("--backfill", action="store_true", help="also read the September 2022 - December 2025 layer once")
    ap.add_argument("--backfill-file", help="read this saved history-layer response instead")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    layers_meta = {}
    try:
        if args.file:
            rows = _load_file(args.file)
            raw_docs = None
        else:
            rows, raw_docs, gone = [], [], []
            for url in year_layers(sess):
                try:
                    feats, doc = query_layer(sess, url, FIELDS, "objectid")
                except LayerUnavailable as e:
                    gone.append(url)
                    layers_meta[url] = {"error": str(e), "unavailable": True}
                    continue
                missing = [k for k in KEY_FIELDS if feats and not any(c.lower() == k for c in feats[0])]
                if missing:   # a republished layer with other field names: never guess the mapping
                    layers_meta[url] = {"error": f"fields {', '.join(missing)} absent; the layer needs a field mapping",
                                        "rows": len(feats)}
                    continue
                rows += [(url, a) for a in feats]
                raw_docs.append(doc)
                layers_meta[url] = {**layer_meta(sess, url), "rows": len(feats)}
            if not raw_docs:
                prev_meta = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("meta") or {}
                since = prev_meta.get("unavailable_since") or fetched_at
                if gone and len(gone) == len(layers_meta):
                    msg = unavailable_text(gone, since)
                    meta = {"unavailable": True, "unavailable_since": since, "layers": layers_meta, "page": PAGE_URL}
                else:
                    msg = "no readable layer: " + "; ".join(f"{u}: {m.get('error')}" for u, m in layers_meta.items())
                    meta = {"unavailable": False, "unavailable_since": None, "layers": layers_meta, "page": PAGE_URL}
                write_events(SOURCE_ID, [], ok=False, error=msg, meta=meta)
                print(f"{SOURCE_ID}: {msg}", file=sys.stderr)
                return 1
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    state = read_json(STATE_FILE, {}) or {}
    raw_path = state.get("raw_path")
    if raw_docs is not None:
        sha = hashlib.sha256(json.dumps([a for _, a in rows], sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, json.dumps(raw_docs, ensure_ascii=False), "json").relative_to(ROOT))
            state = {**state, "sha256": sha, "raw_path": raw_path, "saved_at": fetched_at}
        state["fetched_at"] = fetched_at
        write_json(STATE_FILE, state)
    permits = permit_index()
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(rows, fetched_at, prev, permits)
    records = redact.redact_events(records)
    newest = max((r.get("reported_at") or "" for r in records), default="") or None
    meta = {**stats, "layers": layers_meta or {LAYER: {"rows": len(rows), "from_file": True}},
            "newest_report": newest, "raw_path": raw_path, "time_basis": TIME_BASIS, "page": PAGE_URL,
            "credit": "NC DEQ Division of Water Resources, Sanitary Sewer Overflow Tracking Map",
            "registry_ids": [SOURCE_ID], "unavailable": False, "unavailable_since": None}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['layer_rows']} layer rows, {stats['kept_from_earlier_runs']} kept; status "
          f"{stats['by_status']}; reached water {stats['reached_water']}; operator row {stats['with_operator_row']} "
          f"-> {path}")

    if args.backfill or args.backfill_file:
        try:
            if args.backfill_file:
                hist = [a for _, a in _load_file(args.backfill_file)]
            else:
                hist, doc = query_layer(sess, HIST_LAYER, HIST_FIELDS, "OBJECTID")
                hist = [dict(a) for a in hist]
                doc = json.loads(json.dumps(doc))
                # facility_owner names a few individuals: the saved copy keeps a public body's name only
                for p in doc["pages"]:
                    for f in p.get("features") or []:
                        at = f.get("attributes") or {}
                        at["facility_owner"] = owner_kind(at.get("facility_owner"))[1]
                save_raw(HIST_ID, json.dumps(doc, ensure_ascii=False), "json")
        except Exception as e:  # noqa: BLE001
            write_events(HIST_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
            print(f"{HIST_ID}: FAILED {e}", file=sys.stderr)
            return 1
        hrecs, hstats = build_history(hist, fetched_at, records, permits)
        hrecs = redact.redact_events(hrecs)
        hmeta = {**hstats, "layer": HIST_LAYER, "time_basis": TIME_BASIS, "page": PAGE_URL, "frozen": True,
                 "credit": "NC DEQ Division of Water Resources, Sanitary Sewer Overflows September 2022 through "
                           "December 2025", "registry_ids": [HIST_ID]}
        path_notes_to_meta(hrecs, hmeta)
        hp = write_events(HIST_ID, hrecs, ok=True, error=None, meta=hmeta)
        print(f"{HIST_ID}: {hstats['records']} records, {hstats['duplicate_of_this_year']} duplicates of this year's "
              f"layer, {hstats['without_start']} without a start -> {hp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
