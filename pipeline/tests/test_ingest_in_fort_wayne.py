"""Fort Wayne City Utilities' weekly CSO summary (ingest/in_fort_wayne_cso.py). Fixtures are the text pieces of three
real weekly PDFs (posted 2026-04-08 with a multi-day overflow and hand-edited cells, 2026-08-12 with cells drawn a
character at a time, 2026-11-12 with "no overflows"), read with pypdf 7.1.0 on 2026-11-16; the PDFs carry no
person's details. No network, no pypdf."""
import copy
import json
from datetime import date
from pathlib import Path

import pytest
import requests

from ingest import in_fort_wayne_cso as FW

FIX = Path(__file__).parent / "fixtures"
APR = json.loads((FIX / "in_fort_wayne_cso_apr08.json").read_text())
AUG = json.loads((FIX / "in_fort_wayne_cso_aug12.json").read_text())
NOV = json.loads((FIX / "in_fort_wayne_cso_nov12.json").read_text())
U_APR = FW.BASE + "2026/04/CSO-7-Day-Summary-v2-2026-Apr-08.pdf"
U_AUG = FW.BASE + "2026/08/CSO-7-Day-Summary-v2-2026-Aug-12.pdf"
U_NOV = FW.BASE + "2026/11/CSO-7-Day-Summary-v2-2026-Nov-12.pdf"


def reg(outfall, water, status="active (IDEM layer)", cf="state outfall layer", lat=41.0, lon=-85.1):
    return {"npdes_permit": "IN0032191", "outfall": outfall, "outfall_kind": "cso", "outfall_status": status,
            "coords_from": cf, "lat": lat, "lon": lon, "water_name": water}


REG = [reg("002", "Maumee River", lat=41.081, lon=-85.1), reg("004", "St. Mary's River"),
       reg("013", "St. Mary's River", lat=41.077, lon=-85.156), reg("057", "Maumee River", lat=41.084, lon=-85.108),
       reg("060", "Maumee River"), reg("003", None), reg("036", "Spy Run Creek"),
       reg("018", "St. Mary's River", status="CLS"), reg("023", "St. Mary's River", cf="facility")]


class R:
    def __init__(self, code, text="", content=b""):
        self.status_code, self.text, self.content = code, text, content

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(str(self.status_code))


def site(docs: dict, page_links=None, page_code=200):
    """A fake web: the page links page_links (default: every doc), each doc address serves its pieces (as JSON)."""
    links = list(docs) if page_links is None else page_links
    calls = []

    def get(u):
        calls.append(u)
        if u == FW.URL:
            return R(page_code, "".join(f'<p><a href="{x}">CSO Overflow Data</a></p>' for x in links))
        return R(200, content=json.dumps(docs[u]).encode()) if u in docs else R(404)
    get.calls = calls
    return get


def run(tmp_path, get, now="2026-11-16T20:00:00Z", **kw):
    out = tmp_path / "events.json"
    rc = FW.run(now, tmp_path / "state.json", out, get=get, pieces_of=json.loads, registry=REG, save=False,
                sleep=lambda s: None, **kw)
    return rc, json.loads(out.read_text())


def _ids(f):
    return {r["source_record_id"]: r for r in f["records"]}


# parsing the real documents ----------------------------------------------------------------------------------------

def test_a_real_week_with_overflows_reads_every_row():
    p = FW.parse(APR)
    assert p["days"] == ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06",
                         "2026-04-07"]
    assert len(p["outfalls"]) == 39 and p["outfalls"][:3] == ["60", "57", "64"] and "002" in p["outfalls"]
    assert len(p["rows"]) == 19 and p["no_overflows"] is False
    rows = {(r["outfall"], r["day"]): r for r in p["rows"]}
    # a cell added by hand after the report was made (another font, drawn after the table)
    assert rows[("57", "2026-04-03")] == {"outfall": "57", "day": "2026-04-03", "start": "10:20 PM", "end": "11:35 PM",
                                          "mg": "2.675"}
    # the rows pypdf's layout text merges into one line are placed by their own positions
    assert rows[("002", "2026-04-02")]["start"] == "12:00 AM" and rows[("002", "2026-04-02")]["mg"] == "62.359"
    assert rows[("13", "2026-04-01")]["start"] == "8:15 AM" and rows[("13", "2026-04-03")]["mg"] == "3.629"


