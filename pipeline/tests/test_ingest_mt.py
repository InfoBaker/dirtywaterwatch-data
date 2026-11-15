"""Montana: DEQ's harmful algal bloom map layer, the operator rows, the register, the rules row, the state text and the
missing-waters list. The layer fixture is synthetic, in the layer's shape: its advisory notes are invented ("Example
Person"), so a test proves a person named in a note never reaches a record or the raw save.
Run from pipeline/: python -m pytest tests/test_ingest_mt.py -q
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import mt_deq_hab_map as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
T0 = "2026-11-14T23:00:00Z"


def ms(y, m, d, h=18):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def row(gid, name, issued, lifted=None, level="NA", obs=None, county="LEWIS & CLARK", public="Yes", x=-111.9, y=46.7):
    return {"attributes": {"globalid": "{" + gid + "}", "name": name, "county": county, "agency": None,
                           "sample_date": None, "advisory_lvl": level, "advisory_issued": issued,
                           "advisory_lifted": lifted, "date_observed": obs or ms(2026, 7, 1), "microcystin": None,
                           "anatoxin": None, "public_accessible": public},
            "geometry": {"x": x, "y": y}}


def layer():
    return {"features": [
        row("A-1", "Example Lake - North Ramp", "7/9: continued advisory, 6/25/2026: based on photos",
            "8/3/2026, bloom mostly dispersed"),
        row("A-2", "EXAMPLE RESERVOIR", "7/21: reported by Example Person, closure", None, level="Closure",
            obs=ms(2026, 7, 21)),
        row("A-3", "Example Pond", "8/24: based on photos", None),
        row("A-4", "Example Bay", "7/17: no advisory based on photos", None),
        row("A-5", "Example Algae Pond", "8/27/2026", None, level="Green Algae/Other"),
        row("A-6", "livestock pond (Example County)", "6/12/2026", "6/25/2026", public="No", county="PETROLEUM"),
        row("A-7", "Example Creek", None, None),
        row("A-8", "Example Lake", "9/9 continued; 7/21 initial advisory", "9/21 caution lifted; 7/1 old note"),
    ]}


def recs():
    return {r["source_record_id"]: r for r in M.build(layer(), T0)[0]}


def test_issue_date_is_the_earliest_date_and_lift_the_lift_note():
    r = recs()["a-1"]
    assert (r["started_at"], r["ended_at"], r["status"]) == ("2026-06-25", "2026-08-03", "advisory_lifted")
    assert r["raw"]["ended_at_precision"] == "day" and r["time_precision"] == "day"
    assert r["raw"]["time_zone"] == "America/Denver" and r["event_type"] == "hab_advisory"
    assert (r["waterbody_text"], r["raw"]["place"]) == ("Example Lake", "North Ramp")


def test_a_lift_date_before_the_start_is_not_the_lift():
    r = recs()["a-8"]
    assert r["started_at"] == "2026-07-21" and r["ended_at"] == "2026-09-21"


def test_current_level_confirms_and_a_lapsed_advisory_gets_no_end_and_no_confirmation():
    r = recs()
    cur = r["a-2"]
    assert cur["status"] == "advisory_active" and cur["raw"]["_last_seen_in_source"] == T0 and cur["ended_at"] is None
    assert cur["waterbody_text"] == "Example Reservoir" and "closure" in cur["raw"]["words"]
    lapsed = r["a-3"]
    assert lapsed["status"] == "advisory_active" and lapsed["ended_at"] is None
    assert "_last_seen_in_source" not in lapsed["raw"] and "14-day" in lapsed["raw"]["end_basis"]


def test_rows_that_are_not_advisories_make_no_record():
    r = recs()
    assert "a-4" not in r and "a-5" not in r and "a-7" not in r
    meta = M.build(layer(), T0)[1]
    assert (meta["no_advisory_text"], meta["green_algae"], meta["no_issue_date"]) == (1, 1, 1)


def test_private_water_keeps_its_county_only():
    r = recs()["a-6"]
    assert r["lat"] is None and r["lon"] is None and r["raw"]["county"] == "Petroleum"
    assert "point_withheld" in r["raw"]


def test_points_rounded_and_the_note_text_never_kept():
    out, _ = M.build(layer(), T0)
    blob = json.dumps(out) + json.dumps(M.safe_rows(layer()))
    assert "Example Person" not in blob and "based on photos" not in blob
    for r in out:
        if r["lat"] is not None:
            assert r["lat"] == round(r["lat"], 3) and r["lon"] == round(r["lon"], 3)


def test_the_safe_save_rebuilds_the_same_records():
    a, _ = M.build(layer(), T0)
    b, _ = M.build(M.safe_rows(layer()), T0)
    key = lambda rs: [(r["event_id"], r["started_at"], r["ended_at"], r["status"]) for r in rs]  # noqa: E731
    assert key(a) == key(b)


def test_a_truncated_or_empty_answer_fails_loudly():
    with pytest.raises(ValueError):
        M.build({"error": {"code": 400}}, T0)
    with pytest.raises(ValueError):
        M.build({"features": [], "exceededTransferLimit": True}, T0)


def test_year_comes_from_the_observation_in_mountain_time():
    doc = {"features": [row("B-1", "Example Lake", "1/1", None, obs=ms(2027, 1, 1, 5))]}   # 22:00 MST on Dec 31
    assert M.build(doc, T0)[0][0]["started_at"] == "2026-01-01"


# ---------------------------------------------------------------- operators, register, rules, text, waters

def mt_rows():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
            if r.get("state") == "MT" and "mt" in (r.get("source_areas") or [])]


def test_every_montana_plant_permit_is_in_exactly_one_row():
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "MT"}
    held = [p for r in mt_rows() for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) and plants <= set(held)
    research = {r["id"] for r in json.loads((ROOT / "research" / "mt" / "dischargers.json").read_text())}
    assert research <= {a for r in mt_rows() for a in r["aliases"]}


def test_tribal_land_permits_are_epas_and_names_are_not_persons():
    sys.path.insert(0, str(ROOT / "scripts"))
    import mountain_operator_rows as MR
    rows = {r["id"]: r for r in mt_rows()}
    assert "MT0020559" in rows["mt-city-of-polson"]["epa_issued_permits"]
    assert "EPA Region 8" in rows["mt-city-of-polson"]["notification_channel"]
    assert rows["mt-city-of-deer-lodge"]["legal_form"] == "city"
    assert not rows["mt-town-of-fort-peck"]["epa_issued_permits"]
    for r in rows.values():
        assert not MR.personish(r["name"]) and "[name removed]" not in r["name"]
    assert not any("Wolfe" in r["name"] for r in rows.values())


def test_register_rows_validate_and_cover_every_operator():
    from ingest import notification_pages as NP
    doc = NP.load_register(ROOT / "data" / "notice-channels")
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    assert not NP.validate_register(doc, dis, ROOT)
    mt = [r for r in doc["channels"] if r["state"] == "MT"]
    assert {r["id"] for r in mt_rows()} <= {r["operator_id"] for r in mt if r.get("operator_id")}
    assert {"mt-deq-hab-map", "mt-deq-sso-reports", "mt-deq-warm-springs-2023"} <= {r["id"] for r in mt}
    assert not any(r.get("barrier_review") for r in mt)


def test_rules_row_and_state_text():
    row = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["MT"]
    assert row["hours"] is None and "MT0020168" in row["source"]
    t = (ROOT / "research" / "mt" / "state-text.md").read_text()
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and not re.search(r"\b(safe|clean)\b", t) and ".json" not in t


def test_missing_waters_list():
    doc = json.loads((ROOT / "research" / "mt" / "receiving-waters-missing.json").read_text())
    assert doc["state"] == "MT" and doc["rows"]
    assert all(r["name"] == r["name"].strip() and not r["name"].isupper() for r in doc["rows"])
    assert any(r["county"] for r in doc["rows"])


# ---------------------------------------------------------------- the reviews' lessons (2026-11-15), on invented data

@pytest.mark.parametrize("note", ["lift pending 8/3/2026", "will be lifted 8/3/2026 if no new info",
                                  "not lifted 8/3/2026", "8/3/2026 lifting when results allow"])
def test_lesson_a_conditional_or_negated_lift_note_is_not_a_lift(note):
    doc = {"features": [row("C-1", "Example Lake", "7/9/2026", note)]}
    r = M.build(doc, T0)[0][0]
    assert r["status"] == "advisory_active" and r["ended_at"] is None
    assert M.build(M.safe_rows(doc), T0)[0][0]["ended_at"] is None      # the raw save rebuilds the same
    done = {"features": [row("C-1", "Example Lake", "7/9/2026", "8/3/2026 no new info, lifted")]}
    assert M.build(done, T0)[0][0]["ended_at"] == "2026-08-03"


def test_lesson_a_reissue_in_the_same_row_is_a_second_record():
    doc = {"features": [row("D-1", "Example Lake", "6/25/2026 initial; 9/1/2026 new advisory", "8/3/2026")]}
    recs = {r["source_record_id"]: r for r in M.build(doc, T0)[0]}
    assert (recs["d-1"]["started_at"], recs["d-1"]["ended_at"]) == ("2026-06-25", "2026-08-03")
    again = recs["d-1:2026-09-01"]
    assert again["started_at"] == "2026-09-01" and again["ended_at"] is None and again["status"] == "advisory_active"


def test_lesson_a_confirmation_from_an_earlier_read_is_kept_when_the_level_goes():
    cur = {"features": [row("E-1", "Example Lake", "7/9/2026", None, level="Caution")]}
    first = M.build(cur, T0)[0]
    gone = {"features": [row("E-1", "Example Lake", "7/9/2026", None, level="NA")]}
    later = M.build(gone, "2026-11-20T00:00:00Z", first)[0][0]
    assert later["raw"]["_last_seen_in_source"] == T0 and later["ended_at"] is None


@pytest.mark.parametrize("doc", [{"features": []}, {"features": [{"attributes": {"globalid": "x", "name": "Example"}}]}])
def test_lesson_an_empty_answer_or_renamed_fields_fail(doc):
    with pytest.raises(ValueError):
        M.build(doc, T0)


def test_lesson_names_are_scrubbed_and_a_private_owners_name_withheld():
    doc = {"features": [row("F-1", "Example Pond, call 555-0100", "7/9/2026", None),
                        row("F-2", "Example's stock pond", "7/9/2026", None, public="No"),
                        row("F-3", "Example Lake 46.12345 -111.98765", "7/9/2026", None)]}
    recs = {r["source_record_id"]: r for r in M.build(doc, T0)[0]}
    assert "555-0100" not in json.dumps(recs)
    assert recs["f-2"]["waterbody_text"] == "Private water (name withheld)" and recs["f-2"]["lat"] is None
    assert "46.12345" not in json.dumps(recs)


# ---------------------------------------------------------------- Astra review 2026-11-15 (fix/co-mt-wy-review)

@pytest.mark.parametrize("note", ["not yet lifted 8/3/2026", "Not yet lifted, 8/3/2026", "yet to be lifted 8/3/2026",
                                  "remains in effect until lifted 8/3/2026", "still in effect 8/3/2026"])
def test_review_a_not_yet_lifted_note_is_not_a_lift(note):
    doc = {"features": [row("G-1", "Example Lake", "7/9/2026", note)]}
    r = M.build(doc, T0)[0][0]
    assert r["status"] == "advisory_active" and r["ended_at"] is None
    assert M.build(M.safe_rows(doc), T0)[0][0]["ended_at"] is None


@pytest.mark.parametrize("note,end", [("sampled 7/28/2026, lifted 8/10/2026", "2026-08-10"),
                                      ("lifted 8/10/2026 (sampled 7/28/2026)", "2026-08-10"),
                                      ("7/28/2026 sample results below threshold; 8/10/2026 lifted", "2026-08-10"),
                                      ("sampled 7/28/2026", None),
                                      ("8/3/2026", "2026-08-03")])
def test_review_a_sampling_date_is_not_the_lift_date(note, end):
    doc = {"features": [row("G-2", "Example Lake", "7/9/2026", note)]}
    assert M.build(doc, T0)[0][0]["ended_at"] == end
    assert M.build(M.safe_rows(doc), T0)[0][0]["ended_at"] == end      # the sanitized raw save rebuilds the same


def two_rows():
    return {"features": [row("H-1", "Example Lake", "7/9/2026", None, level="Caution"),
                         row("H-2", "Example Reservoir", "7/12/2026", None, level="Caution")]}


def test_review_a_row_gone_from_a_shorter_answer_is_kept_and_the_read_is_incomplete():
    first, meta1 = M.build(two_rows(), T0)
    assert not meta1["incomplete"] and meta1["last_ok_rows"] == 2
    short = {"features": [two_rows()["features"][0]]}
    recs, meta = M.build(short, "2026-11-15T23:00:00Z", first, meta1)
    by = {r["source_record_id"]: r for r in recs}
    kept = by["h-2"]
    assert kept["status"] == "advisory_active" and kept["ended_at"] is None and kept["started_at"] == "2026-07-12"
    assert kept["raw"]["_last_seen_in_source"] == T0 and "no longer in DEQ's layer" in kept["raw"]["retained"]
    assert meta["incomplete"] and meta["missing_rows"] == ["h-2"] and meta["last_ok_rows"] == 2


def test_review_a_row_whose_advisory_fields_no_longer_read_is_kept():
    first, meta1 = M.build(two_rows(), T0)
    bad = two_rows()
    bad["features"][1]["attributes"]["advisory_issued"] = ""
    recs, meta = M.build(bad, "2026-11-15T23:00:00Z", first, meta1)
    by = {r["source_record_id"]: r for r in recs}
    assert by["h-2"]["ended_at"] is None and "no longer read" in by["h-2"]["raw"]["retained"]
    assert meta["unreadable_rows"] == ["h-2"] and meta["incomplete"]


def test_review_main_writes_an_incomplete_read_with_health_false(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path)
    f1, f2 = tmp_path / "a.json", tmp_path / "b.json"
    f1.write_text(json.dumps(two_rows()))
    f2.write_text(json.dumps({"features": [two_rows()["features"][0]]}))
    assert M.main(["--file", str(f1)]) == 0
    assert M.main(["--file", str(f2)]) == 1
    out = json.loads((tmp_path / "mt-deq-hab-map.json").read_text())
    assert out["ok"] is False and {r["source_record_id"] for r in out["records"]} == {"h-1", "h-2"}
    # a failed read after that keeps both, sanitized again
    f3 = tmp_path / "c.json"
    f3.write_text(json.dumps({"error": {"code": 500, "message": "call 555-0100"}}))
    assert M.main(["--file", str(f3)]) == 1
    out = json.loads((tmp_path / "mt-deq-hab-map.json").read_text())
    assert len(out["records"]) == 2 and "555-0100" not in json.dumps(out)


def test_review_replacement_dates_or_water_make_a_new_episode_and_keep_the_old():
    first, meta1 = M.build({"features": [row("J-1", "Example Lake", "7/1/2026", "7/20/2026")]}, T0)
    redated, _ = M.build({"features": [row("J-1", "Example Lake", "7/5/2026", "7/20/2026")]}, T0, first, meta1)
    by = {r["source_record_id"]: r for r in redated}
    assert by["j-1"]["started_at"] == "2026-07-01" and by["j-1"]["waterbody_text"] == "Example Lake"
    assert by["j-1:2026-07-05"]["started_at"] == "2026-07-05"
    renamed, _ = M.build({"features": [row("J-1", "Example Pond", "7/1/2026", "7/20/2026")]}, T0, first, meta1)
    by = {r["source_record_id"]: r for r in renamed}
    assert by["j-1"]["waterbody_text"] == "Example Lake"
    assert by["j-1:2026-07-01"]["waterbody_text"] == "Example Pond"


def test_review_the_raw_save_is_an_allowlist_with_private_points_removed():
    priv = row("K-1", "Example pond", "7/9/2026", None, public="No", x=-111.912345, y=46.712345)
    pub = row("K-2", "Example Lake", "7/9/2026", None, x=-111.912345, y=46.712345)
    for f in (priv, pub):
        f["attributes"].update({"desc_bloom": "seen by Dr. Example Person", "reporter_email": "x@example.org",
                                "former_advisory": "Example Person"})
    blob = json.dumps(M.safe_rows({"features": [priv, pub]}))
    for s in ("Example Person", "x@example.org", "desc_bloom", "reporter_email", "former_advisory", "912345", "712345"):
        assert s not in blob
    saved = M.safe_rows({"features": [priv, pub]})["features"]
    assert saved[0]["geometry"] is None and saved[1]["geometry"] == {"x": -111.912, "y": 46.712}


def test_review_a_retained_record_is_sanitized_again():
    old = M.build({"features": [row("L-1", "Example Lake", "7/9/2026", None)]}, T0)[0][0]
    old["lat"], old["lon"] = 46.712345, -111.912345
    old["raw"]["point_withheld"] = "private"
    old["raw"]["desc"] = "Dr. Example Person"
    recs, _ = M.build(two_rows(), T0, [old])
    kept = next(r for r in recs if r["source_record_id"] == "l-1")
    assert kept["lat"] is None and "Example Person" not in json.dumps(kept)


def test_review_a_name_with_a_title_or_house_number_is_scrubbed():
    doc = {"features": [row("M-1", "Dr. Example Person's pond at 12-B Sample Road", "7/9/2026", None),
                        row("M-2", "Example Lake", "7/9/2026", None)]}
    doc["features"][1]["attributes"]["agency"] = "Contact Pat Example"
    blob = json.dumps(M.build(doc, T0)[0]) + json.dumps(M.safe_rows(doc))
    for bad in ("Example Person", "12-B", "Pat Example"):
        assert bad not in blob, bad
