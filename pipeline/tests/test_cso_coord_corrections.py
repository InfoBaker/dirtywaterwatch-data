"""Cited corrections to open combined sewer outfall rows without a usable point (scripts/cso_coord_corrections.py,
research/cso-missing-coords, 2026-11-15): Bridgeport West Side 145 at Connecticut DEEP's point, three Massachusetts
co-permittee listings kind "other", four terminated Michigan rows with a true no_point_reason. Data tests on the files
as committed; no network.
Run from pipeline/: python -m pytest tests/test_cso_coord_corrections.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CT = ("CT0100056", "145")
CT_POINT = (41.166149273344594, -73.18194339093611)
EPA_CT_POINT = (41.04481, -73.540018)


def _script():
    spec = importlib.util.spec_from_file_location("cso_coord_corrections", ROOT / "scripts" / "cso_coord_corrections.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _docs(mod):
    return {n: json.loads((DATA / n).read_text()) for n in mod.files_needed(mod.load_points())}


def _registry():
    return {(o.get("npdes_permit"), o.get("outfall")): o for o in common.load_outfall_registry(DATA, provisional=False)}


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def test_each_point_correction_is_cited_and_near_its_operators_other_outfalls():
    mod = _script()
    reg = common.load_outfall_registry(DATA, provisional=False)
    for c in mod.load_points():
        for k in ("npdes_permit", "outfall", "lat", "lon", "coords_from", "coords_note", "source_name", "source_url",
                  "read_at", "registry_file"):
            assert c.get(k) not in (None, ""), (c["npdes_permit"], k)
        assert c["source_url"].startswith("https://") and c["read_at"].startswith("2026-")
        assert c["coords_from"] in {"state outfall layer", "permit", "operator map layer"}
        assert (DATA / Path(c["registry_file"]).name).exists()
        others = [(o["lat"], o["lon"]) for o in reg if o.get("npdes_permit") == c["npdes_permit"]
                  and o.get("outfall") != c["outfall"] and o.get("lat") is not None]
        assert others and min(_km((c["lat"], c["lon"]), p) for p in others) < 10


def test_the_tables_are_what_the_files_say():
    mod = _script()
    docs = _docs(mod)
    assert mod.check(docs, mod.load_points()) == []
    before = {n: mod.dumps(d) for n, d in docs.items()}
    moved, problems = mod.apply_tables(docs, mod.load_points())
    assert moved == [] and problems == []
    assert {n: mod.dumps(d) for n, d in docs.items()} == before      # a second run changes nothing


def test_bridgeport_145_carries_ct_deeps_point_with_epas_kept_aside():
    o = _registry()[CT]
    assert (o["lat"], o["lon"]) == CT_POINT
    assert o["coords_from"] == "state outfall layer" and "CSO_and_CSO_Groups" in o["coords_source"]["url"]
    assert (o["epa_lat"], o["epa_lon"]) == EPA_CT_POINT and o["epa_reach_id"] and not o.get("reach_id")
    for k in ("coords_problem", "echo_lat", "echo_lon", "no_point_reason", "replaced_match"):
        assert k not in o, k
    assert o["water_slug"] == "bridgeport-harbor-ct" and o["distance_m"] is not None and "geometry" in o["match"]
    assert o["_file"] == "data/outfalls-new-england.json"


def test_the_rain_check_reads_bridgeport_145_and_not_the_co_permittee_listings():
    from ingest import rainfall
    out = rainfall.cso_outfalls()
    ct = [o for o in out if (o["permit"], o["outfall"]) == CT]
    assert len(ct) == 1 and (ct[0]["lat"], ct[0]["lon"]) == CT_POINT
    assert not [o for o in out if o["permit"] in {"MAC010510", "MAC010617", "MAC010986"}]


def test_the_co_permittee_listings_are_kind_other_and_stay_in_the_registry():
    mod = _script()
    reg = _registry()
    for (permit, outfall), (_name, _text, note) in mod.KIND_OTHER.items():
        o = reg[(permit, outfall)]
        assert o["outfall_kind"] == "other" and o["kind_note"] == note and o["lat"] is None
        assert "co-permittee" in note and permit in note


def test_the_terminated_michigan_rows_say_why_they_have_no_point_and_claim_no_plant_reading():
    mod = _script()
    reg = common.load_outfall_registry(DATA, provisional=False)
    by_key = {(o.get("npdes_permit"), o.get("outfall")): o for o in reg}
    for (permit, outfall), (_name, reason) in mod.NO_POINT.items():
        o = by_key[(permit, outfall)]
        assert o["lat"] is None and o["no_point_reason"] == reason and "terminated" in reason
        assert "read at the operator's plant" not in reason
        assert not [r for r in reg if r.get("npdes_permit") == permit and r.get("outfall_kind") == "plant"]


def test_open_cso_rows_without_a_point_are_the_22_left():
    from ingest import rainfall
    radar = rainfall.radar_states()
    left = sorted((o["npdes_permit"], o["outfall"]) for o in common.load_outfall_registry(DATA, provisional=False)
                  if (o.get("outfall_kind") or "cso") == "cso" and not str(o.get("outfall_status") or "").startswith("CLS")
                  and o.get("rain_caution") is not False
                  and str(o.get("state") or o["npdes_permit"][:2]).upper() in radar
                  and (o.get("lat") is None or o.get("lon") is None))
    assert CT not in left and not [k for k in left if k[0].startswith("MAC0")]
    assert len(left) <= 22, left


def test_a_row_with_a_point_of_its_own_is_not_overwritten():
    mod = _script()
    c = mod.load_points()[0]
    row = {"npdes_permit": c["npdes_permit"], "outfall": c["outfall"], "outfall_kind": "cso", "lat": 41.17, "lon": -73.18,
           "coords_from": "permitted_feature"}
    keep = copy.deepcopy(row)
    assert "a point of its own" in mod.apply_point(row, c)
    assert row == keep


def test_a_listing_whose_epa_text_changed_is_left_alone():
    mod = _script()
    docs = {"outfalls-new-england.json": {"outfalls": [
        {"npdes_permit": "MAC010510", "outfall": "001", "outfall_name": "MAIN STREET OUTFALL", "lat": None, "lon": None}]},
        "outfalls-us.json": {"outfalls": []}}
    _moved, problems = mod.apply_tables(docs, [])
    assert any("MAC010510 001" in p for p in problems)
    assert "outfall_kind" not in docs["outfalls-new-england.json"]["outfalls"][0]


def test_check_fails_on_a_row_altered_by_hand():
    mod = _script()
    docs = _docs(mod)
    o = next(r for r in docs["outfalls-new-england.json"]["outfalls"] if (r["npdes_permit"], r["outfall"]) == CT)
    o["coords_problem"] = "restored by hand"
    assert any("CT0100056 145" in b for b in mod.check(docs, mod.load_points()))


def test_a_ties_run_cannot_put_epas_point_back():
    """ingest.outfall_waters restores echo_lat/echo_lon on a row that still has coords_problem; the corrected row has
    neither, so a re-tie keeps the cited point and the water."""
    from collections import Counter, defaultdict
    from ingest import outfall_waters as ow
    o = copy.deepcopy(next(r for r in json.loads((DATA / "outfalls-new-england.json").read_text())["outfalls"]
                           if (r["npdes_permit"], r["outfall"]) == CT))
    ow.match_cso_row(ow.Matcher(offline=True), "outfalls-new-england.json", o, Counter(), [], defaultdict(Counter))
    assert (o["lat"], o["lon"]) == CT_POINT and o["water_slug"] == "bridgeport-harbor-ct"
    assert "coords_problem" not in o
