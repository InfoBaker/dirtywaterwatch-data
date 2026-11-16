"""A standing advisory through a source outage (data/rules.json unresolved.source_outage; owner, 2026-11-16:
"disclosure is public safety"). Past the 14 days after the last read that listed it, an advisory whose feed has had no
successful read since is shown as end not confirmed (hatched), never grey and never red for the unread time; a feed
read successfully since keeps today's grey age-out. Asserts what a visitor sees: the colour and label at a time.

Run from pipeline/: python -m pytest tests/test_source_outage.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build import status as S  # noqa: E402

RULES = S.load_rules()
OFF = {**RULES, "unresolved": {k: v for k, v in RULES["unresolved"].items() if k != "source_outage"}}
D, M = timedelta(days=1), timedelta(minutes=1)
L = datetime(2026, 7, 1, 13, 0, tzinfo=UTC)          # the last read that listed the advisory
START = L - 3 * D


def z(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def standing(**over) -> dict:
    """A standing listing kept alive by each read that lists it (Kentucky's swimming advisories' shape)."""
    raw = {"_last_seen_in_source": z(L), **over.pop("raw", {})}
    return {"event_id": "x-feed:1", "source_id": "x-feed", "event_type": "beach_advisory", "status": "advisory_active",
            "started_at": z(START), "ended_at": None, "time_precision": "minute", "authority": "Health Department",
            "source_url": "https://example.org/advisories", "time_zone": "America/New_York", "raw": raw, **over}


def polled(**over) -> dict:
    """A polled layer with no dates (Kansas KDHE's HAB layer: raw._poll_confirmed, time precision poll)."""
    return standing(event_type="hab_advisory", time_precision="poll", raw={"_poll_confirmed": True}, **over)


def outage() -> dict:
    """The feed's header: the run that listed it wrote at L + 2 min; every read since failed."""
    return {"fetched_at": z(L + 40 * D), "ok": False, "last_ok_at": z(L + 2 * M), "prev_ok_at": z(L - 58 * M)}


def healthy_since() -> dict:
    """A successful read after the listing one (that did not list the record)."""
    return {"fetched_at": z(L + 40 * D), "ok": True, "last_ok_at": z(L + 40 * D), "prev_ok_at": z(L + 39 * D)}


def seen(ev, t, rules=RULES):
    return S.status_at(S.event_intervals(ev, "KY", t, None, rules), t)


def test_outage_day_15_and_60_hatched_with_the_last_read():
    for days in (15, 60):
        t = L + days * D
        for ev in (standing(_feed_health=outage()), polled(_feed_health=outage())):
            c, ivs = seen(ev, t)
            assert c == "unresolved", (days, ev["event_type"])
            (iv,) = ivs
            assert iv["rule"] == "outage_unconfirmed" and iv["end"] is None and iv["start"] == L + 14 * D
            assert iv["label"] == ("Advisory listed by the authority at the last read that showed it, Jul 1, 2026, "
                                   "09:00 EDT; the source has not been readable since: end not confirmed")
            assert iv["rule_applied"]["last_listed_at"] == z(L)
            assert iv["rule_applied"]["last_successful_read_at"] == z(L + 2 * M)
            # red only for the authority's window up to 14 days after the last listing, never for the unread time
            reds = [i for i in S.event_intervals(ev, "KY", t, None, RULES) if i["color"] == "red"]
            assert reds and all(i["end"] == L + 14 * D for i in reds)
            assert not [i for i in S.event_intervals(ev, "KY", t, None, RULES) if i["color"] == "grey"]


def test_first_14_days_of_an_outage_unchanged():
    for days in (1, 13.9):
        t = L + days * D
        for mk in (standing, polled):
            assert S.event_intervals(mk(_feed_health=outage()), "KY", t, None, RULES) == \
                S.event_intervals(mk(), "KY", t, None, RULES)
            assert seen(mk(_feed_health=outage()), t)[0] == "red"


def test_kansas_style_successful_read_since_ages_out_grey_as_today():
    t = L + 20 * D
    for mk in (standing, polled):
        ev = mk(_feed_health=healthy_since())
        assert S.event_intervals(ev, "KY", t, None, RULES) == S.event_intervals(mk(), "KY", t, None, RULES)
        c, ivs = seen(ev, t)
        assert c == "grey" and [i["rule"] for i in ivs] == ["not_reconfirmed"]


def test_healthy_read_that_no_longer_lists_it_ends_as_today():
    gone = L + timedelta(hours=1)
    ev = standing(raw={"_unlisted_since": z(gone)}, _feed_health=healthy_since())
    t = L + 30 * D
    assert S.event_intervals(ev, "KY", t, None, RULES) == \
        S.event_intervals(standing(raw={"_unlisted_since": z(gone)}), "KY", t, None, RULES)
    (iv,) = S.event_intervals(ev, "KY", t, None, RULES)
    assert iv["end"] == gone and iv["color"] == "red"


def test_no_health_information_keeps_todays_behaviour():
    t = L + 30 * D
    for mk in (standing, polled):
        assert seen(mk(), t)[0] == "grey"
        for h in ({}, {"ok": False}, {"ok": False, "last_ok_at": None}):
            assert S.event_intervals(mk(_feed_health=h), "KY", t, None, RULES) == \
                S.event_intervals(mk(), "KY", t, None, RULES)


def test_switch_off_keeps_todays_behaviour():
    t = L + 30 * D
    assert seen(standing(_feed_health=outage()), t, OFF)[0] == "grey"


def test_system_wide_48_hour_rule_unchanged():
    t = L + 30 * D
    sw = standing(raw={"advisory_scope": "system-wide"}, _feed_health=outage())
    ivs = S.event_intervals(sw, "KY", t, None, RULES)
    assert ivs == S.event_intervals(standing(raw={"advisory_scope": "system-wide"}), "KY", t, None, RULES)
    assert [i for i in ivs if i["color"] == "red"][0]["end"] == L + timedelta(hours=48)
    assert seen(sw, t)[0] == "grey"


def test_no_ok_read_since():
    f = common.no_ok_read_since
    assert f(outage(), z(L)) is True
    assert f(healthy_since(), z(L)) is False
    # the listing run's own write is not a later read; the next successful write is
    assert f({"last_ok_at": z(L + 2 * M), "prev_ok_at": z(L - 1 * D)}, z(L)) is True
    assert f({"last_ok_at": z(L + 1 * D), "prev_ok_at": z(L + 2 * M)}, z(L)) is False
    # a file from before prev_ok_at: the listing run's write within SAME_READ_MINUTES
    assert f({"last_ok_at": z(L + 2 * M)}, z(L)) is True
    assert f({"last_ok_at": z(L + 1 * D)}, z(L)) is False
    # listed by a read that was not successful (a partial read), none since
    assert f({"last_ok_at": z(L - 1 * D), "prev_ok_at": z(L - 2 * D)}, z(L)) is True
    assert f(None, z(L)) is None and f({}, z(L)) is None and f(outage(), None) is None


def _write(tmp, monkeypatch, at, records, **kw):
    monkeypatch.setattr(common, "now_iso", lambda: z(at))
    return common.write_events("x-feed", records, path=tmp / "x-feed.json", **kw)


def _load(tmp):
    _, events, _ = S.load_events(tmp)
    return {e["event_id"]: e for e in events}


def test_partial_or_failed_reads_are_not_successful(tmp_path, monkeypatch):
    rec = standing()
    _write(tmp_path, monkeypatch, L + 2 * M, [rec])
    _write(tmp_path, monkeypatch, L + 1 * D, [], ok=False, error="timeout")
    _write(tmp_path, monkeypatch, L + 2 * D, [rec], ok=False, partial=True, error="half the pages")
    ev = _load(tmp_path)["x-feed:1"]
    assert ev["_feed_health"]["last_ok_at"] == z(L + 2 * M)
    assert seen(ev, L + 20 * D)[0] == "unresolved"


def test_outage_ends_listed_again_red_from_that_read_gap_not_red(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, L + 2 * M, [standing()])
    for d in (1, 10, 30):
        _write(tmp_path, monkeypatch, L + d * D, [], ok=False, error="unreachable")
    back = L + 40 * D
    during = _load(tmp_path)["x-feed:1"]
    assert seen(during, back - 1 * D)[0] == "unresolved"
    _write(tmp_path, monkeypatch, back + 2 * M, [standing(raw={"_last_seen_in_source": z(back)})])
    ev = _load(tmp_path)["x-feed:1"]
    assert ev["raw"]["_unread_gaps"] == [{"from": z(L), "to": z(back), "listed_again": True}]
    now = back + 1 * D
    ivs = S.event_intervals(ev, "KY", now, None, RULES)
    assert S.status_at(ivs, now)[0] == "red"                          # red again from that read
    assert S.status_at(ivs, L + 5 * D)[0] == "red"                    # the authority's window before the outage
    for d in (14.5, 20, 39.9):                                        # the unread gap: as it was shown, never red
        c, at = S.status_at(ivs, L + d * D)
        assert c == "unresolved" and at[0]["rule"] == "outage_unconfirmed", d
        assert "could not be read again until Aug 10, 2026, 09:00 EDT" in at[0]["label"]
    # the gap is kept at the next successful read, which no longer needs to see it
    _write(tmp_path, monkeypatch, back + 1 * D, [standing(raw={"_last_seen_in_source": z(back + 1 * D)})])
    assert _load(tmp_path)["x-feed:1"]["raw"]["_unread_gaps"][0]["from"] == z(L)


def test_outage_ends_not_listed_ages_out_from_that_read(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, L + 2 * M, [polled()])
    _write(tmp_path, monkeypatch, L + 20 * D, [], ok=False, error="unreachable")
    back = L + 30 * D
    _write(tmp_path, monkeypatch, back, [polled()])                   # read again; the layer still carries it unlisted
    ev = _load(tmp_path)["x-feed:1"]
    assert ev["raw"]["_unread_gaps"] == [{"from": z(L), "to": z(back), "listed_again": False}]
    ivs = S.event_intervals(ev, "KS", back + 5 * D, None, RULES)
    assert S.status_at(ivs, L + 20 * D)[0] == "unresolved"            # the unread time stays as it was shown
    assert S.status_at(ivs, back + 1 * D)[0] == "grey"                # read since, not listed: today's age-out


def test_healthy_feed_writes_nothing_new_on_records(tmp_path, monkeypatch):
    for d in range(0, 40, 5):
        _write(tmp_path, monkeypatch, L + d * D, [standing(raw={"_last_seen_in_source": z(L + d * D - 1 * M)})])
    doc = json.loads((tmp_path / "x-feed.json").read_text())
    assert "_unread_gaps" not in doc["records"][0]["raw"]
    # successful reads that do not list it (a feed that keeps only recent items): no gap either
    for d in (36, 60):
        _write(tmp_path, monkeypatch, L + d * D,
               [standing(raw={"_last_seen_in_source": z(L + 35 * D - 1 * M)})])
        assert "_unread_gaps" not in json.loads((tmp_path / "x-feed.json").read_text())["records"][0]["raw"]


def test_record_carried_by_two_feeds_takes_each_files_health(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, L + 2 * M, [standing()])
    _write(tmp_path, monkeypatch, L + 20 * D, [], ok=False, error="unreachable")
    monkeypatch.setattr(common, "now_iso", lambda: z(L + 2 * M))
    common.write_events("y-feed", [standing(event_id="y-feed:1", source_id="x-feed")], path=tmp_path / "y-feed.json")
    monkeypatch.setattr(common, "now_iso", lambda: z(L + 20 * D))
    common.write_events("y-feed", [standing(event_id="y-feed:1", source_id="x-feed")], path=tmp_path / "y-feed.json")
    evs = _load(tmp_path)
    assert seen(evs["x-feed:1"], L + 21 * D)[0] == "unresolved"       # its file unread since the listing
    assert seen(evs["y-feed:1"], L + 21 * D)[0] == "grey"             # same source id, its own file read since


def test_record_hash_ignores_feed_health():
    assert S.record_hash(standing()) == S.record_hash(standing(_feed_health=outage()))
