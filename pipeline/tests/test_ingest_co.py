"""Colorado: CDPHE's toxic algae sheet, the reviewed set of official notices, the operator rows, the register, the
rules row, the state text and the missing-waters list. Fixtures: real rows of the sheet (no personal data: four columns
of water names, conditions, dates and the agency's notes) and synthetic pages built from the notices' quoted sentences
with an invented contact line, so a test proves the page and its contact never reach a record or a raw save.
Run from pipeline/: python -m pytest tests/test_ingest_co.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import co_cdphe_toxic_algae as A  # noqa: E402
from ingest import co_official_notices as C  # noqa: E402
from ingest import notice_set as NS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "co"
T0 = "2026-11-14T23:30:00Z"
T1 = "2026-11-15T23:30:00Z"


def sheet() -> str:
    return (FIX / "toxic_algae_sheet.csv").read_text()


def by_water(recs):
    return {r["waterbody_text"]: r for r in recs}


# ---------------------------------------------------------------- the toxic algae sheet

def test_sheet_runs_become_advisories_and_no_bloom_rows_none():
    recs, meta = A.build(sheet(), T0, [])
    w = by_water(recs)
    assert set(w) == {"Barr Lake", "Cherry Creek Reservoir", "Blue Heron Lake", "Windsor Lake",
                      "Eleven Mile Reservoir", "Blue Mesa Reservoir"}
    assert "Antero Reservoir" not in w and "Jumbo Reservoir" not in w      # only "No bloom reported" rows
    assert all(r["event_type"] == "hab_advisory" for r in recs)
    assert meta["rows"] == 28 and meta["advisories"] == 6


def test_sheet_end_is_the_next_no_bloom_row_at_day_precision():
    w = by_water(A.build(sheet(), T0, [])[0])
    cc = w["Cherry Creek Reservoir"]
    assert (cc["status"], cc["started_at"], cc["ended_at"]) == ("advisory_lifted", "2026-05-08", "2026-06-01")
    assert cc["raw"]["ended_at_precision"] == "day" and "6/1/2026" in cc["raw"]["end_basis"]
    assert [u["date"] for u in cc["raw"]["updates"]] == ["2026-05-08", "2026-05-20"]
    assert cc["time_precision"] == "day" and cc["raw"]["time_zone"] == "America/Denver"


def test_sheet_current_condition_is_confirmed_at_each_read_without_an_invented_end():
    w = by_water(A.build(sheet(), T0, [])[0])
    barr = w["Barr Lake"]
    assert barr["status"] == "advisory_active" and barr["ended_at"] is None
    assert barr["raw"]["_last_seen_in_source"] == T0
    assert barr["raw"]["condition_max"] == "Warning" and barr["raw"]["condition_last"] == "Warning"
    assert barr["started_at"] == "2026-05-13"           # the run began with the Caution of May 13


def test_sheet_third_party_kept_in_its_words():
    w = by_water(A.build(sheet(), T0, [])[0])
    assert w["Blue Mesa Reservoir"]["raw"]["_agency_label"] == "Third party"
    assert w["Windsor Lake"]["status"] == "advisory_lifted" and w["Windsor Lake"]["ended_at"] == "2026-07-24"


def test_sheet_out_of_order_date_kept_and_listed_never_starting_a_run():
    em = by_water(A.build(sheet(), T0, [])[0])["Eleven Mile Reservoir"]
    assert em["started_at"] == "2026-08-03"
    assert "2024-08-26" in [u["date"] for u in em["raw"]["updates"]]
    assert em["raw"]["date_anomalies"] and "8/26/2024" in em["raw"]["date_anomalies"][0]


def test_sheet_qualifier_kept_as_place():
    bh = by_water(A.build(sheet(), T0, [])[0])["Blue Heron Lake"]
    assert bh["raw"]["place"] == "St. Vrain State Park"
    assert bh["raw"]["placement_hint"]["state"] == "CO"


def test_sheet_current_advisory_gone_from_a_later_read_ends_at_that_read():
    first, _ = A.build(sheet(), T0, [])
    trimmed = "\n".join(line for line in sheet().splitlines() if not line.startswith("Barr Lake,Warning,8/12"))
    second, meta = A.build(trimmed, T1, first)
    barr = [r for r in second if r["waterbody_text"] == "Barr Lake"]
    assert len(barr) == 1                                # the run is the same: still current
    gone = "\n".join(line for line in sheet().splitlines() if not line.startswith("Barr Lake,"))
    third, meta = A.build(gone, T1, first)
    b = [r for r in third if r["waterbody_text"] == "Barr Lake"][0]
    assert b["raw"]["_unlisted_since"] == T1 and b["raw"]["ended_at_precision"] == "poll"
    assert b["ended_at"] is None and meta["kept_from_previous"] == 1


def test_sheet_changed_columns_fail_loudly():
    with pytest.raises(ValueError):
        A.build("Lake,Status,Date\nX,Caution,1/1/2026\n", T0, [])


# ---------------------------------------------------------------- the reviewed notices

CONTACT = "Example Person, Public Information Officer, 555-0100, example.person@example.gov"


def page_for(url: str, drop: str | None = None) -> str:
    """A synthetic page: the notice's quoted sentences with an invented contact line, as HTML."""
    n = next(x for x in C.NOTICES if x["url"] == url)
    qs = [q for r in n["records"] for q in r.get("quotes") or []]
    body = "".join(f"<p>{q}</p>" for q in qs if q != drop)
    return f"<html><body><h1>Notice</h1><p>{CONTACT}</p>{body}</body></html>"


