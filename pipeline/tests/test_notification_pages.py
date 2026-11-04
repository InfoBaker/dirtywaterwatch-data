"""ingest/notification_pages.py: snapshots, change-only notices, unreachable pages and the page-health wording
(no network: a fake fetcher serves pages from memory)."""
import json
import pytest
from datetime import UTC, date, datetime
from pathlib import Path

from ingest import notification_pages as M

ROOT = Path(__file__).resolve().parents[2]
URL = "https://example.org/cso"
SHARED = "https://shared.example.org/"


def chan(**kw):
    r = {"id": "nj-test-page", "state": "NJ", "operator_id": "nj-trenton", "agency": None,
         "name": "Trenton Sewer Utility", "permit": "NJ0020923", "channel_kind": "operator_page", "urls": [URL],
         "method": "html", "legal_basis": "NJPDES permit NJ0020923", "basis_kind": "permit", "monitored": True,
         "unmonitored_reason": None, "publishes": "notices", "note": None, "checked": "2026-11-03",
         "default_event_type": "cso"}
    r.update(kw)
    return r


def page(*paras):
    return ("<html><head><title>x</title><script>var t='Nov 3, 2026 overflow';</script></head><body><nav>Home</nav>"
            + "".join(f"<p>{p}</p>" for p in paras) + "<footer>Call 201-555-0100</footer></body></html>").encode()


class Web:
    """A fake fetcher: {url: bytes | int (HTTP status) | Exception}."""
    def __init__(self, pages):
        self.pages, self.calls = dict(pages), []
        self.at = "2026-11-03T15:00:00Z"

    def __call__(self, url, browser=False):
        self.calls.append(url)
        v = self.pages[url]
        if isinstance(v, Exception):
            return {"at": self.at, "ok": False, "http_status": None, "error": str(v), "body": b""}
        if isinstance(v, int):
            return {"at": self.at, "ok": False, "http_status": v, "error": f"HTTP {v}", "body": b"<h1>Not Found</h1>"}
        return {"at": self.at, "ok": True, "http_status": 200, "final_url": url, "content_type": "text/html",
                "error": None, "body": v}


def runner(tmp_path, channels):
    raws = tmp_path / "raw"

    def saver(source, body, ext):
        p = raws / source / f"{len(list(raws.rglob('*')))}.{ext}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        return p

    def go(web, now):
        web.at = now
        return M.run(channels, now=datetime.fromisoformat(now.replace("Z", "+00:00")), fetcher=web,
                     store=tmp_path / "store", root=tmp_path, raw_saver=saver)
    return go


BASE = ["CSO Advisory System", "Combined sewer overflows can occur during heavy rain.",
        "Report dry weather discharges to the hotline."]


def test_a_changed_page_makes_records_only_from_dated_notices(tmp_path):
    go = runner(tmp_path, [chan()])
    web = Web({URL: page(*BASE)})
    first = go(web, "2026-11-03T15:00:00Z")
    assert first["records"] == [] and first["stats"]["fetched"] == 1      # the first snapshot is a baseline
    web.pages[URL] = page(*BASE,
                          "A CSO discharge occurred at Outfall 002A on November 2, 2026.",      # a dated notice
                          "CSO discharges may occur at any time during wet weather.",          # undated
                          "CSO public meeting on November 18, 2026 at City Hall.",             # a meeting
                          "Outfall 002A: the gate is closed and discharges are unlikely (Nov 3, 2026).",  # negative
                          "Hurricane Floyd overflow of September 16, 1999.")                   # too old
    out = go(web, "2026-11-03T16:00:00Z")
    assert len(out["records"]) == 1 and out["stats"]["records_new"] == 1
    r = out["records"][0]
    assert r["event_type"] == "cso" and r["status"] == "unknown" and r["time_precision"] == "day"
    assert r["started_at"] == "2026-11-02T00:00:00-05:00" and r["ended_at"] is None and r["reported_at"] is None
    assert r["outfall_id"] == "002A" and r["source_url"] == URL and r["discharger_id"] == "nj-trenton"
    assert r["npdes_permit"] == "NJ0020923" and r["raw"]["first_seen_at"] == "2026-11-03T16:00:00Z"
    snap = out["snaps"][URL]
    why = {s["why"].split(" (")[0].split(",")[0] for s in snap["changes"][-1]["skipped"]}
    assert any("meeting" in w for w in why) and any("unlikely" in w or "no overflow" in w for w in why)
    # the same notice on the next fetch matches the previous snapshot: no new record
    again = go(web, "2026-11-03T17:00:00Z")
    assert again["stats"]["records_new"] == 0 and len(again["records"]) == 1
    # an end with its own date ends the record
    web.pages[URL] = page(*BASE, "A CSO discharge began on November 2, 2026 and ended November 3, 2026.")
    ended = go(web, "2026-11-03T18:00:00Z")
    new = [x for x in ended["records"] if x["status"] == "ended"]
    assert len(new) == 1 and new[0]["ended_at"] == "2026-11-03T00:00:00-05:00"
    gone = [x for x in ended["records"] if x["status"] == "unknown"][0]
    assert gone["raw"]["removed_from_page_at"] == "2026-11-03T18:00:00Z"


