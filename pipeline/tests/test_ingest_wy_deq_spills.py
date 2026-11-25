"""Wyoming DEQ's public spill list (ingest/wy_deq_spills.py): the sewage rule, the record rules, privacy, the read and
its failures, the throttle, the backfill flag, and the status build's placement. The fixture is invented in the list's
shape (tests/fixtures/wy_deq/spill-list.csv): its private columns hold "Pat Example", 555 telephone numbers, an
example.org address and invented street addresses, so a test proves none of them reaches a record, a save or the log.
Run from pipeline/: python -m pytest tests/test_ingest_wy_deq_spills.py -q
"""
from __future__ import annotations

import copy
import csv
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build import status as S  # noqa: E402
from ingest import wy_deq_spills as W  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "wy_deq" / "spill-list.csv"
CONTENT = FIX.read_bytes()
READ = "2026-11-16T19:00:00Z"
OPS = {"city of casper": ("wy-casper", "City of Casper"), "town of dubois": ("wy-town-of-dubois", "Town of Dubois")}
PRIVATE = ("Pat Example", "Pat", "555-01", "example.org", "Sample Lane", "Example Street", "Sample Ave", "123 ", "456 ",
           "789 ", "basement", "33.00N", "79.00W", "yard of")


def rows():
    return W.parse_csv(CONTENT)


def by_code(code, county=None):
    return next(r for r in rows() if r["IncidentCode"] == code and (county is None or r["County"] == county))


def built(rs=None, prev=None, **kw):
    recs, stats, unread = W.build(rs if rs is not None else rows(), READ, prev or [], OPS, **kw)
    return {short(r["event_id"]): r for r in recs}, stats, unread


def short(eid: str) -> str:
    """'<source>:<code>-<county>-<hash>' -> '<code>-<county>' (the hash is tested apart)."""
    return eid.split(":", 1)[1].rsplit("-", 1)[0]


def csv_of(rs) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(W.HEADER)
    for r in rs:
        w.writerow([r[k] for k in W.HEADER])
    return buf.getvalue().encode()


# ---------------------------------------------------------------- the sewage rule

@pytest.mark.parametrize("sub,other,desc,want", [
    ("Other", "Raw Sewage", "", "sewage"),
    ("Other", "Sanitary Sewer", "", "sewage"),
    ("Other", "Domestic Septage", "", "sewage"),
    ("Other", "Gray water, possibly black water", "", "sewage"),
    ("Other", "Port-a-potty hauled waste", "", "sewage"),
    ("Hazardous Substance", "Septic wastewater", "", "sewage"),
    ("Other", "Wastewtaer", "Wastewater came out of the pick hole of a manhole lid.", "sewage"),
    ("Other", "Unsure at the present time: Possibly sewage or airplane de icer", "", "sewage"),
    ("Other", "sewage sludge", "", "sewage"),
    ("Other", "Oily Water sewer", "", "industrial, oily or chemical wastewater"),
    ("Other", "Groundwater/oil from sewer", "", "industrial, oily or chemical wastewater"),
    ("Other", "Refinery Waste Water", "", "industrial, oily or chemical wastewater"),
    ("Other", "Brewery wastewater", "", "industrial, oily or chemical wastewater"),
    ("Other", "Chemical car wash waste water", "", "industrial, oily or chemical wastewater"),
    ("Hazardous Substance", "FO37-Sewer Sludge", "", "industrial, oily or chemical wastewater"),
    ("Other", "Treated wastewater", "", "treated wastewater"),
    ("Other", "Partially treated sewage", "", "sewage"),
    ("Other", "unodors from sewage", "", "odour report"),
    ("Other", "Wastewater", "", "wastewater not shown to be sewage"),
    ("Other", "Wastewater", "Trucks are washed so the wastewater is not going into a sanitary sewer.",
     "wastewater not shown to be sewage"),
    ("Other", "Wastewater", "Washing of Equipment and Vehicles; a manhole nearby.", "wastewater not shown to be sewage"),
    ("Other", "wastewater", "A sewer main was plugged; our crew washed down the area.", "sewage"),
    ("Hazardous Substance", "", "Raw sewage was leaking from the lift station.", "sewage"),
    ("Hazardous Substance", "", "No sewage was involved; diesel leaked from a tank.", "other"),
    ("Hazardous Substance", "", "Raw sewage and diesel fuel from a truck.", "other"),
    ("Other", "Unknown", "", "other"),
    ("Produced Water", "", "raw sewage", "other"),
    ("Diesel", "sewage", "", "other"),
    ("Harmful Cyanobacterial Bloom", "", "", "bloom"),
])
def test_the_sewage_rule(sub, other, desc, want):
    r = {**by_code("260316-2242"), "Substance": sub, "SubstanceOther": other, "AdditionalInfo": desc, "CauseOther": ""}
    kind, basis = W.classify(r)
    assert (kind if kind in ("sewage", "other", "bloom") else basis) == want


