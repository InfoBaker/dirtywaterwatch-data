"""North Dakota: DEQ's harmful algal bloom listing (ingest/nd_deq_hab_listings.py), DEQ's incident archive of 1975 to 2020,
the sewage rows (ingest/nd_deq_eir_legacy.py), the Central-Mountain county rule (pipeline/zones.py, 49 CFR 71.7(a)), the
operators, the register, the rules row, the state text and the missing-waters list. Fixtures: the listing PDF of
2026-11-14 (lakes, counties, dates; no person) and ten archive rows of 2026-11-14 (no person in the table; points kept to
0.001 degree; the septic row's point and section replaced by invented ones). No network."""
import json
import re
from pathlib import Path

import pytest

import zones
from ingest import nd_deq_eir_legacy as L
from ingest import nd_deq_hab_listings as H

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "nd"
FETCHED = "2026-11-14T18:00:00Z"
PDF = (FIX / "HABsListings.pdf").read_bytes()


def hab(previous=(), fetched=FETCHED, pdf=PDF):
    recs, meta = H.build(pdf, fetched, list(previous), "2026-10-08T19:44:26Z")
    return {r["waterbody_text"]: r for r in recs}, meta


def legacy():
    rows, n = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    recs, meta = L.build(rows, FETCHED)
    return {r["source_record_id"]: r for r in recs}, meta, n


def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "ND"]


# ---------------------------------------------------------------- the county rule

@pytest.mark.parametrize("county,zone", [
    ("Stark", zones.MOUNTAIN), ("Bowman County", zones.MOUNTAIN), ("Golden Valley", zones.MOUNTAIN),
    ("Dunn", zones.MOUNTAIN), ("Grant", zones.MOUNTAIN), ("McKenzie", zones.MOUNTAIN), ("Sioux County", zones.MOUNTAIN),
    ("Morton", zones.CENTRAL), ("Mercer", zones.CENTRAL), ("Cass", zones.CENTRAL), ("Williams", zones.CENTRAL),
    ("McLean", zones.CENTRAL), (None, zones.CENTRAL)])
def test_north_dakota_zone_by_county(county, zone):
    z, basis = zones.north_dakota_zone(county)
    assert z == zone and "49 CFR 71.7(a)" in basis
    if county in ("McKenzie", "Sioux County"):
        assert "split" in basis and "later day's end" in basis


def test_north_dakota_zone_by_point_and_other_states_unchanged():
    assert zones.zone_for("ND", 46.879, -102.789) == zones.MOUNTAIN          # Dickinson, Stark County
    assert zones.zone_for("ND", 46.877, -96.79) == zones.CENTRAL             # Fargo, Cass County
    assert zones.zone_for("ND", 46.81, -100.78) == zones.CENTRAL             # Bismarck, Burleigh County
    assert zones.zone_for("ND") == zones.CENTRAL and zones.nd_point_county(46.879, -102.789) == "Stark County"
    assert zones.zone_for("SD", 44.08, -103.23) == zones.MOUNTAIN and zones.zone_for("MN") == zones.CENTRAL
    assert zones.zone_for("TN", 35.96, -83.92) == zones.EASTERN and zones.zone_for("FL", 30.44, -87.2) == zones.CENTRAL


# ---------------------------------------------------------------- the bloom listing

def test_the_listing_reads_every_row_with_cells_cut_between_streams():
    rows = H.parse(PDF)
    assert [r["level"] for r in rows].count("advisory") == 14 and [r["level"] for r in rows].count("warning") == 6
    by = {r["lake"]: r for r in rows}
    assert by["Bowman - Haley Dam"]["counties"] == ["Bowman"] and by["Bowman - Haley Dam"]["date"] == "2026-06-29"
    assert by["Lake Darling"]["counties"] == ["Renville"] and by["Lake Darling"]["level"] == "warning"
    assert by["Devils Lake"]["counties"] == ["Ramsey", "Benson"] and by["Devils Lake"]["date"] == "2026-07-16"
    assert by["North Lake Washington"]["level"] == "warning" and by["Buffalo Lake"]["date"] == "2026-10-05"
    with pytest.raises(ValueError):
        H.parse(b"%PDF-1.4\n%%EOF")


