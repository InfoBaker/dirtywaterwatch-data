"""California: the State Water Board's spill history under the 2006 General Order (pipeline/ingest/ca_swrcb_ciwqs_sso_2006.py).
The rows are synthetic, written here under the file's real 66-column header: the certifier, the operator's name and
phone, the narratives and the addresses in them are placeholders that must never reach a record or the saved raw page.
Run from pipeline/: python -m pytest tests/test_ca_swrcb_ciwqs_sso_2006.py -q
"""
from __future__ import annotations

import json

import pytest

import common
from build import redact
from ingest import ca_swrcb_ciwqs_spills as L
from ingest import ca_swrcb_ciwqs_sso_2006 as M

FETCHED = "2026-11-21T10:00:00Z"
WDIDS = {"2SSO99001": "ca-sampleton", "2SSO99002": "ca-sample-bay-sd"}
NAMES = {"ca-sampleton": "Sampleton City", "ca-sample-bay-sd": "Sample Bay Sanitary District"}

# the file's header as published (SSO.txt, 2026-11-21): 66 columns, the last one empty
HEADER = ["REGION", "WDID", "STATUS", "SPILL ID", "CERT PERSON NAME", "STEP", "CERT PERSON TITLE", "CERT LOCATION",
          "CERT ID", "SPILL CREATED DT", "SUBMIT DRAFT DATE", "ORIGINAL CERTIFIED DATE", "CERT DT", "SPILL TYPE",
          "SPILL VOL REACH LAND", "SPILL VOL", "SPILL VOL RECOVER", "SPILL VOL REACH SURF", "REACH_SURFACE",
          "REACH STORM DRAINPIPE", "RETURN TO SSS", "SPILL LOC NAME", "LATTITUDE DECIMAL DEGREES",
          "LONGITUDE DECIMAL DEGREES", "COUNTY", "REGIONAL BOARD", "SPILL LOC DESC", "SSO NUMBER APPEAR POINTS",
          "APPEAR PT", "APPEAR PT EXPLAIN", "FINAL SPILL DEST", "FINAL SPILL DEST EXPL", "START DT", "AGENCY NOTIFY DT",
          "OPRTOR ARRVL DT", "EST END DT", "SPILL CAUSE", "SPILL CAUSE EXPLAIN", "WHERE FAILURE OCCUR",
          "WHERE FAIL OCCUR EXP", "SSO Storm Associated", "DIAMETER OF SEWER", "MATERIAL SEWER_PIPE", "AGE_SEWER_PIPE",
          "RESPONSE ACTIVITIES", "RESPONSE ACTIVITIES EXPL", "RESPONSE COMPLETE DT", "RESPNS_CORCT_ACTN_TAKEN",
          "SSO CRCTIVE ACTION TAKEN EXPL", "ONGOING INVESTIGATE", "REASON INVESTIGATE", "VISUAL INSPCT RESULT",
          "HEALTH WARNING POST", "SSO IF IMPACT BEACH", "BEACH IMPACT", "SURFACE WATER IMPACT", "SAMPLE ANALYZE FOR",
          "SMPLS_ANALYZE_FOR_EXPL", "SAMPLE REPORTED TO", "SMPLS REPORT TO EXPL", "SSO VOLUME METHOD",
          "OES CONTROL NUMBER", "OES CONTROL DT", "SSO OPERATOR NAME", "SSO OPERATOR PHONE", ""]

