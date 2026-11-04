"""California rows of the notice register (data/notice-channels/ca.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ca_register_rows.py [--dry-run]

The law (research/ca/report.md §2.1 in the site repository; the General Order read 2026-11-04):
  - Health and Safety Code 5411.5: any person who causes or permits a sewage discharge to waters of the State "shall,
    as soon as that person has knowledge of the discharge, immediately notify the local health officer or the
    director of environmental health"; it binds every operator, public or private, and requires no publication.
  - Water Code 13271 and Order WQ 2022-0103-DWQ Att. E1 1.1: Cal OES within 2 hours of a spill of 1,000 gallons or
    more to waters of the State (any person). Cal OES publishes spill releases on a script-driven dashboard and in
    yearly spreadsheets, not by law (one agency row).
  - Order WQ 2022-0103-DWQ Att. E1 3.1-3.3: draft and certified spill reports in CIWQS, which the State Water Board
    publishes in a nightly file (the statewide feed row; it covers every enrollee).
  - Health and Safety Code 115885 and 17 CCR 7958: the county health officer posts and closes beaches after a known
    sewage release and keeps a telephone hotline of closed and posted beaches; the law asks for no web page (the
    hotline and signs rows; the counties' voluntary pages below).
  - CSO permits: Sacramento's (CA0079111, Order R5-2026-0003, read) and San Francisco's (CA0037664, CA0037681, not read).
  - NPDES standard provision (40 CFR 122.41(l)(6)): a permittee reports noncompliance that may endanger health or the
    environment to the Regional Water Board within 24 hours; nothing is published. A report to the regulator is not a
    channel the public is told through, so it has no register row (review 2026-11-04 P2-3); the operator row of a plant
    operator with no enrollment under the General Order says its spills do not reach the CIWQS file.

Rows
  - Per operator (every California row of data/dischargers.json): <id>-health-officer-notice (no_web_page).
  - SFPUC's beach map (CSO flag, read by the ca-sfpuc-beach-map feed), its signs and e-mail alerts; Sacramento's CSO
    notification (no web channel found).
  - Agency and voluntary rows: AGENCY below.
A rerun replaces every ca- row it makes and keeps rows it does not make (none today). Validated before writing.
"""
from __future__ import annotations

import json
import re
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
CHECKED = "2026-11-04"
FILE_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/data_files/Cat1-2-3-Spills.txt"
INDEX_URL = "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/index.php"
FEED = "ca-swrcb-ciwqs-spills-flatfile"
SFPUC_FEED = "ca-sfpuc-beach-map"
FHAB_FEED = "ca-swrcb-fhab"
BEACHWATCH_FEED = "ca-beachwatch-advisories"
Q_5411 = ('Health and Safety Code 5411.5(a): any person who causes or permits a discharge of sewage in or on waters of '
          'the State "shall, as soon as that person has knowledge of the discharge, immediately notify the local health '
          'officer or the director of environmental health of the discharge"')
Q_GO = ('Order WQ 2022-0103-DWQ Att. E1 3.1.1: "Within three (3) business days of the Enrollee\'s knowledge of a '
        'Category 1 spill, the Enrollee shall submit a Draft Spill Report to the online CIWQS Sanitary Sewer System '
        'Database"; 3.1.2: a Certified Spill Report "Within 15 calendar days of the spill end date"; 3.2 the same for '
        'Category 2 spills; 3.3 Category 3 spills certified monthly')
Q_13271 = ('Water Code 13271 and Order WQ 2022-0103-DWQ Att. E1 1.1: the California Office of Emergency Services is '
           'notified "as soon as possible but no later than two (2) hours after" knowledge of a spill of 1,000 gallons '
           'or more to waters of the State')
Q_115885 = ('Health and Safety Code 115885(a)(1)(D): the health officer shall "Establish a telephone hotline to inform '
            'the public of all beaches currently closed, posted, or otherwise restricted"; 115885(a)(1)(F) and 17 CCR '
            '7958: on a known untreated sewage release, "Immediately post and close the beach or a portion thereof, '
            'or otherwise restrict its use until the source of the sewage release is eliminated"')
