"""North Carolina's private sewer utilities, covered like any other operator: the permittee of every collection-system
permit DWR's overflow layers name with no public owner (research/nc/private-utilities.json, from DWR's permit
records), the registry rows scripts/add_nc_operators.py makes from it, and the DWR ingester's join of the reports to
those rows by permit. A permittee who is an individual is never named; a report with no permit gets a stated reason,
never an operator. Run from pipeline/: python -m pytest tests/test_nc_private_utilities.py -q
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from common import DATA_DIR, ROOT
from ingest import nc_dwr_sso as S

_spec = importlib.util.spec_from_file_location("add_nc_operators", ROOT / "scripts" / "add_nc_operators.py")
OPS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OPS)

FETCHED = "2026-11-04T03:00:00Z"
PRIVATE = json.loads((ROOT / "research" / "nc" / "private-utilities.json").read_text())
UNRESOLVED = json.loads((ROOT / "research" / "nc" / "private-utilities-unresolved.json").read_text())
REGISTRY = json.loads((DATA_DIR / "dischargers.json").read_text())
PERSON = "Quill, Pat Q."                                   # an invented individual owner: never reaches anything


def hist_row(oid, permit, owner, facility, inc):
    return {"OBJECTID": oid, "report_date": 1700000000000, "start_date": 1699990000000, "end_date": 1699990000000,
            "permit_id": permit, "facility_name": facility, "facility_owner": owner, "incident_number": inc,
            "county": "Wake", "volume": 2000, "volume_reach_water": 1500, "waterbody_impacted": "Example Creek"}


def cur_row(gid, permit_with_name, inc):
    return {"objectid": 1, "globalid": gid, "deq_program": "Sanitary Sewer Overflow", "dwr_incident_number": inc,
            "dwr_permit_with_name": permit_with_name, "deq_county": "Wake", "dwr_report_date": 1780000000000,
            "dwr_start_date": 1779990000000, "dwr_ongoing": "No", "dwr_reached_water": "Yes",
            "dwr_waterbody": "Example Creek - 27-1"}


# ---------------------------------------------------------------- the ingester joins reports by permit

def test_a_company_owned_permit_on_the_history_layer_joins_the_private_operator_row():
    recs, _ = S.build_history([hist_row(1, "WQCS00147", "Aqua North Carolina Inc", "Neuse Colony Collection System",
                                        "202400001")], FETCHED, [], S.permit_index())
    r = recs[0]
    assert r["discharger_id"] == "nc-aqua-north-carolina" and r["npdes_permit"] == "WQCS00147"
    assert r["raw"]["_owner_kind"] == "private or not stated" and "_owner_public" not in r["raw"]
    assert "_discharger_basis" not in r["raw"]


def test_a_permit_seen_only_on_the_2026_layer_joins_by_permit():
    recs, stats = S.build([("layer", cur_row("{AAAAAAAA-0000-4000-8000-0000000000AA}",
                                             "WQCS00380 - Hawthorne Collection System", "202600999"))],
                          FETCHED, [], S.permit_index())
    assert recs[0]["discharger_id"] == "nc-aqua-north-carolina" and stats["with_operator_row"] == 1
    assert "_discharger_basis" not in recs[0]["raw"]


def test_a_report_with_no_permit_gets_a_stated_reason_and_never_an_operator():
    permits = S.permit_index()
    cur, _ = S.build([("layer", cur_row("{AAAAAAAA-0000-4000-8000-0000000000AB}", None, "202600998"))], FETCHED, [],
                     permits)
    hist, _ = S.build_history([hist_row(2, None, "Aqua North Carolina Inc", "Example Crossing Collection System",
                                        "202500002"),
                               hist_row(3, None, PERSON, "Example Community Action, Inc.", "202500003")],
                              FETCHED, [], permits)
    for r in cur + hist:
        assert r["discharger_id"] is None and r["npdes_permit"] is None
        assert r["raw"]["_discharger_basis"] == S.NO_PERMIT and "never inferred" in S.NO_PERMIT
    assert PERSON not in json.dumps(hist)


def test_a_permit_with_no_row_says_so():
    recs, _ = S.build_history([hist_row(4, "WQCSD9999", None, "Example Acres Collection System", "202500004")],
                              FETCHED, [], S.permit_index())
    assert recs[0]["discharger_id"] is None
    assert recs[0]["raw"]["_discharger_basis"] == "No operator on record for permit WQCSD9999 yet."


# ---------------------------------------------------------------- the research file and the registry

def test_every_researched_permit_is_held_by_exactly_one_north_carolina_row():
    held = S.permit_index(REGISTRY)
    entries = PRIVATE["collection_permits"] + PRIVATE["plant_permits"]
    assert len(PRIVATE["collection_permits"]) == 38
    for e in entries:
        assert e["permit"] in held, e["permit"]
        assert e["legal_form"] in OPS.LEGAL_FORMS
        assert re.match(r"^https://(edocs\.deq\.nc\.gov/WaterResources/DocView\.aspx\?id=\d+|echo\.epa\.gov/)",
                        e["source"]["url"])
    rows = {r["id"]: r for r in REGISTRY}
    aqua = rows["nc-aqua-north-carolina"]
    assert aqua["legal_form"] == "private utility" and len(aqua["npdes_permits"]) == 10
    assert aqua["notification_channel"] == OPS.LAW and "G.S. 143-215.1C" in aqua["notes"]
    assert rows["nc-pcs-phosphate-company"]["notification_channel"] == OPS.LAW_C        # industrial: (c)
    assert "WQCSD0135" in rows["nc-henderson-county"]["npdes_permits"]                    # a public owner's row grew


def test_a_permittee_who_is_an_individual_is_never_named():
    # WQCSD0172: DWR's Owner field names the district's chairman, a person; the permittee is the district
    e = next(e for e in PRIVATE["collection_permits"] if e["permit"] == "WQCSD0172")
    assert e["permittee_as_recorded"] is None and e["legal_form"] == "special district"
    row = next(r for r in REGISTRY if "WQCSD0172" in r["npdes_permits"])
    assert row["name"] == e["facility"] == e["operator"]
    # every row made from the research names a body: a company, an association, a club, a district, a public body
    org = re.compile(r"\b(Inc|LLC|Ltd|Company|Corporation|Association|Club|Communities|County|Town|District|"
                     r"Utilities|Service)\b")
    made = [r for r in REGISTRY if r["state"] == "NC" and r.get("legal_form") in OPS.LEGAL_FORMS]
    assert len(made) == 23
    assert [r["name"] for r in made if not org.search(r["name"])] == []
    assert [e["operator"] for e in PRIVATE["collection_permits"] + PRIVATE["plant_permits"]
            if not org.search(e["operator"])] == []
    for doc in (PRIVATE, UNRESOLVED):
        assert "individual" in json.dumps(doc)                 # said so, without the name


def test_a_researched_operator_is_public_or_private_as_its_name_reads():
    """A public body (a town, a county, a county water and sewer district) is never filed as privately owned, and
    no company is filed as public: the legal_form agrees with the ingester's own reading of the name."""
    for e in PRIVATE["collection_permits"] + PRIVATE["plant_permits"]:
        public = e["legal_form"] in OPS.PUBLIC_FORMS
        assert (S.owner_kind(e["operator"])[0] == "public") == public, (e["permit"], e["legal_form"])
    rows = {r["id"]: r for r in REGISTRY}
    for r in rows.values():
        if r["state"] == "NC" and r.get("legal_form") in OPS.PUBLIC_FORMS:
            assert "Privately owned" not in r["notes"], r["id"]
    district = rows["nc-greene-county-water-and-sewer-district-i"]
    assert district["legal_form"] == "special district" and "chairman" in district["notes"]


