"""Historical text normalization ONLY for identity and matching.

Frozen at e70b9758. Never use these functions for published record fields.
The public helpers in common preserve source text.
"""
import re
from common import (EMAIL_RE, CONTACT_DIGITS_RE, PHONE_RE, TITLE_NAME_RE, CONTACT_NAME_RE,
                    CLOSING_NAME_RE, RESIDENCE_NUMBER_RE, RESIDENCE_NUMBER_BEFORE_RE,
                    HOUSE_NUMBER_REMOVED, STREET_NUMBER_RE, ADDRESS_NUMBER_RE, ROUTE_BEFORE,
                    residence_numbers, _is_residence)

def scrub_text(v: str) -> str:
    """Emails and phone numbers inside free text become [email removed] / [phone removed] (a number typed without
    separators too, after a contact word); staff names after "Inspector" / "Investigator", and in "contact <Name> at",
    become [name removed]; the house number of an address tied to a residence or a resident becomes
    [house number removed] (scrub_residence_numbers)."""
    v = EMAIL_RE.sub("[email removed]", v)
    v = CONTACT_DIGITS_RE.sub(r"\1[phone removed]", v)
    return scrub_residence_numbers(scrub_names(PHONE_RE.sub("[phone removed]", v)))

def drop_house_numbers(v: str, pairs) -> str:
    """The house numbers of `pairs` (residence_numbers) removed wherever they stand before the same street word."""
    for n, street in pairs:
        if street:
            v = re.sub(rf"(?<![\w.,/:-]){re.escape(n)}(?=[ ]{{1,2}}{re.escape(street)}\b)", HOUSE_NUMBER_REMOVED, v)
    return v

def scrub_residence_numbers(v: str) -> str:
    """House numbers tied to a residence or a resident become "[house number removed]" (RESIDENCE_NUMBER_RE), and so does
    the same number before the same street word elsewhere in the string ("cleanouts at 808 NW 39th Dr ... the customer at
    808 NW 39th Dr"); the street stays."""
    pairs = residence_numbers(v)
    if not pairs:
        return v
    v = RESIDENCE_NUMBER_RE.sub(lambda m: m.group(1) + HOUSE_NUMBER_REMOVED if _is_residence(m) else m.group(0), v)
    return drop_house_numbers(RESIDENCE_NUMBER_BEFORE_RE.sub(HOUSE_NUMBER_REMOVED, v), pairs)

def strip_house_numbers(v: str, street_word_only: bool = False) -> str:
    """Every street address's house number in v becomes "[house number removed]" (ADDRESS_NUMBER_RE; with
    street_word_only, only a number followed by a street word, STREET_NUMBER_RE: for a name that is a site's own, where
    "Site 3 North" or "- 41 Bridge" is the site and not an address)."""
    v = (STREET_NUMBER_RE if street_word_only else ADDRESS_NUMBER_RE).sub(lambda m: m.group(0) if ROUTE_BEFORE.search(v[max(0, m.start() - 14):m.start()])
                              else HOUSE_NUMBER_REMOVED, v)
    # the numbers listed before it ("the buildings at 226, 224 and 220 Sample Ave")
    return re.sub(rf"(?<![\w.,/:-])(?:\d{{1,6}}[A-Za-z]?[ ]{{0,2}}(?:,[ ]{{0,2}}(?:(?:and|&)[ ]{{1,2}})?|[ ]{{1,2}}(?:and|&)[ ]{{1,2}}))+"
                  rf"(?={re.escape(HOUSE_NUMBER_REMOVED)})", "", v)

def scrub_names(v: str) -> str:
    """Staff names after "Inspector" / "Investigator", in "contact <Name> at", and in a closing signature
    ("Very respectfully, <Name>, P.G.") become [name removed]."""
    v = TITLE_NAME_RE.sub(r"\1\2[name removed]", v)
    v = CONTACT_NAME_RE.sub(r"\1\2[name removed]", v)
    return CLOSING_NAME_RE.sub(r"\1[name removed]", v)

import string
from common import OPERATOR_WORDS, NAME_REMOVED

def scrub_discharger(rec: dict) -> dict:
    """A discharger_name that is only a person's name (build.redact.person_shaped, read as given and with capitals, as
    the Florida feed reads its incident and facility names) becomes "[name removed]": an owner field can hold a private
    owner's or filer's name (generic-ingesters re-check R8). The permit stays the operator's identity: a discharger_id
    that carries the name becomes the npdes_permit. A name with an operator word (OPERATOR_WORDS) is left as it is.
    Changes rec in place and returns it."""
    v = rec.get("discharger_name")
    if not isinstance(v, str) or not v.strip() or v == NAME_REMOVED:
        return rec
    s = " ".join(v.split())
    words = {w.lower() for w in re.split(r"[\s\-/.,()&']+", s) if w}
    if words & OPERATOR_WORDS:
        return rec
    import string

    from build import redact            # here, not at the top: build.redact imports this module
    if not (redact.person_shaped(s) or redact.person_shaped(string.capwords(s))):
        return rec
    rec["discharger_name"] = NAME_REMOVED
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    did = rec.get("discharger_id")
    if isinstance(did, str) and key and key in re.sub(r"[^a-z0-9]", "", did.lower()):
        rec["discharger_id"] = rec.get("npdes_permit")
    return rec
