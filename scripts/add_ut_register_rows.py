"""Utah rows of the notice register (data/notice-channels/ut.json), made from the law and data/dischargers.json so they
are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ut_register_rows.py [--dry-run]

The law (research/ut/report.md section 2.1 in the site repository; research/ut/profile.json):
  - Utah Admin. Code R317-801-4 (read on law.cornell.edu, 2026-11-03): "A Class 1 SSO shall be reported orally within 24
    hrs and with a written report submitted to the DWQ within five calendar days"; Class 2 overflows only in the annual
    sewer management report. R317-801-1(13): a Class 1 overflow is one that reaches waters of the state, exceeds 5,000
    gallons, affects more than five private structures or a public, commercial or industrial one, or may be a risk to
    public health. A report to the agency only: DWQ publishes no list.
  - No duty to tell the public was found; no CSO permits. Local health departments post recreational advisories with
    DWQ (blooms and E. coli).
  - On tribal land EPA Region 8 issues the permits: the federal 24-hour and five-day reports go to EPA, which publishes
    those filed electronically in its overflow tables.
Rows
  - Per operator (every Utah row of data/dischargers.json): <id>-dwq-report, the R317-801-4 report to DWQ (law; by
    telephone and letter; not published), or <id>-epa-report for a tribal permit (read through EPA's tables, the
    echo-sewer-overflow feed); an operator with a report in EPA's tables also gets its <id>-epa-report row.
  - Statewide: DEQ's spill hotline log (the ut-deq-environmental-incidents feed), DWQ's unpublished Class 1 reports, EPA's
    tables, DWQ's recreational advisory layer (the ut-dwq-recreational-advisories feed) and its page (habs.utah.gov now
    redirects there), the old spill search site (expired certificate), Zion National Park's cyanobacteria page, the local
    health departments, Salt Lake County's Jordan River algae app, Utah Water Watch and Swim Guide.
A rerun replaces every ut- row it makes. Validated before writing.
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
INCIDENTS = "ut-deq-environmental-incidents"
REC = "ut-dwq-recreational-advisories"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
RULE_URL = "https://www.law.cornell.edu/regulations/utah/Utah-Admin-Code-R317-801-4"
REC_PAGE = "https://deq.utah.gov/dwq/recreational-water-quality"
LAW = "ut-law-r317-801"
Q_RULE = ('Utah Admin. Code R317-801-4: "A Class 1 SSO shall be reported orally within 24 hrs and with a written report '
          'submitted to the DWQ within five calendar days"; R317-801-1(13) defines a Class 1 overflow (one that reaches '
          'waters of the state, exceeds 5,000 gallons, affects more than five private structures or a public, '
          'commercial or industrial one, or may be a public health risk)')
Q_TRIBAL = ("NPDES permit {permit} (EPA Region 8, tribal land): the 24-hour and five-day noncompliance reports of 40 CFR "
            "122.41(l)(6), to EPA")
Q_EPA = ("NPDES permit {permit}: the permittee's electronic sewer overflow reports to EPA (40 CFR 122.41(l)(6) and "
         "Part 127)")
TRIBAL_PREFIX = ("NN", "COG", "UTG5894")
CONTRACTORS = {"ut-alder-construction", "ut-fx-construction", "ut-whitaker-construction"}
Q_DEWATER = ("UPDES general permit coverage {permit} (construction dewatering): the permit's noncompliance reports to "
             "DWQ")

AGENCY = [
    {"id": "ut-deq-environmental-incidents", "agency": "Utah Department of Environmental Quality",
     "name": "Utah Department of Environmental Quality (Environmental Incidents)", "channel_kind": "feed",
     "urls": ["https://services2.arcgis.com/NnxP4LZ3zX8wWmP9/arcgis/rest/services/EnvironmentalIncidents/FeatureServer/0"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": INCIDENTS, "publishes": "notices", "noun": "Data feed",
     "note": ("The Division of Environmental Response and Remediation's public layer of incidents phoned in to DEQ's "
              "spill hotline since 1991, edited daily, with a point and a PDF report for each: 8,980 rows on "
              "2026-11-08, 387 of them sewage reports by their titles (20 to 38 a year since 2017). It holds the "
              "overflows someone called in, not the Class 1 reports operators send DWQ. (research/ut/report.md §2.2)"),
     "sources": [INCIDENTS]},
    {"id": "ut-dwq-class-1-sso-reports", "agency": "Utah Division of Water Quality",
     "name": "Utah Division of Water Quality (Class 1 sewer overflow reports under R317-801-4)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_RULE, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("Every sewer system under the Utah Sewer Management Program reports a Class 1 overflow to DWQ by telephone "
              "within 24 hours and in writing within five days, and Class 2 overflows in its annual report (April 15). "
              "DWQ publishes no list of these reports and no web channel found carries them; they reach the public only "
              f"through a records request. ({RULE_URL}; research/ut/report.md §2.1)"),
     "sources": [LAW]},
    {"id": "ut-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): EPA's collection-system table "
              "lists 188 Utah permits, but the 2026-11-04 extract holds one Utah report, the Timpanogos Special Service "
              "District's bypass line struck by a vehicle at American Fork (2026-08-17, 1,000 gallons, received "
              "2026-08-25). (research/ut/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "ut-epa-sobe"]},
    {"id": "ut-dwq-recreational-advisories", "agency": "Utah Division of Water Quality",
     "name": "Utah Division of Water Quality (Recreational Waters Map)", "channel_kind": "feed",
     "urls": [REC_PAGE], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": REC, "publishes": "status", "noun": "Data feed",
     "note": ("The map layer of the recreational sites DWQ and local health departments sample, each with its current "
              "advisory: 167 sites on 2026-11-07, 64 under an algal bloom or algae mat advisory, 8 where DWQ's team "
              "observed a few algae mats (\"Mats CF\", not an advisory level) and 12 under an E. coli advisory. "
              "\"Looks Good\" means no current advisory. Blooms and bacteria, not sewage. (research/ut/report.md §2.5)"),
     "sources": [REC]},
    {"id": "ut-dwq-recreational-page", "agency": "Utah Division of Water Quality",
     "name": "Utah Division of Water Quality (recreational water quality page)", "channel_kind": "state_alert_page",
     "urls": [REC_PAGE], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True,
     "unmonitored_reason": None, "publishes": "link_only", "link_text": "DWQ's Recreational Waters Map",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("DWQ's recreational water page explains the bloom and E. coli advisories and links the map; watched for a "
              "new map address. Its old address and habs.utah.gov, which answered 403 to scripts on 2026-11-03, both "
              "redirect here (2026-11-08). Voluntary."),
     "sources": [REC]},
    {"id": "ut-deq-spill-search", "agency": "Utah Department of Environmental Quality",
     "name": "Utah Department of Environmental Quality (Environmental Incidents search site)",
     "channel_kind": "state_alert_page", "urls": ["https://eqspillsps.deq.utah.gov/Search_Public.aspx"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("DEQ's older search page for the incident log failed with an expired certificate and then answered 503 "
              "(2026-11-03); its user guide caps a search at 500 results. Watched for its return; the layer above "
              "carries the same log."),
     "sources": ["ut-deq-environmental-incidents-search"]},
    {"id": "ut-nps-zion-cyanobacteria", "agency": "National Park Service, Zion National Park",
     "name": "Zion National Park (toxic cyanobacteria page)", "channel_kind": "shared_site",
     "urls": ["https://www.nps.gov/zion/planyourvisit/toxic-cyanobacteria-bloom-in-the-virgin-river-and-the-streams-"
              "of-zion-national-park.htm"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "status", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The park's standing advisory on toxic cyanobacteria in the Virgin River and its forks, which DWQ's map "
              "carries as a permanent advisory. Blooms, not sewage. Voluntary."),
     "sources": ["ut-nps-zion-cyanobacteria"]},
    {"id": "ut-local-health-departments", "agency": "Utah local health departments",
     "name": "Utah local health departments (water advisories)", "channel_kind": "local_health_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False,
     "note": ("Utah's thirteen local health departments issue the recreational advisories DWQ's map shows and may close "
              "a water; how each announces them varies by town and county (pages not surveyed one by one). "
              "(research/ut/report.md §2.5)"),
     "sources": [REC]},
    {"id": "ut-slco-jordan-river-algae", "agency": "Salt Lake County",
     "name": "Salt Lake County (Jordan River watershed algae blooms app)", "channel_kind": "shared_site", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False,
     "note": "Found in an ArcGIS search; channel not researched (its address and content were not read).",
     "sources": ["ut-slco-jordan-river-algae"]},
    {"id": "ut-usu-water-watch", "agency": "Utah State University Extension (Utah Water Watch)",
     "name": "Utah Water Watch (Utah State University Extension)", "channel_kind": "group_results", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False,
     "note": "DWQ's volunteer monitoring partner; channel not researched (not fetched).",
     "sources": ["ut-usu-water-watch"]},
    {"id": "ut-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "No Swim Guide affiliate or Utah listing was found (search only, 2026-11-03). (research/ut/report.md §2.5)",
     "sources": ["ut-swim-guide"]},
]


def base(**kw) -> dict:
    r = {"state": "UT", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def report_counts() -> Counter:
    n: Counter = Counter()
    f = ROOT / "data" / "build" / "events" / f"{FEED}.json"
    if f.exists():
        for r in json.loads(f.read_text()).get("records", []):
            if str(r.get("npdes_permit") or "").startswith("UT"):
                n[r["npdes_permit"]] += 1
    return n


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    reports = report_counts()
    for op in dis:
        if op.get("state") != "UT":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        permit = ps[0] if ps else None
        tribal = op.get("legal_form") == "tribal" or any(p.startswith(TRIBAL_PREFIX) for p in ps)
        if tribal:
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
                method=None, legal_basis=Q_TRIBAL.format(permit=permit), basis_kind="permit", monitored=False,
                unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices", noun="EPA report",
                sources=["ut-epa-sobe"],
                note=(f"{name}'s permits are EPA's on tribal land: reports go to EPA Region 8, which publishes those "
                      f"filed electronically in its overflow tables, read by the {FEED} feed (no report under its "
                      "permits in the 2026-11-04 extract). Utah's rule does not apply on tribal land. "
                      "(research/ut/report.md §3)"))))
            continue
        if op["id"] in CONTRACTORS:
            rows.append(finish(base(
                id=f"{oid}-dwq-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
                urls=[], method=None, legal_basis=Q_DEWATER.format(permit=permit), basis_kind="permit",
                monitored=False, unmonitored_reason="other", publishes="none", records=False,
                noun="Report to the state", sources=[LAW],
                note=(f"No web channel found: {name} holds a construction dewatering coverage at a sewer project; "
                      "R317-801's overflow duty rests on the sewer system's owner, whose row carries it. The "
                      "coverage's own noncompliance reports go to DWQ and are not published. (research/ut/report.md §3)"))))
            continue
        private = (" The rule binds the system's owner, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility") else "")
        rows.append(finish(base(
            id=f"{oid}-dwq-report", operator_id=oid, name=name, permit=None, channel_kind="state_alert_page", urls=[],
            method=None, legal_basis=Q_RULE, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=[LAW],
            note=(f"No web channel found: {name} reports a Class 1 overflow to DWQ by telephone within 24 hours and in "
                  "writing within five days (R317-801-4); DWQ publishes no list (ut-dwq-class-1-sso-reports). An "
                  f"overflow becomes public only when someone also calls DEQ's spill hotline ({INCIDENTS}).{private} "
                  "No public notice is required. (research/ut/report.md §2.1)"))))
        n = sum(reports[p] for p in ps)
        if n:
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=next(p for p in ps if reports[p]),
                channel_kind="feed", urls=[], method=None,
                legal_basis=Q_EPA.format(permit=next(p for p in ps if reports[p])), basis_kind="permit",
                monitored=False, unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices",
                noun="EPA report", sources=["ut-epa-sobe"],
                note=(f"{name} filed {n} overflow report(s) electronically with EPA (2026-11-04 extract), read by the "
                      f"{FEED} feed. (research/ut/report.md §2.2)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "UT")
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
    rep = run("--dry-run" in sys.argv[1:])
    print(json.dumps(rep, indent=1))
