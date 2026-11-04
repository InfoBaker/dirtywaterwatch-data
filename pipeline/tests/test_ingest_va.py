"""Virginia ingesters: PReP time decodings, duplicates, MS4 permits, classification and privacy;
VDH issued/lifted pairing and weekday notes; AlexRenew status changes; Richmond workbook rows
(no network; small fixtures taken from research/va/raw with personal fields left out)."""
import json
from pathlib import Path

import pytest

from ingest import va_alexrenew_cso as A
from ingest import va_deq_prep as P
from ingest import va_richmond_cso as R
from ingest import va_vdh_advisories as V
from ingest import va_waters as W

RAW = Path(__file__).resolve().parents[2] / "research" / "va" / "raw"
REFS = P.load_dischargers()


# ---------------------------------------------------------------- time decodings

def test_three_prep_time_encodings_give_the_same_local_time():
    # Douglas Avenue force main, PReP 324738: API 19:16:57 local; export 1785889017000; EDMA 1785871017000
    assert P.api_time("2026-08-04T19:16:57").isoformat() == "2026-08-04T19:16:57-04:00"
    assert P.export_time(1785889017000).isoformat() == "2026-08-04T19:16:57-04:00"   # local + 5 h, even in summer
    assert P.edma_time(1785871017000).isoformat() == "2026-08-04T19:16:57-04:00"     # local labelled as UTC
    # winter: 2026-01-10 12:00 EST is stored as 17:00 (export) and 12:00 (EDMA) on the epoch clock
    assert P.export_time(1768064400000).isoformat() == "2026-01-10T12:00:00-05:00"
    assert P.edma_time(1768046400000).isoformat() == "2026-01-10T12:00:00-05:00"
    assert P.api_time(None) is None and P.export_time(None) is None and P.edma_time("") is None


def test_other_va_time_bases():
    assert A.utc_ms(1767276822000).isoformat() == "2026-01-01T09:13:42-05:00"          # true UTC epoch
    assert R.excel_time("46222.77777777778").isoformat() == "2026-07-19T18:40:00-04:00"  # Excel serial, local
    assert V.iso_local("Mon, 17 Aug 2026 19:33:15 +0000") == "2026-08-17T15:33:15-04:00"


# ---------------------------------------------------------------- PReP records

def _api(**kw):
    base = {
        "id": "1", "incidentDateTime": "2026-08-04T19:16:57", "receivedDateTime": "2026-08-04T21:30:58",
        "isIncidentDateUnknown": "N", "sewageRelated": "Y", "siteName": "SSO - Douglass Ave - Portsmouth",
        "siteAddress1": "154 Rolfe Terrace", "siteCity": "Portsmouth", "receptorWaterbodyId": "Hull Creek",
        "receptorEstimateLow": 3137500.0, "receptorEstimateHigh": 3137500.0, "receptorUnitTypeId": 9,
        "ssorsId": "106791", "nrcId": "1469821, 1469813", "createdDate": "2026-08-04T21:30:30",
        "modifiedDate": "2026-08-18T08:37:45", "prepStatusCode": {"description": "Under Investigation"},
        "prepReportReleaseSubtypes": [{"prepReleaseSubtypeCode": {"name": "Sanitary Sewer Overflow"}}],
        "prepReportSewages": [{"duration": 14.0, "dischargeVolume": 3137500, "dischargeUnknown": "N",
                               "dischargeTreated": "N", "prepComponentTypeCode": {"description": "Pipe Failure"}}],
    }
    base.update(kw)
    return base


def test_prep_record_basics():
    rec = P.to_record(P.from_api(_api(id="324738")), REFS, None, "2026-11-02T12:00:00Z")
    assert rec["event_id"] == "va-deq-prep:324738" and rec["event_type"] == "sso"
    assert rec["started_at"] == "2026-08-04T19:16:57-04:00"
    assert rec["ended_at"] == "2026-08-05T09:16:57-04:00" and "duration 14 h" in rec["raw"]["_ended_at_basis"]
    assert rec["status"] == "ended" and rec["reported_at"] == "2026-08-04T21:30:58-04:00"
    assert rec["source_updated_at"] == "2026-08-18T08:37:45-04:00" and rec["published_at"] is None
    assert rec["volume_gal"] == 3137500 and rec["waterbody_text"] == "Hull Creek"
    assert rec["raw"]["attribution"].startswith("DEQ is the data source.")


