"""Older computed ends keep their times and status, but their provenance is ours.

Use the ingesters' existing fixtures, with explicit variants for missing source ends.
"""
import copy
import csv
from datetime import date
from pathlib import Path

import pytest

from export import csv as C, detail as D, estimates as E
from ingest import ri_ridoh_beaches as R, va_deq_prep as V
from test_event_detail import springfield
from test_ingest_ia import waterloo, at_minute
from test_ingest_md import build, row
from test_ingest_tn_memphis_cd import recs as memphis
from test_ingest_va import _api, REFS
from test_ma_somerville_cso import run, page, tr


def ours(e, *words):
    before = copy.deepcopy(e)
    label = E.ended_at_ours_of(e)
    assert label is not None
    assert label["basis"].startswith("We ")
    for word in words:
        assert word in label["basis"]
    assert label["basis_short"]
    assert e == before
    # End-only readers must not introduce new arithmetic or volume estimates.
    assert E.estimates_of(e) == {"ended_at_ours": label}
    D.enrich([e])
    assert e["ended_at_ours"] == label
    for key in ("started_at", "ended_at", "status", "time_precision"):
        assert e.get(key) == before.get(key)
    context = C._Context([], [], {}, C.SiteLinks([e], [], [], set()))
    exported = dict(zip(C.COLUMNS, C.event_row(e, context)[0]))
    assert exported["end_reported"] == "false"
    assert exported["end_estimate_at"] == before["ended_at"]
    assert exported["end_estimate_basis"] == label["basis"]
    assert E.ended_at_ours_of({**before, "ended_at": None}) is None
    assert E.estimates_of({**before, "ended_at": None}) == {}
    assert E.ended_at_ours_of({**before, "source_id": "unmapped-source"}) is None
    assert E.ended_at_ours_of({**before, "raw": {}}) is None
    return label


@pytest.mark.parametrize("which", [0, 1, 2], ids=["notice", "ceased-update", "verified-report"])
def test_massdep_verified_duration_and_borrowed_ends(which):
    records = springfield()
    # This older linking fixture predates the ingester's own-end provenance field.
    records[2]["raw"]["_ended_at_basis"] = (
        "computed: started_at + verified duration 6 h 35 min (Verified Data Report)")
    e = records[which]
    label = ours(e, "Verified Data Report", "start", "duration")
    if which != 2:
        assert "26019001" in label["basis"]
        assert "report's start" in label["basis"]  # not the notice's different start
    else:
        assert "6 hours, 35 minutes" in label["basis"]


@pytest.mark.parametrize("parent", [False, True])
def test_massdep_covering_period_is_left_for_a_wording_decision(parent):
    e = springfield()[0]
    basis = "end of the verified period of 26019001 that covers this notice"
    e["raw"]["_ended_at_basis"] = f"parent notice's verified end ({basis})" if parent else basis
    assert E.ended_at_ours_of(e) is None


def test_massdep_parent_can_carry_a_verified_reports_direct_calculation():
    e = springfield()[1]
    e["raw"]["_ended_at_basis"] = ("parent notice's verified end (computed: started_at + verified duration "
                                   "6 h 35 min (Verified Data Report))")
    ours(e, "Verified Data Report", "6 hours, 35 minutes", "parent notice")


@pytest.mark.parametrize("clock", ["02:05:00", ""])
def test_maryland_duration_uses_the_record_precision(clock):
    records, _ = build([row(start_time=clock, overflow_address="East Preston St")])
    e = next(iter(records.values()))
    label = ours(e, "2 hours, 45 minutes")
    assert ("last day" in label["basis"]) == (clock == "")


def test_virginia_only_the_duration_fallback_is_ours():
    e = V.to_record(V.from_api(_api(id="324738", siteAddress1=None)), REFS, None, "2026-11-02T12:00:00Z")
    ours(e, "14 hours", "sewage report")
    # Even a stale computed marker must not override the source's own end field.
    e["raw"]["report"]["incident_end"] = "2026-08-05T09:16:57"
    assert E.ended_at_ours_of(e) is None
    e["raw"]["_ended_at_basis"] = "incidentEndDateTime"
    assert E.ended_at_ours_of(e) is None


def test_somerville_duration_fallback_and_stated_stop(tmp_path):
    # Existing real July 12 table row, with its stop blanked to exercise the fallback.
    html = page(current=[tr("7/12/2026 3:25pm", "", "15 min", "0.211", "0.71")], past=[], contacts="")
    _, records, _ = run(tmp_path, html=html)
    ours(records[0], "15 minutes", "table")
    records[0]["raw"]["_ended_at_basis"] = "the table's stop time"
    assert E.ended_at_ours_of(records[0]) is None


def test_waterloo_duration_and_explicit_stopped_time():
    records, _ = waterloo()
    ours(at_minute(records, "2026-10-01T0552"), "10 hours, 5 minutes", "notice")
    assert E.ended_at_ours_of(at_minute(records, "2025-10-23T1100")) is None


def test_memphis_is_the_last_day_allowed_even_with_a_start_time():
    _, records = memphis("q2_2026", "2026Q2", ["2026-04-01", "2026-06-30"])
    e = records["2026-04-27T0300PM:PATERD"]
    assert e["time_precision"] == "minute" and e["raw"]["ended_at_precision"] == "day"
    ours(e, "23 hours, 30 minutes", "last day", "estimated duration")


def test_rhode_island_duration_only_when_reopened_is_blank():
    path = Path(__file__).parent / "fixtures" / "ri_ridoh_beaches_current_2026-11-16.csv"
    with path.open() as f:
        cells = next(csv.DictReader(f))
    item = {"sheet": "history", "row": 2, "cells": cells}
    # Existing row as a finished season; its stated reopening must win.
    e = R.row_to_record(item, R.PAGE_URL, [], date(2027, 1, 1), "2027-01-01T12:00:00Z")
    assert E.ended_at_ours_of(e) is None
    cells["Re-Opened"] = ""
    e = R.row_to_record(item, R.PAGE_URL, [], date(2027, 1, 1), "2027-01-01T12:00:00Z")
    ours(e, "1 day", "closure date")
