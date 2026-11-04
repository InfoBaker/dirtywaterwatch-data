"""Maryland ingesters: the MDE statewide table (composite key, coordinate repair, receiving-water rules,
duplicates), Baltimore DPW's SSO layer (wall-clock times stored as UTC) and Anne Arundel County's
closings (notices edited in place), and the Maryland name traps (no network). Fixture values are
taken from research/md/raw and the MDE CSV of 2026-11-02; no personal names."""
from __future__ import annotations

from ingest import md_aa_health_closings as A
from ingest import md_baltimore_sso as B
from ingest import md_mde_overflows as M
from ingest import md_waters as W

FETCHED = "2026-11-02T20:00:00Z"
META = {"rowsUpdatedAt": 1793634953}          # 2026-11-02 15:55:53 UTC


def row(**kw):
    base = {"overflow_type": "SSO", "facility_collection_system": "Back River WWTP Collection System - Baltimore City",
            "npdes_no": "MDC021555", "start_date": "05/23/2026", "start_time": "02:05:00", "duration_day": "0",
            "duration_hour": "2", "duration_minute": "45", "overflow_address": "428 East Preston St", "zip": "21202",
            "owner_name": "Baltimore City DPW", "discharge_volume": "58080", "overflow_cause": "Rain.",
            "receiving_water": "Jones Falls River, Use I", "county": "Baltimore City", "penalty_id": "",
            "overflow_latitude": "39.3049", "overflow_longitude": "-76.6100", "id": "375"}
    base.update(kw)
    return base


def build(rows, prev=(), dpw=()):
    permits, _ = M.load_dischargers()
    recs, stats = M.build(list(rows), META, FETCHED, list(prev), list(dpw), permits)
    return {r["event_id"]: r for r in recs}, stats


# ---------------------------------------------------------------- MDE: key, times, types

def test_composite_key_ignores_row_number_and_address_spelling():
    a = row(id="375")
    b = row(id="12", overflow_address="428 E\xa0Preston  Street")     # reloaded: new id, other spelling
    assert M.base_key(a) == M.base_key(b) == "mdc021555-20260523T0205-428-e-preston-st"
    assert M.base_key(row(start_time="02:06:00")) != M.base_key(a)
    assert M.base_key(row(npdes_no="")) .startswith("none-20260523T0205-")


def test_repeated_rows_get_suffixes_and_point_at_the_first():
    recs, stats = build([row(discharge_volume="15380", id="1"), row(discharge_volume="15380", id="2"),
                         row(discharge_volume="100", id="3")])
    ids = sorted(recs)
    base = "md-mde-overflows:mdc021555-20260523T0205-428-e-preston-st"
    assert ids == [base, base + "~2", base + "~3"]
    assert recs[base]["duplicate_of"] is None
    assert recs[base + "~2"]["duplicate_of"] == base and recs[base + "~3"]["duplicate_of"] == base
    assert stats["duplicates"]["repeated_rows"] == 2


def test_times_types_and_operator():
    recs, _ = build([
        row(),
        row(overflow_type="Unauthorized Discharge", npdes_no="MD0021598", owner_name="Mayor and City Council of Cumberland",
            overflow_address="Franklin Street", start_date="10/15/2026", start_time="13:26:00", duration_hour="1",
            duration_minute="38", receiving_water="Wills Creek & Potomac River", county="Allegany",
            overflow_latitude="", overflow_longitude=""),
        row(overflow_type="SSO", npdes_no="MDC521199", owner_name="DC Water", overflow_address="",
            start_date="01/19/2026", start_time="16:00:00", discharge_volume="280000000",
            receiving_water="Potomac River", county="Montgomery", duration_day="", duration_hour="", duration_minute=""),
    ])
    p = recs["md-mde-overflows:mdc021555-20260523T0205-428-e-preston-st"]
    assert p["started_at"] == "2026-05-23T02:05:00-04:00" and p["ended_at"] == "2026-05-23T04:50:00-04:00"
    assert p["status"] == "ended" and p["time_precision"] == "minute"
    assert p["source_updated_at"] == "2026-11-02T10:55:53-05:00" and p["fetched_at"] == FETCHED
    assert p["published_at"] is None and p["reported_at"] is None
    assert p["discharger_id"] == "md-baltimore-city-dpw" and p["authority"] == "Baltimore City DPW"
    assert p["npdes_permit"] is None            # MDC021555 is MDE's collection-system id, not a permit
    c = recs["md-mde-overflows:md0021598-20261015T1326-franklin-st"]
    assert c["event_type"] == "sso" and c["raw"]["_source_type"] == "Unauthorized Discharge"
    assert c["npdes_permit"] == "MD0021598" and c["discharger_id"] == "md-cumberland"
    assert c["water_slugs"] == ["north-branch-potomac-river-md"]      # Allegany: the Potomac at Cumberland
    dc = recs["md-mde-overflows:mdc521199-20260119T1600-no-address"]
    assert dc["discharger_id"] == "dc-water" and dc["volume_gal"] == 280_000_000
    assert dc["status"] == "unknown" and dc["ended_at"] is None        # no duration given
    assert dc["water_slugs"] == ["potomac-river-md"]


