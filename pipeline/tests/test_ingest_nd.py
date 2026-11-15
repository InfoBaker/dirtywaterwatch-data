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
    back = dict(first["Lake Ilo"], status="advisory_lifted", ended_at="2026-11-15T18:00:00Z",
                raw=dict(first["Lake Ilo"]["raw"], _unlisted_since="2026-11-15T18:00:00Z", ended_at_precision="poll"))
    recs, _ = H.build(PDF, "2026-11-16T18:00:00Z", [back])
    ilo = sorted((r for r in recs if r["waterbody_text"] == "Lake Ilo"), key=lambda r: r["source_record_id"])
    assert [r["status"] for r in ilo] == ["advisory_lifted", "advisory_active"]       # the gap stays a gap
    assert ilo[1]["source_record_id"] == ilo[0]["source_record_id"] + "~2"
    assert ilo[1]["started_at"] == "2026-11-16T18:00:00Z" and ilo[1]["time_precision"] == "poll"


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


def test_p2_1_county_order_is_one_key():
    first, _ = hab()
    d = first["Devils Lake"]
    assert d["source_record_id"].startswith("devils-lake:benson-ramsey:")
    again, _ = H.build(PDF, "2026-11-17T18:00:00Z", [d])
    assert [r["event_id"] for r in again if r["waterbody_text"] == "Devils Lake"] == [d["event_id"]]


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
    with pytest.raises(ValueError, match="no statement that the table is empty"):
        H.parse(PDF)                                 # two bare headings are no evidence of an empty listing
    said = empty + [{"text": "None", "x": 60.0, "y": 400.0}, {"text": "None", "x": 60.0, "y": 200.0}]
    monkeypatch.setattr(H, "page_items", lambda pdf: said)
    assert H.parse(PDF) == []                        # each table saying it is empty reads as DEQ's empty listing


def test_p1_1_each_listed_lake_with_an_nhd_outline_in_its_county_has_a_cited_point():
    recs, _ = hab()
    pts = json.loads((ROOT / "data" / "reference" / "nd-hab-lake-points.json").read_text())
    assert len(pts["lakes"]) + len(pts["without_point"]) == 20 and len(pts["lakes"]) == 15
    for r in recs.values():
        p = r["raw"].get("marker_point")
        if p is None:
            assert r["lat"] is None
            continue
        assert (r["lat"], r["lon"]) == (p["lat"], p["lon"]) and p["gnis_id"] and round(r["lat"], 3) == r["lat"]
        assert p["county"].removesuffix(" County") in r["raw"]["counties"]
        assert zones.nd_point_county(r["lat"], r["lon"]) == p["county"]
    c = recs["Clear Lake"]                            # no NHD outline in Pierce County: the one GNIS lake there
    assert c["coord_source"] == "gnis_point" and c["raw"]["marker_point"]["gnis_id"] == "01028388"
    assert c["raw"]["marker_point"]["county"] == "Pierce County"
    assert recs["Patterson Lake"]["raw"]["marker_point"]["gnis_name"] == "Edward Arthur Patterson Lake"


# ---------------------------------------------------------------- the point builder (review 2026-11-14 P2-2)

def _square(lat, lon, d=0.01, gnis_id="09999901", name="Example Lake"):
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    return {"attributes": {"GNIS_NAME": name, "GNIS_ID": gnis_id, "AREASQKM": 1, "FTYPE": 390},
            "geometry": {"rings": [ring]}}


def _gaz(lat, lon, county, gid=9999911, name="Example Lake", cls="Lake"):
    return {"attributes": {"gaz_id": gid, "gaz_name": name, "gaz_featureclass": cls, "state_alpha": "ND",
                           "county_name": county}, "geometry": {"x": lon, "y": lat}}


def _points():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ndpts", ROOT / "scripts" / "nd_hab_lake_points.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LISTED = [{"lake": "Example Lake", "counties": ["Kidder"], "level": "advisory", "date": "2026-07-01"}]


