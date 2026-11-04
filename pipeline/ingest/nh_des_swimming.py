"""NHDES Healthy Swimming Mapper -> data/build/events/nh-des-swimming.json.

Source: ArcGIS feature service "2026 NHDES Healthy Swimming Mapper" (item 25c31a6d07134c5689c3a5a7b97606fd,
service name 2024_Healthy_Swimming_Mapper_V2_WFL1, owner CyanoHAB_NHDES), public, no token:
https://services1.arcgis.com/MAcUimSes4gPY4sM/arcgis/rest/services/2024_Healthy_Swimming_Mapper_V2_WFL1/FeatureServer

- Layer 0 "Beach Mapper Points": 93 designated beaches (16 on the Atlantic coast). Status is
  "Advisory" / "No advisory" / "Monitoring Season Completed"; DateIssued (advisory issue date),
  SampleDate, Sample_Results, Advisory_history (this season's advisory ranges as "7/3-7/5,
  8/4-8/6", month/day only). Fecal-bacteria advisories under Env-Wq 1108.14, posted about 24 h
  after sampling; "NHDES does not close waterbodies", so every record is beach_advisory.
  Records: the current state per beach, one record per distinct state (id = EPA_ID + status +
  date), chained per beach with parent_event_id and closed by the next state like the VT
  advisories; plus one advisory_lifted record per Advisory_history range (year = the season of
  SampleDate, day precision, ended_at = the last day of the range at 00:00 local). Earlier
  states and past seasons' ranges are kept across runs (records are replaced by id only).
- Layer 9 "CyanobacteriaMapperLayer2": 2,401 waterbody polygons, nearly all "No bloom reported"
  with no dates. Only polygons with a report (a sampling or status date, a bloom status other than
  "no bloom reported", or a LatestAdvisory other than "No Warnings issued") become hab_advisory
  records. The status fields can disagree (Angle Pond: Bloom_status "Warning", LatestAdvisory "No
  Warnings issued"): a warning in LatestAdvisory -> advisory_active; no bloom and no warning ->
  advisory_lifted; anything else -> unknown with a parse_error so the review queue sees it.
  Coordinates = the polygon's vertex mean (approximate centre).

Waters: by name within NH; with the point, a name only matches a water whose bounding box
(data/waters-nh.json, padded ~2 km) holds the point, which settles shared names (Echo Lake,
Crystal Lake ...). "Atlantic Ocean" beaches have no water record (water_match none).

LICENCE: item licenseInfo ends "These data are to be used for screening purposes only.
Distribution is discouraged." The full text is copied into the events file meta (meta.licence,
meta.distribution_discouraged = true) so export/build.py can withhold these records until the
owner decides (research/nh-vt/report.md §5.4); attribution: copyrightText of the layers.

Cadence: the item says advisories are "posted & updated on this map daily" in season (about June
to Labor Day for beaches; HAB reports through the fall). Poll every 1-3 hours in season, daily
off season.

Run from pipeline/: python -m ingest.nh_des_swimming
"""
from __future__ import annotations

import re
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest.nh_vt_waters import match_waters

SOURCE_ID = "nh-des-swimming"
TZ = ZoneInfo("America/New_York")
SERVICE = "https://services1.arcgis.com/MAcUimSes4gPY4sM/arcgis/rest/services/2024_Healthy_Swimming_Mapper_V2_WFL1/FeatureServer"
ITEM = "https://www.arcgis.com/sharing/rest/content/items/25c31a6d07134c5689c3a5a7b97606fd"
PAGE = "https://www.des.nh.gov/water/healthy-swimming"
MAPPER = "https://nhdes.maps.arcgis.com/apps/dashboards/8d84a6b03acb4efaab571b222c78447b"
LICENCE_FALLBACK = (
    "User is required to read metadata completely before using the data. The information provided in this coverage "
    "is a subset of spatial databases developed by the New Hampshire Department of Environmental Services (NHDES). "
    "The data presented is under constant revision and may not depict the most up to date information. The NHDES is "
    "not responsible for the use or interpretation of this information, or for any inaccuracies in the site names, "
    "tax map and lot information, or locations. All information is subject to verification. These data are to be "
    "used for screening purposes only. Distribution is discouraged.")
BEACH_ADVICE = ("NHDES Healthy Swimming Mapper: if bacteria levels exceed the recreational threshold, an advisory is "
                "issued for the beach (Env-Wq 1108.14); NHDES does not close waterbodies.")
