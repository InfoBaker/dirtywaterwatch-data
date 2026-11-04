"""The generic ingesters (docs/generic-ingesters.md): the field map, each platform's reader on a saved response,
the runner's events file, the block checks, the three times kept apart, and privacy: a personal field never
reaches the records. No network; names in the fixtures are placeholders."""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from ingest.generic import arcgis, csv_json, rss, runner, socrata
from ingest.generic import fieldmap as F

FETCHED = "2026-11-04T12:00:00Z"
TZ = "America/Chicago"


def block(**kw):
    b = {"platform": "csv", "url": "https://example.invalid/reports.csv", "time_zone": TZ,
         "safe_fields": ["report_id", "start", "end", "kind", "water", "gallons", "notes"],
         "free_text": ["notes", "water"],
         "record": {"source_record_id": "report_id", "started_at": "start", "ended_at": "end",
                    "event_type": {"field": "kind", "map": {"Sanitary Sewer Overflow": "sso", "CSO": "cso"}},
                    "waterbody_text": "water", "volume": {"field": "gallons"}}}
    b.update(kw)
    return b


CSV = ("Report ID,Start,End,Kind,Water,Gallons,Notes,Reporter Name,Contact Email,Contact Phone\n"
       "A1,10/02/2026 14:30,10/02/2026 16:00,Sanitary Sewer Overflow,Mill Creek,\"1,200\","
       "\"Inspector Placeholder found a blockage; call 312-555-0142 or ops.person@example.org. Mr. Placeholder said so.\","
       "Pat Example,pat.example@example.org,312-555-0199\n"
       "A2,10/03/2026,,CSO,none,,Rain.,Pat Example,pat.example@example.org,312-555-0199\n"
       "A3,not a date,,Pump station failure,Mill Creek,2 MG,,Pat Example,pat.example@example.org,312-555-0199\n")


def build_csv(b=None, text=CSV, prev=()):
    b = b or block()
    return runner.build("x-test", b, csv_json.parse(b, text.encode()), FETCHED, list(prev))


# ---------------------------------------------------------------- privacy

def test_a_personal_field_never_reaches_the_records():
    recs, _ = build_csv()
    dump = json.dumps(recs)
    for s in ("Pat Example", "pat.example@example.org", "312-555-0199", "312-555-0142", "ops.person@example.org",
              "Placeholder", "reporter_name", "contact_email", "contact_phone"):
        assert s not in dump, s
    a1 = next(r for r in recs if r["source_record_id"] == "A1")
    assert set(a1["raw"]["row"]) <= set(block()["safe_fields"])
    assert "[email removed]" in a1["raw"]["row"]["notes"] and "[phone removed]" in a1["raw"]["row"]["notes"]


def test_a_personal_field_named_safe_is_refused_and_a_reviewed_one_still_leaves_raw():
    b = block(safe_fields=block()["safe_fields"] + ["reporter_name"])
    assert any("reporter_name" in e for e in runner.validate_block(b))
    with pytest.raises(F.SpecError):
        build_csv(b)
    # a reviewer may let a field through (an operator's office line, say); strip_personal still drops it from raw
    b = block(safe_fields=block()["safe_fields"] + ["contact_phone"],
              reviewed_fields={"contact_phone": "test: the office line of the utility"})
    recs, _ = build_csv(b)
    assert "312-555-0199" not in json.dumps(recs) and all("contact_phone" not in r["raw"]["row"] for r in recs)


def test_a_record_field_must_read_a_safe_field():
    b = block()
    b["record"]["discharger_name"] = "reporter_name"
    errs = runner.validate_block(b)
    assert any("not a safe field" in e for e in errs)


# ---------------------------------------------------------------- times, types, never invented

def test_times_precision_and_types_from_the_field_map():
    recs, stats = build_csv()
    by = {r["source_record_id"]: r for r in recs}
    a1, a2, a3 = by["A1"], by["A2"], by["A3"]
    assert (a1["started_at"], a1["ended_at"], a1["time_precision"]) == ("2026-10-02T14:30:00-05:00",
                                                                         "2026-10-02T16:00:00-05:00", "minute")
    assert a1["status"] == "ended" and a1["event_type"] == "sso" and a1["volume_gal"] == 1200
    assert (a2["started_at"], a2["time_precision"], a2["ended_at"], a2["status"]) == ("2026-10-03T00:00:00-05:00",
                                                                                       "day", None, "unknown")
    assert a2["water_slugs"] == [] and a2["raw"]["_water"]["why_none"].startswith("receiving water given as 'none'")
    # what cannot be read is kept, unknown, with the reason
    assert a3["event_type"] == "unknown" and a3["started_at"] is None and "unreadable" in a3["parse_error"]
    assert a3["raw"]["_source_type"] == "Pump station failure" and a3["volume_gal"] == 2_000_000
    # the three clocks stay apart: no source or publication time is made up from the fetch
    for r in recs:
        assert r["fetched_at"] == FETCHED and r["reported_at"] is None and r["published_at"] is None
        assert r["source_updated_at"] is None
    assert stats["by_type"] == {"sso": 1, "cso": 1, "unknown": 1}


