"""Nebraska rows of the notice register (data/notice-channels/ne.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ne_register_rows.py [--dry-run]

The law (research/ne/report.md §2.1 in the site repository; profile research/ne/profile.json):
  - No Nebraska statute or rule requires public notice of a sewage overflow or a bypass. Title 119 defines a sanitary
    sewer overflow (Neb. Admin. Code Title 119 ch. 1 § 028) without a notice duty; Title 126's release notification
    (Chapter 18) covers oil and hazardous substances, not sewage.
  - The permit's standard conditions (40 CFR 122.41(l)(6)-(7), carried in Nebraska NPDES permits; DWEE's noncompliance
    form WAT098): a report to DWEE within 24 hours and in writing within 5 days, filed through EPA's NeT-SewerOverflow
    (DWEE publication 25-032), so the reports become public in EPA's overflow tables, a median 23 days after the start.
    One row per operator (every permittee, public or private: the permit conditions bind both alike), read through
    EPA's tables.
  - Omaha's CSO permit NE0133680: public notification of combined sewer overflows under the permit (Nine Minimum
    Controls no. 8, EPA's CSO Control Policy, 59 FR 18688); the permit text sits in DWEE's OnBase document viewer and
    was not read, so the clause is filed unread.
Rows
  - Per operator: <id>-dwee-epa-report (permit basis; feed_ingested, echo-sewer-overflow), with the count of reports
    EPA's 2026-11-04 extract holds under the operator's permits; for the operators whose permits EPA issues in Indian
    country (add_ne_operators.EPA_ISSUED), <id>-epa-report: the report goes to EPA Region 7, not DWEE.
  - Omaha (the one CSO operator): ne-omaha-cso-public-notification (permit, clause unread), the CSO program site
    (voluntary, monitored), the city's overflow pages (voluntary, 403) and its statements to the news media (voluntary).
  - Agency and voluntary rows: AGENCY below, with "none found" rows (urls []) where the research looked and found no
    channel, and "not searched" rows where it did not look.
A rerun replaces every ne- row it makes. Validated before writing.
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
from add_ne_operators import EPA_ISSUED  # noqa: E402

REGISTER = ROOT / "data" / "notice-channels"
DIS = ROOT / "data" / "dischargers.json"
CHECKED = "2026-11-07"
SOBE_PAGE = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
BW_LAYER = "https://dweegis.nebraska.gov/weesr/rest/services/MonitoredBeachAlertNDEE/FeatureServer/0"
BW_RELEASE = "https://dwee.nebraska.gov/news-events/press-releases/dwee-launches-interactive-hab-map"
Q_PERMIT = ("NPDES permit {permit}, standard conditions (40 CFR 122.41(l)(6)-(7), as carried in Nebraska permits; "
            "DWEE noncompliance form WAT098): report to DWEE within 24 hours and in writing within 5 days, filed through "
            "EPA's NeT-SewerOverflow (DWEE publication 25-032); permit text not read")
Q_EPA = ("NPDES permit {permit}, issued by EPA Region 7 in Indian country (EPA's facility record: issuing agency EPA, "
         "read 2026-11-07), standard conditions (40 CFR 122.41(l)(6)-(7)): report to EPA within 24 hours and in writing "
         "within 5 days, filed through EPA's NeT-SewerOverflow; Nebraska's rules do not apply; permit text not read")
Q_NMC = ("NPDES permit NE0133680: public notification of combined sewer overflows (Nine Minimum Controls no. 8, EPA's "
         "CSO Control Policy, 59 FR 18688); the clause is unread: the permit text sits in DWEE's OnBase document viewer")
# reports in EPA's overflow tables per permit, 2026-11-04 all-versions extract (current version of each report)
SOBE_COUNTS = {"NE0112810": 71, "NE0043702": 23, "NE0023876": 13, "NE0036358": 10, "NE0021148": 9, "NE0133680": 8,
               "NE0112488": 5, "NE0021245": 4, "NE0021199": 3, "NE0021504": 3, "NE0027324": 2, "NE0045101": 2,
               "NE0020915": 1, "NE0023965": 1, "NE0031844": 1, "NE0032891": 1, "NE0034304": 1, "NE0040932": 1,
               "NE0046272": 1, "NE0132632": 1, "NE0139611": 1}
AGENCY = [
    {"id": "ne-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [SOBE_PAGE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "echo-sewer-overflow", "publishes": "notices",
     "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): Nebraska permittees file their "
              "reports through NeT-SewerOverflow and EPA publishes them daily (162 Nebraska reports from 21 permits in "
              "the 2026-11-04 extract, starts 2022-04 to 2026-10-06, received a median 22.5 days after the start). The "
              "only dated, statewide record of Nebraska's overflows; 21 of the state's 336 permits have a report in it. "
              "(research/ne/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "ne-epa-sobe"]},
    {"id": "ne-dwee-overflow-report", "agency": "Nebraska Department of Water, Energy, and Environment",
     "name": "Nebraska Department of Water, Energy, and Environment", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": Q_PERMIT.format(permit="(every Nebraska permit)"), "basis_kind": "permit",
     "monitored": False, "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "noun": "Report to the state",
     "note": ("No web form: every permittee, public or private, reports an overflow or bypass to DWEE within 24 hours "
              "and in writing within 5 days; no Nebraska statute or rule requires the public to be told, and DWEE does "
              "not post the reports. No web channel found; the reports reach the public through EPA's tables weeks "
              "later. (research/ne/report.md §2.1)"),
     "sources": ["ne-dwee-net-sso-guide", "ne-title-126-release"]},
    {"id": "ne-dwee-overflow-alerts", "agency": "Nebraska Department of Water, Energy, and Environment",
     "name": "Nebraska Department of Water, Energy, and Environment (overflow alerts)", "channel_kind": "email_list",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("No e-mail, text or web alert for sewage overflows was found from DWEE: its listservs cover air, waste, "
              "energy and outreach, none sewage (DWEE site navigation read 2026-11-07), and no law requires one. "
              "Operators' own alerts were not searched one by one beyond Omaha and Lincoln. (research/ne/report.md §2.6)"),
     "sources": ["ne-title-126-release"]},
    {"id": "ne-dwee-beachwatch", "agency": "Nebraska Department of Water, Energy, and Environment",
     "name": "Nebraska Department of Water, Energy, and Environment (Beach Watch)", "channel_kind": "state_alert_page",
     "urls": [BW_LAYER], "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "ne-dwee-beachwatch", "publishes": "results",
     "noun": "Beach results",
     "note": ("Beach Watch's public layer: every weekly sample of the season at 57 public beaches (E. coli, microcystin, "
              "the health alert flag), mid-May to mid-September; read by the feed for its health alerts (microcystin "
              "above 8 micrograms per litre, joint with DHHS) and its elevated E. coli labels. Filed voluntary: no "
              "statute for the program was traced (the federal BEACH Act covers coastal and Great Lakes waters only). "
              "(research/ne/report.md §2.5)"),
     "sources": ["ne-dwee-beachwatch"]},
    {"id": "ne-dwee-beachwatch-page", "agency": "Nebraska Department of Water, Energy, and Environment",
     "name": "Nebraska Department of Water, Energy, and Environment (Beach Watch page)",
     "channel_kind": "state_alert_page", "urls": ["https://deq-iis.ne.gov/zs/bw/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "results", "records": False,
     "note": ("DWEE's Beach Watch page, where \"all sample results are posted\" (DWEE "
              "release), answered 503 on 2026-11-03 and no connection on 2026-11-07; its results are the layer the "
              "Beach Watch feed reads. Channel not researched beyond the link. Voluntary. (research/ne/report.md §2.5)"),
     "sources": ["ne-dwee-beachwatch-page"]},
    {"id": "ne-dwee-beachwatch-listserv", "agency": "Nebraska Department of Water, Energy, and Environment",
     "name": "Nebraska Department of Water, Energy, and Environment (Beach Watch listserv)",
     "channel_kind": "email_list", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "email_only", "publishes": "notices",
     "note": ("DWEE's release on its bloom map: \"health alert information is shared through DWEE's Beach Watch email "
              f"listserv and DWEE's social media pages\" ({BW_RELEASE}, read 2026-11-07). Sign-up route not found on "
              "DWEE's site (its listserv instructions cover other programs). Not signed up. Voluntary."),
     "sources": ["ne-dwee-beachwatch"]},
    {"id": "ne-dhhs-health-alerts", "agency": "Nebraska Department of Health and Human Services",
     "name": "Nebraska Department of Health and Human Services (news releases)", "channel_kind": "state_alert_page",
     "urls": ["https://dhhs.ne.gov/Pages/Newsroom.aspx"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "notices",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("DHHS's newsroom, where the joint DWEE and DHHS health alerts for blooms are released (the same alerts as "
              "the Beach Watch layer). Blooms, not sewage. Answered 200 on 2026-11-07. Voluntary. "
              "(research/ne/report.md §2.5)"),
     "sources": ["ne-dhhs-hab-alerts"]},
    {"id": "ne-douglas-county-health", "agency": "Douglas County Health Department",
     "name": "Douglas County Health Department", "channel_kind": "local_health_page",
     "urls": ["https://www.douglascountyhealth.com/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "unknown",
     "records": False,
     "note": ("The health department of Omaha's county: its site answers 403 to the project user agent (2026-11-07), so "
              "whether it posts sewage or water contact advisories could not be read. Voluntary."),
     "sources": []},
    {"id": "ne-papio-missouri-nrd", "agency": "Papio-Missouri River Natural Resources District",
     "name": "Papio-Missouri River Natural Resources District", "channel_kind": "group_results",
     "urls": ["https://www.papionrd.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "none", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The district for the Papillion Creek basin, the receiving waters of Omaha's Papillion Creek reports. Home "
              "page read 2026-11-07 (200): no overflow notice or water quality alert found on it; read for changes. "
              "Voluntary."),
     "sources": []},
    {"id": "ne-lincoln-overflow-notices", "agency": None, "operator_id": "ne-lincoln",
     "name": "City of Lincoln Transportation and Utilities", "permit": None, "channel_kind": "operator_page",
     "urls": ["https://www.lincoln.ne.gov/City/Departments/LTU/Utilities/Wastewater"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Lincoln Transportation and Utilities' wastewater page, read 2026-11-07 (200): no overflow notice or alert "
              "found on it; read for changes. Its overflow reports reach EPA's tables (five in the 2026-11-04 extract, "
              "all under the Northeast plant). Voluntary."),
     "sources": []},
]
OMAHA = [
    {"id": "ne-omaha-cso-public-notification", "permit": "NE0133680", "channel_kind": "operator_page", "urls": [],
     "method": None, "legal_basis": Q_NMC, "basis_kind": "permit", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False, "noun": "CSO public notification",
     "note": ("Clause unread. Omaha's CSO permit is expected to require public notification of overflows (Nine Minimum "
              "Controls no. 8), but its text sits in DWEE's OnBase document viewer, which does not give a linkable "
              "document, and was not read; DWEE's public notice of the permit's modification (dwee.nebraska.gov/node/"
              "4730) names the CSO receiving waters only. No web channel found for the notices: the CSO program site "
              "carries projects and reports, the city's pages answer 403. A records request for the city's CSO public "
              "notification plan is the way to read it. (research/ne/report.md §2.1, §4)"),
     "sources": ["ne-omaha-cso-permit-notice"]},
    {"id": "ne-omaha-cso-program-site", "permit": "NE0133680", "channel_kind": "operator_page",
     "urls": ["https://www.omahacso.com/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "documents", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("Omaha's CSO program site (Clean Solutions for Omaha): projects, quarterly reports and the long-term "
              "control plan; no overflow status, notice or sign information was found on it. Read for changes. "
              "Answered 200 on 2026-11-07. Voluntary. (research/ne/sources.json ne-omaha-cso-program)"),
     "sources": ["ne-omaha-cso-program"]},
    {"id": "ne-omaha-public-works-pages", "permit": None, "channel_kind": "operator_page",
     "urls": ["https://www.cityofomaha.org/", "https://publicworks.omaha.gov/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "unknown",
     "note": ("The City of Omaha's and Omaha Public Works' sites answer 403 to "
              "the project user agent (2026-11-03); no overflow notice page of theirs was found by search. Voluntary. "
              "(research/ne/report.md §2.3)"),
     "sources": ["ne-omaha-cso-program"]},
    {"id": "ne-omaha-media-statements", "permit": None, "channel_kind": "news_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "notices", "records": False,
     "note": ("Omaha Public Works announces large overflows through local television and newspapers, with a map of the "
              "affected stretch (2026-10-02: wastewater overflows into Boxelder and West Papillion creeks, the public "
              "told \"not to touch the water\"; https://www.wowt.com/2026/10/02/wastewater-overflows-into-boxelder-"
              "west-papillion-creeks/). No own page found for these statements. Voluntary. (research/ne/report.md §2.3)"),
     "sources": ["ne-omaha-news"]},
]


def base(**kw) -> dict:
    r = {"state": "NE", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def reports(op: dict) -> str:
    n = {p: SOBE_COUNTS[p] for p in op.get("npdes_permits") or [] if p in SOBE_COUNTS}
    if not n:
        return "None of its permits has a report in the 2026-11-04 extract."
    parts = ", ".join(f"{p} {k}" for p, k in n.items())
    return f"Reports in the 2026-11-04 extract: {sum(n.values())} ({parts})."


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "NE":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        private = " The permit binds the holder, public or private." if op.get("legal_form") in (
            "investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
            "campground or resort", "private club", "business or industrial", "institution",
            "facility (permittee not named)") else ""
        if set(op.get("npdes_permits") or []) <= EPA_ISSUED:
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed",
                urls=[SOBE_PAGE], method="html", legal_basis=Q_EPA.format(permit=permit), basis_kind="permit",
                monitored=False, unmonitored_reason="feed_ingested", feed_source_id="echo-sewer-overflow",
                publishes="notices", noun="Report to EPA", sources=["ne-epa-sobe"],
                note=(f"{name} holds an EPA-issued permit in Indian country: it reports its overflows and bypasses to "
                      "EPA Region 7, not to DWEE, and EPA publishes them in its overflow tables (read by the "
                      f"echo-sewer-overflow feed). {reports(op)} The issuing agency was read from EPA's facility record "
                      "(2026-11-07)."))))
            continue
        rows.append(finish(base(
            id=f"{oid}-dwee-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed",
            urls=[SOBE_PAGE], method="html", legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit",
            monitored=False, unmonitored_reason="feed_ingested", feed_source_id="echo-sewer-overflow",
            publishes="notices", noun="Report to DWEE and EPA", sources=["ne-epa-sobe", "ne-dwee-net-sso-guide"],
            note=(f"{name} reports its overflows and bypasses to DWEE and files them in EPA's NeT-SewerOverflow; EPA "
                  "publishes them in its overflow tables (read by the echo-sewer-overflow feed), weeks after the "
                  f"event. {reports(op)}{private} (research/ne/report.md §2.1, §2.2)"))))
        if oid == "ne-omaha":
            rows += [finish(base(operator_id=oid, name=name, **r)) for r in OMAHA]
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    cso = [op["id"] for op in dis if op.get("state") == "NE" and op.get("kind") == "cso"]
    if cso != ["ne-omaha"]:
        raise SystemExit(f"Nebraska's CSO operators changed ({cso}): name each one's notification row")
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "NE")
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
