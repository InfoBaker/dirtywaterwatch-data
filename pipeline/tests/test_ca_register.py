"""California rows of the notice register (scripts/add_ca_register_rows.py, data/notice-channels/ca.json) and the
barrier read from a hotline-only note. Run from pipeline/: python -m pytest tests/test_ca_register.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest import notification_pages as NP

ROOT = Path(__file__).resolve().parents[2]


def test_a_hotline_only_channel_is_phone_only():
    r = {"monitored": False, "unmonitored_reason": "other", "channel_kind": "local_health_page",
         "note": "The public channel the law names is a telephone hotline in each county: hotline only."}
    assert NP.barrier_for(r) == ("phone_only", None)


def test_every_california_operator_has_its_health_officer_row_and_no_report_to_the_regulator_is_a_channel():
    path = ROOT / "data" / "notice-channels" / "ca.json"
    if not path.exists():
        return
    chans = json.loads(path.read_text())["channels"]
    ids = {c["id"] for c in chans}
    ops = [d for d in json.loads((ROOT / "data" / "dischargers.json").read_text()) if d.get("state") == "CA"]
    assert all(f"{d['id']}-health-officer-notice" in ids for d in ops)
    # review 2026-11-04 P2-3: the NPDES noncompliance report (40 CFR 122.41(l)(6)) goes to the Regional Board, never to
    # the public: it is no channel the public is told through, so it has no row
    assert not [c["id"] for c in chans if "122.41" in (c.get("legal_basis") or "") or "noncompliance-report" in c["id"]]
    assert len(chans) == len(ops) + 22
    feed = next(c for c in chans if c["id"] == "ca-swrcb-ciwqs-spill-file")
    assert feed["basis_kind"] == "law" and feed["feed_source_id"] == "ca-swrcb-ciwqs-spills-flatfile"
    assert next(c for c in chans if c["id"] == "ca-county-health-beach-hotlines")["barrier"] == "phone_only"
    assert [c["id"] for c in chans] == sorted(c["id"] for c in chans)