def test_boilerplate_changes_make_no_records(tmp_path):
    shared_rows = [chan(id="nj-shared-entry", channel_kind="shared_site", urls=[SHARED], publishes="likelihood",
                        records=False, link_text="the shared rainfall site",
                        entry={"start": "NJ0020923", "end": r"\bNJ\d{7}\b|This site indicates"},
                        ignore_lines=[r"^[\d.]+″$", r"^CSO event (?:likely|unlikely)$",
                                      r"^[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M$"],
                        status_pattern=r"CSO event (?:likely|unlikely)")]
    go = runner(tmp_path, [chan()] + shared_rows)
    shared = ["Town A NJ0020923", "0.00″", "CSO event unlikely", "Nov 2, 12:00 PM", "Town B NJ0000001", "0.00″",
              "CSO event unlikely", "Nov 2, 12:00 PM", "This site indicates when an overflow is likely, not that one has occurred."]
    web = Web({URL: page(*BASE), SHARED: page(*shared)})
    go(web, "2026-11-03T15:00:00Z")
    # the shared site reorders its towns and updates its readings: not a change of its text
    web.pages[SHARED] = page("Town B NJ0000001", "0.42″", "CSO event likely", "Nov 3, 9:00 AM", "Town A NJ0020923",
                             "0.10″", "CSO event unlikely", "Nov 3, 9:00 AM", shared[8])
    # the operator page copies the shared site's wording and its time label, reshuffles its own boilerplate
    # and adds a menu item: changes, but no notice
    web.pages[URL] = page("Report dry weather discharges to the hotline.", *BASE[:2], "Plant Tours",
                          "This site indicates when an overflow is likely, not that one has occurred.",
                          "CSO event likely Nov 3, 9:00 AM",
                          "Combined sewer overflows can occur during heavy rain. Updated November 3, 2026.")
    out = go(web, "2026-11-03T16:00:00Z")
    assert out["records"] == []
    assert out["snaps"][SHARED]["last_change_at"] is None                 # reorder and readings: unchanged
    ch = out["snaps"][URL]["changes"][-1]
    assert "Plant Tours" in ch["added"]
    # text that matches the previous snapshot is never read again, even with a date beside it elsewhere
    out2 = go(web, "2026-11-03T17:00:00Z")
    assert out2["records"] == [] and out2["snaps"][URL]["last_change_at"] == "2026-11-03T16:00:00Z"


def test_an_unreachable_page_is_recorded_and_keeps_its_last_snapshot(tmp_path):
    go = runner(tmp_path, [chan()])
    web = Web({URL: page(*BASE)})
    go(web, "2026-11-03T15:00:00Z")
    web.pages[URL] = 404
    out = go(web, "2026-11-03T16:00:00Z")
    s = out["snaps"][URL]
    assert s["last_fetch_ok"] is False and s["unreachable_since"] == "2026-11-03T16:00:00Z"
    assert s["last_ok"]["at"] == "2026-11-03T15:00:00Z" and "CSO Advisory System" in s["last_ok"]["lines"]
    web.pages[URL] = ConnectionError("timed out")
    out = go(web, "2026-11-04T16:00:00Z")
    s = out["snaps"][URL]
    assert s["unreachable_since"] == "2026-11-03T16:00:00Z" and s["last_ok"]["at"] == "2026-11-03T15:00:00Z"
    h = out["health"]["states"]["NJ"]["channels"][0]
    assert h["reachable"] is False and h["wording"] == "Notification page unreachable since Nov 3, 2026"
    assert [f[1] for f in s["fetches"]] == [True, False, False]
    # back up with the same text: reachable again, unchanged since the first copy
    web.pages[URL] = page(*BASE)
    out = go(web, "2026-11-05T16:00:00Z")
    h = out["health"]["states"]["NJ"]["channels"][0]
    assert h["reachable"] and h["wording"] == "Notification page unchanged since Nov 3, 2026"
    assert out["snaps"][URL]["unreachable_since"] is None and h["days_since_change"] == 2


