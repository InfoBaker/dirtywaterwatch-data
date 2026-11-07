"""Texas rows of the notice register (data/notice-channels/tx.json), made from the law and data/dischargers.json so they
are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_tx_register_rows.py [--dry-run]

The law (research/tx/report.md §2.1 in the site repository; research/tx/profile.json):
  - 30 TAC 305.125(9) and TCEQ's reporting page (https://www.tceq.texas.gov/compliance/investigation/ud-sso, answered
    200 on 2026-11-07): every unauthorized discharge or sanitary sewer overflow goes to the TCEQ regional office as soon
    as possible and within 24 hours, in writing within five working days, or in a monthly summary for small qualifying
    spills. A report to the agency; TCEQ publishes the reports in its Sanitary Sewer Overflows open data (data.texas.gov
    8kc5-95uk) in batches months later.
  - 30 TAC 319.302-319.303: the owner of a local government's facility notifies local government officials and local
    media within 24 hours of a spill likely to affect a drinking-water source, of 50,000 gallons or more near one or in
    a sensitive area, or of 100,000 gallons or more, with precautionary statements; nothing requires a web posting.
  - No CSO permits; Texas administers its own permits (TPDES), so EPA's overflow tables hold almost no Texas reports.
Rows
  - Per operator (every Texas row of data/dischargers.json): <id>-tceq-report, the report to the TCEQ regional office,
    read through TCEQ's open data (the tx-tceq-sso-opendata feed), with the operator's report count.
  - Statewide: the regional-office reports before publication (no web channel), the 319.302 notice to local officials and
    media (no web channel; it covers every local government's facility), TCEQ's open data as the statewide feed, EPA's
    overflow tables (8 Texas reports), Texas Beach Watch's layer (the tx-glo-beach-watch feed) and its e-mail alerts,
    the Galveston County Health District's beach advisory page (answers 403), Houston's monthly consent-decree reports
    (PDFs, not searched one by one), and the voluntary channels searched and not found (a freshwater bloom program,
    Swim Guide).
A rerun replaces every tx- row it makes. Validated before writing.
"""
from __future__ import annotations

import glob
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
FEED = "tx-tceq-sso-opendata"
BW_FEED = "tx-glo-beach-watch"
DATASET = "https://data.texas.gov/dataset/8kc5-95uk"
UDSSO = "https://www.tceq.texas.gov/compliance/investigation/ud-sso"
RULE_319 = "https://www.law.cornell.edu/regulations/texas/30-Tex-Admin-Code-SS-319-302"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
Q_REPORT = ("30 TAC 305.125(9) (TCEQ's reporting page): an unauthorized discharge or sanitary sewer overflow is reported to "
            "the TCEQ regional office \"as soon as possible but no later than 24 hours\", in writing \"within five "
            "working days\", or in a monthly summary for small qualifying spills")
Q_319 = ("30 TAC 319.302: the owner of a local government's facility notifies local government officials and local media "
         "within 24 hours of a spill likely to affect a drinking-water source, of 50,000 gallons or more near one or in a "
         "sensitive area, or of \"a spill of 100,000 gallons or more\"; 319.303 sets the precautionary statements")