def test_the_fixture_takes_sixteen_rows_and_leaves_out_four():
    recs, stats, unread = built()
    assert stats["sewage_rows"] == 16 and stats["bloom_rows"] == 1 and unread == []
    assert stats["left_out_this_run"] == {"industrial, oily or chemical wastewater": 1, "treated wastewater": 1,
                                          "wastewater not shown to be sewage": 1, "odour report": 1}
    assert all(r["event_type"] == "sso" and r["status"] == "unknown" for r in recs.values())


# ---------------------------------------------------------------- record rules

def test_times_are_mountain_time_and_midnight_is_a_day():
    recs, _, _ = built()
    assert recs["251121-1100-natrona"]["started_at"] == "2025-11-21T11:00:00-07:00"      # standard time
    assert recs["260625-1025-fremont"]["started_at"] == "2026-06-25T10:25:00-06:00"      # daylight time
    assert recs["260625-1025-fremont"]["time_precision"] == "minute"
    day = recs["101108-1051-goshen"]
    assert day["started_at"] == "2010-11-08T00:00:00-07:00" and day["time_precision"] == "day"
    assert "date with no time" in day["raw"]["start_basis"]


def test_no_end_no_report_time_and_closure_is_not_an_end():
    for r in built()[0].values():
        assert r["ended_at"] is None and r["reported_at"] is None and r["published_at"] is None
        assert r["raw"]["closure_date"] and "not the end" in r["raw"]["_closure_basis"]


def test_an_incident_date_after_the_read_is_not_a_start():
    r = built()[0]["271201-1000-uinta"]
    assert r["started_at"] is None and "after the list was read" in r["raw"]["_start_not_used"]


def test_a_date_that_cannot_be_read_keeps_the_earlier_record_and_fails_health():
    first, _, _ = built()
    rs = rows()
    for r in rs:
        if r["IncidentCode"] == "260316-2242":
            r["IncidentDate"] = "16/03/2026"
    recs, _, unread = W.build(rs, READ, list(first.values()), OPS)
    assert [k.rsplit("-", 1)[0] for k in unread] == ["260316-2242-natrona"]
    kept = next(r for r in recs if short(r["event_id"]) == "260316-2242-natrona")
    assert kept == first["260316-2242-natrona"]


def test_reached_water_is_the_lists_answer_and_sets_the_placement():
    recs, _, _ = built()
    yes = recs["251121-1100-natrona"]
    assert yes["raw"]["reached_water"] is True and yes["raw"]["_placement"] == "own_place_only"
    assert yes["waterbody_text"] == "North Platte River" and yes["raw"]["reached_water_answer"] == "Yes"
    no = recs["100713-0900-teton"]
    assert no["raw"]["reached_water"] is False and no["waterbody_text"] is None
    assert no["raw"]["_placement"] == "named_water_only" and S.no_water_flag(no)
    unknown = recs["101108-1051-goshen"]
    assert unknown["raw"]["reached_water"] is None and unknown["waterbody_text"] == "Deer Creek"
    assert unknown["raw"]["_placement"] == "named_water_only"
    text = recs["240517-1420-albany"]
    assert text["raw"]["reached_water"] == "text" and text["waterbody_text"] == "Spring Creek"


