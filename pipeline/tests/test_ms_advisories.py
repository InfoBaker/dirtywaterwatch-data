"""Mississippi advisories: MDEQ's water contact advisories by news release (ingest/ms_mdeq_water_contact.py) and the
beach layer (ingest/ms_mdeq_beaches.py). No network: MDEQ's real feed of 2026-11-07 (staff names in dc:creator
replaced) and the Trahon Creek release's text; the beach layer of 2026-11-07 (no station flagged that day, so the
open and lift cases set one station's flags by hand, as marked)."""
import copy
import json
from pathlib import Path

import common
from ingest import ms_mdeq_beaches as B
from ingest import ms_mdeq_water_contact as W

FIX = Path(__file__).parent / "fixtures"
REL = FIX / "ms_mdeq_releases"
TRAHON_URL = "https://www.mdeq.ms.gov/water-contact-advisory-issued-for-section-of-trahon-creek/"
AT = "2026-11-07T12:00:00Z"


def _pages():
    return {TRAHON_URL: (REL / "water-contact-advisory-issued-for-section-of-trahon-creek.html").read_text()}


def test_titles_tell_an_issue_from_a_lift():
    assert W.kind("Water Contact Advisory Issued for Section of Trahon Creek") == ("issue", ["Trahon Creek"])
    assert W.kind("MDEQ Lifts Water Contact Advisories for Long Beach and Biloxi East Central Beach") == (
        "lift", ["Long Beach", "Biloxi East Central Beach"])
    assert W.kind("Water Contact Advisory Issued for Biloxi East Central Beach") == ("issue", ["Biloxi East Central Beach"])
    assert W.kind("Air Quality Action Day Issued for August 30th for Ozone in DeSoto County") == (None, [])
    assert W.kind("Check the MDEQ Beach Monitoring Website for Current Water Quality Conditions") == (None, [])


def test_the_feed_gives_the_trahon_creek_advisory_and_the_standing_pearl_river_one():
    recs, stats = W.run((REL / "feed.xml").read_bytes(), _pages(), [], AT)
    by = {r["source_record_id"]: r for r in recs}
    t = by["trahon-creek-2026-09-02"]
    assert t["event_type"] == "beach_advisory" and t["status"] == "advisory_active" and t["ended_at"] is None
    assert t["started_at"] == "2026-09-02" and t["time_precision"] == "day"
    assert t["published_at"].startswith("2026-09-02T13:41:58-05:00")
    assert (t["lat"], t["lon"]) == (32.194572, -90.25033) and t["coord_source"] == "source"   # the release's own point
    assert t["advice_text"].startswith("MDEQ recommends that people avoid water contact")
    assert t["source_url"] == TRAHON_URL and t["source_updated_at"] == AT
    p = by["pearl-river-hanging-moss-creek-to-byram-swinging-bridge"]
    assert p["status"] == "advisory_active" and p["started_at"] == "2026-09-02"
    assert "remains in effect" in p["raw"]["quote"] and "began earlier" in p["raw"]["start_basis"]
    assert p["raw"]["stretch"]["from"]["source"].startswith("USGS GNIS 670883") and p["raw"]["stretch"]["to"]["lat"] == 32.17657
    # the beach issue and the beach lift are left to the beach layer; the air-quality releases are not read
    assert stats["beach_left_to_layer"] == 2 and stats["issues"] == 1 and len(recs) == 2
    assert not any("creator" in json.dumps(r) for r in recs)                 # dc:creator (a staff name) is never read


