"""City of Manchester's "CSO Discharge Notification" e-mail newsletter (not a feed).

Two notices, the same two the city posts on its CSO Discharge Notification page (ingest.nh_permittees, source
nh-permittees): "Please be advised that the City of Manchester has experienced CSO activations due to heavy rain ..."
(an activation somewhere in the system: no outfall, no time, no volume) and "... has experienced no CSO activations
during the past 12 hours" (the all-clear). Read the way the page's feed reads them: an activation is ongoing from the
time it was published; an all-clear closes the open activations with an upper bound (no activation in the 12 hours
before it), status ended, time_precision "bound". The e-mail gives no start: the notice's time is the time the e-mail
reached the project (published_at), and the Date header is kept as the city's sending time. The welcome message of the
newsletter and any other subject are not notices; a CSO subject with other wording is a failure.
"""
from __future__ import annotations

import re
from datetime import timedelta

from common import event

from .message import Mail, Result, parse_iso

NAME = "manchester"
VERSION = 1
WATERS = ["merrimack-river-nh", "piscataquog-river-nh"]
MATERIAL = "combined sewage and stormwater (CSO)"
ACTIVATION = re.compile(r"(?i)has experienced CSO activations\b")
RESEND_MINUTES = 10
ALL_CLEAR = re.compile(r"(?i)has experienced no CSO activations during the past (\d+) hours")


def parse(mail: Mail, spec: dict, ctx: dict) -> Result:
    text = mail.text
    clear = ALL_CLEAR.search(text)
    if clear:
        kind = "all_clear"
    elif ACTIVATION.search(text):
        kind = "activation"
    elif re.search(r"(?i)\bCSO\b", mail.subject):
        return Result("failed", note="a CSO subject without the activation or all-clear sentence")
    else:
        return Result("not_notice", note="not a CSO notice (newsletter or welcome message)")
    sentence = (clear or ACTIVATION.search(text)).group(0)
    hours = int(clear.group(1)) if clear else None
    # the city's own time for the notice: its Date header when that is no later than the receipt and at most 7 days
    # before it (the header is signed with the message; a delayed delivery keeps the city's time); otherwise the receipt, said so (Astra mail review
    # 2026-11-17 P1-11). It orders the notices and bounds an all-clear; it is never a start.
    sent, got = parse_iso(mail.sent_at), parse_iso(mail.received_at)
    if sent and got and timedelta(minutes=-5) <= got - sent <= timedelta(days=7):
        when, basis = mail.sent_at, "the city's sending time (the e-mail's Date header); the notice gives no start"
    else:
        when, basis = mail.received_at, "the time the e-mail reached the project (its Date header missing, after the receipt or over 7 days before it)"
    rec = event(
        source_id=spec["source_id"], source_record_id=mail.inbound_id,
        event_type="cso", status="ongoing" if kind == "activation" else "ended",
        discharger_id=spec.get("operator"), discharger_name="City of Manchester DPW Environmental Protection Division",
        npdes_permit=spec.get("npdes_permit"), waterbody_text=None, water_slugs=list(WATERS), water_match="inferred",
        started_at=None, ended_at=None, time_precision="minute",
        reported_at=when, published_at=mail.received_at, material=MATERIAL,
        authority="City of Manchester EPD (CSO Discharge Notification e-mail)",
        source_url=spec.get("source_url"),
        raw={"_channel": "email", "_list": mail.list_id, "_inbound_id": mail.inbound_id,
             "_received_at": mail.received_at, "_sent_at": mail.sent_at, "kind": kind,
             "_notice_sentence": f"the City of Manchester {sentence}", "_all_clear_hours": hours,
             "_time_basis": basis},
    )
    return Result("notice", records=[rec])


def pair(records: list[dict]) -> None:
    """An all-clear closes every earlier open activation of the list (ingest.nh_permittees.pair_manchester's rule):
    ended, bounded by the all-clear's time minus its hours."""
    rs = sorted((r for r in records if r.get("reported_at")), key=lambda r: (r["reported_at"], r["event_id"]))
    open_acts: list[dict] = []
    for r in rs:
        kind = r["raw"].get("kind")
        if kind == "activation":
            r.update(status="ongoing", time_precision="minute", parent_event_id=None)
            r["raw"].pop("_ended_before", None)
            r["raw"].pop("_ended_before_basis", None)
            open_acts.append(r)
        elif kind == "all_clear":
            hours = r["raw"].get("_all_clear_hours") or 12
            bound = (parse_iso(r["reported_at"]) - timedelta(hours=hours)).isoformat()
            basis = (f"'no CSO activations during the past {hours} hours' e-mail received {r['reported_at']}: no "
                     f"activation in the {hours} hours before it")
            r["parent_event_id"] = open_acts[-1]["event_id"] if open_acts else None
            r.update(status="ended", time_precision="bound")
            r["raw"]["_ended_before"], r["raw"]["_ended_before_basis"] = bound, basis
            for a in open_acts:
                a.update(status="ended", time_precision="bound")
                a["raw"]["_ended_before"], a["raw"]["_ended_before_basis"] = bound, basis
            open_acts = []


def link_page(records: list[dict], page_records: list[dict], minutes: int = 45) -> int:
    """Each e-mail notice that repeats a post on the city's page becomes that post's duplicate: one notice, two
    channels. Same kind, the post's time within `minutes` of the e-mail's (the city's time, reported_at); the closest
    pairs first, one post to one notice. An e-mail sent twice (same kind, RESEND_MINUTES apart) shares its twin's post
    (Astra mail review 2026-11-17 P1-10)."""
    posts = [p for p in page_records if str(p.get("source_record_id") or "").startswith("manchester:")
             and p.get("reported_at") and (p.get("raw") or {}).get("kind") in ("activation", "all_clear")]
    pairs = []
    for r in records:
        t = parse_iso(r.get("reported_at"))
        for p in posts:
            if t is None or p["raw"].get("kind") != r["raw"].get("kind"):
                continue
            gap = abs((parse_iso(p["reported_at"]) - t).total_seconds()) / 60
            if gap <= minutes:
                pairs.append((gap, r["event_id"], p["event_id"], r, p))
    pairs.sort(key=lambda x: (x[0], x[1], x[2]))
    used_r, used_p, n = set(), set(), 0

    def link(r, p, gap, why=""):
        r["duplicate_of"] = p["event_id"]
        r["raw"]["_link_basis"] = (f"the same {r['raw'].get('kind').replace('_', '-')} notice on the city's CSO "
                                   f"Discharge Notification page, published {round(gap)} min apart{why}")
    for gap, rid, pid, r, p in pairs:
        if rid in used_r or pid in used_p:
            continue
        used_r.add(rid)
        used_p.add(pid)
        link(r, p, gap)
        n += 1
    linked = [r for r in records if r.get("duplicate_of")]
    for r in records:
        if r.get("duplicate_of"):
            continue
        t = parse_iso(r.get("reported_at"))
        twin = next((x for x in linked if x["raw"].get("kind") == r["raw"].get("kind") and t
                     and abs((parse_iso(x["reported_at"]) - t).total_seconds()) <= RESEND_MINUTES * 60), None)
        if twin:
            post = next(p for p in posts if p["event_id"] == twin["duplicate_of"])
            link(r, post, abs((parse_iso(post["reported_at"]) - t).total_seconds()) / 60, " (the e-mail was sent twice)")
            n += 1
    return n
