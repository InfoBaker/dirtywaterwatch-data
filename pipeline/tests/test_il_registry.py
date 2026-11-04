"""Illinois registry: MWRD's outfall points against EPA's inventory (scripts/add_il_mwrd_outfalls.py), the operator rows
(scripts/add_il_operators.py) and the register rows (scripts/add_il_register_rows.py). Street names are placeholders."""
import importlib.util
import json
import sys
from pathlib import Path

import common
from ingest import il_mwrd as M

ROOT = Path(__file__).resolve().parents[2]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _feat(oid, owner, loc, lat, lon, tarp="DS-X1", reach="NSC Lower (NSWRP)"):
    return {"attributes": {"OBJECTID": oid, "OWNER": owner, "OUTFALL_CITY": owner, "WATERWAY_REACH": reach,
                           "TARP_CONNECTION": tarp, "LOCATION": loc, "M_OR_U": "Monitored"},
            "geometry": {"x": lon, "y": lat}}


def _epa(permit, outfall, name, lat, lon):
    return {"npdes_permit": permit, "outfall": outfall, "outfall_name": name, "lat": lat, "lon": lon,
            "permittee": "SAMPLE CSO, CITY OF", "receiving_water_echo": "NORTH SHORE CHANNEL"}


def test_reach_labels_and_reversal_structures():
    assert M.reach_water("NSC Lower (NSWRP)") == "North Shore Channel"
    assert M.reach_water("Little Cal R (South)") == "Little Calumet River"
    assert M.reach_water("Cal Sag Ch") == "Calumet Sag Channel"
    assert M.reach_water("I & M Canal") == "Illinois and Michigan Canal"
    assert M.reach_water("Nowhere Cr") is None
    assert M.diversion("OBrien Lock and Dam")[0] == "O'Brien Lock"
    assert M.diversion("Chicago River Controlling Works")[0] == "CRCW"
    assert M.diversion("Wilmette Gate")[0] == "Wilmette" and M.diversion("Sample Ave (E)") is None
    assert M.owner_permits("Chicago / Calumet Park") == ["IL0045012"] and M.owner_permits("Mt. Prospect") == ["IL0052400"]
    assert M.owner_permits("Sample Campground") == []


def test_points_pair_with_epa_rows_by_distance_then_street_and_side():
    S = _script("add_il_mwrd_outfalls")
    feats = [_feat(1, "Chicago", "Sample Ave (E)", 42.0000, -87.7000),
             _feat(2, "Chicago", "Example St (W)", 42.0300, -87.7300, tarp="DS-X2"),
             _feat(3, "Chicago", "Other Ave (W)", 42.0500, -87.7500, tarp="DS-X3"),
             _feat(4, "Chicago", "Third Ave (N)", 42.0600, -87.7600, tarp="DS-X4"),
             _feat(5, "Chicago", "Third Ave (S)", 42.0610, -87.7610, tarp="DS-X4"),
             _feat(6, "Chicago River Controlling Works", "Chicago River Controlling Works", 41.88, -87.60,
                   tarp="Chicago River Controlling Works", reach="Chicago R"),
             _feat(7, "Sample Campground", "Sample Rd (E)", 42.03, -87.87)]
    epa = [_epa("IL0045012", "001", "CSO - SAMPLE AVENUE EAST", 42.0001, -87.7001),      # 15 m away
           _epa("IL0045012", "002", "CSO - EXAMPLE STREET WEST", 41.90, -87.65),          # the facility's point
           _epa("IL0045012", "003", "CSO - OTHER AVENUE EAST", 41.90, -87.65)]            # the other bank
    doc = S.build(feats, epa)
    by = {r["source_record_id"]: r for r in doc["outfalls"]}
    assert by[1]["outfall"] == "001" and by[1]["epa_row"]["paired_by"].startswith("distance")
    assert by[2]["outfall"] == "002" and "street and side" in by[2]["epa_row"]["paired_by"]
    assert by[3]["epa_row"] is None and by[3]["outfall"] == "DS-X3"                      # sides differ: not paired
    assert {by[4]["outfall"], by[5]["outfall"]} == {"DS-X4#4", "DS-X4#5"}                 # one drop shaft, two outfalls
    assert by[3]["receiving_water_echo"] == "North Shore Channel" and by[1]["receiving_water_echo"] == "North Shore Channel"
    assert by[1]["epa_row"]["receiving_water_echo"] == "NORTH SHORE CHANNEL"         # EPA's text kept with its row
    assert 6 not in by and doc["diversion_points"][0]["water"] == "Lake Michigan"
    assert 7 not in by and doc["without_permit"][0]["owner"] == "Sample Campground"


