"""Missouri: KC Water's overflow posts (ingest/mo_kc_water_news.py), MSD Project Clear's alerts (ingest/mo_msd_alerts.py),
DNR's concern reports (ingest/mo_dnr_concerns.py), DNR's outfall layer (scripts/mo_outfall_layer.py), the operator rows,
the register, the rules row, the county-aware placement and the state text. Fixtures are synthetic, shaped on the real
fetches of 2026-11-14 (Example names, placeholder house numbers and a placeholder telephone number); the concern
report is a PDF written by the test. No network."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from build import status as S
from ingest import mo_dnr_concerns as C
from ingest import mo_kc_water_news as K
from ingest import mo_msd_alerts as M
import zones

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "mo"
AT = "2026-11-14T18:00:00Z"
PERSONAL = ["1234 Example", "5678 Sample", "4321 Example", "Jane Example", "573-555-0100", "555-0100", "Staff Example",
            "media@example.org", "1234 Example Lane", "Example Neighbor"]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- KC Water

def kc():
    recs, stats = K.run([(FIX / "kc_feed.xml").read_bytes()], [], AT)
    return {r["source_record_id"]: r for r in recs}, stats


def test_kc_notice_response_time_is_an_upper_bound_with_its_end_volume_and_water():
    recs, stats = kc()
    r = recs["9001"]
    assert r["event_type"] == "sso" and r["status"] == "unknown"
    assert r["started_at"] == "2024-10-14T13:30:00-05:00" and r["time_precision"] == "minute"
    assert r["raw"]["start_kind"] == "response" and r["raw"]["start_is_upper_bound"] is True
    assert r["ended_at"] == "2024-10-14T20:00:00-05:00" and r["raw"]["ended_at_precision"] == "minute"
    assert r["volume_gal"] == 39000 and r["waterbody_text"] == "Missouri River"
    assert r["published_at"] == "2024-10-15T17:15:57-05:00" and r["reported_at"] is None
    assert r["raw"]["time_zone"] == "America/Chicago" and r["discharger_id"] == "mo-kansas-city-mo0024911"
    assert r["source_url"] == "https://www.kcwater.us/?post_type=news1&p=9001"     # its numeric permalink (P1-4)
    assert r["raw"]["counties"] == ["Jackson County", "Clay County", "Platte County", "Cass County"]
    assert stats["notices"] == 5 and stats["not_notices"] == 1 and stats["news_posts"] == 6


def test_kc_update_is_a_copy_whose_end_completes_the_first_notice():
    recs, _ = kc()
    first, upd = recs["9002"], recs["9003"]
    assert first["started_at"] == "2022-09-30T19:00:00-05:00" and first["raw"]["start_kind"] == "start"
    assert upd["duplicate_of"] == first["event_id"] and first["duplicate_of"] is None
    assert first["ended_at"] == "2022-10-01T01:30:00-05:00" and first["raw"]["end_from"] == upd["source_url"]
    assert first["waterbody_text"] == "Brush Creek"


def test_kc_heavy_rain_post_morning_time_and_bond_post_dropped():
    recs, _ = kc()
    r = recs["9004"]
    assert r["started_at"] == "2020-07-27T07:46:00-05:00" and r["ended_at"] == "2020-07-27T15:14:00-05:00"
    assert r["raw"]["multiple_sites"] is True and r["waterbody_text"] == "Rock Creek; Missouri River"
    assert "Missouri River" in r["raw"]["waters_named"]
    assert "Buckeye Creek" not in r["raw"]["waters_named"]          # a pump station's name, not a water reached
    assert "9005" not in recs and "9007" not in recs


def test_kc_unreadable_end_is_left_open_and_no_water_reached_is_unplaced():
    r = kc()[0]["9006"]
    assert r["ended_at"] is None                                      # "11:am" is not a time; never the start
    assert r["raw"]["reached_water"] is False and r["waterbody_text"] is None


def test_kc_records_and_raw_save_carry_no_house_number_or_contact():
    recs, _ = kc()
    blob = json.dumps(list(recs.values())) + K.safe_feed((FIX / "kc_feed.xml").read_bytes()).decode()
    for p in PERSONAL:
        assert p not in blob


def test_kc_records_are_placed_by_named_water_only_and_the_raw_save_holds_no_post_text():
    recs, _ = kc()
    assert {r["raw"]["_placement"] for r in recs.values()} == {"named_water_only"}
    assert not [r for r in recs.values() if "post_text" in r["raw"]]
    saved = json.loads(K.safe_feed((FIX / "kc_feed.xml").read_bytes()))
    assert len(saved["items"]) == 5 and not [i for i in saved["items"] if "text" in i]
    assert not [i for i in saved["items"] if "title" in i]           # titles are no longer saved (re-review P1-9)


def test_kc_first_page_404_is_a_failed_run(monkeypatch):
    class Resp:
        status_code, content = 404, b""

        def raise_for_status(self):
            raise K.requests.HTTPError("404")
    monkeypatch.setattr(K.requests, "get", lambda *a, **k: Resp())
    with pytest.raises(K.requests.HTTPError):
        K.fetch(False)


# ---------------------------------------------------------------- MSD

def msd():
    recs, stats = M.run([json.loads((FIX / "msd_posts.json").read_text())], [], AT)
    return {r["source_record_id"]: r for r in recs}, stats


def test_msd_weekday_is_the_latest_on_or_before_the_post_and_advice_is_quoted_not_dated():
    recs, stats = msd()
    r = recs["8001"]
    assert r["started_at"] == "2023-12-20" and r["time_precision"] == "day"      # posted Thursday; found Wednesday
    assert r["raw"]["start_kind"] == "discovered" and r["raw"]["start_is_upper_bound"] is True
    assert r["ended_at"] is None and r["status"] == "unknown"
    assert r["waterbody_text"] == "Fee Fee Creek" and "until the cleanup is complete" in r["advice_text"]
    assert r["published_at"] == "2023-12-21T22:08:05Z" and r["raw"]["time_zone"] == "America/Chicago"
    assert r["discharger_id"] == "mo-st-louis-mo0025151"
    assert stats["notices"] == 4


def test_msd_contained_spill_unplaced_follow_up_linked_sheen_and_press_coverage_dropped():
    recs, _ = msd()
    assert recs["8002"]["waterbody_text"] is None and recs["8002"]["started_at"] == "2024-05-08"
    assert recs["8003"]["duplicate_of"] == recs["8002"]["event_id"]
    assert "8004" not in recs and "8005" not in recs
    r = recs["8006"]
    assert r["started_at"] == "2015-06-12" and r["volume_gal"] == 77000 and r["waterbody_text"] == "Sugar Creek; Mississippi River"


# ---------------------------------------------------------------- DNR concern reports

def _pdf(lines):
    """A one-page text PDF: lines is [(x, y, text)] (the reader's own coordinates, top of page at y 760)."""
    def esc(t):
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    ops = "BT /F1 9 Tf " + " ".join(f"1 0 0 1 {x} {y} Tm ({esc(t)}) Tj" for x, y, t in lines) + " ET"
    data = ops.encode("latin-1")
    return (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n2 0 obj\n<< /Length " + str(len(data)).encode() +
            b" >>\nstream\n" + data + b"\nendstream\nendobj\n%%EOF\n")


def _block(y, region, received, investigated, source, county, types, no, info, comments):
    rows = [(28.8, y, region), (93.55, y, received), (166.8, y, source[0]), (352.8, y, types[0]), (495.0, y, "XX"),
            (96.35, y - 12, investigated), (166.8, y - 12, source[1] if len(source) > 1 else county),
            (166.8, y - 23, county), (28.8, y - 47, "Concern No."), (100.25, y - 47, f" {no}"),
            (28.8, y - 68, "Concern Info"), (94.8, y - 68, info), (28.8, y - 92, "Comments"), (94.8, y - 92, comments)]
    if len(types) > 1:
        rows.append((352.8, y - 12, types[1]))
    return rows


def concern_pdf():
    head = [(369.1, 760, "Water Pollution Control Detail Report"), (399.5, 745, "Concerns Investigated Between"),
            (350.25, 730, "February 01, 2026 and February 28, 2026"),
            (28.8, 714, 'Note: "Concern Info" refers to the information provided to the department by the concerned party.'),
            (81.65, 680, "Date Received"), (166.8, 680, "Suspected Source"), (28.8, 668, "Region"),
            (72.7, 668, "Investigation Date")]
    b1 = _block(640, "KCRO", "2/16/2026", "2/18/2026", ["City of St.", "Joseph"], "Buchanan",
                ["Bypass or Sewer Overflow"], 70001,
                "From Webform - Date of Incident or Date First Noticed 02/15/2026 sewage entering Blacksnake Creek.",
                "The sanitary sewer overflow (SSO) was entered into the SSO/Bypass Event System. The SSO Event ID is 25395.")
    b2 = _block(520, "SWRO", "2/9/2026", "2/10/2026", ["Example Lagoon"], "Greene", ["Bypass or Sewer Overflow"], 70002,
                "Jane Example at 1234 Example Lane, 573-555-0100, says sewage runs into a ditch.",
                "No violations of the Missouri Clean Water Law were observed; no further actions.")
    b3 = _block(400, "NERO", "2/5/2026", "2/6/2026", ["Example Neighbor"], "Pettis",
                ["Single Family Residence", "Bypass or Sewer Overflow"], 70003,
                "A septic tank overflows behind a house.", "Forwarded to the county health department.")
    b4 = _block(280, "SERO", "2/12/2026", "2/13/2026", ["City of Marble", "Hill"], "Bollinger",
                ["Bypass or Sewer Overflow"], 70004,
                "Jane Example says a lift station overflows and sewage flows into Example Creek.",
                "Referred to the city.")
    b5 = _block(160, "SLRO", "2/20/2026", "2/21/2026", ["Example Mobile Home Park"], "Jefferson",
                ["Land Disturbance"], 70005, "Mud in a creek.", "Letter of Warning issued.")
    foot = [(28.8, 20, "Friday, March 6, 2026"), (525.8, 20, "Page 2 of 58")]
    return _pdf(head + b1 + b2 + b3 + b4 + b5 + foot)


def concerns():
    meta = {"page_url": "https://dnr.mo.gov/document-search/example", "pdf_url": "https://dnr.mo.gov/example.pdf",
            "last_revised": "2026-02-27"}
    recs, stats, safe = C.run([(concern_pdf(), meta)], [], AT)
    return {r["source_record_id"]: r for r in recs}, stats, safe


def test_concern_blocks_parse_with_the_reports_own_clocks():
    blocks, meta = C.blocks(concern_pdf())
    assert [b["no"] for b in blocks] == ["70001", "70002", "70003", "70004", "70005"]
    assert meta["period"] == ["2026-02-01", "2026-02-28"] and meta["generated"] == "2026-03-06"


def test_allegation_filter_keeps_operator_reports_and_public_concerns_marked_drops_the_unsupported():
    recs, stats, _ = concerns()
    assert set(recs) == {"70001", "70004"}
    assert stats["sewer_overflow_type"] == 4 and stats["drop_not_found"] == 1 and stats["drop_private"] == 1
    op = recs["70001"]
    assert op["raw"]["dnr_finding"] == "operator_reported" and op["raw"]["provenance"] == "operator"
    assert op["raw"]["citizen_caution"] is False and op["raw"]["sso_event_id"] == "25395"
    assert op["started_at"] == "2026-02-15" and op["reported_at"] == "2026-02-16" and op["time_precision"] == "day"
    assert op["raw"]["investigated_on"] == "2026-02-18" and op["published_at"] is None and op["ended_at"] is None
    assert op["discharger_name"] == "City of St. Joseph" and op["waterbody_text"] == "Blacksnake Creek"
    assert op["raw"]["county"] == "Buchanan County" and op["raw"]["report_generated"] == "2026-03-06"
    pub = recs["70004"]
    assert pub["raw"]["dnr_finding"] == "not_stated" and pub["raw"]["citizen_caution"] is True
    assert pub["raw"]["provenance"] == "public" and "not confirmed" in pub["authority"]
    assert pub["started_at"] == "2026-02-12" and pub["raw"]["start_kind"] == "received"
    assert pub["discharger_name"] == "City of Marble Hill"         # the pieces joined against Missouri's permit towns


def test_concern_text_and_people_never_reach_records_or_the_raw_save():
    recs, _, safe = concerns()
    blob = json.dumps(list(recs.values())) + json.dumps(safe)
    for p in PERSONAL + ["septic tank overflows behind", "runs into a ditch", "Example Lagoon", "Letter of Warning"]:
        assert p not in blob
    for r in recs.values():
        assert "info" not in r["raw"] and "comments" not in r["raw"] and "source" not in r["raw"]


def test_a_later_report_that_finds_nothing_withdraws_the_concern():
    meta = {"pdf_url": "https://dnr.mo.gov/example.pdf"}
    head = [(350.25, 730, "February 01, 2026 and February 28, 2026"), (28.8, 20, "Friday, March 6, 2026"),
            (525.8, 20, "Page 2 of 5")]
    kept = _pdf(head + _block(640, "SWRO", "2/9/2026", "2/10/2026", ["City of Marble", "Hill"], "Bollinger",
                              ["Bypass or Sewer Overflow"], 70010, "A lift station overflows.", "Referred to the city."))
    head2 = [(350.25, 730, "March 01, 2026 and March 31, 2026"), (28.8, 20, "Monday, April 6, 2026"),
             (525.8, 20, "Page 2 of 5")]
    later = _pdf(head2 + _block(640, "SWRO", "2/9/2026", "3/3/2026", ["City of Marble", "Hill"], "Bollinger",
                                ["Bypass or Sewer Overflow"], 70010, "A lift station overflows.",
                                "No violations were observed; no further action."))
    for order in ([(kept, meta), (later, meta)], [(later, meta), (kept, meta)]):     # the report periods decide
        recs, stats, _ = C.run(order, [], AT)
        assert recs == [] and stats["withdrawn"] == 1
    first, _, _ = C.run([(kept, meta)], [], AT)
    recs, stats, _ = C.run([(later, meta)], first, AT)                                # across runs too
    assert recs == [] and stats["withdrawn_concerns"][0]["concern_no"] == "70010"


def test_concerns_and_msd_are_placed_by_named_water_only():
    assert {r["raw"]["_placement"] for r in concerns()[0].values()} == {"named_water_only"}
    assert {r["raw"]["_placement"] for r in msd()[0].values()} == {"named_water_only"}


# ---------------------------------------------------------------- DNR outfall layer

def test_outfall_layer_supersedes_epa_rows_adds_new_ones_and_holds_back_the_ethanol_plant():
    L = _script("mo_outfall_layer")
    doc = {"features": [
        {"attributes": {"PERMIT_ID": "MO0025151", "P_FEAT_ID": "021", "CSO": "Y", "CA_NAME": "Metropolitan St. Louis "
                        "Sewer District", "FAC_NAME": "MSD Lemay WWTP", "REC_STREAM": "River des Peres", "OBJECTID": 1},
         "geometry": {"x": -90.2812345, "y": 38.5612345}},
        {"attributes": {"PERMIT_ID": "MO0023043", "P_FEAT_ID": "003", "CSO": "Y", "CA_NAME": "City of St. Joseph",
                        "FAC_NAME": "St Joseph WPF", "REC_STREAM": "Tributary to Missouri R.", "OBJECTID": 2},
         "geometry": {"x": -94.862, "y": 39.767}},
        {"attributes": {"PERMIT_ID": "MO0023043", "P_FEAT_ID": "001", "CSO": "N", "CA_NAME": "City of St. Joseph",
                        "OBJECTID": 3}, "geometry": {"x": -94.9, "y": 39.7}}]}
    epa = [{"npdes_permit": "MO0023043", "outfall": "003", "state": "MO", "outfall_status": "CSO", "outfall_kind": "cso"},
           {"npdes_permit": "MO0024911", "outfall": "010", "state": "MO", "outfall_status": "CSO", "outfall_kind": "cso"},
           {"npdes_permit": "MO0134198", "outfall": "009", "state": "MO", "outfall_status": "CSO", "outfall_kind": "cso"},
           {"npdes_permit": "MO0025151", "outfall": "163", "state": "MO", "outfall_status": "CLS", "outfall_kind": "cso"}]
    out = L.build(doc, epa, AT)
    rows = {(r["npdes_permit"], r["outfall"]): r for r in out["outfalls"]}
    assert rows[("MO0025151", "021")]["lat"] == 38.561234 and "supersedes" not in rows[("MO0025151", "021")]
    assert rows[("MO0023043", "003")]["supersedes"]["file"] == "data/outfalls-us.json"
    assert ("MO0023043", "001") not in rows                          # a plant outfall of a CSO permit
    assert rows[("MO0134198", "009")]["outfall_kind"] == "other"
    assert {x["npdes_permit"] for x in out["epa_not_on_state_layer"]} == {"MO0024911", "MO0134198"}


def test_outfall_file_counts():
    d = json.loads((ROOT / "data" / "outfalls-mo.json").read_text())
    assert d["cso_by_permit"] == {"MO0023043": 14, "MO0023221": 3, "MO0024929": 5, "MO0025151": 120, "MO0117960": 4}
    assert sum(1 for r in d["outfalls"] if r["outfall_kind"] == "other") == 1


# ---------------------------------------------------------------- operators, register, rules, zone

def mo_ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "MO"]


