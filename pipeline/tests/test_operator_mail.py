"""Operators' e-mail notices: invented messages in the real shapes. Since the split (2026-11-18) the read (the index,
the archive, trust, the parsers, retries: pipeline/mailfeed/read.py, run by the site repository's mail-feed job) and the
link (placement, the one-event rules, the platform hold, the quiet check: ingest/operator_mail.py, run by the refresh)
are tested here side by side; run_feed runs both, the way the job and the refresh do one after the other.

Nothing here is a real message: the operators' layouts are copied, the names, numbers and contacts are made up."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest

from ingest import operator_mail as O
from ingest.mail import PARSERS, ct_deep_press, holyoke, manchester, springfield
from ingest.mail.message import Mail, parse_mail, read_auth, verified
from mailfeed import read as R

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
                    "platform": {"domains": ["ccsend.com"], "allow_platform_from": False, "body_marks": [], "header_marks": []},
                    "since": "2026-11-02T21:00:00Z",
                    "quiet": {"cross_check": {"source_id": "ma-massdep", "npdes_permit": "MA0101613"}},
                    "source_url": "https://springfieldalerts.com/Suez/"},
    "manchester": {"kind": "notices", "parser": "manchester", "source_id": "nh-manchester-cso-email",
                   "address": "manchester@dirtywaterwatch.org", "operator": "nh-manchester-epd",
                   "npdes_permit": "NH0100447", "senders": ["manchesternh.gov"],
                   "since": "2026-11-02T21:30:00Z",
                   "quiet": {"cross_check": {"source_id": "nh-permittees", "record_prefix": "manchester:",
                                             "raw_kind": "activation"}}},
    "ct-deep-press": {"kind": "notices", "parser": "ct_deep_press", "source_id": "ct-deep-press-email",
                      "senders": ["ct.gov"], "since": "2026-11-02T21:00:00Z", "quiet": {"max_quiet_days": 10}},
    "usgs-waterdata": {"kind": "context"},
    "ct-deep": {"kind": "correspondence"},
}

HOLYOKE_ACTIVE = """Permittee : City of Holyoke Wastewater Pollution Control Permit #MA0101630
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
______________________________
Titular del permiso: City of Holyoke Wastewater Pollution Control Permit #MA0101630
Ubicación: CSO 021B
Hora descarga (galones): 01/10/26 18:55:00 EST
El volumen estimado: 225,192
"""
HOLYOKE_CEASED = HOLYOKE_ACTIVE.replace("01/10/26 18:55:00", "01/10/26 22:40:00").replace(
    "This Discharge is Active CSO at this time.", "This Discharge is Ceased at this time.")

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


def eml(frm: str, to: str, subject: str, body: str, *, auth: str | None = None, html: bool = False,
        date: str = "Sat, 10 Jan 2026 19:01:00 -0500", forged: str | None = None) -> bytes:
    m = EmailMessage()
    if auth is not None:
        m["Authentication-Results"] = auth
    if forged is not None:
        m["Authentication-Results"] = forged
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


def mail_of(raw: bytes, list_id: str, mid: str = "m1", received: str = "2026-01-11T00:05:00Z") -> Mail:
    return parse_mail(raw, mid, received, list_id)


# ---------------------------------------------------------------- trust

def test_only_cloudflares_first_result_counts_and_a_forged_one_is_ignored():
    raw = eml("City of Holyoke <noreply@everbridge.net>", "holyoke@dirtywaterwatch.org", "CSO", HOLYOKE_ACTIVE,
              auth="mx.cloudflare.net; dkim=fail header.d=everbridge.net; dmarc=fail header.from=everbridge.net",
              forged=cf("everbridge.net"))
    m = mail_of(raw, "holyoke")
    ok, why = verified(m, LISTS["holyoke"])
    assert not ok and "neither" in why
    assert read_auth("someone.else.example; dmarc=pass header.from=everbridge.net") == (False, None, set())


def test_from_domain_must_be_the_lists_sender():
    raw = eml("Notices <alerts@example-impostor.net>", "holyoke@dirtywaterwatch.org", "CSO", HOLYOKE_ACTIVE,
              auth=cf("example-impostor.net"))
    ok, why = verified(mail_of(raw, "holyoke"), LISTS["holyoke"])
    assert not ok and "not one of the list's senders" in why


def test_dkim_of_the_lists_platform_counts_without_dmarc_alignment():
    raw = eml("SWSC Alerts <alerts@waterandsewer.org>", "springfield@dirtywaterwatch.org", "CSO", SPRINGFIELD,
              auth="mx.cloudflare.net; dkim=pass header.d=ccsend.com header.s=1000; dmarc=none header.from=waterandsewer.org")
    ok, why = verified(mail_of(raw, "springfield"), LISTS["springfield"])
    assert ok and "DKIM" in why


# ---------------------------------------------------------------- Holyoke

def test_holyoke_active_notice_reads_every_fact_and_no_contact():
    raw = eml("City of Holyoke <noreply@everbridge.net>", "holyoke@dirtywaterwatch.org", "CSO Notification",
              HOLYOKE_ACTIVE, auth=cf("everbridge.net"))
    res = holyoke.parse(mail_of(raw, "holyoke"), LISTS["holyoke"], {})
    assert res.kind == "notice" and len(res.records) == 1      # the Spanish half is not a second block
    r = res.records[0]
    assert r["event_id"] == "ma-holyoke-everbridge:m1:1"
    assert (r["event_type"], r["status"], r["npdes_permit"], r["outfall_id"]) == ("cso", "ongoing", "MA0101630", "CSO 021B")
    assert r["started_at"] == "2026-01-10T23:55:00Z"            # 18:55 Holyoke time in January
    assert r["ended_at"] is None and r["reported_at"] is None
    assert r["published_at"] == "2026-01-11T00:05:00Z"          # the receipt: publication, never a start
    assert (r["volume_gal"], r["volume_text"], r["estimate_flag"]) == (225192, "225,192", "estimated")
    assert "3 years" in r["raw"]["volume_method"]
    assert r["advice_window_hours"] == 48 and r["advice_text"].startswith("Avoid contact")
    assert r["waterbody_text"] == "Connecticut River" and r["material"].startswith("rainwater and untreated sewage")
    s = json.dumps(r)
    assert "413-555" not in s and "example.org" not in s and "wpc.desk" not in s


def test_holyoke_summer_time_is_read_as_the_local_clock():
    body = HOLYOKE_ACTIVE.replace("01/10/26 18:55:00", "07/31/25 10:05:00")
    raw = eml("City of Holyoke <noreply@everbridge.net>", "holyoke@dirtywaterwatch.org", "CSO", body, auth=cf("everbridge.net"))
    r = holyoke.parse(mail_of(raw, "holyoke"), LISTS["holyoke"], {}).records[0]
    assert r["started_at"] == "2025-07-31T14:05:00Z"


def test_holyoke_ceased_gives_the_end_not_a_start_and_joins_the_open_notice():
    a = holyoke.parse(mail_of(eml("C <n@everbridge.net>", "holyoke@x", "CSO", HOLYOKE_ACTIVE, auth=cf("everbridge.net")),
                              "holyoke", "a1"), LISTS["holyoke"], {}).records
    c = holyoke.parse(mail_of(eml("C <n@everbridge.net>", "holyoke@x", "CSO", HOLYOKE_CEASED, auth=cf("everbridge.net")),
                              "holyoke", "c1", "2026-01-11T03:50:00Z"), LISTS["holyoke"], {}).records
    assert c[0]["started_at"] is None and c[0]["ended_at"] == "2026-01-11T03:40:00Z" and c[0]["status"] == "ended"
    recs = a + c
    O.link_chains(recs)
    assert c[0]["parent_event_id"] == a[0]["event_id"]
    assert c[0]["started_at"] == a[0]["started_at"] and "earlier notice" in c[0]["raw"]["_started_at_basis"]
    assert c[0]["raw"]["_chain"] == a[0]["event_id"]


def test_holyoke_html_and_html_tables_read_alike():
    raw = eml("C <n@everbridge.net>", "holyoke@x", "CSO", HOLYOKE_ACTIVE, auth=cf("everbridge.net"), html=True)
    r = holyoke.parse(mail_of(raw, "holyoke"), LISTS["holyoke"], {}).records[0]
    assert r["volume_gal"] == 225192 and r["started_at"] == "2026-01-10T23:55:00Z"


@pytest.mark.parametrize("body, why", [
    ("Dear Health Official:\nPlease be advised that precipitation ... resulted in combined sewer overflow discharges.\n"
     "Site Receiving Waterbody Estimated Volume in Gallons\nCSO 18 Connecticut River 419,050", "no 'Permittee :' block"),
    (HOLYOKE_ACTIVE.replace("MA0101630", "MA0109999"), "is not the list's operator"),
    (HOLYOKE_ACTIVE.replace("This Discharge is Active CSO at this time.", "This Discharge is Paused at this time."),
     "status line not known"),
    (HOLYOKE_ACTIVE.replace("Time of discharge: 01/10/26 18:55:00 EST", "Time of discharge: soon"), "no date and time"),
])
def test_holyoke_unknown_shapes_fail_loudly(body, why):
    res = holyoke.parse(mail_of(eml("C <n@everbridge.net>", "holyoke@x", "CSO", body, auth=cf("everbridge.net")), "holyoke"),
                        LISTS["holyoke"], {})
    assert res.kind == "failed" and why in res.note and not res.records


def test_holyoke_verification_code_is_an_account_message():
    res = holyoke.parse(mail_of(eml("E <noreply@everbridge.net>", "holyoke@x", "Your Everbridge Community Verification Code",
                                    "Your code is 000000.", auth=cf("everbridge.net")), "holyoke"), LISTS["holyoke"], {})
    assert res.kind == "account" and not res.records


# ---------------------------------------------------------------- Springfield

def test_springfield_labelled_notice():
    raw = eml("SWSC <alerts@waterandsewer.org>", "springfield@x", "CSO Public Advisory - Notice Aviso de aviso público de CSO",
              SPRINGFIELD, auth=cf("waterandsewer.org"), date="Fri, 06 Nov 2026 11:30:00 -0500")
    res = springfield.parse(mail_of(raw, "springfield", "s1", "2026-11-06T16:31:00Z"), LISTS["springfield"], {})
    assert res.kind == "notice", res.note
    r = res.records[0]
    assert (r["outfall_id"], r["raw"]["_outfall_key"], r["status"]) == ("SPR012", 12, "ongoing")
    assert r["started_at"] == "2026-11-06T16:00:00Z" and r["published_at"] == "2026-11-06T16:31:00Z"
    assert (r["volume_gal"], r["estimate_flag"]) == (1250000, "estimated")
    assert r["waterbody_text"] == "Connecticut River" and r["advice_window_hours"] == 48


def test_springfield_cessation_and_html_cells():
    body = SPRINGFIELD.replace("Status: Ongoing", "Status: Ceased").replace(
        "Estimated Volume:", "Time of Cessation: 11/06/2026 2:15 PM\nEstimated Volume:")
    body = body.replace("Receiving Water: Connecticut River", "Receiving Water:\nConnecticut River")
    raw = eml("SWSC <alerts@waterandsewer.org>", "springfield@x", "CSO Public Advisory", body, auth=cf("waterandsewer.org"), html=True)
    r = springfield.parse(mail_of(raw, "springfield"), LISTS["springfield"], {}).records[0]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-06T19:15:00Z"
    assert r["waterbody_text"] == "Connecticut River"


@pytest.mark.parametrize("change, why", [
    (("Start Date and Time: 11/06/2026 11:00 AM\n", ""), "no start date and time"),
    (("Start Date and Time: 11/06/2026 11:00 AM", "Start Date and Time: 11/06/2026"), "no start date and time"),
    (("Outfall: SPR012 (Worthington Street)", "Outfall: SPR012 and SPR014"), "several outfall numbers"),
    (("Status: Ongoing\n", ""), "no status"),
    (("Outfall: SPR012 (Worthington Street)", "Where: Worthington Street"), "no outfall line"),
])
def test_springfield_strict_on_what_it_cannot_read(change, why):
    raw = eml("SWSC <alerts@waterandsewer.org>", "springfield@x", "CSO Public Advisory", SPRINGFIELD.replace(*change),
              auth=cf("waterandsewer.org"))
    res = springfield.parse(mail_of(raw, "springfield"), LISTS["springfield"], {})
    assert res.kind == "failed" and why in res.note and not res.records


def test_springfield_sign_up_confirmation_is_an_account_message():
    raw = eml("SWSC <alerts@waterandsewer.org>", "springfield@x", "Please confirm your subscription", "Click to confirm.",
              auth=cf("waterandsewer.org"))
    assert springfield.parse(mail_of(raw, "springfield"), LISTS["springfield"], {}).kind == "account"


# ---------------------------------------------------------------- Manchester

MAN_ACT = ("Please be advised that the City of Manchester has experienced CSO activations due to heavy rain and "
           "corresponding high flows.\nFor more detailed CSO discharge information please go to EPD's website.")
MAN_CLEAR = ("Please be advised that the City of Manchester has experienced no CSO activations during the past 12 "
             "hours.\nFor more detailed CSO discharge information please go to EPD's website.")


def man(body, mid, received, subject="City Of Manchester CSO Notification - Activation", date=None):
    raw = eml("newsletter@manchesternh.gov", "manchester@x", subject, body, auth=cf("manchesternh.gov"), html=True,
              date=date or "Fri, 06 Nov 2026 17:03:40 -0500")
    return PARSERS["manchester"].parse(mail_of(raw, "manchester", mid, received), LISTS["manchester"], {})


def test_manchester_activation_and_all_clear_pair_with_a_bound():
    a = man(MAN_ACT, "a", "2026-11-06T22:03:42Z").records
    c = man(MAN_CLEAR, "c", "2026-11-08T21:57:29Z", "City Of Manchester CSO Notification - No Activations for 12 Hours",
            date="Sun, 08 Nov 2026 16:57:28 -0500").records
    assert a[0]["status"] == "ongoing" and a[0]["started_at"] is None
    assert a[0]["reported_at"] == "2026-11-06T22:03:40Z" and a[0]["published_at"] == "2026-11-06T22:03:42Z"
    manchester.pair(a + c)
    assert a[0]["status"] == "ended" and a[0]["time_precision"] == "bound"
    assert a[0]["raw"]["_ended_before"].startswith("2026-11-08T09:57:28")
    assert c[0]["parent_event_id"] == a[0]["event_id"]


def test_manchester_welcome_is_not_a_notice_and_odd_cso_text_fails():
    assert man("Welcome to Manchester's e-Newsletters.", "w", "2026-11-02T21:34:20Z",
               subject="Welcome to Manchester's e-Newsletters").kind == "not_notice"
    assert man("Something changed in the CSO program.", "x", "2026-11-02T21:34:20Z").kind == "failed"


def test_manchester_email_is_the_duplicate_of_the_same_page_post():
    a = man(MAN_ACT, "a", "2026-11-06T22:03:42Z").records
    post = {"event_id": "nh-permittees:manchester:Item1", "source_record_id": "manchester:Item1",
            "reported_at": "2026-11-06T17:00:00-05:00", "raw": {"kind": "activation"}}
    far = {**post, "event_id": "nh-permittees:manchester:Item2", "source_record_id": "manchester:Item2",
           "reported_at": "2026-11-06T19:30:00-05:00"}
    assert manchester.link_page(a, [far, post]) == 1
    assert a[0]["duplicate_of"] == "nh-permittees:manchester:Item1" and "min apart" in a[0]["raw"]["_link_basis"]


# ---------------------------------------------------------------- CT DEEP press

def test_ct_press_release_sorting():
    m = lambda subj, body: mail_of(eml("DEEP <news@ct.gov>", "ct-deep-press@x", subj, body, auth=cf("ct.gov")), "ct-deep-press")
    assert ct_deep_press.parse(m("Deer Hunting Season Begins", "Hunters are reminded ..."), {}, {}).kind == "not_notice"
    r = ct_deep_press.parse(m("DEEP advises the public", "Avoid contact with the river after a sewage spill in Town."), {}, {})
    assert r.kind == "needs_rule" and not r.records


# ---------------------------------------------------------------- the portal link

def portal(eid, outfall, start, published, parent=None, status="ongoing"):
    return {"event_id": f"ma-massdep:{eid}", "source_record_id": eid, "npdes_permit": "MA0101630", "outfall_id": outfall,
            "started_at": start, "published_at": published, "parent_event_id": parent and f"ma-massdep:{parent}",
            "status": status}


def holyoke_chain():
    a = holyoke.parse(mail_of(eml("C <n@everbridge.net>", "holyoke@x", "CSO", HOLYOKE_ACTIVE, auth=cf("everbridge.net")),
                              "holyoke", "a1"), LISTS["holyoke"], {}).records
    c = holyoke.parse(mail_of(eml("C <n@everbridge.net>", "holyoke@x", "CSO", HOLYOKE_CEASED, auth=cf("everbridge.net")),
                              "holyoke", "c1", "2026-01-11T03:50:00Z"), LISTS["holyoke"], {}).records
    recs = a + c
    O.link_chains(recs)
    return recs


def test_notice_chain_is_one_event_with_the_portals_shown_record():
    recs = holyoke_chain()
    p = [portal("p1", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00"),
         portal("p2", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-13T09:00:00-05:00", parent="p1", status="ended"),
         portal("p3", "HOL018", "2026-01-10T18:55:00-05:00", "2026-01-12T09:00:00-05:00")]
    assert O.link_portal(recs, p, "MA0101630") == 2
    assert {r["duplicate_of"] for r in recs} == {"ma-massdep:p2"}     # the portal's newest word, not the replaced one
    assert "5 min apart" in recs[0]["raw"]["_link_basis"]


def test_no_link_beyond_three_hours_or_to_another_permit():
    recs = holyoke_chain()
    p = [portal("p1", "HOL021", "2026-01-10T23:00:00-05:00", "2026-01-12T09:00:00-05:00"),
         {**portal("p4", "HOL021", "2026-01-10T18:55:00-05:00", "2026-01-12T09:00:00-05:00"), "npdes_permit": "MA0101613"}]
    assert O.link_portal(recs, p, "MA0101630") == 0 and not any(r["duplicate_of"] for r in recs)


# ---------------------------------------------------------------- quiet lists

NOW = datetime(2026, 11, 17, 4, 0, tzinfo=UTC)


def test_quiet_when_the_portal_shows_notices_the_list_never_sent():
    p = [{**portal("p1", "SPR010", "2026-11-06T11:10:00-05:00", "2026-11-06T13:23:00-05:00"), "npdes_permit": "MA0101613"}]
    q = O.quiet_check(LISTS["springfield"], [], {"ma-massdep": p}, NOW)
    assert q and q["missed"] == 1 and "since the sign-up" in q["reason"]
    heard = [{"result": "notice", "trust": "operator", "received_at": "2026-11-06T16:20:00Z"}]
    assert O.quiet_check(LISTS["springfield"], heard, {"ma-massdep": p}, NOW) is None
    forged = [{"result": "unverified", "trust": None, "received_at": "2026-11-06T16:20:00Z"},
              {"result": "fetch_failed", "received_at": "2026-11-06T16:21:00Z"}]
    assert O.quiet_check(LISTS["springfield"], forged, {"ma-massdep": p}, NOW)    # nothing proven came from the list


def test_not_quiet_for_a_notice_before_the_sign_up_or_too_fresh():
    p = [{**portal("p1", "HOL018", "2026-11-12T23:50:00-05:00", "2026-11-13T14:24:00-05:00")},
         {**portal("p2", "HOL018", "2026-11-17T01:30:00Z", "2026-11-17T02:00:00Z")}]
    assert O.quiet_check(LISTS["holyoke"], [], {"ma-massdep": p}, NOW) is None


def test_quiet_after_max_days_for_a_regular_list():
    spec = LISTS["ct-deep-press"]
    assert O.quiet_check(spec, [{"result": "not_notice", "trust": "operator", "received_at": "2026-11-16T21:47:23Z"}],
                         {}, NOW) is None
    q = O.quiet_check(spec, [{"result": "not_notice", "trust": "operator", "received_at": "2026-11-01T21:47:23Z"}], {}, NOW)
    assert q and "15 days" in q["reason"]


# ---------------------------------------------------------------- the whole run

class FakeTransport:
    def __init__(self, rows, raws, fail_rows=False):
        self._rows, self.raws, self.fail_rows, self.reads = rows, raws, fail_rows, 0

    def rows(self):
        if self.fail_rows:
            raise RuntimeError("D1 inbound index answered HTTP 403 (10000: Authentication error)")
        return self._rows

    def raw(self, key):
        self.reads += 1
        return self.raws[key]


def run_feed(tr, lists, state, events_dir, now):
    """The split feed in one call: the read (mailfeed/read.py) writes its state at `state` and the lists' inbox files
    beside it, then the link (ingest/operator_mail.py) reads those files and writes events_dir. The read's exit code."""
    files = Path(state).parent / "inbox-files"
    rc = R.run(tr, lists, Path(state), files, now=now)

    def reader(key):
        p = files / Path(key).name
        return (json.loads(p.read_text()), None) if p.is_file() else (None, "absent")
    O.run(lists, Path(events_dir), now=now, reader=reader)
    return rc


