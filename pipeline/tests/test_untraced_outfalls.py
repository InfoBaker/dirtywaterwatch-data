"""Reports that name a permit and an outfall but sat on no water page (untraced-outfall fixes, 2026-11-28;
research/mi/untraced-outfall-waters-2026-11-28.json and research/registry/untraced-outfall-waters-2026-11-28.csv).
Data tests on the files as committed and the resolver's rules; no network.
Run from pipeline/: python -m pytest tests/test_untraced_outfalls.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import event  # noqa: E402


@pytest.fixture(scope="module")
def waters():
    return S.load_waters()


@pytest.fixture(scope="module")
def resolver(waters):
    S._STATES = S.derive_states(waters, S.load_rules())
    return S.make_resolver(waters)


def _mi(text, permit, did=None, oid=None, name=None):
    return event(source_id="mi-egle-mienviro-cso-sso-list", source_record_id=f"{permit}-{oid}-{text}", event_type="cso",
                 status="ended", waterbody_text=text, npdes_permit=permit, discharger_id=did, outfall_id=oid,
                 outfall_name=name, raw={"state": "MI"})


# ------------------------------------------------------------------ 1. Michigan's same-named river records

def test_michigan_remainders_step_aside_for_their_main_record():
    """A river's NHD remainder (covers_part_of) steps aside for its main record when the report has no point, in
    Michigan as in Tennessee: Port Huron's 'St. Clair River' is the main record at Port Huron, not the Algonac
    remainder 35 km downstream."""
    assert {"TN", "MI"} <= S.REMAINDER_MERGE_STATES


@pytest.mark.parametrize("text,permit,did,oid,slug", [
    ("St. Clair River", "MI0023833", "mi-port-huron-wwtp-mi0023833", "003", "saint-clair-river-mi"),
    ("St. Clair River", "MI0020656", "mi-marysville-wwtp-mi0020656", "101", "saint-clair-river-mi"),
    ("Rouge River", "MI0025542", "mi-dearborn-cso-mi0025542", "011", "river-rouge-mi"),
    ("Rouge River", "MI0025542", "mi-dearborn-cso-mi0025542", "015", "river-rouge-mi"),
    ("Rouge River", "MI0025534", "mi-birmingham-cso-rtb-mi0025534", "102", "river-rouge-mi"),
    ("St. Joseph River", "MI0023701", "mi-niles-wwtp-mi0023701", "004", "st-joseph-river-mi"),
])
def test_a_pointless_report_naming_a_split_river_goes_to_the_main_record(resolver, text, permit, did, oid, slug):
    pl = resolver.resolve(_mi(text, permit, did, oid))
    assert pl["water_slugs"] == [slug], pl


def test_a_remainder_with_a_point_near_it_alone_keeps_the_report(resolver):
    """The rule sets a remainder aside only where the main record reaches the point (or there is none): a point at
    Algonac, on the remainder and 35 km from the main record, still goes to the remainder."""
    assert resolver.merge_remainders(["saint-clair-river-mi", "saint-clair-river-algonac-mi"], 42.6, -82.53) == \
        ["saint-clair-river-mi", "saint-clair-river-algonac-mi"]
    assert resolver.merge_remainders(["saint-clair-river-mi", "saint-clair-river-algonac-mi"], None, None) == \
        ["saint-clair-river-mi"]


def test_crystal_falls_paint_river_is_still_two_unrelated_records(resolver):
    """Crystal Falls' 'Paint River' (GW1810192, no operator on record, no point): the remainder steps aside, but
    paint-river-mi (Crystal Falls) and paint-river-iron-river-mi (Iron River) are two main records, so the report
    stays unplaced until its town or operator is on record (left for a decision)."""
    pl = resolver.resolve(_mi("Paint River", "GW1810192", None, "002"))
    assert pl["water_slugs"] == []
    assert "paint-river-mastodon-mi" not in (pl.get("note") or "")
