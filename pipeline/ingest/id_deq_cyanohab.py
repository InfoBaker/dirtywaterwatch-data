"""Idaho DEQ's CyanoHAB Risk Data Table (harmful algal blooms) -> data/build/events/id-deq-cyanohab-risk-table.json.

Source
  https://www.deq.idaho.gov/water-quality/surface-water/cyanobacteria-harmful-algal-blooms/ (registry
  id-deq-cyanohab-risk-table): the Idaho Department of Environmental Quality's table "CyanoHAB Risk Data Table", one
  row per water with Risk Level, Waterbody, County, Data Type, Collection Date and More Information (19 rows on
  2026-11-14: 13 Health Advisory, 1 Alert, 5 Watch). The page explains the levels in DEQ's words: Idaho's response
  framework "includes two risk levels, Health Watch and Health Alert, that provide timely public information while
  toxin test results are pending", and "Health Advisories are issued as a press release through the DHW News webpage
  to inform news outlets and the public of where an active, toxic bloom has been confirmed"; "Using that information,
  DHW determines whether public health notifications are warranted." The table has no row identifier, no issue date
  and no lift date; the Collection Date is the date of the sample or image the row rests on, not an advisory's date.

  Points: the Idaho Department of Health and Welfare's map layer "Public Health Advisories for Recreational Waters in
  Idaho" (registry id-dhw-recreational-advisories; ArcGIS item 8f6fe24f43d044fc8a9e88aa721f101d,
  Public_Health_Advisories_for_Recreational_Waters_in_Idaho_V2_view/FeatureServer/0), the map DEQ's page points to,
  lists the same waters with DHW's own point and RiskTier. Only LocationDiscription, RiskTier, DisplayOnWebsite and the
  point are requested: the layer's Name, Email, ContactInfo, Creator, Editor and InternalNote fields (staff and
  internal notes) are never requested or saved. A DEQ row whose water DHW's layer names (case, apostrophes and dashes
  ignored) takes DHW's point, rounded to 0.001 degree (coord_source "source", raw.point_basis): the authority's own
  marker on the water, so the advisory draws there and a named arm (C. J. Strike's Bruneau and Snake River arms,
  Hayden Lake's north end) keeps its own place. The points of the last good read are kept in the state file, so a
  layer outage moves nothing; a row DHW does not map is placed by its name and county only.

Records (a list read as a snapshot; never an invented date)
  - Health Advisory: the authority's advisory (DHW issues it on DEQ's toxin results), event_type hab_advisory, status
    advisory_active while the table lists the water at that level, the table's words in advice_text. started_at is
    the first read that listed it at that level (time_precision poll; raw.start_basis says the advisory began before);
    sampled_at the row's Collection Date (a sample date, never an issue date); raw._last_seen_in_source the latest
    read that listed it, so the status build keeps it red while DEQ lists it. When a read shows the water at a lower
    level or no longer lists it, the advisory record ends at that read (advisory_lifted, ended_at the read,
    raw.ended_at_precision "poll", raw.end_basis says which), an upper bound, not DHW's lift time.
  - Watch and Alert (DEQ's risk levels while results are pending, or after a Health Alert expired): never an advisory
    here. Each is a hab_advisory record with status unknown, raw._agency_label_only (DEQ's level) and
    raw._caution_to_notice_end, and the source is in data/rules.json unresolved.sample_caution: the status build shows
    the site's caution, from the Collection Date (time_precision day) for 72 hours or until the read that no longer
    lists the water at that level (raw._notice_closed_at), whichever is later; DEQ's words are quoted, never as DHW's
    advisory. An Alert row whose More Information says the water is "closed to recreational use" keeps that sentence
    in advice_text, quoted as the table's.
  - Identity: one record per water (the table's Waterbody, case and punctuation ignored, with its County) and level
    episode: source_record_id <water slug>:<county slug>:<level>:<the first read's UTC date>. A level change closes the
    episode and opens the next; a new Collection Date at the same level is kept in raw.collection_dates (the latest in
    sampled_at). A row the parser cannot read (a level it does not know, no water, a date it cannot read) is kept as an
    "unknown" record with parse_error, never dropped.
  - A page whose table cannot be found, or with no rows, is ok=False: the records stay and nothing ends.
  - Clock: the record's zone is its county's (pipeline/zones.py idaho_zone: Pacific north of the Salmon River, 49 CFR
    71.9), in raw.time_zone; the Collection Date is that zone's calendar day.
  Privacy: the table carries no personal data; strip_personal runs on raw all the same, and only the table's rows (as
  read) and DHW's safe fields are saved to data/raw/, only when they change.

Run from pipeline/: python -m ingest.id_deq_cyanohab [--file saved.html] [--layer-file layer.json] [--at ISO]
Cadence: daily is enough (DEQ edits the table a few times a week in season); it runs with the refresh.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

import zones
from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "id-deq-cyanohab-risk-table"
URL = "https://www.deq.idaho.gov/water-quality/surface-water/cyanobacteria-harmful-algal-blooms/"
LAYER = ("https://services1.arcgis.com/CNPdEkvnGl65jCX8/arcgis/rest/services/"
         "Public_Health_Advisories_for_Recreational_Waters_in_Idaho_V2_view/FeatureServer/0")
LAYER_QUERY = (LAYER + "/query?where=1%3D1&outFields=LocationDiscription,RiskTier,DisplayOnWebsite"
               "&returnGeometry=true&outSR=4326&f=json")
LAYER_ITEM = "https://www.arcgis.com/home/item.html?id=8f6fe24f43d044fc8a9e88aa721f101d"
STATE_PATH = BUILD_DIR / "id-deq-cyanohab-state.json"
AUTHORITY = ("Idaho Department of Health and Welfare and Idaho Department of Environmental Quality "
             "(CyanoHAB Risk Data Table)")
HEADERS_EXPECTED = ["Risk Level", "Waterbody", "County", "Data Type", "Collection Date", "More Information"]
# the table's levels -> (key, is the authority's advisory)
LEVELS = {"health advisory": ("advisory", True), "advisory": ("advisory", True),
          "alert": ("alert", False), "health alert": ("alert", False),
          "watch": ("watch", False), "health watch": ("watch", False)}
LEVEL_NAMES = {"advisory": "Health Advisory", "alert": "Health Alert", "watch": "Health Watch"}
LEVEL_RULE = ("Idaho DEQ: Health Watch and Health Alert are risk levels “that provide timely public information "
              "while toxin test results are pending”; a Health Advisory is issued by the Department of Health and "
              "Welfare where “an active, toxic bloom has been confirmed”")
START_BASIS = ("the first read of DEQ's table that listed this water at this level: the table gives no issue date, so "
               "the advisory began before this time")
WINDOW_BASIS = "in effect while DEQ's CyanoHAB Risk Data Table lists the water as a Health Advisory"
END_GONE = "the first read of DEQ's table that no longer listed the water"
END_LEVEL = "the first read of DEQ's table that listed the water at another level ({})"


def clean(s) -> str:
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).replace("\xa0", " ").replace("​", " ")
    return re.sub(r"\s+", " ", s).strip()


def key(s: str) -> str:
    """'CJ Strike – Snake River Arm' and 'CJ Strike - Snake River Arm' -> 'cj strike snake river arm';
    "Henry's Lake" and 'Henrys Lake' -> 'henrys lake'."""
    s = clean(s).lower().replace("’", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return key(s).replace(" ", "-")


def parse_table(page: str) -> list[dict]:
    """The table's rows as {level, water, county, data_type, collection_date, info}; ValueError when the table or its
    headers are not on the page, or it has no rows."""
    m = re.search(r"<table\b.*?</table>", page or "", re.S | re.I)
    if not m:
        raise ValueError("no table on DEQ's page")
    rows = re.findall(r"<tr\b.*?</tr>", m.group(0), re.S | re.I)
    cells = [[clean(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", r, re.S | re.I)] for r in rows]
    if not cells or cells[0][:6] != HEADERS_EXPECTED:
        raise ValueError(f"the table's headers are not DEQ's ({cells[0] if cells else None})")
    out = [dict(zip(("level", "water", "county", "data_type", "collection_date", "info"), c + [""] * (6 - len(c))))
           for c in cells[1:] if any(c)]
    if not out:
        raise ValueError("DEQ's table has no rows")
    return out


def read_date(s: str) -> str | None:
    """'10/08/2026' and '06/29/26' -> ISO date; None when unreadable."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", clean(s))
    if not m:
        return None
    mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    yr = yr + 2000 if yr < 100 else yr
    try:
        return date(yr, mo, dy).isoformat()
    except ValueError:
        return None


