"""Publication with agency credit; synthetic inputs, no network or source CSV saved."""
import json
from datetime import UTC, datetime

import pytest

import common
from build import status as S, rain_history, reaches
from export import build as X, coverage, outfalls
from ingest import dc_water_sso as DC, nh_des_swimming as NH

AT = "2026-11-25T01:34:00Z"
DC_CONDITION = "not for any commercial, legal or other use"
NH_CONDITION = "These data are to be used for screening purposes only. Distribution is discouraged."


def beach(status="Advisory"):
    return {"attributes": {"EPA_ID": "TEST", "Beach_Name": "Example Beach", "Waterbody_Name": "Example Lake",
                           "Status": status, "DateIssued": 1795478400000, "SampleDate": 1795478400000}}


@pytest.fixture
def published(tmp_path, monkeypatch):
    events = tmp_path / "events"
    events.mkdir()
    for mod in (common, DC, NH):
        monkeypatch.setattr(mod, "EVENTS_DIR", events)
        monkeypatch.setattr(mod, "now_iso", lambda: AT)
    monkeypatch.setattr(DC, "echo_rows", lambda: [])
    monkeypatch.setattr(NH, "match_waters", lambda *args: ([], []))
    for sid in (DC.SOURCE_ID, NH.SOURCE_ID):
        (events / f"{sid}.json").write_text(json.dumps({"source_id": sid, "records": [],
            "meta": {"distribution_discouraged": True, "export_gate": "old gate"}}))

    class Response:
        content = ("PremiseNo,Date Reported,SpillVolInGal,Location,Description\n"
                   ",2026-11-24 00:00:00,40,@EXAMPLE AVE @TEST ST NE,\n").encode()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(DC.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(NH, "_licence", lambda sess: (NH.LICENCE_FALLBACK, "NHDES"))
    monkeypatch.setattr(NH, "_layer_info", lambda *args: {"copyrightText": "NHDES"})
    monkeypatch.setattr(NH, "_query_all", lambda *args: [beach()])
    monkeypatch.setattr(NH, "fetch_hab", lambda *args: [{"attributes": {
        "WB_ID": "TEST", "WB_NAME": "Example Lake", "Bloom_status": "Warning",
        "LatestAdvisory": "Warning", "CyanoHistory": "https://example.org/bloom-history",
        "StatusDate": 1795478400000}}])
    assert DC.main([]) == NH.main([]) == 0
    return events


def test_successful_refresh_removes_withholding_and_keeps_credit(published):
    docs = {sid: json.loads((published / f"{sid}.json").read_text()) for sid in (DC.SOURCE_ID, NH.SOURCE_ID)}
    for d in docs.values():
        assert "distribution_discouraged" not in d["meta"]
        assert "export_gate" not in d["meta"]
    dc, nh = docs[DC.SOURCE_ID], docs[NH.SOURCE_ID]
    assert DC_CONDITION in dc["meta"]["use_condition"]
    assert DC_CONDITION in dc["records"][0]["raw"]["use_condition"]
    assert DC_CONDITION in dc["meta"]["terms"]
    assert nh["meta"]["licence"] == NH.LICENCE_FALLBACK
    assert NH_CONDITION in nh["meta"]["terms"]
    assert "NHDES" in nh["meta"]["credit"] and "Nov. 25, 2026" in nh["meta"]["credit"]
    assert nh["meta"]["homepage"] == NH.MAPPER
    assert all(r["source_url"] == NH.MAPPER for r in nh["records"])
    bloom, = [r for r in nh["records"] if r["event_type"] == "hab_advisory"]
    assert bloom["raw"]["CyanoHistory"] == "https://example.org/bloom-history"
    assert not list(published.parent.rglob("*.csv"))
    files, records, problems = S.load_events(published)
    assert set(files) == {DC.SOURCE_ID, NH.SOURCE_ID}
    assert len(records) == 3 and problems == [] and S.WITHHELD == []


def test_default_export_includes_both_feeds_and_their_terms(published, tmp_path, monkeypatch):
    rules = S.load_rules()
    monkeypatch.setattr(S, "_STATES", {"DC", "NH"})
    st, hist = S.build(now=datetime(2026, 11, 25, tzinfo=UTC), write=False, events_dir=published,
        waters={}, outfalls=[], registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
    assert st["withheld_sources"] == []
    monkeypatch.setattr(X, "ensure_status", lambda *args: (st, hist))
    for name, value in {"OUT_DIR": tmp_path / "out", "BUILD_DIR": tmp_path / "build",
                        "DATA_DIR": tmp_path / "data", "EVENTS_DIR": published}.items():
        monkeypatch.setattr(X, name, value)
    X.DATA_DIR.mkdir()
    monkeypatch.setattr(S, "load_waters", lambda: {})
    monkeypatch.setattr(S, "load_registry_outfalls", lambda **kw: [])
    monkeypatch.setattr(S, "load_registry", lambda: {})
    monkeypatch.setattr(S, "load_rules", lambda: rules)
    monkeypatch.setattr(X, "load_dischargers", lambda: ([], ""))
    monkeypatch.setattr(X, "launches_for", lambda *args: [])
    monkeypatch.setattr(rain_history, "load_levels", lambda: None)
    monkeypatch.setattr(reaches, "load_reaches", lambda: {})
    monkeypatch.setattr(outfalls, "ma_layer_rows", lambda: [])
    monkeypatch.setattr(coverage, "load_notification_pages", lambda: None)
    monkeypatch.setattr(coverage, "load_register", lambda: None)
    meta = X.export()
    assert meta["withheld_sources"] == [] and meta["restricted_included"] is False
    assert meta["counts"]["events"] == 3
    records = json.loads((X.OUT_DIR / "events.json").read_text())["events"]
    assert {r["category"] for r in records} == {"sewage", "beach", "bloom"}
    bloom, = [r for r in records if r["category"] == "bloom"]
    assert bloom["source_url"] == NH.MAPPER
    feeds = {f["source_id"]: f for f in json.loads((X.OUT_DIR / "sources.json").read_text())["feeds"]}
    assert DC_CONDITION in feeds[DC.SOURCE_ID]["meta"]["terms"]
    assert NH_CONDITION in feeds[NH.SOURCE_ID]["meta"]["terms"]
    assert feeds[NH.SOURCE_ID]["meta"]["homepage"] == NH.MAPPER


def test_coverage_credits_and_quotes_agencies_once():
    rules = S.load_rules()["red"]["by_state"]
    for state, words, agency in (("DC", DC_CONDITION, "DC Water"), ("NH", NH_CONDITION, "NHDES")):
        text = rules[state]["basis"]
        assert text.count(words) == 1 and agency in text


def test_merged_readers_retain_public_text_and_declarations(monkeypatch):
    from pathlib import Path
    import yaml
    monkeypatch.setattr(NH, 'match_waters', lambda *args: ([], []))
    text = 'Published contact at 123 Sample Road, 212-555-0123'
    features = [beach()]
    features[0]['attributes']['Notes'] = text
    records = NH.beach_records(features, AT, None)
    assert records[0]['raw']['Notes'] == text
    bloom = {'WB_ID': 'TEST', 'WB_NAME': 'Example Lake', 'Bloom_status': 'Warning',
             'LatestAdvisory': 'Warning', 'Notes': text}
    assert NH.hab_records([{'attributes': bloom}], AT, None)[0]['raw']['Notes'] == text
    rows, _ = DC.parse('PremiseNo,Date Reported,SpillVolInGal,Location,Description\n'
                       'CUSTOMER-7,2026-11-24 00:00:00,40,123 Sample Road,Published description\n')
    raw = DC.to_records(rows, AT)[0]['raw']
    assert raw['PremiseNo'] == 'CUSTOMER-7' and raw['Description'] == 'Published description'
    assert '123 Sample Road' in json.dumps(raw)
    root = Path(__file__).resolve().parents[2] / 'data/sources'
    dc = yaml.safe_load((root / 'dc-water-sso.yaml').read_text())['raw_fields']
    assert dc['customer_identifier'] == ['PremiseNo']
    for name in ('nhdes-healthy-swimming-mapper-beaches', 'nhdes-healthy-swimming-mapper-cyanobacteria'):
        fields = yaml.safe_load((root / (name + '.yaml')).read_text())['raw_fields']
        assert fields['reporter_contact'] == fields['customer_identifier'] == []
