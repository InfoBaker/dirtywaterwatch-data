"""Washington's go-live gates (2026-11-06): the NHD records tidied against openboatlaunch's extract, the King County and
Seattle outfalls tied by the operators' own lists (Ecology's permits WA0029181, WA0031682 and WA0029581, and Seattle
Public Utilities' CSO basin layer), the Census TIGER/Line records those lists need, and Puget Sound under the shoreline
model. Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_wa_gates.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _json(name):
    return json.loads((DATA / name).read_text())


def _nhd_wa():
    return [r for r in _json("waters-nhd.json")["waters"] if r.get("state") == "WA"]


def _obl_wa():
    return {r["slug"]: r for r in _json("waters-wa.json")["waters"]}


def test_no_washington_nhd_record_hides_behind_an_openboatlaunch_slug():
    """The tidy (waters_from_nhd --state WA --tidy) ran after openboatlaunch's extract: an NHD record that shared a
    slug with an openboatlaunch record was either the same water (dropped) or another one (renamed). Before it, 35
    shared a slug and the status build kept openboatlaunch's: Renton's Black River was read as the Black River
    near Olympia, 78 km away, and two King County South plant outfalls were tied to it."""
    obl = _obl_wa()
    shared = sorted(r["slug"] for r in _nhd_wa() if r["slug"] in obl)
    assert shared == []
    renton = [r for r in _nhd_wa() if r["slug"] == "black-river-renton-wa"]
    assert len(renton) == 1 and renton[0]["name"] == "Black River" and "Renton" in renton[0]["towns"]


# the operators' own points (King County's status file, which Ecology's permit tables repeat) of the outfalls the
# hand records are for
POINTS = {
    ("WA0029181", "030"): (47.581476, -122.342997),     # Lander St: 'Duwamish River - East Waterway'
    ("WA0029181", "032"): (47.577223, -122.34278),      # Hanford #2: 'Duwamish River - East Waterway'
    ("WA0031682", "107"): (47.5736688, -122.3430585),   # 'East Waterway of the Duwamish River'
    ("WA0031682", "059"): (47.6702494, -122.4061857),   # 'Salmon Bay'
    ("WA0031682", "060"): (47.6678326, -122.4077581),   # 'Salmon Bay'
    ("WA0029181", "014"): (47.64711, -122.304861),      # Montlake: 'Lake Washington Ship Canal'
}
HAND = {"east-waterway-wa": ("East Waterway", "110855770942", [("WA0029181", "030"), ("WA0029181", "032"),
                                                                ("WA0031682", "107")]),
        "salmon-bay-waterway-wa": ("Salmon Bay Waterway", "110855771286", [("WA0031682", "059"), ("WA0031682", "060")]),
        "montlake-cut-wa": ("Montlake Cut", "110855771359", [("WA0029181", "014")])}


def _dist_m(geom, lat, lon):
    import math

    import shapely
    from shapely.geometry import Point
    k = (111_320.0 * math.cos(math.radians(lat)), 110_574.0)
    return shapely.transform(geom, lambda xy: xy * k).distance(shapely.transform(Point(lon, lat), lambda xy: xy * k))


def test_the_washington_hand_records_are_the_census_polygons_at_the_operators_points():
    from shapely.geometry import shape
    recs = {r["slug"]: r for r in _nhd_wa()}
    for slug, (name, oid, outfalls) in HAND.items():
        r = recs[slug]
        assert r["name"] == name and r["hand"] is True and r["source"] == "census" and r["tiger_ids"] == [oid]
        assert r["kind"] == "canal" and r["towns"] == ["Seattle"]
        assert "Ecology's" in r["note"] and "WA00" in r["note"]          # the permit that names the water
        for key in outfalls:
            assert _dist_m(shape(r["geometry"]), *POINTS[key]) <= 20, (slug, key)
    assert recs["salmon-bay-waterway-wa"]["aliases"] == ["Salmon Bay"]
    assert recs["montlake-cut-wa"]["gnis_id"] == "1534602"


def test_the_washington_hand_specs_name_their_tiger_ids():
    from ingest import waters_from_nhd as N
    wa = {h["name"]: h for h in N.HAND if h["state"] == "WA"}
    assert {n: h["oids"] for n, h in wa.items()} == {v[0]: [v[1]] for v in HAND.values()}
    assert all(h["service"] == "tiger" and h.get("near") for h in wa.values())


def _rows(name):
    return [o for o in _json(name)["outfalls"] if o.get("state") == "WA"]


KC_SEA = ("WA0029181", "WA0031682", "WA0029581")


def _gate_ties():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wa_gate_ties", ROOT / "scripts" / "wa_gate_ties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_king_county_and_seattle_outfall_has_a_record_or_the_operators_water_and_a_reason():
    """Before the gates, 41 rows of the three permits had no record; now only Seattle's Longfellow Creek outfalls lack
    one, and they carry the operator's water and why."""
    from build import status as S
    waters = S.load_waters()
    left = []
    for name in ("outfalls-wa.json", "outfalls-us.json", "outfalls-plants-us.json"):
        for o in _rows(name):
            if o["npdes_permit"] not in KC_SEA:
                continue
            if o.get("water_slug"):
                assert S.canon_slug(o["water_slug"]) in waters if hasattr(S, "canon_slug") else o["water_slug"] in waters
            else:
                left.append((name, o["outfall"]))
                assert o["receiving_water_override"]["water"] == "Longfellow Creek"
                assert "Longfellow Creek" in o["no_water_reason"] and "Overpass" in o["no_water_reason"]
    assert sorted(left) == sorted([("outfalls-wa.json", x) for x in ("168", "169", "170")]
                                  + [("outfalls-us.json", x) for x in ("168", "169", "170")])


