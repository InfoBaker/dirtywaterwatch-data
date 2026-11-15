"""Guard: no feed module is left out of `make ingest` silently.

The Makefile's INGEST_MODULES keeps every pipeline/ingest module with a __main__ whose text does not contain the words
"not a feed". Colorado's co_official_notices.py was dropped that way by a docstring heading ("Why a set and not a
feed", integrate/co-mt-wy-ia-id 2026-11-15), so its records would never have been produced. These tests read the list
the Makefile itself computes (`make -n ingest`) and require that every module a source file names, every module that
writes an events file, and every name in the saved feed-cadence table is in it or in EXCLUDED below, with its reason.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "pipeline" / "ingest"

# Modules run by `make` on another path, or never run as a feed; each with its reason.
EXCLUDED = {
    "generic": "ingest.generic runs every fetch block in its own loop of the ingest target",
    "nj_cso_likely": "INGEST_SNAPSHOTS: a snapshot read by build/, run after the feeds; writes no events file",
    "rainfall": "INGEST_EXTRA (make rainfall), after the feeds; writes no events file",
    "waters_from_nhd": "INGEST_SKIP: runs as waters-nhd (INGEST_EXTRA) with a time budget",
    "waters_extra": "INGEST_SKIP: a water-record builder, no events file",
}


def make_ingest_modules() -> set[str]:
    if not shutil.which("make"):
        pytest.skip("make is not installed")
    r = subprocess.run(["make", "--no-print-directory", "-n", "-C", str(ROOT), "ingest", "PYTHON=python"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    m = re.search(r"-m cadence due ((?:ingest\.[a-z0-9_]+\s*)+)\)", r.stdout)
    assert m, "the ingest target's module list was not found in `make -n ingest`"
    mods = {x.split(".", 1)[1] for x in m.group(1).split()}
    assert len(mods) > 50, mods
    return mods


def has_main(name: str) -> bool:
    p = INGEST / f"{name}.py"
    return p.exists() and re.search(r"__name__ == .__main__.", p.read_text()) is not None


@pytest.fixture(scope="module")
def listed() -> set[str]:
    return make_ingest_modules()


def test_the_excluded_list_is_current(listed):
    assert not set(EXCLUDED) & listed, "a module in EXCLUDED is in the ingest list: drop it from EXCLUDED"


def test_every_module_a_source_file_names_is_run(listed):
    named: dict[str, list[str]] = {}
    for f in sorted((ROOT / "data" / "sources").glob("*.yaml")):
        for m in set(re.findall(r"\bingest[/.]([a-z][a-z0-9_]+)(?:\.py)?\b", f.read_text())):
            named.setdefault(m, []).append(f.name)
    missing = {m: fs for m, fs in named.items()
               if has_main(m) and m not in listed and m not in EXCLUDED}
    assert missing == {}, missing


def test_every_module_writing_an_events_file_is_run(listed):
    writers = [p.stem for p in INGEST.glob("*.py")
               if not p.stem.endswith("_test") and has_main(p.stem) and "write_events(" in p.read_text()]
    assert writers
    missing = sorted(m for m in writers if m not in listed and m not in EXCLUDED)
    assert missing == [], missing


def test_every_feed_in_the_saved_cadence_table_is_run(listed):
    path = ROOT / "data" / "build" / "feed-cadence.json"
    try:
        stamps = json.loads(path.read_text())
    except (OSError, ValueError):
        pytest.skip("no saved feed-cadence table here (data/build is restored from R2 in the refresh)")
    names = {k.split(".", 1)[1] for k in stamps if isinstance(k, str) and k.startswith("ingest.")}
    missing = sorted(m for m in names if m not in listed and m not in EXCLUDED)
    assert missing == [], missing


def test_colorados_notice_set_is_in_the_ingest_list(listed):
    assert "co_official_notices" in listed
