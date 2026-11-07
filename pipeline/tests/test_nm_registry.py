"""New Mexico's operator rows, register rows, rules row, state text and missing-waters list: every New Mexico permit in
one row, the Navajo Nation's and the Pueblos' permits on EPA's channel, no individual named, the law cited, the page in
the site's shape."""
import json
import re
from collections import Counter
from pathlib import Path

from ingest import dischargers_schema as DS

ROOT = Path(__file__).resolve().parents[2]


def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "NM"]


def register():
    return json.loads((ROOT / "data" / "notice-channels" / "nm.json").read_text())["channels"]


def test_every_new_mexico_permit_is_in_exactly_one_row():
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "NM"}
    cand = json.loads((ROOT / "research" / "nm" / "private-utilities-candidates.json").read_text())
    wanted = plants | {c["npdes_permit"] for c in cand["candidates"] + cand["public_by_name"]}
    assert all(every[p] == 1 for p in wanted), [p for p in wanted if every[p] != 1]
    held = {p for r in ops() for p in r["npdes_permits"]}
    assert wanted <= held and "NN0021555" not in held          # Window Rock stays Arizona's row
    assert {"NN0020621", "NN0030343", "NN0020800", "NN0020958", "NN0030325"} <= held


def test_tribal_and_navajo_nation_permits_carry_epas_channel_not_the_state_rule():
    for r in ops():
        tribal = r["legal_form"] == "tribal" or any(p.startswith("NN") for p in r["npdes_permits"])
        assert ("tribal land" in r["notification_channel"]) == tribal, r["id"]
        assert ("20.6.2.1203" in r["notification_channel"]) == (not tribal), r["id"]
        if any(p.startswith("NN") for p in r["npdes_permits"]):
            assert "Region 9" in r["notification_channel"]


def test_legal_forms_are_controlled_and_no_individual_is_named():
    rows = ops()
    assert not DS.check_legal_forms(rows)
    assert all(r["legal_form"] in DS.LEGAL_FORMS or r["legal_form"] is None for r in rows)
    g = next(r for r in rows if "NM0028088" in r["npdes_permits"])
    assert g["legal_form"] == "facility (permittee not named)" and g["name"].startswith("Glorieta Camps")
    # New Mexico's mutual domestic associations are public bodies under the Sanitary Projects Act
    name = "Mora Mutual Water and Sewer Works Association"
    assert not DS.check_legal_forms([{"id": "nm-x", "state": "NM", "name": name, "legal_form": "special district"}])
    # keyed on New Mexico: the same name elsewhere still warns (review 2026-11-07 P3-3)
    assert DS.check_legal_forms([{"id": "co-x", "state": "CO", "name": name, "legal_form": "special district"}])


def test_register_rows_per_operator_and_the_state_notice():
    reg = {c["id"]: c for c in register()}
    for r in ops():
        row = reg[f"{r['id']}-epa-report"]
        assert row["unmonitored_reason"] == "feed_ingested" and row["feed_source_id"] == "echo-sewer-overflow"
        assert row["basis_kind"] == "permit" and row["permit"] in r["npdes_permits"]
    nmed = reg["nm-nmed-discharge-notice"]
    assert nmed["basis_kind"] == "law" and "20.6.2.1203" in nmed["legal_basis"] and nmed["urls"] == []
    assert nmed["barrier"] == "phone_only"
    assert reg["nm-nmed-hab-mapper"]["feed_source_id"] == "nm-nmed-hab-mapper"
    assert reg["nm-swim-guide"]["urls"] == [] and reg["nm-rio-grande-bacteria"]["urls"] == []
    shiprock = reg["nm-navajo-tribal-utility-authority-epa-report"]
    assert "3 report(s) placed in New Mexico" in shiprock["note"]


def test_rules_row_cites_the_law_and_sets_no_window():
    nm = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["NM"]
    assert nm["hours"] is None and "20.6.2.1203" in nm["source"] and "is not shown on this site" in nm["basis"]
    assert not re.search(r"\b(safe|clean)\b", nm["basis"], re.I)


def test_state_text_is_in_the_page_shape_and_says_what_the_site_does():
    t = (ROOT / "research" / "nm" / "state-text.md").read_text()
    assert t.startswith("---\nstate: NM\nname: New Mexico\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean|counted but not placed)\b", t, re.I) and ".json" not in t
    assert "is not shown on this site" in t and "Navajo" in t and "not searched one by one" in t


def test_missing_waters_list_leaves_out_what_the_national_list_holds():
    d = json.loads((ROOT / "research" / "nm" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in d["rows"]}
    assert d["state"] == "NM" and "San Juan River" not in names and "Rio Grande" not in names
    # the names pass (batch/nm-2026-11-07) resolved Eagle Nest Lake and Quemado Lake to openboatlaunch's records, so
    # the file lists only names no record holds
    have = {w["name"] for f in ("waters-nm.json", "waters-nhd.json")
            for w in json.loads((ROOT / "data" / f).read_text())["waters"] if w.get("state") == "NM"}
    assert not (names & have) and d["waters"] == len(d["rows"])
