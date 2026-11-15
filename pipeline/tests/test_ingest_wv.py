"""West Virginia: DEP's combined sewer outlets against EPA's inventory (scripts/build_wv_outfalls.py), EPA's monthly DMR
flow at combined sewer outlets (ingest/wv_echo_cso_monthly.py), DEP's algal bloom map (ingest/wv_dep_hab_advisories.py),
the operator and register rows, the rules row, the state text and the missing-waters list. Fixtures are synthetic:
example permits, points and names, no person."""
import json
import re
import sys
from pathlib import Path

import common
from build import status as S
from ingest import notification_pages as NP
from ingest import wv_dep_hab_advisories as H
from ingest import wv_echo_cso_monthly as M

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_wv_outfalls as B  # noqa: E402
import wv_la_operator_rules as R  # noqa: E402


def _dep(permit, code, lat, lon, end="NA", stream="Example Run/Example River", **kw):
    return {"objectid": kw.get("oid", 1), "permit_id": permit, "fac_name": "Example Sanitary Board", "iu_code": code,
            "iut_code": "CSO", "iu_bdate": "2001/01/01", "iu_edate": end, "latitude": lat, "longitude": lon,
            "rstream": stream, "rs_code": "X-1", "cnty_code": "Example", "huc": "05000000", "rp_name": "A Person"}


def _epa(permit, outfall, lat, lon, status="CSO", slug="example-river-wv"):
    return {"npdes_permit": permit, "outfall": outfall, "state": "WV", "permittee": "EXAMPLE, CITY OF", "lat": lat,
            "lon": lon, "outfall_status": status, "water_slug": slug, "water_name": "Example River",
            "water_kind": "river", "match": "geometry+name", "coords_from": "permitted_feature"}


def test_outlets_pair_with_epa_by_code_and_by_point():
    dep = [_dep("WV0000001", "C001", 39.1, -80.1, stream="Example River/Ohio River"), _dep("WV0000001", "C002A", 39.2, -80.2),
           _dep("WV0000001", "C003", 39.3, -80.3, end="2026/10/27")]
    epa = [_epa("WV0000001", "C001", 39.1001, -80.1), _epa("WV0000001", "XXX2", 39.2005, -80.2),
           _epa("WV0000001", "C003", 39.3, -80.3)]
    doc = B.build(dep, epa, "2026-11-14T00:00:00Z")
    rows = {r["outfall"]: r for r in doc["outfalls"]}
    assert doc["paired_with_epa"] == 3 and doc["unpaired"] == []
    assert rows["C002A"]["epa_outfall"] == "XXX2"
    assert rows["C001"]["outfall_status"] == "active (DEP layer)" and not common._closed(rows["C001"])
    assert rows["C003"]["outfall_status"].startswith("CLS") and common._closed(rows["C003"])
    assert rows["C001"]["water_slug"] == "example-river-wv" and rows["C001"]["match"] == "carried from EPA's row"
    assert doc["open"] == 2 and len(doc["status_differs_from_epa"]) == 1
    # EPA's 'XXX2' is retired under its own code: one physical outlet
    alias = [r for r in doc["outfalls"] if r["outfall"] == "XXX2"]
    assert alias and alias[0]["outfall_kind"] == "other" and common._closed(alias[0])
    # a different stream (Example Run) does not take EPA's tie to Example River
    assert "water_slug" not in rows["C002A"] and "carry_refused" in rows["C002A"]
    assert all("rp_name" not in r and "A Person" not in json.dumps(r) for r in doc["outfalls"])


def test_a_qualified_name_never_takes_the_plain_waters_tie():
    doc = B.build([_dep("WV0000001", "C001", 39.1, -80.1, stream="Little Example Creek/Example Creek")],
                  [{**_epa("WV0000001", "C001", 39.1, -80.1), "water_name": "Example Creek"}], "2026-11-14T00:00:00Z")
    r = doc["outfalls"][0]
    assert "water_slug" not in r and "Little Example Creek" in r["carry_refused"]
    doc = B.build([_dep("WV0000001", "C001", 39.1, -80.1, stream="Ohio")],
                  [{**_epa("WV0000001", "C001", 39.1, -80.1), "water_name": "Ohio River"}], "2026-11-14T00:00:00Z")
    assert doc["outfalls"][0]["water_slug"] == "example-river-wv"     # a spelling variant is the same water


