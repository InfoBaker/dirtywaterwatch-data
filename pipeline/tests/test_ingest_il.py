"""Illinois: the Illinois rules of EPA's overflow tables (time zone, no-water wordings, free-text scrub, --file), and
the Illinois feeds (MWRD's Possible CSO Events layer and Lake Michigan reversals table, IDPH BeachGuard). No network:
the tables are built here in EPA's layout with invented values; addresses and names are placeholders."""
import csv
import io
import json
import re
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
    # review 2026-11-04: a letter o typed for a zero and a range of numbers are house numbers too; dates stay
    sc = lambda t: E.scrub_free_text({"t": t}, ["t"])["t"]  # noqa: E731
    assert sc("Manhole near 45o1 24th St") == "Manhole near [house number removed] 24th St"
    assert sc("611-615 Sample backup") == "[house number removed] Sample backup"
    assert sc("5oo block of S. Sample") == "500 block of S. Sample"
    assert sc("6/22-26 Rain event") == "6/22-26 Rain event" and sc("07-28-25") == "07-28-25"


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


# ---------------------------------------------------------------- MWRD Possible CSO Events

def _layer():
    return json.loads((FIX / "il_mwrd_possible_cso.json").read_text())


def test_possible_cso_layer_rows_become_dated_unconfirmed_records(tmp_path, monkeypatch):
    from ingest import il_mwrd_possible_cso as P
    monkeypatch.setattr(P, "registry_rows", lambda: [
        {"npdes_permit": "IL0045012", "outfall": "001", "lat": 42.0002, "lon": -87.7001,
         "receiving_water_echo": "NORTH SHORE CHANNEL", "water_slug": "north-shore-channel-il"}])
    recs, meta = P.run(_layer(), "2026-07-04T22:00:00Z", tmp_path / "state.json")
    by = {r["outfall_name"]: r for r in recs}
    a = by["Sample Ave (E)"]
    assert a["event_type"] == "cso" and a["status"] == "unknown" and a["ended_at"] is None
    assert a["started_at"] == "2026-07-04T21:26:19Z" and a["time_precision"] == "poll"
    assert a["npdes_permit"] == "IL0045012" and a["outfall_id"] == "001" and a["water_slugs"] == ["north-shore-channel-il"]
    assert a["source_record_id"].endswith(":2026-07-04") and "at or before" in a["raw"]["start_basis"] \
        and "observed, not when the overflow began" in a["raw"]["start_basis"]
    w = by["Wilmette Gate"]
    assert w["waterbody_text"] == "Lake Michigan" and w["raw"]["diversion"].startswith("Wilmette")
    c = by["Example St (W)"]   # no edit time: our first poll, said so; no permit known for the owner
    assert c["started_at"] == "2026-07-04T22:00:00Z" and "first poll" in c["raw"]["start_basis"] and c["npdes_permit"] is None
    assert meta["features_now"] == 3
    blob = json.dumps(recs) + (tmp_path / "state.json").read_text()
    assert "jdoe" not in blob and "Jane Doe" not in blob and "GlobalID" not in blob   # only the safe fields are kept


def test_possible_cso_records_continue_leave_and_reopen_next_day(tmp_path):
    from ingest import il_mwrd_possible_cso as P
    st = tmp_path / "state.json"
    doc = _layer()
    P.run(doc, "2026-07-04T22:00:00Z", st)
    recs, meta = P.run(doc, "2026-07-04T23:00:00Z", st)
    assert len(recs) == 3 and meta["poll"]["continued"] == 3
    empty = dict(doc, features=[])
    recs, meta = P.run(empty, "2026-07-05T06:00:00Z", st)     # the nightly reset: no end is written
    assert meta["poll"]["left"] == 3 and all(r["raw"]["left_layer_at"] == "2026-07-05T06:00:00Z" for r in recs)
    assert all(r["ended_at"] is None and r["status"] == "unknown" for r in recs)
    nxt = json.loads(json.dumps(doc))
    nxt["features"] = [nxt["features"][0]]
    nxt["features"][0]["attributes"]["last_edited_date"] = 1783290000000            # 2026-07-05 22:20 UTC
    recs, meta = P.run(nxt, "2026-07-05T23:00:00Z", st)
    assert meta["poll"]["opened"] == 1 and len(recs) == 4
    assert sum(r["outfall_name"] == "Sample Ave (E)" for r in recs) == 2