HAB_ADVICE = ("NHDES Healthy Swimming Mapper: waterbodies may be listed as warnings or watches depending on the "
              "severity of the cyanobacteria bloom.")
AUTH_BEACH = "NHDES Beach Inspection Program (Healthy Swimming Mapper)"
AUTH_HAB = "NHDES Harmful Algal Bloom Program (Healthy Swimming Mapper)"


def _query_all(sess, layer: int, tag: str, geometry: bool = True, where: str = "1=1") -> list[dict]:
    feats, offset = [], 0
    while True:
        r = sess.get(f"{SERVICE}/{layer}/query", timeout=90, params={
            "where": where, "outFields": "*", "returnGeometry": "true" if geometry else "false", "outSR": "4326",
            "geometryPrecision": 5, "maxAllowableOffset": 0.0005, "f": "json",
            "resultOffset": offset, "resultRecordCount": 2000})
        r.raise_for_status()
        save_raw(SOURCE_ID, r.content, f"{tag}.{offset}.json")
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"layer {layer}: {d['error']}")
        page = d.get("features", [])
        feats += page
        if not d.get("exceededTransferLimit") or not page:
            return feats
        offset += len(page)


def _licence(sess) -> tuple[str, str | None]:
    try:
        d = sess.get(ITEM, params={"f": "json"}, timeout=30).json()
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d.get("licenseInfo") or "")).strip()
        return (txt or LICENCE_FALLBACK), d.get("accessInformation")
    except Exception:
        return LICENCE_FALLBACK, None


def _layer_info(sess, layer: int) -> dict:
    try:
        return sess.get(f"{SERVICE}/{layer}", params={"f": "json"}, timeout=30).json()
    except Exception:
        return {}


def _ms(ms) -> datetime | None:
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(TZ) if ms not in (None, "") else None


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _day(d: date) -> str:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat()


def _point(g: dict) -> tuple[float | None, float | None]:
    if not g:
        return None, None
    if "x" in g:
        return g["x"], g["y"]
    pts = g.get("points") or [p for ring in g.get("rings", []) for p in ring]
    if not pts:
        return None, None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


# --------------------------------------------------------------------------- beaches (layer 0)

def beach_records(feats: list[dict], fetched_at: str, updated: str | None) -> list[dict]:
    out = []
    for f in feats:
        a = f.get("attributes", {})
        lon, lat = _point(f.get("geometry"))
        if lon is None and a.get("Long") is not None:
            lon, lat = a["Long"], a["Lat"]
        epa = (a.get("EPA_ID") or "").strip() or f"oid{a.get('OBJECTID')}"
        water = (a.get("Waterbody_Name") or "").strip() or None
        slugs, notes = match_waters(water, "nh", None, (lon, lat) if lon is not None else None)
        status_txt = (a.get("Status") or "").strip()
        issued, sampled = _ms(a.get("DateIssued")), _ms(a.get("SampleDate"))
        low = status_txt.lower()
        if low == "advisory":
            st = "advisory_active"
        elif low in ("no advisory", "monitoring season completed"):
            st = "advisory_lifted"
        else:
            st = "unknown"
        when = issued if st == "advisory_active" and issued else sampled
        common = dict(source_id=SOURCE_ID, event_type="beach_advisory", outfall_name=a.get("Beach_Name"),
                      waterbody_text=water, water_slugs=slugs, water_match="name" if slugs else "none",
                      lat=lat, lon=lon, coord_source="source" if lon is not None else None,
                      source_updated_at=updated, fetched_at=fetched_at, material="fecal indicator bacteria",
                      authority=AUTH_BEACH, advice_text=BEACH_ADVICE, source_url=MAPPER)
        key = f"beach:{epa}"
        raw = {**a, "EPA_ID": epa, "_layer": "Beach Mapper Points (0)", "_site_key": key, "_match_notes": notes or None,
               "_was_active": st == "advisory_active"}
        out.append(event(**common, source_record_id=f"{key}:{re.sub(r'[^a-z]+', '-', low).strip('-') or 'none'}:"
                                                    f"{(when.date().isoformat() if when else 'nodate')}",
                         status=st, started_at=_iso(issued) if st == "advisory_active" else None,
                         time_precision="minute" if when else None, reported_at=_iso(when), raw=raw,
                         parse_error=None if st != "unknown" else f"unrecognised Status {status_txt!r}"))
        # this season's past advisories
        hist = a.get("Advisory_history") or ""
        season = (sampled or issued)
        for part in re.split(r"[,;]", hist):
            m = re.match(r"\s*(\d{1,2})/(\d{1,2})\s*(?:-\s*(?:(\d{1,2})/)?(\d{1,2}))?\s*$", part)
            if not part.strip():
                continue
            if not m or not season:
                out.append(event(**common, source_record_id=f"{key}:hist:unparsed:{part.strip()}", status="unknown",
                                 raw={"Advisory_history": hist, "EPA_ID": epa, "_site_key": key + ":hist"},
                                 parse_error=f"advisory history range not parsed: {part.strip()!r}"
                                             + ("" if season else " (no sample date to give the year)")))
                continue
            y = season.year
            try:
                s = date(y, int(m.group(1)), int(m.group(2)))
                e = date(y, int(m.group(3) or m.group(1)), int(m.group(4))) if m.group(4) else s
            except ValueError as ex:
                out.append(event(**common, source_record_id=f"{key}:hist:unparsed:{part.strip()}", status="unknown",
                                 raw={"Advisory_history": hist, "EPA_ID": epa, "_site_key": key + ":hist"},
                                 parse_error=f"advisory history range not a date: {part.strip()!r} ({ex})"))
                continue
            out.append(event(**common, source_record_id=f"{key}:hist:{s.isoformat()}", status="advisory_lifted",
                             started_at=_day(s), ended_at=_day(e), time_precision="day",
                             raw={"Advisory_history": hist, "range": part.strip(), "EPA_ID": epa,
                                  "Beach_Name": a.get("Beach_Name"), "season_from": "SampleDate year",
                                  "_site_key": key + ":hist"}))
    return out


