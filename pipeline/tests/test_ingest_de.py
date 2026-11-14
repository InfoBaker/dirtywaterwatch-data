"""Delaware: DNREC's DERNS Recent Releases (ingest/de_dnrec_derns.py) and its recreational-water advisories
(ingest/de_dnrec_recwater.py), and the state's registry rows, register, rules row, state text and missing-waters list.
Fixtures: a list page and three detail pages in DERNS's markup with invented rows (Example names, placeholder house and
telephone numbers), and rows of the 2026-11-14 fetch of the advisory history and the FirstMap stations. No network."""
import copy
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from ingest import de_dnrec_derns as D
from ingest import de_dnrec_recwater as W

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "de"
T0, T1, T2 = "2026-11-14T18:00:00Z", "2026-11-14T19:00:00Z", "2026-11-14T20:00:00Z"
PERSONAL = ["Pat Example", "pat.example@example.org", "3025550142", "302-555-0142", "555-0142", "9876 Example",
            "1234 Example", "4321 Sample", "5678 Sample"]


def listing():
    return D.list_rows((FIX / "derns_list.html").read_text())


def state_with_details():
    st = {"rows": {}}
    D.merge(st, listing(), T0)
    pages = {"2026-2850": "derns_detail_water.html", "2026-2849": "derns_detail_ground.html",
             "2026-2844": "derns_detail_textwater.html"}
    for key, f in pages.items():
        d = D.safe_detail(D.parse_detail((FIX / f).read_text()))
        st["rows"][key].update(detail=d, detail_hash="h0", detail_read_at=T0)
    return st


def records(st=None):
    recs, reasons = D.build(st or state_with_details(), T0)
    return {r["source_record_id"]: r for r in recs}, reasons


# ---------------------------------------------------------------- DERNS

def test_the_list_and_the_pager_are_read():
    rows = listing()
    assert len(rows) == 7 and rows[0]["key"] == "2026-2850" and rows[0]["release_number"] == "17770"
    page = (FIX / "derns_list.html").read_text()
    assert D.page_count(page) == 3
    nxt = D.Client._next(page, "SEWAGE")
    assert nxt["__VIEWSTATE"] == "EXAMPLEVIEWSTATE" and any(k.endswith("btnNext") for k in nxt)
    assert nxt[D.P + "txtSearchValue"] == "SEWAGE"


def test_only_candidate_substances_are_kept_at_all():
    st = {"rows": {}}
    n = D.merge(st, listing(), T0)
    assert n == {"rows_read": 7, "not_candidate": 1, "candidates": 6}
    assert "2026-2847" not in st["rows"]                          # fuel oil at a home: never saved


@pytest.mark.parametrize("substance,facility,location,detail,want", [
    ("SEWAGE", "SPILL LOCATION", "Example Road", None, "sewage"),
    ("Raw Sewage", "", "", None, "sewage"),
    ("SEWAGE/GREYWATER", "", "", None, "sewage"),
    ("WASTEWATER", "SPILL LOCATION", "Example Pump Station #3, Dover", None, "sewage"),
    ("UNTREATED WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", None, "sewage"),
    ("Poultry process wastewater", "EXAMPLE FOODS LLC", "", None, "industrial"),
    ("WASTEWATER", "PERDUE PROCESSING", "Example Road", None, "industrial"),
    ("Treated effluent", "LEWES BOARD OF PUBLIC WORKS", "", None, "treated_effluent"),
    ("WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", None, "pending"),
    ("WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", {"text": "Water spilled from a truck."}, "wastewater_unattributed"),
    ("WASTEWATER", "DISCHARGE LOCATION", "Example Avenue", {"text": "A force main broke."}, "sewage"),
    ("Non-sanitary poultry process wastewater", "", "", None, "industrial"),
    ("FUEL OIL, [DIESEL]", "RESIDENCE", "", None, "not_candidate"),
])
def test_sewage_by_rule(substance, facility, location, detail, want):
    assert D.classify({"substance": substance, "facility": facility, "location": location}, detail)[0] == want


def test_kept_and_dropped_rows_by_reason():
    recs, reasons = records()
    assert set(recs) == {"2026-2850", "2026-2849", "2026-2845", "2026-2844"}
    assert reasons == {"sewage": 4, "industrial": 1, "treated_effluent": 1}


