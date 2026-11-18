"""The e-mail feed split in two (2026-11-18): the private read (pipeline/mailfeed/read.py, run by the site repository's
mail-feed job) and the public link (ingest/operator_mail.py, run by the refresh).

1. The same mail gives the same records: tests/fixtures/mail-feed/golden.json is what the single-process feed wrote
   (ingest/operator_mail.run at 862eb00) for tests/mail_feed_world.py, step by step; the split feed must write the same
   records, health and meta (meta.address is no longer written; meta.inbox is new).
2. No module the refresh runs reads D1 or the raw mail bucket.
3. An inbox that cannot be used keeps every list's records."""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

import common
from ingest import operator_mail as O
from mailfeed import read as R
from tests import mail_feed_world as W

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "ma_context", lambda lists: W.ctx())
    monkeypatch.delenv("DWW_INBOX_DIR", raising=False)
    W.write_others(tmp_path / "events")
    return tmp_path


def at(monkeypatch, now):
    monkeypatch.setattr(common, "now_iso", lambda: now.strftime("%Y-%m-%dT%H:%M:%SZ"))


def test_the_split_feed_writes_what_the_single_process_feed_wrote(world, monkeypatch):
    golden = json.loads(W.GOLDEN.read_text())["steps"]
    assert len(golden) == len(W.STEPS)
    for n, ((now, missing, fail), want) in enumerate(zip(W.STEPS, golden)):
        at(monkeypatch, now)
        W.run_split(world, now, missing, fail)
        got = W.snapshot(world / "events")
        assert sorted(got) == sorted(want)
        for sid in want:
            g, w = got[sid], want[sid]
            assert g["records"] == w["records"], f"step {n} {sid}: records differ"
            for k in ("ok", "error", "count", "fetched_at", "last_ok_at", "prev_ok_at"):
                assert g.get(k) == w.get(k), f"step {n} {sid}: {k}"
            gm = {k: v for k, v in g["meta"].items() if k != "inbox"}
            wm = {k: v for k, v in w["meta"].items() if k != "address"}
            assert gm == wm, f"step {n} {sid}: meta differs"
            assert "address" not in g["meta"] and g["meta"]["inbox"]["key"] == f"inbox/mail/{sid}.json"
    # the world covers what the rules do: a chain linked to the portal, a platform-only notice held back and one kept
    # as a duplicate, a page post, a quiet list, a retried fetch, an index that could not be read
    hol = golden[1]["ma-holyoke-everbridge"]
    assert hol["meta"]["held_platform_only"] == 1 and hol["meta"]["linked_to_portal"] == 4 and hol["meta"]["quiet"]
    assert golden[0]["ma-swsc-cso-email"]["meta"]["results"] == {"fetch_failed": 1, "notice": 1}
    assert golden[1]["nh-manchester-cso-email"]["meta"]["linked_to_page"] == 1
    assert all(f["ok"] is False and f["records"] == golden[1][sid]["records"] for sid, f in golden[2].items())


def test_the_inbox_carries_no_raw_text_subject_or_address(world, monkeypatch):
    now, missing, fail = W.STEPS[1]
    at(monkeypatch, now)
    W.run_split(world, now, missing, fail)
    files = sorted((world / "inbox" / "mail").glob("*.json"))
    assert {f.stem for f in files} == set(W.notice_sources())
    text = "".join(f.read_text() for f in files) + (world / "state" / "inbound-mail.json").read_text()
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)                 # no address at all, ours included
    for leak in ("CSO Notification", "Verification Code", "413-555", "617-555", "wpc.desk", "Hunters are reminded",
                 "Authentication-Results", "Dear Health Official"):
        assert leak not in text, leak
    doc = json.loads((world / "inbox" / "mail" / "ma-holyoke-everbridge.json").read_text())
    assert set(doc) == {"schema", "list_id", "source_id", "written_at", "ok", "error", "stats", "entries"}
    assert all(set(e) == {"id", *R.ENTRY_KEYS} for e in doc["entries"])
    # the records are handed over unplaced; the refresh places them
    rec = next(r for e in doc["entries"] for r in e["records"])
    assert rec["lat"] is None and rec["water_slugs"] == [] and "_coords" not in rec["raw"]


