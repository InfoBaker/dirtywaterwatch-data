"""A report that names no outlet and gives no point (build/status.py permit_outlet_reaches, 2026-11-21): a CSO, a
bypass, a plant bypass or a blend with a permit is drawn from its permit's most upstream open, traced registry outlet
on each river it is placed on, marked reach_basis "permit_outlet_unnamed"; a sanitary sewer overflow is never placed
this way. The shape of the miss: Hartford, Vermont's plant bypass (VT0101010, "Connecticut River", no outfall, no
point) coloured the whole Vermont record of the river and drew no stretch, so New Hampshire's record of the same river
showed nothing.

Run from pipeline/: python -m pytest tests/test_permit_outlet_reach.py -q
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from build import status as S  # noqa: E402
from common import event  # noqa: E402

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)
VT = "VT0101010"
NH = "NH0100447"


def water(slug, name, state, coords, kind="river"):
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state,
                  "bbox": [min(xs), min(ys), max(xs), max(ys)],
                  "geometry": {"type": "LineString", "coordinates": coords}}


CONN = [[-72.0, 43.6], [-71.8, 43.6]]           # the state line: one river, a record in each state
WATERS = dict([
    water("conn-river-vt", "Connecticut River", "VT", CONN),
    water("conn-river-nh", "Connecticut River", "NH", CONN),
    water("white-river-vt", "White River", "VT", [[-71.99, 43.65], [-71.99, 43.6]]),
    water("other-river-vt", "Other River", "VT", [[-72.5, 44.0], [-72.4, 44.0]]),
    water("merrimack-river-nh", "Merrimack River", "NH", [[-71.5, 43.0], [-71.4, 43.0]]),
    water("piscataquog-river-nh", "Piscataquog River", "NH", [[-71.45, 43.05], [-71.45, 43.0]]),
])


def seg(comid, name, hs, k0, k1, coords):
    return {"comid": comid, "km_start": k0, "km_end": k1, "totdasqkm": 20000, "qe_ma": 10000, "slope": 3e-4,
            "gnis_name": name, "hydroseq": hs, "coords": coords}


def reach(permit, outfall, slug, segs, **kw):
    km = segs[-1]["km_end"]
    return {"key": f"{permit}-{outfall}", "permit": permit, "outfall": outfall, "water_slug": slug,
            "lat": segs[0]["coords"][0][1], "lon": segs[0]["coords"][0][0], "river": segs[0]["gnis_name"],
            "cut_reason": "cap_km", "length_km": km, "segments": segs, **kw}


C = "Connecticut River"
TAIL = seg(11, C, 100, 0, 0, [[-71.95, 43.6], [-71.85, 43.6]])     # km filled per reach below


def tail(k0):
    return {**TAIL, "km_start": k0, "km_end": round(k0 + 8.0, 3)}


def vt_reaches():
    """Hartford's three traced CSO outfalls, all starting within a few hundred metres: 006 enters the Connecticut at
    the top of flowline 10 from the White River's mouth, 004 and 007 start part way down flowline 10 (traces are
    trimmed at the outfall), so 006 covers both."""
    r006 = reach(VT, "006", "conn-river-vt", [
        seg(5, "White River", 300, 0.0, 0.2, [[-71.99, 43.602], [-71.99, 43.6]]),
        seg(10, C, 200, 0.2, 2.2, [[-71.99, 43.6], [-71.95, 43.6]]), tail(2.2)])
    r004 = reach(VT, "004", "conn-river-vt", [seg(10, C, 200, 0.0, 1.7, [[-71.985, 43.6], [-71.95, 43.6]]), tail(1.7)])
    r007 = reach(VT, "007", "conn-river-vt", [seg(10, C, 200, 0.0, 1.5, [[-71.98, 43.6], [-71.95, 43.6]]), tail(1.5)])
    return {r["key"]: r for r in (r004, r006, r007)}


def row(permit, outfall, slug, kind="cso", status="CSO"):
    return {"npdes_permit": permit, "outfall": outfall, "outfall_kind": kind, "outfall_status": status,
            "water_slug": slug, "state": permit[:2], "lat": None, "lon": None, "_file": "data/outfalls-new-england.json"}


VT_ROWS = [row(VT, "004", "conn-river-vt"), row(VT, "006", "conn-river-vt"), row(VT, "007", "conn-river-vt"),
           row(VT, "005", "conn-river-vt", status="CLS"), row(VT, "001", "conn-river-vt", kind="plant", status=None)]


def vt_bypass(rid="hqs", **kw):
    """The Vermont record's shape: a permit, the river named, no outfall, no point."""
    kw.setdefault("event_type", "plant_bypass")
    kw.setdefault("water_slugs", ["conn-river-vt"])
    kw.setdefault("started_at", (NOW - 30 * H).isoformat())
    return event(source_id="vt-dec", source_record_id=rid, status="ongoing", npdes_permit=VT,
                 discharger_name="Hartford White River Junction", waterbody_text="Connecticut River",
                 volume_gal=13_200_000, **kw)


