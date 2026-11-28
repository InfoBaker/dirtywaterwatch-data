"""Compatibility helpers for Iowa and Idaho: preserve public-record text and source points.
Legacy detectors remain available for parsing; default scrub and home-place suppression are disabled.
Requested removals are applied at export."""
from __future__ import annotations

import re

from common import scrub_text, strip_house_numbers
from ingest.wv_la_privacy import ADDRESS_RE, HOUSE_NUMBER, names_a_person

WITHHELD = "[withheld: the text may name a person]"
HOME_OF_RE = re.compile(r"(?i)\b(?:home|house|residence|property|farm|yard)\s+of\s+\S")
HOME_RE = re.compile(r"(?i)\b(?:private\s+(?:home|residence|property)|(?:a|the|his|her|their)\s+(?:home|house|residence|"
                     r"yard|basement)|homeowner'?s?|residential\s+(?:home|lot|yard|property)|basement\s+backup)\b")
COORD_RE = re.compile(r"(?<![\d.])(-?\d{1,3}\.\d{4,})(?![\d.])")


# a street name's abbreviation ('Example Dr.', 'Sample St.') is not a title before a name: masked for the person check
STREET_ABBR_RE = re.compile(r"\b([A-Z][a-z]+)\s+(?:Dr|St|Ave|Rd|Blvd|Ct|Ln|Pl|Hwy)\.(?=\s|$|[,;)])")
# "the Department has been contacted regarding a discharge": a contact verb before what it is about, not a name
AGENCY_CONTACTED_RE = re.compile(r"(?i)\b(?:contacted|called)\s+(?=(?:regarding|about|concerning|by\s+the|by\s+city|"
                                 r"after|when|on|at\s+\d)\b)")
BLOCK_RE = re.compile(r"(?i)^\d{1,6}\s*-?\s*(?:blk|block)\b")


def _house(m: re.Match) -> str:
    s = m.group(0)
    if BLOCK_RE.match(s):                   # '200-blk Example Ave': a block, not a house number
        return s
    return re.sub(rf"(?i)^{HOUSE_NUMBER}", "[house number removed]", s)


def _round_coord(m: re.Match) -> str:
    v = float(m.group(1))
    return f"{round(v, 3):.3f}" if abs(v) <= 180 else m.group(1)


def scrub(text: str | None) -> str | None:
    """Preserve the source public record (decision 57)."""
    return text


def home_place(*texts: str | None) -> bool:
    """Preserve the source public record (decision 57)."""
    return False


def scrub_sentences(text: str | None) -> str | None:
    """Preserve the source public record (decision 57)."""
    return text