def test_operator_rows_hold_every_permit_once_with_the_feeds_ids_as_aliases():
    ops = mo_ops()
    permits = [p for r in ops for p in r["npdes_permits"]]
    assert len(permits) == len(set(permits))
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "MO"}
    assert plants <= set(permits)
    alias = {a: r for r in ops for a in r.get("aliases") or []}
    kc_row, msd_row = alias["mo-kansas-city-mo0024911"], alias["mo-st-louis-mo0025151"]
    assert {"MO0024911", "MO0024929"} <= set(kc_row["npdes_permits"]) and kc_row["kind"] == "cso"
    assert {"MO0025151", "MO0025178", "MO0004391"} <= set(msd_row["npdes_permits"])
    assert msd_row["outfall_count"] == 120 and kc_row["outfall_count"] == 85
    assert alias["mo-carrollton-mo0134198"]["kind"] == "plant"       # the ethanol plant is not a CSO operator
    assert not [r for r in ops if r["name"].startswith("City of Kansas City") and r is not kc_row]


def test_register_has_the_dnr_report_per_operator_and_the_feeds():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "mo.json").read_text())["channels"]}
    for r in mo_ops():
        row = reg[f"{r['id']}-dnr-report"]
        assert row["basis_kind"] == "law" and row["barrier"] == "no_web_page"
    assert reg["mo-kansas-city-mo0024911-news"]["feed_source_id"] == "mo-kc-water-overflow-notices"
    assert reg["mo-st-louis-mo0025151-alerts"]["feed_source_id"] == "mo-msd-stl-project-clear"
    assert reg["mo-dnr-concern-reports"]["feed_source_id"] == "mo-dnr-concern-reports"
    assert reg["mo-dnr-mogem-sso-reports"]["barrier"] == "login_required"
    cso = [k for k in reg if "-cso-permit-notice-" in k]
    assert len(cso) == 7 and not [k for k in cso if "mo0134198" in k]


