"""Plant outfalls matched to water records (scripts/match_outfalls.py --plants, ingest.outfall_waters --plants) and the
operator rows added for their permits (scripts/add_federal_operators.py). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import DATA_DIR, ROOT  # noqa: E402
from ingest import outfall_waters as O  # noqa: E402

LIVE = {"CT", "MA", "ME", "NH", "RI", "VT", "NJ", "NY", "PA", "MD", "VA", "DC"}
PLANTS = DATA_DIR / "outfalls-plants-us.json"
MATCH_FIELDS = {"water_slug", "water_name", "water_kind", "distance_m", "match", "water_match", "water_matched_by"}

_spec = importlib.util.spec_from_file_location("add_federal_operators", ROOT / "scripts" / "add_federal_operators.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)


@pytest.fixture(scope="module")
def plants():
    return json.loads(PLANTS.read_text())


# ---------------------------------------------------------------- the water a name is

def test_same_water_is_the_water_the_text_or_the_reach_names():
    cases = [({"receiving_water_echo": "Mattaponi River, UT"}, "Mattaponi River", True),
             ({"receiving_water_echo": "HUDSON R UNTR"}, "Hudson River", True),
             ({"receiving_water_echo": "Unnamed Trib To Susquehanna River"}, "Susquehanna River", True),
             ({"receiving_water_echo": "Delaware River (Zone 4)"}, "Delaware River", True),
             ({"receiving_water_echo": "x", "reach_gnis_name": "Penobscot River"}, "Penobscot River", True),
             ({"receiving_water_echo": "Little Neshaminy Creek"}, "Neshaminy Creek", False),
             ({"receiving_water_echo": "WHITE LAKE BK"}, "White Lake", False),
             ({"receiving_water_echo": "West Branch Perkiomen Creek"}, "Perkiomen Creek", False)]
    for row, record, want in cases:
        assert O.same_water(row, {"name": record}) is want, (row, record)


def test_a_facility_point_is_not_the_outfalls_and_a_moved_point_stays_none():
    v = O.plant_view({"coords_from": "facility", "lat": 41.0, "lon": -75.0, "receiving_water_override": {"water": "x"}})
    assert v["lat"] is None and v["lon"] is None and "receiving_water_override" not in v
    own = {"coords_from": "permitted_feature", "lat": 41.0, "lon": -75.0}
    assert O.plant_view(own)["lat"] == 41.0


class FakeMatcher:
    """The Matcher methods match_plant calls, with canned answers: what each step says about one outfall."""
    def __init__(self, by_name=None, nhd=None, permit=None, point=None, town=None, waters=None):
        self.answers = {"by_name": by_name or {}, "by_nhd_target": nhd or {}}
        self.point, self.permit, self.town = point, permit, town
        self.waters = waters or {"rec": {"name": "Recorded Creek"}, "pt": {"name": "Point Creek"}}
        self.asked = []

    def by_name(self, o, text):
        self.asked.append(("name", text))
        return self.answers["by_name"].get(text, (None, None))

    def by_nhd_target(self, o, text):
        self.asked.append(("nhd", text))
        return self.answers["by_nhd_target"].get(text, (None, None))

    def by_permit_waters(self, o):
        return self.permit or (None, None)

    def by_point(self, o, text):
        self.asked.append(("point", text))
        return self.point or (None, None)

    def match(self, o, flags=None):
        return self.town or {"slug": None, "reason": "x"}

    def reason(self, o, text, not_name):
        return "no record"

    def dist(self, slug, lat, lon):
        return None


def row(**kw):
    return {"state": "PA", "npdes_permit": "PA0000001", "receiving_water_echo": "Recorded Creek", "reach_gnis_name": None,
            "reach_id": "02050101000001", "lat": 41.0, "lon": -75.0, **kw}


def test_the_permits_text_is_tried_before_the_reach_name():
    mt = FakeMatcher(by_name={"Recorded Creek": ("rec", "by name"), "Reach Creek": ("pt", "reach")})
    res = O.match_plant(mt, row(reach_gnis_name="Reach Creek"))
    assert res["slug"] == "rec" and res["step"] == "name"
    assert ("name", "Reach Creek") not in mt.asked


def test_the_reach_name_places_an_outfall_whose_text_names_no_record():
    mt = FakeMatcher(by_name={"Unnamed Trib To Reach Creek": (None, None), "Reach Creek": ("pt", "its receiving water by name")})
    res = O.match_plant(mt, row(receiving_water_echo="Unnamed Trib To Reach Creek", reach_gnis_name="Reach Creek"))
    assert res["slug"] == "pt" and res["step"] == "reach name" and "02050101000001" in res["how"]


def test_the_reach_name_is_not_read_when_it_names_another_water_than_the_text():
    mt = FakeMatcher(by_name={"Farmington River": ("pt", "x")})
    res = O.match_plant(mt, row(receiving_water_echo="Pequabuck River", reach_gnis_name="Farmington River"))
    assert res["slug"] is None and "Farmington River" in res["reason"] and "not read" in res["reason"]
    assert ("name", "Farmington River") not in mt.asked


def test_the_snap_to_the_point_is_only_for_a_text_with_no_water_in_it():
    pt = (41.0, "pt")
    named = FakeMatcher(point=("pt", "the water record at the outfall's point"))
    assert O.match_plant(named, row(receiving_water_echo="Buffalo Creek"))["slug"] is None       # a named water: no snap
    assert O.match_plant(named, row(receiving_water_echo="GROUNDWATER"))["slug"] is None         # groundwater: no snap
    blank = FakeMatcher(point=("pt", "the water record at the outfall's point"))
    assert O.match_plant(blank, row(receiving_water_echo=None))["slug"] == "pt"
    huc = FakeMatcher(point=("pt", "the water record at the outfall's point"))
    assert O.match_plant(huc, row(receiving_water_echo="Outlet Saugus River-Frontal Broad Sound"))["slug"] == "pt"
    assert pt


def test_the_snap_is_refused_when_the_record_at_the_point_is_not_the_reaches_water():
    mt = FakeMatcher(point=("pt", "the water record at the outfall's point"))
    res = O.match_plant(mt, row(receiving_water_echo=None, reach_gnis_name="Reach Creek"))
    assert res["slug"] is None


def test_a_name_and_town_match_far_from_a_differently_named_record_is_refused():
    town = {"slug": "rec", "how": "by name and town", "step": "name and town"}
    mt = FakeMatcher(town=town, waters={"rec": {"name": "Coxes Creek"}})
    mt.dist = lambda slug, lat, lon: 4900.0
    res = O.match_plant(mt, row(receiving_water_echo="West Branch Coxes Creek", reach_gnis_name="West Branch Coxes Creek"))
    assert res["slug"] is None and "4.9 km" in res["reason"]
    mt2 = FakeMatcher(town=town, waters={"rec": {"name": "Coxes Creek"}})
    mt2.dist = lambda slug, lat, lon: 4900.0
    assert O.match_plant(mt2, row(receiving_water_echo="Coxes Creek"))["slug"] == "rec"          # the water itself: kept


# ---------------------------------------------------------------- the file

def built_states() -> set[str]:
    """States a state build has tied (ingest.outfall_waters --state; data/waters-nhd.json stats.state_builds): their
    rows carry the match fields before the state goes live (every public output still keeps to live_states)."""
    d = json.loads((PLANTS.parent / "waters-nhd.json").read_text())
    return set(((d.get("stats") or {}).get("state_builds") or {}))


def test_every_live_state_plant_row_has_its_match_fields_and_the_others_have_none(plants):
    built = built_states()
    for r in plants["outfalls"]:
        if r["state"] in LIVE or r["state"] in built:
            assert MATCH_FIELDS <= set(r), (r["npdes_permit"], r.get("outfall"))
            assert bool(r["water_slug"]) == (r["match"] != "none") == ("no_water_reason" not in r)
            # the matchers, or a state's hand ties from the operator's own list (scripts/wa_gate_ties.py and
            # scripts/ca_gate_ties.py, 2026-11-06; EPA's limit-set names, scripts/ak_gate_ties.py, 2026-11-07)
            assert r["water_matched_by"].startswith(("scripts/match_outfalls.py", "ingest.outfall_waters",
                                                     "scripts/wa_gate_ties.py", "scripts/ca_gate_ties.py",
                                                     "scripts/ak_gate_ties.py"))
            if not r["water_slug"]:
                assert r["water_name"] is None and r["water_match"].startswith("none: ")
            if r.get("coords_from") == "facility" and r["water_slug"]:
                assert r["distance_m"] is None, "a facility's point is never matched by distance"
        else:
            assert not (MATCH_FIELDS & set(r)), "national rows are matched when their state goes live"


def test_a_matched_plant_row_names_a_water_the_site_has(plants):
    from build import status as S
    waters = S.load_waters()
    missing = [(r["npdes_permit"], r["water_slug"]) for r in plants["outfalls"]
               if r["state"] in LIVE and r.get("water_slug") and S.SLUG_ALIASES.get(r["water_slug"], r["water_slug"]) not in waters]
    assert missing == []


def test_the_plants_file_keeps_its_layout(plants, tmp_path):
    p = tmp_path / "outfalls-plants-us.json"
    O.write_plants(p, plants)
    assert p.read_text() == PLANTS.read_text()


# ---------------------------------------------------------------- the operator rows

def test_the_name_key_keeps_townships_boroughs_and_drinking_water_plants_apart():
    k = F.key
    assert k("MT PLEASANT TWP STP") != k("MT PLEASANT BORO STP")
    assert k("HARRISON TOWNSHIP WWTP") != k("Town of Harrison")
    assert k("BETHLEHEM WATER TREATMENT PLANT") != k("BETHLEHEM CITY WWTP")
    assert k("NEW MILFORD WPCF, TOWN OF") == k("New Milford")
    assert k("TOWN OF SIMSBURY WPCF") == k("Simsbury WPCF")


def test_the_new_operator_rows_have_the_registrys_shape_and_no_permit_is_in_two_rows():
    rows = json.loads((DATA_DIR / "dischargers.json").read_text())
    first = next(r for r in rows if r["id"] == "pa-pa0023736")
    new = [r for r in rows if r.get("source_areas") == ["federal"]]
    assert len(new) > 2000
    holder: dict[str, str] = {}
    for r in rows:
        for p in set(r.get("npdes_permits") or []) | ({r["npdes_permit"]} if r.get("npdes_permit") else set()):
            assert holder.setdefault(p, r["id"]) == r["id"], f"{p} is in {holder[p]} and {r['id']}"
    for r in new:
        assert [k for k in r if k != "short_name"] == list(first)
        assert r["id"] == f"{r['state'].lower()}-{r['npdes_permit'].lower()}" and r["aliases"] == [r["id"]]
        assert r["npdes_permit"] in r["npdes_permits"] and r["kind"] in ("plant", "cso")
        assert r["notification_channel"] == "None found online (not searched individually)"
        # live states: the 2026-11-03 run, or 2026-11-04 for the permits the plant registry's code-split rebuild added
        # (research/federal/build_plant_outfalls.py); a state built ahead of going live (Georgia, 2026-11-04) has its own date
        assert r["verified"] == "fetched" and (r["checked"] in ("2026-11-03", "2026-11-04") if r["state"] in LIVE else
                                               re.fullmatch(r"2026-\d\d-\d\d", r["checked"]))


def test_every_public_live_state_plant_permit_has_an_operator_page(plants):
    rows = json.loads((DATA_DIR / "dischargers.json").read_text())
    held = {"CT0100439"}                  # two Plainfield rows fit its name: docs/reviews/2026-11-03-federal-operators.md
    have = set()
    for r in rows:
        have |= set(r.get("npdes_permits") or []) | ({r["npdes_permit"]} if r.get("npdes_permit") else set())
    private = {"Privately Owned Facility", "Corporation", "NON-POTW"}
    missing = sorted({r["npdes_permit"] for r in plants["outfalls"]
                      if r["state"] in LIVE and r["npdes_permit"] not in have and r["npdes_permit"] not in held
                      and (r["plant_basis"] == "sewerage_code_public_owner"
                           or (r["plant_basis"] in ("potw_component", "potw_indicator") and r["facility_type"] not in private))})
    assert missing == []


def test_the_eight_operators_keep_their_permit_and_say_why():
    rows = {r["id"]: r for r in json.loads((DATA_DIR / "dischargers.json").read_text())}
    for did, (add, old) in F.TERMINATED_FIX.items():
        r = rows[did]
        assert old in r["npdes_permits"] and all(p in r["npdes_permits"] for p in add)
        assert "version 0 terminated" not in "" and old in r["notes"] and "the permit number is current" in r["notes"]
