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
    second, meta = N.build(PAGE, T2, first)
    assert meta["kept_from_previous"] == 2
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
    assert len(okc["npdes_permits"]) == 5 and "ok-okc-utilities" in okc["aliases"]
    for rid in ("ok-tulsa", "ok-broken-arrow", "ok-norman", "ok-lawton", "ok-sulphur"):
        assert sum(rid in r["aliases"] for r in _ops()) == 1


def test_oklahoma_legal_forms_scope_and_no_individual():
    from ingest import dischargers_schema as DS
    rows = _ops()
    assert not DS.check_legal_forms(rows)
    tribal = {r["id"] for r in rows if r["legal_form"] == "tribal"}
    assert {"ok-seneca-cayuga-tribe", "ok-otoe-missouria-tribe", "ok-kickapoo-wwtp",
            "ok-chickasaw-tribal-utilities-authority"} == tribal
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
