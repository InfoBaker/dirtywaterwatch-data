"""Kansas rows of the notice register (data/notice-channels/ks.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ks_register_rows.py [--dry-run]

The law (research/ks/report.md section 2.1 in the site repository; research/ks/expansion-research.md):
  - K.A.R. 28-16-27 (read on law.cornell.edu): an emergency or accidental discharge of sewage "shall be immediately
    reported to the state department of health"; a planned bypass needs notice and approval at least seven days ahead.
    A report to the agency only: KDHE publishes no list.
  - No statute or rule requiring public notice of a sewage discharge was found. KDHE's spill rule (K.A.R. 28-48, as
    KDHE's spill instructions reproduce it) adds a duty to try to notify the owners and tenants of affected property
    within five days: a notice to those people, not a public one. A combined sewer permittee's public notification
    rests on its permit's Nine Minimum Controls and, for the Unified Government, its consent decree (2013, modified
    2020); the permit clauses were not read.
Rows
  - Per operator (every Kansas row of data/dischargers.json): <id>-kdhe-report, the immediate report to KDHE (law; by
    telephone to a district office; not published); a CSO permittee also gets <id>-cso-permit-notice-<permit>;
    Leavenworth gets its transparency pages, read by the ks-leavenworth-sso-transparency feed.
  - Statewide: KDHE's stream advisories (the ks-kdhe-stream-advisories feed), its HAB status layer (ks-kdhe-hab-status)
    and HAB page, its public spills map (a lead: few sewage rows, approximate points), the incident report form, the
    monitoring stations layer, Topeka's stream advisories (city news; refused automated reading), EPA's overflow tables
    and Swim Guide.
A rerun replaces every ks- row it makes. Validated before writing.
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
LAW = "ks-law-kar-28-16-27"
LEAVENWORTH = "ks-leavenworth"
Q_RULE = ('K.A.R. 28-16-27: an emergency or accidental discharge of sewage to waters of the state "shall be immediately '
          'reported to the state department of health"; it applies to a discharge a valid permit does not provide for; '
          "a planned bypass needs notice and approval at least seven days ahead")
Q_CSO = ("NPDES combined sewer permit {permit}: public notification of overflows is one of the nine minimum controls of "
         "EPA's Combined Sewer Overflow Control Policy (59 FR 18688, 1994), which the permit is expected to carry; the "
         "permit's own clause was not read")
KDHE = "Kansas Department of Health and Environment"

AGENCY = [
    {"id": "ks-kdhe-stream-advisories", "agency": KDHE, "name": f"{KDHE} (stream advisories)", "channel_kind": "feed",
     "urls": ["https://www.kdhe.ks.gov/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml"], "method": "rss",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "ks-kdhe-stream-advisories", "publishes": "notices", "noun": "Data feed",
     "note": ("KDHE issues and rescinds stream advisories (avoid contact) by news flash after a sewage or other "
              "wastewater discharge when it judges one needed; its feed carries about a month of releases (42 on "
              "2026-11-14, one stream advisory rescission among them). The release pages and the news index answer 403 "
              "to automated clients. (research/ks/expansion-research.md)"),
     "sources": ["ks-kdhe-stream-advisories"]},
    {"id": "ks-kdhe-hab-status", "agency": KDHE, "name": f"{KDHE} (HAB status map layer)", "channel_kind": "feed",
     "urls": ["https://maps.kdhe.ks.gov/kdhe_doe/rest/services/HAB/HAB_County/MapServer/0"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "ks-kdhe-hab-status", "publishes": "status", "noun": "Data feed",
     "note": ("The lakes under a bloom Hazard, Warning or Watch, with points: 16 points on 15 lakes on 2026-11-14 (8 "
              "Warning, 8 Watch), dated by KDHE's table update (2026-10-30), not per advisory. Blooms, not sewage."),
     "sources": ["ks-kdhe-hab-status"]},
    {"id": "ks-kdhe-hab-page", "agency": KDHE, "name": f"{KDHE} (Harmful Algal Blooms page)",
     "channel_kind": "state_alert_page", "urls": ["https://www.kdhe.ks.gov/777/Harmful-Algal-Blooms"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "status", "records": False,
     "note": ("KDHE's HAB page, with the table of lakes under an advisory, answers 403 to automated clients (2026-11-14); "
              "the map layer above carries the same lakes."),
     "sources": ["ks-kdhe-hab-page"]},
    {"id": "ks-kdhe-district-reports", "agency": KDHE,
     "name": f"{KDHE} (sewage discharge reports under K.A.R. 28-16-27)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_RULE, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("No web channel found: operators report an emergency or accidental sewage discharge to KDHE's district "
              "offices by telephone; KDHE publishes no list of these reports, and its incident form answers 403. They "
              "reach the public only through a records request or, when KDHE issues one, a stream advisory."),
     "sources": [LAW, "ks-kdhe-incident-report"]},
    {"id": "ks-kdhe-spills-dasc", "agency": KDHE, "name": f"{KDHE} (reported spills map layer)",
     "channel_kind": "state_alert_page",
     "urls": ["https://maps.kdhe.ks.gov/kdhe_doe/rest/services/BER/Spills_DASC/MapServer/0"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "availability_only": True, "noun": "Voluntary page",
     "note": ("KDHE's public layer of reported spills since 1983: 32,455 rows on 2026-11-14, of which 474 name waste "
              "water or sewage and 40 sewage (mostly septic haulers and soil spills, many with no point or a point at "
              "0,0; KDHE warns some points are legal-section centroids miles from the spill). Municipal sewer "
              "overflows are not in it in any number, so it is not read as a sewage record; watched for availability."),
     "sources": ["ks-kdhe-spills-dasc"]},
    {"id": "ks-kdhe-monitoring-sites", "agency": KDHE, "name": f"{KDHE} (monitoring stations layer)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "note": ("No web channel found for advisories here: the stations layer names sampling sites and programs, not "
              "advisories (context only)."),
     "sources": ["ks-kdhe-monitoring-sites"]},
    {"id": "ks-topeka-stream-advisories", "agency": "City of Topeka", "name": "City of Topeka (stream advisories)",
     "channel_kind": "news_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "notices", "records": False,
     "note": ("Topeka has posted stream advisories as city news after some overflows (2020, 2023, 2024); its news site "
              "answered 403 to automated clients in the research (2026-11-09)."),
     "sources": ["ks-topeka-stream-advisories"]},
    {"id": "ks-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False,
     "note": ("No web channel found for Kansas: EPA's overflow tables list five Kansas collection systems and no Kansas "
              "events (research of 2026-11-03). Re-checked when EPA adds a state."),
     "sources": ["fed-echo-sewer-overflow-bypass-events"]},
    {"id": "ks-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "note": "No Kansas listing checked (channel not researched).", "sources": []},
]
OWN = {
    LEAVENWORTH: {"id": f"{LEAVENWORTH}-transparency-reports", "name": "City of Leavenworth (Water Pollution Control)",
                  "channel_kind": "operator_page",
                  "urls": ["https://www.leavenworthks.gov/publicworks/page/sanitary-sewer-overflow-transparency-report"],
                  "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
                  "unmonitored_reason": "feed_ingested", "feed_source_id": "ks-leavenworth-sso-transparency",
                  "publishes": "notices", "noun": "Voluntary page",
                  "note": ("The City's Sanitary Sewer Overflow Transparency Reports: a page per overflow, 28 from 2020 "
                           "to 2026, with yearly index pages. Voluntary."),
                  "sources": ["ks-leavenworth-sso-transparency"]},
}


def base(**kw) -> dict:
    r = {"state": "KS", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def cso_permits() -> set[str]:
    """Kansas permits with an open CSO outfall in EPA's inventory."""
    out = set()
    for f in ("outfalls-us.json",):
        for r in json.loads((ROOT / "data" / f).read_text())["outfalls"]:
            if str(r.get("npdes_permit") or "").startswith("KS") and r.get("outfall_kind") == "cso" and \
                    not str(r.get("outfall_status") or "").upper().startswith("CLS"):
                out.add(r["npdes_permit"])
    return out