def test_each_hand_tie_cites_the_operators_list_and_the_record_it_names():
    from build import status as S
    waters = S.load_waters()
    mod = _gate_ties()
    files = {"wa": "outfalls-wa.json", "us": "outfalls-us.json", "plants": "outfalls-plants-us.json"}
    idx = {(k, o["npdes_permit"], o["outfall"]): o for k, n in files.items() for o in _rows(n)}
    assert len(mod.TABLE) == 55
    for key, (slug, water, d, how, basis) in mod.TABLE.items():
        o = idx[key]
        assert o["water_slug"] == slug and o["distance_m"] == d and o["water_matched_by"] == mod.BY, key
        assert o["receiving_water_override"]["water"] == water and o["receiving_water_override"]["basis"].startswith(basis)
        w = waters[slug]
        # the override's water is the record's name or alias, so a ties run with the outlines finds it by name
        assert water.lower() in [str(x).lower() for x in [w["name"]] + list(w.get("aliases") or [])] or key[0] == "plants", key
        assert ("Ecology's permit" in basis) or ("EPA's inventory" in basis), key
        assert "no_water_reason" not in o


def test_the_census_and_nhd_distances_are_measured_from_the_rows_own_points():
    from shapely.geometry import shape
    mod = _gate_ties()
    recs = {r["slug"]: r for r in _nhd_wa()}
    files = {"wa": "outfalls-wa.json", "us": "outfalls-us.json", "plants": "outfalls-plants-us.json"}
    idx = {(k, o["npdes_permit"], o["outfall"]): o for k, n in files.items() for o in _rows(n)}
    n = 0
    for key, (slug, water, d, how, basis) in mod.TABLE.items():
        if how == mod.OBL:
            continue
        o = idx[key]
        got = _dist_m(shape(recs[slug]["geometry"]), o["lat"], o["lon"])
        assert abs(got - d) <= 5, (key, got, d)
        n += 1
    assert n == 15


def test_the_old_wrong_ties_are_gone():
    """King County's Canal Street (007) and 3rd Ave W (008) were tied by EPA's permit-level text to the Duwamish Waterway
    and Pipers Creek, 7.4 and 5.4 km away; Seattle's 170 to Blackjack Creek in Kitsap County; the South plant's 002A and
    WAR002511 0P1 to the Black River near Olympia."""
    for o in _rows("outfalls-us.json") + _rows("outfalls-plants-us.json") + _rows("outfalls-wa.json"):
        if o["npdes_permit"] in KC_SEA + ("WAR002511",) and o.get("water_slug"):
            assert o["water_slug"] not in ("pipers-creek-wa", "blackjack-creek-wa", "black-river-wa"), o["outfall"]
            if (o.get("distance_m") or 0) > 400:      # only a hand tie whose basis says why the point is far
                assert o["water_matched_by"].startswith("scripts/wa_gate_ties.py"), (o["npdes_permit"], o["outfall"])
                assert o["outfall"] in ("031", "161"), (o["npdes_permit"], o["outfall"], o["water_slug"], o["distance_m"])


