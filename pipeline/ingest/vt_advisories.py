"""Vermont advisories -> data/build/events/vt-advisories.json.

Two open ArcGIS layers, snapshotted (both hold only the latest report per site):

1. Vermont Department of Health, Cyanobacteria Tracker, "Cyanobacteria_Current_Approved_Reports_View"
   https://services.arcgis.com/YKJ5JtnaPQ2jDbX8/arcgis/rest/services/Cyanobacteria_Current_Approved_Reports_View/FeatureServer/0
   About 126 sites (Lake Champlain and inland lakes, a few NY shore sites): ReportDate, Waterbody,
   Municipality, SiteName, StatusWeb ("Generally Safe" / "Low Alert" / "High Alert"), point.
   Weekly observations by trained volunteers and staff, early June to early October, reviewed
   before posting ("Approved"). No licence stated. Record per report (GlobalID):
   Low/High Alert -> hab_advisory advisory_active; Generally Safe -> hab_advisory advisory_lifted.
   raw.StatusWeb keeps the level: Low Alert is "some cyanobacteria ... in a contained area, but
   no widespread bloom"; status.py may want it as caution rather than red.
2. City of Burlington, BTV_Beach_Status (Beach Closure Tracker)
   https://maps.burlingtonvt.gov/arcgis/rest/services/BTV_Beach_Status/MapServer/0
   12 Lake Champlain beach points; ResultDateTime ("MM/DD/YYYY hh:mm AM", local), EColi,
   CyanobacteriaDescription (the overall status: Open / Alert / Closed), StatusReason (Safe,
   Combined Sewer Outflow, E. coli, cyanobacteria ...). City legend: Alert = cyanobacteria in low
   levels, children and pets advised to avoid the water; Closed = swimming area closed due to
   cyanobacteria blooms, combined sewer outflow or high E. coli. Live Memorial Day to Labor Day.
   Closed -> beach_closure advisory_active; Alert -> hab_advisory advisory_active (or
   beach_advisory if the reason is not cyanobacteria); Open -> beach_closure advisory_lifted.
   The layer has no waterbody field: every site is on Lake Champlain (water_match inferred).

History: each run keeps earlier reports (records are per report id) and chains reports of the
same site with parent_event_id (newest -> previous). A report that a newer one has replaced gets
ended_at = the newer report's time and status advisory_lifted, so every report is an interval
and the newest report per site carries the current state. Times are America/New_York.
started_at is set only on alert reports: for the cyanobacteria tracker it is the first report of
the unbroken run of Low/High Alert reports at that site. Cyanobacteria source_updated_at is the
report's own ReportDate (so an alert nobody re-checks ages out in status.py); the layer's
last-edit time is kept in raw._layer_data_last_edit.

Cadence: poll hourly (both layers change at most daily in season; nothing changes off season).
Waters: the cyanobacteria Waterbody by name within VT, accepted only when the site point lies in
the water's padded bounding box (data/waters-vt.json); New York shore sites on Lake Champlain
land on lake-champlain-vt (the only Lake Champlain record).

Run from pipeline/: python -m ingest.vt_advisories
"""
from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest.nh_vt_waters import match_waters, norm

SOURCE_ID = "vt-advisories"
TZ = ZoneInfo("America/New_York")
CYANO = "https://services.arcgis.com/YKJ5JtnaPQ2jDbX8/arcgis/rest/services/Cyanobacteria_Current_Approved_Reports_View/FeatureServer/0"
CYANO_PAGE = "https://www.healthvermont.gov/environment/tracking/cyanobacteria-blue-green-algae-tracker"
BTV = "https://maps.burlingtonvt.gov/arcgis/rest/services/BTV_Beach_Status/MapServer/0"
BTV_PAGE = "https://www.burlingtonvt.gov/1219/Beach-Closure-Tracker"
CYANO_ADVICE = {
    "High Alert": "Vermont Department of Health tracker legend: High Alert means a lot of cyanobacteria were "
                  "observed collecting into a dense bloom that extends at least 10-15 feet offshore.",
    "Low Alert": "Vermont Department of Health tracker legend: Low Alert means that some cyanobacteria were "
                 "observed collecting in a contained area, but no widespread bloom conditions were observed.",
    "Generally Safe": "Vermont Department of Health tracker legend: Generally Safe means no blooms were observed, "
                      "but there may have been tiny specks of cyanobacteria observed in the water. "
                      "Conditions can and do change.",
}
BTV_ADVICE = {
    "Alert": "City of Burlington: Alert = cyanobacteria is present in low levels. Vulnerable groups - children "
             "and pets - are advised to avoid the water due to possible ingestion.",
    "Closed": "City of Burlington: Closed = swimming area closed due to cyanobacteria blooms, combined sewer "
              "outflow, or high E. coli levels.",
    "Open": None,
}


