"""scripts/state_batch.py (the per-state water batch helper) and the two workflows that keep state in R2: step and
input validation, the commands a plan runs (its dry run), obl-check, the run summary and pull-request body, the
privacy scan, the publish to batch/<st>-<date>, and the workflow files loaded as YAML.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import stat
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
    assert out == ["[waters] (cd pipeline && /py -m ingest.waters_from_nhd --state NC --budget-s 1500 --max-requests 1000)",
                   "[ties] (cd pipeline && /py -m ingest.outfall_waters --state NC)"]


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
    write(root, "data/outfalls-ne.json", {"outfalls": []})
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
    assert set(inputs) == {"state", "steps", "budget_s", "max_requests"}
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
    assert steps[sr]["if"] == "success()" and steps[sb]["if"] == "success()"
    assert "state_paths.py pack raw-cache.tar.gz" in steps[sr]["run"]
    assert "state_paths.py unpack raw-cache.tar.gz" in steps[rr]["run"]
    assert "check-size build.tar.gz" in steps[sb]["run"]
