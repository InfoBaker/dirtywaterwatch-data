"""The water tile's wording for reports arriving from upstream (build/charts.py stretch_words; owner, 2026-11-03: the
Dog River tile read "0 reported in Vermont, 11 arriving from upstream outfalls in Vermont"). Synthetic operators only.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import charts as C  # noqa: E402


def test_same_state_outfalls_are_named_by_water_and_operator_and_the_state_is_not_on_both_sides():
    w = C.stretch_words("Dog River", "VT", "Vermont", [("VT", "Winooski River", "Montpelier")])
    assert w["local_where"] == "on the Dog River" and w["local_label"] == "Reported on the Dog River"
    assert w["arriving"] == "outfalls upstream on the Winooski River, Montpelier"
    assert w["arriving_label"] == "Arriving from outfalls upstream on the Winooski River, Montpelier, estimated"
    assert "Vermont" not in str(w)
    many = C.stretch_words("Dog River", "VT", "Vermont", [("VT", f"Brook {i}", f"Town {i}") for i in range(5)])
    assert many["arriving"] == ("outfalls upstream on the Brook 0, Town 0; the Brook 1, Town 1; the Brook 2, Town 2; "
                                "and 2 more")


def test_another_states_outfalls_keep_the_state_and_name_the_water_and_operator():
    w = C.stretch_words("Connecticut River", "MA", "Massachusetts",
                        [("NH", "Ashuelot River", "Keene"), ("VT", "Connecticut River", "Brattleboro")])
    assert w["local_where"] == "in Massachusetts" and w["local_label"] == "Reported on the Connecticut River in Massachusetts"
    assert w["arriving"] == ("upstream outfalls in New Hampshire: the Ashuelot River, Keene; "
                             "upstream outfalls in Vermont: the Connecticut River, Brattleboro")
    mixed = C.stretch_words("Dog River", "VT", "Vermont", [("VT", "Winooski River", "Montpelier"), ("NH", None, "Keene")])
    assert mixed["local_where"] == "on the Dog River"
    assert mixed["arriving"] == "outfalls upstream on the Winooski River, Montpelier; upstream outfalls in New Hampshire: Keene"
    assert mixed["arriving"].count("Vermont") == 0


def test_operator_short_names():
    assert C.short_operator("City of Montpelier Water Resource Recovery Facility combined sewer system") == "Montpelier"
    assert C.short_operator("Town of Brattleboro WWTF and collection system") == "Brattleboro"
    assert C.short_operator("Burlington East ('Burlington River') WWTF, Riverside Ave CSO") == "Burlington East"
    assert C.short_operator(None) is None


def test_the_water_tile_headline_and_strip_caption_use_the_new_wording():
    b = C.Bucket("water", "dog-river-vt")
    b.state = "VT"
    from datetime import UTC, datetime
    for i in range(11):
        eid = f"vt-dec:{i}"
        b.events.append({"event_id": eid, "started_at": "2026-10-01T10:00:00-04:00"})
        b.via[eid] = "arriving"
        b.from_state[eid] = "VT"
        b.from_where[eid] = ("Winooski River", "Montpelier")
    months = [f"2025-{m:02d}" for m in range(11, 13)] + [f"2026-{m:02d}" for m in range(1, 11)]
    vals = [0] * 11 + [11]
    doc = {"name": "Dog River", "state_name": "Vermont", "charts": {"events_by_month": {
        "series": [{"values": vals}], "split": {"local": [0] * 12, "arriving": vals}}}}
    data = types.SimpleNamespace(history={}, status={}, waters={"dog-river-vt": {"kind": "river"}}, by_id={}, dropped={},
                                 effective={})
    out = C.headline(b, data, doc, months, [], [])
    t = out["tiles"][0]
    assert t["headline"] == ("11 affecting this stretch: 0 reported on the Dog River; "
                             "11 arriving from outfalls upstream on the Winooski River, Montpelier")
    assert out["split_labels"] == {"local": "Reported on the Dog River",
                                   "arriving": "Arriving from outfalls upstream on the Winooski River, Montpelier, estimated"}
    assert t["parts"][1]["label"] == out["split_labels"]["arriving"] and datetime.now(UTC)


# ---- review 2026-11-03 (docs/reviews/2026-11-03-wording-scan.md H1, H2, H4, H5): synthetic waters and operators only

MONTHS = [f"2025-{m:02d}" for m in range(11, 13)] + [f"2026-{m:02d}" for m in range(1, 11)]


def _tile_doc(name, st_name, kind, state, local, arriving, groups=(), hours=None, slug="test-water"):
    """(bucket, data, doc) for a water with `local` + `arriving` discharges in the last month; `groups` the
    (origin state, water, operator) of each arriving one; `hours` the advisory_hours_by_month chart, if any."""
    b = C.Bucket("water", slug)
    b.state = state
    for i in range(arriving):
        eid = f"src:a{i}"
        b.events.append({"event_id": eid, "started_at": "2026-10-01T10:00:00-04:00"})
        b.via[eid] = "arriving"
        b.from_state[eid], b.from_where[eid] = groups[i % len(groups)][0], groups[i % len(groups)][1:]
    z = [0] * 11
    charts = {"events_by_month": {"series": [{"values": z + [local + arriving]}],
                                  "split": {"local": z + [local], "arriving": z + [arriving]}}}
    if hours is not None:
        charts["advisory_hours_by_month"] = hours
    doc = {"name": name, "state_name": st_name, "charts": charts}
    data = types.SimpleNamespace(history={}, status={}, waters={slug: {"kind": kind, "state": state, "name": name}},
                                 by_id={}, dropped={}, effective={})
    return b, data, doc


def _hours(total, local, arriving, advisory_only):
    z = [0] * 11
    return {"series": [{"values": z + [total]}],
            "parts": {"discharge_window": z + [local], "official_advisory_only": z + [advisory_only],
                      "local_events": z + [local], "arriving_events": z + [arriving]}}


def test_the_same_water_is_not_named_bare_on_both_sides_of_the_headline():
    # buffalo-river-ny: the arriving outfall is on another record of the same name (the operator is Buffalo)
    w = C.stretch_words("Buffalo River", "NY", "New York", [("NY", "Buffalo River", "Buffalo")])
    assert w["arriving"] == "outfalls further up the Buffalo River (Buffalo)"
    assert w["local_where"] == "on the Buffalo River" and w["local_label"] == "Reported on the Buffalo River"
    assert "the Buffalo River, Buffalo" not in w["arriving"] and w["arriving_label"].startswith("Arriving from outfalls further up")
    b, data, doc = _tile_doc("Buffalo River", "New York", "river", "NY", 50, 1, [("NY", "Buffalo River", "Buffalo")],
                             slug="buffalo-river-ny")
    t = C.headline(b, data, doc, MONTHS, [], [])["tiles"][0]
    assert t["headline"] == ("51 affecting this stretch: 50 reported on the Buffalo River; "
                             "1 arriving from outfalls further up the Buffalo River (Buffalo)")
    # case and spacing do not hide it; two operators; mixed with another water of the state and one of another state
    mixed = C.stretch_words("Raquette River", "NY", "New York", [
        ("NY", "RAQUETTE  RIVER", "Potsdam"), ("NY", "RAQUETTE  RIVER", "Massena"), ("NY", "St. Regis River", "Brasher Falls"),
        ("VT", "Raquette River", "Burlington")])
    assert mixed["arriving"] == ("outfalls upstream on the St. Regis River, Brasher Falls; "
                                 "outfalls further up the Raquette River (Potsdam; Massena); "
                                 "upstream outfalls in Vermont: the Raquette River, Burlington")
    assert C.stretch_words("Seekonk River", "RI", "Rhode Island", [("RI", "Seekonk River", None)])["arriving"] == \
        "outfalls further up the Seekonk River"
    # a water of another state with this name keeps naming the state (the sides already differ)
    other = C.stretch_words("Connecticut River", "MA", "Massachusetts", [("VT", "Connecticut River", "Brattleboro")])
    assert other["local_where"] == "in Massachusetts" and "further up" not in other["arriving"]


def test_no_article_before_a_lake_or_pond_name():
    for name in ("Lake Anna", "Alley Pond", "Alcyon Lake", "The Reservoir", "LAKE ERIE", "Lake of the Woods"):
        assert C.the_name(name) == name and "the Lake" not in C.the_name(name) and "the The" not in C.the_name(name)
    for name in ("Winooski River", "Meredith Branch", "Chesapeake and Delaware Canal", "Boston Harbor", "Casco Bay",
                 "Long Island Sound", "Quabbin Reservoir", "Mill Channel", "Pond Brook"):
        assert C.the_name(name) == f"the {name}"
    b, data, doc = _tile_doc("Lake Anna", "Virginia", "lake", "VA", 4, 0, slug="lake-anna-va")
    out = C.headline(b, data, doc, MONTHS, [], [])
    assert out["tiles"][0]["label"] == "Discharges affecting Lake Anna in Virginia, last 12 months"
    assert out["split_labels"]["local"] == "Reported on Lake Anna in Virginia"
    w = C.stretch_words("Alley Pond", "NY", "New York", [("NY", "Alcyon Lake", "Queens")])
    assert w["local_where"] == "on Alley Pond" and w["local_label"] == "Reported on Alley Pond"
    assert w["arriving"] == "outfalls upstream on Alcyon Lake, Queens"
    assert C.stretch_words("The Reservoir", "RI", "Rhode Island", [])["local_label"] == "Reported on The Reservoir in Rhode Island"


def test_a_lake_is_this_lake_and_a_pond_this_pond_never_a_stretch():
    for kind, name, want in (("river", "Dog River", "this stretch"), ("stream", "Dog Brook", "this stretch"),
                             ("canal", "Erie Canal", "this stretch"), ("lake", "Lake Anna", "this lake"),
                             ("pond", "Alley Pond", "this pond"), ("reservoir", "Quabbin Reservoir", "this water"),
                             ("bay", "Casco Bay", "this water"), (None, "Dog River", "this water")):
        assert C.this_water(kind) == want
        b, data, doc = _tile_doc(name, "Vermont", kind, "VT", 3, 2, [("VT", "Winooski River", "Montpelier")])
        out = C.headline(b, data, doc, MONTHS, [], [])
        assert out["tiles"][0]["headline"].startswith(f"5 affecting {want}: 3 reported on "), out["tiles"][0]["headline"]
        if kind in ("lake", "pond", "reservoir", "bay"):
            assert "stretch" not in str(out), (kind, out)
    # the note on a same-named record elsewhere: a lake has no upstream
    b, data, doc = _tile_doc("Lake Anna", "Virginia", "lake", "VA", 1, 0, slug="lake-anna-va")
    data.waters["lake-anna-nc"] = {"kind": "lake", "state": "NC", "name": "Lake Anna"}
    note = C.headline(b, data, doc, MONTHS, [], [])["tiles_note"]
    assert note == "This record covers Lake Anna within Virginia; the same lake in another state is a separate record."
    b, data, doc = _tile_doc("Dog River", "Vermont", "river", "VT", 1, 0, slug="dog-river-vt")
    data.waters["dog-river-nh"] = {"kind": "river", "state": "NH", "name": "Dog River"}
    assert C.headline(b, data, doc, MONTHS, [], [])["tiles_note"] == (
        "This record covers the Dog River within Vermont; the same river upstream is a separate record.")


def _hours_tile(hours):
    b, data, doc = _tile_doc("Alcyon Lake", "New Jersey", "lake", "NJ", 0, 0, hours=hours, slug="alcyon-lake-nj")
    return next(t for t in C.headline(b, data, doc, MONTHS, [], [])["tiles"] if t["key"] == "status_hours_12m")


def test_hours_tile_parts_account_for_the_value():
    # alcyon-lake-nj: 548 hours, all under an official advisory; reported 0 and arriving 0 left the parts 548 short
    t = _hours_tile(_hours(548, 0, 0, 548))
    assert t["value"] == 548
    assert [(p["key"], p["value"]) for p in t["parts"]] == [("local", 0), ("arriving", 0), ("official_advisories", 548)]
    assert t["parts"][2]["label"] == "Official advisories (beach, algal bloom)"
    assert sum(p["value"] for p in t["parts"]) == t["value"] and t["parts_additive"] is True
    # discharge hours short of the total by the advisory hours: 120 = 70 reported + 20 arriving + 30 advisory
    t = _hours_tile(_hours(120, 70, 20, 30))
    assert sum(p["value"] for p in t["parts"]) == t["value"] == 120 and t["parts_additive"] is True
    # no advisory hours: two parts as before, a third only above zero
    t = _hours_tile(_hours(90, 70, 20, 0))
    assert [p["key"] for p in t["parts"]] == ["local", "arriving"] and sum(p["value"] for p in t["parts"]) == 90
    # reported and arriving hours that overlap are counted once in the total: parts exceed it, and say so
    t = _hours_tile(_hours(100, 80, 60, 0))
    assert sum(p["value"] for p in t["parts"]) > t["value"] and t["parts_additive"] is False
    t = _hours_tile(_hours(100, 80, 60, 10))
    assert t["parts"][-1]["key"] == "official_advisories" and t["parts_additive"] is False
