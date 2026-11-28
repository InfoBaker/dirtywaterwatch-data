"""The registry water audit's data fixes of 2026-11-28 (research/registry/outfall-water-fixes-2026-11-28-applied.csv):
MassDEP crosswalk rows for waters that have records now, the Lower Rouge alias for Dearborn's MiEnviro reports, and
Manistee's town. Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_registry_water_fixes.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import event  # noqa: E402
from ingest import ma_massdep as M  # noqa: E402


@pytest.fixture(scope="module")
def cw():
    return M.load_crosswalk()


@pytest.fixture(scope="module")
def waters():
    return S.load_waters()


@pytest.mark.parametrize("text,town,slug", [
    ("MOUNT HOPE BAY", "FALL RIVER", "mount-hope-bay-ma"),
    ("BOSTON INNER HARBOR", "BOSTON", "boston-inner-harbor-ma"),
    ("FORT POINT CHANNEL", "BOSTON", "fort-point-channel-ma"),
    ("CHELSEA RIVER", "BOSTON", "chelsea-river-ma"),
    ("BEAVER BROOK", "LOWELL", "beaver-brook-lowell-ma"),
    ("Beaver Brook", "Lowell", "beaver-brook-lowell-ma"),
    ("LITTLE RIVER", "HAVERHILL", "little-river-ma"),
])
def test_the_crosswalk_places_the_waters_that_have_records_now(cw, waters, text, town, slug):
    slugs, match, note = M.resolve_water([("portal", text)], town, None, cw, {})
    assert slugs == [slug] and match == "name" and note["via"] == "crosswalk on portal waterbody"
    assert waters[slug]["state"] == "MA"


@pytest.mark.parametrize("text,town", [("BEAVER BROOK", "WESTFORD"), ("BEAVER BROOK", None),
                                       ("LITTLE RIVER", "CAMBRIDGE"), ("LITTLE RIVER", None)])
def test_a_shared_name_stays_unplaced_by_the_crosswalk_in_other_towns(cw, text, town):
    """Several Beaver Brooks and two Little Rivers have records: only Lowell's and Haverhill's rows name one."""
    slugs, match, note = M.resolve_water([("portal", text)], town, None, cw, {})
    assert slugs == [] and match == "none" and note.get("no_slug")


def test_every_crosswalk_slug_is_a_massachusetts_record(cw, waters):
    for key, (slug, _, _) in cw.items():
        if slug:
            assert slug in waters and waters[slug]["state"] == "MA", (key, slug)


def _mi_event(text, permit, did):
    return event(source_id="mi-egle-mienviro-cso-sso-list", source_record_id=text, event_type="cso", status="ended",
                 waterbody_text=text, npdes_permit=permit, discharger_id=did, raw={"state": "MI"})


@pytest.fixture(scope="module")
def resolver(waters):
    S._STATES = S.derive_states(waters, S.load_rules())
    return S.make_resolver(waters)


def test_dearborns_lower_branch_of_the_rouge_is_the_lower_river_rouge(resolver):
    """MiEnviro names Dearborn's CSO water 'Rouge River, Lower Branch'; the record is the Lower River Rouge. The name is
    the record's alone in Michigan, so the no-point guard (which checks the state only) keeps it, though the record's
    towns lack Dearborn."""
    pl = resolver.resolve(_mi_event("Rouge River, Lower Branch", "MI0025542", "mi-dearborn-cso-mi0025542"))
    assert pl["water_slugs"] == ["lower-river-rouge-mi"] and pl["water_match"] == "name"
    # the plain 'Rouge River' is still two records and still unplaced without a point
    assert resolver.resolve(_mi_event("Rouge River", "MI0025542", "mi-dearborn-cso-mi0025542"))["water_slugs"] == []


def test_manistee_lake_goes_to_the_lake_at_manistee_by_the_dischargers_town(resolver):
    pl = resolver.resolve(_mi_event("Manistee Lake", "MI0020362", "mi-manistee-wwtp-mi0020362"))
    assert pl["water_slugs"] == ["manistee-lake-mi"]
    # another permittee with no town still meets two Manistee Lakes
    assert resolver.resolve(_mi_event("Manistee Lake", "MI9999999", None))["water_slugs"] == []
