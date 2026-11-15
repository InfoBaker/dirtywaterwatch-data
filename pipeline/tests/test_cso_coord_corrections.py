"""Cited corrections to open combined sewer outfall rows without a usable point (scripts/cso_coord_corrections.py,
research/cso-missing-coords, 2026-11-15): Bridgeport West Side 145 at Connecticut DEEP's point, three Massachusetts
co-permittee listings kind "other", four terminated Michigan rows with a true no_point_reason. Data tests on the files
as committed, and the transformation from EPA's own rows (rebuilt from the committed ones); no network.
Run from pipeline/: python -m pytest tests/test_cso_coord_corrections.py -q
"""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CT = ("CT0100056", "145")
CT_POINT = (41.166149273344594, -73.18194339093611)
EPA_CT_POINT = (41.04481, -73.540018)
EPA_CT_REACH = "1100006000887"
MA = {("MAC010510", "001"), ("MAC010617", "001"), ("MAC010986", "001")}
MI = {("MI0037621", "001"), ("MI0037621", "002"), ("MI0037621", "003"), ("MI0051497", "M23")}
TARGETS = {CT} | MA | MI
OLD_MI_REASON = ("EPA's inventory carries no coordinates for this outfall and Michigan's state layers give none; an "
                 "overflow here is read at the operator's plant until a point is found (MI go-live 2026-11-04)")
# the 26 open CSO rows of the live states without a point on 2026-11-15 (research/cso-missing-coords/report.md);
# 22 stay without one: no source places them
STILL_NO_POINT = ({("MD0021598", x) for x in ("002", "003", "005", "007", "008", "010", "011", "012", "015", "017", "019")}
                  | {("MD0067407", "002"), ("MD0067407", "003")}
                  | {("MD0067547", x) for x in ("001", "003", "006")}
                  | MI | {("NE0133680", "205R"), ("TN0020656", "004")})
