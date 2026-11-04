"""New Jersey's shared CSO notification site (njcsonotifications.com) as the "discharge likely" caution for its
permits, and the per-state reach of the caution (out/coverage.json rain_caution_states).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import rain_likely as RL  # noqa: E402
from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from ingest import nj_cso_likely as L  # noqa: E402
from tests.test_rain_likely import RAIN_RULES  # noqa: E402
from tests.test_status import TEST_RULES, ev, iso, tmp_events, world  # noqa: E402

H = timedelta(hours=1)
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
PERMIT = "NJ0108758"


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


def z(t):
    return t.isoformat().replace("+00:00", "Z")


def site(flags: dict[int, bool | None], snap_age_h=0.5, stale=False):
    """flags: {hours before NOW: exceeded} as hourly observations of the site; the snapshot is the latest."""
    obs = [[z(NOW - b * H - 10 * timedelta(minutes=1)), ex, 0.5 if ex else 0.0, 0.9 if ex else 0.0, False, ex,
            f"obs {b}h back"] for b, ex in sorted(flags.items(), reverse=True)]
    latest = flags[min(flags)]
    snap = {"ok": True, "fetched_at": z(NOW - snap_age_h * H), "last_ok_at": z(NOW - snap_age_h * H),
            "source_is_stale": stale, "source_is_historical": False, "count": 1,
            "disclaimer": "This site indicates when an overflow is likely, not that one has occurred.",
            "permittees": [{"npdes_permit": PERMIT, "name": "Newark (City of)", "discharger_id": "nj-newark",
                            "exceeded": latest, "alert_label": "CSO event likely" if latest else "CSO event unlikely",
                            "short_window": {"total_in": 0.5 if latest else 0.0},
                            "long_window": {"total_in": 0.9 if latest else 0.0}}]}
    return {"snapshot": snap, "history": {"observations": {PERMIT: obs}},
            "outfalls": [{"permit": PERMIT, "outfall": "001", "water_slug": "other-pond-ma", "water_match": "geometry+name",
                          "distance_m": 0, "lat": 40.73, "lon": -74.16}]}


def nj_world(flags, events=(), **kw):
    w = world(tmp_events(list(events)))
    w["rules"] = RAIN_RULES
    w["rain"] = {"rainfall": {}, "history": {}, "thresholds": {}, "dischargers": {}, "site_flags": site(flags, **kw)}
    return w


def test_the_ingester_keeps_one_observation_per_run_for_90_days_and_rebuilds_from_raw(tmp_path):
    rows = [{"npdes_permit": PERMIT, "exceeded": True, "short_window": {"total_in": 0.4, "exceeded": True},
             "long_window": {"total_in": 0.8, "exceeded": False}, "latest_observation_label": "Nov 3, 5:00 AM"}]
    h = L.observe(None, rows, "2026-11-03T10:00:00Z")
    h = L.observe(h, rows, "2026-11-03T10:00:00Z")                             # a repeated fetch is not added twice
    h = L.observe(h, [{**rows[0], "exceeded": False}], "2026-11-03T11:00:00Z", usable=False)
    assert h["observations"][PERMIT] == [["2026-11-03T10:00:00Z", True, 0.4, 0.8, True, False, "Nov 3, 5:00 AM"],
                                         ["2026-11-03T11:00:00Z", None, 0.4, 0.8, None, None, "Nov 3, 5:00 AM"]]
    h = L.observe(h, rows, "2027-02-15T10:00:00Z")                             # 90 days later: the old rows go
    assert [o[0] for o in h["observations"][PERMIT]] == ["2027-02-15T10:00:00Z"]
    raw = tmp_path / "raw"
    raw.mkdir()
    js = {"isStale": False, "permittees": [{"permitNumber": PERMIT, "name": "Newark",
                                            "shortWindow": {"totalInches": 0.3, "isExceeded": True},
                                            "longWindow": {"totalInches": 0.5, "isExceeded": False}}]}
    (raw / "20261103T101434Z.json").write_text(json.dumps(js))
    (raw / "20261103T111124Z.json").write_text(json.dumps({**js, "isStale": True}))
    got = L.history_from_raw(raw)["observations"][PERMIT]
    assert got == [["2026-11-03T10:14:34Z", True, 0.3, 0.5, True, False, None],
                   ["2026-11-03T11:11:24Z", None, 0.3, 0.5, None, None, None]]


def test_the_sites_flag_is_the_caution_at_the_permits_outfalls_with_the_48_hour_tail_and_the_citation():
    flags = {b: (5 <= b <= 7) for b in range(0, 12)}       # readings 10 min before each hour: flagged 7 to 5 h back
    st, hist = S.build(now=NOW, write=False, **nj_world(flags))
    pond = st["waters"]["other-pond-ma"]
    assert pond["status"] == "yellow"
    r = pond["reasons"][0]
    assert r["rule"] == "rain_likely" and r["source_id"] == "nj-cso-likely"
    rain = r["rain"]
    assert rain["basis"] == "site_flag" and rain["site_url"] == "https://njcsonotifications.com/"
    assert rain["above_from"] == z(NOW - 8 * H) and rain["until"] == z(NOW - 5 * H + 48 * H)     # hour of each reading
    assert "shared notification site" in r["short"] and rain["threshold_in"] is None
    # cited to the shared site with the window it flagged and its own observation labels; no fetch time as valid_time
    assert rain["flag_windows"] == ["4-hour"] and "4-hour rainfall over the threshold" in r["short"]
    assert rain["observed_labels"] == ["obs 7h back", "obs 5h back"] and rain["rain_4h_in"] == 0.9
    assert rain["valid_time"] is None and rain["site_fetched_at"] == z(NOW - 5 * H - 10 * timedelta(minutes=1))
    assert rain["citation"]["url"] == "https://njcsonotifications.com/" and "NOAA" not in str(rain)
    assert st["rain_likely"]["permits"][PERMIT]["valid_time"] is None
    assert "nj-cso-likely" in pond["covered_by"] and st["sources"]["nj-cso-likely"]["stale"] is False
    blk = st["rain_likely"]
    assert blk["permits"][PERMIT]["status"] == "likely" and blk["permits"][PERMIT]["state"] == "NJ"
    assert blk["site_flags"]["source_id"] == "nj-cso-likely" and blk["site_flags"]["permits"] == 1
    assert hist["waters"]["other-pond-ma"][-9:] == "y" * 9 and hist["waters"]["other-pond-ma"][-10] == "g"   # replay
    # still flagged at the latest fresh reading: open; a reading the site calls stale is no reading
    st, _ = S.build(now=NOW, write=False, **nj_world({0: True, 1: True, 2: False}))
    assert st["waters"]["other-pond-ma"]["reasons"][0]["until"] is None
    st, _ = S.build(now=NOW, write=False, **nj_world({b: False for b in range(0, 6)}))
    assert st["waters"]["other-pond-ma"]["status"] == "grey" and st["rain_likely"]["permits"][PERMIT]["status"] == "below"
    # a discharge notice from the permittee in the last 24 hours suppresses it, as with the radar
    notice = ev("n", source_id="nj-notice", npdes_permit=PERMIT, status="ended", started_at=iso(NOW - 8 * H),
                ended_at=iso(NOW - 7 * H), water_slugs=[])
    st, _ = S.build(now=NOW, write=False, **nj_world(flags, events=[notice]))
    assert st["rain_likely"]["permits"][PERMIT]["status"] == "suppressed"


def test_coverage_says_per_state_whether_and_how_the_caution_is_computed():
    st, _ = S.build(now=NOW, write=False, **nj_world({0: False}))
    cov = RL.caution_coverage(st["rain_likely"], {"NJ": {PERMIT, "NJ0026182"}, "PA": {"PA0026689"}})
    nj, pa = cov["NJ"], cov["PA"]
    assert nj["covered"] and nj["methods"] == ["site_flag"] and nj["permits"] == 1 and nj["cso_permits"] == 2
    assert nj["sources"] == ["nj-cso-likely"] and "njcsonotifications.com" in nj["sentence"]
    assert "1 of the 2 combined sewer operators" in nj["sentence"] and "For the other 1" in nj["sentence"]
    assert not pa["covered"] and pa["permits"] == 0 and pa["sentence"].startswith('No "discharge likely" caution here')
    off = RL.caution_coverage({"enabled": False, "permits": {}}, ["ME"])
    assert off["ME"]["covered"] is False
    src = Path(X.__file__).read_text()
    assert 'OUT_DIR / "coverage.json"' in src and "rain_states=rain_caution_states(rain_block)" in src


def test_each_caution_cites_its_own_threshold_and_says_what_kind_it_is():
    rules = json.loads((Path(X.__file__).resolve().parents[2] / "data" / "rules.json").read_text())
    stale = {"permits": {"NY0029050": {"threshold_in": 0.1, "basis": "published", "rule": "rain_likely.fallback.default",
                                       "basis_text": "old default", "source": "EPA Region 1 NPDES permit MA0101613"},
                         "MA0101613": {"threshold_in": 0.42, "basis": "history", "rule": "rain_likely.percentile",
                                       "basis_text": "p10 of 50 days", "source": "MassDEP"}}}
    ny = RL.threshold_for("NY0029050", "NY", stale, rules)            # a stale row never carries the default into NY
    assert ny["kind"] == "state" and ny["rule"] == "rain_likely.fallback.by_state.NY" and "6 NYCRR" in ny["source"]
    vt = RL.threshold_for("VT0100871", "VT", stale, rules)
    assert vt["kind"] == "site_default" and vt["threshold_in"] == 0.1
    assert vt["text"] == ("This site's default: 0.1 inch of rain in 24 hours at a combined sewer outfall, applied where "
                          "the state publishes no rain trigger of its own")
    assert vt["source"] == "This site's methods page"
    assert "MA0101613" not in json.dumps(vt) and "Springfield" not in json.dumps(vt)
    assert "MA0101613" not in json.dumps(rules) and "Springfield" not in json.dumps(rules)
    assert RL.threshold_for("MA0101613", "MA", stale, rules)["kind"] == "operator_history"
    assert RL.threshold_for("XX0000001", "VT", {}, {})["text"] == RL.SITE_DEFAULT_TEXT   # no rules at all
    # the records carry the kind: a radar record, and New Jersey's shared site
    st, _ = S.build(now=NOW, write=False, **nj_world({b: (5 <= b <= 7) for b in range(0, 12)}))
    r = st["waters"]["other-pond-ma"]["reasons"][0]["rain"]
    assert r["threshold_kind"] == "shared_site" and st["rain_likely"]["permits"][PERMIT]["threshold_kind"] == "shared_site"
    from tests.test_rain_likely import NOW as RNOW, rain_world, wet
    st, _ = S.build(now=RNOW, write=False, **rain_world(values=wet(range(0, 6))))
    assert st["waters"]["other-pond-ma"]["reasons"][0]["rain"]["threshold_kind"] == "operator_history"
    from build import rain_thresholds as RT
    assert RT.fallback_for("NY", rules)["kind"] == "state" and RT.fallback_for("VT", rules)["kind"] == "site_default"