def test_registry_loads_each_wv_outlet_once():
    reg = [r for r in common.load_outfall_registry(provisional=False) if r.get("state") == "WV"]
    cso = [r for r in reg if r["outfall_kind"] == "cso"]
    assert len(cso) == 792 and sum(1 for r in cso if not common._closed(r)) == 519


def test_xxx_row_far_from_every_outlet_is_not_paired():
    doc = B.build([_dep("WV0000001", "C002A", 39.2, -80.2)], [_epa("WV0000001", "XXX2", 39.3, -80.2)],
                  "2026-11-14T00:00:00Z")
    assert doc["unpaired"] and doc["epa_not_in_state_layer"][0]["outfall"] == "XXX2"


def test_fetch_never_asks_every_field():
    assert "*" not in B.SAFE_FIELDS and "rp_name" not in B.SAFE_FIELDS and "rp_id" not in B.SAFE_FIELDS


def test_real_outlet_file():
    doc = json.loads((ROOT / "data" / "outfalls-wv.json").read_text())
    assert doc["open"] == 519 and doc["open_permits"] == 61 and doc["count"] == 792
    assert all(r["state"] == "WV" for r in doc["outfalls"])
    assert sum(1 for r in doc["outfalls"] if r["outfall_kind"] == "cso") == 792


def _line(end, value, base="MO AVG", nodi=None, received="20-OCT-26"):
    return {"MonitoringPeriodEndDate": end, "DMRValueNmbr": value, "DMRUnitDesc": "MGD" if value else None,
            "StatisticalBaseDesc": base, "NODICode": nodi, "ValueReceivedDate": received}


def test_monthly_flow_is_a_month_record_and_no_discharge_is_none():
    outlets = {"WV0000002": {"C002": {"npdes_permit": "WV0000002", "outfall": "C002", "lat": 37.7, "lon": -81.2,
                                   "permittee": "City of Example", "receiving_water_echo": "Example Creek",
                                   "water_slug": "example-creek-wv"}}}
    cache = {"since": "2025-01-01", "permits": {"WV0000002": {"name": "EXAMPLE", "lines": {"C002": [
        _line("30-SEP-26", ".342", "MINIMUM"), _line("30-SEP-26", "1.634"),
        _line("31-AUG-26", None, nodi="C", received="15-SEP-26")]}}}}
    recs, meta = M.build(cache, outlets)
    assert len(recs) == 1
    r = recs[0]
    assert r["time_precision"] == "month" and r["started_at"] == "2026-09-01" and r["ended_at"] == "2026-09-30"
    assert r["volume_gal"] is None and "not an event" in r["volume_text"] and r["raw"]["time_zone"] == M.TZ
    assert r["reported_at"] == "2026-10-20" and r["water_slugs"] == ["example-creek-wv"]
    assert meta["latest_month_by_outfall"]["WV0000002|C002"]["month"] == "2026-09"
    assert meta["no_discharge_months"] == {"WV0000002": 1}
    assert M.SOURCE_ID in S.EPA_MONTHLY_SOURCES and "nj-echo-monthly" in S.EPA_MONTHLY_SOURCES


def test_compact_keeps_only_cso_outlet_lines():
    res = {"CWPName": "EXAMPLE", "PermFeatures": [
        {"PermFeatureNmbr": "001", "Parameters": [{"ParameterCode": "50050", "MonitoringLocationDesc": "Effluent Gross",
                                                   "DischargeMonitoringReports": [_line("30-SEP-26", "2")]}]},
        {"PermFeatureNmbr": "C002", "Parameters": [{"ParameterCode": "50050", "MonitoringLocationDesc": "Effluent Gross",
                                                    "DischargeMonitoringReports": [_line("30-SEP-26", "1")]}]}]}
    c = M.compact(res, {"C002": {}})
    assert list(c["lines"]) == ["C002"] and c["skipped_non_cso"] == 1


def _answers(rows1=(), error=False):
    a = {"1": {"features": [{"attributes": {"OBJECTID": i, "Advisory": "HAB Advisory: avoid contact",
                                            "Date_Observed": 1786000000000}, "geometry": {"x": -80.12345, "y": 39.12345}}
                            for i in rows1]},
         "2": {"features": []}, "3": {"features": []}}
    if error:
        a["2"] = {"error": {"code": 500}}
    return a


