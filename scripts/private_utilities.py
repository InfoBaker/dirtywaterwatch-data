"""Private sewer utilities, per state: every individually permitted sewage permit whose permittee is not a public body,
listed for the state builder who files them as operators like any other (registry rows, register rows, outfalls and
water records; North Carolina set the pattern: scripts/add_nc_operators.py, research/nc/private-utilities.json).

Usage: pipeline/.venv/bin/python -I scripts/private_utilities.py [--icis PATH] [--fetched-at ISO] [--dry-run]

Inputs
  - EPA ICIS-NPDES Discharge Points (ECHO npdes_outfalls_layer.zip, NPDES_OUTFALLS_LAYER.csv; the zip or the csv),
    the default being the newest data/raw/icis-npdes/<date>/npdes_outfalls_layer.(zip|csv) (git-ignored; fetch with
    curl -o data/raw/icis-npdes/<date>/npdes_outfalls_layer.zip
    https://echo.epa.gov/files/echodownloads/npdes_outfalls_layer.zip, about 50 MB). One row per permitted feature;
    the permit-level fields (facility name, permit name, city, county, facility type, permit type and status, SIC and
    NAICS codes, permit components, design flow) repeat on every row. Without it only the file below is read, which
    holds the private permits EPA marks with the POTW component and none of the others (research/federal/
    plant-outfalls.md section 2.8 left them out), and every output says so.
  - data/outfalls-plants-us.json: the plant permits already in the outfall registry (in_plant_registry), and its
    private-owner permits that only EPA's national dataset lists (the build's supplement rows).
  - data/dischargers.json and research/<st>/dischargers.json: a permit an operator row or a research row already holds
    (registry_row, research_row). research/<st>/federal-seed.json is derived from the plants file and carries no owner
    type, so it adds nothing here.

Rule (a permit is a candidate when all hold)
  - status Effective, Administratively Continued or Expired (EFF, ADC, EXP: ECHO counts all three as active);
  - individual permit (NPD, SIN); general-permit coverages (GPC: single homes and small systems) are left out;
  - sewage: SIC 4952 or NAICS 221320 among its codes (EPA separates several codes with spaces), or the permit
    component POTW; a permit whose components are all stormwater is left out;
  - the permittee is not a public body: EPA's facility type is Privately Owned Facility (POF), Corporation (COR) or
    Non-Government (NON) and the names do not read as a public body; or the type is Mixed Ownership, blank or unknown
    and the names read as a private body (owner_reading: a public body's own words in the permittee first, such as
    "Board of Education", "Dept of", a school district or "Co" for County; then a corporate form before a public word).
    A permit EPA types private whose name reads as a public body (a municipal utility district, a county, a tribe, a
    school district), and any permit whose permittee reads as both a public body and a company, is listed apart in
    public_by_name, for the builder to check against the permit: a public body filed as private is the error to avoid.

Privacy: these files are public. No address, ZIP or coordinate is copied (a small system's point is often a home).
A single-residence system keeps its permit and state only: no name, city, county or receiving water.
A name (facility or permittee) is kept only when it reads as a body: it has an organisation word (common.OPERATOR_WORDS
or ORG_WORDS) and is not a person's name by common.scrub_discharger; any other becomes "[name removed]" with the permit
kept. A single-residence system (SRSTP, SFTF, a street address as its name ...) has both names removed. A receiving
water that reads as a person's name is dropped. The builder takes the permittee from the state's permit documents
(as North Carolina did), never an individual's name.

Writes research/<st>/private-utilities-candidates.json for every state with a candidate or a public_by_name permit
(research/nh-vt/private-utilities-candidates-<st>.json for the two states researched together), and
research/federal/private-utilities-summary.json (per-state counts, the rule, the comparison with the 2,359 of
research/federal/plant-outfalls.md section 2.8). Prints the per-state counts and the national total.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))
from common import NAME_REMOVED, OPERATOR_WORDS, scrub_discharger  # noqa: E402

DATA = ROOT / "data"
RESEARCH = ROOT / "research"
RAW = DATA / "raw" / "icis-npdes"
SOURCE_ID = "fed-echo-npdes-discharge-points"
SUPP_SOURCE_ID = "fed-echo-icis-npdes-national-dataset"
SOURCE_URL = "https://echo.epa.gov/files/echodownloads/npdes_outfalls_layer.zip"
EARLIER_COUNT = 2359            # research/federal/plant-outfalls.md section 2.8

ACTIVE = {"EFF", "ADC", "EXP"}
INDIVIDUAL = {"NPD", "SIN"}
STORMWATER = {"Construction Stormwater", "Industrial Stormwater", "Urban Stormwater (Small MS4)",
              "Urban Stormwater (Medium/Large MS4)"}
SEWAGE_CODES = {"4952", "221320"}
PRIVATE_TYPES = {"POF": "Privately Owned Facility", "COR": "Corporation", "NON": "Non-Government"}
NAME_CHECK_TYPES = {"MXO", "", "UNK"}           # mixed, blank, unknown: the names decide
# the plants file gives the description only (ICIS national dataset types for the supplement rows)
PRIVATE_DESCS = {"Privately Owned Facility", "Corporation", "Non-Government"}
NAME_CHECK_DESCS = {"Mixed Ownership (e.g., Public/Private)", "NON-POTW", "", None}

# Organisation words beyond common.OPERATOR_WORDS that make a private permittee's name a body's (never surnames
# such as Park, Mills, Lake, Hill, Brooks, Camp or Lodge)
ORG_WORDS = set("""
assoc associa associates mgmt management communities community comm condominium condominiums condo condos townhomes
townhouses villas manor manors meadows acres woods hills heights shores gardens commons pines oaks springs terrace
plaza mall square preserve plantation colony brethren hutterian mennonite amish church churches chapel diocese
parish ministry council society institute army mission missions conference conf grounds retreat marina campus
industries industrial ind metals mining mine quarry refinery terminal railroad airport truck stop travel restaurant
restaurants cafe store stores market shopping casino lodging motor court courts rv koa ranch landing crossing
subdivisions sanitarium nursing care fac rehabilitation detention academy seminary isd wsc sud fwsd wcid mud pud
gp llp pllc pc plc lc lllp
""".split())

PUBLIC_RE = re.compile(
    r"^(city|town|village|borough|township|county|state|commonwealth|parish)\s+of\b|"
    r"\b(city|town|village|borough|township|parish)\s+of\b|\btownship\b|\btwp\b|\bcounty\b|\bmunicipal|"
    r"\bmuni\b|\bmud\b|\bm\.u\.d\.|\bpud\b|\bsud\b|\bfwsd\b|\bwcid\b|\bpsd\b|\bmsd\b|\bisd\b|\bcisd\b|"
    r"\b(utility|utilities|sanitary|sanitation|sewer|sewerage|water|improvement|service|reclamation|conservation|"
    r"school|fire|park|irrigation|levee|drainage|metropolitan|regional)\s+(district|dist)\b|\bpublic\s+(service|"
    r"utilit|works|school)|\bauthority\b|\bcommission\b|\bboard of (education|trustees|commissioners)\b|"
    r"\bdepartment of\b|\bdept\.? of\b|\bstate (park|university|college|prison|hospital|forest)\b|"
    r"\buniversity of\b|\bunited states\b|\bu\.?s\.? (army|navy|air force|forest service|coast guard|fish)|"
    r"\b(army|navy|air force|marine corps|national guard)\b|\bcorps of engineers\b|\bnational (park|forest|"
    r"wildlife)\b|\bfederal\b|\btribes?\b|\btribal\b|\bnation\b|\breservation\b|\bpueblo\b|\brancheria\b|"
    r"\bindian community\b|\bband of\b", re.I)
PRIVATE_RE = re.compile(
    r"\b(inc|llc|l\.l\.c|ltd|lp|l\.p|llp|company|co|companies|corp|corporation|assoc\w*|association|club|"
    r"communities|homeowners|home owners|property owners|poa|hoa|condominiums?|apartments?|apts|mhc|mhp|mobile home|"
    r"manufactured|rv|campground|resort|motel|hotel|inn|restaurant|church|ministries|mennonite|brethren|colony|"
    r"wsc|water supply corp\w*|utilities|utility|estates|subdivision|subdiv|village|partners|properties|"
    r"development|investments|holdings|enterprises|management|ranch|marina|camp)\b", re.I)
# a single-residence system: PA's small residential/small flow plants, a residence, a street address as the name
RESIDENCE_RE = re.compile(r"\b(srstp|srstf|sftf|sfstp|sftp|sfs|sfr|sfh|srs|res|residence|residential\s+(?:stp|"
                          r"system|treatment)|single[- ]family|single[- ]residence|homesite|dwelling|home\s+stp)\b",
                          re.I)
ADDRESS_RE = re.compile(r"^\s*\d+[a-z]?\s+(?:[nsew]\.?\s+)?[\w.' -]*\b(rd|road|ln|lane|st|street|dr|drive|ave|avenue|"
                        r"hwy|highway|pike|way|ct|court|blvd|cir|circle|run|trl|trail|pl|place|ter|route|rte|rt|sr|"
                        r"cr|pkwy|hollow|holw|xing)\b", re.I)
DBA_RE = re.compile(r"\b(?:d\s*/\s*b\s*/\s*a|dba|d\.b\.a\.?|t\s*/\s*a)\b", re.I)

LEGAL_FORM_HINTS = [   # (private legal form, words in either name): first match wins
    ("mobile-home park", re.compile(r"\b(mhp|mhc|mobile\s*home|manufactured|trailer|mh\s+park|mobile\s+(estates|"
                                    r"park|court|village|manor))\b", re.I)),
    ("campground or resort", re.compile(r"\b(rv|campground|camp\s*ground|camping|koa|resort|marina|travel\s+park|"
                                        r"recreation|lodge)\b", re.I)),
    ("homeowners' association", re.compile(r"\b(hoa|poa|homeowners|home\s+owners|property\s+owners|owners\s+assoc\w*|"
                                           r"condominiums?|condo|civic\s+assoc\w*|community\s+assoc\w*|"
                                           r"townhomes|townhouses)\b", re.I)),
    ("private club", re.compile(r"\b(club|golf)\b", re.I)),
    ("institution", re.compile(r"\b(school|academy|college|university|seminary|hospital|nursing|care\s+fac\w*|"
                               r"sanitarium|prison|correctional|detention|jail|church|chapel|ministr\w*|mennonite|"
                               r"brethren|hutterian|colony|monastery|abbey|bible|retreat|conference|conf|"
                               r"children|orphan|salvation)\b", re.I)),
    ("investor-owned utility", re.compile(r"\b(utilities|utility|wsc|water\s+supply\s+corp\w*|water\s+service|"
                                          r"sewer\s+(co|company|service|services|corp\w*|inc|llc)|sewage\s+(co|"
                                          r"company|corp\w*)|wastewater\s+(co|company|services|inc|llc)|"
                                          r"water\s+(co|company|corp\w*)|environmental\s+services|aqua|"
                                          r"sanitation\s+(co|company|inc|llc))\b", re.I)),
    ("business or industrial", re.compile(r"\b(inc|llc|l\.l\.c|ltd|lp|l\.p|corp|corporation|company|co|plant|mill|"
                                          r"mfg|manufacturing|industries|industrial|metals|mine|mining|quarry|"
                                          r"refinery|terminal|railroad|airport|truck\s+stop|travel\s+(center|plaza)|"
                                          r"restaurant|cafe|motel|hotel|inn|casino|store|market|shopping|plaza|"
                                          r"mall|foods|products|dairy|farms?)\b", re.I)),
]


# ------------------------------------------------------------------ names

def clean(v) -> str:
    return " ".join(str(v if v is not None else "").replace("\xa0", " ").split())


def words_of(name: str) -> set[str]:
    """Lower-case words of a name, with dotted abbreviations joined (L.L.C. -> llc, L.P. -> lp, M.U.D. -> mud)."""
    s = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), name)
    return {w.lower() for w in re.split(r"[\s\-/.,()&'#:;\"]+", s) if w}


def has_org_word(name: str) -> bool:
    return bool(words_of(name) & (OPERATOR_WORDS | ORG_WORDS))


def single_residence(*names) -> bool:
    return any(n and (RESIDENCE_RE.search(n) or ADDRESS_RE.search(n)) for n in names)


SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def person_like(text: str) -> bool:
    """A segment of a name that is a person's name: build.redact.person_shaped ("John Q Smith"), or two to four
    words (initials and Jr/Sr/II aside) with a common given name first or second ("Hector Smith", EPA's "SMITH JOHN Q")
    and no water or place word. Stricter than the redaction of free text: this file is public and a body's name
    has an organisation word."""
    from build import redact            # here, not at the top: build.redact imports common
    t = clean(text).strip(" ,.-&")
    if not t:
        return False
    if redact.person_shaped(t) or redact.person_shaped(t.title()):
        return True
    w = [x.lower() for x in re.split(r"[\s,.]+", t) if x]
    if not w or not all(re.fullmatch(r"[a-z'’-]+", x) for x in w):
        return False
    core = [x for x in w if len(x) > 1 and x not in SUFFIXES and x not in FUNCTION_WORDS]
    if not 2 <= len(core) <= 4 or any(x in redact.WATER_WORDS or x in redact.STATES or x in PLACE_LEADS
                                      or (x in redact.KILL and x not in SURNAME_PLACE_WORDS) for x in core):
        return False
    names = redact.FIRST_NAMES | GIVEN_EXTRA
    return core[0] in names or core[1] in names


# given names the shared list (build.redact.FIRST_NAMES) lacks, seen leading permittee names; never a word that is
# also a common noun or place (Ivy, Pearl, Ruby, Penny)
GIVEN_EXTRA = set("""
bessie bettye bubba butch chet cletus clyde dolly edna hattie irma jeb jethro leona lola lottie luella lula
mattie maude mavis mikey minnie myrtle nettie ollie ora orville renae riley roxie sadie sid thelma tillie velma
waylon winnie zelda
""".split())


PART_RE = re.compile(r"\s+-\s+|\s*[;()]\s*")             # parts of a name that stand alone: dropped one by one
SEGMENT_RE = re.compile(r"\s*[,/]\s*|\s+(?:and|&)\s+", re.I)   # parts joined into one name: a person removes all
CARE_OF_RE = re.compile(r"\s*,?\s*\b(?:c/o|attn:?|attention:?|care of)\s.*$", re.I)
FUNCTION_WORDS = {"and", "of", "the", "at", "on", "in", "for", "a", "an", "no", "nr", "&"}


def public_name(v) -> str | None:
    """The name as a public file may carry it: kept only when it reads as a body. A name after "d/b/a" stands for the
    whole; a segment (between " - ", ";", "/", brackets) that is a person's name is dropped; what is left is kept only
    when it has an organisation word (common.OPERATOR_WORDS, ORG_WORDS), is not a person's name by
    common.scrub_discharger, and is not a person's name with an organisation word added ("John Q Smith MHP"). A street
    address, a residence, "estate of", "et al" or a title (Mr, Mrs, Dr) removes the name. Any removed name is
    "[name removed]". None for a blank."""
    s = clean(v)
    if not s:
        return None
    parts = DBA_RE.split(s)
    if len(parts) > 1:                     # "John Q Public dba Sunny Acres MHP": the trade name only
        s = clean(parts[-1]).strip(" ,-")
        if not s:
            return NAME_REMOVED
    if ADDRESS_RE.search(s) or RESIDENCE_RE.search(s):
        return NAME_REMOVED
    if re.search(r"\bestate of\b|\bet\s?al\b|\bet\s?ux\b|\b(mr|mrs|ms|dr)\.?\s", s, re.I):
        return NAME_REMOVED
    s = CARE_OF_RE.sub("", s)             # "... Inc Attn <a person>", "... c/o <anyone>": the body only

    def personal(seg):
        return bool(seg) and not has_org_word(seg) and person_like(seg)

    # "<a person> - South Wind Water and Sewer Dist": a part that is a person's name is dropped
    parts = [x for x in PART_RE.split(s) if x and x.strip(" ,.-")]
    s = clean(" - ".join(x for x in parts if not personal(x)))
    # "Partners LP and <a person>", "<a person> & Son LLC": a person inside the name removes the name
    if not s or any(personal(seg) for seg in SEGMENT_RE.split(s)):
        return NAME_REMOVED
    if not s or not has_org_word(s):
        return NAME_REMOVED
    if scrub_discharger({"discharger_name": s})["discharger_name"] == NAME_REMOVED:
        return NAME_REMOVED
    # "John Q Smith MHP", "Smith John Q Trust": a person's name with an organisation word added
    rest = " ".join(w for w in re.split(r"[\s,]+", s)
                    if w and w.lower() not in FUNCTION_WORDS and not words_of(w) & (OPERATOR_WORDS | ORG_WORDS))
    if rest and person_like(rest):
        return NAME_REMOVED
    # "Quill Family LP", "Quill Family Trust", "Quill Trust": a family's or a person's own vehicle
    if family_vehicle(s) or personal_trust(s):
        return NAME_REMOVED
    # "Bill Quill Inc, Wild Bills No 4", "J T Quill & Sons", "Quill J T MHP": a person's name leading a part of the
    # name, whatever follows it (the check above sees only short names)
    if any(leading_person(seg) for seg in LEAD_SPLIT_RE.split(s) if seg):
        return NAME_REMOVED
    return s


LEAD_SPLIT_RE = re.compile(r"\s+-\s+|\s*[,;()/]\s*|\s+(?:and|&)\s+", re.I)
# words that end the leading run of a name: a body's, a place's or a street's word, a business word
BUSINESS_WORDS = {"operating", "operations", "group", "global", "international", "intl", "partnership", "rental",
                  "rentals", "investment", "investments", "ventures", "capital", "equities", "leasing", "trucking",
                  "trucklines", "health", "healthcare", "hb", "jewish", "christian", "catholic", "baptist",
                  "methodist", "lutheran", "presbyterian", "evangelical", "evan", "evang", "episcopal", "formerly", "aka",
                  "fka"}
# place words that are also surnames ("Thomas Park", "Mary Hall"): a person's name still
SURNAME_PLACE_WORDS = {"park", "hall", "mill", "mills", "bridge", "church", "court", "banks", "branch", "marsh", "row",
                       "tower", "towers", "farm", "farms", "garden", "gardens", "shore", "bay", "point", "way", "lane",
                       "isle", "pier", "dam", "neck", "brook", "ford", "field", "wood", "hill", "rink", "bank", "plaza",
                       "path", "ward", "chamber", "square", "store", "inn", "golf", "mall", "center", "centre", "alley",
                       "market", "tunnel", "wharf", "landing", "office", "terrace", "estates", "manor", "gardens"}
# words a place's name starts with ("San Jo", "La Sara", "Ville Marie", "Mt Pleasant"): never a given name's company
PLACE_LEADS = {"san", "santa", "santo", "la", "las", "los", "el", "le", "les", "de", "del", "du", "ville", "st",
               "ste", "saint", "mt", "mount", "ft", "fort", "port", "lake", "new", "old", "north", "south", "east",
               "west", "northeast", "northwest", "southeast", "southwest", "central", "upper", "lower", "camp"}
NSEW = {"n", "s", "e", "w"}
DOTTED_INITIALS_RE = re.compile(r"(?:[a-z]\.\s?){1,3}", re.I)
INITIAL_RE = re.compile(r"[a-z]\.?|(?:[a-z]\.){2,3}", re.I)       # "J", "J.", "J.T." (never "PA", "NB", "LA")


def _breaks(tok: str) -> bool:
    from build import redact
    lw = words_of(tok)
    return (not lw or bool(lw & (OPERATOR_WORDS | ORG_WORDS | BUSINESS_WORDS | redact.KILL | redact.WATER_WORDS))
            or bool(re.search(r"\d", tok)) or tok.lower() in FUNCTION_WORDS or tok.lower().strip(".") in
            {"us", "u.s", "usa"} or bool(PRIVATE_RE.fullmatch(tok.strip(".,'’"))
                                          or CORPORATE_RE.fullmatch(tok.strip(",'’"))))


def leading_person(seg: str) -> bool:
    """The words a part of a name starts with, up to its first body, place, street or business word, read as a
    person's name: a common given name first or second ("Bill Quill" Inc, "Carl Quill" Farms), or initials and one
    other word ("J T Quill" & Sons, "W.Y. Quill" LLC, "Quill J T" MHP; N, S, E, W alone are directions)."""
    run = []
    for t in clean(seg).split(" "):
        if not t:
            break
        bare = t.strip(",'’")
        corporate = PRIVATE_RE.fullmatch(bare.strip(".")) or CORPORATE_RE.fullmatch(bare)
        if corporate or bare.lower().replace(".", "") in {"us", "usa"} or (run and run[-1].strip(".").lower() == "u"
                                                                             and bare.strip(".").lower() == "s") or (
                not DOTTED_INITIALS_RE.fullmatch(bare) and _breaks(t)):
            break
        run.append(t)
    if len(run) < 2:
        return False
    if person_like(" ".join(run[:2])) or (len(run) >= 3 and person_like(" ".join(run[:3]))):
        return True
    if len(run) > 3:
        return False
    def letters(toks):              # how many initials the words are, or 0 when one is not an initial
        if not toks or not all(INITIAL_RE.fullmatch(t) for t in toks):
            return 0
        n = sum(len(t.replace(".", "")) for t in toks)
        return 0 if n == 1 and toks[0].lower().strip(".") in NSEW else n

    def word_ok(t):
        return len(t.strip(".")) > 2 and not INITIAL_RE.fullmatch(t) and t.lower() not in PLACE_LEADS

    # "J T Quill", "W.Y. Quill" (initials first); "Quill J T" MHP (EPA's order: two initials, and a word after them,
    # so a cut-off "Sawgrass P" or a "Rafter A" brand is not read as a person)
    followed = len(clean(seg).split(" ")) > len(run)
    return bool((letters(run[:-1]) and word_ok(run[-1]))
                or (word_ok(run[0]) and letters(run[1:]) >= 2 and followed))


FAMILY_RE = re.compile(r"^\s*(?:the\s+)?((?:[a-z'’.-]+\s+){1,2})family\s+(?:([a-z'’.-]+)\s+)?(trust|l\.?\s?l?\.?\s?p\.?|"
                       r"ltd|limited|partnership|partners|company|co|llc|l\.l\.c\.?|inc|holdings|investments|"
                       r"properties|farms?|enterprises)\b", re.I)
TRUST_RE = re.compile(r"\btrust\b", re.I)
TRUST_WORDS = {"trust", "family", "revocable", "irrevocable", "living", "the", "of", "and", "dated", "dtd", "u", "a"}


def family_vehicle(s: str) -> bool:
    """"Quill Family LP", "Quill Family Houston LLC", "Quill Family Trust": a family's own company or trust. Not a
    family campground or village ("Example Family Campground LLC")."""
    m = FAMILY_RE.search(s)
    if not m:
        return False
    lead, mid = m.group(1).split(), m.group(2)
    if any(_breaks(w) for w in lead):
        return False
    if mid and CORPORATE_RE.fullmatch(mid):           # "Quill Family Ltd Partnership"
        return True
    return not (mid and (_breaks(mid) or any(rx.search(mid) for _, rx in LEGAL_FORM_HINTS[:5])))


def personal_trust(s: str) -> bool:
    """A trust with no body's or place's word beside it ("Quill Trust", "Maranthony Trust") is a person's trust; an
    environmental response trust at a facility keeps its name."""
    if not TRUST_RE.search(s):
        return False
    others = [w for w in words_of(s) if w not in TRUST_WORDS and not CORPORATE_RE.fullmatch(w)]
    return not any(_breaks(w) for w in others)


CORPORATE_RE = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|lp|l\.p|llp|pllc|corp|corporation|company|companies|co|assoc\w*|"
    r"association|poa|hoa|homeowners|property\s+own\w*|club|church|ministries|scouts|wsc|"
    r"water supply corp\w*)\b\.?", re.I)


# "Fulton Co-Cauley Crk", "Colbert Co BOE", "Geauga Co Comm Dept", "Crawford Co. Jr/Sr High": "Co" for County, not
# Company (never after a business word: "Example Water Co-Sunrise", "Example Banking Co.")
COUNTY_CO_RE = re.compile(
    r"\b(?!(?:sewer|sewage|water|utility|utilities|wastewater|oil|gas|power|light|electric|development|dev|product|"
    r"products|banking|bank|supply|construction|realty|land|service|services|operating|fabrication|paper|chemical|"
    r"chemicals|manufacturing|mfg|lumber|coal|mining|investment|investments|ranch|cattle|trucking|sand|gravel|stone|"
    r"brick|ice|fuel|farm|farms|dairy|feed|seed|grain|telephone|mobile|home|homes|park|sons|brothers|bros|and|&)\b)"
    r"([a-z]+)\s+co\b\.?(?=\s*(?:[-/]|boe\b|board\b|bd\b|bos\b|comm\w*\b|dept\b|jr\b|sr\b|high\b|"
    r"school\b|sch\w*\b))", re.I)
SCHOOL_CORP_RE = re.compile(r"\bschool\s+corp(?:oration)?\b\.?|\bcommunity\s+schools?\s+corp(?:oration)?\b\.?",
                            re.I)              # Indiana's public school corporations
# a public body's own words, read in the permittee before its corporate form: a permittee with both is listed for a
# check (public_by_name), never filed as private
STRONG_PUBLIC_RE = re.compile(
    r"\b(city|town|village|borough|township|county)\s+of\b|\bboard\s+of\s+(education|supervisors|commissioners|"
    r"trustees)\b|\bboe\b|\b(dept\.?|department)\s+of\b|\bunified\s+gov|\bcounty\s+comm|\bschool\s+(district|dist|"
    r"board)\b|\br-?\s?[ivx0-9]+\s+school|\b(water|sewer|light|power|utilities|utility|public\s+works|"
    r"water\s+resources|wastewater)\s+(?:&\s+\w+\s+)?(dept|department)\b", re.I)


def public_words(name: str) -> str:
    """The name with "Co" for County and a school corporation spelled as a public body reads."""
    return SCHOOL_CORP_RE.sub("school district", COUNTY_CO_RE.sub(lambda m: m.group(1) + " County", clean(name)))


def owner_reading(facility, permittee) -> str | None:
    """How the names read: "private", "public", "mixed" or None. A public body's own words in the permittee (EPA's
    permit name: "Board of Education", "Dept of", "City of", a school district, "Unified Govt") read public, or
    "mixed" beside a corporate form; a permittee with no corporate form at a facility named by such words reads
    public. Otherwise the permittee first, then the facility; in each, a corporate or association form (CORPORATE_RE:
    Inc, LLC, Co, Association ...) reads private before a public word does ("Deer Trails Water District, LLC",
    "PA Amer Water Co" at "Exeter Twp STP"), then a public body's words (PUBLIC_RE), then a private body's
    (PRIVATE_RE). "Co" before a public body's word is County ("Fulton Co-Cauley Crk")."""
    p, f = public_words(permittee), public_words(facility)
    p_corp = bool(p and CORPORATE_RE.search(p))
    if p and STRONG_PUBLIC_RE.search(p):
        return "mixed" if p_corp else "public"
    if f and not p_corp and STRONG_PUBLIC_RE.search(f) and not CORPORATE_RE.search(f):
        return "public"
    for n in (p, f):
        if not n:
            continue
        if CORPORATE_RE.search(n):
            return "private"
        if PUBLIC_RE.search(n):
            return "public"
        if PRIVATE_RE.search(n):
            return "private"
    return None


