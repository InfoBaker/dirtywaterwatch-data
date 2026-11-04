"""Washington rows of the notice register (data/notice-channels/wa.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_wa_register_rows.py [--dry-run]

The law (research/wa/report.md §2.1 in the site repository; RCW read on app.leg.wa.gov 2026-11-03):
  RCW 90.48.636(1) (2025 c 315): "By July 1, 2026, the department must develop and publish a public-facing website
  that includes ... notices of the locations where sewage spills occur that are reported to the department under
  individual water quality permits for discharges that contain sewage. The department must post on the website notice
  of the reported sewage spill." The duty to publish is Ecology's; it covers every holder of an individual permit,
  public or private. The operator's duty is its permit's: report each spill to Ecology (the permit's noncompliance
  notification; permit texts not read). The bill's e-mail notification system, map format and annual report were cut.
  CSO permittees owe public notification under their permits (the nine minimum controls of the federal CSO Control
  Policy); King County's and Seattle's is the CSO status map, Spokane's its CSOUpdate page.

Rows
  - Per operator (every Washington row of data/dischargers.json except kind cso_closed_or_none, a construction
    stormwater permit EPA's CSO inventory lists): <id>-ecology-spill-report (permit basis: the report to Ecology, made
    public through Ecology's list, read by the wa-ecology-sewage-spills feed). JBLM's permit is EPA's: its row is
    wa-jblm-epa-report, read through EPA's eRule tables (echo-sewer-overflow).
  - Per CSO operator (kind cso): <id>-cso-public-notification (permit basis): King County and Seattle through the
    status file the wa-kc-cso-status-csv feed reads; Spokane's page refuses the project user agent (bot_wall); the
    others not searched (not_verified). King County and Seattle also post signs at their outfalls (<id>-cso-signs).
  - Agency and voluntary rows: AGENCY below.
A rerun replaces every wa- row it makes and keeps rows it does not make (none today). Validated before writing.
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
CHECKED = "2026-11-04"
SPILLS = "https://ecology.wa.gov/water-shorelines/water-quality/wastewater/sewage-spills"
LAYER = ("https://gis.ecology.wa.gov/hosting/rest/services/Hosted/"
         "survey123_48de962d0dea40eb9485805510a40b84_results/FeatureServer/0")
FEED = "wa-ecology-sewage-spills"
KC_FEED = "wa-kc-cso-status-csv"
KC_PAGE = "https://kingcounty.gov/en/dept/dnrp/waste-services/wastewater-treatment/sewer-system-services/cso-status"
KC_CSV = "https://your.kingcounty.gov/dnrp/library/wastewater/cso/img/CSO_metadata.CSV"
ECHO_ZIP = "https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip"
LAW = "wa-rcw-90-48-636"
Q_LAW = ('RCW 90.48.636(1): Ecology "must post on the website notice of the reported sewage spill" for every sewage '
         'spill "reported to the department under individual water quality permits for discharges that contain sewage"')
Q_PERMIT = ("Individual permit {permit}: the permittee reports each spill to Ecology under the permit's noncompliance "
            "notification (permit text not read); " + Q_LAW)
Q_CSO = ("NPDES permit {permit}: CSO public notification, one of the nine minimum controls of the federal CSO Control "
         "Policy (59 FR 18688, 1994), with WAC 173-245 for CSO reduction and reporting; permit text not read")
SPOKANE_PAGE = "https://sewerfinder.spokanecity.org/CSOUpdate"
AGENCY = [
    {"id": "wa-ecology-sewage-spills", "agency": "Washington State Department of Ecology",
     "name": "Washington State Department of Ecology (sewage spills)", "channel_kind": "state_alert_page",
     "urls": [SPILLS, LAYER], "method": "json", "legal_basis": Q_LAW + "; content RCW 90.48.636(1)(a)-(g), final "
     "information within a reasonable time after the spill ends (2); RCW 90.48.632 defines a sewage spill",
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": FEED,
     "publishes": "notices", "noun": "State page",
     "note": ("Ecology's statutory list of sewage spills reported under individual permits (public or private), live "
              "since mid-2026: start, end once known, volume, level of treatment, location and the area potentially "
              "affected, with a link to the operator's report. Read through the table's public layer, which answered "
              "the project user agent on 2026-11-04. Ecology aims to post within five working days; the statute sets "
              "no deadline. No coordinates; no CSO events from operators' routine wet-weather reports were seen apart "
              "from one. (research/wa/report.md §2.2)"),
     "sources": [FEED, LAW]},
    {"id": "wa-ecology-spill-email-alerts", "agency": "Washington State Department of Ecology",
     "name": "Washington State Department of Ecology (sewage spill alerts)", "channel_kind": "email_list",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "note": ("No e-mail or text alert for sewage spills exists: the notification system in the bill (HB 1670 / "
              "SB 5450, 2025) was cut from the law as passed, with the map format and the annual report. The gap is a "
              "legislative one. (research/wa/report.md §2.1)"),
     "sources": [LAW]},
    {"id": "wa-ecology-beach-program", "agency": "Washington State Department of Ecology (BEACH Program)",
     "name": "Washington BEACH Program (Ecology and the Department of Health)", "channel_kind": "state_alert_page",
     "urls": ["https://ecology.wa.gov/water-shorelines/water-monitoring-research/swimming-safety"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "link_only", "link_text": "the beach list and e-mail updates", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("Swimming-safety page of the BEACH Program (marine swimming beaches, Memorial Day to Labor Day; local "
              "health departments issue the advisories). It links the beach list, the e-mail updates and the "
              "Department of Health's shellfish map; no data service was found. Answered 200 to the project user "
              "agent on 2026-11-04 (ecology.wa.gov/beach redirects here). Filed voluntary: the research did not trace "
              "the program's statute. (research/wa/report.md §2.5)"),
     "sources": ["wa-beach-program"]},
    {"id": "wa-ecology-beach-emails", "agency": "Washington State Department of Ecology (BEACH Program)",
     "name": "Washington BEACH Program e-mail updates", "channel_kind": "email_list", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "email_only",
     "publishes": "notices", "signup_url": "https://public.govdelivery.com/accounts/WAECY/subscriber/new?topic_id=WAECY_22",
     "note": ("E-mail updates about beach advisories and closures (GovDelivery topic linked from the BEACH page on "
              "2026-11-04). Voluntary. Not signed up. (research/wa/report.md §2.5)"),
     "sources": ["wa-beach-program"]},
    {"id": "wa-doh-shellfish-safety-map", "agency": "Washington State Department of Health",
     "name": "Washington State Department of Health (Shellfish Safety Map)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "unknown",
     "note": ("Recreational shellfish closures, including emergency closures after sewage spills, which Ecology's page "
              "points to (https://fortress.wa.gov/doh/biotoxin/biotoxin.html, a map; answered 200 on 2026-11-04). "
              "Its data service was not examined: not verified in the research. Filed voluntary: the closure rule was "
              "not read. (research/wa/report.md §2.5)"),
     "sources": ["wa-doh-shellfish-closures"]},
    {"id": "wa-nwtoxicalgae", "agency": "Washington State Department of Ecology and King County",
     "name": "Washington State Toxic Algae", "channel_kind": "state_alert_page",
     "urls": ["https://www.nwtoxicalgae.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "results", "records": False, "every_hours": 24,
     "noun": "Voluntary page",
     "note": ("Freshwater bloom reports and toxin results by lake (Ecology's freshwater algae program, run with King "
              "County). Blooms, not sewage. Home page answered 200 to the project user agent on 2026-11-04; its data "
              "was not read. Voluntary. (research/wa/report.md §2.5)"),
     "sources": ["wa-ecology-freshwater-algae"]},
    {"id": "wa-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": ["https://www.theswimguide.org/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "app_only", "publishes": "results", "records": False,
     "noun": "Swim Guide listing",
     "note": ("Swim Guide listings for Washington (Puget Soundkeeper is an affiliate). Voluntary republisher of local "
              "beach results. The site answered 200 to the project user agent on 2026-11-04 but shows its listings in "
              "a script app with no API: not read. (research/wa/profile.json advisories)"),
     "sources": ["wa-beach-program"]},
    {"id": "wa-puget-soundkeeper", "agency": "Puget Soundkeeper Alliance", "name": "Puget Soundkeeper",
     "channel_kind": "group_results", "urls": ["https://pugetsoundkeeper.org/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "unknown", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Waterkeeper for Puget Sound, the Duwamish and Seattle's lakes, the receiving waters of King County's and "
              "Seattle's CSOs. Home page read (200 on 2026-11-04); no overflow or bacteria results page was found on "
              "it. Voluntary. (research/wa/profile.json advisories)"),
     "sources": ["wa-beach-program"]},
    {"id": "wa-spokane-riverkeeper", "agency": "Spokane Riverkeeper", "name": "Spokane Riverkeeper",
     "channel_kind": "group_results", "urls": ["https://www.spokaneriverkeeper.org/"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "unknown", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("Riverkeeper for the Spokane River, the receiving water of Spokane's CSOs. Home page read (200 on "
              "2026-11-04); no overflow or bacteria results page was found on it. Voluntary. "
              "(research/wa/profile.json advisories)"),
     "sources": ["wa-spokane-cso-update"]},
]


def base(**kw) -> dict:
    r = {"state": "WA", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    rows, left = [], []
    for op in dis:
        if op.get("state") != "WA":
            continue
        if op.get("kind") == "cso_closed_or_none":
            left.append((op["id"], "not a sewer system (a construction stormwater permit EPA's CSO inventory lists)"))
            continue
        oid, name, permit = op["id"], op["name"], op.get("npdes_permit")
        private = " The permit binds the holder, public or private." if op.get("legal_form") in (
            "investor-owned utility", "member-owned utility", "homeowners' association", "mobile-home park",
            "campground or resort", "private club", "business or industrial", "institution",
            "facility (permittee not named)") else ""
        if oid == "wa-jblm":
            rows.append(finish(base(
                id="wa-jblm-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed",
                urls=[], method=None, legal_basis=("NPDES permit WA0021954 (EPA Region 10, a federal facility): "
                                                          "noncompliance reports to EPA (40 CFR 122.41(l)(6)-(7))"),
                basis_kind="permit", monitored=False, unmonitored_reason="feed_ingested",
                feed_source_id="echo-sewer-overflow", publishes="notices", noun="EPA report",
                sources=["wa-epa-sobe"],
                note=("JBLM's spill reports go to EPA, which publishes them in its eRule overflow tables "
                      f"({ECHO_ZIP}, read by the echo-sewer-overflow feed); Ecology's list covers spills reported to Ecology. Most of the base's "
                      "reports name no receiving water. (research/wa/report.md §2.3)"))))
            continue
        rows.append(finish(base(
            id=f"{oid}-ecology-spill-report", operator_id=oid, name=name, permit=permit,
            channel_kind="state_alert_page", urls=[SPILLS, LAYER], method="json",
            legal_basis=Q_PERMIT.format(permit=permit), basis_kind="permit", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices", noun="State page",
            sources=[FEED, LAW],
            note=(f"{name} reports its spills to Ecology, which posts each one on its sewage spill list (read by the "
                  f"{FEED} feed).{private} (research/wa/report.md §2.1)"))))
        if op.get("kind") != "cso":
            continue
        cso = dict(id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit=permit,
                   legal_basis=Q_CSO.format(permit=permit), basis_kind="permit", sources=["wa-wac-173-245"])
        if oid in ("wa-king-county-west-point", "wa-seattle-spu"):
            rows.append(finish(base(**cso, channel_kind="operator_page", urls=[KC_PAGE, KC_CSV], method="html",
                                    monitored=False, unmonitored_reason="feed_ingested", feed_source_id=KC_FEED,
                                    publishes="status", noun="CSO status map",
                                    note=("King County's CSO status map and its file, shared by King County and "
                                          "Seattle Public Utilities: the status of each outfall every 10 minutes "
                                          "(overflowing now, in the last 48 hours, no recent overflow, no data), read "
                                          f"by the {KC_FEED} feed. The page: \"Stay out of the water near combined "
                                          "sewer overflow outfalls for 48 hours after a combined sewer overflow "
                                          "occurs.\" (research/wa/report.md §2.3)"))))
            rows.append(finish(base(
                id=f"{oid}-cso-signs", operator_id=oid, name=name, permit=permit, channel_kind="lights_signs_page",
                urls=[], method=None, legal_basis=Q_CSO.format(permit=permit), basis_kind="permit", monitored=False,
                unmonitored_reason="other", publishes="none", records=False, noun="Outfall signs",
                sources=["wa-kc-cso-status-csv"],
                note=("Warning signs at the CSO outfalls (research/wa/dischargers.json); signs only, nothing published "
                      "on the web beyond the status map."))))
        elif oid == "wa-spokane":
            rows.append(finish(base(**cso, channel_kind="operator_page", urls=[], method=None, monitored=False,
                                    unmonitored_reason="bot_wall", publishes="status", noun="CSO status page",
                                    note=(f"Spokane's real-time CSO monitoring page ({SPOKANE_PAGE}) flashes a site "
                                          "while an overflow is occurring or has occurred in the last 48 hours and "
                                          "shows its start time (search snippet). It answers 403 (Incapsula) to the "
                                          "project user agent (2026-11-04); not worked around. "
                                          "(research/wa/report.md §2.3)"))))
        else:
            rows.append(finish(base(**cso, channel_kind="operator_page", urls=[], method=None, monitored=False,
                                    unmonitored_reason="other", publishes="unknown", records=False,
                                    noun="CSO public notification",
                                    note=(f"No URL known (not searched): {name}'s CSO public notification was not "
                                          "researched. Its spills reported to Ecology reach the public record on "
                                          "Ecology's list. (research/wa/report.md §2.3)"))))
    return rows, left


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows, left = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "WA")
    doc = merge(doc, rows, drop)
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        NP.save_register(doc["channels"], REGISTER)
    return {"rows": len(rows), "left_out": left,
            "barriers": dict(Counter(r["barrier"] or ("review" if r.get("barrier_review") else "none") for r in rows)),
            "by_basis": dict(Counter(r["basis_kind"] for r in rows))}


if __name__ == "__main__":
    rep = run("--dry-run" in sys.argv[1:])
    print(json.dumps(rep, indent=1))
