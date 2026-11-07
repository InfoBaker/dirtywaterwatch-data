"""One test (or a few) per fix from docs/reviews/2026-11-03-review.md: P1-1, P1-2, P1-3, P2-1 to P2-6 and P3 items
1, 2, 7, 8 and 9. Every personal name here is synthetic. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import inspect
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import redact as R  # noqa: E402
from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from tests.test_status import TEST_RULES, ev, iso, tmp_events, world  # noqa: E402

H = timedelta(hours=1)
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
NAME = "Zorvan Quillet"              # synthetic: a person's name as a report might quote it
PHONE = "410-555-0199"


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


@pytest.fixture
def data_dir(tmp_path):
    """Reference files for the redactor's lexicon, and the owner's blocklist holding the synthetic name."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "waters-new-england.csv").write_text("slug,name,kind,state,towns,launch_count,wikidata\n"
                                     "test-river-ma,Test River,river,MA,Springfield,1,\n")
    (d / "dischargers.json").write_text(json.dumps([{"name": "Town of Orange WPCA", "towns": ["Orange"]}]))
    (d / "name-allowlist.json").write_text(json.dumps({"names": []}))
    (d / "name-blocklist.json").write_text(json.dumps({"names": [NAME]}))
    return d


def ended(rid, **kw):
    kw.setdefault("status", "ended")
    kw.setdefault("started_at", iso(NOW - 5 * H))
    kw.setdefault("ended_at", iso(NOW - 4 * H))
    return ev(rid, **kw)


# P1-1 ---------------------------------------------------------------- placement texts are redacted

PREFIX = "Overflow ran from manhole 12 behind the pump station to "      # 56 characters: a 60-character quote cuts the name


def test_p1_1_a_name_quoted_in_a_placement_text_is_removed_from_every_key_of_the_written_record(tmp_path, data_dir):
    assert len(PREFIX) < 60 < len(PREFIX) + len(NAME.split()[0])
    recs = [ended("1", event_type="sso", water_slugs=[], waterbody_text=f"Storm drain at resident {NAME} {PHONE}"),
            ended("2", water_slugs=[], volume_text=f"No spill - per {NAME}"),
            ended("3", event_type="sso", water_slugs=[], waterbody_text=f"{PREFIX}{NAME}'s yard and a storm drain")]
    d = tmp_events(recs)
    st, _ = S.build(now=NOW, write=False, **world(d))
    pl = st["placements"]
    assert NAME in pl["ma-test:1"]["no_receiving_water"] and PHONE in pl["ma-test:1"]["no_receiving_water"]
    assert NAME in pl["ma-test:2"]["no_receiving_water"]                 # the no-release reason quotes the volume
    assert NAME.split()[0][:4] in pl["ma-test:3"]["no_receiving_water"]  # cut mid-name at 60 characters
    _, events, _ = S.load_events(d)
    r = R.redactor_for(events, data_dir)
    red = R.redact_events(events, data_dir, redactor=r)
    for o, e in zip(events, red):
        rec = X.public_record(e, pl[e["event_id"]], r, R.quote_swaps(o, e))
        X.write_compact(tmp_path / "out" / rec["file"], X.publicize(rec))
        text = (tmp_path / "out" / rec["file"]).read_text()
        for part in (*NAME.split(), NAME.split()[0][:4], PHONE):
            assert part not in text, (e["event_id"], part)
        assert R.REDACTED in (rec["no_receiving_water"] or "")
    assert X.blocklist_hits(tmp_path / "out", [NAME]) == []


def test_p1_1_status_lines_that_quote_a_record_go_through_the_same_redactor(data_dir):
    events = [ended("1", waterbody_text=f"Storm drain at resident {NAME}")]
    r = R.redactor_for(events, data_dir)
    st = {"waters": {"w": {"reason_short": f"CSO in progress · {NAME}", "reasons": [
        {"short": f"CSO in progress · {NAME}", "authority": f"{NAME} ({PHONE})",
         "red_rule": {"rule": "red.event", "rationale": f"per {NAME}"}}]}},
          "advisory_points": [{"short": f"Beach advisory · {NAME}"}], "reach_events_active": []}
    assert X.redact_status_texts(st, r) == 5
    assert NAME not in json.dumps(st) and PHONE not in json.dumps(st)


def test_every_nested_text_of_a_water_reason_goes_through_the_redactor(data_dir):
    """A reason's placement note, a rule's basis or a stretch text can quote the record too: the Old Tampa Bay water
    file carried a blocklisted name in such a field and the export's self-check stopped the run (2026-11-04)."""
    events = [ended("1", waterbody_text=f"Storm drain at resident {NAME}")]
    r = R.redactor_for(events, data_dir)
    st = {"waters": {"w": {"reason_short": "CSO", "reasons": [
        {"event_id": "ma-test:1", "short": "CSO", "rule": "red.event", "status": "red",
         "placement": {"note": f"named in the text: {NAME}", "steps": [{"why": f"town of {NAME}"}]},
         "rule_applied": {"rule": "text_caution", "basis": f"the form said no, the text names {NAME}"},
         "reach": "MA1-001"}]}}, "advisory_points": [], "reach_events_active": []}
    assert X.redact_status_texts(st, r) == 3
    assert NAME not in json.dumps(st) and st["waters"]["w"]["reasons"][0]["reach"] == "MA1-001"


def test_a_waters_summary_headline_and_unresolved_events_go_through_the_redactor(data_dir):
    """The water index and the water file also carry the water's summary, headline, per-category status and
    unresolved events, built from the records (the export's self-check stopped run 41921379232 on one of them)."""
    events = [ended("1", waterbody_text=f"Storm drain at resident {NAME}")]
    r = R.redactor_for(events, data_dir)
    st = {"waters": {"w": {"name": "Old Bay", "reason_short": "CSO", "reasons": [{"event_id": "ma-test:1", "short": "CSO"}],
                           "summary": f"One report, from {NAME}", "headline": {"status": "red", "text": f"per {NAME}"},
                           "status_by_category": {"sewage": {"status": "red", "why": f"{NAME} reported it"}},
                           "unresolved_events": [{"event_id": "ma-test:1", "short": f"reported by {NAME}"}],
                           "events": ["ma-test:1"], "towns": ["Tampa"]}},
          "advisory_points": [], "reach_events_active": []}
    assert X.redact_status_texts(st, r) == 4
    assert NAME not in json.dumps(st) and st["waters"]["w"]["name"] == "Old Bay"


