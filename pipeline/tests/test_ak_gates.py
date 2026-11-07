"""Alaska's go-live gates (2026-11-07, final audit docs/checklists/2026-11-07-ak-final.md in the site repository): the
two plant outfalls scripts/ak_gate_ties.py ties by EPA's limit-set names, Koyuk's borrowed point set aside, the
untied rows' reasons saying that NHDPlus V2.1 has no Alaska data, and the radar rainfall left to the contiguous states.
Data tests on the files as committed and unit tests; no network.
Run from pipeline/: python -m pytest tests/test_ak_gates.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _script():
    spec = importlib.util.spec_from_file_location("ak_gate_ties", ROOT / "scripts" / "ak_gate_ties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ak_rows():
    return [r for r in common.load_outfall_registry(DATA, provisional=False) if r.get("state") == "AK"]


def _row(permit, outfall):
    got = [r for r in _ak_rows() if r["npdes_permit"] == permit and str(r.get("outfall")) == outfall]
    assert len(got) == 1
    return got[0]


def test_every_open_alaska_outfall_has_a_water_record_or_a_reason():
    from build import status as S
    waters = S.load_waters()
    rows = [r for r in _ak_rows() if not str(r.get("outfall_status") or "").upper().startswith("CLS")]
    assert len(rows) == 109         # 110 in EPA's lists less the pipeline's 'CSO' feature (held back)
    tied = [r for r in rows if r.get("water_slug")]
    assert len(tied) == 38          # 29 by the water batch of 2026-11-07 (and 004 moved), 9 by scripts/ak_gate_ties.py
    assert all(r["water_slug"] in waters for r in tied)
    assert all(r.get("no_water_reason") for r in rows if not r.get("water_slug"))


def test_the_two_coves_go_to_the_water_epas_limit_sets_name():
    for permit, slug, words in (("AKG572007", "glacier-bay-ak", "Bartlett Cove, Glacier Bay"),
                                ("AKG572111", "carroll-inlet-ak", "SHOAL COVE IN CARROLL INLET")):
        o = _row(permit, "001")
        assert o["water_slug"] == slug
        assert any(words in n for n in o["limit_set_names"])          # EPA's own text names the larger water
        assert words in o["receiving_water_override"]["basis"]
        assert o["water_matched_by"].startswith("scripts/ak_gate_ties.py")
        assert o["match"] == "geometry+name" and o["distance_m"] <= 400
        assert "no_water_reason" not in o


def test_three_lagoons_go_to_the_river_their_limit_sets_name():
    """EPA's inventory gives these lagoons no receiving water; their limit sets name the river (the tie step does not
    read limit-set names). Chuathbaluk's outfall 001 discharges to wetlands by its own limit sets and stays untied."""
    for permit, outfall, slug, river in (("AKG573010", "001", "naknek-river-ak", "NAKNEK RIVER"),
                                         ("AKG573029", "001", "naknek-river-ak", "NAKNEK RIVER"),
                                         ("AKG573002", "002", "kuskokwim-river-ak", "KUSKOKWIM RIVER")):
        o = _row(permit, outfall)
        assert o["receiving_water_echo"] is None and o["water_slug"] == slug
        assert any(river in n.upper() for n in o["limit_set_names"])
        assert o["match"] == ("geometry+name" if o["distance_m"] <= 400 else "name_only")
    assert not _row("AKG573002", "001").get("water_slug")


def test_koyuks_point_in_nome_is_kept_aside_and_not_used():
    o = _row("AKG570023", "None")
    assert o["lat"] is None and o["lon"] is None
    assert (o["echo_lat"], o["echo_lon"]) == (64.5077, -165.4377)
    assert "Nome" in o["coords_problem"] and "209 km" in o["coords_problem"]
    assert not o.get("water_slug")


