"""The state build (ingest.waters_from_nhd --state, ingest.outfall_waters --state) without the network: the national
list's texts, the target order, EPA's reaches, unnamed outfalls, the request budgets and the NLDI limit, the merge into
data/waters-nhd.json that keeps every other state, and the outfall steps by reach and by outfall.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402


# ---------------------------------------------------------------- EPA's receiving-water texts

@pytest.mark.parametrize("text,expected", [
    ("NEUSE RIVER", ["NEUSE RIVER"]),
    ("DAN RIVER (North Carolina portion)", ["DAN RIVER"]),
    ("Nutbush Creek (Including Nutbush Creek Arm of Jo", ["Nutbush Creek"]),     # a parenthesis EPA cut off
    ("Abbotts Creek Arm of High Rock Lake", ["High Rock Lake"]),
    ("BOGGY CRK/SPRING CRK/FLINT RIVER", ["BOGGY Creek"]),                         # path: the first water receives
    ("UNNAMED TRIB/JUNIPER CR/ECHECONNEE-OCUMULGEE RB", ["JUNIPER Creek"]),
    ("ROCKY COMFORT CRK TO OGEECHEE RB", ["ROCKY COMFORT Creek"]),
    ("PANTHER CRK/UPPER OCMULGEE RV BASIN", ["PANTHER Creek"]),
    ("Old Tampa Bay Class II Marine WBID 1558H", ["Old Tampa Bay"]),
    ("Black Cr Class III Fresh WBID 2213I St Johns R", ["Black Creek", "St Johns River"]),
    ("Caloosahatchee R Estuary Class III Marine 3240B", ["Caloosahatchee R Estuary"]),
    ("Little River and Big Creek", ["Little River", "Big Creek"]),
    ("Discharge to Town Branch", ["Town Branch"]),
    ("CHATTAHOOCHEE", ["CHATTAHOOCHEE"]),          # a name with no kind word is kept
    # the way in front of the water (Mississippi's inventory, 2026-11-07): 'DIRECTLY' is not the water's name
    ("DIRECTLY INTO LEAF RIVER", ["LEAF RIVER"]), ("DIRECLTY INTO MOUND BAYOU", ["MOUND BAYOU"]),
    ("DIR INTO YOCONA RIVER", ["YOCONA RIVER"]), ("DIR INTO DITCH THEN BURNEY BRANCH", ["BURNEY BRANCH"]),
    ("directly to Ray Roberts Lake", ["Ray Roberts Lake"]),
    ("DIRECT DISCHARGE CREEK", ["DIRECT DISCHARGE CREEK"]),   # no 'to' or 'into' after it: a name, left alone
])
def test_national_texts_that_name_waters(text, expected):
    assert N.national_parts(text) == (expected, None)


@pytest.mark.parametrize("text,why", [
    ("BANKS COUNTY", "county"), ("CHATHAM COUNTY LAS", "county"), ("SUWANNEE RIVER BASIN", "basin"),
    ("CITY OF REIDSVILLE (TATTNALL CO)", "town"), ("OFF GA HWY 57", "road"), ("Atlantic Ocean Class III Marine WBID 8093", "ocean"),
    ("BOOT WETLAND SYSTEM", "wetland"), ("abc", "no water name"), ("Not applicable", "not a water name"),
])
def test_national_texts_that_name_no_water(text, why):
    parts, reason = N.national_parts(text)
    assert parts == [] and why in reason


# ---------------------------------------------------------------- targets from the national list

def national():
    return {"NC": {"waters": [
        {"name": "Mill Creek", "key": "mill creek", "names_seen": ["Mill Creek"], "reach_ids": [], "nhdplus_ids": [],
         "outfalls": {"plant": 1}, "operators": [{"permit": "NC0000003"}], "points": [], "define_by": "name"},
        {"name": "NEUSE RIVER", "key": "neuse river", "names_seen": ["NEUSE RIVER"], "reach_ids": ["03020201000171"],
         "nhdplus_ids": ["8791413"], "outfalls": {"plant": 3}, "operators": [{"permit": "NC0000001"}],
         "points": [[35.2, -77.6]], "define_by": "reach"},
        {"name": "Eno River", "key": "eno river", "names_seen": ["Eno River"], "reach_ids": [], "nhdplus_ids": [],
         "outfalls": {"plant": 1}, "operators": [{"permit": "NC0000002"}], "points": [[36.07, -79.1]], "define_by": "point"},
        {"name": "Haw River", "key": "haw river", "reach_ids": ["03030002000001"], "nhdplus_ids": [], "outfalls": {"cso": 1},
         "operators": [], "points": [], "water_slug": "haw-river-nc", "define_by": "record"},
        {"name": "Dan River", "key": "dan river", "reach_ids": ["03010103000001"], "nhdplus_ids": [], "outfalls": {"cso": 2},
         "operators": [], "points": [], "water_slug": "dan-river-nc", "define_by": "record"},
        {"name": "BANKS COUNTY", "key": "banks county", "reach_ids": [], "nhdplus_ids": [], "outfalls": {"plant": 1},
         "operators": [], "points": [], "define_by": "name"},
    ], "unnamed_outfalls": [
        {"permit": "NC0000009", "outfall": "001", "lat": 35.0, "lon": -78.0, "reach_id": None, "nhdplus_id": None},
        {"permit": "NC0000010", "outfall": "001", "lat": None, "lon": None, "reach_id": None, "nhdplus_id": None},
    ]}}


def test_state_targets_in_the_order_reach_point_name_unnamed():
    existing = {"haw-river-nc": {"state": "NC", "name": "Haw River"}}
    towns = {"NC0000001": Counter({"Goldsboro": 2}), "NC0000003": Counter({"Hillsborough": 1})}
    targets, skipped, stats = N.collect_state_targets(["NC"], existing, national(), towns)
    order = [(t["define_by"], t["name"]) for t in targets]
    assert order == [("reach", "NEUSE RIVER"), ("reach", "Dan River"), ("point", "Eno River"), ("name", "Mill Creek"),
                     ("unnamed", None)]
    neuse = targets[0]
    assert neuse["reach_ids"] == ["03020201000171"] and neuse["nhdplus_ids"] == ["8791413"]
    assert neuse["points"] == Counter({(-77.6, 35.2): 1}) and neuse["towns"] == Counter({"Goldsboro": 2})
    dan = targets[1]
    assert "is no water record on file" in dan["notes"][0]        # an openboatlaunch slug whose extract is not here
    assert stats["rows with a record"] == 1                        # haw-river-nc is on file: no target
    assert "county" in skipped[("NC", "BANKS COUNTY")]
    assert "no point" in skipped[("NC", "unnamed outfall NC0000010:001")]
    assert targets[-1]["outfall_ref"] == ["NC0000009", "001"]


# ---------------------------------------------------------------- EPA's reaches, no snapping

def flow(comid, gnis_id, name, code="03020201000171", **kw):
    return {"comid": comid, "gnis_id": gnis_id, "gnis_name": name, "reachcode": code, **kw}


def target(name, reach_ids=(), nhdplus_ids=(), points=None):
    return N.Target(state="NC", key=f"NC:{N.compact(name)}", name=name, words=N.words(name), reach_ids=list(reach_ids),
                    nhdplus_ids=list(nhdplus_ids), points=Counter(points or {}), towns=Counter(), point_mode=False)


class FakeNhd:
    def __init__(self, wbs=None):
        self.wbs = wbs or {}
        self.asked = []

    def by_comid(self, layer, comid):
        self.asked.append((layer, comid))
        return self.wbs.get(comid, [])


def test_a_reach_carrying_the_name_gives_its_gnis_feature():
    idx = {("code", "03020201000171"): [flow(8791413, "1013910", "Neuse River")],
           ("comid", 8790357): [flow(8790357, "1025621", "Polecat Branch", "03020201000174")]}
    out, why = N.resolve_reach(FakeNhd(), target("NEUSE RIVER", ["03020201000171"], ["8790357"]), idx)
    assert why is None and len(out) == 1
    k, c, how, ids = out[0]
    assert k == ("line", "NC", "1013910") and c["type"] == "line" and c["gnis_name"] == "Neuse River"
    assert "no snapping" in how and ids == ["03020201000171", "8791413"]


def test_reaches_of_other_names_are_left_to_the_point_or_name_pass():
    idx = {("code", "03020201000174"): [flow(8790357, "1025621", "Polecat Branch", "03020201000174")]}
    out, why = N.resolve_reach(FakeNhd(), target("TAR RIVER", ["03020201000174"]), idx)
    assert out == [] and "Polecat Branch" in why and "'TAR RIVER'" in why
    out, why = N.resolve_reach(FakeNhd(), target("TAR RIVER", ["99999999999999"]), idx)
    assert out == [] and "not NHDPlus V2.1" in why


def test_a_lake_name_takes_the_waterbody_its_reach_runs_through():
    idx = {("code", "03130001000100"): [flow(100, "999", "Chattahoochee River", "03130001000100", wbareacomid=555,
                                             wbarea_ftype=436)]}
    nhd = FakeNhd({555: [{"comid": 555, "gnis_id": "311", "gnis_name": "Lake Sidney Lanier", "ftype": 436}]})
    out, why = N.resolve_reach(nhd, target("Lake Sidney Lanier", ["03130001000100"]), idx)
    assert len(out) == 1 and out[0][1]["type"] == "wb" and out[0][0] == ("wb", "NC", "311")


def test_an_unnamed_outfall_on_a_named_flowline_gets_that_water(monkeypatch):
    idx = {("comid", 77): [flow(77, "1013910", "Neuse River")]}
    out, why = N.resolve_unnamed(FakeNhd(), target("x", nhdplus_ids=["77"]) | {"name": None, "words": []}, idx)
    assert why is None and out[0][0] == ("line", "NC", "1013910")


def test_an_unnamed_flowline_is_named_for_the_first_named_water_downstream(monkeypatch):
    idx = {("comid", 77): [flow(77, None, None)]}
    monkeypatch.setattr(N, "downstream_name", lambda nhd, comid: ("Neuse River", "1013910"))
    t = N.Target(target("x", nhdplus_ids=["77"]), name=None, words=[])
    out, why = N.resolve_unnamed(FakeNhd(), t, idx)
    k, c, how, ids = out[0]
    assert k == ("line", "NC", "comid77") and c["type"] == "comid-line"
    assert c["gnis_name"] == "Unnamed tributary to Neuse River" and "tributary to Neuse River" in how
    assert N.feature_key("NC", c) == k


def test_downstream_name_reads_the_navigation_upstream_first(monkeypatch):
    nav = {"features": [{"properties": {"nhdplus_comid": c}} for c in (77, 78, 79, 80)]}
    http = SimpleNamespace(get=lambda kind, url, params, attempts=3: nav if kind == "nldi-nav" else None)
    monkeypatch.setattr(N, "arcgis", lambda http_, kind, layer, **p: [
        {"comid": 80, "gnis_name": "Neuse River", "gnis_id": "1", "hydroseq": 10},
        {"comid": 78, "gnis_name": None, "hydroseq": 30},
        {"comid": 79, "gnis_name": "Mill Branch", "gnis_id": "2", "hydroseq": 20}])
    assert N.downstream_name(SimpleNamespace(http=http), 77) == ("Mill Branch", "2")


# ---------------------------------------------------------------- budgets and the NLDI limit

class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return SimpleNamespace(status_code=200, headers={}, json=lambda: {"features": []}, text="",
                               raise_for_status=lambda: None)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(N, "PAUSE_S", 0.0)
    return tmp_path


def test_max_requests_stops_before_a_request_and_the_cache_resumes(cache):
    http = N.Http(max_requests=2, nldi_log=cache / "nldi.json")
    http.session = FakeSession()
    http.get("near2", "https://example.invalid/a", {"q": "1"})
    http.get("near2", "https://example.invalid/a", {"q": "2"})
    with pytest.raises(N.BudgetExhausted):
        http.get("near2", "https://example.invalid/a", {"q": "3"})
    assert http.session.calls == 2 and http.requests == 2
    again = N.Http(max_requests=0, nldi_log=cache / "nldi.json")     # the next run: cached answers cost nothing
    again.session = FakeSession()
    assert again.get("near2", "https://example.invalid/a", {"q": "1"}) == {"features": []}
    assert again.session.calls == 0 and again.cached["near2"] == 1


def test_budget_seconds_stops_the_run(cache):
    http = N.Http(deadline=time.monotonic() - 1, nldi_log=cache / "nldi.json")
    http.session = FakeSession()
    with pytest.raises(N.BudgetExhausted, match="budget-s"):
        http.get("gnis2", "https://example.invalid/b", {"q": "1"})
    assert http.session.calls == 0


def test_the_nldi_limit_holds_across_runs(cache):
    log = cache / "nldi.json"
    log.write_text(json.dumps([time.time() - 10] * 3))           # an earlier run's requests this hour
    http = N.Http(deadline=time.monotonic() + 5, nldi_log=log, nldi_per_hour=3)
    http.session = FakeSession()
    http.get("near2", "https://example.invalid/c", {"q": "1"})     # not NLDI: not counted
    with pytest.raises(N.BudgetExhausted, match="NLDI limit"):
        http.get("nldi-position", "https://example.invalid/nldi", {"coords": "POINT(0 0)"})
    old = N.Http(nldi_log=log, nldi_per_hour=4)
    old.session = FakeSession()
    old.get("nldi-position", "https://example.invalid/nldi", {"coords": "POINT(1 1)"})
    assert len(json.loads(log.read_text())) == 4                   # the request is logged for the next run


# ---------------------------------------------------------------- the merge keeps every other state

def test_a_state_build_merges_targets_and_keeps_the_files_statistics(tmp_path, monkeypatch):
    out = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", out)
    prev = {"partial": False, "stats": {"records": 900, "write": {"mode": "merge"}},
            "problems": ["old problem"], "skipped": [{"state": "NY", "text": "storm drain", "reason": "not a water name"}],
            "targets": [{"state": "NY", "name": "Mill Creek", "slugs": ["mill-creek-ny"]}],
            "waters": [{"slug": "mill-creek-ny", "state": "NY", "name": "Mill Creek", "gnis_id": "1"}]}
    out.write_text(json.dumps(prev))
    rows = [{"state": "NC", "name": "Neuse River", "slugs": ["neuse-river-nc"], "define_by": "reach",
             "reach_slugs": {"8791413": "neuse-river-nc"}}]
    rec = {"slug": "neuse-river-nc", "name": "Neuse River", "state": "NC", "gnis_id": "1013910", "kind": "river",
           "_geom": N.shape({"type": "LineString", "coordinates": [[-78, 35], [-77, 35.1]]}), "_targets_n": 1}
    info = N.write_output([rec], rows, [{"state": "NC", "text": "BANKS COUNTY", "reason": "a county"}], ["new"],
                          partial=True, stats={"NC": {"records": 1}}, final=True, scope_states={"NC"})
    d = json.loads(out.read_text())
    assert info["written"] == 2 and [w["slug"] for w in d["waters"]] == ["mill-creek-ny", "neuse-river-nc"]
    assert [t["state"] for t in d["targets"]] == ["NY", "NC"] and d["partial"] is False
    assert d["stats"]["records"] == 900 and d["stats"]["state_builds"]["NC"]["records"] == 1
    assert d["problems"] == ["old problem", "new"] and len(d["skipped"]) == 2


def test_finish_rows_writes_the_reach_slugs():
    rec = {"slug": "neuse-river-nc"}
    rows = N.finish_rows([{"_key": "k", "state": "NC", "name": "Neuse River", "slugs": [], "how": ["x"], "reason": None,
                           "_recs": [rec], "_epa": [(["03020201000171", "8791413"], rec)]}])
    assert rows[0]["reach_slugs"] == {"03020201000171": "neuse-river-nc", "8791413": "neuse-river-nc"}
    assert rows[0]["slugs"] == ["neuse-river-nc"] and "_epa" not in rows[0]


# ---------------------------------------------------------------- the outfall steps of a state build

def matcher():
    mt = OW.Matcher.__new__(OW.Matcher)
    mt.waters = {"neuse-river-nc": {"state": "NC", "name": "Neuse River"},
                 "unnamed-tributary-to-neuse-river-nc": {"state": "NC", "name": "Unnamed tributary to Neuse River"}}
    mt.reach_slugs = {"8791413": "neuse-river-nc"}
    mt.outfall_slugs = {("NC0000009", "001"): ("unnamed-tributary-to-neuse-river-nc", "NLDI position COMID 77")}
    mt.resolver = SimpleNamespace(canon=lambda s: s)
    return mt


def test_an_outfall_is_tied_by_its_own_reach_unless_its_text_names_another_water():
    mt = matcher()
    o = {"state": "NC", "nhdplus_id": "8791413", "reach_id": None}
    assert mt.by_reach(o, "NEUSE RIVER")[0] == "neuse-river-nc"
    assert mt.by_reach(o, "")[0] == "neuse-river-nc"
    assert mt.by_reach(o, "Falling Creek") == (None, None)
    assert mt.by_reach({**o, "state": "SC"}, "") == (None, None)


def test_an_unnamed_outfall_takes_the_builders_water_for_it():
    mt = matcher()
    s, how = mt.by_outfall_ref({"npdes_permit": "NC0000009", "outfall": "001"})
    assert s == "unnamed-tributary-to-neuse-river-nc" and "no receiving-water name" in how
    assert mt.by_outfall_ref({"npdes_permit": "NC0000009", "outfall": "002"}) == (None, None)


# ---------------------------------------------------------------- Florida's inverted GNIS names, the high-resolution pass

def test_inverted_gnis_names_read_as_written():
    assert N.gnis_display("Apopka, Lake") == "Lake Apopka" and N.gnis_display("Marcus, Bayou") == "Bayou Marcus"
    assert N.gnis_display("Neuse River") == "Neuse River"
    assert N.name_score(N.words("Lake Apopka"), "Apopka, Lake") == 1.0
    t = {"name": "Lake Apopka", "words": N.words("Lake Apopka"), "define_by": "reach"}
    assert "APOPKA, LAKE" in N.sql_names(t)
    assert "APOPKA, LAKE" not in N.sql_names({**t, "define_by": None})      # the live runs' queries are unchanged


def test_the_high_resolution_pass_takes_the_nearest_flowline_of_the_name(monkeypatch):
    from shapely.geometry import LineString
    monkeypatch.setattr(N, "arcgis", lambda http, kind, layer, **p: [
        {"gnis_id": "00294329", "gnis_name": "Brooker Creek", "_geom": LineString([(-82.70, 28.08), (-82.69, 28.09)])},
        {"gnis_id": "00999999", "gnis_name": "Other Creek", "_geom": LineString([(-82.70, 28.08), (-82.70, 28.081)])}])
    t = N.Target(target("Brooker Creek", points={(-82.70, 28.08): 1}), define_by="reach")
    c, how = N.resolve_hr(SimpleNamespace(http=None), t)
    assert c["type"] == "hr-line" and c["gnis_id"] == "294329" and "NHD high resolution" in how
    assert N.feature_key("FL", c) == ("line", "FL", "294329")


def test_a_state_build_reads_floridas_receiving_water_text(monkeypatch):
    o = {"receiving_water_echo": "St Johns R Class III Marine WBID 2213H"}
    assert OW.text_of(o) == "St Johns R Class III Marine WBID 2213H"
    monkeypatch.setattr(OW, "STATE_TEXT", True)
    assert OW.text_of(o) == "St Johns River"
    assert OW.text_of({"receiving_water_echo": "BANKS COUNTY"}) == "BANKS COUNTY"
    assert OW.text_of({**o, "receiving_water_override": {"water": "Trout River"}}) == "Trout River"


# ---------------------------------------------------------------- review 2026-11-04: the per-permit tie, the merges, the hourly run

def permit_matcher(dist, reaches):
    """A Matcher whose two Rockfish Creek records are told apart by EPA's point (dist) and the permittee's town
    (reaches): the builder pooled every NC permit naming 'Rockfish Creek' in one target and built the one at Wallace."""
    mt = OW.Matcher.__new__(OW.Matcher)
    mt.waters = {"rockfish-creek-nc": {"state": "NC", "name": "Rockfish Creek", "towns": ["Wallace"]}}
    mt.targets = {("NC", N.compact("Rockfish Creek")): {
        "state": "NC", "name": "Rockfish Creek", "define_by": "reach", "permits": ["NC0000001", "NC0000002"],
        "slugs": ["rockfish-creek-nc"], "how": ["GNIS name in NC, crossing Raeford, Wallace (2 waters of that name)"]}}
    mt.resolver = SimpleNamespace(canon=lambda s: s)
    mt.dis_towns = {}
    mt.dist = lambda slug, lat, lon: dist.get(slug) if lat is not None else None
    mt.reaches_town = lambda slug, o: reaches.get((slug, o.get("city")))
    return mt


def test_the_builders_record_for_the_permit_must_reach_its_town_or_its_point():
    mt = permit_matcher({"rockfish-creek-nc": 110_000}, {("rockfish-creek-nc", "RAEFORD"): False,
                                                        ("rockfish-creek-nc", "WALLACE"): True})
    far = {"state": "NC", "npdes_permit": "NC0000002", "city": "RAEFORD", "lat": 34.98, "lon": -79.22}
    assert mt.by_builder_permit(far, "Rockfish Creek") == (None, None)
    assert "does not reach the permittee's town (raeford)" in mt._builder_far and "110.0 km" in mt._builder_far
    own = {**far, "npdes_permit": "NC0000001", "city": "WALLACE"}
    s, how = mt.by_builder_permit(own, "Rockfish Creek")          # the plant's own town: kept, however far EPA's point
    assert s == "rockfish-creek-nc" and "reaches the permittee's town" in how and mt._builder_far is None


def test_the_builders_record_at_the_point_is_kept_and_an_unknown_town_is_said():
    mt = permit_matcher({"rockfish-creek-nc": 150}, {})
    o = {"state": "NC", "npdes_permit": "NC0000002", "city": "SOMEWHERE", "lat": 34.7, "lon": -78.0}
    assert mt.by_builder_permit(o, "Rockfish Creek")[0] == "rockfish-creek-nc"       # EPA's point on it (TIGHT_M)
    mt = permit_matcher({"rockfish-creek-nc": 5_000}, {})
    assert mt.by_builder_permit(o, "Rockfish Creek") == (None, None)
    assert "could not be checked" in mt._builder_far
    assert mt.by_builder_permit({**o, "lat": None, "lon": None}, "Rockfish Creek")[0] == "rockfish-creek-nc"


def test_a_target_the_budget_did_not_reach_keeps_the_files_row():
    old = [{"state": "NY", "name": "Mill Creek", "slugs": ["mill-creek-ny"], "reason": None}]
    new = [{"state": "NY", "name": "Mill Creek", "slugs": [], "reason": "not reached this run (--budget-s used); the "
            "next run resumes"}]
    assert N.merge_targets(old, new) == old
    resolved = [{"state": "NY", "name": "Mill Creek", "slugs": [], "reason": "no NHD flowline of that name"}]
    assert N.merge_targets(old, resolved) == resolved


def test_a_state_build_keeps_other_states_rows_exactly(tmp_path, monkeypatch):
    out = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", out)
    site = {"state": "NJ", "name": None, "texts": ["57th St (Avalon Borough)"], "slugs": []}
    prev = {"partial": False, "stats": {}, "problems": [], "skipped": [], "waters": [],
            "targets": [site, {**site, "points": 2}, {"state": "NJ", "name": "Cooper River", "slugs": ["cooper-river-nj"]}]}
    out.write_text(json.dumps(prev))
    N.write_output([], [{"state": "NC", "name": "Neuse River", "slugs": []}], [], [], partial=True, stats={},
                   final=True, scope_states={"NC"})
    d = json.loads(out.read_text())
    assert d["targets"][:3] == prev["targets"] and d["targets"][3]["state"] == "NC"


def test_a_live_run_keeps_the_state_builds(tmp_path, monkeypatch):
    out = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", out)
    line = N.shape({"type": "LineString", "coordinates": [[-78, 35], [-77, 35.1]]})
    nc = {"slug": "neuse-river-nc", "state": "NC", "name": "Neuse River", "gnis_id": "1013910"}
    prev = {"partial": False, "stats": {"state_builds": {"NC": {"records": 1}}}, "problems": [],
            "skipped": [{"state": "NC", "text": "BANKS COUNTY", "reason": "a county"}],
            "targets": [{"state": "NC", "name": "Neuse River", "slugs": ["neuse-river-nc"], "define_by": "reach",
                         "reach_slugs": {"8791413": "neuse-river-nc"}}],
            "waters": [nc, {"slug": "mill-creek-ny", "state": "NY", "name": "Mill Creek", "gnis_id": "1"}]}
    rec = {"slug": "mill-creek-ny", "name": "Mill Creek", "state": "NY", "gnis_id": "1", "kind": "stream",
           "_geom": line, "_targets_n": 1}
    for rebuild in (False, True):
        out.write_text(json.dumps(prev))
        info = N.write_output([rec], [{"state": "NY", "name": "Mill Creek", "slugs": ["mill-creek-ny"]}], [], [],
                              partial=False, stats={"records": 1}, final=True, rebuild=rebuild)
        d = json.loads(out.read_text())
        assert sorted(w["slug"] for w in d["waters"]) == ["mill-creek-ny", "neuse-river-nc"], rebuild
        assert info["dropped"] == 0 and [t["state"] for t in d["targets"]] == ["NY", "NC"]
        assert d["targets"][1]["reach_slugs"] == {"8791413": "neuse-river-nc"}
        assert d["skipped"] == prev["skipped"] and d["stats"]["state_builds"] == {"NC": {"records": 1}}


def test_the_hourly_run_gives_the_nhd_build_a_budget():
    import subprocess
    root = Path(__file__).resolve().parents[2]
    run = lambda *a: subprocess.run(["make", "-n", "--no-print-directory", *a], cwd=root, capture_output=True,
                                    text=True, check=True).stdout
    assert "-m ingest.waters_from_nhd --budget-s" in run("waters-nhd")
    ingest = run("ingest")
    loop = ingest.split("; do", 1)[0]                       # the feed loop's module list
    assert "waters_from_nhd" not in loop and "waters-nhd" in ingest


# ---------------------------------------------------------------- review 2026-11-04 WA: artificial paths, far snaps

def seattle_matcher(dist):
    """Lake Union's record, the unnamed NHDPlus artificial path NLDI snapped a lakeside outfall to, and a creek in
    another county that a snap at EPA's wrong point found."""
    mt = OW.Matcher.__new__(OW.Matcher)
    mt.waters = {"lake-union-wa": {"state": "WA", "name": "Lake Union", "kind": "lake", "nhd_fcodes": [39004]},
                 "unnamed-stream-near-seattle-wa": {"state": "WA", "name": "Unnamed stream near Seattle",
                                                    "kind": "stream", "nhd_fcodes": [55800]},
                 "possession-sound-wa": {"state": "WA", "name": "Possession Sound", "nhd_fcodes": [56600]},
                 "blackjack-creek-wa": {"state": "WA", "name": "Blackjack Creek", "nhd_fcodes": [46006]}}
    mt.reach_slugs = {}
    mt.outfall_slugs = {("WA0031682", "124"): ("unnamed-stream-near-seattle-wa", "NLDI position COMID 24537864"),
                        ("WA0031682", "170"): ("blackjack-creek-wa", "NLDI position COMID 1")}
    mt.dis_waters = {}
    mt.dist = lambda slug, lat, lon: dist.get(slug) if lat is not None else None
    near = {"lake-union-wa": 3}
    mt.resolver = SimpleNamespace(canon=lambda s: s, by_point=lambda lat, lon, st: min(
        ((d, s) for s, d in near.items()), default=None))
    mt.by_point = lambda o, text: (("lake-union-wa", "the water record at the outfall's point (3 m)")
                                   if o["outfall"] == "124" else (None, None))
    return mt