def test_bloom_records_are_deqs_own_advisories_dated_to_the_posting():
    recs, meta = hab()
    assert meta["advisories"] == 14 and meta["warnings"] == 6 and len(recs) == 20
    for r in recs.values():
        assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active" and r["ended_at"] is None
        assert r["time_precision"] == "day" and r["started_at"] == r["published_at"] == r["raw"]["date_posted"]
        assert r["source_updated_at"] == "2026-10-08T19:44:26Z" and r["raw"]["_last_seen_in_source"] == FETCHED
        assert r["raw"]["placement_hint"]["state"] == "ND" and r["raw"]["state"] == "ND"
        assert (r["lat"] is None) == ("marker_point" not in r["raw"])
    assert recs["Lake Tschida"]["raw"]["time_zone"] == zones.MOUNTAIN and recs["Lake Ilo"]["raw"]["time_zone"] == zones.MOUNTAIN
    assert recs["Lake Ashtabula"]["raw"]["time_zone"] == zones.CENTRAL
    assert recs["Devils Lake"]["raw"]["county"] == "Ramsey" and recs["Devils Lake"]["raw"]["counties"] == ["Ramsey", "Benson"]
    assert recs["Devils Lake"]["source_record_id"] == "devils-lake:benson-ramsey:advisory:2026-07-16"
    assert "toxins" in recs["Lake Tschida"]["advice_text"] and recs["Clear Lake"]["raw"]["level"] == "advisory"


def test_a_row_that_leaves_the_listing_ends_at_that_read_and_can_come_back():
    first, _ = hab()
    gone = [r for k, r in first.items() if k != "Buffalo Lake"]
    # the second read: Buffalo Lake still there, Lake Ilo gone (simulated by dropping it from the previous list's view)
    prev = list(first.values())
    pdf_without = PDF                      # same file; the record removed below stands for a row DEQ took off
    recs, meta = H.build(pdf_without, "2026-11-15T18:00:00Z", prev + [dict(first["Lake Ilo"], source_record_id="2026:old-lake:dunn",
                                                                             event_id="nd-deq-hab-listings:2026:old-lake:dunn")])
    old = next(r for r in recs if r["source_record_id"] == "2026:old-lake:dunn")
    assert old["status"] == "advisory_lifted" and old["ended_at"] == "2026-11-15T18:00:00Z"
    assert old["raw"]["ended_at_precision"] == "poll" and old["raw"]["_unlisted_since"] == "2026-11-15T18:00:00Z"
    assert meta["lifted_this_read"] == 1 and len(gone) == 19
    back = dict(first["Lake Ilo"], raw=dict(first["Lake Ilo"]["raw"], _unlisted_since="2026-11-15T18:00:00Z"))
    recs, _ = H.build(PDF, "2026-11-16T18:00:00Z", [back])
    ilo = next(r for r in recs if r["waterbody_text"] == "Lake Ilo")
    assert ilo["status"] == "advisory_active" and ilo["raw"]["_absences"] == [{"from": "2026-11-15T18:00:00Z",
                                                                               "to": "2026-11-16T18:00:00Z"}]


def test_p2_1_a_lake_moved_to_the_warning_table_is_a_new_posting_and_the_advisory_ends_at_the_read():
    first, _ = hab()
    prev = dict(first["Lake Tschida"])
    prev["source_record_id"] = "lake-tschida:grant:advisory:2026-07-01"
    prev["event_id"] = "nd-deq-hab-listings:" + prev["source_record_id"]
    prev["started_at"] = prev["published_at"] = "2026-07-01"
    prev["raw"] = dict(prev["raw"], level="advisory", date_posted="2026-07-01")
    recs, _ = H.build(PDF, "2026-11-15T18:00:00Z", [prev])
    by = {r["source_record_id"]: r for r in recs}
    old, new = by["lake-tschida:grant:advisory:2026-07-01"], by["lake-tschida:grant:warning:2026-08-26"]
    assert old["status"] == "advisory_lifted" and old["ended_at"] == "2026-11-15T18:00:00Z"
    assert new["status"] == "advisory_active" and new["started_at"] == "2026-08-26"     # never merged back to July