def test_the_illinois_outfall_file_outranks_epas_rows_for_the_same_outfall():
    doc = json.loads((ROOT / "data" / "outfalls-il.json").read_text())
    keys = [common.outfall_key(r["npdes_permit"], r["outfall"]) for r in doc["outfalls"]]
    assert len(keys) == len(set(keys)) and doc["count"] == len(keys) > 400
    reg = {common.outfall_key(r["npdes_permit"], r["outfall"]): r for r in common.load_outfall_registry(provisional=False)
           if r.get("state") == "IL"}
    paired = [r for r in doc["outfalls"] if r["epa_row"]]
    assert paired and all(reg[common.outfall_key(r["npdes_permit"], r["outfall"])]["_file"] == "data/outfalls-il.json"
                          for r in paired)
    assert all(r["coords_from"] == "il-mwrd-cso-points" and r["source_url"].startswith(M.CSO_POINTS_URL)
               for r in doc["outfalls"])


def _il_rows():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "IL"]


def test_operator_names_read_as_bodies_and_epa_descriptions_are_replaced():
    S = _script("add_il_operators")
    assert S.display("OREGON STP, CITY OF") == "City of Oregon (Oregon STP)"
    assert S.display("ELMHURST, CITY OF") == "City of Elmhurst"
    assert S.display("AVISTON. VILLAGE OF") == "Village of Aviston"
    assert S.facility_part("City of Alton (Alton STP)", "Illinois American Water") == "Alton STP"
    assert S.form("SAMPLE SANITARY DISTRICT") == "special district" and S.form("EJ WATER COOPERATIVE") == "member-owned utility"
    by = {r["npdes_permit"]: r for r in _il_rows()}
    assert by["IL0039551"]["name"] == "Village of Lemont" and by["IL0039551"]["legal_form"] == "town"   # 'COMBINED SEWER OVERFLOW'
    assert by["IL0045012"]["kind"] == "cso" and "40 CFR 122.38" in by["IL0045012"]["notification_channel"]
    assert by["IL0045012"]["notification_signup_url"].startswith("https://www.smart911.com/")
    assert "40 CFR 122.38" not in by["IL0034495"]["notification_channel"]                              # Pekin: downstate


def test_operator_rows_hold_each_permit_once_and_name_no_individual():
    from build import redact
    import string
    rows = _il_rows()
    perms = [p for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) for p in r.get("npdes_permits") or []
             if p.startswith("IL")]
    assert len(perms) == len(set(perms))
    assert len({r["id"] for r in rows}) == len(rows) > 800
    for r in rows:
        for f in ("name", "short_name", "notes"):
            v = r.get(f) or ""
            assert not (redact.person_shaped(v) or redact.person_shaped(string.capwords(v))), (r["id"], v)
    forms = {r["legal_form"] for r in rows} - {None}
    from ingest.dischargers_schema import LEGAL_FORMS
    assert forms <= set(LEGAL_FORMS)
    research = json.loads((ROOT / "research" / "il" / "dischargers.json").read_text())
    ids = {a for r in rows for a in r["aliases"]}
    assert all(r["id"] in ids for r in research)          # EPA's overflow module names the research ids
    named = [r for r in rows if r["legal_form"] == "facility (permittee not named)"]
    assert len(named) == 2 and all("not named" in r["notes"] for r in named)


def test_a_companys_plants_are_one_row():
    rows = _il_rows()
    iaw = [r for r in rows if r["id"] == "il-american-water"][0]
    assert iaw["legal_form"] == "investor-owned utility" and len(iaw["npdes_permits"]) > 20
    assert "IL0021202" in iaw["npdes_permits"] and "private permittee" in iaw["notification_channel"]
    assert sum(1 for r in rows if r["id"].startswith("il-prairie-path")) == 1


