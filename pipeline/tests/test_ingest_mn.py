"""Minnesota: the Metropolitan Council's spill notices (ingest/mn_mces_spill_notices.py), Resource Renew (WLSSD) overflow
points through the generic ArcGIS block (ingest/mn_transforms.py), Minnesota's rows of EPA's eRule tables
(ingest/echo_sewer_overflow_events.py, module docstring, Minnesota), the operators, the register, the rules row, the state
text and the missing-waters list. Fixtures: the Council's index and three spill pages of 2026-11-14 cut to their
content (the Council's own notices; no person), real WLSSD rows (infrastructure points kept to 0.001 degree), EPA's
one Minnesota report; invented pages with Example names. No network."""
import copy
import json
import re
from pathlib import Path

import pytest

from ingest import echo_sewer_overflow_events as E
from ingest import mn_mces_spill_notices as M
from ingest import mn_transforms as T
from ingest.generic import runner as R

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "mn"
FETCHED = "2026-11-14T18:00:00Z"
INDEX = "https://metrocouncil.org/Wastewater-Water/Services/Interceptor-Services/Spills/"


def mces(previous=(), fetched=FETCHED, drop=(), extra_pages=None, index=None):
    idx = index or (FIX / "mces" / "index.html").read_text()
    pages = {}
    for it in M.parse_index(idx):
        name = it["url"].rsplit("/", 1)[-1]
        f = FIX / "mces" / name
        pages[it["url"]] = None if name in drop else (f.read_text() if f.exists() else None)
    pages.update(extra_pages or {})
    recs, meta = M.build(idx, pages, fetched, list(previous))
    return {r["raw"]["city"]: r for r in recs}, meta


def wlssd():
    _, block = R.load_source("mn-wlssd-overflows")
    rows = R.platform("arcgis").parse(block, (FIX / "wlssd.json").read_bytes())
    recs, stats = R.build("mn-wlssd-overflows", block, rows, FETCHED, (), None)
    return {r["raw"]["row"]["OBJECTID"]: r for r in recs}, stats


def echo_tables():
    return {k: v for k, v in json.loads((FIX / "sobe_rows.json").read_text()).items() if isinstance(v, list)}


def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "MN"]


# ---------------------------------------------------------------- the Metropolitan Council's notices

def test_the_index_lists_three_spill_pages_without_their_query():
    items = M.parse_index((FIX / "mces" / "index.html").read_text())
    assert [i["label"] for i in items] == ["Excelsior, May 2026", "Minneapolis and Golden Valley, July 2026",
                                           "Eagan, November 2026"]
    assert all("?" not in i["url"] and i["url"].startswith(INDEX) for i in items)
    with pytest.raises(ValueError):
        M.parse_index("<html><body><h2>Something else</h2></body></html>")


def test_each_spill_is_a_sewer_overflow_dated_to_the_day_the_council_responded():
    recs, meta = mces()
    assert set(recs) == {"Excelsior", "Minneapolis and Golden Valley", "Eagan"} and meta["on_index"] == 3
    for r in recs.values():
        assert r["event_type"] == "sso" and r["time_precision"] == "day" and r["parse_error"] is None
        assert r["raw"]["time_zone"] == "America/Chicago" and r["discharger_id"] == "mn-mces"
        assert r["npdes_permit"] is None and r["published_at"] is None
        assert r["started_at"] is None and r["reported_at"] == r["raw"]["responded_on"]   # a response day, not a start
        assert "the spill's start is not given" in r["raw"]["start_basis"]
        assert r["raw"]["time_of_day_words"] == "afternoon" and "T" not in r["reported_at"]
    assert recs["Excelsior"]["reported_at"] == "2026-05-29" and recs["Eagan"]["reported_at"] == "2026-11-03"
    assert recs["Minneapolis and Golden Valley"]["reported_at"] == "2026-07-09"
    assert recs["Eagan"]["event_id"] == "mn-mces-spill-notices:Eagan-Wastewater-Spill:2026-11-03"
    assert recs["Excelsior"]["source_updated_at"] == "2026-06-01"


