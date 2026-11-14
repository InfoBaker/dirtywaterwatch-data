"""Wisconsin rows of the notice register (data/notice-channels/wi.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_wi_register_rows.py [--dry-run]

The law (research/wi/report.md section 2.1 in the site repository; research/wi/profile.json; the expansion research of
2026-11-09):
  - s. NR 210.21(5), Wis. Adm. Code: every sanitary sewer overflow and treatment facility overflow is publicly noticed
    "promptly", by the communications the operator's emergency response plan names (NR 210.23(4)(f)). The DNR's form
    3400-184 instructions: "At a minimum, if an overflow is to a surface water, a daily newspaper of general circulation
    shall be notified." No web posting and no hour deadline. The official code page did not answer the build's client
    (docs.legis.wisconsin.gov, 2026-11-03 and 2026-11-14), so the wording rests on the DNR's instructions.
  - The overflow is reported to the DNR within 24 hours and on form 3400-184 within five business days through
    Switchboard (permittees only); the DNR publishes none of it.
  - 40 CFR 122.38: the two Great Lakes Basin combined sewer permittees (MMSD WI0036820, Superior WI0025593) give
    electronic public notice within four hours.
  - Tribal permits (EPA Region 5): the federal 24-hour and five-day reports to EPA; Wisconsin's rule does not apply.
Rows
  - Per operator (every Wisconsin row of data/dischargers.json): <id>-nr210-notice, the operator's NR 210.21(5) notice
    (law; the DNR's minimum a daily newspaper: printed only), or <id>-epa-report for a tribal permit; an operator whose
    own web notice the research found gets <id>-web-notice with that notice's address.
  - MMSD: its Storm Update posts (the wi-mmsd-storm-updates feed), the rain and facility page with the year-to-date
    counter (watched, never an event), the CSO impacted-waters page, the 2018 CSO public notification plan (image-only
    notice sections), the four-hour notice (no web channel found), the Water Drop Alert texts (pre-storm requests).
  - Superior: its CSO notification page and the annual notice.
  - Statewide: the DNR's Switchboard reports (login), its SSO reporting page, the SERTS open-spill list and the BRRTS
    search, Wisconsin Beach Health (report pages and map layer), the DHS algae page, the City of Milwaukee Health
    Department's beach report, EPA's overflow tables (no Wisconsin report), Brookfield's press releases, Swim Guide.
  Several Wisconsin government hosts (apps.dnr.wi.gov, dnrmaps.wi.gov, docs.legis.wisconsin.gov) and the City of
  Superior's site did not answer the build's client on 2026-11-14 (connection timed out; a second network was refused):
  their rows are monitored, so the refresh records whether they answer, and they make no records.
A rerun replaces every wi- row it makes. Validated before writing.
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
from add_wi_operators import EPA_TRIBAL_PERMITS  # noqa: E402
from ingest import notification_pages as NP  # noqa: E402

REGISTER = ROOT / "data" / "notice-channels"
DIS = ROOT / "data" / "dischargers.json"
CHECKED = "2026-11-14"
FEED = "wi-mmsd-storm-updates"
LAW = "wi-law-nr-210-21"
INSTR = "https://dnr.wisconsin.gov/sites/default/files/topic/Wastewater/WW_SSOFormInstructions.pdf"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
UNREACHED = (" On 2026-11-14 the host did not answer the build's client (connection timed out) nor a second network "
             "(connection refused); the row is watched so the refresh records when it answers.")
Q_NR210 = ('s. NR 210.21(5), Wis. Adm. Code, as the DNR\'s form 3400-184 instructions give it: "All overflows (SSOs & '
           'TFOs) are required to be public noticed according to s. NR 210.21(5), Wis. Adm. Code. Notification shall '
           'occur according to a facility\'s emergency response plan in their CMOM and occur promptly after any overflow '
           'event. ... At a minimum, if an overflow is to a surface water, a daily newspaper of general circulation '
           'shall be notified."')
Q_REPORT = ("s. NR 210.21, Wis. Adm. Code, and the WPDES permit's standard conditions: the overflow reported to the DNR "
            "within 24 hours and on form 3400-184 within five business days")
Q_122_38 = ('40 CFR 122.38(a): "As soon as possible, but no later than four (4) hours after becoming aware by '
            'monitoring, modeling or other means that a CSO discharge has occurred, the Great Lakes Basin CSO permittee '
            'shall provide public notification of CSO discharges"')
Q_TRIBAL = ("NPDES permit {permit} (EPA Region 5, tribal land): the 24-hour and five-day noncompliance reports of 40 CFR "
            "122.41(l)(6), to EPA")
MMSD, SUPERIOR = "wi-mmsd", "wi-superior-sewage-disposal-system"

AGENCY = [
    {"id": "wi-mmsd-storm-updates", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "feed", "urls": ["https://www.mmsd.com/about-us/news"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "note": ("MMSD's Storm Update posts: what MMSD reported to the DNR after each overflow of its regional system, with "
              "the dates, the volume and the letter; 18 posts from 2018-06-22 to 2026-09-08 among 282 news posts "
              "(2026-11-14), posted four to ten days after the overflow began (the September 3, 2026 overflow on "
              "September 8). Read by the wi-mmsd-storm-updates feed. (research/wi/report.md §2.3)"),
     "sources": [FEED]},
    {"id": "wi-mmsd-rain-facility-page", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/about-us/milwaukee-rain-facility-information"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("MMSD's rain and facility page: rain gauges, the deep tunnels' storage, the plants' flows and the "
              "year-to-date \"Gallons Overflowed\" counter (2,810,937,528 gallons in 2026 on 2026-11-14). MMSD says its "
              "figures can be corrected, so a rise is never read as an overflow; watched for availability only."),
     "sources": ["wi-mmsd-rain-facility-page"]},
    {"id": "wi-mmsd-cso-impacted-waters", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/about-us/milwaukee-rain-facility-information/cso-impacted-waters"],
     "method": "html", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "the City Beaches Water Report and MMSD's CSO public notification plan",
     "records": False, "availability_only": True, "every_hours": 24,
     "note": ("The waters a combined sewer overflow may affect, as MMSD lists them: the Milwaukee River (Kiwanis "
              "Landing and Riverfront launches, Riverside parks, marinas), the Menomonee River (Emmber Lane and Valley "
              "Passage launches), Lake Michigan (McKinley and South Shore launches) and the nearshore harbor; it links "
              "the City of Milwaukee Health Department's beach report and the notification plan. A standing list, not "
              "an event notice."),
     "sources": ["wi-mmsd-cso-impacted-waters"]},
    {"id": "wi-mmsd-cso-notification-plan", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/application/files/1116/4553/8883/MMSD_CSO_Public_Notification_Plan_web.pdf"],
     "method": "pdf", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "image_only", "publishes": "documents", "records": False,
     "note": ("MMSD's CSO Public Notification Plan of July 16, 2018, written for 40 CFR 122.38: its text layer covers "
              "the introduction (115 combined sewer outfalls on seven waterways); the sections on how the public is "
              "told are scanned images and were not read. (research/wi/report.md §2.1)"),
     "sources": ["wi-mmsd-cso-notification-plan"]},
    {"id": "wi-mmsd-four-hour-notice", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": Q_122_38,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False,
     "note": ("No web channel found for the four-hour notice 40 CFR 122.38 requires: MMSD's web posts come with the "
              "five-day letter. It may give notice by news media or social accounts (not verified). (research/wi/"
              "report.md §4)"),
     "sources": ["wi-law-40cfr122-38"]},
    {"id": "wi-mmsd-water-drop-alert", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "email_list",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "likelihood", "records": False,
     "note": ("Water Drop Alert text messages (sign-up at https://mmsd.com/what-you-can-do/water-drop-alert): a request "
              "to use less water when heavy rain threatens, sent to subscribers; not an overflow notice and never read "
              "as one."),
     "sources": ["wi-mmsd-water-drop-alert"]},
    {"id": "wi-superior-cso-page", "operator_id": SUPERIOR, "name": "City of Superior", "permit": "WI0025593",
     "channel_kind": "operator_page", "urls": ["https://www.superiorwi.gov/902/Combined-Sewer-Overflows"],
     "method": "html", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24,
     "note": ("Superior's combined sewer overflow page: a 2026 table with columns for the location, receiving water, "
              "affected access areas, start, end and estimated volume, read empty on 2026-11-09, with the annual "
              "notices linked (2025: no combined sewer overflow; outfalls CSO 2 to Superior Bay, CSO 5 to the Nemadji "
              "River and CSO 6 to the St. Louis River). Not ingested: no filled row has been seen to test a reader on."
              + UNREACHED),
     "sources": ["wi-superior-cso"]},
    {"id": "wi-superior-annual-notice", "operator_id": SUPERIOR, "name": "City of Superior", "permit": "WI0025593",
     "channel_kind": "operator_page", "urls": ["https://www.superiorwi.gov/DocumentCenter/View/16616"],
     "method": "pdf", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 168,
     "note": ("Superior's 2025 annual CSO notice (revised July 2026), which its page links as the public notification "
              "plan: zero combined sewer overflows in 2025; it also covers the Parkland satellite system." + UNREACHED),
     "sources": ["wi-superior-cso"]},
    {"id": "wi-dnr-switchboard-sso-reports", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (Switchboard SSO and TFO reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "login", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("Every sanitary sewer and treatment facility overflow, public or private system, is reported to the DNR "
              "within 24 hours and on form 3400-184 (date, location, duration, volume, receiving water, coordinates "
              "and how the public was told) within five business days, through Switchboard, which only permittees "
              "can open. The DNR publishes none of it and sends none to EPA's tables. (research/wi/report.md §1)"),
     "sources": ["wi-wdnr-sso-report-page", "wi-wdnr-sso-form-instructions"]},
    {"id": "wi-dnr-sso-report-page", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (sanitary sewer overflow reporting page)",
     "channel_kind": "state_alert_page", "urls": ["https://dnr.wisconsin.gov/topic/Wastewater/SSOreport.html"],
     "method": "html", "legal_basis": Q_REPORT, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Notification page",
     "note": ("The DNR's instructions for filing an overflow report through Switchboard; no public list of reports. "
              "Watched for a public extract."),
     "sources": ["wi-wdnr-sso-report-page"]},
    {"id": "wi-dnr-serts-open-spills", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (SERTS open spill incidents)",
     "channel_kind": "state_alert_page", "urls": ["https://apps.dnr.wi.gov/rrbotw/sp-openspillincidents"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True,
     "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The DNR's list of open spill incidents of every substance, with CSV and Excel buttons: 271 open on "
              "2026-11-09, among them a sewage spill at Ashland (incident date, county, municipality, substance, "
              "cause, the coordinator's name). Closed incidents move to the BRRTS search, so a row that leaves the list "
              "has not ended. Not ingested: its export, paging and the share of sewage overflows it holds were not "
              "tested." + UNREACHED),
     "sources": ["wi-wdnr-serts-open-spills"]},
    {"id": "wi-dnr-brrts-search", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (BRRTS on the Web search)",
     "channel_kind": "state_alert_page", "urls": ["https://apps.dnr.wi.gov/rrbotw/botw-search"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "availability_only": True, "every_hours": 168,
     "noun": "Voluntary page",
     "note": ("The search form for closed spill and cleanup cases, where SERTS incidents go when they close; no "
              "closed sewage query was tested." + UNREACHED),
     "sources": ["wi-wdnr-brrts-closed-spills"]},
    {"id": "wi-dnr-beach-health", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (Wisconsin Beach Health)", "channel_kind": "state_alert_page",
     "urls": ["https://apps.dnr.wi.gov/beachhealth/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "status",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The DNR's beach report: advisories and closures with their reason (E. coli, algae) and dates, Great "
              "Lakes beaches under the BEACH Act and the inland beaches local health departments choose to report, in "
              "season (Memorial Day to Labor Day). Not ingested: its export and the map layer's keys were not read."
              + UNREACHED),
     "sources": ["wi-wdnr-beach-health"]},
    {"id": "wi-dnr-beach-layer", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (beach monitoring map layer)", "channel_kind": "feed",
     "urls": ["https://dnrmaps.wi.gov/arcgis2/rest/services/OGW_Beach_Monitoring/BEACH_MONITORING_LOCATIONS/MapServer/1"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Data feed",
     "note": ("The ArcGIS layer behind the beach map: 441 beaches with STATUS, BEACH_ACTION, ISSUED, SAMPLEDATE and "
              "ECOLIVALUE (2026-11-03), \"No Data Available\" off season." + UNREACHED),
     "sources": ["wi-wdnr-beach-health"]},
    {"id": "wi-dhs-algae", "agency": "Wisconsin Department of Health Services",
     "name": "Wisconsin Department of Health Services (harmful algal blooms)", "channel_kind": "state_alert_page",
     "urls": ["https://www.dhs.wisconsin.gov/algae/index.htm"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "none",
     "records": False, "availability_only": True, "every_hours": 168, "noun": "Voluntary page",
     "note": ("The DHS algae program's pages: health information and illness reporting; no statewide bloom advisory "
              "list. Blooms at beaches appear in the DNR's beach report."),
     "sources": ["wi-hab-program"]},
    {"id": "wi-milwaukee-health-beaches", "agency": "City of Milwaukee Health Department",
     "name": "City of Milwaukee Health Department (beach water report)", "channel_kind": "local_health_page",
     "urls": ["https://city.milwaukee.gov/Health/Services-and-Programs/disease-Control-and-Environment/recreational-Water/Beaches"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The Health Department samples Bradford, McKinley and South Shore beaches, near the combined sewer area, "
              "daily from Memorial Day to Labor Day and posts a water report (MMSD's impacted-waters page links it). "
              "Not read in this build."),
     "sources": ["wi-mmsd-cso-impacted-waters"]},
    {"id": "wi-newspaper-notices", "agency": "Wisconsin sewer system owners",
     "name": "Wisconsin sewer system owners (newspaper notices under NR 210.21(5))", "channel_kind": "news_page",
     "urls": [], "method": None, "legal_basis": Q_NR210, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "note": ("The DNR's minimum for an overflow that reaches surface water is a notice to a daily newspaper: printed "
              "only unless the paper or the operator also posts it. Some operators post notices on their own sites "
              "(Brookfield, Hortonville, Fox Crossing, Menomonie, Stoughton, Oconomowoc, Fennimore, Greenville were "
              "found by search); there is no list of them."),
     "sources": [LAW, "wi-municipal-sso-notices"]},
    {"id": "wi-brookfield-sso-notices", "operator_id": "wi-city-of-brookfield", "name": "City of Brookfield",
     "permit": None, "channel_kind": "operator_page",
     "urls": ["https://www.ci.brookfield.wi.us/DocumentCenter/View/24645/April-15-and-16-2026-SSO-Press-Release?bidId="],
     "method": "pdf", "legal_basis": Q_NR210, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False,
     "note": ("Brookfield's press release on its April 15 and 16, 2026 overflows (three locations, to the Fox River and, "
              "by Underwood Creek, the Menomonee River, with the quantities) in the city's document center; no list "
              "page of such releases was found (channel not researched beyond that release)."),
     "sources": ["wi-brookfield-sso-notices"]},
    {"id": "wi-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168, "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables hold no Wisconsin report: none in the current extract of "
              "2026-11-12 (5,751 events) nor in the all-versions extract (6,710 events); the collection-system table "
              "lists 14 Wisconsin permits, all EPA's on tribal land (one payload of 2025-03-04). The DNR keeps its "
              "reports in its own system. Watched for Wisconsin rows."),
     "sources": ["wi-epa-sobe"]},
    {"id": "wi-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish (Milwaukee Riverkeeper's listings)",
     "channel_kind": "swim_guide", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "results", "records": False,
     "note": ("Milwaukee Riverkeeper posts its own and the state's beach and river results to Swim Guide; an app and "
              "site with its own terms, not read."),
     "sources": ["wi-milwaukee-riverkeeper-swim-guide"]},
]


def base(**kw) -> dict:
    r = {"state": "WI", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict], research: dict[str, dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "WI":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        permit = ps[0] if ps else None
        if set(ps) & EPA_TRIBAL_PERMITS:
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
                urls=[], method=None, legal_basis=Q_TRIBAL.format(permit=permit), basis_kind="permit",
                monitored=False, unmonitored_reason="other", publishes="none", records=False, noun="EPA report",
                sources=["wi-epa-sobe"],
                note=(f"No web channel found: {name}'s permit is EPA's on tribal land, so its overflow reports go to EPA "
                      "Region 5, which publishes those filed electronically in its overflow tables (none for "
                      "Wisconsin in the extract of 2026-11-12). Wisconsin's rule does not apply on tribal land."))))
            continue
        private = (" The rule binds the system's owner, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility") else "")
        rows.append(finish(base(
            id=f"{oid}-nr210-notice", operator_id=oid, name=name, permit=None, channel_kind="news_page", urls=[],
            method=None, legal_basis=Q_NR210, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="unknown", records=False, noun="Notification page", sources=[LAW],
            note=(f"{name} gives notice of an overflow by its emergency response plan; the DNR's minimum, a notice to "
                  "a daily newspaper, is printed only, and its report to the DNR is not published "
                  f"(wi-dnr-switchboard-sso-reports).{private} Its own web channel was not searched individually."))))
        r = research.get(oid)
        url = (r or {}).get("notification_channel") or ""
        if url.startswith("http"):
            rows.append(finish(base(
                id=f"{oid}-web-notice", operator_id=oid, name=name, permit=None, channel_kind="operator_page",
                urls=[url], method="pdf" if url.lower().endswith(".pdf") else "html", legal_basis=Q_NR210,
                basis_kind="law", monitored=False, unmonitored_reason="other", publishes="notices", records=False,
                sources=["wi-municipal-sso-notices"],
                note=(f"{name} posted an overflow notice on its own site citing NR 210.21(5) (found by search, "
                      "2026-11-03); the address is that one notice, and no list page of its notices was found (the "
                      "channel not researched beyond it)."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    research = {r["id"]: r for r in json.loads((ROOT / "research" / "wi" / "dischargers.json").read_text())}
    rows = operator_rows(dis, research)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "WI")
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