def test_the_unresolved_file_lists_every_report_without_a_permit_with_its_reason():
    u = UNRESOLVED["reports_without_permit"]
    assert UNRESOLVED["permits"] == [] and len(u) == UNRESOLVED["meta"]["counts"]["reports_without_permit"] == 19
    assert all(x["reason"].startswith("DWR's record gives no permit number") for x in u)
    assert all(x["owner_on_layer"] is None for x in u if x["owner_kind"].startswith("an individual"))


def test_every_operator_private_or_industrial_has_its_own_notice_rows():
    """G.S. 143-215.1C binds every owner or operator: a press-release and a newspaper row per operator
    (scripts/add_register_rows.py, part nc-notice), (c) for an industrial system; the statewide rows they replaced
    are gone."""
    reg = json.loads((DATA_DIR / "notice-channels.json").read_text())["channels"]
    rows = {r["id"]: r for r in reg}
    assert "nc-operator-press-release" not in rows and "nc-operator-newspaper-notice" not in rows
    for op in REGISTRY:
        if op["state"] != "NC":
            continue
        sub = "c" if "G.S. 143-215.1C(c)" in op["notification_channel"] else "b"
        press, paper = rows[f"{op['id']}-press-release"], rows[f"{op['id']}-newspaper-notice"]
        assert press["operator_id"] == paper["operator_id"] == op["id"]
        assert press["legal_basis"].startswith(f"G.S. 143-215.1C({sub})(1)")
        assert paper["legal_basis"].startswith(f"G.S. 143-215.1C({sub})(2)")
        assert press["barrier"] == paper["barrier"] == "print_only"
    # (c)(2) has its own caption: an industrial system's notice is not captioned "... UNTREATED SEWAGE"
    assert '"NOTICE OF DISCHARGE OF UNTREATED WASTE"' in rows["nc-pcs-phosphate-company-newspaper-notice"]["legal_basis"]
    assert '"NOTICE OF DISCHARGE OF UNTREATED SEWAGE"' in rows["nc-aqua-north-carolina-newspaper-notice"]["legal_basis"]


