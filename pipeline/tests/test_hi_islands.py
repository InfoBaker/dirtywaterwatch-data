"""Hawaii's island-aware name placement (final audit 2026-11-07 P1-1): a report gives an island and no point, so a name
two islands share ("Kailua Bay" off Oahu and off Kona) resolves only to the record on the report's island. The Kona
record is the batch's openboatlaunch record kailua-bay-hi (its box as built); the Oahu record is a stand-in. Every other
state's name placement is unchanged."""
import copy
import json
from pathlib import Path

import pytest

from build import status as S
from ingest import hi_doh_cwb_events as HI

FIXTURE = Path(__file__).parent / "fixtures" / "hi_doh_cwb_events.json"
KONA = {"slug": "kailua-bay-hi", "name": "Kailua Bay", "kind": "bay", "state": "HI", "towns": ["Kailua-Kona"],
        "bbox": [-156.03, 19.62, -155.99, 19.65], "aliases": []}
OAHU = {"slug": "kailua-bay-oahu-hi", "name": "Kailua Bay", "kind": "bay", "state": "HI", "towns": ["Kailua"],
        "bbox": [-157.74, 21.39, -157.70, 21.43], "aliases": []}


@pytest.fixture(autouse=True)
def hawaii_live(monkeypatch):
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"HI"})


def advisory_2183():
    """The open Marine Corps Base Hawaii advisory (Oahu, 'Affected waters: Kailua Bay') as the ingester writes it."""
    recs, _ = HI.build(json.loads(FIXTURE.read_text()), "2026-11-07T12:53:27Z", (), HI.Waters([], {}))
    r = next(x for x in recs if x["source_record_id"] == "2183")
    assert r["raw"]["island"] == "Oahu" and r["waterbody_text"] == "Kailua Bay" and r["water_slugs"] == []
    return r


def resolver(*records):
    return S.Resolver({w["slug"]: copy.deepcopy(w) for w in records}, [], placement_rules={})


def test_an_oahu_report_is_never_placed_on_konas_kailua_bay():
    r = resolver(KONA).resolve(advisory_2183())
    assert r["water_slugs"] == []
    slugs, note, _ = resolver(KONA).by_name("Kailua Bay", "HI", None, None, advisory_2183())
    assert slugs == [] and "do not lie on Oahu" in note


def test_the_oahu_report_goes_to_oahus_record_when_one_exists():
    r = resolver(KONA, OAHU).resolve(advisory_2183())
    assert r["water_slugs"] == ["kailua-bay-oahu-hi"]


def test_a_hawaii_island_report_goes_to_konas_bay():
    ev = advisory_2183()
    ev = {**ev, "raw": {**ev["raw"], "island": "Hawaii"}}
    assert resolver(KONA, OAHU).resolve(ev)["water_slugs"] == ["kailua-bay-hi"]


def test_a_record_with_no_box_is_not_taken_for_an_island():
    nobox = {**OAHU, "bbox": None}
    assert resolver(nobox).resolve(advisory_2183())["water_slugs"] == []


def test_other_states_are_unchanged():
    # the island rule is keyed on Hawaii: a Maryland report naming a water with no box still places by name
    w = {"slug": "kailua-bay-md", "name": "Kailua Bay", "kind": "bay", "state": "MD", "towns": [], "bbox": None,
         "aliases": []}
    ev = {"event_id": "x:1", "source_id": "md-test", "event_type": "sso", "status": "ended", "npdes_permit": None,
          "waterbody_text": "Kailua Bay", "water_slugs": [], "raw": {"state": "MD", "island": "Oahu"}}
    assert resolver(w).by_name("Kailua Bay", "MD", None, None, ev)[0] == ["kailua-bay-md"]
    assert S.ISLAND_STATES == {"HI"}


# ---------------------------------------------------------------- the names pass (ingest.waters_from_nhd --names)

def test_the_names_pass_keeps_one_target_per_name_and_island():
    from ingest import waters_from_nhd as N
    rows = [{"name": "Kailua Bay", "island": "Oahu", "reports": 17, "towns": ["Kailua"]},
            {"name": "Kailua Bay", "island": "Hawaii", "reports": 2, "towns": ["Holualoa", "Kalaoa"]},
            {"name": "Waimea Bay", "island": "Oahu", "reports": 20, "towns": ["Pupukea"]},
            {"name": "Waimea Bay", "island": "Kauai", "reports": 2, "towns": ["Waimea"]}]
    waters = {"kailua-bay-hi": copy.deepcopy(KONA)}
    targets, done, skipped = N.collect_name_targets("HI", rows, resolver(KONA), waters)
    assert not skipped
    # Kona's record holds Hawaii Island's Kailua Bay only; Oahu's is built
    assert [(t["island"], s) for t, s in done] == [("Hawaii", ["kailua-bay-hi"])]
    assert sorted((t["name"], t["island"]) for t in targets) == [("Kailua Bay", "Oahu"), ("Waimea Bay", "Kauai"),
                                                                 ("Waimea Bay", "Oahu")]
    assert {t["island"]: dict(t["towns"]) for t in targets if t["name"] == "Waimea Bay"} == \
        {"Oahu": {"Pupukea": 20}, "Kauai": {"Waimea": 2}}


def test_a_resolved_island_row_is_rechecked_on_its_island():
    from ingest import waters_from_nhd as N
    meta = {"resolved": [{"name": "Kailua Bay", "island": "Oahu", "reports": 17, "slugs": ["kailua-bay-hi"],
                          "towns": ["Kailua"]},
                         {"name": "Kailua Bay", "island": "Hawaii", "reports": 2, "slugs": ["kailua-bay-hi"],
                          "towns": ["Holualoa"]}]}
    back = N.recheck_resolved(meta, "HI", resolver(KONA))
    assert [(r["name"], r["island"]) for r in back] == [("Kailua Bay", "Oahu")]     # the batch's wrong resolution undone
    assert [r["island"] for r in meta["resolved"]] == ["Hawaii"]


def test_the_rewrite_matches_rows_by_name_and_island(tmp_path):
    from ingest import waters_from_nhd as N
    rows = [{"name": "Kailua Bay", "island": "Oahu", "reports": 17, "towns": ["Kailua"], "_parts": ["Kailua Bay"]},
            {"name": "Kailua Bay", "island": "Hawaii", "reports": 2, "towns": ["Holualoa"], "_parts": ["Kailua Bay"]}]
    out_rows = [{"from": N.REPORT_ROWS, "name": "Kailua Bay", "island": "Hawaii", "slugs": ["kailua-bay-hi"],
                 "how": ["already a water record"]},
                {"from": N.REPORT_ROWS, "name": "Kailua Bay", "island": "Oahu", "slugs": [],
                 "reason": "no NHD flowline or waterbody of that name in HI"}]
    path = tmp_path / "hi.json"
    N.rewrite_names(path, {}, "HI", rows, out_rows, {}, {"built": "2026-11-08T00:00:00Z", "records": 0,
                                                          "network_requests": 0, "file": str(path)})
    d = json.loads(path.read_text())
    assert [(r["name"], r["island"]) for r in d["rows"]] == [("Kailua Bay", "Oahu")]
    assert [(r["name"], r["island"]) for r in d["resolved"]] == [("Kailua Bay", "Hawaii")]