def test_p1_1_the_blocklist_self_check_finds_a_name_in_out_and_fails_the_export(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    (out / "waters").mkdir(parents=True)
    (out / "events").mkdir()
    X.write_compact(out / "events.json", {"events": [{"event_id": "a", "waterbody_text": "Test River"}]})
    X.write_compact(out / "waters" / "test-river-ma.json", {"events": []})
    X.write_compact(out / "events" / "a.json", {"placement_note": "placed by name"})
    monkeypatch.setattr(X, "BLOCKED_MARK", tmp_path / "export-blocked.json")
    monkeypatch.setattr(X, "HITS_MARK", tmp_path / "blocklist-hits.json")
    assert X.blocklist_hits(out, [NAME]) == []
    assert X.enforce_blocklist(out, [NAME]) == 3 and not X.BLOCKED_MARK.exists() and not X.HITS_MARK.exists()
    X.write_compact(out / "events" / "b.json", {"no_receiving_water": f"only 'yard of {NAME.upper()}'"})
    X.write_compact(out / "waters" / "test-river-ma.json", {"reasons": [{"short": f"SSO · {NAME.split()[0]}  {NAME.split()[1]}"}]})
    assert X.blocklist_hits(out, [NAME]) == ["waters/test-river-ma.json", "events/b.json"]
    assert X.blocklist_hits(out, ["Someone Else"]) == []
    # a hit warns and names the files, never the name; the run goes on (owner, 2026-11-05) and no hard-stop mark is left
    X.BLOCKED_MARK.write_text("{}")
    assert X.enforce_blocklist(out, [NAME]) == 4 and not X.BLOCKED_MARK.exists()
    out_text = capsys.readouterr().out
    assert NAME not in out_text and "events/b.json" in out_text and "::warning::" in out_text
    hits = json.loads(X.HITS_MARK.read_text())
    assert hits["files"] == ["waters/test-river-ma.json", "events/b.json"] and NAME not in json.dumps(hits)
    (out / "events" / "b.json").unlink()
    X.write_compact(out / "waters" / "test-river-ma.json", {"events": []})
    X.enforce_blocklist(out, [NAME])
    assert not X.BLOCKED_MARK.exists() and not X.HITS_MARK.exists()


def test_p1_1_the_export_checks_what_it_wrote_last_and_the_refresh_stops_on_the_mark():
    src = inspect.getsource(X.export)
    assert src.index("redact_status_texts(st, redactor") < src.index("public_record(e, pl, redactor")
    assert src.index('write_compact(OUT_DIR / "meta.json", meta)') < src.index("enforce_blocklist(OUT_DIR)")
    # the refresh script: scripts/refresh.sh here, scripts/refresh-data.sh in the public data repository
    candidates = [Path(X.ROOT) / "scripts" / n for n in ("refresh.sh", "refresh-data.sh")]
    refresh = next(p for p in candidates if p.exists()).read_text()
    assert refresh.index("make refresh") < refresh.index("export-blocked.json") < refresh.index("upload-current.sh")


# P1-2 ---------------------------------------------------------------- the out-of-District rule

def potomac_world(events_dir):
    w = world(events_dir)
    w["waters"] = {
        "potomac-river-dc": {"slug": "potomac-river-dc", "name": "Potomac River", "kind": "river", "state": "DC",
                             "bbox": [-77.1, 38.87, -77.02, 38.93],
                             "geometry": {"type": "LineString", "coordinates": [[-77.10, 38.93], [-77.02, 38.87]]}},
        "potomac-river-md": {"slug": "potomac-river-md", "name": "Potomac River", "kind": "river", "state": "MD",
                             "bbox": [-77.2, 38.95, -77.1, 38.95],
                             "geometry": {"type": "LineString", "coordinates": [[-77.20, 38.95], [-77.10, 38.95]]}},
        **w["waters"]}
    return w


def test_p1_2_a_dc_water_row_with_raw_state_md_counts_and_is_placed_in_maryland(data_dir):
    basis = "point outside the District: reported in Maryland, operator unchanged"
    interceptor = ended("interceptor", source_id="echo-sewer-overflow", event_type="sso", npdes_permit="DC0021199",
                        discharger_id="dc-water", water_slugs=["potomac-river-dc"], water_match="name",
                        waterbody_text="Potomac River", lat=38.9496, lon=-77.1273,
                        raw={"state": "MD", "state_basis": basis})
    inside = ended("inside", source_id="echo-sewer-overflow", event_type="sso", npdes_permit="DC0021199",
                   water_slugs=["potomac-river-dc"], water_match="name", waterbody_text="Potomac River",
                   lat=38.90, lon=-77.06)
    d = tmp_events([interceptor, inside])
    st, _ = S.build(now=NOW, write=False, **potomac_world(d))
    assert S.event_state(interceptor) == "MD" and S.event_state(inside) == "DC"
    pl = st["placements"]
    assert pl[interceptor["event_id"]]["water_slugs"] == ["potomac-river-md"]
    assert pl[interceptor["event_id"]]["set_aside"][0]["water_slug"] == "potomac-river-dc"
    assert "another state" in pl[interceptor["event_id"]]["set_aside"][0]["reason"]
    assert pl[inside["event_id"]]["water_slugs"] == ["potomac-river-dc"]
    assert st["waters"]["potomac-river-md"]["status"] == "yellow"        # no MD red window in the test rules
    # the export's record carries the state read with raw: the meta counts, the index and the site read it
    r = R.redactor_for([interceptor], data_dir)
    rec = X.public_record(interceptor, pl[interceptor["event_id"]], r)
    assert rec["state"] == "MD"
    slim = {k: v for k, v in rec.items() if k not in X.SLIM_DROP}
    assert X.index_obj(slim)["state"] == "MD"                  # without raw, from the record's state
    # a two-letter raw.state wins over the permit; a longer value is only a fallback after it
    assert S.event_state({"npdes_permit": "DC0021199", "raw": {"state": "Maryland"}}) == "DC"


# P1-3 ---------------------------------------------------------------- "did not reach the water" is no receiving water

@pytest.mark.parametrize("text", [
    "the discharge did not reach Middle Patuxent River", "Did not enter the Mill Creek",
    "Loch Raven Reservoir (nearest body of water). Did not enter body of water.",
    "No liquid was determined to have entered into the James River",
    "Closest receiving waters is Leeds Creek (SSO was contained and no sewage entered any waterways or storm drains).",
    "It did not appear to reach Lake Habeeb.", "Reported as not reaching waters of the State (closest to Gwynns Falls)",
    "Not impacted (the area is in close proximity of Clement Cove)", "no impact (closest stream is Cabin Branch)",
    "N/A - Contained within treatment plant", "Lagoon 1 flowed into contact chamber, but not into Barton River.",
    "Straights Pond (NOT affected!)", "N/A - No Waterway", "No waterways or storm drains affected.",
    "The overflow never reached a surface body of water", "There was no discharge to waters of the State"])
def test_p1_3_statements_that_the_discharge_reached_no_water(text):
    assert S.stated_no_water(text), text


@pytest.mark.parametrize("text", [
    "Moores Creek; Sewage did reach a tributary to Moores Creek but did not go far and did not reach Moores Creek.",
    "Thames River is possibly affected but not positive if sewage reached the river after entering storm drains",
    "Swede pond, not clear if it entered Crooked brook", "The spill was not contained and flowed into Mill Brook",
    "Cub Run; UT of Cub Run\nno detrimental impacts observed", "Mill River", "The manhole contained debris",
    "Released into grassy area, then went into stream that goes into stormwater pond",
    "The pump station wouldn't drain and overflowed into Mill Brook"])
def test_p1_3_texts_that_say_it_reached_a_water_or_are_unsure_are_not_such_statements(text):
    assert S.stated_no_water(text) is None, text


def test_p1_3_a_named_or_flagged_report_that_reached_no_water_is_not_placed_and_the_note_quotes_it():
    said = ended("said", event_type="sso", water_slugs=["test-river-ma"], water_match="name",
                 waterbody_text="the discharge did not reach Test River", lat=42.0005, lon=-71.95)
    flagged = ended("flag", event_type="sso", water_slugs=[], waterbody_text="Test River", lat=42.0003, lon=-71.96,
                    raw={"Reach Waterbody": "No"})
    on_point = ended("point", event_type="sso", water_slugs=[], lat=42.0004, lon=-71.97,
                     raw={"row": {"surfaceWater": "No"}})
    placed = ended("placed", event_type="sso", water_slugs=[], waterbody_text="Test River", lat=42.0, lon=-71.95)
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([said, flagged, on_point, placed])))
    pl = st["placements"]
    p = pl[said["event_id"]]
    assert p["water_slugs"] == [] and p["no_receiving_water"] == "the report says the discharge reached no water"
    assert p["note"] == ("the report says: 'the discharge did not reach Test River'; "
                         "water named in the report, not placed: Test River")
    assert p["named_water_slugs"] == ["test-river-ma"] and "reach" not in p
    p = pl[flagged["event_id"]]
    assert p["water_slugs"] == [] and "(Reach Waterbody: No)" in p["no_receiving_water"]
    assert p["note"] == "water named in the report, not placed: Test River"
    p = pl[on_point["event_id"]]
    assert p["water_slugs"] == [] and "surfaceWater: No" in p["no_receiving_water"]
    assert p["note"].startswith("water nearest the report's point, not placed: Test River (")
    assert pl[placed["event_id"]]["water_slugs"] == ["test-river-ma"]
    assert st["waters"]["test-river-ma"]["events"] == [placed["event_id"]]       # the others are not listed on it
    assert st["counts"]["no_receiving_water"] == 3
    # an advisory's water field names its site: never this class
    beach = ended("b", event_type="beach_advisory", status="advisory_active", waterbody_text="did not reach Test River")
    assert S.reached_no_water(beach) is None


