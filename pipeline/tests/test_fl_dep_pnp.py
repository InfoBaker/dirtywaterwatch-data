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