def test_p2_1_absences_carry_and_county_order_is_one_key():
    first, _ = hab()
    d = first["Devils Lake"]
    assert d["source_record_id"].startswith("devils-lake:benson-ramsey:")
    back = dict(d, raw=dict(d["raw"], _unlisted_since="2026-11-15T18:00:00Z",
                            _absences=[{"from": "2026-10-01T00:00:00Z", "to": "2026-10-02T00:00:00Z"}]))
    recs, _ = H.build(PDF, "2026-11-16T18:00:00Z", [back])
    dv = next(r for r in recs if r["waterbody_text"] == "Devils Lake")
    assert dv["raw"]["_absences"] == [{"from": "2026-10-01T00:00:00Z", "to": "2026-10-02T00:00:00Z"},
                                      {"from": "2026-11-15T18:00:00Z", "to": "2026-11-16T18:00:00Z"}]
    again, _ = H.build(PDF, "2026-11-17T18:00:00Z", [dv])
    assert next(r for r in again if r["waterbody_text"] == "Devils Lake")["raw"]["_absences"] == dv["raw"]["_absences"]


def test_p1_5_a_damaged_row_or_a_missing_table_fails_and_lifts_nothing(monkeypatch):
    items = H.page_items(PDF)
    broken = [dict(i) for i in items if not i["text"].startswith("09/15")]      # Larimore Dam's date lost
    monkeypatch.setattr(H, "page_items", lambda pdf: broken)
    with pytest.raises(ValueError, match="could not be read whole"):
        H.parse(PDF)
    no_warnings = [i for i in items if i["y"] > 262]
    monkeypatch.setattr(H, "page_items", lambda pdf: no_warnings)
    with pytest.raises(ValueError, match="tables were not all found"):
        H.parse(PDF)
    empty = [i for i in items if re.sub(r"\s", "", i["text"]).lower() in ("a", "dvisories", "warning")]
    monkeypatch.setattr(H, "page_items", lambda pdf: empty)
    assert H.parse(PDF) == []                        # DEQ's own empty listing reads as empty, not as a failure


def test_p1_1_each_listed_lake_with_an_nhd_outline_in_its_county_has_a_cited_point():
    recs, _ = hab()
    pts = json.loads((ROOT / "data" / "reference" / "nd-hab-lake-points.json").read_text())
    assert len(pts["lakes"]) + len(pts["without_point"]) == 20 and len(pts["lakes"]) == 14
    for r in recs.values():
        p = r["raw"].get("marker_point")
        if p is None:
            assert r["lat"] is None
            continue
        assert (r["lat"], r["lon"]) == (p["lat"], p["lon"]) and p["gnis_id"] and round(r["lat"], 3) == r["lat"]
        assert p["county"].removesuffix(" County") in r["raw"]["counties"]
        assert zones.nd_point_county(r["lat"], r["lon"]) == p["county"]
    assert recs["Clear Lake"]["lat"] is None          # no Clear Lake outline in Pierce County: no borrowed point
    assert recs["Patterson Lake"]["raw"]["marker_point"]["gnis_name"] == "Edward Arthur Patterson Lake"


# ---------------------------------------------------------------- the incident archive

def test_archive_keeps_sewage_rows_only():
    recs, meta, n = legacy()
    assert n == 10 and meta["rows_read"] == 10 and meta["kept"] == 8
    assert sorted(meta["dropped_not_sewage"]) == ["EIR5741", "EIR857"]      # potable water; plain "wastewater"
    assert recs["EIR1084"]["event_type"] == recs["EIR5444"]["event_type"] == "plant_bypass"     # treated sewage
    assert recs["EIR9245"]["event_type"] == recs["EIR1851"]["event_type"] == "sso"


