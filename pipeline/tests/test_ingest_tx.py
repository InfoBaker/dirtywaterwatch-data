"""Texas: TCEQ's Sanitary Sewer Overflows table and Texas Beach Watch through the generic readers (ingest/tx_transforms.py),
the Socrata if_changed gate and the strict free-text scrub, the named-water-only placement, the permit crosswalk, the
operator and register rows, the rules row, the state text and the missing-waters list."""
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from build import provisional_outfalls as P
from ingest import dischargers_schema as DS
from ingest.generic import fieldmap as F
from ingest.generic import runner as R
from ingest.generic import socrata

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-07T13:00:00Z"
PERSONAL = ["Fixturename", "Jane", "1234 Sample", "4321 Fixture", "4321", "555-0142", "512-555", "jfixture",
            "example.com", "CN600000001", "Caller", "limed"]


def tceq(prev=()):
    _, block = R.load_source("tx-tceq-sso-opendata")
    rows = socrata.parse(block, (FIX / "tx_tceq_sso.json").read_bytes())
    meta = json.loads((FIX / "tx_tceq_sso_meta.json").read_text())
    recs, stats = R.build("tx-tceq-sso-opendata", block, rows, FETCHED, prev, meta)
    return {r["source_record_id"]: r for r in recs}, stats


def beach():
    _, block = R.load_source("tx-glo-beach-watch")
    rows = R.platform("arcgis").parse(block, (FIX / "tx_beach_watch.json").read_bytes())
    recs, stats = R.build("tx-glo-beach-watch", block, rows, FETCHED, (), None)
    return recs, stats


def test_blocks_validate():
    for sid in ("tx-tceq-sso-opendata", "tx-glo-beach-watch"):
        _, block = R.load_source(sid)
        assert R.validate_block(block, sid) == []


def test_every_row_is_a_record_with_dates_only_and_the_tables_own_ids():
    recs, stats = tceq()
    assert stats["rows"] == 10 and stats["records_written"] == 10
    assert "900002~2" in recs and recs["900002~2"]["duplicate_of"] == recs["900002"]["event_id"]
    r = recs["900002"]
    assert r["event_type"] == "sso" and r["status"] == "ended" and r["time_precision"] == "day"
    assert r["started_at"].startswith("2025-06-14") and r["ended_at"].startswith("2025-06-15")
    assert r["reported_at"].startswith("2025-06-17") and r["published_at"] is None
    assert r["source_updated_at"].startswith("2026-09-24")
    assert r["volume_gal"] == 95370 and r["source_url"].endswith("incident_number=900002")
    assert r["raw"]["_cause"] == "LINE BLOCKAGE (NON-GREASE)" and r["raw"]["county"] == "Bexar County"
    assert recs["900003"]["status"] == "unknown" and recs["900003"]["ended_at"] is None      # no end given
    # an end in the year 3000 is not an end
    assert recs["900007"]["status"] == "unknown" and "after the fetch" in recs["900007"]["parse_error"]


def test_the_zone_follows_the_county():
    recs, _ = tceq()
    assert recs["900003"]["raw"]["timezone"] == "America/Denver"          # El Paso County: Mountain time
    assert recs["900003"]["raw"]["timezone_note"].startswith("Mountain time (El Paso County")
    assert recs["900001"]["raw"]["timezone"] == "America/Chicago"
    from ingest import tx_transforms as T
    assert T.zone_of("HUDSPETH") == "America/Denver" and T.zone_of("CULBERSON") == "America/Chicago"


def test_receiving_water_text_named_kept_or_cleared():
    recs, _ = tceq()
    assert recs["900002"]["waterbody_text"] == "SAN ANTONIO RIVER"
    for sid, given in (("900001", "Not Provided"), ("900007", "NO WATER BODY PROVIDED"), ("900008", "N/A")):
        assert recs[sid]["waterbody_text"] is None and recs[sid]["raw"]["_water_text_as_given"] == given
    seg = recs["900004"]
    assert seg["waterbody_text"] is None and seg["raw"]["_tceq_segment"] == "0613"
    assert "segment number" in seg["raw"]["_water_text_why"]
    assert recs["900005"]["waterbody_text"] == "CONTAINED ON SITE"            # the status build reads it as no water


def test_named_water_only_never_geolocated_nor_put_at_the_plant():
    recs, _ = tceq()
    evs = list(recs.values())
    assert all(r["raw"]["_placement"] == "named_water_only" and r["lat"] is None for r in evs)
    places, drops, unlocated = P.build_places(evs, outlines={})
    assert places == [] and unlocated == []
    assert drops["placed by its named water only (the source's placement rule): not geolocated"] == \
        sum(1 for r in evs if not r.get("duplicate_of") and r.get("discharger_id"))


