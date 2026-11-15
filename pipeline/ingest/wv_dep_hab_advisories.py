"""West Virginia DEP's algal bloom advisory map -> data/build/events/wv-dep-hab-advisories.json.

Source
  The map service behind DEP's Harmful Algal Blooms page (https://dep.wv.gov/WWE/watershed/Algae/Pages/
  Harmful-Algal-Blooms.aspx): https://tagis.dep.wv.gov/arcgis/rest/services/webMercator/algae_advisories/MapServer
  ("Algae advisories in West Virginia"), three layers: 1 'Algal Bloom Location' (points), 2 'Algal Bloom Segments'
  (lines along a stream), 3 'Algal Bloom Area' (polygons on a lake). Fields: OBJECTID, Advisory (text), and
  Date_Observed (DateObserved on layer 3), an esri date. Read 2026-11-14: every layer answered and held no row (DEP's
  page also says no advisory is in effect; its table of reported blooms was last updated in August 2023). The layers
  carry no person, no water name and no edit date.

Records (a map of what is in effect, read as a snapshot)
  - One record per row of any layer (source_record_id '<layer>-<OBJECTID>'), event_type hab_advisory (blooms, never
    sewage), status advisory_active while the map shows it; advice_text is DEP's Advisory text in its words.
  - started_at is the first read of the map that showed it (time_precision poll): DEP gives the day the bloom was
    observed (raw.date_observed_utc, kept as DEP stores it; its precision unknown), not the day an advisory was issued, so no issue date is
    invented; reported_at, published_at and source_updated_at stay null. A row that leaves the map and comes back is
    a new episode; the earlier one is kept under '<key>~2'. raw._last_seen_in_source is the latest read
    that showed it, so the status build keeps it in effect while the map shows it.
  - A row no longer on a map the module could read is lifted at that read (advisory_lifted, ended_at the read,
    raw.ended_at_precision 'poll'), an upper bound, not DEP's lift time. A layer that answers with an error makes the
    run ok=False: the records are kept and nothing is lifted; so does a layer that answers only part of its rows
    (exceededTransferLimit). The Advisory text is cut before it is saved anywhere (scrub_advisory: common.scrub_text,
    then every street house number, then every sentence naming who reported, sampled or can be called, or still
    holding an address in any case or a label such as 'Reporter:' (ingest.wv_la_privacy); text that cannot be cut to
    the advice alone is withheld).
  - Placement by the agency's own geometry only: the marker is a point's position, the point half way along a
    segment, or an interior point of an area (never a vertex mean, which can fall outside a concave area), rounded to
    three decimals (coord_source 'agency_layer'); raw.geometry_kind and raw.marker_basis say which. DEP's segment or
    area itself is kept in raw.agency_extent (GeoJSON, three decimals); when it has several parts, the status build
    places the advisory on the water of each part by that part's own interior point (build/status.py
    extent_part_points), and each water's colour follows the whole-water and river rules. No water name is invented.

Run from pipeline/: python -m ingest.wv_dep_hab_advisories [--file saved.json] [--at 2026-11-14T12:00:00Z]
Cadence: with the refresh (daily is enough; the map changes rarely).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest import wv_la_privacy

SOURCE_ID = "wv-dep-hab-advisories"
SERVICE = "https://tagis.dep.wv.gov/arcgis/rest/services/webMercator/algae_advisories/MapServer"
PAGE = "https://dep.wv.gov/WWE/watershed/Algae/Pages/Harmful-Algal-Blooms.aspx"
LAYERS = {1: "point", 2: "segment", 3: "area"}
STATE_PATH = BUILD_DIR / "wv-dep-hab-advisories-state.json"
AUTHORITY = "West Virginia Department of Environmental Protection (algal bloom advisory map)"
TZ = "America/New_York"
START_BASIS = ("the first read of DEP's map that showed it: DEP gives the day the bloom was observed, not the day an "
               "advisory was issued")
WINDOW_BASIS = "in effect while DEP's map shows it; DEP sets no fixed period"


def _esri_area(g: dict):
    """An esri polygon (rings: outer rings clockwise, holes counter-clockwise) as a shapely (Multi)Polygon."""
    from shapely.geometry import LinearRing, MultiPolygon, Polygon
    outers, holes = [], []
    for ring in g.get("rings") or []:
        if len(ring) < 4:
            continue
        lr = LinearRing([(float(x), float(y)) for x, y, *_ in ring])
        (holes if lr.is_ccw else outers).append(lr)
    polys = []
    for o in outers:
        po = Polygon(o)
        polys.append(Polygon(o, [h for h in holes if po.contains(Polygon(h).representative_point())]))
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def _esri_line(g: dict):
    from shapely.geometry import LineString, MultiLineString
    paths = [[(float(x), float(y)) for x, y, *_ in p] for p in g.get("paths") or [] if len(p) >= 2]
    if not paths:
        return None
    return LineString(paths[0]) if len(paths) == 1 else MultiLineString(paths)


def _r3_coords(c):
    return [round(c[0], 3), round(c[1], 3)] if isinstance(c[0], (int, float)) else [_r3_coords(x) for x in c]


def place(kind: str, g: dict) -> tuple[float | None, float | None, dict | None]:
    """(lat, lon, extent): the marker and DEP's own extent. A point is itself; a segment's marker lies on the line,
    half way along it; an area's marker is an interior point of the polygon (shapely representative_point: inside
    a concave shape, outside its holes, on one part of a multipart area), never the vertex mean, which can fall
    outside. The extent is DEP's geometry as GeoJSON, every coordinate rounded to three decimals, kept for the
    placement of the advisory's whole stretch or area (raw.agency_extent)."""
    from shapely.geometry import mapping
    try:
        if kind == "point":
            return round(float(g["y"]), 3), round(float(g["x"]), 3), None
        geom = _esri_line(g) if kind == "segment" else _esri_area(g)
        if geom is None or geom.is_empty:
            return None, None, None
        if kind == "segment":
            pt = geom.interpolate(0.5, normalized=True) if geom.geom_type == "LineString" else \
                max(geom.geoms, key=lambda x: x.length).interpolate(0.5, normalized=True)
        else:
            pt = geom.representative_point()
        gj = mapping(geom)
        extent = {"type": gj["type"], "coordinates": _r3_coords(gj["coordinates"])}
        return round(pt.y, 3), round(pt.x, 3), extent
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        return None, None, None