@pytest.fixture(autouse=True)
def _clean():
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    yield
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()


def build(records, reaches, rows):
    tmp = Path(tempfile.mkdtemp())
    f = tmp / "vt-dec.json"
    f.write_text(json.dumps({"source_id": "vt-dec", "ok": True, "last_ok_at": NOW.isoformat(), "meta": {},
                             "records": records}))
    before = f.read_text()
    st, hist = S.build(now=NOW, write=False, events_dir=tmp, waters=copy.deepcopy(WATERS), outfalls=list(rows),
                       registry={}, reaches=copy.deepcopy(reaches), flows=({}, {}), discharger_towns={},
                       discharger_waters={}, placement_cache=False)
    assert f.read_text() == before              # the event record itself is never changed
    return st, hist


def placements_of(st, eid):
    return st["placements"][eid]


# ---------------------------------------------------------------- the Vermont case

def test_a_plant_bypass_naming_no_outlet_is_drawn_from_the_most_upstream_outlet_and_reaches_the_other_state():
    e = vt_bypass()
    st, _ = build([e], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:hqs")
    assert p["reach"] == f"{VT}-006" and "reaches" not in p
    assert p["reach_basis"] == "permit_outlet_unnamed"
    assert p["reach_basis_outfalls"] == [{"water_slug": "conn-river-vt", "reach": f"{VT}-006", "permit": VT,
                                          "outfall": "006", "candidates": 3}]
    assert p["reach_basis_note"] == ("The report names no outlet. The stretch is drawn from the operator's most "
                                     "upstream registered outlet on this river (outfall 006 of 3); our choice, not "
                                     "the report's.")
    vt, nh = st["waters"]["conn-river-vt"], st["waters"]["conn-river-nh"]
    assert [r["placement"] for r in vt["reasons"]] == ["reach"] and vt["reasons"][0]["reach"] == f"{VT}-006"
    # the river is the state line: New Hampshire's record of it now carries the same stretch
    assert nh["status"] == "red" and [r["placement"] for r in nh["reasons"]] == ["reach"]
    assert all(r["reach_basis"] == "permit_outlet_unnamed" for r in vt["reasons"] + nh["reasons"])
    assert st["reaches"][f"{VT}-006"]["status"] == "red" and set(st["reaches"]) == {f"{VT}-006"}
    a = [x for x in st["reach_events_active"] if x["event_id"] == "vt-dec:hqs"]
    assert len(a) == 1 and a[0]["reach_basis"] == "permit_outlet_unnamed"
    assert a[0]["reach_basis_note"] == p["reach_basis_note"]
    assert st["needs_reach"] == []


def test_the_upstream_choice_follows_the_flowlines_not_the_key_or_latitude():
    rs = vt_reaches()
    assert S.most_upstream(list(rs.values()))["key"] == f"{VT}-006"
    assert S.most_upstream([rs[f"{VT}-004"], rs[f"{VT}-007"]])["key"] == f"{VT}-004"   # longer run left on flowline 10
    assert S._covers(rs[f"{VT}-006"], rs[f"{VT}-007"]) and not S._covers(rs[f"{VT}-007"], rs[f"{VT}-006"])


def test_a_plant_outfall_comes_first_for_a_plant_bypass_and_never_for_a_cso():
    rs = vt_reaches()
    r001 = reach(VT, "001", "conn-river-vt", [{**tail(0.0), "km_end": 6.0, "coords": [[-71.9, 43.6], [-71.85, 43.6]]}])
    rs[r001["key"]] = r001
    st, _ = build([vt_bypass(), vt_bypass("cso", event_type="cso")], rs, VT_ROWS)
    bypass, cso = placements_of(st, "vt-dec:hqs"), placements_of(st, "vt-dec:cso")
    assert bypass["reach"] == f"{VT}-001" and bypass["reach_basis_outfalls"][0]["candidates"] == 1
    assert cso["reach"] == f"{VT}-006" and cso["reach_basis_outfalls"][0]["candidates"] == 3


# ---------------------------------------------------------------- a CSO report naming two rivers

def nh_reaches():
    M, P = "Merrimack River", "Piscataquog River"
    m22 = [[-71.45, 43.0], [-71.4, 43.0]]
    out = [
        reach(NH, "001", "merrimack-river-nh", [seg(20, M, 520, 0.0, 1.0, [[-71.49, 43.0], [-71.48, 43.0]]),
                                                seg(21, M, 510, 1.0, 3.0, [[-71.48, 43.0], [-71.45, 43.0]]),
                                                seg(22, M, 500, 3.0, 7.0, m22)]),
        reach(NH, "002", "merrimack-river-nh", [seg(21, M, 510, 0.0, 1.5, [[-71.47, 43.0], [-71.45, 43.0]]),
                                                seg(22, M, 500, 1.5, 5.5, m22)]),
        reach(NH, "010", "piscataquog-river-nh", [seg(30, P, 610, 0.0, 2.0, [[-71.45, 43.05], [-71.45, 43.03]]),
                                                  seg(31, P, 600, 2.0, 5.0, [[-71.45, 43.03], [-71.45, 43.0]]),
                                                  seg(22, M, 500, 5.0, 9.0, m22)]),
        reach(NH, "011", "piscataquog-river-nh", [seg(31, P, 600, 0.0, 1.5, [[-71.45, 43.02], [-71.45, 43.0]]),
                                                  seg(22, M, 500, 1.5, 5.5, m22)]),
        # the plant's outfall, higher up the Merrimack than any CSO: never a CSO report's outlet
        reach(NH, "099", "merrimack-river-nh", [seg(20, M, 520, 0.0, 1.5, [[-71.495, 43.0], [-71.48, 43.0]]),
                                                seg(21, M, 510, 1.5, 3.5, [[-71.48, 43.0], [-71.45, 43.0]])]),
    ]
    return {r["key"]: r for r in out}


NH_ROWS = [row(NH, o, s) for o, s in (("001", "merrimack-river-nh"), ("002", "merrimack-river-nh"),
                                      ("010", "piscataquog-river-nh"), ("011", "piscataquog-river-nh"))] + \
          [row(NH, "099", "merrimack-river-nh", kind="plant", status=None)]


def test_a_cso_report_naming_two_rivers_gets_one_stretch_per_river():
    e = event(source_id="vt-dec", source_record_id="mht", event_type="cso", status="ongoing", npdes_permit=NH,
              water_slugs=["merrimack-river-nh", "piscataquog-river-nh"], started_at=(NOW - 3 * H).isoformat())
    st, _ = build([e], nh_reaches(), NH_ROWS)
    p = placements_of(st, "vt-dec:mht")
    assert p["reach"] == f"{NH}-001" and p["reaches"] == [f"{NH}-001", f"{NH}-010"]
    assert [(x["water_slug"], x["outfall"], x["candidates"]) for x in p["reach_basis_outfalls"]] == [
        ("merrimack-river-nh", "001", 2), ("piscataquog-river-nh", "010", 2)]
    assert p["reach_basis_note"] == ("The report names no outlet. The stretches are drawn from the operator's most "
                                     "upstream registered outlet on each river (Merrimack River: outfall 001 of 2; "
                                     "Piscataquog River: outfall 010 of 2); our choice, not the report's.")
    for slug in ("merrimack-river-nh", "piscataquog-river-nh"):
        assert {r["placement"] for r in st["waters"][slug]["reasons"]} == {"reach"}
        assert len(st["waters"][slug]["reasons"]) == 1               # one record colours a water once
    assert f"{NH}-099" not in st["reaches"]


# ---------------------------------------------------------------- unchanged cases

def test_a_sanitary_sewer_overflow_naming_no_outlet_is_never_placed_on_an_outlet():
    st, _ = build([vt_bypass("sso", event_type="sso")], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:sso")
    assert "reach" not in p and "reach_basis" not in p and "reach_basis_note" not in p
    assert [r["placement"] for r in st["waters"]["conn-river-vt"]["reasons"]] == ["unmodeled"]
    assert "conn-river-nh" not in st["waters"] or not st["waters"]["conn-river-nh"]["reasons"]
    assert st["reaches"] == {}


def test_a_permit_with_no_traced_outfall_on_the_named_river_is_unchanged():
    st, _ = build([vt_bypass("oth", water_slugs=["other-river-vt"])], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:oth")
    assert "reach" not in p and "reach_basis" not in p
    assert [r["placement"] for r in st["waters"]["other-river-vt"]["reasons"]] == ["unmodeled"]
    st, _ = build([vt_bypass("none")], {}, VT_ROWS)          # nothing traced at all
    assert "reach_basis" not in placements_of(st, "vt-dec:none")
    assert [r["placement"] for r in st["waters"]["conn-river-vt"]["reasons"]] == ["unmodeled"]


def test_a_report_naming_its_outfall_or_giving_a_point_is_not_drawn_from_another_outlet():
    st, _ = build([vt_bypass("own", outfall_id="002"), vt_bypass("pt", lat=43.6, lon=-71.97)], vt_reaches(), VT_ROWS)
    for eid in ("vt-dec:own", "vt-dec:pt"):
        assert "reach_basis" not in placements_of(st, eid) and "reach" not in placements_of(st, eid)
    assert [n["event_id"] for n in st["needs_reach"]] == ["vt-dec:pt"]       # traced from its own point, as before


def test_closed_and_untraced_outfalls_are_skipped():
    rs = vt_reaches()
    rows = [row(VT, "006", "conn-river-vt", status="CLS")] + [r for r in VT_ROWS if r["outfall"] != "006"]
    st, _ = build([vt_bypass()], rs, rows)
    p = placements_of(st, "vt-dec:hqs")
    assert p["reach"] == f"{VT}-004" and p["reach_basis_outfalls"][0]["candidates"] == 2
    rs[f"{VT}-004"] = {**rs[f"{VT}-004"], "cut_reason": "no_trace"}
    st, _ = build([vt_bypass()], rs, rows)
    p = placements_of(st, "vt-dec:hqs")
    assert p["reach"] == f"{VT}-007" and p["reach_basis_outfalls"][0]["candidates"] == 1
    rs[f"{VT}-007"] = {**rs[f"{VT}-007"], "segments": [], "cut_reason": "tidal_at_outfall"}
    st, _ = build([vt_bypass()], rs, rows)
    assert "reach_basis" not in placements_of(st, "vt-dec:hqs")


def test_a_monthly_total_or_a_future_start_gets_no_outlet_stretch():
    e = vt_bypass("mo", time_precision="month", started_at=(NOW - 40 * 24 * H).isoformat())
    st, _ = build([e], vt_reaches(), VT_ROWS)
    assert "reach_basis" not in placements_of(st, "vt-dec:mo")


# ---------------------------------------------------------------- the export

class _Redactor:
    def note(self, text, swaps=()):
        return text


def test_the_export_carries_the_basis_on_the_record_the_reasons_and_the_segments():
    from export import build as X
    e = vt_bypass()
    rs = vt_reaches()
    st, _ = build([e], rs, VT_ROWS)
    rec = X.public_record({**e}, st["placements"]["vt-dec:hqs"], _Redactor())
    assert rec["reach_basis"] == "permit_outlet_unnamed" and rec["reach"] == f"{VT}-006"
    assert rec["reach_basis_outfalls"][0]["outfall"] == "006" and rec["reach_basis_outfalls"][0]["candidates"] == 3
    assert rec["reach_basis_note"].startswith("The report names no outlet.")
    assert rec["outfall_id"] is None and rec["lat"] is None and rec["lon"] is None      # the record as published
    feats, paths = X.reach_features(st, {"vt-dec:hqs": {"started_at": e["started_at"]}}, cached=rs)
    segs = [f["properties"] for f in feats if f["properties"]["feature"] == "segment"]
    stops = [f["properties"] for f in feats if f["properties"]["feature"] == "stop"]
    assert segs and all(s["reach_basis"] == "permit_outlet_unnamed" and s["outfall"] == "006" for s in segs)
    assert all(s["label"].endswith("our choice, not the report's.") for s in segs)
    assert stops and stops[0]["reach_basis_note"] == rec["reach_basis_note"]
    # a record naming its outfall keeps its features as before: no basis fields
    plain = {"reach_events_active": [{**a, "reach_basis": None} for a in st["reach_events_active"]],
             "reaches": st["reaches"]}
    for a in plain["reach_events_active"]:
        a.pop("reach_basis"), a.pop("reach_basis_note")
    feats, _ = X.reach_features(plain, {"vt-dec:hqs": {"started_at": e["started_at"]}}, cached=rs)
    assert all("reach_basis" not in f["properties"] for f in feats)
    rec = X.public_record({**e}, {"water_slugs": ["conn-river-vt"]}, _Redactor())
    assert "reach_basis" not in rec and "reach_basis_note" not in rec


def test_reported_outfalls_ignores_a_stretch_drawn_for_a_report_naming_no_outlet(tmp_path, monkeypatch):
    from build import reaches as R
    monkeypatch.setattr(R, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path / "events")
    (tmp_path / "status.json").write_text(json.dumps({"placements": {
        "a": {"reach": f"{VT}-006", "reach_basis": "permit_outlet_unnamed"}, "b": {"reach": f"{VT}-004"}}}))
    assert R.reported_outfalls() == {f"{VT}-004"}
