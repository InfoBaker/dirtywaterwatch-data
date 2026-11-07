"""The two workflows' state steps run as GitHub runs them (bash -e, one script per step, the `if:` conditions with
the implicit success(), continue-on-error, step outputs), against a stand-in wrangler that keeps objects in a folder.
The refresh itself, the installs and the release are stand-ins; the restore and save steps are the workflow's own.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("bash") or not shutil.which("tar"), reason="needs bash and tar")

WRANGLER = r"""#!/bin/sh
# stand-in: wrangler r2 object get|put BUCKET/KEY --file F --remote, objects kept under $FAKE_R2
op="$3"; key="${4#*/}"; file="$6"
case "$op" in
  get)
    echo "Downloading \"$key\""
    case " $FAKE_R2_FAIL_GET " in *" $key "*) : > "$file"; echo "X [ERROR] A request to the Cloudflare API failed (500)"; exit 1 ;; esac
    [ -f "$FAKE_R2/$key" ] || { : > "$file"; echo "X [ERROR] The specified key does not exist."; exit 1; }
    cp "$FAKE_R2/$key" "$file" ;;
  put)
    case " $FAKE_R2_FAIL_PUT " in *" $key "*) echo "X [ERROR] upload failed"; exit 1 ;; esac
    mkdir -p "$(dirname "$FAKE_R2/$key")"; cp "$file" "$FAKE_R2/$key"; echo "put $key" >> "$FAKE_R2/.puts" ;;
esac
"""

# stand-ins for the steps that are not about the state (by name prefix, or the run text for unnamed steps)
REFRESH_STANDIN = """
[ -z "$REFRESH_SKIPS" ] || { echo skipped=1 >> "$GITHUB_OUTPUT"; exit 0; }
mkdir -p data/build data/raw/nhd-waters/nldi data/raw/va-deq-prep out
echo '{"run": 1}' > data/build/history-new.json
echo '{"response": "new answer"}' > data/raw/nhd-waters/nldi/new.json
echo '{}' > data/raw/va-deq-prep/bulk.json
[ -z "$REFRESH_FAILS" ] || exit 1
"""
BATCH_STANDIN = """
mkdir -p data/raw/nhd-waters/nldi data/build/batch/out
echo '{"response": "batch answer"}' > data/raw/nhd-waters/nldi/batch.json
[ -z "$BATCH_FAILS" ] || exit 1
"""
STANDINS = {
    "Refresh (": REFRESH_STANDIN,
    "Dataset release (": 'echo "release weekly=$WEEKLY" > release.done',
    "Check the inputs": '[ -z "$BAD_INPUT" ] || exit 2; echo "BATCH_DATE=2026-11-04" >> "$GITHUB_ENV"',
    "Run the steps": BATCH_STANDIN,
    "Branch and pull request": "echo publish > publish.done",
    "python -m venv": "true",
    "npm install": "true",
    "Backfill": "true",
    "System tools": "true",
}


def load(name: str) -> dict:
    d = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    d["on"] = d.pop(True, d.get("on"))
    return d


def condition(expr, results: dict, outputs: dict, event: str, failed: bool) -> bool:
    """A step's `if:` as GitHub reads the expressions these workflows use (success() is implied when no status
    function is named)."""
    if expr is None:
        expr = "success()"
    e = str(expr).strip()
    if e.startswith("${{"):
        e = e[3:].rstrip("}").strip()
    if not re.search(r"\b(success|failure|always|cancelled)\(\)", e):
        e = f"success() && ({e})"
    e = re.sub(r"steps\.(\w+)\.outputs\.(\w+)", lambda m: repr(outputs.get(m.group(1), {}).get(m.group(2), "")), e)
    e = re.sub(r"steps\.(\w+)\.outcome", lambda m: repr(results.get(m.group(1), "skipped")), e)
    e = e.replace("github.event_name", repr(event)).replace("github.event.inputs.backfill", "''")
    e = re.sub(r"\(github\.event\.schedule && startsWith\([^)]*\)\)", "False", e)   # the 03Z daily release (old form)
    e = (e.replace("success()", str(not failed)).replace("!cancelled()", "True").replace("cancelled()", "False")
         .replace("always()", "True").replace("&&", " and ").replace("||", " or ").replace("!=", " != "))
    return bool(eval(e, {}, {}))          # the expressions are the repository's own workflow text


# a stand-in clock for the release decision: date -u +%H and +%u answer FAKE_HOUR and FAKE_DOW; anything else is date
DATE = r"""#!/bin/sh
case "$*" in
  *+%H*) echo "${FAKE_HOUR:-12}" ;;
  *+%u*) echo "${FAKE_DOW:-3}" ;;
  *) exec REAL_DATE "$@" ;;
