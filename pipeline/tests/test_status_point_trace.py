"""A recent discharge report with its own point and no water: traced downstream from that point on a basis
(build/status.py POINT_TRACE_BASES): (a) the source says it reached water, (b) a kind that discharges to water by
definition, (c) its location lies within POINT_TRACE_NEAR_M of the stretch's start. Contained or denied: never."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build import status as S  # noqa: E402
from tests.test_status import NOW, H, TEST_RULES, ev, iso, tmp_events, world  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


FAR = {"lat": 42.06, "lon": -71.95}      # about 6.7 km from the Test River record: placed on no water


def spill(rid, **kw):
    kw.setdefault("event_type", "sso")
    kw.setdefault("status", "ongoing")
    kw.setdefault("started_at", iso(NOW - 2 * H))
    kw.setdefault("water_slugs", [])
    for k, v in FAR.items():
        kw.setdefault(k, v)
    return ev(rid, **kw)


def point_reach(eid, start=(-71.95, 42.0605)):
    """A stretch traced from the point: a nameless brook from `start` down to the Test River, then along it."""
    import hashlib
    key = "pt-" + hashlib.sha1(eid.encode()).hexdigest()[:12]
    return key, {"key": key, "permit": None, "outfall": None, "water_slug": None, "lat": FAR["lat"], "lon": FAR["lon"],
                 "event_ids": [eid], "sources": ["event-point"], "river": None, "cut_reason": "cap_km", "length_km": 10.0,
                 "segments": [
                     {"comid": 1, "km_start": 0.0, "km_end": 6.7, "totdasqkm": 10, "qe_ma": 5, "slope": 1e-3,
                      "gnis_name": None, "coords": [list(start), [-71.95, 42.0]]},
                     {"comid": 2, "km_start": 6.7, "km_end": 10.8, "totdasqkm": 25000, "qe_ma": 18000, "slope": 2.6e-4,
                      "gnis_name": "Test River", "coords": [[-71.95, 42.0], [-71.9, 42.0]]}]}


def _ma():
    from shapely.geometry import box
    return {"MA": box(-73.51, 41.23, -69.92, 42.89), "NC": box(-84.33, 33.84, -75.46, 36.59)}


def run(records, reaches=None, outlines=None):
    w = world(tmp_events(records))
    w["reaches"] = dict(reaches or {})
    st, hist = S.build(now=NOW, write=False, state_outlines=_ma() if outlines is None else outlines, **w)
    return st, hist


def queued(st):
    return {n["event_id"]: n for n in st["needs_reach"]}


def test_each_basis_queues_the_point():
    a = spill("a", raw={"reached_water": True})
    a2 = spill("a2", raw={"Reach Waterbody": "Yes"})
    a3 = spill("a3", waterbody_text="unnamed tributary of Bear Creek")
    b = spill("b", event_type="cso")
    c = spill("c")                                  # silent: traced once to measure its distance to a stream
    st, _ = run([a, a2, a3, b, c])
    q = queued(st)
    assert q["ma-test:a"]["basis"] == S.POINT_TRACE_REACHED and q["ma-test:a"]["water_slug"] is None
    assert q["ma-test:a2"]["basis"] == S.POINT_TRACE_REACHED and q["ma-test:a3"]["basis"] == S.POINT_TRACE_REACHED
    assert q["ma-test:b"]["basis"] == S.POINT_TRACE_OUTLET and q["ma-test:c"]["basis"] == S.POINT_TRACE_NEAR
    assert q["ma-test:a"]["lat"] == FAR["lat"]
    assert st["counts"]["point_trace"]["queued"] == {S.POINT_TRACE_NEAR: 1, S.POINT_TRACE_OUTLET: 1,
                                                     S.POINT_TRACE_REACHED: 3}
    assert all(not st["placements"][i]["water_slugs"] for i in q)      # nothing placed until traced


def test_a_contained_or_denied_spill_is_never_queued():
    recs = [spill("w", waterbody_text="SSO was contained on site"),       # no receiving water (STATED_NO_WATER)
            spill("f", raw={"reached_water": False}),                        # the form's flag
            spill("bal", raw={"_water_reach": "No"}),                        # Baltimore's OVFL_REACH_WW
            spill("hou", raw={"flow_location": "Storm Sewer - contained on site"}),
            spill("rec", volume_gal=500, raw={"reached_water": True, "volume_recovered_gal": 500}),
            spill("cso", event_type="cso", raw={"reached_water": False})]
    st, _ = run(recs)
    assert st["needs_reach"] == []
    assert sum(st["counts"]["point_trace"]["aside"].values()) == 6


def test_a_denied_spill_with_a_cached_trace_is_not_drawn():
    e = spill("bal", raw={"_water_reach": "No"})
    k, r = point_reach(e["event_id"])
    st, _ = run([e], {k: r})
    assert "reach" not in st["placements"][e["event_id"]] and k not in st["reaches"]
    assert st["placements"][e["event_id"]]["water_slugs"] == []


def test_a_traced_report_gets_its_waters_colours_and_note():
    e = spill("a", raw={"reached_water": True})
    k, r = point_reach(e["event_id"])
    st, hist = run([e], {k: r})
    pl = st["placements"][e["event_id"]]
    assert pl["reach"] == k and pl["water_slugs"] == ["test-river-ma"] and pl["water_match"] == S.POINT_TRACE_MATCH
    assert pl["reach_basis"] == S.POINT_TRACE_REACHED
    assert pl["note"].endswith(S.POINT_TRACE_TAIL) and "The source says the discharge reached water." in pl["note"]
    assert pl["reach_basis_note"].startswith(S.POINT_TRACE_LEAD)
    assert st["reaches"][k]["status"] == "red"
    assert st["waters"]["test-river-ma"]["status"] == "red"
    assert st["waters"]["test-river-ma"]["reasons"][0]["placement"] == "reach"
    assert e["event_id"] not in st["unplaced_events"] and st["needs_reach"] == []
    assert st["counts"]["point_trace"]["traced"] == {S.POINT_TRACE_REACHED: 1}
    assert hist["reaches"][k][-1] == "r"


def test_a_cso_is_drawn_on_its_kind():
    e = spill("b", event_type="cso")
    k, r = point_reach(e["event_id"])
    st, _ = run([e], {k: r})
    pl = st["placements"][e["event_id"]]
    assert pl["reach_basis"] == S.POINT_TRACE_OUTLET and "combined sewer overflow" in pl["note"]


def test_silent_and_near_is_drawn_and_silent_and_far_is_counted():
    near = spill("c")
    far = spill("d")
    kn, rn = point_reach(near["event_id"])                          # starts about 55 m from the point
    kf, rf = point_reach(far["event_id"], start=(-71.95, 42.07))    # starts about 1.1 km from it
    st, _ = run([near, far], {kn: rn, kf: rf})
    pn, pf = st["placements"][near["event_id"]], st["placements"][far["event_id"]]
    assert pn["reach_basis"] == S.POINT_TRACE_NEAR and "from a mapped stream" in pn["note"]
    assert pn["water_slugs"] == ["test-river-ma"]
    assert pf["water_slugs"] == [] and "reach" not in pf and kf not in st["reaches"]
    assert st["needs_reach"] == []                                  # traced once: never queued again
    aside = st["counts"]["point_trace"]["aside"]
    assert list(aside.values()) == [1] and "over 400 m" in next(iter(aside))


def test_a_stretch_on_no_water_record_still_colours_the_stretch():
    e = spill("a", raw={"reached_water": True})
    k, r = point_reach(e["event_id"])
    r["segments"] = [{**r["segments"][0], "coords": [[-71.95, 42.0605], [-71.95, 42.03]]}]   # a brook, far from any record
    st, _ = run([e], {k: r})
    pl = st["placements"][e["event_id"]]
    assert st["reaches"][k]["status"] == "red" and pl["reach_basis"] == S.POINT_TRACE_REACHED
    assert pl["water_slugs"] == [] and e["event_id"] in st["unplaced_events"]


def test_a_report_on_a_river_behaves_as_before():
    e = ev("brk", event_type="sso", status="ongoing", started_at=iso(NOW - 2 * H), lat=42.0, lon=-71.99)
    st, _ = run([e])
    n = queued(st)["ma-test:brk"]
    assert n["water_slug"] == "test-river-ma" and "basis" not in n
    assert st["counts"]["point_trace"] == {"traced": {}, "queued": {}, "aside": {}}


def test_nothing_older_than_30_days_is_queued():
    old = spill("old", raw={"reached_water": True}, started_at=iso(NOW - 31 * 24 * H), status="ended",
                ended_at=iso(NOW - 31 * 24 * H + H))
    undated = spill("u", raw={"reached_water": True}, started_at=None, status="ended")
    reported = spill("r", raw={"reached_water": True}, started_at=None, reported_at=iso(NOW - 3 * H))
    st, _ = run([old, undated, reported])
    assert [n["event_id"] for n in st["needs_reach"]] == ["ma-test:r"]
    assert st["counts"]["point_trace"]["queued"] == {S.POINT_TRACE_REACHED: 1}


def test_month_precision_and_advisories_are_unaffected():
    month = spill("m", time_precision="month", event_type="cso")
    adv = spill("adv", event_type="beach_advisory", status="advisory_active")
    st, _ = run([month, adv])
    assert st["needs_reach"] == []
    assert st["counts"]["point_trace"] == {"traced": {}, "queued": {}, "aside": {}}


def test_a_named_outlet_with_no_water_record_takes_its_outlets_stretch():
    from tests.test_status import _reach
    e = spill("o", event_type="cso", npdes_permit="MA0101613", outfall_id="013")
    r = {**_reach(slug=None), "segments": point_reach("x")[1]["segments"]}
    st, _ = run([e], {r["key"]: r})
    pl = st["placements"][e["event_id"]]
    assert pl["reach"] == r["key"] and pl["reach_basis"] == S.POINT_TRACE_OUTLET
    assert pl["note"].endswith(S.POINT_TRACE_TAIL_OUTLET) and pl["water_slugs"] == ["test-river-ma"]
    assert st["needs_reach"] == []


# ---------------------------------------------------------------- review 2026-11-28 (Astra P1, P2 x4)

def test_a_water_the_report_says_was_not_reached_is_never_coloured_or_listed():
    e = spill("x", waterbody_text="Did not impact Test River; sewage entered Bear Creek")    # Bear Creek: no record
    k, r = point_reach(e["event_id"])                       # its stretch runs down the brook into the Test River
    st, hist = run([e], {k: r})
    pl = st["placements"][e["event_id"]]
    assert pl["water_slugs"] == [] and "reach" not in pl and k not in st["reaches"]
    river = st["waters"].get("test-river-ma") or {}
    assert river.get("status", "grey") == "grey" and not river.get("reasons")
    assert e["event_id"] not in str(river)
    assert S.POINT_TRACE_TAIL not in (pl.get("note") or "") and "not placed there" in pl["note"]
    assert pl["point_trace_aside"] == S.POINT_TRACE_NOT_REACHED
    assert st["counts"]["point_trace"]["aside"] == {S.POINT_TRACE_NOT_REACHED: 1}
    assert k not in (hist.get("reaches") or {})


def test_a_written_recovery_or_denial_is_never_traced_and_partial_recovery_is():
    recs = [spill("all", raw={"description": "All sewage fully recovered"}),
            spill("before", raw={"comments": "Spill was cleaned up before reaching the stream."}),
            spill("vol", volume_text="50 gallons, completely contained in the manhole"),
            spill("nod", raw={"remarks": "No discharge to waters of the state"}),
            spill("part", raw={"description": "Sewage partially recovered"}),
            spill("most", raw={"description": "Most of it was recovered; not all recovered"})]
    st, _ = run(recs)
    assert sorted(n["event_id"] for n in st["needs_reach"]) == ["ma-test:most", "ma-test:part"]
    assert st["counts"]["point_trace"]["aside"] == {
        "the source says no water was reached, or the spill was contained or recovered": 4}
    # a cached trace of a written recovery is not drawn either
    e = spill("all2", raw={"description": "All of the spill was recovered by vacuum truck"})
    k, r = point_reach(e["event_id"])
    st, _ = run([e], {k: r})
    assert k not in st["reaches"] and (st["waters"].get("test-river-ma") or {}).get("status", "grey") == "grey"
    # words saying it reached a water win (err on safety)
    assert S.written_denial(spill("y", raw={"description": "Spill entered Bear Creek; all recovered"})) is None


def test_a_rejected_trace_is_not_the_rain_cautions_place():
    from build import rain_sso as SS
    far, denied, near = spill("d"), spill("bal", raw={"_water_reach": "No"}), spill("c")
    kf, rf = point_reach(far["event_id"], start=(-71.95, 42.07))      # 1.1 km: no basis, too far
    kd, rd = point_reach(denied["event_id"])
    kn, rn = point_reach(near["event_id"])
    reaches = {kf: rf, kd: rd, kn: rn}
    st, _ = run([far, denied, near], reaches)
    assert st["placements"][far["event_id"]]["point_trace_aside"].startswith("no stated basis")
    assert st["placements"][denied["event_id"]]["point_trace_aside"].startswith("the source says")
    entry = {"places": {"events": [{"event_id": x["event_id"], "point": [x["lat"], x["lon"]], "water_slugs": [],
                                    "reaches": []} for x in (far, denied, near)], "waters": []}}
    keys, tags, _, _ = SS.placement(entry, {}, reaches, lambda r, w: ["test-river-ma"], st["placements"])
    assert keys == [kn] and tags == {"test-river-ma": "reach"}
    # the caution's own trace of a report on a river (no point-trace verdict) is used as before
    keys, _, _, _ = SS.placement(entry, {}, reaches, lambda r, w: [], {})
    assert keys == sorted([kf, kd, kn])


def test_a_point_outside_its_state_or_malformed_is_not_traced():
    recs = [spill("zero", raw={"reached_water": True}, lat=0.0, lon=0.0),
            spill("swap", raw={"reached_water": True}, lat=-71.95, lon=42.06),
            spill("nc", raw={"reached_water": True}, lat=35.78, lon=-78.64),        # an MA report located in NC
            spill("sign", event_type="cso", lat=42.06, lon=71.95),
            spill("ok", raw={"reached_water": True})]
    st, _ = run(recs)
    assert [n["event_id"] for n in st["needs_reach"]] == ["ma-test:ok"]
    aside = st["counts"]["point_trace"]["aside"]
    assert aside == {"its location cannot be used (at (0, 0))": 1,
                     "its location cannot be used (latitude and longitude swapped)": 1,
                     "its location cannot be used (outside MA)": 1,
                     "its location cannot be used (longitude without its minus sign)": 1}
    # with no outline to check against, nothing is traced (fail closed) and the reason is counted
    st, _ = run([spill("ok", raw={"reached_water": True})], outlines={})
    assert st["needs_reach"] == [] and st["counts"]["point_trace"]["aside"] == {
        "its location cannot be used (no MA outline to check the point against)": 1}


def test_a_stated_basis_still_needs_the_stretch_to_start_near_the_point():
    near_a = spill("a", raw={"reached_water": True})
    far_a = spill("fa", raw={"reached_water": True})
    far_b = spill("fb", event_type="cso")
    ka, ra = point_reach(near_a["event_id"], start=(-71.95, 42.07))          # 1.1 km: within 2 km
    kfa, rfa = point_reach(far_a["event_id"], start=(-71.95, 42.0855))      # about 2.8 km
    kfb, rfb = point_reach(far_b["event_id"], start=(-71.95, 42.0855))
    st, _ = run([near_a, far_a, far_b], {ka: ra, kfa: rfa, kfb: rfb})
    assert st["placements"][near_a["event_id"]]["reach"] == ka
    for e, k in ((far_a, kfa), (far_b, kfb)):
        pl = st["placements"][e["event_id"]]
        assert "reach" not in pl and pl["water_slugs"] == [] and k not in st["reaches"]
    assert st["counts"]["point_trace"]["aside"] == {f"its stretch starts over {S.POINT_TRACE_FAR_M:,} m from its location": 2}
    assert S.POINT_TRACE_FAR_M == 2000


def test_a_named_registered_outlet_needs_no_point_of_its_own():
    from tests.test_status import _reach
    segs = point_reach("x")[1]["segments"]
    no_water = {**_reach(slug=None), "segments": segs}
    # no point, the registry's own outfall number written with its prefix (SPR013 for 013)
    e = ev("o", event_type="cso", status="ongoing", started_at=iso(NOW - 2 * H), npdes_permit="MA0101613",
           outfall_id="SPR013", water_slugs=[])
    st, hist = run([e], {no_water["key"]: no_water})
    pl = st["placements"][e["event_id"]]
    assert pl["reach"] == no_water["key"] and pl["reach_basis"] == S.POINT_TRACE_OUTLET
    assert pl["note"].endswith(S.POINT_TRACE_TAIL_OUTLET) and pl["water_slugs"] == ["test-river-ma"]
    assert st["waters"]["test-river-ma"]["status"] == "red" and st["reaches"][no_water["key"]]["status"] == "red"
    assert st["needs_reach"] == [] and st["counts"]["point_trace"]["traced"] == {S.POINT_TRACE_OUTLET: 1}
    # one interval for the water, one for the stretch: nothing counted twice
    assert len(st["waters"]["test-river-ma"]["reasons"]) == 1
    # an outlet whose trace starts on a water record the report is not placed on: the same
    with_water = {**_reach(), "segments": segs}
    st, _ = run([e], {with_water["key"]: with_water})
    pl = st["placements"][e["event_id"]]
    assert pl["reach_basis"] == S.POINT_TRACE_OUTLET and pl["water_slugs"] == ["test-river-ma"]
    # a monthly total naming the same outlet: never a reach, as before
    m = ev("m", event_type="cso", status="ended", started_at=iso(NOW - 40 * 24 * H), time_precision="month",
           npdes_permit="MA0101613", outfall_id="013", water_slugs=[])
    st, _ = run([m], {no_water["key"]: no_water})
    assert "reach" not in st["placements"][m["event_id"]] or not st["placements"][m["event_id"]].get("reach_basis")
    assert st["counts"]["point_trace"] == {"traced": {}, "queued": {}, "aside": {}}


# ---------------------------------------------------------------- review 2026-11-28 pass 2 (Astra P1, P2 x2, P3)

OTHER_BROOK = {"slug": "other-brook-ma", "name": "Other Brook", "kind": "stream", "state": "MA",
               "bbox": [-71.95, 42.03, -71.95, 42.0605],
               "geometry": {"type": "LineString", "coordinates": [[-71.95, 42.0605], [-71.95, 42.03]]}}


def test_a_placed_report_never_colours_a_water_it_says_was_not_reached():
    from build import rain_sso as SS
    e = spill("placed", waterbody_text="Did not impact Test River; sewage entered Other Brook")
    k, r = point_reach(e["event_id"])
    r["segments"][0]["gnis_name"] = "Other Brook"          # its stretch runs down Other Brook into the Test River
    w = world(tmp_events([e]))
    w["waters"]["other-brook-ma"] = dict(OTHER_BROOK)
    w["reaches"] = {k: r}
    st, hist = S.build(now=NOW, write=False, state_outlines=_ma(), **w)
    pl = st["placements"][e["event_id"]]
    assert pl["water_slugs"] == ["other-brook-ma"]          # the water it names is still shown
    assert st["waters"]["other-brook-ma"]["status"] == "red"
    river = st["waters"].get("test-river-ma") or {}
    assert river.get("status", "grey") == "grey" and not river.get("reasons") and e["event_id"] not in str(river)
    assert "reach" not in pl and k not in st["reaches"] and k not in (hist.get("reaches") or {})
    assert pl["point_trace_aside"] == S.POINT_TRACE_NOT_REACHED and S.point_trace_withheld(pl, k)
    assert st["needs_reach"] == []                          # never queued again for the same trace
    entry = {"places": {"events": [{"event_id": e["event_id"], "point": [e["lat"], e["lon"]],
                                    "water_slugs": ["other-brook-ma"], "reaches": []}], "waters": []}}
    keys, tags, _, _ = SS.placement(entry, {}, {k: r}, lambda r, w: ["test-river-ma"], st["placements"])
    assert keys == [] and "test-river-ma" not in tags


def test_a_stretch_along_a_named_water_with_no_record_the_report_denies_is_not_drawn():
    e = spill("bear", waterbody_text="Did not impact Bear Creek; sewage entered Other Brook")
    k, r = point_reach(e["event_id"])
    r["segments"][0]["gnis_name"] = "Bear Creek"            # no water record for Bear Creek
    st, hist = run([e], {k: r})
    pl = st["placements"][e["event_id"]]
    assert pl["water_slugs"] == [] and "reach" not in pl and k not in st["reaches"]
    assert (st["waters"].get("test-river-ma") or {}).get("status", "grey") == "grey"
    assert pl["point_trace_aside"] == S.POINT_TRACE_NOT_REACHED
    # a stretch along another water is drawn as before
    e2 = spill("bear2", waterbody_text="Did not impact Bear Creek; sewage entered Other Brook")
    k2, r2 = point_reach(e2["event_id"])
    r2["segments"][0]["gnis_name"] = "Bear Brook"
    st, _ = run([e2], {k2: r2})
    assert st["placements"][e2["event_id"]]["reach"] == k2


def test_a_statement_that_it_reached_water_wins_and_only_a_whole_recovery_or_a_water_denial_denies():
    D = S.written_denial
    # reached water: always wins over a recovery or denial phrase
    assert D(spill("a", raw={"description": "Spill reached surface water; fully recovered"})) is None
    assert D(spill("b", raw={"reached_water": True, "description": "All sewage fully recovered"})) is None
    assert D(spill("c", raw={"reached_water": True, "description": "No discharge to waters of the state"})) is None
    # a part, or the solids, recovered: not the whole discharge
    assert D(spill("d", raw={"description": "Recovered 500 of 5,000 gallons; visible solids fully recovered"})) is None
    assert D(spill("e", raw={"description": "Not fully recovered. All visible solids fully recovered."})) is None
    assert D(spill("f", raw={"description": "All visible solids fully recovered"})) is None
    # a denial of something that is not water
    assert D(spill("g", raw={"description": "Spill did not impact the road"})) is None
    assert D(spill("h", raw={"description": "Did not leave the property"})) is None
    assert D(spill("i", raw={"description": "Sewage was contained in the creek"})) is None
    # whole recoveries and water denials still deny
    for t in ("All sewage fully recovered", "No discharge to waters of the state", "Did not reach the storm drain",
              "The spill did not reach any surface water", "Recovered 5,000 of 5,000 gallons; all of it was recovered",
              "Did not impact Bear Creek"):
        assert D(spill("z", raw={"description": t})), t
    st, _ = run([spill("road", raw={"reached_water": True, "description": "Spill did not impact the road"}),
                 spill("sw", raw={"description": "Spill reached surface water; fully recovered"})])
    assert sorted(n["event_id"] for n in st["needs_reach"]) == ["ma-test:road", "ma-test:sw"]


def test_traces_withheld_for_a_missing_state_outline_are_counted_at_any_age():
    old = spill("old", raw={"reached_water": True}, started_at=iso(NOW - 40 * 24 * H), status="ended",
                ended_at=iso(NOW - 40 * 24 * H + H))
    k, r = point_reach(old["event_id"])
    st, _ = run([old], {k: r}, outlines={})
    assert k not in st["reaches"]                            # fail closed, as before
    assert st["counts"]["point_trace"]["outline_missing"] == {"MA": 1}
    assert any("outline" in p and "MA" in p for p in st["problems"])
    assert "outline" in S.point_trace_summary(st["counts"]["point_trace"])
    # with the outline, no such count
    st, _ = run([old], {k: r})
    assert "outline_missing" not in st["counts"]["point_trace"] and k in st["reaches"]