def test_prep_duplicates_by_ssors_nrc_and_address():
    a = P.to_record(P.from_api(_api(id="324738")), REFS, None, "x")
    b = P.to_record(P.from_api(_api(id="324765", incidentDateTime="2026-08-04T16:00:00", siteAddress1="221 Douglass Avenue",
                                    otherWaterbodyDesc="Elizabeth River")), REFS, None, "x")
    # same address and date, different volumes: two manholes at one address, kept apart
    c = P.to_record(P.from_api(_api(id="325760", ssorsId=None, nrcId=None, siteAddress1="2304 Brambleton Ave SW",
                                    incidentDateTime="2026-10-11T09:45:00",
                                    prepReportSewages=[{"dischargeVolume": 36100}])), REFS, None, "x")
    d = P.to_record(P.from_api(_api(id="325761", ssorsId=None, nrcId=None, siteAddress1="2304 Brambleton Ave SW",
                                    incidentDateTime="2026-10-11T09:30:00",
                                    prepReportSewages=[{"dischargeVolume": 16875}])), REFS, None, "x")
    e = P.to_record(P.from_api(_api(id="325759", ssorsId=None, nrcId=None, siteAddress1="6801 Peters Creek Rd",
                                    incidentDateTime="2026-10-11T08:15:00",
                                    prepReportSewages=[{"dischargeVolume": 2925}])), REFS, None, "x")
    f = P.to_record(P.from_api(_api(id="325758", ssorsId=None, nrcId=None, siteAddress1="6801 Peters Creek Rd.",
                                    incidentDateTime="2026-10-11T08:15:00",
                                    prepReportSewages=[{"dischargeVolume": 2925}])), REFS, None, "x")
    recs = [b, a, c, d, e, f]
    assert P.mark_duplicates(recs) == 2
    assert b["duplicate_of"] == "va-deq-prep:324738" and a["duplicate_of"] is None
    assert set(b["raw"]["duplicate_basis"]) >= {"SSORS 106791", "NRC 1469821"}
    assert a["raw"]["duplicates"] == ["va-deq-prep:324765"]
    assert c["duplicate_of"] is None and d["duplicate_of"] is None
    assert e["duplicate_of"] == "va-deq-prep:325758" and f["duplicate_of"] is None


def test_ms4_permit_is_not_the_operators_vpdes_permit():
    # PReP 326062: Norfolk SSO filed with Norfolk's MS4 permit VA0088650 (DEQ link type WAT_MS4_IP)
    r = _api(id="326062", siteName="SSO - 8521 Executive Dr - Norfolk", ssorsId=None, nrcId="1477408",
             prepReportPermitViews=[{"type": "WAT_MS4_IP", "linkText": "633000000505"},
                                    {"type": "CORE_FAC", "linkText": "Norfolk City MS4"}],
             prepOriginalReport={"permitId": "VA0088650", "facilityPermitted": "N",
                                 "rpCompanyName": "City of Norfolk Utilities", "stillOccurring": "N"})
    rec = P.to_record(P.from_api(r), REFS, None, "x")
    assert rec["npdes_permit"] is None
    assert rec["raw"]["permit"]["typed_permit"] == "VA0088650" and "MS4" in rec["raw"]["permit"]["ms4"]
    assert rec["discharger_id"] == "va-norfolk-utilities"            # by the operator named, not the MS4 permit
    # an MS4 permit found only through DEQ's link type (not in the known list) is refused too
    rep = P.from_api(_api(prepReportPermitViews=[{"type": "WAT_MS4_IP", "linkText": "633000000999"}],
                          prepOriginalReport={"permitId": "VA0088888"}))
    assert P.permit_choice(rep)[0] is None
    assert P.permit_choice(P.from_api(_api(prepOriginalReport={"permitId": "VAR040068"})))[0] is None
    # DEQ's VPDES link wins and gives the discharger
    rep = P.from_api(_api(prepReportPermitViews=[{"type": "WAT_VPDES", "linkText": "VA0063690"}],
                          siteName="SSO - Henrico Conveyance - Manhole at 9319 Dolmen Road"))
    assert P.permit_choice(rep)[0] == "VA0063690"
    assert P.discharger_for(rep, "VA0063690", REFS)[0] == "va-henrico-dpu"
    # permit and name naming two different operators: none set
    rep = P.from_api(_api(siteName="SSO - Hopewell Conveyance - Manhole at 327 Woodbine Street",
                          prepOriginalReport={"permitId": "VA0063690"}))
    did, _, note = P.discharger_for(rep, "VA0063690", REFS)
    assert did is None and "review" in note["result"]


