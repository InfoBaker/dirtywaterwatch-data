"""Conservative reconciliation against DEC's cached workbook.

Real rows stay in memory; fixtures and diagnostics do not copy addresses or narrative.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from ingest import ny_sprtk as M


@pytest.fixture(scope="module")
def workbook_notices():
    path = Path(__file__).resolve().parents[2] / "data/raw/ny-clock-SPRTK_Data.xlsx"
    if not path.exists():
        pytest.skip("cached DEC workbook is not available")
    notices, website, _ = M.notices_from(M.read_workbook(path.read_bytes()))
    for n in notices + website:
        M.parse_notice(n)
    return notices, website


def source_row(rows, tab, row):
    return deepcopy(next(n for n in rows if n["tab"] == tab and n["row"] == row))


def emitted(notices):
    ctx = {"fetched_at": "2026-11-22T20:00:00Z", "echo": {}, "dischargers": {},
           "cso_permits": set(), "place_cache": {}}
    records = []
    for cid, chain in M.build_chains(notices).items():
        parent = None
        for i, n in enumerate(chain):
            r = M.to_record(n, cid, chain, i, parent, ctx)
            records.append(r)
            parent = r["event_id"]
    return records


def test_website_counterpart_uses_stored_day_and_notice_identity(workbook_notices):
    notices, website = workbook_notices
    w = source_row(website, "May _website", 23)
    counterpart = source_row(notices, "May 2021", 31)
    competitor = source_row(notices, "May 2021", 40)
    other_revision = source_row(notices, "May 2021", 32)
    assert M.local_iso(w["p"]["start"]) == "2021-05-04T00:50:00-04:00"
    assert str(counterpart["p"]["start"]) == "2021-05-03"
    kept, dropped = M.website_duplicates([deepcopy(w)], [counterpart])
    assert len(kept) == 0 and dropped == 1
    for unrelated in (competitor, other_revision):
        kept, dropped = M.website_duplicates([deepcopy(w)], [unrelated])
        assert len(kept) == 1 and dropped == 0
        r = emitted(kept)[0]
        assert r["raw"]["_possible_copy_of"]["event_id"] == f"{M.SOURCE_ID}:{unrelated['id']}"
    kept, dropped = M.website_duplicates([deepcopy(w)], [competitor, counterpart, other_revision])
    assert len(kept) == 0 and dropped == 1


def test_website_ambiguous_counterparts_are_kept(workbook_notices):
    notices, website = workbook_notices
    w = source_row(website, "May _website", 23)
    a = source_row(notices, "May 2021", 31)
    b = deepcopy(a)
    b["id"] = b["f"]["notificationId"] = "9999999999999999"
    kept, dropped = M.website_duplicates([w], [a, b])
    assert len(kept) == 1 and dropped == 0
    assert "_possible_copy_of" in list(emitted(kept)[0]["raw"])


def test_website_collision_is_distinct_stable_and_never_self_parent(workbook_notices):
    _, website = workbook_notices
    pair = [source_row(website, "May _website", row) for row in (224, 225)]
    assert {n["id"] for n in pair} == {"r2899a64ec022"}
    kept, dropped = M.website_duplicates(deepcopy(pair), [])
    assert len(kept) == 2 and dropped == 0
    records = emitted(kept)
    assert len({r["event_id"] for r in records}) == len(records)
    assert all(r["parent_event_id"] != r["event_id"] for r in records)
    ids = {n["row"]: n["id"] for n in kept}
    reverse, _ = M.website_duplicates(list(reversed(deepcopy(pair))), [])
    assert {n["row"]: n["id"] for n in reverse} == ids
    moved = deepcopy(pair)
    for n in moved:
        n["row"] += 1000
        n["tab_index"] += 1
    again, _ = M.website_duplicates(moved, [])
    assert [n["id"] for n in again] == [ids[224], ids[225]]


def test_website_exact_repeat_is_reconciled_before_chaining(workbook_notices):
    _, website = workbook_notices
    w = source_row(website, "May _website", 224)
    repeated = deepcopy(w)
    repeated["row"] += 1000
    kept, dropped = M.website_duplicates([w, repeated], [])
    assert len(kept) == 1 and dropped == 1
    assert kept[0]["id"] == "r2899a64ec022"


def test_colliding_website_rows_reconcile_with_their_own_notice_kind(workbook_notices):
    notices, website = workbook_notices
    pair = [source_row(website, "May _website", row) for row in (224, 225)]
    counterparts = [source_row(notices, "May 2021", row) for row in (231, 232)]
    # Row 224 has no UPDATE prefix; row 225 does. Their counterparts appear in reverse order.
    for w, counterpart in zip(pair, reversed(counterparts)):
        kept, dropped = M.website_duplicates([deepcopy(w)], [counterpart])
        assert len(kept) == 0 and dropped == 1
    kept, dropped = M.website_duplicates(deepcopy(pair), counterparts)
    assert len(kept) == 0 and dropped == 2
    all_kept, _ = M.website_duplicates(deepcopy(pair), [])
    partial, dropped = M.website_duplicates(deepcopy(pair), counterparts[:1])
    assert dropped == 1 and len(partial) == 1
    assert partial[0]["id"] == all_kept[0]["id"]


def sample_pair():
    """Small invented rows exercise the matcher even without the cached workbook."""
    ns, ws, _ = M.notices_from([
        {"tab": "May _website", "rows": [{
            "sprtk id": "NY0999999", "start time": "44319.9", "headline": "Example discharge",
            "col8": "Example outfall", "affected water body": "Example River", "duration": "6",
            "units": "Minutes", "quantity": "10", "col15": "Gallons", "estimated indicator": "Estimated",
        }]},
        {"tab": "May 2021", "rows": [{
            "Notification ID": "999999999999", "POTW/POSS ID": "NY0999999",
            "Discharge Start Date": "2021-05-03", "Notification Status": "New",
            "Street Name": "Example outfall", "Receiving Water Body": "Example River",
            "Duration": "6 Minutes - Ended", "Quantity/Volume": "10 Gallons Estimated",
        }]},
    ])
    for n in ns + ws:
        M.parse_notice(n)
    return ns, ws


@pytest.mark.parametrize("field,value", [
    ("startDateTime", "2021-05-04"), ("streetName", "Other outfall"),
    ("receivingWaterBody", "Other River"), ("duration", "7 Minutes - Ended"),
    ("quantity", "11 Gallons Estimated"), ("notificationStatus", "Update"),
])
def test_same_facility_and_date_never_override_conflicting_identity(field, value):
    ns, ws = sample_pair()
    kept, dropped = M.website_duplicates(deepcopy(ws), ns)
    assert len(kept) == 0 and dropped == 1
    ns[0]["f"][field] = value
    M.parse_notice(ns[0])
    kept, dropped = M.website_duplicates(ws, ns)
    assert len(kept) == 1 and dropped == 0
    assert "_possible_copy_of" in list(emitted(kept)[0]["raw"])


def test_distinct_website_notices_cannot_both_claim_one_counterpart():
    ns, ws = sample_pair()
    other = deepcopy(ws[0])
    other["f"]["headline"] = "Another discharge notice"
    other["row_raw"]["headline"] = other["f"]["headline"]
    kept, dropped = M.website_duplicates([ws[0], other], ns)
    assert len(kept) == 2 and dropped == 0
    assert len({n["id"] for n in kept}) == 2
    assert all(n.get("possible_copy_of") for n in kept)


@pytest.mark.parametrize("with_counterparts", [False, True])
@pytest.mark.parametrize("indexed_previous", [False, True])
def test_main_repairs_previously_emitted_collision_even_outside_window(
        workbook_notices, monkeypatch, with_counterparts, indexed_previous):
    notices, website = workbook_notices
    pair = [source_row(website, "May _website", row) for row in (224, 225)]
    old = emitted(deepcopy(pair))
    legacy = old[0]["event_id"]
    assert old[1]["parent_event_id"] == legacy
    # The existing file may contain both bad rows, or the last one after indexing by ID.
    unique = deepcopy(old[0])
    unique.update(event_id=f"{M.SOURCE_ID}:already-unique", source_record_id="already-unique")
    previous = (old[-1:] if indexed_previous else old) + [unique]
    tabs = [{"tab": "May _website", "rows": [n["row_raw"] for n in pair]}]
    if with_counterparts:
        tabs.append({"tab": "May 2021", "rows": [
            source_row(notices, "May 2021", row)["row_raw"] for row in (231, 232)]})
    monkeypatch.setattr(M, "fetch_workbook", lambda *a: (b"", {"via": "file"}))
    monkeypatch.setattr(M, "read_workbook", lambda *a: tabs)
    monkeypatch.setattr(M, "load_dischargers", lambda: ({}, set()))
    monkeypatch.setattr(M, "load_echo", lambda: {})
    monkeypatch.setattr(M, "read_json", lambda *a: {"records": previous})
    captured = []
    monkeypatch.setattr(M, "write_events", lambda sid, records, **kw: captured.extend(records))
    assert M.main(["--since", "1"]) == 0
    assert len(captured) == 3
    assert len({r["event_id"] for r in captured}) == 3
    assert all(r["parent_event_id"] != r["event_id"] for r in captured)
    assert legacy not in {r["event_id"] for r in captured}
    assert unique["event_id"] in {r["event_id"] for r in captured}
    if with_counterparts:
        assert {r["source_record_id"] for r in captured} == {
            "1032995469272951", "1033682664039349", "already-unique"}


def test_main_preserves_published_unique_copy_id_and_links_counterpart(workbook_notices, monkeypatch):
    notices, website = workbook_notices
    w = source_row(website, "May _website", 23)
    counterpart = source_row(notices, "May 2021", 31)
    previous = emitted([w])
    original_id = previous[0]["event_id"]
    tabs = [{"tab": n["tab"], "rows": [n["row_raw"]]} for n in (w, counterpart)]
    monkeypatch.setattr(M, "fetch_workbook", lambda *a: (b"", {"via": "file"}))
    monkeypatch.setattr(M, "read_workbook", lambda *a: tabs)
    monkeypatch.setattr(M, "load_dischargers", lambda: ({}, set()))
    monkeypatch.setattr(M, "load_echo", lambda: {})
    monkeypatch.setattr(M, "read_json", lambda *a: {"records": previous})
    captured = []
    monkeypatch.setattr(M, "write_events", lambda sid, records, **kw: captured.extend(records))
    assert M.main(["--since", "1"]) == 0
    assert len(captured) == 2
    by_id = {r["event_id"]: r for r in captured}
    assert by_id[original_id]["duplicate_of"] == f"{M.SOURCE_ID}:{counterpart['id']}"
    assert by_id[original_id]["duplicate_of"] in by_id
    assert "_missing_from_workbook_since" not in list(by_id[original_id]["raw"])
    # If the source later ceases to establish identity, the old confirmed-copy link must
    # not suppress the preserved page. Recompute the possible-copy marker outside the window.
    tabs[1]["rows"][0]["Discharge Start Date"] = "2021-05-04"
    prior = list(captured)
    captured.clear()
    monkeypatch.setattr(M, "read_json", lambda *a: {"records": prior})
    assert M.main(["--since", "1"]) == 0
    preserved = next(r for r in captured if r["event_id"] == original_id)
    assert not preserved.get("duplicate_of")
    assert "_possible_copy_of" in list(preserved["raw"])


def test_workbook_emitted_ids_are_unique_and_existing_unique_ids_stay(workbook_notices, monkeypatch):
    # Identity/chaining is the subject here; full placement is checked by the backfill audit.
    monkeypatch.setattr(M, "place", lambda *a: {"slugs": [], "match": "none", "note": {}})
    notices, website = deepcopy(workbook_notices)
    old_counts = Counter(n["id"] for n in notices + website)
    old_ids = {(n["tab"], n["row"]): n["id"] for n in notices + website}
    kept, _ = M.website_duplicates(website, notices)
    for n in notices + kept:
        old = old_ids[n["tab"], n["row"]]
        if old_counts[old] == 1:
            assert n["id"] == old
    records = emitted(notices + kept)
    assert len(records) == len({r["event_id"] for r in records})
    assert all(r["event_id"] != r["parent_event_id"] for r in records)