def world(tmp_path):
    rows, raws = [], {}

    def add(mid, list_id, raw, received):
        rows.append({"id": mid, "received_at": received, "list_id": list_id, "raw_key": f"email/{mid}.eml", "size": len(raw)})
        raws[f"email/{mid}.eml"] = raw
    add("h1", "holyoke", eml("City of Holyoke <cso@holyoke.org>", "holyoke@x", "CSO Notification", HOLYOKE_ACTIVE,
                             auth=cf("holyoke.org")), "2026-11-17T02:00:00Z")
    add("h2", "holyoke", eml("Fake <noreply@everbridge.net>", "holyoke@x", "CSO Notification", HOLYOKE_ACTIVE,
                             auth="mx.cloudflare.net; dkim=none; dmarc=fail header.from=everbridge.net"), "2026-11-17T02:01:00Z")
    add("h3", "holyoke", eml("City of Holyoke <cso@holyoke.org>", "holyoke@x", "CSO Notification",
                             "Dear Health Official: a table we do not read", auth=cf("holyoke.org")), "2026-11-17T02:02:00Z")
    add("u1", "usgs-waterdata", eml("USGS <news@usgs.gov>", "usgs-waterdata@x", "Bulletin", "News.", auth=cf("usgs.gov")),
        "2026-11-17T02:03:00Z")
    add("x1", "stranger", eml("Someone <someone@example.com>", "stranger@x", "Hello", "Hi.", auth=cf("example.com")),
        "2026-11-17T02:04:00Z")
    add("o1", "ct-deep", eml("Owner <owner@example.com>", "ct-deep@x", "Letter", "A letter.", auth=cf("example.com")),
        "2026-11-17T02:05:00Z")
    return rows, raws


