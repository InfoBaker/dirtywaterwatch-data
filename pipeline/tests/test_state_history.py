"""scripts/state_paths.py history copies of state/build.tar.gz: the records per source (counts), the history guard
(a drop holds the restored archive under state/held/ and warns; the save goes on) and the daily ring and monthly
copies (generations plan|put), against a stand-in wrangler that keeps objects in a folder. No network.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("state_paths_history", ROOT / "scripts" / "state_paths.py")
SP = importlib.util.module_from_spec(_spec)
sys.modules["state_paths_history"] = SP          # dataclasses look their module up there
_spec.loader.exec_module(SP)

SAT = datetime(2026, 11, 21, 15, 7, tzinfo=timezone.utc)
SENTINEL = "RECORD-TEXT-SENTINEL"                  # in every record: never in anything printed or written by the guard

WRANGLER = r"""#!/bin/sh
# stand-in: wrangler r2 object get|put BUCKET/KEY --file F --remote, objects kept under $FAKE_R2
key="${4#*/}"
case "$3" in
  get)
    [ -f "$FAKE_R2/$key" ] || { : > "$6"; echo "X [ERROR] The specified key does not exist."; exit 1; }
    cp "$FAKE_R2/$key" "$6"; echo "$key" >> "$FAKE_R2/.gets" ;;
  put)
    case " $FAKE_R2_FAIL_PUT " in *" $key "*) echo "X [ERROR] upload failed"; exit 1 ;; esac
    mkdir -p "$FAKE_R2/$(dirname "$key")"; cp "$6" "$FAKE_R2/$key"; echo "$key" >> "$FAKE_R2/.puts" ;;
