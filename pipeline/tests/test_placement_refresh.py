"""An hourly fetch changes provenance, not where the same report is placed."""
import copy
import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from build import status as S
from tests.test_placement_cache import world, recs
from tests.test_placement_steps import NOW, WATERS


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(S, "_GEOM_CACHE", {})
    monkeypatch.setattr(S, "_STATES", None)
    monkeypatch.setattr(S, "now_iso", lambda: NOW.isoformat())


def snapshot(path):
    return {p.name: p.read_bytes() for p in path.glob("*.json")}


@pytest.mark.parametrize("change", ["outline_time", "outfall_fetch", "water_metadata", "record_fetch", "colour_rule"])
def test_two_refreshes_reuse_all_old_placements(tmp_path, monkeypatch, capsys, change):
    records = recs()[:-1]
    kw = world(tmp_path, records, copy.deepcopy(WATERS))
    kw.update(write=True, rain={}, discharger_aliases_map={})
    output = tmp_path / "outputs"
    monkeypatch.setattr(S, "BUILD_DIR", output)
    outlines = tmp_path / "outlines"
    outlines.mkdir()
    monkeypatch.setattr(S, "OBL_WATER_DIR", outlines)
    path = outlines / "test-river-ma.json"
    path.write_text(json.dumps({"geometry": kw["waters"]["test-river-ma"].pop("geometry")}))
    kw["outfalls"] = [{"npdes_permit": "MA0000001", "outfall": "001", "water_slug": "test-river-ma",
                       "fetched_at": NOW.isoformat()}]
    S.build(**kw)
    capsys.readouterr()
    later = (NOW + timedelta(hours=1)).isoformat()
    if change == "outline_time":
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 3600_000_000_000))
    elif change == "outfall_fetch":
        kw["outfalls"][0]["fetched_at"] = later
    elif change == "water_metadata":
        kw["waters"]["short-brook-ma"].update(fetched_at=later, updated_at=later, targets=999,
                                              launches=[{"checked_at": later}])
    elif change == "record_fetch":
        for r in records:
            r["fetched_at"] = later
        path = kw["events_dir"] / "ma-test.json"
        doc = json.loads(path.read_text())
        doc["records"] = records
        doc["fetched_at"] = later
        path.write_text(json.dumps(doc))
    else:
        kw["rules"]["yellow"]["default_hours"] = 1000
    S._GEOM_CACHE.clear()
    S.build(**kw)
    assert "placement reused for 3 of 3" in capsys.readouterr().out
    cached = snapshot(output)
    S._GEOM_CACHE.clear()
    S.build(**{**kw, "placement_cache": None})
    assert snapshot(output) == cached  # includes every byte of current fetch metadata and colour rules


@pytest.mark.parametrize("change", ["outline", "geometry_lines", "outfall", "operator_towns",
                                    "operator_waters", "placement_rule", "code", "county"])
def test_real_placement_inputs_invalidate(tmp_path, monkeypatch, capsys, change):
    kw = world(tmp_path, recs()[:-1], copy.deepcopy(WATERS))
    kw.update(write=True, rain={}, discharger_aliases_map={})
    output = tmp_path / "outputs"
    monkeypatch.setattr(S, "BUILD_DIR", output)
    data = tmp_path / "data"
    (data / "reference").mkdir(parents=True)
    monkeypatch.setattr(S, "DATA_DIR", data)
    outlines = tmp_path / "outlines"
    outlines.mkdir()
    monkeypatch.setattr(S, "OBL_WATER_DIR", outlines)
    path = outlines / "test-river-ma.json"
    geom = kw["waters"]["test-river-ma"].pop("geometry")
    kw["waters"]["test-river-ma"]["geometry_hash"] = "upstream-hash"
    path.write_text(json.dumps({"geometry": geom}))
    kw["outfalls"] = [{"npdes_permit": "MA0000001", "outfall": "001", "water_slug": "test-river-ma"}]
    S.build(**kw)
    capsys.readouterr()
    if change in ("outline", "geometry_lines"):
        doc = {"geometry": geom}
        doc["geometry" if change == "outline" else "geometry_lines"] = {
            "type": "LineString", "coordinates": [[-71.0, 41.0], [-70.9, 41.0]]}
        path.write_text(json.dumps(doc))  # even if upstream geometry_hash did not change
    elif change == "outfall":
        kw["outfalls"][0]["water_slug"] = "short-brook-ma"
    elif change == "operator_towns":
        kw["discharger_towns"]["MA0000001"] = ["Worcester"]
    elif change == "operator_waters":
        kw["discharger_waters"]["MA0000001"] = {"names": ["Short Brook"], "slugs": [], "state": "MA"}
    elif change == "placement_rule":
        kw["rules"].setdefault("placement", {})["no_outfall_all_waters"] = not bool(
            kw["rules"].get("placement", {}).get("no_outfall_all_waters"))
    elif change == "code":
        code = tmp_path / "status.py"
        code.write_bytes(Path(S.__file__).read_bytes() + b"\n# placement version\n")
        monkeypatch.setattr(S, "__file__", str(code))
    else:
        (data / "reference" / S.COUNTY_STATES["TX"]).write_text(json.dumps({"counties": [
            {"geoid": "00001", "county": "Example", "geometry": geom}]}))
    S._GEOM_CACHE.clear()
    S.build(**kw)
    assert "placement reused for 0 of 3" in capsys.readouterr().out
    cached = snapshot(output)
    S._GEOM_CACHE.clear()
    S.build(**{**kw, "placement_cache": None})
    assert snapshot(output) == cached


