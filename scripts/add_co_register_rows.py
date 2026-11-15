"""Colorado rows of the notice register (data/notice-channels/co.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_co_register_rows.py [--dry-run]

The law (research/co/report.md section 2.1 in the site repository; research/co/expansion-research.md):
  - C.R.S. 25-8-601(2): whoever's activity results in a spill or discharge that may pollute state waters notifies the
    Water Quality Control Division as soon as they know of it. The CDPS permits' standard conditions (South Platte
    Renew's CO0032999, Part II, read 2026-11-03): an oral report within 24 hours of noncompliance that may endanger
    health or the environment, a written report within five days, to the Division only. CDPHE's reporting sheet asks for
    "All sanitary sewer releases". No duty to tell the public was found; the Division publishes no list.
  - EPA Region 8 issues the permits on tribal land and for federal facilities in Colorado: their reports go to EPA.
Rows
  - Per operator (every Colorado row of data/dischargers.json): <id>-division-report (the report to the Division, not
    published: no web page), or <id>-epa-report when all its permits are EPA's.
  - The City of Pueblo: its news page (the August 2026 spill notice), which did not answer on 2026-11-14.
  - Statewide: the Division's reports (no web page), CDPHE's incident-reporting page, toxic-algae page, swim-beach page
    (all three 403 to the build's client on 2026-11-14), the toxic-algae sheet (read: co-cdphe-toxic-algae), CPW's news
    and Barr Lake's page and NPS's Curecanti release (read: co-official-notices), Douglas County's guidance page, EPA's
    overflow tables (no Colorado report), Swim Guide.
A rerun replaces every co- row it makes. Validated before writing.
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
ST = "CO"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
Q_LAW = ("C.R.S. 25-8-601(2): \"Any person engaged in any operation or activity which results in a spill or discharge of "
         "oil or other substance which may cause pollution of the waters of the state ... as soon as the person has "
         "knowledge thereof, shall notify the division of such discharge\"; CDPS permit standard conditions (CO0032999, "
         "Part II): \"The permittee shall report the following circumstances orally within twenty-four (24) hours\" "
         "(noncompliance that may endanger health or the environment), in writing within five days, to the Division")
Q_EPA = ("NPDES permit {permit} (EPA Region 8: tribal land or a federal facility in Colorado): the 24-hour and five-day "
         "noncompliance reports of 40 CFR 122.41(l)(6), to EPA")
UNREACHED_403 = " On 2026-11-14 the host answered 403 to the build's client; the row is watched so the refresh records when it answers."
PUEBLO = "co-co0026646"

AGENCY = [
    {"id": "co-official-notices", "agency": "Colorado Parks and Wildlife and the National Park Service",
     "name": "Colorado Parks and Wildlife and the National Park Service (selected official notices)",
     "channel_kind": "feed",
     "urls": ["https://cpw.state.co.us/news/08302026/water-contact-advisory-john-martin-pueblo-sewage-spill-moves-downstream",
              "https://www.nps.gov/cure/learn/news/toxic-algae-detected-in-blue-mesa-reservoir.htm",
              "https://cpw.state.co.us/state-parks/barr-lake-state-park/barr-lake-state-park-activities-trails"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "co-official-notices", "publishes": "notices",
     "noun": "Data feed",
     "note": ("Three official notices read as a reviewed set: CPW's water-contact advisory of August 30, 2026 for John "
              "Martin Reservoir after the Pueblo spill (about 4.2 million gallons of untreated sewage to the Arkansas "
              "River on August 26-27), NPS's Blue Mesa Reservoir toxic algae release of August 13, 2026 and Barr Lake "
              "State Park's red algae alert line (standing since August 3, 2026). Each page is re-read every run."),
     "sources": ["co-cdphe-press-releases", "co-official-notices"]},
    {"id": "co-cdphe-toxic-algae-sheet", "agency": "Colorado Department of Public Health and Environment",
     "name": "Colorado Department of Public Health and Environment (toxic algae status sheet)", "channel_kind": "feed",
     "urls": ["https://docs.google.com/spreadsheets/d/1rnsdGU5IrrCt3jfYQGa3obDd7SN27R1mitLhilBvYSQ/export?format=csv"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "co-cdphe-toxic-algae", "publishes": "status",
     "noun": "Data feed",
     "note": ("The public sheet of algal bloom conditions for selected waters (Caution, Warning, Third party, No bloom "
              "reported), a row added per change: 198 rows on 2026-11-14 for 129 waters, the last update dated "
              "2026-09-09. Read by the co-cdphe-toxic-algae feed."),
     "sources": ["co-cdphe-toxic-algae-sheet"]},
    {"id": "co-cdphe-toxic-algae-page", "agency": "Colorado Department of Public Health and Environment",
     "name": "Colorado Department of Public Health and Environment (toxic algae page)",
     "channel_kind": "state_alert_page", "urls": ["https://cdphe.colorado.gov/toxic-algae"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "the toxic algae status sheet", "records": False,
     "availability_only": True, "every_hours": 168,
     "note": "CDPHE's toxic algae page, which links the status sheet (research, 2026-11-03)." + UNREACHED_403,
     "sources": ["co-cdphe-toxic-algae-sheet"]},
    {"id": "co-cdphe-swim-beaches", "agency": "Colorado Department of Public Health and Environment",
     "name": "Colorado Department of Public Health and Environment (swim beach monitoring)",
     "channel_kind": "state_alert_page", "urls": ["https://cdphe.colorado.gov/swim-beach-monitoring"], "method": "html",
     "legal_basis": "5 CCR 1003-5 (swimming areas): operators of designated swim beaches sample for E. coli",
     "basis_kind": "law", "monitored": True, "unmonitored_reason": None, "publishes": "status", "records": False,
     "availability_only": True, "every_hours": 24,
     "note": ("CDPHE's swim beach page lists closures in HTML (\"None at this time\" on 2026-11-03, research); not "
              "ingested: no closure has been seen to test a reader on." + UNREACHED_403),
     "sources": ["co-cdphe-swim-beaches"]},
    {"id": "co-cdphe-incident-reporting", "agency": "Colorado Department of Public Health and Environment",
     "name": "Colorado Department of Public Health and Environment (incident reporting)",
     "channel_kind": "state_alert_page", "urls": ["https://cdphe.colorado.gov/report-a-public-health-or-environmental-concern"],
     "method": "html", "legal_basis": Q_LAW, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168,
     "noun": "Notification page",
     "note": ("Intake only: a hotline and an online form for spills and releases; no public list of reports."
              + UNREACHED_403),
     "sources": ["co-cdphe-incident-reporting"]},
    {"id": "co-wqcd-spill-reports", "agency": "Colorado Department of Public Health and Environment",
     "name": "Colorado Water Quality Control Division (spill and noncompliance reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_LAW, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("No web channel found: every sanitary sewer release is reported to the Division (C.R.S. 25-8-601(2); the CDPS "
              "permits' 24-hour oral and five-day written reports), and the Division publishes none of them. A "
              "redacted export (incident id, operator and permit, start, end, volume, water reached) is a records "
              "request to CDPHE; none has been sent."),
     "sources": ["co-law-crs-25-8-601", "co-permit-co0032999"]},
    {"id": "co-douglas-county-hazards", "agency": "Douglas County Health Department",
     "name": "Douglas County Health Department (sewage and chemical spills guidance)",
     "channel_kind": "local_health_page", "urls": ["https://www.douglasco.gov/health-department/hazards/"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168,
     "noun": "Voluntary page",
     "note": ("Reporting guidance: sanitary sewer releases go to CDPHE, accidental sewer discharges to the local sewer "
              "authority; no list of incidents (expansion research, 2026-11-09)."),
     "sources": ["co-douglas-county-spills"]},
    {"id": "co-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168, "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables hold no Colorado report and no Colorado collection system: none in "
              "the current extract of 2026-11-14 (5,751 events) nor in the all-versions extract (6,710 events). Watched "
              "for Colorado rows."),
     "sources": ["co-epa-sobe"]},
    {"id": "co-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish (Swim Guide)",
     "channel_kind": "swim_guide", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "No Colorado affiliate found (research, search only).", "sources": ["co-swim-guide"]},
    {"id": "co-pueblo-news", "operator_id": PUEBLO, "name": "City of Pueblo", "permit": "CO0026646",
     "channel_kind": "operator_page", "urls": ["https://www.pueblo.us/m/newsflash/home/detail/5002"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24,
     "note": ("The city's news item of September 14, 2026 on the August spill to the Arkansas River (research); its news "
              "category and alert center are the same site. On 2026-11-14 the host did not answer the build's client "
              "(connection timed out); the row is watched so the refresh records when it answers. Not ingested: its "
              "text has not been read in this build."),
     "sources": ["co-pueblo-wastewater-notices"]},
]


def base(**kw) -> dict:
    r = {"state": ST, "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != ST or "co" not in (op.get("source_areas") or []):
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        epa = op.get("epa_issued_permits") or []
        if epa and len(epa) == len(ps):
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=epa[0], channel_kind="state_alert_page",
                urls=[], method=None, legal_basis=Q_EPA.format(permit=epa[0]), basis_kind="permit", monitored=False,
                unmonitored_reason="other", publishes="none", records=False, noun="EPA report",
                sources=["co-epa-sobe"],
                note=(f"No web channel found: {name}'s permit is EPA's (tribal land or a federal facility in Colorado), "
                      "so its noncompliance reports go to EPA Region 8, which publishes those filed electronically in "
                      "its overflow tables (none for Colorado in the extracts of 2026-11-14)."))))
            continue
        private = (" The statute and the permit bind a private permittee as they bind a public one."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility", "tribal") else "")
        rows.append(finish(base(
            id=f"{oid}-division-report", operator_id=oid, name=name, permit=None, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=Q_LAW, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=["co-law-crs-25-8-601"],
            note=(f"No web channel found: {name} reports a spill or noncompliance to the Water Quality Control Division "
                  "(C.R.S. 25-8-601(2); the CDPS permit's 24-hour and five-day reports), which publishes no list "
                  f"(co-wqcd-spill-reports); no duty to tell the public was found.{private} Its own web channel was not "
                  "searched individually."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == ST)
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