def test_run_writes_one_file_per_list_and_an_index_without_personal_data(tmp_path):
    rows, raws = world(tmp_path)
    tr = FakeTransport(rows, raws)
    lists = {k: v for k, v in LISTS.items() if k in ("holyoke", "usgs-waterdata", "ct-deep")}
    assert run_feed(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW) == 0
    ev = json.loads((tmp_path / "events/ma-holyoke-everbridge.json").read_text())
    assert ev["ok"] is True and ev["count"] == 1 and ev["records"][0]["event_id"] == "ma-holyoke-everbridge:h1:1"
    assert ev["meta"]["results"] == {"failed": 1, "notice": 1, "unverified": 1}
    assert {f["inbound_id"] for f in ev["meta"]["failures"]} == {"h2", "h3"}       # kept and counted, never dropped
    idx = json.loads((tmp_path / "idx.json").read_text())
    assert idx["messages"]["x1"]["result"] == "unknown_list" and idx["messages"]["o1"]["result"] == "correspondence"
    assert idx["messages"]["u1"]["result"] == "not_notice"
    s = (tmp_path / "idx.json").read_text() + json.dumps(ev)
    assert not re.search(r"[\w.+-]+@(?!dirtywaterwatch\.org)[\w-]+\.[\w.]+", s)  # no address but our own
    assert "CSO Notification" not in (tmp_path / "idx.json").read_text()           # no subjects kept
    # a second run reads nothing again; a parser change re-reads its list's messages only
    n = tr.reads
    run_feed(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    assert tr.reads == n
    holyoke.VERSION += 1
    try:
        run_feed(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
        assert tr.reads == n + 3
    finally:
        holyoke.VERSION -= 1


def test_an_unreadable_index_keeps_the_previous_records(tmp_path):
    rows, raws = world(tmp_path)
    lists = {"holyoke": LISTS["holyoke"]}
    run_feed(FakeTransport(rows, raws), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    run_feed(FakeTransport(rows, raws, fail_rows=True), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    ev = json.loads((tmp_path / "events/ma-holyoke-everbridge.json").read_text())
    assert ev["ok"] is False and ev["count"] == 1 and "could not be read" in ev["error"] and "403" in ev["error"]


def test_no_credentials_is_a_recorded_failure(tmp_path):
    assert run_feed(None, {"holyoke": LISTS["holyoke"]}, tmp_path / "idx.json", tmp_path / "events", now=NOW) == 1
    ev = json.loads((tmp_path / "events/ma-holyoke-everbridge.json").read_text())
    assert ev["ok"] is False and "credentials" in ev["error"]


def test_a_fetch_failure_is_tried_again(tmp_path):
    rows, raws = world(tmp_path)
    lists = {"holyoke": LISTS["holyoke"]}
    broken = dict(raws)
    del broken["email/h1.eml"]
    tr = FakeTransport(rows, broken)
    run_feed(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    idx = json.loads((tmp_path / "idx.json").read_text())
    assert idx["messages"]["h1"]["result"] == "fetch_failed"
    run_feed(FakeTransport(rows, raws), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    assert json.loads((tmp_path / "idx.json").read_text())["messages"]["h1"]["result"] == "fetch_failed"   # waits an hour
    run_feed(FakeTransport(rows, raws), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW + timedelta(hours=2))
    assert json.loads((tmp_path / "idx.json").read_text())["messages"]["h1"]["result"] == "notice"


def test_portal_link_and_quiet_flag_in_the_written_file(tmp_path):
    rows, raws = world(tmp_path)
    ev_dir = tmp_path / "events"
    ev_dir.mkdir()
    (ev_dir / "ma-massdep.json").write_text(json.dumps({"records": [
        portal("p1", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00")]}))
    run_feed(FakeTransport(rows, raws), {"holyoke": LISTS["holyoke"]}, tmp_path / "idx.json", ev_dir, now=NOW)
    ev = json.loads((ev_dir / "ma-holyoke-everbridge.json").read_text())
    assert ev["records"][0]["duplicate_of"] == "ma-massdep:p1" and ev["meta"]["linked_to_portal"] == 1
    assert ev["meta"]["quiet"] is None


# ---------------------------------------------------------------- status and export

def test_status_carries_the_notices_facts_to_the_record_it_repeats():
    from build import status as S
    keep = {"event_id": "ma-massdep:p1", "raw": {}}
    dup = {"event_id": "ma-holyoke-everbridge:h1:1", "source_id": "ma-holyoke-everbridge", "published_at": "2026-01-11T00:05:00Z",
           "started_at": "2026-01-10T23:55:00Z", "ended_at": None, "status": "ongoing", "volume_gal": 225192,
           "volume_text": "225,192", "estimate_flag": "estimated", "advice_text": "Avoid contact ...",
           "advice_window_hours": 48, "raw": {"_channel": "email", "volume_method": "The estimated volume is ..."}}
    other = {"event_id": "echo:1", "raw": {}, "volume_gal": 5}
    out = S.linked_notices([keep, dup, other], {dup["event_id"]: keep["event_id"], "echo:1": keep["event_id"]})
    assert list(out) == ["ma-massdep:p1"] and len(out["ma-massdep:p1"]) == 1
    n = out["ma-massdep:p1"][0]
    assert (n["volume_gal"], n["estimate_flag"], n["source_id"]) == (225192, "estimated", "ma-holyoke-everbridge")
    assert n["volume_method"].startswith("The estimated volume")


def test_a_quiet_list_is_a_stale_reason():
    from build import status as S
    f = {"ok": True, "last_ok_at": "2026-11-17T03:55:00Z", "fetched_at": "2026-11-17T03:55:00Z",
         "meta": {"quiet": {"reason": "no message from this list since the sign-up"}}}
    h = S.source_health("ma-swsc-cso-email", f, {"cadence": "per event"}, NOW)
    assert h["stale"] and "list quiet: no message from this list since the sign-up" in h["stale_reason"]
    f["meta"]["quiet"] = None
    assert not S.source_health("ma-swsc-cso-email", f, {"cadence": "per event"}, NOW)["stale"]


def test_the_lists_file_is_consistent():
    from common import SOURCES_DIR
    lists = O.load_lists()
    for lid, spec in lists.items():
        assert spec.get("kind") in ("notices", "context", "correspondence", "pending", "copy"), lid
        if spec["kind"] == "copy":
            assert spec.get("copy_of") and "parser" not in spec and "source_id" not in spec, lid
            for sid in spec["copy_of"]:
                assert (SOURCES_DIR / f"{sid}.yaml").exists(), sid
        if spec["kind"] == "notices":
            assert spec.get("parser") in PARSERS, lid
            assert (SOURCES_DIR / f"{spec['source_id']}.yaml").exists(), spec["source_id"]
            assert spec.get("senders") and spec.get("since") and "dkim" not in spec, lid
            assert not set(spec["senders"]) & set((spec.get("platform") or {}).get("domains") or []), lid
            assert spec.get("address", "").startswith(f"{lid}@dirtywaterwatch.org"), lid


# ---------------------------------------------------------------- Somerville

SOM = ("CSO Activation Notifications\nCombined Sewer Overflow (CSO) Event on July 22, 2026 at 4:25 p.m.  at SOM-001A on "
       "the Alewife Brook\nPublic Health Warning: Public health officials recommend avoiding contact with water bodies "
       "during rainstorms and for 48 hours afterwards, as there may be increased health risks.\nQuestions: 617-555-0199")


def test_somerville_event_sentence():
    from ingest.mail import somerville
    spec = {"source_id": "ma-somerville-cso-email", "operator": "ma-somerville", "npdes_permit": "MA0101982",
            "outfall_prefix": "SOM", "town": "SOMERVILLE"}
    raw = eml("City of Somerville <notify@somervillema.gov>", "somerville@x", "CSO Activation", SOM, auth=cf("somervillema.gov"))
    res = somerville.parse(mail_of(raw, "somerville", "v1", "2026-07-22T20:40:00Z"), spec, {})
    assert res.kind == "notice", res.note
    r = res.records[0]
    assert (r["outfall_id"], r["waterbody_text"], r["started_at"]) == ("SOM001A", "Alewife Brook", "2026-07-22T20:25:00Z")
    assert r["status"] == "unknown" and r["ended_at"] is None and r["advice_window_hours"] is None
    assert "48 hours afterwards" in r["advice_text"] and "617-555" not in json.dumps(r)
    two = somerville.parse(mail_of(eml("C <n@somervillema.gov>", "somerville@x", "CSO", SOM + "\n" + SOM,
                                       auth=cf("somervillema.gov")), "somerville"), spec, {})
    assert two.kind == "failed" and "several" in two.note
    other = somerville.parse(mail_of(eml("C <n@somervillema.gov>", "somerville@x", "News", "Street sweeping.",
                                         auth=cf("somervillema.gov")), "somerville"), spec, {})
    assert other.kind == "failed"


# ---------------------------------------------------------------- the review's findings (Astra 2026-11-17), one test each

def test_p1_1_a_shared_platform_proves_less_than_the_operators_own_domain():
    ev_ = lambda frm, body=HOLYOKE_ACTIVE, auth=None: mail_of(eml(frm, "holyoke@x", "CSO", body, auth=auth), "holyoke")
    assert verified(ev_("C <cso@holyoke.org>", auth=cf("holyoke.org")), LISTS["holyoke"])[0] == "operator"
    assert verified(ev_("C <noreply@everbridge.net>", auth=cf("everbridge.net")), LISTS["holyoke"])[0] == "platform"
    no_mark = HOLYOKE_ACTIVE.replace("453003085611624", "000000000000000")      # another Everbridge customer
    t, why = verified(ev_("C <noreply@everbridge.net>", no_mark, cf("everbridge.net")), LISTS["holyoke"])
    assert t is None and "mark" in why
    sp = lambda frm, auth: mail_of(eml(frm, "springfield@x", "CSO", SPRINGFIELD, auth=auth), "springfield")
    cc = "mx.cloudflare.net; dkim=pass header.d=ccsend.com header.s=1000; dmarc=none header.from=waterandsewer.org"
    assert verified(sp("SWSC <alerts@waterandsewer.org>", cc), LISTS["springfield"])[0] == "platform"
    other = "mx.cloudflare.net; dkim=pass header.d=ccsend.com header.s=1000; dmarc=pass header.from=ccsend.com"
    assert verified(sp("Any customer <news@ccsend.com>", other), LISTS["springfield"])[0] is None


def test_p1_1_a_platform_only_notice_never_stands_alone(tmp_path):
    raw = eml("City of Holyoke <noreply@everbridge.net>", "holyoke@x", "CSO Notification", HOLYOKE_ACTIVE,
              auth=cf("everbridge.net"))
    rows = [{"id": "e1", "received_at": "2026-11-17T02:00:00Z", "list_id": "holyoke", "raw_key": "k1", "size": 1}]
    ev_dir = tmp_path / "events"
    run_feed(FakeTransport(rows, {"k1": raw}), {"holyoke": LISTS["holyoke"]}, tmp_path / "i.json", ev_dir, now=NOW)
    ev = json.loads((ev_dir / "ma-holyoke-everbridge.json").read_text())
    assert ev["count"] == 0 and ev["meta"]["held_platform_only"] == 1 and ev["meta"]["results"] == {"notice": 1}
    (ev_dir / "ma-massdep.json").write_text(json.dumps({"records": [
        portal("p1", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00")]}))
    run_feed(FakeTransport(rows, {"k1": raw}), {"holyoke": LISTS["holyoke"]}, tmp_path / "i.json", ev_dir, now=NOW)
    ev = json.loads((ev_dir / "ma-holyoke-everbridge.json").read_text())
    assert ev["count"] == 1 and ev["records"][0]["duplicate_of"] == "ma-massdep:p1"   # it adds to the portal's record


def test_p1_2_failure_notes_never_quote_the_message():
    body = HOLYOKE_ACTIVE.replace("This Discharge is Active CSO at this time.",
                                  "This Discharge is Call Jane Doe at jane@example.org at this time.")
    res = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "holyoke@x", "CSO", body, auth=cf("holyoke.org")), "holyoke"),
                        LISTS["holyoke"], {})
    assert res.kind == "failed" and "@" not in res.note and "Jane" not in res.note

    class Boom:
        VERSION = 1

        @staticmethod
        def parse(mail, spec, ctx):
            raise ValueError("Call Jane Doe at jane@example.org")
    PARSERS["boom"] = Boom
    try:
        row = {"id": "b1", "received_at": "2026-11-17T02:00:00Z", "list_id": "holyoke"}
        e = R.read_message(eml("C <cso@holyoke.org>", "holyoke@x", "CSO", "x", auth=cf("holyoke.org")), row,
                           {**LISTS["holyoke"], "parser": "boom"}, {})
    finally:
        del PARSERS["boom"]
    assert e["result"] == "failed" and e["note"] == "parser error (ValueError)"


def test_p1_3_an_empty_label_never_takes_the_next_line():
    body = HOLYOKE_ACTIVE.replace("Estimated Volume (gallons): 225,192",
                                  "Estimated Volume (gallons):\nCall 413-555-0100 or desk@example.org")
    body = body.replace("Affected Water Bodies: Connecticut River", "Affected Water Bodies: Jane Doe 413-555-0100")
    r = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "holyoke@x", "CSO", body, auth=cf("holyoke.org")), "holyoke"),
                      LISTS["holyoke"], {}).records[0]
    assert r["volume_text"] is None and r["volume_gal"] is None and r["waterbody_text"] is None
    assert r["raw"]["_fields_set_aside"] == ["water"]           # the empty volume line took nothing, so nothing set aside
    s_ = json.dumps(r)
    assert "555-0100" not in s_ and "example.org" not in s_ and "Jane" not in s_
    sp_body = SPRINGFIELD.replace("Receiving Water: Connecticut River", "Receiving Water:\nJane Doe, Field Supervisor")
    r2 = springfield.parse(mail_of(eml("S <a@waterandsewer.org>", "springfield@x", "CSO", sp_body,
                                       auth=cf("waterandsewer.org")), "springfield"), LISTS["springfield"], {}).records[0]
    assert r2["waterbody_text"] is None and "Jane" not in json.dumps(r2)


def test_p1_4_the_local_reader_never_writes_the_message_to_a_file(monkeypatch):
    calls = []

    class P:
        returncode, stdout = 0, b"raw bytes"
    monkeypatch.setattr(R.subprocess, "run", lambda args, **kw: calls.append(args) or P())
    assert R.WranglerTransport().raw("email/x.eml") == b"raw bytes"
    assert "--pipe" in calls[0] and "--file" not in calls[0]


def test_p1_5_new_mail_is_read_before_retries_and_failures_back_off(tmp_path):
    rows = [{"id": f"old{i}", "received_at": f"2026-11-1{i}T00:00:00Z", "list_id": "holyoke", "raw_key": f"gone{i}",
             "size": 1} for i in range(3)]
    raw = eml("City of Holyoke <cso@holyoke.org>", "holyoke@x", "CSO", HOLYOKE_ACTIVE, auth=cf("holyoke.org"))
    idx = {"messages": {}}
    R.update_index(idx, rows, FakeTransport(rows, {}), {"holyoke": LISTS["holyoke"]}, {}, max_fetch=2, now=NOW)
    assert sorted(e["result"] for e in idx["messages"].values()) == ["fetch_failed", "fetch_failed", "pending"]
    rows2 = rows + [{"id": "new", "received_at": "2026-11-17T03:00:00Z", "list_id": "holyoke", "raw_key": "k", "size": 1}]
    tr = FakeTransport(rows2, {"k": raw})
    R.update_index(idx, rows2, tr, {"holyoke": LISTS["holyoke"]}, {}, max_fetch=2, now=NOW + timedelta(minutes=5))
    assert idx["messages"]["new"]["result"] == "notice"                    # read first
    assert tr.reads == 2                                                    # the pending one, not the waiting failures
    later = NOW + timedelta(hours=30)
    for _ in range(R.RETRY_MAX + 2):
        R.update_index(idx, rows2, FakeTransport(rows2, {"k": raw}), {"holyoke": LISTS["holyoke"]}, {}, max_fetch=10, now=later)
        later += timedelta(hours=25)
    assert all(idx["messages"][f"old{i}"]["tries"] == R.RETRY_MAX for i in range(3))   # then left, still counted


@pytest.mark.parametrize("status", ["Ongoing for over 8 hours", "Not ceased", "Not active", "Ceased or ongoing"])
def test_p1_6_springfield_status_words_must_be_explicit(status):
    body = SPRINGFIELD.replace("Status: Ongoing", f"Status: {status}")
    res = springfield.parse(mail_of(eml("S <a@waterandsewer.org>", "springfield@x", "CSO", body,
                                        auth=cf("waterandsewer.org")), "springfield"), LISTS["springfield"], {})
    assert res.kind == "failed" and "status" in res.note


def test_p1_6_springfield_conflicting_sentence_fails():
    body = SPRINGFIELD.replace("Aviso de aviso", "The discharge has ceased.\nAviso de aviso")
    res = springfield.parse(mail_of(eml("S <a@waterandsewer.org>", "springfield@x", "CSO", body,
                                        auth=cf("waterandsewer.org")), "springfield"), LISTS["springfield"], {})
    assert res.kind == "failed"


def test_p1_7_the_link_goes_to_the_portal_record_shown_even_when_it_has_no_start():
    recs = holyoke_chain()
    p = [portal("P", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00"),
         {**portal("C", "HOL021", None, "2026-01-13T09:00:00-05:00", parent="P", status="ended")}]
    assert O.link_portal(recs, p, "MA0101630") == 2
    assert {r["duplicate_of"] for r in recs} == {"ma-massdep:C"}


def test_p1_8_a_second_overflow_is_not_folded_into_the_first():
    a1 = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_ACTIVE.replace("18:55:00", "10:00:00"),
                                   auth=cf("holyoke.org")), "holyoke", "a1"), LISTS["holyoke"], {}).records
    c1 = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_CEASED.replace("22:40:00", "10:15:00"),
                                   auth=cf("holyoke.org")), "holyoke", "c1"), LISTS["holyoke"], {}).records
    a2 = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_ACTIVE.replace("18:55:00", "12:00:00"),
                                   auth=cf("holyoke.org")), "holyoke", "a2"), LISTS["holyoke"], {}).records
    recs = a1 + c1 + a2
    O.link_chains(recs)
    O.link_portal(recs, [portal("p1", "HOL021", "2026-01-10T10:00:00-05:00", "2026-01-12T09:00:00-05:00")], "MA0101630")
    assert a1[0]["duplicate_of"] == c1[0]["duplicate_of"] == "ma-massdep:p1" and a2[0]["duplicate_of"] is None


def test_p1_9_a_ceased_notice_sent_twice_joins_its_chain():
    recs = holyoke_chain()
    again = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_CEASED, auth=cf("holyoke.org")),
                                  "holyoke", "c2", "2026-01-11T04:30:00Z"), LISTS["holyoke"], {}).records
    recs += again
    O.link_chains(recs)
    assert again[0]["parent_event_id"] == recs[1]["event_id"] and again[0]["started_at"] == recs[0]["started_at"]
    O.link_portal(recs, [portal("p1", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00")], "MA0101630")
    assert all(r["duplicate_of"] == "ma-massdep:p1" for r in recs)


def test_p1_9_updates_keep_a_long_overflow_open():
    a = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_ACTIVE, auth=cf("holyoke.org")),
                              "holyoke", "a"), LISTS["holyoke"], {}).records
    upd = HOLYOKE_ACTIVE.replace("This Discharge is Active CSO at this time.", "This Discharge is Active for 8 hours at this time.")
    u = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", upd, auth=cf("holyoke.org")),
                              "holyoke", "u", "2026-01-13T20:00:00Z"), LISTS["holyoke"], {}).records
    c = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_CEASED.replace("01/10/26 22:40:00", "01/15/26 08:00:00"),
                                  auth=cf("holyoke.org")), "holyoke", "c", "2026-01-15T13:10:00Z"), LISTS["holyoke"], {}).records
    recs = a + u + c
    O.link_chains(recs)
    assert c[0]["parent_event_id"] == u[0]["event_id"] and c[0]["started_at"] == a[0]["started_at"]