def test_no_untied_alaska_row_says_no_named_nhd_water_is_near():
    """NHDPlus V2.1 holds no Alaska data: its steps' silence is not evidence that no water of the name is near."""
    untied = [r for r in _ak_rows() if not r.get("water_slug")]
    assert not [r for r in untied if "no named NHD water nearby" in (r.get("water_match") or "")]
    said = Counter("has no data for Alaska" in (r.get("no_water_reason") or "") for r in untied)
    assert said[True] >= 50
    for r in untied:
        assert r["water_match"] == "none: " + r["no_water_reason"]


def test_the_table_is_what_the_files_say():
    mod = _script()
    docs = {k: json.loads((DATA / n).read_text()) for k, n in mod.FILES.items()}
    before = json.dumps(docs, sort_keys=True)
    from build import status as S
    assert mod.apply(docs, S.load_waters()) == []
    assert json.dumps(docs, sort_keys=True) == before


def test_a_row_whose_text_or_point_changed_is_not_tied_by_the_table():
    mod = _script()
    docs = {"us": {"outfalls": []}, "plants": {"outfalls": [
        {"npdes_permit": "AKG572007", "outfall": "001", "state": "AK", "receiving_water_echo": "Glacier Bay",
         "coords_from": "permitted_feature", "lat": 58.455, "lon": -135.887},
        {"npdes_permit": "AKG570023", "outfall": None, "state": "AK", "receiving_water_echo": "KOYUK INLET OF NORTON SOUND",
         "coords_from": "permitted_feature", "lat": 64.93, "lon": -161.15}]}}
    missing = mod.apply(docs, {"glacier-bay-ak": {"name": "Glacier Bay", "kind": "bay"},
                               "carroll-inlet-ak": {"name": "Carroll Inlet", "kind": "bay"}})
    assert {"AKG572007/001", "AKG572111/001", "AKG570023/None"} <= set(missing)
    a, k = docs["plants"]["outfalls"]
    assert "water_slug" not in a and k["lat"] == 64.93


def test_the_reword_touches_alaska_untied_rows_only():
    mod = _script()
    old = "none: NHD builder: no NHD flowline or waterbody of that name within 2 km (no named NHD water nearby)"
    rows = [{"state": "AK", "water_match": old, "no_water_reason": old[6:], "lat": 1.0},
            {"state": "WA", "water_match": old, "no_water_reason": old[6:], "lat": 1.0},
            {"state": "AK", "water_slug": "x-ak", "water_match": old, "lat": 1.0},
            {"state": "AK", "water_match": "none: " + mod.NO_TEXT, "no_water_reason": mod.NO_TEXT, "lat": 1.0},
            {"state": "AK", "water_match": "none: " + mod.NO_TEXT, "no_water_reason": mod.NO_TEXT, "lat": None}]
    for r in rows:
        mod.reword(r)
    assert rows[0]["water_match"] == "none: NHD builder: " + mod.GAP and rows[0]["no_water_reason"] == "NHD builder: " + mod.GAP
    assert rows[1]["water_match"] == old and rows[2]["water_match"] == old
    assert rows[3]["no_water_reason"].endswith("(NLDI snaps no point there)")
    assert rows[4]["no_water_reason"] == mod.NO_TEXT                   # no point: NLDI was never asked
    mod.reword(rows[3])
    assert rows[3]["no_water_reason"].count("NLDI") == 1               # idempotent


def test_the_nhd_builder_says_nhdplus_has_no_alaska_data():
    from ingest import waters_from_nhd as N
    assert N.nhdplus_gap("AK") == "NHDPlus V2.1, which this step reads, has no data for Alaska"
    assert N.nhdplus_gap("ak") and N.nhdplus_gap("WA") is None and N.nhdplus_gap(None) is None

    class Fake:
        def nldi(self, lon, lat):
            return None

        def near(self, layer, lon, lat, radius=None):
            return []

    t = {"state": "AK", "words": ["taiya", "inlet"], "point_mode": False}
    got, why = N.resolve_point(Fake(), t, -135.32, 59.45)
    assert got is None and why == N.nhdplus_gap("AK")
    got, why = N.resolve_point(Fake(), {**t, "state": "WA"}, -122.3, 47.6)
    assert why == "no NHD flowline or waterbody of that name within 2 km (no named NHD water nearby)"
    t = {"state": "AK", "points": Counter({(-148.6, 70.26): 1}), "reach_ids": [], "nhdplus_ids": []}
    feats, why = N.resolve_unnamed(type("F", (Fake,), {})(), t, {})
    assert feats == [] and why == f"{N.nhdplus_gap('AK')}: NLDI snaps no point there"