def test_register_rows_cover_every_cso_permittee_with_its_duties():
    from ingest import notification_pages as NP
    rows = json.loads((ROOT / "data" / "notice-channels" / "il.json").read_text())["channels"]
    assert not NP.validate_register({"schema_version": 1, "channels": rows},
                                    json.loads((ROOT / "data" / "dischargers.json").read_text()), ROOT)
    ops = _il_rows()
    named = {r["operator_id"] for r in rows if r["operator_id"]}
    assert all(o["id"] in named for o in ops if o["kind"] == "cso")                # the checklist's CSO one-liner
    by = {r["id"]: r for r in rows}
    chi = next(o for o in ops if o["npdes_permit"] == "IL0045012")["id"]
    for suffix, bar in (("cso-public-notification", "no_web_page"), ("cso-signs", "signs_only"),
                        ("health-department-notice", "no_web_page")):
        assert by[f"{chi}-{suffix}"]["barrier"] == bar and by[f"{chi}-{suffix}"]["basis_kind"] in ("law", "permit")
    # every duty of 40 CFR 122.38 by its own paragraph (review 2026-11-04: signs are (a)(1), the health department
    # (a)(2), the public (a)(3) with the 7-day update, the annual notice (b), which had no row)
    gl = [o["id"] for o in ops if o["kind"] == "cso" and "40 CFR 122.38" in (o.get("notification_channel") or "")]
    assert len(gl) == 43
    for oid in gl:
        assert by[f"{oid}-cso-signs"]["legal_basis"].startswith("40 CFR 122.38(a)(1):")
        assert by[f"{oid}-health-department-notice"]["legal_basis"].startswith("40 CFR 122.38(a)(2)(i):")
        assert "122.38(a)(3)(iii)" in by[f"{oid}-cso-public-notification"]["legal_basis"]
        ann = by[f"{oid}-cso-annual-notice"]
        assert ann["legal_basis"].startswith("40 CFR 122.38(b):") and ann["basis_kind"] == "law"
        assert ann["barrier"] == "not_verified" and ann["publishes"] == "documents"
    pekin = next(o for o in ops if o["npdes_permit"] == "IL0034495")["id"]
    assert by[f"{pekin}-cso-public-notification"]["barrier"] == "not_verified" and f"{pekin}-cso-signs" not in by
    syn = by["il-mwrd-cso-synopsis-report"]
    assert syn["barrier"] == "bot_wall" and "request to MWRD" in syn["note"] and syn["urls"] == []
    assert by["il-mwrd-possible-cso-events-map"]["feed_source_id"] == "il-mwrd-possible-cso-events-layer"
    assert by["il-iepa-sso-report"]["barrier"] == "no_web_page" and "public or private" in by["il-iepa-sso-report"]["note"]
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)


def test_register_script_is_reproducible():
    S = _script("add_il_register_rows")
    rep = S.run(dry_run=True)
    assert rep["rows"] == len(json.loads((ROOT / "data" / "notice-channels" / "il.json").read_text())["channels"])


def test_the_lake_cut_downloads_check_the_tiger_files(monkeypatch):
    from ingest import waters_extra as WX
    S = _script("cut_lakes_to_state_waters")
    seen = {}
    monkeypatch.setattr(WX, "states_zip", lambda **kw: seen.update(kw) or kw["dest"])   # the members go as a parameter
    before = WX.STATES_ZIP_MEMBERS
    S.tiger_zip()
    assert tuple(seen["members"]) == ("tl_2023_us_state.shp", "tl_2023_us_state.dbf") and seen["url"] == S.TIGER_URL
    assert WX.STATES_ZIP_MEMBERS == before                      # the shared default is never swapped


def test_lake_michigan_holds_illinois_waters_only():
    w = json.loads((ROOT / "data" / "waters-nhd.json").read_text())
    lake = next(r for r in w["waters"] if r["slug"] == "lake-michigan-il")
    assert lake["bbox"][2] < -87.0 and lake["bbox"][3] < 42.6 and lake["area_km2"] < 5000
    assert not [p for p in w.get("problems", []) if str(p).startswith("lake-michigan-il")]
