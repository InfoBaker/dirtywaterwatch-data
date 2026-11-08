"""Utah go-live audit of 2026-11-08 (docs/checklists/2026-11-08-ut-final.md in the site repository): the fixes, each
with the failure the auditor found. No network."""
import json
import math
from pathlib import Path

import pytest
from shapely.geometry import LineString, mapping, shape

from build import status as S
from ingest import waters_from_nhd as W

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- P1-1: remainders lying on their river

@pytest.fixture
def river(monkeypatch):
    g = LineString([(-111.90, 40.50), (-111.90, 40.80)])
    monkeypatch.setitem(S._GEOM_CACHE, "example-river-ut", g)
    return g


def _rec(slug, coords):
    g = LineString(coords)
    return {"slug": slug, "name": "Example River", "state": "UT", "covers_part_of": "example-river-ut",
            "geometry": mapping(g), "length_km": 1.0, "bbox": list(g.bounds)}


def test_a_remainder_lying_on_its_river_is_dropped_and_its_rows_follow(river):
    rows = [_rec("example-river-north-ut", [(-111.9004, 40.52), (-111.9004, 40.78)])]      # 34 m off, all along
    targets = [{"state": "UT", "name": "Example River", "slugs": ["example-river-north-ut"]}]
    acts = W.recheck_remainders(rows, targets, {})
    assert rows == [] and acts[0]["action"] == "dropped" and targets[0]["slugs"] == ["example-river-ut"]
    assert "lay on example-river-ut" in targets[0]["notes"][0]


def test_a_remainder_half_on_its_river_is_cut_to_the_rest(river):
    rows = [_rec("example-river-north-ut", [(-111.90, 40.70), (-111.90, 40.90)])]          # 10 km on, 11 km beyond
    acts = W.recheck_remainders(rows, [], {})
    assert acts[0]["action"] == "recut" and len(rows) == 1
    g = shape(rows[0]["geometry"])
    assert g.bounds[1] > 40.80 and 9 < rows[0]["length_km"] < 12


def test_a_true_remainder_and_one_without_an_outline_stay(river):
    far = _rec("example-river-south-ut", [(-111.90, 40.40), (-111.90, 40.495)])
    lost = {**_rec("other-river-x-ut", [(-111.9, 40.6), (-111.9, 40.7)]), "covers_part_of": "no-outline-here-ut"}
    rows = [far, lost]
    assert W.recheck_remainders(rows, [], {}) == [] and len(rows) == 2


def test_on_a_runner_with_only_the_api_s_folder_the_recheck_still_recuts(tmp_path, monkeypatch):
    """The batch runner's case (run 42442475851): no openboatlaunch build output, only the API's national bulk file
    restored into out/water. There a river drawn as an area and as lines keeps its line pieces in `geometry_lines`
    and only its area pieces in `geometry`; reading `geometry` alone, the Jordan River was a few polygons, so the
    remainder built along its centre line lay "off" it and was kept. With both read, the recheck drops it."""
    slug = "api-river-ut"
    area = {"type": "Polygon", "coordinates": [[(-111.905, 40.50), (-111.895, 40.50), (-111.895, 40.51),
                                                 (-111.905, 40.51), (-111.905, 40.50)]]}      # one wide stretch
    lines = {"type": "MultiLineString", "coordinates": [[(-111.90, 40.51), (-111.90, 40.80)]]}  # the centre line
    rec = {"slug": slug, "name": "Api River", "kind": "river", "state": "UT", "geometry": area,
           "geometry_lines": lines, "geometry_tolerance_m": 17, "geometry_hash": "x"}       # the API's shape
    (tmp_path / f"{slug}.json").write_text(json.dumps(rec))
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path)
    monkeypatch.delitem(S._GEOM_CACHE, slug, raising=False)
    g = S.water_geometry(slug, None)
    assert g is not None and g.geom_type == "GeometryCollection" and g.bounds[3] >= 40.80   # the lines are read
    # the remainder the runner built: the river less the area piece (the old reading), all along the centre line
    rem = {"slug": "api-river-north-ut", "name": "Api River", "state": "UT", "covers_part_of": slug,
           "geometry": mapping(LineString([(-111.9003, 40.52), (-111.9003, 40.79)])), "length_km": 30.0,
           "bbox": [-111.9003, 40.52, -111.9003, 40.79]}
    # with `geometry` alone the recheck finds nothing to cut (what the runner did)
    monkeypatch.setitem(S._GEOM_CACHE, slug, shape(area))
    rows = [dict(rem)]
    assert W.recheck_remainders(rows, [], {}) == [] and len(rows) == 1
    # with the whole outline it drops the remainder, and its target rows go to the river
    monkeypatch.delitem(S._GEOM_CACHE, slug)
    rows = [dict(rem)]
    targets = [{"state": "UT", "name": "Api River", "slugs": ["api-river-north-ut"]}]
    acts = W.recheck_remainders(rows, targets, {})
    assert rows == [] and acts[0]["action"] == "dropped" and targets[0]["slugs"] == [slug]