def test_bloom_map_snapshot_opens_at_the_poll_and_lifts_at_the_poll():
    state = H.update({}, H.rows_of(_answers([7])), "2026-07-01T12:00:00Z")
    r = H.records(state)[0]
    assert r["event_type"] == "hab_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == "2026-07-01T12:00:00Z" and r["time_precision"] == "poll"
    assert r["reported_at"] is None and r["source_updated_at"] is None and r["raw"]["date_observed"]
    assert (r["lat"], r["lon"]) == (39.123, -80.123)
    state = H.update(state, H.rows_of(_answers([])), "2026-07-08T12:00:00Z")
    r = H.records(state)[0]
    assert r["status"] == "advisory_lifted" and r["ended_at"] == "2026-07-08T12:00:00Z"
    assert r["raw"]["ended_at_precision"] == "poll"


def test_bloom_map_layer_error_lifts_nothing():
    try:
        H.rows_of(_answers([7], error=True))
    except ValueError:
        return
    raise AssertionError("a layer error must not read as an empty map")


def test_operators_hold_every_permit_once_and_name_no_person():
    dis = [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "WV"]
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "WV"}
    held = [p for r in dis for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) and plants <= set(held)
    cso = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-wv.json").read_text())["outfalls"]
           if r["outfall_kind"] == "cso"}
    assert cso <= {p for r in dis if r["kind"] == "cso" for p in r["npdes_permits"]}
    assert not [r["name"] for r in dis if R.person_shaped(r["name"])]
    assert len({r["id"] for r in dis}) == len(dis)


def test_owner_rules():
    assert R.owner("FAIRMONT, CITY OF", None, None, "WV", "WV1", [])[:2] == ("City of Fairmont", "city")
    assert R.owner("SCOTTS RUN PSD", None, None, "WV", "WV1", [])[:2] == ("Scotts Run Public Service District",
                                                                        "special district")
    assert R.owner("SHEPHERDSTOWN, CORPORATION OF", None, None, "WV", "WV1", [])[:2] == ("Town of Shepherdstown", "town")
    assert R.owner("[name removed]", None, None, "WV", "WV9", [])[0] == "Holder of permit WV9"


def test_register_rows():
    doc = NP.load_register(ROOT / "data" / "notice-channels")
    assert NP.validate_register(doc, json.loads((ROOT / "data" / "dischargers.json").read_text()), ROOT) == []
    rows = [r for r in doc["channels"] if r["state"] == "WV"]
    ops = [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "WV"]
    ids = {r["id"] for r in rows}
    assert all(f"{o['id']}-dep-spill-line" in ids for o in ops)
    assert all(f"{o['id']}-cso-public-notice" in ids for o in ops if o["kind"] == "cso")
    feeds = {r["feed_source_id"] for r in rows if r.get("unmonitored_reason") == "feed_ingested"}
    assert {"wv-dep-hab-advisories", "wv-echo-dmr-cso"} <= feeds


def test_rules_row_and_zone():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    row = rules["red"]["by_state"]["WV"]
    assert row["hours"] is None and "Eastern" in row["basis"] and "safe" not in row["basis"].lower()
    import zones
    assert zones.STATE_ZONES["WV"] == "America/New_York"


def test_state_text_shape():
    t = (ROOT / "research" / "wv" / "state-text.md").read_text()
    heads = re.findall(r"^\*\*(.+?)\*\*", t, re.M)
    assert heads == ["What the law requires.", "What is published.", "What is not published.",
                     "What stands in the way.", "Known problems in the data.", "What this site does about it."]
    assert "{{share_line}}" in t and "{{grade}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t
    assert not re.search(r"\b(safe|clean)\b", t.replace("never clean", ""), re.I)


def test_missing_waters_list():
    doc = json.loads((ROOT / "research" / "wv" / "receiving-waters-missing.json").read_text())
    assert doc["state"] == "WV" and doc["waters"] == len(doc["rows"])
    names = {r["name"] for r in doc["rows"]} | set((doc.get("resolved") or {}).keys() if isinstance(
        doc.get("resolved"), dict) else [x.get("name") for x in doc.get("resolved") or []])
    assert "Jim Rum" in names or not doc["rows"]


