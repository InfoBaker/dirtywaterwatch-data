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
    ("LITTLE MYSTIC CHANNEL", "BOSTON", "boston-inner-harbor-ma"),     # second batch (waters follow-up 2026-11-28)
    ("RESERVED CHANNEL", "BOSTON", "reserved-channel-ma"),       # its own record, not the harbor around it (review P2)
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
    # the plain 'Rouge River' is the main record (its NHD remainder steps aside without a point: untraced-outfall
    # fixes 2026-11-28, Michigan in REMAINDER_MERGE_STATES), not the Lower Rouge
    assert resolver.resolve(_mi_event("Rouge River", "MI0025542", "mi-dearborn-cso-mi0025542"))["water_slugs"] == \
        ["river-rouge-mi"]


def test_manistee_lake_goes_to_the_lake_at_manistee_by_the_dischargers_town(resolver):
    pl = resolver.resolve(_mi_event("Manistee Lake", "MI0020362", "mi-manistee-wwtp-mi0020362"))
    assert pl["water_slugs"] == ["manistee-lake-mi"]
    # another permittee with no town still meets two Manistee Lakes
    assert resolver.resolve(_mi_event("Manistee Lake", "MI9999999", None))["water_slugs"] == []


# ------------------------------------------------------------ second registry batch (waters follow-up 2026-11-28)
# research/registry/outfall-water-fixes-2026-11-28-review.md: the 15 rows marked apply

SECOND_BATCH = {("ME0102075", "005"): "back-cove-me", ("ME0102075", "007"): "back-cove-me",
                ("ME0102075", "012"): "back-cove-me", ("ME0102075", "015"): "back-cove-me",
                ("ME0102075", "016"): "back-cove-me", ("ME0101435", "006"): "back-cove-me",
                ("PA0021407", "006"): "camp-run-pa", ("PA0025984", "212"): "sawmill-run-pa",
                ("PA0217611", "056"): "sawmill-run-pa", ("PA0027111", "004"): "pucketa-creek-pa",
                ("PA0027391", "004"): "bull-creek-pa", ("NY0027057", "020"): "eighteenmile-creek-lockport-ny",
                ("NY0027057", "023"): "eighteenmile-creek-lockport-ny",
                ("NY0027057", "034"): "eighteenmile-creek-lockport-ny", ("VT0101010", "005"): "white-river-vt"}
# rows the review left alone: 'Portland Harbor, Back Cove, Ca' names three waters (do not apply); South Portland's
# Fore River rows (two Fore River records; cannot tell). Fall River's 010 (cannot tell from the repository's data) was
# settled later by MassDEP's own outfall layer (waters follow-up 2026-11-28; the test below)
LEFT = {("ME0101435", "013"): "casco-bay-me", ("ME0101435", "017"): "casco-bay-me",
        ("ME0101435", "018"): "casco-bay-me", ("ME0101435", "024"): "casco-bay-me",
        ("ME0100633", "005"): "casco-bay-me", ("ME0100633", "006"): "casco-bay-me",
        ("ME0100633", "018"): "casco-bay-me", ("ME0100633", "024"): "casco-bay-me"}


def test_the_second_batch_rows_carry_their_stated_water_in_the_registry_the_loader_reads():
    from common import load_outfall_registry
    loaded = {(o["npdes_permit"], o["outfall"]): o for o in load_outfall_registry(provisional=False)}
    for k, slug in SECOND_BATCH.items():
        o = loaded[k]
        assert o["water_slug"] == slug and o["water_matched_by"].startswith("data/outfall-water-corrections.json"), k
    # the one Portland row whose shared point lies beyond the tie distance rests on the stated water, off the water
    from ingest.outfall_water_corrections import stated_off_water
    assert loaded[("ME0101435", "006")]["match"] == "permit_stated" and stated_off_water(loaded[("ME0101435", "006")])
    for k, slug in LEFT.items():
        assert loaded[k]["water_slug"] == slug, k


def test_fall_rivers_city_pier_outfall_rests_on_the_taunton_river_the_permit_and_massdep_name():
    """MassDEP's CSO outfall layer gives FAL010 (City Pier) the receiving water 'TAUNTON RIVER' at EPA's own point; the
    river's centre line lies 560 m away, so the tie rests on the statement and no stretch is modeled from the point."""
    from common import load_outfall_registry
    from ingest.outfall_water_corrections import stated_off_water
    o = next(x for x in load_outfall_registry(provisional=False) if (x["npdes_permit"], x["outfall"]) == ("MA0100382", "010"))
    assert o["water_slug"] == "taunton-river-ma" and o["match"] == "permit_stated" and stated_off_water(o)
    assert o["replaced_match"]["water_slug"] == "narragansett-bay-ma"
