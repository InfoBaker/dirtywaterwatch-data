"""Arkansas rows of the notice register (data/notice-channels/ar.json), made from the law, the research and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ar_register_rows.py [--dry-run]

The law (research/ar/report.md in the site repository; research/ar/profile.json and expansion-research.md):
  - The NPDES permits' Part II reporting conditions, as DEQ states them on its incident page: "Notification must be
    made within 24 hours of becoming aware of the circumstances, and in most cases, an additional 5-Day Written Report
    is required" for any unanticipated bypass, any upset, "Any Sanitary Sewer Overflow (SSO), no matter how small" and
    any unpermitted discharge "regardless of whether it reaches waters of the state". No rule requires the permittee
    or DEQ to tell the public; DEQ publishes the filed reports in its incident search.
  - No combined sewers: no CSO notice rows.
  - Per operator (every Arkansas row of data/dischargers.json, 380 on 2026-11-14), two rows:
      <id>-overflow-report (permit basis): the report to DEQ, which DEQ publishes in its search: read by the
        ar-deq-overflow-incidents feed.
      <id>-public-notice (voluntary, or the settlement for Little Rock Water Reclamation Authority, whose 2023 SSO
        response plan provides for warning signs): the operator's own pages were not searched one by one.
  - Agencies: DEQ's incident search and its Access download, DEQ's harmful algal bloom advisories and its e-mail lists,
    the Department of Health's closed swim beaches, the Corps of Engineers Little Rock District's swim beach closures
    (403 to this site's client), DEQ's complaints search (SEEK).
Each URL was answered on 2026-11-14 with one request with the project user agent, except where the row says not.
A rerun replaces every ar- row it makes. Validated before writing.
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
DEQ = "Arkansas Division of Environmental Quality"
SEARCH = "https://adeq.state.ar.us/water/enforcement/sso/data.aspx"
HAB_PAGE = "https://adeq.state.ar.us/water/planning/hab/"
HAB_JSON = "https://adeq.state.ar.us/water/planning/hab/advisories.json"
LISTS = "https://www.adeq.state.ar.us/poa/pi/emaillists.aspx"
SEEK = "https://adeq.state.ar.us/complaints/searches/"
ADH = ("https://healthy.arkansas.gov/programs-services/public-health-safety/marine-sanitation/"
       "arkansas-swim-beach-program/")
USACE = "https://www.swl.usace.army.mil/Home/Swim-Beach-Closures/"
LRWRA_PLAN = "https://www.lrwra.com/site/assets/files/1760/sanitary_sewer_overflow_response_plan_2023_ssorp.pdf"
Q_RULE = ("NPDES permit {permit}, Part II, as DEQ states it on its incident page: \"Notification must be made within 24 "
          "hours of becoming aware of the circumstances, and in most cases, an additional 5-Day Written Report is "
          "required for the following occurrences: ... Any Sanitary Sewer Overflow (SSO), no matter how small ... Any "
          "Unpermitted Discharge from either a collection or treatment system, regardless of whether it reaches waters "
          "of the state\"")

AGENCY = [
    {"id": "ar-deq-overflow-incidents", "agency": DEQ, "name": f"{DEQ}, Office of Water Quality",
     "channel_kind": "state_alert_page", "urls": [SEARCH], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "ar-deq-overflow-incidents", "publishes": "notices", "noun": "Overflow reports search",
     "note": ("DEQ's Reported Noncompliance Incident Data search: every SSO, bypass, upset and unpermitted discharge "
              "filed on its 24-hour online forms, usually by the next day, with the days it started and stopped, the "
              "volume, the filer's impact and a location text, but no coordinates, county or receiving water (2,449 "
              "reports from 2025-01-01 to 2026-11-14). A form search with no export endpoint; no rule requires DEQ to "
              "publish it. Read each run by the ar-deq-overflow-incidents feed. (ar-deq-overflow-incidents)"),
     "sources": ["ar-deq-overflow-incidents"]},
    {"id": "ar-deq-sso-access-db", "agency": DEQ, "name": DEQ, "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False, "noun": "Overflow reports database",
     "note": ("A Microsoft Access copy of the incident reports (NPDES_SSO_web.zip, 5 MB, adeq.state.ar.us/water/"
              "enforcement/sso/NPDES_SSO_web.zip), linked from the search; last "
              "modified 2025-08-13 (HEAD request 2026-11-14), so it lags the search by more than a year. Not read: an "
              "Access file, and the search holds the same reports. (ar-deq-sso-access-db)"),
     "sources": ["ar-deq-sso-access-db"]},
    {"id": "ar-deq-hab-advisories", "agency": DEQ, "name": DEQ, "channel_kind": "state_alert_page",
     "urls": [HAB_JSON], "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "ar-deq-hab-advisories", "publishes": "status",
     "noun": "Algal bloom advisories",
     "note": ("The file behind DEQ's Harmful Algal Blooms page and its archive: 52 recreational use health advisories "
              "since 2014 with the days posted and lifted, county and nearest town (4 in effect on 2026-11-14). Read "
              "each run by the ar-deq-hab-advisories feed. (ar-deq-hab-advisories)"),
     "sources": ["ar-deq-hab-advisories"]},
    {"id": "ar-deq-email-lists", "agency": DEQ, "name": DEQ, "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "notices", "records": False, "noun": "E-mail lists",
     "signup_url": LISTS,
     "note": ("DEQ's e-mail lists, news releases among them; harmful algal bloom advisories are announced by release. "
              "The advisories themselves are read from the ar-deq-hab-advisories file. (ar-deq-email-lists)"),
     "sources": ["ar-deq-email-lists"]},
    {"id": "ar-deq-seek-complaints", "agency": DEQ, "name": DEQ, "channel_kind": "state_alert_page", "urls": [SEEK],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False, "noun": "Complaints search",
     "note": ("DEQ's SEEK complaints search (complaints submitted on or after 2024-10-23): the public's reports, which "
              "carry complainants' names and addresses; not read until a safe-field review is done. A complaint is not a "
              "confirmed discharge. (ar-deq-seek-complaints)"),
     "sources": ["ar-deq-seek-complaints"]},
    {"id": "ar-adh-swim-beach-status", "agency": "Arkansas Department of Health",
     "name": "Arkansas Department of Health, Arkansas Swim Beach Program", "channel_kind": "local_health_page",
     "urls": [ADH], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "ar-adh-swim-beach-status", "publishes": "status",
     "noun": "Closed swim beaches",
     "note": ("The Swim Beach Program page lists the swim beaches the Department has closed, by its SB number and name "
              "(one on 2026-11-14), with no date, reason, water or point. Read each run by the ar-adh-swim-beach-status "
              "feed. (ar-adh-swim-beach-status)"),
     "sources": ["ar-adh-swim-beach-status"]},
    {"id": "ar-usace-swl-swim-beach-closures", "agency": "U.S. Army Corps of Engineers, Little Rock District",
     "name": "U.S. Army Corps of Engineers, Little Rock District", "channel_kind": "operator_page", "urls": [USACE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "status", "records": False, "noun": "Swim beach closures",
     "note": ("The district's swim beach closures page answers 403 to this site's identified client (2026-11-14, as on "
              "2026-11-09). Its closures have several causes, high water among them. (ar-usace-swl-swim-beach-closures)"),
     "sources": ["ar-usace-swl-swim-beach-closures"]},
]

OWN_NOTICE = {
    "ar-lrwra": {
        "channel_kind": "lights_signs_page", "urls": [], "method": None, "monitored": False,
        "unmonitored_reason": "other", "publishes": "unknown", "records": False, "noun": "Overflow signs",
        "legal_basis": ("Little Rock Water Reclamation Authority, Sanitary Sewer Overflow Response Plan (2023), adopted "
                        "under the authority's settlement: warning signs at overflows and public notification"),
        "basis_kind": "law", "sources": ["ar-lrwra-sso-plan"],
        "note": ("LRWRA's 2023 SSO response plan (read 2026-11-09) provides for temporary and permanent warning signs and "
                 "public notification at overflows, kept in its internal SSO database; no web page of notices was "
                 "found. The signs are the channel, so the notices are not on the open web.")},
}
PRIVATE = {"investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
           "campground or resort", "private club", "business or industrial", "institution",
           "facility (permittee not named)"}


def base(**kw) -> dict:
    r = {"state": "AR", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "AR":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        private = " The rule binds every NPDES permittee, public or private." if op.get("legal_form") in PRIVATE else ""
        rows.append(finish(base(
            id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=Q_RULE.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id="ar-deq-overflow-incidents", publishes="notices",
            noun="Report to the state", sources=["ar-deq-overflow-incidents", "ar-deq-overflow-forms"],
            note=(f"{name} reports every sanitary sewer overflow, unanticipated bypass, upset and unpermitted discharge to "
                  "DEQ within 24 hours on its online forms (in most cases with a five-day written report); DEQ publishes "
                  "the report in its Reported Noncompliance Incident Data search, usually the next day, read by the "
                  "ar-deq-overflow-incidents feed." + private))))
        own = OWN_NOTICE.get(oid)
        if own:
            rows.append(finish(base(id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit, **own)))
        else:
            rows.append(finish(base(
                id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit, channel_kind="operator_page",
                urls=[], method=None, legal_basis=None, basis_kind="voluntary", monitored=False,
                unmonitored_reason="other", publishes="unknown", records=False, noun="Notice to the public",
                sources=["ar-deq-overflow-forms"],
                note=("No URL known (not searched individually): no Arkansas rule requires a permittee to tell the "
                      "public of an overflow, and this operator's own pages were not searched, so whether it posts "
                      "notices online is not known. DEQ's form has a 'Public Notification' box among the actions taken; "
                      "the search shows the tick, not the notice."))))
    return rows


def rows_for(dis: list[dict]) -> list[dict]:
    for oid in OWN_NOTICE:
        if not any(d["id"] == oid for d in dis):
            raise SystemExit(f"{oid} is not in data/dischargers.json: run scripts/add_ar_operators.py first")
    return [finish(base(**r)) for r in AGENCY] + operator_rows(dis)


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = rows_for(dis)
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "AR")
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
