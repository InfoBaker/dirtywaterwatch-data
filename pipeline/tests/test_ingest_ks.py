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


# ---------------------------------------------------------------- KDHE stream advisories

def test_stream_advisory_pair_is_kdhes_window_and_an_orphan_rescission_makes_no_record():
    recs, stats = A.run((FIX / "kdhe_feed.xml").read_bytes(), [], AT)
    by = {r["source_record_id"]: r for r in recs}
    assert set(by) == {"9101", "9104"}
    r = by["9101"]
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-01-29T15:00:00-06:00" and r["ended_at"] == "2026-02-03T10:00:00-06:00"
    assert r["raw"]["waters"] == ["Example Creek", "Sample River"] and r["raw"]["county"] == "Shawnee County"
    assert r["raw"]["cause"] == "sewage" and r["raw"]["advisory_extent"] == "named_water"
    assert r["raw"]["lifted_by"]["link"].endswith("aid=9102") and r["raw"]["ended_at_precision"] == "minute"
    m = by["9104"]
    assert m["status"] == "advisory_active" and m["raw"]["cause"] == "livestock waste"
    assert m["raw"]["_last_seen_in_source"] == AT and m["source_updated_at"] is None
    assert stats["rescissions_without_issue"] == 1 and stats["issues"] == 2


def test_stream_advisory_carried_and_lifted_on_a_later_run():
    first, _ = A.run((FIX / "kdhe_feed.xml").read_bytes(), [], AT)
    later = b"""<?xml version="1.0"?><rss><channel><item><title>Stream Advisory Rescinded for Manure Creek in Example
    County</title><link>https://www.kdhe.ks.gov/CivicAlerts.aspx?aid=9106</link><pubDate>Mon, 02 Nov 2026 09:00:00 -0600
    </pubDate><description>Rescinded.</description></item></channel></rss>"""
    recs, stats = A.run(later, first, "2026-11-15T18:00:00Z")
    by = {r["source_record_id"]: r for r in recs}
    assert by["9104"]["status"] == "advisory_lifted" and by["9104"]["ended_at"] == "2026-11-02T09:00:00-06:00"
    assert "9101" in by and stats["open"] == 0


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


def test_missing_waters_list_rows_are_unique_and_unlisted():
    d = json.loads((ROOT / "research" / "ks" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        s = re.sub(r"^\s*(?:trib(?:utary|\.)?\s+to|tributary of)\s+", "", (n or "").lower())
        return re.sub(r"\br\.?$", "river", re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+tributary$", "", s))).replace(" ", "")
    held = {k(n) for w in nat["states"]["KS"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    assert d["state"] == "KS" and d["waters"] == len(d["rows"]) > 0
    for r in d["rows"]:
        assert k(r["name"]) not in held or r.get("resolved")
    keys = [(r["name"], r["county"]) for r in d["rows"]]
    assert len(keys) == len(set(keys))
