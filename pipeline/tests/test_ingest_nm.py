"""New Mexico: the New Mexico rules of EPA's overflow tables (pipeline/ingest/echo_sewer_overflow_events.py, module
docstring, New Mexico), with the Navajo Nation's reports located in New Mexico. The fixture holds real rows of the
2026-11-04 all-versions extract (current version of each report): every report located in New Mexico and one Navajo
Nation building backup located in Arizona; one street intersection replaced by placeholder names. No network."""
import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

import common
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures" / "nm_sobe_rows.json"
NO_EVIDENCE = "no evidence the discharge reached a water"


@pytest.fixture(autouse=True)
def outlines(monkeypatch):
    """The Census state outlines when a saved copy is at hand; else boxes with the Arizona-New Mexico line at
    109.0462 W, its course at 35.9 N (both place the Navajo, New Mexico lift station in New Mexico)."""
    real = E.navajo_outlines()
    if not real:
        from shapely.geometry import box
        real = {"AZ": box(-115, 31, -109.0462, 37), "NM": box(-109.0462, 31, -103, 37),
                "UT": box(-115, 37, -109.0452, 42), "CO": box(-109.0452, 37, -102, 41)}
    monkeypatch.setattr(E, "_NAVAJO_OUTLINES", real)


def tables():
    return {k: v for k, v in json.loads(FIX.read_text()).items() if isinstance(v, list)}


def built(t=None):
    return E.build(t or tables(), {"extract_date": "2026-11-04"})


def placed(r):
    return r.get("state") or (r.get("raw") or {}).get("state") or (r.get("npdes_permit") or r.get("permit"))[:2]


def test_new_mexico_is_read_with_its_zone_and_scrub():
    assert "NM" in E.STATES and E.STATE_TZ["NM"] == "America/Denver" and "NM" in E.FREE_TEXT_STATES
    assert "NM" not in E.REPEATED_POINT_STATES and E.SIGN_REPAIR_PREFIXES == {"NM", "NN"}
    assert E.PERMIT_TZ["NN"] == E.STATE_TZ["NM"]          # the Navajo Nation's clock is New Mexico's: no split


def test_kept_and_dropped_rows_by_reason():
    kept, dropped, why = built()
    assert [(r["npdes_permit"], r["raw"]["reached_water_rule"], r["waterbody_text"]) for r in kept] == [
        ("NN0020621", "receiving water named", "San Juan River")]          # Shiprock's anticipated bypass
    d = {(x["permit"], x["description"].strip()): (x["reason"], placed(x)) for x in dropped}
    assert d == {
        ("NM0024066", "Private sewer overflow on 2/19/26 from 1:10pm to 1:30pm on First Street and Second Street "
                      "Intersection"): (NO_EVIDENCE, "NM"),
        ("NM0024066", "Manhole overflow caused by debris"): (NO_EVIDENCE, "NM"),
        ("NN0020621", "SSO Reported by Customer"): (NO_EVIDENCE, "NM"),
        ("NN0020621", "Due to power outage at the transformer bank at the WWTP."):
            ("receiving water stated as none", "NM"),                     # 'by passed into emergency lagoon.'
        ("NN0021555", "Rain washed out the 8-inch sewer line."): (NO_EVIDENCE, "NM"),
        # the lift station at Navajo, New Mexico: 48 m east of the state line, 160 m west of the meridian (P2-1)
        ("NN0021555", "Debris stuck in propeller of pump #1 pump #2 didn't come on."): (NO_EVIDENCE, "NM"),
        ("NN0021555", "Power outage in the area causing lift station to trip. Has to be manually reset the automatic "
                      "reset"): (NO_EVIDENCE, "NM"),
        ("NN0020281", "Sewer OF coming from clean out near house trailer."): ("building backup", "AZ"),
    }
    assert why[("NM", "kept", "receiving water named")] == 1
    assert sum(n for (s, o, _), n in why.items() if s == "NM" and o == "dropped") == 7


def test_navajo_nation_reports_in_new_mexico_are_placed_by_their_point():
    kept, dropped, _ = built()
    k = kept[0]
    assert k["raw"]["state"] == "NM" and "Four Corners" in k["raw"]["state_basis"]
    assert k["event_type"] == "bypass" and k["lat"] == 36.786944 and k["lon"] == -108.710833   # the plant's point kept
    assert k["raw"]["sewer_overflow_reporting_requirement_desc"] == "Anticipated bypass notice"
    assert k["reported_at"] == "2024-06-14"                                   # filed the day before it began
    # Window Rock's permit is Arizona's operator, but this report's point lies east of the state line
    wr = [x for x in dropped if x["permit"] == "NN0021555"]
    assert len(wr) == 3 and {x["state"] for x in wr} == {"NM"}
    # without New Mexico in STATES its Navajo Nation reports are skipped, as they were before
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(E, "STATES", E.STATES - {"NM"})
        k2, d2, w2 = built()
    assert k2 == [] and [x["permit"] for x in d2] == ["NN0020281"] and not any(s == "NM" for s, _, _ in w2)


def test_times_are_mountain_time_with_daylight_saving():
    kept, _, _ = built()
    assert kept[0]["started_at"] == "2024-06-15T02:00:00-06:00" and kept[0]["ended_at"] == "2024-06-22T11:00:00-06:00"
    assert "America/Denver" in kept[0]["raw"]["timezone_note"]
    assert E.zoned("2026-02-19T18:10:00", "NM") == "2026-02-19T18:10:00-07:00"          # winter: MST
    assert E.zoned("2026-10-16T16:00:00", "NM") == "2026-10-16T16:00:00-06:00"          # summer: MDT
    assert E.zoned("2026-10-16", "NM") == "2026-10-16"                                  # a date stays a date
    assert "America/Denver" in E.tz_note("NM", "NM0024066") and "the permit's state's zone" in E.tz_note("NM", "NM0024066")


