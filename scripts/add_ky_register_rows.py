"""Kentucky rows of the notice register (data/notice-channels/ky.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ky_register_rows.py [--dry-run]

The law (research/ky/report.md §2.1 in the site repository; research/ky/profile.json):
  - 401 KAR 5:065 Section 2(5) (read on apps.legislature.ky.gov, 2026-11-03): reporting as 40 CFR 122.41, except that
    a spill, bypass, upset or other event of noncompliance that may present an imminent or substantial danger to the
    environment or public health is reported "immediately" by calling the Division of Water (the 24-hour environmental
    emergency line after hours). A report to the agency only, by telephone; the Division publishes no list. Kentucky's
    reporting system sent its sewer overflow and bypass reports to EPA's overflow tables for December 2025 and January
    2026 only.
  - No statute or regulation requiring public notice was found. Louisville MSD's advisory and SD1's alerts are their
    own (assumed to come from their consent decrees, not read).
Rows
  - Per operator (every Kentucky row of data/dischargers.json): <id>-division-notice, the 401 KAR 5:065 telephone notice
    to the Division of Water (no web channel), with the operator's reports in EPA's tables counted in the note.
  - Statewide: EPA's tables as the statewide feed (stopped after January 2026), the Division's own intake and the
    Environmental Response Team's incident records (records request only), the Division's HAB Viewer (feed) and the
    standing swimming advisories page (feed: ingest/ky_dow_swimming_advisories.py), ORSANCO's Ohio River bacteria pages (bot
    wall), the CSO annual reports (sent to the Division, not posted).
  - Operators' own channels: Louisville MSD's Overflow Advisory Level (feed), its water quality e-mail list and
    Louisville Metro's GovDelivery bulletins (e-mail only); SD1's Wet Weather Overflow Notification Program (e-mail and
    text to subscribers), its program page (watched) and its outfall signs; Lexington-Fayette (none found).
A rerun replaces every ky- row it makes. Validated before writing.
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
MSD_FEED = "ky-louisville-msd-overflow-advisory"
HAB_FEED = "ky-dow-hab-viewer"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
RULE_URL = "https://apps.legislature.ky.gov/law/kar/titles/401/005/065/"
LAW = "ky-law-401-kar-5-065"
Q_RULE = ('401 KAR 5:065 Section 2(5)(a): "If a spill or release of pollutants or contaminants, bypass, upset, or other '
          'event of noncompliance occurs that may present an imminent or substantial danger to the environment or the '
          'public health or welfare, the permittee shall immediately notify the Division of Water by calling the '
          'Division of Water in Frankfort ... or the appropriate regional field office"; (b) the 24-hour environmental '
          'emergency telephone number after hours; and the reports of 40 CFR 122.41(l)(6)')
MSD = "ky-louisville-msd"
SD1 = "ky-sd1"
MSD_PAGE = "https://louisvillemsd.org/overflowalert"
SD1_PAGE = "https://sd1.org/218/Wet-Weather-Overflow-Notification-Progra"
SWIM_PAGE = "https://eec.ky.gov/Environmental-Protection/Water/Monitor/Pages/Swimming-Advisories.aspx"
AGENCY = [
    {"id": "ky-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [ECHO], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): Kentucky's own reporting "
              "system sent its reports here for two months. 2026-11-04 extract: 43 Kentucky reports from 37 permits, "
              "started 2025-12-08 to 2026-01-08 and received in December 2025 (34) and January 2026 (9), none since; "
              "20 kept as reaching a water, 23 not (21 with no sign of a water, 2 saying none was reached). Every report "
              "is filed as a bypass; most are collection-system overflows. (research/ky/report.md §2.2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "ky-sobe-erule-state-system"]},
    {"id": "ky-dow-telephone-reports", "agency": "Kentucky Division of Water",
     "name": "Kentucky Division of Water (reports under 401 KAR 5:065)", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": Q_RULE, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False, "noun": "Report to the state",
     "note": ("The permittee's notice goes to the Division of Water by telephone only (the Frankfort office, a regional "
              "field office, or the 24-hour environmental emergency line), then in the federal written reports. The "
              "Division publishes no list of these reports; they reach the public through an open records request "
              f"(KRS 61.872). ({RULE_URL}; research/ky/report.md §2.1)"),
     "sources": [LAW]},
    {"id": "ky-dep-ert-incidents", "agency": "Kentucky Department for Environmental Protection, Emergency Response Team",
     "name": "Kentucky Environmental Response Team (incident records)", "channel_kind": "state_alert_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False,
     "note": ("The 24-hour environmental emergency line's incident records (the incident numbers in EPA's tables come "
              "from it) are kept by the Cabinet and released by records request only, by telephone only at intake; no "
              "public incident list was found. (research/ky/report.md §2.6)"),
     "sources": ["ky-dep-ert-incidents"]},
    {"id": "ky-dow-cso-annual-reports", "agency": "Kentucky Division of Water",
     "name": "Kentucky Division of Water (combined sewer overflow annual reports)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": "KPDES combined sewer overflow permits: annual report to the Division "
     "(the Division's template)", "basis_kind": "permit", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "none", "records": False,
     "note": ("The combined sewer permittees' annual reports are e-mailed to the Division on its template; the Division "
              "does not post them. No web channel found. SD1 posts its own on its website. (research/ky/report.md "
              "§2.2)"),
     "sources": ["ky-cso-annual-report-template"]},
    {"id": "ky-dow-hab-viewer", "agency": "Kentucky Division of Water", "name": "Kentucky Division of Water (HAB Viewer)",
     "channel_kind": "feed", "urls": ["https://watermaps.ky.gov/HABs"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": HAB_FEED,
     "publishes": "status", "noun": "Data feed",
     "note": ("The Division's harmful algal bloom map: each sampled lake's current status (Warning, toxins below the "
              "advisory level, none detected) with the Division's text, read from the map's public layer (5 points on "
              "2026-11-07: Old Springfield Reservoir under a recreational advisory). Blooms, not sewage. Voluntary. "
              "(research/ky/report.md §2.5)"),
     "sources": ["ky-dow-hab-viewer"]},
    {"id": "ky-dow-swimming-advisories", "agency": "Kentucky Division of Water and Department for Public Health",
     "name": "Kentucky Division of Water (swimming advisories)", "channel_kind": "feed", "urls": [SWIM_PAGE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "ky-dow-swimming-advisories", "publishes": "status",
     "noun": "Data feed",
     "note": ("Standing swimming advisories for E. coli \"in place for several years\" and \"in effect until further "
              "notice\": the Upper Cumberland River (Four Mile Bridge to Pineville, Wallins Creek to Harlan, Martins Fork, "
              "Catron Creek, Clover Fork, Straight Creek, Poor Fork, Looney Creek), the North Fork Kentucky River "
              "upstream of Chavies, and the Licking River from Banklick Creek to the Ohio with all of Banklick and Three "
              "Mile creeks; and general advice against full-body contact right after heavy rain, naming bypasses and "
              "combined sewer overflows. Prose with no dates: read by the ky-dow-swimming-advisories feed as standing "
              "advisories from the first read that listed them. Voluntary. (research/ky/report.md \u00a72.5)"),
     "sources": ["ky-dow-swimming-advisories"]},
    {"id": "ky-orsanco-bacteria", "agency": "Ohio River Valley Water Sanitation Commission (ORSANCO)",
     "name": "ORSANCO (Ohio River bacteria results)", "channel_kind": "group_results",
     "urls": ["https://www.orsanco.org/data/bacteria/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "results",
     "note": ("Weekly E. coli results for the Ohio River at Louisville and Cincinnati, April to October, and monthly PDF "
              "reports; the site answers 403 behind a Cloudflare check to plain clients (2026-11-03). "
              "(research/ky/report.md §2.5)"),
     "sources": ["ky-orsanco-bacteria"]},
]
OWN = [
    {"id": "ky-louisville-msd-overflow-advisory", "operator_id": MSD, "permit": "KY0022411",
     "name": "Louisville/Jefferson County Metropolitan Sewer District", "channel_kind": "feed", "urls": [MSD_PAGE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": MSD_FEED, "publishes": "status", "noun": "Data feed",
     "note": ("MSD's Overflow Advisory Level on every page of its site: MSD-01 'Wet Weather Overflows' (system-wide, "
              "avoid contact until 48 hours after the rain has stopped), MSD-02 notices of a discharge with its start "
              "time, address, receiving stream and amount, and 'Conditions are normal'. MSD removes old notices, so the "
              "feed keeps every one it sees. Assumed to come from MSD's consent decree (not read). "
              "(research/ky/report.md §2.3)"),
     "sources": ["ky-louisville-msd-overflow-advisory"]},
    {"id": "ky-louisville-msd-email-list", "operator_id": MSD, "permit": None,
     "name": "Louisville/Jefferson County Metropolitan Sewer District", "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "unknown", "signup_url": "https://louisvillemsd.org/",
     "note": ("The 'Water Quality Email List Signup' in the footer of MSD's site; what it sends was not seen (not "
              "subscribed). (research/ky/report.md §2.3)"),
     "sources": ["ky-louisville-msd-overflow-advisory"]},
    {"id": "ky-louisville-metro-govdelivery", "operator_id": MSD, "permit": None,
     "name": "Louisville Metro Government (GovDelivery bulletins)", "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "signup_url": "https://public.govdelivery.com/accounts/KYLOUISVILLE/subscriber/new",
     "note": ("Louisville Metro's e-mail bulletins carried an MSD community message on a pump-station failure "
              "(2025-02-21); occasional, by e-mail to subscribers. (research/ky/report.md §2.3)"),
     "sources": ["ky-msd-govdelivery"]},
    {"id": "ky-sd1-wet-weather-notification", "operator_id": SD1, "permit": "KY0021466",
     "name": "Sanitation District No. 1 of Northern Kentucky", "channel_kind": "email_list", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "signup_url": SD1_PAGE,
     "note": ("SD1's e-mail and text alerts (CivicPlus Notify Me) from May through October when 0.25 inch of rain is "
              "recorded in its service area or the Ohio River exceeds 38 feet; the advisories stand for 72 hours. Sent to "
              "subscribers only; the rule itself is public and the site applies its rainfall part at SD1's outfalls. "
              "(research/ky/report.md §2.3)"),
     "sources": ["ky-sd1-wet-weather-notification"]},
    {"id": "ky-sd1-program-page", "operator_id": SD1, "permit": "KY0021466",
     "name": "Sanitation District No. 1 of Northern Kentucky", "channel_kind": "operator_page", "urls": [SD1_PAGE],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "SD1's e-mail and text alert sign-up", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("The program page states the rule (0.25 inch, the Ohio River above 38 feet, 72 hours, May to October) and "
              "links the sign-up and a map of overflow areas; watched for a change of the rule. Voluntary."),
     "sources": ["ky-sd1-wet-weather-notification"]},
    {"id": "ky-sd1-cso-signs", "operator_id": SD1, "permit": "KY0021466",
     "name": "Sanitation District No. 1 of Northern Kentucky", "channel_kind": "lights_signs_page", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False,
     "note": ("Signs at SD1's combined sewer outfalls: \"If you see these signs, avoid nearby water during and after "
              "rainfall for at least 72 hours.\" Signs only; no page. (research/ky/report.md §2.3)"),
     "sources": ["ky-sd1-wet-weather-notification"]},
    {"id": "ky-lfucg-website", "operator_id": "ky-lfucg", "permit": None, "name": "Lexington-Fayette Urban County "
     "Government", "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False,
     "note": ("Lexington's sanitary sewers are under a consent decree (2008, modified 2015 and 2024) whose reports go to "
              "EPA and the Cabinet; no public overflow notice or list was found. No web channel found. "
              "(research/ky/report.md §2.3)"),
     "sources": ["ky-lfucg-sso-consent-decree"]},
]


def base(**kw) -> dict:
    r = {"state": "KY", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def report_counts(dis: list[dict]) -> dict[str, tuple[int, int]]:
    """operator id -> (its Kentucky reports in EPA's tables, those kept as reaching a water)."""
    allr, kept = Counter(), Counter()
    for f, key in ((ROOT / "data" / "build" / "events" / f"{FEED}.json", "records"),
                   (ROOT / "data" / "build" / "echo-sewer-overflow-dropped.json", "dropped")):
        if f.exists():
            for r in json.loads(f.read_text()).get(key, []):
                permit = r.get("npdes_permit") or r.get("permit") or ""
                if permit.startswith("KY"):
                    allr[permit] += 1
                    if key == "records":
                        kept[permit] += 1
    return {op["id"]: (sum(allr[p] for p in op.get("npdes_permits") or []),
                       sum(kept[p] for p in op.get("npdes_permits") or []))
            for op in dis if op.get("state") == "KY"}


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    reports = report_counts(dis)
    for op in dis:
        if op.get("state") != "KY":
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        n, k = reports.get(oid, (0, 0))
        count = (f"{n} report(s) in EPA's tables (2026-11-04 extract), {k} with evidence the discharge reached a water"
                 if n else "no report under its permits in EPA's tables (2026-11-04 extract)")
        cso = " A combined sewer permittee." if op.get("kind") == "cso" else ""
        own = {MSD: " MSD's own advisory is ky-louisville-msd-overflow-advisory.",
               SD1: " SD1's own alerts are ky-sd1-wet-weather-notification."}.get(oid, "")
        rows.append(finish(base(
            id=f"{oid}-division-notice", operator_id=oid, name=name, permit=ps[0] if ps else None,
            channel_kind="state_alert_page", urls=[], method=None, legal_basis=Q_RULE, basis_kind="law",
            monitored=False, unmonitored_reason="other", publishes="none", records=False,
            noun="Report to the state", sources=[LAW, "ky-sobe-erule-state-system"],
            note=(f"{name} must tell the Division of Water immediately, by telephone only, of a spill, bypass or overflow "
                  "that may endanger health or the environment (401 KAR 5:065 Section 2(5)); the Division publishes no "
                  "list. Kentucky's system sent such reports to EPA's overflow tables for December 2025 and January "
                  f"2026 only: {count}.{cso}{own} No public notice is required. The permit itself was not read: the "
                  "standard condition is assumed. (research/ky/report.md §2.1)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "KY")
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
