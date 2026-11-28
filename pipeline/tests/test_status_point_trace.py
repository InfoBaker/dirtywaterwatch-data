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


def run(records, reaches=None):
    w = world(tmp_events(records))
    w["reaches"] = dict(reaches or {})
    st, hist = S.build(now=NOW, write=False, **w)
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
    st, _ = run([old])
    assert st["needs_reach"] == [] and st["counts"]["point_trace"] == {"traced": {}, "queued": {}, "aside": {}}


def test_month_precision_and_advisories_are_unaffected():
    month = spill("m", time_precision="month", event_type="cso")
    adv = spill("adv", event_type="beach_advisory", status="advisory_active")
    st, _ = run([month, adv])
    assert st["needs_reach"] == []
    assert st["counts"]["point_trace"] == {"traced": {}, "queued": {}, "aside": {}}
