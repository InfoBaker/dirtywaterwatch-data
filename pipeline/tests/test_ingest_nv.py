"""Nevada: the clock by point (West Wendover in Mountain time, 49 CFR 71.9(b)); the state parks' HAB advisory page
(tests/fixtures/nv_state_parks_hab_*.html: the advisory sections of two Internet Archive copies of the page, 2025-11-12
and 2026-08-13; no person named); and the state's registry rows (operators, register, rules row, text, waters)."""
import json
import re
from pathlib import Path

import pytest

import zones
from ingest import nv_state_parks_hab as P

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
NOV25 = (FIX / "nv_state_parks_hab_2025-11-12.html").read_text()
AUG26 = (FIX / "nv_state_parks_hab_2026-08-13.html").read_text()
T1, T2, T3 = "2026-11-14T20:00:00Z", "2026-11-15T20:00:00Z", "2026-11-16T20:00:00Z"


# ---- the clock -------------------------------------------------------------------------------------------------

def test_nevada_is_pacific_except_west_wendover():
    assert zones.zone_for("NV", 40.737, -114.06) == zones.MOUNTAIN            # West Wendover
    assert zones.zone_for("NV", 40.737, -114.0425) == zones.MOUNTAIN          # the strip to the Utah line
    assert zones.zone_for("NV", 40.70, -114.06) == zones.PACIFIC              # south of the city limits
    assert zones.zone_for("NV", 41.99, -114.67) == zones.PACIFIC              # Jackpot: Mountain by custom, Pacific in law
    assert zones.zone_for("NV", 36.17, -115.14) == zones.PACIFIC              # Las Vegas
    assert zones.zone_for("NV", 39.53, -119.81) == zones.PACIFIC              # Reno
    assert zones.zone_for("NV") == zones.PACIFIC
    assert zones.nevada_zone(place="West Wendover city") == zones.MOUNTAIN
    assert zones.nevada_zone(place="Wells") == zones.PACIFIC
    assert zones.zone_for("UT", 40.737, -114.06) == zones.MOUNTAIN and zones.zone_for("CA", 40.0, -120.0) == zones.PACIFIC


def test_the_west_wendover_file_cites_the_boundary():
    doc = json.loads((ROOT / "data" / "reference" / "nv-west-wendover.json").read_text())
    assert doc["law"]["cite"] == "49 CFR 71.9(b) and (d)" and doc["zone"] == "America/Denver"
    assert doc["place"]["name"] == "West Wendover city" and "tigerweb.geo.census.gov" in doc["source"]["url"]


def test_without_the_outline_the_box_decides(monkeypatch):
    monkeypatch.setattr(zones, "_west_wendover_outline", lambda: None)
    assert zones.nevada_zone(40.737, -114.06) == zones.MOUNTAIN and zones.nevada_zone(40.80, -114.06) == zones.PACIFIC


# ---- the state parks' HAB advisory page ------------------------------------------------------------------------

def test_the_page_is_read_by_section_and_water():
    items, sections = P.parse(AUG26)
    assert [(i["level"], i["water"], i["updated"]) for i in items] == [
        ("Watch", "Lahontan Reservoir", "2026-05-11"), ("Watch", "Rye Patch Reservoir", "2026-05-27"),
        ("Watch", "Marlette Lake", "2026-06-17"), ("Watch", "Washoe Lake", "2026-07-20")]
    assert items[0]["heading"] == "Lahontan State Recreation Area"
    assert "Visual assessments have indicated a possible bloom" in items[0]["text"]
    assert sections.count("<section") == 3
    items, _ = P.parse(NOV25)
    assert [(i["level"], i["water"], i["updated"]) for i in items] == [
        ("Watch", "Rye Patch Reservoir", "2025-10-08"), ("Warning", "Lahontan Reservoir", "2025-10-16")]
    assert "SWIM AT YOUR OWN RISK" in items[1]["text"]       # "Updated:" with a colon is read


