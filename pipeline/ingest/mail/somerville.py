"""City of Somerville's "CSO and SSO Activation and Discharge Notifications" list (not a feed).

Only the sign-up form's receipts (Jotform, "We have received your response for CSO Notification Sign-Up") have
arrived since the address was signed up on 2026-11-02; no notice yet, so no notice layout is known. A receipt is an
account message; any other message is a failure with its reason, kept and counted until a parser for the real
notice is written from it (raise VERSION then).
"""
from __future__ import annotations

import re

from .message import Mail, Result

NAME = "somerville"
VERSION = 1


def parse(mail: Mail, spec: dict, ctx: dict) -> Result:
    if re.search(r"(?i)we have received your response|thank(?:s| you) for (?:signing|subscribing)|confirm",
                 mail.subject):
        return Result("account", note="sign-up form receipt (not read)")
    return Result("failed", note="no parser yet for Somerville's notice layout: kept for a rule to be written")
