"""Tennessee: TDEC's Events Report (the generic CSV reader with the APEX session step, ingest/tn_transforms.py) and TDEC's
HAB advisory layer (the generic ArcGIS reader): the county and point zones (49 CFR 71.5(d)), day-precision starts and
ends, the duration bound, TDEC's event types kept as sewage reports, placement on no water, the key, and the privacy
rules (safe fields only, house numbers, phones, emails and person-only names never reach a record or data/raw)."""
import json
from pathlib import Path

import pytest

import zones
from ingest.generic import csv_json
from ingest.generic import runner as R
from ingest import tn_transforms as T

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-07T13:00:00Z"
PERSONAL = ["Fixturename", "Jane", "1234 Example", "4321", "555-0142", "jfixture", "example.com", "Contact Email",
            "99900", "first_name", "phone_number", "e_mail", "McArthur"]


def tdec(prev=()):
    _, block = R.load_source("tn-tdec-events-report")
    rows = csv_json.parse(block, (FIX / "tn_tdec_events.csv").read_bytes())
    recs, stats = R.build("tn-tdec-events-report", block, rows, FETCHED, prev, None)
    return recs, stats


def by_type(recs, label):
    return [r for r in recs if r["raw"].get("_source_type") == label]


def hab():
    _, block = R.load_source("tn-tdec-hab-advisory-status")
    rows = R.platform("arcgis").parse(block, (FIX / "tn_tdec_hab.json").read_bytes())
    recs, stats = R.build("tn-tdec-hab-advisory-status", block, rows, FETCHED, (), None)
    return {r["source_record_id"]: r for r in recs}, stats


def test_blocks_validate():
    for sid in ("tn-tdec-events-report", "tn-tdec-hab-advisory-status"):
        _, block = R.load_source(sid)
        assert R.validate_block(block, sid) == []


def test_the_session_step_fills_the_csv_url(monkeypatch):
    _, block = R.load_source("tn-tdec-events-report")
    seen = []

    class Resp:
        def __init__(self, url, content=b""):
            self.url, self.content = url, content

    def fake_get(sess, url, params=None, timeout=None):
        seen.append(url)
        if "CSV" in url:
            return Resp(url, (FIX / "tn_tdec_events.csv").read_bytes())
        return Resp("https://dataviewers.tdec.tn.gov/dataviewers/f?p=2005:34140:1234567890123:::::")
    monkeypatch.setattr(csv_json, "get", fake_get)
    got = csv_json.fetch(block, None)
    assert seen[1] == "https://dataviewers.tdec.tn.gov/dataviewers/f?p=2005:34140:1234567890123:CSV::::"
    assert got.ext == "csv"
    # a session page whose URL holds no session id fails the fetch (a changed handshake, or a block page)
    monkeypatch.setattr(csv_json, "get", lambda s, u, p=None, timeout=None: Resp("https://example.org/blocked"))
    with pytest.raises(RuntimeError, match="no session id"):
        csv_json.fetch(block, None)
    # the setting is checked
    bad = dict(block, session={"url": "x", "pattern": "no group"})
    assert any("session" in e for e in R.validate_block(bad, "x"))


def test_every_row_is_a_record_with_tdecs_type_and_dates_only():
    recs, stats = tdec()
    assert stats["rows"] == 8 and len(recs) == 8
    r = by_type(recs, "Release [Sewer], Dry Weather")[0]
    assert r["event_type"] == "sso" and r["status"] == "ended" and r["time_precision"] == "day"
    # TDEC's end day 28 October, but 5 hours from a start known only to the day can run into 29 October: the later
    assert r["started_at"] == "2026-10-28T00:00:00-05:00" and r["ended_at"] == "2026-10-29T00:00:00-05:00"
    assert r["raw"]["_end_as_given"] == "2026-10-28T00:00:00-05:00"
    assert r["raw"]["ended_at_precision"] == "day" and r["volume_gal"] == 15000
    assert r["reported_at"] is None and r["published_at"] is None and r["source_updated_at"] is None
    assert r["npdes_permit"] == "TN0020648" and r["discharger_name"] == "Metro Water Services"
    assert by_type(recs, "Bypass")[0]["event_type"] == "plant_bypass"
    for label in ("Upset", "Washout"):
        assert by_type(recs, label)[0]["event_type"] == "plant_bypass"
    assert by_type(recs, "Unpermitted Discharge")[0]["event_type"] == "sso"
    assert T.tdec_kind("SSO, Wet Weather") == "sso" and T.tdec_kind("Release [Sewer], Wet Weather") == "sso"
    assert T.tdec_kind("Extreme Event Report") == "sso"
    # a release reached no water by TDEC's definition (0400-40-05-.02(75)); an overflow is not so marked
    assert r["raw"]["reached_water"] is False and "does not reach waters" in r["raw"]["_no_water_reason"]
    assert "reached_water" not in by_type(recs, "SSO, Wet Weather")[0]["raw"]
    assert by_type(recs, "SSO, Wet Weather")[0]["raw"]["_weather"].startswith("wet weather")


