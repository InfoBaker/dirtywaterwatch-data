"""scripts/state_paths.py: the raw-cache list (cached answers only, never bulk raw saves), the pack with its size cap,
and the restore that writes only listed members.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("state_paths", ROOT / "scripts" / "state_paths.py")
SP = importlib.util.module_from_spec(_spec)
sys.modules["state_paths"] = SP          # dataclasses look their module up there
_spec.loader.exec_module(SP)

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def put(root: Path, rel: str, text: str = "{}") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    put(root, "data/raw/nhd-waters/nldi/ab12.json")
    put(root, "data/raw/nhd-waters/nldi-requests.json", "[1.0]")
    put(root, "data/raw/osm-waters/x.json")
    put(root, "data/raw/census/cb_2023_us_state_500k.zip", "zip")
    put(root, "data/raw/census/other.zip", "zip")                        # not the outlines: not listed
    put(root, "data/raw/iem-iemre/41.80_-71.40_2026.json")
    put(root, "data/raw/ri-nbc/rigis-nbc-sewer-overflows.json")
    put(root, "data/raw/ri-nbc/20261104T120000Z.pins.json")               # a stamped bulk save: not listed
    put(root, "data/raw/ri-ridoh-beaches/ridohgis-beaches-view.json")
    put(root, "data/raw/dc-waters/boundary-dcgis.json")
    put(root, "data/raw/dc-waters/20261104T120000Z.json")                 # bulk: not listed
    put(root, "data/raw/va-deq-prep/20261104T120000Z.json", '{"caller": "x"}')   # personal fields possible: never
    put(root, "data/raw/ny-dec-sprtk/sprtk-2026.xlsx", "wb")
    put(root, "data/raw/ny-dec-sprtk/sprtk-2025.xlsx", "old")
    put(root, "data/build/ny-sprtk-workbook.json", json.dumps({"raw_path": "data/raw/ny-dec-sprtk/sprtk-2026.xlsx"}))
    put(root, "data/raw/nj-echo-monthly/20261104T010203Z.NJ0001-81381.json")
    put(root, "data/raw/nj-echo-monthly/20261004T010203Z.NJ0001-81381.json")   # last month: not kept
    return root


def test_raw_paths_are_the_cached_answers_only(tmp_path):
    root = tree(tmp_path)
    got = SP.raw_paths(root, NOW)
    assert got == ["data/raw/nhd-waters", "data/raw/osm-waters", "data/raw/census/cb_2023_us_state_500k.zip",
                   "data/raw/iem-iemre", "data/raw/ri-nbc/rigis-nbc-sewer-overflows.json",
                   "data/raw/ri-ridoh-beaches/ridohgis-beaches-view.json", "data/raw/dc-waters/boundary-dcgis.json",
                   "data/raw/ny-dec-sprtk/sprtk-2026.xlsx",
                   "data/raw/nj-echo-monthly/20261104T010203Z.NJ0001-81381.json"]
    assert not any("va-deq-prep" in p or p.endswith("pins.json") for p in got)


def test_every_entry_has_a_reason_and_no_bulk_dir_is_listed():
    for e in SP.RAW_CACHE:
        assert e.path.startswith("data/raw/") and len(e.reason) > 30
    # whole directories of stamped bulk saves never go in (they can carry personal fields)
    listed = {e.path for e in SP.RAW_CACHE} | set(SP.DYNAMIC_DIRS)
    for bulk in ("data/raw", "data/raw/ri-nbc", "data/raw/dc-waters", "data/raw/va-deq-prep", "data/raw/fl-dep-pnp",
                 "data/raw/noaa-mrms-qpe", "data/raw/notification-pages", "data/raw/ga-epd-spills"):
        assert bulk not in listed


def test_ny_workbook_outside_its_folder_is_ignored(tmp_path):
    root = tree(tmp_path)
    put(root, "data/build/ny-sprtk-workbook.json", json.dumps({"raw_path": "data/raw/va-deq-prep/20261104T120000Z.json"}))
    assert not any("va-deq-prep" in p for p in SP.raw_paths(root, NOW))
    put(root, "data/build/ny-sprtk-workbook.json", json.dumps({"raw_path": "data/raw/ny-dec-sprtk/../va-deq-prep/x"}))
    assert SP.ny_workbook(root) is None


def test_pack_then_unpack_round_trip(tmp_path, capsys):
    root = tree(tmp_path)
    out = tmp_path / "raw-cache.tar.gz"
    assert SP.pack(out, root, cap_mb=200, now=NOW)
    printed = capsys.readouterr().out
    assert "data/raw/nhd-waters: 2 file(s)" in printed
    assert "raw-cache.tar.gz: " in printed and ".part" not in printed
    with tarfile.open(out) as tf:
        names = set(tf.getnames())
    assert "data/raw/nhd-waters/nldi/ab12.json" in names
    assert not any("va-deq-prep" in n or "other.zip" in n or "pins.json" in n or "20261004" in n for n in names)
    dest = tmp_path / "runner"
    counts = SP.unpack(out, dest)
    assert counts["skipped_not_listed"] == 0
    assert (dest / "data/raw/nhd-waters/nldi-requests.json").read_text() == "[1.0]"
    assert (dest / "data/raw/ny-dec-sprtk/sprtk-2026.xlsx").read_text() == "wb"


def test_pack_over_the_cap_fails_and_leaves_no_file(tmp_path, capsys):
    root = tree(tmp_path)
    put(root, "data/raw/nhd-waters/big.json", "x" * 300_000)
    out = tmp_path / "raw-cache.tar.gz"
    out.write_text("an older tarball")
    assert not SP.pack(out, root, cap_mb=0.0001, now=NOW)
    assert not out.exists() and not (tmp_path / "raw-cache.tar.gz.part").exists()
    assert "::error::" in capsys.readouterr().out


def test_check_size_cli(tmp_path, monkeypatch):
    f = tmp_path / "build.tar.gz"
    f.write_bytes(b"x" * 2000)
    assert SP.main(["check-size", str(f), "--max-mb", "1"]) == 0
    assert SP.main(["check-size", str(f), "--max-mb", "0.001"]) == 1
    monkeypatch.setenv("STATE_MAX_MB", "0.001")
    assert SP.main(["check-size", str(f)]) == 1


def _tar_with(tmp_path: Path, members: list[tuple[str, bytes | None, str]]) -> Path:
    """members: (name, data or None, kind 'file' | 'symlink' | 'dir')."""
    p = tmp_path / "evil.tar.gz"
    with tarfile.open(p, "w:gz") as tf:
        for name, data, kind in members:
            ti = tarfile.TarInfo(name)
            if kind == "file":
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            elif kind == "symlink":
                ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tf.addfile(ti)
            else:
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
    return p


def test_unpack_writes_listed_members_only(tmp_path):
    src = _tar_with(tmp_path, [
        ("data/raw/nhd-waters/ok.json", b"{}", "file"),
        ("data/raw/va-deq-prep/20261104T120000Z.json", b"{}", "file"),       # bulk raw from an older, wider list
        ("research/me/raw/mhb-hist/page.html", b"<p>", "file"),                # research inputs are not in it
        ("data/build/name-blocklist.json", b"[]", "file"),                     # not the raw cache's to write
        ("data/raw/nhd-waters/../../../escape.json", b"{}", "file"),
        ("/tmp/abs.json", b"{}", "file"),
        ("data/raw/nhd-waters/._ok.json", b"x", "file"),                       # AppleDouble from a Mac tarball
        ("data/raw/nhd-waters/link.json", None, "symlink"),
        ("data/raw/osm-waters", None, "dir"),
    ])
    dest = tmp_path / "runner"
    counts = SP.unpack(src, dest)
    assert counts == {"files": 1, "dirs": 1, "skipped_not_listed": 6, "skipped_not_regular": 1}
    written = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert written == ["data/raw/nhd-waters/ok.json"]
    assert not (tmp_path / "escape.json").exists()


@pytest.mark.parametrize("name,ok", [
    ("data/raw/nhd-waters", True), ("data/raw/nhd-waters/a/b.json", True),
    ("data/raw/nhd-watersX/a.json", False), ("./data/raw/osm-waters/a.json", True),
    ("data/raw/census/cb_2023_us_state_500k.zip", True), ("data/raw/census/x.zip", False),
    ("data/raw/nj-echo-monthly/2026.json", True), ("data/raw/ri-nbc/20261104.pins.json", False),
    ("data/raw/../build/x", False), ("", False), ("C:\\x", False),
])
def test_allowed(name, ok):
    assert SP.allowed(name) is ok
