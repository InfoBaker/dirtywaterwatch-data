#!/usr/bin/env python3
"""The pipeline's log on its way to the public workflow log (stdlib only; run with python3 -I).

  sh scripts/refresh-data.sh 2>&1 | python3 -I scripts/log_redact.py

Security review 2026-11-17 #7: an exception's text can quote a full address with its query string, and a provider's
answer can name the account. The workflow steps that run pipeline code (the refresh, a backfill, a state batch, the
openboatlaunch extracts) pass their output through this filter, line by line:
  - every address keeps its scheme, host and path; its user, password, query string and fragment go
    ("https://host/a/b?token=x" -> "https://host/a/b"), and urllib3's "with url: /path?query" keeps the path;
  - a key=value whose name is a key, token, secret, password or signature, and a bearer token, become [redacted];
  - scripts/wrangler_redact.py's filter: a line naming the token's account is replaced, the R2 endpoint and the
    account id (R2_S3_ENDPOINT, CLOUDFLARE_ACCOUNT_ID) become [endpoint] and [account], an e-mail address [redacted].
Everything else passes unchanged, a line at a time and flushed, so the log keeps its order and GitHub's ::warning::
and ::error:: lines still work. A line over 1 MiB is replaced by a fixed line (read in pieces, a query string could
straddle two). The filter never stops early and always exits 0: a line it cannot read is replaced by a fixed line,
so the step's exit code is the pipeline's (the step sets pipefail). Bodies of answers are kept out
of the log by the pipeline itself (pipeline/common.py error_text).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = re.compile(rb"(?i)\b((?:https?|ftp|s3|wss?)://)([^\s'\"<>`/?#]+)([^\s'\"<>`?#]*)(?:[?#][^\s'\"<>`]*)?")
URLLIB3_PATH = re.compile(rb"(\burl: )(/[^\s'\"?#)]*)[?#][^\s'\")]*")
SECRET_PARAM = re.compile(rb"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|access_token|token|secret|password|passwd|"
                          rb"signature|sig|session(?:id)?)=)[^&\s'\";,)]+")
BEARER = re.compile(rb"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
UNREADABLE = b"[log_redact: a line was withheld]\n"
LINE_MAX = 1 << 20
TOO_LONG = b"[log_redact: a line over 1 MiB was withheld]\n"


def _wrangler_redact():
    spec = importlib.util.spec_from_file_location("wrangler_redact", HERE / "wrangler_redact.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.redact_line


try:
    _ACCOUNT_FILTER = _wrangler_redact()
except Exception:  # noqa: BLE001 - without it the line is still cut to host and path below
    _ACCOUNT_FILTER = None


def _host_path(m: re.Match) -> bytes:
    scheme, netloc, path = m.group(1), m.group(2), m.group(3)
    host = netloc.rsplit(b"@", 1)[-1]               # no user or password
    return scheme + host + path


def redact_line(line: bytes) -> bytes:
    line = URL.sub(_host_path, line)                 # first, so a user:password@ never reads as an address
    line = URLLIB3_PATH.sub(lambda m: m.group(1) + m.group(2), line)
    line = BEARER.sub(lambda m: m.group(1) + b" [redacted]", line)
    line = SECRET_PARAM.sub(lambda m: m.group(1) + b"[redacted]", line)
    return _ACCOUNT_FILTER(line) if _ACCOUNT_FILTER is not None else line


def redact(text: str) -> str:
    """The same filter for text a caller holds."""
    data = text.encode("utf-8", "surrogateescape")
    return b"".join(redact_line(x) for x in data.splitlines(keepends=True)).decode("utf-8", "surrogateescape")


def main() -> int:
    src, dst = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            line = src.readline(LINE_MAX)
            if len(line) == LINE_MAX and not line.endswith(b"\n"):
                # a line too long to read whole is withheld and drained: a piece of it read on its own could carry
                # the query string or the key of an address that began in the piece before (Astra 2026-11-21 P2-9)
                while (more := src.readline(LINE_MAX)) and not more.endswith(b"\n"):
                    pass
                line = TOO_LONG
        except Exception:  # noqa: BLE001 - nothing more can be read
            break
        if not line:
            break
        try:
            out = line if line is TOO_LONG else redact_line(line)
        except Exception:  # noqa: BLE001
            out = UNREADABLE
        try:
            dst.write(out)
            dst.flush()
        except BrokenPipeError:
            break
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
