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


# ------------------------------------------------------------------ 2. spellings the reports use

@pytest.mark.parametrize("text,permit,slug", [
    ("Raisin River South Branch", "3112a-0066", "south-branch-river-raisin-mi"),
    ("River Rasin", "MI0020401", "river-raisin-mi"),
    ("St. Joe River", "MI0020109", "st-joseph-river-mi"),
    ("Big Cedar River", "MIG580212", "cedar-river-mi"),
    ("Open ditch discharge to Big Cedar River", "MIG580212", "cedar-river-mi"),
    ("Beguns Creek", "MI0043982", "begunn-creek-mi"),
    ("BeGunns Creek", "MI0043982", "begunn-creek-mi"),
    # Bloomfield Village's basin reaches the main Rouge through two county drains with no record (EPA lists the
    # permit's receiving water as the Rouge River; the permit's ECHO outfall 102 is 323 m from river-rouge-mi)
    ("Rouge River via Luz & Nichols", "MI0048046", "river-rouge-mi"),
])
def test_the_reports_spellings_name_the_record_the_research_settled(resolver, text, permit, slug):
    pl = resolver.resolve(_mi(text, permit))
    assert pl["water_slugs"] == [slug], pl


def test_each_new_alias_belongs_to_one_michigan_record(waters):
    import json
    aliases = json.loads((Path(__file__).resolve().parents[2] / "data" / "water-aliases.json").read_text())
    for slug, texts in {"south-branch-river-raisin-mi": ["Raisin River South Branch"], "river-raisin-mi": ["River Rasin"],
                        "st-joseph-river-mi": ["St. Joe River"], "cedar-river-mi": ["Big Cedar River"],
                        "begunn-creek-mi": ["Beguns Creek", "BeGunns Creek"],
                        "river-rouge-mi": ["Rouge River via Luz & Nichols"]}.items():
        assert waters[slug]["state"] == "MI"
        for t in texts:
            assert t in aliases[slug]
            assert [s for s, v in aliases.items() if t in v] == [slug], t


# ------------------------------------------------------------------ 5 and 7c. Akron at the permit's points; NEORSD 211, 212

def _oh(permit, oid, lat=None, lon=None):
    return event(source_id="oh-echo-dmr-cso", source_record_id=f"{permit}-{oid}", event_type="cso", status="ended",
                 npdes_permit=permit, outfall_id=oid, lat=lat, lon=lon, raw={"state": "OH"})


AKRON_WATERS = {**{n: "little-cuyahoga-river-oh" for n in ("046", "049", "053", "054", "057", "058", "065", "069", "070",
                                                           "071", "072", "081", "083", "084")},
                **{n: "cuyahoga-river-oh" for n in ("075", "076", "077", "078")}}


@pytest.mark.parametrize("oid,slug", sorted(AKRON_WATERS.items()))
def test_akrons_monthly_reports_take_the_water_its_permit_names(resolver, oid, slug):
    pl = resolver.resolve(_oh("OH0023833", oid))
    assert pl["water_slugs"] == [slug] and pl["water_match"] == "outfall_registry", pl


@pytest.mark.parametrize("oid", ["047", "055", "059", "060", "062", "080"])
def test_akrons_ohio_canal_and_camp_brook_outfalls_stay_untied(resolver, oid):
    assert resolver.resolve(_oh("OH0023833", oid))["water_slugs"] == []


@pytest.mark.parametrize("oid", ["211", "212"])
def test_neorsd_nine_mile_creek_outfalls_are_tied_in_both_copies(resolver, oid):
    from common import load_outfall_registry
    import json
    pl = resolver.resolve(_oh("OH0043991", oid))
    assert pl["water_slugs"] == ["ninemile-creek-cleveland-oh"], pl
    rows = [o for name in ("outfalls-oh.json", "outfalls-us.json")
            for o in json.loads((Path(__file__).resolve().parents[2] / "data" / name).read_text())["outfalls"]
            if (o.get("npdes_permit"), o.get("outfall")) == ("OH0043991", oid)]
    assert len(rows) == 2 and {o["water_slug"] for o in rows} == {"ninemile-creek-cleveland-oh"}
    loaded = [o for o in load_outfall_registry(provisional=False) if (o["npdes_permit"], o["outfall"]) == ("OH0043991", oid)]
    assert loaded[0]["_file"].endswith("outfalls-oh.json")