def test_prep_classification():
    def t(name, cats, comp=None):
        rep = {"site_name": name, "categories": cats, "sewage": [{"component": comp}] if comp else []}
        return P.classify(rep)[0]
    assert t("CSO - City of Lynchburg", ["Sanitary Sewer Overflow"]) == "cso"
    assert t("CSO (OF004) - City of Richmond Conveyance", ["Unauthorized Discharge of Pollutant(s)"]) == "cso"
    assert t("SSO - WVWA - Roanoke", ["Risk Tier Referred", "Sanitary Sewer Overflow"]) == "sso"
    assert t("SSO-City of Hopewell-Hopewell Water Renewal-Headworks of WWTP",
             ["Unauthorized Discharge of Pollutant(s)"]) == "bypass"
    assert t("Tappahannock WWTP - Loss of chlorination due to lightning strike",
             ["Unauthorized Discharge of Pollutant(s)"]) == "bypass"
    assert t("Bypass - City of Covington WWTP - EQ Tank", ["Sanitary Sewer Overflow"], "Bypass Outfall") == "bypass"
    assert t("SSO - Wintergreen Mountain WWTP", []) == "sso"
    assert t("Discharge from Laundry Facility", ["No Pollution Noted"]) == "unknown"


def test_prep_volume_placeholders():
    assert P._volume({"sewage": [], "low": 1, "high": -1, "unit": "Gallons"})[0:2] == (None, None)   # DEQ's "unknown"
    gal, text, flag, _ = P._volume({"sewage": [], "low": 0, "high": 725166, "unit": "Gallons"})
    assert gal is None and text.startswith("up to 725,166") and flag == "estimated"
    assert P._volume({"sewage": [{"volume_gal": 24900}], "low": 1, "high": 24900})[0] == 24900


def test_prep_personal_fields_never_reach_the_record():
    r = _api(createdBy="Pat.Doe", modifiedBy="Pat.Doe", legacyAssignedStaff="Pat Doe",
             incidentComment="Assigned to: Pat Doe, Assigned By: Pat.Doe. DEQ spoke with Ms. Roe about the spill.",
             prepOriginalReport={"rbFirstName": "Jo", "rbLastName": "Example", "rbPhone": "8045550100",
                                 "rbEmail": "jo@example.gov", "rpCompanyName": "Jo Example", "permitId": None},
             prepReportEvents=[{"eventDate": "2026-08-05T10:55:36", "comment": "Assigned to: Pat Doe",
                                "createdBy": "Pat.Doe", "prepEventTypeCode": {"description": "Assigned"}}])
    rec = P.to_record(P.from_api(r), REFS, None, "x")
    s = json.dumps(rec)
    for bad in ("Pat", "Doe", "Roe", "Jo ", "Example", "8045550100", "jo@example"):
        assert bad not in s, bad
    assert rec["raw"]["status_log"] == [{"at": "2026-08-05T10:55:36", "type": "Assigned"}]
    saved = json.dumps(P.scrub_obj({"results": [r]}, P.staff_names([r])))
    for bad in ("Pat", "Doe", "rbFirstName", "8045550100"):
        assert bad not in saved, bad