def _run_dmr(tmp_path, monkeypatch, answers, cache):
    import common as C
    monkeypatch.setattr(C, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(M, "CACHE_FILE", tmp_path / "cache.json")
    (tmp_path / "cache.json").write_text(json.dumps(cache))
    outlets = {p: {"C002": {"npdes_permit": p, "outfall": "C002", "lat": 37.712345, "lon": -81.170555}} for p in answers}
    monkeypatch.setattr(M, "cso_outlets", lambda: outlets)
    monkeypatch.setattr(M, "fetch", lambda p, since: answers[p])
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    rc = M.main([])
    return rc, json.loads((tmp_path / f"{M.SOURCE_ID}.json").read_text())


def _cached(p):
    return {"name": "EXAMPLE", "asked_at": "2020-01-01T00:00:00Z",
            "lines": {"C002": [_line("30-SEP-26", "1.5")]}}


def test_a_rejection_keeps_the_months_an_earlier_answer_showed(tmp_path, monkeypatch):
    cache = {"since": "2025-01-01", "permits": {"WV0000003": _cached("WV0000003")}}
    rc, doc = _run_dmr(tmp_path, monkeypatch, {"WV0000003": (None, "not in ECHO")}, cache)
    # re-review P1-3: a rejected request is a degraded run (not ok, exit 1), the cached month and its fetch time kept
    assert rc == 1 and doc["ok"] is False and "rejected" in doc["error"] and doc["count"] == 1
    assert doc["records"][0]["fetched_at"] == "2020-01-01T00:00:00Z"


def test_a_rejection_with_no_cache_and_a_mixed_run_are_not_ok(tmp_path, monkeypatch):
    rc, doc = _run_dmr(tmp_path, monkeypatch, {"WV0000003": (None, "not in ECHO")}, {"since": "2025-01-01", "permits": {}})
    assert rc == 1 and doc["ok"] is False and doc["count"] == 0
    ok_answer = {"CWPName": "EXAMPLE", "PermFeatures": [{"PermFeatureNmbr": "C002", "Parameters": [
        {"ParameterCode": "50050", "MonitoringLocationDesc": "Effluent Gross",
         "DischargeMonitoringReports": [_line("31-OCT-26", "2.0")]}]}]}
    cache = {"since": "2025-01-01", "permits": {"WV0000004": _cached("WV0000004")}}
    rc, doc = _run_dmr(tmp_path, monkeypatch, {"WV0000003": (ok_answer, "live"), "WV0000004": (None, "not in ECHO")},
                       cache)
    assert rc == 1 and doc["ok"] is False and "WV0000004" in doc["error"] and "WV0000003" not in doc["error"]
    old = [r for r in doc["records"] if r["npdes_permit"] == "WV0000004"]
    assert old and old[0]["fetched_at"] == "2020-01-01T00:00:00Z"
    assert [r for r in doc["records"] if r["npdes_permit"] == "WV0000003"]


def test_a_partial_failure_is_not_ok_and_keeps_every_record(tmp_path, monkeypatch):
    cache = {"since": "2025-01-01", "permits": {"WV0000003": _cached("WV0000003"), "WV0000004": _cached("WV0000004")}}
    ok_answer = {"CWPName": "EXAMPLE", "PermFeatures": [{"PermFeatureNmbr": "C002", "Parameters": [
        {"ParameterCode": "50050", "MonitoringLocationDesc": "Effluent Gross",
         "DischargeMonitoringReports": [_line("31-OCT-26", "2.0")]}]}]}
    rc, doc = _run_dmr(tmp_path, monkeypatch, {"WV0000003": (ok_answer, "live"), "WV0000004": (None, "failed (x)")},
                       cache)
    assert rc == 1 and doc["ok"] is False and "1 of 2" in doc["error"]
    assert {r["npdes_permit"] for r in doc["records"]} == {"WV0000003", "WV0000004"}


def test_bloom_map_partial_answer_lifts_nothing():
    a = _answers([7])
    a["1"]["exceededTransferLimit"] = True
    try:
        H.rows_of(a)
    except ValueError as e:
        assert "exceededTransferLimit" in str(e)
        return
    raise AssertionError("a truncated layer must not read as the map")


def test_bloom_map_text_is_scrubbed_before_it_is_kept():
    a = _answers([7])
    a["1"]["features"][0]["attributes"]["Advisory"] = ("Avoid contact. Questions: contact Example Person at "
                                                       "304-555-0100 or example.person@example.org")
    row = H.rows_of(a)["1-7"]
    assert "555-0100" not in row["advisory"] and "example.org" not in row["advisory"]
    r = H.records(H.update({}, {"1-7": row}, "2026-07-01T12:00:00Z"))[0]
    assert "555-0100" not in json.dumps(r) and "example.org" not in json.dumps(r)


def test_bloom_map_reappearance_keeps_the_earlier_episode():
    st = H.update({}, H.rows_of(_answers([7])), "2026-07-01T12:00:00Z")
    st = H.update(st, H.rows_of(_answers([])), "2026-07-08T12:00:00Z")
    st = H.update(st, H.rows_of(_answers([7])), "2026-07-20T12:00:00Z")
    recs = {r["source_record_id"]: r for r in H.records(st)}
    assert recs["1-7~2"]["ended_at"] == "2026-07-08T12:00:00Z" and recs["1-7~2"]["status"] == "advisory_lifted"
    assert recs["1-7"]["started_at"] == "2026-07-20T12:00:00Z" and recs["1-7"]["status"] == "advisory_active"


def test_observation_at_utc_midnight_is_that_date():
    utc, day = H.observed({"Date_Observed": 1782864000000})      # 2026-07-01T00:00:00Z
    assert (utc, day) == ("2026-07-01T00:00:00Z", "2026-07-01")
    utc, day = H.observed({"Date_Observed": 1782876600000})      # 2026-07-01T03:30:00Z: June 30 in Eastern time
    assert day == "2026-06-30" and utc == "2026-07-01T03:30:00Z"


def test_state_text_counts_follow_the_outlet_file():
    doc = json.loads((ROOT / "data" / "outfalls-wv.json").read_text())
    open_rows = [r for r in doc["outfalls"] if r["outfall_kind"] == "cso" and not r["dep_outlet_end"]]
    named = sum(1 for r in open_rows if not r.get("receiving_water_from") and r["receiving_water_echo"])
    t = (ROOT / "research" / "wv" / "state-text.md").read_text()
    assert f"({named} of the {len(open_rows)} open outlets)" in t
    assert f"{len(open_rows)} open combined sewer outlets" in t


def _blank_dep_with_epa_text(epa_text, tie_name):
    return B.build([_dep("WV0000001", "C001", 39.1, -80.1, stream="")],
                   [{**_epa("WV0000001", "C001", 39.1, -80.1, slug="example-creek-wv"), "water_name": tie_name,
                     "receiving_water_echo": epa_text}], "2026-11-14T00:00:00Z")["outfalls"][0]


def test_a_blank_dep_stream_takes_epas_tie_only_when_epas_text_names_that_water(monkeypatch):
    """Re-review P1-1: DEP names no stream, EPA's row says 'Little Example Creek' but ties 'Example Creek'."""
    r = _blank_dep_with_epa_text("LITTLE EXAMPLE CREEK", "Example Creek")
    assert r["receiving_water_echo"] == "LITTLE EXAMPLE CREEK" and r["receiving_water_from"]
    assert "water_slug" not in r and "EPA's row (DEP names none)" in r["carry_refused"]
    for text in ("Unnamed Tributary/Example Creek", "Krout Creek of Example Creek", "NORTH FORK/EXAMPLE CREEK"):
        assert "water_slug" not in _blank_dep_with_epa_text(text, "Example Creek"), text
    assert "water_slug" not in _blank_dep_with_epa_text("EXAMPLE CREEK", "Little Example Creek")
    # agreeing text, a spelling variant, or no text anywhere: the tie is carried
    assert _blank_dep_with_epa_text("EXAMPLE CREEK", "Example Creek")["water_slug"] == "example-creek-wv"
    assert _blank_dep_with_epa_text("EXAMPLE RIVER", "Example Valley River")["water_slug"] == "example-creek-wv"
    assert _blank_dep_with_epa_text("", "Example Creek")["water_slug"] == "example-creek-wv"
    # through the resolver, with WV live: the refused row never lands on the plain creek beside its point
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"WV"})
    r = _blank_dep_with_epa_text("LITTLE EXAMPLE CREEK", "Example Creek")
    waters = {"example-creek-wv": {"slug": "example-creek-wv", "name": "Example Creek", "kind": "river", "state": "WV",
                                   "towns": [], "bbox": [-80.11, 39.09, -80.09, 39.11]}}
    slug, how = S.Resolver(waters, [], placement_rules={}).row_water({**r, "_file": "data/outfalls-wv.json"})
    assert slug is None, how
    ok = _blank_dep_with_epa_text("EXAMPLE CREEK", "Example Creek")
    assert S.Resolver(waters, [], placement_rules={}).row_water({**ok, "_file": "data/outfalls-wv.json"})[0] \
        == "example-creek-wv"


