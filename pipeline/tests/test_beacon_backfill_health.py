"""Incomplete historical reads survive the hourly workflow and both state archives."""
import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pytest

from ingest import fed_beacon_beach_actions as B
from test_fed_beacon import FIX, registry
from test_state_history import SP

NOW = datetime(2026, 11, 28, 12, tzinfo=UTC)
YEARS = [str(y) for y in range(2014, 2025)]


def reports(year, empty=False):
    if year >= 2025:
        return B.read_saved(FIX, year)
    # Synthetic historical rows test orchestration only; no source dates are invented.
    main = io.StringIO()
    writer = csv.DictWriter(main, fieldnames=B.MAIN_COLUMNS)
    writer.writeheader()
    detail = io.StringIO()
    dwriter = csv.DictWriter(detail, fieldnames=B.DETAIL_COLUMNS)
    dwriter.writeheader()
    if not empty:
        writer.writerow({"Jurisdiction": "OH", "Year": str(year), "Action ID": str(year),
                         "Action Type": "Closure", "Beach ID": "synthetic"})
        dwriter.writerow({"Jurisdiction": "OH", "Year": str(year), "Activity ID": str(year)})
    return main.getvalue(), detail.getvalue()


def paths(root, registry):
    build = root / "data/build"
    return dict(events_dir=build / "events", state_file=build / f"{B.SOURCE_ID}-state.json",
                registry_file=registry)


def read_state(kw):
    return json.loads(kw["state_file"].read_text())


def read_events(kw):
    return json.loads((kw["events_dir"] / f"{B.SOURCE_ID}.json").read_text())


def assert_incomplete(kw, outstanding):
    state, doc = read_state(kw), read_events(kw)
    assert state["backfill"]["requested_years"] == YEARS
    assert sorted(state["backfill"]["outstanding_years"]) == outstanding
    assert doc["meta"]["backfill"]["outstanding_years"] == outstanding
    assert doc["meta"]["backfill"]["requested_years"] == YEARS
    assert {s.split(":", 1)[0] for s in doc["meta"]["years_not_read"]} == set(outstanding)
    assert doc["ok"] is False and doc["error"]


@pytest.mark.parametrize("all_failed", [False, True])
def test_outstanding_backfill_survives_refresh_relink_and_archive_restore(tmp_path, monkeypatch, registry, all_failed):
    kw = paths(tmp_path / "original", registry)
    failing = set(range(2014, 2025)) if all_failed else {2015}
    calls = []

    def pull(_session, year, _sleep):
        calls.append(year)
        if year in failing:
            raise B.requests.ConnectionError("synthetic read failure")
        return reports(year)

    monkeypatch.setattr(B, "pull_year", pull)

    def run(args=(), now=NOW):
        return B.run(list(args), now=now, sess=object(), **kw)

    assert run() == 0  # Existing rolling records, with their real source dates.
    published = {r["event_id"]: r for r in read_events(kw)["records"]}
    last_ok = read_events(kw)["last_ok_at"]
    calls.clear()
    assert run(["--backfill"]) == (1 if all_failed else 0)
    assert calls == list(range(2014, 2025))
    outstanding = sorted(str(y) for y in failing)
    assert B.relink_only(**kw) == 0  # Backfill workflow's post-ingest step.
    assert_incomplete(kw, outstanding)

    # Hourly rewrite, then a successful scheduled rolling pull, each followed by relinking.
    for at in (NOW + timedelta(hours=1), NOW + timedelta(days=8)):
        assert run(now=at) == 0
        assert B.relink_only(**kw) == 0
        assert_incomplete(kw, outstanding)
        assert read_events(kw)["last_ok_at"] == last_ok

    frozen, hot = tmp_path / "frozen.tar.gz", tmp_path / "build.tar.gz"
    assert SP.pack_frozen(frozen, tmp_path / "original") == 0
    SP.pack_build(hot, tmp_path / "original", saved_frozen=frozen)
    assert B.SOURCE_ID not in SP.event_counts(hot)
    fresh = tmp_path / "restored"
    SP.unpack_build(hot, fresh)
    SP.unpack_frozen(frozen, fresh)
    restored = paths(fresh, registry)
    assert restored["state_file"].read_bytes() == kw["state_file"].read_bytes()
    kw = restored
    assert run(now=NOW + timedelta(days=16)) == 0
    assert B.relink_only(**kw) == 0
    assert_incomplete(kw, outstanding)

    # A narrower successful backfill cannot clear an unrelated missing season.
    failing.discard(2024)
    assert run(["--backfill", "2024"]) == 0
    outstanding = sorted(str(y) for y in failing)
    assert B.relink_only(**kw) == 0
    assert_incomplete(kw, outstanding)

    failing.clear()
    assert run(["--backfill"]) == 0
    assert B.relink_only(**kw) == 0
    state, doc = read_state(kw), read_events(kw)
    assert state["backfill"] == {"requested_years": YEARS, "outstanding_years": {}}
    assert doc["meta"]["backfill"]["outstanding_years"] == []
    assert not doc["meta"].get("years_not_read")
    assert doc["ok"] is True and doc["error"] is None
    after = {r["event_id"]: r for r in doc["records"]}
    for eid, before in published.items():
        for field in ("source_record_id", "started_at", "ended_at", "reported_at", "published_at"):
            assert after[eid][field] == before[field]
        assert after[eid]["raw"]["_first_seen_at"] == before["raw"]["_first_seen_at"]


@pytest.mark.parametrize("empty", [False, True])
def test_backfill_failure_without_prior_state_is_saved(tmp_path, monkeypatch, registry, empty):
    kw = paths(tmp_path, registry)

    def pull(_session, year, _sleep):
        if empty:
            return reports(year, empty=True)
        raise B.PullError("synthetic read failure")

    monkeypatch.setattr(B, "pull_year", pull)
    assert B.run(["--backfill"], now=NOW, sess=object(), **kw) == 1
    assert_incomplete(kw, YEARS)
    assert read_state(kw)["years"] == {}
    assert read_events(kw)["records"] == []