def legal_form_hint(facility, permittee, residence: bool) -> str | None:
    """A proposed private legal form (docs/legal-forms.md) from the names as EPA records them; None when the names do
    not say (a subdivision, an apartment complex: the permit document does). The builder confirms it."""
    if residence:
        return "facility (permittee not named)"
    for form, rx in LEGAL_FORM_HINTS:
        if any(n and rx.search(n) for n in (permittee, facility)):
            return form
    return None


# ------------------------------------------------------------------ inputs

def codes(v) -> set[str]:
    """EPA's SIC_CODES / NAICS_CODES: several codes separated by spaces (or commas)."""
    return set(re.split(r"[\s,]+", clean(v))) - {""}


def components(v) -> list[str]:
    return [c.strip() for c in clean(v).split(",") if c.strip()]


def newest_icis() -> Path | None:
    found = sorted(RAW.glob("*/npdes_outfalls_layer.zip")) + sorted(RAW.glob("*/npdes_outfalls_layer.csv"))
    return max(found, key=lambda p: (p.parent.name, p.suffix == ".zip")) if found else None


def open_icis(path: Path) -> tuple[io.TextIOBase, str | None]:
    """(text stream of the csv, the file's own date inside the zip as YYYY-MM-DD, or None)."""
    if path.suffix.lower() == ".zip":
        z = zipfile.ZipFile(path)
        info = next(i for i in z.infolist() if i.filename.lower().endswith(".csv"))
        y, m, d = info.date_time[:3]
        return io.TextIOWrapper(z.open(info), encoding="utf-8", errors="replace", newline=""), f"{y:04d}-{m:02d}-{d:02d}"
    return open(path, encoding="utf-8", errors="replace", newline=""), None