# P2-1 ---------------------------------------------------------------- one NHD feature, one record

def nhd_row(slug, gnis=None, fetched="2026-11-03T11:08:00Z", targets=1, **kw):
    return {"slug": slug, "name": slug.rsplit("-", 2)[0].replace("-", " ").title(), "state": "VA", "gnis_id": gnis,
            "comids": kw.pop("comids", [1, 2]), "fetched_at": fetched, "targets": targets, "aliases": kw.pop("aliases", []),
            **kw}


def test_p2_1_a_feature_written_under_a_new_slug_replaces_its_old_row_and_keeps_the_old_slug_as_an_alias():
    from ingest import waters_from_nhd as N
    old = [nhd_row("stony-creek-edinburg-va", "1487616", aliases=["Stony Ck"]),
           nhd_row("glade-creek-salem-va", "1467117", fetched="2026-11-03T09:38:37Z"),
           nhd_row("glade-creek-roanoke-va", "1467117"),
           nhd_row("mill-run-va", "111", comids=[7]),
           nhd_row("mill-run-part-va", "111", comids=[8], covers_part_of="mill-run-va")]
    new = [nhd_row("stony-creek-basye-va", "1487616", targets=2)]
    got = {r["slug"]: r for r in N.merge_waters(old, new)}
    assert sorted(got) == ["glade-creek-roanoke-va", "mill-run-part-va", "mill-run-va", "stony-creek-basye-va"]
    assert got["stony-creek-basye-va"]["slug_aliases"] == ["stony-creek-edinburg-va"]
    assert got["stony-creek-basye-va"]["aliases"] == ["Stony Ck"]
    assert got["glade-creek-roanoke-va"]["slug_aliases"] == ["glade-creek-salem-va"]      # the newer of two file rows
    assert "slug_aliases" not in got["mill-run-va"] and "slug_aliases" not in got["mill-run-part-va"]
    # the next write under the same slug keeps the alias; a third slug collects both
    again = {r["slug"]: r for r in N.merge_waters(list(got.values()), [nhd_row("stony-creek-basye-va", "1487616")])}
    assert again["stony-creek-basye-va"]["slug_aliases"] == ["stony-creek-edinburg-va"]
    third = {r["slug"]: r for r in N.merge_waters(list(again.values()), [nhd_row("stony-creek-mt-jackson-va", "1487616")])}
    assert "stony-creek-basye-va" not in third
    assert third["stony-creek-mt-jackson-va"]["slug_aliases"] == ["stony-creek-basye-va", "stony-creek-edinburg-va"]
    assert N.water_identity(nhd_row("x-va", None, comids=[3, 1])) == ("VA", "comids", (1, 3))
    assert N.water_identity(nhd_row("y-va", None, comids=[], osm=["w2", "w1"])) == ("VA", "osm", ("w1", "w2"))


