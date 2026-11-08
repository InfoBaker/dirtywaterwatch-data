"""Kentucky's standing swimming advisories (ingest/ky_dow_swimming_advisories.py; review 2026-11-08 P1-1): the list of
the agencies' page (tests/fixtures/ky_dow_swimming_advisories.html: the advisory part of the page read on 2026-11-07,
the contact block left out) read as standing advisories in the agencies' own words, with no invented date."""
import json
from pathlib import Path

import common
from ingest import ky_dow_swimming_advisories as M

FIX = Path(__file__).parent / "fixtures" / "ky_dow_swimming_advisories.html"


def _state(*pages):
    st = {}
    for at, page in pages:
        M.update(st, M.list_text(page), at)
    return st


def test_the_pages_stretches_are_standing_advisories_in_the_agencies_words():
    recs = M.records(_state(("2026-11-07T12:00:00Z", FIX.read_text())))
    by = {r["source_record_id"]: r for r in recs}
    assert len(recs) == 12 and all(r["status"] == "advisory_active" for r in recs)
    assert {r["waterbody_text"] for r in recs} == {
        "Cumberland River", "Martins Fork Cumberland River", "Catron Creek", "Clover Fork of the Cumberland River",
        "Straight Creek", "Poor Fork of the Cumberland River", "Looney Creek", "North Fork of Kentucky River",
        "Licking River", "Banklick Creek", "Three Mile Creek"}
    r = by["licking-banklick-to-ohio"]
    assert r["event_type"] == "beach_advisory" and "untreated or inadequately treated sewage" in r["advice_text"]
    assert r["started_at"] == "2026-11-07T12:00:00Z" and r["time_precision"] == "poll"
    assert r["reported_at"] is None and r["published_at"] is None and r["source_updated_at"] is None
    assert "several years" in r["raw"]["start_basis"] and r["raw"]["_last_seen_in_source"] == "2026-11-07T12:00:00Z"
    assert r["raw"]["stretch_text"] == "from Banklick Creek to the confluence with the Ohio River"
    assert r["water_slugs"] == [] and r["lat"] == 39.091734 and r["coord_source"] == "stretch_point"


def test_a_stretch_the_page_drops_ends_at_that_read():
    page = FIX.read_text()
    fewer = page.replace("Looney Creek from the mouth to Lynch Water Plant Bridge", "")
    recs = M.records(_state(("2026-11-07T12:00:00Z", page), ("2026-11-08T12:00:00Z", fewer)))
    by = {r["source_record_id"]: r for r in recs}
    gone = by["looney-creek-mouth-to-lynch"]
    assert gone["status"] == "advisory_lifted" and gone["ended_at"] == "2026-11-08T12:00:00Z"
    assert gone["raw"]["ended_at_precision"] == "poll"
    assert by["catron-creek"]["status"] == "advisory_active"
    assert by["catron-creek"]["raw"]["_last_seen_in_source"] == "2026-11-08T12:00:00Z"


def test_a_new_listed_sentence_is_kept_as_unknown():
    page = FIX.read_text().replace("<li>Looney Creek", "<li>All of Example Creek</li><li>Looney Creek")
    recs = M.records(_state(("2026-11-07T12:00:00Z", page)))
    unk = [r for r in recs if r["event_type"] == "unknown"]
    assert len(unk) == 1 and "Example Creek" in unk[0]["parse_error"]


