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
    rec = event(
        source_id=spec["source_id"], source_record_id=mail.inbound_id,
        event_type="cso", status="ongoing" if kind == "activation" else "ended",
        discharger_id=spec.get("operator"), discharger_name="City of Manchester DPW Environmental Protection Division",
        npdes_permit=spec.get("npdes_permit"), waterbody_text=None, water_slugs=list(WATERS), water_match="inferred",
        started_at=None, ended_at=None, time_precision="minute",
        reported_at=mail.received_at, published_at=mail.received_at, material=MATERIAL,
        authority="City of Manchester EPD (CSO Discharge Notification e-mail)",
        source_url=spec.get("source_url"),
        raw={"_channel": "email", "_list": mail.list_id, "_inbound_id": mail.inbound_id,
             "_received_at": mail.received_at, "_sent_at": mail.sent_at, "kind": kind,
             "_notice_sentence": f"the City of Manchester {sentence}", "_all_clear_hours": hours,
             "_time_basis": "no start in the notice: the time the e-mail reached the project"},
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
    """Each e-mail notice that repeats a post on the city's page (same kind, published within `minutes` of the
    e-mail's sending time, else its receipt) becomes that post's duplicate: one notice, two channels."""
    posts = [p for p in page_records if str(p.get("source_record_id") or "").startswith("manchester:")
             and p.get("reported_at") and (p.get("raw") or {}).get("kind") in ("activation", "all_clear")]
    used, n = set(), 0
    for r in sorted(records, key=lambda r: r.get("reported_at") or ""):
        t = parse_iso(r["raw"].get("_sent_at")) or parse_iso(r.get("reported_at"))
        if t is None:
            continue
        best = None
        for p in posts:
            if p["raw"].get("kind") != r["raw"].get("kind") or p["event_id"] in used:
                continue
            gap = abs((parse_iso(p["reported_at"]) - t).total_seconds()) / 60
            if gap <= minutes and (best is None or gap < best[0]):
                best = (gap, p)
        if best:
            used.add(best[1]["event_id"])
            r["duplicate_of"] = best[1]["event_id"]
            r["raw"]["_link_basis"] = (f"the same {r['raw'].get('kind').replace('_', '-')} notice on the city's CSO "
                                       f"Discharge Notification page, published {round(best[0])} min apart")
            n += 1
    return n