def test_an_unnamed_artificial_path_is_never_an_outfalls_water():
    mt = seattle_matcher({"unnamed-stream-near-seattle-wa": 1681, "lake-union-wa": 3})
    assert mt.line_only("unnamed-stream-near-seattle-wa")
    assert not mt.line_only("possession-sound-wa")                 # a named coastline keeps its own name
    assert not mt.line_only("lake-union-wa")
    o = {"state": "WA", "npdes_permit": "WA0031682", "outfall": "124", "lat": 47.6266, "lon": -122.3386}
    res = mt.match(o)
    assert res["slug"] == "lake-union-wa" and res["step"] == "point"
    mt.by_point = lambda o, text: ("unnamed-stream-near-seattle-wa", "the water record at the outfall's point (0 m)")
    res = mt.match(o)
    assert res["slug"] is None and "artificial path or coastline" in mt.reason(o, "", None)


def test_the_builders_snap_for_an_outfall_must_lie_at_the_rows_own_point():
    mt = seattle_matcher({"blackjack-creek-wa": 29_435})
    o = {"state": "WA", "npdes_permit": "WA0031682", "outfall": "170", "lat": 47.5388, "lon": -122.3628}
    res = mt.match(o)
    assert res["slug"] is None
    assert "lies 29435 m from the row's point" in mt.reason(o, "", None)
    mt = seattle_matcher({"blackjack-creek-wa": 120})
    res = mt.match(o)
    assert res["slug"] == "blackjack-creek-wa" and res["step"] == "NHD builder"
    assert mt.match({**o, "lat": None, "lon": None})["slug"] == "blackjack-creek-wa"   # no point: as the builder chose