def test_prep_export_row():
    # the export table's Tappahannock row (research/va/raw/prep/tappahannock-jul2025.json)
    a = {"IR_NUMBER": "319799", "INCIDENT_NAME": "Tappahannock WWTP - Loss of chlorination due to lightning strike",
         "INCIDENT_DATE_TIME": 1751950800000, "RECEIVED_DATE_TIME": 1752096240000, "FIPS_CITY_COUNTY": "057/Essex County",
         "WATERBODY": "Hoskins Creek", "LOW_QUANTITY_TO_WATER": 0, "HIGH_QUANTITY_TO_WATER": 725166,
         "QUANTITY_UNITS": "Gallons", "INCIDENT_TYPES": "Unauthorized Discharge of Pollutant(s) (UDP)",
         "IR_DESCRIPTION_STATUS": "Closed", "ORIGINAL_REPORT_PERMIT_NUMBER": "VA0071471",
         "SEWAGE_INFO_DURATION_OF_EVENT_HRS": 28, "SEWAGE_INFO_DISCHARGE_VOLUMN_GALLONS": 725166}
    rec = P.to_record(P.from_export(a), REFS, None, "x")
    assert rec["started_at"] == "2025-07-08T00:00:00-04:00" and rec["time_precision"] == "day"
    assert rec["ended_at"] is None and rec["status"] == "ended"                # closed; a midnight start gets no end
    assert rec["event_type"] == "bypass" and rec["npdes_permit"] == "VA0071471"
    assert rec["discharger_id"] == "va-tappahannock" and rec["volume_gal"] == 725166
    assert rec["water_slugs"] == ["hoskins-creek-va"]


def test_edma_point_decoding():
    f = {"attributes": {"PRP_REPORT_ID": "324738", "REFERENCE_POINT": "PG", "PRP_INCIDENT_DATE_TIME": 1785871017000,
                        "PRP_REPORT_RECEIVED_DATE_TIME": 1785879058000},
         "geometry": {"x": -76.34028391112167, "y": 36.850855261839584}}
    pt = P.point_from_edma(f)["324738"]
    assert (pt["lat"], pt["lon"]) == (36.850855, -76.340284)
    assert pt["edma_incident"] == "2026-08-04T19:16:57-04:00" and pt["edma_received"] == "2026-08-04T21:30:58-04:00"


# ---------------------------------------------------------------- water names

def test_va_water_names():
    if not W.WATERS_JSON.exists():
        pytest.skip("data/waters-va.json missing")
    assert W.match_waters("The advisory area for Hull Creek extends throughout the Western Branch of the Elizabeth River.")[0] \
        == ["western-branch-elizabeth-river-va"]
    assert W.match_waters("Lynnhaven River")[0] == ["lynhaven-river-va"]
    assert W.match_waters("Hull Creek")[0] == []
    assert W.match_waters("Meredith Branch", ["Glen Allen"], (-77.5511, 37.6577))[0] == ["meredith-branch-va"]


# ---------------------------------------------------------------- VDH advisories

def _rel(title, published, text, link=None):
    return {"title": title, "link": link or f"https://www.vdh.virginia.gov/news/x/{abs(hash(title + published))}/",
            "pubDate": None, "published": published, "categories": ["Portsmouth Health Department"], "text": text,
            "action": V.action_of(title), "kind": V.kind_of(title), "tokens": V.subject_tokens(title)}


HULL_ISSUE = ("August 5, 2026\nRecreational Water Advisory Issued for Hull Creek following Sewer Main Break\n"
              "PORTSMOUTH, Va. – The Portsmouth Health Department is issuing a recreational water advisory for Hull Creek "
              "following a sewer force main break. For the safety of people and pets, Portsmouth Health Department is "
              "advising Portsmouth residents to avoid recreational water activities in Hull Creek, such as swimming, wading, "
              "tubing, or kayaking, where full-body submersion is more likely to occur. The advisory area for Hull Creek "
              "extends throughout the Western Branch of the Elizabeth River.\n- Avoid contact with water in the advisory area.")
HULL_LIFT = ("August 17, 2026\nRecreational Water Advisory Lifted for Hull Creek Following Sewer Main Break\n"
             "PORTSMOUTH, Va.- Effective immediately, the Virginia Department of Health (VDH), is lifting the Hull Creek "
             "advisory in Portsmouth, VA.\nThe overflow was stopped, and repairs were successfully completed on Friday, "
             "August 7, following efforts by Hampton Roads Sanitation District (HRSD) personnel. Estimated total release "
             "of sewage was 3 million gallons.")