esac
"""


@pytest.fixture
def r2(tmp_path, monkeypatch):
    """The stand-in bucket: a folder; WRANGLER points at the stand-in."""
    w = tmp_path / "bin" / "wrangler"
    w.parent.mkdir()
    w.write_text(WRANGLER)
    w.chmod(0o755)
    bucket = tmp_path / "r2"
    bucket.mkdir()
    monkeypatch.setenv("WRANGLER", str(w))
    monkeypatch.setenv("FAKE_R2", str(bucket))
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "")
    monkeypatch.setenv("STATE_FETCH_RETRY_S", "0")
    return bucket


def puts(bucket: Path) -> list[str]:
    p = bucket / ".puts"
    return p.read_text().split() if p.exists() else []


def records(n: int, sid: str = "s", dup: int = 0, missing: int = 0) -> list[dict]:
    out = []
    for i in range(n):
        raw = {"note": SENTINEL}
        if i < missing:
            raw["_missing_from_source_since"] = "2026-11-01T00:00:00Z"
        out.append({"event_id": f"{sid}:{i}", "duplicate_of": "other:1" if i < dup else None, "raw": raw})
    return out


def build_dir(root: Path, sources: dict) -> Path:
    """data/build with events/<source>.json for each {source: n records}."""
    b = root / "data" / "build"
    (b / "events").mkdir(parents=True, exist_ok=True)
    for sid, n in sources.items():
        (b / "events" / f"{sid}.json").write_text(json.dumps({"source_id": sid, "records": records(n, sid)}))
    return b


def tarball(root: Path, out: Path) -> Path:
    with tarfile.open(out, "w:gz") as tf:
        tf.add(root / "data", arcname="data")
    return out


# ---------------------------------------------------------------- counts

def test_counts_of_the_folder_and_of_the_tarball_agree(tmp_path, capsys):
    root = tmp_path / "ws"
    b = build_dir(root, {"empty": 0})
    (b / "events" / "ca-spills.json").write_text(json.dumps({"records": records(6, "ca", dup=2, missing=1)}))
    (b / "events" / "broken.json").write_text('{"records": [')                 # cut short
    (b / "events" / "not-events.json").write_text('{"x": 1}')
    (b / "events" / "._ca-spills.json").write_text("mac")                     # AppleDouble: not a source
    (b / "events" / "sub").mkdir()
    (b / "other.json").write_text(json.dumps({"records": records(9)}))        # not in events/
    want = {"broken": {"unreadable": True},
            "ca-spills": {"records": 6, "duplicate_of": 2, "missing_from_source": 1},
            "empty": {"records": 0, "duplicate_of": 0, "missing_from_source": 0},
            "not-events": {"unreadable": True}}
    assert SP.event_counts(b) == want
    assert SP.event_counts(tarball(root, tmp_path / "build.tar.gz")) == want
    out = tmp_path / "restored-counts.json"
    assert SP.main(["counts", str(b), str(out)]) == 0
    assert json.loads(out.read_text())["sources"] == want
    printed = capsys.readouterr().out
    assert "4 events file(s), 6 record(s) counted in build" in printed
    assert SENTINEL not in printed and SENTINEL not in out.read_text()


def test_counts_of_a_damaged_tarball_fail_cleanly(tmp_path, capsys):
    root = tmp_path / "ws"
    build_dir(root, {"a": 3})
    good = tarball(root, tmp_path / "good.tar.gz").read_bytes()
    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(good[: len(good) // 2])
    assert SP.main(["counts", str(cut), str(tmp_path / "c.json")]) == 1
    assert "could not be counted" in capsys.readouterr().out and not (tmp_path / "c.json").exists()


# ---------------------------------------------------------------- what is a drop

@pytest.mark.parametrize("before,after,drop", [
    (500, 495, True),      # 5 records and exactly 1%
    (500, 496, False),     # 4 records: under the 5
    (1000, 991, False),    # 9 records: under 1%
    (1000, 990, True),     # 10 records: exactly 1%
    (4, 0, False),         # all of a small file, but 4 records
    (5, 0, True),
    (3567, 218, True),     # a backfill cut to a 60-day window
    (100, 120, False),     # grew
    (100, 100, False),
])
def test_drop_thresholds(before, after, drop):
    got = SP.history_drops({"s": {"records": before}}, {"s": {"records": after}})
    assert bool(got) is drop
    if drop:
        assert got[0]["why"] == "records fell" and got[0]["before"]["records"] == before


def test_a_vanished_or_unreadable_file_is_a_drop_whatever_its_size():
    got = SP.history_drops({"gone": {"records": 0}, "bad": {"records": 2}, "was-bad": {"unreadable": True},
                            "steady": {"records": 7}},
                           {"bad": {"unreadable": True}, "was-bad": {"records": 0}, "steady": {"records": 7},
                            "new": {"records": 50}})
    assert [(d["source"], d["why"], d["after"]) for d in got] == [("bad", "events file unreadable", None),
                                                                   ("gone", "events file gone", None)]


# ---------------------------------------------------------------- the guard

def restored_state(tmp_path: Path, sources: dict) -> tuple[Path, Path, Path]:
    """(data/build, the restored archive, its counts) as the restore step leaves them."""
    root = tmp_path / "ws"
    b = build_dir(root, sources)
    arch = tarball(root, tmp_path / "restored-build.tar.gz")
    counts = tmp_path / "restored-counts.json"
    SP.write_counts(b, counts, SAT)
    return b, arch, counts


def test_guard_first_run_compares_nothing(tmp_path, r2, capsys):
    b = build_dir(tmp_path / "ws", {"a": 10})
    out = b / "history-guard.json"
    assert SP.guard(tmp_path / "restored-counts.json", b, out, tmp_path / "restored-build.tar.gz", "1", SAT) == []
    assert "no restored state (a first run); nothing to compare" in capsys.readouterr().out
    assert puts(r2) == [] and not out.exists()


def test_guard_without_a_drop_uploads_and_writes_nothing(tmp_path, r2, capsys):
    b, arch, counts = restored_state(tmp_path, {"a": 300, "b": 10})
    (b / "events" / "a.json").write_text(json.dumps({"records": records(298)}))     # 2 fewer: not a drop
    assert SP.guard(counts, b, b / "history-guard.json", arch, "1", SAT) == []
    assert "2 source(s) compared with the restored state; no drop" in capsys.readouterr().out
    assert puts(r2) == [] and not (b / "history-guard.json").exists()


def test_guard_drop_holds_the_restored_archive_warns_with_counts_only_and_keeps_earlier_runs(tmp_path, r2, capsys):
    b, arch, counts = restored_state(tmp_path, {"ca-spills": 3567, "gone": 3, "steady": 10})
    (b / "events" / "ca-spills.json").write_text(json.dumps({"records": records(218)}))
    (b / "events" / "gone.json").unlink()
    out = b / "history-guard.json"
    drops = SP.guard(counts, b, out, arch, "1234", SAT)
    assert [d["source"] for d in drops] == ["ca-spills", "gone"]
    key = "state/held/build-2026-11-21-1234.tar.gz"
    assert puts(r2) == [key] and (r2 / key).read_bytes() == arch.read_bytes()
    printed = capsys.readouterr().out
    warnings = [x for x in printed.splitlines() if x.startswith("::warning::")]
    assert warnings == [
        "::warning::history guard: ca-spills: records fell, 3567 record(s) restored, 218 now; the state is saved as "
        "usual",
        "::warning::history guard: gone: events file gone, 3 record(s) restored, none readable now; the state is "
        "saved as usual"]
    assert f"the restored state is held at {key}" in printed
    g = json.loads(out.read_text())
    assert g["time"] == "2026-11-21T15:07:00Z" and g["run"] == "1234" and g["held"] == {"key": key, "uploaded": True}
    assert g["drops"][0]["before"]["records"] == 3567 and g["drops"][0]["after"]["records"] == 218
    assert g["earlier"] == []
    assert SENTINEL not in printed and SENTINEL not in out.read_text()
    # a later drop run keeps this one below it, with its held key
    SP.write_counts(b, counts, SAT)
    (b / "events" / "steady.json").unlink()
    SP.guard(counts, b, out, arch, "1240", SAT + timedelta(hours=6))
    g2 = json.loads(out.read_text())
    assert g2["run"] == "1240" and g2["earlier"][0]["run"] == "1234" and g2["earlier"][0]["held"]["key"] == key


def test_guard_counts_the_kept_archive_when_the_restored_counts_are_missing(tmp_path, r2, capsys):
    b, arch, counts = restored_state(tmp_path, {"a": 100})
    counts.unlink()
    (b / "events" / "a.json").write_text(json.dumps({"records": records(10)}))
    assert [d["source"] for d in SP.guard(counts, b, b / "history-guard.json", arch, "7", SAT)] == ["a"]
    assert "counted from restored-build.tar.gz" in capsys.readouterr().out
    assert puts(r2) == ["state/held/build-2026-11-21-7.tar.gz"]


def test_guard_held_upload_that_fails_is_a_warning_and_recorded(tmp_path, r2, monkeypatch, capsys):
    b, arch, counts = restored_state(tmp_path, {"a": 100})
    (b / "events" / "a.json").unlink()
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "state/held/build-2026-11-21-7.tar.gz")
    monkeypatch.setenv("STATE_NOW", "2026-11-21T15:07:00Z")                 # the held key's date: the CLI's clock
    assert SP.main(["guard", str(counts), "--build", str(b), "--out", str(b / "history-guard.json"),
                    "--restored", str(arch), "--run-id", "7"]) == 0          # the save goes on
    assert "::warning::history guard: the restored state could not be held" in capsys.readouterr().out
    assert json.loads((b / "history-guard.json").read_text())["held"]["uploaded"] is False


# ---------------------------------------------------------------- the generations

def test_daily_ring_key_by_weekday():
    monday = datetime(2026, 11, 16, 0, 7, tzinfo=timezone.utc)
    keys = [SP.generations_due({}, monday + timedelta(days=i))[0]["key"] for i in range(8)]
    assert keys == [f"state/daily/build-{d}.tar.gz" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon")]
    for k in keys:
        assert SP.GENERATION_KEY.fullmatch(k) and SP.STATE_KEY.fullmatch(k)


def run_day(rec_path: Path, src: Path, now: datetime, run: str) -> tuple[list[str], list[str]]:
    """One run's two calls: plan before the archive, put after the save. (planned keys, copies made)."""
    planned = SP.generations_plan(rec_path, run, now)
    return planned, SP.generations_put(src, rec_path, run, now)


