"""City of Somerville's CSO discharge table (ingest/ma_somerville_cso.py). The page below is invented in the real
page's shape (2026-11-17): its headings, header cells, the ways it writes dates and clocks (7/22/2026 4:25pm,
10/8/25 8:55 AM, 8:15 A.M., 0:55 am, line breaks and non-breaking spaces inside cells, a span around a figure) and a
contacts table after it. Every date, figure, name, address and number is made up. No network."""
from __future__ import annotations

import json
import re
from datetime import datetime

import pytest

from common import read_json, write_json
from ingest import ma_somerville_cso as S

HEAD = ('<tr><td><strong>CSO Number</strong></td><td style="width:15%;"><strong>Waterbody affected</strong></td>'
        '<td style="width:15%;"><strong>Potentially Affected Area</strong></td><td style="width:12%;"><strong>Start Time'
        '</strong></td><td style="width:12%;"><strong>Stop Time</strong></td><td><strong>Duration</strong></td><td>'
        '<strong>Volume (million gallons)</strong></td><td><strong>Event Rainfall (inches)</strong></td></tr>')
AREA = "Arlington, Cambridge, Medford, Somerville"


def tr(start, stop, dur, vol, rain, cso="SOM-001A", water="Alewife Brook"):
    return (f"<tr><td>{cso}</td><td>{water}</td><td>{AREA}</td><td>{start}</td><td>{stop}</td><td>{dur}</td>"
            f"<td>{vol}</td><td>{rain}</td></tr>")


CURRENT = [
    tr("7/12/2026<br>3:25pm", "7/12/2026<br>3:40pm", "15 min", "0.211", "0.71"),
    tr("6/3/2026<br>7:10 PM<br>&nbsp;", "6/3/2026<br>7:15 PM<br>&nbsp;", "5 min", "0.57", "0.33"),
    tr("10/9/25 8:55 AM", "10/9/25 9:35 AM", "40 min", "0.729",
       '<span style="font-family:&quot;Aptos&quot;,sans-serif;font-size:11.0pt;">1.12</span>'),
    tr("9/5/2025&nbsp;<br>6:10 PM", "9/5/2025&nbsp;<br>6:25 PM", "15 min", "0.301", "1.01"),
    tr("2/11/2024<br>3:45 am", "2/11/2024<br>5:35 am", "1 hr 50 min", "2.4", "2.6"),
]
PAST = [
    tr("5/19/2023<br>11:25 pm", "5/20/2023<br>0:55 am", "90 min", "0.91", "1.3"),
    tr("7/28/2023<br>6:15 pm", "7/28/2023<br>8:35 pm", "30 min", "0.12", "2.0"),
    tr("10/13/2022<br>8:15 A.M.", "10/13/2022<br>8:20 A.M.", "5 min", "0.03", "0.8"),
    tr("&nbsp;9/3/2021<br>12:00 A.M.", "9/3/2021<br>6:00am", "360 min", "6.1", "4.1"),
    tr("9/13/2023<br>1:35&nbsp;pm", "9/13/2023<br>1:45 pm", "10 min", "0.035", "0.26"),
]
CONTACTS = ('<table class="table"><tbody><tr><td><br><strong>Pat Example</strong><br>Director of Examples<br>'
            '<a href="mailto:pat.example@example.org">pat.example@example.org</a><br>(555) 010-0199<br>&nbsp;</td></tr>'
            '</tbody></table>')