def test_p1_10_a_manchester_email_sent_twice_shares_the_post():
    a = man(MAN_ACT, "a", "2026-11-06T22:03:42Z").records
    b = man(MAN_ACT, "b", "2026-11-06T22:04:10Z", date="Fri, 06 Nov 2026 17:04:05 -0500").records
    post = {"event_id": "nh-permittees:manchester:Item1", "source_record_id": "manchester:Item1",
            "reported_at": "2026-11-06T17:03:00-05:00", "raw": {"kind": "activation"}}
    assert manchester.link_page(a + b, [post]) == 2
    assert a[0]["duplicate_of"] == b[0]["duplicate_of"] == post["event_id"]


def test_p1_11_manchester_orders_and_bounds_by_the_citys_time():
    late_clear = man(MAN_CLEAR, "c", "2026-11-10T22:00:00Z", "CSO Notification - No Activations for 12 Hours",
                     date="Sun, 08 Nov 2026 17:00:00 -0500").records
    act = man(MAN_ACT, "a", "2026-11-09T12:00:00Z", date="Mon, 09 Nov 2026 07:00:00 -0500").records
    assert late_clear[0]["reported_at"] == "2026-11-08T22:00:00Z" and "Date header" in late_clear[0]["raw"]["_time_basis"]
    manchester.pair(late_clear + act)
    assert act[0]["status"] == "ongoing"                         # the earlier all-clear never closes a later activation
    assert late_clear[0]["raw"]["_ended_before"].startswith("2026-11-08T10:00:00")
    odd = man(MAN_ACT, "o", "2026-11-09T12:00:00Z", date="Mon, 09 Nov 2026 09:00:00 -0500").records   # after the receipt
    assert odd[0]["reported_at"] == "2026-11-09T12:00:00Z" and "reached the project" in odd[0]["raw"]["_time_basis"]


