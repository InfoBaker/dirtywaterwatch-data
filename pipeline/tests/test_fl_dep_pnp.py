"""Florida DEP Public Notice of Pollution: which notices become sewage records, times, revisions, water flags and,
above all, that no contact field or personal name in the notice text reaches a record or the saved raw page
(no network; a synthetic fixture whose personal values are placeholders)."""
import json
from pathlib import Path

import common
from ingest import fl_dep_pnp as P

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fl_dep_pnp_layer.json"
PERSONAL = ["Jane Doe", "JANE DOE", "John Roe", "jane.doe@example.org", "john.roe@example.org", "jsample@example.org",
            "8505550100", "8505550101", "555-0100", "555-0123", "555-0199", "Andrew Sample", "Jordan Sample",
            "Concerned citizen", "Lead Operator", "Ask for"]


def features():
    return [f["attributes"] for f in json.loads(FIXTURE.read_text())["features"]]


def built():
    recs, stats = P.build(features(), "2026-11-04T00:00:00Z", [], permits={"FL0031771": ("fl-test", "Test")})
    return {r["raw"]["INCIDENT_NUMBER"] and r["source_record_id"] or r["source_record_id"]: r for r in recs}, stats


def test_only_sewage_notices_become_records():
    recs, stats = built()
    assert stats["excluded"] == {"other_pollution": 1, "reuse": 1}
    kinds = sorted(r["raw"]["_pnp_kind"] for r in recs.values())
    assert kinds == ["citizen_complaint", "partially_treated", "untreated", "untreated", "untreated"]
    by_kind = {r["raw"]["_pnp_kind"]: r for r in recs.values()}
    assert by_kind["partially_treated"]["event_type"] == "plant_bypass"
    c = by_kind["citizen_complaint"]
    assert (c["event_type"], c["status"]) == ("unknown", "unknown")


def test_ids_times_and_status():
    recs, _ = built()
    r = recs["202611076-20261101T155824"]
    assert r["reported_at"] == "2026-11-01T15:58:24-05:00"       # wall clock stored as UTC, read as Florida time (EST from 1 Nov)
    assert r["started_at"] == "2026-11-01T00:00:00-04:00" and r["time_precision"] == "day"
    assert r["ended_at"] == "2026-11-02T00:00:00-05:00" and r["status"] == "ended"
    assert r["published_at"] is None
    later = recs["202611076-20261102T091000"]
    assert later["status"] == "ongoing" and later["ended_at"] is None
    assert later["parent_event_id"] == r["event_id"] and r["parent_event_id"] is None
    plant = [x for x in recs.values() if x["raw"]["_pnp_kind"] == "partially_treated"][0]
    assert plant["status"] == "ended" and plant["ended_at"] is None      # not ongoing, no end given: none invented


def test_volume_water_flag_and_names():
    recs, _ = built()
    r = recs["202611076-20261101T155824"]
    assert r["volume_gal"] == 2500 and r["raw"]["reached_water"] is True
    assert r["waterbody_text"] == "Watson Bayou"
    plant = [x for x in recs.values() if x["raw"]["_pnp_kind"] == "partially_treated"][0]
    assert plant["raw"]["reached_water"] is False and plant["volume_gal"] == 45000
    form = recs["none-20261026T122900"]
    assert form["volume_gal"] == 1500 and form["npdes_permit"] == "FL0031771" and form["discharger_id"] == "fl-test"
    assert form["waterbody_text"] is None                               # a retention pond is not a receiving water
    assert recs["202611076-20261101T155824"]["discharger_id"] == "fl-panama-city-millville"


def test_point_outside_florida_is_dropped():
    recs, _ = built()
    c = [x for x in recs.values() if x["raw"]["_pnp_kind"] == "citizen_complaint"][0]
    assert c["lat"] is None and c["raw"]["_coords_rejected"]["why"] == "not in Florida"


def test_no_contact_field_or_name_reaches_a_record():
    recs, _ = built()
    text = json.dumps(list(recs.values()))
    for p in PERSONAL:
        assert p not in text, p
    for r in recs.values():
        raw = r["raw"]
        assert not any(k.startswith(("REPORTER", "CONTACT")) for k in raw), raw.keys()
        assert "FACILITY_DIRECTIONS" not in raw
    assert {r["raw"]["_filer"] for r in recs.values()} <= {"operator", "owner", "citizen", "other"}
    kept = recs["none-20261026T122900"]["raw"]["INCIDENT_REPORT"]
    assert "Represents" in kept and "Example Utilities" in kept and "1,500 gallons" in kept     # the report survives


