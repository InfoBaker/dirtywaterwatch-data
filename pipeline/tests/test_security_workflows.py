"""Security review 2026-11-17, findings 8, 12 and 13, and the log filter's place in the workflows (finding 7):
- every third-party action is pinned to a full commit with its version in a comment; wrangler and the Python
  packages to exact versions;
- no job hands a secret to every step: each secret is on the steps that use it, and the actions and the installs run
  without one; each step that runs wrangler has the account id its filter needs;
- the steps that run pipeline code pass their output through scripts/log_redact.py and keep their own exit code;
- the runner probe logs each address as scheme, host and path, a failure as curl's exit code and kind, nothing of a
  body, refuses an address with a user or password, and keeps its artifact one day;
- .gitignore covers the secret and private file locations; SECURITY.md names the contact page and no address.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
needs_bash = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


def load(p: Path) -> dict:
    d = yaml.safe_load(p.read_text())
    d["on"] = d.pop(True, d.get("on"))
    return d


def steps(p: Path):
    for job in load(p)["jobs"].values():
        for st in job["steps"]:
            yield job, st


def step(p: Path, prefix: str) -> dict:
    return next(st for _, st in steps(p) if (st.get("name") or st.get("run") or "").startswith(prefix))


# ------------------------------------------------------------------ finding 12: pins

USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")


def test_every_action_is_pinned_to_a_full_commit_with_its_version_in_a_comment():
    seen = 0
    for p in WORKFLOWS:
        for line in p.read_text().splitlines():
            m = USES_LINE.match(line)
            if not m:
                continue
            seen += 1
            ref, rest = m.groups()
            assert re.fullmatch(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}", ref), f"{p.name}: {ref} is not a commit pin"
            assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), f"{p.name}: {ref} has no version comment"
    assert seen >= 10


def test_wrangler_is_installed_at_an_exact_version():
    for p in WORKFLOWS:
        for v in re.findall(r"npm install -g wrangler@(\S+)", p.read_text()):
            assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"{p.name}: wrangler@{v}"


def test_every_python_requirement_is_an_exact_pin():
    lines = [ln.split("#", 1)[0].strip() for ln in (ROOT / "pipeline" / "requirements.txt").read_text().splitlines()]
    reqs = [ln for ln in lines if ln]
    assert len(reqs) >= 6
    for r in reqs:
        assert re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.+-]*", r), r
    names = {r.split("==")[0].lower() for r in reqs}
    assert {"requests", "pyyaml", "shapely", "pytest", "pypdf", "cryptography", "urllib3", "certifi", "numpy"} <= names


# ------------------------------------------------------------------ finding 12: secrets on the steps

def secret_names(env) -> set[str]:
    return {k for k, v in (env or {}).items() if "secrets." in str(v)}


INSTALLS = re.compile(r"pip install|npm install|apt-get install|pip3 install")


def test_no_job_hands_a_secret_to_every_step_and_no_action_or_install_gets_one():
    for p in WORKFLOWS:
        for name, job in load(p)["jobs"].items():
            assert not secret_names(job.get("env")), f"{p.name} {name}: secrets in the job's env"
            for st in job["steps"]:
                if "uses" in st or INSTALLS.search(st.get("run") or ""):
                    assert not secret_names(st.get("env")), f"{p.name}: {st.get('uses') or st.get('run')[:40]}"


WRANGLER_USERS = re.compile(r"\bwrangler r2\b|state_paths\.py (?:fetch|fetch-obl|guard|generations)\b|refresh-data\.sh|r2-s3-keys\.sh")


def test_each_step_that_reaches_r2_has_the_token_and_the_account_id_its_filter_needs():
    n = 0
    for p in WORKFLOWS:
        for _, st in steps(p):
            if WRANGLER_USERS.search(st.get("run") or ""):
                n += 1
                assert {"CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"} <= set(st.get("env") or {}), \
                    f"{p.name}: {st.get('name') or st['run'][:40]}"
    assert n >= 15


def test_the_steps_that_read_the_apis_keep_their_keys():
    refresh = ROOT / ".github/workflows/refresh.yml"
    for prefix in ("Refresh (", "Backfill"):
        assert {"OPENROUTER_API_KEY", "OBL_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"} <= \
            set(step(refresh, prefix).get("env") or {}), prefix
    for p in (refresh, ROOT / ".github/workflows/state-build.yml", ROOT / ".github/workflows/obl-extracts.yml"):
        assert "OBL_API_KEY" in (step(p, "openboatlaunch's water records").get("env") or {}), p.name
    assert "OBL_API_KEY" in (step(ROOT / ".github/workflows/state-build.yml", "Run the steps").get("env") or {})


# ------------------------------------------------------------------ finding 7: the log filter in the steps

PIPELINE_STEPS = [("refresh.yml", "Refresh ("), ("refresh.yml", "Backfill"), ("state-build.yml", "Run the steps"),
                  ("obl-extracts.yml", "Rewrite the live states")]


@pytest.mark.parametrize("wf,prefix", PIPELINE_STEPS)
def test_the_steps_that_run_pipeline_code_filter_their_output_and_keep_their_exit_code(wf, prefix):
    run = step(ROOT / ".github/workflows" / wf, prefix)["run"]
    assert "set -o pipefail" in run and "2>&1" in run and "| python3 -I scripts/log_redact.py" in run


def checkout_with(tmp: Path, refresh_script: str) -> Path:
    (tmp / "scripts").mkdir(parents=True)
    for f in ("log_redact.py", "wrangler_redact.py"):
        shutil.copy(ROOT / "scripts" / f, tmp / "scripts" / f)
    (tmp / "scripts" / "refresh-data.sh").write_text(refresh_script)
    return tmp


@needs_bash
@pytest.mark.parametrize("rc", [0, 1])
def test_the_refresh_step_filters_the_log_keeps_the_exit_code_and_its_output(tmp_path, rc):
    run = step(ROOT / ".github/workflows/refresh.yml", "Refresh (")["run"]
    tmp = checkout_with(tmp_path, f"""#!/bin/sh
