"""Baltimore DPW All SSOs -> the existing md-baltimore-sso event feed.

Reads the full SSO/MapServer/0 table with named fields and count-checked paging.
OBJECTID agrees with all 104 legacy SSO_Points2 rows checked Nov. 22, 2026;
SSOID is a separate business key (34 nulls and one duplicate), never a replacement
for legacy event IDs. Reissued rows retain earlier event IDs through unique SSOID
or an unambiguous legacy crosswalk (same normalized street, rounded point and
SSO_DATE within 10 minutes). Five reissues in the Nov. 4 fixture establish this
correction pattern. Ambiguous candidates are not merged.

The dates encode Eastern wall time as UTC, corroborated against MDE in winter and
summer. SSO_DATE is a fallback with its precision and uncertain meaning retained.
No publication time is invented. Source ends remain source ends; DURATION has
mixed notation and no declared unit, so no end is derived. Cause flags quote the
City's field aliases and Yes/No domain labels without expanding opaque acronyms.

Only allowlisted fields are saved; locations lose house numbers and personal
text and coordinates are rounded to three decimals before persistence. MDE runs
after this module, marks its matching records duplicate_of these events, and adds
an other-source link consumed symmetrically by the existing detail exporter.
Run from pipeline/: python -m ingest.md_baltimore_sso [--file layer.json]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, event, now_iso, path_notes_to_meta, read_json, save_raw,
                    write_events, write_json, scrub_names, scrub_text, strip_house_numbers)
from common import error_detail, error_text
from ingest import md_waters

SOURCE_ID = "md-baltimore-sso"
LEGACY_LAYER = "https://dpwdata.baltimorecity.gov/pubgis/rest/services/Public/SSO_Points2/MapServer/0"
LAYER = "https://dpwview.baltimorecity.gov/agsprd/rest/services/SSO/MapServer/0"
PAGE_URL = "https://experience.arcgis.com/experience/f064b1b0addd4017ac179f1652e182e0"
STATE_FILE = BUILD_DIR / "md-baltimore-sso-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Baltimore City Department of Public Works (Sewer Overflow Map)"
DATE_FIELDS = ("SSO_DATE", "START_DATETIME", "END_DATETIME", "WAIVER_REQUESTED", "WAIVER_GRANTED",
               "WAIVER_CLOSED", "WAIVER_DENIED")
TIME_BASIS = ("The layer stores local wall-clock time as if it were UTC: each epoch value is read as UTC and the "
              "wall-clock time read in America/New_York when it identifies one instant.")
# REC_WATERS coded values (the layer's domain; research/md/sources.json lists the same 24)
REC_WATERS = {
    "ARGO": "Argonne Run", "ARMI": "Armistead Creek", "BIDD": "Biddison Run", "CHIN": "Chinquapin Run",
    "COLG": "Colgate Creek", "CRTB": "Curtis Bay", "CRTC": "Curtis Creek", "DEAD": "Dead Run",
    "GUNP": "Gunpowder Falls", "GWYN": "Gwynns Falls", "HERR": "Herring Run", "HARB": "Inner Harbor",
    "JF": "Jones Falls", "LRR": "Loch Raven Reservoir", "MAID": "Maidens Choice Creek", "MID": "Middle Branch",
    "MOOR": "Moores Run", "MTPL": "Mt Pleasant Run", "NWHB": "Northwest Harbor", "PAT": "Patapsco River",
    "SHCV": "Stonehouse Cove", "SR": "Stony Run", "TIFF": "Tiffany Run", "WEST": "Western Run",
}
# the names openboatlaunch uses for two coded waters (the point is still checked against the box)
MATCH_AS = {"MID": "Middle Branch Patapsco River", "HARB": "Northwest Harbor"}
WATERSHEDS = {2130904: "Jones Falls", 2130901: "Back River", 2130903: "Baltimore Harbor", 2130905: "Gwynns Falls",
              2130906: "Patapsco River L N Br"}
STATUS_NAMES = {"PROG": "In Progress", "5DAY": "5 Day Report Submitted", "24HR": "24 Hour Report Submitted",
                "FORM": "Paper Form Submittal"}
RESPONSIBILITY = {
    "DPW": ("md-baltimore-city-dpw", "Baltimore City Department of Public Works"),
    "CO": ("md-baltimore-county-dpw", "Baltimore County Department of Public Works and Transportation"),
    "PRI": (None, "Private (property owner; not named by the source)"),
    "FAC": (None, "Facility (not named by the source)"),
    "UNK": (None, None),
}
# the safe fields (data/sources/md-baltimore-sso.yaml fetch.safe_fields): every field but the two free-text waiver and
# relief comments (WAIVER_REASON, COMMENT_RELIEF_REQUEST_TYPE), which no record uses and which can carry names
LEGACY_SAFE_FIELDS = ("OBJECTID", "SSO_DATE", "LOCATION", "EST_VOLUME", "EST_FLOW", "STATUS", "REC_WATERS", "WATERSHED",
               "START_DATETIME", "END_DATETIME", "RESPONSIBILITY", "Latitude", "Longitude", "SITE_TYPE",
               "SENSITIVE_AREA", "WAIVER_REQUESTED", "WAIVER_GRANTED", "PENALTY", "WAIVER_CLOSED", "WAIVER_DENIED",
               "ENTER_STORM", "CLEANUP_REQ", "STIPULATED_PENALTY_WAIVED", "STIPULATED_PENALTY_ASSESSED",
               "ANNUAL_ADJUSTMENT")
CAUSE_FIELDS = ("CAUSE_RAGS", "CAUSE_ROOTS", "CAUSE_RAIN", "CAUSE_GREASE", "CAUSE_INFLIT", "CAUSE_TRASH",
                "CAUSE_SGR", "CAUSE_STRUCTURAL", "CAUSE_PLOSS", "CAUSE_UNKNOWN", "CAUSE_VANDAL", "CAUSE_OTHER")
# All cause aliases equal their field names. The domain supplies only Yes/No,
# not expansions of SGR, INFLIT or PLOSS (metadata checked 2026-11-22).
BOOLEAN_DOMAIN = {0: "No", 1: "Yes"}
SAFE_FIELDS = LEGACY_SAFE_FIELDS + ("SSOID", "DURATION", "OVFL_REACH_WW") + CAUSE_FIELDS
# the fields the record's identity, times and status rest on: a layer without one of them is a failed read
REQUIRED_FIELDS = ("OBJECTID", "SSOID", "SSO_DATE", "START_DATETIME", "END_DATETIME", "STATUS")
SITE_RE = re.compile(r"\bSSO\s+Site\s*#\s*(\d+)", re.I)


def wall_clock(ms) -> datetime | None:
    """Decode local time; leave a DST fold or gap naive instead of choosing an offset."""
    if ms is None or ms == "":
        return None
    try:
        t = datetime.fromtimestamp(float(ms) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    local = t.replace(tzinfo=None)
    return local if wall_clock_issue(local) else local.replace(tzinfo=TZ)


def wall_clock_issue(local: datetime) -> str | None:
    """A round trip distinguishes a skipped hour from a repeated hour."""
    local = local.replace(tzinfo=None)
    candidates = [local.replace(tzinfo=TZ, fold=fold) for fold in (0, 1)]
    valid = [t for t in candidates if t.astimezone(UTC).astimezone(TZ).replace(tzinfo=None) == local]
    if not valid:
        return "nonexistent"
    if len({t.utcoffset() for t in valid}) > 1:
        return "ambiguous"
    return None


def iso(dt: datetime | None) -> str | None:
    return (dt.isoformat() if dt.tzinfo is not None else dt.date().isoformat()) if dt else None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def safe_attributes(a: dict) -> dict:
    """The safe fields of one row, its point rounded to three decimals (about 100 m) before anything is saved."""
    out = {k: a.get(k) for k in SAFE_FIELDS if k in a}
    for k in ("Latitude", "Longitude"):
        v = fnum(out.get(k))
        if v is not None:
            out[k] = round(v, 3)
    if a.get("_address_match_sha256"):
        out["_address_match_sha256"] = a["_address_match_sha256"]
    if out.get("LOCATION"):
        if "[house number removed]" not in str(out["LOCATION"]):
            from ingest.md_mde_overflows import norm_addr
            address = norm_addr(out["LOCATION"], for_match=True)
            if address:
                out["_address_match_sha256"] = hashlib.sha256(address.encode()).hexdigest()
        out["LOCATION"] = strip_house_numbers(scrub_names(scrub_text(str(out["LOCATION"]))))
    if out.get("DURATION") is not None:
        out["DURATION"] = scrub_names(scrub_text(str(out["DURATION"])))
    return out


def layer_fields(sess: requests.Session) -> tuple[list[str], list[str], int]:
    """(the safe fields the layer still has, the safe fields it no longer has, its maxRecordCount). A layer that
    lacks a field the records rest on is a failed read: no record may keep a time or status the source no longer
    gives as if it still gave it."""
    r = sess.get(LAYER, params={"f": "json"}, timeout=(15, 60))
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"ArcGIS error (layer description): {d['error']}")
    for field in d.get("fields") or []:
        if field.get("name") in (*CAUSE_FIELDS, "OVFL_REACH_WW") and field.get("domain"):
            domain = {v["code"]: v["name"] for v in field["domain"].get("codedValues", [])}
            if domain != BOOLEAN_DOMAIN:
                raise RuntimeError(f"changed domain for {field['name']}; review the source labels")
    names = {f.get("name") for f in d.get("fields") or [] if isinstance(f, dict)}
    if not names:
        raise RuntimeError("the layer description lists no fields")
    gone = [f for f in SAFE_FIELDS if f not in names]
    lost = [f for f in REQUIRED_FIELDS if f in gone]
    if lost:
        raise RuntimeError(f"the layer no longer has the field(s) {', '.join(lost)} (layer {d.get('id')!r} "
                           f"{d.get('name')!r}); fields now: {', '.join(sorted(n for n in names if n))}")
    return [f for f in SAFE_FIELDS if f in names], gone, int(d.get("maxRecordCount") or 1000)


def query_layer(sess: requests.Session) -> tuple[list[dict], bytes, list[str]]:
    """Every feature (safe attributes only; Latitude/Longitude are fields), the raw pages as one JSON (points already
    rounded) and the safe fields the layer no longer has. A malformed page, an empty layer or a read that does not
    return the layer's own count raises, so the caller keeps the earlier records and saves nothing new."""
    fields, gone, max_count = layer_fields(sess)
    r = sess.get(f"{LAYER}/query", params={"where": "1=1", "returnCountOnly": "true", "f": "json"}, timeout=(15, 60))
    r.raise_for_status()
    c = r.json()
    if "error" in c:
        raise RuntimeError(f"ArcGIS error (count): {c['error']}")
    count = c.get("count")
    if not isinstance(count, int) or count <= 0:
        raise RuntimeError(f"the layer's count is {count!r}: an empty or unreadable layer is treated as a failed read")
    feats, pages, offset, seen = [], [], 0, set()
    while offset < count:
        params = {"where": "1=1", "outFields": ",".join(fields), "returnGeometry": "false",
                  "orderByFields": "OBJECTID", "resultOffset": offset,
                  "resultRecordCount": min(1000, max_count), "f": "json"}
        r = sess.get(f"{LAYER}/query", params=params, timeout=(15, 90))
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        got = d.get("features")
        if not isinstance(got, list) or any(not isinstance(f, dict) for f in got):
            raise RuntimeError(f"malformed page at offset {offset}: no feature list")
        got = [{"attributes": safe_attributes(f.get("attributes") or {})} for f in got]
        ids = [f["attributes"].get("OBJECTID") for f in got]
        if not got:
            raise RuntimeError(f"partial read: empty page at {offset} of {count}")
        if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
            raise RuntimeError("malformed page: missing or invalid OBJECTID")
        if len(set(ids)) != len(ids) or seen.intersection(ids):
            raise RuntimeError("partial read: duplicate OBJECTID in repeated pages")
        if ids != sorted(ids) or (seen and min(ids) <= max(seen)):
            raise RuntimeError("partial read: OBJECTID order changed while paging")
        seen.update(ids)
        pages.append({"features": got})
        feats += got
        offset += len(got)
    if len(feats) != count:
        raise RuntimeError(f"partial read: {len(feats)} rows of the layer's count {count}")
    raw = json.dumps({"layer": LAYER, "fields_requested": fields, "pages": pages}, ensure_ascii=False).encode()
    return [f["attributes"] for f in feats], raw, gone


