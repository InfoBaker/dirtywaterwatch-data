"""A row a source's list still shows as ongoing (data/rules.json unresolved.listed_ongoing; owner, 2026-11-16, "go with
recommendations"): the San Diego Water Board's table lists transboundary flows in the Tijuana River as ongoing since
2023-10-11. Red for the ongoing rule's 7 days, as for any ongoing report; then end not confirmed (hatched) for as long
as the last successful read of the table lists the row as ongoing, past the usual 30 days. A row that gets an end is an
ended report; one that leaves the table with no end gets the usual 30 days counted from the last read that listed it,
then the usual note. Asserts what a visitor sees: the colour and the words at a time.

Run from pipeline/: python -m pytest tests/test_listed_ongoing.py -q
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402

RULES = S.load_rules()
ABSENT = copy.deepcopy(RULES)
ABSENT["unresolved"].pop("listed_ongoing")
OFF = copy.deepcopy(RULES)
OFF["unresolved"]["listed_ongoing"]["enabled"] = False
SID = "ca-sd-regional-board-ibwc-spills"
D = timedelta(days=1)
START = datetime(2023, 10, 11, 7, tzinfo=UTC)        # the bare date 2023-10-11, midnight Pacific (PDT)
READ = datetime(2026, 11, 16, 22, 32, 4, tzinfo=UTC)  # the last read that listed the row


def z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def health(ok=True) -> dict:
    """The events file's header and page date, as load_events attaches them (_feed_health)."""
    return {"fetched_at": z(READ + timedelta(hours=7 if not ok else 0)), "ok": ok,
            "last_ok_at": z(READ + timedelta(seconds=3)), "prev_ok_at": z(READ - 6 * D),
            "page_last_updated": "2026-05-27"}


def row(sid=SID, **over) -> dict:
    """The Tijuana River row as the ingester writes it (ingest/ca_sd_tijuana_table.py)."""
    raw = {"time_zone": "America/Los_Angeles", "event_kinds": ["river_transboundary_flow"], **over.pop("raw", {})}
    return {"event_id": f"{sid}:2023-10-11-tijuana-river-d4f6be1856", "source_id": sid, "event_type": "sso",
            "status": "ongoing", "started_at": "2023-10-11", "ended_at": None, "time_precision": "day",
            "fetched_at": z(READ), "authority": "San Diego Regional Water Quality Control Board (table of events USIBWC "
            "reported)", "source_url": "https://www.waterboards.ca.gov/x.html", "raw": raw,
            "_feed_health": health(), **over}


def ivs(ev, t, rules=RULES):
    return S.event_intervals(ev, "CA", t, None, rules)


def seen(ev, t, rules=RULES):
    return S.status_at(ivs(ev, t, rules), t)


def todays(ev, t):
    """Today's output: the rule absent."""
    return ivs(ev, t, ABSENT)


def test_listed_ongoing_past_30_days_is_end_not_confirmed_now_with_both_dates():
    t = READ + timedelta(hours=1)
    c, act = seen(row(), t)
    assert c == "unresolved"
    (iv,) = act
    assert iv["rule"] == "listed_ongoing" and iv["color"] == "unresolved"
    assert iv["start"] == START + 7 * D and iv["end"] is None
    assert iv["label"] == ("Listed as ongoing by the San Diego Regional Water Quality Control Board (page last updated "
                           "May 27, 2026; last read Nov 16, 2026): end not confirmed")
    ra = iv["rule_applied"]
    # source time and fetch time kept apart; no end invented
    assert ra["rule"] == "unresolved.listed_ongoing" and ra["source"] == "data/rules.json"
    assert ra["rationale"] == RULES["unresolved"]["listed_ongoing"]["rationale"]
    assert ra["page_last_updated"] == "2026-05-27" and ra["last_listed_at"] == z(READ)
    assert ra["source_unread_since"] is False and "last_attempt_at" not in ra
    assert all(i["ended_at"] is None for i in ivs(row(), t))
    # today the same record sets no colour (the 30-day cap from 2023)
    assert seen(row(), t, ABSENT)[0] == "grey"
    # the short status line names the rule and the start with its year
    assert S.short_reason(iv, row()) == ("Sewer overflow of Oct 11, 2023: listed as ongoing by its source, end not "
                                         "confirmed · San Diego Regional Water Quality Control Board (table of events "
                                         "USIBWC reported)")


def test_red_for_its_first_7_days_as_today():
    s = datetime(2026, 11, 10, 8, tzinfo=UTC)          # 2026-11-10, midnight PST
    ev = row(started_at="2026-11-10", fetched_at=z(s + 2 * D))
    for days in (0.5, 3, 6.9):
        t = s + days * D
        assert seen(ev, t)[0] == "red"
        assert seen(ev, t) == seen(ev, t, ABSENT)
    first = ivs(ev, s + D)[0]
    assert first == todays(ev, s + D)[0]                # the same red interval and rule record as today
    assert seen(ev, s + 8 * D)[0] == "unresolved"
    assert seen(ev, s + 8 * D)[1][0]["rule"] == "listed_ongoing"