def parse_layer(doc: dict) -> dict[str, dict]:
    """{water key: {name, tier, lat, lon}} from DHW's layer answer (rounded to 0.001 degree); ValueError on an error."""
    if not isinstance(doc, dict) or doc.get("error") or "features" not in doc:
        raise ValueError(f"DHW's layer answered no features: {str(doc.get('error') if isinstance(doc, dict) else doc)[:200]}")
    out = {}
    for f in doc["features"]:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        name = clean(a.get("LocationDiscription"))
        if not name or g.get("x") is None or g.get("y") is None:
            continue
        out[key(name)] = {"name": name, "tier": clean(a.get("RiskTier")) or None,
                          "shown": clean(a.get("DisplayOnWebsite")) or None,
                          "lat": round(float(g["y"]), 3), "lon": round(float(g["x"]), 3)}
    return out


def split_water(water: str) -> tuple[str, str | None]:
    """('C J Strike Reservoir', 'Snake River Arm') for a qualified name; the name and None otherwise. A dash after
    the water's name gives the part DEQ means; the record keeps the whole name as listed."""
    m = re.match(r"^(.*?)\s+[–—-]\s+(.+)$", clean(water))
    if not m:
        return clean(water), None
    base, part = m.group(1).strip(), m.group(2).strip()
    if re.fullmatch(r"(?i)cj\s+strike", base):
        base = "C J Strike Reservoir"
    return base, part


