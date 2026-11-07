#!/usr/bin/env python3
"""The per-state water batch (docs/national-approach.md §4.3 and §7 item 5 in the site repository): the steps that
build a state's water records and tie its outfalls to them, run by .github/workflows/state-build.yml or by hand, and
the pull request that carries the changed registry files to a person for review.

    python scripts/state_batch.py plan    --state NC [--steps "waters ties"] [--budget-s 1500] [--max-requests 1000]
                                          [--osm-budget 1200] [--obl-dir DIR]
                                          print the commands the steps run, in order, and nothing else (a dry run)
    python scripts/state_batch.py run     (the same options) [--dry-run] [--out DIR]
                                          run them; each step's output is shown and kept in DIR/<step>.log (default
                                          data/build/batch/<st>/); a failed step stops the ones after it; writes
                                          DIR/summary.json and DIR/pr-body.md (the counts the steps printed)
    python scripts/state_batch.py obl-check --state NC
    python scripts/state_batch.py files   --state NC     the registry files the steps changed (the pull request's)
    python scripts/state_batch.py scan    --state NC [--text FILE ...] [--require-blocklist]
                                          the privacy scan: every string new in those files (and the given texts)
                                          against the e-mail and phone patterns (common.EMAIL_RE, PHONE_RE) and the
                                          private name blocklist (data/build/name-blocklist.json, restored with the
                                          build state); prints where, never what
    python scripts/state_batch.py publish --state NC --body FILE [--date YYYY-MM-DD] [--dry-run]
                                          the scan above (the blocklist required), then commit those files on a branch batch/<st>-<date> from the checked-out commit,
                                          push it (replacing a branch of that name: the files are rebuilt from main and
                                          the caches each time) and open the pull request, or update the open one

Steps (--steps, space- or comma-separated; run in this order whatever order they are given in):
  extract    python -m ingest.obl_waters --state <ST> [--from-api] --from <obl-dir> --out ../data/waters-<st>.json:
             with OBL_API_KEY set, the state's records from openboatlaunch's API (states/{ST}/waters, paged; the
             folder below is the fallback when the API cannot be read), else
             the state's openboatlaunch water records from the snapshot the workflows restore from R2
             (state/obl-water.tar.gz, scripts/state_paths.py unpack-obl, into ../openboatlaunch/out beside the
             checkout); the snapshot date comes from its out/meta.json. Refused at run time, before anything is
             written, when the folder is not there (the object is not in R2 yet) or meta.json gives no date (a source
             line is never written with an unknown date), and when the snapshot holds no record of the state or
             fewer than half the records of the extract on file (a partial snapshot never empties or cuts it).
             data/waters-<st>.json is then one of the pull request's
             files. data/receiving-waters-national.json is not regenerated here (obl-check says when it predates the
             extract).
  obl-check  the state's openboatlaunch extract (data/waters-<st>.json, ingest/obl_waters.py) is on file, and the
             national target list's 'record' rows find their slugs; fails when the extract is missing (the NHD pass
             would build records openboatlaunch already has). Reads files only.
  registry   scripts/match_outfalls.py for the state (DWW_STATES=<ST>): the CSO rows of data/outfalls-us.json from EPA's
             CSO inventory (--national --append) and the plant rows of data/outfalls-plants-us.json (--plants). Needs
             EPA's ALL_CSO_DOWNLOADS.csv (--cso-csv or DWW_CSO_CSV) and an openboatlaunch out/water snapshot (--obl-dir
             or OBL_WATER_DIR), which the Actions runner does not have, and needs `ties` after it (a rerun drops the
             ties until ingest.outfall_waters runs again). Not for the twelve states the regional files hold.
  waters     python -m ingest.waters_from_nhd --state <ST> --budget-s S --max-requests N (from pipeline/): the state's
             receiving waters from data/receiving-waters-national.json; stops before a request at the budget, writes
             what it built, and the next run resumes from the raw cache (its own OSM, other-places and NHD
             high-resolution budgets come on top of S).
  osm        the waters step with OpenStreetMap's pass given --osm-budget seconds (60 to 1200, default 1200) instead
             of the module's 180: python -m ingest.waters_from_nhd --state <ST> ... --osm-budget O (S + O at most
             3,780, the batch's worst case before this step, so the job keeps inside the workflow's 120 minutes and
             saves its caches). With `waters`
             listed too they run as this one command. The OSM pass runs once the NHD pass has finished inside its
             budget (a resumed run answers from the raw cache, free); the Overpass answers are cached per state query
             (data/raw/nhd-waters/osm-state/, in the saved raw caches), so the names a run did not reach are asked by
             the next dispatch. Overpass answers GitHub's runners; the cloud sessions cannot reach it.
  names      python -m ingest.waters_from_nhd --names ../research/<st>/receiving-waters-missing.json --state <ST>
             --budget-s S --max-requests N (from pipeline/): the receiving-water names the state's reports give (the
             names file, its rows with their places), each built from NHD at the reports' places or given its reason;
             the file is rewritten to what is still missing and data/waters-nhd.json gains the records (the module's
             docstring, "Report names"). The waters step reads only data/receiving-waters-national.json, which
             holds the outfalls' waters, not the reports': a water only reports name (Georgia's Nancy Creek and Utoy
             Creek, 2026-11-04 final audit P1-1) needs this step. Refused when the state has no names file. With
             waters or osm in the same dispatch the two passes and their OpenStreetMap budgets (the module's 180 s
             here) share NET_BUDGET_MAX.
  ties       python -m ingest.outfall_waters --state <ST>: every outfall row of the state tied to its record or a
             stated reason (counts in data/build/outfall-waters-<st>.json).
  cut        (not a step to choose: added after waters, osm or names for a state on the Great Lakes, GREAT_LAKES_STATES,
             before ties) python -I scripts/cut_lakes_to_state_waters.py --state <ST>: the NHD pass rebuilds a Great
             Lake's record of the state as the lake's whole United States part (Lake Michigan for Illinois: 57,137 km2);
             the cut brings it back to the state's own waters in the lake, which the shoreline stretches walk and the
             outfall ties and the reversal gates' lake entries (data/outfalls-il.json) are measured against
             (2026-11-06 review of Illinois's gates).
The NHD, OSM and tie steps run with OBL_WATER_DIR set to the openboatlaunch out/water folder (--obl-dir, else
OBL_WATER_DIR, else the restored ../openboatlaunch/out/water): build/status.py water_geometry reads each record's
outline there, which ingest.outfall_waters measures a point against and ingest.waters_from_nhd checks a duplicate
with; without it those rows are held "until a run with the record's outline".
Refused: reaches (build/reaches.py has no state scope: it traces the open outfalls of the live states, and the hourly
refresh already does so within its budget; a state batch needs a --state option there first).

Nothing here prints a file's contents beyond the steps' own output and the counts. Standard library only (scan reads
the redactor's blocklist scan from pipeline/build/redact.py).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STEPS = ("extract", "obl-check", "registry", "waters", "osm", "names", "ties")          # the run order
DEFAULT_STEPS = ("waters", "ties")
REFUSED = {
    "reaches": "build/reaches.py has no state scope (it traces the open outfalls of the live states, and the hourly "
               "refresh does that within its budget); a per-state reaches batch needs a --state option there first",
}
BUDGET_S = (60, 3_600)
MAX_REQUESTS = (1, 20_000)
OSM_BUDGET = (60, 1_200)
DEFAULT_OSM_BUDGET = 1_200
# budget_s and the OSM pass's budget together, with the osm step, at most the batch's worst case before the osm step
# existed (budget_s 3,600 and the module's 180 s OSM pass): the build's other budgets (NHD high resolution 900 s, other
# places 120 s), a query begun inside a budget, the loading and the write come on top, and a job past the workflow's
# 120 minutes is cancelled, so its raw caches are never saved and its pull request never opened
NET_BUDGET_MAX = 3_600 + 180
MODULE_OSM_BUDGET = 180      # ingest.waters_from_nhd's own --osm-budget default (the waters and names steps)
OBL_KEY = "state/obl-water.tar.gz"
REGIONAL_FILES = ("outfalls-new-england.json", "outfalls-mid-atlantic.json")
# the states whose water records hold a Great Lake: after a pass that rebuilds the state's records (waters, osm, names)
# the batch cuts those lakes back to the state's waters (scripts/cut_lakes_to_state_waters.py), before the ties
GREAT_LAKES_STATES = ("IL", "IN", "MI", "MN", "NY", "OH", "PA", "WI")
REBUILDS_WATERS = ("waters", "osm", "names")
CSO_ZIP_URL = "https://echo.epa.gov/files/echodownloads/ALL_CSO_downloads.zip"
LINE_MAX = 400               # a printed count line kept in the summary, at most this long
LINES_PER_STEP = 40
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
# the lines of each step's output that carry its counts (all of obl-check's; registry: its last lines)
COUNT_LINES = {
    "obl-check": re.compile(r"\S"),
    "waters": re.compile(r"^(state build |EPA reach index:|\d+ records -> |NOT WRITTEN|NHD pass done|unknown state code|"
                         r"targets collected|stopped)"),
    "ties": re.compile(r"^([A-Z]{2}|ALL): |^written: "),
    "names": re.compile(r"^(report names |\d+ records -> |NOT WRITTEN|--names needs|PROBLEM )"),
    "extract": re.compile(r"^obl_waters: "),
    "cut": re.compile(r"records cut|km2 -> "),
}
COUNT_LINES["osm"] = re.compile(COUNT_LINES["waters"].pattern + r"|^\s+[A-Z]{2}: \d+ names")


class Refused(ValueError):
    """An input the batch will not run with; the message says why."""


@dataclass
class Cmd:
    step: str
    argv: list[str]
    cwd: str = "."                       # relative to the repository root
    env: dict = field(default_factory=dict)

    def shown(self) -> str:
        env = " ".join(f"{k}={v}" for k, v in self.env.items())
        cd = f"(cd {self.cwd} && " if self.cwd != "." else ""
        return f"{cd}{env + ' ' if env else ''}{' '.join(_q(a) for a in self.argv)}{')' if cd else ''}"


def _q(a: str) -> str:
    return a if re.fullmatch(r"[\w./:=,@+-]+", a) else "'" + a.replace("'", "'\\''") + "'"


def say(msg: str) -> None:
    print(f"state-batch: {msg}", flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- inputs

def national_states(root: Path = ROOT) -> dict:
    return (read_json(root / "data" / "receiving-waters-national.json", {}) or {}).get("states") or {}


def valid_state(code: str, root: Path = ROOT) -> str:
    st = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", st):
        raise Refused(f"state must be a two-letter code, not {code!r}")
    if st not in national_states(root):
        raise Refused(f"{st} is not in data/receiving-waters-national.json (no targets to build)")
    return st


def parse_steps(text) -> list[str]:
    words = [w for w in re.split(r"[\s,]+", " ".join(text) if isinstance(text, (list, tuple)) else str(text or ""))
             if w]
    if not words:
        raise Refused(f"no steps given (choose from: {' '.join(STEPS)})")
    for w in words:
        if w in REFUSED:
            raise Refused(f"step {w!r} is not run here: {REFUSED[w]}")
        if w not in STEPS:
            raise Refused(f"unknown step {w!r} (choose from: {' '.join(STEPS)})")
    steps = [s for s in STEPS if s in words]
    if "registry" in steps and "ties" not in steps:
        raise Refused("registry rewrites the outfall rows and drops their ties until ingest.outfall_waters runs again: "
                      "add ties")
    return steps


def bounded(name: str, v, lo_hi) -> int:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise Refused(f"{name} must be a whole number, not {v!r}") from None
    lo, hi = lo_hi
    if not lo <= n <= hi:
        raise Refused(f"{name} must be between {lo} and {hi}, not {n}")
    return n


def regional_states(root: Path = ROOT) -> set[str]:
    out = set()
    for n in REGIONAL_FILES:
        for r in (read_json(root / "data" / n, {}) or {}).get("outfalls") or []:
            out.add(str(r.get("state") or r.get("npdes_permit", "")[:2]).upper())
    return out


def pipeline_python(root: Path = ROOT) -> str:
    venv = root / "pipeline" / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


@dataclass
class Plan:
    state: str
    steps: list[str]
    budget_s: int
    max_requests: int
    cmds: list[Cmd]
    osm_budget: int = DEFAULT_OSM_BUDGET
    obl_dir: Path | None = None          # openboatlaunch's out/water folder the steps read


def obl_water_dir(obl_dir=None, root: Path = ROOT) -> tuple[Path, str]:
    """(the out/water folder, how the pipeline/ steps name it): --obl-dir, else OBL_WATER_DIR, else the sibling
    ../openboatlaunch/out/water the workflows restore state/obl-water.tar.gz into (named relative to pipeline/, so
    no machine's path is printed into a log or a pull request)."""
    given = obl_dir or os.environ.get("OBL_WATER_DIR")
    if given:
        p = Path(given).resolve()
        return p, str(p)
    return root.parent / "openboatlaunch" / "out" / "water", "../../openboatlaunch/out/water"


def plan(state, steps, budget_s=1500, max_requests=1000, cso_csv=None, obl_dir=None, py=None,
         root: Path = ROOT, osm_budget=DEFAULT_OSM_BUDGET) -> Plan:
    st = valid_state(state, root)
    steps = parse_steps(steps)
    budget = bounded("budget_s", budget_s, BUDGET_S)
    maxreq = bounded("max_requests", max_requests, MAX_REQUESTS)
    osm = bounded("osm_budget", osm_budget, OSM_BUDGET)
    if "osm" in steps and budget + osm > NET_BUDGET_MAX:
        raise Refused(f"budget_s {budget} and osm_budget {osm} together are {budget + osm} s, over {NET_BUDGET_MAX} s "
                      "(with the build's other budgets, the job would risk the workflow's 120 minutes, and a "
                      f"cancelled job saves nothing): lower one, for example budget_s {NET_BUDGET_MAX - osm} with "
                      f"osm_budget {osm}")
    if "names" in steps and ("waters" in steps or "osm" in steps):
        both = 2 * budget + MODULE_OSM_BUDGET + (osm if "osm" in steps else MODULE_OSM_BUDGET)
        if both > NET_BUDGET_MAX:
            raise Refused(f"names runs a second NHD pass: with {'osm' if 'osm' in steps else 'waters'}, budget_s "
                          f"{budget} twice and the OpenStreetMap budgets come to {both} s, over {NET_BUDGET_MAX} s; "
                          "lower budget_s, or dispatch names on its own")
    names_file = f"research/{st.lower()}/receiving-waters-missing.json"
    if "names" in steps and not (root / names_file).is_file():
        raise Refused(f"names: {names_file} is not on file (the state's report names; scripts/ga_report_water_names.py "
                      "and scripts/il_report_water_names.py build it from the reports)")
    py = py or pipeline_python(root)
    water, water_arg = obl_water_dir(obl_dir, root)
    outlines = {"OBL_WATER_DIR": water_arg}
    cmds: list[Cmd] = []
    last_rebuild = next((s for s in reversed(steps) if s in REBUILDS_WATERS), None)
    for s in steps:
        if s == "extract":
            have = read_json(root / "data" / f"waters-{st.lower()}.json")
            if have is not None and not (isinstance(have, dict) and str(have.get("state") or "").upper() == st):
                raise Refused(f"extract: data/waters-{st.lower()}.json is another file (not {st}'s openboatlaunch "
                              "extract, e.g. a leftover New England regional file), which the extract "
                              "would overwrite; that state's extract needs another file name first")
            # with the API key here, the state's list from openboatlaunch's API (states/{ST}/waters, paged), the
            # restored folder the fallback; without it, the folder
            api = ["--from-api"] if os.environ.get("OBL_API_KEY") else []
            cmds.append(Cmd(s, [py, "-m", "ingest.obl_waters", "--state", st, *api, "--from", water_arg,
                                "--out", f"../data/waters-{st.lower()}.json"], cwd="pipeline"))
        elif s == "obl-check":
            cmds.append(Cmd(s, [py, "scripts/state_batch.py", "obl-check", "--state", st]))
        elif s == "registry":
            cso_csv = cso_csv or os.environ.get("DWW_CSO_CSV")
            obl_dir = obl_dir or os.environ.get("OBL_WATER_DIR")
            missing = []
            if not cso_csv or not Path(cso_csv).is_file():
                missing.append(f"EPA's CSO inventory ALL_CSO_DOWNLOADS.csv (from {CSO_ZIP_URL}; --cso-csv or DWW_CSO_CSV)")
            if not obl_dir or not Path(obl_dir).is_dir():
                missing.append("an openboatlaunch out/water snapshot (--obl-dir or OBL_WATER_DIR)")
            if missing:
                raise Refused("registry needs " + " and ".join(missing) + "; the Actions runner has no CSO inventory, "
                              "so run this step where it is and dispatch the others")
            if st in regional_states(root):
                raise Refused(f"registry: {st}'s rows are in the regional files ({', '.join(REGIONAL_FILES)}), which "
                              "the national match never writes")
            env = {"DWW_STATES": st}
            cmds.append(Cmd(s, [py, "-I", "scripts/match_outfalls.py", str(cso_csv), str(obl_dir),
                                "data/outfalls-us.json", "--national", "--append"], env=env))
            cmds.append(Cmd(s, [py, "-I", "scripts/match_outfalls.py", "data/outfalls-plants-us.json", str(obl_dir),
                                "data/outfalls-plants-us.json", "--plants"], env=dict(env)))
        elif s == "waters" and "osm" not in steps:        # with osm: one build, the osm step's command
            cmds.append(Cmd(s, [py, "-m", "ingest.waters_from_nhd", "--state", st, "--budget-s", str(budget),
                                "--max-requests", str(maxreq)], cwd="pipeline", env=dict(outlines)))
        elif s == "osm":
            cmds.append(Cmd(s, [py, "-m", "ingest.waters_from_nhd", "--state", st, "--budget-s", str(budget),
                                "--max-requests", str(maxreq), "--osm-budget", str(osm)], cwd="pipeline",
                            env=dict(outlines)))
        elif s == "names":
            cmds.append(Cmd(s, [py, "-m", "ingest.waters_from_nhd", "--names", f"../{names_file}", "--state", st,
                                "--budget-s", str(budget), "--max-requests", str(maxreq)], cwd="pipeline",
                            env=dict(outlines)))
        elif s == "ties":
            cmds.append(Cmd(s, [py, "-m", "ingest.outfall_waters", "--state", st], cwd="pipeline", env=dict(outlines)))
        if s == last_rebuild and st in GREAT_LAKES_STATES:
            cmds.append(Cmd("cut", [py, "-I", "scripts/cut_lakes_to_state_waters.py", "--state", st]))
    return Plan(st, steps, budget, maxreq, cmds, osm, water)


def extract_ready(obl_dir: Path | None, state: str | None = None, root: Path = ROOT) -> tuple[bool, str]:
    """Whether the extract step can run: the snapshot folder is here, its out/meta.json gives a date, and (with state)
    it holds the state's records: none, or fewer than half the records of the extract on file, is a partial snapshot,
    which would empty or cut data/waters-<st>.json. With OBL_API_KEY set the extract reads openboatlaunch's API
    (ingest.obl_waters --from-api refuses a partial answer itself), so only the state code matters here."""
    if os.environ.get("OBL_API_KEY"):
        return True, ""
    if obl_dir is None or not Path(obl_dir).is_dir():
        return False, ("extract: no openboatlaunch snapshot (out/water) beside the checkout or at --obl-dir: "
                       f"{OBL_KEY} is not in R2 (or was not restored). Upload it once from a "
                       "machine with the openboatlaunch checkout (the command is in README.md, the batch section), "
                       "then dispatch again")
    try:
        m = json.loads((Path(obl_dir).parent / "meta.json").read_text())
        date = str(m.get("built") or m.get("generated") or m.get("updated") or "")[:10]
    except (OSError, ValueError, AttributeError):
        date = ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return False, ("extract: the openboatlaunch snapshot has no snapshot date (out/meta.json missing or without "
                       f"built, generated or updated): the source line would be undated; pack {OBL_KEY} again with "
                       "meta.json")
    if state:
        st = state.lower()
        files = sum(1 for _ in Path(obl_dir).glob(f"*-{st}.json"))
        have = read_json(root / "data" / f"waters-{st}.json")
        on_file = len(have.get("waters") or []) if isinstance(have, dict) and isinstance(have.get("waters"), list) else 0
        if not files:
            return False, (f"extract: the openboatlaunch snapshot {date} holds no {state.upper()} water record "
                           f"(*-{st}.json): nothing to extract, and data/waters-{st}.json is left as it is")
        if files * 2 < on_file:
            return False, (f"extract: the openboatlaunch snapshot {date} holds {files} {state.upper()} water files and "
                           f"data/waters-{st}.json {on_file} records: a partial snapshot would cut the extract on "
                           f"file, which is left as it is; pack {OBL_KEY} again from a whole out/water")
    return True, ""


# ---------------------------------------------------------------- obl-check

def water_slugs(root: Path = ROOT) -> dict[str, str]:
    """{slug: state} of every water record on file (data/waters-*.json, openboatlaunch extracts, waters-extra and
    waters-nhd), slug_aliases included."""
    out: dict[str, str] = {}
    for p in sorted((root / "data").glob("waters-*.json")):
        d = read_json(p)
        for w in (d.get("waters") if isinstance(d, dict) else d) or []:
            if isinstance(w, dict) and w.get("slug"):
                st = str(w.get("state") or "").upper()
                for s in [w["slug"]] + [a for a in w.get("slug_aliases") or [] if isinstance(a, str)]:
                    out.setdefault(s, st)
    return out


def obl_check(state: str, root: Path = ROOT) -> tuple[bool, list[str]]:
    st = valid_state(state, root)
    lines: list[str] = []
    ext = root / "data" / f"waters-{st.lower()}.json"
    d = read_json(ext)
    # the file must be this state's extract: a regional file under this state's code (New England's was data/waters-ne.json until 2026-11-07) is not Nebraska's
    if not isinstance(d, dict) or not isinstance(d.get("waters"), list) or str(d.get("state") or "").upper() != st:
        if isinstance(d, dict) and str(d.get("state") or "").upper() != st:
            lines.append(f"{st}: data/waters-{st.lower()}.json is not {st}'s openboatlaunch extract (its state is "
                         f"{d.get('state') or 'not given'}); {st}'s extract needs another file name first")
            return False, lines
        lines.append(f"{st}: no openboatlaunch extract at data/waters-{st.lower()}.json. Add the extract step "
                     f"before this one (python -m ingest.obl_waters --state {st} --from the snapshot restored from "
                     f"{OBL_KEY}), then python3 -I scripts/gen_receiving_waters.py; then the NHD pass")
        return False, lines
    n = len(d["waters"])
    lines.append(f"{st}: openboatlaunch extract data/waters-{st.lower()}.json: {n} records ({d.get('source') or 'no source line'})")
    slugs = water_slugs(root)
    on_file = sum(1 for s in slugs.values() if s == st)
    s = national_states(root).get(st) or {}
    rows = s.get("waters") or []
    rec = [r for r in rows if r.get("define_by") == "record"]
    lost = [r for r in rec if r.get("water_slug") not in slugs]
    lines.append(f"{st}: national target list: {len(rows)} named receiving waters, {len(rec)} with a record, "
                 f"{len(lost)} of those whose slug no water file holds (the NHD pass builds them as reach or point rows)")
    listed = (s.get("summary") or {}).get("water_records_on_file")
    if isinstance(listed, int) and listed < on_file:
        lines.append(f"{st}: the national list counted {listed} water records on file and {on_file} are on file now: "
                     "it predates them; python3 -I scripts/gen_receiving_waters.py refreshes it (a national file, "
                     "not part of this batch)")
    return True, lines


# ---------------------------------------------------------------- run

def _stream(cmd: Cmd, root: Path, log: Path) -> tuple[int, list[str]]:
    env = {**os.environ, **cmd.env, "PYTHONUNBUFFERED": "1"}
    lines: list[str] = []
    with open(log, "w") as fh:
        fh.write(f"$ {cmd.shown()}\n")
        p = subprocess.Popen(cmd.argv, cwd=root / cmd.cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        assert p.stdout is not None
        for line in p.stdout:
            sys.stdout.write(line)
            fh.write(line)
            lines.append(line.rstrip("\n"))
        rc = p.wait()
    sys.stdout.flush()
    return rc, lines


def count_lines(step: str, lines: list[str]) -> list[str]:
    rx = COUNT_LINES.get(step)
    got = [x for x in lines if rx.search(x)] if rx else lines[-15:]
    return [x if len(x) <= LINE_MAX else x[:LINE_MAX] + " ..." for x in got][:LINES_PER_STEP]


def state_counts(st: str, since: str, root: Path = ROOT) -> dict:
    """The structured counts the steps wrote: data/waters-nhd.json stats.state_builds.<ST> and
    data/build/outfall-waters-<st>.json, each only when written by this run (built >= since)."""
    out = {}
    w = ((read_json(root / "data" / "waters-nhd.json", {}) or {}).get("stats") or {}).get("state_builds", {}).get(st)
    if isinstance(w, dict) and str(w.get("built") or "") >= since:
        run = w.get("run") or {}
        out["waters"] = {k: w.get(k) for k in ("targets", "targets_by_define_by", "targets_mapped", "targets_mapped_by",
                                                "targets_failed", "records", "records_by_kind", "failed_reasons")}
        out["waters"]["network_requests"] = run.get("network_requests")
        out["waters"]["stopped"] = run.get("stopped")
        if run.get("osm"):
            out["waters"]["osm"] = run["osm"]
    t = read_json(root / "data" / "build" / f"outfall-waters-{st.lower()}.json", {}) or {}
    if str(t.get("built") or "") >= since and (t.get("counts") or {}).get(st):
        out["ties"] = {"counts": t["counts"][st], "files_written": t.get("files_written") or []}
    return out


def _registry_counts(st: str, load) -> dict:
    """The state's standing in the registry files, read through load(path) (the working tree or the commit)."""
    nhd = load("data/waters-nhd.json") or {}
    rows = [t for t in nhd.get("targets") or [] if str(t.get("state") or "").upper() == st]
    out = {"NHD water records": sum(1 for w in nhd.get("waters") or [] if str(w.get("state") or "").upper() == st),
           "receiving-water targets": len(rows),
           "targets with a record": sum(1 for t in rows if t.get("slugs"))}
    n = tied = 0
    for f in ("data/outfalls-us.json", "data/outfalls-plants-us.json", f"data/outfalls-{st.lower()}.json"):
        for r in (load(f) or {}).get("outfalls") or []:
            if str(r.get("state") or "").upper() == st:
                n += 1
                tied += bool(r.get("water_slug"))
    out["outfall rows"] = n
    out["outfall rows tied to a record"] = tied
    return out


def before_after(st: str, root: Path = ROOT) -> dict:
    """{what: [at the checked-out commit, now]} for the state: water records, targets, ties (the whole state, not
    just this run's part)."""
    def now(f):
        return read_json(root / f)

    def head(f):
        t = git(root, "show", f"HEAD:{f}", check=False).stdout
        try:
            return json.loads(t) if t else None
        except ValueError:
            return None
    a, b = _registry_counts(st, head), _registry_counts(st, now)
    return {k: [a[k], b[k]] for k in a}


def run(p: Plan, out_dir: Path | None = None, dry_run: bool = False, root: Path = ROOT) -> int:
    if dry_run:
        for c in p.cmds:
            print(f"[{c.step}] {c.shown()}")
        return 0
    out_dir = out_dir or root / "data" / "build" / "batch" / p.state.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    started = now_iso()
    results = []
    for i, c in enumerate(p.cmds, 1):
        say(f"step {c.step} ({i}/{len(p.cmds)}): {c.shown()}")
        t0 = time.monotonic()
        refused = None
        if c.step == "obl-check":
            ok, lines = obl_check(p.state, root)        # in process: the same code the command line runs
            for x in lines:
                print(x, flush=True)
            (out_dir / f"{c.step}.log").write_text("\n".join(lines) + "\n")
            rc = 0 if ok else 1
        elif c.step == "extract" and not (ready := extract_ready(p.obl_dir, p.state, root))[0]:
            print(f"::error::{ready[1]}", flush=True)
            (out_dir / f"{c.step}.log").write_text(ready[1] + "\n")
            rc, lines, refused = 1, [ready[1]], [ready[1]]
        else:
            rc, lines = _stream(c, root, out_dir / f"{c.step}{'-' + str(i) if c.step == 'registry' else ''}.log")
        results.append({"step": c.step, "command": c.shown(), "exit": rc, "seconds": round(time.monotonic() - t0),
                        "counts": refused or count_lines(c.step, lines)})
        if rc != 0:
            say(f"step {c.step} failed (exit {rc}); the steps after it are not run")
            break
    ok = len(results) == len(p.cmds) and all(r["exit"] == 0 for r in results)
    summary = {"state": p.state, "steps": p.steps, "budget_s": p.budget_s, "max_requests": p.max_requests,
               "osm_budget": p.osm_budget if "osm" in p.steps else None,
               "started": started, "finished": now_iso(), "ok": ok, "results": results,
               "not_run": [c.step for c in p.cmds[len(results):]], "counts": state_counts(p.state, started, root),
               "before_after": before_after(p.state, root), "files": changed_files(p.state, root)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    (out_dir / "pr-body.md").write_text(pr_body(summary))
    say(f"{'all steps ran' if ok else 'stopped at a failed step'}; files changed: {', '.join(summary['files']) or 'none'}; "
        f"summary in {out_dir.relative_to(root) if out_dir.is_relative_to(root) else out_dir}")
    return 0 if ok else 1


# ---------------------------------------------------------------- the pull request

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "the District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
    "VI": "the U.S. Virgin Islands", "GU": "Guam", "AS": "American Samoa", "MP": "the Northern Mariana Islands",
}


def title(st: str, date: str) -> str:
    return f"Water batch: {STATE_NAMES.get(st, st)} ({st}), {date}"


def _fmt(d) -> str:
    return ", ".join(f"{k} {v}" for k, v in (d or {}).items()) or "none"


def pr_body(s: dict) -> str:
    st = s["state"]
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY"):
        run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"
                   f"/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    out = [f"## {title(st, s['started'][:10])}", "",
           f"The per-state water batch (`.github/workflows/state-build.yml`{f', [run]({run_url})' if run_url else ''}): "
           f"steps `{' '.join(s['steps'])}`, budget {s['budget_s']} s, at most {s['max_requests']} requests, "
           + (f"OpenStreetMap budget {s['osm_budget']} s, " if s.get("osm_budget") else "") +
           f"{s['started']} to {s['finished']}. "
           + ("The pipeline state and the raw caches were restored from R2 and the caches saved back, so the next "
              "dispatch resumes where this one stopped." if os.environ.get("GITHUB_ACTIONS") == "true" else
              "Run by hand with `scripts/state_batch.py`, from that machine's caches."), "",
           "| Step | Result | Time |", "|---|---|---|"]
    for r in s["results"]:
        result = "done" if r["exit"] == 0 else f"failed (exit {r['exit']})"
        out.append(f"| `{r['step']}` | {result} | {r['seconds']} s |")
    for n in s.get("not_run") or []:
        out.append(f"| `{n}` | not run (an earlier step failed) | |")
    ba = s.get("before_after") or {}
    if ba:
        out += ["", f"### {STATE_NAMES.get(st, st)} in the registry files", "", "| | main | this branch |", "|---|---|---|"]
        out += [f"| {k} | {v[0]} | {v[1]} |" for k, v in ba.items()]
        out += ["", "Targets this run did not reach keep the rows they had; records it did not visit stay as they were."]
    w = (s.get("counts") or {}).get("waters")
    if w:
        out += ["", f"### This run's water pass (`data/waters-nhd.json`, stats.state_builds.{st})", "",
                f"- Targets: {w.get('targets')} ({_fmt(w.get('targets_by_define_by'))})",
                f"- Mapped: {w.get('targets_mapped')} ({_fmt(w.get('targets_mapped_by'))}); without a record: "
                f"{w.get('targets_failed')}",
                f"- Records built: {w.get('records')} ({_fmt(w.get('records_by_kind'))})",
                f"- Network requests: {w.get('network_requests')}"]
        osm = w.get("osm") or {}
        if osm.get("by_state"):
            q = sum(int(v.get("queries") or 0) for v in osm["by_state"].values())
            sent = sum(int(v.get("sent") or 0) for v in osm["by_state"].values())
            out.append(f"- OpenStreetMap pass: {sent} of {q} queries answered; {osm.get('left_for_next_run') or 0} "
                       "names left for the next run")
        if w.get("stopped"):
            out.append(f"- Stopped at the budget: {w['stopped']}. Dispatch again with the same state to go on.")
        if w.get("failed_reasons"):
            out += ["", "Reasons this run gives for the targets it left without a record:", ""]
            out += [f"- {n} x {k}" for k, n in list(w["failed_reasons"].items())[:15]]
    t = (s.get("counts") or {}).get("ties")
    if t:
        out += ["", f"### Outfall ties (`data/build/outfall-waters-{st.lower()}.json`)", "", f"- {_fmt(t.get('counts'))}"]
    out += ["", "### What the steps printed", ""]
    for r in s["results"]:
        if r["counts"]:
            out += [f"`{r['step']}`:", "", "```text", *r["counts"], "```", ""]
    out += ["### Files", ""] + ([f"- `{f}`" for f in s.get("files") or []] or ["- none"])
    out += ["", "### Review", "",
            "- The records and ties are machine-built from NHDPlus, OpenStreetMap and EPA's identifiers; check the "
            "reasons above and a sample of the new records before merging.",
            f"- Nothing reaches the site until {st} is in `data/rules.json` `live_states`.",
            "- The privacy scan found no e-mail address, phone number or blocklisted name in the new strings of these "
            "files or in this text (`scripts/state_batch.py scan`).",
            "- `reaches` is not part of the batch: `build/reaches.py` has no state scope yet."]
    return "\n".join(out).rstrip() + "\n"


def candidate_files(st: str) -> list[str]:
    s = st.lower()
    return [f"data/waters-{s}.json", "data/waters-nhd.json", "data/outfalls-us.json", "data/outfalls-plants-us.json",
            f"data/outfalls-{s}.json", f"research/{s}/receiving-waters-missing.json"]


def git(root: Path, *args, check=True, capture=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], check=check, text=True,
                          stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)