def test_the_councils_signs_are_its_window_and_their_removal_notice_ends_it():
    recs, _ = mces()
    ex = recs["Excelsior"]       # "will be removed": the signs stood to the end of June 1, their removal not confirmed
    assert ex["status"] == "advisory_active" and ex["ended_at"] is None and ex["advice_window_hours"] is None
    assert ex["raw"]["_unlisted_since"] == "2026-06-02T05:00:00Z" and ex["raw"]["_end_not_confirmed"] is True
    assert ex["raw"]["signs"]["removal_announced_on"] == "2026-06-01" and ex["raw"]["signs"]["removal_done"] is False
    assert "not one done" in ex["raw"]["signs"]["removal_note"]
    assert ex["raw"]["spill_stopped_on"] == "2026-05-29" and "Do Not Enter/ Sewage Spill" in ex["advice_text"]
    mp = recs["Minneapolis and Golden Valley"]
    assert mp["status"] == "advisory_active" and mp["raw"]["_unlisted_since"] == "2026-07-17T05:00:00Z"
    assert mp["raw"]["signs"]["posted_per_notice_of"] == "2026-07-10" and mp["raw"]["spill_stopped_on"] == "2026-07-09"
    eg = recs["Eagan"]                        # no signs: the spill's own stop, the day it was contained
    assert eg["status"] == "ended" and eg["ended_at"] == "2026-11-03" and "signs" not in eg["raw"]
    assert "in under an hour" in eg["raw"]["spill_stopped_words"]


def test_signs_with_no_removal_notice_stay_standing_with_no_end():
    page = ("<html><body><h1>Example Wastewater Spill</h1><p>The Metropolitan Council responded Monday morning, "
            "March 2, to a wastewater spill in Example City. Wastewater reached nearby Sample Creek.</p>"
            "<p>3/2/2026 - First Notice</p><p>Signs warning the public “Do Not Enter/ Sewage Spill” will be "
            "placed around affected areas.</p><h3>Contact us</h3></body></html>")
    idx = ('<h2>Spill information</h2><ul><li><a href="/Wastewater-Water/Services/Interceptor-Services/Spills/'
           'Example-Spill.aspx">Example City, March 2026</a></li></ul>')
    recs, meta = mces(index=idx, extra_pages={INDEX + "Example-Spill.aspx": page})
    r = recs["Example City"]
    assert r["status"] == "advisory_active" and r["ended_at"] is None and meta["advisory_active"] == 1
    assert r["reported_at"] == "2026-03-02" and r["started_at"] is None and r["waterbody_text"] == "Sample Creek"
    assert r["raw"]["county"] is None and meta["cities_without_county"] == ["Example City"]


def test_a_water_reached_is_placed_and_no_water_or_a_nearby_water_is_not():
    recs, _ = mces()
    ex = recs["Excelsior"]
    assert ex["waterbody_text"] == "Mud Pond" and ex["raw"]["reached_water"] is True
    assert ex["raw"]["county"] == "Hennepin County"          # county-aware: Minnesota has many Mud Ponds
    eg = recs["Eagan"]
    assert eg["waterbody_text"] is None and eg["raw"]["reached_water"] is False
    assert "No waterbodies were impacted" in eg["raw"]["_no_water_reason"] and eg["raw"]["county"] == "Dakota County"
    mp = recs["Minneapolis and Golden Valley"]
    assert mp["waterbody_text"] is None and mp["raw"]["reached_water"] is None
    assert mp["raw"]["nearby_waters"] == ["Bassett Creek", "Wirth Lake"] and mp["raw"]["county"] == "Hennepin County"


def test_a_page_that_leaves_the_index_is_kept_and_standing_signs_become_unconfirmed():
    first, _ = mces()
    prev = list(first.values())
    prev[0] = copy.deepcopy(prev[0])
    gone = next(r for r in prev if r["raw"]["city"] == "Excelsior")
    gone["status"], gone["ended_at"] = "advisory_active", None      # as if its signs were still up at the last read
    gone["raw"].pop("_unlisted_since", None)
    idx = (FIX / "mces" / "index.html").read_text()
    idx = re.sub(r'<li class="hdg-blue"><a href="[^"]*Excelsior[^"]*".*?</li>', "", idx, flags=re.S)
    recs, meta = mces(previous=prev, fetched="2026-11-15T18:00:00Z", index=idx)
    ex = recs["Excelsior"]
    assert meta["on_index"] == 2 and meta["kept_from_previous"] == 1
    assert ex["raw"]["gone_from_index_since"] == "2026-11-15T18:00:00Z"
    assert ex["raw"]["_unlisted_since"] == "2026-11-15T18:00:00Z" and ex["raw"]["_end_not_confirmed"] is True
    assert recs["Eagan"]["raw"]["_first_seen_at"] == FETCHED


