"""North Dakota rows of the notice register (data/notice-channels/nd.json), made from the law, the permits, the
research and data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_nd_register_rows.py [--dry-run]

The law (research/nd/report.md section 2.1 in the site repository; research/nd/expansion-research.md):
  - No North Dakota statute or rule requires the public to be told of a sewage discharge.
  - N.D. Admin. Code 33.1-16-02.1-11(4): a spill or discharge that causes or is likely to cause water pollution is
    reported to the Department of Environmental Quality immediately (by telephone or spill.nd.gov).
  - The permits: the domestic-treatment general permit NDG420000 Part IV(F) and the individual permits' standard
    conditions, an oral report within 24 hours and a written one within five days (40 CFR 122.41(l)(6)).
  - Fargo's draft permit of 2023 (public notice ND-2023-021) proposed immediate public notice of an overflow its plan
    identifies; the final permit was not read, so the clause is quoted as the draft's.
  - Reports since 2021 go into the unified spill system (HazConnect), whose public incident list answers 403 with a
    Cloudflare block page to the project's identified client (2026-11-03, 2026-11-09, 2026-11-14): a barrier to
    register, never to get around.
Rows
  - Per operator (every North Dakota row of data/dischargers.json): <id>-spill-report (law and permit basis), the
    report to DEQ, whose public trace since 2021 is HazConnect's list (bot wall).
  - Fargo: nd-fargo-public-notification (permit basis, the draft's clause), none found.
  - Agency rows: AGENCY below (HazConnect, the archive, the bloom listing, CERIS-ND, the press releases, the permit
    factsheets, EPA's tables, the beach bacteria gap).
A rerun replaces every nd- row it makes. Validated before writing.
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
HAZ = "https://northdakota.hazconnect.com/ListIncidentPublic.aspx"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
LAW = ("N.D. Admin. Code 33.1-16-02.1-11(4): immediate report to the Department of Environmental Quality of a spill or "
       "discharge that causes or is likely to cause water pollution; the permit's standard conditions (NDG420000 Part "
       "IV(F) for the domestic-treatment general permit; 40 CFR 122.41(l)(6)): an oral report within 24 hours and a "
       "written one within five days")
FARGO = ("NDPDES permit ND0022870, draft of 2023 (public notice ND-2023-021): \"The permittee shall immediately notify "
         "the public, public health agencies, and other affected entities (e.g. public water systems) of any sanitary "
         "sewer overflow\" identified in its notification plan; the final permit was not read")
AGENCY = [
    {"id": "nd-hazconnect-public-incidents", "agency": "North Dakota Department of Environmental Quality and Department of Emergency Services",
     "name": "North Dakota unified spill reporting (HazConnect)", "channel_kind": "state_alert_page", "urls": [HAZ],
     "method": "html", "legal_basis": LAW, "basis_kind": "law", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "notices", "records": False, "noun": "Incident list",
     "note": ("The state's public list of every incident reported since 2021-01-01 answers 403 with Cloudflare's block "
              "page to the project's identified client (2026-11-03, 2026-11-09, 2026-11-14); whether municipal sewage "
              "overflows are entered could not be confirmed. Not got around: the fix is a supported export or "
              "allow-listing."),
     "sources": ["nd-hazconnect-public-incidents", "nd-spill-reporting-procedures"]},
    {"id": "nd-deq-eir-legacy-general", "agency": "North Dakota Department of Environmental Quality",
     "name": "North Dakota DEQ (incident archive 1975-2020)", "channel_kind": "state_alert_page",
     "urls": ["https://deq.nd.gov/FOIA/Spills/defaultarc.aspx/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "nd-deq-eir-legacy-general", "publishes": "notices", "noun": "Incident archive",
     "note": ("DEQ's archive of General Environmental Incident reports from 1975 to 2020 (4,452 incidents; 36 name "
              "sewage, a sewer or a septic system); read by the nd-deq-eir-legacy-general feed. Frozen."),
     "sources": ["nd-deq-eir-legacy-general"]},
    {"id": "nd-deq-hab-listings", "agency": "North Dakota Department of Environmental Quality",
     "name": "North Dakota DEQ (harmful algal bloom listing)", "channel_kind": "state_alert_page",
     "urls": ["https://www.deq.nd.gov/publications/WQ/3_WM/HABs/HABsListings.pdf"], "method": "pdf",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "nd-deq-hab-listings", "publishes": "notices", "noun": "Bloom advisories",
     "note": ("DEQ's listing of harmful algal bloom advisories and warnings by lake and county (14 and 6 on "
              "2026-11-14), updated 1 May to 31 December; read by the nd-deq-hab-listings feed. Blooms, not sewage."),
     "sources": ["nd-deq-hab-listings", "nd-deq-hab-program"]},
    {"id": "nd-ceris-open-records", "agency": "North Dakota Department of Environmental Quality",
     "name": "North Dakota DEQ (CERIS-ND open records)", "channel_kind": "state_alert_page",
     "urls": ["https://ceris.deq.nd.gov/ext/nsite/default"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other", "publishes": "unknown",
     "records": False, "noun": "Permit records",
     "note": ("DEQ's permit reporting system's public records (noncompliance submittals, inspections, final permits); "
              "the interface is a JavaScript application that returned only its shell to the research (2026-11-09), so "
              "whether it shows overflows is not verified in the research."),
     "sources": ["nd-ceris-open-records"]},
    {"id": "nd-deq-press-releases", "agency": "North Dakota Department of Environmental Quality",
     "name": "North Dakota DEQ (press releases)", "channel_kind": "news_page",
     "urls": ["https://deq.nd.gov/PressReleases.aspx"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "notices",
     "records": False, "every_hours": 24, "noun": "Press releases",
     "note": ("DEQ's dated PDF press releases: weekly bloom updates in season and occasional water advisories (the Goose "
              "River notice of 2026-09-22, not a sewage event). Not a list of overflows."),
     "sources": ["nd-deq-press-releases"]},
    {"id": "nd-permit-factsheets", "agency": "North Dakota Department of Environmental Quality",
     "name": "North Dakota DEQ (permit factsheets)", "channel_kind": "state_alert_page",
     "urls": ["https://deq.nd.gov/PublicComment/NDPDES-Fargo-20231216.pdf"], "method": "pdf", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "image_only", "publishes": "documents",
     "records": False, "noun": "Permit factsheets",
     "note": ("Draft-permit factsheets list a city's past bypasses and overflows (Fargo's Table 4: 23 rows, January 2019 "
              "to July 2023; Grand Forks' Table 3: five rows to September 2023). Fargo's package is a scanned image; "
              "Grand Forks' table is text the project's PDF reader could not place reliably. History only, not read."),
     "sources": ["nd-permit-factsheet-sso-tables", "nd-fargo-ndpdes-permit"]},
    {"id": "nd-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "none", "records": False, "every_hours": 168, "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables hold no North Dakota report (2026-11-12 current and all-versions "
              "extracts; five North Dakota permits in the collection-system table). Watched: North Dakota is added to "
              "the feed when one appears."),
     "sources": ["nd-epa-sobe"]},
    {"id": "nd-beach-bacteria-advisories", "agency": "North Dakota Department of Environmental Quality",
     "name": "North Dakota (beach bacteria advisories)", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("No web channel found: the research found no North Dakota program that samples swimming beaches for "
              "bacteria and posts advisories (search only)."),
     "sources": ["nd-beach-ecoli"]},
]


def base(**kw) -> dict:
    r = {"state": "ND", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "ND":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        rows.append(finish(base(
            id=f"{oid}-spill-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
            urls=[HAZ], method="html", legal_basis=LAW, basis_kind="law", monitored=False,
            unmonitored_reason="bot_wall", publishes="notices", records=False, noun="Report to the state",
            sources=["nd-hazconnect-public-incidents", "nd-ndac-33-1-16-02-1-11", "nd-ndg420000-general-permit"],
            note=(f"{name} reports a spill or overflow to DEQ immediately, and under its permit within 24 hours and in "
                  "writing within five days. Since 2021 the reports go into the unified spill system, whose public list "
                  "answers 403 to the project's identified client; no North Dakota rule requires it to tell the "
                  "public."))))
        if oid == "nd-fargo":
            rows.append(finish(base(
                id=f"{oid}-public-notification", operator_id=oid, name=name, permit="ND0022870",
                channel_kind="operator_page", urls=[], method=None, legal_basis=FARGO, basis_kind="permit",
                monitored=False, unmonitored_reason="none_found", publishes="none", records=False,
                noun="Public notification of overflows", sources=["nd-fargo-ndpdes-permit"],
                note=("No web channel found: the research found no City page of overflow notices (its May 2024 "
                      "release was a sump-pump precaution, not an overflow notice); the plan the draft permit "
                      "names was not read."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "ND")
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
