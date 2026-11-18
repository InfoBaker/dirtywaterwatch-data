"""A fixed world of invented e-mail notices for the e-mail feed's equivalence test (tests/test_mail_feed_split.py).

Nothing here is a real message: the operators' layouts are copied from tests/test_operator_mail.py, the names, numbers
and contacts are made up. The world has every list kind and every result a message can have (notice, a notice chain,
an update, a platform-only notice held back and one linked to the portal, unverified, failed, account, not_notice,
needs_rule, context, correspondence, an unknown address, a pending list, a fetch failure retried), the MassDEP lookups
the Massachusetts parsers place an outfall with (ctx), and the other sources' records the lists link to (others).

tests/fixtures/mail-feed/golden.json holds what the single-process feed (ingest/operator_mail.py before the split,
data repository 862eb00) wrote for this world, step by step; the split feed (the private read, the inbox files, the
public link) must write the same records. Regenerate it only for a parser change made on purpose:
    python -m tests.mail_feed_world --write-golden     (from pipeline/)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "mail-feed" / "golden.json"
NOW = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)

LISTS = {
    "holyoke": {"kind": "notices", "parser": "holyoke", "source_id": "ma-holyoke-everbridge",
                "address": "holyoke@dirtywaterwatch.org", "operator": "ma-holyoke", "npdes_permit": "MA0101630",
                "outfall_prefix": "HOL", "town": "HOLYOKE", "senders": ["holyoke.org"],
                "platform": {"domains": ["everbridge.net"], "allow_platform_from": True,
                             "body_marks": ["MA0101630", "453003085611624"], "header_marks": []},
                "since": "2026-11-17T01:00:00Z",
                "quiet": {"cross_check": {"source_id": "ma-massdep", "npdes_permit": "MA0101630"}},
                "source_url": "https://www.holyoke.org/emergency-notification-system/"},
    "springfield": {"kind": "notices", "parser": "springfield", "source_id": "ma-swsc-cso-email",
                    "address": "springfield@dirtywaterwatch.org", "operator": "ma-springfield-wsc",
                    "npdes_permit": "MA0101613", "outfall_prefix": "SPR", "town": "SPRINGFIELD",
                    "senders": ["waterandsewer.org"],
                    "platform": {"domains": ["ccsend.com"], "allow_platform_from": False, "body_marks": [],
                                 "header_marks": []},
                    "since": "2026-11-02T21:00:00Z",
                    "quiet": {"cross_check": {"source_id": "ma-massdep", "npdes_permit": "MA0101613"}},
                    "source_url": "https://springfieldalerts.com/Suez/"},
    "somerville": {"kind": "notices", "parser": "somerville", "source_id": "ma-somerville-cso-email",
                   "address": "somerville@dirtywaterwatch.org", "operator": "ma-somerville", "npdes_permit": "MA0101982",
                   "outfall_prefix": "SOM", "town": "SOMERVILLE", "senders": ["somervillema.gov"],
                   "since": "2026-11-02T21:40:00Z", "quiet": {"cross_check": {"source_id": "ma-massdep",
                                                                              "npdes_permit": "MA0101982"}}},
    "manchester": {"kind": "notices", "parser": "manchester", "source_id": "nh-manchester-cso-email",
                   "address": "manchester@dirtywaterwatch.org", "operator": "nh-manchester-epd",
                   "npdes_permit": "NH0100447", "senders": ["manchesternh.gov"],
                   "since": "2026-11-02T21:30:00Z",
                   "quiet": {"cross_check": {"source_id": "nh-permittees", "record_prefix": "manchester:",
                                             "raw_kind": "activation"}}},
    "ct-deep-press": {"kind": "notices", "parser": "ct_deep_press", "source_id": "ct-deep-press-email",
                      "address": "ct-deep-press@dirtywaterwatch.org", "senders": ["ct.gov"],
                      "since": "2026-11-02T21:00:00Z", "quiet": {"max_quiet_days": 10}},
    "usgs-waterdata": {"kind": "context", "address": "usgs-waterdata@dirtywaterwatch.org"},
    "ct-deep": {"kind": "correspondence", "address": "ct-deep@dirtywaterwatch.org"},
    "revere": {"kind": "pending", "address": "revere@dirtywaterwatch.org", "since": "2026-11-17T05:20:00Z"},
}

HOLYOKE = """Permittee : City of Holyoke Wastewater Pollution Control Permit #MA0101630
Location: CSO 021B
For a map of the location visit www.holyoke.org
Time of discharge: 01/10/26 18:55:00 EST
Estimated Volume (gallons): 225,192
The estimated volume is calculated by taking the total overflow volume for the last 3 years and dividing by the total number of overflow event for the last 3 years.
This Discharge is Active CSO at this time.
Affected Water Bodies: Connecticut River
Avoid contact with these waterbodies for 48 hours after the discharge ceases due to increased health risks from bacteria and other pollutants. The discharge consists of rainwater and untreated sewage and waste.
Affected communities: Springfield, West Springfield, Agawam
For questions call 413-555-0142 or write to wpc.desk@example.org.
Unsubscribe: if you no longer wish to receive these emails, please go to https://member.everbridge.net/453003085611624/login
"""
HOLYOKE_CEASED = HOLYOKE.replace("01/10/26 18:55:00", "01/10/26 22:40:00").replace(
    "This Discharge is Active CSO at this time.", "This Discharge is Ceased at this time.")
HOLYOKE_UPDATE = HOLYOKE.replace("This Discharge is Active CSO at this time.",
                                 "This Discharge is Active for 8 hours at this time.")
HOLYOKE_OTHER = HOLYOKE.replace("CSO 021B", "CSO 018").replace("01/10/26 18:55:00", "02/03/26 07:10:00")
HOLYOKE_FAR = HOLYOKE.replace("CSO 021B", "CSO 007").replace("01/10/26 18:55:00", "03/03/26 05:00:00")

SPRINGFIELD = """CSO Public Advisory Notice
Permittee: Springfield Water and Sewer Commission, Permit MA0101613
Outfall: SPR012 (Worthington Street)
Start Date and Time: 11/06/2026 11:00 AM
Status: Ongoing
Estimated Volume: 1,250,000 gallons
Receiving Water: Connecticut River
Affected Communities: Springfield, Longmeadow
The discharge contains untreated sewage and stormwater.
Avoid contact with these water bodies for 48 hours after the discharge or overflow ceases due to increased health risks from bacteria and other pollutants.
Aviso de aviso público de CSO
Ubicación: SPR012
"""
SPRINGFIELD_CEASED = SPRINGFIELD.replace("Status: Ongoing", "Status: Ceased").replace(
    "Estimated Volume:", "Time of Cessation: 11/06/2026 2:15 PM\nEstimated Volume:")

SOMERVILLE = ("CSO Activation Notifications\nCombined Sewer Overflow (CSO) Event on July 22, 2026 at 4:25 p.m.  at SOM-001A "
              "on the Alewife Brook\nPublic Health Warning: Public health officials recommend avoiding contact with water "
              "bodies during rainstorms and for 48 hours afterwards, as there may be increased health risks.\n"
              "Questions: 617-555-0199")

MAN_ACT = ("Please be advised that the City of Manchester has experienced CSO activations due to heavy rain and "
           "corresponding high flows.\nFor more detailed CSO discharge information please go to EPD's website.")
MAN_CLEAR = ("Please be advised that the City of Manchester has experienced no CSO activations during the past 12 "
             "hours.\nFor more detailed CSO discharge information please go to EPD's website.")


def eml(frm: str, to: str, subject: str, body: str, *, auth: str | None = None, html: bool = False,
        date: str = "Sat, 10 Jan 2026 19:01:00 -0500") -> bytes:
    m = EmailMessage()
    if auth is not None:
        m["Authentication-Results"] = auth
    m["From"], m["To"], m["Subject"], m["Date"] = frm, to, subject, date
    if html:
        m.set_content("<html><body>" + "".join(f"<p>{line}</p>" for line in body.split("\n")) + "</body></html>",
                      subtype="html")
    else:
        m.set_content(body)
    return bytes(m)


def cf(domain: str) -> str:
    return (f"mx.cloudflare.net; dkim=pass header.d={domain} header.s=s1 header.b=abc; dmarc=pass "
            f"header.from={domain} policy.dmarc=quarantine; spf=none")


def messages() -> list[tuple[str, str, str, bytes]]:
    """(inbound id, list id, receipt time, raw message), in the order the index lists them."""
    H, EB = "City of Holyoke <cso@holyoke.org>", "City of Holyoke <noreply@everbridge.net>"
    S = "SWSC Alerts <alerts@waterandsewer.org>"
    out = [
        ("h1", "holyoke", "2026-01-11T00:05:00Z", eml(H, "holyoke@x", "CSO Notification", HOLYOKE, auth=cf("holyoke.org"))),
        ("h2", "holyoke", "2026-01-11T08:05:00Z", eml(H, "holyoke@x", "CSO Notification", HOLYOKE_UPDATE,
                                                      auth=cf("holyoke.org"))),
        ("h3", "holyoke", "2026-01-11T03:50:00Z", eml(H, "holyoke@x", "CSO Notification", HOLYOKE_CEASED,
                                                      auth=cf("holyoke.org"))),
        ("h4", "holyoke", "2026-02-03T12:20:00Z", eml(EB, "holyoke@x", "CSO Notification", HOLYOKE_OTHER,
                                                      auth=cf("everbridge.net"))),          # platform only, linked
        ("h5", "holyoke", "2026-03-03T10:10:00Z", eml(EB, "holyoke@x", "CSO Notification", HOLYOKE_FAR,
                                                      auth=cf("everbridge.net"))),          # platform only, held back
        ("h6", "holyoke", "2026-11-17T02:01:00Z", eml("Fake <noreply@everbridge.net>", "holyoke@x", "CSO Notification",
                                                      HOLYOKE, auth="mx.cloudflare.net; dkim=none; dmarc=fail "
                                                                    "header.from=everbridge.net")),   # unverified
        ("h7", "holyoke", "2026-11-17T02:02:00Z", eml(H, "holyoke@x", "CSO Notification",
                                                      "Dear Health Official: a table we do not read",
                                                      auth=cf("holyoke.org"))),             # failed
        ("h8", "holyoke", "2026-11-17T02:03:00Z", eml(EB, "holyoke@x", "Your Everbridge Community Verification Code",
                                                      "Your code is 000000.", auth=cf("everbridge.net"))),  # account
        ("s1", "springfield", "2026-11-06T16:31:00Z", eml(S, "springfield@x", "CSO Public Advisory", SPRINGFIELD,
                                                          auth=cf("waterandsewer.org"),
                                                          date="Fri, 06 Nov 2026 11:30:00 -0500")),
        ("s2", "springfield", "2026-11-06T19:20:00Z", eml(S, "springfield@x", "CSO Public Advisory", SPRINGFIELD_CEASED,
                                                          auth=cf("waterandsewer.org"), html=True,
                                                          date="Fri, 06 Nov 2026 14:19:00 -0500")),
        ("v1", "somerville", "2026-07-22T20:40:00Z", eml("City of Somerville <notify@somervillema.gov>", "somerville@x",
                                                         "CSO Activation", SOMERVILLE, auth=cf("somervillema.gov"))),
        ("m1", "manchester", "2026-11-06T22:03:42Z", eml("newsletter@manchesternh.gov", "manchester@x",
                                                         "City Of Manchester CSO Notification - Activation", MAN_ACT,
                                                         auth=cf("manchesternh.gov"), html=True,
                                                         date="Fri, 06 Nov 2026 17:03:40 -0500")),
        ("m2", "manchester", "2026-11-08T21:57:29Z", eml("newsletter@manchesternh.gov", "manchester@x",
                                                         "City Of Manchester CSO Notification - No Activations for 12 Hours",
                                                         MAN_CLEAR, auth=cf("manchesternh.gov"), html=True,
                                                         date="Sun, 08 Nov 2026 16:57:28 -0500")),
        ("c1", "ct-deep-press", "2026-11-16T21:47:23Z", eml("DEEP <news@ct.gov>", "ct-deep-press@x",
                                                            "Deer Hunting Season Begins", "Hunters are reminded ...",
                                                            auth=cf("ct.gov"))),
        ("c2", "ct-deep-press", "2026-11-16T22:00:00Z", eml("DEEP <news@ct.gov>", "ct-deep-press@x", "DEEP advises the public",
                                                            "Avoid contact with the river after a sewage spill in Town.",
                                                            auth=cf("ct.gov"))),
        ("u1", "usgs-waterdata", "2026-11-17T02:03:00Z", eml("USGS <news@usgs.gov>", "usgs-waterdata@x", "Bulletin",
                                                             "News.", auth=cf("usgs.gov"))),
        ("o1", "ct-deep", "2026-11-17T02:05:00Z", eml("Owner <owner@example.com>", "ct-deep@x", "Letter", "A letter.",
                                                      auth=cf("example.com"))),
        ("x1", "stranger", "2026-11-17T02:04:00Z", eml("Someone <someone@example.com>", "stranger@x", "Hello", "Hi.",
                                                       auth=cf("example.com"))),
        ("r1", "revere", "2026-11-17T06:00:00Z", eml("Revere <alerts@publicinput.com>", "revere@x",
                                                     "Please confirm your subscription", "Click.",
                                                     auth=cf("publicinput.com"))),
    ]
    return out


def rows_and_raws(missing: tuple[str, ...] = ()) -> tuple[list[dict], dict]:
    rows, raws = [], {}
    for mid, lid, received, raw in messages():
        key = f"email/2026/11/17/{mid}.eml"
        rows.append({"id": mid, "received_at": received, "list_id": lid, "raw_key": key, "size": len(raw)})
        if mid not in missing:
            raws[key] = raw
    return rows, raws


class FakeTransport:
    """The mail index and archive in memory (operator_mail's transport contract: rows(), raw(key))."""

    def __init__(self, rows, raws, fail_rows=False):
        self._rows, self.raws, self.fail_rows, self.reads = rows, raws, fail_rows, 0

    def rows(self):
        if self.fail_rows:
            raise RuntimeError("D1 inbound index answered HTTP 403 (10000: Authentication error)")
        return self._rows

    def raw(self, key):
        self.reads += 1
        if key not in self.raws:
            raise RuntimeError("R2 object answered HTTP 404")
        return self.raws[key]


def ctx() -> dict:
    """ingest.ma_massdep's lookups, as ma_context loads them, for the outfalls of this world."""
    layer = {
        "HOL021": {"dep_id": "HOL021", "npdes": "MA0101630", "outfall": "021", "system": "Holyoke",
                   "receiving_water": "CONNECTICUT RIVER", "address": "Example Street at the river", "town": "HOLYOKE",
                   "lat": 42.2041234, "lon": -72.6012345},
        "SPR012": {"dep_id": "SPR012", "npdes": "MA0101613", "outfall": "012", "system": "Springfield",
                   "receiving_water": "CONNECTICUT RIVER", "address": "Worthington Street", "town": "SPRINGFIELD",
                   "lat": 42.1051234, "lon": -72.5961234},
    }
    echo = {
        ("MA0101630", "018"): {"npdes_permit": "MA0101630", "outfall": "018", "lat": 42.2, "lon": -72.61,
                               "water_slug": "connecticut-river-ma", "water_name": "Connecticut River",
                               "match": "geometry+name", "distance_m": 14},
        ("MA0101982", "001A"): {"npdes_permit": "MA0101982", "outfall": "001A", "lat": 42.4, "lon": -71.13,
                                "water_slug": "alewife-brook-ma", "water_name": "Alewife Brook",
                                "match": "geometry", "distance_m": 40},
    }
    crosswalk = {"CONNECTICUT RIVER": ("connecticut-river-ma", "high", "")}
    crosswalk["N:CONNECTICUT RIVER"] = crosswalk["CONNECTICUT RIVER"]
    waters = defaultdict(list)
    waters["ALEWIFE BROOK"].append(("alewife-brook-ma", {"SOMERVILLE", "CAMBRIDGE", "ARLINGTON"}))
    return {"echo": echo, "crosswalk": crosswalk, "waters": waters, "layer": layer}


def portal(eid, permit, outfall, start, published, parent=None, status="ongoing"):
    return {"event_id": f"ma-massdep:{eid}", "source_record_id": eid, "npdes_permit": permit, "outfall_id": outfall,
            "started_at": start, "published_at": published, "parent_event_id": parent and f"ma-massdep:{parent}",
            "status": status, "raw": {}}


def others() -> dict:
    """The same run's records of the sources the lists link to (ma-massdep, nh-permittees)."""
    return {
        "ma-massdep": [
            portal("p1", "MA0101630", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00"),
            portal("p2", "MA0101630", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-13T09:00:00-05:00", parent="p1",
                   status="ended"),
            portal("p3", "MA0101630", "HOL018", "2026-02-03T07:00:00-05:00", "2026-02-04T09:00:00-05:00"),
            portal("p4", "MA0101630", "HOL018", "2026-11-17T00:30:00-05:00", "2026-11-17T01:00:00-05:00"),  # quiet
            portal("p5", "MA0101613", "SPR012", "2026-11-06T10:50:00-05:00", "2026-11-06T13:00:00-05:00"),
        ],
        "nh-permittees": [
            {"event_id": "nh-permittees:manchester:Item1", "source_record_id": "manchester:Item1",
             "reported_at": "2026-11-06T17:00:00-05:00", "published_at": "2026-11-06T17:00:00-05:00",
             "started_at": None, "raw": {"kind": "activation"}},
        ],
    }


# the steps of the world: (clock, inbound ids whose raw message cannot be fetched, whether the index read fails)
STEPS = [
    (NOW, ("s2",), False),                          # Springfield's Ceased notice cannot be fetched: tried again later
    (NOW + timedelta(hours=2), (), False),          # read now; everything else is not read again
    (NOW + timedelta(hours=3), (), True),           # the index cannot be read: every list keeps its records
]


def write_others(events_dir: Path) -> None:
    events_dir.mkdir(parents=True, exist_ok=True)
    for sid, recs in others().items():
        (events_dir / f"{sid}.json").write_text(json.dumps({"source_id": sid, "records": recs}))


def notice_sources() -> list[str]:
    return sorted(v["source_id"] for v in LISTS.values() if v.get("kind") == "notices")


def snapshot(events_dir: Path) -> dict:
    return {sid: json.loads((events_dir / f"{sid}.json").read_text()) for sid in notice_sources()}


def _write_golden_with_the_single_process_feed() -> None:     # pragma: no cover - run by hand
    """The golden file from ingest/operator_mail.run as it was before the split (data repository 862eb00)."""
    import tempfile

    import common
    from ingest import operator_mail as O
    O.ma_context = lambda lists: ctx()
    out = []
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        write_others(d / "events")
        for now, missing, fail in STEPS:
            common.now_iso = lambda now=now: now.strftime("%Y-%m-%dT%H:%M:%SZ")
            rows, raws = rows_and_raws(missing)
            O.run(FakeTransport(rows, raws, fail), LISTS, d / "inbound-mail.json", d / "events", now=now)
            out.append(snapshot(d / "events"))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps({"_about": "ingest/operator_mail.run (single process, before the split, data "
                                            "repository 862eb00) on tests/mail_feed_world.py, one entry per step",
                                  "steps": out}, indent=1, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":     # pragma: no cover
    if "--write-golden" in sys.argv:
        _write_golden_with_the_single_process_feed()
