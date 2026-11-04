"""The CSV downloads (export/csv.py, docs/data-downloads.md): fixed columns, RFC 4180 quoting, newest first,
a file per water, operator and state plus all-reports per year, only public fields, and the page link rule.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import csv
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as status_mod  # noqa: E402
from common import PERSONAL_KEYS, event  # noqa: E402
from export import build as X  # noqa: E402
from export import csv as csv_export  # noqa: E402

HEADER = ("event_id,water,water_slug,state,operator,operator_id,outlet_id,outlet_name,event_type,category,status,started_at,"
          "ended_at,end_reported,volume_gal,volume_text,lat,lon,towns,source_id,source_name,record_id,published_at,"
          "reported_at,source_updated_at,retrieved_at,report_url,notice_url,site_url,duplicate_of,superseded_by").split(",")
AS_OF = "2026-11-02T12:00:00Z"


@pytest.fixture(autouse=True)
def covered_states(monkeypatch):
    monkeypatch.setattr(status_mod, "_STATES", {"MA", "CT"})       # event_state() without reading the data files


def ev(rid, started="2026-10-20T10:00:00-04:00", **kw):
    """A public event as export() writes it: the common.event() record plus the placement fields."""
    base = dict(source_id="ma-massdep", source_record_id=rid, event_type="cso", status="ended", started_at=started,
                ended_at="2026-10-20T12:00:00-04:00", npdes_permit="MA0101613", discharger_id="ma-springfield-wsc",
                discharger_name="Springfield Water and Sewer Commission", water_slugs=["connecticut-river-ma"],
                outfall_id="SPR010", outfall_name="Clinton Street", lat=42.1, lon=-72.59, volume_gal=35500000,
                volume_text="35.5 MG", source_url="https://eeaonline.eea.state.ma.us/portal/x", fetched_at="2026-11-02T10:45:00Z",
                published_at="2026-10-20T15:00:00-04:00")
    base.update(kw)
    e = event(**base)
    e["fixture"] = False
    return e


WATERS = [
    {"slug": "connecticut-river-ma", "name": "Connecticut River", "state": "MA", "towns": ["Springfield"], "events": []},
    {"slug": "mill-river-ma", "name": "Mill River", "state": "MA", "towns": [], "events": []},          # no reports
]
DISCHARGERS = [
    {"id": "ma-springfield-wsc", "name": "Springfield Water and Sewer Commission", "npdes_permit": "MA0101613",
     "towns": ["Springfield", "Agawam"]},
    {"id": "ma-empty-operator", "name": "Empty Operator", "npdes_permit": "MA0000001", "towns": []},
]


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def header_of(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def write(tmp_path, events, waters=None, dischargers=None, **kw):
    out = tmp_path / "csv"
    counts = csv_export.write_csvs(events, WATERS if waters is None else waters,
                                   DISCHARGERS if dischargers is None else dischargers, out,
                                   page_ids=kw.pop("page_ids", set()), **kw)
    return out, counts


def test_files_and_columns(tmp_path):
    events = [ev("1"), ev("2", water_slugs=[], waterbody_text="Mystery Brook")]
    out, counts = write(tmp_path, events)
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*.csv"))
    assert files == ["all-reports-2026.csv", "operator/ma-springfield-wsc.csv", "state/ma.csv",
                     "water/connecticut-river-ma.csv"]          # no file for a water or operator with no reports
    assert counts["files"] == 4 and counts["water"] == 1 and counts["operator"] == 1 and counts["state"] == 1
    for p in out.rglob("*.csv"):
        assert header_of(p) == HEADER, p
    assert csv_export.COLUMNS == HEADER
    r = read(out / "water/connecticut-river-ma.csv")[0]
    assert r == {
        "event_id": "ma-massdep:1", "water": "Connecticut River", "water_slug": "connecticut-river-ma", "state": "MA",
        "operator": "Springfield Water and Sewer Commission", "operator_id": "ma-springfield-wsc", "outlet_id": "SPR010",
        "outlet_name": "Clinton Street", "event_type": "cso", "category": "sewage", "status": "ended",
        "started_at": "2026-10-20T10:00:00-04:00",
        "ended_at": "2026-10-20T12:00:00-04:00", "end_reported": "true", "volume_gal": "35500000", "volume_text": "35.5 MG",
        "lat": "42.1", "lon": "-72.59", "towns": "Springfield;Agawam", "source_id": "ma-massdep", "source_name": "",
        "record_id": "1", "published_at": "2026-10-20T15:00:00-04:00", "reported_at": "", "source_updated_at": "",
        "retrieved_at": "2026-11-02T10:45:00Z", "report_url": "https://eeaonline.eea.state.ma.us/portal/x", "notice_url": "",
        # no page of its own (page_ids is empty here): its row on the state-year archive page
        "site_url": "https://dirtywaterwatch.org/discharges/ma/2026/#ma-massdep~3A1", "duplicate_of": "", "superseded_by": ""}


def test_text_is_utf8_crlf_and_a_comma_and_quote_are_quoted(tmp_path):
    e = ev("1", outfall_name='Main St, "North" outlet', volume_text="1,200 gal\nest.", waterbody_text="Rivière")
    out, _ = write(tmp_path, [e])
    raw = (out / "all-reports-2026.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")                                  # no byte-order mark
    text = raw.decode("utf-8")
    assert '"Main St, ""North"" outlet"' in text                                # RFC 4180: quote the field, double the quote
    assert '"1,200 gal\nest."' in text                                          # a line break inside a field is quoted
    assert text.startswith(",".join(HEADER) + "\r\n") and text.endswith("\r\n")
    r = read(out / "all-reports-2026.csv")[0]
    assert r["outlet_name"] == 'Main St, "North" outlet' and r["volume_text"] == "1,200 gal\nest."


def test_text_that_a_spreadsheet_would_run_gets_an_apostrophe_numbers_do_not(tmp_path):
    e = ev("-7", outfall_name="=HYPERLINK(\"http://x\")", volume_text="-", discharger_name="+Plant", lon=-72.5, lat=-1.25)
    out, _ = write(tmp_path, [e])
    r = read(out / "all-reports-2026.csv")[0]
    assert r["outlet_name"].startswith("'=") and r["volume_text"] == "'-" and r["operator"] == "'+Plant"
    assert r["record_id"] == "'-7"
    assert r["lon"] == "-72.5" and r["lat"] == "-1.25"                          # coordinates are numbers, left alone


def test_newest_first_in_every_file_and_ties_by_id(tmp_path):
    old, new, mid = ev("old", "2025-01-01T00:00:00-05:00"), ev("new", "2026-10-30T09:00:00-04:00"), ev("mid", "2026-06-01T00:00:00-04:00")
    undated = ev("undated", None, ended_at=None, reported_at="2026-08-01T00:00:00-04:00", status="unknown")  # reported time stands in
    tie_b, tie_a = ev("b", "2026-09-01T00:00:00-04:00"), ev("a", "2026-09-01T00:00:00-04:00")
    waters = [{**WATERS[0], "events": [e["event_id"] for e in (old, new, mid, undated, tie_b, tie_a)]}, WATERS[1]]
    out, _ = write(tmp_path, [old, new, mid, undated, tie_b, tie_a], waters=waters)
    want = ["new", "a", "b", "undated", "mid", "old"]       # undated sits at its report time (08-01), after the 09-01 pair
    for rel in ("water/connecticut-river-ma.csv", "operator/ma-springfield-wsc.csv", "state/ma.csv"):
        assert [r["record_id"] for r in read(out / rel)] == want, rel
    # all-reports: a file per year, the newest year's holds the undated one, each newest first
    assert [r["record_id"] for r in read(out / "all-reports-2026.csv")] == want[:-1]
    assert [r["record_id"] for r in read(out / "all-reports-2025.csv")] == ["old"]


def test_a_water_or_operator_with_no_reports_gets_no_file(tmp_path):
    # the site links a file only when it exists; empty files for 2,500 operators passed the host's file cap
    out, _ = write(tmp_path, [ev("1")])
    assert not (out / "water/mill-river-ma.csv").exists() and not (out / "operator/ma-empty-operator.csv").exists()
    assert (out / "water").is_dir() and (out / "operator").is_dir()


def test_an_unplaced_report_is_in_state_and_all_reports_but_in_no_water_file(tmp_path):
    placed, unplaced = ev("1"), ev("2", water_slugs=[], waterbody_text="Mystery Brook")
    waters = [{**WATERS[0], "events": [placed["event_id"]]}, WATERS[1]]
    out, _ = write(tmp_path, [placed, unplaced], waters=waters)
    ids = lambda rel: {r["record_id"] for r in read(out / rel)}                 # noqa: E731
    assert ids("all-reports-2026.csv") == {"1", "2"} and ids("state/ma.csv") == {"1", "2"}
    assert ids("water/connecticut-river-ma.csv") == {"1"} and not (out / "water/mill-river-ma.csv").exists()
    r = next(r for r in read(out / "all-reports-2026.csv") if r["record_id"] == "2")
    assert r["water_slug"] == "" and r["water"] == "Mystery Brook"              # the source's own wording, no slug
    assert ids("operator/ma-springfield-wsc.csv") == {"1", "2"}                 # still the operator's report


def test_a_water_file_holds_what_the_water_page_lists_including_upstream_reports(tmp_path):
    upstream = ev("up", water_slugs=["mill-river-ma"])
    waters = [{**WATERS[0], "events": [upstream["event_id"]]}, {**WATERS[1], "events": [upstream["event_id"]]}]
    out, _ = write(tmp_path, [upstream], waters=waters)
    assert [r["water_slug"] for r in read(out / "water/connecticut-river-ma.csv")] == ["mill-river-ma"]
    assert [r["record_id"] for r in read(out / "water/mill-river-ma.csv")] == ["up"]


def test_duplicates_are_included_with_duplicate_of_and_superseded_by_as_the_last_columns(tmp_path):
    first, copy = ev("1"), ev("2", source_id="echo-sewer-overflow", duplicate_of="ma-massdep:1")
    out, _ = write(tmp_path, [first, copy])
    assert header_of(out / "all-reports-2026.csv")[-2:] == ["duplicate_of", "superseded_by"]
    rows = {r["record_id"]: r for r in read(out / "all-reports-2026.csv")}
    assert rows["2"]["duplicate_of"] == "ma-massdep:1" and rows["1"]["duplicate_of"] == ""
    assert {r["record_id"] for r in read(out / "state/ma.csv")} == {"1", "2"}


def test_no_underscore_key_and_no_personal_field_reaches_a_csv(tmp_path):
    e = ev("1")
    # what a bug could let through: private keys and personal fields at the top level and inside raw
    e.update({"_fixture": "UNDERSCORE-TOP", "_file": "UNDERSCORE-FILE", "reporter_name": "REPORTER-JANE",
              "contact_email": "CONTACT-MAIL", "inspector": "INSPECTOR-BOB", "phone": "PHONE-NUMBER",
              "submitted_by": "SUBMITTER", "operator_name": "OPERATOR-PERSON"})
    e["raw"] = {"_facility_url": "https://internal.example/UNDERSCORE-RAW", "reporter": "RAW-REPORTER",
                "contact_phone": "RAW-PHONE", "municipality": "Springfield", "note": "RAW-NOTE"}
    out, _ = write(tmp_path, [e])
    text = "".join(p.read_text(encoding="utf-8") for p in out.rglob("*.csv"))
    for secret in ("UNDERSCORE", "REPORTER", "CONTACT-MAIL", "INSPECTOR", "PHONE", "SUBMITTER", "OPERATOR-PERSON",
                   "RAW-NOTE", "internal.example"):
        assert secret not in text, secret
    for col in csv_export.COLUMNS:
        assert not col.startswith("_")
        # operator / operator_id name the sewer operator, an organisation (the registry's discharger), not a person
        assert not PERSONAL_KEYS.search(col) or col in ("operator", "operator_id"), col
    assert read(out / "all-reports-2026.csv")[0]["towns"] == "Springfield"          # the one raw value read: the record's town


def test_report_and_notice_links_are_http_only(tmp_path):
    ok = ev("1", source_url="https://example.org/a b")
    ok["raw"] = {"notice_urls": ["https://example.org/notice.pdf", "https://example.org/other"], "memo_pdf": "http://old.example/m.pdf"}
    bad = ev("2", source_url="javascript:alert(1)")
    bad["raw"] = {"notice_url": "file:///etc/passwd", "MoreInfo": "ftp://x/y"}
    out, _ = write(tmp_path, [ok, bad])
    rows = {r["record_id"]: r for r in read(out / "all-reports-2026.csv")}
    assert rows["1"]["report_url"] == "https://example.org/a%20b" and rows["1"]["notice_url"] == "https://example.org/notice.pdf"
    assert rows["2"]["report_url"] == "" and rows["2"]["notice_url"] == ""


def test_site_url_only_when_the_event_has_a_page_and_uses_the_encoded_id(tmp_path):
    a, b = ev("1"), ev("2")
    out, _ = write(tmp_path, [a, b], page_ids={a["event_id"]})
    rows = {r["record_id"]: r for r in read(out / "all-reports-2026.csv")}
    assert rows["1"]["site_url"] == "https://dirtywaterwatch.org/event/ma-massdep~3A1/"
    assert rows["2"]["site_url"] == "https://dirtywaterwatch.org/discharges/ma/2026/#ma-massdep~3A2"   # its archive row
    assert csv_export.encode_id("a:b/c~d é") == "a~3Ab~2Fc~7Ed~20~C3~A9"
    assert csv_export.encode_id("a:b/c~d é") + ".json" == X.event_file_name("a:b/c~d é")        # the export's file rule


def test_event_page_ids_follow_the_sites_rule():
    """site/src/lib/data.ts eventGetsPage (review 2026-11-03 P2-2): 90 days, active.json, a non-grey reason on a
    water, a water's unresolved flag; an old ongoing record without one of these has no page."""
    recent = ev("recent", "2026-09-01T00:00:00-04:00")
    day_91 = ev("day91", "2026-08-03T00:00:00-04:00")
    old = ev("old", "2025-01-01T00:00:00-05:00")
    old_ongoing = ev("ongoing", "2025-01-01T00:00:00-05:00", status="ongoing", ended_at=None)
    old_active = ev("active", "2025-01-01T00:00:00-05:00")
    old_unresolved = ev("unresolved", "2025-01-01T00:00:00-05:00")
    old_behind = ev("behind", "2025-01-01T00:00:00-05:00")
    old_grey = ev("grey", "2025-01-01T00:00:00-05:00")
    annual = ev("annual", "2026-10-01T00:00:00-04:00", event_type="annual_total", time_precision="year")
    month = ev("month", "2026-10-01T00:00:00-04:00", time_precision="month")
    reported_only = ev("reported", None, reported_at="2026-10-01T00:00:00-04:00", ended_at=None)
    waters = [{"slug": "w", "unresolved_events": [old_unresolved["event_id"]],
               "reasons": [{"event_id": old_behind["event_id"], "status": "yellow"},
                           {"event_id": old_grey["event_id"], "status": "grey"}]}]
    ids = csv_export.event_page_ids([recent, day_91, old, old_ongoing, old_active, old_unresolved, old_behind, old_grey,
                                     annual, month, reported_only], waters, {old_active["event_id"]}, as_of=AS_OF)
    assert ids == {e["event_id"] for e in (recent, old_active, old_unresolved, old_behind, reported_only)}