def test_a_row_with_an_end_is_an_ended_report_as_today():
    ev = row(status="ended", ended_at="2026-11-01", raw={"ended_at_precision": "day"})
    for t in (datetime(2026, 11, 2, tzinfo=UTC), READ):
        assert ivs(ev, t) == todays(ev, t)
    assert all(i["rule"] != "listed_ongoing" for i in ivs(ev, READ))


def test_a_row_with_a_blank_end_is_unknown_and_untouched():
    ev = row(status="unknown")
    assert ivs(ev, READ) == todays(ev, READ)


def test_a_row_that_left_the_table_gets_30_days_from_the_last_listing_then_the_note():
    gone = READ + 6 * D                               # first read that no longer showed it
    ev = row(raw={"_missing_from_table_since": z(gone)}, _feed_health={**health(), "last_ok_at": z(gone)})
    out = ivs(ev, gone)
    assert [i["rule"] for i in out] == ["ongoing", "listed_ongoing", "unresolved", "end_never_reported"]
    lo, un, note = out[1], out[2], out[3]
    assert (lo["start"], lo["end"]) == (START + 7 * D, READ)
    assert (un["start"], un["end"]) == (READ, READ + 30 * D)
    assert (note["start"], note["end"]) == (READ + 30 * D, READ + S.NOTE_DAYS * D)
    assert un["label"] == lo["label"] == ("Listed as ongoing by the San Diego Regional Water Quality Control Board at "
                                          "our read of Nov 16, 2026; the row has since left the list with no end")
    assert un["rule_applied"]["rule"] == "unresolved.listed_ongoing"
    assert un["rule_applied"]["last_listed_at"] == z(READ)
    assert un["rule_applied"]["missing_from_list_since"] == z(gone)
    assert "page_last_updated" not in un["rule_applied"]   # the page date on file is a later read's
    assert seen(ev, READ + 29 * D)[0] == "unresolved"
    c, act = seen(ev, READ + 31 * D)
    assert c == "grey" and [i["rule"] for i in act] == ["end_never_reported"]
    assert seen(ev, READ + (S.NOTE_DAYS + 1) * D) == ("grey", [])


def test_the_table_cannot_be_read_the_last_read_stands_with_its_date():
    ev = row(_feed_health=health(ok=False))
    for t in (READ + 2 * D, READ + 90 * D):
        c, (iv,) = seen(ev, t)
        assert c == "unresolved" and iv["rule"] == "listed_ongoing" and iv["end"] is None
        assert iv["label"] == ("Listed as ongoing by the San Diego Regional Water Quality Control Board (page last "
                               "updated May 27, 2026; last read Nov 16, 2026, not readable since): end not confirmed")
        assert iv["rule_applied"]["source_unread_since"] is True
        assert iv["rule_applied"]["last_listed_at"] == z(READ)
        assert iv["rule_applied"]["last_attempt_at"] == z(READ + timedelta(hours=7))


def test_no_page_date_on_file_names_the_read_only():
    h = {k: v for k, v in health().items() if k != "page_last_updated"}
    (iv,) = seen(row(_feed_health=h), READ)[1]
    assert iv["label"] == ("Listed as ongoing by the San Diego Regional Water Quality Control Board (last read Nov 16, "
                           "2026): end not confirmed")
    assert iv["rule_applied"]["page_last_updated"] is None


def test_rule_absent_and_rule_off_give_todays_output_exactly():
    for t in (START + 3 * D, START + 20 * D, START + 60 * D, READ):
        for ev in (row(), row(_feed_health=health(ok=False)), row(raw={"_missing_from_table_since": z(READ)})):
            assert ivs(ev, t, OFF) == ivs(ev, t, ABSENT)
            # today's rule: red 7 days, end not confirmed to day 30, the note to day 90
            assert [(i["rule"], i["start"], i["end"]) for i in ivs(ev, t, ABSENT)] == [
                ("ongoing", START, START + 7 * D), ("unresolved", START + 7 * D, START + 30 * D),
                ("end_never_reported", START + 30 * D, START + 90 * D)]


def test_an_ongoing_record_of_another_source_is_untouched():
    ev = row(sid="ca-swrcb-ciwqs-spills")
    for t in (START + 3 * D, START + 20 * D, READ):
        assert ivs(ev, t) == todays(ev, t)
    assert seen(ev, READ)[0] == "grey"


