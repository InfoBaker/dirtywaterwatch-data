"""Houston text points; real rows trimmed to coordinates, manholes and location types."""
import json
import math

import pytest

from build import status as S
from build.redact import redactor_for
from export import build as X
from ingest.generic import runner as R


# TCEQ incident ids from the 2026-11-14 export. No addresses or personal fields.
REAL_ROWS = [
    ("462666", "RN101611069", "(3163210,13875092) / Manhole / Backyard. Manhole TW001009",
     "TW001009", "Backyard", 29.84787919551619, -95.23062219351459),
    ("462056", "RN100217603", "(3084994,13856284)/Manhole/Street. Manhole IA034044",
     "IA034044", "Street", 29.802886073224176, -95.47902970511512),
    ("458019", "RN101607174", "(3045421,13829898) / Manhole / Parking Lot. Manhole AR001214",
     "AR001214", "Parking Lot", 29.73357297411615, -95.60616958241563),
]


def record(description=None, rn="RN100217603", rid="462056"):
    _, block = R.load_source("tx-tceq-sso-opendata")
    rows = [{"incident_number": rid, "regulated_entity_number": rn,
             "incident_description": description or REAL_ROWS[1][2], "county": "HARRIS",
             "material_type": "Sewage", "start_date": "2026-08-01T00:00:00",
             "receiving_water_body": "NOT PROVIDED"}]
    recs, _ = R.build("tx-tceq-sso-opendata", block, rows, "2026-11-14T23:37:00Z", (), None)
    assert len(recs) == 1
    return recs[0]


@pytest.mark.parametrize("x,y,lat,lon", [
    (3163210, 13875092, 29.84787919551619, -95.23062219351459),
    (3084994, 13856284, 29.802886073224176, -95.47902970511512),
    (3045421, 13829898, 29.73357297411615, -95.60616958241563),
    (3072179, 13817664, 29.697782248118937, -95.52303886892352),
    (1968500, 13123333.333, 27.83333333333331, -99.0),
    (3020000, 13780000, 29.598409235198098, -95.69068693439247),
    (3170000, 13880000, 29.860765354968596, -95.20871250644039),
    (3176813, 13956762, 30.071126387990905, -95.17931928407218),
])
def test_lambert_against_independent_pyproj_constants_under_one_meter(x, y, lat, lon):
    # Computed 2026-11-24 in /private/tmp/houston-control-venv, not the pipeline:
    # pyproj 3.8.0 / PROJ 9.8.1, TransformerGroup(2278,4326,always_xy=True).transformers[0].
    # Inverse SPCS83 + NAD83 to WGS 84 (1), EPSG:1188, nominal datum accuracy 4 m.
    # This tests numerical conversion error, NOT geodetic or source-location accuracy.
    from geo.stateplane import texas_south_central_to_wgs84
    got_lat, got_lon = texas_south_central_to_wgs84(x, y)
    meters = math.hypot((got_lat - lat) * 111320,
                        (got_lon - lon) * 111320 * math.cos(math.radians(lat)))
    assert meters < 1


@pytest.mark.parametrize("rid,rn,text,manhole,location,lat,lon", REAL_ROWS)
def test_real_houston_manholes(rid, rn, text, manhole, location, lat, lon):
    e = record(text, rn, rid)
    assert (e["lat"], e["lon"]) == pytest.approx((lat, lon), abs=1e-10)
    assert e["raw"]["row"]["incident_description"] == text
    assert e["coord_precision_m"] is None
    assert e["coord_source"] == "source"
    p = e["raw"]["_place_from_operator_coords"]
    assert p["manhole_id"] == manhole and p["location_type"] == location
    assert p["place_tier"] == 1 and p["source_crs"] == "EPSG:2278"
    assert p["place_method"] == "operator_coordinates"
    assert p["place_precision_m"] is None
    assert "operator's coordinates" in p["place_basis"] and "we converted" in p["place_basis"]
    assert e["raw"]["_placement"] == "named_water_only"


@pytest.mark.parametrize("pair", ["(1,1)", "(0,0)", "(13856284,3084994)",
                                 "(940308,4223395)", "(3084994,99999999)",
                                 "(9999999,13856284)", "(nan,inf)",
                                 "(3084994,13856284) (3045421,13829898)"])
def test_placeholder_wrong_units_swapped_axes_and_conflicting_pairs_rejected(pair):
    e = record(pair + "/Manhole/Street")
    assert e["lat"] is None and e["lon"] is None
    assert "_place_from_operator_coords" not in e["raw"]


def test_spaced_digits_and_repeated_identical_pair():
    e = record("(3068393,1386235 2)/Manhole/Street. (3068393,13862352)")
    assert e["lat"] is not None


def test_other_operator_is_not_assumed_to_use_houstons_projection():
    e = record(rn="RN000000000")
    assert e["lat"] is None and "_place_from_operator_coords" not in e["raw"]


def test_rejection_reason_survives_record_build():
    assert "outside Houston" in record("(1,1)/Manhole/Street")["raw"]["_place_coords_rejected"]


def test_existing_source_point_is_not_replaced():
    from ingest import tx_transforms as T
    e = record()
    rec = {"lat": 29.7, "lon": -95.4, "discharger_id": "tx-city-of-houston"}
    notes = {}
    T.houston_operator_coords({"incident_description": REAL_ROWS[1][2]}, rec, notes)
    assert (rec["lat"], rec["lon"]) == (29.7, -95.4) and not notes


