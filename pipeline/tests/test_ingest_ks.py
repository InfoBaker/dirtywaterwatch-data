"""Kansas: Leavenworth's overflow pages (ingest/ks_leavenworth_sso.py), KDHE's stream advisories
(ingest/ks_kdhe_stream_advisories.py) and HAB layer (ingest/ks_kdhe_hab.py), the county time-zone rule
(pipeline/zones.py kansas_zone, 49 CFR 71.7(d)), the operator rows, the register, the rules row and the state text.
Fixtures are synthetic, shaped on the real fetches of 2026-11-14 (Example names, placeholder house and telephone
numbers). No network."""
import json
import re
from pathlib import Path

from ingest import ks_kdhe_hab as H
from ingest import ks_kdhe_stream_advisories as A
from ingest import ks_leavenworth_sso as L
import zones

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "ks"
AT = "2026-11-14T18:00:00Z"
PERSONAL = ["1234 Example", "5678 Sample", "913) 555-0199", "555-0199"]


# ---------------------------------------------------------------- Leavenworth

def leavenworth():
    pages = {f"/publicworks/page/{f.stem}": f.read_text() for f in sorted((FIX / "leavenworth").glob("*.html"))}
    recs, stats = L.run(pages, [], AT)
    return {r["outfall_name"]: r for r in recs}, stats


def test_leavenworth_notified_time_stop_time_volume_creek_and_advice():
    recs, stats = leavenworth()
    r = recs["Example Court"]
    assert r["started_at"] == "2020-05-27T15:50:00-05:00" and r["time_precision"] == "minute"
    assert r["raw"]["start_kind"] == "notified" and r["raw"]["start_is_upper_bound"] is True
    assert r["ended_at"] == "2020-05-27T18:00:00-05:00" and r["raw"]["ended_at_precision"] == "minute"
    assert r["volume_gal"] == 2500 and r["estimate_flag"] == "estimated" and r["waterbody_text"] == "Five-Mile Creek"
    assert "until testing is done and signs are removed" in r["advice_text"] and r["status"] == "unknown"
    assert r["discharger_id"] == "ks-leavenworth" and r["raw"]["county"] == "Leavenworth County"
    assert r["raw"]["time_zone"] == "America/Chicago" and stats["pages"] == 3


def test_leavenworth_time_without_am_pm_is_day_precision_and_an_unnamed_creek_is_unplaced():
    r = leavenworth()[0]["Sample St"]
    assert r["started_at"] == "2026-04-27" and r["time_precision"] == "day" and r["raw"]["start_kind"] is None
    assert r["ended_at"] == "2026-04-27T11:30:00-05:00"
    assert r["waterbody_text"] is None and r["raw"]["reached_water"] is True and r["volume_gal"] == 9000


def test_leavenworth_prison_lift_station_is_not_the_citys_and_numbers_are_dropped():
    recs, _ = leavenworth()
    r = recs["1200 block of Example"]
    assert r["discharger_id"] is None and "federal prison" in r["raw"]["system_note"]
    assert r["started_at"] == "2025-10-23"
    blob = json.dumps(list(recs.values()))
    for p in PERSONAL:
        assert p not in blob


def _page(title, body):
    return (f'<html><body><h1 id="page-title">{title}</h1><div class="region region-content"><p>{body}</p></div>'
            '<ul class="menu jquerymenu"></ul></body></html>')


def test_leavenworth_end_clause_date_and_record_ids_carry_no_house_number():
    h = _page("Sanitary Sewer Overflow Reported on May 27, 2020 at 1234 Example Court",
              "At 3:50 p.m. May 27, 2020, staff were notified of sewage in Five-Mile Creek. The overflow stopped May 29 "
              "at 4:00 p.m.")
    r = L.record("/publicworks/page/sanitary-sewer-overflow-reported-may-27-2020-1234-example-court", h, AT)
    assert r["ended_at"] == "2020-05-29T16:00:00-05:00"
    assert "1234" not in r["source_record_id"] and r["raw"]["_placement"] == "named_water_only"
    assert "page_text" not in r["raw"]


