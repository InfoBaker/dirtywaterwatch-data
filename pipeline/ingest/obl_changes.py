"""openboatlaunch's hourly changed-since check (a registry helper, not a feed; the first stage of `make refresh`).

    python -m ingest.obl_changes [--obl-dir <openboatlaunch>/out/water] [--max-records 2000]

Asks openboatlaunch's API (pipeline/obl_api.py; key in OBL_API_KEY, never printed) for changes?since=<the last
until> with the last ETag (a 304 most hours), fetches each changed record by slug (waters/{slug}: 200 the record,
301 a renamed or merged record with its successor, 410 a deleted one), writes it into the folder the run restored
(../openboatlaunch/out/water, OBL_WATER_DIR's parent; marked so the workflow saves the folder back to R2
state/obl-water.tar.gz: scripts/state_paths.py pack-obl), and rewrites the affected live states' extracts
(data/waters-<st>.json, ingest.obl_waters from the folder). Renames and merges become slug_aliases on the successor
record there (build/status.py slug_aliases resolves them: events, outfall rows and pages follow the new slug). The
placement cache follows geometry_hash (build/status.py outline_files and the extract's geometry_hash).

The state is data/build/obl-changes.json (saved with the pipeline state): until (the next since), etag, the national
pull (scripts/state_paths.py fetch-obl), pending_states (live states whose extract on file is behind the folder:
rewritten every run until the checked-out file equals the rewrite, i.e. until the change is committed to main), and
log, the review list: every rename, merge and deletion, and every outline change (geometry_hash) on a water with an
active report (data/build/status.json), each with a line for docs/status.md, printed here as `status.md: ...` in the
run log. The first run (no until) starts from the folder's snapshot time without rewriting anything; a 410 (since
older than the API keeps) marks every live state pending and asks fetch-obl for a national pull.

Never fails the run: no key, the API down, or no folder are said in one line and the run goes on as before (the
until is not advanced when the changes could not be applied). At most --max-records single records a run; more
changes than that wait for the national pull (need_full).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import BUILD_DIR, DATA_DIR, write_json
from ingest import obl_waters

ROOT = DATA_DIR.parent
STATE_FILE = BUILD_DIR / "obl-changes.json"
STATUS_FILE = BUILD_DIR / "status.json"
MARK = ".dww-changed"            # scripts/state_paths.py OBL_MARK
LOG_KEEP = 500
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*-[a-z]{2}(-\d+)?")
QUIET = ("grey", "none", "")     # a status that is no active report


def say(msg: str) -> None:
    print(f"obl_changes: {msg}", flush=True)


def obl_water_dir() -> Path:
    return Path(os.environ.get("OBL_WATER_DIR") or ROOT.parent / "openboatlaunch" / "out" / "water")


def read(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def live_states() -> list[str]:
    return [str(s).upper() for s in read(DATA_DIR / "rules.json").get("live_states") or []]


def active_reports(path: Path = STATUS_FILE) -> set[str]:
    """The water slugs with a report showing now (the last run's data/build/status.json)."""
    ws = read(path).get("waters") or {}
    return {s for s, w in ws.items() if isinstance(w, dict) and str(w.get("status") or "") not in QUIET}


def folder_snapshot_time(obl_dir: Path) -> str | None:
    """The folder's snapshot time when it came from the API (its meta.json names a snapshot id); None for the older
    hand-packed copy, whose date is no point in the API's change history."""
    m = read(Path(obl_dir).parent / "meta.json")
    return (str(m.get("built") or "") or None) if m.get("snapshot") else None


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_record(obl_dir: Path, rec: dict) -> dict | None:
    """Write a record into the folder; return the record it replaced (or None)."""
    slug = rec.get("slug")
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        return None
    p = Path(obl_dir) / f"{slug}.json"
    old = read(p) or None
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False))
    tmp.replace(p)
    return old


def rewrite(states, obl_dir: Path, until: str | None, data_dir: Path = DATA_DIR) -> dict:
    """Rewrite each state's extract from the folder. {state: "rewritten" | "current" | reason}."""
    out = {}
    for st in sorted(states):
        path = data_dir / f"waters-{st.lower()}.json"
        have = read(path)
        if have and str(have.get("state") or "").upper() != st:
            out[st] = "not this state's extract"
            continue
        before = path.read_bytes() if path.exists() else None
        try:
            obl_waters.extract(st, obl_dir, path, until=until)
        except obl_waters.Partial as ex:
            out[st] = f"refused ({ex})"
            continue
        # the records are what matters: an extract on file with the same records (its source line perhaps naming
        # an older date) is current, and is left exactly as it was
        same = before is not None and (read(path).get("waters") == have.get("waters"))
        if same:
            path.write_bytes(before)
        out[st] = "current" if same else "rewritten"
    return out


def entry(kind: str, slug: str, state: str, at: str, **kw) -> dict:
    e = {"kind": kind, "slug": slug, "state": state, "at": at, **{k: v for k, v in kw.items() if v is not None}}
    if kind in ("renamed", "merged"):
        line = f"openboatlaunch {kind} {slug} into {kw.get('successor_slug')} ({state}); its events and outfalls follow by slug_aliases"
    elif kind == "deleted":
        line = f"openboatlaunch deleted {slug} ({state}); anything citing it needs a new water"
    else:
        line = f"openboatlaunch changed the outline of {slug} ({state}), a water with an active report; placement redone"
    e["status_line"] = line
    return e


