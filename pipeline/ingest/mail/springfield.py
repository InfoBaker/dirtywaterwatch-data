"""Springfield Water and Sewer Commission's public advisories by e-mail (Constant Contact list "CSO Notification -
Public"), the advisory 314 CMR 16.04 requires (not a feed).

No message from this list has reached the project yet (signed up 2026-11-02 and again 2026-11-17), so this parser is
built from what 16.04(10) says a notice must carry and from the portal's record of the same notices: the permittee,
the outfall (SPR012 in the portal), the start and, when it has stopped, the approximate cessation time, the estimated
volume, the affected waters and towns, the untreated-sewage statement and the required advice. The subject is
bilingual ("CSO Public Advisory - Notice Aviso de aviso público de CSO"); only the English part is read.

It reads labelled lines ("Outfall: SPR012", "Start: 11/06/2026 11:10 AM", "Estimated Volume: 1,234,000 gallons") in a
block per outfall, with the value on the label's line or the next. Strict on purpose: a notice whose outfall, start
or status it cannot read, or that names several outfalls in a layout it does not know, is a failure with its reason,
kept and counted for a person to see, never a guess. When the first real notice arrives, check the parse against it
and raise VERSION.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from common import scrub_text

from .ma_common import ma_record
from .message import Mail, Result, outfall_number

NAME = "springfield"
VERSION = 1
TZ = ZoneInfo("America/New_York")

L_OUTFALL = (r"(?:CSO\s+)?(?:Outfall|Discharge Location|Location of (?:the )?Discharge|Location|CSO)"
             r"(?:\s+(?:ID|Number|No\.?|#|Location))?")
L_START = (r"(?:Date (?:and|&) Time (?:of )?(?:the )?(?:Discharge|Overflow)(?: (?:Began|Started|Start))?|"
           r"(?:Discharge|Overflow|Event) (?:Start|Began|Started)(?: Date(?: (?:and|&) Time)?| Time)?|"
           r"Start(?:ed)?(?: Date(?: (?:and|&) Time)?| Time)?|Time of (?:the )?(?:Discharge|Overflow)(?: Start)?|"
           r"Date/Time (?:Discharge|Overflow) (?:Began|Started))")
L_END = (r"(?:(?:Approximate )?(?:Date (?:and|&) )?Time (?:of )?(?:Cessation|(?:the )?(?:Discharge|Overflow) "
         r"(?:Ceased|Ended|Stopped))|(?:Discharge|Overflow|Event) (?:End|Ended|Ceased|Stopped)(?: Date(?: (?:and|&) "
         r"Time)?| Time)?|Ceased(?: at)?|End(?:ed)?(?: Date(?: (?:and|&) Time)?| Time)?|Cessation(?: Time)?)")
L_VOLUME = (r"(?:Estimated (?:Discharge |Overflow )?Volume(?: of (?:the )?(?:Discharge|Overflow))?(?: \(gallons\))?|"
            r"Volume(?: \(gallons\))?)")
L_STATUS = r"(?:(?:Discharge |Overflow |Current )?Status)"
L_WATER = r"(?:Receiving Water(?:s| ?bod(?:y|ies))?|Affected Water ?bod(?:y|ies)|Water ?bod(?:y|ies)(?: Affected)?)"
L_TOWNS = r"(?:Affected (?:Communities|Municipalities|Towns)|Municipalit(?:y|ies) Affected)"
SPANISH = re.compile(r"(?im)^\s*(?:Aviso|AVISO|Ubicaci[oó]n|Titular del permiso|Fecha y hora|Estimado|En espa[nñ]ol)\b")

MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october november "
                                     "december".split(), 1)}
NUM_DT = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)(?:,?\s+(?:at\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*"
                    r"([AaPp]\.?\s?[Mm]\.?)?)?")
WORD_DT = re.compile(r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december)"
                     r"\s+(\d{1,2}),?\s+(\d{4})(?:,?\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*([ap]\.?\s?m\.?)?)?")


def read_dt(s: str | None) -> tuple[datetime | None, bool]:
    """(local time, has a clock time). A date without a time is returned with False: not precise enough for a start."""
    if not s:
        return None, False
    m = NUM_DT.search(s)
    if m:
        mo, d, y, hh, mm, ss, ap = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        mon, day = int(mo), int(d)
    else:
        m = WORD_DT.search(s)
        if not m:
            return None, False
        mname, d, y, hh, mm, ap = m.groups()
        ss = None
        y, mon, day = int(y), MONTHS[mname.lower()], int(d)
    if hh is None:
        try:
            return datetime(y, mon, day, tzinfo=TZ), False
        except ValueError:
            return None, False
    h = int(hh)
    if ap:
        pm = ap.lower().startswith("p")
        if not 1 <= h <= 12:
            return None, False
        h = (h % 12) + (12 if pm else 0)
    try:
        return datetime(y, mon, day, h, int(mm), int(ss or 0), tzinfo=TZ), True
    except ValueError:
        return None, False


def labelled(block: str, label: str) -> str | None:
    """The value after "Label:" on its line, or on the next line when the label stands alone (table cells)."""
    m = re.search(rf"(?im)^\s*{label}\s*:?\s*(?::\s*)?(.*?)\s*$", block)
    if not m:
        return None
    v = m.group(1).strip(" :")
    if v:
        return v
    rest = block[m.end():].lstrip("\n").split("\n", 1)[0].strip()
    return rest or None


def english(text: str) -> str:
    m = SPANISH.search(text)
    return text[:m.start()] if m else text


def outfall_blocks(text: str) -> list[str]:
    starts = [m.start() for m in re.finditer(rf"(?im)^\s*{L_OUTFALL}\s*:", text)]
    if not starts:
        return []
    return [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]


def state_of(block: str) -> str | None:
    st = labelled(block, L_STATUS) or ""
    said = st + " " + " ".join(re.findall(r"(?i)(?:discharge|overflow)\s+(?:is|has|was)\s+(?:been\s+)?(\w+)", block))
    low = said.lower()
    if re.search(r"\b(ceased|ended|stopped|over|inactive)\b", low):
        return "ceased"
    if re.search(r"\b(ongoing|active|continuing|occurring|in progress)\b", low):
        return "active"
    return None


def parse(mail: Mail, spec: dict, ctx: dict) -> Result:
    if re.search(r"(?i)confirm|welcome|thank(?:s| you) for (?:signing|subscribing|joining)|verify|you(?:'re| are) "
                 r"(?:now )?subscribed", mail.subject) and not re.search(r"(?i)advisory|overflow|discharge", mail.subject):
        return Result("account", note="sign-up or confirmation message (not read)")
    text = english(mail.text)
    if not re.search(r"(?i)\b(CSO|combined sewer|overflow|discharge|blend|SSO)\b", mail.subject + " " + text):
        return Result("not_notice", note="no discharge words in the subject or the English text")
    pm = re.search(r"\b(MA\d{7})\b", text)
    permit = pm.group(1) if pm else spec.get("npdes_permit")
    if pm and spec.get("npdes_permit") and pm.group(1) != spec["npdes_permit"]:
        return Result("failed", note=f"permit {pm.group(1)} is not the list's operator ({spec['npdes_permit']})")
    blocks = outfall_blocks(text)
    if not blocks:
        return Result("failed", note="no outfall line (Outfall:, Location:): not a layout this parser knows")
    head = text[:text.find(blocks[0])]
    records, problems = [], []
    for n, b in enumerate(blocks, 1):
        loc = labelled(b, L_OUTFALL) or ""
        ids = {outfall_number(x) for x in re.findall(r"(?i)\b(?:SPR|CSO)[\s#_-]*\d{1,3}[A-Z]?\b", loc)}
        ids.discard((None, ""))
        if len(ids) != 1:
            problems.append(f"block {n}: {'no' if not ids else 'several'} outfall numbers on the outfall line")
            continue
        num, suffix = next(iter(ids))
        both = b + "\n" + head          # a start or a water given once above the outfalls is read for each
        start, start_clock = read_dt(labelled(b, L_START) or labelled(head, L_START))
        end, end_clock = read_dt(labelled(b, L_END) or labelled(head, L_END))
        state = state_of(b) or state_of(head)
        if state is None and end is not None:
            state = "ceased"
        if state is None:
            problems.append(f"block {n}: no status (ongoing or ceased) found")
            continue
        if start is None or not start_clock:
            problems.append(f"block {n}: no start date and time found")
            continue
        if end is not None and not end_clock:
            end = None
        etype = "blended" if re.search(r"(?i)blend", mail.subject + " " + both) else (
            "sso" if re.search(r"(?i)\bSSO\b|sanitary sewer overflow", mail.subject + " " + both) else "cso")
        vol = labelled(b, L_VOLUME) or labelled(head, L_VOLUME)
        extra = {"_subject_kind": etype}
        towns = labelled(b, L_TOWNS) or labelled(head, L_TOWNS)
        if towns:
            extra["affected_communities"] = scrub_text(towns)
        if end is not None:
            extra["_ended_at_basis"] = "the notice's cessation time"
        records.append(ma_record(mail, spec, ctx, n, permit=permit, org="Springfield Water and Sewer Commission",
                                 location=f"SPR{num:03d}{suffix}", num=num, suffix=suffix, state=state,
                                 start=start, end=end, vol_text=vol,
                                 water=labelled(b, L_WATER) or labelled(head, L_WATER), block=both,
                                 event_type=etype, extra_raw=extra))
    if problems:
        return Result("failed", note="; ".join(problems))
    return Result("notice", records=records)
