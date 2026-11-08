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
