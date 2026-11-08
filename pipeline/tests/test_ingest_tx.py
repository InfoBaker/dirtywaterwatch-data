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
            "example.com", "CN600000001", "Caller", "limed", "1967", "Lot 108", "Apt #2"]


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
    assert stats["rows"] == 12 and stats["records_written"] == 11 and "900011" not in recs   # 2022: before the cut
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
    assert recs["900003"]["raw"]["time_zone"] == "America/Denver" and recs["900003"]["started_at"] == "2026-07-20T00:00:00-06:00"          # El Paso County: Mountain time
    assert recs["900003"]["raw"]["timezone_note"].startswith("Mountain time (El Paso County")
    assert recs["900001"]["raw"]["time_zone"] == "America/Chicago" and recs["900001"]["started_at"] == "2026-08-03T00:00:00-05:00"
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
    assert "[house number removed] FIXTURE DRIVE" in recs["900006"]["waterbody_text"]
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
                                "meta": {"table_version": "1790274119", "rows": 11}}))
    _, block = R.load_source("tx-tceq-sso-opendata")
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1790274119")
    line = R.keep_unchanged("tx-tceq-sso-opendata", block, path, "2026-11-07T14:00:00Z")
    doc = json.loads(path.read_text())
    assert "unchanged" in line and doc["ok"] and doc["count"] == 11 and doc["meta"]["checked_at"] == "2026-11-07T14:00:00Z"
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
    assert "El Paso and Hudspeth" in tx["basis"] and "TX" in rules["live_states"]   # live since 2026-11-08
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


def check_missing_waters(d: dict, national: dict) -> None:
    """The invariants of research/tx/receiving-waters-missing.json, true both as the state build writes it and after a
    water batch moves the names it resolves into `resolved` (final audit 2026-11-07 P2-4: the names change with each
    batch; these do not)."""
    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in ((national.get("states") or {}).get("TX") or {}).get("waters") or []
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or [])] if n}
    rows, resolved = d["rows"], d.get("resolved") or []
    assert d["state"] == "TX" and d["waters"] == len(rows)
    assert not [r["name"] for r in rows if k(r["name"]) in held]                  # the national list's names left out
    keys = [(r["name"], r["county"]) for r in rows]
    assert len(keys) == len(set(keys))                                           # one row per name and county
    for r in rows + resolved:
        assert not re.search(r"\d", r["name"]) and "removed]" not in json.dumps(r)
        assert r["name"] not in ("Unnamed Creek", "Not Provided", "Colorado")     # generic wording, basin label
    for r in rows:
        assert r["county"] and not re.search(r"\d", " ".join(r.get("spellings") or []))
    # a name several counties share keeps one row or resolved entry per county, never one for all (final audit P1-2)
    seen = set(keys) | {(r["name"], r.get("county")) for r in resolved}
    assert ("Post Oak Creek", "Grayson County") in seen
    for r in resolved:
        if r["name"] == "Canyon Lake System":
            assert "canyon-lake-tx" not in (r.get("slugs") or [])                 # Comal County's lake


def test_missing_waters_list_holds_its_invariants():
    d = json.loads((ROOT / "research" / "tx" / "receiving-waters-missing.json").read_text())
    check_missing_waters(d, json.loads((ROOT / "data" / "receiving-waters-national.json").read_text()))


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


def test_cause_slash_address_and_unit_numbers_are_cut_but_roads_and_segments_stay():
    recs, _ = tceq()
    r = recs["900010"]
    assert r["outfall_name"] == "Line Break/ [house number removed] Sampleton Ave."
    d = r["raw"]["row"]["incident_description"]
    assert "Lot [house number removed]" in d and "Apt [house number removed]" in d and "1967" not in d
    assert "FM 1960" in d and "2202 Arroyo Colorado Above Tidal" in d
    for t, want in (("Grease/ 1967 Columbus Ave", "Grease/ [house number removed] Columbus Ave"),
                    ("1967 Columbus Ave.", "[house number removed] Columbus Ave."),
                    ("Manhole/1209 N Main St", "Manhole/ [house number removed] N Main St"),
                    ("Manhole/ 12345 FM 1960 Rd", "Manhole/ [house number removed] FM 1960 Rd"),
                    ("1007 OF THE SAN JACINTO RIVER BASIN", "1007 OF THE SAN JACINTO RIVER BASIN"),
                    ("2513 Rosebud Ct. into Walnut Creek", "[house number removed] Rosebud Ct. into Walnut Creek"),
                    ("Lift Station #6 on Moore Lane", "Lift Station #6 on Moore Lane")):
        assert F.scrub_strict(t) == want, t


HOUSE = re.compile(r"(?<![\\w.,:#-])\\d{2,6}[A-Za-z]?\\s{1,2}(?:[NSEW]\\.?\\s{1,2})?(?:[A-Za-z][\\w'.-]*\\s{1,2}){1,3}"
                   r"(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|court|ct|circle|cir|boulevard|blvd|trail|trl|"
                   r"parkway|pkwy|cove|cv)\\b", re.I)


def test_no_record_built_from_the_saved_read_keeps_a_house_number_before_a_street_word():
    saved = sorted(p for p in (ROOT / "data" / "raw" / "tx-tceq-sso-opendata").glob("2026*Z.json"))
    if not saved:
        pytest.skip("the saved read is not on this machine (data/raw is not in git)")
    _, block = R.load_source("tx-tceq-sso-opendata")
    rows = socrata.parse(block, saved[-1].read_bytes())
    recs, _ = R.build("tx-tceq-sso-opendata", block, rows, FETCHED, (), None)
    bad = [m.group(0) for r in recs for t in [r.get("outfall_name") or "", r.get("waterbody_text") or "",
                                               *map(str, (r["raw"].get("row") or {}).values())]
           for m in HOUSE.finditer(t)]
    assert not bad, bad[:10]


