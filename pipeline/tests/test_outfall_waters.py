"""Every registered outfall has a water record or a stated reason (owner, 2026-11-03: "Do we have all water bodies
clearly identified as we move forward with more states?"), and the pieces that give them one: ingest/outfall_waters.py
and the NHD builder's other places of a name, short branch names and kept slugs (ingest/waters_from_nhd.py).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import DATA_DIR  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402


# ---------------------------------------------------------------- the registries themselves

@pytest.fixture(scope="module")
def registry():
    rows = []
    for name in OW.FILES:
        d = json.loads((DATA_DIR / name).read_text())
        assert d["count"] == len(d["outfalls"]), f"{name}: count {d['count']} for {len(d['outfalls'])} rows"
        rows += [(name, o) for o in d["outfalls"]]
    return rows


def built_states() -> list[str]:
    """The states a state build has made water records for (data/waters-nhd.json stats.state_builds)."""
    d = json.loads((DATA_DIR / "waters-nhd.json").read_text())
    return sorted(((d.get("stats") or {}).get("state_builds") or {}))


@pytest.fixture(scope="module")
def state_registry():
    """The rows of the state-built states: data/outfalls-us.json, data/outfalls-plants-us.json, data/outfalls-<st>.json
    (ingest.outfall_waters --state)."""
    states = set(built_states())
    rows = []
    for name in list(OW.STATE_FILES) + [f"outfalls-{st.lower()}.json" for st in sorted(states)]:
        path = DATA_DIR / name
        if path.exists():
            rows += [(name, o) for o in json.loads(path.read_text())["outfalls"] if (o.get("state") or "") in states]
    return rows


@pytest.fixture(scope="module")
def waters():
    w = S.load_waters()
    return w, S.slug_aliases(w)


def test_every_registered_outfall_has_a_water_record_or_a_stated_reason(registry, waters):
    w, moved = waters
    bad = []
    for name, o in registry:
        where = f"{name} {o.get('npdes_permit')} {o.get('outfall')}"
        slug = o.get("water_slug")
        if slug:
            if moved.get(slug, slug) not in w:
                bad.append(f"{where}: water_slug {slug} is no water record")
        elif not str(o.get("no_water_reason") or "").strip():
            bad.append(f"{where}: no water_slug and no no_water_reason")
        if not str(o.get("water_match") or "").strip():
            bad.append(f"{where}: no water_match note")
    assert not bad, f"{len(bad)} outfalls:\n" + "\n".join(bad[:40])


def test_every_outfall_of_a_state_built_state_has_a_water_record_or_a_stated_reason(state_registry, waters):
    """A state build (2026-11-04) ties every outfall row of the state, CSO and treatment plant, before the state goes
    live: a slug that is a water record on file, or no_water_reason; and the note of how."""
    w, moved = waters
    bad = []
    for name, o in state_registry:
        where = f"{name} {o.get('npdes_permit')} {o.get('outfall')}"
        slug = o.get("water_slug")
        if slug:
            if moved.get(slug, slug) not in w:
                bad.append(f"{where}: water_slug {slug} is no water record")
        elif not str(o.get("no_water_reason") or "").strip():
            bad.append(f"{where}: no water_slug and no no_water_reason")
        if not str(o.get("water_match") or "").strip():
            bad.append(f"{where}: no water_match note")
    assert not bad, f"{len(bad)} outfalls:\n" + "\n".join(bad[:40])


def test_a_named_match_carries_a_name_of_the_receiving_water(registry, waters):
    """A slug matched by name alone (match 'name_only') must be a water of that name: the registry once matched
    'Burr Creek' to Burr Pond (status.Resolver.row_water makes the same check at build time)."""
    w, moved = waters
    bad = []
    for name, o in registry:
        slug = moved.get(o.get("water_slug"), o.get("water_slug"))
        if not slug or o.get("match") != "name_only" or slug not in w:
            continue
        text = OW.text_of(o)
        if not text or OW.why_not_a_name(text):
            continue
        rec = w[slug]
        names = [rec.get("name") or ""] + list(rec.get("aliases") or [])
        tw = N.words(text)
        if not any(N.name_score(tw, n) >= 0.7 or S.norm_name(n) in S.norm_name(" ".join(OW.variants(text)))
                   for n in names) and S.names_disagree(text, rec.get("name")):
            bad.append(f"{o['npdes_permit']} {o['outfall']}: '{text}' -> {slug} ({rec.get('name')})")
    assert not bad, "\n".join(bad[:40])


def test_no_name_only_match_names_another_water(registry, waters):
    """match_outfalls.py's words() dropped kind words, so its name-only matches sent 'Onondaga Creek' to Onondaga Lake
    and 'Upper New York Bay' to Upper Little York Lake (106 rows, re-matched 2026-11-03). A name-only match left in the
    registry must pass build/status.py's own check (the record's name inside the receiving water's text, or the text
    inside it). Exempt: this pass's matches whose note says why the text is not the record's name (a short form, 'read
    as'; a one-letter spelling or a qualifier, 'name and town'; a text that names no water, matched by the permit's
    listed water or the point)."""
    w, moved = waters

    def explained(o):
        note = str(o.get("water_match") or "")
        return str(o.get("water_matched_by") or "").startswith(OW.BY_HERE) and (
            "(read as '" in note or note.startswith(("name and town", "permit's receiving water", "point"))
            or bool(OW.why_not_a_name(OW.text_of(o))))
    bad = [f"{o['npdes_permit']} {o['outfall']}: '{OW.text_of(o)}' -> {o['water_slug']}"
           for _, o in registry
           if o.get("water_slug") and not explained(o)
           and OW.names_another_water({**o, "water_slug": moved.get(o["water_slug"], o["water_slug"])}, w)]
    assert not bad, "\n".join(bad[:40])


def test_a_replaced_match_is_kept_on_the_row(registry):
    for _, o in registry:
        rm = o.get("replaced_match")
        if rm:
            # the same slug may come back by another step (the name and the permittee's town), said in the note
            assert rm["water_slug"] and rm["why"] and "replaces" in o["water_match"]
            assert rm["water_slug"] != o.get("water_slug") or o["water_match"].startswith("name and town")


def test_a_moved_point_keeps_echos_values_and_says_why(registry):
    for _, o in registry:
        if o.get("coords_problem"):
            assert o.get("lat") is None and o.get("echo_lat") is not None and o.get("water_slug")


# ---------------------------------------------------------------- outfall_waters helpers

@pytest.mark.parametrize("text,why", [
    ("Outlet Saugus River-Frontal Broad Sound", "HUC-12"),
    ("Charles River-Frontal Boston Harbor", "HUC-12"),
    ("POTOMAC RIVER - ALLEGHANY COUNTY", "basin label"),
    ("UPPER POTOMAC RIVER", "basin label"),
    ("TO UBWPAD FINAL DSCHGE TO BLACKSTON", "treatment plant"),
    ("Ditch at Water Street & Canton Street", "street ditch"),
    ("", "no receiving-water text"),
])
def test_texts_that_name_no_water(text, why):
    assert why in (OW.why_not_a_name(text) or "")


@pytest.mark.parametrize("text", ["Unnamed Trib To Sawmill Run", "Great Ditch", "Queen Ditch", "Dutch Kills",
                                  "South Branch Park River Conduit", "Atlantic Ocean (Boston Harbor)", "Third Branch"])
def test_texts_that_name_a_water(text):
    assert OW.why_not_a_name(text) is None


def test_short_forms_of_a_receiving_water():
    assert "Upper New York Bay" in OW.variants("Upper NY Bay")
    assert "South Branch Park River" in OW.variants("South Branch Park River Conduit")
    assert "Park River Auxiliary" in OW.variants("Park River Aux. Conduit")


# ---------------------------------------------------------------- the NHD builder

def test_a_short_branch_name_is_its_river_branch_and_only_that():
    w = N.words
    assert N.name_score(w("THIRD BRANCH"), "Third Branch White River") == 0.8
    assert N.name_score(w("East Branch"), "East Branch Ausable River") == 0.8
    assert N.name_score(w("West Branch"), "East Branch Indian Creek") == 0.0
    assert N.name_score(w("Branch"), "Branch Brook") == 0.0


def test_kills_is_a_kind_word():
    assert N.has_kind(N.words("Dutch Kills")) and N.osm_kind(N.words("English Kills")) == "bay"


def _rec(name, gnis, weight, town):
    return {"name": name, "state": "PA", "gnis_id": gnis, "_weight": weight, "towns": [town],
            "_slug_towns": Counter({town: weight}), "comids": [int(gnis)]}


def test_a_record_keeps_its_slug_when_a_same_named_water_with_more_reports_appears():
    old = _rec("West Run", "1", 3, "Wetmore")
    new = _rec("West Run", "2", 9, "West Homestead")
    N.assign_slugs([old, new], {}, previous={("PA", "gnis", "1"): "west-run-pa"})
    assert old["slug"] == "west-run-pa" and new["slug"] == "west-run-west-homestead-pa"
    a, b = _rec("West Run", "1", 3, "Wetmore"), _rec("West Run", "2", 9, "West Homestead")
    N.assign_slugs([a, b], {})                       # no file: the most reported takes the plain slug, as before
    assert b["slug"] == "west-run-pa" and a["slug"] == "west-run-wetmore-pa"


def test_a_kept_slug_must_be_free_and_carry_the_name():
    r = _rec("Mill Creek", "5", 1, "Erie")
    N.assign_slugs([r], {"mill-creek-pa": {"slug": "mill-creek-pa", "name": "Mill Creek", "state": "PA"}},
                   previous={("PA", "gnis", "5"): "mill-creek-pa"})
    assert r["slug"] == "mill-creek-erie-pa"         # an openboatlaunch record holds that slug now
    r = _rec("Mill Creek", "5", 1, "Erie")
    N.assign_slugs([r], {}, previous={("PA", "gnis", "5"): "sawmill-run-pa"})
    assert r["slug"] == "mill-creek-pa"


def test_a_kept_record_keeps_its_slug_unless_this_run_built_the_same_water():
    """The file's records a run does not rebuild stay in the file (merge_waters), so their slugs are not free: a Lick
    Run found 60 km from Roanoke's must not take Roanoke's slug (the merge would drop Roanoke's record). A Bull Run
    that NHDPlus now names where only OSM had named it is the same water: it takes the slug."""
    roanoke = LineString([(-79.99, 37.27), (-79.95, 37.28)])
    lick = {**_rec("Lick Run", "9", 5, "Bedford"), "state": "VA", "_geom": LineString([(-79.35, 37.25), (-79.33, 37.30)])}
    N.assign_slugs([lick], {}, previous={}, kept=[("lick-run-va", "VA", "lick run", ("VA", "osm", ("w1",)), roanoke)])
    assert lick["slug"] == "lick-run-bedford-va"
    osm_bull = LineString([(-77.60, 38.80), (-77.45, 38.78)])
    bull = {**_rec("Bull Run", "7", 1, "Sudley"), "state": "VA", "_geom": LineString([(-77.60, 38.8001), (-77.45, 38.7801)])}
    N.assign_slugs([bull], {}, previous={}, kept=[("bull-run-va", "VA", "bull run", ("VA", "osm", ("r1",)), osm_bull)])
    assert bull["slug"] == "bull-run-va"


def test_other_places_of_a_name_are_the_points_no_record_of_it_reaches():
    """West Run in Pennsylvania: the record built near Wetmore does not reach West Homestead's outfalls, 181 km
    away; they are one more place to resolve, ahead of places only reports name."""
    wetmore, homestead, events_only = (-78.83, 41.65), (-79.9175, 40.4022), (-77.0, 40.9)
    t = {"name": "West Run", "state": "PA",
         "points": Counter({wetmore: 2, homestead: 3, (-79.9183, 40.4022): 1, events_only: 5}),
         "outfall_points": Counter({homestead: 3, (-79.9183, 40.4022): 1})}
    row = {"_recs": [{"_geom": LineString([(-78.86, 41.645), (-78.80, 41.655)])}], "slugs": [], "_tried": [wetmore]}
    fake = SimpleNamespace(existing={}, place_geoms=lambda r: N.Run.place_geoms(fake, r))
    places = N.Run.uncovered_places(fake, t, row)
    by_point = {(round(lon, 4), round(lat, 4)): (o, n) for lon, lat, o, n in places}
    assert by_point[homestead] == (4, 4) and by_point[events_only] == (0, 5)
    assert wetmore not in by_point
