"""Idaho rows of the notice register (data/notice-channels/id.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_id_register_rows.py [--dry-run]

The law: Idaho's IPDES permits (IDAPA 58.01.25; West Boise's permit, sections 2.2.7 and 2.2.8, read in the research)
require noncompliance that may endanger health, collection-system overflows included, to be reported to DEQ by
telephone within 24 hours and electronically within five days, and an affected MS4 operator told; an emergency plan
names the health district and other officials to be told at once. No statute, rule or permit clause found requires
the public to be told, and DEQ publishes no list of the reports. EPA Region 10's permits in Indian country report to
EPA. EPA's overflow tables hold one Idaho report (2023, a basement backup).

Rows
  - Per operator: <id>-noncompliance-report (permit basis), no web channel (the reports are not public).
  - Agency rows (AGENCY): DEQ's CyanoHAB Risk Data Table (feed_ingested), DHW's recreational water advisories map
    (feed_ingested for its points), DHW's news releases (health advisories, not read), DEQ's HAB e-mail list, DEQ's
    noncompliance reports and the IPDES E-Permitting portal (login), EPA's overflow tables.
A rerun replaces every id- row it makes. Validated before writing.
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
Q_PERMIT = ("NPDES permit {permit} ({who}): noncompliance that may endanger health, collection-system overflows "
            "included, reported to the permitting authority by telephone within 24 hours and in writing within five "
            "days (40 CFR 122.41(l)(6); IDAPA 58.01.25 for DEQ's permits; permit text read for West Boise only)")
CYANO = "https://www.deq.idaho.gov/water-quality/surface-water/cyanobacteria-harmful-algal-blooms/"
DHW_MAP = "https://www.gethealthy.dhw.idaho.gov/recreational-water-health-advisories"
AGENCY = [
    {"id": "id-deq-cyanohab-risk-table", "agency": "Idaho Department of Environmental Quality",
     "name": "Idaho DEQ (CyanoHAB Risk Data Table)", "channel_kind": "state_alert_page", "urls": [CYANO],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "id-deq-cyanohab-risk-table", "publishes": "notices",
     "noun": "Bloom risk table", "sources": ["id-deq-cyanohab-risk-table"],
     "note": ("DEQ's table of waters with a cyanobacteria Health Watch, Health Alert or Health Advisory, with county, "
              "data type and collection date (19 rows on 2026-11-14). Read by the feed. Blooms, not sewage.")},
    {"id": "id-dhw-recreational-advisories", "agency": "Idaho Department of Health and Welfare",
     "name": "Idaho DHW (Recreational Water Health Advisories map)", "channel_kind": "state_alert_page",
     "urls": [DHW_MAP], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "id-deq-cyanohab-risk-table", "publishes": "notices",
     "noun": "Advisories map", "sources": ["id-dhw-recreational-advisories"],
     "note": ("DHW's map of the same bloom advisories with a point per water; its layer's safe fields (water, risk tier, "
              "point) are read by the feed to place DEQ's rows. Staff and contact fields are never requested.")},
    {"id": "id-dhw-news-health-advisories", "agency": "Idaho Department of Health and Welfare",
     "name": "Idaho DHW (news releases)", "channel_kind": "news_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "notices", "records": False, "noun": "News releases", "sources": ["id-deq-cyanohab-risk-table"],
     "barrier_review": "the issue and lift dates of bloom health advisories are in DHW's press releases, not yet read",
     "note": ("DEQ: \"Health Advisories are issued as a press release through the DHW News webpage\"; not read (the "
              "table carries each advisory, without its issue date).")},
    {"id": "id-deq-hab-email-list", "agency": "Idaho Department of Environmental Quality",
     "name": "Idaho DEQ (HABs e-mail list)", "channel_kind": "email_list", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "records": False, "noun": "E-mail list", "sources": ["id-deq-cyanohab-risk-table"],
     "note": "DEQ's subscription list for bloom updates, sent by e-mail to subscribers."},
    {"id": "id-deq-noncompliance-reports", "agency": "Idaho Department of Environmental Quality",
     "name": "Idaho DEQ (IPDES noncompliance reports)", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": "IDAPA 58.01.25; IPDES permit conditions (24-hour and five-day reports)",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False, "noun": "Report to the state", "sources": ["id-deq-ipdes-noncompliance"],
     "note": ("No web channel found: every IPDES permittee reports overflows and other noncompliance to DEQ within 24 "
              "hours and in five days; DEQ publishes no list of the reports, and no rule requires the public to be "
              "told.")},
    {"id": "id-ipdes-e-permitting", "agency": "Idaho Department of Environmental Quality",
     "name": "Idaho DEQ (IPDES E-Permitting)", "channel_kind": "state_alert_page",
     "urls": ["https://apps-deq.idaho.gov/water/ipdes"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "login", "publishes": "documents",
     "records": False, "noun": "Permit portal", "sources": ["id-ipdes-reporting-portal"],
     "note": "The reporting portal where permittees file; its submissions are behind a login."},
    {"id": "id-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "EPA sewer overflow and bypass tables (Idaho)", "channel_kind": "feed", "urls": [], "method": None,
     "legal_basis": "40 CFR part 127 (NPDES electronic reporting)", "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False, "noun": "EPA overflow tables",
     "sources": ["id-epa-sobe"],
     "note": ("No web channel found for Idaho's current reports: EPA's overflow tables (extract of 2026-11-12) hold one "
              "Idaho report, Kamiah's 5-gallon basement backup of December 2023, which is no discharge to water.")},
]


def base(**kw) -> dict:
    r = {"state": "ID", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "ID":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        auth = op.get("permitting_authority") or ["unconfirmed"]
        who = {"IDEQ": "Idaho DEQ, IPDES", "EPA": "EPA Region 10"}.get(auth[0], "issuer not confirmed") \
            if len(auth) == 1 else "issuers DEQ and not confirmed"
        to = "EPA Region 10" if auth == ["EPA"] else "DEQ"
        rows.append(finish(base(
            id=f"{oid}-noncompliance-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=Q_PERMIT.format(permit=permit, who=who), basis_kind="permit",
            monitored=False, unmonitored_reason="none_found", publishes="none", records=False,
            noun="Report to the permitting authority", sources=["id-deq-ipdes-noncompliance"],
            note=(f"No web channel found: {name} reports overflows and other noncompliance to {to} within 24 hours and "
                  "in five days; the reports are not published, and no public notice requirement was found."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "ID")
    doc = merge(doc, rows, drop)
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        NP.save_register(doc["channels"], REGISTER)
    return {"rows": len(rows),
            "barriers": dict(Counter(r["barrier"] or ("review" if r.get("barrier_review") else "none") for r in rows)),
            "by_basis": dict(Counter(r["basis_kind"] for r in rows))}


if __name__ == "__main__":
    print(json.dumps(run("--dry-run" in sys.argv[1:]), indent=1))