def _query_all(sess: requests.Session, layer: str, tag: str) -> list[dict]:
    feats, offset = [], 0
    while True:
        params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326",
                  "f": "json", "resultOffset": offset, "resultRecordCount": 1000}
        r = sess.get(layer + "/query", params=params, timeout=60)
        r.raise_for_status()
        save_raw(SOURCE_ID, r.content, f"{tag}.{offset}.json")
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"{tag}: {d['error']}")
        page = d.get("features", [])
        feats.extend(page)
        if not d.get("exceededTransferLimit") or not page:
            return feats
        offset += len(page)


def _layer_edit(sess: requests.Session, layer: str) -> str | None:
    try:
        d = sess.get(layer, params={"f": "json"}, timeout=30).json()
        ms = (d.get("editingInfo") or {}).get("dataLastEditDate") or (d.get("editingInfo") or {}).get("lastEditDate")
        return datetime.fromtimestamp(ms / 1000, UTC).isoformat().replace("+00:00", "Z") if ms else None
    except Exception:
        return None


def _iso_ms(ms) -> str | None:
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(TZ).isoformat()


def cyano_records(feats: list[dict], fetched_at: str, updated: str | None) -> list[dict]:
    out = []
    for f in feats:
        a, g = f.get("attributes", {}), f.get("geometry") or {}
        level = (a.get("StatusWeb") or "").strip()
        rid = a.get("GlobalID") or a.get("OBJECTID")
        active = level in ("Low Alert", "High Alert")
        rep = _iso_ms(a.get("ReportDate"))
        pt = (g["x"], g["y"]) if g.get("x") is not None else None
        slugs, notes = match_waters(a.get("Waterbody"), "vt", [a.get("Municipality")], pt)
        perr = None if level in CYANO_ADVICE else f"unrecognised StatusWeb {level!r}"
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"cyano:{rid}",
            event_type="hab_advisory",
            status="advisory_active" if active else ("advisory_lifted" if level == "Generally Safe" else "unknown"),
            outfall_name=None, waterbody_text=a.get("Waterbody"), water_slugs=slugs,
            water_match="name" if slugs else "none",
            lat=g.get("y"), lon=g.get("x"), coord_source="source" if g else None,
            started_at=rep if active else None, time_precision="minute" if rep else None,
            reported_at=rep, source_updated_at=rep, fetched_at=fetched_at,
            material="cyanobacteria (visual observation)",
            authority="Vermont Department of Health (Cyanobacteria Tracker; volunteer and staff observations)",
            advice_text=CYANO_ADVICE.get(level), source_url=CYANO_PAGE,
            raw={**a, "_layer": "Cyanobacteria_Current_Approved_Reports_View", "_site_key": _site("cyano", a),
                 "_match_notes": notes or None, "_layer_data_last_edit": updated},
            parse_error=perr,
        ))
    return out


def _btv_time(s: str | None) -> str | None:
    try:
        return datetime.strptime((s or "").strip(), "%m/%d/%Y %I:%M %p").replace(tzinfo=TZ).isoformat()
    except ValueError:
        return None


def btv_records(feats: list[dict], fetched_at: str) -> list[dict]:
    out = []
    lake, _ = match_waters("Lake Champlain", "vt", ["Burlington"])
    for f in feats:
        a, g = f.get("attributes", {}), f.get("geometry") or {}
        status = (a.get("CyanobacteriaDescription") or "").strip()
        reason = (a.get("StatusReason") or "").strip()
        cyan = bool(re.search(r"cyano|bloom|algae", reason, re.I))
        if status == "Closed":
            etype, st = "beach_closure", "advisory_active"
        elif status == "Alert":
            etype, st = ("hab_advisory" if cyan or not reason or reason.lower() == "safe" else "beach_advisory"), "advisory_active"
        elif status == "Open":
            etype, st = "beach_closure", "advisory_lifted"
        else:
            etype, st = "unknown", "unknown"
        rep = _btv_time(a.get("ResultDateTime"))
        active = st == "advisory_active"
        material = None
        if active and reason and reason.lower() != "safe":
            material = "sewage (combined sewer overflow)" if re.search(r"sewer|cso", reason, re.I) else reason
        out.append(event(
            source_id=SOURCE_ID, source_record_id=f"btv:{a.get('LocationId')}:{a.get('ResultId')}",
            event_type=etype, status=st,
            outfall_name=None, waterbody_text="Lake Champlain", water_slugs=lake, water_match="inferred",
            lat=g.get("y"), lon=g.get("x"), coord_source="source" if g else None,
            started_at=rep if active else None, time_precision="minute" if rep else None,
            reported_at=rep, fetched_at=fetched_at, material=material,
            authority="City of Burlington Parks, Recreation & Waterfront (Beach Closure Tracker)",
            advice_text=BTV_ADVICE.get(status), source_url=BTV_PAGE,
            raw={**a, "_layer": "BTV_Beach_Status", "_site_key": _site("btv", a)},
            parse_error=None if rep else f"ResultDateTime not parsed: {a.get('ResultDateTime')!r}",
        ))
    return out