# placeholders in the columns never read, and in the house number of a typed location
PERSONAL = {"CERT PERSON NAME": "Pat Example", "CERT PERSON TITLE": "Inspector Sample",
            "CERT LOCATION": "Sample Yard Office", "CERT ID": "CERT-55501",
            "SSO OPERATOR NAME": "Robin Placeholder", "SSO OPERATOR PHONE": "916-555-0123",
            "SPILL LOC DESC": "Behind the house of Lee Placeholder at 12 Sample Lane",
            "APPEAR PT EXPLAIN": "Crew met the resident at the clean-out",
            "FINAL SPILL DEST EXPL": "Into the yard of 31 Example Way",
            "SPILL CAUSE EXPLAIN": "Roots found by Jordan Placeholder",
            "WHERE FAIL OCCUR EXP": "Lateral under the driveway of 9 Sample Court",
            "RESPONSE ACTIVITIES EXPL": "Casey Placeholder vacuumed the drain",
            "SSO CRCTIVE ACTION TAKEN EXPL": "Called Morgan Placeholder back",
            "REASON INVESTIGATE": "Complaint by Avery Placeholder",
            "VISUAL INSPCT RESULT": "Video shows the home’s lateral",
            "BEACH IMPACT": "Sample Beach posted by Quinn Placeholder",
            "SURFACE WATER IMPACT": "Reached Sample Creek near 77 Example Court",
            "SMPLS_ANALYZE_FOR_EXPL": "Samples by Riley Placeholder",
            "SMPLS REPORT TO EXPL": "Told Drew Placeholder",
            "SSO VOLUME METHOD": "Estimated by Taylor Placeholder"}
PLACEHOLDERS = [v for v in PERSONAL.values()] + ["Lee Placeholder", "448 Example", "12 Sample Lane", "Sample Creek",
                                                   "77 Example Court", "home’s lateral"]


def row(**over) -> dict:
    """A Category 1 spill in the file's columns, with every withheld column filled with a placeholder."""
    r = {"REGION": "2", "WDID": "2SSO99001", "STATUS": "Active", "SPILL ID": "970001", "STEP": "Certified",
         "SPILL CREATED DT": "01-OCT-15", "SUBMIT DRAFT DATE": "10/02/2015", "ORIGINAL CERTIFIED DATE": "15-OCT-15",
         "CERT DT": "10/20/2015", "SPILL TYPE": "Category 1", "SPILL VOL REACH LAND": "400", "SPILL VOL": "1500",
         "SPILL VOL RECOVER": "400", "SPILL VOL REACH SURF": "1100", "REACH_SURFACE": "Yes",
         "REACH STORM DRAINPIPE": "Yes", "RETURN TO SSS": "No", "SPILL LOC NAME": "448 Example St, Sampleton CA",
         "LATTITUDE DECIMAL DEGREES": "37.8", "LONGITUDE DECIMAL DEGREES": "-122.27", "COUNTY": "Alameda",
         "REGIONAL BOARD": "2", "SSO NUMBER APPEAR POINTS": "1", "APPEAR PT": "Manhole",
         "FINAL SPILL DEST": "Separate Storm Drain;Surface Water", "START DT": "10/01/2015 08:15",
         "AGENCY NOTIFY DT": "10/01/2015 08:30", "OPRTOR ARRVL DT": "10/01/2015 09:00",
         "EST END DT": "10/01/2015 11:45", "SPILL CAUSE": "Root intrusion", "WHERE FAILURE OCCUR": "Gravity Mainline",
         "SSO Storm Associated": "No", "HEALTH WARNING POST": "Yes", "SSO IF IMPACT BEACH": "No",
         "OES CONTROL NUMBER": "15-5550", "OES CONTROL DT": "10/01/2015 09:40", **PERSONAL}
    r.update(over)
    return r