def test_a_record_starts_at_the_first_read_never_at_the_update_date():
    recs, meta = P.build(AUG26, T1, [])
    assert meta["on_page"] == 4 and meta["by_level"] == {"Watch": 4, "Warning": 0, "Danger": 0}
    r = next(x for x in recs if x["waterbody_text"] == "Lahontan Reservoir")
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == T1 and r["time_precision"] == "poll" and r["ended_at"] is None
    assert r["source_updated_at"] == "2026-05-11" and r["reported_at"] is None and r["published_at"] is None
    assert r["raw"]["_last_seen_in_source"] == T1 and "not the date the advisory was issued" in r["raw"]["start_basis"]
    assert r["raw"]["time_zone"] == "America/Los_Angeles" and r["raw"]["level"] == "Watch"
    assert r["raw"]["placement_hint"] == {"name": "Lahontan Reservoir", "county": "Churchill County", "state": "NV",
                                          "basis": r["raw"]["placement_hint"]["basis"]}
    assert r["lat"] is None and r["coord_source"] is None                  # no GNIS feature: placed by name and county
    m = next(x for x in recs if x["waterbody_text"] == "Marlette Lake")
    assert (m["lat"], m["lon"], m["coord_source"]) == (39.174, -119.902, "gnis") and "860477" in m["raw"]["point_url"]
    assert r["source_record_id"] == "lahontan-reservoir:2026-11-14"


def test_a_level_change_updates_the_same_record_and_a_water_gone_is_lifted_at_the_read():
    first, _ = P.build(NOV25, T1, [])                         # Rye Patch Watch, Lahontan Warning
    page = NOV25.replace("upgraded to a&nbsp;HAB WARNING", "placed under a HAB Watch")
    # Lahontan moves from the Warning section to the Watch section, Rye Patch leaves the page
    watch = re.search(r"(<p><strong>Rye Patch.*?</p>\s*<p>.*?</p>)", page, re.S).group(1)
    lah = re.search(r"(<p><strong>Lahontan.*?SWIM AT YOUR OWN RISK</p>)", page, re.S).group(1)
    page = page.replace(lah, "<p>None at this time.</p>").replace(watch, lah.replace("Updated: October 16",
                                                                                      "Updated: November 2"))
    second, meta = P.build(page, T2, first)
    assert meta["opened"] == 0 and meta["lifted_this_read"] == 1
    lah2 = next(x for x in second if x["waterbody_text"] == "Lahontan Reservoir")
    lah1 = next(x for x in first if x["waterbody_text"] == "Lahontan Reservoir")
    assert lah2["event_id"] == lah1["event_id"] and lah2["started_at"] == T1 and lah2["raw"]["level"] == "Watch"
    assert [h["level"] for h in lah2["raw"]["level_history"]] == ["Warning", "Watch"]
    assert lah2["source_updated_at"] == "2025-11-02" and lah2["raw"]["_last_seen_in_source"] == T2
    rye = next(x for x in second if x["waterbody_text"] == "Rye Patch Reservoir")
    assert rye["status"] == "advisory_lifted" and rye["ended_at"] == T2
    assert rye["raw"]["ended_at_precision"] == "poll" and rye["raw"]["_unlisted_since"] == T2
    assert "upper bound" in rye["raw"]["end_basis"]
    # listed again later: a new record, the lifted one kept as it was
    third, meta = P.build(NOV25, T3, second)
    assert meta["opened"] == 1
    ryes = sorted((x for x in third if x["waterbody_text"] == "Rye Patch Reservoir"), key=lambda x: x["started_at"])
    assert [x["status"] for x in ryes] == ["advisory_lifted", "advisory_active"] and ryes[1]["started_at"] == T3
    assert ryes[0]["ended_at"] == T2


def test_a_missing_section_or_a_failed_read_never_lifts(tmp_path, monkeypatch):
    broken = AUG26.replace("HAB Danger Advisories", "HAB Advisories (archive)")
    with pytest.raises(ValueError, match="Danger"):
        P.build(broken, T2, [])
    with pytest.raises(ValueError, match="lists no water"):
        P.parse(AUG26.replace("None at this time.", "", 1))
    monkeypatch.setattr(P, "EVENTS_DIR", tmp_path)
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    good, meta = P.build(AUG26, T1, [])
    common.write_events(P.SOURCE_ID, good, meta=meta, path=tmp_path / f"{P.SOURCE_ID}.json")
    page = tmp_path / "broken.html"
    page.write_text(broken)
    assert P.main(["--file", str(page)]) == 1
    doc = json.loads((tmp_path / f"{P.SOURCE_ID}.json").read_text())
    assert doc["ok"] is False and doc["count"] == 4 and all(r["status"] == "advisory_active" for r in doc["records"])