def read_icis(stream) -> dict[str, dict]:
    """Permit -> its permit-level fields (from its first row) plus every row's receiving water and the count of its
    external outfalls. Only the fields named here are read; the address, ZIP and coordinates are not kept."""
    perm: dict[str, dict] = {}
    for r in csv.DictReader(stream):
        p = clean(r.get("EXTERNAL_PERMIT_NMBR")).upper()
        if not p:
            continue
        e = perm.get(p)
        if e is None:
            e = perm[p] = {
                "permit": p, "facility": clean(r.get("FACILITY_NAME")), "permit_name": clean(r.get("PERMIT_NAME")),
                "state": clean(r.get("STATE_CODE")).upper(), "city": clean(r.get("CITY")) or None,
                "county": clean(r.get("FAC_COUNTY_NAME")) or None,
                "type_code": clean(r.get("FACILITY_TYPE_CODE")).upper(), "type": clean(r.get("FACILITY_TYPE_DESC")),
                "permit_type": clean(r.get("PERMIT_TYPE_CODE")).upper(),
                "status": clean(r.get("PERMIT_STATUS_CODE")).upper(),
                "sic": sorted(codes(r.get("SIC_CODES"))), "naics": sorted(codes(r.get("NAICS_CODES"))),
                "components": components(r.get("PERMIT_COMPONENTS")),
                "design_flow_mgd": num(r.get("TOTAL_DESIGN_FLOW_NMBR")),
                "major_minor": clean(r.get("MAJOR_MINOR_FLAG")) or None,
                "effective": us_date(r.get("PERMIT_EFFECTIVE_DATE")),
                "expiration": us_date(r.get("PERMIT_EXPIRATION_DATE")),
                "waters": [], "outfalls": set(),
            }
        w = clean(r.get("STATE_WATER_BODY_NAME"))
        if w and w.lower() not in {x.lower() for x in e["waters"]}:
            e["waters"].append(w)
        if clean(r.get("SUB_TYPE_DESC")) == "External Outfall" and clean(r.get("PERM_FEATURE_NMBR")):
            e["outfalls"].add(clean(r.get("PERM_FEATURE_NMBR")))
    return perm