BAILEY_LIFT = ("July 23, 2026\nRecreational Water Advisory for Bailey Bay Lifted\nHOPEWELL, Va. – Effective immediately, "
               "VDH is lifting the recreational advisory for Bailey Bay in Hopewell.\nThe overflow was stopped and repairs "
               "were successfully completed on Tuesday, July 22, following several days of repair efforts.")


def test_vdh_issued_and_lifted_pair_into_one_advisory():
    rels = [
        _rel("Recreational Water Advisory Issued for Hull Creek following Sewer Main Break", "2026-08-05T17:16:15-04:00", HULL_ISSUE),
        _rel(" Recreational Water Advisory Lifted for Hull Creek Following Sewer Main Break ".strip(), "2026-08-17T15:33:15-04:00", HULL_LIFT),
        _rel("Recreational Water Advisory Issued for Bailey Bay, Hopewell", "2026-07-16T16:30:44-04:00",
             "July 16, 2026\nx\nHOPEWELL, Va. – VDH is advising residents to avoid recreational water activities in Bailey Bay "
             "after a sewage main break."),
        _rel("Recreational Water Advisory for Bailey Bay Lifted", "2026-07-23T11:15:51-04:00", BAILEY_LIFT),
        _rel("Recreational Water Advisory for Bailey Bay Lifted", "2026-07-23T15:30:56-04:00", BAILEY_LIFT,
             link="https://www.vdh.virginia.gov/news/x/bailey-2/"),
        _rel("Swimming Advisory Issued for Hilton Beach in Newport News", "2026-08-13T14:56:56-04:00",
             "August 13, 2026\nx\nThe signs read: “Warning swimmers – bacteria levels do not meet state water quality "
             "standards, swimming not advised until further notice.”"),
        _rel("Swimming Advisory Lifted at Hilton Beach", "2026-08-14T13:47:00-04:00", "August 14, 2026\nx\nLifted."),
        _rel("VDH Partially Lifts Potomac River Recreational Water Advisory", "2026-03-05T12:00:00-05:00", "March 5\nx\nPartly."),
        _rel("VDH Issues Recreational Water Advisory for the Potomac River", "2026-02-13T16:01:01-05:00",
             "February 13, 2026\nx\nVDH is advising Virginia residents to avoid recreational water activities in the Potomac "
             "River due to a sewage spill. The advisory area extends for 72.5 miles from the American Legion Memorial "
             "Bridge (I-495) in Fairfax County to the Governor Harry W. Nice Memorial Bridge (Route 301) in King George County."),
        _rel("VDH Lifts Potomac River Recreational Water Advisory", "2026-03-17T15:32:41-04:00", "March 17\nx\nLifted."),
        _rel("Virginia Health Officials Issue Fish Consumption Advisory for Chickahominy River", "2026-04-14T09:53:17-04:00", "x"),
    ]
    advs = V.pair(rels)
    recs = {r["raw"]["releases"][0]["title"]: r for r in (V.to_record(a, REFS, "2026-11-02T12:00:00Z") for a in advs)}
    assert len(advs) == 4                                          # fish consumption advisory skipped
    hull = recs["Recreational Water Advisory Issued for Hull Creek following Sewer Main Break"]
    assert hull["event_type"] == "sso" and hull["status"] == "advisory_lifted"
    assert hull["started_at"] == "2026-08-05T17:16:15-04:00" and hull["ended_at"] == "2026-08-17T15:33:15-04:00"
    assert hull["raw"]["valid_until"] == hull["ended_at"] and hull["published_at"] == hull["started_at"]
    assert "extends throughout the Western Branch" in hull["waterbody_text"]
    assert hull["water_slugs"] == ["western-branch-elizabeth-river-va"] or not W.WATERS_JSON.exists()
    assert hull["advice_text"].startswith("For the safety of people and pets") and "avoid" in hull["advice_text"]
    assert hull["volume_gal"] == 3_000_000 and hull["raw"]["notes"] is None      # Friday, August 7, 2026 is a Friday
    bailey = recs["Recreational Water Advisory Issued for Bailey Bay, Hopewell"]
    assert [x["role"] for x in bailey["raw"]["releases"]] == ["issued", "lifted", "repeat_lift"]
    assert bailey["ended_at"] == "2026-07-23T11:15:51-04:00"
    assert any("'Tuesday, July 22', but July 22, 2026 is a Wednesday" in n and "kept as published" in n
               for n in bailey["raw"]["notes"])
    beach = recs["Swimming Advisory Issued for Hilton Beach in Newport News"]
    assert beach["event_type"] == "beach_advisory" and beach["status"] == "advisory_lifted"
    assert "swimming not advised" in beach["advice_text"]
    potomac = recs["VDH Issues Recreational Water Advisory for the Potomac River"]
    assert [x["role"] for x in potomac["raw"]["releases"]] == ["issued", "partial_lift", "lifted"]
    assert potomac["ended_at"] == "2026-03-17T15:32:41-04:00" and potomac["waterbody_text"].startswith("Potomac River: ")