ROWS = [
    row(),
    # a draft never certified, on private property, the minus sign of its longitude left out, a person's name typed
    # as its location, sewage in a storm drain and not returned (REACH_SURFACE No)
    row(**{"SPILL ID": "970002", "WDID": "2SSO99002", "STEP": "Submit Draft", "ORIGINAL CERTIFIED DATE": "",
           "CERT DT": "", "SUBMIT DRAFT DATE": "03/14/2019", "START DT": "03/12/2019 17:00",
           "EST END DT": "03/12/2019 19:30", "OES CONTROL DT": "", "OES CONTROL NUMBER": "", "REACH_SURFACE": "No",
           "SPILL LOC NAME": "Lee Placeholder", "LATTITUDE DECIMAL DEGREES": "37.812345",
           "LONGITUDE DECIMAL DEGREES": "122.265432", "APPEAR PT": "Lateral Clean Out (Private);"}),
    row(**{"SPILL ID": "970003", "SPILL TYPE": "Category 2", "SPILL VOL": "3000", "SPILL VOL REACH SURF": "0",
           "REACH_SURFACE": "No", "REACH STORM DRAINPIPE": "No"}),
    row(**{"SPILL ID": "970004", "SPILL TYPE": "Category 3", "SPILL VOL": "60", "SPILL VOL REACH SURF": "0",
           "REACH_SURFACE": "Yes"}),
    row(**{"SPILL ID": "970005", "START DT": "09/08/2016 07:00", "EST END DT": "09/08/2016 06:30",
           "SPILL LOC NAME": "Sampleton’s Pump Station 4"}),
    # one spill in two rows: an amended report and its certified version
    row(**{"SPILL ID": "970006", "STEP": "Amend", "CERT DT": "11/01/2017", "START DT": "10/20/2017 10:00",
           "EST END DT": "10/20/2017 12:00", "SPILL VOL": "900"}),
    row(**{"SPILL ID": "970006", "STEP": "Certified", "CERT DT": "03/28/2018", "START DT": "10/20/2017 10:00",
           "EST END DT": "10/20/2017 12:00", "SPILL VOL": "950"}),
    # one SPILL ID for two different spills
    row(**{"SPILL ID": "970007", "START DT": "02/02/2010 00:00", "EST END DT": "02/02/2010 08:35"}),
    row(**{"SPILL ID": "970007", "START DT": "07/10/2011 09:00", "EST END DT": "07/10/2011 09:30"}),
    row(**{"SPILL ID": "970008", "START DT": "12/31/2002 10:28", "EST END DT": "12/31/2002 11:00"}),
    # in the 2022 order's file too: the same WDID and start
    row(**{"SPILL ID": "970009", "START DT": "06/01/2023 09:15", "EST END DT": "06/01/2023 10:00"}),
    row(**{"SPILL ID": "970010", "START DT": "05/05/2012 00:00", "EST END DT": ""}),
    # in the 2022 order's file too: the same WDID and day, the point within 150 m, the time typed twelve hours apart
    row(**{"SPILL ID": "970011", "START DT": "03/13/2023 02:15", "EST END DT": "03/13/2023 02:45",
           "LATTITUDE DECIMAL DEGREES": "34.1498", "LONGITUDE DECIMAL DEGREES": "-118.0743"}),
]

LIVE = [
    {"source_record_id": "990009", "npdes_permit": "2SSO99001", "started_at": "2023-06-01T09:15:00-07:00",
     "lat": 37.9, "lon": -122.1, "discharger_name": "Sampleton City"},
    {"source_record_id": "990011", "npdes_permit": "2SSO99001", "started_at": "2023-03-13T14:15:00-07:00",
     "lat": 34.1499, "lon": -118.0744, "discharger_name": "Sampleton City"},
    {"source_record_id": "990012", "npdes_permit": "2SSO99003", "started_at": "2024-01-01T10:00:00-08:00",
     "lat": 34.0, "lon": -118.0, "discharger_name": "Sample Valley Sewer Authority"},
]


def text(rows=ROWS, header=HEADER) -> str:
    lines = ["\t".join(header)] + ["\t".join(r.get(h, "") if h else "" for h in header) for r in rows]
    return "\n".join(lines) + "\n"


def file_bytes(rows=ROWS) -> bytes:
    return text(rows).encode("cp1252")


def rows_read(rows=ROWS) -> list[dict]:
    return L.read_rows(L.decode(file_bytes(rows)), M.COLUMNS, M.REQUIRED)


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


