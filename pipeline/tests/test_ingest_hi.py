"""Hawaii: the Department of Health Clean Water Branch's events list (ingest/hi_doh_cwb_events.py) from a fixture of real,
name-free events of the read of 2026-11-07 (the staff fields replaced by a placeholder address and the one house number
by a placeholder of the same form), and Hawaii's operator rows, register rows, rules row, state text and missing-waters
list. No network."""
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from build import status as S
from ingest import dischargers_schema as DS
from ingest import hi_doh_cwb_events as HI
from ingest import notification_pages as NP

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "hi_doh_cwb_events.json"
FETCHED = "2026-11-07T12:53:27Z"
STAFF = "staff.member@doh.example"


def doc():
    return json.loads(FIXTURE.read_text())


def waters(records=()):
    return HI.Waters(list(records), {})


def build(d=None, previous=(), w=None):
    return HI.build(d or doc(), FETCHED, previous, w or waters())


def by_id(records):
    return {r["source_record_id"]: r for r in records}


def box_record(slug, name, island, kind="bay"):
    x0, y0, x1, y1 = HI.ISLANDS[island][2]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return {"slug": slug, "name": name, "kind": kind, "state": "HI", "bbox": [cx - 0.01, cy - 0.01, cx + 0.01, cy + 0.01],
            "aliases": []}


# ---------------------------------------------------------------- types, statuses, times

def test_types_follow_the_departments_categories():
    recs, meta = build()
    r = by_id(recs)
    assert meta["read"] == 19 and meta["total_results"] == 1901
    assert r["2174"]["event_type"] == "sso"                         # a manhole at a pump station
    assert r["2143"]["event_type"] == "plant_bypass"                # "partially treated sewage" from the Hilo plant
    assert r["2046"]["event_type"] == "bypass"                      # at the Wahiawa plant, untreated as far as told
    assert r["2183"]["event_type"] == "plant_bypass"                # Permit Exceedance
    bwa = r["2194"]
    assert bwa["event_type"] == "rain_advisory" and bwa["raw"]["advisory_noun"] == "Brown Water Advisory"
    assert S.category_of(bwa["event_type"]) == "beach" and S.category_of(r["2174"]["event_type"]) == "sewage"
    assert r["2193"]["event_type"] == "beach_advisory" and r["2193"]["status"] == "advisory_active"
    note = r["2179"]                                                 # a retest notice, no advisory
    assert note["event_type"] == "beach_advisory" and note["status"] == "unknown"
    assert note["raw"]["_agency_label_only"] is True and "retesting" in note["raw"]["_agency_label"]
    for x in recs:
        assert x["raw"]["_type_basis"] and x["authority"] == HI.AUTHORITY and x["source_url"].endswith("/details/view")


def test_times_are_utc_written_in_hawaii_time_and_the_hst_date_field_is_not_used():
    r = by_id(build()[0])["2174"]
    # postedDate 2026-10-23T01:26:16 UTC is 15:26 on 10-22 in Honolulu (postedDateHst says 10-23: the UTC date)
    assert r["started_at"] == "2026-10-22T15:26:16-10:00" == r["published_at"]
    assert r["ended_at"] == "2026-10-23T11:13:55-10:00" and r["status"] == "advisory_lifted"
    assert r["raw"]["sign_removal_hawaii_time"].startswith("2026-10-23T11:13:55")   # the same instant, in Hawaii
    assert r["time_precision"] == "minute" and r["reported_at"] is None
    assert r["source_updated_at"] == "2026-10-23T11:14:05-10:00"


def test_open_advisories_have_no_end_and_are_confirmed_by_the_read():
    r = by_id(build()[0])
    for rid in ("2183", "2194", "2193"):
        assert r[rid]["status"] == "advisory_active" and r[rid]["ended_at"] is None
        assert r[rid]["raw"]["_last_seen_in_source"] == FETCHED


def test_beach_notification_starts_on_its_sample_day_unless_the_date_cannot_be_right():
    r = by_id(build()[0])
    assert r["2179"]["started_at"] == "2026-10-28T00:00:00-10:00" and r["2179"]["time_precision"] == "day"
    bad = r["1735"]                                                  # sampleDate 2001-12-13 on a 2023 notice
    assert bad["started_at"] == bad["published_at"] and bad["started_at"].startswith("2023-12-14")
    assert "typing slip" in bad["raw"]["_sample_date_not_used"]


# ---------------------------------------------------------------- privacy

