"""MassDEP Sewage Notification portal -> data/build/events/ma-massdep.json

Source
  The MassDEP "Sewage Notification" public portal on the EEA Data Portal
  (https://eeaonline.eea.state.ma.us/portal/dep/cso-data-portal/) is an Angular app over an
  undocumented JSON API at https://eeaonline.eea.state.ma.us/dep/CSOAPI/api/. Every report
  required by M.G.L. c. 21 s. 43A / 314 CMR 16.00 lands here (since 2022-07-06): CSO, partially
  treated (blended / other) and the three reportable SSO types. Records come in three classes:
  Public Notification Reports (Initial-Ongoing, Initial-Ceased, and "Ceased" child updates numbered
  <parent>-1), Verified Data Reports (about a month later, per outfall-event, with volume in
  gallons, rainfall and duration hours + minutes) and "No Events for the month" attestations
  (kept in meta, not as events). Credit: "MassDEP Sewage Notification Data System, via the EEA
  Data Portal". The portal's disclaimer says the data are not fully verified.

Quirks (research/ma/report.md 2.2)
  - Undocumented API; it answers HTTP 500 unless the request carries Origin
    https://eeaonline.eea.state.ma.us and the portal Referer. No key, no visible rate limit.
  - The IncidentFromDate / IncidentToDate filters return HTTP 500 in every format, so we page
    GetIncidentsBySearchFields ordered by submittedDate desc and filter client-side.
  - No end timestamp anywhere. "Ceased" children carry no cessation time; ended_at exists only
    when a Verified Data Report gives a duration (ended_at = start + hours/minutes, computed and
    noted in raw). Zero verified volume is how DEP records a retraction.
  - No timezone: incidentDate (midnight) + incidentTime (local clock, 2022-23 rows use amPm) and
    submittedDate are read as America/New_York.
  - List rows show children with parentIncidentId null; we link them by incidentNumber
    (26017854-1 -> 26017854) and, when the parent is not in hand, by GetIncidentById.
  - The detail call returns reporterName / createdBy / modifiedBy / uploadedBy (staff names and
    emails): dropped before anything is saved, raw files included; emails in free text are masked.
  - Coordinates are null on most rows: outfallId is joined to the MassDEP CSOs layer
    (DEP_OUTFL_, cached in data/build/ma-cso-outfalls.json for a day), then to the ECHO outfall
    registry (data/outfalls-new-england.json, permit + outfall number).
  - The advisory text is only in attached .eml/.pdf files whose download returns 500, so
    advice_text is the 314 CMR 16.04(10)(g) required wording unless the record itself carries it.
  - Portal lag: Springfield median 18 h, Holyoke 39 h, Chicopee days; weekend events land Monday.

Cadence
  Poll every 15-30 minutes (`--since 2` is plenty for a poll; the default 30 days also re-reads
  late Verified Data Reports). Run `--backfill` once (about 20 pages of 1,000, 2 s apart).
  Every fetched row is kept in data/build/ma-massdep-rows.json (upsert by incidentId) so the
  events file holds the whole history seen so far, not only the polled window.

Usage (from pipeline/):  python -m ingest.ma_massdep [--since DAYS] [--backfill] [--max-details N]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, DATA_DIR, HEADERS, PERSONAL_KEYS, ROOT, event, now_iso,
                    parse_volume_gal, read_json, save_raw, write_events, write_json)

SOURCE_ID = "ma-massdep"
API = "https://eeaonline.eea.state.ma.us/dep/CSOAPI/api/"
PORTAL = "https://eeaonline.eea.state.ma.us/portal/dep/cso-data-portal/"
DETAILS_URL = PORTAL + "details/{}"
API_HEADERS = {**HEADERS, "Accept": "application/json, text/plain, */*",
               "Origin": "https://eeaonline.eea.state.ma.us", "Referer": PORTAL}
CSO_LAYER_URL = ("https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/"
                 "MassDEP_CSOs_2/FeatureServer/0")
FIRST_DAY = date(2022, 7, 6)  # 314 CMR 16.04 enforceable; first record in the portal
TZ = ZoneInfo("America/New_York")

ROWS_PATH = BUILD_DIR / "ma-massdep-rows.json"
LAYER_CACHE = BUILD_DIR / "ma-cso-outfalls.json"
LAYER_FALLBACK = ROOT / "research/ma/raw/portal/massdep-csos-all.json"
# The hand-kept portal-name -> water-slug crosswalk: the tracked copy in data/reference/ first (the public data
# repository carries it), else the research raw folder on the machine that built it; missing: no crosswalk.
CROSSWALK = next((p for p in (ROOT / "data/reference/ma-portal-waterbody-crosswalk.csv",
                               ROOT / "research/ma/raw/portal/waterbody-crosswalk.csv") if p.exists()),
                 ROOT / "data/reference/ma-portal-waterbody-crosswalk.csv")
DISCHARGERS = ROOT / "research/ma/dischargers.json"
WATERS_CSV = DATA_DIR / "waters-new-england.csv"
ECHO_OUTFALLS = DATA_DIR / "outfalls-new-england.json"

ADVICE_314 = ("Avoid contact with these water bodies for 48 hours after the discharge or overflow "
              "ceases due to increased health risks from bacteria and other pollutants. See website "
              "for more information on whether specific resource areas, such as bathing beaches, "
              "are affected.")
ADVICE_BASIS = "314 CMR 16.04(10)(g)"

# keys that hold people (on top of common.PERSONAL_KEYS, which misses these two) ...
EXTRA_PERSONAL = {"modifiedby", "uploadedby"}
# ... and keys PERSONAL_KEYS would wrongly drop ("reporter" also matches the report class)
KEEP_KEYS = {"reporterClass", "reporterClassId"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PERMIT_RE = re.compile(r"^MA[A-Z0-9]{7}$")


# ---------------------------------------------------------------- privacy

def scrub(obj):
    """Drop personal keys (reporterName, createdBy, modifiedBy, uploadedBy ...) and mask email
    addresses in free text, recursively. Used on everything before it is saved."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k not in KEEP_KEYS and (PERSONAL_KEYS.search(str(k)) or str(k).lower() in EXTRA_PERSONAL):
                continue
            out[k] = scrub(v)
        return out
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str) and "@" in obj:
        return EMAIL_RE.sub("[email removed]", obj)
    return obj


