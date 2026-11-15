"""Wyoming rows of the notice register (data/notice-channels/wy.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_wy_register_rows.py [--dry-run]

The law (research/wy/sources.json wy-deq-sso-page; research/wy/expansion-research.md):
  - WDEQ's Sanitary Sewer Overflows page (WYPDES program, read 2026-11-14): the owner or operator of a collection
    system or treatment works reports an SSO to WDEQ verbally within 24 hours of becoming aware of it and in writing
    within five days. No public notification duty found; WDEQ publishes no list; its spill system's search needs a login.
  - EPA Region 8 issues the permits on the Wind River Reservation (WYG589 lagoon general permit): their reports go to EPA.
Rows
  - Per operator: <id>-deq-report (the report to WDEQ, not published: no web page), or <id>-epa-report.
  - Statewide: the HCB bulletins (read: wy-deq-hcb-bulletins), the HCB program page, the current-advisory StoryMap, the
    historical HCB layer, the Department of Health's HCB posts, WDEQ's SSO reports and page, the spill system (login),
    the 2024 Hudson notices (HTTP 500), EPA's overflow tables (no Wyoming report), Swim Guide.
A rerun replaces every wy- row it makes. Validated before writing.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts"))
from add_register_rows import finish, merge  # noqa: E402
from ingest import notification_pages as NP  # noqa: E402

REGISTER = ROOT / "data" / "notice-channels"
DIS = ROOT / "data" / "dischargers.json"
CHECKED = "2026-11-14"
ST = "WY"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
Q_LAW = ("WDEQ, Sanitary Sewer Overflows (WYPDES program page): \"Reporting of the SSO should occur verbally within 24 "
         "hours of becoming aware of the event\"; written notification to WDEQ within five days after the event")
Q_EPA = ("NPDES permit {permit} (EPA Region 8, Wind River Reservation): the 24-hour and five-day noncompliance reports of "
         "40 CFR 122.41(l)(6), to EPA")
HCB = "https://deq.wyoming.gov/water-quality/watershed-protection/cyanobacteria/"

AGENCY = [
    {"id": "wy-deq-hcb-bulletins", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming Department of Environmental Quality (harmful cyanobacteria bloom bulletins)", "channel_kind": "feed",
     "urls": ["https://public.govdelivery.com/topics/WYDEQ_42/feed.rss"], "method": "rss", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "wy-deq-hcb-bulletins", "publishes": "notices", "noun": "Data feed",
     "note": ("WDEQ's public bulletin topic, issued with the Department of Health: each bulletin carries the table of "
              "current bloom and toxin advisories (water, location, type, date issued), and a lift has its own "
              "bulletin. 25 bulletins from 2026-07-31 to 2026-10-28 on 2026-11-15; read by the wy-deq-hcb-bulletins "
              "feed (71 advisories)."),
     "sources": ["wy-deq-hcb-bulletins"]},
    {"id": "wy-deq-hcb-page", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (harmful cyanobacteria blooms program page)", "channel_kind": "state_alert_page",
     "urls": [HCB], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True,
     "unmonitored_reason": None, "publishes": "link_only", "link_text": "the current advisories StoryMap",
     "records": False, "availability_only": True, "every_hours": 168,
     "note": ("The program page and its FAQ: an advisory holds until the bloom has dissipated or toxins are below the "
              "recreational levels, or December 31, whichever comes first."),
     "sources": ["wy-deq-hcb-current"]},
    {"id": "wy-deq-hcb-storymap", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (current HCB advisories StoryMap)", "channel_kind": "state_alert_page",
     "urls": ["https://storymaps.arcgis.com/stories/5449617036994efa8c227df3c97be27b"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "the current bloom and toxin advisory lists", "records": False,
     "availability_only": True, "every_hours": 168,
     "note": ("A script page with the current Bloom Advisory, Toxin Advisory and Under Investigation lists; its rows "
              "match the bulletins' table, which is read (wy-deq-hcb-bulletins). The Under Investigation list is not "
              "in the bulletins and is not read."),
     "sources": ["wy-deq-hcb-current"]},
    {"id": "wy-deq-hcb-history-layer", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (past HCB advisories layer)", "channel_kind": "feed",
     "urls": ["https://services6.arcgis.com/TtxLb6QYNGSSARuk/arcgis/rest/services/WDEQ_ALL_Past_HCB_Advisories/FeatureServer/1"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "availability_only": True, "every_hours": 168, "noun": "Data feed",
     "note": ("78 waters with per-year columns of the advisories issued (layer metadata and count read 2026-11-14; "
              "last data edit 2025-06-17). Not read for records in this build: channel not researched beyond its "
              "metadata. Watched."),
     "sources": ["wy-deq-hcb-advisories-layer"]},
    {"id": "wy-wdh-hcb", "agency": "Wyoming Department of Health",
     "name": "Wyoming Department of Health (HCB posts)", "channel_kind": "state_alert_page",
     "urls": ["https://health.wyo.gov/tag/hcbs/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "link_only", "link_text": "WDEQ's HCB advisories",
     "records": False, "availability_only": True, "every_hours": 168,
     "note": "The Department of Health issues the advisories with WDEQ; its posts repeat the bulletins.",
     "sources": ["wy-wdh-hcb"]},
    {"id": "wy-deq-sso-reports", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (sanitary sewer overflow reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_LAW, "basis_kind": "permit", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("No web channel found: operators report an overflow to WDEQ by telephone within 24 hours and in writing "
              "within five days; WDEQ publishes none of them. A redacted export is a records request to WDEQ; none "
              "has been sent."),
     "sources": ["wy-deq-sso-page"]},
    {"id": "wy-deq-sso-page", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (Sanitary Sewer Overflows, WYPDES)", "channel_kind": "state_alert_page",
     "urls": ["https://deq.wyoming.gov/water-quality/wypdes/sanitary-sewer-overflows/"], "method": "html",
     "legal_basis": Q_LAW, "basis_kind": "permit", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "availability_only": True, "every_hours": 168,
     "note": "The page that sets the 24-hour verbal and five-day written report; watched for a change.",
     "sources": ["wy-deq-sso-page"]},
    {"id": "wy-deq-spills", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (spill reporting system)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "login", "publishes": "none", "records": False,
     "note": ("deqspills.wyo.gov: the public side is a report form; its incident search needs a login (a script shell "
              "to the build's client, 2026-11-14)."),
     "sources": ["wy-deq-spills-portal"]},
    {"id": "wy-deq-hudson-2024", "agency": "Wyoming Department of Environmental Quality",
     "name": "Wyoming DEQ (news: Hudson wastewater release, June 2024)", "channel_kind": "news_page",
     "urls": ["https://deq.wyoming.gov/2024/06/the-department-of-environmental-quality-provides-update-on-hudson-wastewater-release/"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 168,
     "note": ("WDEQ's June 2024 updates on the Hudson wastewater release (expansion research). Not ingested: the pages "
              "answered HTTP 500 to the build's client on 2026-11-14; watched so the refresh records when they answer."),
     "sources": ["wy-deq-hudson-2024"]},
    {"id": "wy-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168, "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables hold no Wyoming report in the current or the all-versions extract "
              "of 2026-11-14; the collection-system table lists one Wyoming permit, EPA's lagoon coverage WYG589101. "
              "Watched for Wyoming rows."),
     "sources": ["wy-epa-sobe"]},
    {"id": "wy-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish (Swim Guide)",
     "channel_kind": "swim_guide", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "No Wyoming beach bacteria program or Swim Guide affiliate found (research, search only).",
     "sources": ["wy-beach-ecoli"]},
]


def base(**kw) -> dict:
    r = {"state": ST, "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != ST or "wy" not in (op.get("source_areas") or []):
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        epa = op.get("epa_issued_permits") or []
        if epa and len(epa) == len(ps):
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=epa[0], channel_kind="state_alert_page",
                urls=[], method=None, legal_basis=Q_EPA.format(permit=epa[0]), basis_kind="permit", monitored=False,
                unmonitored_reason="other", publishes="none", records=False, noun="EPA report",
                sources=["wy-epa-sobe"],
                note=(f"No web channel found: {name}'s permit is EPA's (Wind River Reservation), so its noncompliance "
                      "reports go to EPA Region 8, which publishes those filed electronically in its overflow tables "
                      "(none for Wyoming in the extracts of 2026-11-14)."))))
            continue
        rows.append(finish(base(
            id=f"{oid}-deq-report", operator_id=oid, name=name, permit=None, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=Q_LAW, basis_kind="permit", monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=["wy-deq-sso-page"],
            note=(f"No web channel found: {name} reports an overflow to WDEQ verbally within 24 hours and in writing "
                  "within five days; WDEQ publishes no list (wy-deq-sso-reports), and no duty to tell the public was "
                  "found. Its own web channel was not searched individually."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == ST)
    doc = merge(doc, rows, drop)
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        NP.save_register(doc["channels"], REGISTER)
    return {"rows": len(rows),
            "barriers": dict(Counter(r["barrier"] or ("review" if r.get("barrier_review") else "none") for r in rows)),
            "by_basis": dict(Counter(r["basis_kind"] for r in rows)),
            "monitored": sum(1 for r in rows if r["monitored"])}


if __name__ == "__main__":
    print(json.dumps(run("--dry-run" in sys.argv[1:]), indent=1))
