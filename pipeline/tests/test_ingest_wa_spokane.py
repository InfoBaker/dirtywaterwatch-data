"""City of Spokane's real-time CSO table (ingest/wa_spokane_cso.py). The fixture is the page as GitHub's runner read
it on 2026-11-16 (every site "none"), trimmed to its text and table; no capture with an overflow exists, so overflows
are written into it here in the formats the reader takes. No network."""
import json
import re
from pathlib import Path

import pytest

from ingest import wa_spokane_cso as SP

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "wa_spokane_cso.html").read_text()
NOW = "2026-11-16T20:00:00Z"
LATER = "2026-11-16T21:00:00Z"
DAY3 = "2026-11-18T22:00:00Z"
REG = [{"npdes_permit": "WA0024473", "outfall": o, "outfall_kind": "cso", "outfall_status": "CSO", "coords_from":
        "permitted_feature", "lat": 47.69, "lon": -117.48, "water_name": "Spokane River"} for o in ("002", "023", "033")]
REG.append({"npdes_permit": "WA0024473", "outfall": "0020", "outfall_kind": "cso", "outfall_status": "CLS",
            "coords_from": "permitted_feature", "lat": 47.6, "lon": -117.4, "water_name": "Hangman Creek"})


def overflow(page, n, when, img="cso_on.gif"):
    """Row n's date cell set to `when` (and its image), as the page would show a started overflow."""
    page = page.replace(f'<span id="MainContent_CSOGridView_CSOOverflowDate_{n}">none</span>',
                        f'<span id="MainContent_CSOGridView_CSOOverflowDate_{n}">{when}</span>')
    return re.sub(rf'(id="MainContent_CSOGridView_CSOImage_{n}" src=")Images/[^"]+', rf"\1Images/{img}", page)


def _ids(recs):
    return {r["source_record_id"]: r for r in recs}


def test_the_real_page_reads_twenty_sites_and_no_overflow(tmp_path):
    rows, unread = SP.parse(PAGE)
    assert unread == [] and len(rows) == 20
    assert [r["site"] for r in rows][:3] == ["CSO2", "CSO6", "CSO7"] and rows[-1]["site"] == "RPWRF Bypass"
    assert all(r["start"] is None and r["status"] == "IS" for r in rows)
    assert rows[9]["site"] == "CSO23-1" and rows[0]["location"] == "0.6 miles downstream of RPWRF"
    recs, meta = SP.run(rows, NOW, tmp_path / "s.json", REG)
    assert recs == [] and meta["sites"] == 20 and meta["sites_not_in_service"] == []


@pytest.mark.parametrize("when,iso", [("11/16/2026 3:45:00 PM", "2026-11-16T15:45:00-08:00"),
                                      ("11/16/2026 3:45 PM", "2026-11-16T15:45:00-08:00"),
                                      ("11/16/2026 15:45", "2026-11-16T15:45:00-08:00"),
                                      ("7/4/2026 1:05:00 AM", "2026-07-04T01:05:00-07:00")])
def test_a_start_becomes_a_record_with_no_end(tmp_path, when, iso):
    rows, unread = SP.parse(overflow(PAGE, 0, when))
    assert unread == []
    recs, _ = SP.run(rows, NOW, tmp_path / "s.json", REG)
    assert len(recs) == 1
    r = recs[0]
    assert r["started_at"] == iso and r["ended_at"] is None and r["status"] == "unknown"
    assert "end not confirmed" in r["raw"]["end_note"] and r["published_at"] is None and r["fetched_at"] == NOW
    assert r["event_type"] == "cso" and r["npdes_permit"] == "WA0024473" and r["discharger_id"] == "wa-spokane"
    assert r["outfall_id"] == "002" and r["waterbody_text"] == "Spokane River" and r["coord_source"] == "outfall_layer"
    assert r["raw"]["start_as_written"] == when and r["raw"]["time_zone"] == "America/Los_Angeles"


def test_records_build_up_and_stay_after_the_page_drops_them(tmp_path):
    st = tmp_path / "s.json"
    SP.run(SP.parse(overflow(PAGE, 0, "11/16/2026 3:45:00 PM"))[0], NOW, st, REG)
    recs, _ = SP.run(SP.parse(overflow(PAGE, 0, "11/16/2026 3:45:00 PM"))[0], LATER, st, REG)
    assert len(recs) == 1 and recs[0]["raw"]["_first_seen_at"] == NOW and recs[0]["fetched_at"] == LATER
    recs, _ = SP.run(SP.parse(PAGE)[0], DAY3, st, REG)          # 48 hours later the page shows "none"
    assert len(recs) == 1 and recs[0]["raw"]["_left_page_at"] == DAY3
    assert recs[0]["ended_at"] is None and recs[0]["status"] == "unknown"      # dropping it is not an end
    # a new start at the same site is a second record; the first keeps its own start
    recs, _ = SP.run(SP.parse(overflow(PAGE, 0, "11/19/2026 8:00:00 AM"))[0], "2026-11-19T17:00:00Z", st, REG)
    assert set(_ids(recs)) == {"cso2:20261116T1545", "cso2:20261119T0800"}