def test_no_end_is_end_not_confirmed_and_a_duration_bounds_the_end_day():
    recs, _ = tdec()
    wet = [r for r in by_type(recs, "SSO, Wet Weather") if not r["duplicate_of"]][0]
    assert wet["ended_at"] is None and wet["status"] == "unknown" and "ended_at_precision" not in wet["raw"]
    by = by_type(recs, "Bypass")[0]              # 2 March, 30 hours: the latest end falls on 4 March
    assert by["ended_at"] == "2026-03-04T00:00:00-05:00" and by["status"] == "ended"
    assert "Duration[hours] 30" in by["raw"]["_basis"]["ended_at"] and by["raw"]["ended_at_precision"] == "day"
    nostart = by_type(recs, "Unpermitted Discharge")[0]
    assert nostart["started_at"] is None and nostart["ended_at"] is None and nostart["status"] == "unknown"


def test_the_zone_follows_the_county():
    recs, _ = tdec()
    knox = by_type(recs, "SSO, Wet Weather")[0]
    assert knox["raw"]["time_zone"] == "America/New_York" and knox["started_at"].endswith("-04:00")
    assert knox["raw"]["timezone_note"].startswith("Eastern time (Knox County")
    assert by_type(recs, "Bypass")[0]["raw"]["time_zone"] == "America/New_York"          # Hamilton: Chattanooga
    assert by_type(recs, "Washout")[0]["raw"]["county"] == "DeKalb County"
    assert by_type(recs, "Washout")[0]["raw"]["time_zone"] == "America/Chicago"
    assert zones.tennessee_zone("McMinn County") == zones.EASTERN == zones.tennessee_zone("SULLIVAN")
    assert zones.tennessee_zone("Marion") == zones.CENTRAL == zones.tennessee_zone("Cumberland County")
    assert zones.tennessee_zone() == zones.CENTRAL
    assert len(zones.TN_EASTERN_COUNTIES) == 30
    # by point: Knoxville and Johnson City Eastern, Nashville, Memphis and Crossville Central
    assert zones.zone_for("TN", 35.96, -83.92) == zones.zone_for("TN", 36.31, -82.35) == zones.EASTERN
    for lat, lon in ((36.16, -86.78), (35.15, -90.05), (35.95, -85.03)):
        assert zones.zone_for("TN", lat, lon) == zones.CENTRAL
    # the other states keep their zones
    assert zones.zone_for("KY") == zones.EASTERN and zones.zone_for("TX") == zones.CENTRAL


def test_placement_is_no_water_and_never_the_plant():
    recs, _ = tdec()
    for r in recs:
        assert r["water_slugs"] == [] and r["waterbody_text"] is None and r["lat"] is None
        assert r["raw"]["_placement"] == "named_water_only" and r["raw"]["state"] == "TN"
    r = by_type(recs, "Release [Sewer], Dry Weather")[0]
    assert r["outfall_name"] == "[house number removed] Example Dr, Nashville" and r["raw"]["city"] == "Nashville"
    assert by_type(recs, "Bypass")[0]["outfall_name"] == "Example Water Authority Treatment Plant"


def test_the_key_is_stable_and_repeats_are_suffixed():
    recs, _ = tdec()
    ids = [r["source_record_id"] for r in recs]
    assert len(set(ids)) == len(ids)
    dup = [r for r in recs if r["duplicate_of"]]
    assert len(dup) == 1 and dup[0]["source_record_id"].endswith("~2") and dup[0]["volume_gal"] == 400
    first = [r for r in by_type(recs, "SSO, Wet Weather") if not r["duplicate_of"]][0]
    assert first["source_record_id"].startswith("tn0099901-20260915-sso-wet-weather-")
    again, _ = tdec(prev=recs)
    assert sorted(r["source_record_id"] for r in again) == sorted(ids)
    st = by_type(recs, "Washout")[0]
    assert st["npdes_permit"] is None and st["raw"]["state_permit"] == "SOP-99001"


