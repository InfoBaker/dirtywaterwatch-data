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
    assert sorted(kept) == ["MS0020117:1:1", "MS0022381:1:1", "MS0024295:1:1", "MS0024295:5:1", "MS0044059:10:1",
                            "MS0045446:10:18", "MS0061191:1:1"]
    assert {k: d["reason"] for k, d in dropped.items()} == {
        "MS0024163:1:1": "building backup",                                   # sewage backup in a building
        "MS0036111:2:1": "receiving water stated as none",                    # a bypass whose water is 'None'
        "MS0024848:1:1": "no evidence the discharge reached a water",         # the one CSO-typed row: no water named
        "MS0020184:1:1": "no evidence the discharge reached a water"}         # an SSO naming no water
    assert why[("MS", "kept", "receiving water named")] == 7


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
    eu = next(r for r in kept.values() if r["raw"]["receiving_waters"] == ["EUBANKS"])
    assert eu["waterbody_text"] == "Eubanks Creek" and eu["raw"]["receiving_water_aliases"] == {"EUBANKS": "Eubanks Creek"}
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
    for n in ("1391", "4049", "4625"):
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
    assert doc["count"] == 7 and doc["meta"]["dropped"] == 4
    assert {"state": "MS", "outcome": "dropped", "reason": "building backup", "count": 1} in doc["meta"]["by_rule"]
