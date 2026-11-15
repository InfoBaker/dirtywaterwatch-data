"""Free-text scrub for the Colorado, Montana and Wyoming feeds (co_cdphe_toxic_algae notes, wy_deq_hcb_bulletins
cells, mt_deq_hab_map names), run after common.scrub_text and scrub_names on everything they save. It adds the forms
those miss (lessons, item 6; Astra review 2026-11-15 P1): a title before a name ("Dr. Example Person"), "Contact
<Name>", "<Name> reported", "at the home of <Name>", any street address's house number including a suffix or a fraction
("123-A Sample Road", "12 1/2 Sample St"), and a coordinate written in the text, rounded to three decimals. Used only by
those three modules, so no other state's output changes.
"""
from __future__ import annotations

import re

from common import HOUSE_NUMBER_REMOVED, scrub_names, scrub_text, strip_house_numbers

_NAME = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*){0,2}"
TITLE_RE = re.compile(rf"\b(?:Dr\.|Mr\.?|Mrs\.?|Ms\.?|Mx\.?|Prof\.|Rev\.)\s+{_NAME}")
CONTACT_RE = re.compile(rf"\b([Cc]ontact(?:ed)?:?\s+){_NAME}")
REPORTED_RE = re.compile(rf"\b{_NAME}(?=\s+(?:reported|called|emailed|e-mailed|observed|noticed)\b)")
HOME_RE = re.compile(rf"\b((?:at|near|by)\s+the\s+(?:home|house|residence|property|cabin|dock)\s+of\s+){_NAME}", re.I)
SUFFIX_NUMBER_RE = re.compile(r"(?<![\w.,/:-])\d{1,6}(?:\s?-\s?[A-Za-z0-9]{1,3}|\s\d/\d|[A-Za-z])"
                              r"(?=\s+(?:[NSEW]\.?\s+)?[A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*){0,2}\s+"
                              r"(?i:street|st|road|rd|avenue|ave|lane|ln|drive|dr|way|court|ct|place|pl|circle|cir|"
                              r"boulevard|blvd|highway|hwy|trail|trl|loop|parkway|pkwy|terrace|ter)\b)")
COORD_RE = re.compile(r"(?<![\d.])(-?\d{1,3}\.\d{4,})(?![\d])")
NAME_REMOVED = "[name removed]"


def scrub(v: str | None) -> str:
    """The text with personal forms removed and coordinates rounded to three decimals."""
    t = scrub_names(scrub_text(" ".join(str(v or "").split())))
    t = TITLE_RE.sub(NAME_REMOVED, t)
    t = CONTACT_RE.sub(lambda m: m.group(1) + NAME_REMOVED, t)
    t = HOME_RE.sub(lambda m: m.group(1) + NAME_REMOVED, t)
    t = REPORTED_RE.sub(lambda m: m.group(0) if m.group(0).split()[-1] in _NOT_A_NAME_END else NAME_REMOVED, t)
    t = SUFFIX_NUMBER_RE.sub(HOUSE_NUMBER_REMOVED, t)
    t = strip_house_numbers(t, street_word_only=True)
    return COORD_RE.sub(lambda m: f"{round(float(m.group(1)), 3):.3f}", t)


# "Example Lake reported", "CPW Staff reported": the words before "reported" that end a body or a water, not a person
_NOT_A_NAME_END = {"Lake", "Reservoir", "Pond", "River", "Creek", "Park", "Parks", "Staff", "County", "City", "Town",
                   "Department", "District", "Service", "Division", "Office", "Agency", "Wildlife", "Rangers", "Ranger"}
