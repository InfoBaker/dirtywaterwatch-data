"""Iowa and Idaho: the operator rows (scripts/add_ia_operators.py, scripts/add_id_operators.py), the registers
(data/notice-channels/ia.json, id.json), the rules rows, the combined sewer outfalls' caution, the state texts and the
missing-waters lists. Read from the committed data files; nothing here asserts either state's place in live_states."""
import json
import re
from pathlib import Path

import pytest

from build import rain_likely as RL
from common import scrub_discharger

ROOT = Path(__file__).resolve().parents[2]


def ops(st):
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == st]


def register(st):
    return {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / f"{st}.json").read_text())["channels"]}


@pytest.mark.parametrize("st", ["IA", "ID"])
def test_every_permit_is_held_once_and_no_row_is_a_person(st):
    rows = ops(st)
    permits = [p for r in rows for p in r["npdes_permits"]]
    assert len(permits) == len(set(permits))
    every = [p for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") != st
             for p in r.get("npdes_permits") or []]
    assert not set(permits) & set(every)                          # no other state's row holds one
    for r in rows:
        assert scrub_discharger({"discharger_name": r["name"]})["discharger_name"] == r["name"], r["name"]
        assert r["npdes_permit"] == r["npdes_permits"][0] and r["id"].startswith(st.lower() + "-")


def test_iowa_operators_cover_every_plant_permit_and_the_nine_cso_systems():
    rows = ops("IA")
    held = {p for r in rows for p in r["npdes_permits"]}
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if str(r.get("npdes_permit") or "").startswith("IA")}
    assert plants <= held
    cso = {r["npdes_permits"][0]: r for r in rows if r["kind"] == "cso"}
    assert set(cso) == {"IA0043079", "IA0035947", "IA0044130", "IA0027219", "IA0042609", "IA0023434", "IA0058611",
                        "IA0021059", "IA0047961"}
    assert cso["IA0044130"]["name"] == "Des Moines Metropolitan Wastewater Reclamation Authority"


def test_idaho_rows_say_who_issues_the_permit_and_a_plant_label_is_permit_only():
    rows = ops("ID")
    assert all(set(r["permitting_authority"]) <= {"IDEQ", "EPA", "unconfirmed"} for r in rows)
    epa = [r for r in rows if r["permitting_authority"] == ["EPA"]]
    assert len(epa) == 13 and all("EPA" in r["notification_channel"] for r in epa)
    elk = next(r for r in rows if "ID0027979" in r["npdes_permits"])
    assert elk["permit_only"] is True and elk["legal_form"] == "facility (permittee not named)"
    assert "not established" in elk["notes"] and "(permit ID0027979)" in elk["name"]
    # every other row names a body (a legal form), never a plant
    assert not [r["name"] for r in rows if not r.get("permit_only") and not r.get("legal_form")]


def test_iowa_register_names_each_cso_permittee_and_the_feeds():
    reg = register("ia")
    for r in ops("IA"):
        if r["kind"] == "cso":
            row = reg[f"{r['id']}-cso-public-notification"]
            assert row["name"] == r["name"] and row["permit"] == r["npdes_permits"][0]
            assert row["barrier"] == "no_web_page" and row["legal_basis"]
    dm = next(c for c in reg.values() if c.get("permit") == "IA0044130" and c["id"].endswith("-cso-public-notification"))
    assert "connect time-out" in dm["note"]                      # a time-out is a barrier recorded, never got around
    assert reg["ia-dnr-news-releases"]["feed_source_id"] == "ia-dnr-news-releases"
    assert "four municipal wastewater releases" in reg["ia-dnr-news-releases"]["note"]
    assert reg["ia-waterloo-sso-bypass-page"]["feed_source_id"] == "ia-waterloo-sso-notices"
    focomp = [c for c in reg.values() if c.get("feed_source_id") == "ia-dnr-focomp-incoming-reports"]
    assert len(focomp) >= 90 and all(c["legal_basis"].startswith("567 IAC 63.6") for c in focomp)