def leaks(obj) -> list[str]:
    t = "\n".join(strings(obj))
    return [p for p in PLACEHOLDERS if p in t]


def records(rows=None, prev=(), live=LIVE, fetched=FETCHED):
    recs, stats = M.build(rows_read() if rows is None else rows, fetched, list(prev), list(live), dict(WDIDS),
                          dict(NAMES), file_modified="2026-11-20T14:00:32Z")
    return {r["source_record_id"]: r for r in recs}, stats


def test_a_certified_category_1_spill_is_a_record_with_the_boards_times_point_and_volumes():
    recs, _ = records()
    r = recs["970001"]
    assert r["event_id"] == "ca-swrcb-ciwqs-sso-2006-order:970001"
    assert r["event_type"] == "sso" and r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["started_at"] == "2015-10-01T08:15:00-07:00" and r["ended_at"] == "2015-10-01T11:45:00-07:00"
    assert r["reported_at"] == "2015-10-01T09:40:00-07:00" and "Cal OES" in r["raw"]["_reported_basis"]
    assert r["published_at"] is None and r["source_updated_at"] == "2015-10-20"
    assert r["raw"]["spill_category"] == "1" and r["raw"]["reached_water"] is True
    assert r["waterbody_text"] is None and r["water_slugs"] == [] and r["water_match"] == "none"
    assert r["npdes_permit"] == "2SSO99001" and r["discharger_id"] == "ca-sampleton"
    assert r["discharger_name"] == "Sampleton City"
    assert r["lat"] == 37.8 and r["lon"] == -122.27 and r["coord_precision_m"] is None
    assert r["volume_gal"] == 1500 and r["estimate_flag"] == "estimated"
    assert "1,100 gallons reached surface water" in r["volume_text"] and "400 gallons recovered" in r["volume_text"]
    assert r["raw"]["_first_seen_in_file"] == "2026-11-20T14:00:32Z" and r["raw"]["_first_seen_at"] == FETCHED
    assert r["raw"]["county"] == "Alameda" and r["raw"]["health_warning_posted"] == "Yes"


def test_only_category_1_makes_records_and_categories_2_and_3_are_counted():
    recs, stats = records()
    assert "970003" not in recs and "970004" not in recs
    assert all(r["raw"]["spill_category"] == "1" for r in recs.values())
    assert stats["by_category"] == {"Category 1": 10, "Category 2": 1, "Category 3": 1}
    assert stats["not_kept"] == {"Category 2": 1, "Category 3": 1}
    assert stats["category_2_3_marked_reached_surface"] == 1
    assert stats["category_1_flags"]["reached surface water: no; storm drain, sewage not returned"] == 1
    assert stats["rows_read"] == 13 and stats["spills_in_file"] == 12 and stats["versions_folded"] == 1
    assert stats["shown_category_1"] == len(recs) == 8


def test_a_draft_on_private_property_is_rounded_repaired_and_says_its_end_is_the_drafts():
    recs, _ = records()
    r = recs["970002"]
    assert r["lat"] == 37.812 and r["lon"] == -122.265 and r["coord_precision_m"] == 150
    assert "rounded" in r["raw"]["_coords_rounded"] and "minus sign" in r["raw"]["_coords_repaired"]
    assert r["status"] == "ended" and "never certified" in r["raw"]["_end_basis"]
    assert r["reported_at"] == "2019-03-14" and "draft" in r["raw"]["_reported_basis"]
    assert r["discharger_id"] == "ca-sample-bay-sd" and r["outfall_name"] == "[name removed]"


