"""Idaho: DEQ's CyanoHAB Risk Data Table (ingest/id_deq_cyanohab.py) with DHW's map points, and Idaho's clock (49 CFR
71.9: Pacific north of the Salmon River). A Health Advisory is the authority's, red while DEQ lists it and ended at
the read that no longer does; a Watch or an Alert is DEQ's risk level, never an advisory: the site's caution only,
with DEQ's words. Fixtures: seven real rows of the table read 2026-11-14 and DHW's points for them (safe fields)."""
import json
from datetime import datetime
from pathlib import Path

import pytest

import zones
from ingest import id_deq_cyanohab as H

FIX = Path(__file__).resolve().parent / "fixtures" / "id"
T0 = "2026-11-14T23:00:00Z"
T1 = "2026-11-15T23:00:00Z"
T2 = "2026-11-16T23:00:00Z"
RULES = json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())


def page():
    return (FIX / "cyanohab-table.html").read_text()


def layer():
    return H.parse_layer(json.loads((FIX / "dhw-layer.json").read_text()))


def without(lay, name):
    """DHW's layer without one water: the second source agrees the water is no longer listed."""
    return {k: v for k, v in lay.items() if k != H.key(name)}


def run(state, rows, at, lay=None):
    state = H.update(state, rows, at, lay)
    return state, {r["source_record_id"]: r for r in H.records(state)}


def first():
    return run({}, H.parse_table(page()), T0, layer())


def find(recs, prefix):
    out = [r for k, r in recs.items() if k.startswith(prefix)]
    assert len(out) == 1, (prefix, sorted(recs))
    return out[0]


def intervals(ev, now):
    from build import status as S
    return S._event_intervals(ev, "ID", datetime.fromisoformat(now), None, RULES)


def test_table_rows_read_as_deq_gives_them():
    rows = H.parse_table(page())
    assert len(rows) == 7
    by = {r["water"]: r for r in rows}
    assert by["Lake Lowell"]["data_type"] == "" and by["Lake Lowell"]["level"] == "Watch"
    assert H.read_date(by["Crane Creek Reservoir"]["collection_date"]) == "2026-06-29"      # "06/29/26"
    assert H.read_date("13/40/2026") is None