def test_times_in_eastern_time_with_no_end_and_the_report_time_apart():
    recs, _ = records()
    r = recs["2026-2850"]
    assert r["started_at"] == "2026-11-12T07:30:00-05:00" and r["time_precision"] == "minute"
    assert r["reported_at"] == "2026-11-12T09:05:00-05:00" and r["published_at"] is None
    assert r["ended_at"] is None and r["status"] == "unknown" and r["raw"]["time_zone"] == "America/New_York"
    assert r["raw"]["release_duration"] == "3 hours" and r["raw"]["derns_status"] == "Final"
    assert "never read as an end" in r["raw"]["end_basis"]
    midnight = recs["2026-2849"]
    assert midnight["started_at"] == "2026-11-11" and midnight["time_precision"] == "day"
    summer = D.parse_time("7/4/2026 2:00:00 PM")
    assert summer == ("2026-07-04T14:00:00-04:00", "minute")


def test_water_ground_and_the_text_over_the_form():
    recs, _ = records()
    w = recs["2026-2850"]
    assert w["raw"]["released_to"] == ["Ground", "Water"] and w["raw"]["reached_water"] is True
    assert w["waterbody_text"] == "White Clay Creek" and w["advice_text"].startswith("Avoid contact")
    g = recs["2026-2849"]
    assert g["raw"]["reached_water"] is False and "ground only" in g["raw"]["_no_water_reason"]
    assert g["waterbody_text"] is None and g["advice_text"] is None
    t = recs["2026-2844"]
    assert t["raw"]["reached_water"] == "text" and t["waterbody_text"] == "Shellpot Creek"
    assert "ground only" in t["raw"]["_reached_water_basis"]
    # a list row whose detail is not read yet: no water claim either way
    assert "reached_water" not in recs["2026-2845"]["raw"]


def test_operator_type_volume_and_county():
    recs, _ = records()
    r = recs["2026-2850"]
    assert r["event_type"] == "sso" and r["discharger_id"] == "de-new-castle-county"
    assert r["volume_gal"] == 12000.0 and r["estimate_flag"] == "estimated"
    assert r["raw"]["county"] == "New Castle" and r["raw"]["town"] == "Newark"
    assert recs["2026-2849"]["raw"]["county"] == "Kent" and recs["2026-2849"]["discharger_id"] is None
    assert D.county_of("Example Road, Rehoboth Beach, DE 19971") == "Sussex"
    assert D.county_of("Example Road, Milford, DE 19963") is None                       # a ZIP across two counties
    assert D.county_of("Example Road, Smyrna") == "Kent"


def test_a_release_at_a_private_home_keeps_its_county_only():
    recs, _ = records()
    r = recs["2026-2845"]
    assert r["raw"]["private_source"] and r["raw"]["county"] == "Sussex" and r["raw"]["town"] == "Milton"
    assert "location_text" not in r["raw"] and "facility_text" not in r["raw"] and r["outfall_name"] is None
    assert r["discharger_id"] is None


def test_no_personal_field_or_string_reaches_a_record_or_the_saved_state():
    st = state_with_details()
    recs, _ = records(st)
    blob = json.dumps(list(recs.values())) + json.dumps(st)
    for s in PERSONAL:
        assert s not in blob, s
    assert "[house number removed]" in blob and "[phone removed]" in blob and "Call [name removed]" in blob
    assert D.scrub("Spoke with Ms. Sample about the spill; called New Castle County.") == \
        "Spoke with [name removed] about the spill; called New Castle County."
    assert "lblContact" not in json.dumps(D.DETAIL_SPANS) and "lblFacAddress" not in json.dumps(D.DETAIL_SPANS)


def test_a_changed_detail_is_kept_with_its_revision_and_the_key_is_stable():
    st = state_with_details()

    class Fake:
        def detail(self, key):
            d = D.parse_detail((FIX / "derns_detail_water.html").read_text())
            d["quantity"] = "15,000 gallons"
            return d
    n = D.read_details(Fake(), st, ["2026-2850"], T1)
    assert n["details_changed"] == 1
    recs, _ = records(st)
    r = recs["2026-2850"]
    assert r["event_id"] == "de-dnrec-derns-recent-releases:2026-2850" and r["volume_gal"] == 15000.0
    assert r["raw"]["_revisions"][0]["seen_at"] == T1 and r["raw"]["release_number"] == "17770"
    assert r["source_url"].endswith("ReleaseID=2026-2850")


def test_details_are_due_newest_first_and_capped():
    st = {"rows": {}}
    D.merge(st, listing(), T0)
    from datetime import datetime, timezone
    due = D.due_for_detail(st, datetime(2026, 11, 14, 18, tzinfo=timezone.utc), 3)
    assert due == ["2026-2850", "2026-2849", "2026-2848"]


