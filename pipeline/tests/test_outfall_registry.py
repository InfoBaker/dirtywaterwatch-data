"""The national outfall registry (docs/national-outfalls.md): one loader over every data/outfalls-*.json and the
provisional places from the reports, the live-state gate, the operator and water lists, out/outfalls.json, the radar
point list and the rain caution's outfalls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build import rain_likely as RL  # noqa: E402
from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from export import outfalls as XO  # noqa: E402
from ingest import rainfall as RF  # noqa: E402


def row(permit, outfall, state=None, **f):
    return {"npdes_permit": permit, "outfall": outfall, "state": state or permit[:2], "outfall_status": "CSO",
            "permittee": f"{permit} AUTH", "lat": 41.9, "lon": -75.6, "water_slug": None, "match": "none", **f}


def write(d: Path, name: str, rows, raw: str | None = None):
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw if raw is not None else json.dumps({"outfalls": rows}))
    return p


# ---------------------------------------------------------------- the loader

def test_one_row_per_permit_and_outfall_number_and_the_more_specific_file_wins(tmp_path):
    write(tmp_path, "outfalls-new-england.json", [row("MA0100001", "001", water_slug="ne-river-ma"),
                                         row("MA0100001", "1", water_slug="later-river-ma")])
    write(tmp_path, "outfalls-us.json", [row("MA0100001", "1", water_slug="us-river-ma"),
                                         row("OH0100001", "002", water_slug="ohio-river-oh")])
    write(tmp_path, "outfalls-plants-us.json", [row("MA0100001", "01", outfall_kind="cso"),
                                                row("MA0100001", "100"), row("OH0100001", "2")])
    rows = {(r["npdes_permit"], common.outfall_number(r["outfall"])): r for r in common.load_outfall_registry(tmp_path)}
    assert len(rows) == 3
    assert rows[("MA0100001", "1")]["water_slug"] == "ne-river-ma"                  # regional over national, first in file
    assert rows[("MA0100001", "1")]["_file"] == "data/outfalls-new-england.json"
    assert rows[("MA0100001", "100")]["outfall_kind"] == "plant"                      # a plants file's rows are plants
    assert rows[("OH0100001", "2")]["outfall_kind"] == "cso"                          # the plant row never replaces it
    assert rows[("OH0100001", "2")]["_file"] == "data/outfalls-us.json"
    assert all(r["country"] == "US" for r in rows.values())
    assert common.outfall_number("001A") == common.outfall_number("01A") == "1A" and common.outfall_number("000") == "0"


def test_within_a_file_an_open_listing_replaces_a_closed_one_and_a_row_keeps_its_own_kind_and_country(tmp_path):
    write(tmp_path, "outfalls-mid-atlantic.json", [
        row("NY0027766", "001A", outfall_status="CLS"), row("NY0027766", "01A", outfall_status="TCS"),
        row("NY0027766", "002", outfall_status="CSO"), row("NY0027766", "2", outfall_status="CLS"),
        row("ON0000001", "1", state="ON", country="ca", outfall_kind="plant")])
    rows = {(r["npdes_permit"], common.outfall_number(r["outfall"])): r for r in common.load_outfall_registry(tmp_path)}
    assert rows[("NY0027766", "1A")]["outfall_status"] == "TCS"
    assert rows[("NY0027766", "2")]["outfall_status"] == "CSO"
    assert rows[("ON0000001", "1")]["country"] == "CA" and rows[("ON0000001", "1")]["outfall_kind"] == "plant"


def test_a_half_written_file_is_skipped_and_noted_and_the_others_still_load(tmp_path):
    write(tmp_path, "outfalls-new-england.json", [row("MA0100001", "001")])
    write(tmp_path, "outfalls-us.json", None, raw='{"outfalls": [{"npdes_permit": "OH01')
    rows = common.load_outfall_registry(tmp_path)
    assert [r["npdes_permit"] for r in rows] == ["MA0100001"]
    assert common.OUTFALL_REGISTRY_SKIPPED == ["data/outfalls-us.json: not read (JSONDecodeError)"]
    assert common.load_outfall_registry(tmp_path / "nowhere") == [] and common.OUTFALL_REGISTRY_SKIPPED == []


def test_the_status_wrappers_read_the_whole_registry_and_placement_leaves_the_provisional_places_out(tmp_path, monkeypatch):
    write(tmp_path, "outfalls-new-england.json", [row("MA0100001", "001")])
    write(tmp_path, "outfalls-mid-atlantic.json", [row("PA0023736", "002"), row("PA0023736", "003")])
    write(tmp_path, "build/outfalls-reported.json", [row("PA0023736", "MH-7", outfall_kind="reported",
                                                         record_status="provisional")])
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    assert sorted((r["npdes_permit"], r["outfall"]) for r in S.load_outfalls()) == [
        ("MA0100001", "001"), ("PA0023736", "002"), ("PA0023736", "003"), ("PA0023736", "MH-7")]
    assert all("_file" not in r for r in S.load_outfalls())
    placement = S.load_registry_outfalls()
    assert sorted(r["outfall"] for r in placement) == ["001", "002", "003"]
    assert {r["_file"] for r in placement} == {"data/outfalls-new-england.json", "data/outfalls-mid-atlantic.json"}
    assert len(S.load_registry_outfalls(provisional=True)) == 4


# ---------------------------------------------------------------- provisional places from the reports

def test_provisional_places_never_replace_an_official_row_and_superseded_ones_are_left_out(tmp_path):
    write(tmp_path, "outfalls-mid-atlantic.json", [row("NY0026191", "004", water_slug="official-creek-ny")])
    write(tmp_path, "build/outfalls-reported.json", [
        row("NY0026191", "4", outfall_kind="cso", coords_from="report", record_status="provisional",
            water_slug="nldi-creek-ny"),                                        # the official row wins
        row("NY0026191", "017", outfall_kind="cso", coords_from="report", record_status="provisional"),
        {"discharger_id": "ny-some-village", "state": "NY", "lat": 42.1, "lon": -76.2, "outfall_kind": "reported",
         "record_status": "confirmed", "confidence": "high", "report_count": 4, "last_report_at": "2026-10-30T12:00:00Z",
         "event_ids": ["a", "b"], "reached_water": "yes"},                       # no permit, no outfall id: its own row
        {"discharger_id": "ny-some-village", "state": "NY", "lat": 42.2, "lon": -76.3, "outfall_kind": "reported",
         "record_status": "superseded"},
        {"state": "NY", "lat": 42.3, "lon": -76.4}])                            # neither permit nor operator: left out
    rows = common.load_outfall_registry(tmp_path)
    by = {(r.get("npdes_permit"), r.get("outfall")): r for r in rows}
    assert by[("NY0026191", "004")]["water_slug"] == "official-creek-ny" and not common.is_provisional(by[("NY0026191", "004")])
    assert by[("NY0026191", "017")]["outfall_kind"] == "cso" and by[("NY0026191", "017")]["record_status"] == "provisional"
    assert by[(None, None)]["outfall_kind"] == "reported" and by[(None, None)]["record_status"] == "confirmed"
    assert by[(None, None)]["_file"] == "data/build/outfalls-reported.json"
    assert len(rows) == 3
    assert len(common.load_outfall_registry(tmp_path, provisional=False)) == 1
    write(tmp_path, "build/outfalls-reported.json", None, raw="[{")            # half-written: noted, the rest loads
    assert len(common.load_outfall_registry(tmp_path)) == 1
    assert common.OUTFALL_REGISTRY_SKIPPED == ["data/build/outfalls-reported.json: not read (JSONDecodeError)"]


# ---------------------------------------------------------------- operator and water pages, out/outfalls.json

DIS = [{"id": "pa-pa0023736", "name": "TRI-BORO MUN AUTH", "state": "PA", "npdes_permit": "PA0023736", "npdes_permits": ["PA0023736"]},
       {"id": "ma-two-permits", "name": "Two Permits", "state": "MA", "npdes_permit": "MA0100001",
        "npdes_permits": ["MA0100001", "MA0100002"], "aliases": ["ma-old-id"]},
       {"id": "ny-some-village", "name": "Some Village", "state": "NY", "npdes_permit": None, "npdes_permits": []}]
LIVE = {"MA", "PA", "NY", "NJ"}


def registry(tmp_path):
    write(tmp_path, "outfalls-new-england.json", [row("MA0100001", "001", water_slug="ne-river-ma", match="geometry+name"),
                                         row("MA0100002", "005", outfall_status="CLS")])
    write(tmp_path, "outfalls-mid-atlantic.json", [
        row("PA0023736", "002", water_slug="susquehanna-river-pa", match="geometry+name", receiving_water_echo="Susquehanna River"),
        row("PA0023736", "003", water_slug=None, receiving_water_echo="Susquehanna River"),          # no water record
        row("PA0023736", "004", lat=None, lon=None),                     # neither a point nor a water: not drawn
        row("DC0021199", "019", receiving_water_echo="Potomac River",
            receiving_water_override={"water": "Anacostia River", "basis": "x"})])
    write(tmp_path, "outfalls-us.json", [row("OH0024741", "001", water_slug="ohio-river-oh")])    # not live
    write(tmp_path, "outfalls-plants-us.json", [row("PA0023736", "101"),
                                                row("PA0099999", None, coords_from="facility")])
    write(tmp_path, "build/outfalls-reported.json", [
        {"discharger_id": "ny-some-village", "state": "NY", "lat": 42.1, "lon": -76.2, "outfall_kind": "reported",
         "outfall_name": "12 Elm Street", "record_status": "provisional", "confidence": "medium", "report_count": 2,
         "last_report_at": "2026-10-30T12:00:00Z", "event_ids": ["e1", "e2"], "reached_water": "unknown"}])
    return common.load_outfall_registry(tmp_path)


def test_an_operator_with_only_mid_atlantic_outfalls_gets_them_on_its_page_and_the_live_gate_holds(tmp_path):
    rows = S.live_outfalls(registry(tmp_path), LIVE)
    assert {S.outfall_state(r) for r in rows} == {"MA", "PA", "NY"}               # OH and DC are not live here
    by_water, by_permit, by_operator = X.outfall_lists(rows, common.discharger_alias_map(DIS))
    tri = X.operator_outfalls(DIS[0], by_permit, by_operator)
    assert [(o["outfall"], o["outfall_kind"]) for o in tri] == [("002", "cso"), ("003", "cso"), ("004", "cso"), ("101", "plant")]
    assert tri[0]["receiving_water"] == "Susquehanna River" and tri[0]["water_slug"] == "susquehanna-river-pa"
    two = X.operator_outfalls(DIS[1], by_permit, by_operator)                     # every permit the operator holds
    assert [(o["npdes_permit"], o["outfall"], o["outfall_status"]) for o in two] == [
        ("MA0100001", "001", "CSO"), ("MA0100002", "005", "CLS")]
    village = X.operator_outfalls(DIS[2], by_permit, by_operator)                 # a provisional place, no address
    assert len(village) == 1 and village[0]["record_status"] == "provisional" and village[0]["outfall_name"] is None
    assert village[0]["report_count"] == 2 and village[0]["event_ids"] == ["e1", "e2"]
    assert [o["outfall"] for o in by_water["susquehanna-river-pa"]] == ["002"]
    assert "ohio-river-oh" not in by_water


def test_out_outfalls_rows_follow_the_contract_with_or_without_a_water_record_and_live_states_only(tmp_path):
    rain = {"PA0023736": {"status": "likely", "rain_24h_in": 1.3, "threshold_in": 0.1, "threshold_kind": "site_default",
                          "valid_time": "2026-11-03T20:00:00Z", "episode": "rain_likely:PA0023736:20261103T16Z",
                          "name": "TRI-BORO", "waters": ["x"]},
            "MA0100002": {"status": "below", "rain_24h_in": 0.0, "threshold_in": 0.5, "threshold_kind": "state"}}
    out = XO.outfall_rows(registry(tmp_path), LIVE, waters={"ne-river-ma", "susquehanna-river-pa"}, dischargers=DIS,
                          rain_permits=rain)
    by = {(r["npdes_permit"], r["outfall_id"]): r for r in out}
    assert set(by) == {("MA0100001", "001"), ("MA0100002", "005"), ("PA0023736", "002"), ("PA0023736", "003"),
                       ("PA0023736", "101"), ("PA0099999", ""), (None, "")}
    assert by[("PA0099999", "")]["coords_from"] == "facility" and "coords_from" not in by[("PA0023736", "101")]
    tri = by[("PA0023736", "002")]
    assert list(tri) == ["source_id", "npdes_permit", "outfall_id", "outfall_kind", "outfall_status", "discharger_id",
                         "permittee", "state", "lat", "lon", "receiving_water", "water_slugs", "water_match", "rain"]
    assert tri["discharger_id"] == "pa-pa0023736" and tri["water_slugs"] == ["susquehanna-river-pa"]
    assert tri["rain"] == {"status": "likely", "rain_24h_in": 1.3, "threshold_in": 0.1, "threshold_kind": "site_default",
                           "trigger_basis": "default",
                           "valid_time": "2026-11-03T20:00:00Z", "episode": "rain_likely:PA0023736:20261103T16Z"}
    assert by[("PA0023736", "003")]["water_slugs"] == [] and by[("PA0023736", "003")]["lat"] == 41.9   # still exported
    assert by[("PA0023736", "101")]["outfall_kind"] == "plant" and by[("PA0023736", "101")]["rain"] is None
    closed = by[("MA0100002", "005")]
    assert closed["outfall_status"] == "CLS" and closed["rain"] is None and closed["discharger_id"] == "ma-two-permits"
    prov = by[(None, "")]
    assert prov["outfall_kind"] == "reported" and prov["record_status"] == "provisional" and prov["rain"] is None
    assert prov["discharger_id"] == "ny-some-village" and prov["reached_water"] == "unknown" and "outfall_name" not in prov
    assert not any(r["state"] in ("OH", "DC") for r in out)
    # a state going live brings its rows, with the reviewed receiving water
    dc = XO.outfall_rows(registry(tmp_path), LIVE | {"DC"})
    assert [r["receiving_water"] for r in dc if r["state"] == "DC"] == ["Anacostia River"]
    p = XO.write(out, tmp_path / "out", "2026-11-03T21:00:00Z")
    doc = json.loads(p.read_text())
    assert doc["count"] == len(out) and "data/" not in json.dumps(doc) and ", " not in p.read_text()[:40]


def test_the_massdep_ids_and_the_monthly_marks_join_the_registry_rows(tmp_path):
    rows = registry(tmp_path)
    layer = {"SPR010": {"dep_id": "SPR010", "npdes": "MA0100001", "outfall": "1", "lat": 42.1, "lon": -72.6},
             "SPR099": {"dep_id": "SPR099", "npdes": "MA0109999", "outfall": "9", "lat": 42.2, "lon": -72.6}}
    marks = [{"npdes_permit": "MA0100001", "outfall_id": "1", "status": "monthly", "days": 3, "month": "2026-09",
              "label": "3 days", "event_id": "m1"},
             {"npdes_permit": "NJ0025321", "outfall_id": "002", "status": "monthly", "days": 1, "month": "2026-09",
              "label": "1 day", "event_id": "m2", "lat": 40.78, "lon": -73.99, "source_id": "nj-echo-monthly",
              "water_slugs": ["hudson-river-nj"]},
             {"npdes_permit": "OH0024741", "outfall_id": "001", "status": "monthly", "event_id": "m3"}]   # not live
    out = XO.outfall_rows(rows, LIVE, dischargers=DIS, ma_layer=layer, marks=marks)
    dep = {r["outfall_id"]: r for r in out if r["source_id"] == "ma-massdep"}
    assert dep["SPR010"]["alias_of"] == "MA0100001:001" and dep["SPR010"]["water_slugs"] == ["ne-river-ma"]
    assert dep["SPR099"]["alias_of"] is None
    echo = next(r for r in out if r["npdes_permit"] == "MA0100001" and r["source_id"] == "echo")
    assert echo["status"] == "monthly" and echo["days"] == 3 and "status" not in dep["SPR010"]
    nj = next(r for r in out if r["npdes_permit"] == "NJ0025321")
    assert nj["status"] == "monthly" and nj["state"] == "NJ" and nj["outfall_kind"] == "cso"
    assert not any(r["npdes_permit"] == "OH0024741" for r in out)


# ---------------------------------------------------------------- the radar and the caution

def test_the_radar_reads_open_combined_sewer_outfalls_of_live_states_only(tmp_path, monkeypatch):
    registry(tmp_path)
    write(tmp_path, "outfalls-mid-atlantic.json", [row("PA0023736", "002"), row("PA0023736", "009", outfall_status="CLS"),
                                                   row("NJ0108812", "004"), row("NJ0108880", "025")])
    write(tmp_path, "build/nj-cso-likely-history.json", None, raw=json.dumps({"observations": {"NJ0108880": []}}))
    write(tmp_path, "build/outfalls-reported.json", [
        row("NY0026191", "017", outfall_kind="cso", coords_from="report", record_status="provisional"),
        row("NY0026191", "MH-3", outfall_kind="reported", record_status="provisional")])
    monkeypatch.setattr(RF, "DATA_DIR", tmp_path)
    monkeypatch.setattr(RF, "BUILD_DIR", tmp_path / "build")
    got = {(o["permit"], o["outfall"]): o for o in RF.cso_outfalls(live=LIVE)}
    assert set(got) == {("MA0100001", "001"), ("PA0023736", "002"), ("NY0026191", "017"), ("NJ0108812", "004")}
    # closed (CLS), plant, reported, a New Jersey permit on its shared site and a state not live are not read
    assert got[("NY0026191", "017")]["source"] == "reported-cso" and got[("PA0023736", "002")]["source"] == "echo-mid-atlantic"
    assert RF.radar_states({"MA", "NJ", "OH"}) == {"MA", "NJ", "OH"}


def test_the_caution_places_by_open_combined_sewer_outfalls_only():
    waters = {"cso-river-ma": {"kind": "river"}, "plant-river-ma": {"kind": "river"},
              "closed-river-ma": {"kind": "river"}, "reported-river-ma": {"kind": "river"}}
    outs = [{"npdes_permit": "MA0100001", "outfall": "1", "outfall_kind": "cso", "water_slug": "cso-river-ma"},
            {"npdes_permit": "MA0100001", "outfall": "2", "outfall_kind": "plant", "water_slug": "plant-river-ma"},
            {"npdes_permit": "MA0100001", "outfall": "3", "outfall_status": "CLS", "water_slug": "closed-river-ma"},
            {"npdes_permit": "MA0100001", "outfall": "4", "outfall_kind": "reported", "water_slug": "reported-river-ma",
             "record_status": "provisional"}]
    _, tags, _, _ = RL.targets("MA0100001", waters, outs, [], {}, lambda r, w: [])
    assert tags == {"cso-river-ma": "unmodeled"}
    assert RL.cso_open(outs[0]) and not any(RL.cso_open(o) for o in outs[1:])
    assert RL.cso_open({"outfall_kind": "cso", "record_status": "provisional"})


def test_the_rain_coverage_lists_live_states_only(monkeypatch):
    monkeypatch.setattr(S, "load_registry_outfalls", lambda provisional=False: [
        row("PA0023736", "002"), row("OH0024741", "001"), row("NY0026191", "MH-3", outfall_kind="reported")])
    monkeypatch.setattr(S, "states", lambda: {"PA", "NY"})
    got = X.rain_caution_states({"enabled": True, "permits": {}})
    assert "OH" not in got and "PA" in got


def test_provisional_rows_as_the_report_step_writes_them(tmp_path):
    """The provisional step's own shape: outfall is its place id, the outfall ids its reports name in outfall_ids,
    water_slugs a list, water_match a short code, on_map, and a discharger_id that may be no operator page."""
    write(tmp_path, "outfalls-new-england.json", [row("CT0100366", "015"), row("CT0100366", "016")])
    rep = lambda rid, **f: {"id": rid, "source_id": "outfalls-reported", "npdes_permit": "CT0100366", "state": None,
                            "lat": 41.3, "lon": -72.9, "outfall": rid, "outfall_kind": "reported",
                            "record_status": "provisional", "confidence": "high", "report_count": 3,
                            "last_report_at": "2026-10-01T00:00:00Z", "event_ids": ["x"], "reached_water": "yes",
                            "on_map": True, "water_slugs": [], "water_match": "none", "outfall_ids": [], **f}
    write(tmp_path, "build/outfalls-reported.json", [
        rep("rep-1", outfall_kind="cso", outfall_ids=["015", "16"]),                 # every named outfall official
        rep("rep-2", outfall_kind="cso", outfall_ids=["015", "019"], water_slugs=["quinnipiac-river-ct", "x-ct"],
            water_match="reports"),                                                 # 019 is not: it stays
        rep("rep-3", reached_water="no", on_map=False),
        rep("rep-4", npdes_permit=None, discharger_id="CT9999999", state="CT")])    # no operator page
    rows = common.load_outfall_registry(tmp_path)
    prov = {r["outfall"]: r for r in rows if common.is_provisional(r)}
    assert set(prov) == {"rep-2", "rep-3", "rep-4"}
    assert prov["rep-2"]["water_slug"] == "quinnipiac-river-ct" and prov["rep-2"]["match"] == "reports"
    live = S.live_outfalls(rows, {"CT"})
    assert {r["outfall"] for r in live} == {"015", "016", "rep-2", "rep-3", "rep-4"}     # state from the permit
    dis = [{"id": "ct-gnhwpca", "npdes_permit": "CT0100366", "npdes_permits": []}]
    by_water, by_permit, by_operator = X.outfall_lists(live)
    page = X.operator_outfalls(dis[0], by_permit, by_operator)
    assert [o["outfall"] for o in page] == ["015", "016", "rep-2", "rep-3"]
    assert page[3]["on_map"] is False and page[2]["record_status"] == "provisional"
    # the operator record lists them apart, so a page that knows only `outfalls` never shows one as a permitted outfall
    assert [o["outfall"] for o in X.official(page)] == ["015", "016"]
    assert [o["outfall"] for o in X.provisional(page)] == ["rep-2", "rep-3"]
    assert [o["outfall"] for o in by_water["x-ct"]] == ["rep-2"]
    out = {r["outfall_id"]: r for r in XO.outfall_rows(live, {"CT"}, dischargers=dis,
                                                         rain_permits={"CT0100366": {"status": "below"}})}
    assert "rep-3" not in out                                                    # not drawn: reached no water
    assert out["rep-2"]["rain"]["status"] == "below" and out["rep-2"]["water_match"] == "reports"
    assert out["rep-4"]["discharger_id"] is None and out["rep-4"]["source_id"] == "outfalls-reported"
    # a provisional place's receiving water is report text (not redacted here): left out, the water record stands
    noted = rep("rep-5", receiving_water="May be reaching Swan Creek; shared by a nearby owner")
    assert XO.receiving_water(noted) is None and XO.receiving_water(row("CT0100366", "015", receiving_water_echo="Mill River")) == "Mill River"


# ---------------------------------------------------------------- the live states: data/rules.json live_states

TWELVE = {"CT", "MA", "ME", "NH", "RI", "VT", "NJ", "NY", "PA", "MD", "VA", "DC"}   # the first twelve; the list grows


def test_the_live_states_are_the_rules_list_exactly(tmp_path, monkeypatch):
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    live = set(rules["live_states"])              # the list is the contract: states join it as they go live
    assert len(rules["live_states"]) == len(live) >= 12 and TWELVE <= live
    assert all(isinstance(s, str) and len(s) == 2 and s.isupper() for s in live)
    assert set(common.live_states()) == live
    monkeypatch.setattr(S, "_STATES", None)
    assert S.states() == live
    from build import reaches as R
    assert R.live_states() == live
    assert RF.radar_states() == live - RF.OUTSIDE_RADAR_GRID      # the radar grid is the contiguous states'
    waters = {"ohio-river-oh": {"state": "OH"}, "mill-river-ma": {"state": "MA"}}
    assert S.derive_states(waters, rules) == live                    # a water record opens no state
    assert "OH" in S.derive_states(waters, rules, live_only=False)    # a tool working beyond the live states
    assert S.derive_states(waters, {"red": {"by_state": {"CT": {}}}}) == {"OH", "MA", "CT"}   # rules without the list
    assert common.rules_live_states({"live_states": ["ma", "XX1", 3, "Oh"]}) == {"MA", "OH"}
    with pytest.raises(LookupError):
        common.live_states(tmp_path)
    (tmp_path / "rules.json").write_text(json.dumps({"version": "x"}))
    with pytest.raises(LookupError):
        common.live_states(tmp_path)


def test_a_water_record_of_a_state_not_live_reaches_no_status(monkeypatch):
    from tests.test_status import NOW, TEST_RULES, H, ev, iso, tmp_events, world
    monkeypatch.setattr(S, "_STATES", S._STATES)          # put back after the builds below
    line = {"type": "LineString", "coordinates": [[-84.5, 39.1], [-84.4, 39.1]]}
    oh = {"slug": "ohio-river-oh", "name": "Ohio River", "kind": "river", "state": "OH", "bbox": [-84.5, 39.1, -84.4, 39.1],
          "geometry": line}
    w = world(tmp_events([ev("1", status="ongoing", started_at=iso(NOW - 2 * H)),
                          ev("2", status="ongoing", started_at=iso(NOW - 2 * H), water_slugs=["ohio-river-oh"],
                             npdes_permit="OH0024741")]))
    w["waters"]["ohio-river-oh"] = oh
    w["outfalls"] = [{"npdes_permit": "OH0024741", "outfall": "001", "state": "OH", "outfall_kind": "cso",
                      "outfall_status": "CSO", "water_slug": "ohio-river-oh", "lat": 39.1, "lon": -84.45}]
    st, hist = S.build(now=NOW, write=False, rules={**TEST_RULES, "live_states": ["MA", "CT"]}, **w)
    assert S.states() == {"MA", "CT"}
    assert "test-river-ma" in st["waters"] and "ohio-river-oh" not in st["waters"]
    assert "ohio-river-oh" not in hist["waters"]
    assert all("ohio-river-oh" not in (pl.get("water_slugs") or []) for pl in st["placements"].values())
    assert S.live_waters(w["waters"], {"MA"}).keys() == {"test-river-ma", "other-pond-ma", "big-lake-ma", "test-bay-ma"}
    assert S.water_state("x-creek-oh") == "OH" and S.water_state("x", {"state": "va"}) == "VA"
    # the same record once its state is on the list is a water like any other
    st2, _ = S.build(now=NOW, write=False, rules={**TEST_RULES, "live_states": ["MA", "CT", "OH"]}, **w)
    assert S.states() == {"MA", "CT", "OH"}
    assert any("ohio-river-oh" in (pl.get("water_slugs") or []) for pl in st2["placements"].values())


def test_the_export_keeps_the_live_states_records_and_coverage_rows_only():
    src = Path(X.__file__).read_text()
    assert "waters = status_mod.live_waters(status_mod.load_waters())" in src
    assert 'cov["states"] = {k: v for k, v in (cov.get("states") or {}).items() if k in status_mod.states()}' in src
    assert "states=set(status_mod.states())," in src


def test_new_jersey_permits_off_the_shared_site_get_the_radar_caution_and_coverage_names_both_methods():
    from datetime import UTC, datetime, timedelta
    now = datetime(2026, 11, 3, 20, tzinfo=UTC)
    hours = [(now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:00:00Z") for h in range(5, -1, -1)]
    rain = {"rainfall": {"fetched_at": hours[-1], "mrms": {"valid_time": hours[-1]}, "permits": {
                "NJ0108812": {"state": "NJ", "h24": 1.4, "valid_time": hours[-1], "outfalls": []},
                "NJ0108880": {"state": "NJ", "h24": 2.0, "valid_time": hours[-1], "outfalls": []}}},
            "history": {"start": hours[0], "permits": {"NJ0108812": [1.4] * 6, "NJ0108880": [2.0] * 6}},
            "thresholds": {}, "dischargers": {}, "site_flags": {"permits": ["NJ0108880"]}}
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    _, _, block = RL.compute(rain, rules, [], now, now - timedelta(days=90), {}, [], {}, lambda r, w: [])
    camden = block["permits"]["NJ0108812"]
    assert camden["status"] == "likely" and camden["threshold_kind"] == "site_default" and camden["threshold_in"] == 0.1
    assert "NJ0108880" not in block["permits"]            # the site's own permit: the site's flag, never the radar too
    both = RL.caution_coverage({"enabled": True, "permits": {
        "NJ0108812": {**camden, "rainfall_read": "grid"},
        "NJ0108880": {"state": "NJ", "threshold_basis": "site_flag", "threshold_in": None, "waters": []}}},
        {"NJ": {"NJ0108812", "NJ0108880"}})["NJ"]
    assert sorted(both["methods"]) == ["radar", "site_flag"] and both["covered"]
    assert "radar" in both["sentence"] and "njcsonotifications.com" in both["sentence"] and "other" not in both["sentence"]
    assert both["threshold_kind"] == "site_default" and "this site's default amount of 0.1 in" in both["sentence"]
    assert "published" not in both["sentence"]


def test_an_aggregate_row_and_a_row_that_is_no_sewage_outfall_stay_off_the_map_and_the_radar(tmp_path, monkeypatch):
    write(tmp_path, "outfalls-new-england.json", [
        row("MA0100137", "C01", water_slug="connecticut-river-ma"), row("MA0100137", "C02"),
        row("MA0100137", "CSO", lat=None, lon=None, aggregate_of=["C01", "C02"], no_point_reason="x"),
        row("MAG250958", "003", outfall_status="CSO|NCW", outfall_kind="other", kind_note="cooling water")])
    rows = common.load_outfall_registry(tmp_path)
    assert sorted(r["outfall"] for r in rows) == ["003", "C01", "C02"]
    other = next(r for r in rows if r["outfall"] == "003")
    assert other["outfall_kind"] == "other" and not RL.cso_open(other)
    assert {r["outfall_id"] for r in XO.outfall_rows(rows, {"MA"})} == {"C01", "C02"}
    _, by_permit, _ = X.outfall_lists(rows)
    assert "MAG250958" not in by_permit
    monkeypatch.setattr(RF, "DATA_DIR", tmp_path)
    monkeypatch.setattr(RF, "BUILD_DIR", tmp_path / "build")
    assert {o["outfall"] for o in RF.cso_outfalls(live={"MA"})} == {"C01", "C02"}


def test_every_open_combined_sewer_outfall_of_a_live_state_has_a_point_or_says_why():
    live = set(common.live_states())
    rows = [o for o in common.load_outfall_registry(provisional=False) if S.outfall_state(o) in live
            and o["outfall_kind"] == "cso" and not str(o.get("outfall_status") or "").upper().startswith("CLS")]
    unexplained = [(o["npdes_permit"], o["outfall"]) for o in rows if (o.get("lat") is None or o.get("lon") is None)
                   and not o.get("no_point_reason") and not o.get("coords_problem")]
    assert unexplained == []
    placed = [o for o in rows if o.get("coords_from") == "state_layer"]
    assert all(o.get("coords_source") and o.get("lat") is not None for o in placed) and len(placed) >= 29


def test_an_operator_with_no_outfall_point_is_read_at_its_treatment_plant(tmp_path, monkeypatch):
    write(tmp_path, "outfalls-mid-atlantic.json", [
        row("MD0021598", "002", lat=None, lon=None, water_slug="wills-creek-md"),
        row("MD0021598", "003", lat=None, lon=None, water_slug="north-branch-potomac-river-md"),
        row("MD0067547", "001", lat=None, lon=None), row("MD0067547", "007", lat=39.64, lon=-78.82)])
    write(tmp_path, "outfalls-plants-us.json", [
        row("MD0021598", None, lat=39.70, lon=-78.70, coords_from="facility"),
        row("MD0021598", "001", lat=39.6245, lon=-78.754, coords_from="permitted_feature"),
        row("MD0067547", "101", lat=39.60, lon=-78.80, coords_from="permitted_feature"),
        row("MD0099999", "001", lat=39.0, lon=-77.0)])                      # a plant with no CSO outfall
    monkeypatch.setattr(RF, "DATA_DIR", tmp_path)
    monkeypatch.setattr(RF, "BUILD_DIR", tmp_path / "build")
    got = RF.cso_outfalls(live={"MD"})
    assert [(o["permit"], o["outfall"], o["lat"], o["source"]) for o in got] == [
        ("MD0067547", "007", 39.64, "echo-mid-atlantic"),                   # LaVale has an outfall point: no plant
        ("MD0021598", "001", 39.6245, "plant-point")]                        # Cumberland: the plant outfall first
    pts = RF.group_points(got)
    for p in pts.values():
        p["mrms"] = {"valid_time": "2026-11-03T20:00:00Z", "h24": 1.2, "read": "grid"}
    summary = RF.permit_summary(pts, got)
    assert summary["MD0021598"]["read"] == "plant_point" and summary["MD0067547"]["read"] == "grid"
    # the caution lands on the waters the outfalls' registry rows name, and says where the rain was read
    rows = common.load_outfall_registry(tmp_path)
    keys, tags, _, _ = RL.targets("MD0021598", {"wills-creek-md": {"kind": "river"},
                                                "north-branch-potomac-river-md": {"kind": "river"}},
                                  rows, summary["MD0021598"]["outfalls"], {}, lambda r, w: [])
    assert tags == {"wills-creek-md": "unmodeled", "north-branch-potomac-river-md": "unmodeled"}
    cov = RL.caution_coverage({"enabled": True, "permits": {
        "MD0021598": {"state": "MD", "threshold_basis": "published", "threshold_in": 0.1, "threshold_kind": "state",
                      "rainfall_read": "plant_point", "waters": ["wills-creek-md"]},
        "MD0067547": {"state": "MD", "threshold_basis": "published", "threshold_in": 0.1, "threshold_kind": "state",
                      "rainfall_read": "grid", "waters": []}}}, {"MD": {"MD0021598", "MD0067547"}})["MD"]
    assert cov["method"] == "NOAA MRMS radar rainfall: one radar grid an hour, sampled at each outfall"
    assert ("For one of them, rainfall is read at the treatment plant; the outfalls' own locations are not "
            "published.") in cov["sentence"]
    assert RL.READ_TEXT["plant_point"] == "rainfall read at the treatment plant; the outfalls' own locations are not published"