def test_a_lift_release_ends_the_advisory_and_history_is_kept():
    feed = (REL / "feed.xml").read_bytes()
    first, _ = W.run(feed, _pages(), [], AT)
    # a later lift release (made up for the test in MDEQ's wording of 2026-09-01) added to the feed
    lift = (b"<item><title>MDEQ Lifts Water Contact Advisory for Trahon Creek</title>"
            b"<link>https://www.mdeq.ms.gov/lift-test/</link><pubDate>Tue, 10 Nov 2026 15:00:00 +0000</pubDate></item>")
    feed2 = feed.replace(b"<item>", lift + b"<item>", 1)
    recs, stats = W.run(feed2, {}, copy.deepcopy(first), "2026-11-10T18:00:00Z")
    by = {r["source_record_id"]: r for r in recs}
    t = by["trahon-creek-2026-09-02"]
    assert t["status"] == "advisory_lifted" and t["ended_at"] == "2026-11-10" and stats["lifted"] == 1
    assert t["raw"]["release_text"]                                     # carried: the page was read last time
    assert by["pearl-river-hanging-moss-creek-to-byram-swinging-bridge"]["status"] == "advisory_active"
    # a run whose feed no longer lists the issue keeps the record
    gone, _ = W.run(b"<rss></rss>", {}, copy.deepcopy(first), "2026-12-01T00:00:00Z")
    assert {r["source_record_id"] for r in gone} == {r["source_record_id"] for r in first}


def test_status_keeps_a_reconfirmed_advisory_red():
    from build import status
    recs, _ = W.run((REL / "feed.xml").read_bytes(), _pages(), [], AT)
    t = next(r for r in recs if r["source_record_id"] == "trahon-creek-2026-09-02")
    ivs = status.event_intervals(t, "MS", status.parse_time(AT))
    assert ivs[0]["color"] == "red" and ivs[0]["rule"] == "advisory_active"
    assert status.category_of(t["event_type"]) == "beach"


def test_main_reads_a_saved_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "water-contact-advisory-issued-for-section-of-trahon-creek.html").write_text(_pages()[TRAHON_URL])
    assert W.main(["--file", str(REL / "feed.xml"), "--pages", str(pages)]) == 0
    doc = json.loads((tmp_path / f"{W.SOURCE_ID}.json").read_text())
    assert doc["count"] == 2 and doc["meta"]["open"] == 2


# ---------------------------------------------------------------- the beach layer

def _rows(**flags):
    rows = B.stations((FIX / "ms_mdeq_beaches" / "stations.json").read_bytes())
    for r in rows:
        if r["stationnumber"] == "3":
            r.update(flags)        # set by hand: no station was flagged on 2026-11-07
    return rows


def _segs():
    return B.segments((FIX / "ms_mdeq_beaches" / "segments.json").read_bytes())


def test_no_flag_no_record():
    recs, stats = B.run(_rows(), _segs(), [], AT)
    assert recs == [] and stats["stations"] == 21 and stats["flagged"] == 0


def test_an_advisory_opens_on_mdeqs_start_date_and_lifts_at_the_first_clear_poll():
    recs, stats = B.run(_rows(isadvisory=1, startdate="11/5/2026 10:00:00", advisorydesc="Enterococci above criteria"),
                        _segs(), [], AT)
    r = recs[0]
    assert stats["opened"] == 1 and r["event_type"] == "beach_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == "2026-11-05" and r["time_precision"] == "day" and r["source_updated_at"] == AT
    assert (r["lat"], r["lon"]) == (30.27639, -89.3736) and r["raw"]["station"] == "Waveland Beach"
    assert r["raw"]["segment"]["paths"] and r["raw"]["segment"]["west_end"] == "Oak Blvd"
    assert r["advice_text"] == "Enterococci above criteria"
    again, _ = B.run(_rows(isadvisory=1, startdate="11/5/2026 10:00:00"), _segs(), copy.deepcopy(recs),
                     "2026-11-07T13:00:00Z")
    assert len(again) == 1 and again[0]["source_updated_at"] == "2026-11-07T13:00:00Z"     # re-confirmed
    off, st = B.run(_rows(), _segs(), copy.deepcopy(again), "2026-11-08T13:00:00Z")
    assert st["lifted"] == 1 and off[0]["status"] == "advisory_lifted" and off[0]["ended_at"] == "2026-11-08T13:00:00Z"