def page(current=CURRENT, past=PAST, head=HEAD, contacts=CONTACTS):
    return (
        '<html><head><meta name="description" content="CSO Activation Notifications" /></head><body>'
        '<h2 class="jump-link-title">CSO Activation Notifications</h2><div align="center">'
        "<h4>Combined Sewer Overflow (CSO) Event on July 12, 2026 at 3:25 p.m. &nbsp;at&nbsp;SOM-001A on the Alewife "
        'Brook</h4><p><span style="color:#df3114;"><strong>Public Health Warning:&nbsp;</strong> Public health officials '
        "recommend avoiding contact with water bodies during rainstorms and for 48 hours afterwards, as there may be "
        "increased health risks due to bacteria or other pollutants associated with urban stormwater runoff and CSO "
        "discharges.</span></p></div>"
        "<p><strong>Disclaimer: The information is based upon remotely operated equipment and may be subject to change "
        "upon actual observed conditions.</strong></p><h4>CSO Discharge Table</h4><p>The CSO discharge table provides "
        "additional details for current CSO activations and their estimated discharge duration and volume.&nbsp;Data "
        "for CSOs is preliminary and subject to change.</p>"
        f'<table class="table smaller"><tbody>{head}{"".join(current)}</tbody></table>'
        '<div class="has-more js-has-more"><h4 class="has-more--trigger">Past CSO Activations</h4><div>'
        f'<table class="table smaller"><tbody>{head}{"".join(past)}</tbody></table></div></div>'
        f"<h3>Contacts</h3>{contacts}</body></html>")


NOW = "2026-11-17T12:00:00Z"
LATER = "2026-11-17T13:00:00Z"


def run(tmp_path, html=None, now=NOW, portal=None, ctx=None):
    ev = tmp_path / "ev"
    ev.mkdir(exist_ok=True)
    if portal is not None:
        write_json(ev / "ma-massdep.json", {"source_id": "ma-massdep", "records": portal})
    return S.run(page() if html is None else html, now, state_path=tmp_path / "state.json", events_dir=ev,
                 out=ev / f"{S.SOURCE_ID}.json", ctx={} if ctx is None else ctx)


def by_start(recs):
    return {r["started_at"]: r for r in recs}


def portal(eid, outfall, start, published, parent=None, status="ended", permit="MA0101982"):
    return {"event_id": f"ma-massdep:{eid}", "source_record_id": eid, "npdes_permit": permit, "outfall_id": outfall,
            "started_at": start, "published_at": published, "parent_event_id": parent and f"ma-massdep:{parent}",
            "status": status, "duplicate_of": None}


# ---------------------------------------------------------------- the page as written

def test_every_row_of_both_tables_is_read_with_its_times_in_eastern_time(tmp_path):
    code, recs, meta = run(tmp_path)
    assert code == 0 and len(recs) == 10 and meta["tables"] == ["CSO Discharge Table", "Past CSO Activations"]
    r = by_start(recs)
    assert r["2026-07-12T15:25:00-04:00"]["ended_at"] == "2026-07-12T15:40:00-04:00"         # 3:25pm, summer time
    assert r["2026-06-03T19:10:00-04:00"]["ended_at"] == "2026-06-03T19:15:00-04:00"         # <br>&nbsp; after
    assert r["2025-10-09T08:55:00-04:00"]["raw"]["rainfall_in"] == "1.12"                    # two-digit year; span
    assert "2025-09-05T18:10:00-04:00" in r                                                  # &nbsp; before <br>
    assert r["2024-02-11T03:45:00-05:00"]["ended_at"] == "2024-02-11T05:35:00-05:00"         # winter time
    assert r["2024-02-11T03:45:00-05:00"]["raw"]["duration_min"] == 110                      # "1 hr 50 min"
    assert r["2023-05-19T23:25:00-04:00"]["ended_at"] == "2023-05-20T00:55:00-04:00"         # "0:55 am"
    assert r["2022-10-13T08:15:00-04:00"]["ended_at"] == "2022-10-13T08:20:00-04:00"         # "A.M."
    assert r["2021-09-03T00:00:00-04:00"]["ended_at"] == "2021-09-03T06:00:00-04:00"         # 12:00 A.M.; "6:00am"
    assert "2023-09-13T13:35:00-04:00" in r                                                  # "1:35&nbsp;pm"
    one = r["2026-07-12T15:25:00-04:00"]
    assert one["source_record_id"] == "SOM001A:20260712T1525" and one["outfall_id"] == "SOM001A"
    assert (one["event_type"], one["status"], one["time_precision"]) == ("cso", "ended", "minute")
    assert (one["npdes_permit"], one["discharger_id"], one["waterbody_text"]) == ("MA0101982", "ma-somerville", "Alewife Brook")
    assert one["raw"]["row"]["cso_number"] == "SOM-001A" and one["raw"]["row"]["affected_area"] == AREA
    assert one["raw"]["table"] == "CSO Discharge Table" and one["parse_error"] is None
    assert r["2023-07-28T18:15:00-04:00"]["raw"]["table"] == "Past CSO Activations"


