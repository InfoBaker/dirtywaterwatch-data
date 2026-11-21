"""New York's rates, durations and descriptions, and our estimates from them (export/estimates.py, export/detail.py;
site docs/decisions.md items 31, 46, 47, 48), on real NY-Alert records trimmed from the export of 2026-11-14
(tests/fixtures/ny_sprtk_estimates.json). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as status_mod  # noqa: E402
from common import NAME_KEYS, PERSONAL_KEYS, event  # noqa: E402
from export import build as X  # noqa: E402
from export import csv as csv_export  # noqa: E402
from export import detail as D  # noqa: E402
from export import estimates as E  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "ny_sprtk_estimates.json"


@pytest.fixture
def recs():
    doc = json.loads(FIXTURE.read_text())
    return {r["event_id"]: {k: v for k, v in r.items() if not k.startswith("_")} for r in doc["records"]}


def wb(recs, rid):
    return copy.deepcopy(recs[f"ny-dec-sprtk:{rid}"])


# ------------------------------------------------------------------------------------------------ the source's rate


@pytest.mark.parametrize("text, want", [
    ("75 Gallons per Minute Estimated", {"unit": "gallons per minute", "low": 75, "high": 75, "qualifier": "estimated"}),
    ("Estimated at 75gpm Gallons per Minute Estimated", {"unit": "gallons per minute", "low": 75, "high": 75, "qualifier": "estimated"}),
    ("16 Gallons per Minute Actual", {"unit": "gallons per minute", "low": 16, "high": 16, "qualifier": "actual"}),
    ("10,277 Gallons per Minute Estimated", {"unit": "gallons per minute", "low": 10277, "high": 10277, "qualifier": "estimated"}),
    ("100-150gpm Gallons per Minute Estimated", {"unit": "gallons per minute", "low": 100, "high": 150, "qualifier": "estimated"}),
    ("100+ Gallons per Minute Estimated", {"unit": "gallons per minute", "low": 100, "bound": "at_least", "qualifier": "estimated"}),
    # the notifier's unit wins over the form's: a rate in million gallons per day filed under "Gallons"
    (".5 mgd Gallons Estimated", {"unit": "million gallons per day", "low": 0.5, "high": 0.5, "qualifier": "estimated"}),
    ("less than .1 mgd Gallons Estimated", {"unit": "million gallons per day", "high": 0.1, "bound": "less_than", "qualifier": "estimated"}),
])
def test_a_rate_is_kept_as_the_sources_value(text, want):
    assert E.parse_ny_rate(text) == {"text": text, **want}


@pytest.mark.parametrize("text", [
    "60,000 Gallons Estimated",                       # a total: volume_of's, not a rate
    "500 gallons Gallons Estimated",
    "unknown Gallons per Minute Estimated",
    "Heavy Rain Gallons per Minute Estimated",
    "exact quantity unknown due to pump not running at full capacity during duration. 6 inch diesel pump used rated at "
    "200 gpm Gallons per Minute Estimated",           # a pump's rating inside a sentence: not the rate of the discharge
    "1-2 and 5 Gallons per Minute Estimated",
    "15-10 Gallons per Minute Estimated",             # a range written backwards
    None, "",
])
def test_anything_but_a_plain_rate_gives_no_value(text):
    assert E.parse_ny_rate(text) is None


@pytest.mark.parametrize("text, want", [
    ("4 Hours - Ongoing", (240, "ongoing")),
    ("30 Minutes - Ended", (30, "ended")),
    ("3 hours and 50 minutes Hours - Ended", (230, "ended")),
    ("2hrs 15mins Hours - Ended", (135, "ended")),
    ("05:30 Hours - Ended", (330, "ended")),
    ("00:08 Minutes - Ended", (8, "ended")),              # H:MM whatever the form's unit (start 20:30, end 20:38)
    (".5 Hours - Ended", (30, "ended")),
    ("1,750 Minutes - Ended", (1750, "ended")),
    ("Apprx 3hrs Hours - Ongoing", (180, "ongoing")),
    ("2 Hours", (120, None)),                             # the web page's message: no Ongoing/Ended marker
    ("36 hours 45 min Hours", (2205, None)),
    ("unknown Hours - Ongoing", (None, "ongoing")),
    ("all day Hours - Ongoing", (None, "ongoing")),
    ("Intermittent 2 Hours - Ongoing", (None, "ongoing")),  # an intermittent discharge: not a duration to multiply
    ("TBD - Ongoing Hours - Ongoing", (None, "ongoing")),
    ("NA Hours - Ongoing", (None, "ongoing")),
    ("continuous when it is raining while collection system is charged Hours - Ongoing", (None, "ongoing")),
])
def test_a_duration_is_read_only_where_it_is_a_number(text, want):
    assert E.parse_ny_duration(text) == want


# ------------------------------------------------------------------------------------------------ computed volumes


def test_a_rate_with_the_notices_own_start_and_end_gives_our_volume(recs):
    """Walden, a Close notice: "Estimated at 75gpm" from 19:25 to 10:00 the next morning (875 minutes)."""
    e = wb(recs, "2397177477336798")
    v = E.volume_estimate_of(e)
    assert v["gallons"] == 75 * 875 == 65625
    assert v["basis"] == ("We multiplied the rate the notice gives, 75 gallons per minute, by the 14 hours, 35 minutes "
                          "between its start and end times.")
    assert v["formula"] == "rate × duration"
    assert v["inputs"]["duration_from"] == "start_to_end" and v["inputs"]["duration_minutes"] == 875
    assert (v["inputs"]["started_at"], v["inputs"]["ended_at"]) == (e["started_at"], e["ended_at"])
    assert v["inputs"]["rate"]["text"] == "Estimated at 75gpm Gallons per Minute Estimated"
    assert E.end_estimate_of(e) is None                   # the notice gives its end
    assert e["volume_gal"] is None                        # never written to the source's field


def test_an_open_notice_gives_our_volume_and_our_end_from_its_expected_duration(recs):
    """Cheektowaga, a New notice: 1,350 gallons per minute, "4 Hours - Ongoing", from 08:50."""
    e = wb(recs, "2345603510134952")
    v = E.volume_estimate_of(e)
    assert v["gallons"] == 1350 * 240 == 324000
    assert v["basis"] == ("We multiplied the rate the notice gives, 1,350 gallons per minute, by the expected duration it "
                          "gives, 4 hours.")
    assert v["inputs"]["duration_from"] == "duration_expected" and v["inputs"]["duration_text"] == "4 Hours - Ongoing"
    end = E.end_estimate_of(e)
    assert end == {"at": "2026-02-18T12:50:00-05:00", "precision": "minute",
                   "basis": "We added the expected duration the notice gives, 4 hours, to its start time.",
                   "inputs": {"started_at": "2026-02-18T08:50:00-05:00", "duration_minutes": 240,
                              "duration_from": "duration_expected", "duration_text": "4 Hours - Ongoing"}}
    assert e["ended_at"] is None and e["status"] == "ongoing"     # the record and its status are unchanged


def test_a_start_and_end_that_disagree_with_the_reported_duration_give_a_range(recs):
    """Cheektowaga: start 12:30, end 19:02 (6 h 32 min), duration "05:30 Hours - Ended"; 650 gallons per minute."""
    v = E.volume_estimate_of(wb(recs, "2527641404017062"))
    assert (v["low"], v["high"]) == (650 * 330, 650 * 392) and "gallons" not in v
    assert v["basis"] == ("The notice's start and end times are 6 hours, 32 minutes apart, and the duration it reports is "
                          "5 hours, 30 minutes. We multiplied the rate it gives, 650 gallons per minute, by each.")
    assert (v["inputs"]["duration_minutes_low"], v["inputs"]["duration_minutes_high"]) == (330, 392)


def test_a_range_of_rates_gives_a_range_and_a_bound_gives_a_bound(recs):
    v = E.volume_estimate_of(wb(recs, "2431124898858640"))           # 10-15 gallons per minute, 48 hours expected
    assert (v["low"], v["high"]) == (10 * 2880, 15 * 2880) and "bound" not in v
    assert v["basis"].startswith("We multiplied the rate range the notice gives, 10 to 15 gallons per minute, by")
    v = E.volume_estimate_of(wb(recs, "2709404419944422"))           # less than 0.1 mgd for 3 minutes
    assert v == {**v, "high": 209, "bound": "less_than"} and "low" not in v and "gallons" not in v   # 208 1/3, rounded up
    assert "less than 0.1 million gallons per day" in v["basis"]
    e = wb(recs, "2428857156430377")                                 # 100+ gpm, "Ongoing Hours - Ongoing"
    assert E.rate_of(e)["bound"] == "at_least" and E.volume_estimate_of(e) is None   # no duration: no volume


def test_no_estimate_from_a_zero_rate_free_text_or_a_stated_total(recs):
    zero = wb(recs, "2437172212948804")                              # "0 Gallons per Minute Estimated", 2 hours
    assert E.rate_of(zero)["low"] == 0 and E.volume_estimate_of(zero) is None
    assert E.end_estimate_of(zero)["at"] == "2026-03-23T09:00:00-04:00"   # its end is still estimated
    na = wb(recs, "2713046552293488")                                # 10 gpm, "NA Hours - Ongoing"
    assert E.rate_of(na)["low"] == 10 and E.volume_estimate_of(na) is None and E.end_estimate_of(na) is None
    total = wb(recs, "2203972668576492")                             # "30000 Gallons Estimated", "31 Minutes - Ongoing"
    assert E.rate_of(total) is None and E.volume_estimate_of(total) is None
    assert E.end_estimate_of(total)["at"] == "2025-10-20T05:10:00-04:00"


def test_a_later_stated_total_of_the_same_event_wins(recs):
    """Syracuse's New notice (2,274 gpm, 24 hours expected) and the chain's Close (830,010 Gallons Estimated)."""
    new, close = wb(recs, "2560558033413876"), wb(recs, "2560558033432051")
    assert E.volume_estimate_of(new) is not None                     # alone it would get one
    D.enrich([new, close])
    assert new["later_volume"]["volume_gal"] == 830010
    assert "volume_estimate" not in new and "volume_estimate" not in close
    assert new["end_estimate"]["at"] == "2026-06-11T15:10:00-04:00"  # its own expected end stays, labelled ours
    assert "end_estimate" not in close


def test_web_page_notices_use_the_duration_the_message_gives(recs):
    web = copy.deepcopy(recs["ny-dec-sprtk-web:NYS900021-20261106T162658Z"])
    v = E.volume_estimate_of(web)
    assert v["gallons"] == 15 * 150 and v["inputs"]["duration_from"] == "duration_given"
    assert v["basis"] == "We multiplied the rate the notice gives, 15 gallons per minute, by the duration it gives, 2 hours, 30 minutes."
    assert E.end_estimate_of(web)["at"] == "2026-11-06T11:00:00-05:00"
    nyc = copy.deepcopy(recs["ny-dec-sprtk-web:NYCDEPCSO-20261114T122520Z"])   # "0 Gallons per Minute", 2 hours
    assert E.volume_estimate_of(nyc) is None
    assert E.end_estimate_of(nyc)["basis"] == "We added the duration the notice gives, 2 hours, to its start time."
    # an ENDED web notice's end is start + duration already (ny_sprtk_web): not the notice's own end to multiply
    ended = {**web, "status": "ended", "ended_at": "2026-11-06T11:00:00-05:00",
             "raw": {**web["raw"], "_ended_at_basis": "computed: discharge start + reported duration (2 hours 30 minutes Hours)"}}
    assert E.volume_estimate_of(ended)["inputs"]["duration_from"] == "duration_given"
    assert E.end_estimate_of(ended) is None


def test_starts_we_do_not_trust_give_no_estimate(recs):
    e = wb(recs, "2345603510134952")
    future = {**e, "started_at": "2026-12-30T08:50:00-05:00"}        # a start in the future as published: no end from it
    assert E.end_estimate_of(future) is None
    assert E.volume_estimate_of(future)["gallons"] == 324000          # rate x stated duration does not use the start
    bound = {**e, "raw": {**e["raw"], "start_is_upper_bound": True}}  # a start that is only an upper bound
    assert E.end_estimate_of(bound) is None
    long = {**e, "raw": {**e["raw"], "row": {**e["raw"]["row"], "dischargeDuration": "800 Hours - Ongoing"}}}
    assert E.end_estimate_of(long) is None and E.volume_estimate_of(long) is None    # over MAX_DAYS


def test_a_start_known_only_to_the_day_gives_a_day(recs):
    e = {**wb(recs, "2345603510134952"), "started_at": "2024-02-18T00:00:00-05:00", "time_precision": "day"}
    end = E.end_estimate_of(e)
    assert end["at"] == "2024-02-19" and end["precision"] == "day"   # the last day 4 hours after that day allows
    assert "gives no time of day" in end["basis"]
    assert E.volume_estimate_of(e)["inputs"]["duration_from"] == "duration_expected"   # a day start is no span


def test_only_mapped_sources_get_anything(recs):
    e = {**wb(recs, "2345603510134952"), "source_id": "md-baltimore-sso"}
    assert E.estimates_of(e) == {} and E.rate_of(e) is None


# ------------------------------------------------------------------------------------------------ descriptions


def test_descriptions_and_the_component_are_the_sources_words(recs):
    k = wb(recs, "2625738457226843")                                 # Kenmore: a manhole on a lawn
    d = D.detail_of(k)
    assert d["description"] == "Sanitary sewer overflow into storm sewer"
    assert d["overflow_point"] == "Manhole"
    assert "location_description" not in d                         # the outlet name already says it (said once)
    assert D.ny_place_text("row.addressDescription")(k["raw"]) == "Manhole is on the front lawn of [house number removed] Sample sso #12"
    assert d["rate"] == {"text": "10 Gallons per Minute Estimated", "unit": "gallons per minute", "low": 10, "high": 10,
                         "qualifier": "estimated"}
    assert "volume_qualifier" not in d                              # a rate carries its own; there is no volume
    w = wb(recs, "2397177477336798")                                 # Walden: address description = outlet name
    assert "location_description" not in D.detail_of(w)
    c = wb(recs, "2345603510134952")                                 # Cheektowaga: component "Storm bypass pump"
    dc = D.detail_of(c)
    assert dc["overflow_point"] == "Pump Station" and dc["location_description"] == "Pump station"
    s = wb(recs, "2560558033413876")                                 # "CSO Outfall,CSO Outfall,... -" read once
    assert D.detail_of(s)["overflow_point"] == "CSO Outfall"
    assert D.detail_of(s)["location_description"] == "CSO outfall is farthest upstream."
    web = copy.deepcopy(recs["ny-dec-sprtk-web:NYS900021-20261106T162658Z"])
    assert D.detail_of(web)["description"] == "Sanitary sewer overflowing into storm sewer"
    assert D.ny_place_text("parsed.location_details")(web["raw"]) == "Manhole is in the Melrose lawn at [house number removed] Example, SSO #004"


def test_a_description_loses_any_street_addresss_house_number_and_contacts():
    raw = {"row": {"dischargeDescription": "Overflow at 12 Sample Rd; call 555-123-4567 or pat@example.org",
                   "addressDescription": "Manhole in front of 45 Oak Street", "quantity": "60 Gallons per Minute Estimated"}}
    d = D.detail_of({"source_id": "ny-dec-sprtk", "raw": raw, "outfall_name": "Manhole"})
    assert "12 Sample" not in d["description"] and "555" not in d["description"] and "@" not in d["description"]
    assert d["location_description"] == "Manhole in front of [house number removed] Oak Street"
    assert not any(PERSONAL_KEYS.search(f) or NAME_KEYS.search(f) for f in D.FIELDS)


# ------------------------------------------------------------------------------------------------ the export


def test_slim_rows_carry_our_figures_without_their_inputs(recs):
    e = wb(recs, "2345603510134952")
    D.enrich([e])
    assert e["volume_estimate"]["inputs"]["duration_minutes"] == 240        # the event's own file has the inputs
    s = X.slim_event({**e, "file": "events/x.json", "fixture": False})
    assert s["volume_estimate"] == {"gallons": 324000, "basis": e["volume_estimate"]["basis"]}
    assert s["end_estimate"] == {"at": "2026-02-18T12:50:00-05:00", "precision": "minute", "basis": e["end_estimate"]["basis"]}
    assert s["detail"]["rate"]["low"] == 1350 and "overflow_point" not in s["detail"]     # the cell's fields only
    k = wb(recs, "2625738457226843")
    D.enrich([k])
    assert X.slim_event({**k, "file": "events/k.json", "fixture": False})["detail"]["description"] == "Sanitary sewer overflow into storm sewer"
    assert "volume_gal" not in s or s["volume_gal"] is None
    for k in ("volume_estimate", "end_estimate"):
        assert k in X.WATER_EVENT_EXTRA


@pytest.fixture
def covered(monkeypatch):
    monkeypatch.setattr(status_mod, "_STATES", {"NY"})


def test_csv_rows_carry_the_sources_rate_and_our_figures_apart(tmp_path, covered, recs):
    a, b = wb(recs, "2345603510134952"), wb(recs, "2527641404017062")
    D.enrich([a, b])
    rows = []
    for r in (a, b):
        x = event(**{k: v for k, v in r.items() if k in {"event_id", "source_id", "source_record_id", "event_type", "status",
                                                          "started_at", "ended_at", "discharger_name", "published_at",
                                                          "volume_gal", "volume_text", "parent_event_id"}})
        x.update(fixture=False, water_slugs=[], detail=r.get("detail"), volume_estimate=r.get("volume_estimate"),
                 end_estimate=r.get("end_estimate"), raw={}, state="NY")
        rows.append(x)
    out = tmp_path / "csv"
    csv_export.write_csvs(rows, [], [], out, page_ids=set())
    import csv as _csv
    with (out / "state" / "ny.csv").open(newline="", encoding="utf-8") as f:
        got = {r["event_id"]: r for r in _csv.DictReader(f)}
    ga, gb = got[a["event_id"]], got[b["event_id"]]
    assert ga["volume_gal"] == "" and ga["rate_text"] == "1350 Gallons per Minute Estimated"
    assert (ga["volume_estimate_gal"], ga["end_estimate_at"]) == ("324000", "2026-02-18T12:50:00-05:00")
    assert ga["volume_estimate_basis"].startswith("We multiplied") and ga["end_estimate_basis"].startswith("We added")
    assert ga["location_description"] == "Pump station" and ga["overflow_point"] == "Pump Station"
    assert (gb["volume_estimate_gal"], gb["volume_estimate_low_gal"], gb["volume_estimate_high_gal"]) == ("", "214500", "254800")


def test_an_existing_export_gets_our_figures(tmp_path, recs):
    """export.detail's applier (python -m export.detail <out>): event files, events.json and water files."""
    out = tmp_path / "out"
    (out / "events").mkdir(parents=True)
    (out / "waters").mkdir()
    chosen = [wb(recs, r) for r in ("2345603510134952", "2560558033413876", "2560558033432051")]
    for e in chosen:
        e["file"] = f"events/{X.event_file_name(e['event_id'])}"
        (out / e["file"]).write_text(json.dumps(e))
    slim = [{k: v for k, v in e.items() if k != "raw"} for e in chosen]
    (out / "events.json").write_text(json.dumps({"events": slim}))
    (out / "waters" / "onondaga-creek-ny.json").write_text(json.dumps({"events": [dict(slim[1])]}))
    D._main(str(out))
    full = json.loads((out / chosen[0]["file"]).read_text())
    assert full["volume_estimate"]["gallons"] == 324000 and full["volume_estimate"]["inputs"]["duration_minutes"] == 240
    new = json.loads((out / chosen[1]["file"]).read_text())
    assert "volume_estimate" not in new and new["later_volume"]["volume_gal"] == 830010 and "end_estimate" in new
    rows = {r["event_id"]: r for r in json.loads((out / "events.json").read_text())["events"]}
    assert rows[chosen[0]["event_id"]]["volume_estimate"] == {"gallons": 324000, "basis": full["volume_estimate"]["basis"]}
    w = json.loads((out / "waters" / "onondaga-creek-ny.json").read_text())["events"][0]
    assert "volume_estimate" not in w and w["end_estimate"]["at"] == "2026-06-11T15:10:00-04:00"


