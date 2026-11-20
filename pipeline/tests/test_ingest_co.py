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
    assert b["ended_at"] == T1 and b["raw"]["_ages_after_confirmation"] is True and meta["kept_from_previous"] == 1


def test_sheet_changed_columns_fail_loudly():
    with pytest.raises(ValueError):
        A.build("Lake,Status,Date\nX,Caution,1/1/2026\n", T0, [])


# ---------------------------------------------------------------- the reviewed notices

CONTACT = "Example Person, Public Information Officer, 555-0100, example.person@example.gov"


def page_for(url: str, drop: str | None = None) -> str:
    """A synthetic page: the notice's quoted sentences with an invented contact line, as HTML."""
    n = next(x for x in C.NOTICES if x["url"] == url)
    qs = [q for r in n["records"] for q in r.get("quotes") or []]
    drops = (drop,) if isinstance(drop, str) or drop is None else tuple(drop)
    body = "".join(f"<p>{q}</p>" for q in qs if q not in drops)
    return f"<html><body><h1>Notice {n.get('anchor') or ''}</h1><p>{CONTACT}</p>{body}</body></html>"


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
    assert adv["raw"]["related_event_id"] == spill["event_id"] and not adv.get("parent_event_id") \
        and "_last_seen_in_source" not in adv["raw"]
    assert ids["blue-mesa-iola-basin-2026-08-13"]["event_type"] == "hab_advisory"
    assert meta["pages_read"] == 3


def test_standing_notice_confirmed_while_shown_and_ended_at_the_first_read_without_it():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    barr = next(r for r in first if r["source_record_id"].startswith("barr-lake"))
    assert barr["raw"]["_last_seen_in_source"] == T0 and barr["started_at"] == "2026-08-03T19:00:00-06:00"
    q = C.NOTICES[2]["records"][0]["quotes"]          # the whole notice gone (one sentence alone: unresolved)
    second, _ = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(drop=q), save=False)
    barr2 = next(r for r in second if r["source_record_id"].startswith("barr-lake"))
    assert barr2["raw"]["_unlisted_since"] == T1 and barr2["raw"]["_last_seen_in_source"] == T0
    assert barr2["ended_at"] == T1 and barr2["raw"]["ended_at_precision"] == "poll"
    assert barr2["raw"]["_ages_after_confirmation"] is True


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
              "Known problems in the data", "What we do about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t.replace("as clean water", ""))
    assert "research/" not in t and ".json" not in t


def test_missing_waters_list_names_the_records_waters_or_their_resolution():
    doc = json.loads((ROOT / "research" / "co" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in doc["rows"]}
    assert doc["state"] == "CO" and doc["reports"] + doc["resolved_reports"] >= 4
    assert "Barr Lake" in names or doc["resolved_names"] >= 1


# ---------------------------------------------------------------- the reviews' lessons (2026-11-15), on invented data

def test_lesson_an_absence_seen_months_later_does_not_colour_the_gap():
    from datetime import datetime, timedelta, timezone
    from build import status as S
    first, _ = A.build(sheet(), T0, [])
    gone = "\n".join(line for line in sheet().splitlines() if not line.startswith("Barr Lake,"))
    late = "2027-02-01T12:00:00Z"
    b = [r for r in A.build(gone, late, first)[0] if r["waterbody_text"] == "Barr Lake"][0]
    reds = [iv for iv in S.event_intervals(b, "CO", datetime(2027, 2, 2, tzinfo=timezone.utc)) if iv["color"] == "red"]
    seen = datetime.fromisoformat(T0.replace("Z", "+00:00"))
    assert reds and max(iv["end"] for iv in reds) <= seen + timedelta(days=14)


def test_lesson_a_standing_notice_whose_page_is_not_the_page_ends_nothing():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)

    def error_page(url):
        return 200, NS.page_text("<html><body>We are down for maintenance</body></html>"), None
    second, meta = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=error_page, save=False)
    barr = next(r for r in second if r["source_record_id"].startswith("barr-lake"))
    assert barr["ended_at"] is None and "_unlisted_since" not in barr["raw"]
    assert any("anchor" in (p["error"] or "") for p in meta["pages"])