def test_the_south_plants_marine_outfall_is_at_the_permits_diffuser_with_epas_point_kept():
    for o in _rows("outfalls-plants-us.json"):
        if o["npdes_permit"] == "WA0029581" and o["outfall"] in ("001", "001A"):
            assert (o["lat"], o["lon"]) == (47.602778, -122.429) and o["coords_from"] == "permit"
            assert (o["epa_lat"], o["epa_lon"]) == (47.471111, -122.296112)
            assert "S1.A" in o["coords_note"] and o["water_slug"] == "puget-sound-wa"


def test_the_gate_ties_script_finds_the_files_as_its_table_says():
    mod = _gate_ties()
    assert mod.main(["--check"]) == 0



# Seattle Public Utilities' CSO basin layer (ArcGIS item 1dd13c8a00ae4ff187cef29d208a5ada, layer 0), its
# CSOB_REC_WTR_BDY_NAME for the outfalls the gate table cites, as published when the review fetched it (2026-11-06)
SPU_LAYER_NAMES = {
    "019": "Union Bay", "059": "Salmon Bay", "060": "Salmon Bay", "071": "Elliott Bay",
    "091": "Puget Sound - S-Central", "094": "Puget Sound - S-Central", "095": "Puget Sound - S-Central",
    "107": "East Waterway of the Duwamish River", "161": "Lake Washington", "168": "Longfellow Creek",
    "169": "Longfellow Creek", "170": "Longfellow Creek", "174": "Lake Washington - Ship Canal",
}


def test_seattles_rows_quote_the_basin_layer_verbatim():
    """Review 2026-11-06: four of Seattle's rows quoted 'Puget Sound - Central' and 'East Waterway - Duwamish River' as
    the layer's text, which reads 'Puget Sound - S-Central' and 'East Waterway of the Duwamish River'."""
    mod = _gate_ties()
    n = 0
    for key, entry in list(mod.TABLE.items()) + list(mod.NO_RECORD.items()):
        basis = entry[-1]
        if key[1] != "WA0031682" or "basin layer" not in basis or "gives outfall" not in basis:
            continue
        assert f"gives outfall {key[2]} the receiving water '{SPU_LAYER_NAMES[key[2]]}'" in basis, key
        n += 1
    assert n == 24


def test_the_south_plants_note_places_epas_point_where_it_is():
    """Review 2026-11-06: EPA's point for outfall 001 is a permitted-feature point about 4 km west of the plant (ECHO
    places the facility at longitude -122.238935), 17.7 km from the diffuser; the note said 'the plant in Renton, 15 km'."""
    import math

    def km(a, b, c, d):
        p1, p2, dl = math.radians(a), math.radians(c), math.radians(d - b)
        x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(x))
    for o in _rows("outfalls-plants-us.json"):
        if o["npdes_permit"] == "WA0029581" and o["outfall"] in ("001", "001A"):
            d = km(o["epa_lat"], o["epa_lon"], o["lat"], o["lon"])
            assert f"{round(d)} km from the diffuser" in o["coords_note"], (d, o["coords_note"])
            assert "is the plant" not in o["coords_note"] + o["receiving_water_override"]["basis"]
            assert abs((o["epa_lon"] - -122.238935) * 111.32 * math.cos(math.radians(47.47))) > 3.5   # not the plant


# ---------------------------------------------------------------- Puget Sound under the shoreline model

def _shore():
    from build import shoreline as SH
    return SH.rule(_json("rules.json"))


def test_puget_sound_is_a_shoreline_water_in_washington_and_no_other_sound_is():
    """Puget Sound (openboatlaunch's record of the main basin, 472 km2, Q604141) takes the lake model with its own
    wording; before, a report on it was a marker only. Other sounds and bays keep today's handling; the entry applies
    in WA only, and a lake entry never picks up a sound that shares a lake's name."""
    from build import shoreline as SH
    from build import status as S
    shore = _shore()
    waters = S.load_waters()
    e = SH.shoreline_entry(waters["puget-sound-wa"], shore)
    assert e["name"] == "Puget Sound" and e["sound"] is True and not e.get("ocean")
    assert {s for s, w in waters.items() if SH.is_shoreline(w, shore) and w.get("state") == "WA"} == {"puget-sound-wa"}
    assert SH.shoreline_entry({**waters["puget-sound-wa"], "state": "OR"}, shore) is None
    assert SH.shoreline_entry({"kind": "sound", "name": "Lake Erie", "wikidata": "Q5492", "state": "PA"}, shore) is None
    assert SH.shoreline_entry({"kind": "lake", "name": "Lake Erie", "wikidata": "Q5492", "state": "PA"}, shore)["name"] \
        == "Lake Erie"
    assert "sound" not in SH.shoreline_entry({"kind": "lake", "name": "Lake Erie", "wikidata": "Q5492"}, shore)