def test_operator_alias_change_recomputes_the_affected_record(tmp_path, monkeypatch, capsys):
    records = recs()[:-1]
    records[0]["discharger_id"] = "old-utility"
    kw = world(tmp_path, records)
    kw["discharger_aliases_map"] = {"old-utility": "utility-a"}
    S.build(**kw)
    capsys.readouterr()
    kw["discharger_aliases_map"] = {"old-utility": "utility-b"}
    S.build(**kw)
    assert "placement reused for 2 of 3" in capsys.readouterr().out


def test_stamp_ignores_object_order_and_inter_permit_order_but_keeps_meaningful_order(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path)
    waters = copy.deepcopy(WATERS)
    outfalls = [{"npdes_permit": "MA0000001", "outfall": "001", "water_slug": "test-river-ma"},
               {"npdes_permit": "MA0000002", "outfall": "001", "water_slug": "short-brook-ma"}]
    stamp = lambda: S.placement_stamp(waters, outfalls, {}, {}, {}, {"MA"})
    base = stamp()
    waters["test-river-ma"] = dict(reversed(list(waters["test-river-ma"].items())))
    outfalls.reverse()
    assert stamp() == base
    # Tied nearest waters and multi-outfall notes use input order. Ignoring it would return stale bytes.
    waters = dict(reversed(list(waters.items())))
    assert stamp() != base
    outfalls[0]["npdes_permit"] = outfalls[1]["npdes_permit"]
    base = stamp()
    outfalls.reverse()
    assert stamp() != base


def test_outline_stamp_is_portable_and_ignores_metadata_and_json_order(tmp_path, monkeypatch):
    waters = {"test-river-ma": {k: v for k, v in WATERS["test-river-ma"].items() if k != "geometry"}}
    geometry = WATERS["test-river-ma"]["geometry"]
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    (one / "test-river-ma.json").write_text(json.dumps({"geometry": geometry, "fetched_at": "earlier"}))
    (two / "test-river-ma.json").write_text(json.dumps({"fetched_at": "later", "geometry": geometry}, indent=4))
    monkeypatch.setattr(S, "OBL_WATER_DIR", one)
    first = S.placement_stamp(waters, [], {}, {}, {}, {"MA"})
    monkeypatch.setattr(S, "OBL_WATER_DIR", two)
    assert S.placement_stamp(waters, [], {}, {}, {}, {"MA"}) == first


def test_production_default_cache_survives_synthetic_ingest_nhd_and_provisional_stages(tmp_path, monkeypatch, capsys):
    from shapely.geometry import shape
    from ingest import waters_from_nhd as N

    data = tmp_path / "data"
    build = data / "build"
    events = build / "events"
    events.mkdir(parents=True)
    monkeypatch.setattr(S, "DATA_DIR", data)
    monkeypatch.setattr(S, "BUILD_DIR", build)
    monkeypatch.setattr(S, "EVENTS_DIR", events)
    monkeypatch.setattr(S, "PLACEMENT_CACHE", build / "placement-cache.json")
    kw = world(tmp_path, recs()[:-1])
    kw.update(events_dir=events, waters=None, outfalls=None, write=True, placement_cache=True,
              discharger_aliases_map={}, rain={})
    for hour in range(2):
        fetched = (NOW + timedelta(hours=hour)).isoformat()
        # The stages' file contracts, without network calls: ingest, NHD public records, provisional places.
        records = recs()[:-1]
        for r in records:
            r["fetched_at"] = fetched
        S.write_json(events / "ma-test.json", {"source_id": "ma-test", "ok": True, "fetched_at": fetched,
                                               "last_ok_at": NOW.isoformat(), "meta": {}, "records": records})
        waters = [N.public_record({**w, "_geom": shape(w["geometry"]), "fetched_at": fetched})
                  for w in WATERS.values()]
        S.write_json(data / "waters-nhd.json", {"built": fetched, "waters": waters})
        S.write_json(data / "outfalls-ma.json", {"built": fetched, "outfalls": [
            {"npdes_permit": "MA0000001", "outfall": "001", "water_slug": "test-river-ma", "fetched_at": fetched}]})
        S.write_json(build / "outfalls-reported.json", {"generated_at": fetched, "outfalls": [
            {"id": "reported-place", "npdes_permit": "MA0000002", "outfall": "001",
             "water_slug": "short-brook-ma", "record_status": "provisional", "fetched_at": fetched}]})
        assert len(S.load_registry_outfalls()) == 1  # provisional output cannot invalidate placement
        S.build(**kw)
        assert f"placement reused for {3 if hour else 0} of 3" in capsys.readouterr().out
        assert S.PLACEMENT_CACHE.exists()
        cached = {p: (build / p).read_bytes() for p in ("status.json", "history.json")}
        S.build(**{**kw, "placement_cache": None})
        assert cached == {p: (build / p).read_bytes() for p in cached}
        capsys.readouterr()
