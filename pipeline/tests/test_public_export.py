"""The public out/ carries no internal keys or wording: out/rules.json without "_" keys, rule records
pointing into rules.json instead of internal source paths, no ArcGIS account names, numeric
constants only. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import DATA_DIR, has_repo_path  # noqa: E402
from export import build as X  # noqa: E402


def test_public_rules_drop_underscore_keys_at_any_depth():
    rules = {"_doc": "internal", "_internal_doc": "x", "version": "v",
             "yellow": {"default_hours": 72, "by_water": {"_example": {"enabled": False}, "real-river-ma": {"hours": 96}},
                        "list": [{"_note": 1, "keep": 2}]}}
    out = X.public_rules(rules)
    assert out == {"version": "v", "yellow": {"default_hours": 72, "by_water": {"real-river-ma": {"hours": 96}},
                                              "list": [{"keep": 2}]}}
    assert rules["yellow"]["by_water"]["_example"] == {"enabled": False}          # the input is not changed


def test_rule_records_point_into_rules_json_and_notice_quotes_stay():
    water = {"yellow_rule": {"rule": "yellow.by_event_type.cso", "hours": 72, "rationale": "owner's principle",
                             "source": "research/science/report.md 2.8", "applied": True},
             "red_rule": {"rule": "red.event", "hours": 24, "rationale": "notice: avoid contact for 24 hours",
                          "source": "https://example.org/notice"},
             "reasons": [{"rule_applied": {"rule": "unresolved.ongoing_red_days", "days": 7,
                                           "rationale": "x", "source": "data/rules.json"}}]}
    out = X.publicize(water)
    assert out["yellow_rule"] == {"rule": "yellow.by_event_type.cso", "hours": 72, "applied": True,
                                  "rules_ref": "yellow.by_event_type.cso"}
    assert out["red_rule"]["rationale"].startswith("notice") and out["red_rule"]["source"].startswith("https://")
    assert out["reasons"][0]["rule_applied"] == {"rule": "unresolved.ongoing_red_days", "days": 7,
                                                 "rules_ref": "unresolved.ongoing_red_days"}
    assert X.internal_wording(out) == []


def test_internal_wording_check_and_scrubs():
    assert X.internal_wording({"a": "see docs/decisions.md", "b": ["Owner's safety principle"],
                               "c": "research/me/report.md", "d": "https://frwa.org/research/bacteria/",
                               "e": "sample data from the fixture set", "f": "ask the coordinator"}) == \
        [".a", ".b[]", ".c", ".e", ".f"]
    assert X.ARCGIS_OWNER.sub("", "US EPA Office of Water (ArcGIS owner skocher_EPA2)") == "US EPA Office of Water"
    c = X.public_constants({"history_days": 90, "confirm_days": 14, "advisory_no_end_days": 7,
                            "unresolved": {"ongoing_red_days": 7, "ongoing_red_rationale": "Owner's ...",
                                           "unresolved_yellow_days": 30, "unknown_status_yellow_days": 14},
                            "reach": {"cap_km": 40, "cap_rationale": "Owner's safety principle"}})
    assert c == {"history_days": 90, "confirm_days": 14, "advisory_no_end_days": 7, "ongoing_red_days": 7,
                 "unresolved_until_day": 30, "unknown_status_yellow_days": 14, "reach_cap_km": 40}


# data/rules.json: the site prints its prose and sources as they are (out/rules.json is the one copy of
# the rule wording), so they are public copy: no owner, project or file references, and the numbers the
# prose states match the numbers beside it.
PROSE_KEY = re.compile(r"^(principle|doc|basis|rationale|source|default_source|\w+_rationale)$")
NOT_PUBLIC = re.compile(r"\bowner\b|\bdecision\b|\bcoordinator\b|\bfixture|\bresearch sample|rules\.json|"
                        r"\.(?:md|py|json|csv)\b|\bsite default\b|\bthis file\b|\bwe were told\b", re.I)


def prose(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and PROSE_KEY.match(k):
                yield f"{path}.{k}", v
            else:
                yield from prose(v, f"{path}.{k}")


def test_rules_prose_is_public_copy():
    rules = X.public_rules(json.loads((DATA_DIR / "rules.json").read_text()))
    texts = dict(prose(rules))
    assert rules.get("version") and len(texts) > 40
    bad = {p: t for p, t in texts.items() if NOT_PUBLIC.search(t) or has_repo_path(t) or X.internal_wording(t)}
    assert not bad, bad
    for p, t in texts.items():
        assert t == t.strip() and "  " not in t and t[-1] not in ",;:", p
    # every rule the site prints has a reason and a public citation
    for st, r in rules["red"]["by_state"].items():
        assert r["basis"] and r["source"], st
    y = rules["yellow"]
    for group in ("by_event_type", "by_water_kind"):
        for k, r in y[group].items():
            assert r["rationale"] and r["source"], (group, k)
    assert y["default_rationale"] and y["default_source"] and y["conditions"]["source"]


def test_rules_prose_states_the_configured_numbers():
    rules = json.loads((DATA_DIR / "rules.json").read_text())
    SITE_HOURS = re.compile(r"\b(?:uses?|period of|counts those) (\d+) hours")

    def check(text, hours, where):              # a period the prose states is the one configured
        said = {int(n) for n in SITE_HOURS.findall(text)}
        assert said <= ({hours} if hours is not None else set()), (where, said, hours)
        return said

    for st, r in rules["red"]["by_state"].items():
        if r["hours"] is not None and st != "VT":            # Vermont's text uses "that period" (48 hours, stated first)
            assert check(r["basis"], r["hours"], f"red.{st}"), st
    assert "48 hours" in rules["red"]["by_state"]["VT"]["basis"] and rules["red"]["by_state"]["VT"]["hours"] == 48
    y = rules["yellow"]
    check(y["default_rationale"], y["default_hours"], "yellow.default")
    for group in ("by_event_type", "by_water_kind"):
        for k, r in y[group].items():
            check(r["rationale"], r["hours"], f"yellow.{group}.{k}")
    u = rules["unresolved"]
    assert {int(n) for n in re.findall(r"(\d+) days", u["ongoing_red_rationale"])} == {u["ongoing_red_days"]}
    assert {int(n) for n in re.findall(r"day (\d+)", u["unresolved_yellow_rationale"])} == {u["ongoing_red_days"], u["unresolved_yellow_days"]}
    assert {int(n) for n in re.findall(r"(\d+) days", u["unknown_status_rationale"])} == {u["unknown_status_yellow_days"]}
    assert re.search(rf"\b{rules['reach']['cap_km']} kilometres", rules["reach"]["cap_rationale"])
    c = y["conditions"]
    assert isinstance(c["cold_water_c"], (int, float)) and isinstance(c["turbid_ntu"], (int, float))


def test_launches_come_with_coordinates_and_their_page(tmp_path, monkeypatch):
    import json
    from build import status as S
    (tmp_path / "test-river-ma.json").write_text(json.dumps({"slug": "test-river-ma", "launches": [
        {"s": "oxbow-ma", "n": "Oxbow", "k": "ramp", "st": "MA", "t": "Easthampton", "x": -72.618302, "y": 42.288418,
         "f": "free", "a": None}, {"n": "no slug"}]}))
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path)
    assert X.launches_for("test-river-ma") == [
        {"slug": "oxbow-ma", "name": "Oxbow", "kind": "ramp", "town": "Easthampton", "state": "MA",
         "water_slug": "test-river-ma", "lat": 42.288418, "lon": -72.618302, "fee": "free", "access": "public",
         "url": "https://openboatlaunch.org/launch/oxbow-ma/"}]
    assert X.launches_for("no-such-water") == []


def test_private_and_commercial_launches_are_shown_unknown_ones_are_not(tmp_path, monkeypatch):
    import json
    from build import status as S
    (tmp_path / "water").mkdir()
    (tmp_path / "build" / "MA").mkdir(parents=True)
    (tmp_path / "water" / "test-bay-ma.json").write_text(json.dumps({"launches": [
        {"s": "town-ramp-ma", "n": "Town Ramp", "k": "ramp", "st": "MA", "t": "Hull", "x": -70.9, "y": 42.3, "f": "fee",
         "a": None},
        {"s": "club-ramp-ma", "n": "Club Ramp", "k": "ramp", "st": "MA", "t": "Hull", "x": -70.91, "y": 42.31,
         "f": None, "a": "r"}]}))
    water = {"slug": "test-bay-ma", "name": "Test Bay", "kind": "bay"}
    rec = lambda slug, access, vis, **kw: {"slug": slug, "name": slug, "kind": "ramp", "access": access, "state": "MA",
                                           "lon": -70.92, "lat": 42.32, "town": "Hull", "visibility": vis,
                                           "water": water, **kw}
    (tmp_path / "build" / "MA" / "launches.json").write_text(json.dumps([
        rec("town-ramp-ma", "public", "published"),
        rec("club-ramp-ma", "public_restricted", "published", operator="Hull Yacht Club"),
        rec("marina-ma", "commercial", "hidden", operator="Hull Marina", website="https://marina.example"),
        rec("private-dock-ma", "private", "hidden"),
        rec("boat-club-ma", "club", "hidden", operator="Hull Boat Club"),
        rec("mystery-ma", "unknown", "held")]))
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "water")
    monkeypatch.setattr(X, "OBL_BUILD_DIR", tmp_path / "build")
    X._OBL_BUILD.clear()
    got = {o["slug"]: o for o in X.launches_for("test-bay-ma", "MA")}
    assert set(got) == {"town-ramp-ma", "club-ramp-ma", "marina-ma", "private-dock-ma", "boat-club-ma"}
    assert got["town-ramp-ma"] == {"slug": "town-ramp-ma", "name": "Town Ramp", "kind": "ramp", "town": "Hull",
                                   "state": "MA", "water_slug": "test-bay-ma", "lat": 42.3, "lon": -70.9, "fee": "fee",
                                   "access": "public", "url": "https://openboatlaunch.org/launch/town-ramp-ma/"}
    assert got["club-ramp-ma"]["access"] == "public_restricted" and got["club-ramp-ma"]["operator"] == "Hull Yacht Club"
    assert got["marina-ma"]["access"] == "commercial" and got["marina-ma"]["url"] is None
    assert got["marina-ma"]["website"] == "https://marina.example"
    assert got["private-dock-ma"]["access"] == "private" and "operator" not in got["private-dock-ma"]
    assert got["boat-club-ma"]["access"] == "club" and got["boat-club-ma"]["operator"] == "Hull Boat Club"
    X._OBL_BUILD.clear()


def test_editorial_launches_are_added_cited_and_yield_to_the_source(tmp_path, monkeypatch):
    import json
    from build import status as S
    (tmp_path / "water").mkdir()
    (tmp_path / "water" / "big-river-ma.json").write_text(json.dumps({"launches": [
        {"s": "town-ramp-ma", "n": "Town Ramp", "k": "ramp", "st": "MA", "t": "Hull", "x": -70.9, "y": 42.3, "f": "fee", "a": None}]}))
    (tmp_path / "launches-extra.json").write_text(json.dumps([
        {"slug": "club-ma", "name": "A Yacht Club", "kind": "ramp", "town": "Longmeadow", "state": "MA", "water_slug": "big-river-ma",
         "lat": 42.0635, "lon": -72.5927, "access": "club", "operator": "A Yacht Club", "website": "https://club.example",
         "source": "OpenStreetMap node 1", "_added": "note"},
        {"slug": "town-ramp-ma", "name": "Duplicate of a source row", "kind": "ramp", "state": "MA", "water_slug": "big-river-ma",
         "lat": 1, "lon": 1, "access": "public"},
        {"slug": "mystery-ma", "name": "No access class", "kind": "ramp", "state": "MA", "water_slug": "big-river-ma",
         "lat": 1, "lon": 1, "access": "unknown"}]))
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "water")
    monkeypatch.setattr(X, "OBL_BUILD_DIR", tmp_path / "no-build")
    monkeypatch.setattr(X, "LAUNCHES_EXTRA", tmp_path / "launches-extra.json")
    X._OBL_BUILD.clear(); X._LAUNCHES_EXTRA = None
    got = X.launches_for("big-river-ma", "MA")
    assert [o["slug"] for o in got] == ["town-ramp-ma", "club-ma"]
    assert got[0]["name"] == "Town Ramp"
    assert got[1] == {"slug": "club-ma", "name": "A Yacht Club", "kind": "ramp", "town": "Longmeadow", "state": "MA",
                      "water_slug": "big-river-ma", "lat": 42.0635, "lon": -72.5927, "fee": None, "access": "club", "url": None,
                      "operator": "A Yacht Club", "website": "https://club.example", "source": "OpenStreetMap node 1"}
    assert X.launches_for("other-ma", "MA") == []
    X._OBL_BUILD.clear(); X._LAUNCHES_EXTRA = None


def test_reach_waters_inverts_the_per_water_reach_list_with_the_own_water_first():
    st = {"reaches": {"MA1-008": {"water_slug": "connecticut-river-ma"}, "CT2-001": {"water_slug": "connecticut-river-ct"}},
          "waters": {"connecticut-river-ct": {"reaches": ["MA1-008", "CT2-001"]},
                     "connecticut-river-ma": {"reaches": ["MA1-008"]},
                     "farmington-river-ct": {"reaches": []}}}
    assert X.reach_waters(st) == {"MA1-008": ["connecticut-river-ma", "connecticut-river-ct"], "CT2-001": ["connecticut-river-ct"]}
    assert X.reach_waters({}) == {}


def test_export_keeps_to_the_live_states():
    """Nothing outside live_states reaches out/ (docs/national-approach.md §8 item 3): registry rows, feeds, operator
    rows and per-state windows of a state built but not yet live stay home; national rows and feeds stay."""
    live = {"MA", "MD"}
    rows = [{"id": "md-x", "states": ["MD"]}, {"id": "ga-x", "states": ["GA"]}, {"id": "fed-echo", "states": []},
            {"id": "mix", "states": ["ga", "ma"]}]
    kept = X.live_registry_rows(rows, live)
    assert [r["id"] for r in kept] == ["md-x", "fed-echo", "mix"]
    feeds = [{"source_id": "md-f", "registry_ids": ["md-x"]}, {"source_id": "ga-f", "registry_ids": ["ga-x"]},
             {"source_id": "orphan", "registry_ids": []}]
    assert [f["source_id"] for f in X.live_feeds(feeds, {r["id"] for r in kept})] == ["md-f", "orphan"]
    dis = [{"id": "md-a", "state": "MD"}, {"id": "ga-a", "state": "GA"}, {"id": "n", "state": None}]
    assert [d["id"] for d in X.live_dischargers(dis, live)] == ["md-a", "n"]
    rules = {"version": "x", "red": {"by_state": {"MD": {"hours": 1}, "GA": {"hours": None}},
                                     "by_discharger": {"pa-alcosan": {"hours": 48}, "md-x": {"hours": 2}}, "none": 1},
             "unresolved": {"day_start_caution": {"sources": ["ga-epd-spills"]}}}
    out = X.live_rules(rules, live)
    assert set(out["red"]["by_state"]) == {"MD"} and set(out["red"]["by_discharger"]) == {"md-x"}
    assert out["red"]["none"] == 1 and out["unresolved"] == rules["unresolved"] and "GA" in rules["red"]["by_state"]
