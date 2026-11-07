"""The sewage reach fixture whose export must stay byte-identical when advisory stretches are added
(tests/test_advisory_stretch.py). `python -m tests.sewage_reach_golden` from pipeline/ rewrites
tests/fixtures/sewage-reaches-golden.json from the current code: only do that for an intended change to the
sewage reaches' export."""
import json
import tempfile
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "sewage-reaches-golden.json"
CROSS, HOME, SLOW, SHORE = "PA0026000-001", "PA0027000-002", "NY0021000-003", "IL0028053-004"
BUILT = "2026-11-07T12:00:00+00:00"


def _seg(comid, k0, k1, coords, **kw):
    return {"comid": comid, "km_start": k0, "km_end": k1, "gnis_name": "R", "coords": coords, **kw}


def cached() -> dict:
    return {
        CROSS: {"key": CROSS, "permit": "PA0026000", "outfall": "001", "water_slug": "chemung-river-pa", "state": "PA",
                "river": "Chemung River", "cut_reason": "cap_km", "length_km": 40.0,
                "segments": [_seg(1, 0.0, 6.0, [[-76.8, 41.98], [-76.7, 41.999]]),
                             _seg(2, 6.0, 40.0, [[-76.7, 41.999], [-76.6, 42.01]])]},
        HOME: {"key": HOME, "permit": "PA0027000", "outfall": "002", "water_slug": "pine-creek-pa", "state": "PA",
               "river": "Pine Creek", "cut_reason": "tidal", "length_km": 12.0,
               "segments": [_seg(3, 0.0, 12.0, [[-77.3, 41.4], [-77.2, 41.35], [-77.1, 41.3]])]},
        SLOW: {"key": SLOW, "permit": "NY0021000", "outfall": "003", "water_slug": "mill-creek-ny", "state": "NY",
               "river": "Mill Creek", "cut_reason": "lake_or_reservoir", "length_km": 3.5,
               "segments": [_seg(4, 0.0, 3.5, [[-74.0, 42.0], [-74.01, 42.02]])]},
        SHORE: {"key": SHORE, "permit": "IL0028053", "outfall": "004", "water_slug": "lake-michigan-il", "state": "IL",
                "model": "shoreline", "lake": "Lake Michigan", "each_way_km": 5.0, "states": ["IL"],
                "waters": ["lake-michigan-il"], "cut_reason": "shoreline", "length_km": 10.0,
                "segments": [{"km_start": 0.0, "km_end": 5.0, "coords": [[-87.6, 41.9], [-87.6, 41.95]]},
                             {"km_start": 0.0, "km_end": 5.0, "coords": [[-87.6, 41.9], [-87.6, 41.85]]}],
                "stops": [{"coords": [-87.6, 41.95], "km_from_outfall": 5.0, "cut_reason": "shoreline_limit"},
                          {"coords": [-87.6, 41.85], "km_from_outfall": 5.0, "cut_reason": "shoreline_limit"}]},
    }


BAND = {"hours_typical": 3.0, "hours_fast": 2.0, "hours_leading_edge": 2.7, "reached_fast": True,
        "reached_typical": True}
NOBAND = {"hours_typical": None, "hours_fast": None, "hours_leading_edge": None, "reached_fast": None,
          "reached_typical": None}


def status() -> dict:
    return {"waters": {"chemung-river-pa": {"state": "PA", "reaches": [CROSS]},
                       "susquehanna-river-ny": {"state": "NY", "reaches": [CROSS]},
                       "pine-creek-pa": {"state": "PA", "reaches": [HOME]},
                       "mill-creek-ny": {"state": "NY", "reaches": [SLOW]},
                       "lake-michigan-il": {"state": "IL", "reaches": [SHORE]}},
            "reaches": {CROSS: {"water_slug": "chemung-river-pa", "status": "red", "active": ["pa-test:1"]},
                        HOME: {"water_slug": "pine-creek-pa", "status": "yellow", "active": [],
                               "rain_likely": ["x"]},
                        SLOW: {"water_slug": "mill-creek-ny", "status": "yellow", "active": ["ny-test:2"]},
                        SHORE: {"water_slug": "lake-michigan-il", "status": "red", "active": ["il-test:3"]}},
            "reach_events_active": [
                {"event_id": "pa-test:1", "reach": CROSS, "status": "red", "rule": "ongoing", "short": "CSO ongoing",
                 "hours_since_start": 4.0, "gauge": "01531000", "gauge_name": "Chemung R at Chemung NY",
                 "flow_cfs": 812.0, "flow_time": "2026-11-07T11:00:00Z", "flow_basis": "gauge",
                 "segments": [BAND, BAND]},
                {"event_id": "ny-test:2", "reach": SLOW, "status": "yellow", "rule": "caution", "short": "SSO ended",
                 "hours_since_start": 30.0, "flow_basis": "NHDPlus mean annual", "segments": [NOBAND]},
                {"event_id": "il-test:3", "reach": SHORE, "status": "red", "rule": "ongoing", "short": "CSO",
                 "hours_since_start": 1.0, "segments": [NOBAND, NOBAND]}]}


BY_EVENT = {"pa-test:1": {"started_at": "2026-11-07T08:00:00Z"}, "ny-test:2": {"started_at": "2026-11-06T06:00:00Z",
                                                                                 "fixture": True},
            "il-test:3": {"started_at": "2026-11-07T11:00:00Z"}}
LIVE = {"PA", "NY", "IL", "MA"}


def render(st: dict, by_event: dict, cache: dict, live: set = LIVE) -> dict:
    """{"reaches.geojson", "reach-paths.geojson", "reaches/<st>.geojson"...: the bytes as text} for the fixture."""
    from build import reaches as R
    from export import build as X
    orig = R.cap_km
    R.cap_km = lambda rules=None: 40.0
    try:
        feats, paths = X.reach_features(st, by_event, cache)
    finally:
        R.cap_km = orig
    out = {"reaches.geojson": json.dumps({"type": "FeatureCollection", "features": feats}, sort_keys=False),
           "reach-paths.geojson": json.dumps({"type": "FeatureCollection", "features": paths}, sort_keys=False)}
    by_state, _ = X.reaches_by_state(feats, paths, st, cache, live)
    with tempfile.TemporaryDirectory() as d:
        X.write_reach_state_files(by_state, out_dir=Path(d), built=BUILT)
        for p in sorted((Path(d) / "reaches").glob("*")):
            out[f"reaches/{p.name}"] = p.read_text()
    return out


if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(render(status(), BY_EVENT, cached()), indent=1, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN}")