def test_idaho_register_has_a_report_row_per_operator_with_its_barrier():
    reg = register("id")
    for r in ops("ID"):
        row = reg[f"{r['id']}-noncompliance-report"]
        assert row["barrier"] == "no_web_page" and row["publishes"] == "none"
    assert reg["id-deq-cyanohab-risk-table"]["feed_source_id"] == "id-deq-cyanohab-risk-table"
    assert reg["id-ipdes-e-permitting"]["barrier"] == "login_required"


def test_rules_rows():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ia, idh = rules["red"]["by_state"]["IA"], rules["red"]["by_state"]["ID"]
    assert ia["hours"] is None and "567 IAC 63.6" in ia["source"]
    assert idh["hours"] is None and "49 CFR 71.9" in idh["source"] and "no Idaho sewage report" in idh["basis"]
    for row in (ia, idh):
        assert not re.search(r"\b(safe|clean)\b", row["basis"], re.I)
    assert "id-deq-cyanohab-risk-table" in rules["unresolved"]["sample_caution"]["sources"]
    assert {"ia-dnr-news-releases", "ia-dnr-focomp-incoming-reports"} <= set(rules["unresolved"]["day_start_caution"]["sources"])


def test_iowa_closed_cso_outfalls_carry_no_rain_caution():
    rows = [r for r in json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"] if r.get("state") == "IA"]
    closed = [r for r in rows if str(r["outfall_status"]).upper().startswith("CLS")]
    open_ = [r for r in rows if RL.cso_open(r)]
    assert len(closed) == 45 and not any(RL.cso_open(r) for r in closed)
    assert len(open_) == 39 and len({r["npdes_permit"] for r in open_}) == 9
    # Des Moines' three open outfalls keep the caution (owner question: the Authority's elimination notice was not read)
    assert len([r for r in open_ if r["npdes_permit"] == "IA0044130"]) == 3


@pytest.mark.parametrize("st,name", [("ia", "Iowa"), ("id", "Idaho")])
def test_state_text_is_in_the_page_shape(st, name):
    t = (ROOT / "research" / st / "state-text.md").read_text()
    assert t.startswith(f"---\nstate: {st.upper()}\nname: {name}\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t


def test_idaho_text_says_plainly_that_no_sewage_report_is_public():
    t = (ROOT / "research" / "id" / "state-text.md").read_text()
    assert "No Idaho sewage report is public." in t and "shows only blooms for Idaho" in t
    assert "13 under a health advisory, 1 at the Health Alert level and 5 at the Health Watch level" in t


def test_iowa_text_counts_follow_the_feeds():
    t = (ROOT / "research" / "ia" / "state-text.md").read_text()
    assert "359 bypass and overflow reports" in t and "from 76 facilities" in t and "17 notices" in t
    assert "The 39 combined sewer outfalls" in t and "the 45 it lists as closed" in t


@pytest.mark.parametrize("st", ["ia", "id"])
def test_missing_waters_lists_keep_county_and_accept_a_resolved_name(st):
    d = json.loads((ROOT / "research" / st / "receiving-waters-missing.json").read_text())
    assert d["state"] == st.upper() and d["rows"]
    for r in d["rows"]:                     # a name the names pass resolves moves to "resolved" (with its record)
        assert r["county"] and r["reports"] >= 1
        for lat, lon in r.get("points") or []:
            assert round(lat, 3) == lat and round(lon, 3) == lon
    if st == "id":
        arms = {(r["name"], tuple(r.get("parts") or ())) for r in d["rows"]}
        # the water batch (2026-11-16) built C J Strike Reservoir's record, so its two arms moved to "resolved"
        assert {a[0] for a in arms} == {"Hordemann Pond", "Weston Reservoir"}
        assert "C J Strike Reservoir" in {r["name"] for r in d["resolved"]}
