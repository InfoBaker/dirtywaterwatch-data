"""An authority's standing advisory placed by name on a water record that has no outline here keeps its marker at the
record's own cited point (ND go-live audit 2026-11-15, P1-1: Clear Lake and Antelope Lake in Pierce County were
coloured red with nothing for the map to draw). A general rule, not keyed to one state. Invented data; no network."""
import copy
import json
from datetime import UTC, datetime

import pytest

from build import status as S

NOW = datetime(2026, 11, 14, 19, tzinfo=UTC)


def _record(state, slug, lat=46.9, lon=-99.4, event_type="hab_advisory"):
    src = f"{state.lower()}-example-blooms"
    return {"event_id": f"{src}:example-lake:advisory:2026-08-26", "source_id": src,
            "source_record_id": "example-lake:advisory:2026-08-26", "event_type": event_type,
            "status": "advisory_active", "waterbody_text": "Example Lake", "water_slugs": [slug] if slug else [],
            "water_match": "name" if slug else "none", "lat": lat, "lon": lon,
            "coord_source": "gnis_point" if lat is not None else None, "started_at": "2026-08-26", "ended_at": None,
            "time_precision": "day", "published_at": "2026-08-26", "fetched_at": "2026-11-14T18:00:00Z",
            "estimate_flag": "unknown", "authority": "Example Department (bloom advisories)",
            "advice_text": "The Department's advisory: a harmful algal bloom is present",
            "source_url": "https://example.org/blooms", "raw": {"state": state, "_last_seen_in_source": "2026-11-14T18:00:00Z"}}


def _build(tmp_path, monkeypatch, recs, waters, state):
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-outlines-here")     # no openboatlaunch outline at all
    ev_dir = tmp_path / "events"
    ev_dir.mkdir(exist_ok=True)
    src = recs[0]["source_id"]
    (ev_dir / f"{src}.json").write_text(json.dumps(
        {"source_id": src, "ok": True, "last_ok_at": NOW.isoformat(), "meta": {}, "records": recs}))
    rules = copy.deepcopy(S.load_rules())
    rules["live_states"] = sorted(set(rules["live_states"]) | {state})
    st, _ = S.build(now=NOW, write=False, events_dir=ev_dir, waters=waters, outfalls=[], registry={}, reaches={},
                    flows=({}, {}), rules=rules, placement_cache=False)
    return st


def _lake(slug, state, geometry=None, area=None):
    w = {"slug": slug, "name": "Example Lake", "kind": "lake", "state": state, "area_km2": area,
         "bbox": None, "geometry": None}
    if geometry:
        lon, lat, d = -99.4, 46.9, 0.02
        ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
        w.update(bbox=[lon - d, lat - d, lon + d, lat + d], geometry={"type": "Polygon", "coordinates": [ring]})
    return w


@pytest.mark.parametrize("state,extent,why", [
    ("ND", "named_water", "the advisory covers the water it names; the marker is its point"),
    ("OH", "named_water", "the advisory covers the water it names; the marker is its point"),
    ("OH", None, S.NO_OUTLINE_WHY)])
def test_an_advisory_on_a_water_with_no_outline_keeps_its_marker_at_its_point(tmp_path, monkeypatch, state, extent,
                                                                              why):
    slug = f"example-lake-{state.lower()}"
    rec = _record(state, slug)
    if extent:
        rec["raw"]["advisory_extent"] = extent
    st = _build(tmp_path, monkeypatch, [rec], {slug: _lake(slug, state)}, state)
    assert st["waters"][slug]["status"] == "red"                  # the water is still coloured as before
    pts = [p for p in st["advisory_points"] if p["event_id"] == rec["event_id"]]
    assert len(pts) == 1
    p = pts[0]
    assert p["water_slugs"] == [slug] and p["status"] == "red"
    assert "part_point" not in p                                  # at the record's own point
    assert p["why"] == why


def test_an_advisory_on_a_small_lake_with_an_outline_still_has_no_marker(tmp_path, monkeypatch):
    slug = "example-lake-nd"
    rec = _record("ND", slug)
    st = _build(tmp_path, monkeypatch, [rec], {slug: _lake(slug, "ND", geometry=True, area=1.0)}, "ND")
    assert st["waters"][slug]["status"] == "red"
    assert [p for p in st["advisory_points"] if p["event_id"] == rec["event_id"]] == []     # the fill shows it


def test_an_advisory_with_no_point_on_a_water_with_no_outline_gets_no_invented_marker(tmp_path, monkeypatch):
    slug = "example-lake-nd"
    rec = _record("ND", slug, lat=None, lon=None)
    st = _build(tmp_path, monkeypatch, [rec], {slug: _lake(slug, "ND")}, "ND")
    assert st["waters"][slug]["status"] == "red"
    assert [p for p in st["advisory_points"] if p["event_id"] == rec["event_id"]] == []


def test_a_marker_on_a_water_that_is_not_coloured_whole_keeps_its_reason(tmp_path, monkeypatch):
    # a beach advisory on a bay with no outline was a marker already: its reason is unchanged
    slug = "example-bay-oh"
    rec = _record("OH", slug, event_type="beach_advisory")
    bay = {**_lake(slug, "OH"), "name": "Example Bay", "kind": "bay"}
    st = _build(tmp_path, monkeypatch, [rec], {slug: bay}, "OH")
    pts = [p for p in st["advisory_points"] if p["event_id"] == rec["event_id"]]
    assert len(pts) == 1 and pts[0]["why"] == "water is not a lake, pond or reservoir under 50 km²"
