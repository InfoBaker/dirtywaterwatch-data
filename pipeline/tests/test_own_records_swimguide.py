"""Corrections to our own records found by the Swim Guide review (2026-11-21), each checked against the source.

- Michigan: EGLE's beach map export is public without a login (trimmed real fixture of report 2082); the register,
  the research row, the profile and the state text no longer say a login stands in the way.
- Louisiana: LDH's beach layer is open and its page answers a browser's user agent; the register no longer records a
  bot wall, and the generic ArcGIS reader reads the layer with a fetch block only (trimmed real fixture).
- Georgia: Valdosta publishes river results and spill-testing pages: a channel of its own, watched standing.
- Texas: texasbeachwatch.com redirected to GLO's home page during GLO's announced weekend maintenance; the citation
  stays.
"""
import csv
import io
import json
import re
from pathlib import Path

import yaml

from ingest import notification_pages as NP
from ingest.generic import runner as R

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
REG = NP.load_register(ROOT / "data" / "notice-channels")
LA_LAYER = "https://services5.arcgis.com/O5K6bb5dZVZcTo5M/arcgis/rest/services/BEACH_ADVISORY_STATUS/FeatureServer/0"


def channel(cid):
    rows = [r for r in REG["channels"] if r["id"] == cid]
    assert len(rows) == 1, cid
    return rows[0]


def research(st, sid):
    rows = [r for r in json.loads((ROOT / "research" / st / "sources.json").read_text()) if r["id"] == sid]
    assert len(rows) == 1, sid
    return rows[0]


def test_register_is_valid():
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    assert NP.validate_register(REG, dis, ROOT) == []


# ---------------------------------------------------------------- Michigan

def test_michigan_export_carries_dates_type_and_reason_without_a_login():
    rows = list(csv.DictReader(io.StringIO((FIX / "mi_egle_beach_advisories_2082.csv").read_text())))
    assert {"StartDate", "EndDate", "AdvisoryType", "Reason", "PollutionSource", "Name", "Identifier"} <= set(rows[0])
    sewage = next(r for r in rows if r["Reason"] == "Sewage")
    assert sewage["Name"] == "L'Anse Waterfront Park" and sewage["PollutionSource"] == "Combined Sewer Overflow"
    assert sewage["StartDate"].startswith("6/25/2026") and sewage["EndDate"].startswith("7/1/2026")
    assert all(not r["AdvisoryComments"] for r in rows)          # free text is never kept, fixture included


def test_michigan_beachguard_row_has_no_login_barrier():
    r = channel("mi-egle-beachguard")
    assert r["barrier"] is None and r["unmonitored_reason"] is None and r["monitored"] is True
    assert r["urls"] == ["https://mienviro.michigan.gov/nsite/beach/map/"] and r["availability_only"] is True
    assert "2082" in r["note"] and "without a login" in r["note"] and r["checked"] == "2026-11-21"
    s = research("mi", "mi-egle-beachguard")
    assert s["status"] == "candidate" and "csv" in s["access"] and "need login" not in s["access_detail"]
    prof = json.loads((ROOT / "research" / "mi" / "profile.json").read_text())
    assert not [b for b in prof["barriers"] if b["kind"] == "login" and "BeachGuard" in b["what"]]
    y = yaml.safe_load((ROOT / "data" / "sources" / "mi-egle-beachguard.yaml").read_text())
    assert "csv" in y["access"] and "explorersiteexports" in y["access_detail"]
    text = (ROOT / "research" / "mi" / "state-text.md").read_text()
    assert "has not been verified" not in text and "export gives each one's dates, type and reason" in text


# ---------------------------------------------------------------- Louisiana

