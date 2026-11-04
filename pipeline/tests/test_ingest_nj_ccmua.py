"""Camden County MUA CSO Status page: the status block and the open / continue / close / reappear
state machine (no network)."""
import json
import pytest
from pathlib import Path

from ingest import nj_ccmua as M

RAW = Path(__file__).resolve().parents[2] / "research" / "nj" / "raw"
_SAVED_PATH = RAW / "ccmua-wp-page-13694.json"
if not _SAVED_PATH.exists():   # research/*/raw/ is git-ignored: the sample is only on the machine that fetched it
    pytest.skip("research/nj/raw/ccmua-wp-page-13694.json is not on this clone (git-ignored raw sample)", allow_module_level=True)
SAVED = json.loads(_SAVED_PATH.read_text())["content"]["rendered"]


def page(word):
    return SAVED.replace("<b>CLOSED</b> and discharges are unlikely", f"<b>{word}</b> and discharges are likely")


def test_parse_saved_page_and_variants():
    r = M.parse_status(SAVED)
    assert r["status"] == "closed" and r["word"] == "CLOSED" and r["block_found"]
    assert r["sentence"].startswith("The 32nd Street CSO permitted outfall 040A") and "Press F5" not in r["sentence"]
    assert r["sentence"].endswith("is CLOSED and discharges are unlikely to be occurring.")
    assert r["icon"].endswith("gate-icon[1].png") and r["static_text"].startswith("The 32nd Street CSO")
    # the block decides, not the fixed rich-text paragraph above it
    o = M.parse_status(page("OPEN"))
    assert o["status"] == "open" and "CLOSED" in o["static_text"]
    assert M.parse_status(page("UNDER MAINTENANCE"))["status"] == "unreadable"
    gone = M.parse_status(SAVED.replace('class="post-entry"', 'class="something-else"'))
    assert gone["status"] == "unreadable" and not gone["block_found"]


def recs(st):
    return {k: M.to_record(k, ev, {"lat": 39.965, "lon": -75.091, "water_slugs": ["delaware-river-nj"],
                                   "water_match": "outfall_registry"}) for k, ev in st["events"].items()}


def test_open_continue_close_reappear():
    closed, opened = M.parse_status(SAVED), M.parse_status(page("OPEN"))
    st = {}
    M.step(st, closed, "2026-11-03T12:17:00Z")
    M.step(st, closed, "2026-11-03T13:17:00Z")
    assert st["events"] == {} and st["readings"] == [
        {"status": "closed", "word": "CLOSED", "first": "2026-11-03T12:17:00Z", "last": "2026-11-03T13:17:00Z",
         "polls": 2, "sentence": closed["sentence"]}]
    # open: the first poll that reads OPEN
    M.step(st, opened, "2026-11-03T14:17:00Z")
    (key, ev), = st["events"].items()
    assert key == "040A-20261103T0917" and st["open"] == key
    r = recs(st)[key]
    assert r["status"] == "ongoing" and r["started_at"] == "2026-11-03T09:17:00-05:00" and r["ended_at"] is None
    assert r["time_precision"] == "poll" and r["raw"]["started_after"] == "2026-11-03T13:17:00Z"
    assert "not a measured or reported discharge" in r["raw"]["status_basis"]
    assert r["npdes_permit"] == "NJ0026182" and r["outfall_id"] == "040A" and r["water_slugs"] == ["delaware-river-nj"]
    # continue
    M.step(st, opened, "2026-11-03T15:17:00Z")
    assert len(st["events"]) == 1 and ev["last_open_at"] == "2026-11-03T15:17:00Z"
    # close: the first poll that reads CLOSED
    M.step(st, closed, "2026-11-03T16:17:00Z")
    r = recs(st)[key]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-03T11:17:00-05:00"
    assert r["raw"]["ended_after"] == "2026-11-03T15:17:00Z" and "open" not in st
    M.step(st, closed, "2026-11-03T17:17:00Z")
    assert len(st["events"]) == 1
    # reappear: a new event
    M.step(st, opened, "2026-11-03T18:17:00Z")
    assert len(st["events"]) == 2 and st["open"] != key
    assert st["events"][st["open"]]["started_after"] == "2026-11-03T17:17:00Z"
    assert [x["status"] for x in st["readings"]] == ["closed", "open", "closed", "open"]


def test_unreadable_page_leaves_an_open_event_unknown():
    closed, opened = M.parse_status(SAVED), M.parse_status(page("OPEN"))
    odd = M.parse_status(page("UNDER MAINTENANCE"))
    st = {}
    M.step(st, odd, "2026-11-03T12:17:00Z")
    assert st["events"] == {}                                   # never an event by itself
    M.step(st, opened, "2026-11-03T13:17:00Z")
    (key, ev), = st["events"].items()
    M.step(st, odd, "2026-11-03T14:17:00Z")
    assert recs(st)[key]["status"] == "unknown" and recs(st)[key]["raw"]["unreadable_since"] == "2026-11-03T14:17:00Z"
    M.step(st, opened, "2026-11-03T15:17:00Z")                 # read again: the same event continues
    assert len(st["events"]) == 1 and ev["state"] == "ongoing" and ev["resumed"][0]["after"] == "unknown"
    M.step(st, closed, "2026-11-03T16:17:00Z")
    assert recs(st)[key]["status"] == "ended" and recs(st)[key]["ended_at"] == "2026-11-03T11:17:00-05:00"
