"""Time zones and end precision in the status engine and the ingesters that feed it (SOL reviews of 2026-11-07: data
wave 1 P1-1 to P1-5, data wave 2 P1-1 and P1-2). Each test is the reviewer's failure scenario, asserted at the exact
local boundary. Placeholder names only; no network.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import zones  # noqa: E402
from build import status as S  # noqa: E402

RULES = S.load_rules()


def Z(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def colour(ev, state, at: str, rules=RULES) -> str | None:
    """The colour the event sets at the UTC instant `at` (None: no colour)."""
    t = Z(at)
    ivs = S.event_intervals(ev, state, t, rules=rules)
    hit = [iv for iv in ivs if iv["start"] <= t and (iv["end"] is None or t < iv["end"])
           and iv["color"] in ("red", "yellow")]
    if any(iv["color"] == "red" for iv in hit):
        return "red"
    return "yellow" if hit else None


def ev(**kw) -> dict:
    base = {"event_id": "x:1", "source_id": "x", "event_type": "sso", "status": "ended", "raw": {},
            "started_at": None, "ended_at": None, "time_precision": "minute", "fetched_at": "2026-11-01T00:00:00Z",
            "lat": None, "lon": None, "source_url": "https://example.org/"}
    base.update(kw)
    return base


# ---------------------------------------------------------------- wave 2 P1-1: South Dakota's December 31

def _sd_page(lake="Lake Poinsett", county="Hamlin", date="6/30/2026"):
    return (f"<h2>Harmful Algal Bloom Advisories 2026</h2><p><strong>{lake} ({county})</strong> {date}</p>"
            '<h2 class="title">end</h2>')


def test_sd_advisory_ending_december_31_lasts_to_central_midnight():
    from ingest import sd_danr_hab_advisories as H
    recs, _ = H.build(_sd_page(), "2026-12-31T20:00:00Z", [])
    r = recs[0]
    assert r["ended_at"] == "2026-12-31" and r["raw"]["time_zone"] == "America/Chicago"
    assert colour(r, "SD", "2027-01-01T05:30:00Z") == "red"          # 23:30 CST on December 31
    assert colour(r, "SD", "2027-01-01T06:00:00Z") is None           # January 1 in Central time
    # 01:00Z on January 1 is still December 31 in South Dakota: the advisory is not yet lifted
    late, _ = H.build(_sd_page(), "2027-01-01T01:00:00Z", [])
    assert late[0]["status"] == "advisory_active"


def test_sd_advisory_in_a_mountain_county_ends_at_mountain_midnight():
    from ingest import sd_danr_hab_advisories as H
    r = H.build(_sd_page("Example Lake", "Pennington"), "2026-12-01T00:00:00Z", [])[0][0]
    assert r["raw"]["time_zone"] == "America/Denver" and "71.7" in r["raw"]["time_zone_basis"]
    assert colour(r, "SD", "2027-01-01T06:30:00Z") == "red"
    assert colour(r, "SD", "2027-01-01T07:00:00Z") is None


def test_echo_date_only_records_of_central_and_mountain_states_end_their_own_day():
    # ECHO's date-only path stamps raw.time_zone (the zone it reads the event's times in); status honours it
    central = ev(event_id="echo-sewer-overflow:c", npdes_permit="NE0000001", started_at="2026-07-03",
                 ended_at="2026-07-04", time_precision="day", raw={"time_zone": "America/Chicago"})
    mountain = dict(central, event_id="echo-sewer-overflow:m", npdes_permit="NM0000001",
                    raw={"time_zone": "America/Denver"})
    ends = {e["event_id"]: S.event_intervals(e, None, Z("2026-07-04T00:00:00Z"), rules=RULES)[0]["end"]
            for e in (central, mountain)}
    assert ends["echo-sewer-overflow:c"] == Z("2026-07-05T05:00:00Z")   # midnight CDT
    assert ends["echo-sewer-overflow:m"] == Z("2026-07-05T06:00:00Z")   # midnight MDT
    # without the stamp, the permit's state gives the zone (never New York's)
    bare = dict(central, raw={})
    assert S.event_intervals(bare, None, Z("2026-07-04T00:00:00Z"), rules=RULES)[0]["end"] == Z("2026-07-05T05:00:00Z")


def test_echo_stamps_the_zone_of_a_date_only_record():
    src = (Path(__file__).resolve().parent.parent / "ingest" / "echo_sewer_overflow_events.py").read_text()
    assert 'raw["time_zone"] = ev_tz' in src


# ---------------------------------------------------------------- wave 2 P1-2 / wave 1 P1-1: an exact borrowed end

def test_ga_pairing_keeps_epas_exact_end_and_the_window_follows_it():
    import test_ingest_ga as T
    rows = [T.row(PERMIT_NUMBER="GAJ020999", WATERWAY_IMPACTED="Keg Creek")]
    recs, _ = T.run([T.posting("2026-11-02", rows)], epa=[T.epa("a", "2026-10-29", "Keg Creek", permit="GAJ020999")])
    r = recs[0]
    assert r["ended_at"] == "2026-10-29T11:00:00" and r["time_precision"] == "day"
    assert r["raw"]["ended_at_precision"] == "minute"
    ivs = S.event_intervals(r, "GA", Z("2026-11-01T00:00:00Z"), rules=RULES)
    discharge = [iv for iv in ivs if iv["rule"] == "discharge"][0]
    assert discharge["end"] == Z("2026-10-29T15:00:00Z")              # 11:00 EDT, not midnight
    assert colour(r, "GA", "2026-10-29T14:59:00Z") == "red"
    assert colour(r, "GA", "2026-10-29T15:01:00Z") == "yellow"       # was red until 04:00Z October 30
    caution = [iv for iv in ivs if iv["rule"] == "caution"][0]
    assert caution["end"] == Z("2026-10-29T15:00:00Z") + timedelta(hours=72)   # counted from 11:00, not midnight


def test_ga_unpairing_clears_the_end_precision():
    import test_ingest_ga as T
    from ingest import ga_epd_spills as G
    rows = [T.row(PERMIT_NUMBER="GAJ020999", WATERWAY_IMPACTED="Keg Creek")]
    recs, _ = T.run([T.posting("2026-11-02", rows)], epa=[T.epa("a", "2026-10-29", "Keg Creek", permit="GAJ020999")])
    G.mark_epa_duplicates(recs, [])
    assert recs[0]["ended_at"] is None and "ended_at_precision" not in recs[0]["raw"]


def test_illinois_poll_lift_ends_red_at_the_poll():
    r = ev(event_id="il-idph-beachguard:1", source_id="il-idph-beachguard", event_type="beach_advisory",
           status="advisory_lifted", started_at="2026-07-01", ended_at="2026-07-05T13:00:00Z", time_precision="day",
           raw={"ended_at_precision": "poll"})
    assert colour(r, "IL", "2026-07-05T12:59:00Z") == "red"
    assert colour(r, "IL", "2026-07-05T18:00:00Z") is None
    # the start is a Chicago day: 05:00Z, not 04:00Z
    assert S.event_intervals(r, "IL", Z("2026-07-06T00:00:00Z"), rules=RULES)[0]["start"] == Z("2026-07-01T05:00:00Z")


def test_a_poll_clearing_of_a_day_dated_beach_record_is_exact():
    # the Mississippi beach records' shape (start a day, end the poll that saw the flags clear) once the end carries its
    # own precision: the ms_mdeq_* ingesters are another fixer's; this asserts the status side
    r = ev(event_id="ms-mdeq-beach-monitoring:1", source_id="ms-mdeq-beach-monitoring", event_type="beach_advisory",
           status="advisory_lifted", started_at="2026-07-01", ended_at="2026-07-03T16:00:00Z", time_precision="day",
           raw={"ended_at_precision": "poll"})
    assert colour(r, "MS", "2026-07-03T15:59:00Z") == "red"
    assert colour(r, "MS", "2026-07-03T16:01:00Z") is None


def test_a_day_precision_end_still_runs_to_the_end_of_its_day():
    r = ev(started_at="2026-07-01", ended_at="2026-07-02", time_precision="day", npdes_permit="CT0000001")
    assert S.event_intervals(r, "CT", Z("2026-07-03T00:00:00Z"), rules=RULES)[0]["end"] == Z("2026-07-03T04:00:00Z")


# ---------------------------------------------------------------- wave 1 P1-2: California and Illinois days

def test_california_day_end_with_offset_runs_to_pacific_midnight():
    r = ev(event_id="ca-swrcb-ciwqs-spills:1", source_id="ca-swrcb-ciwqs-spills", npdes_permit="CA0000001",
           started_at="2026-11-04T00:00:00-08:00", ended_at="2026-11-04T00:00:00-08:00", time_precision="day")
    ivs = S.event_intervals(r, "CA", Z("2026-11-06T00:00:00Z"), rules=RULES)
    assert [iv for iv in ivs if iv["rule"] == "discharge"][0]["end"] == Z("2026-11-05T08:00:00Z")
    assert colour(r, "CA", "2026-11-05T07:59:00Z") == "red"
    assert colour(r, "CA", "2026-11-05T08:00:00Z") == "yellow"
    caution = [iv for iv in ivs if iv["rule"] == "caution"][0]     # 72 absolute hours from the Pacific boundary
    assert caution["end"] == Z("2026-11-08T08:00:00Z")
    assert colour(r, "CA", "2026-11-08T07:59:00Z") == "yellow" and colour(r, "CA", "2026-11-08T08:00:00Z") is None


def test_bare_dates_of_fhab_and_mwrd_reversals_are_their_states_days_including_the_dst_day():
    fhab = ev(event_id="ca-swrcb-fhab:1", source_id="ca-swrcb-fhab", event_type="hab_advisory",
              status="advisory_lifted", started_at="2026-10-30", ended_at="2026-11-01", time_precision="day")
    ivs = S.event_intervals(fhab, "CA", Z("2026-11-05T00:00:00Z"), rules=RULES)
    assert ivs[0]["start"] == Z("2026-10-30T07:00:00Z")              # midnight PDT
    assert ivs[0]["end"] == Z("2026-11-02T08:00:00Z")                # the end of November 1 (25 h day) in PST
    assert colour(fhab, "CA", "2026-11-02T07:59:00Z") == "red" and colour(fhab, "CA", "2026-11-02T08:00:00Z") is None
    rev = ev(event_id="il-mwrd-lake-reversals:1", source_id="il-mwrd-lake-reversals", event_type="cso",
             started_at="2026-11-01", ended_at="2026-11-01", time_precision="day")
    ivs = S.event_intervals(rev, "IL", Z("2026-11-03T00:00:00Z"), rules=RULES)
    d = [iv for iv in ivs if iv["rule"] == "discharge"][0]
    assert d["start"] == Z("2026-11-01T05:00:00Z") and d["end"] == Z("2026-11-02T06:00:00Z")


def test_eastern_records_are_unchanged():
    # the shared path: a New York day as before (the corpus of the twelve first jurisdictions is byte-identical)
    r = ev(event_id="ny-dec-sprtk:1", source_id="ny-dec-sprtk", started_at="2026-11-01", ended_at="2026-11-01",
           time_precision="day")
    assert S.event_zone(r, "NY") == S.LOCAL
    d = S.event_intervals(r, "NY", Z("2026-11-03T00:00:00Z"), rules=RULES)[0]
    assert d["start"] == Z("2026-11-01T04:00:00Z") and d["end"] == Z("2026-11-02T05:00:00Z")
    assert S.parse_time("2026-11-01") == Z("2026-11-01T04:00:00Z")    # the default is still New York's
    assert all(S.event_zone(ev(raw={"state": s}), s) == S.LOCAL for s, z in zones.STATE_ZONES.items()
               if z == zones.EASTERN and s in S.states())


# ---------------------------------------------------------------- wave 1 P1-3: Florida's Central time

def test_florida_zone_by_the_point():
    cases = {"Pensacola": (30.42, -87.22, zones.CENTRAL), "Panama City": (30.16, -85.66, zones.CENTRAL),
             "Mexico Beach": (29.94, -85.42, zones.CENTRAL), "Blountstown": (30.44, -85.05, zones.CENTRAL),
             "Bristol": (30.43, -84.98, zones.EASTERN), "Port St. Joe": (29.81, -85.30, zones.EASTERN),
             "Apalachicola": (29.73, -84.98, zones.EASTERN), "Tallahassee": (30.44, -84.28, zones.EASTERN),
             "Tampa": (27.95, -82.46, zones.EASTERN), "Marianna": (30.77, -85.23, zones.CENTRAL)}
    got = {k: zones.florida_zone(lat, lon) for k, (lat, lon, _) in cases.items()}
    assert got == {k: z for k, (_, _, z) in cases.items()}
    assert zones.florida_zone(None, None) == zones.EASTERN


def _pnp(lat, lon, **kw):
    import json as _json
    from ingest import fl_dep_pnp as P
    fx = Path(__file__).resolve().parent / "fixtures" / "fl_dep_pnp_layer.json"
    a = dict(_json.loads(fx.read_text())["features"][0]["attributes"])
    noon = int(datetime(2026, 7, 1, 12, tzinfo=UTC).timestamp() * 1000)     # wall clock stored as UTC
    a.update(INCIDENT_NUMBER=202607010, OBJECTID=7, LATITUDE=lat, LONGITUDE=lon, DATE_TIME_OF_REPORT=noon,
             RELEASE_START_DATE_TIME=noon - 12 * 3600_000, RELEASE_END_DATE_TIME=noon - 12 * 3600_000,
             RELEASE_ONGOING="N")
    a.update(kw)
    recs, _ = P.build([a], "2026-07-02T00:00:00Z", [], permits={})
    return recs[0]


def test_pnp_pensacola_noon_is_central_and_tampa_eastern():
    pen, tam = _pnp(30.42, -87.22), _pnp(27.95, -82.46)
    assert pen["reported_at"] == "2026-07-01T12:00:00-05:00" and pen["raw"]["time_zone"] == "America/Chicago"
    assert tam["reported_at"] == "2026-07-01T12:00:00-04:00" and "time_zone" not in tam["raw"]
    assert pen["started_at"] == "2026-07-01T00:00:00-05:00" and pen["ended_at"] == "2026-07-01T00:00:00-05:00"
    # the resulting window: the end of July 1 in Pensacola is 05:00Z on July 2, in Tampa 04:00Z
    end = lambda r: [iv for iv in S.event_intervals(r, "FL", Z("2026-07-03T00:00:00Z"), rules=RULES)  # noqa: E731
                     if iv["rule"] == "discharge"][0]["end"]
    assert end(pen) == Z("2026-07-02T05:00:00Z") and end(tam) == Z("2026-07-02T04:00:00Z")
    # either side of the river
    assert _pnp(30.44, -85.05)["raw"]["time_zone"] == "America/Chicago"
    assert "time_zone" not in _pnp(30.43, -84.98)["raw"]


def test_beach_dates_in_the_panhandle_are_central():
    from ingest import fl_doh_beaches as B
    page = (Path(__file__).resolve().parent / "fixtures" / "fl_doh_beach_page.html").read_text()
    pt = {"County": "Escambia", "EPAbeachID": "FL000001", "SPLocation": "EXAMPLE BEACH", "SPLat": 30.33,
          "SPLong": -87.14, "Link": "https://example.org/b"}
    r = B.build([pt], {B.point_key(pt): page}, [], "2026-11-04T00:00:00Z")[0][0]
    assert r["started_at"] == "2026-10-12T00:00:00-05:00" and r["raw"]["time_zone"] == "America/Chicago"


# ---------------------------------------------------------------- wave 1 P1-4: a late-posted clean sample

def _beach_page(rows):
    cells = "".join(
        f'<tr class="cbResultSetDataRow"><td class="cbResultSetData">ID: {pid} Location: EXAMPLE BEACH '
        f'Date: {d} Advisory: {adv}</td></tr>' for pid, d, adv in rows)
    return f"<table>{cells}</table>"


PT = {"County": "Example", "EPAbeachID": "FL000002", "SPLocation": "EXAMPLE BEACH", "SPLat": 27.95, "SPLong": -82.83,
      "Link": "https://example.org/c"}


def test_a_late_posted_negative_sample_does_not_backdate_the_end():
    from ingest import fl_doh_beaches as B
    k = B.point_key(PT)
    open_page = _beach_page([("2", "10/28/2026", "Yes")])
    first, _ = B.build([PT], {k: open_page}, [], "2026-11-05T12:00:00Z")
    assert first[0]["status"] == "advisory_active" and first[0]["raw"]["last_seen_open_at"] == "2026-11-05T12:00:00Z"
    # the November 4 sample's clean result is posted and read on November 6
    clean_page = _beach_page([("3", "11/04/2026", "No"), ("2", "10/28/2026", "Yes")])
    lifted, _ = B.build([PT], {k: clean_page}, first, "2026-11-06T15:00:00Z")
    r = lifted[0]
    assert r["status"] == "advisory_lifted" and r["raw"]["clean_sample_date"] == "2026-11-04"
    assert r["ended_at"] == "2026-11-06T15:00:00Z" and r["raw"]["ended_at_precision"] == "poll"
    assert r["raw"]["lift_observed_between"] == ["2026-11-05T12:00:00Z", "2026-11-06T15:00:00Z"]
    assert colour(r, "FL", "2026-11-05T12:00:00Z") == "red"         # not grey after November 4
    assert colour(r, "FL", "2026-11-06T14:59:00Z") == "red"
    assert colour(r, "FL", "2026-11-06T15:01:00Z") is None
    # read again later: the end stays the first observation
    again, _ = B.build([PT], {k: clean_page}, lifted, "2026-11-08T15:00:00Z")
    assert again[0]["ended_at"] == "2026-11-06T15:00:00Z"


def test_history_first_read_lifted_ends_at_the_sites_bound_not_the_collection_date():
    from ingest import fl_doh_beaches as B
    k = B.point_key(PT)
    page = _beach_page([("3", "10/04/2026", "No"), ("2", "09/28/2026", "Yes")])
    r = B.build([PT], {k: page}, [], "2026-11-06T15:00:00Z")[0][0]
    assert r["ended_at"] == "2026-10-08T00:00:00-04:00" and r["raw"]["ended_at_precision"] == "bound"
    assert "not DOH's date" in r["raw"]["ended_at_basis"]
    # a clean result first read within three days of its sample is the observation itself
    r = B.build([PT], {k: _beach_page([("3", "11/04/2026", "No"), ("2", "10/28/2026", "Yes")])}, [],
                "2026-11-06T15:00:00Z")[0][0]
    assert r["ended_at"] == "2026-11-06T15:00:00Z" and r["raw"]["lift_observed_between"][0] == "2026-11-04T00:00:00-05:00"


# ---------------------------------------------------------------- wave 1 P1-5: the public's sewage report

def test_explicit_citizen_sewage_report_colours_the_caution_through_ingest_and_status():
    r = _pnp(27.95, -82.46, REPORTER_REALTIONSHIP="OTHER- concerned citizen", RELEASE_ONGOING="Y",
             INCIDENT_REPORT="Incident Description: Raw sewage is flowing into Example Creek. Wastewater Type: Untreated "
                             "Cause: Blockage Spill Volume: 100 Volume Recovered: 0 Waterbodies Impacted: Y")
    assert r["raw"]["_pnp_kind"] == "citizen_complaint" and r["raw"]["report_provenance"] == "citizen"
    assert r["event_type"] == "sso" and r["status"] == "ongoing" and r["raw"]["reached_water"] is True
    assert r["waterbody_text"] == "Example Creek"
    ivs = S.event_intervals(r, "FL", Z("2026-07-02T00:00:00Z"), rules=RULES)
    assert ivs and not any(iv["color"] == "red" for iv in ivs)
    first = ivs[0]
    assert first["color"] == "yellow" and first["rule"] == "citizen_caution"
    assert first["rule_applied"]["rule"] == "provenance.citizen_report" and first["rule_applied"]["replaces"] == "ongoing"
    assert "member of the public" in first["citizen_report"] and "not confirmed" in first["label"]
    assert colour(r, "FL", "2026-07-02T00:00:00Z") == "yellow"


def test_a_citizen_report_never_absorbs_an_operators_report():
    op = ev(event_id="echo-sewer-overflow:9", source_id="echo-sewer-overflow", npdes_permit="FL0000009",
            started_at="2026-07-01T10:00:00-04:00", ended_at="2026-07-01T11:00:00-04:00")
    cit = ev(event_id="fl-dep-pnp:9", source_id="fl-dep-pnp", npdes_permit="FL0000009",
             started_at="2026-07-01T00:00:00-04:00", time_precision="day", raw={"report_provenance": "citizen"})
    assert S.find_duplicates([op, cit]) == {}
