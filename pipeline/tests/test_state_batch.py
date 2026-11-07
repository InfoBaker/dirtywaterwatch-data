"""scripts/state_batch.py (the per-state water batch helper) and the two workflows that keep state in R2: step and
input validation, the commands a plan runs (its dry run), obl-check, the run summary and pull-request body, the
privacy scan, the publish to batch/<st>-<date>, and the workflow files loaded as YAML.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import stat
import tarfile
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("state_batch", ROOT / "scripts" / "state_batch.py")
B = importlib.util.module_from_spec(_spec)
sys.modules["state_batch"] = B            # dataclasses look their module up there
_spec.loader.exec_module(B)

PY = "/py"


# ---------------------------------------------------------------- inputs

def test_steps_default_order_and_separators():
    assert B.parse_steps("waters ties") == ["waters", "ties"]
    assert B.parse_steps("ties,waters") == ["waters", "ties"]          # run order, whatever the given order
    assert B.parse_steps(" ties  waters obl-check ") == ["obl-check", "waters", "ties"]
    assert B.parse_steps(["waters", "waters"]) == ["waters"]


@pytest.mark.parametrize("text,why", [
    ("", "no steps"), ("waters rm", "unknown step 'rm'"), ("reaches", "no state scope"),
    ("waters reaches ties", "no state scope"), ("registry waters", "add ties"), ("waters;ls", "unknown step"),
])
def test_steps_refused(text, why):
    with pytest.raises(B.Refused, match=why):
        B.parse_steps(text)


def test_state_validated():
    assert B.valid_state("nc") == "NC"
    assert B.valid_state(" GA ") == "GA"
    for bad in ("N", "NCX", "N1", "", "../", "ZZ"):
        with pytest.raises(B.Refused):
            B.valid_state(bad)


def test_numbers_bounded():
    assert B.bounded("budget_s", "1500", B.BUDGET_S) == 1500
    for bad in ("0", "-5", "1e3", "abc", "999999"):
        with pytest.raises(B.Refused):
            B.bounded("budget_s", bad, B.BUDGET_S)


# ---------------------------------------------------------------- plan

def test_plan_commands_for_north_carolina(capsys):
    p = B.plan("nc", "waters ties", "1500", "1000", py=PY)
    assert [(c.step, c.cwd, c.argv) for c in p.cmds] == [
        ("waters", "pipeline", [PY, "-m", "ingest.waters_from_nhd", "--state", "NC", "--budget-s", "1500",
                                "--max-requests", "1000"]),
        ("ties", "pipeline", [PY, "-m", "ingest.outfall_waters", "--state", "NC"]),
    ]
    assert B.run(p, dry_run=True) == 0
    out = capsys.readouterr().out.splitlines()
    # the outlines' folder is named on the steps that measure against it (the restored openboatlaunch snapshot)
    assert out == ["[waters] (cd pipeline && OBL_WATER_DIR=../../openboatlaunch/out/water /py -m ingest.waters_from_nhd "
                   "--state NC --budget-s 1500 --max-requests 1000)",
                   "[ties] (cd pipeline && OBL_WATER_DIR=../../openboatlaunch/out/water /py -m ingest.outfall_waters --state NC)"]


def test_plan_cli_dry_run_runs_nothing(capsys):
    assert B.main(["plan", "--state", "NC", "--steps", "obl-check waters ties"]) == 0
    out = capsys.readouterr().out
    assert "[obl-check]" in out and "ingest.waters_from_nhd --state NC --budget-s 1500 --max-requests 1000" in out
    assert B.main(["run", "--state", "NC", "--dry-run"]) == 0
    assert B.main(["plan", "--state", "NC", "--steps", "reaches"]) == 2
    assert "no state scope" in capsys.readouterr().out


def test_registry_needs_its_inputs(tmp_path, monkeypatch):
    monkeypatch.delenv("DWW_CSO_CSV", raising=False)
    monkeypatch.delenv("OBL_WATER_DIR", raising=False)
    with pytest.raises(B.Refused, match="ALL_CSO_DOWNLOADS.csv.*openboatlaunch"):
        B.plan("NC", "registry ties", py=PY)
    csv = tmp_path / "ALL_CSO_DOWNLOADS.csv"
    csv.write_text("x")
    obl = tmp_path / "water"
    obl.mkdir()
    p = B.plan("NC", "registry ties", cso_csv=str(csv), obl_dir=str(obl), py=PY)
    reg = [c for c in p.cmds if c.step == "registry"]
    assert [c.argv[1:] for c in reg] == [
        ["-I", "scripts/match_outfalls.py", str(csv), str(obl), "data/outfalls-us.json", "--national", "--append"],
        ["-I", "scripts/match_outfalls.py", "data/outfalls-plants-us.json", str(obl), "data/outfalls-plants-us.json",
         "--plants"]]
    assert all(c.env == {"DWW_STATES": "NC"} and c.cwd == "." for c in reg)
    assert [c.step for c in p.cmds] == ["registry", "registry", "ties"]
    with pytest.raises(B.Refused, match="regional files"):
        B.plan("MA", "registry ties", cso_csv=str(csv), obl_dir=str(obl), py=PY)


# ---------------------------------------------------------------- a small repository

def git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], check=True, text=True, capture_output=True).stdout


def write(root: Path, rel: str, obj) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1) if not isinstance(obj, str) else obj)


def repo(tmp_path: Path) -> Path:
    """A git repository with origin, the files the batch reads and writes, committed on main."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    write(root, ".gitignore", "data/build/\n")
    write(root, "data/receiving-waters-national.json", {"states": {
        "NC": {"summary": {"water_records_on_file": 0},
               "waters": [{"name": "Neuse River", "define_by": "reach"},
                          {"name": "Haw River", "define_by": "record", "water_slug": "haw-river-nc"},
                          {"name": "Gone Creek", "define_by": "record", "water_slug": "gone-creek-nc"}]},
        "OH": {"summary": {}, "waters": []}}})
    write(root, "data/waters-nc.json", {"state": "NC", "source": "openboatlaunch out/water snapshot 2026-11-02",
                                        "waters": [{"slug": "haw-river-nc", "state": "NC"}]})
    write(root, "data/waters-nhd.json", {"waters": [{"slug": "neuse-river-nc", "state": "NC", "name": "Neuse River"}],
                                         "targets": [{"state": "NC", "name": "Neuse River", "slugs": []}]})
    write(root, "data/outfalls-us.json", {"outfalls": [{"state": "NC", "npdes_permit": "NC0000001", "water_slug": None}]})
    write(root, "data/outfalls-plants-us.json", {"outfalls": []})
    write(root, "data/outfalls-new-england.json", {"outfalls": []})
    write(root, "data/outfalls-mid-atlantic.json", {"outfalls": []})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "origin", "main")
    return root