# ---------------------------------------------------------------- HTTP

def get(sess: requests.Session, url: str, params=None, tries: int = 3, timeout: int = 90) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = sess.get(url, params=params, timeout=timeout)
            if r.status_code < 500:
                r.raise_for_status()
                return r
            last = requests.HTTPError(f"HTTP {r.status_code} for {r.url}")
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
        time.sleep(3 * (i + 1))
    raise last


def fetch_list_page(sess, page: int, size: int) -> dict:
    url = (f"{API}Incident/GetIncidentsBySearchFields/?pageNumber={page}&pageSize={size}"
           f"&&orderBy=submittedDate%20desc")
    r = get(sess, url)
    data = scrub(r.json())
    save_raw(SOURCE_ID, json.dumps(data, ensure_ascii=False), f"list-p{page:03d}-s{size}.json")
    return data


def fetch_detail(sess, incident_id: str) -> dict:
    r = get(sess, f"{API}Incident/GetIncidentById", params={"id": incident_id})
    data = scrub(r.json())
    save_raw(SOURCE_ID, json.dumps(data, ensure_ascii=False), f"detail-{incident_id}.json")
    return data


def detail_to_row(d: dict) -> dict:
    """GetIncidentById's incidentInformation in the list-row shape."""
    i = d.get("incidentInformation") or {}
    return {
        "incidentId": i.get("incidentId"), "incidentNumber": i.get("incidentNumber"),
        "incidentDate": i.get("incidentDate"), "incidentTime": i.get("incidentTime"), "amPm": i.get("amPm"),
        "reporterClass": i.get("reporterClass"), "eventType": i.get("eventType"),
        "permiteeClass": i.get("permiteeClass"), "permiteeName": i.get("permitee"),
        "permiteeId": i.get("permiteeNumber"), "outfallId": i.get("outfall"),
        "municipality": i.get("municipality"), "reportingType": i.get("reportingType"),
        "location": i.get("location") if i.get("location") != "Other" else (i.get("otherLocation") or "Other"),
        "latitude": i.get("latitude"), "longitude": i.get("longitude"),
        "waterBody": i.get("waterBody") if i.get("waterBody") != "Other" else (i.get("waterBodyOther") or "Other"),
        "waterBodyDescription": i.get("waterBodyDescription"),
        "volumnOfEvent": i.get("volumnOfEvent"), "rainfallData": i.get("rainfallData"),
        "hours": i.get("hours"), "minutes": i.get("minutes"), "month": i.get("month"), "year": i.get("year"),
        "additionalInformation": i.get("additionalInformation"), "submittedDate": i.get("submittedDate"),
        "parentIncidentId": i.get("parentIncidentId"),
    }


def detail_extra(d: dict) -> dict:
    i = d.get("incidentInformation") or {}
    keep = {k: v for k, v in i.items() if k.startswith(("did", "was", "for", "ifYou"))}
    return {"createdDt": i.get("createdDt"), "modifiedDt": i.get("modifiedDt"),
            "parentIncidentId": i.get("parentIncidentId"), "self_check": keep,
            "attachments": [a.get("attachmentName") for a in (d.get("incidentDocuments") or [])]}


# ---------------------------------------------------------------- reference data

