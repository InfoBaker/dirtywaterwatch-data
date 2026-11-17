"""City of Somerville's "CSO and SSO Activation and Discharge Notifications" list (not a feed).

Signed up 2026-11-02; only the sign-up form's receipts (Jotform, "We have received your response for CSO Notification
Sign-Up") have arrived, and Somerville's last overflow before then was 2026-07-22. The notice's wording is taken from
the city's own CSO page, which repeats each notice as its headline (read 2026-11-17):

    Combined Sewer Overflow (CSO) Event on July 22, 2026 at 4:25 p.m.  at SOM-001A on the Alewife Brook

That sentence, when a message carries exactly one, gives the start, the outfall and the water. It says nothing of
whether the overflow is still going, so the record's status is "unknown" (no end confirmed). The page's public health
warning ("avoiding contact with water bodies during rainstorms and for 48 hours afterwards") is kept as the advice.
The page's discharge table (start, stop, duration, volume in million gallons, rainfall) is a web channel of its own
and is not read here. Anything else from the list is a failure with its reason, kept until a rule is written from it.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from common import scrub_text

from .ma_common import ma_record
from .message import Mail, Result

NAME = "somerville"
VERSION = 2
TZ = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october november "
                                     "december".split(), 1)}
HEADLINE = re.compile(
    r"(?i)(Combined Sewer Overflow \(CSO\)|Sanitary Sewer Overflow \(SSO\)) Event on\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),\s*(\d{4})"
    r"\s+at\s+(\d{1,2}):(\d{2})\s*([ap])\.?\s?m\.?\s+at\s+SOM-?0*(\d{1,3})([A-Z]?)\s+on the\s+([A-Z][\w' ]*?[\w])\s*(?:[.\n]|$)")
WARNING = re.compile(r"(?i)(Public health officials recommend avoiding contact with water bodies during rainstorms and "
                     r"for (\d+) hours afterwards[^.]*\.)")


def parse(mail: Mail, spec: dict, ctx: dict) -> Result:
    if re.search(r"(?i)we have received your response|thank(?:s| you) for (?:signing|subscribing)|confirm",
                 mail.subject):
        return Result("account", note="sign-up form receipt (not read)")
    heads = list(HEADLINE.finditer(mail.text))
    if len(heads) != 1:
        return Result("failed", note=("no 'Combined Sewer Overflow (CSO) Event on <date> at <time> at SOM-<n> on the "
                                      "<water>' sentence" if not heads else "several event sentences: layout not known"))
    m = heads[0]
    kind, mon, day, year, hh, mm, ap, num, suffix, water = m.groups()
    if not 1 <= int(hh) <= 12:
        return Result("failed", note="the event sentence's hour is not a 12-hour clock time")
    h = int(hh) % 12 + (12 if ap.lower() == "p" else 0)
    try:
        start = datetime(int(year), MONTHS[mon.lower()], int(day), h, int(mm), tzinfo=TZ)
    except ValueError:
        return Result("failed", note="the event sentence's date or time is not a valid time")
    rec = ma_record(mail, spec, ctx, 1, permit=spec.get("npdes_permit"), org="City of Somerville",
                    location=f"SOM{int(num):03d}{suffix.upper()}", num=int(num), suffix=suffix.upper(), state="active",
                    start=start, end=None, vol_text=None, water=water.strip(), block="",
                    event_type="sso" if "SSO" in kind.upper() else "cso",
                    extra_raw={"_event_sentence": scrub_text(re.sub(r"\s+", " ", m.group(0)).strip())})
    rec["status"] = "unknown"           # the sentence gives a start; whether it is still going is not said
    rec["raw"]["_status_basis"] = "the notice gives the start only; ongoing or ended is not stated"
    warn = WARNING.search(mail.text)
    if warn:        # the warning's hours count from the end of a rainstorm, not of this discharge: quoted, no window
        rec["advice_text"] = scrub_text(warn.group(1))
        rec["advice_window_hours"] = None
        rec["advice_window_basis"] = "the notice's public health warning (its hours count from the end of a rainstorm)"
    return Result("notice", records=[rec])