def test_volume_is_exact_gallons_and_keeps_the_pages_estimate_wording(tmp_path):
    _, recs, meta = run(tmp_path)
    r = by_start(recs)
    v = r["2026-06-03T19:10:00-04:00"]
    assert v["volume_gal"] == 570000                     # 0.57 x 1e6 in floats is 569,999.99...
    assert v["volume_text"] == "0.57 million gallons" and v["estimate_flag"] == "estimated"
    assert "preliminary and subject to change" in v["raw"]["volume_method"]
    assert "estimated discharge duration and volume" in v["raw"]["volume_method"]
    assert "CSO Discharge Table The" not in v["raw"]["volume_method"]       # a heading never runs into the sentence
    assert meta["estimate_wording"].startswith("The CSO discharge table provides")
    assert r["2021-09-03T00:00:00-04:00"]["volume_gal"] == 6100000


def test_the_pages_health_warning_is_quoted_without_a_window(tmp_path):
    _, recs, _ = run(tmp_path)
    r = recs[0]
    assert r["advice_text"].startswith("Public health officials recommend avoiding contact with water bodies")
    assert r["advice_window_hours"] is None and "rainstorm" in r["advice_window_basis"]


def test_a_duration_that_disagrees_keeps_the_stop_as_written(tmp_path):
    _, recs, _ = run(tmp_path)
    r = by_start(recs)["2023-07-28T18:15:00-04:00"]
    assert r["ended_at"] == "2023-07-28T20:35:00-04:00"
    assert "30 min" in r["raw"]["_duration_check"] and "140 min" in r["raw"]["_duration_check"]
    assert "_duration_check" not in by_start(recs)["2023-05-19T23:25:00-04:00"]["raw"]      # 90 min agrees


def test_a_missing_or_backward_stop_takes_the_duration_and_neither_leaves_no_end(tmp_path):
    rows = [tr("7/12/2026<br>3:25pm", "", "15 min", "0.2", "0.7"),
            tr("6/3/2026<br>7:10 PM", "6/2/2026<br>7:15 PM", "5 min", "0.1", "0.3"),
            tr("5/3/2026<br>7:10 PM", "", "", "0.1", "0.3")]
    _, recs, _ = run(tmp_path, page(current=rows, past=[]))
    r = by_start(recs)
    a = r["2026-07-12T15:25:00-04:00"]
    assert a["ended_at"] == "2026-07-12T15:40:00-04:00" and "duration" in a["raw"]["_ended_at_basis"]
    b = r["2026-06-03T19:10:00-04:00"]
    assert b["ended_at"] == "2026-06-03T19:15:00-04:00" and "before the start" in b["parse_error"]
    c = r["2026-05-03T19:10:00-04:00"]
    assert c["ended_at"] is None and c["status"] == "unknown" and "end not confirmed" in c["raw"]["_end_note"]


@pytest.mark.parametrize("text,want", [
    ("7/22/2026 4:25pm", datetime(2026, 7, 22, 16, 25)), ("10/8/25 8:55 AM", datetime(2025, 10, 8, 8, 55)),
    ("10/14/2022 8:15 A.M.", datetime(2022, 10, 14, 8, 15)), ("9/2/2021 12:00 A.M.", datetime(2021, 9, 2, 0, 0)),
    ("7/31/2024 12:05 PM", datetime(2024, 7, 31, 12, 5)), ("5/21/2023 0:55 am", datetime(2023, 5, 21, 0, 55)),
    ("5/21/2023 13:05", datetime(2023, 5, 21, 13, 5)), ("5/21/2023  1:35 pm", datetime(2023, 5, 21, 13, 35)),
    ("5/21/2023 8:15", None), ("5/21/2023 13:05 pm", None), ("2/30/2024 1:00 pm", None), ("5/21/2023 8:75 am", None),
    ("TBD", None), ("", None),
])
def test_dates_and_clocks(text, want):
    got, why = S.parse_stamp(text)
    assert (got.replace(tzinfo=None) if got else None) == want
    assert (why is None) == (want is not None)


