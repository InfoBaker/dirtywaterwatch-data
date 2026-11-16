"""Puerto Rico's go-live audit (2026-11-16): P1-2, a report is placed only on the water it names or at its own point,
never on its permit's plant river (raw._placement on every PR record of EPA's overflow tables), on the audit's own
real rows (tests/fixtures/pr_sobe_audit_rows.json, the 2026-11-13 extract) with the real water records, outfall
registry and operator files; and P1-1, the beach text says what the status code does."""
import copy
import json
from pathlib import Path

import pytest

from build import status as S
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
NO_NAME = ("PR0025976:40:1", "PR0020923:2:1", "PR0020460:5:1")     # pump stations; the audit's 28 inferred ties
WAS = {"PR0025976:40:1": "rio-bairoa-pr", "PR0020923:2:1": "rio-cibuco-pr", "PR0020460:5:1": "rio-de-la-plata-pr",
       "PR0020753:2:1": "rio-chico-pr", "PR0026549:1:1": "unnamed-stream-near-culebra-pr"}


def _records() -> dict:
    t = json.loads((FIX / "pr_sobe_audit_rows.json").read_text())
    kept, _, _ = E.build(copy.deepcopy(t), {"extract_date": t["extract_date"], "last_modified": None,
                                            "now": "2026-11-16T08:00:00Z"})
    return {r["source_record_id"]: r for r in kept}


@pytest.fixture(scope="module")
def resolver():
    mp = pytest.MonkeyPatch()
    mp.setattr(S, "_STATES", set(S.states()) | {"PR"})       # Puerto Rico live in memory only
    S._GEOM_CACHE.clear()
    try:
        yield S.Resolver(S.load_waters(), S.load_registry_outfalls(), S.load_discharger_towns(),
                         S.load_discharger_waters(), S.load_rules().get("placement") or {})
    finally:
        S._GEOM_CACHE.clear()
        mp.undo()


def test_every_pr_record_carries_its_placement_mode():
    r = _records()
    assert len(r) == 7
    for k in ("PR0020753:2:1", "PR0026549:1:1", "PR0023761:1:1"):          # the report names a water
        assert r[k]["raw"]["_placement"] == "named_water_only", k
    for k in NO_NAME + ("PR0025976:57:1",):                                 # it names none
        assert r[k]["waterbody_text"] is None and r[k]["lat"] is not None, k
        assert r[k]["raw"]["_placement"] == "own_place_only", k
    assert E.OWN_PLACE_MODE_STATES == {"PR"}                                # no other state's records change


def test_the_fixture_reproduces_the_audits_wrong_ties(resolver):
    # without the mode, the status build ties each to a water it does not name (the audit's P1-2)
    for k, ev in _records().items():
        if k in WAS:
            raw = {x: v for x, v in ev["raw"].items() if x != "_placement"}
            assert resolver.resolve({**ev, "raw": raw})["water_slugs"] == [WAS[k]], k


def test_a_pump_station_report_naming_no_water_is_listed_and_colours_no_water(resolver):
    r = _records()
    for k in NO_NAME:
        out = resolver.resolve(r[k])
        assert out["water_slugs"] == [] and out["water_match"] == "none", k
        assert out["unplaced_reason"] == S.OWN_PLACE_NONE, k
        assert r[k]["lat"] is not None                                      # listed with its own place


def test_rio_de_apeadero_is_not_put_on_rio_chico(resolver):
    out = resolver.resolve(_records()["PR0020753:2:1"])
    assert "rio-chico-pr" not in out["water_slugs"] and out["water_slugs"] == []


def test_the_caribbean_sea_is_not_put_on_the_stream_near_culebra(resolver):
    out = resolver.resolve(_records()["PR0026549:1:1"])
    assert "unnamed-stream-near-culebra-pr" not in out["water_slugs"] and out["water_slugs"] == []
    assert out["unplaced_reason"] == S.OPEN_SEA_NONE                       # the audit's P2-3: the reason is given


