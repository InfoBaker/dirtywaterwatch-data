"""New Mexico rows of the notice register (data/notice-channels/nm.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_nm_register_rows.py [--dry-run]

The law (research/nm/report.md §2.1 in the site repository; research/nm/profile.json):
  - 20.6.2.1203.A NMAC (read on law.cornell.edu, 2026-11-03): for "any discharge from any facility of oil or other water
    contaminant, in such quantity as may with reasonable probability injure or be detrimental to human health, animal
    or plant life, or property", "any person in charge of the facility shall orally notify the chief of the ground
    water quality bureau of the department" within 24 hours, in writing within one week, with a corrective-action
    report within 15 days. A report to the agency only; NMED publishes no list of these notices.
  - EPA Region 6 issues New Mexico's NPDES permits (New Mexico has no delegated program), so every permit carries the
    federal 24-hour and five-day noncompliance reports to EPA (40 CFR 122.41(l)(6)); EPA publishes those filed
    electronically in its overflow tables. On tribal land EPA administers the program (Region 9 for the Navajo Nation,
    Region 6 for the Pueblos and the Apache nations) and the state rule does not apply.
  - No duty to tell the public was found; no CSO permits.
Rows
  - Per operator (every New Mexico row of data/dischargers.json): <id>-epa-report, the permit's report to EPA, read
    through EPA's overflow tables (the echo-sewer-overflow feed), with the report count placed in New Mexico.
  - Statewide: the 20.6.2.1203 notice to NMED (by telephone, then in writing; no web channel), the reports filed with EPA
    Region 6 outside its electronic tool (not published), EPA's tables as the statewide feed; NMED's HABs Mapper layer
    (the nm-nmed-hab-mapper feed) and its HAB page and news releases (watched, without records), the Bureau of Land
    Management's bloom announcement for the Rio Grande del Norte, and the voluntary channels searched and not found
    (Rio Grande bacteria results, Swim Guide).
  - Operators' own pages, searched for the largest (2026-11-07): Albuquerque Bernalillo County Water Utility Authority,
    Santa Fe, Rio Rancho and Farmington (no notice of overflows found), Las Cruces (refuses the project user agent).
A rerun replaces every nm- row it makes. Validated before writing.
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
HAB_FEED = "nm-nmed-hab-mapper"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
RULE_URL = "https://www.law.cornell.edu/regulations/new-mexico/N-M-Admin-Code-SS-20.6.2.1203"
HAB_PAGE = "https://www.env.nm.gov/surface-water-quality/habs/"
LAW = "nm-law-20-6-2-1203"
Q_RULE = ('20.6.2.1203.A(1) NMAC: "As soon as possible after learning of such a discharge, but in no event more than '
          'twenty-four (24) hours thereafter, any person in charge of the facility shall orally notify the chief of the '
          'ground water quality bureau of the department"; (3) written notice within one week; (6) a corrective-action '
          'report within 15 days')
Q_PERMIT = ("NPDES permit {permit} (EPA Region 6): the 24-hour and five-day noncompliance reports of 40 CFR "
            "122.41(l)(6), to EPA")
Q_TRIBAL = ("NPDES permit {permit} (EPA {region}, tribal land): the 24-hour and five-day noncompliance reports of 40 CFR "
            "122.41(l)(6), to EPA")
AGENCY = [
    {"id": "nm-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): the reports New Mexico's "
              "permittees file electronically with EPA, and the Navajo Nation's under its own permits. 2026-11-04 "
              "extract: 2 reports under New Mexico permits, both the Town of Taos's (2026), and 6 Navajo Nation "
              "reports located in New Mexico (3 Shiprock, 2024 to 2025; 3 under Window Rock's permit, 2026, two of them "
              "at the lift station by Navajo, New Mexico); a median 4 days from start to receipt. EPA's collection-system table lists 55 New Mexico permits, Albuquerque, Santa Fe and Las "
              "Cruces among them, but no other has filed a report. (research/nm/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "nm-epa-sobe"]},
    {"id": "nm-nmed-discharge-notice", "agency": "New Mexico Environment Department",
     "name": "New Mexico Environment Department (discharge notices under 20.6.2.1203 NMAC)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_RULE, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("The notice goes to NMED's Ground Water Quality Bureau by telephone only at first, then in writing within a "
              "week, with a corrective-action report in 15 days; it binds every person in charge of a facility, public "
              "or private, off tribal land. NMED publishes no list of the notices and no web form was found; the notices "
              f"reach the public only through a records request. ({RULE_URL}; research/nm/report.md §2.1)"),
     "sources": [LAW]},
    {"id": "nm-epa-region-6-reports", "agency": "U.S. Environmental Protection Agency, Region 6",
     "name": "U.S. Environmental Protection Agency, Region 6 (noncompliance reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": "40 CFR 122.41(l)(6) and (m)(3): the permit's 24-hour and five-day "
     "noncompliance reports to the permitting authority", "basis_kind": "permit", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("Reports New Mexico's permittees send EPA Region 6 outside its electronic tool (by telephone, e-mail or "
              "letter) do not reach EPA's tables, and no web channel found publishes them. The electronic reporting "
              "deadline for sewer overflows passed on 2025-12-21, yet of the 55 New Mexico permits EPA lists with a "
              "collection system only Taos has filed. (research/nm/profile.json barriers)"),
     "sources": ["nm-epa-r6-permits", "nm-epa-sobe"]},
    {"id": "nm-nmed-hab-mapper", "agency": "New Mexico Environment Department",
     "name": "New Mexico Environment Department (HABs Mapper)", "channel_kind": "feed", "urls": [HAB_PAGE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": HAB_FEED, "publishes": "status", "noun": "Data feed",
     "note": ("NMED's harmful algal bloom advisory map: each monitored lake or river station's latest result and its "
              "status (WATCH, WARNING or DANGER, or monitored with no advisory), read from the map's public layer "
              "(40 stations on 2026-11-07: 8 WATCH, 6 WARNING). Blooms, not sewage. Advisories follow NMED's HAB "
              "Advisory Guidance; no law requires them. (research/nm/report.md §2.5)"),
     "sources": ["nm-nmed-hab-mapper"]},
    {"id": "nm-nmed-hab-page", "agency": "New Mexico Environment Department",
     "name": "New Mexico Environment Department (harmful algal blooms page)", "channel_kind": "state_alert_page",
     "urls": [HAB_PAGE], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True,
     "unmonitored_reason": None, "publishes": "link_only", "link_text": "NMED's HAB advisory map", "records": False,
     "every_hours": 24, "noun": "Voluntary page",
     "note": ("NMED's bloom page (answered 200 on 2026-11-07) explains the WATCH, WARNING and DANGER advisories and links "
              "the advisory map; watched for a new map address, since the map's layer is named for its upload "
              "(Upload_Data_May2026). Blooms, not sewage. Voluntary."),
     "sources": ["nm-nmed-hab-mapper"]},
    {"id": "nm-nmed-news-releases", "agency": "New Mexico Environment Department",
     "name": "New Mexico Environment Department (news releases)", "channel_kind": "news_page",
     "urls": ["https://www.env.nm.gov/news-releases/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("NMED's news list (answered 200 on 2026-11-07): algal bloom advisories issued and lifted (a DANGER "
              "advisory at Charette Lake in 2026), boil water advisories and monthly enforcement summaries; no sewage "
              "overflow notice was seen. Watched without records: the bloom map is read as a feed, and a lift reads like "
              "an issue. Voluntary."),
     "sources": ["nm-nmed-hab-mapper"]},
    {"id": "nm-blm-rio-grande-del-norte-habs", "agency": "Bureau of Land Management, Taos Field Office",
     "name": "Bureau of Land Management (Rio Grande del Norte bloom announcement)", "channel_kind": "shared_site",
     "urls": ["https://www.blm.gov/announcement/blm-notifies-public-harmful-algal-blooms-within-rio-grande-del-norte-"
              "national-monument"], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True,
     "unmonitored_reason": None, "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The Bureau's announcement of blooms in the Rio Grande within the Rio Grande del Norte National Monument "
              "(Orilla Verde, Taos Junction Bridge), linked from NMED's map; answered 200 on 2026-11-07. Blooms, not "
              "sewage. Voluntary."),
     "sources": ["nm-nmed-hab-mapper"]},
    {"id": "nm-rio-grande-bacteria", "agency": "Rio Grande (Albuquerque reach) bacteria sampling",
     "name": "Rio Grande bacteria sampling (Albuquerque reach)", "channel_kind": "group_results", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("No public program posting E. coli results for the Rio Grande through Albuquerque was found (search, "
              "2026-11-03); New Mexico has no state beach monitoring program. (research/nm/report.md §2.5)"),
     "sources": ["nm-rio-grande-bacteria"]},
    {"id": "nm-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "No Swim Guide affiliate or New Mexico listing was found (search only, 2026-11-03). (research/nm/report.md §2.5)",
     "sources": ["nm-swim-guide"]},
]
# operators' own pages, searched for the largest (2026-11-07; the rest not searched one by one)
OWN = [
    {"id": "nm-abcwua-website", "operator_id": "nm-abcwua", "name": "Albuquerque Bernalillo County Water Utility Authority",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("The Authority's site (https://www.abcwua.org/, 200 on 2026-11-07; its news address leads to the home page) "
              "carries no notice or list of overflows; the press reported that it told NMED, EPA and the Pueblo of "
              "Isleta of one overflow case by case, and a 2024 EPA settlement over Rio Grande discharges. No web channel "
              "found. (research/nm/report.md §2.3)"),
     "sources": ["nm-abcwua"]},
    {"id": "nm-city-of-santa-fe-website", "operator_id": "nm-city-of-santa-fe", "name": "City of Santa Fe",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "The city's site (https://santafenm.gov/, 200 on 2026-11-07) gives no notice or list of overflows. No web channel found."},
    {"id": "nm-city-of-rio-rancho-website", "operator_id": "nm-city-of-rio-rancho", "name": "City of Rio Rancho",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "The city's site (https://rrnm.gov/, 200 on 2026-11-07) gives no notice or list of overflows. No web channel found."},
    {"id": "nm-city-of-farmington-website", "operator_id": "nm-city-of-farmington", "name": "City of Farmington",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("The city's site (https://farmingtonnm.gov/, 200 on 2026-11-07) gives no notice or list of overflows. No web "
              "channel found.")},
    {"id": "nm-city-of-las-cruces-website", "operator_id": "nm-city-of-las-cruces", "name": "City of Las Cruces",
     "channel_kind": "operator_page", "urls": ["https://lascruces.gov/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "unknown",
     "note": ("The city's site answers 403 to the project user agent (2026-11-07); whether Las Cruces Utilities posts "
              "overflows is not known.")},
]


# reports placed in New Mexico under another state's operator row (review 2026-11-07 P3-11)
WINDOW_ROCK = {"nm-navajo-tribal-utility-authority": (
    " Three more reports under the Authority's Window Rock permit (NN0021555, Arizona's row) lie in New Mexico and are "
    "placed there: two at the lift station by Navajo, New Mexico, and a line washed out east of Fort Defiance (2026-08).")}


def base(**kw) -> dict:
    r = {"state": "NM", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def report_counts(dis: list[dict]) -> dict[str, int]:
    """operator id -> its reports in EPA's tables placed in New Mexico (the events and dropped files; empty when absent)."""
    by_permit: Counter = Counter()
    for f, key in ((ROOT / "data" / "build" / "events" / f"{FEED}.json", "records"),
                   (ROOT / "data" / "build" / "echo-sewer-overflow-dropped.json", "dropped")):
        if f.exists():
            for r in json.loads(f.read_text()).get(key, []):
                permit = r.get("npdes_permit") or r.get("permit") or ""
                if (r.get("state") or (r.get("raw") or {}).get("state") or permit[:2]) == "NM":
                    by_permit[permit] += 1
    return {op["id"]: sum(by_permit[p] for p in op.get("npdes_permits") or []) for op in dis if op.get("state") == "NM"}


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    reports = report_counts(dis)
    for op in dis:
        if op.get("state") != "NM":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        permit = ps[0] if ps else None
        n = reports.get(oid, 0)
        count = (f"{n} report(s) placed in New Mexico in the 2026-11-04 extract" if n else
                 "no report under its permits in the 2026-11-04 extract")
        if op.get("legal_form") == "tribal" or any(p.startswith("NN") for p in ps):
            reg = "Region 9, the Navajo Nation" if any(p.startswith("NN") for p in ps) else "Region 6"
            rows.append(finish(base(
                id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
                method=None, legal_basis=Q_TRIBAL.format(permit=permit, region=reg), basis_kind="permit",
                monitored=False, unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices",
                noun="EPA report", sources=["nm-epa-sobe"],
                note=(f"{name}'s permits are EPA's on tribal land: reports go to EPA, which publishes those filed "
                      f"electronically in its overflow tables, read by the {FEED} feed ({count}). New Mexico's notice "
                      "rule does not apply on tribal land." + WINDOW_ROCK.get(oid, "") + " (research/nm/report.md §3)"))))
            continue
        private = (" The permit and the state rule bind the holder, public or private."
                   if op.get("legal_form") not in (None, "city", "town", "county", "authority", "special district",
                                                   "federal facility", "state facility") else "")
        rows.append(finish(base(
            id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices", noun="EPA report",
            sources=["nm-epa-sobe", "nm-epa-r6-permits"],
            note=(f"{name} reports noncompliance to EPA Region 6 under its permit; EPA publishes the reports filed "
                  f"electronically in its overflow tables, read by the {FEED} feed ({count}). Its 20.6.2.1203 notice to "
                  f"NMED is not published (nm-nmed-discharge-notice).{private} No public notice is required. The "
                  "permit itself was not read: the federal standard condition is assumed. (research/nm/report.md §2.1)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "NM")
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