def test_cells_drawn_a_character_at_a_time_are_read():
    rows = {(r["outfall"], r["day"]): r for r in FW.parse(AUG)["rows"]}
    assert len(rows) == 18
    assert rows[("57", "2026-08-11")] == {"outfall": "57", "day": "2026-08-11", "start": "2:33 PM", "end": "2:45 PM",
                                          "mg": "0.186"}


def test_a_week_with_no_overflows_has_no_row():
    p = FW.parse(NOV)
    assert p["no_overflows"] is True and p["rows"] == [] and p["days"][0] == "2026-11-05" and len(p["outfalls"]) == 38 and "44" not in p["outfalls"]


def _edit(doc, old, new=None, at=None):
    d = copy.deepcopy(doc)
    hits = [i for i, p in enumerate(d["pieces"]) if p[3] == old and (at is None or (p[1], p[2]) == at)]
    assert hits, old
    for i in hits:
        if new is None:
            d["pieces"][i] = None
        else:
            d["pieces"][i][3] = new
    d["pieces"] = [p for p in d["pieces"] if p is not None]
    if d.get("layout_text"):                     # the layout text changes with the document (the same characters)
        d["layout_text"] = d["layout_text"].replace(old, new or "", len(hits))
    return d


@pytest.mark.parametrize("change", [
    ("CSO Past Seven Days Summary", "CSO Weekly Summary"),       # renamed title
    ("Start of CSO", "Start of Event"),                         # renamed header
    ("NO OVERFLOWS OCCURRED IN THE  LAST 7 DAYS", None),         # banner gone, cells empty: never "no overflows"
])
def test_a_changed_empty_week_fails_and_never_reads_as_no_overflows(change):
    old = change[0]
    if old.startswith("NO OVERFLOWS"):
        old = next(p[3] for p in NOV["pieces"] if p[3].startswith("NO OVERFLOWS"))
    d = _edit(NOV, old, change[1])
    d.pop("layout_text")
    with pytest.raises(FW.SummaryError):
        FW.parse(d)


def test_an_unknown_word_a_lost_piece_or_a_part_row_is_unread():
    d = copy.deepcopy(APR)
    d["pieces"].append([0, 600.0, 600.2, "Preliminary"])
    d["layout_text"] += " Preliminary"
    with pytest.raises(FW.SummaryError, match="does not know|no dated row|in no column|only some"):
        FW.parse(d)
    # a row the position reader lost (pypdf changed): the layout text still has it
    d = copy.deepcopy(APR)
    d["pieces"] = [p for p in d["pieces"] if not (abs(p[2] - 642.0) < 1 and 450 < p[1] < 560)]
    with pytest.raises(FW.SummaryError, match="differ"):
        FW.parse(d)
    # a row with its volume missing
    with pytest.raises(FW.SummaryError, match="only some"):
        FW.parse(_edit(APR, "0.105"))


@pytest.mark.parametrize("bad", ["TBD", "13:20 PM", "9:75 PM"])
def test_an_unreadable_time_is_unread_never_a_volume(bad):
    d = _edit(APR, "8:55 PM", bad, at=(454.9, 642.0))
    d["layout_text"] = None
    with pytest.raises(FW.SummaryError):
        FW.parse(d)


def test_a_time_in_the_spring_forward_gap_is_unread():
    d = copy.deepcopy(APR)
    for p in d["pieces"]:
        p[3] = p[3].replace("4/1/2026", "3/8/2026").replace("4/2/2026", "3/9/2026").replace("4/3/2026", "3/10/2026")
        p[3] = p[3].replace("4/4/2026", "3/11/2026").replace("4/5/2026", "3/12/2026").replace("4/6/2026", "3/13/2026")
        p[3] = p[3].replace("4/7/2026", "3/14/2026")
    d["layout_text"] = None
    assert FW.parse(d)["rows"]
    d = _edit(d, "8:15 AM", "2:30 AM")          # 3/8/2026 02:30 does not exist in Eastern time
    with pytest.raises(FW.SummaryError, match="not a time"):
        FW.parse(d)


