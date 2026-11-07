#!/usr/bin/env python3
"""The daily openboatlaunch extracts pull request (.github/workflows/obl-extracts.yml; review 2026-11-07, P2-3).

The hourly refresh rewrites a live state's extract only in its runner (ingest.obl_changes), so the site follows
openboatlaunch within the hour while data/waters-<st>.json in the repository stays as committed. Once a day this
carries those rewrites to a person: every live state's openboatlaunch extract is rewritten from the restored folder
(../openboatlaunch/out/water: the API's national file or the R2 copy the refresh keeps current), with the slug
aliases of renames and merges and the tombstones of deleted and moved waters (ingest.obl_waters), and the changed files
go on a branch batch/obl-<date> with a pull request whose body lists the counts and the review entries of
data/build/obl-changes.json (renames, merges, deletions, outline changes on reported waters) as docs/status.md lines.
Nothing is committed to main. When the pull request is merged, the hourly check finds the extracts current and its
pending states empty. An extract built from another source (DC's, from NHD) is never rewritten.

    python scripts/obl_extracts.py run [--obl-dir DIR] [--body FILE] [--days 7]
    python scripts/obl_extracts.py publish --body FILE [--date YYYY-MM-DD] [--dry-run]
                    the privacy scan over the changed extracts and the body (the blocklist required), then the branch
                    and pull request (scripts/state_batch.py publish, its commands and rules)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

from ingest import obl_changes  # noqa: E402


def _batch():
    if "state_batch" in sys.modules:
        return sys.modules["state_batch"]
    spec = importlib.util.spec_from_file_location("state_batch", ROOT / "scripts" / "state_batch.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["state_batch"] = mod
    spec.loader.exec_module(mod)
    return mod


def say(msg: str) -> None:
    print(f"obl-extracts: {msg}", flush=True)


def counts(path: Path) -> dict:
    d = obl_changes.read(path)
    ws = [w for w in d.get("waters") or [] if isinstance(w, dict)]
    return {"records": len(ws), "slugs": {w.get("slug") for w in ws},
            "tombstones": sum(1 for w in ws if w.get("status") in ("deleted", "moved", "not_in_snapshot")),
            "aliases": sum(len(w.get("slug_aliases") or []) for w in ws)}


def run(obl_dir: Path | None = None, body: Path | None = None, days: int = 7, data_dir: Path | None = None,
        state_file: Path | None = None, now: datetime | None = None) -> dict:
    """Rewrite every live state's openboatlaunch extract from the folder; write the pull request body. Returns
    {state: result}."""
    data_dir = data_dir or obl_changes.DATA_DIR
    obl_dir = Path(obl_dir or obl_changes.obl_water_dir())
    live = sorted({str(s).upper() for s in obl_changes.read(data_dir / "rules.json").get("live_states") or []})
    if not obl_dir.is_dir():
        say(f"no openboatlaunch folder at {obl_dir.parent.name}/{obl_dir.name}: nothing rewritten")
        return {}
    before = {st: counts(data_dir / f"waters-{st.lower()}.json") for st in live}
    st0 = obl_changes.read(state_file or data_dir / "build" / "obl-changes.json")
    res = obl_changes.rewrite(live, obl_dir, st0.get("until"), data_dir)
    lines = [f"Daily openboatlaunch extracts, {(now or datetime.now(timezone.utc)):%Y-%m-%d}, from snapshot "
             f"{(obl_changes.read(obl_dir.parent / 'meta.json').get('snapshot') or 'unknown')}"
             + (f" with changes to {st0['until']}" if st0.get("until") else "") + ".", "",
             "| State | Result | Records | New | Kept as retired | Slug aliases |", "|---|---|---|---|---|---|"]
    for st in live:
        a = counts(data_dir / f"waters-{st.lower()}.json")
        b = before[st]
        lines.append(f"| {st} | {res.get(st, 'not rewritten')} | {b['records']} to {a['records']} | "
                     f"{len(a['slugs'] - b['slugs'])} | {a['tombstones']} | {a['aliases']} |")
        say(f"{st}: {res.get(st)} ({b['records']} to {a['records']} records)")
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    review = [e for e in st0.get("log") or [] if isinstance(e, dict) and str(e.get("at") or "") >= since]
    lines += ["", f"Changes for review (the last {days} days, docs/status.md lines):", ""]
    lines += [e.get("status_line", "") for e in review] or ["- none"]
    lines += ["", "A water openboatlaunch deleted or moved into another state stays in its extract (status deleted or "
              "moved) until its reports and outfalls are moved by hand; renames and merges within a state follow "
              "by slug_aliases."]
    if body:
        Path(body).parent.mkdir(parents=True, exist_ok=True)
        Path(body).write_text("\n".join(lines) + "\n")
    return res


def changed(root: Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all", "--",
                          "data/waters-*.json"], text=True, stdout=subprocess.PIPE).stdout
    files = sorted({ln[3:].strip() for ln in (out or "").splitlines()})
    return [f for f in files if re.fullmatch(r"data/waters-[a-z]{2}\.json", f)]


def publish(body: Path, date: str | None = None, dry_run: bool = False, root: Path = ROOT, gh: str = "gh") -> int:
    B = _batch()
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        print(f"::error::date must be YYYY-MM-DD, not {date!r}")
        return 2
    files = changed(root)
    if not files:
        say("no extract changed: no branch, no pull request")
        return 0
    if B.scan("RI", [body], True, root, files=files) != 0:
        print("::error::the privacy scan found something (above): nothing is committed or pushed", flush=True)
        return 1
    c = B.publish_cmds("RI", date, body, files, gh, label="obl", pr_title=f"openboatlaunch extracts, {date}")
    if dry_run:
        for cmd in c["commit"]:
            print(" ".join(B._q(a) for a in cmd))
        print(" ".join(B._q(a) for a in c["create"]))
        return 0
    for cmd in c["commit"]:
        subprocess.run(cmd, cwd=root, check=True)
    found = subprocess.run(c["find"], cwd=root, text=True, stdout=subprocess.PIPE)
    n = (found.stdout or "").strip()
    r = subprocess.run(c["edit"](n) if found.returncode == 0 and re.fullmatch(r"\d+", n) else c["create"], cwd=root)
    if r.returncode != 0:
        print(f"::error::the branch {c['branch']} is pushed but the pull request was not opened or updated", flush=True)
        return 1
    say(f"branch {c['branch']} with {', '.join(files)}; pull request opened or updated")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("--obl-dir")
    s.add_argument("--body")
    s.add_argument("--days", type=int, default=7)
    s = sub.add_parser("publish")
    s.add_argument("--body", required=True)
    s.add_argument("--date")
    s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(Path(a.obl_dir) if a.obl_dir else None, Path(a.body) if a.body else None, a.days)
        return 0
    return publish(Path(a.body), a.date, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
