"""A report that names no outlet and gives no point (build/status.py permit_outlet_reaches, 2026-11-21): a CSO, a
bypass, a plant bypass or a blend with a permit is drawn from its permit's most upstream open, traced registry outlet
on each river it is placed on, marked reach_basis "permit_outlet_unnamed"; a sanitary sewer overflow is never placed
this way. The shape of the miss: Hartford, Vermont's plant bypass (VT0101010, "Connecticut River", no outfall, no
point) coloured the whole Vermont record of the river and drew no stretch, so New Hampshire's record of the same river
showed nothing.

2026-11-21, after review: the chosen outlet must start on the river, have a current open registry row, and be
established upstream of every other candidate (its trace runs through their starts), or all of them start within 1 km
along the network; otherwise nothing is placed. An outlet the report names that the registry holds is never stood in
for; one it does not hold gives basis "permit_outlet_unmatched" and its own note. A river the placement took from the
permit counts, and the note says so.

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
    kw.setdefault("waterbody_text", "Connecticut River")
    return event(source_id="vt-dec", source_record_id=rid, status="ongoing", npdes_permit=VT,
                 discharger_name="Hartford White River Junction",
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


def r006_on_conn():
    """006 as an outlet on the Connecticut itself: at the top of flowline 10, above 004 and 007."""
    return reach(VT, "006", "conn-river-vt", [seg(10, C, 200, 0.0, 2.0, [[-71.99, 43.6], [-71.95, 43.6]]), tail(2.0)])


# ---------------------------------------------------------------- the Vermont case

def test_a_plant_bypass_naming_no_outlet_is_drawn_from_the_most_upstream_outlet_and_reaches_the_other_state():
    e = vt_bypass()
    st, hist = build([e], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:hqs")
    # 006's trace starts on the White River (a tributary): not an outlet on the Connecticut; 004 runs through 007's start
    assert p["reach"] == f"{VT}-004" and "reaches" not in p
    assert p["reach_basis"] == "permit_outlet_unnamed"
    assert p["reach_basis_outfalls"] == [{"water_slug": "conn-river-vt", "reach": f"{VT}-004", "permit": VT,
                                          "outfall": "004", "candidates": 2, "water_named": True}]
    assert p["reach_basis_note"] == ("The report names no outlet. The stretch is drawn from the operator's most "
                                     "upstream registered outlet on this river (outfall 004, one of its 2 outlets on this river); our choice, not "
                                     "the report's.")
    vt, nh = st["waters"]["conn-river-vt"], st["waters"]["conn-river-nh"]
    assert [r["placement"] for r in vt["reasons"]] == ["reach"] and vt["reasons"][0]["reach"] == f"{VT}-004"
    # the river is the state line: New Hampshire's record of it now carries the same stretch
    assert nh["status"] == "red" and [r["placement"] for r in nh["reasons"]] == ["reach"]
    assert all(r["reach_basis"] == "permit_outlet_unnamed" for r in vt["reasons"] + nh["reasons"])
    assert "white-river-vt" not in st["waters"] or not st["waters"]["white-river-vt"]["reasons"]
    assert set(st["reaches"]) == {f"{VT}-004"} and st["reaches"][f"{VT}-004"]["status"] == "red"
    assert st["reaches"][f"{VT}-004"]["reach_basis_events"] == {
        "vt-dec:hqs": {"reach_basis": "permit_outlet_unnamed", "reach_basis_note": p["reach_basis_note"]}}
    a = [x for x in st["reach_events_active"] if x["event_id"] == "vt-dec:hqs"]
    assert len(a) == 1 and a[0]["reach_basis"] == "permit_outlet_unnamed"
    assert a[0]["reach_basis_note"] == p["reach_basis_note"]
    # history and replay keep the basis: a seventh item on the reach's and the waters' intervals
    assert all(iv[4] != "vt-dec:hqs" or iv[6:] == ["permit_outlet_unnamed"]
               for iv in hist["reach_intervals"][f"{VT}-004"])
    assert any(iv[4] == "vt-dec:hqs" for iv in hist["reach_intervals"][f"{VT}-004"])
    for slug in ("conn-river-vt", "conn-river-nh"):
        mine = [iv for iv in hist["intervals"][slug] if iv[4] == "vt-dec:hqs"]
        assert mine and all(iv[6:] == ["permit_outlet_unnamed"] for iv in mine)
    assert st["needs_reach"] == []


def test_an_outlet_on_the_river_above_the_others_is_chosen():
    rs = vt_reaches()
    rs[f"{VT}-006"] = r006_on_conn()
    st, _ = build([vt_bypass()], rs, VT_ROWS)
    p = placements_of(st, "vt-dec:hqs")
    assert p["reach"] == f"{VT}-006" and p["reach_basis_outfalls"][0]["candidates"] == 3
    assert "(outfall 006, one of its 3 outlets on this river)" in p["reach_basis_note"]


def test_a_plant_outfall_comes_first_for_a_plant_bypass_and_never_for_a_cso():
    rs = vt_reaches()
    rs[f"{VT}-006"] = r006_on_conn()
    r001 = reach(VT, "001", "conn-river-vt", [{**tail(0.0), "km_end": 6.0, "coords": [[-71.9, 43.6], [-71.85, 43.6]]}])
    rs[r001["key"]] = r001
    st, _ = build([vt_bypass(), vt_bypass("cso", event_type="cso")], rs, VT_ROWS)
    bypass, cso = placements_of(st, "vt-dec:hqs"), placements_of(st, "vt-dec:cso")
    assert bypass["reach"] == f"{VT}-001" and bypass["reach_basis_outfalls"][0]["candidates"] == 1
    assert cso["reach"] == f"{VT}-006" and cso["reach_basis_outfalls"][0]["candidates"] == 3


# ---------------------------------------------------------------- the order of the candidates (review findings 3, 4)

def _one(key, segs, cut="end_of_trace"):
    return {**reach(VT, key, "conn-river-vt", segs), "cut_reason": cut}


def test_an_upstream_outlet_whose_trace_stops_before_the_others_is_not_proof_of_order():
    # a runs along flowline 10 and is cut at the cap inside flowline 11, where b starts: whether a reaches b is unknown
    a = _one("a", [seg(10, C, 200, 0.0, 39.0, [[-72.0, 43.6], [-71.95, 43.6]]),
                   seg(11, C, 100, 39.0, 40.0, [[-71.95, 43.6], [-71.94, 43.6]])], cut="cap_km")
    b = _one("b", [seg(11, C, 100, 0.0, 3.0, [[-71.93, 43.6], [-71.9, 43.6]]),
                   seg(12, C, 90, 3.0, 9.0, [[-71.9, 43.6], [-71.85, 43.6]])])
    c = _one("c", [seg(12, C, 90, 0.0, 2.0, [[-71.88, 43.6], [-71.85, 43.6]])])
    assert S._order(a, b) == (None, None)
    assert S._order(b, c)[0] == 1
    assert S.most_upstream([a, b, c]) is None         # the old count of covered starts chose b, a downstream outlet


def test_two_capped_outlets_on_one_long_flowline_are_not_ordered():
    a = _one("a", [seg(10, C, 200, 0.0, 40.0, [[-72.0, 43.6], [-71.95, 43.6]])], cut="cap_km")
    b = _one("b", [seg(10, C, 200, 0.0, 40.0, [[-71.99, 43.6], [-71.95, 43.6]])], cut="cap_km")
    assert S._order(a, b) == (None, None) and S.most_upstream([a, b]) is None


def test_outlets_on_separate_branches_are_chosen_only_when_all_start_within_a_kilometre():
    def branch(key, comid, run):
        return _one(key, [seg(comid, C, 300 + comid, 0.0, run, [[-71.99, 43.61], [-71.99, 43.6]]),
                          seg(10, C, 200, run, run + 2.0, [[-71.99, 43.6], [-71.95, 43.6]])])
    far = [branch("a", 5, 3.0), branch("b", 6, 0.4)]
    assert S._order(*far) == (None, 3.4) and S.most_upstream(far) is None
    near = [branch("a", 5, 0.5), branch("b", 6, 0.3)]
    assert S.most_upstream(near)["key"] == f"{VT}-a"      # farther above the flowline where they meet
    assert S.most_upstream([branch("a", 5, 0.4), branch("b", 6, 0.4)])["key"] == f"{VT}-a"   # the same place: lower key


def test_the_upstream_outlet_is_found_by_position_not_by_key():
    rs = vt_reaches()
    assert S.most_upstream([rs[f"{VT}-007"], rs[f"{VT}-004"]])["key"] == f"{VT}-004"
    assert S._order(rs[f"{VT}-004"], rs[f"{VT}-007"])[0] == 1 and S._order(rs[f"{VT}-007"], rs[f"{VT}-004"])[0] == -1


def test_the_selection_is_made_once_per_permit_preference_and_river(monkeypatch):
    calls = []
    real = S.most_upstream
    monkeypatch.setattr(S, "most_upstream", lambda c: calls.append(1) or real(c))
    rs = vt_reaches()
    st, _ = build([vt_bypass(str(n)) for n in range(5)], rs, VT_ROWS)
    assert len(calls) == 1 and all(placements_of(st, f"vt-dec:{n}")["reach"] == f"{VT}-004" for n in range(5))


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


def manchester():
    return event(source_id="vt-dec", source_record_id="mht", event_type="cso", status="ongoing", npdes_permit=NH,
                 water_slugs=["merrimack-river-nh", "piscataquog-river-nh"], started_at=(NOW - 3 * H).isoformat())


def test_a_cso_report_naming_two_rivers_gets_one_stretch_per_river():
    st, _ = build([manchester()], nh_reaches(), NH_ROWS)
    p = placements_of(st, "vt-dec:mht")
    assert p["reach"] == f"{NH}-001" and p["reaches"] == [f"{NH}-001", f"{NH}-010"]
    assert [(x["water_slug"], x["outfall"], x["candidates"]) for x in p["reach_basis_outfalls"]] == [
        ("merrimack-river-nh", "001", 2), ("piscataquog-river-nh", "010", 2)]
    assert p["reach_basis_note"] == ("The report names no outlet. The stretches are drawn from the operator's most "
                                     "upstream registered outlet on each river (Merrimack River: outfall 001, one of its 2 outlets there; "
                                     "Piscataquog River: outfall 010, one of its 2 outlets there); our choice, not the report's.")
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
    st, _ = build([vt_bypass("oth", water_slugs=["other-river-vt"], waterbody_text="Other River")],
                  vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:oth")
    assert "reach" not in p and "reach_basis" not in p
    assert [r["placement"] for r in st["waters"]["other-river-vt"]["reasons"]] == ["unmodeled"]
    st, _ = build([vt_bypass("none")], {}, VT_ROWS)          # nothing traced at all
    assert "reach_basis" not in placements_of(st, "vt-dec:none")
    assert [r["placement"] for r in st["waters"]["conn-river-vt"]["reasons"]] == ["unmodeled"]


UNMATCHED_NOTE = ("The outlet the report names is not in our outlet records. The stretch is drawn from the operator's "
                  "most upstream registered outlet on this river (outfall 004, one of its 2 outlets on this river); our choice, not the report's.")


def test_a_facility_name_in_the_outfall_name_is_not_an_outlet():
    """Vermont's record gives "White River Junction" as its outfall name: the plant's place, no outlet."""
    st, _ = build([vt_bypass("wrj", outfall_name="White River Junction")], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:wrj")
    assert p["reach"] == f"{VT}-004" and p["reach_basis"] == "permit_outlet_unnamed"
    assert p["reach_basis_note"].startswith("The report names no outlet.")


def test_an_outlet_the_registry_does_not_hold_is_drawn_from_the_upstream_outlet_and_said_so():
    """Review finding 1, revised: an outlet the report names that the registry does not hold (an unresolved
    outfall_id, an outfall number in its name or per-outfall volume, an outlet description) changes the basis and the
    note; the note never quotes the report's outlet text."""
    recs = [vt_bypass("id", outfall_id="002"),                                   # 002 is in no registry row
            vt_bypass("nm", event_type="cso", outfall_name="CSO 999"),
            vt_bypass("vol", event_type="cso", volume_text="999-0.2 MG 1405 to 1650",
                      raw={"Final Volume": "999-0.2 MG 1405 to 1650"}),
            vt_bypass("desc", event_type="cso", outfall_name="CSO outfall at 12 Elm Street")]
    st, hist = build(recs, vt_reaches(), VT_ROWS)
    for r in ("id", "nm", "vol", "desc"):
        p = placements_of(st, f"vt-dec:{r}")
        assert p["reach"] == f"{VT}-004" and p["reach_basis"] == "permit_outlet_unmatched", r
        assert p["reach_basis_note"] == UNMATCHED_NOTE, r
        assert "Elm" not in json.dumps(p) and "999" not in p["reach_basis_note"]
    # the reach, its history and its active band carry the basis
    assert st["reaches"][f"{VT}-004"]["reach_basis_events"]["vt-dec:id"]["reach_basis"] == "permit_outlet_unmatched"
    assert any(iv[4] == "vt-dec:id" and iv[6:] == ["permit_outlet_unmatched"] for iv in hist["reach_intervals"][f"{VT}-004"])
    a = [x for x in st["reach_events_active"] if x["event_id"] == "vt-dec:id"][0]
    assert a["reach_basis"] == "permit_outlet_unmatched" and a["reach_basis_note"] == UNMATCHED_NOTE