def test_archive_dates_zones_volumes_and_no_end():
    recs, _, _ = legacy()
    r = recs["EIR9245"]
    assert r["started_at"] == "2019-09-21" and r["reported_at"] == "2019-09-23" and r["time_precision"] == "day"
    assert r["ended_at"] is None and r["status"] == "unknown" and r["volume_gal"] == 500000
    assert r["raw"]["contained"] == "No" and "not an end" in r["raw"]["contained_note"]
    assert r["raw"]["time_zone"] == zones.CENTRAL and r["raw"]["county"] == "Grand Forks County"
    d = recs["EIR2031"]
    assert d["raw"]["time_zone"] == zones.MOUNTAIN and d["volume_gal"] == 378 and d["volume_text"] == "9 barrels"
    assert recs["EIR1084"]["volume_gal"] == 1000 and recs["EIR10628"]["volume_gal"] == 38
    assert all(x["discharger_id"] is None and x["npdes_permit"] is None for x in recs.values())


def test_archive_points_rounded_septic_kept_to_county_and_a_double_filing_marked():
    recs, _, _ = legacy()
    for r in recs.values():
        if r["lat"] is not None:
            assert round(r["lat"], 3) == r["lat"] and round(r["lon"], 3) == r["lon"]
    s = recs["EIR5540"]
    assert s["lat"] is None and s["lon"] is None and s["raw"]["row"]["twn_rng_sec"] is None
    assert s["raw"]["point_withheld"] and s["raw"]["county"] == "Burleigh County"
    assert recs["EIR2032"]["duplicate_of"] == "nd-deq-eir-legacy-general:EIR2031" and recs["EIR2031"]["duplicate_of"] is None


def test_archive_saved_rows_carry_only_the_safe_columns():
    rows, _ = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    for r in rows:
        assert set(L.safe_row(r)) <= set(L.COLUMNS) | {"point_withheld"}


# ---------------------------------------------------------------- registry, register, rules, text

def test_operators_hold_every_north_dakota_plant_permit_once():
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "ND"}
    rows = ops()
    held = [p for r in rows for p in r["npdes_permits"]]
    assert plants <= set(held) and len(held) == len(set(held))
    by = {a: r for r in rows for a in r["aliases"]}
    assert "ND0022870" in by["nd-fargo"]["npdes_permits"] and by["nd-grand-forks"]["npdes_permits"] == ["ND0022888"]
    assert "draft" in by["nd-fargo"]["notification_channel"] and "33.1-16-02.1-11(4)" in by["nd-fargo"]["notification_channel"]


def test_register_rows_name_the_bot_wall_and_the_feeds():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "nd.json").read_text())["channels"]}
    for r in ops():
        row = reg[f"{r['id']}-spill-report"]
        assert row["barrier"] == "bot_wall" and row["monitored"] is False
    assert reg["nd-hazconnect-public-incidents"]["barrier"] == "bot_wall"
    assert reg["nd-deq-hab-listings"]["feed_source_id"] == "nd-deq-hab-listings"
    assert reg["nd-deq-eir-legacy-general"]["feed_source_id"] == "nd-deq-eir-legacy-general"
    assert reg["nd-permit-factsheets"]["barrier"] == "image_only"
    assert reg["nd-fargo-public-notification"]["basis_kind"] == "permit"


def test_rules_row_and_state_text():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    nd = rules["red"]["by_state"]["ND"]
    assert nd["hours"] is None and "71.7(a)" in nd["source"] and not re.search(r"\b(safe|clean)\b", nd["basis"], re.I)
    assert "nd-deq-eir-legacy-general" in rules["unresolved"]["day_start_caution"]["sources"]
    t = (ROOT / "research" / "nd" / "state-text.md").read_text()
    assert t.startswith("---\nstate: ND\nname: North Dakota\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "\n{{share_line}}\n" in t and "{{dated_share}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean|green)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "4,452" in t and "36 sewage reports" in t and "14 advisories" in t and "6 warnings" in t


def test_missing_waters_list_carries_the_bloom_lakes_with_their_counties():
    d = json.loads((ROOT / "research" / "nd" / "receiving-waters-missing.json").read_text())
    names = {r["name"]: r for r in d["rows"]} | {r["name"]: r for r in d.get("resolved") or []}
    for lake in ("Lake Tschida", "Lake Ashtabula", "Clear Lake", "Bowman-Haley Dam"):
        assert lake in names
    if "Clear Lake" in {r["name"] for r in d["rows"]}:
        assert names["Clear Lake"]["county"] == "Pierce County"
    assert d["waters"] == len(d["rows"])