def changed_files(st: str, root: Path = ROOT) -> list[str]:
    """The pull request's files that differ from the checked-out commit (or are new)."""
    out = git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *candidate_files(st), check=False).stdout
    got = []
    for line in (out or "").splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and path not in got:
            got.append(path)
    return sorted(got)


def other_changes(st: str, root: Path = ROOT) -> list[str]:
    keep = set(candidate_files(st))
    out = git(root, "status", "--porcelain=v1", "--", "data", "docs", "research", "pipeline", "scripts",
              check=False).stdout
    return sorted({ln[3:].strip() for ln in (out or "").splitlines()} - keep)


BATCH_BRANCH = re.compile(r"batch/([a-z]{2}|obl)-\d{4}-\d{2}-\d{2}")      # obl: scripts/obl_extracts.py


def publish_cmds(st: str, date: str, body: Path, files: list[str], gh: str = "gh", label: str | None = None,
                 pr_title: str | None = None) -> dict:
    branch = f"batch/{(label or st).lower()}-{date}"
    # the push replaces the branch (--force): only ever a batch branch of this pattern, never main or another
    if not BATCH_BRANCH.fullmatch(branch):
        raise Refused(f"not a batch branch name: {branch!r}")
    who = ["-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}"]
    ttl = pr_title or title(st, date)
    msg = f"{ttl}: {', '.join(files)}"
    return {
        "branch": branch,
        "commit": [["git", "checkout", "-B", branch],
                   ["git", "add", "--", *files],
                   ["git", *who, "commit", "-m", msg],
                   ["git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}"]],
        "find": [gh, "pr", "list", "--head", branch, "--state", "open", "--json", "number", "--jq", ".[0].number"],
        "edit": lambda n: [gh, "pr", "edit", str(n), "--title", ttl, "--body-file", str(body)],
        "create": [gh, "pr", "create", "--base", "main", "--head", branch, "--title", ttl,
                   "--body-file", str(body)],
    }