def test_an_event_with_no_discharger_id_goes_to_the_rows_holding_its_permit(tmp_path):
    e = ev("1", discharger_id=None, discharger_name=None)
    other = ev("2", discharger_id="not-in-the-registry", discharger_name="Elsewhere WWTF", npdes_permit="MA9999999")
    out, _ = write(tmp_path, [e, other])
    assert [r["record_id"] for r in read(out / "operator/ma-springfield-wsc.csv")] == ["1"]
    rows = {r["record_id"]: r for r in read(out / "all-reports-2026.csv")}
    assert rows["1"]["operator_id"] == "ma-springfield-wsc" and rows["1"]["operator"] == "Springfield Water and Sewer Commission"
    assert rows["2"]["operator_id"] == "not-in-the-registry" and rows["2"]["operator"] == "Elsewhere WWTF"
    assert not (out / "operator/ma-empty-operator.csv").exists()


def test_states_covered_get_a_file_even_with_no_reports_and_unknown_state_only_in_all_reports(tmp_path):
    nowhere = ev("1", npdes_permit=None, source_id="zz-feed", water_slugs=[], discharger_id=None)
    nowhere["event_id"] = "zz-feed:1"
    out, _ = write(tmp_path, [nowhere], states={"ma", "ct"})
    assert sorted(p.name for p in (out / "state").glob("*.csv")) == ["ct.csv", "ma.csv"]
    assert read(out / "state/ct.csv") == [] and read(out / "state/ma.csv") == []
    assert [r["record_id"] for r in read(out / "all-reports-2026.csv")] == ["1"]
    assert read(out / "all-reports-2026.csv")[0]["state"] == ""