def test_p2_1_the_status_follows_an_old_slug_to_its_record(tmp_path):
    w = world(tmp_events([]))["waters"]
    w["test-river-ma"] = {**w["test-river-ma"], "slug_aliases": ["test-river-springfield-ma"]}
    old = ended("old", water_slugs=["test-river-springfield-ma"], water_match="outfall_registry")
    st, _ = S.build(now=NOW, write=False, **{**world(tmp_events([old])), "waters": w})
    assert st["placements"][old["event_id"]]["water_slugs"] == ["test-river-ma"]
    assert "unknown_slugs" not in st["placements"][old["event_id"]] and not st["placements"][old["event_id"]].get("note")
    hand = tmp_path / "water-aliases.json"
    hand.write_text(json.dumps({"test-river-springfield-ma": ["Test R."]}))
    assert S.apply_water_aliases(w, hand, S.slug_aliases(w)) == []
    assert w["test-river-ma"]["aliases"] == ["Test R."]


# P2-3 ---------------------------------------------------------------- operators looked up by the registry id

def test_p2_3_placement_reads_the_operator_row_of_an_alias_id(tmp_path, monkeypatch):
    rep = ended("alias", discharger_id="ny-nycdep-city-wide-cso", npdes_permit=None, water_slugs=[],
                waterbody_text=None, raw={})
    kw = {**world(tmp_events([rep])),
          "discharger_waters": {"ny-nyc-dep": {"id": "ny-nyc-dep", "state": "MA", "names": ["Test River"],
                                               "slugs": ["test-river-ma"]}},
          "discharger_towns": {"ny-nyc-dep": ["Springfield"]}}
    st, _ = S.build(now=NOW, write=False, discharger_aliases_map={}, **kw)
    assert st["placements"][rep["event_id"]]["water_slugs"] == []                      # the ingester's id finds no row
    st, _ = S.build(now=NOW, write=False, discharger_aliases_map={"ny-nycdep-city-wide-cso": "ny-nyc-dep"}, **kw)
    p = st["placements"][rep["event_id"]]
    assert p["water_slugs"] == ["test-river-ma"] and p["water_match"] == "inferred"
    assert "single listed receiving water" in p["note"]
    # the lookups built from data/dischargers.json carry the aliases too (waters_from_nhd resolves raw events)
    (tmp_path / "dischargers.json").write_text(json.dumps({"dischargers": [
        {"id": "ny-nyc-dep", "aliases": ["ny-nycdep-city-wide-cso"], "towns": ["New York"], "state": "NY",
         "receiving_waters": ["East River (tidal strait)"]}]}))
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    assert S.load_discharger_towns()["ny-nycdep-city-wide-cso"] == ["New York"]
    assert S.load_discharger_waters()["ny-nycdep-city-wide-cso"]["names"] == ["East River"]
    assert S.canonical_dischargers([rep], S.discharger_aliases())[0]["discharger_id_source"] == "ny-nycdep-city-wide-cso"
    # a red rule written under the ingester's id still applies to the canonical record
    rules = {"red": {"by_discharger": {"ny-nycdep-city-wide-cso": {"hours": 24, "basis": "b"}}, "by_state": {}}}
    canon = {**rep, "discharger_id": "ny-nyc-dep", "discharger_id_source": "ny-nycdep-city-wide-cso"}
    assert S.red_rule_for(canon, "NY", rules)["hours"] == 24


# P2-4 ---------------------------------------------------------------- the MDE degrees-and-minutes repair

def test_p2_4_a_point_outside_its_county_is_left_as_given_and_noted_unless_the_repair_lands_in_the_county():
    from ingest import md_mde_overflows as M
    # outside Anne Arundel; read as minutes it is (39.35, -77.17), not in Anne Arundel either: left, and noted
    lat, lon, note = M.coords("39.2100", "-77.1000", "Anne Arundel")
    assert (lat, lon) == (39.21, -77.1)
    assert "outside Anne Arundel County" in note and "kept as given" in note and "decimal minutes" in note
    # minutes of 70 are not minutes: left, and noted
    lat, lon, note = M.coords("39.2100", "-76.7000", "Frederick")
    assert (lat, lon) == (39.21, -76.7) and "outside Frederick County" in note
    # inside its county: never changed, no county note
    lat, lon, note = M.coords("39.2100", "-77.1000", "Montgomery")
    assert (lat, lon) == (39.21, -77.1) and "outside" not in note
    # the repair itself: the decimal reading is outside the county and the minutes reading inside it
    lat, lon, note = M.coords("39.4012", "-78.4734", "Allegany")
    assert (round(lat, 3), round(lon, 3)) == (39.669, -78.789) and "read as degrees and decimal minutes" in note
    # no county: nothing tried, nothing noted
    assert M.coords("39.2100", "-77.1000") == (39.21, -77.1, "as given")


# coordinator 2026-11-03 ------------------------------------------------ a start in the future as published

def test_a_start_more_than_a_day_in_the_future_is_noted_and_sets_no_status_reach_or_colour(data_dir):
    future = ev("future", status="ongoing", started_at="2026-12-30T08:00:00-05:00", lat=42.0, lon=-71.95)
    soon = ev("soon", status="ongoing", started_at=iso(NOW + 12 * H), water_slugs=["other-pond-ma"])
    past = ended("past", started_at=iso(NOW - 100 * H), ended_at=iso(NOW - 99 * H))
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([future, soon, past])))
    p = st["placements"][future["event_id"]]
    assert p["future_start"] is True and "start is in the future as published" in p["validation_error"]
    assert p["water_slugs"] == ["test-river-ma"] and "reach" not in p             # still placed and listed
    w = st["waters"]["test-river-ma"]
    assert w["status"] == "grey" and w["reasons"] == []                            # no colour, no reason
    assert w["events"] == [past["event_id"], future["event_id"]]                   # never the latest report
    assert not any(iv[4] == future["event_id"] for iv in hist["intervals"].get("test-river-ma", []))
    assert not any(n["event_id"] == future["event_id"] for n in st["needs_reach"])
    assert "future_start" not in st["placements"][soon["event_id"]]                # within a day: a clock difference
    assert S.event_intervals(soon, "MA", NOW)                                         # it keeps its intervals
    assert st["counts"]["future_start"] == 1
    assert any("start more than 24 h in the future" in x for x in st["problems"])
    assert S.event_intervals(future, "MA", NOW) == []
    # the export keeps its page and archive row, marked, with the note in parse_error; it is not the latest report
    r = R.redactor_for([future], data_dir)
    rec = X.public_record(future, st["placements"][future["event_id"]], r)
    assert rec["future_start"] is True and "in the future as published" in rec["parse_error"]
    assert rec["file"] == f"events/{X.event_file_name(future['event_id'])}"
    src = inspect.getsource(X.export)
    assert 'for e in evs if not e.get("future_start")' in src and '"events_future_start"' in src
    from build import charts as C
    assert "future_start(ev, now)" in inspect.getsource(C.Data.__init__)


