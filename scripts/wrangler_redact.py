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


# R2 objects through R2's S3 endpoint (2026-11-18). The token is limited to the pipeline's two buckets, and
# Cloudflare's REST API (which wrangler uses) refuses object calls from such a token; R2's S3 endpoint accepts them.
# When R2_S3_ENDPOINT is set (scripts/r2-s3-keys.sh, with AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY), the calls
# `r2 object get BUCKET/KEY (--file F | --pipe)`, `r2 object put BUCKET/KEY --file F` and `r2 object delete BUCKET/KEY`
# (with or without --remote) are made with the AWS CLI against that endpoint, keeping wrangler's contract: exit 0 on
# success; a get of an absent key prints wrangler's "The specified key does not exist." and exits 1; --pipe writes the
# object's bytes to stdout and nothing else. Any other r2 object call is refused (exit 2) rather than sent where it
# would be refused anyway; every other wrangler call (d1, ...) runs wrangler as before.
S3_OPS = ("get", "put", "delete")
S3_MISSING = re.compile(rb"\(404\)|NoSuchKey|Not Found|does not exist", re.I)
UNSUPPORTED = "unsupported"


def s3_args(argv: list[str]):
    """(op, bucket, key, file, pipe) for an r2 object call the S3 route makes, UNSUPPORTED, or None (not ours)."""
    if len(argv) < 3 or argv[0] != "r2" or argv[1] != "object":
        return None
    if argv[2] not in S3_OPS or len(argv) < 4:
        return UNSUPPORTED
    op, (bucket, sep, key) = argv[2], argv[3].partition("/")
    if not (sep and bucket and key):
        return UNSUPPORTED
    file, pipe, rest, i = None, False, argv[4:], 0
    while i < len(rest):
        a = rest[i]
        if a in ("--file", "-f") and i + 1 < len(rest):
            file, i = rest[i + 1], i + 2
            continue
        if a.startswith("--file="):
            file = a.split("=", 1)[1]
        elif a in ("--pipe", "-p"):
            pipe = True
        elif a != "--remote":
            return UNSUPPORTED
        i += 1
    if (op == "put" and not file) or (op == "get" and bool(file) == pipe) or (op == "delete" and (file or pipe)):
        return UNSUPPORTED
    return op, bucket, key, file, pipe


def s3_main(op: str, bucket: str, key: str, file: str | None, pipe: bool) -> int:
    aws = os.environ.get("AWS_CLI") or shutil.which("aws")
    if not aws:
        sys.stderr.write("wrangler_redact: R2_S3_ENDPOINT is set but the AWS CLI is not installed\n")
        return 127
    base = [aws, "--endpoint-url", os.environ["R2_S3_ENDPOINT"], "--region", os.environ.get("AWS_DEFAULT_REGION") or "auto"]
    if op == "get" and pipe:
        cmd = base + ["s3", "cp", f"s3://{bucket}/{key}", "-", "--only-show-errors"]
    elif op == "get":
        cmd = base + ["s3api", "get-object", "--bucket", bucket, "--key", key, file]
    elif op == "put":
        cmd = base + ["s3api", "put-object", "--bucket", bucket, "--key", key, "--body", file]
    else:
        cmd = base + ["s3api", "delete-object", "--bucket", bucket, "--key", key]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"wrangler_redact: the AWS CLI could not run ({type(e).__name__})\n")
        return 1
    if p.returncode == 0:
        if pipe:
            sys.stdout.buffer.write(p.stdout)
            sys.stdout.buffer.flush()
        else:
            sys.stdout.write(f"r2 object {op} {bucket}/{key}: done (S3 endpoint)\n")
        return 0
    if op == "get" and file:
        try:
            os.unlink(file)
        except OSError:
            pass
    if op == "get" and S3_MISSING.search(p.stderr):
        sys.stderr.write("The specified key does not exist.\n")
        return 1
    for line in p.stderr.splitlines(keepends=True)[-5:]:
        sys.stderr.buffer.write(redact_line(line))
    sys.stderr.buffer.flush()
    return p.returncode if p.returncode > 0 else 1


def main(argv: list[str]) -> int:
    if os.environ.get("R2_S3_ENDPOINT"):
        route = s3_args(argv)
        if route == UNSUPPORTED:
            sys.stderr.write(f"wrangler_redact: this r2 object call is not made through the S3 endpoint: {' '.join(argv[:3])}\n")
            return 2
        if route:
            return s3_main(*route)
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
