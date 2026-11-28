"""The waters follow-up of 2026-11-28 (research/registry/waters-followup-2026-11-28.md): water records for receiving
waters a permit or an operator names for a registered outfall and no record had, built as hand records
(ingest/waters_from_nhd.py HAND) from the USGS NHD high-resolution lines at the outfalls' own points, with the name
from a cited public source. Data tests on the files as committed and the resolver's rules; no network.
Run from pipeline/: python -m pytest tests/test_waters_followup.py -q
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import event  # noqa: E402
from ingest import waters_from_nhd as W  # noqa: E402

FOLLOWUP = "-followup-2026-11-28.json"

# slug: (name, kind, state, GNIS id or None, the outfall point the record was built at (lat, lon), at most this far)
RECORDS = {
    "st-louis-creek-mi": ("St. Louis Creek", "stream", "MI", None, (47.2339669, -88.428109), 25),
    "spring-creek-oh": ("Spring Creek", "stream", "OH", None, (41.436564, -81.682069), 25),
    "wolf-creek-garfield-heights-oh": ("Wolf Creek", "stream", "OH", None, (41.42304, -81.599487), 25),
    "green-creek-oh": ("Green Creek", "stream", "OH", None, (41.552446, -81.543681), 25),
    "shaw-brook-oh": ("Shaw Brook", "stream", "OH", None, (41.552456, -81.599685), 50),
    "bloody-run-oh": ("Bloody Run", "stream", "OH", None, (39.1794444, -84.4866667), 50),
    "longfellow-creek-wa": ("Longfellow Creek", "stream", "WA", None, (47.5291595, -122.3638), 25),
}


@pytest.fixture(scope="module")
def waters():
    return S.load_waters()


@pytest.fixture(scope="module")
def resolver(waters):
    S._STATES = S.derive_states(waters, S.load_rules())
    return S.make_resolver(waters)


def _metres(geom: dict, lat: float, lon: float) -> float:
    from shapely.geometry import Point, shape
    k = math.cos(math.radians(lat))
    g = shape(geom)
    from shapely import transform
    import numpy as np
    m = transform(g, lambda a: np.column_stack([(a[:, 0] - lon) * 111320 * k, (a[:, 1] - lat) * 110540]))
    return m.distance(Point(0, 0))


@pytest.mark.parametrize("slug", sorted(RECORDS))
def test_each_record_is_a_hand_record_from_the_nhd_lines_at_its_outfall(waters, slug):
    name, kind, state, gnis, (lat, lon), within = RECORDS[slug]
    w = waters[slug]
    assert (w["name"], w["kind"], w["state"], w.get("hand"), w["source"]) == (name, kind, state, True, "nhd")
    assert w.get("gnis_id") == gnis
    assert w["note"].startswith("USGS National Hydrography Dataset, high resolution") and "Hand record:" in w["note"]
    assert _metres(S.water_geometry(slug, waters), lat, lon) <= within


@pytest.mark.parametrize("slug", sorted(RECORDS))
def test_each_record_has_its_spec_scoped_to_the_follow_up_names_file(slug):
    name, _, state, gnis, (lat, lon), _ = RECORDS[slug]
    spec = [h for h in W.HAND if h["state"] == state and h["name"] == name and str(h.get("names_file", "")).endswith(FOLLOWUP)]
    assert len(spec) == 1
    h = spec[0]
    assert h.get("service") == "hr" and (h.get("gnis_id") == gnis if gnis else h.get("pids"))
    assert h["near"] == (lon, lat)
    assert "https://" in h["why"] or "NEORSD's CSO alerts map" in h["why"]       # the name's source, cited


@pytest.mark.parametrize("text,permit,oid,slug", [
    ("St. Louis Creek", "MI0043982", "001", "st-louis-creek-mi"),
])
def test_michigans_report_places_by_its_own_text_on_the_new_record(resolver, text, permit, oid, slug):
    ev = event(source_id="mi-egle-mienviro-cso-sso-list", source_record_id=f"{permit}-{oid}", event_type="cso",
               status="ended", waterbody_text=text, npdes_permit=permit, outfall_id=oid, raw={"state": "MI"})
    pl = resolver.resolve(ev)
    assert pl["water_slugs"] == [slug], pl


# ------------------------------------------------------------------ the outfalls tied to the new records

TIED = {("MI0043982", "001"): "st-louis-creek-mi", ("OH0043991", "059"): "spring-creek-oh",
        ("OH0043991", "257"): "spring-creek-oh", ("OH0043991", "249"): "wolf-creek-garfield-heights-oh",
        ("OH0043991", "256"): "green-creek-oh", ("OH0043991", "232"): "shaw-brook-oh",
        ("OH0105457", "181"): "bloody-run-oh", ("WA0031682", "168"): "longfellow-creek-wa",
        ("WA0031682", "169"): "longfellow-creek-wa", ("WA0031682", "170"): "longfellow-creek-wa"}


@pytest.mark.parametrize("permit,oid", sorted(TIED))
def test_a_report_of_a_tied_outfall_places_on_its_new_record(resolver, permit, oid):
    ev = event(source_id="test-registry", source_record_id=f"{permit}-{oid}", event_type="cso", status="ended",
               npdes_permit=permit, outfall_id=oid, raw={"state": permit[:2]})
    pl = resolver.resolve(ev)
    assert pl["water_slugs"] == [TIED[(permit, oid)]] and pl["water_match"] == "outfall_registry", pl


def test_the_ties_rest_on_the_hand_corrections_and_the_washington_gate_table():
    from common import load_outfall_registry
    loaded = {(o["npdes_permit"], o["outfall"]): o for o in load_outfall_registry(provisional=False)}
    for k, slug in TIED.items():
        o = loaded[k]
        by = "scripts/wa_gate_ties.py" if k[0] == "WA0031682" else "data/outfall-water-corrections.json"
        assert o["water_slug"] == slug and o["water_matched_by"].startswith(by), k


@pytest.mark.parametrize("permit,oid", [("OH0043991", "230"), ("OH0043991", "231"), ("NJ0108758", "026"),
                                        ("NY0213934", "002"), ("OH0023833", "047"), ("OH0023833", "055")])
def test_the_waters_left_without_a_record_stay_untied(resolver, permit, oid):
    """Dugway Brook (no published line reaches the outfalls), Queen Ditch (no line within 300 m), the tributary of
    Little Snake Creek (4 km from the creek) and Akron's Ohio Canal and Camp Brook (no named line) are left."""
    ev = event(source_id="test-registry", source_record_id=f"{permit}-{oid}", event_type="cso", status="ended",
               npdes_permit=permit, outfall_id=oid, raw={"state": permit[:2]})
    assert resolver.resolve(ev)["water_slugs"] == []