def update(state: dict, rows: list[dict], at: str, layer: dict | None) -> dict:
    """Fold one read of the table into the state: open, continue and close level episodes."""
    if layer is not None:
        state["points"] = layer
        state["points_read_at"] = at
    eps = state.setdefault("episodes", {})
    seen = {}
    for r in rows:
        lv = LEVELS.get(clean(r["level"]).lower())
        wk = f"{slug(r['water'])}:{slug(r['county'])}"
        if not lv or not r["water"]:
            wk = "unread-" + slug(" ".join(r.values()))[:60]
        seen[wk] = (lv[0] if lv else "unknown", r)
    for sid, ep in eps.items():
        if ep.get("ended_at"):
            continue
        cur = seen.get(ep["water_key"])
        if cur is None:
            ep.update(ended_at=at, end_basis=END_GONE)
        elif cur[0] != ep["level"]:
            ep.update(ended_at=at, end_basis=END_LEVEL.format(LEVEL_NAMES.get(cur[0], cur[1]["level"])))
    open_by_key = {ep["water_key"]: sid for sid, ep in eps.items() if not ep.get("ended_at")}
    for wk, (lv, r) in seen.items():
        sid = open_by_key.get(wk)
        if sid is None:
            sid = f"{wk}:{lv}:{at[:10]}"
            n = 2
            while sid in eps:
                sid, n = f"{wk}:{lv}:{at[:10]}~{n}", n + 1
            eps[sid] = {"water_key": wk, "level": lv, "first_seen": at, "collection_dates": []}
        ep = eps[sid]
        ep.update(last_seen=at, row=r)
        # the episode keeps the point it was first placed at: a later move of DHW's marker never rewrites an earlier
        # record's place (lessons 3); an episode with no point yet takes the first one the layer gives
        if not ep.get("point"):
            pt = (state.get("points") or {}).get(key(r["water"]))
            if pt:
                ep["point"] = dict(pt)
        d = read_date(r["collection_date"])
        if d and d not in ep["collection_dates"]:
            ep["collection_dates"].append(d)
    state["last_poll"] = {"at": at, "rows": len(rows), "listed": sorted(seen)}
    return state


