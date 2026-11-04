"""RIDEM / RIDOH cyanobacteria (blue-green algae) advisories, Rhode Island.

Source: ArcGIS layer Cyanobacteria_Advisories_WFL1/FeatureServer/0 (RIDEM Office of Water Resources
with RIDOH), the data behind dem.ri.gov/bluegreen and dashboard d5780051f06f4c1b906bb692ccd7309a.
No key, no licence on the item (DEM site disclaimer asks for credit). One feature per advisory:
WaterbodyN, Town / SecMun (coded 1-39, sometimes typed as a name), F2024_Advis (C current,
P previous, N no advisory; sometimes the label "No Advisory" instead of the code), AdvisoryPo
(posted) and AdvisoryL (lifted) as epoch ms, MoreInfo (press release URL), point geometry.

Record rules:
- C -> hab_advisory advisory_active; P -> advisory_lifted with ended_at = AdvisoryL. Features with
  no advisory (N, no dates) are monitored waters, not events: they are listed in meta.tracked so the
  status build can show them as covered. A feature with dates that disagree with its code keeps the
  code's status and says so in parse_error.
- event_id = ri-dem-cyano:<OBJECTID>; a water with several advisories in a season has several
  features (e.g. Wenscott Reservoir 40, 53, 57). Features that disappear from the layer are kept
  from the previous run.
- Times are the layer's timestamps (to the second, entered by RIDEM; close to but not necessarily
  the press release time), converted to America/New_York, time_precision "minute".
- advice_text is null: the advice is in the linked press release, which sits behind Cloudflare on
  dem.ri.gov / health.ri.gov and is not fetched.
- This layer carries no observer names; the companion field-inspection layer does and is not read.
  strip_personal() runs on every raw record regardless.
- water_slugs: openboatlaunch water named like WaterbodyN (or its bracketed alternative, e.g.
  "Echo Lake (Pascoag Reservoir)"), same town when names repeat (water_match "name"); else a water
  sharing a name word within 150 m, or the one water the point lies in (water_match "geometry");
  else none (Roger Williams Park ponds, Slack, Wenscott, Almy ... have no openboatlaunch record).

Cadence: daily (advisories are posted and lifted on weekdays; monitoring biweekly mid-May to
late October, responses year-round).

Run: python -m ingest.ri_dem_cyano   (from pipeline/)
"""
from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta, read_json, save_raw, write_events
from ingest import ri_waters

SOURCE_ID = "ri-dem-cyano"
LAYER = "https://services1.arcgis.com/HAt3zp2GOzn12Lxk/arcgis/rest/services/Cyanobacteria_Advisories_WFL1/FeatureServer/0"
PAGE_URL = "https://dem.ri.gov/environmental-protection-bureau/water-resources/research-monitoring/cyanobacteria-blue-green-algae"
AUTHORITY = "RIDEM and RIDOH cyanobacteria advisories (RIDEM advisories layer)"
TZ = ZoneInfo("America/New_York")
TOWNS = ["Barrington", "Bristol", "Central Falls", "Charlestown", "Coventry", "Cranston", "Cumberland",
         "East Greenwich", "East Providence", "Exeter", "Foster", "Hopkinton", "Jamestown", "Johnston",
         "Lincoln", "Little Compton", "Middletown", "Narragansett", "Newport", "North Kingstown",
         "North Providence", "North Smithfield", "Pawtucket", "Portsmouth", "Providence", "Smithfield",
         "Tiverton", "Warren", "Warwick", "West Greenwich", "West Warwick", "Westerly", "Woonsocket",
         "Glocester", "Burrillville", "South Kingstown", "New Shoreham", "Richmond", "Scituate"]
STATUS_CODES = {"c": "C", "current advisory": "C", "p": "P", "previous advisory": "P", "n": "N", "no advisory": "N"}


def town_name(v, domain: dict) -> str | None:
    if v in (None, ""):
        return None
    s = str(v).strip()
    return domain.get(s) or (TOWNS[int(s) - 1] if s.isdigit() and 0 < int(s) <= len(TOWNS) else s)


def ms_iso(v) -> tuple[str | None, str | None]:
    if v in (None, ""):
        return None, None
    dt = datetime.fromtimestamp(int(v) / 1000, UTC).astimezone(TZ)
    prec = "day" if (dt.hour, dt.minute, dt.second) == (0, 0, 0) else "minute"
    return dt.isoformat(timespec="seconds"), prec


def names_of(waterbody: str) -> list[str]:
    """'Flat River Reservoir (Johnson's Pond)' -> ['Flat River Reservoir', "Johnson's Pond"];
    'Cunliff Lake - RWP Ponds' -> ['Cunliff Lake']; 'Slack Reservoir at Little Beach' -> ['Slack Reservoir']."""
    s = waterbody or ""
    alts = re.findall(r"\(([^)]*)\)", s)
    base = re.sub(r"\([^)]*\)", "", s)
    base = re.split(r"\s+-\s+|\s+at\s+", base)[0]
    return [n.strip() for n in [base, *alts] if n.strip()]


