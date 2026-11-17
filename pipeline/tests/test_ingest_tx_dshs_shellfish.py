"""Texas: DSHS's shellfish harvest area status table (ingest/tx_dshs_shellfish.py).

Fixture tx_dshs_shellfish_status_2026-11-16.html: the page as read on 2026-11-16, trimmed to the title, the status
heading, the table and the link below it (the contact card is not kept). Variants are edited copies; invented text is
marked so.
"""
import json
import re
from pathlib import Path

import pytest

from ingest import tx_dshs_shellfish as X

PAGE = (Path(__file__).parent / "fixtures" / "tx_dshs_shellfish_status_2026-11-16.html").read_text()
T1, T2, T3 = "2026-11-16T23:30:00Z", "2026-11-17T15:00:00Z", "2026-11-25T15:00:00Z"


def by_area(recs):
    return {r["raw"]["area_code"]: r for r in recs}


def edit(page, old, new):
    assert old in page, old
    return page.replace(old, new, 1)


def row(page, area, pub, priv, reason):
    m = re.search(r"<tr><td>" + re.escape(area) + r"(?:&nbsp;)?</td>.*?</tr>", page)
    assert m, area
    return page[:m.start()] + f"<tr><td>{area}</td><td>{pub}</td><td>{priv}</td><td>{reason}</td></tr>" + page[m.end():]


def redate(page, d):
    return edit(page, "Status of Shellfish Harvesting Areas 11.16.2026</h2>", f"Status of Shellfish Harvesting Areas {d}</h2>")


def test_closures_for_rainfall_are_records_and_tpwd_closures_are_left_out():
    recs, meta = X.build(PAGE, T1, [])
    assert sorted(by_area(recs)) == ["TX 14", "TX 19", "TX 20", "TX 21"]
    assert meta["left_out"]["areas"] == sorted(["TX 2", "TX 3", "TX 4", "TX 6", "TX 7", "TX 8", "TX 9", "TX 11", "TX 12",
                                                "TX 15", "TX 16", "TX 18", "TX 24", "TX 25", "TX 26", "TX 27"])
    assert meta["open"] == 8 and meta["unread"] == [] and meta["table_updated"] == "2026-11-16"
    t14 = by_area(recs)["TX 14"]
    assert t14["raw"]["reason"] == "TPWD Action, Rainfall" and t14["raw"]["reasons_taken"] == ["Rainfall"]
    assert t14["raw"]["reasons_left_out"] == ["TPWD Action"]
    assert t14["raw"]["public_status"] == "Closed" and t14["raw"]["private_status"] == "Closed"
    for r in recs:
        assert r["event_type"] == "shellfish_closure" and r["status"] == "advisory_active" and r["ended_at"] is None
        assert r["started_at"] == T1 and r["time_precision"] == "poll" and r["raw"]["start_basis"] == X.START_BASIS
        assert r["published_at"] == "2026-11-16" and r["source_updated_at"] == "2026-11-16" and r["fetched_at"] == T1
        assert r["raw"]["_placement"] == "listed_only" and r["water_slugs"] == [] and r["lat"] is None
        assert r["raw"]["_poll_confirmed"] is True and r["raw"]["time_zone"] == "America/Chicago"
        assert "safe" not in json.dumps(r).lower()


def test_a_bloom_or_season_closure_is_never_a_sewage_sign_and_an_unknown_reason_is_unread():
    page = row(PAGE, "TX 19", "Closed", "n/a", "Harmful Algal Bloom")                       # invented
    recs, meta = X.build(page, T1, [])
    assert "TX 19" not in by_area(recs) and "TX 19" in meta["left_out"]["areas"]
    page = row(PAGE, "TX 19", "Closed", "n/a", "Hurricane")                                 # invented
    recs, meta = X.build(page, T1, [])
    assert "TX 19" not in by_area(recs)
    assert meta["unread"] == [{"row": 17, "area": "TX 19", "reason": "a closure reason the reader does not know"}]
    page = row(PAGE, "TX 19", "Closed", "n/a", "Not rainfall")                              # invented negation
    assert X.build(page, T1, [])[1]["unread"][0]["reason"] == "a closure reason the reader does not know"


def test_an_open_row_is_never_a_closure_whatever_its_reason():
    page = row(PAGE, "TX 19", "Open", "n/a", "Rainfall")                                    # invented
    assert "TX 19" not in by_area(X.build(page, T1, [])[0])


