"""Illinois rows of the notice register (data/notice-channels/il.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_il_register_rows.py [--dry-run]

The law (research/il/report.md §2.1 in the site repository; profile research/il/profile.json):
  - 40 CFR 122.38 (eCFR, fetched 2026-11-03), for the 43 Great Lakes Basin CSO permits EPA lists for Illinois (all in
    the Chicago area: the City of Chicago, MWRD's plants, Golf, Phoenix and the suburban general-permit coverages
    ILM5800xx; the operator rows whose notification_channel cites 40 CFR 122.38): (a)(3)(i) public notification
    "electronically, such as by text, email, social media alerts to subscribers or by posting a notice on its public
    access website" no later than 4 hours after becoming aware of a discharge; signs at outfalls and public access
    areas; notice to the local public health department within 4 hours; a supplemental notice within 7 days; an
    annual notice; under a public notification plan. MWRD's permits put the program in Special Condition 13.14 of the
    Stickney and Calumet permits (seen through MWRD's monitoring plan; the permit text was not read). MWRD sends CSO
    and diversion notices by e-mail and text through Smart911 and shows possible CSO activity on a daily map.
  - The other CSO permits (downstate): public notification under the permit (Nine Minimum Controls no. 8); no
    deadline found; permit texts not read.
  - Sanitary sewer overflows and bypasses: no Illinois statute or rule requires public notice; the permit's standard
    conditions require a report to Illinois EPA's regional office within 24 hours and a written report within 5 days
    (40 CFR 122.41(l)(6)), filed through EPA's NeT-SewerOverflow and published in EPA's overflow tables. One statewide
    row (every permittee, public or private: the permit conditions bind both alike) and EPA's tables as the feed row.

Rows
  - Per CSO operator (kind cso in data/dischargers.json):
      Great Lakes permittees: <id>-cso-public-notification (MWRD's e-mail and text alerts, email_only, the sign-up),
      <id>-cso-signs (signs_only) and <id>-health-department-notice (no web page).
      Other CSO permittees: <id>-cso-public-notification (permit, not searched; Arlington Heights' plan page and
      Bloomington-Normal's notice document are rows of their own where found).
  - Agency and voluntary rows: AGENCY below.
A rerun replaces every il- row it makes. Validated before writing.
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
CHECKED = "2026-11-04"
MWRD = "Metropolitan Water Reclamation District of Greater Chicago"
MWRD_PAGE = ("https://mwrd.org/community-action/you-can-help-prevent-flooding-and-protect-water-quality/"
             "combined-sewer-overflow-notification")
SIGNUP = "https://www.smart911.com/smart911/ref/reg.action?pa=mwrdcso"
APP = "https://mwrdgc.maps.arcgis.com/apps/instant/sidebar/index.html?appid=1a2bc307bc404d9e927528fd215da022"
LAYER = ("https://utility.arcgis.com/usrsvcs/servers/addf95280b254c1e8fe64dc8e35dfedc/rest/services/CSO/"
         "CSO_PossibleEvents/MapServer/0")
Q_GL = ('40 CFR 122.38(a)(3)(i): "As soon as possible, but no later than four (4) hours after becoming aware by monitoring, '
        'modeling or other means that a CSO discharge has occurred, the Great Lakes Basin CSO permittee shall provide '
        'public notification of CSO discharges. The Great Lakes Basin CSO permittee shall provide public notification of '
        'CSO discharges electronically, such as by text, email, social media alerts to subscribers or by posting a notice '
        'on its public access website"; MWRD permits IL0028053 and IL0028061, Special Condition 13.14 (public '
        'notification program; permit text not read)')
Q_SIGNS = ("40 CFR 122.38(a)(2): the Great Lakes Basin CSO permittee posts signage at its CSO outfalls and at public "
           "access areas potentially affected by its discharges")
Q_HEALTH = ("40 CFR 122.38(a)(3)(ii): notice to the local public health department, and other affected entities, "
            "within 4 hours of becoming aware of a CSO discharge")
Q_NMC = ("NPDES permit public notification condition for combined sewer overflows (Nine Minimum Controls no. 8, EPA's "
         "CSO Control Policy, 59 FR 18688); the Illinois permit texts were not read")
Q_SSO = ("NPDES permit standard conditions (40 CFR 122.41(l)(6)): report to Illinois EPA within 24 hours (Illinois EPA "
         "SSO form: \"Within 24 hours of the occurrence, notify the Illinois EPA regional wastewater staff by telephone, "
         "FAX, email or voice mail\") and a written report within 5 days, filed through EPA's NeT-SewerOverflow")
OWN_PAGES = {
    "ILM580006": {"urls": ["https://vah.com/government/departments/public_works/stormwater___flood_management/"
                           "combined_sewer_overflow_public_notification_plan_.php"], "method": "html",
                  "monitored": True, "unmonitored_reason": None, "publishes": "documents", "records": False,
                  "every_hours": 24, "channel_kind": "operator_page",
                  "note": ("The village's CSO public notification plan page (answered 200 on 2026-11-04); it points the "
                           "public to MWRD's alerts. (research/il/report.md §2.6, il-suburban-cso-notification-pages)")},
    "IL0027731": {"urls": [], "method": None, "monitored": False, "unmonitored_reason": "bot_wall",
                  "publishes": "unknown", "channel_kind": "operator_page",
                  "note": ("Bloomington's CSO notice document (https://bloomingtonil.gov/home/showpublisheddocument/52/"
                           "636955030167100000) answers 403 to the project user agent (2026-11-04); the channel it "
                           "describes was not traced. (il-bloomington-normal-cso-notice)")},
    "ILM580002": {"urls": [], "method": None, "monitored": False, "unmonitored_reason": "email_only",
                  "publishes": "notices", "channel_kind": "email_list", "signup_url": SIGNUP,
                  "note": ("Evanston's CSO public notification plan page has moved (404 on 2026-11-04 at "
                           "cityofevanston.org/.../cso-public-notification-plan); the suburban plans found point to "
                           "MWRD's e-mail and text alerts, which cover CSO events in MWRD's service area. Not signed up. "
                           "(il-evanston-cso-plan)")},
}
AGENCY = [
    {"id": "il-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "echo-sewer-overflow", "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): Illinois permittees file their "
              "24-hour and 5-day reports through NeT-SewerOverflow and EPA publishes them daily (1,687 Illinois reports "
              "from 267 permits since 2024-10-01 in the 2026-11-03 extract; median 3 days from start to receipt). "
              "Covers every operator in the state, public or private, except the Cook County CSO permittees, which file "
              "no CSO reports there. (research/il/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "il-epa-sobe-events"]},
    {"id": "il-iepa-sso-report", "agency": "Illinois Environmental Protection Agency", "name": "Illinois EPA",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_SSO, "basis_kind": "permit",
     "monitored": False, "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "noun": "Report to the state",
     "note": ("No web form: every permittee, public or private, reports a sanitary sewer overflow or bypass to Illinois "
              "EPA's regional office within 24 hours; no Illinois statute or rule requires the public to be told, and "
              "Illinois EPA does not post the reports. No web channel found; the reports reach the public through EPA's "
              "tables days later. (research/il/report.md §2.1)"),
     "sources": ["il-law-iepa-sso-form"]},
    {"id": "il-mwrd-possible-cso-events-map", "agency": MWRD, "name": MWRD, "channel_kind": "shared_site",
     "urls": [APP, LAYER], "method": "json", "legal_basis": Q_GL, "basis_kind": "permit", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "il-mwrd-possible-cso-events-layer",
     "publishes": "status", "noun": "Notification map",
     "note": ("MWRD's map of possible CSO events, \"updated daily\" and showing \"unconfirmed CSO and diversion "
              "activity\" at the outfalls MWRD monitors (273 of 441 in Cook County, for MWRD, the City of Chicago and the "
              "suburbs); reset nightly, with no public archive. Read hourly by the feed. (research/il/report.md §2.3)"),
     "sources": ["il-mwrd-possible-cso-events-layer"]},
    {"id": "il-mwrd-cso-notification-page", "agency": MWRD, "name": MWRD, "channel_kind": "shared_site",
     "urls": [MWRD_PAGE], "method": "html", "legal_basis": Q_GL, "basis_kind": "permit", "monitored": True,
     "unmonitored_reason": None, "publishes": "link_only", "link_text": "MWRD's alerts, map and reports",
     "records": False, "every_hours": 24, "noun": "Notification page",
     "note": ("MWRD's CSO notification page: \"CSO notifications are available via both email and SMS/text\" and the "
              "system \"provides notification of CSO events and waterway diversions to Lake Michigan within the MWRD "
              "service area\"; links the alert sign-up, the map, the event synopsis report and the Lake Michigan "
              "reversals table. Answered 200 on 2026-11-04. (research/il/report.md §2.3)"),
     "sources": ["il-mwrd-cso-alerts"]},
    {"id": "il-mwrd-cso-alerts", "agency": MWRD, "name": MWRD, "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": Q_GL, "basis_kind": "permit", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "signup_url": SIGNUP,
     "note": ("The 4-hour public notice for MWRD's and the suburban permittees' combined sewer overflows and the "
              "diversions to Lake Michigan goes out by e-mail and text through Smart911 (a third-party account; moved "
              "there 2025-06-17). Reporting (WTTW, 2025) says an alert names only that an overflow occurred somewhere in "
              "the MWRD system. Not signed up. (research/il/report.md §2.3)"),
     "sources": ["il-mwrd-cso-alerts"]},
    {"id": "il-mwrd-cso-synopsis-report", "agency": MWRD, "name": MWRD, "channel_kind": "shared_site", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "notices",
     "note": ("MWRD's CSO Event Synopsis Report (https://apps.mwrd.org/csoreports/): per-outfall tide-gate open and close "
              "times for every event day since April 2016, the only per-outfall record of Cook County's overflows. It is "
              "reached only through a form, a session and a report viewer; it is not read by an automated session. The "
              "request to MWRD: publish the same table as a download or a feed (a CSV per event day, or an API), with "
              "the posting time of each day. Voluntary posting. (research/il/report.md §2.3)"),
     "sources": ["il-mwrd-cso-event-synopsis"]},
    {"id": "il-mwrd-lake-michigan-reversals", "agency": MWRD, "name": MWRD, "channel_kind": "shared_site",
     "urls": ["https://mwrd.org/files/rdrct/Lake_Michigan_Reversals.pdf"], "method": "pdf", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "il-mwrd-lake-michigan-reversals", "publishes": "notices", "noun": "Data table",
     "note": ("MWRD's table of reversals of the waterways into Lake Michigan since 1985 (days and million gallons at "
              "O'Brien Lock, the Chicago River Controlling Works and the Wilmette gate); read by the feed. Voluntary "
              "posting. (research/il/report.md §2.3)"),
     "sources": ["il-mwrd-lake-michigan-reversals"]},
    {"id": "il-mwrd-iepa-quarterly-reports", "agency": MWRD, "name": MWRD, "channel_kind": "shared_site",
     "urls": ["https://www.mwrd.org/sites/default/files/2026-03/IEPA_Quarterly_Reports_2025.pdf"], "method": "pdf",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("MWRD's quarterly reports to Illinois EPA (2025), posted on its site; read for changes, for reconciling the "
              "map and the alerts. Answered 200 on 2026-11-04. Voluntary posting. (research/il/report.md §2.3)"),
     "sources": ["il-mwrd-iepa-quarterly-reports"]},
    {"id": "il-mwrd-pump-station-activity", "agency": MWRD, "name": MWRD, "channel_kind": "shared_site",
     "urls": ["https://mwrd.org/files/rdrct/PS_Activity_sort_current.xls"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other", "publishes": "unknown",
     "records": False,
     "note": ("MWRD's pumping-station activity workbook (answered 200 on 2026-11-04): pumping stations discharge to the "
              "waterways in storms, a path for combined sewage; a spreadsheet the monitor does not read; content not "
              "checked. Channel not researched beyond the link. Voluntary. (il-mwrd-pump-station-activity)"),
     "sources": ["il-mwrd-pump-station-activity"]},
    {"id": "il-idph-beachguard", "agency": "Illinois Department of Public Health",
     "name": "Illinois Department of Public Health (Illinois BeachGuard)", "channel_kind": "state_alert_page",
     "urls": ["https://idph.illinois.gov/envhealth/ilbeaches/public/RssFeed.aspx"], "method": "rss",
     "legal_basis": "Illinois Swimming Facility Act (210 ILCS 125) and the federal BEACH Act for Lake Michigan beaches, "
                    "as the research cites them (statute text not quoted)",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "il-idph-beachguard", "publishes": "status", "noun": "Beach advisories",
     "note": ("IDPH's list of beach advisories and closures in effect (licensed public and private beaches, Lake "
              "Michigan's included), entered by county health departments and park districts; read by the feed with each "
              "beach's page. Some entries are years old. (research/il/report.md §2.5)"),
     "sources": ["il-idph-beachguard"]},
    {"id": "il-chicago-beach-lab-data", "agency": "Chicago Park District (City of Chicago Data Portal)",
     "name": "Chicago Park District", "channel_kind": "feed",
     "urls": ["https://data.cityofchicago.org/resource/2ivx-z93u.json?$order=dna_sample_timestamp%20DESC&$limit=20"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "results", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Chicago's Lake Michigan beach bacteria results (qPCR enterococci and culture E. coli, with coordinates); "
              "results, not advisories: the Park District's swim status is published elsewhere (not traced). Answered "
              "200 on 2026-11-04. Voluntary. (research/il/report.md §2.5)"),
     "sources": ["il-chicago-beach-lab-data"]},
    {"id": "il-lake-county-beaches", "agency": "Lake County Health Department", "name": "Lake County Health Department",
     "channel_kind": "local_health_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "status",
     "note": ("Lake County's beach monitoring and advisories page (https://www.lakecountyil.gov/2385/Beach-Monitoring-and-"
              "Advisories) answers 403 to the project user agent (2026-11-04); its advisories also reach IDPH's "
              "BeachGuard, which the feed reads. Voluntary. (research/il/report.md §2.5)"),
     "sources": ["il-lake-county-beaches"]},
    {"id": "il-iepa-hab-program", "agency": "Illinois Environmental Protection Agency",
     "name": "Illinois EPA (harmful algal bloom program)", "channel_kind": "state_alert_page",
     "urls": ["https://epa.illinois.gov/topics/water-quality/monitoring/algal-bloom/2026-harmful-algal-bloom-program.html"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "unknown", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Illinois EPA's 2026 algal bloom program page (routine sites, the bloom report form and a dashboard whose "
              "data service was not traced). Blooms, not sewage. Answered 200 on 2026-11-04. Voluntary. "
              "(research/il/report.md §2.5)"),
     "sources": ["il-iepa-hab-program"]},
    {"id": "il-friends-of-the-chicago-river", "agency": "Friends of the Chicago River",
     "name": "Friends of the Chicago River", "channel_kind": "group_results",
     "urls": ["https://www.chicagoriver.org/get-involved/take-action/overflow-action-days"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "unknown", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Overflow Action Days: the group's call to cut water use when MWRD expects overflows. Answered 200 on "
              "2026-11-04. Voluntary. (research/il/report.md §2.6)"),
     "sources": ["il-friends-chicago-river-overflow-action"]},
    {"id": "il-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": ["https://www.theswimguide.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "results", "noun": "Swim Guide listing",
     "note": "Swim Guide listings for Illinois's Lake Michigan beaches. Voluntary; no API. (research/il/profile.json)",
     "sources": []},
]


def base(**kw) -> dict:
    r = {"state": "IL", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def great_lakes(op: dict) -> bool:
    return "40 CFR 122.38" in (op.get("notification_channel") or "")


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "IL" or op.get("kind") != "cso":
            continue
        name, permit, oid = op["name"], op.get("npdes_permit"), op["id"]
        if great_lakes(op):
            own = OWN_PAGES.get(permit)
            rows.append(finish(base(
                id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit=permit,
                channel_kind="email_list", urls=[], method=None, legal_basis=Q_GL, basis_kind="permit",
                monitored=False, unmonitored_reason="email_only", publishes="notices", signup_url=SIGNUP,
                noun="CSO public notification", sources=["il-law-40cfr122-38", "il-mwrd-cso-alerts"],
                note=(own or {}).get("note") or (
                    f"{name}'s 4-hour notice: MWRD's e-mail and text alerts (Smart911) cover CSO events in MWRD's "
                    "service area, the City of Chicago's and the suburbs' outfalls included; the permittee's own plan "
                    "was not read. Not signed up. (research/il/report.md §2.1, §2.3)"))))
            if own and own.get("monitored"):
                rows.append(finish(base(id=f"{oid}-cso-notification-plan-page", operator_id=oid, name=name,
                                        permit=permit, legal_basis=Q_GL, basis_kind="permit",
                                        noun="Notification page", sources=["il-suburban-cso-notification-pages"],
                                        **{k: v for k, v in own.items()})))
            rows.append(finish(base(
                id=f"{oid}-cso-signs", operator_id=oid, name=name, permit=permit, channel_kind="lights_signs_page",
                urls=[], method=None, legal_basis=Q_SIGNS, basis_kind="law", monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, noun="Outfall signs",
                sources=["il-law-40cfr122-38"],
                note=f"No web form: {name}'s signs at its outfalls and at public access areas. On site only.")))
            rows.append(finish(base(
                id=f"{oid}-health-department-notice", operator_id=oid, name=name, permit=permit,
                channel_kind="local_health_page", urls=[], method=None, legal_basis=Q_HEALTH, basis_kind="law",
                monitored=False, unmonitored_reason="other", publishes="unknown", records=False,
                noun="Health department notice", sources=["il-law-40cfr122-38"],
                note=(f"No web form: {name}'s notice of each CSO discharge to the local public health department within "
                      "4 hours; the rule does not require the department to publish it. No web channel found."))))
        else:
            own = OWN_PAGES.get(permit)
            if own and not own.get("monitored"):
                rows.append(finish(base(
                    id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit=permit,
                    legal_basis=Q_NMC, basis_kind="permit", noun="CSO public notification",
                    sources=["il-bloomington-normal-cso-notice"], records=False, **own)))
                continue
            rows.append(finish(base(
                id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit=permit,
                channel_kind="operator_page", urls=[], method=None, legal_basis=Q_NMC, basis_kind="permit",
                monitored=False, unmonitored_reason="other", publishes="unknown", records=False,
                noun="CSO public notification", sources=["il-epa-cso-inventory"],
                note=(f"No URL known (not searched): {name}'s CSO public notification under its permit was not read, "
                      "and its own pages were not searched; its overflow reports to Illinois EPA reach EPA's tables "
                      "when it files them there. (research/il/report.md §3)"))))
    chicago = next((op for op in dis if op.get("npdes_permit") == "IL0045012"), None)
    if chicago:
        rows.append(finish(base(
            id=f"{chicago['id']}-cso-warning-lights", operator_id=chicago["id"], name=chicago["name"],
            permit="IL0045012", channel_kind="lights_signs_page", urls=[], method=None, legal_basis=None,
            basis_kind="voluntary", monitored=False, unmonitored_reason="other", publishes="status", records=False,
            noun="Warning lights", sources=["il-chicago-cso-lights-pilot"],
            note=("Warning lights announced in 2025 for River Park, Clark Park, Ping Tom and Park 571 near the outfalls "
                  "the 2024 permit designates as sensitive areas; installation not confirmed; on site only unless the "
                  "City also publishes their state. (research/il/report.md §2.3)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "IL")
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
