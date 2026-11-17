"""Operators' e-mail notices (ingest/operator_mail.py, ingest/mail/): invented messages in the real shapes.

Nothing here is a real message: the operators' layouts are copied, the names, numbers and contacts are made up."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from ingest import operator_mail as O
from ingest.mail import PARSERS, ct_deep_press, holyoke, manchester, springfield
from ingest.mail.message import Mail, parse_mail, read_auth, verified

LISTS = {
    "holyoke": {"kind": "notices", "parser": "holyoke", "source_id": "ma-holyoke-everbridge",
                "address": "holyoke@dirtywaterwatch.org", "operator": "ma-holyoke", "npdes_permit": "MA0101630",
                "outfall_prefix": "HOL", "town": "HOLYOKE", "senders": ["everbridge.net"], "dkim": ["everbridge.net"],
                "since": "2026-11-17T01:00:00Z",
                "quiet": {"cross_check": {"source_id": "ma-massdep", "npdes_permit": "MA0101630"}},
                "source_url": "https://www.holyoke.org/emergency-notification-system/"},
    "springfield": {"kind": "notices", "parser": "springfield", "source_id": "ma-swsc-cso-email",
                    "address": "springfield@dirtywaterwatch.org", "operator": "ma-springfield-wsc",
                    "npdes_permit": "MA0101613", "outfall_prefix": "SPR", "town": "SPRINGFIELD",
                    "senders": ["waterandsewer.org", "ccsend.com"], "dkim": ["ccsend.com", "waterandsewer.org"],
                    "since": "2026-11-02T21:00:00Z",
                    "quiet": {"cross_check": {"source_id": "ma-massdep", "npdes_permit": "MA0101613"}},
                    "source_url": "https://springfieldalerts.com/Suez/"},
    "manchester": {"kind": "notices", "parser": "manchester", "source_id": "nh-manchester-cso-email",
                   "address": "manchester@dirtywaterwatch.org", "operator": "nh-manchester-epd",
                   "npdes_permit": "NH0100447", "senders": ["manchesternh.gov"], "dkim": ["manchesternh.gov"],
                   "since": "2026-11-02T21:30:00Z",
                   "quiet": {"cross_check": {"source_id": "nh-permittees", "record_prefix": "manchester:",
                                             "raw_kind": "activation"}}},
    "ct-deep-press": {"kind": "notices", "parser": "ct_deep_press", "source_id": "ct-deep-press-email",
                      "senders": ["ct.gov"], "dkim": ["ct.gov"], "since": "2026-11-02T21:00:00Z",
                      "quiet": {"max_quiet_days": 10}},
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
Unsubscribe: if you no longer wish to receive these emails, please go to https://member.everbridge.net/0000/login
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
    c = man(MAN_CLEAR, "c", "2026-11-08T21:57:29Z", "City Of Manchester CSO Notification - No Activations for 12 Hours").records
    assert a[0]["status"] == "ongoing" and a[0]["started_at"] is None and a[0]["reported_at"] == "2026-11-06T22:03:42Z"
    manchester.pair(a + c)
    assert a[0]["status"] == "ended" and a[0]["time_precision"] == "bound"
    assert a[0]["raw"]["_ended_before"].startswith("2026-11-08T09:57:29")
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
    heard = [{"result": "notice", "received_at": "2026-11-06T16:20:00Z"}]
    assert O.quiet_check(LISTS["springfield"], heard, {"ma-massdep": p}, NOW) is None
    forged = [{"result": "unverified", "received_at": "2026-11-06T16:20:00Z"}]
    assert O.quiet_check(LISTS["springfield"], forged, {"ma-massdep": p}, NOW)    # a forged message proves nothing


def test_not_quiet_for_a_notice_before_the_sign_up_or_too_fresh():
    p = [{**portal("p1", "HOL018", "2026-11-12T23:50:00-05:00", "2026-11-13T14:24:00-05:00")},
         {**portal("p2", "HOL018", "2026-11-17T01:30:00Z", "2026-11-17T02:00:00Z")}]
    assert O.quiet_check(LISTS["holyoke"], [], {"ma-massdep": p}, NOW) is None


def test_quiet_after_max_days_for_a_regular_list():
    spec = LISTS["ct-deep-press"]
    assert O.quiet_check(spec, [{"result": "not_notice", "received_at": "2026-11-16T21:47:23Z"}], {}, NOW) is None
    q = O.quiet_check(spec, [{"result": "not_notice", "received_at": "2026-11-01T21:47:23Z"}], {}, NOW)
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


def world(tmp_path):
    rows, raws = [], {}

    def add(mid, list_id, raw, received):
        rows.append({"id": mid, "received_at": received, "list_id": list_id, "raw_key": f"email/{mid}.eml", "size": len(raw)})
        raws[f"email/{mid}.eml"] = raw
    add("h1", "holyoke", eml("City of Holyoke <noreply@everbridge.net>", "holyoke@x", "CSO Notification", HOLYOKE_ACTIVE,
                             auth=cf("everbridge.net")), "2026-11-17T02:00:00Z")
    add("h2", "holyoke", eml("Fake <noreply@everbridge.net>", "holyoke@x", "CSO Notification", HOLYOKE_ACTIVE,
                             auth="mx.cloudflare.net; dkim=none; dmarc=fail header.from=everbridge.net"), "2026-11-17T02:01:00Z")
    add("h3", "holyoke", eml("City of Holyoke <noreply@everbridge.net>", "holyoke@x", "CSO Notification",
                             "Dear Health Official: a table we do not read", auth=cf("everbridge.net")), "2026-11-17T02:02:00Z")
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
    assert O.run(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW) == 0
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
    O.run(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    assert tr.reads == n
    holyoke.VERSION += 1
    try:
        O.run(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
        assert tr.reads == n + 3
    finally:
        holyoke.VERSION -= 1


def test_an_unreadable_index_keeps_the_previous_records(tmp_path):
    rows, raws = world(tmp_path)
    lists = {"holyoke": LISTS["holyoke"]}
    O.run(FakeTransport(rows, raws), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    O.run(FakeTransport(rows, raws, fail_rows=True), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    ev = json.loads((tmp_path / "events/ma-holyoke-everbridge.json").read_text())
    assert ev["ok"] is False and ev["count"] == 1 and "could not be read" in ev["error"] and "403" in ev["error"]


def test_no_credentials_is_a_recorded_failure(tmp_path):
    assert O.run(None, {"holyoke": LISTS["holyoke"]}, tmp_path / "idx.json", tmp_path / "events", now=NOW) == 1
    ev = json.loads((tmp_path / "events/ma-holyoke-everbridge.json").read_text())
    assert ev["ok"] is False and "credentials" in ev["error"]


def test_a_fetch_failure_is_tried_again(tmp_path):
    rows, raws = world(tmp_path)
    lists = {"holyoke": LISTS["holyoke"]}
    broken = dict(raws)
    del broken["email/h1.eml"]
    tr = FakeTransport(rows, broken)
    O.run(tr, lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    idx = json.loads((tmp_path / "idx.json").read_text())
    assert idx["messages"]["h1"]["result"] == "fetch_failed"
    O.run(FakeTransport(rows, raws), lists, tmp_path / "idx.json", tmp_path / "events", now=NOW)
    assert json.loads((tmp_path / "idx.json").read_text())["messages"]["h1"]["result"] == "notice"


def test_portal_link_and_quiet_flag_in_the_written_file(tmp_path):
    rows, raws = world(tmp_path)
    ev_dir = tmp_path / "events"
    ev_dir.mkdir()
    (ev_dir / "ma-massdep.json").write_text(json.dumps({"records": [
        portal("p1", "HOL021", "2026-01-10T18:50:00-05:00", "2026-01-12T09:00:00-05:00")]}))
    O.run(FakeTransport(rows, raws), {"holyoke": LISTS["holyoke"]}, tmp_path / "idx.json", ev_dir, now=NOW)
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
        assert spec.get("kind") in ("notices", "context", "correspondence"), lid
        if spec["kind"] == "notices":
            assert spec.get("parser") in PARSERS, lid
            assert (SOURCES_DIR / f"{spec['source_id']}.yaml").exists(), spec["source_id"]
            assert spec.get("senders") and spec.get("dkim") and spec.get("since"), lid
            assert spec.get("address", "").startswith(f"{lid}@dirtywaterwatch.org"), lid
