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