def getter(drop=None, fail=()):
    def g(url):
        if url in fail:
            return None, None, "ConnectTimeout: timed out"
        return 200, NS.page_text(page_for(url, drop)), None
    return g


def test_notices_build_the_reviewed_records_when_every_quote_is_on_the_page():
    recs, meta = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    ids = {r["source_record_id"]: r for r in recs}
    spill = ids["pueblo-arkansas-river-2026-08-26"]
    assert spill["event_type"] == "sso" and spill["status"] == "ended"
    assert (spill["started_at"], spill["ended_at"], spill["time_precision"]) == ("2026-08-26", "2026-08-27", "day")
    assert spill["volume_gal"] == 4200000 and spill["npdes_permit"] == "CO0026646"
    assert spill["discharger_id"] == "co-co0026646" and spill["raw"]["county"] == "Pueblo"
    adv = ids["john-martin-water-contact-advisory-2026-08-31"]
    assert adv["status"] == "advisory_active" and adv["ended_at"] is None
    assert adv["parent_event_id"] == spill["event_id"] and "_last_seen_in_source" not in adv["raw"]
    assert ids["blue-mesa-iola-basin-2026-08-13"]["event_type"] == "hab_advisory"
    assert meta["pages_read"] == 3


def test_standing_notice_confirmed_while_shown_and_ended_at_the_first_read_without_it():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    barr = next(r for r in first if r["source_record_id"].startswith("barr-lake"))
    assert barr["raw"]["_last_seen_in_source"] == T0 and barr["started_at"] == "2026-08-03T19:00:00-06:00"
    q = C.NOTICES[2]["records"][0]["quotes"][0]
    second, _ = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(drop=q), save=False)
    barr2 = next(r for r in second if r["source_record_id"].startswith("barr-lake"))
    assert barr2["raw"]["_unlisted_since"] == T1 and barr2["raw"]["_last_seen_in_source"] == T0
    assert barr2["ended_at"] is None and barr2["raw"]["ended_at_precision"] == "poll"


def test_a_page_that_does_not_answer_keeps_the_previous_records_and_a_never_read_page_makes_none():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    second, meta = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(fail=(C.CPW_JM,)), save=False)
    assert {r["event_id"] for r in second} == {r["event_id"] for r in first}
    assert meta["pages_read"] == 2
    none, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(fail=(C.CPW_JM,)), save=False)
    assert not any(r["source_record_id"].startswith(("pueblo", "john-martin")) for r in none)


