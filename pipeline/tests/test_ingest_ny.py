"""New York ingesters: workbook clocks, coordinates, volumes, chains, water names, the DEC page
template, NYC advisory episodes and beach reasons (no network)."""
from datetime import UTC, datetime

from ingest import ny_beaches_habs, ny_sprtk, ny_sprtk_web, ny_waters, nyc_dep_advisories


def _resolve(text):
    v, fam = ny_sprtk.parse_dt(text)
    era, _ = ny_sprtk.row_era(v, fam)
    return ny_sprtk.resolve(v, fam, era)


def test_workbook_clocks():
    # 2026 tab: UTC (17:37 in the workbook = 13:37 EDT in the alert text)
    v, prec, basis = _resolve("05/14/2026 17:37:00")
    assert basis == "utc" and ny_sprtk.local_iso(v) == "2026-05-14T13:37:00-04:00" and prec == "minute"
    # April-July 2024 tab: local time (Warwick's chain start 17:11:51 EDT)
    v, _, basis = _resolve("03/18/2024 17:11:51")
    assert basis == "local" and ny_sprtk.local_iso(v) == "2024-03-18T17:11:51-04:00"
    # DD/MON tab: the same start shown 4 h early (EDT) ...
    v, _, basis = _resolve("18/MAR/2024 13:11:51")
    assert basis == "dmon_shifted" and ny_sprtk.local_iso(v) == "2024-03-18T17:11:51-04:00"
    # ... and 5 h early in winter (EST)
    v, _, _ = _resolve("15/JAN/2025 16:15:00")
    assert ny_sprtk.local_iso(v) == "2025-01-15T21:15:00-05:00"
    # date-only tabs and whole Excel serials: day precision
    v, prec, basis = _resolve("2021-01-01")
    assert prec == "day" and basis == "date" and ny_sprtk.local_iso(v) == "2021-01-01T00:00:00-05:00"
    assert ny_sprtk.parse_dt("44502") == (datetime(2021, 11, 2).date(), "serial_date")


def test_coordinates_swapped_and_sign():
    lat, lon, note = ny_sprtk.coords({"latitude": "-73.58801308780096", "longitude": "43.29781286752899"}, "NY0183695")
    assert (lat, lon) == (43.297813, -73.588013) and "swapped" in note
    lat, lon, note = ny_sprtk.coords({"latitude": "73.5880", "longitude": "43.2978"}, "NY0183695")
    assert (lat, lon) == (43.2978, -73.588) and "minus" in note
    assert ny_sprtk.coords({"latitude": "73", "longitude": "44"}, "X")[0] is None
    assert ny_sprtk.coords({"latitude": "-74.0", "longitude": "40.7"}, "NYCDEPCSO")[0] is None


def test_volumes():
    assert ny_sprtk.volume_of("5000000 Gallons Estimated", "New")[:3] == (5000000, "5000000 Gallons Estimated", "estimated")
    assert ny_sprtk.volume_of("26,400 Gallons Actual", "Update")[2] == "measured"
    gal, text, flag, note = ny_sprtk.volume_of("381 Gallons per Minute Estimated", "Update")
    assert gal is None and flag == "estimated" and "rate" in note
    assert ny_sprtk.volume_of("0 Gallons per Minute Actual", "New")[2] == "estimated"
    assert ny_sprtk.volume_of("9 M Gallons Estimated", "Close")[0] == 9_000_000
    assert ny_sprtk.volume_of("between 10,000 and 20,000 Gallons Estimated", "Close")[0] is None


def _notice(nid, status, air, start, fac="NY0027081", street="1 Main"):
    n = {"id": nid, "synthetic_id": False, "tab": "t", "tab_index": 0, "row": 2, "row_raw": {}, "website": False,
         "f": {"notificationId": nid, "notificationStatus": status, "airDateTime": air, "startDateTime": start,
               "facilityId": fac, "facilityName": "Metropolitan Syracuse WWTP", "streetNumber": street,
               "streetName": "Velasko", "city": "Syracuse"}}
    ny_sprtk.parse_notice(n)
    return n


def test_chains_by_key_and_edited_start():
    a = _notice("1001", "New", "04/16/2026 23:40:00", "04/16/2026 23:35:00")
    b = _notice("1002", "Close", "04/17/2026 18:00:00", "04/16/2026 23:30:00")   # start edited by 5 minutes
    c = _notice("1003", "New", "04/16/2026 23:41:00", "04/16/2026 23:35:00", street="2 Other")
    chains = ny_sprtk.build_chains([a, b, c])
    assert sorted(len(v) for v in chains.values()) == [1, 2]
    two = next(v for v in chains.values() if len(v) == 2)
    assert [x["id"] for x in two] == ["1001", "1002"] and "edited" in two[1]["chain_basis"]


