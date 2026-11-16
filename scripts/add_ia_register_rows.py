"""Iowa rows of the notice register (data/notice-channels/ia.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ia_register_rows.py [--dry-run]

The law: 567 IAC 63.6 (an unanticipated bypass or upset reported to the DNR field office by telephone within 24 hours,
in writing within five days; DNR decides whether the public must be told, and then the operator prepares the notice).
The reports are public in DNR's Field Office Compliance records (FOCOMP), one page per report.

Rows
  - Per operator whose facility the FOCOMP feed reads (its notification_channel says so): <id>-field-office-report,
    feed_ingested by ia-dnr-focomp-incoming-reports.
  - Per CSO operator: <id>-cso-public-notification (permit basis; permit text not read; no web notice found except
    Waterloo's page, which is not a CSO permittee).
  - Waterloo: its SSO & Bypass Public Notification page (feed_ingested by ia-waterloo-sso-notices).
  - Agency rows (AGENCY): DNR's FOCOMP records for every other facility (public, one page per report, not read yet),
    DNR's advisory news releases (feed_ingested), the spill search, AQuIA's beach results (empty out of season), the
    beach hotline, the Corps of Engineers' reservoir beaches (telephone), WWPIE permit documents, EPA's overflow tables
    (no Iowa report).
A rerun replaces every ia- row it makes. Validated before writing.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts"))
from add_ia_operators import READ  # noqa: E402
from add_register_rows import finish, merge  # noqa: E402
from ingest import notification_pages as NP  # noqa: E402

REGISTER = ROOT / "data" / "notice-channels"
DIS = ROOT / "data" / "dischargers.json"
CHECKED = "2026-11-14"
FOCOMP = "https://programs.iowadnr.gov/focomp/"
LAW = ("567 IAC 63.6: an unanticipated bypass or upset reported to the DNR field office by telephone within 24 hours and "
       "in writing within five days; public notice when DNR decides one is needed")
Q_CSO = ("NPDES permit {permit}: CSO public notification, one of the nine minimum controls of the federal CSO Control "
         "Policy (59 FR 18688, 1994); permit text not read")
WATERLOO_URL = "https://www.ci.waterloo.ia.us/departments/waste_management/sso_and_bypass_public_notification.php"
AGENCY = [
    {"id": "ia-dnr-focomp-other-facilities", "agency": "Iowa Department of Natural Resources",
     "name": "Iowa DNR field office records (minor municipal and other facilities)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": LAW, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "documents", "records": False, "noun": "Report to the state",
     "sources": ["ia-dnr-focomp-incoming-reports"],
     "barrier_review": ("public in DNR's Field Office Compliance records, one page per report with no list or download; "
                        "this site reads the 105 major municipal facilities and not yet the about 930 others"),
     "note": ("The bypass reports of Iowa's minor municipal and semi-public facilities are public in FOCOMP "
              f"({FOCOMP}) on each facility's page; not read yet (the feed reads the major municipal facilities).")},
    {"id": "ia-dnr-news-releases", "agency": "Iowa Department of Natural Resources",
     "name": "Iowa DNR (news releases, advisory topic)", "channel_kind": "news_page",
     "urls": ["https://www.iowadnr.gov/topics/203/feed"], "method": "rss", "legal_basis": LAW, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "ia-dnr-news-releases",
     "publishes": "notices", "noun": "News releases", "sources": ["ia-dnr-news-releases", "ia-dnr-advisory-rss"],
     "note": ("DNR's releases when it decides the public must be told: four municipal wastewater releases from November "
              "2024 to October 2026 in the advisory topic (five records: one release names two places), and one "
              "release about a company's process wastewater, which is not a sewage report. Read by the feed.")},
    {"id": "ia-dnr-focomp-spill-search", "agency": "Iowa Department of Natural Resources",
     "name": "Iowa DNR (spill search)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "documents", "records": False, "noun": "Spill records",
     "sources": ["ia-dnr-focomp-spills"],
     "barrier_review": "a search form with posted queries; its wastewater rows were not assessed against the bypass reports",
     "note": ("FOCOMP's spill search (https://programs.iowadnr.gov/focomp/Search/Spills) lists reported spills by "
              "material and medium; not read (the bypass reports cover the municipal systems).")},
    {"id": "ia-aquia-beaches", "agency": "Iowa Department of Natural Resources",
     "name": "Iowa DNR (AQuIA beach monitoring)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "results", "records": False, "noun": "Beach results",
     "sources": ["ia-aquia-beaches"],
     "barrier_review": ("public JSON and CSV, but empty out of season (read 2026-11-14): the reader is to be built on "
                        "the first rows of the 2027 season"),
     "note": ("AQuIA's state and county beach results (https://programs.iowadnr.gov/aquia/beaches; JSON "
              "/aquia/api/v1/beaches/weekly_results/state?week=all) give each beach's sample date, E. coli, five-week "
              "geometric mean, microcystin and status, Memorial Day to Labor Day; both answered [] on 2026-11-14.")},
    {"id": "ia-dnr-beach-hotline", "agency": "Iowa Department of Natural Resources",
     "name": "Iowa DNR (beach monitoring hotline)", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "results", "records": False, "noun": "Beach hotline",
     "sources": ["ia-aquia-beaches"],
     "note": "Beach advisory status by telephone only (515-725-3434), updated Fridays in season."},
    {"id": "ia-usace-reservoir-beaches", "agency": "U.S. Army Corps of Engineers",
     "name": "Corps of Engineers reservoirs (Coralville, Red Rock, Saylorville, Rathbun)",
     "channel_kind": "local_health_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Beach advisories",
     "sources": ["ia-aquia-beaches"],
     "note": ("DNR's beach page refers to each lake's ranger for advisories at the Corps beaches: by telephone only.")},
    {"id": "ia-wwpie-permits", "agency": "Iowa Department of Natural Resources",
     "name": "Iowa DNR (WWPIE permit documents)", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False, "noun": "Permit documents", "sources": ["ia-wwpie-permits"],
     "barrier_review": "a permit search, not a notice channel: read for permit terms only",
     "note": "WWPIE (https://programs.iowadnr.gov/wwpie/) holds the final and draft permits; no notice is posted there."},
    {"id": "ia-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "EPA sewer overflow and bypass tables (Iowa)", "channel_kind": "feed", "urls": [], "method": None,
     "legal_basis": "40 CFR part 127 (NPDES electronic reporting)", "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False, "noun": "EPA overflow tables",
     "sources": ["ia-epa-sobe"], "checked": "2026-11-15",
     "note": ("No web channel found for Iowa: EPA's current and all-versions overflow tables (tables of 2026-11-13, "
              "read 2026-11-15) "
              "hold no Iowa event, and two Iowa collection-system rows; Iowa reports go to DNR, not EPA's system.")},
]


def base(**kw) -> dict:
    r = {"state": "IA", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "IA":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        if READ in (op.get("notification_channel") or ""):
            rows.append(finish(base(
                id=f"{oid}-field-office-report", operator_id=oid, name=name, permit=permit, channel_kind="feed",
                urls=[], method=None, legal_basis=LAW, basis_kind="law", monitored=False,
                unmonitored_reason="feed_ingested", feed_source_id="ia-dnr-focomp-incoming-reports",
                publishes="notices", noun="Report to the state", sources=["ia-dnr-focomp-incoming-reports"],
                note=(f"{name} reports each bypass to the DNR field office; the field office's record of the report "
                      "(times, receiving stream, gallons) is public in FOCOMP and read by the feed."))))
        if op.get("kind") == "cso":
            rows.append(finish(base(
                id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit=permit,
                checked=CHECKED_ON.get(permit, CHECKED),
                channel_kind="operator_page", urls=[], method=None, legal_basis=Q_CSO.format(permit=permit),
                basis_kind="permit", monitored=False, unmonitored_reason="none_found", publishes="none",
                records=False, noun="CSO public notification", sources=["ia-epa-cso-inventory"],
                note=(f"No web channel found: {name}'s public notification of combined sewer overflows under its "
                      "permit; no web notice was found (search only) and the permit was not read. Its bypass reports "
                      "to DNR are read from FOCOMP." + DMWRA_SITE.get(permit, "")))))
        if "IA0042650" in (op.get("npdes_permits") or []):
            rows.append(finish(base(
                id=f"{oid}-sso-bypass-page", operator_id=oid, name=name, permit="IA0042650",
                channel_kind="operator_page", urls=[WATERLOO_URL], method="html", legal_basis=LAW, basis_kind="law",
                monitored=False, unmonitored_reason="feed_ingested", feed_source_id="ia-waterloo-sso-notices",
                publishes="notices", noun="SSO and bypass notices", sources=["ia-waterloo-sso-notices"],
                note=("The City's SSO & Bypass Public Notification page lists each overflow and bypass with its time, "
                      "place, gallons and duration (17 on 2026-11-14); the City says IADNR and EPA require it to "
                      "notify the public. Read by the feed."))))
    return rows


# the Authority's own site answers GitHub's runner (200, 2026-11-16; it timed out only from the audit machine, which is
# no barrier of the source): its 2025 notice on eliminating combined sewer overflows is not read yet, so its three open
# outfalls keep the caution (owner question 1, IA final audit 2026-11-16)
DMWRA_SITE = {"IA0044130": (" The Authority's site (www.dmmwra.org) answers GitHub's runner (200, 2026-11-16); its notice "
                            "on eliminating its combined sewer overflows has not been read yet.")}
CHECKED_ON = {"IA0044130": "2026-11-15"}        # the row's note was checked again (IA final audit 2026-11-16, edit 5)


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "IA")
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