@pytest.mark.parametrize("location", ["Backyard", "Front Yard", "Side Yard", "Side of Building",
                                      "Private Property", "Backlot Easement", "Street", "Parking Lot"])
def test_operator_points_and_original_pair_are_preserved(location):
    text = "(3084994,13856284)/Manhole/" + location
    e = record(text)
    assert (e["lat"], e["lon"]) == pytest.approx((29.802886073224176, -95.47902970511512), abs=1e-10)
    assert e["raw"]["row"]["incident_description"] == text
    public = X.public_record(e, {}, redactor_for([e]))
    assert public["raw"]["row"]["incident_description"] == text
    for output in (public, X.slim_event(public)):
        assert (output["lat"], output["lon"]) == (e["lat"], e["lon"])


def test_basis_survives_full_and_slim_export():
    e = record()
    public = X.public_record(e, {}, redactor_for([e]))
    for output in (public, X.slim_event(public)):
        assert output["place_tier"] == 1
        assert output["place_method"] == "operator_coordinates"
        assert output.get("place_precision_m") is None
        assert output["place_basis"] == (
            "Location: the operator's coordinates in the report, which we converted from Texas State "
            "Plane South Central to latitude and longitude.")
    # The shared compact index uses five decimals for every source point.
    assert X.index_obj(public)["lat"] == round(e["lat"], 5)


def resolver(monkeypatch):
    from tests.test_tx_placement import resolver as tx_resolver, REGISTRY
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"TX"})
    res = tx_resolver("buffalo-bayou-tx", registry=REGISTRY)
    monkeypatch.setattr(res, "by_point", lambda *args: (10, "buffalo-bayou-tx"))
    return res


def test_operator_point_can_place_on_water_without_plant_fallback(monkeypatch):
    res = resolver(monkeypatch)
    e = record()
    pl = res.resolve(e)
    assert pl["water_match"] == "geometry" and pl["water_slugs"] == ["buffalo-bayou-tx"]
    assert "operator's coordinates" in pl["note"]
    monkeypatch.setattr(res, "by_point", lambda *args: None)
    assert res.resolve(e)["water_slugs"] == []


def test_named_water_keeps_priority_over_operator_point(monkeypatch):
    res = resolver(monkeypatch)
    e = record()
    e["waterbody_text"] = "Buffalo Bayou"
    e.update(lat=29.7558, lon=-95.2979)
    monkeypatch.setattr(res, "by_point", lambda *args: (0, "different-water-tx"))
    pl = res.resolve(e)
    assert pl["water_match"] == "name" and pl["water_slugs"] == ["buffalo-bayou-tx"]


def test_unmatched_named_water_is_not_replaced_by_another_water_at_the_point(monkeypatch):
    res = resolver(monkeypatch)
    e = record()
    e["waterbody_text"] = "Unmatched Fixture Creek"
    assert res.resolve(e)["water_slugs"] == []


def test_point_with_no_match_does_not_claim_the_source_gave_no_location(monkeypatch):
    res = resolver(monkeypatch)
    monkeypatch.setattr(res, "by_point", lambda *args: None)
    pl = res.resolve(record())
    assert "source gives no location" not in str(pl)


@pytest.mark.parametrize("flow", ["Contained On Site, not within 5 ft. of Bayou", "Contained onsite",
                                 "Storm Sewer - contained"])
def test_contained_description_never_places_or_colors_water(monkeypatch, flow):
    res = resolver(monkeypatch)
    e = record(REAL_ROWS[0][2] + ". " + flow)
    pl = res.resolve(e)
    assert pl["water_slugs"] == [] and pl["no_receiving_water"]
    assert e["lat"] is not None


def test_not_contained_is_not_read_as_contained(monkeypatch):
    e = record(REAL_ROWS[1][2] + ". Storm Sewer (not contained).")
    assert e["raw"].get("reached_water") is not False
    assert resolver(monkeypatch).resolve(e)["water_match"] == "geometry"


@pytest.mark.parametrize("old_version", [2, 3])
def test_unchanged_source_batch_is_reprocessed_for_coordinate_parser(tmp_path, monkeypatch, old_version):
    from ingest.generic import socrata
    _, block = R.load_source("tx-tceq-sso-opendata")
    path = tmp_path / "events.json"
    path.write_text(json.dumps({"ok": True, "records": [record()],
                                "meta": {"table_version": "1", "parser_version": old_version}}))
    monkeypatch.setattr(socrata, "current_version", lambda *args: "1")
    assert R.keep_unchanged("tx-tceq-sso-opendata", block, path, "2026-11-24T12:00:00Z") is None


def test_coordinate_metadata_and_public_contact_fields_pass_through():
    from common import strip_personal
    p = record()["raw"]["_place_from_operator_coords"]
    raw = {"_place_from_operator_coords": {**p, "operator": "Fixture operator", "extra": "source value"},
           "reporter": {"name": "Fixture reporter", "phone": "512-555-0142"}}
    assert strip_personal(raw) == raw
    text_value = {"_place_from_operator_coords": "source value", "operator": "Fixture operator"}
    assert strip_personal(text_value) == text_value
