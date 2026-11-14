"""Puerto Rico: the Puerto Rico rules of EPA's overflow tables (Atlantic Standard Time all year, generic receiving-water
texts as a water reached with no name, algal bloom and eutrophication impacts and storm-drain texts as a water, the
description read as a structure's name, the scrub with its courtesy-title rule, --file) on real PRASA rows
(tests/fixtures/pr_sobe_rows.json, the 2026-11-12 extract, with two synthetic rows), and the proof that adding Puerto
Rico changes no other state's record."""
import copy
import json
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E
from tests.test_ingest_ne import _zip

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def _fixture() -> dict:
    return json.loads((FIX / "pr_sobe_rows.json").read_text())


def _build(tables=None):
    t = copy.deepcopy(tables or _fixture())
    return E.build(t, {"extract_date": "2026-11-12", "last_modified": None, "now": "2026-11-14T00:00:00Z"})


def _by_key():
    kept, dropped, why = _build()
    return ({r["raw"]["sewer_overflow_bypass_event_key"]: r for r in kept},
            {r["source_record_id"]: r for r in dropped}, why)


def test_puerto_rico_is_read_in_its_own_clock_with_its_own_rules():
    assert "PR" in E.STATES and E.STATE_TZ["PR"] == "America/Puerto_Rico"
    assert "PR" in E.FREE_TEXT_STATES and "PR" not in E.REPEATED_POINT_STATES and "PR" not in E.PLANT_POINT_STATES
    assert "PR" not in E.SIGN_REPAIR_PREFIXES and "PR" not in E.POINT_ZONE_FILES
    assert set(E.STATE_UNNAMED_WATER) == {"PR"} and E.STATE_WATER_IMPACTS == {"PR": {"ALB", "EUT"}}
    assert E.DESCRIPTION_IS_PLACE_STATES == {"PR"} and set(E.EXTRA_PERSON_SCRUB) == {"PR"}


def test_kept_and_dropped_by_reason_and_the_stable_record_id():
    kept, dropped, why = _by_key()
    reasons = {r: n for (s, o, r), n in why.items() if s == "PR"}
    assert kept["5215"]["raw"]["reached_water_rule"] == "receiving water named"
    assert kept["5215"]["waterbody_text"] == "RIO BAIROA"            # as filed, never translated
    assert kept["27372"]["event_type"] == "bypass" and kept["27372"]["waterbody_text"] == "CABO CARIBE"
    assert kept["5215"]["source_record_id"] == "PR0025976:21:1"
    assert kept["5215"]["event_id"] == "echo-sewer-overflow:PR0025976:21:1"
    assert {"PR0025399:47:1", "PR0020923:6:1", "PR0026484:5:1"} <= set(dropped)   # odours, land, a station's name
    assert all(d["reason"] == "no evidence the discharge reached a water"
               for k, d in dropped.items() if k in ("PR0025399:47:1", "PR0020923:6:1", "PR0026484:5:1"))
    assert dropped["PR0000001:9001:1"]["reason"] == "building backup"
    assert reasons["receiving water reached, its name not given"] == 4


def test_a_generic_receiving_water_is_a_water_reached_with_no_name():
    kept, _, _ = _by_key()
    for k, said in (("5009", "CREEK (UNKNOWN THE NAME)"), ("26401", "Quebrada aledaña a la estación"),
                    ("27660", "CAÑO (UNKNOWN THE NAME)"), ("4060", "CREEK")):
        r = kept[k]
        assert r["waterbody_text"] is None and r["water_slugs"] == [], k
        assert r["raw"]["reached_water_rule"] == "receiving water reached, its name not given"
        assert said in r["raw"]["receiving_water_note"] and r["raw"]["receiving_waters"] == [said]
        assert r["lat"] is not None                                  # placed by its own point
    for w in ("RIO BAIROA", "QUEBRADA YAUREL", "QUEBRADA  Y EL RIO APEADERO", "ENSENADA HONDA BAY", "Charca los corazones"):
        assert not E.pr_unnamed(w), w
    for w in ("unnamed creek", "STREET, MANGROVE AND BAY", "RAVINE", "Laguna Artificial", "ADJACENT CREEK", "QUEBRADA"):
        assert E.pr_unnamed(w), w


def test_bloom_and_eutrophication_impacts_and_storm_drains_are_waters():
    kept, _, _ = _by_key()
    assert kept["4043"]["raw"]["reached_water_rule"] == "impact to a water (ALB)"
    assert kept["7222"]["raw"]["reached_water_rule"] == "impact to a water (EUT)"
    assert kept["5355"]["raw"]["reached_water_rule"] == "text names a water (stormwater drainage)"
    assert E.pr_water_text("RAINWATER LAGOON") and E.pr_water_text("descarga a la quebrada")
    assert E.pr_water_text("LAND") is None and E.pr_water_text("STREET") is None