def publish(st: str, body: Path, date: str | None = None, dry_run: bool = False, root: Path = ROOT,
            gh: str = "gh", require_blocklist: bool = True) -> int:
    """Commit the changed registry files on batch/<st>-<date>, push, open or update the pull request. The privacy
    scan runs first, over the files and the body; any finding stops it before anything is committed."""
    st = valid_state(st, root)
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise Refused(f"date must be YYYY-MM-DD, not {date!r}")
    files = changed_files(st, root)
    for f in other_changes(st, root):
        say(f"changed but not part of the pull request: {f}")
    if not files:
        say("the steps changed none of the registry files: no branch, no pull request")
        return 0
    if scan(st, [body], require_blocklist, root) != 0:
        print("::error::the privacy scan found something (above): nothing is committed or pushed", flush=True)
        return 1
    c = publish_cmds(st, date, body, files, gh)
    if dry_run:
        for cmd in c["commit"]:
            print(" ".join(_q(a) for a in cmd))
        print(" ".join(_q(a) for a in c["find"]))
        print("then, when a pull request is open for the branch: " + " ".join(_q(a) for a in c["edit"]("<number>")))
        print("else: " + " ".join(_q(a) for a in c["create"]))
        return 0
    for cmd in c["commit"]:
        subprocess.run(cmd, cwd=root, check=True)
    say(f"branch {c['branch']} pushed with {', '.join(files)}")
    found = subprocess.run(c["find"], cwd=root, text=True, stdout=subprocess.PIPE)
    n = (found.stdout or "").strip()
    if found.returncode == 0 and re.fullmatch(r"\d+", n):
        r = subprocess.run(c["edit"](n), cwd=root)
        what = f"pull request #{n} updated"
    else:
        r = subprocess.run(c["create"], cwd=root)
        what = "pull request opened"
    if r.returncode != 0:
        print(f"::error::the branch {c['branch']} is pushed but the pull request was not opened or updated. If the "
              "message above says GitHub Actions may not create pull requests, allow it in the repository's Settings, "
              "Actions, General, Workflow permissions, or open it by hand from the branch.", flush=True)
        return 1
    say(what)
    return 0


