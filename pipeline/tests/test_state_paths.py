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


# ---------------------------------------------------------------- review 2026-11-04: fetch, damaged tarballs, caps

def _stand_in_wrangler(tmp_path: Path, script: str) -> str:
    w = tmp_path / "wrangler"
    w.write_text("#!/bin/sh\n" + script)
    w.chmod(0o755)
    return str(w)


def test_fetch_tells_a_missing_object_from_a_failed_fetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STATE_FETCH_RETRY_S", "0")
    out = tmp_path / "build.tar.gz"
    got = _stand_in_wrangler(tmp_path, 'echo data > "$6"; echo "Download complete."\n')
    assert SP.fetch("state/build.tar.gz", out, wrangler=got) == SP.FETCHED and out.read_text() == "data\n"
    # wrangler's own answer for a key that is not there, with the empty file it leaves behind
    missing = _stand_in_wrangler(tmp_path, ': > "$6"; echo "X [ERROR] The specified key does not exist."; exit 1\n')
    assert SP.fetch("state/build.tar.gz", out, wrangler=missing) == SP.ABSENT and not out.exists()
    counter = tmp_path / "tries"
    failing = _stand_in_wrangler(tmp_path, f'echo x >> {counter}; echo partial > "$6"; '
                                           'echo "X [ERROR] A request to the Cloudflare API failed (500)"; exit 1\n')
    assert SP.fetch("state/build.tar.gz", out, wrangler=failing) == SP.FAILED and not out.exists()
    assert len(counter.read_text().split()) == 3                     # tried three times
    assert "::warning::state/build.tar.gz could not be fetched" in capsys.readouterr().out
    # a missing bucket is not a missing object
    nobucket = _stand_in_wrangler(tmp_path, 'echo "The specified bucket does not exist."; exit 1\n')
    assert SP.fetch("state/build.tar.gz", out, tries=1, wrangler=nobucket) == SP.FAILED
    gone = str(tmp_path / "not-installed")
    assert SP.fetch("state/build.tar.gz", out, tries=1, wrangler=gone) == SP.FAILED


@pytest.mark.parametrize("key", ["../x.tar.gz", "state/../x.tar.gz", "current/meta.json", "state/x", "/state/a.tar.gz"])
def test_fetch_takes_state_keys_only(tmp_path, key):
    with pytest.raises(ValueError):
        SP.fetch(key, tmp_path / "f", wrangler="true")
    assert SP.main(["fetch", key, str(tmp_path / "f")]) == 2


def test_unpack_refuses_a_damaged_tarball_before_writing_anything(tmp_path):
    root = tree(tmp_path)
    out = tmp_path / "raw-cache.tar.gz"
    # stored (level 0) deflate: a changed byte decodes without complaint; only the gzip checksum shows it
    paths = SP.raw_paths(root, NOW)
    with tarfile.open(out, "w:gz", compresslevel=0) as tf:
        for p in paths:
            tf.add(root / p, arcname=p)
    data = bytearray(out.read_bytes())
    i = data.index(b"[1.0]")                                        # inside nldi-requests.json
    data[i + 1] = ord("9")
    out.write_bytes(bytes(data))
    dest = tmp_path / "runner"
    with pytest.raises(Exception):
        SP.unpack(out, dest)
    assert not dest.exists() or not any(p.is_file() for p in dest.rglob("*"))
    # truncated: nothing written either
    good = tmp_path / "good.tar.gz"
    assert SP.pack(good, root, now=NOW)
    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    with pytest.raises(Exception):
        SP.unpack(cut, dest)
    assert not dest.exists() or not any(p.is_file() for p in dest.rglob("*"))


def test_unpack_does_not_follow_a_link_already_on_the_runner(tmp_path):
    src = _tar_with(tmp_path, [("data/raw/nhd-waters/x.json", b"{}", "file")])
    dest = tmp_path / "runner"
    outside = tmp_path / "outside"
    outside.mkdir()
    (dest / "data/raw").mkdir(parents=True)
    (dest / "data/raw/nhd-waters").symlink_to(outside)
    with pytest.raises(tarfile.TarError):
        SP.unpack(src, dest)
    assert not (outside / "x.json").exists()


def test_check_size_with_a_hard_limit_warns_over_the_cap(tmp_path, capsys):
    f = tmp_path / "build.tar.gz"
    f.write_bytes(b"x" * 2000)
    assert SP.main(["check-size", str(f), "--max-mb", "0.001", "--hard-mb", "1"]) == 0
    assert "::warning::build.tar.gz is" in capsys.readouterr().out
    assert SP.main(["check-size", str(f), "--max-mb", "0.0001", "--hard-mb", "0.001"]) == 1
    assert "upload limit" in capsys.readouterr().out