def test_rules_row_and_day_start_caution():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    mo = rules["red"]["by_state"]["MO"]
    assert mo["hours"] is None and "RSMo 640.080" in mo["source"] and not re.search(r"\b(safe|clean)\b", mo["basis"], re.I)
    ds = rules["unresolved"]["day_start_caution"]["sources"]
    assert "mo-msd-stl-project-clear" in ds and "mo-dnr-concern-reports" in ds


def test_missouri_is_central_time():
    assert zones.zone_for("MO") == "America/Chicago" and zones.zone_for("MO", 38.6, -90.2) == "America/Chicago"


# ---------------------------------------------------------------- county-aware placement

def _waters():
    return {"brush-creek-kansas-city-mo": {"bbox": [-94.60, 39.02, -94.50, 39.06]},       # Jackson County
            "brush-creek-elsewhere-mo": {"bbox": [-92.30, 37.10, -92.20, 37.15]}}         # far from Kansas City


@pytest.fixture
def mo_known(monkeypatch):
    """Missouri counted as a state of the build (it is not live yet; the placement rule is the same once it is)."""
    known = set(S.states()) | {"MO"}
    monkeypatch.setattr(S, "states", lambda *a, **k: known)


def test_counties_field_keeps_a_name_within_the_operators_counties_only(mo_known):
    ev = {"raw": {"state": "MO", "counties": ["Jackson County", "Clay County", "Platte County", "Cass County"]},
          "source_id": "mo-kc-water-overflow-notices"}
    kept, why = S.county_slugs(["brush-creek-kansas-city-mo", "brush-creek-elsewhere-mo"], ev, _waters(),
                               lambda *a: None)
    assert kept == ["brush-creek-kansas-city-mo"] and "Jackson County or Clay County" in why