def test_scrub_keeps_ordinary_text():
    t = ("Crews were notified of a manhole overflow on Dale Mabry Hwy near Wesley Chapel. The City of Orlando "
         "Conserv I Water Reclamation Facility was called.")
    assert P.scrub(t) == t


def test_main_requests_safe_fields_and_saves_scrubbed_raw(tmp_path, monkeypatch):
    calls = []

    class Resp:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self.d

    class Sess:
        headers = {}

        def get(self, url, params=None, timeout=None):
            calls.append(params)
            return Resp(json.loads(FIXTURE.read_text()))

    monkeypatch.setattr(P.requests, "Session", Sess)
    ev, raw, build = tmp_path / "events", tmp_path / "raw", tmp_path / "build"
    for d in (ev, raw, build):
        d.mkdir()
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(common, "RAW_DIR", raw)
    monkeypatch.setattr(P, "EVENTS_DIR", ev)
    monkeypatch.setattr(P, "STATE_FILE", build / "state.json")
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "load_permit_index", lambda data_dir=None: {})
    assert P.main([]) == 0
    fields = set(calls[0]["outFields"].split(","))
    assert fields == set(P.SAFE_FIELDS) | {P.RELATIONSHIP_FIELD}
    assert not any(f.startswith("CONTACT") or f in ("REPORTER_NAME", "REPORTER_EMAIL", "REPORTER_PHONE", "REPORTER_TITLE")
                   for f in fields)
    saved = "".join(p.read_text() for p in raw.rglob("*.json"))
    out = (ev / f"{P.SOURCE_ID}.json").read_text()
    for p in PERSONAL:
        assert p not in saved, p
        assert p not in out, p
    assert json.loads(out)["count"] == 5


# ---------------------------------------------------------------- review 2026-11-04

def _row(i, **kw):
    a = dict(features()[i])
    a.update(kw)
    return a


def test_name_in_incident_or_facility_name_never_reaches_a_record():
    # filers type their own name as the incident name, and a complaint's facility is often a resident's name and home
    staff = _row(0, INCIDENT_NAME="Jordan Sample", INCIDENT_NUMBER=202611200, OBJECTID=20)
    home = _row(5, FACILITY_NAME="jordan sample", INCIDENT_NAME="Mr. Sample residence", INCIDENT_NUMBER=202611201,
                FACILITY_ADDRESS_LINE_1="12 Placeholder Ln", OBJECTID=21)
    recs, _ = P.build([staff, home], "2026-11-04T00:00:00Z", [], permits={})
    text = json.dumps(recs).lower()
    assert "jordan" not in text and "sample residence" not in text and "12 placeholder ln" not in text
    by = {r["raw"]["_pnp_kind"]: r for r in recs}
    assert by["untreated"]["outfall_name"] == "[name removed]"
    assert by["citizen_complaint"]["discharger_name"] == "[name removed]"
    assert by["citizen_complaint"]["raw"]["FACILITY_ADDRESS_LINE_1"] == "[address removed]"
    # public facilities named after people, and places, stay
    for v in ("William Example WRF", "Patrick Air Force Base", "Lift Station 12", "City of Tampa", "Lake Mary Jane",
              "COWP Hurricane Ian #7", "Mary Esther Waste Water Plant"):
        assert P.scrub_name_field(v) == v, v


def test_storm_sewer_fuel_and_generator_diesel_are_not_sewage():
    for t in ("Approximately 20 gallons of diesel fuel entered a storm sewer inlet.",
              "Hydraulic oil leaked from a garbage truck into the storm sewer.",
              "Diesel fuel leaked from the generator at Lift Station 5. 30 gallons. No water impacted."):
        assert P.classify(t, None, None)[1] is None, t
    for t in ("Generator ran out of diesel fuel and Lift Station 5 overflowed.",
              "Sewage entered the storm sewer system.",
              "Sewer issue caused by a gravity main blockage; chlorine was placed down for disinfection."):
        assert P.classify(t, None, None)[1] == "sso", t


def test_sewer_shorthand_and_a_contradicted_template_are_sewage():
    for t in ("There was a spill located at LS #104. 800 gallons went into a storm drain.",
              "FM was hit by Contractor - 2,000 Gals went into Storm",
              "The spill caused by an ARV (Air relief Valve) that broke. Approx. 8,000 gallons spilled"):
        assert P.classify(t, None, None)[1] == "sso", t
    t = ("Incident Description: A citizen reported an overflowing manhole; a bypass failure released untreated wastewater. "
         "Wastewater Type: Treated Cause: Bypass Spill Volume: 2,400 Volume Recovered: 0 Waterbodies Impacted: Y")
    kind, et, rule = P.classify(t, None, None)
    assert (kind, et) == ("untreated", "bypass") and "description reports untreated" in rule
    t = ("Incident Description: Effluent force main leaking. Wastewater Type: Treated Cause: Break Spill Volume: 10 "
         "Volume Recovered: 0")
    assert P.classify(t, None, None)[0] == "treated"


