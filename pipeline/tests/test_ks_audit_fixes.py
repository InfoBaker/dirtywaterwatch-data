"""Kansas go-live audit fixes (2026-11-15), on invented data: the hand-entered KDHE release (P1-1), the widened title
matcher (P2-1), the Kill Creek Park Lake alias (P2-2) and Kansas in EPA's shared overflow feed (P2-5)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ingest import echo_sewer_overflow_events as E
from ingest import ks_kdhe_stream_advisories as A
from tests.test_ingest_ks import ROOT, _feed, _line, _mo_ks_build

HAND = {"release": "9001", "url": "https://www.kdhe.ks.gov/CivicAlerts.aspx?aid=9001", "title": None,
        "published": "2026-06-25", "entered": "2026-11-15", "entered_from": "the release as indexed",
        "county": "Scott County", "waters": ["Example Creek", "Example Lake"], "cause": "livestock waste"}


# ------------------------------------------------------------------------------------------------ P1-1 hand entry

def test_a_hand_row_opens_an_advisory_at_day_precision_cited_and_marked_by_hand():
    recs, st = A.run(_feed(), [], "2026-11-15T18:00:00Z", [HAND])
    assert len(recs) == 2 and st["hand_entered_open"] == 2 and st["open"] == 2
    r = {x["waterbody_text"]: x for x in recs}["Example Lake"]
    assert r["status"] == "advisory_active" and r["event_type"] == "beach_advisory"
    assert r["started_at"] == "2026-06-25" and r["time_precision"] == "day" and r["ended_at"] is None
    assert r["source_url"] == HAND["url"] and r["raw"]["hand_entry"]["release"] == "9001"
    assert "read by hand on 2026-11-15" in r["raw"]["start_basis"]
    assert r["raw"]["county"] == "Scott County" and r["raw"]["time_zone"] == "America/Chicago"
    assert r["raw"]["_last_seen_in_source"] == "2026-11-15T18:00:00Z"


def test_a_feed_run_without_the_release_does_not_age_it_out(tmp_path):
    recs, _ = A.run(_feed(), [], "2026-11-15T18:00:00Z", [HAND])
    later, st = A.run(_feed(), recs, "2026-12-30T18:00:00Z", [HAND])
    assert st["open"] == 2 and all(r["raw"]["_last_seen_in_source"] == "2026-12-30T18:00:00Z" for r in later)
    waters = dict([_line("example-creek-ks", "Example Creek", "KS", [[-100.9, 38.6], [-100.85, 38.65]])])
    st = _mo_ks_build(tmp_path, {A.SOURCE_ID: later}, waters, now="2026-12-30T19:00:00Z")
    red = [p for p in st["advisory_points"] if p["event_id"].startswith(A.SOURCE_ID) and p["status"] == "red"]
    assert [p["event_id"] for p in red] == [f"{A.SOURCE_ID}:9001-examplecreek"]


def test_a_later_feed_rescission_lifts_it_in_its_county_only():
    recs, _ = A.run(_feed(), [], "2026-11-15T18:00:00Z", [HAND])
    other = ("Stream Advisory Rescinded for Example Creek in Shawnee County", "9100", "Mon, 16 Nov 2026 09:00:00 -0600",
             "Rescinded.")
    kept, _ = A.run(_feed(other), recs, "2026-11-16T18:00:00Z", [HAND])
    assert all(r["status"] == "advisory_active" for r in kept)
    lift = ("Stream and Lake Advisory Rescinded for Example Creek and Example Lake in Scott County", "9101",
            "Mon, 16 Nov 2026 09:00:00 -0600", "Rescinded.")
    out, st = A.run(_feed(lift), kept, "2026-11-16T18:00:00Z", [HAND])
    assert st["open"] == 0 and {r["ended_at"] for r in out} == {"2026-11-16T09:00:00-06:00"}
    again, st = A.run(_feed(), out, "2026-11-17T18:00:00Z", [HAND])       # the hand row never reopens it
    assert st["open"] == 0 and len(again) == 2


def test_a_rescission_entered_in_the_row_lifts_it_at_its_day():
    row = {**HAND, "rescission": {"date": "2026-11-20", "url": "https://www.kdhe.ks.gov/CivicAlerts.aspx?aid=9200"}}
    out, st = A.run(_feed(), [], "2026-11-21T18:00:00Z", [row])
    assert st["open"] == 0 and {r["ended_at"] for r in out} == {"2026-11-20"}
    assert all(r["raw"]["ended_at_precision"] == "day" for r in out)


def test_the_real_hand_file_holds_the_scott_county_release_and_a_bare_day():
    rows = A.hand_rows()
    assert [r["release"] for r in rows] == ["2004"]
    recs = [x for r in rows for x in A.hand_records(r)]
    assert {r["waterbody_text"] for r in recs} == {"Ladder Creek", "Scott Lake"}
    assert {r["started_at"] for r in recs} == {"2026-06-25"} and {r["time_precision"] for r in recs} == {"day"}
    aliases = json.loads((ROOT / "data" / "water-aliases.json").read_text())
    assert "Scott Lake" in aliases["scott-state-fishing-lake-ks"]


# ------------------------------------------------------------------------------------------------ P2-1 titles

def test_the_stream_and_lake_lake_and_regional_wordings_are_read():
    assert A.kind("Stream and Lake Advisory Issued for Ladder Creek and Lake Scott in Scott County") == (
        "issue", ["Ladder Creek", "Lake Scott"], "Scott County")
    assert A.kind("KDHE Issues Stream and Lake Advisory for Example Creek in Scott County")[0] == "issue"
    assert A.kind("Lake Advisory Issued for Example Lake in Butler County") == ("issue", ["Example Lake"],
                                                                                "Butler County")
    assert A.kind("Stream and Lake Advisory Rescinded for Ladder Creek in Scott County")[0] == "lift"
    assert A.kind("KDHE Issues Regional Advisory for Flooded Waterways in Southeast Kansas")[0] == "regional"
    assert A.kind("KDHE Rescinds Regional Advisory for Flooded Waterways")[0] == "regional_lift"
    assert A.kind("Stream Advisory Issued for Example Creek in Shawnee County")[0] == "issue"     # unchanged


def test_a_regional_advisory_is_listed_with_its_counties_never_on_a_water_and_lifted_by_its_rescission(tmp_path):
    reg = ("KDHE Issues Regional Advisory for Flooded Waterways", "9300", "Fri, 26 Jun 2026 15:00:00 -0500",
           "KDHE advises avoiding contact with flooded waterways in Allen, Bourbon and Neosho Counties after sewage "
           "bypasses.")
    other = ("Boil Water Advisory Issued for Example City", "9301", "Fri, 26 Jun 2026 16:00:00 -0500", "Boil.")
    new = ("Example Advisory Issued for Example Creek", "9302", "Fri, 26 Jun 2026 17:00:00 -0500", "New wording.")
    recs, st = A.run(_feed(reg, other, new), [], "2026-06-27T18:00:00Z")
    assert st["regional_issues"] == 1 and len(recs) == 1
    r = recs[0]
    assert r["waterbody_text"] is None and r["raw"]["advisory_extent"] == "regional"
    assert r["raw"]["counties"] == ["Allen County", "Bourbon County", "Neosho County"] and r["raw"]["cause"] == "sewage"
    assert st["unread_advisory_titles"] == ["Example Advisory Issued for Example Creek"]
    waters = dict([_line("example-creek-ks", "Example Creek", "KS", [[-95.3, 37.8], [-95.2, 37.85]])])
    built = _mo_ks_build(tmp_path, {A.SOURCE_ID: recs}, waters, now="2026-06-27T19:00:00Z")
    assert built["waters"].get("example-creek-ks", {}).get("status") != "red"
    assert f"{A.SOURCE_ID}:9300" in json.dumps(built["unplaced_events"])
    assert not [p for p in built["advisory_points"] if p["event_id"].startswith(A.SOURCE_ID)]
    lift = ("KDHE Rescinds Regional Advisory for Flooded Waterways", "9310", "Mon, 27 Jul 2026 10:00:00 -0500", "Lifted.")
    out, st = A.run(_feed(lift), recs, "2026-07-27T18:00:00Z")
    assert st["open"] == 0 and out[0]["ended_at"] == "2026-07-27T10:00:00-05:00"


# ------------------------------------------------------------------------------------------------ P2-2 Kill Creek

def test_kill_creek_park_lake_is_placed_on_the_lake_not_the_creek(tmp_path):
    from build import status as S
    from ingest import ks_kdhe_hab as H
    lake = {"slug": "kill-creek-lake-ks", "name": "Kill Creek Lake", "kind": "reservoir", "state": "KS",
            "bbox": [-94.975, 38.93, -94.965, 38.94],
            "geometry": {"type": "Polygon", "coordinates": [[[-94.975, 38.93], [-94.965, 38.93], [-94.965, 38.94],
                                                             [-94.975, 38.94], [-94.975, 38.93]]]}}
    waters = dict([_line("kill-creek-ks", "Kill Creek", "KS", [[-94.99, 38.90], [-94.96, 38.99]], kind="stream"),
                   ("kill-creek-lake-ks", lake)])
    S.apply_water_aliases(waters, ROOT / "data" / "water-aliases.json")
    assert "Kill Creek Park Lake" in waters["kill-creek-lake-ks"]["aliases"]
    rec = {"event_id": f"{H.SOURCE_ID}:x", "source_id": H.SOURCE_ID, "event_type": "hab_advisory",
           "status": "advisory_active", "waterbody_text": "Kill Creek Park Lake", "lat": 38.944, "lon": -94.97,
           "coord_source": "source", "coord_precision_m": 100, "started_at": "2026-11-15T12:00:00Z",
           "time_precision": "poll", "authority": "KDHE", "source_url": "https://example.invalid/hab",
           "raw": {"state": "KS", "waterbody_id": "1", "kdhe_level": "Warning",
                   "_last_seen_in_source": "2026-11-15T12:00:00Z"}}
    st = _mo_ks_build(tmp_path, {H.SOURCE_ID: [rec]}, waters, now="2026-11-15T13:00:00Z")
    assert st["waters"]["kill-creek-lake-ks"]["status"] == "red"
    assert st["waters"].get("kill-creek-ks", {}).get("status") != "red"


# ------------------------------------------------------------------------------------------------ P2-5 EPA feed

def test_kansas_is_read_on_central_time_with_its_four_mountain_counties():
    assert "KS" in E.STATES and E.STATE_TZ["KS"] == "America/Chicago" and "KS" in E.FREE_TEXT_STATES
    assert E.POINT_ZONE_FILES["KS"] == "ks-mountain-time-counties.json"
    zone, basis = E.point_zone("KS", 39.35, -101.7)          # Goodland, Sherman County
    assert zone == "America/Denver" and "Sherman County" in basis
    zone, basis = E.point_zone("KS", 39.05, -95.68)          # Topeka
    assert zone == "America/Chicago" and "four Mountain-time counties" in basis
    assert E.point_zone("KS", 38.48, -100.9)[0] == "America/Chicago"    # Scott City, east of the line


def test_adding_kansas_changes_no_other_states_record(monkeypatch):
    from tests.test_ingest_dc import _row
    from tests.test_ingest_in import _fixture, _build
    fx = _fixture()
    rows = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
            _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                 sewer_overflow_bypass_description_text="Operator Jane Example reported a break at a manhole."),
            _row(sewer_overflow_bypass_event_key="k1", permit_identifier="KS0000001", program_report_form_set_id="3",
                 latitude_measure="39.35", longitude_measure="-101.70",
                 sewer_overflow_bypass_description_text="Manhole overflow to Example Creek.")]
    fx["events"] += rows
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": "SSO",
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k in ("o1", "o2", "k1")]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": k, "name_receiving_water": w}
                     for k, w in (("o1", "Rock Creek"), ("o2", "Sample Creek"), ("k1", "Example Creek"))]

    def build(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(copy.deepcopy(fx))
        return kept, sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                            for r in kept + dropped
                            if not str(r.get("npdes_permit") or r.get("permit")).startswith("KS"))
    (kept, with_ks), (_, without_ks) = build(set(E.STATES)), build(set(E.STATES) - {"KS"})
    assert with_ks == without_ks and len(with_ks) >= 3
    ks = [r for r in kept if str(r.get("npdes_permit")).startswith("KS")]
    assert len(ks) == 1 and "Sherman County" in ks[0]["raw"]["timezone_note"]