# ---------------------------------------------------------------- privacy scan

def strings(o, path="$"):
    """(json path, string) for every key and string value."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield f"{path}.{k}", str(k)
            yield from strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from strings(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o


def _patterns(root: Path):
    """The pipeline's own patterns (this repository's code) and the blocklist of root's data/build."""
    if str(ROOT / "pipeline") not in sys.path:
        sys.path.insert(0, str(ROOT / "pipeline"))
    from common import EMAIL_RE, PHONE_RE  # noqa: E402
    from build.redact import BlockScan, blocklist  # noqa: E402
    names = blocklist(root / "data")
    return EMAIL_RE, PHONE_RE, (BlockScan(names) if names else None)


def scan(st: str, texts: list[Path] = (), require_blocklist: bool = False, root: Path = ROOT,
         files: list[str] | None = None) -> int:
    """Exit 1 when a string new in the changed files (or a line of the texts) has an e-mail address or phone number
    shape or a blocklisted name; prints the file and the place, never the string."""
    email, phone, block = _patterns(root)
    if block is None:
        if require_blocklist:
            print("::error::the private name blocklist (data/build/name-blocklist.json) is not here: it comes with the "
                  "restored build state; without it names cannot be checked, so nothing is published", flush=True)
            return 1
        say("no name blocklist here: e-mail and phone shapes only")
    hits = 0

    def check(where: str, s: str) -> None:
        nonlocal hits
        kinds = [k for k, bad in (("an e-mail address", email.search(s)), ("a phone number", phone.search(s)),
                                  ("a blocklisted name", block.found(s) if block else None)) if bad]
        for k in kinds:
            hits += 1
            print(f"::error::{where}: {k}", flush=True)

    files = changed_files(valid_state(st, root), root) if files is None else files
    for f in files:
        try:
            new = json.loads((root / f).read_text())
        except (OSError, ValueError) as ex:
            print(f"::error::{f}: not readable as JSON ({type(ex).__name__}); not scanned, so not published")
            hits += 1
            continue
        old_text = git(root, "show", f"HEAD:{f}", check=False).stdout
        try:
            old = {s for _, s in strings(json.loads(old_text))} if old_text else set()
        except ValueError:
            old = set()
        n = 0
        for where, s in strings(new):
            if s not in old:
                n += 1
                check(f"{f} {where}", s)
        say(f"{f}: {n} new string(s) scanned")
    for t in texts:
        for i, line in enumerate(Path(t).read_text().splitlines(), 1):
            check(f"{Path(t).name} line {i}", line)
    say(f"privacy scan: {hits} finding(s) in {len(files)} file(s) and {len(texts)} text(s)")
    return 1 if hits else 0


