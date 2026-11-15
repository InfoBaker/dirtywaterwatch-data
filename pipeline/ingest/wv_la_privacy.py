"""Privacy checks shared by the West Virginia and Louisiana feeds only (wv_dep_hab_advisories,
la_baton_rouge_quarterly): free text that can carry a street address or the name of who reported, sampled or can be
called is cut, or withheld, before anything is saved. Case does not matter ('123 example lane', '123 EXAMPLE LANE')."""
from __future__ import annotations

import re

STREET_WORDS = (r"(?:lane|ln|road|rd|street|st|avenue|ave|drive|dr|court|ct|way|boulevard|blvd|circle|cir|place|pl|"
                r"pike|highway|hwy|route|rte|trail|trl|terrace|ter|parkway|pkwy|hollow|holw|ridge|loop|alley|square|"
                r"sq|cove|cv|row|crossing|xing)")
# a house number, with a suffix or a fraction ('123', '12B', '123-A', '12-14', '12 1/2', '12½'), before a street word,
# one to four words apart, in any case: '123 Example Lane', '12B N. EXAMPLE ST', '123-A Example Lane'
HOUSE_NUMBER = r"\d{1,6}(?:[-/]?[a-z0-9]{1,4}\b)?(?:\s*-\s*[a-z]\b)?(?:\s+\d/\d|\s*\u00bd)?"
ADDRESS_RE = re.compile(rf"(?i)(?<![\w.,/:-]){HOUSE_NUMBER}\s+(?:[nsew]\.?\s+)?(?:[\w'.-]+\s+){{0,4}}?{STREET_WORDS}\b\.?")
# a label that introduces who reported, sampled, collected or can be called, with or without a colon
PERSON_LABEL_RE = re.compile(
    r"(?i)\b(?:reporter|reported\s+by|reporting\s+party|reportee|caller|complainant|submitter|submitted\s+by|"
    r"(?:sample\s+)?collector|collected\s+by|sampler|sampled\s+by|observer|observed\s+by|"
    r"point\s+of\s+contact|photo(?:graph)?(?:er|\s+by)|resident|homeowner|landowner|property\s+owner|"
    r"neighbou?r|courtesy\s+of|thanks\s+to)\b|(?i:\b(?:contact(?:\s+person)?|name|phone|e-?mail)\s*:)"
    r"|\b(?:Mr|Mrs|Ms|Miss)\.?\s+[A-Z]|@"
    # a contact or call form naming whom to reach ('Contact Example Person', 'call Example', 'attn: ...'), in any
    # case; 'contact with the water', 'avoid contact.' and the like are not names
    r"|(?i:\b(?:contact(?:ing|ed)?|call(?:ing|ed)?|ask\s+for|speak\s+(?:to|with)|spoke\s+(?:to|with)|talk\s+to)\s+"
    r"(?!(?:with|of|to|and|or|for|in|on|at|from|by|water|the\s+water|this|that|these|those|it|skin|pets|animals|"
    r"dogs|livestock|any|all|affected|is|was|may|can|should|must|if|when|until|while|near|around|within|along|"
    r"below|above|downstream|upstream|between|during|unless|after|before|as|except)\b)[a-z\[])"
    r"|(?i:\b(?:attn|attention|c/o|care\s+of)\b)"
    # an honorific before a name, in any case ('Dr. Example Person', 'dr. example', 'MRS EXAMPLE')
    r"|(?i:\b(?:mr|mrs|ms|mx|dr|prof|rev|sgt|capt|lt|officer|deputy)\.\s*[a-z])"
    r"|\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Rev|MR|MRS|MS|MISS|DR)\s+[A-Z]")


# a receiving-water cell that is a water's name: words of letters only, at most six, one of them a water word
WATER_WORDS = (r"(?:creek|bayou|canal|branch|lateral|river|lake|ditch|drain|drainage|coulee|slough|pond|run|stream|"
               r"tributary|trib|channel|waterway|swamp|marsh|lagoon|bay|spillway|diversion|basin|gully|brook|fork|"
               r"reservoir|sound|pass)")
WATER_NAME_RE = re.compile(rf"(?i)^(?=(?:.*\b{WATER_WORDS}\b))[a-z][a-z'.-]*(?:[ ][a-z][a-z'.-]*){{0,5}}$")


def has_address(text: str) -> bool:
    return bool(ADDRESS_RE.search(text or ""))


def names_a_person(text: str) -> bool:
    return bool(PERSON_LABEL_RE.search(text or ""))


def is_water_name(text: str) -> bool:
    """True for a cell that reads as a water's name ('Ward Creek', 'Clay Cut Bayou', 'Canal'); a cell that may be
    personal and cannot be told apart from one (a bare name, a number, a label) is not, and is withheld."""
    t = " ".join((text or "").split())
    return bool(WATER_NAME_RE.match(t)) and not has_address(t) and not names_a_person(t)
