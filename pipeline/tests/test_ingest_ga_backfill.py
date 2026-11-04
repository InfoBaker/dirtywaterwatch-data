"""Georgia: the history backfill from EPD's older dated spill workbooks (--backfill, --rebuild). No network: the older
postings are small name-free fixtures in the older layout (tests/fixtures/ga_epd_backfill/: BEGIN_DATE, one file
with a text posting date and an extra personal column), and the daily feed's postings are built in code."""
import copy
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import common
from build import status as S
from ingest import ga_epd_spills as G
from tests.test_ingest_ga import epa, posting, row, run

FIX = Path(__file__).parent / "fixtures" / "ga_epd_backfill"
OLD = sorted(FIX.glob("sewagespillsreport*.xlsx"))
A = "ga-epd-spills:ga0000001-20251007-12-elm-st-testville-ga-30000"
B = "ga-epd-spills:ga0000002-20250910-4-bay-st-testtown-ga-30001"
C = "ga-epd-spills:ga0000002-20250912-9-oak-rd-testtown-ga-30001"
D = "ga-epd-spills:ga0000001-20251120-12-elm-st-testville-ga-30000"


def old_postings():
    return [(p.name[18:26], G.FILE_URL.format(ymd=p.name[18:26]), p.read_bytes(), None) for p in OLD]


def rebuild(postings, prev=(), epa_recs=(), at="2026-11-05T00:00:00Z", read_at=None):
    return G.build(list(postings), list(prev), None, list(epa_recs), {"GA0000001": "ga-test-water"}, at,
                   rebuild=True, read_at=read_at)


def by_id(records):
    return {r["event_id"]: r for r in records}


