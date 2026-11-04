#!/usr/bin/env python3
"""What the workflows keep in R2 between runs (bucket dirtywaterwatch-data, prefix state/), and the tarballs of it.

Three state objects:
  state/build.tar.gz       data/build whole: the ingesters' history and snapshot files, the reach traces
                           (data/build/reaches/, build/reaches.py: its NLDI and NHDPlus answers are kept there, 30
                           days), the provisional-outfall and geocoder caches, the private name blocklist. Made with
                           tar by the workflow; this script only checks its size (check-size).
  state/raw-cache.tar.gz   the answers in data/raw that the code reads back (RAW_CACHE below, with the reasons),
                           packed and restored by this script. Everything else in data/raw is a bulk raw save that
                           no step reads back and that can carry personal fields; it stays on the runner and is
                           never saved. The git-ignored research/*/raw inputs some ingesters read are hand-gathered
                           files, not answers, and are not in it either.
  state/obl-water.tar.gz   openboatlaunch's water records with their outlines (its out/water/<slug>.json, one per
                           water per state, and out/meta.json with the snapshot date), packed once on a machine with
                           the openboatlaunch checkout: tar -czf obl-water.tar.gz -C <openboatlaunch>/out water
                           meta.json (top-level entries water/<slug>.json and meta.json). Restored read only by both
                           workflows into ../openboatlaunch/out (OBL_OUT: the sibling folder the pipeline reads by
                           default: build/status.py OBL_WATER_DIR for the outlines that ingest.outfall_waters and
                           ingest.waters_from_nhd measure ties and duplicates against, ingest.obl_waters --from for a
                           state's extract, whose snapshot date it takes from out/meta.json); never saved by them.
                           Missing: a warning (the outlines are absent, as before). There but unreadable: the batch
                           stops, the hourly refresh warns and goes on.

Restore order: build.tar.gz, then raw-cache.tar.gz (the NY workbook entry is named by a data/build file). Save: both
only after a run that ended well (a cancelled or failed refresh never overwrites the saved state). A state object
that is there but cannot be fetched (fetch exits 1) is never saved over: the refresh stops when build.tar.gz cannot be
fetched or unpacked (a run without its history and blocklist would publish and then save a history that starts from
nothing), and a run that could not fetch raw-cache.tar.gz goes on without it and keeps the stored one. A raw cache
that cannot be read is replaced by the next good run's.

    python3 -I scripts/state_paths.py list                  the raw-cache paths present now, one per line
    python3 -I scripts/state_paths.py pack FILE [--max-mb N]  raw-cache tarball of them; prints the size per entry
                                                            and in all; exit 1 (and no FILE) over the cap
    python3 -I scripts/state_paths.py unpack FILE           restore a raw-cache tarball: only regular files and
                                                            directories under the RAW_CACHE paths are written; links,
                                                            absolute or '..' paths, AppleDouble '._*' files and
                                                            anything else are skipped and counted (a tarball made
                                                            elsewhere, or by an older list, cannot widen the set)
    python3 -I scripts/state_paths.py unpack-obl FILE [--to DIR]
                                                            restore state/obl-water.tar.gz into DIR (default
                                                            ../openboatlaunch/out): only water/<slug>.json and
                                                            meta.json, regular files, are written; the gzip is read to
                                                            its end and the member list checked first, so a damaged
                                                            object, or one with no water record, writes nothing (exit
                                                            1); never into a folder that is a git checkout
    python3 -I scripts/state_paths.py check-size FILE [--max-mb N] [--hard-mb N]
                                                            exit 1 when a tarball is over the cap; with --hard-mb,
                                                            over the cap is a warning and only over N fails
    python3 -I scripts/state_paths.py fetch KEY FILE        get state object KEY (e.g. state/build.tar.gz) from the
                                                            bucket with wrangler, tried three times; exit 0 fetched,
                                                            3 when there is no such object (a first run), 1 when it
                                                            could not be fetched (the workflow then keeps the stored
                                                            object: a run that could not restore it never saves over it)

The cap is 200 MB (STATE_MAX_MB in the environment, or --max-mb, overrides it). The build state's save warns over the
cap and fails only over wrangler's upload limit (300 MiB, --hard-mb 314), where the upload would fail anyway: a build
state that grew is still saved, so no history is lost while the growth is looked at. Nothing here prints a file's
contents, only paths, counts and sizes. Standard library only.

The NY workbook is DEC's public download as published; its free text can carry contact details, which the ingester
scrubs before anything is written. Like the name blocklist in build.tar.gz, it is kept only in the private state
bucket, never committed or published.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_MB = 200.0
WRANGLER_MAX_MB = 314.0          # wrangler r2 object put refuses a file over 300 MiB (314.6 MB)
BUCKET = "dirtywaterwatch-data"
STATE_KEY = re.compile(r"state/[a-z0-9][a-z0-9._-]*\.tar\.gz")
# wrangler's answer for a key that is not there ("The specified key does not exist."): a first run, not a failure
MISSING = re.compile(r"specified key does not exist|NoSuchKey", re.I)
FETCHED, ABSENT, FAILED = 0, 3, 1
# openboatlaunch's water records (state/obl-water.tar.gz) and where the pipeline reads them: <repo>/../openboatlaunch/out
OBL_KEY = "state/obl-water.tar.gz"
OBL_OUT = ROOT.parent / "openboatlaunch" / "out"
OBL_RECORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.json")


class Unreadable(Exception):
    """A state object that is there but cannot be restored; the message says why (never its contents)."""


@dataclass(frozen=True)
class Entry:
    path: str      # relative to the repository root, POSIX form
    reason: str    # the code that reads it back, and why it is worth keeping


# The cached answers the code reads back (decided from the code, 2026-11-04). A directory entry keeps everything
# under it; a file entry keeps that file only.
RAW_CACHE: tuple[Entry, ...] = (
    Entry("data/raw/nhd-waters",
          "ingest/waters_from_nhd.py (and ingest/outfall_waters.py through it): every NLDI, NHDPlus MapServer, "
          "TIGERweb, NHD high-resolution and Overpass answer, reused unless --refresh, and nldi-requests.json, the "
          "NLDI request log that keeps USGS's 3,600-an-hour limit across runs; without it the budgeted hourly "
          "waters-nhd target and every state batch start again from nothing"),
    Entry("data/raw/osm-waters",
          "ingest/waters_extra.py and waters_from_nhd's OpenStreetMap fallback: one Overpass answer per water"),
    Entry("data/raw/census/cb_2023_us_state_500k.zip",
          "ingest/waters_extra.py states_zip(): the Census state outlines every water record is cut to "
          "(downloaded once, 3 MB)"),
    Entry("data/raw/iem-iemre",
          "build/rain_thresholds.py: IEM's MRMS daily rainfall per outfall point and year (past years final)"),
    Entry("data/raw/ri-nbc/rigis-nbc-sewer-overflows.json",
          "ingest/ri_nbc.py: the RIGIS outfall layer, refetched after 30 days"),
    Entry("data/raw/ri-ridoh-beaches/ridohgis-beaches-view.json",
          "ingest/ri_ridoh_beaches.py: the beach layer, refetched after 30 days"),
    Entry("data/raw/dc-waters/boundary-dcgis.json",
          "ingest/dc_waters.py in_district() (read by echo_sewer_overflow_events): the District boundary"),
)
# Named at run time (raw_paths): the workbook data/build/ny-sprtk-workbook.json names (ingest/ny_sprtk.py reuses it
# for 20 hours, and it is the fallback when DEC and archive.org both fail), and this month's NJ ECHO answers
# (ingest/nj_echo_monthly.py asks ECHO once a month per permit and reads the month's answers back).
NY_WORKBOOK_META = "data/build/ny-sprtk-workbook.json"
NY_WORKBOOK_DIR = "data/raw/ny-dec-sprtk"
NJ_ECHO_DIR = "data/raw/nj-echo-monthly"
DYNAMIC_DIRS = (NY_WORKBOOK_DIR, NJ_ECHO_DIR)


def say(msg: str) -> None:
    print(f"state-paths: {msg}", flush=True)


def max_mb(arg: float | None = None) -> float:
    if arg is not None:
        return float(arg)
    try:
        return float(os.environ.get("STATE_MAX_MB") or DEFAULT_MAX_MB)
    except ValueError:
        return DEFAULT_MAX_MB


def ny_workbook(root: Path = ROOT) -> str | None:
    """The workbook path data/build/ny-sprtk-workbook.json names, when it is a file under data/raw/ny-dec-sprtk/."""
    try:
        p = json.loads((root / NY_WORKBOOK_META).read_text()).get("raw_path")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(p, str) or not allowed(p, (NY_WORKBOOK_DIR,)) or p == NY_WORKBOOK_DIR:
        return None
    return p if (root / p).is_file() else None


def raw_paths(root: Path = ROOT, now: datetime | None = None) -> list[str]:
    """The raw-cache paths present under root: the RAW_CACHE entries that exist, the NY workbook, this month's (UTC)
    NJ ECHO answers."""
    out = [e.path for e in RAW_CACHE if (root / e.path).exists()]
    wb = ny_workbook(root)
    if wb:
        out.append(wb)
    month = (now or datetime.now(timezone.utc)).strftime("%Y%m")
    nj = root / NJ_ECHO_DIR
    if nj.is_dir():
        out += sorted(f"{NJ_ECHO_DIR}/{p.name}" for p in nj.glob(f"{month}*") if p.is_file())
    return out


def allowed(name: str, prefixes=None) -> bool:
    """A tar member name may be restored: relative, no '..', no AppleDouble part, and equal to or under a RAW_CACHE
    entry or one of the run-time directories (prefixes: the entries to allow, default all)."""
    if not name or name.startswith("/") or "\\" in name:
        return False
    parts = PurePosixPath(name).parts
    if not parts or any(x in ("..", "") for x in parts) or any(x.startswith("._") for x in parts):
        return False
    norm = "/".join(x for x in parts if x != ".")
    keep = [e.path for e in RAW_CACHE] + list(DYNAMIC_DIRS) if prefixes is None else list(prefixes)
    return any(norm == k or norm.startswith(k + "/") for k in keep)


def _size(p: Path) -> tuple[int, int]:
    """(files, bytes) under p."""
    if p.is_file():
        return 1, p.stat().st_size
    n = b = 0
    for q in p.rglob("*"):
        if q.is_file() and not q.is_symlink():
            n += 1
            b += q.stat().st_size
    return n, b


def mb(b: int) -> str:
    return f"{b / 1e6:.1f} MB"


def check_size(path: Path, cap_mb: float, label: str | None = None, hard_mb: float | None = None) -> bool:
    """False when the file is over the cap, or, given hard_mb, only when it is over hard_mb (over the cap is then a
    warning and the file is saved)."""
    size, label = path.stat().st_size, label or path.name
    if hard_mb is not None and cap_mb * 1e6 < size <= hard_mb * 1e6:
        print(f"::warning::{label} is {mb(size)}, over the {cap_mb:g} MB cap for a state object; it is saved (the "
              f"upload limit is {hard_mb:g} MB). Find what grew, prune it or raise STATE_MAX_MB in the workflow on "
              f"purpose.", flush=True)
        return True
    limit = hard_mb if hard_mb is not None else cap_mb
    if size > limit * 1e6:
        print(f"::error::{label} is {mb(size)}, over the {limit:g} MB {'upload limit' if hard_mb is not None else 'cap'}"
              f" for a state object; it is not saved. Find what grew, prune it or raise STATE_MAX_MB in the workflow "
              f"on purpose.", flush=True)
        return False
    say(f"{label}: {mb(size)} (cap {cap_mb:g} MB)")
    return True


def fetch(key: str, out: Path, tries: int = 3, wrangler: str | None = None) -> int:
    """Get a state object with wrangler: FETCHED (0), ABSENT (3: wrangler says there is no such key) or FAILED (1:
    anything else, after `tries` attempts). Never leaves a partial file behind on ABSENT or FAILED."""
    if not STATE_KEY.fullmatch(key):
        raise ValueError(f"not a state object key: {key!r}")
    cmd = [wrangler or os.environ.get("WRANGLER") or "wrangler", "r2", "object", "get", f"{BUCKET}/{key}",
           "--file", str(out), "--remote"]
    pause = float(os.environ.get("STATE_FETCH_RETRY_S") or 15)
    last = "no answer"
    for n in range(tries):
        out.unlink(missing_ok=True)
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                               timeout=300)
        except (OSError, subprocess.TimeoutExpired) as ex:
            p, text = None, f"{type(ex).__name__}"
        else:
            text = p.stdout or ""
        if p is not None and p.returncode == 0 and out.is_file():
            say(f"{key}: fetched, {mb(out.stat().st_size)}")
            return FETCHED
        out.unlink(missing_ok=True)
        if MISSING.search(text):
            say(f"{key}: not in the bucket")
            return ABSENT
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        last = lines[-1][:300] if lines else (f"exit {p.returncode}" if p is not None else text)
        if n < tries - 1:
            say(f"{key}: not fetched ({last}); trying again")
            time.sleep(pause * (n + 1))
    print(f"::warning::{key} could not be fetched ({last})", flush=True)
    return FAILED


def pack(out: Path, root: Path = ROOT, cap_mb: float = DEFAULT_MAX_MB, now: datetime | None = None) -> bool:
    """Write the raw-cache tarball; print the sizes; False (and no file) when it is over the cap."""
    paths = raw_paths(root, now)
    total = 0
    for p in paths:
        n, b = _size(root / p)
        total += b
        say(f"{p}: {n} file(s), {mb(b)}")
    say(f"raw cache: {len(paths)} path(s), {mb(total)} before compression")

    def regular(ti: tarfile.TarInfo):
        # no links or devices, no AppleDouble files: what unpack() would refuse is never written
        if not (ti.isfile() or ti.isdir()) or any(x.startswith("._") for x in PurePosixPath(ti.name).parts):
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti

    tmp = out.with_name(out.name + ".part")
    with tarfile.open(tmp, "w:gz", compresslevel=6) as tf:
        for p in paths:
            tf.add(root / p, arcname=p, recursive=True, filter=regular)
    if not check_size(tmp, cap_mb, out.name):
        tmp.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
        return False
    tmp.replace(out)
    return True


def unpack(src: Path, root: Path = ROOT) -> dict:
    """Restore a raw-cache tarball under root, members on the list only. Returns the counts. A gzip file is read to
    its end first (its length and checksum), so a damaged tarball raises before anything is written."""
    counts = {"files": 0, "dirs": 0, "skipped_not_listed": 0, "skipped_not_regular": 0}
    with open(src, "rb") as fh:
        is_gz = fh.read(2) == b"\x1f\x8b"
    if is_gz:
        with gzip.open(src, "rb") as g:
            while g.read(1 << 20):
                pass
    with tarfile.open(src, "r:*") as tf:
        members = []
        for m in tf.getmembers():
            if not allowed(m.name):
                counts["skipped_not_listed"] += 1
                continue
            if not (m.isfile() or m.isdir()):
                counts["skipped_not_regular"] += 1
                continue
            members.append(m)
            counts["files" if m.isfile() else "dirs"] += 1
        tf.extractall(root, members=members, filter="data")
    say(f"restored {counts['files']} file(s) from {src.name}"
        + "".join(f", {v} {k.replace('_', ' ')}" for k, v in counts.items() if k.startswith("skipped") and v))
    return counts


def obl_allowed(name: str) -> bool:
    """A member of state/obl-water.tar.gz that may be restored: water/<slug>.json (one level, no AppleDouble '._'),
    meta.json, or the water directory itself; relative, no '..'."""
    if not name or name.startswith("/") or "\\" in name:
        return False
    parts = [x for x in PurePosixPath(name).parts if x != "."]
    if any(x in ("..", "") for x in parts):
        return False
    if parts in (["water"], ["meta.json"]):
        return True
    return len(parts) == 2 and parts[0] == "water" and bool(OBL_RECORD.fullmatch(parts[1]))


def unpack_obl(src: Path, dest: Path = OBL_OUT) -> dict:
    """Restore openboatlaunch's water records into dest (<openboatlaunch>/out). Raises Unreadable, having written
    nothing, when the gzip or the tar cannot be read to its end or the object holds no water record, and when dest
    belongs to a git checkout (a real openboatlaunch project is never written over)."""
    dest = Path(dest)
    if (dest.parent / ".git").exists() or (dest / ".git").exists():
        raise Unreadable(f"{dest} is in a git checkout (an openboatlaunch project): not written over")
    counts = {"records": 0, "meta": 0, "skipped_not_listed": 0, "skipped_not_regular": 0}
    try:
        with open(src, "rb") as fh:
            if fh.read(2) != b"\x1f\x8b":
                raise Unreadable(f"{Path(src).name} is not a gzip file")
        with gzip.open(src, "rb") as g:
            while g.read(1 << 20):
                pass
        with tarfile.open(src, "r:gz") as tf:
            members = []
            for m in tf.getmembers():
                if not obl_allowed(m.name):
                    counts["skipped_not_listed"] += 1
                    continue
                if not (m.isfile() or m.isdir()):
                    counts["skipped_not_regular"] += 1
                    continue
                members.append(m)
                if m.isfile():
                    top = [x for x in PurePosixPath(m.name).parts if x != "."][0]
                    counts["meta" if top == "meta.json" else "records"] += 1
            if not counts["records"]:
                raise Unreadable(f"{Path(src).name} holds no water/<slug>.json record")
            dest.mkdir(parents=True, exist_ok=True)
            tf.extractall(dest, members=members, filter="data")
    except Unreadable:
        raise
    except (OSError, EOFError, tarfile.TarError, zlib.error) as ex:
        raise Unreadable(f"{Path(src).name}: {type(ex).__name__}") from None
    say(f"restored {counts['records']} openboatlaunch water record(s) into {dest}"
        + ("" if counts["meta"] else "; no meta.json, so the snapshot date is unknown (an extract then refuses to run)")
        + "".join(f", {v} {k.replace('_', ' ')}" for k, v in counts.items() if k.startswith("skipped") and v))
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("pack", "check-size"):
        s = sub.add_parser(name)
        s.add_argument("file")
        s.add_argument("--max-mb", type=float)
        if name == "check-size":
            s.add_argument("--hard-mb", type=float, help="over the cap is a warning; only over this fails")
    s = sub.add_parser("unpack")
    s.add_argument("file")
    s = sub.add_parser("unpack-obl")
    s.add_argument("file")
    s.add_argument("--to", default=str(OBL_OUT), help="openboatlaunch's out folder (default ../openboatlaunch/out)")
    s = sub.add_parser("fetch")
    s.add_argument("key")
    s.add_argument("file")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print("\n".join(raw_paths()))
        return 0
    if a.cmd == "pack":
        return 0 if pack(Path(a.file), cap_mb=max_mb(a.max_mb)) else 1
    if a.cmd == "check-size":
        return 0 if check_size(Path(a.file), max_mb(a.max_mb), hard_mb=a.hard_mb) else 1
    if a.cmd == "fetch":
        try:
            return fetch(a.key, Path(a.file))
        except ValueError as ex:
            print(f"::error::{ex}", flush=True)
            return 2
    if a.cmd == "unpack-obl":
        try:
            unpack_obl(Path(a.file), Path(a.to))
        except Unreadable as ex:
            say(f"the openboatlaunch object could not be read ({ex}); nothing was restored from it")
            return 1
        return 0
    unpack(Path(a.file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