def decoded_dates(a: dict) -> dict:
    return {k: (dt.isoformat() if (dt := wall_clock(a.get(k))) else None)
            for k in DATE_FIELDS if a.get(k) not in (None, "")}


def place(a: dict, lat, lon) -> tuple[str | None, list[str], str, dict]:
    code = (a.get("REC_WATERS") or "").strip() or None
    note: dict = {}
    if not code:
        return None, [], "none", {"why_none": "REC_WATERS empty (the layer names no receiving water)"}
    if code == "N/A":
        return "N/A", [], "none", {"why_none": "REC_WATERS N/A"}
    name = REC_WATERS.get(code)
    if not name:
        return code, [], "none", {"why_none": f"unknown REC_WATERS code {code!r}"}
    point = (lon, lat) if lat is not None and lon is not None else None
    slugs, notes = md_waters.match_waters(MATCH_AS.get(code, name), None, point, "Baltimore City")
    if MATCH_AS.get(code):
        note["matched_as"] = MATCH_AS[code]
    if notes:
        note["name_notes"] = notes
    if not slugs:
        note["why_none"] = f"no Maryland water record named {name!r} near the point"
    return name, slugs, ("name" if slugs else "none"), note


def to_record(a: dict, fetched_at: str, prev: dict | None) -> dict:
    if "SSOID" in a:
        a = safe_attributes(a)
    oid = a.get("OBJECTID")
    layer = LAYER if "SSOID" in a else LEGACY_LAYER
    fields = SAFE_FIELDS if "SSOID" in a else LEGACY_SAFE_FIELDS
    base = dict(source_id=SOURCE_ID, source_record_id=(prev or {}).get("source_record_id") or str(oid),
                fetched_at=fetched_at,
                source_url=f"{layer}/query?where=OBJECTID%3D{oid}&outFields={','.join(fields)}&returnGeometry=false&f=json")
    raw = {k: v for k, v in a.items()}
    try:
        return build_record(a, base, raw, prev)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{error_text(e)}")