def test_obl_check(tmp_path):
    root = repo(tmp_path)
    ok, lines = B.obl_check("nc", root)
    assert ok
    assert "1 records (openboatlaunch out/water snapshot 2026-11-02)" in lines[0]
    assert "3 named receiving waters, 2 with a record, 1 of those whose slug no water file holds" in lines[1]
    assert "predates them" in lines[2]                                  # 0 counted, 2 on file now
    ok, lines = B.obl_check("OH", root)
    assert not ok and "ingest.obl_waters --state OH" in lines[0]
    # SOL wave1 P2-11: a correctly shaped empty extract is not accepted
    write(root, "data/waters-nc.json", {"state": "NC", "source": "openboatlaunch out/water snapshot 2026-11-02",
                                        "count": 0, "waters": []})
    ok, lines = B.obl_check("nc", root)
    assert not ok and "holds no water record" in lines[0]


def fake_step(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_writes_summary_and_body_and_stops_at_a_failure(tmp_path, capsys):
    root = repo(tmp_path)
    change = ("import json,pathlib;p=pathlib.Path('data/waters-nhd.json');d=json.loads(p.read_text());"
              "d['waters'].append({'slug':'haw-creek-nc','state':'NC'});d['targets'][0]['slugs']=['neuse-river-nc'];"
              "d.setdefault('stats',{})['state_builds']={'NC':{'built':'2999-01-01T00:00:00Z','targets':1,"
              "'targets_mapped':1,'targets_failed':0,'records':1,'records_by_kind':{'river':1},"
              "'run':{'network_requests':7,'stopped':'--max-requests 7 used'}}};p.write_text(json.dumps(d));"
              "print('state build NC: {1}');print('table row not kept');print('1 records -> data/waters-nhd.json: merged')")
    p = B.Plan("NC", ["waters", "ties"], 60, 7, [
        B.Cmd("waters", fake_step(change)),
        B.Cmd("ties", fake_step("import sys;print('NC: tied to a record 1');print('written: x');sys.exit(3)")),
    ])
    out = tmp_path / "out"
    assert B.run(p, out, root=root) == 1
    s = json.loads((out / "summary.json").read_text())
    assert [r["exit"] for r in s["results"]] == [0, 3] and not s["ok"]
    assert s["results"][0]["counts"] == ["state build NC: {1}", "1 records -> data/waters-nhd.json: merged"]
    assert s["results"][1]["counts"] == ["NC: tied to a record 1", "written: x"]
    assert s["files"] == ["data/waters-nhd.json"]
    assert s["counts"]["waters"]["network_requests"] == 7
    assert s["before_after"]["NHD water records"] == [1, 2]
    assert s["before_after"]["targets with a record"] == [0, 1]
    body = (out / "pr-body.md").read_text()
    assert body.startswith("## Water batch: North Carolina (NC), ")
    assert "| `ties` | failed (exit 3) |" in body and "Stopped at the budget: --max-requests 7 used" in body
    assert "| NHD water records | 1 | 2 |" in body and "- `data/waters-nhd.json`" in body
    assert (out / "waters.log").read_text().startswith("$ ")
    # a failed first step stops the second
    p2 = B.Plan("NC", ["waters", "ties"], 60, 7, [B.Cmd("waters", fake_step("raise SystemExit(1)")),
                                                  B.Cmd("ties", fake_step("print('never')"))])
    assert B.run(p2, tmp_path / "out2", root=root) == 1
    s2 = json.loads((tmp_path / "out2" / "summary.json").read_text())
    assert s2["not_run"] == ["ties"] and len(s2["results"]) == 1
    assert "never" not in capsys.readouterr().out


def test_run_obl_check_failure_stops_the_batch(tmp_path):
    root = repo(tmp_path)
    p = B.Plan("OH", ["obl-check", "waters"], 60, 7, [B.Cmd("obl-check", ["unused"]),
                                                      B.Cmd("waters", fake_step("print('never')"))])
    assert B.run(p, tmp_path / "out", root=root) == 1
    s = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert s["not_run"] == ["waters"] and "ingest.obl_waters --state OH" in s["results"][0]["counts"][0]


# ---------------------------------------------------------------- privacy scan

def test_scan_finds_new_contact_strings_and_prints_only_where(tmp_path, capsys):
    root = repo(tmp_path)
    assert B.scan("NC", root=root) == 0                                # nothing changed
    d = json.loads((root / "data/waters-nhd.json").read_text())
    d["waters"].append({"slug": "x-nc", "state": "NC", "note": "call 919-555-0134 or write to pat@example.org",
                        "length_km": 123.4567})
    write(root, "data/waters-nhd.json", d)
    capsys.readouterr()
    assert B.scan("NC", root=root) == 1
    out = capsys.readouterr().out
    assert "data/waters-nhd.json $.waters[1].note: an e-mail address" in out and "a phone number" in out
    assert out.count("::error::") == 2                                 # numbers are not strings: not scanned
    assert "pat@example.org" not in out and "555" not in out
    assert B.scan("NC", require_blocklist=True, root=root) == 1        # no blocklist on this machine: closed
    assert "blocklist" in capsys.readouterr().out


def test_scan_blocklist_and_body_text(tmp_path, capsys):
    root = repo(tmp_path)
    write(root, "data/build/name-blocklist.json", {"names": ["Jordan Quill"]})
    d = json.loads((root / "data/outfalls-us.json").read_text())
    d["outfalls"][0]["permittee"] = "JORDAN QUILL"
    write(root, "data/outfalls-us.json", d)
    body = tmp_path / "body.md"
    body.write_text("## Water batch\n- counts only\n")
    assert B.scan("NC", [body], require_blocklist=True, root=root) == 1
    out = capsys.readouterr().out
    assert "data/outfalls-us.json $.outfalls[0].permittee: a blocklisted name" in out
    assert "quill" not in out.lower()
    d["outfalls"][0]["permittee"] = "Town of Example"
    write(root, "data/outfalls-us.json", d)
    assert B.scan("NC", [body], require_blocklist=True, root=root) == 0
    body.write_text("thanks to Jordan Quill\n")
    assert B.scan("NC", [body], require_blocklist=True, root=root) == 1


def test_body_says_where_it_ran(monkeypatch):
    s = {"state": "GA", "steps": ["waters"], "budget_s": 60, "max_requests": 5, "started": "2026-11-04T05:00:00Z",
         "finished": "2026-11-04T05:01:00Z", "ok": True, "results": [], "counts": {}, "files": ["data/waters-nhd.json"]}
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert "Run by hand" in B.pr_body(s) and "restored from R2" not in B.pr_body(s)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/data")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    body = B.pr_body(s)
    assert "restored from R2" in body and "(https://github.com/example/data/actions/runs/42)" in body
    assert body.startswith("## Water batch: Georgia (GA), 2026-11-04")


def test_body_template_passes_the_scan(tmp_path):
    root = repo(tmp_path)
    s = {"state": "NC", "steps": ["waters", "ties"], "budget_s": 1500, "max_requests": 1000,
         "started": "2026-11-04T05:00:00Z", "finished": "2026-11-04T05:30:00Z", "ok": True,
         "results": [{"step": "waters", "exit": 0, "seconds": 1700, "counts": ["state build NC: {}"]}],
         "counts": {}, "before_after": {"NHD water records": [1, 2]}, "files": []}
    body = tmp_path / "body.md"
    body.write_text(B.pr_body(s))
    assert "- none" in body.read_text()
    write(root, "data/build/name-blocklist.json", {"names": ["Jordan Quill"]})
    assert B.scan("NC", [body], require_blocklist=True, root=root) == 0


# ---------------------------------------------------------------- publish

def fake_gh(tmp_path: Path, list_answer: str) -> tuple[Path, Path]:
    log = tmp_path / "gh.log"
    gh = tmp_path / "gh"
    gh.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n"
                  f"case \"$1 $2\" in 'pr list') printf '%s' '{list_answer}' ;; esac\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return gh, log


def test_publish_dry_run_and_nothing_changed(tmp_path, capsys):
    root = repo(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("counts\n")
    assert B.publish("NC", body, "2026-11-04", dry_run=True, root=root, require_blocklist=False) == 0
    assert "no branch, no pull request" in capsys.readouterr().out
    write(root, "data/waters-nhd.json", {"waters": [], "targets": []})
    write(root, "data/rules.json", {"live_states": ["NC"]})            # changed, not the batch's: left out
    assert B.publish("NC", body, "2026-11-04", dry_run=True, root=root, require_blocklist=False) == 0
    out = capsys.readouterr().out
    assert "git checkout -B batch/nc-2026-11-04" in out
    assert "git add -- data/waters-nhd.json\n" in out
    assert "git push --force origin HEAD:refs/heads/batch/nc-2026-11-04" in out
    assert "gh pr create --base main --head batch/nc-2026-11-04 --title 'Water batch: North Carolina (NC), 2026-11-04'" in out
    assert "changed but not part of the pull request: data/rules.json" in out
    assert git(root, "branch", "--list", "batch/*") == ""              # a dry run changes nothing


def test_publish_opens_then_updates(tmp_path):
    root = repo(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("counts\n")
    write(root, "data/build/name-blocklist.json", {"names": ["Jordan Quill"]})   # git-ignored, as in the real repo
    write(root, "data/waters-nhd.json", {"waters": [{"slug": "neuse-river-nc", "state": "NC"}], "targets": []})
    gh, log = fake_gh(tmp_path, "")
    assert B.publish("NC", body, "2026-11-04", root=root, gh=str(gh)) == 0
    calls = log.read_text().splitlines()
    assert calls[0].startswith("pr list --head batch/nc-2026-11-04")
    assert calls[1].startswith("pr create --base main --head batch/nc-2026-11-04 --title Water batch: North Carolina")
    origin = tmp_path / "origin.git"
    shown = git(origin, "show", "--stat", "--format=%an|%s", "batch/nc-2026-11-04")
    assert shown.startswith("github-actions[bot]|Water batch: North Carolina (NC), 2026-11-04: data/waters-nhd.json")
    assert "data/waters-nhd.json" in shown and "name-blocklist" not in shown
    # the same day again, from main with another change: the branch is replaced and the open pull request edited
    git(root, "checkout", "-q", "main")
    write(root, "data/outfalls-us.json", {"outfalls": [{"state": "NC", "npdes_permit": "NC0000001",
                                                        "water_slug": "neuse-river-nc"}]})
    gh, log = fake_gh(tmp_path, "17")
    log.unlink()
    assert B.publish("NC", body, "2026-11-04", root=root, gh=str(gh)) == 0
    calls = log.read_text().splitlines()
    assert calls[1].startswith("pr edit 17 --title Water batch: North Carolina (NC), 2026-11-04 --body-file")
    files = git(origin, "show", "--name-only", "--format=", "batch/nc-2026-11-04").split()
    assert files == ["data/outfalls-us.json"]          # the earlier commit is replaced, not stacked on
    assert git(origin, "rev-parse", "batch/nc-2026-11-04~1") == git(origin, "rev-parse", "main")


def test_publish_finds_the_pull_request_after_a_failed_create(tmp_path, capsys):
    # GitHub's GraphQL endpoint answered 502 to `gh pr create` on 2026-11-07 after the pull request was open: the step
    # looks again before failing, and the pull request is updated
    root = repo(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("counts\n")
    write(root, "data/build/name-blocklist.json", {"names": ["Jordan Quill"]})
    write(root, "data/waters-nhd.json", {"waters": [{"slug": "neuse-river-nc", "state": "NC"}], "targets": []})
    log = tmp_path / "gh.log"
    seen = tmp_path / "gh.calls"
    gh = tmp_path / "gh"
    # `pr list` answers nothing the first time and 31 after the create has failed; `pr create` fails like a 502
    gh.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n"
                  f"case \"$1 $2\" in 'pr list') if [ -f {seen} ]; then printf '%s' 31; fi ;; "
                  f"'pr create') touch {seen}; echo 'HTTP 502: 502 Bad Gateway' >&2; exit 1 ;; esac\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    assert B.publish("NC", body, "2026-11-04", root=root, gh=str(gh), pause_s=0) == 0
    calls = log.read_text().splitlines()
    assert [c.split()[0:2] for c in calls] == [["pr", "list"], ["pr", "create"], ["pr", "list"], ["pr", "edit"]]
    assert "pull request #31 was open after all" in capsys.readouterr().out


def test_publish_opens_through_rest_when_graphql_keeps_failing(tmp_path, capsys):
    root = repo(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("counts\n")
    write(root, "data/build/name-blocklist.json", {"names": ["Jordan Quill"]})
    write(root, "data/waters-nhd.json", {"waters": [{"slug": "neuse-river-nc", "state": "NC"}], "targets": []})
    log = tmp_path / "gh.log"
    gh = tmp_path / "gh"
    gh.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n"
                  f"case \"$1 $2\" in 'pr create') exit 1 ;; 'api -X') exit 0 ;; esac\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    assert B.publish("NC", body, "2026-11-04", root=root, gh=str(gh), pause_s=0) == 0
    calls = log.read_text().splitlines()
    assert calls[1].startswith("pr create") and calls[3].startswith("api -X POST repos/{owner}/{repo}/pulls -f base=main -f head=batch/nc-2026-11-04")
    assert "through the REST endpoint" in capsys.readouterr().out


def test_publish_refuses_when_the_scan_finds_something(tmp_path, capsys):
    root = repo(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("counts\n")
    write(root, "data/waters-nhd.json", {"waters": [{"slug": "a", "note": "pat@example.org"}], "targets": []})
    gh, log = fake_gh(tmp_path, "")
    assert B.publish("NC", body, "2026-11-04", root=root, gh=str(gh), require_blocklist=False) == 1
    assert not log.exists()
    assert git(root, "branch", "--list", "batch/*") == ""
    assert "nothing is committed or pushed" in capsys.readouterr().out


def test_publish_reports_a_refused_pull_request(tmp_path, capsys):
    root = repo(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("counts\n")
    write(root, "data/waters-nhd.json", {"waters": [], "targets": []})
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\n[ \"$2\" = create ] && { echo 'GitHub Actions is not permitted to create or approve "
                  "pull requests' >&2; exit 1; }\nexit 0\n")
    gh.chmod(0o755)
    assert B.publish("NC", body, "2026-11-04", root=root, gh=str(gh), require_blocklist=False) == 1
    assert "Workflow permissions" in capsys.readouterr().out
    assert git(tmp_path / "origin.git", "branch", "--list", "batch/nc-2026-11-04").strip()


# ---------------------------------------------------------------- the workflows

def load(name: str) -> dict:
    d = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    d["on"] = d.pop(True, d.get("on"))            # YAML 1.1 reads the key `on` as true
    return d


def test_state_build_workflow():
    w = load("state-build.yml")
    assert set(w["on"]) == {"workflow_dispatch"}
    inputs = w["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"state", "steps", "budget_s", "max_requests", "osm_budget"}
    assert inputs["state"]["required"] is True
    assert (inputs["steps"]["default"], inputs["budget_s"]["default"], inputs["max_requests"]["default"]) == \
        ("waters ties", "1500", "1000")
    assert w["concurrency"] == {"group": "refresh", "cancel-in-progress": False}
    assert w["permissions"] == {"contents": "write", "pull-requests": "write"}
    job = next(iter(w["jobs"].values()))
    names = [s.get("name", "") for s in job["steps"]]
    order = [next(i for i, n in enumerate(names) if n.startswith(k)) for k in
             ("Check the inputs", "Restore pipeline state", "Restore the raw caches", "Run the steps",
              "Save the raw caches", "Branch and pull request")]
    assert order == sorted(order)
    # dispatch inputs reach the shell through env, never pasted into a script
    for s in job["steps"]:
        assert "github.event.inputs" not in s.get("run", "") and "inputs." not in s.get("run", "")
    text = (ROOT / ".github/workflows/state-build.yml").read_text()
    assert "state/raw-cache.tar.gz" in text and "state/build.tar.gz" in text
    assert "object put dirtywaterwatch-data/state/build.tar.gz" not in text        # the batch never saves build
    assert "cancelled()" in job["steps"][order[4]]["if"]
    assert "state_batch.py publish" in job["steps"][order[5]]["run"]


def test_refresh_workflow_keeps_the_raw_cache():
    w = load("refresh.yml")
    steps = w["jobs"]["refresh"]["steps"]
    names = [s.get("name", "") for s in steps]
    rb = names.index("Restore pipeline state from R2")
    rr = next(i for i, n in enumerate(names) if n.startswith("Restore the raw caches"))
    refresh = next(i for i, n in enumerate(names) if n.startswith("Refresh ("))
    sb = names.index("Save pipeline state to R2")
    sr = next(i for i, n in enumerate(names) if n.startswith("Save the raw caches"))
    assert rb < rr < refresh < sb < sr
    assert steps[sb]["if"].startswith("success() && ") and steps[sr]["if"].startswith("success() && ")
    assert "steps.pause.outputs.paused != '1'" in steps[sb]["if"]                 # SOL wave1 P2-9
    assert "steps.refresh.outputs.skipped != '1'" in steps[sb]["if"] and "steps.refresh.outputs.skipped != '1'" in steps[sr]["if"]
    assert "steps.restore_raw.outputs.keep != '1'" in steps[sr]["if"]       # a cache it could not fetch stays
    assert "state_paths.py pack raw-cache.tar.gz" in steps[sr]["run"]
    assert "state_paths.py unpack raw-cache.tar.gz" in steps[rr]["run"]
    assert "check-size build.tar.gz" in steps[sb]["run"]


@pytest.mark.parametrize("st,date", [("NC", "2026-11-04 main"), ("N C", "2026-11-04"), ("NC", "../main"),
                                     ("NCX", "2026-11-04"), ("nc", "x")])
def test_publish_force_pushes_a_batch_branch_only(st, date):
    with pytest.raises(B.Refused):
        B.publish_cmds(st, date, Path("body.md"), ["data/waters-nhd.json"])
    c = B.publish_cmds("NC", "2026-11-04", Path("body.md"), ["data/waters-nhd.json"])
    assert c["commit"][-1] == ["git", "push", "--force", "origin", "HEAD:refs/heads/batch/nc-2026-11-04"]


# ---------------------------------------------------------------- openboatlaunch in the batch: extract, osm, outlines

OBL_REL = "../../openboatlaunch/out/water"          # the restored sibling, from pipeline/


def test_steps_extract_and_osm_order():
    assert B.parse_steps("ties osm extract waters obl-check") == ["extract", "obl-check", "waters", "osm", "ties"]
    assert B.parse_steps("osm") == ["osm"]


def test_plan_extract_osm_ties_with_the_restored_snapshot():
    p = B.plan("nc", "extract obl-check osm ties", "1500", "1000", py=PY, osm_budget="1200")
    assert [(c.step, c.cwd, c.argv, c.env) for c in p.cmds] == [
        ("extract", "pipeline", [PY, "-m", "ingest.obl_waters", "--state", "NC", "--from", OBL_REL,
                                 "--out", "../data/waters-nc.json"], {}),
        ("obl-check", ".", [PY, "scripts/state_batch.py", "obl-check", "--state", "NC"], {}),
        ("osm", "pipeline", [PY, "-m", "ingest.waters_from_nhd", "--state", "NC", "--budget-s", "1500",
                             "--max-requests", "1000", "--osm-budget", "1200"], {"OBL_WATER_DIR": OBL_REL}),
        ("ties", "pipeline", [PY, "-m", "ingest.outfall_waters", "--state", "NC"], {"OBL_WATER_DIR": OBL_REL}),
    ]
    assert p.osm_budget == 1200 and p.obl_dir == B.ROOT.parent / "openboatlaunch" / "out" / "water"


def test_plan_waters_and_osm_run_as_one_build():
    p = B.plan("FL", "waters osm", py=PY, osm_budget=600)
    assert p.steps == ["waters", "osm"]
    assert [(c.step, c.argv[-2:]) for c in p.cmds] == [("osm", ["--osm-budget", "600"])]
    w = B.plan("FL", "waters", py=PY)
    assert "--osm-budget" not in w.cmds[0].argv and w.cmds[0].env == {"OBL_WATER_DIR": OBL_REL}


def test_plan_osm_budget_bounded():
    for bad in ("0", "59", "1201", "x"):
        with pytest.raises(B.Refused, match="osm_budget"):
            B.plan("FL", "osm", py=PY, osm_budget=bad)


def test_plan_given_obl_dir_is_absolute(tmp_path):
    water = tmp_path / "out" / "water"
    p = B.plan("NC", "extract ties", py=PY, obl_dir=str(water))
    assert p.cmds[0].argv[p.cmds[0].argv.index("--from") + 1] == str(water.resolve())
    assert p.cmds[1].env == {"OBL_WATER_DIR": str(water.resolve())}


def test_plan_dry_run_shows_the_outline_path(capsys):
    assert B.main(["plan", "--state", "NC", "--steps", "extract osm ties", "--osm-budget", "900"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("[extract] (cd pipeline && ") and f"--from {OBL_REL} --out ../data/waters-nc.json" in out[0]
    assert out[1].startswith(f"[osm] (cd pipeline && OBL_WATER_DIR={OBL_REL} ") and out[1].endswith("--osm-budget 900)")
    assert out[2].endswith(f"OBL_WATER_DIR={OBL_REL} {B.pipeline_python()} -m ingest.outfall_waters --state NC)")


def obl_fixture(tmp_path: Path, meta: bool = True) -> Path:
    """Three fake openboatlaunch records (two in NC, one in GA) packed as the upload packs them, restored as the workflow
    restores them; returns <tmp>/openboatlaunch/out/water."""
    sp_spec = importlib.util.spec_from_file_location("state_paths", ROOT / "scripts" / "state_paths.py")
    SP = importlib.util.module_from_spec(sp_spec)
    sys.modules["state_paths"] = SP
    sp_spec.loader.exec_module(SP)
    src = tmp_path / "obl-src" / "out"
    (src / "water").mkdir(parents=True)
    line = {"type": "LineString", "coordinates": [[-79.30, 35.90], [-79.20, 35.95], [-79.10, 36.00]]}
    poly = {"type": "Polygon", "coordinates": [[[-78.70, 35.70], [-78.68, 35.70], [-78.68, 35.72], [-78.70, 35.70]]]}
    for slug, name, kind, geom in (("haw-river-nc", "Haw River", "river", line),
                                   ("lake-wheeler-nc", "Lake Wheeler", "lake", poly),
                                   ("lake-lanier-ga", "Lake Lanier", "lake", poly)):
        (src / "water" / f"{slug}.json").write_text(json.dumps({
            "slug": slug, "name": name, "kind": kind, "state": slug[-2:].upper(), "towns": ["Example"],
            "bbox": [-79.3, 35.7, -78.6, 36.0], "launches": [{"s": f"{slug}-ramp"}], "geometry": geom}))
    if meta:
        (src / "meta.json").write_text(json.dumps({"built": "2026-11-01T04:00:00Z"}))
    tgz = tmp_path / "obl-water.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(src / "water", arcname="water")
        if meta:
            tf.add(src / "meta.json", arcname="meta.json")
    SP.unpack_obl(tgz, tmp_path / "openboatlaunch" / "out")
    return tmp_path / "openboatlaunch" / "out" / "water"


def test_extract_step_on_three_fake_records(tmp_path, monkeypatch):
    root = repo(tmp_path)                                   # <tmp>/repo: its sibling is <tmp>/openboatlaunch
    water = obl_fixture(tmp_path)
    (root / "pipeline").mkdir()                             # the steps run from pipeline/; the code comes from here
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "pipeline"))
    p = B.plan("NC", "extract obl-check", py=sys.executable, root=root)
    assert p.obl_dir == water.parent.parent.parent / "openboatlaunch" / "out" / "water"
    assert B.run(p, tmp_path / "out", root=root) == 0
    d = json.loads((root / "data/waters-nc.json").read_text())
    assert d["count"] == 2 and [w["slug"] for w in d["waters"]] == ["haw-river-nc", "lake-wheeler-nc"]
    assert d["source"] == "openboatlaunch out/water snapshot 2026-11-01"
    assert d["waters"][0]["launches"] == ["haw-river-nc-ramp"] and "geometry" not in d["waters"][0]
    s = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert s["files"] == ["data/waters-nc.json"]
    assert s["results"][0]["counts"][0].startswith("obl_waters: 2 NC waters")
    assert "2 records (openboatlaunch out/water snapshot 2026-11-01)" in s["results"][1]["counts"][0]
    assert "data/waters-nc.json" in B.candidate_files("NC")


def test_ties_read_the_restored_outlines(tmp_path):
    """build/status.py water_geometry (what ingest.outfall_waters and ingest.waters_from_nhd measure against) reads
    the outline from OBL_WATER_DIR, the path the batch sets on its steps."""
    import os
    water = obl_fixture(tmp_path)
    code = ("from build import status as S;g=S.water_geometry('haw-river-nc');"
            "print(S.OBL_WATER_DIR, g.geom_type if g is not None else None)")
    py = str(ROOT / "pipeline/.venv/bin/python") if (ROOT / "pipeline/.venv").exists() else sys.executable
    base = {k: v for k, v in os.environ.items() if k != "OBL_WATER_DIR"}
    r = subprocess.run([py, "-c", code], cwd=ROOT / "pipeline", text=True, capture_output=True,
                       env={**base, "OBL_WATER_DIR": str(water)})
    assert r.stdout.strip() == f"{water} LineString", r.stderr
    r = subprocess.run([py, "-c", code], cwd=ROOT / "pipeline", text=True, capture_output=True, env=base)
    assert r.stdout.strip().startswith(str(ROOT.parent / "openboatlaunch" / "out" / "water")), r.stderr


@pytest.mark.parametrize("meta", [False, None])
def test_extract_refuses_without_the_snapshot_or_its_date(tmp_path, meta, capsys):
    root = repo(tmp_path)
    if meta is False:
        obl_fixture(tmp_path, meta=False)
    p = B.plan("NC", "extract ties", py=sys.executable, root=root)
    p.cmds[1] = B.Cmd("ties", fake_step("print('never')"))
    assert B.run(p, tmp_path / "out", root=root) == 1
    s = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert s["not_run"] == ["ties"]
    msg = s["results"][0]["counts"][0]
    assert ("no snapshot date" in msg) if meta is False else ("state/obl-water.tar.gz" in msg)
    assert "never" not in capsys.readouterr().out
    assert json.loads((root / "data/waters-nc.json").read_text())["source"].endswith("2026-11-02")   # untouched


def test_osm_counts_reach_the_summary_and_body(tmp_path):
    root = repo(tmp_path)
    change = ("import json,pathlib;p=pathlib.Path('data/waters-nhd.json');d=json.loads(p.read_text());"
              "d.setdefault('stats',{})['state_builds']={'FL':{'built':'2999-01-01T00:00:00Z','targets':3,"
              "'run':{'network_requests':2,'stopped':None,'osm':{'by_state':{'FL':{'targets':40,'queries':3,'sent':2,"
              "'failed':'time budget of 1200 s used','via':['x']}},'left_for_next_run':11}}}};p.write_text(json.dumps(d));"
              "print('state build FL: {}');print('  FL: 40 names, 30 asked in 3 queries; stopped after 2 (time budget)')")
    write(root, "data/receiving-waters-national.json", {"states": {"FL": {"waters": []}}})
    p = B.Plan("FL", ["osm"], 60, 7, [B.Cmd("osm", fake_step(change))], osm_budget=1200)
    assert B.run(p, tmp_path / "out", root=root) == 0
    s = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert s["osm_budget"] == 1200
    assert s["results"][0]["counts"] == ["state build FL: {}",
                                         "  FL: 40 names, 30 asked in 3 queries; stopped after 2 (time budget)"]
    assert s["counts"]["waters"]["osm"]["left_for_next_run"] == 11
    body = (tmp_path / "out" / "pr-body.md").read_text()
    assert "OpenStreetMap budget 1200 s" in body
    assert "- OpenStreetMap pass: 2 of 3 queries answered; 11 names left for the next run" in body


def test_state_stats_carry_the_osm_pass():
    from types import SimpleNamespace
    from ingest import waters_from_nhd as N
    http = SimpleNamespace(fetched={}, requests=0, cached={}, failed={})
    run = SimpleNamespace(skipped_reason={}, stopped=None, place_stats={}, osm_remaining=["FL: Tampa Bay"],
                          osm_states={"FL": {"targets": 1, "queries": 1, "sent": 0, "failed": "x", "via": []}})
    out = N.state_stats(["FL"], [], [], [], {}, http, run)
    assert out["FL"]["run"]["osm"] == {"by_state": run.osm_states, "left_for_next_run": 1}


def test_state_build_workflow_restores_the_openboatlaunch_object():
    w = load("state-build.yml")
    inputs = w["on"]["workflow_dispatch"]["inputs"]
    assert inputs["osm_budget"]["default"] == "1200"
    assert "extract" in inputs["steps"]["description"] and "osm" in inputs["steps"]["description"]
    job = next(iter(w["jobs"].values()))
    assert job["env"]["OSM_BUDGET"] == "${{ inputs.osm_budget }}"
    names = [s.get("name", "") for s in job["steps"]]
    ro = next(i for i, n in enumerate(names) if n.startswith("openboatlaunch's water records"))
    run = next(i for i, n in enumerate(names) if n.startswith("Run the steps"))
    assert names.index("Restore pipeline state from R2 (read only here)") < ro < run
    assert "state_paths.py unpack-obl obl-water.tar.gz" in job["steps"][ro]["run"]
    # the API first (fetch-obl), the R2 copy only when it was not used
    assert job["steps"][ro]["run"].index("fetch-obl") < job["steps"][ro]["run"].index("fetch state/obl-water.tar.gz")
    assert job["env"]["OBL_API_KEY"] == "${{ secrets.OBL_API_KEY }}"
    for s in job["steps"]:
        if s.get("run") and "state_batch.py" in s["run"] and ("plan" in s["run"] or " run " in s["run"]):
            assert '--osm-budget "$OSM_BUDGET"' in s["run"]
    text = (ROOT / ".github/workflows/state-build.yml").read_text()
    assert "object put dirtywaterwatch-data/state/obl-water.tar.gz" not in text      # restored only, never saved
    # the refresh saves the folder only when the API changed it (pack-obl), before the build state, rolled back on
    # a failed upload (obl-not-saved)
    rt = (ROOT / ".github/workflows/refresh.yml").read_text()
    assert rt.index("state_paths.py pack-obl") < rt.index("object put dirtywaterwatch-data/state/obl-water.tar.gz") \
        < rt.index("state_paths.py obl-not-saved") < rt.index("tar -czf build.tar.gz data/build")


def test_extract_never_overwrites_a_regional_water_file(tmp_path):
    root = repo(tmp_path)
    write(root, "data/receiving-waters-national.json", {"states": {"NE": {"waters": []}, "NC": {"waters": []}}})
    write(root, "data/waters-ne.json", {"source": "New England", "count": 0, "waters": []})
    with pytest.raises(B.Refused, match="New England"):
        B.plan("NE", "extract", py=PY, root=root)
    assert B.plan("NE", "waters", py=PY, root=root).cmds                 # the other steps are not affected
    assert B.plan("NC", "extract", py=PY, root=root).cmds[0].step == "extract"   # NC's own extract is replaced


# ---------------------------------------------------------------- review 2026-11-04 (eng/obl-in-state)

def test_plan_osm_with_budget_s_keeps_the_old_worst_case():
    """budget_s and osm_budget together stay within the batch's worst case before the osm step (3,600 + 180 s), so
    the job is not cancelled at the workflow's 120 minutes with nothing saved."""
    with pytest.raises(B.Refused, match="osm_budget 1200 together"):
        B.plan("FL", "osm ties", budget_s=3600, osm_budget=1200, py=PY)
    p = B.plan("FL", "osm ties", budget_s=2580, osm_budget=1200, py=PY)
    assert "--osm-budget" in p.cmds[0].argv
    assert B.plan("FL", "osm ties", py=PY).cmds                        # the defaults (1500 and 1200) are within it
    assert B.plan("FL", "waters ties", budget_s=3600, osm_budget=1200, py=PY).cmds   # no osm step: the module's 180


def test_steps_resolve_the_restored_outlines_from_pipeline(tmp_path):
    """The batch names the outlines' folder relative to pipeline/ (../../openboatlaunch/out/water): from the steps'
    cwd that is the folder state_paths.py unpack-obl restores beside the checkout, and build/status.py reads it."""
    import os
    root = repo(tmp_path)
    water = obl_fixture(tmp_path)
    (root / "pipeline").mkdir()
    p = B.plan("NC", "ties", py=PY, root=root)
    env = p.cmds[0].env
    assert env == {"OBL_WATER_DIR": "../../openboatlaunch/out/water"} and p.cmds[0].cwd == "pipeline"
    assert (root / p.cmds[0].cwd / env["OBL_WATER_DIR"]).resolve() == water.resolve()
    sp = sys.modules["state_paths"]
    assert sp.OBL_OUT.parent.parent == ROOT.parent                    # the real checkout's sibling, as in the runner
    code = ("from build import status as S;g=S.water_geometry('lake-wheeler-nc');"
            "print(S.OBL_WATER_DIR.resolve(), g.geom_type if g is not None else None)")
    py = str(ROOT / "pipeline/.venv/bin/python") if (ROOT / "pipeline/.venv").exists() else sys.executable
    base = {k: v for k, v in os.environ.items() if k != "OBL_WATER_DIR"}
    r = subprocess.run([py, "-c", code], cwd=root / "pipeline", text=True, capture_output=True,
                       env={**base, **env, "PYTHONPATH": str(ROOT / "pipeline")})
    assert r.stdout.strip() == f"{water.resolve()} Polygon", r.stderr


def test_hourly_default_is_the_folder_unpack_obl_restores():
    """The hourly refresh sets no OBL_WATER_DIR: build/status.py's default (from its own file, not the cwd) is
    state_paths.py's OBL_OUT/water, where the refresh restores the object."""
    import os
    sp_spec = importlib.util.spec_from_file_location("state_paths", ROOT / "scripts" / "state_paths.py")
    SP = importlib.util.module_from_spec(sp_spec)
    sys.modules["state_paths"] = SP
    sp_spec.loader.exec_module(SP)
    py = str(ROOT / "pipeline/.venv/bin/python") if (ROOT / "pipeline/.venv").exists() else sys.executable
    base = {k: v for k, v in os.environ.items() if k != "OBL_WATER_DIR"}
    for cwd in (ROOT, ROOT / "pipeline"):
        r = subprocess.run([py, "-c", "import sys;sys.path.insert(0,'pipeline');sys.path.insert(0,'.');"
                            "from build import status as S;print(S.OBL_WATER_DIR)"], cwd=cwd, text=True,
                           capture_output=True, env=base)
        assert r.stdout.strip() == str(SP.OBL_OUT / "water"), r.stderr


@pytest.mark.parametrize("snapshot", ["none", "partial"])
def test_extract_refuses_a_snapshot_without_the_state_and_keeps_the_file(tmp_path, snapshot, capsys):
    """A snapshot with no NC record, or far fewer than the extract on file, would empty or cut data/waters-nc.json:
    the extract refuses before writing and the steps after it are not run."""
    root = repo(tmp_path)
    write(root, "data/waters-nc.json", {"state": "NC", "source": "openboatlaunch out/water snapshot 2026-11-02",
                                        "waters": [{"slug": f"w{i}-nc", "state": "NC"} for i in range(5)]})
    water = obl_fixture(tmp_path)
    for f in water.glob("*-nc.json"):
        if snapshot == "none" or f.name.startswith("haw"):
            f.unlink()
    before = (root / "data/waters-nc.json").read_text()
    p = B.plan("NC", "extract ties", py=sys.executable, root=root)
    p.cmds[1] = B.Cmd("ties", fake_step("print('never')"))
    assert B.run(p, tmp_path / "out", root=root) == 1
    s = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert s["not_run"] == ["ties"]
    assert ("holds no NC water record" if snapshot == "none" else "1 NC water files") in s["results"][0]["counts"][0]
    assert (root / "data/waters-nc.json").read_text() == before
    assert "never" not in capsys.readouterr().out


def test_new_england_file_does_not_block_nebraska_extract(tmp_path):
    """New England's records are data/waters-new-england.json, so Nebraska's data/waters-ne.json is free to be written."""
    root = repo(tmp_path)
    write(root, "data/receiving-waters-national.json", {"states": {"NE": {"waters": []}}})
    write(root, "data/waters-new-england.json", {"source": "New England", "count": 0, "waters": []})
    assert not (root / "data/waters-ne.json").exists()
    p = B.plan("NE", "extract", py=PY, root=root)
    assert p.cmds[0].step == "extract" and p.cmds[0].argv[-1] == "../data/waters-ne.json"


def test_obl_check_refuses_another_states_file(tmp_path):
    """Nebraska's obl-check never reads New England's data/waters-ne.json as Nebraska's extract."""
    root = repo(tmp_path)
    write(root, "data/receiving-waters-national.json", {"states": {"NE": {"waters": []}}})
    write(root, "data/waters-ne.json", {"source": "openboatlaunch out/water snapshot 2026-11-01",
                                        "waters": [{"slug": "charles-river-ma", "state": "MA"}]})
    ok, lines = B.obl_check("NE", root)
    assert not ok and "not NE's openboatlaunch extract" in lines[0]


def test_a_great_lakes_state_has_its_lakes_cut_after_its_waters_are_rebuilt():
    """2026-11-06 review of Illinois's gates: the NHD pass rebuilds Lake Michigan's Illinois record as the lake's whole
    United States part; the batch cuts it back to the state's waters before the ties (and the gates' lake entries)."""
    cut = ["/py", "-I", "scripts/cut_lakes_to_state_waters.py", "--state", "IL"]
    p = B.plan("IL", "waters ties", py=PY)
    assert [c.step for c in p.cmds] == ["waters", "cut", "ties"] and p.cmds[1].argv == cut and p.cmds[1].cwd == "."
    assert [c.step for c in B.plan("IL", "waters osm names ties", budget_s=600, py=PY, osm_budget=600).cmds] == ["osm", "names", "cut", "ties"]
    assert [c.step for c in B.plan("IL", "names", py=PY).cmds] == ["names", "cut"]
    assert [c.step for c in B.plan("IL", "ties", py=PY).cmds] == ["ties"]           # nothing rebuilt: nothing to cut
    assert [c.step for c in B.plan("NC", "waters ties", py=PY).cmds] == ["waters", "ties"]     # no Great Lake
    assert B.count_lines("cut", ["lake-michigan-il: 57137.2 km2 -> 4055.3 km2, bbox [1]", "1 records cut; problems left: 0",
                                 "noise"]) == ["lake-michigan-il: 57137.2 km2 -> 4055.3 km2, bbox [1]",
                                               "1 records cut; problems left: 0"]