def test_a_changed_page_is_a_revision_and_an_unread_page_keeps_its_record():
    first, _ = mces()
    prev = list(first.values())
    eagan = INDEX + "Eagan-Wastewater-Spill.aspx"
    changed = (FIX / "mces" / "Eagan-Wastewater-Spill.aspx").read_text().replace(
        "<h3>Contact us</h3>", "<p>11/6/2026 - Third Notice</p><p>Example follow-up.</p><h3>Contact us</h3>")
    recs, _ = mces(previous=prev, fetched="2026-11-16T18:00:00Z", extra_pages={eagan: changed})
    revs = recs["Eagan"]["raw"]["_revisions"]
    assert len(revs) == 1 and revs[0]["seen_at"] == "2026-11-16T18:00:00Z" and "Third Notice" in revs[0]["headings"]
    assert recs["Excelsior"]["raw"].get("_revisions") is None
    recs, meta = mces(previous=prev, drop=("Eagan-Wastewater-Spill.aspx",))
    assert recs["Eagan"] == first["Eagan"] and meta["pages_unread"] == [eagan]


def test_a_weekday_that_does_not_fit_the_date_is_a_parse_note():
    page = ("<h1>Example</h1><p>The Council responded Sunday afternoon, May 29, to a wastewater spill.</p>"
            "<h3>Contact us</h3>")
    r = M.build_one({"url": INDEX + "Example.aspx", "label": "Example City, May 2026"}, M.parse_page(page), FETCHED,
                    None)
    assert r["reported_at"] == "2026-05-29" and "does not fall on" in r["parse_error"] and r["event_type"] == "sso"


# ---------------------------------------------------------------- Resource Renew (WLSSD)

def test_wlssd_block_validates_and_requests_only_its_fields():
    _, block = R.load_source("mn-wlssd-overflows")
    assert R.validate_block(block, "mn-wlssd-overflows") == []
    assert block["metadata"] is False and block["round_coords"] == 3
    assert set(block["safe_fields"]) == {"OBJECTID", "OverflowDate", "FacilityType", "GlobalID", "ReleaseAmount",
                                         "StateWaters", "_x", "_y"}


def test_wlssd_types_dates_and_amounts():
    recs, _ = wlssd()
    assert recs[121]["event_type"] == recs[122]["event_type"] == "plant_bypass"
    assert all(r["event_type"] == "sso" for k, r in recs.items() if k not in (121, 122))       # blank type too
    assert recs[8]["raw"]["row"]["FacilityType"] is None and recs[8]["event_type"] == "sso"
    assert recs[122]["started_at"] == "2026-11-04T06:06:00-06:00" and recs[122]["time_precision"] == "minute"
    assert recs[78]["time_precision"] == "day" and recs[78]["started_at"].startswith("2023-04-12")
    assert recs[122]["volume_gal"] is None and recs[122]["volume_text"] == "70 MGD"          # a rate, never a volume
    assert recs[118]["volume_gal"] is None and recs[118]["volume_text"] == "100 gpm"
    assert recs[78]["volume_gal"] == 25000 and recs[116]["volume_gal"] is None               # "Less than 50 gallons"
    assert all(r["status"] == "unknown" and r["ended_at"] is None for r in recs.values())
    assert all(r["discharger_id"] == "mn-wlssd" and r["npdes_permit"] == "MN0049786" for r in recs.values())
    assert all(r["raw"]["time_zone"] == "America/Chicago" and r["raw"]["state"] == "MN" for r in recs.values())


def test_wlssd_state_waters_flag_and_points():
    recs, _ = wlssd()
    assert recs[121]["raw"]["reached_water"] is True and recs[116]["raw"]["reached_water"] is False
    assert "StateWaters field: No" in recs[116]["raw"]["_no_water_reason"]
    assert recs[78]["raw"]["reached_water"] is None
    for r in recs.values():
        assert round(r["lat"], 3) == r["lat"] and round(r["lon"], 3) == r["lon"]
        assert r["raw"]["county"] in ("St. Louis County", "Carlton County")
    assert T.point_county(46.758, -92.12) == "St. Louis County" and T.point_county(None, None) is None