esac
""".replace("REAL_DATE", shutil.which("date") or "/bin/date")


def expand(value: str, outputs: dict, event: str) -> str | None:
    """A step env value as GitHub fills it: github.event_name and steps.<id>.outputs.<name>; None for any other
    expression (a secret: not set here)."""
    v = str(value)
    if "${{" not in v:
        return v
    v = v.replace("${{ github.event_name }}", event)
    v = re.sub(r"\$\{\{ steps\.(\w+)\.outputs\.(\w+) \}\}",
               lambda m: outputs.get(m.group(1), {}).get(m.group(2), ""), v)
    return None if "${{" in v else v


def simulate(workflow: str, tmp: Path, env: dict | None = None, event: str = "schedule",
             tools: dict | None = None) -> dict:
    """Run the job's steps in order in a checkout at tmp; returns {step label: outcome}, the outputs and the log.
    tools: extra stand-in commands {name: script} put first on the path."""
    job = next(iter(load(workflow)["jobs"].values()))
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in {"wrangler": WRANGLER, "date": DATE, **(tools or {})}.items():
        w = bin_dir / name
        w.write_text(text)
        w.chmod(w.stat().st_mode | stat.S_IEXEC)
    base = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_R2": str(tmp / "r2"),
            "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a", "STATE_FETCH_RETRY_S": "0",
            **(env or {})}
    github_env = tmp / "github_env"
    github_env.write_text("")
    results, outputs, ran, log = {}, {}, [], []
    any_failed = False
    for i, step in enumerate(job["steps"]):
        label = step.get("id") or step.get("name") or step.get("run", step.get("uses", ""))[:30]
        if "uses" in step:
            results[label] = "success"
            continue
        if not condition(step.get("if"), results, outputs, event, any_failed):
            results[label] = "skipped"
            continue
        name = step.get("name") or step["run"]
        script = next((v for k, v in STANDINS.items() if name.startswith(k)), step["run"])
        out_file = tmp / f"out-{i}"
        out_file.write_text("")
        senv = {**base, **{k: str(v) for k, v in (job.get("env") or {}).items() if "${{" not in str(v)},
                **{k: x for k, v in (step.get("env") or {}).items() if (x := expand(v, outputs, event)) is not None},
                "GITHUB_OUTPUT": str(out_file), "GITHUB_ENV": str(github_env)}
        for line in github_env.read_text().splitlines():
            k, _, v = line.partition("=")
            senv[k] = v
        p = subprocess.run(["bash", "-e", "-c", script], cwd=tmp, env=senv, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        log.append(f"--- {name}\n{p.stdout}")
        outputs[label] = dict(x.split("=", 1) for x in out_file.read_text().splitlines() if "=" in x)
        ok = p.returncode == 0
        results[label] = "success" if ok else "failure"
        ran.append(label)
        if not ok and not step.get("continue-on-error"):
            any_failed = True
    return {"results": results, "ran": ran, "log": "\n".join(log), "failed": any_failed, "outputs": outputs}


def checkout(tmp: Path) -> Path:
    (tmp / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "state_paths.py", tmp / "scripts" / "state_paths.py")
    (tmp / "r2" / "state").mkdir(parents=True)
    return tmp


def seed(tmp: Path) -> None:
    """Stored objects as a good earlier run left them."""
    src = tmp / "seed"
    (src / "data/build").mkdir(parents=True)
    (src / "data/build/history-old.json").write_text('{"kept": true}')
    (src / "data/build/name-blocklist.json").write_text('["Placeholder Name"]')
    with tarfile.open(tmp / "r2/state/build.tar.gz", "w:gz") as tf:
        tf.add(src / "data", arcname="data")
    (src / "data/raw/nhd-waters/nldi").mkdir(parents=True)
    (src / "data/raw/nhd-waters/nldi/old.json").write_text('{"response": "old answer"}')
    with tarfile.open(tmp / "r2/state/raw-cache.tar.gz", "w:gz") as tf:
        tf.add(src / "data/raw/nhd-waters", arcname="data/raw/nhd-waters")
    shutil.rmtree(src)


def members(tmp: Path, key: str) -> list[str]:
    with tarfile.open(tmp / "r2" / key) as tf:
        return sorted(m.name for m in tf.getmembers() if m.isfile())


def puts(tmp: Path) -> list[str]:
    p = tmp / "r2" / ".puts"
    return p.read_text().split("\n")[:-1] if p.exists() else []


# ---------------------------------------------------------------- refresh.yml

def test_refresh_installs_pdftotext_before_the_refresh_and_a_failed_install_never_stops_the_run(tmp_path):
    """ingest/il_mwrd_lake_reversals.py needs poppler's pdftotext, which the hosted runner may not have."""
    steps = next(iter(load("refresh.yml")["jobs"].values()))["steps"]
    names = [s.get("name") or s.get("run", "") for s in steps]
    i = next(i for i, n in enumerate(names) if n.startswith("System tools"))
    assert i < next(i for i, n in enumerate(names) if n.startswith("Refresh ("))
    script = steps[i]["run"]
    assert "poppler-utils" in script and "|| echo \"::warning::" in script
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("sudo",):                      # an install that fails: the step still succeeds
        (bin_dir / tool).write_text("#!/bin/sh\nexit 100\n")
        (bin_dir / tool).chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir)}         # no pdftotext on the path; the shell's builtins only
    p = subprocess.run([shutil.which("bash"), "-e", "-c", script], env=env, text=True, capture_output=True)
    assert p.returncode == 0 and "::warning::poppler-utils could not be installed" in p.stdout


