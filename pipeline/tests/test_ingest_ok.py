"""Oklahoma: the National Park Service's E. coli table at Chickasaw National Recreation Area (tests/fixtures/
ok_nps_chickasaw_bacteria.html: the table, its key and the posting rule as read on 2026-11-14, last updated August 27,
2026; no person named): a sample is a sample, a result over the park's threshold is the site's caution from the sample
date, never an advisory and never a posting date; and the state's registry rows (operators, register, rules row, text,
waters)."""
import json
import re
from pathlib import Path

import pytest

import zones
from ingest import ok_nps_chickasaw_bacteria as N

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]
PAGE = (FIX / "ok_nps_chickasaw_bacteria.html").read_text()
T1, T2 = "2026-11-14T20:00:00Z", "2026-11-15T20:00:00Z"


def test_oklahoma_is_central_time():
    assert zones.zone_for("OK") == zones.CENTRAL and zones.zone_for("OK", 36.15, -95.99) == zones.CENTRAL
    assert N.TZ == zones.CENTRAL


def test_the_table_is_read_with_its_qualifiers_and_threshold():
    t = N.parse(PAGE)
    assert t["dates"] == ["2026-08-06", "2026-08-13", "2026-08-20", "2026-08-27"]
    assert sorted(r["place"] for r in t["rows"]) == sorted(N.PLACES) and len(t["rows"]) == 10
    assert (t["weekly"], t["mean_limit"]) == (235.0, 126.0)
    buck = next(r for r in t["rows"] if r["place"] == "Buckhorn Pavilion")
    cell = buck["results"]["2026-08-13"]
    assert (cell["text"], cell["qualifier"], cell["value"]) == ("<1", "<", 1.0)      # censored, never zero
    ln = next(r for r in t["rows"] if r["place"] == "Little Niagara")
    assert ln["results"]["2026-08-27"]["value"] == 160.7 and ln["mean"]["value"] == 113.6


def test_the_real_table_makes_no_record_since_no_result_reaches_the_threshold():
    recs, meta = N.build(PAGE, T1, [])
    assert recs == [] and meta["results"] == 40 and meta["censored"] == 8 and meta["over_threshold"] == 0
    assert meta["highest_result"] == {"value": 162.4, "place": "Bear Falls", "sampled_at": "2026-08-20"}
    assert meta["highest_mean"] == 113.6


def _over(page=PAGE):
    # synthetic: Bear Falls's August 20 result raised to 260, and Panther Falls's mean marked red by the park
    page = page.replace('<td style="text-align: center;">162.4</td>', '<td style="text-align: center;">260.0</td>')
    return page.replace('<td style="text-align: center;">56.0</td>',
                        '<td style="text-align: center;"><span style="color: #ff0000;">56.0</span></td>')


def test_a_result_over_the_threshold_is_a_sample_caution_dated_to_the_sample():
    recs, meta = N.build(_over(), T1, [])
    assert meta["over_threshold"] == 2
    r = next(x for x in recs if x["source_record_id"] == "bear-falls:2026-08-20")
    assert r["event_type"] == "beach_advisory" and r["status"] == "unknown"
    assert r["sampled_at"] == "2026-08-20" and r["started_at"] == "2026-08-20" and r["time_precision"] == "day"
    assert r["ended_at"] is None and r["reported_at"] is None and r["published_at"] is None
    assert r["raw"]["_agency_label_only"] is True and "235" in r["raw"]["_agency_label"]
    assert r["raw"]["time_zone"] == "America/Chicago" and r["waterbody_text"] == "Travertine Creek"
    assert (r["lat"], r["lon"], r["coord_source"]) == (34.51, -96.954, "gnis") and "1101917" in r["raw"]["point_url"]
    assert "not a posted notice" in r["advice_text"] and "no unit" in r["advice_text"]
    m = next(x for x in recs if x["source_record_id"] == "panther-falls:mean:2026-08-27")
    assert m["raw"]["kind"] == "mean" and "Values in red" in m["raw"]["_agency_label"]
    assert "does not say whether a sign was posted" in m["advice_text"]
    rules = json.loads((ROOT / "data" / "rules.json").read_text())["unresolved"]["sample_caution"]
    assert N.SOURCE_ID in rules["sources"] and rules["flag"] == "_agency_label_only"


