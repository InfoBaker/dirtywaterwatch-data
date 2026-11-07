"""South Dakota rows of the notice register (data/notice-channels/sd.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_sd_register_rows.py [--dry-run]

The law (research/sd/report.md §2.1 in the site repository; profile research/sd/profile.json):
  - No South Dakota statute, rule or permit clause found requires notice to the public of a sewage overflow or bypass.
    The general spill rule (ARSD 74:34:01:05, SDCL 34A-12: "Suspected Discharges must be reported to DANR within 24
    Hours") covers regulated substances; its page does not name sewage.
  - The permit's standard conditions (40 CFR 122.41(l)(6), as adopted in South Dakota surface water discharge permits;
    the permit text was not read) require a report to the permitting authority within 24 hours and a written report
    within 5 days. Since the eRule (40 CFR part 127) the written report is filed through EPA's NeT-SewerOverflow and
    EPA publishes it in its daily overflow tables: that is the only public trace of an overflow in South Dakota. DANR
    is the authority for the state's permits; EPA Region 8 for the permits it writes in Indian country (the operator
    rows say which).
  - The two CSO permits (Lead, Lead-Deadwood Sanitary District) carry public notification under the permit (Nine
    Minimum Controls no. 8); permit texts not read; no web notice found for either.

Rows
  - Per operator (every South Dakota row of data/dischargers.json): <id>-overflow-report (permit basis): the report to
    DANR (or EPA), made public through EPA's overflow tables and read by the echo-sewer-overflow feed.
  - Per CSO operator: <id>-cso-public-notification (permit basis), none found.
  - Per research operator that is not a CSO permittee (the twelve largest reporters): <id>-own-overflow-page
    (voluntary), none found by the research's search.
  - Agency and voluntary rows: AGENCY below (EPA's tables, DANR, DANR's HAB advisories, Game, Fish and Parks,
    the beach bacteria gap, Friends of the Big Sioux River).
A rerun replaces every sd- row it makes. Validated before writing.
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
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
HAB_PAGE = "https://danr.sd.gov/Conservation/WatershedProtection/HAB.aspx"
SPILLS = "https://danr.sd.gov/Agriculture/Inspection/Spills/default.aspx"
Q_PERMIT = ("NPDES (surface water discharge) permit {permit}: standard conditions, a report of noncompliance that may "
            "endanger health or the environment to the permitting authority within 24 hours and a written report within "
            "5 days (40 CFR 122.41(l)(6), as adopted in the permit; permit text not read), filed electronically through "
            "EPA's NeT-SewerOverflow (40 CFR part 127)")
Q_CSO = ("NPDES permit {permit}: CSO public notification, one of the nine minimum controls of the federal CSO Control "
         "Policy (59 FR 18688, 1994); permit text not read")
AGENCY = [
    {"id": "sd-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "echo-sewer-overflow", "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): South Dakota permittees file "
              "their 5-day written reports through NeT-SewerOverflow and EPA publishes them daily (208 South Dakota "
              "reports from 56 permits, April 2023 to 2026-11-02, in the 2026-11-04 extract; a median 5 days from start "
              "to receipt). The only public record of overflows in the state, public or private operators alike. "
              "(research/sd/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "sd-epa-sobe"]},
    {"id": "sd-danr-overflow-report", "agency": "South Dakota Department of Agriculture and Natural Resources",
     "name": "South Dakota DANR", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": ("Surface water discharge permit standard conditions: 24-hour report and 5-day written report to "
                     "DANR (40 CFR 122.41(l)(6), as adopted; permit text not read)"),
     "basis_kind": "permit", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False, "noun": "Report to the state",
     "note": ("No web channel found: every permittee, public or private, reports an overflow or bypass to DANR within 24 "
              "hours and in writing within 5 days; no South Dakota statute or rule requires the public to be told, and "
              "DANR posts no list of the reports. The written reports reach the public only through EPA's tables, days "
              "to weeks later. The fix is legislative (a public-notice duty) or an agency posting. "
              "(research/sd/report.md §2.1, §2.6)"),
     "sources": ["sd-danr-ereporting"]},
    {"id": "sd-danr-spill-reporting", "agency": "South Dakota Department of Agriculture and Natural Resources",
     "name": "South Dakota DANR (spill reporting)", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": ("ARSD 74:34:01:05; SDCL 34A-12: \"Suspected Discharges must be reported to DANR within 24 Hours\" "
                     "(regulated substances)"),
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Spill reports",
     "note": ("No web channel found for sewage: the spill rule's page (" + SPILLS + ") covers gasoline, pesticides and "
              "solvents and does not name sewage; DANR's spill map (NR42) lists petroleum and chemical remediation "
              "cases, and its map service reset the research's connections. Municipal overflows go the permit route. "
              "(research/sd/report.md §2.1, sd-danr-spills-nr42)"),
     "sources": ["sd-danr-spills-nr42"]},
    {"id": "sd-danr-hab-advisories", "agency": "South Dakota Department of Agriculture and Natural Resources",
     "name": "South Dakota DANR (harmful algal bloom advisories)", "channel_kind": "state_alert_page",
     "urls": [HAB_PAGE], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "sd-danr-hab-advisories", "publishes": "notices",
     "noun": "Bloom advisories",
     "note": ("DANR's HAB page lists the year's harmful algal bloom advisories, lake, county and date (five in 2026 on "
              "2026-11-07); \"Advisories expire at the end of the calendar year\". Read by the feed. Blooms, not "
              "sewage. No statute requiring them was found: filed voluntary. (research/sd/report.md §2.5)"),
     "sources": ["sd-danr-hab-advisories"]},
    {"id": "sd-gfp-harmful-algae", "agency": "South Dakota Game, Fish and Parks",
     "name": "South Dakota Game, Fish and Parks", "channel_kind": "state_alert_page",
     "urls": ["https://gfp.sd.gov/harmful-algae/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "link_only", "link_text": "DANR's HAB page",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Game, Fish and Parks' harmful algae page: advice (\"When in doubt, stay out!\") and a pointer to DANR, which "
              "it names as the agency that monitors blooms. Answered 200 to the project user agent on 2026-11-07. "
              "Voluntary. (sd-gfp-harmful-algae)"),
     "sources": ["sd-gfp-harmful-algae"]},
    {"id": "sd-beach-bacteria-advisories", "agency": "South Dakota Department of Agriculture and Natural Resources",
     "name": "South Dakota (beach bacteria advisories)", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "none", "records": False,
     "note": ("No web channel found: the research found no South Dakota program that samples swimming beaches for "
              "bacteria and posts advisories (state parks included; search only). (research/sd/report.md §2.5, "
              "sd-beach-ecoli)"),
     "sources": ["sd-beach-ecoli"]},
    {"id": "sd-friends-of-the-big-sioux-river", "agency": "Friends of the Big Sioux River",
     "name": "Friends of the Big Sioux River", "channel_kind": "group_results",
     "urls": ["https://www.friendsofthebigsiouxriver.org/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "unknown",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Watershed group for the Big Sioux River, the receiving water of Sioux Falls, Brookings and Watertown; its "
              "summer bacteria and flood-impact reports (the 2024 report covered the Sioux Falls and Vermillion "
              "releases) are documents, not read. Home page answered 200 on 2026-11-07. Voluntary. "
              "(sd-friends-big-sioux)"),
     "sources": ["sd-friends-big-sioux"]},
]
# what each CSO permit has filed in EPA's tables (2026-11-04 extract), per permit (review 2026-11-07 P3-1)
CSO_FILED = {"SD0027481": "three reports in 2026, to Gold Run Creek"}
OWN_PAGE_NOTES = {
    "sd-sioux-falls": (" Sioux Falls announced its June 2024 flood releases (partially treated, then untreated, to the "
                       "Big Sioux River) at a press conference; no standing overflow page was found."),
    "sd-rapid-city": " The city's site answered 403 to the project user agent on 2026-11-07.",
}


def base(**kw) -> dict:
    r = {"state": "SD", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict], research_ids: set[str]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "SD":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        epa = "EPA Region 8" in (op.get("notification_channel") or "")
        to = ("EPA Region 8 (a permit in Indian country, as read from the permit series and EPA's facility type, not "
              "from the permit text)") if epa else "DANR"
        private = " The permit binds the holder, public or private." if op.get("legal_form") in (
            "investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
            "campground or resort", "private club", "business or industrial", "institution",
            "facility (permittee not named)") else ""
        rows.append(finish(base(
            id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed",
            urls=[], method=None, legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id="echo-sewer-overflow", publishes="notices",
            noun="Report to the permitting authority", sources=["sd-epa-sobe", "sd-danr-ereporting"],
            note=(f"{name} reports each overflow and bypass to {to} within 24 hours and in writing within 5 days; the "
                  "written report, filed through NeT-SewerOverflow, is published in EPA's overflow tables, read by the "
                  f"echo-sewer-overflow feed. No public-notice requirement was found.{private} (research/sd/report.md §2.1)"))))
        if op.get("kind") == "cso":
            rows.append(finish(base(
                id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit=permit,
                channel_kind="operator_page", urls=[], method=None, legal_basis=Q_CSO.format(permit=permit),
                basis_kind="permit", monitored=False, unmonitored_reason="none_found", publishes="none",
                records=False, noun="CSO public notification", sources=["sd-echo-dmr-cso"],
                note=(f"No web channel found: {name}'s public notification of combined sewer overflows under its permit; "
                      "the research found no web notice and did not read the permit. Its overflows reach EPA's tables "
                      f"when it files them there: {CSO_FILED.get(permit, 'no report of this permit in the 2026-11-04 extract')}. "
                      "(research/sd/report.md §2.1, §2.4)"))))
        elif oid in research_ids:
            rows.append(finish(base(
                id=f"{oid}-own-overflow-page", operator_id=oid, name=name, permit=permit, channel_kind="operator_page",
                urls=[], method=None, legal_basis=None, basis_kind="voluntary", monitored=False,
                unmonitored_reason="none_found", publishes="none", records=False, noun="Voluntary page",
                sources=["sd-epa-sobe"],
                note=(f"No own page found: the research searched for an overflow notice page of {name} and found none "
                      "(search only)." + OWN_PAGE_NOTES.get(oid, "") + " (research/sd/report.md §2.3)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    research_ids = {r["id"] for r in json.loads((ROOT / "research" / "sd" / "dischargers.json").read_text())}
    rows = operator_rows(dis, research_ids) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "SD")
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