echo "GET https://gis.example.gov/q?where=1&token=SECRETTOKEN"
echo "an error on stderr: https://user:pw@h.example.gov/x?key=SECRETTOKEN" >&2
echo "skipped=1" >> "$GITHUB_OUTPUT"
exit {rc}
""")
    out = tmp / "github_output"
    out.write_text("")
    p = subprocess.run(["bash", "-e", "-c", run], cwd=tmp, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "GITHUB_OUTPUT": str(out)})
    assert p.returncode == rc
    assert "SECRETTOKEN" not in p.stdout and "?" not in p.stdout and "pw@" not in p.stdout
    assert "https://gis.example.gov/q" in p.stdout and "https://h.example.gov/x" in p.stdout
    assert out.read_text() == "skipped=1\n"


# ------------------------------------------------------------------ finding 8: the runner probe

PROBE = ROOT / ".github/workflows/runner-probe.yml"
CURL = r"""#!/bin/sh
# stand-in curl: -o FILE, -w FORMAT, the address last
out=""; for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; u="$a"; done
echo "$u" >> "$CURL_LOG"
case "$u" in
  *fail*) echo "curl: (6) Could not resolve host: $u with SECRETTOKEN" >&2; printf '000 0B 0.1s  -> %s' "$u"; exit 6 ;;
