"""Ohio rows of the notice register (data/notice-channels/oh.json), made from the law, the research and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_oh_register_rows.py [--dry-run]

The law (research/oh/report.md section 2.1 in the site repository; research/oh/profile.json):
  - No Ohio statute or rule requires public notice of a sewage discharge in general (no bill in the 136th General
    Assembly). OAC 3745-33-08(A)(12) (effective 2025-10-31) requires a permanent sign at each permitted outfall,
    bypass and CSO outfalls included; (F)(1) requires a major discharger within 3,000 feet of a lake intake or ten
    river miles upstream of a river intake to notify the public water supply operator as soon as practicable after a
    discharge begins. Overflows and bypasses are reported to Ohio EPA within 24 hours (permit standard conditions; a
    5-day follow-up form for SSOs; annual SSO reports in STREAMS): none of it is published.
  - Lake Erie basin CSO permittees (44 of the research's CSO rows, EPA's Great Lakes list) owe 40 CFR 122.38's public
    notice: an initial notice no later than four hours after becoming aware of a discharge, under a public
    notification plan. CSO permittees in the Ohio River basin notify under their permits' Nine Minimum Controls and
    consent decrees.
Rows
  - AGENCY: Ohio EPA's spills layer (read by the oh-epa-spills-opendata feed), the 24-hour report to Ohio EPA (not
    published), the outfall signs of (A)(12) (signs only), the water-supplier notice of (F)(1) (not public), ODH
    BeachGuard (read by the oh-odh-beachguard feed), the HAB program pages (moved; not reached), the SSO annual
    reports (documents, not read).
  - OPERATOR_CHANNELS: the operators' own channels the research found (NEORSD, Akron, Bowling Green and Columbus read
    by feeds, and Clyde's yearly report tables too; Toledo's status line and Lima's notification list watched;
    Lakewood's, Clyde's and MSD Cincinnati's map pages and Euclid's, Elyria's, Defiance's and Upper Sandusky's pages
    watched for health with no records made (Upper Sandusky's answered 404; MSD's map is a Power BI image). Each URL was answered on 2026-11-08 with one GET with the project user agent.
  - Every CSO permittee (89 permits, in 89 operator rows) gets a <id>-public-notice row: its own channel when listed
    above, else "not searched individually" (122.38 or the permit's Nine Minimum Controls as the basis).
  - The operators known only from their SSO annual reports (Dayton, Montgomery County, Wooster, Willoughby,
    Middlefield) get an annual-report row.
A rerun replaces every oh- row it makes. Validated before writing.
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
CHECKED = "2026-11-08"
OEPA = "Ohio Environmental Protection Agency"
ODH = "Ohio Department of Health"
Q_SIGNS = ("OAC 3745-33-08(A)(12): permanent signs \"At each outfall authorized under the NPDES permit. Outfalls covered "
           "by this provision include ... bypass or combined sewer overflow discharges\", naming the permittee, the "
           "permit and outfall numbers and a phone number")
Q_SUPPLY = ("OAC 3745-33-08(F)(1): a major discharger near a drinking-water intake must \"notify the public water supply "
            "operator as soon as practicable after a discharge begins that results from a spill, sanitary sewer "
            "overflow, bypass, upset, or combined sewer overflow\"")
Q_REPORT = ("Ohio NPDES permit standard conditions (40 CFR 122.41(l)(6)): noncompliance, including a sanitary sewer "
            "overflow or bypass, reported to Ohio EPA within 24 hours, with Ohio EPA's 5-day SSO follow-up form")
Q_122_38 = ("40 CFR 122.38 (Great Lakes CSO public notification): \"initial notification ... as soon as possible but no "
            "later than four hours after becoming aware\" of a combined sewer overflow discharge, under the permittee's "
            "public notification plan")
Q_NMC = ("NPDES permit {permit}: the CSO Nine Minimum Controls, public notification (EPA CSO Control Policy, 1994), and "
         "any consent decree")
Q_BEACH = ("BEACH Act of 2000 (33 U.S.C. 1346), for the Lake Erie beaches; Ohio's bathing beach program (ODH with local "
           "health districts and ODNR) for inland beaches (statute text not quoted)")
Q_SSO_ANNUAL = "the operator's NPDES permit: an annual SSO report (the permit text was not read)"
COLUMBUS_FAQ = ("https://www.columbus.gov/Services/Columbus-Water-Power/About-Columbus-Water-Power/"
                "The-Division-of-Water-Reclamation/WW-Treatment/Sewer-Overflow-Discharge-Information-SSOCSO/"
                "Sewer-Overflow-FAQs")

AGENCY = [
    {"id": "oh-epa-spills-layer", "agency": OEPA, "name": f"{OEPA}, Office of Emergency Response",
     "channel_kind": "state_alert_page",
     "urls": ["https://geo.epa.ohio.gov/arcgis/rest/services/EmergResponse/Spills2_OpenData/MapServer"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "oh-epa-spills-opendata", "publishes": "notices",
     "noun": "Spills layer",
     "note": ("Ohio EPA's open spills layer: every incident called in to the emergency response line since 2017, "
              "updated daily, with the spill's day, the report time, a point and the product (873 human sewage and "
              "sewage sludge cases on 2026-11-08). No operator, no start time, no end. Read daily by the feed. "
              "(oh-epa-spills-opendata)"), "sources": ["oh-epa-spills-opendata"]},
    {"id": "oh-epa-overflow-report", "agency": OEPA, "name": OEPA, "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": Q_REPORT, "basis_kind": "permit", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("No web page: every Ohio permittee reports a sewer overflow or bypass to Ohio EPA within 24 hours by "
              "e-mail or phone and files a 5-day follow-up for an SSO; annual SSO reports go into STREAMS (search only). "
              "None of these reports is published, and Ohio files nothing to EPA's sewer overflow tables (0 Ohio rows "
              "on 2026-11-03). Covers every Ohio operator in data/dischargers.json. "
              "(oh-epa-noncompliance-sso-notification)"),
     "sources": ["oh-epa-noncompliance-sso-notification", "oh-echo-sobe"]},
    {"id": "oh-outfall-signs", "agency": OEPA, "name": "Ohio NPDES permittees (outfall signs)",
     "channel_kind": "lights_signs_page", "urls": [], "method": None, "legal_basis": Q_SIGNS, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Outfall signs",
     "note": ("No web form: the rule requires a permanent sign at each permitted outfall a person can reach by land or "
              "by boat, CSO and bypass outfalls included, naming the permittee, the permit and outfall numbers and a "
              "phone number. A sign marks the outfall; it does not say when it discharges. Covers every Ohio permittee. "
              "(oh-law-oac-3745-33-08)"), "sources": ["oh-law-oac-3745-33-08"]},
    {"id": "oh-water-supply-notice", "agency": OEPA, "name": "Ohio major dischargers near drinking-water intakes",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": Q_SUPPLY, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "noun": "Notice to the water supplier",
     "note": ("No web page: the notice goes to the public water supply operator only (a major discharger within 3,000 "
              "feet of a lake intake or ten river miles upstream of a river intake), not to the public. "
              "(oh-law-oac-3745-33-08)"), "sources": ["oh-law-oac-3745-33-08"]},
    {"id": "oh-odh-beachguard", "agency": ODH, "name": f"{ODH} (BeachGuard)", "channel_kind": "state_alert_page",
     "urls": ["https://publicapps.odh.ohio.gov/beachguardpublic/"], "method": "json", "legal_basis": Q_BEACH,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "oh-odh-beachguard", "publishes": "notices", "noun": "Beach advisories",
     "note": ("BeachGuard's public pages and the JSON behind them: the bacteria and algal-bloom advisories in effect at "
              "Ohio's bathing beaches, entered by local health districts and ODNR, with start dates and points (5 on "
              "2026-11-08). Read hourly by the feed. (oh-odh-beachguard)"), "sources": ["oh-odh-beachguard"]},
    {"id": "oh-epa-hab-program", "agency": OEPA, "name": f"{OEPA} (harmful algal blooms)",
     "channel_kind": "state_alert_page", "urls": ["https://www.ohioalgaeinfo.com/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False, "noun": "Algal bloom page",
     "note": ("Ohio's algal bloom information site redirected to a missing page on epa.ohio.gov on 2026-11-03: not "
              "verified in the research; recreational bloom advisories are read from BeachGuard. (oh-epa-hab-program)"),
     "sources": ["oh-epa-hab-program"]},
]

# the operators' own channels (by permit), each answered on 2026-11-08 unless the note says otherwise
OPERATOR_CHANNELS = {
    "OH0043991": {"suffix": "cso-alerts-map", "channel_kind": "operator_page",
                  "urls": ["https://www.neorsd.org/cso-alerts-map-and-status-of-outfalls/"], "method": "json",
                  "monitored": False, "unmonitored_reason": "feed_ingested",
                  "feed_source_id": "oh-neorsd-cso-notification-map", "publishes": "status", "noun": "CSO alerts map",
                  "sources": ["oh-neorsd-cso-notification-map"],
                  "note": ("NEORSD's CSO alerts map: each of 112 outfalls with its last wet- and dry-weather overflow "
                           "(start, end, volume), metered at 24 and modelled at 88, updated hourly; \"for display "
                           "purposes only\". Read hourly by the feed. (oh-neorsd-cso-notification-map)")},
    "OH0023833": {"suffix": "overflow-status", "channel_kind": "operator_page",
                  "urls": ["https://www.akronwaterwaysrenewed.com/overflow-status"], "method": "json",
                  "monitored": False, "unmonitored_reason": "feed_ingested",
                  "feed_source_id": "oh-akron-cso-notifications", "publishes": "status",
                  "noun": "Overflow status map", "sources": ["oh-akron-cso-notifications"],
                  "note": ("Akron's overflow status map: 28 sites with a status (overflowing or not), the receiving "
                           "water and per-site PDFs; the real-time data \"has not yet been reviewed for accuracy\". "
                           "Read hourly by the feed. (oh-akron-cso-notifications)")},
    "OH0024139": {"suffix": "cso-events", "channel_kind": "operator_page",
                  "urls": ["https://gis.bgohio.org/cso_events/dbo_cso_events_list.php"], "method": "html",
                  "monitored": False, "unmonitored_reason": "feed_ingested",
                  "feed_source_id": "oh-bowling-green-cso-events", "publishes": "notices", "noun": "CSO events table",
                  "sources": ["oh-bowling-green-cso-events"],
                  "note": ("Bowling Green's CSO events table: 37 overflows at Mercer and Poe roads since 2019 with begin, "
                           "end, rainfall and estimated volume (the last on 2026-07-21). Read daily by the feed. "
                           "(oh-bowling-green-cso-events)")},
    "OH0024732": {"suffix": "overflow-dashboard", "channel_kind": "operator_page", "urls": [COLUMBUS_FAQ],
                  "method": "json", "monitored": False, "unmonitored_reason": "feed_ingested",
                  "feed_source_id": "oh-columbus-sewer-overflow", "publishes": "notices", "noun": "Overflow dashboard",
                  "sources": ["oh-columbus-sewer-overflow"],
                  "note": ("Columbus's Sewer Overflow FAQs (moved under Columbus Water & Power; 403 to the research on "
                           "2026-11-03, 200 on 2026-11-08) link an ArcGIS dashboard of every recorded CSO and SSO by "
                           "discharge point, inspection date and volume (8,542 since 2002). Read daily by the feed. "
                           "(oh-columbus-sewer-overflow)")},
    "OH0027740": {"suffix": "cso-status", "channel_kind": "operator_page",
                  "urls": ["https://toledo.oh.gov/residents/water/quality/combined-sewer-overflows-csos"],
                  "method": "html", "monitored": True, "unmonitored_reason": None, "publishes": "status",
                  "every_hours": 1, "noun": "CSO status line", "sources": ["oh-toledo-cso"],
                  "status_pattern": r"There (?:are|is) (?:no )?combined sewer overflows?[^.]*\.",
                  "note": ("Toledo's CSO page: a dated status line (\"Last updated: 11/06/2026 There are no combined "
                           "sewer overflows at this time. The public will be notified within four hours of a "
                           "documented CSO event.\") and dated CSO report PDFs (latest 09 05 26). Watched hourly. "
                           "(oh-toledo-cso)")},
    "OH0026069": {"suffix": "cso-notifications", "channel_kind": "operator_page",
                  "urls": ["https://www.limaohio.gov/410/Combined-Sewer-Overflow-Activity-Report"], "method": "html",
                  "monitored": True, "unmonitored_reason": None, "publishes": "documents", "every_hours": 6,
                  "noun": "CSO notifications", "sources": ["oh-lima-cso-activity"],
                  "note": ("Lima's CSO activity page: each overflow's 4-hour public notification and 7-day supplemental "
                           "notification as dated PDFs (26 Mar, 1 Apr, 22 Apr 2026 ...). Watched for new entries; the "
                           "PDFs are not parsed. (oh-lima-cso-activity)")},
    "OH0026018": {"suffix": "cso-map", "channel_kind": "operator_page", "urls": ["https://cso.lakewoodoh.gov/"],
                  "method": "html", "monitored": True, "unmonitored_reason": None, "publishes": "status",
                  "every_hours": 24, "records": False, "noun": "CSO notification map", "sources": ["oh-lakewood-cso-map"],
                  "note": ("Lakewood's CSO notification map (a script map: status per site, in progress, past 48 hours, "
                           "no recent, unknown meter data); its data endpoint was not traced; the page says to contact the "
                           "city for a text list of overflow locations. Watched for health and changes; no records "
                           "are made from it. (oh-lakewood-cso-map)")},
    "OH0024686": [
        {"suffix": "cso-map", "channel_kind": "operator_page", "urls": ["https://cso.clydeohio.org/"],
         "method": "html", "monitored": True, "unmonitored_reason": None, "publishes": "status", "every_hours": 24,
         "records": False, "noun": "CSO notification system", "sources": ["oh-clyde-cso-notification"],
         "note": ("Clyde's CSO notification system (a script map with notification plan PDFs). Watched for health and "
                  "changes; the overflows are read from the yearly report pages. (oh-clyde-cso-notification)")},
        {"suffix": "cso-reports", "channel_kind": "operator_page",
         "urls": ["https://cso.clydeohio.org/templates/cso-report.php?year=2026"], "method": "html",
         "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "oh-clyde-cso-notification",
         "publishes": "notices", "noun": "Yearly CSO report", "sources": ["oh-clyde-cso-notification"],
         "note": ("Clyde's yearly CSO report pages: each overflow of its one CSO (Raccoon Creek) with start, end, "
                  "rainfall and volume, 2017 on (9 to 2026-04-01). Read daily by the feed; the page's staff contact is "
                  "not read. (oh-clyde-cso-notification)")}],
    "OH0105457": {"suffix": "cso-activity-map", "channel_kind": "operator_page",
                  "urls": ["https://msdgc.org/programs/cso-notification-program/"], "method": "html",
                  "monitored": True, "unmonitored_reason": None, "publishes": "status", "every_hours": 24,
                  "records": False, "noun": "CSO activity map", "sources": ["oh-msdgc-cso-activity-map"],
                  "note": ("MSD of Greater Cincinnati's CSO activity map is a Power BI embed (outfalls active now or in "
                           "the past 72 hours, hourly) with no machine-readable output; MSD advises avoiding contact "
                           "with streams for 72 hours after rain. The page is watched for health and changes; the map "
                           "itself shows only as an image. (oh-msdgc-cso-activity-map)")},
    "OH0031062": {"suffix": "cso-notification", "channel_kind": "operator_page",
                  "urls": ["https://www.cityofeuclid.gov/combined-sewer-overflow-public-notification"],
                  "method": "html", "monitored": True, "unmonitored_reason": None, "publishes": "none",
                  "every_hours": 24, "records": False, "noun": "CSO notification page",
                  "sources": ["oh-euclid-cso-notification"],
                  "note": ("Euclid's CSO public notification page: its 17 CSO structures and the notification plan; no "
                           "event list seen. Watched for changes. (oh-euclid-cso-notification)")},
    "OH0025003": {"suffix": "cso-page", "channel_kind": "operator_page",
                  "urls": ["https://www.cityofelyria.org/department/wastewater/combined-sewer-overflow/"],
                  "method": "html", "monitored": True, "unmonitored_reason": None, "publishes": "documents",
                  "every_hours": 24, "records": False, "noun": "CSO page", "sources": ["oh-elyria-cso"],
                  "note": ("Elyria's CSO page: annual CSO reports, the notification plan and a link to the Lorain County "
                           "emergency alerting system; Elyria's Ordinance 521.11 bans swimming in the Black River in "
                           "the city. Watched for changes. (oh-elyria-cso)")},
    "OH0024899": {"suffix": "cso-page", "channel_kind": "operator_page",
                  "urls": ["https://cityofdefiance.com/296/Combined-Sewer-Overflows-CSO"], "method": "html",
                  "monitored": True, "unmonitored_reason": None, "publishes": "unknown", "every_hours": 24,
                  "records": False, "noun": "CSO page", "sources": ["oh-defiance-cso"],
                  "note": ("Defiance's CSO page (connection reset to the research on 2026-11-03; 200 on 2026-11-08). "
                           "Watched for changes. (oh-defiance-cso)")},
    "OH0020001": {"suffix": "cso-reports", "channel_kind": "operator_page",
                  "urls": ["https://www.uppersanduskyoh.com/cso-reports-2024"], "method": "html", "monitored": True,
                  "unmonitored_reason": None, "publishes": "documents", "records": False, "every_hours": 24,
                  "noun": "CSO reports",
                  "sources": ["oh-upper-sandusky-cso-reports"],
                  "note": ("Upper Sandusky's yearly CSO public notification report pages (2023 to 2025 per search); the "
                           "2024 page answered 404 on 2026-11-08; watched, so its health shows whether it returns. "
                           "(oh-upper-sandusky-cso-reports)")},
}
PRIVATE = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
           "campground or resort", "private club", "business or industrial", "institution",
           "facility (permittee not named)"}


def base(**kw) -> dict:
    r = {"state": "OH", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows, by_permit = [], {}
    for op in dis:
        if op.get("state") == "OH":
            for p in op.get("npdes_permits") or []:
                by_permit[p] = op
    for permit, chs in OPERATOR_CHANNELS.items():
        op = by_permit.get(permit)
        if not op:
            raise SystemExit(f"{permit} is in no Ohio row of data/dischargers.json: run scripts/add_oh_operators.py")
        for ch in chs if isinstance(chs, list) else [chs]:
            x = dict(ch)
            suffix = x.pop("suffix")
            lake_erie = bool(op.get("great_lakes_basin"))
            rows.append(finish(base(id=f"{op['id']}-{suffix}", operator_id=op["id"], name=op["name"], permit=permit,
                                    legal_basis=Q_122_38 if lake_erie else Q_NMC.format(permit=permit),
                                    basis_kind="law" if lake_erie else "permit", **x)))
    own = {r["operator_id"] for r in rows}
    for op in dis:
        if op.get("state") != "OH" or "oh" not in (op.get("source_areas") or []):
            continue
        if op.get("kind") == "cso":
            if op["id"] in own:
                continue                 # its own channel row above is its public notice
            lake_erie = bool(op.get("great_lakes_basin"))
            permit = op.get("npdes_permit")
            private = " The permit binds the permittee, public or private." if op.get("legal_form") in PRIVATE else ""
            rows.append(finish(base(
                id=f"{op['id']}-public-notice", operator_id=op["id"], name=op["name"], permit=permit,
                channel_kind="operator_page", urls=[], method=None,
                legal_basis=Q_122_38 if lake_erie else Q_NMC.format(permit=permit),
                basis_kind="law" if lake_erie else "permit", monitored=False, unmonitored_reason="other",
                publishes="unknown", records=False, noun="Notice to the public",
                sources=["oh-law-40cfr122-38" if lake_erie else "oh-epa-cso-inventory", "oh-epa-gl-cso-ohio"],
                note=(("No URL known (not searched individually): as a combined sewer permittee in the Lake Erie basin "
                       "it owes an initial public notice within four hours of becoming aware of a discharge, under its "
                       "public notification plan; whether it posts the notices online was not checked." if lake_erie
                       else "No URL known (not searched individually): its public notice of combined sewer overflows "
                       "rests on its permit's Nine Minimum Controls and any consent decree; whether it posts notices "
                       "online was not checked.") + private))))
        elif op.get("kind") == "sso" and not op.get("npdes_permits"):
            rows.append(finish(base(
                id=f"{op['id']}-sso-annual-report", operator_id=op["id"], name=op["name"], permit=None,
                channel_kind="operator_page", urls=[], method=None, legal_basis=Q_SSO_ANNUAL, basis_kind="permit",
                monitored=False, unmonitored_reason="other", publishes="documents", records=False,
                noun="Annual SSO report", sources=["oh-sso-annual-reports"],
                note=("No web form read: the operator posts a yearly SSO report as a PDF (search only); it summarises "
                      "the year, not single overflows, and was not read (not verified in the research). "
                      "(oh-sso-annual-reports)"))))
    return rows


def rows_for(dis: list[dict]) -> list[dict]:
    return [finish(base(**r)) for r in AGENCY] + operator_rows(dis)


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = rows_for(dis)
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "OH")
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