# P2-5, P2-6, P2-2 ---------------------------------------------------------------- the CSV downloads

def csv_ev(rid, started="2026-10-20T10:00:00-04:00", **kw):
    from common import event
    base = dict(source_id="ma-massdep", source_record_id=rid, event_type="cso", status="ended", started_at=started,
                ended_at=None, npdes_permit="MA0101613", discharger_id="ma-springfield-wsc", water_slugs=["connecticut-river-ma"],
                fetched_at="2026-11-02T10:45:00Z")
    extra = {k: kw.pop(k) for k in ("superseded", "state") if k in kw}     # placement fields the export adds
    base.update(kw)
    e = event(**base)
    e.update(fixture=False, **extra)
    return e


CSV_WATERS = [{"slug": "connecticut-river-ma", "name": "Connecticut River", "state": "MA", "events": []},
              {"slug": "potomac-river-md", "name": "Potomac River", "state": "MD", "events": []}]
CSV_DIS = [{"id": "ma-springfield-wsc", "name": "Springfield Water and Sewer Commission", "npdes_permit": "MA0101613",
            "state": "MA"},
           {"id": "dc-water", "name": "DC Water", "npdes_permit": "DC0021199", "state": "DC"}]


def csv_rows(tmp_path, events, **kw):
    import csv as std_csv
    from export import csv as C
    out = tmp_path / "csv"
    C.write_csvs(events, kw.pop("waters", CSV_WATERS), CSV_DIS, out, page_ids=kw.pop("page_ids", set()),
                 as_of=kw.pop("as_of", "2026-11-03T12:00:00Z"), **kw)
    rows = []
    for p in sorted(out.glob("all-reports-*.csv")):
        with p.open(newline="", encoding="utf-8") as f:
            rows += list(std_csv.DictReader(f))
    return {r["record_id"]: r for r in rows}


@pytest.fixture
def csv_states(monkeypatch):
    monkeypatch.setattr(S, "_STATES", {"MA", "MD", "DC", "VA"})


def test_p2_5_the_csv_keeps_the_report_time_and_the_source_update_time(tmp_path, csv_states):
    deq = csv_ev("325644", source_id="va-deq-prep", npdes_permit=None, discharger_id=None, water_slugs=[],
                 published_at=None, reported_at="2026-09-27T10:12:00-04:00", source_updated_at="2026-10-02T08:00:00-04:00")
    r = csv_rows(tmp_path, [deq])["325644"]
    assert (r["published_at"], r["reported_at"], r["source_updated_at"], r["retrieved_at"]) == (
        "", "2026-09-27T10:12:00-04:00", "2026-10-02T08:00:00-04:00", "2026-11-02T10:45:00Z")


def test_p2_6_superseded_versions_name_the_record_they_are_counted_under(tmp_path, csv_states):
    parent = csv_ev("1", superseded="revised by ma-massdep:2")
    child = csv_ev("2", parent_event_id="ma-massdep:1")
    notice = csv_ev("3", parent_event_id="ma-massdep:2", superseded="notice about ma-massdep:2, which carries the times")
    lost = csv_ev("4", superseded="revised by a record no longer in the file")
    rows = csv_rows(tmp_path, [parent, child, notice, lost])
    assert rows["1"]["superseded_by"] == "ma-massdep:2" and rows["3"]["superseded_by"] == "ma-massdep:2"
    assert rows["2"]["superseded_by"] == "" and rows["4"]["superseded_by"] == "revised by a record no longer in the file"
    # the site counts a revised discharge once: so do the rows with neither duplicate_of nor superseded_by
    assert [k for k, r in sorted(rows.items()) if not r["duplicate_of"] and not r["superseded_by"]] == ["2"]


def test_p2_2_site_url_is_the_page_by_the_sites_rule_else_the_archive_row(tmp_path, csv_states, monkeypatch):
    from export import csv as C
    recent = csv_ev("recent", "2026-10-20T10:00:00-04:00")
    old = csv_ev("old", "2025-03-01T10:00:00-05:00")
    old_ongoing = csv_ev("ongoing", "2024-12-30T10:00:00-05:00", status="ongoing")   # no page by status alone now
    late_night = csv_ev("night", "2025-01-01T04:30:00Z")                             # New York day: 2024-12-31
    md_row = csv_ev("md", "2025-03-01T10:00:00-05:00", npdes_permit="DC0021199", discharger_id="dc-water",
                    water_slugs=[], state="MD")                                      # the export's state wins
    by_source = csv_ev("src", "2025-03-01T10:00:00-05:00", source_id="zz-feed", npdes_permit=None, discharger_id=None,
                       water_slugs=[])
    undated = csv_ev("undated", None, npdes_permit=None, discharger_id=None, water_slugs=[], source_id="zz-feed")
    nowhere = csv_ev("nowhere", "2025-03-01T10:00:00-05:00", source_id="zz-feed", npdes_permit=None, discharger_id=None,
                     water_slugs=[])
    events = [recent, old, old_ongoing, late_night, md_row, by_source, undated, nowhere]
    rows = csv_rows(tmp_path, events, page_ids=None, active_ids=set(), source_states={"zz-feed": ["VA"]})
    site = "https://dirtywaterwatch.org"
    assert rows["recent"]["site_url"] == f"{site}/event/ma-massdep~3Arecent/"
    assert rows["old"]["site_url"] == f"{site}/discharges/ma/2025/#ma-massdep~3Aold"
    assert rows["ongoing"]["site_url"] == f"{site}/discharges/ma/2024/#ma-massdep~3Aongoing"
    assert rows["night"]["site_url"] == f"{site}/discharges/ma/2024/#ma-massdep~3Anight"
    assert rows["md"]["site_url"] == f"{site}/discharges/md/2025/#ma-massdep~3Amd"
    # VA is no covered state here (no water, no counted record in it): the list of all reports, by year chunk
    assert rows["src"]["site_url"] == f"{site}/discharges/all/?id=zz-feed~3Asrc&y=2025"
    assert rows["undated"]["site_url"] == f"{site}/discharges/all/?id=zz-feed~3Aundated&y=undated"
    # a state-year with more than ARCHIVE_SPLIT records lists its months
    monkeypatch.setattr(C, "ARCHIVE_SPLIT", 1)
    rows = csv_rows(tmp_path / "b", events, page_ids=None, active_ids={old["event_id"]})
    assert rows["old"]["site_url"] == f"{site}/event/ma-massdep~3Aold/"                       # active.json: a page
    assert rows["ongoing"]["site_url"] == f"{site}/discharges/ma/2024/12/#ma-massdep~3Aongoing"
    assert rows["md"]["site_url"] == f"{site}/discharges/md/2025/#ma-massdep~3Amd"            # one record: no split


