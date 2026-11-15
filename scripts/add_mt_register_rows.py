"""Montana rows of the notice register (data/notice-channels/mt.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_mt_register_rows.py [--dry-run]

The law (research/mt/report.md section 2.1 in the site repository; research/mt/expansion-research.md):
  - MPDES permit standard conditions (Lolo's MT0020168, Part II.I, read 2026-11-03 and in the expansion pass): serious
    noncompliance reported to DEQ's Water Protection Bureau or Disaster and Emergency Services as soon as possible and
    within 24 hours, in writing within five days (DEQ's SSO form, April 2020). No public notification clause; DEQ
    publishes no list. deq.mt.gov and dphhs.mt.gov did not resolve for the build's client on 2026-11-14.
  - EPA Region 8 issues the permits on tribal land: their reports go to EPA.
Rows
  - Per operator: <id>-deq-report (the report to DEQ, not published: no web page), or <id>-epa-report.
  - Statewide: DEQ's SSO reports and form, DEQ's HAB map layer (read: mt-deq-hab-map) and its dashboard, DPHHS's HAB
    page, DEQ's StoryMap, DEQ's 2023 Warm Springs notice, DEQ's records archive (GovQA) and request portal, the FACTS
    and GIS permit viewers, EPA's overflow tables (no Montana report), the watershed groups, Swim Guide.
A rerun replaces every mt- row it makes. Validated before writing.
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
ST = "MT"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
Q_LAW = ("MPDES permit standard conditions (MT0020168, Part II.I): noncompliance that may seriously endanger health or "
         "the environment, an unanticipated bypass or an upset exceeding a limit reported to DEQ's Water Protection "
         "Bureau or Disaster and Emergency Services \"as soon as possible, but no later than twenty-four (24) hours\", "
         "in writing within five days")
Q_EPA = ("NPDES permit {permit} (EPA Region 8, tribal land): the 24-hour and five-day noncompliance reports of 40 CFR "
         "122.41(l)(6), to EPA")
DNS = (" On 2026-11-14 the host did not resolve for the build's client (DNS timed out); the row is watched so the "
       "refresh records when it answers.")

AGENCY = [
    {"id": "mt-deq-hab-map", "agency": "Montana Department of Environmental Quality",
     "name": "Montana Department of Environmental Quality (harmful algal bloom map layer)", "channel_kind": "feed",
     "urls": ["https://gis.mtdeq.us/hosting/rest/services/Hosted/Harmful_Algal_Bloom_Survey_(Public_Web_Map)/FeatureServer/0"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "mt-deq-hab-map", "publishes": "status",
     "noun": "Data feed",
     "note": ("The layer behind DEQ's HAB dashboard: 445 bloom reports from 2019 to 2026 (2026-11-14), with DEQ's "
              "advisory level and its issue and lift dates; read by the mt-deq-hab-map feed (276 advisories)."),
     "sources": ["mt-hab-map", "mt-deq-hab-dashboard"]},
    {"id": "mt-deq-hab-dashboard", "agency": "Montana Department of Environmental Quality",
     "name": "Montana Department of Environmental Quality (harmful algal bloom dashboard)",
     "channel_kind": "state_alert_page",
     "urls": ["https://gis.mtdeq.us/portal/sharing/rest/content/items/10c34f5c7da24c4188b9ddc220d43970?f=json"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "the harmful algal bloom map layer", "records": False,
     "availability_only": True, "every_hours": 168,
     "note": "DEQ's HAB dashboard (a script page): its item record, watched for a change of layer.",
     "sources": ["mt-deq-hab-dashboard"]},
    {"id": "mt-dphhs-hab", "agency": "Montana Department of Public Health and Human Services",
     "name": "Montana DPHHS (harmful algal blooms)", "channel_kind": "state_alert_page",
     "urls": ["https://dphhs.mt.gov/publichealth/Epidemiology/hab/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "link_only",
     "link_text": "DEQ's harmful algal bloom map", "records": False, "availability_only": True, "every_hours": 168,
     "note": "DPHHS's HAB program page (HAB.mt.gov redirects there), which links the map." + DNS,
     "sources": ["mt-hab-map"]},
    {"id": "mt-deq-hab-storymap", "agency": "Montana Department of Environmental Quality",
     "name": "Montana Department of Environmental Quality (HAB observations StoryMap)", "channel_kind": "state_alert_page",
     "urls": ["https://storymaps.arcgis.com/stories/12f8eb354a51402e9a4732269c515c53"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "DEQ's harmful algal bloom map layer", "records": False,
     "availability_only": True, "every_hours": 168,
     "note": "A narrative StoryMap (a script page with no rows); the layer it shows is read directly (mt-deq-hab-map).",
     "sources": ["mt-deq-hab-storymap"]},
    {"id": "mt-deq-sso-reports", "agency": "Montana Department of Environmental Quality",
     "name": "Montana DEQ (sanitary sewer overflow and noncompliance reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_LAW, "basis_kind": "permit", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("No web channel found: permittees report overflows to DEQ by telephone within 24 hours and on DEQ's SSO "
              "form within five days (start and end, volume, coordinates, receiving water, whether it reached water); "
              "DEQ publishes none of them, and the FACTS system where reports are filed is not public. A redacted "
              "export is a records request to DEQ; none has been sent."),
     "sources": ["mt-deq-sso-form", "mt-mpdes-24h-clause"]},
    {"id": "mt-deq-sso-form", "agency": "Montana Department of Environmental Quality",
     "name": "Montana DEQ (SSO event form)", "channel_kind": "state_alert_page",
     "urls": ["https://deq.mt.gov/files/water/Forms/SanitarySewerOverflow.pdf"], "method": "pdf",
     "legal_basis": Q_LAW, "basis_kind": "permit", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "availability_only": True, "every_hours": 168,
     "note": "The form operators file (April 2020); its fields are the export a records request would ask for." + DNS,
     "sources": ["mt-deq-sso-form"]},
    {"id": "mt-deq-warm-springs-2023", "agency": "Montana Department of Environmental Quality",
     "name": "Montana DEQ (news: Warm Springs Creek wastewater discharge, July 2023)", "channel_kind": "news_page",
     "urls": ["https://deq.mt.gov/News/pressrelease-folder/news-article95"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "notices",
     "records": False, "every_hours": 168,
     "note": ("DEQ's notice of July 21, 2023 (expansion research, 2026-11-09): more than three million gallons of "
              "partially treated wastewater to Warm Springs Creek during construction at the Montana State Hospital, "
              "DEQ notified June 23. Not ingested: the page could not be read in this build." + DNS),
     "sources": ["mt-news-spills", "mt-deq-warm-springs-2023"]},
    {"id": "mt-deq-records-archive", "agency": "Montana Department of Environmental Quality",
     "name": "Montana DEQ (released public records archive)", "channel_kind": "state_alert_page",
     "urls": ["https://montanadeq.govqa.us/WEBAPP/_rs/openrecordssummary.aspx?sSessionID=&view=1"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "documents", "records": False,
     "note": ("Summaries of released records requests (request number, date, summary, release status). Not fetched: "
              "the summaries name requesters and properties, and a request summary is not a finding (channel not researched "
              "beyond the expansion pass)."),
     "sources": ["mt-deq-records-archive"]},
    {"id": "mt-deq-facts", "agency": "Montana Department of Environmental Quality",
     "name": "Montana DEQ (FACTS permitting and the GIS permit viewer)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "login", "publishes": "none", "records": False,
     "note": ("FACTS (https://svc.mt.gov/deq/factspermitting), where permittees file reports, and the GIS permit viewer "
              "expose no public overflow rows (expansion research, 2026-11-09)."),
     "sources": ["mt-deq-facts-public-viewer"]},
    {"id": "mt-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "availability_only": True, "every_hours": 168, "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables hold no Montana report: none in the current extract of 2026-11-14 "
              "(5,751 events) nor in the all-versions extract (6,710 events); the collection-system table lists three "
              "Montana permits, EPA's on tribal land (Polson, Ronan, Poplar). Watched for Montana rows."),
     "sources": ["mt-epa-sobe"]},
    {"id": "mt-watershed-groups", "agency": "Montana watershed groups",
     "name": "Montana watershed groups (Gallatin River Task Force, Clark Fork Coalition)", "channel_kind": "group_results",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "results", "records": False,
     "note": ("Annual nutrient and algae monitoring reports (Gallatin, Bitterroot); not sewage or bloom advisories "
              "(expansion research, 2026-11-09); not verified in the research as a public results feed."),
     "sources": ["mt-watershed-groups"]},
    {"id": "mt-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish (Swim Guide)",
     "channel_kind": "swim_guide", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "No Montana beach bacteria program or Swim Guide affiliate found (research, search only).",
     "sources": ["mt-beach-ecoli"]},
]


def base(**kw) -> dict:
    r = {"state": ST, "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != ST or "mt" not in (op.get("source_areas") or []):
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        epa = op.get("epa_issued_permits") or []
        if epa and len(epa) == len(ps):
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=epa[0], channel_kind="state_alert_page",
                urls=[], method=None, legal_basis=Q_EPA.format(permit=epa[0]), basis_kind="permit", monitored=False,
                unmonitored_reason="other", publishes="none", records=False, noun="EPA report",
                sources=["mt-epa-sobe"],
                note=(f"No web channel found: {name}'s permit is EPA's (tribal land), so its noncompliance reports go to "
                      "EPA Region 8, which publishes those filed electronically in its overflow tables (none for "
                      "Montana in the extracts of 2026-11-14)."))))
            continue
        rows.append(finish(base(
            id=f"{oid}-deq-report", operator_id=oid, name=name, permit=None, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=Q_LAW, basis_kind="permit", monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=["mt-mpdes-24h-clause"],
            note=(f"No web channel found: {name} reports an overflow or other serious noncompliance to DEQ within 24 "
                  "hours and in writing within five days under its permit; DEQ publishes no list (mt-deq-sso-reports), "
                  "and no duty to tell the public was found. Its own web channel was not searched individually."))))
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
