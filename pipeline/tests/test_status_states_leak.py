"""The status build's cached live states never cross from one test to the next (tests/conftest.py): the failing
order of 2026-11-16 (the rain caution tests, then the rain grid's registry test) run in a fresh process."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_the_rain_grid_registry_test_passes_after_the_rain_caution_tests():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "tests/test_rain_likely.py::test_heavy_rain_colours_the_permittees_reach_river_and_pond_yellow",
                        "tests/test_rain_grid.py::test_the_registry_outfalls_join_and_new_jersey_permits_on_the_shared_site_stay_there"],
                       cwd=HERE.parent, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "2 passed" in r.stdout