# ---------------------------------------------------------------- MDE: coordinates

def test_swapped_and_unsigned_coordinates_are_repaired_only_into_maryland():
    assert M.coords("39.3049", "-76.6100")[:2] == (39.3049, -76.61)
    lat, lon, note = M.coords("-76.6342", "39.3567")           # 2025-02-13 Deepdene Rd
    assert (lat, lon) == (39.3567, -76.6342) and "swapped" in note
    lat, lon, note = M.coords("78.7754", "39.6591")            # Allegany: swapped, no minus sign
    assert (lat, lon) == (39.6591, -78.7754) and "minus sign" in note
    assert M.coords("39.6591", "78.7754")[:2] == (39.6591, -78.7754)
    assert M.coords("39.2316", "-76.591C")[:2] == (39.2316, -76.591)   # longitude typed as text
    assert M.coords("", "76°22'46.5\"W")[:2] == (None, None)       # one coordinate only
    assert M.coords("6632", "2557")[:2] == (None, None)                  # not degrees
    lat, lon, note = M.coords("37.6438", "-77.6037")                     # Virginia
    assert lat is None and "not in Maryland" in note
    assert M.coords("39.3121", "39.3121")[:2] == (None, None)


def test_degrees_and_decimal_minutes_written_as_decimal_degrees_are_read_as_minutes_inside_the_county():
    """2026-11-03: Braddock Run's LaVale rows (52 reports 46 km off). 39.4012, -78.4734 is in West Virginia;
    39 deg 40.12 min N, 78 deg 47.34 min W is 1 Old Mt Savage Rd, LaVale (the same address's other row gives
    39.67, -78.7934)."""
    lat, lon, note = M.coords("39.4012", "-78.4734", "Allegany")
    assert (round(lat, 3), round(lon, 3)) == (39.669, -78.789) and "decimal minutes" in note
    assert "outside Allegany County" in note
    lat, lon, note = M.coords("-78.4734", "39.4011", "Allegany")            # swapped, then minutes
    assert (round(lat, 3), round(lon, 3)) == (39.669, -78.789) and "swapped" in note
    lat, lon, _ = M.coords("39.3824", "-78.5121", "Allegany")                # 12610 Labers Lane (other row: 39.6397, -78.8559)
    assert abs(lat - 39.6397) < 0.01 and abs(lon + 78.8559) < 0.01
    lat, lon, _ = M.coords("39.3932", "-78.5555", "Allegany")                # Jennings Run, Frostburg
    assert (round(lat, 3), round(lon, 3)) == (39.655, -78.926)
    lat, lon, _ = M.coords("39.382", "-78.5557", "Allegany")                 # three decimals (a trailing zero dropped)
    assert (round(lat, 3), round(lon, 3)) == (39.637, -78.926)
    lat, lon, _ = M.coords("39.1632", "-76.4958", "Howard")                  # North Chatham Rd, Ellicott City
    assert (round(lat, 3), round(lon, 3)) == (39.272, -76.826)
    # never changed: a point inside its county, a row with no county or an unknown one, minutes of 60 or more
    assert M.coords("39.6358", "-78.8418", "Allegany")[:2] == (39.6358, -78.8418)      # 1268 National Hwy, as given
    assert M.coords("39.4012", "-78.4734")[:2] == (39.4012, -78.4734)
    assert M.coords("39.4012", "-78.4734", "Nowhere")[:2] == (39.4012, -78.4734)
    assert M.coords("39.3861", "-78.7698", "Allegany")[:2] == (39.3861, -78.7698)       # 76.98 is not minutes
    assert M.coords("39.3049", "-76.6100", "Baltimore City")[:2] == (39.3049, -76.61)
    assert M.coords("39.67", "-78.7934", "Allegany")[:2] == (39.67, -78.7934)           # two decimals, in the county
    lat, lon, note = M.coords("39.6", "-78.4", "Allegany")                              # too few decimals to be minutes
    assert (lat, lon) == (39.6, -78.4) and "decimal minutes" not in note