def test_the_radar_reads_no_state_outside_its_grid():
    """The rainfall product is the contiguous states' grid (conus_QPE_*). Juneau's outfalls (58.3 N) and the pipeline
    row at Prudhoe Bay (70.26 N) would stretch the one export box for every state to 8,146 x 3,883 pixels and get no
    value; Alaska's combined sewer permits stay listed in rain_caution_states with covered false."""
    from ingest import rainfall as RF
    from build import rain_likely as RL
    assert RF.radar_states({"AK", "WA", "NY"}) == {"WA", "NY"}
    assert {"AK", "HI", "PR"} <= RF.OUTSIDE_RADAR_GRID
    got = RF.cso_outfalls(live={"AK"})
    assert got == []
    cov = RL.caution_coverage({"enabled": True, "permits": {}}, {"AK": {"AK0023213"}})["AK"]
    assert cov["covered"] is False and cov["cso_permits"] == 1
    assert "does not read rainfall" in cov["sentence"]


def test_alaskas_monitored_rows_start_with_page_health_only():
    """Collection checklist section 3: a new row starts with records false (the register's default is true)."""
    rows = json.loads((DATA / "notice-channels" / "ak.json").read_text())["channels"]
    mon = sorted(r["id"] for r in rows if r.get("monitored"))
    assert mon == ["ak-ahab-network", "ak-juneau-douglas-cso-public-notification"]
    assert all(r.get("records") is False and r.get("every_hours") == 24 for r in rows if r.get("monitored"))


def test_juneaus_outfalls_go_to_gastineau_channel_by_the_permits_text():
    """Permit AK0023213 names Gastineau Channel for the plant (001) and the CSO outfalls of Table I.D.1 (N-11, N11.2,
    N-15.1: 002, 003, 004). 004 leaves Douglas Boat Harbor, which only the outline rule had given it."""
    from build import status as S
    w = S.load_waters()["gastineau-channel-ak"]
    assert w["source"] == "census" and w["hand"] is True and w["tiger_ids"] == ["11050889607"]
    assert "Table I.D.1" in w["note"] and w["kind"] == "bay"
    for o in ("001", "002", "003", "004"):
        r = _row("AK0023213", o)
        assert r["water_slug"] == "gastineau-channel-ak" and r["receiving_water_echo"] == "Gastineau Channel"
        assert "to the Gastineau Channel" in r["receiving_water_override"]["basis"]
        assert r["distance_m"] <= 150 and r["match"] == "geometry+name"
        assert r["outfall_kind"] == ("plant" if o == "001" else "cso")


def test_the_pipelines_cso_feature_is_held_back_by_epas_record():
    doc = json.loads((DATA / "outfalls-us.json").read_text())
    held = {x["npdes_permit"]: x for x in doc["excluded_not_sewage"]}
    assert held["AKG320002"]["reason"] == "not_a_combined_sewer"
    assert "Crude Petroleum Pipelines" in held["AKG320002"]["basis"]
    assert any(o["npdes_permit"] == "AKG320002" for o in doc["outfalls"])        # EPA's row kept as listed
    assert not [r for r in _ak_rows() if r["npdes_permit"] == "AKG320002"]          # no reader sees it
    assert {r["npdes_permit"] for r in _ak_rows() if r["outfall_kind"] == "cso"} == {"AK0023213"}
