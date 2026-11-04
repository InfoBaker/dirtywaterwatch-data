"""docs/source-checklist.json says what is true of the feeds: a research row a feed reads is "used" (Georgia's were
still "candidate" or "watch" after the feeds were built; GA checklist P2-5). Checked for the states of the second
wave; the older states' rows are listed in the coordinator's report, not changed here."""
import glob
import json
import re

from common import ROOT

CHECKLIST = {r["id"]: r for r in json.loads((ROOT / "docs" / "source-checklist.json").read_text())}
AREAS = {"nc", "ga", "fl"}


def feed_registry_ids() -> dict[str, str]:
    out = {}
    for f in glob.glob(str(ROOT / "data" / "sources" / "*.yaml")):
        m = re.search(r"^registry_ids: (\[.*\])", open(f).read(), re.M)
        for i in json.loads(m.group(1)) if m else []:
            out[i] = f.rsplit("/", 1)[-1]
    return out


def test_every_research_row_a_feed_reads_is_used():
    stale = [(i, f, CHECKLIST[i]["status"]) for i, f in feed_registry_ids().items()
             if i in CHECKLIST and CHECKLIST[i]["area"] in AREAS and CHECKLIST[i]["status"] != "used"]
    assert stale == []


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