def test_lesson_the_john_martin_advisory_ages_although_its_type_is_sewage():
    from datetime import datetime, timedelta, timezone
    from build import status as S
    recs, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    adv = next(r for r in recs if r["source_record_id"].startswith("john-martin"))
    ivs = S.event_intervals(adv, "CO", datetime(2026, 11, 15, tzinfo=timezone.utc))
    reds = [iv for iv in ivs if iv["color"] == "red"]
    assert reds and all(iv["end"] is not None for iv in reds)
    assert max(iv["end"] for iv in reds) <= datetime(2026, 9, 1, 6, tzinfo=timezone.utc) + timedelta(days=14)


def test_lesson_a_truncated_sheet_is_a_failed_read():
    with pytest.raises(ValueError):
        A.build("\n".join(sheet().splitlines()[:3]), T1, [], previous_rows=len(sheet().splitlines()) - 1)
    with pytest.raises(ValueError):
        A.build("Waterbody name,Condition Category,Update Date,Other notes\n", T1, [])


def test_lesson_a_note_naming_a_person_is_scrubbed_in_records_and_the_raw_save():
    text = sheet() + "\nExample Pond,Caution,9/1/2026,contact Example Person at 555-0100 or example.person@example.org\n"
    recs, _ = A.build(text, T0, [])
    blob = json.dumps(recs) + A.scrubbed_csv(text)
    assert "555-0100" not in blob and "example.org" not in blob


def test_lesson_reissue_after_no_bloom_is_a_second_record():
    text = sheet() + "\nExample Pond,Caution,7/1/2026,\nExample Pond,No bloom reported,7/20/2026,\n" \
        "Example Pond,Warning,9/1/2026,\n"
    ponds = sorted((r["started_at"], r["ended_at"]) for r in A.build(text, T0, [])[0]
                   if r["waterbody_text"] == "Example Pond")
    assert ponds == [("2026-07-01", "2026-07-20"), ("2026-09-01", None)]


# ---------------------------------------------------------------- Astra review 2026-11-15 (fix/co-mt-wy-review)

def _run_sheet(tmp_path, monkeypatch, text, at):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "now_iso", lambda: at)
    f = tmp_path / "sheet.csv"
    f.write_text(text)
    rc = A.main(["--file", str(f)])
    return rc, json.loads((tmp_path / f"{A.SOURCE_ID}.json").read_text())


def test_review_good_then_failed_then_truncated_is_still_refused(tmp_path, monkeypatch):
    rc, good = _run_sheet(tmp_path, monkeypatch, sheet(), T0)
    assert rc == 0 and good["ok"] and good["meta"]["last_ok_rows"] == good["meta"]["rows"]
    active = {r["event_id"] for r in good["records"] if r["status"] == "advisory_active"}
    rc, failed = _run_sheet(tmp_path, monkeypatch, "Lake,Status\nX,Y\n", T1)
    assert rc == 1 and failed["ok"] is False
    short = "\n".join(sheet().splitlines()[:-3]) + "\n"
    rc, after = _run_sheet(tmp_path, monkeypatch, short, "2026-11-16T23:30:00Z")
    assert rc == 1 and after["ok"] is False
    recs = {r["event_id"]: r for r in after["records"]}
    assert all(recs[e]["ended_at"] is None and "_unlisted_since" not in recs[e]["raw"] for e in active)


