"""Florida DEP PNP: the notice's text against its form's flag (owner, 2026-11-04, afternoon item 2). A notice whose form
says "Waterbodies Impacted: N" while its text says the sewage entered, may have entered, reached, discharged to or
flowed into a named water is placed on that water under the site's caution (never red), and the record says the
form's flag said otherwise. Placeholder names only; no network.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from build import status as S  # noqa: E402
from ingest import fl_dep_pnp as P  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fl_dep_pnp_layer.json"


def _row(text, n=202611900, **kw):
    a = dict(json.loads(FIXTURE.read_text())["features"][0]["attributes"])
    a.update(INCIDENT_NUMBER=n, OBJECTID=n % 1000, INCIDENT_REPORT=text, **kw)
    return a


def template(description, flag="N"):
    return (f"Incident Description: {description} Wastewater Type: Untreated Cause: Blockage Spill Volume: 300 "
            f"Volume Recovered: 0 Waterbodies Impacted: {flag} Clean-up Status: Complete Clean-up Actions: Area washed down.")


def record(description, flag="N"):
    recs, _ = P.build([_row(template(description, flag))], "2026-11-04T00:00:00Z", [], permits={})
    assert len(recs) == 1
    return recs[0]


# ---------------------------------------------------------------- the shapes that flip the flag

@pytest.mark.parametrize("description,water", [
    ("A manhole overflowed and sewage entered Example Creek.", "Example Creek"),
    ("Sewage entered into the Sample Bayou behind the lift station.", "Sample Bayou"),
    ("Sewage was observed entering Placeholder Canal.", "Placeholder Canal"),
    ("The overflow may have entered Example Bayou.", "Example Bayou"),
    ("Some of the spill might have reached the Sample River.", "Sample River"),
    ("Sewage possibly entered Lake Placeholder.", "Lake Placeholder"),
    ("The spill reached Example Branch before the crew arrived.", "Example Branch"),
    ("The force main break discharged into Sample Creek.", "Sample Creek"),
    ("Sewage discharged to the Placeholder River.", "Placeholder River"),
    ("Sewage flowed into Example Lake from the yard.", "Example Lake"),
    ("Sewage flowed to the Sample Bayou.", "Sample Bayou"),
    ("Sewage went down the storm drain into Example Creek.", "Example Creek"),
    ("The storm drain discharges into the St. Example River.", "St. Example River"),
    ("Sewage overflowed from the manhole, and impacted Placeholder Bay.", "Placeholder Bay"),
])
def test_text_naming_a_water_reached_wins_over_the_forms_n(description, water):
    r = record(description)
    raw = r["raw"]
    assert raw["reached_water"] == "text" and r["waterbody_text"] == water
    assert raw["_reached_water_basis"] == ("the notice's description names this water; its form answered "
                                           "\"Waterbodies Impacted: N\"")
    assert raw["_form_waterbodies_impacted"] == "N" and raw["_template"]["waterbodies_impacted"] == "N"
    assert raw["_reached_water_words"] and water.split()[-1] in raw["_reached_water_words"]
    assert S.no_water_flag(r) is None and S.reached_no_water(r) is None      # the shared no-water reading lets it through


# ---------------------------------------------------------------- the negations that must not flip it

@pytest.mark.parametrize("description", [
    "Sewage did not enter Example Creek.",
    "The sewage did not flow into Example Creek.",
    "No discharge to Sample Bayou occurred.",
    "No sewage entered Placeholder Canal.",
    "None of the spill entered Example Lake.",
    "The spill was contained before reaching Sample River.",
    "Crews contained the overflow before it reached Example Bayou.",
    "Sandbags prevented sewage from entering Placeholder Creek.",
    "Sewage never reached Example Bay.",
    "The overflow didn't flow into Sample Creek.",
    "The spill was kept from flowing into Example Canal.",
    "Sewage pooled near Example Creek but did not flow into it.",
    "Sewage flowed into the storm drain on Example Rd.",        # a storm drain is not a water
    "Sewage flowed into the retention pond.",                   # a retention pond is not a receiving water
    "Sewage flowed into a nearby creek.",                       # no water named
])
def test_negations_and_unnamed_waters_keep_the_forms_n(description):
    r = record(description)
    raw = r["raw"]
    assert raw["reached_water"] is False
    assert "_reached_water_basis" not in raw and "_form_waterbodies_impacted" not in raw
    assert S.no_water_flag(r) == "the report says the discharge did not reach a water"


def test_a_negation_in_another_part_of_the_sentence_does_not_cancel_the_reach():
    # "not" governs the pump, not the water; an unsure "not known whether" is the reason for the rule
    for d, water in (("The pump was not working, and sewage flowed into Example Creek.", "Example Creek"),
                     ("It is not known whether sewage entered Sample Bayou.", "Sample Bayou"),
                     ("No alarm sounded. Sewage reached Placeholder Canal.", "Placeholder Canal")):
        r = record(d)
        assert r["raw"]["reached_water"] == "text" and r["waterbody_text"] == water, d


def test_a_forms_y_or_no_flag_is_unchanged():
    y = record("Sewage entered Example Creek.", flag="Y")
    assert y["raw"]["reached_water"] is True and "_reached_water_basis" not in y["raw"]
    recs, _ = P.build([_row("Raw sewage overflowed from a manhole and flowed into Example Creek.", n=202611901)],
                      "2026-11-04T00:00:00Z", [], permits={})
    assert "reached_water" not in recs[0]["raw"] and recs[0]["waterbody_text"] == "Example Creek"


def test_the_text_water_is_the_one_the_reach_names_and_rebuilds_keep_it():
    r = record("Sewage flowed toward Sample River. The overflow entered Example Creek.")
    assert r["waterbody_text"] == "Example Creek" and r["raw"]["_water_names"][0] == "Example Creek"
    again = P.rebuilt(json.loads(json.dumps(r)), {})
    assert again["raw"]["reached_water"] == "text" and again["waterbody_text"] == "Example Creek"


def test_the_name_scrubs_are_unchanged_by_the_rule():
    r = record("Jordan Sample received call; sewage entered Example Creek. Contact Jane Doe at 850-555-0100.")
    text = json.dumps(r)
    assert r["raw"]["reached_water"] == "text"
    assert "Jordan" not in text and "Jane Doe" not in text and "555-0100" not in text


# ---------------------------------------------------------------- the status build: the site's caution, never red

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _ev(status, ended_at=None, reached="text"):
    raw = {"reached_water": reached}
    if reached == "text":
        raw["_reached_water_basis"] = P.TEXT_REACHED_BASIS
    return {"event_id": "fl-dep-pnp:x", "source_id": "fl-dep-pnp", "event_type": "sso", "status": status,
            "started_at": "2026-11-09T00:00:00-05:00", "ended_at": ended_at, "time_precision": "day",
            "reported_at": "2026-11-09T10:00:00-05:00", "discharger_name": "Example Utility",
            "source_url": "https://example.org/notice", "raw": raw}


def test_an_ongoing_text_placed_notice_is_caution_not_red():
    ivs = S.event_intervals(_ev("ongoing"), "FL", NOW)
    assert ivs and not any(iv["color"] == "red" for iv in ivs)
    first = ivs[0]
    assert first["rule"] == "text_caution" and first["color"] == "yellow"
    assert first["rule_applied"]["replaces"] == "ongoing" and "never red" in first["rule_applied"]["rationale"]
    assert S.short_reason(first, _ev("ongoing")).endswith(
        "water named in the notice's text; its form said no water was reached")
    plain = S.event_intervals(_ev("ongoing", reached=True), "FL", NOW)
    assert plain[0]["color"] == "red" and plain[0]["rule"] == "ongoing"           # the flag's Y: unchanged


def test_an_ended_text_placed_notice_keeps_the_sites_caution_after_the_end():
    e = _ev("ended", "2026-11-09T00:00:00-05:00")
    ivs = S.event_intervals(e, "FL", NOW)
    assert [iv["rule"] for iv in ivs] == ["text_caution", "caution"]
    assert all(iv["color"] == "yellow" and iv["text_over_flag"] for iv in ivs)


def test_the_placement_note_says_the_water_comes_from_the_text():
    from shapely.geometry import shape
    geom = {"type": "LineString", "coordinates": [[-82.0, 28.0], [-81.99, 28.0]]}
    waters = {"example-creek-fl": {"slug": "example-creek-fl", "name": "Example Creek", "kind": "stream", "state": "FL",
                                   "towns": [], "bbox": list(shape(geom).bounds), "geometry": geom}}
    saved = S._STATES
    S._STATES = {"FL"}
    try:
        r = S.Resolver(waters, [], {}, {}, {})
        e = {**_ev("ended", "2026-11-09T00:00:00-05:00"), "waterbody_text": "Example Creek", "lat": 28.0005,
             "lon": -81.995, "water_slugs": []}
        pl = r.resolve(e)
        assert pl["water_slugs"] == ["example-creek-fl"] and not pl.get("no_receiving_water")
        assert pl["note"].startswith(P.TEXT_REACHED_BASIS) and pl["text_over_flag"] == P.TEXT_REACHED_BASIS
        # with the notice's words on the record, the note quotes them (cite everything), in public words
        worded = {**e, "raw": {**e["raw"], "_reached_water_words": "may have entered the nearby Example Creek"}}
        note = r.resolve(worded)["note"]
        assert note.startswith('the notice\'s description says "may have entered the nearby Example Creek"; its form '
                               'answered "Waterbodies Impacted: N"'), note
        assert "flag" not in note
        flagged = {**e, "raw": {"reached_water": False}}
        assert r.resolve(flagged).get("no_receiving_water")              # the form's N alone: no water, as before
    finally:
        S._STATES = saved
        S._GEOM_CACHE.clear()


def test_a_ditch_named_after_a_water_and_a_plants_own_outflow_are_not_a_reach():
    for d in ("Raw wastewater entered Example Lake drainage ditch area.",
              "The manhole overflowed near a grate. At the time we were discharging to Sample Creek via our treatment "
              "system."):
        assert record(d)["raw"]["reached_water"] is False, d


def test_the_water_status_reason_carries_the_basis(tmp_path):
    # the whole status build: a text-placed notice on a Florida water gives a yellow reason that names the basis
    geom = {"type": "Polygon", "coordinates": [[[-82.0, 28.0], [-81.99, 28.0], [-81.99, 28.01], [-82.0, 28.0]]]}
    waters = {"example-lake-fl": {"slug": "example-lake-fl", "name": "Example Lake", "kind": "lake", "state": "FL",
                                  "area_km2": 0.5, "bbox": [-82.0, 28.0, -81.99, 28.01], "geometry": geom}}
    now = datetime(2026, 11, 9, 18, 0, tzinfo=UTC)
    e = {**_ev("ongoing"), "fetched_at": "2026-11-09T16:00:00Z", "waterbody_text": "Example Lake",
         "water_slugs": [], "water_match": "none", "lat": 28.002, "lon": -81.998}
    (tmp_path / "fl-dep-pnp.json").write_text(json.dumps({"source_id": "fl-dep-pnp", "ok": True,
                                                          "last_ok_at": "2026-11-09T16:00:00Z", "meta": {},
                                                          "records": [e]}))
    rules = {**S.load_rules(), "live_states": sorted(set(S.rules_live_states(S.load_rules()) or []) | {"FL"})}
    S._GEOM_CACHE.clear()
    saved = S._STATES
    try:
        st, _ = S.build(now=now, write=False, events_dir=tmp_path, waters=waters, outfalls=[], registry={},
                        reaches={}, flows=({}, {}), rules=rules, rain={})
    finally:
        S._STATES = saved
        S._GEOM_CACHE.clear()
    w = st["waters"]["example-lake-fl"]
    assert w["status"] == "yellow"
    r = w["reasons"][0]
    assert r["rule"] == "text_caution" and r["text_over_flag"] == P.TEXT_REACHED_BASIS and r["window_hours"] is None
    assert "its form said no water was reached" in r["short"]


# ---------------------------------------------------------------- the review of 2026-11-04: shapes a careful reader counts

@pytest.mark.parametrize("description,water", [
    # the storm-drain shape (the coordinator's default): the drain the sewage went into drains or leads to the water
    ("The remaining 600 gallons entered a nearby storm drain which led to Example Waterway.", "Example Waterway"),
    ("Sewage entered a storm drain. The storm drain drains to Example Creek.", "Example Creek"),
    ("The spill flowed into a storm inlet leading to Lake Placeholder. Street was washed down.", "Lake Placeholder"),
    ("It is suspected the pond overflowed into the swale that leads to the Sample River. Samples were taken.",
     "Sample River"),
    ("A portion of the overflow did enter a nearby stormwater conveyance leading to the Example Creek tributary.",
     "Example Creek"),
    # the water before its verb
    ("Example Waterway was affected by the leak at two points of entry.", "Example Waterway"),
    ("The storm drains on the street were affected, along with the Sample Waterway. 500 gallons entered the waterway.",
     "Sample Waterway"),
    # an unnamed part of the named water, a name in brackets, a kind typed in lower case
    ("Sewage overflowed into a storm drain that discharges into a boat basin off of Example Sound.", "Example Sound"),
    ("Wastewater reached surface waters (Example Ocean) and was fully dispersed.", "Example Ocean"),
    ("The remaining 4,000 gallons entered the Placeholder waterway. Sampling in progress.", "Placeholder Waterway"),
    ("Approximately 50 gallons entered a storm drain that flows into Sample waterway.", "Sample Waterway"),
    # "not recovered" is the part that escaped, not a negation
    ("The remaining 200 gallons not recovered entered Example Creek.", "Example Creek"),
])
def test_the_review_shapes_win_over_the_forms_n(description, water):
    r = record(description)
    assert r["raw"]["reached_water"] == "text" and r["waterbody_text"] == water, r["raw"].get("_reached_water_words")


@pytest.mark.parametrize("description", [
    # a drain the text only places near the spill, or one the sewage stayed in
    "The manhole cover is located about 6 feet away from a storm water grate that drains to Lake Placeholder on "
    "property. The spill was cleaned up.",
    "Sewage pooled near a storm drain that leads to Example Creek.",
    "Sewage entered a catch basin, this basin leads to Example Lake. Staff observed the sewage remained within the "
    "storm water basin roughly 100 yards from the lake.",
    "Sewage entered a storm drain that leads to Example Creek, but was recovered before reaching the creek.",
    # a negation or no name in the passive form
    "No waterway was affected. No storm drains were impacted.",
    "Example Creek was not affected.",
    "Sample Lake, west of the property, was not impacted.",
    "Example Creek was reached by crews at noon.",
    # a lower-case kind that is as often a storm inlet or a catch basin is no name
    "Sewage entered the Curb inlet on the street.",
    "Sewage flowed into the Catch basin behind the station.",
])
def test_the_review_negatives_keep_the_forms_n(description):
    r = record(description)
    assert r["raw"]["reached_water"] is False, (description, r["raw"].get("_reached_water_words"))


def test_text_caution_with_an_authority_window_is_never_red_and_keeps_the_caution():
    # a state rule with an authority window (24 h) and the site's 72 h caution: start-end and the window are the site's
    # caution (text_caution), the caution runs on to 72 h after the end; nothing is red
    rules = S.load_rules()
    rules = {**rules, "red": {**rules["red"], "by_state": {**rules["red"]["by_state"],
                                                            "FL": {"hours": 24, "clock": "end_of_discharge",
                                                                   "basis": "placeholder", "source": None}}}}
    e = {**_ev("ended", "2026-11-09T06:00:00-05:00"), "time_precision": "minute",
         "started_at": "2026-11-09T00:00:00-05:00"}
    ivs = S.event_intervals(e, "FL", NOW, rules=rules)
    assert [iv["rule"] for iv in ivs] == ["text_caution", "text_caution", "caution"]
    assert {iv["color"] for iv in ivs} == {"yellow"}
    assert [iv["rule_applied"].get("replaces") for iv in ivs[:2]] == ["discharge", "authority_window"]
    assert ivs[-1]["end"] == datetime(2026, 11, 12, 11, 0, tzinfo=UTC)               # 72 h after the 06:00 EST end
    plain = S.event_intervals({**e, "raw": {"reached_water": False}}, "FL", NOW, rules=rules)
    assert [iv["color"] for iv in plain][:2] == ["red", "red"]                       # the same record without "text"


@pytest.mark.parametrize("reached", [True, False, None, "yes", "no"])
@pytest.mark.parametrize("status,ended_at", [("ongoing", None), ("ended", "2026-11-09T00:00:00-05:00"),
                                             ("unknown", None)])
def test_event_intervals_are_unchanged_for_every_record_not_placed_by_text(reached, status, ended_at):
    e = _ev(status, ended_at, reached=reached)
    rules = S.load_rules()
    assert S.event_intervals(e, "FL", NOW, rules=rules) == S._event_intervals(e, "FL", NOW, None, rules)
    assert not any("text_over_flag" in iv for iv in S.event_intervals(e, "FL", NOW, rules=rules))


def test_rebuilt_keeps_a_review_shape_and_its_words():
    r = record("Sewage entered a nearby storm drain which led to Example Waterway.")
    again = P.rebuilt(json.loads(json.dumps(r)), {})
    assert {k: v for k, v in again["raw"].items() if k != "_first_seen_at"} == \
        {k: v for k, v in r["raw"].items() if k != "_first_seen_at"}
    assert again["raw"]["_reached_water_words"] == "led to Example Waterway"


def test_a_provisional_outfall_reads_a_text_placed_report_as_reaching_a_water():
    from build import provisional_outfalls as PO
    assert PO.reached(_ev("ended", "2026-11-09T00:00:00-05:00")) == "yes"
    assert PO.reached(_ev("ended", "2026-11-09T00:00:00-05:00", reached=False)) == "no"