@pytest.mark.parametrize("text,want", [("10 min", 10), ("1 hr 50 min", 110), ("275 min", 275), ("2 hours", 120),
                                       ("1 hour, 5 minutes", 65), ("about an hour", None), ("", None), ("5", None)])
def test_durations(text, want):
    assert S.parse_duration(text) == want


def test_a_placeholder_figure_keeps_its_text_no_gallons_and_is_not_a_failure(tmp_path):
    code, recs, _ = run(tmp_path, page(current=[tr("7/12/2026<br>3:25pm", "", "TBD", "TBD", "")], past=[]))
    r = recs[0]
    assert code == 0 and r["volume_gal"] is None and r["volume_text"] == "TBD" and r["estimate_flag"] == "unknown"
    assert r["parse_error"] is None and r["raw"]["rainfall_in"] is None
    assert r["ended_at"] is None and r["status"] == "unknown"           # no stop and no duration: end not confirmed


def test_an_unreadable_figure_makes_the_read_partial_and_a_held_row_keeps_its_earlier_cells(tmp_path):
    run(tmp_path)
    garbled = [tr("7/12/2026<br>3:25pm", "about four", "a while", "0.2 or so", "0.71")] + CURRENT[1:]
    code, recs, meta = run(tmp_path, page(current=garbled), now=LATER)
    doc = read_json(tmp_path / "ev" / f"{S.SOURCE_ID}.json")
    assert code == 1 and doc["ok"] is False and len(recs) == 10
    assert "CSO Discharge Table row 1: stop time, duration, volume not read" in doc["error"]
    assert "about four" not in doc["error"] and "0.2 or so" in json.dumps(doc["records"])
    r = by_start(recs)["2026-07-12T15:25:00-04:00"]
    assert r["ended_at"] == "2026-07-12T15:40:00-04:00" and r["volume_gal"] == 211000      # the earlier cells
    assert r["raw"]["_unread_version_seen_at"] == LATER
    new = [tr("8/1/2026<br>1:00 pm", "later", "", "0.1", "0.4")]
    code, recs, _ = run(tmp_path, page(current=new + CURRENT), now="2026-11-17T14:00:00Z")
    fresh = by_start(recs)["2026-08-01T13:00:00-04:00"]
    assert code == 1 and fresh["parse_error"] == "stop time not read" and fresh["status"] == "unknown"


def test_placed_by_the_massdep_layer_when_it_is_cached(tmp_path):
    layer = {"SOM001A": {"dep_id": "SOM001A", "npdes": "MA0101982", "outfall": "001A", "lat": 42.4001234,
                         "lon": -71.1301234, "address": "End of Example Road", "receiving_water": "ALEWIFE BROOK"}}
    _, recs, _ = run(tmp_path, ctx={"layer": layer, "echo": {}, "crosswalk": {}, "waters": {}})
    r = recs[0]
    assert (r["lat"], r["lon"], r["coord_source"]) == (42.400123, -71.130123, "outfall_layer")
    assert r["outfall_name"] == "End of Example Road" and "SOM001A" in r["raw"]["_coords"]


# ---------------------------------------------------------------- one event, not two