def test_the_status_build_gives_the_sites_caution_never_the_authoritys_advisory():
    from datetime import datetime, timezone
    from build import status as S
    recs, _ = N.build(_over(), T1, [])
    r = next(x for x in recs if x["source_record_id"] == "bear-falls:2026-08-20")
    ivs = S.event_intervals(r, "OK", datetime(2026, 8, 21, tzinfo=timezone.utc), None)
    assert [iv["rule"] for iv in ivs] == ["sample_caution"]
    assert ivs[0]["rule_applied"]["hours"] == 72.0


def test_a_result_that_leaves_the_table_keeps_its_record_and_an_unreadable_page_keeps_all(tmp_path, monkeypatch):
    first, _ = N.build(_over(), T1, [])
    # the table moves on four weeks: the earlier samples have left it (not corrected), so their records stay
    later = PAGE
    for a, b in (("8/27/26", "9/24/26"), ("8/20/26", "9/17/26"), ("8/13/26", "9/10/26"), ("8/6/26", "9/3/26")):
        later = later.replace(a, b)
    second, meta = N.build(later, T2, first)
    assert meta["kept_from_previous"] == 2 and meta["corrected_below_threshold"] == []
    assert all(r["raw"]["_missing_from_source_since"] == T2 for r in second)
    assert all(r["sampled_at"] in ("2026-08-20", "2026-08-27") for r in second)
    with pytest.raises(ValueError, match="threshold"):
        N.parse(PAGE.replace("Threshold limit = weekly", "Limits:"))
    with pytest.raises(ValueError, match="table"):
        N.parse(PAGE.replace("Status of Bacterial Levels", "Results"))
    import common
    path = tmp_path / f"{N.SOURCE_ID}.json"
    monkeypatch.setattr(N, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(N.SOURCE_ID, first, path=path)
    bad = tmp_path / "bad.html"
    bad.write_text(PAGE.replace("Status of Bacterial Levels", "Results"))
    assert N.main(["--file", str(bad)]) == 1
    doc = json.loads(path.read_text())
    assert doc["ok"] is False and doc["count"] == 2


def test_the_fixture_names_no_person():
    assert not re.search(r"@|\(\d{3}\)\s*\d{3}-\d{4}|\bMr\.|\bMs\.", PAGE)


# ---- the registry rows -----------------------------------------------------------------------------------------

def _ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "OK"]


def test_every_oklahoma_permit_is_in_exactly_one_row():
    from collections import Counter
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "OK"}
    cand = json.loads((ROOT / "research" / "ok" / "private-utilities-candidates.json").read_text())
    wanted = plants | {c["npdes_permit"] for c in cand["candidates"]}
    assert all(every[p] == 1 for p in wanted), [p for p in wanted if every[p] != 1]
    held = {p for r in _ops() for p in r["npdes_permits"]}
    assert wanted <= held and len(plants) == 316
    okc = next(r for r in _ops() if r["id"] == "ok-oklahoma-city-water-utilities-trust")
    assert okc["npdes_permits"] == ["OK0027553", "OK0027561"] and "ok-okc-utilities" in okc["aliases"]
    city = next(r for r in _ops() if r["id"] == "ok-city-of-oklahoma-city")
    assert city["npdes_permits"] == ["OK0030520", "OK0036978", "OK0038385"] and city["legal_form"] == "city"
    for rid in ("ok-tulsa", "ok-broken-arrow", "ok-norman", "ok-lawton", "ok-sulphur"):
        assert sum(rid in r["aliases"] for r in _ops()) == 1


def test_oklahoma_legal_forms_scope_and_no_individual():
    from ingest import dischargers_schema as DS
    rows = _ops()
    assert not DS.check_legal_forms(rows)
    assert {r["id"] for r in rows if r["legal_form"] == "tribal"} == {"ok-seneca-cayuga-tribe",
                                                                      "ok-chickasaw-tribal-utilities-authority"}
    tribal = {"ok-seneca-cayuga-tribe", "ok-chickasaw-tribal-utilities-authority", "ok-permit-ok0044695",
              "ok-permit-ok0044733"}                 # the two permit-only rows of tribal scope keep the tribal channel
    for r in rows:
        assert ("tribal permit" in r["notification_channel"]) == (r["id"] in tribal), r["id"]
    choctaw = next(r for r in rows if r["id"] == "ok-choctaw-utilities-authority")
    assert choctaw["legal_form"] == "authority"                  # the City of Choctaw's, not a tribal body
    hidden = next(r for r in rows if "OK0034835" in r["npdes_permits"])
    assert hidden["legal_form"] == "facility (permittee not named)" and "OK0034835" in hidden["name"]
    for r in rows:
        assert "[name removed]" not in r["name"]
    channel = rows[0]["notification_channel"] if rows[0]["legal_form"] != "tribal" else rows[1]["notification_channel"]
    assert "24 hours" in channel and "48 hours" in channel and "605-011" in channel