STREET = (r"(?:Lane|Ln|Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Court|Ct|Way|Boulevard|Blvd|Circle|Cir|Place|Pl|Pike|"
          r"Highway|Hwy|Route|Rte|Trail|Trl|Terrace|Ter|Parkway|Pkwy|Hollow|Holw|Ridge|Loop|Alley|Square|Sq)")
# a house number before a street: '123 Example Lane', '12B N. Example St' (any street, not only a residence's)
HOUSE_NUMBER_RE = re.compile(rf"(?<![\w.,/:-])\d{{1,6}}[A-Za-z]?(?=[ ]{{1,2}}(?:[NSEW]\.?[ ]{{1,2}})?(?:[A-Z0-9][\w'.-]*[ ]{{1,2}}){{1,4}}{STREET}\b)")
# a clause that names who reported, sampled or can be called: the whole sentence is cut
PERSON_CLAUSE_RE = re.compile(
    r"(?i:\b(?:submitted|reported|sampled|collected|photographed|found|called in|sent|provided|observed|noticed)[ ]+by\b)"
    r"|(?i:\b(?:contact(?:ing)?|call(?:ing)?))[ ]+(?!(?i:with)\b)(?:[A-Z]|(?i:us|the)\b|\[|\d)"
    r"|(?i:\b(?:e-?mail|courtesy of|thanks to|resident|residents|homeowner|landowner|property owner|neighbou?r)\b)"
    r"|\b(?:Mr|Mrs|Ms|Miss|Dr)\.?[ ]+[A-Z]|\[(?:name|phone|email) removed\]")