def test_the_history_strip_reads_it_as_unresolved():
    t = READ
    h0 = t - S.HISTORY_DAYS * D
    strip = S.paint(ivs(row(), t), h0, t, S.HISTORY_DAYS * 24)
    assert set(strip) == {"u"}
    assert set(S.paint(ivs(row(), t, ABSENT), h0, t, S.HISTORY_DAYS * 24)) == {"g"}


def _world(tmp_path, ev):
    """A one-water world: the record placed on a lake (filled whole, so its status shows in the counts)."""
    d = tmp_path / "events"
    d.mkdir()
    rec = {k: v for k, v in ev.items() if k != "_feed_health"}
    rec["water_slugs"] = ["test-lake-ca"]
    rec["water_match"] = "name"
    (d / f"{SID}.json").write_text(json.dumps({
        "source_id": SID, "ok": True, "fetched_at": z(READ), "last_ok_at": z(READ), "prev_ok_at": z(READ - 6 * D),
        "meta": {"page_last_updated": "2026-05-27"}, "count": 1, "records": [rec]}))
    waters = {"test-lake-ca": {"name": "Test Lake", "kind": "lake", "state": "CA", "area_km2": 1.0,
                               "bbox": [-117.2, 32.5, -117.1, 32.6]}}
    return d, waters


def _build(d, waters, rules):
    r = copy.deepcopy(rules)
    r["rain_likely"] = {**r.get("rain_likely", {}), "enabled": False}
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    return S.build(now=READ + timedelta(hours=1), write=False, events_dir=d, waters=waters, outfalls=[], registry={},
                   reaches={}, flows=({}, {}), rules=r, placement_cache=False)


def test_the_build_counts_and_lists_it_as_unresolved(tmp_path):
    d, waters = _world(tmp_path, row())
    st, hist = _build(d, waters, RULES)
    w = st["waters"]["test-lake-ca"]
    assert w["status"] == "unresolved"
    assert w["unresolved_events"] == [row()["event_id"]]
    assert w["reasons"][0]["rule"] == "listed_ongoing"
    assert w["reasons"][0]["rule_applied"]["page_last_updated"] == "2026-05-27"   # from the file's meta
    assert st["counts"]["waters"]["CA"].get("unresolved") == 1
    strip = json.dumps(hist)
    assert "u" * 24 in strip
    st0, _ = _build(d, waters, ABSENT)
    w0 = st0["waters"]["test-lake-ca"]
    assert w0["status"] == "grey" and w0["unresolved_events"] == []    # today: nothing since 2024 (the note's 90 days)
    assert st0["counts"]["waters"]["CA"].get("unresolved") is None


def test_page_date_rides_only_on_feeds_whose_meta_has_it(tmp_path):
    d, _ = _world(tmp_path, row())
    other = d / "x-feed.json"
    other.write_text(json.dumps({"source_id": "x-feed", "ok": True, "fetched_at": z(READ), "last_ok_at": z(READ),
                                 "meta": {}, "count": 1, "records": [{"event_id": "x-feed:1", "source_id": "x-feed"}]}))
    _, evs, _ = S.load_events(d)
    by = {e["event_id"]: e for e in evs}
    assert by[row()["event_id"]]["_feed_health"]["page_last_updated"] == "2026-05-27"
    assert by["x-feed:1"]["_feed_health"] == {"fetched_at": z(READ), "ok": True, "last_ok_at": z(READ)}
    # the page date is not part of the record (record_hash leaves feed health out)
    a = dict(by[row()["event_id"]])
    b = {**a, "_feed_health": {}}
    assert S.record_hash(a) == S.record_hash(b)


# ---------------------------------------------------------------- review 2026-11-16 (Astra) findings


def test_the_note_after_the_row_left_the_table_never_says_the_discharge_ended():
    gone = READ + 6 * D
    ev = row(raw={"_missing_from_table_since": z(gone)})
    note = [i for i in ivs(ev, READ + 40 * D) if i["rule"] == "end_never_reported"][0]
    text = json.dumps(note["rule_applied"])
    assert "assume" not in text and "end_assumed_rationale" not in note["rule_applied"]
    assert note["rule_applied"]["rule"] == "unresolved.listed_ongoing"


def test_a_listing_read_at_the_start_itself_counts():
    s = datetime(2026, 11, 10, 8, tzinfo=UTC)          # 2026-11-10, midnight PST
    ev = row(started_at="2026-11-10", fetched_at=z(s), _feed_health=health(ok=False))
    c, act = seen(ev, s + 45 * D)
    assert c == "unresolved" and act[0]["rule"] == "listed_ongoing"
    assert seen(ev, s + 3 * D)[0] == "red"