# ------------------------------------------------------------------------------------------------ review fixes
# Astra's review of 2026-11-21 ($C/reviews/ny-fields-astra.md): each finding taken, with the input that showed it


def test_review_1_a_hyphenated_house_number_leaves_a_description():
    raw = {"row": {"addressDescription": "Manhole outside 123-45 Example Avenue",
                   "dischargeDescription": "Overflow between 12-14 Sample Road and the creek",
                   "streetNumber": "123-45", "streetName": "Example Avenue"}}
    d = D.detail_of({"source_id": "ny-dec-sprtk", "raw": raw, "outfall_name": "Manhole"})
    assert d["location_description"] == "Manhole outside [house number removed] Example Avenue"
    assert d["description"] == "Overflow between [house number removed] Sample Road and the creek"
    raw = {"row": {"addressDescription": "Manhole on the lawn of 123-45 Example", "streetNumber": "123-45", "streetName": "Example St"}}
    assert "123" not in D.ny_place_text("row.addressDescription")(raw)          # the notice's own number, no street word


def test_review_2_a_bound_or_a_small_figure_is_never_rounded_into_a_stronger_claim(recs):
    v = E.volume_estimate_of(wb(recs, "2709404419944422"))           # less than 0.1 mgd for 3 minutes = 208 1/3 gallons
    assert (v["high"], v["bound"]) == (209, "less_than")             # rounded outward
    e = wb(recs, "2345603510134952")
    more = {**e, "raw": {**e["raw"], "row": {**e["raw"]["row"], "quantity": "more than 1.6 Gallons per Minute Estimated",
                                             "dischargeDuration": "1 Minutes - Ongoing"}}}
    assert (E.volume_estimate_of(more)["low"], E.volume_estimate_of(more)["bound"]) == (1, "more_than")
    tiny = {**e, "raw": {**e["raw"], "row": {**e["raw"]["row"], "quantity": "0.1 Gallons per Minute Estimated",
                                             "dischargeDuration": "1 Minutes - Ongoing"}}}
    t = E.volume_estimate_of(tiny)                                   # 0.1 gallon: never printed as zero gallons
    assert t.get("gallons") is None and (t["high"], t["bound"]) == (1, "less_than")
    rng = {**e, "raw": {**e["raw"], "row": {**e["raw"]["row"], "quantity": "1.5-2.5 Gallons per Minute Estimated",
                                            "dischargeDuration": "1 Minutes - Ongoing"}}}
    assert (E.volume_estimate_of(rng)["low"], E.volume_estimate_of(rng)["high"]) == (1, 3)


