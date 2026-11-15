"""Privacy for the Iowa and Idaho feeds only (ia_dnr_focomp, ia_waterloo_sso, ia_dnr_news, id_deq_cyanohab): the
scrub that runs on free text before the first save and again on everything carried from earlier state. It adds to
common.scrub_text and common.strip_house_numbers (which other states use unchanged) the forms they miss: a house number
with a suffix or a fraction ('123-A', '12 1/2'), a coordinate inside the text (rounded to three decimals like any
report point), and text that names or may name a person ('Contact ...', 'Dr. ...', '... reported', 'the home of ...'),
which is withheld whole, since it cannot be told apart from text that does not. A place described as a private home
loses its point and its street (home_place). The detectors are wv_la_privacy's, imported, not changed."""
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
    """The strict scrub: common's (emails, phones, titled names, house numbers), then every remaining house number
    before a street word, coordinates rounded; text that may name a person is withheld whole. None stays None."""
    if text is None:
        return None
    t = strip_house_numbers(scrub_text(str(text)))
    t = ADDRESS_RE.sub(_house, t)
    t = COORD_RE.sub(_round_coord, t)
    probe = STREET_ABBR_RE.sub(lambda m: m.group(1) + " Street", t)
    probe = AGENCY_CONTACTED_RE.sub("reached ", probe)
    if t != WITHHELD and (names_a_person(probe) or HOME_OF_RE.search(probe)):
        return WITHHELD
    return t


def home_place(*texts: str | None) -> bool:
    """True when the text describes the place as a private home: the point and the street are removed, not rounded."""
    return any(t and (HOME_RE.search(t) or HOME_OF_RE.search(t)) for t in texts)


def scrub_sentences(text: str | None) -> str | None:
    """The strict scrub sentence by sentence: a sentence that may name a person is withheld, the rest kept (an agency's
    release keeps its facts when its contact line names someone)."""
    if text is None:
        return None
    out = []
    for line in str(text).split("\n"):
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[\"“])", line)
        out.append(" ".join(s for s in (scrub(x) for x in parts) if s))
    return "\n".join(out)