def check(obl_dir: Path | None = None, state_file: Path = STATE_FILE, status_file: Path = STATUS_FILE,
          max_records: int = 2000, now: datetime | None = None, data_dir: Path = DATA_DIR) -> dict:
    import obl_api
    obl_dir = Path(obl_dir or obl_water_dir())
    st = read(state_file)
    live = set(live_states()) if data_dir == DATA_DIR else set(read(data_dir / "rules.json").get("live_states") or [])
    pending = set(st.get("pending_states") or [])
    st["until_before"] = st.get("until")
    run = {"at": now_iso(now), "changes": 0, "fetched": 0, "logged": []}
    have_folder = obl_dir.is_dir()
    if not obl_api.key():
        say("no OBL_API_KEY here: no changes asked")
    elif not have_folder:
        say(f"no openboatlaunch folder at {obl_dir.parent.name}/{obl_dir.name}: no changes asked (until kept)")
    elif not st.get("until"):
        start = folder_snapshot_time(obl_dir)
        if start:
            st["until"] = start
            say(f"first run: changes are asked from the folder's snapshot time {start} on")
        else:
            say("first run, and the folder is not an API snapshot (the older copy): no changes asked until one is")
    else:
        try:
            ans = obl_api.changes(st["until"], etag=st.get("etag"))
        except obl_api.ApiError as ex:
            ans = None
            say(f"the API could not be read ({ex}); this run goes on with the folder as restored")
        if ans and ans["status"] == 304:
            say(f"no change since {st['until']} (304)")
        elif ans and ans["status"] == 410:
            st["need_full"] = True
            st.pop("etag", None)
            if folder_snapshot_time(obl_dir):
                pending |= {s for s in live}
                st["until"] = folder_snapshot_time(obl_dir)
            say("410: the change history no longer reaches the last until; a national pull is asked for and every live "
                "state's extract is rewritten from the folder")
        elif ans:
            run["changes"] = len(ans["changes"])
            latest = {}
            for c in ans["changes"]:
                if isinstance(c, dict) and isinstance(c.get("slug"), str):
                    latest[c["slug"]] = c
            if len(latest) > max_records:
                st["need_full"] = True
                say(f"{len(latest)} changed records, over {max_records} a run: left for the national pull (until kept)")
            else:
                ok = apply(latest, obl_dir, live, active_reports(status_file), run, pending)
                if ok:
                    st["until"], st["etag"] = ans["until"], ans.get("etag")
                    say(f"{len(latest)} changed record(s) since {st['until_before']}, applied; until {st['until']}")
                else:
                    say("some changed records could not be fetched; until kept, asked again next run")
    if pending and have_folder:
        res = rewrite(pending & live, obl_dir, st.get("until"), data_dir)
        for s, r in res.items():
            say(f"{s}: extract {r}")
        pending = {s for s in pending if s in live and res.get(s) not in ("current",)}
    elif pending:
        say(f"pending states {sorted(pending)}: no folder this run, rewritten when there is one")
    st["pending_states"] = sorted(pending)
    log = list(st.get("log") or []) + run["logged"]
    st["log"] = log[-LOG_KEEP:]
    st["last_run"] = {k: v for k, v in run.items() if k != "logged"} | {"logged": len(run["logged"])}
    write_json(state_file, st)
    for e in run["logged"]:
        print(f"status.md: {e['status_line']}", flush=True)
    return st


def apply(latest: dict, obl_dir: Path, live: set, reported: set, run: dict, pending: set) -> bool:
    """Fetch each changed record and write it into the folder; log what is for review. False when any could not be
    fetched (nothing is lost: the same changes are asked again)."""
    import obl_api
    ok = True
    for slug, c in sorted(latest.items()):
        try:
            code, rec, succ = obl_api.water(slug)
        except obl_api.ApiError as ex:
            say(f"{slug}: not fetched ({ex})")
            ok = False
            continue
        run["fetched"] += 1
        if rec is None:
            continue
        state = str(rec.get("state") or c.get("state") or slug[-2:]).upper()
        old = write_record(obl_dir, rec)
        Path(obl_dir).parent.joinpath(MARK).write_text(run["at"])
        if state in live:
            pending.add(state)
        status = rec.get("status") or {301: "renamed", 410: "deleted"}.get(code, "active")
        at = c.get("at") or rec.get("updated_at")
        if status in ("renamed", "merged"):
            run["logged"].append(entry(status, slug, state, at, successor_slug=rec.get("successor_slug") or succ))
        elif status == "deleted":
            run["logged"].append(entry("deleted", slug, state, at, name=rec.get("name")))
        elif slug in reported and (old or {}).get("geometry_hash") != rec.get("geometry_hash") and old is not None:
            run["logged"].append(entry("outline", slug, state, at, geometry_hash_before=(old or {}).get("geometry_hash"),
                                       geometry_hash=rec.get("geometry_hash")))
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="openboatlaunch's hourly changed-since check (not a feed)")
    ap.add_argument("--obl-dir", help="openboatlaunch's out/water folder (default OBL_WATER_DIR, else ../openboatlaunch/out/water)")
    ap.add_argument("--max-records", type=int, default=2000)
    a = ap.parse_args(argv)
    try:
        check(Path(a.obl_dir) if a.obl_dir else None, max_records=a.max_records)
    except Exception as ex:  # noqa: BLE001 - never fails the refresh; the message carries no key (obl_api.scrub)
        import obl_api
        say(f"not completed ({type(ex).__name__}: {obl_api.scrub(str(ex))[:300]}); the run goes on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