def test_a_longitude_without_its_minus_sign_is_read_as_west():
    t = tables()
    # Shiprock's customer-reported overflow gives 108.666488; with a receiving water named it is kept, at the point
    t["waters"].append({"sewer_overflow_bypass_event_key": "3755", "name_receiving_water": "San Juan River"})
    kept, _, _ = built(t)
    r = next(x for x in kept if x["raw"]["sewer_overflow_bypass_event_key"] == "3755")
    assert r["lon"] == -108.666488 and r["lat"] == 36.784583 and r["raw"]["state"] == "NM"
    assert r["raw"]["reported_longitude"] == "108.666488" and "minus sign" in r["raw"]["coord_note"]
    # a positive longitude whose negative is not in the Four Corners states is kept as filed; other prefixes untouched
    ev = {"latitude_measure": "13.4", "longitude_measure": "144.6"}
    assert E.repair_sign(ev) == (ev, None)
    assert E.repair_sign({"latitude_measure": "36.7", "longitude_measure": "-108.7"})[1] is None


def test_a_basement_backup_is_dropped_and_a_lagoon_entry_is_no_water():
    t = tables()
    backup = next(e for e in t["events"] if "house trailer" in (e.get("sewer_overflow_bypass_description_text") or ""))
    k = backup["sewer_overflow_bypass_event_key"]
    for name in ("events", "types", "impacts", "causes", "actions"):
        for x in t[name]:
            if x.get("sewer_overflow_bypass_event_key") == k:
                x["permit_identifier"] = "NM0024066"          # the same row filed under a New Mexico permit
    _, dropped, _ = built(t)
    assert next(x for x in dropped if x["description"].startswith("Sewer OF"))["reason"] == "building backup"
    assert E.no_water("by passed into emergency lagoon.", "NM") and not E.no_water("San Juan River", "NM")


def test_stable_record_ids():
    kept, _, _ = built()
    raw = kept[0]["raw"]
    assert kept[0]["source_record_id"] == (f"{kept[0]['npdes_permit']}:{raw['program_report_form_set_id']}:"
                                           f"{raw['sewer_overflow_bypass_event_id_ext']}") == "NN0020621:1:1"
    again, _, _ = built()
    assert [r["event_id"] for r in kept] == [r["event_id"] for r in again]


def test_other_states_records_do_not_change():
    """The fixture's rows filed under a New Hampshire and a Georgia permit give the same records whether or not the New
    Mexico rules exist (the rules are keyed on NM, and the sign repair on the NM and NN prefixes)."""
    def relabel(t, st):
        t = copy.deepcopy(t)
        for rows in t.values():
            for r in rows:
                if r.get("permit_identifier", "")[:2] in ("NM", "NN"):
                    r["permit_identifier"] = st + r["permit_identifier"][2:]
        return t
    for st in ("NH", "GA"):
        t = relabel(tables(), st)
        with_nm = built(copy.deepcopy(t))
        with pytest.MonkeyPatch.context() as mp:
            for name, val in (("STATES", E.STATES - {"NM"}),
                              ("STATE_TZ", {k: v for k, v in E.STATE_TZ.items() if k != "NM"}),
                              ("FREE_TEXT_STATES", E.FREE_TEXT_STATES - {"NM"}), ("SIGN_REPAIR_PREFIXES", set()),
                              ("STATE_NO_WATER", {k: v for k, v in E.STATE_NO_WATER.items() if k != "NM"})):
                mp.setattr(E, name, val)
            without = built(copy.deepcopy(t))
        strip = lambda recs: json.dumps([{**r, "fetched_at": None} for r in recs], sort_keys=True)  # noqa: E731
        assert strip(with_nm[0]) == strip(without[0]) and with_nm[1] == without[1] and with_nm[2] == without[2], st


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
    assert doc["count"] == 1 and "NM" in doc["meta"]["states"]
    assert any(r["state"] == "NM" for r in doc["meta"]["by_rule"])


def test_the_state_line_near_navajo_new_mexico_is_the_census_outline_not_the_meridian():
    """Review 2026-11-07 P2-1: the Arizona-New Mexico line runs west of 109.045 W; a point between them is New Mexico's."""
    st, basis = E.navajo_point_place(35.903429, -109.045520)
    assert st == "NM" and "Census" in basis
    assert E.navajo_point_place(35.903429, -109.0470)[0] == "AZ"             # west of the line
    assert E.navajo_point_place(35.73111, -109.036228) == ("NM", E.NAVAJO_BASIS)   # away from the band: the meridian
    with pytest.MonkeyPatch.context() as mp:                                 # no outlines: the meridian, said so
        mp.setattr(E, "_NAVAJO_OUTLINES", {})
        assert E.navajo_point_place(35.903429, -109.045520) == ("AZ", E.NAVAJO_FALLBACK_BASIS)


def test_the_shiprock_bypass_says_why_it_is_shown_despite_the_lagoon():
    """Review 2026-11-07 P2-3: kept on the San Juan River, which the report names, with a note on the lagoon."""
    kept, _, _ = built()
    note = kept[0]["raw"]["kept_note"]
    assert "lagoon" in note and "San Juan River" in note
    assert E.repair_sign({"latitude_measure": "36.7", "longitude_measure": "+108.7"})[0]["longitude_measure"] == "-108.7"