def test_no_personal_field_or_string_reaches_the_records():
    recs, _ = tdec()
    text = json.dumps(recs)
    for s in PERSONAL:
        assert s not in text, s
    for r in recs:
        assert "contact_email" not in r["raw"]["row"]
    p = by_type(recs, "SSO, Dry Weather")[0]          # a small system filed under its owner's name
    assert p["discharger_name"] == "[name removed]" and p["raw"]["row"]["permittee_name"] == "[name removed]"
    assert p["raw"]["row"]["project_name"] == "[name removed]" and p["npdes_permit"] == "TN0099903"
    w = by_type(recs, "Washout")[0]
    assert "[phone removed]" in w["outfall_name"] and "[house number removed]" in w["outfall_name"]


def test_raw_storage_keeps_only_safe_scrubbed_rows():
    _, block = R.load_source("tn-tdec-events-report")
    rows = csv_json.parse(block, (FIX / "tn_tdec_events.csv").read_bytes())
    doc = json.loads(R.safe_payload(rows, block, None))
    assert len(doc["rows"]) == 8 and all(set(r) <= set(block["safe_fields"]) for r in doc["rows"])
    blob = json.dumps(doc)
    for s in PERSONAL:
        assert s not in blob, s


def test_hab_advisories_reports_and_left_out_rows():
    recs, stats = hab()
    assert stats["rows"] == 8 and set(recs) == {"901", "902", "903", "904", "905", "906"}   # no bloom, green algae out
    a = recs["901"]
    assert a["event_type"] == "hab_advisory" and a["status"] == "advisory_lifted"
    assert a["advice_text"] == "TDEC harmful algal bloom No Contact Advisory."
    assert a["started_at"] == "2023-03-27T00:00:00-04:00" and a["ended_at"] == "2023-04-18T00:00:00-04:00"
    assert a["raw"]["ended_at_precision"] == "day" and a["raw"]["time_zone"] == "America/New_York"   # Knox County
    assert "71.5(d)" in a["raw"]["timezone_note"] and "Knox County" in a["raw"]["timezone_note"]
    assert recs["902"]["raw"]["time_zone"] == "America/Chicago"
    assert recs["902"]["advice_text"].endswith("Precautionary Advisory.")
    c = recs["904"]                                   # confirmed, no advisory: a report, never TDEC's advisory
    assert c["status"] == "unknown" and c["advice_text"] is None and "no advisory" in c["raw"]["_agency_label_only"]
    assert c["raw"]["time_zone"] == "America/New_York" and c["raw"]["county"] == "Union County"


def _intervals(ev, now="2026-11-08T12:00:00+00:00"):
    from datetime import datetime
    from build import status as S
    rules = json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())
    return S._event_intervals(ev, "TN", datetime.fromisoformat(now), None, rules)


def test_bloom_reports_without_an_advisory_carry_the_sites_caution_never_tdecs_red():
    """Review 2026-11-08 P1-1: objects 59, 72 and 74 (confirmed, no advisory, with an end) were drawn red as TDEC's
    advisory; six reports TDEC had not assessed had no date at all."""
    recs, _ = hab()
    for r in recs.values():
        ivs = _intervals(r)
        if r["raw"].get("_agency_label_only"):
            assert ivs and all(iv["rule"] == "sample_caution" for iv in ivs), r["source_record_id"]
            assert not any(iv["rule"] == "advisory_active" for iv in ivs)
    # like object 72: confirmed 11 June, TDEC's end 23 July: the caution runs to the end of 23 July, not 72 hours
    ivs = _intervals(recs["903"])
    assert ivs[-1]["end"].isoformat() >= "2026-07-24T00:00" and ivs[0]["start"].isoformat().startswith("2026-06-11")
    # a report TDEC has not assessed: no status date, so the reporter's observation day, said in the record
    u = recs["905"]
    assert u["started_at"] == "2026-06-11T00:00:00-05:00" and u["time_precision"] == "day"
    assert "observed" in u["raw"]["_basis"]["started_at"] or "saw the bloom" in u["raw"]["_basis"]["started_at"]
    assert [iv["rule"] for iv in _intervals(u)] == ["sample_caution"]
    # TDEC's own advisory stays red (the authority's window)
    assert any(iv["rule"] == "advisory_active" for iv in _intervals(recs["901"]))