def test_a_dmm_row_is_placed_where_its_address_is_and_says_so():
    recs, stats = build([row(npdes_no="MD0067547", receiving_water="Braddock Run", county="Allegany",
                             overflow_address="1 Old Mt Savage Rd", overflow_latitude="39.4012",
                             overflow_longitude="-78.4734", zip="21502", owner_name="LaVale Sanitary Commission")])
    r = next(iter(recs.values()))
    assert (round(r["lat"], 3), round(r["lon"], 3)) == (39.669, -78.789) and r["coord_source"] == "source"
    assert "read as degrees and decimal minutes" in r["raw"]["_coords"]
    assert r["raw"]["row"]["overflow_latitude"] == "39.4012"             # the source value stays in the raw row
    assert stats["coordinate_repairs"] == {"as given, read as degrees and decimal minutes": 1}


# ---------------------------------------------------------------- MDE: receiving water

def test_none_ground_and_storm_drain_keep_their_text_and_colour_no_water():
    for text in ("none", "None.", "N/A", "NA", "n/a", "no", "Groundwater.", "storm drain", "Storm Drain", "unknown", ""):
        slugs, match, note = M.water_of(text, "Baltimore", None, None)
        assert slugs == [] and match == "none", text
        assert "decision 3" in note["why_none"], text
    recs, _ = build([row(receiving_water="None", overflow_address="3915 Stokes Drive", npdes_no="MDC021601")])
    r = next(iter(recs.values()))
    assert r["waterbody_text"] == "None" and r["water_slugs"] == [] and r["water_match"] == "none"
    slugs, match, _ = M.water_of("Did not enter body of water", "Baltimore", None, None)
    assert slugs == [] and match == "none"
    slugs, _, _ = M.water_of("Storm drain leading to Bear Creek", "Baltimore", None, None)
    assert slugs == ["bear-creek-md"]
    assert M.water_of("Patapsco River", "Anne Arundel", 39.20, -76.55)[0] == ["patapsco-river-md"]


def test_maryland_name_traps():
    assert W.match_waters("Mill Creek", county="Anne Arundel")[0] == []          # mill-creek-md is Perryville
    assert W.match_waters("Mill Creek", county="Cecil")[0] == ["mill-creek-md"]
    assert W.match_waters("Broad Creek", county="Prince George's")[0] == []      # broad-creek-md is Darlington
    assert W.match_waters("Herring Creek", county="Baltimore")[0] == []          # herring-creek-md is St. Mary's
    assert W.match_waters("Back Creek", county="Baltimore")[0] == []             # back-creek-md is Annapolis
    assert W.match_waters("Wicomico River", county="Wicomico")[0] == ["wicomico-river-mt-vernon-md"]
    assert W.match_waters("Wicomico River", county="St. Mary's")[0] == ["wicomico-river-md"]
    assert W.match_waters("Wicomico River")[0] == []
    assert W.match_waters("Little Patuxent River", county="Howard")[0] == []
    assert W.match_waters("Potomac River", county="Montgomery")[0] == ["potomac-river-md"]
    assert W.match_waters("Western Branch", county="Prince George's")[0] == ["western-branch-patuxent-river-md"]
    assert W.match_waters("Western Branch", county="Baltimore")[0] == []
    assert W.match_waters("Western Branch", None, (-76.95, 38.95), "Prince George's")[0] == []   # point outside its box


