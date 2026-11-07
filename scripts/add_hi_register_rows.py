"""Hawaii rows of the notice register (data/notice-channels/hi.json), made from the law, the Department of Health's
practice and data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_hi_register_rows.py [--dry-run]

The law (research/hi/report.md in the site repository; profile research/hi/profile.json):
  - HAR 11-62 Appendix B ("Responses for wastewater spills, overflows and discharges"), section 9: the owner or agent
    of a wastewater system reports spills, overflows and discharges to the Department of Health's Clean Water Branch.
    The rule's text could not be read by a script (its published copies refuse automated reads), so its deadline is
    not quoted; news reports describe the report as immediate. No duty to tell the public was found.
  - HAR 11-55 (water pollution control; NPDES): the permits' standard conditions require noncompliance to be reported
    to the Department.
  - The Department tells the public: an advisory on its Clean Water Branch portal (the JSON list the feed reads), signs
    at the water, e-mail notices by island and, for large spills, news releases. None of these is required by a rule
    found in the research: they are the Department's practice (basis voluntary).

Rows
  - Per operator (every Hawaii row of data/dischargers.json): <id>-doh-cwb-report (law basis, HAR 11-62 Appendix B):
    the report goes to the Department; it is not published, but the Department's advisory for the affected waters is,
    in the list the feed reads (feed_ingested).
  - Agency and voluntary rows: AGENCY below (the Department's report desk, its advisory list, its e-mail notices, its
    signs, its news releases; the Surfrider Foundation's volunteer sampling; the Swim Guide app).
A rerun replaces every hi- row it makes. Validated before writing.
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
FEED = "hi-doh-cwb-events-api"
PORTAL = "https://eha-cloud.doh.hawaii.gov/cwb/"
API = "https://eha-cloud.doh.hawaii.gov/cwb/api/events"
AUTHORITY = "Hawaii State Department of Health, Clean Water Branch"
Q_LAW = ("HAR 11-62 Appendix B (Responses for wastewater spills, overflows and discharges), section 9: whoever owns "
         "or runs a wastewater system reports spills, overflows and discharges to the Department of Health's Clean "
         "Water Branch (the rule's text was not read: its published copies refuse automated reads; its deadline is not "
         "quoted)")
Q_NPDES = ("HAR 11-55 (water pollution control), the NPDES permits' standard conditions: noncompliance that may "
           "endanger health or the environment is reported to the Department of Health")
AGENCY = [
    {"id": "hi-doh-cwb-spill-reports", "agency": AUTHORITY, "name": f"{AUTHORITY} (wastewater spill reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": f"{Q_LAW}; {Q_NPDES}",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False, "noun": "Report to the state",
     "note": ("No web form: every wastewater operator, public or private, reports spills, overflows and discharges to "
              "the Clean Water Branch. The reports themselves are not published; the Department posts an advisory for "
              "the waters it judges affected (hi-doh-cwb-advisories). No Hawaii rule requires the operator to tell the "
              "public. (research/hi/report.md section 2)"),
     "sources": ["hi-har-11-62-app-b", "hi-har-11-55"]},
    {"id": "hi-doh-cwb-advisories", "agency": AUTHORITY, "name": f"{AUTHORITY} (water quality advisories and events)",
     "channel_kind": "feed", "urls": [API], "method": "json", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": FEED, "publishes": "notices",
     "noun": "Data feed", "signup_url": PORTAL, "authority": AUTHORITY,
     "note": ("The Department's portal lists every advisory it issues (sewage spills, permit exceedances, Brown Water "
              "Advisories, beach advisories and retest notifications), open and closed, from one JSON endpoint: the "
              "newest 500 of 1,901 events on 2026-11-07 (Brown Water Advisory 279, Beach Notification 104, Beach "
              "Advisory 52, Sewage Spill 50, Permit Exceedance 15). Read every refresh by the feed. No terms or licence "
              "stated. The Department's practice; no rule requiring it was found. (research/hi/sources.json)"),
     "sources": [FEED]},
    {"id": "hi-doh-cwb-email-notices", "agency": AUTHORITY, "name": f"{AUTHORITY} (e-mail notices by island)",
     "channel_kind": "email_list", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "email_only", "publishes": "notices", "records": False,
     "signup_url": PORTAL,
     "note": ("E-mail notices of the same advisories, by island, through the portal's subscription form; the advisories "
              "themselves are read from the portal's list. Not subscribed."),
     "sources": [FEED]},
    {"id": "hi-doh-cwb-signs", "agency": AUTHORITY, "name": f"{AUTHORITY} (warning signs at the water)",
     "channel_kind": "lights_signs_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "notices", "records": False,
     "note": ("No web form: the Department posts warning signs at the affected waters (\"Warning signs have been "
              "posted\" in its sewage spill notices) and removes them when it cancels the advisory; the portal gives the "
              "removal time. On site only."),
     "sources": [FEED]},
    {"id": "hi-doh-news-releases", "agency": "Hawaii State Department of Health",
     "name": "Hawaii State Department of Health (news releases)", "channel_kind": "news_page",
     "urls": ["https://health.hawaii.gov/news/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The Department's news releases; large spills also get a release. Answered 200 on 2026-11-07. Page health "
              "only: the advisories are read from the portal's list. Voluntary. (research/hi/sources.json "
              "hi-doh-news-releases)"),
     "sources": ["hi-doh-news-releases"]},
    {"id": "hi-surfrider-bwtf", "agency": "Surfrider Foundation (Blue Water Task Force, Hawaii chapters)",
     "name": "Surfrider Foundation Blue Water Task Force", "channel_kind": "group_results",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "results", "records": False,
     "barrier_review": "volunteer sample results in a script-drawn map (https://bwtf.surfrider.org/), not notices",
     "note": ("Volunteer bacteria sampling at Hawaii beaches, shown in a map drawn by script; results, not advisories. "
              "Answered 200 on 2026-11-07. Prior art. (research/hi/sources.json hi-swim-guide-surfrider)"),
     "sources": ["hi-swim-guide-surfrider"]},
    {"id": "hi-swim-guide", "agency": "Swim Guide (Swim Drink Fish)", "name": "Swim Guide",
     "channel_kind": "swim_guide", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "unknown", "records": False,
     "note": ("The Swim Guide app lists Hawaii beaches (research/hi/profile.json advisories.swim_guide); its source for "
              "them is the Department's monitoring. An app; not read."),
     "sources": ["hi-swim-guide-surfrider"]},
]


def base(**kw) -> dict:
    r = {"state": "HI", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "HI":
            continue
        name, permit, oid = op["name"], op.get("npdes_permit"), op["id"]
        basis = Q_LAW + (f"; permit {permit}: " + Q_NPDES if permit else "")
        rows.append(finish(base(
            id=f"{oid}-doh-cwb-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=basis, basis_kind="law", monitored=False, unmonitored_reason="feed_ingested",
            feed_source_id=FEED, publishes="notices", noun="Report to the state",
            sources=["hi-har-11-62-app-b", "hi-har-11-55", FEED],
            note=(f"{name} reports spills, overflows and discharges to the Department of Health's Clean Water Branch. "
                  "The report itself is not published; the Department's advisory for the affected waters is, in the "
                  "list the feed reads (a notice names the facility when the Department gives it). No Hawaii rule "
                  "requires the operator to tell the public; its own pages were not searched. (research/hi/report.md "
                  "section 2)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "HI")
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