def test_review_notes_with_titles_house_numbers_and_points_never_reach_a_save(tmp_path, monkeypatch):
    note = ("Dr. Example Person reported scum at 123-A Sample Road, 39.123456, -105.987654; Contact Pat Example; "
            "at the home of Sam Example")
    text = sheet() + f'\nExample Pond,Caution,9/1/2026,"{note}"\n'
    recs, _ = A.build(text, T0, [])
    blob = json.dumps(recs) + A.scrubbed_csv(text)
    for bad in ("Example Person", "123-A", "39.123456", "105.987654", "Pat Example", "Sam Example"):
        assert bad not in blob, bad
    assert "39.123" in A.scrubbed_csv(text)
    # an extra column in the sheet is never saved
    wide = "Waterbody name,Condition Category,Update Date,Other notes,Reporter\nExample Pond,Caution,9/1/2026,x,Pat Example\n"
    assert "Pat Example" not in A.scrubbed_csv(wide) and "Reporter" not in A.scrubbed_csv(wide)
    # a record carried from an earlier run, and the failure path, are scrubbed again
    old = [r for r in recs if r["waterbody_text"] == "Example Pond"][0]
    old["raw"]["updates"][0]["note"] = note
    old["advice_text"] = note
    kept, _ = A.build(sheet(), T1, [old])
    assert "Example Person" not in json.dumps(kept)
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(A, "EVENTS_DIR", tmp_path)
    (tmp_path / f"{A.SOURCE_ID}.json").write_text(json.dumps({"ok": True, "meta": {}, "records": [old]}))
    bad = tmp_path / "bad.csv"
    bad.write_text("Lake,Status\nX,Y\n")
    assert A.main(["--file", str(bad)]) == 1
    out = (tmp_path / f"{A.SOURCE_ID}.json").read_text()
    assert "Example Person" not in out and "123-A" not in out and "Example Pond" in out


def test_review_part_of_a_standing_notice_gone_keeps_the_advisory_and_fails_health():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    q = C.NOTICES[2]["records"][0]["quotes"][1]            # only the precaution sentence removed
    second, meta = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(drop=q), save=False)
    barr = next(r for r in second if r["source_record_id"].startswith("barr-lake"))
    assert barr["ended_at"] is None and "_unlisted_since" not in barr["raw"]
    # the red-alert sentence (its core quote) still stands: confirmed at this read (Astra verification 2026-11-15)
    assert barr["raw"]["_last_seen_in_source"] == T1 and barr["raw"]["_unresolved_wording"] == [q]
    assert any(u["notice"] == "cpw-barr-lake-red-alert" for u in meta["unvalidated"])


def test_review_changed_wording_that_still_says_red_alert_is_not_a_withdrawal():
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)

    def reworded(url):
        if url == C.CPW_BARR:
            return 200, NS.page_text("<h1>Barr Lake</h1><p>Barr Lake remains on red alert for toxic algae.</p>"), None
        return getter()(url)
    second, meta = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=reworded, save=False)
    barr = next(r for r in second if r["source_record_id"].startswith("barr-lake"))
    assert barr["ended_at"] is None and meta["unvalidated"]


