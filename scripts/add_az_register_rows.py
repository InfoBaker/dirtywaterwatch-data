"""Arizona rows of the notice register (data/notice-channels/az.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_az_register_rows.py [--dry-run]

The law (research/az/report.md §2.1 in the site repository; A.A.C. R18-9-C305 read on law.cornell.edu, 2026-11-03):
  - R18-9-C305(F)(1)(a): a collection-system permittee reports to ADEQ, "by telephone, facsimile, or on the applicable
    notification form on the Department's Internet web site", any release that is an imminent and substantial threat
    to public health or the environment, no later than 24 hours after becoming aware of it; (F)(1)(b) a written report
    within five business days; (F)(2) an annual report by March 1 tabulating releases over 50 gallons. R18-9-C305(A)
    sets the threshold (over 2,000 gallons, or 50 to 2,000 gallons reaching a public area, a street, a perennial
    stream, an intermittent stream in flow, a waterbody, a detention basin or drywell, an occupied building, or within
    100 feet of a school or well). AZPDES permits carry the federal 24-hour and five-day reports (40 CFR
    122.41(l)(6)); permittees file the five-day report in ADEQ's myDEQ, and EPA publishes the AZPDES reports in its
    overflow tables.
  - R18-9-C305(G): "Post a notice, in a format approved by the Department, at any location where there were more than
    three reportable releases ... during any 12-month period", warning of the releases and their health hazards, where
    the public is likely to come in contact with the release, kept up until 12 months pass without one. The only
    public duty; nothing on the web.
  - No CSO permits; no alert list; no public notice duty on ADEQ.
Rows
  - Per operator (every Arizona row of data/dischargers.json but the two whose permits are not sewage permits,
    LEFT_OUT): <id>-adeq-report, the report to ADEQ under the rule and the permit, made public through EPA's overflow
    tables (read by the echo-sewer-overflow feed). Tribal rows: <id>-epa-report (EPA Region 9 permits on tribal land,
    where the state rule does not apply).
  - Statewide: the warning-sign duty (signs only), ADEQ's own report intake (myDEQ, login), the APP-only systems'
    reports and the annual reports (not published), EPA's tables; the voluntary bloom pages (ADEQ's list behind a bot
    check, the National Park Service's Lake Mead page, Mohave County's notices), Tempe Town Lake, Swim Guide (none);
    Pima County's service-request portal as its only channel (AGENCY below).
A rerun replaces every az- row it makes. Validated before writing.
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
FEED = "echo-sewer-overflow"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
RULE_URL = "https://www.law.cornell.edu/regulations/arizona/Ariz-Admin-Code-SS-R18-9-C305"
LAW = "az-law-r18-9-c305"
Q_REPORT = ('A.A.C. R18-9-C305(F)(1)(a): "A permittee shall report to the Department, by telephone, facsimile, or on '
            'the applicable notification form on the Department\'s Internet web site, any release that is an imminent '
            'and substantial threat to public health or the environment as soon as practical, but no later than 24 '
            'hours of becoming aware of the release"; (F)(1)(b) a written report within five business days')
Q_PERMIT = ("AZPDES permit {permit}: the 24-hour and five-day noncompliance reports of 40 CFR 122.41(l)(6), filed in "
            "ADEQ's myDEQ; " + Q_REPORT)
Q_TRIBAL = ("NPDES permit {permit} (EPA Region 9, tribal land): the 24-hour and five-day noncompliance reports of 40 CFR "
            "122.41(l)(6), to EPA")
Q_SIGNS = ('A.A.C. R18-9-C305(G): "Post a notice, in a format approved by the Department, at any location where there '
           'were more than three reportable releases under subsection (F)(2)(a) from the sewage collection system during '
           'any 12-month period", with "a warning that identified the releases or potential releases at the location and '
           'potential health hazards", posted "at a place where the public is likely to come in contact with the '
           'release" and kept until 12 months pass without a reportable release')
Q_ANNUAL = ("A.A.C. R18-9-C305(F)(2): an annual report to ADEQ by March 1 tabulating the releases of more than 50 "
            "gallons in the previous calendar year")
LEFT_OUT = {"az-city-of-tempe": "its only permit is the city's MS4 (stormwater) permit",
            "az-city-of-tucson": "its permits are a groundwater remediation discharge and the city's MS4; Tucson's sewers "
                                 "are Pima County's"}
AGENCY = [
    {"id": "az-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): Arizona's AZPDES permittees "
              "file their 24-hour and five-day reports in ADEQ's myDEQ and EPA publishes them (288 Arizona reports from "
              "42 permits, September 2019 to 28 October 2026, in the 2026-11-04 extract; a median 3 days from start to "
              "receipt). No report from Pima County's permits. (research/az/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "az-epa-sobe"]},
    {"id": "az-r18-9-c305-warning-signs", "agency": "Sewage collection system permittees (A.A.C. R18-9-C305)",
     "name": "Warning signs at repeated release locations", "channel_kind": "lights_signs_page", "urls": [],
     "method": None, "legal_basis": Q_SIGNS, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False, "noun": "Warning signs",
     "note": ("Arizona's only public notice duty for sewage releases: a sign, in ADEQ's approved format, where more than "
              "three reportable releases happened at one location in 12 months. Signs only: nothing is posted on the web "
              "and no list of the signed locations was found. It binds every collection-system permittee, public or "
              f"private, AZPDES or APP-only. ({RULE_URL}; research/az/report.md §2.1)"),
     "sources": [LAW]},
    {"id": "az-adeq-release-report", "agency": "Arizona Department of Environmental Quality",
     "name": "Arizona Department of Environmental Quality (release reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "login", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("The report goes to ADEQ (the Spill Line by phone, the web form, and the five-day report in myDEQ, which is "
              "account-only); ADEQ does not post the reports, and azdeq.gov answers 403 to scripted requests "
              "(2026-11-07). The AZPDES reports reach the public through EPA's tables days later. "
              "(research/az/report.md §2.1)"),
     "sources": ["az-adeq-sso-reporting", LAW]},
    {"id": "az-adeq-app-only-release-reports", "agency": "Arizona Department of Environmental Quality",
     "name": "Arizona Department of Environmental Quality (APP-only collection systems)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("Collection systems that hold only an Aquifer Protection Permit (no AZPDES surface-water permit) report their "
              "releases to ADEQ under the same rule, but the reports are not in EPA's tables and no web channel found "
              "publishes them. (research/az/profile.json barriers)"),
     "sources": [LAW]},
    {"id": "az-adeq-annual-release-reports", "agency": "Arizona Department of Environmental Quality",
     "name": "Arizona Department of Environmental Quality (annual release reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_ANNUAL, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("Each collection-system permittee's annual table of releases over 50 gallons goes to ADEQ; no web channel "
              "found publishes it. (research/az/report.md §2.1)"),
     "sources": [LAW]},
    {"id": "az-adeq-reported-habs", "agency": "Arizona Department of Environmental Quality",
     "name": "Arizona Department of Environmental Quality (reported harmful algal blooms)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "notices",
     "note": ("ADEQ's \"Currently Reported\" bloom list (https://azdeq.gov/reported-habs) answers 403 to the project user "
              "agent (2026-11-07); a search snippet showed Lake Mohave advisories (Placer Cove danger, Eagle Wash "
              "warning, a lake-wide watch) as of 2026-06-12. Testing is voluntary for lake managers. Blooms, not sewage. "
              "No data service was found on ADEQ's ArcGIS Online account. (research/az/report.md §2.5)"),
     "sources": ["az-adeq-reported-habs"]},
    {"id": "az-nps-lake-mead-habs", "agency": "National Park Service, Lake Mead National Recreation Area",
     "name": "Lake Mead National Recreation Area (harmful algal blooms)", "channel_kind": "shared_site",
     "urls": ["https://www.nps.gov/lake/planyourvisit/harmful-blue-green-algae-blooms-habs.htm"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The park's bloom page for Lake Mead and Lake Mohave, waters shared with Nevada (\"Severe HAB at Eagle Wash "
              "cove\", last updated 2026-11-02; answered 200 to the project user agent on 2026-11-07). Blooms, not "
              "sewage. Voluntary. (research/az/report.md §2.5)"),
     "sources": ["az-nps-lake-mead-habs"]},
    {"id": "az-mohave-county-health-notices", "agency": "Mohave County Department of Public Health",
     "name": "Mohave County (news and notices)", "channel_kind": "news_page",
     "urls": ["https://www.mohave.gov/news-notices/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The county's news list, where the health department posts bloom warnings for Lake Havasu and the Colorado "
              "River (answered 200 on 2026-11-07). Scattered posts, not a list of advisories. Voluntary. "
              "(research/az/report.md §2.5)"),
     "sources": ["az-mohave-county-health-habs"]},
    {"id": "az-tempe-town-lake", "agency": "City of Tempe", "name": "City of Tempe (Tempe Town Lake)",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "unknown",
     "note": ("Tempe Town Lake's page (https://www.tempe.gov/government/community-services/tempe-town-lake) answers 403 "
              "to the project user agent (2026-11-07); whether the city posts E. coli results or closures was not "
              "verified. Voluntary. (research/az/report.md §2.5)"),
     "sources": ["az-tempe-town-lake"]},
    {"id": "az-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("No Swim Guide affiliate or Arizona listing was found (search only, 2026-11-03); Arizona has no state beach "
              "monitoring program. (research/az/report.md §2.5)"),
     "sources": ["az-swim-guide"]},
]


def base(**kw) -> dict:
    r = {"state": "AZ", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def first_sewage_permit(op: dict) -> str | None:
    """The row's first plant permit (not a construction, de minimis, pretreatment or MS4 coverage)."""
    ps = op.get("npdes_permits") or []
    return next((p for p in ps if p[:3] in ("AZ0", "AZ1", "NN0")), ps[0] if ps else None)


