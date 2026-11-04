"""ingest/waters_from_nhd.py without the network: names in waterbody texts, GNIS name matching, slugs.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

from ingest import waters_from_nhd as N  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("Teall Brook & Ley Creek", ["Teall Brook", "Ley Creek"]),
    ("Delaware River/Newton Creek", ["Delaware River", "Newton Creek"]),
    ("Tributary of Longhouse creek", ["Longhouse creek"]),
    ("Penhorn Creek UNT", ["Penhorn Creek"]),
    ("Foster Brook to Lake Erie", ["Foster Brook"]),
    ("Catch Basin to Fall Mountain lake", ["Fall Mountain lake"]),
    ("Overland flow to storm drain to Foster Brook", ["Foster Brook"]),
    ("Mill Creek Tube to Lake Erie", ["Mill Creek"]),
    ("Black River (Springfield)", ["Black River"]),
    ("West river at the Retreat Meadows setback", ["West river"]),
    ("Harbor Brook", ["Harbor Brook"]),          # kind words can be a name
    ("Dry Creek", ["Dry Creek"]),
    ("Catch Basin", []), ("none", []), ("Wetland", []), ("Canal", []), ("Did not reach a waterbody", []),
    ("Atlantic Ocean", []), ("12 Main St", []), ("N", []), ("UT", []), ("UT to Back Creek", ["Back Creek"]),
])
def test_water_names_in_discharge_texts(text, expected):
    assert N.split_names(text, False) == expected


@pytest.mark.parametrize("text,expected", [
    ("Harry Wright Lake Low Beach (Manchester Township)", ["Harry Wright Lake"]),
    ("Kingston's Camp at Larkin Pond (North Kingstown)", ["Larkin Pond"]),
    ("Cheesequake State Park - Hooks Creek Lake N (Old Bridge Township)", ["Hooks Creek Lake"]),
    ("Camp Grosvenor (North Kingstown)", []),      # a site: its lake comes from its point
])
def test_water_names_in_beach_and_hab_sites(text, expected):
    assert N.split_names(text, True) == expected


def test_not_water_reasons():
    assert N.not_water("Atlantic Ocean").startswith("the open ocean")
    assert N.not_water("Intervale Wetlands").startswith("a wetland")
    assert N.not_water("12 Main St") == "a street address"
    assert N.not_water("Scajaquada Creek") is None


def test_gnis_name_scores():
    w = N.words
    assert N.name_score(w("2 Mile Creek"), "Twomile Creek") == 1.0
    assert N.name_score(w("Eighteen Mile Creek"), "Eighteenmile Creek") == 1.0
    assert N.name_score(w("Mill R."), "Mill River") == 1.0
    assert N.name_score(w("Lake Mohawk Country"), "Lake Mohawk") == 0.9
    assert N.name_score(w("moodna"), "Moodna Creek") == 0.85
    assert N.name_score(w("smokes creek"), "Smoke Creek") == 0.8
    assert N.name_score(w("Nashua River"), "North Nashua River") == 0.7     # snapped flowline only
    assert N.name_score(w("West Branch Indian Creek"), "East Branch Indian Creek") == 0.0
    assert N.name_score(w("Mill River"), "Sawmill River") == 0.0
    assert N.name_score(w("Mill Brook"), "Hill Brook") == 0.0
    assert N.name_score(w("Stoney Run"), "Stony Run") == 0.8
    assert N.name_score(w("Mill Run"), "Mile Run") == 0.0


def test_sql_names_join_numbers_to_mile():
    t = {"name": "2 Mile Creek", "words": N.words("2 Mile Creek")}
    assert {"TWOMILE CREEK", "TWO MILE CREEK", "2 MILE CREEK"} <= set(N.sql_names(t))


def rec(name, state, gnis, weight, towns, slug_towns):
    return {"name": name, "state": state, "gnis_id": gnis, "_weight": weight, "towns": towns,
            "_slug_towns": Counter(slug_towns), "comids": [1]}


def test_slugs_plain_for_the_main_record_town_for_the_others_never_existing():
    existing = {"stony-brook-ny": {"slug": "stony-brook-ny", "name": "Stony Brook", "state": "NY"},
                "cayuga-creek-x": {"slug": "cayuga-creek-x", "name": "Other", "state": "NY"}}
    a = rec("Cayuga Creek", "NY", "1", 200, ["Cheektowaga"], {"Cheektowaga": 9})
    b = rec("Cayuga Creek", "NY", "2", 50, ["Niagara Falls"], {"Niagara Falls": 3})
    c = rec("Stony Brook", "NY", "3", 60, ["Dansville"], {"Dansville": 2})
    N.assign_slugs([a, b, c], existing)
    assert a["slug"] == "cayuga-creek-ny" and b["slug"] == "cayuga-creek-niagara-falls-ny"
    assert c["slug"] == "stony-brook-dansville-ny"          # the name is already a record in the state


def test_aliases_only_for_texts_the_resolver_would_not_match():
    t = {"texts": Counter({"2 Mile Creek": 5, "Tributary of Twomile Creek": 1}), "names": Counter({"2 Mile Creek": 5}),
         "point_mode": False}
    assert N.aliases_for("Twomile Creek", t, "NY", {}) == ["2 Mile Creek"]


def test_point_towns_only_near_the_record():
    class FakeTowns:
        def at(self, state, lon, lat):
            return "Near" if lon < -78 else "Far"

        def canonical(self, state, name):
            return None         # 'erie county' is not a county subdivision
    t = {"state": "NY", "points": Counter({(-78.90, 42.98): 4, (-76.0, 43.0): 2}), "towns": Counter({"erie county": 3}),
         "events": 6, "outfalls": 0}
    tc, n = N.target_point_towns(t, FakeTowns(), LineString([(-78.91, 42.98), (-78.89, 42.98)]))
    assert n == 4 and tc["Near"] == 4 and "Far" not in tc


# ---------------------------------------------------------------- 2026-11-03: hand records, --osm-only

class _Http:
    def __init__(self, elements):
        self.elements = elements

    def get(self, kind, url, params):
        assert kind == "osm-hand" and "way(id:" in params["data"]
        return {"elements": self.elements}


class _States:
    def clip(self, g, state):
        return g


class _Towns:
    def along(self, state, geom):
        return ["Cumberland"]


def _way(i, coords):
    return {"type": "way", "id": i, "tags": {"name": "Test Run", "waterway": "stream"},
            "geometry": [{"lon": x, "lat": y} for x, y in coords]}


def test_hand_record_from_osm_ways_is_cited_and_shaped_like_waters_extra():
    from types import SimpleNamespace
    nhd = SimpleNamespace(states=_States(), towns=_Towns())
    spec = dict(name="Test Run", state="MD", kind="stream", source="osm", ways=[1, 2], aliases=["Test Rn"],
                why="the reports name it; no NHD feature")
    els = [_way(1, [(-78.70, 39.67), (-78.71, 39.672)]), _way(2, [(-78.71, 39.672), (-78.72, 39.675)])]
    rec, problem = N.build_hand(spec, nhd, _Http(els))
    assert problem == "" and rec["hand"] is True and rec["source"] == "osm" and rec["osm"] == ["w1", "w2"]
    assert rec["kind"] == "stream" and rec["towns"] == ["Cumberland"] and rec["aliases"] == ["Test Rn"]
    assert "w1, w2" in rec["note"] and "Hand record: the reports name it" in rec["note"]
    assert 1.5 < rec["length_km"] < 2.5 and rec["bbox"][0] < rec["bbox"][2]
    rec["slug"] = "test-run-md"
    row = N.public_record(rec)
    assert row["hand"] is True and row["geometry"]["type"] == "MultiLineString"
    rec, problem = N.build_hand(spec, nhd, _Http(els[:1]))           # a way Overpass did not return
    assert rec is None and "OSM ways [2] not returned" in problem


def test_hand_specs_cite_a_geometry_source():
    for spec in N.HAND:
        assert spec["why"] and spec["state"] and spec["name"]
        assert (spec["source"] == "nhd" and (spec.get("gnis_id") or spec.get("pids"))) or \
            (spec["source"] == "osm" and spec["ways"])
        if spec.get("pids"):                 # an identifier search is bounded by a box (the service times out without)
            assert spec["service"] == "hr" and len(spec["box"]) == 4


# ---------------------------------------------------------------- 2026-11-03: NHD high-resolution hand records

class _HrNhd:
    """The parts of Nhd that build_hr uses: hr_lines (recording its call), states, towns."""

    def __init__(self, feats):
        from types import SimpleNamespace
        self.feats, self.calls = feats, []
        self.states, self.towns = _States(), _Towns()
        self.http = SimpleNamespace()

    def hr_lines(self, state, gnis_id=None, pids=None, box=None):
        self.calls.append((state, gnis_id, pids, box))
        return self.feats


def _hr(pid, coords, name="Test Creek", fcode=46006, reach="04270101000937"):
    return {"permanent_identifier": pid, "gnis_id": "00964557", "gnis_name": name, "fcode": fcode, "ftype": 460,
            "reachcode": reach, "lengthkm": 1.0, "_geom": LineString(coords)}


def test_hr_hand_record_by_gnis_id_carries_culverted_stretches_and_cites_the_service():
    nhd = _HrNhd([_hr("1", [(-78.80, 42.92), (-78.78, 42.92)]),
                  _hr("2", [(-78.78, 42.92), (-78.70, 42.915)], fcode=33400),         # a culvert (connector)
                  _hr("3", [(-78.70, 42.915), (-78.65, 42.91)], fcode=55800, reach="04270101001555")])
    spec = dict(name="Test Creek", state="NY", kind="stream", source="nhd", service="hr", gnis_id="964557",
                why="NHDPlus V2.1 has 4.9 km of it")
    rec, problem = N.build_hr(spec, nhd)
    assert problem == "" and nhd.calls == [("NY", "964557", None, None)]
    assert rec["source"] == "nhd" and rec["gnis_id"] == "964557" and rec["comids"] == []
    assert rec["nhd_fcodes"] == [33400, 46006, 55800] and rec["reachcodes"] == ["04270101000937", "04270101001555"]
    assert rec["length_km"] > 12 and rec["towns"] == ["Cumberland"] and rec["kind"] == "stream"
    assert "high resolution" in rec["note"] and "layer 6" in rec["note"] and "3 flowlines with GNIS id 964557" in rec["note"]
    assert "NHDPlus V2.1 has 4.9 km of it" in rec["note"]
    full, problem = N.build_hand(spec, nhd, None)                    # through build_hand: hand, the plain name, no targets
    assert problem == "" and full["hand"] is True and full["name"] == "Test Creek" and full["_targets_n"] == 0


def test_hr_hand_record_by_permanent_identifier_needs_every_identifier_in_its_box():
    pids = ["{A}", "{B}"]
    spec = dict(name="Test Creek", state="CT", source="nhd", service="hr", pids=pids, box=(-73.18, 41.15, -73.14, 41.19),
                why="the GNIS line runs along it")
    nhd = _HrNhd([_hr("{A}", [(-73.16, 41.17), (-73.15, 41.16)], fcode=55800)])
    rec, problem = N.build_hr(spec, nhd)
    assert rec is None and "['{B}'] not returned" in problem
    assert nhd.calls == [("CT", None, pids, (-73.18, 41.15, -73.14, 41.19))]
    nhd = _HrNhd([_hr("{A}", [(-73.16, 41.17), (-73.15, 41.16)], fcode=55800),
                  _hr("{B}", [(-73.15, 41.16), (-73.14, 41.15)], fcode=55800)])
    rec, problem = N.build_hr(spec, nhd)
    assert problem == "" and rec["gnis_id"] is None and "by permanent identifier ({A}, {B})" in rec["note"]
    nhd = _HrNhd([])
    rec, problem = N.build_hr({**spec, "pids": None, "gnis_id": "208183"}, nhd)
    assert rec is None and "no NHD high-resolution flowlines with GNIS id 208183" in problem


def test_a_superseding_hand_record_replaces_the_automatic_record_and_takes_its_targets(monkeypatch):
    """Scajaquada Creek: the NHDPlus V2.1 record (4.9 km) built by the automatic pass is dropped; the hand record
    (24 km) is attached to the same targets by name, and a row mapped only by point comes along."""
    from types import SimpleNamespace
    old = {"name": "Scajaquada Creek", "state": "NY", "gnis_id": "964557", "length_km": 4.9, "aliases": ["Scajaquada Cr"],
           "_targets": [], "_geom": LineString([(0, 0), (1, 1)])}
    other = {"name": "Ley Creek", "state": "NY", "gnis_id": "1", "length_km": 3.0, "aliases": [], "_targets": [],
             "_geom": LineString([(0, 0), (1, 1)])}
    row_by_name = {"_recs": [old], "how": ["NLDI position"], "reason": None, "slugs": []}
    row_by_point = {"_recs": [old], "how": ["NLDI position"], "reason": None, "slugs": []}
    old["_targets"] = [row_by_name, row_by_point]
    t1 = {"state": "NY", "name": "Scajaquada Creek", "names": ["Scajaquada Creek"]}
    t2 = {"state": "NY", "name": "Cheektowaga branch", "names": ["Cheektowaga branch"]}
    new = {"name": "Scajaquada Creek", "state": "NY", "aliases": [], "source": "nhd", "_key": ("hand", "NY", "scajaquada-creek"),
           "_targets": [], "_geom": LineString([(0, 0), (2, 2)])}
    spec = dict(name="Scajaquada Creek", state="NY", source="nhd", service="hr", gnis_id="964557", supersede=True, why="x")
    monkeypatch.setattr(N, "HAND", [spec])
    monkeypatch.setattr(N, "build_hand", lambda *a_: (new, ""))
    attached = []

    def attach(rec, row, t, how):
        rec["_targets"].append(row)
        row["_recs"].append(rec)
        row["how"].append(how)
        attached.append((t["name"], how))

    run = SimpleNamespace(feats={("line", "NY", "964557"): old, ("line", "NY", "1"): other}, existing={}, problems=[],
                          nhd=None, http=None, attach=attach)
    N.Run.hand_pass(run, [(t1, row_by_name), (t2, row_by_point)])
    assert run.problems == [] and list(run.feats) == [("line", "NY", "1"), ("hand", "NY", "scajaquada-creek")]
    assert run.feats[("hand", "NY", "scajaquada-creek")] is new and new["aliases"] == ["Scajaquada Cr"]
    assert row_by_name["_recs"] == [new] and row_by_point["_recs"] == [new]
    assert [n for n, _ in attached] == ["Scajaquada Creek", "Cheektowaga branch"]
    assert any("replaces the NHDPlus V2.1 record" in h for h in row_by_name["how"])
    # without supersede the same situation is refused, as for any hand record
    run = SimpleNamespace(feats={("line", "NY", "964557"): {**old, "_targets": []}}, existing={}, problems=[],
                          nhd=None, http=None, attach=attach)
    monkeypatch.setattr(N, "HAND", [{k: v for k, v in spec.items() if k != "supersede"}])
    N.Run.hand_pass(run, [])
    assert run.problems == []          # a same-named record found this run wins quietly (a note, not a problem)


def test_the_scajaquada_hand_record_is_listed_to_replace_the_automatic_one():
    assert ("NY", N.S.norm_name("Scajaquada Creek")) in N.superseded_keys()
    names = {(h["state"], h["name"]) for h in N.HAND}
    assert {("NJ", "Penhorn Creek"), ("CT", "Webster Brook"), ("CT", "Johnson's Creek")} <= names


@pytest.mark.parametrize("name,expected", [("No Name Small Stream", True), ("Small Stream", True),
                                           ("Little River", False), ("Crow Hollow Brook", False), ("Stream", False)])
def test_generic_descriptions_are_not_sent_to_osm(name, expected):
    assert N.generic_name(name) is expected


def test_osm_only_asks_only_where_nhd_failed_and_osm_was_not_asked():
    tried = "no NHD flowline or waterbody of that name within 2 km (nearby: X); OSM fallback not tried (over --osm-max 120)"
    assert N.NHD_FAILED.search(tried) and not N.OSM_ASKED.search(tried)
    asked = "no NHD flowline or waterbody of that name within 2 km; no NHD feature and no OSM feature of that name near"
    assert N.OSM_ASKED.search(asked)
    assert not N.NHD_FAILED.search("2 NHD waters of that name in NY and no town to choose one")


def test_state_queries_escape_names_and_split_long_alternations():
    specs = [{"name": f"Brook {i} (East)", "osm_names": [f"brook {i} (east)"], "box": (42.0 + i / 100, -72.0, 42.1, -71.9)}
             for i in range(400)]
    chunks = N.state_chunks(specs)
    assert len(chunks) > 1 and all(len(N.WX.name_regex(n)) <= N.OSM_REGEX_MAX + 40 for n, _ in chunks)
    assert sum(len(n) for n, _ in chunks) == 800
    q = N.state_query(["Johnson's Creek", "St. Mary (Upper)"], (41.0, -73.0, 42.0, -72.0))
    assert r'St\. Mary \(Upper\)' in q and '"waterway"~"^(river|stream|canal)$"' in q and "out tags geom" in q
    assert "(41.0,-73.0,42.0,-72.0)" in q and "[timeout:90]" in q


def test_a_state_answer_is_split_to_each_names_box():
    resp = {"elements": [
        {"type": "way", "id": 1, "tags": {"name": "Penhorn Creek", "waterway": "stream"},
         "bounds": {"minlat": 40.75, "minlon": -74.06, "maxlat": 40.76, "maxlon": -74.05}},
        {"type": "way", "id": 2, "tags": {"name": "Penhorn Creek", "waterway": "stream"},          # far away
         "bounds": {"minlat": 39.0, "minlon": -75.0, "maxlat": 39.01, "maxlon": -74.99}},
        {"type": "way", "id": 3, "tags": {"name": "Queen Ditch", "waterway": "canal"},
         "bounds": {"minlat": 40.75, "minlon": -74.06, "maxlat": 40.76, "maxlon": -74.05}}],
        "osm3s": {"timestamp_osm_base": "x"}}
    spec = {"name": "Penhorn Creek", "osm_names": ["penhorn creek"], "box": (40.7, -74.1, 40.8, -74.0)}
    got = N.for_spec(resp, spec)
    assert [e["id"] for e in got["elements"]] == [1] and got["osm3s"] == {"timestamp_osm_base": "x"}


def test_osm_state_pass_stops_asking_overpass_when_the_time_budget_is_used(monkeypatch):
    """A scheduled refresh must never wait on Overpass: with the budget used, no query is sent and the
    targets say they are left for the next run (cached answers are still applied)."""
    import types
    from ingest import waters_from_nhd as W
    asked = []
    monkeypatch.setattr(W, "state_fetch", lambda *a_, **k: asked.append(1) or (None, "x"))
    monkeypatch.setattr(W.WX, "is_cached", lambda *a_, **k: False)
    monkeypatch.setattr(W, "osm_spec", lambda t, towns: {"key": f"k-{t['name']}", "name": t["name"], "box": (0.0, 0.0, 1.0, 1.0), "osm_names": []})
    monkeypatch.setattr(W, "mirror_order", lambda **k: ["m"])
    monkeypatch.setattr(W.time, "monotonic", iter([0.0, 10.0, 20.0]).__next__)   # start, then over budget
    t = {"name": "Mill Brook", "state": "MA", "key": "MA|Mill Brook", "events": 3, "outfalls": 0, "points": [[0, 0]], "words": ["brook"]}
    row = {"reason": "no NHD feature", "how": None}
    fake = types.SimpleNamespace(args=types.SimpleNamespace(osm_max=600, refresh=False, offline=False, osm_budget=5.0),
                                 osm_queue=[(t, row)], towns={}, osm_used=0, osm_remaining=[], feats={}, states={},
                                 existing_list=[], problems=[], attach=lambda *a_: None)
    W.Run.osm_state_pass(fake)
    assert asked == []
    assert "time budget used" in row["reason"] and "left for the next run" in row["reason"]
    assert fake.osm_remaining == ["MA: Mill Brook"] and fake.osm_states["MA"]["failed"].startswith("time budget")


# ---------------------------------------------------------------- 2026-11-03: writes never lose records

def _run_rec(slug, note="this run", state="NY"):
    """A record as the run holds it (internal form), enough for public_record()."""
    return {"slug": slug, "name": slug.rsplit("-", 1)[0].replace("-", " ").title(), "state": state, "kind": "stream",
            "note": note, "_geom": LineString([(-75.0, 42.0), (-75.01, 42.01)]), "_targets_n": 1}


@pytest.fixture
def out_file(tmp_path, monkeypatch):
    path = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", path)
    return path


def _seed(path, slugs, note="old"):
    """The file on disk from an earlier full run (not sorted, like the committed one)."""
    from common import write_json
    write_json(path, {"partial": False, "count": len(slugs), "stats": {"records": len(slugs), "targets": 9},
                      "targets": [{"state": "NY", "name": f"T {s}", "texts": [s], "slugs": [s]} for s in slugs],
                      "waters": [N.public_record(_run_rec(s, note)) for s in slugs]})


def _read(path):
    import json
    return json.loads(path.read_text())


def _notes(path):
    return {r["slug"]: r["note"] for r in _read(path)["waters"]}


def _write(recs, partial=False, **kw):
    return N.write_output(recs, [], [], [], partial=partial, **kw)


def test_checkpoint_of_a_partial_run_keeps_the_untouched_records(out_file):
    _seed(out_file, ["d-ny", "a-ny", "c-ny", "b-ny", "e-ny"])
    info = _write([_run_rec("c-ny"), _run_rec("f-ny")], partial=True)          # 2 records so far, 5 on disk
    got = _read(out_file)
    assert [r["slug"] for r in got["waters"]] == ["a-ny", "b-ny", "c-ny", "d-ny", "e-ny", "f-ny"]   # sorted by slug
    assert got["count"] == 6 and got["partial"] is True
    assert _notes(out_file) == {"a-ny": "old", "b-ny": "old", "c-ny": "this run", "d-ny": "old", "e-ny": "old",
                                "f-ny": "this run"}
    assert info["mode"] == "merge" and (info["replaced"], info["added"], info["kept"]) == (1, 1, 4)
    assert got["stats"]["records"] == 5                                         # the last full run's statistics stay
    assert {r["name"] for r in got["targets"]} >= {"T a-ny", "T e-ny"}          # and its target rows


def test_checkpoint_through_the_run_object_merges(out_file, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(N, "CHECKPOINT_EVERY", 1)
    _seed(out_file, ["a-ny", "b-ny", "c-ny", "d-ny"])
    feats = {("line", "NY", "1"): {**_run_rec("x"), "name": "Mill Brook", "gnis_id": "1", "comids": [1], "_weight": 3,
                                   "_slug_towns": Counter({"Dryden": 3}), "towns": ["Dryden"]}}
    fake = SimpleNamespace(feats=feats, last_written=0, existing={}, rows=[], skipped_reason={},
                           http=SimpleNamespace(fetched={}, cached={}, failed={}))
    N.Run.checkpoint(fake, 1, 800)
    assert list(_notes(out_file)) == ["a-ny", "b-ny", "c-ny", "d-ny", "mill-brook-ny"]


def test_final_write_with_fewer_records_merges_and_notes_it(out_file):
    """A full run that resolved fewer records than the file holds (the OSM time budget makes this normal)
    merges: the file keeps every record and the summary carries a warning; only --rebuild drops records."""
    import json
    _seed(out_file, ["a-ny", "b-ny", "c-ny", "d-ny", "e-ny"])
    _write([_run_rec("a-ny"), _run_rec("b-ny"), _run_rec("c-ny")], final=True)
    data = json.loads(out_file.read_text())
    assert sorted(r["slug"] for r in data["waters"]) == ["a-ny", "b-ny", "c-ny", "d-ny", "e-ny"]
    w = data["stats"]["write"]
    assert w["mode"] == "merge" and w["kept"] == 2 and w["dropped"] == 0 and w["written"] == 5
    assert "resolved 3 records" in w["warning"] and "holds 5" in w["warning"] and "--rebuild" in w["warning"]


def test_merge_keeps_the_aliases_of_a_record_the_run_replaces():
    """A re-resolved record takes the new row but keeps the file row's aliases (the union, the file's first);
    a record the run did not visit, and one with no aliases either side, stay as they are."""
    old = [{"slug": "a-ny", "name": "A", "aliases": ["A Crk", "A Creek"], "note": "old"},
           {"slug": "b-ny", "name": "B", "aliases": ["B Crk"], "note": "old"},
           {"slug": "c-ny", "name": "C", "aliases": [], "note": "old"},
           {"slug": "d-ny", "name": "D", "note": "old"}]
    new = [{"slug": "a-ny", "name": "A", "aliases": ["A Creek", "Ay Creek"], "note": "new"},
           {"slug": "b-ny", "name": "B", "aliases": None, "note": "new"},
           {"slug": "c-ny", "name": "C", "aliases": ["C Crk"], "note": "new"},
           {"slug": "d-ny", "name": "D", "note": "new"},
           {"slug": "e-ny", "name": "E", "aliases": ["E Crk"], "note": "new"}]
    got = {r["slug"]: r for r in N.merge_waters(old, new)}
    assert got["a-ny"]["aliases"] == ["A Crk", "A Creek", "Ay Creek"] and got["a-ny"]["note"] == "new"
    assert got["b-ny"]["aliases"] == ["B Crk"] and got["b-ny"]["note"] == "new"
    assert got["c-ny"]["aliases"] == ["C Crk"]
    assert "aliases" not in got["d-ny"] and got["d-ny"]["note"] == "new"
    assert got["e-ny"]["aliases"] == ["E Crk"]
    assert old[0]["aliases"] == ["A Crk", "A Creek"] and new[0]["aliases"] == ["A Creek", "Ay Creek"]   # inputs untouched
    only_old = N.merge_waters(old, [])
    assert [r["slug"] for r in only_old] == ["a-ny", "b-ny", "c-ny", "d-ny"] and only_old[0]["aliases"] == ["A Crk", "A Creek"]


def test_write_output_keeps_the_aliases_of_the_file_on_a_rerun(out_file):
    import json
    _seed(out_file, ["a-ny", "b-ny"])
    data = _read(out_file)
    data["waters"][0]["aliases"] = ["A Crk"]
    out_file.write_text(json.dumps(data))
    _write([{**_run_rec("a-ny"), "aliases": ["A Creek"]}, _run_rec("b-ny")], final=True)
    got = {r["slug"]: r for r in _read(out_file)["waters"]}
    assert got["a-ny"]["aliases"] == ["A Crk", "A Creek"] and got["a-ny"]["note"] == "this run"
    assert not got["b-ny"]["aliases"]


def test_rebuild_lets_a_final_write_replace_the_file_and_says_so(out_file):
    _seed(out_file, ["a-ny", "b-ny", "c-ny", "d-ny", "e-ny"])
    info = _write([_run_rec("c-ny"), _run_rec("a-ny"), _run_rec("z-ny")], final=True, rebuild=True)
    got = _read(out_file)
    assert [r["slug"] for r in got["waters"]] == ["a-ny", "c-ny", "z-ny"] and got["count"] == 3
    assert _notes(out_file) == {"a-ny": "this run", "c-ny": "this run", "z-ny": "this run"}
    assert info["mode"] == "rebuild" and info["dropped"] == 3 and info["added"] == 1
    assert got["stats"]["write"]["mode"] == "rebuild"
    text = N.describe_write(info)
    assert text.startswith("--rebuild: replaced the 5 records") and "3 existing records dropped" in text


def test_a_re_resolved_record_is_replaced_and_one_not_visited_is_kept(out_file):
    _seed(out_file, ["a-ny", "b-ny", "c-ny"])
    info = _write([_run_rec("b-ny", "re-resolved"), _run_rec("c-ny", "re-resolved"), _run_rec("d-ny", "new")],
                  final=True)                                                   # 3 records against 3: not fewer
    assert _notes(out_file) == {"a-ny": "old", "b-ny": "re-resolved", "c-ny": "re-resolved", "d-ny": "new"}
    assert info["mode"] == "merge" and (info["replaced"], info["added"], info["kept"], info["written"]) == (2, 1, 1, 4)
    assert _read(out_file)["partial"] is False
    assert N.describe_write(info).startswith("merged into the 3 records")


def test_a_limited_run_merges_and_is_never_refused(out_file):
    _seed(out_file, ["a-ny", "b-ny", "c-ny"])
    _write([_run_rec("b-ny", "re-resolved")], partial=True, final=True)         # --limit: one record, 3 on disk
    assert _notes(out_file) == {"a-ny": "old", "b-ny": "re-resolved", "c-ny": "old"}


def test_first_write_without_a_file_and_an_unreadable_file(out_file):
    _write([_run_rec("b-ny"), _run_rec("a-ny")], final=True)                    # no file yet: nothing to lose
    assert list(_notes(out_file)) == ["a-ny", "b-ny"]
    out_file.write_text("{not json")
    with pytest.raises(N.WriteRefused, match="cannot be read"):
        _write([_run_rec("a-ny")], partial=True)
    assert out_file.read_text() == "{not json"


def test_rebuild_cannot_be_combined_with_limit():
    with pytest.raises(SystemExit):
        N.main(["--rebuild", "--limit", "5"])


def test_a_hand_record_yields_quietly_to_a_found_record_of_the_same_name(monkeypatch, capsys):
    """When a regular record of the hand record's name exists in this run, the hand record is skipped with a
    note, not a problem (a problem would read as a failed run in the refresh log)."""
    import types
    from ingest import waters_from_nhd as W
    monkeypatch.setattr(W, "HAND", [{"name": "Jennings Run", "state": "MD", "service": "hr"}])
    monkeypatch.setattr(W, "same_named_existing", lambda existing, state, name: [])
    built = []
    monkeypatch.setattr(W, "build_hand", lambda spec, nhd, http: built.append(spec) or (None, "should not be called"))
    fake = types.SimpleNamespace(feats={("nhd", "MD", "jennings-run"): {"name": "Jennings Run", "state": "MD"}},
                                 existing={}, problems=[], nhd=None, http=None)
    W.Run.hand_pass(fake, [])
    assert built == [] and fake.problems == []
    assert "not needed" in capsys.readouterr().out


# ---------------------------------------------------------------- 2026-11-04: --wall-s bounds the whole hourly target

def test_a_pass_budget_is_cut_to_the_time_left_before_the_wall():
    assert N.left_of(180.0, None) == 180.0 and N.left_of(None, None) is None
    assert N.left_of(180.0, 100.0, now=40.0) == 60.0          # 60 s left: the OSM fallback gets 60, not 180
    assert N.left_of(None, 100.0, now=40.0) == 60.0
    assert N.left_of(120.0, 100.0, now=130.0) == 0.0          # past the wall: nothing


def _osm_fake(monkeypatch, budget, net_end, clock):
    import types
    asked, mirrors = [], []
    monkeypatch.setattr(N, "state_fetch", lambda *a_, **k: asked.append(k.get("deadline")) or (None, "time budget used"))
    monkeypatch.setattr(N.WX, "is_cached", lambda *a_, **k: False)
    monkeypatch.setattr(N, "osm_spec", lambda t, towns: {"key": f"k-{t['name']}", "name": t["name"],
                                                         "box": (0.0, 0.0, 1.0, 1.0), "osm_names": []})
    monkeypatch.setattr(N, "mirror_order", lambda **k: mirrors.append(k.get("timeout")) or ["m"])
    monkeypatch.setattr(N.time, "monotonic", iter(clock).__next__)
    t = {"name": "Mill Brook", "state": "MA", "key": "MA|Mill Brook", "events": 3, "outfalls": 0, "points": [[0, 0]],
         "words": ["brook"]}
    row = {"reason": "no NHD feature", "how": None}
    fake = types.SimpleNamespace(args=types.SimpleNamespace(osm_max=600, refresh=False, offline=False, osm_budget=budget),
                                 osm_queue=[(t, row)], towns={}, osm_used=0, osm_remaining=[], feats={}, states={},
                                 existing_list=[], problems=[], attach=lambda *a_: None, net_end=net_end)
    return fake, row, asked, mirrors


def test_the_osm_fallback_starts_nothing_when_the_wall_leaves_too_little_time(monkeypatch):
    """Run 41788856038: the mirror check took 62 s outside the OSM budget and the queries ran on past it; with --wall-s
    the budget is what is left before the wall, and under OSM_MIN_S neither the check nor a query is started."""
    fake, row, asked, mirrors = _osm_fake(monkeypatch, 180.0, net_end=1005.0, clock=[1000.0] + [1001.0] * 20)
    N.Run.osm_state_pass(fake)
    assert mirrors == [] and asked == []
    assert "time budget used" in row["reason"] and "left for the next run" in row["reason"]
    assert fake.osm_states["MA"]["failed"].startswith("time budget")


def test_the_mirror_check_and_the_queries_keep_inside_the_wall(monkeypatch):
    fake, row, asked, mirrors = _osm_fake(monkeypatch, 180.0, net_end=1060.0, clock=[1000.0] + [1001.0] * 20)
    N.Run.osm_state_pass(fake)
    assert mirrors == [10.0]                     # 60 s left: each mirror is given a sixth of it, not 30 s
    assert asked == [1060.0]                     # the state query is cut to the wall
    # without a wall it is as it was: 30 s a mirror, a query started inside the budget not cut
    fake, row, asked, mirrors = _osm_fake(monkeypatch, 180.0, net_end=None, clock=[1000.0] + [1001.0] * 20)
    N.Run.osm_state_pass(fake)
    assert mirrors == [30.0] and asked == [None]


def test_a_state_query_is_not_sent_without_time_left(monkeypatch, tmp_path):
    monkeypatch.setattr(N, "CACHE_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(N.requests, "post", lambda *a_, **k: sent.append(k["timeout"]))
    monkeypatch.setattr(N.time, "monotonic", lambda: 100.0)
    assert N.state_fetch("q", ["m1", "m2"], False, False, deadline=105.0) == (None, "time budget used")
    assert sent == []


def test_http_stops_at_the_wall_and_says_so(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(N.time, "monotonic", lambda: clock[0])
    slept = []
    monkeypatch.setattr(N.time, "sleep", slept.append)
    h = N.Http(deadline=130.0, deadline_reason="--wall-s used", nldi_log=Path("/nonexistent/x.json"))
    assert h.timeout(120) == 30.0                # a request never runs two minutes past the wall
    h.nap(120)
    assert slept == [30.0]                       # nor a retry pause
    clock[0] = 131.0
    with pytest.raises(N.BudgetExhausted, match="--wall-s used"):
        h.spend("near2")
    # the reason reaches the public outfall registry in public voice
    text, found = N.public_voice(f"{N.NOT_REACHED} (--wall-s used); the next run resumes", "2026-11-04")
    assert found == ["(--wall-s used)"] and "time or request limit" in text


def test_the_hourly_check_resolves_only_the_unplaced_events_again(monkeypatch):
    resolved = []

    class Res:
        def resolve(self, ev):
            resolved.append(ev["event_id"])
            return {"water_slugs": ["mill-brook-ma"] if ev["event_id"] == "a" else []}

    monkeypatch.setattr(N.S, "make_resolver", lambda waters: Res())
    monkeypatch.setattr(N.S, "derive_states", lambda waters, rules: {})
    monkeypatch.setattr(N.S, "load_rules", lambda: {})
    monkeypatch.setattr(N, "public_record", lambda r: {"slug": r["slug"]})
    unplaced = [{"event_id": "a", "waterbody_text": "Mill Brook"}, {"event_id": "b", "waterbody_text": "Elsewhere"}]
    out = N.evaluate_unplaced({}, [{"slug": "mill-brook-ma"}], unplaced)
    assert resolved == ["a", "b"]                # not every event, not twice
    assert out["before"]["unplaced_with_text"] == 2 and out["after"]["unplaced_with_text"] == 1
    assert out["before"]["ids"] - out["after"]["ids"] == {"a"}
    assert out["before"]["unplaced"] is None     # the count over all events is not made in this check


def test_the_last_line_gives_the_seconds_of_each_phase_and_why_the_run_stopped():
    import types
    args = types.SimpleNamespace(wall_s=300.0, finish_s=60.0)
    line = N.timing_line(287.4, {"targets": 41.6, "nhd": 150.2, "places": 0.1, "osm": 47.0, "finish": 48.5}, args,
                         "--budget-s used")
    assert line.startswith("waters-nhd: 287 s of --wall-s 300 (60 s kept for the end): loading the targets 42 s, NHDPlus 150 s")
    assert line.endswith("stopped early: --budget-s used; the next run resumes from the cache")


def test_no_mirror_check_when_every_queued_name_is_answered_from_the_cache(monkeypatch, tmp_path):
    """The hourly run's OSM share is short: the mirror check (up to half of it) is made only when a query will be sent."""
    fake, row, asked, mirrors = _osm_fake(monkeypatch, 180.0, net_end=1060.0, clock=[1000.0] + [1001.0] * 20)
    monkeypatch.setattr(N.WX, "is_cached", lambda *a_, **k: True)
    monkeypatch.setattr(N.WX, "CACHE_DIR", tmp_path)
    (tmp_path / "k-Mill Brook.json").write_text('{"elements": []}')
    monkeypatch.setattr(N, "osm_record", lambda *a_, **k: (None, "no OSM feature of that name near the points"))
    N.Run.osm_state_pass(fake)
    assert mirrors == [] and asked == []
    assert "no OSM feature" in row["reason"]