def test_a_building_or_structure_alone_rounds_the_point_and_a_manhole_does_not():
    rs = rows_read([row(**{"APPEAR PT": "Building or structure", "LATTITUDE DECIMAL DEGREES": "37.812345",
                          "LONGITUDE DECIMAL DEGREES": "-122.265432"})])
    recs, _ = records(rs)
    assert (recs["970001"]["lat"], recs["970001"]["lon"], recs["970001"]["coord_precision_m"]) == (37.812, -122.265, 150)
    rs = rows_read([row(**{"APPEAR PT": "Building or structure;Manhole", "LATTITUDE DECIMAL DEGREES": "37.812345"})])
    recs, _ = records(rs)
    assert recs["970001"]["lat"] == 37.812345 and recs["970001"]["coord_precision_m"] is None


def test_an_end_before_the_start_is_kept_as_published_and_the_shared_rule_draws_no_window_from_it():
    from datetime import datetime, timezone
    from build import status
    recs, _ = records()
    r = recs["970005"]
    assert r["status"] == "unknown" and r["ended_at"] == "2016-09-08T06:30:00-07:00"
    assert "before the start" in r["raw"]["_end_not_used"] and "unresolved.implausible_end" in r["raw"]["_end_basis"]
    ivs = status.event_intervals(r, "CA", datetime(2016, 9, 12, tzinfo=timezone.utc), None, status.load_rules())
    assert ivs and all(iv["end_not_used"]["rule"] == "unresolved.implausible_end" for iv in ivs)
    assert r["outfall_name"] == "Sampleton’s Pump Station 4"        # Windows-1252 read


def test_a_spill_with_no_end_is_never_given_one():
    recs, _ = records()
    r = recs["970010"]
    assert r["status"] == "unknown" and r["ended_at"] is None and "no end" in r["raw"]["_end_basis"]
    assert r["time_precision"] == "day" and r["started_at"] == "2012-05-05T00:00:00-07:00"


def test_versions_of_one_spill_fold_and_one_id_for_two_spills_keys_each_by_its_start():
    recs, _ = records()
    r = recs["970006"]
    assert r["raw"]["report_step"] == "Certified" and r["volume_gal"] == 950
    assert r["raw"]["_versions"] == [{"report_step": "Amend", "certified_on": "11/01/2017", "spill_type": "Category 1"}]
    assert "970007" not in recs
    a, b = recs["970007-201002020000"], recs["970007-201107100900"]
    assert a["started_at"].startswith("2010-02-02") and b["started_at"].startswith("2011-07-10")
    assert "different starts" in a["raw"]["_key_basis"]


def test_a_start_before_the_order_is_not_used():
    recs, _ = records()
    r = recs["970008"]
    assert r["started_at"] is None and "before the 2006 General Order" in r["raw"]["_start_not_used"]
    assert r["status"] == "ended" and r["ended_at"] == "2002-12-31T11:00:00-08:00"


def test_a_spill_in_the_2022_orders_file_is_kept_only_there():
    recs, stats = records()
    assert "970009" not in recs and "970011" not in recs
    o = stats["overlap_with_2022_order"]
    assert o["count"] == 2 and o["checked_against"] == 3
    by = {x["spill_id"]: x for x in o["spills"]}
    assert by["970009"] == {"spill_id": "970009", "spill_id_2022": "990009", "basis": "same WDID and start"}
    assert by["970011"]["spill_id_2022"] == "990011" and "150 m" in by["970011"]["basis"]
    recs2, stats2 = records(live=[{"source_record_id": "970001", "npdes_permit": "2SSO99009",
                                   "started_at": "2024-01-01T10:00:00-08:00"}])
    assert "970001" not in recs2 and stats2["overlap_with_2022_order"]["spills"][0]["basis"] == "same SPILL ID"
    recs3, stats3 = records(live=[])
    assert "970009" in recs3 and "970011" in recs3 and stats3["overlap_with_2022_order"]["count"] == 0
    # far apart on the same day: two spills
    far = [dict(LIVE[1], lat=34.3, lon=-118.3)]
    recs4, _ = records(live=far)
    assert "970011" in recs4