def full_details(a: dict, raw: dict, base: dict) -> None:
    flags = {k: BOOLEAN_DOMAIN.get(a[k], f"Unrecognized code: {a[k]}")
             for k in CAUSE_FIELDS if a.get(k) is not None}
    raw["_cause_flags"] = flags
    selected = [f'{k}: "{label}"' for k, label in flags.items() if label == "Yes"]
    if selected:
        raw["_cause_text"] = "; ".join(selected)
    duration = a.get("DURATION")
    if duration is not None and str(duration).strip():
        raw["_duration_text"] = f"{str(duration).strip()} (source duration; unit not stated)"
    reach = a.get("OVFL_REACH_WW")
    if reach in BOOLEAN_DOMAIN:
        raw["_water_reach"] = BOOLEAN_DOMAIN[reach]
    elif reach is not None:
        raw["_water_reach_unknown_code"] = reach
    named = a.get("REC_WATERS") not in (None, "", "N/A")
    if (reach == 0 and named) or (reach == 1 and not named):
        raw["_water_reach_conflict"] = ("The City names a receiving water but answers No to whether the overflow "
                                        "reached a waterway." if named else
                                        "The City answers Yes to whether the overflow reached a waterway but names none.")
    for key, field in (("started_at", "START_DATETIME"), ("ended_at", "END_DATETIME")):
        dt = wall_clock(a.get(field))
        if dt:
            raw[f"_{key}_precision"] = "second" if dt.second or dt.microsecond else "minute"
    raw["_field_sources"] = {
        key: {"fields": fields, "record": str(a["OBJECTID"])}
        for key, fields in {"cause": list(CAUSE_FIELDS), "duration": ["DURATION"],
                            "water_reach": ["OVFL_REACH_WW"], "receiving_water": ["REC_WATERS"],
                            "volume": ["EST_VOLUME"], "start": ["START_DATETIME", "SSO_DATE"],
                            "end": ["END_DATETIME"]}.items()
    }
    raw["_source_reference"] = {"url": base["source_url"], "record": str(a["OBJECTID"]),
                                "fetched_at": base["fetched_at"]}
    raw["_domain_source"] = {"url": f"{LAYER}?f=pjson", "checked": "2026-11-22"}