def test_refresh_first_run_with_no_state_objects(tmp_path):
    tmp = checkout(tmp_path)
    r = simulate("refresh.yml", tmp)
    assert not r["failed"], r["log"]
    assert "no state yet" in r["log"] and "no raw cache yet" in r["log"]
    assert puts(tmp) == ["put state/out.tar.gz", "put state/build.tar.gz", "put state/raw-cache.tar.gz"]
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/new.json"]     # no bulk raw


def test_refresh_normal_run_restores_both_and_saves_both(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, event="workflow_dispatch")
    assert not r["failed"], r["log"]
    assert (tmp / "data/build/history-old.json").exists() and (tmp / "data/raw/nhd-waters/nldi/old.json").exists()
    assert "data/build/history-old.json" in members(tmp, "state/build.tar.gz")
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/new.json",
                                                       "data/raw/nhd-waters/nldi/old.json"]
    assert (tmp / "release.done").exists()


def test_refresh_raw_save_failure_does_not_fail_the_run(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"FAKE_R2_FAIL_PUT": "state/raw-cache.tar.gz"}, event="workflow_dispatch")
    assert not r["failed"], r["log"]
    assert puts(tmp) == ["put state/out.tar.gz", "put state/build.tar.gz"]
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/old.json"]    # the stored one stands
    assert (tmp / "release.done").exists()                                                    # the release still runs


def test_refresh_raw_cache_not_fetched_runs_on_and_keeps_the_stored_one(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"FAKE_R2_FAIL_GET": "state/raw-cache.tar.gz"})
    assert not r["failed"], r["log"]
    assert "keeps the stored one" in r["log"]
    assert puts(tmp) == ["put state/out.tar.gz", "put state/build.tar.gz"]                       # not saved over with this run's answers only
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/old.json"]