def test_a_closure_ends_only_on_a_complete_read_and_a_return_is_a_new_record():
    first, _ = X.build(PAGE, T1, [])
    # the same date, TX 19 gone: an incomplete read; nothing ends, health false
    gone = re.sub(r"<tr><td>TX 19</td>.*?</tr>", "", PAGE, count=1)
    recs, meta = X.build(gone, T2, first)
    assert [u["reason"] for u in meta["unread"]] == ["an area of DSHS's table is missing"]
    assert all(r["status"] == "advisory_active" for r in recs) and by_area(recs)["TX 20"]["raw"]["_last_seen_in_source"] == T2
    # a new date: TX 19 listed Open ends it; TX 21 closed now only for TPWD action ends the rainfall closure
    page = row(row(redate(PAGE, "11.17.2026"), "TX 19", "Open", "n/a", "n/a"), "TX 21", "Closed", "n/a", "TPWD Action")
    recs, meta = X.build(page, T2, first)
    t19, t21 = by_area(recs)["TX 19"], by_area(recs)["TX 21"]
    assert t19["status"] == "advisory_lifted" and t19["ended_at"] == T2 and t19["raw"]["ended_at_precision"] == "poll"
    assert t19["raw"]["end_seen_as"] == "listed open" and t19["raw"]["end_basis"] == X.END_BASIS
    assert t21["status"] == "advisory_lifted" and t21["raw"]["end_seen_as"].startswith("listed closed for a reason not")
    assert meta["lifted_this_read"] == 2 and by_area(recs)["TX 14"]["status"] == "advisory_active"
    back, _ = X.build(redate(PAGE, "11.25.2026"), T3, recs)
    t19s = [r for r in back if r["raw"]["area_code"] == "TX 19"]
    assert len(t19s) == 2 and len({r["event_id"] for r in t19s}) == 2
    assert next(r for r in t19s if r["status"] == "advisory_active")["started_at"] == T3


@pytest.mark.parametrize("bad", [
    PAGE.replace("</html>", ""),                                                             # truncated
    PAGE.replace("Shellfish Harvest Area Status and Maps</span>", "Shellfish</span>"),       # title changed
    PAGE.replace("Status of Shellfish Harvesting Areas 11.16.2026", "Status of Areas"),      # heading changed
    PAGE.replace("11.16.2026</h2>", "soon</h2>"),                                            # date unreadable
    PAGE.replace("11.16.2026</h2>", "12.30.2026</h2>"),                                      # after the read
    PAGE.replace("<th>Reason for Status</th>", "<th>Notes</th>"),                            # headings changed
    PAGE.replace("<td>TPWD Action, Rainfall</td>", "", 1),                                   # a row of three cells
    re.sub(r"<tbody>.*?</tbody>", "<tbody></tbody>", PAGE, flags=re.S),                       # no row
    "<html><body>Just a moment...</body></html>",
    "",
])
def test_a_page_not_read_whole_raises(bad):
    with pytest.raises(ValueError):
        X.parse(bad, T1)


def test_one_unreadable_row_holds_every_earlier_closure(run_tx):
    run_tx(PAGE, T1)
    page = row(redate(PAGE, "11.17.2026"), "TX 20", "Pending", "n/a", "Rainfall")           # invented status
    page = row(page, "TX 19", "Open", "n/a", "n/a")
    code, doc = run_tx(page, T2)
    assert code == 1 and doc["ok"] is False and doc["last_ok_at"] is not None
    by = by_area(doc["records"])
    assert by["TX 19"]["status"] == "advisory_active" and by["TX 19"]["raw"]["_held_unread"]   # not ended on a partial read
    assert by["TX 20"]["status"] == "advisory_active"
    assert by["TX 14"]["raw"]["_last_seen_in_source"] == T2


def test_a_failed_read_keeps_every_closure_and_fails_health(run_tx):
    code, doc = run_tx(PAGE, T1)
    assert code == 0 and doc["ok"] and len(doc["records"]) == 4
    code, doc = run_tx(PAGE.replace("<th>Harvest Area</th>", "<th>Area</th>"), T2)
    assert code == 1 and doc["ok"] is False and len(doc["records"]) == 4
    assert all(r["status"] == "advisory_active" for r in doc["records"])


PRIVATE = ("Pat Example", "512-555-0100", "pat@example.org")


def test_nothing_personal_reaches_any_save(run_tx):
    page = row(PAGE, "TX 19", "Closed", "n/a", "Rainfall")
    page = edit(page, "<td>TPWD Action, Rainfall</td>", "<td>TPWD Action, Rainfall. Call Pat Example at 512-555-0100 or "
                                                        "pat@example.org.</td>")                         # invented
    code, doc = run_tx(page, T1)
    blob = json.dumps(doc) + json.dumps(run_tx.saved)
    for p in PRIVATE:
        assert p not in blob, p
    assert "@" not in PAGE and not re.search(r"\d{3}-\d{3}-\d{4}", PAGE)
    assert all("<" not in body for _, body in run_tx.saved)


def test_ids_do_not_depend_on_row_order():
    a, _ = X.build(PAGE, T1, [])
    trs = re.findall(r"<tr><td>TX.*?</tr>", PAGE)
    body = re.search(r"<tbody>(.*?)</tbody>", PAGE).group(1)
    b, _ = X.build(PAGE.replace(body, "".join(reversed(trs))), T1, [])
    assert {r["event_id"] for r in a} == {r["event_id"] for r in b}


