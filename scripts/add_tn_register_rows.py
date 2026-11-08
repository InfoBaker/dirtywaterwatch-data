"""Tennessee rows of the notice register (data/notice-channels/tn.json), made from the law, the research and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_tn_register_rows.py [--dry-run]

The law (research/tn/report.md §2.1 in the site repository; profile research/tn/profile.json):
  - Tenn. Comp. R. & Regs. 0400-40-05-.07(2)(o), a term of every NPDES permit: "In the case of any noncompliance, or any
    release ... which could cause a threat to human health or the environment, the permittee shall: 1. Report the
    noncompliance or release to the Commissioner within 24 hours from the time the permittee becomes aware of the
    circumstances. ... 2. Submit a written report within five days". (2)(n)1 prohibits sanitary sewer overflows. No
    rule requires the permittee or TDEC to tell the public; TDEC publishes the filed reports in its Events Report.
  - Combined sewer permits (Nashville TN0020575, Clarksville TN0020656, Chattanooga TN0024210): the national CSO
    Control Policy (59 FR 18688, 1994) makes public notification one of the nine minimum controls a CSO permit
    carries; the permits' own clauses were not read, so their rows say so (not verified).
  - Per operator (every Tennessee row of data/dischargers.json, 315 on 2026-11-07), two rows:
      <id>-overflow-report (permit basis): the report to TDEC, which TDEC publishes in its Events Report: read by the
        tn-tdec-events-report feed (whose host refused this pipeline's client on 2026-11-07: the agency row says so).
      <id>-public-notice (voluntary): no rule sets a notice to the public; the operator's own pages were not searched
        one by one (barrier not_verified). Franklin's is the signs and web notices the Harpeth Conservancy describes.
    and a third, <id>-cso-notice (permit basis), for the three CSO permittees.
  - Advisories: TDEC's bacteriological (water-contact) advisory page and its posted-streams list (PDF), and TDEC's HAB
    advisory layer (read by the tn-tdec-hab-advisory-status feed).
Each URL was answered on 2026-11-07 with one request with the project user agent, except where the row says not.
A rerun replaces every tn- row it makes. Validated before writing.
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
TDEC = "Tennessee Department of Environment and Conservation"
EVENTS = "https://dataviewers.tdec.tn.gov/dataviewers/f?p=2005:34140"
EVENTS_MAP = "https://dataviewers.tdec.tn.gov/dataviewers/f?p=2005:34152"
DOCS = "https://tdec.tn.gov/document-viewer/search/SewerOF"
ADVISORIES = ("https://www.tn.gov/content/tn/environment/program-areas/wr-water-resources/watershed-stewardship/"
              "bacteriological-and-fishing-advisories.html")
ADVISORY_PDF = "https://www.tn.gov/content/dam/tn/environment/water/watershed-planning/wr_wq_fish-advisories.pdf"
HAB_LAYER = ("https://services5.arcgis.com/bPacKTm9cauMXVfn/arcgis/rest/services/survey123_ecdde0d22aef4bc897dd90831ea05618/"
             "FeatureServer/0/query?where=1%3D1&returnCountOnly=true&f=json")
Q_RULE = ("Tenn. Comp. R. & Regs. 0400-40-05-.07(2)(o) (a term of every NPDES permit): \"In the case of any noncompliance, "
          "or any release (whether or not caused by improper operation and maintenance), which could cause a threat to "
          "human health or the environment, the permittee shall: 1. Report the noncompliance or release to the "
          "Commissioner within 24 hours from the time the permittee becomes aware of the circumstances. ... 2. Submit a "
          "written report within five days\"; NPDES permit {permit}")
Q_CSO = ("NPDES permit {permit} (combined sewer system): the national CSO Control Policy (59 FR 18688, 1994; Clean Water "
         "Act section 402(q)) makes public notification of CSO occurrences and impacts one of the nine minimum controls "
         "a CSO permit carries; the permit's own clause was not read")
Q_ADVISORY = ("Tennessee Water Quality Control Act (Tenn. Code Ann. 69-3-101 et seq.): TDEC posts streams whose bacteria "
              "levels make contact a risk to health (\"The department notifies citizens when the waters are not safe to "
              "swim in\", TDEC's advisory page); statute text not quoted")

AGENCY = [
    {"id": "tn-tdec-events-report", "agency": TDEC, "name": f"{TDEC}, Division of Water Resources",
     "channel_kind": "state_alert_page", "urls": [EVENTS], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "notices",
     "records": False, "noun": "Overflow reports table",
     "note": ("TDEC's Events Report (an Oracle APEX interactive report): every sewer overflow, release, bypass, upset and "
              "washout filed through MyTDEC Forms since 2020 (12,857 rows on 2026-11-03), about five days after the "
              "event, with dates, county, city, street, permittee and volume; one CSV download. No rule requires TDEC "
              "to publish it. The host answers 403 to this pipeline's identified client (AWS load balancer, every path, "
              "2026-11-07); the tn-tdec-events-report feed retries each run. (tn-tdec-events-report)"),
     "sources": ["tn-tdec-events-report"]},
    {"id": "tn-tdec-events-map", "agency": TDEC, "name": f"{TDEC}, Division of Water Resources",
     "channel_kind": "state_alert_page", "urls": [EVENTS_MAP], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "notices",
     "records": False, "noun": "Overflow reports map",
     "note": ("TDEC's Events Map (APEX page 34152): the same reports as points, loaded by the page's script. The host "
              "answers 403 to this pipeline's identified client (2026-11-07), so whether the points can be read is not "
              "known. (tn-tdec-events-report)"),
     "sources": ["tn-tdec-events-report"]},
    {"id": "tn-tdec-document-viewer-sewerof", "agency": TDEC, "name": TDEC, "channel_kind": "state_alert_page",
     "urls": [DOCS], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "documents", "records": False, "noun": "Filed reports",
     "note": ("TDEC's Document Viewer, Sewer Overflow folder: the filed report of each event (the copy of record, likely "
              "with the receiving water and cause). Answers 403 to this pipeline's client (2026-11-07). "
              "(tn-tdec-document-viewer-sewerof)"),
     "sources": ["tn-tdec-document-viewer-sewerof"]},
    {"id": "tn-tdec-bacteriological-advisories", "agency": TDEC, "name": TDEC, "channel_kind": "state_alert_page",
     "urls": [ADVISORIES], "method": "html", "legal_basis": Q_ADVISORY, "basis_kind": "law", "monitored": True,
     "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "Water-contact advisories",
     "note": ("TDEC's Bacteriological and Fishing Advisories page (answered 200 on 2026-11-07; last updated 2026-08-25): "
              "the press releases issuing and lifting water-contact advisories (Cash Hollow Creek lifted 2026-08-21) and "
              "a link to the posted-streams list. No table: watched for changes. (tn-tdec-bacteriological-advisories)"),
     "sources": ["tn-tdec-bacteriological-advisories"]},
    {"id": "tn-tdec-posted-streams-list", "agency": TDEC, "name": TDEC, "channel_kind": "state_alert_page",
     "urls": [ADVISORY_PDF], "method": "pdf", "legal_basis": Q_ADVISORY, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "tn-tdec-bacteriological-advisories",
     "publishes": "status",
     "noun": "Posted streams list",
     "note": ("TDEC's list of posted streams, rivers and reservoirs (PDF, Rev. August 2026, read 2026-11-07): 25 stream "
              "segments under a standing bacteriological (water-contact) advisory, 21 of them naming sewer collection "
              "systems or a sewage plant among the sources (Knoxville's First, Second, Third and Goose creeks, "
              "Chattanooga's Citico and Chattanooga creeks, Nashville's Browns, Richland and McCrory creeks and the "
              "Cumberland River from Bordeaux Bridge to Woodland Street, Memphis's Cypress Creek), with no dates. "
              "Read daily by the feed as TDEC's standing advisories. (tn-tdec-bacteriological-advisories)"),
     "sources": ["tn-tdec-bacteriological-advisories"]},
    {"id": "tn-tdec-hab-advisory-status", "agency": TDEC, "name": TDEC, "channel_kind": "state_alert_page",
     "urls": [HAB_LAYER], "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "tn-tdec-hab-advisory-status", "publishes": "status",
     "noun": "Algal bloom advisories",
     "note": ("The layer behind TDEC's HAB Dashboard: bloom reports with TDEC's finding and its Precautionary or No "
              "Contact advisories with their dates (71 rows, 21 advisories, on 2026-11-07). Read hourly by the feed, "
              "advisory fields only: the layer also exposes the reporters' names, phone numbers and emails. "
              "(tn-tdec-hab-advisory-status)"),
     "sources": ["tn-tdec-hab-advisory-status"]},
    {"id": "tn-clean-water-nashville", "agency": "Metro Water Services (Clean Water Nashville)",
     "name": "Clean Water Nashville", "channel_kind": "operator_page",
     "urls": ["https://www.cleanwaternashville.org/history-and-consent-decree"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 24, "noun": "Consent decree page",
     "note": ("Metro Water Services' consent decree program site (answered 200 on 2026-11-07): the history, a map of CSO "
              "locations and the decree reports; no event notices found. Voluntary. (tn-clean-water-nashville)"),
     "sources": ["tn-clean-water-nashville"]},
    {"id": "tn-chattanooga-cd-quarterly", "agency": "City of Chattanooga", "name": "City of Chattanooga",
     "channel_kind": "operator_page",
     "urls": ["https://register.chattanooga.gov/sites/default/files/resources/Chattanooga-Quarterly-Report-No.-52---2nd-Quarter_2026.pdf"],
     "method": "pdf", "legal_basis": "Consent decree, United States v. City of Chattanooga, No. 1:12-cv-00245 (E.D. Tenn. 2013): quarterly reports",
     "basis_kind": "law", "monitored": True, "unmonitored_reason": None, "publishes": "documents", "records": False,
     "every_hours": 168, "noun": "Quarterly reports",
     "note": ("Chattanooga's consent decree quarterly report (No. 52, second quarter 2026; answered 200 on 2026-11-07): "
              "a table of each SSO with date, location, volume and receiving water. The same events are in TDEC's "
              "Events Report. Watched weekly. (tn-chattanooga-cd-quarterly)"),
     "sources": ["tn-chattanooga-cd-quarterly"]},
    {"id": "tn-hamilton-wwta-quarterly", "agency": "Hamilton County Water and Wastewater Treatment Authority",
     "name": "Hamilton County Water and Wastewater Treatment Authority", "channel_kind": "operator_page",
     "urls": ["https://wwta.hamiltontn.gov/DocumentCenter/View/797/Quarterly-Report-No-3-January-16-2025-April-15-2025"],
     "method": "pdf", "legal_basis": "WWTA consent decree (2013): quarterly reports", "basis_kind": "law",
     "monitored": True, "unmonitored_reason": None, "publishes": "documents", "records": False, "every_hours": 168,
     "noun": "Quarterly reports",
     "note": ("WWTA's consent decree quarterly report (No. 3, January to April 2025; answered 200 on 2026-11-07): SSO "
              "tables. The same events are in TDEC's Events Report. Watched weekly. (tn-hamilton-wwta-quarterly)"),
     "sources": ["tn-hamilton-wwta-quarterly"]},
    {"id": "tn-harpeth-conservancy", "agency": "Harpeth Conservancy", "name": "Harpeth Conservancy",
     "channel_kind": "group_results", "urls": ["https://harpethconservancy.org/sewer-videos"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 168, "noun": "Voluntary page",
     "note": ("The Harpeth Conservancy's sewer page (answered 200 on 2026-11-07): advocacy for real-time public reporting "
              "of overflows; it notes that Franklin and Brentwood post overflows with signs and a web notice within days. "
              "Voluntary. (tn-harpeth-conservancy)"),
     "sources": ["tn-harpeth-conservancy"]},
]

FRANKLIN = ("https://www.franklintn.gov/government/departments-k-z/water-management-department/water-reclamation-division/"
            "sanitary-sewer-release-and-overflows")
OWN_NOTICE = {
    "tn-city-of-franklin": {
        "channel_kind": "operator_page", "urls": [FRANKLIN], "method": "html", "monitored": False,
        "unmonitored_reason": "bot_wall", "publishes": "documents", "records": False, "noun": "Overflow page",
        "sources": ["tn-harpeth-conservancy"],
        "note": ("Franklin's Water Reclamation Division page on sanitary sewer releases and overflows (its permit's "
                 "definitions, causes, the Sewer Overflow Response Plan and the numbers to report one, as a search "
                 "engine shows it); the Harpeth Conservancy reports that Franklin also posts each overflow with signs and "
                 "a web notice within days. www.franklintn.gov answers 403 to the project user agent (2026-11-07), so "
                 "whether the page lists events is not known. Voluntary.")},
}
# operators whose reports are not in TDEC's Events Report (research 2026-11-03: no rows for their permits)
NOT_IN_TABLE = {
    "tn-memphis": ("The City of Memphis's two plants (TN0020711, TN0020729) had no rows in TDEC's Events Report when the "
                   "research read the whole table on 2026-11-03, although the city's sewers overflow (consent decree, "
                   "United States and State of Tennessee v. City of Memphis, W.D. Tenn., 2012); how its reports reach "
                   "TDEC, and why they are not published there, is not known."),
}
PRIVATE = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
           "campground or resort", "private club", "business or industrial", "institution",
           "facility (permittee not named)"}


def base(**kw) -> dict:
    r = {"state": "TN", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "TN":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        private = " The rule binds every NPDES permittee, public or private." if op.get("legal_form") in PRIVATE else ""
        if oid in NOT_IN_TABLE:
            rows.append(finish(base(
                id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
                method=None, legal_basis=Q_RULE.format(permit=permit), basis_kind="permit", monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, noun="Report to the state",
                sources=["tn-tdec-events-report", "tn-law-0400-40-05-07"],
                note=NOT_IN_TABLE[oid] + " Not verified in the research beyond the table's rows.")))
        else:
          rows.append(finish(base(
            id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=Q_RULE.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id="tn-tdec-events-report", publishes="notices",
            noun="Report to the state", sources=["tn-tdec-events-report", "tn-law-0400-40-05-07"],
            note=(f"{name} reports each release that could threaten health or the environment to TDEC within 24 hours "
                  "and in writing within five days through MyTDEC Forms; TDEC publishes the report in its Events Report "
                  "about five days after the event, read by the tn-tdec-events-report feed, whose host has refused this "
                  "site's client since 2026-11-07 (the tn-tdec-events-report row)." + private))))
        own = OWN_NOTICE.get(oid)
        if own:
            rows.append(finish(base(id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit,
                                    legal_basis=None, basis_kind="voluntary", **own)))
        else:
            rows.append(finish(base(
                id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit, channel_kind="operator_page",
                urls=[], method=None, legal_basis=None, basis_kind="voluntary", monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, noun="Notice to the public",
                sources=["tn-law-0400-40-05-07"],
                note=("No URL known (not searched individually): no Tennessee rule requires a permittee to tell the "
                      "public of an overflow, and this operator's own pages were not searched, so whether it posts "
                      "notices online is not known."))))
        if op.get("kind") == "cso":
            p = next((x for x in op.get("npdes_permits") or [] if x in ("TN0020575", "TN0020656", "TN0024210")), permit)
            rows.append(finish(base(
                id=f"{oid}-cso-notice", operator_id=oid, name=name, permit=p, channel_kind="operator_page", urls=[],
                method=None, legal_basis=Q_CSO.format(permit=p), basis_kind="permit", monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, noun="CSO notice",
                sources=["tn-clean-water-nashville"] if oid == "tn-metro-water-services" else [],
                note=("No URL known: no public notice of a combined sewer overflow event was found for this permittee, "
                      "and the permit's public-notification clause is not verified in the research. CSO discharges are "
                      "permitted and are not in TDEC's Events Report."))))
    return rows


def rows_for(dis: list[dict]) -> list[dict]:
    for oid in OWN_NOTICE:
        if not any(d["id"] == oid for d in dis):
            raise SystemExit(f"{oid} is not in data/dischargers.json: run scripts/add_tn_operators.py first")
    return [finish(base(**r)) for r in AGENCY] + operator_rows(dis)


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = rows_for(dis)
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "TN")
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
