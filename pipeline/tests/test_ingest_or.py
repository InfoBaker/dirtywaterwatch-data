"""Oregon: Portland Environmental Services' advisories (ingest/or_bes_news.py), DEQ's OERS sewage spills 2013-2025
(ingest/or_deq_oers_spills.py), OHA's bloom advisories through the generic ArcGIS block (ingest/or_transforms.py), the
Malheur County clock (zones.oregon_zone), and the state's registry rows, register, rules row, text and missing-waters
list. Fixtures are real rows and pages (the pages' contact blocks already cut); the personal strings are synthetic
("Example")."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import zones
from ingest import or_bes_news as B
from ingest import or_deq_oers_spills as O
from ingest.generic import runner as R

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-07T23:00:00Z"
PERSONAL = ["Pat Example", "pat.example", "555-0199", "555-0100", "555-0142", "1234 SE Example", "Caller",
            "Situation", "1234"]


def strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def no_personal(recs) -> None:
    blob = "\n".join(strings(recs))
    for p in PERSONAL:
        assert p not in blob, p


# ---------------------------------------------------------------- the clock

def test_oregon_zone_follows_malheur_county_and_township_35_south():
    assert zones.oregon_zone(44.03, -116.96) == zones.MOUNTAIN                 # Ontario
    assert zones.oregon_zone(42.97, -117.05) == zones.MOUNTAIN                 # Jordan Valley
    assert zones.oregon_zone(42.10, -117.80) == zones.PACIFIC                  # south of T. 35 S.
    assert zones.oregon_zone(45.52, -122.68) == zones.PACIFIC                  # Portland
    assert zones.oregon_zone(44.78, -117.83, "Baker") == zones.PACIFIC         # Baker City by its county
    assert zones.oregon_zone(None, None, "Malheur County") == zones.MOUNTAIN
    assert zones.zone_for("OR", 43.98, -117.24) == zones.MOUNTAIN and zones.zone_for("OR") == zones.PACIFIC


def test_other_states_zones_unchanged():
    for st, z in zones.STATE_ZONES.items():
        if st not in ("FL", "SD", "NE", "OR"):
            assert zones.zone_for(st) == z and zones.zone_for(st, 44.0, -117.0) == z


# ---------------------------------------------------------------- Portland Environmental Services

def bes(prev=()):
    doc = json.loads((FIX / "or_bes" / "safe.json").read_text())
    recs, stats = B.build(doc, list(prev), FETCHED)
    return {r["source_record_id"]: r for r in recs}, stats


def test_only_sewage_advisories_are_read():
    recs, stats = bes()
    assert stats["items"] == 9 and stats["not_read"] == 2                      # rates; treated effluent
    assert set(recs) == {"59515", "57715", "56908", "56908-2", "58937", "56798", "64402", "56546"}
    assert all(r["raw"]["time_zone"] == "America/Los_Angeles" and r["raw"]["state"] == "OR" for r in recs.values())


def test_cso_advisory_window_is_the_citys_own():
    r = bes()[0]["59515"]
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["npdes_permit"] == "OR0026905"
    assert r["discharger_id"] == "or-portland-bes" and r["waterbody_text"] == "Willamette River"
    assert r["started_at"] == "2026-03-12T06:26:00-07:00" and r["time_precision"] == "minute"
    # only the expiry is given: the end is the expiry less BES's 48 hours, so the window ends at BES's own expiry
    assert r["raw"]["advisory_expires_at"] == "2026-03-16T03:34:00-07:00"
    # P2-1 (review 2026-11-08): the City never states the stop, so the derived end is a bound ("ended by")
    assert r["ended_at"] == "2026-03-14T03:34:00-07:00" and r["raw"]["ended_at_precision"] == "bound"
    assert r["raw"]["end_basis"].startswith("ended by")
    assert r["advice_window_hours"] == 48 and "48 hours after it stops" in r["advice_window_basis"]
    assert r["published_at"] == "2026-03-12T09:14:00-07:00" and r["source_updated_at"] == "2026-03-12T09:15:00-07:00"
    assert r["reported_at"] is None and r["raw"]["stretch_text"] == "downstream of the Ross Island Bridge"
    assert r["lat"] is None and r["lon"] is None                               # never geocoded


def test_the_rss_date_is_never_the_start():
    recs = bes()[0]
    r = recs["56546"]                                                          # Elk Rock, "Start Time: Midnight 11/28/25"
    assert r["started_at"] == "2025-11-28T00:00:00-08:00" and r["ended_at"] == "2025-11-28T01:15:00-08:00"
    assert r["waterbody_text"] == "Willamette River; Columbia Slough" and r["volume_gal"] == 5000
    for x in recs.values():
        assert x["started_at"] != B.rss_time(x["raw"]["rss_pub_date"]).isoformat() or \
            x["raw"]["start_basis"].startswith("the advisory gives no start")


def test_stated_duration_bound_and_open_ends():
    recs = bes()[0]
    r = recs["57715"]                                                          # "lasted about two minutes"
    assert r["ended_at"] == "2026-01-06T09:03:00-08:00" and r["volume_gal"] == 1995 and r["estimate_flag"] == "estimated"
    r = recs["56798"]                                                          # "The release has stopped."
    assert r["raw"]["ended_at_precision"] == "bound" and r["ended_at"] == r["published_at"]
    assert r["raw"]["reached_water"] is False and "reconnects to the city sewer" in r["raw"]["_no_water_reason"]
    r = recs["64402"]                                                          # Woods Creek: the day, ongoing
    assert r["status"] == "ongoing" and r["time_precision"] == "day" and r["ended_at"] is None
    assert r["started_at"] == "2026-10-21T00:00:00-07:00" and r["waterbody_text"] == "Woods Creek; Fanno Creek"
    assert r["discharger_id"] is None and r["raw"]["private_source"] is True and r["advice_window_hours"] is None
    r = recs["58937"]                                                          # still in the excavation hole
    assert r["status"] == "unknown" and r["waterbody_text"] is None and r["raw"]["reached_water"] is False


def test_a_second_release_in_one_advisory_is_its_own_record():
    recs = bes()[0]
    a, b = recs["56908"], recs["56908-2"]
    assert a["started_at"] == "2025-12-09T12:00:00-08:00" and b["started_at"] == "2025-12-18T20:00:00-08:00"
    assert a["discharger_id"] is None and a["volume_gal"] is None and "2,250" in a["volume_text"]
    assert a["published_at"] == "2025-12-09T17:11:00-08:00" and b["published_at"] == "2025-12-19T06:30:00-08:00"


def test_records_are_carried_when_their_item_leaves_the_feed():
    first, _ = bes()
    old = json.loads(json.dumps(first["57715"]))
    old["source_record_id"], old["event_id"] = "1", "or-bes-news-rss:1"
    recs, stats = bes([old])
    assert "1" in recs and stats["records"] == 9
    again, _ = bes(list(first.values()))
    assert again["59515"]["raw"]["_first_seen_at"] == FETCHED


def test_contact_block_house_numbers_and_phones_never_kept():
    page = B.page_lines((FIX / "or_bes" / "page_contact.html").read_bytes())
    assert page["published"] == "March 2, 2026 4:00 pm" and page["label"] == "News article"
    item = {"title": "Sewage Advisory: Crews respond to sewage release in SE Portland", "node": "1",
            "link": "https://www.portland.gov/bes/news/example", "guid": "https://www.portland.gov/node/1#x",
            "pub_date": "Mon, 02 Mar 2026 16:00:00 -0800", "description": ""}
    recs = B.records_for(item, page, FETCHED)
    no_personal([page, recs])
    r = recs[0]
    assert r["started_at"] == "2026-03-02T13:15:00-08:00" and r["waterbody_text"] == "Example Creek"
    assert "[house number removed] SE Example St" in r["raw"]["text"]


# ---------------------------------------------------------------- DEQ's OERS archive

def oers():
    rows, meta = O.load_file(str(FIX / "or_oers" / "rows.json"))
    recs, stats = O.build(rows, FETCHED)
    return {r["source_record_id"]: r for r in recs}, stats, rows


def test_oers_sewage_rows_only_with_their_own_numbers():
    recs, stats, rows = oers()
    assert stats["rows_read"] == 11 and stats["records"] == 10 and stats["not_sewage"] == {"Milk": 1}
    assert "2018-1404" in recs and len([k for k in recs if k.startswith("2018-1404-")]) == 1
    assert all(r["status"] == "unknown" and r["ended_at"] is None and r["published_at"] is None for r in recs.values())


def test_oers_types_waters_and_reached_water():
    recs, _, _ = oers()
    r = recs["2022-2950"]
    assert r["event_type"] == "bypass" and r["waterbody_text"] == "Yaquina River" and "reached_water" not in r["raw"]
    r = recs["2023-0975"]
    assert r["waterbody_text"] == "Columbia River" and r["raw"]["waterway_place"] == "Astoria"
    r = recs["2013-1512"]
    assert r["event_type"] == "sso" and r["raw"]["reached_water"] is False and r["volume_gal"] == 200
    r = recs["2017-1160"]                                                     # P2-3: a private residence's sewage
    assert r["event_type"] == "sso" and r["raw"]["_source_type"] == "Private Residence" and "_type_basis" in r["raw"]
    r = recs["2023-0731"]
    assert r["waterbody_text"] is None and r["volume_gal"] == 50000          # "Unknown, Madras" names no water
    r = recs["2016-0260"]
    assert r["lat"] is None and r["coord_source"] is None


def test_oers_clock_is_the_counties_own():
    recs, _, _ = oers()
    r = recs["2015-1616"]                                                     # Nyssa, Malheur County
    assert r["raw"]["time_zone"] == "America/Denver" and r["started_at"] == "2015-07-21T18:31:00-06:00"
    assert r["reported_at"] == r["started_at"] and "at or before" in r["raw"]["start_basis"]
    assert recs["2022-2950"]["raw"]["time_zone"] == "America/Los_Angeles"


def test_oers_never_reads_the_narrative_name_or_address():
    recs, _, rows = oers()
    assert all(set(r) <= set(O.SAFE_FIELDS) for r in rows)
    no_personal(list(recs.values()))
    assert "2099-0001" in recs


def test_oers_archive_written_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "EVENTS_DIR", tmp_path)
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    assert O.main(["--file", str(FIX / "or_oers" / "rows.json")]) == 0
    d = json.loads((tmp_path / f"{O.SOURCE_ID}.json").read_text())
    assert d["ok"] and d["meta"]["frozen"] is True and d["meta"]["layer_last_edit"] == "2025-04-01T16:59:57Z"
    assert d["count"] == 10


# ---------------------------------------------------------------- OHA's bloom advisories

def hab():
    _, block = R.load_source("or-oha-hab-advisories")
    rows = R.platform("arcgis").parse(block, (FIX / "or_oha" / "hab.json").read_bytes())
    recs, stats = R.build("or-oha-hab-advisories", block, rows, FETCHED, (), None)
    return {r["waterbody_text"]: r for r in recs}, stats


def test_hab_block_validates_and_keeps_advisories_and_precautions_only():
    _, block = R.load_source("or-oha-hab-advisories")
    assert R.validate_block(block, "or-oha-hab-advisories") == []
    recs, stats = hab()
    assert set(recs) == {"South Umpqua River; Umpqua River", "Detroit Lake", "Owyhee Reservoir"}
    for r in recs.values():
        assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active" and r["time_precision"] == "day"
        assert r["lat"] is not None and r["raw"]["_last_seen_in_source"] == FETCHED
    u = recs["South Umpqua River; Umpqua River"]
    assert u["raw"]["_hab_level"] == "Advisory" and "PERMANENT RECREATIONAL USE ADVISORY" in u["advice_text"]
    assert u["started_at"] == "2024-01-01T00:00:00-08:00"
    assert recs["Detroit Lake"]["raw"]["_hab_level"] == "Precaution" and recs["Detroit Lake"]["raw"]["county_2"] == "Linn"


def test_hab_owyhee_is_on_mountain_time():
    r = hab()[0]["Owyhee Reservoir"]
    assert r["raw"]["time_zone"] == "America/Denver" and r["started_at"].endswith("-06:00")
    assert r["started_at"][:10] == "2026-09-21"


# ---------------------------------------------------------------- registry, register, rules, text, waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "OR"]


def test_every_oregon_permit_is_in_exactly_one_row():
    rows = ops()
    held = [p for r in rows for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) == 168
    epa = set()
    for f in ("outfalls-us.json", "outfalls-plants-us.json"):
        doc = json.loads((ROOT / "data" / f).read_text())
        epa |= {r["npdes_permit"] for r in (doc["outfalls"] if isinstance(doc, dict) else doc)
                if str(r.get("npdes_permit") or "").startswith("OR")}
    assert epa <= set(held) and {"OR0030864", "OR0020834"} <= set(held)
    by = {r["id"]: r for r in rows}
    assert by["or-portland-bes"]["npdes_permits"] == ["OR0026905", "OR0026891"] and by["or-portland-bes"]["kind"] == "cso"
    assert by["or-astoria"]["outfall_count"] == 38 and by["or-corvallis"]["kind"] == "cso"     # the CSO outfalls
    assert len(by["or-clean-water-services"]["npdes_permits"]) == 4


def test_legal_forms_are_controlled_and_no_individual_is_named():
    from build import redact
    from ingest import dischargers_schema as DS
    rows = ops()
    assert DS.check_legal_forms(rows) == []
    assert not [r["name"] for r in rows if redact.person_shaped(r["name"])]


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "or.json").read_text())["channels"]}
    for r in ops():
        row = reg[f"{r['id']}-public-notice"]
        assert row["basis_kind"] == "permit" and "Emergency Response and Public Notification Plan" in row["legal_basis"]
    assert reg["or-portland-bes-public-notice"]["feed_source_id"] == "or-bes-news-rss"
    assert reg["or-astoria-public-notice"]["barrier"] == "no_web_page" and reg["or-corvallis-public-notice"]["barrier"] == "no_web_page"
    assert reg["or-deq-oers-reports"]["barrier"] == "phone_only" and reg["or-deq-oers-reports"]["urls"] == []
    assert reg["or-deq-oers-spills-archive"]["feed_source_id"] == "or-deq-oers-spills-2013-2025"
    assert reg["or-oha-hab-advisories"]["feed_source_id"] == "or-oha-hab-advisories"
    assert reg["or-portland-bes-big-pipe-tracker"]["monitored"]
    assert reg["or-oha-beach-conditions"]["feed_source_id"] == "or-oha-beach-monitoring"


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    r = rules["red"]["by_state"]["OR"]
    assert r["hours"] is None and "340-142-0040" in r["source"] and "Schedule F" in r["source"]
    assert "Malheur County" in r["basis"] and "48 hours" in r["basis"] and "OR" not in rules["live_states"]
    assert not re.search(r"\b(safe|clean)\b", r["basis"], re.I)


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "or" / "state-text.md").read_text()
    assert t.startswith("---\nstate: OR\nname: Oregon\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean|green)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "2,371" in t and "March 27, 2025" in t and "township 35 South" in t


def test_missing_waters_list_holds_its_invariants():
    d = json.loads((ROOT / "research" / "or" / "receiving-waters-missing.json").read_text())
    national = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in ((national.get("states") or {}).get("OR") or {}).get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    rows = d["rows"]
    assert d["state"] == "OR" and d["waters"] == len(rows)
    assert not [r["name"] for r in rows if k(r["name"]) in held]
    keys = [(k(r["name"]), r["county"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in rows:
        assert r["county"] and r["county"].endswith("County") and not re.search(r"\d", r["name"])
        assert "removed]" not in json.dumps(r) and not re.search(r"(?i)\bpossible\b|\bnull\b|\bunknown\b", r["name"])


def test_oregon_name_placement_is_county_aware():
    from build import status as S
    assert "OR" in S.COUNTY_STATES and "OR" in S.COUNTY_FIELD_STATES
    assert S.point_county("OR", 44.03, -116.96)[1] == "Malheur County"
    assert S.point_county("OR", 46.19, -123.83)[1] == "Clatsop County"
    assert S.named_county("OR", "Multnomah")[1] == "Multnomah County"


def test_oers_waterway_text():
    assert O.waterway("Columbia River, Hood River") == (["Columbia River"], "Hood River")
    assert O.waterway("Evans Creek and the Rogue River") == (["Evans Creek", "Rogue River"], None)
    assert O.waterway("Willamette, Oak Lodge") == (["Willamette River"], "Oak Lodge")
    assert O.waterway("Possible impact to creek") == ([], None) and O.waterway("NULL") == ([], None)
    assert O.waterway("nye creek") == (["Nye Creek"], None)


# ---------------------------------------------------------------- the review of 2026-11-08

def intervals(ev, now="2026-11-08T00:00:00+00:00"):
    from datetime import datetime
    from build import status as S
    return S.event_intervals(ev, "OR", datetime.fromisoformat(now), None, S.load_rules())


def test_p2_3_a_private_homes_sewage_report_carries_the_caution():
    r = oers()[0]["2017-1160"]
    ivs = intervals(r, "2017-04-12T00:00:00+00:00")
    assert ivs and ivs[0]["color"] == "yellow" and ivs[0]["category"] == "sewage"
    from build import status as S
    assert r["event_type"] in S.DISCHARGE_TYPES


def test_p2_4_an_advice_to_avoid_a_water_with_no_end_is_red_then_hatched():
    r = bes()[0]["56908"]
    assert r["status"] == "ongoing" and "avoid the Willamette River" in r["raw"]["status_basis"]
    ivs = intervals(r, "2025-12-10T00:00:00+00:00")
    assert ivs[0]["color"] == "red" and ivs[0]["rule"] == "ongoing"
    assert any(iv["rule"] == "unresolved" for iv in ivs)
    assert bes()[0]["58937"]["status"] == "unknown"                            # no water to avoid: unchanged


def test_p2_5_a_failed_read_clears_on_the_next_unchanged_read(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(O, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    assert O.main(["--file", str(FIX / "or_oers" / "rows.json")]) == 0

    def boom(sess):
        raise RuntimeError("timeout")
    monkeypatch.setattr(O, "metadata", boom)
    assert O.main([]) == 1
    d = json.loads((tmp_path / f"{O.SOURCE_ID}.json").read_text())
    assert d["ok"] is False and d["count"] == 10
    monkeypatch.setattr(O, "metadata", lambda sess: {"name": "x", "hasStaticData": True,
                                                       "lastEditDate": O.FROZEN_EDIT_MS})
    monkeypatch.setattr(O, "query", lambda sess: (_ for _ in ()).throw(AssertionError("rows read again")))
    assert O.main([]) == 0
    d = json.loads((tmp_path / f"{O.SOURCE_ID}.json").read_text())
    assert d["ok"] is True and d["error"] is None and d["count"] == 10 and d["meta"]["frozen"] is True


def test_p2_2_ohas_precaution_is_labelled_a_precaution():
    recs = hab()[0]
    p, a = recs["Detroit Lake"], recs["South Umpqua River; Umpqua River"]
    assert p["authority"] == "Oregon Health Authority (recreational use precaution)"
    assert p["raw"]["advisory_noun"] == "Cyanobacteria precaution (Oregon Health Authority)"
    assert a["authority"] == "Oregon Health Authority (recreational use advisory)" and "_interval_label" not in a["raw"]
    ivs = intervals(p)
    assert ivs[0]["category"] == "bloom" and "precaution" in ivs[0]["label"] and "not an advisory" in ivs[0]["label"]
    assert a["raw"]["_water_as_given"] == "South & mainstream Umpqua River"


def test_p2_6_misspellings_are_aliased_not_sent_to_the_batch():
    aliases = json.loads((ROOT / "data" / "water-aliases.json").read_text())
    assert aliases["tualatin-river-or"] == ["Tualitan River"] and "Coquile River" in aliases["coquille-river-or"]
    d = json.loads((ROOT / "research" / "or" / "receiving-waters-missing.json").read_text())
    bad = {re.sub(r"[^a-z0-9]", "", a.lower()) for k, v in aliases.items() if k.endswith("-or") for a in v}
    assert not [r["name"] for r in d["rows"] if re.sub(r"[^a-z0-9]", "", r["name"].lower()) in bad]
    assert d["aliased"]["Tualitan River"] == 2
    from ingest import or_transforms as T
    assert T.water_names("Brownlee Reservoir - Powder Arm") == ["Brownlee Reservoir"]


def test_p2_7_ohas_beach_table_advisory_and_sewage():
    from ingest import or_oha_beaches as OB
    rows = OB.rows_of((FIX / "or_oha_beach" / "status.html").read_bytes())
    assert [r["status"] for r in rows] == ["ADVISORY", "OPEN", "SEWAGE", "NO MONITORING"]
    recs, stats = OB.build(rows, [], FETCHED)
    by = {r["waterbody_text"]: r for r in recs}
    assert set(by) == {"Seaside Beach", "Cannon Beach"} and stats["open_records"] == 2
    assert by["Seaside Beach"]["event_type"] == "beach_advisory" and by["Cannon Beach"]["event_type"] == "sso"
    assert by["Cannon Beach"]["status"] == "advisory_active" and by["Cannon Beach"]["time_precision"] == "poll"
    assert by["Cannon Beach"]["raw"]["county"] == "Clatsop" and "Sewage spills" in by["Cannon Beach"]["advice_text"]
    assert intervals(by["Cannon Beach"], "2026-11-08T00:00:00+00:00")[0]["color"] == "red"
    # the next read shows Cannon Beach open: OHA's window ends there; Seaside still listed
    later = "2026-11-08T05:00:00Z"
    rows2 = [dict(r, status="OPEN") if r["beach"] == "Cannon Beach" else r for r in rows]
    recs2, stats2 = OB.build(rows2, json.loads(json.dumps(recs)), later)
    by2 = {r["waterbody_text"]: r for r in recs2}
    assert by2["Cannon Beach"]["raw"]["_unlisted_since"] == later and stats2["open_records"] == 1
    assert by2["Seaside Beach"]["raw"]["_last_seen_in_source"] == later and len(recs2) == 2


def test_p3_small_fixes():
    # Malheur north of 44.30 N by its Census outline (P3-2)
    assert zones.oregon_zone(44.31, -118.10) == zones.MOUNTAIN
    # a sewer overflow title is read; treated effluent is not (P3-6)
    assert B.TITLE_RE.search("Sewer overflow to Johnson Creek")
    assert B.NOT_SEWAGE_TITLE.search("Treated wastewater that was not dechlorinated enters the Columbia Slough")
    # a renamed contact heading still ends the article (P3-7)
    page = (FIX / "or_bes" / "page_contact.html").read_text().replace("<h2>Help prevent sewage releases</h2>", "") \
        .replace("<h2>Contact</h2>", "<h2>Media contact</h2>")
    lines = B.page_lines(page)
    no_personal(lines)
    # a volume under one gallon is text, never 0 gallons (P3-1)
    rows, _ = O.load_file(str(FIX / "or_oers" / "rows.json"))
    a = dict(rows[0], Q_released_gal=0.5, Quantity_Unknown="No", UOM="Gallons")
    r = O.record(a, "x", FETCHED)
    assert r["volume_gal"] is None and r["volume_text"] == "0.5 gallons"
