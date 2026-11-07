"""Arizona: the Arizona rules of EPA's overflow tables (pipeline/ingest/echo_sewer_overflow_events.py, module docstring,
Arizona). The fixture holds real Arizona rows of the 2026-11-04 all-versions extract (current version of each report),
with one street number replaced by a placeholder; no network."""
import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures" / "az_sobe_rows.json"


def tables():
    return {k: v for k, v in json.loads(FIX.read_text()).items() if isinstance(v, list)}


def built(t=None):
    return E.build(t or tables(), {"extract_date": "2026-11-04"})


def by_desc(recs, key="raw"):
    return {(r[key].get("sewer_overflow_bypass_description_text") if key == "raw" else r["description"]): r for r in recs}


def test_arizona_is_read_with_its_zone_scrub_and_repeated_points():
    assert "AZ" in E.STATES and E.STATE_TZ["AZ"] == "America/Phoenix"
    assert "AZ" in E.FREE_TEXT_STATES and "AZ" in E.REPEATED_POINT_STATES and E.REPEATED_POINT_ALL_REPORTS == {"AZ"}


def test_kept_and_dropped_rows_by_reason():
    kept, dropped, why = built()
    k = {r["raw"]["sewer_overflow_bypass_description_text"].replace("[house number removed]", "#"):
         r["raw"]["reached_water_rule"] for r in kept}
    assert k == {
        "Pipe ID : 186207": "receiving water named",                                  # UNK_PERNL
        "Manhole ID : 33550": "text names a water (into rid canal)",
        "Lift Station ID : 158022": "receiving water named",                           # four Andorra Wash reports
        "Lift Station ID : 190502": "receiving water named",
        "Lift Station ID : 47048": "receiving water named",
        "Lift Station ID : 48186": "receiving water named",
        "Pipe ID : 90378": "bypass (leaves the plant through its permitted outfall)",
        "Treatment Component ID : 162675": "text names a water (to the corgett wash)",
        "Manhole ID : 112945": "text names a water (to an unnamed wash)",
        "SSO @ # N. 9th Ave": "receiving water named",                                 # Az Canal Diversion Channel
        "Lift Station ID : 23102": "receiving water named",                            # a WBID, Munds Creek
    }
    d = {r["description"]: r["reason"] for r in dropped}
    assert d["Manhole ID : 104839"] == "no evidence the discharge reached a water"   # "did not impact any waterway"
    assert d["Pipe ID : 97623"] == "no evidence the discharge reached a water"       # "did not reach any body of water"
    assert d["Pipe ID : 19774"] == "no evidence the discharge reached a water"       # "Wash with potable water"
    assert d["Manhole ID : 74141"] == "no evidence the discharge reached a water"     # "1/2 mile from the closest dry wash"
    assert d["Other ID : 96431"] == "no evidence the discharge reached a water"      # "dry retention pond"
    assert d["Other ID : 158426"] == "building backup"
    assert sum(n for (s, o, _), n in why.items() if s == "AZ" and o == "kept") == len(kept) == 11
    assert sum(n for (s, o, _), n in why.items() if s == "AZ" and o == "dropped") == len(dropped) == 8


def test_times_are_phoenix_time_all_year():
    kept, _, _ = built()
    r = by_desc(kept)
    assert r["Lift Station ID : 190502"]["started_at"] == "2026-09-16T13:30:00-07:00"     # summer
    assert r["Lift Station ID : 190502"]["ended_at"] == "2026-09-16T14:05:00-07:00"
    assert r["Pipe ID : 90378"]["started_at"].endswith("-07:00")
    assert E.zoned("2026-01-15T08:00:00", "AZ") == "2026-01-15T08:00:00-07:00"           # winter: no daylight time
    assert "America/Phoenix" in r["Pipe ID : 90378"]["raw"]["timezone_note"]
    assert r["Lift Station ID : 190502"]["reported_at"] == "2026-09-17"


def test_receiving_water_codes_become_adeq_names_and_the_filing_is_kept():
    kept, _, _ = built()
    r = by_desc(kept)
    a = r["Lift Station ID : 190502"]
    assert a["waterbody_text"] == "Andorra Wash" and a["raw"]["receiving_waters"] == ["AZ15060106B-8861"]
    assert a["raw"]["receiving_water_aliases"] == {"AZ15060106B-8861": "Andorra Wash"}
    assert a["raw"]["receiving_water_wbids"]["AZ15060106B-8861"]["terminus"] == "Cave Creek"
    assert r["Lift Station ID : 23102"]["waterbody_text"] == "Unnamed Trib to Munds Creek"
    assert next(v for k, v in r.items() if "9th Ave" in k)["waterbody_text"] == "Az Canal Diversion Channel"
    u = r["Pipe ID : 186207"]                                     # a receiving-water entry that names nothing
    assert u["waterbody_text"] is None and u["raw"]["receiving_waters"] == ["UNK_PERNL"]
    assert u["raw"]["receiving_water_aliases"] == {"UNK_PERNL": None}
    assert E.normalise_az_water("AZ99999999-999") == "AZ99999999-999"     # a code ADEQ's layer lacks: as typed


