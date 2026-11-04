"""Michigan rows of the notice register (data/notice-channels/mi.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_mi_register_rows.py [--dry-run]

The law (MCL 324.3112a, read on legislature.mi.gov 2026-11-03; research/mi/report.md §2.1 in the site repository):
  (1) "the person responsible for the sewer system shall immediately, but not more than 24 hours after the discharge
      begins, notify the department; local health departments ...; a daily newspaper of general circulation in the
      county or counties in which a municipality notified pursuant to subsection (4) is located; and a daily newspaper
      of general circulation in the county in which the discharge occurred or is occurring". It binds whoever is
      responsible for the sewer system, public or private.
  (2) "Upon being notified of a discharge under subsection (1), the department shall promptly post the notification
      on its website": EGLE's MiEnviro CSO/SSO List, read by the mi-egle-mienviro-cso-sso-list feed (one statewide
      row covering every operator).
  (3) the operator "shall test the affected waters for E. coli", results to the county health departments and EGLE.
  Great Lakes basin CSO permittees also owe a public notice within 4 hours under 40 CFR 122.38 through their public
  notification plans; GLWA's plan (MI0022802, 2018, read) gives it through the MiEnviro list; the other plans were
  not read.

Rows
  - Per operator (every Michigan row of data/dischargers.json except the general permits for petroleum sites EPA's CSO
    inventory lists, kind cso_closed_or_none, and the cities' stormwater (MS4) permits EPA files as plants): <id>-newspaper-notice (print_only), <id>-health-department-notice
    (no_web_page), <id>-ecoli-results (no_web_page). For a CSO operator also <id>-cso-public-notification (permit
    basis): GLWA's is read through the feed (feed_ingested); the others are not_verified (plan not read).
  - Agency and voluntary rows: AGENCY below.
A rerun replaces every mi- row it makes and keeps rows it does not make (none today). Validated before writing.
"""
from __future__ import annotations

import json
import re
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
CHECKED = "2026-11-04"
LIST_PAGE = "https://mienviro.michigan.gov/ncore/external/overflow/list"
LIST_SERVICE = "https://mienviro.michigan.gov/ncore/ss/ssolist"
FEED = "mi-egle-mienviro-cso-sso-list"
LAW = "mi-law-mcl-324-3112a"
Q1 = ('MCL 324.3112a(1): "the person responsible for the sewer system shall immediately, but not more than 24 hours after '
      'the discharge begins, notify the department; local health departments ...; a daily newspaper of general '
      'circulation in the county or counties in which a municipality notified pursuant to subsection (4) is located; and '
      'a daily newspaper of general circulation in the county in which the discharge occurred or is occurring"')
Q3 = ('MCL 324.3112a(3): "Each time a discharge to surface waters occurs under subsection (1), the person responsible for '
      'the sewer system shall test the affected waters for E. coli to assess the risk to the public health", with the '
      'results to the county health departments and the department (up to 10 tests; the health department may waive it)')
Q_CSO = ("40 CFR 122.38: a CSO permittee in the Great Lakes Basin gives the public an initial notice of a discharge as "
         "soon as possible and no later than 4 hours after becoming aware of it, a supplemental notice within 7 days "
         "after it ends and an annual notice, under the public notification plan its permit requires")
