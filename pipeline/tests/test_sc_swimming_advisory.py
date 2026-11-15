"""DES's map layer titled "Swimming Advisory" (SCDES Water Advisories layer 0): river and lake sites shown as DES's
undated listing, one marker a site (ingest/sc_des_advisories.py swim_records). Fixture: five of the 23 sites of the
2026-11-15 read, as returned (OBJECTID, Name, Station, point). No network."""
import copy
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import sc_des_advisories as A

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "sc"
T0, T1, T2 = "2026-11-15T15:00:00Z", "2026-11-15T16:00:00Z", "2026-11-15T17:00:00Z"


def layer():
    return json.loads((FIX / "swimming_advisory.json").read_text())


def feats(drop=()):
    d = layer()
    sf = A.safe_features(A.check_swim(d["layer"], d["count"]), "geometry", A.SWIM_FIELDS)
    return [f for f in sf if f["attributes"]["Station"] not in drop]


def by_station(recs):
    return {r["raw"]["station"]: r for r in recs}


def test_each_listed_site_is_one_record_at_its_own_point_with_no_date_of_des_invented():
    recs, state, n = A.swim_records(feats(), {}, T0)
    assert n == {"sites": 5, "without_point": 0} and len(recs) == 5
    r = by_station(recs)
    assert set(r) == {"R3-048", "R3-049", "R3-050", "R8-031", "R8-032"}
    # the two Granby Park sites and the two sites DES puts at one landing stay one record each
    assert r["R3-049"]["outfall_name"] == r["R3-050"]["outfall_name"] == "Granby Park"
    assert (r["R8-031"]["lat"], r["R8-031"]["lon"]) == (r["R8-032"]["lat"], r["R8-032"]["lon"]) == (32.744, -80.557)
    assert (r["R3-048"]["lat"], r["R3-048"]["lon"]) == (33.995, -81.053)
    for x in recs:
        assert x["source_id"] == "sc-des-freshwater-swim-advisories"
        assert x["event_type"] == "beach_advisory" and x["status"] == "advisory_active"
        assert x["started_at"] == T0 and x["time_precision"] == "poll" and x["ended_at"] is None
        assert x["reported_at"] is None and x["published_at"] is None and x["source_updated_at"] is None
        assert x["waterbody_text"] is None and x["coord_source"] == "station"
        assert x["raw"]["_point_extent_only"] is True and x["raw"]["_last_seen_in_source"] == T0
        assert "may have begun earlier" in x["raw"]["start_basis"]
        assert '"Swimming Advisory"' in x["advice_text"] and "no date and no status" in x["advice_text"]
        assert x["source_url"].endswith("/Water_Advisories/MapServer/0")
        assert len(str(x["lat"]).split(".")[1]) <= 3 and len(str(x["lon"]).split(".")[1]) <= 3
        text = json.dumps({k: x[k] for k in ("advice_text", "advice_window_basis", "raw")})
        assert not re.search(r"\b(safe|clean)\b", text, re.I)
    assert r["R3-048"]["source_record_id"] == "R3-048-20261115T1500"


def test_a_later_read_confirms_and_a_complete_read_without_a_site_ends_it_at_that_read():
    _, st, _ = A.swim_records(feats(), {}, T0)
    recs, st, _ = A.swim_records(feats(), {"swim": st}, T1)
    assert len(recs) == 5 and all(r["raw"]["_last_seen_in_source"] == T1 and r["started_at"] == T0 for r in recs)
    recs, st, _ = A.swim_records(feats(drop={"R3-048"}), {"swim": st}, T2)
    gone = by_station(recs)["R3-048"]
    assert gone["status"] == "advisory_lifted" and gone["ended_at"] == T2
    assert gone["raw"]["ended_at_precision"] == "poll" and "no longer listed" in gone["raw"]["end_basis"]
    assert gone["raw"]["_last_seen_in_source"] == T1                       # the end confirms nothing between
    assert all(r["status"] == "advisory_active" for k, r in by_station(recs).items() if k != "R3-048")


def test_a_site_listed_again_later_is_a_new_record_and_the_earlier_one_is_unchanged():
    _, st, _ = A.swim_records(feats(), {}, T0)
    recs1, st, _ = A.swim_records(feats(drop={"R3-048"}), {"swim": st}, T1)
    before = copy.deepcopy([r for r in recs1 if r["raw"]["station"] == "R3-048"][0])
    later = "2027-03-01T12:00:00Z"
    recs2, st, _ = A.swim_records(feats(), {"swim": st}, later)
    rows = [r for r in recs2 if r["raw"]["station"] == "R3-048"]
    assert len(rows) == 2
    old = [r for r in rows if r["source_record_id"] == before["source_record_id"]][0]
    new = [r for r in rows if r is not old][0]
    assert {k: old[k] for k in ("started_at", "ended_at", "lat", "lon", "status")} == \
        {k: before[k] for k in ("started_at", "ended_at", "lat", "lon", "status")}
    assert new["started_at"] == later and new["status"] == "advisory_active"


