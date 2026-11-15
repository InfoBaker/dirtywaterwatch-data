"""Puerto Rico rows of the notice register (data/notice-channels/pr.json), made from the permits, the consent decree,
DRNA's beach program and data/dischargers.json so they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_pr_register_rows.py [--dry-run]

The law and the permits (research/pr/profile.json, read 2026-11-04 and 2026-11-14):
  - EPA Region 2 writes every Puerto Rico permit. Their standard conditions (40 CFR 122.41(l)(6)) require the 24-hour
    oral and five-day written report of noncompliance that may endanger health or the environment to EPA; since eRule
    phase 2 (40 CFR part 127) the report is filed electronically and EPA publishes it in its overflow tables.
  - PRASA's Puerto Nuevo permit (PR0021555, 2021), CSO permit conditions, Nine Minimum Controls 8: "The permittee shall
    implement a public notification process to inform citizens of when and where CSOs occur", with no deadline. The
    2023 modification of the consent decree (United States v. PRASA, No. 3:15-cv-02283, D.P.R.) adds communication to
    the public on PRASA's website of the Puerto Nuevo CSO discharges and their estimated volume.
  - No Puerto Rico statute requiring the public to be told of a sewage overflow or bypass was found; R. del S. 310
    (2025) is a Senate investigation proposing weekly public incident reports.
  - DRNA's beach program (Programa de Monitoría de Playas y Notificación Pública) is run under the federal BEACH Act
    grant program (33 U.S.C. 1346), which requires the public to be notified when a beach exceeds the water quality
    standard.
Rows
  - Per operator (every Puerto Rico row of data/dischargers.json): <id>-epa-report (the federal report, published in
    EPA's tables, which the overflow module reads: feed_ingested).
  - PRASA: its combined sewer pages (monitored standing, no records: no events posted), and the public notification
    process the permit requires for Puerto Nuevo (no event list found).
  - Agency and voluntary rows: AGENCY below.
A rerun replaces every pr- row it makes. Validated before writing.
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
FEED = "echo-sewer-overflow"
SUMMARY = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
Q_EPA = ("40 CFR 122.41(l)(6): the permittee reports noncompliance that may endanger health or the environment to EPA "
         "orally within 24 hours and in writing within five days; 40 CFR part 127: filed electronically "
         "(NeT-SewerOverflow), and EPA publishes the reports in its sewer overflow and bypass tables")
Q_NMC8 = ("NPDES permit PR0021555 (2021), CSO permit conditions, Nine Minimum Controls 8: \"The permittee shall implement "
          "a public notification process to inform citizens of when and where CSOs occur. The process must include (a) "
          "a mechanism to alert persons of the occurrence of CSOs and (b) a system to determine the nature and duration "
          "of conditions that are potentially harmful for users of receiving waters due to CSOs.\"")
Q_DECREE = ("United States v. PRASA, No. 3:15-cv-02283 (D.P.R.), consent decree (2016) as modified in 2023 (EPA Region 2 "
            "public notice of 2023-07-05): communication to the public through PRASA's website of the discharges from "
            "the permitted combined sewer outfalls and their estimated volume")
PRASA_CSO = "https://www.acueductos.pr.gov/en-us/combinado/alcantarillado-combinado"
PRASA_MAP = "https://www.acueductos.pr.gov/en-us/combinado/mapa-de-ubicacion-csos"
DRNA_API = "https://www.drna.pr.gov/wp-json/wp/v2/posts?categories=1424"
DRNA = "Departamento de Recursos Naturales y Ambientales (DRNA)"

AGENCY = [
    {"id": "pr-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. EPA sewer overflow and bypass event tables (Puerto Rico permits)", "channel_kind": "feed",
     "urls": [SUMMARY], "method": "html", "legal_basis": Q_EPA, "basis_kind": "law", "monitored": False,
     "unmonitored_reason": "feed_ingested", "feed_source_id": FEED, "publishes": "notices", "noun": "Data feed",
     "authority": "U.S. EPA (reports filed by the permittees)", "sources": ["pr-epa-sobe"],
     "note": ("Puerto Rico's only dated, event-level sewage record: 940 current reports from 45 permits in the "
              "2026-11-12 extract (SSO 863, bypass 77, none typed CSO), received a median 2 days after the start. "
              "Read daily by the overflow module (research/pr/sources.json).")},
    {"id": "pr-drna-beach-notices", "agency": DRNA,
     "name": f"{DRNA}, Programa de Monitoría de Playas y Notificación Pública (weekly beach notices)",
     "channel_kind": "feed", "urls": [DRNA_API], "method": "json",
     "legal_basis": ("BEACH Act, 33 U.S.C. 1346(c): a state or territory receiving a beach grant notifies the public "
                     "when a coastal recreation water exceeds the water quality criteria"),
     "basis_kind": "law", "monitored": False, "unmonitored_reason": "feed_ingested",
     "feed_source_id": "pr-drna-beach-notices", "publishes": "notices", "noun": "Data feed", "authority": DRNA,
     "sources": ["pr-drna-beach-notices"],
     "note": ("DRNA's weekly notice lists the beaches whose enterococci samples exceed the Beach Action Value as not "
              "fit for bathers (280 notices since 2019-10; 36 stations in its table). Read by its own module every refresh. No terms "
              "of use stated on the API.")},
    {"id": "pr-drna-spill-reports", "agency": DRNA, "name": f"{DRNA} (spill and bypass reports from permittees)",
     "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": ("NPDES permit PR0021555 (2021): written notice of a spill to the Department within 24 hours; "
                     "permits direct bypass and spill notices to its Point Sources Permits Division by e-mail"),
     "basis_kind": "permit", "monitored": False, "unmonitored_reason": "none_found", "publishes": "none",
     "records": False, "noun": "Report to the territory", "sources": ["pr-dnr-bypass-email"],
     "note": ("A regulator-only channel: the reports go to DRNA by e-mail; no public list or page of them was found.")},
    {"id": "pr-estuario-bacteria", "agency": "San Juan Bay Estuary Program (Programa del Estuario de la Bahía de San Juan)",
     "name": "San Juan Bay Estuary Program, bacteriological monitoring", "channel_kind": "group_results",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "results", "records": False, "noun": "Sampling results",
     "sources": ["pr-estuario-bacteria"],
     "note": ("Periodic PDF reports of bacteria in the Condado lagoon and San Juan's beaches; whether a current "
              "list is published was not verified (research: search only).")},
    {"id": "pr-surfrider-bwtf", "agency": "Surfrider Foundation (Blue Water Task Force, Puerto Rico chapters)",
     "name": "Surfrider Foundation Blue Water Task Force, Rincón and Isabela", "channel_kind": "group_results",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "other", "publishes": "results", "records": False, "noun": "Sampling results",
     "sources": ["pr-surfrider-bwtf"],
     "note": "Volunteer bacteria results; whether a current list is published was not verified: the channel was not researched beyond the programme page (search only)."},
    {"id": "pr-epa-beacon", "agency": "U.S. Environmental Protection Agency (BEACON 2.0)",
     "name": "U.S. EPA BEACON 2.0, Puerto Rico beaches", "channel_kind": "shared_site", "urls": [],
     "method": None, "legal_basis": "BEACH Act, 33 U.S.C. 1346: the states' and territories' notification data reported "
     "to EPA", "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "results",
     "records": False, "noun": "Shared site", "sources": ["pr-epa-beacon"],
     "note": "Season-level beach notification data reported to EPA; not verified in the research (not fetched)."},
]


def base(**kw) -> dict:
    r = {"state": "PR", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    for op in dis:
        if op.get("state") != "PR":
            continue
        name, permit, oid = op["name"], op.get("npdes_permit"), op["id"]
        rows.append(finish(base(
            id=f"{oid}-epa-report", operator_id=oid, name=name, permit=permit, channel_kind="feed", urls=[],
            method=None, legal_basis=f"permit {permit} (EPA Region 2): " + Q_EPA, basis_kind="permit",
            monitored=False, unmonitored_reason="feed_ingested", feed_source_id=FEED, publishes="notices",
            noun="Report to EPA", sources=["pr-epa-sobe"],
            note=(("The holder of " + name.replace("Permit ", "permit ", 1) if op.get("permit_only") else name)
                  + " reports an overflow or bypass to EPA Region 2 within 24 hours and in writing within five "
                  "days; the electronic report is published in EPA's overflow tables, which the overflow module reads "
                  f"daily ({len(op.get('npdes_permits') or [])} permit(s) in this row). No public notice of its own is "
                  "required by Puerto Rico law."
                  + (" The body that holds the permit is not established (a permit-only row)." if op.get("permit_only")
                     else "")))))
        if oid == "pr-prasa":
            rows.append(finish(base(
                id="pr-prasa-cso-pages", operator_id=oid, name=name, permit="PR0021555", channel_kind="operator_page",
                urls=[PRASA_CSO, PRASA_MAP], method="html", legal_basis=Q_NMC8 + "; " + Q_DECREE,
                basis_kind="permit", monitored=True, unmonitored_reason=None, publishes="none", records=False,
                noun="Notification page", sources=["pr-prasa-cso-web", "pr-epa-npdes-pr0021555", "pr-prasa-consent-decree"],
                note=("PRASA's combined sewer pages (Spanish and English): the outfall map, precautions, the work under "
                      "way and a form for the public to report an overflow (reCAPTCHA). On 2026-11-04 no overflow "
                      "event or volume was posted, although the 2023 decree modification calls for it. Watched for a "
                      "change; no records are made from the page."))))
            rows.append(finish(base(
                id="pr-prasa-cso-public-notification", operator_id=oid, name=name, permit="PR0021555",
                channel_kind="lights_signs_page", urls=[], method=None, legal_basis=Q_NMC8, basis_kind="permit",
                monitored=False, unmonitored_reason="none_found", publishes="none", records=False,
                noun="Public notification process", sources=["pr-epa-npdes-pr0021555"],
                note=("The permit's mechanism to alert persons when and where CSOs occur: no alert, sign list or "
                      "event page was found on PRASA's site; no web channel found."))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis) + [finish(base(**r)) for r in AGENCY]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "PR")
    doc = merge(doc, rows, drop)
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        NP.save_register(doc["channels"], REGISTER)
    return {"rows": len(rows),
            "barriers": dict(Counter(r["barrier"] or ("review" if r.get("barrier_review") else "none") for r in rows))}


if __name__ == "__main__":
    print(json.dumps(run("--dry-run" in sys.argv[1:]), indent=1))