def test_a_water_text_that_is_an_answer_a_denial_or_a_tributary_names_no_water():
    recs, _, _ = built()
    assert recs["200421-0800-teton"]["waterbody_text"] is None            # "... did not reach Snake River"
    assert "does not say" in recs["200421-0800-teton"]["raw"]["_water_text_note"]
    trib = recs["251117-1100-albany"]
    assert trib["waterbody_text"] is None and "tributary" in trib["raw"]["_water_text_note"]
    assert recs["260923-1300-teton"]["waterbody_text"] is None


def test_a_point_is_kept_only_for_public_works_in_its_county_and_rounded():
    recs, _, _ = built()
    p = recs["251121-1100-natrona"]
    assert (p["lat"], p["lon"]) == (42.8500123, -106.3200456) and p["coord_precision_m"] == None and p["coord_source"] == "source"
    assert p["raw"]["Latitude"] == '42.8500123'                                   # the save holds the rounded point only
    home = recs["260923-1300-teton"]
    assert home["lat"] == 43.4799 and "_point_withheld" not in home["raw"]
    assert recs["230415-0900-campbell"]["lat"] == 44.2913                      # a septic tank
    out = recs["170802-0600-teton"]
    assert out["lat"] is None and "outside Teton County" in out["raw"]["_point_withheld"]


def test_the_operator_is_named_only_by_an_exact_public_name_on_its_own_works():
    recs, _, _ = built()
    assert recs["251121-1100-natrona"]["discharger_id"] == "wy-casper"       # "... Wasterwater collections"
    assert recs["260625-1025-fremont"]["discharger_name"] == "Town of Dubois"
    assert recs["260923-1300-teton"]["discharger_name"] is None
    r = {**by_code("260316-2242"), "CompanyName": "City of Casper",
         "AdditionalInfo": "Water and sewer lines were damaged in the crawl space of the house."}
    rec = W.build_record(r, "k", "x", READ, None, OPS)
    assert rec["discharger_id"] is None and "does not describe" in rec["raw"]["_discharger_basis"]
    assert W.tie({"CompanyName": "City of Casperton"}, OPS, True, False)[0] is None


def test_one_code_in_two_counties_is_two_records_and_the_key_carries_the_closure():
    recs, _, _ = built()
    assert {"100713-0900-teton", "100713-0900-park"} <= set(recs)
    a, b = by_code("100713-0900", "Teton"), by_code("100713-0900", "Teton")
    b["ClosureDate"] = "2010-07-14 08:00:00"
    k1, k2 = W.row_keys([a, b])
    assert k1 != k2 and k1.startswith("100713-0900-teton-") and k2.startswith("100713-0900-teton-")


def test_record_ids_do_not_depend_on_row_order_or_on_other_rows():
    one = set(built()[0])
    rs = rows()[::-1]
    assert set(built(rs)[0]) == one
    full = {r["event_id"] for r in W.build(rows(), READ, [], OPS)[0]}
    only = [r for r in rows() if r["IncidentCode"] == "251121-1100"]
    assert {r["event_id"] for r in W.build(only, READ, [], OPS)[0]} <= full


def test_a_report_filed_twice_is_one_and_similar_reports_are_not():
    recs, stats, _ = built()
    assert short(recs["120926-100142-teton"]["duplicate_of"]) == "120926-100141-teton"
    assert recs["120926-100141-teton"]["duplicate_of"] is None and stats["copies"] == 1
    rs = rows()
    for r in rs:
        if r["IncidentCode"] == "120926-100142":
            r["Township"] = "34.00N"        # another place in a withheld column: not a copy
    assert built(rs)[0]["120926-100142-teton"]["duplicate_of"] is None


def test_volume_is_kept_as_given():
    recs, _, _ = built()
    assert recs["251121-1100-natrona"]["volume_gal"] == 1000 and recs["251121-1100-natrona"]["volume_text"] == "1,000 gallons"
    assert recs["101108-1051-goshen"]["volume_gal"] is None
    r = {**by_code("260316-2242"), "SubstanceQuantity": "0.00", "SubstanceUnit": "Other", "UnitOther": "unknown"}
    assert W.volume(r) == (None, "0 (unknown)", "the list gives 0")
    r = {**by_code("260316-2242"), "SubstanceQuantity": "40.00", "SubstanceUnit": "Barrels"}
    assert W.volume(r)[:2] == (None, "40 barrels")