def snap_of(lines, at="2026-11-03T15:00:00Z", ok=True, first=None, changed=None, down_since=None, entries=None):
    return {"first_fetch_at": first or at, "last_fetch_at": at, "last_fetch_ok": ok, "text_since": first or at,
            "last_change_at": changed, "unreachable_since": down_since, "entries": entries or {},
            "last_ok": {"at": first or at, "lines": lines, "lines_full": lines}}


def test_health_wording_for_each_state_of_a_page():
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    status = ["The outfall 040A into the Delaware River is CLOSED and discharges are unlikely to be occurring."]
    cases = [
        (chan(publishes="status", status_pattern=r"Delaware River is (?:OPEN|CLOSED)"), snap_of(status),
         "Publishes a current status", "status"),
        (chan(publishes="status", status_pattern=r"Delaware River is (?:OPEN|CLOSED)"),
         snap_of(["CSO Status", "Page under maintenance"], first="2026-11-05T15:00:00Z"),
         "No current status shown since Nov 5, 2026", "no_status"),
        (chan(publishes="link_only", link_text="the shared rainfall site"), snap_of(["CSO Notification System"]),
         "Links to the shared rainfall site only", "link_only"),
        (chan(channel_kind="shared_site", publishes="likelihood", link_text="the shared rainfall site",
              entry={"start": "NJ0020923", "end": r"NJ\d{7}"}), snap_of(["Town A NJ0020923", "CSO event unlikely"]),
         "Links to the shared rainfall site only", "link_only"),
        (chan(channel_kind="shared_site", publishes="likelihood", link_text="the shared rainfall site",
              entry={"start": "NJ0020923", "end": r"NJ\d{7}"}),
         snap_of(["Town B NJ0000001"], entries={"NJ0020923": {"found": False, "since": "2026-11-08T15:00:00Z"}}),
         "Not listed on the shared rainfall site since Nov 8, 2026", "entry_missing"),
        (chan(), snap_of(["CSO Advisory System"], first="2026-11-02T17:58:00Z"),
         "Notification page unchanged since Nov 2, 2026", "unchanged"),
        (chan(basis_kind="voluntary", legal_basis=None), snap_of(["Alerts"], first="2026-11-04T15:00:00Z"),
         "Voluntary page unchanged since Nov 4, 2026", "unchanged"),
        (chan(noun="Sensor map", publishes="status"),
         snap_of([], ok=False, down_since="2026-11-02T17:57:00Z"),
         "Sensor map unreachable since Nov 2, 2026", "status_unreachable"),
        (chan(basis_kind="voluntary", legal_basis=None), snap_of([], ok=False, down_since="2026-11-09T01:00:00Z"),
         "Voluntary page unreachable since Nov 8, 2026", "unreachable"),
        (chan(monitored=False, unmonitored_reason="none_found", urls=[], method=None, note="none"), None,
         "No notification page found", "none_found"),
        (chan(monitored=False, unmonitored_reason="bot_wall"), None,
         "Notification page behind a bot check; not read", "not_read"),
        (chan(monitored=False, unmonitored_reason="feed_ingested", feed_source_id="nj-beaches"), None,
         "Read as a feed", "feed"),
        (chan(), None, "Not checked yet", "not_checked"),
    ]
    for row, snap, wording, kind in cases:
        h = M.channel_health(row, {URL: snap} if snap else {}, now)
        assert (h["wording"], h["wording_kind"]) == (wording, kind), (row, h["wording"])
        assert "required" not in h["wording"].lower()
    # an operator carries its most telling channel's line
    hs = [M.channel_health(cases[2][0], {URL: cases[2][1]}, now),
          dict(M.channel_health(cases[7][0], {URL: cases[7][1]}, now), id="nj-map")]
    op = M.rollup(hs)
    assert len(op) == 1 and op[0]["wording"] == "Sensor map unreachable since Nov 2, 2026"