def gets(bucket: Path) -> list[str]:
    p = bucket / ".gets"
    return p.read_text().split() if p.exists() else []


def test_monthly_once_a_month_and_daily_once_a_day(tmp_path, r2):
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    both = ["state/daily/build-Sat.tar.gz", "state/monthly/build-2026-11.tar.gz"]
    assert run_day(rec, src, SAT, "1") == (both, both)
    assert puts(r2) == ["state/daily/build-Sat.tar.gz", "state/daily/build-Sat.json",
                        "state/monthly/build-2026-11.tar.gz", "state/monthly/build-2026-11.json"]
    assert json.loads((r2 / "state/monthly/build-2026-11.json").read_text()) == {
        "key": "state/monthly/build-2026-11.tar.gz", "date": "2026-11-21", "run": "1",
        "made_at": "2026-11-21T15:07:00Z", "bytes": 7}
    assert run_day(rec, src, SAT + timedelta(hours=7), "2") == ([], [])       # same day: recorded, none due
    assert gets(r2) == ["state/daily/build-Sat.json", "state/monthly/build-2026-11.json"]
    assert run_day(rec, src, datetime(2026, 11, 22, 0, 7, tzinfo=timezone.utc), "3")[0] == \
        ["state/daily/build-Sun.tar.gz"]
    assert run_day(rec, src, datetime(2026, 11, 30, 23, 7, tzinfo=timezone.utc), "4")[0] == \
        ["state/daily/build-Mon.tar.gz"]
    assert run_day(rec, src, datetime(2026, 12, 1, 0, 7, tzinfo=timezone.utc), "5")[0] == \
        ["state/daily/build-Tue.tar.gz", "state/monthly/build-2026-12.tar.gz"]
    # a week on, the ring key is overwritten; the monthly keys stay
    assert run_day(rec, src, SAT + timedelta(days=7), "6")[0] == ["state/daily/build-Sat.tar.gz"]
    SP.generations_plan(rec, "7", SAT + timedelta(days=7, hours=1))
    r = json.loads(rec.read_text())
    assert r["daily"]["Sat"] == {"date": "2026-11-28", "run": "6"}
    assert sorted(r["monthly"]) == ["2026-11", "2026-12"] and "pending" not in r
    assert puts(r2).count("state/monthly/build-2026-11.tar.gz") == 1