def sandbox(tmp_path, monkeypatch):
    ev = tmp_path / "events"
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(G, "EVENTS_DIR", ev)
    monkeypatch.setattr(G, "EPA_EVENTS", ev / "echo-sewer-overflow.json")
    monkeypatch.setattr(G, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(G, "RAW", tmp_path / "raw")
    monkeypatch.setattr(G, "BACKFILL_PAUSE_S", 0)
    return ev


# ---------------------------------------------------------------- the older workbooks

def test_the_older_workbooks_are_read_in_their_own_layout():
    got = [G.read_posting(p.read_bytes()) for p in OLD]
    assert [g[0] for g in got] == ["2025-10-09", "2025-10-10", "2025-12-01"]    # serials, and "12/1/2025" as text
    assert [len(g[1]) for g in got] == [3, 2, 1]
    assert got[0][1][0]["begin_date"] == "2025-10-07"                             # BEGIN_DATE, aliased
    assert set(got[0][1][0]) == set(G.FIELDS)                                     # safe fields only


def test_a_personal_column_and_personal_free_text_never_reach_the_records(tmp_path, monkeypatch):
    ev = sandbox(tmp_path, monkeypatch)
    assert G.main(["--rebuild", "--no-layer", "--file", *map(str, OLD)]) == 0
    doc = json.loads((ev / "ga-epd-spills.json").read_text())
    text = json.dumps(doc["records"])
    for personal in ("Testperson", "Jane", "404-555-0123", "404-555-0199", "jt@example.com", "reported_by"):
        assert personal not in text
    assert "Grease" in text
    assert doc["meta"]["unread_columns"] == ["reported_by"]       # the header is named, its values never read
    assert "Testperson" not in json.dumps(doc["meta"])


def test_backfilled_records_keep_the_workbooks_fields_and_day_precision():
    recs, stats = rebuild(old_postings(), read_at={"20251009": "2026-11-04T20:00:00Z"})
    r = by_id(recs)
    assert set(r) == {A, B, C, D} and stats["unreadable_postings"] == []
    a = r[A]
    assert a["started_at"] == "2025-10-07" and a["time_precision"] == "day"
    assert a["ended_at"] is None and a["status"] == "unknown"                     # never an invented end
    assert a["published_at"] == "2025-10-09" and a["volume_gal"] == 1200 and a["waterbody_text"] == "Test Creek"
    assert a["raw"]["_revisions"][0]["old_values"]["quantity_gallons"] == ""      # filled in on the next posting
    assert a["raw"]["_read_from_archive"] == "2026-11-04T20:00:00Z"               # when the archived file was read
    assert a["raw"]["_aged_out_after"] == "2025-10-10"
    assert r[B]["raw"]["_aged_out_after"] == "2025-10-09" and r[B]["volume_gal"] == 500
    assert r[C]["raw"]["reached_water"] is False and r[C]["volume_gal"] is None and r[C]["volume_text"] == G.ZERO_NOTE
    assert r[D]["published_at"] == "2025-12-01" and "_read_from_archive" not in r[D]["raw"]   # the newest posting
    assert not any(x.get("duplicate_of") for x in recs)


def test_a_backfilled_spill_gets_the_day_start_caution_and_sets_no_colour_today():
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    recs, _ = rebuild(old_postings())
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    ivs = S.event_intervals(by_id(recs)[A], "GA", now, rules=rules)
    day0 = datetime(2025, 10, 7, 4, tzinfo=timezone.utc)                         # midnight in Georgia (EDT)
    assert [(i["rule"], i["color"], i["start"], i["end"]) for i in ivs[:2]] == [
        ("day_start_caution", "yellow", day0, day0 + timedelta(hours=72)),
        ("unresolved", "unresolved", day0 + timedelta(hours=72), day0 + timedelta(days=30))]
    assert all(i["end"] is not None and i["end"] < now for i in ivs if i["color"] in ("yellow", "red", "unresolved"))


# ---------------------------------------------------------------- dedupe against the daily feed

def test_the_rebuild_and_the_daily_feed_give_one_record_per_spill():
    """The live feed read 2026-11-02 and 2026-11-03; the rebuild reads 2026-10-30 (archived), then both again."""
    x = row(OVERFLOW_LOCATION="1 A St", SPILL_BEGIN_DATE="2026-10-28")
    y = row(OVERFLOW_LOCATION="2 A St", SPILL_BEGIN_DATE="2026-10-29")
    z = row(OVERFLOW_LOCATION="3 A St", SPILL_BEGIN_DATE="2026-11-02")
    old = row(OVERFLOW_LOCATION="9 Old Rd", SPILL_BEGIN_DATE="2026-10-01")
    p30, p02, p03 = posting("2026-10-30", [old, x, y]), posting("2026-11-02", [x, y]), posting("2026-11-03", [y, z])
    live, _ = G.build([p02], [], None, [], {}, "2026-11-02T12:00:00Z")
    live, _ = G.build([p03], live, None, [], {}, "2026-11-03T12:00:00Z")
    # the hazard: an old posting laid on top of today's rows marks them missing
    laid, _ = G.build([p30], live, None, [], {}, "2026-11-05T00:00:00Z")
    assert by_id(laid)["ga-epd-spills:ga0000001-20261102-3-a-st"]["raw"].get("_missing_from_source_since")
    recs, stats = rebuild([p30, p02, p03], prev=live, read_at={"20261030": "2026-11-04T20:00:00Z"})
    r = by_id(recs)
    assert len(recs) == len(r) == 4 and stats["kept_from_previous_file_not_rebuilt"] == 0
    xi, yi, zi = (f"ga-epd-spills:ga0000001-{d}-{n}-a-st" for d, n in (("20261028", 1), ("20261029", 2), ("20261102", 3)))
    assert {v["event_id"] for v in live} <= set(r)
    assert not any(v["raw"].get("_missing_from_source_since") for v in recs)
    assert r[zi]["raw"]["_first_seen_at"] == "2026-11-03T12:00:00Z" and "_read_from_archive" not in r[zi]["raw"]
    assert r[yi]["raw"]["_first_seen_at"] == "2026-11-02T12:00:00Z" and "_read_from_archive" not in r[yi]["raw"]
    assert r[yi]["published_at"] == "2026-10-30"                  # the first posting that listed it
    o = r["ga-epd-spills:ga0000001-20261001-9-old-rd"]
    assert o["raw"]["_read_from_archive"] == "2026-11-04T20:00:00Z" and o["raw"]["_first_seen_at"] == "2026-11-05T00:00:00Z"
    assert o["raw"]["_aged_out_after"] == "2026-10-30"
    assert r[xi]["raw"]["_aged_out_after"] == "2026-11-02"


def test_a_previous_record_no_saved_posting_rebuilds_is_kept():
    live, _ = run([posting("2026-11-02", [row(OVERFLOW_LOCATION="5 Lost Ln")])])
    recs, stats = rebuild(old_postings(), prev=live)
    assert live[0]["event_id"] in by_id(recs) and stats["kept_from_previous_file_not_rebuilt"] == 1


def test_backfilled_rows_pair_with_epas_reports_by_the_feeds_rules():
    reports = [epa("a", "2025-10-07", "Test Creek"), epa("b", "2025-09-10", "Other River", permit="GA0000002")]
    recs, stats = rebuild(old_postings(), epa_recs=reports)
    r = by_id(recs)
    assert r[A]["raw"]["_epa_record"] == "echo-sewer-overflow:a" and r[A]["status"] == "ended"
    assert r[A]["ended_at"] == "2025-10-07T11:00:00" and r[A]["raw"]["_end_basis"].startswith(G.EPA_BASIS)
    assert reports[0]["duplicate_of"] == A
    assert r[B]["ended_at"] is None and "_epa_not_paired" in r[B]["raw"]          # EPD and EPA name different waters
    assert reports[1]["duplicate_of"] is None and stats["epa_pairing"]["paired_by_water"] == 1
    again, _ = rebuild(old_postings(), prev=recs, epa_recs=reports)
    assert by_id(again)[A]["ended_at"] == "2025-10-07T11:00:00" and reports[0]["duplicate_of"] == A


# ---------------------------------------------------------------- idempotence, meta, the archive

def strip_fetch_times(doc):
    d = copy.deepcopy(doc)
    for r in d["records"]:
        r.pop("fetched_at", None)
    return d["records"]


def test_running_the_backfill_twice_yields_the_same_ids_and_records(tmp_path, monkeypatch):
    ev = sandbox(tmp_path, monkeypatch)
    clock = iter(["2026-11-05T00:00:00Z", "2026-11-06T00:00:00Z"])
    monkeypatch.setattr(G, "now_iso", lambda: next(clock))
    args = ["--rebuild", "--no-layer", "--file", *map(str, OLD)]
    assert G.main(args) == 0
    first = json.loads((ev / "ga-epd-spills.json").read_text())
    assert G.main(args) == 0
    second = json.loads((ev / "ga-epd-spills.json").read_text())
    assert [r["event_id"] for r in first["records"]] == [r["event_id"] for r in second["records"]]
    assert strip_fetch_times(first) == strip_fetch_times(second)                  # _first_seen_at carried over
    assert second["records"][0]["fetched_at"] == "2026-11-06T00:00:00Z"


def test_the_feeds_meta_gives_the_backfills_range_and_counts_and_keeps_them(tmp_path, monkeypatch):
    ev = sandbox(tmp_path, monkeypatch)
    assert G.main(["--rebuild", "--no-layer", "--file", *map(str, OLD)]) == 0
    bf = json.loads((ev / "ga-epd-spills.json").read_text())["meta"]["backfill"]
    assert bf["mode"] == "rebuild" and bf["postings_from"] == "2025-10-09" and bf["postings_to"] == "2025-12-01"
    assert bf["postings_applied"] == 3 and bf["records"] == 4 and bf["records_by_begin_year"] == {"2025": 4}
    assert bf["began_from"] == "2025-09-10" and bf["records_first_read_from_archive"] == 3
    later = tmp_path / "sewagespillsreport20261103.xlsx"
    later.write_bytes(posting("2026-11-03", [row()])[2])
    assert G.main(["--no-layer", "--file", str(later)]) == 0                    # an ordinary run afterwards
    doc = json.loads((ev / "ga-epd-spills.json").read_text())
    assert doc["meta"]["backfill"] == bf and doc["count"] == 5


class _Resp:
    def __init__(self, status, content=b"", text="", headers=None):
        self.status_code, self.content, self.text, self.headers = status, content, text, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_the_backfill_downloads_only_days_not_saved_keeps_each_and_rebuilds(tmp_path, monkeypatch):
    ev = sandbox(tmp_path, monkeypatch)
    files = {p.name[18:26]: p.read_bytes() for p in OLD}
    G.keep_posting("20251009", files["20251009"], None, "2026-11-01T00:00:00Z")      # saved by an earlier run
    asked: list = []

    class Sess:
        headers: dict = {}

        def get(self, url, **kw):
            asked.append(url)
            if url == G.PAGE_URL:
                return _Resp(200, text='<a href="/document/document/sewagespillsreport20251201/download">')
            ymd = url.split("sewagespillsreport")[1][:8]
            if ymd in files:
                return _Resp(200, content=files[ymd], headers={"Last-Modified": "Mon, 01 Dec 2025 14:00:00 GMT"})
            return _Resp(404, headers={"content-type": "text/html"})
    monkeypatch.setattr(G.requests, "Session", Sess)
    monkeypatch.setattr(G, "now_iso", lambda: "2026-11-05T00:00:00Z")
    assert G.main(["--backfill", "--no-layer"]) == 0
    days = [u.split("sewagespillsreport")[1][:8] for u in asked if "sewagespillsreport" in u]
    linked = date(2025, 12, 1)
    assert "20251009" not in days and {"20251010", "20251201"} <= set(days)
    assert min(days) >= (linked - timedelta(days=G.BACKFILL_DAYS)).strftime("%Y%m%d")
    assert all(date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday() < 5 for d in days)
    saved = sorted(p.name for p in G.ARCHIVE.glob("*.xlsx"))
    assert saved == [p.name for p in OLD]
    idx = json.loads((G.ARCHIVE / "index.json").read_text())
    assert idx["20251009"]["fetched_at"] == "2026-11-01T00:00:00Z"                  # not downloaded again
    assert idx["20251201"] == {"last_modified": "2025-12-01T14:00:00Z", "fetched_at": "2026-11-05T00:00:00Z"}
    doc = json.loads((ev / "ga-epd-spills.json").read_text())
    bf = doc["meta"]["backfill"]
    assert bf["mode"] == "backfill" and bf["requested_from"] == (linked - timedelta(days=G.BACKFILL_DAYS)).isoformat()
    assert bf["requests"] == len(days) and bf["days_not_posted"] == len(days) - 2 and doc["count"] == 4
    r = by_id(doc["records"])
    assert r[A]["raw"]["_read_from_archive"] == "2026-11-01T00:00:00Z"
    assert r[D]["source_updated_at"] == "2025-12-01T14:00:00Z"
    asked.clear()
    assert G.main(["--rebuild", "--no-layer"]) == 0                                  # from the archive alone
    assert not [u for u in asked if "sewagespillsreport" in u]
    assert [x["event_id"] for x in json.loads((ev / "ga-epd-spills.json").read_text())["records"]] == \
        [x["event_id"] for x in doc["records"]]


def test_a_changed_file_of_the_same_day_replaces_the_saved_copy(tmp_path):
    G.keep_posting("20251009", b"PK one", None, "2026-11-01T00:00:00Z", archive=tmp_path)
    G.keep_posting("20251009", b"PK one", None, "2026-11-02T00:00:00Z", archive=tmp_path)
    assert json.loads((tmp_path / "index.json").read_text())["20251009"]["fetched_at"] == "2026-11-01T00:00:00Z"
    G.keep_posting("20251009", b"PK two", "x", "2026-11-03T00:00:00Z", archive=tmp_path)
    assert (tmp_path / "sewagespillsreport20251009.xlsx").read_bytes() == b"PK two"
    got, read_at = G.saved_postings(tmp_path)
    assert [g[0] for g in got] == ["20251009"] and read_at == {"20251009": "2026-11-03T00:00:00Z"} and got[0][3] == "x"


def test_the_archive_is_kept_with_the_pipeline_state():
    assert G.ARCHIVE == common.BUILD_DIR / "archive" / "ga-epd-spills"           # data/build travels to R2 state/


def test_a_backfill_cut_short_keeps_what_it_downloaded(tmp_path, monkeypatch):
    sandbox(tmp_path, monkeypatch)
    files = {p.name[18:26]: p.read_bytes() for p in OLD}

    class Sess:
        def get(self, url, **kw):
            if url == G.PAGE_URL:
                return _Resp(200, text='<a href="/document/document/sewagespillsreport20251201/download">')
            ymd = url.split("sewagespillsreport")[1][:8]
            if ymd == "20251201":
                return _Resp(503, headers={"content-type": "text/html"})          # the linked file fails
            return _Resp(200, content=files[ymd]) if ymd in files else _Resp(404)
    try:
        G.fetch_postings(Sess(), None, "2025-10-08", [], have=set(),
                         keep=lambda ymd, content, lm: G.keep_posting(ymd, content, lm, "2026-11-05T00:00:00Z"))
    except ValueError:
        pass
    assert sorted(p.name for p in G.ARCHIVE.glob("*.xlsx")) == [p.name for p in OLD[:2]]


# ---------------------------------------------------------------- what the older files showed

def test_a_posting_date_that_disagrees_with_the_files_url_gives_way_to_the_url():
    """The 2026-05-18 file says 2025-05-18; others misspell the label or leave the row out."""
    ymd, url, content, lm = posting("2026-11-02", [row()])
    recs, stats = run([("20261103", G.FILE_URL.format(ymd="20261103"), content, lm)])
    assert recs[0]["published_at"] == "2026-11-02"                    # one day apart: the file's own date stands
    recs, stats = run([("20271102", G.FILE_URL.format(ymd="20271102"), content, lm)])
    assert recs[0]["published_at"] == "2027-11-02" and stats["posting_date_from_url"] == [
        "20271102: the file says 2026-11-02; 2027-11-02 used"]
    assert G.posting_date(None, "20260109", {}) == "2026-01-09" and G.posting_date("2026-01-09", "00000000", {}) == \
        "2026-01-09"


def test_a_row_whose_address_or_permit_was_corrected_is_a_duplicate_of_the_corrected_row():
    first = [row(OVERFLOW_LOCATION="12 Test Road West Testville"),
             row(OVERFLOW_LOCATION="5 Pine St", PERMIT_NUMBER="GAJ000001", SPILL_BEGIN_DATE="2026-10-28")]
    fixed = [row(OVERFLOW_LOCATION="14 Test Road West Testville"),
             row(OVERFLOW_LOCATION="5 Pine St", SPILL_BEGIN_DATE="2026-10-28")]
    recs, stats = run([posting("2026-10-30", first), posting("2026-11-02", fixed)])
    r = {x["source_record_id"]: x for x in recs}
    old_addr, old_permit = r["ga0000001-20261029-12-test-rd-w-testville"], r["gaj000001-20261028-5-pine-st"]
    assert old_addr["duplicate_of"] == "ga-epd-spills:ga0000001-20261029-14-test-rd-w-testville"
    assert "address corrected" in old_addr["raw"]["_duplicate_basis"]
    assert old_permit["duplicate_of"] == "ga-epd-spills:ga0000001-20261028-5-pine-st"
    assert "permit corrected" in old_permit["raw"]["_duplicate_basis"]
    assert stats["history"]["superseded_by_corrected_row"] == 2 and not stats["history"].get("withdrawn_within_window")


def test_a_vanished_row_with_two_possible_corrections_stays_withdrawn():
    recs, stats = run([posting("2026-10-30", [row(OVERFLOW_LOCATION="12 Test Rd")]),
                       posting("2026-11-02", [row(OVERFLOW_LOCATION="1 A St"), row(OVERFLOW_LOCATION="2 A St")])])
    gone = [x for x in recs if x["raw"].get("_missing_from_source_since")]
    assert len(gone) == 1 and gone[0]["duplicate_of"] is None and stats["history"]["withdrawn_within_window"] == 1


EXTRA = sorted((FIX / "extra").glob("sewagespillsreport*.xlsx"))


def test_epds_own_point_and_end_date_in_some_older_files_are_kept_as_given():
    """Ten files (2025-11-14 to 2026-07-14) add LATITUDE / LONGITUDE; the 2026-10-13 file adds SPILL_END_DATE (and the
    2026-10-26 file BYPASS_ID): the point is EPD's own, the end date is kept as given but never made the record's end."""
    ps = [(p.name[18:26], G.FILE_URL.format(ymd=p.name[18:26]), p.read_bytes(), None) for p in EXTRA]
    recs, stats = rebuild(ps)
    r = {x["outfall_name"].split()[0]: x for x in recs}
    seven, eight = r["7"], r["8"]
    assert (seven["lat"], seven["lon"], seven["coord_source"]) == (33.5, -84.4, "source")
    assert seven["raw"]["_coords_kept_from_earlier_read"] is True                 # the 2025-11-18 file has no point
    assert eight["lat"] is None and eight["coord_source"] is None                 # 0, 0 is not in Georgia
    assert seven["raw"]["epd_spill_end_date"]["value"] == "2025-11-13"
    assert seven["raw"]["epd_spill_end_date"]["posting"] == "2025-11-17"
    assert seven["ended_at"] is None and seven["status"] == "unknown"
    assert "_revisions" not in seven["raw"]                  # a column one posting adds or leaves out is no revision
    assert stats["unread_columns"] == ["bypass_id"] and "12345" not in json.dumps(recs)