def load_cso_layer(sess) -> tuple[dict, dict]:
    """MassDEP_CSOs_2 by DEP_OUTFL_ id. Cached a day; on failure use the cache however old, then
    the research copy."""
    cache = read_json(LAYER_CACHE)
    if cache:
        age = datetime.now(UTC) - datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
        if age < timedelta(days=1):
            return cache["outfalls"], {"source": "cache", "fetched_at": cache["fetched_at"]}
    try:
        r = get(sess, CSO_LAYER_URL + "/query",
                params={"where": "1=1", "outFields": "*", "outSR": "4326", "f": "json",
                        "resultRecordCount": 2000}, timeout=60)
        save_raw(SOURCE_ID, r.content, "cso-layer.json")
        data = r.json()
        if "features" not in data:
            raise ValueError(f"layer answered without features: {str(data)[:200]}")
        how = {"source": "live", "fetched_at": now_iso()}
    except Exception as e:  # noqa: BLE001
        if cache:
            return cache["outfalls"], {"source": "stale cache", "fetched_at": cache["fetched_at"], "error": str(e)}
        data = json.loads(LAYER_FALLBACK.read_text())
        how = {"source": "research copy 2026-11-01", "fetched_at": None, "error": str(e)}
    outfalls = {}
    for f in data["features"]:
        a = f["attributes"]
        g = f.get("geometry") or {}
        rec = {"dep_id": a.get("DEP_OUTFL_"), "npdes": a.get("NPDES_ID"), "outfall": a.get("OUTFALL_ID"),
               "system": a.get("SYSTEMNAME"), "receiving_water": a.get("RECVING_WA"),
               "address": a.get("ADDRESS"), "town": a.get("TOWN"),
               "lat": a.get("POINT_Y") or g.get("y"), "lon": a.get("POINT_X") or g.get("x")}
        for part in str(a.get("DEP_OUTFL_") or "").split("/"):  # "SOM007A/MWR205A"
            if part.strip():
                outfalls.setdefault(part.strip().upper(), rec)
    if how["source"] == "live":
        write_json(LAYER_CACHE, {"fetched_at": how["fetched_at"], "url": CSO_LAYER_URL,
                                 "terms": "Locations are estimates and should only be used as a guide.",
                                 "count": len(data["features"]), "outfalls": outfalls})
    how["count"] = len(data["features"])
    return outfalls, how


def norm_name(s: str | None) -> str:
    s = (s or "").upper().strip()
    s = re.sub(r"\bR\.?(?=\s|$)", "RIVER", s)
    s = re.sub(r"\bBK\.?(?=\s|$)", "BROOK", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_crosswalk() -> dict:
    cw = {}
    if not CROSSWALK.exists():
        print(f"{SOURCE_ID if 'SOURCE_ID' in globals() else 'ma-massdep'}: no waterbody crosswalk at {CROSSWALK.name}; "
              "water names resolve by name only (copy the crosswalk to data/reference/)", file=sys.stderr)
        return cw
    with CROSSWALK.open() as fh:
        for row in csv.DictReader(fh):
            v = (row["water_slug"].strip() or None, row["confidence"].strip(), row["note"].strip())
            cw[row["portal_waterBody"].strip().upper()] = v
            cw.setdefault("N:" + norm_name(row["portal_waterBody"]), v)
    return cw


def load_waters() -> dict:
    idx = defaultdict(list)
    with WATERS_CSV.open() as fh:
        for row in csv.DictReader(fh):
            if row["state"] == "MA":
                towns = {t.strip().upper() for t in row["towns"].split(";") if t.strip()}
                idx[norm_name(row["name"])].append((row["slug"], towns))
    return idx


def load_echo() -> dict:
    idx = {}
    for o in (read_json(ECHO_OUTFALLS, {}) or {}).get("outfalls", []):
        if o.get("state") == "MA":
            idx[(o["npdes_permit"], str(o["outfall"]).upper())] = o
    return idx


def load_dischargers() -> dict:
    return {d["npdes_permit"]: d["id"] for d in (read_json(DISCHARGERS, []) or []) if d.get("npdes_permit")}


# ---------------------------------------------------------------- parsing helpers

def blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in ("", ":"))


def local_dt(s: str | None) -> datetime | None:
    if blank(s):
        return None
    return datetime.fromisoformat(str(s).strip()[:26]).replace(tzinfo=TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def parse_start(row: dict) -> tuple[datetime | None, str | None, str | None]:
    """incidentDate (midnight) + incidentTime ('09:20', '9:20', '9:20 PM' or amPm) -> (dt, precision, problem)."""
    if blank(row.get("incidentDate")):
        return None, None, "no incidentDate"
    d = datetime.fromisoformat(str(row["incidentDate"])[:19]).date()
    t = (row.get("incidentTime") or "").strip()
    if blank(t):
        return datetime(d.year, d.month, d.day, tzinfo=TZ), "day", None
    m = re.match(r"^(\d{1,2})(?::|\.)?(\d{2})(?::\d{2})?\s*([AaPp]\.?[Mm]\.?)?$", t)
    if not m:
        return datetime(d.year, d.month, d.day, tzinfo=TZ), "day", f"incidentTime {t!r} not understood; day precision"
    hh, mm = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or row.get("amPm") or "").replace(".", "").upper()
    if ap in ("AM", "PM"):
        if not 1 <= hh <= 12:
            return datetime(d.year, d.month, d.day, tzinfo=TZ), "day", f"incidentTime {t!r} {ap} out of range; day precision"
        hh = (0 if hh == 12 else hh) + (12 if ap == "PM" else 0)
    if hh == 24 and mm == 0:
        return datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(days=1), "minute", None
    if hh > 23 or mm > 59:
        return datetime(d.year, d.month, d.day, tzinfo=TZ), "day", f"incidentTime {t!r} out of range; day precision"
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ), "minute", None


