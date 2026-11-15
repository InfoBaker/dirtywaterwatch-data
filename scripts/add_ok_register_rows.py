"""Oklahoma rows of the notice register (data/notice-channels/ok.json), made from the law and data/dischargers.json so
they are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_ok_register_rows.py [--dry-run]

The law (research/ok/expansion-research.md, read 2026-11-09):
  - DEQ's municipal permits' standard conditions (Part III, revision of March 2017, B.6): oral notice to DEQ within 24
    hours of becoming aware of any collection-system bypass or overflow, a written report within five days (waivable);
    C.11 on unanticipated bypasses. DEQ's wastewater reporting page (modified 2026-09-04) asks for a telephone report
    within 48 hours of the event and a written follow-up in "five business days" and "five days"; DEQ Form 605-011
    (revised 2025-10-01) for 24 hours and five days. The three are quoted as they are; none is chosen.
  - OAC 252:606 incorporates 40 CFR 122.41; OAC 252:616-5-3 (24 hours, seven days) covers industrial systems only.
  - No duty to tell the public was found; DEQ publishes no list; EPA's tables hold no Oklahoma report; no CSO permits.
Rows
  - Per operator (every Oklahoma row of data/dischargers.json): <id>-deq-report, the permit's report, not published.
  - Statewide: DEQ's reporting line and page, the bypass form, EPA's tables (none), DEQ's discharger layer (outfalls,
    no events), the NPS Chickasaw bacteria table (the ok-nps-chickasaw-bacteria feed), TravelOK's lake conditions,
    Tulsa's Zink Lake dashboard, GRDA's water-quality map, OWRB's monitoring data, USACE Tulsa District (403), Swim Guide.
  - Operators' own channels: Tulsa's sewer overflow reporting line, Oklahoma City's news.
A rerun replaces every ok- row it makes. Validated before writing.
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
PART3 = "https://oklahoma.gov/content/dam/ok/en/deq/documents/water-division/MunyPart3modified_3-17-17.pdf"
REPORTING = "https://oklahoma.gov/deq/divisions/water-quality/wastewater-stormwater/wastewater-reporting.html"
FORM = ("https://oklahoma.gov/content/dam/ok/en/deq/documents/water-division/"
        "form_605-011_wastewater_bypass_reporting-1.pdf")
ECHO = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"
NPS = "https://www.nps.gov/chic/planyourvisit/bathing-beach-monitoring-program.htm"
Q_PERMIT = ("OPDES permit {permit}, Part III B.6 (DEQ's municipal standard conditions, March 2017): oral notice to DEQ "
            "within 24 hours of becoming aware of any collection-system bypass or overflow, a written report within "
            "five days")
Q_GENERAL = ("OPDES general permit coverage {permit} (DEQ's general permit for small lagoon systems, not read): the "
             "24-hour and five-day noncompliance reports of 40 CFR 122.41(l)(6), which OAC 252:606 incorporates, "
             "assumed, unverified")
Q_UNRESOLVED = ("OPDES permit {permit} (not a municipal POTW permit in EPA's record; not read): the 24-hour and "
                "five-day noncompliance reports of 40 CFR 122.41(l)(6), which OAC 252:606 incorporates, assumed, "
                "unverified; DEQ's municipal standard conditions not asserted")
Q_TRIBAL = ("NPDES permit {permit} (tribal; issuing agency not read): the 24-hour and five-day noncompliance reports of "
            "40 CFR 122.41(l)(6), to the issuing agency")
NOTE_CONFLICT = ("DEQ's three instructions differ: the permit's standard conditions say 24 hours from awareness, DEQ's "
                 "reporting page 48 hours from the event, its bypass form 24 hours; they are quoted as they are.")
AGENCY = [
    {"id": "ok-deq-bypass-sso-report", "agency": "Oklahoma Department of Environmental Quality",
     "name": "Oklahoma Department of Environmental Quality (bypass and overflow reports)",
     "channel_kind": "state_alert_page", "urls": [], "method": None,
     "legal_basis": ("Municipal OPDES permits, Part III B.6 and C.11 (March 2017); DEQ Form 605-011 (revised "
                     "2025-10-01); OAC 252:606 (40 CFR 122.41 incorporated)"),
     "basis_kind": "permit", "monitored": False, "unmonitored_reason": "other", "publishes": "none", "records": False,
     "noun": "Report to the state", "sources": ["ok-deq-opdes-rules", "ok-deq-wastewater-reporting"],
     "note": ("Operators report bypasses and overflows to DEQ by telephone on its around-the-clock line, then in "
              f"writing on Form 605-011 (e-mail preferred). {NOTE_CONFLICT} DEQ publishes no list of the reports: no "
              f"web channel found; they reach the public only through an Open Records Act request. ({PART3}; "
              f"{REPORTING}; {FORM})")},
    {"id": "ok-deq-wastewater-reporting-page", "agency": "Oklahoma Department of Environmental Quality",
     "name": "Oklahoma Department of Environmental Quality (wastewater reporting requirements page)",
     "channel_kind": "state_alert_page", "urls": [REPORTING], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "metadata_only": True, "publishes": "documents",
     "records": False, "every_hours": 24, "noun": "Voluntary page", "sources": ["ok-deq-wastewater-reporting"],
     "note": ("DEQ's instructions to operators (last modified 2026-09-04): a telephone report within 48 hours of the "
              "event and a written follow-up in five days (also written five business days). Watched for a change of "
              "the instructions or a published list; it is intake guidance, not a notice to the public.")},
    {"id": "ok-epa-echo-overflow-events", "agency": "U.S. Environmental Protection Agency (ECHO)",
     "name": "U.S. Environmental Protection Agency (ECHO)", "channel_kind": "feed", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "none_found",
     "publishes": "none", "records": False, "sources": ["ok-epa-sobe"],
     "note": ("EPA's sewer overflow and bypass tables hold no Oklahoma report; their collection-system table lists one "
              f"Oklahoma system, the Kickapoo plant's (OK0044733, tribal), with no report (extracts of 2026-11-12, "
              f"{ECHO}). The state is not read from these tables.")},
    {"id": "ok-deq-npdes-dischargers-layer", "agency": "Oklahoma Department of Environmental Quality",
     "name": "Oklahoma Department of Environmental Quality (NPDES Dischargers map layer)", "channel_kind": "shared_site",
     "urls": ["https://gis.deq.ok.gov/server/rest/services/WaterQWeb/MapServer/4"], "method": "json",
     "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "metadata_only": True,
     "publishes": "documents", "records": False, "every_hours": 168, "noun": "Voluntary page",
     "sources": ["ok-deq-gis-waterqweb"],
     "note": ("DEQ's map layer of permitted discharge points (1,499 rows, 872 permits, \"Data set updated 06/14/2026\"): "
              "the same points as EPA's records for the 307 sewage permits it holds, with permit status. Outfalls, not "
              "events; watched weekly for a change of the data set.")},
    {"id": "ok-nps-chickasaw-bacteria", "agency": "National Park Service, Chickasaw National Recreation Area",
     "name": "National Park Service, Chickasaw National Recreation Area (bathing beach monitoring)",
     "channel_kind": "feed", "urls": [NPS], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "feed_ingested", "feed_source_id": "ok-nps-chickasaw-bacteria",
     "publishes": "results", "noun": "Data feed", "sources": ["ok-beaches"],
     "note": ("The park's weekly E. coli results at ten swimming places in summer, with its threshold (235 weekly, 126 "
              "geometric mean) and its posting rule; 40 results of August 6 to 27, 2026 on 2026-11-14, none at the "
              "threshold. The park posts signs at the water; the page gives no posting or removal date. Samples, not "
              "sewage reports. Voluntary.")},
    {"id": "ok-travelok-lake-conditions", "agency": "Oklahoma Tourism and Recreation Department",
     "name": "Oklahoma Tourism and Recreation Department (lake conditions)", "channel_kind": "state_alert_page",
     "urls": ["https://www.travelok.com/state-parks/lake-conditions"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None, "metadata_only": True, "publishes": "unknown",
     "records": False, "every_hours": 24, "noun": "Voluntary page", "sources": ["ok-otrd-checkmyoklake"],
     "note": ("The state's lake chooser for current conditions and blue-green algae (the successor of Check My OK "
              "Lake, whose host failed in November); the selected-lake results and their dates were not exposed to the "
              "research (2026-11-09). Watched for a readable advisory list.")},
    {"id": "ok-tulsa-zink-lake-dashboard", "agency": "City of Tulsa", "name": "City of Tulsa (Zink Lake dashboard)",
     "channel_kind": "state_alert_page", "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary",
     "monitored": False, "unmonitored_reason": "other", "publishes": "unknown", "records": False,
     "sources": ["ok-beaches"],
     "note": ("The Zink Lake project page links a dashboard (maps.cityoftulsa.org/zinklake) of E. coli testing and "
              "recreation closures; the ArcGIS Experience rendered no records to the research (2026-11-09). Not "
              "verified in the research as a readable source.")},
    {"id": "ok-grda-water-quality-map", "agency": "Grand River Dam Authority",
     "name": "Grand River Dam Authority (water-quality advisory map)", "channel_kind": "shared_site", "urls": [],
     "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "image_only", "publishes": "unknown", "records": False, "sources": ["ok-beaches"],
     "note": ("An embedded Google map of sampling sites (https://grda.com/water-quality-advisory-map/) whose records "
              "did not render as data (2026-11-09).")},
    {"id": "ok-owrb-monitoring-data", "agency": "Oklahoma Water Resources Board",
     "name": "Oklahoma Water Resources Board (water monitoring and data)", "channel_kind": "group_results",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "login", "publishes": "results", "records": False, "sources": ["ok-beaches"],
     "note": ("The public-data link of the Board's monitoring page returned a sign-in page (2026-11-09); rotating "
              "ambient monitoring, not swimming notices.")},
    {"id": "ok-usace-tulsa-district", "agency": "U.S. Army Corps of Engineers, Tulsa District",
     "name": "U.S. Army Corps of Engineers, Tulsa District (water quality)", "channel_kind": "shared_site",
     "urls": ["https://www.swt.usace.army.mil/Locations/Water-Quality/"], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "bot_wall", "publishes": "unknown",
     "records": False, "sources": ["ok-usace-tulsa-hab"],
     "note": ("The District's water-quality program page answers 403 to automated readers (2026-11-09); it has posted "
              "lake algae notices in past seasons.")},
    {"id": "ok-swim-guide", "agency": "Swim Drink Fish", "name": "Swim Drink Fish", "channel_kind": "swim_guide",
     "urls": [], "method": None, "legal_basis": None, "basis_kind": "voluntary", "monitored": False,
     "unmonitored_reason": "none_found", "publishes": "none", "records": False, "sources": ["ok-beaches"],
     "note": "No Swim Guide affiliate or Oklahoma listing was found (search, 2026-11-03)."},
]
OWN = [
    {"id": "ok-tulsa-sewer-overflow-line", "operator_id": "ok-tulsa-metropolitan-utility-authority",
     "name": "Tulsa Metropolitan Utility Authority", "channel_kind": "operator_page", "urls": [], "method": None,
     "legal_basis": None, "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other",
     "publishes": "none", "records": False, "sources": ["ok-okc-tulsa-utilities"],
     "note": ("Tulsa's Water and Sewer page (https://cityoftulsa.org/government/departments/water-and-sewer/) asks the "
              "public to report a sewer overflow by telephone only; no published list of overflows was found.")},
    {"id": "ok-okc-news", "operator_id": "ok-city-of-oklahoma-city", "name": "City of Oklahoma City",
     "channel_kind": "news_page", "urls": [], "method": None, "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "other", "publishes": "notices",
     "records": False, "sources": ["ok-okc-tulsa-utilities"],
     "note": ("The city's news articles: the June 15, 2026 notice of the Oklahoma River's eastern basin drained for a "
              "sewer main repair said officials believed no untreated wastewater entered the river "
              "(https://www.okc.gov/News-articles/). News articles are occasional and not a notice channel; not "
              "verified in the research as a place where overflows are announced.")},
]


def base(**kw) -> dict:
    r = {"state": "OK", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    r.update(kw)
    return r


def _plants() -> dict:
    out = {}
    for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]:
        if r.get("state") == "OK" and r.get("npdes_permit"):
            out.setdefault(r["npdes_permit"], r)
    return out


def legal_basis(op: dict, plants: dict) -> tuple[str, dict]:
    """(the legal basis each of the row's permits supports, grouped; the scopes), Astra P2-10: the municipal Part III
    B.6 only for a permit EPA records as a municipal POTW."""
    from add_ok_operators import permit_scope
    lf = "permit only" if op.get("permit_only") else op.get("legal_form")
    q = {"municipal": Q_PERMIT, "general": Q_GENERAL, "unresolved": Q_UNRESOLVED, "tribal": Q_TRIBAL}
    scopes = {p: permit_scope(p, plants.get(p), lf) for p in op.get("npdes_permits") or []}
    return "; ".join(q[sc].format(permit=p) for p, sc in sorted(scopes.items())), scopes


def operator_rows(dis: list[dict]) -> list[dict]:
    rows = []
    plants = _plants()
    for op in dis:
        if op.get("state") != "OK" or "ok" not in (op.get("source_areas") or []):
            continue
        oid, name, ps = op["id"], op["name"], op.get("npdes_permits") or []
        permit = ps[0] if ps else None
        basis, scopes = legal_basis(op, plants)
        tribal = bool(scopes) and all(sc == "tribal" for sc in scopes.values())
        rows.append(finish(base(
            id=f"{oid}-deq-report", operator_id=oid, name=name, permit=permit, channel_kind="state_alert_page",
            urls=[], method=None, legal_basis=basis,
            basis_kind="permit", monitored=False, unmonitored_reason="other", publishes="none", records=False,
            noun="Report to the state", sources=["ok-deq-opdes-rules"],
            note=(f"{name} reports a bypass or overflow under its permit to "
                  + ("the issuing agency (DEQ or EPA Region 6; not read)" if tribal else "DEQ")
                  + "; no list is published and no public notice duty was found: no web channel found. The permit "
                  "itself was not read: "
                  + ("DEQ's municipal standard condition is assumed for a municipal POTW permit; for any other, the "
                     "federal condition, unverified." if set(scopes.values()) - {"tribal"} else
                     "the federal condition is assumed.")))))
    return rows


def run(dry_run: bool = False) -> dict:
    doc = NP.load_register(REGISTER)
    dis = json.loads(DIS.read_text())
    rows = operator_rows(dis)
    rows += [finish(base(**r)) for r in AGENCY + OWN]
    drop = tuple(r["id"] for r in doc["channels"] if r.get("state") == "OK")
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
