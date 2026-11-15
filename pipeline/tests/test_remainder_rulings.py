"""Hand rulings on NHD remainders (ingest/waters_from_nhd.py REMAINDER_ON, read by recheck_remainders at every write of
data/waters-nhd.json): the MN go-live audit's P2-1 (pomme-de-terre-river-hodges-mn lay 99 per cent on
pomme-de-terre-river-mn) and the ND go-live audit's P2-2 (missouri-river-east-oliver-nd lay 70 per cent on Lake
Sakakawea). Invented geometry for the rule; the real files for the outcome. No network."""
import json
from pathlib import Path

import pytest

from build import status as S
from ingest import waters_from_nhd as N

ROOT = Path(__file__).resolve().parents[2]
D = 0.009     # about 1 km of latitude


def line(*pts):
    return {"type": "LineString", "coordinates": [list(p) for p in pts]}


@pytest.fixture(autouse=True)
def _clear(monkeypatch, tmp_path):
    S._GEOM_CACHE.clear()
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "none")
    yield
    S._GEOM_CACHE.clear()


def _existing():
    # a river running north along lon -95.0 for 50 km, a 1 km stub of it far downstream, and a lake further on
    lake = [[-95.05, 46.6], [-94.95, 46.6], [-94.95, 46.8], [-95.05, 46.8], [-95.05, 46.6]]
    return {
        "example-river-xx": {"slug": "example-river-xx", "name": "Example River", "kind": "river", "state": "MN",
                             "geometry": line((-95.0, 46.0), (-95.0, 46.45))},
        "example-river-stub-xx": {"slug": "example-river-stub-xx", "name": "Example River", "kind": "river",
                                  "state": "MN", "geometry": line((-95.0, 45.0), (-95.0, 45.009))},
        "example-lake-xx": {"slug": "example-lake-xx", "name": "Example Lake", "kind": "reservoir", "state": "MN",
                            "geometry": {"type": "Polygon", "coordinates": [lake]}},
    }


def _target(slug):
    return {"state": "MN", "name": "Example River", "slugs": [slug],
            "reach_slugs": {"0701": slug, "4100": slug}, "permits": ["MN0000001"]}


def test_a_remainder_lying_on_another_same_named_record_is_dropped_and_its_rows_go_to_the_river(monkeypatch):
    monkeypatch.setattr(N, "REMAINDER_ON", {("MN", 111): {"to": "example-river-xx", "on": ["example-river-xx"],
                                                          "why": "invented"}})
    existing = _existing()
    # the NHD copy: the river's own line (cut only against the stub), with a 400 m braid beside it
    rows = [{"slug": "example-river-hodges-xx", "name": "Example River", "kind": "river", "state": "MN",
             "gnis_id": "00000111", "covers_part_of": "example-river-stub-xx",
             "geometry": {"type": "MultiLineString", "coordinates": [
                 [[-95.0, 46.0], [-95.0, 46.45]], [[-95.0052, 46.1], [-95.0052, 46.11]]]}},
            {"slug": "other-river-xx", "name": "Other River", "kind": "river", "state": "MN",
             "gnis_id": "222", "covers_part_of": "example-river-stub-xx", "geometry": line((-96.0, 46.0), (-96.0, 46.2))}]
    targets = [_target("example-river-hodges-xx"),
               {"state": "MN", "name": "Example River", "slugs": [], "reach_slugs": {"9": "example-river-hodges-xx"}}]
    acts = N.recheck_remainders(rows, targets, existing, "2026-11-15")
    assert [w["slug"] for w in rows] == ["other-river-xx"]
    assert acts == [{"slug": "example-river-hodges-xx", "action": "dropped", "to": "example-river-xx",
                     "why": acts[0]["why"]}] and "hand ruling: invented" in acts[0]["why"]
    assert targets[0]["slugs"] == ["example-river-xx"]
    assert set(targets[0]["reach_slugs"].values()) == {"example-river-xx"}
    assert targets[1]["reach_slugs"] == {"9": "example-river-xx"}           # a row naming it only by reach
    assert any("was dropped" in n for n in targets[0]["notes"])


def test_without_the_ruling_the_same_copy_stays_as_before(monkeypatch):
    monkeypatch.setattr(N, "REMAINDER_ON", {})
    rows = [{"slug": "example-river-hodges-xx", "name": "Example River", "kind": "river", "state": "MN",
             "gnis_id": "111", "covers_part_of": "example-river-stub-xx",
             "geometry": line((-95.0, 46.0), (-95.0, 46.45))}]
    assert N.recheck_remainders(rows, [_target("example-river-hodges-xx")], _existing()) == []
    assert rows[0]["slug"] == "example-river-hodges-xx" and "kind" in rows[0]


def test_a_river_through_a_reservoir_keeps_only_its_true_remainder_as_a_river(monkeypatch):
    monkeypatch.setattr(N, "REMAINDER_ON", {("MN", 111): {
        "to": "example-river-xx", "on": ["example-river-xx", "example-lake-xx"], "kind": "river", "why": "invented"}})
    # the copy: through the lake (22 km), along the river (50 km), and 10 km of true river far from both
    rows = [{"slug": "example-river-east-xx", "name": "Example River", "kind": "canal", "state": "MN",
             "gnis_id": "111", "covers_part_of": "example-river-stub-xx",
             "geometry": {"type": "MultiLineString", "coordinates": [
                 [[-95.0, 46.0], [-95.0, 46.45]], [[-95.0, 46.6], [-95.0, 46.8]], [[-94.5, 47.0], [-94.5, 47.09]]]}}]
    t = _target("example-river-east-xx")
    acts = N.recheck_remainders(rows, [t], _existing(), "2026-11-15")
    assert [a["action"] for a in acts] == ["recut"]
    w = rows[0]
    assert w["slug"] == "example-river-east-xx" and w["kind"] == "river"
    assert 9.0 < w["length_km"] < 11.0 and w["bbox"][0] > -94.6           # only the true remainder is left
    assert t["slugs"] == ["example-river-east-xx"]                          # its rows stay with it


@pytest.mark.parametrize("state,gnis,to", [("MN", 649622, "pomme-de-terre-river-mn"), ("ND", 756398, "missouri-river-nd")])
def test_the_audits_rulings_are_recorded(state, gnis, to):
    assert N.REMAINDER_ON[(state, gnis)]["to"] == to


def test_the_files_carry_neither_copy_and_their_rows_point_at_the_river():
    nhd = json.loads((ROOT / "data" / "waters-nhd.json").read_text())
    slugs = {w["slug"] for w in nhd["waters"]}
    gone = {"pomme-de-terre-river-hodges-mn": "pomme-de-terre-river-mn", "missouri-river-east-oliver-nd": "missouri-river-nd"}
    assert not set(gone) & slugs
    for t in nhd["targets"]:                      # no target row names either copy
        assert not set(gone) & (set(t.get("slugs") or []) | set((t.get("reach_slugs") or {}).values()))
    from common import load_outfall_registry       # no outfall is tied to either copy
    assert not [o for o in load_outfall_registry(ROOT / "data") if o.get("water_slug") in gone]
    plants = [json.loads(x.rstrip(",\n")) for x in (ROOT / "data" / "outfalls-plants-us.json").read_text().splitlines()
              if x.startswith('{"') and ('"ND0022349"' in x or '"NDG589311"' in x)]
    tied = {(r["npdes_permit"], r["outfall"]): r["water_slug"] for r in plants}
    assert tied[("ND0022349", "002")] == tied[("NDG589311", "NODI")] == "missouri-river-nd"