def test_a_dated_notice_whose_sentence_left_the_page_is_kept_and_flagged():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    q = C.NOTICES[0]["records"][0]["quotes"][1]
    second, _ = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(drop=q), save=False)
    spill = next(r for r in second if r["source_record_id"].startswith("pueblo"))
    assert spill["raw"]["quotes_missing"] == [q]


def test_no_page_text_or_contact_reaches_a_record_or_the_raw_save(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(NS, "save_raw", lambda sid, content, ext: saved.setdefault("x", content))
    recs, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter())
    blob = json.dumps(recs) + saved["x"]
    for bad in ("Example Person", "555-0100", "example.person@example.gov"):
        assert bad not in blob


def test_every_quote_is_found_in_its_own_synthetic_page_after_normalisation():
    for n in C.NOTICES:
        text = NS.page_text(page_for(n["url"]))
        found, missing = NS.check(text, [q for r in n["records"] for q in r["quotes"]])
        assert not missing, (n["id"], missing)


# ---------------------------------------------------------------- operators, register, rules, text, waters

def co_rows():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
            if r.get("state") == "CO" and "co" in (r.get("source_areas") or [])]


def test_every_colorado_plant_permit_is_in_exactly_one_row():
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "CO"}
    held = [p for r in co_rows() for p in r["npdes_permits"]]
    assert len(held) == len(set(held))
    assert plants <= set(held)
    research = {r["id"] for r in json.loads((ROOT / "research" / "co" / "dischargers.json").read_text())}
    aliases = {a for r in co_rows() for a in r["aliases"]}
    assert research <= aliases


def test_epa_issued_permits_carry_epa_channel_and_state_permits_the_division():
    rows = {r["id"]: r for r in co_rows()}
    assert rows["co-southern-ute-indian-tribe"]["legal_form"] == "tribal"
    assert "EPA Region 8" in rows["co-southern-ute-indian-tribe"]["notification_channel"]
    assert "CO0021181" in rows["co-u-s-department-of-the-army-fort-carson"]["epa_issued_permits"]
    assert "25-8-601(2)" in rows["co-co0026646"]["notification_channel"]
    assert rows["co-co0026646"]["kind"] == "sso"
    assert rows["co-co0026638"]["name"] == "Metro Water Recovery"


def test_no_operator_row_is_named_for_a_person():
    sys.path.insert(0, str(ROOT / "scripts"))
    import mountain_operator_rows as M
    for r in co_rows():
        assert not M.personish(r["name"]), r["name"]
        assert "[name removed]" not in r["name"]


def test_register_rows_validate_and_cover_every_operator():
    from ingest import notification_pages as NP
    doc = NP.load_register(ROOT / "data" / "notice-channels")
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    assert not NP.validate_register(doc, dis, ROOT)
    co = [r for r in doc["channels"] if r["state"] == "CO"]
    ops = {r["operator_id"] for r in co if r.get("operator_id")}
    assert {r["id"] for r in co_rows()} <= ops
    ids = {r["id"] for r in co}
    assert {"co-cdphe-toxic-algae-sheet", "co-official-notices", "co-wqcd-spill-reports", "co-pueblo-news"} <= ids


def test_rules_row_sets_no_window_and_cites_the_statute():
    row = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["CO"]
    assert row["hours"] is None and "25-8-601(2)" in row["source"] and "Mountain time" in row["basis"]


def test_state_text_has_the_six_paragraphs_and_the_placeholders():
    t = (ROOT / "research" / "co" / "state-text.md").read_text()
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t.replace("as clean water", ""))
    assert "research/" not in t and ".json" not in t


def test_missing_waters_list_names_the_records_waters_or_their_resolution():
    doc = json.loads((ROOT / "research" / "co" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in doc["rows"]}
    assert doc["state"] == "CO" and doc["reports"] + doc["resolved_reports"] >= 4
    assert "Barr Lake" in names or doc["resolved_names"] >= 1
