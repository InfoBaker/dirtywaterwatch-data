"""Oregon rows of the notice register (data/notice-channels/or.json), made from the law, the permits' general
conditions, the operators' and agencies' practice and data/dischargers.json, so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_or_register_rows.py [--dry-run]

The law (research/or/profile.json law; research/or/sources.json):
  - No Oregon statute requires the public to be told of a sewage release.
  - DEQ's permit general conditions (NPDES Schedule F; the WPCF domestic general conditions, DEQ's copy
    https://www.oregon.gov/deq/FilterPermitsDocs/WPCFGenCondDom.pdf): "If effluent limitations specified in this permit
    are exceeded or an overflow occurs that threatens public health, the permittee must take such steps as are
    necessary to alert the public, health agencies and other affected entities (e.g., public water systems) about the
    extent and nature of the discharge in accordance with the notification procedures specified in this permit or as
    specified in its Emergency Response and Public Notification Plan". No deadline, no channel. Schedule F D.5: an oral
    report within 24 hours (the Oregon Emergency Response System, 1-800-452-0311) and a written report within five days
    (DEQ's SSO report form). The NPDES text was quoted from search results (verified search_only in the research).
  - OAR 340-142-0040: the person in charge of a reportable spill reports it to OERS immediately.

Rows
  - Per operator (every Oregon row of data/dischargers.json): <id>-public-notice (permit basis: the general
    conditions' duty to alert the public by the operator's own plan). Portland's is its advisories feed (read by the
    or-bes-news-rss ingester: feed_ingested); Oak Lodge's is its news page (monitored, page health); Astoria's and
    Corvallis's pages publish no event notices (none_found: no web page); every other operator's own pages were not
    searched individually (not_verified).
  - Portland's two voluntary channels: the Big Pipe Tracker (monitored, page health only: a fill level is not a
    report) and the CSO advisories e-mail list (email_only).
  - Agency rows (AGENCY): the report to OERS and DEQ (law and permit; by telephone and on paper, never published),
    DEQ's OERS spill layer 2013-2025 (read as an archive), OHA's bloom advisories (read by the generic block), OHA's
    beach conditions page (monitored) and its e-mail notices, ODA's shellfish closures page (monitored), the Swim Guide.
A rerun replaces every or- row it makes. Validated before writing.
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
Q_GEN = ("DEQ permit general conditions (NPDES Schedule F; WPCF domestic general conditions): \"If effluent limitations "
         "specified in this permit are exceeded or an overflow occurs that threatens public health, the permittee must "
         "take such steps as are necessary to alert the public, health agencies and other affected entities (e.g., "
         "public water systems) about the extent and nature of the discharge in accordance with the notification "
         "procedures specified in this permit or as specified in its Emergency Response and Public Notification Plan\" "
         "(no deadline, no channel set)")
Q_REPORT = ("DEQ permit general conditions (NPDES Schedule F, D.5): an oral report within 24 hours to the Oregon "
            "Emergency Response System (1-800-452-0311) and a written report to DEQ within five days (DEQ's Sanitary "
            "Sewer Overflow Report Form); OAR 340-142-0040: a reportable spill is reported to OERS immediately")
PORTLAND_FEED = "or-bes-news-rss"
SOURCES = ["or-schedule-f-public-notice"]


def base(**kw) -> dict:
    r = {"state": "OR", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def public_notice(op: dict) -> dict:
    oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
    common = dict(id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit, legal_basis=Q_GEN,
                  basis_kind="permit")
    if oid == "or-portland-bes":
        return base(**common, channel_kind="feed", urls=["https://www.portland.gov/bes/news/rss"], method="rss",
                    monitored=False, unmonitored_reason="feed_ingested", feed_source_id=PORTLAND_FEED,
                    publishes="notices", noun="Data feed",
                    signup_url="https://public.govdelivery.com/accounts/ORPORTLAND_ENT/signup/39493",
                    authority="City of Portland Environmental Services",
                    note=("Portland Environmental Services publishes a CSO Advisory for each combined sewer overflow "
                          "(4 between 2025-11-28 and 2026-03-12) and a Sewage Advisory for each sewage release it "
                          "reports, as news articles with an RSS feed, read every refresh by the feed: the start, the "
                          "stretch ('the Willamette River downstream of the Ross Island Bridge'), the advice to avoid "
                          "contact during the overflow and for 48 hours after it stops, and the expiry. The City's "
                          "practice under its permit's public notification duty; the permit's own CSO clause was not "
                          "read. (research/or/sources.json or-bes-news-rss)"),
                    sources=SOURCES + [PORTLAND_FEED])
    if oid == "or-oak-lodge":
        return base(**common, channel_kind="news_page", urls=["https://oakwater.specialdistrict.org/news"],
                    method="html", monitored=True, unmonitored_reason=None, publishes="notices", records=False,
                    every_hours=24, noun="Notification page",
                    note=("Oak Lodge Water Services posts each overflow as a news article (2025-12-18: three lift "
                          "stations, impacts to Kellogg Creek and the Willamette River, the advice to avoid contact "
                          "during the overflow and for 48 hours afterwards; answered 200 on 2026-11-07). Page health "
                          "first: records off until a reviewer reads the first snapshots. (research/or/sources.json "
                          "or-oak-lodge-sso-posts)"),
                    sources=SOURCES + ["or-oak-lodge-sso-posts"])
    if oid in ("or-astoria", "or-corvallis"):
        page = {"or-astoria": ("https://www.astoria.gov/Wastewater_Combined_Sewage_Overflow_CSO_Stormwater.aspx",
                               "Astoria's wastewater and CSO page (38 open combined sewer outfalls to the Columbia River "
                               "and Youngs Bay) is background only; it posts no overflow notices", "or-astoria-cso-page"),
                "or-corvallis": ("https://www.corvallisoregon.gov/node/9031",
                                 "Corvallis's Public Notification & Spill Response Plan page describes signs and media "
                                 "contacts for larger discharges; it posts no overflow notices", "or-corvallis-spill-plan")}
        url, what, sid = page[oid]
        return base(**common, channel_kind="operator_page", urls=[], method=None, monitored=False,
                    unmonitored_reason="none_found", publishes="none", records=False,
                    note=(f"No web channel found for event notices: {what} ({url}, answered 200 on 2026-11-07). A "
                          "CSO permittee whose public notice is not on the web. (research/or/sources.json)"),
                    sources=SOURCES + [sid])
    return base(**common, channel_kind="operator_page", urls=[], method=None, monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, sources=SOURCES,
                note=(f"{name}: the general conditions require the permittee to alert the public by its own Emergency "
                      "Response and Public Notification Plan, with no channel set. Whether it posts its overflows on "
                      "the web was not searched individually."))


AGENCY = [
    {"id": "or-deq-oers-reports", "agency": "Oregon Department of Environmental Quality (Oregon Emergency Response System)",
     "name": "Oregon Emergency Response System and DEQ (spill and overflow reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("Reported by telephone only (OERS, 1-800-452-0311) within 24 hours, and on DEQ's paper form within five "
              "days. Neither is published: DEQ's layer of the spills it verified stops at 2025-03-27 "
              "(or-deq-oers-spills-archive) and no successor was found. Every Oregon permittee, public or private, "
              "reports this way."),
     "sources": ["or-oar-340-142", "or-deq-sso-report-form", "or-schedule-f-public-notice"]},
    {"id": "or-deq-oers-spills-archive", "agency": "Oregon Department of Environmental Quality",
     "name": "Oregon DEQ: spills reported to OERS and verified by DEQ, 2013 to March 2025", "channel_kind": "feed",
     "urls": ["https://services.arcgis.com/uUvqNMGPm7axC2dD/arcgis/rest/services/all_spills_Aug1_2013_Mar27_2025_pts/"
              "FeatureServer/1"], "method": "json", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "or-deq-oers-spills-2013-2025",
     "publishes": "notices", "noun": "Data feed",
     "note": ("A frozen ArcGIS layer of every spill reported to OERS and verified by DEQ, 2013-07-24 to 2025-03-27: "
              "2,371 sewage spills with DEQ's point, the report date and time and gallons. Read as an archive; the "
              "layer's edits are checked each refresh. No successor found. (research/or/sources.json)"),
     "sources": ["or-deq-oers-spills-2013-2025"]},
    {"id": "or-oha-hab-advisories", "agency": "Oregon Health Authority",
     "name": "Oregon Health Authority (cyanobacteria recreational use advisories)", "channel_kind": "feed",
     "urls": ["https://services.arcgis.com/uUvqNMGPm7axC2dD/arcgis/rest/services/HABs_Advisories_(Points)/FeatureServer/0"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "or-oha-hab-advisories", "publishes": "notices",
     "noun": "Data feed",
     "note": ("OHA's advisories and precautions for cyanobacteria blooms, with the issue date and a point: 39 of 64 "
              "rows on 2026-11-07 (5 Advisory, 34 Precaution). Read every refresh through the generic block; blooms, "
              "not sewage. (research/or/sources.json)"),
     "sources": ["or-oha-hab-advisories"]},
    {"id": "or-oha-beach-conditions", "agency": "Oregon Health Authority (Oregon Beach Monitoring Program)",
     "name": "Oregon Beach Monitoring Program (current beach conditions)", "channel_kind": "state_alert_page",
     "urls": ["https://www.oregon.gov/oha/PH/HEALTHYENVIRONMENTS/RECREATION/BEACHWATERQUALITY/Pages/status.aspx"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "or-oha-beach-monitoring", "publishes": "status",
     "noun": "Data feed",
     "signup_url": "https://public.govdelivery.com/accounts/ORHA/subscriber/new?topic_id=ORHA_190",
     "note": ("A table per coast (County, Beach, Status) with OPEN, ADVISORY, SEWAGE ('Sewage spills or major pollution "
              "events occurred. Avoid swimming or water contact.') and NO MONITORING; mid-May to mid-September. 'The "
              "2026 monitoring season has ended' on 2026-11-07 (answered 200). Read every refresh by the feed: ADVISORY as "
              "OHA's beach advisory, SEWAGE as its sewage advisory. (research/or/sources.json or-oha-beach-monitoring)"),
     "sources": ["or-oha-beach-monitoring"]},
    {"id": "or-oha-beach-notices-email", "agency": "Oregon Health Authority (Oregon Beach Monitoring Program)",
     "name": "Oregon Beach Monitoring Program (advisory notices by e-mail)", "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "notices", "records": False,
     "signup_url": "https://public.govdelivery.com/accounts/ORHA/subscriber/new?topic_id=ORHA_190",
     "note": "GovDelivery topic ORHA_190: OHA's beach advisory notices by e-mail. Not subscribed.",
     "sources": ["or-oha-beach-monitoring"]},
    {"id": "or-oda-shellfish-closures", "agency": "Oregon Department of Agriculture",
     "name": "Oregon Department of Agriculture (shellfish closures)", "channel_kind": "state_alert_page",
     "urls": ["https://www.oregon.gov/oda/programs/foodsafety/shellfish/pages/shellfishclosures.aspx"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Commercial and recreational shellfish closures, for biotoxins and after sewage events (Tillamook Bay). "
              "Not read in the research; page health first. (research/or/sources.json or-oda-shellfish)"),
     "sources": ["or-oda-shellfish"]},
    {"id": "or-swim-guide", "agency": "Swim Guide (Swim Drink Fish)", "name": "Swim Guide", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "app_only", "publishes": "unknown", "records": False,
     "note": ("The Swim Guide app lists Oregon beaches and Willamette River sites (research/or/profile.json "
              "advisories.swim_guide). An app; not read.")},
]
PORTLAND_EXTRA = [
    {"id": "or-portland-bes-big-pipe-tracker", "operator_id": "or-portland-bes",
     "name": "City of Portland Environmental Services (Big Pipe Tracker)", "permit": "OR0026905",
     "channel_kind": "operator_page", "urls": ["https://www.portland.gov/bes/big-pipe-tracker"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "noun": "Voluntary page",
     "ignore_lines": [r"\d{1,3}\s*%", r"\b\d{1,2}:\d{2}\s*[ap]m\b"],
     "status_pattern": r"Current CSO Advisories:\s*(.+?)(?:\n|$)",
     "note": ("The tracker shows the current CSO advisory ('There is no current CSO advisory in effect.' on 2026-11-07) "
              "and the Big Pipe tunnels' fill, updated every 15 minutes with up to a 45-minute lag (gauge 0 % at "
              "3:45 pm on 2026-11-07). Page health only: a fill level is not a report of an overflow, and the "
              "advisories are read from the news feed. (research/or/sources.json or-bes-big-pipe-tracker)"),
     "sources": ["or-bes-big-pipe-tracker"]},
    {"id": "or-portland-bes-cso-email", "operator_id": "or-portland-bes",
     "name": "City of Portland Environmental Services (CSO advisories by e-mail)", "permit": "OR0026905",
     "channel_kind": "email_list", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "email_only", "publishes": "notices", "records": False,
     "signup_url": "https://public.govdelivery.com/accounts/ORPORTLAND_ENT/signup/39493",
     "note": ("The City's Combined Sewer Overflow Advisories e-mail list (GovDelivery); the same advisories are read "
              "from the news feed. Not subscribed."),
     "sources": ["or-bes-cso-email"]},
]


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    ops = sorted((r for r in dis if r.get("state") == "OR"), key=lambda r: r["id"])
    rows = [finish(public_notice(op)) for op in ops] + [finish(base(**r)) for r in PORTLAND_EXTRA + AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "OR")
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