@pytest.mark.parametrize("case", ["absent", "stale", "failed", "unreadable", "other schema"])
def test_an_inbox_that_cannot_be_used_keeps_every_list(world, monkeypatch, case):
    now, missing, fail = W.STEPS[1]
    at(monkeypatch, now)
    W.run_split(world, now, missing, fail)
    before = W.snapshot(world / "events")
    later = now + timedelta(hours=1)
    at(monkeypatch, later)
    for f in (world / "inbox" / "mail").glob("*.json"):
        doc = json.loads(f.read_text())
        if case == "absent":
            f.unlink()
            continue
        if case == "stale":
            doc["written_at"] = (later - timedelta(hours=O.INBOX_MAX_AGE_H, minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif case == "failed":
            doc.update(ok=False, error="the inbound mail index could not be read: HTTP 403", entries=[])
        elif case == "other schema":
            doc["schema"] = 99
        f.write_text("{not json" if case == "unreadable" else json.dumps(doc))
    monkeypatch.setenv("DWW_INBOX_DIR", str(world))
    assert O.run(W.LISTS, world / "events", now=later) == 1
    after = W.snapshot(world / "events")
    for sid, f in after.items():
        assert f["ok"] is False and f["records"] == before[sid]["records"] and f["count"] == before[sid]["count"]
        assert f["error"] and f["meta"]["inbox"]["key"].endswith(f"{sid}.json")
        assert f["last_ok_at"] == before[sid]["last_ok_at"]
    words = {"absent": "no file", "stale": "more than 3 hours ago", "failed": "could not be read",
             "unreadable": "not JSON", "other schema": "expected form"}[case]
    assert all(words in f["error"] for f in after.values())


def test_a_fresh_inbox_that_is_old_but_within_the_limit_is_used(world, monkeypatch):
    now, missing, fail = W.STEPS[1]
    at(monkeypatch, now)
    W.run_split(world, now, missing, fail)
    later = now + timedelta(hours=O.INBOX_MAX_AGE_H) - timedelta(minutes=5)
    at(monkeypatch, later)
    monkeypatch.setenv("DWW_INBOX_DIR", str(world))
    assert O.run(W.LISTS, world / "events", now=later) == 0
    f = W.snapshot(world / "events")["ma-swsc-cso-email"]
    assert f["ok"] is True and f["count"] == 2 and f["meta"]["inbox"]["age_hours"] == pytest.approx(2.92, abs=0.01)


def test_the_private_read_writes_failure_files_and_no_state_when_the_index_fails(tmp_path):
    rows, raws = W.rows_and_raws()
    assert R.run(W.FakeTransport(rows, raws, fail_rows=True), W.LISTS, tmp_path / "s.json", tmp_path / "out",
                 now=W.NOW) == 1
    assert not (tmp_path / "s.json").exists()
    for f in (tmp_path / "out").glob("*.json"):
        doc = json.loads(f.read_text())
        assert doc["ok"] is False and doc["entries"] == [] and "403" in doc["error"]
    assert R.run(None, W.LISTS, tmp_path / "s.json", tmp_path / "out", now=W.NOW) == 1
    assert "credentials" in json.loads((tmp_path / "out" / "ma-swsc-cso-email.json").read_text())["error"]


def test_errors_never_carry_the_account_or_an_address(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "0123456789abcdef0123456789abcdef")
    s = R.safe("Could not route to /accounts/0123456789abcdef0123456789abcdef/d1/database (owner@example.com)")
    assert "0123456789abcdef" not in s and "@" not in s and "[account]" in s


# ---------------------------------------------------------------- the refresh reads neither D1 nor the raw bucket

D1_CALL = re.compile(r"""\bd1\s+execute\b|["']d1["']\s*,\s*["']execute["']|/d1/database|\bd1_databases\b|"""
                     r"""\bD1_DATABASE(?:_ID)?\b|\bdatabase_id\b""", re.I)
RAW_BUCKET = re.compile(r"dirtywaterwatch-raw")


def refresh_files() -> list[Path]:
    """What the hourly refresh runs: every pipeline module but the tests and the private mail read (mailfeed/), the
    scripts, the Makefile and the refresh workflow."""
    py = [p for p in (ROOT / "pipeline").rglob("*.py")
          if not {".venv", "tests", "mailfeed", "__pycache__"} & set(p.relative_to(ROOT / "pipeline").parts)]
    return py + sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "scripts").glob("*.sh")) + \
        [ROOT / "Makefile", ROOT / ".github" / "workflows" / "refresh.yml"]


def code_lines(p: Path) -> str:
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix == ".py":
        return text                     # docstrings count: a module the refresh runs does not name the raw bucket
    return "\n".join(x for x in text.splitlines() if not x.lstrip().startswith("#"))


def test_no_module_the_refresh_runs_reads_d1_or_names_the_raw_bucket():
    files = refresh_files()
    assert any(p.name == "operator_mail.py" for p in files) and any(p.name == "ri_nbc.py" for p in files)
    bad = [f"{p.relative_to(ROOT)}: {m.group(0)}" for p in files for rx in (D1_CALL, RAW_BUCKET)
           for m in [rx.search(code_lines(p))] if m]
    assert not bad, bad


def test_no_module_the_refresh_runs_imports_the_private_read():
    bad = [str(p.relative_to(ROOT)) for p in refresh_files() if p.suffix == ".py"
           and re.search(r"^\s*(?:from\s+mailfeed\b|import\s+mailfeed\b)", p.read_text(errors="replace"), re.M)]
    assert not bad, bad


def test_the_private_read_is_never_a_refresh_feed():
    make = (ROOT / "Makefile").read_text()
    assert "pipeline/ingest/*.py" in make                  # INGEST_MODULES: ingest/*.py only, not mailfeed/
    assert not (ROOT / "pipeline" / "ingest" / "mailfeed").exists()
    assert "mailfeed" not in (ROOT / ".github" / "workflows" / "refresh.yml").read_text()


def test_an_index_that_answers_no_rows_is_a_failed_read_not_an_empty_list(world, monkeypatch):
    # the mail index only grows: no rows at all is a wrong database or a broken query, never "no mail"; the lists keep
    # their records rather than being emptied by a healthy-looking read of nothing
    now, missing, fail = W.STEPS[1]
    at(monkeypatch, now)
    W.run_split(world, now, missing, fail)
    before = W.snapshot(world / "events")
    (world / "state" / "inbound-mail.json").unlink()            # a lost state as well: nothing to fall back on
    later = now + timedelta(hours=1)
    at(monkeypatch, later)
    assert R.run(W.FakeTransport([], {}), W.LISTS, world / "state" / "inbound-mail.json", world / "inbox" / "mail",
                 now=later) == 1
    monkeypatch.setenv("DWW_INBOX_DIR", str(world))
    O.run(W.LISTS, world / "events", now=later)
    for sid, f in W.snapshot(world / "events").items():
        assert f["ok"] is False and "no rows" in f["error"] and f["records"] == before[sid]["records"]