Q_SAC = ('Order R5-2026-0003 (NPDES CA0079111): "The Discharger shall implement its \'Spill Emergency Response Plan\' '
         'for CSS outflow notifications and the \'Combined Wastewater Collection and Treatment System Plan of '
         'Operations\' for CSO notifications to ensure that the public is receiving adequate notification of CSS '
         'outflows and CSO\'s in accordance with the U.S. EPA\'s CSO Control Policy"')
Q_SF = ("NPDES CA0037664 and CA0037681 (San Francisco's combined system), under the CSO Control Policy's ninth minimum "
        "control, public notification of CSO occurrences and impacts (59 FR 18688; Clean Water Act 402(q)); the "
        "permits' own clause was not read")
SFPUC_MAP = "https://webapps.sfpuc.org/sapps/beachesandbay.html"
SFPUC_JSON = "https://infrastructure.sfwater.org/lims.asmx/getBeaches"
SFPUC_PAGE = "https://www.sfpuc.gov/programs/ocean-and-beach-monitoring"

AGENCY = [
    {"id": "ca-swrcb-ciwqs-spill-file", "agency": "California State Water Resources Control Board",
     "name": "California State Water Board (CIWQS sanitary sewer spill reports)", "channel_kind": "state_alert_page",
     "urls": [FILE_URL, INDEX_URL], "method": "html", "legal_basis": Q_GO, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": FEED, "publishes": "notices", "noun": "State page",
     "note": ("The Board's nightly file of every Category 1, 2 and 3 spill reported under the Statewide Sanitary Sewer "
              "Systems General Order since June 2023, with start, end once certified, a point, volumes and the "
              "receiving water; it covers every enrollee (public agencies, and private systems the Board requires to "
              "enroll). Drafts arrive within 3 business days of a spill (median 2 days from its start in 2026); the "
              "end and the receiving water come only with certification, within 15 days of the spill's end. "
              "Category 4 spills (under 50 gallons, no surface water) are reported as monthly counts only. "
              "(research/ca/report.md §2.2)"),
     "sources": [FEED, "ca-go-2022-0103-dwq"]},
    {"id": "ca-swrcb-sso-incident-map", "agency": "California State Water Resources Control Board",
     "name": "California State Water Board (sanitary sewer spill maps)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "notices",
     "note": ("Interactive maps of the same spill reports (https://www.waterboards.ca.gov/water_issues/programs/sso/"
              "sso_map/sso_pub.html); the map pages answer scripts with an Incapsula stub. The nightly file carries "
              "the same reports. Voluntary. (research/ca/report.md §2.2)"),
     "sources": ["ca-swrcb-sso-incident-map"]},
    {"id": "ca-caloes-spill-releases", "agency": "California Governor's Office of Emergency Services",
     "name": "Cal OES spill release reports", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "notices",
     "note": ("Cal OES receives the 2-hour notice of every spill of 1,000 gallons or more to waters of the State "
              "(Water Code 13271) and publishes spill releases on a script-driven dashboard "
              "(https://p.veoci.com/SpillReleases) and in yearly spreadsheets (latest found: 2022). It may be faster "
              "than the CIWQS file for large spills; not verified in the research (the dashboard needs a browser "
              "and its data service was not traced). Voluntary publication: the law requires notice to Cal OES, not "
              "publication. (research/ca/report.md §4)"),
     "sources": ["ca-caloes-spill-reports", "ca-water-code-13271"]},
    {"id": "ca-county-health-beach-hotlines", "agency": "County health officers (coastal counties)",
     "name": "County health officers: beach closure hotlines", "channel_kind": "local_health_page",
     "urls": [], "method": None, "legal_basis": Q_115885, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "status",
     "note": ("The public channel the law names for beach closures and postings, including those after a sewage "
              "release, is a telephone hotline in each coastal county: hotline only, with no duty to publish closures "
              "on the web. Several counties also post them on voluntary web pages (rows below). "
              "(research/ca/report.md §2.1)"),
     "sources": ["ca-hsc-115885"]},
    {"id": "ca-county-health-beach-signs", "agency": "County health officers (coastal counties)",
     "name": "County health officers: beach closure and posting signs", "channel_kind": "lights_signs_page",
     "urls": [], "method": None, "legal_basis": Q_115885, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "status",
     "note": ("Signs posted at the beach when it is closed or restricted after a known sewage release, until the "
              "source is eliminated and sampling allows reopening (17 CCR 7958). (research/ca/report.md §2.1)"),
     "sources": ["ca-hsc-115885"]},
    {"id": "ca-health-officer-notices", "agency": "Local health officers and directors of environmental health",
     "name": "Local health officers: sewage discharge notices", "channel_kind": "local_health_page",
     "urls": [], "method": None, "legal_basis": Q_5411, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown",
     "note": ("No web channel found: the health officer receives every discharge notice (per operator rows) and the "
              "law asks for no publication; the officer acts through closures, signs and the hotline. "
              "(research/ca/report.md §2.1)"),
     "sources": ["ca-hsc-5411-5"]},
    {"id": "ca-beachwatch-advisories", "agency": "California State Water Resources Control Board",
     "name": "California Beach Watch (beach postings and closures)", "channel_kind": "state_alert_page",
     "urls": ["https://data.ca.gov/dataset/beach-water-quality-postings-and-closures"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": BEACHWATCH_FEED, "publishes": "notices", "noun": "State page",
     "note": ("The Board's compilation of county beach postings and closures since 1985, with cause (sewage spill, "
              "CSO, rain) and dates, on data.ca.gov (ODC-By). About seven months behind (newest advisory 2026-03-06 "
              "when read): history, not current status. Voluntary publication. (research/ca/report.md §2.5)"),
     "sources": [BEACHWATCH_FEED]},
    {"id": "ca-swrcb-fhab-bloom-reports", "agency": "California State Water Resources Control Board",
     "name": "California freshwater harmful algal bloom reports (FHAB)", "channel_kind": "state_alert_page",
     "urls": ["https://data.ca.gov/dataset/surface-water-freshwater-harmful-algal-blooms"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FHAB_FEED, "publishes": "notices", "noun": "State page",
     "note": ("Bloom reports with advisory level (Caution, Warning, Danger) and dates, the data behind the map at "
              "mywaterquality.ca.gov. Blooms, not sewage. Voluntary. (research/ca/report.md §2.5)"),
     "sources": [FHAB_FEED]},
    {"id": "ca-sd-water-board-tijuana-flows", "agency": "San Diego Regional Water Quality Control Board",
     "name": "San Diego Water Board: Tijuana River transboundary flows", "channel_kind": "state_alert_page",
     "urls": ["https://www.waterboards.ca.gov/sandiego/water_issues/programs/tijuana_river_valley_strategy/"
              "sewage_issue.html"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "State page",
     "note": ("A table of transboundary sewage flows from Mexico in the Tijuana River valley (start, end, type, "
              "location, volume), updated about once a week. A shared water with Mexico: whether the site covers it "
              "at launch is the owner's call. Watched for changes; no records made. Voluntary. "
              "(research/ca/report.md §2.3)"),
     "sources": ["ca-sd-regional-board-ibwc-spills"]},
    {"id": "ca-sdcounty-beach-info", "agency": "County of San Diego Department of Environmental Health and Quality",
     "name": "San Diego County beach and bay water quality", "channel_kind": "local_health_page",
     "urls": ["https://cosdapps.sandiegocounty.gov/sdbeachinfo/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "status",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The county's current closures, advisories and warnings, including sewage-spill closures and the "
              "Tijuana River flows; an application page with no documented data service. Watched for changes; no "
              "records made. Voluntary (the law asks for a hotline). (research/ca/report.md §2.5)"),
     "sources": ["ca-sdcounty-beachinfo"]},
    {"id": "ca-lacounty-beach-grades", "agency": "Los Angeles County Department of Public Health",
     "name": "Los Angeles County beach water quality", "channel_kind": "local_health_page",
     "urls": ["http://publichealth.lacounty.gov/phcommon/public/eh/water_quality/beach_grades.cfm"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The county's beach status page (closures, rain advisories and grades); answered 200 on 2026-11-04. "
              "Watched for changes; no records made. Voluntary. (research/ca/report.md §2.5)"),
     "sources": ["ca-lacounty-beach"]},
    {"id": "ca-oc-beach-info", "agency": "OC Health Care Agency",
     "name": "Orange County beach closures and advisories (ocbeachinfo)", "channel_kind": "local_health_page",
     "urls": ["https://ocbeachinfo.com/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "status", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The county's closures (sewage spills) and advisories; answered 200 on 2026-11-04. Watched for changes; "
              "no records made. Voluntary. (research/ca/report.md §2.5)"),
     "sources": ["ca-ocbeachinfo"]},
    {"id": "ca-water-boards-email-subscriptions", "agency": "California State Water Resources Control Board",
     "name": "Water Boards e-mail subscriptions", "channel_kind": "email_list", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "signup_url": "https://www.waterboards.ca.gov/resources/email_subscriptions/",
     "note": ("Program lists, among them the Sanitary Sewer Systems program and the San Diego Region's Tijuana River "
              "updates; program notices, not spill alerts. Voluntary. Not signed up. (research/ca/report.md §2.3)"),
     "sources": ["ca-swrcb-sso-monthly-counts"]},
    {"id": "ca-usibwc-spill-listserv", "agency": "US Section, International Boundary and Water Commission",
     "name": "USIBWC transboundary spill notifications", "channel_kind": "email_list", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices",
     "note": ("E-mail notices of transboundary spills from Mexico (Tijuana River, New River); sign-up route not found "
              "(search only). Voluntary. (research/ca/report.md §2.3)"),
     "sources": ["ca-sd-regional-board-ibwc-spills"]},
    {"id": "ca-heal-the-bay-beach-report-card", "agency": "Heal the Bay", "name": "Heal the Bay Beach Report Card",
     "channel_kind": "group_results", "urls": ["https://beachreportcard.org/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "results",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Grades and closures for California beaches from the counties' sampling; a script application. Watched "
              "for changes; no records made. Voluntary republisher. (research/ca/report.md §2.5)"),
     "sources": ["ca-heal-the-bay"]},
    {"id": "ca-sd-coastkeeper-beach-advisories", "agency": "San Diego Coastkeeper",
     "name": "San Diego Coastkeeper beach advisories", "channel_kind": "group_results",
     "urls": ["https://www.sdcoastkeeper.org/beach-advisories/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "status",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Republishes San Diego County's closures and advisories. Watched for changes; no records made. "
              "Voluntary. (research/ca/report.md §2.5)"),
     "sources": ["ca-sdcoastkeeper-swim-guide"]},
    {"id": "ca-swim-guide", "agency": "Swim Guide (Swim Drink Fish)", "name": "Swim Guide listings for California",
     "channel_kind": "swim_guide", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "status",
     "note": ("Swim Guide listings for California beaches from affiliates' and counties' results; a script app. "
              "Voluntary republisher. (research/ca/report.md §2.5)"),
     "sources": ["ca-sdcoastkeeper-swim-guide"]},
    {"id": "ca-sf-beach-water-quality-open-data", "agency": "City and County of San Francisco (DataSF)",
     "name": "San Francisco beach water quality results (DataSF)", "channel_kind": "shared_site",
     "urls": ["https://data.sfgov.org/d/v3fv-x3ux"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "results", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("Sampling results behind SFPUC's beach postings; context, not notices. Watched for changes; no records "
              "made. Voluntary. (research/ca/report.md §2.5)"),
     "sources": ["ca-sf-beach-wq-opendata"]},
]


def base(**kw) -> dict:
    r = {"state": "CA", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


PRIVATE_FORMS = ("investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
                 "campground or resort", "private club", "business or industrial", "institution",
                 "facility (permittee not named)")


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "CA":
            continue
        name = op.get("name")
        priv = op.get("legal_form") in PRIVATE_FORMS
        who = " The law binds any person who causes or permits a discharge, public or private." if priv else ""
        rows.append(finish(base(
            id=f"{op['id']}-health-officer-notice", operator_id=op["id"], name=name, channel_kind="local_health_page",
            urls=[], method=None, legal_basis=Q_5411, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="unknown", records=False, noun="Health officer notice", sources=["ca-hsc-5411-5"],
            note=(f"No web form: {name}: notice of each sewage discharge to the local health officer or director of "
                  "environmental health as soon as it is known; the law does not require the officer to publish it. "
                  f"No web channel found.{who} (research/ca/report.md §2.1)"))))
    return rows


def cso_rows(dis: list[dict]) -> list[dict]:
    ids = {d["id"] for d in dis}
    rows = []
    if "ca-sfpuc" in ids:
        rows += [
            finish(base(id="ca-sfpuc-beach-map-cso-flag", operator_id="ca-sfpuc",
                        name="San Francisco Public Utilities Commission (beach map)", permit="CA0037664",
                        channel_kind="operator_page", urls=[SFPUC_MAP, SFPUC_JSON], method="json", legal_basis=Q_SF,
                        basis_kind="permit", monitored=False, unmonitored_reason="feed_ingested",
                        feed_source_id=SFPUC_FEED, publishes="status", noun="CSO map",
                        note=("SFPUC's beach and bay map: per station, 'Combined Sewer Discharge has occurred within "
                              "the last 24-72 hours' and the posting state, from an undocumented JSON service "
                              "(getBeaches); current state only, read hourly as a snapshot. "
                              "(research/ca/report.md §2.3)"),
                        sources=[SFPUC_FEED])),
            finish(base(id="ca-sfpuc-beach-signs", operator_id="ca-sfpuc",
                        name="San Francisco Public Utilities Commission (beach signs)", permit="CA0037664",
                        channel_kind="lights_signs_page", urls=[], method=None, legal_basis=Q_SF, basis_kind="permit",
                        monitored=False, unmonitored_reason="other", publishes="status",
                        note=("Signs go up at a beach 'whenever a Combined Sewer System discharge occurs that affects a "
                              "recreational beach' and stay 'until the discharge ceases'; SFPUC's hotline "
                              "1-877-SFBEACH gives the same. (research/ca/report.md §2.3)"),
                        sources=[SFPUC_FEED])),
            finish(base(id="ca-sfpuc-beach-email-alerts", operator_id="ca-sfpuc",
                        name="San Francisco Public Utilities Commission (beach e-mail alerts)", permit=None,
                        channel_kind="email_list", urls=[], method=None, legal_basis=None, basis_kind="voluntary",
                        monitored=False, unmonitored_reason="email_only", publishes="notices",
                        note=(f"E-mail alerts of beach postings, including combined sewer discharges, offered on {SFPUC_PAGE}; "
                              "sign-up route not found. Not signed up. Voluntary. (research/ca/report.md §2.3)"),
                        sources=[SFPUC_FEED])),
        ]
    if "ca-sacramento-css" in ids:
        rows.append(finish(base(
            id="ca-sacramento-css-cso-public-notification", operator_id="ca-sacramento-css",
            name="City of Sacramento (combined system notification)", permit="CA0079111", channel_kind="operator_page",
            urls=[], method=None, legal_basis=Q_SAC, basis_kind="permit", monitored=False, unmonitored_reason="other",
            publishes="unknown", records=False, noun="CSO public notification", sources=["ca-sacramento-css-permit"],
            note=("No web channel found: the City notifies downstream drinking-water agencies by phone, e-mail or fax "
                  "within 2 hours of a discharge to the Sacramento River; no public web notice of outflows or CSOs "
                  "was found. (research/ca/report.md §2.3)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + cso_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "CA")
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
    rep = run("--dry-run" in sys.argv[1:])
    print(json.dumps(rep, indent=1))