def us_date(v) -> str | None:
    """EPA's MM/DD/YYYY as YYYY-MM-DD (None for a blank or another shape, which is kept as given)."""
    t = clean(v)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else (t or None)


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def plants_permits(plants: dict) -> dict[str, dict]:
    """Permit -> a record in read_icis's shape from data/outfalls-plants-us.json (its first row per permit)."""
    out: dict[str, dict] = {}
    for o in plants.get("outfalls", []):
        p = clean(o.get("npdes_permit")).upper()
        if not p:
            continue
        e = out.get(p)
        if e is None:
            e = out[p] = {
                "permit": p, "facility": clean(o.get("permittee")), "permit_name": clean(o.get("permit_name")),
                "state": clean(o.get("state")).upper(), "city": clean(o.get("city")) or None, "county": None,
                "type_code": None, "type": o.get("facility_type") or "", "permit_type": clean(o.get("permit_type")),
                "status": clean(o.get("permit_status")), "sic": [], "naics": [],
                "components": list(o.get("permit_components") or []), "design_flow_mgd": o.get("design_flow_mgd"),
                "major_minor": o.get("major_minor"), "effective": None, "expiration": None,
                "waters": [], "outfalls": set(), "source": o.get("source"), "plant_basis": o.get("plant_basis"),
            }
        w = clean(o.get("receiving_water_echo"))
        if w and w.lower() not in {x.lower() for x in e["waters"]}:
            e["waters"].append(w)
        if o.get("outfall"):
            e["outfalls"].add(str(o["outfall"]))
    return out


