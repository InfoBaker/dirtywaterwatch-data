"""Illinois: the Illinois rules of EPA's overflow tables (time zone, no-water wordings, free-text scrub, --file), and
the Illinois feeds (MWRD's Possible CSO Events layer and Lake Michigan reversals table, IDPH BeachGuard). No network:
the tables are built here in EPA's layout with invented values; addresses and names are placeholders."""
import csv
import io
import json
import zipfile
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures"


def _row(**kw):
    base = {"permit_identifier": "IL0000001", "program_report_form_set_id": "1", "program_report_form_id": "1",
            "sewer_overflow_bypass_event_key": "1", "sewer_overflow_bypass_event_id_ext": "1",
            "sewer_overflow_bypass_description_text": "", "sewer_overflow_structure_type_code": "MH",
            "sewer_overflow_structure_type_desc": "Manhole", "sewer_overflow_structure_type_code_other_text": "",
            "collection_system_identifier": "", "permitted_feature_identifier": "", "latitude_measure": "40.10",
            "longitude_measure": "-89.10", "sewer_overflow_bypass_start_datetime": "2026-07-04 19:26:00",
            "sewer_overflow_bypass_end_datetime": "2026-07-04 20:06:00",
            "discharge_quantification_method_desc": "Best Professional Judgement",
            "sewer_overflow_bypass_discharge_volume_gallons": "500", "program_report_received_date": "2026-07-06",
            "program_report_npdes_data_group_number_code": "", "program_report_start_date": "", "program_report_end_date": ""}
    base.update(kw)
    return base


def _tables(rows, waters, types=None, causes=None):
    keys = [r["sewer_overflow_bypass_event_key"] for r in rows]
    return {
        "events": rows,
        "types": [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": (types or {}).get(k, "SSO"),
                   "sewer_overflow_bypass_type_desc": "x", "sewer_overflow_bypass_type_code_sequence": "1"} for k in keys],
        "waters": [{"sewer_overflow_bypass_event_key": k, "name_receiving_water": w} for k, w in waters.items()],
        "causes": causes or [],
    }


def test_illinois_is_read_with_its_own_zone_and_scrub_only():
    assert "IL" in E.STATES and E.STATE_TZ == {"IL": "America/Chicago"} and E.FREE_TEXT_STATES == {"IL"}
    assert "IL" not in E.REPEATED_POINT_STATES          # Illinois points are the event's own (module docstring)


def test_illinois_times_carry_central_offsets_and_other_states_stay_naive():
    assert E.zoned("2026-07-04T19:26:00", "IL") == "2026-07-04T19:26:00-05:00"
    assert E.zoned("2026-01-04T19:26:00", "IL") == "2026-01-04T19:26:00-06:00"
    assert E.zoned("2026-11-01T01:30:00", "IL") == "2026-11-01T01:30:00-05:00"     # the first of the two 1:30s
    assert E.zoned("2026-07-04", "IL") == "2026-07-04"                               # a date stays a date
    assert E.zoned("2026-07-04T19:26:00", "MA") == "2026-07-04T19:26:00"
    kept, _, _ = E.build(_tables([_row(), _row(permit_identifier="MA0000001", sewer_overflow_bypass_event_key="2")],
                                 {"1": "Sample Creek", "2": "Sample Brook"}), {"extract_date": "2026-11-03"})
    by = {r["npdes_permit"]: r for r in kept}
    il = by["IL0000001"]
    assert il["started_at"] == "2026-07-04T19:26:00-05:00" and il["ended_at"] == "2026-07-04T20:06:00-05:00"
    assert "America/Chicago" in il["raw"]["timezone_note"]
    assert by["MA0000001"]["started_at"] == "2026-07-04T19:26:00" and by["MA0000001"]["raw"]["timezone_note"] == E.TZ_NOTE


def test_status_reads_the_illinois_offset_as_central_time():
    from build import status
    assert status.parse_time("2026-07-04T19:26:00-05:00").isoformat().startswith("2026-07-05T00:26")
    assert status.parse_time("2026-07-04T19:26:00").isoformat().startswith("2026-07-04T23:26")   # naive: Eastern