def num(v) -> float | None:
    if blank(v):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def event_type_of(s: str | None) -> str | None:
    t = (s or "").replace("–", "-").replace("—", "-").lower()
    if t.startswith("cso"):
        return "cso"
    if t.startswith("sso"):
        return "sso"
    if "blended" in t:
        return "blended"
    if t.startswith("partially treated"):
        return "bypass"  # "Partially Treated - Other": treatment units bypassed
    return None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------- joins

def layer_lookup(layer: dict, outfall_id: str | None) -> dict | None:
    if blank(outfall_id):
        return None
    o = str(outfall_id).strip().upper()
    return layer.get(o) or layer.get(o.split("/")[0])


def echo_lookup(echo: dict, permit: str | None, outfall_id: str | None, lay: dict | None) -> dict | None:
    if lay and lay.get("npdes") and lay.get("outfall"):
        hit = echo.get((lay["npdes"], str(lay["outfall"]).upper()))
        if hit:
            return hit
    if not permit or blank(outfall_id):
        return None
    o = str(outfall_id).strip().upper()
    m = re.match(r"^[A-Z]*?(\d+)([A-Z]?)(?:-\d+)?$", o)
    tries = [o]
    if m:
        n, suf = m.group(1), m.group(2)
        tries += [n.zfill(3) + suf, n.zfill(3), n]
    for t in tries:
        if (permit, t) in echo:
            return echo[(permit, t)]
    return None


def resolve_water(texts: list[tuple[str, str]], town: str | None, echo_rec: dict | None,
                  cw: dict, waters: dict) -> tuple[list, str, dict]:
    """texts: [(label, waterbody text)] in priority order. Returns (slugs, water_match, note)."""
    note = {}
    explicit_none = []
    for label, text in texts:
        if blank(text):
            continue
        key = str(text).strip().upper()
        hit = cw.get(key) or cw.get("N:" + norm_name(text))
        if hit:
            slug, conf, why = hit
            if slug:
                match = "inferred" if conf == "low" else ("name" if label.startswith("portal") else "outfall_registry")
                note.update({"via": f"crosswalk on {label} waterbody", "text": text, "confidence": conf})
                return [slug], match, note
            explicit_none.append(f"{text} ({why or 'no slug'})")
    if echo_rec and echo_rec.get("water_slug"):
        em = echo_rec.get("match")
        words = {w for t in texts for w in norm_name(t[1]).split() if len(w) > 3 and w not in ("RIVER", "BROOK", "HARBOR", "CHANNEL")}
        name_ok = bool(words & set(norm_name(echo_rec.get("water_name")).split()))
        if em in ("geometry+name", "name_only") or (em == "geometry" and name_ok):
            note.update({"via": "ECHO outfall registry (data/outfalls-new-england.json)", "echo_match": em,
                         "distance_m": echo_rec.get("distance_m")})
            return [echo_rec["water_slug"]], "outfall_registry", note
        note["echo_candidate"] = {"slug": echo_rec["water_slug"], "match": em, "why_not": "geometry only, name differs"}
    for label, text in texts:
        if blank(text):
            continue
        key = str(text).strip().upper()
        if key in cw or ("N:" + norm_name(text)) in cw:
            continue  # the crosswalk already decided this name has no slug
        names = [norm_name(text)]
        tail = re.split(r"\b(?:TO THE|TO)\b", norm_name(text))
        if len(tail) > 1:
            names.append(tail[-1].strip())
        for i, n in enumerate(names):
            cands = waters.get(n, [])
            local = [s for s, towns in cands if town and town.strip().upper() in towns]
            if len(local) == 1:
                note.update({"via": f"name + town on {label} waterbody", "text": text})
                return local, ("name" if i == 0 else "inferred"), note
            if cands:
                note["name_candidates"] = [s for s, _ in cands]
    if explicit_none:
        note["no_slug"] = explicit_none
    return [], "none", note


# ---------------------------------------------------------------- normalise

def normalise(entry: dict, ctx: dict) -> dict:
    row = entry["row"]
    rid = row.get("incidentId") or row.get("incidentNumber") or hashlib.sha1(
        json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]
    base = dict(source_id=SOURCE_ID, source_record_id=rid, fetched_at=entry.get("fetched_at") or now_iso(),
                source_url=DETAILS_URL.format(row["incidentId"]) if row.get("incidentId") else PORTAL)
    try:
        return build_event(row, entry, ctx, base)
    except Exception as e:  # noqa: BLE001 - never drop a record
        raw = dict(row)
        raw["_report_class"] = row.get("reporterClass")
        return event(**base, event_type="unknown", status="unknown", raw=raw,
                     parse_error=f"{type(e).__name__}: {e}")