def test_p2_2_two_same_named_lakes_with_separate_gnis_ids_get_no_point_even_if_one_is_larger():
    m = _points()
    big = _square(46.75, -99.95, d=0.03, gnis_id="09999901")
    small = _square(46.75, -99.48, d=0.01, gnis_id="09999902")         # about 36 km east, same county
    doc = m.build([big, small], LISTED, "2026-11-14")
    assert doc["lakes"] == [] and len(doc["without_point"]) == 1
    why = doc["without_point"][0]["why"]
    assert "2 separate NHD lakes" in why and "beyond 25 km" in why
    near = _square(46.77, -99.93, d=0.005, gnis_id="09999903")          # a separate lake close by: still refused
    assert m.build([big, near], LISTED, "2026-11-14")["lakes"] == []


def test_p2_2_parts_of_one_gnis_lake_are_one_lake_and_qualified_names_are_other_waters():
    m = _points()
    part1 = _square(46.75, -99.95, d=0.03, gnis_id="09999901")
    part2 = _square(46.75, -99.70, d=0.01, gnis_id="09999901")         # a second part of the same identity
    other = _square(46.9, -99.7, d=0.05, gnis_id="09999909", name="North Example Lake")
    doc = m.build([part1, part2, other], LISTED, "2026-11-14")
    (row,) = doc["lakes"]
    assert row["gnis_id"] == "09999901" and abs(row["lon"] - -99.95) < 0.04 and row["coord_source"] == "nhd_waterbody"
    assert m.build([other], LISTED, "2026-11-14")["lakes"] == []       # "North Example Lake" is not "Example Lake"


def test_p2_2_gnis_point_only_for_one_identified_lake_in_the_listed_county():
    m = _points()
    one = m.build([], LISTED, "2026-11-14", [_gaz(46.9, -99.7, "Kidder")])
    assert one["lakes"][0]["coord_source"] == "gnis_point" and one["lakes"][0]["gnis_id"] == "09999911"
    assert (one["lakes"][0]["lat"], one["lakes"][0]["lon"]) == (46.9, -99.7)
    two = m.build([], LISTED, "2026-11-14", [_gaz(46.9, -99.7, "Kidder"), _gaz(46.75, -99.95, "Kidder", 9999912)])
    assert two["lakes"] == [] and "2 GNIS lakes" in two["without_point"][0]["why"]
    elsewhere = m.build([], LISTED, "2026-11-14", [_gaz(47.95, -100.1, "Pierce")])      # another county's namesake
    assert elsewhere["lakes"] == []
    wrong_county = m.build([], LISTED, "2026-11-14", [_gaz(47.95, -100.1, "Kidder")])   # gazetteer and point disagree
    assert wrong_county["lakes"] == []
    stream = m.build([], LISTED, "2026-11-14", [_gaz(46.9, -99.7, "Kidder", cls="Stream")])
    assert stream["lakes"] == []


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
        if r.get("permit_only"):
            assert f"{r['id']}-spill-report" not in reg                    # no operator row for a permit-only row
            continue
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


# ---------------------------------------------------------------- review 2026-11-14 (Astra), the archive

class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise L.requests.HTTPError(f"{self.status_code}")


class _Session:
    def __init__(self, answers):
        self.answers = list(answers)

    def request(self, method, url, **kw):
        return self.answers.pop(0)


def test_p1_4_a_refused_or_malformed_archive_read_fails(monkeypatch):
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    page = (FIX / "legacy-search-sample.html").read_text()
    with pytest.raises(L.requests.HTTPError):
        L.fetch_search("sewage", _Session([_Resp("Access denied", 403)]))
    with pytest.raises(ValueError, match="not its table"):
        L.fetch_search("sewage", _Session([_Resp(page), _Resp("<html>Service unavailable</html>")]))
    no_count = page.replace("Records: 10", "")
    with pytest.raises(ValueError, match="no record count"):
        L.fetch_search("sewage", _Session([_Resp(page), _Resp(no_count)]))
    short = page.replace("Records: 10", "Records: 25")
    with pytest.raises(ValueError, match="rows read of 25"):
        L.fetch_search("sewage", _Session([_Resp(page), _Resp(short), _Resp(short)]))
    assert len(L.fetch_search("sewage", _Session([_Resp(page), _Resp(page)]))) == 10


def test_p1_4_a_report_that_leaves_the_archive_is_kept_and_marked():
    recs, _, _ = legacy()
    rows, _ = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    later, meta = L.build([r for r in rows if r["incident_id"] != "EIR9245"], "2026-12-20T00:00:00Z",
                          list(recs.values()))
    gone = next(r for r in later if r["source_record_id"] == "EIR9245")
    assert gone["raw"]["_missing_from_source_since"] == "2026-12-20T00:00:00Z" and meta["carried_missing"] == 1