def permit_index(rows) -> dict[str, str]:
    """Permit -> the id of the row that holds it (npdes_permit or npdes_permits)."""
    idx = {}
    for r in rows:
        for p in [r.get("npdes_permit")] + list(r.get("npdes_permits") or []):
            if p:
                idx.setdefault(clean(p).upper(), r.get("id"))
    return idx


def research_rows() -> list[dict]:
    rows = []
    for f in sorted(RESEARCH.glob("*/dischargers.json")):
        d = json.loads(f.read_text())
        rows += d if isinstance(d, list) else [r for v in d.values() if isinstance(v, list) for r in v]
    return [r for r in rows if isinstance(r, dict)]


# ------------------------------------------------------------------ the rule

def classify(e: dict) -> tuple[str | None, str]:
    """("private", basis) | ("public_by_name", basis) | (None, why not). e is a read_icis / plants_permits record."""
    if e["status"] not in ACTIVE:
        return None, "not active"
    if e["permit_type"] not in INDIVIDUAL:
        return None, "not an individual permit"
    comps = set(e["components"])
    sewage = bool(set(e["sic"]) & SEWAGE_CODES or set(e["naics"]) & SEWAGE_CODES or "POTW" in comps
                  or e.get("plant_basis"))
    if not sewage:
        return None, "not a sewage permit"
    if comps and comps <= STORMWATER:
        return None, "stormwater-only permit"
    reading = owner_reading(e["facility"], e["permit_name"])
    code, desc = e.get("type_code"), e.get("type") or ""
    typed_private = code in PRIVATE_TYPES if code is not None else desc in PRIVATE_DESCS
    name_check = code in NAME_CHECK_TYPES if code is not None else desc in NAME_CHECK_DESCS
    if typed_private:
        if reading == "public":
            return "public_by_name", f"EPA facility type {desc or code}; the name reads as a public body"
        if reading == "mixed":
            return "public_by_name", f"EPA facility type {desc or code}; the name reads as a public body and a company"
        return "private", f"EPA facility type {desc or code}"
    if name_check:
        if reading == "private":
            return "private", f"EPA facility type {desc or 'blank'}; the name reads as a private body"
        if reading == "mixed":
            return "public_by_name", f"EPA facility type {desc or 'blank'}; the name reads as a public body and a company"
        return None, f"EPA facility type {desc or 'blank'}; the name does not read as a private body"
    return None, "public owner type"