def test_refresh_corrupt_raw_cache_runs_on_and_is_replaced(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    good = (tmp / "r2/state/raw-cache.tar.gz").read_bytes()
    (tmp / "r2/state/raw-cache.tar.gz").write_bytes(good[: len(good) // 2])
    r = simulate("refresh.yml", tmp)
    assert not r["failed"], r["log"]
    assert "raw cache could not be read" in r["log"]
    assert not (tmp / "data/raw/nhd-waters/nldi/old.json").exists()
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/new.json"]


@pytest.mark.parametrize("how", ["fetch", "corrupt"])
def test_refresh_build_state_unreadable_stops_before_publishing_and_saves_nothing(tmp_path, how):
    tmp = checkout(tmp_path)
    seed(tmp)
    before = {k: (tmp / "r2/state" / k).read_bytes() for k in ("build.tar.gz", "raw-cache.tar.gz")}
    env = {}
    if how == "fetch":
        env["FAKE_R2_FAIL_GET"] = "state/build.tar.gz"
    else:
        (tmp / "r2/state/build.tar.gz").write_bytes(before["build.tar.gz"][:40])
        before["build.tar.gz"] = (tmp / "r2/state/build.tar.gz").read_bytes()
    r = simulate("refresh.yml", tmp, env)
    assert r["failed"]
    assert "refresh" not in r["ran"] and not (tmp / "release.done").exists()
    assert puts(tmp) == []
    assert {k: (tmp / "r2/state" / k).read_bytes() for k in before} == before


def test_refresh_failed_run_saves_nothing(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"REFRESH_FAILS": "1"})
    assert r["failed"] and puts(tmp) == []


def test_refresh_build_state_over_the_cap_is_still_saved(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"STATE_MAX_MB": "0.000001"})
    assert not r["failed"], r["log"]
    assert "::warning::build.tar.gz is" in r["log"]
    assert "put state/build.tar.gz" in puts(tmp)
    assert "put state/raw-cache.tar.gz" not in puts(tmp)           # the raw cache keeps its cap (and the run goes on)


# ---------------------------------------------------------------- state-build.yml

def test_batch_saves_the_raw_caches_after_a_failed_step_but_never_the_build_state(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("state-build.yml", tmp, {"BATCH_FAILS": "1"}, event="workflow_dispatch")
    assert r["failed"]
    assert puts(tmp) == ["put state/raw-cache.tar.gz"]
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/batch.json",
                                                       "data/raw/nhd-waters/nldi/old.json"]
    assert not (tmp / "publish.done").exists()


def test_batch_with_bad_inputs_never_saves_an_empty_raw_cache(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("state-build.yml", tmp, {"BAD_INPUT": "1"}, event="workflow_dispatch")
    assert r["failed"] and puts(tmp) == []
    assert members(tmp, "state/raw-cache.tar.gz") == ["data/raw/nhd-waters/nldi/old.json"]


def test_batch_build_state_not_fetched_stops_and_saves_nothing(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("state-build.yml", tmp, {"FAKE_R2_FAIL_GET": "state/build.tar.gz"}, event="workflow_dispatch")
    assert r["failed"] and puts(tmp) == []
    assert not any(n.startswith("Run the steps") for n in r["ran"])


def test_batch_raw_cache_not_fetched_is_kept(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("state-build.yml", tmp, {"FAKE_R2_FAIL_GET": "state/raw-cache.tar.gz"}, event="workflow_dispatch")
    assert not r["failed"], r["log"]
    assert puts(tmp) == [] and (tmp / "publish.done").exists()


# ---------------------------------------------------------------- openboatlaunch's object (state/obl-water.tar.gz)

def seed_obl(tmp: Path, corrupt: bool = False) -> None:
    """The object as the upload packs it: tar -czf obl-water.tar.gz -C <openboatlaunch>/out water meta.json."""
    src = tmp / "obl-src"
    (src / "water").mkdir(parents=True)
    for slug in ("haw-river-nc", "lake-wheeler-nc", "lake-lanier-ga"):
        (src / "water" / f"{slug}.json").write_text('{"slug": "%s", "geometry": null}' % slug)
    (src / "meta.json").write_text('{"built": "2026-11-01"}')
    obj = tmp / "r2/state/obl-water.tar.gz"
    with tarfile.open(obj, "w:gz") as tf:
        tf.add(src / "water", arcname="water")
        tf.add(src / "meta.json", arcname="meta.json")
    if corrupt:
        obj.write_bytes(obj.read_bytes()[:60])
    shutil.rmtree(src)


def restored(tmp_path: Path) -> list[str]:
    out = tmp_path / "openboatlaunch" / "out"
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) if out.is_dir() else []


OBL_FILES = ["meta.json", "water/haw-river-nc.json", "water/lake-lanier-ga.json", "water/lake-wheeler-nc.json"]


@pytest.mark.parametrize("workflow,event", [("refresh.yml", "schedule"), ("state-build.yml", "workflow_dispatch")])
def test_obl_object_restored_beside_the_checkout_and_never_saved(tmp_path, workflow, event):
    tmp = checkout(tmp_path / "ws")                     # its sibling ../openboatlaunch is tmp_path/openboatlaunch
    seed(tmp)
    seed_obl(tmp)
    before = (tmp / "r2/state/obl-water.tar.gz").read_bytes()
    r = simulate(workflow, tmp, event=event)
    assert not r["failed"], r["log"]
    assert restored(tmp_path) == OBL_FILES
    assert "put state/obl-water.tar.gz" not in puts(tmp)
    assert (tmp / "r2/state/obl-water.tar.gz").read_bytes() == before
    assert not (tmp / "obl-water.tar.gz").exists()


@pytest.mark.parametrize("workflow,event", [("refresh.yml", "schedule"), ("state-build.yml", "workflow_dispatch")])
def test_obl_object_missing_is_a_warning(tmp_path, workflow, event):
    tmp = checkout(tmp_path / "ws")
    seed(tmp)
    r = simulate(workflow, tmp, event=event)
    assert not r["failed"], r["log"]
    assert "::warning::state/obl-water.tar.gz is not in R2 yet" in r["log"]
    assert restored(tmp_path) == []


@pytest.mark.parametrize("how", ["corrupt", "fetch"])
def test_obl_object_unreadable_warns_in_the_refresh(tmp_path, how):
    tmp = checkout(tmp_path / "ws")
    seed(tmp)
    seed_obl(tmp, corrupt=how == "corrupt")
    env = {"FAKE_R2_FAIL_GET": "state/obl-water.tar.gz"} if how == "fetch" else {}
    r = simulate("refresh.yml", tmp, env)
    assert not r["failed"], r["log"]
    assert "goes on without openboatlaunch's outlines" in r["log"]
    assert puts(tmp) == ["put state/out.tar.gz", "put state/build.tar.gz", "put state/raw-cache.tar.gz"]
    assert restored(tmp_path) == []


@pytest.mark.parametrize("how", ["corrupt", "fetch"])
def test_obl_object_unreadable_stops_the_batch_before_it_saves_anything(tmp_path, how):
    tmp = checkout(tmp_path / "ws")
    seed(tmp)
    seed_obl(tmp, corrupt=how == "corrupt")
    env = {"FAKE_R2_FAIL_GET": "state/obl-water.tar.gz"} if how == "fetch" else {}
    raw = (tmp / "r2/state/raw-cache.tar.gz").read_bytes()
    r = simulate("state-build.yml", tmp, env, event="workflow_dispatch")
    assert r["failed"]
    assert "::error::state/obl-water.tar.gz is in R2 but could not be" in r["log"]
    assert not any(n.startswith("Run the steps") or n == "batch" for n in r["ran"])
    assert puts(tmp) == [] and (tmp / "r2/state/raw-cache.tar.gz").read_bytes() == raw
    assert not (tmp / "publish.done").exists() and restored(tmp_path) == []


# ---------------------------------------------------------------- SOL wave1 P2-9: the shared R2 pause switch

def test_refresh_r2_pause_collects_publishes_and_saves_nothing(tmp_path):
    """A standalone state/PAUSE object (the saved build archive holds no PAUSE file) stops the run before any
    restore, backfill, ingest, upload or state save; the run itself succeeds."""
    tmp = checkout(tmp_path)
    seed(tmp)
    (tmp / "r2/state/PAUSE").write_text("paused for maintenance\n")
    before = {k: (tmp / "r2/state" / k).read_bytes() for k in ("build.tar.gz", "raw-cache.tar.gz")}
    r = simulate("refresh.yml", tmp, event="workflow_dispatch")
    assert not r["failed"], r["log"]
    assert "R2 state/PAUSE is set" in r["log"]
    assert r["ran"][:2] == ["release", "Secrets present"] and r["ran"][-1] == "pause"     # nothing after the switch
    assert puts(tmp) == [] and not (tmp / "release.done").exists() and not (tmp / "data").exists()
    assert {k: (tmp / "r2/state" / k).read_bytes() for k in before} == before


def test_refresh_r2_pause_that_cannot_be_checked_stops_the_run(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"FAKE_R2_FAIL_GET": "state/PAUSE"})
    assert r["failed"] and "R2 state/PAUSE could not be checked" in r["log"]
    assert "refresh" not in r["ran"] and puts(tmp) == []


def test_refresh_that_stopped_at_once_publishes_and_saves_nothing(tmp_path):
    """refresh-data.sh stopped by data/build/PAUSE or another run's lock says skipped=1: no export, no state save,
    no release."""
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"REFRESH_SKIPS": "1"}, event="workflow_dispatch")
    assert not r["failed"], r["log"]
    assert "refresh" in r["ran"] and puts(tmp) == [] and not (tmp / "release.done").exists()