def test_staff_fields_and_house_numbers_never_reach_a_record():
    recs, _ = build()
    text = json.dumps(recs, ensure_ascii=False)
    assert STAFF not in text and "createdBy" not in text and "updatedBy" not in text and "descriptionHtml" not in text
    assert "99-999" not in text                                     # Hawaii's hyphenated house number ("99-999 Sample Place")
    r = by_id(recs)["1934"]
    assert "[house number removed] Sample Place" in r["raw"]["row"]["title"]
    assert "Kalauau Stream" in r["waterbody_text"]                  # the water stays
    assert HI.scrub_address("Near 9999 Sample Street") == "Near [house number removed] Sample Street"
    assert HI.scrub_address("Kihei Pump Station #6 on South Kihei Road") == "Kihei Pump Station #6 on South Kihei Road"


def test_the_authority_is_named_in_full_and_no_other_title_field_says_safe_or_clean():
    # the event pages' meta descriptions carry the authority, the operator and the water (site audit-seo FORBIDDEN):
    # the Department's "Clean Water Branch" is named in raw only
    for r in build()[0]:
        assert r["authority"] == "Hawaii Department of Health, Clean Water Branch"   # the audit strips authority names
        for k in ("discharger_name", "waterbody_text"):
            assert not re.search(r"\b(safe|clean)\b", str(r.get(k) or ""), re.I), (r["source_record_id"], k)


def test_the_saved_answer_drops_the_staff_fields_at_every_depth():
    saved = json.dumps(HI.drop_never_read(doc()))
    assert STAFF not in saved and "descriptionHtml" not in saved
    assert "Kalapaki Beach Park" in saved


# ---------------------------------------------------------------- places

@pytest.mark.parametrize("text,kw,want", [
    ("Offshore waters near the entrance channel to Pearl Harbor just off the Ewa end of the Reef Runway.", {},
     [("Pearl Harbor", False)]),
    ("Joint Base Pearl Harbor Hickam", {}, []),                                        # a base, not a water
    ("Pearl Harbor Peninsula, East Loch", {}, [("East Loch", False)]),                  # land after the water word
    ("Kailua Regional Wastewater Treatment Plant ocean outfall", {}, []),               # 'ocean outfall' is no water
    ("Kāneʻohe Bay", {}, [("Kaneohe Bay", False)]),                                     # diacritics folded
    ("Hilo bay and along the Hamakua coast", {}, [("Hilo Bay", False)]),
    ("Waimea Bay Beach Park", {}, [("Waimea Bay", True)]),                              # the beach on that bay
    ("Guardrails to Olowalu Stream", {"range_ends_fresh": True}, []),                   # a stretch's landmark end
    ("Puhi Bay to Onekahakaha", {"range_ends_fresh": True}, [("Puhi Bay", False)]),
    ("Kolekole Gulch (Ocean)", {}, []),                                                 # the land behind an ocean station
    ("the Wahiawa plant spilled into Lake Wilson", {}, [("Lake Wilson", False)]),
    ("Nuuipa Pond", {}, [("Nuupia Pond", False)]),                                      # the Department's typing
])
def test_water_names_by_rule(text, kw, want):
    assert HI.water_names(text, **kw) == want


def test_records_carry_the_named_waters_and_beaches_as_places():
    r = by_id(build()[0])
    assert r["1881"]["waterbody_text"] == "Kuapa Pond"              # named only in the advice: "stay out of Kuapa Pond"
    assert r["1638"]["waterbody_text"] == "Kailua Bay"              # not "Treatment Plant Ocean"
    assert r["1686"]["waterbody_text"] == "Pearl Harbor"
    assert r["2190"]["waterbody_text"] == "Hilo Bay" and r["2190"]["raw"]["advisory_extent"] == "named_water"
    assert r["2194"]["waterbody_text"] == "Kalapaki Beach Park" and "advisory_extent" not in r["2194"]["raw"]
    assert r["2194"]["raw"]["place_basis"].startswith("the Department names a beach")
    assert r["2193"]["raw"].get("advisory_extent") is None          # a beach station never colours a whole bay
    isl = next(x for x in r.values() if x["raw"]["row"].get("isIslandWide"))
    assert isl["waterbody_text"] is None and isl["raw"]["extent"] == "island"
    assert r["2174"]["waterbody_text"] is None                       # "Beach fronting Kalama Park": no water named
    assert r["2174"]["raw"]["town"] == "Kihei"