def test_closure_and_bloom_types_and_a_flag_without_a_date():
    recs, _ = B.run(_rows(isclosure=1, startdate="11/5/2026"), _segs(), [], AT)
    assert recs[0]["event_type"] == "beach_closure"
    recs, _ = B.run(_rows(isadvisory=1, eventtype="HAB", startdate="11/5/2026"), _segs(), [], AT)
    assert recs[0]["event_type"] == "hab_advisory"
    from build import status
    assert status.category_of("hab_advisory") != status.category_of("beach_advisory")
    recs, _ = B.run(_rows(isadvisory=1), _segs(), [], AT)
    assert recs[0]["time_precision"] == "poll" and recs[0]["started_at"] == AT
    again, st = B.run(_rows(isadvisory=1), _segs(), copy.deepcopy(recs), "2026-11-07T13:00:00Z")
    assert len(again) == 1 and st["opened"] == 0                       # the same advisory, not a new one each poll


def test_a_short_layer_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    (tmp_path / f"{B.SOURCE_ID}.json").write_text(json.dumps({"records": [], "meta": {"stations": 21}}))
    short = tmp_path / "short.json"
    short.write_text(json.dumps({"features": json.loads((FIX / "ms_mdeq_beaches" / "stations.json").read_text())
                                 ["features"][:5]}))
    assert B.main(["--file", str(short)]) == 1
    assert json.loads((tmp_path / f"{B.SOURCE_ID}.json").read_text())["ok"] is False


# ---------------------------------------------------------------- the water the advisory names (final audit, P2-2)