def records(state: dict) -> list[dict]:
    points = state.get("points") or {}
    out = []
    for sid, ep in sorted(state.get("episodes", {}).items()):
        r = ep["row"]
        level, ended = ep["level"], ep.get("ended_at")
        base, part = split_water(r["water"])
        pt = ep.get("point") or points.get(key(r["water"]))
        # the county decides; in Idaho County (split by the Salmon River) the listing's own point does (lessons 9)
        zone = zones.idaho_zone(county=r["county"] or None, lat=(pt or {}).get("lat"), lon=(pt or {}).get("lon"))
        sample = sorted(ep["collection_dates"])[-1] if ep["collection_dates"] else None
        raw = {"row": dict(r), "level_as_listed": r["level"], "waterbody_as_listed": r["water"], "part": part,
               "county": f"{r['county']} County" if r["county"] else None, "state": "ID",
               "collection_dates": sorted(ep["collection_dates"]), "first_seen_at": ep["first_seen"],
               "_last_seen_in_source": ep.get("last_seen"), "time_zone": zone,
               "timezone_note": ("Pacific time north of the Salmon River, Mountain time elsewhere (49 CFR 71.9): "
                                 f"{r['county'] or 'no county'} County; the Collection Date is a calendar day there"),
               "level_rule": LEVEL_RULE, "advisory_noun": "Algal bloom health advisory",
               "date_note": ("the Collection Date is the date of the sample or image the row rests on (DEQ's "
                             "column), not an advisory's issue date")}
        lat = lon = None
        if pt:
            lat, lon = pt["lat"], pt["lon"]
            raw.update(point_basis=(f"Idaho Department of Health and Welfare's map point for “{pt['name']}” "
                                    "(Public Health Advisories for Recreational Waters in Idaho), rounded to 0.001 "
                                    "degree: the authority's marker on the water, not a sampling station"),
                       point_url=LAYER_ITEM, dhw_risk_tier=pt.get("tier"))
        if ended:
            raw.update(ended_at_precision="poll", end_basis=ep.get("end_basis"))
        info = r["info"]
        common_f = dict(source_id=SOURCE_ID, source_record_id=sid, waterbody_text=base, water_slugs=[],
                        water_match="none", lat=lat, lon=lon, coord_source="source" if pt else None,
                        coord_precision_m=150 if pt else None, reported_at=None, published_at=None,
                        source_updated_at=None, authority=AUTHORITY, source_url=URL)
        if level == "advisory":
            raw["start_basis"] = START_BASIS
            out.append(event(**common_f, event_type="hab_advisory",
                             status="advisory_lifted" if ended else "advisory_active",
                             started_at=ep["first_seen"], ended_at=ended, time_precision="poll", sampled_at=sample,
                             advice_text=(f"Health Advisory (DEQ's CyanoHAB Risk Data Table, {r['data_type'] or 'no data type given'}"
                                          f", collection date {sample or r['collection_date'] or 'not given'}): "
                                          f"“{info}”" if info else "Health Advisory (DEQ's CyanoHAB Risk Data Table)"),
                             advice_window_hours=None, advice_window_basis=WINDOW_BASIS, raw=raw))
        elif level in ("alert", "watch"):
            name = LEVEL_NAMES[level]
            raw.update(_agency_label_only=f"DEQ's {name}: a risk level, not an advisory",
                       _agency_label=f"{name} (Idaho DEQ)", _caution_to_notice_end=True,
                       _notice_end_basis="DEQ's table still listed the water at this level")
            if ended:
                raw["_notice_closed_at"] = ended
            start = sample or ep["first_seen"][:10]
            if not sample:
                raw["start_basis"] = "no collection date in the row: the first read that listed it"
            out.append(event(**common_f, event_type="hab_advisory", status="ended" if ended else "unknown",
                             started_at=start, ended_at=ended, time_precision="day", sampled_at=sample,
                             advice_text=(f"{name} (DEQ's CyanoHAB Risk Data Table, {r['data_type'] or 'no data type given'}"
                                          f", collection date {sample or 'not given'}): “{info}”" if info
                                          else f"{name} (DEQ's CyanoHAB Risk Data Table)"),
                             advice_window_hours=None, advice_window_basis=None, raw=raw))
        else:
            out.append(event(**common_f, event_type="unknown", status="ended" if ended else "unknown",
                             started_at=ep["first_seen"], ended_at=ended, time_precision="poll", raw=raw,
                             parse_error=f"a row the reader cannot read: {r!r}"))
        if level != "unknown" and r["collection_date"] and not read_date(r["collection_date"]):
            out[-1]["parse_error"] = f"unreadable Collection Date {r['collection_date']!r}"
    return out


def fetch_page() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.text


def fetch_layer() -> dict:
    r = requests.get(LAYER_QUERY, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        page = Path(argv[argv.index("--file") + 1]).read_text() if "--file" in argv else fetch_page()
        rows = parse_table(page)
        if not any(LEVELS.get(clean(r["level"]).lower()) and r["water"] for r in rows):
            # not one row the reader can read (renamed levels, shifted columns): a failed read, nothing ends
            raise ValueError("no row of DEQ's table could be read")
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    layer, layer_error = None, None
    try:
        doc = (json.loads(Path(argv[argv.index("--layer-file") + 1]).read_text()) if "--layer-file" in argv
               else (None if "--file" in argv else fetch_layer()))
        layer = parse_layer(doc) if doc is not None else None
    except (requests.RequestException, OSError, ValueError) as e:
        layer_error = f"DHW's layer: {e} (the last good points are kept)"
    state = read_json(STATE_PATH, {}) or {}
    snapshot = {"rows": rows, "points": layer}
    if "--file" not in argv and state.get("last_snapshot") != snapshot:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, **snapshot}, indent=1).encode(), "json")
    state["last_snapshot"] = snapshot
    state = update(state, rows, at, layer)
    write_json(STATE_PATH, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID, "id-dhw-recreational-advisories"], "url": URL, "layer": LAYER,
            "last_poll": state.get("last_poll"), "points_read_at": state.get("points_read_at"),
            "layer_error": layer_error,
            "cadence": "with the refresh; DEQ edits the table a few times a week in season"}
    unread = [r for r in recs if r.get("parse_error")]
    if unread:
        # an unreadable row is kept (parse_error) and read again next run; the feed is not healthy until it is read
        meta["unread"] = [r["source_record_id"] for r in unread][:20]
        path = write_events(SOURCE_ID, recs, ok=False, partial=True, meta=meta,
                            error=f"{len(unread)} row(s) of DEQ's table the reader cannot read")
    else:
        path = write_events(SOURCE_ID, recs, meta=meta)
    act = sum(1 for r in recs if r["status"] == "advisory_active")
    print(f"{SOURCE_ID}: {len(rows)} rows listed, {act} health advisories in effect; {len(recs)} records -> {path}"
          + (f"; {layer_error}" if layer_error else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