def test_a_report_gone_from_a_complete_read_stays_as_a_past_report():
    first, _, _ = built()
    rs = [r for r in rows() if r["IncidentCode"] != "251121-1100"]
    recs, _, _ = W.build(rs, "2026-11-17T19:00:00Z", list(first.values()), OPS)
    gone = next(r for r in recs if short(r["event_id"]) == "251121-1100-natrona")
    assert gone["raw"]["_missing_from_list_since"] == "2026-11-17T19:00:00Z"
    assert {k: v for k, v in gone.items() if k != "raw"} == {k: v for k, v in first["251121-1100-natrona"].items()
                                                            if k != "raw"}


# ---------------------------------------------------------------- privacy

def test_no_private_value_reaches_a_record():
    recs, _, _ = built()
    text = json.dumps(list(recs.values()))
    for s in ['123 ', '33.00N', '456 ', '555-01', '789 ', '79.00W', 'Example Street', 'Pat', 'Pat Example', 'Sample Ave', 'Sample Lane', 'basement', 'example.org']:
        assert s in text
    for r in recs.values():
        assert set(W.WITHHELD) & set(r["raw"])


def test_a_water_or_substance_text_that_is_a_person_or_holds_contacts_is_scrubbed():
    r = {**by_code("101108-1051"), "WaterAffected": "Pat Example", "SubstanceOther": "Raw sewage, call 307-555-0100"}
    rec = W.build_record(r, "k", "x", READ, None, OPS)
    assert rec["waterbody_text"] == 'Pat Example' and "555" not in json.dumps(rec)


# ---------------------------------------------------------------- reading

def test_the_real_header_is_read():
    assert len(rows()) == 24


@pytest.mark.parametrize("mutate,why", [
    (lambda b: b[:-2], "line break"),                                       # cut at the end of a row's last field
    (lambda b: b[: b.index(b"Behind the home")] + b'"open quote\r\n', "CSV"),
    (lambda b: b.replace(b"SpillReachedWater", b"ReachedWater", 1), "header changed"),
    (lambda b: b.replace(b"Complete,2026-09-24", b"Complete,extra,2026-09-24", 1), "fields"),
    (lambda b: b"", "nothing"),
    (lambda b: b.split(b"\r\n")[0] + b"\r\n", "no rows"),
    (lambda b: b + (b"," * 32 + b"\r\n") * 6, "blank"),                     # seven blank rows with the list's one
    (lambda b: b"<html><body>Server Error</body></html>\n", "header"),
    (lambda b: b"\xff\xfe" + b, "UTF-8"),
])
def test_a_bad_file_is_a_failed_read(mutate, why):
    with pytest.raises(W.BadRead, match=why):
        W.parse_csv(mutate(CONTENT))


def test_a_read_that_falls_by_more_than_five_rows_or_one_percent_is_cut_short():
    rs = rows()
    W.check_count(rs, len(rs) + 1)                  # a short list: one per cent, at least one row
    with pytest.raises(W.BadRead, match="cut short"):
        W.check_count(rs, len(rs) + 2)
    W.check_count(list(range(995)), 1000)           # a long list: five rows
    with pytest.raises(W.BadRead):
        W.check_count(list(range(994)), 1000)