def test_possible_cso_file_replay_needs_out(tmp_path):
    from ingest import il_mwrd_possible_cso as P
    out = tmp_path / "ev.json"
    assert P.main(["--file", str(FIX / "il_mwrd_possible_cso.json"), "--out", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["count"] == 3 and (tmp_path / "ev.state.json").exists()


# ---------------------------------------------------------------- MWRD reversals to Lake Michigan

def test_reversal_rows_become_one_record_per_structure_with_days_only():
    from ingest import il_mwrd_lake_reversals as R
    recs, meta = R.build((FIX / "il_mwrd_lake_reversals.txt").read_text(), "2026-02-04T14:30:51Z")
    by = {r["source_record_id"]: r for r in recs}
    a = by["2023-07-02-crcw"]
    assert a["started_at"] == "2023-07-02" and a["ended_at"] == "2023-07-03" and a["time_precision"] == "day"
    assert a["status"] == "ended" and a["event_type"] == "cso" and a["waterbody_text"] == "Lake Michigan"
    assert a["volume_gal"] == 911_800_000 and a["raw"]["diversion"] == "Chicago River Controlling Works"
    assert by["2023-07-02-wilmette"]["volume_gal"] == 230_800_000
    assert by["2013-04-18-o-brien-lock"]["volume_gal"] == 3_185_600_000                     # three structures
    assert by["2019-10-03-wilmette"]["ended_at"] == "2019-10-03"                           # one day: that day
    assert by["1998-12-31-wilmette"]["ended_at"] == "1999-01-01"                           # into the next year
    assert 2025 in meta["years_without_reversal"] and 2023 not in meta["years_without_reversal"]
    assert a["source_updated_at"] == "2026-02-04T14:30:51Z" and a["published_at"] is None
    bad = by["1997-08-16-crcw"]                                                             # 559.0, not 600.0
    assert bad["parse_error"] and "do not add up" in bad["parse_error"] and meta["problems"]


def test_a_reversal_table_without_its_header_fails_the_run(tmp_path):
    from ingest import il_mwrd_lake_reversals as R
    t = tmp_path / "x.txt"
    t.write_text("Reversals to Lake Michigan\n 2023  7/2-7/3   911.8\n")
    out = tmp_path / "ev.json"
    assert R.main(["--text", str(t), "--out", str(out)]) == 1
    assert json.loads(out.read_text())["ok"] is False


# ---------------------------------------------------------------- IDPH BeachGuard

BG = FIX / "il_idph_beachguard"


def _bg_details():
    from ingest import il_idph_beachguard as B
    return {p.stem: B.parse_detail(p.read_text()) for p in BG.glob("*.html")}


def test_beachguard_items_and_pages_become_dated_advisories():
    from ingest import il_idph_beachguard as B
    state = {}
    recs, meta = B.run(state, (BG / "rss.xml").read_bytes(), _bg_details(), "2026-11-04T12:00:00Z")
    by = {r["source_record_id"]: r for r in recs}
    c = by["467-20260901T0800"]
    assert c["event_type"] == "beach_closure" and c["status"] == "advisory_active"
    assert c["started_at"] == "2026-09-01T08:00:00-05:00" and c["time_precision"] == "minute"
    assert c["waterbody_text"] == "Deep Lake" and (c["lat"], c["lon"]) == (42.41633, -88.06466)
    assert c["authority"].startswith("Lake County Health Department") and c["published_at"] is None
    a = by["273-20260904T0800"]
    assert a["event_type"] == "beach_advisory" and a["raw"]["advisory_type"] == "Contamination Advisory"
    o = by["247-nostart"]                                   # the page shows none: kept, undated, said so
    assert o["started_at"] is None and o["raw"]["closure_kind"].startswith("closed by") and "showed no advisory" in o["raw"]["start_basis"]
    assert o["waterbody_text"] is None                       # a bare "Lake" names no water
    blob = json.dumps(recs) + json.dumps(state)
    assert "Jane" not in blob and "555-0199" not in blob and "jdoe@" not in blob and "555-0100" not in blob


def test_beachguard_advisory_lifts_when_the_feed_stops_listing_it():
    from ingest import il_idph_beachguard as B
    state = {}
    rss = (BG / "rss.xml").read_text()
    B.run(state, rss, _bg_details(), "2026-11-04T12:00:00Z")
    fewer = re.sub(r"<item><title>Closure - Deep Lake.*?</item>", "", rss)
    recs, meta = B.run(state, fewer, _bg_details(), "2026-11-04T13:00:00Z")
    c = {r["source_record_id"]: r for r in recs}["467-20260901T0800"]
    assert c["status"] == "advisory_lifted" and c["ended_at"] == "2026-11-04T13:00:00Z"
    assert c["raw"]["lift_observed_between"] == ["2026-11-04T12:00:00Z", "2026-11-04T13:00:00Z"]
    assert meta["poll"]["lifted"] == 1


def test_beachguard_replay_from_saved_files(tmp_path):
    from ingest import il_idph_beachguard as B
    out = tmp_path / "ev.json"
    assert B.main(["--rss", str(BG / "rss.xml"), "--detail-dir", str(BG), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["count"] == 3


def test_beachguard_an_advisory_the_feed_still_lists_stays_in_effect_however_old_its_start():
    """Review 2026-11-04: each poll that lists an advisory re-confirms it (source_updated_at), so the status build's
    14-day ageing counts from the last listing, not from a start two months back."""
    from datetime import UTC, datetime
    from build import status as S
    from ingest import il_idph_beachguard as B
    state = {}
    recs, _ = B.run(state, (BG / "rss.xml").read_bytes(), _bg_details(), "2026-11-04T12:00:00Z")
    c = {r["source_record_id"]: r for r in recs}["467-20260901T0800"]
    assert c["source_updated_at"] == "2026-11-04T12:00:00Z"
    now = datetime(2026, 11, 4, 13, tzinfo=UTC)
    ivs = S.event_intervals(c, "IL", now)
    live = [iv for iv in ivs if iv["rule"] == "advisory_active"]
    assert live and S.parse_time(live[0]["end"]) > now        # before the fix it ended 2026-09-15: aged out


def test_beachguard_an_empty_feed_lifts_nothing_until_the_next_poll_is_empty_too():
    from ingest import il_idph_beachguard as B
    state = {}
    rss = (BG / "rss.xml").read_text()
    empty = re.sub(r"<item>.*</item>", "", rss, flags=re.S)
    B.run(state, rss, _bg_details(), "2026-11-04T12:00:00Z")
    recs, meta = B.run(state, empty, _bg_details(), "2026-11-04T13:00:00Z")
    assert meta["poll"]["lifted"] == 0 and meta["poll"]["held"] == 3
    assert all(r["status"] == "advisory_active" for r in recs)
    recs, meta = B.run(state, rss, _bg_details(), "2026-11-04T14:00:00Z")     # back: nothing was lifted
    assert meta["poll"]["lifted"] == 0 and all(r["status"] == "advisory_active" for r in recs)
    B.run(state, empty, _bg_details(), "2026-11-04T15:00:00Z")
    recs, meta = B.run(state, empty, _bg_details(), "2026-11-04T16:00:00Z")   # empty twice: lifted at the first
    c = {r["source_record_id"]: r for r in recs}["467-20260901T0800"]
    assert meta["poll"]["lifted"] == 3 and c["status"] == "advisory_lifted" and c["ended_at"] == "2026-11-04T15:00:00Z"
