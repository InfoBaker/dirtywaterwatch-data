"""Florida DEP algal bloom visits -> bloom episodes per site (no network; synthetic visits)."""
from datetime import UTC, datetime

from ingest import fl_dep_habs as H


def ms(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp() * 1000)


def v(oid, when, bloom, toxin=None, loc="Lake Example - Center (LEX)", lat=28.5, lon=-81.5):
    return {"objectid": oid, "globalid": f"g{oid}", "SampleDateTime": ms(when), "locationString": loc,
            "esrignss_latitude": lat, "esrignss_longitude": lon, "BloomObserved": bloom, "ToxinPresent": toxin,
            "AlgalIDResult": "Microcystis aeruginosa" if bloom == "Yes" else None, "County": "Orange",
            "MonitoringGroupPublicFacing": "CEROC", "Comments": "not requested", "PicURL": "not requested"}


NOW = datetime(2026, 11, 4, tzinfo=UTC)


def test_bloom_opens_and_a_clear_visit_lifts():
    recs, stats = H.build([v(1, "2026-09-01T14:00", "Yes", "Yes"), v(2, "2026-09-10T14:00", "Yes", "Pending"),
                           v(3, "2026-09-20T14:00", "No", "No"), v(4, "2026-10-01T14:00", "No", "No")],
                          "2026-11-04T00:00:00Z", NOW)
    assert len(recs) == 1 and stats["visits_without_bloom"] == 1
    r = recs[0]
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-09-01T10:00:00-04:00" and r["ended_at"] == "2026-09-20T10:00:00-04:00"
    assert r["waterbody_text"] == "Lake Example" and r["event_id"] == "fl-dep-habs:g1"
    assert r["source_updated_at"] == "2026-09-10T10:00:00-04:00"
    assert "not a health advisory" in r["raw"]["basis"]
    assert "Comments" not in str(r) and "PicURL" not in str(r)


def test_open_episode_is_active_then_unknown_when_stale():
    recs, _ = H.build([v(1, "2026-10-20T14:00", "No", "Yes")], "x", NOW)
    assert recs[0]["status"] == "advisory_active" and recs[0]["ended_at"] is None
    recs, _ = H.build([v(1, "2026-03-01T14:00", "Yes")], "x", NOW)
    assert recs[0]["status"] == "unknown" and "no later visit" in recs[0]["raw"]["note"]


def test_a_site_named_by_a_street_address_keeps_no_house_number():
    # name review 2026-11-04: DEP names some sites by a street address, often a resident's dock
    recs, _ = H.build([v(1, "2026-10-20T14:00", "Yes", loc="Example Lake - 1915 Placeholder Lane"),
                       v(2, "2026-10-25T14:00", "Yes", loc="Example Lake - 1915 Placeholder Lane")], "x", NOW)
    assert len(recs) == 1 and len(recs[0]["raw"]["visits"]) == 2            # still one site
    r = recs[0]
    assert "1915" not in str(r)
    assert r["outfall_name"] == r["raw"]["site"] == "Example Lake - [house number removed] Placeholder Lane"
    assert r["waterbody_text"] == "Example Lake"
    recs, _ = H.build([v(1, "2026-10-20T14:00", "Yes", loc="Example River - Highway 17 Bridge")], "x", NOW)
    assert recs[0]["outfall_name"] == "Example River - Highway 17 Bridge"