def build_record(a: dict, base: dict, raw: dict, prev: dict | None) -> dict:
    problems = []
    raw["_decoded_times"] = decoded_dates(a)
    raw["_time_basis"] = TIME_BASIS
    start, end = wall_clock(a.get("START_DATETIME")), wall_clock(a.get("END_DATETIME"))
    if start is None and a.get("SSO_DATE"):
        start = wall_clock(a.get("SSO_DATE"))
        raw["_start_basis"] = ("START_DATETIME is empty: started_at is SSO_DATE (the layer's DATE field, equal to "
                               "START_DATETIME wherever both are filled). Its seconds suggest the time the record was "
                               "entered, so the overflow may have begun earlier.")
    full = "SSOID" in a
    if full:
        if start is not None and start.year < 2000:
            problems.append("Source start predates this table's 2003 history; we leave started_at empty.")
            start = None
        if end is not None and end.year < 2000:
            problems.append("Source end predates this table's 2003 history; we leave ended_at empty.")
            end = None
        full_details(a, raw, base)
        if a.get("START_DATETIME") in (None, "") and a.get("SSO_DATE"):
            raw["_start_basis"] = ("The City gives no overflow start time. We use its record date (SSO_DATE); "
                                   "the overflow may have begun earlier. A midnight record date has day precision.")
        if start:
            raw["_started_at_precision"] = (
                "day" if a.get("START_DATETIME") in (None, "") and not (start.hour or start.minute or start.second or start.microsecond)
                else "second" if start.second or start.microsecond else "minute")
    # Preserve the source's exact wall time in raw, but publish only its date
    # when neither offset (gap) or both offsets (fold) fit that local time.
    issues = []
    for field, value in raw["_decoded_times"].items():
        if value and (dt := datetime.fromisoformat(value)).tzinfo is None:
            issues.append(f"{field} {value} is {wall_clock_issue(dt)} in America/New_York")
    if issues:
        raw["_time_uncertainty"] = "; ".join(issues) + ". We show affected event times at day precision."
        raw["_time_basis"] += " " + raw["_time_uncertainty"]
    for key, dt in (("started_at", start), ("ended_at", end)):
        if dt and dt.tzinfo is None:
            raw[f"_{key}_precision"] = "day"
    if raw.get("_ended_at_precision"):
        raw["ended_at_precision"] = raw["_ended_at_precision"]
    code = (a.get("STATUS") or "").strip().upper()
    raw["_status_name"] = STATUS_NAMES.get(code)
    if code == "PROG":
        status, ended_at = "ongoing", None
        if end is not None:
            raw["_end_while_in_progress"] = iso(end)
    elif end is not None:
        status, ended_at = "ended", iso(end)
    else:
        status, ended_at = "unknown", None
    if end is not None and start is not None and (
            end.date() < start.date() if end.tzinfo is None or start.tzinfo is None else end < start):
        problems.append("END_DATETIME before START_DATETIME: ended_at left empty")
        ended_at = None
        if status == "ended":
            status = "unknown"

    lat, lon = fnum(a.get("Latitude")), fnum(a.get("Longitude"))
    if lat is not None and lon is not None and not md_waters.in_md(lon, lat):
        raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in Maryland"}
        lat = lon = None
    water, slugs, match, wnote = place(a, lat, lon)
    if wnote:
        raw["_water"] = wnote
    ws = a.get("WATERSHED")
    if ws is not None:
        raw["_watershed_name"] = WATERSHEDS.get(ws)

    vol = fnum(a.get("EST_VOLUME"))
    gal = (vol if full else int(round(vol))) if vol is not None and vol >= 0 else None
    vtext = f"{vol:,.2f}".rstrip("0").rstrip(".") + " gallons (EST_VOLUME)" if vol is not None else None
    resp = (a.get("RESPONSIBILITY") or "").strip().upper() or None
    did, dname = RESPONSIBILITY.get(resp, (None, None)) if resp else (None, None)
    raw["_responsibility"] = {"DPW": "DPW", "CO": "County", "PRI": "Private", "FAC": "Facility", "UNK": "Unknown"}.get(resp or "", resp)
    loc = " ".join(str(a.get("LOCATION") or "").split()) or None
    m = SITE_RE.search(loc or "")

    # carried across runs: first sighting and the STATUS values seen
    p_raw = (prev or {}).get("raw") or {}
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or base["fetched_at"]
    seen = list(p_raw.get("_status_seen") or [])
    if not seen or seen[-1].get("status") != code:
        seen.append({"status": code or None, "first_seen_at": base["fetched_at"]})
    raw["_status_seen"] = seen
    if prev and p_raw.get("_volume_seen"):
        vs = list(p_raw["_volume_seen"])
    else:
        vs = []
    if gal is not None and (not vs or vs[-1].get("gallons") != gal):
        vs.append({"gallons": gal, "first_seen_at": base["fetched_at"]})
    if vs:
        raw["_volume_seen"] = vs

    return event(
        **base, event_type="sso", status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=None,
        outfall_id=f"SSO Site #{m.group(1)}" if m else None, outfall_name=loc,
        waterbody_text=water, water_slugs=slugs, water_match=match,
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=None,
        started_at=iso(start), ended_at=ended_at,
        time_precision=(raw.get("_started_at_precision", "minute") if start else None),
        reported_at=None, published_at=None, source_updated_at=None,
        material=None, volume_gal=gal, volume_text=vtext, estimate_flag="estimated" if gal is not None else "unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def identity_location(a: dict) -> tuple | None:
    """Street plus rounded point; the time is checked separately, never proximity alone."""
    loc = strip_house_numbers(str(a.get("LOCATION") or "")).lower()
    loc = re.sub(r"[^a-z0-9]+", "", loc)
    lat, lon = fnum(a.get("Latitude")), fnum(a.get("Longitude"))
    if not loc or lat is None or lon is None:
        return None
    return loc, round(lat, 3), round(lon, 3)


def crosswalk(features: list[dict], prev: dict, *, uniqueness_records: dict | None = None) -> dict[int, tuple[dict, str]]:
    """Only one-to-one links. A stored business key survives source OBJECTID reissues.
    Legacy rows lack SSOID, so require the observed street/point/time correction pattern.
    """
    result, claimed = {}, set()
    full = [a for a in features if "SSOID" in a]
    source_sso = Counter(a.get("SSOID") for a in full)
    prev_sso = Counter((p.get("raw") or {}).get("SSOID")
                       for p in (prev if uniqueness_records is None else uniqueness_records).values())
    by_oid = {str((p.get("raw") or {}).get("OBJECTID", p.get("source_record_id"))): p for p in prev.values()}
    by_sso = {(p.get("raw") or {}).get("SSOID"): p for p in prev.values()}
    for a in full:
        oid, sid = a["OBJECTID"], a.get("SSOID")
        p = by_oid.get(str(oid))
        if p and (p.get("raw") or {}).get("SSOID") is not None and sid is not None and p["raw"]["SSOID"] != sid:
            p = None  # reused OBJECTID is not the same business record
        basis = "The City's full and legacy layers use the same OBJECTID."
        if p is None and sid is not None and source_sso[sid] == prev_sso[sid] == 1:
            p = by_sso.get(sid)
            basis = "The City's unique SSOID links this reissued row to our earlier record."
        if p and p["event_id"] not in claimed:
            result[oid] = (p, basis)
            claimed.add(p["event_id"])
    locations = defaultdict(list)
    for p in prev.values():
        if p["event_id"] not in claimed:
            locations[identity_location(p.get("raw") or {})].append(p)
    candidates = {}
    for a in full:
        if a["OBJECTID"] in result or identity_location(a) is None:
            continue
        t = fnum(a.get("SSO_DATE"))
        hits = []
        for p in locations.get(identity_location(a), []):
            old = p.get("raw") or {}
            pt = fnum(old.get("SSO_DATE"))
            if "SSOID" not in old and t is not None and pt is not None and abs(t - pt) <= 600_000:
                hits.append(p)
        if len(hits) == 1:
            candidates[a["OBJECTID"]] = hits[0]
    counts = Counter(p["event_id"] for p in candidates.values())
    for oid, p in candidates.items():
        if counts[p["event_id"]] == 1:
            result[oid] = (p, "We link the City's reissued legacy row by the same street, rounded point and "
                          "SSO_DATE within 10 minutes, with one candidate in each direction.")
    return result


def build(features: list[dict], fetched_at: str, prev_records: list[dict]) -> tuple[list[dict], dict]:
    prev = {r["event_id"]: copy.deepcopy(r) for r in prev_records}
    links = crosswalk(features, prev)
    records, seen = [], set()
    for a in features:
        if a.get("OBJECTID") is None:
            continue
        eid = f"{SOURCE_ID}:{a['OBJECTID']}"
        p, basis = links.get(a["OBJECTID"], (prev.get(eid) if "SSOID" not in a else None, None))
        if p:
            eid = p["event_id"]
        if eid in seen:
            raise ValueError("ambiguous City event identity; no records replaced")
        if p is None and eid in prev and "SSOID" in a:
            raise ValueError("City OBJECTID reused without a confirmed identity; no records replaced")
        seen.add(eid)
        r = to_record(a, fetched_at, p)
        if basis:
            pr = (p or {}).get("raw") or {}
            r["raw"]["_identity_basis"] = pr.get("_identity_basis") or basis
            r["raw"]["_legacy_objectid"] = pr.get("_legacy_objectid", (p or {}).get("source_record_id"))
        records.append(r)
    # Old polls may already have retained both sides of a City reissue. Keep
    # both published IDs, but count the overflow only once and link the evidence.
    aliases = crosswalk(features, {eid: r for eid, r in prev.items() if eid not in seen},
                        uniqueness_records=prev)
    current = {r["raw"].get("OBJECTID"): r["event_id"] for r in records}
    alias_targets = {p["event_id"]: (current[oid], basis) for oid, (p, basis) in aliases.items() if oid in current}
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        r.setdefault("raw", {})
        if eid in alias_targets:
            target, basis = alias_targets[eid]
            r["duplicate_of"] = target
            r["raw"]["_other_source_record"] = target
            r["raw"]["_duplicate_basis"] = basis
        r["raw"]["_missing_from_layer_since"] = r["raw"].get("_missing_from_layer_since") or fetched_at
        records.append(r)
        kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"layer_rows": len(seen), "kept_from_earlier_runs": kept,
             "by_status": dict(Counter(r["status"] for r in records)),
             "water_match": dict(Counter(r["water_match"] for r in records)),
             "with_coordinates": sum(1 for r in records if r.get("lat") is not None)}
    return records, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved query response instead of the layer")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    gone: list[str] = []
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            pages = d.get("pages") or [d]
            features = [safe_attributes(f.get("attributes") or {}) for p in pages for f in p.get("features") or []]
            raw_bytes = None
        else:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            features, raw_bytes, gone = query_layer(sess)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    for r in prev:      # records saved before the safe-field and three-decimal rules
        for k in ("lat", "lon"):
            if fnum(r.get(k)) is not None:
                r[k] = round(float(r[k]), 3)
        rr = r.get("raw") or {}
        rr.update(safe_attributes(rr))
        if r.get("outfall_name"):
            r["outfall_name"] = strip_house_numbers(scrub_names(scrub_text(r["outfall_name"])))
        for k in ("WAIVER_REASON", "COMMENT_RELIEF_REQUEST_TYPE"):     # not safe fields
            rr.pop(k, None)
        for k in ("Latitude", "Longitude"):
            if fnum(rr.get(k)) is not None:
                rr[k] = round(float(rr[k]), 3)
    try:
        records, stats = build(features, fetched_at, prev)
    except Exception as e:  # noqa: BLE001 - preserve previous records on identity conflicts
        write_events(SOURCE_ID, [], ok=False, error=error_text(e))
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    state = read_json(STATE_FILE, {}) or {}
    raw_path = state.get("raw_path")
    if raw_bytes is not None:
        sha = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, raw_bytes, "json").relative_to(ROOT))
            state = {"sha256": sha, "raw_path": raw_path, "saved_at": fetched_at}
        state["fetched_at"] = fetched_at
        write_json(STATE_FILE, state)
    records = redact.redact_events(records)      # private individuals' names in quoted text (build/redact.py)
    meta = {**stats, "layer": LAYER, "raw_path": raw_path, "time_basis": TIME_BASIS,
            "credit": "Baltimore City Department of Public Works, All SSOs",
            "registry_ids": ["md-baltimore-dpw-sso-map"], "safe_fields_missing_from_layer": gone}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    from ingest.md_mde_overflows import relink_baltimore_files
    try:
        relink_baltimore_files(records, EVENTS_DIR)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=error_text(e))
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    print(f"{SOURCE_ID}: {stats['layer_rows']} layer rows, {stats['kept_from_earlier_runs']} kept from earlier runs; "
          f"status {stats['by_status']}; water match {stats['water_match']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