# sentence breaks, not after a title or an initial ('Mrs. Example', 'N. Example Rd')
# (a title in any case: 'dr. example person' stays one sentence, so the honorific check sees the name after it)
SENTENCE_RE = re.compile(r"(?<=[.!?;])(?<!\b(?i:mr)\.)(?<!\b(?i:mrs)\.)(?<!\b(?i:ms)\.)(?<!\b(?i:mx)\.)(?<!\b(?i:dr)\.)"
                         r"(?<!\b(?i:prof)\.)(?<!\b(?i:rev)\.)(?<!\bSt\.)(?<!\b[A-Z]\.)[ ]+")
WITHHELD = "(DEP's advisory text is withheld here: it could not be cut to the advisory alone)"


def scrub_advisory(text: str) -> str | None:
    """DEP's Advisory text, cut to the advice before anything is saved: common.scrub_text (e-mails, phones, contact
    names), then every street house number, then every sentence that names who reported, sampled or can be called.
    Text left with a capitalised name pair after 'by' or with nothing but removals is withheld (WITHHELD)."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    t = HOUSE_NUMBER_RE.sub(common.HOUSE_NUMBER_REMOVED, common.scrub_text(t))
    # then, in any case, every sentence still holding an address or a label of who reported, sampled, collected or
    # can be called ('123 example lane', 'Reporter: ...', 'Sample collector: ...'; ingest.wv_la_privacy) is cut
    kept = [x for x in SENTENCE_RE.split(t) if x and not PERSON_CLAUSE_RE.search(x)
            and not wv_la_privacy.has_address(x) and not wv_la_privacy.names_a_person(x)]
    out = " ".join(kept).strip()
    if not re.search(r"[A-Za-z]{3}", out.replace(common.HOUSE_NUMBER_REMOVED, "")) or \
            re.search(r"\bby[ ]+[A-Z][a-z]+[ ]+[A-Z][a-z]+", out):
        return WITHHELD
    return out


def observed(attrs: dict) -> tuple[str | None, int | None]:
    """(the observation as DEP stores it, as a UTC instant; the stored value itself, epoch milliseconds). The layer's
    metadata gives the field no time reference and does not say whether it holds a date or a time of day, so no
    calendar day is read from it: the instant is kept as stored, its precision recorded as unknown."""
    v = attrs.get("Date_Observed", attrs.get("DateObserved"))
    try:
        ms = int(v) if v not in (None, "") else None
        t = datetime.fromtimestamp(ms / 1000, UTC) if ms is not None else None
    except (TypeError, ValueError, OverflowError):
        return None, None
    if t is None:
        return None, None
    return t.strftime("%Y-%m-%dT%H:%M:%SZ"), ms


def rows_of(answers: dict) -> dict[str, dict]:
    """{'<layer>-<OBJECTID>': {kind, advisory, date_observed_utc, date_observed_source_ms, lat, lon, extent}}; ValueError for a layer error."""
    out = {}
    for lid, kind in LAYERS.items():
        doc = answers.get(str(lid))
        if not isinstance(doc, dict) or "error" in doc or "features" not in doc:
            raise ValueError(f"layer {lid} did not answer with features: {str(doc)[:200]}")
        if doc.get("exceededTransferLimit"):
            # a page of a longer answer is not the map: no lift is read from it
            raise ValueError(f"layer {lid} answered only part of its rows (exceededTransferLimit)")
        for f in doc["features"]:
            a = f.get("attributes") or {}
            lat, lon, extent = place(kind, f.get("geometry") or {})
            utc, ms = observed(a)
            text = " ".join(str(a.get("Advisory") or "").split())
            out[f"{lid}-{a.get('OBJECTID')}"] = {"kind": kind, "advisory": scrub_advisory(text),
                                                 "date_observed_utc": utc, "date_observed_source_ms": ms, "lat": lat, "lon": lon,
                                                 "extent": extent}
    return out


def update(state: dict, current: dict, at: str) -> dict:
    items = state.setdefault("items", {})
    for k, it in items.items():
        if it.get("left_at") is None and k not in current:
            it["left_at"] = at
    for k, row in current.items():
        it = items.get(k)
        if it is not None and it.get("left_at"):
            # back on the map after leaving it: the earlier episode is kept under its own key
            n = 2
            while f"{k}~{n}" in items:
                n += 1
            items[f"{k}~{n}"] = it
            it = None
        if it is None:
            it = items[k] = {"first_seen": at}
        it.update(last_seen=at, **row)
    state["last_poll"] = {"at": at, "listed": sorted(current)}
    return state


def records(state: dict) -> list[dict]:
    out = []
    for k, it in sorted((state.get("items") or {}).items()):
        left = it.get("left_at")
        raw = {"layer_row": k.split("~")[0], "geometry_kind": it.get("kind"),
               "date_observed_utc": it.get("date_observed_utc"), "date_observed_source_ms": it.get("date_observed_source_ms"),
               "date_observed_precision": "unknown" if it.get("date_observed_utc") else None,
               "date_observed_basis": ("Date_Observed: DEP's observation of the bloom, an esri date field kept as "
                                       "stored (date_observed_utc, the instant in UTC; date_observed_source_ms, the "
                                       "value itself); DEP's layer does not say whether it holds a date or a time of "
                                       "day, nor in which zone, so no calendar day is read from it"),
               "agency_extent": it.get("extent"),
               "marker_basis": {"point": "DEP's point", "segment": "half way along DEP's segment",
                                "area": "an interior point of DEP's area"}.get(it.get("kind")),
               "first_seen_at": it["first_seen"], "_last_seen_in_source": it.get("last_seen"),
               "start_basis": START_BASIS, "time_zone": TZ, "advisory_noun": "Algal bloom advisory"}
        if left:
            raw.update(ended_at_precision="poll", end_basis="the first read of DEP's map that no longer showed it")
        adv = it.get("advisory")
        out.append(event(source_id=SOURCE_ID, source_record_id=k, event_type="hab_advisory",
                         status="advisory_lifted" if left else "advisory_active", waterbody_text=None,
                         water_slugs=[], water_match="none", lat=it.get("lat"), lon=it.get("lon"),
                         coord_source="agency_layer" if it.get("lat") is not None else None,
                         started_at=it["first_seen"], ended_at=left, time_precision="poll", reported_at=None,
                         published_at=None, source_updated_at=None, authority=AUTHORITY,
                         advice_text=f"West Virginia DEP algal bloom map: {adv}" if adv else "West Virginia DEP algal bloom map (no advisory text given)",
                         advice_window_hours=None, advice_window_basis=WINDOW_BASIS, source_url=PAGE, raw=raw))
        out[-1]["fetched_at"] = it.get("last_seen") or out[-1]["fetched_at"]
    return out


def fetch() -> dict:
    answers = {}
    for lid in LAYERS:
        r = requests.get(f"{SERVICE}/{lid}/query", headers=HEADERS, timeout=120,
                         params={"where": "1=1", "outFields": "OBJECTID,Advisory,Date_Observed" if lid != 3 else
                                 "OBJECTID,Advisory,DateObserved", "returnGeometry": "true", "outSR": "4326",
                                 "f": "json"})
        r.raise_for_status()
        answers[str(lid)] = r.json()
    return answers


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        answers = json.loads(Path(argv[argv.index("--file") + 1]).read_text()) if "--file" in argv else fetch()
        current = rows_of(answers)
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    state = read_json(STATE_PATH, {}) or {}
    if "--file" not in argv and current and state.get("last_rows") != current:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "rows": current}, indent=1).encode(), "json")
    state["last_rows"] = current
    state = update(state, current, at)
    write_json(STATE_PATH, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID], "url": SERVICE, "last_poll": state.get("last_poll"),
            "cadence": "with the refresh; the map lists only what is in effect"}
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {sum(1 for r in recs if r['status'] == 'advisory_active')} on the map; {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
