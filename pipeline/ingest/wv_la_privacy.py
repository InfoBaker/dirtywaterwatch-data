"""Privacy checks shared by the West Virginia and Louisiana feeds only (wv_dep_hab_advisories,
la_baton_rouge_quarterly): free text that can carry a street address or the name of who reported, sampled or can be
called is cut, or withheld, before anything is saved. Case does not matter ('123 example lane', '123 EXAMPLE LANE')."""
from __future__ import annotations

import re

STREET_WORDS = (r"(?:lane|ln|road|rd|street|st|avenue|ave|drive|dr|court|ct|way|boulevard|blvd|circle|cir|place|pl|"
                r"pike|highway|hwy|route|rte|trail|trl|terrace|ter|parkway|pkwy|hollow|holw|ridge|loop|alley|square|"
                r"sq|cove|cv|row|crossing|xing)")
# a number before a street word, one to four words apart, in any case: '123 Example Lane', '12B N. EXAMPLE ST'
ADDRESS_RE = re.compile(rf"(?i)(?<![\w.,/:-])\d{{1,6}}[a-z]?\s+(?:[nsew]\.?\s+)?(?:[\w'.-]+\s+){{0,4}}?{STREET_WORDS}\b\.?")
# a label that introduces who reported, sampled, collected or can be called, with or without a colon
PERSON_LABEL_RE = re.compile(
    r"(?i)\b(?:reporter|reported\s+by|reporting\s+party|reportee|caller|complainant|submitter|submitted\s+by|"
    r"(?:sample\s+)?collector|collected\s+by|sampler|sampled\s+by|observer|observed\s+by|"
    r"point\s+of\s+contact|photo(?:graph)?(?:er|\s+by)|resident|homeowner|landowner|property\s+owner|"
    r"neighbou?r|courtesy\s+of|thanks\s+to)\b|(?i:\b(?:contact(?:\s+person)?|name|phone|e-?mail)\s*:)"
    r"|\b(?:Mr|Mrs|Ms|Miss)\.?\s+[A-Z]|@")


def has_address(text: str) -> bool:
    return bool(ADDRESS_RE.search(text or ""))


def names_a_person(text: str) -> bool:
    return bool(PERSON_LABEL_RE.search(text or ""))
