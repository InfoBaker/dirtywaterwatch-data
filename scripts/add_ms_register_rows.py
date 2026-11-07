"""Mississippi rows of the notice register (data/notice-channels/ms.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ms_register_rows.py [--dry-run]

The law (research/ms/report.md §2.1 in the site repository; profile research/ms/profile.json):
  - Sanitary sewer overflows and bypasses: no Mississippi statute or rule requiring public notice was found. MDEQ's
    flyer (fetched 2026-11-03) says every municipal and private provider "must report sanitary sewer overflows (SSOs)
    and/or bypasses to the Mississippi Department of Environmental Quality (MDEQ) within 24 hours of the event" and,
    from 2025-12-21, files an electronic report within 5 days through EPA's NeT-SewerOverflow; the reports reach the
    public only through EPA's overflow tables. One statewide row (every permittee, public or private: the permit
    conditions bind both alike; 323 operator rows in data/dischargers.json) and EPA's tables as the feed row. There are
    no combined sewer permits in Mississippi, so no CSO notification rows.
  - The City of Jackson (operator ms-jackson-jxn): the 2013 consent decree's Sewer Overflow Response Plan calls for a
    news release and temporary signs for significant overflows (as the press reports it; the plan was not read); the
    2023 interim stipulated order put the system under JXN Water, which files quarterly status reports with the court.
  - Beaches: MDEQ's Beach Monitoring Program (BEACH Act grants) posts advisories on its map first; from 2026-09-08
    routine advisories go to beach signs and the map only, no longer to text alerts and news releases (MDEQ news
    release of 2026-09-08). Ad hoc water contact advisories for rivers (Trahon Creek and the Pearl River below
    Jackson, 2026-09-02) come as MDEQ news releases.
  - Per operator (every Mississippi row of data/dischargers.json, 2026-11-07 final audit): <id>-overflow-report
    (permit basis): the 24-hour report to MDEQ and the 5-day report through NeT-SewerOverflow, which reaches the
    public only through EPA's tables (the echo-sewer-overflow feed), as South Dakota's and Nebraska's rows give it.
    The duty falls on each operator (collection checklist §2), and without these rows the coverage file counted only
    the City of Jackson as an operator and read Mississippi as "1 of 1" operators posting each overflow online.
Rows: AGENCY, JACKSON and the per-operator rows below; each URL checked 2026-11-07 with one GET with the project user
agent.
A rerun replaces every ms- row it makes. Validated before writing.
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
CHECKED = "2026-11-07"
MDEQ = "Mississippi Department of Environmental Quality"
JACKSON = "ms-jackson-jxn"
BEACH_LAYER = ("https://mgis19.mdeq.ms.gov/arcgis/rest/services/Hosted/BeachMonitoringView/FeatureServer/0/query?"
               "where=1%3D1&outFields=stationnumber,name,isadvisory,isclosure,eventtype,advisorydesc,closuredesc,"
               "startdate&orderByFields=stationnumber&returnGeometry=false&f=json")
Q_SSO = ("MDEQ, Reporting Sanitary Sewer Overflows or Bypasses in Mississippi (NeT-SewerOverflow flyer): \"Municipal and "
         "private sanitary sewer collection and treatment providers in Mississippi must report sanitary sewer overflows "
         "(SSOs) and/or bypasses to the Mississippi Department of Environmental Quality (MDEQ) within 24 hours of the "
         "event. ... Starting December 21, 2025, in addition to the 24-hr reporting requirement, an electronic report "
         "shall be submitted to the MDEQ within 5 days ... through NeT-SewerOverflow\"; NPDES permit conditions "
         "(40 CFR 122.41(l)(6))")
Q_BEACH = ("BEACH Act of 2000 (33 U.S.C. 1346): a state beach program funded under it notifies the public of "
           "exceedances of the bacteria criteria; MDEQ's Beach Monitoring Program, with the University of Southern "
           "Mississippi's Gulf Coast Research Laboratory (statute text not quoted)")
Q_JXN = ("United States and State of Mississippi v. City of Jackson (S.D. Miss.): the 2013 consent decree's Sewer "
         "Overflow Response Plan calls for a news release and temporary signs for significant overflows (as reported "
         "in the press; the plan was not read)")
Q_ORDER = ("United States v. City of Jackson (S.D. Miss.), 2023 interim stipulated order: JXN Water, the interim "
           "third-party manager, files quarterly status reports with the court (as reported; the order was not read)")

AGENCY = [
    {"id": "ms-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "echo-sewer-overflow", "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): Mississippi permittees file "
              "their 5-day reports through NeT-SewerOverflow and EPA publishes them daily (358 Mississippi reports from "
              "47 permits in the 2026-11-04 extract; median 4 days from start to receipt). The only statewide dated "
              "record: it covers every operator in the state, public or private. (research/ms/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "ms-epa-sobe"]},
    {"id": "ms-mdeq-sso-report", "agency": MDEQ, "name": MDEQ, "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": Q_SSO, "basis_kind": "permit", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False, "noun": "Report to the state",
     "note": ("No web form: every permittee, public or private, reports a sanitary sewer overflow or bypass to MDEQ "
              "within 24 hours (telephone, e-mail or voicemail after hours) and files the 5-day report through EPA's "
              "NeT-SewerOverflow; no Mississippi statute or rule requiring the public to be told was found, and MDEQ "
              "posts no list or map of the reports. No web channel found; they reach the public through EPA's tables days "
              "later. "
              "(research/ms/report.md §2.1)"),
     "sources": ["ms-mdeq-netsso-guidance"]},
    {"id": "ms-mdeq-news-releases", "agency": MDEQ, "name": MDEQ, "channel_kind": "news_page",
     "urls": ["https://www.mdeq.ms.gov/category/news-release/feed/"], "method": "rss", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "ms-mdeq-water-contact-advisories", "publishes": "notices", "noun": "News releases",
     "note": ("MDEQ's news releases (RSS, answered 200 on 2026-11-07). Ad hoc water contact advisories after sewage "
              "discharges come this way: 2026-09-02, an advisory for an unnamed tributary of Trahon Creek and Trahon "
              "Creek to the Pearl River \"due to an ongoing sewage bypass\", the release adding that \"the longstanding "
              "water contact advisory for the section of the Pearl River from Hanging Moss Creek to the Byram Swinging "
              "bridge remains in effect\". Beach advisories came this way until 2026-09-07. No law requires the "
              "releases. Read by the feed: an issue opens an advisory, a lift ends it, and the Pearl River advisory "
              "the release cites is a record of its own. (ms-mdeq-water-contact-advisories)"),
     "sources": ["ms-mdeq-water-contact-advisories"]},
    {"id": "ms-mdeq-beach-monitoring-map", "agency": MDEQ, "name": f"{MDEQ} (Beach Monitoring Program)",
     "channel_kind": "state_alert_page", "urls": [BEACH_LAYER], "method": "json", "legal_basis": Q_BEACH,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "ms-mdeq-beach-monitoring", "publishes": "status", "noun": "Beach advisories",
     "note": ("The layer behind beaches.mdeq.ms.gov: 21 Gulf Coast stations, each with an advisory flag, a closure flag, "
              "the event type (Enterococci, HAB, debris), MDEQ's start date and the advisory or closure text. MDEQ "
              "posts advisories here first; since 2026-09-08 routine advisories go only here and to beach signs. None "
              "in effect on 2026-11-07. Read hourly by the feed (both flags, MDEQ's start date, the station's point). "
              "(ms-mdeq-beach-monitoring)"),
     "sources": ["ms-mdeq-beach-monitoring", "ms-hab"]},
    {"id": "ms-mdeq-beach-signs", "agency": MDEQ, "name": f"{MDEQ} (Beach Monitoring Program)",
     "channel_kind": "lights_signs_page", "urls": [], "method": None, "legal_basis": Q_BEACH, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "status", "records": False,
     "noun": "Beach signs",
     "note": ("No web form: signs posted at the beach segments under advisory. From 2026-09-08 routine beach advisories "
              "are \"communicated through posted beach signage and the MDEQ Beach Monitoring website rather than text "
              "alerts and news releases\" (MDEQ news release, 2026-09-08). On site only."),
     "sources": ["ms-mdeq-beach-alerts"]},
    {"id": "ms-mdeq-beach-text-alerts", "agency": MDEQ, "name": f"{MDEQ} (Beach Monitoring Program)",
     "channel_kind": "email_list", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Beach text alerts",
     "note": ("No web form: the text alerts (text \"MDEQbeach\" to 95577) and the e-mail list that carried beach "
              "advisories ended with routine advisories on 2026-09-08 (MDEQ news release of that day). Kept as a row so "
              "the retired channel stays on record; no web channel found for it. Voluntary. (ms-mdeq-beach-alerts)"),
     "sources": ["ms-mdeq-beach-alerts"]},
    {"id": "ms-pearl-riverkeeper", "agency": "Pearl Riverkeeper", "name": "Pearl Riverkeeper",
     "channel_kind": "group_results", "urls": ["https://www.pearlriverkeeper.com/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "unknown", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The watershed group for the Pearl River; the press reports it petitioned MDEQ to enforce the notice in "
              "Jackson's overflow response plan (date not confirmed). Answered 200 on 2026-11-07; content not traced "
              "beyond the home page. Voluntary. (research/ms/profile.json)"),
     "sources": []},
    {"id": "ms-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": ["https://www.theswimguide.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "results", "noun": "Swim Guide listing",
     "note": ("Swim Guide (a script app); the research found no Mississippi listing (research/ms/profile.json, "
              "swim_guide false). Voluntary; no API."),
     "sources": []},
]

JACKSON_ROWS = [
    {"id": "ms-jackson-jxn-news-releases", "channel_kind": "operator_page",
     "urls": ["https://jxnwater.com/newservice/"], "method": "html", "legal_basis": Q_JXN, "basis_kind": "law",
     "monitored": True, "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 6,
     "noun": "News releases",
     "note": ("JXN Water's news page (answered 200 on 2026-11-07), where the overflow response plan's news releases for "
              "significant overflows would appear; whether they are posted here was not checked. (ms-jxn-water)"),
     "sources": ["ms-jxn-water"]},
    {"id": "ms-jackson-jxn-overflow-signs", "channel_kind": "lights_signs_page", "urls": [], "method": None,
     "legal_basis": Q_JXN, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False, "noun": "Overflow signs",
     "note": "No web form: temporary signs at significant overflows under the overflow response plan. On site only.",
     "sources": ["ms-jxn-water"]},
    {"id": "ms-jackson-jxn-quarterly-reports", "channel_kind": "operator_page", "urls": [], "method": None,
     "legal_basis": Q_ORDER, "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "documents", "records": False, "noun": "Quarterly reports",
     "note": ("No URL known: JXN Water's quarterly status reports to the court give the period's overflow totals; no "
              "page listing them was found (jxnwater.com/reports answered 404 on 2026-11-07). (ms-jxn-water)"),
     "sources": ["ms-jxn-water"]},
]


def base(**kw) -> dict:
    r = {"state": "MS", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


Q_PERMIT = ("NPDES permit {permit}: standard conditions, a report of a sanitary sewer overflow or bypass to MDEQ within "
            "24 hours and an electronic report within 5 days through EPA's NeT-SewerOverflow (MDEQ's NeT-SewerOverflow "
            "flyer; 40 CFR 122.41(l)(6) and part 127; permit text not read)")
PRIVATE = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
           "campground or resort", "private club", "business or industrial", "institution",
           "facility (permittee not named)"}


def operator_rows(dis: list[dict]) -> list[dict]:
    """One permit row per Mississippi operator: the report to MDEQ, public only through EPA's tables."""
    rows = []
    for op in dis:
        if op.get("state") != "MS":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        private = " The permit binds the holder, public or private." if op.get("legal_form") in PRIVATE else ""
        rows.append(finish(base(
            id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id="echo-sewer-overflow", publishes="notices",
            noun="Report to the state", sources=["ms-epa-sobe", "ms-mdeq-netsso-guidance"],
            note=(f"{name} reports each sewer overflow and bypass to MDEQ within 24 hours and files the 5-day report "
                  "through NeT-SewerOverflow; the report is published in EPA's overflow tables, read by the "
                  f"echo-sewer-overflow feed. No public-notice requirement was found.{private} "
                  "(research/ms/report.md §2.1)"))))
    return rows


def rows_for(dis: list[dict]) -> list[dict]:
    op = next((d for d in dis if d["id"] == JACKSON), None)
    if op is None:
        raise SystemExit(f"{JACKSON} is not in data/dischargers.json: run scripts/add_ms_operators.py first")
    out = [finish(base(**r)) for r in AGENCY]
    out += [finish(base(operator_id=JACKSON, name=op["name"], permit=op["npdes_permit"], **r)) for r in JACKSON_ROWS]
    out += operator_rows(dis)
    return out


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = rows_for(dis)
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "MS")
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