def test_vdh_weekday_note_does_not_correct_the_date():
    notes = V.weekday_notes("completed the afternoon of Friday April 14, after the advisory", "2026-04-14T11:44:08-04:00")
    assert notes == ["The release says 'Friday April 14', but April 14, 2026 is a Tuesday; the date is kept as "
                     "published (not corrected)."]
    assert V.weekday_notes("on Friday, August 7, following", "2026-08-17T15:33:15-04:00") == []


def test_vdh_feed_drops_contacts_and_quotes():
    xml = ("<rss><channel><item><title>Swimming Advisory Issued for Buckroe Beach South</title>"
           "<link>https://www.vdh.virginia.gov/news/a/b/</link><dc:creator><![CDATA[someuser]]></dc:creator>"
           "<pubDate>Wed, 22 Jul 2026 17:24:12 +0000</pubDate>"
           "<category><![CDATA[Buckroe Beach South]]></category><category><![CDATA[Jane Example]]></category>"
           "<category><![CDATA[Environmental Health Manager Jane Example]]></category>"
           "<content:encoded><![CDATA[<p>July 22, 2026</p><p>Media Contacts: Jo Doe, PIO, 757-555-0100<br>jo.doe@vdh.virginia.gov</p>"
           "<p>Jane Example, Environmental Health Manager, 757-555-0101</p>"
           "<p><strong>Swimming Advisory Issued for Buckroe Beach South</strong></p>"
           "<p>HAMPTON, Va.– The Hampton Health District has issued a swimming advisory for Buckroe Beach South.</p>"
           "<p>“We encourage the public to comply,” said Jane Example, Environmental Health Manager.</p>"
           "<p>Send all questions and interview requests to Jo Doe at jo.doe@vdh.virginia.gov.</p>]]></content:encoded>"
           "</item></channel></rss>")
    items = V.parse_feed(xml)
    s = json.dumps(items)
    for bad in ("Jo Doe", "Jane", "Example", "555-01", "someuser", "jo.doe"):
        assert bad not in s, bad
    assert items[0]["categories"] == ["Buckroe Beach South"]
    assert items[0]["published"] == "2026-07-22T13:24:12-04:00"
    assert "issued a swimming advisory for Buckroe Beach South" in items[0]["text"]


# ---------------------------------------------------------------- AlexRenew status changes

def _feat(oid, name, status, start, end):
    return {"attributes": {"OBJECTID": oid, "CSO_Name": name, "status": status,
                           "status_text": "Overflowing" if status else "Normal",
                           "timestamp_start": start, "timestamp_end": end},
            "geometry": {"x": -77.04, "y": 38.81}}


