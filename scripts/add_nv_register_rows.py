"""Nevada rows of the notice register (data/notice-channels/nv.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_nv_register_rows.py [--dry-run]

The law (research/nv/report.md §2.1 in the site repository; research/nv/expansion-research.md):
  - NRS 445A.467 (added in 2025 by SB 276; official chapter read 2026-11-09, revision of 2026-04-15): "Any city, county,
    unincorporated town, general improvement district, wastewater district or water authority of this State that has
    powers, duties or jurisdiction within the area of the incident that has been notified or is aware of the incident
    shall notify the Division electronically on the Internet website of the Division or by telephone"; NDEP notifies an
    Indian tribe that may be affected. No deadline, no public notice, no published list.
  - NDEP issues Nevada's NPDES permits: the permit's 24-hour and five-day noncompliance reports go to NDEP
    (40 CFR 122.41(l)(6)); NDEP publishes no list. The hazardous-substance release rules (NAC 445A.345 to 445A.348) are
    a lead whose scope over sewage was not confirmed (the chapter could not be read whole).
  - No CSO permits; EPA's overflow tables hold no Nevada report and no Nevada collection system (2026-11-12 extracts).
Rows
  - Per operator (every Nevada row of data/dischargers.json): <id>-ndep-report, the report to NDEP (the statute's notice
    for a local government, the permit's report for every permit holder), not published.
  - Statewide: NDEP's intake (online form or telephone), EPA's tables (none), the state parks' HAB advisory page (the
    nv-state-parks-hab feed), NDEP's HAB program page (watched), the statewide HAB dashboard (Power BI), the weekly HAB
    e-mail list, NPS Lake Mead's bloom page (watched), Lake Tahoe's nearshore bacteria monitoring (NTCD), NDEP's water
    quality data warehouse and public document search, SNWA's watershed monitoring (by e-mail request), Swim Guide.
  - Operators' own channels: the City of Reno's spill line (Environmental Control).
A rerun replaces every nv- row it makes. Validated before writing.
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
STATUTE = "https://www.leg.state.nv.us/NRS/NRS-445A.html#NRS445ASec467"
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
PARKS = "https://parks.nv.gov/about/hab-advisory"
HAB_PAGE = "https://ndep.nv.gov/water/rivers-streams-lakes/water-quality-monitoring/harmful-algal-bloom-program"
DASHBOARD = ("https://app.powerbigov.us/view?r=eyJrIjoiZDIxMmZiZjktMTlhMS00ZTgxLWFmNTAtY2Y5Yzc3NzE0MTU4IiwidCI6ImU0YTM0"
             "MGU2LWI4OWUtNGU2OC04ZWFhLTE1NDRkMjcwMzk4MCJ9")
Q_LAW = ('NRS 445A.467(1)(a): a city, county, unincorporated town, general improvement district, wastewater district or '
         'water authority "that has been notified or is aware of the incident shall notify the Division electronically '
         'on the Internet website of the Division or by telephone"')
Q_PERMIT = ("NPDES permit {permit} (NDEP): the 24-hour and five-day noncompliance reports of 40 CFR 122.41(l)(6), to "
            "NDEP")
LOCAL = {"city", "county", "town", "special district", "authority"}
AGENCY = [
    {"id": "nv-ndep-sewage-notice", "agency": "Nevada Division of Environmental Protection",
     "name": "Nevada Division of Environmental Protection (sewage discharge notices under NRS 445A.467)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_LAW, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state", "sources": ["nv-law-sb276-2025", "nv-ndep-environmental-activities"],
     "note": ("The notice goes to NDEP through its online intake (Nevada Environmental Activities, a reporting form "
              "and account login) or by telephone; no deadline is set, and NDEP passes it to an Indian tribe that may "
              "be affected. NDEP publishes no list of the notices and no public view of the intake was found: no web "
              f"channel found. ({STATUTE}; research/nv/expansion-research.md)")},
    {"id": "nv-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "none", "records": False, "sources": ["nv-epa-sobe"],
     "note": ("EPA's sewer overflow and bypass tables hold no Nevada report and list no Nevada collection system "
              f"(current and all-versions extracts of 2026-11-12, {ECHO}); Nevada's permittees report to NDEP. "
              "Checked again at each state build; the state is not read from these tables.")},
    {"id": "nv-state-parks-hab", "agency": "Nevada Division of State Parks",
     "name": "Nevada Division of State Parks (HAB advisories)", "channel_kind": "feed", "urls": [PARKS],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": "nv-state-parks-hab", "publishes": "status",
     "noun": "Data feed", "sources": ["nv-state-parks-hab"],
     "note": ("The parks' HAB Advisory page: the waters in state parks under a HAB Watch, Warning or Danger advisory, "
              "each with its update date (four Watch advisories in the Internet Archive's copy of 2026-08-13; the "
              "expansion research read Lahontan's November 2 downgrade to Warning and October 5 Watch notices for Rye "
              "Patch and Wild Horse). Blooms, not sewage. Voluntary. The host did not answer the collector's ordinary "
              "requests on 2026-11-14 (ports 443 and 80, as ndep.nv.gov) and 2026-11-15 (connect timeout): the feed "
              "is built but has no successful current read, and its health stays not ok until one succeeds.")},
    {"id": "nv-ndep-hab-program", "agency": "Nevada Division of Environmental Protection",
     "name": "Nevada Division of Environmental Protection (harmful algal bloom program)",
     "channel_kind": "state_alert_page", "urls": [HAB_PAGE], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "metadata_only": True, "publishes": "link_only",
     "link_text": "the statewide HAB dashboard and the weekly e-mail list", "records": False, "every_hours": 24,
     "noun": "Voluntary page", "sources": ["nv-ndep-hab-dashboard"],
     "note": ("NDEP's bloom program page (read 2026-11-09 in the expansion research) links the statewide dashboard and "
              "the weekly e-mail update; watched for a new dashboard address or a data download. Blooms, not sewage.")},
    {"id": "nv-ndep-hab-dashboard", "agency": "Nevada Division of Environmental Protection",
     "name": "Nevada harmful algal bloom dashboard (Power BI)", "channel_kind": "state_alert_page",
     "urls": [DASHBOARD], "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "image_only", "publishes": "status", "records": False, "sources": ["nv-ndep-hab-dashboard"],
     "note": ("The state's only statewide bloom status, shown in a Power BI report that draws the data as a picture: the "
              "page is a script shell with no rows, no download and no data endpoint (expansion research 2026-11-09). Not read; a supported export is "
              "an owner request. Blooms, not sewage.")},
    {"id": "nv-ndep-hab-email", "agency": "Nevada Division of Environmental Protection",
     "name": "Nevada harmful algal bloom weekly e-mail update", "channel_kind": "email_list", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "email_only", "publishes": "status", "records": False, "sources": ["nv-ndep-hab-dashboard"],
     "note": "NDEP's weekly bloom update goes by e-mail to subscribers; no subscription was made. Blooms, not sewage."},
    {"id": "nv-nps-lake-mead-habs", "agency": "National Park Service, Lake Mead National Recreation Area",
     "name": "National Park Service, Lake Mead (harmful algal blooms page)", "channel_kind": "shared_site",
     "urls": ["https://www.nps.gov/lake/planyourvisit/harmful-blue-green-algae-blooms-habs.htm"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "metadata_only": True,
     "publishes": "notices", "records": False, "every_hours": 24, "noun": "Voluntary page",
     "sources": ["nv-nps-lake-mead-habs"],
     "note": ("The park's bloom page: general advice, intermittent monitoring and public reports; its page date "
              "(November 2, 2026) is not the date of a new advisory. Watched without records for a dated alert. Lake "
              "Mead and Lake Mohave are shared with Arizona. Blooms, not sewage.")},
    {"id": "nv-ntcd-tahoe-nearshore", "agency": "Nevada Tahoe Conservation District",
     "name": "Nevada Tahoe Conservation District (Nearshore Human Health monitoring)", "channel_kind": "group_results",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "documents", "records": False, "sources": ["nv-tahoe-beaches"],
     "note": ("Lake Tahoe's nearshore bacteria monitoring (https://ntcd.org/nearshorehumanhealth/) is described with a "
              "2023 report; its program page on Lake Tahoe Info gave no readable results (2026-11-09). No current "
              "station results or closures were found: no web channel found for current results.")},
    {"id": "nv-ndep-water-quality-data", "agency": "Nevada Division of Environmental Protection",
     "name": "Nevada Division of Environmental Protection (Water Quality Data Warehouse)",
     "channel_kind": "group_results", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "results", "records": False,
     "sources": ["nv-ndep-hab-dashboard"],
     "note": ("Sampling results by station behind a search form (https://nevadawaterquality.ndep.nv.gov/MainPage.aspx); "
              "results and downloads were not exercised. Samples, not notices: a sample is never shown as a sewage "
              "report. Not verified in the research as a source of current results.")},
    {"id": "nv-ndep-public-documents", "agency": "Nevada Division of Environmental Protection",
     "name": "Nevada Division of Environmental Protection (public document search)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "documents", "records": False,
     "sources": ["nv-ndep-environmental-activities"],
     "note": ("NDEP's document search (https://ndep-onbase.nv.gov/) warns that not all record series are online; "
              "whether sewage incident files are searchable was not verified in the research. A records request for "
              "the NRS 445A.467 notices is an owner item.")},
    {"id": "nv-snwa-watershed-monitoring", "agency": "Southern Nevada Water Authority",
     "name": "Southern Nevada Water Authority (Lower Colorado River watershed monitoring)",
     "channel_kind": "group_results", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "email_only", "publishes": "results", "records": False,
     "sources": ["nv-nps-lake-mead-habs"],
     "note": ("SNWA describes its Lake Mead and Colorado River monitoring and offers its regional database by e-mail "
              "request (https://www.snwa.com/water-quality/watershed/index.html); no request was sent. Samples, not "
              "notices.")},
    {"id": "nv-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False, "sources": ["nv-swim-guide"],
     "note": "No Swim Guide affiliate or Nevada listing was established (search only, 2026-11-03 and 2026-11-09)."},
]
OWN = [
    {"id": "nv-city-of-reno-spill-line", "operator_id": "nv-city-of-reno", "name": "City of Reno",
     "channel_kind": "operator_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "sources": ["nv-truckee-river-news"],
     "note": ("Reno's Environmental Control program takes spill and release reports from the public by telephone only "
              "(https://www.reno.gov/government/departments/utility-services/environmental-control.php); it publishes "
              "no list of overflows. A contact and a record holder, not a notice channel.")},
]


def base(**kw) -> dict:
    r = {"state": "NV", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "NV" or "nv" not in (op.get("source_areas") or []):
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        permit = ps[0] if ps else None
        local = op.get("legal_form") in LOCAL
        if local:
            basis, kind = Q_LAW + (("; " + Q_PERMIT.format(permit=permit)) if permit else ""), "law"
            what = ("its notice to NDEP under NRS 445A.467 (online or by telephone)"
                    + (" and its permit's noncompliance reports" if permit else ""))
        elif op.get("permit_only"):
            basis, kind = Q_PERMIT.format(permit=permit), "permit"
            what = ("the permit's noncompliance reports (whether NRS 445A.467 also binds the holder depends on who "
                    "holds the permit, which is not established here)")
        else:
            basis, kind = Q_PERMIT.format(permit=permit), "permit"
            what = ("its permit's noncompliance reports (NRS 445A.467 binds local governments, not "
                    + ("the federal government" if op.get("legal_form") == "federal facility" else "private holders")
                    + ")")
        rows.append(finish(base(
            id=f"{oid}-ndep-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=basis, basis_kind=kind, monitored=False, unmonitored_reason="other",
            publishes="none", records=False, noun="Report to the state", sources=["nv-law-sb276-2025"],
            note=(f"{name} reports a sewage discharge to NDEP: {what}. NDEP publishes no list of them; no public notice "
                  "is required: no web channel found. The permit itself was not read: the federal standard condition "
                  "is assumed. (research/nv/expansion-research.md)"))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "NV")
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