def _site(kind: str, a: dict) -> str:
    if kind == "btv":
        return f"btv:{a.get('LocationId')}"
    return "cyano:" + norm(f"{a.get('Waterbody')} {a.get('Municipality')} {a.get('SiteName')}").replace(" ", "-")


def chain(records: list[dict]) -> list[dict]:
    """Per site, newest report last: link parent_event_id to the previous report and close
    superseded reports (ended_at = next report time, status advisory_lifted). Cyanobacteria
    reports also get source_updated_at = their own ReportDate (the latest report in the site's
    chain when a report has none) and, when they are alerts, started_at = the first report of the
    unbroken run of Low/High Alert reports they belong to."""
    by_site: dict[str, list[dict]] = {}
    for r in records:
        by_site.setdefault(r["raw"].get("_site_key") or r["event_id"], []).append(r)
    for key, reps in by_site.items():
        reps.sort(key=lambda r: (r.get("reported_at") or "", r["event_id"]))
        if key.startswith("cyano:"):
            latest = max((r.get("reported_at") for r in reps if r.get("reported_at")), default=None)
            run_start = None
            for r in reps:
                r["source_updated_at"] = r.get("reported_at") or latest
                if r["raw"].get("StatusWeb") in ("Low Alert", "High Alert"):
                    run_start = run_start or r.get("reported_at")
                    r["started_at"] = run_start
                else:
                    run_start = None
                    r["started_at"] = None
        for i, r in enumerate(reps):
            r["parent_event_id"] = reps[i - 1]["event_id"] if i else None
            if i + 1 < len(reps) and r["status"] in ("advisory_active", "advisory_lifted"):
                nxt = reps[i + 1].get("reported_at")
                if r["status"] == "advisory_active" and nxt:
                    r["ended_at"] = nxt
                r["status"] = "advisory_lifted"
    return records


def main(argv=None) -> int:
    fetched_at = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    errors, new = [], []
    meta = {"layers": {"cyano": CYANO, "btv": BTV},
            "notes": "Low Alert and High Alert are both advisory_active; raw.StatusWeb keeps the level. "
                     "A report replaced by a newer one is closed (ended_at = newer report time). Cyanobacteria "
                     "source_updated_at = the report's ReportDate; started_at = first report of the run of alert "
                     "reports; the layer's last-edit time is in raw._layer_data_last_edit and meta.cyano_data_last_edit."}
    try:
        updated = _layer_edit(sess, CYANO)
        feats = _query_all(sess, CYANO, "cyano")
        new += cyano_records(feats, fetched_at, updated)
        meta["cyano_count"], meta["cyano_data_last_edit"] = len(feats), updated
    except Exception as e:
        errors.append(f"cyano: {type(e).__name__}: {e}")
    try:
        feats = _query_all(sess, BTV, "btv")
        new += btv_records(feats, fetched_at)
        meta["btv_count"] = len(feats)
    except Exception as e:
        errors.append(f"btv: {type(e).__name__}: {e}")
    if not new and errors:
        write_events(SOURCE_ID, [], ok=False, error="; ".join(errors))
        print(f"{SOURCE_ID}: failed: {errors}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    failed_layers = {e.split(":")[0] for e in errors}
    ids = {r["event_id"] for r in new}
    kept = [r for r in prev if r["event_id"] not in ids]
    for r in kept:   # reset derived fields; chain() recomputes them
        if r["raw"].get("_layer") == "Cyanobacteria_Current_Approved_Reports_View" and "_layer_data_last_edit" not in r["raw"]:
            r["raw"]["_layer_data_last_edit"] = r.get("source_updated_at")   # older runs stored the layer time there
        if r["status"] == "advisory_lifted" and r["raw"].get("_was_active"):
            r["status"] = "advisory_active"
            r["ended_at"] = None
    for r in new:
        r["raw"]["_was_active"] = r["status"] == "advisory_active"
    records = chain(kept + new)
    records.sort(key=lambda r: r.get("reported_at") or "", reverse=True)
    meta["errors"] = errors or None
    meta["partial"] = sorted(failed_layers) or None
    path = write_events(SOURCE_ID, records, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"{SOURCE_ID}: {len(new)} fetched, {len(records)} in file -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
