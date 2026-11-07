"""Mississippi: the Mississippi rules of EPA's overflow tables (Central time, the free-text scrub, the City of Jackson's
shorthand creek names), on real Mississippi rows of the 2026-11-04 extract (tests/fixtures/ms_epa_sobe.json: street
names replaced by placeholders). No network."""
import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures" / "ms_epa_sobe.json"
INFO = {"extract_date": "2026-11-04", "last_modified": None}


def _tables():
    doc = json.loads(FIX.read_text())
    return {k: v for k, v in doc.items() if isinstance(v, list)}


def _build(tables=None):
    kept, dropped, why = E.build(copy.deepcopy(tables or _tables()), INFO)
    return {r["source_record_id"]: r for r in kept}, {d["source_record_id"]: d for d in dropped}, why


def test_mississippi_is_read_in_central_time_with_the_scrub_and_its_own_points():
    assert "MS" in E.STATES and E.STATE_TZ["MS"] == "America/Chicago" and "MS" in E.FREE_TEXT_STATES
    assert "MS" not in E.REPEATED_POINT_STATES      # a manhole that overflows each storm repeats its own point
    assert set(E.STATE_WATER_ALIASES) == {"MS"}


def test_kept_and_dropped_rows_by_reason():
    kept, dropped, why = _build()
    assert sorted(kept) == ["MS0020117:1:1", "MS0022381:1:1", "MS0024295:1:1", "MS0024295:5:1", "MS0024295:8:1",
                            "MS0044059:10:1", "MS0045446:10:18", "MS0061191:1:1"]
    assert {k: d["reason"] for k, d in dropped.items()} == {
        "MS0029513:8:1": "the report says the matter was not sewage",          # "It was algae and lawn chemicals"
        "MS0024295:16:3": "no evidence the discharge reached a water",         # 'SAMPLE LAKE CIR' is a street
        "MS0024163:1:1": "building backup",                                   # sewage backup in a building
        "MS0036111:2:1": "receiving water stated as none",                    # a bypass whose water is 'None'
        "MS0024848:1:1": "no evidence the discharge reached a water",         # the one CSO-typed row: no water named
        "MS0020184:1:1": "no evidence the discharge reached a water"}         # an SSO naming no water
    assert why[("MS", "kept", "receiving water named")] == 8


def test_a_bypass_is_kept_and_an_extreme_event_report_keeps_its_days():
    kept, _, _ = _build()
    vb = kept["MS0022381:1:1"]                                               # Vicksburg's plant bypass
    assert vb["event_type"] == "bypass" and vb["waterbody_text"] == "Mississippi River" and vb["outfall_id"] is None
    assert vb["started_at"] == "2026-01-10T11:00:00-06:00" and vb["lat"] is not None
    g9b = kept["MS0061191:1:1"]                                              # no per-event times: the report period
    assert g9b["time_precision"] == "day" and g9b["started_at"] == "2026-06-20" and g9b["ended_at"] == "2026-06-23"


def test_times_carry_central_offsets_winter_and_summer():
    kept, _, _ = _build()
    assert kept["MS0020117:1:1"]["started_at"] == "2026-01-09T21:50:00-06:00"
    assert kept["MS0045446:10:18"]["started_at"] == "2026-06-18T23:20:00-05:00"
    assert "America/Chicago" in kept["MS0020117:1:1"]["raw"]["timezone_note"]
    assert kept["MS0020117:1:1"]["reported_at"] == "2026-05-26"               # received date, kept apart (late)