def test_the_open_sea_reason_reads_spanish_and_english_and_only_in_puerto_rico(resolver):
    from tests.test_pr_review_fixes import _ev
    for text in ("OCEANO ATLANTICO", "Oceano Atlantico", "Caribe Ocean", "CARIBBEAN SEA", "ATLANTIC OCEAN", "Mar Caribe"):
        out = resolver.resolve(_ev(text, None, None, raw={"_placement": "named_water_only"}))
        assert out["water_slugs"] == [] and out["unplaced_reason"] == S.OPEN_SEA_NONE, text
    for text in ("QUEBRADA  Y EL RIO APEADERO", "Charca los corazones"):                # not the sea: no such reason
        out = resolver.resolve(_ev(text, None, None, raw={"_placement": "named_water_only"}))
        assert out.get("unplaced_reason") != S.OPEN_SEA_NONE, text
    assert not S.folds("NY") and S.ACCENT_FOLD_STATES == frozenset({"PR"})              # keyed on Puerto Rico only


def test_a_named_water_and_a_point_on_a_water_still_place(resolver):
    r = _records()
    out = resolver.resolve(r["PR0023761:1:1"])                              # "Río Coamo", named
    assert out["water_slugs"] == ["rio-coamo-pr"] and out["water_match"] == "name"
    out = resolver.resolve(r["PR0025976:57:1"])                             # no name; its own point is on Río Gurabo
    assert out["water_slugs"] == ["rio-gurabo-pr"] and out["water_match"] == "geometry"


# ----------------------------------------------------------------- P1-1: the beach text says what the colour does

def _red_until(rec, now):
    from tests.test_status import TEST_RULES
    ivs = S.event_intervals(rec, None, now, None, TEST_RULES)
    return max(i["end"] for i in ivs if i["color"] == "red")


def test_the_beach_text_says_what_the_colour_does():
    from datetime import datetime, timedelta, timezone
    from tests.test_pr_review_fixes import SANTA, TROP, post, recs_of
    utc = timezone.utc
    # the Sardinera case: listed on Nov. 6, left off on Nov. 13 -> shown until the Nov. 13 notice, not until Nov. 20
    recs = recs_of([post(1, "2026-11-06T12:00:00", [TROP, SANTA]), post(2, "2026-11-13T12:00:00", [TROP])])[0]
    assert _red_until(recs["RW-10:1"], datetime(2026, 11, 16, tzinfo=utc)) == datetime(2026, 11, 13, 12, tzinfo=utc)
    # left off only 30 days later: no more than 14 days after the last notice that listed it
    recs = recs_of([post(1, "2026-06-01T12:00:00", [TROP, SANTA]), post(2, "2026-07-01T12:00:00", [TROP])])[0]
    assert _red_until(recs["RW-10:1"], datetime(2026, 11, 16, tzinfo=utc)) == \
        datetime(2026, 6, 1, 12, tzinfo=utc) + timedelta(days=14)
    # a beach DRNA's newest notice still lists is DRNA's current advisory: each read reconfirms it, however old the
    # notice (so the text's 14-day limit is worded for a beach a later notice left off, not for every advisory)
    recs = recs_of([post(1, "2026-10-27T12:00:00", [TROP])], at="2026-11-16T12:00:00Z")[0]
    assert recs["RW-31:1"]["status"] == "advisory_active"
    assert _red_until(recs["RW-31:1"], datetime(2026, 11, 16, 12, tzinfo=utc)) == datetime(2026, 11, 30, 12, tzinfo=utc)
    # and the public text says exactly that, never the 14 days after the last listing it once promised
    text = (ROOT / "research" / "pr" / "state-text.md").read_text()
    basis = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["PR"]["basis"]
    assert ("the advisory is shown until that notice, for no more than 14 days after the last notice that listed it, "
            "and its end is marked as first seen there, not as lifted") in text
    assert ("the advisory is shown until that notice, its end marked as first seen there, and for no more than 14 days "
            "after the last notice that listed it") in basis
    for said in (text, basis):
        assert "shown for 14 days after the last notice" not in said