@pytest.mark.parametrize("why", ["pause", "lock"])
def test_refresh_data_sh_says_skipped_when_it_stops_at_once(tmp_path, why):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "refresh-data.sh", tmp_path / "scripts" / "refresh-data.sh")
    (tmp_path / "data/build").mkdir(parents=True)
    if why == "pause":
        (tmp_path / "data/build/PAUSE").write_text("")
    else:
        (tmp_path / "data/build/refresh.lockdir").mkdir()
    out = tmp_path / "gh-output"
    out.write_text("")
    p = subprocess.run(["sh", str(tmp_path / "scripts" / "refresh-data.sh")], env={**os.environ, "GITHUB_OUTPUT": str(out)},
                       text=True, capture_output=True)
    assert p.returncode == 0 and ("paused" if why == "pause" else "locked") in p.stdout
    assert out.read_text() == "skipped=1\n"


# ---------------------------------------------------------------- SOL wave1 P2-12: the export archive

FAILING_TAR = r"""#!/bin/sh
# stand-in: creating out.tar.gz writes the file and then fails; anything else is the real tar
case "$*" in *"-czf out.tar.gz"*) echo partial > out.tar.gz; echo "tar: out/x: file changed as we read it"; exit 2 ;; esac
exec REAL_TAR "$@"
""".replace("REAL_TAR", shutil.which("tar") or "/usr/bin/tar")