def test_leavenworth_refused_page_is_a_failed_run(monkeypatch, tmp_path):
    import common
    import requests

    class Resp:
        def __init__(self, code, text=""):
            self.status_code, self.text, self.ok = code, text, code == 200

        def raise_for_status(self):
            if self.status_code != 200:
                raise requests.HTTPError(str(self.status_code))
    idx = '<a href="/publicworks/page/2026-sanitary-sewer-overflow-transparency-report">2026</a>'
    yr = '<a href="/publicworks/page/sanitary-sewer-overflow-reported-april-27-2026-1234-example-st">x</a>'
    pages = {L.INDEX: Resp(200, idx), L.BASE + "/publicworks/page/2026-sanitary-sewer-overflow-transparency-report":
             Resp(200, yr)}
    monkeypatch.setattr(L.requests, "get", lambda url, **k: pages.get(url, Resp(403)))
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(L.SOURCE_ID, [{"event_id": "x", "raw": {}}])
    assert L.main([]) == 1
    out = json.loads((tmp_path / f"{L.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["records"] == [{"event_id": "x", "raw": {}}]


# ---------------------------------------------------------------- KDHE stream advisories

def test_stream_advisory_pair_is_kdhes_window_one_record_per_water_and_an_orphan_rescission_makes_no_record():
    recs, stats = A.run((FIX / "kdhe_feed.xml").read_bytes(), [], AT)
    by = {r["source_record_id"]: r for r in recs}
    assert set(by) == {"9101-examplecreek", "9101-sampleriver", "9104-manurecreek"}
    r, s2 = by["9101-examplecreek"], by["9101-sampleriver"]
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-01-29T15:00:00-06:00" and r["ended_at"] == "2026-02-03T10:00:00-06:00"
    assert r["waterbody_text"] == "Example Creek" and r["raw"]["county"] == "Shawnee County"
    assert r["raw"]["cause"] == "sewage" and r["raw"]["advisory_extent"] == "named_water"
    assert r["raw"]["_placement"] == "named_water_only" and r["raw"]["time_zone"] == "America/Chicago"
    assert r["raw"]["lifted_by"]["link"].endswith("aid=9102") and r["raw"]["ended_at_precision"] == "minute"
    assert s2["waterbody_text"] == "Sample River" and s2["status"] == "advisory_lifted"   # the description names it
    m = by["9104-manurecreek"]
    assert m["status"] == "advisory_active" and m["raw"]["cause"] == "livestock waste"
    assert m["raw"]["_last_seen_in_source"] == AT and m["source_updated_at"] is None
    assert stats["rescissions_without_issue"] == 1 and stats["issues"] == 2


def _feed(*items):
    body = "".join(f"<item><title>{t}</title><link>https://www.kdhe.ks.gov/CivicAlerts.aspx?aid={a}</link>"
                   f"<pubDate>{d}</pubDate><description>{x}</description></item>" for t, a, d, x in items)
    return f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode()


def test_partial_and_county_scoped_rescissions_and_the_mountain_county_clock():
    feed = _feed(("Stream Advisory Issued for Alpha Creek and Beta River in Shawnee County", "1", "Mon, 02 Nov 2026 "
                  "09:00:00 -0600", "KDHE issued a stream advisory after a sewage discharge."),
                 ("Stream Advisory Issued for Alpha Creek in Leavenworth County", "2", "Mon, 02 Nov 2026 10:00:00 -0600",
                  "Sewage."),
                 ("Stream Advisory Issued for Gamma Creek in Sherman County", "3", "Mon, 02 Nov 2026 11:00:00 -0600",
                  "Wastewater."),
                 ("Stream Advisory Rescinded for Alpha Creek in Shawnee County", "4", "Wed, 04 Nov 2026 09:00:00 -0600",
                  "Rescinded."))
    by = {r["source_record_id"]: r for r in A.run(feed, [], AT)[0]}
    assert by["1-alphacreek"]["status"] == "advisory_lifted" and by["1-betariver"]["status"] == "advisory_active"
    assert by["2-alphacreek"]["status"] == "advisory_active"             # another county's Alpha Creek stands
    assert by["3-gammacreek"]["raw"]["time_zone"] == "America/Denver"


def test_a_feed_that_no_longer_holds_the_issue_does_not_reconfirm():
    first, _ = A.run((FIX / "kdhe_feed.xml").read_bytes(), [], AT)
    later = _feed(("Boil Water Advisory Issued for the City of Example", "9200", "Mon, 08 Feb 2027 09:00:00 -0600", "x"))
    recs, stats = A.run(later, first, "2027-02-09T18:00:00Z")
    m = {r["source_record_id"]: r for r in recs}["9104-manurecreek"]
    assert m["status"] == "advisory_active" and m["raw"]["_last_seen_in_source"] == AT     # not moved to February
    later2 = _feed(("Stream Advisory Rescinded for Manure Creek in Example County", "9106",
                    "Mon, 02 Nov 2026 09:00:00 -0600", "Rescinded."))
    recs2, stats2 = A.run(later2, first, "2026-11-15T18:00:00Z")
    by = {r["source_record_id"]: r for r in recs2}
    assert by["9104-manurecreek"]["status"] == "advisory_lifted" and stats2["open"] == 0


def test_raw_save_keeps_only_stream_advisory_releases():
    saved = json.loads(A.safe_feed((FIX / "kdhe_feed.xml").read_bytes()))
    assert not [i for i in saved["items"] if "Boil Water" in i["title"]] and len(saved["items"]) == 4


# ---------------------------------------------------------------- KDHE HAB layer

def test_hab_lakes_open_at_the_poll_change_level_and_lift_at_the_poll():
    p1 = json.loads((FIX / "hab_poll1.json").read_text())
    recs, s1 = H.run(p1, [], AT)
    by = {r["raw"]["waterbody_id"]: r for r in recs}
    assert set(by) == {"LM9001", "LM9002"} and s1["opened"] == 2      # Lift is not an advisory
    a = by["LM9001"]
    assert a["event_type"] == "hab_advisory" and a["status"] == "advisory_active"
    assert a["started_at"] == AT and a["time_precision"] == "poll" and a["raw"]["status_date"] == "2026-10-30T17:00:00Z"
    assert a["waterbody_text"] == "Example County State Fishing Lake" and a["raw"]["points_on_layer"] == 2
    assert (a["lat"], a["lon"]) == (38.321, -96.985) and a["raw"]["time_zone"] == "America/Chicago"
    assert by["LM9002"]["raw"]["time_zone"] == "America/Denver"           # a point in Hamilton County
    later = "2026-11-21T18:00:00Z"
    recs2, s2 = H.run(json.loads((FIX / "hab_poll2.json").read_text()), recs, later)
    by2 = {r["raw"]["waterbody_id"]: r for r in recs2}
    assert by2["LM9001"]["raw"]["kdhe_level"] == "Watch" and len(by2["LM9001"]["raw"]["levels"]) == 2
    assert by2["LM9001"]["started_at"] == AT and by2["LM9001"]["raw"]["_last_seen_in_source"] == later
    b = by2["LM9002"]
    assert b["status"] == "advisory_lifted" and b["ended_at"] == later and b["raw"]["ended_at_precision"] == "poll"
    assert s2 == {"listed": 1, "opened": 0, "confirmed": 1, "lifted": 1, "open": 1}


def test_hab_malformed_answer_is_a_failed_read_never_a_lift(tmp_path, monkeypatch):
    import common
    import pytest
    recs, _ = H.run(json.loads((FIX / "hab_poll1.json").read_text()), [], AT)
    for bad in ({}, {"error": {"code": 500}}, {"features": [], "exceededTransferLimit": True},
                {"features": [{"attributes": {"STATUS": "Closed?", "WATERBODY_ID": "X"}}]}):
        with pytest.raises(ValueError):
            H.run(bad, recs, "2026-11-21T18:00:00Z")
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(H.SOURCE_ID, recs)
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert H.main(["--file", str(bad)]) == 1
    out = json.loads((tmp_path / f"{H.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and {r["status"] for r in out["records"]} == {"advisory_active"}
    empty, s = H.run({"features": []}, recs, "2026-11-21T18:00:00Z")            # a valid empty list lifts
    assert s["lifted"] == 2


def test_hab_same_day_respell_keeps_both_and_saved_points_are_rounded():
    p1 = json.loads((FIX / "hab_poll1.json").read_text())
    r1, _ = H.run(p1, [], "2026-11-14T08:00:00Z")
    r2, _ = H.run({"features": []}, r1, "2026-11-14T09:00:00Z")
    r3, _ = H.run(p1, r2, "2026-11-14T10:00:00Z")
    ids = [r["event_id"] for r in r3 if r["raw"]["waterbody_id"] == "LM9001"]
    assert len(ids) == 2 and len(set(ids)) == 2
    g = H.rounded(p1)["features"][0]["geometry"]
    assert g == {"x": -96.985, "y": 38.321}


# ---------------------------------------------------------------- the time-zone rule

def test_kansas_mountain_counties_by_name_and_by_point():
    for c in ("Sherman County", "Wallace", "GREELEY", "Hamilton County"):
        assert zones.kansas_zone(county=c) == "America/Denver"
    for c in ("Leavenworth County", "Logan", "Wichita County", "Kearny"):
        assert zones.kansas_zone(county=c) == "America/Chicago"
    assert zones.zone_for("KS", 39.35, -101.70) == "America/Denver"        # Goodland, Sherman County
    assert zones.zone_for("KS", 38.48, -101.36) == "America/Chicago"       # Leoti, Wichita County (Central)
    assert zones.zone_for("KS", 38.87, -101.75) == "America/Denver"        # Sharon Springs area, Wallace County
    assert zones.zone_for("KS", 37.98, -101.75) == "America/Denver"        # Syracuse, Hamilton County
    assert zones.zone_for("KS", 39.31, -94.92) == "America/Chicago"        # Leavenworth
    assert zones.zone_for("KS") == "America/Chicago"


def test_other_states_zones_unchanged():
    assert zones.zone_for("NE", 41.13, -100.77) == "America/Chicago"       # North Platte, Lincoln County
    assert zones.zone_for("MO", 39.1, -94.6) == "America/Chicago"
    assert zones.zone_for("CO", 39.7, -104.9) == "America/Denver"


# ---------------------------------------------------------------- operators, register, rules, text

def ks_ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "KS"]


def test_operator_rows_hold_every_permit_once_with_research_ids_as_aliases():
    ops = ks_ops()
    permits = [p for r in ops for p in r["npdes_permits"]]
    assert len(permits) == len(set(permits))
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "KS"}
    assert plants <= set(permits)
    alias = {a: r for r in ops for a in r.get("aliases") or []}
    ug = alias["ks-kansas-city-ks0038563"]
    assert ug["name"] == "Unified Government of Wyandotte County/Kansas City, Kansas" and ug["legal_form"] == "city"
    assert ug["kind"] == "cso" and ug["outfall_count"] == 48 and len([r for r in ops if "Unified" in r["name"]]) == 1
    assert alias["ks-leavenworth"]["npdes_permits"] == ["KS0036366"]
    assert {alias["ks-topeka-ks0042722"]["kind"], alias["ks-atchison-ks0039128"]["kind"]} == {"cso"}


def test_an_influent_connection_is_not_counted_as_an_outfall():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ko", ROOT / "scripts" / "add_ks_operators.py")
    ko = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ko)
    assert ko.influent_only({"limit_set_names": ["Influent to Collection System from Example Foods"]})
    assert not ko.influent_only({"limit_set_names": ["Influent / Effluent"]})
    alias = {a: r for r in ks_ops() for a in r.get("aliases") or []}
    sh = next(r for r in ks_ops() if "KS0095711" in r["npdes_permits"])
    assert sh["outfall_count"] == 1


def test_register_has_the_kdhe_report_per_operator_and_the_feeds():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "ks.json").read_text())["channels"]}
    for r in ks_ops():
        row = reg[f"{r['id']}-kdhe-report"]
        assert "K.A.R. 28-16-27" in row["legal_basis"] and row["barrier"] == "no_web_page"
    assert reg["ks-leavenworth-transparency-reports"]["feed_source_id"] == "ks-leavenworth-sso-transparency"
    assert reg["ks-kdhe-stream-advisories"]["feed_source_id"] == "ks-kdhe-stream-advisories"
    assert reg["ks-kdhe-hab-status"]["feed_source_id"] == "ks-kdhe-hab-status"
    assert reg["ks-kdhe-hab-page"]["barrier"] == "bot_wall" and reg["ks-kdhe-spills-dasc"]["records"] is False
    assert len([k for k in reg if "-cso-permit-notice-" in k]) == 3