def test_a_banner_beside_rows_is_unread():
    d = copy.deepcopy(APR)
    d["pieces"].append([0, 600.0, 720.0, "NO OVERFLOWS OCCURRED IN THE LAST 7 DAYS"])
    d["layout_text"] = None
    with pytest.raises(FW.SummaryError, match="banner"):
        FW.parse(d)


# records -------------------------------------------------------------------------------------------------------------

def test_records_from_a_real_week(tmp_path):
    rc, f = run(tmp_path, site({U_APR: APR}))
    assert rc == 0 and f["ok"] is True and len(f["records"]) == 14
    by = _ids(f)
    r = by["002:20260401T1610"]                          # six daily rows, one overflow
    assert r["event_type"] == "cso" and r["status"] == "ended"
    assert r["started_at"] == "2026-04-01T16:10:00-04:00" and r["ended_at"] == "2026-04-06T12:56:00-04:00"
    assert r["volume_gal"] == 310_704_000 and "126.506 + 62.359" in r["volume_text"]
    assert r["outfall_id"] == "002" and (r["lat"], r["lon"]) == (41.081, -85.1) and r["waterbody_text"] == "Maumee River"
    assert r["npdes_permit"] == "IN0032191" and r["discharger_id"] == "in-city-of-fort-wayne"
    assert r["published_at"] == "2026-04-08T13:08:41-04:00" and r["reported_at"] is None
    assert r["time_precision"] == "minute" and r["estimate_flag"] == "estimated"
    assert r["raw"]["time_zone"] == "America/Indiana/Indianapolis" and r["source_url"] == U_APR
    # 36 starts 12:00 AM on the week's first day: the day before is not read, so it may have begun earlier
    assert "start_note" in by["36:20260401T0000"]["raw"]
    assert f["meta"]["weeks"][0]["from"] == "2026-04-01"


def test_ties_need_an_open_own_point_and_the_permits_water(tmp_path):
    _, f = run(tmp_path, site({U_APR: APR}))
    by = _ids(f)
    assert by["57:20260403T2220"]["outfall_id"] == "057"
    assert by["13:20260403T2045"]["outfall_id"] == "013"                  # "13" is 013
    # 60: the permit names an unnamed ditch to the Maumee, the registry the Maumee: no tie
    r = by["60:20260403T2220"] if "60:20260403T2220" in by else None
    assert r is None or r["outfall_id"] is None
    # 18 is closed in this registry, 23's point is the plant's: neither tied
    assert by["18:20260403T2100"]["outfall_id"] is None and by["18:20260403T2100"]["lat"] is None
    assert by["23:20260403T2055"]["outfall_id"] is None
    assert by["36:20260401T0000"]["outfall_id"] == "036"
    pts = FW.outfall_points(REG)
    assert FW.tie("60", pts)[0] is None and "Unnamed Ditch" in FW.tie("60", pts)[1]
    assert FW.tie("3", pts)[0] is None                                    # registry water unknown
    assert FW.tie("4", pts)[0]["outfall"] == "004"
    assert FW.tie("4A", pts)[0] is None                                   # a suffix is never 004


def test_a_no_overflow_week_is_a_read_with_no_record(tmp_path):
    rc, f = run(tmp_path, site({U_NOV: NOV}))
    assert rc == 0 and f["ok"] is True and f["records"] == []
    assert f["meta"]["weeks"] == [{"url": U_NOV, "from": "2026-11-05", "to": "2026-11-11", "rows": 0,
                                   "no_overflows": True, "created": "2026-11-12T12:23:54-05:00", "via": "page"}]


def test_records_stay_when_their_week_leaves_the_page(tmp_path):
    run(tmp_path, site({U_APR: APR}))
    rc, f = run(tmp_path, site({U_APR: APR, U_NOV: NOV}, page_links=[U_NOV]))
    assert rc == 0 and len(f["records"]) == 14 and len(f["meta"]["weeks"]) == 2


