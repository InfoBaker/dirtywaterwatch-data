"""build.status --live-only: the records of states not in rules.json live_states are left out of the status build, as
the export leaves them out of out/ (2026-11-07: Alabama's ingester, merged before Alabama went live, placed a report on
the Georgia side of the Chattahoochee and of Walter F George Reservoir; the pages then counted "Record not found" and
the publish failed the wording scan). Without the flag (tests, batches, audits) every state's records load."""
from __future__ import annotations

import json
from pathlib import Path

from build import status as S

ROOT = Path(__file__).resolve().parents[2]


def _events_file(d: Path, sid: str, st: str, n: int) -> None:
    recs = [{"event_id": f"{sid}:{i}", "source_id": sid, "event_type": "sso", "status": "ended", "raw": {"state": st},
             "started_at": "2026-10-10T10:00:00-05:00", "ended_at": "2026-10-10T12:00:00-05:00", "water_slugs": []}
            for i in range(n)]
    (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "fetched_at": "2026-11-07T00:00:00Z", "ok": True,
                                                "count": n, "records": recs}))


def test_live_only_leaves_out_the_records_of_states_not_live(tmp_path):
    d = tmp_path / "events"
    d.mkdir()
    _events_file(d, "ga-epd-spills", "GA", 3)
    _events_file(d, "al-adem-sso-history", "AL", 2)
    files, events, problems = S.load_events(d)
    assert not problems and len(events) == 5 and sorted(files) == ["al-adem-sso-history", "ga-epd-spills"]
    files, events, problems = S.load_events(d, live={"GA"})
    assert not problems and [e["event_id"] for e in events] == [f"ga-epd-spills:{i}" for i in range(3)]
    assert S.NOT_LIVE == [("al-adem-sso-history", "AL")] * 2
    # a record whose state cannot be told is kept (a national feed's row with no state)
    _events_file(d, "epa-national", "", 1)
    files, events, _ = S.load_events(d, live={"GA"})
    assert "epa-national:0" in {e["event_id"] for e in events}


def test_the_refresh_runs_the_status_build_live_only():
    mk = (ROOT / "Makefile").read_text()
    line = next(ln for ln in mk.splitlines() if "-m build.status" in ln)
    assert "--live-only" in line