# --------------------------------------------------------------------------- cyanobacteria (layer 9)

def _reported(a: dict) -> bool:
    bloom = (a.get("Bloom_status") or "").strip().lower()
    adv = (a.get("LatestAdvisory") or "").strip().lower()
    return bool(bloom not in ("", "no bloom reported") or adv not in ("", "no warnings issued")
                or a.get("SamplingDate") or a.get("StatusDate"))


def fetch_hab(sess) -> list[dict]:
    """Attributes for all 2,401 polygons (no geometry: ~11 MB with it), then geometry only for the
    polygons that carry a report."""
    attrs = _query_all(sess, 9, "cyano-attrs", geometry=False)
    oids = [str(f["attributes"]["OBJECTID"]) for f in attrs if _reported(f.get("attributes", {}))]
    if not oids:
        return []
    out = []
    for i in range(0, len(oids), 200):
        out += _query_all(sess, 9, "cyano-reported", geometry=True, where=f"OBJECTID IN ({','.join(oids[i:i + 200])})")
    return out

def hab_records(feats: list[dict], fetched_at: str, updated: str | None) -> list[dict]:
    out = []
    for f in feats:
        a = f.get("attributes", {})
        bloom = (a.get("Bloom_status") or "").strip()
        adv = (a.get("LatestAdvisory") or "").strip()
        sampled, issued = _ms(a.get("SamplingDate")), _ms(a.get("StatusDate"))
        no_bloom = bloom.lower() in ("", "no bloom reported")
        no_warn = adv.lower() in ("", "no warnings issued")
        if not _reported(a):
            continue   # never reported: not an event
        perr = None
        if re.search(r"warning|watch|advisory", adv, re.I) and not no_warn:
            st = "advisory_active"
        elif no_bloom and no_warn:
            st = "advisory_lifted"
        else:
            st = "unknown"
            perr = f"status fields disagree or are unrecognised: Bloom_status={bloom!r}, LatestAdvisory={adv!r}, Status={a.get('Status')!r}"
        lon, lat = _point(f.get("geometry"))
        wb = (a.get("WB_NAME") or "").strip() or None
        slugs, notes = match_waters(wb, "nh", [a.get("Town")], (lon, lat) if lon is not None else None)
        wbid = a.get("WB_ID") or f"oid{a.get('OBJECTID')}"
        when = issued or sampled
        key = f"cyano:{wbid}"
        raw = {k: v for k, v in a.items() if k not in ("Shape__Area", "Shape__Length")}
        raw.update({"_layer": "CyanobacteriaMapperLayer2 (9)", "_site_key": key, "_match_notes": notes or None,
                    "_was_active": st == "advisory_active"})
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"{key}:{when.date().isoformat() if when else 'nodate'}",
            event_type="hab_advisory", status=st, waterbody_text=wb, water_slugs=slugs,
            water_match="name" if slugs else "none", lat=lat, lon=lon, coord_source="source" if lon is not None else None,
            started_at=_iso(issued or sampled) if st == "advisory_active" else None,
            time_precision="minute" if when else None, reported_at=_iso(when), source_updated_at=updated,
            fetched_at=fetched_at, material="cyanobacteria", authority=AUTH_HAB, advice_text=HAB_ADVICE,
            source_url=a.get("CyanoHistory") or MAPPER, raw=raw, parse_error=perr))
    return out