def test_a_read_after_an_unread_gap_opens_a_new_listing_period():
    _, st, _ = A.swim_records(feats(), {}, T0)
    recs, st, _ = A.swim_records(feats(), {"swim": st}, "2026-12-20T15:00:00Z")
    p = by_station(recs)["R3-048"]["raw"]["listed_periods"]
    assert [x["from"] for x in p] == [T0, "2026-12-20T15:00:00Z"]


def test_a_renamed_site_keeps_its_record_and_the_earlier_name():
    _, st, _ = A.swim_records(feats(), {}, T0)
    f = feats()
    next(x for x in f if x["attributes"]["Station"] == "R3-048")["attributes"]["Name"] = "Cayce Riverwalk Park"
    recs, _, _ = A.swim_records(f, {"swim": st}, T1)
    r = by_station(recs)["R3-048"]
    assert r["outfall_name"] == "Cayce Riverwalk Park" and len([x for x in recs if x["raw"]["station"] == "R3-048"]) == 1
    assert r["raw"]["revisions"] == [{"seen_at": T1, "field": "name", "was": "Cayce Riverwalk", "now": "Cayce Riverwalk Park"}]


@pytest.mark.parametrize("bad", ["cut_off", "error", "empty", "count", "field", "station", "not_json"])
def test_a_partial_failed_or_malformed_read_is_refused(bad):
    d = layer()
    js, cnt = d["layer"], d["count"]
    if bad == "cut_off":
        js["exceededTransferLimit"] = True
    elif bad == "error":
        js = {"error": {"code": 500, "message": "Unable to complete operation."}}
    elif bad == "empty":
        js["features"], cnt = [], {"count": 0}
    elif bad == "count":
        cnt = {"count": 23}                                    # the layer holds more than came back
    elif bad == "field":
        for f in js["features"]:
            f["attributes"]["SiteName"] = f["attributes"].pop("Name")
    elif bad == "station":
        js["features"][0]["attributes"]["Station"] = " "
    elif bad == "not_json":
        js = "<html>Service unavailable</html>"
    with pytest.raises(ValueError):
        A.check_swim(js, cnt)


class Resp:
    def __init__(self, js=None, text=""):
        self._js, self.text = js, text

    def raise_for_status(self):
        pass

    def json(self):
        if self._js is None:
            raise ValueError("not JSON")
        return self._js


def run_with(monkeypatch, tmp_path, swim_js, swim_count, at):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "STATE_PATH", tmp_path / "state.json")
    saved_raw = []
    monkeypatch.setattr(A, "save_raw", lambda name, body, ext: saved_raw.append(body))
    adv = json.loads((FIX / "advisories.json").read_text())
    page = ("<h2>HAB Watches &amp; Advisories</h2><table><tr><th>Advisory Level</th><th>Advisory Area</th>"
            "<th>Waterbody</th><th>Date Issued</th></tr><tr><td>Watch</td><td>Cedar Point Cove</td>"
            "<td>J. Strom Thurmond</td><td>10/16/2026</td></tr></table>")
    urls = []

    def fake_get(url, **k):
        urls.append(url)
        if "Water_Advisories" in url:
            return Resp(swim_count if "returnCountOnly" in url else swim_js)
        if "BW_Monitoring" in url:
            return Resp({"features": adv["beach"]})
        if "algal_hydro" in url:
            return Resp({"features": adv["hab"]})
        return Resp(text=page)
    monkeypatch.setattr(A.requests, "get", fake_get)
    rc = A.main(["--at", at])
    return rc, json.loads((tmp_path / "sc-des-freshwater-swim-advisories.json").read_text()), saved_raw, urls


def test_a_bad_read_keeps_every_held_site_and_marks_the_feed_not_ok(monkeypatch, tmp_path):
    d = layer()
    rc, out, _, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0)
    assert rc == 0 and out["ok"] is True and out["count"] == 5
    held = out["records"]
    state = json.loads((tmp_path / "state.json").read_text())["swim"]
    for js, cnt in ((dict(d["layer"], exceededTransferLimit=True), d["count"]),
                    (dict(d["layer"], features=d["layer"]["features"][:2]), d["count"]),
                    ({"error": {"code": 400}}, d["count"]),
                    (None, d["count"])):
        rc, out, _, _ = run_with(monkeypatch, tmp_path, js, cnt, T1)
        assert rc == 1 and out["ok"] is False and out["error"]
        assert out["records"] == held                                     # nothing lifted, greyed or dropped
        assert all(r["status"] == "advisory_active" and r["ended_at"] is None for r in out["records"])
        assert json.loads((tmp_path / "state.json").read_text())["swim"] == state
    # the next complete read picks the held sites up again, still from their first read
    rc, out, _, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T2)
    assert rc == 0 and out["ok"] is True
    assert all(r["started_at"] == T0 and r["raw"]["_last_seen_in_source"] == T2 for r in out["records"])