def test_new_jersey_seeds_stand_as_first_snapshots(tmp_path):
    if not (ROOT / "research" / "nj" / "raw").exists():
        pytest.skip("research/nj/raw/ (git-ignored seed copies) is not on this clone")
    doc = M.load_register()
    nj = [r for r in doc["channels"] if r["state"] == "NJ"]
    out = M.run(nj, now=datetime(2026, 11, 3, 13, tzinfo=UTC), save=False, fetch_pages=False, store=tmp_path)
    by = {o["operator_id"]: o for o in out["health"]["states"]["NJ"]["operators"] if o["operator_id"]}
    assert by["nj-ccmua"]["wording"] == "Publishes a current status"
    assert by["nj-nhsa-adams-street"]["wording"] == "Sensor map unreachable since Nov 2, 2026"
    assert by["nj-paterson"]["wording"] == "Links to the shared rainfall site only"
    assert by["nj-trenton"]["wording"] == "Notification page unchanged since Nov 2, 2026"
    assert by["nj-camden-city"]["wording"] == "No notification page found"
    ccmua = next(c for c in out["health"]["states"]["NJ"]["channels"] if c["id"] == "nj-ccmua-cso-status-page")
    assert ccmua["shown_text"].startswith("The 32nd Street CSO permitted outfall 040A")
    assert ccmua["shown_text"].endswith("is CLOSED and discharges are unlikely to be occurring.")
    paterson = next(c for c in out["health"]["states"]["NJ"]["channels"] if c["id"] == "nj-paterson-shared-site")
    assert paterson["shown_text"] == "CSO event unlikely" and paterson["publishes_status"] is False
    assert out["records"] == []


def test_dates_in_notices():
    ref = date(2026, 11, 3)
    got = [d for _, d in M.find_dates("Overflow 11/2/2026; Nov. 1, 2026; 2026-10-30; 8-26-2020; 2 November 2026; "
                                      "Oct 31 at 3 PM; Nov 2, 12:00 PM", ref)]
    assert got == [date(2026, 11, 2), date(2026, 11, 1), date(2026, 10, 30), date(2020, 8, 26), date(2026, 11, 2),
                   date(2026, 10, 31)]
    assert [d for _, d in M.find_dates("Dec 30", ref)] == [date(2025, 12, 30)]       # no year: the latest past one
    assert M.find_dates("call 201-963-6043", ref) == []


def test_coverage_carries_the_health_table_for_register_states_only(monkeypatch):
    from build import status as S
    from common import event
    from export import coverage as C
    monkeypatch.setattr(S, "_STATES", {"MA", "NJ"})
    feeds = [{"source_id": "ma-x", "registry_ids": ["r-ma"], "expected_cadence_hours": 6},
             {"source_id": "nj-x", "registry_ids": ["r-nj"], "expected_cadence_hours": 720}]
    reg = [{"id": "r-ma", "states": ["MA"], "event_types": ["cso"]}, {"id": "r-nj", "states": ["NJ"], "event_types": ["cso"]}]
    e = event(source_id="nj-x", source_record_id="1", event_type="cso", started_at="2026-10-01T00:00:00Z",
              time_precision="month")
    e["state"] = "NJ"
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    health = M.build_health([chan(), chan(id="nj-none", monitored=False, unmonitored_reason="none_found", urls=[],
                                          method=None, note="none", operator_id="nj-camden-city", permit="NJ0108812",
                                          name="City of Camden")], {}, now)
    base = C.coverage([e], [], feeds, reg, [], {}, "2026-11-10T12:00:00Z")
    got = C.coverage([e], [], feeds, reg, [], {}, "2026-11-10T12:00:00Z", notification_pages=health)
    np_ = got["states"]["NJ"]["notification_pages"]
    assert np_["built"] == health["built"] and np_["counts"]["channels"] == 2
    assert [o["wording"] for o in np_["operators"]] == ["No notification page found", "Not checked yet"]
    assert "notification_pages" not in got["states"]["MA"] and got["states"]["MA"] == base["states"]["MA"]
    assert {k: v for k, v in got["states"]["NJ"].items() if k != "notification_pages"} == base["states"]["NJ"]