# ---------------------------------------------------------------- MDE: duplicates

def test_same_overflow_under_two_owners_keeps_both_and_marks_the_lower_volume():
    city = row()
    county = row(npdes_no="MDC121601", facility_collection_system="Patapsco WWTP Collection System - Baltimore County",
                 owner_name="Baltimore County DPW", overflow_address="428 E Preston Street", discharge_volume="10000",
                 duration_hour="0", receiving_water="Jones Fall River", county="Baltimore", overflow_latitude="",
                 overflow_longitude="", zip="", id="376")
    recs, stats = build([city, county])
    c, k = (recs["md-mde-overflows:mdc021555-20260523T0205-428-e-preston-st"],
            recs["md-mde-overflows:mdc121601-20260523T0205-428-e-preston-st"])
    assert c["duplicate_of"] is None and k["duplicate_of"] == c["event_id"]
    assert k["discharger_id"] == "md-baltimore-county-dpw" and "lower-volume" in k["raw"]["_duplicate_basis"]
    assert stats["duplicates"]["same_start_and_address"] == 1


def test_mde_row_points_at_the_baltimore_dpw_record():
    a = {"OBJECTID": 25942, "SSO_DATE": 1791717300000, "LOCATION": "428 E Preston St - SSO Site #72",
         "EST_VOLUME": 672000.07, "EST_FLOW": 1701.266, "STATUS": "5DAY", "REC_WATERS": "JF", "WATERSHED": 2130904,
         "START_DATETIME": 1791717300000, "END_DATETIME": 1791741000000, "RESPONSIBILITY": "DPW",
         "Latitude": 39.30549853, "Longitude": -76.60973024, "SITE_TYPE": "Structured SSO", "SENSITIVE_AREA": 0}
    dpw = B.to_record(a, FETCHED, None)
    mde = row(start_date="10/11/2026", start_time="11:15:00", duration_hour="6", duration_minute="35",
              discharge_volume="672000", overflow_latitude="", overflow_longitude="")
    near = row(start_date="10/11/2026", start_time="12:00:00", overflow_address="Hillen St and E Preston St",
               discharge_volume="300", overflow_latitude="39.3060", overflow_longitude="-76.6095")   # ~130 m away
    other_day = row(start_date="10/12/2026", start_time="11:15:00", discharge_volume="5")
    county = row(start_date="10/11/2026", start_time="11:15:00", npdes_no="MDC121555", owner_name="Baltimore County DPW",
                 overflow_address="9 Elsewhere Rd", discharge_volume="7", county="Baltimore")
    recs, stats = build([mde, near, other_day, county], dpw=[dpw])
    assert recs["md-mde-overflows:mdc021555-20261011T1115-428-e-preston-st"]["duplicate_of"] == "md-baltimore-sso:25942"
    n = recs["md-mde-overflows:mdc021555-20261011T1200-hillen-st-and-e-preston-st"]
    assert n["duplicate_of"] == "md-baltimore-sso:25942" and " m apart" in n["raw"]["_duplicate_basis"]
    assert recs["md-mde-overflows:mdc021555-20261012T1115-428-e-preston-st"]["duplicate_of"] is None   # another day
    assert recs["md-mde-overflows:mdc121555-20261011T1115-9-elsewhere-rd"]["duplicate_of"] is None      # another operator
    assert stats["duplicates"]["baltimore_dpw"] == 2


