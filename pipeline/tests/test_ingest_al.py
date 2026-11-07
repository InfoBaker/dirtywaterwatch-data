"""Alabama: ADEM's SSO report layers (history and live map) and the coastal beach monitoring layer, on real rows of the
2026-11-07 read (tests/fixtures/al_adem/: locations replaced by placeholders, one permittee replaced by a made-up
person's name, one location given a made-up phone number and e-mail). No network."""
import copy
import json
from pathlib import Path

import common
from ingest import al_adem_beaches as B
from ingest import al_adem_sso as S

FIX = Path(__file__).parent / "fixtures" / "al_adem"
AT = "2026-11-07T14:00:00Z"
OPS = {"AL0042234": ("al-baldwin-county-sewer-service", "Baldwin County Sewer Service, LLC")}


def _rows(name):
    return S.rows_of(json.loads((FIX / name).read_text()))


def _build(prev=(), full=True, hist=None, live=None):
    recs, stats = S.build(hist if hist is not None else _rows("history.json"),
                          live if live is not None else _rows("live.json"), AT, list(prev), full, ops=OPS)
    return {r["source_record_id"]: r for r in recs}, stats


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def test_every_row_is_one_record_keyed_by_adem_report_id():
    recs, stats = _build()
    assert len(recs) == 19 and stats["read_reports"] == 19
    assert all(r["event_type"] == "sso" and r["event_id"] == f"al-adem-sso-history:{k}" for k, r in recs.items())
    assert S.report_id("8447") == "SSO-00008447" and S.report_id("sso-00215084") == "SSO-00215084"
    assert "SSO-00008447" in recs                     # the live layer's bare id joins the history row


def test_times_are_central_wall_clock_and_received_time_from_the_live_layer():
    recs, _ = _build()
    r = recs["SSO-00215084"]                          # live: began 2026-11-03 01:03 pm, stopped 01:30 pm
    assert r["started_at"] == "2026-11-03T13:03:00-06:00" and r["ended_at"] == "2026-11-03T13:30:00-06:00"
    assert r["time_precision"] == "minute" and r["status"] == "ended"
    assert r["reported_at"] == "2026-11-05T15:05:00-06:00"         # received_date 'Nov  5 2026  3:05PM'
    assert r["raw"]["report_type"] == "Final Report" and r["raw"]["live"]["cause_of_discharge"] == "vent saddle rusted"
    assert r["discharger_id"] == "al-baldwin-county-sewer-service"
    summer = recs["SSO-00207548"]["started_at"]
    assert summer.endswith("-05:00") or summer.endswith("-06:00")
    assert recs["SSO-00000285"]["reported_at"] is None and recs["SSO-00000285"]["published_at"] is None


def test_ongoing_as_adem_marks_it_however_old():
    recs, stats = _build()
    r = recs["SSO-00008447"]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["started_at"].startswith("2018-03-18T17:00")
    assert r["raw"]["_ongoing_days"] > 3000
    assert stats["by_status"]["ongoing"] == 2      # 8447 and SSO-00212910 (Dallas County, influent lift station)


def test_receiving_water_rules():
    recs, _ = _build()
    w = {k: (r["waterbody_text"], r["raw"]["reached_water"]) for k, r in recs.items()}
    assert w["SSO-00207548"] == ("Little Cahaba Creek", True)                  # 'Storm Drain(Little Cahaba Creek)'
    assert w["SSO-00009766"] == ("UT to Stinking Bear Creek", True)
    assert w["SSO-00007989"] == ("Tennessee River; Wheeler Lake", True)         # 'Tennessee River (Wheeler Lake)'
    assert w["SSO-00209294"] == ("Rock Creek", True)        # 'Rock Creek is the discharge destination but isnt listed'
    assert w["SSO-00214479"] == ("Moores Mill Creek", True)     # the live layer's newer wording, not 'UT to ...'
    assert w["SSO-00015194"][0] == "D'olive Creek"
    assert w["SSO-00000285"] == (None, False)                                    # 'Ground Absorbed'
    assert w["SSO-00007692"] == (None, False)                                    # 'Backup into Building/Residence'
    assert w["SSO-00215084"] == (None, False)                                    # 'Ground Absorbed;pump truck'
    assert w["SSO-00000031"] == (None, None)                                     # 'Ground Absorbed;Drainage Ditch'
    assert w["SSO-00006342"] == (None, None)                                     # blank
    assert w["SSO-00008717"] == (None, None)                                     # the name lost in ADEM's migration
    assert w["SSO-00012537"] == (None, True)                                     # a private pond: a water, no name
    assert recs["SSO-00000285"]["raw"]["_no_water_reason"] == "the report names no water, only 'Ground Absorbed'"
    assert all(r["water_slugs"] == [] and r["water_match"] == "none" for r in recs.values())


def test_duplicates_and_not_an_overflow_are_kept_unplaced():
    recs, stats = _build()
    d = recs["SSO-00212910"]                          # 'This is a duplicate to Schedule SSO-00212633'
    assert d["duplicate_of"] == "al-adem-sso-history:SSO-00212633" and stats["duplicates"] == 1
    n = recs["SSO-00212317"]                          # '... this was not a sanitary sewer overflow.'
    assert n["duplicate_of"] is None and n["raw"]["reached_water"] is False and n["waterbody_text"] is None
    assert "not a sewer overflow" in n["raw"]["_no_water_reason"]


