"""Alabama rows of the notice register (data/notice-channels/al.json), made from the law, the research and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_al_register_rows.py [--dry-run]

The law (research/al/report.md §2.1 in the site repository; profile research/al/profile.json):
  - Ala. Admin. Code r. 335-6-6-.12(l)6.(v) (quoted in the 2017 petition): "The permittee shall report to the Director,
    the public, the county health department, and any other affected entity such as public water systems, as soon as
    possible upon becoming aware of any notifiable sanitary sewer overflow." A notifiable SSO (r. 335-6-6-.02(hh), as
    quoted on ADEM's AEPACS form) reaches a surface water of the State or may imminently and substantially endanger
    human health. ADEM's AEPACS SSO form (v1.5) sets the notice at 24 hours and a written follow-up at 5 days. The rule
    sets no channel or content for the public notice; the 2017 petition of the Alabama Rivers Alliance and eight
    riverkeepers asked for one (web posting, media notice, opt-in alerts) and a 2018 petition for a 12-hour window was
    denied. ADEM answered with its county e-mail list (May 2017) and its public SSO map. There are no combined sewer
    permits in Alabama, so no CSO rows.
  - Per operator (every Alabama row of data/dischargers.json, 379 on 2026-11-07), two rows:
      <id>-overflow-report (permit basis): the report to ADEM through AEPACS, which ADEM publishes on its SSO map and
        layer within minutes: read by the al-adem-sso-history feed.
      <id>-public-notice (law basis): the rule's notice to the public, for which no channel is set: unmonitored
        "other", "not searched individually" (barrier not_verified), since the operators' own pages were not searched
        one by one; for MAWSS it is its news posts and for Jefferson County its opt-in alerts (PUBLIC_NOTICE_CHANNEL).
  - Beaches: the Coastal Alabama Beach Monitoring Program (ADEM with the Alabama Department of Public Health, under the
    federal BEACH Act): ADEM's map layer (read by the al-adem-beach-monitoring feed) and ADPH's beach page and swim
    advisories.
Rows: AGENCY and the per-operator rows; each URL was answered on 2026-11-07 with one GET with the project
user agent (jccal.org answered 403; mobilebaykeeper.org did not answer within 90 seconds).
A rerun replaces every al- row it makes. Validated before writing.
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
ADEM = "Alabama Department of Environmental Management"
ADPH = "Alabama Department of Public Health"
SSO_MAP = "https://gis.adem.alabama.gov/sso/index.html"
SSO_LAYER = ("https://gis.adem.alabama.gov/arcgis/rest/services/SSOs_ALL_OB_ID/MapServer/0/query?where=1%3D1&"
             "returnCountOnly=true&f=json")
BEACH_LAYER = ("https://gis.adem.alabama.gov/arcgis/rest/services/BeachMonitoring_New/MapServer/15/query?where=1%3D1&"
               "outFields=ID,Descriptio,WaterbodyN,Date,Advisory&returnGeometry=false&f=json")
BEACH_PAGE = "https://adem.alabama.gov/coastal/ademadph-coastal-alabama-beach-monitoring-program"
ADPH_BEACH = "https://www.alabamapublichealth.gov/environmental/beach-monitoring.html"
Q_RULE = ("Ala. Admin. Code r. 335-6-6-.12(l)6.(v): \"The permittee shall report to the Director, the public, the county "
          "health department, and any other affected entity such as public water systems, as soon as possible upon "
          "becoming aware of any notifiable sanitary sewer overflow\" (a notifiable SSO, r. 335-6-6-.02(hh): one that "
          "reaches a surface water of the State or may imminently and substantially endanger human health)")
Q_FORM = ("ADEM AEPACS NPDES SSO Event Reporting Form v1.5: \"Immediate notification shall be provided within 24 hours of "
          "becoming aware of the event. ... The follow-up report shall be submitted within five days\"; Ala. Admin. Code "
          "r. 335-6-6-.12(l)6.; NPDES permit {permit}")
Q_BEACH = ("BEACH Act of 2000 (33 U.S.C. 1346): a state beach program funded under it notifies the public of exceedances "
           "of the bacteria criteria; the Coastal Alabama Beach Monitoring Program of ADEM and ADPH (statute text not "
           "quoted)")

AGENCY = [
    {"id": "al-adem-sso-map", "agency": ADEM, "name": ADEM, "channel_kind": "state_alert_page",
     "urls": [SSO_MAP, SSO_LAYER], "method": "json", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "al-adem-sso-history",
     "publishes": "notices", "noun": "Sewer overflow map",
     "note": ("ADEM's public SSO map and the two layers behind it: every SSO report filed through AEPACS since 2012 "
              "(14,758 on 2026-11-07), posted within minutes of filing, with the point, start and stop, volume, receiving "
              "water and permittee; the map shows ongoing reports and those that stopped in the last 10 days. No law "
              "requires ADEM to post them: ADEM began the map after the 2017 petition. Read hourly by the feed. "
              "(al-adem-sso-history, al-adem-sso-map-live)"),
     "sources": ["al-adem-sso-history", "al-adem-sso-map-live"]},
    {"id": "al-adem-sso-email", "agency": ADEM, "name": ADEM, "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "notices", "records": False, "noun": "E-mail alerts",
     "note": ("No web form: ADEM's opt-in e-mail notice of SSO reports by county (since May 2017, at the request of "
              "Waterkeepers Alabama and the Alabama Rivers Alliance). Sign-up only; the same reports are on ADEM's map "
              "and layer. Voluntary. (al-adem-sso-email)"),
     "sources": ["al-adem-sso-email"]},
    {"id": "al-adem-efile-sso", "agency": ADEM, "name": ADEM, "channel_kind": "state_alert_page",
     "urls": ["http://app.adem.alabama.gov/efile/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "documents", "records": False,
     "noun": "Filed reports",
     "note": ("ADEM's eFile: the signed AEPACS SSO forms, searched per permit (DocType SSO; answered 200 on 2026-11-07). "
              "Each record links its permit's search; the same reports are read from ADEM's layer, so the forms are not "
              "fetched. (al-adem-efile-sso)"),
     "sources": ["al-adem-efile-sso"]},
    {"id": "al-county-health-departments", "agency": "Alabama county health departments",
     "name": "Alabama county health departments", "channel_kind": "local_health_page", "urls": [], "method": None,
     "legal_basis": Q_RULE, "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "unknown", "records": False, "noun": "Report to the health department",
     "note": ("No web form: the rule names the county health department as a recipient of the permittee's report; no "
              "county health department page that posts SSO reports was found (not searched county by county). "
              "(al-adem-rule-335-6-6-12)"),
     "sources": ["al-adem-rule-335-6-6-12"]},
    {"id": "al-adem-beach-monitoring-map", "agency": ADEM, "name": f"{ADEM} (Coastal Alabama Beach Monitoring)",
     "channel_kind": "state_alert_page", "urls": [BEACH_LAYER], "method": "json", "legal_basis": Q_BEACH,
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "al-adem-beach-monitoring", "publishes": "status", "noun": "Beach monitoring map",
     "note": ("The stations layer behind ADEM's beach monitoring map: 25 coastal stations with the last sample date, "
              "the results PDF and an advisory code (11 at every station on 2026-11-07; ADEM does not publish the codes' "
              "meaning, so any other code is shown as this site's caution, never as an advisory). Read hourly by the feed. (al-adem-beach-monitoring)"),
     "sources": ["al-adem-beach-monitoring"]},
    {"id": "al-adem-beach-monitoring-page", "agency": ADEM, "name": f"{ADEM} (Coastal Alabama Beach Monitoring)",
     "channel_kind": "state_alert_page", "urls": [BEACH_PAGE], "method": "html", "legal_basis": Q_BEACH,
     "basis_kind": "law", "monitored": True, "unmonitored_reason": None, "publishes": "link_only",
     "link_text": "the beach monitoring map and site list", "records": False, "every_hours": 24,
     "noun": "Beach monitoring page",
     "note": ("ADEM's program page (answered 200 on 2026-11-07, the old beachMonitoring.cnt address redirects here): "
              "links to the map and the site list, each site giving its latest advisory status and results. "
              "(al-adem-beach-monitoring)"),
     "sources": ["al-adem-beach-monitoring"]},
    {"id": "al-adph-beach-monitoring", "agency": ADPH, "name": ADPH, "channel_kind": "local_health_page",
     "urls": [ADPH_BEACH], "method": "html", "legal_basis": Q_BEACH, "basis_kind": "law", "monitored": True,
     "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "Beach advisories",
     "note": ("ADPH's beach monitoring page (answered 200 on 2026-11-07). ADPH issues the coastal swim advisories as news "
              "releases (Wolf Bay at Orange Beach Waterfront Park, issued July 2026 and lifted September 2026, as the "
              "press reported) and lifts them when enterococci fall below 104 per 100 mL. Watched for changes; the "
              "advisory state itself is read from ADEM's map layer. (al-adem-beach-monitoring)"),
     "sources": ["al-adem-beach-monitoring"]},
    {"id": "al-mobile-baykeeper-swim", "agency": "Mobile Baykeeper", "name": "Mobile Baykeeper",
     "channel_kind": "group_results", "urls": ["https://mobilebaykeeper.org/swim"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "results", "records": False, "noun": "Voluntary page",
     "note": ("Mobile Baykeeper's SWIM bacteria monitoring, 16 sites in Mobile and Baldwin counties, weekly from April to "
              "September (results to Swim Guide). The page did not answer within 90 seconds on 2026-11-07: not verified in the research; not yet "
              "watched. Voluntary. (al-mobile-baykeeper-swim)"),
     "sources": ["al-mobile-baykeeper-swim"]},
    {"id": "al-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": ["https://www.theswimguide.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "results", "noun": "Swim Guide listing",
     "note": ("Swim Guide (a script app): Mobile Baykeeper's SWIM results are listed there (research/al/profile.json, "
              "swim_guide true). Voluntary; no API."),
     "sources": ["al-mobile-baykeeper-swim"]},
]

# operators whose own channel for the rule's public notice is known: their -public-notice row is that channel
PUBLIC_NOTICE_CHANNEL = {
    "al-mawss": {
        "channel_kind": "news_page", "urls": ["https://www.mawss.com/"], "method": "html", "monitored": True,
        "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 6,
        "noun": "Overflow news posts", "sources": ["al-mawss-news", "al-adem-rule-335-6-6-12"],
        "note": ("MAWSS gives its public notice as a news post for each overflow (\"wastewater overflow\", \"preliminary "
                 "advisory\") on its website; the home page answered 200 on 2026-11-07, the news list not traced "
                 "further. Watched for changes; the same overflows are read from ADEM's layer. (al-mawss-news)")},
    "al-jefferson-county": {
        "channel_kind": "email_list", "urls": [], "method": None, "monitored": False,
        "unmonitored_reason": "email_only", "publishes": "notices", "records": False, "noun": "Overflow alerts",
        "sources": ["al-jefferson-county-everbridge", "al-adem-rule-335-6-6-12"],
        "note": ("No web form: Jefferson County Environmental Services gives its public notice as opt-in overflow "
                 "alerts (Everbridge, since March 2021) and GovDelivery no-contact advisories, to subscribers only; "
                 "www.jccal.org answered 403 to the project user agent on 2026-11-07. The same overflows are read from "
                 "ADEM's layer. (al-jefferson-county-everbridge)")},
}
OPERATOR_EXTRA: dict = {}
PRIVATE = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
           "campground or resort", "private club", "business or industrial", "institution",
           "facility (permittee not named)"}


def base(**kw) -> dict:
    r = {"state": "AL", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "AL":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        private = " The rule binds every NPDES permittee, public or private." if op.get("legal_form") in PRIVATE else ""
        ssos = op.get("kind") == "sso"
        rows.append(finish(base(
            id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=Q_FORM.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id="al-adem-sso-history", publishes="notices",
            noun="Report to the state", sources=["al-adem-sso-history", "al-adem-rule-335-6-6-12"],
            note=(f"{name} reports each notifiable sanitary sewer overflow to ADEM within 24 hours and files the 5-day "
                  "follow-up through AEPACS; ADEM posts the report on its SSO map and layer within minutes, read by the "
                  "al-adem-sso-history feed. "
                  + ("Its permits appear on ADEM's layer." if ssos else "None of its permits has a report on ADEM's "
                     "layer (read 2026-11-07).") + private))))
        own = PUBLIC_NOTICE_CHANNEL.get(oid)
        if own:                      # the operator's own channel for the rule's notice
            rows.append(finish(base(id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit,
                                    legal_basis=Q_RULE, basis_kind="law", **own)))
        else:
            rows.append(finish(base(
                id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit, channel_kind="operator_page",
                urls=[], method=None, legal_basis=Q_RULE, basis_kind="law", monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, noun="Notice to the public",
                sources=["al-adem-rule-335-6-6-12", "al-petition-2017-notice"],
                note=("No URL known (not searched individually): the rule requires the permittee to report a notifiable "
                      "overflow to the public as soon as possible but sets no channel or content, and this operator's "
                      "own pages were not searched, so whether it posts its notices online is not known. The 2017 "
                      "petition asking for a minimum standard was not adopted." + private))))
        for x in OPERATOR_EXTRA.get(oid, []):
            x = dict(x)
            suffix = x.pop("suffix")
            rows.append(finish(base(id=f"{oid}-{suffix}", operator_id=oid, name=name, permit=permit, **x)))
    return rows


def rows_for(dis: list[dict]) -> list[dict]:
    for oid in PUBLIC_NOTICE_CHANNEL:
        if not any(d["id"] == oid for d in dis):
            raise SystemExit(f"{oid} is not in data/dischargers.json: run scripts/add_al_operators.py first")
    return [finish(base(**r)) for r in AGENCY] + operator_rows(dis)


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = rows_for(dis)
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "AL")
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
