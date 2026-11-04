"""Discharger ids: the registry (data/dischargers.json) lists, as `aliases`, the other ids the ingesters
stamped on events (research file ids, slugs of a feed's facility names); the export writes every event
with the registry row's id, counts events by it, and scripts/align-discharger-ids.py fills the aliases
in. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import DATA_DIR, ROOT, discharger_alias_map  # noqa: E402
from export import build as X  # noqa: E402

_spec = importlib.util.spec_from_file_location("align_discharger_ids", ROOT / "scripts" / "align-discharger-ids.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def row(rid, name, state, permit=None, aliases=None, **kw):
    return {"id": rid, "name": name, "state": state, "kind": "cso", "npdes_permit": permit,
            "npdes_permits": [permit] if permit else [], "receiving_waters": [], "water_slugs": [], "outfall_count": None,
            "outfalls_source": None, "notification_channel": None, "notification_feed_machine_readable": False,
            "notification_signup_url": None, "towns": [], "notes": "", "verified": "fetched", "checked": "2026-11-01",
            "aliases": [rid] if aliases is None else aliases, "source_areas": [state.lower()], **kw}


def ev(eid, did=None, name=None, permit=None, state=None):
    return {"event_id": eid, "event_type": "sso", "discharger_id": did, "discharger_name": name,
            "npdes_permit": permit, **({"state": state} if state else {}), "raw": {"k": "v"}}


# ---------------------------------------------------------------- the alias map

def test_alias_map_maps_aliases_and_ignores_self_and_contested_ones():
    rows = [row("a-one", "One", "NY", aliases=["a-one", "a-uno", "shared", "a-two"]),
            row("a-two", "Two", "NY", aliases=["a-two", "shared", "a-dos"]),
            row("a-three", "Three", "NY", aliases=[])]
    m = discharger_alias_map(rows)
    # a row's own id is no alias; an alias that is another row's id yields to that row; two claims = no mapping
    assert m == {"a-uno": "a-one", "a-dos": "a-two"}


def test_alias_map_takes_research_ids_of_merged_rows():
    assert discharger_alias_map([{"id": "x-1", "research_ids": ["x-1", "x-2"]}]) == {"x-2": "x-1"}


def test_the_real_registry_has_no_contested_alias_and_no_alias_that_is_a_row_id():
    rows = json.loads((DATA_DIR / "dischargers.json").read_text())
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    claims: dict[str, set] = {}
    for r in rows:
        for a in r.get("aliases") or []:
            if a != r["id"]:
                claims.setdefault(a, set()).add(r["id"])
    assert [a for a, v in claims.items() if len(v) > 1 or a in set(ids)] == []
    assert discharger_alias_map(rows) == {a: next(iter(v)) for a, v in claims.items()}


# ---------------------------------------------------------------- the export

def test_events_with_an_alias_id_are_written_with_the_registry_id_and_nothing_else_changes():
    aliases = {"vt-rutland": "vt-rutland-city"}
    events = [ev("e1", "vt-rutland", "Rutland", "VT0100871"), ev("e2", "vt-rutland-city"), ev("e3", "vt-unknown"), ev("e4")]
    before = json.loads(json.dumps(events))
    out, n = X.canonicalize_events(events, aliases)
    assert n == 1 and events == before                                   # the input is not changed
    assert out[0] == {**before[0], "discharger_id": "vt-rutland-city", "discharger_id_source": "vt-rutland"}
    assert out[1:] == before[1:] and all("discharger_id_source" not in e for e in out[1:])


def test_the_status_records_and_the_rain_block_get_the_registry_id_at_any_depth():
    aliases = {"nh-exeter-wwtp-bypass": "nh-exeter-wwtp"}
    st = {"rain_likely": {"permits": {"NH1": {"discharger_id": "nh-exeter-wwtp-bypass", "name": "x"}},
                          "episodes": {"r:1": {"discharger_id": "nh-exeter-wwtp-bypass",
                                               "rain": {"discharger_id": "nh-exeter-wwtp-bypass"}}}},
          "waters": {"w": {"reasons": [{"rain": {"discharger_id": "nh-exeter-wwtp-bypass"}},
                                       {"rain": {"discharger_id": "other"}}]}}}
    assert X.rewrite_discharger_ids(st, aliases) == 4
    assert st["rain_likely"]["permits"]["NH1"] == {"discharger_id": "nh-exeter-wwtp", "name": "x"}
    assert st["rain_likely"]["episodes"]["r:1"]["rain"]["discharger_id"] == "nh-exeter-wwtp"
    assert st["waters"]["w"]["reasons"][1]["rain"]["discharger_id"] == "other"
    assert X.rewrite_discharger_ids(st, aliases) == 0


def test_event_counts_follow_the_canonical_id_then_the_permit_and_count_an_event_once():
    dis = [row("vt-rutland-city", "City of Rutland", "VT", "VT0100871"), row("vt-other", "Other", "VT", "VT0100001"),
           row("ny-kenmore-poss", "Kenmore", "NY")]
    aliases = discharger_alias_map([{**dis[0], "aliases": ["vt-rutland-city", "vt-rutland"]}, *dis[1:]])
    events, _ = X.canonicalize_events([
        ev("a", "vt-rutland", permit="VT0100871"),            # alias id and permit: one row, once
        ev("b", None, permit="VT0100871"),                    # no id: by permit
        ev("c", "vt-nowhere", permit="VT0100001"),            # an id with no row: by permit
        ev("d", "ny-kenmore-poss"),                           # a row id, no permit: counted (the permit-only count missed it)
        ev("e", "vt-nowhere"),                                # nothing to go by
        ev("f", "vt-other", permit="VT0100871"),              # the id wins over the permit
    ], aliases)
    got = X.events_by_discharger(dis, events)
    assert {k: [e["event_id"] for e in v] for k, v in got.items()} == {
        "vt-rutland-city": ["a", "b"], "vt-other": ["c", "f"], "ny-kenmore-poss": ["d"]}


# ---------------------------------------------------------------- scripts/align-discharger-ids.py

def research(rid, name, state, permit=None, area="vt", file=None, **kw):
    r = {"id": rid, "name": name, "state": state, "kind": "cso", "npdes_permit": permit, "receiving_waters": ["Otter Creek"],
         "water_slugs": ["otter-creek-vt"], "outfall_count": 4, "outfalls_source": None, "notification_channel": "a notice",
         "notification_feed_machine_readable": False, "towns": ["Rutland"], "notes": "note", "verified": "fetched",
         "checked": "2026-11-01", **kw}
    return {"row": r, "file": file or f"research/{area}/dischargers.json", "area": area}


REGISTRY = [row("vt-rutland-city", "City of Rutland WWTF combined sewer system", "VT", "VT0100871"),
            row("vt-burlington-dpw-main", "Burlington DPW Main WWTF", "VT", "VT0100153"),
            row("ma-west-springfield-dpw", "West Springfield Department of Public Works", "MA"),
            row("ny-west-springfield", "West Springfield Department of Public Works", "NY"),
            row("ct-groton-town-wpca", "Town of Groton WPCA", "CT", "CT0100001"),
            row("ct-groton-utilities", "Town of Groton WPCA", "CT", "CT0100002")]


def run(events, registry=REGISTRY, res=None):
    return A.align(events, json.loads(json.dumps(registry)), res or {}, today="2026-11-02")


def test_an_id_is_aliased_by_the_events_permit_even_when_the_names_differ():
    plan = run([ev("1", "vt-rutland", "Rutland", "VT0100871"), ev("2", "vt-rutland", "Rutland", "VT0100871")])
    assert [(a["orphan"], a["row"], a["events"]) for a in plan["aliased"]] == [("vt-rutland", "vt-rutland-city", 2)]
    assert plan["created"] == plan["ambiguous"] == plan["unmatched"] == []


def test_the_research_row_is_tried_first_by_permit_then_exact_name_then_normalised_name():
    by_permit = {"vt-x": research("vt-x", "Some other name", "VT", "VT0100153")}
    exact = {"vt-x": research("vt-x", "Burlington DPW Main WWTF", "VT")}
    loose = {"vt-x": research("vt-x", "burlington dpw - MAIN wwtf.", "VT")}
    for res, how in ((by_permit, "permit"), (exact, "name"), (loose, "normalised name")):
        plan = run([ev("1", "vt-x")], res=res)
        assert plan["aliased"][0]["row"] == "vt-burlington-dpw-main" and plan["aliased"][0]["via"].endswith(how)


def test_an_id_falls_back_to_the_events_when_the_research_row_matches_nothing():
    res = {"ma-x": research("ma-x", "Nothing like it", "MA", "MA0000001")}
    plan = run([ev("1", "ma-x", "West Springfield Department of Public Works", state="MA")], res=res)
    assert plan["aliased"][0]["row"] == "ma-west-springfield-dpw" and plan["aliased"][0]["via"].startswith("events")


def test_matching_stays_within_the_state():
    # the same name is a row in MA and in NY: the id's state decides, so each finds its own row
    name = "West Springfield Department of Public Works"
    plan = run([ev("1", "ma-west-springfield-department-of-public-works", name.upper()),
                ev("2", "ny-west-springfield-department-of-public-works", name.upper())])
    assert {a["orphan"]: a["row"] for a in plan["aliased"]} == {
        "ma-west-springfield-department-of-public-works": "ma-west-springfield-dpw",
        "ny-west-springfield-department-of-public-works": "ny-west-springfield"}
    # a state with no such row finds none
    assert run([ev("1", "vt-west-springfield", name)])["aliased"] == []


def test_a_name_that_belongs_to_another_permittee_is_no_match():
    plan = run([ev("1", "vt-burlington-x", "Burlington DPW Main WWTF", "VT0999999")])
    assert plan["aliased"] == [] and len(plan["unmatched"]) == 1


def test_more_than_one_matching_row_is_ambiguous_and_nothing_is_decided():
    plan = run([ev("1", "ct-groton-city-of", "Town of Groton WPCA", state="CT")])
    assert plan["aliased"] == [] and plan["created"] == []
    (a,) = plan["ambiguous"]
    assert a["orphan"] == "ct-groton-city-of" and a["events"] == 1
    assert sorted(c[0] for c in a["candidates"]) == ["ct-groton-town-wpca", "ct-groton-utilities"]
    assert "Town of Groton WPCA" in A.review_text(plan, "2026-11-02") and "ct-groton-utilities" in A.review_text(plan, "2026-11-02")


def test_no_match_with_a_research_row_creates_a_registry_row_in_the_shape_of_the_others():
    res = {"vt-new-town": research("vt-new-town", "Town of New Town WWTF (VT0100999; bypass)", "VT", "VT0100999")}
    plan = run([ev("1", "vt-new-town", "New Town", "VT0100999"), ev("2", "vt-new-town", "New Town", "VT0100999")], res=res)
    assert plan["aliased"] == [] and plan["ambiguous"] == []
    (c,) = plan["created"]
    new = c["row"]
    assert c["events"] == 2 and new["id"] == "vt-new-town" and new["verified"] is False
    assert new["npdes_permit"] == "VT0100999" and new["npdes_permits"] == ["VT0100999"] and new["aliases"] == []
    assert new["source_areas"] == ["vt"] and "research/vt/dischargers.json" in new["notes"] and new["notes"].startswith("note")
    assert new["receiving_waters"] == ["Otter Creek"] and new["towns"] == ["Rutland"]
    assert list(new) == list(REGISTRY[0])                                   # same keys, same order as the other rows


def test_an_id_with_no_research_row_and_no_match_is_listed_for_review_not_invented():
    plan = run([ev("1", "ct-west-haven", "WEST HAVEN"), ev("2", "ct-west-haven", "West Haven")])
    assert plan["created"] == [] and [(u["orphan"], u["events"], u["names"]) for u in plan["unmatched"]] == [
        ("ct-west-haven", 2, ["WEST HAVEN", "West Haven"])]
    # a similar row is a hint, never a match
    hint = run([ev("1", "ct-groton-city-of", "GROTON, CITY OF", state="CT")])["unmatched"][0]
    assert hint["hints"] == ["ct-groton-town-wpca", "ct-groton-utilities"]


def test_ids_already_in_the_registry_as_an_id_or_an_alias_are_left_alone():
    reg = [row("vt-rutland-city", "City of Rutland", "VT", "VT0100871", aliases=["vt-rutland-city", "vt-rutland"])]
    plan = run([ev("1", "vt-rutland-city"), ev("2", "vt-rutland"), ev("3"), ev("4", None, "x")], reg)
    assert [plan[k] for k in A.CATEGORIES] == [[], [], [], []] and plan["already"] == 1


def test_apply_adds_aliases_keeps_order_and_old_aliases_drops_self_aliases_and_appends_new_rows():
    reg = [row("vt-rutland-city", "City of Rutland", "VT", "VT0100871"),
           row("vt-other", "Other", "VT", "VT0100001", aliases=["vt-other", "vt-old-id"]),
           row("vt-third", "Third", "VT", "VT0100002")]
    res = {"vt-new-town": research("vt-new-town", "New Town", "VT", "VT0100999")}
    plan = A.align([ev("1", "vt-rutland", permit="VT0100871"), ev("2", "vt-other-b", permit="VT0100001"),
                    ev("3", "vt-other-c", permit="VT0100001"), ev("4", "vt-new-town")], reg, res, "2026-11-02")
    out = A.apply(plan, reg)
    assert [r["id"] for r in out] == ["vt-rutland-city", "vt-other", "vt-third", "vt-new-town"]
    assert out[0]["aliases"] == ["vt-rutland"]
    assert out[1]["aliases"] == ["vt-old-id", "vt-other-b", "vt-other-c"]
    assert out[2] == reg[2]                                              # untouched rows are unchanged, self-alias and all
    assert reg[0]["aliases"] == ["vt-rutland-city"]                      # the input is not changed
    # a second pass over the result has nothing left to do
    again = A.align([ev("1", "vt-rutland", permit="VT0100871"), ev("2", "vt-other-b"), ev("4", "vt-new-town")], out, res)
    assert [again[k] for k in A.CATEGORIES] == [[], [], [], []]


def test_the_registry_file_format_round_trips():
    text = (DATA_DIR / "dischargers.json").read_text()
    assert A.dump(json.loads(text)) == text
    assert text.endswith("]\n") and not text.endswith("\n\n")


def test_summary_counts_ids_and_events():
    plan = run([ev("1", "vt-rutland", "Rutland", "VT0100871"), ev("2", "ct-west-haven", "WEST HAVEN")])
    lines = A.summary(plan).splitlines()
    assert lines[2].split() == ["aliased", "1", "1"] and lines[5].split() == ["unmatched", "1", "1"]
    assert lines[-1].split() == ["total", "2", "2"]
