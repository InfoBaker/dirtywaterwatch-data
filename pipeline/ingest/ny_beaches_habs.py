"""New York State Park beaches and DEC harmful algal bloom reports
-> data/build/events/ny-parks-beaches.json and data/build/events/ny-dec-habs.json

Sources
  1. Open Data NY "Beach Water Testing: Beginning 2015" (wwwd-za77, NYS OPRHP): one row per State
     Park beach sample with beach_status (Open, Closed, Open with Advisory, Reopened, Off - Season)
     and status_reason (Exceedance, Preemptive: rainfall, Preemptive: sewage overflow, Predicted
     exceedance (model), Harmful Algal Bloom ...). Posted once a year after the season (2015 to
     2025-10-27 on 2026-11-02). SODA https://data.ny.gov/resource/wwwd-za77.json, no key.
  2. NYS Parks live beach status layer behind https://parks.ny.gov/activities/swimming/
     water-quality-beach-results (ArcGIS 2025_Beach_Status_view, 73 beaches with coordinates,
     Beach_status, Status_Reason, Date_sampled "08-Sep-26", Results, Indicator_). Off-season now.
  3. DEC NYHABS current reports (ArcGIS Current_HAB_Reports_DIL: date_time, STATUS_DATE, county,
     data_provider, water_name, extent_bloom, HAB_STATUS, Weblink, point). The public map is
     https://on.ny.gov/nyhabs. No layer is literally "Current_HAB_Reports".

Beach records (ny-parks-beaches)
  - Closures and advisories for water quality only: reasons Exceedance, Preemptive: rainfall /
    sewage overflow / turbidity, Predicted exceedance (model), "No model: previous day's E.coli",
    Harmful Algal Bloom, Blue-green algae. Closures for the season, preseason, lifeguards, weather,
    waves, cold water, lab error, "Other" or no reason are not events (counted in meta).
  - wwwd-za77 rows of one beach and waterbody are read in date order; consecutive dates with a
    qualifying status form one episode: beach_closure (any Closed), beach_advisory (Open with
    Advisory only) or hab_advisory (an algae reason). started_at = the first such sample date;
    ended_at = the date of the next row with another status (raw._ended_at_basis names it);
    status advisory_lifted, or unknown when the dataset has no later row for the beach. Dates are
    day precision (sample dates; the page says the public is told 18-24 hours after sampling).
  - The live layer adds episodes for the current season: a beach shown Closed / Open with Advisory
    for a qualifying reason is advisory_active from its Date_sampled; when a later poll shows
    another status the episode is lifted at that row's Date_sampled (state in
    data/build/ny-parks-beaches-state.json). A live episode the annual dataset later holds (same
    beach, same start date) gets duplicate_of the dataset record.
  - Coordinates from the live layer, joined by beach name; water slugs by the waterbody name
    within New York, checked against that point (ingest/ny_waters.py).
  - The layer's Creator / Editor fields (staff emails) are dropped before anything is saved.

HAB records (ny-dec-habs)
  - One hab_advisory per current report, advisory_active, event id = the report's globalid;
    started_at = date_time, source_updated_at = STATUS_DATE; advice_text = the Weblink text.
  - The layer only lists current reports: a report seen before and missing now becomes
    advisory_lifted with ended_at = the first poll without it, an upper bound
    (raw._ended_at_basis); state in data/build/ny-dec-habs-state.json.

Run (from pipeline/): python -m ingest.ny_beaches_habs
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest import ny_waters

BEACH_SOURCE = "ny-parks-beaches"
HAB_SOURCE = "ny-dec-habs"
SODA = "https://data.ny.gov/resource/wwwd-za77.json"
DATASET_PAGE = "https://data.ny.gov/d/wwwd-za77"
BEACH_LAYER = "https://services.arcgis.com/1xFZPtKn1wKC6POA/arcgis/rest/services/2025_Beach_Status_view/FeatureServer/0"
BEACH_PAGE = "https://parks.ny.gov/activities/swimming/water-quality-beach-results"
HAB_LAYER = "https://services6.arcgis.com/DZHaqZm9cxOD4CWM/arcgis/rest/services/Current_HAB_Reports_DIL/FeatureServer/0"
HAB_PAGE = "https://on.ny.gov/nyhabs"
BEACH_STATE = BUILD_DIR / "ny-parks-beaches-state.json"
HAB_STATE = BUILD_DIR / "ny-dec-habs-state.json"
TZ = ZoneInfo("America/New_York")
BEACH_AUTHORITY = "NYS Office of Parks, Recreation and Historic Preservation (State Park beaches)"
HAB_AUTHORITY = "NYS DEC Harmful Algal Blooms Program (NYHABS)"

QUALIFY = re.compile(r"exceedance|preemptive|predicted exceedance|previous day.s e\.?coli|harmful algal bloom$|"
                     r"blue-green algae$", re.I)
ALGAE = re.compile(r"algal|blue-green", re.I)
CLEAR = re.compile(r"\bclear\b", re.I)
DROP_KEYS = {"Creator", "Editor", "CreationDate", "EditDate", "GlobalID"}


def norm(s) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).split())


def slug(s) -> str:
    return norm(s).replace(" ", "-")


def day_iso(d: date | None) -> str | None:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).isoformat(timespec="seconds") if d else None


def qualifies(status: str | None, reason: str | None) -> str | None:
    """'closed' / 'advisory' when the row is a water-quality closure or advisory, else None."""
    st = norm(status)
    if st not in ("closed", "open with advisory"):
        return None
    if not reason or not QUALIFY.search(reason) or CLEAR.search(reason):
        return None
    return "closed" if st == "closed" else "advisory"


def save_if_changed(state: dict, source: str, name: str, content: bytes) -> None:
    h = hashlib.sha256(content).hexdigest()
    if state.setdefault("raw_hashes", {}).get(name) != h:
        save_raw(source, content, f"{name}.json")
        state["raw_hashes"][name] = h


def arcgis(sess, url: str, params: dict) -> list[dict]:
    r = sess.get(url + "/query", params={"f": "json", **params}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "features" not in data:
        raise ValueError(f"{url}: {str(data)[:200]}")
    return data["features"]


# ---------------------------------------------------------------- beaches

def beach_points(features: list[dict]) -> dict:
    out = {}
    for f in features:
        a = f["attributes"]
        if a.get("Latitude") is not None and a.get("Longitude") is not None:
            out.setdefault(norm(a.get("StateParkBeach")), (a["Longitude"], a["Latitude"]))
    return out


def place(waterbody: str | None, pt) -> tuple[list[str], str, dict]:
    if not waterbody:
        return [], "none", {}
    slugs, notes = ny_waters.match_waters(waterbody, None, pt)
    return slugs, ("name" if slugs else "none"), {"text": waterbody, "notes": notes or None,
                                                   "checked_against_point": bool(pt)}


def dataset_episodes(rows: list[dict], points: dict, fetched: str, stats: dict) -> list[dict]:
    groups: dict[tuple, dict[date, list]] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(r["date_sample_taken"][:19]).date()
        except (KeyError, ValueError):
            stats["rows_without_date"] = stats.get("rows_without_date", 0) + 1
            continue
        groups.setdefault((r.get("state_park_beach"), r.get("waterbody")), {}).setdefault(d, []).append(r)
    out = []
    for (beach, water), by_day in groups.items():
        days = sorted(by_day)
        ep = None
        for d in days:
            day_rows = by_day[d]
            kinds = [qualifies(x.get("beach_status"), x.get("status_reason")) for x in day_rows]
            kind = "closed" if "closed" in kinds else ("advisory" if "advisory" in kinds else None)
            for x in day_rows:
                st = norm(x.get("beach_status"))
                if st in ("closed", "open with advisory") and not qualifies(x.get("beach_status"), x.get("status_reason")):
                    key = f"{x.get('beach_status')} / {x.get('status_reason') or '(no reason)'}"
                    stats["not_water_quality"][key] = stats["not_water_quality"].get(key, 0) + 1
            if kind:
                if ep is None:
                    ep = {"beach": beach, "water": water, "start": d, "rows": [], "kinds": set()}
                ep["rows"].extend(day_rows)
                ep["kinds"].add(kind)
                continue
            if ep is not None:
                nxt = day_rows[0]
                ep.update(end=d, end_basis=(f"date of the next sample row, which reads "
                                            f"{nxt.get('beach_status')} / {nxt.get('status_reason') or '(no reason)'}"))
                out.append(ep)
                ep = None
        if ep is not None:
            ep.update(end=None, end_basis="the dataset has no later row for this beach")
            out.append(ep)
    recs = []
    for ep in out:
        reasons = sorted({x.get("status_reason") for x in ep["rows"] if x.get("status_reason")})
        etype = ("hab_advisory" if any(ALGAE.search(r) for r in reasons) else
                 "beach_closure" if "closed" in ep["kinds"] else "beach_advisory")
        pt = points.get(norm(ep["beach"]))
        slugs, match, wnote = place(ep["water"], pt)
        rid = f"{slug(ep['beach'])}:{slug(ep['water'])}:{ep['start'].isoformat()}"
        statuses = sorted({x.get("beach_status") for x in ep["rows"]})
        recs.append(event(
            source_id=BEACH_SOURCE, source_record_id=rid, event_type=etype,
            status="advisory_lifted" if ep["end"] else "unknown",
            discharger_name=None, waterbody_text=ep["water"], water_slugs=slugs, water_match=match,
            outfall_name=ep["beach"], lat=pt[1] if pt else None, lon=pt[0] if pt else None,
            coord_source="source" if pt else None,
            started_at=day_iso(ep["start"]), ended_at=day_iso(ep["end"]), time_precision="day",
            fetched_at=fetched, material=None,
            authority=BEACH_AUTHORITY,
            advice_text=f"{' / '.join(statuses)}: {'; '.join(reasons)}" if reasons else None,
            source_url=DATASET_PAGE,
            raw={"rows": ep["rows"], "_ended_at_basis": ep["end_basis"], "_water": wnote,
                 "_dates": "sample dates (day precision); the public is told 18-24 hours after sampling (Parks page)",
                 "_coords": "NYS Parks beach status layer point, joined by beach name" if pt else "no layer point for this beach"},
        ))
    return recs


def live_beaches(features: list[dict], state: dict, now: datetime, fetched: str, by_start: dict,
                 beach_water: dict) -> list[dict]:
    eps = state.setdefault("episodes", {})
    for f in features:
        a = {k: v for k, v in f["attributes"].items() if k not in DROP_KEYS}
        beach = a.get("StateParkBeach")
        try:
            sampled = datetime.strptime(a.get("Date_sampled") or "", "%d-%b-%y").date()
        except ValueError:
            sampled = None
        kind = qualifies(a.get("Beach_status"), a.get("Status_Reason"))
        open_key = next((k for k, e in eps.items() if e["beach"] == beach and e["state"] == "active"), None)
        if kind and sampled:
            key = open_key or f"{slug(beach)}:{sampled.isoformat()}"
            e = eps.setdefault(key, {"beach": beach, "start": sampled.isoformat(), "state": "active",
                                     "first_seen_at": now.isoformat(timespec="seconds"), "kinds": [], "rows": []})
            if kind not in e["kinds"]:
                e["kinds"].append(kind)
            if not e["rows"] or e["rows"][-1] != a:
                e["rows"].append(a)
            e["last_seen_at"] = now.isoformat(timespec="seconds")
        elif open_key:
            e = eps[open_key]
            e.update(state="lifted", end=(sampled or now.astimezone(TZ).date()).isoformat(),
                     end_basis=(f"Date_sampled of the next status shown ({a.get('Beach_status')} / "
                                f"{a.get('Status_Reason') or '(no reason)'})" if sampled else "first poll showing another status"),
                     lifted_seen_at=now.isoformat(timespec="seconds"))
            e["rows"].append(a)
    pts = beach_points(features)
    recs = []
    for key, e in eps.items():
        last = e["rows"][-1] if e["rows"] else {}
        reasons = sorted({r.get("Status_Reason") for r in e["rows"] if r.get("Status_Reason")})
        etype = ("hab_advisory" if any(ALGAE.search(r) for r in reasons) else
                 "beach_closure" if "closed" in e["kinds"] else "beach_advisory")
        pt = pts.get(norm(e["beach"])) or ((last.get("Longitude"), last.get("Latitude")) if last.get("Latitude") else None)
        dup = by_start.get((norm(e["beach"]), e["start"]))
        water = beach_water.get(norm(e["beach"]))   # the layer has no waterbody field: the dataset's name
        slugs, match, wnote = place(water, pt)
        recs.append(event(
            source_id=BEACH_SOURCE, source_record_id=f"live:{key}", event_type=etype,
            status="advisory_active" if e["state"] == "active" else "advisory_lifted", duplicate_of=dup,
            outfall_name=e["beach"], waterbody_text=water, water_slugs=slugs, water_match=match,
            lat=pt[1] if pt else None, lon=pt[0] if pt else None, coord_source="source" if pt else None,
            started_at=day_iso(date.fromisoformat(e["start"])),
            ended_at=day_iso(date.fromisoformat(e["end"])) if e.get("end") else None, time_precision="day",
            fetched_at=fetched, authority=BEACH_AUTHORITY,
            advice_text=f"{last.get('Beach_status')}: {'; '.join(reasons)}" if reasons else last.get("Beach_status"),
            source_url=BEACH_PAGE,
            raw={"rows": e["rows"], "first_seen_at": e.get("first_seen_at"), "last_seen_at": e.get("last_seen_at"),
                 "_ended_at_basis": e.get("end_basis"), "_water": wnote},
        ))
    return recs


def run_beaches(sess, fetched: str) -> str:
    state = read_json(BEACH_STATE, {}) or {}
    now = datetime.now(UTC)
    try:
        r = sess.get(SODA, params={"$limit": 50000, "$order": "state_park_beach,date_sample_taken"}, timeout=90)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list):
            raise ValueError(str(rows)[:200])
        save_if_changed(state, BEACH_SOURCE, "wwwd-za77", r.content)
    except Exception as e:  # noqa: BLE001
        write_events(BEACH_SOURCE, [], ok=False, error=f"wwwd-za77: {type(e).__name__}: {e}")
        return f"{BEACH_SOURCE}: FAILED {e}"
    errors = []
    try:
        feats = arcgis(sess, BEACH_LAYER, {"where": "1=1", "outFields": "*", "returnGeometry": "false"})
        clean = [{"attributes": {k: v for k, v in f["attributes"].items() if k not in DROP_KEYS}} for f in feats]
        save_if_changed(state, BEACH_SOURCE, "beach-status-layer", json.dumps(clean, sort_keys=True).encode())
    except Exception as e:  # noqa: BLE001
        feats, clean = [], []
        errors.append(f"beach status layer: {type(e).__name__}: {e}")
    stats = {"not_water_quality": {}}
    points = beach_points(feats)
    recs = dataset_episodes(rows, points, fetched, stats)
    by_start = {(norm(x["outfall_name"]), x["started_at"][:10]): x["event_id"] for x in recs}
    counts: dict[str, dict[str, int]] = {}
    for x in rows:
        c = counts.setdefault(norm(x.get("state_park_beach")), {})
        c[x.get("waterbody")] = c.get(x.get("waterbody"), 0) + 1
    beach_water = {b: max(c, key=c.get) for b, c in counts.items()}
    live = live_beaches(clean, state, now, fetched, by_start, beach_water)
    state["last_poll_at"] = now_iso()
    write_json(BEACH_STATE, state)
    records = sorted(recs + live, key=lambda x: x["started_at"] or "", reverse=True)
    beaches = {(x.get("state_park_beach"), x.get("waterbody")) for x in rows}
    placed = {(b, w) for b, w in beaches if place(w, points.get(norm(b)))[0]}
    meta = {"dataset_rows": len(rows), "dataset_last_sample": max((x.get("date_sample_taken") or "") for x in rows)[:10],
            "beaches": len(beaches), "beaches_with_slug": len(placed), "beaches_with_point": sum(1 for b, _ in beaches if norm(b) in points),
            "live_layer_beaches": len(feats),
            "live_layer_status": {s: sum(1 for f in feats if f["attributes"].get("Beach_status") == s)
                                  for s in sorted({f["attributes"].get("Beach_status") for f in feats})},
            "episodes_dataset": len(recs), "episodes_live": len(live),
            "not_water_quality_rows": dict(sorted(stats["not_water_quality"].items(), key=lambda kv: -kv[1])),
            "credit": "NYS OPRHP, Beach Water Testing: Beginning 2015 (Open Data NY) and the State Parks beach status map"}
    write_events(BEACH_SOURCE, records, ok=True, error="; ".join(errors) or None, meta=meta)
    by = {}
    for x in records:
        by[(x["event_type"], x["status"])] = by.get((x["event_type"], x["status"]), 0) + 1
    return (f"{BEACH_SOURCE}: {len(rows)} sample rows -> {len(recs)} episodes, {len(live)} live; "
            f"{meta['beaches_with_slug']}/{meta['beaches']} beaches with a water slug; {by}")


# ---------------------------------------------------------------- HABs

def ms_iso(v) -> str | None:
    if v in (None, ""):
        return None
    return datetime.fromtimestamp(v / 1000, UTC).astimezone(TZ).isoformat(timespec="seconds")


def run_habs(sess, fetched: str) -> str:
    state = read_json(HAB_STATE, {}) or {}
    now = datetime.now(UTC)
    try:
        feats = arcgis(sess, HAB_LAYER, {"where": "1=1", "outFields": "*", "outSR": "4326", "returnGeometry": "true"})
        save_if_changed(state, HAB_SOURCE, "current-hab-reports", json.dumps(feats, sort_keys=True).encode())
    except Exception as e:  # noqa: BLE001
        write_events(HAB_SOURCE, [], ok=False, error=f"{type(e).__name__}: {e}")
        return f"{HAB_SOURCE}: FAILED {e}"
    seen = state.setdefault("reports", {})
    current = set()
    for f in feats:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        rid = str(a.get("globalid") or a.get("objectid")).strip("{}").lower()
        current.add(rid)
        rec = seen.setdefault(rid, {"first_seen_at": now.isoformat(timespec="seconds")})
        rec.update({"attributes": a, "x": g.get("x"), "y": g.get("y"), "last_seen_at": now.isoformat(timespec="seconds"),
                    "state": "active"})
        rec.pop("missing_at", None)
    for rid, rec in seen.items():
        if rid not in current and rec.get("state") == "active":
            rec.update(state="lifted", missing_at=now.isoformat(timespec="seconds"))
    state["last_poll_at"] = now_iso()
    write_json(HAB_STATE, state)
    records = []
    for rid, rec in seen.items():
        a = rec["attributes"]
        pt = (rec["x"], rec["y"]) if rec.get("x") is not None else None
        water = " ".join(str(a.get("water_name") or "").split()) or None
        slugs, match, wnote = place(water, pt)
        lifted = rec.get("state") == "lifted"
        raw = {"attributes": a, "first_seen_at": rec.get("first_seen_at"), "last_seen_at": rec.get("last_seen_at"),
               "_water": wnote}
        if lifted:
            raw["_ended_at_basis"] = (f"the report left DEC's current HAB layer between {rec.get('last_seen_at')} and "
                                      f"{rec.get('missing_at')}; ended_at is the first poll without it (an upper bound)")
        records.append(event(
            source_id=HAB_SOURCE, source_record_id=rid, event_type="hab_advisory",
            status="advisory_lifted" if lifted else "advisory_active",
            waterbody_text=water, water_slugs=slugs, water_match=match,
            lat=pt[1] if pt else None, lon=pt[0] if pt else None, coord_source="source" if pt else None,
            started_at=ms_iso(a.get("date_time")), ended_at=rec.get("missing_at") if lifted else None,
            time_precision="minute", source_updated_at=ms_iso(a.get("STATUS_DATE")), fetched_at=fetched,
            material=f"cyanobacteria bloom ({a.get('HAB_STATUS')}; extent {a.get('extent_bloom')})",
            authority=HAB_AUTHORITY, advice_text=a.get("Weblink"), source_url=HAB_PAGE, raw=raw,
        ))
    records.sort(key=lambda x: x["started_at"] or "", reverse=True)
    meta = {"current_reports": len(feats), "kept": len(records),
            "lifted": sum(1 for x in records if x["status"] == "advisory_lifted"),
            "with_slug": sum(1 for x in records if x["water_slugs"]),
            "status": {s: sum(1 for f in feats if f["attributes"].get("HAB_STATUS") == s)
                       for s in sorted({f["attributes"].get("HAB_STATUS") for f in feats})},
            "credit": "NYS DEC Harmful Algal Blooms Program (NYHABS current reports)"}
    write_events(HAB_SOURCE, records, ok=True, meta=meta)
    return (f"{HAB_SOURCE}: {len(feats)} current reports, {len(records)} kept ({meta['lifted']} lifted); "
            f"{meta['with_slug']} with a water slug")


def main(argv=None) -> int:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    fetched = now_iso()
    msgs = [run_beaches(sess, fetched), run_habs(sess, fetched)]
    for m in msgs:
        print(m, file=sys.stderr if "FAILED" in m else sys.stdout)
    return 1 if all("FAILED" in m for m in msgs) else 0


if __name__ == "__main__":
    sys.exit(main())