def test_the_committed_wv_registry_carries_no_tie_its_text_contradicts():
    doc = json.loads((ROOT / "data" / "outfalls-wv.json").read_text())
    for r in doc["outfalls"]:
        if r.get("match") == "carried from EPA's row":
            name = B._first_name(r["receiving_water_echo"])
            assert (not (r["receiving_water_echo"] or "").strip()) or (name and B._same_water(name, r["water_name"])), r


def test_monthly_report_points_are_three_decimals_in_good_and_degraded_runs(tmp_path, monkeypatch):
    """Re-review P1-4: the registry's six-decimal point never reaches a report record or the events file."""
    ok_answer = {"CWPName": "EXAMPLE", "PermFeatures": [{"PermFeatureNmbr": "C002", "Parameters": [
        {"ParameterCode": "50050", "MonitoringLocationDesc": "Effluent Gross",
         "DischargeMonitoringReports": [_line("31-OCT-26", "2.0")]}]}]}
    for answers in ({"WV0000003": (ok_answer, "live")}, {"WV0000003": (None, "failed (x)")}):
        cache = {"since": "2025-01-01", "permits": {"WV0000003": _cached("WV0000003")}}
        rc, doc = _run_dmr(tmp_path, monkeypatch, answers, cache)
        assert doc["records"], answers
        for r in doc["records"]:
            assert (r["lat"], r["lon"]) == (37.712, -81.171), r
        raw = (tmp_path / f"{M.SOURCE_ID}.json").read_text()
        assert "37.712345" not in raw and "81.170555" not in raw