def test_a_failed_copy_is_not_recorded_and_the_next_run_makes_it(tmp_path, r2, monkeypatch, capsys):
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "state/daily/build-Sat.tar.gz")
    assert run_day(rec, src, SAT, "1")[1] == ["state/monthly/build-2026-11.tar.gz"]
    assert "::warning::state generation state/daily/build-Sat.tar.gz was not uploaded" in capsys.readouterr().out
    assert "state/daily/build-Sat.json" not in puts(r2)                      # no marker for a copy that failed
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "")
    assert run_day(rec, src, SAT + timedelta(hours=1), "2") == (["state/daily/build-Sat.tar.gz"],
                                                                ["state/daily/build-Sat.tar.gz"])
    r = json.loads(rec.read_text())
    assert "Sat" not in r.get("daily", {}) and r["monthly"]["2026-11"]["run"] == "1"
    SP.generations_plan(rec, "3", SAT + timedelta(hours=2))
    assert json.loads(rec.read_text())["daily"]["Sat"]["run"] == "2"


def test_a_failed_marker_leaves_the_copy_unrecorded_and_it_is_made_again(tmp_path, r2, monkeypatch, capsys):
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "state/daily/build-Sat.json")
    assert run_day(rec, src, SAT, "1")[1] == ["state/monthly/build-2026-11.tar.gz"]
    assert "uploaded but its marker state/daily/build-Sat.json did not" in capsys.readouterr().out
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "")
    assert run_day(rec, src, SAT + timedelta(hours=1), "2")[0] == ["state/daily/build-Sat.tar.gz"]


def test_a_marker_from_an_earlier_week_records_nothing(tmp_path, r2):
    """Last week's marker is still at the ring key: a pending copy of this week whose upload failed is not taken for
    it."""
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    (r2 / "state/daily").mkdir(parents=True)
    (r2 / "state/daily/build-Sat.json").write_text(json.dumps(
        {"key": "state/daily/build-Sat.tar.gz", "date": "2026-11-14", "run": "1"}))
    SP.generations_plan(rec, "9", SAT)                                       # pending, its upload never made
    SP.generations_plan(rec, "10", SAT + timedelta(hours=1))
    r = json.loads(rec.read_text())
    assert "Sat" not in r.get("daily", {}) and r["pending"]["run"] == "10"
    assert [g["key"] for g in r["pending"]["copies"]][0] == "state/daily/build-Sat.tar.gz"


def test_when_every_upload_fails_nothing_is_recorded_and_both_are_due_again(tmp_path, r2, monkeypatch):
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "state/daily/build-Sat.tar.gz state/monthly/build-2026-11.tar.gz")
    assert run_day(rec, src, SAT, "1")[1] == []
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "")
    assert len(SP.generations_plan(rec, "2", SAT + timedelta(hours=1))) == 2