def test_review_3_a_web_notices_computed_end_is_labelled_ours(recs):
    web = copy.deepcopy(recs["ny-dec-sprtk-web:NYS900021-20261106T162658Z"])
    ended = {**web, "status": "ended", "ended_at": "2026-11-06T11:00:00-05:00",
             "raw": {**web["raw"], "_ended_at_basis": "computed: discharge start + reported duration (2 hours 30 minutes Hours)"}}
    got = E.estimates_of(ended)
    assert got["ended_at_ours"] == {"basis": "We added the duration the notice gives, 2 hours, 30 minutes, to its start time."}
    assert "end_estimate" not in got and ended["ended_at"] == "2026-11-06T11:00:00-05:00"   # the record and status unchanged
    assert "ended_at_ours" not in E.estimates_of(wb(recs, "2397177477336798"))               # a workbook end is the source's
    D.enrich([ended])
    assert X.slim_event({**ended, "file": "events/w.json", "fixture": False})["ended_at_ours"] == got["ended_at_ours"]


def test_review_4_a_total_typed_under_the_rate_unit_is_not_multiplied(recs):
    assert E.parse_ny_rate("60,000 gallons Gallons per Minute Estimated") is None
    assert E.parse_ny_rate("5 gallons Gallons per Minute Estimated") is None     # the units disagree: no figure of ours
    e = wb(recs, "2345603510134952")
    e["raw"]["row"]["quantity"] = "60,000 gallons Gallons per Minute Estimated"
    assert E.volume_estimate_of(e) is None and D.detail_of(e).get("rate") is None