def test_operator_and_federal_permit():
    recs, _ = tceq()
    h = recs["900001"]
    assert h["discharger_id"] == "tx-city-of-houston" and h["discharger_name"] == "City of Houston"
    assert h["npdes_permit"] == "TX0096172" and "regulated entity" in h["raw"]["_permit_basis"]
    assert h["raw"]["state_permits"] == ["WQ0010495090"] and h["raw"]["row"]["regulated_entity_name"] == "PWE WWTP 69TH STREET"
    assert recs["900003"]["npdes_permit"] == "TX0026751"                   # the row's own federal id
    assert recs["900002"]["discharger_id"] == "tx-san-antonio-water-system"


def test_volume_units_and_materials():
    recs, _ = tceq()
    assert recs["900007"]["volume_gal"] is None and recs["900007"]["raw"]["_volume_unit"] == "POUNDS"
    assert recs["900007"]["volume_text"] == "4 pounds"
    assert recs["900008"]["event_type"] == "unknown" and recs["900008"]["raw"]["_source_type"] == "Rock"


def test_no_personal_field_or_string_reaches_the_records():
    recs, _ = tceq()
    text = json.dumps(list(recs.values()))
    for s in PERSONAL:
        assert s not in text, s
    r = recs["900006"]["raw"]["row"]
    assert not {"customer_number", "incident_comment", "incident_action"} & set(r)
    assert "[house number removed]" in r["incident_description"] and "[phone removed]" in r["incident_description"]
    assert "[email removed]" in r["incident_description"] and "[name removed]" in r["incident_description"]
    assert "[house number removed] FIXTURE DRIVE" in r["receiving_water_body"]
    assert "[house number removed] Fixture Drive" in recs["900006"]["outfall_name"]
    # an entity filed under a person's name: gone from discharger_name and from raw.row
    p = recs["900009"]
    assert p["discharger_name"] == "[name removed]" and p["raw"]["row"]["regulated_entity_name"] == "[name removed]"


def test_the_strict_scrub_is_only_where_a_block_asks_for_it():
    row = {"a": "Backup at 1234 Sample Lane"}
    assert F.safe_row(row, {"safe_fields": ["a"], "free_text": ["a"]})[0]["a"] == "Backup at 1234 Sample Lane"
    assert "[house number removed]" in F.safe_row(row, {"safe_fields": ["a"], "free_text": ["a"],
                                                         "free_text_scrub": "strict"})[0]["a"]
    assert F.validate({"platform": "socrata", "safe_fields": ["a"], "free_text_scrub": "loose", "record": {}})


def test_if_changed_keeps_the_last_read_while_the_table_is_unchanged(tmp_path, monkeypatch):
    recs, _ = tceq()
    path = tmp_path / "tx.json"
    path.write_text(json.dumps({"ok": True, "records": list(recs.values()),
                                "meta": {"table_version": "1790274119", "rows": 10}}))
    _, block = R.load_source("tx-tceq-sso-opendata")
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1790274119")
    line = R.keep_unchanged("tx-tceq-sso-opendata", block, path, "2026-11-07T14:00:00Z")
    doc = json.loads(path.read_text())
    assert "unchanged" in line and doc["ok"] and doc["count"] == 10 and doc["meta"]["checked_at"] == "2026-11-07T14:00:00Z"
    assert all(r["fetched_at"] == FETCHED for r in doc["records"])       # the records' own fetch time stays
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1800000000")
    assert R.keep_unchanged("tx-tceq-sso-opendata", block, path, "2026-11-07T15:00:00Z") is None
    bad = {**block, "metadata": False}
    assert any("if_changed needs metadata" in e for e in R.validate_block(bad, "x"))


def test_beach_watch_levels():
    recs, stats = beach()
    assert stats["rows"] == 3 and len(recs) == 2                          # Low is not a record
    hi = next(r for r in recs if r["raw"]["_level"] == "High")
    med = next(r for r in recs if r["raw"]["_level"] == "Medium")
    assert hi["event_type"] == "beach_advisory" and hi["status"] == "advisory_active" and "advisory recommended" in hi["advice_text"]
    assert med["event_type"] == "beach_advisory" and med["status"] == "unknown" and med["raw"]["_agency_label_only"]
    assert hi["source_record_id"] == "GAL999-20261027" and hi["time_precision"] == "day" and hi["lat"] is not None
    assert hi["waterbody_text"] is None and hi["raw"]["_last_seen_in_source"] == FETCHED


# ---------------------------------------------------------------- registry, register, rules, text, waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "TX"]


def test_every_texas_permit_and_entity_is_in_exactly_one_row():
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "TX" and r["npdes_permit"].startswith("TX")}
    assert len(plants) > 1800 and all(every[p] == 1 for p in plants)
    ents = Counter(rn for r in ops() for rn in r.get("tceq_entities") or [])
    assert len(ents) == 2117 and set(ents.values()) == {1}
    houston = next(r for r in ops() if r["id"] == "tx-city-of-houston")
    assert "tx-houston" in houston["aliases"] and "RN100217603" in houston["tceq_entities"]
    assert {"RN101612463", "RN101611739"} <= set(houston["tceq_entities"])   # by Houston's WQ base number