class _Resp:
    def __init__(self, text):
        self.text, self.headers, self.status_code = text, {}, 200

    def raise_for_status(self):
        return None


@pytest.fixture
def run_tx(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(X, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    saved = []
    monkeypatch.setattr(X, "save_raw", lambda src, body, ext: saved.append((ext, body)) or tmp_path / "raw")

    def go(page, stamp):
        monkeypatch.setattr(X, "now_iso", lambda: stamp)
        monkeypatch.setattr(X.requests, "get", lambda *a, **k: _Resp(page))
        code = X.main([])
        return code, json.loads((tmp_path / f"{X.SOURCE_ID}.json").read_text())
    go.saved = saved
    return go


def test_listed_only_closures_colour_no_water_in_the_status_build(tmp_path):
    from datetime import UTC, datetime
    from build import status as S
    recs, _ = X.build(PAGE, T1, [])
    d = tmp_path / "ev"
    d.mkdir()
    (d / f"{X.SOURCE_ID}.json").write_text(json.dumps({"source_id": X.SOURCE_ID, "ok": True, "records": recs,
                                                        "fetched_at": T1, "last_ok_at": T1}))
    allw = S.load_waters()
    waters = {k: v for k, v in allw.items() if k.endswith("-tx") and "bay" in k}
    st, _ = S.build(now=datetime(2026, 11, 17, 0, 0, tzinfo=UTC), events_dir=d, write=False, waters=waters,
                    outfalls=[], placement_cache=False, reaches={}, flows=({}, {}), discharger_towns={},
                    discharger_waters={})
    for r in recs:
        assert st["placements"][r["event_id"]]["water_slugs"] == []
        assert st["placements"][r["event_id"]]["unplaced_reason"] == S.LISTED_ONLY_WHY
    assert not [w for w in st["waters"].values() if w.get("status") == "red"]


# ---- the independent review (2026-11-16), one test per finding -------------------------------------------------------

def test_review_p1_2_only_a_strictly_newer_table_ends_a_closure():
    first, _ = X.build(PAGE, T1, [])
    same = row(PAGE, "TX 19", "Open", "n/a", "n/a")                            # the same date, the row changed
    recs, meta = X.build(same, T2, first)
    assert by_area(recs)["TX 19"]["status"] == "advisory_active" and meta["unread"]
    older = row(redate(PAGE, "11.15.2026"), "TX 19", "Open", "n/a", "n/a")      # an older table than the one held
    with pytest.raises(ValueError):
        X.build(older, T2, first)
    with pytest.raises(ValueError):                                              # dated after the read's local day
        X.parse(redate(PAGE, "11.18.2026"), T2)


def test_review_p1_3_a_table_missing_known_areas_holds_every_closure():
    first, _ = X.build(PAGE, T1, [])
    only = re.sub(r"<tbody>.*?</tbody>", "<tbody><tr><td>TX 1</td><td>Open</td><td>Open</td><td>n/a</td></tr></tbody>",
                  redate(PAGE, "11.17.2026"), flags=re.S)
    recs, meta = X.build(only, T2, first)
    assert all(r["status"] == "advisory_active" for r in recs) and len(recs) == 4
    assert any(u["reason"] == "an area of DSHS's table is missing" for u in meta["unread"])


RUNNER_PAGE = (Path(__file__).parent / "fixtures" / "tx_dshs_shellfish_runner_2026-11-17.html").read_text()


def test_runner_page_with_the_title_twice_reads():
    # GitHub's runner received the page with two h1 headings, a hidden one for screen readers and the visible one,
    # both the page's title (runner probe 44016859738, 2026-11-17); the reader failed on it ("the page's title is not
    # Shellfish Harvest Area Status and Maps")
    parsed = X.parse(RUNNER_PAGE, T1)
    assert parsed["updated"] == "2026-11-16" and not parsed["unread"]
    assert sorted(r["area"] for r in parsed["rows"] if r["kind"] == "closed") == ["TX 14", "TX 19", "TX 20", "TX 21"]


@pytest.mark.parametrize("bad", [
    RUNNER_PAGE.replace("Shellfish Harvest Area Status and Maps</span>", "Beach Watch</span>", 1),   # one h1 is another page's
    RUNNER_PAGE.replace("Shellfish Harvest Area Status and Maps</span>", "Beach Watch</span>"),      # neither is the title
    RUNNER_PAGE.replace("</h1>", "</h1>\n<h1>Page not found</h1>", 1),                              # a third, other h1
    re.sub(r"<h1\b.*?</h1>", "", RUNNER_PAGE, flags=re.S),                                          # no h1
])
def test_every_h1_must_be_the_title(bad):
    with pytest.raises(ValueError):
        X.parse(bad, T1)