CORRECTED = {CT} | MA


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("cso_coord_corrections", ROOT / "scripts" / "cso_coord_corrections.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _docs(mod):
    return {n: json.loads((DATA / n).read_text()) for n in mod.files_needed(mod.load_points())}


def _row(docs, key):
    return next(o for d in docs.values() for o in d["outfalls"] if (o.get("npdes_permit"), o.get("outfall")) == key)


def _as_epa_had_them(docs):
    """The committed files with the eight rows put back as EPA's inventory and the ties left them (the state the
    script first met on 2026-11-15)."""
    docs = copy.deepcopy(docs)
    o = _row(docs, CT)
    for k in ("epa_lat", "epa_lon", "epa_reach_id", "coords_from", "coords_note", "coords_source"):
        o.pop(k, None)
    o.update(lat=None, lon=None, echo_lat=EPA_CT_POINT[0], echo_lon=EPA_CT_POINT[1], reach_id=EPA_CT_REACH,
             distance_m=None, match="name_only", coords_problem="ECHO's point is 41.4 km from bridgeport-harbor-ct")
    for k in MA:
        o = _row(docs, k)
        o.pop("outfall_kind", None), o.pop("kind_note", None), o.pop("checked", None)
    for k in MI:
        _row(docs, k)["no_point_reason"] = OLD_MI_REASON
    return docs


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def test_each_point_correction_is_cited_and_near_its_operators_other_outfalls(mod):
    reg = common.load_outfall_registry(DATA, provisional=False)
    for c in mod.load_points():
        for k in ("npdes_permit", "outfall", "lat", "lon", "coords_from", "coords_note", "source_name", "source_url",
                  "read_at", "registry_file", "expect"):
            assert c.get(k) not in (None, ""), (c["npdes_permit"], k)
        assert c["source_url"].startswith("https://") and c["read_at"].startswith("2026-")
        assert c["coords_from"] in {"state outfall layer", "permit", "operator map layer"}
        others = [(o["lat"], o["lon"]) for o in reg if o.get("npdes_permit") == c["npdes_permit"]
                  and o.get("outfall") != c["outfall"] and o.get("lat") is not None]
        assert others and min(_km((c["lat"], c["lon"]), p) for p in others) < 10


def test_the_committed_files_are_as_the_tables_say_and_a_rerun_changes_nothing(mod):
    docs = _docs(mod)
    assert mod.check(docs, mod.load_points()) == []
    before = {n: mod.dumps(d) for n, d in docs.items()}
    rows, problems = mod.apply_tables(docs, mod.load_points())
    assert rows == [] and problems == []
    assert {n: mod.dumps(d) for n, d in docs.items()} == before


def test_from_epas_rows_the_script_changes_the_eight_rows_and_nothing_else(mod):
    committed = _docs(mod)
    docs = _as_epa_had_them(committed)
    assert mod.check(docs, mod.load_points())                      # EPA's rows are not as the tables say
    untouched = {n: [o for o in d["outfalls"] if (o["npdes_permit"], o["outfall"]) not in TARGETS] for n, d in docs.items()}
    rows, problems = mod.apply_tables(docs, mod.load_points())
    assert problems == [] and [(n, (o["npdes_permit"], o["outfall"])) for n, o in rows] == [("outfalls-new-england.json", CT)]
    mod.retie(docs, rows, offline=True)
    assert mod.check(docs, mod.load_points()) == []
    for n, d in docs.items():
        assert [o for o in d["outfalls"] if (o["npdes_permit"], o["outfall"]) not in TARGETS] == untouched[n]
    o = _row(docs, CT)
    assert (o["lat"], o["lon"]) == CT_POINT and (o["epa_lat"], o["epa_lon"]) == EPA_CT_POINT
    assert o["epa_reach_id"] == EPA_CT_REACH and not o.get("reach_id")
    assert o["water_slug"] == "bridgeport-harbor-ct" and "geometry" in o["match"] and o["distance_m"] is not None
    rows, problems = mod.apply_tables(docs, mod.load_points())     # a second run: nothing to do
    assert rows == [] and problems == []


def test_a_co_permittee_listing_that_has_gained_a_point_is_not_reclassified_and_nothing_is_written(mod):
    docs = _as_epa_had_them(_docs(mod))
    o = _row(docs, ("MAC010510", "001"))
    o.update(lat=42.7, lon=-73.2)
    before = {n: mod.dumps(d) for n, d in docs.items()}
    rows, problems = mod.apply_tables(docs, mod.load_points())
    assert rows == [] and any("MAC010510 001" in p and "point" in p for p in problems)
    assert {n: mod.dumps(d) for n, d in docs.items()} == before    # the other rows were not changed either


@pytest.mark.parametrize("key,change", [
    (CT, {"outfall_name": "Main Street and Elm Street"}),
    (CT, {"echo_lat": 41.2, "echo_lon": -73.2}),
    (("MI0037621", "001"), {"outfall_name": "Eight Mile Road regulator"}),
    (("MI0051497", "M23"), {"permit_status": "EFF"}),
    (("MI0037621", "002"), {"lon": -83.4}),
    (("MAC010986", "001"), {"outfall_name": "MAIN STREET OUTFALL"}),
])
def test_changed_epa_evidence_is_reported_not_overwritten(mod, key, change):
    docs = _as_epa_had_them(_docs(mod))
    _row(docs, key).update(change)
    before = {n: mod.dumps(d) for n, d in docs.items()}
    rows, problems = mod.apply_tables(docs, mod.load_points())
    assert rows == [] and any(f"{key[0]} {key[1]}" in p for p in problems)
    assert {n: mod.dumps(d) for n, d in docs.items()} == before


def test_a_corrected_row_whose_point_drifted_is_reported_not_rewritten(mod):
    docs = _docs(mod)
    _row(docs, CT)["lat"] = 41.17
    rows, problems = mod.apply_tables(docs, mod.load_points())
    assert rows == [] and any("CT0100056 145" in p for p in problems)
    assert _row(docs, CT)["lat"] == 41.17


def test_epas_reach_put_back_is_caught_and_repaired(mod):
    docs = _docs(mod)
    _row(docs, CT)["reach_id"] = EPA_CT_REACH
    assert any("reach_id" in b for b in mod.check(docs, mod.load_points()))
    rows, problems = mod.apply_tables(docs, mod.load_points())
    assert problems == [] and not _row(docs, CT)["reach_id"]
    mod.retie(docs, rows, offline=True)
    assert mod.check(docs, mod.load_points()) == []


@pytest.mark.parametrize("change", [
    {"water_slug": "pequonnock-river-ct"}, {"match": "name_only"}, {"outfall_kind": "other"},
    {"epa_lat": 41.0}, {"coords_source": {"url": "https://example.org"}}, {"coords_problem": "restored by hand"},
])
def test_check_catches_drift_in_every_promised_field(mod, change):
    docs = _docs(mod)
    _row(docs, CT).update(change)
    assert any("CT0100056 145" in b for b in mod.check(docs, mod.load_points()))


def test_a_failed_run_writes_nothing(mod, tmp_path, monkeypatch):
    for n in mod.files_needed(mod.load_points()):
        shutil.copy(DATA / n, tmp_path / n)
    doc = json.loads((tmp_path / "outfalls-new-england.json").read_text())
    _row({"x": doc}, ("MAC010617", "001")).update(lat=42.6, lon=-71.7)
    (tmp_path / "outfalls-new-england.json").write_text(mod.dumps(doc))
    before = {p.name: p.read_text() for p in tmp_path.iterdir()}
    monkeypatch.setattr(mod, "DATA", tmp_path)
    assert mod.main([]) == 1 and mod.main(["--check"]) == 1
    assert {p.name: p.read_text() for p in tmp_path.iterdir()} == before


def test_a_national_row_is_not_corrected_here(mod):
    c = dict(mod.load_points()[0], registry_file="data/outfalls-us.json", npdes_permit="TN0020656", outfall="004")
    rows, problems = mod.apply_tables(_docs(mod), [c])
    assert rows == [] and any("not a regional file" in p for p in problems)


def test_the_rain_check_reads_bridgeport_145_and_not_the_co_permittee_listings():
    from ingest import rainfall
    out = rainfall.cso_outfalls()
    ct = [o for o in out if (o["permit"], o["outfall"]) == CT]
    assert len(ct) == 1 and (ct[0]["lat"], ct[0]["lon"]) == CT_POINT
    assert not [o for o in out if o["permit"] in {p for p, _ in MA}]


def test_the_listings_stay_in_the_registry_as_kind_other_and_the_michigan_rows_say_why(mod):
    reg = common.load_outfall_registry(DATA, provisional=False)
    by_key = {(o.get("npdes_permit"), o.get("outfall")): o for o in reg}
    for k, (_n, _t, note) in mod.KIND_OTHER.items():
        assert by_key[k]["outfall_kind"] == "other" and by_key[k]["kind_note"] == note and by_key[k]["lat"] is None
    for (permit, outfall), (_n, _t, _w, reason) in mod.NO_POINT.items():
        o = by_key[(permit, outfall)]
        assert o["lat"] is None and o["no_point_reason"] == reason and "terminated" in reason
        assert "read at the operator's plant" not in reason
        assert not [r for r in reg if r.get("npdes_permit") == permit and r.get("outfall_kind") == "plant"]


def test_of_the_26_rows_found_without_a_point_the_22_unplaced_are_left_and_the_4_corrected_are_not():
    from ingest import rainfall
    radar = rainfall.radar_states(set(common.live_states()))     # the committed live list, whatever another test set
    left = {(o["npdes_permit"], o["outfall"]) for o in common.load_outfall_registry(DATA, provisional=False)
            if (o.get("outfall_kind") or "cso") == "cso" and not str(o.get("outfall_status") or "").startswith("CLS")
            and o.get("rain_caution") is not False
            and str(o.get("state") or o["npdes_permit"][:2]).upper() in radar
            and (o.get("lat") is None or o.get("lon") is None)}
    assert len(STILL_NO_POINT) == 22 and not left & CORRECTED
    assert left & (STILL_NO_POINT | CORRECTED) == STILL_NO_POINT


def test_a_ties_run_cannot_put_epas_point_back():
    """ingest.outfall_waters restores echo_lat/echo_lon on a row that still has coords_problem; the corrected row has
    neither, so the full regional ties pass (run's own shared-point count) keeps the cited point and the water."""
    from collections import Counter, defaultdict
    from ingest import outfall_waters as ow
    docs = {n: json.loads((DATA / n).read_text()) for n in ow.FILES}
    rows = [o for n in ow.FILES for o in docs[n]["outfalls"]]
    shared = Counter((o["npdes_permit"], round(o["lat"], 4), round(o["lon"], 4)) for o in rows if o.get("lat") is not None)
    o = _row(docs, CT)
    ow.match_cso_row(ow.Matcher(offline=True), "outfalls-new-england.json", o, shared, [], defaultdict(Counter))
    assert (o["lat"], o["lon"]) == CT_POINT and o["water_slug"] == "bridgeport-harbor-ct"
    assert "coords_problem" not in o and not o.get("reach_id")