def test_rules_row():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ks = rules["red"]["by_state"]["KS"]
    assert ks["hours"] is None and "K.A.R. 28-16-27" in ks["source"] and "49 CFR 71.7(d)" in ks["source"]
    assert not re.search(r"\b(safe|clean)\b", ks["basis"], re.I)


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "ks" / "state-text.md").read_text()
    assert t.startswith("---\nstate: KS\nname: Kansas\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "28 pages from April 2020 to April 2026" in t and "15 lakes, 7 under a Warning and 8 under a Watch" in t
    assert "Sherman, Wallace, Greeley and Hamilton counties keep Mountain time" in t


def check_missing_waters(d: dict, nat: dict) -> None:
    """The invariants of research/ks/receiving-waters-missing.json, true as the state build writes it and after a water
    batch moves some or all of its names into `resolved` (re-review P2-6): no pending name is one the national list
    holds (unless the row itself says resolved), one row per name and county, and each resolved name has its records."""
    def k(n):
        s = re.sub(r"^\s*(?:trib(?:utary|\.)?\s+to|tributary of)\s+", "", (n or "").lower())
        return re.sub(r"\br\.?$", "river", re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+tributary$", "", s))).replace(" ", "")
    held = {k(n) for w in nat["states"]["KS"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows, resolved = d["rows"], d.get("resolved") or []
    rows = rows if isinstance(rows, list) else []
    assert d["state"] == "KS" and d["waters"] == len(rows) and len(rows) + len(resolved) > 0
    for r in rows:
        assert k(r["name"]) not in held or r.get("resolved")
    keys = [(r["name"], r["county"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in resolved:
        assert r.get("name") and r.get("slugs"), r


def _batch(d: dict, share: float) -> dict:
    """The file as a water batch leaves it: the first share of its names moved into `resolved` with a record each."""
    rows = list(d["rows"])
    n = round(len(rows) * share)
    done = [{"name": r["name"], "reports": r["reports"], "slugs": [f"{k}-example-ks" for k in [r["name"].lower()]],
             "how": "built from NHD"} for r in rows[:n]]
    return {**d, "rows": rows[n:], "waters": len(rows) - n, "resolved": done}


def test_missing_waters_list_rows_are_unique_and_unlisted():
    d = json.loads((ROOT / "research" / "ks" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())
    check_missing_waters(d, nat)
    if not d.get("resolved"):                                  # before the batch: the same holds part- and fully-done
        check_missing_waters(_batch(d, 0.5), nat)
        check_missing_waters(_batch(d, 1.0), nat)


# ---------------------------------------------------------------- re-review fixes (2026-11-15)

def _hab_main(tmp_path, monkeypatch, recs, doc):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(H.SOURCE_ID, recs)
    f = tmp_path / "answer.json"
    f.write_text(json.dumps(doc))
    code = H.main(["--file", str(f)])
    return code, json.loads((tmp_path / f"{H.SOURCE_ID}.json").read_text())


def test_hab_rows_without_identity_or_point_are_a_failed_read_through_main(tmp_path, monkeypatch):
    """Re-review P1-1: a row the parser would drop must not lift its lake."""
    recs, _ = H.run(json.loads((FIX / "hab_poll1.json").read_text()), [], AT)
    good = {"attributes": {"STATUS": "Watch", "WATERBODY_ID": "LM9001", "WATERBODY_NAME": "Example Lake"},
            "geometry": {"x": -96.985, "y": 38.321}}
    for bad in ([{"attributes": {"STATUS": "Watch"}}],                                    # no identity
                [good, {"attributes": {"STATUS": "Warning", "WATERBODY_ID": "LM9002"}}],   # no point
                [good, {"attributes": {"STATUS": "Warning", "WATERBODY_ID": "LM9002"}, "geometry": {"x": "?", "y": 1}}],
                [good, {"attributes": {"STATUS": "Warning", "WATERBODY_ID": "LM9002"},
                        "geometry": {"x": -80.0, "y": 38.0}}],                              # outside Kansas
                [good, "not a row"], [good, {"geometry": {"x": -96.9, "y": 38.3}}]):
        code, out = _hab_main(tmp_path, monkeypatch, recs, {"features": bad})
        assert code == 1 and out["ok"] is False
        assert {r["status"] for r in out["records"]} == {"advisory_active"} and len(out["records"]) == 2


def test_hab_conflicting_duplicate_rows_keep_the_more_severe_level():
    doc = {"features": [
        {"attributes": {"STATUS": "Watch", "WATERBODY_ID": "LM9001", "WATERBODY_NAME": "Example Lake"},
         "geometry": {"x": -96.985, "y": 38.321}},
        {"attributes": {"STATUS": "Warning", "WATERBODY_ID": "LM9001", "WATERBODY_NAME": "Example Lake"},
         "geometry": {"x": -96.98, "y": 38.32}},
        {"attributes": {"STATUS": "Lift", "WATERBODY_ID": "LM9001", "WATERBODY_NAME": "Example Lake"},
         "geometry": {"x": -96.98, "y": 38.32}}]}
    recs, s = H.run(doc, [], AT)
    assert len(recs) == 1 and recs[0]["raw"]["kdhe_level"] == "Warning" and recs[0]["status"] == "advisory_active"
    assert recs[0]["raw"]["conflicting_levels"] == ["Warning", "Watch"]


def test_hab_lift_after_an_outage_does_not_colour_the_unread_gap():
    """Re-review P1-2: opened in January, no read until June: the colour stops 14 days after the last listing read."""
    from datetime import datetime, timezone
    from build import status as S
    p1 = json.loads((FIX / "hab_poll1.json").read_text())
    jan, jun = "2026-01-01T12:00:00Z", "2026-06-01T12:00:00Z"
    recs, _ = H.run(p1, [], jan)
    recs, _ = H.run({"features": []}, recs, jun)
    r = next(x for x in recs if x["raw"]["waterbody_id"] == "LM9001")
    assert r["status"] == "advisory_lifted" and r["ended_at"] == jun and "sampled_at" not in r
    now = datetime(2026, 6, 2, tzinfo=timezone.utc)
    ivs = S.event_intervals(r, "KS", now)
    red = [iv for iv in ivs if iv["rule"] == "advisory_active"]
    assert len(red) == 1 and red[0]["end"] == datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    assert all(iv["end"] and iv["end"] <= datetime(2026, 6, 1, 12, tzinfo=timezone.utc) for iv in ivs)
    assert {iv["rule"] for iv in ivs} <= {"advisory_active", "not_reconfirmed"}
    # an old saved record without the flag (the state branch's format) gets it at the next read
    old = json.loads(json.dumps(r))
    old["raw"].pop("_poll_confirmed")
    again, _ = H.run({"features": []}, [old], "2026-06-01T13:00:00Z")
    assert again[0]["raw"]["_poll_confirmed"] is True


def test_hab_poll_flag_leaves_other_states_aging_unchanged():
    """The aging branch is keyed on raw._poll_confirmed: a record without it (another state's poll advisory) keeps the
    state branch's intervals."""
    from datetime import datetime, timezone
    from build import status as S
    ev = {"event_id": "x", "source_id": "zz-example", "event_type": "hab_advisory", "status": "advisory_lifted",
          "started_at": "2026-01-01T12:00:00Z", "ended_at": "2026-06-01T12:00:00Z", "time_precision": "poll",
          "raw": {"ended_at_precision": "poll", "_last_seen_in_source": "2026-01-01T12:00:00Z"}}
    ivs = S.event_intervals(ev, "WA", datetime(2026, 6, 2, tzinfo=timezone.utc))
    assert len(ivs) == 1 and ivs[0]["end"] == datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def _line(slug, name, st, coords, kind="river"):
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return slug, {"slug": slug, "name": name, "kind": kind, "state": st, "source": "nhd", "gnis_id": "1",
                  "bbox": [min(xs), min(ys), max(xs), max(ys)], "geometry": {"type": "LineString", "coordinates": coords}}


def _mo_ks_build(tmp_path, feeds: dict, waters: dict, now="2026-11-03T12:00:00Z"):
    """A build with Missouri and Kansas counted live (they are not yet; the rules are the same once they are)."""
    from datetime import datetime
    from build import status as S
    d = tmp_path / "events"
    d.mkdir(exist_ok=True)
    for sid, rr in feeds.items():
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "last_ok_at": now, "meta": {},
                                                   "records": rr}))
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    rules["live_states"] = list(rules["live_states"]) + ["KS", "MO"]
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    st, _ = S.build(now=datetime.fromisoformat(now.replace("Z", "+00:00")), write=False, events_dir=d, waters=waters,
                    outfalls=[], registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
    return st


def test_every_named_water_is_placed_and_a_kdhe_river_advisory_gets_a_cited_point_in_its_county(tmp_path):
    """Re-review P1-3: KC's post naming Rock Creek and the Missouri River is placed on both; KDHE's advisory for a creek
    gets a marker on the creek's mapped line inside the county it names, never on the namesake in another county; an
    advisory whose water has no line in its county, and one whose water has no record, stay listed."""
    from ingest import mo_kc_water_news as K
    feed = _feed(("Stream Advisory Issued for Example Creek in Shawnee County", "1", "Mon, 02 Nov 2026 09:00:00 -0600",
                  "KDHE issued a stream advisory after a sewage discharge."),
                 ("Stream Advisory Issued for Sample Creek in Shawnee County", "2", "Mon, 02 Nov 2026 10:00:00 -0600",
                  "Sewage."),
                 ("Stream Advisory Issued for Nowhere Creek in Shawnee County", "3", "Mon, 02 Nov 2026 11:00:00 -0600",
                  "Sewage."))
    ks, _ = A.run(feed, [], "2026-11-02T18:00:00Z")
    kc, _ = K.run([(ROOT / "pipeline" / "tests" / "fixtures" / "mo" / "kc_feed.xml").read_bytes()], [],
                  "2026-11-02T18:00:00Z")
    waters = dict([_line("example-creek-ks", "Example Creek", "KS", [[-95.8, 39.0], [-95.7, 39.05]]),
                   _line("example-creek-johnson-ks", "Example Creek", "KS", [[-94.9, 38.8], [-94.8, 38.85]]),
                   ("sample-creek-ks", {"slug": "sample-creek-ks", "name": "Sample Creek", "kind": "river", "state": "KS",
                                        "bbox": [-95.8, 39.0, -95.7, 39.05]}),            # a box, no line
                   _line("rock-creek-mo", "Rock Creek", "MO", [[-94.45, 39.10], [-94.40, 39.12]]),
                   _line("missouri-river-mo", "Missouri River", "MO", [[-94.6, 39.11], [-94.3, 39.15]])])
    st = _mo_ks_build(tmp_path, {A.SOURCE_ID: ks, K.SOURCE_ID: kc}, waters)
    pl = st["placements"]
    assert sorted(pl[f"{K.SOURCE_ID}:9004"]["water_slugs"]) == ["missouri-river-mo", "rock-creek-mo"]
    ex = pl[f"{A.SOURCE_ID}:1-examplecreek"]
    assert ex["water_slugs"] == ["example-creek-ks"]
    pts = {p["event_id"]: p for p in st["advisory_points"]}
    p = pts[f"{A.SOURCE_ID}:1-examplecreek"]
    assert p["status"] == "red" and (p["lat"], p["lon"]) == (39.0, -95.8)
    assert "inside Shawnee County" in p["point_basis"] and "NHDPlus" in p["point_basis"]
    assert f"{A.SOURCE_ID}:2-samplecreek" not in pts                          # no line: listed on its water only
    assert pl[f"{A.SOURCE_ID}:2-samplecreek"]["water_slugs"] == ["sample-creek-ks"]
    assert f"{A.SOURCE_ID}:3-nowherecreek" in {e["event_id"] if isinstance(e, dict) else e
                                                for e in st["unplaced_events"]}


def test_kdhe_confirms_only_while_its_own_release_is_in_the_feed_and_reconciles_revisions():
    """Re-review P1-4."""
    issue = ("Stream Advisory Issued for Example Creek in Shawnee County", "50", "Mon, 02 Nov 2026 09:00:00 -0600",
             "KDHE issued a stream advisory after a sewage discharge.")
    older = ("Stream Advisory Rescinded for Other Creek in Example County", "40", "Mon, 26 Oct 2026 09:00:00 -0600", "x")
    first, _ = A.run(_feed(issue, older), [], "2026-11-02T18:00:00Z")
    # the issue is gone; an unrelated older item remains: no confirmation
    recs, _ = A.run(_feed(older), first, "2026-11-20T18:00:00Z")
    r = {x["source_record_id"]: x for x in recs}["50-examplecreek"]
    assert r["status"] == "advisory_active" and r["raw"]["_last_seen_in_source"] == "2026-11-02T18:00:00Z"
    # repeated unchanged reads are idempotent
    again, _ = A.run(_feed(issue, older), first, "2026-11-02T19:00:00Z")
    again2, _ = A.run(_feed(issue, older), again, "2026-11-02T20:00:00Z")
    assert len(again2) == 1 and again2[0]["started_at"] == first[0]["started_at"]
    # KDHE revises the release: Sample Creek in Douglas County, a later pubDate
    rev = ("Stream Advisory Issued for Sample Creek in Douglas County", "50", "Tue, 03 Nov 2026 09:00:00 -0600",
           "KDHE issued a stream advisory after a wastewater discharge.")
    recs, stats = A.run(_feed(rev), first, "2026-11-03T18:00:00Z")
    by = {x["source_record_id"]: x for x in recs}
    assert by["50-examplecreek"]["status"] == "advisory_lifted" and by["50-examplecreek"]["raw"]["revised_out"] is True
    assert by["50-examplecreek"]["ended_at"] == "2026-11-03T18:00:00Z"
    assert by["50-examplecreek"]["raw"]["ended_at_precision"] == "poll"
    s = by["50-samplecreek"]
    assert s["status"] == "advisory_active" and s["raw"]["county"] == "Douglas County" and stats["revised_out"] == 1
    # the same water, the county and date revised: the earliest publication stays the start
    rev2 = ("Stream Advisory Issued for Example Creek in Douglas County", "50", "Wed, 04 Nov 2026 09:00:00 -0600", "x")
    recs2, _ = A.run(_feed(rev2), first, "2026-11-04T18:00:00Z")
    e = {x["source_record_id"]: x for x in recs2}["50-examplecreek"]
    assert e["raw"]["county"] == "Douglas County" and e["started_at"] == "2026-11-02T09:00:00-06:00"
    assert e["raw"]["publication_times_seen"] == ["2026-11-02T09:00:00-06:00", "2026-11-04T09:00:00-06:00"]


def test_a_county_less_rescission_lifts_only_when_one_county_holds_the_water():
    two = _feed(("Stream Advisory Issued for Alpha Creek in Shawnee County", "1", "Mon, 02 Nov 2026 09:00:00 -0600", "s"),
                ("Stream Advisory Issued for Alpha Creek in Riley County", "2", "Mon, 02 Nov 2026 10:00:00 -0600", "s"),
                ("Stream Advisory Rescinded for Alpha Creek", "3", "Wed, 04 Nov 2026 09:00:00 -0600", "Rescinded."))
    recs, stats = A.run(two, [], AT)
    assert {r["status"] for r in recs} == {"advisory_active"} and stats["rescissions_ambiguous"] == 1
    one = _feed(("Stream Advisory Issued for Alpha Creek in Shawnee County", "1", "Mon, 02 Nov 2026 09:00:00 -0600", "s"),
                ("Stream Advisory Rescinded for Alpha Creek", "3", "Wed, 04 Nov 2026 09:00:00 -0600", "Rescinded."))
    recs, stats = A.run(one, [], AT)
    assert [r["status"] for r in recs] == ["advisory_lifted"] and stats["rescissions_ambiguous"] == 0


def test_leavenworth_old_ids_and_addresses_migrate_to_one_record_per_page_through_main(tmp_path, monkeypatch):
    """Re-review P1-8 and P1-9: a save with the earlier, house-numbered identifier and page address, plus the page read
    again: one record, no house number anywhere, the year page as the citation; twice over, nothing changes."""
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    path = "/publicworks/page/sanitary-sewer-overflow-reported-may-27-2020-1234-example-court"
    h = _page("Sanitary Sewer Overflow Reported on May 27, 2020 at 1234 Example Court",
              "At 3:50 p.m. May 27, 2020, staff were notified of sewage in Five-Mile Creek.")
    old = L.record(path, h, "2026-11-01T00:00:00Z", None)
    old["source_record_id"] = "sanitary-sewer-overflow-reported-may-27-2020-1234-example-court"
    old["event_id"] = f"{L.SOURCE_ID}:{old['source_record_id']}"
    old["source_url"] = L.BASE + path
    old["raw"]["page_text"] = "At 1234 Example Court, call 913-555-0199."
    old["raw"].pop("cited_page")
    old["raw"]["first_seen_at"] = "2026-11-01T00:00:00Z"
    (tmp_path / f"{L.SOURCE_ID}.json").write_text(json.dumps({"source_id": L.SOURCE_ID, "ok": True, "meta": {},
                                                               "records": [old]}))
    d = tmp_path / "pages"
    d.mkdir()
    (d / f"{path.rsplit('/', 1)[-1]}.html").write_text(h)
    for _ in range(2):
        assert L.main(["--dir", str(d)]) == 0
        doc = json.loads((tmp_path / f"{L.SOURCE_ID}.json").read_text())
        assert doc["count"] == 1
        r = doc["records"][0]
        assert r["source_record_id"] == "sanitary-sewer-overflow-reported-may-27-2020-example-court"
        assert r["raw"]["first_seen_at"] == "2026-11-01T00:00:00Z" and "page_text" not in r["raw"]
        blob = json.dumps(doc) + "".join(p.read_text() for p in (tmp_path / "raw").rglob("*.json"))
        for p in PERSONAL + ["1234"]:
            assert p not in blob
    assert L.record_id(L.record_id(path)) == L.record_id(path)
    assert L.record_id("/x/sanitary-sewer-overflow-1200-block-example-reported-thursday-oct-23-2025") == \
        "sanitary-sewer-overflow-block-example-reported-thursday-oct-23-2025"


def test_leavenworth_cites_the_year_page_not_the_address_page():
    h = _page("Sanitary Sewer Overflow Reported on May 27, 2020 at 1234 Example Court", "At 3:50 p.m. May 27, 2020.")
    year = L.BASE + "/publicworks/page/2020-sanitary-sewer-overflow-transparency-report"
    r = L.record("/publicworks/page/sanitary-sewer-overflow-reported-may-27-2020-1234-example-court", h, AT, year)
    assert r["source_url"] == year and r["raw"]["cited_page"] == year and "1234" not in json.dumps(r)


def _end(body, title="Sanitary Sewer Overflow Reported on May 27, 2020 at Example Court"):
    return L.record("/publicworks/page/x", _page(title, body), AT)["ended_at"]


def test_leavenworth_end_date_before_or_after_the_stop_verb():
    """Re-review P2-3."""
    start = "At 3:50 p.m. May 27, 2020, staff were notified of sewage in Five-Mile Creek. "
    assert _end(start + "On May 29, 2020, the overflow stopped at 4:00 p.m.") == "2020-05-29T16:00:00-05:00"
    assert _end(start + "The overflow stopped May 29 at 4:00 p.m.") == "2020-05-29T16:00:00-05:00"
    assert _end(start + "The overflow stopped at 4:00 p.m.") == "2020-05-27T16:00:00-05:00"
    # several dates before the verb and none after: not resolved, no end
    assert _end(start + "Between May 28 and May 30 crews worked, and the overflow stopped at 4:00 p.m.") is None
    # a year boundary: reported December 31, stopped January 1 (no year given)
    t = "Sanitary Sewer Overflow Reported on December 31, 2025 at Example Court"
    assert _end("At 11:00 p.m. December 31, 2025, staff were notified. On January 1 the overflow stopped at 2:00 a.m.",
                t) == "2026-01-01T02:00:00-06:00"


def _ko():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ko", ROOT / "scripts" / "add_ks_operators.py")
    ko = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ko)
    return ko


def test_a_plant_label_is_a_permit_only_row_never_an_operator():
    """Re-review P2-1: a permittee of record that names only a plant is a permit-only row (legal form "facility
    (permittee not named)", left out of operator counts); a body with a plant word stays an operator; a city with
    several plants stays one row."""
    ko = _ko()
    by = {r["name"]: r for r in ks_ops()}
    b = by["Beattie Wastewater Plant (permit KS0047236)"]
    assert b["legal_form"] == "facility (permittee not named)" and b["id"] == "ks-beattie-wastewater-plant"
    assert "not established" in b["notes"]
    assert not [r for r in ks_ops() if r["legal_form"] is None and ko.FACILITY_LABEL.search(r["name"])
                and not ko.BODY_WORDS.search(r["name"])]
    assert ko.BODY_WORDS.search("Lake Area Waste Water Association Inc") and ko.FACILITY_LABEL.search("Olathe Harold Street WWTF")
    multi = [r for r in ks_ops() if r["legal_form"] == "city" and len(r["npdes_permits"]) > 1]
    assert multi                                                    # one city, several plants: one operator row


def test_the_not_a_discharge_rule_reads_feature_ids_and_limit_sets():
    """Re-review P2-2, for both states' scripts."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mo_ops", ROOT / "scripts" / "add_mo_operators.py")
    mo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mo)
    for m in (mo, _ko()):
        assert m.influent_only({"outfall": "INF", "limit_set_names": ["Influent Monitoring Monthly"]})
        assert m.influent_only({"outfall": "002", "limit_set_names": ["Influent Monitoring Quarterly"]})
        assert m.influent_only({"outfall": "002", "limit_set_names": ["Influent to Collection System from Example"]})
        assert m.influent_only({"outfall": "001", "limit_set_names": ["Land App/Storage Basin", "Operational Monitoring"]})
        assert not m.influent_only({"outfall": "001", "limit_set_names": ["MONTHLY", "Influent Monitoring", "Quarterly"]})
        assert not m.influent_only({"outfall": "001", "limit_set_names": ["Influent / Effluent"]})
        assert not m.influent_only({"outfall": "001", "limit_set_names": []})
    mo_ops = {r["id"]: r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "MO"}
    sk = next(r for r in mo_ops.values() if "MO0022969" in r["npdes_permits"])
    assert sk["outfall_count"] == 1                                 # its INF feature is not counted


def test_the_permit_exception_and_the_advisory_limits_are_stated_alike_everywhere():
    """Re-review P2-5: K.A.R. 28-16-27's scope (a discharge a valid permit does not provide for, as the saved research
    records it) in the register, the rules row, the operator rows and the state text; the state text states the 14-day
    limit and the advisories whose place is not known."""
    prof = json.loads((ROOT / "research" / "ks" / "profile.json").read_text())
    assert "not provided for by permit" in json.dumps(prof)
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "ks.json").read_text())["channels"]}
    law_rows = [c for c in reg.values() if "K.A.R. 28-16-27" in (c.get("legal_basis") or "")]
    assert law_rows and all("valid permit does not provide for" in c["legal_basis"] for c in law_rows)
    assert all("permit does not provide for" in c["note"] for k, c in reg.items() if k.endswith("-kdhe-report"))
    rules = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["KS"]
    assert "valid permit does not provide for" in rules["basis"] and "14 days" in rules["basis"]
    assert all("valid permit does not" in r["notification_channel"] for r in ks_ops())
    t = (ROOT / "research" / "ks" / "state-text.md").read_text()
    assert "a valid permit does not provide for" in t and "14 days after the last read that confirmed it" in t
    assert "its place on the map is not known" in t and "publishes no list or map layer" in t