def test_an_outline_without_line_pieces_reads_as_before():
    poly = {"type": "Polygon", "coordinates": [[(0, 0), (1, 0), (1, 1), (0, 0)]]}
    assert S.outline_of({"geometry": poly, "geometry_lines": None}).geom_type == "Polygon"
    assert S.outline_of({"geometry": None}) is None
    only = S.outline_of({"geometry": None, "geometry_lines": {"type": "LineString", "coordinates": [(0, 0), (1, 1)]}})
    assert only.geom_type == "LineString"


def test_every_remainder_lies_off_its_rivers_outline():
    """The auditor's data test: for every NHD record with covers_part_of whose parent outline is on disk, under 10 per
    cent of its length lies within SAME_WATER_M of the parent."""
    d = json.loads((ROOT / "data" / "waters-nhd.json").read_text())
    for w in d["waters"]:
        if not w.get("covers_part_of") or not w.get("geometry"):
            continue
        eg = S.water_geometry(w["covers_part_of"], None)
        if eg is None:
            continue
        g = shape(w["geometry"])
        lat0 = g.centroid.y
        gm, em = W.to_m_geom(g, lat0), W.to_m_geom(eg, lat0)
        assert gm.intersection(em.buffer(W.SAME_WATER_M)).length / gm.length < 0.10, w["slug"]


# ---------------------------------------------------------------- P1-2: no layer edit time on the records

def test_undated_hotline_reports_take_no_layer_edit_time_and_the_newest_date_is_a_report_s():
    from export import coverage as C
    from ingest.generic import runner as R
    _, block = R.load_source("ut-deq-environmental-incidents")
    assert block.get("metadata") is False
    rows = R.platform("arcgis").parse(block, (ROOT / "pipeline" / "tests" / "fixtures" / "ut" / "incidents.json").read_bytes())
    meta = {"editingInfo": {"lastEditDate": 1794053173876}}               # 2026-11-07, the layer's last edit
    recs, _ = R.build("ut-deq-environmental-incidents", block, rows, "2026-11-08T01:00:00Z", (), meta)
    undated = [r for r in recs if not r["started_at"]]
    assert undated and all(r["source_updated_at"] is None for r in undated)
    f = C._figures(recs, [], {}, {}, {}, [])
    newest = max(r["started_at"] for r in recs if r["started_at"])
    assert f["latest_dated"][:10] == C.when_of({"started_at": newest}).isoformat()[:10]
    assert not f["latest_dated"].startswith("2026-11-07")


# ---------------------------------------------------------------- P2-1: the Mats CF caution's label

def test_no_utah_interval_label_says_the_code_is_unexplained():
    from datetime import UTC, datetime
    from ingest.generic import runner as R
    _, block = R.load_source("ut-dwq-recreational-advisories")
    rows = R.platform("arcgis").parse(block, (ROOT / "pipeline" / "tests" / "fixtures" / "ut" / "recreational.json").read_bytes())
    recs, _ = R.build("ut-dwq-recreational-advisories", block, rows, "2026-11-08T01:00:00Z", (), None)
    now = datetime(2026, 11, 8, 2, tzinfo=UTC)
    labels = [iv["label"] for r in recs for iv in S.event_intervals(r, "UT", now)]
    mats = [iv for r in recs if r["raw"]["_advisory_label"] == "Mats CF" for iv in S.event_intervals(r, "UT", now)]
    assert mats and mats[0]["color"] == "yellow" and "observed by DWQ's monitoring team" in mats[0]["label"]
    assert not [x for x in labels if "does not publish" in x]


# ---------------------------------------------------------------- P2-2: private points

def test_points_are_kept_to_three_decimals_and_private_homes_to_their_county():
    from ingest.generic import runner as R
    _, block = R.load_source("ut-deq-environmental-incidents")
    assert block["round_coords"] == 3 and not {"Northing", "Easting"} & set(block["safe_fields"])
    rows = R.platform("arcgis").parse(block, (ROOT / "pipeline" / "tests" / "fixtures" / "ut" / "incidents.json").read_bytes())
    home = dict(rows[0], OBJECTID=99010, Id="99000010", Title_EventName="Garland - Sewage Release from Residence",
                _x=-112.1612345, _y=41.7412345)
    recs, _ = R.build("ut-deq-environmental-incidents", block, rows + [home], "2026-11-08T01:00:00Z", (), None)
    for r in recs:
        if r["lat"] is not None:
            assert r["lat"] == round(r["lat"], 3) and r["lon"] == round(r["lon"], 3)
            assert r["raw"]["row"]["_x"] == round(r["raw"]["row"]["_x"], 3)
    h = next(r for r in recs if r["source_record_id"] == "99000010")
    assert h["lat"] is None and h["lon"] is None and "_x" not in h["raw"]["row"] and h["raw"]["county"]
    assert "41.7412" not in json.dumps(h) and "Northing" not in json.dumps(recs)


# ---------------------------------------------------------------- P2-3, P2-5: county-aware names, the missing list