def la_block():
    return {
        "platform": "arcgis", "live": False, "url": LA_LAYER, "order_by": "ObjectId", "time_zone": "America/Chicago",
        "bounds": [-94.1, 28.8, -88.8, 31.1],
        "safe_fields": ["ObjectId", "STATE_ID", "BEACH_NAME", "LAT", "LONG", "STATUS", "ADVISORY_REASON",
                        "SAMPLE_DATE", "TIME_SAMPL", "ENTEROCOCCI", "GEO_MEAN"],
        "reviewed_fields": {"BEACH_NAME": "the beach's name ('LAKE CHARLES NORTH BEACH'), never a person"},
        "filter": [{"field": "STATUS", "regex": "^\\s*ADVISORY\\s*$"}],
        "record": {
            "source_record_id": {"template": "{STATE_ID|upper}-{@started_at|compact}"},
            "started_at": {"field": "SAMPLE_DATE", "parse": "date", "formats": ["%m/%d/%Y"]},
            "event_type": {"const": "beach_advisory"},
            "status": {"field": "STATUS", "upper": True, "map": {"ADVISORY": "advisory_active"}},
            "lat": {"field": "LAT", "parse": "number"}, "lon": {"field": "LONG", "parse": "number"},
            "outfall_name": "BEACH_NAME",
            "authority": {"const": "Louisiana Department of Health (Beach Monitoring Program)"},
            "source_url": {"const": "https://ldh.la.gov/page/beach-monitoring-program"},
        },
        "raw_notes": {"_advisory_reason": {"field": "ADVISORY_REASON"}},
        "dedupe": {"repeats": "first"},
        "history": {"keep_missing": True, "confirm_while_listed": True},
        "meta": {"credit": "Louisiana Department of Health, Beach Monitoring Program"},
    }


def test_louisiana_layer_reads_with_a_fetch_block_only():
    block = la_block()
    assert R.validate_block(block, "la-ldh-beach-monitoring") == []
    rows = R.platform("arcgis").parse(block, (FIX / "la_ldh_beach_advisory_status.json").read_bytes())
    recs, stats = R.build("la-ldh-beach-monitoring", block, rows, "2026-11-21T15:00:00Z", (), None)
    assert stats["rows"] == 3 and len(recs) == 1                     # NO ADVISORY rows make no record
    r = recs[0]
    assert r["source_record_id"] == "LCNB1-20261020" and r["status"] == "advisory_active"
    assert r["time_precision"] == "day" and r["lat"] == 30.23583 and r["outfall_name"] == "LAKE CHARLES NORTH BEACH"
    assert r["raw"]["_advisory_reason"] == "Geometric Mean + Single Sample"
    assert r["raw"]["_last_seen_in_source"] == "2026-11-21T15:00:00Z"


def test_louisiana_rows_record_no_bot_wall():
    r = channel("la-ldh-beach-monitoring")
    assert r["barrier"] is None and r["monitored"] is True and r["method"] == "json"
    assert r["urls"][0].startswith(LA_LAYER) and "browser" in r["note"] and "44913220623" in r["note"]
    h = channel("la-ldh-hab-advisories")
    assert h["barrier"] != "bot_wall" and h["unmonitored_reason"] != "bot_wall"
    for sid in ("la-ldh-beach-monitoring", "la-ldh-beach-alternate"):
        assert research("la", sid)["status"] == "candidate"
    text = (ROOT / "research" / "la" / "state-text.md").read_text()
    assert "refuse automated reading" not in text and "We do not yet collect the Department of Health's" in text


# ---------------------------------------------------------------- Georgia

def test_valdosta_has_a_watched_channel_for_its_results_and_spill_testing():
    r = channel("ga-valdosta-river-water-quality")
    assert r["monitored"] is True and r["barrier"] is None and r["records"] is False
    assert r["urls"][0] == "https://www.valdostacity.com/utilities/river-stream-water-quality-monitoring"
    assert re.search(r"Covers: ga-ga0020222, ga-ga0033235\.$", r["note"])
    for op in ("ga-ga0020222", "ga-ga0033235"):
        assert "No web channel found." not in channel(f"{op}-health-department")["note"]
    assert research("ga", "ga-valdosta-river-water-quality")["status"] == "candidate"


# ---------------------------------------------------------------- Texas

def test_texas_beach_watch_keeps_its_citation_through_the_outage():
    y = yaml.safe_load((ROOT / "data" / "sources" / "tx-glo-beach-watch.yaml").read_text())
    assert y["fetch"]["record"]["source_url"] == {"const": "https://www.texasbeachwatch.com/"}
    raw = (ROOT / "data" / "sources" / "tx-glo-beach-watch.yaml").read_text()
    assert "Checked 2026-11-21" in raw and "maintenance" in raw
