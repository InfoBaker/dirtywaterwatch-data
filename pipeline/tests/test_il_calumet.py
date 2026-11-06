"""Illinois's final audit (2026-11-06; review 2026-11-06 P2-7): the Calumet River and the Little Calumet River.
NHDPlus V2.1 gives the Calumet River's GNIS id (405379) to the Little Calumet River from the Indiana line to Blue Island;
the USGS NHD high-resolution flowlines carry the Calumet River itself under that id, from Hegewisch through O'Brien Lock
to Lake Michigan. The lower river is calumet-river-il (hand record, NHD high resolution); the NHDPlus flowlines are
little-calumet-river-il (hand record, by their COMIDs). O'Brien Lock's reversal row stays on Lake Michigan (matched at its
lake entry), and its stretch's river path belongs to the Calumet River's record too.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from shapely.geometry import LineString, Point, shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build import reaches as R  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LOCK = (-87.569396, 41.654744)          # MWRD's CSO Points layer, OBJECTID 395
MOUTH = (-87.529216, 41.732891)         # the Calumet River's mouth (NHD high resolution)


def _waters():
    return {w["slug"]: w for w in json.loads((ROOT / "data" / "waters-nhd.json").read_text())["waters"]}


def _spec(name):
    return [h for h in N.HAND if h["state"] == "IL" and h["name"] == name][0]


def test_the_lower_river_takes_the_calumet_rivers_gnis_id_and_slug():
    spec = _spec("Calumet River")
    assert spec["service"] == "hr" and spec["gnis_id"] == "405379" and spec["supersede"] is True
    w = _waters()["calumet-river-il"]
    assert w["name"] == "Calumet River" and w["hand"] is True and w["gnis_id"] == "405379"
    assert "high resolution" in w["note"] and "O'Brien Lock" in w["note"]
    g = shape(w["geometry"])
    assert g.distance(Point(*LOCK)) < 0.0005 and g.distance(Point(*MOUTH)) < 0.0005   # lock to mouth
    assert w["bbox"][3] > 41.73 and 11 < w["length_km"] < 13.5


def test_the_nhdplus_flowlines_are_the_little_calumet_river_by_their_comids():
    spec = _spec("Little Calumet River")
    assert spec["gnis_id"] == "405379" and spec.get("service") is None and spec["gnis_not_its_own"]
    ws = _waters()
    w = ws["little-calumet-river-il"]
    assert w["name"] == "Little Calumet River" and w["hand"] is True
    assert w["gnis_id"] is None and w["nhdplus_gnis_id"] == "405379" and set(w["comids"]) == {13463969, 13463979}
    # cut west of the junction at Hegewisch: the Grand Calumet east of it is grand-calumet-river-il (review P2-1)
    assert w["bbox"][2] <= -87.5613 and spec["within"][2] == -87.5614 and "Grand Calumet" in spec["why"]
    import shapely
    m = lambda g: shapely.transform(g, lambda xy: xy * [83_000.0, 111_000.0])      # metres near 41.6 N
    grand = m(shape(ws["grand-calumet-river-il"]["geometry"])).buffer(30)
    assert m(shape(w["geometry"])).intersection(grand).length / 1000 < 0.1
    assert "is not this water's own" in w["note"]
    assert N.water_identity(w) == ("IL", "comids", tuple(sorted(w["comids"])))
    assert N.water_identity(ws["calumet-river-il"]) == ("IL", "gnis", "405379")
    assert shape(w["geometry"]).distance(Point(*MOUTH)) > 0.05                     # none of the lower river
    # one feature, one record: the two never collapse into one on a merge
    ids = [N.water_identity(x) for x in ws.values() if x.get("state") == "IL"]
    assert ids.count(("IL", "gnis", "405379")) == 1


def test_a_nhdplus_hand_record_whose_gnis_id_is_another_waters_keeps_it_aside(monkeypatch):
    rec = {"name": "Calumet River", "kind": "river", "gnis_id": "405379", "note": "NHDPlus V2.1: 6 network flowlines",
           "comids": [1, 2], "_geom": LineString([(-87.65, 41.65), (-87.53, 41.63)])}
    monkeypatch.setattr(N, "build_feature", lambda *a, **k: dict(rec))
    nhd = SimpleNamespace(lines_by_gnis=lambda st, g: [{"reachcode": "07120003000061", "comid": 1}],
                          towns=SimpleNamespace(along=lambda st, g: ["Chicago"]))
    out, problem = N.build_hand(_spec("Little Calumet River"), nhd, None)
    assert problem == "" and out["name"] == "Little Calumet River"
    assert out["gnis_id"] is None and out["nhdplus_gnis_id"] == "405379"
    pub = N.public_record({**out, "slug": "little-calumet-river-il"})
    assert pub["nhdplus_gnis_id"] == "405379" and pub["gnis_id"] is None


def test_a_superseded_records_targets_go_to_the_hand_record_that_carries_their_name(monkeypatch):
    """The automatic NHDPlus 'Calumet River' record held the Little Calumet's targets: the Calumet River's hand record
    (supersede) does not inherit a row named for the Little Calumet; the Little Calumet's hand record takes it."""
    old = {"name": "Calumet River", "state": "IL", "gnis_id": "405379", "aliases": [], "_targets": [],
           "_geom": LineString([(0, 0), (1, 1)])}
    little_row = {"_recs": [old], "how": [], "reason": None, "slugs": []}
    cal_row = {"_recs": [old], "how": [], "reason": None, "slugs": []}
    old["_targets"] = [little_row, cal_row]
    t_little = {"state": "IL", "name": "LITTLE CALUMET RIVER", "names": ["LITTLE CALUMET RIVER"]}
    t_cal = {"state": "IL", "name": "Cal R reach", "names": ["Cal R reach"]}
    recs = {"Calumet River": {"name": "Calumet River", "state": "IL", "aliases": [], "source": "nhd",
                              "_key": ("hand", "IL", "calumet-river"), "_targets": [], "_geom": LineString([(0, 0), (2, 2)])},
            "Little Calumet River": {"name": "Little Calumet River", "state": "IL", "aliases": [], "source": "nhd",
                                     "_key": ("hand", "IL", "little-calumet-river"), "_targets": [],
                                     "_geom": LineString([(0, 0), (3, 3)])}}
    monkeypatch.setattr(N, "HAND", [_spec("Calumet River"), _spec("Little Calumet River")])
    monkeypatch.setattr(N, "build_hand", lambda spec, *a: (recs[spec["name"]], ""))

    def attach(rec, row, t, how):
        rec["_targets"].append(row)
        row["_recs"].append(rec)

    run = SimpleNamespace(feats={("line", "IL", "405379"): old}, existing={}, problems=[], nhd=None, http=None,
                          attach=attach)
    N.Run.hand_pass(run, [(t_little, little_row), (t_cal, cal_row)])
    assert little_row["_recs"] == [recs["Little Calumet River"]]
    assert cal_row["_recs"] == [recs["Calumet River"]]
    assert any("left to the hand record that carries this name" in h for h in little_row["how"])