def test_duration_status_map_end_before_start_and_epoch_wall_clock():
    b = {"platform": "json", "url": "https://example.invalid/x.json", "time_zone": "America/New_York",
         "json": {"records_path": "data.items"},
         "safe_fields": ["id", "began", "mins", "state", "ends", "loc.lat", "loc.lon"],
         "record": {"source_record_id": "id", "started_at": {"field": "began", "parse": "epoch_ms_wallclock"},
                    "ended_at": {"duration": {"minutes": "mins"}},
                    "status": {"field": "state", "map": {"open": "ongoing"}, "otherwise": "from_end"},
                    "event_type": {"const": "sso"},
                    "lat": {"field": "loc.lat", "parse": "number"}, "lon": {"field": "loc.lon", "parse": "number"}}}
    doc = {"data": {"items": [
        {"id": 1, "began": 1791717300000, "mins": "45", "state": "closed", "loc": {"lat": 39.3, "lon": -76.6}},
        {"id": 2, "began": 1791717300000, "mins": "45", "state": "OPEN", "loc": {"lat": 39.3}},
        {"id": 3, "began": 1791717300000, "mins": "-5", "state": "closed"}]}}
    recs, _ = runner.build("x-json", b, csv_json.parse(b, json.dumps(doc).encode()), FETCHED, [])
    by = {r["source_record_id"]: r for r in recs}
    assert (by["1"]["started_at"], by["1"]["ended_at"], by["1"]["status"]) == (
        "2026-10-11T11:15:00-04:00", "2026-10-11T12:00:00-04:00", "ended")
    assert by["1"]["lat"] == 39.3 and by["1"]["coord_source"] == "source"
    assert by["2"]["status"] == "ongoing" and by["2"]["ended_at"] is None and by["2"]["raw"]["_end_while_ongoing"]
    assert by["2"]["lat"] is None and by["2"]["lon"] is None            # one coordinate is no point
    assert by["3"]["ended_at"] is None and by["3"]["status"] == "unknown"   # a negative duration gives no end


def test_templates_filters_and_value_maps():
    ctx = F.Ctx("x", {"record": {}}, ZoneInfo(TZ), FETCHED)
    row = {"permit": "md0021555", "addr": "428 East Preston Street", "code": "jf", "v": 672000.07, "empty": ""}
    rec = {"started_at": "2026-05-23T02:05:00-04:00", "time_precision": "minute"}
    assert F.render("{permit|upper|slug}-{@started_at|compact}-{addr|address|slug}", row, rec, ctx) == \
        "md0021555-20260523T0205-428-e-preston-st"
    assert F.render("{empty|default:none}/{v|num}", row, rec, ctx) == "none/672,000.07"
    assert F.render("{empty} gallons", row, rec, ctx) is None
    assert F.value({"field": "code", "map": {"JF": "Jones Falls"}}, row, rec, ctx) == "Jones Falls"
    assert F.value({"field": "code", "map": {"X": "y"}, "unmapped": None}, row, rec, ctx) is None
    assert F.value({"field": "addr", "regex": r"(\d+) East", "replace": r"No. \1"}, row, rec, ctx) == "No. 428"
    assert F.value({"field": "code", "match": "regex", "map": {"^j": "starts with j"}}, row, rec, ctx) == "starts with j"


def test_dedupe_suffix_and_history_across_runs():
    b = block(dedupe={"repeats": "suffix", "order": ["-volume_gal"]}, history={"revisions": True, "track": ["kind"]})
    text = CSV + "A1,10/02/2026 14:30,10/02/2026 16:00,Sanitary Sewer Overflow,Mill Creek,\"5,000\",,,,\n"
    first, stats = build_csv(b, text)
    by = {r["event_id"]: r for r in first}
    assert by["x-test:A1"]["volume_gal"] == 5000 and by["x-test:A1~2"]["duplicate_of"] == "x-test:A1"
    assert stats["duplicates"]["repeated_rows"] == 1
    second, stats = runner.build("x-test", b, csv_json.parse(b, CSV.replace("Rain.", "Heavy rain.").encode()),
                                 "2026-11-05T12:00:00Z", first)
    by = {r["event_id"]: r for r in second}
    assert by["x-test:A2"]["raw"]["_first_seen_at"] == FETCHED
    assert by["x-test:A2"]["raw"]["_revisions"][0]["old_values"] == {"notes": "Rain."}
    assert by["x-test:A1~2"]["raw"]["_missing_from_source_since"] == "2026-11-05T12:00:00Z"
    assert stats["history"]["kept_missing"] == 1


