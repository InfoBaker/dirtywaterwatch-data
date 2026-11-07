"""New Mexico: NMED's HABs Mapper layer through the generic ArcGIS ingester (data/sources/nm-nmed-hab-mapper.yaml,
ingest/nm_transforms.py). The fixture holds real rows of the layer fetched 2026-11-07 (the internal-notes field and
the GlobalID left out), with a placeholder staff note added to one row to prove it never reaches a record."""
import copy
import json
from pathlib import Path

import yaml

from ingest.generic import arcgis, runner

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures" / "nm_nmed_habs.json"
FETCHED = "2026-11-07T02:00:00Z"
META = {"editingInfo": {"lastEditDate": 1793382911190}}


def block():
    return yaml.safe_load((ROOT / "data" / "sources" / "nm-nmed-hab-mapper.yaml").read_text())["fetch"]


def build(page=None, prev=()):
    b = block()
    page = page or json.loads(FIX.read_text())
    return runner.build("nm-nmed-hab-mapper", b, arcgis.parse(b, json.dumps(page).encode()), FETCHED, list(prev), META)


def test_the_block_is_valid_live_and_never_asks_for_the_internal_notes():
    b = block()
    assert runner.validate_block(b, "nm-nmed-hab-mapper") == [] and b["live"] is True
    assert "SWQB_internal_notes" not in b["safe_fields"] and "GlobalID" not in b["safe_fields"]
    assert b["time_zone"] == "America/Denver"


def test_advisories_are_blooms_with_the_layers_points_and_monitored_stations_are_not_records():
    recs, stats = build()
    assert stats["rows"] == 7 and stats["rows_kept_by_filter"] == 5          # Springer and San Gregorio: MONITORED
    assert {r["event_type"] for r in recs} == {"hab_advisory"} and {r["status"] for r in recs} == {"advisory_active"}
    by = {r["waterbody_text"]: r for r in recs}
    assert set(by) == {"Eagle Nest Lake", "Quemado Lake", "Nichols Reservoir",
                       "Rio Grande (Rio Pueblo de Taos to Red River)", "Rio Grande (Embudo Creek to Rio Pueblo de Taos)"}
    e = by["Eagle Nest Lake"]
    assert (e["lat"], e["lon"]) == (36.53417, -105.254726) and e["coord_source"] == "source"
    assert e["started_at"] == "2026-10-01T10:01:00-06:00" and e["time_precision"] == "minute"
    assert e["source_updated_at"].startswith("2026-10-30T11:55:11") and e["ended_at"] is None
    assert e["advice_text"] == "NMED harmful algal bloom WARNING advisory: Entire lake under WARNING advisory."
    assert e["raw"]["_toxin"] == "Microcystin 24.8 µg/L at the latest sample"
    assert e["source_record_id"] == "05ensixmilerec-20261001T1001"
    jd = by["Rio Grande (Rio Pueblo de Taos to Red River)"]
    assert jd["started_at"].startswith("2026-10-13") and jd["time_precision"] == "day"     # '10-13-2026': a date


def test_the_html_link_leaves_the_advice_text_and_is_kept_apart():
    recs, _ = build()
    ov = next(r for r in recs if r["source_record_id"].startswith("near-28rgrand658"))
    assert "<a" not in ov["advice_text"] and ov["advice_text"].endswith("See BLM press release.")
    assert ov["raw"]["_links"][0]["url"].startswith("https://www.blm.gov/announcement/")


def test_a_personal_note_never_reaches_the_records():
    recs, _ = build()
    blob = json.dumps(recs)
    assert "Pat Example" not in blob and "505-555-0100" not in blob and "SWQB_internal_notes" not in blob


def test_a_point_outside_new_mexico_is_not_used():
    page = json.loads(FIX.read_text())
    a = next(f["attributes"] for f in page["features"] if f["attributes"]["OBJECTID"] == 146)
    a["MLOC_LATITUDE"] = 40.0
    recs, _ = build(page)
    r = next(x for x in recs if x["waterbody_text"] == "Nichols Reservoir")
    assert r["lat"] is None and r["raw"].get("_coords_rejected")


def test_a_lifted_station_keeps_its_record_with_the_missing_mark():
    first, _ = build()
    page = json.loads(FIX.read_text())
    for f in page["features"]:
        if f["attributes"]["OBJECTID"] == 100:
            f["attributes"]["HAB_Status"] = "MONITORED"
    again, stats = build(page, copy.deepcopy(first))
    e = next(r for r in again if r["waterbody_text"] == "Eagle Nest Lake")
    assert e["raw"].get("_missing_from_source_since") == FETCHED and e["status"] == "advisory_active"
    assert [r["event_id"] for r in again if r["waterbody_text"] != "Eagle Nest Lake"] == \
           [r["event_id"] for r in first if r["waterbody_text"] != "Eagle Nest Lake"]