def test_a_failed_page_keeps_the_records_and_fails_health(tmp_path):
    run(tmp_path, site({U_APR: APR}))
    rc, f = run(tmp_path, site({U_APR: APR}, page_code=403))
    assert rc == 1 and f["ok"] is False and len(f["records"]) == 14
    rc, f = run(tmp_path, site({U_APR: APR}, page_links=[]))           # no summary link: a layout change
    assert rc == 1 and f["ok"] is False and len(f["records"]) == 14 and "no CSO-7-Day-Summary" in f["error"]


def test_an_unread_document_holds_health_false_and_is_retried(tmp_path):
    run(tmp_path, site({U_APR: APR}))
    broken = _edit(NOV, "Start of CSO", "Start of Event")
    rc, f = run(tmp_path, site({U_APR: APR, U_NOV: broken}, page_links=[U_NOV]))
    assert rc == 1 and f["ok"] is False and len(f["records"]) == 14 and U_NOV in f["meta"]["unread"]
    # the next run asks it again; still on the server, now readable
    rc, f = run(tmp_path, site({U_APR: APR, U_NOV: NOV}, page_links=[U_NOV]))
    assert rc == 0 and f["ok"] is True and "unread" not in f["meta"]


def test_a_revised_week_replaces_its_rows_and_never_duplicates(tmp_path):
    run(tmp_path, site({U_APR: APR}))
    rev = _edit(APR, "2.675", "2.900")
    rc, f = run(tmp_path, site({U_APR: rev}))                            # same address, new content
    assert rc == 0 and len(f["records"]) == 14
    assert _ids(f)["57:20260403T2220"]["volume_text"] == "2.900 million gallons"
    # a new address for the same days, made later: it rules those days
    rev2 = _edit(APR, "8:15 AM", "8:20 AM")
    rev2["created"] = "2026-04-09T09:00:00-04:00"
    u2 = FW.BASE + "2026/04/CSO-7-Day-Summary-v2-2026-Apr-08-1.pdf"
    rc, f = run(tmp_path, site({U_APR: rev, u2: rev2}, page_links=[u2]))
    ids = _ids(f)
    assert rc == 0 and len(f["records"]) == 14
    assert "13:20260401T0820" in ids and "13:20260401T0815" not in ids
    assert ids["57:20260403T2220"]["volume_text"] == "2.675 million gallons"     # the newer document's value


def _shift(doc, days_map, created):
    d = copy.deepcopy(doc)
    for p in d["pieces"]:
        p[3] = days_map.get(p[3], p[3])
    d["created"] = created
    lt = d["layout_text"]
    for a, b in days_map.items():
        lt = lt.replace(a, b)
    d["layout_text"] = lt
    return d


def test_an_overflow_running_past_the_last_day_read_has_no_end_until_the_next_week(tmp_path):
    # Apr-08's week cut to 4/1..4/3 is not possible (blocks need consecutive days), so the week is moved so that 002's
    # 4/2 row (12:00 AM to 11:59 PM) is the last day read: take the rows of 4/1..4/7 and rename them 3/27..4/2
    m = {f"4/{i}/2026": f"{'3/' + str(26 + i) if i <= 5 else '4/' + str(i - 5)}/2026" for i in range(1, 8)}
    m = {k: v.replace("/2026/2026", "/2026") for k, v in m.items()}
    early = _shift(APR, m, "2026-04-03T10:00:00-04:00")   # covers 3/27..4/2; 002 runs 3/27 to 4/1 then 4/1..
    rc, f = run(tmp_path, site({U_APR: early}))
    r = _ids(f)["002:20260327T1610"]
    assert r["raw"]["rows"][-1]["day"] == "2026-04-01" and r["ended_at"] == "2026-04-01T12:56:00-04:00"
    # now a week whose last day ends at 11:59 PM: drop 002's 4/6 row from the real week (4:283 MG, 12:00 AM..12:56 PM)
    d = copy.deepcopy(APR)
    d["pieces"] = [p for p in d["pieces"] if not (p[2] == 228.4 and p[1] > 800) and p[3] not in ("4.283",)]
    d["pieces"] = [p for p in d["pieces"] if not (abs(p[2] - 228.4) < 1 and p[1] > 800)]
    d["layout_text"] = None
    p = FW.parse(d)
    assert ("002", "2026-04-06") not in {(x["outfall"], x["day"]) for x in p["rows"]}
    tmp2 = tmp_path / "b"
    tmp2.mkdir()
    rc, f = run(tmp2, site({U_APR: d}))
    r = _ids(f)["002:20260401T1610"]
    assert r["ended_at"] == "2026-04-05T23:59:00-04:00" and r["status"] == "ended"   # 4/6 read, no 12:00 AM row