def test_hab_points_are_rounded_everywhere_and_withheld_at_a_private_residence():
    """Review 2026-11-08 P2-3: raw.row kept the reporter's exact point; a private residence keeps only its county."""
    import re as _re
    recs, _ = hab()
    blob = json.dumps(list(recs.values()))
    assert not _re.search(r"-?\d+\.\d{4,}", blob.replace('"coord_precision_m"', "")), "a point with 4+ decimals"
    p = recs["905"]
    assert p["lat"] is None and p["lon"] is None and "_x" not in p["raw"]["row"] and "_y" not in p["raw"]["row"]
    assert p["raw"]["county"] == "Davidson County" and "private residence" in p["raw"]["_point_withheld"]
    _, block = R.load_source("tn-tdec-hab-advisory-status")
    rows = R.platform("arcgis").parse(block, (FIX / "tn_tdec_hab.json").read_bytes())
    saved = R.safe_payload(rows, block, None).decode()
    assert not _re.search(r"\d+\.\d{4,}", saved)


def test_hab_layer_personal_fields_never_read():
    recs, _ = hab()
    text = json.dumps(list(recs.values()))
    for s in PERSONAL:
        assert s not in text, s
    assert "[house number removed]" in recs["905"]["waterbody_text"]
    _, block = R.load_source("tn-tdec-hab-advisory-status")
    assert not {"first_name", "last_name", "phone_number", "e_mail_address", "comments"} & set(block["safe_fields"])


def test_every_tdec_type_carries_a_colour_and_no_end_is_the_day_start_caution():
    """Review 2026-11-08 P2-1 (upset, washout, extreme event and unpermitted discharge never coloured) and P2-2 (the
    state text's 72 hours from the start of the day, which the code did not apply)."""
    recs, _ = tdec()
    for r in recs:
        if r["started_at"]:
            assert _intervals(r), r["raw"]["_source_type"]
    for label in ("Extreme Event Report", "Upset", "Washout", "Unpermitted Discharge", "Bypass", "SSO, Dry Weather",
                  "Release [Sewer], Wet Weather"):
        assert T.tdec_kind(label) in ("sso", "plant_bypass")
    knox = [r for r in by_type(recs, "SSO, Wet Weather") if not r["duplicate_of"]][0]
    ivs = _intervals(knox)
    assert ivs[0]["rule"] == "day_start_caution" and ivs[0]["start"].isoformat() == "2026-09-15T04:00:00+00:00"   # local midnight, Eastern


def test_the_shared_changes_leave_other_blocks_as_they_were():
    """operator_fields and the csv session step are opt-in: a block without them reads and saves rows as before."""
    from ingest.generic import fieldmap as F
    block = {"safe_fields": ["permittee", "notes"], "free_text": ["notes"]}
    row = {"permittee": "Jane Fixturename", "notes": "plain"}
    assert F.safe_row(row, block)[0] == row
    assert F.safe_row(row, dict(block, operator_fields=["permittee"]))[0]["permittee"] == "[name removed]"
    assert csv_json.session_url({"url": "https://example.org/x.csv"}, None) == "https://example.org/x.csv"
    for sid in ("tx-tceq-sso-opendata", "md-mde-overflows"):
        _, b = R.load_source(sid)
        assert "operator_fields" not in b and "session" not in b and R.validate_block(b, sid) == []


# ---------------------------------------------------------------- TDEC's posted streams (review 2026-11-08 P1-2)

def posted(prev=(), at="2026-11-07T13:00:00Z"):
    from ingest import tn_tdec_posted_streams as PS
    items = json.loads((FIX / "tn_tdec_posted_streams_items.json").read_text())
    return PS.run(items, list(prev), at)