def test_rows_marked_duplicate_by_mde_point_at_the_original():
    orig = row(npdes_no="MDC021601", start_date="07/07/2026", start_time="10:48:00", overflow_address="2211 Arden Rd",
               discharge_volume="216000")
    marked = row(npdes_no="MDC021601", start_date="07/07/2026", start_time="10:48:00",
                 overflow_address="2211 Arden Rd (DUPLICATE)", discharge_volume="",
                 overflow_cause="DUPLICATE - see original report", receiving_water="DUPLICATE - see original report")
    recs, _ = build([orig, marked])
    m = recs["md-mde-overflows:mdc021601-20260707T1048-2211-arden-rd-duplicate"]
    assert m["duplicate_of"] == "md-mde-overflows:mdc021601-20260707T1048-2211-arden-rd"
    assert m["water_match"] == "none"


# ---------------------------------------------------------------- MDE: revisions, vanished rows, names

def test_revisions_are_kept_and_vanished_rows_point_at_their_corrected_form():
    first, _ = build([row(discharge_volume="11000"), row(start_date="04/01/2026", overflow_address="1 Old Spelling Ave")])
    prev = list(first.values())
    second, stats = build([row(discharge_volume="17520"), row(start_date="04/01/2026", overflow_address="1 New Spelling Ave")],
                          prev=prev)
    r = second["md-mde-overflows:mdc021555-20260523T0205-428-e-preston-st"]
    assert r["volume_gal"] == 17520
    assert r["raw"]["_revisions"][0]["old_values"] == {"discharge_volume": "11000"}
    assert r["raw"]["_first_seen_at"] == FETCHED
    old = second["md-mde-overflows:mdc021555-20260401T0205-1-old-spelling-ave"]
    assert old["raw"]["_missing_from_source_since"] == FETCHED
    assert old["duplicate_of"] == "md-mde-overflows:mdc021555-20260401T0205-1-new-spelling-ave"
    assert stats["vanished"] == {"superseded_by_corrected_row": 1}


def test_names_after_an_honorific_do_not_reach_the_record():
    recs, _ = build([row(overflow_cause="Undetermined.  Mr. Example reports the canal was a factor.",
                         receiving_water="Ms. Sample Person, the property owner, said it reached a pond")])
    r = next(iter(recs.values()))
    assert "Example" not in r["raw"]["row"]["overflow_cause"] and "[name removed]" in r["raw"]["row"]["overflow_cause"]
    assert "Sample" not in (r["waterbody_text"] or "")
    assert M.scrub_people("Mr. Rooter cleared the line") == "Mr. Rooter cleared the line"     # allowlisted company


# ---------------------------------------------------------------- Baltimore DPW layer

def test_baltimore_wall_clock_times_and_status():
    assert B.wall_clock(1791717300000).isoformat() == "2026-10-11T11:15:00-04:00"   # MDE: 11:15 the same day
    assert B.wall_clock(1793622000000).isoformat() == "2026-11-02T12:20:00-05:00"   # after the DST change
    a = {"OBJECTID": 25942, "SSO_DATE": 1791717300000, "LOCATION": "428 E Preston St - SSO Site #72",
         "EST_VOLUME": 672000.07, "STATUS": "5DAY", "REC_WATERS": "JF", "WATERSHED": 2130904,
         "START_DATETIME": 1791717300000, "END_DATETIME": 1791741000000, "RESPONSIBILITY": "DPW",
         "Latitude": 39.30549853, "Longitude": -76.60973024, "SITE_TYPE": "Structured SSO"}
    r = B.to_record(a, FETCHED, None)
    assert (r["started_at"], r["ended_at"], r["status"]) == ("2026-10-11T11:15:00-04:00", "2026-10-11T17:50:00-04:00", "ended")
    assert r["volume_gal"] == 672000 and r["estimate_flag"] == "estimated"
    assert r["waterbody_text"] == "Jones Falls" and r["water_slugs"] == [] and r["outfall_id"] == "SSO Site #72"
    assert r["discharger_id"] == "md-baltimore-city-dpw" and r["raw"]["_watershed_name"] == "Jones Falls"
    prog = B.to_record({"OBJECTID": 25958, "SSO_DATE": 1793622000000, "START_DATETIME": 1793622000000,
                        "END_DATETIME": 1793630000000, "STATUS": "PROG", "LOCATION": "5693 Liberty Heights Ave ",
                        "Latitude": 39.33512068, "Longitude": -76.70769947, "SITE_TYPE": "Standard",
                        "RESPONSIBILITY": None, "REC_WATERS": None}, FETCHED, None)
    assert prog["status"] == "ongoing" and prog["ended_at"] is None and prog["raw"]["_end_while_in_progress"]
    assert prog["discharger_id"] is None and prog["waterbody_text"] is None
    nw = B.to_record({"OBJECTID": 25927, "START_DATETIME": 1791717300000, "STATUS": "5DAY", "REC_WATERS": "NWHB",
                      "RESPONSIBILITY": "PRI", "Latitude": 39.2786, "Longitude": -76.5932}, FETCHED, None)
    assert nw["water_slugs"] == ["northwest-harbor-md"] and nw["status"] == "unknown" and nw["discharger_id"] is None