def test_dates_are_the_countys_midnight_and_a_day_ends_there():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from build import status as S
    recs, _ = tceq()
    ep = recs["900003"]
    assert S.event_zone(ep) == ZoneInfo("America/Denver") and ep["reported_at"] == "2026-07-21T00:00:00-06:00"
    hou = recs["900001"]
    end = S.end_of_local_day(S.parse_time(hou["ended_at"]), S.event_zone(hou))
    assert end == datetime(2026, 8, 4, tzinfo=ZoneInfo("America/Chicago"))


def test_a_basin_name_is_not_a_water():
    recs, _ = tceq()
    r = recs["900010"]
    assert r["waterbody_text"] is None and r["raw"]["_water_text_as_given"] == "COLORADO"
    assert "basin" in r["raw"]["_water_text_why"] and r["raw"]["_tceq_segment"] == "1412"


def test_beach_watch_medium_is_the_sites_72_hour_caution():
    from datetime import UTC, datetime, timedelta
    from build import status as S
    recs, _ = beach()
    med = next(r for r in recs if r["raw"]["_level"] == "Medium")
    ivs = S.event_intervals(med, "TX", datetime(2026, 10, 29, tzinfo=UTC), None, S.load_rules())
    assert len(ivs) == 1 and ivs[0]["rule"] == "sample_caution" and ivs[0]["color"] == "yellow"
    assert ivs[0]["end"] - ivs[0]["start"] == timedelta(hours=72) and ivs[0]["red_rule"] is None


def test_a_read_torn_by_a_refresh_is_read_again_or_refused(monkeypatch):
    _, block = R.load_source("tx-tceq-sso-opendata")
    versions = iter(["1", "2", "2", "2"])                 # moved during the first read, steady during the second
    monkeypatch.setattr(socrata, "current_version", lambda b, s: next(versions))
    reads = []
    monkeypatch.setattr(socrata, "read_pages", lambda b, s, u: (reads.append(1) or ([[{"incident_number": "1"}]], 1)))
    monkeypatch.setattr(socrata, "row_count", lambda b, s, u: 1)
    out = socrata.fetch({**block, "metadata": False}, None)
    assert len(reads) == 2 and b"incident_number" in out.content
    monkeypatch.setattr(socrata, "current_version", lambda b, s, it=iter(range(100)): str(next(it)))
    with pytest.raises(RuntimeError, match="changed during each"):
        socrata.fetch({**block, "metadata": False}, None)
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1")
    monkeypatch.setattr(socrata, "row_count", lambda b, s, u: 5)
    with pytest.raises(RuntimeError, match="table counts 5"):
        socrata.fetch({**block, "metadata": False}, None)


def test_a_segment_name_below_another_water_names_its_own_water():
    _, block = R.load_source("tx-tceq-sso-opendata")
    rows = socrata.parse(block, (FIX / "tx_tceq_sso.json").read_bytes())
    base = next(r for r in rows if r["incident_number"] == "900002")
    extra = [dict(base, incident_number=f"95000{i}", receiving_water_body=t)
             for i, t in enumerate(["Brazos River Below Navasota River", "Rio Grande Below Amistad Reservoir",
                                    "Buffalo Bayou Above Tidal"])]
    recs, _ = R.build("tx-tceq-sso-opendata", block, extra, FETCHED, (), None)
    got = {r["source_record_id"]: r for r in recs}
    assert got["950000"]["waterbody_text"] == "Brazos River" and "Navasota" in got["950000"]["raw"]["_water_text_as_given"]
    assert got["950001"]["waterbody_text"] == "Rio Grande"
    assert got["950002"]["waterbody_text"] == "Buffalo Bayou Above Tidal"


@pytest.mark.parametrize("text,cut,kept", [
    ("manholes at 17613-17645-17661 Northern Harrier Ct, 1026-1050-1058 Bat Hawk", ["17613", "1026"], []),
    ("Property line between 606-608 Port St, Horseshoe Bay, TX 78657", ["606"], ["78657"]),
    ("Grease/ 807 W 15th", ["807"], ["15th"]),
    ("Line Blockage/12341 C. F. Hawn Fwy", ["12341"], []),
    ("On 12/18/2024 a break near 29.7604, -95.3698", [], ["12/18/2024", "29.7604, -95.3698"]),
])
def test_the_audits_residual_house_numbers_are_cut_and_coordinates_stay(text, cut, kept):
    out = F.scrub_strict(text)
    assert all(c not in out for c in cut) and all(k in out for k in kept), out


def test_a_name_only_tie_far_from_the_outfall_is_refused_in_texas():
    from ingest import outfall_waters as OW

    class MT:
        waters = {"coon-lake-tx": {"name": "Coon Lake", "kind": "lake"}}

        def dist(self, s, lat, lon):
            return 930_000.0

        def source_of(self, s):
            return "nhd"

        def no_outline(self, s):
            return False

        def evidence_of(self):
            return {}
    o = {"state": "TX", "npdes_permit": "TX0129500", "lat": 35.86, "lon": -101.97, "receiving_water_echo": "COON LAKE"}
    OW.apply(o, {"slug": "coon-lake-tx", "step": "name", "how": "the only record of that name"}, MT())
    assert o["water_slug"] is None and "930 km" in o["no_water_reason"]
    o2 = {**o, "state": "OK", "npdes_permit": "OK0000001"}
    OW.apply(o2, {"slug": "coon-lake-tx", "step": "name", "how": "the only record of that name"}, MT())
    assert o2["water_slug"] == "coon-lake-tx"                              # other states unchanged