def test_a_bay_drawn_by_its_coastline_is_a_bay_not_a_stream():
    """Review 2026-11-04 WA: Budd Inlet, Padilla Bay and Possession Sound came from NHDPlus coastline flowlines and were
    kinded stream."""
    assert N.kind_of("Budd Inlet", "line", fcodes=[56600]) == "bay"
    assert N.kind_of("Possession Sound", "line", fcodes=[56600]) == "bay"
    assert N.kind_of("Harbor Creek", "line", fcodes=[46006]) == "stream"
    assert N.kind_of("Bay River", "line", fcodes=[46006]) == "river"
    w = {r["slug"]: r for r in json.loads((Path(__file__).resolve().parents[2] / "data" / "waters-nhd.json").read_text())["waters"]}
    assert w["budd-inlet-wa"]["kind"] == "bay"
    # Padilla Bay's and Possession Sound's NHD records were dropped for openboatlaunch's by the tidy (2026-11-06):
    # the records the site reads are a bay and a sound, never a stream
    from build import status as S
    loaded = S.load_waters()
    assert "padilla-bay-wa" not in w and "possession-sound-wa" not in w
    assert loaded["padilla-bay-wa"]["kind"] == "bay" and loaded["possession-sound-wa"]["kind"] == "sound"


def test_an_artificial_path_at_the_point_does_not_contradict_the_inventorys_name():
    """Review 2026-11-04 WA: King County's outfall 027B ('Elliot Bay/Puget Sound') was said to lie on 'Unnamed stream
    near Seattle', which is Elliott Bay's coastline: the name and the point do not disagree."""
    mt = seattle_matcher({})
    mt.waters["unnamed-stream-near-seattle-23989539-wa"] = {"state": "WA", "name": "Unnamed stream near Seattle",
                                                            "nhd_fcodes": [56600]}
    mt.resolver = SimpleNamespace(canon=lambda s: s,
                                  by_point=lambda lat, lon, st: (147, "unnamed-stream-near-seattle-23989539-wa"))
    for f in ("by_name", "by_nhd_target", "by_reach", "by_builder_permit", "by_point"):
        setattr(mt, f, lambda o, text: (None, None))
    mt.by_name_and_town = lambda o, text: (None, None)
    mt.reason = lambda o, text, not_name: mt._conflict or "no record"
    o = {"state": "WA", "npdes_permit": "WA0029181", "outfall": "027B", "lat": 47.6, "lon": -122.34,
         "receiving_water_echo": "Elliot Bay/Puget Sound"}
    assert mt.match(o, {})["reason"] == "no record" and mt._conflict is None