# P3-1 ---------------------------------------------------------------- guard drops in no-outfall placements

def test_p3_1_waters_the_guard_sets_aside_from_a_no_outfall_placement_are_recorded_and_the_note_counts_them():
    waters = world(tmp_events([]))["waters"]
    rows = [{"npdes_permit": "MA0000001", "outfall": "001", "water_slug": "test-river-ma", "lat": 42.0, "lon": -71.95,
             "match": "geometry", "distance_m": 0},
            {"npdes_permit": "MA0000001", "outfall": "002", "water_slug": "test-bay-ma", "lat": 42.05, "lon": -70.95,
             "match": "geometry", "distance_m": 0}]
    r = S.Resolver(waters, rows, {}, {}, {"no_outfall_all_waters": True})
    cso = ended("cso", npdes_permit="MA0000001", water_slugs=[], lat=42.009, lon=-71.95)       # 1 km from the river
    pl = r.resolve(cso)
    assert pl["water_slugs"] == ["test-river-ma"] and pl["water_match"] == "inferred"
    assert pl["note"].startswith(S.NO_OUTFALL_NOTE + " (2 waters")
    assert "placed on 1 of these 2 waters; the placement guard set aside 1" in pl["note"]
    assert [a["water_slug"] for a in pl["set_aside"]] == ["test-bay-ma"] and "too far" in pl["set_aside"][0]["reason"]


# P3-2 ---------------------------------------------------------------- "no release" with an unreliable reading

@pytest.mark.parametrize("text,confirmed", [
    ("NO OVERFLOW - INSTRUMENTATION ISSUES", False), ("No release (meter offline)", False),
    ("No overflow - estimate pending", False), ("No discharge - unknown, sensor failure", False),
    ("No spill - under investigation", False), ("No release - SCADA communication lost", False),
    ("No release", True), ("NO SPILL - Change of conveyance", True), ("N/A - No spill", True), ("0 Did not overflow", True)])
def test_p3_2_a_no_release_that_says_its_reading_is_unreliable_counts_as_released(text, confirmed):
    e = ended("nr", water_slugs=[], volume_text=text)
    assert bool(S.no_release(e)) is confirmed, text


# P3-8 ---------------------------------------------------------------- DEQ PReP grouping across volumes

def test_p3_8_a_report_with_no_volume_does_not_join_two_reports_with_different_volumes():
    from ingest import va_deq_prep as P
    from tests.test_ingest_va import REFS, _api

    def rep(rid, minute, vol):
        return P.to_record(P.from_api(_api(id=rid, ssorsId=None, nrcId=None, siteAddress1="12 Example Mill Rd",
                                           incidentDateTime=f"2026-10-11T09:{minute}:00", receptorEstimateLow=vol,
                                           receptorEstimateHigh=vol, prepReportSewages=[{"dischargeVolume": vol}])),
                           REFS, None, "x")
    a, b, c = rep("400001", "10", 100), rep("400002", "20", None), rep("400003", "30", 200)
    assert (a["volume_gal"], b["volume_gal"], c["volume_gal"]) == (100, None, 200)
    assert P.mark_duplicates([a, b, c]) == 1
    assert b["duplicate_of"] == a["event_id"] and a["duplicate_of"] is None and c["duplicate_of"] is None
    # the same volume, or none, still makes one event
    d, e, f = rep("400011", "10", 100), rep("400012", "20", None), rep("400013", "30", 100)
    assert P.mark_duplicates([d, e, f]) == 2 and e["duplicate_of"] == f["duplicate_of"] == d["event_id"]


# P3-9 ---------------------------------------------------------------- the OSM time budget, chunk by chunk

def test_p3_9_the_osm_budget_is_checked_before_each_chunk_of_a_state(monkeypatch):
    import types
    from ingest import waters_from_nhd as W
    asked = []

    def fetch(q, *a_, **k):
        asked.append(q)
        return {"elements": [], "osm3s": None, "_fetched_at": None}, "m"
    monkeypatch.setattr(W, "state_fetch", fetch)
    monkeypatch.setattr(W, "state_query", lambda names, box: tuple(names))
    monkeypatch.setattr(W.WX, "is_cached", lambda *a_, **k: False)
    monkeypatch.setattr(W, "osm_spec", lambda t, towns: {"key": f"k-{t['name']}", "name": t["name"],
                                                         "box": (0.0, 0.0, 1.0, 1.0), "osm_names": []})
    monkeypatch.setattr(W, "state_chunks", lambda specs: [([sp["name"]], (0, 0, 1, 1)) for sp in specs])  # one name each
    monkeypatch.setattr(W, "mirror_order", lambda **k: ["m"])
    monkeypatch.setattr(W, "osm_record", lambda *a_, **k: (None, "no OSM feature of that name near the points"))
    clock = iter([0.0, 1.0, 2.0, 10.0, 11.0])        # start, state check, chunk 1, chunk 2 (over budget) ...
    monkeypatch.setattr(W.time, "monotonic", clock.__next__)
    ts = [{"name": n, "state": "MA", "key": f"MA|{n}", "events": 1, "outfalls": 0, "points": [[0, 0]], "words": ["brook"]}
          for n in ("Alpha Brook", "Beta Brook", "Gamma Brook")]
    rows = [{"reason": "no NHD feature", "how": None} for _ in ts]
    fake = types.SimpleNamespace(args=types.SimpleNamespace(osm_max=600, refresh=False, offline=False, osm_budget=5.0),
                                 osm_queue=list(zip(ts, rows)), towns={}, osm_used=0, osm_remaining=[], feats={},
                                 states={}, existing_list=[], problems=[], attach=lambda *a_: None)
    W.Run.osm_state_pass(fake)
    assert asked == [("Alpha Brook",)]                                      # the second chunk was over the budget
    assert "no OSM feature" in rows[0]["reason"] and "left for the next run" not in rows[0]["reason"]
    assert all("time budget used" in r["reason"] and "left for the next run" in r["reason"] for r in rows[1:])
    assert fake.osm_remaining == ["MA: Beta Brook", "MA: Gamma Brook"]
    assert fake.osm_states["MA"]["failed"].startswith("time budget") and fake.osm_states["MA"]["sent"] == 1