def test_receiving_water_text_jackson_shorthand_and_as_typed():
    kept, _, _ = _build()
    eu = kept["MS0024295:1:1"]
    assert eu["waterbody_text"] == "Eubanks Creek" and eu["raw"]["receiving_water_aliases"] == {"EUBANKS": "Eubanks Creek"}
    far = kept["MS0024295:8:1"]                                              # 15.4 km from Eubanks Creek: as typed
    assert far["waterbody_text"] == "EUBANKS" and "receiving_water_aliases" not in far["raw"]
    assert kept["MS0044059:10:1"]["waterbody_text"] == "Trahon Creek"
    assert kept["MS0024295:5:1"]["waterbody_text"] == "BELHAVEN"              # no NHD creek of that name: as typed
    assert "receiving_water_aliases" not in kept["MS0024295:5:1"]["raw"]
    assert kept["MS0045446:10:18"]["waterbody_text"] == "Davis bayou"          # trailing space trimmed only
    # the shorthand is read for its own permit only
    t = _tables()
    ev = next(e for e in t["events"] if e["sewer_overflow_bypass_event_key"] == "6027")
    ev["permit_identifier"] = "MS0099999"
    k, _, _ = _build(t)
    assert next(r for r in k.values() if r["npdes_permit"] == "MS0099999")["waterbody_text"] == "EUBANKS"


def test_house_numbers_never_reach_a_mississippi_record():
    kept, dropped, _ = _build()
    blob = json.dumps([kept, dropped])
    for n in ("1391", "4049", "4625", "2009", "512 "):
        assert n not in blob, n
    assert kept["MS0024295:5:1"]["raw"]["sewer_overflow_bypass_description_text"] == (
        "[house number removed] SAMPLE ST - MANHOLE")
    # manhole numbers in the corrective-action text stay
    assert any("EU0708A" in (a["other"] or "") for r in kept.values() for a in r["raw"]["corrective_actions"])


def test_source_record_id_is_stable_across_report_versions():
    t = _tables()
    for e in t["events"]:
        e["program_report_form_id"] = str(int(e["program_report_form_id"] or 0) + 7)   # a later version of the report
    a, _, _ = _build()
    b, _, _ = _build(t)
    assert sorted(a) == sorted(b)
    assert all(r["raw"]["report_version"] != a[k]["raw"]["report_version"] for k, r in b.items())


def test_adding_mississippi_changes_no_other_states_record(monkeypatch):
    """The fixture's rows plus an Illinois and a New Hampshire row giving Jackson's shorthand 'EUBANKS', built with
    and without MS: every other record identical (also checked on the real 2026-11-04 extract: 3,550 other states'
    records and dropped rows identical; 248 Mississippi kept, 110 dropped)."""
    t = _tables()
    base = next(e for e in t["events"] if e["sewer_overflow_bypass_event_key"] == "6027")
    for key, permit in (("901", "IL0000001"), ("902", "NH0000001")):
        t["events"].append(dict(base, sewer_overflow_bypass_event_key=key, permit_identifier=permit,
                                program_report_form_set_id=key))
        t["types"].append({"sewer_overflow_bypass_event_key": key, "sewer_overflow_bypass_type_code": "SSO",
                           "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"})
        t["waters"].append({"sewer_overflow_bypass_event_key": key, "name_receiving_water": "EUBANKS"})

    def others(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = E.build(copy.deepcopy(t), INFO)
        return sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True) for r in kept + dropped
                      if not str(r.get("npdes_permit") or r.get("permit")).startswith("MS"))
    with_ms, without_ms = others(set(E.STATES)), others(set(E.STATES) - {"MS"})
    assert with_ms == without_ms and len(with_ms) == 2
    assert all('"waterbody_text": "EUBANKS"' in r for r in with_ms)


def test_main_reads_a_saved_zip_of_mississippi_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    t = _tables()
    z = tmp_path / "sobe.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for k, name in E.TABLES.items():
            rows = t.get(k) or []
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=sorted({c for r in rows for c in r}) or ["sewer_overflow_bypass_event_key"])
            w.writeheader()
            w.writerows(rows)
            zf.writestr(name, buf.getvalue())
    assert E.main(["--file", str(z)]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 8 and doc["meta"]["dropped"] == 6
    assert {"state": "MS", "outcome": "dropped", "reason": "building backup", "count": 1} in doc["meta"]["by_rule"]


# ---------------------------------------------------------------- operator rows (scripts/add_ms_operators.py)

ROOT = Path(__file__).resolve().parents[2]


def _ms_operators():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "MS"]