def test_the_operator_name_comes_from_the_registry_else_the_2022_file():
    rs = rows_read([row(**{"WDID": "2SSO99003"})])
    recs, _ = records(rs)
    r = recs["970001"]
    assert r["discharger_id"] is None and r["discharger_name"] == "Sample Valley Sewer Authority"
    assert "current spill file" in r["raw"]["_name_basis"] and "No operator on record" in r["raw"]["_discharger_basis"]


def test_a_spill_that_leaves_the_file_is_kept_and_marked_and_a_change_is_a_revision():
    old, _ = records()
    rs = [r for r in rows_read() if r["spill_id"] != "970010"]
    for r in rs:
        if r["spill_id"] == "970001":
            r["end_at"] = "10/01/2015 12:15"
    recs, stats = records(rs, prev=list(old.values()), fetched="2026-11-28T10:00:00Z")
    assert recs["970010"]["raw"]["_missing_from_file_since"] == "2026-11-28T10:00:00Z"
    assert stats["kept_missing_from_file"] == 1
    r = recs["970001"]
    assert r["ended_at"] == "2015-10-01T12:15:00-07:00" and r["raw"]["_revisions"][0]["end_at"] == "10/01/2015 11:45"
    assert r["raw"]["_first_seen_at"] == FETCHED


def test_personal_fields_never_reach_a_record_or_the_saved_page():
    rs = rows_read()
    # the withheld columns are never read; the typed location is read, and scrubbed before anything keeps it
    read = "\n".join(strings(rs))
    assert [p for p in PERSONAL.values() if p in read] == [] and all(set(r) == set(M.KEYS) for r in rs)
    recs, _ = records()
    out = redact.redact_events(list(recs.values()))
    assert leaks(out) == []
    saved = [M.scrubbed_row(r) for r in rs]
    assert leaks(saved) == []
    assert not any(k.isupper() for r in saved for k in r)
    assert recs["970001"]["outfall_name"] == "[house number removed] Example St, Sampleton CA"
    dumped = json.dumps(out)
    for col in ("CERT PERSON", "OPERATOR NAME", "OPERATOR PHONE", "cert_person", "operator_phone"):
        assert col not in dumped


def test_a_changed_layout_is_refused_and_extra_columns_are_never_read():
    with pytest.raises(ValueError):
        L.read_rows("REGION\tWDID\n2\t2SSO99001\n", M.COLUMNS, M.REQUIRED)
    t = text([dict(r, **{"CONTACT EMAIL": "pat.example@example.com"}) for r in ROWS], HEADER[:-1] + ["CONTACT EMAIL"])
    assert "pat.example@example.com" in t
    rs = L.read_rows(t, M.COLUMNS, M.REQUIRED)
    assert len(rs) == len(ROWS) and "pat.example@example.com" not in json.dumps(rs)


def test_the_columns_read_are_in_the_published_header_and_none_is_personal():
    assert all(c in HEADER for c in M.COLUMNS), [c for c in M.COLUMNS if c not in HEADER]
    assert not set(M.COLUMNS) & set(PERSONAL)
    assert len(HEADER) == 66 and HEADER[-1] == ""


def run_main(monkeypatch, tmp_path, argv, fetch=None):
    events = tmp_path / "build" / "events"
    monkeypatch.setattr(common, "EVENTS_DIR", events)
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(M, "EVENTS_DIR", events)
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "STATE_FILE", tmp_path / "build" / "state.json")
    monkeypatch.setattr(M, "LIVE_EVENTS", events / "live.json")
    monkeypatch.setattr(M, "discharger_names", lambda rows=None: dict(NAMES))
    monkeypatch.setattr(M.L, "wdid_index", lambda rows=None: dict(WDIDS))
    if fetch is not None:
        monkeypatch.setattr(M.L, "fetch", fetch)
    rc = M.main(argv)
    doc = json.loads((events / f"{M.SOURCE_ID}.json").read_text())
    state = json.loads((tmp_path / "build" / "state.json").read_text())
    return rc, doc, state