def _rows():
    return {(r["npdes_permit"], str(r["outfall"])): r for r in common.load_outfall_registry(provisional=False)
            if r.get("state") == "IL"}


def test_mwrds_cal_r_outfalls_are_on_the_calumet_river_and_little_cal_r_on_the_little_calumet():
    rows = _rows()
    for k in [("IL0028061", "151"), ("IL0028061", "152"), ("IL0045012", "206"), ("IL0045012", "CDS-20")]:
        assert rows[k]["water_slug"] == "calumet-river-il" and rows[k]["distance_m"] < 400, k
    il = [r for r in json.loads((ROOT / "data" / "outfalls-il.json").read_text())["outfalls"]]
    north = [r for r in il if r.get("mwrd_reach") == "Little Cal R (North)"]
    assert north and all(r["water_slug"] == "little-calumet-river-il" for r in north)
    assert not [r for r in il if r.get("mwrd_reach") == "Cal R" and not r.get("structure")
                and r.get("water_slug") != "calumet-river-il"]          # O'Brien Lock itself is on the lake (below)
    # no row names the Little Calumet and sits on the Calumet River's record
    assert not [k for k, r in rows.items() if r.get("water_slug") == "calumet-river-il"
                and "LITTLE" in str(r.get("receiving_water_echo") or "").upper()]


def test_obrien_lock_stays_on_lake_michigan_matched_at_its_lake_entry():
    gate = _rows()[("IL0028061", "OBrien Lock and Dam")]
    assert gate["water_slug"] == "lake-michigan-il" and gate["distance_m"] == 0
    assert "matched at the structure's lake entry" in gate["water_match"] and "10.93 km" in gate["water_match"]
    crcw = _rows()[("IL0028053", "Chicago River Controlling Works")]
    assert crcw["water_slug"] == "lake-michigan-il" and "lake entry" not in crcw["water_match"]   # no river path