PORTAL = [
    # 7/12/2026: a notice and its Verified Data Report (the shown record)
    portal("n1", "SOM001A", "2026-07-12T15:25:00-04:00", "2026-07-12T20:00:00-04:00"),
    portal("v1", "SOM001A", "2026-07-12T15:25:00-04:00", "2026-08-10T09:00:00-04:00", parent="n1"),
    # 9/5/2025 filed a day later: not the same overflow by the rule
    portal("v2", "SOM001A", "2025-09-06T18:10:00-04:00", "2025-10-01T09:00:00-04:00"),
    # 6/3/2026 at another outfall, and another permit's SOM001A: never linked
    portal("n3", "SOM007A/MWR205A", "2026-06-03T19:10:00-04:00", "2026-06-03T21:00:00-04:00"),
    portal("n4", "SOM001A", "2026-06-03T19:10:00-04:00", "2026-06-03T21:00:00-04:00", permit="MA0103284"),
    # 2/11/2024, 2 h 30 min from the row
    portal("n5", "SOM001A", "2024-02-11T06:15:00-05:00", "2024-02-11T09:00:00-05:00"),
]


def test_each_row_is_the_duplicate_of_the_portals_shown_record_of_the_same_overflow(tmp_path):
    _, recs, meta = run(tmp_path, portal=PORTAL)
    r = by_start(recs)
    a = r["2026-07-12T15:25:00-04:00"]
    assert a["duplicate_of"] == "ma-massdep:v1"                  # the Verified Data Report, not the replaced notice
    assert "same permit and outfall number, starts 0 min apart" in a["raw"]["_link_basis"]
    assert r["2024-02-11T03:45:00-05:00"]["duplicate_of"] == "ma-massdep:n5"           # within 3 hours
    assert r["2026-06-03T19:10:00-04:00"]["duplicate_of"] is None                      # other outfall, other permit
    late = r["2025-09-05T18:10:00-04:00"]
    assert late["duplicate_of"] is None
    assert late["raw"]["_portal_nearest"]["record"] == "ma-massdep:v2"
    assert late["raw"]["_portal_nearest"]["starts_hours_apart"] == 24.0
    assert r["2021-09-03T00:00:00-04:00"]["duplicate_of"] is None                      # before the portal's first day
    assert "_chain" not in a["raw"]
    assert meta["links"]["linked_to_portal"] == 2 and meta["links"]["standing_alone"] == 8
    assert meta["links"]["near_portal_record"] == 1


def test_two_rows_never_share_one_portal_overflow(tmp_path):
    rows = [tr("7/12/2026<br>3:25pm", "7/12/2026<br>3:40pm", "15 min", "0.2", "0.7"),
            tr("7/12/2026<br>5:05pm", "7/12/2026<br>5:15pm", "10 min", "0.1", "0.7")]
    _, recs, _ = run(tmp_path, page(current=rows, past=[]), portal=PORTAL)
    r = by_start(recs)
    assert r["2026-07-12T15:25:00-04:00"]["duplicate_of"] == "ma-massdep:v1"
    second = r["2026-07-12T17:05:00-04:00"]
    assert second["duplicate_of"] is None and second["raw"]["_portal_nearest"]["record"] == "ma-massdep:v1"


def test_without_the_portal_file_every_row_stands_alone_and_is_shown(tmp_path):
    run(tmp_path, portal=PORTAL)
    (tmp_path / "ev" / "ma-massdep.json").unlink()
    code, recs, meta = run(tmp_path, now=LATER)
    assert code == 0 and not any(r["duplicate_of"] for r in recs)      # never a link to a record the build lacks
    assert "every row stands alone" in meta["links"]["portal"] and meta["links"]["linked_to_portal"] == 0


def test_a_portal_record_marked_duplicate_is_left_out_and_its_family_still_links(tmp_path):
    p = [{**PORTAL[0], "duplicate_of": "ma-massdep:v1"}, PORTAL[1]]
    _, recs, _ = run(tmp_path, portal=p)
    assert by_start(recs)["2026-07-12T15:25:00-04:00"]["duplicate_of"] == "ma-massdep:v1"


# ---------------------------------------------------------------- publication, state and revisions