# ---------------------------------------------------------------- scripts/add_nc_operators.py

def _setup(tmp_path, monkeypatch):
    dis = [{"id": "nc-henderson-county", "name": "Henderson County", "state": "NC", "kind": "plant",
            "npdes_permit": "NC0000001", "npdes_permits": ["NC0000001"], "towns": ["Etowah"], "notes": "x",
            "outfall_count": 1, "outfalls_source": "s", "aliases": ["nc-henderson-county"]},
           {"id": "ga-example", "name": "Example", "state": "GA", "npdes_permits": ["GA0000001"]}]
    events = {"records": [
        {"npdes_permit": "WQCS00147", "discharger_name": "Neuse Colony Collection System", "waterbody_text": "Mill Creek",
         "raw": {"_owner_kind": "private or not stated", "reached_water": True}},
        {"npdes_permit": "WQCS00380", "discharger_name": "Hawthorne Collection System", "waterbody_text": "Private pond",
         "raw": {"reached_water": True}},
        {"npdes_permit": "WQCSD0172", "discharger_name": "Example District I", "raw": {}},
        {"npdes_permit": "WQCSD0135", "discharger_name": "Example Sewer Company WWTP", "raw": {}},
        {"npdes_permit": None, "discharger_name": "No Permit Apartments", "raw": {}},
        {"npdes_permit": "WQCSD0998", "discharger_name": "Unknown Acres Collection System", "raw": {}}]}
    def ent(permit, op, form, **kw):
        return {"permit": permit, "operator": op, "legal_form": form, "facility": kw.get("facility", op),
                "county": "Wake", "towns": kw.get("towns", ["Raleigh"]),
                "permittee_as_recorded": kw.get("rec", op),
                "source": {"document": f"{permit}_Permit", "document_date": "1/1/2026",
                           "url": f"https://edocs.deq.nc.gov/WaterResources/DocView.aspx?id=1&dbid=0&repo=WaterResources"},
                **({"permittee_note": kw["note"]} if "note" in kw else {})}
    priv = {"collection_permits": [ent("WQCS00147", "Aqua North Carolina Inc", "private utility"),
                                   ent("WQCS00380", "Aqua North Carolina Inc", "private utility", towns=["Wake Forest"]),
                                   ent("WQCSD0172", "Example District I", "facility (permittee not named)", rec=None,
                                       note="The permit record names an individual as owner; not reproduced."),
                                   ent("WQCSD0135", "Henderson County", "county")],
            "plant_permits": [ent("NC0000002", "Example Catering LLC", "private company", towns=["Pantego"])]}
    plants = {"outfalls": [
        {"state": "NC", "npdes_permit": "NC0000002", "permit_name": "Example Catering LLC", "permittee": "EXAMPLE WWTP",
         "city": "PANTEGO", "receiving_water_echo": "Pantego Creek", "plant_basis": "potw_component",
         "facility_type": "Privately Owned Facility"},
        {"state": "NC", "npdes_permit": "NC0000003", "permit_name": "Henderson County", "permittee": "EXAMPLE CENTER",
         "city": "ETOWAH", "plant_basis": "potw_component", "facility_type": "NON-POTW"},
        {"state": "NC", "npdes_permit": "NC0000004", "permit_name": "Other Example LLC", "permittee": "OTHER WWTP",
         "plant_basis": "potw_component", "facility_type": "Privately Owned Facility"}]}
    paths = {"DIS": tmp_path / "dischargers.json", "RESEARCH": tmp_path / "research.json",
             "PRIVATE": tmp_path / "private.json", "PLANTS": tmp_path / "plants.json"}
    paths["DIS"].write_text(json.dumps(dis, indent=1) + "\n")
    paths["RESEARCH"].write_text("[]")
    paths["PRIVATE"].write_text(json.dumps(priv))
    paths["PLANTS"].write_text(json.dumps(plants))
    (tmp_path / "events.json").write_text(json.dumps(events))
    for k, v in paths.items():
        monkeypatch.setattr(OPS, k, v)
    monkeypatch.setattr(OPS, "EVENTS", [tmp_path / "events.json"])
    return paths