def test_a_name_two_islands_share_is_placed_only_on_the_events_island():
    w = waters([box_record("waimea-bay-oahu-hi", "Waimea Bay", "oahu"),
                box_record("waimea-bay-kauai-hi", "Waimea Bay", "kauai"),
                box_record("hilo-bay-hi", "Hilo Bay", "hawaii")])
    recs = by_id(build(w=w)[0])
    oahu = next(x for x in recs.values() if x["raw"]["row"].get("locationName") == "Waimea Bay")
    kauai = next(x for x in recs.values() if x["raw"]["row"].get("locationName") == "Waimea Bay Landing")
    assert oahu["raw"]["island"] == "Oahu" and oahu["water_slugs"] == ["waimea-bay-oahu-hi"]
    assert kauai["raw"]["island"] == "Kauai" and kauai["water_slugs"] == ["waimea-bay-kauai-hi"]
    assert recs["2190"]["water_slugs"] == ["hilo-bay-hi"] and recs["2190"]["water_match"] == "name"
    # a name whose only record lies on another island is not placed
    only_kauai = waters([box_record("waimea-bay-kauai-hi", "Waimea Bay", "kauai")])
    oahu = next(x for x in build(w=only_kauai)[0] if x["raw"]["row"].get("locationName") == "Waimea Bay")
    assert oahu["water_slugs"] == [] and "another island" in oahu["raw"]["unplaced_reason"]


def test_aliases_match_with_spelling_marks_folded():
    rec = box_record("kaneohe-bay-hi", "Kāneʻohe Bay", "oahu")
    assert waters([rec]).match("Kaneohe Bay", "oahu")[0] == "kaneohe-bay-hi"
    assert waters([rec]).match("Kaneohe Bay", "maui")[0] is None


# ---------------------------------------------------------------- operators and volumes

def test_operators_only_when_the_notice_names_a_facility():
    r = by_id(build()[0])
    assert (r["2143"]["discharger_id"], r["2143"]["npdes_permit"]) == ("hi-hawaii-county", "HI0021377")
    assert (r["2183"]["discharger_id"], r["2183"]["npdes_permit"]) == ("hi-mcbh-kaneohe", "HI0110078")
    assert (r["1686"]["discharger_id"], r["1686"]["npdes_permit"]) == ("hi-jbphh", "HI0110086")
    assert (r["2174"]["discharger_id"], r["2174"]["npdes_permit"]) == ("hi-maui-county", None)   # Kihei Pump Station #6
    assert r["1934"]["discharger_id"] is None                        # a street address names no operator
    assert r["2194"]["discharger_id"] is None                        # an advisory is never an operator's report


def test_volumes_only_from_a_gallon_figure():
    r = by_id(build()[0])
    assert r["2143"]["volume_gal"] == 71000 and r["2143"]["estimate_flag"] == "estimated"
    assert r["2016"]["volume_gal"] is None and r["2016"]["volume_text"] is None   # a date typed on the volume line
    assert r["2174"]["volume_gal"] is None and r["2174"]["volume_text"] == "Undetermined"


# ---------------------------------------------------------------- the status build

def test_status_windows_the_departments_advisory_and_the_sites_caution_for_a_retest():
    rules = S.load_rules()
    now = datetime(2026, 11, 7, 13, tzinfo=UTC)
    r = by_id(build()[0])
    ivs = S.event_intervals(r["2174"], "HI", now, None, rules)                       # lifted: posted to cancelled
    assert [(i["color"], i["rule"]) for i in ivs] == [("red", "advisory_active")]
    assert ivs[0]["start"] == S.parse_time(r["2174"]["started_at"]) and ivs[0]["end"] == S.parse_time(r["2174"]["ended_at"])
    assert ivs[0]["category"] == "sewage"
    ivs = S.event_intervals(r["2183"], "HI", now, None, rules)                       # open: red with no end
    assert ivs[0]["color"] == "red" and ivs[0]["end"] is None
    ivs = S.event_intervals(r["2194"], "HI", now, None, rules)                       # Brown Water: the beach category
    assert ivs[0]["category"] == "beach" and ivs[0]["rule"] == "rain_advisory"
    ivs = S.event_intervals(r["2179"], "HI", now, None, rules)                       # retest notice: 72 h, site's caution
    assert len(ivs) == 1 and ivs[0]["rule"] == "sample_caution" and ivs[0]["color"] == "yellow"
    assert ivs[0]["end"] - ivs[0]["start"] == timedelta(hours=72) and ivs[0]["red_rule"] is None