def test_rebuild_replaces_the_files_it_owns_and_leaves_the_rest(tmp_path):
    out, _ = write(tmp_path, [ev("1")])
    (out / "water/gone-ma.csv").write_text("stale")
    (out / "README.txt").write_text("not ours")
    (out / "all-reports-2019.csv").write_text("stale year")
    (out / "all-reports.csv").write_text("stale single file")
    _, counts = write(tmp_path, [ev("1"), ev("2")])
    assert not (out / "water/gone-ma.csv").exists() and (out / "README.txt").read_text() == "not ours"
    assert not (out / "all-reports-2019.csv").exists() and not (out / "all-reports.csv").exists()
    assert len(read(out / "all-reports-2026.csv")) == 2 and counts["files"] == 4
    assert not (tmp_path / "csv.tmp").exists()


def test_all_reports_is_one_file_per_start_year_newest_year_first_undated_in_the_latest(tmp_path):
    y24, y25, y26 = ev("a24", "2024-03-01T00:00:00-05:00"), ev("a25", "2025-12-31T23:30:00-05:00"), ev("a26", "2026-01-01T00:30:00-05:00")
    y26b = ev("b26", "2026-10-30T00:00:00-04:00")
    undated = ev("none", None, ended_at=None, status="unknown", published_at=None)
    out, counts = write(tmp_path, [y24, y25, y26, y26b, undated])
    assert counts["all_reports"] == ["all-reports-2026.csv", "all-reports-2025.csv", "all-reports-2024.csv"]
    assert sorted(p.name for p in out.glob("*.csv")) == ["all-reports-2024.csv", "all-reports-2025.csv", "all-reports-2026.csv"]
    ids = lambda y: [r["record_id"] for r in read(out / f"all-reports-{y}.csv")]    # noqa: E731
    assert ids(2026) == ["b26", "a26", "none"] and ids(2025) == ["a25"] and ids(2024) == ["a24"]   # undated last: no time
    for y in (2024, 2025, 2026):
        assert header_of(out / f"all-reports-{y}.csv") == HEADER