def test_filter_keeps_only_matching_rows():
    b = block(filter=[{"field": "kind", "regex": "overflow|cso"}])
    recs, stats = build_csv(b)
    assert sorted(r["source_record_id"] for r in recs) == ["A1", "A2"] and stats["rows_kept_by_filter"] == 2


# ---------------------------------------------------------------- platforms on saved responses

RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>News</title>
<item><title>Beach closed after sewage overflow</title><link>https://example.invalid/n/1</link><guid>n-1</guid>
<pubDate>Tue, 03 Nov 2026 15:20:00 -0600</pubDate><description>&lt;p&gt;The county closed Example Beach.
Contact &lt;b&gt;press@example.org&lt;/b&gt;.&lt;/p&gt;</description><author>pat.example@example.org (Pat Example)</author>
<category>Health</category></item>
<item><title>Road work</title><link>https://example.invalid/n/2</link><pubDate>Mon, 02 Nov 2026 09:00:00 -0600</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Alerts</title>
<entry><id>urn:alert:7</id><title>Overflow advisory lifted</title><link href="https://example.invalid/a/7"/>
<published>2026-11-03T08:00:00Z</published><updated>2026-11-03T09:30:00Z</updated>
<author><name>Pat Example</name></author><summary>Lifted for Example Creek.</summary></entry></feed>"""


def rss_block(**kw):
    b = {"platform": "rss", "url": "https://example.invalid/feed.xml", "time_zone": TZ,
         "safe_fields": ["id", "title", "link", "published", "updated", "summary", "categories"],
         "free_text": ["title", "summary"],
         "filter": [{"field": "title", "regex": "sewage|overflow"}],
         "record": {"source_record_id": "id", "published_at": "published", "source_updated_at": "updated",
                    "event_type": {"field": "title", "match": "regex",
                                   "map": {"beach closed": "beach_closure", "advisory": "beach_advisory"}},
                    "status": {"field": "title", "match": "regex", "map": {"lifted": "advisory_lifted"},
                               "otherwise": "unknown"},
                    "advice_text": "summary", "source_url": "link"}}
    b.update(kw)
    return b


def test_rss_and_atom_items_keep_publication_time_apart_and_drop_authors():
    b = rss_block()
    recs, _ = runner.build("x-rss", b, rss.parse(b, RSS.encode()), FETCHED, [])
    assert len(recs) == 1
    r = recs[0]
    assert r["published_at"] == "2026-11-03T15:20:00-06:00" and r["started_at"] is None and r["fetched_at"] == FETCHED
    assert r["event_type"] == "beach_closure" and r["source_url"] == "https://example.invalid/n/1"
    assert "Pat Example" not in json.dumps(recs) and "press@example.org" not in json.dumps(recs)
    assert r["advice_text"].startswith("The county closed Example Beach.")
    a = runner.build("x-atom", b, rss.parse(b, ATOM.encode()), FETCHED, [])[0][0]
    assert (a["published_at"], a["source_updated_at"]) == ("2026-11-03T08:00:00+00:00", "2026-11-03T09:30:00+00:00")
    assert a["status"] == "advisory_lifted" and a["event_type"] == "beach_advisory" and "Pat Example" not in json.dumps(a)


def test_socrata_json_pages_and_metadata_time():
    b = {"platform": "socrata", "domain": "https://data.example.invalid", "dataset": "abcd-1234", "time_zone": TZ,
         "safe_fields": ["case_no", "start_date", "start_time", "type"],
         "record": {"source_record_id": "case_no", "started_at": {"field": "start_date", "time": "start_time"},
                    "event_type": {"field": "type", "map": {"SSO": "sso"}}}}
    pages = {"pages": [[{"case_no": "1", "start_date": "2026-11-01T00:00:00.000", "start_time": "07:00:00", "type": "SSO",
                         "contact_name": "Pat Example"}], [{"case_no": "2", "start_date": "2026-11-02T00:00:00.000"}]]}
    rows = socrata.parse(b, json.dumps(pages).encode())
    recs, stats = runner.build("x-soda", b, rows, FETCHED, [], {"rowsUpdatedAt": 1793634953})
    by = {r["source_record_id"]: r for r in recs}
    assert by["1"]["started_at"] == "2026-11-01T07:00:00-06:00" and by["1"]["time_precision"] == "minute"
    assert by["2"]["started_at"] == "2026-11-02T00:00:00-06:00" and by["2"]["time_precision"] == "day"
    assert by["1"]["source_updated_at"] == "2026-11-02T09:55:53-06:00" == stats["source_updated_at"]
    assert "Pat Example" not in json.dumps(recs)
    assert socrata.urls(b)["json"] == "https://data.example.invalid/resource/abcd-1234.json"


def test_arcgis_geometry_and_layer_edit_time():
    b = {"platform": "arcgis", "url": "https://example.invalid/arcgis/rest/services/X/FeatureServer/0", "time_zone": TZ,
         "safe_fields": ["OBJECTID", "STATUS", "_x", "_y"], "geometry": True, "metadata": True,
         "record": {"source_record_id": "OBJECTID", "event_type": {"const": "cso"},
                    "status": {"field": "STATUS", "map": {"Active": "ongoing"}, "otherwise": "unknown"},
                    "lat": "_y", "lon": "_x"}}
    page = {"features": [{"attributes": {"OBJECTID": 5, "STATUS": "Active", "EDITOR": "pexample"},
                          "geometry": {"x": -87.62, "y": 41.88}}]}
    recs, _ = runner.build("x-arc", b, arcgis.parse(b, json.dumps(page).encode()), FETCHED, [],
                           {"editingInfo": {"lastEditDate": 1793634953000}})
    r = recs[0]
    assert (r["lat"], r["lon"], r["status"]) == (41.88, -87.62, "ongoing")
    assert r["source_updated_at"] == "2026-11-02T09:55:53-06:00" and "pexample" not in json.dumps(recs)


# ---------------------------------------------------------------- the runner and the registry

def write_source(d: Path, sid: str, b: dict, **row):
    (d / f"{sid}.yaml").write_text(yaml.safe_dump({"id": sid, "name": sid, "enabled": True, "registry_ids": ["r1"],
                                                   **row, "fetch": b}))


def test_runner_writes_the_events_file_as_a_module_does(tmp_path, monkeypatch):
    src = tmp_path / "sources"
    src.mkdir()
    write_source(src, "x-live", {**block(), "live": True})
    write_source(src, "x-port", {**block(), "live": False})
    saved = tmp_path / "saved.csv"
    saved.write_text(CSV)
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    assert runner.live_ids(src) == ["x-live"]
    # a block that is not live never writes the module's events file
    assert runner.run("x-port", file=str(saved), sources_dir=src) == 2
    out = tmp_path / "out.json"
    assert runner.run("x-port", file=str(saved), out=str(out), sources_dir=src) == 0
    d = json.loads(out.read_text())
    assert d["source_id"] == "x-port" and d["ok"] and d["count"] == 3 and len(d["records"]) == 3
    assert d["meta"]["generic"] is True and d["meta"]["registry_ids"] == ["r1"] and d["meta"]["platform"] == "csv"
    # a failed fetch keeps the previous records and says why
    assert runner.run("x-port", file=str(tmp_path / "missing.csv"), out=str(out), sources_dir=src) == 1
    d2 = json.loads(out.read_text())
    assert d2["ok"] is False and d2["count"] == 3 and "FileNotFoundError" in d2["error"]


def test_every_fetch_block_in_the_registry_is_valid():
    assert runner.check_all() == {}
    assert {"md-mde-overflows", "md-baltimore-sso"} <= set(runner.blocks())
    assert "md-mde-overflows" not in runner.live_ids()        # the coordinator switches a port over, not a test


def test_the_makefile_runs_the_live_generic_sources_after_the_modules():
    mk = (Path(__file__).resolve().parents[2] / "Makefile").read_text()
    ingest = mk.split("\ningest:", 1)[1].split("\n\n", 1)[0]
    assert "ingest.generic --list" in ingest
    assert ingest.index("INGEST_MODULES") < ingest.index("ingest.generic") < ingest.index("for m in $(INGEST_SNAPSHOTS)")


def test_every_example_in_the_documentation_is_a_valid_block():
    import re
    doc = (Path(__file__).resolve().parents[2] / "docs" / "generic-ingesters.md").read_text()
    examples = [yaml.safe_load(m)["fetch"] for m in re.findall(r"```yaml\n(.*?)```", doc, re.S)]
    assert {b["platform"] for b in examples} == {"socrata", "arcgis", "csv", "json", "rss", "snapshot"}
    for b in examples:
        assert runner.validate_block(b) == [], b["platform"]