def test_refresh_failed_export_archive_fails_the_step_and_saves_nothing(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    before = {k: (tmp / "r2/state" / k).read_bytes() for k in ("build.tar.gz", "raw-cache.tar.gz")}
    r = simulate("refresh.yml", tmp, event="workflow_dispatch", tools={"tar": FAILING_TAR})
    assert r["failed"]
    assert next(v for k, v in r["results"].items() if k.startswith("Full export")) == "failure"
    assert puts(tmp) == [] and not (tmp / "release.done").exists()
    assert {k: (tmp / "r2/state" / k).read_bytes() for k in before} == before


def test_refresh_failed_export_upload_fails_the_step_and_saves_nothing(tmp_path):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"FAKE_R2_FAIL_PUT": "state/out.tar.gz"})
    assert r["failed"] and puts(tmp) == []


# ---------------------------------------------------------------- SOL wave1 P2-13: the dataset release decision

@pytest.mark.parametrize("event,hour,dow,due,weekly", [
    ("schedule", "03", "3", "1", "0"),          # the daily release
    ("schedule", "04", "3", "0", "0"),          # any other hour: none
    ("schedule", "02", "7", "0", "0"),
    ("schedule", "03", "7", "1", "1"),          # Sunday 03Z: the dated one too
    ("workflow_dispatch", "11", "7", "1", "1"),
    ("workflow_dispatch", "11", "2", "1", "0"),
])
def test_refresh_release_decision_from_the_run_start_time(tmp_path, event, hour, dow, due, weekly):
    tmp = checkout(tmp_path)
    seed(tmp)
    r = simulate("refresh.yml", tmp, {"FAKE_HOUR": hour, "FAKE_DOW": dow}, event=event)
    assert not r["failed"], r["log"]
    assert r["outputs"]["release"] == {"due": due, "weekly": weekly}
    if due == "1":
        assert (tmp / "release.done").read_text().strip() == f"release weekly={weekly}"
    else:
        assert not (tmp / "release.done").exists()