def test_review_5_a_fractional_duration_is_kept_in_the_arithmetic(recs):
    e = wb(recs, "2345603510134952")
    e["raw"]["row"].update(quantity="100 Gallons per Minute Estimated", dischargeDuration=".025 Hours - Ongoing")
    v = E.volume_estimate_of(e)
    assert v["gallons"] == 150 and v["inputs"]["duration_minutes"] == 1.5
    assert v["basis"].endswith("by the expected duration it gives, 1.5 minutes.")
    assert E.end_estimate_of(e)["at"] == "2026-02-18T08:51:30-05:00"
    k = wb(recs, "2625738457226843")                                 # 17:45:00 to 19:45:52: 120.87 minutes
    v = E.volume_estimate_of(k)
    assert v["gallons"] == 1209 and "2 hours, 0.9 minutes" in v["basis"]


def test_review_6_a_later_total_given_as_words_also_wins(recs):
    new, close = wb(recs, "2560558033413876"), wb(recs, "2560558033432051")
    close.update(volume_gal=None, volume_text="more than 830,010 Gallons Estimated")
    D.enrich([new, close])
    assert "later_volume" not in new and "volume_estimate" not in new
    new2, close2 = wb(recs, "2560558033413876"), wb(recs, "2560558033432051")
    close2.update(volume_gal=None, volume_text="unknown Gallons Estimated")      # no figure at all: ours stays
    D.enrich([new2, close2])
    assert "volume_estimate" in new2