def _status(recs, now, monkeypatch):
    """The status build over MDEQ's records with two Mississippi waters near the releases' points."""
    import tempfile
    from datetime import datetime
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / f"{W.SOURCE_ID}.json").write_text(json.dumps({"source_id": W.SOURCE_ID, "ok": True, "last_ok_at": now,
                                                       "meta": {}, "records": recs}))
    line = lambda pts: {"type": "LineString", "coordinates": pts}                        # noqa: E731
    pearl = [[-90.16, 32.42], [-90.112036, 32.351817], [-90.14, 32.25], [-90.20, 32.18]]
    trahon = [[-90.25033, 32.194572], [-90.23, 32.19], [-90.205, 32.182]]
    waters = {"pearl-river-ms": {"slug": "pearl-river-ms", "name": "Pearl River", "kind": "river", "state": "MS",
                                 "bbox": [-90.20, 32.18, -90.11, 32.42], "geometry": line(pearl)},
              "trahon-creek-ms": {"slug": "trahon-creek-ms", "name": "Trahon Creek", "kind": "stream", "state": "MS",
                                  "bbox": [-90.25033, 32.182, -90.205, 32.194572], "geometry": line(trahon)}}
    st, _ = S.build(now=datetime.fromisoformat(now.replace("Z", "+00:00")), write=False, events_dir=d, waters=waters,
                    outfalls=[], registry={}, reaches={}, flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return st


def test_the_pearl_river_and_trahon_creek_read_red_while_mdeqs_advisories_stand_and_grey_after_a_lift(monkeypatch):
    feed = (REL / "feed.xml").read_bytes()
    recs, _ = W.run(feed, _pages(), [], AT)
    by = {r["source_record_id"]: r for r in recs}
    p, t = by["pearl-river-hanging-moss-creek-to-byram-swinging-bridge"], by["trahon-creek-2026-09-02"]
    assert p["water_slugs"] == ["pearl-river-ms"] and p["raw"]["advisory_extent"] == "named_water"
    # both ends of the Pearl River stretch carry a cited public point: GNIS for the mouth, the bridge's National
    # Register nomination (UTM 15 759900 E 3563150 N, NAD 1927) for the Byram Swinging Bridge
    to = p["raw"]["stretch"]["to"]
    assert (to["lat"], to["lon"]) == (32.17657, -90.24366) and "79003427" in to["source"] and to["url"]
    assert t["raw"]["stretch"]["from"]["name"] == "culvert at the Interstate 55 frontage road"
    assert (t["raw"]["stretch"]["from"]["lat"], t["raw"]["stretch"]["to"]["name"]) == (32.194572, "confluence with the Pearl River")
    st = _status(recs, "2026-11-07T13:00:00Z", monkeypatch)
    pr = st["waters"]["pearl-river-ms"]
    # the river itself reads the authority's advisory: red, beach category, the stretch named in its reason
    assert pr["status"] == "red" and pr["status_by_category"]["beach"] == "red"
    assert pr["reasons"][0]["rule"] == "advisory_active"
    assert pr["reason_short"].startswith("Water contact advisory in effect · Mississippi Department of Environmental")
    # no stretch traced here (reaches={}): the whole-water fallback, and the reason says so
    assert pr["reason_short"].endswith("from the mouth of Hanging Moss Creek to the Byram Swinging Bridge"
                                       " · stretch not traced: shown on the whole water")
    assert pr["reasons"][0]["placement"] == "stretch_unmodeled"
    assert "not traced yet" in pr["reasons"][0]["stretch_fallback"]
    # Trahon Creek is tied by its name once its record exists (the report-names pass builds it)
    assert st["placements"][t["event_id"]]["water_slugs"] == ["trahon-creek-ms"]
    # reaches, not whole rivers (2026-11-07): Trahon Creek's advisory names no stretch with both ends, so it is listed
    # on the creek's page and shown at its point in the authority's colour; the creek record is not coloured
    tc = st["waters"]["trahon-creek-ms"]
    assert tc["status"] == "grey" and t["event_id"] in tc["events"]
    # rivers are drawn by reaches and markers, never filled: the markers stay, so the map still shows both
    pts = {a["event_id"]: a for a in st["advisory_points"]}
    assert pts[p["event_id"]]["status"] == "red" and pts[p["event_id"]]["water_slugs"] == ["pearl-river-ms"]
    assert pts[t["event_id"]]["status"] == "red" and pts[t["event_id"]]["water_slugs"] == ["trahon-creek-ms"]
    from build.status import RIVER_POINT_WHY
    assert pts[t["event_id"]]["why"] == RIVER_POINT_WHY
    # a lift release ends it: the river reads grey after the lift day
    lift = (b"<item><title>MDEQ Lifts Water Contact Advisory for Pearl River</title>"
            b"<link>https://www.mdeq.ms.gov/lift-test/</link><pubDate>Tue, 10 Nov 2026 15:00:00 +0000</pubDate></item>")
    lifted, _ = W.run(feed.replace(b"<item>", lift + b"<item>", 1), {}, copy.deepcopy(recs), "2026-11-10T18:00:00Z")
    assert next(r for r in lifted if r["event_id"] == p["event_id"])["status"] == "advisory_lifted"
    st = _status(lifted, "2026-11-12T13:00:00Z", monkeypatch)
    assert st["waters"]["pearl-river-ms"]["status"] == "grey"
    assert st["waters"]["trahon-creek-ms"]["status"] == "grey"                 # a point, never the whole creek
    assert {a["event_id"]: a for a in st["advisory_points"]}[t["event_id"]]["status"] == "red"   # still stands


def test_a_beach_advisory_on_a_river_still_colours_only_its_point(monkeypatch):
    recs, _ = W.run((REL / "feed.xml").read_bytes(), _pages(), [], AT)
    p = copy.deepcopy(next(r for r in recs if r["source_record_id"].startswith("pearl-river")))
    for k in ("advisory_extent", "advisory_noun"):
        p["raw"].pop(k)                                                         # an ordinary station's advisory
    st = _status([p], "2026-11-07T13:00:00Z", monkeypatch)
    assert st["waters"]["pearl-river-ms"]["status"] == "grey"
    assert st["advisory_points"][0]["why"] == "water is not a lake, pond or reservoir under 50 km²"