def test_oklahoma_register_rows():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "ok.json").read_text())["channels"]}
    for r in _ops():
        row = reg[f"{r['id']}-deq-report"]
        assert row["urls"] == [] and row["barrier"] == "no_web_page" and row["records"] is False
    assert reg["ok-nps-chickasaw-bacteria"]["feed_source_id"] == N.SOURCE_ID
    assert reg["ok-usace-tulsa-district"]["barrier"] == "bot_wall"
    assert reg["ok-owrb-monitoring-data"]["barrier"] == "login_required"
    assert reg["ok-tulsa-sewer-overflow-line"]["barrier"] == "phone_only"
    assert "48 hours" in reg["ok-deq-bypass-sso-report"]["note"] and reg["ok-deq-wastewater-reporting-page"]["monitored"]


def test_oklahoma_rules_row_and_text():
    ok = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["OK"]
    assert ok["hours"] is None and "Part III B.6" in ok["source"] and "48 hours" in ok["basis"]
    assert not re.search(r"\b(safe|clean)\b", ok["basis"], re.I)
    t = (ROOT / "research" / "ok" / "state-text.md").read_text()
    assert t.startswith("---\nstate: OK\nname: Oklahoma\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t
    assert "48 hours" in t and "No sewage discharge report is published" in t and "never as the park's own notice" in t


def test_oklahoma_missing_waters_list():
    d = json.loads((ROOT / "research" / "ok" / "receiving-waters-missing.json").read_text())
    assert d["state"] == "OK" and d["waters"] == len(d["rows"])
    listed = {r["name"] for r in d["rows"]} | {r["name"] for r in d.get("resolved", [])}
    assert {N.PLACES[p][0] for p in N.PLACES} <= listed
    assert all(r["county"] == "Murray County" for r in d["rows"])


# ---- review fixes (Astra, 2026-11-15) --------------------------------------------------------------------------

from build import status as S  # noqa: E402


def _line(name, slug, coords, st="OK", kind="river"):
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return {"slug": slug, "name": name, "kind": kind, "state": st, "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "geometry": {"type": "LineString", "coordinates": coords}}


# synthetic waters: Rock Creek in Murray County (the park), a namesake in Osage County (about 240 km north), a qualified
# name in Murray County
OK_WATERS = {
    "rock-creek-ok": _line("Rock Creek", "rock-creek-ok", [[-96.99, 34.50], [-96.96, 34.51]]),
    "rock-creek-osage-ok": _line("Rock Creek", "rock-creek-osage-ok", [[-96.40, 36.60], [-96.37, 36.62]]),
    "little-rock-creek-ok": _line("Little Rock Creek", "little-rock-creek-ok", [[-97.05, 34.45], [-97.04, 34.46]]),
}


@pytest.fixture
def ok_live(monkeypatch):
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"OK"})
    return S


def _hole_record(value="300"):
    page = re.sub(r"(40 Ft Hole</strong></td>\s*<td[^>]*>)[^<]*", lambda m: m.group(1) + value, PAGE, count=1)
    recs, _ = N.build(page, T1, [])
    return next(r for r in recs if r["raw"]["place"] == "40 Ft Hole")


def test_p1_2_county_aware_placement_takes_the_murray_county_water_only(ok_live):
    assert S.COUNTY_STATES["OK"] == "ok-counties.json" and "OK" in S.COUNTY_FIELD_STATES
    assert S.named_county("OK", "Murray County")[1] == "Murray County"
    assert len(json.loads((ROOT / "data" / "reference" / "ok-counties.json").read_text())["counties"]) == 77
    hole = _hole_record()
    assert hole["lat"] is None and hole["raw"]["county"] == "Murray County" and hole["waterbody_text"] == "Rock Creek"
    res = S.Resolver(OK_WATERS, [], placement_rules={})
    assert res.resolve(hole)["water_slugs"] == ["rock-creek-ok"]           # not Osage's namesake, not Little Rock Creek
    alone = S.Resolver({"rock-creek-osage-ok": OK_WATERS["rock-creek-osage-ok"]}, [], placement_rules={})
    assert alone.resolve(hole)["water_slugs"] == []                        # a sole wrong-county namesake is refused
    little = S.Resolver({"little-rock-creek-ok": OK_WATERS["little-rock-creek-ok"]}, [], placement_rules={})
    assert little.resolve(hole)["water_slugs"] == []                       # a qualified name is another water