def operator_rows(dis: list[dict]) -> list[dict]:
    rows, csos = [], cso_permits()
    for op in dis:
        if op.get("state") != "KS":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        private = (" The duty binds the permittee, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility") else "")
        rows.append(finish(base(
            id=f"{oid}-kdhe-report", operator_id=oid, name=name, permit=None, channel_kind="state_alert_page", urls=[],
            method=None, legal_basis=Q_RULE, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=[LAW],
            note=(f"No web channel found: {name} reports an emergency or accidental sewage discharge that its "
                  "permit does not provide for to KDHE immediately (K.A.R. 28-16-27); KDHE publishes no list (ks-kdhe-district-reports). An overflow becomes "
                  f"public only when KDHE issues a stream advisory (ks-kdhe-stream-advisories).{private} No public "
                  "notice is required by statute or rule. (research/ks/report.md §2.1)"))))
        for p in ps:
            if p in csos:
                rows.append(finish(base(
                    id=f"{oid}-cso-permit-notice-{p.lower()}", operator_id=oid, name=name, permit=p,
                    channel_kind="operator_page", urls=[], method=None, legal_basis=Q_CSO.format(permit=p),
                    basis_kind="permit", monitored=False, unmonitored_reason="other", publishes="unknown",
                    sources=[LAW],
                    note=(f"What {name}'s combined sewer permit {p} requires the public to be told, and how, was not "
                          "verified in the research: the permit's notification clause was not read. "
                          "(research/ks/expansion-research.md)"))))
        if oid in OWN:
            rows.append(finish(base(operator_id=oid, **OWN[oid])))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "KS")
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