def test_suffixed_sites_and_the_bypass_are_not_tied(tmp_path):
    page = overflow(overflow(overflow(PAGE, 9, "11/16/2026 3:45 PM"), 13, "11/16/2026 3:50 PM"), 19, "11/16/2026 4:00 PM")
    recs, _ = SP.run(SP.parse(page)[0], NOW, tmp_path / "s.json", REG)
    by = {r["outfall_name"]: r for r in recs}
    for site in ("CSO23-1", "CSO33-1"):
        assert by[site]["outfall_id"] is None and by[site]["lat"] is None and by[site]["waterbody_text"] is None
        assert "numbered part" in by[site]["raw"]["place_basis"]
    assert by["RPWRF Bypass"]["event_type"] == "plant_bypass" and by["RPWRF Bypass"]["outfall_id"] is None
    assert SP.tie("CSO20", SP.outfall_points(REG))[0] is None                  # 0020 is closed


@pytest.mark.parametrize("bad", ["11/16/2026", "TBD", "13/40/2026 3:45 PM", "3/8/2026 2:30 AM", "11/16/2026 13:45 PM"])
def test_an_unknown_date_is_an_unread_row_never_none(tmp_path, bad):
    rows, unread = SP.parse(overflow(PAGE, 3, bad))
    assert len(rows) == 19 and len(unread) == 1 and "CSO10" in unread[0]


def test_an_unknown_status_is_unread():
    page = PAGE.replace('<td align="center"><font color="#000066">IS</font></td>',
                        '<td align="center"><font color="#000066">Offline</font></td>', 1)
    rows, unread = SP.parse(page)
    assert len(unread) == 1 and "status" in unread[0]


@pytest.mark.parametrize("cut", ["header", "table", "truncated", "rows"])
def test_a_changed_or_truncated_page_fails(tmp_path, cut):
    st = tmp_path / "s.json"
    SP.run(SP.parse(PAGE)[0], NOW, st, REG)
    if cut == "header":
        page = PAGE.replace("OVERFLOW DATE &amp; TIME", "LAST OVERFLOW").replace("OVERFLOW DATE & TIME", "LAST OVERFLOW")
        with pytest.raises(SP.LayoutError):
            SP.parse(page)
    elif cut == "table":
        with pytest.raises(SP.LayoutError):
            SP.parse(PAGE.replace("MainContent_CSOGridView\"", "MainContent_Grid\""))
    elif cut == "truncated":
        with pytest.raises(SP.LayoutError):
            SP.parse(PAGE[:PAGE.index("CSO26")])
    else:                                                       # a page with 12 of its 20 rows
        trs = list(re.finditer(r"<tr>.*?</tr>", PAGE, re.S))
        page = PAGE[:trs[11].start()] + PAGE[trs[-1].end():]
        rows, unread = SP.parse(page)
        with pytest.raises(SP.LayoutError, match="truncated"):
            SP.complete(len(rows) + len(unread), st)


def test_main_failed_read_keeps_records_and_fails_health(tmp_path):
    good = tmp_path / "good.html"
    good.write_text(overflow(PAGE, 0, "11/16/2026 3:45:00 PM"))
    out = tmp_path / "events.json"
    assert SP.main(["--file", str(good), "--out", str(out)]) == 0
    assert len(json.loads(out.read_text())["records"]) == 1
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>Service unavailable</body></html>")
    assert SP.main(["--file", str(bad), "--out", str(out)]) == 1
    f = json.loads(out.read_text())
    assert f["ok"] is False and len(f["records"]) == 1


def test_main_partial_read_keeps_the_unread_sites_record(tmp_path):
    out = tmp_path / "events.json"
    p1 = tmp_path / "p1.html"
    p1.write_text(overflow(PAGE, 3, "11/16/2026 3:45:00 PM"))
    assert SP.main(["--file", str(p1), "--out", str(out)]) == 0
    p2 = tmp_path / "p2.html"
    p2.write_text(overflow(PAGE, 3, "garbled"))
    assert SP.main(["--file", str(p2), "--out", str(out)]) == 1
    f = json.loads(out.read_text())
    assert f["ok"] is False and f["meta"]["unread"] and len(f["records"]) == 1
    assert "_left_page_at" not in f["records"][0]["raw"]                       # an unread row is no evidence


def test_main_accepts_backfill():
    with pytest.raises(SystemExit) as e:
        SP.main(["--backfill", "--help"])
    assert e.value.code == 0


def test_an_out_of_service_site_is_listed(tmp_path):
    page = PAGE.replace('<td align="center"><font color="#000066">IS</font></td>',
                        '<td align="center"><font color="#000066">OS</font></td>', 1)
    _, meta = SP.run(SP.parse(page)[0], NOW, tmp_path / "s.json", REG)
    assert meta["sites_not_in_service"] == ["CSO2"]


def test_no_contact_in_the_fixture_or_records(tmp_path):
    recs, _ = SP.run(SP.parse(overflow(PAGE, 0, "11/16/2026 3:45 PM"))[0], NOW, tmp_path / "s.json", REG)
    text = PAGE + json.dumps(recs)
    assert not re.search(r"\(\d{3}\)\s*\d{3}|@[a-z]+\.(?:org|com|gov)", text)