def test_puget_sounds_entry_states_its_reason_in_the_public_voice():
    from export import build as X
    e = [x for x in _json("rules.json")["reach"]["shoreline"]["lakes"] if x["name"] == "Puget Sound"][0]
    assert e["wikidata"] == "Q604141" and e["kinds"] == ["sound"] and e["states"] == ["WA"]
    assert "20 kilometres" in e["rationale"] and "72-hour caution" in e["rationale"] and "not shown as clean" in e["rationale"]
    assert _json("rules.json")["yellow"]["default_hours"] == 72          # a sound takes the default caution
    assert not X.internal_wording(e)


def _puget_build():
    import copy
    import tempfile
    from datetime import UTC, datetime, timedelta

    from build import reaches as R
    from build import status as S
    from common import event
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    rec = S.load_waters()["puget-sound-wa"]
    # a stand-in outline: the record's own is openboatlaunch's (cloud runs); a box whose east edge is the shore
    geom = {"type": "Polygon", "coordinates": [[[-122.40, 47.52], [-122.40, 47.70], [-122.60, 47.70], [-122.60, 47.52],
                                                [-122.40, 47.52]]]}
    waters = {"puget-sound-wa": {**copy.deepcopy(rec), "geometry": geom}}
    S._STATES = {"WA"}
    tmp = Path(tempfile.mkdtemp())
    rid = "WA0029181-057"
    e = event(source_id="wa-test", source_record_id=rid, event_type="cso", status="ongoing", npdes_permit="WA0029181",
              outfall_id="057", waterbody_text="Puget Sound", started_at=(now - timedelta(hours=2)).isoformat())
    (tmp / "wa-test.json").write_text(json.dumps({"source_id": "wa-test", "ok": True, "last_ok_at": now.isoformat(),
                                                  "meta": {}, "records": [e]}))
    row = {"npdes_permit": "WA0029181", "outfall": "057", "state": "WA", "water_slug": "puget-sound-wa",
           "lat": 47.5238863, "lon": -122.3963928, "outfall_kind": "cso", "_file": "data/outfalls-us.json"}
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = {**_json("rules.json"), "live_states": ["WA"]}
    st, _ = S.build(now=now, write=False, events_dir=tmp, waters=waters, outfalls=[row], registry={}, reaches={},
                    flows=({}, {}), discharger_towns={}, discharger_waters={}, rules=rules)
    land = {"WA": __import__("shapely.geometry", fromlist=["box"]).box(-122.40, 47.40, -122.20, 47.80)}
    stretch = R.shoreline_record({"water_slug": "puget-sound-wa", "lat": row["lat"], "lon": row["lon"], "state": "WA",
                                  "permit": "WA0029181", "outfall": "057"}, waters, _shore(), land)
    return st, stretch


def test_a_report_on_puget_sound_colours_its_stretch_and_never_the_sound():
    from build import status as S
    st, stretch = _puget_build()
    sound = st["waters"]["puget-sound-wa"]
    assert sound["events"] == ["wa-test:WA0029181-057"]
    assert sound["fill"] is False and sound["stretch_model"] == "shoreline"
    assert sound["status_basis"] == S.SOUND_STATUS_BASIS
    assert stretch["model"] == "shoreline" and stretch["sound"] is True and not stretch["ocean"]
    assert stretch["segments"] and stretch["lake"] == "Puget Sound"


def test_the_export_words_a_sound_stretch_as_a_sound():
    from export import build as X
    _, stretch = _puget_build()
    props = X.shore_path_props(stretch)
    assert props["sound"] is True
    label = X.SOUND_LABEL.format(lake="Puget Sound", where_from="outfall 057", each=20)
    text = " ".join(s["label"] for s in props["stops"]) + " " + label
    assert "lake" not in text.replace("large lakes'", "") and "sound" in text