def test_volumes_as_adem_states_them():
    recs, _ = _build()
    assert recs["SSO-00207548"]["volume_gal"] == 930
    assert recs["SSO-00007989"]["volume_gal"] == 600                            # '600.00'
    assert recs["SSO-00015194"]["volume_text"].startswith("1,000 gallons or less")   # '<=1,0', cut
    v = recs["SSO-00006394"]                                                     # '10,000 < gall', cut
    assert v["volume_gal"] is None and v["volume_text"].startswith("more than 10,000 gallons") and "25,000" in v["volume_text"]
    assert recs["SSO-00008447"]["volume_text"] == "250,000 to 500,000 gallons (a range on ADEM's form)"  # live, in full
    assert recs["SSO-00000285"]["volume_text"] == "less than 1,000 gallons (as filed)"
    assert recs["SSO-00000031"]["volume_text"].startswith("more than 1,000 gallons")  # '>=1,000'
    assert all(r["volume_gal"] is None for r in recs.values() if "range" in (r["volume_text"] or ""))


def test_personal_data_never_reaches_a_record():
    recs, _ = _build()
    text = "\n".join(s for r in recs.values() for s in strings(r))
    for gone in ("Pat Q Sample", "1234 Sample", "905 Example", "205-555-0142", "ops@example.org", "77 Sample"):
        assert gone not in text
    assert recs["SSO-00000285"]["outfall_name"] == "[house number removed] Sample Ct"
    p = recs["SSO-00007280"]
    assert p["discharger_name"] == common.NAME_REMOVED and p["raw"]["row"]["permittee"] == common.NAME_REMOVED
    assert p["npdes_permit"] == "AL0060976"


def test_history_is_carried_and_a_full_read_marks_missing_reports():
    recs, _ = _build()
    prev = list(recs.values())
    hist = [a for a in _rows("history.json") if a["sso_report_id"] != "SSO-00000285"]
    again, stats = _build(prev=copy.deepcopy(prev), hist=hist, full=True)
    assert stats["kept_from_earlier_runs"] == 1
    assert again["SSO-00000285"]["raw"]["_missing_from_layer_since"] == AT
    part, _ = _build(prev=copy.deepcopy(prev), hist=hist[:3], live=[], full=False)
    assert len(part) == 19 and "_missing_from_layer_since" not in part["SSO-00000285"]["raw"]
    assert part["SSO-00215084"]["reported_at"] == "2026-11-05T15:05:00-06:00"   # kept once seen


def test_live_only_report_is_built_from_the_live_layer():
    live = _rows("live.json")
    recs, _ = _build(hist=[], live=live)
    r = recs["SSO-00214479"]
    assert r["started_at"] == "2026-10-30T08:30:00-05:00" and r["ended_at"] == "2026-10-30T10:30:00-05:00"
    assert r["npdes_permit"] == "AL0050237" and r["lat"] is not None


# ---------------------------------------------------------------- beaches

def _stations(code_of=None):
    rows = B.stations((FIX / "beach.json").read_bytes())
    for a in rows:
        if code_of and a["ID"] in code_of:
            a["Advisory"] = code_of[a["ID"]]
    return rows


def test_beach_code_11_is_no_advisory_and_another_code_opens_one():
    recs, stats = B.run(_stations(), [], AT)
    assert recs == [] and stats["stations"] == 3 and stats["codes"] == [11]
    recs, stats = B.run(_stations({"AL436981": 7}), [], AT)
    assert len(recs) == 1 and stats["opened"] == 1
    r = recs[0]
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_active"
    assert r["started_at"] == AT and r["time_precision"] == "poll" and r["waterbody_text"] == "Wolf Bay"
    assert r["raw"]["code"] == 7 and "does not publish" in r["raw"]["code_note"]
    assert r["raw"]["last_sample_date"] == "2026-11-03"


def test_beach_advisory_reconfirmed_then_lifted():
    first, _ = B.run(_stations({"AL436981": 7}), [], AT)
    later = "2026-11-08T14:00:00Z"
    again, stats = B.run(_stations({"AL436981": 3}), copy.deepcopy(first), later)
    assert stats["opened"] == 0 and again[0]["source_updated_at"] == later
    assert [c["code"] for c in again[0]["raw"]["codes_seen"]] == [7, 3]
    lifted, stats = B.run(_stations(), again, "2026-11-09T14:00:00Z")
    assert stats["lifted"] == 1 and lifted[0]["status"] == "advisory_lifted"
    assert lifted[0]["ended_at"] == "2026-11-09T14:00:00Z"


def test_beach_station_missing_changes_nothing():
    first, _ = B.run(_stations({"AL436981": 7}), [], AT)
    rows = [a for a in _stations() if a["ID"] != "AL436981"]
    out, stats = B.run(rows, copy.deepcopy(first), "2026-11-08T14:00:00Z")
    assert out[0]["status"] == "advisory_active" and stats["lifted"] == 0


def test_alabama_is_wired_in():
    import re
    root = Path(__file__).resolve().parents[2]
    rules = json.loads((root / "data" / "rules.json").read_text())
    assert rules["red"]["by_state"]["AL"]["hours"] is None
    assert "AL" not in rules["live_states"]
    assert re.search(r'"al": "Alabama"', (root / "scripts" / "gen_source_checklist.py").read_text())
    for sid in ("al-adem-sso-history", "al-adem-sso-map-live", "al-adem-beach-monitoring"):
        assert (root / "data" / "sources" / f"{sid}.yaml").exists()