def sewage_basis(e: dict) -> list[str]:
    """Why the permit counts as a sewage permit, in EPA's own codes."""
    out = []
    if "4952" in e["sic"]:
        out.append("SIC 4952 (sewerage systems)")
    if "221320" in e["naics"]:
        out.append("NAICS 221320 (sewage treatment facilities)")
    if "POTW" in e["components"]:
        out.append("permit component POTW")
    if e.get("plant_basis") and not out:
        out.append(f"outfall registry plant basis {e['plant_basis']}")
    return out


def industrial(e: dict) -> bool:
    """An industrial permit that also lists sewage treatment (a manufacturing, mining or power SIC code and not SIC
    4952): it may treat only its own staff's sewage, not serve the public; the builder checks."""
    def ind(c):
        return c.isdigit() and len(c) == 4 and (1000 <= int(c) <= 3999 or 4911 <= int(c) <= 4939)
    return "4952" not in e["sic"] and any(ind(c) for c in e["sic"])


def candidate(e: dict, basis: str, src: dict, registry: dict, research: dict, in_plants: set) -> dict:
    residence = single_residence(e["facility"], e["permit_name"])
    facility = NAME_REMOVED if residence else public_name(e["facility"])
    permittee = NAME_REMOVED if residence else public_name(e["permit_name"])
    from build import redact
    waters = [w for w in e["waters"] if not (redact.person_shaped(w) or redact.person_shaped(w.title()))]
    if residence:              # a home: the permit and the state only (its city, county and stream point to it)
        waters = []
    row = {
        "npdes_permit": e["permit"],
        "state": e["state"],
        "facility": facility,
        "permittee_as_recorded": permittee,
        "county": None if residence else e["county"],
        "city": None if residence else e["city"],
        "system_kind": "single residence" if residence else ("industrial permit with a sewage code"
                                                              if industrial(e) else None),
        "sewage_basis": sewage_basis(e),
        "legal_form_proposed": legal_form_hint(e["facility"], e["permit_name"], residence),
        "ownership": {"basis": basis, "facility_type": e.get("type") or None, "facility_type_code": e.get("type_code"),
                      **src},
        "permit_type": e["permit_type"],
        "permit_status": e["status"],
        "permit_components": e["components"],
        "sic_codes": e["sic"],
        "naics_codes": e["naics"],
        "design_flow_mgd": e["design_flow_mgd"],
        "major_minor": e["major_minor"],
        "permit_effective": e["effective"],
        "permit_expiration": e["expiration"],
        "receiving_waters_echo": waters,
        "external_outfalls": len(e["outfalls"]),
        "in_plant_registry": e["permit"] in in_plants,
        "registry_row": registry.get(e["permit"]),
        "research_row": research.get(e["permit"]),
        "echo_url": f"https://echo.epa.gov/effluent-charts#{e['permit']}",
    }
    return row


