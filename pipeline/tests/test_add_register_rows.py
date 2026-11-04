"""scripts/add_register_rows.py: per-operator rows of data/notice-channels.json for duties the law puts on every operator
(docs/collection-checklist.md §2), built on a fixture and checked on the real register.
Run from pipeline/: python -m pytest tests/test_add_register_rows.py -q
"""
from __future__ import annotations

import importlib.util
import json

from common import DATA_DIR, ROOT
from ingest import notification_pages as NP

_spec = importlib.util.spec_from_file_location("add_register_rows", ROOT / "scripts" / "add_register_rows.py")
ARR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ARR)

REG = json.loads((DATA_DIR / "notice-channels.json").read_text())
DIS = json.loads((DATA_DIR / "dischargers.json").read_text())
BY_ID = {r["id"]: r for r in REG["channels"]}


def nc_op(oid, permits, channel="Press release ... (G.S. 143-215.1C(b)). No web posting is required.", **kw):
    return {"id": oid, "name": kw.get("name", oid.title()), "state": "NC", "kind": kw.get("kind", "sso"),
            "npdes_permit": permits[0], "npdes_permits": permits, "notification_channel": channel}


FIX_DIS = [
    nc_op("nc-big", ["WQCS00001", "NC0000001"]),                          # plant over the threshold
    nc_op("nc-small", ["NC0000002"], kind="plant"),                        # plant at 0.2 MGD: out
    nc_op("nc-small-with-sewers", ["WQCS00003", "NC0000003"]),             # small plant, collection flow unknown: in
    nc_op("nc-sewers-only", ["WQCS00004"]),                                # no flow on record: in
    nc_op("nc-zero", ["NCG550001"], kind="plant"),                         # ICIS flow 0 = not entered: in
    nc_op("nc-mill", ["WQCSD0005"], channel="Press release ... (G.S. 143-215.1C(c), works other than municipal ..."),
    {"id": "ga-x", "name": "X", "state": "GA", "kind": "plant", "npdes_permit": "GA0000001", "npdes_permits": ["GA0000001"],
     "notification_channel": "None found online (not searched individually)"},
]
FIX_PLANTS = {"outfalls": [
    {"state": "NC", "npdes_permit": "NC0000001", "design_flow_mgd": 4.5},
    {"state": "NC", "npdes_permit": "NC0000001", "design_flow_mgd": 1.0},
    {"state": "NC", "npdes_permit": "NC0000002", "design_flow_mgd": 0.2},
    {"state": "NC", "npdes_permit": "NC0000003", "design_flow_mgd": 0.15},
    {"state": "NC", "npdes_permit": "NCG550001", "design_flow_mgd": 0},
    {"state": "GA", "npdes_permit": "GA0000001", "design_flow_mgd": 9.0},
]}
OLD_ROW = {"id": "nc-big-annual-report", "state": "NC", "operator_id": "nc-big", "agency": None, "name": "stale",
           "permit": None, "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": "old",
           "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "unknown",
           "note": "old note, not searched individually", "checked": "2026-01-01", "barrier": "not_verified"}


def _files(tmp_path, channels=()):
    reg = {"about": NP.ABOUT, "schema_version": 1, "schema": NP.SCHEMA, "channels": list(channels)}
    paths = {"register": tmp_path / "reg.json", "dis_path": tmp_path / "dis.json", "plants_path": tmp_path / "pl.json"}
    paths["register"].write_text(json.dumps(reg, indent=1) + "\n")
    paths["dis_path"].write_text(json.dumps(FIX_DIS))
    paths["plants_path"].write_text(json.dumps(FIX_PLANTS))
    return paths


# ---------------------------------------------------------------- nc-annual: G.S. 143-215.1C(a)