def test_a_target_rows_towns_are_most_counted_first_then_by_name():
    """The towns written to a target row of data/waters-nhd.json do not follow the order they were counted in (2026-11-04
    run-time review P3-7: 223 rows changed between two runs on the same inputs)."""
    def row(order):
        t = N.Target(key="MD:x", state="MD", name="Gwynns Falls", texts=Counter({"Gwynns Falls": 1}), outfalls=0,
                     events=4, points=Counter(), towns=Counter())
        for tw in order:
            t["towns"][tw] += 2 if tw == "Baltimore" else 1
        return N.Run.new_row(t)["towns"]
    a = row(["Towson", "Essex", "Baltimore", "Pikesville", "Catonsville"])
    b = row(["Catonsville", "Pikesville", "Baltimore", "Essex", "Towson"])
    assert a == b == ["Baltimore", "Catonsville", "Essex", "Pikesville"]


def test_a_target_rows_towns_are_the_same_under_any_hash_seed():
    """An event's towns are a set; the row must not change with Python's hash seed (two processes, two seeds)."""
    import os
    import subprocess
    code = ("from collections import Counter; from ingest import waters_from_nhd as N; "
            "t = N.Target(key='MD:x', state='MD', name='x', texts=Counter(), outfalls=0, events=1, points=Counter(), "
            "towns=Counter()); "
            "[t['towns'].update([tw]) for tw in {'lonaconing', 'barton', 'cresaptown', 'frostburg', 'westernport', "
            "'midland', 'luke'}]; print(N.Run.new_row(t)['towns'])")
    outs = set()
    for seed in ("1", "2", "3", "4"):
        r = subprocess.run([sys.executable, "-c", code], cwd=Path(N.__file__).resolve().parent.parent,
                           env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True, text=True, check=True)
        outs.add(r.stdout.strip())
    assert outs == {"['barton', 'cresaptown', 'frostburg', 'lonaconing']"}
