"""California's go-live gates (2026-11-06): the big coastal plants' outfalls given their permits' receiving waters and,
where EPA gives none, the permits' points (scripts/ca_gate_ties.py). Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_ca_gates.py -q
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "scripts"))

import ca_gate_ties as C  # noqa: E402


def _rows():
    docs = {k: json.loads((DATA / n).read_text()) for k, n in C.FILES.items()}
    return {(k, o.get("npdes_permit"), str(o.get("outfall"))): o for k, d in docs.items() for o in d["outfalls"]}


def test_every_row_of_the_table_carries_the_permits_water_and_its_citation():
    rows = _rows()
    assert len(C.TABLE) == 38
    bayside = [k for k in C.TABLE if k[0] == "us" and k[1] == "CA0037664"]
    assert len(bayside) == 29                       # the stipulation's 29 Bayside combined sewer discharge outfalls
    for key, (slug, water, basis) in C.TABLE.items():
        o = rows[key]
        ov = o["receiving_water_override"]
        assert ov["water"] == water and ov["basis"].startswith(basis) and "CA go-live gates" in ov["basis"]
        assert any(x in basis for x in ("Order R2-2013-0029", "Order R8-2021-0010", "Order R4-2023-0033",
                                        "EPA's inventory gives"))
        assert OW.text_of(o) == water                # the ties pass reads the permit's water, not EPA's text
        for word in ("owner", "docs/", "agent"):
            assert word not in ov["basis"]


def test_the_bayside_outfalls_are_never_read_as_the_pacific_ocean():
    rows = _rows()
    for key in C.TABLE:
        if key[1] == "CA0037664":
            assert "pacific" not in OW.text_of(rows[key]).lower()
    assert rows[("us", "CA0037664", "013")]["receiving_water_echo"] == "Pacific Ocean"     # EPA's own text is kept


def test_no_row_is_tied_to_a_record_that_is_not_on_file_and_each_untied_row_says_why():
    waters = S.load_waters()
    rows = _rows()
    for key, (slug, water, _) in C.TABLE.items():
        o = rows[key]
        if o.get("water_slug"):
            assert o["water_slug"] == slug and slug in waters
        else:
            assert o["match"] == "none" and water in o["no_water_reason"] and slug in o["no_water_reason"]
    ca = [o for o in rows.values() if o.get("state") == "CA" and o.get("water_slug")]
    assert all(o["water_slug"] in waters for o in ca)          # the share line counts only records on file


def test_the_deep_ocean_outfalls_with_epas_sign_dropped_point_take_their_permits_point():
    rows = _rows()
    want = {("plants", "CA0110604", "001"): (33.576667, -118.01), ("plants", "CA0110604", "002"): (33.615556, -117.970278),
            ("plants", "CA0109991", "002"): (33.91197, -118.52145)}
    assert set(C.MOVE) == set(want) | set(BAYSIDE_MOVES)
    for key, (lat, lon) in want.items():
        o = rows[key]
        assert (o["lat"], o["lon"]) == (lat, lon) and o["coords_from"] == "permit"
        # EPA's inventory gives the same figures without the minus sign (review of 2026-11-06): kept, and said so
        assert (o["epa_lat"], o["epa_lon"]) == (lat, -lon) == (o["echo_lat"], o["echo_lon"])
        assert "Order R" in o["coords_note"] and "without the longitude's minus sign" in o["coords_note"]
        assert "gives no point" not in o["coords_note"]
        # the flag on EPA's point is cleared: reaches.py skips a row that carries one (the 78-inch outfall, 1.5 miles
        # out, gets its stretch)
        assert "coords_problem" not in o


# review of 2026-11-06, P3-4: the point taken and EPA's inventory point
# Laguna Street takes the 2008 revised tentative order's point (37 48 22 N, 122 25 53 W): the cited point nearest the
# shore (review of 2026-11-06, ca-bays P3-3)
BAYSIDE_MOVES = {("us", "CA0037664", "011"): ((37.806111, -122.431389), (37.80611, -122.38))}


def test_laguna_street_takes_the_2008_orders_point_brannan_and_sunnydale_keep_epas():
    rows = _rows()
    for key, ((lat, lon), (elat, elon)) in BAYSIDE_MOVES.items():
        o = rows[key]
        assert (o["lat"], o["lon"]) == (lat, lon) and o["coords_from"] == "permit"
        assert (o["epa_lat"], o["epa_lon"]) == (elat, elon)
        assert o["coords_note"].startswith("the " + C.ORDER_2008) and "EPA's inventory gives" in o["coords_note"]
        assert C.BAYSIDE in o["coords_note"] and C.POINT_RULE in o["coords_note"]
        assert abs((37 + 48 / 60 + 22 / 3600) - lat) < 1e-6 and abs((122 + 25 / 60 + 53 / 3600) + lon) < 1e-6
        assert C.TABLE[key][0] == C.SFB_SLUG            # the water is unchanged: San Francisco Bay
    # Brannan Street (019): EPA's point is the 2008 tentative order's (37 47 7 N, 122 23 24 W); Table 2's 122 22 24 W
    # lies out in the bay. Sunnydale Avenue (043): Table 2 prints Quint Street's point. Neither is moved.
    for oid in ("019", "043"):
        o = rows[("us", "CA0037664", oid)]
        assert ("us", "CA0037664", oid) not in C.MOVE and o["coords_from"] != "permit"
        # the row carries why, with the records cited and the rule applied (review of 2026-11-06, ca-bays P3-4)
        assert o["coords_note"] == C.NOTE[("us", "CA0037664", oid)]
        assert C.BAYSIDE in o["coords_note"] and "R2-2008-00XX" in o["coords_note"] and C.POINT_RULE in o["coords_note"]
    assert C.POINT_RULE in rows[("us", "CA0037664", "011")]["coords_note"]
    assert set(C.NOTE).isdisjoint(C.MOVE)
    assert (rows[("us", "CA0037664", "019")]["lat"], rows[("us", "CA0037664", "019")]["lon"]) == (37.785278, -122.39)
    assert abs((37 + 47 / 60 + 7 / 3600) - 37.785278) < 1e-6 and abs((122 + 23 / 60 + 24 / 3600) - 122.39) < 1e-9


def test_moving_a_row_to_the_permits_point_keeps_epas_point_and_clears_its_flag_and_is_idempotent():
    o = {"lat": None, "lon": None, "echo_lat": 33.6, "echo_lon": 117.9, "coords_from": "permitted_feature",
         "coords_problem": "EPA's point (33.6, 117.9) lies more than about 2 km outside CA"}
    C.move(o, 33.6, -117.9, "note")
    assert (o["lat"], o["lon"], o["epa_lat"], o["epa_lon"]) == (33.6, -117.9, 33.6, 117.9) and "coords_problem" not in o
    once = dict(o)
    C.move(o, 33.6, -117.9, "note")
    assert o == once
    p = {"lat": 37.8, "lon": -122.4, "coords_from": "permitted_feature"}
    C.move(p, 37.81, -122.43, "note")
    assert (p["epa_lat"], p["epa_lon"]) == (37.8, -122.4)
    # 33 34 36 N, 118 00 36 W and 33 36 56 N, 117 58 13 W, as the order prints them
    assert abs((33 + 34 / 60 + 36 / 3600) - 33.576667) < 1e-6 and abs((118 + 0 / 60 + 36 / 3600) - 118.01) < 1e-9
    assert abs((33 + 36 / 60 + 56 / 3600) - 33.615556) < 1e-6 and abs((117 + 58 / 60 + 13 / 3600) - 117.970278) < 1e-6


def test_the_script_finds_the_files_as_the_table_says():
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "ca_gate_ties.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_once_openboatlaunchs_bay_record_is_on_file_the_permits_water_finds_it_by_name():
    waters = copy.deepcopy({s: w for s, w in S.load_waters().items() if w.get("state") == "CA"})
    waters["san-francisco-bay-ca"] = {"slug": "san-francisco-bay-ca", "name": "San Francisco Bay", "kind": "bay",
                                      "state": "CA", "towns": ["San Francisco", "Oakland"], "wikidata": "Q232264",
                                      "bbox": [-122.50742, 37.44598, -122.03392, 37.98309]}
    waters["pacific-ocean-ca"] = {"slug": "pacific-ocean-ca", "name": "Pacific Ocean", "kind": "bay", "state": "CA",
                                  "towns": [], "bbox": None}
    r = S.Resolver(waters, [], placement_rules={})
    assert r.by_name("San Francisco Bay", "CA", None, None)[0] == ["san-francisco-bay-ca"]
    assert r.by_name("Pacific Ocean", "CA", None, None)[0] == ["pacific-ocean-ca"]


def test_the_oceanwell_test_vessel_is_held_back_as_no_sewage_plant_by_its_epa_record():
    """CA final audit (2026-11-06): CA0000018 entered the plants file by its POTW component, but EPA's record classes it
    NON-POTW with no sewerage code, and its limit sets are brine and freshwater outfalls of six test sites."""
    import ast
    import common
    root = Path(__file__).resolve().parents[2]
    doc = json.loads((root / "data" / "outfalls-plants-us.json").read_text())
    assert not [r for r in doc["outfalls"] if r.get("npdes_permit") == "CA0000018"]
    ex = [x for x in doc["excluded_not_sewage"] if x["npdes_permit"] == "CA0000018"]
    assert len(ex) == 1 and ex[0]["reason"] == "not_a_sewage_plant" and ex[0]["facility_type"] == "NON-POTW"
    assert "NON-POTW" in ex[0]["basis"] and "BRINE OUTFALL" in ex[0]["basis"] and "ECHO" in ex[0]["basis"]
    assert doc["counts"]["excluded_not_sewage"]["not_a_sewage_plant"] == 1
    assert doc["count"] == len(doc["outfalls"]) == sum(doc["counts"]["by_state"].values())
    assert not [r for r in common.load_outfall_registry(provisional=False) if r.get("npdes_permit") == "CA0000018"]
    src = (root / "research" / "federal" / "build_plant_outfalls.py").read_text()   # a rebuild holds it back too
    hand = next(ast.literal_eval(n.value) for n in ast.parse(src).body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", None) == "HAND_NOT_SEWAGE")
    assert hand["CA0000018"] == ex[0]["basis"]