def test_the_plan_claims_nothing_and_a_plan_from_another_run_is_not_put(tmp_path, r2):
    """The record saved in the archive (written by plan) names no copy; a pending plan restored from an earlier run
    is never uploaded by this run's put."""
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    SP.generations_plan(rec, "1", SAT)
    r = json.loads(rec.read_text())
    assert r["pending"]["run"] == "1" and not r.get("daily") and not r.get("monthly")
    assert SP.generations_due(r, SAT) != []                                     # still due by the record
    assert SP.generations_put(src, rec, "2", SAT) == [] and puts(r2) == []


def test_a_marker_that_cannot_be_read_records_nothing(tmp_path, monkeypatch):
    """No wrangler at all (or R2 down): the earlier run's copies stay unrecorded and are due again."""
    monkeypatch.setenv("WRANGLER", str(tmp_path / "not-installed"))
    monkeypatch.setenv("STATE_FETCH_RETRY_S", "0")
    rec = tmp_path / "state-generations.json"
    SP.generations_plan(rec, "1", SAT)
    assert len(SP.generations_plan(rec, "2", SAT + timedelta(hours=1))) == 2


def test_generations_cli(tmp_path, r2, monkeypatch, capsys):
    monkeypatch.setenv("STATE_NOW", "2026-11-21T15:07:00Z")
    monkeypatch.setenv("GITHUB_RUN_ID", "88")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    rec = tmp_path / "state-generations.json"
    assert SP.main(["generations", "plan", "--record", str(rec)]) == 0
    assert "generation due: state/daily/build-Sat.tar.gz" in capsys.readouterr().out
    assert SP.main(["generations", "put", "--record", str(rec)]) == 2         # no archive named
    src = tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    monkeypatch.setenv("FAKE_R2_FAIL_PUT", "state/daily/build-Sat.tar.gz")
    assert SP.main(["generations", "put", str(src), "--record", str(rec)]) == 0   # a failed copy: a warning only
    assert puts(r2) == ["state/monthly/build-2026-11.tar.gz", "state/monthly/build-2026-11.json"]
    monkeypatch.setenv("GITHUB_RUN_ID", "89")
    assert SP.main(["generations", "put", str(src), "--record", str(rec)]) == 0   # nothing planned by this run
    assert SP.main(["generations", "plan", "--record", str(rec), "--run-id", "../x"]) == 2


# ---------------------------------------------------------------- keys and run ids

@pytest.mark.parametrize("key", ["state/build.tar.gz", "current/meta.json", "current/state/daily/build-Sat.tar.gz",
                                 "state/daily/build-Funday.tar.gz", "state/daily/build-sat.tar.gz",
                                 "state/monthly/build-2026-13.tar.gz", "state/held/build-2026-11-21-../x.tar.gz",
                                 "state/held/build-2026-11-21-.tar.gz", "state/daily/../build.tar.gz",
                                 "state/PAUSE", "out/events.json", "state/held/build-2026-11-21-1.json",
                                 "state/daily/build-Sat.txt", "state/monthly/build-2026-11.json/x"])
def test_put_writes_history_copies_only(tmp_path, r2, key):
    src = tmp_path / "f"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        SP.put(key, src)
    assert puts(r2) == []


def test_history_copies_may_be_fetched_and_the_other_keys_stand():
    for k in ("state/daily/build-Sun.tar.gz", "state/monthly/build-2026-11.tar.gz",
              "state/held/build-2026-11-21-1234.tar.gz", "state/held/build-2026-11-21-1234-a2.tar.gz",
              "state/daily/build-Sun.json", "state/monthly/build-2026-11.json", "state/build.tar.gz", "state/PAUSE"):
        assert SP.STATE_KEY.fullmatch(k), k
    for k in ("state/daily/x.tar.gz", "state/held/x.tar.gz", "current/x.tar.gz", "state/monthly/build-26-11.tar.gz"):
        assert not SP.STATE_KEY.fullmatch(k), k
    with pytest.raises(ValueError):
        SP.generation_key("held", "2026-11-21-1")                              # held copies are the guard's only


def test_run_token(monkeypatch):
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    assert SP.run_token() == "local"
    monkeypatch.setenv("GITHUB_RUN_ID", "19633452001")
    assert SP.run_token() == "19633452001"
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert SP.run_token() == "19633452001-a2"                                  # a re-run keeps the first one's copy
    assert SP.run_token("77") == "77"
    for bad in ("../x", "a/b", "-x", "x" * 41):
        with pytest.raises(ValueError):
            SP.run_token(bad)


