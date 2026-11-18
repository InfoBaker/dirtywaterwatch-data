"""Files the private site repository hands this pipeline: the bucket dirtywaterwatch-data, under inbox/ (2026-11-18).

This repository's Cloudflare token reaches R2 objects in dirtywaterwatch-data only. What needs more (the site's D1
database, the archive of raw mail) is read by the site repository with its own token, which writes finished files
here:
  inbox/mail/<list's source id>.json   the e-mail notice lists, parsed (the site's .github/workflows/mail-feed.yml,
                                       running pipeline/mailfeed/read.py of this repository); read by
                                       ingest/operator_mail.py
  inbox/nbc-worker.json                the site Worker's 5-minute NBC sightings (worker/src/live/nbc-export.ts in the
                                       site repository); read by ingest/ri_nbc.py
The layout and the owner's switch are in the site repository's docs/mail-feed.md.

A file is fetched with `wrangler r2 object get dirtywaterwatch-data/<key> --remote --pipe` through
scripts/wrangler_redact.py, which in a workflow goes through R2's S3 endpoint (scripts/r2-s3-keys.sh) and keeps the
token's account out of the log; the bytes go to memory, never to a file. DWW_INBOX_DIR (a folder holding the same keys)
reads local copies instead: a hand run, and the tests.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

BUCKET = "dirtywaterwatch-data"
WRANGLER_REDACT = Path(__file__).resolve().parents[1] / "scripts" / "wrangler_redact.py"
KEY_RE = re.compile(r"inbox/[a-z0-9][a-z0-9._/-]{0,200}\.json")
MISSING = re.compile(r"specified key does not exist|NoSuchKey|\(404\)|not found", re.I)
ABSENT = "absent"


def get(key: str, timeout: int = 120) -> tuple[bytes | None, str | None]:
    """(bytes, None), or (None, ABSENT) when the bucket has no such key, or (None, why) when it could not be read."""
    if not KEY_RE.fullmatch(key) or ".." in key:
        raise ValueError(f"not an inbox key: {key!r}")
    local = os.environ.get("DWW_INBOX_DIR")
    if local:
        p = Path(local) / key
        return (p.read_bytes(), None) if p.is_file() else (None, ABSENT)
    try:
        p = subprocess.run([sys.executable, "-I", str(WRANGLER_REDACT), "r2", "object", "get", f"{BUCKET}/{key}",
                            "--remote", "--pipe"], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env={**os.environ, "WRANGLER_SEND_METRICS": "false"})
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"not read ({type(e).__name__})"
    if p.returncode == 0 and p.stdout:
        return p.stdout, None
    err = (p.stderr or b"").decode("utf-8", "replace")
    if MISSING.search(err):
        return None, ABSENT
    # the filter has already taken the account and any address out of wrangler's words; the last line says why
    lines = [x.strip() for x in err.splitlines() if x.strip()]
    return None, f"not read (exit {p.returncode}" + (f": {lines[-1][:200]}" if lines else "") + ")"


def get_json(key: str) -> tuple[dict | None, str | None]:
    data, why = get(key)
    if data is None:
        return None, why
    try:
        doc = json.loads(data)
    except ValueError:
        return None, "not JSON"
    return (doc, None) if isinstance(doc, dict) else (None, "not a JSON object")