def test_illinois_wordings_that_name_no_water():
    for t in ("LAWN", "We do not expect any overflows ", "None, opposite side of Sample Canal Levee",
              "City of Sampleton Lagoon", "lagoon"):
        assert E.no_water(t, "IL"), t
    for t in ("Sample Creek", "Retention pond", "Unnamed stormwater detention pond", "Crab Orchard Lake",
              "ditch that runs into Sample Lake", "storm drain"):
        assert not E.no_water(t, "IL"), t
    assert not E.no_water("LAWN", "MA") and not E.no_water("City of Sampleton Lagoon", "GA")
    ok, why = E.reached_water({}, ["BYP"], ["We do not expect any overflows"], [], "IL")
    assert not ok and why == "receiving water stated as none"


def test_house_numbers_and_owner_names_never_reach_an_illinois_record():
    rows = [_row(sewer_overflow_bypass_description_text="Force main break at 4521 Sample Prairie Dr. Sampleton",
                 sewer_overflow_structure_type_code="OTH",
                 sewer_overflow_structure_type_code_other_text="Manhole behind 97 Sample Creek Rd. owned by Jane Doe"),
            _row(sewer_overflow_bypass_event_key="2", program_report_form_set_id="2",
                 sewer_overflow_bypass_description_text="SSO at 13230 Sample Ct, call 217-555-0100",
                 permit_identifier="IL0000002")]
    causes = [{"sewer_overflow_bypass_event_key": "1", "sewer_overflow_bypass_cause_code": "OTH",
               "sewer_overflow_bypass_cause_desc": "Other",
               "sewer_overflow_bypass_cause_other_text": "Grease from 719 Sample Ln residence"}]
    kept, _, _ = E.build(_tables(rows, {"1": "Sample Creek", "2": "Sample Creek"}, causes=causes),
                         {"extract_date": "2026-11-03"})
    blob = json.dumps(kept)
    for leak in ("4521", "97 Sample", "Jane", "Doe", "13230", "555-0100", "719"):
        assert leak not in blob, leak
    one = next(r for r in kept if r["npdes_permit"] == "IL0000001")
    assert one["raw"]["sewer_overflow_bypass_description_text"] == ("Force main break at [house number removed] "
                                                                     "Sample Prairie Dr. Sampleton")
    assert "Sample Creek Rd." in one["raw"]["sewer_overflow_structure_type_code_other_text"]
    assert one["raw"]["causes"][0]["other"] == "Grease from [house number removed] Sample Ln residence"
    # outfall and manhole numbers stay
    assert E.scrub_free_text({"t": "MH 006 between Sample and Example streets; CSO 004"}, ["t"])["t"] == (
        "MH 006 between Sample and Example streets; CSO 004")


def test_a_live_states_free_text_is_left_as_it_was():
    kept, _, _ = E.build(_tables([_row(permit_identifier="NH0000001",
                                       sewer_overflow_bypass_description_text="Break at 4521 Sample Prairie Dr.")],
                                 {"1": "Sample Brook"}), {"extract_date": "2026-11-03"})
    assert kept[0]["raw"]["sewer_overflow_bypass_description_text"] == "Break at 4521 Sample Prairie Dr."


def _zip(tmp_path, tables) -> Path:
    p = tmp_path / "sobe.zip"
    with zipfile.ZipFile(p, "w") as z:
        for k, name in E.TABLES.items():
            rows = tables.get(k) or []
            buf = io.StringIO()
            if rows:
                w = csv.DictWriter(buf, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            else:
                buf.write("sewer_overflow_bypass_event_key\n")
            z.writestr(name, buf.getvalue())
    return p


def test_main_reads_a_saved_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    z = _zip(tmp_path, _tables([_row()], {"1": "Sample Creek"}))
    assert E.main(["--file", str(z)]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 1 and doc["meta"]["via"] == "file sobe.zip" and doc["meta"]["last_modified"] is None
    assert doc["records"][0]["started_at"].endswith("-05:00")
