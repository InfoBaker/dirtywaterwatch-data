"""Idaho go-live audit fixes (2026-11-16): the permits' public notification duty in the text, rule and register (P1),
Idaho in EPA's shared overflow feed (P2) and the Watch label as DEQ's own level (P2)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from ingest import echo_sewer_overflow_events as E
from tests.test_ia_id_review import ROWS, iv_at, run_main

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ P1 the law

def test_text_and_rule_state_the_two_permits_duty_and_no_more():
    t = (ROOT / "research" / "id" / "state-text.md").read_text()
    assert "permit condition found requires" not in t
    assert "Kooskia's 2026 draft and West Boise's earlier permit" in t
    assert "notify the public, health agencies and other affected entities immediately" in t
    assert "No Idaho statute or rule requires public notice" in t
    rule = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["ID"]
    assert "permit condition found" not in rule["basis"] and "2026 draft for Kooskia" in rule["basis"]
    assert "ID0023981 (2016 modification) and ID0021814 (2026 draft), Part III.I" in rule["source"]


def test_permit_rows_change_only_their_note_by_what_was_read():
    doc = json.loads((ROOT / "data" / "notice-channels" / "id.json").read_text())
    rows = [r for r in (doc if isinstance(doc, list) else doc["channels"]) if r.get("basis_kind") == "permit"]
    dis = {o["id"]: o for o in json.loads((ROOT / "data" / "dischargers.json").read_text()) if o.get("state") == "ID"}
    assert len(rows) == 118 and all(r["barrier"] == "no_web_page" for r in rows)
    assert not any("no public notice requirement was found" in r["note"] for r in rows)
    by = {r["operator_id"]: r["note"] for r in rows}
    assert "2026 draft permit (ID0021814, Part III.I)" in by["id-kooskia"]
    assert "ID0023981, 2016 modification, Part III.I" in by["id-boise"]
    epa = [o for o, n in by.items() if "this permit's text was not read" in n]
    assert sorted(epa) == sorted(o for o in dis if dis[o].get("permitting_authority") == ["EPA"] and o != "id-kooskia")
    rest = [o for o, n in by.items() if n.endswith("the permit's public notice terms were not read.")]
    assert len(epa) == 12 and len(rest) == 104


# ------------------------------------------------------------------------------------------------ P2 EPA's feed

def test_idaho_is_read_mountain_and_pacific_north_of_the_salmon_river():
    assert "ID" in E.STATES and E.STATE_TZ["ID"] == "America/Denver" and "ID" in E.FREE_TEXT_STATES
    assert "ID" in E.ZONE_ALWAYS_STATES
    assert E.point_zone("ID", 43.6, -116.2)[0] == "America/Denver"           # Boise
    zone, basis = E.point_zone("ID", 46.42, -117.0)                            # Lewiston, Nez Perce County
    assert zone == "America/Los_Angeles" and "north of the Salmon River" in basis
    assert E.point_zone("ID", 46.23, -116.03)[0] == "America/Los_Angeles"    # Kamiah, Idaho County north of the river
    assert E.point_zone("ID", None, None)[0] == "America/Denver"


def test_adding_idaho_changes_no_other_states_record(monkeypatch):
    from tests.test_ingest_dc import _row
    from tests.test_ingest_in import _fixture, _build
    fx = _fixture()
    rows = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
            _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                 sewer_overflow_bypass_description_text="Operator Jane Example reported a break at a manhole."),
            _row(sewer_overflow_bypass_event_key="i1", permit_identifier="ID0000001", program_report_form_set_id="3",
                 latitude_measure="46.42", longitude_measure="-117.00",
                 sewer_overflow_bypass_description_text="Manhole overflow to Example Creek.")]
    fx["events"] += rows
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": "SSO",
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k in ("o1", "o2", "i1")]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": k, "name_receiving_water": w}
                     for k, w in (("o1", "Rock Creek"), ("o2", "Sample Creek"), ("i1", "Example Creek"))]

    def build(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(copy.deepcopy(fx))
        return kept, sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                            for r in kept + dropped
                            if not str(r.get("npdes_permit") or r.get("permit")).startswith("ID"))
    (kept, with_id), (_, without_id) = build(set(E.STATES)), build(set(E.STATES) - {"ID"})
    assert with_id == without_id and len(with_id) >= 3
    idr = [r for r in kept if str(r.get("npdes_permit")).startswith("ID")]
    assert len(idr) == 1 and idr[0]["raw"]["time_zone"] == "America/Los_Angeles"
    assert "north of the Salmon River" in idr[0]["raw"]["timezone_note"]


def test_the_epa_register_row_and_source_are_read_by_the_feed():
    doc = json.loads((ROOT / "data" / "notice-channels" / "id.json").read_text())
    r = next(x for x in (doc if isinstance(doc, list) else doc["channels"]) if x["id"] == "id-epa-echo-overflow-events")
    assert r["unmonitored_reason"] == "feed_ingested" and r["feed_source_id"] == "echo-sewer-overflow"
    assert r["barrier"] is None and r["urls"] and r["channel_kind"] == "feed"
    y = (ROOT / "data" / "sources" / "id-epa-sobe.yaml").read_text()
    assert re.search(r"^enabled: true$", y, re.M) and "(file of 2026-11-13)" in y


# ------------------------------------------------------------------------------------------------ P2 the Watch label

def test_a_watch_is_labelled_as_deqs_level_never_as_an_advisory_or_clean(monkeypatch, tmp_path):
    names = [r[1] for r in ROWS]
    _, _, recs = run_main(monkeypatch, tmp_path, ROWS, names, "2026-11-20T23:00:00Z")
    ivs = iv_at(recs["specimen-pond"], "2026-11-21T00:30:00+00:00")
    assert ivs and ivs[0]["rule"] == "sample_caution" and ivs[0]["color"] == "yellow"
    lab = ivs[0]["label"]
    assert lab == "Health Watch, Idaho DEQ's risk level; no health advisory issued: the site's caution"
    assert "Elevated result" not in lab and not re.search(r"\b(safe|clean)\b|advisory in effect", lab, re.I)


def test_the_label_is_keyed_on_the_record_so_other_sample_cautions_keep_theirs():
    from build import status as S
    from tests.test_ia_id_review import RULES
    names = [r[1] for r in ROWS]
    ev = {"event_id": "x:1", "source_id": "id-deq-cyanohab-risk-table", "event_type": "hab_advisory",
          "status": "unknown", "started_at": "2026-11-10", "time_precision": "day",
          "raw": {"_agency_label_only": True}}
    from datetime import datetime
    out = S.event_intervals(ev, "ID", datetime.fromisoformat("2026-11-10T12:00:00+00:00"), None, RULES)
    assert names and out and out[0]["label"] == S.RULES["sample_caution"][1]