def test_a_complaint_is_never_linked_to_an_operator_notice_and_never_colours():
    from datetime import UTC, datetime

    from build import status as S
    op = _row(0, INCIDENT_NUMBER=202611300, OBJECTID=30)
    comp = _row(5, INCIDENT_NUMBER=202611300, OBJECTID=31, LATITUDE=27.9, LONGITUDE=-82.4,
                DATE_TIME_OF_REPORT=op["DATE_TIME_OF_REPORT"] + 3600_000)
    recs, stats = P.build([op, comp], "2026-11-04T00:00:00Z", [], permits={})
    c = [r for r in recs if r["raw"]["_pnp_kind"] == "citizen_complaint"][0]
    o = [r for r in recs if r is not c][0]
    assert c["parent_event_id"] is None and o["parent_event_id"] is None and stats["revisions"] == 0
    superseded, _ = S.resolve_revisions(recs, {r["event_id"]: r for r in recs})
    assert o["event_id"] not in superseded
    for now in (datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 20, tzinfo=UTC)):
        assert S.event_intervals(c, "FL", now) == []


def test_city_is_not_a_water_name():
    assert P.water_names("flowed into the City of Example River storm drains and into Watson Bayou") == ["Watson Bayou"]


def test_missing_flag_only_inside_the_layer_window():
    recs, _ = P.build(features(), "2026-11-04T00:00:00Z", [], permits={})
    old = {**recs[0], "event_id": "fl-dep-pnp:old-1", "source_record_id": "old-1", "reported_at": "2025-01-01T08:00:00-05:00",
           "raw": {"_pnp_kind": "untreated"}}
    recent = {**recs[0], "event_id": "fl-dep-pnp:new-1", "source_record_id": "new-1", "reported_at": "2026-11-01T08:00:00-05:00",
              "raw": {"_pnp_kind": "untreated"}}
    out, _ = P.build(features(), "2026-11-04T00:00:00Z", [old, recent], permits={})
    by = {r["event_id"]: r for r in out}
    assert "_missing_from_layer_since" not in by["fl-dep-pnp:old-1"]["raw"]
    assert by["fl-dep-pnp:new-1"]["raw"]["_missing_from_layer_since"] == "2026-11-04T00:00:00Z"


def _fake_session(monkeypatch, tmp_path, payload):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class Sess:
        headers = {}

        def get(self, url, params=None, timeout=None):
            return Resp()

    monkeypatch.setattr(P.requests, "Session", Sess)
    ev, raw, build = tmp_path / "events", tmp_path / "raw", tmp_path / "build"
    for d in (ev, raw, build):
        d.mkdir(exist_ok=True)
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(common, "RAW_DIR", raw)
    monkeypatch.setattr(P, "EVENTS_DIR", ev)
    monkeypatch.setattr(P, "STATE_FILE", build / "state.json")
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "load_permit_index", lambda data_dir=None: {})
    return ev


def test_left_out_counts_are_public_cumulative_and_not_doubled(tmp_path, monkeypatch):
    from export.build import PUBLIC_FEED_META
    ev = _fake_session(monkeypatch, tmp_path, json.loads(FIXTURE.read_text()))
    assert P.main([]) == 0 and P.main([]) == 0
    meta = json.loads((ev / f"{P.SOURCE_ID}.json").read_text())["meta"]
    assert meta["left_out"] == {"other pollution (fuel, oil, chemicals, stormwater and the like)": 1,
                                "reclaimed water (reuse)": 1}
    assert meta["listed_without_status"] == {"filed by a member of the public": 1}
    assert {"left_out", "listed_without_status", "left_out_note"} <= PUBLIC_FEED_META


def test_an_empty_layer_is_an_outage_not_an_empty_feed(tmp_path, monkeypatch):
    ev = _fake_session(monkeypatch, tmp_path, json.loads(FIXTURE.read_text()))
    assert P.main([]) == 0
    _fake_session(monkeypatch, tmp_path, {"features": []})
    assert P.main([]) == 1
    d = json.loads((ev / f"{P.SOURCE_ID}.json").read_text())
    assert d["ok"] is False and d["count"] == 5