def test_all_reports_with_no_dated_report_is_one_header_only_file_for_the_as_of_year(tmp_path):
    out, counts = write(tmp_path, [], as_of="2026-11-02T12:00:00Z")
    assert counts["all_reports"] == ["all-reports-2026.csv"]
    assert (out / "all-reports-2026.csv").read_bytes() == (",".join(HEADER) + "\r\n").encode()
    out, counts = write(tmp_path / "b", [ev("n", None, ended_at=None, status="unknown", published_at=None)], as_of="2027-01-05T00:00:00Z")
    assert counts["all_reports"] == ["all-reports-2027.csv"] and [r["record_id"] for r in read(out / "all-reports-2027.csv")] == ["n"]


def test_a_file_over_24_mib_is_split_by_year_and_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(csv_export, "SPLIT_BYTES", 1)          # every file with reports in two or more years splits
    old, new, undated = ev("old", "2025-05-01T00:00:00-04:00"), ev("new", "2026-10-01T00:00:00-04:00"), ev("none", None, ended_at=None, published_at=None)
    only25 = ev("only25", "2025-06-01T00:00:00-04:00", water_slugs=[], discharger_id="ma-empty-operator", npdes_permit="MA0000001")
    waters = [{**WATERS[0], "events": [e["event_id"] for e in (old, new, undated)]}, WATERS[1]]
    out, counts = write(tmp_path, [old, new, undated, only25], waters=waters)
    assert not (out / "water/connecticut-river-ma.csv").exists()
    ids = lambda rel: [r["record_id"] for r in read(out / rel)]                 # noqa: E731
    assert ids("water/connecticut-river-ma-2026.csv") == ["new", "none"] and ids("water/connecticut-river-ma-2025.csv") == ["old"]
    assert ids("state/ma-2026.csv") == ["new", "none"] and ids("state/ma-2025.csv") == ["only25", "old"]
    assert not (out / "operator/ma-empty-operator-2025.csv").exists() and ids("operator/ma-empty-operator.csv") == ["only25"]  # one year: whole
    assert not (out / "water/mill-river-ma.csv").exists()                       # no reports, no file
    assert counts["split"] == ["water/connecticut-river-ma.csv", "operator/ma-springfield-wsc.csv", "state/ma.csv"]
    assert counts["water"] == 1 and counts["operator"] == 2 and counts["state"] == 1
    # all-reports 2 (2026, 2025) + water 2 split + mill 1 + operator 2 split + empty operator 1 + state 2 split
    assert counts["files"] == len(list(out.rglob("*.csv"))) == 9                # mill-river-ma has no reports: no file
    logged = capsys.readouterr().out
    assert "water/connecticut-river-ma.csv" in logged and "written as" in logged


