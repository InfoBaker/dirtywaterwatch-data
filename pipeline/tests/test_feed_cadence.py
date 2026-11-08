"""The feed cadence (pipeline/cadence.py; docs/refresh-time-brief-2026-11-07.md): a feed of a state not in
data/rules.json live_states runs on a daily pass, every other feed hourly; the switch in live_states is the only edit
a go-live needs. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import cadence as C

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 8, 3, 7, tzinfo=UTC)


def test_a_feed_belongs_to_the_state_its_name_starts_with():
    assert C.feed_state("ingest.al_adem_sso") == "AL"
    assert C.feed_state("generic.tx-tceq-sso-opendata") == "TX"
    assert C.feed_state("wa-kc-cso-status-csv") == "WA"
    # national, multi-state and city feeds belong to no one state: hourly, always
    for n in ("ingest.echo_sewer_overflow_events", "ingest.echo_cso_dmr_monthly", "ingest.notification_pages",
              "ingest.nyc_dep_advisories", "generic.boston-phc-warning", "ingest.generic"):
        assert C.feed_state(n) is None, n


def test_a_live_states_feed_runs_every_hour_whatever_the_stamps_say():
    stamps = {"ingest.ct_deep": (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert C.due(["ingest.ct_deep", "ingest.echo_sewer_overflow_events"], {"CT"}, stamps, NOW) == [
        "ingest.ct_deep", "ingest.echo_sewer_overflow_events"]


def stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_not_live_feed_runs_once_a_day():
    names = ["ingest.al_adem_sso", "ingest.ct_deep"]
    # never run: due now
    assert C.due(names, {"CT"}, {}, NOW) == ["ingest.al_adem_sso:daily", "ingest.ct_deep"]
    # ran an hour ago: waits
    assert C.due(names, {"CT"}, {"ingest.al_adem_sso": stamp(NOW - timedelta(hours=1))}, NOW) == ["ingest.ct_deep"]
    # ran 23 h 40 min ago (yesterday's run started a few minutes later): due (the 30-minute slack)
    assert C.due(names, {"CT"}, {"ingest.al_adem_sso": stamp(NOW - timedelta(hours=23, minutes=40))}, NOW)[0] \
        == "ingest.al_adem_sso:daily"
    # 23 h ago: not yet
    assert C.due(names, {"CT"}, {"ingest.al_adem_sso": stamp(NOW - timedelta(hours=23))}, NOW) == ["ingest.ct_deep"]
    # a stamp in the future (a clock moved back) or unreadable: due
    assert C.due(["ingest.al_adem_sso"], {"CT"}, {"ingest.al_adem_sso": stamp(NOW + timedelta(hours=3))}, NOW)
    assert C.due(["ingest.al_adem_sso"], {"CT"}, {"ingest.al_adem_sso": "garbage"}, NOW)
    # FEEDS_ALL
    assert C.due(names, {"CT"}, {"ingest.al_adem_sso": stamp(NOW)}, NOW, run_all=True) == [
        "ingest.al_adem_sso:daily", "ingest.ct_deep"]


def test_the_live_states_switch_is_the_only_edit_a_go_live_needs():
    st = {"ingest.al_adem_sso": stamp(NOW - timedelta(hours=1))}
    assert C.due(["ingest.al_adem_sso"], {"CT"}, st, NOW) == []
    assert C.due(["ingest.al_adem_sso"], {"CT", "AL"}, st, NOW) == ["ingest.al_adem_sso"]
    # no live_states list at all (or rules unreadable): every feed hourly, never a feed skipped by accident
    assert C.due(["ingest.al_adem_sso"], None, st, NOW) == ["ingest.al_adem_sso"]


def test_ran_records_the_stamp(tmp_path):
    p = tmp_path / "feed-cadence.json"
    C.mark_ran("ingest.al_adem_sso", NOW, p)
    C.mark_ran("generic.tx-glo-beach-watch", NOW, p)
    assert json.loads(p.read_text()) == {"generic.tx-glo-beach-watch": stamp(NOW), "ingest.al_adem_sso": stamp(NOW)}


# ---------------------------------------------------------------- the Makefile's ingest loop

needs_make = pytest.mark.skipif(not shutil.which("sh") or not shutil.which("make"), reason="needs sh and make")


def run_ingest(tmp_path, live, stamps, extra_env=None, cadence_works=True):
    """make ingest with a stand-in Python that logs each feed it is asked to run; `-m cadence` goes to the real
    interpreter with a scratch rules file and stamps file."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "rules.json").write_text(json.dumps({"live_states": live}))
    sf = tmp_path / "feed-cadence.json"
    sf.write_text(json.dumps(stamps))
    log = tmp_path / "ran.log"
    log.write_text("")
    stub = tmp_path / "python"
    real = sys.executable if cadence_works else "/bin/false"
    stub.write_text(
        "#!/bin/sh\n"
        f'case "$*" in "-m cadence "*) exec "{real}" "$@" ;; "-m ingest.generic --list") echo tx-glo-beach-watch; '
        "echo wa-kc-cso-status-csv; exit 0 ;; esac\n"
        f'echo "$*" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("MAKE")}
    env.update(DWW_CADENCE_FILE=str(sf), DWW_CADENCE_DATA_DIR=str(data), TIMINGS_FILE=str(tmp_path / "t.tsv"))
    env.update(extra_env or {})
    r = subprocess.run(["make", "--no-print-directory", "-C", str(ROOT), "ingest", f"PYTHON={stub}",
                        "INGEST_MODULES=al_adem_sso ct_deep echo_sewer_overflow_events", "INGEST_PRE=",
                        "INGEST_SNAPSHOTS=", "INGEST_EXTRA="],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return [line for line in log.read_text().splitlines() if line], json.loads(sf.read_text()), r.stdout


@needs_make
def test_the_hourly_run_skips_a_not_live_feed_run_today_and_runs_the_rest(tmp_path):
    recent = stamp(datetime.now(UTC) - timedelta(hours=2))
    ran, stamps, out = run_ingest(tmp_path, ["CT", "WA"], {"ingest.al_adem_sso": recent, "generic.tx-glo-beach-watch": recent})
    assert ran == ["-m ingest.ct_deep", "-m ingest.echo_sewer_overflow_events", "-m ingest.generic wa-kc-cso-status-csv"]
    assert "ingest.al_adem_sso: a state not yet live" in out and "generic.tx-glo-beach-watch: a state not yet live" in out
    assert stamps["ingest.al_adem_sso"] == recent


@needs_make
def test_the_daily_pass_runs_a_not_live_feed_and_records_it(tmp_path):
    old = stamp(datetime.now(UTC) - timedelta(hours=25))
    ran, stamps, _ = run_ingest(tmp_path, ["CT", "WA"], {"ingest.al_adem_sso": old})
    assert ran == ["-m ingest.al_adem_sso", "-m ingest.ct_deep", "-m ingest.echo_sewer_overflow_events",
                   "-m ingest.generic tx-glo-beach-watch", "-m ingest.generic wa-kc-cso-status-csv"]
    assert stamps["ingest.al_adem_sso"] != old and "generic.tx-glo-beach-watch" in stamps
    # live feeds leave no stamp (nothing to decide for them)
    assert "ingest.ct_deep" not in stamps


@needs_make
def test_going_live_makes_the_feed_hourly_and_a_broken_check_runs_everything(tmp_path):
    recent = stamp(datetime.now(UTC) - timedelta(hours=2))
    ran, _, _ = run_ingest(tmp_path, ["CT", "WA", "AL", "TX"], {"ingest.al_adem_sso": recent, "generic.tx-glo-beach-watch": recent})
    assert "-m ingest.al_adem_sso" in ran and "-m ingest.generic tx-glo-beach-watch" in ran
    ran, _, _ = run_ingest(tmp_path, ["CT"], {"ingest.al_adem_sso": recent}, cadence_works=False)
    assert len(ran) == 5
    ran, _, _ = run_ingest(tmp_path, ["CT"], {"ingest.al_adem_sso": recent}, extra_env={"FEEDS_ALL": "1"})
    assert len(ran) == 5


# ---------------------------------------------------------------- the standing name review's daily pass

def test_the_name_review_is_due_once_a_day(tmp_path):
    assert C.daily_due("name-review", {}, NOW)
    assert not C.daily_due("name-review", {"name-review": stamp(NOW - timedelta(hours=3))}, NOW)
    assert C.daily_due("name-review", {"name-review": stamp(NOW - timedelta(hours=23, minutes=45))}, NOW)
    assert C.daily_due("name-review", {"name-review": stamp(NOW - timedelta(hours=3))}, NOW, run_all=True)
    sf = tmp_path / "c.json"
    env = {**os.environ, "DWW_CADENCE_FILE": str(sf)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "cadence", *a], cwd=ROOT / "pipeline", env=env,  # noqa: E731
                                    capture_output=True, text=True).returncode
    assert run("daily", "name-review") == 0
    assert run("ran", "name-review") == 0 and "name-review" in json.loads(sf.read_text())
    assert run("daily", "name-review") == 3


def test_the_refresh_script_runs_the_name_review_on_its_daily_pass_and_fails_open():
    s = (ROOT / "scripts" / "refresh-data.sh").read_text()
    gate = s[s.index("-m cadence daily name-review"):]
    # only an answer of 3 (ran in the last day) skips it; a failing check runs it; a good run is recorded
    assert 'if [ "$nr_due" = 3 ]' in gate and "-m build.name_review --standing" in gate
    assert gate.index("-m build.name_review --standing") < gate.index("-m cadence ran name-review")
    assert s.index("-m cadence daily name-review") < s.index("make tally")