def test_legal_forms_are_controlled_and_no_individual_is_named():
    rows = ops()
    assert not DS.check_legal_forms(rows)
    assert all(r["legal_form"] in DS.LEGAL_FORMS or r["legal_form"] is None for r in rows)
    from build import redact
    assert not [r["name"] for r in rows if redact.person_shaped(r["name"])]
    assert all("Fixturename" not in json.dumps(r) for r in rows)


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "tx.json").read_text())["channels"]}
    for r in ops():
        row = reg[f"{r['id']}-tceq-report"]
        assert row["feed_source_id"] == "tx-tceq-sso-opendata" and row["basis_kind"] == "law"
        assert "305.125(9)" in row["legal_basis"]
    assert reg["tx-local-officials-media-notice"]["urls"] == [] and reg["tx-local-officials-media-notice"]["barrier"] == "no_web_page"
    assert "319.302" in reg["tx-local-officials-media-notice"]["legal_basis"]
    assert reg["tx-glo-beach-watch"]["feed_source_id"] == "tx-glo-beach-watch"
    assert reg["tx-gchd-beach-advisories"]["barrier"] == "bot_wall"


def test_rules_row_cites_the_law_and_sets_no_window():
    tx = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["TX"]
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    assert tx["hours"] is None and "305.125(9)" in tx["source"] and "319.30" in tx["source"]
    assert "El Paso and Hudspeth" in tx["basis"] and "TX" not in rules["live_states"]
    assert not re.search(r"\b(safe|clean)\b", tx["basis"], re.I)


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "tx" / "state-text.md").read_text()
    assert t.startswith("---\nstate: TX\nname: Texas\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "56,545" in t and "Mountain time in El Paso and Hudspeth" in t


def test_missing_waters_list_names_waters_only():
    d = json.loads((ROOT / "research" / "tx" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())["states"]["TX"]["waters"]
    have = {re.sub(r"[^a-z0-9]", "", n.lower()) for w in nat for n in [w["name"], w["key"]]}
    assert d["state"] == "TX" and d["waters"] == len(d["rows"]) > 500
    for r in d["rows"]:
        assert re.sub(r"[^a-z0-9]", "", r["name"].lower()) not in have
        assert not re.search(r"\d", r["name"]) and not re.search(r"\d", " ".join(r["spellings"]))
        assert "removed]" not in json.dumps(r)
    names = {r["name"] for r in d["rows"]}
    assert "Leon Creek" in names and "Unnamed Creek" not in names and "Not Provided" not in names


@pytest.mark.parametrize("text", ["Not Provided", "NOT PROVIDEDD", "NONE LISTED", "None listed in report", "n/a",
                                  "NOT SPECIFIED", "UNKNOWN", "SEGMENT NO. 2501BC", "1218"])
def test_tceqs_no_water_wordings(text):
    from ingest import tx_transforms as T
    assert T.NOT_GIVEN.match(text) or T.SEGMENT_ONLY.match(text)


@pytest.mark.parametrize("text", ["SAN ANTONIO RIVER", "Leon Creek", "Lake Waco", "NONE, GROUND AT A HOUSE"])
def test_names_are_not_cleared(text):
    from ingest import tx_transforms as T
    assert not (T.NOT_GIVEN.match(text) or T.SEGMENT_ONLY.match(text))


@pytest.mark.parametrize("name, person", [
    ("ABCD EDGEWOOD SAMPLESON, PAT", True), ("HOA JORDAN FIXTURE AND ALEX SAMPLETON", True),
    ("PRIYA RAMESH SAMPLEWALA", True), ("HOUSE FIXTURE OWNERS ASSOCIATION INC, LEG FIXTURE LLC, AND PAT SAMPL", True),
    ("THE PAT SAMPLE FAMILY LIMITED PARTNERSHIP", True),
    ("HOUSTON, CITY OF", False), ("AUSTIN,CITY OF", False), ("TEMPLE, CITY OF AND BELTON, CITY OF", False),
    ("ANGELINA AND NECHES RIVER AUTHORITY", False), ("BEARPEN CREEK, LP", False), ("PRAIRIE VIEW A&M UNIVERSITY", False),
    ("HARRIS COUNTY MUD 26", False), ("AQUA TEXAS INC", False), ("JWR-HO, L.P.", False)])
def test_owner_names_of_people_are_told_apart(name, person):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import add_tx_operators as A
    assert A.owner_person(name) is person


def test_the_rows_once_named_for_people_carry_their_facility():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import add_tx_operators as A
    rows = ops()
    want = {"TX0146510": "Overlook WWTF", "TX0135364": "Southgate WWTP", "TX0137804": "Arcola Estates",
            "TX0134546": "House Hahl WWTP", "TX0146129": "Harris Waller Counties MUD No. 11 WWTP"}
    for p, fac in want.items():
        r = next(r for r in rows if p in r["npdes_permits"])
        assert r["name"].startswith(fac) and r["id"].startswith("tx-" + fac.lower().split()[0])
    assert not [r["name"] for r in rows if A.owner_person(r["name"]) and r.get("npdes_permits")
                and not r["name"].startswith("Holder of permit") and r["id"].startswith("tx-") and
                not r["id"].startswith("tx-rn")]