def test_p2_2_nearby_incidents_are_not_duplicates_after_rounding():
    rows, _ = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    a = next(r for r in rows if r["incident_id"] == "EIR10628")
    b = dict(a, incident_id="EIR99999", latitude="47.8471", longitude="-102.6092")      # invented, same 0.001 cell
    recs, _ = L.build([a, b], FETCHED)
    assert all(r["duplicate_of"] is None for r in recs)
    recs, _ = L.build([a, dict(a, incident_id="EIR99999")], FETCHED)                    # every value repeated
    assert [r["duplicate_of"] for r in recs if r["source_record_id"] == "EIR99999"] == [
        "nd-deq-eir-legacy-general:EIR10628"]


def test_p1_6_archive_free_text_is_scrubbed_before_saving():
    rows, _ = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    r = dict(rows[0], contaminant="Sewage from 1234 Example Street, call 701-555-0142")
    out = json.dumps(L.safe_row(r)) + json.dumps(L.record(r, FETCHED))
    assert "701-555-0142" not in out and "1234 Example" not in out


def test_p2_3_a_plant_name_is_a_permit_only_row_and_outfalls_are_eligible_rows():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import icis_operators as I
    by = {r["id"]: r for r in ops()}
    nt = by["nd-new-town-water-resource-recovery-facility"]
    assert nt["permit_only"] is True and nt["legal_form"] is None and nt["name"].startswith("Permit NDG")
    plants = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
    for r in ops():
        if r["kind"] == "cso":
            continue
        rows = [x for x in plants if x.get("npdes_permit") in r["npdes_permits"]]
        n = sum(1 for x in rows if I.outfall_eligible(x)[0])
        assert r["outfall_count"] == (n or None)


# ---------------------------------------------------------------- every standing listing visible (re-review P1-1)

def _status_build(tmp_path, recs, waters):
    import copy
    from datetime import UTC, datetime
    from build import status as S
    now = datetime(2026, 11, 14, 19, tzinfo=UTC)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    (tmp_path / "nd-deq-hab-listings.json").write_text(json.dumps(
        {"source_id": "nd-deq-hab-listings", "ok": True, "last_ok_at": now.isoformat(), "meta": {}, "records": recs}))
    rules = copy.deepcopy(S.load_rules())
    rules["live_states"] = sorted(set(rules["live_states"]) | {"ND"})
    st, _ = S.build(now=now, write=False, events_dir=tmp_path, waters=waters, outfalls=[], registry={}, reaches={},
                    flows=({}, {}), rules=rules, placement_cache=False)
    return st, S


@pytest.mark.parametrize("area", [100.0, 2.0])
def test_p1_1_every_standing_listing_is_visible_before_and_after_its_water_is_resolved(tmp_path, area):
    recs = list(hab()[0].values())
    assert len(recs) == 20 and all(r["status"] == "advisory_active" for r in recs)
    assert all(r["raw"]["advisory_extent"] == "named_water" for r in recs)
    for r in recs:
        r["water_slugs"] = []
    st, S = _status_build(tmp_path, recs, {})
    marked = {p["event_id"] for p in st["advisory_points"] if p["status"] == "red"}
    assert len(marked) == 15
    unplaced = set(st["unplaced_events"])
    for r in recs:                     # a point-less listing is kept, filed under North Dakota, listed unplaced
        assert r["event_id"] in marked or (r["event_id"] in unplaced and S.event_state(r) == "ND")
    waters = {}
    for i, r in enumerate(recs):       # each lake resolved to a water record of its own (a large or a small lake)
        lat, lon = (r["lat"], r["lon"]) if r["lat"] is not None else (46.5 + i * 0.05, -99.0)
        d = 0.05
        slug = f"example-lake-{i}-nd"
        ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
        waters[slug] = {"slug": slug, "name": r["waterbody_text"], "kind": "lake", "state": "ND", "area_km2": area,
                        "bbox": [lon - d, lat - d, lon + d, lat + d],
                        "geometry": {"type": "Polygon", "coordinates": [ring]}}
        r["water_slugs"], r["water_match"] = [slug], "name"
    st, _ = _status_build(tmp_path, recs, waters)
    assert all(w["status"] == "red" for w in st["waters"].values())       # every listed lake coloured, large or small
    pts = {p["event_id"] for p in st["advisory_points"] if p["status"] == "red"}
    if area >= 50:
        assert pts == marked           # a large lake keeps its marker where the listing has a point