def test_the_posted_streams_list_reads_25_segments_with_counties_and_causes():
    from ingest import tn_tdec_posted_streams as PS
    items = json.loads((FIX / "tn_tdec_posted_streams_items.json").read_text())
    segs = PS.segments(PS.section_items(items))
    assert len(segs) == 25 and all(s["county"] for s in segs) and PS.revision(items) == "August 2026"
    by = {s["stream"]: s for s in segs}
    cum = by["Cumberland River"]
    assert cum["county"] == "Davidson" and "River mile 185.7" in cum["portion"] and "190.6" in cum["portion"]
    assert "collection system overflows" in cum["comments"]
    assert by["First Creek"]["portion"].startswith("From Neyland Drive to Topeka Street")
    assert by["Gibson Creek"]["portion"].endswith("to Neeley's Branch (River mile 0.0 to 0.2)")      # the shifted font
    assert by["East Fork Poplar Creek"]["county"] == "Roane, Anderson"
    recs, stats = posted()
    assert stats["segments"] == 25 and stats["sewer_cause"] == 21 and len(recs) == 25


def test_a_posting_is_tdecs_standing_advisory_with_no_invented_date():
    recs, _ = posted()
    r = next(x for x in recs if x["waterbody_text"] == "First Creek")
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_active" and r["ended_at"] is None
    assert r["time_precision"] == "poll" and r["started_at"] == "2026-11-07T13:00:00Z"
    assert r["published_at"] is None and r["reported_at"] is None and r["raw"]["list_revision"] == "August 2026"
    assert "first read" in r["raw"]["start_basis"] and r["raw"]["county"] == "Knox County"
    assert r["raw"]["_last_seen_in_source"] == "2026-11-07T13:00:00Z"
    assert "not suitable for recreational activities" in r["advice_text"]
    # a later read keeps the first read as the start
    again, _ = posted(prev=recs, at="2026-11-08T13:00:00Z")
    r2 = next(x for x in again if x["event_id"] == r["event_id"])
    assert r2["started_at"] == "2026-11-07T13:00:00Z" and r2["raw"]["_last_seen_in_source"] == "2026-11-08T13:00:00Z"
    ivs = _intervals(r2)
    assert ivs and ivs[0]["rule"] == "advisory_active"          # red: the authority's own window


def test_a_segment_that_leaves_the_list_ends_at_that_read():
    recs, _ = posted()
    gone = dict(recs[0], raw=dict(recs[0]["raw"]), event_id="tn-tdec-bacteriological-advisories:example-creek-knox",
                source_record_id="example-creek-knox")
    again, stats = posted(prev=recs + [gone], at="2026-11-09T13:00:00Z")
    g = next(x for x in again if x["event_id"] == gone["event_id"])
    assert g["raw"]["_unlisted_since"] == "2026-11-09T13:00:00Z" and stats["unlisted"] == 1
    ivs = _intervals(g, now="2026-11-20T00:00:00+00:00")
    assert ivs and ivs[-1]["end"].isoformat().startswith("2026-11-09T13:00")


def test_a_posting_is_a_marker_on_its_named_stream_never_the_whole_stream():
    from build import status as S
    recs, _ = posted()
    first = next(x for x in recs if x["waterbody_text"] == "First Creek")
    assert (first["lat"], first["lon"]) == (35.9604, -83.9127) and first["coord_source"] == "gnis"
    assert "stretch" not in first and S.names_its_water(first)
    assert S.advisory_on_river(first, {"kind": "river"})        # a stream with no stretch: a point there
    cum = next(x for x in recs if x["waterbody_text"] == "Cumberland River")
    assert cum["lat"] is None and "name and county only" in cum["raw"]["coords_basis"]
    assert next(x for x in recs if x["raw"]["stream_as_listed"].startswith("Cypress"))["waterbody_text"] == "Cypress Creek"
    assert "TN" in S.COUNTY_FIELD_STATES


def test_missing_waters_are_resolved_by_county():
    """Review 2026-11-08 P2-5 and P2-4: Beaver, Cypress and Richland creeks of the posted list are not the national
    list's streams of those names elsewhere; the Centennial Park lake is Lake Watauga, Davidson County."""
    doc = json.loads((Path(__file__).resolve().parents[2] / "research" / "tn" / "receiving-waters-missing.json").read_text())
    rows = {(r["name"], tuple(r.get("counties") or [])) for r in doc["rows"]}
    for name, county in (("Beaver Creek", "Sullivan County"), ("Cypress Creek", "Shelby County"),
                         ("Richland Creek", "Davidson County"), ("Lake Watauga (Centennial Park)", "Davidson County")):
        assert (name, (county,)) in rows, name
    assert not any(r["name"] == "Watauga Lake" for r in doc["rows"])