def test_p1_2_the_nv_ok_additions_change_no_other_states_placement(ok_live, monkeypatch):
    from test_ingest_or import OUTFALLS, SLOUGH, WILL, bes
    evs = list(bes()[0].values())

    def run():
        res = S.Resolver({"willamette-river-or": WILL, "columbia-slough-or": SLOUGH}, OUTFALLS, placement_rules={})
        return json.dumps([res.resolve(e) for e in evs], sort_keys=True, default=str)
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"OR", "NV", "OK"})
    with_new = run()
    monkeypatch.setattr(S, "COUNTY_FIELD_STATES", S.COUNTY_FIELD_STATES - {"NV", "OK"})
    monkeypatch.setattr(S, "COUNTY_STATES", {k: v for k, v in S.COUNTY_STATES.items() if k not in ("NV", "OK")})
    assert run() == with_new


def test_p1_4_nothing_personal_reaches_any_save(tmp_path, monkeypatch):
    import common
    from test_ingest_nv import PRIVATE, _Resp
    from ingest import notification_pages as NP
    from test_ingest_wi import _np_run
    page = PAGE.replace("40 Ft Hole</strong>", "40 Ft Hole (call Pat Example 775-555-0100)</strong>").replace(
        "Threshold limit", "Questions: pat@example.org, Jane Sample at home, 1234-A Example St. Threshold limit", 1)
    page = re.sub(r"(Veterans Lake</strong></td>\s*<td[^>]*>)[^<]*", lambda m: m.group(1) + "see Jane Sample", page, count=1)
    saved, writes = [], []
    monkeypatch.setattr(N, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(N, "save_raw", lambda src, body, ext: saved.append((ext, body)) or tmp_path / "raw")
    real = common.write_events
    monkeypatch.setattr(N, "write_events", lambda *a, **k: writes.append((a, k)) or real(
        *a, **{**k, "path": tmp_path / f"{N.SOURCE_ID}.json"}))
    monkeypatch.setattr(N.requests, "get", lambda *a, **k: _Resp(page))
    assert N.main([]) == 0
    assert len(saved) == 1 and saved[0][0] == "json" and "<td" not in saved[0][1] and "style" not in saved[0][1]
    blob = saved[0][1] + json.dumps(writes, default=str) + (tmp_path / f"{N.SOURCE_ID}.json").read_text()
    for p in PRIVATE:
        assert p not in blob, p
    rows = [r for r in json.loads((ROOT / "data" / "notice-channels" / "ok.json").read_text())["channels"]
            if r.get("monitored")]
    assert len(rows) == 3 and all(r["metadata_only"] is True and r["records"] is False for r in rows)
    personal = b"<html><body><p>Contact Pat Example, 775-555-0100, pat@example.org, 1234-A Example St.</p></body></html>"
    out, raws = _np_run(NP, rows, {u: personal for r in rows for u in r["urls"]}, tmp_path, "2026-11-15T12:00:00Z")
    assert raws == []


def _cell(page, place, n, text):
    """The n-th result cell (0-based) of a place's row set to text (invented values)."""
    def sub(m):
        cells = re.findall(r"<td[^>]*>[^<]*</td>", m.group(2))
        cells[n] = re.sub(r">[^<]*<", f">{text}<", cells[n], count=1)
        return m.group(1) + "\n".join(cells)
    return re.sub(rf"({re.escape(place)}</strong></td>\s*)((?:<td[^>]*>[^<]*</td>\s*)+)", sub, page, count=1)


def test_p2_6_a_corrected_sample_is_the_parks_corrected_value():
    hi = _cell(PAGE, "Bear Falls", 2, "260.0")                       # Bear Falls, 2026-08-20
    first, _ = N.build(hi, T1, [])
    assert [r["source_record_id"] for r in first] == ["bear-falls:2026-08-20"]
    # high -> low: the park corrected it; no caution stays on the sample
    second, meta = N.build(_cell(hi, "Bear Falls", 2, "20.0"), T2, first)
    assert second == [] and meta["kept_from_previous"] == 0
    assert meta["corrected_below_threshold"] == [{"source_record_id": "bear-falls:2026-08-20", "was": "260.0",
                                                  "now": "20.0", "seen_at": T2}]
    # low -> high: a record from the read that shows it
    third, _ = N.build(hi, "2026-11-16T20:00:00Z", second)
    assert [r["raw"]["result"]["text"] for r in third] == ["260.0"]
    # high -> other high: the same record with the corrected value
    fourth, _ = N.build(_cell(hi, "Bear Falls", 2, "300.0"), "2026-11-17T20:00:00Z", third)
    assert [(r["source_record_id"], r["raw"]["result"]["text"]) for r in fourth] == [("bear-falls:2026-08-20", "300.0")]
    # a mean corrected below its limit
    m_hi = _cell(PAGE, "Bear Falls", 4, "150.0")
    m1, _ = N.build(m_hi, T1, [])
    assert [r["source_record_id"] for r in m1] == ["bear-falls:mean:2026-08-27"]
    m2, meta = N.build(_cell(m_hi, "Bear Falls", 4, "100.0"), T2, m1)
    assert m2 == [] and meta["corrected_below_threshold"][0]["source_record_id"] == "bear-falls:mean:2026-08-27"


@pytest.mark.parametrize("text,kind,expect", [
    (">300", 2, "definite"), ("≥300", 2, "definite"), (">=235", 2, "definite"), (">200", 2, "possible"),
    ("<300", 2, "possible"), ("<1", 2, None), ("<235", 2, None), ("≤235", 2, "possible"), ("120", 2, None),
    (">130", 4, "definite"), (">100", 4, "possible"), ("<100", 4, None),
])
def test_p2_7_a_qualified_result_keeps_its_bound(text, kind, expect):
    recs, meta = N.build(_cell(PAGE, "Bear Falls", kind, text), T1, [])
    assert [r["raw"]["exceedance"] for r in recs] == ([expect] if expect else [])
    if expect:
        r = recs[0]
        assert r["raw"]["result"]["text"] == text and r["raw"]["_agency_label_only"] is True
        assert ("may be at or above" in r["raw"]["_agency_label"]) == (expect == "possible")
        assert text.replace(">=", "≥") in r["advice_text"] or text in r["advice_text"] or r["raw"]["result"]["qualifier"]


def test_p2_9_operators_are_the_permittees_epa_records():
    from nv_ok_evidence import unsupported
    assert unsupported("OK") == []
    rows = {r["id"]: r for r in _ops()}
    po = {rid for rid, r in rows.items() if r.get("permit_only")}
    assert po == {f"ok-permit-{p.lower()}" for p in ("OKG580038", "OK0066666", "OK0100731", "OK0032417", "OK0032425",
                                                     "OK0029190", "OKG580062", "OK0044695", "OK0044733", "OK0037982",
                                                     "OK0044971")}
    assert all(rows[r]["legal_form"] is None and "not counted as an operator" in rows[r]["notes"] for r in po)
    assert not [r for r in rows.values() if "owner not read" in r["name"] or "wastewater plant" in r["name"]]
    assert "ok-norman" in rows["ok-permit-ok0029190"]["aliases"]


def test_p2_10_only_municipal_permits_carry_the_municipal_clause():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "ok.json").read_text())["channels"]}
    ops = {r["id"]: r for r in _ops()}
    # an industrial company's permit (not read): the federal condition, unverified; never Part III B.6
    for rid in ("ok-vicinity-energy-tulsa-llc", "ok-umicore-optical-materials"):
        b = reg[f"{rid}-deq-report"]["legal_basis"]
        assert "Part III B.6" not in b and "unverified" in b, rid
        assert "Part III" not in ops[rid]["notification_channel"] and "unverified" in ops[rid]["notification_channel"]
    # a municipal POTW permit: the municipal clause
    tulsa = reg["ok-tulsa-metropolitan-utility-authority-deq-report"]["legal_basis"]
    assert "Part III B.6" in tulsa and "unverified" not in tulsa
    # a general-permit coverage: its own words, unverified
    b = reg["ok-mounds-public-works-authority-deq-report"]["legal_basis"]
    assert "OK0022888, Part III B.6" in b and "general permit coverage OKG580003" in b and "unverified" in b
    # a state prison's permit and a mobile-home park's: not municipal by EPA's record
    for rid in ("ok-oklahoma-department-of-corrections", "ok-lone-elm-mobile-home-park"):
        assert "Part III B.6" not in reg[f"{rid}-deq-report"]["legal_basis"], rid
    # tribal: the issuing agency not read
    assert "tribal; issuing agency not read" in reg["ok-permit-ok0044733-deq-report"]["legal_basis"]
    for rid, r in reg.items():
        if rid.endswith("-deq-report"):
            assert "expansion-research.md" not in r["note"]