def test_no_publication_time_is_invented_and_reads_are_kept_as_fetch_times(tmp_path):
    _, recs, _ = run(tmp_path)
    assert all(r["published_at"] is None and r["reported_at"] is None for r in recs)
    assert all(r["fetched_at"] == NOW and r["raw"]["_first_seen_at"] == NOW for r in recs)
    new = tr("11/16/2026<br>9:05 PM", "11/16/2026<br>9:20 PM", "15 min", "0.15", "0.9")
    _, recs, _ = run(tmp_path, page(current=[new] + CURRENT), now=LATER)
    r = by_start(recs)
    fresh = r["2026-11-16T21:05:00-05:00"]
    assert fresh["published_at"] is None
    assert fresh["raw"]["_first_seen_at"] == LATER and fresh["fetched_at"] == LATER
    assert r["2026-07-12T15:25:00-04:00"]["raw"]["_first_seen_at"] == NOW


def test_a_row_taken_off_the_page_stays_and_a_changed_row_keeps_its_earlier_cells(tmp_path):
    run(tmp_path)
    changed = [tr("7/12/2026<br>3:25pm", "7/12/2026<br>3:45pm", "20 min", "0.25", "0.71")] + CURRENT[1:]
    _, recs, meta = run(tmp_path, page(current=changed, past=PAST[:-1]), now=LATER)
    r = by_start(recs)
    assert len(recs) == 10 and meta["missing_from_source"] == 1
    gone = r["2023-09-13T13:35:00-04:00"]
    assert gone["raw"]["_missing_from_source_since"] == LATER and gone["raw"]["_last_seen_in_source"] == NOW
    c = r["2026-07-12T15:25:00-04:00"]
    assert c["volume_gal"] == 250000 and c["ended_at"] == "2026-07-12T15:45:00-04:00"
    assert c["raw"]["revisions"][0]["cells"]["volume_mg"] == "0.211"
    assert c["raw"]["revisions"][0]["last_seen_at"] == NOW
    _, recs, meta = run(tmp_path, now="2026-11-17T14:00:00Z")          # back on the page: no longer missing
    assert "_missing_from_source_since" not in by_start(recs)["2023-09-13T13:35:00-04:00"]["raw"]


def test_a_corrected_start_is_the_same_row_not_a_second_overflow(tmp_path):
    run(tmp_path, portal=PORTAL)
    fixed = [tr("7/12/2026<br>3:26pm", "7/12/2026<br>3:40pm", "15 min", "0.211", "0.71")] + CURRENT[1:]
    _, recs, meta = run(tmp_path, page(current=fixed), now=LATER, portal=PORTAL)
    assert len(recs) == 10 and meta["corrections_joined"] == 1 and meta["missing_from_source"] == 0
    r = by_start(recs)
    assert "2026-07-12T15:25:00-04:00" not in r
    c = r["2026-07-12T15:26:00-04:00"]
    assert c["duplicate_of"] == "ma-massdep:v1" and c["raw"]["_first_seen_at"] == NOW
    assert c["raw"]["revisions"][-1]["key"] == "SOM001A:20260712T1525"


def test_several_candidates_for_a_corrected_start_are_left_apart(tmp_path):
    run(tmp_path)
    two = [tr("7/12/2026<br>3:26pm", "7/12/2026<br>3:40pm", "15 min", "0.211", "0.71"),
           tr("7/13/2026<br>3:25pm", "7/13/2026<br>3:40pm", "15 min", "0.211", "0.71")] + CURRENT[1:]
    _, recs, meta = run(tmp_path, page(current=two), now=LATER)
    assert meta["corrections_joined"] == 0 and len(recs) == 12 and meta["missing_from_source"] == 1
    assert "SOM001A:20260712T1525" in meta["corrections_left_apart"]


def test_a_lost_state_file_is_rebuilt_from_the_previous_events_file(tmp_path):
    run(tmp_path)
    (tmp_path / "state.json").unlink()
    _, recs, meta = run(tmp_path, page(current=CURRENT, past=PAST[:2]), now=LATER)
    assert len(recs) == 10 and "rebuilt from the previous events file" in meta["state_recovered"]
    gone = by_start(recs)["2021-09-03T00:00:00-04:00"]
    assert gone["raw"]["_missing_from_source_since"] == LATER and gone["raw"]["_first_seen_at"] == NOW
    assert by_start(recs)["2026-07-12T15:25:00-04:00"]["raw"]["_first_seen_at"] == NOW