def test_single_county_field_behaves_as_before(mo_known):
    ev = {"raw": {"state": "MO", "county": "Jackson County"}, "source_id": "mo-dnr-concern-reports"}
    kept, why = S.county_slugs(["brush-creek-kansas-city-mo", "brush-creek-elsewhere-mo"], ev, _waters(),
                               lambda *a: None)
    assert kept == ["brush-creek-kansas-city-mo"] and why.endswith("the county the report gives")
    ev = {"raw": {"state": "MO"}, "source_id": "mo-dnr-concern-reports"}
    assert S.county_slugs(["a", "b"], ev, {}, lambda *a: None) == (["a", "b"], None)


def test_counties_list_is_not_read_for_other_states(monkeypatch):
    """Tennessee's records carry raw.counties of their own; its placement is the same as before the Missouri rule
    (Astra 2026-11-14 P1-10)."""
    known = set(S.states()) | {"TN"}
    monkeypatch.setattr(S, "states", lambda *a, **k: known)
    ev = {"raw": {"state": "TN", "counties": ["Knox County"]}, "source_id": "tn-tdec-events-report"}
    w = {"a-tn": {"bbox": [-83.95, 35.95, -83.90, 36.0]}, "b-tn": {"bbox": [-90.0, 35.1, -89.9, 35.2]}}
    assert S.county_slugs(["a-tn", "b-tn"], ev, w, lambda *a: None) == (["a-tn", "b-tn"], None)


# ---------------------------------------------------------------- state text and waters