def test_every_mississippi_permit_has_exactly_one_operator_row():
    from collections import Counter
    dis = _ms_operators()
    held = Counter(p for r in dis for p in r["npdes_permits"])
    assert all(n == 1 for n in held.values())
    plants = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
    need = {r["npdes_permit"] for r in plants if r.get("state") == "MS"}
    cand = json.loads((ROOT / "research" / "ms" / "private-utilities-candidates.json").read_text())
    need |= {c["npdes_permit"] for c in cand["candidates"] + cand["public_by_name"]}
    need |= {x["npdes_permit"] for x in json.loads((ROOT / "research" / "ms" / "federal-seed.json").read_text())
             ["major_plant_permits"]}
    assert need <= set(held)
    by_id = {r["id"]: r for r in dis}
    jxn = by_id["ms-jackson-jxn"]
    assert set(jxn["npdes_permits"]) == {"MS0024295", "MS0044059", "MS0030295"} and jxn["legal_form"] == "city"
    assert "JXN Water" in jxn["notification_channel"] and "news releases" in jxn["notification_channel"]
    assert {"MS0045446", "MS0020249", "MS0021521", "MSU008001"} <= set(by_id["ms-jcua"]["npdes_permits"])
    assert by_id["ms-jcua"]["legal_form"] == "authority"
    assert by_id["ms-meridian"]["npdes_permits"] == ["MS0020117", "MS0055735"]
    assert by_id["ms-hinds-community-college"]["legal_form"] == "state facility"   # EPA types it private
    assert by_id["ms-cleary-heights-potw"]["legal_form"] is None                      # a subdivision's plant, not a town
    assert by_id["ms-great-river-utility-operating-co-llc"]["legal_form"] == "investor-owned utility"
    assert by_id["ms-mize-potw"]["legal_form"] is None and by_id["ms-beau-rivage-resorts-llc"]["legal_form"] == \
        "campground or resort"
    filing = set(json.loads((ROOT / "data" / "reference" / "ms-epa-sobe-permits.json").read_text())["permits"])
    for r in dis:      # one kind rule: an operator with a permit that files overflow reports is "sso"
        assert r["kind"] == ("sso" if set(r["npdes_permits"]) & filing else "plant"), r["id"]
        assert "Owner from" not in r["notes"] and "Plants:  (" not in r["notes"]
    assert sum(r["kind"] == "sso" for r in dis) == 33
    for r in dis:
        assert "[name removed]" not in r["name"] and r["notification_signup_url"] is None
        assert "24 hours" in r["notification_channel"]