def test_refresh_release_never_reads_a_context_github_does_not_have():
    steps = next(iter(load("refresh.yml")["jobs"].values()))["steps"]
    assert not any("run_started_at" in str(st.get("if") or "") + str(st.get("env") or "") for st in steps)


# ---------------------------------------------------------------- SOL wave1 P2-14: build state archive members

def hostile_build(tmp: Path, kind: str) -> None:
    """state/build.tar.gz with a good data/build member and one that may not be restored."""
    import io
    with tarfile.open(tmp / "r2/state/build.tar.gz", "w:gz") as tf:
        def add(name, body=b"x", **kw):
            ti = tarfile.TarInfo(name)
            for k, v in kw.items():
                setattr(ti, k, v)
            if ti.isfile():
                ti.size = len(body)
                tf.addfile(ti, io.BytesIO(body))
            else:
                tf.addfile(ti)
        add("data/build/history-old.json", b'{"kept": true}')
        if kind == "code":
            add("scripts/state_paths.py", b"print('replaced')\n")
        elif kind == "traversal":
            add("data/build/../../scripts/state_paths.py", b"print('replaced')\n")
        elif kind == "absolute":
            add(str(tmp / "scripts" / "state_paths.py"), b"print('replaced')\n")
        elif kind == "symlink-pivot":
            add("data/build/pivot", type=tarfile.SYMTYPE, linkname="../../scripts")
            add("data/build/pivot/state_paths.py", b"print('replaced')\n")
        elif kind == "hardlink":
            add("data/build/hard", type=tarfile.LNKTYPE, linkname="scripts/state_paths.py")
        elif kind == "fifo":
            add("data/build/pipe", type=tarfile.FIFOTYPE)
        elif kind == "data-file":
            add("data/rules.json", b"{}")


HOSTILE = ["code", "traversal", "absolute", "symlink-pivot", "hardlink", "fifo", "data-file"]


@pytest.mark.parametrize("kind", HOSTILE)
@pytest.mark.parametrize("workflow,event", [("refresh.yml", "schedule"), ("state-build.yml", "workflow_dispatch")])
def test_build_state_with_members_outside_data_build_is_refused_before_the_checkout_changes(tmp_path, workflow,
                                                                                          event, kind):
    tmp = checkout(tmp_path)
    seed(tmp)
    hostile_build(tmp, kind)
    code = (tmp / "scripts" / "state_paths.py").read_bytes()
    r = simulate(workflow, tmp, event=event)
    assert r["failed"] and "may not be restored" in r["log"], r["log"]
    assert (tmp / "scripts" / "state_paths.py").read_bytes() == code
    assert not (tmp / "data" / "build").exists() and not (tmp / "data" / "rules.json").exists()
    assert puts(tmp) == [] and not (tmp / "publish.done").exists() and not (tmp / "release.done").exists()


def test_unpack_build_restores_data_build_and_skips_appledouble(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("state_paths_t", ROOT / "scripts" / "state_paths.py")
    SP = importlib.util.module_from_spec(spec)
    sys.modules["state_paths_t"] = SP
    spec.loader.exec_module(SP)
    src = tmp_path / "src"
    (src / "data/build/sub").mkdir(parents=True)
    (src / "data/build/sub/a.json").write_text("{}")
    (src / "data/build/._a.json").write_text("mac")
    tgz = tmp_path / "b.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(src / "data", arcname="data")
    root = tmp_path / "root"
    root.mkdir()
    assert SP.unpack_build(tgz, root) == {"files": 1, "skipped": 1}
    assert (root / "data/build/sub/a.json").read_text() == "{}" and not (root / "data/build/._a.json").exists()
    # a checkout whose data/build is a link is never written through
    other = tmp_path / "elsewhere"
    other.mkdir()
    root2 = tmp_path / "root2"
    (root2 / "data").mkdir(parents=True)
    (root2 / "data" / "build").symlink_to(other)
    with pytest.raises(SP.Unreadable):
        SP.unpack_build(tgz, root2)
    assert list(other.iterdir()) == []