def test_a_morgan_county_gordon_creek_report_is_not_placed_on_carbon_countys_creek(monkeypatch):
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"UT"})                # Utah as it will be once live
    assert "UT" in S.COUNTY_STATES and "UT" in S.COUNTY_FIELD_STATES
    waters = {"gordon-creek-ut": {"slug": "gordon-creek-ut", "state": "UT", "name": "Gordon Creek",
                                  "bbox": [-110.95, 39.62, -110.75, 39.72]}}        # Carbon County, near Helper
    ev = {"lat": 41.151, "lon": -111.82, "raw": {"state": "UT", "county": "Morgan County"}, "npdes_permit": None,
          "source_id": "ut-deq-environmental-incidents"}
    kept, why = S.county_slugs(["gordon-creek-ut"], ev, waters, lambda s, la, lo: 180_000.0)
    assert kept == [] and "Morgan" in why
    withheld = {**ev, "lat": None, "lon": None}                                # a private home's report: the field
    kept, why = S.county_slugs(["gordon-creek-ut"], withheld, waters, lambda s, la, lo: None)
    assert kept == [] and "the county the report gives" in why


def _water_boxes() -> dict:
    """{slug: bbox} over every water file (openboatlaunch's extracts and the NHD build)."""
    out = {}
    for f in sorted((ROOT / "data").glob("waters-*.json")):
        try:
            d = json.loads(f.read_text())
        except ValueError:
            continue
        for w in (d.get("waters") if isinstance(d, dict) else d) or []:
            if isinstance(w, dict) and w.get("slug") and w.get("bbox"):
                out.setdefault(w["slug"], w["bbox"])
    return out


def _held(entry: dict, boxes: dict, pad: float = 0.01) -> bool:
    """A resolved name's record holds the reports' points (its box, padded about 1 km)."""
    pts = entry.get("points") or []
    for s in entry.get("slugs") or []:
        b = boxes.get(s)
        if b and pts and all(b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad for lat, lon in pts):
            return True
    return False


def test_the_missing_list_carries_places_and_the_unplaced_advisories():
    """Each name the auditor found unplaced is either still a missing row with its places, or resolved (the water
    batch) to a record that holds the reports' points: Gordon Creek in Morgan County, not Carbon County's (re-check of
    2026-11-08: the rerun batch built Gordon Creek, Red Creek Reservoir, Sulphur Creek and North Creek at the reports'
    points, so the test must accept a resolved record)."""
    d = json.loads((ROOT / "research" / "ut" / "receiving-waters-missing.json").read_text())
    rows = {(r["name"], r["county"]): r for r in d["rows"]}
    resolved = {(r["name"], r.get("county")): r for r in d.get("resolved") or []}
    boxes = _water_boxes()

    def entry(name, county=None):
        key = next((k for k in list(rows) + list(resolved) if k[0] == name and (county is None or k[1] == county)), None)
        assert key is not None, f"{name} ({county}) is neither a missing row nor resolved"
        return (rows.get(key), None) if key in rows else (None, resolved[key])

    row, res = entry("Gordon Creek", "Morgan County")
    g = row or res
    assert g["points"] and g["points"][0][0] > 41                    # the report's point, north of Morgan
    if row:
        assert row["reports"] == 1
    else:
        assert _held(res, boxes), "Gordon Creek resolved to a record away from the Morgan County report"
    for name in ("Big East Lake", "Red Creek Reservoir", "Sulphur Creek", "North Creek", "Babylon Trail Creek",
                 "Manila Creek Pond", "Fifth Water Hot Springs"):
        row, res = entry(name)
        if row:
            assert row["reports"] >= 1 and "ut-dwq-recreational-advisories" in row["sources"] and row["points"]
        else:
            assert _held(res, boxes), f"{name} resolved to a record that does not hold its points"
    assert all(r["county"] for r in d["rows"])


# ---------------------------------------------------------------- P2-4: construction dewatering is no sewage outfall

def test_construction_dewatering_coverages_are_not_outfalls_but_keep_their_rows():
    from common import load_outfall_registry
    held = {"UTG071774", "UTG072162", "UTG072174"}
    reg = [r for r in load_outfall_registry(provisional=False) if r.get("state") == "UT"]
    assert not held & {r["npdes_permit"] for r in reg} and len(reg) == 116
    doc = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())
    ex = {x["npdes_permit"]: x for x in doc["excluded_not_sewage"]}
    assert all(ex[p]["reason"] == "construction_project" and "UTG07" in ex[p]["basis"] for p in held)
    ops = {p: r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "UT"
           for p in r["npdes_permits"]}
    assert all(ops[p]["outfall_count"] is None and "held back" in ops[p]["notes"] for p in held)
    reg_rows = json.loads((ROOT / "data" / "notice-channels" / "ut.json").read_text())["channels"]
    assert {"ut-alder-construction-dwq-report", "ut-fx-construction-dwq-report",
            "ut-whitaker-construction-dwq-report"} <= {c["id"] for c in reg_rows}