def test_a_failed_list_keeps_the_previous_records(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    (tmp_path / f"{D.SOURCE_ID}.json").write_text(json.dumps({"records": [{"event_id": "x"}], "meta": {"m": 1}}))

    class Boom(D.Client):
        def recent(self, pages):
            raise RuntimeError("the Recent Releases list showed no rows")
    monkeypatch.setattr(D, "Client", Boom)
    monkeypatch.setattr(D, "STATE_PATH", tmp_path / "state.json")
    assert D.main([]) == 1
    out = json.loads((tmp_path / f"{D.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["records"] == [{"event_id": "x"}] and "no rows" in out["error"]


# ---------------------------------------------------------------- recreational water

def rec():
    s = json.loads((FIX / "recwater.json").read_text())
    return s


def test_history_types_lifts_tests_and_the_label_only_resampling():
    s = rec()
    recs, n = W.history_records(s["advisories"], W.station_index(s["stations"]), date(2026, 11, 14), T0)
    by = {r["source_record_id"]: r for r in recs}
    assert n["test_rows"] == 2 and "adv-319" not in by and "adv-352" not in by
    assert "adv-628" not in by and "adv-695" not in by and "adv-716" not in by and "adv-479" not in by
    assert "adv-331" not in by                                   # an advisory row whose text is a lift
    a = by["adv-625"]
    assert a["event_type"] == "beach_advisory" and a["status"] == "advisory_lifted"
    assert (a["started_at"], a["ended_at"], a["time_precision"]) == ("2025-06-17", "2025-06-18", "day")
    assert a["raw"]["ended_at_precision"] == "day" and a["raw"]["time_zone"] == "America/New_York"
    assert a["waterbody_text"] == "Lake Como" and a["lat"] == round(a["lat"], 3) and a["coord_source"] == "station"
    assert by["adv-264"]["event_type"] == "beach_closure" and by["adv-266"]["event_type"] == "hab_advisory"
    assert by["adv-264"]["waterbody_text"] == "Silver Lake" and by["adv-264"]["raw"]["county"] == "Kent"
    r = by["adv-727"]
    assert r["status"] == "unknown" and r["raw"]["_agency_label_only"] and r["raw"]["_caution_to_notice_end"]
    assert r["raw"]["_agency_label"] == "Recreational Water Quality Resampling Underway"
    assert r["raw"]["_notice_closed_at"] == "2026-07-29" and r["waterbody_text"] == "Atlantic Ocean"
    assert by["adv-274"]["status"] == "unknown" and "no end date" in by["adv-274"]["raw"]["status_basis"]
    assert by["adv-274"]["waterbody_text"] == "Delaware Bay" and by["adv-274"]["lat"] is None


def test_the_map_status_opens_and_closes_records_at_polls():
    s = rec()
    st = copy.deepcopy(s["stations"])
    for x in st:
        x["CurrentAdvisory"] = 0 if x["UnitName"] == "Slaughter Beach" else (2 if x["UnitName"].startswith("Lewes") else 4)
    hist, _ = W.history_records(s["advisories"], W.station_index(st), date(2026, 7, 1), T0)
    recs, state = W.poll_records(st, hist, {}, T0, date(2026, 7, 1))
    by = {r["raw"]["unit_name"]: r for r in recs}
    sl = by["Slaughter Beach"]
    assert sl["status"] == "advisory_active" and sl["started_at"] == T0 and sl["time_precision"] == "poll"
    assert sl["waterbody_text"] == "Delaware Bay" and sl["raw"]["current_advisory_label"] == "Monitoring – Current Advisory"
    lw = by["Lewes Beach (Savannah Beach)"]
    assert lw["status"] == "unknown" and lw["raw"]["_agency_label_only"]
    for x in st:
        x["CurrentAdvisory"] = 3
    recs2, _ = W.poll_records(st, hist, state, T1, date(2026, 7, 1))
    ended = {r["raw"]["unit_name"]: r for r in recs2}
    assert ended["Slaughter Beach"]["status"] == "advisory_lifted" and ended["Slaughter Beach"]["ended_at"] == T1
    assert ended["Slaughter Beach"]["raw"]["ended_at_precision"] == "poll"
    # winter, outside the advisory area and no advisory: no record
    recs3, _ = W.poll_records(st, hist, {}, T2, date(2026, 11, 14))
    assert recs3 == []


def test_a_history_row_in_effect_is_not_doubled_by_the_map():
    s = rec()
    st = copy.deepcopy(s["stations"])
    for x in st:
        x["CurrentAdvisory"] = 2 if x["UnitName"].startswith("Rehoboth Beach - Rehoboth") else 4
    hist, _ = W.history_records(s["advisories"], W.station_index(st), date(2026, 7, 28), T0)
    recs, _ = W.poll_records(st, hist, {}, T0, date(2026, 7, 28))
    assert recs == []                                        # adv-727 covers that day


# ---------------------------------------------------------------- registry, register, rules, text, waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "DE"]


def test_every_delaware_permit_is_in_exactly_one_row():
    from build import redact
    from ingest import dischargers_schema as DS
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    permits = {r["npdes_permit"] for f in ("outfalls-plants-us.json", "outfalls-us.json")
               for r in json.loads((ROOT / "data" / f).read_text())["outfalls"] if r.get("state") == "DE"}
    assert len(permits) == 13 and all(every[p] == 1 for p in permits)
    rows = ops()
    assert not DS.check_legal_forms(rows) and not [r["name"] for r in rows if redact.person_shaped(r["name"])]
    wil = next(r for r in rows if r["id"] == "de-de0020320")
    assert wil["kind"] == "cso" and wil["outfall_count"] == 41 and "sign" in wil["notification_channel"]
    ids = {r["id"] for r in rows}
    assert {i for _, i in D.OPERATORS} <= ids                          # every operator the ingester names has a row


def test_the_storm_sewer_permit_is_kind_other():
    doc = json.loads((ROOT / "data" / "outfalls-de.json").read_text())
    assert [(r["npdes_permit"], r["outfall_kind"]) for r in doc["outfalls"]] == [("DE0051071", "other")]
    import common
    reg = [r for r in common.load_outfall_registry(provisional=False) if r.get("npdes_permit") == "DE0051071"]
    assert [r["outfall_kind"] for r in reg] == ["other"]
    ncc = next(r for r in ops() if r["id"] == "de-new-castle-county")
    assert "DE0051071" in ncc["npdes_permits"] and ncc["outfall_count"] == 3


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "de.json").read_text())["channels"]}
    for r in ops():
        row = reg[f"{r['id']}-dnrec-releases"]
        assert row["feed_source_id"] == "de-dnrec-derns-recent-releases" and "6028(a)" in row["legal_basis"]
    assert reg["de-wilmington-cso-signs"]["barrier"] == "signs_only"
    assert reg["de-dnrec-derns-alerts"]["barrier"] == "login_required"
    assert reg["de-dnrec-recreational-water"]["feed_source_id"] == "de-dnrec-recreational-water"
    assert reg["de-epa-echo-overflow-events"]["monitored"]


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    de = rules["red"]["by_state"]["DE"]
    assert de["hours"] is None and "6028(a)" in de["source"] and "6002(20)" in de["source"]
    assert not re.search(r"\b(safe|clean)\b", de["basis"], re.I)
    assert "de-dnrec-recreational-water" in rules["unresolved"]["sample_caution"]["sources"]


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "de" / "state-text.md").read_text()
    assert t.startswith("---\nstate: DE\nname: Delaware\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "6028" in t and "10,000 gallons" in t and "41" in t


def test_missing_waters_list_leaves_out_the_national_lists_names():
    d = json.loads((ROOT / "research" / "de" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in nat["states"]["DE"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    assert d["state"] == "DE" and d["waters"] == len(d["rows"]) > 0
    assert not [r["name"] for r in d["rows"] if k(r["name"]) in held]
    keys = [(r["name"], r["county"]) for r in d["rows"]]
    assert len(keys) == len(set(keys))


def test_adding_the_states_leaves_the_other_states_lists_as_they_were():
    from build import charts, report_geolocate, status
    assert status.COUNTY_STATES["DE"] == "de-counties.json" and "DE" in status.COUNTY_FIELD_STATES
    assert status.COUNTY_STATES["TN"] == "tn-counties.json" and status.COUNTY_STATES["AL"] == "al-counties.json"
    assert charts.STATE_NAMES["DE"] == "Delaware" and report_geolocate.STATE_NAMES["SC"] == "South Carolina"
    assert report_geolocate.STATE_NAMES["DE"] == "Delaware" and charts.STATE_NAMES["TN"] == "Tennessee"
    counties = json.loads((ROOT / "data" / "reference" / "de-counties.json").read_text())
    assert sorted(c["county"] for c in counties["counties"]) == ["Kent County", "New Castle County", "Sussex County"]