# ---------------------------------------------------------------- command line

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("--state", required=True)
        s.add_argument("--steps", default=" ".join(DEFAULT_STEPS))
        s.add_argument("--budget-s", default="1500")
        s.add_argument("--max-requests", default="1000")
        s.add_argument("--osm-budget", default=str(DEFAULT_OSM_BUDGET))
        s.add_argument("--cso-csv")
        s.add_argument("--obl-dir", help="openboatlaunch's out/water (default OBL_WATER_DIR, else the restored "
                                         "../openboatlaunch/out/water)")
        if name == "run":
            s.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
            s.add_argument("--out")
    for name in ("obl-check", "files"):
        sub.add_parser(name).add_argument("--state", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--state", required=True)
    s.add_argument("--text", action="append", default=[])
    s.add_argument("--require-blocklist", action="store_true")
    s = sub.add_parser("publish")
    s.add_argument("--state", required=True)
    s.add_argument("--body", required=True)
    s.add_argument("--date")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-blocklist-ok", action="store_true",
                   help="by hand only: publish when the name blocklist is not on this machine (shapes still checked)")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("plan", "run"):
            p = plan(a.state, a.steps, a.budget_s, a.max_requests, a.cso_csv, a.obl_dir, osm_budget=a.osm_budget)
            if a.cmd == "plan":
                return run(p, dry_run=True)
            return run(p, Path(a.out) if a.out else None, dry_run=a.dry_run)
        if a.cmd == "obl-check":
            ok, lines = obl_check(a.state)
            print("\n".join(lines))
            return 0 if ok else 1
        if a.cmd == "files":
            print("\n".join(changed_files(valid_state(a.state))))
            return 0
        if a.cmd == "scan":
            return scan(a.state, [Path(t) for t in a.text], a.require_blocklist)
        return publish(a.state, Path(a.body), a.date, a.dry_run, gh=os.environ.get("GH_BIN") or "gh",
                       require_blocklist=not a.no_blocklist_ok)
    except Refused as ex:
        print(f"::error::{ex}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