def test_a_page_without_the_list_is_not_a_withdrawal(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert M.main(["--file", str(FIX), "--at", "2026-11-07T12:00:00Z"]) == 0
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>Page not available</body></html>")
    assert M.main(["--file", str(bad), "--at", "2026-11-08T12:00:00Z"]) == 1
    doc = json.loads((tmp_path / "events" / f"{M.SOURCE_ID}.json").read_text())
    assert doc["ok"] is False and doc["count"] == 12 and {r["status"] for r in doc["records"]} == {"advisory_active"}


# ---------------------------------------------------------------- final audit 2026-11-08 P1-1: a marker for each

def _ky_world(tmp_path):
    from build import status as S
    recs = M.records(_state(("2026-11-07T12:00:00Z", FIX.read_text())))
    d = tmp_path / "events"
    d.mkdir()
    (d / f"{M.SOURCE_ID}.json").write_text(json.dumps({"source_id": M.SOURCE_ID, "ok": True,
                                                       "last_ok_at": "2026-11-07T12:00:00Z", "meta": {},
                                                       "records": recs}))

    def line(slug, name, coords):
        xs, ys = [c[0] for c in coords], [c[1] for c in coords]
        return slug, {"slug": slug, "name": name, "kind": "river", "state": "KY", "bbox": [min(xs), min(ys), max(xs),
                      max(ys)], "geometry": {"type": "LineString", "coordinates": coords}}
    waters = dict([
        line("cumberland-river-ky", "Cumberland River", [[-83.80, 36.80], [-83.69, 36.762], [-83.42, 36.826],
                                                         [-83.33, 36.85]]),
        line("cumberland-river-kuttawa-ky", "Cumberland River", [[-88.20, 37.06], [-88.10, 37.10]]),
        line("licking-river-ky", "Licking River", [[-84.49, 39.03], [-84.5036, 39.0917]]),
        line("banklick-creek-ky", "Banklick Creek", [[-84.60, 38.89], [-84.4905, 39.0328]]),
    ])
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())
    rules["live_states"] = list(rules["live_states"]) + ["KY"]
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    return S, {"events_dir": d, "waters": waters, "outfalls": [], "registry": {}, "reaches": {}, "flows": ({}, {}),
               "rules": rules, "placement_cache": False}


def test_every_standing_advisory_has_its_own_red_marker_near_its_stretch(tmp_path):
    from datetime import UTC, datetime
    from ingest.echo_sewer_overflow_events import metres
    S, w = _ky_world(tmp_path)
    st, _ = S.build(now=datetime(2026, 11, 8, 12, tzinfo=UTC), write=False, **w)
    pts = [p for p in st["advisory_points"] if p["event_id"].startswith(M.SOURCE_ID)]
    assert len(pts) == 12 and {p["status"] for p in pts} == {"red"} and {p["category"] for p in pts} == {"beach"}
    by = {p["event_id"].split(":", 1)[1]: p for p in pts}
    assert set(by) == {k for k, *_ in M.STRETCHES}
    # the marker is drawn at the record's own point, which lies on the named stretch (within 2 km of the GNIS feature)
    recs = {r["source_record_id"]: r for r in M.records(_state(("2026-11-07T12:00:00Z", FIX.read_text())))}
    for key, *_, (_, lat, lon, _, _) in M.STRETCHES:
        assert metres((recs[key]["lat"], recs[key]["lon"]), (lat, lon)) < 2000, key
    for key in ("cumberland-four-mile-bridge-to-pineville", "cumberland-wallins-creek-bridge-to-harlan"):
        assert by[key]["water_slugs"] == ["cumberland-river-ky"], by[key]["water_slugs"]   # the point decides
    assert not any(v.get("status") == "red" for v in st["waters"].values())             # markers, no whole water


def test_each_record_cites_its_point_and_the_licking_carries_both_ends():
    recs = {r["source_record_id"]: r for r in M.records(_state(("2026-11-07T12:00:00Z", FIX.read_text())))}
    for r in recs.values():
        assert r["lat"] and r["coord_source"] == "stretch_point" and "USGS GNIS feature" in r["raw"]["point_basis"]
        assert r["raw"]["point_url"].startswith("https://edits.nationalmap.gov/") and r["raw"]["county"]
    lick = recs["licking-banklick-to-ohio"]["stretch"]
    assert lick["water"] == "Licking River" and lick["start"]["name"] == "mouth of Banklick Creek"
    assert lick["end"]["name"] == "mouth of the Licking River"
    assert recs["straight-creek"]["raw"]["county"] == "Bell" and recs["three-mile-creek"]["raw"]["county"] == "Campbell"
    assert "stretch" not in recs["catron-creek"]
