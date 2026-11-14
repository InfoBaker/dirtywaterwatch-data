"""docs/source-checklist.json says what is true of the feeds: a research row a feed reads is "used" (Georgia's were
still "candidate" or "watch" after the feeds were built; GA checklist P2-5). Checked for every area, so a live state's
rows cannot go stale again (23 rows in DC, NJ, NY, PA and VA had; register-gaps review, "Finding for later"). A feed
that is a stub and reads nothing is the one exception: its row keeps the research status."""
import glob
import json
import re

from common import ROOT

CHECKLIST = {r["id"]: r for r in json.loads((ROOT / "docs" / "source-checklist.json").read_text())}
# Feeds that fetch nothing (the module says so in its meta); their research rows are not read, so not "used".
STUB_FEEDS = {"pa-crw.yaml": ("pa_crw.py", "pa-crw-cso-advisory-status")}


def feed_registry_ids() -> dict[str, str]:
    """Research id -> the feed row's file, for every feed row: its registry_ids, or (North Carolina's feed rows took
    the research id as their own) the row's id when it names none."""
    out = {}
    for f in glob.glob(str(ROOT / "data" / "sources" / "*.yaml")):
        text = open(f).read()
        m = re.search(r"^registry_ids: (\[.*\])", text, re.M)
        ids = json.loads(m.group(1)) if m else []
        if not m and (text.startswith("# Feed row") or "\n# Feed row" in text or re.search(r"^fetch:", text, re.M)):
            ids = re.findall(r'^id: "(.*)"', text, re.M)
        for i in ids:
            out[i] = f.rsplit("/", 1)[-1]
    return out


def research_rows() -> dict[str, dict]:
    out = {}
    for f in sorted(glob.glob(str(ROOT / "research" / "*" / "sources.json"))):
        for r in json.loads(open(f).read()):
            out.setdefault(r["id"], r)
    return out


def test_every_research_row_a_feed_reads_is_used():
    feeds = {i: f for i, f in feed_registry_ids().items() if f not in STUB_FEEDS}
    stale = [(i, f, CHECKLIST[i]["status"]) for i, f in feeds.items() if i in CHECKLIST and CHECKLIST[i]["status"] != "used"]
    assert stale == []
    research = research_rows()
    stale = [(i, f, research[i]["status"]) for i, f in feeds.items() if i in research and research[i]["status"] != "used"]
    assert stale == []


def test_the_check_covers_every_live_state():
    """Each live state's feeds name research rows, so the check above reaches every one of them."""
    areas = {CHECKLIST[i]["area"] for i in feed_registry_ids() if i in CHECKLIST}
    assert {"dc", "nj", "ny", "pa", "va", "nc", "ga", "fl", "md"} <= areas


def test_a_stub_feed_reads_nothing_and_its_row_is_not_used():
    """Capital Region Water's licence bars republishing without written permission, so pa_crw.py fetches nothing;
    when it is built the stub entry goes and the row must turn "used"."""
    for yaml, (module, rid) in STUB_FEEDS.items():
        assert '"stub": True' in (ROOT / "pipeline" / "ingest" / module).read_text(), module
        assert feed_registry_ids()[rid] == yaml
        assert CHECKLIST[rid]["status"] != "used"
        assert research_rows()[rid]["status"] == CHECKLIST[rid]["status"]


def test_stub_file_is_not_successful_collection_or_source_coverage(tmp_path):
    """A placeholder's run time must not appear as a successful check of the original source."""
    from build.status import load_events
    from ingest.pa_crw import META

    stamp = "2026-11-09T12:00:00Z"
    for sid, meta in [("pa-crw", META), ("ordinary-empty-feed", {})]:
        (tmp_path / f"{sid}.json").write_text(json.dumps({
            "source_id": sid, "fetched_at": stamp, "last_ok_at": stamp, "ok": True,
            "count": 0, "records": [], "meta": meta,
        }))
    for include_restricted in (False, True):
        feeds, events, problems = load_events(tmp_path, include_restricted=include_restricted)
        assert set(feeds) == {"ordinary-empty-feed"}
        assert feeds["ordinary-empty-feed"]["last_ok_at"] == stamp
        assert events == [] and problems == []