def test_alexrenew_state_changes_become_events():
    state = {}
    jan_s, jan_e = 1767276822000, 1767299173000          # 2026-01-01 14:13:42-20:26:13 UTC
    ph_s, ph_e = 1767247200000, 1767247260000            # 06:00:00-06:01:00 UTC on two outfalls: initial value
    snap1 = [_feat(2, "CSO 019 - Potomac River", 0, jan_s, jan_e), _feat(4, "CSO 021 - Hooffs Run", 0, ph_s, ph_e),
             _feat(5, "CSO 022 - Hooffs Run", 0, ph_s, ph_e)]
    A.poll(state, snap1, "2026-11-02T12:00:00Z")
    assert set(state["events"]) == {"019-20260101T1413", "021-20260101T0600", "022-20260101T0600"}
    first = A.to_record("019-20260101T1413", state["events"]["019-20260101T1413"])
    assert first["event_type"] == "cso" and first["status"] == "ended"
    assert first["started_at"] == "2026-01-01T09:13:42-05:00" and first["ended_at"] == "2026-01-01T15:26:13-05:00"
    assert first["raw"]["first_seen_already_in_layer"] is True
    ph = A.to_record("021-20260101T0600", state["events"]["021-20260101T0600"])
    assert ph["event_type"] == "unknown" and "initial value" in ph["parse_error"]
    # the outfall turns red: a new overflow, ongoing, with the layer's start
    new_s = 1793800000000
    A.poll(state, [_feat(2, "CSO 019 - Potomac River", 1, new_s, None)], "2026-11-04T12:00:00Z")
    key = [k for k in state["events"] if k.startswith("019-") and k != "019-20260101T1413"][0]
    rec = A.to_record(key, state["events"][key])
    assert rec["status"] == "ongoing" and rec["started_at"] == A.utc_ms(new_s).isoformat(timespec="seconds")
    assert rec["raw"]["first_seen_already_in_layer"] is False and rec["raw"]["seen_red"] is True
    assert rec["discharger_id"] == "va-alexrenew" and rec["npdes_permit"] == "VA0025160" and rec["outfall_id"] == "019"
    assert rec["advice_window_hours"] == 24
    # the layer reports the end, then turns green: same event, ended
    A.poll(state, [_feat(2, "CSO 019 - Potomac River", 1, new_s, new_s + 3_600_000)], "2026-11-04T13:00:00Z")
    A.poll(state, [_feat(2, "CSO 019 - Potomac River", 0, new_s, new_s + 3_600_000)], "2026-11-05T14:00:00Z")
    rec = A.to_record(key, state["events"][key])
    assert rec["status"] == "ended" and rec["ended_at"] == A.utc_ms(new_s + 3_600_000).isoformat(timespec="seconds")
    assert [x["status"] for x in rec["raw"]["status_log"]] == [1, 1, 0]
    assert len([k for k in state["events"] if k.startswith("019-")]) == 2


# ---------------------------------------------------------------- Richmond workbook rows

def test_richmond_spreadsheet_row():
    parsed = {"title": "Jul2026 Overflow Summary; 287.0 MG Overflow Observed", "notes": [],
              "summary": {"CSO_06": {"Sensor Type": "Flow", "Number of Observed Activations": "3",
                                     "Observed Overflow Volume, MG": "226"},
                          "CSO_14": {"Sensor Type": "Level"}},
              "events": {"CSO_06": [{"label": "2026Jul19", "start": "46222.77777777778", "end": "46231.93402777778",
                                     "Rainfall, in": "5.05", "Observed Overflow Volume, mg": "226",
                                     "overflow_duration_hours": "41"}],
                         "CSO_14": [{"label": "2026Jul06", "start": "46209.86111111111", "end": "46209.86805555555",
                                     "Rainfall, in": "2.35", "Observed Overflow Volume, mg": "0.08",
                                     "overflow_duration_hours": "0.25"}]}}
    recs = {r["outfall_id"]: r for r in R.to_records("2026-07", parsed, "https://rva.gov/x.xlsx", "2026-11-02T12:00:00Z")}
    r = recs["006"]
    assert r["event_id"] == "va-richmond-cso:CSO_06-20260719T1840" and r["event_type"] == "cso" and r["status"] == "ended"
    assert r["started_at"] == "2026-07-19T18:40:00-04:00" and r["ended_at"] == "2026-07-28T22:25:00-04:00"
    assert r["volume_gal"] == 226_000_000 and r["volume_text"] == "226 MG (observed overflow volume)"
    assert r["estimate_flag"] == "measured" and recs["014"]["estimate_flag"] == "estimated"
    assert r["raw"]["overflow_duration_hours"] == 41.0 and r["raw"]["rain_in"] == 5.05
    assert r["discharger_id"] == "va-richmond-dpu" and r["npdes_permit"] == "VA0063177"
    if r["raw"]["echo_outfall"]:
        assert r["waterbody_text"] == "James River" and r["water_slugs"] == ["james-river-va"]
        assert r["water_match"] == "outfall_registry" and r["lat"] == 37.531