esac
printf 'PRIVATE BODY TEXT jane.doe@example.org\n' > "$out"
printf '200 30B 0.2s text/html -> %s&session=SECRETTOKEN' "$u"
"""


@needs_bash
def test_the_probe_logs_host_and_path_only_and_never_a_body_or_curls_words(tmp_path):
    run = step(PROBE, "One ordinary request")["run"]
    (tmp_path / "pipeline").mkdir()
    shutil.copy(ROOT / "pipeline" / "common.py", tmp_path / "pipeline" / "common.py")
    (tmp_path / "scripts").mkdir()
    for f in ("log_redact.py", "wrangler_redact.py"):
        shutil.copy(ROOT / "scripts" / f, tmp_path / "scripts" / f)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(CURL)
    (bin_dir / "curl").chmod(0o755)
    urls = ("https://gis.example.gov/a/b?where=1&token=SECRETTOKEN https://fail.example.gov/x?k=SECRETTOKEN "
            "https://user:pw@private.example.gov/y ftp://x.example.gov/z")
    event = tmp_path / "event.json"                       # the dispatch's inputs, as the runner hands them over
    event.write_text(json.dumps({"inputs": {"urls": urls, "save": False}}))
    p = subprocess.run(["bash", "-e", "-c", run], cwd=tmp_path, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_EVENT_PATH": str(event),
                            "CURL_LOG": str(tmp_path / "curl.log")})
    assert p.returncode == 0, p.stdout + p.stderr
    log = p.stdout + p.stderr
    assert "SECRETTOKEN" not in log and "?" not in log and "PRIVATE BODY" not in log and "jane" not in log
    assert "Could not resolve" not in log
    assert "1 https://gis.example.gov/a/b : 200 30B 0.2s text/html -> https://gis.example.gov/a/b" in log
    assert "2 https://fail.example.gov/x : no answer (curl exit 6, dns)" in log
    assert "3 (an address with a user or password is not requested)" in log
    assert "4 (not an http address, skipped)" in log
    assert "private.example.gov" not in (tmp_path / "curl.log").read_text()       # never requested
    assert (tmp_path / "probe" / "summary.txt").read_text().strip() == p.stdout.strip()


def test_the_probe_keeps_its_artifact_one_day_holds_no_credentials_and_says_what_save_is_for():
    d = load(PROBE)
    save = step(PROBE, "Keep the bodies")
    assert save["with"]["retention-days"] == 1
    assert d["permissions"] == {"contents": "read"}
    checkout = next(st for _, st in steps(PROBE) if "actions/checkout" in str(st.get("uses")))
    assert checkout["with"]["persist-credentials"] is False
    assert "personal data" in d["on"]["workflow_dispatch"]["inputs"]["save"]["description"]
    assert not any(secret_names(st.get("env")) for _, st in steps(PROBE))


# ------------------------------------------------------------------ finding 13 and SECURITY.md

IGNORED = [".env", ".env.local", "deploy.env", ".envrc", ".dev.vars", ".wrangler/state/x.json",
           "data/name-blocklist.json", "data/build/name-blocklist.json", "key.pem", "server.key", "id_rsa",
           "id_ed25519.pub", "session.har", "refresh.log", "refresh.log.1", ".npmrc", ".netrc", ".pypirc",
           "credentials.json", "service-account-x.json", "probe/1.body", ".claude/settings.json", "notes.bak"]


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_gitignore_covers_the_secret_and_private_file_locations_and_ignores_nothing_tracked():
    p = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--no-index", "-v", *IGNORED],
                       capture_output=True, text=True)
    ignored = {line.split("\t", 1)[1] for line in p.stdout.splitlines() if "\t" in line}
    assert ignored == set(IGNORED), sorted(set(IGNORED) - ignored)
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-ci", "--exclude-standard"],
                             capture_output=True, text=True).stdout.split()
    assert tracked == []


def test_security_md_names_the_contact_page_and_no_address():
    text = (ROOT / "SECURITY.md").read_text()
    assert "https://dirtywaterwatch.org/contact/" in text
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    for word in ("public records", "No secrets", "bucket"):
        assert word.lower() in text.lower(), word


# ------------------------------------------------------------------ Astra review 2026-11-21 (fix pass)

def test_the_probe_never_puts_the_addresses_in_a_step_env_or_the_script_text():
    # P1-1: the runner prints a step's env and its script before running it; the addresses come from the event file
    for _, st in steps(PROBE):
        assert "inputs.urls" not in str(st.get("env") or {}) and "inputs.urls" not in (st.get("run") or "")
    assert "GITHUB_EVENT_PATH" in step(PROBE, "One ordinary request")["run"]


def test_the_steps_that_need_no_storage_hold_no_storage_keys():
    # P2-10: scripts/r2-s3-keys.sh puts the S3 keys in the job's environment; the steps after it that never reach
    # R2 (the poppler install, the release, the artifacts, the publish steps, the extracts rewrite) blank them
    want = {"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": ""}
    names = [("refresh.yml", "System tools"), ("refresh.yml", "Dataset release (daily"),
             ("state-build.yml", "Keep the summary"), ("state-build.yml", "Branch and pull request"),
             ("state-build.yml", "Keep the privacy scan"), ("obl-extracts.yml", "Rewrite the live states"),
             ("obl-extracts.yml", "Branch and pull request")]
    for wf, prefix in names:
        env = step(ROOT / ".github/workflows" / wf, prefix).get("env") or {}
        assert {k: env.get(k) for k in want} == want, f"{wf}: {prefix}"


def test_the_state_batch_logs_and_their_artifacts_are_filtered_before_they_are_written(tmp_path, monkeypatch, capsys):
    # P1-5: _stream writes the steps' output to data/build/batch/out/*.log, which is uploaded as an artifact
    import importlib.util
    spec = importlib.util.spec_from_file_location("state_batch_t", ROOT / "scripts" / "state_batch.py")
    sb = importlib.util.module_from_spec(spec)
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "state_batch_t", sb)       # its dataclasses look their module up
    spec.loader.exec_module(sb)
    cmd = sb.Cmd("waters", [_sys.executable, "-c",
                            "print('GET https://gis.example.gov/q?where=1&token=SECRETTOKEN'); print('done')"])
    rc, lines = sb._stream(cmd, tmp_path, tmp_path / "waters.log")
    log = (tmp_path / "waters.log").read_text()
    out = capsys.readouterr().out
    assert rc == 0 and "done" in log
    for text in (log, out, "\n".join(lines)):
        assert "SECRETTOKEN" not in text and "https://gis.example.gov/q" in text