# ------------------------------------------------------------------ 6. Euclid: 'Lake Erie via storm sewer'

EUCLID = ["005", "006", "008", "009", "010", "011", "012", "015", "018", "019", "022"]


@pytest.mark.parametrize("oid", EUCLID)
def test_euclids_outfalls_take_lake_erie_on_the_permits_statement_and_keep_their_points(resolver, oid):
    import json
    row = next(o for o in json.loads((Path(__file__).resolve().parents[2] / "data" / "outfalls-us.json").read_text())["outfalls"]
               if (o.get("npdes_permit"), o.get("outfall")) == ("OH0031062", oid))
    assert row["match"] == "permit_stated" and "'Lake Erie via storm sewer'" in row["water_match"]
    assert (row["lat"], row["lon"]) != (None, None) and "epa_lat" not in row          # the point is EPA's, not moved
    pl = resolver.resolve(_oh("OH0031062", oid, row["lat"], row["lon"]))
    assert pl["water_slugs"] == ["lake-erie-oh"], pl
    assert "the water its permit names" in (pl.get("note") or ""), pl.get("note")


@pytest.mark.parametrize("oid", ["023", "024"])
def test_euclids_ravine_outfalls_stay_untied(resolver, oid):
    assert resolver.resolve(_oh("OH0031062", oid))["water_slugs"] == []


# ------------------------------------------------------------------ 4. the Narragansett Bay Commission's outfall numbers

@pytest.mark.parametrize("permit,oid,row,slug", [
    ("RI0100072", "OF 107", "107A", "blackstone-river-ri"),
    ("RI0100072", "OF 218", "218A", "seekonk-river-ri"),
    ("RI0100315", "OF 027", "027A", "seekonk-river-ri"),
])
def test_an_nbc_report_of_of_107_is_the_registry_row_107a(resolver, permit, oid, row, slug):
    rows = resolver.outfall_rows(permit, oid)
    assert [r["outfall"] for r in rows] == [row]
    ev = event(source_id="ri-nbc", source_record_id=f"{oid}-x", event_type="cso", status="ended", npdes_permit=permit,
               outfall_id=oid, outfall_name=f"{oid} Regs Combined", raw={"state": "RI"})
    pl = resolver.resolve(ev)
    assert pl["water_slugs"] == [slug] and pl["water_match"] == "outfall_registry", pl


def test_the_a_suffix_rule_is_only_the_nbc_permits_and_only_a_single_a_row(resolver):
    assert S.NBC_A_SUFFIX_PERMITS == {"RI0100072", "RI0100315"}
    by = {p: rows for p, rows in resolver.by_permit.items()}
    # another permit with an 'A' row is not read so (a bare number names no lettered row there)
    other = next(p for p, rows in sorted(by.items()) if p not in S.NBC_A_SUFFIX_PERMITS and p.startswith("MI")
                 and any(str(r.get("outfall") or "").endswith("A") and str(r.get("outfall"))[:-1].isdigit() for r in rows)
                 and not any(str(r.get("outfall") or "").isdigit() for r in rows
                             if str(r.get("outfall")) + "A" in {str(x.get("outfall")) for x in rows}))
    arow = next(r for r in by[other] if str(r.get("outfall") or "").endswith("A") and str(r.get("outfall"))[:-1].isdigit())
    assert resolver.outfall_rows(other, "OF " + arow["outfall"][:-1]) == []
    # a lettered report ('OF 107 B' style) or a plant outfall ('OF 002 BP') is not changed
    assert resolver.outfall_rows("RI0100072", "OF 002 BP") == [] or \
        all(r["outfall"] != "002A" for r in resolver.outfall_rows("RI0100072", "OF 002 BP"))