def test_a_failed_run_keeps_the_previous_files(tmp_path, monkeypatch):
    out, _ = write(tmp_path, [ev("1")])
    before = (out / "all-reports-2026.csv").read_bytes()
    real, calls = csv_export._write, []

    def flaky(path, rows):
        calls.append(path)
        if len(calls) == 3:
            raise OSError("disk full")
        real(path, rows)

    monkeypatch.setattr(csv_export, "_write", flaky)
    with pytest.raises(OSError):
        write(tmp_path, [ev("1"), ev("2")])
    assert (out / "all-reports-2026.csv").read_bytes() == before and not (tmp_path / "csv.tmp").exists()


def test_a_file_over_the_hosts_limit_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(csv_export, "MAX_FILE_BYTES", len(",".join(HEADER)) + 10)       # a header-only file fits
    _, counts = write(tmp_path, [ev("1")])
    assert "all-reports-2026.csv" in counts["oversize"] and "water/mill-river-ma.csv" not in counts["oversize"]


def test_source_names_are_the_sites_shortened_registry_name_else_the_authority_aside():
    feeds = [{"source_id": "ma-massdep", "registry_ids": ["r1", "r2"]}, {"source_id": "ny-x", "registry_ids": []}]
    registry = [{"id": "r1", "name": "MassDEP CSO API behind the portal (eeaonline.eea.state.ma.us/dep/CSOAPI/api/)"},
                {"id": "r2", "name": "Other"}]
    events = [ev("1"), ev("2", source_id="ny-x", authority="Kenmore (V) POSS (NY DEC Sewage Pollution Right to Know)")]
    assert csv_export.source_labels(events, feeds, registry) == {"ma-massdep": "MassDEP CSO API behind the portal",
                                                                 "ny-x": "NY DEC Sewage Pollution Right to Know"}


def test_the_export_writes_the_csvs_and_counts_them_in_meta():
    src = inspect.getsource(X.export)
    assert "write_csvs" in src and '"csv_files": csv_files' in src and "OUT_DIR / \"csv\"" in src
    assert src.index("write_csvs") < src.index('"csv_files": csv_files') < src.index('write_compact(OUT_DIR / "meta.json"')
    assert src.index('write_compact(water_dir / f"{slug}.json"') < src.index("write_csvs")   # after the per-water files
