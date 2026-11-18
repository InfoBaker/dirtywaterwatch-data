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

What is kept about a failure (an events file's error, meta, a state file) is a fixed category (category, category_of):
an HTTP status with Cloudflare's numeric codes, absent, denied, unreachable, timeout, an exit code. Never the words of
Cloudflare or the AWS CLI, which can carry the account id (in R2's endpoint host) or an address (Astra review
2026-11-18 P1-3).
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
    c = category(err)
    return None, f"not read ({c if c != 'unreadable' else f'exit {p.returncode}'})"


HTTP_RE = re.compile(r"\bHTTP (\d{3})\b")
CF_CODE_RE = re.compile(r"(?<![\d.])(\d{4,5}):")
EXIT_RE = re.compile(r"\bexit (-?\d{1,3})\b")


def category(text) -> str:
    """A fixed word for what a failure's text says, safe to keep anywhere: "HTTP 403, code 7403", "absent", "denied",
    "timeout", "unreachable", "exit 2", else "unreadable". Nothing of the text itself is kept."""
    t = str(text or "")
    m = HTTP_RE.search(t)
    if m:
        codes = CF_CODE_RE.findall(t[m.end():])[:2]
        return f"HTTP {m.group(1)}" + (f", code {','.join(codes)}" if codes else "")
    if MISSING.search(t):
        return ABSENT
    if re.search(r"AccessDenied|Access Denied|Forbidden|\(403\)|Unauthorized|InvalidAccessKeyId|SignatureDoesNotMatch", t):
        return "denied"
    if re.search(r"(?i)timed? ?out|Timeout", t):
        return "timeout"
    if re.search(r"(?i)could not connect|connection|refused|unreachable|name resolution|not known|EndpointConnection", t):
        return "unreachable"
    m = EXIT_RE.search(t)
    return f"exit {m.group(1)}" if m else "unreadable"


def category_of(e: BaseException) -> str:
    """category() for an exception: a response's HTTP status, the kind of a network error, else what its words say."""
    resp = getattr(e, "response", None)
    if resp is not None and isinstance(getattr(resp, "status_code", None), int):
        return f"HTTP {resp.status_code}"
    name = type(e).__name__
    if "Timeout" in name:
        return "timeout"
    if "Connection" in name:
        return "unreachable"
    if name == "JSONDecodeError":
        return "not JSON"
    c = category(str(e))
    return c if c != "unreadable" else (name if re.fullmatch(r"[A-Za-z]{1,40}", name) else c)


def get_json(key: str) -> tuple[dict | None, str | None]:
    data, why = get(key)
    if data is None:
        return None, why
    try:
        doc = json.loads(data)
    except ValueError:
        return None, "not JSON"
    return (doc, None) if isinstance(doc, dict) else (None, "not a JSON object")