def test_baltimore_keeps_records_that_left_the_layer():
    a = {"OBJECTID": 1, "START_DATETIME": 1791717300000, "END_DATETIME": 1791741000000, "STATUS": "PROG"}
    first, _ = B.build([a], FETCHED, [])
    second, stats = B.build([{**a, "STATUS": "5DAY", "EST_VOLUME": 10.0}], "2026-11-03T20:00:00Z", first)
    r = second[0]
    assert r["status"] == "ended" and [s["status"] for s in r["raw"]["_status_seen"]] == ["PROG", "5DAY"]
    assert r["raw"]["_first_seen_at"] == FETCHED
    third, stats = B.build([], "2026-11-04T20:00:00Z", second)
    assert third[0]["raw"]["_missing_from_layer_since"] == "2026-11-04T20:00:00Z" and stats["kept_from_earlier_runs"] == 1


# ---------------------------------------------------------------- Anne Arundel County closings

def page(paragraphs, title, nid="1847", slug="update-6-9-26-emergency"):
    body = "".join(f"<p>{p}</p><hr>" for p in paragraphs)
    return (f'<html><head><link rel="canonical" href="https://www.aahealth.org{A.LIST_PATH}/{slug}" />'
            f'<link rel="shortlink" href="https://www.aahealth.org/node/{nid}" /></head><body><main>'
            f"<h1>{title}</h1><div id=\"block-anne-arundel-content\"><article><div>{body}</div></article></div>"
            f"</main></body></html>")


ORIGINAL = ("<strong>Severna Park, (June 2, 2026) -</strong> The Anne Arundel County Department of Health has issued an "
            "emergency closure for Cypress Creek in Severna Park to the headwaters of the Magothy River due to a large "
            "sewage spill. The affected waters are closed for direct water contact. The emergency closing will remain in "
            "effect for one week following a spill, unless the sewage spill is determined to adversely impact a "
            "designated bathing beach. Visit AAHealth.org or contact the water quality program at 410-222-7999.")
RESCINDED = ("<strong>Severna Park, MD (June 9, 2026) –</strong> Effective June 9, 2026, the Department of Health "
             "has rescinded this advisory.")


def recs_for(html, list_date, fetched):
    item = {"href": A.LIST_PATH + "/update-6-9-26-emergency", "title": None, "list_date": list_date}
    recs, _ = A.records_for(A.parse_notice(html), item, fetched)
    return {r["event_id"]: r for r in recs}