# ---------------------------------------------------------------- EPA's tables

def test_epa_minnesota_report_in_central_time_with_its_zone():
    recs, dropped, _ = E.build(echo_tables(), {"extract_date": "2026-11-12"})
    assert len(recs) == 1 and not dropped
    r = recs[0]
    assert r["npdes_permit"] == "MN0061310" and r["discharger_id"] == "mn-bois-forte" and r["event_type"] == "sso"
    assert r["started_at"] == r["ended_at"] == "2024-06-18" and r["reported_at"] == "2024-06-25"
    assert r["raw"]["time_zone"] == "America/Chicago" and r["waterbody_text"] == "Pike Bay Lake Vermilion Tower Minnesota"


def test_adding_minnesota_leaves_other_states_records_unchanged(monkeypatch):
    ut = {k: v for k, v in json.loads((FIX.parent / "ut" / "sobe_rows.json").read_text()).items() if isinstance(v, list)}
    with_mn = E.build(copy.deepcopy(ut), {"extract_date": "2026-11-04"})[0]
    monkeypatch.setattr(E, "STATES", E.STATES - {"MN"})
    monkeypatch.setattr(E, "STATE_ZONE_ALWAYS", E.STATE_ZONE_ALWAYS - {"MN"})
    monkeypatch.setattr(E, "FREE_TEXT_STATES", E.FREE_TEXT_STATES - {"MN"})
    monkeypatch.setattr(E, "STATE_NAME_SCRUB", {})
    without = E.build(copy.deepcopy(ut), {"extract_date": "2026-11-04"})[0]
    strip = [{k: v for k, v in r.items() if k != "fetched_at"} for r in with_mn]
    assert strip == [{k: v for k, v in r.items() if k != "fetched_at"} for r in without] and strip
    assert not E.build(echo_tables(), {"extract_date": "2026-11-12"})[0]       # MN out: its report is not read


# ---------------------------------------------------------------- registry, register, rules, text

def test_operators_hold_every_minnesota_plant_permit_once():
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "MN"}
    rows = ops()
    held = [p for r in rows for p in r["npdes_permits"]]
    assert plants <= set(held) and len(held) == len(set(held))
    by = {r["id"]: r for r in rows}
    assert set(by["mn-mces"]["npdes_permits"]) >= {"MN0029815", "MN0029882", "MN0030007", "MN0029998", "MN0025488"}
    assert by["mn-mces"]["name"] == "Metropolitan Council" and by["mn-mces"]["legal_form"] == "special district"
    assert by["mn-wlssd"]["npdes_permits"] == ["MN0049786"] and by["mn-duluth"]["kind"] == "sso"
    assert by["mn-bois-forte"]["legal_form"] == "tribal"
    assert all("115.061" in r["notification_channel"] for r in rows)