def test_washes_canals_and_denials():
    rw = lambda t, st="AZ": E.reached_water({}, ["SSO"], [], [{"sewer_overflow_bypass_impact_code": "OTH",  # noqa: E731
                                                              "sewer_overflow_bypass_impact_other_text": t}], st)
    for t in ("Some of the SSO entered water flowing through the New River Wash", "Flow went to wash.",
              "Less than 1000 gallons entered Queen Creek Wash.", "SSO flowed into RID canal",
              "The SSO spilled into a Concrete lined canal.", "ran into an arroyo"):
        assert rw(t)[0], t
    for t in ("Wash with potable water into sewer", "Area was power washed and vacuumed",
              "The overflow occurred over 1/2 mile from the closest dry wash.",
              "The SSO did not impact any waterway. It was all contained in a Retention Basin.",
              "The SSO did not reach any body of water.", "The spill stayed on site in a dry retention pond",
              "all effluent was sent to our effluent storage pond", "flowed onto the street and into a drywell"):
        assert not rw(t)[0], t
    assert rw("There are no fish in the water feature pond.")[0]           # a pond that is not the plant's
    assert rw("did not reach the creek but entered the wash")[0]
    # the same texts in another state are read as before
    assert rw("The SSO did not impact any waterway.", "MA")[0]
    assert not rw("Flow went to wash.", "MA")[0] and not rw("SSO flowed into RID canal", "GA")[0]


def test_the_plants_point_is_not_the_spills_but_a_bypass_keeps_it():
    kept, _, _ = built()
    r = by_desc(kept)
    for d in ("Lift Station ID : 158022", "Lift Station ID : 190502", "Lift Station ID : 47048"):
        assert r[d]["lat"] is None and r[d]["raw"]["reported_point"] == [33.80058, -111.98892], d
        assert "different descriptions" in r[d]["raw"]["point_note"]
    g = r["Pipe ID : 90378"]                      # Grand Canyon South Rim: a bypass keeps its point
    assert g["lat"] is not None and g["event_type"] == "bypass" and "reported_point" not in g["raw"]
    assert r["Manhole ID : 112945"]["lat"] is not None                    # Payson: one report at its point here


def test_a_manhole_that_overflows_again_keeps_its_point():
    t = tables()
    base = next(e for e in t["events"] if e["sewer_overflow_bypass_description_text"] == "Manhole ID : 112945")
    for i in range(3):
        e = dict(base, sewer_overflow_bypass_event_key=f"9{i}", program_report_form_set_id=f"X{i}")
        t["events"].append(e)
        t["types"].append({"sewer_overflow_bypass_event_key": f"9{i}", "sewer_overflow_bypass_type_code": "SSO",
                           "sewer_overflow_bypass_type_desc": "Sanitary Sewer Overflow",
                           "sewer_overflow_bypass_type_code_sequence": "1"})
        t["impacts"] += [dict(x, sewer_overflow_bypass_event_key=f"9{i}") for x in t["impacts"]
                         if x["sewer_overflow_bypass_event_key"] == base["sewer_overflow_bypass_event_key"]]
    kept, _, _ = built(t)
    same = [r for r in kept if r["raw"]["sewer_overflow_bypass_description_text"] == "Manhole ID : 112945"]
    assert len(same) == 4 and all(r["lat"] is not None for r in same)


def test_stable_record_ids_and_no_house_number():
    kept, dropped, _ = built()
    for r in kept:
        raw = r["raw"]
        assert r["source_record_id"] == (f"{r['npdes_permit']}:{raw['program_report_form_set_id']}:"
                                         f"{raw['sewer_overflow_bypass_event_id_ext']}")
    again, _, _ = built()
    assert [r["event_id"] for r in kept] == [r["event_id"] for r in again]
    blob = json.dumps(kept)
    assert "4521" not in blob and "[house number removed] N. 9th Ave" in blob


def test_other_states_records_do_not_change():
    """The fixture's rows filed under a New Hampshire and a Georgia permit give the same records whether or not the
    Arizona rules exist (the rules are keyed on AZ only)."""
    def relabel(t, st):
        t = copy.deepcopy(t)
        for name, rows in t.items():
            for r in rows:
                if r.get("permit_identifier", "").startswith("AZ"):
                    r["permit_identifier"] = st + r["permit_identifier"][2:]
        return t
    for st in ("NH", "GA"):
        t = relabel(tables(), st)
        with_az = built(copy.deepcopy(t))
        import pytest
        mp = pytest.MonkeyPatch()
        for name, val in (("STATES", E.STATES - {"AZ"}), ("STATE_TZ", {k: v for k, v in E.STATE_TZ.items() if k != "AZ"}),
                          ("FREE_TEXT_STATES", E.FREE_TEXT_STATES - {"AZ"}),
                          ("REPEATED_POINT_STATES", E.REPEATED_POINT_STATES - {"AZ"}),
                          ("REPEATED_POINT_ALL_REPORTS", set()), ("REPEATED_POINT_MIN_BY_STATE", {}),
                          ("STATE_WATER_TEXT", {}), ("STATE_NOT_WATER_TEXT", {})):
            mp.setattr(E, name, val)
        try:
            without = built(copy.deepcopy(t))
        finally:
            mp.undo()
        strip = lambda recs: json.dumps([{**r, "fetched_at": None} for r in recs], sort_keys=True)  # noqa: E731
        assert strip(with_az[0]) == strip(without[0]) and with_az[1] == without[1] and with_az[2] == without[2], st


def test_main_reads_a_saved_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    t = tables()
    p = tmp_path / "sobe.zip"
    with zipfile.ZipFile(p, "w") as z:
        for k, name in E.TABLES.items():
            rows = t.get(k) or []
            cols = list(dict.fromkeys(c for r in rows for c in r)) or ["sewer_overflow_bypass_event_key"]
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
            z.writestr(name, buf.getvalue())
    assert E.main(["--file", str(p)]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 11 and "AZ" in doc["meta"]["states"]
    assert {r["outcome"]: r for r in doc["meta"]["by_rule"] if r["state"] == "AZ"}
