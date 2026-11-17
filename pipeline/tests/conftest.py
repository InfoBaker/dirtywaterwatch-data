"""Test isolation for the status build's cached live states (build/status.py _STATES).

A status build sets the module's live states from the rules it is given, and its callers read them back after it
(states(), event_state()): that is the build's contract within one run. Between tests it is a leak: a later test that
reads states() saw the previous test's world (tests/test_rain_grid.py's registry test after tests/test_rain_likely.py,
2026-11-16; the same order failed on origin/main). Each test starts with the cache empty, so it is derived again from
data/rules.json or from the test's own build."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _fresh_status_states():
    from build import status as S
    S._STATES = None
    yield
    S._STATES = None


@pytest.fixture
def no_separate_sewer_points(monkeypatch):
    """A rainfall reader test world of its own outfalls only: the hourly reader (ingest/rainfall.py run) also reads the
    separate sewer operators' points (build/rain_sso.py live_points) from the committed rules and data/rain-levels-sso.json
    seed whenever rules.rain_likely.separate_sewers is on (2026-11-16), which would add the real Alabama, Connecticut
    and Florida points to every synthetic world. The reader tests that pin their own points, tiles and request counts use
    this; the tests of the separate sewer points in the reader set their own (test_rain_tiles.py)."""
    from build import rain_sso
    monkeypatch.setattr(rain_sso, "live_points", lambda *a, **k: [])