# ---------------------------------------------------------------- re-review 2026-11-14 P1-4: a whole read or none

def test_p1_4_a_lost_county_cell_fails_the_read_and_keeps_the_advisory(monkeypatch):
    first, _ = hab()
    items = H.page_items(PDF)
    clear = next(i for i in items if i["text"].strip().startswith("Clear Lake"))
    no_county = [i for i in items if not (abs(i["y"] - clear["y"]) <= 3 and 300 <= i["x"] < 450)]
    assert len(no_county) < len(items)
    monkeypatch.setattr(H, "page_items", lambda pdf: no_county)
    with pytest.raises(ValueError, match="could not be read whole"):
        H.parse(PDF)
    bogus = [dict(i, text="Example") if (abs(i["y"] - clear["y"]) <= 3 and 300 <= i["x"] < 450) else i for i in items]
    monkeypatch.setattr(H, "page_items", lambda pdf: bogus)
    with pytest.raises(ValueError, match="could not be read whole"):     # not a North Dakota county
        H.parse(PDF)


def _main_with(monkeypatch, pdf, previous):
    written = []

    class Resp:
        content, headers = pdf, {}

        def raise_for_status(self):
            return None
    monkeypatch.setattr(H.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(H, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(H, "read_json", lambda path, default=None: {"records": list(previous)})
    monkeypatch.setattr(H, "write_events", lambda sid, recs, **k: written.append((list(recs), k)))
    return H.main([]), written


def test_p1_4_a_second_page_or_a_missing_stream_fails_and_lifts_nothing(monkeypatch):
    first, _ = hab()
    two_pages = PDF.replace(b"%%EOF", b"\n999 0 obj\n<< /Type /Page /Contents 998 0 R >>\nendobj\n%%EOF", 1)
    with pytest.raises(ValueError, match="2 pages"):
        H.parse(two_pages)
    rc, written = _main_with(monkeypatch, two_pages, first.values())
    assert rc == 1 and written[0][1]["ok"] is False and written[0][0] == []      # previous records kept by the writer
    m = re.search(rb"/Contents\s*\[\s*(\d+)", PDF)
    gone = PDF.replace(m.group(0), m.group(0).replace(m.group(1), b"9999"), 1)       # a stream the page names, absent
    with pytest.raises(ValueError, match="missing or cannot be decoded"):
        H.parse(gone)
    rc, written = _main_with(monkeypatch, gone, first.values())
    assert rc == 1 and written[0][1]["ok"] is False
    rc, written = _main_with(monkeypatch, PDF, first.values())
    assert rc == 0 and len(written[0][0]) == 20
    assert all(r["status"] == "advisory_active" for r in written[0][0])


# ---------------------------------------------------------------- re-review 2026-11-14 P1-5: the archive's text

def test_p1_5_archive_contaminant_text_carries_no_name_or_address_at_any_save(monkeypatch):
    rows, _ = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    row = dict(next(r for r in rows if L.keep(r) and r["latitude"]))
    row["contaminant"] = "Raw sewage, reported by Pat Example at 1234 Example Street"
    assert L.keep(row)
    blob = json.dumps([L.safe_row(row), L.record(row, FETCHED)])
    assert "Pat Example" not in blob and "1234 Example" not in blob and "Raw sewage" in blob
    saved, written = [], []
    monkeypatch.setattr(L, "fetch_search", lambda w, s: [row] if w == "sewage" else [])
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.setattr(L, "read_json", lambda path, default=None: {})
    monkeypatch.setattr(L, "save_raw", lambda sid, content, ext: saved.append(content))
    monkeypatch.setattr(L, "write_events", lambda sid, recs, **k: written.append(list(recs)))
    assert L.main(["--force"]) == 0
    out = json.dumps([saved, written])
    assert saved and written and "Pat Example" not in out and "1234 Example" not in out



# ---------------------------------------------------------------- re-review 2026-11-14 P2-1: observed periods

def test_p2_1_a_returning_posting_keeps_its_gap_through_status(monkeypatch):
    from datetime import datetime, timezone
    from build import status as S
    row = {"level": "advisory", "lake": "Example Lake", "counties": ["Kidder"], "date": "2026-07-01"}
    monkeypatch.setattr(H, "parse", lambda pdf: [dict(row)] if listed[0] else [])
    listed = [True]

    def read(when, prev):
        recs, _ = H.build(b"", when, prev)
        return recs
    r1 = read("2026-07-02T18:00:00Z", [])
    r1 = read("2026-07-05T18:00:00Z", r1)                             # repeated unchanged read: one record
    assert len(r1) == 1 and r1[0]["started_at"] == "2026-07-01"
    listed[0] = False
    r2 = read("2026-07-10T18:00:00Z", r1)
    assert r2[0]["status"] == "advisory_lifted" and r2[0]["ended_at"] == "2026-07-10T18:00:00Z"
    listed[0] = True
    r3 = read("2026-08-01T18:00:00Z", r2)
    r3 = read("2026-08-02T18:00:00Z", r3)                             # unchanged again: the same second period
    assert len(r3) == 2
    now = datetime(2026, 8, 5, tzinfo=timezone.utc)

    def colour(y, mo, d):
        at = datetime(y, mo, d, 12, tzinfo=timezone.utc)
        cs = [S.status_at(S.event_intervals(r, "ND", now), at)[0] for r in r3]
        return "red" if "red" in cs else cs
    assert colour(2026, 7, 5) == "red"
    assert colour(2026, 7, 20) != "red"                               # the gap: DEQ did not list it
    assert colour(2026, 8, 3) == "red"
    row["date"] = "2026-08-20"                                         # reposted with a new date: a new posting
    r4 = read("2026-08-21T18:00:00Z", r3)
    assert len(r4) == 3 and any(r["started_at"] == "2026-08-20" and r["status"] == "advisory_active" for r in r4)


# ---------------------------------------------------------------- re-review 2026-11-14 P2-4: the split counties

@pytest.mark.parametrize("lat,lon,county,zone", [
    (47.8, -103.8, "McKenzie County", zones.MOUNTAIN), (47.8, -102.8, "McKenzie County", zones.CENTRAL),
    (46.0, -101.8, "Sioux County", zones.MOUNTAIN), (46.0, -100.9, "Sioux County", zones.CENTRAL)])
def test_p2_4_a_point_in_a_split_county_is_read_on_its_side_of_the_line(lat, lon, county, zone):
    assert zones.nd_point_county(lat, lon) == county
    for given in (county, None):                       # the county given by the source, or found from the point
        z, basis = zones.north_dakota_zone(given, lat, lon)
        assert z == zone and "side" in basis and "NTAD" in basis
        assert zones.north_dakota_zone_uncertain(given, lat, lon) is False


def test_p2_4_a_county_only_record_states_that_its_zone_is_assumed():
    z, basis = zones.north_dakota_zone("Sioux County")
    assert z == zones.MOUNTAIN and "not known" in basis and zones.north_dakota_zone_uncertain("Sioux County")
    assert not zones.north_dakota_zone_uncertain("Stark County") and not zones.north_dakota_zone_uncertain("Cass")
    rows, _ = L.parse_page((FIX / "legacy-search-sample.html").read_text())
    row = dict(next(r for r in rows if L.keep(r) and r["latitude"]))
    east = L.record(dict(row, county="McKenzie", latitude="47.8", longitude="-102.8"), FETCHED)
    assert east["raw"]["time_zone"] == zones.CENTRAL and "time_zone_uncertain" not in east["raw"]
    blind = L.record(dict(row, county="McKenzie", latitude="", longitude=""), FETCHED)
    assert blind["raw"]["time_zone"] == zones.MOUNTAIN and blind["raw"]["time_zone_uncertain"] is True


def test_p2_4_other_states_clocks_are_unchanged():
    for st, lat, lon in (("NE", 41.25, -96.0), ("TN", 36.16, -86.78), ("FL", 30.44, -84.28), ("OR", 45.52, -122.68)):
        assert zones.zone_for(st, lat, lon) == {"NE": zones.CENTRAL, "TN": zones.CENTRAL, "FL": "America/New_York",
                                                "OR": "America/Los_Angeles"}[st]