# --------------------------------------------------------------------------- history

def chain(records: list[dict]) -> None:
    """Per site, oldest first: parent_event_id -> previous state; a replaced state is closed."""
    by: dict[str, list[dict]] = {}
    for r in records:
        k = (r.get("raw") or {}).get("_site_key")
        if k and not k.endswith(":hist"):
            by.setdefault(k, []).append(r)
    for reps in by.values():
        reps.sort(key=lambda r: (r.get("reported_at") or "", r["event_id"]))
        for i, r in enumerate(reps):
            if r["raw"].get("_was_active"):
                r["status"], r["ended_at"] = "advisory_active", None
            r["parent_event_id"] = reps[i - 1]["event_id"] if i else None
            if i + 1 < len(reps):
                nxt = reps[i + 1].get("reported_at")
                if r["status"] == "advisory_active" and nxt:
                    r["ended_at"] = nxt
                if r["status"] in ("advisory_active", "advisory_lifted"):
                    r["status"] = "advisory_lifted"
    # a season-history range that starts on an advisory's issue date continues that advisory
    issued = {(r["raw"].get("_site_key"), (r.get("started_at") or "")[:10]): r for r in records
              if r["raw"].get("_was_active") and r.get("started_at")}
    for r in records:
        k = (r.get("raw") or {}).get("_site_key", "")
        if k.endswith(":hist") and r.get("started_at"):
            snap = issued.get((k[:-5], r["started_at"][:10]))
            if snap:
                r["parent_event_id"] = snap["event_id"]


def main(argv=None) -> int:
    fetched_at = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    licence, access = _licence(sess)
    new, errors, meta = [], [], {}
    for layer, tag, fn in ((0, "beaches", beach_records), (9, "cyano", hab_records)):
        try:
            info = _layer_info(sess, layer)
            ms = (info.get("editingInfo") or {}).get("dataLastEditDate")
            updated = datetime.fromtimestamp(ms / 1000, UTC).isoformat().replace("+00:00", "Z") if ms else None
            feats = _query_all(sess, layer, tag) if layer == 0 else fetch_hab(sess)
            recs = fn(feats, fetched_at, updated)
            new += recs
            meta[f"{tag}_features"] = len(feats) if layer == 0 else f"{len(feats)} reported of the layer's polygons"
            meta[f"{tag}_records"], meta[f"{tag}_data_last_edit"] = len(recs), updated
            meta.setdefault("attribution", info.get("copyrightText"))
        except Exception as e:
            errors.append(f"{tag}: {type(e).__name__}: {e}")
    meta.update({
        "service": SERVICE, "item": ITEM,
        "licence": licence, "licence_access_information": access,
        "distribution_discouraged": "distribution is discouraged" in licence.lower(),
        "export_gate": "Owner decision pending on republishing ('Distribution is discouraged'); export should "
                       "withhold or link-only these records until docs/decisions.md records a ruling.",
        "errors": errors or None,
    })
    if not new and errors:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(errors), meta=meta)
        print(f"{SOURCE_ID}: failed: {errors}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    ids = {r["event_id"] for r in new}
    kept = [r for r in prev if r["event_id"] not in ids]   # earlier states and past seasons stay
    records = kept + new
    chain(records)
    records.sort(key=lambda r: r.get("reported_at") or r.get("started_at") or "", reverse=True)
    path = write_events(SOURCE_ID, records, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"{SOURCE_ID}: {meta.get('beaches_records')} beach + {meta.get('cyano_records')} HAB records fetched, "
          f"{len(records)} in file -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
