"""Wisconsin rows of the notice register (data/notice-channels/wi.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_wi_register_rows.py [--dry-run]

The law (research/wi/report.md section 2.1 in the site repository; research/wi/profile.json; the expansion research of
2026-11-09):
  - s. NR 210.21(5), Wis. Adm. Code: every sanitary sewer overflow and treatment facility overflow is publicly noticed
    "promptly", by the communications the operator's emergency response plan names (NR 210.23(4)(f)). The DNR's form
    3400-184 instructions: "At a minimum, if an overflow is to a surface water, a daily newspaper of general circulation
    shall be notified." No web posting and no hour deadline. The wording rests on the DNR's instructions; the code
    page itself (docs.legis.wisconsin.gov) answered GitHub's runner on 2026-11-16 (run 43789054085).
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
  - MMSD's overflows page (each year's overflows with their volumes and the post-storm reports): watched, not read.
  - Statewide: the DNR's Switchboard reports (login), its SSO reporting page, the SERTS open-spill list and the BRRTS
    search, Wisconsin Beach Health (the map layer, read by the wi-dnr-beach-health feed, and the report page), the DHS
    algae page, the DNR's blue-green algae page, the City of Milwaukee Health Department's beach report, Public Health
    Madison and Dane County's beach page, Kenosha County's and Sheboygan County's beach pages, EPA's overflow tables (no
    Wisconsin report), Brookfield's press release and the City of Madison's and the Village of Allouez's overflow
    notices (independent research, read by GitHub's runner 2026-11-16), Swim Guide.
  The Wisconsin state hosts (apps.dnr.wi.gov, dnrmaps.wi.gov, docs.legis.wisconsin.gov) and the City of Superior's site
  answer GitHub's runner, where the pipeline runs (runs 43788047052, 43788371768, 43788396939 and 43789054085,
  2026-11-16); the developer's machine could not open a connection to them, which is not a barrier of the source. The
  City of Milwaukee's beach pages, Kenosha County's and Sheboygan County's answered the runner 403 (a browser
  challenge or bot check): that is the source's barrier. Fox Crossing's, Greenville's and Oconomowoc's notice addresses
  answered the runner 404 on 2026-11-16 (GONE_404).
  Every monitored Wisconsin row is metadata_only (notification_pages): no response body is saved and the snapshot keeps
  only the text's hash, so a page carrying a name, telephone or address is never stored.
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
RUNNER_READ = "2026-11-16"
FEED = "wi-mmsd-storm-updates"
LAW = "wi-law-nr-210-21"
INSTR = "https://dnr.wisconsin.gov/sites/default/files/topic/Wastewater/WW_SSOFormInstructions.pdf"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
# rows that would carry people's names (SERTS's coordinator, a health department's contact) are not fetched until a reader
# keeps only safe fields: the register's page monitor saves the page it reads (Astra review 2026-11-14 P1-6)
NOT_WATCHED_TEXT = (" Watched for availability only: its pages can carry staff names, so no page text or body is kept "
                    "(metadata_only) and no record is made until a reader that keeps only safe fields exists (Astra "
                    "re-review 2026-11-15 P1-7, P2-11).")
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
# operators whose one web notice found by search answered 404 to GitHub's runner on 2026-11-16 (audit of that day)
GONE_404 = {"wi-fox-crossing-sso", "wi-greenville-sso", "wi-oconomowoc-sso"}

AGENCY = [
    {"id": "wi-mmsd-storm-updates", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "feed", "urls": ["https://www.mmsd.com/about-us/news"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed", "checked": RUNNER_READ,
     "note": ("MMSD's Storm Update posts: what MMSD reported to the DNR after each overflow of its regional system, with "
              "the dates, the volume and the letter, and its spill and release notices; 21 posts from 2018-06-22 to 2026-09-08 among 281 news posts "
              "(2026-11-14 and 2026-11-16), posted one to six days after the overflow began where the post dates it (11 posts; the other 10 give "
              "only the storm's dates; the September 3, 2026 overflow on September 8). Read by the wi-mmsd-storm-updates feed. (research/wi/report.md §2.3)"),
     "sources": [FEED]},
    {"id": "wi-mmsd-rain-facility-page", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/about-us/milwaukee-rain-facility-information"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Voluntary page", "checked": RUNNER_READ,
     "note": ("MMSD's rain and facility page: rain gauges, the deep tunnels' storage, the plants' flows and the "
              "year-to-date \"Gallons Overflowed\" counter (2,810,937,528 gallons in 2026 on 2026-11-14). MMSD says its "
              "figures can be corrected, so a rise is never read as an overflow; watched for availability only."),
     "sources": ["wi-mmsd-rain-facility-page"]},
    {"id": "wi-mmsd-cso-impacted-waters", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/about-us/milwaukee-rain-facility-information/cso-impacted-waters"],
     "method": "html", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "the City Beaches Water Report and MMSD's CSO public notification plan",
     "records": False, "availability_only": True, "every_hours": 24, "checked": RUNNER_READ,
     "note": ("The waters a combined sewer overflow may affect, as MMSD lists them: the Milwaukee River (Kiwanis "
              "Landing and Riverfront launches, Riverside parks, marinas), the Menomonee River (Emmber Lane and Valley "
              "Passage launches), Lake Michigan (McKinley and South Shore launches) and the nearshore harbor; it links "
              "the City of Milwaukee Health Department's beach report and the notification plan. A standing list, not "
              "an event notice."),
     "sources": ["wi-mmsd-cso-impacted-waters"]},
    {"id": "wi-mmsd-overflows-page", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/what-we-do/wastewater-treatment/overflows"], "method": "html",
     "legal_basis": Q_122_38, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Operator page", "checked": RUNNER_READ,
     "note": ("MMSD's overflows page: each 2026 overflow by its dates with the volumes by kind and a link to the "
              "post-storm report to the DNR (April 14 to 19: combined 2,703,000,000 gallons, separate 11,590,728, "
              "treatment facility 15,300; August 1: combined 96,000,000; September 3: combined 331,500, as GitHub's "
              "runner read it on 2026-11-16), the 2025 annual CSO notification report and the year's totals. The same "
              "overflows reach us through the Storm Update posts (wi-mmsd-storm-updates); the page and its reports "
              "are not read yet."),
     "sources": [FEED]},
    {"id": "wi-mmsd-cso-notification-plan", "operator_id": MMSD, "name": "Milwaukee Metropolitan Sewerage District",
     "permit": "WI0036820", "channel_kind": "operator_page",
     "urls": ["https://www.mmsd.com/application/files/1116/4553/8883/MMSD_CSO_Public_Notification_Plan_web.pdf"],
     "method": "pdf", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "image_only", "publishes": "documents", "records": False, "checked": RUNNER_READ,
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
              "affected access areas, start, end and estimated volume, with two blank rows and no filled row when "
              "GitHub's runner read it on 2026-11-16 (\"Last Updated 07/14/2022\"), and the annual notices linked "
              "(2025: no combined sewer overflow; outfalls CSO 2 to Superior Bay, CSO 5 to the Nemadji River and CSO 6 "
              "to the St. Louis River). The page says the City also announces overflows by press release to the "
              "Superior Telegram. Not ingested yet: no filled row has been seen to test a reader on, and blank rows "
              "are not a finding of no overflow."),
     "sources": ["wi-superior-cso"]},
    {"id": "wi-superior-annual-notice", "operator_id": SUPERIOR, "name": "City of Superior", "permit": "WI0025593",
     "channel_kind": "operator_page", "urls": ["https://www.superiorwi.gov/DocumentCenter/View/16616"],
     "method": "pdf", "legal_basis": Q_122_38, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 168,
     "note": ("Superior's 2025 annual CSO notice (revised July 2026), which its page links as the public notification "
              "plan: zero combined sewer overflows in 2025; it also covers the Parkland satellite system. It answered "
              "GitHub's runner on 2026-11-16 (a PDF)."),
     "sources": ["wi-superior-cso"]},
    {"id": "wi-dnr-switchboard-sso-reports", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (Switchboard SSO and TFO reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "login", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("Every sanitary sewer and treatment facility overflow, public or private system, is reported to the DNR "
              "within 24 hours and on form 3400-184 (date, location, duration, volume, receiving water, coordinates "
              "and how the public was told) within five business days, through Switchboard, which only permittees "
              "can open. The DNR publishes none of it, and EPA's tables held no Wisconsin report in their files of 2026-11-13. (research/wi/report.md §1)"),
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
     "unmonitored_reason": None, "publishes": "notices", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The DNR's list of open spill incidents of every substance, with CSV and Excel buttons: 271 open on "
              "2026-11-09, among them a sewage spill at Ashland (incident date, county, municipality, substance, "
              "cause, the coordinator's name). Closed incidents move to the BRRTS search, so a row that leaves the list "
              "has not ended. It answered GitHub's runner on 2026-11-16. Not ingested yet: its export, paging and the "
              "share of sewage overflows it holds were not tested, and the coordinator's name must be dropped before "
              "anything is saved." + NOT_WATCHED_TEXT),
     "sources": ["wi-wdnr-serts-open-spills"]},
    {"id": "wi-dnr-brrts-search", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (BRRTS on the Web search)",
     "channel_kind": "state_alert_page", "urls": ["https://apps.dnr.wi.gov/rrbotw/botw-search"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "availability_only": True, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The search form for closed spill and cleanup cases, where SERTS incidents go when they close; no "
              "closed sewage query was tested. It answered GitHub's runner on 2026-11-16." + NOT_WATCHED_TEXT),
     "sources": ["wi-wdnr-brrts-closed-spills"]},
    {"id": "wi-dnr-beach-health", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (Wisconsin Beach Health)", "channel_kind": "state_alert_page",
     "urls": ["https://apps.dnr.wi.gov/beachhealth/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "wi-dnr-beach-health", "publishes": "status", "noun": "Voluntary page", "checked": RUNNER_READ,
     "note": ("The DNR's beach report (Beach Name, Status, Reason, Date of Advisory, Nearest Town): advisories and "
              "closures with their reason (E. coli, algae) and dates, Great Lakes beaches under the BEACH Act and the "
              "inland beaches local health departments choose to report, in season (Memorial Day to Labor Day). Read "
              "by GitHub's runner on 2026-11-16: 453 beaches, one algae advisory (Gile Flowage Beach, September 17, "
              "2026) and one algae closure (Lake Kegonsa State Park Beach, September 11), the rest closed for the "
              "season. The same statuses, reasons and dates are on the beach map layer; the page adds the nearest "
              "town and 12 beaches the layer gives no point for (by name). The wi-dnr-beach-health feed reads the layer for "
              "points and status and this table for those 12 beaches: an advisory there is listed with its beach and "
              "nearest town, with no place on the map."),
     "sources": ["wi-wdnr-beach-health"]},
    {"id": "wi-dnr-beach-layer", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (beach monitoring map layer)", "channel_kind": "feed",
     "urls": ["https://dnrmaps.wi.gov/arcgis2/rest/services/OGW_Beach_Monitoring/BEACH_MONITORING_LOCATIONS/MapServer/1"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "wi-dnr-beach-health", "publishes": "status",
     "noun": "Data feed", "checked": RUNNER_READ,
     "note": ("The ArcGIS layer behind the beach map: 441 beaches when GitHub's runner read it on 2026-11-16, each "
              "with the Department's action (Advisory, Closed, End), reason, Date of Advisory and point; one algae "
              "advisory and one algae closure in effect, the rest closed for the season. Read by the "
              "wi-dnr-beach-health feed: each advisory or closure is shown at its beach while the Department lists it, "
              "an algae reason as a bloom."),
     "sources": ["wi-wdnr-beach-health"]},
    {"id": "wi-dhs-algae", "agency": "Wisconsin Department of Health Services",
     "name": "Wisconsin Department of Health Services (harmful algal blooms)", "channel_kind": "state_alert_page",
     "urls": ["https://www.dhs.wisconsin.gov/algae/index.htm"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "none",
     "records": False, "availability_only": True, "every_hours": 168, "noun": "Voluntary page",
     "note": ("The DHS algae program's pages: health information and illness reporting; no statewide bloom advisory "
              "list. Blooms at beaches appear in the DNR's beach report."),
     "sources": ["wi-hab-program"]},
    {"id": "wi-madison-dane-health-beaches", "agency": "Public Health Madison and Dane County",
     "name": "Public Health Madison and Dane County (beach conditions)", "channel_kind": "local_health_page",
     "urls": ["https://publichealthmdc.com/home-environment/beaches"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "status", "records": False,
     "availability_only": True, "every_hours": 24, "noun": "Voluntary page", "checked": RUNNER_READ,
     "note": ("Public Health Madison and Dane County's beach page: the status of 27 Dane County beach and access sites, "
              "with the reason for a closure (bacteria, blue-green algae), all closed for the season when independent "
              "research read it in November 2026. It answered GitHub's runner on 2026-11-16. Watched for availability; "
              "not read for records yet. The Dane County beaches the Department lists are shown through the "
              "wi-dnr-beach-health feed."),
     "sources": ["wi-madison-dane-health-beaches"]},
    {"id": "wi-kenosha-county-beach-conditions", "agency": "Kenosha County",
     "name": "Kenosha County (beach conditions)", "channel_kind": "local_health_page",
     "urls": ["https://www.kenoshacountywi.gov/348/Beach-Conditions"], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "status", "records": False, "noun": "Voluntary page",
     "checked": RUNNER_READ,
     "note": ("Kenosha County's beach conditions table (beach, result, condition, sampling date). It answered GitHub's "
              "runner, where the pipeline runs, with HTTP 403 on 2026-11-16 (a bot check), which we do not get around: "
              "not read. Kenosha's beaches are in the DNR's beach system when the Department lists them."),
     "sources": ["wi-kenosha-county-beach-conditions"]},
    {"id": "wi-sheboygan-county-water-quality", "agency": "Sheboygan County",
     "name": "Sheboygan County (public health water quality page)", "channel_kind": "local_health_page",
     "urls": ["https://www.sheboygancounty.com/departments/departments-f-q/health-and-human-services/public-health/environmental-health/water-quality-drinking-water"], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "unknown", "records": False, "noun": "Voluntary page",
     "checked": RUNNER_READ,
     "note": ("Sheboygan County's water quality page. It answered GitHub's runner, where the pipeline runs, with HTTP "
              "403 on 2026-11-16 (a bot check), which we do not get around: not read. Sheboygan's beaches are in the "
              "DNR's beach system when the Department lists them."),
     "sources": ["wi-sheboygan-county-water-quality"]},
    {"id": "wi-dnr-bluegreenalgae", "agency": "Wisconsin Department of Natural Resources",
     "name": "Wisconsin Department of Natural Resources (blue-green algae)", "channel_kind": "state_alert_page",
     "urls": ["https://dnr.wisconsin.gov/topic/lakes/bluegreenalgae"], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True,
     "unmonitored_reason": None, "publishes": "none", "records": False, "availability_only": True,
     "every_hours": 168, "noun": "Voluntary page", "checked": RUNNER_READ,
     "note": ("The DNR's blue-green algae page: guidance, a form to report a bloom and referrals to beach and local "
              "health pages; it says there is no routine statewide algae or toxin monitoring, and it holds no list of "
              "current blooms. It answered GitHub's runner on 2026-11-16. Blooms at beaches appear in the DNR's beach "
              "report."),
     "sources": ["wi-hab-program"]},
    {"id": "wi-milwaukee-health-beaches", "agency": "City of Milwaukee Health Department",
     "name": "City of Milwaukee Health Department (beach water report)", "channel_kind": "local_health_page",
     "urls": ["https://city.milwaukee.gov/Health/Services-and-Programs/disease-Control-and-Environment/recreational-Water/Beaches",
              "https://city.milwaukee.gov/health/information/environmental-health/beaches"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall",
     "checked": RUNNER_READ,
     "publishes": "status", "records": False, "noun": "Voluntary page",
     "note": ("The Health Department samples Bradford, McKinley and South Shore beaches, near the combined sewer area, "
              "in season (Monday, Wednesday and Friday, as independent research read its page on 2026-11-15) and posts a water report (MMSD's impacted-waters page links it). "
              "On 2026-11-16 both of its addresses answered GitHub's runner, where the pipeline runs, with HTTP 403 (a "
              "browser challenge, as on 2026-11-15), which we do not get around: not read, and its advisories are not "
              "shown. The same beaches are in the DNR's beach system when the Department lists them."),
     "sources": ["wi-mmsd-cso-impacted-waters"]},
    {"id": "wi-newspaper-notices", "agency": "Wisconsin sewer system owners",
     "name": "Wisconsin sewer system owners (newspaper notices under NR 210.21(5))", "channel_kind": "news_page",
     "urls": [], "method": None, "legal_basis": Q_NR210, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "note": ("The DNR's minimum for an overflow that reaches surface water is a notice to a daily newspaper; whether "
              "a paper puts it on the web varies by town and paper (town pages not surveyed). Some operators post notices on their own sites "
              "(Brookfield, Hortonville, Fox Crossing, Menomonie, Stoughton, Oconomowoc, Fennimore, Greenville were "
              "found by search, Madison and Allouez by independent research in November 2026); there is no list of "
              "them."),
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
    {"id": "wi-madison-sso-web-notice", "agency": "City of Madison", "name": "City of Madison",
     "channel_kind": "operator_page", "urls": ["https://www.cityofmadison.com/news/2026-09-11/roots-cause-sanitary-sewer-overflow-city-teamwork-leads-to-fast-cleanup"], "method": "html", "legal_basis": Q_NR210,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "notices",
     "records": False, "checked": RUNNER_READ,
     "note": ("The City of Madison's news item of September 11, 2026 on a sanitary sewer overflow of about 500 gallons "
              "on September 10 (a root blockage; it entered a storm sewer). It answered GitHub's runner on 2026-11-16. "
              "The address is that one notice; no list page of the City's overflow notices was found (channel not "
              "researched beyond it)."),
     "sources": ["wi-municipal-sso-notices"]},
    {"id": "wi-allouez-sso-web-notice", "agency": "Village of Allouez", "name": "Village of Allouez",
     "channel_kind": "operator_page", "urls": ["https://www.villageofallouezwi.gov/announcements/notice-of-sanitary-sewer-overflow/"], "method": "html", "legal_basis": Q_NR210,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "notices",
     "records": False, "checked": RUNNER_READ,
     "note": ("The Village of Allouez's notice of April 21, 2026 on a sanitary sewer overflow of April 14 to 16 near the "
              "East River (no volume given). It answered GitHub's runner on 2026-11-16. The address is that one notice; "
              "no list page of the Village's overflow notices was found (channel not researched beyond it)."),
     "sources": ["wi-municipal-sso-notices"]},
    {"id": "wi-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168, "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables hold no Wisconsin report: none in the current extract of "
              "2026-11-13 (5,751 events) nor in the all-versions extract (6,714 events); the collection-system table "
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
                      "Wisconsin in the extract of 2026-11-13). Wisconsin's rule does not apply on tribal land."))))
            continue
        private = (" The rule binds the system's owner, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility") else "")
        rows.append(finish(base(
            id=f"{oid}-nr210-notice", operator_id=oid, name=name, permit=None, channel_kind="news_page", urls=[],
            method=None, legal_basis=Q_NR210, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="unknown", records=False, noun="Notification page", sources=[LAW],
            note=(f"{name} gives notice of an overflow by its emergency response plan; the DNR's minimum is a notice to "
                  "a daily newspaper, which does not by itself say whether the notice reaches the web, and its report "
                  f"to the DNR is not published (wi-dnr-switchboard-sso-reports).{private} Its own web channel was not "
                  "searched individually."))))
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
                      "channel not researched beyond it)."
                      + (" The address answered 404 to GitHub's runner on 2026-11-16." if oid in GONE_404 else "")),
                checked=RUNNER_READ if oid in GONE_404 else CHECKED)))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    research = {r["id"]: r for r in json.loads((ROOT / "research" / "wi" / "dischargers.json").read_text())}
    rows = operator_rows(dis, research)
    rows += [finish(base(**r)) for r in AGENCY]
    for r in rows:
        # every watched Wisconsin page is watched for availability and change only: no body and no text is kept, so a
        # page that names staff, a telephone or an address is never saved (Astra re-review 2026-11-15 P1-7)
        if r["monitored"]:
            r["metadata_only"] = True
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