def test_the_rules_catalog_has_no_new_entry_with_the_rule_off_or_absent(tmp_path):
    d, waters = _world(tmp_path, row())
    for rules in (ABSENT, OFF):
        st, _ = _build(d, waters, rules)
        assert "listed_ongoing" not in st["rules"]
    st, _ = _build(d, waters, RULES)
    assert st["rules"]["listed_ongoing"]["status"] == "unresolved"


# ---------------------------------------------------------------- a row still listed that no longer reads ongoing
# (coordinator, 2026-11-16): the end cell stops reading ongoing and gives no end; the same fallback as a row that left
# the list, from the last read that listed it as ongoing (raw._ongoing_listing, set once by the ingester)

from ingest import ca_sd_tijuana_table as M  # noqa: E402

T1, T2, T3, T4 = "2026-11-16T22:32:04Z", "2026-11-17T04:40:00Z", "2026-11-17T10:50:00Z", "2026-11-17T17:00:00Z"


def table(end="Ongoing"):
    return [{"start": "10/11/2023", "end": end, "event_type": "Tijuana River Transboundary Flow Event",
             "location": "Tijuana River", "volume": "", "recovered": "", "notes": ""}]


def read(at, rows, prev=()):
    recs, _ = M.build(rows, at, [copy.deepcopy(r) for r in prev], {})
    (r,) = recs
    return r


def shown(rec, t, rules=RULES):
    return seen({**rec, "_feed_health": health()}, t, rules)


def test_ongoing_then_a_blank_end_falls_back_from_the_last_ongoing_read():
    a = read(T1, table())
    b = read(T2, table(""), [a])
    assert b["status"] == "unknown" and b["ended_at"] is None
    assert b["raw"]["_ongoing_listing"] == {"last_listed_at": T1, "unmarked_since": T2}
    out = ivs({**b, "_feed_health": health()}, datetime(2026, 11, 18, tzinfo=UTC))
    assert [i["rule"] for i in out] == ["ongoing", "listed_ongoing", "unresolved", "end_never_reported"]
    lo, un, note = out[1:]
    assert (lo["start"], lo["end"]) == (START + 7 * D, READ)
    assert (un["start"], un["end"]) == (READ, READ + 30 * D)
    assert (note["start"], note["end"]) == (READ + 30 * D, READ + S.NOTE_DAYS * D)
    assert un["label"] == ("Listed as ongoing by the San Diego Regional Water Quality Control Board at our read of "
                           "Nov 16, 2026; the list no longer marks it ongoing and gives no end")
    assert un["rule_applied"]["unmarked_since"] == T2 and un["rule_applied"]["last_listed_at"] == T1
    assert "missing_from_list_since" not in un["rule_applied"]
    assert shown(b, READ + 29 * D)[0] == "unresolved"
    assert shown(b, READ + 31 * D)[0] == "grey"
    # rule off or absent: today's rule for an unknown-status record with no end (nothing since 2023)
    for rules in (OFF, ABSENT):
        assert ivs({**b, "_feed_health": health()}, READ, rules) == ivs({**b, "_feed_health": health()}, READ, ABSENT)
        assert shown(b, READ + D, rules)[0] == "grey"


def test_a_row_never_listed_ongoing_with_no_end_is_untouched():
    a = read(T1, table(""))
    b = read(T2, table(""), [a])
    assert "_ongoing_listing" not in b["raw"]
    assert ivs({**b, "_feed_health": health()}, READ) == ivs({**b, "_feed_health": health()}, READ, ABSENT)


def test_reading_ongoing_again_is_a_listed_row_from_that_read():
    a = read(T1, table())
    b = read(T2, table(""), [a])
    c = read(T3, table(), [b])
    assert c["status"] == "ongoing" and "_ongoing_listing" not in c["raw"]
    (iv,) = shown(c, datetime(2026, 11, 17, 12, tzinfo=UTC))[1]
    assert iv["rule"] == "listed_ongoing" and iv["end"] is None and iv["rule_applied"]["last_listed_at"] == T3


def test_no_revision_churn_across_three_runs():
    a = read(T1, table())
    b = read(T2, table(""), [a])
    c = read(T3, table(""), [b])
    d = read(T4, table(""), [c])
    # one revision for the Board's own change of the end cell, none after; the marker set once and carried
    assert len(b["raw"]["_revisions"]) == len(c["raw"]["_revisions"]) == len(d["raw"]["_revisions"]) == 1
    assert b["raw"]["_ongoing_listing"] == c["raw"]["_ongoing_listing"] == d["raw"]["_ongoing_listing"] == \
        {"last_listed_at": T1, "unmarked_since": T2}
    # and a still-ongoing row: no revision and no marker over three runs
    x = read(T1, table())
    y = read(T2, table(), [x])
    z_ = read(T3, table(), [y])
    assert "_revisions" not in z_["raw"] and "_ongoing_listing" not in z_["raw"]