def test_review_7_the_fixture_keeps_no_address_in_any_field():
    import re
    text = FIXTURE.read_text()
    doc = json.loads(text)
    for r in doc["records"]:
        assert "_chain" not in (r.get("raw") or {}), r["event_id"]
    # the only numbered addresses are the two fictional ones the note names
    assert not re.search(r"\b\d{2,6} (?!Sample|Example)[A-Z][a-z]+ (?:St|Ave|Rd|Blvd|Dr)\b", text)


def test_review_13_the_applier_removes_a_stale_figure_from_an_event_file(tmp_path, recs):
    out = tmp_path / "out"
    (out / "events").mkdir(parents=True)
    (out / "waters").mkdir()
    e = wb(recs, "2713046552293488")                                 # "NA Hours - Ongoing": no figure of ours now
    e["file"] = f"events/{X.event_file_name(e['event_id'])}"
    e["raw"]["row"].pop("dischargeReason", None)
    for k in ("receivingWaterBody", "treatedState", "notificationStatus", "city", "dischargeDescription", "addressDescription",
              "componentDescription", "systemComponent", "quantity", "dischargeDuration"):
        e["raw"]["row"].pop(k, None)
    stale = {**e, "volume_estimate": {"gallons": 600, "basis": "old"}, "detail": {"cause": "old"}}
    (out / e["file"]).write_text(json.dumps(stale))
    (out / "events.json").write_text(json.dumps({"events": [{"event_id": e["event_id"], "file": e["file"]}]}))
    D._main(str(out))
    after = json.loads((out / e["file"]).read_text())
    assert "volume_estimate" not in after and "detail" not in after