def test_classify():
    assert ny_sprtk.classify({"systemComponent": "CSO Outfall - Kelsey CSO"})[0] == "cso"
    assert ny_sprtk.classify({"systemComponent": "Manhole -", "treatedState": "Untreated"})[0] == "sso"
    assert ny_sprtk.classify({"treatedState": "Partially Treated with Disinfection"})[0] == "bypass"
    t, basis = ny_sprtk.classify({"facilityName": "Niagara Falls (C) WWTP", "treatedState": "Untreated",
                                  "explanation": "Heavy Rain"}, {"NY0026336"}, "NY0026336")
    assert t == "cso" and basis.startswith("inferred")


def test_water_names():
    assert ny_waters.match_waters("White Lake Brook")[0] == []
    assert ny_waters.match_waters("Little Niagara")[0] == []
    assert ny_waters.match_waters("Tributary of Longhouse creek")[0] == []
    assert ny_waters.match_waters("Lake Champlain - Cumberland Bay")[0] == ["lake-champlain-ny"]
    assert ny_waters.match_waters("Newtown Creek", None, (-73.95, 40.73))[0] == []       # not the Elmira stream
    assert ny_waters.match_waters("Hudson River", None, (-73.75, 42.65))[0] == ["hudson-river-ny"]


SAMPLE = ("New York Sewage Pollution Right to Know UPDATE Issued: 10-31-2026, 20:59:00  Affects: New York - Orange - "
          "Warwick The Warwick (T) SD #1 NY0021890, NY0021890 is issuing this notification. Discharge location: 50 State "
          "School Rd, Warwick, NY Location details:  Waterbody affected: Tributary of Longhouse creek Discharge "
          "description:  Potentially impacted public areas:  -  Discharge date and time: 05-30-2025 00:00:00 Discharge "
          "duration: unknown Hours  Discharge reason: System Capacity -  Sand filter system not operating correctly Steps "
          "taken to contain discharge: Working to upgrade and repair the facility Volume/rate of discharge: 60,000 Gallons "
          "Estimated  Treated state of discharge: Partially Treated with Disinfection Additional information:     For more "
          "information on the Sewage Pollution Right to Know Act visit SPRTK. [Disclaimer: Daily and/or termination "
          "reports will be provided for ongoing discharges.]")


def test_dec_page_template():
    m = ny_sprtk_web.parse_message(SAMPLE)
    assert m["word"] == "UPDATE" and m["facility_id"] == "NY0021890"
    assert m["affects"] == "New York - Orange - Warwick"
    assert m["waterbody"] == "Tributary of Longhouse creek"
    assert m["volume"] == "60,000 Gallons Estimated" and m["additional"] is None
    assert ny_sprtk_web.local_dt(m["discharge_datetime"]).isoformat() == "2025-05-30T00:00:00-04:00"
    assert ny_sprtk_web.duration_hours("36 hours 45 min Hours") == 36.75
    assert ny_sprtk_web.duration_hours("unknown Hours") is None


def _row(wid, occurred, dur, msg="Advisory"):
    return {"occurredOn": occurred, "waterbody": {"id": wid, "name": "Flushing Bay", "class": "I", "rainGauge": "BB"},
            "duration": dur, "message": msg if dur else "No Advisory", "volume": 0.0}


def test_nyc_episode_opens_extends_and_lifts():
    state = {}
    t0 = datetime(2026, 11, 3, 15, tzinfo=UTC)
    nyc_dep_advisories.poll(state, [_row(10, "2026-11-03T09:00:00", 24)], t0, {}, {})
    nyc_dep_advisories.poll(state, [_row(10, "2026-11-03T10:00:00", 30)], t0, {}, {})
    (ep,) = state["episodes"].values()
    assert ep["started_at"] == "2026-11-03T09:00:00-05:00" and ep["until"] == "2026-11-04T16:00:00-05:00"
    nyc_dep_advisories.poll(state, [_row(10, "2026-11-04T08:00:00", 0)], t0, {}, {})
    assert ep["state"] == "lifted" and ep["ended_at"] == "2026-11-04T08:00:00-05:00"
    rec = nyc_dep_advisories.to_record(ep, {}, "2026-11-04T13:00:00Z")
    assert rec["status"] == "advisory_lifted" and rec["water_slugs"] == ["flushing-bay-ny"] and rec["event_type"] == "cso"


def test_beach_reasons():
    q = ny_beaches_habs.qualifies
    assert q("Closed", "Exceedance") == "closed"
    assert q("Closed", "Preemptive: rainfall") == "closed"
    assert q("Open with Advisory", "Exceedance") == "advisory"
    assert q("Closed", "Harmful Algal Bloom") == "closed"
    assert q("Closed", "Closed for end of season") is None
    assert q("Closed", "No lifeguard") is None
    assert q("Reopened", "Harmful Algal Bloom clear") is None
    assert q("Closed", None) is None