def test_the_script_makes_one_row_per_private_operator_grows_a_public_row_and_keeps_the_state_together(
        tmp_path, monkeypatch, capsys):
    paths = _setup(tmp_path, monkeypatch)
    assert OPS.main([]) == 0
    out = json.loads(paths["DIS"].read_text())
    assert [r["state"] for r in out][-1] == "GA"                      # new rows go in after the last NC row
    rows = {r["id"]: r for r in out}
    aqua = rows["nc-aqua-north-carolina"]
    assert aqua["npdes_permits"] == ["WQCS00147", "WQCS00380"] and aqua["legal_form"] == "private utility"
    assert aqua["kind"] == "sso" and aqua["towns"] == ["Raleigh", "Wake Forest"]
    assert aqua["receiving_waters"] == ["Mill Creek"]                 # "Private pond" names no water
    assert "WQCS00147" in aqua["permit_note"] and "edocs.deq.nc.gov" in aqua["permit_note"]
    greene = rows["nc-example-district-i"]
    assert greene["legal_form"] == "facility (permittee not named)" and "individual" in greene["notes"]
    hc = rows["nc-henderson-county"]
    assert hc["npdes_permits"] == ["NC0000001", "WQCSD0135", "NC0000003"] and hc["outfall_count"] == 2
    cat = rows["nc-example-catering"]
    assert cat["kind"] == "plant" and cat["legal_form"] == "private company" and cat["towns"] == ["Pantego"]
    assert not any("NC0000004" in r.get("npdes_permits", []) for r in out)   # private, not researched: skipped
    assert not any("WQCSD0998" in r.get("npdes_permits", []) for r in out)   # no owner on record: no row
    assert "No Permit" not in paths["DIS"].read_text()
    # idempotent
    before = paths["DIS"].read_text()
    assert OPS.main([]) == 0 and paths["DIS"].read_text() == before


def test_the_script_refuses_a_legal_form_outside_the_list(tmp_path, monkeypatch):
    paths = _setup(tmp_path, monkeypatch)
    d = json.loads(paths["PRIVATE"].read_text())
    d["collection_permits"][0]["legal_form"] = "person"
    paths["PRIVATE"].write_text(json.dumps(d))
    with pytest.raises(ValueError, match="legal_form"):
        OPS.main([])
