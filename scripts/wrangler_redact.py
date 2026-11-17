#!/usr/bin/env python3
"""Run wrangler with who-the-token-belongs-to taken out of what it prints (stdlib only; run with python3 -I).

When Cloudflare refuses a call, wrangler prints the account the API token belongs to ("You are logged in with an
Account API Token, associated with the account <name>." and a table row "| <name>'s Account | <id> |"). GitHub masks
the secrets, but the account's name is not one, and it can be a person's e-mail address; this repository's workflow
logs are public. Every wrangler call in a workflow goes through this filter: scripts/wrangler-guard.sh puts a
`wrangler` in front of the real one on the job's PATH that runs it here (pipeline/tests/test_wrangler_redact.py
fails when a workflow installs wrangler without the guard, or a script calls it around the PATH).

  python3 -I scripts/wrangler_redact.py <wrangler arguments...>

The real wrangler is $WRANGLER_REAL, else the first `wrangler` on the PATH that is not this guard. Both streams are
filtered line by line: an e-mail-shaped string becomes "[redacted]", and a line that names the account ("associated
with the account", "'s Account", "logged in with") is replaced whole by a fixed line. Everything else (the HTTP
status, Cloudflare's error code and message, the object key) passes as it was. The exit code is wrangler's (a signal
gives 128 + its number). A file wrangler writes itself (--file) is never touched. With --json or --pipe, stdout is
the caller's data: it is held and passed byte for byte when wrangler succeeds, and filtered only when it failed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

REDACTED = b"[redacted]"
ACCOUNT_LINE = b"[wrangler: the token's account is not printed]"
EMAIL = re.compile(rb"[A-Za-z0-9._%+\-]+(?:@|%40)[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
# a line that names the account: wrangler's "associated with the account X", the whoami table's "X's Account" cell
# (straight or curly apostrophe), and the logged-in banner whatever follows it
ACCOUNT = re.compile(rb"associated with the (?:account|email)|(?:'|\xe2\x80\x99)s Account\b|logged in with",
                     re.IGNORECASE)
DATA_FLAGS = {"--json", "--pipe", "-p"}
GUARD_MARK = "wrangler-guard"   # the shim's directory name (scripts/wrangler-guard.sh); never taken as the real one


def redact_line(line: bytes) -> bytes:
    if ACCOUNT.search(line):
        end = line[len(line.rstrip(b"\r\n")):]
        return ACCOUNT_LINE + (end or b"")
    return EMAIL.sub(REDACTED, line)


def redact(data: bytes | str) -> bytes | str:
    """The same filter for text a caller already holds (bytes or str)."""
    if isinstance(data, str):
        return redact(data.encode("utf-8", "surrogateescape")).decode("utf-8", "surrogateescape")
    return b"".join(redact_line(x) for x in data.splitlines(keepends=True))


def real_wrangler() -> str | None:
    if os.environ.get("WRANGLER_REAL"):
        return os.environ["WRANGLER_REAL"]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or GUARD_MARK in d:
            continue
        found = shutil.which("wrangler", path=d)
        if found:
            return found
    return None


def _pump(src, dst) -> None:
    for line in iter(src.readline, b""):
        dst.write(redact_line(line))
        dst.flush()
    src.close()


def main(argv: list[str]) -> int:
    real = real_wrangler()
    if not real:
        sys.stderr.write("wrangler_redact: no wrangler found (set WRANGLER_REAL or put wrangler on the PATH)\n")
        return 127
    data = any(a in DATA_FLAGS for a in argv)
    out, err = sys.stdout.buffer, sys.stderr.buffer
    try:
        p = subprocess.Popen([real, *argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        sys.stderr.write(f"wrangler_redact: wrangler could not be started ({type(e).__name__})\n")
        return 127
    held = tempfile.SpooledTemporaryFile(max_size=64 << 20) if data else None
    if data:
        t_out = threading.Thread(target=lambda: (shutil.copyfileobj(p.stdout, held), p.stdout.close()))
    else:
        t_out = threading.Thread(target=_pump, args=(p.stdout, out))
    t_err = threading.Thread(target=_pump, args=(p.stderr, err))
    t_out.start(); t_err.start()
    rc = p.wait()
    t_out.join(); t_err.join()
    if held is not None:
        held.seek(0)
        if rc == 0:
            shutil.copyfileobj(held, out)
        else:
            for line in iter(held.readline, b""):
                out.write(redact_line(line))
        out.flush()
        held.close()
    return rc if rc >= 0 else 128 - rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