def place(waterbody: str, towns: list[str], lat, lon) -> tuple[list[str], str, dict]:
    names = names_of(waterbody)
    for n in names:
        for t in towns or [None]:
            hits = ri_waters.by_name(n, t)
            if hits and (len(hits) == 1 or t):
                return hits[:1] if len(hits) > 1 else hits, "name", {"by": n}
        toks = set(ri_waters.norm(n).split())
        same = [w["slug"] for w in ri_waters.waters() if set(ri_waters.norm(w["name"]).split()) == toks]
        if len(same) == 1:
            return same, "name", {"by": n, "word_order": True}
    near = ri_waters.near(lat, lon, 150)
    words = {w for n in names for w in ri_waters.norm(n).split()}
    shared = [s for s, d in near if ri_waters.water_words(s) & words]
    if shared:
        return shared[:1], "geometry", {"nearest_waters_m": near[:3]}
    inside = [s for s, d in near if d == 0 and ri_waters.geom_kind(s) == "geometry"]
    if len(inside) == 1:
        return inside, "geometry", {"nearest_waters_m": near[:3], "point_inside": True}
    return [], "none", {"nearest_waters_m": near[:3]} if near else {}


def main() -> int:
    s = requests.Session()
    s.headers.update(HEADERS)
    fetched = now_iso()
    try:
        r = s.get(f"{LAYER}/query", params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "json",
                                             "resultRecordCount": 2000}, timeout=60)
        r.raise_for_status()
        js = r.json()
        if "features" not in js:
            raise ValueError(f"no features: {str(js)[:200]}")
        save_raw(SOURCE_ID, r.content, "json")
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"ri-dem-cyano: FAILED {e}", file=sys.stderr)
        return 1
    domain, edited = {}, None
    try:
        meta_js = s.get(LAYER, params={"f": "json"}, timeout=60).json()
        for f in meta_js.get("fields", []):
            if f["name"] == "Town" and f.get("domain"):
                domain = {c["code"]: c["name"] for c in f["domain"].get("codedValues", [])}
        edited, _ = ms_iso((meta_js.get("editingInfo") or {}).get("dataLastEditDate"))
    except Exception as e:
        print(f"ri-dem-cyano: layer metadata unavailable ({e}); using built-in town list", file=sys.stderr)

    records, tracked = {}, []
    for f in js["features"]:
        a, g = f.get("attributes", {}), f.get("geometry") or {}
        lat, lon = g.get("y"), g.get("x")
        code = STATUS_CODES.get(str(a.get("F2024_Advis") or "").strip().lower())
        towns = [t for t in (town_name(a.get("Town"), domain), town_name(a.get("SecMun"), domain)) if t]
        posted, p_prec = ms_iso(a.get("AdvisoryPo"))
        lifted, _ = ms_iso(a.get("AdvisoryL"))
        name = (a.get("WaterbodyN") or "").strip()
        slugs, how, detail = place(name, towns, lat, lon)
        if code == "N" and not posted and not lifted:
            tracked.append({"objectid": a.get("OBJECTID"), "waterbody": name, "towns": towns, "lat": lat, "lon": lon,
                            "water_slugs": slugs, "water_match": how})
            continue
        parse_error = None
        if code == "C":
            status = "advisory_active"
            if lifted:
                parse_error = "coded Current Advisory but has a lifted date"
        elif code == "P":
            status = "advisory_lifted"
            if not lifted:
                parse_error = "coded Previous Advisory but has no lifted date"
        else:
            status = "unknown"
            parse_error = f"advisory code {a.get('F2024_Advis')!r} with dates"
        if not posted:
            parse_error = (parse_error + "; " if parse_error else "") + "no posted date"
        raw = {**a, "Town_name": towns[0] if towns else None, "SecMun_name": towns[1] if len(towns) > 1 else None,
               "layer_url": LAYER, "water_placement": detail or None,
               "time_note": "layer timestamps as entered by RIDEM; may differ from the press release time"}
        rec = event(
            source_id=SOURCE_ID, source_record_id=str(a.get("OBJECTID")),
            event_type="hab_advisory" if posted or code in ("C", "P") else "unknown", status=status,
            waterbody_text=name or None, water_slugs=slugs, water_match=how,
            lat=round(lat, 6) if lat is not None else None, lon=round(lon, 6) if lon is not None else None,
            coord_source="source" if lat is not None else None,
            started_at=posted, ended_at=lifted if status != "advisory_active" else None,
            time_precision=p_prec or "day", source_updated_at=edited, fetched_at=fetched,
            material=None, authority=AUTHORITY, source_url=a.get("MoreInfo") or PAGE_URL,
            raw=raw, parse_error=parse_error,
        )
        records[rec["event_id"]] = rec
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    kept = 0
    for p in prev:
        if p["event_id"] not in records:
            p["raw"] = {**p.get("raw", {}), "gone_from_layer_since": p["raw"].get("gone_from_layer_since") or fetched}
            records[p["event_id"]] = p
            kept += 1
    out = sorted(records.values(), key=lambda r: r["started_at"] or "", reverse=True)
    meta = {"features": len(js["features"]), "advisories": len(out), "kept_from_previous": kept,
            "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "with_water_slug": sum(1 for r in out if r["water_slugs"]),
            "layer_last_edit": edited, "tracked": tracked}
    path_notes_to_meta(out, meta)          # notes naming repository files stay out of raw
    path = write_events(SOURCE_ID, out, ok=True, meta=meta)
    print(f"ri-dem-cyano: {len(out)} advisories ({meta['advisory_active']} active), {len(tracked)} monitored waters "
          f"with none; water slug {meta['with_water_slug']}/{len(out)} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