def test_p1_12_a_ceased_only_notice_never_makes_a_reversed_window():
    from build import status as S
    c = holyoke.parse(mail_of(eml("C <cso@holyoke.org>", "h@x", "CSO", HOLYOKE_CEASED, auth=cf("holyoke.org")),
                              "holyoke", "c1", "2026-01-11T03:50:00Z"), LISTS["holyoke"], {}).records[0]
    assert c["started_at"] is None and c["ended_at"] == "2026-01-11T03:40:00Z"
    ivs = S.event_intervals(c, "MA", datetime(2026, 1, 11, 6, 0, tzinfo=UTC), None)
    assert ivs and all(iv["start"] <= (iv["end"] or iv["start"]) for iv in ivs)
    assert min(iv["start"] for iv in ivs) == datetime(2026, 1, 11, 3, 40, tzinfo=UTC)


def test_a_pending_list_keeps_its_messages_and_makes_no_record():
    spec = {"kind": "pending", "address": "revere@dirtywaterwatch.org"}
    row = {"id": "r1", "received_at": "2026-11-17T06:00:00Z", "list_id": "revere"}
    e = R.read_message(eml("Revere <alerts@publicinput.com>", "revere@x", "Please confirm your subscription", "Click.",
                           auth=cf("publicinput.com")), row, spec, {})
    assert e["result"] == "account" and e["records"] == []
    e = R.read_message(eml("Revere <alerts@publicinput.com>", "revere@x", "SSO Notice", "An overflow at ...",
                           auth=cf("publicinput.com")), row, spec, {})
    assert e["result"] == "needs_rule" and e["records"] == []