def test_review_3_the_csv_says_a_computed_end_was_not_reported(tmp_path, covered, recs):
    web = copy.deepcopy(recs["ny-dec-sprtk-web:NYS900021-20261106T162658Z"])
    web.update(status="ended", ended_at="2026-11-06T11:00:00-05:00")
    web["raw"]["_ended_at_basis"] = "computed: discharge start + reported duration (2 hours 30 minutes Hours)"
    D.enrich([web])
    x = event(**{k: v for k, v in web.items() if k in {"event_id", "source_id", "source_record_id", "event_type", "status",
                                                        "started_at", "ended_at", "discharger_name", "published_at",
                                                        "volume_gal", "volume_text"}})
    x.update(fixture=False, water_slugs=[], detail=web.get("detail"), volume_estimate=web.get("volume_estimate"),
             ended_at_ours=web.get("ended_at_ours"), raw={}, state="NY")
    out = tmp_path / "csv"
    csv_export.write_csvs([x], [], [], out, page_ids=set())
    import csv as _csv
    with (out / "state" / "ny.csv").open(newline="", encoding="utf-8") as f:
        row = next(_csv.DictReader(f))
    assert row["ended_at"] == "2026-11-06T11:00:00-05:00" and row["end_reported"] == "false"
    assert row["end_estimate_at"] == row["ended_at"] and row["end_estimate_basis"].startswith("We added the duration")