# ------------------------------------------------------------------ Michigan permits with no town on record

def test_the_two_michigan_permits_take_their_holders_town():
    """EGLE's MiEnviro CSO/SSO List names the City of Manistee as responsible party for 3112a-0142 (Manistee CM) and
    Crystal Falls for GW1810192 (Crystal Falls WWTP): each permit joins its city's row (scripts/add_mi_operators.py's
    owner-key rule)."""
    towns = S.load_discharger_towns()
    assert towns["3112a-0142"] == ["Manistee"] and towns["GW1810192"] == ["Crystal Falls"]


def test_manistees_collection_system_reports_go_to_the_lake_at_manistee(resolver):
    ev = event(source_id="mi-egle-mienviro-cso-sso-list", source_record_id="3112a-0142-018", event_type="cso",
               status="ended", waterbody_text="Manistee Lake", npdes_permit="3112a-0142", outfall_id="018",
               raw={"state": "MI"})
    assert resolver.resolve(ev)["water_slugs"] == ["manistee-lake-mi"]


# ------------------------------------------------------------------ common names and other localities (review P2)

def _no_point(text, state, county=None, permit=None):
    raw = {"state": state, **({"county": county} if county else {})}
    return event(source_id="test-no-point", source_record_id=f"{state}-{text}-{county}", event_type="sso",
                 status="ended", waterbody_text=text, npdes_permit=permit, raw=raw)


