"""Missouri rows of the notice register (data/notice-channels/mo.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_mo_register_rows.py [--dry-run]

The law (research/mo/report.md section 2.1 in the site repository; research/mo/expansion-research.md):
  - DNR's sewer overflow guidance (read 2026-11-09 and 2026-11-14): "All permitted wastewater treatment facilities must
    report SSOs or bypasses from their treatment works or collection system to the department within 24 hours of
    discovering the event", through its MoGEM portal. A report to the agency only: DNR publishes no list.
  - No statute or rule requiring public notice of a sewage discharge was found. A combined sewer permittee's public
    notification rests on its permit's Nine Minimum Controls and its consent decree (MSD 2011, Kansas City 2010); the
    permit clauses were not read.
  - RSMo 640.080: DNR posts "Swimming is Not Recommended" at a state park swim beach when the weekly samples' geometric
    mean exceeds 190 E. coli per 100 mL (a bacteria advisory, not a sewage report).
Rows
  - Per operator (every Missouri row of data/dischargers.json): <id>-dnr-report, the 24-hour report to DNR (law; through
    MoGEM; not published); a CSO permittee also gets <id>-cso-permit-notice (the permit's public notification, not
    read); KC Water and MSD get their news channels, read by the mo-kc-water-overflow-notices and
    mo-msd-stl-project-clear feeds.
  - Statewide: DNR's concern reports (the mo-dnr-concern-reports feed), MoGEM's unpublished reports, the MERLIN and
    MEERTS emergency-response searches (forms, not read), the environmental-concern intake form, the state park beach
    status (a script-drawn map, in season), the HAB reports map (an ArcGIS Experience app), the outfall signs, EPA's
    overflow tables (no Missouri reports) and Swim Guide.
A rerun replaces every mo- row it makes. Validated before writing.
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
LAW = "mo-dnr-sso-reporting-mogem"
GUIDE = ("https://dnr.mo.gov/water/business-industry-other-entities/permits-certification-engineering-fees/wastewater/"
         "sewer-overflows")
KC_ID, MSD_ID = "mo-kansas-city-mo0024911", "mo-st-louis-mo0025151"
Q_RULE = ('DNR sewer overflow guidance: "All permitted wastewater treatment facilities must report SSOs or bypasses from '
          'their treatment works or collection system to the department within 24 hours of discovering the event", '
          "through the MoGEM portal; the permits' standard conditions")
Q_CSO = ("NPDES combined sewer permit {permit}: public notification of overflows is one of the nine minimum controls of "
         "EPA's Combined Sewer Overflow Control Policy (59 FR 18688, 1994), which the permit is expected to carry; the "
         "permit's own clause was not read")
Q_BEACH = ("RSMo 640.080: the Department posts a state park swim beach \"Swimming is Not Recommended\" when the weekly "
           "samples' geometric mean exceeds 190 E. coli per 100 mL")

AGENCY = [
    {"id": "mo-dnr-concern-reports", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (Water Pollution Control concern reports)", "channel_kind": "feed",
     "urls": ["https://dnr.mo.gov/commissions-boards-councils/clean-water-commission"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "mo-dnr-concern-reports", "publishes": "documents", "noun": "Data feed",
     "note": ("The monthly reports of the environmental concerns the Department investigated, linked from the Clean "
              "Water Commission's page with its meetings, two to four months after the month: six reports, December "
              "2025 to May 2026, 945 concerns, 140 typed 'Bypass or Sewer Overflow' (read 2026-11-14). A concern is "
              "the concerned party's report; the Department's comments say what it found. (research/mo/expansion-"
              "research.md)"),
     "sources": ["mo-dnr-concern-reports"]},
    {"id": "mo-dnr-mogem-sso-reports", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (sewer overflow and bypass reports through MoGEM)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_RULE, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "login", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("Every permitted facility reports an overflow or bypass to DNR within 24 hours through MoGEM, the "
              "Department's login portal. DNR publishes no list of these reports; they reach the public only through a "
              f"Sunshine Law request or when a concern report cross-references one. ({GUIDE})"),
     "sources": [LAW]},
    {"id": "mo-dnr-merlin-search", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (MERLIN environmental emergency search)",
     "channel_kind": "state_alert_page", "urls": ["https://apps5.mo.gov/merlin/publicSearch.action"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "availability_only": True,
     "noun": "Voluntary page",
     "note": ("The public search of the Department's environmental emergency response incidents since November 2021 "
              "(spill line and National Response Center calls). A search form with no export; no sewage query was "
              "verified, so its records are not read. Watched for availability."),
     "sources": ["mo-dnr-merlin-search"]},
    {"id": "mo-dnr-meerts-search", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (MEERTS historical incident search)",
     "channel_kind": "state_alert_page", "urls": ["https://dnrservices.mo.gov/env/esp/meerts/search"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "availability_only": True,
     "noun": "Voluntary page",
     "note": ("The older incident search (incidents to October 2021). Its result list loads, its detail pages did not "
              "(cache misses, 2026-11-09); not read. Watched for availability."),
     "sources": ["mo-dnr-meerts-search"]},
    {"id": "mo-dnr-environmental-concern", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (report an environmental concern)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "note": ("No web channel found for the reports themselves: the public's form for reporting a concern (https://dnr.mo.gov/reporting/environmental-concern) and the "
              "24-hour spill line: intake only, nothing published there; what DNR investigated appears later in the "
              "monthly concern reports."),
     "sources": ["mo-dnr-environmental-concern"]},
    {"id": "mo-dnr-beach-status", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (state park beach status)", "channel_kind": "state_alert_page",
     "urls": ["https://dnr.mo.gov/water/alerts-hazards/beaches"], "method": "html", "legal_basis": Q_BEACH,
     "basis_kind": "law", "monitored": True, "unmonitored_reason": None, "publishes": "status", "records": False,
     "every_hours": 24, "availability_only": True, "noun": "Notification page",
     "note": ("Weekly E. coli results and posting status of the state park swim beaches from Memorial Day to Labor Day, "
              "drawn by a script map on the page (each beach on its own page) with a GovDelivery sign-up. Bacteria, not "
              "sewage. The per-beach data were not read (out of season on 2026-11-14): watched for availability."),
     "sources": ["mo-dnr-beach-status"]},
    {"id": "mo-dnr-hab-map", "agency": "Missouri Department of Natural Resources",
     "name": "Missouri Department of Natural Resources (HAB reports map)", "channel_kind": "feed",
     "urls": ["https://gis.dnr.mo.gov/host/rest/services/wqm/HAB_SUBMIT_POINTS/MapServer/6",
              "https://dnr.mo.gov/water/alerts-hazards/harmful-algal-bloom-hab-reports-map"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "mo-dnr-hab-map", "publishes": "status", "noun": "Data feed",
     "note": ("The public layer behind DNR's HAB map: one point per bloom report, with DNR's status. The reports DNR's "
              "map shows as a harmful algal bloom present, or the water closed, are read as standing bloom advisories "
              "(39 on 2026-11-15, observed from May to November 2026); suspected, dissipated and unverified reports "
              "are counted, not shown. Privately owned waters are only counted by county. Blooms, not sewage."),
     "sources": ["mo-dnr-hab-map"]},
    {"id": "mo-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False,
     "note": ("No web channel found for Missouri: EPA's sewer overflow and bypass event tables carry no Missouri reports (research of 2026-11-03; Missouri "
              "is not among the states whose systems send them). Re-checked when EPA adds a state."),
     "sources": ["fed-echo-sewer-overflow-bypass-events"]},
    {"id": "mo-outfall-signs", "agency": "Missouri combined sewer operators",
     "name": "Combined sewer outfall signs (MSD, KC Water)", "channel_kind": "lights_signs_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False,
     "note": ("MSD's customer letters describe signs at its overflow points (\"do not play, swim, or fish during possible "
              "sewage overflow\"), and KC Water posts signs near overflow sites: signs only, no web notice of each "
              "overflow. (research/mo/report.md §2.3)"),
     "sources": ["mo-msd-stl-project-clear"]},
    {"id": "mo-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "note": ("Swim Guide lists Missouri state park beaches, mostly with no data, attributing monitoring to DNR; not "
              "read (channel not researched beyond one beach page)."),
     "sources": ["mo-swim-guide"]},
]
OWN = {
    KC_ID: {"id": f"{KC_ID}-news", "name": "KC Water (City of Kansas City, Missouri)", "channel_kind": "news_page",
            "urls": ["https://www.kcwater.us/news/"], "method": "rss", "legal_basis": None, "basis_kind": "voluntary",
            "monitored": False, "unmonitored_reason": "feed_ingested",
            "feed_source_id": "mo-kc-water-overflow-notices", "publishes": "notices", "noun": "Voluntary page",
            "note": ("KC Water's news posts announce some overflows (\"Customers Advised of Wastewater Overflow near "
                     "...\"): 99 notices from July 2016 to August 2025, read through the site search's RSS feed. No "
                     "rule requiring the posts was found."),
            "sources": ["mo-kc-water-overflow-notices"]},
    MSD_ID: {"id": f"{MSD_ID}-alerts", "name": "Metropolitan St. Louis Sewer District (MSD Project Clear)",
             "channel_kind": "news_page", "urls": ["https://msdprojectclear.org/newsroom/alerts/"], "method": "json",
             "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
             "feed_source_id": "mo-msd-stl-project-clear", "publishes": "notices", "noun": "Voluntary page",
             "note": ("MSD Project Clear's alerts and news releases announce some overflows: 89 posts since June 2013 "
                      "read through the site's WordPress API. No rule requiring the posts was found."),
             "sources": ["mo-msd-stl-project-clear"]},
}


def base(**kw) -> dict:
    r = {"state": "MO", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def cso_permits() -> set[str]:
    """Missouri permits with an open CSO outfall (DNR's rows win over EPA's; an industrial row held back is not one)."""
    out = set()
    held = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-mo.json").read_text())["outfalls"]
            if r.get("outfall_kind") == "other"}
    for f in ("outfalls-us.json", "outfalls-mo.json"):
        for r in json.loads((ROOT / "data" / f).read_text())["outfalls"]:
            if r.get("npdes_permit") in held:
                continue
            if str(r.get("npdes_permit") or "").startswith("MO") and r.get("outfall_kind") == "cso" and \
                    not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                out.add(r["npdes_permit"])
    return out


def operator_rows(dis: list[dict]) -> list[dict]:
    rows, csos = [], cso_permits()
    for op in dis:
        if op.get("state") != "MO":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        private = (" The duty binds the permittee, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility") else "")
        rows.append(finish(base(
            id=f"{oid}-dnr-report", operator_id=oid, name=name, permit=None, channel_kind="state_alert_page", urls=[],
            method=None, legal_basis=Q_RULE, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=[LAW],
            note=(f"No web channel found: {name} reports a sewer overflow or bypass to DNR within 24 hours through "
                  "MoGEM; DNR publishes no list (mo-dnr-mogem-sso-reports). An overflow becomes public only when a "
                  f"concern report names it, months later (mo-dnr-concern-reports).{private} No public notice is "
                  "required by statute or rule. (research/mo/report.md §2.1)"))))
        for p in ps:
            if p in csos:
                rows.append(finish(base(
                    id=f"{oid}-cso-permit-notice-{p.lower()}", operator_id=oid, name=name, permit=p,
                    channel_kind="operator_page", urls=[], method=None, legal_basis=Q_CSO.format(permit=p),
                    basis_kind="permit", monitored=False, unmonitored_reason="other", publishes="unknown",
                    sources=[LAW],
                    note=(f"What {name}'s combined sewer permit {p} requires the public to be told, and how, was not "
                          "verified in the research: the permit's notification clause was not read. "
                          "(research/mo/expansion-research.md)"))))
        if oid in OWN:
            rows.append(finish(base(operator_id=oid, **OWN[oid])))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "MO")
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