# ---------------------------------------------------------------- Astra review 2026-11-21 (state generations)

def test_p1_1_guard_with_no_build_folder_holds_the_restored_archive(tmp_path, r2, capsys):
    """A refresh that removed data/build whole: every restored source is gone, and the restored archive is held."""
    import shutil
    b, arch, counts = restored_state(tmp_path, {"a": 100, "b": 3})
    shutil.rmtree(b)
    drops = SP.guard(counts, b, tmp_path / "history-guard.json", arch, "5", SAT)
    assert [(d["source"], d["why"]) for d in drops] == [("a", "events file gone"), ("b", "events file gone")]
    assert puts(r2) == ["state/held/build-2026-11-21-5.tar.gz"]
    assert not b.exists()                                                     # the guard never makes the folder


def test_p1_1_plan_never_creates_a_missing_build_folder(tmp_path, capsys):
    rec = tmp_path / "gone" / "build" / "state-generations.json"
    assert SP.generations_plan(rec, "1", SAT) == []
    assert not (tmp_path / "gone").exists()
    assert "::warning::" in capsys.readouterr().out
    assert SP.main(["generations", "plan", "--record", str(rec)]) == 0 and not (tmp_path / "gone").exists()


@pytest.mark.parametrize("now,restored,ok", [
    ({"a": 3}, {"a": 3, "b": 1}, True),          # events files there: the guard's business, the save goes on
    (None, {"a": 3}, False),                      # data/build/events missing
    ({}, {"a": 3}, False),                        # data/build/events empty
    ("nofolder", {"a": 3}, False),                # data/build missing whole
    ({}, {}, True),                               # the restored state had no events file either
])
def test_p1_1_save_check_refuses_to_save_over_a_history_with_nothing(tmp_path, capsys, now, restored, ok):
    import shutil
    b, arch, counts = restored_state(tmp_path, restored)
    shutil.rmtree(b / "events")
    if now == "nofolder":
        shutil.rmtree(b)
    elif now is not None:
        build_dir(tmp_path / "ws", now)
    args = ["save-check", str(counts), "--build", str(b), "--restored", str(arch)]
    assert SP.main(args) == (0 if ok else 1)
    out = capsys.readouterr().out
    assert ("::error::" in out) is (not ok)
    # the counts missing: the kept archive is counted instead, with the same answer
    counts.unlink()
    assert SP.main(args) == (0 if ok else 1)


def test_p1_1_save_check_on_a_first_run_passes(tmp_path):
    b = tmp_path / "ws" / "data" / "build"
    b.mkdir(parents=True)
    assert SP.main(["save-check", str(tmp_path / "none.json"), "--build", str(b),
                    "--restored", str(tmp_path / "none.tar.gz")]) == 0


STALL = r"""#!/bin/sh
# stand-in: hangs (a stalled upload or read); its sleep's pid is written so the test can see it killed
sleep 60 & echo $! > "$STALL_PID"; wait
"""


def stalled(tmp_path: Path, monkeypatch) -> Path:
    w = tmp_path / "stall" / "wrangler"
    w.parent.mkdir()
    w.write_text(STALL)
    w.chmod(0o755)
    monkeypatch.setenv("WRANGLER", str(w))
    monkeypatch.setenv("STALL_PID", str(tmp_path / "stall" / "pid"))
    monkeypatch.setenv("STATE_FETCH_RETRY_S", "0")
    return tmp_path / "stall" / "pid"


def gone(pid_file: Path) -> bool:
    import os
    import time
    pid = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


@pytest.mark.parametrize("op", ["put", "fetch"])
def test_p1_2_a_stalled_operation_is_killed_at_its_total_deadline(tmp_path, monkeypatch, op):
    import time
    pid = stalled(tmp_path, monkeypatch)
    monkeypatch.setattr(SP, "MIN_OPTIONAL_S", 0.5)                         # a short deadline, to keep the test short
    src = tmp_path / "f"
    src.write_bytes(b"x")
    t0 = time.monotonic()
    if op == "put":
        assert SP.put("state/daily/build-Sat.tar.gz", src, tries=3, budget_s=1.5) == SP.FAILED
    else:
        assert SP.fetch("state/daily/build-Sat.json", tmp_path / "m.json", tries=3, budget_s=1.5) == SP.FAILED
    assert time.monotonic() - t0 < 10                                       # retries included
    assert gone(pid)                                                        # the whole process group killed