def test_restored_cache_lets_the_next_run_answer_without_requests(tmp_path, monkeypatch):
    """The point of the raw cache: an NHD answer saved by one runner is answered from cache by the next, at no cost
    to its request budget."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    from types import SimpleNamespace
    from ingest import waters_from_nhd as N

    class Session:
        calls = 0

        def get(self, url, params=None, headers=None, timeout=None):
            Session.calls += 1
            return SimpleNamespace(status_code=200, headers={}, json=lambda: {"features": [{"id": 1}]}, text="",
                                   raise_for_status=lambda: None)

    first = tmp_path / "first"
    monkeypatch.setattr(N, "CACHE_DIR", first / "data/raw/nhd-waters")
    monkeypatch.setattr(N, "PAUSE_S", 0.0)
    http = N.Http(max_requests=1, nldi_log=first / "data/raw/nhd-waters/nldi-requests.json")
    http.session = Session()
    assert http.get("nldi-comid", "https://example.invalid/nldi", {"q": "1"}) == {"features": [{"id": 1}]}
    tarball = tmp_path / "raw-cache.tar.gz"
    assert SP.pack(tarball, first, now=NOW)
    second = tmp_path / "second"
    SP.unpack(tarball, second)
    monkeypatch.setattr(N, "CACHE_DIR", second / "data/raw/nhd-waters")
    again = N.Http(max_requests=0, nldi_log=second / "data/raw/nhd-waters/nldi-requests.json")
    again.session = Session()
    assert again.get("nldi-comid", "https://example.invalid/nldi", {"q": "1"}) == {"features": [{"id": 1}]}
    assert Session.calls == 1 and again.requests == 0
    assert len(again._nldi_recent()) == 1                             # the first runner's NLDI request still counts


# ---------------------------------------------------------------- openboatlaunch's water records (state/obl-water.tar.gz)

def obl_tarball(tmp_path: Path, extra=(), records=3, meta=True) -> Path:
    """The object as the upload packs it: tar -czf obl-water.tar.gz -C <openboatlaunch>/out water meta.json."""
    src = tmp_path / "obl-src" / "out"
    for i, slug in enumerate(["haw-river-nc", "lake-wheeler-nc", "lake-lanier-ga"][:records]):
        put(src, f"water/{slug}.json", json.dumps({"slug": slug, "state": slug[-2:].upper(), "name": slug}))
    if meta:
        put(src, "meta.json", json.dumps({"built": "2026-11-01T04:00:00Z"}))
    out = tmp_path / "obl-water.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        if (src / "water").is_dir():
            tf.add(src / "water", arcname="water")
        if meta:
            tf.add(src / "meta.json", arcname="meta.json")
        for name, kind, data in extra:
            ti = tarfile.TarInfo(name)
            if kind == "link":
                ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tf.addfile(ti)
            else:
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
    return out


@pytest.mark.parametrize("name,ok", [
    ("water/haw-river-nc.json", True), ("./water/haw-river-nc.json", True), ("meta.json", True), ("water", True),
    ("water/sub/x.json", False), ("water/._haw-river-nc.json", False), ("../water/x.json", False),
    ("/water/x.json", False), ("water/x.txt", False), ("launch/x.json", False), ("out/water/x.json", False),
    ("water/..json", False), ("", False), ("meta.json/x", False),
])
def test_obl_member_names(name, ok):
    assert SP.obl_allowed(name) is ok


def test_unpack_obl_writes_the_records_and_meta_only(tmp_path):
    src = obl_tarball(tmp_path, extra=[("../evil.json", "file", b"{}"), ("water/sub/x.json", "file", b"{}"),
                                       ("water/._haw-river-nc.json", "file", b"apple"), ("water/link.json", "link", b""),
                                       ("notes.txt", "file", b"x")])
    dest = tmp_path / "openboatlaunch" / "out"
    c = SP.unpack_obl(src, dest)
    assert c["records"] == 3 and c["meta"] == 1 and c["skipped_not_listed"] == 4 and c["skipped_not_regular"] == 1
    got = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert got == ["meta.json", "water/haw-river-nc.json", "water/lake-lanier-ga.json", "water/lake-wheeler-nc.json"]
    assert not (tmp_path / "evil.json").exists() and not (tmp_path / "openboatlaunch" / "evil.json").exists()


@pytest.mark.parametrize("how", ["corrupt", "no-records", "not-gzip"])
def test_unpack_obl_refuses_an_unreadable_object_and_writes_nothing(tmp_path, how, capsys):
    src = obl_tarball(tmp_path, records=0 if how == "no-records" else 3)
    if how == "corrupt":
        src.write_bytes(src.read_bytes()[:-30])
    elif how == "not-gzip":
        src.write_bytes(b"<html>not an object</html>")
    dest = tmp_path / "openboatlaunch" / "out"
    with pytest.raises(SP.Unreadable):
        SP.unpack_obl(src, dest)
    assert not dest.exists()
    assert SP.main(["unpack-obl", str(src), "--to", str(dest)]) == 1
    assert "could not be read" in capsys.readouterr().out


def test_unpack_obl_never_writes_into_a_real_openboatlaunch_checkout(tmp_path):
    src = obl_tarball(tmp_path)
    dest = tmp_path / "openboatlaunch" / "out"
    (tmp_path / "openboatlaunch" / ".git").mkdir(parents=True)
    with pytest.raises(SP.Unreadable, match="checkout"):
        SP.unpack_obl(src, dest)
    assert not dest.exists()


def test_unpack_obl_without_meta_warns(tmp_path, capsys):
    src = obl_tarball(tmp_path, meta=False)
    dest = tmp_path / "openboatlaunch" / "out"
    assert SP.main(["unpack-obl", str(src), "--to", str(dest)]) == 0
    assert "no meta.json" in capsys.readouterr().out
    assert len(list((dest / "water").glob("*.json"))) == 3


def test_obl_default_destination_is_the_sibling_the_pipeline_reads():
    assert SP.OBL_OUT == ROOT.parent / "openboatlaunch" / "out"
    assert SP.OBL_KEY == "state/obl-water.tar.gz" and SP.STATE_KEY.fullmatch(SP.OBL_KEY)


def test_unpack_obl_only_the_water_folder_is_a_directory(tmp_path):
    """A directory named like a record or meta.json, or a file named water, is skipped (status.py would read a
    directory as a record)."""
    src = tmp_path / "odd.tar.gz"
    with tarfile.open(src, "w:gz") as tf:
        for name, kind in (("water", "dir"), ("water/ok-ny.json", "file"), ("water/dir-ny.json", "dir"),
                           ("meta.json", "dir")):
            ti = tarfile.TarInfo(name)
            if kind == "dir":
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
            else:
                ti.size = 2
                tf.addfile(ti, io.BytesIO(b"{}"))
    dest = tmp_path / "openboatlaunch" / "out"
    c = SP.unpack_obl(src, dest)
    assert c["records"] == 1 and c["meta"] == 0 and c["skipped_not_regular"] == 2
    assert sorted(str(p.relative_to(dest)) for p in dest.rglob("*")) == ["water", "water/ok-ny.json"]
    src2 = tmp_path / "file-water.tar.gz"
    with tarfile.open(src2, "w:gz") as tf:
        ti = tarfile.TarInfo("water")
        ti.size = 2
        tf.addfile(ti, io.BytesIO(b"{}"))
    with pytest.raises(SP.Unreadable, match="no water"):
        SP.unpack_obl(src2, tmp_path / "o2" / "out")


def test_unpack_obl_caps_a_member_and_the_whole(tmp_path):
    """A record over the member cap (a 2 GB sparse member, say) is skipped and counted; an object that unpacks past
    the total cap writes nothing."""
    src = obl_tarball(tmp_path, extra=[("water/huge-ny.json", "file", b"0" * 5000)])
    dest = tmp_path / "openboatlaunch" / "out"
    c = SP.unpack_obl(src, dest, member_max=1000)
    assert c["skipped_too_large"] == 1 and c["records"] == 3 and not (dest / "water" / "huge-ny.json").exists()
    with pytest.raises(SP.Unreadable, match="more than"):
        SP.unpack_obl(src, tmp_path / "o2" / "out", total_max=4000)
    assert not (tmp_path / "o2").exists()


def test_unpack_obl_never_writes_anywhere_inside_a_checkout(tmp_path):
    """Not only beside .git: any folder under a checkout (this repository's data/, an openboatlaunch subfolder)."""
    src = obl_tarball(tmp_path)
    (tmp_path / "proj" / ".git").mkdir(parents=True)
    for dest in (tmp_path / "proj" / "data" / "obl" / "out", tmp_path / "proj" / "out"):
        with pytest.raises(SP.Unreadable, match="checkout"):
            SP.unpack_obl(src, dest)
        assert not dest.exists()
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "proj")
    with pytest.raises(SP.Unreadable, match="checkout"):
        SP.unpack_obl(src, link / "out")