def test_the_operator_rows_are_reproducible():
    import importlib.util
    spec = importlib.util.spec_from_file_location("add_ms_operators", ROOT / "scripts" / "add_ms_operators.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    out, _ = m.build(dis)
    assert [r for r in out if r.get("state") == "MS"] == _ms_operators()


def test_owner_names_from_epa_permit_names():
    import importlib.util
    spec = importlib.util.spec_from_file_location("add_ms_operators", ROOT / "scripts" / "add_ms_operators.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    o = lambda p, n, t="Municipal or Water District": m.owner(p, n, t)[:3]   # noqa: E731
    assert o("X", "LAUREL POTW, NUMBER 2") == ("LAUREL", "City of Laurel", "city")          # Census: a city
    assert o("X", "KILMICHAEL POTW") == ("KILMICHAEL", "Town of Kilmichael", "town")         # Census: a town
    assert o("X", "FOXWORTH POTW")[1:] == ("Foxworth municipal sewer system", None)        # not incorporated
    assert o("X", "WEST POINT POTW, WEST")[0] == "WEST POINT"
    assert o("X", "HARRISON CO UTIL AUTH, S20 D'IBERVILLE WWTF")[:2] == (
        "HARRISON COUNTY UTILITY AUTHORITY", "Harrison County Utility Authority")
    assert o("X", "DCRUA, OLIVE BRANCH POTW ROSS ROAD")[0] == "DESOTO COUNTY REGIONAL UTILITY AUTHORITY"
    assert o("X", "COLUMBUS, CITY OF, REYNOLDS R RIDGLEY WWTP") == ("COLUMBUS", "City of Columbus", "city")
    assert o("X", "JUMPERTOWN,TOWN OF, WWTF") == ("JUMPERTOWN", "Town of Jumpertown", "town")
    assert o("X", "Mississippi Band of Choctaw Indians (Tucker WWTF)", "Tribal Government")[2] == "tribal"
    assert o("X", "CLEARY HEIGHTS POTW")[2] is None


# ---------------------------------------------------------------- the register (scripts/add_ms_register_rows.py)

def test_the_mississippi_register_rows():
    from ingest import notification_pages as NP
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    doc = NP.load_register(ROOT / "data" / "notice-channels")
    assert NP.validate_register(doc, dis, ROOT) == []
    rows = {r["id"]: r for r in doc["channels"] if r["state"] == "MS"}
    assert rows["ms-epa-echo-overflow-events"]["feed_source_id"] == "echo-sewer-overflow"
    assert rows["ms-mdeq-sso-report"]["basis_kind"] == "permit" and rows["ms-mdeq-sso-report"]["barrier"] == "no_web_page"
    news = rows["ms-mdeq-news-releases"]
    assert news["unmonitored_reason"] == "feed_ingested" and news["feed_source_id"] == "ms-mdeq-water-contact-advisories"
    assert rows["ms-mdeq-beach-monitoring-map"]["feed_source_id"] == "ms-mdeq-beach-monitoring"
    assert rows["ms-mdeq-beach-signs"]["barrier"] == "signs_only"
    assert {r["operator_id"] for r in rows.values() if r["operator_id"]} == {"ms-jackson-jxn"}
    assert rows["ms-jackson-jxn-overflow-signs"]["barrier"] == "signs_only"
    assert not any("@" in json.dumps(r) for r in rows.values())


def test_mississippi_rules_row_cites_the_law_and_is_not_live():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ms = rules["red"]["by_state"]["MS"]
    assert ms["hours"] is None and "24 hours" in ms["basis"] and "NeT-SewerOverflow" in ms["source"]
    assert "MS" not in rules["live_states"]


def test_text_rules_are_mississippi_only_and_meridians_spellings_read():
    ev = {"sewer_overflow_bypass_description_text": "customer thought there was sewer in the pond. It was algae"}
    assert E.reached_water(ev, ["SSO"], [], [], "MS") == (False, "the report says the matter was not sewage")
    assert E.reached_water(ev, ["SSO"], [], [], "IL")[0] is True               # other states: the word rule as before
    st = {"sewer_overflow_bypass_description_text": "[house number removed] FOREST LAKE CIR - 220858"}
    assert E.reached_water(st, ["SSO"], [], [], "MS")[0] is False
    assert E.reached_water(st, ["SSO"], [], [], "GA")[0] is True
    keep = {"sewer_overflow_bypass_description_text": "Links Cove SSO - Lake Caroline"}
    assert E.reached_water(keep, ["SSO"], [], [], "MS")[0] is True            # a real lake named after the street word
    tab = E.STATE_WATER_ALIASES["MS"]
    assert tab[("MS0020117", "oaktibee creek")][0] == "Okatibbee Creek"
    assert tab[("MS0020117", "sawashee creek")][0] == "Sowashee Creek"
    assert E.alias_reaches(tab[("MS0024295", "eubanks")][2], 32.3480, -90.1817)
    assert not E.alias_reaches(tab[("MS0024295", "eubanks")][2], 32.2300, -90.2900)
    assert not E.alias_reaches(tab[("MS0024295", "eubanks")][2], None, None)