def test_each_fetch_that_finds_an_advisory_confirms_it_and_the_first_that_does_not_ends_it():
    """Review 2026-11-07 P2-2: NMED's map shows an advisory until it lifts it, however long since the layer's last edit.
    A fetch that still finds the station confirms the advisory; the first fetch that no longer finds it ends it."""
    from datetime import datetime, timezone
    from build import status
    first, _ = build()
    later = "2026-12-20T02:00:00Z"                    # weeks after the layer's last edit (2026-10-30)
    b = block()
    page = json.loads(FIX.read_text())
    again, _ = runner.build("nm-nmed-hab-mapper", b, arcgis.parse(b, json.dumps(page).encode()), later,
                            copy.deepcopy(first), META)
    e = next(r for r in again if r["waterbody_text"] == "Eagle Nest Lake")
    assert e["raw"]["_last_seen_in_source"] == later and "_unlisted_since" not in e["raw"]
    rules = status.load_rules()
    ivs = status.event_intervals(e, "NM", datetime(2026, 12, 21, tzinfo=timezone.utc), None, rules)
    assert ivs[0]["rule"] == "advisory_active" and ivs[0]["end"] > datetime(2027, 1, 2, tzinfo=timezone.utc)
    assert ivs[0]["confirmed"].startswith("2026-12-20")
    # lifted: the station is MONITORED at the next fetch; the advisory ends at that fetch, not 14 days later
    lifted = "2026-12-27T02:00:00Z"
    for f in page["features"]:
        if f["attributes"]["OBJECTID"] == 100:
            f["attributes"]["HAB_Status"] = "MONITORED"
    third, _ = runner.build("nm-nmed-hab-mapper", b, arcgis.parse(b, json.dumps(page).encode()), lifted,
                            copy.deepcopy(again), META)
    e = next(r for r in third if r["waterbody_text"] == "Eagle Nest Lake")
    assert e["raw"]["_unlisted_since"] == lifted and e["raw"]["_last_seen_in_source"] == later
    ivs = status.event_intervals(e, "NM", datetime(2027, 1, 5, tzinfo=timezone.utc), None, rules)
    assert len(ivs) == 1 and ivs[0]["end"] == datetime(2026, 12, 27, 2, tzinfo=timezone.utc)
    # without the history key (every other block) nothing changes
    b2 = {**b, "history": {k: v for k, v in b["history"].items() if k != "confirm_while_listed"}}
    plain, _ = runner.build("nm-nmed-hab-mapper", b2, arcgis.parse(b2, json.dumps(page).encode()), lifted, [], META)
    assert not any("_last_seen_in_source" in r["raw"] or "_unlisted_since" in r["raw"] for r in plain)


def test_nmeds_names_place_on_the_openboatlaunch_records_by_hand_alias(monkeypatch, tmp_path):
    """Final audit 2026-11-07: NMED names six lakes otherwise than openboatlaunch does (Stubblefield Lake, under a WATCH
    on 2026-11-07, is openboatlaunch's Stubblefield Reservoir). Each station's own point lies inside the record's box;
    data/water-aliases.json carries the names, so the advisory places on the lake and no second record is built."""
    from build import status as S
    pairs = {"Stubblefield Lake": ("stubblefield-reservoir-nm", 36.57564, -104.66115),
             "Navajo Reservoir": ("navajo-lake-nm", 36.84907, -107.60725),
             "Abiquiu Reservoir": ("abiquiu-lake-nm", 36.25388, -106.44208),
             "Avalon Lake": ("lake-avalon-nm", 32.49889, -104.2494),
             "Conchas Reservoir": ("conchas-lake-nm", 35.38911, -104.19451),
             "Sumner Lake": ("lake-sumner-nm", 34.61868, -104.38561)}
    waters = S.load_waters()
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path)
    monkeypatch.setattr(S, "_STATES", S.derive_states(waters, S.load_rules()) | {"NM"})
    S._GEOM_CACHE.clear()
    live = S.live_waters(waters, S._STATES)
    R = S.Resolver(live, S.load_registry_outfalls(), S.load_discharger_towns(), S.load_discharger_waters(),
                   S.load_rules().get("placement") or {})
    try:
        for name, (slug, lat, lon) in pairs.items():
            x0, y0, x1, y1 = waters[slug]["bbox"]
            assert x0 <= lon <= x1 and y0 <= lat <= y1 and name in waters[slug]["aliases"]
            ev = {"event_id": "t", "source_id": "nm-nmed-hab-mapper", "event_type": "hab_advisory",
                  "waterbody_text": name, "lat": lat, "lon": lon, "raw": {}, "npdes_permit": None, "discharger_id": None}
            assert R.resolve(ev)["water_slugs"] == [slug], name
    finally:
        S._GEOM_CACHE.clear()
