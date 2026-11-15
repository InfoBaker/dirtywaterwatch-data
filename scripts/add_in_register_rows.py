"""Indiana rows of the notice register (data/notice-channels/in.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_in_register_rows.py [--dry-run]

The law (research/in/report.md §2.1 in the site repository; research/in/profile.json):
  - 327 IAC 5-2.1-5 and -6 (read on Cornell LII, 2026-11-03): a CSO community notifies the affected public, local health
    departments, drinking water suppliers with intakes within ten river miles downstream, and those who ask after its
    annual March newspaper notice, whenever an overflow is occurring or imminent, "in a manner that is mutually
    agreeable to the recipient and the CSO community", and posts signs at public access points. No web channel and no
    deadline.
  - 327 IAC 5-2.2 applies 40 CFR 122.38 to CSO permittees in the Great Lakes basin: a public notice within four hours,
    a supplemental notice within seven days and an annual notice, by the means the permittee's plan names.
  - Overflows, bypasses and sewage basement backups are reported to IDEM within 24 hours on State Form 48373 (IDEM's
    reporting page, read 2026-11-14); IDEM files them in its Virtual File Cabinet and publishes no list. No public
    notice duty for them was found.
Rows
  - Per operator (every Indiana row of data/dischargers.json): <id>-idem-report, the 24-hour report to IDEM (no list).
  - Per combined sewer operator: <id>-cso-notice, the 327 IAC 5-2.1 notice to those who ask (by e-mail, telephone or
    as agreed: no web channel); and, in the Lake Michigan or Lake Erie basin, <id>-great-lakes-notice, the four-hour
    notice of 40 CFR 122.38, unless the operator's own channels below are read (their rows carry that rule).
  - Statewide: EPA's overflow tables and monthly CSO discharge monitoring reports (feeds), IDEM's intake and Virtual
    File Cabinet, the CSO signs, IDEM's cyanobacteria layer (feed), BeachAlert (sign-in), DNR's advisories page (watched).
  - Operators' own channels (fetched 2026-11-14): Fort Wayne (bot wall), South Bend, Hammond, Mishawaka (X account and
    yearly PDFs), La Porte (no connection), Waterloo (start and end PDFs), Goshen (dated notice posts), Citizens Energy
    Group (e-mail warnings), Evansville, Kendallville and Speedway (bot walls).
A rerun replaces every in- row it makes. Validated before writing.
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
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
IDEM_PAGE = "https://www.in.gov/idem/cleanwater/wastewater-compliance/sewer-bypassoverflow-incident-reporting/"
VFC = "https://www.in.gov/idem/legal/public-records/virtual-file-cabinet"
Q_521 = ('327 IAC 5-2.1-5(d): "Notification must be provided whenever information from a reliable source indicates '
         'that: (1) a discharge or discharges from one (1) or more combined sewer overflow outfalls is occurring; or (2) '
         'a discharge ... is imminent based on predicted or actual precipitation or a related event"; 327 IAC 5-2.1-6: '
         'notice to those who ask after the March newspaper notice "in a manner that is mutually agreeable to the '
         'recipient and the CSO community", and signs at public access points')
Q_522 = ('327 IAC 5-2.2-1: "The requirements of this rule and 40 CFR 122.38 apply to a permittee authorized to discharge '
         'a combined sewer overflow to the Great Lakes Basin": a public notice within four hours of becoming aware of a '
         'discharge, a supplemental notice within seven days, and an annual notice')
Q_REPORT = ("IDEM's sewer bypass/overflow reporting instructions (the NPDES permit's standard conditions; 40 CFR "
            "122.41(l)(6)): an overflow, bypass or sewage basement backup is reported to IDEM within 24 hours on State "
            "Form 48373")
GREAT_LAKES = ("Southeastern Lake Michigan", "Southwestern Lake Michigan", "Western Lake Erie")

AGENCY = [
    {"id": "in-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "echo-sewer-overflow", "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables: IDEM's reports are not sent here yet (IDEM says a move to "
              "EPA's NeT-SewerOverflow system is coming). 2026-11-12 extract: one Indiana report, Shelbyville's plant "
              "bypass of 2026-08-12 to 2026-08-13 (5,055,000 gallons, Big Blue River), filed through EPA's own system."),
     "sources": ["in-echo-sobe"]},
    {"id": "in-epa-echo-cso-dmr", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (discharge monitoring reports)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/trends/loading-tool/water-pollution-search"], "method": "json",
     "legal_basis": "327 IAC 5-2.1-7: notification efforts and overflows documented on the monthly CSO discharge "
                    "monitoring report", "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "in-echo-dmr-cso", "publishes": "results", "noun": "Data feed",
     "note": ("Each combined sewer outfall's monthly totals (number of discharges, hours, million gallons) from the "
              "operators' discharge monitoring reports, read per permit from ECHO's effluent-chart service: 4,484 "
              "outfall-months with a discharge from 73 of 91 permits, January 2025 to October 2026 (2026-11-14). Month "
              "precision, a median 24 days after the month."),
     "sources": ["in-echo-dmr-cso"]},
    {"id": "in-idem-overflow-reports", "agency": "Indiana Department of Environmental Management",
     "name": "Indiana Department of Environmental Management (bypass and overflow reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "permit",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": (f"Reports go to IDEM by e-mail on State Form 48373 ({IDEM_PAGE}); IDEM files each with the facility's "
              f"documents in its Virtual File Cabinet ({VFC}), a document search by facility, and publishes no list or "
              "feed of overflows; no web channel found. An archive of 2005 to 2016 reports is posted as a ZIP of county "
              "lists. IDEM says reporting will move to EPA's NeT-SewerOverflow system."),
     "sources": ["in-idem-bypass-overflow-reporting", "in-idem-vfc"]},
    {"id": "in-cso-signs", "agency": "Indiana combined sewer communities",
     "name": "Indiana combined sewer communities (signs at access points)", "channel_kind": "lights_signs_page",
     "urls": [], "method": None, "legal_basis": Q_521, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False,
     "note": ("327 IAC 5-2.1-6 signs at boat ramps, bridges, parks, school yards and greenways: \"Caution-Sewage or "
              "Wastewater pollution. Sewage or Wastewater may be in this water during and for several days after "
              "periods of rainfall or snow melt.\" Signs only."),
     "sources": ["in-law-327-iac-5-2-1"]},
    {"id": "in-idem-cyanobacteria", "agency": "Indiana Department of Environmental Management",
     "name": "Indiana Department of Environmental Management (Blue-Green Algae)", "channel_kind": "feed",
     "urls": ["https://www.in.gov/idem/algae/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "in-idem-cyanobacteria",
     "publishes": "results", "noun": "Data feed",
     "note": ("IDEM's beach samples with IDEM's advisory level for each (1,717 samples at 29 beaches, 2010 to "
              "2026-09-14), read from the dashboard's public layer. Blooms, not sewage. Voluntary."),
     "sources": ["in-idem-cyanobacteria"]},
    {"id": "in-idem-beachalert", "agency": "Indiana Department of Environmental Management",
     "name": "Indiana Department of Environmental Management (BeachAlert)", "channel_kind": "state_alert_page",
     "urls": ["https://portal.idem.in.gov/BeachAlert/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other", "publishes": "unknown",
     "note": ("The Lake Michigan and inland beach advisories and closures (an E. coli result above 235 cfu/100 mL makes "
              "the beach manager post an alert), in a Power Apps portal whose page loads its records by script from an "
              "entity-grid service and a beach map; the page alone shows only templates, and the data calls were not "
              "verified in the research (2026-11-14), so whether the records need a sign-in is not settled."),
     "sources": ["in-idem-beachalert"]},
    {"id": "in-dnr-advisories-closings", "agency": "Indiana Department of Natural Resources",
     "name": "Indiana Department of Natural Resources (state park advisories and closings)",
     "channel_kind": "state_alert_page", "urls": ["https://www.in.gov/dnr/state-parks/parks-lakes/advisories-and-closings/"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("State park alerts by property: road and trail closures, beach seasons, and a standing blue-green algae "
              "note at most lakes (\"Found in lakes year round. Don't drink the water. Shower after you swim.\"), which "
              "is general advice, not a report of a bloom. Watched for a dated algae or swimming alert; no records."),
     "sources": ["in-dnr-advisories-closings"]},
]
OWN = [
    {"id": "in-fort-wayne-cso-notifications", "operator_id": "in-city-of-fort-wayne", "permit": "IN0032191",
     "name": "City of Fort Wayne (City Utilities)", "channel_kind": "operator_page",
     "urls": ["https://utilities.cityoffortwayne.org/sewer-system/cso-notifications"], "method": "html",
     "legal_basis": Q_522, "basis_kind": "law", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "documents",
     "note": ("A summary of the past seven days' overflows (location, start, end, estimated volume) each Wednesday as a "
              "PDF, and a yearly report; the host answers 403 behind a Cloudflare check to this client (2026-11-14)."),
     "sources": ["in-fort-wayne-cso-notifications"]},
    {"id": "in-south-bend-cso-email", "operator_id": "in-city-of-south-bend", "permit": "IN0024520",
     "name": "City of South Bend", "channel_kind": "email_list", "urls": [], "method": None, "legal_basis": Q_522,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "email_only", "publishes": "notices",
     "signup_url": "https://southbendin.gov/department/public-works/utilities-division/waste-water/",
     "note": "E-mail CSO notifications to people who sign up by telephone; not subscribed.",
     "sources": ["in-south-bend-cso"]},
    {"id": "in-south-bend-cso-page", "operator_id": "in-city-of-south-bend", "permit": "IN0024520",
     "name": "City of South Bend", "channel_kind": "operator_page",
     "urls": ["https://southbendin.gov/department/public-works/utilities-division/waste-water/"], "method": "html",
     "legal_basis": Q_522, "basis_kind": "law", "monitored": True, "unmonitored_reason": None, "publishes": "documents",
     "records": False, "every_hours": 24, "noun": "Notification page",
     "note": ("The public notification plan, the 2025 CSO annual public notice and the 2025 monthly reports of "
              "operation, as PDFs; watched for new reports."),
     "sources": ["in-south-bend-cso"]},
    {"id": "in-hammond-cso-email", "operator_id": "in-sanitary-district-of-hammond", "permit": "IN0023060",
     "name": "Sanitary District of Hammond", "channel_kind": "email_list", "urls": [], "method": None,
     "legal_basis": Q_521, "basis_kind": "law", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "signup_url": "https://www.hammondsd.com/cso-notification-plan/",
     "note": "E-mail notice when the combined sewers discharge, to anyone who asks by post; not subscribed.",
     "sources": ["in-hammond-cso-notification"]},
    {"id": "in-hammond-cso-page", "operator_id": "in-sanitary-district-of-hammond", "permit": "IN0023060",
     "name": "Sanitary District of Hammond", "channel_kind": "operator_page",
     "urls": ["https://www.hammondsd.com/cso-notification-plan/"], "method": "html", "legal_basis": Q_522,
     "basis_kind": "law", "monitored": True, "unmonitored_reason": None, "publishes": "documents", "records": False,
     "every_hours": 24, "noun": "Notification page",
     "note": "The notification plan and the yearly CSO notice; watched for a change.",
     "sources": ["in-hammond-cso-notification"]},
    {"id": "in-mishawaka-cso-alerts-x", "operator_id": "in-city-of-mishawaka", "permit": "IN0025640",
     "name": "City of Mishawaka (Mishawaka Utilities)", "channel_kind": "social", "urls": ["https://x.com/CSOAlerts"],
     "method": "html", "legal_basis": Q_522, "basis_kind": "law", "monitored": False, "unmonitored_reason": "login",
     "publishes": "notices",
     "note": ("Mishawaka's CSO alerts are posted on an X account (@CSOAlerts), which X shows only to signed-in readers; "
              "the city's page says the initial notice comes within four hours and a supplemental notice within seven "
              "days."),
     "sources": ["in-mishawaka-cso"]},
    {"id": "in-mishawaka-cso-page", "operator_id": "in-city-of-mishawaka", "permit": "IN0025640",
     "name": "City of Mishawaka (Mishawaka Utilities)", "channel_kind": "operator_page",
     "urls": ["https://mishawaka.in.gov/government/departments/mishawaka-utilities/wastewater/cso-information/"],
     "method": "html", "legal_basis": Q_522, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 24, "noun": "Notification page",
     "note": ("The 2025 CSO annual report (a date-by-outfall table with hours and modelled volumes) and the outfall "
              "map, as PDFs; watched for the next."),
     "sources": ["in-mishawaka-cso"]},
    {"id": "in-la-porte-cso-status", "operator_id": "in-city-of-la-porte", "permit": "IN0025577",
     "name": "City of La Porte", "channel_kind": "operator_page",
     "urls": ["https://www.cityoflaporte.com/departments/laporte-utilties/wastewater-division/combined-sewer-overflow-status"],
     "method": "html", "legal_basis": Q_522, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "every_hours": 24, "noun": "Notification page",
     "note": ("A current status (\"NOT overflowing\" in the research of 2026-11-09) and a list of past overflows with "
              "dates and volumes (the last on 2025-08-19, 1.1 million gallons, which EPA's monthly report for August "
              "2025 matches). The host did not accept a connection from this build on 2026-11-14 (two tries): watched "
              "daily; not yet read into records."),
     "sources": ["in-laporte-cso-status"]},
    {"id": "in-waterloo-cso-notices", "operator_id": "in-town-of-waterloo", "permit": "IN0020711",
     "name": "Town of Waterloo", "channel_kind": "operator_page", "urls": ["https://waterlooin.gov/cso-policy/"],
     "method": "html", "legal_basis": Q_522, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Notification page",
     "note": ("Start and end notices as PDFs linked by date (\"CSO Start 3-11-2026\", \"CSO End 3-20-2026\"; three "
              "pairs in March and April 2026), the 2025 annual notice and monthly reports of operation. The PDFs' text "
              "uses a font this build's reader cannot decode, so the notices are watched, not yet read into records."),
     "sources": ["in-waterloo-cso-posts"]},
    {"id": "in-goshen-cso-notice", "operator_id": "in-city-of-goshen", "permit": "IN0025755",
     "name": "City of Goshen", "channel_kind": "operator_page", "urls": ["https://goshen.in.gov/cso-notice/"],
     "method": "html", "legal_basis": Q_522, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Notification page",
     "note": ("A dated CSO notice post naming the permit and outfall (the one seen is of 2018-02-20) with the city's "
              "notification policy: all its overflows reach the Elkhart River downstream of the plant. Watched."),
     "sources": ["in-goshen-cso-notice"]},
    {"id": "in-citizens-cso-warnings", "operator_id": "in-citizens-energy-group-cwa-authority", "permit": "IN0023183",
     "name": "CWA Authority, Inc. (Citizens Energy Group), Indianapolis", "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": Q_521, "basis_kind": "law", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "likelihood",
     "note": ("E-mail CSO warnings when about a quarter inch of rain or more is forecast (Citizens' 2018 post, which "
              "now redirects to the company's home page); the sign-up route not found in this pass."),
     "sources": ["in-citizens-cso-warnings"]},
    {"id": "in-evansville-cso-page", "operator_id": "in-city-of-evansville", "permit": "IN0032956",
     "name": "City of Evansville (Evansville Water and Sewer Utility)", "channel_kind": "operator_page",
     "urls": ["https://ewsu.com/water-sewer/sewer-wastewater/combined-sewer-overflow/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The utility's CSO page explains overflows to the Ohio River and Pigeon Creek (about 50 a year) and its "
              "Renew Evansville plan; no event notices on it (2026-11-14). Watched."),
     "sources": ["in-evansville-ewsu-clear-path"]},
    {"id": "in-kendallville-cso", "operator_id": "in-city-of-kendallville", "permit": "IN0020656",
     "name": "City of Kendallville", "channel_kind": "operator_page",
     "urls": ["https://www.kendallvillein.gov/departments/wastewater/cso.aspx"], "method": "html",
     "legal_basis": Q_522, "basis_kind": "law", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "unknown", "note": "The city's CSO page answers 403 to this client (2026-11-14).",
     "sources": ["in-kendallville-cso"]},
    {"id": "in-speedway-cso", "operator_id": "in-town-of-speedway", "permit": "IN0032972", "name": "Town of Speedway",
     "channel_kind": "operator_page", "urls": ["https://www.speedwayin.gov/node/1301"], "method": "html",
     "legal_basis": Q_521, "basis_kind": "law", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "unknown",
     "note": ("The town's CSO public notification page answers 403 to this client (2026-11-14); search results say "
              "notices go by e-mail on request or by calling the plant."),
     "sources": ["in-speedway-cso"]},
]


def base(**kw) -> dict:
    r = {"state": "IN", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def great_lakes_permits() -> set[str]:
    out = set()
    for r in json.loads((ROOT / "data" / "outfalls-in.json").read_text())["outfalls"]:
        if r.get("basin") in GREAT_LAKES and not str(r.get("outfall_status") or "").startswith("CLS"):
            out.add(r["npdes_permit"])
    return out


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    gl = great_lakes_permits()
    own = {r["operator_id"] for r in OWN}
    for op in dis:
        if op.get("state") != "IN":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        permit = ps[0] if ps else None
        rows.append(finish(base(
            id=f"{oid}-idem-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=Q_REPORT, basis_kind="permit", monitored=False,
            unmonitored_reason="other", publishes="none", records=False, noun="Report to the state",
            sources=["in-idem-bypass-overflow-reporting"],
            note=(f"{name} reports an overflow, bypass or sewage basement backup to IDEM within 24 hours on State Form "
                  "48373; IDEM files the reports in its Virtual File Cabinet and publishes no list; no web channel "
                  "found. No public notice is required for these. The permit itself was not read: the standard "
                  "condition is assumed."))))
        if op.get("kind") != "cso":
            continue
        cso_permit = next((p for p in ps if p.startswith("IN")), permit)
        rows.append(finish(base(
            id=f"{oid}-cso-notice", operator_id=oid, name=name, permit=cso_permit, channel_kind="email_list",
            urls=[], method=None, legal_basis=Q_521, basis_kind="law", monitored=False,
            unmonitored_reason="email_only", publishes="notices", sources=["in-law-327-iac-5-2-1"],
            note=(f"{name} must notify, whenever an overflow is occurring or imminent, the people who asked after its "
                  "March newspaper notice, by e-mail, telephone or another agreed means, and post signs; no web channel "
                  "is required." + (" Its own channels are listed in their rows." if oid in own else
                                    " Its own channel was not searched individually.")))))
        if gl & set(ps) and oid not in own:     # an operator whose own channels are read: those rows carry 122.38
            rows.append(finish(base(
                id=f"{oid}-great-lakes-notice", operator_id=oid, name=name, permit=sorted(gl & set(ps))[0],
                channel_kind="operator_page", urls=[], method=None, legal_basis=Q_522, basis_kind="law",
                monitored=False, unmonitored_reason="other", publishes="unknown", sources=["in-law-327-iac-5-2-2",
                                                                                          "in-epa-gl-cso-indiana"],
                note=(f"{name}'s outfalls discharge in the Great Lakes basin (IDEM's layer), so its plan must give a "
                      "public notice within four hours (40 CFR 122.38); the channel its plan names was not verified in "
                      "the research."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    ids = {d["id"] for d in dis}
    missing = [r["operator_id"] for r in OWN if r["operator_id"] not in ids]
    if missing:
        raise SystemExit(f"operator rows missing from data/dischargers.json: {missing}")
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "IN")
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
    rep = run("--dry-run" in sys.argv[1:])
    print(json.dumps(rep, indent=1))
