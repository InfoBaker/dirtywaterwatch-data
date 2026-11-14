"""West Virginia rows of the notice register (data/notice-channels/wv.json), made from the law and data/dischargers.json.

Usage: pipeline/.venv/bin/python -I scripts/add_wv_register_rows.py [--dry-run]

The law (research/wv/report.md §2.1 in the site repository; research/wv/expansion-research.md):
  - The Water Resources rules require whoever causes a spill or accidental discharge of pollutants, sewage included, to
    notify DEP's emergency spill line immediately (1-800-642-3074). The official register lists the active rule as
    47CSR11 (Special Rules, effective 1987); its scanned text could not be read, so the clause is cited from DEP's
    spill-reporting page and the research's earlier reading, not quoted. A report to the agency only, by telephone;
    DEP publishes no list. HB 3217 (2025), which would have required public notice within 24 hours and an online spill
    database, is pending in committee.
  - Combined sewer permittees: public notification is one of the nine minimum controls of EPA's CSO Control Policy; the
    practice seen is an annual newspaper legal notice and a sign at each outlet. No permit clause was read.
Rows
  - Per operator (every West Virginia row of data/dischargers.json): <id>-dep-spill-line, the telephone report to DEP.
  - Per combined sewer permittee: <id>-cso-public-notice, the annual legal notice and outlet signs (print only).
  - Agencies: the spill line, DEP's algal bloom map (feed), EPA's monthly DMRs (feed), DEP's HAB page (watched),
    the outlet layer, DEP's document system and public permit query, EPA's eRule tables (no West Virginia report),
    ORSANCO's bacteria pages (bot wall), the newspaper legal notices, Clarksburg's alerts.
  - Operators' own pages: Charleston Sanitary Board, Morgantown Utility Board, Wheeling (watched daily, no records).
A rerun replaces every wv- row it makes. Validated before writing.
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
SPILL_PAGE = "https://dep.wv.gov/WWE/i-e/Pages/default.aspx"
HAB_PAGE = "https://dep.wv.gov/WWE/watershed/Algae/Pages/Harmful-Algal-Blooms.aspx"
LAW_TEXT = ("West Virginia Water Resources rules (47CSR11, Special Rules; earlier cited as 46CSR3): whoever causes a "
            "spill or accidental discharge of pollutants, sewage included, notifies DEP's emergency spill line "
            "(1-800-642-3074) immediately; the permit's standard conditions add the reports of 40 CFR 122.41(l)(6)")
CSO_BASIS = ("WV/NPDES combined sewer permit: public notification is one of the nine minimum controls of EPA's Combined "
             "Sewer Overflow Control Policy (59 FR 18688, 1994), which the permit is expected to carry; the permit's own "
             "clause was not read")
AGENCY = [
    {"id": "wv-dep-spill-line", "agency": "West Virginia Department of Environmental Protection",
     "name": "West Virginia DEP (emergency spill line)", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": LAW_TEXT, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("Spills and accidental discharges are reported to DEP by telephone only, on the emergency spill line; DEP "
              f"publishes no list of them and they reach the public only by a records request ({SPILL_PAGE}). HB 3217 "
              "(2025) would have required public notice within 24 hours and an online database; it is pending in "
              "committee."),
     "sources": ["wv-law-spill-rule", "wv-dep-spill-intake", "wv-hb3217-2025"]},
    {"id": "wv-dep-hab-advisories", "agency": "West Virginia Department of Environmental Protection",
     "name": "West Virginia DEP (algal bloom advisory map)", "channel_kind": "feed",
     "urls": ["https://tagis.dep.wv.gov/arcgis/rest/services/webMercator/algae_advisories/MapServer"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "wv-dep-hab-advisories", "publishes": "status", "noun": "Data feed",
     "note": ("DEP's map of algal bloom advisories (points, stream segments and lake areas, with the advisory text and the "
              "day the bloom was observed): read by the wv-dep-hab-advisories feed; empty on 2026-11-14. Blooms, not "
              "sewage. Voluntary."),
     "sources": ["wv-dep-hab-advisories"]},
    {"id": "wv-dep-hab-program-page", "agency": "West Virginia Department of Environmental Protection",
     "name": "West Virginia DEP (Harmful Algal Blooms page)", "channel_kind": "state_alert_page", "urls": [HAB_PAGE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "status", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("DEP's program page: watch and warning levels, a statement of current advisories (none on 2026-11-14) and "
              "a table of reported blooms last updated in August 2023; watched daily for a change. Voluntary."),
     "sources": ["wv-dep-hab-program"]},
    {"id": "wv-echo-dmr-cso", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (discharge monitoring reports)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/trends/loading-tool/water-pollution-search"], "method": "json", "legal_basis":
     "WV/NPDES permits: monthly discharge monitoring reports (40 CFR 122.41(l)(4))", "basis_kind": "permit",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "wv-echo-dmr-cso",
     "publishes": "results", "noun": "Data feed",
     "note": ("The operators' monthly reports to DEP, published by EPA weeks after the month: of the 61 permits with an "
              "open combined sewer outlet, two report a line at an outlet (Princeton and Beckley, flow at outlet C002); "
              "none reports a number of overflows, hours or volume (2026-11-14)."),
     "sources": ["wv-echo-dmr-cso"]},
    {"id": "wv-dep-npdes-outlets", "agency": "West Virginia Department of Environmental Protection",
     "name": "West Virginia DEP (NPDES Outlets layer)", "channel_kind": "feed",
     "urls": ["https://tagis.dep.wv.gov/arcgis/rest/services/WVDEP_enterprise/water_resources/MapServer/24"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "wv-dep-npdes-outlets", "publishes": "documents",
     "records": False, "noun": "Data feed",
     "note": ("DEP's permitted outlets, read for the combined sewer outlets only (792 on 62 permits, 519 open on 2026-11-"
              "14): where each outlet is and the stream it reaches, not when it discharges."),
     "sources": ["wv-dep-npdes-outlets"]},
    {"id": "wv-dep-document-search", "agency": "West Virginia Department of Environmental Protection",
     "name": "West Virginia DEP (Application Enhancer document search)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "login",
     "publishes": "documents", "records": False,
     "note": ("DEP's Data Center describes a login for its document system (Application Enhancer), which holds permits, "
              "discharge reports and enforcement files one document at a time; only the application's shell answered "
              "on 2026-11-09."),
     "sources": ["wv-dep-applicationxtender", "wv-dep-application-enhancer"]},
    {"id": "wv-dep-ess-permit-query", "agency": "West Virginia Department of Environmental Protection",
     "name": "West Virginia DEP (public permit query)", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False,
     "note": ("The Electronic Submission System's public permit query (no account) holds permit versions, not overflow "
              "reports; it timed out on 2026-11-09. Not verified in the research as a route to discharge reports."),
     "sources": ["wv-dep-ess-public-query", "wv-dep-erule-ess"]},
    {"id": "wv-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (sewer overflow and bypass tables)", "channel_kind": "feed",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("EPA's sewer overflow and bypass event tables hold no West Virginia report (current and all-versions "
              "extracts of 2026-11-14): DEP's own electronic system sends none there. No web channel found."),
     "sources": ["wv-dep-erule-ess"]},
    {"id": "wv-orsanco-bacteria", "agency": "Ohio River Valley Water Sanitation Commission (ORSANCO)",
     "name": "ORSANCO (Ohio River bacteria results)", "channel_kind": "group_results",
     "urls": ["https://www.orsanco.org/data/bacteria/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "results",
     "note": ("Weekly E. coli results for the Ohio River at Wheeling and Huntington in season; the site answers 403 to "
              "plain clients (2026-11-09)."),
     "sources": ["wv-orsanco-bacteria"]},
    {"id": "wv-wvlegals-cso-notices", "agency": "West Virginia Legals (newspaper legal notices)",
     "name": "West Virginia Legals (combined sewer legal notices)", "channel_kind": "news_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False,
     "note": ("The combined sewer towns' annual notices appear as paid notices in newspapers, collected by "
              "wvlegals.com (Wheeling's 2015 notice: avoid contact for at least 24 hours after 0.10 inch of rain); "
              "printed only, once a year, with no dated overflow; the site did not answer on 2026-11-09."),
     "sources": ["wv-wvlegals-cso-notices"]},
    {"id": "wv-clarksburg-alerts", "agency": "City of Clarksburg", "name": "City of Clarksburg (public alerts)",
     "channel_kind": "email_list", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "email_only", "publishes": "unknown",
     "note": ("The city's text and e-mail alerts; whether they carry sewer overflow notices is not known (no archive)."),
     "sources": ["wv-clarksburg-text-alerts"]},
]
OWN = [
    {"id": "wv-charleston-cso-page", "operator_id": "wv-charleston-sanitary-board", "permit": "WV0023205",
     "name": "Charleston Sanitary Board", "channel_kind": "operator_page",
     "urls": ["https://csbwv.gov/index.php?Itemid=68&id=62&option=com_content&view=article"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "none",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Standing combined sewer notice (read 2026-11-14): outlets may discharge in rain or heavy snow runoff; \"You "
              "are advised to avoid contact with the water around these outlets during these overflow events for at "
              "least 24 hours thereafter.\" No dated overflows. Watched daily for a change."),
     "sources": ["wv-charleston-cso-notice"]},
    {"id": "wv-morgantown-cso-page", "operator_id": "wv-city-of-morgantown", "permit": "WV0023124",
     "name": "Morgantown Utility Board (City of Morgantown, permittee)", "channel_kind": "operator_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False,
     "note": ("Standing combined sewer notice read on 2026-11-09 (mub.org/cso): outlets on Deckers Creek, the Monongahela "
              "River, Popenoe Run and Burrough Run, avoid contact for 72 hours after rain, a January 2025 notice and a "
              "map; no dated overflows. Both of the Board's combined sewer page addresses answered 404 on 2026-11-14 "
              "(moved): the new address is not verified in the research."),
     "sources": ["wv-mub-cso-current", "wv-mub-cso-public-notice-2025"]},
    {"id": "wv-wheeling-water-pollution-page", "operator_id": "wv-city-of-wheeling", "permit": "WV0023230",
     "name": "City of Wheeling", "channel_kind": "operator_page",
     "urls": ["https://www.wheelingwv.gov/departments/PublicWorks/water-pollution"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "none",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": "The Water Pollution Control Division's page: the system and a route to report problems; no dated overflows.",
     "sources": ["wv-wheeling-water-pollution"]},
]


def base(**kw) -> dict:
    r = {"state": "WV", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "WV":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        rows.append(finish(base(
            id=f"{oid}-dep-spill-line", operator_id=oid, name=name, permit=ps[0] if ps else None,
            channel_kind="state_alert_page", urls=[], method=None, legal_basis=LAW_TEXT, basis_kind="law",
            monitored=False, unmonitored_reason="other", publishes="none", records=False, noun="Report to the state",
            sources=["wv-law-spill-rule"],
            note=(f"{name} must report a spill or accidental discharge to DEP's emergency spill line, by telephone only; "
                  "DEP publishes no list and no public notice is required. The permit itself was not read."))))
        if op.get("kind") == "cso":
            permit = next((p for p in ps if p), None)
            rows.append(finish(base(
                id=f"{oid}-cso-public-notice", operator_id=oid, name=name, permit=permit,
                channel_kind="operator_page", urls=[], method=None, legal_basis=CSO_BASIS, basis_kind="permit",
                monitored=False, unmonitored_reason="other", publishes="documents", records=False,
                sources=["wv-wvlegals-cso-notices", "wv-dep-npdes-outlets"],
                note=(f"{name}'s combined sewer public notice as seen in the state: a paid notice in a newspaper once a "
                      "year and a sign at each outlet, with no dated overflow; printed only. The permit's clause was "
                      "not verified in the research."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "WV")
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