def test_aa_closure_edited_in_place_uses_the_page_dates():
    before = recs_for(page([ORIGINAL], "Emergency Closing Issued for Cypress Creek due to a Large Sewage Spill",
                           slug="emergency-closing-cypress"), "2026-06-02T10:00:00", "2026-06-03T12:00:00Z")
    assert list(before) == ["md-aa-health-closings:node-1847"]
    r = before["md-aa-health-closings:node-1847"]
    assert (r["event_type"], r["status"]) == ("beach_closure", "advisory_active")
    assert r["started_at"] == r["published_at"] == "2026-06-02T00:00:00-04:00" and r["time_precision"] == "day"
    assert r["ended_at"] == "2026-06-09T00:00:00-04:00" and "one week" in r["raw"]["_valid_until_basis"]
    assert r["waterbody_text"] == "Cypress Creek in Severna Park to the headwaters of the Magothy River"
    assert r["water_slugs"] == ["magothy-river-md"]
    assert "closed for direct water contact" in r["advice_text"] and "410" not in r["advice_text"]
    # the same page a week later: the rescission is added above the original and the title gains *Update*
    after = recs_for(page([RESCINDED, ORIGINAL], "*Update 6-9-26* Emergency Closing Issued for Cypress Creek due to a "
                          "Large Sewage Spill"), "2026-06-09T16:38:21", "2026-11-02T20:00:00Z")
    assert set(after) == {"md-aa-health-closings:node-1847", "md-aa-health-closings:node-1847:20260609-lifted"}
    assert after["md-aa-health-closings:node-1847"]["started_at"] == "2026-06-02T00:00:00-04:00"   # unchanged
    lift = after["md-aa-health-closings:node-1847:20260609-lifted"]
    assert lift["parent_event_id"] == "md-aa-health-closings:node-1847" and lift["status"] == "advisory_lifted"
    assert lift["started_at"] == "2026-06-02T00:00:00-04:00" and lift["ended_at"] == "2026-06-09T00:00:00-04:00"
    assert lift["published_at"] == "2026-06-09T00:00:00-04:00"
    assert lift["source_updated_at"] == "2026-06-09T00:00:00-04:00"     # the page's own date, not the fetch
    assert all("2026-11-02" not in (x["started_at"] + (x["ended_at"] or "") + (x["published_at"] or ""))
               for x in after.values())


def test_aa_rescission_with_a_typed_year_falls_back_to_the_title_date():
    html = page(["<strong>Annapolis, Maryland (March 6, 2024) –</strong> The Department of Health has rescinded "
                 "this advisory.",
                 "<strong>Annapolis, Maryland (February 26, 2025) –</strong> The Anne Arundel County Department of "
                 "Health has issued an emergency closure for a sanitary sewage overflow in excess of 10,000 gallons. The "
                 "affected area from the intersection of Fort Smallwood Road and Wagner Station Road to Brandon Shore "
                 "Road is closed. The emergency closing will remain in effect until further notice."],
                "*Update 3/6/25* Sanitary Sewer Overflow for The Intersection of Fort Smallwood Road", nid="1509")
    recs = recs_for(html, "2025-03-06T14:00:00", FETCHED)
    issued = recs["md-aa-health-closings:node-1509"]
    assert issued["ended_at"] is None and issued["waterbody_text"].startswith("the intersection of Fort Smallwood Road")
    lift = recs["md-aa-health-closings:node-1509:20250306-lifted"]
    assert lift["ended_at"] == "2025-03-06T00:00:00-05:00" and "title's update date" in lift["parse_error"]


def test_aa_list_and_sewage_filter():
    html = ('<div class="views-row"><div class="zn-date"><time datetime="2026-06-09T16:38:21">06/09/2026</time></div>'
            f'<h2><a href=""><a href="{A.LIST_PATH}/update-6-9-26-emergency" hreflang="en">*Update 6-9-26* Emergency '
            'Closing Issued for Cypress Creek due to a Large Sewage Spill</a></a></h2></div>'
            '<div class="views-row"><div class="zn-date"><time datetime="2026-06-05T13:31:00">06/05/2026</time></div>'
            f'<h2><a href=""><a href="{A.LIST_PATH}/update-6-5-2026-advisory" hreflang="en">*Update 6-5-2026* Advisory '
            'Issued for Herrington Harbor South Due to High Enterococci or Bacteria Levels</a></a></h2></div>')
    items = A.parse_list(html)
    assert [i["list_date"] for i in items] == ["2026-06-09T16:38:21", "2026-06-05T13:31:00"]
    pages = {items[0]["href"]: {"html": page([RESCINDED, ORIGINAL], items[0]["title"]), "fetched_at": FETCHED}}
    recs, stats = A.build(items, pages, FETCHED)
    assert stats["bacteria_advisories_skipped"] == 1 and stats["sewage_notices"] == 1 and len(recs) == 2