def test_a_copy_list_counts_its_notices_as_copies_and_makes_no_record():
    spec = {"kind": "copy", "copy_of": ["al-adem-sso-map-live", "al-adem-sso-history"],
            "address": "al-adem-sso@dirtywaterwatch.org"}
    row = {"id": "a1", "received_at": "2026-11-18T13:38:57Z", "list_id": "al-adem-sso"}
    e = R.read_message(eml("ADEM <noreply@adem.example.gov>", "al-adem-sso@x", "ADEM Email Notification Confirmation",
                           "Confirm.", auth=cf("adem.example.gov")), row, spec, None)
    assert e["result"] == "account" and e["records"] == []
    e = R.read_message(eml("ADEM <noreply@adem.example.gov>", "al-adem-sso@x", "SSO Notification",
                           "An initial SSO report has been submitted to ADEM ...\nNPDES Permit No. AL0000001",
                           auth=cf("adem.example.gov")), row, spec, None)
    assert e["result"] == "copy" and e["records"] == []
    assert "al-adem-sso-map-live" in e["note"] and "AL0000001" not in e["note"]
    # the kind is part of the rule, so a list moved from pending to copy has its stored messages read again
    assert R.rule_of(spec) != R.rule_of({**spec, "kind": "pending"})
    assert O.load_lists()["al-adem-sso"]["kind"] == "copy"


