"""R2 objects through R2's S3 endpoint (2026-11-18): scripts/wrangler_redact.py's S3 route, scripts/r2-s3-keys.sh,
the mail read's S3 read, the refresh's inbox read, and the workflows' wiring. A stand-in AWS CLI keeps objects in a folder; no network."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REDACT = ROOT / "scripts" / "wrangler_redact.py"
KEYS = ROOT / "scripts" / "r2-s3-keys.sh"
ENDPOINT = "https://acct.r2.cloudflarestorage.com"

FAKE_AWS = r'''#!/usr/bin/env python3
import os, shutil, sys
from pathlib import Path
store = Path(os.environ["FAKE_S3"]); a = sys.argv[1:]
with open(store / "calls.log", "a") as fh:
    fh.write(" ".join(a) + "\n")
def opt(name):
    return a[a.index(name) + 1]
if os.environ.get("FAKE_S3_ERROR"):
    sys.stderr.write(os.environ["FAKE_S3_ERROR"] + "\n")
    sys.exit(254)
if os.environ.get("FAKE_S3_DENY"):
    sys.stderr.write("An error occurred (AccessDenied) when calling the GetObject operation: Access Denied for someone@example.com\n")
    sys.exit(254)
if "s3api" in a:
    op = a[a.index("s3api") + 1]
    obj = store / opt("--bucket") / opt("--key")
    if op == "get-object":
        if not obj.is_file():
            sys.stderr.write("An error occurred (NoSuchKey) when calling the GetObject operation: The specified key does not exist.\n")
            sys.exit(254)
        if os.environ.get("FAKE_S3_SLEEP"):
            Path(a[-1]).write_bytes(b"partial"); import time; time.sleep(float(os.environ["FAKE_S3_SLEEP"]))
        shutil.copyfile(obj, a[-1]); print('{"ContentLength": 1}'); sys.exit(0)
    if op == "put-object":
        obj.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(opt("--body"), obj); print('{"ETag": "x"}'); sys.exit(0)
    if op == "delete-object":
        obj.unlink(missing_ok=True); sys.exit(0)
if "s3" in a and "cp" in a:
    src = a[a.index("cp") + 1]
    bucket, _, key = src[len("s3://"):].partition("/")
    obj = store / bucket / key
    if not obj.is_file():
        sys.stderr.write("fatal error: An error occurred (404) when calling the HeadObject operation: Not Found\n")
        sys.exit(1)
    sys.stdout.buffer.write(obj.read_bytes()); sys.exit(0)
sys.stderr.write("fake aws: unexpected call\n"); sys.exit(9)
'''


def _exe(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def s3(tmp_path):
    store = tmp_path / "store"
    (store / "dirtywaterwatch-data" / "state").mkdir(parents=True)
    aws = _exe(tmp_path / "aws", FAKE_AWS)
    env = {**os.environ, "R2_S3_ENDPOINT": ENDPOINT, "AWS_CLI": str(aws), "FAKE_S3": str(store),
           "AWS_DEFAULT_REGION": "auto", "WRANGLER_REAL": str(tmp_path / "no-wrangler")}
    for k in ("FAKE_S3_DENY", "FAKE_S3_ERROR", "FAKE_S3_SLEEP", "R2_S3_GET_TIMEOUT"):
        env.pop(k, None)
    return store, env


def run(env, *args):
    return subprocess.run([sys.executable, "-I", str(REDACT), *args], env=env, capture_output=True, timeout=60)


def calls(store):
    p = store / "calls.log"
    return p.read_text().splitlines() if p.exists() else []


def test_get_to_a_file_and_an_absent_key(s3, tmp_path):
    store, env = s3
    (store / "dirtywaterwatch-data" / "state" / "build.tar.gz").write_bytes(b"state bytes")
    out = tmp_path / "build.tar.gz"
    p = run(env, "r2", "object", "get", "dirtywaterwatch-data/state/build.tar.gz", "--file", str(out), "--remote")
    assert p.returncode == 0 and out.read_bytes() == b"state bytes"
    assert all(ENDPOINT in c and "--region auto" in c for c in calls(store))
    absent = tmp_path / "PAUSE"
    p = run(env, "r2", "object", "get", "dirtywaterwatch-data/state/PAUSE", "--file", str(absent), "--remote")
    assert p.returncode == 1 and b"The specified key does not exist." in p.stderr and not absent.exists()


def test_state_paths_fetch_reads_the_route_as_wrangler(s3, tmp_path, monkeypatch):
    store, env = s3
    shim = _exe(tmp_path / "wrangler", f"#!/bin/sh\nexec {sys.executable} -I {REDACT} \"$@\"\n")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("state_paths_r2", ROOT / "scripts" / "state_paths.py")
    sp = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "state_paths_r2", sp)
    spec.loader.exec_module(sp)
    out = tmp_path / "pause.check"
    assert sp.fetch("state/PAUSE", out, tries=1, wrangler=str(shim)) == sp.ABSENT
    (store / "dirtywaterwatch-data" / "state" / "PAUSE").write_text("paused")
    assert sp.fetch("state/PAUSE", out, tries=1, wrangler=str(shim)) == sp.FETCHED
    assert out.read_text() == "paused"


def test_pipe_passes_the_bytes_exactly(s3):
    store, env = s3
    body = b"From: list@sender.example\r\n\r\nline two \xff\n"
    (store / "dirtywaterwatch-raw" / "email").mkdir(parents=True)
    (store / "dirtywaterwatch-raw" / "email" / "m.eml").write_bytes(body)
    p = run(env, "r2", "object", "get", "dirtywaterwatch-raw/email/m.eml", "--remote", "--pipe")
    assert p.returncode == 0 and p.stdout == body


def test_put_and_delete(s3, tmp_path):
    store, env = s3
    f = tmp_path / "out.tar.gz"
    f.write_bytes(b"export")
    p = run(env, "r2", "object", "put", "dirtywaterwatch-data/state/out.tar.gz", "--file", str(f), "--remote")
    assert p.returncode == 0 and (store / "dirtywaterwatch-data" / "state" / "out.tar.gz").read_bytes() == b"export"
    p = run(env, "r2", "object", "delete", "dirtywaterwatch-data/state/out.tar.gz", "--remote")
    assert p.returncode == 0 and not (store / "dirtywaterwatch-data" / "state" / "out.tar.gz").exists()


@pytest.mark.parametrize("args", [
    ["r2", "object", "get", "dirtywaterwatch-data/state/PAUSE", "--remote"],          # neither --file nor --pipe
    ["r2", "object", "put", "dirtywaterwatch-data/current/x.json", "--remote"],       # no --file
    ["r2", "object", "put", "dirtywaterwatch-data/x", "--file", "y", "--content-type", "text/plain"],
    ["r2", "object", "list", "dirtywaterwatch-data"],
    ["r2", "object", "get", "no-key-here", "--pipe"],
])
def test_other_r2_object_calls_are_refused_not_sent(s3, args):
    store, env = s3
    p = run(env, *args)
    assert p.returncode == 2 and b"not made through the S3 endpoint" in p.stderr and calls(store) == []


def test_a_refusal_is_reported_with_addresses_redacted(s3, tmp_path):
    store, env = s3
    env = {**env, "FAKE_S3_DENY": "1"}
    p = run(env, "r2", "object", "get", "dirtywaterwatch-data/state/PAUSE", "--file", str(tmp_path / "x"))
    assert p.returncode == 254 and b"AccessDenied" in p.stderr and b"@example.com" not in p.stderr
    assert b"does not exist" not in p.stderr


def test_without_the_endpoint_wrangler_runs_as_before(tmp_path):
    real = _exe(tmp_path / "wrangler-real", "#!/bin/sh\necho \"real wrangler: $*\"\n")
    env = {**os.environ, "WRANGLER_REAL": str(real)}
    env.pop("R2_S3_ENDPOINT", None)
    p = run(env, "r2", "object", "get", "dirtywaterwatch-data/state/PAUSE", "--file", "x", "--remote")
    assert p.returncode == 0 and b"real wrangler: r2 object get" in p.stdout


def test_d1_calls_still_go_to_wrangler_with_the_endpoint_set(s3, tmp_path):
    store, env = s3
    real = _exe(tmp_path / "wrangler-real", "#!/bin/sh\necho \"real wrangler: $*\"\n")
    p = run({**env, "WRANGLER_REAL": str(real)}, "d1", "execute", "dirtywaterwatch", "--remote", "--command", "select 1")
    assert p.returncode == 0 and b"real wrangler: d1 execute" in p.stdout and calls(store) == []


def test_the_mail_read_reads_raw_mail_through_s3(s3, monkeypatch):
    # the private mail job's reader (mailfeed/read.py since 2026-11-18; the refresh no longer reads raw mail)
    store, env = s3
    for k in ("R2_S3_ENDPOINT", "AWS_CLI", "FAKE_S3", "AWS_DEFAULT_REGION"):
        monkeypatch.setenv(k, env[k])
    from mailfeed import read as M
    (store / "dirtywaterwatch-raw" / "email" / "2026" / "11").mkdir(parents=True)
    (store / "dirtywaterwatch-raw" / "email" / "2026" / "11" / "a.eml").write_bytes(b"raw message")
    t = M.ApiTransport("token", "acct")
    assert t.raw("email/2026/11/a.eml") == b"raw message"
    with pytest.raises(RuntimeError, match=r"R2 S3 read failed \(absent\)"):
        t.raw("email/2026/11/missing.eml")
    assert all(c.split()[-2:] == ["-", "--only-show-errors"] for c in calls(store))    # to stdout, never a file


def test_the_refresh_reads_its_inbox_through_s3(s3, monkeypatch):
    # pipeline/inbox.py (operator_mail's lists, ri_nbc's Worker file): wrangler's get --pipe through the filter, which
    # takes the S3 route; the bytes to memory, an absent key told apart from a refusal
    store, env = s3
    for k in ("R2_S3_ENDPOINT", "AWS_CLI", "FAKE_S3", "AWS_DEFAULT_REGION", "WRANGLER_REAL"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.delenv("DWW_INBOX_DIR", raising=False)
    import inbox
    (store / "dirtywaterwatch-data" / "inbox" / "mail").mkdir(parents=True)
    (store / "dirtywaterwatch-data" / "inbox" / "mail" / "ma-swsc-cso-email.json").write_text('{"schema": 1}')
    assert inbox.get_json("inbox/mail/ma-swsc-cso-email.json") == ({"schema": 1}, None)
    assert inbox.get("inbox/mail/nothing.json") == (None, inbox.ABSENT)
    assert all(" s3 cp s3://dirtywaterwatch-data/inbox/mail/" in f" {c}" and c.endswith("- --only-show-errors")
               for c in calls(store))
    monkeypatch.setenv("FAKE_S3_DENY", "1")
    data, why = inbox.get("inbox/mail/ma-swsc-cso-email.json")
    assert data is None and why.startswith("not read (exit") and "@" not in why
    with pytest.raises(ValueError):
        inbox.get("state/build.tar.gz")                     # inbox/ only


def _keys_env(tmp_path, verify_json: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _exe(bin_dir / "curl", f"#!/bin/sh\ncat <<'JSON'\n{verify_json}\nJSON\n")
    aws = _exe(bin_dir / "aws", "#!/bin/sh\nexit 0\n")
    ghenv = tmp_path / "github_env"
    ghenv.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GITHUB_ENV": str(ghenv),
           "CLOUDFLARE_API_TOKEN": "tok-value", "CLOUDFLARE_ACCOUNT_ID": "acct", "AWS_CLI": str(aws)}
    return env, ghenv


def test_keys_script_writes_masked_s3_credentials(tmp_path):
    kid = "0123456789abcdef0123456789abcdef"
    env, ghenv = _keys_env(tmp_path, json.dumps({"success": True, "result": {"id": kid, "status": "active"}}))
    p = subprocess.run(["sh", str(KEYS)], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    sec = hashlib.sha256(b"tok-value").hexdigest()
    lines = ghenv.read_text().splitlines()
    assert lines == [f"AWS_ACCESS_KEY_ID={kid}", f"AWS_SECRET_ACCESS_KEY={sec}", "AWS_DEFAULT_REGION=auto",
                     "R2_S3_ENDPOINT=https://acct.r2.cloudflarestorage.com"]
    masks = [x for x in p.stdout.splitlines() if x.startswith("::add-mask::")]
    assert masks == [f"::add-mask::{kid}", f"::add-mask::{sec}"]
    assert p.stdout.index("::add-mask::") < len(p.stdout) and "tok-value" not in p.stdout


@pytest.mark.parametrize("verify", [
    json.dumps({"success": False, "errors": [{"code": 1000}], "result": None}),
    json.dumps({"success": True, "result": {"id": "0123456789abcdef0123456789abcdef", "status": "disabled"}}),
    "not json",
])
def test_keys_script_fails_when_the_token_does_not_verify(tmp_path, verify):
    env, ghenv = _keys_env(tmp_path, verify)
    p = subprocess.run(["sh", str(KEYS)], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 1 and "did not verify" in p.stdout and ghenv.read_text() == ""


def test_workflows_run_the_keys_step_after_the_guard_with_the_r2_token():
    seen = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        t = wf.read_text()
        if "scripts/wrangler-guard.sh" not in t:
            continue
        seen += 1
        lines = t.splitlines()
        g = next(i for i, x in enumerate(lines) if "sh scripts/wrangler-guard.sh" in x)
        assert "sh scripts/r2-s3-keys.sh" in lines[g + 1], wf.name
        assert re.search(r"CLOUDFLARE_API_TOKEN: \$\{\{ secrets\.CLOUDFLARE_R2_TOKEN \}\}", t), wf.name
        assert "secrets.CLOUDFLARE_API_TOKEN" not in t, wf.name
    assert seen >= 3


@pytest.mark.parametrize("error", [
    "An error occurred (InvalidAccessKeyId) when calling the GetObject operation: The AWS Access Key Id you provided does not exist in our records.",
    "An error occurred (NoSuchBucket) when calling the GetObject operation: The specified bucket does not exist",
    "An error occurred (AccessDenied) when calling the GetObject operation: Access Denied",
])
def test_a_credential_or_bucket_error_is_a_failure_never_an_absent_key(s3, tmp_path, monkeypatch, error):
    # Astra r2-s3 review P1: "does not exist" in a bad-key or missing-bucket message must not read as no pause switch
    store, env = s3
    env = {**env, "FAKE_S3_ERROR": error}
    p = run(env, "r2", "object", "get", "dirtywaterwatch-data/state/PAUSE", "--file", str(tmp_path / "p"), "--remote")
    assert p.returncode != 0 and b"The specified key does not exist." not in p.stderr
    shim = _exe(tmp_path / "wrangler", f"#!/bin/sh\nexec {sys.executable} -I {REDACT} \"$@\"\n")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("STATE_FETCH_RETRY_S", "0")
    spec = importlib.util.spec_from_file_location("state_paths_r2b", ROOT / "scripts" / "state_paths.py")
    sp = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "state_paths_r2b", sp)
    spec.loader.exec_module(sp)
    assert sp.fetch("state/PAUSE", tmp_path / "pause.check", tries=1, wrangler=str(shim)) == sp.FAILED


def test_a_pipe_read_of_a_missing_bucket_by_head_is_the_only_404(s3):
    store, env = s3
    p = run({**env, "FAKE_S3_ERROR": "fatal error: An error occurred (403) when calling the HeadObject operation: Forbidden"},
            "r2", "object", "get", "dirtywaterwatch-raw/email/x.eml", "--pipe")
    assert p.returncode != 0 and b"does not exist" not in p.stderr


def test_a_download_that_times_out_leaves_no_file(s3, tmp_path):
    # Astra r2-s3 review P2: the AWS CLI is killed at the wrapper's deadline and nothing partial stays behind
    store, env = s3
    (store / "dirtywaterwatch-data" / "state" / "build.tar.gz").write_bytes(b"full state")
    out = tmp_path / "build.tar.gz"
    p = run({**env, "FAKE_S3_SLEEP": "20", "R2_S3_GET_TIMEOUT": "1"},
            "r2", "object", "get", "dirtywaterwatch-data/state/build.tar.gz", "--file", str(out), "--remote")
    assert p.returncode == 1 and b"did not finish" in p.stderr
    assert not out.exists() and not list(tmp_path.glob("build.tar.gz.part-*"))
    p = run(env, "r2", "object", "get", "dirtywaterwatch-data/state/build.tar.gz", "--file", str(out), "--remote")
    assert p.returncode == 0 and out.read_bytes() == b"full state" and not list(tmp_path.glob("*.part-*"))


def test_keys_script_prints_no_credential_even_when_traced(tmp_path):
    # Astra r2-s3 review P2: `sh -x` while troubleshooting must not print the key id or the secret before masking
    kid = "0123456789abcdef0123456789abcdef"
    env, ghenv = _keys_env(tmp_path, json.dumps({"success": True, "result": {"id": kid, "status": "active"}}))
    p = subprocess.run(["sh", "-x", str(KEYS)], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0
    sec = hashlib.sha256(b"tok-value").hexdigest()
    assert kid not in p.stderr and sec not in p.stderr and "tok-value" not in p.stderr