# P3-7 ---------------------------------------------------------------- repository paths in placement texts

@pytest.mark.parametrize("note,want", [
    # the registries named in public words (wording scan 2026-11-03), not only without their paths
    ("outfall not stated in the report; shown on every water this permit's outfalls discharge to (2 waters from the 13 "
     "registry outfalls of CT0100412; data/outfalls-new-england.json)",
     "outfall not stated in the report; shown on every water this permit's outfalls discharge to (2 waters from the 13 "
     "listed outlets of CT0100412)"),
    ("placed by outfall 024 of permit CT0100366 (outfall registry): 024 to Long Island Sound (its water slug, geometry "
     "match, 0 m); from its per-outfall volume text (no release at 021, 025) (data/outfalls-new-england.json)",
     "placed by outfall 024 of permit CT0100366 (EPA and state outlet records): 024 to Long Island Sound (its water "
     "slug, geometry match, 0 m); from its per-outfall volume text (no release at 021, 025)"),
    ("water from the outfall registry (data/outfalls-mid-atlantic.json, data/outfalls-new-england.json): every listed outfall",
     "water from the outlet list in EPA and state records: every listed outfall"),
    ("the report names no water and the operator lists 2 receiving waters (data/dischargers.json)",
     "the report names no water and the operator lists 2 receiving waters (our list of sewer operators)"),
    ("water from data/dischargers.json: the operator's single listed receiving water (Test River)",
     "water from our list of sewer operators: the operator's single listed receiving water (Test River)"),
    ("the report names no water and no outfall the registry lists", "the report names no water and no outlet listed in EPA and state records"),
    ("the report names no water and VA0081302's 12 registry outfalls discharge to 2 waters",
     "the report names no water and VA0081302's 12 listed outlets discharge to 2 waters"),
    ("the outfall registry gives it no water record", "the outlet list in EPA and state records gives it no water record"),
    ("see docs/decisions.md for why", "see for why"),
    ("contained on site/ground near the plant", "contained on site/ground near the plant")])
def test_p3_7_placement_texts_name_the_registries_in_words_not_paths(note, want):
    assert X.public_note(note) == want
    assert X.note_wording({"placement_note": X.public_note(note)}) == []


def test_p3_7_the_export_checks_the_records_placement_texts_and_more_files(data_dir):
    rec = {"placement_note": "from data/outfalls-new-england.json", "unplaced_reason": "fixture row",
           "set_aside": [{"water_slug": "x", "reason": "see research/ma/report.md"}]}
    assert X.note_wording(rec) == ["placement_note", "unplaced_reason", "set_aside"]
    e = ended("p", water_slugs=[])
    r = R.redactor_for([e], data_dir)
    pl = {"water_slugs": [], "note": "x (data/dischargers.json)", "set_aside": [{"water_slug": "y", "reason": "z (data/outfalls-new-england.json)"}]}
    out = X.public_record(e, pl, r)
    assert out["placement_note"] == "x (our list of sewer operators)" and out["set_aside"][0]["reason"] == "z"
    src = inspect.getsource(X.export)
    assert '"active.json", "dischargers.json"' in src and "wording.update(note_wording(rec))" in src


# SOL review of 2026-11-03 ------------------------------------------------------------------------------------------

def test_sol_p1_1_monthly_labels_and_names_are_redacted_and_the_map_payloads_are_checked(tmp_path, data_dir):
    from tests.test_monthly_mark import month_rec
    rec = month_rec("m", "2026-10", outfall="002", volume_text=f"per {NAME} {PHONE} zorvan@example.org",
                    outfall_name=f"behind {NAME}'s yard")
    st, _ = S.build(now=datetime(2026, 11, 10, tzinfo=UTC), write=False, **world(tmp_events([rec])))
    assert NAME in st["monthly_outfalls"][0]["label"]                    # the status quotes the record as written
    _, events, _ = S.load_events(tmp_events([rec]))
    r = R.redactor_for(events, data_dir)
    red = R.redact_events(events, data_dir, redactor=r)
    swaps = {e["event_id"]: R.quote_swaps(o, e) for o, e in zip(events, red)}
    X.redact_status_texts(st, r, swaps)
    text = json.dumps(st)
    for part in (*NAME.split(), PHONE, "zorvan@example.org"):
        assert part not in text, part
    assert "monthly-outfalls.json" in X.PUBLIC_PAYLOADS and "overlays.geojson" in X.PUBLIC_PAYLOADS
    out = tmp_path / "out"
    (out / "waters").mkdir(parents=True)
    X.write_compact(out / "events.json", {"events": []})
    X.write_compact(out / "monthly-outfalls.json", {"outfalls": [{"label": f"4 days ({NAME})"}]})
    assert X.blocklist_hits(out, [NAME]) == ["monthly-outfalls.json"]


def test_sol_p1_2_a_negation_is_scoped_to_its_clause_and_water():
    text = "Did not impact Test River; sewage entered Other Pond"
    assert S.stated_no_water(text) is None and S.negated_clauses(text) == ["Did not impact Test River"]
    assert S.stated_no_water("sewage entered Bear Creek but was contained") is None
    mixed = ended("mixed", event_type="sso", water_slugs=[], waterbody_text=text)
    # the ingester placed this one on the pond; the negation names the river only: it stays on the pond
    explicit = ended("explicit", event_type="sso", water_slugs=["other-pond-ma"], water_match="outfall_registry",
                     waterbody_text="the discharge did not reach Test River")
    blanket = ended("blanket", event_type="sso", water_slugs=["other-pond-ma"], water_match="outfall_registry",
                    waterbody_text="Did not reach waters of the State")
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([mixed, explicit, blanket])))
    pl = st["placements"]
    assert pl[mixed["event_id"]]["water_slugs"] == ["other-pond-ma"] and "no_receiving_water" not in pl[mixed["event_id"]]
    assert "did not reach Test River (not placed there)" in pl[mixed["event_id"]]["note"]
    assert pl[explicit["event_id"]]["water_slugs"] == ["other-pond-ma"]
    assert pl[blanket["event_id"]]["water_slugs"] == [] and pl[blanket["event_id"]]["no_receiving_water"]