def test_register_rows_per_operator_and_the_feeds():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from add_mn_register_rows import OWN, duty_applies
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "mn.json").read_text())["channels"]}
    for r in ops():          # the statute's duty only where the row's legal form puts it in the statute's scope
        if duty_applies(r) or r["id"] in OWN:
            assert reg[f"{r['id']}-public-notice"]["operator_id"] == r["id"]
        else:
            assert f"{r['id']}-public-notice" not in reg
    assert reg["mn-mces-public-notice"]["feed_source_id"] == "mn-mces-spill-notices"
    assert reg["mn-wlssd-public-notice"]["feed_source_id"] == "mn-wlssd-overflows"
    assert reg["mn-bois-forte-overflow-report"]["feed_source_id"] == "echo-sewer-overflow"
    assert reg["mn-duty-officer"]["barrier"] == "phone_only" and reg["mn-mpca-release-reports"]["barrier"] == "no_web_page"
    assert all(c["state"] == "MN" for c in reg.values())


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    mn = rules["red"]["by_state"]["MN"]
    assert mn["hours"] is None and "115.061" in mn["source"] and not re.search(r"\b(safe|clean)\b", mn["basis"], re.I)
    srcs = rules["unresolved"]["day_start_caution"]["sources"]
    assert {"mn-wlssd-overflows", "mn-mces-spill-notices"} <= set(srcs)


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "mn" / "state-text.md").read_text()
    assert t.startswith("---\nstate: MN\nname: Minnesota\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "\n{{share_line}}\n" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean|green)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "117 releases" in t and "115.061" in t          # operator counts: test_p2_5_mn_text_and_register_follow...


def test_missing_waters_list_names_what_the_national_list_lacks():
    d = json.loads((ROOT / "research" / "mn" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in nat["states"]["MN"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    names = {r["name"] for r in d["rows"]} | {r["name"] for r in d.get("resolved") or []}
    assert "Mud Pond" in names and d["waters"] == len(d["rows"])
    assert not [r["name"] for r in d["rows"] if k(r["name"]) in held]
    mud = next((r for r in d["rows"] if r["name"] == "Mud Pond"), None)
    assert mud is None or mud["county"] == "Hennepin County"


# ---------------------------------------------------------------- review 2026-11-14 (Astra)

def test_p1_2_a_stop_named_by_weekday_a_week_later_is_kept_on_its_own_day():
    page = ("<h1>Example</h1><p>The Council responded Monday afternoon, March 2, to a wastewater spill in Example City."
            "</p><p>3/9/2026 - Second Notice</p><p>Crews stopped the spill Monday evening.</p>"
            "<p>3/12/2026 - Third Notice</p><p>Signs warning the public \u201cDo Not Enter/ Sewage Spill\u201d have "
            "been placed.</p><h3>Contact us</h3>")
    r = M.build_one({"url": INDEX + "Example.aspx", "label": "Example City, March 2026"}, M.parse_page(page), FETCHED,
                    None)
    assert r["reported_at"] == "2026-03-02" and r["raw"]["spill_stopped_on"] == "2026-03-09"   # "Monday" of 3/9
    assert r["status"] == "advisory_active" and r["ended_at"] is None and r["advice_window_hours"] is None


def test_p1_2_removal_announced_with_no_stop_is_not_a_lift():
    page = ("<h1>Example</h1><p>The Council responded Monday afternoon, March 2, to a wastewater spill in Example City."
            " Signs warning the public \u201cDo Not Enter/ Sewage Spill\u201d will be placed.</p>"
            "<p>3/20/2026 - Second Notice</p><p>Signs will be removed.</p><h3>Contact us</h3>")
    r = M.build_one({"url": INDEX + "Example.aspx", "label": "Example City, March 2026"}, M.parse_page(page), FETCHED,
                    None)
    assert r["status"] == "advisory_active" and r["ended_at"] is None and r["raw"]["_end_not_confirmed"] is True
    assert r["raw"]["_unlisted_since"] == "2026-03-21T05:00:00Z"        # the end of March 20, Central daylight time


def test_p1_3_the_councils_window_then_grey_and_eagans_caution_in_central_time():
    from datetime import datetime, timezone
    from build import status as S
    recs, _ = mces()
    now = datetime(2026, 11, 14, 18, tzinfo=timezone.utc)

    def at(r, y, mo, d, h):
        c, ivs = S.status_at(S.event_intervals(r, "MN", now), datetime(y, mo, d, h, tzinfo=timezone.utc))
        return c, [iv["rule"] for iv in ivs]
    ex = recs["Excelsior"]
    assert at(ex, 2026, 5, 29, 20)[0] == "red"                       # the spill's day
    assert at(ex, 2026, 6, 1, 20) == ("red", ["advisory_active"])    # the Council's signs, to the end of June 1 (CDT)
    assert at(ex, 2026, 6, 2, 6)[1] == ["unresolved"]                # removal announced, not confirmed: hatched
    eg = recs["Eagan"]
    assert at(eg, 2026, 11, 6, 12)[0] == "yellow"                    # the site's caution, 72 hours after Nov 3 (CST)
    assert at(eg, 2026, 11, 7, 7)[0] == "grey"


def test_p1_4_an_error_page_keeps_the_previous_record_and_the_run_fails():
    first, _ = mces()
    ex_url = INDEX + "Excelsior-Wastewater-Spill-(1).aspx"
    recs, meta = mces(previous=list(first.values()), extra_pages={ex_url: "<html><h1>Service unavailable</h1></html>"})
    assert recs["Excelsior"] == first["Excelsior"] and meta["pages_unread"] == [ex_url]


def test_p1_6_raw_save_is_scrubbed():
    page = {"intro": "Call Pat Example at 612-555-0142 or pat@example.com; the spill at 1234 Example Street.",
            "updates": [{"date": "2026-03-02", "heading": "Contact Inspector Example", "text": "x"}]}
    out = json.dumps(M.scrubbed({"pages": {"u": page}}))
    assert "612-555-0142" not in out and "pat@example.com" not in out and "1234 Example" not in out


def test_p1_8_advice_quotes_the_signs_and_no_safety_assurance():
    recs, _ = mces()
    for r in recs.values():
        assert not re.search(r"\bsafe\b|\bclean\b", json.dumps(r), re.I)
    assert recs["Excelsior"]["advice_text"].startswith("The Council's signs at the affected areas")


def test_p1_6_wlssd_free_text_is_scrubbed_and_p1_7_mn_epa_points_are_rounded():
    _, block = R.load_source("mn-wlssd-overflows")
    assert {"ReleaseAmount", "FacilityType", "StateWaters"} <= set(block["free_text"])
    raw = json.loads((FIX / "wlssd.json").read_text())
    raw["features"][0]["attributes"]["ReleaseAmount"] = "about 50 gallons, call 218-555-0142"
    rows = R.platform("arcgis").parse(block, json.dumps(raw).encode())
    recs, _ = R.build("mn-wlssd-overflows", block, rows, FETCHED, (), None)
    assert "218-555-0142" not in json.dumps(recs)
    r = E.build(echo_tables(), {"extract_date": "2026-11-12"})[0][0]
    assert round(r["lat"], 3) == r["lat"] and round(r["lon"], 3) == r["lon"]
    assert all(round(float(x["latitude_measure"]), 3) == float(x["latitude_measure"])
               for x in echo_tables()["events"])


def test_p2_3_mn_plant_only_names_are_permit_only_rows_and_facility_rows_count_no_outfall():
    by = {r["id"]: r for r in ops()}
    for rid in ("mn-arlington-wwtp", "mn-montevideo-wwtp"):
        r = by[rid]
        assert r["permit_only"] is True and r["legal_form"] is None and r["name"].startswith("Permit MN")
        assert "not established" in r["notes"]
    assert "permit_only" not in by["mn-mces"]
    benson = by["mn-benson"]
    assert benson["outfall_count"] is None and "0 outfalls of 1 rows" in benson["outfalls_source"]


def test_p2_3_operator_builder_rules_on_invented_rows():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import icis_operators as I
    assert I.plant_only("Example WWTP") and I.plant_only("Example Water Resource Recovery Facility")
    assert not I.plant_only("City of Example") and not I.plant_only("Example Sanitary District")
    assert not I.plant_only("Example Wastewater Treatment Association Inc")
    ok = {"outfall": "001", "receiving_water_echo": "Example Creek", "permittee": "EXAMPLE WWTP"}
    assert I.outfall_eligible(ok) == (True, None)
    assert not I.outfall_eligible({**ok, "outfall": None})[0]                       # facility-only
    assert not I.outfall_eligible({**ok, "receiving_water_echo": "Example WWTP"})[0]  # a collection system
    assert not I.outfall_eligible({**ok, "permittee": "Example Dewatering Project"})[0]
    assert not I.outfall_eligible({**ok, "outfall_kind": "other"})[0]


def test_p2_5_mn_text_and_register_follow_the_computed_counts_and_the_statutes_scope():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from add_mn_register_rows import duty_applies
    t = (ROOT / "research" / "mn" / "state-text.md").read_text()
    rows = ops()
    n_ops = sum(1 for r in rows if not r.get("permit_only"))
    n_only = sum(1 for r in rows if r.get("permit_only"))
    n_duty = sum(1 for r in rows if duty_applies(r))
    assert f"name {n_ops} Minnesota sewer and treatment operators" in t and f"{n_only} more permits" in t
    assert f"{n_duty} of the operators" in t
    assert "publicly or privately owned domestic sewer system" in t                   # the statute's own scope
    law = re.search(r"\*\*What the law requires\.\*\*([^\n]*)", t).group(1)
    assert "domestic" in law
    assert "where the District gives them" in t                                        # amounts and types not always given