def test_a_structure_is_matched_at_its_lake_entry_and_keeps_its_own_point(monkeypatch):
    seen = []

    class MT:
        def match(self, o, flags):
            seen.append((o["lat"], o["lon"]))
            return {"slug": "lake-x", "how": "x", "step": "name"}

    def apply(o, res, mt):
        o.update(water_slug=res["slug"], water_match="name: x", distance_m=0)

    monkeypatch.setattr(OW, "apply", apply)
    entry = {"lat": 41.73, "lon": -87.53, "water": "River Y", "path": [[-87.57, 41.65], [-87.53, 41.73]], "path_km": 10.0}
    row = {"lat": 41.65, "lon": -87.57, "lake_entry": entry}
    OW.match_and_apply(row, {}, MT())
    assert seen == [(41.73, -87.53)] and (row["lat"], row["lon"]) == (41.65, -87.57)
    assert "matched at the structure's lake entry (41.73, -87.53), the River Y's mouth" in row["water_match"]
    # an entry with no river path (the Controlling Works: the outer shore beside the structure) is matched at the point
    seen.clear()
    row = {"lat": 41.88, "lon": -87.60, "lake_entry": {**entry, "path": []}}
    OW.match_and_apply(row, {}, MT())
    assert seen == [(41.88, -87.60)] and "lake entry" not in row["water_match"]


def test_the_stretchs_river_path_belongs_to_the_rivers_record():
    ws = {s: {**w, "extra": True} for s, w in _waters().items() if s in ("calumet-river-il", "little-calumet-river-il",
                                                                            "lake-michigan-il")}
    gate = [r for r in json.loads((ROOT / "data" / "outfalls-il.json").read_text())["outfalls"]
            if r["outfall"] == "OBrien Lock and Dam"][0]
    assert R.river_path_waters(gate["lake_entry"]["path"], ws, "IL") == ["calumet-river-il"]
    assert R.river_path_waters([], ws, "IL") == []


def test_a_reach_segment_on_a_records_own_comid_flags_it_whatever_nhdplus_names_it():
    """Review P1-1: NHDPlus names the Little Calumet's flowlines 'Calumet River'; a traced segment on COMID 13463969
    flags little-calumet-river-il (its own COMID) and not calumet-river-il; an unnamed segment on the lower river flags
    calumet-river-il."""
    from build import status as S
    ws = {s: {**w, "extra": True} for s, w in _waters().items()
          if s in ("calumet-river-il", "little-calumet-river-il", "grand-calumet-river-il")}
    little = shape(ws["little-calumet-river-il"]["geometry"])
    line = little.geoms[0] if little.geom_type == "MultiLineString" else little
    pts = [list(c) for c in line.coords][len(line.coords) // 3:len(line.coords) // 3 + 3]
    S._REACH_WATERS.clear()
    seg = {"comid": 13463969, "gnis_name": "Calumet River", "coords": pts}
    assert S.reach_waters({"key": "t-little", "segments": [seg]}, ws) == ["little-calumet-river-il"]
    S._REACH_WATERS.clear()
    assert S.reach_waters({"key": "t-little-noid", "segments": [{**seg, "comid": None}]}, ws) == []   # name alone: no
    lower = shape(ws["calumet-river-il"]["geometry"])
    lower = lower.geoms[0] if lower.geom_type == "MultiLineString" else lower
    mid = [list(c) for c in lower.coords][len(lower.coords) // 2:len(lower.coords) // 2 + 3]
    assert S.reach_waters({"key": "t-lower", "segments": [{"comid": None, "gnis_name": "", "coords": mid}]},
                          ws) == ["calumet-river-il"]
    S._REACH_WATERS.clear()


def test_mwrds_little_cal_south_outfalls_are_on_the_east_arm():
    """Review P2-2: the south arm carries the name MWRD and EPA use (alias), so each 'Little Cal R (South)' row is
    tied to the east arm at its point."""
    spec = _spec("East Arm Little Calumet River")
    assert spec["supersede"] and "Little Calumet River" in spec["aliases"] and "Little Cal R (South)" in spec["why"]
    assert "Little Calumet River" in _waters()["east-arm-little-calumet-river-il"]["aliases"]
    il = json.loads((ROOT / "data" / "outfalls-il.json").read_text())["outfalls"]
    south = [r for r in il if r.get("mwrd_reach") == "Little Cal R (South)"]
    assert len(south) >= 20
    assert all(r["water_slug"] == "east-arm-little-calumet-river-il" and r["distance_m"] <= 250 for r in south)
    assert all(r["distance_m"] <= 50 for r in south if r["npdes_permit"] == "ILM580025")