def test_review_main_fails_health_when_any_notice_does_not_validate(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(C, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(NS, "save_raw", lambda *a, **k: None)
    calls = {"g": getter(fail=(C.NPS_BM,))}
    real = NS.build
    monkeypatch.setattr(C.NS, "build", lambda *a, **k: real(*a, getter=calls["g"], save=False))
    assert C.main([]) == 1
    out = json.loads((tmp_path / f"{C.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["records"]                        # the readable notices still updated

    def maintenance(url):                                               # HTTP 200, not the page
        if url == C.CPW_JM:
            return 200, NS.page_text("<html><body>Down for maintenance</body></html>"), None
        return getter()(url)
    calls["g"] = maintenance
    assert C.main([]) == 1
    meta = json.loads((tmp_path / f"{C.SOURCE_ID}.json").read_text())["meta"]
    assert meta["pages_read"] == 2 and any(u["notice"] == "cpw-john-martin-2026-08-30" for u in meta["unvalidated"])
    calls["g"] = getter()
    assert C.main([]) == 0


def test_review_the_blue_mesa_publication_day_is_not_an_issue_date():
    from datetime import datetime, timezone
    from build import status as S
    recs, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    bm = next(r for r in recs if r["source_record_id"].startswith("blue-mesa"))
    assert bm["time_precision"] == "bound" and bm["raw"]["start_bound"] == "on_or_before"
    assert bm["published_at"] == "2026-08-13" and "not given" in bm["raw"]["start_basis"]
    assert S.event_intervals(bm, "CO", datetime(2026, 8, 20, tzinfo=timezone.utc))      # still shown


def test_review_listed_absent_relisted_is_two_records_and_the_gap_stays_uncoloured():
    q = C.NOTICES[2]["records"][0]["quotes"]
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    gone, _ = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(drop=q), save=False)
    t2 = "2027-03-01T18:00:00Z"
    back, _ = NS.build(C.SOURCE_ID, C.NOTICES, t2, gone, getter=getter(), save=False)
    barr = sorted((r for r in back if r["source_record_id"].startswith("barr-lake")), key=lambda r: r["event_id"])
    assert len(barr) == 2
    orig, again = barr
    assert orig["ended_at"] == T1 and orig["started_at"] == "2026-08-03T19:00:00-06:00"
    assert again["source_record_id"] == "barr-lake-red-alert-2026-08-03:relisted-2027-03-01"
    assert again["started_at"] == t2 and again["time_precision"] == "poll" and again["ended_at"] is None
    # a later read confirms the relisted record, not the original
    t3 = "2027-03-02T18:00:00Z"
    later, _ = NS.build(C.SOURCE_ID, C.NOTICES, t3, back, getter=getter(), save=False)
    barr = {r["source_record_id"]: r for r in later if r["source_record_id"].startswith("barr-lake")}
    assert len(barr) == 2 and barr[again["source_record_id"]]["raw"]["_last_seen_in_source"] == t3
    assert barr[again["source_record_id"]]["started_at"] == t2 and barr[orig["source_record_id"]]["ended_at"] == T1


def test_review_the_state_text_matches_the_retained_record_behaviour():
    t = (ROOT / "research" / "co" / "state-text.md").read_text()
    assert "kept only while" not in t and "kept as it was" in t and "never dropped" in t
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    q = C.NOTICES[0]["records"][0]["quotes"]                # every sentence of the dated notice changed
    second, _ = NS.build(C.SOURCE_ID, C.NOTICES, T1, first, getter=getter(drop=q), save=False)
    assert {r["event_id"] for r in first} <= {r["event_id"] for r in second}


def test_review_the_mountain_scrub_and_notice_set_are_used_only_by_these_three_states():
    """No other state's output can change: the new scrub and the notice set are imported by CO, MT and WY only."""
    users = {p.name for p in (ROOT / "pipeline").rglob("*.py") if "tests" not in p.parts
             and re.search(r"mountain_scrub|notice_set", p.read_text(errors="ignore"))
             and p.name not in ("mountain_scrub.py", "notice_set.py")}
    assert users == {"co_cdphe_toxic_algae.py", "co_official_notices.py", "mt_deq_hab_map.py",
                     "wy_deq_hcb_bulletins.py"}, users


# ---------------------------------------------------------------- Astra verification 2026-11-15 (last round)

def test_verify_barr_lake_stays_coloured_while_its_red_alert_sentence_stands():
    from datetime import datetime, timezone
    from build import status as S
    first, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    q = C.NOTICES[2]["records"][0]["quotes"][1]            # only the precaution sentence removed, for weeks
    recs, at = first, None
    for at in ("2026-11-20T18:00:00Z", "2026-12-05T18:00:00Z", "2026-12-20T18:00:00Z"):
        recs, meta = NS.build(C.SOURCE_ID, C.NOTICES, at, recs, getter=getter(drop=q), save=False)
        assert any(u["notice"] == "cpw-barr-lake-red-alert" for u in meta["unvalidated"])
    barr = next(r for r in recs if r["source_record_id"].startswith("barr-lake"))
    assert barr["ended_at"] is None and barr["raw"]["_last_seen_in_source"] == at
    assert barr["raw"]["_unresolved_wording"] == [q]
    now = datetime(2026, 12, 20, 19, tzinfo=timezone.utc)
    live = [iv for iv in S.event_intervals(barr, "CO", now) if iv["start"] <= now <= iv["end"]]
    assert live and live[0]["color"] in ("red", "yellow")
    # the red-alert sentence itself gone (the precaution left): unresolved, never confirmed
    q0 = C.NOTICES[2]["records"][0]["quotes"][0]
    nxt, _ = NS.build(C.SOURCE_ID, C.NOTICES, "2026-12-21T18:00:00Z", recs, getter=getter(drop=q0), save=False)
    barr = next(r for r in nxt if r["source_record_id"].startswith("barr-lake"))
    assert barr["raw"]["_last_seen_in_source"] == at and barr["ended_at"] is None


def test_verify_two_relisting_cycles_in_one_day_keep_both_intervals():
    q = C.NOTICES[2]["records"][0]["quotes"]
    reads = [("2026-11-16T15:00:00Z", None), ("2026-11-16T16:00:00Z", q), ("2026-11-16T17:00:00Z", None),
             ("2026-11-16T18:00:00Z", q), ("2026-11-16T19:00:00Z", None), ("2026-11-16T20:00:00Z", q)]
    recs = []
    for at, drop in reads:
        recs, _ = NS.build(C.SOURCE_ID, C.NOTICES, at, recs, getter=getter(drop=drop), save=False)
    barr = sorted(((r["started_at"], r["ended_at"]) for r in recs if r["source_record_id"].startswith("barr-lake")))
    assert barr == [("2026-08-03T19:00:00-06:00", "2026-11-16T16:00:00Z"),
                    ("2026-11-16T17:00:00Z", "2026-11-16T18:00:00Z"),
                    ("2026-11-16T19:00:00Z", "2026-11-16T20:00:00Z")]
    ids = [r["event_id"] for r in recs]
    assert len(ids) == len(set(ids))


def test_verify_an_unreadable_row_is_not_a_withdrawal(tmp_path, monkeypatch):
    rc, good = _run_sheet(tmp_path, monkeypatch, sheet(), T0)
    em = next(r for r in good["records"] if r["source_record_id"] == "eleven-mile-reservoir:2026-08-03")
    assert rc == 0 and em["status"] == "advisory_active" and em["ended_at"] is None
    bad = sheet().replace("Eleven Mile Reservoir,Caution,8/3/2026", "Eleven Mile Reservoir,Caution,see note")
    assert len(bad.splitlines()) == len(sheet().splitlines())
    rc, out = _run_sheet(tmp_path, monkeypatch, bad, T1)
    assert rc == 1 and out["ok"] is False
    em2 = next(r for r in out["records"] if r["source_record_id"] == "eleven-mile-reservoir:2026-08-03")
    assert em2["ended_at"] is None and em2["status"] == "advisory_active"
    assert "_unlisted_since" not in em2["raw"] and em2["raw"]["_last_seen_in_source"] == T0
    assert out["meta"]["unreadable_rows"] and out["meta"]["last_ok_rows"] == good["meta"]["last_ok_rows"]
    # the next readable answer reads it again as before
    rc, again = _run_sheet(tmp_path, monkeypatch, sheet(), "2026-11-16T23:30:00Z")
    em3 = next(r for r in again["records"] if r["source_record_id"] == "eleven-mile-reservoir:2026-08-03")
    assert rc == 0 and em3["ended_at"] is None and em3["raw"]["_last_seen_in_source"] == "2026-11-16T23:30:00Z"


# ---------------------------------------------------------------- go-live audit 2026-11-16 (fixes 1 to 4)

NOW_AUDIT = "2026-11-16T03:00:00Z"
AUDIT_ROWS = ("Navajo Lake,No bloom reported,4/1/2026,\n"
              "Navajo Lake,Caution,9/9/2026,\"bloom present, not producing toxins at this time\"\n")


def _co_waters():
    """Colorado's own water records (data/waters-*.json with data/water-aliases.json merged), as the status build
    reads them."""
    from build import status as S
    return {k: w for k, w in S.load_waters().items() if w.get("state") == "CO"}


def _visitor_status(tmp_path, recs, waters):
    """The status build with CO live over these records only: what the map shows."""
    import copy
    from datetime import datetime
    from build import status as S
    ev_dir = tmp_path / "events"
    ev_dir.mkdir(exist_ok=True)
    by_src = {}
    for r in recs:
        by_src.setdefault(r["source_id"], []).append(r)
    for sid, rs in by_src.items():
        (ev_dir / f"{sid}.json").write_text(json.dumps(
            {"source_id": sid, "ok": True, "last_ok_at": NOW_AUDIT, "meta": {}, "records": rs}))
    rules = copy.deepcopy(S.load_rules())
    rules["live_states"] = sorted(set(rules["live_states"]) | {"CO"})
    now = datetime.fromisoformat(NOW_AUDIT.replace("Z", "+00:00"))
    st, _ = S.build(now=now, write=False, events_dir=ev_dir, waters=waters, outfalls=[], registry={}, reaches={},
                    flows=({}, {}), rules=rules, placement_cache=False)
    return st


@pytest.mark.parametrize("name,ext", [
    ("Navajo Lake", "named_water"), ("Eleven Mile Reservoir", "named_water"), ("Harvey Gap", "named_water"),
    ("North Delaney Butte Lake", "named_water"), ("Upper Brown Lake", "named_water"),
    ("Blue Lake/Adobe Creek Reservoir", "named_water"),
    ("Blue Heron Lake, St. Vrain State Park", "named_water"), ("Turtle Pond, Chatfield State Park", "named_water"),
    ("Jumbo Reservoir (Julesburg)", "named_water"),
    # a part of a water or a place beside one never colours a whole water
    ("Midwestern Pond, East", "part_of_water"), ("Chatfield Dog Park Pond - East", "part_of_water"),
    ("Chatfield Dog Park", "part_of_water"), ("Ken Mitchell Park", "part_of_water"),
    ("Navajo Lake, Sims Mesa swim beach", "part_of_water"), ("Example Reservoir (north arm)", "part_of_water"),
    ("Example Reservoir, Example Cove", "part_of_water"), ("Example Lake, somewhere unknown", "part_of_water")])
def test_audit_a_sheet_row_names_its_whole_water_or_a_part_of_one(name, ext):
    assert A.extent(name) == ext


def test_audit_every_sheet_advisory_carries_its_extent():
    recs, _ = A.build(sheet() + AUDIT_ROWS, T0, [])
    assert recs and all(r["raw"]["advisory_extent"] in ("named_water", "part_of_water") for r in recs)
    assert by_water(recs)["Navajo Lake"]["raw"]["advisory_extent"] == "named_water"


def test_audit_navajo_lakes_caution_colours_the_large_lake_a_visitor_sees(tmp_path):
    from build import status as S
    waters = _co_waters()
    assert waters["navajo-lake-co"]["area_km2"] > S.SMALL_WATER_KM2      # over the size limit for a whole water
    recs, _ = A.build(sheet() + AUDIT_ROWS, NOW_AUDIT, [])
    nav = [r for r in recs if r["waterbody_text"] == "Navajo Lake"]
    st = _visitor_status(tmp_path, nav, waters)
    assert st["waters"]["navajo-lake-co"]["status"] == "red"
    assert nav[0]["event_id"] in st["placements"] and st["placements"][nav[0]["event_id"]]["water_slugs"] == \
        ["navajo-lake-co"]


def test_audit_a_row_for_part_of_a_large_lake_never_colours_it(tmp_path):
    waters = _co_waters()
    rows = ("\"Navajo Lake, Sims Mesa swim beach\",No bloom reported,4/1/2026,\n"
            "\"Navajo Lake, Sims Mesa swim beach\",Caution,9/9/2026,bloom present\n")
    recs, _ = A.build(sheet() + rows, NOW_AUDIT, [])
    part = [r for r in recs if r["raw"]["sheet_name"].startswith("Navajo Lake,")]
    assert part and part[0]["raw"]["advisory_extent"] == "part_of_water"
    st = _visitor_status(tmp_path, part, waters)
    assert st["waters"].get("navajo-lake-co", {}).get("status", "grey") != "red"


def test_audit_eleven_mile_reservoir_places_on_its_water_and_shows(tmp_path):
    waters = _co_waters()
    assert "Eleven Mile Reservoir" in (waters["elevenmile-canyon-reservoir-co"].get("aliases") or [])
    assert "Blue Heron Lake" in (waters["blue-heron-reservoir-co"].get("aliases") or [])
    recs, _ = A.build(sheet(), NOW_AUDIT, [])
    w = by_water(recs)
    em, bh = w["Eleven Mile Reservoir"], w["Blue Heron Lake"]
    st = _visitor_status(tmp_path, [em, bh], waters)
    assert st["placements"][em["event_id"]]["water_slugs"] == ["elevenmile-canyon-reservoir-co"]
    assert st["waters"]["elevenmile-canyon-reservoir-co"]["status"] == "red"
    assert st["placements"][bh["event_id"]]["water_slugs"] == ["blue-heron-reservoir-co"]
    assert st["waters"]["blue-heron-reservoir-co"]["status"] == "grey"            # lifted June 25: history only
    doc = json.loads((ROOT / "research" / "co" / "receiving-waters-missing.json").read_text())
    assert {r["name"] for r in doc["rows"]} == {"Jackson Reservoir", "Windsor Lake"}


def test_audit_the_pueblo_spill_and_the_john_martin_advisory_each_colour_from_their_own_source(tmp_path):
    from datetime import datetime, timedelta, timezone
    from build import status as S
    recs, _ = NS.build(C.SOURCE_ID, C.NOTICES, T0, [], getter=getter(), save=False)
    ids = {r["source_record_id"]: r for r in recs}
    spill, adv = ids["pueblo-arkansas-river-2026-08-26"], ids["john-martin-water-contact-advisory-2026-08-31"]
    assert adv["raw"]["related_event_id"] == spill["event_id"] and not adv.get("parent_event_id")
    waters = _co_waters()
    st = _visitor_status(tmp_path, [spill, adv], waters)
    assert "superseded" not in st["placements"][spill["event_id"]]
    # the spill: red for its own days (Mountain time), then our caution, nothing invented; nothing today
    ivs = S.event_intervals(spill, "CO", datetime(2026, 11, 16, tzinfo=timezone.utc))
    red = [iv for iv in ivs if iv["color"] == "red"]
    yel = [iv for iv in ivs if iv["color"] == "yellow"]
    assert red and min(iv["start"] for iv in red) == datetime(2026, 8, 26, 6, tzinfo=timezone.utc)
    assert max(iv["end"] for iv in red) == datetime(2026, 8, 28, 6, tzinfo=timezone.utc)
    assert yel and max(iv["end"] for iv in yel) <= datetime(2026, 8, 28, 6, tzinfo=timezone.utc) + timedelta(hours=96)
    slugs = st["placements"][spill["event_id"]]["water_slugs"]
    assert slugs and all(st["waters"][s]["status"] == "grey" for s in slugs)          # past: history, not today
    # the advisory: its own start, aged 14 days, and no note claiming a 30-day assumed end
    pa = st["placements"][adv["event_id"]]
    assert "end_assumed_at" not in pa and "30 days" not in (pa.get("note") or "")
