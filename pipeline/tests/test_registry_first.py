"""Registry-first placement and watershed labels (build/status.py, owner 2026-11-03, docs/next-steps.md 2g):
a report whose outfall the outfall registry maps to a water is placed on that water before any name matching (the
note names the registry's match), unless its own text names another water; a registry row the registry pass has
matched keeps its water (or its stated lack of one); a watershed label (HUC-12 name, MDE basin label, "watershed",
"<stream> basin", "<stream> drainage") is never read as a water name. Reports with no registered outfall keep the
placement guard.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from build import status as S  # noqa: E402
from common import event  # noqa: E402

BY_PASS = "ingest.outfall_waters (2026-11-03)"


def w(slug, name, kind, coords, state="MA", towns=(), aliases=()):
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": list(towns),
                  "aliases": list(aliases), "bbox": [min(xs), min(ys), max(xs), max(ys)],
                  "geometry": {"type": "LineString", "coordinates": coords}}


WATERS = dict([
    # two records of one name: the registry says which one the outfall is on
    w("hudson-river-nj", "Hudson River", "river", [[-74.03, 40.80], [-74.00, 40.85]], "NJ", ["Hoboken"]),
    w("hudson-river-jersey-city-nj", "Hudson River", "river", [[-74.05, 40.70], [-74.03, 40.73]], "NJ",
      ["Jersey City"]),
    w("clarks-cove-ma", "Clarks Cove", "bay", [[-70.93, 41.59], [-70.92, 41.60]], towns=["New Bedford"],
      aliases=["Clark Cove"]),
    w("buzzards-bay-ma", "Buzzards Bay", "bay", [[-70.95, 41.55], [-70.90, 41.58]], towns=["New Bedford"]),
    w("charles-river-ma", "Charles River", "river", [[-71.12, 42.35], [-71.07, 42.36]], towns=["Boston"],
      aliases=["Charles River Basin"]),
    w("saugus-river-ma", "Saugus River", "river", [[-71.00, 42.45], [-70.98, 42.47]], towns=["Saugus"]),
    w("gwynns-falls-md", "Gwynns Falls", "stream", [[-76.70, 39.30], [-76.65, 39.28]], "MD", ["Baltimore"]),
    w("dead-run-md", "Dead Run", "stream", [[-76.72, 39.31], [-76.70, 39.30]], "MD", ["Baltimore"]),
    w("herring-run-md", "Herring Run", "stream", [[-76.57, 39.33], [-76.55, 39.31]], "MD", ["Baltimore"]),
    w("oxon-run-md", "Oxon Run", "stream", [[-76.98, 38.83], [-76.96, 38.82]], "MD", ["Oxon Hill"]),
    w("braddock-run-md", "Braddock Run", "stream", [[-78.82, 39.64], [-78.80, 39.65]], "MD", ["LaVale"]),
    w("potomac-river-md", "Potomac River", "river", [[-78.76, 39.62], [-77.0, 38.9]], "MD", ["Cumberland"]),
    w("paerdegat-basin-ny", "Paerdegat Basin", "bay", [[-73.91, 40.62], [-73.90, 40.63]], "NY", ["Brooklyn"]),
    w("otter-creek-vt", "Otter Creek", "river", [[-73.26, 44.16], [-73.25, 44.17]], "VT", ["Vergennes"]),
])

REG_NJ = {"npdes_permit": "NJ0108723", "outfall": "016", "state": "NJ", "city": "JERSEY CITY",
          "receiving_water_echo": "Hudson River", "lat": 40.715, "lon": -74.04, "water_slug": "hudson-river-jersey-city-nj",
          "water_name": "Hudson River", "match": "name_only", "distance_m": 2473,
          "water_match": "name: its receiving water 'Hudson River' by name; Hudson River (hudson-river-jersey-city-nj)",
          "water_matched_by": BY_PASS, "_file": "data/outfalls-mid-atlantic.json"}
REG_NB = {"npdes_permit": "MA0100781", "outfall": "003", "state": "MA", "city": "NEW BEDFORD",
          "receiving_water_echo": None, "lat": 41.565, "lon": -70.92, "water_slug": "buzzards-bay-ma",
          "match": "geometry", "distance_m": 0, "water_match": "EPA's point lies 0 m from Buzzards Bay",
          "water_matched_by": "scripts/match_outfalls.py (2026-11-01)", "_file": "data/outfalls-ne.json"}
REG_MWRA = [{"npdes_permit": "MA0103284", "outfall": "C01", "outfall_name": "MWR201: Cottage Farm", "state": "MA",
             "receiving_water_echo": "ATLANTIC OCEAN (BOSTON HARBOR)", "lat": 42.3526, "lon": -71.1111,
             "water_slug": "charles-river-ma", "match": "geometry", "distance_m": 19,
             "water_match": "EPA's point lies 19 m from Charles River", "water_matched_by": BY_PASS,
             "_file": "data/outfalls-ne.json"},
            {"npdes_permit": "MA0100137", "outfall": "C01", "outfall_name": "GREENFIELD RD NEAR WPCF", "state": "MA",
             "receiving_water_echo": "Connecticut River", "lat": 42.58, "lon": -72.57, "water_slug": None,
             "match": "none", "_file": "data/outfalls-ne.json"}]
REG_LAVALE = {"npdes_permit": "MD0067547", "outfall": "001", "state": "MD", "city": "LAVALE",
              "receiving_water_echo": "UPPER POTOMAC RIVER", "lat": 39.645, "lon": -78.81, "water_slug": "braddock-run-md",
              "match": "geometry", "distance_m": 120,
              "water_match": "permit's receiving water: 'UPPER POTOMAC RIVER' is a basin label; the permit's ...",
              "water_matched_by": BY_PASS, "_file": "data/outfalls-mid-atlantic.json"}
REG_HUC = {"npdes_permit": "MA0101192", "outfall": "070", "state": "MA", "city": "BOSTON",
           "receiving_water_echo": "Charles River-Frontal Boston Harbor", "lat": None, "lon": None, "water_slug": None,
           "match": "none", "no_water_reason": "'Charles River-Frontal Boston Harbor' is a USGS HUC-12 watershed name",
           "water_match": "none: 'Charles River-Frontal Boston Harbor' is a USGS HUC-12 watershed name",
           "water_matched_by": BY_PASS, "_file": "data/outfalls-ne.json"}
ROWS = [REG_NJ, REG_NB, REG_LAVALE, REG_HUC, *REG_MWRA]


@pytest.fixture(autouse=True)
def _steps():
    saved, yields = dict(S.PLACE_STEPS), S.REGISTRY_YIELDS_TO_NAMED_WATER
    S.PLACE_STEPS.update(registry=True, relaxed_guard=True, no_receiving_water=True, outfall_ids=True,
                         multi_outfall=True, registry_first=True, watershed_labels=True)
    S._GEOM_CACHE.clear()
    S._STATES = {"MA", "NJ", "MD", "NY", "VT"}
    yield
    S.PLACE_STEPS.update(saved)
    S.REGISTRY_YIELDS_TO_NAMED_WATER = yields
    S._GEOM_CACHE.clear()
    S._STATES = None


def resolver(rows=ROWS):
    return S.Resolver(WATERS, [dict(r) for r in rows], {}, {}, {})


def ev(rid="1", **kw):
    kw.setdefault("event_type", "cso")
    kw.setdefault("status", "ended")
    return event(source_id=kw.pop("source_id", "test"), source_record_id=rid, **kw)


# ---------------------------------------------------------------- rule 1: the registry's water first

def test_the_registry_water_wins_over_the_name_of_the_report_and_the_note_names_the_registry_match():
    # the ingester read 'Hudson River' as the Hoboken record; the registry puts outfall 016 on Jersey City's
    pl = resolver().resolve(ev(npdes_permit="NJ0108723", outfall_id="016", waterbody_text="Hudson River",
                               water_slugs=["hudson-river-nj"], water_match="name"))
    assert pl["water_slugs"] == ["hudson-river-jersey-city-nj"] and pl["water_match"] == "outfall_registry"
    assert pl["note"].startswith("placed by outfall 016 of permit NJ0108723 (outfall registry): 016 to Hudson River "
                                 "(its registry water (name, 2473 m from the point; ingest.outfall_waters (2026-11-03)))")
    # status.py's own name matching too (no ingester slug), and the placement guard is not asked
    pl = resolver().resolve(ev("2", npdes_permit="NJ0108723", outfall_id="016", waterbody_text="Hudson River",
                               lat=40.84, lon=-74.01))
    assert pl["water_slugs"] == ["hudson-river-jersey-city-nj"] and pl["water_match"] == "outfall_registry"


def test_a_text_that_names_no_record_does_not_stop_the_registry():
    pl = resolver().resolve(ev(npdes_permit="NJ0108723", outfall_name="016", waterbody_text="Upper NY Bay"))
    assert pl["water_slugs"] == ["hudson-river-jersey-city-nj"]


def test_a_report_naming_another_water_keeps_it_and_the_note_records_the_registry():
    pl = resolver().resolve(ev(npdes_permit="MA0100781", outfall_id="NEW003", waterbody_text="CLARK COVE",
                               water_slugs=["clarks-cove-ma"], water_match="name"))
    assert pl["water_slugs"] == ["clarks-cove-ma"] and pl["water_match"] == "name"
    assert "the outfall registry gives outfall NEW003 of MA0100781 Buzzards Bay; not used, the report names " \
           "another water" in pl["note"]
    # ... and the registry's water when the report's text names none
    pl = resolver().resolve(ev("2", npdes_permit="MA0100781", outfall_id="NEW003"))
    assert pl["water_slugs"] == ["buzzards-bay-ma"] and pl["water_match"] == "outfall_registry"
    # the switch: the registry wins over every name
    S.REGISTRY_YIELDS_TO_NAMED_WATER = False
    pl = resolver().resolve(ev("3", npdes_permit="MA0100781", outfall_id="NEW003", waterbody_text="CLARK COVE",
                               water_slugs=["clarks-cove-ma"], water_match="name"))
    assert pl["water_slugs"] == ["buzzards-bay-ma"]


def test_a_registry_row_the_registry_pass_matched_keeps_its_water_or_its_lack_of_one():
    r = resolver()
    # MDE's basin label 'UPPER POTOMAC RIVER' was read as the Potomac's main stem; the registry says Braddock Run
    assert r.row_water(REG_LAVALE)[0] == "braddock-run-md"
    assert "its registry water (permit's receiving water, 120 m from the point" in r.row_water(REG_LAVALE)[1]
    # a HUC-12 name was read as the Charles River; the registry found no water for the outfall
    slug, how = r.row_water(REG_HUC)
    assert slug is None and how.startswith("the outfall registry gives it no water record")
    # without the step, the row is read again by its text (the old disagreement)
    S.PLACE_STEPS["registry_first"] = False
    S.PLACE_STEPS["watershed_labels"] = False
    assert resolver().row_water(REG_HUC)[0] == "charles-river-ma"


def test_an_outfall_name_id_joins_and_another_letter_prefix_does_not():
    r = resolver()
    assert [x["outfall"] for x in r.outfall_rows("MA0103284", "MWR201")] == ["C01"]     # its outfall name's id
    assert r.outfall_rows("MA0103284", "T01") == []                                      # Deer Island is not C01
    assert r.outfall_rows("MA0103284", "MWR001") == []
    assert [x["outfall"] for x in r.outfall_rows("MA0100137", "MON001")] == ["C01"]     # no id in its name: by number


def test_a_report_with_no_registered_outfall_keeps_the_placement_guard():
    # the Dead Run record is 300 km from the point: set aside, not placed
    pl = resolver().resolve(ev(npdes_permit="MD9999999", outfall_id="001", waterbody_text="Dead Run",
                               lat=39.65, lon=-76.0, raw={"state": "MD"}))
    assert pl["water_slugs"] == [] and pl["set_aside"][0]["water_slug"] == "dead-run-md"


def test_a_storm_drain_text_is_not_overruled_by_the_registry():
    # as by_registry: a text that names no water is not overruled by the outfall a report's outfall name gives
    pl = resolver().resolve(ev(npdes_permit="NJ0108723", outfall_name="016", waterbody_text="storm drain"))
    assert pl["water_slugs"] == [] and pl["no_receiving_water"]


# ---------------------------------------------------------------- rule 2: a watershed label is not a water name

@pytest.mark.parametrize("state,text,rest", [
    ("MA", "Charles River-Frontal Boston Harbor", None),                 # USGS HUC-12 names
    ("MA", "Outlet Saugus River-Frontal Broad Sound", None),
    ("MD", "UPPER POTOMAC RIVER", None),                                 # MDE basin labels
    ("MD", "Potomac River - Allegany County", None),
    ("MD", "Herring Run watershed", None),
    ("MD", "Oxon Run Basin", None),                                      # WSSC's sewer basins
    ("MD", "Little Falls Basin", None),
    ("NY", "Hudson River drainage", None),
    ("NY", "Croton Watershed", None),
    ("MD", "NA (Gwynns Falls watershed)", "NA"),
    ("MD", "Dead Run, in the Gwynn Falls watershed.", "Dead Run"),
    ("MD", "Tinkers Creek in the Piscataway Basin", "Tinkers Creek"),
    ("MD", "N/A (watershed is Dead Run, confluent to Gwynns Falls)", "N/A"),
    ("MD", "Basin 10- NW Branch", "NW Branch"),
])
def test_watershed_labels(state, text, rest):
    got, labels = resolver().watershed_labels(text, state)
    assert labels and got == rest


@pytest.mark.parametrize("state,text", [
    ("NY", "Paerdegat Basin"), ("NY", "Atlantic Basin"), ("NY", "Erie Basin"),       # basins that are waters
    ("MA", "CHARLES RIVER BASIN"),                                                  # a record's alias
    ("MA", "catch basin to Marblehead Harbor"), ("CT", "Catch Basin"),             # structures
    ("VT", "Otter Creek Basin below the falls in Vergennes"),                       # a place on the water
    ("NY", "Drainage ditch to Foster Brook"), ("CT", "drainage is upstream from west river"),
    ("ME", "SEBASTICOOK RIVER, EAST BRANCH"), ("MD", "Stormwater management basin"),
])
def test_not_watershed_labels(state, text):
    assert resolver().watershed_labels(text, state) == (text, [])


def test_a_label_is_never_read_as_a_water_name():
    r = resolver()
    assert r.by_name("Charles River-Frontal Boston Harbor", "MA", None, None)[0] == []
    assert r.by_name("Outlet Saugus River-Frontal Broad Sound", "MA", None, None)[0] == []
    assert r.by_name("UPPER POTOMAC RIVER", "MD", None, None)[0] == []
    assert r.by_name("Dead Run, in the Gwynn Falls watershed.", "MD", None, None)[0] == ["dead-run-md"]
    assert r.by_name("CHARLES RIVER BASIN", "MA", None, None)[0] == ["charles-river-ma"]
    assert r.by_name("Paerdegat Basin", "NY", None, None)[0] == ["paerdegat-basin-ny"]
    assert not r.mentions_water("Herring Run watershed", "MD")
    S.PLACE_STEPS["watershed_labels"] = False
    assert resolver().by_name("Herring Run watershed", "MD", None, None)[0] == ["herring-run-md"]


def test_a_report_whose_text_is_only_a_label_is_read_as_naming_no_water():
    pl = resolver().resolve(ev(npdes_permit="MD9999999", event_type="sso", waterbody_text="Herring Run watershed",
                               water_slugs=["herring-run-md"], water_match="name", raw={"state": "MD"}))
    assert pl["water_slugs"] == [] and not pl.get("no_receiving_water")              # unplaced, not "no water"
    assert "is a watershed label, not a water name" in pl["note"]
    assert "the ingester's Herring Run came from it" in pl["note"]
    # a label and a water: placed on the water only
    pl = resolver().resolve(ev("2", npdes_permit="MD9999999", event_type="sso", raw={"state": "MD"},
                               waterbody_text="Dead Run, in the Gwynns Falls watershed.",
                               water_slugs=["dead-run-md", "gwynns-falls-md"], water_match="name"))
    assert pl["water_slugs"] == ["dead-run-md"]


def test_a_label_text_with_a_registered_outfall_is_placed_by_the_registry():
    pl = resolver().resolve(ev(npdes_permit="MD0067547", outfall_id="001", waterbody_text="UPPER POTOMAC RIVER",
                               raw={"state": "MD"}))
    assert pl["water_slugs"] == ["braddock-run-md"] and pl["water_match"] == "outfall_registry"


def test_an_outfall_group_label_naming_another_water_counts_as_the_report_naming_it():
    rows = [{**REG_NB, "npdes_permit": "MA0100999", "outfall": o} for o in ("021", "024")]
    pl = resolver(rows).resolve(ev(npdes_permit="MA0100999", outfall_name="Clarks Cove CSOs: 021, 024"))
    assert pl["water_slugs"] == ["clarks-cove-ma"] and pl["water_match"] == "name"
    assert "not used, the report names another water" in pl["note"]