def test_open_end_on_the_last_day_then_joined_by_the_next_week(tmp_path):
    # the real week with 002's rows of 4/6 removed and 4/5..4/7 kept: build a week whose last day (4/7) ends 11:59 PM
    d = copy.deepcopy(APR)
    rows_y = {p[2] for p in d["pieces"] if p[3] in ("4/6/2026", "4/7/2026") and p[1] < 40}
    col = [p for p in d["pieces"] if abs(p[2] - 238.8) < 1 and p[1] > 800]      # 002's 4/5 row (12:00 AM-11:59 PM)
    d["pieces"] = [p for p in d["pieces"] if not (p[1] > 800 and any(abs(p[2] - y) < 1 for y in rows_y)
                                                 and p[1] < 960)]
    y7 = min(rows_y)
    d["pieces"] += [[0, c[1], y7, c[3] if c[3] != "26.393" else "5.000"] for c in col]
    d["layout_text"] = None
    rc, f = run(tmp_path, site({U_APR: d}))
    r = _ids(f)["002:20260407T0000"]
    assert r["status"] == "unknown" and r["ended_at"] is None and "end not confirmed" in r["raw"]["end_note"]
    assert "so far" in r["volume_text"]
    # the next week starts with 002 at 12:00 AM on 4/8: one overflow, its end now given
    m = {f"4/{i}/2026": f"4/{i + 7}/2026" for i in range(1, 8)}
    nxt = _shift(NOV, {**{f"11/{i}/2026": f"4/{i + 3}/2026" for i in range(5, 12)}}, "2026-04-15T10:00:00-04:00")
    assert FW.parse(nxt)["days"][0] == "2026-04-08"
    nxt2 = copy.deepcopy(nxt)
    nxt2["pieces"] = [p for p in nxt2["pieces"] if not p[3].startswith("NO OVERFLOWS")]
    y8 = next(p[2] for p in nxt2["pieces"] if p[3] == "4/8/2026" and p[2] < 300 and p[1] < 40)
    nxt2["pieces"] += [[0, 833.3, y8, "12:00 AM"], [0, 876.1, y8, "3:00 AM"], [0, 922.0, y8, "1.000"]]
    nxt2["layout_text"] = None
    u = FW.BASE + "2026/04/CSO-7-Day-Summary-v2-2026-Apr-15.pdf"
    assert ("002", "2026-04-08") in {(x["outfall"], x["day"]) for x in FW.parse(nxt2)["rows"]}
    rc, f = run(tmp_path, site({U_APR: d, u: nxt2}, page_links=[u]))
    ids = _ids(f)
    assert "002:20260408T0000" not in ids
    r = ids["002:20260407T0000"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-04-08T03:00:00-04:00" and r["volume_gal"] == 6_000_000
    del m


def test_backfill_tries_the_wednesday_then_the_thursday_and_lists_what_is_missing(tmp_path):
    u_thu = FW.BASE + "2026/11/CSO-7-Day-Summary-v2-2026-Nov-12.pdf"         # Wednesday 11/11 missing, Thursday there
    get = site({U_NOV: NOV}, page_links=[U_NOV])
    rc, f = run(tmp_path, get, backfill=True, since="2026-11-03", today=date(2026, 11, 16))
    assert rc == 0 and u_thu == U_NOV
    assert f["meta"]["backfill_missing"] == ["CSO-7-Day-Summary-v2-2026-Nov-04.pdf"]
    assert FW.BASE + "2026/11/CSO-7-Day-Summary-v2-2026-Nov-05.pdf" in get.calls
    assert FW.BASE + "2026/11/CSO-7-Day-Summary-v2-2026-Nov-03.pdf" in get.calls


def test_main_accepts_backfill():
    with pytest.raises(SystemExit) as e:
        FW.main(["--backfill", "--help"])
    assert e.value.code == 0


def test_pdf_date():
    assert FW.pdf_date("D:20261112122354-05'00'") == "2026-11-12T12:23:54-05:00"
    assert FW.pdf_date(None) is None and FW.pdf_date("yesterday") is None


# review 2026-11-16 (Astra) ------------------------------------------------------------------------------------------

def test_a_revision_missing_a_block_is_unread_and_keeps_the_records(tmp_path):
    run(tmp_path, site({U_APR: APR}))
    d = copy.deepcopy(APR)
    d["pieces"] = [p for p in d["pieces"] if p[2] > 200]          # the last block (27, 33, 36) cut off
    d["layout_text"] = None
    rc, f = run(tmp_path, site({U_APR: d}))
    assert rc == 1 and f["ok"] is False and len(f["records"]) == 14 and U_APR in f["meta"]["unread"]


def test_a_broken_pdf_is_unread_and_fails_health(tmp_path):
    run(tmp_path, site({U_APR: APR}))

    def bad(content):
        raise RuntimeError("PdfStreamError: truncated")             # any pypdf failure
    out = tmp_path / "events.json"
    rc = FW.run("2026-11-17T20:00:00Z", tmp_path / "state.json", out, get=site({U_APR: APR, U_NOV: NOV},
                page_links=[U_NOV]), pieces_of=bad, registry=REG, save=False, sleep=lambda s: None)
    f = json.loads(out.read_text())
    assert rc == 1 and f["ok"] is False and len(f["records"]) == 14 and U_NOV in f["meta"]["unread"]


def test_a_404_does_not_clear_an_unread_document(tmp_path):
    broken = _edit(NOV, "Start of CSO", "Start of Event")
    run(tmp_path, site({U_NOV: broken}))
    rc, f = run(tmp_path, site({U_APR: APR}, page_links=[U_APR]))       # U_NOV now answers 404
    assert rc == 1 and U_NOV in f["meta"]["unread"]


def test_error_text_is_scrubbed(tmp_path):
    d = copy.deepcopy(NOV)
    d["pieces"].append([0, 600.0, 30.0, "Contact jane.doe@example.org 260-555-0123"])
    d["layout_text"] = None
    rc, f = run(tmp_path, site({U_NOV: d}))
    st = (tmp_path / "state.json").read_text()
    assert rc == 1 and "jane.doe@" not in json.dumps(f) + st and "555-0123" not in json.dumps(f) + st


# the runner's backfill (refresh 43995607963, 2026-11-17) left three weeks unread: 2025-12-17, 2026-01-07 and
# 2026-02-25, each a "no overflows" week whose first block draws its dates a few characters at a time ("12", "/",
# "31/2025"), as hand-edited cells are drawn
JAN07 = json.loads((FIX / "in_fort_wayne_cso_jan07_2026.json").read_text())
FEB25 = json.loads((FIX / "in_fort_wayne_cso_feb25_2026.json").read_text())


@pytest.mark.parametrize("doc,first", [(JAN07, "2025-12-31"), (FEB25, "2026-02-18")])
def test_dates_drawn_a_few_characters_at_a_time_are_read(doc, first):
    p = FW.parse(doc)
    assert p["no_overflows"] is True and p["rows"] == []
    assert p["days"][0] == first and len(p["days"]) == 7 and len(p["outfalls"]) == 39


def test_a_split_date_that_does_not_make_a_day_is_unread():
    bad = copy.deepcopy(JAN07)
    piece = next(p for p in bad["pieces"] if p[3] == "31/2025")
    piece[3] = "31/20x5"
    bad["layout_text"] = bad["layout_text"].replace("12/31/2025", "12/31/20x5", 1)
    with pytest.raises(FW.SummaryError):
        FW.parse(bad)
    gone = copy.deepcopy(JAN07)                    # one piece of a split date lost: the week is not read
    gone["pieces"] = [p for p in gone["pieces"] if p[3] != "31/2025"]
    gone["layout_text"] = None
    with pytest.raises(FW.SummaryError):
        FW.parse(gone)
