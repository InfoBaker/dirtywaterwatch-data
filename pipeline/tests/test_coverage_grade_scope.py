"""Indiana's coverage wording (its operators' monthly totals published by EPA) is Indiana's alone: for every state live
before Indiana, grade_of returns the text origin/main 76c4655 returned, under both federal settings and monthly, mixed
and dated figures (integration review of state/in, 2026-11-14: the unscoped change altered every live state's text when
federal=True and the figures were predominantly monthly)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from export import coverage as C  # noqa: E402

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "coverage" / "grade_of_before_indiana.json")
                     .read_text())
AS_OF = datetime.fromisoformat(FIXTURE["as_of"])
LIVE_BEFORE = sorted({k.split("|")[0] for k in FIXTURE["texts"]})


def test_the_fixture_covers_every_live_state_both_federal_settings_and_each_figure():
    rules = json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())
    assert len(LIVE_BEFORE) == 33 and set(LIVE_BEFORE) <= set(rules["live_states"])
    assert {"monthly", "mixed", "dated"} <= set(FIXTURE["figures"])
    assert len(FIXTURE["texts"]) == len(LIVE_BEFORE) * 2 * len(FIXTURE["figures"])


@pytest.mark.parametrize("key", sorted(FIXTURE["texts"]))
def test_grade_of_is_unchanged_for_every_live_state(key):
    st, fed, fig = key.split("|")
    got = C.grade_of(st, dict(FIXTURE["figures"][fig]), AS_OF, federal=bool(int(fed)))
    assert list(got) == FIXTURE["texts"][key]


def test_indiana_alone_gets_the_federal_monthly_wording():
    for fig in ("monthly", "mixed"):
        _, s = C.grade_of("IN", dict(FIXTURE["figures"][fig]), AS_OF, federal=True)
        assert "Indiana are published by the U.S. Environmental Protection Agency" in s
        assert "Indiana publishes" not in s
