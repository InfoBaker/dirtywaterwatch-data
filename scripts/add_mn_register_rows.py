"""Minnesota rows of the notice register (data/notice-channels/mn.json), made from the law, the research and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_mn_register_rows.py [--dry-run]

The law (research/mn/report.md section 2.1 in the site repository; research/mn/expansion-research.md):
  - Minn. Stat. 115.061(a): every person reports a discharge that may pollute waters of the state to the Minnesota
    Pollution Control Agency immediately (the Minnesota Duty Officer takes the call); the reports are not published.
  - 115.061(c): promptly after that, a publicly owned treatment works or a publicly or privately owned domestic sewer
    system owner notifies potentially impacted downstream users, including the public, Tribal governments and drinking
    water facilities, "using the most efficient communications system available" (in person, telephone, radio, social
    media, web page or another expedited form), posts signs at impacted public use areas (or tells the body with
    jurisdiction over them), and gives the date and time, the material, a health warning and its contact.
  - MPCA guidance wq-wwprm1-43 (November 2023) and wq-wwprm1-59 (October 2026): public locations within 25 miles
    downstream; a notice when the release has ended.
Rows
  - Per operator (every Minnesota row of data/dischargers.json): <id>-public-notice (law basis, 115.061(c)). Three are
    read or monitored: the Metropolitan Council (its spill pages, read by mn-mces-spill-notices), the Western Lake
    Superior Sanitary District (its overflow map, read by mn-wlssd-overflows) and the City of Duluth (its press releases:
    the host did not answer the project's client on 2026-11-14, so unmonitored, other). Every other operator's channel
    was not searched individually (barrier not_verified): the statute lets each choose its means.
  - The Bois Forte Band (MN0061310, an EPA permit): <id>-overflow-report, its written reports through EPA's tables.
  - Agency rows: AGENCY below (the Duty Officer, MPCA, EPA's tables, MDH's beach programs, MPCA's bloom guidance).
A rerun replaces every mn- row it makes. Validated before writing.
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
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
MCES = "https://metrocouncil.org/Wastewater-Water/Services/Interceptor-Services/Spills.aspx"
WLSSD = "https://wlssd.com/services/wastewater/overflows/"
LAW = ("Minn. Stat. 115.061(c): promptly after reporting a discharge to the agency, a publicly owned treatment works or "
       "a publicly or privately owned domestic sewer system owner must notify potentially impacted downstream users, "
       "including the public, Tribal governments and drinking water facilities, by the most efficient communications "
       "system available (in person, telephone, radio, social media, web page or another expedited form), and post "
       "signs at impacted public use areas or notify the entity with jurisdiction over them")
Q_PERMIT = ("NPDES permit {permit} (EPA Region 5): standard conditions, a report of noncompliance that may endanger "
            "health or the environment within 24 hours and a written report within 5 days (40 CFR 122.41(l)(6)), filed "
            "electronically through EPA's NeT-SewerOverflow (40 CFR part 127)")
OWN = {
    "mn-mces": dict(channel_kind="operator_page", urls=[MCES], method="html", monitored=False,
                    unmonitored_reason="feed_ingested", feed_source_id="mn-mces-spill-notices", publishes="notices",
                    noun="Spill notices", sources=["mn-mces-spill-notices"],
                    note=("The Council's Wastewater Spills page links a page per spill from its regional interceptors "
                          "(posted for one year), with dated updates and the signs it posts and removes; read by the "
                          "mn-mces-spill-notices feed (three spills listed on 2026-11-14).")),
    "mn-wlssd": dict(channel_kind="operator_page", urls=[WLSSD], method="html", monitored=False,
                     unmonitored_reason="feed_ingested", feed_source_id="mn-wlssd-overflows", publishes="notices",
                     noun="Overflow map", sources=["mn-wlssd-overflows"],
                     note=("Resource Renew (WLSSD) maps its releases on its overflows page from a public ArcGIS layer "
                           "(117 releases, 2005 to 2026-11-04, on 2026-11-14); read by the mn-wlssd-overflows feed.")),
    "mn-duluth": dict(channel_kind="news_page", urls=[], method=None, monitored=False, unmonitored_reason="other",
                      publishes="notices", records=False, noun="Press releases", sources=["mn-duluth-press-releases"],
                      signup_url=None,
                      note=("The City posts overflow notices as press releases with an e-mail subscription (the Chester "
                            "Creek notice of October 2024 kept its earlier warnings below its updates). No list or feed "
                            "of the overflow notices was found, and duluthmn.gov did not answer the project's client on "
                            "2026-11-14 (connection timed out), as it did not on 2026-11-09 for the research: the channel is not verified in the research and not read.")),
}
AGENCY = [
    {"id": "mn-duty-officer", "agency": "Minnesota Department of Public Safety (Minnesota Duty Officer)",
     "name": "Minnesota Duty Officer", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": "Minn. Stat. 115.061(a): immediate notice to the agency of a discharge that may pollute waters of the state",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("Reports are taken by telephone only, around the clock; the Duty Officer's log is not published and the "
              "program page did not answer the research (2026-11-09). The 2017 compilation for a legislative commission "
              "shows the reports can be extracted. Hotline only: no public channel."),
     "sources": ["mn-duty-officer", "mn-mpca-2017-release-data"]},
    {"id": "mn-mpca-release-reports", "agency": "Minnesota Pollution Control Agency",
     "name": "Minnesota Pollution Control Agency", "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": LAW, "basis_kind": "law", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "none", "records": False, "noun": "Release reports",
     "note": ("No web channel found: the agency receives the Duty Officer reports and the release sampling reports "
              "(due within 30 days, guidance wq-wwprm1-59) but publishes no list of releases; What's in My Neighborhood "
              "lists sites, not incidents. The route to the records is an information request."),
     "sources": ["mn-mpca-wimn", "mn-mpca-collection-release-guidance", "mn-mpca-information-requests"]},
    {"id": "mn-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "echo-sewer-overflow", "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass tables: one Minnesota report in the 2026-11-12 extract, from the Bois "
              "Forte Band's collection system (EPA permit MN0061310, 2024-06-18). Minnesota's own permittees report to "
              "the state, not through this tool."),
     "sources": ["mn-epa-sobe"]},
    {"id": "mn-mdh-lake-superior-beaches", "agency": "Minnesota Department of Health (Lake Superior beach program)",
     "name": "Minnesota Department of Health (Lake Superior beaches)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown", "records": False, "noun": "Beach advisories",
     "note": ("The Lake Superior beach program's site, mnbeaches.org, did not answer the project's client on 2026-11-14 "
              "(connection timed out) nor the research on 2026-11-09: its advisories, sample results and format were not "
              "seen, so the channel is not verified in the research. MDH notes advisories may follow sewage pipe breaks."),
     "sources": ["mn-mdh-lake-superior-beaches"]},
    {"id": "mn-mdh-beach-locator", "agency": "Minnesota Department of Health",
     "name": "Minnesota Department of Health (beach locator)", "channel_kind": "state_alert_page",
     "urls": ["https://www.health.state.mn.us/communities/environment/recreation/beaches/locator.html"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "local beach programs", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("MDH's beach locator links the Lake Superior program and local programs (Minneapolis Parks, Three Rivers, "
              "Ramsey County); inland beach monitoring is local and optional. Read for the research on 2026-11-09."),
     "sources": ["mn-mdh-beach-locator"]},
    {"id": "mn-mpca-hab", "agency": "Minnesota Pollution Control Agency",
     "name": "Minnesota Pollution Control Agency (harmful algae)", "channel_kind": "state_alert_page",
     "urls": ["https://www.pca.state.mn.us/business-with-us/harmful-algae-blooms-water-recreation-advisories"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "documents", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("MPCA's guidance on harmful algae and water recreation advisories and its reporting route: local bodies "
              "decide advisories; no statewide list of current bloom advisories (research 2026-11-09)."),
     "sources": ["mn-mpca-hab"]},
]


def base(**kw) -> dict:
    r = {"state": "MN", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "MN":
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        if oid == "mn-bois-forte":
            rows.append(finish(base(
                id=f"{oid}-overflow-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
                method=None, legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit", monitored=False,
                unmonitored_reason="feed_ingested", feed_source_id="echo-sewer-overflow", publishes="notices",
                noun="Report to the permitting authority", sources=["mn-epa-sobe"],
                note=(f"{name} holds an EPA permit and files its written overflow reports through NeT-SewerOverflow; "
                      "EPA publishes them in its overflow tables, read by the echo-sewer-overflow feed (one report, "
                      "2024-06-18)."))))
        own = OWN.get(oid)
        if own:
            rows.append(finish(base(id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit,
                                    legal_basis=LAW, basis_kind="law", **own)))
            continue
        private = " The duty binds a private sewer system owner as it binds a public one." if op.get("legal_form") in (
            "investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
            "campground or resort", "private club", "business or industrial", "institution",
            "facility (permittee not named)") else ""
        rows.append(finish(base(
            id=f"{oid}-public-notice", operator_id=oid, name=name, permit=permit, channel_kind="operator_page",
            urls=[], method=None, legal_basis=LAW, basis_kind="law", monitored=False, unmonitored_reason="other",
            publishes="unknown", records=False, noun="Public notice of a discharge", sources=["mn-law-stat-115-061"],
            note=(f"{name} must tell downstream users and the public of a discharge by the means it chooses (in person, "
                  "telephone, radio, social media or a web page) and post signs at affected public use areas; its "
                  f"own public channel was not searched individually.{private}"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "MN")
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
