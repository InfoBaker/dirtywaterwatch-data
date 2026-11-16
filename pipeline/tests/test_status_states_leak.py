"""A status build run on a test world's rules must not leave its live states behind for the next reader of
status.states() in the same process (2026-11-16: tests/test_rain_grid.py's registry test read only the rain caution
world's states after tests/test_rain_likely.py had run; it failed on main too)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build import status as S  # noqa: E402

HERE = Path(__file__).resolve().parent


def test_a_build_on_other_rules_leaves_the_cached_states_as_it_found_them(monkeypatch):
    from tests.test_rain_likely import NOW, rain_world, wet
    monkeypatch.setattr(S, "_RULES", S.load_rules())
    before = S.states()
    S.build(now=NOW, write=False, **rain_world(values=wet(range(0, 6))))
    assert S.states() == before
    S._STATES = None
    assert S.states() == before


def test_the_rain_grid_registry_test_passes_after_the_rain_caution_tests():
    """The failing order itself, in a fresh process."""
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "tests/test_rain_likely.py::test_heavy_rain_colours_the_permittees_reach_river_and_pond_yellow",
                        "tests/test_rain_grid.py::test_the_registry_outfalls_join_and_new_jersey_permits_on_the_shared_site_stay_there"],
                       cwd=HERE.parent, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "2 passed" in r.stdout