@pytest.mark.parametrize("slug", ["big-beaver-creek-mi", "holly-drain-mi", "crystal-creek-mi", "bradshaw-drain-mi"])
def test_the_four_michigan_common_names_are_not_records(waters, slug):
    """Michigan is not a county state: a report with no point naming 'Crystal Creek' in Oceana County would take the
    Lapeer County record. Each served one report, so the records were left out (summary: a statewide name with no
    locality check)."""
    assert slug not in waters
    assert not [h for h in W.HAND if h["state"] == "MI" and str(h.get("names_file", "")).endswith(FOLLOWUP)
                and h.get("gnis_id")]


def test_a_crystal_creek_report_from_oceana_county_is_not_placed_on_lapeers_creek(resolver):
    pl = resolver.resolve(_no_point("Crystal Creek", "MI", "Oceana"))
    assert "crystal-creek-mi" not in pl["water_slugs"], pl


@pytest.mark.parametrize("text,county,slug", [("Spring Creek", "Medina", "spring-creek-oh"),
                                              ("Spring Creek", "Hamilton", "spring-creek-oh"),
                                              ("Bloody Run", "Licking", "bloody-run-oh"),
                                              ("Bloody Run", "Cuyahoga", "bloody-run-oh"),
                                              ("Green Creek", "Sandusky", "green-creek-oh"),
                                              ("Shaw Brook", "Lake", "shaw-brook-oh")])
def test_an_ohio_report_from_another_county_is_not_placed_on_the_new_record(resolver, text, county, slug):
    """Ohio is a county state with a county field (status.COUNTY_STATES, COUNTY_FIELD_STATES): a name goes only to a
    record reaching the county of the report's point or its own county field."""
    assert "OH" in S.COUNTY_STATES and "OH" in S.COUNTY_FIELD_STATES
    pl = resolver.resolve(_no_point(text, "OH", county))
    assert slug not in pl["water_slugs"], pl


@pytest.mark.parametrize("text,county,slug", [("Spring Creek", "Cuyahoga", "spring-creek-oh"),
                                              ("Bloody Run", "Hamilton", "bloody-run-oh")])
def test_an_ohio_report_from_the_records_county_is_placed_on_it(resolver, text, county, slug):
    assert resolver.resolve(_no_point(text, "OH", county))["water_slugs"] == [slug]


@pytest.mark.parametrize("text,permit,oid,slug", [("Spring Creek", "OH0043991", "059", "spring-creek-oh"),
                                                  ("Spring Creek", "OH0043991", "257", "spring-creek-oh"),
                                                  ("Bloody Run", "OH0105457", "181", "bloody-run-oh")])
def test_neorsds_and_cincinnatis_named_reports_still_place(resolver, text, permit, oid, slug):
    ev = event(source_id="test-registry", source_record_id=f"{permit}-{oid}", event_type="cso", status="ended",
               waterbody_text=text, npdes_permit=permit, outfall_id=oid, raw={"state": "OH"})
    assert resolver.resolve(ev)["water_slugs"] == [slug]


@pytest.mark.parametrize("slug,names", [("st-louis-creek-mi", ("St. Louis Creek", "St Louis Creek", "Saint Louis Creek")),
                                        ("longfellow-creek-wa", ("Longfellow Creek",))])
def test_the_records_kept_in_states_without_a_county_check_are_the_only_ones_of_their_name(resolver, slug, names):
    """Michigan and Washington are not county states: St. Louis Creek and Longfellow Creek stay because no other water
    of the name is known in the state (the NHD high-resolution flowlines, whose names are GNIS's, carry none in
    Michigan or Washington; research/registry/waters-followup-2026-11-28.md), so the statewide name catches no other
    locality's report. A report with a point is still held to the placement guard's distance."""
    st = resolver.waters[slug]["state"]
    for n in map(S.norm_name, names):
        assert sorted(set(resolver.names.get((st, n), []) + resolver.exact.get((st, n), []))) == [slug], n
    far = event(source_id="test-point", source_record_id=f"{slug}-far", event_type="sso", status="ended",
                waterbody_text=resolver.waters[slug]["name"], raw={"state": st},
                lat=46.0 if st == "MI" else 47.66, lon=-84.0 if st == "MI" else -117.42)
    assert slug not in resolver.resolve(far)["water_slugs"]