def test_an_open_sewage_advisory_that_leaves_the_list_is_end_not_confirmed():
    rules = S.load_rules()
    first, _ = build()
    later = {"page": 0, "totalResultsCount": 1901, "list": [e for e in doc()["list"] if e["id"] != 2183]}
    recs, meta = HI.build(later, "2026-11-08T12:00:00Z", first, waters())
    r = by_id(recs)["2183"]
    assert meta["carried"] == 1 and r["status"] == "advisory_active"
    assert r["raw"]["_unlisted_since"] == "2026-11-08T12:00:00Z" and r["raw"]["_end_not_confirmed"] is True
    ivs = S.event_intervals(r, "HI", datetime(2026, 11, 9, tzinfo=UTC), None, rules)
    start = S.parse_time(r["started_at"])
    assert [(i["color"], i["rule"]) for i in ivs] == [("red", "advisory_active"), ("unresolved", "unresolved"),
                                                      ("grey", "end_never_reported")]
    assert ivs[0]["end"] == S.parse_time("2026-11-08T12:00:00Z") and "not confirmed" in ivs[0]["ended_by"]
    assert ivs[1]["end"] == start + timedelta(days=30)                      # unlisted on day 8: hatched to day 30
    assert ivs[2]["end"] == start + timedelta(days=90)                      # then the end-never-reported note
    # a Brown Water Advisory that leaves the list simply ends there (no flag): other feeds' behaviour is unchanged
    b = by_id(recs)
    assert "_end_not_confirmed" not in b["2193"]["raw"]
    plain = {**r, "raw": {k: v for k, v in r["raw"].items() if k != "_end_not_confirmed"}}
    assert len(S.event_intervals(plain, "HI", datetime(2026, 11, 9, tzinfo=UTC), None, rules)) == 1


@pytest.mark.parametrize("day", [10, 40])
def test_an_unlisted_sewage_advisory_is_hatched_for_at_least_72_hours_even_after_day_30(day):
    rules = S.load_rules()
    r = by_id(build()[0])["2183"]
    start = S.parse_time(r["started_at"])
    gone = start + timedelta(days=day)
    r = {**r, "raw": {**r["raw"], "_unlisted_since": gone.isoformat(), "_end_not_confirmed": True}}
    ivs = S.event_intervals(r, "HI", gone + timedelta(days=100), None, rules)
    assert [i["rule"] for i in ivs] == ["advisory_active", "unresolved", "end_never_reported"]
    assert ivs[0]["end"] == gone and ivs[1]["start"] == gone and ivs[1]["color"] == "unresolved"
    assert ivs[1]["end"] == max(start + timedelta(days=30), gone + timedelta(hours=72))
    assert ivs[2]["end"] == start + timedelta(days=90) and ivs[2]["rule_applied"]["rationale"]


def test_a_retest_caution_runs_until_the_department_closes_the_notice():
    rules = S.load_rules()
    now = datetime(2026, 11, 7, 13, tzinfo=UTC)
    n = by_id(build()[0])["2179"]
    sample = S.parse_time(n["started_at"])
    assert n["raw"]["_notice_closed_at"] == n["ended_at"] == "2026-10-30T13:59:30-10:00"
    late = {**n, "raw": {**n["raw"], "_notice_closed_at": (sample + timedelta(hours=130)).isoformat()}}
    iv = S.event_intervals(late, "HI", now, None, rules)[0]
    assert iv["rule"] == "sample_caution" and iv["end"] == sample + timedelta(hours=130)
    assert iv["rule_applied"]["extended_to"]["source"] == n["source_url"] and iv["red_rule"] is None
    early = {**n, "raw": {**n["raw"], "_notice_closed_at": (sample + timedelta(hours=30)).isoformat()}}
    iv = S.event_intervals(early, "HI", now, None, rules)[0]
    assert iv["end"] == sample + timedelta(hours=72) and "extended_to" not in iv["rule_applied"]
    raw_open = {k: v for k, v in n["raw"].items() if k != "_notice_closed_at"}
    opened = {**n, "ended_at": None, "raw": {**raw_open, "_last_seen_in_source": (sample + timedelta(days=5)).isoformat()}}
    assert S.event_intervals(opened, "HI", now, None, rules)[0]["end"] == sample + timedelta(days=5)
    # Nebraska's samples carry no flag: unchanged
    plain = {**late, "raw": {k: v for k, v in late["raw"].items() if k != "_caution_to_notice_end"}}
    assert S.event_intervals(plain, "HI", now, None, rules)[0]["end"] == sample + timedelta(hours=72)