def build_event(row: dict, entry: dict, ctx: dict, base: dict) -> dict:
    problems = []
    raw = dict(row)
    raw["_report_class"] = row.get("reporterClass")  # common.strip_personal drops "reporterClass"
    raw["_tz_assumed"] = "America/New_York (portal gives local clock time without zone)"
    detail = entry.get("detail")
    if detail:
        raw["_detail"] = detail

    etype = event_type_of(row.get("eventType"))
    if etype is None:
        problems.append(f"eventType {row.get('eventType')!r} not recognised")
        etype = "unknown"

    cls = (row.get("reporterClass") or "").strip()
    rtype = (row.get("reportingType") or "").strip()
    start, prec, tprob = parse_start(row)
    if tprob:
        problems.append(tprob)

    ended_at = None
    if cls == "Verified Data Report":
        status = "ended"
        h, m = num(row.get("hours")), num(row.get("minutes"))
        if start and prec == "minute" and (h is not None or m is not None):
            dur = timedelta(hours=h or 0, minutes=m or 0)
            ended_at = start + dur
            raw["_ended_at_basis"] = (f"computed: started_at + verified duration {row.get('hours') or 0} h "
                                      f"{row.get('minutes') or 0} min (Verified Data Report)")
    elif rtype in ("Initial-Ongoing", "Ongoing"):   # "Ongoing" = the 8-hourly update notice while a discharge continues
        status = "ongoing"
    elif rtype in ("Initial-Ceased", "Ceased"):
        status = "ended"
        raw["_ended_note"] = "reported ceased; the portal gives no cessation time"
    else:
        status = "unknown"
        problems.append(f"reporterClass {cls!r} / reportingType {rtype!r} not recognised")

    permit = (row.get("permiteeId") or "").strip().upper()
    permit = permit if PERMIT_RE.match(permit) else None
    name = (row.get("permiteeName") or "").strip() or None
    outfall = (row.get("outfallId") or "").strip() or None
    town = (row.get("municipality") or "").strip() or None

    lay = layer_lookup(ctx["layer"], outfall)
    echo = echo_lookup(ctx["echo"], permit or (lay or {}).get("npdes"), outfall, lay)
    lat = lon = None
    coord_source = None
    src_lat, src_lon = num(row.get("latitude")), num(row.get("longitude"))
    if lay and lay.get("lat") is not None:
        lat, lon, coord_source = round(lay["lat"], 6), round(lay["lon"], 6), "outfall_layer"
        raw["_coords"] = f"MassDEP CSOs layer DEP_OUTFL_ {lay['dep_id']} (locations are estimates)"
    elif src_lat is not None and src_lon is not None and 41 < src_lat < 43.1 and -73.6 < src_lon < -69.8:
        lat, lon, coord_source = round(src_lat, 6), round(src_lon, 6), "source"
    elif echo and echo.get("lat") is not None:
        lat, lon, coord_source = echo["lat"], echo["lon"], "outfall_layer"
        raw["_coords"] = f"EPA ECHO CSO inventory {echo['npdes_permit']} outfall {echo['outfall']}"
    elif src_lat is not None or src_lon is not None:
        problems.append(f"latitude/longitude {row.get('latitude')!r},{row.get('longitude')!r} outside MA; ignored")

    wb = (row.get("waterBody") or "").strip() or None
    wb_desc = (row.get("waterBodyDescription") or "").strip() or None
    waterbody_text = wb_desc if (wb in (None, "Other") and wb_desc) else wb
    texts = [("portal", wb), ("portal description", wb_desc), ("outfall layer", (lay or {}).get("receiving_water"))]
    slugs, wmatch, wnote = resolve_water(texts, town, echo, ctx["crosswalk"], ctx["waters"])
    if wnote:
        raw["_water"] = wnote

    vol_raw = row.get("volumnOfEvent")
    volume_gal, est = parse_volume_gal(None if blank(vol_raw) else vol_raw)
    volume_text = None if blank(vol_raw) else str(vol_raw)
    if volume_text is not None:
        if cls == "Public Notification Report":
            est = "estimated"  # s. 43A(b): notices estimate from the prior 3 years' average
        else:
            raw["_volume_note"] = "verified by permittee, reported to MassDEP (metered or modelled not stated)"
        if volume_gal == 0:
            raw["_volume_note"] = "zero volume: MassDEP records a retraction this way"

    info = row.get("additionalInformation") or ""
    if re.search(r"avoid (?:all )?contact", info, re.I):
        advice_text, raw["_advice_source"] = info.strip(), "record (additionalInformation)"
    elif etype != "unknown":
        advice_text = ADVICE_314
        raw["_advice_source"] = ("required wording of 314 CMR 16.04(10)(g); the permittee's own advisory "
                                 "is only in an attachment the portal will not serve")
    else:
        advice_text = None

    if cls == "Public Notification Report" and rtype == "Ceased":
        raw["_parent_number"] = re.sub(r"-\d+$", "", str(row.get("incidentNumber") or ""))

    return event(
        **base, event_type=etype, status=status,
        discharger_id=ctx["dischargers"].get(permit) or (f"ma-{slugify(name)}" if name else None),
        discharger_name=name, npdes_permit=permit or (lay or {}).get("npdes"),
        outfall_id=outfall,
        outfall_name=(row.get("location") if row.get("location") not in (None, "", "Other") else (lay or {}).get("address")),
        waterbody_text=waterbody_text, water_slugs=slugs, water_match=wmatch,
        lat=lat, lon=lon, coord_source=coord_source, coord_precision_m=None,
        started_at=iso(start), ended_at=iso(ended_at), time_precision=prec,
        reported_at=None, published_at=iso(local_dt(row.get("submittedDate"))),
        source_updated_at=iso(local_dt((detail or {}).get("modifiedDt"))) if detail else None,
        material=row.get("eventType"), volume_gal=volume_gal, volume_text=volume_text, estimate_flag=est,
        authority=f"{name} (MassDEP sewage notification portal)" if name else "MassDEP sewage notification portal (permittee not named)",
        advice_text=advice_text,
        advice_window_hours=48 if advice_text else None,
        advice_window_basis=ADVICE_BASIS if advice_text else None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


# ---------------------------------------------------------------- linking

def link(records: list[dict], rows: dict) -> dict:
    """Children -> parents. 'Ceased' updates by incidentNumber (or the detail's parentIncidentId);
    Verified Data Reports to the notice for the same permittee, outfall and day. A parent with a
    Ceased child or a verified duration becomes 'ended'; a verified duration also gives it ended_at."""
    by_id = {r["source_record_id"]: r for r in records}
    by_number = {}
    for r in records:
        n = r["raw"].get("incidentNumber")
        if n:
            by_number[str(n)] = r
    stats = Counter()

    # Ceased children
    for r in records:
        if r["raw"].get("_report_class") != "Public Notification Report" or r["raw"].get("reportingType") != "Ceased":
            continue
        pid = (rows.get(r["source_record_id"], {}).get("parent_incident_id")
               or r["raw"].get("parentIncidentId"))
        parent = by_id.get(pid) if pid else by_number.get(r["raw"].get("_parent_number") or "")
        if parent is None and pid:
            r["parent_event_id"] = f"{SOURCE_ID}:{pid}"
            r["raw"]["_link_basis"] = "parentIncidentId from GetIncidentById; parent not in file"
            stats["ceased_parent_not_in_file"] += 1
            continue
        if parent is None:
            stats["ceased_orphan"] += 1
            continue
        r["parent_event_id"] = parent["event_id"]
        r["raw"]["_link_basis"] = "parentIncidentId" if pid else "incidentNumber suffix"
        stats["ceased_linked"] += 1
        if parent["status"] == "ongoing":
            parent["status"] = "ended"
            parent["raw"]["_status_note"] = (f"ended per Ceased update {r['raw'].get('incidentNumber')} "
                                             f"(published {r['published_at']}); no cessation time given")

    # Verified Data Reports -> the notice for the same permittee and outfall whose start is within
    # 3 h of the verified start, or inside the verified period (some notices gave the end time as
    # the start: "initial notification originally listed the end time instead of the start time").
    dt = datetime.fromisoformat
    notices, vdrs = defaultdict(list), defaultdict(list)
    for r in records:
        if not r["started_at"] or not r["outfall_id"]:
            continue
        key = (r["discharger_name"], r["outfall_id"].upper())
        if (r["raw"].get("_report_class") == "Public Notification Report"
                and r["raw"].get("reportingType") in ("Initial-Ongoing", "Initial-Ceased")):
            notices[key].append(r)
        elif r["raw"].get("_report_class") == "Verified Data Report":
            vdrs[key].append(r)
    has_vdr = set()
    for key, vs in vdrs.items():
        for v in vs:
            s, e = dt(v["started_at"]), dt(v["ended_at"]) if v["ended_at"] else None
            q = [n for n in notices.get(key, [])
                 if abs(dt(n["started_at"]) - s) <= timedelta(hours=3)
                 or (e and s <= dt(n["started_at"]) <= e + timedelta(hours=1))]
            if not q:
                stats["verified_no_notice"] += 1
                continue
            best = min(q, key=lambda n: abs(dt(n["started_at"]) - s))
            gap = int(abs(dt(best["started_at"]) - s).total_seconds() // 60)
            v["parent_event_id"] = best["event_id"]
            v["raw"]["_link_basis"] = (f"same permittee and outfall as notice {best['raw'].get('incidentNumber')}; "
                                       f"start times {gap} min apart")
            has_vdr.add(best["event_id"])
            stats["verified_linked"] += 1
            if v["ended_at"] and dt(v["ended_at"]) < dt(best["started_at"]):
                # the verified discharge ended before this notice's own start (the notice gave its report
                # time, or the end, as the start): its end would precede the start, so the notice keeps
                # its own times and the verified report (its child, which supersedes it) carries the period
                best["raw"]["_verified_period"] = (f"Verified Data Report {v['raw'].get('incidentNumber')}: "
                                                   f"{v['started_at']} to {v['ended_at']}, before this notice's start")
                stats["verified_end_before_notice_start"] += 1
            elif v["ended_at"] and (not best["ended_at"] or dt(v["ended_at"]) > dt(best["ended_at"])):
                best["ended_at"] = v["ended_at"]
                best["raw"]["_ended_at_basis"] = (f"from Verified Data Report {v['raw'].get('incidentNumber')}: "
                                                  f"its start + verified duration")
            if best["status"] != "ended":
                best["status"] = "ended"
                best["raw"]["_status_note"] = f"ended per Verified Data Report {v['raw'].get('incidentNumber')}"
    # A notice with no verified report of its own whose start lies inside another verified
    # discharge period at the same outfall (a re-notice of a continuing discharge).
    for key, ns in notices.items():
        for n in ns:
            if n["event_id"] in has_vdr:
                continue
            t = dt(n["started_at"])
            cover = [v for v in vdrs.get(key, []) if v["ended_at"] and dt(v["started_at"]) <= t <= dt(v["ended_at"])]
            if not cover:
                continue
            v = max(cover, key=lambda x: dt(x["ended_at"]))
            n["parent_event_id"] = v["parent_event_id"] or v["event_id"]
            n["raw"]["_link_basis"] = (f"start lies inside the verified discharge period of Verified Data Report "
                                       f"{v['raw'].get('incidentNumber')} at the same outfall")
            if not n["ended_at"]:
                n["ended_at"] = v["ended_at"]
                n["raw"]["_ended_at_basis"] = f"end of the verified period of {v['raw'].get('incidentNumber')} that covers this notice"
            if n["status"] != "ended":
                n["status"] = "ended"
                n["raw"]["_status_note"] = f"inside the verified period of {v['raw'].get('incidentNumber')}"
            stats["notice_inside_verified_period"] += 1
    # Ceased updates take their parent's verified end.
    by_event = {r["event_id"]: r for r in records}
    for r in records:
        p = by_event.get(r["parent_event_id"]) if r["raw"].get("reportingType") == "Ceased" else None
        if p and p["ended_at"] and not r["ended_at"] and not (
                r["started_at"] and dt(p["ended_at"]) < dt(r["started_at"])):
            r["ended_at"] = p["ended_at"]
            r["raw"]["_ended_at_basis"] = f"parent notice's verified end ({p['raw'].get('_ended_at_basis')})"
    return dict(stats)


# ---------------------------------------------------------------- main

def fetch_rows(sess, since_days: int, backfill: bool) -> tuple[list[dict], dict]:
    size = 1000 if backfill else (100 if since_days <= 7 else 500)
    cutoff = (datetime.combine(FIRST_DAY, datetime.min.time(), TZ) if backfill
              else datetime.now(TZ) - timedelta(days=since_days))
    out, page, info = [], 1, {}
    while True:
        data = fetch_list_page(sess, page, size)
        res = data.get("results") or []
        info = {k: data.get(k) for k in ("pageCount", "rowCount")}
        oldest = None
        for row in res:
            try:
                sub = local_dt(row.get("submittedDate"))
            except ValueError:
                sub = None
            if sub is None or sub >= cutoff:
                out.append(row)
            if sub is not None:
                oldest = sub if oldest is None else min(oldest, sub)
        print(f"  page {page}/{data.get('pageCount')}: {len(res)} rows, oldest submitted {iso(oldest)}", file=sys.stderr)
        if not res or page >= (data.get("pageCount") or 0) or (oldest is not None and oldest < cutoff):
            break
        page += 1
        time.sleep(2.0 if backfill else 1.0)
    info["pages"] = page
    info["cutoff"] = iso(cutoff)
    return out, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", type=int, default=30, help="days of submissions to fetch (default 30)")
    ap.add_argument("--backfill", action="store_true", help="page everything back to 2022-07-06")
    ap.add_argument("--max-details", type=int, default=60,
                    help="cap on GetIncidentById calls per run (orphan Ceased updates and their parents)")
    args = ap.parse_args(argv)

    sess = requests.Session()
    sess.headers.update(API_HEADERS)
    store = read_json(ROWS_PATH, {}) or {}
    rows: dict = store.get("rows", {})
    try:
        fetched, info = fetch_rows(sess, args.since, args.backfill)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"fetch failed: {e}", file=sys.stderr)
        return 1

    stamp_now = now_iso()
    seen = set()
    for row in fetched:
        key = row.get("incidentId") or row.get("incidentNumber") or hashlib.sha1(
            json.dumps(row, sort_keys=True).encode()).hexdigest()[:16]
        seen.add(key)
        prev = rows.get(key, {})
        rows[key] = {**prev, "row": row, "fetched_at": stamp_now,
                     "first_seen_at": prev.get("first_seen_at") or stamp_now, "via": "list"}
        rows[key].pop("missing_since", None)
    cutoff = datetime.fromisoformat(info["cutoff"])
    for key, e in rows.items():  # rows we hold for the window that the source no longer lists
        try:
            sub = local_dt(e["row"].get("submittedDate"))
        except ValueError:
            sub = None
        if key not in seen and e.get("via") == "list" and sub and sub >= cutoff:
            e.setdefault("missing_since", stamp_now)

    # Ceased updates whose parent we do not hold: ask the detail endpoint, then fetch the parent.
    numbers = {str(e["row"].get("incidentNumber")) for e in rows.values()}
    budget = args.max_details
    for key, e in list(rows.items()):
        r = e["row"]
        if budget <= 0:
            break
        if r.get("reportingType") != "Ceased" or e.get("parent_incident_id") or e.get("detail_tried"):
            continue
        if re.sub(r"-\d+$", "", str(r.get("incidentNumber") or "")) in numbers:
            continue
        e["detail_tried"] = stamp_now
        try:
            d = fetch_detail(sess, r["incidentId"]); budget -= 1
            e["detail"] = detail_extra(d)
            pid = e["detail"].get("parentIncidentId")
            if pid:
                e["parent_incident_id"] = pid
                if pid not in rows and budget > 0:
                    pd = fetch_detail(sess, pid); budget -= 1
                    prow = detail_to_row(pd)
                    if prow.get("incidentId"):
                        rows[pid] = {"row": prow, "fetched_at": stamp_now, "first_seen_at": stamp_now,
                                     "via": "detail", "detail": detail_extra(pd)}
            time.sleep(0.5)
        except Exception as ex:  # noqa: BLE001
            e["detail_error"] = f"{type(ex).__name__}: {ex}"

    write_json(ROWS_PATH, {"source_id": SOURCE_ID, "updated_at": stamp_now, "count": len(rows), "rows": rows})

    sess_layer = requests.Session()
    sess_layer.headers.update(HEADERS)
    layer, layer_info = load_cso_layer(sess_layer)
    ctx = {"layer": layer, "echo": load_echo(), "crosswalk": load_crosswalk(), "waters": load_waters(),
           "dischargers": load_dischargers()}

    records, no_events = [], []
    for key, e in rows.items():
        r = e["row"]
        if (r.get("reporterClass") or "").strip() == "No Events for the month":
            no_events.append({"incidentId": r.get("incidentId"), "incidentNumber": r.get("incidentNumber"),
                              "permittee": r.get("permiteeName"), "npdes_permit": r.get("permiteeId"),
                              "month": r.get("month"), "year": r.get("year"),
                              "submitted": iso(local_dt(r.get("submittedDate"))),
                              "source_url": DETAILS_URL.format(r.get("incidentId"))})
            continue
        rec = normalise(e, ctx)
        if e.get("missing_since"):
            rec["raw"]["_missing_from_source_since"] = e["missing_since"]
        records.append(rec)
    link_stats = link(records, rows)
    records.sort(key=lambda r: (r["published_at"] or "", r["event_id"]), reverse=True)

    summary = summarise(records)
    meta = {
        "mode": "backfill" if args.backfill else f"since {args.since} days",
        "api": API, "portal": PORTAL, "fetch": info, "fetched_rows_this_run": len(fetched),
        "rows_held": len(rows), "cso_layer": layer_info, "links": link_stats, "summary": summary,
        "no_event_reports": sorted(no_events, key=lambda x: x["submitted"] or "", reverse=True),
        "credit": "MassDEP Sewage Notification Data System, via the EEA Data Portal",
        "disclaimer": ("EEA Data Portal: data not fully verified for accuracy and/or completeness; "
                       "should not be relied upon to determine overall compliance."),
        "time_note": "portal times have no zone; read as America/New_York",
    }
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(json.dumps({"written": str(path), "records": len(records), "no_event_reports": len(no_events),
                      "links": link_stats, **summary}, indent=1))
    return 0


def summarise(records: list[dict]) -> dict:
    by = Counter((r["event_type"], r["status"]) for r in records)
    cities = {}
    for label, pat in (("Springfield", "SPRINGFIELD WATER"), ("Holyoke", "HOLYOKE"), ("Chicopee", "CHICOPEE")):
        rs = [r for r in records if pat in (r["discharger_name"] or "").upper()]
        cities[label] = {"records": len(rs),
                         "by_class": dict(Counter(r["raw"].get("_report_class") for r in rs)),
                         "by_status": dict(Counter(r["status"] for r in rs)),
                         "with_coords": sum(r["lat"] is not None for r in rs),
                         "with_slug": sum(bool(r["water_slugs"]) for r in rs)}
    return {
        "by_type": dict(Counter(r["event_type"] for r in records)),
        "by_status": dict(Counter(r["status"] for r in records)),
        "by_type_status": {f"{t}/{s}": n for (t, s), n in sorted(by.items())},
        "by_class": dict(Counter(r["raw"].get("_report_class") for r in records)),
        "with_coords": sum(r["lat"] is not None for r in records),
        "coord_source": dict(Counter(r["coord_source"] for r in records)),
        "with_slug": sum(bool(r["water_slugs"]) for r in records),
        "water_match": dict(Counter(r["water_match"] for r in records)),
        "with_ended_at": sum(bool(r["ended_at"]) for r in records),
        "parse_errors": sum(bool(r["parse_error"]) for r in records),
        "ongoing_older_than_7d": sum(
            r["status"] == "ongoing" and r["started_at"] is not None
            and datetime.fromisoformat(r["started_at"]) < datetime.now(TZ) - timedelta(days=7) for r in records),
        "cities": cities,
    }


if __name__ == "__main__":
    sys.exit(main())
