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
