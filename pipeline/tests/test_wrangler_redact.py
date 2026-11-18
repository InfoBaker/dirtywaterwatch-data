"""wrangler's output reaches the public workflow logs only through scripts/wrangler_redact.py: no e-mail address and
no Cloudflare account name (refresh run 44068719433 printed the token's account when a put was refused), the same
exit code, the caller's --json/--pipe data and --file downloads unchanged. And no workflow or script calls wrangler
around the guard. A stand-in wrangler on the PATH plays Cloudflare; the real one is never called.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
REDACT = ROOT / "scripts" / "wrangler_redact.py"
GUARD = ROOT / "scripts" / "wrangler-guard.sh"
pytestmark = pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")

ADDRESS = "jane.doe@example.org"            # invented
PERSON = "Jane Doe"                         # invented: an account named after a person, no address in it
EMAILISH = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# wrangler's answer to a refused put, as run 44068719433 printed it (the name invented), on both streams
REFUSED = f"""#!/bin/sh
echo 'Creating object "state/out.tar.gz" in bucket "dirtywaterwatch-data".'
echo 'X [ERROR] A request to the Cloudflare API (/accounts/***/r2/buckets/dirtywaterwatch-data/objects/state/out.tar.gz) failed.' >&2
echo '  Authentication error [code: 10000]' >&2
echo "You are logged in with an Account API Token, associated with the account {ADDRESS}'s Account." >&2
echo '┌──────────────────────────────┬─────┐' >&2
echo '│ Account Name                 │ Account ID │' >&2
echo "│ {ADDRESS}'s Account │ *** │" >&2
echo "│ {PERSON}’s Account │ *** │" >&2
echo "You are logged in with an Account API Token, associated with the account {ADDRESS}'s Account."
echo "Contact {ADDRESS} or see https://developers.cloudflare.com/r2/ (status 403)"
exit ${{FAKE_RC:-1}}
"""
SUCCESS = """#!/bin/sh
echo 'Creating object "current/meta.json" in bucket "dirtywaterwatch-data".'
echo 'Upload complete.'
echo 'a warning line' >&2
"""
# --json / --pipe: stdout is the caller's data (rows can hold an address; a raw message holds anything)
DATA = f"""#!/bin/sh
printf '[{{"results":[{{"from":"{ADDRESS}","s":"Jane\\047s Account"}}]}}]\\n'
printf 'binary\\000\\377\\n'
[ -z "$FAKE_FAIL" ] || {{ echo "associated with the account {ADDRESS}'s Account" >&2; exit 1; }}
"""
# --file: wrangler writes the object itself
FILE = r"""#!/bin/sh
while [ $# -gt 0 ]; do [ "$1" = --file ] && { printf 'obj\000\377 jane.doe@example.org\n' > "$2"; }; shift; done
echo "Downloading \"state/build.tar.gz\""
"""


def fake(tmp_path: Path, script: str) -> Path:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    w = d / "wrangler"
    w.write_text(script, encoding="utf-8")
    w.chmod(0o755)
    return d


def run_redact(tmp_path: Path, script: str, *args: str, **env: str) -> subprocess.CompletedProcess:
    d = fake(tmp_path, script)
    e = {**os.environ, "PATH": f"{d}{os.pathsep}{os.environ['PATH']}", **env}
    e.pop("WRANGLER_REAL", None)
    return subprocess.run([sys.executable, "-I", str(REDACT), *args], capture_output=True, env=e, timeout=60)


def assert_clean(text: str) -> None:
    assert not EMAILISH.search(text), "an e-mail-shaped string reached the output"
    assert "'s Account" not in text and "’s Account" not in text
    assert "Jane" not in text and "jane" not in text
    assert "logged in with" not in text


def test_a_refused_call_prints_no_address_or_account_name_and_keeps_the_error_and_exit_code(tmp_path):
    p = run_redact(tmp_path, REFUSED, "r2", "object", "put", "dirtywaterwatch-data/state/out.tar.gz",
                   "--file", "out.tar.gz", "--remote")
    out, err = p.stdout.decode(), p.stderr.decode()
    assert p.returncode == 1
    assert_clean(out + err)
    # the useful part stays: which object, Cloudflare's code and message, the status
    assert "state/out.tar.gz" in err and "Authentication error [code: 10000]" in err
    assert "(status 403)" in out and "Account Name" in err
    assert err.count("[wrangler: the token's account is not printed]") == 3
    for rc in ("2", "7", "255"):
        assert run_redact(tmp_path, REFUSED, "r2", "object", "put", FAKE_RC=rc).returncode == int(rc)


def test_a_successful_call_passes_through_unchanged(tmp_path):
    p = run_redact(tmp_path, SUCCESS, "r2", "object", "put", "dirtywaterwatch-data/current/meta.json",
                   "--file", "out/meta.json", "--remote")
    assert p.returncode == 0
    assert p.stdout == b'Creating object "current/meta.json" in bucket "dirtywaterwatch-data".\nUpload complete.\n'
    assert p.stderr == b"a warning line\n"


def test_json_and_pipe_data_pass_byte_for_byte_on_success_and_are_filtered_on_failure(tmp_path):
    want = subprocess.run(["sh", "-c", DATA.split("\n", 1)[1]], capture_output=True, env={"PATH": os.environ["PATH"]}).stdout
    for flag in ("--json", "--pipe"):
        p = run_redact(tmp_path, DATA, "d1", "execute", "x", "--remote", flag)
        assert p.returncode == 0 and p.stdout == want and ADDRESS.encode() in p.stdout
    p = run_redact(tmp_path, DATA, "d1", "execute", "x", "--remote", "--json", FAKE_FAIL="1")
    assert p.returncode == 1
    assert_clean(p.stdout.decode("utf-8", "replace") + p.stderr.decode())


def test_a_file_download_is_byte_identical(tmp_path):
    out = tmp_path / "build.tar.gz"
    p = run_redact(tmp_path, FILE, "r2", "object", "get", "dirtywaterwatch-data/state/build.tar.gz",
                   "--file", str(out), "--remote")
    assert p.returncode == 0 and out.read_bytes() == b"obj\x00\xff jane.doe@example.org\n"


def test_no_wrangler_is_exit_127(tmp_path):
    e = {"PATH": str(tmp_path), "WRANGLER_REAL": ""}
    p = subprocess.run([sys.executable, "-I", str(REDACT), "whoami"], capture_output=True, env=e)
    assert p.returncode == 127


def guard(tmp_path: Path, script: str) -> dict:
    """scripts/wrangler-guard.sh as the workflow runs it; the PATH a later step gets back."""
    d = fake(tmp_path, script)
    gh_path = tmp_path / "github_path"
    gh_path.write_text("")
    base = f"{d}{os.pathsep}{os.environ['PATH']}"
    env = {**os.environ, "PATH": base, "GITHUB_PATH": str(gh_path), "RUNNER_TEMP": str(tmp_path / "runner")}
    env.pop("WRANGLER_REAL", None)
    subprocess.run(["sh", str(GUARD)], check=True, env=env, capture_output=True)
    added = gh_path.read_text().split()
    assert len(added) == 1 and added[0].endswith("wrangler-guard")
    return {**env, "PATH": f"{added[0]}{os.pathsep}{base}"}


def test_after_the_guard_a_bare_wrangler_in_a_step_is_filtered(tmp_path):
    env = guard(tmp_path, REFUSED)
    step = 'wrangler r2 object put dirtywaterwatch-data/state/out.tar.gz --file out.tar.gz --remote'
    p = subprocess.run(["bash", "-e", "-c", step], capture_output=True, text=True, env=env)
    assert p.returncode == 1
    assert_clean(p.stdout + p.stderr)
    assert "Authentication error [code: 10000]" in p.stderr
    ok = guard(tmp_path, SUCCESS)
    p = subprocess.run(["bash", "-e", "-c", "wrangler r2 object put x --file y --remote"], capture_output=True,
                       text=True, env=ok)
    assert p.returncode == 0 and "Upload complete." in p.stdout
    # run again in the same job, the guard does not wrap itself
    p = subprocess.run(["sh", str(GUARD)], capture_output=True, text=True, env=ok)
    assert p.returncode == 0 and "already in place" in p.stdout


def test_after_the_guard_the_state_fetch_warning_has_no_account_name(tmp_path):
    env = guard(tmp_path, REFUSED)
    p = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "state_paths.py"), "fetch", "state/PAUSE",
                        str(tmp_path / "pause.check")], capture_output=True, text=True,
                       env={**env, "STATE_FETCH_RETRY_S": "0"}, cwd=tmp_path)
    assert p.returncode == 1 and "could not be fetched" in p.stdout
    assert_clean(p.stdout + p.stderr)


# --- every call goes through the guard ---------------------------------------------------------------------------

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
GUARDED_INSTALL = re.compile(r"npm install -g wrangler@\S+ && sh scripts/wrangler-guard\.sh(\s|$)")
# what runs wrangler in a step: the command itself, and the scripts that call it by name from the PATH
USES_WRANGLER = re.compile(r"(^|[\s;&|(`$])wrangler\s|state_paths\.py fetch\b|upload-current\.sh|refresh-data\.sh|"
                           r"refresh-and-verify\.sh")
AROUND = re.compile(r"npx\s+(-\S+\s+)*wrangler|node_modules/\.bin/wrangler|wrangler-action|\S/wrangler(\s|$)|"
                    r"\bwrangler\.js\b")


def code(text: str) -> str:
    """Shell text without its comments (a # at the start of a line or after a space)."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def test_every_workflow_job_guards_wrangler_before_using_it():
    assert WORKFLOWS
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_name, job in (doc.get("jobs") or {}).items():
            guarded = False
            for step in job.get("steps") or []:
                assert "cloudflare/wrangler-action" not in str(step.get("uses", "")), f"{wf.name} {job_name}"
                run = code(str(step.get("run") or ""))
                if "wrangler" in run and re.search(r"npm\s+(i|install|add)\b|yarn add|pnpm add", run):
                    assert GUARDED_INSTALL.search(run), \
                        f"{wf.name} {job_name}: wrangler installed without scripts/wrangler-guard.sh in the same step"
                    guarded = True
                    continue
                assert not AROUND.search(run), f"{wf.name} {job_name}: wrangler called around the guard: {run[:120]}"
                if USES_WRANGLER.search(run):
                    assert guarded, f"{wf.name} {job_name}: wrangler used before the guarded install: {run[:120]}"


def test_no_script_calls_wrangler_around_the_guard():
    files = [*sorted((ROOT / "scripts").glob("*.sh")), *([ROOT / "Makefile"] if (ROOT / "Makefile").exists() else [])]
    for f in files:
        assert not AROUND.search(code(f.read_text(encoding="utf-8"))), f"{f.name}: wrangler called around the guard"
    # Python: a module that starts wrangler as a subprocess goes through scripts/wrangler_redact.py, except
    # state_paths.py, which runs only in the workflows and calls the bare name (the guard on the PATH)
    pys = [p for d in ("scripts", "pipeline") for p in (ROOT / d).rglob("*.py")
           if ".venv" not in p.parts and "tests" not in p.parts and p.name != "wrangler_redact.py"]
    callers = []
    for p in pys:
        t = p.read_text(encoding="utf-8", errors="replace")
        if "subprocess" in t and re.search(r"wrangler", t, re.IGNORECASE) and \
                re.search(r"WRANGLER\b|\"wrangler\"|'wrangler'|/wrangler", t):
            callers.append(p.name)
            if p.name == "state_paths.py":
                assert 'or "wrangler", "r2"' in t, \
                    "state_paths.py must call wrangler by its bare name, so the guard on the PATH filters it"
            else:
                assert "wrangler_redact" in t, f"{p.relative_to(ROOT)} starts wrangler without scripts/wrangler_redact.py"
    # the refresh's inbox reader (pipeline/inbox.py: ri_nbc and operator_mail since 2026-11-18) and the private mail
    # job's hand path (mailfeed/read.py)
    assert {"state_paths.py", "inbox.py", "read.py"} <= set(callers)
