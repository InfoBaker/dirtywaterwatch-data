"""City of Holyoke's CSO notices by e-mail (Everbridge), the advisory 314 CMR 16.04 requires (not a feed).

Shape (the city's own copies of these e-mails on holyoke.org, November 2023 to January 2026): one block per outfall,
English then Spanish, labelled lines:

    Permittee : City of Holyoke Wastewater Pollution Control Permit #MA0101630
    Location: CSO 021B
    Time of discharge: 01/10/26 18:55:00 EST
    Estimated Volume (gallons): 225,192
    The estimated volume is calculated by taking the total overflow volume for the last 3 years and dividing by ...
    This Discharge is Active CSO at this time.          (or "is Ceased", "has ceased", "is Active for 8 hours")
    Affected Water Bodies: Connecticut River
    Avoid contact with these waterbodies for 48 hours after the discharge ceases due to ... The discharge consists of
    rainwater and untreated sewage and waste.
    Affected communities: Springfield, West Springfield, ...

Read as follows. In an "Active" notice the time is the start; in a "Ceased" notice it is the time the discharge ceased
(the same outfall's Active and Ceased notices of 2025-09-05 give 01:35 and 06:35); "Active for 8 hours" is the 8-hour
update and gives the start again. The time is printed "EST" all year and is read as Holyoke's local clock. The volume
is the city's estimate (its 3-year average per event), kept with its method. Only the English block is read; a block
without the permit, the outfall, the time or the status line is a failure, and so is any other layout (the 2024
"Dear Health Official" table is not read).
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from common import scrub_text

from .ma_common import ma_record
from .message import Mail, Result, outfall_number

NAME = "holyoke"
VERSION = 1
TZ = ZoneInfo("America/New_York")
TIME_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)\s+(\d{1,2}):(\d{2})(?::(\d{2}))?")


def _line(block: str, label: str) -> str | None:
    m = re.search(rf"(?im)^\s*{label}\s*:\s*(.*?)\s*$", block)
    return m.group(1).strip() if m and m.group(1).strip() else None


def english_blocks(text: str) -> list[str]:
    """The English blocks: each starts at "Permittee :" and stops at the next one or at the Spanish half."""
    out = []
    for part in re.split(r"(?im)^\s*(?=Permittee\s*:)", text):
        if not re.match(r"(?i)\s*Permittee\s*:", part):
            continue
        part = re.split(r"(?im)^\s*(?:Titular del permiso|_{6,})", part)[0]
        out.append(part.strip())
    return out


def read_time(s: str | None) -> tuple[datetime | None, str | None]:
    m = TIME_RE.search(s or "")
    if not m:
        return None, None
    mo, d, y, hh, mm, ss = m.groups()
    y = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return datetime(y, int(mo), int(d), int(hh), int(mm), int(ss or 0), tzinfo=TZ), m.group(0)
    except ValueError:
        return None, None


def parse(mail: Mail, spec: dict, ctx: dict) -> Result:
    text = mail.text
    if re.search(r"(?i)verification code|verify your|confirm your (?:e-?mail|account|contact)|welcome to", mail.subject) \
            and not re.search(r"(?im)^\s*Permittee\s*:", text):
        return Result("account", note="account or verification message (not read)")
    blocks = english_blocks(text)
    if not blocks:
        return Result("failed", note="no 'Permittee :' block: not the notice layout this parser knows")
    records, problems = [], []
    for n, b in enumerate(blocks, 1):
        rec, why = block_record(b, n, mail, spec, ctx)
        if rec is None:
            problems.append(f"block {n}: {why}")
        else:
            records.append(rec)
    if problems:
        return Result("failed", note="; ".join(problems))
    return Result("notice", records=records)


def block_record(b: str, n: int, mail: Mail, spec: dict, ctx: dict) -> tuple[dict | None, str | None]:
    permittee = _line(b, r"Permittee")
    pm = re.search(r"Permit\s*#?\s*(MA\d{7})", permittee or "")
    if not pm:
        return None, "no permit number on the Permittee line"
    permit = pm.group(1)
    if spec.get("npdes_permit") and permit != spec["npdes_permit"]:
        return None, f"permit {permit} is not the list's operator ({spec['npdes_permit']})"
    location = _line(b, r"Location")
    num, suffix = outfall_number(location)
    if num is None:
        return None, "no CSO number on the Location line"
    time_line = _line(b, r"Time of discharge")
    t, _ = read_time(time_line)
    if t is None:
        return None, "no date and time on the 'Time of discharge' line"
    sm = re.search(r"(?i)This discharge (?:is|has) (.+?) at this time", b)
    if not sm:
        return None, "no 'This Discharge is ... at this time' line"
    said = sm.group(1).strip()
    low = said.lower()
    if low == "ceased":
        state = "ceased"
    elif low.startswith("active for 8 hours"):
        state = "update"
    elif low.startswith("active"):
        state = "active"
    else:
        return None, f"status line not known: {said[:60]!r}"
    activated_word = bool(re.search(r"(?i)\bACTIVATED at\b", time_line or ""))
    start = end = None
    if state in ("active", "update") or activated_word:
        start = t
    else:
        end = t
    method = re.search(r"(?i)(The estimated volume is calculated by [^.]+\.)", b)
    towns = _line(b, r"Affected communities")
    location = re.sub(r"(?i)\s*partly treated\s*", " ", location or "").strip()
    extra = {"_status_line": scrub_text(f"This Discharge is {said} at this time."),
             "_time_line": scrub_text(time_line or ""),
             "_tz_assumed": "America/New_York: the notice prints EST all year; read as the local clock"}
    if state == "ceased" and not activated_word:
        extra["_ended_at_basis"] = "the time on a 'Ceased' notice is the time the discharge ceased"
    if activated_word:
        extra["_time_note"] = "the time line reads 'ACTIVATED at' on a Ceased notice: read as the start; no end given"
    if method:
        extra["volume_method"] = scrub_text(method.group(1))
    if towns:
        extra["affected_communities"] = scrub_text(towns)
    if re.search(r"(?i)partly treated|partially treated", _line(b, r"Location") or ""):
        extra["partly_treated"] = True
    org = re.sub(r"\s*Permit\s*#?\s*MA\d{7}.*$", "", permittee or "").strip() or None
    rec = ma_record(mail, spec, ctx, n, permit=permit, org=org, location=location, num=num, suffix=suffix,
                    state=state, start=start, end=end, vol_text=_line(b, r"Estimated Volume \(gallons\)"),
                    water=_line(b, r"Affected Water Bodies"), block=b, extra_raw=extra)
    return rec, None
