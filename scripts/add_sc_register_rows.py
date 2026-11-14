"""South Carolina's rows of the public-notice register: data/notice-channels/sc.json (one row per channel per operator
or agency: law, permit and voluntary).

Usage: pipeline/.venv/bin/python -I scripts/add_sc_register_rows.py

Rows
  - Every South Carolina operator of data/dischargers.json (scripts/add_sc_operators.py): the public notice S.C. Code
    48-1-95(E) requires of a significant spill (5,000 gallons or more) within 24 hours of discovery, through no named
    channel; the operator's own pages were not searched individually (barrier not_verified), except:
    the City of Florence, whose overflow notices this site reads (feed sc-florence-sso-notices), and Charleston Water
    System, whose news page is watched (its host did not answer this site's client on 2026-11-14) and whose
    "Notify Me" alerts are e-mail only.
  - DES: the overflow reports utilities file (48-1-95(B); DES publishes no list; the ePermitting "SSO Discharge Search"
    its training material shows could not be read without a browser session), the beach monitoring station layer
    (feed), the beach program page with its short-term advisory table (watched), the bloom delineations and table
    (feed), the freshwater swimming-advisory layer (not read: what a site on it means is not published), the shellfish
    closure map (an app shell) and DES's news releases (watched).
  - Charleston Waterkeeper's Swim Alert (independent sampling, weekly May to October; watched, no records).
  - EPA's eRule overflow tables: no South Carolina row in the current or the all-versions extract on 2026-11-14.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "notice-channels" / "sc.json"
DIS = ROOT / "data" / "dischargers.json"
CHECKED = "2026-11-14"
LAW_E = ("S.C. Code 48-1-95(E): \"The department shall require that all wastewater utilities provide public notice of "
         "any significant spill of five thousand gallons or more within twenty-four hours of the discovery\"; DES gives "
         "the notice when the utility does not; no channel is named")
LAW_B = ("S.C. Code 48-1-95(B): \"Utilities must verbally notify the department of any significant spill within "
         "twenty-four hours\", in writing within five days")
DES = "South Carolina Department of Environmental Services"
FLORENCE_NEWS = "https://www.cityofflorencesc.gov/city-news"
CWS_NEWS = "https://www.charlestonwater.com/m/newsflash"


def base(**kw) -> dict:
    row = {"state": "SC", "operator_id": None, "agency": None, "permit": None, "checked": CHECKED}
    row.update(kw)
    return row


def rows() -> list[dict]:
    dis = [r for r in json.loads(DIS.read_text()) if r.get("state") == "SC"]
    out = []
    for r in dis:
        if r["id"] == "sc-florence":
            out.append(base(
                operator_id=r["id"], id="sc-florence-sso-notices", name="City of Florence (sewer overflow notices)",
                channel_kind="news_page", urls=[FLORENCE_NEWS], method="html", legal_basis=LAW_E, basis_kind="law",
                monitored=False, unmonitored_reason="feed_ingested", feed_source_id="sc-florence-sso-notices",
                publishes="notices", noun="Data feed", sources=["sc-florence-sso-notices", "sc-law-48-1-95"],
                note=("The City posts a 'Notification of Sanitary Sewer Overflow' news release for each overflow of "
                      "5,000 gallons or more (five on 2026-11-14, March 2024 to October 2025, all on Jeffries Creek), "
                      "read by this site."),
                barrier=None))
            continue
        if r["id"] == "sc-charleston-water-system":
            out += [
                base(operator_id=r["id"], permit="SC0021229", id="sc-charleston-water-news",
                     name="Charleston Water System (news)", channel_kind="news_page", urls=[CWS_NEWS], method="html",
                     legal_basis=LAW_E, basis_kind="law", monitored=True, unmonitored_reason=None, publishes="notices",
                     records=False, every_hours=24, noun="Notification page",
                     sources=["sc-charleston-water-notices", "sc-law-48-1-95"],
                     note=("Charleston Water System posts overflow and line-break news (its October 20, 2026 article was "
                           "later rewritten for another break, so an article's address is not one overflow). Its host "
                           "did not answer this site's client on 2026-11-14 (connection timed out); watched daily, no "
                           "records until it can be read."),
                     barrier=None),
                base(operator_id=r["id"], permit="SC0021229", id="sc-charleston-water-notify-me",
                     name="Charleston Water System (Notify Me alerts)", channel_kind="email_list", urls=[], method=None,
                     legal_basis=("Settlement with Charleston Waterkeeper (2026): overflow alerts for West Ashley and "
                                  "quarterly public reports; the executed agreement was not read"),
                     basis_kind="voluntary", monitored=False, unmonitored_reason="email_only", publishes="unknown",
                     records=False, noun="Alert list", sources=["sc-charleston-water-notices"],
                     note=("The site links a 'Notify Me' sign-up; whether it carries overflow alerts was not verified "
                           "(its page failed in the research, 2026-11-09). Sent to subscribers; no page to read."),
                     barrier="no_web_page"),
            ]
            continue
        out.append(base(
            operator_id=r["id"], permit=r.get("npdes_permit"), id=f"{r['id']}-public-notice", name=r["name"],
            channel_kind="operator_page", urls=[], method=None, legal_basis=LAW_E, basis_kind="law", monitored=False,
            unmonitored_reason="other", publishes="unknown", records=False, noun="Public notice",
            sources=["sc-law-48-1-95"],
            note=(f"{r['name']} must give public notice of a spill of 5,000 gallons or more within 24 hours of "
                  "discovery (48-1-95(E)), through a channel of its choosing. Not searched individually."),
            barrier="not_verified"))
    out += [
        base(agency=DES, id="sc-des-sso-reports", name="SC DES (sewer overflow reports under 48-1-95(B))",
             channel_kind="state_alert_page", urls=[], method=None, legal_basis=LAW_B, basis_kind="law", monitored=False,
             unmonitored_reason="other", publishes="none", records=False, noun="Report to the state",
             sources=["sc-des-sso-database", "sc-des-sso-reporting"],
             note=("Utilities report significant spills to DES by telephone within 24 hours and in writing within five "
                   "days, and DES's guidance asks for reports of any overflow reaching water and of larger ones that do "
                   "not; DES publishes no list. DES training material shows an 'SSO Discharge Search' among "
                   "ePermitting's public services (https://epermitting.des.sc.gov/ext/ncore/), but the application "
                   "returned only its shell to a plain client on 2026-11-09 and no search result was read. No web "
                   "channel found."),
             barrier="no_web_page"),
        base(agency=DES, id="sc-des-beach-monitoring", name="SC DES (beach monitoring stations)", channel_kind="feed",
             urls=["https://gis.des.sc.gov/gisserver/rest/services/water/BW_Monitoring_Stations/MapServer/0"],
             method="json", legal_basis=None, basis_kind="voluntary", monitored=False,
             unmonitored_reason="feed_ingested", feed_source_id="sc-des-beach-monitoring", publishes="status",
             noun="Data feed", sources=["sc-des-beach-monitoring"],
             note=("The S.C. Beach Access Guide's station layer: 123 stations on 2026-11-14, 21 under a long-term "
                   "advisory (20 in Horry County, three at Edisto Beach), the rest 'No Advisory' (out of season)."),
             barrier=None),
        base(agency=DES, id="sc-des-beach-page", name="SC DES (beach monitoring page)", channel_kind="state_alert_page",
             urls=["https://des.sc.gov/programs/bureau-water/aquatic-science/beach-monitoring"], method="html",
             legal_basis=None, basis_kind="voluntary", monitored=True, unmonitored_reason=None, publishes="notices",
             records=False, noun="Voluntary page", sources=["sc-des-beach-monitoring"],
             note=("The program page's table of active short-term swim advisories (empty on 2026-11-14) and its FAQ; "
                   "the station layer carries the same advisories. Watched."),
             barrier=None),
        base(agency=DES, id="sc-des-hab", name="SC DES (harmful algal bloom watches and advisories)", channel_kind="feed",
             urls=["https://services5.arcgis.com/OMDIQXm11z4wcK26/arcgis/rest/services/algal_hydro_2_view/FeatureServer/0",
                   "https://des.sc.gov/programs/bureau-water/aquatic-science/harmful-algal-blooms"],
             method="json", legal_basis=None, basis_kind="voluntary", monitored=False,
             unmonitored_reason="feed_ingested", feed_source_id="sc-des-hab", publishes="notices", noun="Data feed",
             sources=["sc-des-hab"],
             note=("DES's bloom delineations (897 on 2026-11-14, one a Watch: Cedar Point Cove, J. Strom Thurmond, "
                   "dated 2026-10-16) and the program page's table of active watches and advisories. Blooms, not "
                   "sewage."),
             barrier=None),
        base(agency=DES, id="sc-des-freshwater-swim-advisories", name="SC DES (freshwater swimming advisory sites)",
             channel_kind="state_alert_page",
             urls=["https://gis.des.sc.gov/gisserver/rest/services/water/Water_Advisories/MapServer/0"], method="json",
             legal_basis=None, basis_kind="voluntary", monitored=False, unmonitored_reason="other", publishes="unknown",
             records=False, noun="Voluntary page", sources=["sc-des-freshwater-swim-advisories"],
             note=("A layer named 'Swimming Advisory' with 23 river and lake sites (name, station, point; a contact and "
                   "telephone field not read) and no date or status; DES's pages do not say what a site on it means. "
                   "Listed in the research as not checked against DES; not read until DES confirms its meaning."),
             barrier="not_verified"),
        base(agency=DES, id="sc-des-shellfish-closures", name="SC DES (shellfish closure map)",
             channel_kind="state_alert_page", urls=[], method=None, legal_basis=None, basis_kind="voluntary",
             monitored=False, unmonitored_reason="app_only", publishes="notices", records=False,
             noun="Voluntary page", sources=["sc-des-shellfish"],
             note=("The closure viewer (https://gis.des.sc.gov/shellfishclosures/) returned only its shell to a plain "
                   "client; closures after heavy rain are also announced in DES's news releases. Harvest restrictions, "
                   "not swimming advisories or sewage reports."),
             barrier=None, barrier_review="an app shell with no readable feature layer found; no login wall"),
        base(agency=DES, id="sc-des-news", name="SC DES (news releases)", channel_kind="news_page",
             urls=["https://des.sc.gov/news"], method="html", legal_basis=None, basis_kind="voluntary", monitored=True,
             unmonitored_reason=None, publishes="notices", records=False, every_hours=24, noun="Voluntary page",
             sources=["sc-des-beach-monitoring", "sc-des-shellfish"],
             note=("DES announces swim advisories it issues and lifts (Edisto Beach, August 2025) and shellfish closures "
                   "and reopenings in its news releases; watched daily, no records."),
             barrier=None),
        base(agency="Charleston Waterkeeper", id="sc-charleston-waterkeeper-swim-alert",
             name="Charleston Waterkeeper (Swim Alert)", channel_kind="group_results",
             urls=["https://charlestonwaterkeeper.org/swimalert/"], method="html", legal_basis=None,
             basis_kind="voluntary", monitored=True, unmonitored_reason=None, publishes="results", records=False,
             every_hours=24, noun="Voluntary page", sources=["sc-charleston-waterkeeper"],
             note=("Independent bacteria sampling at about 20 sites, weekly from May to October; sample results, not "
                   "an authority's advisory or a sewage report. Watched daily."),
             barrier=None),
        base(agency="U.S. Environmental Protection Agency (ECHO)", id="sc-epa-echo-overflow-events",
             name="U.S. Environmental Protection Agency (ECHO)", channel_kind="feed",
             urls=["https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"], method="html",
             legal_basis=None, basis_kind="voluntary", monitored=True, unmonitored_reason=None, publishes="notices",
             records=False, every_hours=24, noun="Data feed", sources=["sc-epa-sobe"],
             note=("EPA's eRule sewer overflow and bypass tables: no South Carolina row in the current or the "
                   "all-versions extract on 2026-11-14. Watched daily for South Carolina rows."),
             barrier=None),
    ]
    return sorted(out, key=lambda c: c["id"])


def main() -> int:
    doc = {"about": ("Public-notice channels per operator or agency: pages, sites, feeds, lists and accounts through "
                     "which the public is told of sewage discharges, by law, permit or voluntarily. Read by "
                     "pipeline/ingest/notification_pages.py (schema and validator there; test "
                     "tests/test_notice_channels.py)."),
           "schema_version": 1, "state": "SC", "channels": rows()}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {len(doc['channels'])} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