def test_sol_p2_7_a_newer_zero_month_clears_an_older_monthly_mark(tmp_path):
    from ingest import nj_echo_monthly as NJM
    from tests.test_monthly_mark import month_rec
    aug = month_rec("aug", "2026-08", outfall="002")
    d = tmp_events([aug])
    meta = {"latest_month_by_outfall": {"MA0025321|002": {"month": "2026-09", "discharged": False, "days": 0}}}
    p = d / "ma-test.json"
    body = json.loads(p.read_text())
    p.write_text(json.dumps({**body, "source_id": "nj-echo-monthly", "meta": meta}))
    st, _ = S.build(now=datetime(2026, 11, 3, 12, tzinfo=UTC), write=False, **world(d))
    assert st["monthly_outfalls"] == [] and st["waters"]["test-river-ma"]["status"] == "grey"
    p.write_text(json.dumps({**body, "source_id": "nj-echo-monthly", "meta": {}}))
    st, _ = S.build(now=datetime(2026, 11, 3, 12, tzinfo=UTC), write=False, **world(d))
    assert [m["event_id"] for m in st["monthly_outfalls"]] == [aug["event_id"]]
    cells = {("NJ1", "002", "31-AUG-26", 1): {"DMRValueNmbr": "3", "ValueReceivedDate": "15-SEP-26"},
             ("NJ1", "002", "30-SEP-26", 1): {"DMRValueNmbr": "0", "ValueReceivedDate": "15-OCT-26"},
             ("NJ1", "003", "30-SEP-26", 1): {"NODICode": "C"},
             ("NJ1", "004", "30-SEP-26", 1): {"NODICode": "9"}}
    got = NJM.latest_months(cells)
    assert got["NJ1|002"]["month"] == "2026-09" and got["NJ1|002"]["discharged"] is False
    assert got["NJ1|003"]["discharged"] is False and "NJ1|004" not in got


def test_sol_p2_8_monthly_reasons_carry_no_repository_reference_and_the_check_covers_them():
    from tests.test_monthly_mark import month_rec
    st, _ = S.build(now=datetime(2026, 11, 3, 12, tzinfo=UTC), write=False,
                    **world(tmp_events([month_rec("sep", "2026-09")])))
    r = st["waters"]["test-river-ma"]["reasons"][0]
    assert r["rule"] == "monthly" and "docs/" not in json.dumps(r) and r["rule_applied"]["methods"] == "monthly"
    assert X.wording_in_status(st) == []
    r["rule_applied"]["rationale"] += " (docs/plan.md)"
    st["monthly_outfalls"][0]["label"] += " see research/nj/report.md"
    assert X.wording_in_status(st) == ["waters.test-river-ma.reasons[0].rule_applied.rationale", "monthly_outfalls[0].label"]


# owner, 2026-11-03: a report with no end is assumed to stop ------------------------------------------------------

def test_a_no_end_window_counts_from_the_sources_report_time_never_from_an_extract_date():
    nh = ev("nh", source_id="echo-sewer-overflow", event_type="bypass", status="unknown",
            started_at="2022-12-27T06:00:00", reported_at="2022-12-29", published_at="2026-11-03",
            water_slugs=["test-river-ma"])
    assert S.color_of(S.overlapping(S.event_intervals(nh, "NH", NOW), NOW)) == "grey"
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([nh])))
    assert st["waters"]["test-river-ma"]["status"] == "grey"
    assert "assumes the discharge ended 30 days after it began (Jan 26, 2023)" in st["placements"][nh["event_id"]]["note"]
    assert st["placements"][nh["event_id"]]["end_assumed_at"] == "2023-01-26T11:00:00Z"
    # no reported_at: the publication time; neither: the start
    pub = ev("pub", status="unknown", started_at=iso(NOW - 3 * 24 * H), published_at=iso(NOW - 2 * 24 * H))
    ivs = S.event_intervals(pub, "MA", NOW)
    assert ivs[0]["rule"] == "no_end" and ivs[0]["start"] == NOW - 2 * 24 * H and ivs[0]["end"] == NOW + 12 * 24 * H
    bare = ev("bare", status="unknown", started_at=iso(NOW - 3 * 24 * H))
    assert S.event_intervals(bare, "MA", NOW)[0]["start"] == NOW - 3 * 24 * H


def test_no_report_without_an_end_colours_anything_30_days_after_it_began():
    d = 24 * H
    late = ev("late", status="unknown", started_at=iso(NOW - 25 * d), reported_at=iso(NOW - 20 * d))
    ivs = S.event_intervals(late, "MA", NOW)
    assert [(iv["rule"], iv["start"], iv["end"]) for iv in ivs if iv["color"] != "grey"] == \
        [("no_end", NOW - 20 * d, NOW - 6 * d), ("unresolved", NOW - 6 * d, NOW + 5 * d)]   # day 30 after it began
    very_late = ev("vl", status="unknown", started_at=iso(NOW - 45 * d), reported_at=iso(NOW - 2 * d))
    ivs = S.event_intervals(very_late, "MA", NOW)
    assert all(iv["color"] == "grey" for iv in ivs) and ivs[0]["rule"] == "end_never_reported"   # flagged, no colour
    old_ongoing = ev("og", status="ongoing", started_at=iso(NOW - 31 * d))
    assert S.color_of(S.overlapping(S.event_intervals(old_ongoing, "MA", NOW), NOW)) == "grey"
    assert S.end_assumed(old_ongoing, NOW, TEST_RULES) == NOW - d
    assert S.end_assumed({**old_ongoing, "ended_at": iso(NOW - 30 * d)}, NOW, TEST_RULES) is None
    rules = json.loads((S.DATA_DIR / "rules.json").read_text())
    u = rules["unresolved"]
    assert u["end_assumed_rationale"].startswith("A report with no end is shown as unresolved for 30 days after it began")
    assert {int(n) for n in __import__("re").findall(r"(\d+) days", u["end_assumed_rationale"])} == {u["unresolved_yellow_days"]}