def test_p1_2_optional_operations_are_skipped_close_to_the_job_limit(tmp_path, r2, monkeypatch, capsys):
    import time
    start = tmp_path / "job-started"
    monkeypatch.setenv("STATE_JOB_START_FILE", str(start))
    start.write_text(str(int(time.time()) - 90 * 60))                      # 90 of the 100 minutes gone
    assert SP.optional_budget("held") < SP.MIN_OPTIONAL_S
    b, arch, counts = restored_state(tmp_path, {"a": 100})
    (b / "events" / "a.json").unlink()
    SP.guard(counts, b, tmp_path / "history-guard.json", arch, "5", SAT)
    out = capsys.readouterr().out
    assert "skipped" in out and "::warning::history guard: the restored state could not be held" in out
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    assert SP.generations_plan(rec, "1", SAT) and SP.generations_put(src, rec, "1", SAT) == []
    assert puts(r2) == []
    # with time to spare, each operation still has its own cap
    start.write_text(str(int(time.time()) - 84 * 60))                      # a minute before the reserve
    assert SP.MIN_OPTIONAL_S <= SP.optional_budget("copy") <= 61
    start.write_text(str(int(time.time())))
    assert SP.optional_budget("copy") == SP.OPTIONAL_CAP_S["copy"]


def test_p2_3_an_unreadable_restored_file_that_vanishes_is_a_drop(tmp_path, r2, capsys):
    assert [(d["source"], d["why"]) for d in SP.history_drops({"lost": {"unreadable": True}}, {})] == \
        [("lost", "events file gone")]
    b, arch, counts = restored_state(tmp_path, {"a": 3})
    (b / "events" / "lost.json").write_text('{"records": [')
    SP.write_counts(b, counts, SAT)
    (b / "events" / "lost.json").unlink()
    SP.guard(counts, b, tmp_path / "history-guard.json", arch, "5", SAT)
    out = capsys.readouterr().out
    assert "::warning::history guard: lost: events file gone, an unknown number of record(s) restored" in out
    assert puts(r2) == ["state/held/build-2026-11-21-5.tar.gz"]


@pytest.mark.parametrize("bad", [
    {"daily": None, "monthly": None},
    {"daily": [], "monthly": "x"},
    {"daily": {"Sat": None, "Funday": {"date": "2026-11-21"}}, "monthly": {"2026-11": None, "x": {}}},
    {"daily": {"Sat": {"date": 5}}, "monthly": {"2026-13": {"date": "2026-11-01"}}},
])
def test_p2_4_a_malformed_record_is_repaired_and_copies_go_on(tmp_path, r2, bad):
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    # the previous run left the day's daily pending (with a junk entry beside it), and its marker says it uploaded
    (r2 / "state/daily").mkdir(parents=True)
    (r2 / "state/daily/build-Sat.json").write_text(json.dumps(
        {"key": "state/daily/build-Sat.tar.gz", "date": "2026-11-21", "run": "1"}))
    rec.write_text(json.dumps({**bad, "pending": {"run": "1", "copies": [
        {"kind": "daily", "slot": "Sat", "date": "2026-11-21"}, "junk", {"kind": "held", "slot": "x"}]}}))
    assert run_day(rec, src, SAT + timedelta(hours=1), "2") == (["state/monthly/build-2026-11.tar.gz"],
                                                                ["state/monthly/build-2026-11.tar.gz"])
    r = json.loads(rec.read_text())                                         # repaired and saved that way
    assert r["daily"] == {"Sat": {"date": "2026-11-21", "run": "1"}} and isinstance(r["monthly"], dict)
    assert all(isinstance(v, dict) for v in r["monthly"].values())
    assert run_day(rec, src, SAT + timedelta(hours=2), "3") == ([], [])     # the next run: recorded, none due
    assert list(json.loads(rec.read_text())["monthly"]) == ["2026-11"]


@pytest.mark.parametrize("bad", ["[]", "null", '"text"', '{"pending": "x"}', '{"pending": {"run": 5, "copies": 3}}'])
def test_p2_4_a_record_of_the_wrong_shape_starts_again(tmp_path, r2, bad):
    rec, src = tmp_path / "state-generations.json", tmp_path / "build.tar.gz"
    src.write_bytes(b"archive")
    rec.write_text(bad)
    assert len(run_day(rec, src, SAT, "2")[1]) == 2
    assert run_day(rec, src, SAT + timedelta(hours=1), "3") == ([], [])
