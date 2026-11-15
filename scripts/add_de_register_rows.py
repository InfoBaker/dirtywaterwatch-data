"""Delaware's rows of the public-notice register: data/notice-channels/de.json (one row per channel per operator or
agency: law, permit and voluntary).

Usage: pipeline/.venv/bin/python -I scripts/add_de_register_rows.py

Rows
  - Every Delaware operator of data/dischargers.json (scripts/add_de_operators.py): its releases reach the public
    through DNREC's release list (7 Del. C. 6028(a): DNREC posts a reported release, sewage from 10,000 gallons, within
    one business day), which this site reads: feed_ingested, feed de-dnrec-derns-recent-releases. The operators' own
    pages were not searched individually.
  - Wilmington (DE0020320, the state's 41 open combined sewer outfalls): the signs at each outfall (the City's page:
    "Each location is marked by a sign notifying the public of the CSO"), barrier signs_only; the City's CSO page,
    watched daily for a notice; the City's alert sign-up (AlertSense), whose overflow content was not verified.
  - DNREC: the release list (feed); DERNS release alerts by e-mail, fax or telephone to registered recipients
    (6014(b), an account needed: login); the recreational-water advisories and map (feed); the beach-advisory e-mail
    list (listserv, e-mail only); the shellfish program page and the blue-green algae page (watched, no records).
  - EPA's eRule overflow tables: no Delaware row in the current or the all-versions extract on 2026-11-14.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "notice-channels" / "de.json"
DIS = ROOT / "data" / "dischargers.json"
CHECKED = "2026-11-14"
DERNS = "https://derns.dnrec.delaware.gov/Pub/RecentReleases.aspx"
LAW_6028 = ("7 Del. C. 6028(a): a person causing an environmental release (sewage of 10,000 gallons or more, 6002(20)) "
            "\"shall report such an incident to the Department as soon as the person has knowledge\"; DNREC posts it on "
            "its website \"no later than 1 business day after the release is reported\"; permitted discharges are exempt")
LAW_6014 = ("7 Del. C. 6014(b): DNREC's central unified notification system notifies, within 12 hours after DNREC is "
            "informed of a release, the "
            "district's State Representative and Senator, community groups within 5 miles and residents within 5 miles "
            "who have registered")


def base(**kw) -> dict:
    row = {"state": "DE", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    row.update(kw)
    return row


def rows() -> list[dict]:
    dis = [r for r in json.loads(DIS.read_text()) if r.get("state") == "DE"]
    out = []
    for r in dis:
        out.append(base(
            operator_id=r["id"], permit=r.get("npdes_permit"), id=f"{r['id']}-dnrec-releases", name=r["name"],
            channel_kind="feed", urls=[DERNS], method="html", legal_basis=LAW_6028, basis_kind="law", monitored=False,
            unmonitored_reason="feed_ingested", feed_source_id="de-dnrec-derns-recent-releases", publishes="notices",
            noun="Data feed", sources=["de-dnrec-derns-recent-releases", "de-law-7-del-c-6028"],
            note=(f"{r['name']}'s sewage releases reach the public through DNREC's Recent Releases list when reported "
                  "under 6028 (sewage from 10,000 gallons; smaller ones when reported), read by this site. The "
                  "operator's own pages were not searched individually."),
            barrier=None))
    w = "de-de0020320"
    out += [
        base(operator_id=w, permit="DE0020320", id="de-wilmington-cso-signs", name="City of Wilmington (CSO outfall signs)",
             channel_kind="lights_signs_page", urls=[], method=None,
             legal_basis=("EPA's Combined Sewer Overflow Control Policy, minimum control 8 (public notification), "
                          "carried by NPDES permit DE0020320; the permit's own clause was not read"),
             basis_kind="permit", monitored=False, unmonitored_reason="other", publishes="none", records=False,
             noun="Signs", sources=["de-wilmington-cso-site"],
             note=("The City says each of its combined sewer outfalls \"is marked by a sign notifying the public of the "
                   "CSO\". No overflow notice, status or list was found on the web; Wilmington's overflows are "
                   "permitted discharges, exempt from DNREC's release list (6028(a))."),
             barrier="signs_only"),
        base(operator_id=w, permit="DE0020320", id="de-wilmington-cso-page", name="City of Wilmington (CSO page)",
             channel_kind="operator_page", urls=["https://wilmingtondewater.gov/262/Combined-Sewer-Overflows-CSOs"],
             method="html", legal_basis=None, basis_kind="voluntary", monitored=True, unmonitored_reason=None,
             publishes="documents", records=False, every_hours=24, noun="Voluntary page",
             sources=["de-wilmington-cso-site"],
             note=("The City's explainer of its combined sewers and the outfall signs (the older cso.wilmingtonde.gov "
                   "site could not be read on 2026-11-09); no overflow status. Watched daily for a notice."),
             barrier=None),
        base(operator_id=w, permit="DE0020320", id="de-wilmington-alerts", name="City of Wilmington (alert sign-up)",
             channel_kind="email_list", urls=[], method=None, legal_basis=None, basis_kind="voluntary", monitored=False,
             unmonitored_reason="email_only", publishes="unknown", records=False, noun="Alert list",
             sources=["de-wilmington-cso-site"],
             note=("The City's utility pages link an alert sign-up (AlertSense); whether it carries overflow notices was "
                   "not verified (expansion research, 2026-11-09). Sent to subscribers; no page to read."),
             barrier="no_web_page"),
        base(agency="Delaware Department of Natural Resources and Environmental Control", id="de-dnrec-derns-recent-releases",
             name="Delaware DNREC (Environmental Release Notification System, Recent Releases)", channel_kind="feed",
             urls=[DERNS], method="html", legal_basis=LAW_6028, basis_kind="law", monitored=False,
             unmonitored_reason="feed_ingested", feed_source_id="de-dnrec-derns-recent-releases", publishes="notices",
             noun="Data feed", sources=["de-dnrec-derns-recent-releases", "de-law-7-del-c-6028"],
             note=("DNREC's public list of every environmental release reported under 6028, of every substance, with a "
                   "detail page each (release and report times, location, facility, Released To, estimated quantity, "
                   "DNREC's notes). This site keeps the sewage and sanitary-wastewater releases by rule."),
             barrier=None),
        base(agency="Delaware Department of Natural Resources and Environmental Control", id="de-dnrec-derns-alerts",
             name="Delaware DNREC (DERNS release notifications)", channel_kind="email_list",
             urls=["https://derns.dnrec.delaware.gov/"], method="html", legal_basis=LAW_6014, basis_kind="law",
             monitored=False, unmonitored_reason="login", publishes="notices", records=False, noun="Alert list",
             signup_url="https://derns.dnrec.delaware.gov/", sources=["de-dnrec-derns-recent-releases"],
             note=("E-mail, fax or telephone notices of releases to registered recipients; registration needs an "
                   "account. The public list carries the same releases."),
             barrier="login_required"),
        base(agency="Delaware Department of Natural Resources and Environmental Control", id="de-dnrec-recreational-water",
             name="Delaware DNREC (Recreational Water Program advisories)", channel_kind="feed",
             urls=["https://data.delaware.gov/resource/ever-58ni.json", "https://recwaters.dnrec.delaware.gov/"],
             method="json", legal_basis=None, basis_kind="voluntary", monitored=False,
             unmonitored_reason="feed_ingested", feed_source_id="de-dnrec-recreational-water", publishes="notices",
             noun="Data feed", sources=["de-dnrec-recreational-water"],
             note=("DNREC's advisory and closure history on the state's open-data portal (474 rows since 2001 on "
                   "2026-11-14) and the map's 47 sampling stations with their current status; bacteria advisories, "
                   "not sewage reports."),
             barrier=None),
        base(agency="Delaware Department of Natural Resources and Environmental Control", id="de-dnrec-beach-email-list",
             name="Delaware DNREC (beach advisory e-mail list)", channel_kind="email_list", urls=[], method=None,
             legal_basis=None, basis_kind="voluntary", monitored=False, unmonitored_reason="email_only",
             publishes="notices", records=False, noun="Alert list", sources=["de-dnrec-recreational-water"],
             note=("DNREC's map invites subscriptions to the dnrec_beach_monitoring list (by e-mail to the state's "
                   "listserv) for the beach advisories it issues; the same advisories are on the map and the portal."),
             barrier="no_web_page"),
        base(agency="Delaware Department of Natural Resources and Environmental Control", id="de-dnrec-shellfish",
             name="Delaware DNREC (shellfish program)", channel_kind="state_alert_page",
             urls=["https://dnrec.delaware.gov/watershed-stewardship/assessment/shellfish/"], method="html",
             legal_basis=None, basis_kind="voluntary", monitored=True, unmonitored_reason=None, publishes="documents",
             records=False, every_hours=24, noun="Voluntary page", sources=["de-dnrec-shellfish"],
             note=("Harvest-area classifications and links; emergency closures after a sewage release are announced as "
                   "state news releases (Indian River Bay, 2026-01-15 and its reopening 2026-02-06). Harvest "
                   "restrictions, not swimming advisories. Watched daily."),
             barrier=None),
        base(agency="Delaware Department of Natural Resources and Environmental Control", id="de-dnrec-blue-green-algae",
             name="Delaware DNREC (blue-green algae page)", channel_kind="state_alert_page",
             urls=["https://dnrec.delaware.gov/watershed-stewardship/assessment/blue-green-algae/"], method="html",
             legal_basis=None, basis_kind="voluntary", monitored=True, unmonitored_reason=None, publishes="documents",
             records=False, every_hours=24, noun="Voluntary page", sources=["de-dnrec-hab"],
             note=("Guidance and a reporting route; no dated bloom advisory list was found (2026-11-09). Bloom "
                   "advisories at monitored beaches appear in the recreational-water history. Watched daily."),
             barrier=None),
        base(agency="U.S. Environmental Protection Agency (ECHO)", id="de-epa-echo-overflow-events",
             name="U.S. Environmental Protection Agency (ECHO)", channel_kind="feed",
             urls=["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], method="html",
             legal_basis=None, basis_kind="voluntary", monitored=True, unmonitored_reason=None, publishes="notices",
             records=False, every_hours=24, noun="Data feed", sources=["de-epa-sobe"],
             note=("EPA's eRule sewer overflow and bypass tables: no Delaware row in the current or the all-versions "
                   "extract on 2026-11-14. Watched daily for Delaware rows."),
             barrier=None),
    ]
    return sorted(out, key=lambda c: c["id"])


def main() -> int:
    doc = {"about": ("Public-notice channels per operator or agency: pages, sites, feeds, lists and accounts through "
                     "which the public is told of sewage discharges, by law, permit or voluntarily. Read by "
                     "pipeline/ingest/notification_pages.py (schema and validator there; test "
                     "tests/test_notice_channels.py)."),
           "schema_version": 1, "state": "DE", "channels": rows()}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(doc['channels'])} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