def operator_rows(dis: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    rows, left = [], []
    for op in dis:
        if op.get("state") != "AZ":
            continue
        oid, name = op["id"], op["name"]
        if oid in LEFT_OUT:
            left.append((oid, LEFT_OUT[oid]))
            continue
        permit = first_sewage_permit(op)
        private = (" The rule and the permit bind the holder, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility", "tribal") else "")
        if op.get("legal_form") == "tribal":
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
                method=None, legal_basis=Q_TRIBAL.format(permit=permit), basis_kind="permit", monitored=False,
                unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices", noun="EPA report",
                sources=["az-epa-sobe"],
                note=(f"{name}'s permits are EPA's (tribal land): reports go to EPA, which publishes the reports filed "
                      f"electronically in its overflow tables (read by the {FEED} feed); none are there in the "
                      "2026-11-04 extract. Arizona's collection-system rule does not apply on tribal land. "
                      "(research/az/report.md §3)"))))
            continue
        rows.append(finish(base(
            id=f"{oid}-adeq-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices", noun="EPA report",
            sources=["az-epa-sobe", LAW],
            note=(f"{name} reports its releases to ADEQ; EPA publishes the AZPDES reports in its overflow tables, read "
                  f"by the {FEED} feed, a median 3 days after the start.{private} No public notice is required beyond "
                  "the warning sign at a location with repeated releases (az-r18-9-c305-warning-signs). "
                  "(research/az/report.md §2.1)"))))
        if oid == "az-pima-county":
            rows.append(finish(base(
                id="az-pima-county-service-requests", operator_id=oid, name=name, permit=None,
                channel_kind="operator_page", urls=[], method=None, legal_basis=None, basis_kind="voluntary",
                monitored=False, unmonitored_reason="none_found", publishes="none", records=False,
                sources=["az-pima-rwrd"],
                note=("Pima County's wastewater pages offer a sewer service-request portal "
                      "(sewerservicerequest.pima.gov) and an emergency line, but no list or notice of overflows; no "
                      "report under its permits is in EPA's tables (2026-11-04 extract), though EPA's collection-system "
                      "table lists its systems. No web channel found. (research/az/report.md §2.3)"))))
    return rows, left


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows, left = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "AZ")
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
