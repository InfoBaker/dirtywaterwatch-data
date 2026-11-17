"""Connecticut DEEP's press releases by e-mail (DEEP Communications) (not a feed).

The list carries every DEEP release: hunting seasons, rebates, weekly wrap-ups, and now and then a sewage spill
advisory (East Windsor 2025) or a reminder to avoid the water after heavy rain (2026-07-07). Free text, no fixed
fields, so nothing is taken from it by guesswork: a release that does not speak of sewage is not a notice; one that
does is kept as "needs a rule" and counted, for a rule (or the model step, once one is written) to read it.
"""
from __future__ import annotations

import re

from .message import Mail, Result

NAME = "ct_deep_press"
VERSION = 1
SEWAGE = re.compile(r"(?i)\b(sewage|sewer overflow|combined sewer|wastewater (?:spill|discharge|release|bypass)|"
                    r"raw sewage|untreated (?:sewage|wastewater)|sanitary sewer|SSO|CSO|bypass(?:ed)? (?:of )?"
                    r"(?:the )?(?:treatment|plant)|avoid (?:all )?contact with)\b")


def parse(mail: Mail, spec: dict, ctx: dict) -> Result:
    words = SEWAGE.findall(mail.subject + "\n" + mail.text[:20000])
    if not words:
        return Result("not_notice", note="press release that does not speak of sewage")
    return Result("needs_rule", note=f"press release that speaks of sewage ({len(words)} mentions): no rule reads "
                                     "its facts yet")
