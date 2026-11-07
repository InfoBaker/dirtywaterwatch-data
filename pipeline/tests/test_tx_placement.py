"""Texas's placement (final audit 2026-11-07): a TCEQ report is placed only on the water it names (raw._placement
named_water_only), never on its permit's outfalls' water (P1-1); a name several counties share goes only to a record
reaching the report's own county, read from its county field since TCEQ gives no point (P1-2). Records are the
water batch's (boxes only, tests/fixtures/tx_same_named_waters.json). Every other state is unchanged."""
import copy
import json
from pathlib import Path

import pytest

from build import status as S

WATERS = json.loads((Path(__file__).parent / "fixtures" / "tx_same_named_waters.json").read_text())
REGISTRY = [{"npdes_permit": "TX0096172", "outfall": "001", "water_slug": "buffalo-bayou-tx", "match": "geometry",
             "distance_m": 120, "outfall_kind": "plant", "lat": 29.7558, "lon": -95.2979, "state": "TX",
             "receiving_water_echo": "BUFFALO BAYOU TIDAL"}]


@pytest.fixture(autouse=True)
def texas_live(monkeypatch):
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"TX"})


def resolver(*slugs, registry=()):
    return S.Resolver({s: copy.deepcopy(WATERS[s]) for s in slugs}, list(registry), placement_rules={})


def report(rid, text, county, permit=None, named_only=True, state="TX"):
    raw = {"state": state, "county": county}
    if named_only:
        raw["_placement"] = "named_water_only"
    return {"event_id": f"tx-tceq-sso-opendata:{rid}", "source_id": "tx-tceq-sso-opendata", "source_record_id": rid,
            "event_type": "sso", "status": "ended", "waterbody_text": text, "water_slugs": [], "water_match": "none",
            "lat": None, "lon": None, "npdes_permit": permit, "outfall_id": None, "raw": raw,
            "time_precision": "day", "started_at": "2026-08-03T00:00:00-05:00"}


def test_a_report_naming_no_water_is_not_put_on_its_plants_water():
    res = resolver("buffalo-bayou-tx", registry=REGISTRY)
    plain = res.resolve(report("x1", None, "Harris County", "TX0096172", named_only=False))
    assert plain["water_slugs"] == ["buffalo-bayou-tx"]                     # the registry would place it
    r = res.resolve(report("x2", None, "Harris County", "TX0096172"))
    assert r["water_slugs"] == [] and r["unplaced_reason"] == S.NAMED_ONLY_NONE
    seg = res.resolve(report("x3", None, "Harris County", "TX0096172") | {"waterbody_text": None})
    assert seg["water_slugs"] == []


def test_a_report_naming_its_water_is_placed_on_it():
    r = resolver("buffalo-bayou-tx", registry=REGISTRY).resolve(report("x4", "Buffalo Bayou", "Harris County",
                                                                       "TX0096172"))
    assert r["water_slugs"] == ["buffalo-bayou-tx"] and r["water_match"] == "name"


def test_the_county_field_names_the_county():
    assert S.named_county("TX", "Lubbock County")[1] == "Lubbock County"
    assert S.named_county("TX", "COMAL")[1] == "Comal County"
    assert S.named_county("TX", "Nowhere County") is None


@pytest.mark.parametrize("text,county", [("Canyon Lake System", "Lubbock County"), ("Canyon Lake", "Lubbock County")])
def test_lubbocks_canyon_lake_system_is_not_comal_countys_canyon_lake(text, county):
    res = resolver("canyon-lake-tx")
    r = res.resolve(report("x5", text, county))
    assert r["water_slugs"] == []
    slugs, note, _ = res.by_name(text, "TX", None, None, report("x5", text, county))
    assert slugs == [] and (note is None or "Lubbock County" in note)


def test_comal_countys_report_keeps_canyon_lake():
    r = resolver("canyon-lake-tx").resolve(report("x6", "Canyon Lake", "Comal County"))
    assert r["water_slugs"] == ["canyon-lake-tx"]


def test_tarrants_johnson_creek_is_not_marion_countys_reservoir():
    r = resolver("johnson-creek-reservoir-tx").resolve(report("x7", "Johnson Creek Reservoir", "Tarrant County"))
    assert r["water_slugs"] == []
    r = resolver("johnson-creek-reservoir-tx").resolve(report("x8", "Johnson Creek Reservoir", "Marion County"))
    assert r["water_slugs"] == ["johnson-creek-reservoir-tx"]


def test_other_states_are_unchanged():
    def as_state(st):
        ws = {"canyon-lake-x": {**copy.deepcopy(WATERS["canyon-lake-tx"]), "slug": "canyon-lake-x", "state": st}}
        res = S.Resolver(ws, [], placement_rules={})
        return res.by_name("Canyon Lake", st, None, None, report("x", "Canyon Lake", "Lubbock County", state=st))[0]
    with_rule = as_state("MS")
    saved_c, saved_f = dict(S.COUNTY_STATES), set(S.COUNTY_FIELD_STATES)
    try:
        S.COUNTY_STATES.clear()
        S.COUNTY_FIELD_STATES.clear()
        without = as_state("MS")
    finally:
        S.COUNTY_STATES.update(saved_c)
        S.COUNTY_FIELD_STATES.update(saved_f)
    assert with_rule == without == ["canyon-lake-x"]
    # a record without the flag is placed by the registry as before (every other source)
    assert not S.named_water_only({"raw": {}})


def test_the_names_pass_keeps_a_row_per_county():
    from ingest import waters_from_nhd as N
    res = resolver("canyon-lake-tx")
    slugs, at = N.has_record_at(res, "Canyon Lake", "TX", [], [], per_place=True, county="Lubbock County")
    assert slugs == []
    slugs, at = N.has_record_at(res, "Canyon Lake", "TX", [], [], per_place=True, county="Comal County")
    assert slugs == ["canyon-lake-tx"]


def test_a_no_end_report_is_cautioned_from_the_day_it_began():
    from datetime import UTC, datetime, timedelta
    ev = report("x9", "Buffalo Bayou", "Harris County") | {"status": "unknown", "ended_at": None,
                                                           "reported_at": "2026-08-10T00:00:00-05:00"}
    ev["raw"]["time_zone"] = "America/Chicago"
    ivs = S.event_intervals(ev, "TX", datetime(2026, 8, 4, tzinfo=UTC), None, S.load_rules())
    first = ivs[0]
    assert first["rule"] == "day_start_caution" and first["start"] == S.parse_time("2026-08-03T00:00:00-05:00")
    assert first["end"] - first["start"] == timedelta(hours=72)