def test_the_annual_report_rows_follow_the_flow_threshold_and_skip_industrial_works(tmp_path):
    paths = _files(tmp_path, [OLD_ROW])
    rep = ARR.run(["nc-annual"], **paths)
    doc = json.loads(paths["register"].read_text())
    rows = {r["id"]: r for r in doc["channels"]}
    assert set(rows) == {f"nc-{x}-annual-report" for x in ("big", "small-with-sewers", "sewers-only", "zero")}
    assert dict(rep["nc-annual"]["left_out"]).keys() == {"nc-small", "nc-mill"}
    assert "0.2 MGD or less" in dict(rep["nc-annual"]["left_out"])["nc-small"]
    big = rows["nc-big-annual-report"]                                    # the stale row is rebuilt, not kept
    assert big["name"] == "Nc-Big" and big["checked"] == ARR.CHECKED
    assert "NC0000001 is 4.5 MGD, over the threshold" in big["note"] and "was not checked" in big["note"]
    assert "flow not checked" in rows["nc-sewers-only-annual-report"]["note"]
    assert "NC0000003 is 0.15 MGD, under the threshold" in rows["nc-small-with-sewers-annual-report"]["note"]
    assert "NCG550001" in rows["nc-zero-annual-report"]["note"]          # a 0 flow is not entered, not zero
    for r in rows.values():
        assert r["basis_kind"] == "law" and r["legal_basis"].startswith('G.S. 143-215.1C(a): "The owner or operator')
        assert r["urls"] == [] and r["monitored"] is False and r["unmonitored_reason"] == "other"
        assert r["records"] is False and r["note"].startswith("No web form")
        assert "200,000 gallons a day" in r["note"] and "the Department" in r["note"]
        assert (r["barrier"], r.get("barrier_review")) == NP.barrier_for(r) == ("not_verified", None)
    assert NP.validate_register(doc, FIX_DIS) == []
    # idempotent
    before = paths["register"].read_text()
    ARR.run(["nc-annual"], **paths)
    assert paths["register"].read_text() == before


def test_the_real_register_has_an_annual_report_row_for_every_north_carolina_operator_in_scope():
    plants = json.loads((DATA_DIR / "outfalls-plants-us.json").read_text())
    flows = ARR.design_flows(plants, "NC")
    for op in DIS:
        if op["state"] != "NC":
            continue
        ok, _ = ARR.nc_annual_scope(op, flows)
        assert (f"{op['id']}-annual-report" in BY_ID) == ok, op["id"]
    rows = [r for r in REG["channels"] if r["id"].endswith("-annual-report") and r["state"] == "NC"]
    assert len(rows) > 300
    assert all(r["legal_basis"] == ARR.LAW_NC_A and r["sources"] == ["nc-law-gs-143-215-1c-a"] for r in rows)
    # (a) quoted whole, as ncleg.gov gives it
    assert ARR.LAW_NC_A.endswith('no later than 60 days after the end of the calendar or fiscal year."')
    assert "having an average annual flow greater than 200,000 gallons per day" in ARR.LAW_NC_A
    research = json.loads((ROOT / "research" / "nc" / "sources.json").read_text())
    law = next(r for r in research if r["id"] == "nc-law-gs-143-215-1c-a")
    assert law["role"] == "law" and law["status"] == "used" and ARR.LAW_NC_A.split(": ", 1)[1] in law["notes"]


# ---------------------------------------------------------------- scripts/gen_source_checklist.py --refresh

def test_the_checklist_refresh_replaces_one_area_in_place():
    spec = importlib.util.spec_from_file_location("gen_source_checklist", ROOT / "scripts" / "gen_source_checklist.py")
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    rows = [{"id": "a1", "area": "ma", "status": "used"}, {"id": "g1", "area": "ga", "status": "candidate"},
            {"id": "g2", "area": "ga", "status": "watch"}, {"id": "f1", "area": "fl", "status": "used"}]
    out = G.refresh(rows, "ga", [{"id": "g1", "status": "used"}, {"id": "g2", "status": "watch"},
                                 {"id": "g3", "status": "used"}])
    assert [(r["id"], r["area"], r["status"]) for r in out] == [
        ("a1", "ma", "used"), ("g1", "ga", "used"), ("g2", "ga", "watch"), ("g3", "ga", "used"), ("f1", "fl", "used")]
    for bad in ([{"id": "f1", "status": "used"}],):
        try:
            G.refresh(rows, "ga", bad)
        except SystemExit as e:
            assert "another area" in str(e)
        else:
            raise AssertionError("a clash with another area must be refused")
    # the checklist on disk is what the research says now
    checklist = json.loads((ROOT / "docs" / "source-checklist.json").read_text())
    for area in ("nc", "ga", "fl"):
        research = json.loads((ROOT / "research" / area / "sources.json").read_text())
        assert [r for r in checklist if r["area"] == area] == [{**G.scrub_row(r), "area": area} for r in research]
