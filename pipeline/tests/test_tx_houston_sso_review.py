"""The independent review of the Houston monthly SSO reader (2026-11-17, Astra, high): one test per finding fixed.
Fixtures as in test_ingest_tx_houston_sso.py (trimmed real pages, house numbers replaced by an invented 1234; the
addresses written here, such as 5678 WESTHOLLOW DR, are invented too)."""
import json

import pytest

from ingest import tx_houston_sso_monthly as H
from tests.test_ingest_tx_houston_sso import INDEX, PAGES, Resp, _fake_pages, _get, recs, rep, tceq_rec


# P1-1: a street holding another's letters is another street
def test_p1_1_pine_is_not_alpine():
    records = list(recs("2026-09").values())
    g = next(r for r in records if r["source_record_id"] == "68784")
    g["raw"]["location"] = "PINE ST"
    tceq = [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567, "Manhole at [house number removed] Alpine St",
                     water="Brays Bayou")]
    links = H.link_tceq(records, tceq)
    assert links["linked"] == 0 and tceq[0]["duplicate_of"] is None and g["waterbody_text"] is None
    # the street's type or a missing direction is not a difference: SAM HOUSTON PKWY and "SAM HOUSTON"
    assert H._same_street(H.street_key_of("SAM HOUSTON PKWY"), H.street_key_of("SAM HOUSTON")) is True
    assert H._same_street(H.street_key_of("N WAYSIDE DR"), H.street_key_of("WAYSIDE")) is True
    assert H._same_street(H.street_key_of("N WAYSIDE DR"), H.street_key_of("S WAYSIDE DR")) is False


# P1-2: an address TCEQ writes in lower case is still an address; one that cannot be read never allows the weaker match
def test_p1_2_lower_case_and_unreadable_tceq_addresses():
    assert H.tceq_street(tceq_rec("1", "2026-09-10", [], 0, "[house number removed] alpine st"))[0] == \
        H.street_key_of("ALPINE ST")
    key, had = H.tceq_street(tceq_rec("2", "2026-09-10", [], 0, "[house number removed] (1,1) / Manhole"))
    assert key is None and had is True
    records = list(recs("2026-09").values())
    tceq = [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567, "[house number removed] alpine st", water="Brays Bayou"),
            tceq_rec("2", "2026-09-10", ["WQ0010495003"], 567, "Manhole at [house number removed] ;", water="Brays Bayou")]
    assert H.link_tceq(records, tceq)["linked"] == 0


# P1-3: house numbers with letters, prefixes or hyphens are removed
@pytest.mark.parametrize("cell,street", [("1234AB MAIN ST", "MAIN ST"), ("REAR-1234 MAIN ST", "MAIN ST"),
                                         ("1234 MAIN ST UNIT 5B", "MAIN ST"), ("I-45 FWY", "I-45 FWY"),
                                         ("1234 W 18TH ST", "W 18TH ST"), ("1234 FM 1960 RD", "FM 1960 RD")])
def test_p1_3_strict_house_number_drop(cell, street):
    assert H.street_of(cell) == street


# P1-4: an ID before an incomplete permit starts a row; a cell holding an address is never kept
def test_p1_4_incomplete_permit_starts_a_row_and_addresses_never_reach_free_text():
    lines = ["68784 WQ0010495003 1234 GRAUSTARK ST Storm Sewer (not contained) Yes 567 Manhole Grease Blockage "
             "9/10/2026 9:33:00 AM 9/10/2026 12:15:00 PM 4 Cleaned and Disinfected",
             "68785 NON-COH (14418-", "001) 5678 WESTHOLLOW DR"]
    rows, _ = H.join_rows(lines)
    assert len(rows) == 2
    assert H.parse_row(rows[0])["corrective_action"] == "Cleaned and Disinfected"
    glued = lines[0] + " 5678 WESTHOLLOW DR"
    assert H.parse_row(glued) is None


# P1-5, P1-6: a revision that reads less completely never replaces a complete copy, and the month stays unhealthy
def test_p1_5_6_incomplete_revision_keeps_the_copy_and_is_named(tmp_path):
    state = {}
    info = {"url": "https://x/s.pdf", "title": "t"}
    assert H.read_report(state, "2026-09", info, b"a", "t1", None, pages_of=lambda c: PAGES["2026-09"]) == "new"
    short = json.loads(json.dumps(PAGES["2026-09"]))
    # one whole row taken out: every row left reads, the stated total does not match
    page = short["pages"][1].split("\n")
    start = next(i for i, x in enumerate(page) if x.startswith("68720 "))
    end = next(i for i, x in enumerate(page) if x.startswith("68726 "))
    short["pages"][1] = "\n".join(page[:start] + page[end:])
    assert H.read_report(state, "2026-09", info, b"b", "t2", None, pages_of=lambda c: short) == "kept"
    assert len(state["reports"]["2026-09"]["rows"]) == 7
    assert "2026-09" in state["pending"] and "not read completely" in state["pending"]["2026-09"]["reason"]