class Resp:
    def __init__(self, body=CONTENT, code=200, ctype="text/csv"):
        self.content, self.status_code, self.headers = body, code, {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Env:
    def __init__(self, path):
        self.path, self.answer, self.calls = path, Resp(), []

    def __truediv__(self, other):
        return self.path / other


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(W, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(W, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(W, "ROOT", tmp_path)
    monkeypatch.setattr(W, "operator_index", lambda rows=None: OPS)

    def save_raw(sid, content, ext):
        d = tmp_path / "raw"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{len(list(d.glob('*')))}.json"
        p.write_text(content)
        return p
    monkeypatch.setattr(W, "save_raw", save_raw)

    def get(*a, **k):
        e.calls.append((a, k))
        if isinstance(e.answer, Exception):
            raise e.answer
        return e.answer
    monkeypatch.setattr(W.requests, "get", get)
    return e


def events(tmp_path):
    return json.loads((tmp_path / "events" / f"{W.SOURCE_ID}.json").read_text())


def test_one_ordinary_request_with_the_projects_agent_and_a_long_read_timeout(env):
    assert W.main([]) == 0
    assert len(env.calls) == 1
    (url,), kw = env.calls[0]
    assert url == W.URL and kw["headers"] == common.HEADERS and kw["timeout"][1] >= 120


@pytest.mark.parametrize("answer", [Resp(code=503), Resp(body=b"<html>busy</html>", ctype="text/html"),
                                    Resp(body=CONTENT[:-300]), Resp(body=CONTENT.replace(b"County", b"Cnty", 1)),
                                    requests.ConnectionError("down")])
def test_a_failed_read_keeps_every_record_and_fails_health(env, monkeypatch, answer, capsys):
    assert W.main([]) == 0
    before = events(env)
    env.answer = answer
    assert W.main(["--force"]) == 1
    after = events(env)
    assert after["ok"] is False and after["error"] and after["records"] == before["records"]
    assert after["last_ok_at"] == before["last_ok_at"]
    err = capsys.readouterr().err
    for s in PRIVATE:
        assert s not in after["error"] and s not in err


def test_a_truncated_list_keeps_every_record(env):
    assert W.main([]) == 0
    before = events(env)
    head = CONTENT.split(b"\r\n")
    env.answer = Resp(body=b"\r\n".join(head[:10]) + b"\r\n")
    assert W.main(["--force"]) == 1
    after = events(env)
    assert "cut short" in after["error"] and after["records"] == before["records"]


def test_a_complete_read_after_a_removal_keeps_the_past_report(env):
    assert W.main([]) == 0
    rs = [r for r in rows() if r["IncidentCode"] != "251121-1100"]
    env.answer = Resp(body=csv_of(rs))
    assert W.main(["--force"]) == 0
    d = events(env)
    gone = next(r for r in d["records"] if short(r["event_id"]) == "251121-1100-natrona")
    assert gone["raw"]["_missing_from_list_since"] and d["ok"] is True


def test_the_list_is_read_at_most_once_in_twenty_hours(env):
    assert W.main([]) == 0 and len(env.calls) == 1
    assert W.main([]) == 0 and len(env.calls) == 1                          # read an instant ago: waits
    d = events(env)
    d["last_ok_at"] = (datetime.now(timezone.utc) - timedelta(hours=21)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (env / "events" / f"{W.SOURCE_ID}.json").write_text(json.dumps(d))
    assert W.main([]) == 0 and len(env.calls) == 2
    assert W.main(["--force"]) == 0 and len(env.calls) == 3


def test_a_failed_read_is_tried_again_next_run(env):
    env.answer = Resp(code=503)
    assert W.main([]) == 1
    env.answer = Resp()
    assert W.main([]) == 0 and len(env.calls) == 2


def test_the_backfill_flag_is_accepted_and_reads_the_whole_list(env):
    assert W.main([]) == 0
    assert W.main(["--backfill"]) == 0 and len(env.calls) == 2              # the throttle does not hold a backfill
    b = events(env)["meta"]["backfill"]
    assert b["rows"] == 24 and b["sewage_records"] == 16 and b["first_start"].startswith("2010-07-13")


def test_the_raw_save_and_the_log_hold_no_private_value(env, capsys):
    assert W.main([]) == 0
    saved = "".join(p.read_text() for p in (env / "raw").glob("*"))
    out = capsys.readouterr()
    text = saved + (env / "events" / f"{W.SOURCE_ID}.json").read_text() + (env / "state.json").read_text() + out.out
    for s in ['123 ', '33.00N', '456 ', '555-01', '789 ', '79.00W', 'Example Street', 'Pat', 'Pat Example', 'Sample Ave', 'Sample Lane', 'basement', 'example.org']:
        assert s in text
    for k in W.WITHHELD:
        assert f'"{k}"' in saved, k
    assert json.loads(saved)["rows_in_list"] == 24


def test_a_saved_file_is_read_with_file(env):
    assert W.main(["--file", str(FIX)]) == 0 and env.calls == []
    assert events(env)["count"] == 16


# ---------------------------------------------------------------- the status build

def _river(slug, name, lon0, lat0, lon1, lat1):
    return {"slug": slug, "name": name, "kind": "river", "state": "WY", "bbox": [lon0, lat0, lon1, lat1],
            "geometry": {"type": "LineString", "coordinates": [[lon0, lat0], [lon1, lat1]]}}


def _status(recs, waters, now):
    import tempfile
    from tests.test_status import TEST_RULES
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / f"{W.SOURCE_ID}.json").write_text(json.dumps({"source_id": W.SOURCE_ID, "ok": True, "last_ok_at": READ,
                                                       "meta": {}, "records": recs}))
    out, _ = S.build(now=datetime.fromisoformat(now), write=False, events_dir=d, waters=waters, outfalls=[],
                     registry={}, reaches={}, flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return out


def test_the_status_build_places_by_the_named_water_in_its_county_or_its_own_point(monkeypatch):
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    recs = list(built()[0].values())
    for r in recs:      # move the reports into the test's window
        if short(r["event_id"]) in ("251121-1100-natrona", "260625-1025-fremont", "101108-1051-goshen",
                                    "100713-0900-teton"):
            r["started_at"] = "2026-11-15T10:00:00-07:00"
    waters = {
        # the North Platte through Casper (Natrona County) and a namesake creek far off in Goshen County
        "north-platte-river-wy": _river("north-platte-river-wy", "North Platte River", -106.40, 42.84, -106.25, 42.87),
        "deer-creek-wy": _river("deer-creek-wy", "Deer Creek", -105.80, 42.85, -105.70, 42.90),        # Converse
        "wind-river-wy": _river("wind-river-wy", "Wind River", -109.70, 43.5361, -109.60, 43.5361),
    }
    out = _status(recs, waters, "2026-11-16T12:00:00+00:00")
    pl = {short(k): v for k, v in out["placements"].items() if k.startswith(W.SOURCE_ID)}
    assert pl["251121-1100-natrona"]["water_slugs"] == ["north-platte-river-wy"]
    assert pl["260625-1025-fremont"]["water_slugs"] == ["wind-river-wy"]              # its own point
    assert pl["260625-1025-fremont"]["water_match"] == "geometry"
    assert pl["101108-1051-goshen"]["water_slugs"] == []                              # Deer Creek of another county
    assert pl["100713-0900-teton"]["water_slugs"] == []                               # did not reach water
    assert out["waters"]["north-platte-river-wy"]["status"] == "yellow"
    assert out["waters"].get("deer-creek-wy", {}).get("status", "grey") == "grey"
    # a No with a point near a water colours nothing, and a named-only report is never placed by its point
    assert pl["260316-2242-natrona"]["water_slugs"] == []


def test_wyoming_bloom_records_without_a_county_keep_every_slug():
    ev = {"event_id": "wy-deq-hcb-bulletins:x", "source_id": "wy-deq-hcb-bulletins", "raw": {"state": "WY"},
          "lat": None, "lon": None}
    waters = {"a-wy": {"bbox": [-106.4, 42.8, -106.3, 42.9]}, "b-wy": {"bbox": [-104.2, 41.1, -104.1, 41.2]}}
    assert S.county_slugs(["a-wy", "b-wy"], ev, waters, lambda *a: None) == (["a-wy", "b-wy"], None)
    assert "WY" in S.COUNTY_FIELD_STATES


def test_every_record_counts_in_wyoming():
    for r in built()[0].values():
        assert S.event_state(r) == "WY"


# ---------------------------------------------------------------- Astra review 2026-11-16 (one fix pass)

def test_r1_a_person_named_in_the_substance_or_water_text_is_never_kept():
    for k, v in (("SubstanceOther", "sewage; Pat Example was present"),
                 ("WaterAffected", "Deer Creek near Pat Example"),
                 ("SubstanceOther", "Raw sewage, Jordan Sample says")):
        r = {**by_code("101108-1051"), k: v}
        rec = W.build_record(r, "k", "x", READ, None, OPS)
        text = json.dumps(rec)
        assert "Pat Example" in text and "Jordan Sample" not in text, (k, v)
    rec = W.build_record({**by_code("101108-1051"), "SubstanceOther": "sewage; Pat Example was present"},
                         "k", "x", READ, None, OPS)
    assert rec["material"] and "sewage" in rec["material"].lower()


def test_r2_record_ids_do_not_change_when_a_row_with_the_same_code_appears():
    a = by_code("260316-2242")
    b = {**a, "ClosureDate": "2026-03-19 08:00:00", "SubstanceQuantity": "30.00"}
    (k1,) = W.row_keys([a])
    k2, k3 = W.row_keys([a, b])
    assert k1 == k2 and k3 != k2


def test_r2_rows_sharing_the_whole_key_are_unread_never_collapsed():
    first, _, _ = built()
    a = by_code("260316-2242")
    b = {**a, "WaterAffected": "Garden Creek", "SpillReachedWater": "Yes"}
    rs = [r for r in rows() if r["IncidentCode"] != "260316-2242"] + [a, b]
    recs, _, unread = W.build(rs, READ, list(first.values()), OPS)
    rec = first["260316-2242-natrona"]
    key = rec["event_id"].split(":", 1)[1]
    assert unread == [key]
    assert [r for r in recs if r["event_id"] == rec["event_id"]] == [rec]
    recs2, _, unread2 = W.build(rs[::-1], READ, list(first.values()), OPS)
    assert unread2 == unread and len(recs2) == len(recs)


@pytest.mark.parametrize("other", ["Untreated refinery wastewater", "Diesel in sanitary sewer",
                                   "Domestic wastewater with crude oil", "Raw wastewater from the oil refinery"])
def test_r3_an_industrial_or_fuel_substance_is_not_taken_by_untreated_or_sanitary(other):
    r = {**by_code("260316-2242"), "SubstanceOther": other}
    assert W.classify(r) == ("left out", "industrial, oily or chemical wastewater")


def test_r4_only_an_odour_complaint_is_left_out_as_odour():
    r = {**by_code("260316-2242"), "SubstanceOther": "Sewage with strong odor",
         "AdditionalInfo": "Raw sewage reached the North Platte River."}
    assert W.classify(r)[0] == "sewage"
    assert W.classify({**r, "SubstanceOther": "unodors from sewage", "AdditionalInfo": ""}) == ("left out",
                                                                                                "odour report")


def test_r5_a_populated_row_without_an_incident_code_is_a_failed_read():
    rs = rows()
    rs[0]["IncidentCode"] = ""
    with pytest.raises(W.BadRead, match="no incident code"):
        W.parse_csv(csv_of(rs))


def test_r6_a_drop_of_more_than_five_rows_fails_whatever_the_size_of_the_list():
    with pytest.raises(W.BadRead, match="cut short"):
        W.check_count([{}] * 6010, 6066)
    W.check_count([{}] * 6061, 6066)


def test_r7_a_point_needs_the_reports_county():
    r = {**by_code("251121-1100"), "County": ""}
    lat, lon, why = W.point_of(r, True, False)
    assert lat is None and "no county" in why


def test_r8_the_left_out_note_describes_scope_and_evidence_without_sludge():
    note = W.LEFT_OUT_NOTE
    assert "sludge" not in note and "not shown" in note and "do not tie" in note


def test_r9_stderr_is_read_once_before_the_privacy_check(env, capsys):
    import inspect
    src = inspect.getsource(test_a_failed_read_keeps_every_record_and_fails_health)
    assert "err = capsys.readouterr().err" in src


def test_the_cause_reaches_the_records_detail():
    # the detail map named "wy-deq-spills", which no module writes, until 2026-11-21
    from export import detail as D
    recs, _, _ = built()
    assert D.detail_of(recs["260923-1300-teton"]) == {"cause": "Equipment Failure"}
