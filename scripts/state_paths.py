#!/usr/bin/env python3
"""What the workflows keep in R2 between runs (bucket dirtywaterwatch-data, prefix state/), and the tarballs of it.

Three state objects:
  state/build.tar.gz       data/build whole: the ingesters' history and snapshot files, the reach traces
                           (data/build/reaches/, build/reaches.py: its NLDI and NHDPlus answers are kept there, 30
                           days), the provisional-outfall and geocoder caches, the private name blocklist. Made with
                           tar by the workflow; this script checks its size (check-size) and restores it
                           (unpack-build: data/build members only).
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
                           stops, the hourly refresh warns and goes on. Since the openboatlaunch API (2026-11-07)
                           the workflows first try fetch-obl (below) and restore this object only when the API was
                           not used; the refresh saves the folder back here (pack-obl) whenever the API changed it,
                           so this object is the last good copy, the fallback when the API is down.

  state/attains.tar.gz     the state assessments joined to the water records (data/build/attains/attains-waters.json,
                           pipeline/build/attains.py, docs/attains.md), written only by the weekly ATTAINS workflow
                           (.github/workflows/attains.yml) and restored read only by the hourly refresh after the build
                           state (unpack-attains), so the export reads this week's file; the copy that rides in
                           build.tar.gz is the fallback when this object cannot be fetched.
  state/attains-geom.tar.gz the ATTAINS assessment-unit geometry per state (data/raw/attains/geom/<ST>.json.gz and its
                           manifest.json), public map-layer answers kept so the weekly job fetches a state again only
                           when EPA reloaded it; written and read by the weekly job only (unpack-attains).

History copies of state/build.tar.gz (2026-11-21). R2 keeps no versions and the bucket has no expiry rule, so each
save of state/build.tar.gz replaces the only copy: a run that ends well with less history than it restored (a module
that rewrites its file from a short window, a code change, a bad merge) would lose the rest for good. The refresh
keeps three kinds of copy of the same archive, private like it, in the bucket dirtywaterwatch-data under state/held/,
state/daily/ and state/monthly/ only (GENERATION_KEY; put() writes nothing else, never current/ or any public path).
Every call is `wrangler r2 object get|put`, which the workflows route to R2's S3 endpoint (scripts/wrangler-guard.sh,
scripts/r2-s3-keys.sh), as the state save does:
  state/daily/build-<Mon..Sun>.tar.gz    the first save of each UTC day: a ring of seven keys, each overwritten a week
                                         later, so nothing is listed or deleted
  state/monthly/build-<YYYY-MM>.tar.gz   the first save of each calendar month (UTC); kept
  state/held/build-<date>-<run>.tar.gz   the archive as restored (the history before the run), uploaded by the
                                         history guard when a source lost records; kept. <run> is the Actions run id,
                                         with -a<attempt> for a re-run attempt
  state/daily/build-<Mon..Sun>.json and state/monthly/build-<YYYY-MM>.json
                                         each copy's marker (its key, date and run; a few hundred bytes), uploaded
                                         only after the copy
The history guard. Right after the restore the workflow keeps the restored archive (restored-build.tar.gz) and its
records per source (counts: restored-counts.json; both in the runner's workspace, outside data/build). Before the
save, guard counts data/build/events again. A source whose records fell by at least DROP_MIN_PERCENT percent and at
least DROP_MIN_RECORDS records, or whose events file disappeared or can no longer be read, is a drop: one ::warning::
per source with its counts, the restored archive held, and data/build/history-guard.json written (time, run, each
drop's counts, the held key and whether it uploaded; earlier drop runs kept below it). The save still goes on
(operations are not disrupted; the held copy and the warning are the safeguard). No drop: nothing uploaded. No
restored state (a first run): nothing compared. A missing data/build counts as every source gone. The one case that
stops the save is save-check's: data/build/events missing or holding no events file while the restored state had some;
the save step then fails and the stored state stands.
Time. The held copy, the copies, their markers and the marker reads are optional: each has a total deadline, retries
included (OPTIONAL_CAP_S: 10 minutes for an archive, 1 for a marker), its process group killed when it runs out, and
none runs past SAVE_RESERVE_S (15 minutes) before the job's 100-minute limit, counted from the job's start the restore
step writes to job-started; with less time left an operation is skipped with a warning.
The generation record, data/build/state-generations.json, travels with the state. Before the archive is made,
generations plan records the copies the previous run left pending whose markers name that run (one small read each),
then writes the copies due (the day's daily when the record does not hold this UTC date for that weekday, the month's
monthly when it does not hold this month) as this run's pending ones, claiming nothing for them. After the save,
generations put uploads the saved archive to each, then its marker. A failed upload is a warning, never fails the run
and leaves no marker that names the run, so the next run finds the copy still due and makes it again. The record
never claims a copy that was not uploaded (it can miss one whose marker failed; that copy is simply made again).
Cost at R2 list prices (Standard storage $0.015 per GB-month, Class A operations $4.50 per million, Class B $0.36 per
million; no free allowance netted out), for a 123 MB archive: the daily ring holds 7 x 123 MB = 0.86 GB, $0.013 a
month; each monthly copy adds 0.123 GB, $0.0018 a month, kept (12 copies, 1.48 GB, $0.022 a month after a year); the
uploads are about 63 Class A operations a month (31 copies and 31 markers), $0.0003, and the marker reads about 31
Class B operations, $0.00001. A held copy is one more Class A operation and 0.123 GB ($0.0018 a month) until someone
deletes it. In all about $0.015 a month at first, $0.035 a month after a year and $0.30 over the first year; every
figure grows in step with the archive.
Rollback, by hand (never automated): set the pause (any small file at state/PAUSE); wait until a running refresh has
ended (one past its pause check still saves); fetch the chosen daily, monthly or held copy (fetch KEY FILE; counts
FILE OUT shows its records per source) and put that file as state/build.tar.gz; delete state/PAUSE. The generation
record goes back with the state, so the next run makes the day's daily again, and the month's monthly when the copy
predates it, over those keys: copy either to a state/held/ key first to keep it as it was.

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
    python3 -I scripts/state_paths.py unpack-build FILE     restore state/build.tar.gz: the whole archive is read and
                                                            checked first; only data/build and regular files and
                                                            folders under it; a link, special file, absolute or '..'
                                                            path, or anything outside data/build refuses the whole
                                                            archive (exit 1, nothing written)
    python3 -I scripts/state_paths.py fetch state/PAUSE FILE
                                                            the shared pause switch: exit 0 set, 3 not set, 1 could
                                                            not be checked (the workflows then stop)
    python3 -I scripts/state_paths.py unpack-obl FILE [--to DIR]
                                                            restore state/obl-water.tar.gz into DIR (default
                                                            ../openboatlaunch/out): only water/<slug>.json and
                                                            meta.json, regular files, are written; the gzip is read to
                                                            its end and the member list checked first, so a damaged
                                                            object, or one with no water record, writes nothing (exit
                                                            1); a record over 256 MB is skipped, an object over 8 GB
                                                            unpacked refused; never into a folder in a git checkout
    python3 -I scripts/state_paths.py fetch-obl [--to DIR] [--force]
                                                            openboatlaunch's national bulk file from its API
                                                            (pipeline/obl_api.py; key in OBL_API_KEY, never printed):
                                                            meta (ETag, a 304 most hours), then bulk/national.tar.gz
                                                            and its .sha256, checked against both, unpacked with the
                                                            unpack-obl rules into DIR (swapped in whole). At most one
                                                            national pull a day (unless the changes check asked for
                                                            one: need_full), and none while the snapshot is the
                                                            one last pulled (data/build/obl-changes.json "national"):
                                                            the R2 copy plus the hourly changes check
                                                            (ingest.obl_changes) is then current. Exit 0 unpacked from
                                                            the API; 4 the API was not used (no key, not needed, or any
                                                            failure, said in the log): restore the R2 copy as before
    python3 -I scripts/state_paths.py pack-obl FILE [--from DIR] [--always]
                                                            pack DIR (water/ and meta.json, regular files only) for R2
                                                            state/obl-water.tar.gz when the API changed it this run
                                                            (fetch-obl or ingest.obl_changes leave the mark
                                                            .dww-changed there); exit 0 packed, 3 nothing to save
    python3 -I scripts/state_paths.py obl-not-saved         that pack was not uploaded: data/build/obl-changes.json's
                                                            national pull and changes until go back to before the run
    python3 -I scripts/state_paths.py unpack-attains FILE [--only cache|geom]
                                                            restore state/attains.tar.gz (--only cache:
                                                            data/build/attains/attains-waters.json) or
                                                            state/attains-geom.tar.gz (--only geom:
                                                            data/raw/attains/geom/<ST>.json.gz and manifest.json),
                                                            regular files; the whole archive is read and checked first,
                                                            and anything else refuses it whole (exit 1, nothing written)
    python3 -I scripts/state_paths.py check-size FILE [--max-mb N] [--hard-mb N]
                                                            exit 1 when a tarball is over the cap; with --hard-mb,
                                                            over the cap is a warning and only over N fails
    python3 -I scripts/state_paths.py fetch KEY FILE        get state object KEY (e.g. state/build.tar.gz) from the
                                                            bucket with wrangler, tried three times; exit 0 fetched,
                                                            3 when there is no such object (a first run), 1 when it
                                                            could not be fetched (the workflow then keeps the stored
                                                            object: a run that could not restore it never saves over it)
    python3 -I scripts/state_paths.py counts SRC OUT        records per source (records, duplicate_of,
                                                            missing_from_source) of SRC, the data/build folder or a
                                                            state tarball (read, never unpacked), as JSON in OUT
    python3 -I scripts/state_paths.py guard COUNTS [--restored FILE] [--out FILE] [--run-id ID]
                                                            the history guard (above) against COUNTS, the counts taken
                                                            at the restore; FILE (default restored-build.tar.gz) is
                                                            held on a drop; exit 0 (the save goes on)
    python3 -I scripts/state_paths.py save-check COUNTS [--restored FILE] [--build DIR]
                                                            exit 1 (an ::error::) when data/build/events is missing or
                                                            empty while the restored state had events files
    python3 -I scripts/state_paths.py generations plan|put [FILE] [--record FILE] [--run-id ID]
                                                            plan: record the previous run's copies their markers name,
                                                            print the copies due and write them as pending; put FILE:
                                                            upload the saved archive to them, then their markers;
                                                            exit 0 (a failed upload is a warning)

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
import signal
import subprocess
import sys
import tarfile
import time
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAX_MB = 200.0
WRANGLER_MAX_MB = 314.0          # wrangler r2 object put refuses a file over 300 MiB (314.6 MB)
BUCKET = "dirtywaterwatch-data"
# the history copies of state/build.tar.gz (put() writes these keys only; never current/ or any public path)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
GENERATION_KEY = re.compile(r"state/daily/build-(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.(?:tar\.gz|json)"
                            r"|state/monthly/build-[0-9]{4}-(?:0[1-9]|1[0-2])\.(?:tar\.gz|json)"
                            r"|state/held/build-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-z][0-9a-z-]{0,39}\.tar\.gz")
# state/PAUSE: the shared pause switch; the history copies may be fetched too (to look at one before a rollback)
STATE_KEY = re.compile(r"state/[a-z0-9][a-z0-9._-]*\.tar\.gz|state/PAUSE|" + GENERATION_KEY.pattern)
# wrangler's answer for a key that is not there ("The specified key does not exist."): a first run, not a failure
MISSING = re.compile(r"specified key does not exist|NoSuchKey", re.I)
FETCHED, ABSENT, FAILED = 0, 3, 1
# openboatlaunch's water records (state/obl-water.tar.gz) and where the pipeline reads them: <repo>/../openboatlaunch/out
OBL_KEY = "state/obl-water.tar.gz"
OBL_OUT = ROOT.parent / "openboatlaunch" / "out"
OBL_RECORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.json")
# a water record's outline is a few MB at most (a Great Lake's): a member over OBL_MEMBER_MAX is skipped and counted,
# and an object that unpacks to more than OBL_TOTAL_MAX in all is refused (a damaged or wrong object, never a snapshot)
OBL_CHANGES = ROOT / "data" / "build" / "obl-changes.json"   # the API state: national pull, changes until (shared)
OBL_MARK = ".dww-changed"          # left in OBL_OUT when the API changed the folder this run: pack-obl saves it
OBL_NATIONAL_MIN_H = 24.0          # a national bulk pull at most once a day
NOT_USED = 4
OBL_MEMBER_MAX = 256 * 1024 * 1024
OBL_TOTAL_MAX = 8 * 1024 * 1024 * 1024


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
    Entry("data/raw/census/tl_2023_us_state.zip",
          "build/reaches.py tiger_states(): the Census TIGER/Line state boundaries through the Great Lakes, the outline "
          "of a Great Lakes record that has none (its state's waters in the lake; downloaded once, 10 MB)"),
    Entry("data/raw/iem-iemre",
          "build/rain_thresholds.py: IEM's MRMS daily rainfall per outfall point and year (past years final)"),
    Entry("data/raw/nws-gauges/observations.json",
          "ingest/rainfall.py gauge_check(): the airport gauges' latest observations and MRMS identify at them, per "
          "valid time, so a rerun in the same hour asks again for none of them (the unit cross-check, 2026-11-07)"),
    Entry("data/raw/obl-api",
          "pipeline/obl_api.py: openboatlaunch's API meta with its ETag (the hourly meta check answers 304 and needs "
          "the body it confirms) and the state pages a state build read, with their snapshot (a second build on the "
          "same snapshot asks again for nothing)"),
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


def run_killable(cmd: list[str], timeout: float) -> tuple[int | None, str]:
    """(exit code, output) of cmd, stdout and stderr together; (None, the reason) when it could not start or ran past
    timeout, in which case its whole process group (wrangler's filter and the AWS CLI it starts) is killed."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                             start_new_session=True)
    except OSError as ex:
        return None, type(ex).__name__
    try:
        out, _ = p.communicate(timeout=max(timeout, 0.1))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()
        try:
            p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return None, "TimeoutExpired"
    return p.returncode, out or ""


def _attempts(tries: int, budget_s: float | None, per_try_s: float):
    """The timeouts of up to `tries` attempts: per_try_s each, or with a total budget (retries and pauses included)
    what is left of it. Yields (attempt number, timeout); the caller sleeps between attempts with pause()."""
    end = None if budget_s is None else time.monotonic() + budget_s
    for n in range(tries):
        left = per_try_s if end is None else min(per_try_s, end - time.monotonic())
        if left < 1:
            return
        yield n, left


def _pause(n: int, tries: int, budget_end: float | None, pause: float) -> bool:
    """Sleep before attempt n + 1; False when there is none, or no time for it within the budget."""
    if n >= tries - 1:
        return False
    wait = pause * (n + 1)
    if budget_end is not None and time.monotonic() + wait + 1 >= budget_end:
        return False
    time.sleep(wait)
    return True


def fetch(key: str, out: Path, tries: int = 3, wrangler: str | None = None, budget_s: float | None = None) -> int:
    """Get a state object with wrangler: FETCHED (0), ABSENT (3: wrangler says there is no such key) or FAILED (1:
    anything else, after `tries` attempts). Never leaves a partial file behind on ABSENT or FAILED. budget_s: a total
    deadline, retries included, for an optional read (a generation marker); without it each attempt has 300 s."""
    if not STATE_KEY.fullmatch(key):
        raise ValueError(f"not a state object key: {key!r}")
    cmd = [wrangler or os.environ.get("WRANGLER") or "wrangler", "r2", "object", "get", f"{BUCKET}/{key}",
           "--file", str(out), "--remote"]
    pause = float(os.environ.get("STATE_FETCH_RETRY_S") or 15)
    if budget_s is not None and budget_s < MIN_OPTIONAL_S:
        say(f"{key}: not fetched, skipped ({max(budget_s, 0):.0f} s left for it, kept for the state save)")
        return FAILED
    end = None if budget_s is None else time.monotonic() + budget_s
    last = "no answer"
    for n, timeout in _attempts(tries, budget_s, 300):
        out.unlink(missing_ok=True)
        rc, text = run_killable(cmd, timeout)
        if rc == 0 and out.is_file():
            say(f"{key}: fetched, {mb(out.stat().st_size)}")
            return FETCHED
        out.unlink(missing_ok=True)
        if MISSING.search(text):
            say(f"{key}: not in the bucket")
            return ABSENT
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        last = lines[-1][:300] if lines else (f"exit {rc}" if rc is not None else text)
        if n < tries - 1:
            say(f"{key}: not fetched ({last}); trying again")
        if not _pause(n, tries, end, pause):
            break
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


BUILD_DIR = "data/build"


def build_member_problem(m: tarfile.TarInfo) -> str | None:
    """Why a member of state/build.tar.gz may not be restored, or None: only data/build itself and regular files and
    directories under it (the folders data and data/build as directories); no link, device or fifo, no absolute or
    '..' path (SOL wave1 P2-14)."""
    name = m.name
    if not name or name.startswith("/") or "\\" in name:
        return "an absolute or odd path"
    parts = [x for x in PurePosixPath(name).parts if x != "."]
    if not parts or any(x in ("..", "") for x in parts):
        return "a path outside data/build"
    if not (m.isfile() or m.isdir()):
        return "a link or special file"
    if parts in (["data"], ["data", "build"]):
        return None if m.isdir() else "a file in place of the data/build folder"
    if len(parts) < 3 or parts[:2] != ["data", "build"]:
        return "a path outside data/build"
    return None


def unpack_build(src: Path, root: Path = ROOT) -> dict:
    """Restore state/build.tar.gz under root. The whole archive is read and every member checked first: one member
    outside data/build, a link, a device or fifo, or a damaged gzip raises Unreadable having written nothing (a
    replaced or mispacked object can never overwrite the code that later runs with the credentials). AppleDouble '._*'
    files are skipped. Refused too when root/data or root/data/build is a link."""
    root = Path(root)
    for d in (root / "data", root / BUILD_DIR):
        if d.is_symlink():
            raise Unreadable(f"{d.relative_to(root)} is a link: not written through")
    try:
        with open(src, "rb") as fh:
            if fh.read(2) != b"\x1f\x8b":
                raise Unreadable(f"{Path(src).name} is not a gzip file")
        with gzip.open(src, "rb") as g:
            while g.read(1 << 20):
                pass
        with tarfile.open(src, "r:gz") as tf:
            ms = tf.getmembers()
            bad = [(m.name, why) for m in ms if (why := build_member_problem(m))]
            if bad:
                shown = "; ".join(f"{n[:120]!r}: {w}" for n, w in bad[:3])
                raise Unreadable(f"{Path(src).name} holds {len(bad)} member(s) that may not be restored ({shown}); "
                                 "nothing was written")
            keep = [m for m in ms if not any(x.startswith("._") for x in PurePosixPath(m.name).parts)]
            tf.extractall(root, members=keep, filter="data")
    except Unreadable:
        raise
    except (OSError, EOFError, tarfile.TarError, zlib.error) as ex:
        raise Unreadable(f"{Path(src).name}: {type(ex).__name__}") from None
    n = sum(1 for m in keep if m.isfile())
    say(f"restored {n} file(s) from {Path(src).name} into {BUILD_DIR}"
        + (f", {len(ms) - len(keep)} AppleDouble file(s) skipped" if len(ms) != len(keep) else ""))
    return {"files": n, "skipped": len(ms) - len(keep)}


ATTAINS_CACHE = "data/build/attains/attains-waters.json"
ATTAINS_GEOM = re.compile(r"data/raw/attains/geom/(?:[A-Z]{2}\.json\.gz|manifest\.json)")
ATTAINS_DIRS = {"data", "data/build", "data/build/attains", "data/raw", "data/raw/attains", "data/raw/attains/geom"}


def attains_member_problem(m: tarfile.TarInfo, only: str | None = None) -> str | None:
    """Why a member of state/attains.tar.gz or state/attains-geom.tar.gz may not be restored, or None: only the
    assessment cache, the per-state geometry files and their manifest (regular files) and the folders above them;
    only="cache" or "geom" allows the one kind of file."""
    name = m.name
    if not name or name.startswith("/") or "\\" in name:
        return "an absolute or odd path"
    parts = [x for x in PurePosixPath(name).parts if x != "."]
    if not parts or any(x in ("..", "") for x in parts):
        return "an odd path"
    path = "/".join(parts)
    if not (m.isfile() or m.isdir()):
        return "a link or special file"
    if m.isdir():
        return None if path in ATTAINS_DIRS else "a folder that is not the cache's"
    ok = (path == ATTAINS_CACHE and only in (None, "cache")) or (bool(ATTAINS_GEOM.fullmatch(path))
                                                                 and only in (None, "geom"))
    return None if ok else "a file that is not the cache's"


def safe_error(ex: BaseException) -> str:
    """An exception as a public log may show it: the pipeline's common.error_text (a fixed category, never the
    exception's own words, which can quote a member name or a path), loaded from pipeline/common.py (standard library
    only); the exception's kind alone when that file cannot be loaded."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("dww_common", ROOT / "pipeline" / "common.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.error_text(ex)
    except Exception:  # noqa: BLE001 - the kind alone rather than the words
        name = type(ex).__name__
        return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", name) else "Error"


def unpack_attains(src: Path, root: Path = ROOT, only: str | None = None) -> dict:
    """Restore state/attains.tar.gz (the assessment cache) or state/attains-geom.tar.gz (the geometry cache) under
    root. The whole archive is read and checked first (attains_member_problem); one member that may not be restored,
    or a damaged gzip, raises Unreadable having written nothing. Refused when a folder on the way is a link. The
    message counts the refused members by their fixed category (attains_member_problem's words) and never names one:
    a member name is the archive's text, which can hold a path or an address, and the logs are public."""
    root = Path(root)
    for d in ATTAINS_DIRS:
        if (root / d).is_symlink():
            raise Unreadable(f"{d} is a link: not written through")
    try:
        with open(src, "rb") as fh:
            if fh.read(2) != b"\x1f\x8b":
                raise Unreadable("the archive is not a gzip file")
        with gzip.open(src, "rb") as g:
            while g.read(1 << 20):
                pass
        with tarfile.open(src, "r:gz") as tf:
            ms = tf.getmembers()
            # AppleDouble '._*' files from a tarball made on a Mac are skipped, as in unpack-build
            ms = [m for m in ms if not any(x.startswith("._") for x in PurePosixPath(m.name).parts)]
            bad = [why for m in ms if (why := attains_member_problem(m, only))]
            if bad:
                counts = sorted(Counter(bad).items())
                shown = "; ".join(f"{why}: {n}" for why, n in counts)
                raise Unreadable(f"the archive holds {len(bad)} member(s) that may not be restored ({shown}); "
                                 "nothing was written")
            if not any(m.isfile() for m in ms):
                raise Unreadable("the archive holds no file; nothing was written")
            tf.extractall(root, members=ms, filter="data")
    except Unreadable:
        raise
    except (OSError, EOFError, tarfile.TarError, zlib.error) as ex:
        raise Unreadable(f"the archive could not be read ({safe_error(ex)})") from None
    n = sum(1 for m in ms if m.isfile())
    say(f"restored {n} file(s) from {Path(src).name}")
    return {"files": n}


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


def in_git_checkout(dest: Path) -> Path | None:
    """The folder holding .git that dest is in or under (dest itself or any folder above it), else None."""
    d = Path(dest).resolve()
    for p in (d, *d.parents):
        if (p / ".git").exists():
            return p
    return None


def unpack_obl(src: Path, dest: Path = OBL_OUT, member_max: int = OBL_MEMBER_MAX,
               total_max: int = OBL_TOTAL_MAX) -> dict:
    """Restore openboatlaunch's water records into dest (<openboatlaunch>/out). Raises Unreadable, having written
    nothing, when the gzip or the tar cannot be read to its end, unpacks to more than total_max, or holds no water
    record, and when dest is in a git checkout (a real openboatlaunch project, or this one, is never written over).
    Only the folder water may be a directory: a directory named like a record or meta.json is skipped, and so is a
    record over member_max."""
    dest = Path(dest)
    repo = in_git_checkout(dest)
    if repo is not None:
        raise Unreadable(f"{dest} is in a git checkout ({repo.name}): not written over")
    counts = {"records": 0, "meta": 0, "skipped_not_listed": 0, "skipped_not_regular": 0, "skipped_too_large": 0}
    try:
        with open(src, "rb") as fh:
            if fh.read(2) != b"\x1f\x8b":
                raise Unreadable(f"{Path(src).name} is not a gzip file")
        with gzip.open(src, "rb") as g:
            total = 0
            while chunk := g.read(1 << 20):
                total += len(chunk)
                if total > total_max:
                    raise Unreadable(f"{Path(src).name} unpacks to more than {mb(total_max)}")
        with tarfile.open(src, "r:gz") as tf:
            members = []
            for m in tf.getmembers():
                if not obl_allowed(m.name):
                    counts["skipped_not_listed"] += 1
                    continue
                is_top_dir = [x for x in PurePosixPath(m.name).parts if x != "."] == ["water"]
                if not ((m.isfile() and not is_top_dir) or (m.isdir() and is_top_dir)):
                    counts["skipped_not_regular"] += 1
                    continue
                if m.isfile() and m.size > member_max:
                    counts["skipped_too_large"] += 1
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


def _obl_api():
    """pipeline/obl_api.py, loaded by its path (this script runs with -I, before the virtual environment exists)."""
    import importlib.util
    if "obl_api" in sys.modules:
        return sys.modules["obl_api"]
    spec = importlib.util.spec_from_file_location("obl_api", ROOT / "pipeline" / "obl_api.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["obl_api"] = mod
    spec.loader.exec_module(mod)
    return mod


def read_obl_changes(path: Path = OBL_CHANGES) -> dict:
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def write_obl_changes(d: dict, path: Path = OBL_CHANGES) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    tmp.replace(path)


def _iso_time(s) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _swap_in(staging: Path, dest: Path) -> None:
    """Put the unpacked staging folder at dest (the old folder removed), so a reader never sees half of each."""
    import shutil
    old = dest.with_name(dest.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if dest.exists():
        dest.rename(old)
    staging.rename(dest)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def fetch_obl(dest: Path = OBL_OUT, state_file: Path = OBL_CHANGES, force: bool = False,
              now: datetime | None = None) -> int:
    """The national bulk file from openboatlaunch's API into dest: FETCHED (0) or NOT_USED (4, with the reason said;
    the workflow then restores the R2 copy). Never raises for an API failure; never prints the key."""
    import shutil
    import tempfile
    api = _obl_api()
    now = now or datetime.now(timezone.utc)
    st0 = read_obl_changes(state_file)
    if st0:
        # cleared at the start, so an early return never leaves an older run's value for obl-not-saved to restore
        st0["national_before"] = st0.get("national")
        st0.pop("need_full_before", None)
        write_obl_changes(st0, state_file)
    if not api.key():
        say("openboatlaunch API: no OBL_API_KEY here; the R2 copy is restored instead")
        return NOT_USED
    dest = Path(dest)
    if (repo := in_git_checkout(dest)) is not None:
        say(f"openboatlaunch API: {dest} is in a git checkout ({repo.name}): not written over; the R2 copy is used")
        return NOT_USED
    try:
        m = api.meta()
    except api.ApiError as ex:
        print(f"::warning::openboatlaunch API meta could not be read ({ex}); the R2 copy is restored instead", flush=True)
        return NOT_USED
    snap = m.get("snapshot")
    st = read_obl_changes(state_file)
    last = st.get("national") if isinstance(st.get("national"), dict) else {}
    when = _iso_time(last.get("fetched_at")) if last else None
    full = bool(st.get("need_full"))               # ingest.obl_changes: the change history did not reach (410)
    if not force and not full and last.get("snapshot") == snap and (dest / "water").is_dir():
        say(f"openboatlaunch API: snapshot {snap} is the one pulled at {last.get('fetched_at')}; the folder is current")
        return NOT_USED
    if not force and not full and last.get("snapshot") == snap:
        say(f"openboatlaunch API: snapshot {snap} is the one pulled at {last.get('fetched_at')} and saved to R2; "
            "the R2 copy is restored")
        return NOT_USED
    if not force and not full and when is not None and (now - when).total_seconds() < OBL_NATIONAL_MIN_H * 3600:
        say(f"openboatlaunch API: snapshot {snap} is newer than the one pulled at {last.get('fetched_at')}, but the "
            f"national file is pulled at most once a day; the R2 copy is restored and the hourly changes check brings "
            "it up to date")
        return NOT_USED
    if full:
        say("openboatlaunch API: the changes check asked for a full pull (need_full): the national file is pulled")
    nat = ((m.get("bulk") or {}).get("national") or {})
    want = str(nat.get("sha256") or "").lower()
    try:
        path = api.path_of(nat.get("url") or "bulk/national.tar.gz")
    except api.ApiError as ex:
        print(f"::warning::openboatlaunch API: {ex}; the R2 copy is restored instead", flush=True)
        return NOT_USED
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".obl-fetch-", dir=dest.parent))
    try:
        tgz = work / "national.tar.gz"
        a = api.get(path, stream_to=tgz, accept_json=False, timeout=600)
        if a.status != 200:
            raise api.ApiError(f"{path}: HTTP {a.status}")
        side = api.get(path + ".sha256", accept_json=False)
        if side.status != 200:
            raise api.ApiError(f"{path}.sha256: HTTP {side.status}")
        stated = (side.body.decode("ascii", "replace").split() or [""])[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", stated):
            raise api.ApiError(f"{path}.sha256 holds no sha256")
        if a.sha256 != stated or (want and a.sha256 != want):
            raise api.ApiError(f"{path}: sha256 does not match its .sha256 file or meta; not unpacked")
        staging = work / "out"
        counts = unpack_obl(tgz, staging)
        try:
            got = json.loads((staging / "meta.json").read_text()).get("snapshot")
        except (OSError, ValueError, AttributeError):
            got = None
        if got and got != snap:
            say(f"openboatlaunch API: the bulk file is snapshot {got}, meta said {snap} (replaced between the two "
                "requests); the bulk file's is used")
        (staging / OBL_MARK).write_text(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _swap_in(staging, dest)
    except (api.ApiError, Unreadable, OSError) as ex:
        print(f"::warning::openboatlaunch API national file not used ({api.scrub(str(ex))}); the R2 copy is restored "
              "instead", flush=True)
        return NOT_USED
    finally:
        shutil.rmtree(work, ignore_errors=True)
    st = read_obl_changes(state_file)
    st["national"] = {"snapshot": got or snap, "built": m.get("built"), "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "bytes": a.size, "sha256": a.sha256, "records": counts["records"]}
    if st.pop("need_full", None):
        st["full_pulled"] = True                   # ingest.obl_changes then rewrites every live state from it
        # kept until the folder is saved: obl-not-saved asks for the full pull again (SOL wave2 P2-8)
        st["need_full_before"] = True
    write_obl_changes(st, state_file)
    say(f"openboatlaunch API: national snapshot {got or snap} ({mb(a.size)}, sha256 checked), {counts['records']} "
        f"record(s) unpacked into {dest.name}/")
    return FETCHED


def pack_obl(out: Path, src: Path = OBL_OUT, always: bool = False) -> int:
    """Pack src's water/ and meta.json (regular files) into out for R2 when the API changed it this run (the mark),
    or always. FETCHED (0) packed, ABSENT (3) nothing to save."""
    src = Path(src)
    if not (src / "water").is_dir() or not (always or (src / OBL_MARK).exists()):
        say("openboatlaunch folder unchanged by the API this run (or absent): state/obl-water.tar.gz is not saved")
        return ABSENT

    def regular(ti: tarfile.TarInfo):
        if not (ti.isfile() or ti.isdir()) or any(x.startswith("._") for x in PurePosixPath(ti.name).parts):
            return None
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        return ti

    tmp = Path(out).with_name(Path(out).name + ".part")
    with tarfile.open(tmp, "w:gz", compresslevel=6) as tf:
        tf.add(src / "water", arcname="water", recursive=True, filter=regular)
        if (src / "meta.json").is_file():
            tf.add(src / "meta.json", arcname="meta.json", filter=regular)
    tmp.replace(out)
    say(f"openboatlaunch folder packed for R2: {mb(Path(out).stat().st_size)}")
    return FETCHED


# ---------------------------------------------------------------- history copies of state/build.tar.gz (2026-11-21)

EVENT_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json")   # data/build/events/<source>.json; no AppleDouble '._'
DROP_MIN_RECORDS = 5               # a drop: at least this many records fewer...
DROP_MIN_PERCENT = 1               # ...and at least this share of the restored count
GUARD_FILE = ROOT / BUILD_DIR / "history-guard.json"
GUARD_KEEP = 50                    # earlier drop runs kept in it (their held keys among them)
GENERATIONS_FILE = ROOT / BUILD_DIR / "state-generations.json"
# Time for the optional R2 operations (Astra review 2026-11-21 P1-2): each has a total deadline, retries included, and
# none runs past SAVE_RESERVE_S before the job's limit (refresh.yml timeout-minutes), counted from the start the
# restore step writes to JOB_START_FILE
JOB_START_FILE = ROOT / "job-started"
JOB_LIMIT_S = 100 * 60
SAVE_RESERVE_S = 15 * 60
OPTIONAL_CAP_S = {"held": 600.0, "copy": 600.0, "marker": 60.0}
MIN_OPTIONAL_S = 20.0


def utc_now() -> datetime:
    """The clock in UTC; STATE_NOW (an ISO time, for the tests) stands in for it."""
    t = _iso_time(os.environ["STATE_NOW"]) if os.environ.get("STATE_NOW") else None
    return t.astimezone(timezone.utc) if t is not None else datetime.now(timezone.utc)


def stamp(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_token(arg: str | None = None) -> str:
    """This run's id in keys and records: --run-id, else GITHUB_RUN_ID with '-a<attempt>' for a re-run attempt (a
    re-run never overwrites the first attempt's held copy), else 'local'. ValueError for anything that could not be
    part of a key."""
    if arg:
        tok = str(arg)
    else:
        rid, att = os.environ.get("GITHUB_RUN_ID") or "", os.environ.get("GITHUB_RUN_ATTEMPT") or "1"
        tok = (rid + (f"-a{att}" if att != "1" else "")) if rid else "local"
    tok = tok.lower()
    if not re.fullmatch(r"[0-9a-z][0-9a-z-]{0,39}", tok):
        raise ValueError(f"not a run id: {tok[:60]!r}")
    return tok


def read_json_dict(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def write_json(path: Path, d) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _record_counts(d) -> dict:
    """Counts of one events file: records, those marked duplicate_of (another source's copy) and those marked
    missing from the source (raw._missing_from_source_since); {"unreadable": True} when it is not an events file."""
    recs = d.get("records") if isinstance(d, dict) else None
    if not isinstance(recs, list):
        return {"unreadable": True}
    dup = miss = 0
    for r in recs:
        if isinstance(r, dict):
            dup += bool(r.get("duplicate_of"))
            raw = r.get("raw")
            miss += isinstance(raw, dict) and bool(raw.get("_missing_from_source_since"))
    return {"records": len(recs), "duplicate_of": dup, "missing_from_source": miss}


def event_counts(src: Path) -> dict:
    """{source: counts} for every data/build/events/<source>.json in src: the data/build folder, or a state tarball
    (state/build.tar.gz, a daily, monthly or held copy; read, never unpacked). Counts only, never a record."""
    src = Path(src)
    out: dict = {}
    if src.is_dir():
        d = src / "events"
        for p in sorted(d.glob("*.json")) if d.is_dir() else []:
            if not EVENT_FILE.fullmatch(p.name) or p.is_symlink() or not p.is_file():
                continue
            try:
                out[p.name[:-5]] = _record_counts(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                out[p.name[:-5]] = {"unreadable": True}
        return out
    with tarfile.open(src, "r:gz") as tf:
        for m in tf:
            parts = [x for x in PurePosixPath(m.name).parts if x != "."]
            if len(parts) != 4 or parts[:3] != ["data", "build", "events"] or not m.isfile() \
                    or not EVENT_FILE.fullmatch(parts[3]):
                continue
            try:
                out[parts[3][:-5]] = _record_counts(json.load(tf.extractfile(m)))
            except (OSError, ValueError, EOFError, zlib.error):
                out[parts[3][:-5]] = {"unreadable": True}
    return dict(sorted(out.items()))


def write_counts(src: Path, out: Path, now: datetime | None = None) -> dict:
    sources = event_counts(src)
    n = sum(c.get("records") or 0 for c in sources.values())
    write_json(out, {"counted_at": stamp(now or utc_now()), "of": Path(src).name, "sources": sources})
    say(f"{len(sources)} events file(s), {n} record(s) counted in {Path(src).name}")
    return sources


def history_drops(before: dict, after: dict) -> list[dict]:
    """The sources whose events file disappeared (whether or not it could be read when restored: its bytes may still
    have been recoverable), can no longer be read, or whose records fell by at least DROP_MIN_RECORDS and
    DROP_MIN_PERCENT percent of the restored count. A source unreadable when restored that is still there has no
    count to compare and is left out."""
    out = []
    for sid in sorted(before):
        b = before[sid] if isinstance(before[sid], dict) else {}
        n = b.get("records") if isinstance(b.get("records"), int) and not b.get("unreadable") else None
        a = after.get(sid)
        if a is None:
            out.append({"source": sid, "why": "events file gone", "before": b, "after": None})
        elif n is None:
            continue
        elif a.get("unreadable") or not isinstance(a.get("records"), int):
            out.append({"source": sid, "why": "events file unreadable", "before": b, "after": None})
        elif (fell := n - a["records"]) >= DROP_MIN_RECORDS and fell * 100 >= n * DROP_MIN_PERCENT:
            out.append({"source": sid, "why": "records fell", "before": b, "after": a})
    return out


def _shown(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "?", str(sid))[:80]


def job_start() -> float | None:
    """The job's start (epoch seconds) the restore step wrote (JOB_START_FILE, or STATE_JOB_START_FILE); None when
    there is none (outside the workflow)."""
    path = Path(os.environ.get("STATE_JOB_START_FILE") or JOB_START_FILE)
    try:
        return float(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def optional_budget(kind: str) -> float:
    """Seconds an optional R2 operation (OPTIONAL_CAP_S: held, copy, marker) may take, retries included: its own cap,
    and never past SAVE_RESERVE_S before the job's limit (JOB_LIMIT_S from the start on file), so the state save and
    the steps after it keep their time. Below MIN_OPTIONAL_S the operation is skipped."""
    cap = OPTIONAL_CAP_S[kind]
    start = job_start()
    if start is None:
        return cap
    return min(cap, start + JOB_LIMIT_S - SAVE_RESERVE_S - time.time())


def put(key: str, src: Path, tries: int = 2, wrangler: str | None = None, budget_s: float | None = None) -> int:
    """Upload src to a history-copy key (GENERATION_KEY only) with `wrangler r2 object put BUCKET/KEY --file F
    --remote`, the form the workflow uses: FETCHED (0) uploaded, FAILED (1) not (the reason is said; the caller
    warns). Every attempt counts against one total deadline (budget_s, default optional_budget for the key's kind),
    and a stalled upload is killed when it runs out; with too little time left it is skipped."""
    if not GENERATION_KEY.fullmatch(key):
        raise ValueError(f"not a history copy key: {key!r}")
    if budget_s is None:
        budget_s = optional_budget("held" if key.startswith("state/held/") else
                                   "marker" if key.endswith(".json") else "copy")
    if budget_s < MIN_OPTIONAL_S:
        say(f"{key}: not uploaded, skipped ({max(budget_s, 0):.0f} s left for it, kept for the state save)")
        return FAILED
    cmd = [wrangler or os.environ.get("WRANGLER") or "wrangler", "r2", "object", "put", f"{BUCKET}/{key}",
           "--file", str(src), "--remote"]
    pause = float(os.environ.get("STATE_FETCH_RETRY_S") or 15)
    end = time.monotonic() + budget_s
    last = "no answer"
    for n, timeout in _attempts(tries, budget_s, budget_s):
        rc, text = run_killable(cmd, timeout)
        if rc == 0:
            say(f"{key}: uploaded, {mb(Path(src).stat().st_size)}")
            return FETCHED
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        last = lines[-1][:300] if lines else (f"exit {rc}" if rc is not None else text)
        if n < tries - 1:
            say(f"{key}: not uploaded ({last}); trying again")
        if not _pause(n, tries, end, pause):
            break
    say(f"{key}: not uploaded ({last})")
    return FAILED


def restored_baseline(restored_counts: Path, restored: Path | None) -> dict | None:
    """The restored records per source: the counts taken at the restore, else the kept archive counted; None when
    there is no restored state (a first run) or it cannot be counted (said in a warning)."""
    if Path(restored_counts).is_file():
        s = read_json_dict(restored_counts).get("sources")
        if isinstance(s, dict):
            return s
        say(f"{Path(restored_counts).name} cannot be read")
    if restored is None or not Path(restored).is_file():
        return None
    try:
        before = event_counts(Path(restored))
    except (OSError, EOFError, tarfile.TarError, zlib.error) as ex:
        print(f"::warning::the restored state could not be counted ({type(ex).__name__})", flush=True)
        return None
    say(f"the restored records were counted from {Path(restored).name}")
    return before


def guard(restored_counts: Path, build: Path = ROOT / BUILD_DIR, out: Path = GUARD_FILE,
          restored: Path | None = None, run: str = "local", now: datetime | None = None,
          wrangler: str | None = None) -> list[dict]:
    """Before the save: compare data/build/events with the counts taken at the restore (restored_counts; the kept
    archive `restored` is counted instead when they are missing). A missing build folder counts as every restored
    source gone. On a drop: one ::warning:: per source (counts only), the restored archive uploaded to
    state/held/build-<UTC date>-<run>.tar.gz (within optional_budget), and `out` written when its folder is there
    (time, run, the drops, the held key and whether it uploaded; earlier drop runs kept below). Returns the drops;
    never stops the save and never creates the build folder. No restored state (a first run): nothing compared."""
    now = now or utc_now()
    restored = Path(restored) if restored else None
    before = restored_baseline(restored_counts, restored)
    if before is None:
        if restored is None or not restored.is_file():
            say("history guard: no restored state (a first run); nothing to compare")
        else:
            print("::warning::history guard: the history was not compared this run", flush=True)
        return []
    drops = history_drops(before, event_counts(build) if Path(build).is_dir() else {})
    if not drops:
        say(f"history guard: {len(before)} source(s) compared with the restored state; no drop")
        return []
    key = f"state/held/build-{now.strftime('%Y-%m-%d')}-{run}.tar.gz"
    held = restored is not None and restored.is_file() and put(key, restored, wrangler=wrangler) == FETCHED
    for d in drops:
        b, a = d["before"].get("records"), (d["after"] or {}).get("records")
        b = b if isinstance(b, int) and not d["before"].get("unreadable") else "an unknown number of"
        print(f"::warning::history guard: {_shown(d['source'])}: {d['why']}, {b} record(s) restored, "
              f"{'none readable' if a is None else a} now; the state is saved as usual", flush=True)
    if held:
        say(f"history guard: {len(drops)} source(s) lost records; the restored state is held at {key}")
    else:
        print(f"::warning::history guard: the restored state could not be held at {key}; the state is saved as "
              "usual", flush=True)
    if not Path(out).parent.is_dir():
        say(f"history guard: {Path(out).parent} is gone; {Path(out).name} is not written")
        return drops
    prev = read_json_dict(out)
    earlier = ([{k: prev[k] for k in ("time", "run", "drops", "held") if k in prev}] if prev.get("time") else []) \
        + [e for e in prev.get("earlier") or [] if isinstance(e, dict)]
    write_json(out, {"time": stamp(now), "run": run, "drops": drops, "held": {"key": key, "uploaded": held},
                     "earlier": earlier[:GUARD_KEEP]})
    return drops


def save_check(restored_counts: Path, build: Path = ROOT / BUILD_DIR, restored: Path | None = None) -> bool:
    """Right before the state is archived: False, with an ::error::, when data/build/events is missing or holds no
    events file while the restored state had some (or a restored state is there that cannot be counted). The save
    step then fails and the stored state stands, rather than a run that ended well replacing the history with
    nothing (Astra review 2026-11-21 P1-1). A first run, or a restored state with no events file, passes."""
    events = Path(build) / "events"
    n = sum(1 for p in events.glob("*.json") if EVENT_FILE.fullmatch(p.name) and p.is_file()) \
        if events.is_dir() else 0
    if n:
        return True
    restored = Path(restored) if restored else None
    before = restored_baseline(restored_counts, restored)
    if before is None and (restored is None or not restored.is_file()) and not Path(restored_counts).is_file():
        return True                                    # a first run: nothing restored
    if before == {}:
        return True
    had = f"{len(before)} events file(s)" if before else "a history that could not be counted"
    print(f"::error::data/build/events is {'empty' if events.is_dir() else 'missing'} while the restored state had "
          f"{had}; state/build.tar.gz is not saved over, so the stored state stands", flush=True)
    return False


def generation_key(kind: str, slot: str, mark: bool = False) -> str:
    """state/<kind>/build-<slot>.tar.gz, the copy, or with mark its .json marker (written only after the copy)."""
    key = f"state/{kind}/build-{slot}.{'json' if mark else 'tar.gz'}"
    if kind not in ("daily", "monthly") or not GENERATION_KEY.fullmatch(key):
        raise ValueError(f"not a generation: {kind} {slot!r}")
    return key


def generations_due(rec: dict, now: datetime) -> list[dict]:
    """The copies a save at `now` is due for: the day's daily (state/daily/build-<weekday>.tar.gz) when the record
    does not hold this UTC date for that weekday, the month's monthly when the record does not hold this month."""
    day, slot, month = now.strftime("%Y-%m-%d"), WEEKDAYS[now.weekday()], now.strftime("%Y-%m")
    daily = rec.get("daily") if isinstance(rec.get("daily"), dict) else {}
    monthly = rec.get("monthly") if isinstance(rec.get("monthly"), dict) else {}
    due = []
    if (daily.get(slot) or {}).get("date") != day:
        due.append({"kind": "daily", "slot": slot, "date": day, "key": generation_key("daily", slot)})
    if month not in monthly:
        due.append({"kind": "monthly", "slot": month, "date": day, "key": generation_key("monthly", month)})
    return due


DATE_RE = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])")
MONTH_RE = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
RUN_RE = re.compile(r"[0-9a-z][0-9a-z-]{0,39}")


def normalize_generations(rec) -> tuple[dict, bool]:
    """(the record with only well-formed entries, whether anything was dropped). daily: {weekday: {"date", "run"}}
    with a weekday key and a date; monthly: {"YYYY-MM": {...}}; pending: {"run", "planned_at", "copies": [daily or
    monthly copies with a valid slot and date]}. A malformed entry is dropped (its copy is then due again); a
    malformed record starts again from nothing (Astra review 2026-11-21 P2-4)."""
    if not isinstance(rec, dict):
        return {}, rec not in ({}, None)
    out: dict = {}
    daily = rec.get("daily") if isinstance(rec.get("daily"), dict) else {}
    out["daily"] = {k: {"date": v["date"], **({"run": str(v["run"])} if isinstance(v.get("run"), (str, int)) else {})}
                    for k, v in daily.items()
                    if k in WEEKDAYS and isinstance(v, dict) and isinstance(v.get("date"), str)
                    and DATE_RE.fullmatch(v["date"])}
    monthly = rec.get("monthly") if isinstance(rec.get("monthly"), dict) else {}
    out["monthly"] = {k: v for k, v in monthly.items() if isinstance(k, str) and MONTH_RE.fullmatch(k)
                      and isinstance(v, dict)}
    pend = rec.get("pending")
    if isinstance(pend, dict) and isinstance(pend.get("run"), str) and RUN_RE.fullmatch(pend["run"]) \
            and isinstance(pend.get("copies"), list):
        copies = []
        for g in pend["copies"]:
            if not (isinstance(g, dict) and g.get("kind") in ("daily", "monthly") and isinstance(g.get("slot"), str)
                    and isinstance(g.get("date"), str) and DATE_RE.fullmatch(g["date"])):
                continue
            try:
                key = generation_key(g["kind"], g["slot"])
            except ValueError:
                continue
            copies.append({"kind": g["kind"], "slot": g["slot"], "date": g["date"], "key": key})
        if copies:
            out["pending"] = {"run": pend["run"], "planned_at": pend.get("planned_at"), "copies": copies}
    return out, out != {"daily": {}, "monthly": {}, **rec}


def _marker_says(kind: str, slot: str, date, run: str, wrangler: str | None = None) -> bool:
    """True when the copy's marker in R2 names this copy, date and run: the copy uploaded. Absent, unreadable, not
    read within its time (optional_budget) or naming another run (an earlier week's, or a copy whose upload failed
    after an earlier one): False."""
    import tempfile
    fd, name = tempfile.mkstemp(prefix="dww-mark-", suffix=".json")
    os.close(fd)
    tmp = Path(name)
    try:
        if fetch(generation_key(kind, slot, mark=True), tmp, tries=2, wrangler=wrangler,
                 budget_s=optional_budget("marker")) != FETCHED:
            return False
        m = read_json_dict(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return m.get("key") == generation_key(kind, slot) and m.get("date") == date and m.get("run") == run


def generations_plan(record: Path = GENERATIONS_FILE, run: str = "local", now: datetime | None = None,
                     wrangler: str | None = None) -> list[str]:
    """Before the archive is made. The record is checked first (a malformed one repaired: normalize_generations).
    Then the copies an earlier run left pending are recorded when their markers say they uploaded (one small read
    each, once a day); then the copies this save is due for are written as this run's pending ones (the record
    travels in the archive and claims nothing for them) and their keys printed. When the build folder is missing,
    nothing is written (the folder is never made here) and no generation is due."""
    now = now or utc_now()
    record = Path(record)
    if not record.parent.is_dir():
        print(f"::warning::state generations: {record.parent} is missing; no generation is made this run",
              flush=True)
        return []
    try:
        raw = json.loads(record.read_text(encoding="utf-8")) if record.exists() else {}
    except (OSError, ValueError):
        raw = None
    rec, repaired = normalize_generations(raw)
    if repaired:
        say(f"the generation record {record.name} was malformed; repaired (what could not be read is due again)")
    pend = rec.get("pending") or {}
    if pend.get("run") and pend["run"] != run:
        for g in pend["copies"]:
            if _marker_says(g["kind"], g["slot"], g["date"], pend["run"], wrangler):
                rec[g["kind"]][g["slot"]] = {"date": g["date"], "run": pend["run"]}
                say(f"generation {g['key']} of run {pend['run']}: uploaded, recorded")
            else:
                say(f"generation {g['key']} of run {pend['run']}: no marker for it, so not recorded (made again when "
                    "due)")
    due = generations_due(rec, now)
    if due:
        rec["pending"] = {"run": run, "planned_at": stamp(now), "copies": due}
    else:
        rec.pop("pending", None)
    write_json(record, rec)
    for g in due:
        say(f"generation due: {g['key']}")
    if not due:
        say("no generation due (the day's daily and the month's monthly are made)")
    return [g["key"] for g in due]


def generations_put(src: Path, record: Path = GENERATIONS_FILE, run: str = "local", now: datetime | None = None,
                    wrangler: str | None = None) -> list[str]:
    """After the save: upload src (the archive just saved) to each copy this run planned, then each copy's marker
    (state/<kind>/build-<slot>.json: key, date, run), which the next run's plan reads to record it. Returns the
    copies uploaded with their markers. A failed upload is a warning and leaves no marker, so the next run makes the
    copy again; it never stops the run."""
    import tempfile
    now = now or utc_now()
    pend = normalize_generations(read_json_dict(record))[0].get("pending") or {}
    if pend.get("run") != run or not pend.get("copies"):
        say("no generation planned by this run")
        return []
    made = []
    for g in pend["copies"]:
        try:
            kind, slot = g["kind"], g["slot"]
            key, mark = generation_key(kind, slot), generation_key(kind, slot, mark=True)
        except (KeyError, TypeError, ValueError):
            say("a pending generation that is not one was left out")
            continue
        if put(key, src, wrangler=wrangler) != FETCHED:
            print(f"::warning::state generation {key} was not uploaded; the next run makes it again (the run goes "
                  "on)", flush=True)
            continue
        fd, name = tempfile.mkstemp(prefix="dww-mark-", suffix=".json")
        os.close(fd)
        tmp = Path(name)
        try:
            write_json(tmp, {"key": key, "date": g.get("date"), "run": run, "made_at": stamp(now),
                             "bytes": Path(src).stat().st_size})
            ok = put(mark, tmp, wrangler=wrangler) == FETCHED
        finally:
            tmp.unlink(missing_ok=True)
        if ok:
            made.append(key)
        else:
            print(f"::warning::state generation {key} uploaded but its marker {mark} did not; it is not recorded and "
                  "the next run makes it again", flush=True)
    return made


def obl_not_saved(state_file: Path = OBL_CHANGES, src: Path = OBL_OUT) -> int:
    """The folder the API changed this run could not be saved to R2: put the national pull and the changes' until
    back to where they were before this run (data/build/obl-changes.json "national_before", "until_before", and
    need_full when this run's full pull consumed it: "need_full_before"), so the next run, restoring the older R2 copy,
    pulls and asks for those changes again. Exit 0."""
    if not (Path(src) / OBL_MARK).exists():
        return 0
    st = read_obl_changes(state_file)
    if not st:
        return 0
    if "national_before" in st:
        st["national"] = st.pop("national_before")
    if "until_before" in st:
        st["until"] = st.pop("until_before")
        st.pop("etag", None)
    if st.pop("need_full_before", None):
        # this run's full pull (asked for by need_full: the changes it replaces were never fetched one by one) was not
        # saved: the next run restores the older copy, so the full pull is asked for again (SOL wave2 P2-8)
        st["need_full"] = True
        st.pop("full_pulled", None)
    write_obl_changes(st, state_file)
    print("::warning::the openboatlaunch folder changed by the API was not saved to R2; the next run pulls those "
          "changes again", flush=True)
    return 0


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
    s = sub.add_parser("unpack-build")
    s.add_argument("file")
    s = sub.add_parser("unpack-attains")
    s.add_argument("file")
    s.add_argument("--only", choices=("cache", "geom"), help="allow only the assessment cache, or only the geometry")
    s = sub.add_parser("unpack-obl")
    s.add_argument("file")
    s.add_argument("--to", default=str(OBL_OUT), help="openboatlaunch's out folder (default ../openboatlaunch/out)")
    s = sub.add_parser("fetch-obl")
    s.add_argument("--to", default=str(OBL_OUT), help="openboatlaunch's out folder (default ../openboatlaunch/out)")
    s.add_argument("--force", action="store_true", help="pull the national file even if pulled today")
    s.add_argument("--state-file", default=str(OBL_CHANGES), help="the API state (default data/build/obl-changes.json)")
    s = sub.add_parser("pack-obl")
    s.add_argument("file")
    s.add_argument("--from", dest="src", default=str(OBL_OUT))
    s.add_argument("--always", action="store_true")
    s = sub.add_parser("obl-not-saved")
    s.add_argument("--state-file", default=str(OBL_CHANGES))
    s.add_argument("--from", dest="src", default=str(OBL_OUT))
    s = sub.add_parser("fetch")
    s.add_argument("key")
    s.add_argument("file")
    s = sub.add_parser("counts", help="records per source of the data/build folder or a state tarball")
    s.add_argument("src")
    s.add_argument("out")
    s = sub.add_parser("guard", help="the history guard before the save")
    s.add_argument("restored_counts")
    s.add_argument("--restored", help="the restored archive, held in R2 on a drop (default restored-build.tar.gz)",
                   default="restored-build.tar.gz")
    s.add_argument("--build", default=str(ROOT / BUILD_DIR))
    s.add_argument("--out", default=str(GUARD_FILE))
    s.add_argument("--run-id")
    s = sub.add_parser("save-check", help="refuse to save over the history with no events file")
    s.add_argument("restored_counts")
    s.add_argument("--restored", default="restored-build.tar.gz")
    s.add_argument("--build", default=str(ROOT / BUILD_DIR))
    s = sub.add_parser("generations", help="the daily and monthly copies: plan before the archive, put after the save")
    s.add_argument("action", choices=("plan", "put"))
    s.add_argument("file", nargs="?", help="put: the archive just saved")
    s.add_argument("--record", default=str(GENERATIONS_FILE))
    s.add_argument("--run-id")
    a = ap.parse_args(argv)
    if a.cmd in ("guard", "generations"):
        try:
            run = run_token(a.run_id)
        except ValueError as ex:
            print(f"::error::{ex}", flush=True)
            return 2
    if a.cmd == "counts":
        try:
            write_counts(Path(a.src), Path(a.out))
        except (OSError, EOFError, tarfile.TarError, zlib.error) as ex:
            print(f"::error::{Path(a.src).name} could not be counted ({type(ex).__name__})", flush=True)
            return 1
        return 0
    if a.cmd == "save-check":
        return 0 if save_check(Path(a.restored_counts), Path(a.build), Path(a.restored) if a.restored else None) else 1
    if a.cmd == "guard":
        guard(Path(a.restored_counts), Path(a.build), Path(a.out), Path(a.restored) if a.restored else None, run)
        return 0
    if a.cmd == "generations":
        if a.action == "plan":
            generations_plan(Path(a.record), run)
            return 0
        if not a.file or not Path(a.file).is_file():
            print("::error::generations put needs the archive just saved", flush=True)
            return 2
        generations_put(Path(a.file), Path(a.record), run)
        return 0
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
    if a.cmd == "fetch-obl":
        return fetch_obl(Path(a.to), Path(a.state_file), force=a.force)
    if a.cmd == "obl-not-saved":
        return obl_not_saved(Path(a.state_file), Path(a.src))
    if a.cmd == "pack-obl":
        return pack_obl(Path(a.file), Path(a.src), a.always)
    if a.cmd == "unpack-build":
        try:
            unpack_build(Path(a.file))
        except Unreadable as ex:
            print(f"::error::the build state could not be restored ({ex})", flush=True)
            return 1
        return 0
    if a.cmd == "unpack-attains":
        try:
            unpack_attains(Path(a.file), only=a.only)
        except Exception as ex:  # noqa: BLE001 - every failure in fixed words (Unreadable's are this script's own)
            say(f"the assessment object could not be read ({safe_error(ex)}); nothing was restored from it")
            return 1
        return 0
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