def test_harrisburg_status_page_is_health_only_not_an_ingested_feed(tmp_path):
    from datetime import UTC, datetime
    from ingest.notification_pages import load_register, run
    from export.coverage import notice_reach

    row = next(r for r in load_register()["channels"] if r["id"] == "pa-pa0027197-public-notification")
    assert row["monitored"] and row["method"] == "html"
    assert row["records"] is False
    assert row["availability_only"] is True
    assert row["unmonitored_reason"] is None and not row.get("feed_source_id")
    # The monitored HTML page links to the app. A successful fetch of generic information must not
    # count as observing a current CSO status from that app.
    result = run([row], now=datetime(2026, 11, 9, 12, tzinfo=UTC), store=tmp_path, save=False,
                 fetcher=lambda url, browser: {
                     "at": "2026-11-09T12:00:00Z", "ok": True, "http_status": 200,
                     "body": b"<html><body>Welcome. General information only.</body></html>",
                 })
    health = result["health"]["states"]["PA"]
    assert health["channels"][0]["reachable"] is True
    assert health["channels"][0]["publishes_status"] is False
    assert health["channels"][0]["wording"] == "Page reachable; status data not checked"
    assert health["channels"][0]["wording_kind"] == "not_checked"
    assert health["counts"]["publishing_status"] == 0
    assert health["operators"][0]["publishes_status"] is False
    assert health["operators"][0]["wording_kind"] == "not_checked"
    assert result["records"] == [] and result["stats"]["records_new"] == 0
    # Availability-only monitoring does not erase the researched fact that a public status source exists.
    reach = notice_reach({"channels": [row]})["PA"]["told_online"]
    assert reach["classes"]["online"] == [row["operator_id"]] and reach["online"] == 1
    down = run([row], now=datetime(2026, 11, 9, 13, tzinfo=UTC), store=tmp_path, save=False,
               fetcher=lambda url, browser: {
                   "at": "2026-11-09T13:00:00Z", "ok": False, "http_status": 503, "body": b"Unavailable",
               })["health"]["states"]["PA"]["channels"][0]
    assert down["reachable"] is False and down["publishes_status"] is False
    assert down["wording_kind"] == "status_unreachable" and "unreachable since" in down["wording"]


def test_nashville_candidate_reports_are_registered_without_event_ingestion(monkeypatch):
    import yaml
    from ingest.notification_pages import load_register

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from add_tn_register_rows import rows_for

    sid = "tn-clean-water-nashville"
    ops = json.loads((ROOT / "data" / "dischargers.json").read_text())
    regenerated = {r["id"]: r for r in rows_for(ops)}
    rows = {r["id"]: r for r in load_register()["channels"]}
    ids = [sid, "tn-metro-water-services-cso-notice", "tn-metro-water-services-public-notice"]
    assert all(rows[i] == regenerated[i] for i in ids)
    assert rows[sid]["urls"] == ["https://www.cleanwaternashville.org/monthly-regulatory-reports"]
    assert rows[sid]["monitored"] and rows[sid]["records"] is False
    source = yaml.safe_load((ROOT / "data" / "sources" / f"{sid}.yaml").read_text())
    assert not source.get("fetch")
    assert source["url"] == rows[sid]["urls"][0]
    assert CHECKLIST[sid]["status"] == research_rows()[sid]["status"] == "candidate"


def test_the_rows_the_register_gaps_review_found_stale_are_used():
    want = ["dc-dcwater-news-notices", "nj-njcso-group-interim-outlook", "nj-echo-effluent-dmr-cso",
            "nj-njdep-hab-dashboard", "ny-dec-sprtk-page-recent-alerts", "nyc-dep-waterbody-advisory-api",
            "nyc-dep-arcgis-advisory-layers", "ny-oprhp-beach-water-testing-wwwd-za77", "ny-parks-beach-results-page",
            "ny-dec-hab-current-reports", "pa-alcosan-soak-log", "pa-pwd-csocast", "pa-erie-cso-monitoring",
            "pa-alcosan-news-advisories", "pa-erie-county-beach-mymaps", "pa-doh-habs-dashboard", "va-deq-prep-api",
            "va-deq-prep-export-mapserver", "va-deq-edma-prep-daily-points", "va-richmond-monthly-cso-xlsx",
            "va-alexrenew-cso-status-layer", "va-vdh-news-advisory-feed"]
    assert {CHECKLIST[i]["status"] for i in want} == {"used"}


def test_georgia_statuses():
    want = {"ga-epd-sewage-spills-report": "used", "ga-epd-spills-map-layer": "used", "ga-epa-sobe": "used",
            "ga-dnr-healthy-beaches": "used", "ga-wwals-archive": "watch"}
    assert {i: CHECKLIST[i]["status"] for i in want} == want
    research = {r["id"]: r for r in json.loads((ROOT / "research" / "ga" / "sources.json").read_text())}
    assert {i: research[i]["status"] for i in want} == want


def test_a_beach_feeds_registry_row_names_the_event_type_the_feed_writes():
    """ga-dnr-beaches writes beach_advisory records; its registry row (ga-dnr-healthy-beaches) said no event type, so
    the sources' event types for Georgia's beach feed came out empty (Florida's counterpart names beach_advisory)."""
    for rid in ("ga-dnr-healthy-beaches", "fl-doh-healthy-beaches"):
        text = (ROOT / "data" / "sources" / f"{rid}.yaml").read_text()
        assert re.search(r'^event_types: \["beach_advisory"\]', text, re.M), rid
        assert CHECKLIST[rid]["event_types"] == ["beach_advisory"]