AGENCY = [
    {"id": "tx-tceq-sso-opendata", "agency": "Texas Commission on Environmental Quality",
     "name": "Texas Commission on Environmental Quality (Sanitary Sewer Overflows open data)", "channel_kind": "feed",
     "urls": [DATASET], "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "note": ("TCEQ's table of every sewer overflow reported to its regional offices since September 2010 (56,545 rows "
              "read 2026-11-07, start dates 2010-09-02 to 2026-08-29): dates, volume, cause, source, county, the "
              "regulated entity and its permits, and a receiving water on about one row in four (a water's own name on about one in eight); no coordinates. "
              "Published in batches (rows last updated 2026-09-24, holding reports received to 2026-08-31); TCEQ "
              "receives a report a median of 2 days after the spill began. Voluntary: no law requires the table. "
              "(research/tx/report.md §2.2)"),
     "sources": ["tx-tceq-sso-opendata"]},
    {"id": "tx-tceq-regional-office-reports", "agency": "Texas Commission on Environmental Quality",
     "name": "Texas Commission on Environmental Quality (regional office reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_REPORT, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("The 24-hour report goes to the TCEQ regional office by telephone, in person or by fax (after hours a "
              "hotline), the written report within five working days. No web channel found publishes a report "
              "when it is made: it reaches the public only in the open data table, months later, or by a records "
              f"request. ({UDSSO}; research/tx/report.md §2.1)"),
     "sources": ["tx-tceq-ud-sso-page"]},
    {"id": "tx-local-officials-media-notice", "agency": "Local governments (30 TAC 319.302)",
     "name": "Notice to local officials and local media (30 TAC 319.302)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": Q_319, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "other", "publishes": "none", "records": False, "noun": "Notice to local officials",
     "note": ("Every local government's facility in Texas: the notice goes to local government officials and local "
              "media by hand delivery, fax, e-mail or telephone, with a copy to the TCEQ regional office within 48 "
              "hours, only above the thresholds. No web channel found: nothing requires a posting, and the media "
              f"decide whether to publish. ({RULE_319}; research/tx/report.md §2.1)"),
     "sources": ["tx-30tac-319-302"]},
    {"id": "tx-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "notices", "records": False,
     "note": ("EPA's sewer overflow and bypass event tables hold 8 Texas reports from 5 permits (2026-11-03): Texas "
              "permittees report to TCEQ, not through EPA's tool, so the table is not read for Texas; TCEQ's open data "
              "is the statewide record. No web channel found beyond these few reports. (research/tx/sources.json "
              "tx-epa-sobe)"),
     "sources": ["tx-epa-sobe"]},
    {"id": "tx-glo-beach-watch", "agency": "Texas General Land Office",
     "name": "Texas General Land Office (Texas Beach Watch map layer)", "channel_kind": "feed",
     "urls": ["https://www.texasbeachwatch.com/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": BW_FEED, "publishes": "results",
     "noun": "Data feed",
     "note": ("The program's layer of 174 coastal stations, each with its latest enterococcus sample and level (Low, "
              "Medium, High; High: \"An advisory for this beach is recommended\"); 12 Medium and no High on 2026-11-07. "
              "Beach advisories, not sewage. The BEACH Act grant program; local governments post the advisories. "
              "(research/tx/report.md §2.5)"),
     "sources": ["tx-glo-beach-watch"]},
    {"id": "tx-glo-beach-watch-alerts", "agency": "Texas General Land Office",
     "name": "Texas General Land Office (Texas Beach Watch e-mail alerts)", "channel_kind": "email_list",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "notices", "records": False,
     "signup_url": "https://www.texasbeachwatch.com/alertSignup.cfm",
     "note": ("E-mail alerts per beach (the sign-up page answered 200 on 2026-11-07); the same levels the layer shows, "
              "which is read as a feed. Voluntary."),
     "sources": ["tx-glo-beach-watch"]},
    {"id": "tx-gchd-beach-advisories", "agency": "Galveston County Health District",
     "name": "Galveston County Health District (beach water advisories)", "channel_kind": "local_health_page",
     "urls": ["https://www.gchd.org/about-us/environmental-health-services/air-water-pollution-services/"
              "beach-water-advisories"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "unknown",
     "note": ("The district's beach advisory page, linked from Texas Beach Watch, answers 403 to the project user agent "
              "(2026-11-07); whether it posts more than the program's levels is not known. Voluntary."),
     "sources": ["tx-gchd-beach-advisories"]},
    {"id": "tx-hab", "agency": "Texas Parks and Wildlife Department",
     "name": "Freshwater harmful algal bloom advisories (Texas)", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("No freshwater harmful algal bloom advisory program was found (search only, 2026-11-03); the Parks and "
              "Wildlife Department tracks red tide and fish kills on the coast. (research/tx/report.md §2.5)"),
     "sources": ["tx-hab"]},
    {"id": "tx-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": "No Swim Guide listing for Texas waters was found in the research (search only, 2026-11-03).",
     "sources": ["tx-watershed-groups"]},
]
# operators' own channels found in the research
OWN = [
    {"id": "tx-city-of-houston-sso-monthly", "operator_id": "tx-city-of-houston", "name": "City of Houston",
     "channel_kind": "operator_page", "urls": ["https://www.houstonpublicworks.org/wastewater-cd"], "method": "html",
     "legal_basis": ("Consent decree, United States and State of Texas v. City of Houston, No. 4:18-cv-03368 (S.D. "
                     "Tex., 2021), paragraph 61: a monthly summary of the prior month's sanitary sewer overflows"),
     "basis_kind": "permit", "monitored": True, "unmonitored_reason": None, "publishes": "documents",
     "records": False, "every_hours": 24, "noun": "Consent decree reports",
     "note": ("Houston Public Works' consent decree page (answered 200 on 2026-11-07) lists the monthly SSO reports as "
              "PDFs, January 2021 to September 2026 (SSO id, permit, address, whether waters were reached, gallons, "
              "cause, start and end times), a month ahead of TCEQ's table. Watched for new reports; the PDFs are not "
              "read into records: the same overflows reach TCEQ's table. (research/tx/sources.json tx-houston-sso-monthly)"),
     "sources": ["tx-houston-sso-monthly"]},
    {"id": "tx-city-of-austin-water-news", "operator_id": "tx-city-of-austin", "name": "City of Austin (Austin Water)",
     "channel_kind": "news_page", "urls": ["https://www.austintexas.gov/water/news"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Austin Water's news list (answered 200 on 2026-11-07) carries releases on large overflows (one of more "
              "than 100,000 gallons near E. Howard Lane, September 2026). Watched without records: the overflows reach "
              "TCEQ's table. Voluntary beyond the 30 TAC 319.302 media notice.")},
    {"id": "tx-city-of-dallas-news", "operator_id": "tx-city-of-dallas", "name": "City of Dallas (Dallas Water Utilities)",
     "channel_kind": "news_page", "urls": ["https://www.dallascitynews.net/"], "method": "html",
     "legal_basis": Q_319, "basis_kind": "law", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Notice to local media",
     "note": ("Dallas posts its overflow bulletins (heavy-rain overflows) and the TCEQ public notification forms it "
              "files under 30 TAC 319.302 (dallascityhall.com, govdelivery); the city news site answered 200 on "
              "2026-11-07. Watched without records.")},
    {"id": "tx-saws-website", "operator_id": "tx-san-antonio-water-system", "name": "San Antonio Water System",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("SAWS's site (https://www.saws.org/, 200 on 2026-11-07) gives no notice or list of overflows in a search "
              "of 2026-11-07; only news coverage was found. No web channel found.")},
    {"id": "tx-el-paso-water-website", "operator_id": "tx-el-paso-water-utilities-public-service-board",
     "name": "El Paso Water", "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False,
     "note": ("El Paso Water's site (https://www.epwater.org/, 200 on 2026-11-07) gives no notice or list of overflows "
              "in a search of 2026-11-07. No web channel found.")},
    {"id": "tx-city-of-fort-worth-water-website", "operator_id": "tx-city-of-fort-worth", "name": "City of Fort Worth",
     "channel_kind": "operator_page", "urls": ["https://www.fortworthtexas.gov/departments/water"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall",
     "publishes": "unknown",
     "note": ("The water department's site answers 403 to the project user agent (2026-11-07); a search found no public "
              "overflow notice page, only the utility's reporting procedure.")},
] + [
    {"id": f"{oid}-website", "operator_id": oid, "name": name, "channel_kind": "operator_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "unknown", "records": False,
     "note": f"{name}'s own pages were not searched individually (one of the ten operators with the most reports)."}
    for oid, name in (("tx-city-of-arlington", "City of Arlington"), ("tx-city-of-waco", "City of Waco"),
                      ("tx-city-of-corpus-christi", "City of Corpus Christi"),
                      ("tx-trinity-river-authority-of-texas", "Trinity River Authority of Texas"),
                      ("tx-city-of-baytown", "City of Baytown"))
]


def base(**kw) -> dict:
    r = {"state": "TX", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def report_counts() -> Counter:
    """regulated entity -> its rows in the saved TCEQ table (empty when absent)."""
    saved = sorted(p for p in glob.glob(str(ROOT / "data" / "raw" / FEED / "*.json"))
                   if not p.endswith(".meta.json") and not p.endswith("/meta.json"))
    if not saved:
        return Counter()
    doc = json.loads(Path(saved[-1]).read_text())
    return Counter((r.get("regulated_entity_number") or "").strip().upper() for pg in doc["pages"] for r in pg)


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    counts = report_counts()
    for op in dis:
        if op.get("state") != "TX":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        n = sum(counts[rn] for rn in op.get("tceq_entities") or [])
        count = (f"{n} report(s) in the table read 2026-11-07" if n
                 else "no report under its entities in the table read 2026-11-07")
        public = op.get("legal_form") in ("city", "town", "county", "authority", "special district")
        rows.append(finish(base(
            id=f"{oid}-tceq-report", operator_id=oid, name=name, permit=ps[0] if ps else None, channel_kind="feed",
            urls=[], method=None, legal_basis=Q_REPORT, basis_kind="law", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices", noun="Report to TCEQ",
            sources=["tx-tceq-ud-sso-page", "tx-tceq-sso-opendata"],
            note=(f"{name} reports each overflow to the TCEQ regional office; TCEQ publishes the reports in its open "
                  f"data, read by the {FEED} feed ({count})."
                  + (" As a local government's facility it also notifies local officials and media above the 30 TAC "
                     "319.302 thresholds (tx-local-officials-media-notice)." if public else "")
                  + " (research/tx/report.md §2.1)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "TX")
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