def test_a_water_word_in_a_stations_name_is_not_a_water_reached():
    """'EBAS RIO GRANDE ESTATES' and 'EBAS BRISAS DEL MAR' are pump stations (module docstring, Puerto Rico)."""
    ev = {"sewer_overflow_bypass_description_text": "EBAS LAKE VIEW (PUMP STATION)", "sewer_overflow_structure_type_code": "PUM"}
    imp = [{"sewer_overflow_bypass_impact_code": "ODO", "sewer_overflow_bypass_impact_other_text": ""}]
    assert E.reached_water(ev, ["SSO"], [], imp, "PR") == (False, "no evidence the discharge reached a water")
    assert E.reached_water(ev, ["SSO"], [], imp, "NH")[0] is True     # elsewhere the description is still read


def test_times_carry_atlantic_standard_time_all_year():
    kept, _, _ = _by_key()
    for r in kept.values():
        assert r["raw"]["time_zone"] == "America/Puerto_Rico"
        assert "Puerto Rico keeps no daylight time" in r["raw"]["timezone_note"] and "state" not in r["raw"]["timezone_note"]
        if r["time_precision"] == "minute":
            assert r["started_at"].endswith("-04:00"), r["started_at"]
    assert kept["6096"]["time_precision"] == "day" and "T" not in kept["6096"]["started_at"]   # an extreme-event report
    assert E.zoned("2026-07-04T12:00:00", "PR") == "2026-07-04T12:00:00-04:00"
    assert E.zoned("2026-01-04T12:00:00", "PR") == "2026-01-04T12:00:00-04:00"


def test_a_shared_point_is_the_named_station_and_is_kept():
    kept, _, _ = _by_key()
    a, b = kept["27660"], kept["4060"]
    assert (a["lat"], a["lon"]) == (b["lat"], b["lon"]) == (18.352444, -65.69833)
    assert "point_note" not in a["raw"] and "reported_point" not in a["raw"]


def test_people_phones_and_house_numbers_never_reach_a_record():
    kept, dropped, _ = _by_key()
    text = json.dumps([kept, dropped], ensure_ascii=False)
    for s in ("Juan Ejemplo", "Pedro Ejemplo", "555-0100", "123 Calle", "45 Calle"):
        assert s not in text, s
    r = kept["s2"]
    assert "[name removed]" in r["raw"]["sewer_overflow_bypass_description_text"]
    assert "Carr. 306" in E.scrub_free_text({"x": "Pumping shut down due to emergency on Carr. 306, Lajas"}, ["x"])["x"]


def test_adding_puerto_rico_changes_no_other_states_record(monkeypatch):
    """The same tables built with and without PR give identical records for every other state (also checked on the
    real 2026-11-12 extract: 2,278 kept and 2,485 dropped records of the other states identical)."""
    from tests.test_ingest_dc import _row
    fx = _fixture()
    other = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
             _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                  sewer_overflow_bypass_description_text="Lift station near the river overflowed"),
             _row(sewer_overflow_bypass_event_key="o3", permit_identifier="NH0000001", program_report_form_set_id="3",
                  sewer_overflow_bypass_description_text="Manhole overflow"),
             _row(sewer_overflow_bypass_event_key="o4", permit_identifier="GA0000001", program_report_form_set_id="4",
                  latitude_measure="33.75", longitude_measure="-84.39",
                  sewer_overflow_bypass_description_text="Sr. Example called")]
    fx["events"] += other
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": "SSO",
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k in ("o1", "o2", "o3", "o4")]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": "o1", "name_receiving_water": "unnamed creek"},
                     {"sewer_overflow_bypass_event_key": "o3", "name_receiving_water": "CREEK (UNKNOWN THE NAME)"}]
    fx["impacts"] += [{"sewer_overflow_bypass_event_key": "o4", "sewer_overflow_bypass_impact_code": "ALB",
                       "sewer_overflow_bypass_impact_desc": "Algal blooms", "sewer_overflow_bypass_impact_other_text": ""}]

    def others(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(fx)
        return sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                      for r in kept + dropped if not str(r.get("npdes_permit") or r.get("permit")).startswith("PR"))
    with_pr, without_pr = others(set(E.STATES)), others(set(E.STATES) - {"PR"})
    assert with_pr == without_pr and len(with_pr) == 4
    dc = json.loads(next(r for r in with_pr if '"o1"' in r))
    assert dc["waterbody_text"] == "unnamed creek"                       # Puerto Rico's no-name rule is its own
    il = json.loads(next(r for r in with_pr if "IL0000001" in r))
    assert il["raw"]["reached_water_rule"] == "text names a water (river)"   # the description is still read there
    ga = json.loads(next(r for r in with_pr if "GA0000001" in r))
    assert ga["reason"] == "no evidence the discharge reached a water"    # ALB is a water impact in Puerto Rico only


def test_main_reads_a_saved_zip_of_puerto_rico_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert E.main(["--file", str(_zip(tmp_path, _fixture()))]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 11 and "PR" in doc["meta"]["states"]
    dropped = json.loads((tmp_path / "echo-sewer-overflow-dropped.json").read_text())
    assert dropped["count"] == 4 and "Juan Ejemplo" not in json.dumps(dropped, ensure_ascii=False)
