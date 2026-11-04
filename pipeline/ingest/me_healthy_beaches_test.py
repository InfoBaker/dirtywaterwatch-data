"""Simulated polls for ingest/me_healthy_beaches.py (snapshot validation and lifting rules).

Run from pipeline/:  python -m pytest ingest/me_healthy_beaches_test.py -q
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
import requests  # noqa: E402

import common  # noqa: E402
from ingest import me_healthy_beaches as m  # noqa: E402

BASE_SNAPSHOT = Path(__file__).resolve().parents[2] / "research/me/raw/mapdata_bma.geojson"
T0 = datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
H = timedelta(hours=1)
EAST_END, WILLARD = "East End Beach", "Willard Beach"
EAST_END_ID = "102"
EMPTY_HISTORY = "<table><tbody></tbody></table>"


def history_html(rows):
    tr = "".join(f"<tr><td>{s}</td><td>{sd}</td><td>{st}</td><td>{ed}</td><td>{et}</td><td>{c}</td></tr>"
                 for s, sd, st, ed, et, c in rows)
    return f"<table><tbody>{tr}</tbody></table>"


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.body, str):
            return json.loads(self.body)
        return self.body


def snapshot(advisories: dict | None = None, drop: set | None = None, keep_only: int | None = None) -> dict:
    """The research copy of mapdata_bma.geojson (66 named beaches, all 'No Active Advisory') with
    advisories set by beach name: {name: (type, start text)}; beaches in `drop` removed."""
    js = copy.deepcopy(json.loads(BASE_SNAPSHOT.read_text()))
    feats = []
    for f in js["features"]:
        p = f["properties"]
        name = p.get("Beach Management Area")
        if drop and name in drop:
            continue
        if advisories and name in advisories:
            t, start = advisories[name]
            p["Advisory Type"], p["Advisory Status"], p["Advisory Start Date"] = t, "Active", start
            p["Public Comment"] = "test comment"
        feats.append(f)
    if keep_only is not None:
        feats = [f for f in feats if f["properties"].get("Beach Management Area")][:keep_only]
    js["features"] = feats
    return js


class World:
    """Fake network, clock and file locations for one test."""

    def __init__(self, tmp_path, monkeypatch):
        self.bma = snapshot()
        self.history: dict[str, str] = {}
        self.fail = set()          # 'bma', 'site', 'history'
        self.now = T0
        monkeypatch.setattr(m, "STATE_PATH", tmp_path / "state.json")
        monkeypatch.setattr(m, "RESEARCH_HIST", tmp_path / "no-research-copy")
        monkeypatch.setattr(m, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
        monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
        monkeypatch.setattr(m.time, "sleep", lambda s: None)
        monkeypatch.setattr(m, "fetch", self.fetch)
        monkeypatch.setattr(m, "_clock", lambda: self.now)
        self.events_path = tmp_path / "events" / f"{m.SOURCE_ID}.json"

    def fetch(self, url, tries=3):
        if "mapdata_bma" in url:
            if "bma" in self.fail:
                raise requests.ConnectionError("simulated outage")
            return Resp(self.bma)
        if "mapdata_site" in url:
            if "site" in self.fail:
                raise requests.HTTPError("HTTP 503")
            return Resp({"type": "FeatureCollection", "features": []})
        if "beach-status-history" in url:
            if "history" in self.fail:
                raise requests.HTTPError("HTTP 500")
            beach = url.split("beach=", 1)[1].replace("+", " ")
            return Resp(self.history.get(beach, EMPTY_HISTORY))
        raise AssertionError(url)

    def poll(self, advance=H):
        self.now += advance
        return m.main([])

    def out(self):
        return json.loads(self.events_path.read_text())

    def rec(self, beach_id=EAST_END_ID):
        rs = [r for r in self.out()["records"] if r["source_record_id"].startswith(f"{beach_id}:")]
        assert len(rs) == 1, rs
        return rs[0]

    def state(self):
        return json.loads(m.STATE_PATH.read_text())


@pytest.fixture
def w(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    world.bma = snapshot({EAST_END: ("Elevated Bacteria", "08/04/2026 10:00 AM")})
    assert world.poll(advance=timedelta(0)) == 0
    r = world.rec()
    assert r["status"] == "advisory_active" and r["started_at"] == "2026-08-04T10:00:00-04:00"
    return world


# --------------------------------------------------------------------------- failed fetches

@pytest.mark.parametrize("bad", [{"features": []}, {}, [], {"type": "FeatureCollection"}])
def test_empty_or_malformed_snapshot_is_a_failed_fetch(w, bad):
    before = w.out()["records"]
    w.bma = bad
    assert w.poll() == 1
    out = w.out()
    assert out["ok"] is False and "snapshot" in out["error"]
    assert out["records"] == before
    assert w.state()["active"] and not w.state()["lifted"]


def test_http_error_is_a_failed_fetch(w):
    w.fail.add("bma")
    assert w.poll() == 1
    out = w.out()
    assert out["ok"] is False and "ConnectionError" in out["error"]
    assert w.rec()["status"] == "advisory_active"


def test_snapshot_under_half_the_previous_beaches_is_a_failed_fetch(w):
    w.bma = snapshot(keep_only=20)          # 20 of 66
    assert w.poll() == 1
    assert "incomplete snapshot" in w.out()["error"]
    assert list(w.state()["active"]) and not w.state()["lifted"]


def test_advisory_survives_a_missed_poll_then_continues(w):
    w.fail.add("bma")
    w.poll()
    w.fail.clear()
    w.bma = snapshot({EAST_END: ("Elevated Bacteria", "08/04/2026 10:00 AM")})
    assert w.poll() == 0
    r = w.rec()
    assert r["status"] == "advisory_active" and r["source_updated_at"] == "2026-08-04T17:00:00Z"


# --------------------------------------------------------------------------- disappearance vs lifting

def test_beach_missing_from_snapshot_keeps_advisory_active(w):
    w.bma = snapshot(drop={EAST_END})        # 65 beaches: a valid snapshot without this beach
    assert w.poll() == 0
    r = w.rec()
    assert r["status"] == "advisory_active" and r["ended_at"] is None
    assert r["raw"]["missing_polls"] == 1
    assert r["source_updated_at"] == "2026-08-04T15:00:00Z"   # last confirmation, for the 14-day aging


def test_empty_advisory_type_is_no_observation(w):
    js = snapshot()
    for f in js["features"]:
        if f["properties"].get("Beach Management Area") == EAST_END:
            f["properties"]["Advisory Type"] = ""
    w.bma = js
    w.poll()
    assert w.rec()["status"] == "advisory_active"


def test_one_no_active_poll_keeps_it_active_two_lift_at_the_first(w):
    w.bma = snapshot()                       # East End present, 'No Active Advisory'
    assert w.poll() == 0                     # 16:00Z
    r = w.rec()
    assert r["status"] == "advisory_active" and r["raw"]["pending_lift"]["observations"] == 1
    assert w.poll() == 0                     # 17:00Z: second consecutive observation
    r = w.rec()
    assert r["status"] == "advisory_lifted"
    assert r["ended_at"] == "2026-08-04T12:00:00-04:00"      # the first poll that saw it lifted
    assert r["raw"]["ended_at_precision"] == "poll" and r["raw"]["ended_at_basis"] == "poll"
    assert r["raw"]["lift_observed_between"] == ["2026-08-04T11:00:00-04:00", "2026-08-04T12:00:00-04:00"]


def test_pending_lift_cancelled_when_advisory_is_posted_again(w):
    w.bma = snapshot()
    w.poll()
    w.bma = snapshot({EAST_END: ("Elevated Bacteria", "08/04/2026 10:00 AM")})
    w.poll()
    r = w.rec()
    assert r["status"] == "advisory_active" and "pending_lift" not in r["raw"]
    w.bma = snapshot()
    w.poll()
    assert w.rec()["status"] == "advisory_active"          # a new single observation is pending again


def test_missing_poll_between_lift_observations_does_not_lift_early(w):
    w.bma = snapshot()
    w.poll()
    w.fail.add("bma")
    w.poll()                                              # failed: no observation
    w.fail.clear()
    w.bma = snapshot(drop={EAST_END})
    w.poll()                                              # absent: no observation
    assert w.rec()["status"] == "advisory_active"
    w.bma = snapshot()
    w.poll()                                              # second observation
    r = w.rec()
    assert r["status"] == "advisory_lifted" and r["ended_at"] == "2026-08-04T12:00:00-04:00"


def test_history_page_end_lifts_at_once_with_the_earlier_time(w):
    w.history[EAST_END] = history_html([("Elevated Bacteria Advisory", "08/04/2026", "10:00 AM",
                                         "08/04/2026", "11:30 AM", "")])
    w.bma = snapshot()
    assert w.poll() == 0                                  # 16:00Z = 12:00 local
    r = w.rec()
    assert r["status"] == "advisory_lifted" and r["ended_at"] == "2026-08-04T11:30:00-04:00"
    assert r["raw"]["ended_at_basis"] == "status history page" and r["raw"]["ended_at_precision"] == "minute"
    assert len([x for x in w.out()["records"] if x["source_record_id"].startswith(EAST_END_ID)]) == 1


def test_history_end_after_the_poll_uses_the_poll_time(w):
    w.history[EAST_END] = history_html([("Elevated Bacteria Advisory", "08/04/2026", "10:00 AM",
                                         "08/04/2026", "02:00 PM", "")])
    w.bma = snapshot()
    w.poll()
    r = w.rec()
    assert r["status"] == "advisory_lifted" and r["ended_at"] == "2026-08-04T12:00:00-04:00"
    assert r["raw"]["ended_at_precision"] == "poll"


def test_history_row_with_another_start_is_not_used(w):
    w.history[EAST_END] = history_html([("Elevated Bacteria Advisory", "07/22/2026", "02:42 PM",
                                         "07/23/2026", "04:00 PM", "")])
    w.bma = snapshot()
    w.poll()
    recs = {r["source_record_id"]: r for r in w.out()["records"]}
    assert recs["102:beach_advisory:2026-08-04T10:00"]["status"] == "advisory_active"   # no confident end
    assert recs["102:beach_advisory:2026-07-22T14:42"]["status"] == "advisory_lifted"   # its own record


def test_different_advisory_at_the_beach_lifts_the_old_one(w):
    w.bma = snapshot({EAST_END: ("Precautionary Rainfall", "08/04/2026 12:00 PM")})
    w.poll()
    w.poll()
    recs = {r["event_type"]: r for r in w.out()["records"] if r["source_record_id"].startswith(EAST_END_ID)}
    assert recs["beach_advisory"]["status"] == "advisory_lifted"
    assert recs["beach_advisory"]["ended_at"] == "2026-08-04T12:00:00-04:00"
    assert recs["beach_advisory"]["raw"]["lift_observed"].startswith("other advisory posted")
    assert recs["rain_advisory"]["status"] == "advisory_active"
    assert recs["rain_advisory"]["advice_window_hours"] == 48


def test_revised_start_is_the_same_advisory(w):
    w.bma = snapshot({EAST_END: ("Elevated Bacteria", "08/04/2026 09:00 AM")})
    w.poll()
    w.poll()
    rs = [r for r in w.out()["records"] if r["source_record_id"].startswith(EAST_END_ID)]
    assert len(rs) == 1 and rs[0]["status"] == "advisory_active"
    assert rs[0]["started_at"] == "2026-08-04T09:00:00-04:00" and rs[0]["raw"]["start_revisions"]


# --------------------------------------------------------------------------- partial runs

def test_site_geojson_failure_makes_the_run_not_ok(w):
    before = w.out()["records"]
    w.fail.add("site")
    w.bma = snapshot()
    assert w.poll() == 1
    out = w.out()
    assert out["ok"] is False and "site geojson" in out["error"] and out["records"] == before


def test_history_failure_is_reported_and_does_not_lift(w):
    w.fail.add("history")
    w.bma = snapshot()
    assert w.poll() == 1
    assert "history page" in w.out()["error"]
    st = w.state()
    assert list(st["active"]) and st["active"][next(iter(st["active"]))]["pending_lift"]["observations"] == 1
