"""NJDEP harmful algal bloom (HAB) sampling: cyanobacteria alert tiers per sampled site.

Source
  The public feature service behind the NJDEP HAB Dashboard (ArcGIS item
  49190166531d4e5a811c9a91e4a41677; registry row nj-njdep-hab-dashboard):
  NJDEP_Production_HAB_Sampling_2021_public/FeatureServer/0 ('HAB_sample_table', points, no key).
  One row per site visit (2020 onward): sitevisitdate, watbodnm, siteid, latitude/longitude, cell
  count, toxins, advisorytier (HAB Not Present, Watch, Advisory, Warning, Danger), advistorytrigdt
  (the date the tier was set), mungis/ctygis, EditDate. NJDEP staff sample in response to reports;
  rows appear 1-2 days after sampling and the dashboard "is updated each day at noon". Item terms:
  "provided for information purposes only and is not monitored 24/7 for accuracy and currency";
  NJDEP Data Distribution Agreement (credit NJDEP). Only the fields below are requested, so the
  layer's staff fields (createdby, Creator, Editor, emailalert) never reach disk; the raw response is
  saved when it changed.

Records (hab_advisory)
  The dashboard stacks the dots of one site by date "with the current Alert on top", so the alert
  is per site. A site is one waterbody + site id (case and punctuation ignored: 'FTM-030' is
  'FTM030'), or a visit within 25 m of an earlier site of the same waterbody. Per site, in date order:
  a visit with tier Watch, Advisory, Warning or Danger opens an episode (or continues the open one;
  raw.visits keeps every tier); a later visit with 'HAB Not Present' lifts it. started_at = the
  opening sample's time; ended_at = the lifting sample's advistorytrigdt when that falls within 14
  days after the sample (the tier changes when results are posted), else the sample time
  (raw.ended_at_basis). An episode still open is advisory_active; source_updated_at = its latest
  active sample's posting (same rule), from which build/status.py ages it out after 14 days. The
  dashboard is reset each year, so an episode from an earlier year that was never lifted is status
  unknown (raw.note: end not reported).
  A visit with no tier is no observation (counted in meta); an unrecognised tier is a record with
  event_type unknown and a parse_error. Coordinates are the site's point; water_slugs by the
  waterbody name within New Jersey, checked against the point (ingest/nj_waters.py).

Lag and cadence
  Rows 1-2 days after sampling; poll daily (more often in season does no harm).

Run from pipeline/:  python -m ingest.nj_hab [--since 2025-01-01]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, read_json, save_raw, strip_personal, write_events, write_json
from ingest import nj_waters

SOURCE_ID = "nj-hab"
LAYER = ("https://services1.arcgis.com/QWdNfRs7lkPq4g4Q/arcgis/rest/services/"
         "NJDEP_Production_HAB_Sampling_2021_public/FeatureServer/0")
ITEM_URL = "https://www.arcgis.com/home/item.html?id=49190166531d4e5a811c9a91e4a41677"
STATE_PATH = BUILD_DIR / "nj-hab-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "NJDEP Harmful Algal Bloom Program (Division of Water Monitoring, Standards and Pesticide Control)"
DEFAULT_SINCE = "2025-01-01"
PAGE = 1000
SAME_SITE_M = 25
POST_WINDOW = timedelta(days=14)
TIERS = ["Watch", "Advisory", "Warning", "Danger"]       # ascending
FIELDS = ["objectid", "globalid", "sitevisitdate", "watbodnm", "siteid", "algaeobserved", "sampletaken", "algalid",
          "fluorosense", "watertemp", "samplehabitat", "comments", "latitude", "longitude", "toxinpresent", "cellct",
          "cellctqual", "totalcyanogenera", "predomtaxa", "microcystins", "cylindrospermopsin", "anatoxin", "saxitoxin",
          "phyco_ugl", "chl_B", "habstatus", "advisorytrig", "advistorytrigdt", "advisorytier", "dwsource",
          "bathbeach", "watbodgis", "ctygis", "mungis", "EditDate"]
VISIT_KEEP = ["objectid", "sitevisitdate", "siteid", "advisorytier", "advistorytrigdt", "algaeobserved", "cellct",
              "microcystins", "cylindrospermopsin", "anatoxin", "saxitoxin", "predomtaxa", "toxinpresent", "comments",
              "EditDate"]
ADVICE_BASIS = ("NJDEP HAB Dashboard: the current alert at a site is its latest sample's tier "
                "(HAB Watch, Advisory, Warning, Danger); no fixed window")


def ms(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, UTC) if v not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


def local_iso(t: datetime | None) -> str | None:
    return t.astimezone(TZ).replace(microsecond=0).isoformat() if t else None


def tier_of(v) -> tuple[str | None, str]:
    """('Advisory', 'active') / (None, 'lift') / (None, 'blank') / (text, 'unknown')."""
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    low = s.lower()
    if not low:
        return None, "blank"
    if "not present" in low:
        return None, "lift"
    for t in TIERS:
        if re.search(rf"\b{t.lower()}\b", low):
            return t, "active"
    return s, "unknown"


def clean_name(s) -> str:
    return re.sub(r"^[\W_]+|[\W_]+$", "", str(s or "").strip())


def site_norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def dist_m(a, b) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 111_320, (lon2 - lon1) * 111_320 * k)


def posted(v: dict) -> tuple[datetime | None, str]:
    """The time a sample's tier took effect on the dashboard: advistorytrigdt when it falls within 14
    days after the sample, else the sample time."""
    t, trig = ms(v.get("sitevisitdate")), ms(v.get("advistorytrigdt"))
    if t and trig and t <= trig <= t + POST_WINDOW:
        return trig, "advistorytrigdt (the date the tier was set)"
    return t, "sample time"


# --------------------------------------------------------------------------- fetch

def fetch_all(since: str) -> list[dict]:
    feats: list[dict] = []
    offset = 0
    while True:
        params = {"where": f"sitevisitdate >= DATE '{since}'", "outFields": ",".join(FIELDS),
                  "returnGeometry": "true", "outSR": "4326", "orderByFields": "objectid",
                  "resultOffset": offset, "resultRecordCount": PAGE, "f": "json"}
        last = None
        for i in range(3):
            try:
                r = requests.get(LAYER + "/query", params=params, headers=HEADERS, timeout=120)
                r.raise_for_status()
                js = r.json()
                if not isinstance(js.get("features"), list):
                    raise ValueError(f"no features: {str(js)[:200]}")
                break
            except (requests.RequestException, ValueError) as e:  # noqa: PERF203
                last = e
                time.sleep(3 * (i + 1))
        else:
            raise last  # type: ignore[misc]
        feats += js["features"]
        if not js.get("exceededTransferLimit") and len(js["features"]) < PAGE:
            return feats
        offset += len(js["features"])
        if not js["features"]:
            return feats
        time.sleep(1)


# --------------------------------------------------------------------------- sites and episodes

def visits_from(features: list[dict]) -> list[dict]:
    out = []
    for f in features:
        a = dict(f.get("attributes") or {})
        g = f.get("geometry") or {}
        lat, lon = a.get("latitude"), a.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            lat, lon = g.get("y"), g.get("x")
        if not isinstance(lat, (int, float)) or not nj_waters.in_nj(lon, lat):
            lat = lon = None
        a["_lat"], a["_lon"] = lat, lon
        out.append(a)
    out.sort(key=lambda v: (v.get("sitevisitdate") or 0, v.get("objectid") or 0))
    return out


def assign_sites(visits: list[dict]) -> dict[str, list[dict]]:
    """site key -> visits in date order (same waterbody + same site id, or within 25 m)."""
    sites: dict[str, dict] = {}
    by_water: dict[str, list[str]] = {}
    for v in visits:
        w = nj_waters.norm(clean_name(v.get("watbodnm")))
        sid = site_norm(v.get("siteid"))
        pt = (v["_lat"], v["_lon"]) if v["_lat"] is not None else None
        key = None
        for k in by_water.get(w, []):
            s = sites[k]
            if sid and sid == s["sid"]:
                key = k
                break
        if key is None and pt:
            for k in by_water.get(w, []):
                s = sites[k]
                if s["pt"] and dist_m(pt, s["pt"]) <= SAME_SITE_M:
                    key = k
                    break
        if key is None:
            key = f"{w}|{sid or (f'{pt[0]:.5f},{pt[1]:.5f}' if pt else v.get('objectid'))}"
            sites[key] = {"sid": sid, "pt": pt, "visits": []}
            by_water.setdefault(w, []).append(key)
        sites[key]["visits"].append(v)
    return {k: s["visits"] for k, s in sites.items()}


def episodes(site_visits: list[dict], stats: Counter) -> list[dict]:
    out, cur = [], None
    for v in site_visits:
        tier, kind = tier_of(v.get("advisorytier"))
        if kind == "blank":
            stats["visits_without_tier"] += 1
            continue
        if kind == "unknown":
            out.append({"unknown": True, "visits": [v], "tier": tier})
            continue
        if kind == "active":
            if cur is None:
                cur = {"visits": [], "tiers": []}
                out.append(cur)
            cur["visits"].append(v)
            cur["tiers"].append(tier)
        elif cur is not None:          # lift
            cur["lift"] = v
            cur = None
    return out


def build_record(ep: dict, year: int) -> dict:
    first = ep["visits"][0]
    last_active = ep["visits"][-1]
    name = clean_name(first.get("watbodnm")) or None
    pt = (first["_lon"], first["_lat"]) if first["_lat"] is not None else None
    town = first.get("mungis")
    slugs, notes = nj_waters.match_waters(name, [town] if town else None, pt)
    start = ms(first.get("sitevisitdate"))
    visits = [{k: (local_iso(ms(x.get(k))) if k in ("sitevisitdate", "advistorytrigdt", "EditDate") else x.get(k))
               for k in VISIT_KEEP} for x in ep["visits"] + ([ep["lift"]] if ep.get("lift") else [])]
    raw = {"waterbody": name, "site_id": (first.get("siteid") or "").strip() or None, "municipality": town,
           "county": first.get("ctygis"), "bathing_beach": first.get("bathbeach"), "visits": visits,
           "credit": "NJDEP HAB Dashboard (provided for information purposes only; not monitored 24/7)"}
    if notes:
        raw["water_match_notes"] = notes
    perr, etype = None, "hab_advisory"
    if ep.get("unknown"):
        etype, status, ended, upd = "unknown", "unknown", None, None
        perr = f"unrecognised advisorytier {ep['tier']!r}"
    else:
        tiers = ep["tiers"]
        raw["current_tier"] = tiers[-1]
        raw["highest_tier"] = max(tiers, key=TIERS.index)
        upd_t, upd_basis = posted(last_active)
        upd = local_iso(upd_t)
        raw["last_confirmed_basis"] = upd_basis
        if ep.get("lift"):
            end_t, basis = posted(ep["lift"])
            if end_t and start and end_t < start:
                end_t, basis = start, "sample time (lift posted before the opening sample)"
            status, ended = "advisory_lifted", local_iso(end_t)
            raw["ended_at_basis"] = f"'HAB Not Present' sample at this site: {basis}"
        elif last_active.get("sitevisitdate") and ms(last_active["sitevisitdate"]).astimezone(TZ).year < year:
            # the dashboard is reset each year; an alert never resampled before the reset has no reported end
            status, ended = "unknown", None
            raw["note"] = (f"no 'HAB Not Present' sample at this site before the dashboard was reset for "
                           f"{ms(last_active['sitevisitdate']).astimezone(TZ).year + 1}; end not reported")
        else:
            status, ended = "advisory_active", None
    tier_txt = raw.get("current_tier") or ep.get("tier")
    return event(
        source_id=SOURCE_ID, source_record_id=str(first.get("globalid") or first.get("objectid")).strip("{}"),
        event_type=etype, status=status,
        waterbody_text=name, water_slugs=slugs, water_match="name" if slugs else "none",
        lat=first["_lat"], lon=first["_lon"], coord_source="source" if pt else None,
        started_at=local_iso(start), ended_at=ended, time_precision="minute",
        source_updated_at=upd, authority=AUTHORITY,
        advice_text=(f"NJDEP HAB alert tier at this site: {tier_txt}." if tier_txt and etype == "hab_advisory" else None),
        advice_window_basis=ADVICE_BASIS if etype == "hab_advisory" else None,
        source_url=ITEM_URL, raw=raw, parse_error=perr,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=DEFAULT_SINCE)
    args = ap.parse_args(argv)
    state = read_json(STATE_PATH, {}) or {}
    try:
        feats = fetch_all(args.since)
        err = None
        prev = (state.get("visit_count") or {}).get(args.since)
        if not feats:
            err = "empty response: no site visits"
        elif prev and len(feats) < prev / 2:
            err = f"incomplete response: {len(feats)} visits against {prev} before"
    except (requests.RequestException, ValueError) as e:
        feats, err = [], f"{type(e).__name__}: {e}"
    if err:
        write_events(SOURCE_ID, [], ok=False, error=err)
        print(f"{SOURCE_ID}: fetch failed, records kept: {err}", file=sys.stderr)
        return 1
    # free-text comments are scrubbed (emails, phones, staff names) before the raw copy is saved
    content = json.dumps({"where": f"sitevisitdate >= DATE '{args.since}'", "features": strip_personal(feats)},
                         separators=(",", ":")).encode()
    h = hashlib.sha256(content).hexdigest()
    if state.get("raw_hash") != h:
        save_raw(SOURCE_ID, content, "json")
        state["raw_hash"] = h
    state.setdefault("visit_count", {})[args.since] = len(feats)
    write_json(STATE_PATH, state)

    stats: Counter = Counter()
    visits = visits_from(feats)
    stats["visits"] = len(visits)
    stats.update(f"tier {tier_of(v.get('advisorytier'))[1]}" for v in visits)
    sites = assign_sites(visits)
    records = []
    for _, sv in sorted(sites.items()):
        for ep in episodes(sv, stats):
            records.append(build_record(ep, datetime.now(TZ).year))
    records.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": ["nj-njdep-hab-dashboard"], "since": args.since, "sites": len(sites),
            "stats": dict(stats), "active_now": sum(1 for r in records if r["status"] == "advisory_active"),
            "credit": "NJDEP HAB Dashboard; NJDEP Data Distribution Agreement",
            "cadence": "daily (rows appear 1-2 days after sampling)"}
    path = write_events(SOURCE_ID, records, meta=meta)
    print(f"{SOURCE_ID}: {len(records)} episodes at {len(sites)} sites from {len(visits)} visits -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