def test_richmond_workbook_parse():
    p = RAW / "richmond" / "monthly" / "jul2026.xlsx"
    if not p.exists():
        pytest.skip("research copy missing")
    parsed = R.parse_workbook(p.read_bytes())
    assert parsed["title"].endswith("287.0 MG Overflow Observed")
    assert parsed["summary"]["CSO_06"]["Observed Overflow Volume, MG"] == "226"
    assert [e["label"] for e in parsed["events"]["CSO_06"]] == ["2026Jul06", "2026Jul10", "2026Jul19"]
    total = sum(float(e["Observed Overflow Volume, mg"]) for rows in parsed["events"].values() for e in rows)
    assert abs(total - 287.0) < 1.0


def test_richmond_month_links():
    html = ('<a href="https://rva.gov/media/53271">July 2026</a> <a href="/sites/default/files/2025-12/x.xlsx">November 2025</a>'
            '<a href="https://rva.gov/media/50886">Click here</a>')
    links = R.month_links(html)
    assert links == {"2026-07": "https://rva.gov/media/53271",
                     "2025-11": "https://www.rva.gov/sites/default/files/2025-12/x.xlsx"}
    assert R.xlsx_link('<a href="/sites/default/files/2026-08/47_CSO%20%281%29.xlsx">x</a>', "https://rva.gov/media/1") \
        == "https://rva.gov/sites/default/files/2026-08/47_CSO%20%281%29.xlsx"


def test_prep_backs_off_on_403_and_reports_the_block():
    class Resp:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class Sess:
        def __init__(self, codes):
            self.codes = list(codes)

        def get(self, url, params=None, timeout=None):
            return Resp(self.codes.pop(0))

    waits, meta = [], {}
    with pytest.raises(P.Blocked):
        P._get(Sess([403, 403, 403]), P.API, {}, meta, sleep=waits.append)
    assert waits == [20, 60] and len(meta["http_403"]) == 3
    waits, meta = [], {}
    assert P._get(Sess([403, 200]), P.API, {}, meta, sleep=waits.append).status_code == 200
    assert waits == [20] and len(meta["http_403"]) == 1


# owner, 2026-11-04 ("yes strip names"): the other party of an e-mail, call, letter or report named in DEQ's free text
# (the shape found in a water-target note: "email from Last, First <address> indicated ...")
@pytest.mark.parametrize("text, gone, kept", [
    ("05/27/2025 email from Doe, Jane <jdoe@example.org> indicated that the sewage spilled was to the ground only.",
     ["Doe", "Jane", "jdoe", "example.org"], ["05/27/2025 email from [name removed] indicated"]),
    ("Phone call from John Q. Public (operator) reported the overflow stopped.", ["John", "Public"], ["Phone call from [name removed] (operator)"]),
    ("Letter from Jane Doe (jdoe@town.gov) attached.", ["Jane", "Doe", "jdoe"], ["Letter from [name removed] attached"]),
    ("Email from HRSD indicated the spill reached a ditch.", [], ["Email from HRSD indicated"]),
    ("Report from City of Richmond staff; call from Richmond, Virginia dispatch.", [], ["City of Richmond staff", "Richmond, Virginia dispatch"]),
    ("Discussion with Roto Rooter Services about the lateral.", [], ["Roto Rooter Services"]),
    ("Contact Jane Doe <jane.doe@example.org> for the closure report.", ["Jane", "Doe", "jane.doe"], ["Contact [name removed] for the closure report"]),
])
def test_scrub_free_removes_the_other_party_of_a_call_or_email(text, gone, kept):
    out = P.scrub_free(text)
    for g in gone:
        assert g not in out, out
    for k in kept:
        assert k in out, out
    assert "@" not in out