def test_a_page_without_the_table_is_a_failure_not_a_withdrawal(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        H.parse_table("<html><body>No table today</body></html>")
    with pytest.raises(ValueError):
        H.parse_table("<table><tr><th>Lake</th><th>Status</th></tr><tr><td>x</td><td>y</td></tr></table>")
    monkeypatch.setattr(H, "STATE_PATH", tmp_path / "state.json")
    out = tmp_path / "events.json"
    monkeypatch.setattr(H, "write_events", lambda sid, recs, **kw: out.write_text(json.dumps({"recs": recs, **kw})))
    bad = tmp_path / "bad.html"
    bad.write_text("<html>maintenance</html>")
    assert H.main(["--file", str(bad), "--at", T0]) == 1
    assert json.loads(out.read_text())["ok"] is False


def test_health_advisory_is_the_authoritys_dated_by_the_poll_with_the_sample_apart():
    _, recs = first()
    r = find(recs, "mann-lake:nez-perce:advisory:")
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == T0 and r["time_precision"] == "poll"
    assert r["sampled_at"] == "2026-10-08"                       # the Collection Date, never the advisory's start
    assert r["reported_at"] is None and r["published_at"] is None and r["source_updated_at"] is None
    assert r["raw"]["_last_seen_in_source"] == T0 and "began before" in r["raw"]["start_basis"]
    assert "Toxins have exceeded threshold levels" in r["advice_text"]
    ivs = intervals(r, "2026-11-15T12:00:00+00:00")
    assert ivs and ivs[0]["rule"] == "advisory_active"


def test_watch_and_alert_are_deqs_risk_levels_never_an_advisory():
    _, recs = first()
    for prefix in ("lake-lowell:canyon:watch:", "henrys-lake:fremont:watch:"):
        r = find(recs, prefix)
        assert r["status"] == "unknown" and r["raw"]["_agency_label_only"] and r["raw"]["_caution_to_notice_end"]
        assert r["time_precision"] == "day" and r["started_at"] == r["sampled_at"]
        assert "Health Advisory" not in r["advice_text"]
        ivs = intervals(r, "2026-11-15T12:00:00+00:00")
        assert ivs and all(iv["rule"] == "sample_caution" for iv in ivs)
    # an Alert whose More Information closes the water is the authority's closure, red while listed (Astra
    # 2026-11-15 P1-2): quoted as the table's, DEQ's level kept
    alert = find(recs, "hordemann-pond:latah:closure:")
    assert "closed to recreational use" in alert["advice_text"] and alert["raw"]["_closure_level"] == "Health Alert"
    assert alert["status"] == "advisory_active" and "_agency_label_only" not in alert["raw"]
    assert "id-deq-cyanohab-risk-table" in RULES["unresolved"]["sample_caution"]["sources"]


def test_a_watch_listed_for_weeks_keeps_the_caution_while_listed_and_closes_when_gone():
    state, recs = first()
    rows = H.parse_table(page())
    state, recs = run(state, rows, "2026-12-01T23:00:00Z")
    w = find(recs, "lake-lowell:canyon:watch:")
    assert w["raw"]["_last_seen_in_source"] == "2026-12-01T23:00:00Z"
    ivs = intervals(w, "2026-12-02T12:00:00+00:00")
    assert ivs and ivs[-1]["end"].isoformat() >= "2026-12-01T23:00"      # past 72 h from the sample: still listed
    gone = [r for r in rows if r["water"] != "Lake Lowell"]
    # a disappearance ends the notice only when DHW's map, read in the same run, no longer shows it (Astra P1-1)
    state, recs = run(state, gone, "2026-12-03T23:00:00Z", without(layer(), "Lake Lowell"))
    w = find(recs, "lake-lowell:canyon:watch:")
    assert w["status"] == "ended" and w["raw"]["_notice_closed_at"] == w["ended_at"]
    assert w["raw"]["ended_at_precision"] == "poll"


def test_an_advisory_ends_at_the_read_that_shows_a_lower_level_and_the_watch_follows():
    state, recs = first()
    rows = H.parse_table(page())
    down = [dict(r, level="Watch", info="HABs Health Alert expired after 30 days.") if r["water"] == "Mann Lake" else r
            for r in rows]
    state, recs = run(state, down, T1)
    adv = find(recs, "mann-lake:nez-perce:advisory:")
    assert adv["status"] == "advisory_lifted" and adv["ended_at"] == T1
    assert adv["raw"]["ended_at_precision"] == "poll" and "Health Watch" in adv["raw"]["end_basis"]
    watch = find(recs, "mann-lake:nez-perce:watch:")
    assert watch["status"] == "unknown" and watch["raw"]["_agency_label_only"]
    # a water that leaves the table ends at that read; nothing else changes
    state, recs = run(state, [r for r in down if r["water"] != "Crane Creek Reservoir"], T2,
                      without(layer(), "Crane Creek Reservoir"))
    crane = find(recs, "crane-creek-reservoir:washington:advisory:")
    assert crane["status"] == "advisory_lifted" and crane["ended_at"] == T2
    assert crane["raw"]["end_basis"] == H.END_GONE
    assert find(recs, "lake-lowell:canyon:watch:")["status"] == "unknown"


def test_a_new_collection_date_at_the_same_level_keeps_the_record():
    state, _ = first()
    rows = [dict(r, collection_date="11/12/2026") if r["water"] == "Mann Lake" else r for r in H.parse_table(page())]
    state, recs = run(state, rows, T1)
    r = find(recs, "mann-lake:nez-perce:advisory:")
    assert r["started_at"] == T0 and r["sampled_at"] == "2026-11-12"
    assert r["raw"]["collection_dates"] == ["2026-10-08", "2026-11-12"]


def test_points_are_dhws_own_rounded_and_named_arms_keep_their_place():
    _, recs = first()
    bru, snk = find(recs, "cj-strike-bruneau-arm:owyhee:"), find(recs, "cj-strike-snake-river-arm:elmore:")
    assert bru["waterbody_text"] == snk["waterbody_text"] == "C J Strike Reservoir"
    assert bru["raw"]["part"] == "Bruneau Arm" and snk["raw"]["part"] == "Snake River Arm"
    assert (bru["lat"], bru["lon"]) != (snk["lat"], snk["lon"])
    for r in recs.values():
        assert r["lat"] is not None and round(r["lat"], 3) == r["lat"] and round(r["lon"], 3) == r["lon"]
        assert "Health and Welfare" in r["raw"]["point_basis"]
    assert find(recs, "henrys-lake:fremont:")["lat"] == 44.643          # "Henrys Lake" is DHW's "Henry's Lake"


def test_layer_query_never_asks_for_staff_fields():
    fields = H.LAYER_QUERY.split("outFields=")[1].split("&")[0].split(",")
    assert fields == ["objectid", "LocationDiscription", "RiskTier", "DisplayOnWebsite", "Issue", "Issue_other",
                      "WebNote"]
    raw = (FIX / "dhw-layer.json").read_text()
    for k in ("Email", "Creator", "Editor", "InternalNote", "ContactInfo", '"Name"'):
        assert k not in raw


def test_a_layer_outage_keeps_the_last_points():
    state, _ = first()
    state, recs = run(state, H.parse_table(page()), T1, None)
    assert find(recs, "mann-lake:nez-perce:")["lat"] == 46.372


def test_an_unknown_level_is_kept_with_a_parse_error():
    rows = H.parse_table(page()) + [{"level": "Caution", "water": "Example Reservoir", "county": "Ada",
                                     "data_type": "", "collection_date": "11/01/2026", "info": ""}]
    _, recs = run({}, rows, T0, layer())
    r = find(recs, "unread-")
    assert r["event_type"] == "unknown" and "cannot read" in r["parse_error"] and len(recs) == 8


def test_clock_is_the_countys_pacific_north_of_the_salmon_river():
    _, recs = first()
    assert find(recs, "mann-lake:nez-perce:")["raw"]["time_zone"] == "America/Los_Angeles"
    assert find(recs, "hordemann-pond:latah:")["raw"]["time_zone"] == "America/Los_Angeles"
    assert find(recs, "lake-lowell:canyon:")["raw"]["time_zone"] == "America/Denver"
    assert find(recs, "crane-creek-reservoir:washington:")["raw"]["time_zone"] == "America/Denver"


@pytest.mark.parametrize("county,lat,lon,zone", [
    ("Kootenai County", None, None, zones.PACIFIC), ("Nez Perce", None, None, zones.PACIFIC),
    ("Benewah", None, None, zones.PACIFIC), ("Ada", None, None, zones.MOUNTAIN), ("Lemhi", None, None, zones.MOUNTAIN),
    ("Idaho", None, None, zones.PACIFIC),                       # no point: Grangeville's side of the river
    ("Idaho County", 45.93, -116.12, zones.PACIFIC),            # Grangeville, north of the Salmon River
    ("Idaho County", 45.30, -115.00, zones.MOUNTAIN),           # south of the main channel
    (None, 47.68, -116.78, zones.PACIFIC), (None, 43.61, -116.20, zones.MOUNTAIN), (None, None, None, zones.MOUNTAIN),
])
def test_idaho_zone_49_cfr_71_9(county, lat, lon, zone):
    assert zones.idaho_zone(county=county, lat=lat, lon=lon) == zone


def test_zone_for_idaho_by_point_and_other_states_unchanged():
    assert zones.zone_for("ID", 47.68, -116.78) == zones.PACIFIC
    assert zones.zone_for("ID", 43.61, -116.20) == zones.MOUNTAIN
    assert zones.zone_for("ID") == zones.MOUNTAIN
    assert zones.zone_for("UT", 40.76, -111.89) == zones.MOUNTAIN and zones.zone_for("WA", 47.6, -122.3) == zones.PACIFIC
    assert zones.zone_for("OR", 44.0, -117.0) == zones.oregon_zone(44.0, -117.0)
    doc = json.loads((Path(zones.__file__).resolve().parents[1] / "data" / "reference" / "id-counties.json").read_text())
    assert doc["time_zone"]["law"]["cite"] == "49 CFR 71.9(a) and (d)"
    assert len(doc["time_zone"]["pacific_counties"]) == 9 and doc["time_zone"]["split_county"] == "Idaho County"


# ---------------------------------------------------------------- DHW's Issue field (own-fixes 2026-11-21)
# The Swim Guide review: the reader ignored DHW's Issue (Cyanobacterial Bloom, Beach Closure, Swimmer's Itch, Other),
# so a closure row read as a bloom's point and tier. Fixture: three real rows of DHW's layer (2026-11-21) and a copy
# of Mann Lake's row with DHW's own Issue value "Beach Closure" (no closure row was on the layer that day).

def issue_doc():
    return json.loads((FIX / "dhw-layer-issue.json").read_text())


def run_issues(state, rows, at, doc, partial=None):
    lay = H.parse_layer(doc) if doc is not None else None
    iss = H.parse_issues(doc) if doc is not None else None
    state = H.update(state, rows, at, lay, partial, issues=iss)
    return state, {r["source_record_id"]: r for r in H.records(state)}


def test_a_closure_row_is_never_a_blooms_point_or_tier():
    lay = H.parse_layer(issue_doc())
    assert lay[H.key("Mann Lake")]["tier"] == "Health Advisory"         # the bloom row's, not the closure copy's
    iss = H.parse_issues(issue_doc())
    assert [(i["name"], i["issue"], i["shown"]) for i in iss] == [("Mann Lake", "Beach Closure", "Yes")]
    doc = issue_doc()
    doc["features"] = [f for f in doc["features"] if f["attributes"]["Issue"] != "Cyanobacterial Bloom"
                       or f["attributes"]["LocationDiscription"] != "Mann Lake"]
    assert H.key("Mann Lake") not in H.parse_layer(doc)                 # a closure alone does not keep a bloom shown


def test_a_dhw_closure_is_a_beach_closure_listed_without_a_colour_unless_its_note_gives_a_reason():
    from build import beach_reason as BR
    _, recs = run_issues({}, H.parse_table(page()), T0, issue_doc())
    r = find(recs, "dhw:mann-lake:beach-closure:")
    assert r["event_type"] == "beach_closure" and r["status"] == "advisory_active" and r["time_precision"] == "poll"
    assert r["started_at"] == T0 and r["raw"]["_last_seen_in_source"] == T0 and r["lat"] is not None
    assert r["raw"]["dhw_issue"] == "Beach Closure" and "Health and Welfare" in r["authority"]
    assert r["waterbody_text"] == "Mann Lake" and "Beach Closure" in r["advice_text"]
    assert BR.judge(r, RULES)["stated"] is False                        # decision 40: listed, not coloured
    doc = issue_doc()
    doc["features"][-1]["attributes"]["WebNote"] = "Closed after E. coli results above the standard."
    _, recs = run_issues({}, H.parse_table(page()), T0, doc)
    assert BR.judge(find(recs, "dhw:mann-lake:beach-closure:"), RULES)["stated"] is True
    blooms = [x for x in recs.values() if x["event_type"] == "hab_advisory"]
    assert len(blooms) == 7 and not [x for x in recs.values() if x["source_record_id"].startswith("dhw:")
                                     and x["event_type"] == "hab_advisory"]


def test_a_dhw_listing_ends_only_on_a_complete_read_of_the_map():
    state, _ = run_issues({}, H.parse_table(page()), T0, issue_doc())
    state, recs = run_issues(state, H.parse_table(page()), T1, None)                  # the map was not read
    assert find(recs, "dhw:mann-lake:beach-closure:")["status"] == "advisory_active"
    state, recs = run_issues(state, H.parse_table(page()), T1, issue_doc(), "a feature of DHW's layer has no name")
    assert find(recs, "dhw:mann-lake:beach-closure:")["status"] == "advisory_active"
    doc = issue_doc()
    doc["features"][-1]["attributes"]["DisplayOnWebsite"] = "End"                    # DHW ends it on its map
    state, recs = run_issues(state, H.parse_table(page()), T2, doc)
    r = find(recs, "dhw:mann-lake:beach-closure:")
    assert r["status"] == "advisory_lifted" and r["ended_at"] == T2 and r["raw"]["ended_at_precision"] == "poll"


def test_swimmers_itch_and_other_are_beach_advisories_with_the_issuers_words():
    doc = issue_doc()
    doc["features"][-1]["attributes"].update(Issue="Other", Issue_other="Debris in the swim area")
    _, recs = run_issues({}, H.parse_table(page()), T0, doc)
    r = find(recs, "dhw:mann-lake:other:")
    assert r["event_type"] == "beach_advisory" and "Debris in the swim area" in r["advice_text"]
    doc["features"][-1]["attributes"].update(Issue="Swimmer's Itch", Issue_other=None)
    _, recs = run_issues({}, H.parse_table(page()), T0, doc)
    assert find(recs, "dhw:mann-lake:swimmers-itch:")["event_type"] == "beach_advisory"


def test_review_dhw_listings_keep_dhws_own_row_identity():
    doc = issue_doc()
    twin = json.loads(json.dumps(doc["features"][-1]))
    twin["attributes"]["objectid"] = 999
    twin["geometry"] = {"x": -117.0, "y": 46.0}
    doc["features"].append(twin)                       # a second closure row of the same name: two listings
    state, recs = run_issues({}, H.parse_table(page()), T0, doc)
    closures = [r for r in recs.values() if r["event_type"] == "beach_closure"]
    assert len(closures) == 2 and {r["raw"]["dhw_objectid"] for r in closures} == {doc["features"][-2]["attributes"]["objectid"], 999}
    doc2 = issue_doc()
    doc2["features"][-1]["attributes"]["LocationDiscription"] = "Mann Lake (north beach)"      # renamed, same row
    state2, recs2 = run_issues({}, H.parse_table(page()), T0, issue_doc())
    state2, recs2 = run_issues(state2, H.parse_table(page()), T1, doc2)
    closures = [r for r in recs2.values() if r["event_type"] == "beach_closure"]
    assert len(closures) == 1 and closures[0]["status"] == "advisory_active" and closures[0]["started_at"] == T0


def test_review_a_failed_deq_read_still_updates_dhws_listings(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(H, "save_raw", lambda *a, **k: None)
    written = {}
    monkeypatch.setattr(H, "write_events", lambda sid, recs, **kw: written.update(recs=recs, **kw) or tmp_path / "e.json")
    (tmp_path / "bad.html").write_text("<html><p>no table today</p></html>")
    (tmp_path / "layer.json").write_text(json.dumps(issue_doc()))
    assert H.main(["--file", str(tmp_path / "bad.html"), "--layer-file", str(tmp_path / "layer.json"), "--at", T0]) == 1
    assert written["ok"] is False and written.get("partial") is True
    assert [r["event_type"] for r in written["recs"]] == ["beach_closure"]