def test_bloom_map_text_loses_house_numbers_and_reporting_names_before_any_write(tmp_path, monkeypatch):
    """Re-review P1-5: house numbers and reporting/contact clauses never reach the raw save, the state or a record."""
    import common as C
    texts = {7: "Avoid contact near 123 Example Lane. Sample submitted by Example Person.",
             8: "Avoid contact with the water. Reported by Mrs. Example; call 3045550100 for details.",
             9: "Bloom observed on the cove at 45B N. Example Rd. Contact Example Person at the marina.",
             10: "Submitted by Example Person"}
    a = _answers(list(texts))
    for f in a["1"]["features"]:
        f["attributes"]["Advisory"] = texts[f["attributes"]["OBJECTID"]]
    saved = []
    monkeypatch.setattr(H, "save_raw", lambda sid, data, ext: saved.append(data.decode()))
    monkeypatch.setattr(H, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(C, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(H, "fetch", lambda: a)
    assert H.main(["--at", "2026-07-01T12:00:00Z"]) == 0
    written = saved + [(tmp_path / "state.json").read_text(), (tmp_path / f"{H.SOURCE_ID}.json").read_text()]
    assert len(saved) == 1
    for blob in written:
        for bad in ("123 Example", "45B", "Example Person", "Mrs. Example", "3045550100", "555"):
            assert bad not in blob, (bad, blob[:300])
    recs = {r["source_record_id"]: r for r in json.loads(written[-1])["records"]}
    assert recs["1-7"]["advice_text"].endswith("Avoid contact near [house number removed] Example Lane.")
    assert recs["1-8"]["advice_text"].endswith("Avoid contact with the water.")
    assert H.WITHHELD in recs["1-10"]["advice_text"]