def build(icis: dict[str, dict] | None, icis_src: dict | None, plants: dict, registry_rows: list[dict],
          research: list[dict]) -> tuple[dict[str, dict], dict]:
    """(state -> {"candidates": [...], "public_by_name": [...]}, national summary counts)."""
    in_plants_rec = plants_permits(plants)
    in_plants = set(in_plants_rec)
    reg, res = permit_index(registry_rows), permit_index(research)
    plants_src = {"source": SOURCE_ID, "file": "data/outfalls-plants-us.json",
                  "fetched_at": plants.get("fetched_at")}
    by_state: dict[str, dict] = defaultdict(lambda: {"candidates": [], "public_by_name": []})
    why = Counter()
    gap = Counter()
    seen = set()

    def take(e, src):
        kind, basis = classify(e)
        why[(kind or "skipped") + ": " + basis] += 1
        if kind is None:
            return
        row = candidate(e, basis, src, reg, res, in_plants)
        by_state[e["state"]][("candidates" if kind == "private" else "public_by_name")].append(row)
        gap[("candidate" if kind == "private" else "public by name") + ": " + gap_reason(e)] += 1

    for p, e in sorted((icis or {}).items()):
        seen.add(p)
        take(e, icis_src)
    for p, e in sorted(in_plants_rec.items()):
        if p in seen:
            continue
        src = dict(plants_src)
        if e.get("source") == SUPP_SOURCE_ID:
            src["source"] = SUPP_SOURCE_ID
        take(e, src)
    for v in by_state.values():
        v["candidates"].sort(key=lambda r: r["npdes_permit"])
        v["public_by_name"].sort(key=lambda r: r["npdes_permit"])
    return dict(by_state), {"why": why, "gap": gap}


def gap_reason(e: dict) -> str:
    """Where a candidate stands against the 2,359 of research/federal/plant-outfalls.md section 2.8, whose build split
    the SIC/NAICS field on commas only (so a permit with several space-separated codes was not seen as sewage)."""
    comps = set(e["components"])
    code = e.get("type_code")
    if code is None:
        return "private owner in the plants file (EPA's national dataset or POTW component): already in the outfall registry"
    if "POTW" in comps:
        return "POTW component with a private owner type: already in the outfall registry"
    if code not in PRIVATE_TYPES:
        return "owner type mixed or blank, the names decide"
    exact = (len(e["sic"]) == 1 and e["sic"][0] in SEWAGE_CODES) or (len(e["naics"]) == 1 and e["naics"][0] in SEWAGE_CODES)
    return "in the 2,359 (one sewage code)" if exact else "several codes, one of them sewage (missed by the comma split)"


# ------------------------------------------------------------------ output

RULE = ("An active (EFF, ADC, EXP) individual (NPD, SIN) NPDES permit that is a sewage permit (SIC 4952 or NAICS 221320 "
        "among its codes, or the POTW permit component; not stormwater-only) and whose permittee is not a public body: "
        "EPA's facility type Privately Owned Facility, Corporation or Non-Government with names that do not read as a "
        "public body, or a mixed, blank or unknown type with names that read as a private body.")
PRIVACY = ("No address, ZIP or coordinate is copied. A facility or permittee name is kept only when it reads as a body; "
           "any other is \"[name removed]\" with the permit kept. A single-residence system keeps its permit and "
           "state only: no name, city, county or receiving water. The permittee of record is taken from the state's "
           "permit documents, never an individual's name.")
