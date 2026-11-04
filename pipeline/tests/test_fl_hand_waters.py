"""Florida's bays, bayous and passes as hand records from the Census TIGER/Line hydrography (ingest/waters_from_nhd.py
build_tiger, HAND service "tiger"), and the hand aliases for the spellings Florida DEP's notices use
(data/water-aliases.json). Florida's go-live gates of 2026-11-04. No network.
Run from pipeline/: python -m pytest tests/test_fl_hand_waters.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

from build import status as S  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class _States:
    def clip(self, g, state):
        return g


class _Towns:
    def along(self, state, geom):
        return ["Panama City"]


def _nhd():
    return SimpleNamespace(states=_States(), towns=_Towns(), http=SimpleNamespace())


SQUARE = Polygon([(-85.660, 30.150), (-85.652, 30.150), (-85.652, 30.157), (-85.660, 30.157)])


def _tiger(monkeypatch, feats, calls):
    def fake(http, kind, layer, *, service=N.EPA_NHD, **params):
        calls.append((kind, layer, service, params.get("where")))
        return feats
    monkeypatch.setattr(N, "arcgis", fake)


SPEC = dict(name="Massalina Bayou", state="FL", kind="bay", source="census", service="tiger", gnis_id="286507",
            oids=["11090501436"], gnis_point=(-85.6559045, 30.1545507), near=(-85.6559045, 30.1545507),
            aliases=["Messalina Bayou"], why="the notices name it; NHD carries no water of that name")


def test_a_tiger_hand_record_is_the_census_polygon_with_its_ids_and_the_gnis_feature(monkeypatch):
    calls = []
    _tiger(monkeypatch, [{"OID": "11090501436", "NAME": None, "MTFCC": "H3010", "_geom": SQUARE}], calls)
    rec, problem = N.build_hand(SPEC, _nhd(), None)
    assert problem == ""
    assert calls == [("tiger-hand", N.TIGER_AREA, N.TIGER_HYDRO, "OID IN ('11090501436')")]
    assert rec["hand"] is True and rec["source"] == "census" and rec["tiger_ids"] == ["11090501436"]
    assert rec["kind"] == "bay" and rec["gnis_id"] == "286507" and rec["aliases"] == ["Messalina Bayou"]
    assert 0.4 < rec["area_km2"] < 0.7 and rec["length_km"] is None and rec["towns"] == ["Panama City"]
    assert "TIGER/Line hydrography" in rec["note"] and "11090501436" in rec["note"] and "feature 286507" in rec["note"]
    assert "named nothing by the Census" in rec["note"] and "Hand record: the notices name it" in rec["note"]
    rec["slug"] = "massalina-bayou-fl"
    row = N.public_record(rec)
    assert row["geometry"]["type"] in ("Polygon", "MultiPolygon") and row["tiger_ids"] == ["11090501436"]
    assert N.water_identity(row) == ("FL", "gnis", "286507")
    assert N.water_identity({**row, "gnis_id": None}) == ("FL", "tiger", ("11090501436",))


def test_an_unnamed_polygon_away_from_the_gnis_point_is_refused(monkeypatch):
    far = Polygon([(-85.70, 30.20), (-85.69, 30.20), (-85.69, 30.21), (-85.70, 30.21)])
    _tiger(monkeypatch, [{"OID": "11090501436", "NAME": None, "MTFCC": "H3010", "_geom": far}], [])
    rec, problem = N.build_hand(SPEC, _nhd(), None)
    assert rec is None and "GNIS point" in problem and f"more than {N.GNIS_POINT_M} m" in problem


def test_a_tiger_id_the_service_does_not_return_is_a_problem_not_a_record(monkeypatch):
    _tiger(monkeypatch, [], [])
    rec, problem = N.build_hand(SPEC, _nhd(), None)
    assert rec is None and "TIGER features ['11090501436'] not returned" in problem


FL_HAND = [h for h in N.HAND if h["state"] == "FL"]


def test_florida_hand_records_cite_the_census_ids_and_a_gnis_feature_at_their_place():
    assert len(FL_HAND) >= 17
    names = [h["name"] for h in FL_HAND]
    assert len(names) == len(set(names))
    for h in FL_HAND:
        assert h["source"] == "census" and h["service"] == "tiger" and h["oids"] and h["kind"] == "bay"
        assert h["gnis_id"] and len(h["near"]) == 2 and -88 < h["near"][0] < -79 and 24 < h["near"][1] < 31.1
        assert "GNIS lists" in h["why"] and "Florida DEP's pollution notices name" in h["why"]
        if h.get("gnis_point"):            # an unnamed Census polygon: the GNIS point is the evidence
            assert h["gnis_point"] == h["near"]


@pytest.mark.parametrize("slug,name,kind,spelling", [
    ("gulf-of-america-fl", "Gulf Of America", "bay", "Gulf of Mexico"),
    ("saint-joseph-bay-fl", "Saint Joseph Bay", "bay", "St Joe Bay"),
    ("saint-joseph-bay-fl", "Saint Joseph Bay", "bay", "St. Joe Bay"),
    ("posten-bayou-fl", "Posten Bayou", "river", "Poste Bayou"),
    ("posten-bayou-fl", "Posten Bayou", "river", "Posted Bayou"),
    ("fannin-bayou-fl", "Fannin Bayou", "river", "Fanning Bayou"),
    ("old-tampa-bay-fl", "Old Tampa Bay", "bay", "Upper Tampa Bay"),
    ("the-narrows-fl", "The Narrows", "river", "Narrows Waterway"),
    ("halifax-river-fl", "Halifax River", "river", "Halifax Intracoastal Waterway"),
    ("atlantic-icw-lake-worth-lagoon-fl", "Atlantic ICW - Lake Worth Lagoon", "lake", "Lake Worth Lagoon"),
    ("atlantic-intercoastal-waterway-fl", "Atlantic Intercoastal Waterway", "canal", "Intracoastal Waterway"),
    ("gulf-intracoastal-waterway-fl", "Gulf Intracoastal Waterway", "canal", "ICW"),
])
def test_the_florida_notices_spellings_are_hand_aliases(slug, name, kind, spelling):
    waters = {slug: {"slug": slug, "name": name, "state": "FL", "kind": kind}}
    problems = S.apply_water_aliases(waters, S.DATA_DIR / S.WATER_ALIASES_FILE)     # the file's other slugs are absent
    assert not [p for p in problems if slug in p]
    r = S.Resolver(waters, [], placement_rules={})
    assert r.by_name(spelling, "FL", None, None)[0] == [slug]


def test_the_intracoastal_waterway_goes_to_the_nearest_record_or_none():
    """The alias sits on every Atlantic and Gulf Intracoastal Waterway record: a report goes to the one its town names
    (or the nearest by outline, where the outlines are read); with neither it is not placed on any."""
    waters = {s: {"slug": s, "name": n, "state": "FL", "kind": "canal", "towns": t} for s, n, t in [
        ("atlantic-intracoastal-waterway-boca-raton-fl", "Atlantic Intracoastal Waterway", ["Delray Beach"]),
        ("gulf-intracoastal-waterway-indian-rocks-beach-fl", "Gulf Intracoastal Waterway", ["Madeira Beach"])]}
    S.apply_water_aliases(waters, S.DATA_DIR / S.WATER_ALIASES_FILE)
    r = S.Resolver(waters, [], placement_rules={})
    ev = {"raw": {"municipality": "Delray Beach"}}
    assert r.by_name("Intracoastal Waterway", "FL", None, None, ev)[0] == ["atlantic-intracoastal-waterway-boca-raton-fl"]
    slugs, note, ambiguous = r.by_name("Intracoastal Waterway", "FL", None, None, {})
    assert slugs == [] and ambiguous and "names 2 waters" in note


def test_hand_only_needs_names():
    with pytest.raises(SystemExit):
        N.main(["--hand-only"])


def test_a_scoped_merge_keeps_the_states_rows_where_they_stood():
    old = [{"state": "CT", "name": "A", "from": "reports"}, {"state": "FL", "name": "B", "from": "reports"},
           {"state": "FL", "name": "C", "from": "reports"}, {"state": "GA", "name": "D", "from": "reports"}]
    new = [{"state": "FL", "name": "B", "from": "reports", "slugs": ["b-fl"]}]
    out = N.merge_targets_scoped(old, new, {"FL"}, "reports")
    assert [r["name"] for r in out] == ["A", "B", "C", "D"] or [r["name"] for r in out] == ["A", "C", "B", "D"]
    assert out[0]["state"] == "CT" and out[-1]["state"] == "GA"
    assert N.merge_targets_scoped([{"state": "CT", "name": "A"}], new, {"FL"}, "reports")[-1]["name"] == "B"


# ---------------------------------------------------------------- the outlines on the hourly path (gate 3)

def test_the_status_build_counts_the_outlines_it_can_measure_against_per_state(tmp_path, monkeypatch):
    """The placement guard measures a name match against the record's outline: an inline geometry, or openboatlaunch's
    out/water/<slug>.json, which the hourly run restores. The build says per state how many it has, and a problem when
    a state's records mostly have none (Florida's 1,030 openboatlaunch records carry no inline geometry)."""
    obl = tmp_path / "water"
    obl.mkdir()
    (obl / "lake-a-fl.json").write_text("{}")
    monkeypatch.setattr(S, "OBL_WATER_DIR", obl)
    waters = {"lake-a-fl": {"state": "FL"}, "lake-b-fl": {"state": "FL"}, "lake-c-fl": {"state": "FL"},
              "bayou-fl": {"state": "FL", "extra": True, "geometry": {"type": "Point", "coordinates": [0, 0]}},
              "creek-ny": {"state": "NY", "extra": True, "geometry": {"type": "Point", "coordinates": [0, 0]}}}
    cov = S.outline_coverage(waters)
    assert cov["FL"] == {"records": 4, "with_outline": 2, "openboatlaunch": 3, "openboatlaunch_with_outline": 1}
    assert cov["NY"]["with_outline"] == 1 and not S.outline_problems(cov)
    (obl / "lake-a-fl.json").unlink()
    probs = S.outline_problems(S.outline_coverage(waters))
    assert len(probs) == 1 and probs[0].startswith("FL: 1 of 4 water records have an outline here")
    assert "obl-water" not in probs[0] and "data/" not in probs[0]
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "absent")
    assert S.outline_coverage(waters)["FL"]["openboatlaunch_with_outline"] == 0


def test_the_hourly_run_restores_the_outlines_where_the_status_build_reads_them():
    """refresh.yml unpacks state/obl-water.tar.gz into ../openboatlaunch/out (water/<slug>.json), the default
    OBL_WATER_DIR of build/status.py; the Florida feed is an hourly ingest module (not skipped), and the hand records
    are rebuilt by the hourly waters-nhd step."""
    root = Path(__file__).resolve().parents[2]
    wf = (root / ".github" / "workflows" / "refresh.yml").read_text()
    assert "unpack-obl obl-water.tar.gz" in wf
    text = (root / "scripts" / "state_paths.py").read_text()
    assert 'OBL_OUT' in text and '"openboatlaunch" / "out"' in text.replace("'", '"')
    import os
    assert S.OBL_WATER_DIR.parts[-3:] == ("openboatlaunch", "out", "water") or "OBL_WATER_DIR" in os.environ
    mk = (root / "Makefile").read_text()
    skip = next(line for line in mk.splitlines() if line.startswith("INGEST_SKIP"))
    assert "fl_dep_pnp" not in skip and "waters-nhd" in next(l for l in mk.splitlines() if l.startswith("INGEST_EXTRA"))
    assert "__main__" in (root / "pipeline" / "ingest" / "fl_dep_pnp.py").read_text()


def test_each_florida_hand_records_note_carries_its_specs_evidence_as_written():
    # review of 2026-11-04 (P3-1): the GNIS point of Johns Pass lies just inside the Census's Boca Ciega Bay polygon, 95 m
    # from the pass polygon the record is; the evidence says so, and the record on file carries the spec's words
    recs = {w["name"]: w for w in json.loads((ROOT / "data" / "waters-nhd.json").read_text())["waters"]
            if w.get("state") == "FL" and w.get("source") == "census"}
    for h in FL_HAND:
        assert h["why"] in recs[h["name"]]["note"], h["name"]
    jp = next(h for h in FL_HAND if h["name"] == "Johns Pass")
    assert "holds that point" not in jp["why"] and "95 m from that point" in jp["why"]
