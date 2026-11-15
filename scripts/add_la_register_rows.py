"""Louisiana rows of the notice register (data/notice-channels/la.json), made from the law and data/dischargers.json.

Usage: pipeline/.venv/bin/python -I scripts/add_la_register_rows.py [--dry-run]

The law (research/la/report.md §2.1 in the site repository; research/la/expansion-research.md; LDEQ's Single Point of
Contact page, read 2026-11-14):
  - LAC 33:I.3915 and 3917: an emergency discharge is reported to the Louisiana State Police hotline within the first
    hour, a non-emergency discharge above a reportable quantity to the same hotline within 24 hours of learning of it;
    LAC 33:I.3925: a written report to LDEQ within seven calendar days; other permit excursions go to LDEQ's Single
    Point of Contact by telephone or its online form. Reports to agencies only; LDEQ files them in its document system
    (EDMS), searched one document at a time behind a reCAPTCHA; no list is published and no duty to tell the public was
    found.
Rows
  - Per operator (every Louisiana row of data/dischargers.json): <id>-ldeq-report, the report to LDEQ and the State
    Police (telephone, online form, letter; no public output).
  - Agencies: LDEQ's Single Point of Contact, EDMS (reCAPTCHA), EPA's eRule tables (no Louisiana report), LDH's beach
    monitoring and bloom advisories (403 to this client), Pontchartrain Conservancy's weekly results (not read).
  - Operators' own: Baton Rouge's quarterly reports (feed), the Sewerage and Water Board's consent-decree page
    (watched), Shreveport's consent-decree repository (did not answer).
A rerun replaces every la- row it makes. Validated before writing.
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
SPOC = "https://www.deq.louisiana.gov/page/single-point-of-contact"
LAW_TEXT = ("LAC 33:I.3915 and 3917 (an emergency discharge to the Louisiana State Police hotline within the first hour; "
            "a discharge above a reportable quantity within 24 hours of learning of it) and LAC 33:I.3925 (a written "
            "'Unauthorized Discharge Notification Report' to LDEQ within seven calendar days); other permit excursions to "
            "LDEQ's Single Point of Contact; the permit's standard conditions add the reports of 40 CFR 122.41(l)(6)")
BR = "la-city-of-baton-rouge-and-parish-of-east-baton-rouge"
AGENCY = [
    {"id": "la-ldeq-spoc", "agency": "Louisiana Department of Environmental Quality",
     "name": "LDEQ (Single Point of Contact)", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": LAW_TEXT, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("Discharges are reported to the State Police hotline by telephone, and to LDEQ by telephone, its online "
              f"incident form (which returns a tracking number to the filer only) and a written report ({SPOC}). No "
              "public list of the reports exists; no web channel found for the public."),
     "sources": ["la-ldeq-spoc", "la-lac-33-i-ch39", "la-ldeq-written-notification-guidance"]},
    {"id": "la-ldeq-edms", "agency": "Louisiana Department of Environmental Quality",
     "name": "LDEQ (Electronic Document Management System)", "channel_kind": "state_alert_page",
     "urls": ["https://edms.deq.louisiana.gov/edmsv2"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "documents",
     "records": False,
     "note": ("LDEQ's official record of permits, discharge reports and correspondence, searched one document at a time "
              "in a JavaScript application whose search is guarded by a reCAPTCHA (2026-11-14); this project does not "
              "pass a CAPTCHA, so the pilot read no document. A bulk export exists for staff and records requests."),
     "sources": ["la-ldeq-edms"]},
    {"id": "la-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (sewer overflow and bypass tables)", "channel_kind": "feed",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("EPA's sewer overflow and bypass event tables hold no Louisiana report (current and all-versions extracts "
              "of 2026-11-14), although 17 Louisiana collection-system permits are listed in its permits table. No web "
              "channel found."),
     "sources": ["la-epa-sobe"]},
    {"id": "la-ldh-beach-monitoring", "agency": "Louisiana Department of Health",
     "name": "Louisiana Department of Health (Beach Monitoring Program)", "channel_kind": "local_health_page",
     "urls": ["https://ldh.la.gov/page/beach-monitoring-program"], "method": "html", "legal_basis":
     "BEACH Act grant (33 U.S.C. 1346): coastal recreation water monitoring and public notification",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "status",
     "note": ("Weekly advisories for about two dozen coastal beach sites, May to October, with sample dates; the "
              "Department's site answers 403 to this project's client (2026-11-14, both addresses)."),
     "sources": ["la-ldh-beach-monitoring", "la-ldh-beach-alternate"]},
    {"id": "la-ldh-hab-advisories", "agency": "Louisiana Department of Health",
     "name": "Louisiana Department of Health (algal bloom advisories)", "channel_kind": "news_page",
     "urls": ["https://www.ldh.la.gov/news/5177"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "notices",
     "note": "Bloom advisories as occasional news releases; the Department's site answers 403 to this project's client.",
     "sources": ["la-ldh-hab-advisories"]},
    {"id": "la-pontchartrain-conservancy-results", "agency": "Pontchartrain Conservancy",
     "name": "Pontchartrain Conservancy (weekly water quality results)", "channel_kind": "group_results", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "results",
     "note": ("Weekly bacteria results for Lake Pontchartrain sites on a public spreadsheet and Swim Guide; the rows and "
              "the terms of reuse were not verified in the research."),
     "sources": ["la-pontchartrain-conservancy", "la-pontchartrain-weekly-results"]},
]
OWN = [
    {"id": "la-baton-rouge-quarterly-reports", "operator_id": BR, "permit": "LA0036412",
     "name": "City of Baton Rouge and Parish of East Baton Rouge", "channel_kind": "feed",
     "urls": ["https://brprojects.com/baton-rouge-sso-program/program-overview/regulatory-information/"],
     "method": "pdf", "legal_basis": ("Consent decree, United States and Louisiana v. City of Baton Rouge and Parish of "
                                      "East Baton Rouge (2002), Paragraph 26, Section XI: every unauthorized discharge "
                                      "reported to EPA and LDEQ in the quarterly report"), "basis_kind": "permit",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "la-baton-rouge-quarterly",
     "publishes": "documents", "noun": "Data feed",
     "note": ("The City-Parish posts each quarterly report (Report 98, July to September 2026, issued October 30, 2026); "
              "Part D lists every collection-system discharge with its date, cause, receiving water and gallons. Read "
              "by the la-baton-rouge-quarterly feed; treatment plant discharges are scanned forms."),
     "sources": ["la-baton-rouge-quarterly-reports", "la-baton-rouge-consent-decree"]},
    {"id": "la-swbno-consent-decree-page", "operator_id": "la-sewerage-and-water-board-of-new-orleans",
     "permit": "LA0038091", "name": "Sewerage and Water Board of New Orleans", "channel_kind": "operator_page",
     "urls": ["https://www.swbno.org/Wastewater/ConsentDecree"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "documents",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The Board's consent-decree reports, quarterly since 2008: the Q3 2026 report (624 pages, read 2026-11-14) "
              "covers repairs, inspections and private-property letters but holds no dated list of overflows. Watched "
              "daily for a new report."),
     "sources": ["la-swbno-consent-decree"]},
    {"id": "la-shreveport-consent-decree", "operator_id": "la-city-of-shreveport", "permit": "LA0041394",
     "name": "City of Shreveport", "channel_kind": "operator_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "documents",
     "note": ("The City's consent-decree repository (cleanwatershreveport.com) posts annual reports whose Attachment 3 "
              "lists the year's sanitary sewer overflows (131 rows for May 2025 to May 2026 in the research); the host "
              "did not answer this project's client on 2026-11-14 (no connection, twice), so the table was not verified "
              "in the research."),
     "sources": ["la-shreveport-consent-decree"]},
]


def base(**kw) -> dict:
    r = {"state": "LA", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "LA":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        rows.append(finish(base(
            id=f"{oid}-ldeq-report", operator_id=oid, name=name, permit=ps[0] if ps else None,
            channel_kind="state_alert_page", urls=[], method=None, legal_basis=LAW_TEXT, basis_kind="law",
            monitored=False, unmonitored_reason="other", publishes="none", records=False, noun="Report to the state",
            sources=["la-lac-33-i-ch39", "la-ldeq-spoc"],
            note=(f"{name} reports an unauthorized discharge to the State Police hotline by telephone and to LDEQ by "
                  "telephone or LDEQ's online intake form (whose tracking number goes to the filer only), then in "
                  "writing; LDEQ publishes no list and no public notice is required. No web channel found for the "
                  "public. The permit itself was not read."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "LA")
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