FOR_BUILDER = ("Candidates for operator rows (data/dischargers.json), one per permittee: confirm the permittee and its "
               "legal form from the state's permit documents (legal_form_proposed is a hint from the names), group "
               "permits of one permittee, and file the register rows the state's law gives private operators. A permit "
               "in public_by_name is typed private by EPA but reads as a public body: check it before filing. "
               "registry_row or research_row set means the permit is already held.")


def state_doc(st: str, v: dict, sources: list[dict]) -> dict:
    c = v["candidates"]
    return {
        "state": st,
        "generated_by": "scripts/private_utilities.py",
        "sources": sources,
        "rule": RULE,
        "privacy": PRIVACY,
        "for_the_builder": FOR_BUILDER,
        "counts": {
            "candidates": len(c),
            "already_in_registry": sum(1 for r in c if r["registry_row"]),
            "in_research": sum(1 for r in c if r["research_row"] and not r["registry_row"]),
            "in_plant_outfall_registry": sum(1 for r in c if r["in_plant_registry"]),
            "single_residence": sum(1 for r in c if r["system_kind"] == "single residence"),
            "industrial_with_sewage_code": sum(1 for r in c if r["system_kind"] == "industrial permit with a sewage code"),
            "permittee_name_removed": sum(1 for r in c if r["permittee_as_recorded"] == NAME_REMOVED),
            "by_legal_form_proposed": dict(sorted(Counter(r["legal_form_proposed"] or "not stated by the names"
                                                          for r in c).items())),
            "public_by_name": len(v["public_by_name"]),
        },
        "candidates": c,
        "public_by_name": v["public_by_name"],
    }


SHARED_DIRS = {"NH": "nh-vt", "VT": "nh-vt"}     # states researched together


def state_file(st: str, root: Path = RESEARCH) -> Path:
    """research/<st>/private-utilities-candidates.json; in a directory two states share, one file per state."""
    if st in SHARED_DIRS:
        return root / SHARED_DIRS[st] / f"private-utilities-candidates-{st.lower()}.json"
    return root / st.lower() / "private-utilities-candidates.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--icis", help="npdes_outfalls_layer.zip or .csv (default: newest under data/raw/icis-npdes/)")
    ap.add_argument("--fetched-at", help="when the ICIS file was fetched (default: the file's modification time)")
    ap.add_argument("--plants", default=str(DATA / "outfalls-plants-us.json"), help="the plant outfall registry")
    ap.add_argument("--registry", default=str(DATA / "dischargers.json"), help="the operator registry")
    ap.add_argument("--out", default=str(RESEARCH), help="where the research/<st>/ files go (default research/)")
    ap.add_argument("--dry-run", action="store_true", help="print the counts, write nothing")
    a = ap.parse_args(argv)

    path = Path(a.icis) if a.icis else newest_icis()
    icis, icis_src = None, None
    if path and path.exists():
        stream, file_date = open_icis(path)
        with stream:
            icis = read_icis(stream)
        stamp = path.parent / "fetched_at.txt"          # written beside the download when it was fetched
        fetched = a.fetched_at or (stamp.read_text().strip() if stamp.exists() else None) or datetime.fromtimestamp(
            path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        icis_src = {"source": SOURCE_ID, "url": SOURCE_URL, "file_date": file_date or path.parent.name,
                    "fetched_at": fetched}
    else:
        print("!! no ICIS discharge-points file: only the private permits already in data/outfalls-plants-us.json are"
              " listed (see the docstring for the download)", file=sys.stderr)
    plants = json.loads(Path(a.plants).read_text())
    registry_rows = json.loads(Path(a.registry).read_text())
    out = Path(a.out)
    by_state, summ = build(icis, icis_src, plants, registry_rows, research_rows())

    sources = [s for s in (icis_src, {"source": SOURCE_ID, "file": "data/outfalls-plants-us.json",
                                      "fetched_at": plants.get("fetched_at"),
                                      "note": "the plant permits already in the outfall registry"}) if s]
    total = sum(len(v["candidates"]) for v in by_state.values())
    print(f"{'state':5} {'candidates':>10} {'in registry':>11} {'single res':>10} {'public by name':>14}")
    for st, v in sorted(by_state.items(), key=lambda kv: (-len(kv[1]["candidates"]), kv[0])):
        d = state_doc(st, v, sources)["counts"]
        print(f"{st:5} {d['candidates']:>10} {d['already_in_registry']:>11} {d['single_residence']:>10} "
              f"{d['public_by_name']:>14}")
    print(f"national: {total} candidates in {sum(1 for v in by_state.values() if v['candidates'])} states and "
          f"territories; {sum(len(v['public_by_name']) for v in by_state.values())} typed private but public by name")
    print(f"against the earlier {EARLIER_COUNT}:")
    for k, n in sorted(summ["gap"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:6}  {k}")

    if a.dry_run:
        return 0
    for st, v in sorted(by_state.items()):
        f = state_file(st, out)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(
            json.dumps(state_doc(st, v, sources), indent=1, ensure_ascii=False) + "\n")
    summary = {
        "generated_by": "scripts/private_utilities.py",
        "sources": sources,
        "rule": RULE,
        "privacy": PRIVACY,
        "national_candidates": total,
        "earlier_count": {"value": EARLIER_COUNT, "where": "research/federal/plant-outfalls.md section 2.8"},
        "against_earlier_count": dict(sorted(summ["gap"].items())),
        "by_state": {st: {"candidates": len(v["candidates"]), "public_by_name": len(v["public_by_name"]),
                          "single_residence": sum(1 for r in v["candidates"]
                                                  if r["system_kind"] == "single residence"),
                          "industrial_with_sewage_code": sum(1 for r in v["candidates"] if r["system_kind"] ==
                                                             "industrial permit with a sewage code"),
                          "already_in_registry": sum(1 for r in v["candidates"] if r["registry_row"])}
                     for st, v in sorted(by_state.items())},
        "decisions": dict(sorted((k, n) for k, n in summ["why"].items() if not k.startswith("skipped: not "))),
    }
    (out / "federal").mkdir(parents=True, exist_ok=True)
    (out / "federal" / "private-utilities-summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