DUTIES = [
    # (suffix, channel_kind, noun, legal_basis, what, barrier sentence)
    ("newspaper-notice", "news_page", "Printed notice", Q1,
     "notice of each discharge to a daily newspaper of general circulation in the county where it occurred (and in "
     "the counties of downstream municipalities that asked to be told) within 24 hours of its start",
     "Printed only; EGLE's posting of the same notice on its list is the web record."),
    ("health-department-notice", "local_health_page", "Health department notice", Q1,
     "notice of each discharge to the local health departments within 24 hours of its start; the law does not require "
     "the departments to publish it",
     "No web channel found."),
    ("ecoli-results", "local_health_page", "Testing results", Q3,
     "E. coli tests of the affected waters after each discharge to surface waters, with the results sent to the "
     "county health departments and EGLE; the law does not require their publication",
     "No web channel found: the results stay with the health departments and EGLE."),
]
AGENCY = [
    {"id": "mi-egle-mienviro-cso-sso-list", "agency": "Michigan Department of Environment, Great Lakes, and Energy",
     "name": "Michigan EGLE (MiEnviro CSO/SSO List)", "channel_kind": "state_alert_page",
     "urls": [LIST_PAGE, LIST_SERVICE], "method": "json",
     "legal_basis": ('MCL 324.3112a(2): "Upon being notified of a discharge under subsection (1), the department shall '
                     'promptly post the notification on its website."'),
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": FEED,
     "publishes": "notices", "noun": "State page",
     "note": ("EGLE's public list of sewage discharge reports (CSO, SSO, retention treatment basin and other "
              "discharges) with start, end, volume, permit, outfall and receiving water; it covers every operator in "
              "Michigan, public or private, because each must notify EGLE (MCL 324.3112a(1)) and EGLE must post the "
              "notice. GLWA's CSO notification plan names it as GLWA's 4-hour public notice. The list gives no "
              "coordinates and no posting time, and its JSON service is undocumented and carries no licence "
              "statement. No e-mail alert for overflows exists. (research/mi/report.md §2.2)"),
     "sources": [FEED, LAW]},
    {"id": "mi-egle-sewage-discharge-program", "agency": "Michigan Department of Environment, Great Lakes, and Energy",
     "name": "Michigan EGLE (SSO, CSO and RTB program page)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "documents", "noun": "Voluntary page",
     "note": ("Program page (Michigan.gov/SewageDischarge, "
              "https://www.michigan.gov/egle/about/organization/water-resources/sso-cso-rtb) linking the list and the "
              "annual CSO/SSO/RTB reports (latest found 2021). Answered 403 to the project user agent on 2026-11-04; "
              "not tried with a browser agent. Voluntary. (research/mi/report.md §2.2)"),
     "sources": ["mi-egle-sso-cso-rtb-program"]},
    {"id": "mi-egle-beachguard", "agency": "Michigan Department of Environment, Great Lakes, and Energy",
     "name": "Michigan EGLE BeachGuard (beach monitoring)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "login", "publishes": "status",
     "note": ("Advisory and sample detail need a MiEnviro login; not read yet: the BeachGuard map (https://mienviro.michigan.gov/nsite/beach/map/, answered 200 on "
              "2026-11-04) shows only a current status colour per beach site (2,913 sites) through a POST service. Local health departments enter results and issue "
              "advisories within 24 hours of an exceedance (E. coli 300 per 100 mL daily geometric mean or 130 "
              "30-day). The research did not trace the statute behind the program, so the row is filed voluntary. "
              "(research/mi/report.md §2.5)"),
     "sources": ["mi-egle-beachguard"]},
    {"id": "mi-egle-beach-advisory-emails", "agency": "Michigan Department of Environment, Great Lakes, and Energy",
     "name": "MiEnviro e-mail subscriptions (beach advisories)", "channel_kind": "email_list",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "notices",
     "signup_url": "https://mienviro.michigan.gov/ncore/external/home",
     "note": ("E-mails for beach advisories by site or county; there is no subscription for sewage overflows. "
              "Voluntary. Not signed up. (research/mi/report.md §2.5)"),
     "sources": ["mi-egle-mienviro-subscriptions"]},
    {"id": "mi-egle-hab-reports", "agency": "Michigan EGLE and Michigan Department of Health and Human Services",
     "name": "Michigan harmful algal bloom reports", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "unknown",
     "note": ("HAB program page (https://www.michigan.gov/egle/about/organization/water-resources/glwarm/"
              "harmful-algal-blooms) with the HAB Reports Map of verified reports for the last two weeks and a "
              "reporting form; the map's layer was not traced. The page answered 403 to the project user agent on "
              "2026-11-04. Blooms, not sewage. Voluntary. (research/mi/report.md §2.5)"),
     "sources": ["mi-egle-hab-reports-map"]},
    {"id": "mi-clinton-river-watershed-council", "agency": "Clinton River Watershed Council",
     "name": "Clinton River Watershed Council", "channel_kind": "group_results",
     "urls": ["https://www.crwc.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "unknown", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("Watershed group for the Clinton River and Lake St. Clair shore (Macomb and Oakland counties, CSO and SSO "
              "receiving waters). Home page read (200 on 2026-11-04); no overflow or bacteria results page was found "
              "on it. Voluntary. (research/mi/report.md §2.5: watershed groups not searched in depth)"),
     "sources": ["mi-watershed-groups"]},
    {"id": "mi-detroit-riverkeeper", "agency": "Detroit Riverkeeper (Friends of the Detroit River)",
     "name": "Detroit Riverkeeper", "channel_kind": "group_results",
     "urls": ["https://www.detroitriver.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "unknown", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("Riverkeeper for the Detroit River, the receiving water of GLWA's largest CSO outfalls. Home page read "
              "(200 on 2026-11-04); no overflow or bacteria results page was found on it. Voluntary. "
              "(research/mi/report.md §2.5)"),
     "sources": ["mi-watershed-groups"]},
    {"id": "mi-friends-of-the-rouge", "agency": "Friends of the Rouge", "name": "Friends of the Rouge",
     "channel_kind": "group_results", "urls": ["https://therouge.org/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "unknown",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Watershed group for the Rouge River, which takes the Wayne County, Dearborn and GLWA CSO outfalls. Home "
              "page read (www.therouge.org answered 301 to therouge.org on 2026-11-04); no overflow or bacteria results "
              "page was found on it. Voluntary. (research/mi/report.md §2.5)"),
     "sources": ["mi-watershed-groups"]},
    {"id": "mi-huron-river-watershed-council", "agency": "Huron River Watershed Council",
     "name": "Huron River Watershed Council", "channel_kind": "group_results", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "results",
     "note": ("Volunteer river monitoring on the Huron River (https://www.hrwc.org/our-work/programs/river-monitoring/). "
              "Answered 403 to the project user agent on 2026-11-04; not tried with a browser agent. Voluntary. "
              "(research/mi/report.md §2.5)"),
     "sources": ["mi-watershed-groups"]},
]


MS4 = re.compile(r"\bMS4\b")


def base(**kw) -> dict:
    r = {"state": "MI", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    rows, left = [], []
    for op in dis:
        if op.get("state") != "MI":
            continue
        if op.get("kind") == "cso_closed_or_none":
            left.append((op["id"], "not a sewer system (a general permit for a petroleum or remediation site)"))
            continue
        if MS4.search(op.get("name") or ""):
            left.append((op["id"], "a municipal separate storm sewer (MS4) permit: stormwater, not a sewer system "
                                   "MCL 324.3112a covers; the city's sewer system has its own row"))
            continue
        name = op.get("name")
        priv = op.get("legal_form") in ("investor-owned utility", "member-owned utility", "homeowners' association",
                                        "mobile-home park", "campground or resort", "private club",
                                        "business or industrial", "institution", "facility (permittee not named)")
        who = " The law binds the person responsible for the sewer system, public or private." if priv else ""
        for suffix, kind, noun, basis, what, bar in DUTIES:
            rows.append(finish(base(
                id=f"{op['id']}-{suffix}", operator_id=op["id"], name=name, channel_kind=kind, urls=[], method=None,
                legal_basis=basis, basis_kind="law", monitored=False, unmonitored_reason="other",
                publishes="unknown", records=False, noun=noun, sources=[LAW],
                note=f"No web form: {name}: {what}. {bar}{who} (research/mi/report.md §2.1)")))
        if op.get("kind") == "cso":
            permit = op.get("npdes_permit")
            if op["id"] == "mi-glwa-wrrf-mi0022802":
                rows.append(finish(base(
                    id=f"{op['id']}-cso-public-notification", operator_id=op["id"], name=name, permit=permit,
                    channel_kind="state_alert_page", urls=[LIST_PAGE, LIST_SERVICE], method="json",
                    legal_basis=(Q_CSO + '; GLWA CSO Public Notification Plan (2018), VI.2: "Within four hours of '
                                 "becoming aware of a CSO discharge, GLWA will provide public notification through the "
                                 "Michigan Department of Environmental Quality's (MEDQ) MiWaters System.\""),
                    basis_kind="permit", monitored=False, unmonitored_reason="feed_ingested", feed_source_id=FEED,
                    publishes="notices", noun="State page", sources=["mi-glwa-cso-notification-plan", FEED],
                    note=("GLWA gives its 4-hour notice and its 7-day supplemental update through EGLE's MiEnviro list "
                          "(the MiWaters system's successor), which the feed reads; its first notices often carry no "
                          "permit number or receiving water. (research/mi/report.md §2.1)"))))
            else:
                rows.append(finish(base(
                    id=f"{op['id']}-cso-public-notification", operator_id=op["id"], name=name, permit=permit,
                    channel_kind="operator_page", urls=[], method=None,
                    legal_basis=Q_CSO + (f"; NPDES permit {permit}: public notification plan (permit text not read)"
                                         if permit else ""),
                    basis_kind="permit", monitored=False, unmonitored_reason="other", publishes="unknown",
                    records=False, noun="CSO public notification", sources=["mi-epa-gl-cso-michigan"],
                    note=(f"No URL known (not searched): {name}'s CSO public notification plan was not read. GLWA's "
                          "plan gives the 4-hour notice through EGLE's MiEnviro list, and this permittee's discharges "
                          "reach the public record there as well; EPA's Great Lakes CSO page lists websites for 27 of "
                          "40 Michigan operators, not fetched one by one. (research/mi/report.md §2.3)"))))
    return rows, left


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows, left = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "MI")
    doc = merge(doc, rows, drop)
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        NP.save_register(doc["channels"], REGISTER)
    return {"rows": len(rows), "left_out": left,
            "barriers": dict(Counter(r["barrier"] or ("review" if r.get("barrier_review") else "none") for r in rows)),
            "by_basis": dict(Counter(r["basis_kind"] for r in rows))}


if __name__ == "__main__":
    rep = run("--dry-run" in sys.argv[1:])
    print(json.dumps(rep, indent=1))