def test_a_repeated_row_is_counted_once(tmp_path):
    _, recs, meta = run(tmp_path, page(current=CURRENT + CURRENT[:1], past=[]))
    assert len(recs) == 5 and meta["repeated_rows"] == 1


# ---------------------------------------------------------------- failures and privacy

def test_a_changed_header_is_a_failed_read_that_keeps_the_previous_records(tmp_path):
    run(tmp_path)
    head = HEAD.replace("Volume (million gallons)", "Volume (gallons)")
    code, _, _ = run(tmp_path, page(head=head), now=LATER)
    doc = read_json(tmp_path / "ev" / f"{S.SOURCE_ID}.json")
    assert code == 1 and doc["ok"] is False and "columns changed" in doc["error"] and doc["count"] == 10


def test_a_header_renamed_in_one_table_only_still_fails_the_read(tmp_path):
    run(tmp_path)
    renamed = page().replace(HEAD, HEAD.replace("Start Time", "Began"), 1)
    code, _, _ = run(tmp_path, renamed, now=LATER)
    doc = read_json(tmp_path / "ev" / f"{S.SOURCE_ID}.json")
    assert code == 1 and doc["ok"] is False and "columns changed" in doc["error"] and doc["count"] == 10


def test_a_table_gone_since_the_last_read_makes_the_read_partial(tmp_path):
    run(tmp_path)
    one = page().split('<div class="has-more')[0] + "</body></html>"
    code, recs, meta = run(tmp_path, one, now=LATER)
    assert code == 1 and len(recs) == 10 and meta["missing_from_source"] == 5
    assert any("'Past CSO Activations' seen at the previous read is not on the page" in u for u in meta["unread"])


def test_a_page_without_the_table_is_a_failed_read(tmp_path):
    code, _, _ = run(tmp_path, "<html><body><h4>CSO Discharge Table</h4><p>Moved.</p>" + CONTACTS + "</body></html>")
    doc = read_json(tmp_path / "ev" / f"{S.SOURCE_ID}.json")
    assert code == 1 and doc["ok"] is False and "no CSO discharge table" in doc["error"]


def test_an_unreadable_row_is_named_and_the_others_are_published(tmp_path):
    bad = [tr("July 12<br>afternoon", "", "", "0.1", "0.5"), tr("7/1/2026<br>1:00 pm", "7/1/2026<br>1:10 pm", "10 min", "0.1",
                                                                    "0.5", cso="Outfall A"),
           '<tr><td colspan="8">Data for 2026 under review</td></tr>']
    code, recs, meta = run(tmp_path, page(current=bad + CURRENT, past=[]))
    doc = read_json(tmp_path / "ev" / f"{S.SOURCE_ID}.json")
    assert code == 1 and doc["ok"] is False and len(recs) == 5 and doc["count"] == 5
    assert "start time not read" in doc["error"] and "CSO number not read" in doc["error"] and "1 cells" in doc["error"]
    assert "Outfall A" not in doc["error"] and "afternoon" not in doc["error"]       # names, never the cells' text
    assert len(meta["unread"]) == 3


def test_a_held_row_that_no_longer_builds_is_named_and_the_rest_are_written(tmp_path):
    run(tmp_path)
    state = read_json(tmp_path / "state.json")
    state["rows"]["SOM001A:20990101T0000"] = {"table": "x", "cells": {"cso_number": "SOM-001A", "start": "garbled"},
                                              "first_seen_at": NOW, "last_seen_at": NOW}
    write_json(tmp_path / "state.json", state)
    code, recs, meta = run(tmp_path, now=LATER)
    assert code == 1 and len(recs) == 10 and any("SOM001A:20990101T0000" in u for u in meta["unread"])


