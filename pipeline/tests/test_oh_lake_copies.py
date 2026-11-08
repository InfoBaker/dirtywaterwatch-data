"""Ohio re-check of 2026-11-08, P1-2: a lake, pond or reservoir record built from OpenStreetMap that lies on an existing
(openboatlaunch) lake's outline is that lake's copy and is dropped at the write, for every state (recheck_osm_lakes,
run beside recheck_remainders). No network."""
from shapely.geometry import LineString, Polygon, mapping

from ingest import waters_from_nhd as W


def _poly(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


def _rec(slug, name, g, state="OH", kind="lake", source="osm", **kw):
    return {"slug": slug, "name": name, "kind": kind, "state": state, "source": source, "geometry": mapping(g),
            "bbox": list(g.bounds), **kw}


EXISTING = {"example-lake-logan-oh": {**_rec("example-lake-logan-oh", "Example Lake", _poly(-82.50, 39.53, -82.46, 39.55)),
                                      "source": None}}


def test_an_osm_lake_lying_on_an_existing_lake_is_dropped_and_its_rows_follow():
    copy = _rec("example-lake-copy-oh", "Example Lake Falls", _poly(-82.495, 39.532, -82.465, 39.548))   # 100 % on it
    rows = [copy]
    targets = [{"state": "OH", "name": "Example Lake", "slugs": ["example-lake-copy-oh"]}]
    acts = W.recheck_osm_lakes(rows, targets, EXISTING)
    assert rows == [] and acts[0]["action"] == "dropped" and acts[0]["to"] == "example-lake-logan-oh"
    assert targets[0]["slugs"] == ["example-lake-logan-oh"] and "lay on example-lake-logan-oh" in targets[0]["notes"][0]


def test_other_records_stay():
    beside = _rec("example-pond-oh", "Example Pond", _poly(-82.459, 39.53, -82.45, 39.54), kind="pond")  # off the lake
    half = _rec("example-reservoir-oh", "Example Reservoir", _poly(-82.47, 39.53, -82.43, 39.55), kind="reservoir")
    nhd = _rec("example-lake-nhd-oh", "Example Lake", _poly(-82.495, 39.532, -82.465, 39.548), source=None)
    river = _rec("example-run-oh", "Example Run", LineString([(-82.49, 39.535), (-82.47, 39.545)]), kind="stream")
    other_state = _rec("example-lake-wv", "Example Lake", _poly(-82.495, 39.532, -82.465, 39.548), state="WV")
    rows = [beside, half, nhd, river, other_state]
    assert W.recheck_osm_lakes(rows, [], EXISTING) == [] and len(rows) == 5


def test_the_write_runs_it():
    """The batch's waters, osm and names steps all write through the same function: the check runs there unaided."""
    import inspect
    src = inspect.getsource(W)
    assert "rechecked += recheck_osm_lakes(rows, targets_rows)" in src