def test_p1_6_kept_revision_makes_the_run_partial(tmp_path):
    out, st = tmp_path / "ev.json", tmp_path / "st.json"
    assert H.run("2026-11-17T16:00:00Z", st, out, get=_get([]), tceq_path=None, pages_of=_fake_pages) == 0
    worse = json.loads(json.dumps(PAGES))
    worse["2026-09"]["pages"][1] = worse["2026-09"]["pages"][1].replace("Yes 567", "Maybe 567")

    def get(url, headers=None):
        r = _get([])(url, None)                  # no 304: a changed file
        if url != H.INDEX and r.status_code == 200:
            r.content = r.content + b"!"
        return r
    code = H.run("2026-11-17T17:00:00Z", st, out, get=get, tceq_path=None,
                 pages_of=lambda c: worse[c.decode().rstrip("!")])
    doc = json.loads(out.read_text())
    assert code == 1 and doc["ok"] is False and "2026-09" in doc["meta"]["pending"]
    assert doc["count"] == 9                 # the held copy's records are all still there (7 and the 2 of the other months)
    assert "tx-houston-sso-monthly:68784" in {r["event_id"] for r in doc["records"]}


# P1-7: a total that cannot be read is a problem, never a passed check
def test_p1_7_unread_total_is_named(tmp_path):
    pages = json.loads(json.dumps(PAGES))
    pages["2026-09"]["pages"][3] = pages["2026-09"]["pages"][3].replace("SSOs: 7", "SSOs: seven")
    out = tmp_path / "ev.json"
    H.run("2026-11-17T16:00:00Z", tmp_path / "st.json", out, get=_get([]), tceq_path=None,
          pages_of=lambda c: pages[c.decode()])
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and doc["meta"]["count_mismatch"]["2026-09"]["stated"] is None


# P1-8: an index with no month to carry, or no month read, is never a healthy read
def test_p1_8_nothing_read_is_never_healthy(tmp_path):
    old = '<a href="/a.pdf">Monthly SSO Report - JANUARY 2023</a>'
    out = tmp_path / "ev.json"
    code = H.run("2026-11-17T16:00:00Z", tmp_path / "st.json", out,
                 get=lambda u, h=None: Resp(text=old), tceq_path=None)
    assert code == 1 and json.loads(out.read_text())["ok"] is False


# P1-10: a backfill that read the index exits 0 even when every report failed, naming each
def test_p1_10_backfill_exits_0_when_every_report_failed(tmp_path):
    out = tmp_path / "ev.json"

    def get(url, headers=None):
        return Resp(text=INDEX) if url == H.INDEX else Resp(status=503)
    assert H.run("2026-11-17T16:00:00Z", tmp_path / "st.json", out, get=get, backfill=True, tceq_path=None) == 0
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and len(doc["meta"]["pending"]) == 8


# P2-11: a month that failed to fetch and then answers with the copy held is healthy again
def test_p2_11_same_copy_after_a_failure_clears_pending(tmp_path):
    out, st = tmp_path / "ev.json", tmp_path / "st.json"
    H.run("2026-11-17T16:00:00Z", st, out, get=_get([]), tceq_path=None, pages_of=_fake_pages)
    ok = _get([])

    def down(url, headers=None):
        return Resp(status=503) if "september_2026" in url else ok(url, headers)
    H.run("2026-11-17T17:00:00Z", st, out, get=down, tceq_path=None, pages_of=_fake_pages)
    assert "2026-09" in json.loads(out.read_text())["meta"]["pending"]
    assert H.run("2026-11-17T18:00:00Z", st, out, get=_get([]), tceq_path=None, pages_of=_fake_pages) == 0
    doc = json.loads(out.read_text())
    assert doc["ok"] is True and doc["meta"]["pending"] == {}


# P1-9, P2-12: the City's file is written before TCEQ's marks, and the link step after the generic reader restores
# the marks a fresh TCEQ read dropped
def test_p1_9_12_link_after_the_generic_reader_and_write_order(tmp_path, monkeypatch):
    out, st, tq = tmp_path / "ev.json", tmp_path / "st.json", tmp_path / "tceq.json"
    tq.write_text(json.dumps({"ok": True, "records": [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567,
                                                               "Manhole at [house number removed] Graustark St")]}))
    order = []
    real = H.write_json

    def spy(path, data):
        order.append(path.name)
        return real(path, data)
    import common
    monkeypatch.setattr(H, "write_json", spy)
    monkeypatch.setattr(common, "write_json", spy)
    H.run("2026-11-17T16:00:00Z", st, out, get=_get([]), tceq_path=tq, pages_of=_fake_pages)
    assert order.index("ev.json") < order.index("tceq.json")
    # the generic reader reads a new TCEQ batch: its records come back without the mark
    t = json.loads(tq.read_text())
    t["records"][0]["duplicate_of"] = None
    t["records"][0]["raw"].pop("_duplicate_basis")
    tq.write_text(json.dumps(t))
    assert H.link_only("2026-11-17T16:30:00Z", out, tq) == 0
    assert json.loads(tq.read_text())["records"][0]["duplicate_of"] == "tx-houston-sso-monthly:68784"
    doc = json.loads(out.read_text())
    assert doc["ok"] is True and doc["meta"]["tceq_links"]["linked"] == 1
    # no events file of the City's (a first run not made, a failed one): TCEQ's records are left alone, marks cleared
    t = json.loads(tq.read_text())
    assert H.link_only("2026-11-17T17:00:00Z", tmp_path / "none.json", tq) == 0
    assert json.loads(tq.read_text())["records"][0]["duplicate_of"] is None


@pytest.fixture(autouse=True)
def monthly_transport_only(monkeypatch):
    """These existing cases isolate the PDF/link transport; history paging has its own integration tests."""
    monkeypatch.setattr(H, "read_history", lambda held, at, get: held)