def test_a_platform_list_marked_stands_alone_publishes_on_its_own(tmp_path):
    """Owner, 2026-11-27: Holyoke's Everbridge notices (both of Holyoke's marks present) stand alone while the portal
    lags; another Everbridge customer's mail still fails the marks, and a list without the flag still holds."""
    spec = {**LISTS["holyoke"], "platform": {**LISTS["holyoke"]["platform"], "stands_alone": True}}
    raw = eml("City of Holyoke <noreply@everbridge.net>", "holyoke@x", "CSO Notification", HOLYOKE_ACTIVE,
              auth=cf("everbridge.net"))
    forged = eml("Someone <noreply@everbridge.net>", "holyoke@x", "CSO Notification",
                 HOLYOKE_ACTIVE.replace("453003085611624", "000000000000000"), auth=cf("everbridge.net"))
    rows = [{"id": "e1", "received_at": "2026-11-17T02:00:00Z", "list_id": "holyoke", "raw_key": "k1", "size": 1},
            {"id": "e2", "received_at": "2026-11-17T02:05:00Z", "list_id": "holyoke", "raw_key": "k2", "size": 1}]
    ev_dir = tmp_path / "events"
    run_feed(FakeTransport(rows, {"k1": raw, "k2": forged}), {"holyoke": spec}, tmp_path / "i.json", ev_dir, now=NOW)
    ev = json.loads((ev_dir / "ma-holyoke-everbridge.json").read_text())
    assert ev["count"] == 1 and ev["meta"]["held_platform_only"] == 0
    rec = ev["records"][0]
    assert rec["raw"]["_trust"] == "platform" and rec["status"] == "ongoing" and not rec.get("duplicate_of")
    assert ev["meta"]["results"] == {"notice": 1, "unverified": 1}
    # a portal record of the same overflow later still takes the e-mail as its duplicate
    (ev_dir / "ma-massdep.json").write_text(json.dumps({"records": [
        portal("p1", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00")]}))
    run_feed(FakeTransport(rows, {"k1": raw, "k2": forged}), {"holyoke": spec}, tmp_path / "i2.json", ev_dir, now=NOW)
    ev = json.loads((ev_dir / "ma-holyoke-everbridge.json").read_text())
    assert ev["count"] == 1 and ev["records"][0]["duplicate_of"] == "ma-massdep:p1"


def test_the_shipped_lists_let_only_holyoke_stand_alone():
    lists = json.loads((Path(__file__).resolve().parents[2] / "data/mail-lists.json").read_text())["lists"]
    alone = [lid for lid, s in lists.items() if (s.get("platform") or {}).get("stands_alone")]
    assert alone == ["holyoke"]
    assert set(lists["holyoke"]["platform"]["body_marks"]) == {"MA0101630", "453003085611624"}