def test_only_the_needed_fields_are_asked_for_and_saved_rounded(monkeypatch, tmp_path):
    d = layer()
    for f in d["layer"]["features"]:
        f["attributes"].update(Contact="Pat Example", Phone="803-555-0142")   # a server that sends more than asked
    rc, out, raw, urls = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0)
    assert rc == 0
    swim_urls = [u for u in urls if "Water_Advisories" in u]
    assert swim_urls[0] == A.SWIM_LAYER and "outFields=OBJECTID,Name,Station&" in A.SWIM_LAYER
    assert not any(re.search(r"outFields=\*|Contact|Phone|PicURL|PicNAME", u) for u in swim_urls)
    body = json.loads(raw[0])
    assert {k for f in body["swim"] for k in f["attributes"]} == {"OBJECTID", "Name", "Station"}
    assert all(len(str(f["geometry"]["x"]).split(".")[1]) <= 3 for f in body["swim"])
    blob = json.dumps(out) + raw[0] + (tmp_path / "state.json").read_text()
    assert "Pat Example" not in blob and "555-0142" not in blob


def _status(recs, w, now):
    from build import status as S
    from tests.test_status import TEST_RULES
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / "sc-des-freshwater-swim-advisories.json").write_text(json.dumps(
        {"source_id": "sc-des-freshwater-swim-advisories", "ok": True, "last_ok_at": T0, "meta": {},
         "records": copy.deepcopy(recs)}))
    st, _ = S.build(now=now, write=False, events_dir=d, waters={w["slug"]: w}, outfalls=[], registry={},
                    reaches={}, flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return st


def test_a_site_is_a_marker_and_never_colours_its_small_lake_whole(monkeypatch):
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    recs, _, _ = A.swim_records([f for f in feats() if f["attributes"]["Station"] == "R3-048"], {}, T0)
    lat, lon = recs[0]["lat"], recs[0]["lon"]
    box = {"type": "Polygon", "coordinates": [[[lon - .05, lat - .05], [lon + .05, lat - .05], [lon + .05, lat + .05],
                                               [lon - .05, lat + .05], [lon - .05, lat - .05]]]}
    w = {"slug": "lake-example-sc", "name": "Lake Example", "kind": "reservoir", "state": "SC", "area_km2": 5,
         "bbox": [lon - .05, lat - .05, lon + .05, lat + .05], "geometry": box}
    st = _status(recs, w, datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert st["waters"]["lake-example-sc"]["status"] == "grey"           # never the whole lake
    pts = {a["event_id"]: a for a in st["advisory_points"]}
    assert pts[recs[0]["event_id"]]["status"] == "red"                  # the site's own marker, DES's listing
    assert recs[0]["event_id"] in st["waters"]["lake-example-sc"]["events"]   # listed on the water's page


def test_an_end_seen_months_later_never_colours_the_unread_months(monkeypatch):
    from build import status as S
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    one = [f for f in feats() if f["attributes"]["Station"] == "R3-048"]
    _, st, _ = A.swim_records(one, {}, T0)
    recs, _, _ = A.swim_records(feats(drop={"R3-048"}), {"swim": st}, "2027-03-01T12:00:00Z")
    rec = by_station(recs)["R3-048"]
    ivs = S.event_intervals(rec, "SC", datetime(2027, 3, 2, tzinfo=timezone.utc), None, TEST_RULES)
    red = [i for i in ivs if i["color"] == "red"]
    assert red and max(i["end"] for i in red) == datetime(2026, 11, 29, 15, tzinfo=timezone.utc)   # 14 days after
    assert not [i for i in ivs if i["color"] == "red" and i["start"] >= datetime(2026, 11, 29, 15, tzinfo=timezone.utc)]


def test_the_register_and_source_file_name_the_feed():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "sc.json").read_text())["channels"]}
    row = reg["sc-des-freshwater-swim-advisories"]
    assert row["feed_source_id"] == "sc-des-freshwater-swim-advisories" and row["channel_kind"] == "feed"
    assert row["unmonitored_reason"] == "feed_ingested" and row["barrier"] is None
    assert "Swimming Advisory" in row["note"]
    src = (ROOT / "data" / "sources" / "sc-des-freshwater-swim-advisories.yaml").read_text()
    assert 'id: "sc-des-freshwater-swim-advisories"' in src and "outFields OBJECTID, Name, Station" in src


def test_the_state_text_says_the_sites_are_shown_as_des_listing():
    t = (ROOT / "research" / "sc" / "state-text.md").read_text()
    assert "not coloured here" not in t and "is not shown here" not in t
    assert 'titled "Swimming Advisory"' in t and "23 river and lake sites" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I)