def test_a_water_outside_the_crosswalk_keeps_its_name_and_the_page_names_no_person():
    page = AUG26.replace("Washoe Lake (Updated July 20, 2026)", "Example Lake (Updated July 20, 2026)").replace(
        "Washoe Lake, located in", "Example Lake, located in")
    recs, _ = P.build(page, T1, [])
    ex = next(x for x in recs if x["waterbody_text"] == "Example Lake")
    assert ex["raw"]["placement_hint"]["county"] is None and "crosswalk" in ex["raw"]["placement_note"]
    for text in (NOV25, AUG26):
        assert not re.search(r"@|\(\d{3}\)\s*\d{3}-\d{4}", text)


# ---- the registry rows -----------------------------------------------------------------------------------------

def _ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "NV"]


def test_every_nevada_permit_is_in_exactly_one_row():
    from collections import Counter
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "NV"}
    cand = json.loads((ROOT / "research" / "nv" / "private-utilities-candidates.json").read_text())
    wanted = plants | {c["npdes_permit"] for c in cand["candidates"]}
    assert all(every[p] == 1 for p in wanted), [p for p in wanted if every[p] != 1]
    held = {p for r in _ops() for p in r["npdes_permits"]}
    assert "AZ0025160" not in held and wanted - held == {"AZ0025160"}      # Hoover Dam stays with Arizona's row
    sparks = next(r for r in _ops() if r["id"] == "nv-city-of-sparks")
    assert sparks["npdes_permits"] == [] and sparks["kind"] == "collection_system"


def test_nevada_legal_forms_and_channels():
    from ingest import dischargers_schema as DS
    rows = _ops()
    assert not DS.check_legal_forms(rows)
    fed = {r["id"] for r in rows if r["legal_form"] == "federal facility"}
    assert fed == {"nv-hawthorne-army-depot", "nv-nnsa-north-las-vegas", "nv-naval-air-station-fallon"}
    for r in rows:
        local = r["legal_form"] in ("city", "county", "special district")
        assert ("NRS 445A.467 (2025) requires" in r["notification_channel"]) == local, r["id"]
        assert not re.search(r"\bAmentum\b", r["name"])                    # a contractor is not the operator's name


def test_nevada_register_rows():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "nv.json").read_text())["channels"]}
    for r in _ops():
        row = reg[f"{r['id']}-ndep-report"]
        assert row["urls"] == [] and row["barrier"] == "no_web_page" and row["records"] is False
        assert row["basis_kind"] == ("law" if r["legal_form"] in ("city", "county", "special district") else "permit")
    assert reg["nv-state-parks-hab"]["feed_source_id"] == "nv-state-parks-hab"
    assert reg["nv-ndep-sewage-notice"]["basis_kind"] == "law" and "445A.467" in reg["nv-ndep-sewage-notice"]["legal_basis"]
    assert reg["nv-ndep-hab-dashboard"]["barrier"] == "image_only"
    assert reg["nv-ndep-hab-email"]["barrier"] == "no_web_page"
    assert reg["nv-city-of-reno-spill-line"]["barrier"] == "phone_only"
    assert reg["nv-ndep-hab-program"]["monitored"] and reg["nv-nps-lake-mead-habs"]["monitored"]


def test_nevada_rules_row_and_text():
    nv = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["NV"]
    assert nv["hours"] is None and "NRS 445A.467" in nv["source"] and "71.9(b)" in nv["source"]
    assert not re.search(r"\b(safe|clean)\b", nv["basis"], re.I)
    t = (ROOT / "research" / "nv" / "state-text.md").read_text()
    assert t.startswith("---\nstate: NV\nname: Nevada\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t
    assert "NRS 445A.467" in t and "West Wendover" in t and "No sewage discharge report is published" in t


def test_nevada_missing_waters_list():
    d = json.loads((ROOT / "research" / "nv" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["NV"]["waters"]
    national = {w["key"] for w in nat}
    assert d["state"] == "NV" and d["waters"] == len(d["rows"])
    for r in d["rows"]:
        assert r["name"].lower() not in national and r["county"]
        # the batch may resolve a name to a record; a resolved name is listed under "resolved" with its record
        assert r.get("sources") or r.get("resolved")
    assert {r["name"] for r in d["rows"]} | {r["name"] for r in d.get("resolved", [])} >= {
        "Lahontan Reservoir", "Rye Patch Reservoir", "Marlette Lake", "Washoe Lake"}
    for name in P.WATERS:                                    # every water the crosswalk knows is listed with its county
        assert any(r["name"] == name and r["county"] == P.WATERS[name][0] for r in d["rows"] + d.get("resolved", []))
