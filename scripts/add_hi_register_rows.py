"""Hawaii rows of the notice register (data/notice-channels/hi.json), made from the law, the Department of Health's
practice and data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_hi_register_rows.py [--dry-run]

The law, read on 2026-11-07 in the Department's own copy of chapter 11-62 (effective 2016-03-21:
https://health.hawaii.gov/opppd/files/2026/08/chapter-11-62-HAR-effective-2016.03.21.pdf):
  - HAR 11-62-06(g): the owner or person responsible for a wastewater system "shall notify the director immediately"
    of a wastewater spill, overflow or discharge into surface waters, unless they comply with the protocol of Appendix B,
    "Responses for Wastewater Spills, Overflows, and Discharges ('Spills')", dated July 1, 2014.
  - Appendix B section 2, spills from any public or private wastewater system into state waters (drainage ditches
    included): the owner or its agent shall (b) "immediately notify the CWB"; (c) "immediately send out a press
    release for spills of a thousand gallons or more and for lesser spills if they present a substantial threat to
    public health", to the Associated Press, the major newspapers and television stations, the Department's
    Communications Office and the Branch (section 7); (e) "immediately post warning signs in the area(s) likely to be
    affected by the spill and where public access is possible", the Department assuring enough signs and authorizing
    their removal; (f) monitor the receiving water for enterococci (and Clostridium perfringens in fresh or brackish
    water) for spills over 100 gallons until the Department says to stop (section 8); (g) a written report within five
    working days (section 9.a).
  - HAR 11-55 (NPDES): the permits' standard conditions require noncompliance to be reported to the Department.
  - The Department's own advisory list, e-mail notices and news releases are its practice: no rule requiring them was
    found (basis voluntary).

Rows
  - Per operator (every Hawaii row of data/dischargers.json): <id>-doh-cwb-report (law: the notice and the five-day
    report; the report is not published, the Department's advisory is, in the list the feed reads: feed_ingested);
    <id>-press-release (law, Appendix B 2.c and 7: no web channel known, not searched); <id>-warning-signs (law,
    Appendix B 2.e: on site only).
  - Agency and voluntary rows: AGENCY below (the Department's report desk and its check of the signs, its advisory
    list, its e-mail notices, its news releases; the Surfrider Foundation's volunteer sampling; the Swim Guide app).
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
AUTHORITY = "Hawaii Department of Health, Clean Water Branch"
RULE_URL = "https://health.hawaii.gov/opppd/files/2026/08/chapter-11-62-HAR-effective-2016.03.21.pdf"
Q_LAW = ("HAR 11-62-06(g) and Appendix B (Responses for Wastewater Spills, Overflows, and Discharges, July 1, 2014), "
         "sections 2.b and 9.a: for a spill into state waters the owner or its agent shall \"immediately notify the "
         "CWB\" and submit a written report within five working days")
Q_PRESS = ("HAR 11-62 Appendix B, sections 2.c, 4.c and 7: for a spill into state waters, and for one onto the ground "
           "where the public has access, the owner or its agent \"shall immediately send out a press release for spills "
           "of a thousand gallons or more and for lesser spills if they present a substantial threat to public "
           "health\", to the Associated Press, major newspapers and television news stations, the Department's "
           "Communications Office and the Clean Water Branch (the Wastewater Branch for a ground spill)")
Q_SIGNS = ("HAR 11-62 Appendix B, sections 2.e and 4.e: the owner or its agent \"shall immediately post warning signs "
           "in the area(s) likely to be affected by the spill and where public access is possible\" (a spill into state "
           "waters), and \"in the vicinity of the spill area\" (a spill onto the ground where the public has access); "
           "the Department assures that enough signs are posted and authorizes their removal")
Q_GROUND = ("HAR 11-62 Appendix B, section 4 (spills onto the ground, not into state waters, where the public has or may "
            "have access): for a spill of a thousand gallons or more the owner or its agent immediately notifies the "
            "Wastewater Branch on Oahu, or the district environmental health program chief on the other islands, and "
            "reports in writing under section 9.a; smaller spills go in a quarterly tabulated summary (section 9.b)")
Q_NPDES = ("HAR 11-55 (water pollution control), the NPDES permits' standard conditions: noncompliance that may "
           "endanger health or the environment is reported to the Department of Health")
AGENCY = [
    {"id": "hi-doh-cwb-spill-reports", "agency": AUTHORITY, "name": f"{AUTHORITY} (wastewater spill reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": f"{Q_LAW}; {Q_NPDES}",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False, "noun": "Report to the state",
     "note": ("No web form: every wastewater operator, public or private, reports a spill into state waters to the "
              "Clean Water Branch immediately and in writing within five working days (HAR 11-62 Appendix B, read in "
              f"the Department's copy {RULE_URL} on 2026-11-07). The reports themselves are not published; the "
              "Department posts an advisory for the waters it judges affected (hi-doh-cwb-advisories). The operator's "
              "own duties to the public are its press release and its warning signs (the operator rows)."),
     "sources": ["hi-har-11-62-app-b", "hi-har-11-55"]},
    {"id": "hi-doh-wwb-ground-spill-reports", "agency": "Hawaii Department of Health, Wastewater Branch",
     "name": "Hawaii Department of Health, Wastewater Branch (ground spill reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_GROUND, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("No web form: spills that reach no state water, where the public has access, are reported to the "
              "Wastewater Branch (or a district office) and, under 1,000 gallons, only in quarterly summaries. Neither "
              "is published, and such spills get no Clean Water Branch advisory; the operator's press release and "
              "signs (sections 4.c and 4.e) are the public notice. (HAR 11-62 Appendix B, read 2026-11-07)"),
     "sources": ["hi-har-11-62-app-b"]},
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
     "channel_kind": "lights_signs_page", "urls": [], "method": None, "legal_basis": Q_SIGNS, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "notices", "records": False,
     "note": ("No web form: the operator posts warning signs at the affected waters; the Department checks that enough "
              "are posted and authorizes their removal, and its portal gives the removal time (\"Warning signs have "
              "been posted\" in its sewage spill notices). On site only."),
     "sources": ["hi-har-11-62-app-b", FEED]},
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
            note=(f"{name} reports a spill into state waters to the Department of Health's Clean Water Branch "
                  "immediately and in writing within five working days. The report itself is not published; the "
                  "Department's advisory for the affected waters is, in the list the feed reads (a notice names the "
                  "facility when the Department gives it). (HAR 11-62 Appendix B, read 2026-11-07)"))))
        rows.append(finish(base(
            id=f"{oid}-press-release", operator_id=oid, name=name, permit=permit, channel_kind="news_page", urls=[],
            method=None, legal_basis=Q_PRESS, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="notices", records=False, noun="Press release", sources=["hi-har-11-62-app-b"],
            note=("No URL known (not searched): the rule sends the operator's press release to the news media and the "
                  "Department, not to a web page; whether this operator posts its releases on its own site was not "
                  "searched."))))
        rows.append(finish(base(
            id=f"{oid}-warning-signs", operator_id=oid, name=name, permit=permit, channel_kind="lights_signs_page",
            urls=[], method=None, legal_basis=Q_SIGNS, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="notices", records=False, noun="Warning signs", sources=["hi-har-11-62-app-b"],
            note="No web form: warning signs at the affected waters, posted by the operator. On site only.")))
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