def test_the_contacts_table_is_never_decoded_or_saved(tmp_path, monkeypatch):
    seen = []
    for name in ("cell_text", "page_text"):
        fn = getattr(S, name)
        monkeypatch.setattr(S, name, lambda x, _fn=fn: (seen.append(x), _fn(x))[1])
    run(tmp_path)
    assert seen and any("Pat Example" in x or "example.org" in x for x in seen)
    text = (tmp_path / "ev" / f"{S.SOURCE_ID}.json").read_text() + (tmp_path / "state.json").read_text()
    for s in ("Pat Example", "example.org", "555", "Director"):
        assert s in text


def test_a_contact_inside_a_discharge_cell_is_scrubbed_before_it_is_kept(tmp_path):
    row = tr("7/12/2026<br>3:25pm", "7/12/2026<br>3:40pm", "15 min", "0.2", "0.7",
             water="Alewife Brook, call 617-555-0123 or write pat@example.org")
    run(tmp_path, page(current=[row], past=[]))
    text = (tmp_path / "ev" / f"{S.SOURCE_ID}.json").read_text() + (tmp_path / "state.json").read_text()
    assert "pat@example.org" in text and "555-0123" in text and "[email removed]" not in text


@pytest.mark.parametrize("start,stop,want_end,partial", [
    ("3/8/2026<br>2:30 am", "3/8/2026<br>3:15 am", None, True),                 # the start does not exist: not read
    ("3/8/2026<br>1:30 am", "3/8/2026<br>2:15 am", "2026-03-08T03:00:00-04:00", True),   # the stop does not exist
    ("11/1/2026<br>1:30 am", "11/1/2026<br>1:50 am", "2026-11-01T01:50:00-04:00", False),  # repeated hour: first
])
def test_daylight_time_changes(tmp_path, start, stop, want_end, partial):
    code, recs, _ = run(tmp_path, page(current=[tr(start, stop, "30 min", "0.1", "0.5")], past=[]))
    assert (code == 1) == partial
    if want_end is None:
        assert recs == []
    else:
        assert recs[0]["ended_at"] == want_end


def test_the_events_file_says_what_it_covers(tmp_path):
    run(tmp_path)
    doc = read_json(tmp_path / "ev" / f"{S.SOURCE_ID}.json")
    assert doc["meta"]["covers_permits"] == ["MA0101982"] and doc["meta"]["statewide"] is False
    assert doc["meta"]["registry_ids"] == [S.SOURCE_ID] and doc["meta"]["rows_read"] == 10


# ---------------------------------------------------------------- export detail, registry and channel

def test_the_export_detail_names_the_rows_own_cells(tmp_path):
    from export import detail
    _, recs, _ = run(tmp_path)
    d = detail.detail_of(by_start(recs)["2024-02-11T03:45:00-05:00"])
    assert d == {"rainfall_in": "2.6", "rainfall_label": "Event rainfall", "duration_text": "1 hr 50 min",
                 "volume_qualifier": "estimated"}


def test_the_registry_row_and_the_notice_channel_name_the_feed():
    from common import ROOT
    y = (ROOT / "data" / "sources" / f"{S.SOURCE_ID}.yaml").read_text()
    assert re.search(rf'^id: "{S.SOURCE_ID}"$', y, re.M) and S.URL in y
    rows = json.loads((ROOT / "data" / "notice-channels" / "ma.json").read_text())["channels"]
    row = next(r for r in rows if r["id"] == "ma-somerville-website")
    assert row["unmonitored_reason"] == "feed_ingested" and row["feed_source_id"] == S.SOURCE_ID
    assert "not a feed" not in (ROOT / "pipeline" / "ingest" / "ma_somerville_cso.py").read_text()
    from build import charts
    assert charts.SOURCE_LABEL[S.SOURCE_ID] == "City of Somerville combined sewer overflow table"
    assert "ma_massdep" < "ma_somerville_cso"           # the Makefile's sorted order: the portal file is this run's