def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "mo" / "state-text.md").read_text()
    assert t.startswith("---\nstate: MO\nname: Missouri\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "99 posts from July 2016 to August 2025" in t and "89 posts from June 2013 to January 2026" in t
    assert "945 entries (a concern investigated over more than one month appears in each month's report), 140 of them" in t and "131 distinct concerns" in t and "146 combined sewer outfalls on five permits" in t


def check_missing_waters(d: dict, nat: dict) -> None:
    """The invariants of research/mo/receiving-waters-missing.json, true as the state build writes it and after a water
    batch moves some or all of its names into `resolved` (re-review P2-6)."""
    names = _script("mo_report_water_names")
    held = {names.key(n) for w in nat["states"]["MO"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    rows, resolved = d["rows"], d.get("resolved") or []
    rows = rows if isinstance(rows, list) else []
    assert d["state"] == "MO" and d["waters"] == len(rows) and len(rows) + len(resolved) > 0
    for r in rows:
        assert names.key(r["name"]) not in held or r.get("resolved")
        assert not re.search(r"(?i)presumed use|storm|outfall", r["name"])
    keys = [(r["name"], r["county"]) for r in rows]
    assert len(keys) == len(set(keys))
    for r in resolved:
        assert r.get("name") and r.get("slugs"), r


def _batch(d: dict, share: float) -> dict:
    rows = list(d["rows"])
    n = round(len(rows) * share)
    done = [{"name": r["name"], "reports": r["reports"], "slugs": [r["name"].lower().replace(" ", "-") + "-mo"],
             "how": "built from NHD"} for r in rows[:n]]
    return {**d, "rows": rows[n:], "waters": len(rows) - n, "resolved": done}


def test_missing_waters_list_leaves_out_the_national_lists_names():
    d = json.loads((ROOT / "research" / "mo" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())
    check_missing_waters(d, nat)
    if not d.get("resolved"):                                  # before the batch: the same holds part- and fully-done
        check_missing_waters(_batch(d, 0.5), nat)
        check_missing_waters(_batch(d, 1.0), nat)


# ---------------------------------------------------------------- re-review fixes (2026-11-15)

from ingest import mo_dnr_hab as HAB


def test_dnr_hab_map_standing_blooms_are_advisories_from_the_first_read_whatever_their_age():
    """Re-review P1-5: a bloom DNR's map still shows as present, observed months before the site first read the map,
    is represented as a standing advisory (dated to the read, the observation day kept apart) and stays red while shown."""
    from datetime import datetime, timezone
    doc = json.loads((FIX / "hab_layer.json").read_text())
    recs, st = HAB.run(doc, [], AT)
    by = {r["raw"]["report_id"]: r for r in recs}
    assert set(by) == {"aaaa0001-0000-0000-0000-000000000001", "aaaa0001-0000-0000-0000-000000000002"}
    a = by["aaaa0001-0000-0000-0000-000000000001"]
    assert a["event_type"] == "hab_advisory" and a["status"] == "advisory_active" and a["started_at"] == AT
    assert a["time_precision"] == "poll" and a["raw"]["observed_on"] == "2026-05-18" and "sampled_at" not in a
    assert a["waterbody_text"] == "Example Lake" and (a["lat"], a["lon"]) == (38.951, -92.327)
    assert a["advice_text"] == "DNR's map: Harmful Algal Bloom Present." and a["raw"]["case_status"] == "Closed"
    assert st["by_code"] == {"advise": 2, "none": 1, "notice": 1} and st["open"] == 2
    ivs = S.event_intervals(a, "MO", datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert ivs[0]["color"] == "red" and ivs[0]["start"] == datetime(2026, 11, 14, 18, tzinfo=timezone.utc)
    later = "2026-12-20T18:00:00Z"
    recs2, st2 = HAB.run(doc, recs, later)                     # still shown: confirmed, never aged out
    a2 = {r["raw"]["report_id"]: r for r in recs2}["aaaa0001-0000-0000-0000-000000000001"]
    assert a2["raw"]["_last_seen_in_source"] == later and st2["opened"] == 0
    gone = {"features": doc["features"][1:]}
    recs3, st3 = HAB.run(gone, recs2, "2026-12-21T18:00:00Z")
    a3 = {r["raw"]["report_id"]: r for r in recs3}["aaaa0001-0000-0000-0000-000000000001"]
    assert a3["status"] == "advisory_lifted" and a3["raw"]["ended_at_precision"] == "poll" and st3["lifted"] == 1


def test_dnr_hab_map_bad_answers_fail_and_the_raw_save_is_cut_and_rounded(tmp_path, monkeypatch):
    import common
    doc = json.loads((FIX / "hab_layer.json").read_text())
    recs, _ = HAB.run(doc, [], AT)
    for bad in ({}, {"error": {}}, {"features": [], "exceededTransferLimit": True},
                {"features": [{"attributes": {"BloomStat": "advise"}, "geometry": {"x": -92.0, "y": 38.0}}]},
                {"features": [{"attributes": {"globalid": "x", "BloomStat": "advise"}}]},
                {"features": [{"attributes": {"globalid": "x", "BloomStat": "maybe"}}]}):
        monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
        common.write_events(HAB.SOURCE_ID, recs)
        f = tmp_path / "a.json"
        f.write_text(json.dumps(bad))
        assert HAB.main(["--file", str(f)]) == 1
        out = json.loads((tmp_path / f"{HAB.SOURCE_ID}.json").read_text())
        assert out["ok"] is False and len(out["records"]) == 2
    extra = {"features": [{**doc["features"][0], "attributes": {**doc["features"][0]["attributes"],
                                                                "PubInfo": "Call Jane Example at 573-555-0100"}}]}
    saved = HAB.rounded(extra)
    assert "PubInfo" not in json.dumps(saved) and saved["features"][0]["geometry"] == {"x": -92.327, "y": 38.951}


def test_dnr_hab_map_is_registered_as_a_read_feed():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "mo.json").read_text())["channels"]}
    row = reg["mo-dnr-hab-map"]
    assert row["feed_source_id"] == "mo-dnr-hab-map" and not row.get("availability_only")
    assert (ROOT / "data" / "sources" / "mo-dnr-hab-map.yaml").exists()


def test_a_response_or_publication_bound_is_never_an_unqualified_start_in_any_export():
    """Re-review P1-6: KC's response time, MSD's post day, DNR's receipt day and Leavenworth's notified time stay
    qualified as upper bounds in the intervals, the slim record, the index, active.json and the CSV; a record whose
    start is its own (and every other state's) is written as before."""
    from datetime import datetime, timezone
    from export import build as B
    from export import csv as X
    r = kc()[0]["9001"]
    assert r["raw"]["start_kind"] == "response"
    ivs = S.event_intervals(r, "MO", datetime(2024, 10, 15, tzinfo=timezone.utc))
    assert ivs and all(iv["started_at_bound"] == "on_or_before" and iv["started_at_kind"] == "response" for iv in ivs)
    slim = B.slim_event({**r, "file": "events/x.json"})
    assert "raw" not in slim and slim["started_at_bound"] == "on_or_before" and slim["started_at_kind"] == "response"
    ix = B.index_obj(slim)
    assert ix["started_at_bound"] == "on_or_before" and ix["started_at_kind"] == "response"
    act = B.active_entries({r["event_id"]: [{"status": "red", "water": "w"}]}, {r["event_id"]: slim})
    assert act[0]["started_at_bound"] == "on_or_before"
    assert X.start_precision_text(r) == "minute; on or before (response)"
    own = kc()[0]["9002"]                                     # "began at": the start is the overflow's own
    assert own["raw"]["start_kind"] == "start" and S.start_bound(own) == {}
    assert X.start_precision_text(own) == "minute" and "started_at_bound" not in B.slim_event({**own, "file": "f"})
    plain = {"event_id": "ma-massdep:1", "source_id": "ma-massdep", "event_type": "cso", "status": "ended",
             "started_at": "2026-06-12T10:00:00-04:00", "time_precision": "minute", "file": "f", "water_slugs": [],
             "raw": {"start_kind": "response"}}                # another state's record: no flag, no change
    assert "started_at_bound" not in B.slim_event(plain) and "started_at_bound" not in B.index_obj(B.slim_event(plain))
    assert X.start_precision_text(plain) == "minute"


def test_dnr_concern_received_day_is_an_upper_bound():
    recs = list(concerns()[0].values())
    got = [r for r in recs if r["raw"]["start_kind"] == "received"]
    assert got and all(r["raw"]["start_is_upper_bound"] is True and S.start_bound(r)["started_at_kind"] == "received"
                       for r in got)
    assert all(S.start_bound(r) == {} for r in recs if r["raw"]["start_kind"] == "incident")


def _marble(period, footer, investigated, comments, no=70010):
    head = [(350.25, 730, period), (28.8, 20, footer), (525.8, 20, "Page 2 of 5")]
    return _pdf(head + _block(640, "SWRO", "2/9/2026", investigated, ["City of Marble", "Hill"], "Bollinger",
                              ["Bypass or Sewer Overflow"], no, "A lift station overflows.", comments))


FEB = ("February 01, 2026 and February 28, 2026", "Friday, March 6, 2026")
MAR = ("March 01, 2026 and March 31, 2026", "Monday, April 6, 2026")


def test_a_withdrawn_concern_stays_withdrawn_when_an_older_report_is_read_again():
    """Re-review P1-7: keep (February) -> rejection (March) -> February read again alone, in a later run: nothing
    returns; a later revision of the March report that keeps it restores it; repeat runs change nothing."""
    meta = {"pdf_url": "https://dnr.mo.gov/feb.pdf"}
    keep = _marble(*FEB, "2/10/2026", "Referred to the city.")
    reject = _marble(*MAR, "3/3/2026", "No violations were observed; no further action.")
    r1, s1, _ = C.run([(keep, meta)], [], AT)
    r2, s2, _ = C.run([(reject, {"pdf_url": "https://dnr.mo.gov/mar.pdf"})], r1, AT, s1["decisions"])
    assert r2 == [] and s2["decisions"]["70010"]["kept"] is False
    r3, s3, _ = C.run([(keep, meta)], r2, AT, s2["decisions"])                         # the older report again
    assert r3 == [] and s3["older_decision_ignored"] == 1 and s3["decisions"] == s2["decisions"]
    r4, s4, _ = C.run([(keep, meta)], r3, AT, s3["decisions"])                         # and again
    assert r4 == [] and s4["decisions"] == s2["decisions"]
    # an older revision of the February report (an earlier Last revised date) changes nothing either
    r5, _, _ = C.run([(keep, {**meta, "last_revised": "2026-02-01"})], r4, AT, s4["decisions"])
    assert r5 == []
    # the March report revised (a later Last revised date) to keep it: restored
    revised = _marble(*MAR, "3/3/2026", "Referred to the city.")
    r6, s6, _ = C.run([(revised, {"pdf_url": "https://dnr.mo.gov/mar.pdf", "last_revised": "2026-05-01"})], r5, AT,
                      s4["decisions"])
    assert [r["source_record_id"] for r in r6] == ["70010"] and s6["decisions"]["70010"]["kept"] is True
    # a private-system correction in a still later revision withdraws it again
    private = _pdf([(350.25, 730, MAR[0]), (28.8, 20, MAR[1]), (525.8, 20, "Page 2 of 5")] + _block(
        640, "SWRO", "2/9/2026", "3/3/2026", ["Example Neighbor"], "Bollinger",
        ["Single Family Residence", "Bypass or Sewer Overflow"], 70010, "A septic tank overflows.", "Forwarded."))
    r7, s7, _ = C.run([(private, {"pdf_url": "https://dnr.mo.gov/mar.pdf", "last_revised": "2026-06-01"})], r6, AT,
                      s6["decisions"])
    assert r7 == [] and s7["decisions"]["70010"]["decision"] == "drop_private"


def test_the_decision_ledger_survives_through_main_and_old_saves_are_migrated(tmp_path, monkeypatch):
    """Re-review P1-7 and P1-8: an old-format save (no ledger, no placement guard, a received-day start unflagged, a
    removed text field) replayed through main(): migrated in memory, the ledger written and used on the next run."""
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    keep = _marble(*FEB, "2/10/2026", "Referred to the city.")
    first, _, _ = C.run([(keep, {"pdf_url": "https://dnr.mo.gov/feb.pdf"})], [], AT)
    old = json.loads(json.dumps(first))
    for r in old:                                               # the state branch's earlier format
        r["raw"].pop("_placement")
        r["raw"].pop("start_is_upper_bound")
        r["raw"].pop("decision_revision", None)
        r["raw"]["info"] = "A lift station overflows near 1234 Example Lane."
        r["waterbody_text"] = None
    (tmp_path / f"{C.SOURCE_ID}.json").write_text(json.dumps({"source_id": C.SOURCE_ID, "ok": True, "meta": {},
                                                               "records": old}))
    reject = tmp_path / "mar.pdf"
    reject.write_bytes(_marble(*MAR, "3/3/2026", "No violations were observed; no further action."))
    feb = tmp_path / "feb.pdf"
    feb.write_bytes(keep)
    other = tmp_path / "other.pdf"
    other.write_bytes(_marble(*MAR, "3/3/2026", "Referred to the city.", no=70011))
    assert C.main(["--file", str(other), "--pdf-url", "https://dnr.mo.gov/other.pdf"]) == 0
    doc = json.loads((tmp_path / f"{C.SOURCE_ID}.json").read_text())
    by = {r["source_record_id"]: r for r in doc["records"]}
    assert set(by) == {"70010", "70011"} and "1234 Example" not in json.dumps(doc)
    m = by["70010"]["raw"]
    assert m["_placement"] == "named_water_only" and m["start_is_upper_bound"] is True and "info" not in m
    assert set(doc["meta"]["decisions"]) == {"70010", "70011"}
    from build import provisional_outfalls as P
    assert not any(not P.named_water_only(r) for r in doc["records"])                  # nothing to geocode
    assert C.main(["--file", str(reject), "--pdf-url", "https://dnr.mo.gov/mar.pdf"]) == 0
    assert C.main(["--file", str(feb), "--pdf-url", "https://dnr.mo.gov/feb.pdf"]) == 0
    doc = json.loads((tmp_path / f"{C.SOURCE_ID}.json").read_text())
    assert {r["source_record_id"] for r in doc["records"]} == {"70011"}
    assert ["https://dnr.mo.gov/feb.pdf", None] in doc["meta"]["reports_seen"]


def test_kc_old_saves_lose_post_text_and_gain_every_water_on_repeated_runs(tmp_path, monkeypatch):
    """Re-review P1-8: an old-format save run three times: no post text, every named water, the
    placement guard, no duplicate."""
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    recs, _ = K.run([(FIX / "kc_feed.xml").read_bytes()], [], AT)
    old = json.loads(json.dumps(recs))
    for r in old:
        r["raw"]["post_text"] = "Call Staff Example at 573-555-0100."
        r["raw"].pop("_placement")
        if len(r["raw"]["waters_named"]) > 1 and r["raw"]["reached_water"] is not False:
            r["waterbody_text"] = r["raw"]["waters_named"][0]
    (tmp_path / f"{K.SOURCE_ID}.json").write_text(json.dumps({"source_id": K.SOURCE_ID, "ok": True, "meta": {},
                                                               "records": old}))
    out, _ = K.run([], old, "2026-11-15T00:00:00Z")
    for _ in range(2):
        out, _ = K.run([], out, "2026-11-15T01:00:00Z")
    assert len(out) == len(recs) and "555-0100" not in json.dumps(out)
    assert {r["raw"]["_placement"] for r in out} == {"named_water_only"}
    assert {r["event_id"]: r["waterbody_text"] for r in out} == {r["event_id"]: r["waterbody_text"] for r in recs}


def test_names_phones_and_addresses_never_reach_titles_advice_links_or_the_raw_saves():
    """Re-review P1-9: a synthetic person, telephone and house number in an MSD title, advice and link, in a KC title and
    link and in a KDHE release's title and description: absent from every record and raw save, earlier saves too."""
    from ingest import ks_kdhe_stream_advisories as A
    post = {"id": 7001, "date_gmt": "2026-03-02T15:00:00", "modified_gmt": "2026-03-02T15:00:00",
            "link": "https://msdprojectclear.org/newsroom/alerts/overflow-at-4321-example-lane-reported-by-jane-example/",
            "title": {"rendered": "Overflow reported by Jane Example, 573-555-0100, at 4321 Example Lane in Example Heights"},
            "content": {"rendered": "<p>On Monday sewage reached Example Creek. Residents should avoid Example Creek; "
                                    "call Staff Example at 573-555-0100.</p>"}}
    recs, _ = M.run([[post]], [], AT)
    saved = json.dumps(M.safe_posts([post]))
    blob = json.dumps(recs) + saved
    for p in PERSONAL:
        assert p not in blob, p
    assert recs[0]["source_url"] == "https://msdprojectclear.org/?p=7001"
    assert recs[0]["raw"]["place_key"] == "exampleheights"
    old = json.loads(json.dumps(recs))
    old[0]["raw"]["title"] = post["title"]["rendered"]
    old[0]["advice_text"] = "Avoid Example Creek; call Staff Example at 573-555-0100."
    old[0]["source_url"] = post["link"]
    again, _ = M.run([], old, AT)
    for p in PERSONAL:
        assert p not in json.dumps(again), p
    feed = (b'<?xml version="1.0"?><rss><channel><item><title>Stream Advisory Issued for Example Creek in Shawnee County'
            b'</title><link>https://www.kdhe.ks.gov/CivicAlerts.aspx?aid=77</link><pubDate>Mon, 02 Nov 2026 09:00:00 -0600'
            b'</pubDate><description>Sewage from 1234 Example Lane reached Example Creek. Jane Example, 913-555-0199, '
            b'says call her.</description></item></channel></rss>')
    ks, _ = A.run(feed, [], AT)
    blob = json.dumps(ks) + A.safe_feed(feed).decode()
    for p in PERSONAL + ["Jane Example", "913-555-0199"]:
        assert p not in blob, p
    assert ks[0]["raw"]["cause"] == "sewage" and ks[0]["advice_text"].startswith("KDHE stream advisory for Example Creek")
    old = json.loads(json.dumps(ks))
    old[0]["advice_text"] = "Sewage from 1234 Example Lane. Jane Example, 913-555-0199."
    old[0]["raw"]["description"] = old[0]["advice_text"]
    again, _ = A.run(b'<?xml version="1.0"?><rss><channel></channel></rss>', old, AT)
    assert "Jane Example" not in json.dumps(again) and "1234" not in json.dumps(again)


def test_safe_text_keeps_places_and_safe_link_keeps_plain_addresses():
    assert K.safe_text("avoid the creek by Example Creek") == "avoid the creek by Example Creek"
    assert "Jane" not in K.safe_text("reported by Jane Example near the plant")
    # with no numeric permalink the address stays unless it carries a number outside a date (verification P1-4: a
    # numeric permalink, where there is one, is always used instead)
    assert K.safe_link("https://x.org/news/overflow-near-example-street/", None) == \
        "https://x.org/news/overflow-near-example-street/"
    assert K.safe_link("https://x.org/news/overflow-on-june-3-2024/", "https://x.org/news/") == \
        "https://x.org/news/overflow-on-june-3-2024/"
    assert K.safe_link("https://x.org/news/overflow-at-1234-example-st/", "https://x.org/?p=1") == "https://x.org/?p=1"


def test_msd_post_without_a_publication_time_or_malformed_fails_the_run_and_keeps_the_records(tmp_path, monkeypatch):
    """Re-review P2-4."""
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    good = json.loads((FIX / "msd_posts.json").read_text())
    recs, _ = M.run([good], [], AT)
    common.write_events(M.SOURCE_ID, recs)
    first = json.loads((tmp_path / f"{M.SOURCE_ID}.json").read_text())
    nodate = [{**p, "date_gmt": None} for p in good]
    broken = [{**good[0], "title": None}]
    for bad in (nodate, [{**p, "date_gmt": "not a date"} for p in good], broken):
        f = tmp_path / "page.json"
        f.write_text(json.dumps(bad))
        assert M.main(["--file", str(f)]) == 1
        out = json.loads((tmp_path / f"{M.SOURCE_ID}.json").read_text())
        assert out["ok"] is False and out["records"] == first["records"]


def test_a_concern_reclassified_outside_the_sewer_category_loses_its_sewage_record():
    """Verification P1-3: sewer (February) -> the March entry filed only as a single-family residence and referred to
    the county -> February read again: no sewage record, the ledger keeps the reclassification."""
    keep = _marble(*FEB, "2/10/2026", "Referred to the city.")
    resid = _pdf([(350.25, 730, MAR[0]), (28.8, 20, MAR[1]), (525.8, 20, "Page 2 of 5")] + _block(
        640, "SWRO", "2/9/2026", "3/3/2026", ["Example Neighbor"], "Bollinger",
        ["Single Family Residence"], 70010, "A septic tank overflows.", "Referred to the county health department."))
    r1, s1, _ = C.run([(keep, {"pdf_url": "https://dnr.mo.gov/feb.pdf"})], [], AT)
    assert len(r1) == 1
    r2, s2, _ = C.run([(resid, {"pdf_url": "https://dnr.mo.gov/mar.pdf"})], r1, AT, s1["decisions"])
    assert r2 == [] and s2["decisions"]["70010"]["decision"] == "reclassified_out_of_scope"
    assert s2["withdrawn_concerns"][0]["decision"] == "reclassified_out_of_scope"
    r3, s3, _ = C.run([(keep, {"pdf_url": "https://dnr.mo.gov/feb.pdf"})], r2, AT, s2["decisions"])
    assert r3 == [] and s3["older_decision_ignored"] == 1
    for order in ([(keep, {}), (resid, {})], [(resid, {}), (keep, {})]):       # one run, either order
        r, _, _ = C.run(order, [], AT)
        assert r == []
    # a concern never filed as sewer is still not read
    r4, s4, _ = C.run([(resid, {})], [], AT)
    assert r4 == [] and "70010" not in s4["decisions"]


def test_msd_names_in_titles_and_slugs_never_reach_the_key_the_link_or_the_raw_save():
    """Verification P1-4: a title "Overflow reported by Jane Example" and a name-bearing slug: the place key, the
    record and safe_posts carry neither; an earlier save's unscrubbed key is dropped at the next read."""
    p = {"id": 8101, "date_gmt": "2026-05-27T15:00:00", "modified_gmt": "2026-05-27T15:00:00",
         "link": "https://msdprojectclear.org/newsroom/alerts/overflow-reported-by-jane-example/",
         "title": {"rendered": "Overflow reported by Jane Example"},
         "content": {"rendered": "<p>An overflow was discovered Tuesday into Example Creek.</p>"}}
    recs, _ = M.run([[p]], [], AT)
    blob = json.dumps(recs) + json.dumps(M.safe_posts([p]))
    assert "jane" not in blob.lower() and recs[0]["source_url"] == "https://msdprojectclear.org/?p=8101"
    old = json.loads(json.dumps(recs[0]))
    old["raw"]["place_key"] = "overflowreportedbyjaneexample"
    old["raw"].pop("place_key_version")
    again, _ = M.run([], [old], AT)
    assert "jane" not in json.dumps(again).lower()


def test_kc_and_shared_links_treat_a_year_shaped_house_number_as_a_house_number():
    """Verification P1-4: only a number in a date position is exempt."""
    assert K.safe_link("https://x.org/news/overflow-at-2026-example-lane/", None) == \
        "https://x.org/news/overflow-at-2026-example-lane/"     # no permalink to fall back on: unchanged
    assert K.safe_link("https://x.org/news/overflow-at-2026-example-lane/", "https://x.org/news/") == "https://x.org/news/"
    assert K.safe_link("https://x.org/news/overflow-may-27-2026/", "https://x.org/news/") == \
        "https://x.org/news/overflow-may-27-2026/"
    assert K.safe_link("https://x.org/news/a-slug/", "https://x.org/?post_type=news1&p=9") == \
        "https://x.org/?post_type=news1&p=9"


def test_kc_end_date_before_the_stop_verb_and_ambiguous_dates():
    """Verification P2-2: the end clause's own date, before or after the verb; several dates before it: no end."""
    from datetime import date
    pub = date(2026, 6, 1)
    t = K.times("Crews responded May 27, 2026 at 9:00 a.m. to an overflow. On May 29, 2026, the overflow stopped at "
                "4:00 p.m.", pub)
    assert t["start"].startswith("2026-05-27T09:00") and t["end"] == "2026-05-29T16:00:00-05:00"
    t = K.times("Crews responded May 27 at 9:00 a.m. to an overflow. The overflow stopped May 28 at 4:00 p.m.", pub)
    assert t["end"] == "2026-05-28T16:00:00-05:00"
    t = K.times("Crews responded May 27 at 9:00 a.m. to an overflow. Between May 27 and May 29 the overflow stopped "
                "at 4:00 p.m.", pub)
    assert t["end"] is None
    t = K.times("Crews responded May 27 at 9:00 a.m. to an overflow. The overflow stopped at 4:00 p.m.", pub)
    assert t["end"] == "2026-05-27T16:00:00-05:00"
    t = K.times("Crews responded Dec. 31, 2025 at 10:00 p.m. to an overflow. On Jan. 1, 2026, it stopped at 2:00 a.m.",
                date(2026, 1, 2))
    assert t["end"] == "2026-01-01T02:00:00-06:00"


def test_kc_notices_with_invalid_publication_dates_fail_the_run_and_keep_the_records(tmp_path, monkeypatch):
    """Verification P2-5: a notice whose pubDate cannot be read fails the run through main(), never a successful
    run with the notices dropped."""
    import re as _re
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    good = (FIX / "kc_feed.xml").read_bytes()
    recs, _ = K.run([good], [], AT)
    common.write_events(K.SOURCE_ID, recs)
    bad = tmp_path / "bad.xml"
    bad.write_bytes(_re.sub(rb"<pubDate>[^<]*</pubDate>", b"<pubDate>not a date</pubDate>", good))
    assert K.main(["--file", str(bad)]) == 1
    out = json.loads((tmp_path / f"{K.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and len(out["records"]) == len(recs) > 0


def test_kc_stop_today_is_the_publication_day_and_a_dated_stop_survives_a_day_only_start():
    """Verification 2 P2: a post published May 29 about a response on May 27 that "stopped today at 4:00 p.m." ends
    May 29, not May 27; a stop with its own date is kept when the start has only a day; the caution intervals follow."""
    from datetime import datetime, timezone

    def item(body, pid):
        return {"title": "Customers Advised of Wastewater Overflow near Example Street",
                "link": f"https://www.kcwater.us/news/example-{pid}/", "date": "Fri, 29 May 2026 22:00:00 +0000",
                "guid": f"https://www.kcwater.us/?post_type=news1&p={pid}", "html": f"<p>{body}</p>"}
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    utc = lambda dd, h: datetime(2026, 5, dd, h, tzinfo=timezone.utc)
    r = K.record(item("KC Water crews responded to a wastewater overflow near Example Street at 9:00 a.m. on "
                      "Wednesday, May 27, 2026. The overflow stopped today at 4:00 p.m. About 500 gallons entered "
                      "Brush Creek.", "1"), AT)
    assert r["started_at"] == "2026-05-27T09:00:00-05:00" and r["ended_at"] == "2026-05-29T16:00:00-05:00"
    ivs = [(iv["color"], iv["start"], iv["end"]) for iv in S.event_intervals(r, "MO", now)]
    assert ivs == [("red", utc(27, 14), utc(29, 21)),
                   ("yellow", utc(29, 21), datetime(2026, 6, 1, 21, tzinfo=timezone.utc))]
    r2 = K.record(item("KC Water crews responded to a wastewater overflow near Example Street on Wednesday, May 27, "
                       "2026. The overflow stopped May 28 at 4:00 p.m. About 500 gallons entered Brush Creek.", "2"), AT)
    assert r2["time_precision"] == "day" and r2["ended_at"] == "2026-05-28T16:00:00-05:00"
    assert r2["raw"]["ended_at_precision"] == "minute"
    ivs2 = [(iv["color"], iv["start"], iv["end"]) for iv in S.event_intervals(r2, "MO", now)]
    assert ivs2 == [("red", utc(27, 5), utc(28, 21)), ("yellow", utc(28, 21), utc(31, 21))]
    # a day-only start and a stop with no date of its own: the end day is not known, so no end
    from datetime import date
    t = K.times("Crews responded May 27 to an overflow. The overflow stopped at 4:00 p.m.", date(2026, 5, 29))
    assert t["precision"] == "day" and t["end"] is None
    t = K.times("Crews responded May 27 at 9:00 a.m. to an overflow. It stopped yesterday at 4:00 p.m.",
                date(2026, 5, 29))
    assert t["end"] == "2026-05-28T16:00:00-05:00"


def test_kc_stop_the_next_day_is_the_day_after_whatever_the_clock_order():
    """Verification 3 P2-2: a response May 27 at 9:00 a.m. that "stopped the next day at 4:00 p.m." ends May 28 (the
    later clock no longer keeps it on May 27); an earlier clock, "the following morning", a day-only start, a dated
    sentence before the stop and "the next day" before the verb all end the day after; the caution intervals follow."""
    from datetime import date, datetime, timezone
    pub = date(2026, 5, 29)
    t = lambda s: K.times(s, pub)
    r = "KC Water crews responded to an overflow at 9:00 a.m. on May 27, 2026. "
    assert t(r + "The overflow stopped the next day at 4:00 p.m.")["end"] == "2026-05-28T16:00:00-05:00"
    assert t(r + "The overflow stopped the next day at 4:00 a.m.")["end"] == "2026-05-28T04:00:00-05:00"
    assert t(r + "It stopped the following morning at 10:30 a.m.")["end"] == "2026-05-28T10:30:00-05:00"
    assert t(r + "It was stopped at 6:00 p.m. the next day.")["end"] == "2026-05-28T18:00:00-05:00"
    assert t(r + "The next day the overflow stopped at 1:00 p.m.")["end"] == "2026-05-28T13:00:00-05:00"
    assert t(r + "It stopped at 4:00 p.m.")["end"] == "2026-05-27T16:00:00-05:00"          # no next-day words: same day
    assert t(r + "It stopped at 4:00 a.m.")["end"] == "2026-05-28T04:00:00-05:00"          # before the start: next day
    d = t("KC Water crews responded to an overflow on May 27, 2026. The overflow stopped the next day at 4:00 p.m.")
    assert d["precision"] == "day" and d["end"] == "2026-05-28T16:00:00-05:00"
    e = t(r + "On May 28, 2026 crews worked on it and it stopped the next day at 4:00 p.m.")
    assert e["end"] == "2026-05-29T16:00:00-05:00"
    # the interval: red from the response to the next day's stop, then the 72-hour caution
    item = {"title": "Customers Advised of Wastewater Overflow near Example Street",
            "link": "https://www.kcwater.us/news/example-9/", "date": "Fri, 29 May 2026 22:00:00 +0000",
            "guid": "https://www.kcwater.us/?post_type=news1&p=9",
            "html": f"<p>{r}The overflow stopped the next day at 4:00 p.m. About 500 gallons entered Brush Creek.</p>"}
    rec = K.record(item, AT)
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    utc = lambda dd, h: datetime(2026, 5, dd, h, tzinfo=timezone.utc)
    ivs = [(iv["color"], iv["start"], iv["end"]) for iv in S.event_intervals(rec, "MO", now)]
    assert ivs == [("red", utc(27, 14), utc(28, 21)), ("yellow", utc(28, 21), utc(31, 21))]