def test_an_unresolved_outfall_id_reaches_the_rule():
    """An outfall_id the registry lacks finds no reach in event_reaches and is not placed by outfall: the record gets
    as far as the rule (before: it stayed unmodeled)."""
    e = vt_bypass("id", outfall_id="002")
    assert S.event_reaches(e, {"water_slugs": ["conn-river-vt"]}, S.index_reaches(vt_reaches())) == []
    st, _ = build([e], vt_reaches(), VT_ROWS)
    assert placements_of(st, "vt-dec:id")["reach_basis"] == "permit_outlet_unmatched"


def test_an_outlet_the_registry_holds_is_never_drawn_from_another_outlet():
    """The registry holds outfall 001 (a plant outfall with no trace yet) and outfall 005 (closed): a report naming
    either waits for its own outlet, by number or by the registry's outfall name; a point goes to needs_reach."""
    rows = VT_ROWS + [{**row(VT, "008", "conn-river-vt"), "outfall_name": "Bridge Street Regulator"}]
    recs = [vt_bypass("own", outfall_id="001"), vt_bypass("cls", event_type="cso", outfall_name="CSO 005"),
            vt_bypass("byname", event_type="cso", outfall_name="Bridge Street Regulator"),
            vt_bypass("pt", lat=43.6, lon=-71.97)]
    st, _ = build(recs, vt_reaches(), rows)
    for r in ("own", "cls", "byname", "pt"):
        p = placements_of(st, f"vt-dec:{r}")
        assert "reach_basis" not in p and "reach" not in p, r
    assert [n["event_id"] for n in st["needs_reach"]] == ["vt-dec:pt"]       # traced from its own point, as before


