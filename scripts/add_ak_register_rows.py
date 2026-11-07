"""Alaska rows of the notice register (data/notice-channels/ak.json), made from the law, the permits and
data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ak_register_rows.py [--dry-run]

The law (research/ak/report.md in the site repository; profile research/ak/profile.json):
  - 18 AAC 72.940 "Emergency notice" (read on akleg.gov 2026-11-07): (a) the owner or operator of a domestic or
    nondomestic wastewater collection, treatment, or disposal system "shall report to the department within 24 hours,
    or as soon after that as possible", among other events, when "an accident, spill, or other event occurs that ...
    threatens public health or water quality", "a sludge carry-over, washout, or overflow occurs", or "any part of the
    treatment works is by-passed"; (b) "A follow-up written report must be sent to the department within seven days".
    Not for an onsite system serving a private residence (c). No duty to tell the public.
  - APDES permits, Appendix A (Standard Conditions), Part 3.4 Twenty-four Hour Reporting (read in permit AK0022951,
    2014, on the City and Borough of Juneau's site): a noncompliance event that may endanger health or the environment
    is reported orally within 24 hours and in writing within five days; the written report may go by e-mail to DEC.
  - Juneau-Douglas permit AK0023213 (EPA-issued 2001, administratively continued; read on the City and Borough's
    site 2026-11-07): Part I.D.1.g, "The permittee must ensure that the public receives adequate notification of CSO
    occurrences and CSO impacts"; Part II.H.2.a, notification of the public, health agencies and other affected
    entities of sewer overflows that may imminently and substantially endanger human health, under the permittee's
    overflow emergency response plan.

Rows
  - Per operator (every Alaska row of data/dischargers.json except kind cso_closed_or_none, the pipeline permit EPA's
    CSO inventory lists): <id>-dec-emergency-notice (permit basis, 18 AAC 72.940 and the permit's 24-hour and
    5-day reports): the report goes to DEC only; no web page.
  - Juneau: <id>-cso-public-notification (the City and Borough's wastewater utility page, which lists its CSO public
    notices; monitored, the CSO section cut out with an entry) and <id>-sso-public-notification (Part II.H.2.a; not
    found on the utility page, not searched further).
  - Agency and voluntary rows: AGENCY below (EPA's overflow tables, read by the eRule feed; DEC's report desk and spill
    database; DEC's beach program; the Alaska Harmful Algal Bloom Network; AWWU's site), and Juneau's permit-required
    outfall signs (<id>-outfall-signs-<permit>, AK0023213 Part I.C.7 and AK0022951 Part 2.5; on site only).
A rerun replaces every ak- row it makes. Validated before writing.
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
LAW_ID = "ak-18-aac-72-940"
JUNEAU_PAGE = "https://juneau.org/engineering-public-works/utilities-division/wastewater-utility-division"   # https://juneau.org/engineering-public-works/wastewater-utility answers 301 to it (2026-11-07)
Q_LAW = ('18 AAC 72.940(a): the operator of a wastewater collection, treatment, or disposal system "shall '
         'report to the department within 24 hours, or as soon after that as possible" when "an accident, spill, or '
         'other event occurs that results in inadequate treatment in violation of permit conditions, or threatens '
         'public health or water quality", "a sludge carry-over, washout, or overflow occurs" or "any part of the '
         'treatment works is by-passed"; (b): "A follow-up written report must be sent to the department within seven '
         'days"')
Q_PERMIT = ("Permit {permit}: the permit's noncompliance reporting (APDES Standard Conditions, Appendix A, Part 3.4: "
            "orally within 24 hours and in writing within five days after the permittee becomes aware of a "
            "noncompliance event that may endanger health or the environment; the operator's own permit text not "
            "read unless named); " + Q_LAW)
Q_CSO = ('NPDES permit AK0023213, Part I.D.1.g: "The permittee must ensure that the public receives adequate '
         'notification of CSO occurrences and CSO impacts"')
Q_SSO = ("NPDES permit AK0023213, Part II.H.2.a: for sanitary sewer overflows that may imminently and substantially "
         "endanger human health, \"notification of the public, health agencies and other affected entities (e.g., "
         "public water systems)\", in accordance with the permittee's overflow emergency response plan")
SIGNS = {   # permit-required shoreline signs at the plant outfalls (read in the permits on the City and Borough's site)
    "AK0023213": ("NPDES permit AK0023213, Part I.C.7 (Outfall Location Signs): signs on the shoreline near the mixing "
                  "zone and outfall line that \"inform the public that certain activities, such as the harvesting of "
                  "shellfish for raw consumption and contact recreation should not take place in the mixing zone\""),
    "AK0022951": ("APDES permit AK0022951, Part 2.5 (Identification Sign(s)): signs on the shoreline adjacent to the "
                  "discharge point that \"inform the public that certain activities, such as harvesting of aquatic life "
                  "for raw consumption and primary contact recreation, should not take place in the mixing zone\""),
}
AGENCY = [
    {"id": "ak-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed",
     "urls": ["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], "method": "html",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "echo-sewer-overflow", "publishes": "notices", "noun": "Data feed",
     "note": ("EPA's sewer overflow and bypass event tables (NPDES electronic reporting): 46 current Alaska reports from "
              "three permits in the 2026-11-04 extract (Anchorage 43, Ketchikan 2, Denali National Park 1), received a "
              "median one day after the start. The only dated, machine-readable overflow record for Alaska; Juneau's "
              "combined sewer permit files nothing there. (research/ak/report.md section 2)"),
     "sources": ["fed-echo-sewer-overflow-bypass-events", "ak-epa-sobe"]},
    {"id": "ak-dec-wastewater-reports", "agency": "Alaska Department of Environmental Conservation",
     "name": "Alaska Department of Environmental Conservation (wastewater noncompliance reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": Q_LAW, "basis_kind": "law",
     "monitored": False, "unmonitored_reason": "none_found", "publishes": "none", "records": False,
     "noun": "Report to the state",
     "note": ("No web form: every wastewater operator, public or private, reports overflows, bypasses and spills that "
              "threaten public health or water quality to DEC within 24 hours and in writing within seven days (five "
              "under an APDES permit). DEC does not post the reports and no Alaska law requires the public to be told. "
              "DEC's web pages answer 403 to the project's reader (2026-11-07). (research/ak/report.md section 2)"),
     "sources": [LAW_ID, "ak-apdes-permits"]},
    {"id": "ak-dec-spill-database", "agency": "Alaska Department of Environmental Conservation",
     "name": "Alaska Department of Environmental Conservation (spill database)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "notices", "records": False,
     "note": ("DEC's statewide oil and hazardous substance spill search "
              "(https://dec.alaska.gov/Applications/SPAR/PublicMVC/PERP/SpillSearch) and its spill data page answer 403 "
              "behind a bot check (2026-11-03 and 2026-11-07). Whether sewage spills are in it is not known: its scope "
              "is oil and hazardous substances. The request to DEC: say whether wastewater spills are recorded there and "
              "publish an export. (research/ak/sources.json ak-dec-spill-database)"),
     "sources": ["ak-dec-spill-database"]},
    {"id": "ak-dec-beach-program", "agency": "Alaska Department of Environmental Conservation",
     "name": "Alaska Department of Environmental Conservation (beach program)", "channel_kind": "state_alert_page",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "bot_wall", "publishes": "unknown", "records": False,
     "note": ("DEC's BEACH Act monitoring of a few marine beaches, seasonal; its pages answer 403 behind a bot check "
              "(2026-11-07), and no advisory list or map service was found. Voluntary under the federal BEACH Act "
              "grant. (research/ak/sources.json ak-dec-beach-program)"),
     "sources": ["ak-dec-beach-program"]},
    {"id": "ak-ahab-network", "agency": "Alaska Harmful Algal Bloom Network (Alaska Ocean Observing System)",
     "name": "Alaska Harmful Algal Bloom Network", "channel_kind": "group_results",
     "urls": ["https://ahab.aoos.org/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "publishes": "unknown",
     "records": False, "every_hours": 24, "noun": "Voluntary page",
     "note": ("The network's page (HAB alerts, shellfish poisoning, monitoring links); marine biotoxins, not sewage. "
              "Answered 200 on 2026-11-07 after a redirect from https://aoos.org/alaska-hab-network/. No machine-readable alert layer found. Voluntary. "
              "(research/ak/sources.json ak-ahab)"),
     "sources": ["ak-ahab"]},
]


def base(**kw) -> dict:
    r = {"state": "AK", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "AK" or op.get("kind") == "cso_closed_or_none":
            continue
        name, permit, oid = op["name"], op.get("npdes_permit"), op["id"]
        sobe = op.get("notification_feed_machine_readable")
        rows.append(finish(base(
            id=f"{oid}-dec-emergency-notice", operator_id=oid, name=name, permit=permit,
            channel_kind="state_alert_page", urls=[], method=None, legal_basis=Q_PERMIT.format(permit=permit),
            basis_kind="permit", monitored=False, unmonitored_reason="other", publishes="none", records=False,
            noun="Report to the state", sources=[LAW_ID, "ak-apdes-permits"] + (["ak-epa-sobe"] if sobe else []),
            note=(f"No web channel found: {name} reports overflows, bypasses and spills to DEC within 24 hours and in "
                  "writing within days; DEC does not post them and no Alaska law requires the public to be told. "
                  + ("Its reports are filed through EPA's NeT-SewerOverflow and reach EPA's overflow tables, which the "
                     "feed reads. " if sobe else "Its reports were not found in EPA's overflow tables. ")
                  + "(research/ak/report.md section 2)"))))
        if oid == "ak-juneau-douglas":
            rows.append(finish(base(
                id=f"{oid}-cso-public-notification", operator_id=oid, name=name, permit="AK0023213",
                channel_kind="operator_page", urls=[JUNEAU_PAGE], method="html", legal_basis=Q_CSO,
                basis_kind="permit", monitored=True, unmonitored_reason=None, publishes="notices", every_hours=24,
                noun="CSO public notification",
                entry={"start": r"^Combined Sewer Overflows$", "end": r"^Juneau-Douglas Treatment Facility$"},
                sources=["ak-apdes-permits"],
                note=("The City and Borough's wastewater utility page lists its combined sewer overflow public notices "
                      "\"in an effort to make the public aware of these events and to fully comply with the EPA "
                      "discharge permit\": PDF notices from 2004 and November 2005, and \"No Combined Sewer Overflow "
                      "since 2005\". Answered 200 on 2026-11-07 after a 301 from https://juneau.org/engineering-public-works/wastewater-utility; the CSO section is read. The permit's clause was read "
                      "in the permit the page links."))))
            rows.append(finish(base(
                id=f"{oid}-sso-public-notification", operator_id=oid, name=name, permit="AK0023213",
                channel_kind="operator_page", urls=[], method=None, legal_basis=Q_SSO, basis_kind="permit",
                monitored=False, unmonitored_reason="other", publishes="unknown", records=False,
                noun="Overflow public notification", sources=["ak-apdes-permits"],
                note=("No URL known (not searched): the permit requires public notification of sewer overflows that "
                      "may imminently and substantially endanger human health under the overflow emergency response "
                      "plan; the wastewater utility page carries no such notices, and the plan and the City and "
                      "Borough's news pages were not searched individually."))))
        if oid == "ak-juneau-douglas":
            for pmt, clause in SIGNS.items():
                rows.append(finish(base(
                    id=f"{oid}-outfall-signs-{pmt.lower()}", operator_id=oid, name=name, permit=pmt,
                    channel_kind="lights_signs_page", urls=[], method=None, legal_basis=clause, basis_kind="permit",
                    monitored=False, unmonitored_reason="other", publishes="unknown", records=False,
                    noun="Outfall signs", sources=["ak-apdes-permits"],
                    note=(f"No web form: the shoreline sign(s) at permit {pmt}'s outfall tell the public that contact "
                          "recreation and raw shellfish harvest should not take place in the mixing zone. On site "
                          "only. Other Alaska plant permits probably carry the same clause (not read)."))))
        if oid == "ak-awwu-anchorage":
            rows.append(finish(base(
                id=f"{oid}-website", operator_id=oid, name=name, permit=permit, channel_kind="operator_page",
                urls=[], method=None, legal_basis=None, basis_kind="voluntary", monitored=False,
                unmonitored_reason="bot_wall", publishes="unknown", records=False, sources=["ak-awwu"],
                note=("AWWU's site (https://www.awwu.biz/) answers 403 to the project's reader (2026-11-07); research "
                      "by search found no overflow notice page. Its reports reach EPA's overflow tables. Voluntary."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "AK")
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
