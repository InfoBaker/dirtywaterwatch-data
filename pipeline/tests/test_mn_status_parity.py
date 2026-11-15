"""build/status.py's addition for the Metropolitan Council (raw._advisory_from, verification pass 2026-11-15 P1-2) is
keyed on that field: every other record's intervals are identical to those of the status module before it
(46a35fe). Records: invented ones on each status path in other states, and EPA's eRule rows of other states from the
saved build where present. No network."""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from build import status as S

ROOT = Path(__file__).resolve().parents[2]
BASE = "46a35fe"
NOW = datetime(2026, 11, 14, 18, tzinfo=timezone.utc)


def base_status():
    try:
        src = subprocess.run(["git", "show", f"{BASE}:pipeline/build/status.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("the base commit is not in this clone")
    spec = importlib.util.spec_from_loader("build._status_base", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "build"
    sys.modules["build._status_base"] = mod
    exec(compile(src, "status_base.py", "exec"), mod.__dict__)
    return mod


def ev(i, state, **k):
    raw = k.pop("raw", {})
    return {"event_id": f"x:{i}", "source_id": f"x-{state.lower()}", "event_type": "sso", "status": "unknown",
            "started_at": None, "reported_at": "2026-03-02", "ended_at": None, "time_precision": "day",
            "source_url": "https://example.org/", "raw": {"state": state, **raw}, **k}


CASES = [
    ev(1, "MI", status="ended", ended_at="2026-03-03", advice_window_hours=48.0),
    ev(2, "HI", status="advisory_active", raw={"_unlisted_since": "2026-03-09T05:00:00Z", "_end_not_confirmed": True}),
    ev(3, "NE", status="advisory_active", event_type="hab"),
    ev(4, "OH", status="unknown"),
    ev(5, "TX", status="ongoing", started_at="2026-03-02T10:00:00"),
    ev(6, "KY", status="advisory_lifted", started_at="2026-03-01", ended_at="2026-03-05"),
    ev(7, "FL", status="advisory_active", raw={"_unlisted_since": "2026-03-09T05:00:00Z"}),
    ev(8, "PA", status="ended", ended_at="2026-03-02", started_at="2026-03-01"),
]


def strip(ivs):
    return json.dumps(ivs, default=str, sort_keys=True)


def test_other_states_intervals_identical_to_the_base():
    B = base_status()
    records = list(CASES)
    f = ROOT / "data" / "build" / "events" / "echo-sewer-overflow.json"
    if f.exists():
        records += [r for r in json.loads(f.read_text()).get("records", [])
                    if (r.get("state") or (r.get("raw") or {}).get("state")) != "MN"]
    assert len(records) > 100 or not f.exists()
    for r in records:
        st = r.get("state") or (r.get("raw") or {}).get("state")
        assert strip(S.event_intervals(r, st, NOW)) == strip(B.event_intervals(r, st, NOW)), r["event_id"]


def test_the_council_record_with_later_signs_is_the_one_that_differs():
    B = base_status()
    r = ev(9, "MN", status="advisory_active", raw={"time_zone": "America/Chicago", "_advisory_from": "2026-03-12",
                                                    "_before_advisory": {"status": "ended", "ended_at": "2026-03-02",
                                                                         "ended_at_precision": "day"}})
    assert strip(S.event_intervals(r, "MN", NOW)) != strip(B.event_intervals(r, "MN", NOW))