def test_a_run_reads_at_most_weekly_and_keeps_the_records_between_reads(monkeypatch, tmp_path):
    calls = []

    def fetch(sess, state, url=None):
        calls.append(dict(state))
        state["last_modified_http"] = "Fri, 20 Nov 2026 14:00:32 GMT"
        return file_bytes(), "2026-11-20T14:00:32Z"
    rc, doc, state = run_main(monkeypatch, tmp_path, [], fetch)
    assert rc == 0 and doc["ok"] and doc["count"] == 10 and len(calls) == 1      # no 2022 file: no overlap
    assert doc["meta"]["frozen"] is True and doc["meta"]["statewide"] is False
    assert "overlap_note" in doc["meta"] and state["read_at"]
    saved = list((tmp_path / "raw" / M.SOURCE_ID).glob("*.json"))
    assert len(saved) == 1
    page = json.loads(saved[0].read_text())
    assert leaks(page) == [] and {r["spill_type"] for r in page["rows"]} == {"Category 1"}

    def no_fetch(*a, **k):
        raise AssertionError("asked for the file within the week")
    (tmp_path / "build" / "events" / "live.json").write_text(json.dumps({"records": LIVE}))
    rc, doc, _ = run_main(monkeypatch, tmp_path, [], no_fetch)
    assert rc == 0 and doc["ok"] and doc["count"] == 8                           # the overlap checked again
    assert doc["meta"]["overlap_with_2022_order"]["count"] == 2


def test_a_304_keeps_the_records_and_backfill_reads_the_whole_file_without_if_modified_since(monkeypatch, tmp_path):
    def fetch(sess, state, url=None):
        state["last_modified_http"] = "Fri, 20 Nov 2026 14:00:32 GMT"
        return file_bytes(), "2026-11-20T14:00:32Z"
    run_main(monkeypatch, tmp_path, [], fetch)
    st = json.loads((tmp_path / "build" / "state.json").read_text())
    st["read_at"] = "2026-11-01T00:00:00Z"
    (tmp_path / "build" / "state.json").write_text(json.dumps(st))
    asked = []

    def not_modified(sess, state, url=None):
        asked.append(state.get("last_modified_http"))
        return None, "2026-11-20T14:00:32Z"
    rc, doc, state = run_main(monkeypatch, tmp_path, [], not_modified)
    assert rc == 0 and doc["ok"] and doc["count"] == 10 and asked == ["Fri, 20 Nov 2026 14:00:32 GMT"]
    assert doc["meta"]["file_not_modified_since"] == "2026-11-20T14:00:32Z" and state["read_at"] != "2026-11-01T00:00:00Z"

    def full(sess, state, url=None):
        asked.append(state.get("last_modified_http"))
        return file_bytes(), "2026-11-20T14:00:32Z"
    rc, doc, state = run_main(monkeypatch, tmp_path, ["--backfill"], full)
    assert rc == 0 and asked[-1] is None and doc["count"] == 10 and state["backfill"]["spills"] == 12


def test_a_failed_read_exits_1_and_keeps_the_records(monkeypatch, tmp_path):
    def fetch(sess, state, url=None):
        return file_bytes(), None
    run_main(monkeypatch, tmp_path, [], fetch)

    def boom(sess, state, url=None):
        raise OSError("no route")
    rc, doc, _ = run_main(monkeypatch, tmp_path, ["--backfill"], boom)
    assert rc == 1 and doc["ok"] is False and doc["count"] == 10 and "no route" in doc["error"]

    def broken(sess, state, url=None):
        return b"REGION\tWDID\n2\t2SSO99001\n", None
    rc, doc, _ = run_main(monkeypatch, tmp_path, ["--backfill"], broken)
    assert rc == 1 and doc["ok"] is False and doc["count"] == 10