def test_a_river_taken_from_the_permit_is_drawn_from_the_permits_own_outlet_and_said_so():
    """Review finding 2, reverted: a report naming no water, placed on the river its permit names ("inferred"), gets
    the stretch of the permit's own outlet that starts on that river; the note says where the river comes from."""
    bare = vt_bypass("bare", water_slugs=[], waterbody_text=None)
    by_text = vt_bypass("text", water_slugs=[])
    st, _ = build([bare, by_text], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:bare")
    assert p["water_match"] == "inferred" and p["reach"] == f"{VT}-004"
    assert p["reach_basis"] == "permit_outlet_unnamed" and p["reach_basis_outfalls"][0]["water_named"] is False
    assert p["reach_basis_note"].endswith("(outfall 004, one of its 2 outlets on this river); our choice, not the report's. The report names no "
                                          "water; this river is the one the operator's permit names.")
    t = placements_of(st, "vt-dec:text")
    assert t["reach"] == f"{VT}-004" and t["reach_basis_outfalls"][0]["water_named"] is True
    assert "permit names" not in t["reach_basis_note"]


def test_the_note_names_the_rivers_the_report_does_not_name():
    picks = [{"outfall": "001", "water_slugs": ["merrimack-river-nh"], "candidates": {"merrimack-river-nh": 2}},
             {"outfall": "010", "water_slugs": ["piscataquog-river-nh"], "candidates": {"piscataquog-river-nh": 2}}]
    some = S.permit_outlet_note(picks, WATERS, "permit_outlet_unnamed", {"merrimack-river-nh"})
    assert some.endswith("The report does not name the Piscataquog River; the operator's permit does.")
    none = S.permit_outlet_note(picks, WATERS, "permit_outlet_unmatched", set())
    assert none.startswith("The outlet the report names is not in our outlet records. The stretches are drawn")
    assert none.endswith("The report names no water; these rivers are the ones the operator's permit names.")


def test_an_outlet_on_a_tributary_never_stands_for_the_named_river():
    """Review finding 5: the only outlet starts on the White River; a report naming the Connecticut gets none."""
    rows = [row(VT, "006", "white-river-vt")]
    rs = {f"{VT}-006": {**vt_reaches()[f"{VT}-006"], "water_slug": "white-river-vt"}}
    st, _ = build([vt_bypass()], rs, rows)
    assert "reach_basis" not in placements_of(st, "vt-dec:hqs")
    assert "white-river-vt" not in st["waters"] or not st["waters"]["white-river-vt"]["reasons"]


def test_a_cached_trace_without_a_current_registry_row_is_never_used():
    """Review finding 6: outfall 004 left the registry; its cached trace stays out."""
    rows = [r for r in VT_ROWS if r["outfall"] != "004"]
    st, _ = build([vt_bypass()], vt_reaches(), rows)
    p = placements_of(st, "vt-dec:hqs")
    assert p["reach"] == f"{VT}-007" and p["reach_basis_outfalls"][0]["candidates"] == 1


def test_closed_and_untraced_outfalls_are_skipped():
    rs = vt_reaches()
    rows = [row(VT, "004", "conn-river-vt", status="CLS")] + [r for r in VT_ROWS if r["outfall"] != "004"]
    st, _ = build([vt_bypass()], rs, rows)
    p = placements_of(st, "vt-dec:hqs")
    assert p["reach"] == f"{VT}-007" and p["reach_basis_outfalls"][0]["candidates"] == 1
    rs[f"{VT}-007"] = {**rs[f"{VT}-007"], "cut_reason": "no_trace"}
    st, _ = build([vt_bypass()], rs, rows)
    assert "reach_basis" not in placements_of(st, "vt-dec:hqs")
    rs[f"{VT}-007"] = {**rs[f"{VT}-007"], "segments": [], "cut_reason": "tidal_at_outfall"}
    st, _ = build([vt_bypass()], rs, rows)
    assert "reach_basis" not in placements_of(st, "vt-dec:hqs")


def test_a_monthly_total_gets_no_outlet_stretch():
    e = vt_bypass("mo", time_precision="month", started_at=(NOW - 40 * 24 * H).isoformat())
    st, _ = build([e], vt_reaches(), VT_ROWS)
    assert "reach_basis" not in placements_of(st, "vt-dec:mo") and "reach" not in placements_of(st, "vt-dec:mo")


def test_a_future_start_gets_no_outlet_stretch():
    e = vt_bypass("fut", started_at=(NOW + 5 * 24 * H).isoformat())
    st, _ = build([e], vt_reaches(), VT_ROWS)
    p = placements_of(st, "vt-dec:fut")
    assert p.get("future_start") is True and "reach_basis" not in p and "reach" not in p
    assert st["reaches"] == {}


# ---------------------------------------------------------------- the export

TOKEN = "Zqxname Privatesurname"


class _Redactor:
    """Removes a synthetic private name, as the export's redactor removes a blocklisted one."""
    def note(self, text, swaps=()):
        return text.replace(TOKEN, "[name withheld]") if isinstance(text, str) else text


def _no_token(o):
    assert TOKEN not in json.dumps(o)


def test_the_export_carries_the_basis_and_redacts_the_note_on_every_path():
    from export import build as X
    e = vt_bypass()
    rs = vt_reaches()
    st, _ = build([e], rs, VT_ROWS)
    # a note quoting a private name (a water named after a person, say): every copy must lose it
    for a in st["reach_events_active"]:
        a["reach_basis_note"] += f" {TOKEN}"
    for b in st["reaches"][f"{VT}-004"]["reach_basis_events"].values():
        b["reach_basis_note"] += f" {TOKEN}"
    pl = {**st["placements"]["vt-dec:hqs"]}
    pl["reach_basis_note"] += f" {TOKEN}"
    X.redact_status_texts(st, _Redactor())
    rec = X.public_record({**e}, pl, _Redactor())
    _no_token(rec)
    assert rec["reach_basis"] == "permit_outlet_unnamed" and rec["reach"] == f"{VT}-004"
    assert rec["reach_basis_outfalls"][0]["outfall"] == "004" and rec["reach_basis_outfalls"][0]["candidates"] == 2
    assert rec["reach_basis_note"].startswith("The report names no outlet.")
    assert rec["outfall_id"] is None and rec["lat"] is None and rec["lon"] is None      # the record as published
    feats, paths = X.reach_features(st, {"vt-dec:hqs": {"started_at": e["started_at"]}}, cached=rs)
    _no_token(feats), _no_token(paths)
    segs = [f["properties"] for f in feats if f["properties"]["feature"] == "segment"]
    stops = [f["properties"] for f in feats if f["properties"]["feature"] == "stop"]
    assert segs and all(s["reach_basis"] == "permit_outlet_unnamed" and s["outfall"] == "004" for s in segs)
    assert all("our choice, not the report's." in s["label"] and "[name withheld]" in s["label"] for s in segs)
    assert stops and stops[0]["reach_basis"] == "permit_outlet_unnamed"
    path = [f["properties"] for f in paths if f["properties"]["reach"] == f"{VT}-004"][0]
    assert path["reach_basis_events"]["vt-dec:hqs"]["reach_basis"] == "permit_outlet_unnamed"
    assert all("reach_basis_events" not in f["properties"] for f in paths if f["properties"]["reach"] != f"{VT}-004")
    bands = X.band_fields([a for a in st["reach_events_active"] if a["event_id"] == "vt-dec:hqs"], pl)
    _no_token(bands)
    assert bands["reach_band"]["reach"] == f"{VT}-004" and "reach_bands" not in bands
    # a record drawn from its own outfall keeps its features as before: no basis fields
    plain = {"reach_events_active": [{k: v for k, v in a.items() if not k.startswith("reach_basis")}
                                     for a in st["reach_events_active"]],
             "reaches": {k: {f: x for f, x in v.items() if f != "reach_basis_events"} for k, v in st["reaches"].items()}}
    feats, paths = X.reach_features(plain, {"vt-dec:hqs": {"started_at": e["started_at"]}}, cached=rs)
    assert all("reach_basis" not in f["properties"] and "reach_basis_events" not in f["properties"]
               for f in feats + paths)
    rec = X.public_record({**e}, {"water_slugs": ["conn-river-vt"]}, _Redactor())
    assert "reach_basis" not in rec and "reach_basis_note" not in rec


def test_a_record_on_two_rivers_exports_the_band_of_its_reach_and_one_per_reach():
    """Review finding 9: the singular band is the singular reach's; every band is listed."""
    from export import build as X
    st, _ = build([manchester()], nh_reaches(), NH_ROWS)
    pl = st["placements"]["vt-dec:mht"]
    out = X.band_fields([a for a in st["reach_events_active"] if a["event_id"] == "vt-dec:mht"], pl)
    assert out["reach_band"]["reach"] == pl["reach"] == f"{NH}-001"
    assert sorted(b["reach"] for b in out["reach_bands"]) == [f"{NH}-001", f"{NH}-010"]
    assert all(b["reach_basis"] == "permit_outlet_unnamed" for b in out["reach_bands"])


def test_reported_outfalls_ignores_a_stretch_drawn_for_a_report_naming_no_outlet(tmp_path, monkeypatch):
    from build import reaches as R
    monkeypatch.setattr(R, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path / "events")
    (tmp_path / "status.json").write_text(json.dumps({"placements": {
        "a": {"reach": f"{VT}-006", "reach_basis": "permit_outlet_unnamed"}, "b": {"reach": f"{VT}-004"}}}))
    assert R.reported_outfalls() == {f"{VT}-004"}


def test_the_status_summary_counts_the_records_drawn_from_a_chosen_outlet():
    from build.status import outlet_basis_summary
    assert outlet_basis_summary({}) == "status: no record drawn from an outlet chosen for it (reach_basis)"
    pls = {
        "a": {"reach_basis": "permit_outlet_unnamed",
              "reach_basis_outfalls": [{"reach": "VT0101010-004", "water_named": True}]},
        "b": {"reach_basis": "permit_outlet_unmatched",
              "reach_basis_outfalls": [{"reach": "NY0027081-067", "water_named": True}]},
        "c": {"reach_basis": "permit_outlet_unnamed",
              "reach_basis_outfalls": [{"reach": "NH0100447-031", "water_named": False},
                                       {"reach": "NH0100447-039", "water_named": False}]},
        "d": {"reach": "MA0101613-010"},
    }
    assert outlet_basis_summary(pls) == (
        "status: 3 records drawn from an outlet chosen for them (reach_basis) "
        "{'permit_outlet_unmatched': 1, 'permit_outlet_unnamed': 2} on 4 reaches; "
        "1 with a river taken from the permit")


def test_the_note_never_reads_as_the_fourth_of_two():
    from build.status import outlet_among
    assert outlet_among("004", 2) == "outfall 004, one of its 2 outlets on this river"
    assert outlet_among("039", 1) == "outfall 039, its only outlet on this river"
    assert outlet_among("031", 14, "there") == "outfall 031, one of its 14 outlets there"