def test_an_outage_keeps_the_records(tmp_path):
    out = tmp_path / "hi.json"
    assert HI.run(str(FIXTURE), str(out)) == 0
    small = tmp_path / "small.json"
    small.write_text(json.dumps({"page": 0, "totalResultsCount": 1901, "list": doc()["list"][:3]}))
    assert HI.run(str(small), str(out)) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and d["count"] == 19 and "fewer than half" in d["error"]
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    assert HI.run(str(bad), str(out)) == 1 and json.loads(out.read_text())["count"] == 19


# ---------------------------------------------------------------- registry, rules, page text, missing waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "HI"]


def test_every_hawaii_sewage_permit_is_in_exactly_one_row():
    from collections import Counter
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "HI"}
    cand = json.loads((ROOT / "research" / "hi" / "private-utilities-candidates.json").read_text())
    wanted = plants | {c["npdes_permit"] for c in cand["candidates"]}
    assert len(wanted) == 14 and all(every[p] == 1 for p in wanted)
    assert {r["id"] for r in ops()} >= {"hi-honolulu-env", "hi-maui-county", "hi-mcbh-kaneohe", "hi-jbphh"}
    assert not DS.check_legal_forms(ops())
    # the operator ids the ingester names exist
    assert {oid for _, oid, _ in HI.FACILITIES} <= {r["id"] for r in ops()}


def test_register_rows_per_operator_and_the_departments_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "hi.json").read_text())["channels"]}
    for r in ops():
        row = reg[f"{r['id']}-doh-cwb-report"]
        assert row["unmonitored_reason"] == "feed_ingested" and row["feed_source_id"] == HI.SOURCE_ID
        assert row["basis_kind"] == "law" and "11-62" in row["legal_basis"]
        press, signs = reg[f"{r['id']}-press-release"], reg[f"{r['id']}-warning-signs"]
        assert "press release" in press["legal_basis"] and press["barrier"] == "not_verified"
        assert "warning signs" in signs["legal_basis"] and signs["barrier"] == "signs_only"
    assert reg["hi-doh-cwb-advisories"]["feed_source_id"] == HI.SOURCE_ID
    assert reg["hi-doh-cwb-spill-reports"]["urls"] == [] and reg["hi-doh-cwb-signs"]["barrier"] == "signs_only"
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    assert not NP.validate_register(NP.load_register(ROOT / "data" / "notice-channels"), dis, ROOT)


def test_rules_row_and_the_retest_caution():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    hi = rules["red"]["by_state"]["HI"]
    assert hi["hours"] is None and "Appendix B" in hi["source"] and "Brown Water" in hi["basis"]
    assert "press release" in hi["basis"] and "Virginia" in hi["rationale"] and "sample" in hi["rationale"]
    assert hi["source"].count("Clean Water Branch") == 1
    assert not re.search(r"\b(safe|clean)\b", hi["basis"], re.I)
    assert HI.SOURCE_ID in rules["unresolved"]["sample_caution"]["sources"]
    assert "HI" not in rules["live_states"]


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "hi" / "state-text.md").read_text()
    assert t.startswith("---\nstate: HI\nname: Hawaii\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    body = t.replace("Clean Water Branch", "")                               # the agency's name, not a verdict
    assert not re.search(r"\b(safe|clean)\b", body, re.I) and ".json" not in t
    assert "press release" in t and "Appendix B" in t and "whichever is later" in t
    assert not re.search(r"\b(owner|decision|coordinator)\b", t, re.I)
    assert "Brown Water Advisories" in t and "contiguous United States" in t


def test_missing_waters_list_leaves_out_what_the_national_list_holds():
    d = json.loads((ROOT / "research" / "hi" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in d["rows"]}
    assert d["state"] == "HI" and d["waters"] == len(d["rows"]) and "Hilo Bay" not in names
    assert {"Kaneohe Bay", "Pearl Harbor", "Ala Wai Canal", "Lake Wilson"} <= names
    assert {s["name"] for s in d["same_name_on_islands"]} == {"Waimea Bay", "Kailua Bay"}
    rows = {(r["name"], r["island"]): r for r in d["rows"]}
    assert {("Waimea Bay", "Oahu"), ("Waimea Bay", "Kauai"), ("Kailua Bay", "Oahu"), ("Kailua Bay", "Hawaii")} <= set(rows)
    assert rows[("Waimea Bay", "Kauai")]["towns"] == ["Waimea"] and rows[("Waimea Bay", "Oahu")]["towns"][0] == "Pupukea"
    assert rows[("Waimea Bay", "Kauai")]["slug_hint"] == "waimea-bay-kauai-hi"
    assert all(r["towns"] and "county seat" not in r["towns_basis"] for r in d["rows"])
